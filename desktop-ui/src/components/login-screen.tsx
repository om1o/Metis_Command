'use client';

import { useEffect, useState, FormEvent } from 'react';
import { Loader2, ChevronDown, ChevronUp, Mail, Lock, Laptop, KeyRound } from 'lucide-react';
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

// Google "G" mark — small inline SVG so we don't ship a logo asset.
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

// GitHub Octocat mark — inline so it renders without the lucide icon
// (lucide-react ≥1 dropped brand logos for trademark reasons).
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
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState('');

  // Ping the bridge so we can show a "bridge offline" hint immediately.
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
        // Sign-up may return user without session if email confirmation is on.
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
      // Hand off to the provider — the callback page completes the flow.
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

  return (
    <div className="metis-app-bg flex min-h-screen w-full items-center justify-center px-4 py-10 text-[var(--metis-fg)]">
      <div className="relative w-full max-w-md">
        <div
          className="pointer-events-none absolute inset-x-0 -top-32 mx-auto h-72"
          style={{ background: 'var(--metis-orb-hero)' }}
          aria-hidden
        />
        <div className="relative metis-glow-border rounded-[24px] border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-6 shadow-2xl">
          <div className="flex items-center gap-2.5">
            <Mark size={32} />
            <Wordmark size="md" />
          </div>
          <h1 className="mt-4 text-2xl font-light tracking-[-0.01em] text-[var(--metis-foreground)]">
            {tab === SIGN_IN ? 'Welcome back' : 'Create your account'}
          </h1>
          <p className="mt-1 text-sm text-[var(--metis-fg-muted)]">
            Sign in to your agent. Local-first — your work stays on your device.
          </p>

          {bridgeUp === false && (
            <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-200">
              Local API bridge isn&apos;t reachable at {API_BASE}. Start it with <code className="rounded bg-black/30 px-1">python launch.py</code> and refresh.
            </div>
          )}

          {/* OAuth row */}
          <div className="mt-5 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => handleOAuth('google')}
              disabled={busy !== null || bridgeUp === false}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5 text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)] disabled:opacity-50"
            >
              {busy === 'google' ? <Loader2 className="h-4 w-4 animate-spin" /> : <GoogleGlyph size={16} />}
              <span>Google</span>
            </button>
            <button
              type="button"
              onClick={() => handleOAuth('github')}
              disabled={busy !== null || bridgeUp === false}
              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5 text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)] disabled:opacity-50"
            >
              {busy === 'github' ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitHubGlyph size={16} />}
              <span>GitHub</span>
            </button>
          </div>

          {/* Divider */}
          <div className="my-5 flex items-center gap-3">
            <div className="h-px flex-1 bg-[var(--metis-border)]" />
            <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">or</span>
            <div className="h-px flex-1 bg-[var(--metis-border)]" />
          </div>

          {/* Tab switch */}
          <div
            role="tablist"
            aria-label="Email auth mode"
            className="mb-3 inline-flex items-center gap-0.5 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5"
          >
            {[SIGN_IN, SIGN_UP].map((t) => (
              <button
                key={t}
                role="tab"
                type="button"
                aria-selected={tab === t}
                onClick={() => { setTab(t as Tab); setError(null); setInfo(null); }}
                className={`rounded-full px-3 py-1 text-[11px] transition ${
                  tab === t
                    ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-fg)]'
                    : 'text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]'
                }`}
              >
                {t === SIGN_IN ? 'Sign in' : 'Sign up'}
              </button>
            ))}
          </div>

          {/* Email + password form */}
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

          {/* Local-device shortcut */}
          <div className="mt-4 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
            <button
              type="button"
              onClick={handleLocal}
              disabled={busy !== null || bridgeUp === false}
              className="flex w-full items-center justify-between gap-3 text-left transition disabled:opacity-50"
            >
              <span className="flex items-center gap-2.5 text-sm text-[var(--metis-fg)]">
                <Laptop className="h-4 w-4 text-violet-400" />
                Use this device only
              </span>
              {busy === 'local' ? (
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
              ) : (
                <span className="text-[11px] text-[var(--metis-fg-dim)]">No account · stays here</span>
              )}
            </button>
          </div>

          {/* Setup-code expander */}
          <button
            type="button"
            onClick={() => setTokenOpen((v) => !v)}
            className="mt-3 flex w-full items-center justify-between rounded-lg px-1 text-[11.5px] text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]"
          >
            <span className="inline-flex items-center gap-1.5">
              <KeyRound className="h-3.5 w-3.5" />
              I have a setup code
            </span>
            {tokenOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          {tokenOpen && (
            <form onSubmit={handleTokenPaste} className="mt-2 grid gap-2">
              <input
                type="password"
                placeholder="Paste setup code"
                autoComplete="off"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                className="w-full rounded-xl border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2.5 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
              />
              <button
                type="submit"
                disabled={busy !== null || !tokenInput.trim()}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-3 py-2 text-sm text-[var(--metis-fg)] transition hover:brightness-110 disabled:opacity-50"
              >
                Continue with code
              </button>
            </form>
          )}

          {error && (
            <div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200" role="alert">
              {error}
            </div>
          )}
          {info && (
            <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[12.5px] text-emerald-200">
              {info}
            </div>
          )}

          <p className="mt-5 text-center text-[11px] text-[var(--metis-fg-dim)]">
            By continuing you agree your agent runs locally. Your data stays on your device.
          </p>
        </div>
      </div>
    </div>
  );
}

function humanizeError(err: unknown, ctx: string): string {
  const raw = err instanceof Error ? err.message : String(err);
  // Friendly mappings for common Supabase / config errors.
  if (/SUPABASE|supabase|not configured|missing.*key/i.test(raw)) {
    return `${ctx}: Supabase isn’t configured on the bridge. Set SUPABASE_URL + SUPABASE_ANON_KEY in your .env, or use “Use this device only”.`;
  }
  if (/invalid.*credentials|invalid login/i.test(raw)) return 'Wrong email or password.';
  if (/already.*registered|already exists/i.test(raw)) return 'That email is already registered. Try signing in.';
  if (/rate.?limit/i.test(raw)) return 'Too many attempts. Wait a minute and try again.';
  if (/network|failed to fetch/i.test(raw)) return 'Network error. Is the local bridge running?';
  return raw;
}
