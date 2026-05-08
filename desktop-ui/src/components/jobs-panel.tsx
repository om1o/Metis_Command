'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  CalendarClock,
  Loader2,
  Pause,
  Play,
  Trash2,
  X,
  RefreshCw,
  Repeat,
  Sparkles,
} from 'lucide-react';
import { MetisClient, Schedule } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

function fmtNext(ts: number | null): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  const ms = d.getTime() - Date.now();
  if (ms < 0) return 'overdue';
  if (ms < 60_000) return 'in <1m';
  if (ms < 3_600_000) return `in ${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `in ${Math.floor(ms / 3_600_000)}h`;
  return d.toLocaleString();
}

function fmtCadence(s: Schedule): string {
  if (s.kind === 'daily') return `every day at ${s.spec}`;
  if (s.kind === 'interval') {
    const m = parseInt(s.spec, 10);
    if (!Number.isFinite(m) || m <= 0) return 'often';
    if (m === 60) return 'hourly';
    if (m % 1440 === 0) return `every ${m / 1440}d`;
    if (m % 60 === 0)   return `every ${m / 60}h`;
    return `every ${m}m`;
  }
  if (s.kind === 'cron') return `cron ${s.spec}`;
  return s.spec;
}

export default function JobsPanel({ client, reduceMotion, onClose }: Props) {
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const list = await client.listSchedules();
      // Newest first; built-in actions (daily_briefing etc.) sink below user jobs.
      list.sort((a, b) => {
        const aBuilt = a.action ? 1 : 0;
        const bBuilt = b.action ? 1 : 0;
        if (aBuilt !== bBuilt) return aBuilt - bBuilt;
        return b.created_at - a.created_at;
      });
      setItems(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  // Defer the first fetch so the effect body itself is side-effect-free
  // (React 19 lint flags synchronous setState in an effect body).
  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const onToggle = async (id: string) => {
    setBusyId(id);
    try {
      await client.toggleSchedule(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (id: string) => {
    setBusyId(id);
    try {
      await client.deleteSchedule(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const userJobs = (items || []).filter((s) => !s.action);
  const builtIns = (items || []).filter((s) => !!s.action);

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Jobs"
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
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Jobs</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Repeat className="h-3 w-3" /> {userJobs.length}
          </span>
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="ml-auto metis-icon-btn"
            aria-label="Refresh"
            title="Refresh"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button type="button" onClick={onClose} className="metis-icon-btn" aria-label="Close" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[calc(80vh-56px)] overflow-y-auto px-4 py-3">
          {error && (
            <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200" role="alert">
              {error}
            </div>
          )}

          {!items ? (
            <div className="flex items-center gap-2 py-6 text-sm text-[var(--metis-fg-muted)]">
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading jobs…
            </div>
          ) : items.length === 0 ? (
            <EmptyState />
          ) : (
            <>
              {userJobs.length > 0 ? (
                <div className="grid gap-2">
                  {userJobs.map((s) => (
                    <JobRow
                      key={s.id}
                      s={s}
                      busy={busyId === s.id}
                      onToggle={() => onToggle(s.id)}
                      onDelete={() => onDelete(s.id)}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState />
              )}

              {builtIns.length > 0 && (
                <details className="mt-4 group">
                  <summary className="cursor-pointer text-[11px] uppercase tracking-widest text-[var(--metis-fg-dim)] hover:text-[var(--metis-fg-muted)]">
                    System jobs ({builtIns.length})
                  </summary>
                  <div className="mt-2 grid gap-2">
                    {builtIns.map((s) => (
                      <JobRow
                        key={s.id}
                        s={s}
                        busy={busyId === s.id}
                        onToggle={() => onToggle(s.id)}
                        onDelete={() => onDelete(s.id)}
                        readonly
                      />
                    ))}
                  </div>
                </details>
              )}
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
      <div className="inline-flex items-center gap-2 text-[var(--metis-fg)]">
        <CalendarClock className="h-4 w-4 text-violet-400" /> No jobs yet
      </div>
      <p>
        Switch the composer to <span className="inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-[11px] text-violet-200"><Sparkles className="h-3 w-3" /> Job</span>, type what you want done, and pick a cadence. It&apos;ll show up here.
      </p>
    </div>
  );
}

function JobRow({
  s,
  busy,
  onToggle,
  onDelete,
  readonly,
}: {
  s: Schedule;
  busy: boolean;
  onToggle: () => void;
  onDelete: () => void;
  readonly?: boolean;
}) {
  return (
    <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5">
      <div className="flex items-start gap-2.5">
        <span
          className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${
            s.enabled ? 'bg-emerald-400' : 'bg-[var(--metis-fg-dim)]'
          }`}
          aria-label={s.enabled ? 'Enabled' : 'Paused'}
        />
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] leading-5 text-[var(--metis-fg)]" style={{ wordBreak: 'break-word' }}>
            {s.goal}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11.5px] text-[var(--metis-fg-dim)]">
            <span className="inline-flex items-center gap-1">
              <Repeat className="h-3 w-3" /> {fmtCadence(s)}
            </span>
            <span>Next: {fmtNext(s.next_run)}</span>
            {s.action && (
              <span className="rounded-full border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-1.5 py-0.5 text-[10px] uppercase tracking-widest">
                {s.action}
              </span>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={onToggle}
            disabled={busy || readonly}
            className="metis-icon-btn disabled:opacity-40"
            aria-label={s.enabled ? 'Pause' : 'Resume'}
            title={s.enabled ? 'Pause' : 'Resume'}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : s.enabled ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy || readonly}
            className="metis-icon-btn text-rose-400/80 hover:text-rose-400 disabled:opacity-40"
            aria-label="Delete"
            title={readonly ? 'System job — delete disabled' : 'Delete'}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
