'use client';

import { useState, FormEvent } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  X,
  Search,
  Brain,
  Pin,
  Check,
  AlertCircle,
} from 'lucide-react';
import { MetisClient, MemoryHit } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

export default function MemoryPanel({ client, reduceMotion, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [pinText, setPinText] = useState('');
  const [hits, setHits] = useState<MemoryHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [pinning, setPinning] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true); setError(null);
    try {
      const r = await client.recall(query.trim(), 12);
      setHits(Array.isArray(r) ? r : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setHits([]);
    } finally {
      setSearching(false);
    }
  };

  const pin = async (e: FormEvent) => {
    e.preventDefault();
    const t = pinText.trim();
    if (!t) return;
    setPinning(true); setError(null);
    try {
      await client.remember(t, 'semantic');
      setPinText('');
      setPinned(true);
      setTimeout(() => setPinned(false), 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPinning(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog" aria-modal="true" aria-label="Memory"
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
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Memory</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Brain className="h-3 w-3" /> what Metis knows
          </span>
          <button type="button" onClick={onClose} className="ml-auto metis-icon-btn" aria-label="Close" title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-4 px-4 py-3">
          {/* Pin a fact */}
          <form onSubmit={pin} className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
            <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">
              <Pin className="h-3 w-3" /> Pin a fact Metis should always remember
            </div>
            <div className="flex gap-2">
              <input
                value={pinText}
                onChange={(e) => setPinText(e.target.value)}
                placeholder="e.g. I live in Austin, my partner's name is Sam, I'm allergic to peanuts."
                className="min-w-0 flex-1 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
              />
              <button
                type="submit"
                disabled={pinning || !pinText.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-50"
                style={{ background: 'var(--metis-accent)' }}
              >
                {pinning ? <Loader2 className="h-4 w-4 animate-spin" /> : pinned ? <Check className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
                {pinning ? 'Pinning…' : pinned ? 'Pinned' : 'Pin'}
              </button>
            </div>
          </form>

          {/* Search */}
          <form onSubmit={search} className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-3">
            <div className="mb-2 flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">
              <Search className="h-3 w-3" /> Recall what Metis already knows
            </div>
            <div className="flex gap-2">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="e.g. when I'm traveling, what I bought last week, who's the lawyer in Austin"
                className="min-w-0 flex-1 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
              />
              <button
                type="submit"
                disabled={searching || !query.trim()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-3 py-2 text-sm text-[var(--metis-fg)] transition hover:brightness-110 disabled:opacity-50"
              >
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                Search
              </button>
            </div>
          </form>

          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {error}
            </div>
          )}

          <div className="max-h-[40vh] overflow-y-auto">
            {hits === null ? (
              <p className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-3 text-[12.5px] text-[var(--metis-fg-dim)]">
                Type a query above to recall facts. Pinned facts and conversation history are searched by semantic similarity.
              </p>
            ) : hits.length === 0 ? (
              <p className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-3 text-[12.5px] text-[var(--metis-fg-dim)]">
                Nothing relevant found. Try different words or pin a fact above.
              </p>
            ) : (
              <ul className="grid gap-1.5">
                {hits.map((h, i) => (
                  <li key={h.id || `m-${i}`} className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-2.5">
                    <div className="flex items-center gap-2 text-[10px] text-[var(--metis-fg-dim)]">
                      {h.kind && (
                        <span className="rounded-full border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-1.5 py-0.5 uppercase tracking-widest">
                          {String(h.kind)}
                        </span>
                      )}
                      {typeof h.score === 'number' && (
                        <span>score {h.score.toFixed(3)}</span>
                      )}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-[13px] leading-5 text-[var(--metis-fg)]">
                      {h.text}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
