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
  oauthComplete: (code) => _fetch('/auth/oauth/complete', {
    method: 'POST',
    body: JSON.stringify({ code }),
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
  marketplace: () => _fetch('/marketplace'),
  installPlugin: (slug) => _fetch('/marketplace/install', { method: 'POST', body: JSON.stringify({ slug }) }),
  uninstallPlugin: (slug) => _fetch('/marketplace/uninstall', { method: 'POST', body: JSON.stringify({ slug }) }),
  skills: () => _fetch('/skills'),
  sessions: () => _fetch('/sessions'),
  sessionMessages: (id) => _fetch(`/sessions/${encodeURIComponent(id)}`),
  deleteSession: (id) => _fetch(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  renameSession: (id, title) => _fetch(`/sessions/${encodeURIComponent(id)}/rename`, {
    method: 'POST', body: JSON.stringify({ title }),
  }),

  // Jobs
  jobs: (status) => _fetch(status ? `/jobs?status=${status}` : '/jobs'),
  createJob: (data) => _fetch('/jobs', { method: 'POST', body: JSON.stringify(data) }),
  deleteJob: (id) => _fetch(`/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  updateJobStatus: (id, status) => _fetch(`/jobs/${encodeURIComponent(id)}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),

  // Manager configuration + available models
  managerConfig: () => _fetch('/manager/config'),
  saveManagerConfig: (updates) => _fetch('/manager/config', {
    method: 'POST', body: JSON.stringify(updates || {}),
  }),
  models: () => _fetch('/models'),

  // Agent health
  agentHealth: () => _fetch('/agents/health'),

  // Ollama auto-management
  ollamaStatus: () => _fetch('/ollama/status'),
  ollamaStart: () => _fetch('/ollama/start', { method: 'POST' }),

  // Streaming chat (Server-Sent Events)
  chatStream: async function* (sessionId, message, role = 'manager', signal) {
    const token = getToken();
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ session_id: sessionId, message, role }),
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
