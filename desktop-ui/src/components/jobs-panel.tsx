'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Bell,
  CalendarClock,
  FileText,
  Loader2,
  Pause,
  Play,
  Trash2,
  X,
  RefreshCw,
  Repeat,
  Sparkles,
} from 'lucide-react';
import { Artifact, MetisClient, Mission, Schedule } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
  onOpenArtifact: (id: string) => void;
}

function fmtNext(ts: number | null): string {
  if (!ts) return '-';
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

function artifactTs(artifact: Artifact): number {
  const raw = artifact.created_at ?? artifact.metadata?.created_at ?? artifact.metadata?.ts ?? 0;
  if (typeof raw === 'number') return raw > 10_000_000_000 ? raw / 1000 : raw;
  const parsed = Date.parse(String(raw));
  return Number.isFinite(parsed) ? parsed / 1000 : 0;
}

function missionTitle(mission: Mission): string {
  return mission.goal
    .replace(/^\[Metis run contract\][\s\S]*?\[\/Metis run contract\]\s*/i, '')
    .split('\n')[0]
    .trim()
    .slice(0, 120) || mission.id;
}

function fmtMissionTime(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  if (isNaN(d.getTime())) return '';
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function eventText(event: Record<string, unknown>): string {
  const kind = String(event.type || 'event');
  const detail = event.description || event.answer || event.error || event.status || event.message || '';
  return `${kind}${detail ? ` - ${String(detail).slice(0, 220)}` : ''}`;
}

export default function JobsPanel({ client, reduceMotion, onClose, onOpenArtifact }: Props) {
  const [items, setItems] = useState<Schedule[] | null>(null);
  const [reports, setReports] = useState<Record<string, Artifact>>({});
  const [missions, setMissions] = useState<Mission[]>([]);
  const [openMissionId, setOpenMissionId] = useState<string | null>(null);
  const [runState, setRunState] = useState<Record<string, { missionId?: string; status: string }>>({});
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const [list, artifacts, missionList] = await Promise.all([
        client.listSchedules(),
        client.getArtifacts(100),
        client.listMissions(20),
      ]);
      // Newest first; built-in actions (daily_briefing etc.) sink below user jobs.
      list.sort((a, b) => {
        const aBuilt = a.action ? 1 : 0;
        const bBuilt = b.action ? 1 : 0;
        if (aBuilt !== bBuilt) return aBuilt - bBuilt;
        return b.created_at - a.created_at;
      });
      setItems(list);
      const latestReports: Record<string, Artifact> = {};
      for (const artifact of artifacts) {
        if (artifact.metadata?.kind !== 'scheduled_job_report' || typeof artifact.metadata.schedule_id !== 'string') {
          continue;
        }
        const scheduleId = String(artifact.metadata.schedule_id);
        const current = latestReports[scheduleId];
        if (!current || artifactTs(artifact) > artifactTs(current)) latestReports[scheduleId] = artifact;
      }
      setReports(latestReports);
      setMissions(missionList.filter((m) => m.tag?.startsWith('scheduled:')).slice(0, 8));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  // Defer the first fetch so the effect body itself is side-effect-free
  // (React 19 lint flags synchronous setState in an effect body).
  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const activeRuns = useMemo(
    () => Object.entries(runState).filter(([, state]) => state.missionId && ['queued', 'running'].includes(state.status)),
    [runState],
  );

  useEffect(() => {
    if (activeRuns.length === 0) return;
    let cancelled = false;

    const poll = async () => {
      const updates = await Promise.all(
        activeRuns.map(async ([scheduleId, state]) => {
          try {
            const mission = await client.getMission(state.missionId!);
            return [scheduleId, mission] as const;
          } catch {
            return [scheduleId, null] as const;
          }
        }),
      );
      if (cancelled) return;
      let terminal = false;
      setRunState((current) => {
        const next = { ...current };
        for (const [scheduleId, mission] of updates) {
          if (!mission) continue;
          next[scheduleId] = { missionId: mission.id, status: mission.status };
          if (!['queued', 'running'].includes(mission.status)) terminal = true;
        }
        return next;
      });
      if (terminal) await refresh();
    };

    const timer = window.setInterval(poll, 2500);
    queueMicrotask(poll);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeRuns, client, refresh]);

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

  const onRunNow = async (id: string) => {
    setBusyId(id);
    try {
      const result = await client.runScheduleNow(id);
      setRunState((current) => ({
        ...current,
        [id]: { missionId: result.mission_id, status: result.status },
      }));
      setError(null);
      if (!result.mission_id) await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onCancelRun = async (id: string, missionId?: string) => {
    if (!missionId) return;
    setBusyId(id);
    try {
      const result = await client.cancelMission(missionId);
      if (!result.ok) {
        setError('That run is already active and could not be cancelled.');
        return;
      }
      setRunState((current) => ({
        ...current,
        [id]: { missionId, status: 'cancelled' },
      }));
      setError(null);
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
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading jobs...
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
                      onRunNow={() => onRunNow(s.id)}
                      onCancelRun={() => onCancelRun(s.id, runState[s.id]?.missionId)}
                      runState={runState[s.id]}
                      report={reports[s.id]}
                      onOpenReport={() => reports[s.id] && onOpenArtifact(reports[s.id].id)}
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
                        onRunNow={() => onRunNow(s.id)}
                        onCancelRun={() => onCancelRun(s.id, runState[s.id]?.missionId)}
                        runState={runState[s.id]}
                        report={reports[s.id]}
                        onOpenReport={() => reports[s.id] && onOpenArtifact(reports[s.id].id)}
                        readonly
                      />
                    ))}
                  </div>
                </details>
              )}

              {missions.length > 0 && (
                <section className="mt-4">
                  <div className="mb-2 text-[11px] uppercase tracking-widest text-[var(--metis-fg-dim)]">
                    Recent runs
                  </div>
                  <div className="grid gap-1.5">
                    {missions.map((mission) => (
                      <MissionRow
                        key={mission.id}
                        mission={mission}
                        open={openMissionId === mission.id}
                        onToggle={() => setOpenMissionId((current) => current === mission.id ? null : mission.id)}
                      />
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function MissionRow({
  mission,
  open,
  onToggle,
}: {
  mission: Mission;
  open: boolean;
  onToggle: () => void;
}) {
  const active = ['queued', 'running'].includes(mission.status);
  const events = (mission.events || []).slice(-4);
  return (
    <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${active ? 'bg-violet-400' : mission.status === 'success' ? 'bg-emerald-400' : mission.status === 'failed' ? 'bg-rose-400' : 'bg-[var(--metis-fg-dim)]'}`} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12.5px] text-[var(--metis-fg)]">{missionTitle(mission)}</p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10.5px] text-[var(--metis-fg-dim)]">
            <span className="capitalize">{mission.status}</span>
            <span className="font-mono">{mission.id}</span>
            {fmtMissionTime(mission.submitted_at) && <span>{fmtMissionTime(mission.submitted_at)}</span>}
          </div>
        </div>
      </button>
      {open && (
        <div className="border-t border-[var(--metis-border)] px-3 py-2 text-[11.5px] text-[var(--metis-fg-muted)]">
          {mission.final_answer && (
            <div>
              <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Result</div>
              <p className="max-h-24 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--metis-elevated)] px-2 py-1.5">
                {mission.final_answer}
              </p>
            </div>
          )}
          {events.length > 0 && (
            <div className={mission.final_answer ? 'mt-2' : ''}>
              <div className="mb-1 text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">Events</div>
              <ul className="grid gap-1">
                {events.map((event, idx) => (
                  <li key={`${mission.id}-${idx}`} className="truncate rounded-md bg-[var(--metis-elevated)] px-2 py-1">
                    {eventText(event)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!mission.final_answer && events.length === 0 && (
            <p className="text-[var(--metis-fg-dim)]">No run detail recorded yet.</p>
          )}
        </div>
      )}
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
  onRunNow,
  onCancelRun,
  runState,
  report,
  onOpenReport,
  readonly,
}: {
  s: Schedule;
  busy: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onRunNow: () => void;
  onCancelRun: () => void;
  runState?: { missionId?: string; status: string };
  report?: Artifact;
  onOpenReport: () => void;
  readonly?: boolean;
}) {
  const canCancelRun = !!runState?.missionId && ['queued', 'running'].includes(runState.status);

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
            {s.notify && (
              <span className="inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-300" title="Texts + emails you when this fires">
                <Bell className="h-2.5 w-2.5" /> Notify
              </span>
            )}
            {s.action && (
              <span className="rounded-full border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-1.5 py-0.5 text-[10px] uppercase tracking-widest">
                {s.action}
              </span>
            )}
          </div>
          {report && (
            <button
              type="button"
              onClick={onOpenReport}
              className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[11px] text-emerald-200 hover:bg-emerald-500/15"
            >
              <FileText className="h-3 w-3" />
              Latest report
            </button>
          )}
          {runState && (
            <div className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200">
              {['queued', 'running'].includes(runState.status) ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
              <span className="capitalize">{runState.status}</span>
              {runState.missionId && <span className="font-mono text-[10px] text-violet-300/80">{runState.missionId}</span>}
              {canCancelRun && (
                <button
                  type="button"
                  onClick={onCancelRun}
                  disabled={busy}
                  className="-mr-1 rounded px-1 text-violet-200/80 hover:bg-violet-400/15 hover:text-violet-100 disabled:opacity-40"
                  aria-label="Cancel run"
                  title="Cancel queued run"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {!s.action && (
            <button
              type="button"
              onClick={onRunNow}
              disabled={busy}
              className="metis-icon-btn text-violet-400/80 hover:text-violet-400 disabled:opacity-40"
              aria-label="Run now"
              title="Run now"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            </button>
          )}
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
            title={readonly ? 'System job - delete disabled' : 'Delete'}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
