'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  Mail,
  Phone,
  PhoneCall,
  MessageSquare,
  Building2,
  StickyNote,
  Tag,
  Trash2,
  X,
  RefreshCw,
  Users,
  ChevronDown,
  ChevronUp,
  Send,
  Check,
  AlertCircle,
} from 'lucide-react';
import { MetisClient, Relationship } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  onClose: () => void;
}

function fmtCreated(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export default function RelationshipsPanel({ client, reduceMotion, onClose }: Props) {
  const [items, setItems] = useState<Relationship[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const list = await client.listRelationships();
      setItems(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }, [client]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const onDelete = async (id: string) => {
    setBusyId(id);
    try {
      await client.deleteRelationship(id);
      if (openId === id) setOpenId(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !items) return items;
    return items.filter((r) => {
      const hay = `${r.name} ${r.role ?? ''} ${r.company ?? ''} ${r.email ?? ''} ${(r.tags ?? []).join(' ')}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, query]);

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Relationships"
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
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">Relationships</div>
          <span className="ml-2 inline-flex items-center gap-1 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] uppercase tracking-widest text-violet-300">
            <Users className="h-3 w-3" /> {(items || []).length}
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

        <div className="border-b border-[var(--metis-border)] px-4 py-2.5">
          <input
            type="search"
            placeholder="Filter by name, role, company, email, or tag…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-sm outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
          />
        </div>

        <div className="max-h-[calc(80vh-104px)] overflow-y-auto px-4 py-3">
          {error && (
            <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12.5px] text-rose-200" role="alert">
              {error}
            </div>
          )}

          {!items ? (
            <div className="flex items-center gap-2 py-6 text-sm text-[var(--metis-fg-muted)]">
              <Loader2 className="h-4 w-4 animate-spin text-violet-400" /> Loading…
            </div>
          ) : (filtered || []).length === 0 ? (
            <EmptyState hasQuery={!!query.trim()} />
          ) : (
            <div className="grid gap-2">
              {(filtered || []).map((r) => (
                <RelationshipRow
                  key={r.id}
                  r={r}
                  open={openId === r.id}
                  busy={busyId === r.id}
                  client={client}
                  onToggle={() => setOpenId(openId === r.id ? null : r.id)}
                  onDelete={() => onDelete(r.id)}
                />
              ))}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function EmptyState({ hasQuery }: { hasQuery: boolean }) {
  if (hasQuery) {
    return (
      <div className="rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
        No matches for that filter.
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-[var(--metis-border)] bg-[var(--metis-bg)] px-4 py-6 text-[13px] text-[var(--metis-fg-muted)]">
      <div className="inline-flex items-center gap-2 text-[var(--metis-fg)]">
        <Users className="h-4 w-4 text-violet-400" /> No relationships yet
      </div>
      <p>
        Ask your agent something like <em>&ldquo;find me a contracts lawyer in Austin&rdquo;</em> in Task mode. When it finds someone, it will save a contact card here automatically.
      </p>
    </div>
  );
}

function RelationshipRow({
  r,
  open,
  busy,
  client,
  onToggle,
  onDelete,
}: {
  r: Relationship;
  open: boolean;
  busy: boolean;
  client: MetisClient;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const subtitle = [r.role, r.company].filter(Boolean).join(' · ');
  const [smsOpen, setSmsOpen] = useState(false);
  const [smsBody, setSmsBody] = useState('');
  const [smsBusy, setSmsBusy] = useState(false);
  const [smsResult, setSmsResult] = useState<'sent' | string | null>(null);
  const [callBusy, setCallBusy] = useState(false);
  const [callResult, setCallResult] = useState<'placed' | string | null>(null);

  const sendSms = async () => {
    const msg = smsBody.trim();
    if (!msg) return;
    setSmsBusy(true); setSmsResult(null);
    try {
      await client.sendRelationshipSms(r.id, msg);
      setSmsResult('sent');
      setSmsBody('');
      setTimeout(() => { setSmsResult(null); setSmsOpen(false); }, 1500);
    } catch (err) {
      setSmsResult(err instanceof Error ? err.message : String(err));
    } finally {
      setSmsBusy(false);
    }
  };

  const placeCall = async () => {
    const ok = window.confirm(
      `Place a Twilio call to ${r.name}${r.phone ? ` (${r.phone})` : ''}? ` +
      `They will hear your TWIML script. This costs Twilio credits.`,
    );
    if (!ok) return;
    setCallBusy(true); setCallResult(null);
    try {
      await client.placeRelationshipCall(r.id);
      setCallResult('placed');
      setTimeout(() => setCallResult(null), 2000);
    } catch (err) {
      setCallResult(err instanceof Error ? err.message : String(err));
    } finally {
      setCallBusy(false);
    }
  };
  return (
    <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition hover:bg-[var(--metis-hover-surface)]"
      >
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-[var(--metis-border)] bg-[var(--metis-elevated)] text-[11px] font-medium text-violet-300">
          {(r.name || '?').slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-medium text-[var(--metis-fg)]">{r.name || 'Unnamed'}</div>
          {subtitle && (
            <div className="mt-0.5 truncate text-[11.5px] text-[var(--metis-fg-dim)]">{subtitle}</div>
          )}
          {(r.tags || []).length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {(r.tags || []).slice(0, 4).map((t, i) => (
                <span
                  key={`${t}-${i}`}
                  className="inline-flex items-center gap-1 rounded-full border border-[var(--metis-border)] bg-[var(--metis-hover-surface)] px-1.5 py-0.5 text-[10px] text-[var(--metis-fg-muted)]"
                >
                  <Tag className="h-2.5 w-2.5" />
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <span className="metis-icon-btn pointer-events-none shrink-0">
          {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </span>
      </button>
      {open && (
        <div className="border-t border-[var(--metis-border)] px-3 py-3">
          <dl className="grid gap-2 text-[12.5px]">
            {r.email && (
              <Field icon={<Mail className="h-3.5 w-3.5" />} label="Email">
                <a href={`mailto:${r.email}`} className="text-violet-300 hover:underline">{r.email}</a>
              </Field>
            )}
            {r.phone && (
              <Field icon={<Phone className="h-3.5 w-3.5" />} label="Phone">
                <a href={`tel:${r.phone}`} className="text-violet-300 hover:underline">{r.phone}</a>
              </Field>
            )}
            {r.company && (
              <Field icon={<Building2 className="h-3.5 w-3.5" />} label="Company">
                <span className="text-[var(--metis-fg)]">{r.company}</span>
              </Field>
            )}
            {r.notes && (
              <Field icon={<StickyNote className="h-3.5 w-3.5" />} label="Notes">
                <span className="whitespace-pre-wrap text-[var(--metis-fg)]">{r.notes}</span>
              </Field>
            )}
          </dl>
          {/* Twilio outreach actions — only meaningful when there's a phone number */}
          {r.phone && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => { setSmsOpen((v) => !v); setSmsResult(null); }}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1 text-[11px] text-[var(--metis-fg)] hover:bg-[var(--metis-hover-surface)]"
              >
                <MessageSquare className="h-3 w-3 text-violet-400" />
                {smsOpen ? 'Cancel SMS' : 'Send SMS'}
              </button>
              <button
                type="button"
                onClick={placeCall}
                disabled={callBusy}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-1 text-[11px] text-[var(--metis-fg)] hover:bg-[var(--metis-hover-surface)] disabled:opacity-40"
              >
                {callBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <PhoneCall className="h-3 w-3 text-violet-400" />}
                Call
              </button>
              {callResult === 'placed' && (
                <span className="inline-flex items-center gap-1 text-[10.5px] text-emerald-300">
                  <Check className="h-3 w-3" /> dialed
                </span>
              )}
              {callResult && callResult !== 'placed' && (
                <span className="inline-flex items-center gap-1 text-[10.5px] text-rose-300">
                  <AlertCircle className="h-3 w-3" /> {callResult}
                </span>
              )}
            </div>
          )}

          {/* Inline SMS composer */}
          {smsOpen && r.phone && (
            <div className="mt-2 grid gap-2 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2.5">
              <textarea
                value={smsBody}
                onChange={(e) => setSmsBody(e.target.value)}
                placeholder={`Message ${r.name}…`}
                rows={3}
                maxLength={1000}
                className="w-full resize-none rounded-md border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-2 py-1.5 text-[12.5px] outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-1 focus:ring-[var(--metis-focus)]"
              />
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-[var(--metis-fg-dim)]">{smsBody.length}/1000 · sent via Twilio</span>
                {smsResult === 'sent' && (
                  <span className="inline-flex items-center gap-1 text-[10.5px] text-emerald-300">
                    <Check className="h-3 w-3" /> delivered
                  </span>
                )}
                {smsResult && smsResult !== 'sent' && (
                  <span className="inline-flex items-center gap-1 text-[10.5px] text-rose-300">
                    <AlertCircle className="h-3 w-3" /> {smsResult}
                  </span>
                )}
                <button
                  type="button"
                  onClick={sendSms}
                  disabled={smsBusy || !smsBody.trim()}
                  className="ml-auto inline-flex items-center gap-1 rounded-md bg-violet-500 px-2 py-1 text-[11px] font-medium text-white hover:brightness-110 disabled:opacity-40"
                >
                  {smsBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                  Send
                </button>
              </div>
            </div>
          )}

          <div className="mt-3 flex items-center gap-2">
            {r.created_at && (
              <span className="text-[10.5px] text-[var(--metis-fg-dim)]">Added {fmtCreated(r.created_at)}</span>
            )}
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--metis-border)] px-2 py-1 text-[11px] text-rose-300 hover:bg-rose-500/10 disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              Delete
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[16px_84px_1fr] items-start gap-2">
      <span className="mt-0.5 text-[var(--metis-fg-dim)]">{icon}</span>
      <dt className="text-[10.5px] uppercase tracking-widest text-[var(--metis-fg-dim)]">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}
