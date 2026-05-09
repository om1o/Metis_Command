'use client';

import { useEffect, useState, FormEvent } from 'react';
import {
  Loader2,
  ChevronDown,
  ChevronUp,
  Mail,
  Lock,
  Laptop,
  KeyRound,
  ArrowRight,
  AlertCircle,
  Copy,
  Check,
} from 'lucide-react';
import { Mark, Wordmark } from '@/components/brand';
import { MetisClient, AuthUser, OAuthProvider } from '@/lib/metis-client';

const API_BASE = 'http://127.0.0.1:7331';

type AuthMode = 'local' | 'email' | 'google' | 'github';
type Tab = 'signin' | 'signup';

export interface AuthSuccess {
  token: string;
  user: AuthUser;
  mode: AuthMode;
}

interface Props {
  onAuth: (result: AuthSuccess) => void;
}

const SIGN_IN = 'signin';
const SIGN_UP = 'signup';

function GoogleGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.4-.4-3.5z"/>
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16 18.9 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.1 5.6l6.2 5.2C41 35.5 44 30.2 44 24c0-1.2-.1-2.4-.4-3.5z"/>
    </svg>
  );
}

function GitHubGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" fill="currentColor">
      <path d="M8 .2a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38l-.01-1.49c-2.22.48-2.69-.94-2.69-.94-.36-.93-.89-1.18-.89-1.18-.73-.5.06-.49.06-.49.81.06 1.23.83 1.23.83.72 1.23 1.88.87 2.34.67.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.83-2.15-.08-.2-.36-1.02.08-2.13 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 4 0c1.53-1.03 2.2-.82 2.2-.82.44 1.11.16 1.93.08 2.13.52.56.83 1.27.83 2.15 0 3.07-1.87 3.74-3.65 3.94.29.25.54.74.54 1.5l-.01 2.22c0 .21.15.46.55.38A8 8 0 0 0 8 .2"/>
    </svg>
  );
}

export default function LoginScreen({ onAuth }: Props) {
  const [tab, setTab] = useState<Tab>(SIGN_IN);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<AuthMode | null>(null);
  // Lazy initializer reads any OAuth error stashed by the / fallback or
  // /oauth/callback page. Using initializer instead of useEffect avoids
  // React 19's set-state-in-effect rule.
  const [error, setError] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    try {
      const stashed = sessionStorage.getItem('metis-auth-error');
      if (stashed) {
        sessionStorage.removeItem('metis-auth-error');
        return stashed;
      }
    } catch {}
    return null;
  });
  const [info, setInfo] = useState<string | null>(null);
  const [tokenOpen, setTokenOpen] = useState(false);
  // Auto-open the cloud panel if we landed here with an OAuth error so
  // the user sees the context they were last in.
  const [cloudOpen, setCloudOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    try { return !!sessionStorage.getItem('metis-auth-error'); } catch {}
    return false;
  });
  const [tokenInput, setTokenInput] = useState('');
  const [copied, setCopied] = useState(false);

  // Bridge ping so we can show a "bridge offline" hint immediately.
  const [bridgeUp, setBridgeUp] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/health`, { headers: { Accept: 'application/json' } });
        if (!cancelled) setBridgeUp(r.ok);
      } catch {
        if (!cancelled) setBridgeUp(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const guard = (mode: AuthMode) => {
    setError(null);
    setInfo(null);
    setBusy(mode);
  };
  const settle = () => setBusy(null);

  const handleEmailSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setError('Enter email and password.');
      return;
    }
    guard('email');
    try {
      const client = new MetisClient(API_BASE);
      const fn = tab === SIGN_IN ? client.signIn(email.trim(), password) : client.signUp(email.trim(), password);
      const result = await fn;
      const token = result.session?.access_token;
      const user = result.user;
      if (!token || !user) {
        if (tab === SIGN_UP) {
          setInfo('Check your inbox to confirm your email, then sign in.');
        } else {
          setError('Sign-in returned no session. Check your Supabase config.');
        }
        return;
      }
      onAuth({ token, user, mode: 'email' });
    } catch (err) {
      setError(humanizeError(err, tab));
    } finally {
      settle();
    }
  };

  const handleOAuth = async (provider: OAuthProvider) => {
    guard(provider);
    try {
      const client = new MetisClient(API_BASE);
      const redirectTo = `${window.location.origin}/oauth/callback`;
      const { url } = await client.oauthStart(provider, redirectTo);
      if (!url) {
        setError(`${provider} did not return a sign-in URL. Check Supabase auth config.`);
        return;
      }
      window.location.href = url;
    } catch (err) {
      setError(humanizeError(err, provider));
      settle();
    }
  };

  const handleLocal = async () => {
    guard('local');
    try {
      const client = new MetisClient(API_BASE);
      const { token } = await client.getLocalToken();
      if (!token) {
        setError('Local bridge did not issue a token.');
        return;
      }
      const authed = new MetisClient(API_BASE, token);
      const me = await authed.getMe();
      onAuth({ token, user: me.user, mode: 'local' });
    } catch (err) {
      setError(humanizeError(err, 'local'));
    } finally {
      settle();
    }
  };

  const handleTokenPaste = async (e: FormEvent) => {
    e.preventDefault();
    const tok = tokenInput.trim();
    if (!tok) return;
    guard('local');
    try {
      const authed = new MetisClient(API_BASE, tok);
      const me = await authed.getMe();
      onAuth({ token: tok, user: me.user, mode: 'local' });
    } catch (err) {
      setError(humanizeError(err, 'local'));
    } finally {
      settle();
    }
  };

  const copyError = async () => {
    if (!error) return;
    try {
      await navigator.clipboard.writeText(error);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  };

  return (
    <div className="metis-app-bg flex min-h-screen w-full items-center justify-center px-4 py-10 text-[var(--metis-fg)]">
      <div className="relative w-full max-w-md">
        {/* Hero orb behind the card */}
        <div
          className="pointer-events-none absolute inset-x-0 -top-40 mx-auto h-80"
          style={{ background: 'var(--metis-orb-hero)' }}
          aria-hidden
        />

        <div className="relative metis-glow-border overflow-hidden rounded-[28px] border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-7 shadow-2xl">
          {/* Brand */}
          <div className="flex flex-col items-center gap-2 text-center">
            <Mark size={48} />
            <Wordmark size="large" />
            <p className="mt-1 text-[12.5px] text-[var(--metis-fg-dim)]">
              Your private agent. Local-first.
            </p>
          </div>

          {/* Bridge status banner — only when actually unreachable */}
          {bridgeUp === false && (
            <div className="mt-5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-[12.5px] text-amber-200">
              <strong className="font-medium">Local bridge offline.</strong> Start it with{' '}
              <code className="rounded bg-black/30 px-1 font-mono">python launch.py</code> and refresh.
            </div>
          )}

          {/* PRIMARY: Use this device — the path that always works */}
          <div className="mt-6">
            <button
              type="button"
              onClick={handleLocal}
              disabled={busy !== null || bridgeUp === false}
              className="group flex w-full items-center gap-3 rounded-2xl border border-violet-500/30 bg-gradient-to-br from-violet-500/15 to-violet-500/5 px-4 py-3.5 text-left text-[var(--metis-fg)] transition hover:border-violet-500/50 hover:from-violet-500/20 hover:to-violet-500/10 disabled:opacity-50"
              autoFocus
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-500/20 text-violet-200">
                {busy === 'local' ? (
                  <Loader2 className="h-4.5 w-4.5 animate-spin" />
                ) : (
                  <Laptop className="h-4.5 w-4.5" />
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[14.5px] font-medium leading-snug">Use this device</span>
                <span className="block text-[11.5px] text-[var(--metis-fg-dim)]">
                  No account · everything stays on your machine
                </span>
              </span>
              <ArrowRight className="h-4 w-4 text-[var(--metis-fg-dim)] transition group-hover:translate-x-0.5 group-hover:text-violet-300" />
            </button>
          </div>

          {/* SECONDARY: cloud account expander */}
          <div className="mt-3">
            <button
              type="button"
              onClick={() => { setCloudOpen((v) => !v); setError(null); setInfo(null); }}
              className="flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-[12px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
            >
              {cloudOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {cloudOpen ? 'Hide cloud sign-in options' : 'Sign in with a cloud account'}
            </button>
          </div>

          {cloudOpen && (
            <div className="mt-2 grid gap-3 rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-4">
              {/* OAuth row */}
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => handleOAuth('google')}
                  disabled={busy !== null || bridgeUp === false}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-3 py-2.5 text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)] disabled:opacity-50"
                >
                  {busy === 'google' ? <Loader2 className="h-4 w-4 animate-spin" /> : <GoogleGlyph size={16} />}
                  <span>Google</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleOAuth('github')}
                  disabled={busy !== null || bridgeUp === false}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-3 py-2.5 text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)] disabled:opacity-50"
                >
                  {busy === 'github' ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitHubGlyph size={16} />}
                  <span>GitHub</span>
                </button>
              </div>

              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-[var(--metis-border)]" />
                <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">or with email</span>
                <div className="h-px flex-1 bg-[var(--metis-border)]" />
              </div>

              {/* Sign in / Sign up tabs */}
              <div role="tablist" className="inline-flex items-center gap-0.5 self-start rounded-full border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-0.5">
                {[SIGN_IN, SIGN_UP].map((t) => (
                  <button
                    key={t}
                    role="tab"
                    type="button"
                    aria-selected={tab === t}
                    onClick={() => { setTab(t as Tab); setError(null); setInfo(null); }}
                    className={`rounded-full px-3 py-1 text-[11px] transition ${
                      tab === t
                        ? 'bg-violet-500/15 text-violet-200'
                        : 'text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]'
                    }`}
                  >
                    {t === SIGN_IN ? 'Sign in' : 'Sign up'}
                  </button>
                ))}
              </div>

              <form onSubmit={handleEmailSubmit} className="grid gap-2.5">
                <label className="grid gap-1">
                  <span className="sr-only">Email</span>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--metis-fg-dim)]" />
                    <input
                      type="email"
                      autoComplete="email"
                      placeholder="you@domain.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full rounded-xl border border-[var(--metis-border)] bg-[var(--metis-input-bg)] py-2.5 pl-9 pr-3 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
                    />
                  </div>
                </label>
                <label className="grid gap-1">
                  <span className="sr-only">Password</span>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--metis-fg-dim)]" />
                    <input
                      type="password"
                      autoComplete={tab === SIGN_IN ? 'current-password' : 'new-password'}
                      placeholder="Password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full rounded-xl border border-[var(--metis-border)] bg-[var(--metis-input-bg)] py-2.5 pl-9 pr-3 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
                    />
                  </div>
                </label>
                <button
                  type="submit"
                  disabled={busy !== null || bridgeUp === false}
                  className="mt-1 inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
                  style={{ background: 'var(--metis-accent)' }}
                >
                  {busy === 'email' ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {tab === SIGN_IN ? 'Sign in' : 'Create account'}
                </button>
              </form>
            </div>
          )}

          {/* Tertiary: setup-code expander */}
          <button
            type="button"
            onClick={() => setTokenOpen((v) => !v)}
            className="mt-4 flex w-full items-center justify-center gap-1.5 text-[11px] text-[var(--metis-fg-dim)] hover:text-[var(--metis-fg-muted)]"
          >
            <KeyRound className="h-3 w-3" />
            {tokenOpen ? 'Hide setup code' : 'I have a setup code'}
          </button>
          {tokenOpen && (
            <form onSubmit={handleTokenPaste} className="mt-2 grid gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
              <input
                type="password"
                placeholder="Paste setup code"
                autoComplete="off"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                className="w-full rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
              />
              <button
                type="submit"
                disabled={busy !== null || !tokenInput.trim()}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-3 py-2 text-sm text-[var(--metis-fg)] transition hover:brightness-110 disabled:opacity-50"
              >
                Continue with code
              </button>
            </form>
          )}

          {/* Persistent error display */}
          {error && (
            <div className="mt-4 grid gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3" role="alert">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-medium text-rose-100">Sign-in failed</div>
                  <p className="mt-0.5 break-words text-[12px] text-rose-200/90">{error}</p>
                </div>
                <button
                  type="button"
                  onClick={copyError}
                  className="shrink-0 rounded-md border border-rose-500/30 bg-rose-500/10 px-1.5 py-1 text-[10px] text-rose-200 hover:bg-rose-500/20"
                  title="Copy error"
                >
                  {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                </button>
              </div>
            </div>
          )}
          {info && (
            <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[12.5px] text-emerald-200">
              {info}
            </div>
          )}

          <p className="mt-5 text-center text-[10.5px] text-[var(--metis-fg-dim)]">
            By continuing you agree your agent runs locally. Your data stays on your device.
          </p>
        </div>
      </div>
    </div>
  );
}

function humanizeError(err: unknown, ctx: string): string {
  const raw = err instanceof Error ? err.message : String(err);
  if (/SUPABASE|supabase|not configured|missing.*key/i.test(raw)) {
    return `${ctx}: Supabase isn’t configured on the bridge. Set SUPABASE_URL + SUPABASE_KEY in your .env, or use “Use this device”.`;
  }
  if (/invalid.*flow.*state/i.test(raw)) {
    return `${ctx}: OAuth flow expired or already used. Open a fresh tab and try again.`;
  }
  if (/code_verifier|missing.*verifier/i.test(raw)) {
    return `${ctx}: PKCE verifier was lost between redirect and callback. The bridge probably restarted mid-flow — try again.`;
  }
  if (/invalid.*credentials|invalid login/i.test(raw)) return 'Wrong email or password.';
  if (/already.*registered|already exists/i.test(raw)) return 'That email is already registered. Try signing in.';
  if (/rate.?limit/i.test(raw)) return 'Too many attempts. Wait a minute and try again.';
  if (/network|failed to fetch/i.test(raw)) return 'Network error. Is the local bridge running?';
  return raw;
}
