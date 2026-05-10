'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { Globe, Terminal, X, MousePointer, Type, FileSearch, Loader2, Camera } from 'lucide-react';
import { MetisClient } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

// ── Output renderers ──────────────────────────────────────────────────────────

interface BrowserResult {
  ok?: boolean;
  url?: string;
  title?: string;
  text?: string;
  note?: string;
  error?: string;
  artifact?: { id: string; title: string };
  buttons?: string[];
  inputs?: { selector: string; type: string }[];
  links?: string[];
  [key: string]: unknown;
}

function BrowserOutput({ raw }: { raw: string }) {
  let parsed: BrowserResult | null = null;
  try { parsed = JSON.parse(raw) as BrowserResult; } catch { /* show raw */ }

  if (!parsed) {
    return (
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-[11px] text-[var(--metis-code-fg)]">
        {raw}
      </pre>
    );
  }

  const ok = parsed.ok !== false;
  return (
    <div className={`rounded-lg border p-2.5 text-[11.5px] space-y-1.5 ${ok ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-rose-500/25 bg-rose-500/5'}`}>
      {parsed.title && <div className="font-medium text-[var(--metis-fg)]">{parsed.title}</div>}
      {parsed.url && <div className="text-[10.5px] text-[var(--metis-fg-dim)] truncate">{parsed.url}</div>}
      {parsed.note && <div className="text-[var(--metis-fg-muted)]">{parsed.note}</div>}
      {parsed.error && <div className="text-rose-300">{parsed.error}</div>}
      {parsed.text && (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-[11px] text-[var(--metis-fg-muted)] border-t border-[var(--metis-border)] pt-1.5 mt-1.5">
          {parsed.text.slice(0, 2000)}{parsed.text.length > 2000 ? '\n…' : ''}
        </pre>
      )}
      {parsed.artifact && (
        <div className="text-[10.5px] text-violet-300">📎 {parsed.artifact.title}</div>
      )}
      {(parsed.buttons ?? []).length > 0 && (
        <div className="text-[10.5px] text-[var(--metis-fg-dim)]">
          <span className="font-medium">Buttons: </span>
          {(parsed.buttons as string[]).slice(0, 8).join(' · ')}
        </div>
      )}
      {(parsed.inputs ?? []).length > 0 && (
        <div className="text-[10.5px] text-[var(--metis-fg-dim)]">
          <span className="font-medium">Inputs: </span>
          {(parsed.inputs as { selector: string; type: string }[]).slice(0, 6).map(i => `${i.type} ${i.selector}`).join(' · ')}
        </div>
      )}
      {!parsed.title && !parsed.text && !parsed.note && !parsed.error && (
        <pre className="text-[10.5px] text-[var(--metis-fg-dim)] whitespace-pre-wrap break-words">
          {JSON.stringify(parsed, null, 2).slice(0, 800)}
        </pre>
      )}
    </div>
  );
}

function ShellOutput({ raw }: { raw: string }) {
  let parsed: Record<string, unknown> | null = null;
  try { parsed = JSON.parse(raw); } catch { /* show raw */ }

  if (!parsed) {
    return (
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-[11px] text-[var(--metis-code-fg)]">
        {raw}
      </pre>
    );
  }

  const ok = parsed.ok !== false && (parsed.exit_code === undefined || parsed.exit_code === 0);
  const isPending = parsed.confirm_required === true;

  return (
    <div className={`rounded-lg border p-2.5 text-[11.5px] space-y-1.5 ${isPending ? 'border-amber-500/30 bg-amber-500/5' : ok ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-rose-500/25 bg-rose-500/5'}`}>
      {isPending ? (
        <div className="text-amber-200 font-medium">Approval required — click &quot;Approve run&quot; to execute</div>
      ) : (
        <div className="flex items-center gap-2">
          <span className={`text-[10.5px] font-mono px-1.5 py-0.5 rounded ${ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'}`}>
            exit {String(parsed.exit_code ?? 0)}
          </span>
          {typeof parsed.duration_ms === 'number' && (
            <span className="text-[10px] text-[var(--metis-fg-dim)]">{parsed.duration_ms as number}ms</span>
          )}
          {typeof parsed.cmd === 'string' && (
            <code className="ml-auto text-[10px] text-[var(--metis-fg-dim)] truncate max-w-[200px]">{parsed.cmd as string}</code>
          )}
        </div>
      )}
      {typeof parsed.stdout === 'string' && parsed.stdout.trim() && (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-[11px] text-[var(--metis-fg)] border-t border-[var(--metis-border)] pt-1.5">
          {(parsed.stdout as string).slice(0, 4000)}{(parsed.stdout as string).length > 4000 ? '\n…' : ''}
        </pre>
      )}
      {typeof parsed.stderr === 'string' && (parsed.stderr as string).trim() && (
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words text-[11px] text-rose-300 border-t border-rose-500/20 pt-1.5">
          {(parsed.stderr as string).slice(0, 2000)}{(parsed.stderr as string).length > 2000 ? '\n…' : ''}
        </pre>
      )}
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function AutomationPanel({ client, reduceMotion, onClose }: Props) {
  const [tab, setTab] = useState<'browser' | 'shell'>('browser');

  // Browser state
  const [bUrl, setBUrl]             = useState('https://example.com');
  const [bOut, setBOut]             = useState('');
  const [bBusy, setBBusy]           = useState(false);
  const [clickTarget, setClickTarget] = useState('');
  const [byText, setByText]           = useState(true);
  const [fillSel, setFillSel]         = useState('');
  const [fillVal, setFillVal]         = useState('');
  const [extractSel, setExtractSel]   = useState('');

  // Shell state
  const [shellCmd, setShellCmd]     = useState('');
  const [shellCwd, setShellCwd]     = useState('');
  const [shellOut, setShellOut]     = useState('');
  const [shellBusy, setShellBusy]   = useState(false);
  const [pendingToken, setPendingToken] = useState<string | null>(null);

  const runBrowser = async (action: string, extra: Record<string, unknown> = {}) => {
    setBBusy(true);
    try {
      const res = await client.automationBrowser({
        action: action as never,
        url: action === 'goto' ? bUrl : undefined,
        ...extra,
      });
      setBOut(typeof res === 'string' ? res : JSON.stringify(res, null, 2));
    } catch (e) {
      setBOut(String(e instanceof Error ? e.message : e));
    } finally {
      setBBusy(false);
    }
  };

  const runShell = async (token?: string | null) => {
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
      } else {
        setPendingToken(null);
      }
      setShellOut(JSON.stringify(res, null, 2));
    } catch (e) {
      setShellOut(String(e instanceof Error ? e.message : e));
    } finally {
      setShellBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Automation"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur"
      >
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3 shrink-0">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Automation</div>
          <div className="ml-2 inline-flex items-center gap-0.5 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5">
            {([
              { key: 'browser', icon: Globe,    label: 'Browser' },
              { key: 'shell',   icon: Terminal, label: 'Shell'   },
            ] as { key: 'browser' | 'shell'; icon: typeof Globe; label: string }[]).map(({ key, icon: Icon, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11.5px] transition ${
                  tab === key
                    ? 'bg-violet-500/15 text-violet-200'
                    : 'text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]'
                }`}
              >
                <Icon className="h-3 w-3" />
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto metis-icon-btn"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">

          {tab === 'browser' && (
            <>
              <p className="text-[11.5px] text-[var(--metis-fg-dim)] leading-5">
                Headless Chromium via Playwright. Requires{' '}
                <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">playwright install chromium</code>.
                Localhost is blocked unless <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">METIS_BROWSER_ALLOW_LOCALHOST=1</code>.
              </p>

              {/* URL + core actions */}
              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3 space-y-2">
                <label className="grid gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">URL</span>
                  <input
                    value={bUrl}
                    onChange={(ev) => setBUrl(ev.target.value)}
                    className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
                  />
                </label>
                <div className="flex flex-wrap gap-1.5 items-center">
                  {([
                    { label: 'Start',      action: 'start'      },
                    { label: 'Goto + wait', action: 'goto'      },
                    { label: 'Snapshot',   action: 'snapshot',  accent: true },
                    { label: 'Screenshot', action: 'screenshot', icon: Camera },
                    { label: 'Close',      action: 'close'      },
                  ] as { label: string; action: string; accent?: boolean; icon?: typeof Camera }[]).map(({ label, action, accent }) => (
                    <button
                      key={action}
                      type="button"
                      disabled={bBusy}
                      onClick={() => void runBrowser(action)}
                      className={`rounded-lg border px-2.5 py-1 text-[11.5px] transition disabled:opacity-40 ${
                        accent
                          ? 'border-violet-500/30 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20'
                          : 'border-[var(--metis-border)] bg-[var(--metis-elevated)] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                  {bBusy && <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />}
                </div>
              </div>

              {/* Click */}
              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <MousePointer className="h-3 w-3 text-violet-300" />
                  <span className="text-[11px] font-medium text-[var(--metis-fg-dim)]">Click element</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    value={clickTarget}
                    onChange={(ev) => setClickTarget(ev.target.value)}
                    placeholder={byText ? 'Button label text…' : 'CSS selector…'}
                    className="flex-1 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
                  />
                  <label className="flex items-center gap-1 text-[11px] text-[var(--metis-fg-dim)] cursor-pointer select-none whitespace-nowrap">
                    <input
                      type="checkbox"
                      checked={byText}
                      onChange={(e) => setByText(e.target.checked)}
                      className="accent-violet-500"
                    />
                    by text
                  </label>
                  <button
                    type="button"
                    disabled={bBusy || !clickTarget.trim()}
                    onClick={() => void runBrowser('click', { target: clickTarget, by_text: byText })}
                    className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-2.5 py-1.5 text-[11.5px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-40"
                  >
                    Click
                  </button>
                </div>
              </div>

              {/* Fill */}
              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <Type className="h-3 w-3 text-violet-300" />
                  <span className="text-[11px] font-medium text-[var(--metis-fg-dim)]">Fill form field</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    value={fillSel}
                    onChange={(ev) => setFillSel(ev.target.value)}
                    placeholder="CSS selector (input, textarea…)"
                    className="flex-1 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
                  />
                  <input
                    value={fillVal}
                    onChange={(ev) => setFillVal(ev.target.value)}
                    placeholder="value"
                    className="w-28 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
                  />
                  <button
                    type="button"
                    disabled={bBusy || !fillSel.trim()}
                    onClick={() => void runBrowser('fill', { target: fillSel, value: fillVal })}
                    className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-2.5 py-1.5 text-[11.5px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-40"
                  >
                    Fill
                  </button>
                </div>
              </div>

              {/* Extract */}
              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
                <div className="flex items-center gap-1.5 mb-2">
                  <FileSearch className="h-3 w-3 text-violet-300" />
                  <span className="text-[11px] font-medium text-[var(--metis-fg-dim)]">Extract text</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    value={extractSel}
                    onChange={(ev) => setExtractSel(ev.target.value)}
                    placeholder="CSS selector — leave blank for full page"
                    className="flex-1 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 text-[12px] text-[var(--metis-fg)] outline-none focus:border-violet-500/50"
                  />
                  <button
                    type="button"
                    disabled={bBusy}
                    onClick={() => void runBrowser('extract', { selector: extractSel.trim() || null })}
                    className="rounded-lg border border-violet-500/30 bg-violet-500/10 px-2.5 py-1.5 text-[11.5px] text-violet-200 hover:bg-violet-500/20 disabled:opacity-40"
                  >
                    Extract
                  </button>
                </div>
              </div>

              {bOut && (
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Result</div>
                  <BrowserOutput raw={bOut} />
                </div>
              )}
            </>
          )}

          {tab === 'shell' && (
            <>
              <p className="text-[11.5px] text-[var(--metis-fg-dim)] leading-5">
                Allow-listed shell commands (git, python, npm, curl, etc.). First request returns an
                approval token — click <strong className="text-[var(--metis-fg)]">Approve run</strong> to actually execute.
              </p>

              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3 space-y-2">
                <label className="grid gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Command</span>
                  <input
                    value={shellCmd}
                    onChange={(ev) => setShellCmd(ev.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !shellBusy) void runShell(null); }}
                    placeholder="e.g. git status  or  where python"
                    className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 font-mono text-[12px] text-[var(--metis-fg)] outline-none focus:border-emerald-500/50"
                  />
                </label>
                <label className="grid gap-1">
                  <span className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">cwd (optional)</span>
                  <input
                    value={shellCwd}
                    onChange={(ev) => setShellCwd(ev.target.value)}
                    placeholder="Defaults to bridge process directory"
                    className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-1.5 font-mono text-[12px] text-[var(--metis-fg)] outline-none focus:border-emerald-500/50"
                  />
                </label>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={shellBusy || !shellCmd.trim()}
                    onClick={() => void runShell(null)}
                    className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-[11.5px] text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-40 flex items-center gap-1.5"
                  >
                    {shellBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                    Request run
                  </button>
                  {pendingToken && (
                    <button
                      type="button"
                      disabled={shellBusy}
                      onClick={() => void runShell(pendingToken)}
                      className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-1.5 text-[11.5px] text-amber-200 hover:bg-amber-500/20 disabled:opacity-40"
                    >
                      Approve run
                    </button>
                  )}
                </div>
              </div>

              {shellOut && (
                <div>
                  <div className="mb-1 text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)]">Result</div>
                  <ShellOutput raw={shellOut} />
                </div>
              )}

              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
                <div className="text-[10px] uppercase tracking-wide text-[var(--metis-fg-dim)] mb-1.5">Allow-listed programs</div>
                <div className="flex flex-wrap gap-1">
                  {['git', 'python', 'node', 'npm', 'npx', 'pip', 'pytest', 'ruff', 'ls', 'dir', 'cat', 'curl', 'wget', 'ollama', 'uvicorn'].map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setShellCmd(p + ' ')}
                      className="rounded border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--metis-fg-dim)] hover:text-[var(--metis-fg)] hover:bg-[var(--metis-hover-surface)] transition"
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}
