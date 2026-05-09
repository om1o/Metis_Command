'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3,
  CheckCircle,
  XCircle,
  CalendarClock,
  Bell,
  Brain,
  Loader2,
  RefreshCw,
  Sparkles,
  X,
  Zap,
} from 'lucide-react';
import { AnalyticsSummary, MetisClient } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

function fmtCents(cents: number): string {
  if (cents === 0) return '$0.00';
  return `$${(cents / 100).toFixed(2)}`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: typeof BarChart3;
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-4">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
        <Icon className={`h-3.5 w-3.5 ${accent || 'text-violet-400'}`} />
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-[var(--metis-foreground)]">
        {value}
      </div>
      {sub && <div className="text-[11.5px] text-[var(--metis-fg-muted)]">{sub}</div>}
    </div>
  );
}

function MissionBar({ by_status }: { by_status: Record<string, number> }) {
  const total = Object.values(by_status).reduce((a, b) => a + b, 0);
  if (total === 0) return null;
  const success = by_status['success'] ?? 0;
  const failed = (by_status['failed'] ?? 0) + (by_status['cancelled'] ?? 0);
  const running = (by_status['running'] ?? 0) + (by_status['queued'] ?? 0);
  const other = total - success - failed - running;

  const pct = (n: number) => `${Math.round((n / total) * 100)}%`;

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[11px] text-[var(--metis-fg-muted)]">
        <span>Mission outcomes</span>
        <span>{total} total</span>
      </div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-[var(--metis-elevated)]">
        {success > 0 && (
          <div className="bg-emerald-500" style={{ width: pct(success) }} title={`Success: ${success}`} />
        )}
        {running > 0 && (
          <div className="bg-violet-500" style={{ width: pct(running) }} title={`In progress: ${running}`} />
        )}
        {other > 0 && (
          <div className="bg-[var(--metis-fg-dim)]" style={{ width: pct(other) }} title={`Other: ${other}`} />
        )}
        {failed > 0 && (
          <div className="bg-rose-500" style={{ width: pct(failed) }} title={`Failed/cancelled: ${failed}`} />
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-3 text-[10.5px]">
        {success > 0 && (
          <span className="flex items-center gap-1 text-emerald-400">
            <CheckCircle className="h-3 w-3" /> {success} succeeded
          </span>
        )}
        {failed > 0 && (
          <span className="flex items-center gap-1 text-rose-400">
            <XCircle className="h-3 w-3" /> {failed} failed
          </span>
        )}
        {running > 0 && (
          <span className="flex items-center gap-1 text-violet-400">
            <Loader2 className="h-3 w-3 animate-spin" /> {running} active
          </span>
        )}
      </div>
    </div>
  );
}

function ModelBreakdown({ by_model }: { by_model: Record<string, { calls: number; tokens_in: number; tokens_out: number; cost: number }> }) {
  const entries = Object.entries(by_model).sort((a, b) => b[1].calls - a[1].calls).slice(0, 6);
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="mb-2 text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
        Token usage by model
      </div>
      <div className="divide-y divide-[var(--metis-border)] rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)]">
        {entries.map(([model, stats]) => (
          <div key={model} className="flex items-center gap-3 px-3 py-2 text-[12.5px]">
            <span className="min-w-0 flex-1 truncate font-mono text-[var(--metis-fg)]">{model}</span>
            <span className="shrink-0 tabular-nums text-[var(--metis-fg-muted)]">
              {fmtTokens(stats.tokens_in + stats.tokens_out)} tok
            </span>
            <span className="shrink-0 tabular-nums text-[var(--metis-fg-muted)]">
              {stats.calls} call{stats.calls !== 1 ? 's' : ''}
            </span>
            {stats.cost > 0 && (
              <span className="shrink-0 tabular-nums text-emerald-400">
                ${stats.cost.toFixed(4)}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AnalyticsPanel({ client, reduceMotion, onClose }: Props) {
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      setData(await client.getAnalytics());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const successRate = data && data.missions.total > 0
    ? Math.round((data.missions.success / data.missions.total) * 100)
    : null;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Analytics"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border max-h-[85vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur"
      >
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Analytics</div>
          {data && (
            <span className="ml-2 text-[10.5px] text-[var(--metis-fg-dim)]">
              Updated {new Date(data.generated_at).toLocaleTimeString()}
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
          <button type="button" onClick={onClose} className="metis-icon-btn" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[calc(85vh-56px)] overflow-y-auto px-4 py-4">
          {error && (
            <div className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200" role="alert">
              {error}
            </div>
          )}

          {!data ? (
            <div className="flex items-center gap-2 py-10 text-sm text-[var(--metis-fg-muted)]">
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading analytics…
            </div>
          ) : (
            <div className="space-y-5">
              {/* Top stat cards */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard
                  icon={Sparkles}
                  label="Sessions"
                  value={data.sessions.total}
                  sub={`${data.sessions.active_last_7d} this week`}
                />
                <StatCard
                  icon={BarChart3}
                  label="Missions"
                  value={data.missions.total}
                  sub={successRate !== null ? `${successRate}% success` : undefined}
                  accent="text-violet-400"
                />
                <StatCard
                  icon={CalendarClock}
                  label="Jobs"
                  value={data.schedules.active}
                  sub={`${data.schedules.total} total`}
                  accent="text-amber-400"
                />
                <StatCard
                  icon={Bell}
                  label="Inbox"
                  value={data.inbox.unread}
                  sub={`${data.inbox.total} total`}
                  accent="text-emerald-400"
                />
              </div>

              {/* Mission bar */}
              {data.missions.total > 0 && (
                <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-4">
                  <MissionBar by_status={data.missions.by_status} />
                </div>
              )}

              {/* Token usage */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <StatCard
                  icon={Zap}
                  label="API Calls"
                  value={data.tokens.calls.toLocaleString()}
                  accent="text-violet-400"
                />
                <StatCard
                  icon={Brain}
                  label="Tokens used"
                  value={fmtTokens(data.tokens.total)}
                  accent="text-violet-400"
                />
                <StatCard
                  icon={BarChart3}
                  label="Token cost"
                  value={data.tokens.cost_usd > 0 ? `$${data.tokens.cost_usd.toFixed(4)}` : '$0.00'}
                  sub={data.wallet.spent_cents > 0 ? `${fmtCents(data.wallet.spent_cents)} charged` : undefined}
                  accent="text-emerald-400"
                />
              </div>

              {/* Model breakdown */}
              {Object.keys(data.tokens.by_model).length > 0 && (
                <ModelBreakdown by_model={data.tokens.by_model} />
              )}

              {/* Wallet */}
              {data.wallet.cap_cents > 0 && (
                <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-4">
                  <div className="mb-2 flex items-center justify-between text-[11px] text-[var(--metis-fg-muted)]">
                    <span className="font-medium uppercase tracking-widest">Monthly budget</span>
                    <span className="tabular-nums">
                      {fmtCents(data.wallet.spent_cents)} / {fmtCents(data.wallet.cap_cents)}
                    </span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-[var(--metis-elevated)]">
                    <div
                      className="h-full rounded-full bg-violet-500 transition-all"
                      style={{ width: `${Math.min(100, Math.round((data.wallet.spent_cents / data.wallet.cap_cents) * 100))}%` }}
                    />
                  </div>
                  <div className="mt-1.5 text-[11px] text-[var(--metis-fg-dim)]">
                    {Math.round((data.wallet.spent_cents / data.wallet.cap_cents) * 100)}% of monthly cap used
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
