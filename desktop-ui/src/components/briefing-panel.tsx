'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  RefreshCw,
  X,
  Sunrise,
  Play,
  AlertCircle,
} from 'lucide-react';
import { MetisClient, BriefingSummary, BriefingDetail } from '@/lib/metis-client';
import { Mark } from '@/components/brand';
import MarkdownView from '@/components/markdown-view';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

function fmtDate(date: string): string {
  // YYYY-MM-DD → "Sat May 9, 2026"
  const d = new Date(date + 'T00:00:00');
  if (Number.isNaN(d.getTime())) return date;
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
}

export default function BriefingPanel({ client, reduceMotion, onClose }: Props) {
  const [items, setItems] = useState<BriefingSummary[] | null>(null);
  const [activeDate, setActiveDate] = useState<string | null>(null);
  const [detail, setDetail] = useState<BriefingDetail | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoadingList(true); setError(null);
    try {
      const list = await client.listBriefings();
      setItems(list);
      // Auto-select newest if nothing selected.
      if (list.length > 0 && !activeDate) setActiveDate(list[0].date);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingList(false);
    }
  }, [client, activeDate]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  // Load full detail whenever the active date changes. setState calls
  // are deferred via queueMicrotask to satisfy React 19's
  // set-state-in-effect rule.
  useEffect(() => {
    if (!activeDate) return;
    let cancelled = false;
    queueMicrotask(async () => {
      if (cancelled) return;
      setLoadingDetail(true);
      try {
        const d = await client.getBriefing(activeDate);
        if (!cancelled) setDetail(d);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    });
    return () => { cancelled = true; };
  }, [activeDate, client]);

  const runNow = async () => {
    setRunning(true); setError(null);
    try {
      const r = await client.runBriefingNow();
      if (!r.ok) throw new Error(r.status);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog" aria-modal="true" aria-label="Daily briefing"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur"
      >
        <div className="flex items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Daily briefing</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Sunrise className="h-3 w-3" /> {(items || []).length}
          </span>
          <button
            type="button"
            onClick={runNow}
            disabled={running}
            className="ml-auto inline-flex items-center gap-1 rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-1 text-[11px] text-violet-200 hover:bg-violet-500/15 disabled:opacity-50"
            title="Generate today's briefing now (takes a few seconds)"
          >
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            {running ? 'Running…' : 'Run now'}
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loadingList}
            className="metis-icon-btn"
            aria-label="Refresh"
            title="Refresh"
          >
            {loadingList ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
          <button type="button" onClick={onClose} className="metis-icon-btn" aria-label="Close" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid h-[calc(85vh-56px)] grid-cols-[220px_1fr]">
          {/* Date list */}
          <div className="overflow-y-auto border-r border-[var(--metis-border)] py-2">
            {!items ? (
              <div className="flex items-center gap-2 px-4 py-6 text-[12.5px] text-[var(--metis-fg-muted)]">
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading…
              </div>
            ) : items.length === 0 ? (
              <div className="mx-3 mt-2 rounded-xl border border-dashed border-[var(--metis-border)] p-3 text-[11.5px] text-[var(--metis-fg-dim)]">
                No briefings yet. Hit <strong>Run now</strong> above, or wait for the morning schedule to fire.
              </div>
            ) : (
              <ul className="grid gap-0.5">
                {items.map((b) => {
                  const sel = activeDate === b.date;
                  return (
                    <li key={b.date}>
                      <button
                        type="button"
                        onClick={() => setActiveDate(b.date)}
                        className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-[12.5px] transition ${
                          sel
                            ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-fg)]'
                            : 'text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
                        }`}
                      >
                        <span className="font-medium">{fmtDate(b.date)}</span>
                        <span className="line-clamp-1 text-[10.5px] text-[var(--metis-fg-dim)]">
                          {(b.preview || '').replace(/^#.*\n/, '').replace(/\n+/g, ' · ').slice(0, 80)}
                        </span>
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
                <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading briefing…
              </div>
            ) : !detail ? (
              <div className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
                <div className="inline-flex items-center gap-2 text-[var(--metis-fg)]">
                  <Sunrise className="h-4 w-4 text-violet-400" /> No briefing selected
                </div>
                <p className="mt-1">
                  Pick a date on the left, or run today&apos;s briefing now. The morning briefing schedule writes one
                  every day at <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">07:00</code> by default
                  (configurable via <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">DAILY_BRIEFING_TIME</code> in <code>.env</code>).
                </p>
                <p className="mt-1">
                  Set <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">DAILY_PLAN_EMAIL</code> in <code>.env</code> to also have it emailed.
                </p>
              </div>
            ) : (
              <article className="max-w-none text-[14px] leading-7">
                <MarkdownView source={detail.content} />
              </article>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
