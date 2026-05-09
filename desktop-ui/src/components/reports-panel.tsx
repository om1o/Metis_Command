'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  FileText,
  Loader2,
  RefreshCw,
  X,
  CalendarClock,
  Code,
  AlignLeft,
} from 'lucide-react';
import { MetisClient, Artifact } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
  onOpen: (id: string) => void;
}

function artifactIcon(type: string) {
  if (type === 'code') return <Code className="h-3.5 w-3.5 text-violet-300" />;
  if (type === 'text') return <AlignLeft className="h-3.5 w-3.5 text-violet-300" />;
  return <FileText className="h-3.5 w-3.5 text-violet-300" />;
}

function artifactTs(artifact: Artifact): number {
  const raw = artifact.created_at ?? artifact.metadata?.created_at ?? artifact.metadata?.ts ?? 0;
  if (typeof raw === 'number') return raw > 10_000_000_000 ? raw / 1000 : raw;
  const parsed = Date.parse(String(raw));
  return Number.isFinite(parsed) ? parsed / 1000 : 0;
}

function fmtTs(artifact: Artifact): string {
  const ts = artifactTs(artifact);
  if (!ts) return '';
  const d = new Date(ts * 1000);
  if (isNaN(d.getTime())) return '';
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

export default function ReportsPanel({ client, reduceMotion, onClose, onOpen }: Props) {
  const [items, setItems] = useState<Artifact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const all = await client.getArtifacts(100);
      setItems([...all].sort((a, b) => artifactTs(b) - artifactTs(a)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const reports = (items || []).filter(
    (a) => a.metadata?.kind === 'manager_run_report' || a.metadata?.kind === 'scheduled_job_report',
  );
  const other = (items || []).filter(
    (a) => a.metadata?.kind !== 'manager_run_report' && a.metadata?.kind !== 'scheduled_job_report',
  );

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Saved reports"
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
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Saved Reports</div>
          {items && (
            <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
              <FileText className="h-3 w-3" /> {items.length}
            </span>
          )}
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
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading...
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
              <div className="inline-flex items-center gap-2 text-[var(--metis-fg)]">
                <FileText className="h-4 w-4 text-violet-400" /> No saved reports yet
              </div>
              <p className="mt-1">Run a task or job; the manager saves a report here when it finishes.</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {reports.length > 0 && (
                <section>
                  <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
                    Run reports
                  </div>
                  <ul className="grid gap-1.5">
                    {reports.map((a) => (
                      <ArtifactRow key={a.id} artifact={a} onOpen={onOpen} onClose={onClose} />
                    ))}
                  </ul>
                </section>
              )}
              {other.length > 0 && (
                <section>
                  <div className="mb-2 text-[10px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
                    Other artifacts
                  </div>
                  <ul className="grid gap-1.5">
                    {other.map((a) => (
                      <ArtifactRow key={a.id} artifact={a} onOpen={onOpen} onClose={onClose} />
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function ArtifactRow({
  artifact,
  onOpen,
  onClose,
}: {
  artifact: Artifact;
  onOpen: (id: string) => void;
  onClose: () => void;
}) {
  const isScheduled = artifact.metadata?.kind === 'scheduled_job_report';
  const ts = fmtTs(artifact);

  return (
    <li>
      <button
        type="button"
        onClick={() => { onOpen(artifact.id); onClose(); }}
        className="flex w-full items-start gap-3 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5 text-left transition hover:border-violet-500/30 hover:bg-[var(--metis-hover-surface)]"
      >
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)]">
          {isScheduled ? <CalendarClock className="h-3.5 w-3.5 text-violet-300" /> : artifactIcon(artifact.type)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13.5px] font-medium text-[var(--metis-fg)]">
            {artifact.title || 'Untitled'}
          </p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-[var(--metis-fg-dim)]">
            {artifact.type && (
              <span className="rounded-full border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-1.5 py-0.5 text-[10px] uppercase tracking-widest">
                {artifact.type}
              </span>
            )}
            {ts && <span>{ts}</span>}
          </div>
        </div>
      </button>
    </li>
  );
}
