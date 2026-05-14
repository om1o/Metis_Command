/**
 * Metis API client — talks to the FastAPI backend on the same origin.
 * Stores the Supabase access_token in localStorage and attaches it as
 * `Authorization: Bearer <token>` on every authenticated request.
 */

const TOKEN_KEY = 'metis.access_token';
const REFRESH_KEY = 'metis.refresh_token';
const USER_KEY = 'metis.user';
const MODE_KEY = 'metis.auth_mode';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export function setSession(session, user) {
  if (session?.access_token) localStorage.setItem(TOKEN_KEY, session.access_token);
  if (session?.refresh_token) localStorage.setItem(REFRESH_KEY, session.refresh_token);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  if (session?.token_type === 'local-install') localStorage.setItem(MODE_KEY, 'local-install');
  else if (session?.access_token) localStorage.setItem(MODE_KEY, 'supabase');
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(MODE_KEY);
}

function jwtPayload(token) {
  const parts = String(token || '').split('.');
  if (parts.length !== 3 || parts.some((p) => !p)) return null;
  try {
    const json = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
    const payload = JSON.parse(json);
    return payload && typeof payload === 'object' ? payload : null;
  } catch {
    return null;
  }
}

function isUsableSupabaseToken(token) {
  const payload = jwtPayload(token);
  if (!payload?.sub) return false;
  if (typeof payload.exp === 'number' && payload.exp <= Math.floor(Date.now() / 1000)) return false;
  return true;
}

export function shouldReplaceStoredToken(token = getToken()) {
  if (!token) return true;
  if (localStorage.getItem(MODE_KEY) === 'local-install') return false;
  return !isUsableSupabaseToken(token);
}

export async function bootstrapLocalSession() {
  const res = await fetch('/auth/local-token', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`local-token: ${res.status}`);
  const data = await res.json();
  if (!data?.token) throw new Error('local-token: missing token');
  const user = {
    id: 'local-install',
    email: 'operator@local',
    user_metadata: { local_install: true },
  };
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.setItem(MODE_KEY, 'local-install');
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  return user;
}

async function _fetch(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = j.detail || j.error?.message || detail;
    } catch {}
    const err = new Error(detail);
    err.status = r.status;
    throw err;
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return r.json();
  return r.text();
}

export const api = {
  // Auth
  signup: (email, password) => _fetch('/auth/signup', { method: 'POST', body: JSON.stringify({ email, password }) }),
  signin: (email, password) => _fetch('/auth/signin', { method: 'POST', body: JSON.stringify({ email, password }) }),
  signout: () => _fetch('/auth/signout', { method: 'POST' }),
  me: () => _fetch('/auth/me'),
  oauthStart: (provider, redirect_to) => _fetch('/auth/oauth/start', {
    method: 'POST',
    body: JSON.stringify({ provider, redirect_to }),
  }),
  oauthComplete: (code, state) => _fetch('/auth/oauth/complete', {
    method: 'POST',
    body: JSON.stringify({ code, state }),
  }),
  resetPassword: (email) => _fetch('/auth/reset_password', {
    method: 'POST',
    body: JSON.stringify({ email }),
  }),

  // App
  status: () => _fetch('/status'),
  brains: () => _fetch('/brains'),
  switchBrain: (slug) => _fetch('/brains/switch', { method: 'POST', body: JSON.stringify({ slug }) }),
  agents: () => _fetch('/agents'),
  wallet: () => _fetch('/wallet'),
  walletLedger: (limit = 50) => _fetch(`/wallet/ledger?limit=${limit}`),
  schedules: () => _fetch('/schedules'),
  createSchedule: (data) => _fetch('/schedules', { method: 'POST', body: JSON.stringify(data) }),
  deleteSchedule: (id) => _fetch(`/schedules/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  toggleSchedule: (id) => _fetch(`/schedules/${encodeURIComponent(id)}/toggle`, { method: 'POST' }),
  runScheduleNow: (id) => _fetch(`/schedules/${encodeURIComponent(id)}/run`, { method: 'POST' }),
  automationEvents: (limit = 100, scheduleId = '') => _fetch(`/automation-events?limit=${limit}${scheduleId ? `&schedule_id=${encodeURIComponent(scheduleId)}` : ''}`),
  marketplace: () => _fetch('/marketplace'),
  installPlugin: (slug) => _fetch('/marketplace/install', {
    method: 'POST',
    body: JSON.stringify({ slug }),
  }),
  skills: () => _fetch('/skills'),
  artifacts: (limit = 50) => _fetch(`/artifacts?limit=${limit}`),
  sessions: () => _fetch('/sessions'),
  sessionMessages: (id) => _fetch(`/sessions/${encodeURIComponent(id)}`),
  deleteSession: (id) => _fetch(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  renameSession: (id, title) => _fetch(`/sessions/${encodeURIComponent(id)}/rename`, {
    method: 'POST', body: JSON.stringify({ title }),
  }),

  // Manager configuration + available models
  managerConfig: () => _fetch('/manager/config'),
  saveManagerConfig: (updates) => _fetch('/manager/config', {
    method: 'POST', body: JSON.stringify(updates || {}),
  }),
  models: () => _fetch('/models'),

  // Browser operator
  browserStatus: () => _fetch('/browser/status'),
  browserOpen: (headless = false) => _fetch('/browser/open', {
    method: 'POST',
    body: JSON.stringify({ headless }),
  }),
  browserClose: () => _fetch('/browser/close', { method: 'POST' }),
  browserNavigate: (url) => _fetch('/browser/navigate', {
    method: 'POST',
    body: JSON.stringify({ url }),
  }),
  browserScreenshot: () => _fetch('/browser/screenshot'),
  browserFill: (selector, value, secret = false) => _fetch('/browser/fill', {
    method: 'POST',
    body: JSON.stringify({ selector, value, secret }),
  }),
  browserClick: (selector) => _fetch('/browser/click', {
    method: 'POST',
    body: JSON.stringify({ selector }),
  }),
  browserWait: (selector, timeout_ms = 10000) => _fetch('/browser/wait', {
    method: 'POST',
    body: JSON.stringify({ selector, timeout_ms }),
  }),
  browserAudit: (limit = 50) => _fetch(`/browser/audit?limit=${limit}`),
  browserApprovals: () => _fetch('/browser/approvals'),
  approveBrowserAction: (id) => _fetch(`/browser/approvals/${encodeURIComponent(id)}/approve`, { method: 'POST' }),
  denyBrowserAction: (id) => _fetch(`/browser/approvals/${encodeURIComponent(id)}/deny`, { method: 'POST' }),
  browserSessionMode: (mode, job_label = '') => _fetch('/browser/session-mode', {
    method: 'POST',
    body: JSON.stringify({ mode, job_label }),
  }),
  browserServices: () => _fetch('/browser/services'),
  addBrowserService: (payload) => _fetch('/browser/services', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  patchBrowserService: (id, payload) => _fetch(`/browser/services/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }),

  // Agent health
  agentHealth: () => _fetch('/agents/health'),
  notifyStatus: () => _fetch('/notify/status'),

  // Relationships
  relationships: () => _fetch('/relationships'),
  createRelationship: (data) => _fetch('/relationships', { method: 'POST', body: JSON.stringify(data) }),
  deleteRelationship: (id) => _fetch(`/relationships/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // Ollama auto-management + model warmup
  ollamaStatus: () => _fetch('/ollama/status'),
  ollamaStart: () => _fetch('/ollama/start', { method: 'POST' }),
  warmupModel: (modelId) => _fetch('/models/warmup', {
    method: 'POST',
    body: JSON.stringify({ model: modelId }),
  }),

  // Web search
  searchWeb: (query, limit = 5) => _fetch('/search/web', {
    method: 'POST',
    body: JSON.stringify({ query, limit }),
  }),

  // File upload + extract
  analyzeFile: async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    const token = getToken();
    const r = await fetch('/files/analyze', {
      method: 'POST',
      headers: token ? { 'Authorization': `Bearer ${token}` } : {},
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  // Media generation
  generateImage: (prompt, opts = {}) => _fetch('/generate/image', {
    method: 'POST',
    body: JSON.stringify({ prompt, width: opts.width || 1024, height: opts.height || 1024, style: opts.style || '' }),
  }),
  generateVideo: (prompt, opts = {}) => _fetch('/generate/video', {
    method: 'POST',
    body: JSON.stringify({ prompt, duration: opts.duration || 4 }),
  }),

  // Streaming chat (Server-Sent Events)
  // `extra` is a Group-6 hook that piggybacks per-call fields onto the
  // POST body — currently agents_md_overrides + director_answer +
  // director_answer_for. Existing callers stay backward-compatible.
  chatStream: async function* (sessionId, message, role = 'manager', signal, direct = false, extra = {}) {
    const token = getToken();
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ session_id: sessionId, message, role, direct, ...(extra || {}) }),
      signal,
    });
    if (!r.ok || !r.body) {
      let detail = r.statusText;
      try { const j = await r.json(); detail = j.detail || detail; } catch {}
      throw new Error(`Chat failed: ${detail}`);
    }
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) !== -1) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        // SSE: lines like "event: close" / "data: {...}"
        let isClose = false;
        let dataLine = '';
        for (const line of chunk.split('\n')) {
          if (line.startsWith('event: close')) isClose = true;
          else if (line.startsWith('data:')) dataLine = line.slice(5).trim();
        }
        if (isClose) return;
        if (dataLine) {
          try { yield JSON.parse(dataLine); } catch {}
        }
      }
    }
  },
};

export async function ensureAuthed() {
  if (shouldReplaceStoredToken()) {
    clearSession();
    try {
      await bootstrapLocalSession();
    } catch {
      window.location.href = '/login';
      return null;
    }
  }
  try {
    const { user } = await api.me();
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  } catch {
    clearSession();
    try {
      await bootstrapLocalSession();
      const { user } = await api.me();
      if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
      return user;
    } catch {
      window.location.href = '/login';
      return null;
    }
  }
}
