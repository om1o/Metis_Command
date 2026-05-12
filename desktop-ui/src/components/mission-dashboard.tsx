'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  X,
  Plus,
  Play,
  Square,
  CheckCircle2,
  XCircle,
  CircleDot,
  AlertCircle,
  LayoutGrid,
} from 'lucide-react';
import { MetisClient } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

type Status = 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | 'error';

interface Step {
  index: number;
  description: string;
  tool?: string | null;
  ok?: boolean;
  duration_ms?: number;
  status: 'running' | 'done' | 'failed';
}

interface Shot {
  step?: number;
  tool?: string;
  image?: string;
  ts: number;
}

interface MissionPane {
  id: string;
  goal: string;
  status: Status;
  steps: Step[];
  shots: Shot[];
  answer: string;
  startedAt: number;
  endedAt: number | null;
  abort: AbortController;
  missionId?: string; // server-assigned
  errorMsg?: string;
}

const STATUS_META: Record<Status, { icon: React.ReactNode; pill: string }> = {
  queued:    { icon: <CircleDot    className="h-3.5 w-3.5 text-slate-400" />,                  pill: 'border-slate-500/30 bg-slate-500/10 text-slate-200' },
  running:   { icon: <CircleDot    className="h-3.5 w-3.5 animate-pulse text-violet-300" />,    pill: 'border-violet-500/30 bg-violet-500/10 text-violet-200' },
  success:   { icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />,                pill: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' },
  failed:    { icon: <XCircle      className="h-3.5 w-3.5 text-rose-300" />,                   pill: 'border-rose-500/30 bg-rose-500/10 text-rose-200' },
  cancelled: { icon: <Square       className="h-3.5 w-3.5 text-slate-300" />,                  pill: 'border-slate-500/30 bg-slate-500/10 text-slate-200' },
  error:     { icon: <AlertCircle  className="h-3.5 w-3.5 text-rose-300" />,                   pill: 'border-rose-500/30 bg-rose-500/10 text-rose-200' },
};

function fmtElapsed(start: number, end: number | null): string {
  const dur = ((end || Date.now()) - start) / 1000;
  if (dur < 60) return `${dur.toFixed(1)}s`;
  return `${Math.floor(dur / 60)}m ${Math.floor(dur % 60)}s`;
}

function newSessionId(): string {
  // Per-mission session id so the bridge's permission gate scopes correctly.
  return 'dash-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

export default function MissionDashboard({ client, reduceMotion, onClose }: Props) {
  const [missions, setMissions] = useState<MissionPane[]>([]);
  const [draftGoal, setDraftGoal] = useState('');
  const [permission] = useState<'read' | 'balanced' | 'full'>('balanced');
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const missionsRef = useRef<MissionPane[]>([]);
  // Sync ref in an effect (React 19 forbids ref writes during render).
  useEffect(() => { missionsRef.current = missions; }, [missions]);

  // Heartbeat for the elapsed-time labels on running cards.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // Cleanup all in-flight streams on unmount (panel close).
  useEffect(() => {
    return () => {
      for (const m of missionsRef.current) {
        try { m.abort.abort(); } catch { /* noop */ }
      }
    };
  }, []);

  const updateMission = useCallback((id: string, patch: Partial<MissionPane> | ((m: MissionPane) => Partial<MissionPane>)) => {
    setMissions((prev) => prev.map((m) => {
      if (m.id !== id) return m;
      const p = typeof patch === 'function' ? patch(m) : patch;
      return { ...m, ...p };
    }));
  }, []);

  const launch = useCallback((goalIn: string) => {
    const goal = goalIn.trim();
    if (!goal) return;
    const id = newSessionId();
    const ac = new AbortController();
    const pane: MissionPane = {
      id, goal,
      status: 'running',
      steps: [], shots: [],
      answer: '',
      startedAt: Date.now(),
      endedAt: null,
      abort: ac,
    };
    setMissions((prev) => [...prev, pane]);

    (async () => {
      try {
        const stream = client.chat('autonomous', goal, id, {
          mode: 'task',
          permission,
        });
        for await (const ev of stream) {
          if (ac.signal.aborted) break;
          const t = ev.type as string;
          if (t === 'mission_start') {
            updateMission(id, { missionId: typeof ev.mission_id === 'string' ? ev.mission_id : undefined });
          } else if (t === 'step_start') {
            const newStep: Step = {
              index: Number(ev.step || 0),
              description: String(ev.description || ''),
              status: 'running',
            };
            updateMission(id, (m) => ({
              steps: [...m.steps.filter((s) => s.index !== newStep.index), newStep],
            }));
          } else if (t === 'step_end') {
            updateMission(id, (m) => ({
              steps: m.steps.map((s) => s.index === Number(ev.step || 0)
                ? { ...s, ok: Boolean(ev.ok), tool: typeof ev.tool === 'string' ? ev.tool : s.tool, duration_ms: Number(ev.duration_ms || 0), status: ev.ok ? 'done' : 'failed' }
                : s),
            }));
          } else if (t === 'live_artifact') {
            const shot: Shot = {
              step: typeof ev.step === 'number' ? ev.step : undefined,
              tool: typeof ev.tool === 'string' ? ev.tool : undefined,
              image: typeof ev.image_b64 === 'string' ? ev.image_b64 : undefined,
              ts: Date.now(),
            };
            updateMission(id, (m) => ({ shots: [...m.shots, shot].slice(-8) }));
          } else if (t === 'finish') {
            updateMission(id, { answer: String(ev.answer || ''), status: 'success' });
          } else if (t === 'mission_end') {
            updateMission(id, (m) => ({
              status: (ev.status as Status) || m.status,
              endedAt: Date.now(),
              answer: m.answer || String(ev.answer || ''),
            }));
          } else if (t === 'error') {
            updateMission(id, {
              status: 'error',
              errorMsg: typeof ev.message === 'string' ? ev.message : 'unknown error',
              endedAt: Date.now(),
            });
          }
        }
      } catch (err) {
        if (!ac.signal.aborted) {
          updateMission(id, {
            status: 'error',
            errorMsg: err instanceof Error ? err.message : String(err),
            endedAt: Date.now(),
          });
        }
      }
    })();
  }, [client, permission, updateMission]);

  const onLaunchClick = () => { launch(draftGoal); setDraftGoal(''); };

  const onCancel = useCallback((id: string) => {
    const m = missionsRef.current.find((x) => x.id === id);
    if (!m) return;
    try { m.abort.abort(); } catch { /* noop */ }
    // Use setMissions updater so Date.now() runs during commit, not render.
    setMissions((prev) => prev.map((x) =>
      x.id === id ? { ...x, status: 'cancelled' as const, endedAt: Date.now() } : x,
    ));
  }, []);

  const onRemove = (id: string) => {
    const m = missions.find((x) => x.id === id);
    if (m && (m.status === 'running' || m.status === 'queued')) {
      try { m.abort.abort(); } catch { /* noop */ }
    }
    setMissions((prev) => prev.filter((x) => x.id !== id));
  };

  const inflight = missions.filter((m) => m.status === 'running' || m.status === 'queued').length;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog" aria-modal="true" aria-label="Mission dashboard"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border max-h-[92vh] w-full max-w-6xl overflow-hidden rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur"
      >
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Mission dashboard</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <LayoutGrid className="h-3 w-3" /> {missions.length}{inflight ? ` · ${inflight} live` : ''}
          </span>
          <button type="button" onClick={onClose} className="ml-auto metis-icon-btn" aria-label="Close" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Launch row */}
        <div className="flex items-center gap-2 border-b border-[var(--metis-border)] px-4 py-2.5">
          <Plus className="h-4 w-4 text-violet-400" />
          <input
            value={draftGoal}
            onChange={(e) => setDraftGoal(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onLaunchClick(); } }}
            placeholder="New mission goal — e.g. read package.json and report the version"
            className="flex-1 rounded-md border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2.5 py-1.5 text-[13px] text-[var(--metis-fg)] placeholder:text-[var(--metis-fg-dim)] focus:outline-none focus:ring-2 focus:ring-violet-500/40"
          />
          <button
            type="button"
            onClick={onLaunchClick}
            disabled={!draftGoal.trim()}
            className="inline-flex items-center gap-1 rounded-md bg-violet-600 px-3 py-1.5 text-[12.5px] font-medium text-white hover:brightness-110 disabled:opacity-40"
          >
            <Play className="h-3.5 w-3.5" /> Launch
          </button>
        </div>

        {/* Grid */}
        <div className="overflow-y-auto p-4" style={{ maxHeight: 'calc(92vh - 120px)' }}>
          {missions.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-6 py-10 text-center text-[13px] text-[var(--metis-fg-muted)]">
              <LayoutGrid className="mx-auto h-6 w-6 text-violet-400" />
              <div className="mt-2 text-[14px] font-medium text-[var(--metis-fg)]">No missions running</div>
              <div className="mt-1">Type a goal above and hit <kbd className="rounded bg-[var(--metis-code-bg)] px-1 text-[11px]">↵</kbd> to fire one. Launch as many as you want — each runs on its own SSE stream.</div>
            </div>
          ) : (
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(320px,1fr))]">
              {missions.map((m) => {
                const meta = STATUS_META[m.status] || STATUS_META.queued;
                return (
                  <div key={m.id} className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] overflow-hidden flex flex-col">
                    {/* Card header */}
                    <div className="flex items-start gap-2 border-b border-[var(--metis-border)] px-3 py-2">
                      <span className={`mt-0.5 inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] ${meta.pill}`}>
                        {meta.icon} {m.status}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="line-clamp-2 text-[12.5px] font-medium text-[var(--metis-fg)]">{m.goal}</div>
                        <div className="mt-0.5 text-[10px] text-[var(--metis-fg-dim)]">
                          {fmtElapsed(m.startedAt, m.endedAt)}
                          {m.steps.length ? ` · ${m.steps.length} steps` : ''}
                          {m.shots.length ? ` · ${m.shots.length} captures` : ''}
                        </div>
                      </div>
                      {(m.status === 'running' || m.status === 'queued') ? (
                        <button
                          type="button"
                          onClick={() => onCancel(m.id)}
                          className="rounded-md border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.5 text-[10.5px] text-rose-200 hover:bg-rose-500/20"
                          title="Cancel"
                        >
                          <Square className="h-3 w-3" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onRemove(m.id)}
                          className="rounded-md border border-[var(--metis-border)] px-1.5 py-0.5 text-[10.5px] text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]"
                          title="Remove from dashboard"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      )}
                    </div>

                    {/* Body */}
                    <div className="flex-1 grid gap-2 p-3">
                      {/* Step trail */}
                      {m.steps.length > 0 && (
                        <div className="grid gap-0.5 text-[11px]">
                          {m.steps.sort((a, b) => a.index - b.index).slice(-5).map((s) => (
                            <div key={s.index} className="flex items-baseline gap-1.5">
                              <span className={`inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border text-[8px] font-bold ${
                                s.status === 'running' ? 'border-violet-500/40 bg-violet-500/10 text-violet-300 animate-pulse'
                                : s.status === 'done' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                                : 'border-rose-500/40 bg-rose-500/10 text-rose-200'
                              }`}>{s.index}</span>
                              <span className="line-clamp-1 flex-1 text-[var(--metis-fg-muted)]">{s.description}</span>
                              {s.tool && <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[9.5px] text-[var(--metis-code-fg)]">{s.tool}</code>}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Live shots */}
                      {m.shots.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {m.shots.slice(-4).map((shot, i) => (
                            shot.image ? (
                              <button
                                key={i}
                                type="button"
                                onClick={() => shot.image && setLightbox(shot.image)}
                                className="overflow-hidden rounded-md border border-[var(--metis-border)] hover:border-violet-500/60"
                                title={`Step ${shot.step ?? '?'} · ${shot.tool ?? 'capture'}`}
                              >
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img src={shot.image} alt="capture" className="h-12 w-16 object-cover" />
                              </button>
                            ) : (
                              <div key={i} className="flex h-12 w-16 items-center justify-center rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)] text-[9px] text-[var(--metis-fg-dim)]">
                                {shot.tool || 'shot'}
                              </div>
                            )
                          ))}
                        </div>
                      )}

                      {/* Final answer / error */}
                      {m.answer && (
                        <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2 py-1.5 text-[11.5px] leading-snug text-[var(--metis-fg)]">
                          <div className="text-[9px] uppercase tracking-widest text-emerald-300/80 mb-0.5">Answer</div>
                          <div className="line-clamp-3 whitespace-pre-wrap">{m.answer}</div>
                        </div>
                      )}
                      {m.errorMsg && (
                        <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200">
                          <AlertCircle className="mr-1 inline h-3 w-3" /> {m.errorMsg}
                        </div>
                      )}
                      {m.status === 'running' && m.steps.length === 0 && (
                        <div className="flex items-center gap-1.5 text-[11px] text-[var(--metis-fg-muted)]">
                          <Loader2 className="h-3 w-3 animate-spin text-violet-400" /> planning…
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Lightbox */}
        {lightbox && (
          <div
            className="fixed inset-0 z-[200] flex items-center justify-center p-4"
            onClick={() => setLightbox(null)}
            style={{ background: 'rgba(0,0,0,0.85)' }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={lightbox} alt="capture full size" className="max-h-[92vh] max-w-[92vw] rounded-lg shadow-2xl" />
          </div>
        )}
      </motion.div>
      <span className="sr-only">{now}</span>
    </div>
  );
}
