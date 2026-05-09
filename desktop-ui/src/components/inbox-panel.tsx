'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Bell,
  CalendarClock,
  Loader2,
  RefreshCw,
  Sparkles,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { MetisClient, InboxItem } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

function fmtAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const d = Date.now() - t;
  if (d < 60_000) return 'just now';
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`;
  if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}h ago`;
  return `${Math.floor(d / 86_400_000)}d ago`;
}

function sourceIcon(source: string) {
  if (source.startsWith('schedule:')) return <CalendarClock className="h-3.5 w-3.5 text-violet-300" />;
  if (source.startsWith('manager:relationship')) return <Users className="h-3.5 w-3.5 text-violet-300" />;
  return <Sparkles className="h-3.5 w-3.5 text-violet-300" />;
}

export default function InboxPanel({ client, reduceMotion, onClose }: Props) {
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [clearing, setClearing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      setItems(await client.listInbox());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const onMarkRead = async (id: string) => {
    setBusyId(id);
    try {
      await client.markInboxRead(id);
      setItems((prev) => (prev ? prev.map((it) => it.id === id ? { ...it, read: true } : it) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (id: string) => {
    setBusyId(id);
    try {
      await client.deleteInbox(id);
      setItems((prev) => (prev ? prev.filter((it) => it.id !== id) : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onClearAll = async () => {
    if (!items || items.length === 0) return;
    setClearing(true);
    try {
      await client.clearInbox();
      setItems([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setClearing(false);
    }
  };

  const unread = (items || []).filter((i) => !i.read).length;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Inbox"
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
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Inbox</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Bell className="h-3 w-3" /> {unread} new
          </span>
          {(items || []).length > 0 && (
            <button
              type="button"
              onClick={onClearAll}
              disabled={clearing}
              className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--metis-border)] px-2 py-1 text-[11px] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Clear all"
            >
              {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              Clear all
            </button>
          )}
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className={`metis-icon-btn ${(items || []).length > 0 ? '' : 'ml-auto'}`}
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
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading…
            </div>
          ) : items.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
              <div className="inline-flex items-center gap-2 text-[var(--metis-fg)]">
                <Bell className="h-4 w-4 text-violet-400" /> Inbox zero
              </div>
              <p className="mt-1">When a job fires or your agent saves a contact, it lands here.</p>
            </div>
          ) : (
            <ul className="grid gap-2">
              {items.map((it) => (
                <li
                  key={it.id}
                  className={`rounded-xl border px-3 py-2.5 ${
                    it.read
                      ? 'border-[var(--metis-border)] bg-[var(--metis-bg)]'
                      : 'border-violet-500/30 bg-violet-500/5'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className="mt-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)]">
                      {sourceIcon(it.source)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-[13.5px] font-medium text-[var(--metis-fg)]">{it.title}</p>
                        {!it.read && <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" aria-label="Unread" />}
                      </div>
                      {it.body && (
                        <p className="mt-1 whitespace-pre-wrap text-[12.5px] leading-5 text-[var(--metis-fg-muted)]">{it.body}</p>
                      )}
                      <div className="mt-1.5 flex items-center gap-3 text-[11px] text-[var(--metis-fg-dim)]">
                        <span>{fmtAgo(it.created_at)}</span>
                        <span className="font-mono">{it.source}</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {!it.read && (
                        <button
                          type="button"
                          onClick={() => onMarkRead(it.id)}
                          disabled={busyId === it.id}
                          className="metis-icon-btn disabled:opacity-40"
                          aria-label="Mark read"
                          title="Mark read"
                        >
                          <Sparkles className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => onDelete(it.id)}
                        disabled={busyId === it.id}
                        className="metis-icon-btn text-rose-400/80 hover:text-rose-400 disabled:opacity-40"
                        aria-label="Delete"
                        title="Delete"
                      >
                        {busyId === it.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </motion.div>
    </div>
  );
}
