/**
 * Metis API Client — TypeScript adapter for the Metis Command FastAPI bridge.
 *
 * Connects any frontend (Next.js, Tauri, Acode) to the running Metis backend.
 * All authenticated routes use the local bearer token from identity/local_auth.token.
 *
 * Usage:
 *   import { MetisClient } from './metis-client';
 *   const metis = new MetisClient('http://127.0.0.1:7331', '<your-token>');
 *   const status = await metis.getStatus();
 *   for await (const ev of metis.chat('manager', 'build me a web scraper')) { ... }
 */

// ── Types ───────────────────────────────────────────────────────────────────

export interface MetisStatus {
  ok: boolean;
  version: string;
  generated_at_ms: number;
  latency_ms: number;
  ollama: { reachable: boolean; model_count: number };
  wallet: WalletSummary | null;
  brain: BrainStats | null;
  mission_pool: { max_workers: number; max_queue_depth: number; total_records: number } | null;
}

export interface WalletSummary {
  id: string;
  name: string;
  balance_cents: number;
  monthly_cap_cents: number;
  monthly_spent_cents: number;
  mode: string;
  policies: WalletPolicy[];
  month_key: string;
}

export interface WalletPolicy {
  id: string;
  category: string;
  max_per_day_cents: number | null;
  max_per_charge_cents: number | null;
  require_approval_above_cents: number | null;
  deny: boolean;
  note: string;
}

export interface LedgerEntry {
  id: string;
  category: string;
  cents: number;
  memo: string;
  subject: string;
  ts: string;
}

export interface BrainInfo {
  slug: string;
  name: string;
  [key: string]: unknown;
}

export interface BrainStats {
  [key: string]: unknown;
}

export interface AgentSpec {
  slug: string;
  name: string;
  role: string;
  system: string;
  wallet_category: string | null;
  tags: string[];
  persistent: boolean;
}

export interface Artifact {
  id: string;
  type: string;
  title: string;
  language?: string;
  path?: string;
  content?: string;
  metadata?: Record<string, unknown>;
}

export interface StreamEvent {
  type: 'token' | 'reasoning' | 'done';
  delta?: string;
  duration_ms?: number;
  tokens?: number;
}

export interface AuthUser {
  id: string;
  email: string;
  created_at?: string;
  user_metadata?: Record<string, unknown>;
}

export interface LocalTokenResult {
  token: string;
  type: 'local-install' | string;
}

function jwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split('.');
  if (parts.length !== 3 || parts.some((part) => !part)) return null;
  try {
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    return payload && typeof payload === 'object' ? payload as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function isUsableSupabaseAccessToken(token: string): boolean {
  const payload = jwtPayload(token);
  if (typeof payload?.sub !== 'string' || !payload.sub) return false;
  if (typeof payload.exp === 'number' && payload.exp <= Math.floor(Date.now() / 1000)) return false;
  return true;
}

export function shouldReplaceStoredToken(token: string | null, mode: string | null): boolean {
  if (!token) return true;
  if (mode === 'local-install') return false;
  return !isUsableSupabaseAccessToken(token);
}

// ── Client ──────────────────────────────────────────────────────────────────

export class MetisClient {
  private baseUrl: string;
  private token: string;

  constructor(baseUrl = 'http://127.0.0.1:7331', token = '') {
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.token = token;
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json', ...extra };
    if (this.token) h['Authorization'] = `Bearer ${this.token}`;
    return h;
  }

  private async get<T>(path: string): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, { headers: this.headers() });
    if (!res.ok) throw new Error(`Metis API ${path}: ${res.status} ${res.statusText}`);
    return res.json();
  }

  private async post<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Metis API ${path}: ${res.status} ${res.statusText}`);
    return res.json();
  }

  // ── Public routes (no auth) ─────────────────────────────────────────────

  async getVersion(): Promise<{ version: string }> {
    return this.get('/version');
  }

  async getHealth(): Promise<{ ok: boolean }> {
    return this.get('/health');
  }

  async getStatus(): Promise<MetisStatus> {
    return this.get('/status');
  }

  async getLocalToken(): Promise<LocalTokenResult> {
    const res = await fetch(`${this.baseUrl}/auth/local-token`, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`Metis API /auth/local-token: ${res.status} ${res.statusText}`);
    return res.json();
  }

  async getMe(): Promise<{ user: AuthUser }> {
    return this.get('/auth/me');
  }

  // ── Streaming chat (SSE) ────────────────────────────────────────────────

  async *chat(role: string, message: string, sessionId = 'default'): AsyncGenerator<StreamEvent> {
    const res = await fetch(`${this.baseUrl}/chat`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ session_id: sessionId, message, role }),
    });
    if (!res.ok) throw new Error(`Metis chat: ${res.status}`);
    if (!res.body) return;

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event: StreamEvent = JSON.parse(line.slice(6));
            yield event;
            if (event.type === 'done') return;
          } catch { /* skip malformed */ }
        }
      }
    }
  }

  // ── Wallet ──────────────────────────────────────────────────────────────

  async getWallet(): Promise<WalletSummary> {
    return this.get('/wallet');
  }

  async chargeWallet(category: string, cents: number, memo = ''): Promise<LedgerEntry> {
    return this.post('/wallet/charge', { category, cents, memo });
  }

  async topUpWallet(cents: number, source = 'frontend'): Promise<{ balance_cents: number }> {
    return this.post('/wallet/top_up', { cents, source });
  }

  async getWalletLedger(limit = 50): Promise<LedgerEntry[]> {
    return this.get(`/wallet/ledger?limit=${limit}`);
  }

  // ── Brains ──────────────────────────────────────────────────────────────

  async getBrains(): Promise<{ active: string | null; brains: BrainInfo[] }> {
    return this.get('/brains');
  }

  async switchBrain(slug: string): Promise<{ ok: boolean; active: string }> {
    return this.post('/brains/switch', { slug });
  }

  async remember(text: string, kind = 'semantic'): Promise<{ ok: boolean; id: string }> {
    return this.post('/brains/remember', { text, kind });
  }

  async recall(query: string, k = 5): Promise<unknown[]> {
    return this.get(`/brains/recall?q=${encodeURIComponent(query)}&k=${k}`);
  }

  // ── Agents ──────────────────────────────────────────────────────────────

  async getAgents(): Promise<{ agents: AgentSpec[]; persistent: string[] }> {
    return this.get('/agents');
  }

  async startAgent(slug: string): Promise<{ ok: boolean }> {
    return this.post(`/agents/${slug}/start`, {});
  }

  async stopAgent(slug: string): Promise<{ ok: boolean }> {
    return this.post(`/agents/${slug}/stop`, {});
  }

  async messageAgent(slug: string, payload: Record<string, unknown>, kind = 'prompt'): Promise<unknown> {
    return this.post(`/agents/${slug}/message`, { kind, payload });
  }

  // ── Memory search ───────────────────────────────────────────────────────

  async searchMemory(query: string, k = 5): Promise<unknown[]> {
    return this.get(`/memory/search?q=${encodeURIComponent(query)}&k=${k}`);
  }

  // ── Artifacts ───────────────────────────────────────────────────────────

  async getArtifacts(limit = 50): Promise<Artifact[]> {
    return this.get(`/artifacts?limit=${limit}`);
  }

  async getArtifact(id: string): Promise<Artifact> {
    return this.get(`/artifacts/${id}`);
  }

  // ── Skill forge ─────────────────────────────────────────────────────────

  async forgeSkill(goal: string): Promise<Artifact> {
    return this.post('/forge', { goal });
  }

  // ── Tier planning ───────────────────────────────────────────────────────

  async getTierPlan(tier: string): Promise<{
    tier: string;
    models: string[];
    missing: string[];
    present: string[];
    total_gb: number;
    missing_gb: number;
  }> {
    return this.get(`/tiers/plan?tier=${tier}`);
  }
}

// ── Convenience: auto-connect ───────────────────────────────────────────────

/**
 * Create a MetisClient pre-configured for a local Metis instance.
 * In a Tauri context, you'd read the token from the filesystem.
 * In a browser, you'd fetch it from an endpoint or localStorage.
 */
export function createLocalClient(token: string, port = 7331): MetisClient {
  return new MetisClient(`http://127.0.0.1:${port}`, token);
}
