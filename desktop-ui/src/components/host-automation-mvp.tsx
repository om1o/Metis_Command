'use client';

import { useState } from 'react';
import { Globe, Loader2, Terminal } from 'lucide-react';
import { MetisClient } from '@/lib/metis-client';

function ShellOutput({ raw }: { raw: string }) {
  let parsed: Record<string, unknown> | null = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    parsed = null;
  }

  if (!parsed || typeof parsed !== 'object') {
    return (
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-[11px] text-[var(--metis-code-fg)]">
        {raw}
      </pre>
    );
  }

  const ok = parsed.ok !== false && (parsed.exit_code === undefined || parsed.exit_code === 0);
  const isPending = parsed.confirm_required === true;

  return (
    <div
      className={`space-y-1.5 rounded-lg border p-2.5 text-[11.5px] ${
        isPending ? 'border-amber-500/30 bg-amber-500/5' : ok ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-rose-500/25 bg-rose-500/5'
      }`}
    >
      {isPending ? (
        <div className="font-medium text-amber-200">Approval pending — use the amber Approve run control.</div>
      ) : (
        <div className="flex items-center gap-2">
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[10.5px] ${ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}
          >
            exit {String(parsed.exit_code ?? 0)}
          </span>
          {typeof parsed.duration_ms === 'number' && (
            <span className="text-[10px] text-[var(--metis-fg-dim)]">{parsed.duration_ms}ms</span>
          )}
        </div>
      )}
      {typeof parsed.stdout === 'string' && parsed.stdout.trim() && (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words border-t border-[var(--metis-border)] pt-1.5 font-mono text-[11px] text-[var(--metis-fg)]">
          {parsed.stdout.slice(0, 2000)}
          {parsed.stdout.length > 2000 ? '\n…' : ''}
        </pre>
      )}
      {typeof parsed.stderr === 'string' && parsed.stderr.trim() && (
        <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-words border-t border-rose-500/20 pt-1.5 font-mono text-[11px] text-rose-300">
          {parsed.stderr.slice(0, 1000)}
          {parsed.stderr.length > 1000 ? '\n…' : ''}
        </pre>
      )}
    </div>
  );
}

export default function HostAutomationMvp({ client }: { client: MetisClient }) {
  const [bUrl, setBUrl] = useState('https://example.com');
  const [bOut, setBOut] = useState('');
  const [bBusy, setBBusy] = useState(false);
  const [shellCmd, setShellCmd] = useState('');
  const [shellCwd, setShellCwd] = useState('');
  const [shellRaw, setShellRaw] = useState('');
  const [shellBusy, setShellBusy] = useState(false);
  const [pendingToken, setPendingToken] = useState<string | null>(null);

  const runBrowser = async (action: 'start' | 'goto' | 'snapshot' | 'screenshot' | 'close') => {
    setBBusy(true);
    try {
      const res = await client.automationBrowser({
        action,
        url: action === 'goto' ? bUrl : undefined,
      });
      setBOut(typeof res === 'string' ? res : JSON.stringify(res, null, 2));
    } catch (e) {
      setBOut(String(e instanceof Error ? e.message : e));
    } finally {
      setBBusy(false);
    }
  };

  const runShellOnce = async (token?: string | null) => {
    const cmd = shellCmd.trim();
    if (!cmd) return;
    setShellBusy(true);
    try {
      const res = (await client.automationShell({
        cmd,
        cwd: shellCwd.trim() || undefined,
        confirm_token: token ?? pendingToken ?? undefined,
      })) as Record<string, unknown>;

      if (res.confirm_required === true && typeof res.confirm_token === 'string') {
        setPendingToken(res.confirm_token);
        setShellRaw(JSON.stringify(res, null, 2));
      } else {
        setPendingToken(null);
        setShellRaw(JSON.stringify(res, null, 2));
      }
    } catch (e) {
      setPendingToken(null);
      setShellRaw(String(e instanceof Error ? e.message : e));
    } finally {
      setShellBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
      <div className="flex items-center gap-2">
        <Globe className="h-3.5 w-3.5 text-violet-300" aria-hidden />
        <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Host automation (MVP)</div>
      </div>
      <p className="mt-1 text-[11px] leading-5 text-[var(--metis-fg-dim)]">
        Local Playwright + allow-listed shell behind the bridge. Requires{' '}
        <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">playwright install chromium</code>
        .
        localhost URLs stay blocked unless you set{' '}
        <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">METIS_BROWSER_ALLOW_LOCALHOST=1</code>{' '}
        in your repo <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">.env</code>.
      </p>

      <div className="mt-3 space-y-2">
        <label className="grid gap-1">
          <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">URL</span>
          <input
            value={bUrl}
            onChange={(ev) => setBUrl(ev.target.value)}
            className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)]"
          />
        </label>
        <div className="flex flex-wrap gap-1.5">
          {(
            [
              { label: 'Start', action: 'start' as const, accent: false },
              { label: 'Goto + wait', action: 'goto' as const, accent: false },
              { label: 'Snapshot', action: 'snapshot' as const, accent: true },
              { label: 'Screenshot', action: 'screenshot' as const, accent: false },
              { label: 'Close', action: 'close' as const, accent: false },
            ] as const
          ).map(({ label, action, accent }) => (
            <button
              key={action}
              type="button"
              disabled={bBusy}
              onClick={() => void runBrowser(action)}
              className={`rounded-lg border px-2 py-1 text-[11px] transition disabled:opacity-40 ${
                accent
                  ? 'border-violet-500/30 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20'
                  : 'border-[var(--metis-border)] bg-[var(--metis-bg)] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
              }`}
            >
              {label}
            </button>
          ))}
          {bBusy && <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" aria-label="busy" />}
        </div>
        {bOut && (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-[11px] text-[var(--metis-code-fg)]">{bOut}</pre>
        )}
      </div>

      <hr className="my-4 border-[var(--metis-border)]" />

      <div className="flex items-center gap-2">
        <Terminal className="h-3.5 w-3.5 text-emerald-300" aria-hidden />
        <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Allow-listed shell</div>
      </div>
      <p className="mt-1 text-[11px] text-[var(--metis-fg-dim)]">
        First POST returns approve token (HTTP 428); then approve with the same command.
      </p>
      <label className="mt-2 grid gap-1">
        <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Command</span>
        <input
          value={shellCmd}
          onChange={(ev) => setShellCmd(ev.target.value)}
          placeholder="e.g. where python"
          className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 font-mono text-[12px] text-[var(--metis-fg)]"
        />
      </label>
      <label className="mt-2 grid gap-1">
        <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">cwd (optional)</span>
        <input
          value={shellCwd}
          onChange={(ev) => setShellCwd(ev.target.value)}
          placeholder="Leave blank to use the bridge process cwd"
          className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 font-mono text-[12px] text-[var(--metis-fg)]"
        />
      </label>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={shellBusy}
          onClick={() => void runShellOnce(null)}
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-200 hover:bg-emerald-500/20"
        >
          Request run
        </button>
        {pendingToken && (
          <button
            type="button"
            disabled={shellBusy}
            onClick={() => void runShellOnce(pendingToken)}
            className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-200 hover:bg-amber-500/20"
          >
            Approve run
          </button>
        )}
      </div>
      {shellRaw ? <ShellOutput raw={shellRaw} /> : null}
    </div>
  );
}
