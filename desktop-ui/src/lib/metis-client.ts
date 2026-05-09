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
  created_at?: number;
}

export interface StreamEvent {
  type:
    | 'token'
    | 'reasoning'
    | 'done'
    | 'heartbeat'
    | 'manager_identity'
    | 'manager_plan'
    | 'manager_synthesis'
    | 'agent_start'
    | 'agent_done'
    | 'session_title'
    | 'relationship_saved'
    | 'run_artifact_saved'
    | 'error';
  delta?: string;
  duration_ms?: number;
  tokens?: number;
  // relationship_saved
  id?: string;
  name?: string;
  title?: string;
  // generic passthrough — the SSE shape on the wire is wider than this type;
  // unknown fields are accepted so we never drop an event for being too rich.
  [key: string]: unknown;
}

export interface AuthUser {
  id: string;
  email: string;
  created_at?: string;
  user_metadata?: Record<string, unknown>;
}

export interface AuthSession {
  access_token: string;
  refresh_token?: string;
  expires_at?: number;
  token_type?: string;
}

export interface AuthResult {
  user: AuthUser | null;
  session: AuthSession | null;
}

export type OAuthProvider = 'google' | 'github';
export type RunMode = 'task' | 'job';
export type RunPermission = 'read' | 'balanced' | 'full';

export interface LocalTokenResult {
  token: string;
  setup_code?: string;
  type: string;
}

export interface SetupCodeResult {
  code: string;
  type: string;
}

export function normalizeSetupCode(code: string): string {
  const compact = code.trim().replace(/^["']|["']$/g, '').replace(/\s+/g, '');
  const prefix = 'metis-local:';
  return compact.toLowerCase().startsWith(prefix) ? compact.slice(prefix.length) : compact;
}

// ── Daily briefings ─────────────────────────────────────────────────────────

export interface BriefingSummary {
  date: string;            // YYYY-MM-DD
  filename: string;
  size: number;
  modified_at: number;     // unix seconds
  preview: string;         // first ~280 chars of markdown
}

export interface BriefingDetail {
  date: string;
  filename: string;
  content: string;         // full markdown body
}

// ── Memory ──────────────────────────────────────────────────────────────────

export interface MemoryHit {
  id?: string;
  text: string;
  kind?: 'episodic' | 'semantic' | 'procedural' | string;
  score?: number;
  meta?: Record<string, unknown>;
  // Some brains return additional fields like "source" or "ts" — keep open.
  [key: string]: unknown;
}

// ── Models + manager config ─────────────────────────────────────────────────

export interface AvailableModel {
  id: string;
  label: string;
  kind: 'local' | 'cloud';
  note?: string;
}

export interface ManagerConfig {
  user_id?: string;
  manager_name?: string;
  persona_key?: string;
  manager_persona?: string;
  manager_model?: string;
  company_name?: string;
  company_mission?: string;
  director_name?: string;
  director_about?: string;
  accent_color?: string;
  specialists?: string[];
  configured_at?: string;
}

// ── System health ──────────────────────────────────────────────────────────

export interface ProviderStatus {
  ok: boolean;
  reason?: string;
  fix?: string;
  model?: string;
  models?: number;
  destination?: string | null;
}

export interface SystemHealth {
  checked_at: number;
  ollama: ProviderStatus;
  groq:   ProviderStatus;
  glm:    ProviderStatus;
  openai: ProviderStatus;
  twilio: ProviderStatus;
  smtp:   ProviderStatus;
  preferred_manager: 'groq' | 'glm' | 'openai' | 'ollama' | null;
}

// ── Schedules ──────────────────────────────────────────────────────────────
// Mirror of scheduler.Schedule on the backend. Kind-specific spec format:
//   interval — minutes as a string ("60", "1440")
//   daily    — "HH:MM" 24-hour
//   once     — ISO timestamp
//   cron     — 5-field cron string

export type ScheduleKind = 'interval' | 'daily' | 'once' | 'cron';

export interface Schedule {
  id: string;
  kind: ScheduleKind;
  spec: string;
  goal: string;
  action: string;
  enabled: boolean;
  project_slug: string | null;
  auto_approve: boolean;
  notify: boolean;
  last_run: number | null;
  next_run: number | null;
  created_at: number;
}

export interface Mission {
  id: string;
  goal: string;
  status: 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | string;
  tag: string;
  project_slug?: string | null;
  auto_approve?: boolean;
  events?: Record<string, unknown>[];
  final_answer?: string;
  submitted_at?: number;
  started_at?: number | null;
  ended_at?: number | null;
}

export interface ScheduleRunResult {
  ok: boolean;
  id: string;
  status: string;
  mission_id?: string;
  action?: string;
  error?: string;
}

// ── Relationships ──────────────────────────────────────────────────────────

export interface Relationship {
  id: string;
  name: string;
  role?: string;
  company?: string;
  phone?: string;
  email?: string;
  notes?: string;
  tags?: string[];
  created_at?: string;
  // Open-ended extra fields the manager might attach (source URL, links).
  [key: string]: unknown;
}

export interface RelationshipInput {
  name: string;
  role?: string;
  company?: string;
  phone?: string;
  email?: string;
  notes?: string;
  tags?: string[];
}

// ── Inbox ──────────────────────────────────────────────────────────────────

export interface InboxItem {
  id: string;
  title: string;
  body: string;
  source: string;          // e.g. "schedule:abc123" or "agent:manager"
  created_at: string;      // ISO
  read: boolean;
  // Optional structured link to the source artifact.
  schedule_id?: string;
  relationship_id?: string;
  artifact_id?: string;
}

export interface NotificationItem {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error' | 'agent' | string;
  title: string;
  body: string;
  read: boolean;
  created_at: string;
  [key: string]: unknown;
}

export interface SessionMeta {
  id: string;
  title: string;
  updated_at: string;
}

export interface SessionMessage {
  role: 'user' | 'assistant' | 'agent' | string;
  content: string;
  created_at: string;
}

export interface SessionSearchResult {
  session_id: string;
  session_title: string;
  role: string;
  created_at: string;
  snippet: string;
}

// ── Analytics ─────────────────────────────────────────────────────────────

export interface AnalyticsSummary {
  generated_at: string;
  sessions: { total: number; active_last_7d: number };
  missions: { total: number; success: number; failed: number; by_status: Record<string, number> };
  schedules: { total: number; active: number };
  inbox: { total: number; unread: number };
  tokens: { calls: number; total: number; cost_usd: number; by_model: Record<string, { calls: number; tokens_in: number; tokens_out: number; cost: number }> };
  wallet: { spent_cents: number; cap_cents: number };
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

  async getSystemHealth(): Promise<SystemHealth> {
    return this.get('/system/health');
  }

  async listModels(): Promise<{ models: AvailableModel[] }> {
    return this.get('/models');
  }

  async getManagerConfig(): Promise<{ config: ManagerConfig; is_configured: boolean }> {
    return this.get('/manager/config');
  }

  async setManagerConfig(updates: Partial<ManagerConfig>): Promise<{ config: ManagerConfig; is_configured: boolean }> {
    return this.post('/manager/config', updates);
  }

  // ── Streaming chat (SSE) ────────────────────────────────────────────────

  async *chat(
    role: string,
    message: string,
    sessionId = 'default',
    options: {
      mode?: RunMode;
      permission?: RunPermission;
      // MVP 8: per-turn overrides. Win over saved manager_config.
      model?: string;
      temperature?: number;
    } = {},
  ): AsyncGenerator<StreamEvent> {
    const res = await fetch(`${this.baseUrl}/chat`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({
        session_id: sessionId,
        message,
        role,
        mode: options.mode ?? 'task',
        permission: options.permission ?? 'balanced',
        ...(options.model       ? { model: options.model } : {}),
        ...(options.temperature !== undefined ? { temperature: options.temperature } : {}),
      }),
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

  async recall(query: string, k = 5): Promise<MemoryHit[]> {
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

  async searchSessions(query: string, limit = 20): Promise<SessionSearchResult[]> {
    return this.get(`/sessions/search?q=${encodeURIComponent(query)}&limit=${limit}`);
  }

  async loadSession(id: string, limit = 200): Promise<SessionMessage[]> {
    return this.get(`/sessions/${encodeURIComponent(id)}?limit=${limit}`);
  }

  // ── Artifacts ───────────────────────────────────────────────────────────

  async getArtifacts(limit = 50): Promise<Artifact[]> {
    return this.get(`/artifacts?limit=${limit}`);
  }

  async getArtifact(id: string): Promise<Artifact> {
    return this.get(`/artifacts/${id}`);
  }

  async deleteArtifact(id: string): Promise<{ ok: boolean; id: string }> {
    const res = await fetch(`${this.baseUrl}/artifacts/${id}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`delete artifact: ${res.status}`);
    return res.json();
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

  // ── Schedules ───────────────────────────────────────────────────────────

  async listSchedules(): Promise<Schedule[]> {
    return this.get('/schedules');
  }

  async createSchedule(input: {
    goal: string;
    kind: ScheduleKind;
    spec: string;
    auto_approve?: boolean;
    project_slug?: string | null;
    action?: string;
    notify?: boolean;
    mode?: RunMode;
    permission?: RunPermission;
  }): Promise<Schedule> {
    return this.post('/schedules', {
      goal: input.goal,
      kind: input.kind,
      spec: input.spec,
      auto_approve: input.auto_approve ?? true,
      project_slug: input.project_slug ?? null,
      action: input.action ?? '',
      notify: input.notify ?? false,
      mode: input.mode ?? 'job',
      permission: input.permission ?? 'balanced',
    });
  }

  async deleteSchedule(id: string): Promise<{ ok: boolean; id: string }> {
    const res = await fetch(`${this.baseUrl}/schedules/${id}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`delete schedule: ${res.status}`);
    return res.json();
  }

  async toggleSchedule(id: string): Promise<{ enabled: boolean; id: string }> {
    return this.post(`/schedules/${id}/toggle`, {});
  }

  async runScheduleNow(id: string): Promise<ScheduleRunResult> {
    return this.post(`/schedules/${id}/run`, {});
  }

  async listMissions(limit = 50): Promise<Mission[]> {
    return this.get(`/missions?limit=${limit}`);
  }

  async getMission(id: string): Promise<Mission> {
    return this.get(`/missions/${id}`);
  }

  async cancelMission(id: string): Promise<{ ok: boolean; id: string }> {
    return this.post(`/missions/${id}/cancel`, {});
  }

  // ── Relationships ───────────────────────────────────────────────────────

  async listRelationships(): Promise<Relationship[]> {
    return this.get('/relationships');
  }

  async getRelationship(id: string): Promise<Relationship> {
    return this.get(`/relationships/${id}`);
  }

  async createRelationship(input: RelationshipInput): Promise<Relationship> {
    return this.post('/relationships', {
      name: input.name,
      role: input.role || '',
      company: input.company || '',
      phone: input.phone || '',
      email: input.email || '',
      notes: input.notes || '',
      tags: input.tags || [],
    });
  }

  async deleteRelationship(id: string): Promise<{ ok: boolean; id: string }> {
    const res = await fetch(`${this.baseUrl}/relationships/${id}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`delete relationship: ${res.status}`);
    return res.json();
  }

  // ── Inbox ───────────────────────────────────────────────────────────────

  async listInbox(): Promise<InboxItem[]> {
    return this.get('/inbox');
  }

  async markInboxRead(id: string): Promise<{ ok: boolean; id: string }> {
    return this.post(`/inbox/${id}/read`, {});
  }

  async deleteInbox(id: string): Promise<{ ok: boolean; id: string }> {
    const res = await fetch(`${this.baseUrl}/inbox/${id}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`delete inbox: ${res.status}`);
    return res.json();
  }

  async clearInbox(): Promise<{ ok: boolean; cleared: number }> {
    const res = await fetch(`${this.baseUrl}/inbox`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`clear inbox: ${res.status}`);
    return res.json();
  }

  async listNotifications(unreadOnly = false, limit = 50): Promise<NotificationItem[]> {
    return this.get(`/notifications?limit=${limit}&unread_only=${unreadOnly ? 'true' : 'false'}`);
  }

  async getNotificationCount(): Promise<{ unread: number }> {
    return this.get('/notifications/count');
  }

  async markNotificationRead(id: string): Promise<{ ok: boolean; id: string }> {
    return this.post(`/notifications/${id}/read`, {});
  }

  async markAllNotificationsRead(): Promise<{ ok: boolean; marked: number }> {
    return this.post('/notifications/read-all', {});
  }

  async clearNotifications(): Promise<{ ok: boolean; cleared: number }> {
    const res = await fetch(`${this.baseUrl}/notifications`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`clear notifications: ${res.status}`);
    return res.json();
  }

  async deleteNotification(id: string): Promise<{ ok: boolean; id: string }> {
    const res = await fetch(`${this.baseUrl}/notifications/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: this.headers(),
    });
    if (!res.ok) throw new Error(`delete notification: ${res.status}`);
    return res.json();
  }

  // ── Daily briefings ─────────────────────────────────────────────────────

  async listBriefings(): Promise<BriefingSummary[]> {
    return this.get('/briefings');
  }

  async getBriefing(date: string): Promise<BriefingDetail> {
    return this.get(`/briefings/${encodeURIComponent(date)}`);
  }

  async runBriefingNow(): Promise<{ ok: boolean; status: string }> {
    return this.post('/briefings/run', {});
  }

  // ── Analytics ────────────────────────────────────────────────────────────

  async getAnalytics(): Promise<AnalyticsSummary> {
    return this.get('/analytics');
  }

  // ── Auth ────────────────────────────────────────────────────────────────
  // These do NOT include the bearer token (sign-in is the bearer-issuer).
  // The bridge serves the local-install token endpoint at 127.0.0.1 only.

  private async postNoAuth<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      const msg = (detail && (detail.detail || detail.message)) || `${res.status} ${res.statusText}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return res.json();
  }

  async getLocalToken(): Promise<LocalTokenResult> {
    const res = await fetch(`${this.baseUrl}/auth/local-token`, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`local-token: ${res.status}`);
    return res.json();
  }

  async getSetupCode(): Promise<SetupCodeResult> {
    const res = await fetch(`${this.baseUrl}/auth/setup-code`, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`setup-code: ${res.status}`);
    return res.json();
  }

  async signIn(email: string, password: string): Promise<AuthResult> {
    return this.postNoAuth('/auth/signin', { email, password });
  }

  async signUp(email: string, password: string): Promise<AuthResult> {
    return this.postNoAuth('/auth/signup', { email, password });
  }

  async oauthStart(provider: OAuthProvider, redirectTo: string): Promise<{ url: string }> {
    return this.postNoAuth('/auth/oauth/start', { provider, redirect_to: redirectTo });
  }

  async oauthComplete(code: string, state?: string): Promise<AuthResult> {
    return this.postNoAuth('/auth/oauth/complete', { code, state });
  }

  async getMe(): Promise<{ user: AuthUser }> {
    return this.get('/auth/me');
  }

  async signOut(): Promise<{ ok: boolean }> {
    return this.post('/auth/signout', {});
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
