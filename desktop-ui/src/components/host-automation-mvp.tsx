'use client';

import { useState } from 'react';
import { Globe, Loader2, Terminal, MousePointer, Type, FileSearch } from 'lucide-react';
import { MetisClient } from '@/lib/metis-client';

interface BrowserResult {
  ok?: boolean;
  url?: string;
  title?: string;
  text?: string;
  note?: string;
  error?: string;
  artifact?: { id: string; title: string };
  links?: string[];
  inputs?: { selector: string; type: string }[];
  buttons?: string[];
  [key: string]: unknown;
}

function BrowserOutput({ raw }: { raw: string }) {
  let parsed: BrowserResult | null = null;
  try { parsed = JSON.parse(raw) as BrowserResult; } catch { /* show raw */ }

  if (!parsed) {
    return <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-[11px] text-[var(--metis-code-fg)]">{raw}</pre>;
  }

  const ok = parsed.ok !== false;
  return (
    <div className={`rounded-lg border p-2.5 text-[11.5px] space-y-1.5 ${ok ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-rose-500/25 bg-rose-500/5'}`}>
      {parsed.title && <div className="font-medium text-[var(--metis-fg)]">{parsed.title}</div>}
      {parsed.url && <div className="text-[10.5px] text-[var(--metis-fg-dim)] truncate">{parsed.url}</div>}
      {parsed.note && <div className="text-[var(--metis-fg-muted)]">{parsed.note}</div>}
      {parsed.error && <div className="text-rose-300">{parsed.error}</div>}
      {parsed.text && (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words text-[11px] text-[var(--metis-fg-muted)] border-t border-[var(--metis-border)] pt-1.5 mt-1.5">
          {parsed.text.slice(0, 1200)}{parsed.text.length > 1200 ? '…' : ''}
        </pre>
      )}
      {parsed.artifact && (
        <div className="text-[10.5px] text-violet-300">📎 {parsed.artifact.title}</div>
      )}
      {(parsed.buttons ?? []).length > 0 && (
        <div className="text-[10.5px] text-[var(--metis-fg-dim)]">
          Buttons: {(parsed.buttons as string[]).slice(0, 6).join(' · ')}
        </div>
      )}
      {!parsed.title && !parsed.text && !parsed.note && !parsed.error && (
        <pre className="text-[10.5px] text-[var(--metis-fg-dim)] whitespace-pre-wrap break-words">
          {JSON.stringify(parsed, null, 2).slice(0, 600)}
        </pre>
      )}
    </div>
  );
}

export default function HostAutomationMvp({ client }: { client: MetisClient }) {
  const [bUrl, setBUrl]         = useState('https://example.com');
  const [bOut, setBOut]         = useState('');
  const [bBusy, setBBusy]       = useState(false);

  const [clickTarget, setClickTarget] = useState('');
  const [byText, setByText]           = useState(true);
  const [fillSel, setFillSel]         = useState('');
  const [fillVal, setFillVal]         = useState('');
  const [extractSel, setExtractSel]   = useState('');

  const [shellCmd, setShellCmd]   = useState('');
  const [shellCwd, setShellCwd]   = useState('');
  const [shellOut, setShellOut]   = useState('');
  const [shellBusy, setShellBusy] = useState(false);
  const [pendingToken, setPendingToken] = useState<string | null>(null);

  const runBrowser = async (action: string, extra: Record<string, unknown> = {}) => {
    setBBusy(true);
    try {
      const res = await client.automationBrowser({
        action: action as never,
        url:    action === 'goto' ? bUrl : undefined,
        ...extra,
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
      const res = await client.automationShell({
        cmd,
        cwd: shellCwd.trim() || undefined,
        confirm_token: token ?? pendingToken ?? undefined,
      }) as Record<string, unknown>;

      if (res.confirm_required === true && typeof res.confirm_token === 'string') {
        setPendingToken(res.confirm_token);
        setShellOut(JSON.stringify(res, null, 2));
      } else {
        setPendingToken(null);
        setShellOut(JSON.stringify(res, null, 2));
      }
    } catch (e) {
      setShellOut(String(e instanceof Error ? e.message : e));
    } finally {
      setShellBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3 space-y-4">
      {/* ── Browser section ── */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Globe className="h-3.5 w-3.5 text-violet-300" aria-hidden />
          <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Host browser (Playwright)</div>
          {bBusy && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-violet-400" />}
        </div>
        <p className="text-[11px] leading-5 text-[var(--metis-fg-dim)] mb-2">
          Requires <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">playwright install chromium</code>. Localhost blocked by default.
        </p>

        {/* URL + navigation */}
        <label className="grid gap-1 mb-2">
          <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">URL</span>
          <input
            value={bUrl}
            onChange={(ev) => setBUrl(ev.target.value)}
            className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
          />
        </label>
        <div className="flex flex-wrap gap-1.5 mb-3">
          {([
            { label: 'Start',       action: 'start' },
            { label: 'Goto',        action: 'goto'  },
            { label: 'Snapshot',    action: 'snapshot', accent: true },
            { label: 'Screenshot',  action: 'screenshot' },
            { label: 'Close',       action: 'close' },
          ] as { label: string; action: string; accent?: boolean }[]).map(({ label, action, accent }) => (
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
        </div>

        {/* Click */}
        <div className="mb-3 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-2 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <MousePointer className="h-3 w-3 text-[var(--metis-fg-dim)]" />
            <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Click</span>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={clickTarget}
              onChange={(ev) => setClickTarget(ev.target.value)}
              placeholder={byText ? 'Button label…' : 'CSS selector…'}
              className="flex-1 rounded border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1 text-[11.5px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
            />
            <label className="flex items-center gap-1 text-[10.5px] text-[var(--metis-fg-dim)] cursor-pointer select-none">
              <input type="checkbox" checked={byText} onChange={(e) => setByText(e.target.checked)} className="accent-violet-500" />
              by text
            </label>
            <button
              type="button"
              disabled={bBusy || !clickTarget.trim()}
              onClick={() => void runBrowser('click', { target: clickTarget, by_text: byText })}
              className="rounded border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-40"
            >
              Click
            </button>
          </div>
        </div>

        {/* Fill */}
        <div className="mb-3 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-2 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Type className="h-3 w-3 text-[var(--metis-fg-dim)]" />
            <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Fill form field</span>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={fillSel}
              onChange={(ev) => setFillSel(ev.target.value)}
              placeholder="CSS selector (input, textarea…)"
              className="flex-1 rounded border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1 text-[11.5px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
            />
            <input
              value={fillVal}
              onChange={(ev) => setFillVal(ev.target.value)}
              placeholder="value"
              className="w-24 rounded border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1 text-[11.5px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
            />
            <button
              type="button"
              disabled={bBusy || !fillSel.trim()}
              onClick={() => void runBrowser('fill', { target: fillSel, value: fillVal })}
              className="rounded border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-40"
            >
              Fill
            </button>
          </div>
        </div>

        {/* Extract */}
        <div className="mb-3 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-2 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <FileSearch className="h-3 w-3 text-[var(--metis-fg-dim)]" />
            <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Extract text</span>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={extractSel}
              onChange={(ev) => setExtractSel(ev.target.value)}
              placeholder="CSS selector (leave blank for full page)"
              className="flex-1 rounded border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1 text-[11.5px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
            />
            <button
              type="button"
              disabled={bBusy}
              onClick={() => void runBrowser('extract', { selector: extractSel.trim() || null })}
              className="rounded border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-40"
            >
              Extract
            </button>
          </div>
        </div>

        {bOut && <BrowserOutput raw={bOut} />}
      </div>

      <hr className="border-[var(--metis-border)]" />

      {/* ── Shell section ── */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Terminal className="h-3.5 w-3.5 text-emerald-300" aria-hidden />
          <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Allow-listed shell</div>
        </div>
        <p className="text-[11px] text-[var(--metis-fg-dim)] mb-2">
          First POST returns approve token (HTTP 428). Click <em>Approve run</em> to execute.
        </p>

        <label className="grid gap-1 mb-2">
          <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Command</span>
          <input
            value={shellCmd}
            onChange={(ev) => setShellCmd(ev.target.value)}
            placeholder="e.g. where python"
            className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 font-mono text-[12px] text-[var(--metis-fg)] outline-none focus:border-emerald-500/50"
          />
        </label>
        <label className="grid gap-1 mb-2">
          <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">cwd (optional)</span>
          <input
            value={shellCwd}
            onChange={(ev) => setShellCwd(ev.target.value)}
            placeholder="Leave blank to use bridge process cwd"
            className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 font-mono text-[12px] text-[var(--metis-fg)] outline-none focus:border-emerald-500/50"
          />
        </label>
        <div className="flex flex-wrap gap-2 mb-2">
          <button
            type="button"
            disabled={shellBusy}
            onClick={() => void runShellOnce(null)}
            className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40"
          >
            {shellBusy ? <Loader2 className="inline h-3 w-3 animate-spin" /> : 'Request run'}
          </button>
          {pendingToken && (
            <button
              type="button"
              disabled={shellBusy}
              onClick={() => void runShellOnce(pendingToken)}
              className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
            >
              Approve run
            </button>
          )}
        </div>

        {shellOut && (
          <ShellOutput raw={shellOut} />
        )}
      </div>
    </div>
  );
}

function ShellOutput({ raw }: { raw: string }) {
  let parsed: Record<string, unknown> | null = null;
  try { parsed = JSON.parse(raw); } catch { /* show raw */ }

  if (!parsed) {
    return <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-[11px] text-[var(--metis-code-fg)]">{raw}</pre>;
  }

  const ok = parsed.ok !== false && (parsed.exit_code === undefined || parsed.exit_code === 0);
  const isPending = parsed.confirm_required === true;

  return (
    <div className={`rounded-lg border p-2.5 text-[11.5px] space-y-1.5 ${isPending ? 'border-amber-500/30 bg-amber-500/5' : ok ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-rose-500/25 bg-rose-500/5'}`}>
      {isPending ? (
        <div className="text-amber-200 font-medium">Approval required — click "Approve run" to execute</div>
      ) : (
        <div className="flex items-center gap-2">
          <span className={`text-[10.5px] font-mono px-1.5 py-0.5 rounded ${ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}>
            exit {String(parsed.exit_code ?? 0)}
          </span>
          {typeof parsed.duration_ms === 'number' && (
            <span className="text-[10px] text-[var(--metis-fg-dim)]">{parsed.duration_ms}ms</span>
          )}
        </div>
      )}
      {typeof parsed.stdout === 'string' && parsed.stdout.trim() && (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words text-[11px] text-[var(--metis-fg)] border-t border-[var(--metis-border)] pt-1.5">
          {parsed.stdout.slice(0, 2000)}{parsed.stdout.length > 2000 ? '…' : ''}
        </pre>
      )}
      {typeof parsed.stderr === 'string' && parsed.stderr.trim() && (
        <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-words text-[11px] text-rose-300 border-t border-rose-500/20 pt-1.5">
          {parsed.stderr.slice(0, 1000)}{parsed.stderr.length > 1000 ? '…' : ''}
        </pre>
      )}
    </div>
  );
}
