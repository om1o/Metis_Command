'use client';

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  Fragment,
  FormEvent,
  KeyboardEvent,
} from 'react';
import {
  Send,
  Plus,
  Settings,
  LogOut,
  Sun,
  Moon,
  Square,
  Sparkles,
  Loader2,
  Trash2,
  PanelLeft,
  PanelRightOpen,
  PanelRightClose,
  Copy,
  Check,
  ArrowRight,
  CircleCheck,
  CircleX,
  X,
  FileText,
  ListChecks,
  Globe,
  Mail,
  Calendar,
  Code,
  ShieldCheck,
  ShieldAlert,
  Eye,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { createLocalClient, MetisClient, AuthUser, Schedule } from '@/lib/metis-client';
import { Mark, Wordmark } from '@/components/brand';
import LoginScreen, { AuthSuccess } from '@/components/login-screen';
import JobPlanner from '@/components/job-planner';

// ── Types ──────────────────────────────────────────────────────────────────

type Theme = 'dark' | 'light';
type AgentStatus = 'idle' | 'thinking' | 'working' | 'done' | 'error';
type Permission = 'full' | 'balanced' | 'read';
type Mode = 'task' | 'job';

interface Message {
  id: string;
  role: 'user' | 'agent';
  content: string;
  ts: number;
  status?: AgentStatus;
}

interface Session {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
}

// ── Permission tiers ──────────────────────────────────────────────────────

const PERMISSION_META: Record<
  Permission,
  { label: string; short: string; tone: string; chip: string; icon: typeof ShieldCheck; system: string }
> = {
  full: {
    label: 'Full',
    short: 'Full access',
    tone: 'rose',
    chip: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
    icon: ShieldAlert,
    system:
      'Permission level: FULL. You may read and write files, run shell commands, install dependencies, and browse the web. Confirm only for destructive actions (delete, force-push, payments).',
  },
  balanced: {
    label: 'Balanced',
    short: 'Ask before changes',
    tone: 'violet',
    chip: 'border-violet-500/40 bg-violet-500/10 text-violet-200',
    icon: ShieldCheck,
    system:
      'Permission level: BALANCED. You may read files and browse the web freely. Ask the user before writing files, running commands, installing packages, or making any external changes.',
  },
  read: {
    label: 'Read-only',
    short: 'Research and explain',
    tone: 'emerald',
    chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    icon: Eye,
    system:
      'Permission level: READ-ONLY. You may answer questions, research, and explain. Do not write files, run commands, or perform any action that changes the user\'s system.',
  },
};

// ── Suggestions (customer-facing) ──────────────────────────────────────────

const SUGGESTIONS: { icon: typeof Mail; label: string; prompt: string }[] = [
  { icon: Mail,     label: 'Summarize my inbox',  prompt: 'Summarize my last 24 hours of emails into a 5-bullet briefing, sorted by priority.' },
  { icon: Globe,    label: 'Research a topic',    prompt: 'Research the top 3 trends in AI agents this week and produce a one-page brief with sources.' },
  { icon: Calendar, label: 'Plan my week',        prompt: 'Look at my calendar and to-do list. Draft a focused weekly plan that protects deep-work time.' },
  { icon: Code,     label: 'Build a small tool',  prompt: 'Build a small Python script that watches my Downloads folder and auto-organizes files by type.' },
];

// ── Utility ────────────────────────────────────────────────────────────────

const newId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

function relTime(ms: number): string {
  const d = Math.max(0, Date.now() - ms);
  if (d < 60_000)     return 'just now';
  if (d < 3_600_000)  return `${Math.floor(d / 60_000)}m ago`;
  if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}h ago`;
  return `${Math.floor(d / 86_400_000)}d ago`;
}

function pickTitle(text: string): string {
  const t = text.trim().replace(/\s+/g, ' ');
  if (t.length <= 48) return t || 'New session';
  return `${t.slice(0, 45).trimEnd()}…`;
}

function formatMinutes(mins: number): string {
  if (!Number.isFinite(mins) || mins <= 0) return 'often';
  if (mins < 60)  return `${mins} min`;
  if (mins === 60) return 'hour';
  if (mins % 1440 === 0) return `${mins / 1440} day${mins === 1440 ? '' : 's'}`;
  if (mins % 60 === 0)   return `${mins / 60} hours`;
  return `${mins} min`;
}

// Heuristic status for the agent header line while it's streaming.
function deriveStatus(content: string): string {
  const lower = content.toLowerCase();
  if (lower.includes('searching')   || lower.includes('looking up')) return 'Researching';
  if (lower.includes('reading')     || lower.includes('opening'))    return 'Reading sources';
  if (lower.includes('writing')     || lower.includes('drafting'))   return 'Drafting';
  if (lower.includes('analyzing')   || lower.includes('comparing'))  return 'Analyzing';
  if (lower.includes('summarizing'))                                  return 'Summarizing';
  if (lower.includes('plan')        || lower.includes('step'))       return 'Planning';
  return 'Thinking';
}

// ── Light markdown renderer ────────────────────────────────────────────────
// Supports: # H1/## H2/### H3, **bold**, *italic*, `inline`, ```code blocks```,
// - bullets, 1. numbered, paragraphs, [text](url) links.

type Block =
  | { type: 'h'; level: 1 | 2 | 3; text: string }
  | { type: 'p'; text: string }
  | { type: 'ul'; items: string[] }
  | { type: 'ol'; items: string[] }
  | { type: 'code'; lang: string; text: string };

function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    if (/^```/.test(line)) {
      const lang = line.slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
      if (i < lines.length) i++;
      blocks.push({ type: 'code', lang, text: buf.join('\n') });
      continue;
    }

    // headings
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push({ type: 'h', level: h[1].length as 1 | 2 | 3, text: h[2].trim() });
      i++;
      continue;
    }

    // bullets
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, ''));
        i++;
      }
      blocks.push({ type: 'ul', items });
      continue;
    }

    // ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''));
        i++;
      }
      blocks.push({ type: 'ol', items });
      continue;
    }

    // blank
    if (line.trim() === '') { i++; continue; }

    // paragraph (consume until blank)
    const buf: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^\s*[-*•]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^```/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push({ type: 'p', text: buf.join(' ') });
  }
  return blocks;
}

function renderInline(text: string, keyBase: string): React.ReactNode {
  // Process in a single pass: links → bold → italic → code.
  // Returns React nodes safely (no dangerouslySetInnerHTML).
  type Token = { type: 'text' | 'code' | 'bold' | 'italic' | 'link'; value: string; href?: string };
  const tokens: Token[] = [];
  let rest = text;

  // We do one regex per pass, prioritizing links/code over bold/italic.
  const consume = (re: RegExp, kind: Token['type']) => {
    const out: Token[] = [];
    for (const tok of tokens.length ? tokens : [{ type: 'text', value: rest } as Token]) {
      if (tok.type !== 'text') { out.push(tok); continue; }
      const s = tok.value;
      let m: RegExpExecArray | null;
      let last = 0;
      const localRe = new RegExp(re.source, re.flags);
      while ((m = localRe.exec(s)) !== null) {
        if (m.index > last) out.push({ type: 'text', value: s.slice(last, m.index) });
        if (kind === 'link') out.push({ type: 'link', value: m[1], href: m[2] });
        else                  out.push({ type: kind, value: m[1] });
        last = m.index + m[0].length;
      }
      if (last < s.length) out.push({ type: 'text', value: s.slice(last) });
    }
    tokens.length = 0;
    tokens.push(...out);
    rest = '';
  };

  consume(/\[([^\]]+)\]\(([^)]+)\)/g, 'link');
  consume(/`([^`]+)`/g, 'code');
  consume(/\*\*([^*]+)\*\*/g, 'bold');
  consume(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, 'italic');

  return (
    <>
      {tokens.map((t, idx) => {
        const k = `${keyBase}-${idx}`;
        if (t.type === 'code')   return <code key={k} className="rounded bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[0.85em] text-[var(--metis-code-fg)]">{t.value}</code>;
        if (t.type === 'bold')   return <strong key={k} className="font-semibold">{t.value}</strong>;
        if (t.type === 'italic') return <em key={k} className="italic">{t.value}</em>;
        if (t.type === 'link')   return <a key={k} href={t.href} target="_blank" rel="noreferrer noopener" className="text-violet-400 underline-offset-2 hover:underline">{t.value}</a>;
        return <Fragment key={k}>{t.value}</Fragment>;
      })}
    </>
  );
}

function MarkdownView({ source }: { source: string }) {
  const blocks = useMemo(() => parseBlocks(source), [source]);
  return (
    <div className="space-y-4 text-[15px] leading-7 text-[var(--metis-fg)]">
      {blocks.map((b, idx) => {
        const k = `b-${idx}`;
        if (b.type === 'h') {
          const Tag: 'h1' | 'h2' | 'h3' = (`h${b.level}` as 'h1' | 'h2' | 'h3');
          const cls =
            b.level === 1 ? 'text-2xl font-semibold tracking-tight text-[var(--metis-foreground)]' :
            b.level === 2 ? 'mt-2 text-xl font-semibold tracking-tight text-[var(--metis-foreground)]' :
                            'mt-1 text-base font-semibold text-[var(--metis-foreground)]';
          return <Tag key={k} className={cls}>{renderInline(b.text, k)}</Tag>;
        }
        if (b.type === 'p')   return <p key={k} className="text-[var(--metis-fg)]">{renderInline(b.text, k)}</p>;
        if (b.type === 'ul')  return (
          <ul key={k} className="ml-5 list-disc space-y-1.5">
            {b.items.map((it, j) => <li key={`${k}-${j}`}>{renderInline(it, `${k}-${j}`)}</li>)}
          </ul>
        );
        if (b.type === 'ol')  return (
          <ol key={k} className="ml-5 list-decimal space-y-1.5">
            {b.items.map((it, j) => <li key={`${k}-${j}`}>{renderInline(it, `${k}-${j}`)}</li>)}
          </ol>
        );
        return (
          <pre key={k} className="overflow-x-auto rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] p-4 text-[13px] leading-6 text-[var(--metis-fg)]">
            {b.lang && <div className="mb-2 text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">{b.lang}</div>}
            <code className="font-mono">{b.text}</code>
          </pre>
        );
      })}
    </div>
  );
}

// Activity items extracted from streaming output (mostly: headings, list items).
function extractActivity(content: string, max = 6): { kind: 'heading' | 'step'; text: string }[] {
  const blocks = parseBlocks(content);
  const out: { kind: 'heading' | 'step'; text: string }[] = [];
  for (const b of blocks) {
    if (b.type === 'h')             out.push({ kind: 'heading', text: b.text });
    else if (b.type === 'ol' || b.type === 'ul') for (const it of b.items) out.push({ kind: 'step', text: it });
    if (out.length >= max) break;
  }
  return out.slice(0, max);
}

// ── Main ───────────────────────────────────────────────────────────────────

export default function App() {
  const [theme, setTheme] = useState<Theme>('dark');
  const [themeReady, setThemeReady] = useState(false);
  const [client, setClient] = useState<MetisClient | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authResolved, setAuthResolved] = useState(false);

  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [workspaceOpen, setWorkspaceOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [permission, setPermission] = useState<Permission>('balanced');
  const [mode, setMode] = useState<Mode>('task');
  const [jobPlanner, setJobPlanner] = useState<{ goal: string } | null>(null);

  const composerRef = useRef<HTMLTextAreaElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const reduceMotion = useReducedMotion();

  const active = useMemo(() => sessions.find((s) => s.id === activeId) || null, [sessions, activeId]);
  const lastAgentMsg = useMemo(() => {
    if (!active) return null;
    for (let i = active.messages.length - 1; i >= 0; i--) {
      if (active.messages[i].role === 'agent') return active.messages[i];
    }
    return null;
  }, [active]);
  const activity = useMemo(() => (lastAgentMsg ? extractActivity(lastAgentMsg.content) : []), [lastAgentMsg]);

  // ── theme bootstrap ─────────────────────────────────────────────────────
  useEffect(() => {
    const stored = localStorage.getItem('metis-theme') as Theme | null;
    if (stored === 'light' || stored === 'dark') setTheme(stored);
    else if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches) setTheme('light');
    setThemeReady(true);
  }, []);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    if (themeReady) try { localStorage.setItem('metis-theme', theme); } catch {}
  }, [theme, themeReady]);

  // ── persistence + saved-session check ──────────────────────────────────
  // We restore a saved session if it still validates against /auth/me.
  // If validation fails (token expired or revoked), we drop it and show
  // the LoginScreen — no silent auto-login.
  useEffect(() => {
    try {
      const raw = localStorage.getItem('metis-sessions');
      if (raw) {
        const parsed: Session[] = JSON.parse(raw);
        setSessions(parsed);
        setActiveId(parsed[0]?.id ?? null);
      }
    } catch {}
    try {
      const p = localStorage.getItem('metis-permission');
      if (p === 'full' || p === 'balanced' || p === 'read') setPermission(p);
    } catch {}
    try {
      const m = localStorage.getItem('metis-mode');
      if (m === 'task' || m === 'job') setMode(m);
    } catch {}

    let cancelled = false;
    (async () => {
      let token: string | null = null;
      let savedUser: AuthUser | null = null;
      try {
        token = localStorage.getItem('metis-token');
        const u = localStorage.getItem('metis-user');
        if (u) savedUser = JSON.parse(u) as AuthUser;
      } catch {}
      if (!token) {
        if (!cancelled) setAuthResolved(true);
        return;
      }
      try {
        const probe = createLocalClient(token);
        const me = await probe.getMe();
        if (cancelled) return;
        setClient(probe);
        setUser(me.user || savedUser);
        try { localStorage.setItem('metis-user', JSON.stringify(me.user || savedUser)); } catch {}
      } catch {
        // Saved token no longer works — clear it and ask the user to sign in.
        try {
          localStorage.removeItem('metis-token');
          localStorage.removeItem('metis-user');
          localStorage.removeItem('metis-auth-mode');
        } catch {}
      } finally {
        if (!cancelled) setAuthResolved(true);
      }
    })();
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    try { localStorage.setItem('metis-permission', permission); } catch {}
  }, [permission]);
  useEffect(() => {
    try { localStorage.setItem('metis-mode', mode); } catch {}
  }, [mode]);
  useEffect(() => {
    try { localStorage.setItem('metis-sessions', JSON.stringify(sessions.slice(0, 30))); } catch {}
  }, [sessions]);

  // ── auto-scroll ─────────────────────────────────────────────────────────
  useEffect(() => { chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [active?.messages.length, streaming]);
  useEffect(() => { if (workspaceRef.current) workspaceRef.current.scrollTop = workspaceRef.current.scrollHeight; }, [lastAgentMsg?.content]);

  // ── shortcuts ───────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (!meta) return;
      const k = e.key.toLowerCase();
      if (k === 'k')        { e.preventDefault(); composerRef.current?.focus(); }
      else if (k === ',')   { e.preventDefault(); setSettingsOpen(true); }
      else if (k === 'b')   { e.preventDefault(); setSidebarOpen((v) => !v); }
      else if (k === '/')   { e.preventDefault(); setWorkspaceOpen((v) => !v); }
      else if (k === 'n')   { e.preventDefault(); newSession(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── auth ────────────────────────────────────────────────────────────────
  const handleAuth = ({ token, user, mode }: AuthSuccess) => {
    setClient(createLocalClient(token));
    setUser(user);
    try {
      localStorage.setItem('metis-token', token);
      localStorage.setItem('metis-user', JSON.stringify(user));
      localStorage.setItem('metis-auth-mode', mode);
    } catch {}
  };
  const handleSignOut = async () => {
    abortRef.current?.abort();
    // Best-effort server-side sign-out for Supabase sessions; ignore failure.
    if (client) { try { await client.signOut(); } catch {} }
    setClient(null);
    setUser(null);
    setStreaming(false);
    try {
      localStorage.removeItem('metis-token');
      localStorage.removeItem('metis-user');
      localStorage.removeItem('metis-auth-mode');
    } catch {}
  };

  // ── sessions ────────────────────────────────────────────────────────────
  const newSession = () => {
    setActiveId(null);
    setInput('');
    composerRef.current?.focus();
  };
  const deleteSession = (id: string) => {
    setSessions((s) => s.filter((x) => x.id !== id));
    if (activeId === id) setActiveId(null);
  };

  // ── send ────────────────────────────────────────────────────────────────
  const send = (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || streaming) return;
    if (!client) return; // gated by LoginScreen above

    // Job mode short-circuits the chat stream and opens the scheduler.
    // We don't insert the goal as a user message — the user only commits
    // to a job after picking a cadence in the planner.
    if (mode === 'job') {
      setJobPlanner({ goal: text });
      return;
    }

    let session = active;
    if (!session) {
      session = {
        id: newId(),
        title: pickTitle(text),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: [],
      };
      setSessions((all) => [session as Session, ...all]);
      setActiveId(session.id);
    }

    const userMsg: Message = { id: newId(), role: 'user', content: text, ts: Date.now() };
    const agentMsg: Message = { id: newId(), role: 'agent', content: '', ts: Date.now(), status: 'thinking' };
    const sId = session.id;

    setSessions((all) =>
      all.map((s) =>
        s.id === sId ? { ...s, updatedAt: Date.now(), messages: [...s.messages, userMsg, agentMsg] } : s,
      ),
    );

    if (!overrideText) setInput('');
    if (composerRef.current) composerRef.current.style.height = 'auto';
    setStreaming(true);

    const ac = new AbortController();
    abortRef.current = ac;

    (async () => {
      let acc = '';
      try {
        // Prepend the permission contract so the agent respects scope
        // without surfacing the directive in the user-visible chat bubble.
        const wireMessage = `${PERMISSION_META[permission].system}\n\n${text}`;
        const stream = client.chat('manager', wireMessage, sId);
        for await (const ev of stream) {
          if (ac.signal.aborted) break;
          if (ev.type === 'token' && ev.delta) {
            acc += ev.delta;
            setSessions((all) =>
              all.map((s) =>
                s.id === sId
                  ? {
                      ...s,
                      messages: s.messages.map((m) =>
                        m.id === agentMsg.id ? { ...m, content: acc, status: 'working' } : m,
                      ),
                    }
                  : s,
              ),
            );
          }
        }
        if (!ac.signal.aborted) {
          setSessions((all) =>
            all.map((s) =>
              s.id === sId
                ? {
                    ...s,
                    messages: s.messages.map((m) =>
                      m.id === agentMsg.id ? { ...m, content: acc, status: 'done' } : m,
                    ),
                  }
                : s,
            ),
          );
        }
      } catch (err) {
        setSessions((all) =>
          all.map((s) =>
            s.id === sId
              ? {
                  ...s,
                  messages: s.messages.map((m) =>
                    m.id === agentMsg.id ? { ...m, content: acc + `\n\n[Error: ${String(err)}]`, status: 'error' } : m,
                  ),
                }
              : s,
          ),
        );
      } finally {
        if (abortRef.current === ac) abortRef.current = null;
        setStreaming(false);
      }
    })();
  };

  const stop = () => { abortRef.current?.abort(); setStreaming(false); };

  // After a job is created, drop a confirmation message into the active
  // (or new) session so the user has a visible breadcrumb of what they
  // just scheduled, plus how it'll run.
  const handleJobCreated = (s: Schedule) => {
    setJobPlanner(null);
    setInput('');
    if (composerRef.current) composerRef.current.style.height = 'auto';

    let session = active;
    if (!session) {
      session = {
        id: newId(),
        title: pickTitle(s.goal),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: [],
      };
      setSessions((all) => [session as Session, ...all]);
      setActiveId(session.id);
    }
    const sId = session.id;

    const cadenceText =
      s.kind === 'daily' ? `every day at ${s.spec}` :
      s.kind === 'interval' ? `every ${formatMinutes(parseInt(s.spec, 10))}` :
      s.kind === 'cron' ? `cron \`${s.spec}\`` :
      `once at ${s.spec}`;

    const nextRun = s.next_run ? new Date(s.next_run * 1000).toLocaleString() : 'soon';

    const userMsg: Message = { id: newId(), role: 'user', content: s.goal, ts: Date.now() };
    const agentMsg: Message = {
      id: newId(),
      role: 'agent',
      content: `**Scheduled** — runs ${cadenceText}.\n\nFirst run: ${nextRun}.\n\n_Goal:_ ${s.goal}`,
      ts: Date.now(),
      status: 'done',
    };
    setSessions((all) =>
      all.map((x) =>
        x.id === sId ? { ...x, updatedAt: Date.now(), messages: [...x.messages, userMsg, agentMsg] } : x,
      ),
    );
  };

  const handleSubmit = (e: FormEvent) => { e.preventDefault(); send(); };
  const onComposerKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const copyAgent = async () => {
    if (!lastAgentMsg) return;
    try { await navigator.clipboard.writeText(lastAgentMsg.content); setCopied(true); setTimeout(() => setCopied(false), 1200); } catch {}
  };

  // ── App ────────────────────────────────────────────────────────────────
  const hasMessages = !!active && active.messages.length > 0;

  // While the saved-session probe is in flight, show a tiny splash so we
  // don't flash the LoginScreen for users who are about to be auto-restored.
  if (!authResolved) {
    return (
      <div className="metis-app-bg flex min-h-screen w-full items-center justify-center text-[var(--metis-fg-muted)]">
        <div className="flex items-center gap-2.5">
          <Mark size={22} />
          <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
        </div>
      </div>
    );
  }

  // No client / user → gate behind the LoginScreen. Until auth succeeds,
  // we don't render any of the chat surface (and never auto-fetch a token).
  if (!client || !user) {
    return <LoginScreen onAuth={handleAuth} />;
  }

  return (
    <div className="metis-app-bg flex h-full w-full min-h-0 text-[var(--metis-fg)]">
      {/* Sessions rail */}
      <aside
        className={`hidden shrink-0 flex-col border-r border-[var(--metis-border)] bg-[var(--metis-bg-sidebar)] transition-[width] duration-200 md:flex ${
          sidebarOpen ? 'w-[260px]' : 'w-[64px]'
        }`}
      >
        <div className="flex items-center gap-2.5 px-3 py-3">
          <Mark size={22} />
          {sidebarOpen && <Wordmark size="md" />}
          <button
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            className="ml-auto metis-icon-btn"
            title={sidebarOpen ? 'Collapse' : 'Expand'}
            aria-label="Toggle sidebar"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
        </div>

        <div className="px-2 pb-2">
          <button
            type="button"
            onClick={newSession}
            className={`flex w-full items-center gap-2 rounded-xl border border-[var(--metis-border)] px-3 py-2.5 text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)] ${
              sidebarOpen ? '' : 'justify-center px-2'
            }`}
            title="New session (⌘N)"
          >
            <Plus className="h-4 w-4 shrink-0" />
            {sidebarOpen && <span>New session</span>}
            {sidebarOpen && <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘N</span>}
          </button>
        </div>

        {sidebarOpen && (
          <div className="px-3 pt-3 pb-1.5">
            <p className="text-[10px] font-medium uppercase tracking-widest text-[var(--metis-chats-label)]">Recent</p>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {sessions.length === 0 ? (
            sidebarOpen && (
              <div className="mx-2 mt-2 rounded-xl border border-dashed border-[var(--metis-border)] p-3 text-xs text-[var(--metis-fg-dim)]">
                Sessions will appear here.
              </div>
            )
          ) : (
            <ul className="space-y-0.5">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setActiveId(s.id)}
                    className={`group flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition ${
                      activeId === s.id
                        ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-fg)]'
                        : 'text-[var(--metis-chats-item)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
                    }`}
                    title={s.title}
                  >
                    <span className={`inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${activeId === s.id ? 'bg-violet-400' : 'bg-[var(--metis-fg-faint)]'}`} aria-hidden />
                    {sidebarOpen && (
                      <>
                        <span className="truncate text-[13px]">{s.title}</span>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); deleteSession(s.id); }
                          }}
                          className="ml-auto inline-flex cursor-pointer items-center justify-center rounded p-1 text-[var(--metis-fg-dim)] opacity-0 transition hover:text-rose-400 group-hover:opacity-100"
                          title="Delete"
                        >
                          <Trash2 className="h-3 w-3" />
                        </span>
                      </>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {sidebarOpen && user && (
          <div className="px-3 pt-2 pb-1 text-[11px] text-[var(--metis-fg-dim)] truncate" title={user.email}>
            Signed in as <span className="text-[var(--metis-fg-muted)]">{user.email}</span>
          </div>
        )}
        <div className="flex gap-1 border-t border-[var(--metis-border)] p-2">
          <button
            type="button"
            onClick={handleSignOut}
            className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)] ${
              sidebarOpen ? '' : 'px-0'
            }`}
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
            {sidebarOpen && 'Sign out'}
          </button>
          <button
            type="button"
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
            className="metis-icon-btn"
            aria-label="Theme"
            title="Theme"
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="metis-icon-btn"
            aria-label="Settings"
            title="Settings (⌘,)"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </aside>

      {/* Chat column */}
      <main className={`flex min-w-0 flex-col ${workspaceOpen && hasMessages ? 'flex-[0_0_44%] border-r border-[var(--metis-border)]' : 'flex-1'}`}>
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-[var(--metis-border)] bg-[var(--metis-header-bg)] px-4 backdrop-blur-md sm:h-14">
          <div className="flex min-w-0 items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-400" />
            <div className="truncate text-sm font-medium">{active?.title ?? 'New conversation'}</div>
            {streaming && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">
                <Loader2 className="h-3 w-3 animate-spin" />
                {lastAgentMsg ? deriveStatus(lastAgentMsg.content) : 'Thinking'}
              </span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => setWorkspaceOpen((v) => !v)}
              className="metis-icon-btn"
              title={workspaceOpen ? 'Hide workspace' : 'Show workspace'}
              aria-label="Toggle workspace"
            >
              {workspaceOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {!hasMessages ? (
            <EmptyHero onPick={(p) => { setInput(p); composerRef.current?.focus(); }} />
          ) : (
            <div className="mx-auto w-full max-w-[760px] px-4 py-6 sm:px-6">
              <div className="flex flex-col gap-5">
                {active!.messages.map((m, idx) => (
                  <MessageBubble
                    key={m.id}
                    msg={m}
                    isLast={idx === active!.messages.length - 1}
                    streaming={streaming}
                    reduceMotion={!!reduceMotion}
                  />
                ))}
                <div ref={chatBottomRef} className="h-2" />
              </div>
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="shrink-0 px-3 pb-3 pt-2 sm:px-4 sm:pb-4">
          <form
            onSubmit={handleSubmit}
            className="metis-glow-border mx-auto w-full max-w-[760px] rounded-[24px] border border-[var(--metis-composer-border)] p-1.5 transition-[box-shadow,border-color]"
            style={{ background: 'var(--metis-composer-bg)', boxShadow: 'var(--metis-composer-shadow)' }}
            aria-label="Send a message to your agent"
          >
            <textarea
              ref={composerRef}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                const t = e.target;
                t.style.height = 'auto';
                t.style.height = `${Math.min(t.scrollHeight, 220)}px`;
              }}
              onKeyDown={onComposerKey}
              placeholder={mode === 'job' ? 'Schedule a job — e.g. \'check my stocks every weekday morning\'' : 'Ask your agent to do something…'}
              disabled={!client}
              className="max-h-[220px] min-h-[44px] w-full resize-none bg-transparent px-3 py-3 text-[14.5px] text-[var(--metis-foreground)] placeholder:text-[var(--metis-fg-dim)] outline-none"
              aria-label="Message"
            />
            <div className="flex flex-wrap items-center gap-1.5 px-1.5 pb-1.5">
              <ModeSelector value={mode} onChange={setMode} />
              <PermissionSelector value={permission} onChange={setPermission} />
              <span className="hidden text-[11px] text-[var(--metis-fg-dim)] sm:inline">
                <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-code-fg)]">↵</kbd> {mode === 'job' ? 'schedule' : 'send'} · <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-code-fg)]">⇧↵</kbd> newline
              </span>
              <div className="ml-auto">
                {streaming ? (
                  <button
                    type="button"
                    onClick={stop}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-full text-white transition hover:brightness-110"
                    style={{ background: 'var(--metis-accent)' }}
                    aria-label="Stop"
                    title="Stop"
                  >
                    <Square className="h-3.5 w-3.5" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-full text-white transition hover:brightness-110 disabled:opacity-40"
                    style={{ background: 'var(--metis-accent)' }}
                    aria-label="Send"
                    title="Send"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
          </form>
        </div>
      </main>

      {/* Workspace panel */}
      <AnimatePresence initial={false}>
        {workspaceOpen && hasMessages && (
          <motion.aside
            key="workspace"
            initial={reduceMotion ? false : { opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 16 }}
            transition={{ duration: 0.18 }}
            className="hidden min-w-0 flex-1 flex-col bg-[var(--metis-bg)] md:flex"
            aria-label="Agent workspace"
          >
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-[var(--metis-border)] bg-[var(--metis-header-bg)] px-4 backdrop-blur-md sm:h-14">
              <FileText className="h-4 w-4 text-violet-400" />
              <div className="text-sm font-medium">Workspace</div>
              {streaming ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">
                  <Loader2 className="h-3 w-3 animate-spin" /> Live
                </span>
              ) : lastAgentMsg?.status === 'done' ? (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">
                  <CircleCheck className="h-3 w-3" /> Ready
                </span>
              ) : null}
              <div className="ml-auto flex items-center gap-1">
                {lastAgentMsg?.content && (
                  <button
                    type="button"
                    onClick={copyAgent}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--metis-border)] px-2 py-1 text-[11px] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
                  >
                    {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                    {copied ? 'Copied' : 'Copy'}
                  </button>
                )}
              </div>
            </header>
            <div ref={workspaceRef} className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto max-w-[760px] px-6 py-7 sm:px-8 sm:py-9">
                {/* Activity strip */}
                {activity.length > 0 && (
                  <div className="mb-6 rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-4">
                    <div className="mb-2 flex items-center gap-2 text-[11px] font-medium uppercase tracking-widest text-[var(--metis-fg-dim)]">
                      <ListChecks className="h-3.5 w-3.5" /> Plan
                    </div>
                    <ul className="space-y-1.5">
                      {activity.map((a, i) => {
                        const Done = !streaming || i < activity.length - 1;
                        return (
                          <li key={i} className="flex items-start gap-2 text-[13px]">
                            <span className="mt-1 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)]">
                              {Done ? (
                                <Check className="h-2.5 w-2.5 text-emerald-400" />
                              ) : (
                                <Loader2 className="h-2.5 w-2.5 animate-spin text-violet-400" />
                              )}
                            </span>
                            <span className={a.kind === 'heading' ? 'font-medium text-[var(--metis-fg)]' : 'text-[var(--metis-fg-muted)]'}>
                              {a.text}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}

                {lastAgentMsg?.content ? (
                  <MarkdownView source={lastAgentMsg.content} />
                ) : (
                  <div className="flex flex-col items-start gap-3 text-sm text-[var(--metis-fg-muted)]">
                    <div className="flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin text-violet-400" />
                      Working on your request…
                    </div>
                    <div className="grid w-full max-w-md gap-2">
                      <div className="h-3 w-[42%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                      <div className="h-3 w-[68%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                      <div className="h-3 w-[54%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Job planner — opens when user submits in Job mode */}
      <AnimatePresence>
        {jobPlanner && client && (
          <JobPlanner
            goal={jobPlanner.goal}
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setJobPlanner(null)}
            onCreated={handleJobCreated}
          />
        )}
      </AnimatePresence>

      {/* Settings */}
      <AnimatePresence>
        {settingsOpen && (
          <Modal title="Settings" onClose={() => setSettingsOpen(false)} reduceMotion={!!reduceMotion}>
            <div className="grid gap-3">
              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
                <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Theme</div>
                <div className="mt-2 flex items-center gap-2">
                  {(['dark', 'light'] as Theme[]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTheme(t)}
                      className={`rounded-lg px-3 py-2 text-sm capitalize transition ${
                        theme === t ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-foreground)]' : 'text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
                <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Shortcuts</div>
                <div className="mt-2 space-y-1.5 text-sm text-[var(--metis-fg-muted)]">
                  {[
                    ['New session',      '⌘ N'],
                    ['Focus message box', '⌘ K'],
                    ['Toggle sidebar',    '⌘ B'],
                    ['Toggle workspace',  '⌘ /'],
                    ['Settings',          '⌘ ,'],
                  ].map(([a, b]) => (
                    <div key={a} className="flex items-center justify-between gap-4">
                      <span>{a}</span>
                      <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-2 py-0.5 text-xs text-[var(--metis-code-fg)]">{b}</kbd>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Modal>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Empty hero ─────────────────────────────────────────────────────────────

function EmptyHero({ onPick }: { onPick: (s: string) => void }) {
  return (
    <div className="relative mx-auto flex h-full w-full max-w-[760px] flex-col justify-center px-4 py-10 sm:px-6 sm:py-14">
      <div
        className="pointer-events-none absolute inset-x-0 top-[8%] mx-auto h-72 w-full"
        style={{ background: 'var(--metis-orb-hero)' }}
        aria-hidden
      />
      <div className="relative">
        <div className="mb-5 flex items-center gap-2 text-[var(--metis-fg-dim)]">
          <Mark size={20} />
          <Wordmark size="md" />
          <span className="ml-1 text-[11px] uppercase tracking-[0.18em] text-[var(--metis-fg-dim)]">Agent</span>
        </div>
        <h1 className="text-balance text-3xl font-light tracking-[-0.02em] text-[var(--metis-hero-title)] sm:text-5xl sm:leading-[1.05]">
          What can your agent do for you today?
        </h1>
        <p className="mt-3 max-w-xl text-balance text-sm text-[var(--metis-hero-sub)] sm:text-base">
          Tell it a goal in plain English. It plans the steps, does the work, and shows you everything as it goes.
        </p>
        <div className="mt-7 grid gap-2.5 sm:grid-cols-2 sm:gap-3">
          {SUGGESTIONS.map(({ icon: Icon, label, prompt }) => (
            <button
              key={label}
              type="button"
              onClick={() => onPick(prompt)}
              suppressHydrationWarning
              className="group relative flex items-start gap-3 rounded-2xl border border-[var(--metis-sugg-border)] bg-[var(--metis-sugg-bg)] p-4 text-left shadow-[var(--metis-sugg-shadow)] transition hover:scale-[1.005] hover:border-violet-500/30"
            >
              <span className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] p-2 text-violet-400">
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-[var(--metis-sugg-title)] group-hover:text-[var(--metis-sugg-title-hover)]">{label}</div>
                <p className="mt-1 line-clamp-2 text-xs text-[var(--metis-sugg-muted)]">{prompt}</p>
              </div>
              <ArrowRight className="mt-1 h-4 w-4 text-[var(--metis-fg-dim)] opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Message bubble ─────────────────────────────────────────────────────────

function MessageBubble({
  msg,
  isLast,
  streaming,
  reduceMotion,
}: {
  msg: Message;
  isLast: boolean;
  streaming: boolean;
  reduceMotion: boolean;
}) {
  const isUser = msg.role === 'user';
  const liveAgent = !isUser && streaming && isLast;
  const motionProps = {
    initial: reduceMotion ? false : { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] as [number, number, number, number] },
  };

  if (isUser) {
    return (
      <motion.div className="flex justify-end" {...motionProps}>
        <div
          className="max-w-[min(100%,520px)] rounded-2xl border border-[var(--metis-bubble-user-border)] bg-[var(--metis-bubble-user)] px-3.5 py-2.5 text-[14px] leading-6 text-[var(--metis-bubble-fg)]"
          style={{ wordBreak: 'break-word' }}
        >
          <p className="whitespace-pre-wrap">{msg.content}</p>
          <div className="mt-1 text-right text-[10px] text-[var(--metis-fg-dim)]">{relTime(msg.ts)}</div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div className="flex gap-3" {...motionProps}>
      <div className="shrink-0">
        <div className={`flex h-8 w-8 items-center justify-center rounded-full border border-[var(--metis-border)] bg-[var(--metis-elevated)] ${liveAgent ? 'ring-2 ring-violet-500/30' : ''}`}>
          <Sparkles className={`h-4 w-4 text-violet-400 ${liveAgent ? 'animate-pulse' : ''}`} />
        </div>
      </div>
      <div className="min-w-0 flex-1 text-[14px] leading-6">
        <div className="mb-1 flex items-center gap-2">
          <div className="text-[11px] font-medium text-[var(--metis-name-label)]">Agent</div>
          {msg.status === 'thinking' && (
            <span className="inline-flex items-center gap-1 text-[11px] text-violet-300">
              <Loader2 className="h-3 w-3 animate-spin" /> Thinking
            </span>
          )}
          {msg.status === 'working' && liveAgent && (
            <span className="inline-flex items-center gap-1 text-[11px] text-violet-300">
              <Loader2 className="h-3 w-3 animate-spin" /> {deriveStatus(msg.content)}
            </span>
          )}
          {msg.status === 'done' && (
            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
              <CircleCheck className="h-3 w-3" /> Done
            </span>
          )}
          {msg.status === 'error' && (
            <span className="inline-flex items-center gap-1 text-[11px] text-rose-400">
              <CircleX className="h-3 w-3" /> Error
            </span>
          )}
          <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">{relTime(msg.ts)}</span>
        </div>
        {msg.content ? (
          <div className="text-[var(--metis-bubble-fg)]">
            <p className="line-clamp-6 whitespace-pre-wrap">{msg.content}</p>
          </div>
        ) : (
          <div className="flex gap-1 pt-1" aria-label="Loading">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '0ms' }} />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '150ms' }} />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '300ms' }} />
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ── Mode selector (Task vs Job) ────────────────────────────────────────────

function ModeSelector({ value, onChange }: { value: Mode; onChange: (v: Mode) => void }) {
  const items: { id: Mode; label: string; tip: string }[] = [
    { id: 'task', label: 'Task',  tip: 'One-off — your agent does it now and reports back.' },
    { id: 'job',  label: 'Job',   tip: 'Recurring — pick a cadence; runs on its own.' },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Run mode"
      className="inline-flex items-center gap-0.5 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5"
    >
      {items.map((m) => {
        const sel = value === m.id;
        return (
          <button
            key={m.id}
            type="button"
            role="radio"
            aria-checked={sel}
            onClick={() => onChange(m.id)}
            title={m.tip}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] transition ${
              sel
                ? 'border border-violet-500/40 bg-violet-500/10 text-violet-200'
                : 'border border-transparent text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
            }`}
          >
            {m.id === 'task' ? <Sparkles className="h-3 w-3" /> : <Calendar className="h-3 w-3" />}
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Permission selector (under composer) ──────────────────────────────────

function PermissionSelector({ value, onChange }: { value: Permission; onChange: (v: Permission) => void }) {
  const order: Permission[] = ['read', 'balanced', 'full'];
  return (
    <div
      role="radiogroup"
      aria-label="Agent permission level"
      className="inline-flex items-center gap-0.5 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5"
    >
      {order.map((p) => {
        const meta = PERMISSION_META[p];
        const Icon = meta.icon;
        const selected = value === p;
        return (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(p)}
            title={meta.short}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] transition ${
              selected
                ? `${meta.chip} border`
                : 'border border-transparent text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
            }`}
          >
            <Icon className="h-3 w-3" />
            {meta.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Modal shell ────────────────────────────────────────────────────────────

function Modal({
  title,
  onClose,
  children,
  reduceMotion,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  reduceMotion: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ background: 'rgba(0,0,0,0.45)' }}
    >
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 10, scale: 0.99 }}
        transition={{ duration: 0.18 }}
        className="metis-glow-border w-full max-w-lg rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-4 shadow-2xl backdrop-blur"
      >
        <div className="flex items-center gap-2.5">
          <Mark size={18} />
          <div className="text-sm font-semibold text-[var(--metis-foreground)]">{title}</div>
          <button type="button" onClick={onClose} className="ml-auto metis-icon-btn" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-3">{children}</div>
      </motion.div>
    </div>
  );
}
