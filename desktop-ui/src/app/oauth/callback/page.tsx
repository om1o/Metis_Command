'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Loader2, CircleX, CircleCheck } from 'lucide-react';
import { Mark, Wordmark } from '@/components/brand';
import { MetisClient } from '@/lib/metis-client';

const API_BASE = 'http://127.0.0.1:7331';

type Phase = 'working' | 'done' | 'error';

// Read URL params lazily on mount so the initial render already reflects the
// "missing code" or "provider error" cases without an extra setState.
function readCallbackParams(): { code: string | null; state: string | undefined; error: string | null } {
  if (typeof window === 'undefined') return { code: null, state: undefined, error: null };
  const u = new URL(window.location.href);
  return {
    code: u.searchParams.get('code'),
    state: u.searchParams.get('state') || undefined,
    error: u.searchParams.get('error_description') || u.searchParams.get('error'),
  };
}

export default function OAuthCallbackPage() {
  const [params] = useState(readCallbackParams);
  const [phase, setPhase] = useState<Phase>(params.error || !params.code ? 'error' : 'working');
  const [message, setMessage] = useState<string>(() => {
    if (params.error) return decodeURIComponent(params.error);
    if (!params.code) return 'Missing authorization code in callback URL.';
    return 'Finishing sign-in…';
  });

  useEffect(() => {
    if (phase !== 'working' || !params.code) return;
    let cancelled = false;
    (async () => {
      try {
        const client = new MetisClient(API_BASE);
        const result = await client.oauthComplete(params.code as string, params.state);
        if (cancelled) return;
        const token = result.session?.access_token;
        const user = result.user;
        if (!token || !user) {
          throw new Error('OAuth completed without a session. Check Supabase auth config.');
        }
        try {
          localStorage.setItem('metis-token', token);
          localStorage.setItem('metis-auth-mode', 'oauth');
          localStorage.setItem('metis-user', JSON.stringify(user));
        } catch {}
        setPhase('done');
        setMessage('Signed in. Redirecting…');
        setTimeout(() => { window.location.replace('/'); }, 600);
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        // Stash a copy for the LoginScreen so the user can see + copy
        // the underlying Supabase error if they navigate back to /.
        try { sessionStorage.setItem('metis-auth-error', msg); } catch {}
        setPhase('error');
        setMessage(msg);
      }
    })();
    return () => { cancelled = true; };
  }, [params, phase]);

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
            <Mark size={28} />
            <Wordmark size="md" />
          </div>
          <div className="mt-6 flex items-start gap-3">
            {phase === 'working' && <Loader2 className="mt-0.5 h-5 w-5 animate-spin text-violet-400" />}
            {phase === 'done' && <CircleCheck className="mt-0.5 h-5 w-5 text-emerald-400" />}
            {phase === 'error' && <CircleX className="mt-0.5 h-5 w-5 text-rose-400" />}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-[var(--metis-foreground)]">
                {phase === 'working' ? 'Completing sign-in' : phase === 'done' ? 'You’re in' : 'Sign-in failed'}
              </div>
              <p className="mt-1 break-words text-[12.5px] text-[var(--metis-fg-muted)]">{message}</p>
            </div>
          </div>
          {phase === 'error' && (
            <div className="mt-5 flex justify-end">
              <Link
                href="/"
                className="inline-flex items-center gap-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2 text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)]"
              >
                Back to login
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
