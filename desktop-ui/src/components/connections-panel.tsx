'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  RefreshCw,
  X,
  Cloud,
  HardDrive,
  Phone,
  Mail,
  Check,
  Copy,
  AlertCircle,
} from 'lucide-react';
import { MetisClient, ProviderStatus, SystemHealth } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

const PROVIDERS: Array<{
  key: keyof Omit<SystemHealth, 'checked_at' | 'preferred_manager'>;
  label: string;
  blurb: string;
  envHint: string;
  icon: typeof Cloud;
}> = [
  { key: 'ollama', label: 'Local Ollama',  blurb: 'Local models on your machine.',                envHint: '',                              icon: HardDrive },
  { key: 'groq',   label: 'Groq',          blurb: 'Free, very fast 70B-class chat.',              envHint: 'GROQ_API_KEY=gsk_…',            icon: Cloud },
  { key: 'glm',    label: 'Z.ai GLM-4.6',  blurb: 'Smart cloud model from Zhipu / Z.ai.',         envHint: 'GLM_API_KEY=…',                 icon: Cloud },
  { key: 'openai', label: 'OpenAI',        blurb: 'GPT-class chat (paid).',                       envHint: 'OPENAI_API_KEY=sk-…',           icon: Cloud },
  { key: 'twilio', label: 'Twilio (SMS)',  blurb: 'Texts you when notify-on-fire is on.',         envHint: 'TWILIO_SID=AC…\\nTWILIO_TOKEN=…\\nTWILIO_FROM=+1…\\nMETIS_NOTIFY_PHONE=+1…', icon: Phone },
  { key: 'smtp',   label: 'SMTP (email)',  blurb: 'Emails you the same.',                         envHint: 'EMAIL_USER=you@gmail.com\\nEMAIL_PASS=<app-password>\\nMETIS_NOTIFY_EMAIL=you@gmail.com', icon: Mail },
];

function dotColor(p?: ProviderStatus): string {
  if (!p) return 'bg-[var(--metis-fg-dim)]';
  return p.ok ? 'bg-emerald-400' : 'bg-rose-400';
}

export default function ConnectionsPanel({ client, reduceMotion, onClose }: Props) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true); setError(null);
    try { setHealth(await client.getSystemHealth()); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }, [client]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const copyEnvHint = async (provider: string, hint: string) => {
    if (!hint) return;
    try {
      await navigator.clipboard.writeText(hint.replaceAll('\\n', '\n'));
      setCopied(provider);
      setTimeout(() => setCopied(null), 1500);
    } catch {}
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog" aria-modal="true" aria-label="Connections"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border max-h-[80vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur"
      >
        <div className="flex items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Connections</div>
          {health?.preferred_manager && (
            <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
              chat: {health.preferred_manager}
            </span>
          )}
          <button type="button" onClick={refresh} disabled={busy}
            className="ml-auto metis-icon-btn" aria-label="Refresh" title="Re-test all">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button type="button" onClick={onClose} className="metis-icon-btn" aria-label="Close" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[calc(80vh-56px)] overflow-y-auto px-4 py-3">
          {error && (
            <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200">
              {error}
            </div>
          )}

          {!health ? (
            <div className="flex items-center gap-2 py-6 text-sm text-[var(--metis-fg-muted)]">
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Probing providers…
            </div>
          ) : (
            <ul className="grid gap-2">
              {PROVIDERS.map(({ key, label, blurb, envHint, icon: Icon }) => {
                const p = health[key];
                return (
                  <li key={key} className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-3">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)] text-violet-300">
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`inline-block h-2 w-2 rounded-full ${dotColor(p)}`} />
                          <span className="text-[13.5px] font-medium text-[var(--metis-fg)]">{label}</span>
                          {p?.ok && p.model && (
                            <code className="ml-auto rounded bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[10.5px] text-[var(--metis-code-fg)]">{p.model}</code>
                          )}
                          {p?.ok && p.models !== undefined && (
                            <code className="ml-auto rounded bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[10.5px] text-[var(--metis-code-fg)]">{p.models} models</code>
                          )}
                        </div>
                        <p className="mt-0.5 text-[11.5px] text-[var(--metis-fg-dim)]">{blurb}</p>
                        {p?.ok && p.destination && (
                          <p className="mt-1 text-[11px] text-emerald-300/80">→ {p.destination}</p>
                        )}
                        {!p?.ok && (
                          <div className="mt-2 grid gap-2">
                            <p className="flex items-start gap-1.5 text-[11.5px] text-rose-200">
                              <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                              {p?.reason || 'unknown error'}
                            </p>
                            {(p?.fix || envHint) && (
                              <div className="flex items-start gap-2 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2.5 py-2">
                                <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] text-[var(--metis-fg-muted)]">
                                  {envHint || p?.fix}
                                </pre>
                                {envHint && (
                                  <button
                                    type="button"
                                    onClick={() => copyEnvHint(label, envHint)}
                                    className="shrink-0 rounded-md border border-[var(--metis-border)] bg-[var(--metis-bg)] px-1.5 py-1 text-[10px] text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]"
                                    title="Copy template"
                                  >
                                    {copied === label ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          <p className="mt-4 text-[11px] leading-5 text-[var(--metis-fg-dim)]">
            After editing <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">.env</code>, restart the bridge (close this app and run <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">python launch.py</code> again) and click Refresh here.
          </p>
        </div>
      </motion.div>
    </div>
  );
}
