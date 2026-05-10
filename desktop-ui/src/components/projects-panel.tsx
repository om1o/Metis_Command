'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Loader2,
  RefreshCw,
  X,
  FolderOpen,
  Plus,
  Pencil,
  Trash2,
  Check,
  CheckCircle2,
  Circle,
  ChevronDown,
  ChevronUp,
  AlertCircle,
} from 'lucide-react';
import { MetisClient, Project } from '@/lib/metis-client';
import { Mark } from '@/components/brand';

interface Props {
  client: MetisClient;
  reduceMotion: boolean;
  activeProjectSlug: string | null;
  onActiveChange: (slug: string | null, name: string | null) => void;
  onClose: () => void;
}

function fmtDate(ts: number): string {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

// ── Create / edit form ────────────────────────────────────────────────────

function ProjectForm({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial?: Partial<Project>;
  onSave: (name: string, description: string, instructions: string) => Promise<void>;
  onCancel: () => void;
  saving: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [instructions, setInstructions] = useState(initial?.instructions ?? '');
  const [showInstructions, setShowInstructions] = useState(!!(initial?.instructions));
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => { nameRef.current?.focus(); }, []);

  const submit = async () => {
    if (!name.trim()) return;
    await onSave(name.trim(), description.trim(), instructions.trim());
  };

  return (
    <div className="grid gap-2.5">
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
          Project name *
        </label>
        <input
          ref={nameRef}
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
          placeholder="e.g. Metis Codebase"
          className="w-full rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-[13px] text-[var(--metis-foreground)] outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-1 focus:ring-[var(--metis-focus)]"
        />
      </div>
      <div>
        <label className="mb-1 block text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
          Description
        </label>
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What is this project about?"
          className="w-full rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-[13px] text-[var(--metis-foreground)] outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-1 focus:ring-[var(--metis-focus)]"
        />
      </div>
      <button
        type="button"
        onClick={() => setShowInstructions((v) => !v)}
        className="flex items-center gap-1.5 text-[11px] text-[var(--metis-fg-muted)] hover:text-[var(--metis-fg)]"
      >
        {showInstructions ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        Custom system instructions
      </button>
      {showInstructions && (
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={5}
          placeholder="You are working on the Metis codebase. Always use Python 3.12+. Prefer async patterns…"
          className="w-full resize-y rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2 text-[13px] text-[var(--metis-foreground)] outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-1 focus:ring-[var(--metis-focus)]"
        />
      )}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={submit}
          disabled={saving || !name.trim()}
          className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-[13px] font-medium text-white transition hover:bg-violet-700 disabled:opacity-50"
        >
          {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {initial?.slug ? 'Save changes' : 'Create project'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg border border-[var(--metis-border)] px-3 py-2 text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)]"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────

export default function ProjectsPanel({ client, reduceMotion, activeProjectSlug, onActiveChange, onClose }: Props) {
  const [items, setItems] = useState<Project[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [deletingSlug, setDeletingSlug] = useState<string | null>(null);
  const [expandedSlug, setExpandedSlug] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const list = await client.listProjects();
      setItems(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => { queueMicrotask(refresh); }, [refresh]);

  const activate = async (slug: string) => {
    const project = items?.find((p) => p.slug === slug);
    try {
      if (slug === activeProjectSlug) {
        await client.clearActiveProject();
        onActiveChange(null, null);
      } else {
        await client.setActiveProject(slug);
        onActiveChange(slug, project?.name ?? slug);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCreate = async (name: string, description: string, instructions: string) => {
    setSaving(true);
    try {
      await client.createProject(name, description, instructions);
      setCreating(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (slug: string, name: string, description: string, instructions: string) => {
    setSaving(true);
    try {
      await client.updateProject(slug, { name, description, instructions });
      setEditingSlug(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (slug: string) => {
    setDeletingSlug(slug);
    try {
      await client.deleteProject(slug);
      if (activeProjectSlug === slug) onActiveChange(null, null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingSlug(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[120] flex items-start justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Projects"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.35)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, x: 40 }}
        animate={{ opacity: 1, x: 0 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 40 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
        className="flex h-full w-full max-w-md flex-col border-l border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center gap-2.5 border-b border-[var(--metis-border)] px-4 py-3.5">
          <Mark size={18} />
          <FolderOpen className="h-4 w-4 text-violet-400" />
          <span className="text-sm font-semibold text-[var(--metis-foreground)]">Projects</span>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="metis-icon-btn"
              aria-label="Refresh"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              type="button"
              onClick={() => { setCreating(true); setEditingSlug(null); }}
              className="metis-icon-btn text-violet-400"
              aria-label="New project"
              title="New project"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button type="button" onClick={onClose} className="metis-icon-btn" aria-label="Close">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Active project banner */}
        {activeProjectSlug && (
          <div className="shrink-0 border-b border-violet-500/20 bg-violet-500/10 px-4 py-2.5">
            <div className="flex items-center gap-2 text-[12px] text-violet-200">
              <CheckCircle2 className="h-3.5 w-3.5 text-violet-400" />
              <span>
                Active workspace:{' '}
                <span className="font-semibold">
                  {items?.find((p) => p.slug === activeProjectSlug)?.name ?? activeProjectSlug}
                </span>
              </span>
              <button
                type="button"
                onClick={() => activate(activeProjectSlug)}
                className="ml-auto text-[10px] text-violet-300 hover:text-violet-100"
              >
                Clear
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="mx-4 mt-3 flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-[12px] text-rose-300">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-auto shrink-0 hover:text-rose-100">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Create form */}
        <AnimatePresence>
          {creating && (
            <motion.div
              initial={reduceMotion ? false : { opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="shrink-0 overflow-hidden border-b border-[var(--metis-border)]"
            >
              <div className="p-4">
                <p className="mb-3 text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
                  New project
                </p>
                <ProjectForm
                  onSave={handleCreate}
                  onCancel={() => setCreating(false)}
                  saving={saving}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* List */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading && !items && (
            <div className="flex items-center justify-center py-12 text-[var(--metis-fg-dim)]">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          )}
          {!loading && items?.length === 0 && !creating && (
            <div className="mx-4 mt-6 rounded-xl border border-dashed border-[var(--metis-border)] p-5 text-center">
              <FolderOpen className="mx-auto mb-2 h-8 w-8 text-[var(--metis-fg-dim)]" />
              <p className="text-[13px] text-[var(--metis-fg-muted)]">No projects yet</p>
              <p className="mt-1 text-[11px] text-[var(--metis-fg-dim)]">
                Create a project to give the agent focused context for a specific codebase, client, or goal.
              </p>
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-violet-700"
              >
                <Plus className="h-3.5 w-3.5" /> Create first project
              </button>
            </div>
          )}
          {items && items.length > 0 && (
            <ul className="divide-y divide-[var(--metis-border)]">
              {items.map((p) => (
                <li key={p.slug}>
                  {/* Edit mode */}
                  <AnimatePresence>
                    {editingSlug === p.slug && (
                      <motion.div
                        initial={reduceMotion ? false : { opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="overflow-hidden"
                      >
                        <div className="p-4">
                          <p className="mb-3 text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
                            Edit project
                          </p>
                          <ProjectForm
                            initial={p}
                            onSave={(name, description, instructions) => handleEdit(p.slug, name, description, instructions)}
                            onCancel={() => setEditingSlug(null)}
                            saving={saving}
                          />
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {/* Row */}
                  {editingSlug !== p.slug && (
                    <div className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {/* Active toggle */}
                        <button
                          type="button"
                          onClick={() => activate(p.slug)}
                          title={p.slug === activeProjectSlug ? 'Deactivate workspace' : 'Set as active workspace'}
                          className="shrink-0 text-[var(--metis-fg-dim)] transition hover:text-violet-400"
                        >
                          {p.slug === activeProjectSlug
                            ? <CheckCircle2 className="h-4 w-4 text-violet-400" />
                            : <Circle className="h-4 w-4" />
                          }
                        </button>

                        {/* Name + description */}
                        <button
                          type="button"
                          onClick={() => setExpandedSlug((v) => v === p.slug ? null : p.slug)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className={`truncate text-[13px] font-medium ${p.slug === activeProjectSlug ? 'text-violet-200' : 'text-[var(--metis-foreground)]'}`}>
                            {p.name}
                          </div>
                          {p.description && (
                            <div className="mt-0.5 truncate text-[11px] text-[var(--metis-fg-muted)]">{p.description}</div>
                          )}
                        </button>

                        {/* Actions */}
                        <div className="flex shrink-0 items-center gap-0.5">
                          <button
                            type="button"
                            onClick={() => { setEditingSlug(p.slug); setCreating(false); setExpandedSlug(null); }}
                            className="metis-icon-btn"
                            title="Edit"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (window.confirm(`Delete "${p.name}"? This cannot be undone.`)) {
                                handleDelete(p.slug);
                              }
                            }}
                            disabled={deletingSlug === p.slug}
                            className="metis-icon-btn text-[var(--metis-fg-dim)] hover:text-rose-400"
                            title="Delete"
                          >
                            {deletingSlug === p.slug
                              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              : <Trash2 className="h-3.5 w-3.5" />
                            }
                          </button>
                        </div>
                      </div>

                      {/* Expanded detail */}
                      <AnimatePresence>
                        {expandedSlug === p.slug && (
                          <motion.div
                            initial={reduceMotion ? false : { opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            exit={{ opacity: 0, height: 0 }}
                            className="overflow-hidden"
                          >
                            <div className="mt-2.5 space-y-2 pl-6">
                              {p.instructions ? (
                                <div>
                                  <div className="mb-1 text-[10px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
                                    System instructions
                                  </div>
                                  <pre className="whitespace-pre-wrap rounded-lg border border-[var(--metis-border)] bg-[var(--metis-input-bg)] p-2.5 text-[11px] text-[var(--metis-fg-muted)]">
                                    {p.instructions}
                                  </pre>
                                </div>
                              ) : (
                                <p className="text-[11px] text-[var(--metis-fg-dim)]">No custom instructions set.</p>
                              )}
                              <div className="text-[10px] text-[var(--metis-fg-dim)]">
                                Created {fmtDate(p.created_at)} · slug: <code className="font-mono">{p.slug}</code>
                              </div>
                              <button
                                type="button"
                                onClick={() => activate(p.slug)}
                                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-medium transition ${
                                  p.slug === activeProjectSlug
                                    ? 'border border-violet-500/40 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20'
                                    : 'bg-violet-600 text-white hover:bg-violet-700'
                                }`}
                              >
                                {p.slug === activeProjectSlug
                                  ? <><X className="h-3 w-3" /> Clear workspace</>
                                  : <><Check className="h-3 w-3" /> Set as active workspace</>
                                }
                              </button>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Footer hint */}
        <div className="shrink-0 border-t border-[var(--metis-border)] px-4 py-3 text-[11px] text-[var(--metis-fg-dim)]">
          The active workspace injects its custom instructions into every conversation.
        </div>
      </motion.div>
    </div>
  );
}
