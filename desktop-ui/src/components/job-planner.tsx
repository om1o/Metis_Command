'use client';

import { useMemo, useState, FormEvent } from 'react';
import { motion } from 'framer-motion';
import { Bell, CalendarClock, Loader2, Repeat, Sparkles, X } from 'lucide-react';
import { MetisClient, Schedule, ScheduleKind } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

type Cadence = 'daily' | 'hourly' | 'every_n_hours' | 'cron';

interface Props {
  goal: string;
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
  onCreated: (s: Schedule) => void;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}

// ── cadence → backend (kind, spec) ─────────────────────────────────────────

function buildSchedulePayload(c: Cadence, dailyTime: string, everyN: number, cron: string): { kind: ScheduleKind; spec: string } | { error: string } {
  if (c === 'daily') {
    if (!/^\d{2}:\d{2}$/.test(dailyTime)) return { error: 'Pick a time like 09:00.' };
    return { kind: 'daily', spec: dailyTime };
  }
  if (c === 'hourly') return { kind: 'interval', spec: '60' };
  if (c === 'every_n_hours') {
    const n = Math.max(1, Math.min(168, Math.floor(everyN || 0)));
    return { kind: 'interval', spec: String(n * 60) };
  }
  // cron
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return { error: 'Cron must be 5 fields (m h dom mon dow). Example: 0 9 * * mon-fri' };
  return { kind: 'cron', spec: cron.trim() };
}

function describe(c: Cadence, dailyTime: string, everyN: number, cron: string): string {
  if (c === 'daily') return `every day at ${dailyTime}`;
  if (c === 'hourly') return 'every hour';
  if (c === 'every_n_hours') return `every ${Math.max(1, everyN)} hour${everyN === 1 ? '' : 's'}`;
  return `cron ${cron.trim() || '0 9 * * *'}`;
}

const CADENCES: { id: Cadence; label: string }[] = [
  { id: 'daily', label: 'Daily' },
  { id: 'hourly', label: 'Hourly' },
  { id: 'every_n_hours', label: 'Every N hours' },
  { id: 'cron', label: 'Cron' },
];

export default function JobPlanner({ goal, client, reduceMotion, onClose, onCreated }: Props) {
  const [cadence, setCadence] = useState<Cadence>('daily');
  const now = new Date();
  const defaultTime = `${pad(now.getHours())}:00`;
  const [dailyTime, setDailyTime] = useState(defaultTime);
  const [everyN, setEveryN] = useState(6);
  const [cron, setCron] = useState('0 9 * * mon-fri');
  const [autoApprove, setAutoApprove] = useState(true);
  const [notify, setNotify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const summary = useMemo(
    () => describe(cadence, dailyTime, everyN, cron),
    [cadence, dailyTime, everyN, cron],
  );

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    const payload = buildSchedulePayload(cadence, dailyTime, everyN, cron);
    if ('error' in payload) {
      setError(payload.error);
      return;
    }
    setBusy(true);
    try {
      const s = await client.createSchedule({
        goal,
        kind: payload.kind,
        spec: payload.spec,
        auto_approve: autoApprove,
        notify,
      });
      onCreated(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Schedule this job"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border w-full max-w-lg rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-4 shadow-2xl backdrop-blur"
      >
        <div className="flex items-center gap-2.5">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Schedule this job</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Repeat className="h-3 w-3" /> Job
          </span>
          <button type="button" onClick={onClose} className="ml-auto metis-icon-btn" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={submit} className="mt-4 grid gap-3.5">
          {/* Goal preview */}
          <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5">
            <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Goal</div>
            <p className="text-[13.5px] leading-6 text-[var(--metis-fg)]">{goal}</p>
          </div>

          {/* Cadence picker */}
          <div className="grid gap-1.5">
            <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Cadence</span>
            <div role="radiogroup" aria-label="Cadence" className="inline-flex flex-wrap items-center gap-1 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5">
              {CADENCES.map((c) => {
                const sel = cadence === c.id;
                return (
                  <button
                    key={c.id}
                    type="button"
                    role="radio"
                    aria-checked={sel}
                    onClick={() => setCadence(c.id)}
                    className={`rounded-lg px-2.5 py-1.5 text-[12px] transition ${
                      sel
                        ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-fg)]'
                        : 'text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]'
                    }`}
                  >
                    {c.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Cadence-specific input */}
          {cadence === 'daily' && (
            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Run at</span>
              <input
                type="time"
                value={dailyTime}
                onChange={(e) => setDailyTime(e.target.value)}
                step={60}
                className="w-40 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-sm outline-none focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
              />
            </label>
          )}
          {cadence === 'every_n_hours' && (
            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Every</span>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  max={168}
                  value={everyN}
                  onChange={(e) => setEveryN(Number(e.target.value))}
                  className="w-24 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-sm outline-none focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
                />
                <span className="text-[12.5px] text-[var(--metis-fg-muted)]">hours</span>
              </div>
            </label>
          )}
          {cadence === 'cron' && (
            <label className="grid gap-1">
              <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Cron expression</span>
              <input
                type="text"
                value={cron}
                onChange={(e) => setCron(e.target.value)}
                placeholder="m h dom mon dow"
                className="w-full rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 font-mono text-sm outline-none focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
              />
              <span className="text-[11px] text-[var(--metis-fg-dim)]">Example: <code>0 9 * * mon-fri</code> = 9am Mon–Fri.</span>
            </label>
          )}

          {/* Auto-approve toggle */}
          <label className="flex items-start gap-2.5 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5 text-[13px]">
            <input
              type="checkbox"
              checked={autoApprove}
              onChange={(e) => setAutoApprove(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-violet-500"
            />
            <span>
              <span className="block text-[var(--metis-fg)]">Run unattended</span>
              <span className="block text-[11.5px] text-[var(--metis-fg-dim)]">
                Skip the approval prompt each run. You can still pause the job from the Jobs panel.
              </span>
            </span>
          </label>

          {/* Notify toggle */}
          <label className="flex items-start gap-2.5 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5 text-[13px]">
            <input
              type="checkbox"
              checked={notify}
              onChange={(e) => setNotify(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-violet-500"
            />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-[var(--metis-fg)]">
                <Bell className="h-3.5 w-3.5 text-violet-400" />
                Text + email me when this fires
              </span>
              <span className="block text-[11.5px] text-[var(--metis-fg-dim)]">
                Sends to <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">METIS_NOTIFY_PHONE</code> via Twilio and <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">METIS_NOTIFY_EMAIL</code> via SMTP. Set them in <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">.env</code> first; otherwise this is silently a no-op.
              </span>
            </span>
          </label>

          {/* Summary */}
          <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 px-3 py-2.5 text-[12.5px] text-violet-200">
            <Sparkles className="mr-1 inline h-3.5 w-3.5" />
            Will run <span className="font-medium text-violet-100">{summary}</span>.
          </div>

          {error && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200" role="alert">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-3 py-2 text-sm text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
              style={{ background: 'var(--metis-accent)' }}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
              Schedule job
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  );
}
