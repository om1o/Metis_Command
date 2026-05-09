/**
 * Metis API client — talks to the FastAPI backend on the same origin.
 * Stores the Supabase access_token in localStorage and attaches it as
 * `Authorization: Bearer <token>` on every authenticated request.
 */

const TOKEN_KEY = 'metis.access_token';
const REFRESH_KEY = 'metis.refresh_token';
const USER_KEY = 'metis.user';

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
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
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
    // Surface rate-limit errors with retry-after hint
    if (r.status === 429) {
      const retryAfter = r.headers.get('retry-after');
      err.message = retryAfter
        ? `Rate limit reached. Try again in ${retryAfter}s.`
        : 'Rate limit reached. Please wait a moment and try again.';
      if (typeof window !== 'undefined' && window.toast) {
        window.toast('warning', 'Rate limit', err.message, 5000);
      }
    }
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
  marketplace: () => _fetch('/marketplace'),
  installPlugin: (slug) => _fetch('/marketplace/install', { method: 'POST', body: JSON.stringify({ slug }) }),
  skills: () => _fetch('/skills'),
  sessions: () => _fetch('/sessions'),
  sessionMessages: (id) => _fetch(`/sessions/${encodeURIComponent(id)}`),
  deleteSession: (id) => _fetch(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  renameSession: (id, title) => _fetch(`/sessions/${encodeURIComponent(id)}/rename`, {
    method: 'POST', body: JSON.stringify({ title }),
  }),
  exportSession: (id, format = 'md') => {
    const token = getToken();
    const url = `/sessions/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}`;
    const a = document.createElement('a');
    a.href = url + (token ? `&_t=${encodeURIComponent(token)}` : '');
    // Use fetch so we can attach the auth header, then trigger download
    return fetch(url, { headers: token ? { 'Authorization': `Bearer ${token}` } : {} })
      .then(r => {
        if (!r.ok) throw new Error(r.statusText);
        const cd = r.headers.get('content-disposition') || '';
        const fn = cd.match(/filename="([^"]+)"/)?.[1] || `metis-export.${format}`;
        return r.blob().then(b => {
          const url2 = URL.createObjectURL(b);
          const link = document.createElement('a');
          link.href = url2;
          link.download = fn;
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(url2), 5000);
        });
      });
  },

  // Manager configuration + available models
  managerConfig: () => _fetch('/manager/config'),
  saveManagerConfig: (updates) => _fetch('/manager/config', {
    method: 'POST', body: JSON.stringify(updates || {}),
  }),
  models: () => _fetch('/models'),

  // Agent health
  agentHealth: () => _fetch('/agents/health'),

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

  // Notifications
  notifications: (limit = 50, unreadOnly = false) =>
    _fetch(`/notifications?limit=${limit}&unread_only=${unreadOnly}`),
  notificationCount: () => _fetch('/notifications/count'),
  markNotificationRead: (id) => _fetch(`/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => _fetch('/notifications/read-all', { method: 'POST' }),
  clearNotifications: () => _fetch('/notifications', { method: 'DELETE' }),

  // Sessions full-text search
  searchSessions: (q, limit = 20) =>
    _fetch(`/sessions/search?q=${encodeURIComponent(q)}&limit=${limit}`),

  // Analytics summary
  analytics: () => _fetch('/analytics'),

  // Artifacts
  artifacts: (limit = 50) => _fetch(`/artifacts?limit=${limit}`),
  deleteArtifact: (id) => _fetch(`/artifacts/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  // Multi-model comparison (Phase 13)
  compareModels: (message, models = []) => _fetch('/chat/compare', {
    method: 'POST',
    body: JSON.stringify({ message, models }),
  }),

  // Workflows (Phase 15)
  workflows: () => _fetch('/workflows'),
  workflowTemplates: () => _fetch('/workflows/templates'),
  saveWorkflow: (data) => _fetch('/workflows', { method: 'POST', body: JSON.stringify(data) }),
  getWorkflow: (id) => _fetch(`/workflows/${encodeURIComponent(id)}`),
  deleteWorkflow: (id) => _fetch(`/workflows/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  runWorkflow: (id, inputs = {}) => _fetch(`/workflows/${encodeURIComponent(id)}/run`, {
    method: 'POST', body: JSON.stringify({ inputs }),
  }),

  // Streaming chat (Server-Sent Events)
  chatStream: async function* (sessionId, message, role = 'manager', signal, direct = false) {
    const token = getToken();
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ session_id: sessionId, message, role, direct }),
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
  if (!getToken()) {
    window.location.href = '/login';
    return null;
  }
  try {
    const { user } = await api.me();
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    return user;
  } catch {
    clearSession();
    window.location.href = '/login';
    return null;
  }
}
