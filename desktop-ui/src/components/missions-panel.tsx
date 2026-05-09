'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  RefreshCw,
  X,
  Workflow,
  Play,
  Trash2,
  AlertCircle,
  CheckCircle2,
  CircleDot,
  PauseCircle,
  XCircle,
  Clock,
} from 'lucide-react';
import {
  MetisClient,
  PersistedMission,
  PersistedMissionDetail,
} from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

function fmtRelative(ts: number): string {
  if (!ts) return '';
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - ts);
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function fmtDuration(start: number, end: number | null): string {
  if (!start) return '';
  const e = end || Date.now() / 1000;
  const dur = Math.max(0, e - start);
  if (dur < 60) return `${dur.toFixed(1)}s`;
  if (dur < 3600) return `${Math.floor(dur / 60)}m ${Math.floor(dur % 60)}s`;
  return `${Math.floor(dur / 3600)}h ${Math.floor((dur % 3600) / 60)}m`;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  pending:  <Clock        className="h-3.5 w-3.5 text-slate-400" />,
  running:  <CircleDot    className="h-3.5 w-3.5 animate-pulse text-violet-300" />,
  paused:   <PauseCircle  className="h-3.5 w-3.5 text-amber-300" />,
  success:  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />,
  failed:   <XCircle      className="h-3.5 w-3.5 text-rose-300" />,
  stopped:  <XCircle      className="h-3.5 w-3.5 text-slate-400" />,
};

const STATUS_COLOR: Record<string, string> = {
  pending: 'text-slate-300 border-slate-500/30 bg-slate-500/10',
  running: 'text-violet-200 border-violet-500/30 bg-violet-500/10',
  paused:  'text-amber-200 border-amber-500/30 bg-amber-500/10',
  success: 'text-emerald-200 border-emerald-500/30 bg-emerald-500/10',
  failed:  'text-rose-200 border-rose-500/30 bg-rose-500/10',
  stopped: 'text-slate-300 border-slate-500/30 bg-slate-500/10',
};

export default function MissionsPanel({ client, reduceMotion, onClose }: Props) {
  const [items, setItems] = useState<PersistedMission[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<PersistedMissionDetail | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoadingList(true);
    setError(null);
    try {
      const list = await client.listPersistedMissions({ limit: 60 });
      setItems(list);
      // Auto-select the newest if nothing selected, OR if the
      // current selection vanished (e.g. just deleted).
      if (list.length > 0 && (!activeId || !list.some((m) => m.id === activeId))) {
        setActiveId(list[0].id);
      }
      if (list.length === 0) setActiveId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingList(false);
    }
  }, [client, activeId]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  // Load full detail whenever the active mission changes. The
  // detail-clear branch is wrapped in queueMicrotask too to satisfy
  // React 19's set-state-in-effect rule.
  useEffect(() => {
    let cancelled = false;
    if (!activeId) {
      queueMicrotask(() => { if (!cancelled) setDetail(null); });
      return () => { cancelled = true; };
    }
    queueMicrotask(async () => {
      if (cancelled) return;
      setLoadingDetail(true);
      try {
        const d = await client.getPersistedMission(activeId);
        if (!cancelled) setDetail(d);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    });
    return () => { cancelled = true; };
  }, [activeId, client]);

  const onResume = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await client.resumePersistedMission(id);
      // Optimistically flip the row to running; the next refresh
      // confirms.
      setItems((prev) => prev ? prev.map((m) => m.id === id ? { ...m, status: 'running' } : m) : prev);
      // Give the worker a moment, then re-pull state.
      setTimeout(() => { queueMicrotask(refresh); }, 800);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const onDelete = async (id: string) => {
    setBusy(id);
    setError(null);
    try {
      await client.deletePersistedMission(id);
      if (activeId === id) setActiveId(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const canResume = (s: string): boolean => s === 'paused' || s === 'failed' || s === 'stopped';

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Missions"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border max-h-[85vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur"
      >
        <div className="flex items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Missions</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Workflow className="h-3 w-3" /> {(items || []).length}
          </span>
          <button
            type="button"
            onClick={refresh}
            disabled={loadingList}
            className="ml-auto metis-icon-btn"
            aria-label="Refresh"
            title="Refresh"
          >
            {loadingList ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button type="button" onClick={onClose} className="metis-icon-btn" aria-label="Close" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid h-[calc(85vh-56px)] grid-cols-[300px_1fr]">
          {/* Mission list */}
          <div className="overflow-y-auto border-r border-[var(--metis-border)] py-2">
            {!items ? (
              <div className="flex items-center gap-2 px-4 py-6 text-[12.5px] text-[var(--metis-fg-muted)]">
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading…
              </div>
            ) : items.length === 0 ? (
              <div className="mx-3 mt-2 rounded-xl border border-dashed border-[var(--metis-border)] p-3 text-[11.5px] text-[var(--metis-fg-dim)]">
                No missions yet. Autonomous missions kicked off via the chat or schedules will show up here.
              </div>
            ) : (
              <ul className="grid gap-0.5">
                {items.map((m) => {
                  const sel = activeId === m.id;
                  const status = m.status || 'pending';
                  const dur = fmtDuration(m.started_at, m.ended_at);
                  return (
                    <li key={m.id}>
                      <button
                        type="button"
                        onClick={() => setActiveId(m.id)}
                        className={`flex w-full flex-col gap-1 px-3 py-2 text-left transition ${
                          sel
                            ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-fg)]'
                            : 'text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          {STATUS_ICON[status] || STATUS_ICON.pending}
                          <span className="line-clamp-1 flex-1 text-[12.5px] font-medium">{m.goal || '(no goal)'}</span>
                        </div>
                        <div className="flex items-center gap-2 text-[10.5px] text-[var(--metis-fg-dim)]">
                          <span className="font-mono">{m.id.slice(0, 8)}</span>
                          <span>·</span>
                          <span>{fmtRelative(m.started_at)}</span>
                          {dur ? <><span>·</span><span>{dur}</span></> : null}
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Detail */}
          <div className="overflow-y-auto px-5 py-4">
            {error && (
              <div className="mb-3 flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {error}
              </div>
            )}
            {loadingDetail && !detail ? (
              <div className="flex items-center gap-2 py-6 text-[12.5px] text-[var(--metis-fg-muted)]">
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading mission…
              </div>
            ) : !detail ? (
              <div className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
                <div className="inline-flex items-center gap-2 text-[var(--metis-fg)]">
                  <Workflow className="h-4 w-4 text-violet-400" /> No mission selected
                </div>
                <p className="mt-1">Pick a mission on the left to see its full step trail.</p>
              </div>
            ) : (
              <div className="grid gap-4">
                {/* Header */}
                <div className="flex flex-wrap items-start gap-2">
                  <div className="flex-1 min-w-[200px]">
                    <div className="text-[15px] font-semibold text-[var(--metis-fg)]">{detail.goal}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--metis-fg-dim)]">
                      <span className="font-mono">{detail.id.slice(0, 12)}</span>
                      <span>·</span>
                      <span>started {fmtRelative(detail.started_at)}</span>
                      <span>·</span>
                      <span>{fmtDuration(detail.started_at, detail.ended_at)}</span>
                    </div>
                  </div>
                  <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${STATUS_COLOR[detail.status] || STATUS_COLOR.pending}`}>
                    {STATUS_ICON[detail.status] || STATUS_ICON.pending}
                    {detail.status}
                  </span>
                  {canResume(detail.status) && (
                    <button
                      type="button"
                      onClick={() => onResume(detail.id)}
                      disabled={busy === detail.id}
                      className="inline-flex items-center gap-1 rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200 hover:bg-violet-500/15 disabled:opacity-50"
                      title="Resume from the last successful step"
                    >
                      {busy === detail.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                      Resume
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onDelete(detail.id)}
                    disabled={busy === detail.id}
                    className="inline-flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-200 hover:bg-rose-500/15 disabled:opacity-50"
                    title="Delete this mission record"
                  >
                    {busy === detail.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                    Delete
                  </button>
                </div>

                {/* Final answer */}
                {detail.final_answer ? (
                  <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-3">
                    <div className="text-[11px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Answer</div>
                    <div className="mt-1 whitespace-pre-wrap text-[13.5px] leading-6 text-[var(--metis-fg)]">{detail.final_answer}</div>
                  </div>
                ) : null}

                {/* Steps */}
                <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)]">
                  <div className="border-b border-[var(--metis-border)] px-4 py-2 text-[11px] uppercase tracking-widest text-[var(--metis-fg-dim)]">
                    Steps ({detail.steps.length})
                  </div>
                  <ol className="divide-y divide-[var(--metis-border)]">
                    {detail.steps.map((s) => {
                      const ok = s.ok;
                      const obs = typeof s.observation === 'string'
                        ? s.observation
                        : JSON.stringify(s.observation);
                      return (
                        <li key={s.index} className="px-4 py-3">
                          <div className="flex items-baseline gap-2">
                            <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] ${ok ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' : 'border-rose-500/40 bg-rose-500/10 text-rose-200'}`}>
                              {s.index}
                            </span>
                            <div className="flex-1 text-[13px] text-[var(--metis-fg)]">{s.description}</div>
                            <span className="text-[10.5px] text-[var(--metis-fg-dim)]">
                              {s.tool ? <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">{s.tool}</code> : null}
                              {s.duration_ms ? ` · ${s.duration_ms}ms` : null}
                            </span>
                          </div>
                          {obs ? (
                            <pre className="mt-1.5 max-h-32 overflow-y-auto whitespace-pre-wrap rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1.5 text-[11.5px] leading-5 text-[var(--metis-fg-muted)]">
                              {obs.slice(0, 800)}
                            </pre>
                          ) : null}
                        </li>
                      );
                    })}
                  </ol>
                </div>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
