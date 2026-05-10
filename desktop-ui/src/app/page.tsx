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
  CalendarClock,
  Users,
  Bell,
  Monitor,
  Brain,
  BarChart3,
  Search,
  Sunrise,
  Workflow,
  LayoutGrid,
  HelpCircle,
  MessageCircle,
  Scale,
  Paperclip,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { createLocalClient, MetisClient, AuthUser, Schedule, Artifact, RunMode, RunPermission, SessionMessage, SessionSearchResult } from '@/lib/metis-client';
import { Mark, Wordmark } from '@/components/brand';
import LoginScreen, { AuthSuccess } from '@/components/login-screen';
import JobPlanner from '@/components/job-planner';
import JobsPanel from '@/components/jobs-panel';
import RelationshipsPanel from '@/components/relationships-panel';
import InboxPanel from '@/components/inbox-panel';
import ConnectionsPanel from '@/components/connections-panel';
import InstallAppButton from '@/components/install-app-button';
import BriefingPanel from '@/components/briefing-panel';
import MissionsPanel from '@/components/missions-panel';
import MissionDashboard from '@/components/mission-dashboard';
import VoiceButton from '@/components/voice-button';
import MemoryPanel from '@/components/memory-panel';
import HostAutomationMvp from '@/components/host-automation-mvp';
import ReportsPanel from '@/components/reports-panel';
import AnalyticsPanel from '@/components/analytics-panel';
import type { SystemHealth } from '@/lib/metis-client';

// ── Types ──────────────────────────────────────────────────────────────────

type Theme = 'dark' | 'light' | 'system';
type EffectiveTheme = 'dark' | 'light';
type AgentStatus = 'idle' | 'thinking' | 'working' | 'done' | 'error';
type Permission = RunPermission;
type Mode = RunMode;
// MVP 8 — per-turn tone preset that maps to a temperature value.
type Tone = 'precise' | 'balanced' | 'creative';
const TONE_TEMP: Record<Tone, number> = { precise: 0.2, balanced: 0.7, creative: 1.0 };

interface Message {
  id: string;
  role: 'user' | 'agent';
  content: string;
  ts: number;
  status?: AgentStatus;
  // Set when the manager extracted a fenced relationship block at the end
  // of this message; the UI shows a "Saved <name>" pill linking to the
  // Relationships panel.
  savedRelationship?: { id: string; name: string };
  savedArtifact?: { id: string; title: string };
  // The model id the auto-router actually used for this turn — captured
  // from the manager_identity SSE event. Shown as a small "via X" badge
  // so the user can see what's behind the answer without picking a model.
  routedModel?: string;
  // MVP 14 — pending tool approvals from the permission gate. The
  // orchestrator parks until the user clicks Approve or Deny on each.
  pendingApprovals?: Array<{ id: string; tool: string; summary: string }>;
  // History of decisions for this turn (handled = clicked, expired = timed out)
  approvalLog?: Array<{ id: string; tool: string; summary: string; outcome: 'approved' | 'denied' | 'expired' }>;
  // MVP 22 — autonomous mission step trail (role='autonomous' / /run prefix)
  missionId?: string;
  missionStatus?: string;
  missionSteps?: Array<{
    index: number;
    description: string;
    tool?: string | null;
    ok?: boolean;
    duration_ms?: number;
    status: 'running' | 'done' | 'failed';
  }>;
  // MVP 23 — live agent viewport: screenshots / browser captures the
  // agent took during the mission, newest-last. Image is a data: URI
  // (already base64 from the bridge); path is the on-disk artifact.
  liveShots?: Array<{
    step?: number;
    tool?: string;
    title?: string;
    image?: string;          // data:image/...;base64,...
    path?: string;
    artifactId?: string;
    ts: number;
  }>;
}

interface Session {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
}

interface Attachment {
  name: string;
  content: string;
  size: number;
}

// ── Permission tiers ──────────────────────────────────────────────────────

const PERMISSION_META: Record<
  Permission,
  { label: string; short: string; tone: string; chip: string; icon: typeof ShieldCheck }
> = {
  full: {
    label: 'Full',
    short: 'Full access',
    tone: 'rose',
    chip: 'border-rose-500/40 bg-rose-500/10 text-rose-200',
    icon: ShieldAlert,
  },
  balanced: {
    label: 'Balanced',
    short: 'Ask before changes',
    tone: 'violet',
    chip: 'border-violet-500/40 bg-violet-500/10 text-violet-200',
    icon: ShieldCheck,
  },
  read: {
    label: 'Read-only',
    short: 'Research and explain',
    tone: 'emerald',
    chip: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
    icon: Eye,
  },
};

// ── Suggestions (customer-facing) ──────────────────────────────────────────

const SUGGESTIONS: { icon: typeof Mail; label: string; prompt: string }[] = [
  { icon: Mail,     label: 'Summarize my inbox',  prompt: 'Summarize my last 24 hours of emails into a 5-bullet briefing, sorted by priority.' },
  { icon: Globe,    label: 'Research a topic',    prompt: 'Research the top 3 trends in AI agents this week and produce a one-page brief with sources.' },
  { icon: Calendar, label: 'Plan my week',        prompt: 'Look at my calendar and to-do list. Draft a focused weekly plan that protects deep-work time.' },
  { icon: Code,     label: 'Build a small tool',  prompt: 'Build a small Python script that watches my Downloads folder and auto-organizes files by type.' },
];

const QUESTION_STARTERS: { icon: typeof Mail; label: string; prompt: string }[] = [
  {
    icon: HelpCircle,
    label: 'Clarify before you answer',
    prompt:
      'Before you answer my next message: ask me up to 5 short, specific questions until you are sure what "done" looks like. Wait for my answers, then help me.',
  },
  {
    icon: MessageCircle,
    label: 'Stress-test my idea',
    prompt:
      'I will describe a decision or idea in my next message. Your job is to poke holes lovingly: assumptions, blind spots, and what evidence would falsify my take. Finish with two better questions I should answer.',
  },
  {
    icon: Brain,
    label: 'Teach me, then quiz',
    prompt:
      'Explain the topic from my next message for a curious beginner — use a crisp outline + one concrete analogy. End with exactly 3 quick questions that check whether I understood; wait for my answers and correct misconceptions.',
  },
  {
    icon: Scale,
    label: 'Frame a tough decision',
    prompt:
      'Help me decide the tradeoff described in my next message. Lay out objectives, constraints, options, then score them with pros/cons you would bet on — and spell out what new information would most change your mind.',
  },
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

// Compress a model id into a short label for the inline "via X" badge.
// "groq/llama-3.3-70b-versatile" → "groq · llama-3.3-70b". Long local
// tags get cut at the first colon and shortened.
function prettyModel(id: string): string {
  if (id.startsWith('groq/'))   return `groq · ${id.slice('groq/'.length).replace(/-versatile$/, '')}`;
  if (id.startsWith('glm-'))    return `glm · ${id.slice(4)}`;
  if (id.startsWith('gpt-'))    return `openai · ${id}`;
  if (id.includes(':'))         return id.split(':')[0];
  return id;
}

// Removes the auto-save fenced JSON block the Manager appends when it
// profiled a person. Kept symmetric with the backend's regex in
// api_bridge.py so we don't show raw JSON to the user. Tolerates a
// partially-streamed block (no closing fence yet) by truncating from
// the opening fence.
function stripRelationshipBlock(text: string): string {
  const closed = text.replace(/```\s*relationship\s*\n[\s\S]+?\n```\s*$/i, '').trimEnd();
  if (closed !== text) return closed;
  const openIdx = text.search(/```\s*relationship\b/i);
  return openIdx >= 0 ? text.slice(0, openIdx).trimEnd() : text;
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

// Pre-token "thinking" cycler — gives the user something alive to look
// at during the first-token wait on a slow local model. Cycles through
// short status phrases every ~2.5s and folds in an elapsed-time hint
// once we've been waiting more than a beat.
const _PRE_TOKEN_PHRASES = [
  'Thinking',
  'Working it out',
  'Picking the right words',
  'Getting set up',
  'Composing the answer',
];

function useStreamingStatus(streaming: boolean, hasContent: boolean, content: string): string {
  // tick = which phrase to show, elapsed = whole seconds since start.
  // Both are updated by the interval; we never read Date.now() during
  // render (that would be impure).
  const [tick, setTick] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!streaming) return;
    const t0 = Date.now();
    const id = setInterval(() => {
      setTick((t) => t + 1);
      setElapsed(Math.floor((Date.now() - t0) / 1000));
    }, 1000);
    return () => {
      clearInterval(id);
      setTick(0);
      setElapsed(0);
    };
  }, [streaming]);

  if (!streaming) return '';
  if (hasContent) return deriveStatus(content);
  const phrase = _PRE_TOKEN_PHRASES[Math.floor(tick / 2.5) % _PRE_TOKEN_PHRASES.length];
  if (elapsed > 5) return `${phrase} · ${elapsed}s`;
  return `${phrase}…`;
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
        return <CodeBlock key={k} lang={b.lang} text={b.text} />;
      })}
    </div>
  );
}

// Code block with header (language label) + copy button. The pre body
// stays selectable + scrollable; the header floats above it.
function CodeBlock({ lang, text }: { lang: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {}
  };
  const lineCount = text.split('\n').length;
  return (
    <div className="metis-code-block group overflow-hidden rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)]">
      <div className="flex items-center gap-2 border-b border-[var(--metis-border)] bg-[var(--metis-elevated)] px-3 py-1.5">
        <span className="text-[10px] uppercase tracking-widest text-[var(--metis-fg-dim)]">
          {lang || 'code'}
        </span>
        <span className="text-[10px] text-[var(--metis-fg-dim)]">·</span>
        <span className="text-[10px] text-[var(--metis-fg-dim)]">{lineCount} {lineCount === 1 ? 'line' : 'lines'}</span>
        <button
          type="button"
          onClick={onCopy}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-[var(--metis-border)] bg-[var(--metis-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
          title="Copy code"
        >
          {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 text-[12.5px] leading-6 text-[var(--metis-fg)]">
        <code className="font-mono">{text}</code>
      </pre>
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
  const [theme, setTheme] = useState<Theme>('system');
  const [osTheme, setOsTheme] = useState<EffectiveTheme>('dark');
  const [themeReady, setThemeReady] = useState(false);
  const effectiveTheme: EffectiveTheme = theme === 'system' ? osTheme : theme;
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
  // MVP 8 — per-turn tone (temperature preset). Model selection itself
  // is fully auto-routed: cloud-first cascade in brain_engine plus the
  // manager_orchestrator's planner already pick the best model and
  // delegate to specialists where appropriate. No manual override pill.
  const [tone, setTone] = useState<Tone>('balanced');
  const [jobPlanner, setJobPlanner] = useState<{ goal: string } | null>(null);
  const [jobsOpen, setJobsOpen] = useState(false);
  const [relationshipsOpen, setRelationshipsOpen] = useState(false);
  const [inboxOpen, setInboxOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [connectionsOpen, setConnectionsOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [reportsOpen, setReportsOpen] = useState(false);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const [briefingOpen, setBriefingOpen] = useState(false);
  const [missionsOpen, setMissionsOpen] = useState(false);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [activeArtifactId, setActiveArtifactId] = useState<string | null>(null);
  const [reportArtifact, setReportArtifact] = useState<Artifact | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [managerName, setManagerName] = useState<string>('Agent');
  const [appVersion, setAppVersion] = useState<string>('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);

  const composerRef = useRef<HTMLTextAreaElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
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

  useEffect(() => {
    const id = lastAgentMsg?.savedArtifact?.id;
    if (id && !activeArtifactId) setActiveArtifactId(id);
  }, [activeArtifactId, lastAgentMsg?.savedArtifact?.id]);

  // ── theme bootstrap ─────────────────────────────────────────────────────
  // Three modes: 'system' (default — follow OS), 'light', 'dark'.
  // The DOM data-theme attribute always gets the resolved value so CSS
  // variables work in both modes.
  useEffect(() => {
    let stored: Theme | null = null;
    try { stored = localStorage.getItem('metis-theme') as Theme | null; } catch {}
    if (stored === 'light' || stored === 'dark' || stored === 'system') setTheme(stored);
    setThemeReady(true);
  }, []);
  // Watch the OS preference live so 'system' mode updates when the user
  // flips light/dark in their settings.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(prefers-color-scheme: light)');
    const update = () => setOsTheme(mql.matches ? 'light' : 'dark');
    update();
    mql.addEventListener('change', update);
    return () => mql.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', effectiveTheme);
    if (themeReady) try { localStorage.setItem('metis-theme', theme); } catch {}
  }, [theme, effectiveTheme, themeReady]);

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
    try {
      const t = localStorage.getItem('metis-tone');
      if (t === 'precise' || t === 'balanced' || t === 'creative') setTone(t);
    } catch {}
    // Wipe any stale model-override left over from MVP 8's manual picker.
    try { localStorage.removeItem('metis-model-override'); } catch {}

    let cancelled = false;
    (async () => {
      // ── 0. OAuth fallback — when Supabase drops the user back at "/"
      // instead of "/oauth/callback" (because the redirect URL isn't
      // in the project's Redirect URLs allowlist), the code arrives in
      // *our* URL. Detect and finish the flow inline so the user isn't
      // bounced to LoginScreen with their auth code thrown away.
      try {
        const here = new URL(window.location.href);
        const code = here.searchParams.get('code');
        const state = here.searchParams.get('state') || undefined;
        const err = here.searchParams.get('error_description') || here.searchParams.get('error');
        if (code) {
          const fallback = createLocalClient('');
          try {
            const result = await fallback.oauthComplete(code, state);
            const tok = result.session?.access_token;
            const u = result.user;
            if (tok && u) {
              try {
                localStorage.setItem('metis-token', tok);
                localStorage.setItem('metis-auth-mode', 'oauth');
                localStorage.setItem('metis-user', JSON.stringify(u));
              } catch {}
              if (!cancelled) {
                setClient(createLocalClient(tok));
                setUser(u);
              }
            }
          } catch (e) {
            // OAuth completion failed — leave token state alone and
            // stash the error so LoginScreen can surface it (and the
            // user can copy it).
            const msg = e instanceof Error ? e.message : String(e);
            console.warn('[metis] OAuth code on / failed to exchange:', e);
            try { sessionStorage.setItem('metis-auth-error', msg); } catch {}
          }
          // Clean the code/state out of the URL so a refresh doesn't
          // double-spend it (codes are single-use).
          here.searchParams.delete('code');
          here.searchParams.delete('state');
          here.searchParams.delete('error');
          here.searchParams.delete('error_description');
          window.history.replaceState({}, '', here.pathname + (here.searchParams.toString() ? '?' + here.searchParams.toString() : ''));
          if (!cancelled) setAuthResolved(true);
          return;
        }
        if (err) {
          console.warn('[metis] OAuth error returned to /:', err);
          here.searchParams.delete('error');
          here.searchParams.delete('error_description');
          window.history.replaceState({}, '', here.pathname);
        }
      } catch (e) {
        console.warn('[metis] OAuth fallback check failed:', e);
      }

      // ── 1. Saved-session probe ──────────────────────────────────────
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
      // 8-second cap on the saved-session probe. Supabase JWT validation
      // hops to the Supabase API and can take a couple seconds on a slow
      // network — 4s was too tight and was wiping freshly-OAuth'd
      // sessions. On timeout we KEEP the saved user (optimistic) and
      // let the next real API call surface the failure if the token is
      // actually dead.
      const probe = createLocalClient(token);
      try {
        const meP = probe.getMe();
        const timeoutP = new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error('TIMEOUT')), 8000),
        );
        const me = await Promise.race([meP, timeoutP]);
        if (cancelled) return;
        setClient(probe);
        setUser(me.user || savedUser);
        try { localStorage.setItem('metis-user', JSON.stringify(me.user || savedUser)); } catch {}
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (msg === 'TIMEOUT' && savedUser) {
          // Slow network, not a bad token — let the user in optimistically.
          // If the token is genuinely dead, the first real API call will
          // 401 and we can re-gate then.
          if (!cancelled) {
            setClient(probe);
            setUser(savedUser);
          }
        } else {
          // Definite failure (401/403/JSON parse). Clear and re-login.
          try {
            localStorage.removeItem('metis-token');
            localStorage.removeItem('metis-user');
            localStorage.removeItem('metis-auth-mode');
          } catch {}
        }
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
    try { localStorage.setItem('metis-tone', tone); } catch {}
  }, [tone]);

  // Probe the system once at start + whenever the connections panel
  // closes (so a refresh inside it can update the dot color).
  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    (async () => {
      try {
        const h = await client.getSystemHealth();
        if (!cancelled) setHealth(h);
      } catch { /* ignore — UI still works without health */ }
    })();
    return () => { cancelled = true; };
  }, [client, connectionsOpen]);

  // Load manager name + app version once on login.
  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    (async () => {
      try {
        const [cfg, ver] = await Promise.all([client.getManagerConfig(), client.getVersion()]);
        if (cancelled) return;
        if (cfg.config.manager_name) setManagerName(cfg.config.manager_name);
        if (ver.version) setAppVersion(ver.version);
      } catch { /* non-critical */ }
    })();
    return () => { cancelled = true; };
  }, [client]);

  // Poll notifications for the unread count so the bell badge stays fresh.
  // Cheap call; cap to once every 15s. Also re-checks when the panel is
  // closed so dismissing a notification updates the count immediately.
  useEffect(() => {
    if (!client) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const count = await client.getNotificationCount();
        if (!cancelled) setUnreadCount(count.unread);
      } catch { /* offline or auth — leave count alone */ }
    };
    tick();
    const id = setInterval(tick, 15_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [client, inboxOpen]);
  useEffect(() => {
    try { localStorage.setItem('metis-sessions', JSON.stringify(sessions.slice(0, 30))); } catch {}
  }, [sessions]);

  useEffect(() => {
    if (!client || !activeArtifactId) {
      setReportArtifact(null);
      setReportLoading(false);
      return;
    }
    let cancelled = false;
    setReportLoading(true);
    (async () => {
      try {
        const artifact = await client.getArtifact(activeArtifactId);
        if (!cancelled) setReportArtifact(artifact);
      } catch {
        if (!cancelled) setReportArtifact(null);
      } finally {
        if (!cancelled) setReportLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeArtifactId, client]);

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
      else if (k === 'i')   { e.preventDefault(); setInboxOpen((v) => !v); }
      else if (k === 'j')   { e.preventDefault(); setJobsOpen((v) => !v); }
      else if (k === 'r')   { e.preventDefault(); setRelationshipsOpen((v) => !v); }
      else if (k === 'm')   { e.preventDefault(); setMemoryOpen((v) => !v); }
      else if (k === 'p')   { e.preventDefault(); setReportsOpen((v) => !v); }
      else if (k === 'a')   { e.preventDefault(); setAnalyticsOpen((v) => !v); }
      else if (k === 'g')   { e.preventDefault(); setConnectionsOpen((v) => !v); }
      else if (k === 'd')   { e.preventDefault(); setBriefingOpen((v) => !v); }
      else if (k === 'o')   { e.preventDefault(); setMissionsOpen((v) => !v); }
      else if (k === 'g')   { e.preventDefault(); setDashboardOpen((v) => !v); }
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
  const openPersistedSession = async (id: string, fallbackTitle = 'Saved session') => {
    if (!client) return;
    const rows = await client.loadSession(id);
    const messages: Message[] = rows.map((row: SessionMessage, index: number) => ({
      id: `${id}-${index}`,
      role: row.role === 'user' ? 'user' : 'agent',
      content: row.content,
      ts: Number.isFinite(new Date(row.created_at).getTime()) ? new Date(row.created_at).getTime() : Date.now(),
      status: row.role === 'user' ? undefined : 'done',
    }));
    const title = fallbackTitle.trim() || messages.find((m) => m.role === 'user')?.content.slice(0, 60) || 'Saved session';
    const updatedAt = messages.at(-1)?.ts ?? Date.now();
    setSessions((all) => [{
      id,
      title,
      createdAt: messages[0]?.ts ?? updatedAt,
      updatedAt,
      messages,
    }, ...all.filter((s) => s.id !== id)]);
    setActiveId(id);
  };

  // ── send ────────────────────────────────────────────────────────────────
  const send = (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text && attachments.length === 0) return;
    if (streaming) return;
    if (!client) return; // gated by LoginScreen above
    const capturedAttachments = attachments;

    // Job mode short-circuits the chat stream and opens the scheduler.
    // We don't insert the goal as a user message — the user only commits
    // to a job after picking a cadence in the planner.
    if (mode === 'job') {
      setJobPlanner({ goal: text });
      return;
    }

    let session = active;
    if (!session) {
      const titleSrc = text || (capturedAttachments[0]?.name ?? 'Attachment');
      session = {
        id: newId(),
        title: pickTitle(titleSrc),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: [],
      };
      setSessions((all) => [session as Session, ...all]);
      setActiveId(session.id);
    }

    const userMsg: Message = {
      id: newId(),
      role: 'user',
      content: capturedAttachments.length > 0
        ? (text ? text + '\n' : '') + capturedAttachments.map((a) => `📎 ${a.name}`).join('\n')
        : text,
      ts: Date.now(),
    };
    const agentMsg: Message = { id: newId(), role: 'agent', content: '', ts: Date.now(), status: 'thinking' };
    const sId = session.id;

    setSessions((all) =>
      all.map((s) =>
        s.id === sId ? { ...s, updatedAt: Date.now(), messages: [...s.messages, userMsg, agentMsg] } : s,
      ),
    );

    if (!overrideText) setInput('');
    if (!overrideText) setAttachments([]);
    if (composerRef.current) composerRef.current.style.height = 'auto';
    setStreaming(true);

    const ac = new AbortController();
    abortRef.current = ac;

    (async () => {
      let acc = '';
      let saved: { id: string; name: string } | undefined;
      let savedArtifact: { id: string; title: string } | undefined;
      let routedModel: string | undefined;
      try {
        // MVP 22: /run prefix → autonomous loop instead of manager.
        const isAutoRun = text.trimStart().startsWith('/run ');
        const fullText = capturedAttachments.length > 0
          ? (text ? text + '\n\n' : '') + capturedAttachments
              .map((a) => `**Attached: ${a.name}**\n\`\`\`\n${a.content.slice(0, 8000)}\n\`\`\``)
              .join('\n\n')
          : text;
        const chatText  = isAutoRun ? text.trimStart().slice(5).trim() : fullText;
        const chatRole  = isAutoRun ? 'autonomous' : 'manager';
        const stream = client.chat(chatRole, chatText, sId, {
          mode: 'task',
          permission,
          temperature: TONE_TEMP[tone],
        });
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
                        m.id === agentMsg.id ? { ...m, content: stripRelationshipBlock(acc), status: 'working' } : m,
                      ),
                    }
                  : s,
              ),
            );
          } else if (ev.type === 'relationship_saved' && typeof ev.id === 'string' && typeof ev.name === 'string') {
            saved = { id: ev.id, name: ev.name };
            // Optimistic bump; the next /inbox poll will reconcile.
            setUnreadCount((c) => c + 1);
          } else if (ev.type === 'run_artifact_saved' && typeof ev.id === 'string') {
            savedArtifact = { id: ev.id, title: typeof ev.title === 'string' ? ev.title : 'Manager run report' };
            setActiveArtifactId(ev.id);
            setWorkspaceOpen(true);
          } else if (ev.type === 'manager_identity' && typeof ev.model === 'string' && ev.model) {
            // Auto-router decision — capture so we can show "via X" on the
            // finished message. Both direct + orchestrator paths emit this.
            routedModel = ev.model;
          } else if (ev.type === 'approval_required' && typeof ev.id === 'string' && typeof ev.tool === 'string') {
            // The permission gate is parked on a tool call. Push a card
            // onto the agent message so the user can Approve / Deny.
            const approval = { id: ev.id, tool: ev.tool, summary: typeof ev.summary === 'string' ? ev.summary : ev.tool };
            setSessions((all) =>
              all.map((s) =>
                s.id === sId
                  ? {
                      ...s,
                      messages: s.messages.map((m) =>
                        m.id === agentMsg.id
                          ? { ...m, pendingApprovals: [...(m.pendingApprovals || []), approval] }
                          : m,
                      ),
                    }
                  : s,
              ),
            );
          } else if (ev.type === 'mission_start' && isAutoRun) {
            setSessions((all) => all.map((s) => s.id === sId ? {
              ...s, messages: s.messages.map((m) => m.id === agentMsg.id
                ? { ...m, missionId: typeof ev.mission_id === 'string' ? ev.mission_id : undefined, missionStatus: 'running', missionSteps: [] }
                : m),
            } : s));
          } else if (ev.type === 'step_start' && isAutoRun) {
            setSessions((all) => all.map((s) => s.id === sId ? {
              ...s, messages: s.messages.map((m) => {
                if (m.id !== agentMsg.id) return m;
                const newStep = { index: Number(ev.step || 0), description: String(ev.description || ''), status: 'running' as const };
                return { ...m, missionSteps: [...(m.missionSteps || []).filter(x => x.index !== newStep.index), newStep] };
              }),
            } : s));
          } else if (ev.type === 'step_end' && isAutoRun) {
            setSessions((all) => all.map((s) => s.id === sId ? {
              ...s, messages: s.messages.map((m) => {
                if (m.id !== agentMsg.id) return m;
                return { ...m, missionSteps: (m.missionSteps || []).map(x => x.index === Number(ev.step || 0)
                  ? { ...x, ok: Boolean(ev.ok), tool: typeof ev.tool === 'string' ? ev.tool : x.tool, duration_ms: Number(ev.duration_ms || 0), status: ev.ok ? 'done' as const : 'failed' as const }
                  : x) };
              }),
            } : s));
          } else if (ev.type === 'finish' && isAutoRun) {
            acc = String(ev.answer || acc);
            setSessions((all) => all.map((s) => s.id === sId ? {
              ...s, messages: s.messages.map((m) => m.id === agentMsg.id
                ? { ...m, content: acc, missionStatus: 'success' }
                : m),
            } : s));
          } else if ((ev.type as string) === 'live_artifact' && isAutoRun) {
            // MVP 23: agent just produced a screenshot / browser capture.
            // Append to liveShots so the bubble can render the thumbnail strip.
            const shot = {
              step:       typeof ev.step === 'number' ? ev.step : undefined,
              tool:       typeof ev.tool === 'string' ? ev.tool : undefined,
              title:      typeof ev.title === 'string' ? ev.title : undefined,
              image:      typeof ev.image_b64 === 'string' ? ev.image_b64 : undefined,
              path:       typeof ev.path === 'string' ? ev.path : undefined,
              artifactId: typeof ev.artifact_id === 'string' ? ev.artifact_id : undefined,
              ts:         Date.now(),
            };
            setSessions((all) => all.map((s) => s.id === sId ? {
              ...s, messages: s.messages.map((m) => m.id === agentMsg.id
                ? { ...m, liveShots: [...(m.liveShots || []), shot].slice(-12) }
                : m),
            } : s));
          } else if (ev.type === 'mission_end' && isAutoRun) {
            setSessions((all) => all.map((s) => s.id === sId ? {
              ...s, messages: s.messages.map((m) => m.id === agentMsg.id
                ? { ...m, missionStatus: String(ev.status || 'done') }
                : m),
            } : s));
          } else if (ev.type === 'approval_expired' && typeof ev.id === 'string') {
            // Card sat too long — gate already default-denied. Strike it.
            setSessions((all) =>
              all.map((s) =>
                s.id === sId
                  ? {
                      ...s,
                      messages: s.messages.map((m) => {
                        if (m.id !== agentMsg.id) return m;
                        const expired = (m.pendingApprovals || []).find((a) => a.id === ev.id);
                        return {
                          ...m,
                          pendingApprovals: (m.pendingApprovals || []).filter((a) => a.id !== ev.id),
                          approvalLog: expired
                            ? [...(m.approvalLog || []), { ...expired, outcome: 'expired' as const }]
                            : (m.approvalLog || []),
                        };
                      }),
                    }
                  : s,
              ),
            );
          }
        }
        if (!ac.signal.aborted) {
          const finalContent = stripRelationshipBlock(acc);
          setSessions((all) =>
            all.map((s) =>
              s.id === sId
                ? {
                    ...s,
                    messages: s.messages.map((m) =>
                      m.id === agentMsg.id
                        ? { ...m, content: finalContent, status: 'done', savedRelationship: saved, savedArtifact, routedModel }
                        : m,
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

  const copyMsg = async (id: string, content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMsgId(id);
      setTimeout(() => setCopiedMsgId((prev) => (prev === id ? null : prev)), 1200);
    } catch {}
  };

  const handleFiles = (files: FileList | File[]) => {
    const allowed = ['.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.csv', '.yaml', '.yml', '.toml', '.html', '.css', '.sh'];
    Array.from(files as FileList).forEach((file) => {
      const hasAllowedExt = allowed.some((ext) => file.name.toLowerCase().endsWith(ext));
      if (!hasAllowedExt && file.size > 512_000) return;
      const r = new FileReader();
      r.onload = (e) => {
        const content = typeof e.target?.result === 'string' ? e.target.result : '';
        setAttachments((a) => [...a, { name: file.name, content, size: file.size }]);
      };
      r.readAsText(file);
    });
  };

  const removeAttachment = (i: number) => setAttachments((a) => a.filter((_, j) => j !== i));

  // ── App ────────────────────────────────────────────────────────────────
  const hasMessages = !!active && active.messages.length > 0;
  const hasWorkspace = hasMessages || !!activeArtifactId;

  // While the saved-session probe is in flight, show a branded splash so
  // we don't flash the LoginScreen for users who are about to be
  // auto-restored. The probe has a 4-second hard cap so this never
  // strands; if it does, the user can punch out manually.
  if (!authResolved) {
    return <Splash reduceMotion={!!reduceMotion} />;
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
          <SessionsList
            client={client}
            sessions={sessions}
            activeId={activeId}
            setActiveId={setActiveId}
            deleteSession={deleteSession}
            openPersistedSession={openPersistedSession}
            clearAll={() => {
              if (sessions.length === 0) return;
              const ok = window.confirm(`Delete all ${sessions.length} session${sessions.length === 1 ? '' : 's'}? This can't be undone.`);
              if (!ok) return;
              setSessions([]);
              setActiveId(null);
            }}
          />
        )}
        {!sidebarOpen && (
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            {sessions.length > 0 && (
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
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {sidebarOpen && user && (
          <div className="px-3 pt-2 pb-1 text-[11px] text-[var(--metis-fg-dim)] truncate" title={user.email}>
            Signed in as <span className="text-[var(--metis-fg-muted)]">{user.email}</span>
          </div>
        )}
        {sidebarOpen && (
          <div className="grid gap-0.5 px-2 pt-1.5">
            <button
              type="button"
              onClick={() => setJobsOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Jobs (⌘J)"
            >
              <CalendarClock className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Jobs</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘J</span>
            </button>
            <button
              type="button"
              onClick={() => setRelationshipsOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Relationships (⌘R)"
            >
              <Users className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Relationships</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘R</span>
            </button>
            <button
              type="button"
              onClick={() => setMemoryOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Memory (⌘M)"
            >
              <Brain className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Memory</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘M</span>
            </button>
            <button
              type="button"
              onClick={() => setReportsOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Reports (⌘P)"
            >
              <FileText className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Reports</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘P</span>
            </button>
            <button
              type="button"
              onClick={() => setBriefingOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Daily briefing (⌘D)"
            >
              <Sunrise className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Briefing</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘D</span>
            </button>
            <button
              type="button"
              onClick={() => setMissionsOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Missions (⌘O)"
            >
              <Workflow className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Missions</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘O</span>
            </button>
            <button
              type="button"
              onClick={() => setDashboardOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Mission dashboard — run many in parallel (⌘G)"
            >
              <LayoutGrid className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Dashboard</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘G</span>
            </button>
            <button
              type="button"
              onClick={() => setAnalyticsOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Analytics (⌘A)"
            >
              <BarChart3 className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Analytics</span>
              <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">⌘A</span>
            </button>
            <button
              type="button"
              onClick={() => setConnectionsOpen(true)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Connections (⌘G)"
            >
              <Globe className="h-4 w-4 shrink-0 text-violet-400" />
              <span>Connections</span>
              {health && (
                <span className={`ml-auto inline-block h-1.5 w-1.5 rounded-full ${health.ollama.ok || health.groq.ok || health.glm.ok || health.openai.ok ? 'bg-emerald-400' : 'bg-rose-400'}`} />
              )}
              <span className="text-[10px] text-[var(--metis-fg-dim)]">⌘G</span>
            </button>
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
          {!sidebarOpen && (
            <>
              <button
                type="button"
                onClick={() => setInboxOpen(true)}
                className="metis-icon-btn relative"
                aria-label="Inbox"
                title="Inbox (⌘I)"
              >
                <Bell className="h-4 w-4" />
                {unreadCount > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 inline-flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-violet-500 px-0.5 text-[8px] font-medium text-white">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => setJobsOpen(true)}
                className="metis-icon-btn"
                aria-label="Jobs"
                title="Jobs (⌘J)"
              >
                <CalendarClock className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setRelationshipsOpen(true)}
                className="metis-icon-btn"
                aria-label="Relationships"
                title="Relationships (⌘R)"
              >
                <Users className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setMemoryOpen(true)}
                className="metis-icon-btn"
                aria-label="Memory"
                title="Memory (⌘M)"
              >
                <Brain className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setReportsOpen(true)}
                className="metis-icon-btn"
                aria-label="Reports"
                title="Reports (⌘P)"
              >
                <FileText className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={() => setAnalyticsOpen(true)}
                className="metis-icon-btn"
                aria-label="Analytics"
                title="Analytics (⌘A)"
              >
                <BarChart3 className="h-4 w-4" />
              </button>
            </>
          )}
          <button
            type="button"
            onClick={() => setTheme((t) => (t === 'system' ? 'dark' : t === 'dark' ? 'light' : 'system'))}
            className="metis-icon-btn"
            aria-label={`Theme (current: ${theme})`}
            title={`Theme: ${theme}${theme === 'system' ? ` · OS=${effectiveTheme}` : ''} — click to cycle`}
          >
            {theme === 'system' ? <Monitor className="h-4 w-4" /> : effectiveTheme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
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
      <main className={`flex min-w-0 flex-col ${workspaceOpen && hasWorkspace ? 'flex-[0_0_44%] border-r border-[var(--metis-border)]' : 'flex-1'}`}>
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-[var(--metis-border)] bg-[var(--metis-header-bg)] px-4 backdrop-blur-md sm:h-14">
          <div className="flex min-w-0 items-center gap-2">
            <Sparkles className="h-4 w-4 text-violet-400" />
            <div className="truncate text-sm font-medium">{active?.title ?? 'New conversation'}</div>
            {streaming && (
              <HeaderStatus
                streaming={streaming}
                hasContent={!!lastAgentMsg?.content}
                content={lastAgentMsg?.content || ''}
              />
            )}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <ConnectionsBadge health={health} onOpen={() => setConnectionsOpen(true)} />
            <button
              type="button"
              onClick={() => setInboxOpen(true)}
              className="metis-icon-btn relative"
              title={`Inbox${unreadCount ? ` (${unreadCount} unread)` : ''}`}
              aria-label="Inbox"
            >
              <Bell className="h-4 w-4" />
              {unreadCount > 0 && (
                <span className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-violet-500 px-1 text-[9px] font-medium text-white">
                  {unreadCount > 9 ? '9+' : unreadCount}
                </span>
              )}
            </button>
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
                    agentName={managerName}
                    onOpenArtifact={(id) => {
                      setActiveArtifactId(id);
                      setWorkspaceOpen(true);
                    }}
                    copiedMsgId={copiedMsgId}
                    onCopy={copyMsg}
                    onApproval={async (actionId, decision) => {
                      if (!client) return;
                      // Optimistic: move from pending → log immediately so
                      // the user sees feedback even before the server
                      // round-trip lands.
                      setSessions((all) =>
                        all.map((s) =>
                          s.id !== active!.id
                            ? s
                            : {
                                ...s,
                                messages: s.messages.map((mm) => {
                                  if (mm.id !== m.id) return mm;
                                  const found = (mm.pendingApprovals || []).find((a) => a.id === actionId);
                                  return {
                                    ...mm,
                                    pendingApprovals: (mm.pendingApprovals || []).filter((a) => a.id !== actionId),
                                    approvalLog: found
                                      ? [...(mm.approvalLog || []), { ...found, outcome: decision === 'approve' ? 'approved' as const : 'denied' as const }]
                                      : (mm.approvalLog || []),
                                  };
                                }),
                              },
                        ),
                      );
                      try { await client.decideAction(actionId, decision); }
                      catch (e) { console.warn('[metis] decision POST failed:', e); }
                    }}
                  />
                ))}
                <div ref={chatBottomRef} className="h-2" />
              </div>
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="shrink-0 px-3 pb-3 pt-2 sm:px-4 sm:pb-4">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.csv,.yaml,.yml,.toml,.html,.css,.sh"
            className="hidden"
            onChange={(e) => { if (e.target.files) { handleFiles(e.target.files); e.target.value = ''; } }}
          />
          <form
            onSubmit={handleSubmit}
            className="metis-glow-border mx-auto w-full max-w-[760px] rounded-[24px] border border-[var(--metis-composer-border)] p-1.5 transition-[box-shadow,border-color]"
            style={{ background: 'var(--metis-composer-bg)', boxShadow: 'var(--metis-composer-shadow)' }}
            aria-label="Send a message to your agent"
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }}
            onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files); }}
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
              placeholder={mode === 'job' ? 'Schedule a job — e.g. \'check my stocks every weekday morning\'' : 'Ask plainly, or paste context first — coaching tip: \'before you answer, ask me 3 clarifying questions\''}
              disabled={!client}
              className="max-h-[220px] min-h-[44px] w-full resize-none bg-transparent px-3 py-3 text-[14.5px] text-[var(--metis-foreground)] placeholder:text-[var(--metis-fg-dim)] outline-none"
              aria-label="Message"
            />
            {/* Attachment chips */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 px-3 pb-2">
                {attachments.map((a, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] px-2 py-0.5 text-[11.5px] text-[var(--metis-fg-muted)]"
                  >
                    <Paperclip className="h-3 w-3 shrink-0" />
                    <span className="max-w-[140px] truncate">{a.name}</span>
                    <span className="text-[10px] text-[var(--metis-fg-dim)]">({(a.size / 1024).toFixed(1)}KB)</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(i)}
                      className="ml-0.5 text-[var(--metis-fg-dim)] hover:text-rose-400"
                      aria-label={`Remove ${a.name}`}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-1.5 px-1.5 pb-1.5">
              {/* Paperclip attach button */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="metis-icon-btn h-7 w-7"
                title="Attach file"
                aria-label="Attach file"
              >
                <Paperclip className="h-3.5 w-3.5" />
              </button>
              <span className="hidden text-[11px] text-[var(--metis-fg-dim)] sm:inline">
                <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-code-fg)]">↵</kbd> {mode === 'job' ? 'schedule' : 'send'} · <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-code-fg)]">⇧↵</kbd> newline
              </span>
              <div className="ml-auto inline-flex items-center gap-1.5">
                <VoiceButton
                  onAppend={(t) => {
                    const sep = input && !/\s$/.test(input) ? ' ' : '';
                    setInput(input + sep + t);
                  }}
                  onInterim={() => { /* live preview reserved for future */ }}
                  disabled={streaming}
                />
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
                    disabled={!input.trim() && attachments.length === 0}
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

          {/* Composer controls (Mode / Permission / Tone) — below the
              prompt box but still in sight. The model picker is gone:
              the backend auto-routes via the cloud cascade + the
              manager-orchestrator planner. */}
          <div className="mx-auto mt-2 flex max-w-[760px] flex-wrap items-center justify-center gap-1.5 px-1.5 text-center">
            <ModeSelector value={mode} onChange={setMode} />
            <PermissionSelector value={permission} onChange={setPermission} />
            <ToneSelector value={tone} onChange={setTone} />
          </div>
        </div>
      </main>

      {/* Workspace panel */}
      <AnimatePresence initial={false}>
        {workspaceOpen && hasWorkspace && (
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
              <FileText className="h-4 w-4 shrink-0 text-violet-400" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">
                  {reportArtifact?.title || (activeArtifactId ? 'Report' : 'Workspace')}
                </div>
              </div>
              {streaming ? (
                <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">
                  <Loader2 className="h-3 w-3 animate-spin" /> Live
                </span>
              ) : lastAgentMsg?.status === 'done' ? (
                <span className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">
                  <CircleCheck className="h-3 w-3" /> Ready
                </span>
              ) : null}
              <div className="flex shrink-0 items-center gap-1">
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
                {activeArtifactId && (
                  <button
                    type="button"
                    onClick={() => setActiveArtifactId(null)}
                    className="metis-icon-btn"
                    aria-label="Close report"
                    title="Close report"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </header>
            <div ref={workspaceRef} className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto max-w-[760px] px-6 py-7 sm:px-8 sm:py-9">
                {activeArtifactId && (
                  <div className="mb-6 rounded-2xl border border-emerald-500/25 bg-emerald-500/5 p-4">
                    <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-widest text-emerald-300">
                      <FileText className="h-3.5 w-3.5" /> Saved report
                    </div>
                    {reportLoading ? (
                      <div className="mt-3 flex items-center gap-2 text-sm text-[var(--metis-fg-muted)]">
                        <Loader2 className="h-4 w-4 animate-spin text-emerald-300" /> Loading report...
                      </div>
                    ) : reportArtifact ? (
                      <div className="mt-3">
                        <div className="mb-3 text-sm font-semibold text-[var(--metis-fg)]">{reportArtifact.title}</div>
                        {reportArtifact.content ? (
                          <MarkdownView source={reportArtifact.content} />
                        ) : (
                          <p className="text-sm text-[var(--metis-fg-muted)]">Report artifact has no inline content.</p>
                        )}
                      </div>
                    ) : (
                      <p className="mt-3 text-sm text-rose-300">Could not load this report artifact.</p>
                    )}
                  </div>
                )}
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
            permission={permission}
            reduceMotion={!!reduceMotion}
            onClose={() => setJobPlanner(null)}
            onCreated={handleJobCreated}
          />
        )}
      </AnimatePresence>

      {/* Jobs panel — list of all schedules with pause / delete */}
      <AnimatePresence>
        {jobsOpen && client && (
          <JobsPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onOpenArtifact={(id) => {
              setActiveArtifactId(id);
              setWorkspaceOpen(true);
              setJobsOpen(false);
            }}
            onClose={() => setJobsOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Relationships panel — every contact the agent has saved */}
      <AnimatePresence>
        {relationshipsOpen && client && (
          <RelationshipsPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setRelationshipsOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Inbox — notifications from scheduled jobs + saved contacts */}
      <AnimatePresence>
        {inboxOpen && client && (
          <InboxPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onOpenArtifact={(id) => {
              setActiveArtifactId(id);
              setWorkspaceOpen(true);
              setInboxOpen(false);
            }}
            onClose={() => setInboxOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Connections — provider health + how to fix dead keys */}
      <AnimatePresence>
        {connectionsOpen && client && (
          <ConnectionsPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setConnectionsOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Memory — recall + pin facts */}
      <AnimatePresence>
        {memoryOpen && client && (
          <MemoryPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setMemoryOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Daily briefing — read past plans + run today's now */}
      <AnimatePresence>
        {briefingOpen && client && (
          <BriefingPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setBriefingOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Missions — autonomous_loop runs, with resume + delete */}
      <AnimatePresence>
        {missionsOpen && client && (
          <MissionsPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setMissionsOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Mission dashboard — N parallel autonomous missions in a grid */}
      <AnimatePresence>
        {dashboardOpen && client && (
          <MissionDashboard
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setDashboardOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Reports — browse saved run artifacts */}
      <AnimatePresence>
        {reportsOpen && client && (
          <ReportsPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setReportsOpen(false)}
            onOpen={(id) => {
              setActiveArtifactId(id);
              setWorkspaceOpen(true);
              setReportsOpen(false);
            }}
          />
        )}
      </AnimatePresence>

      {/* Analytics */}
      <AnimatePresence>
        {analyticsOpen && client && (
          <AnalyticsPanel
            client={client}
            reduceMotion={!!reduceMotion}
            onClose={() => setAnalyticsOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Settings */}
      <AnimatePresence>
        {settingsOpen && client && (
          <Modal title="Settings" onClose={() => setSettingsOpen(false)} reduceMotion={!!reduceMotion}>
            <SettingsBody
              theme={theme}
              effectiveTheme={effectiveTheme}
              setTheme={setTheme}
              client={client}
              health={health}
              appVersion={appVersion}
              onOpenConnections={() => { setSettingsOpen(false); setConnectionsOpen(true); }}
            />
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
        <p className="mt-10 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--metis-fg-dim)]">
          Ask better questions — sharper answers
        </p>
        <p className="mt-1 max-w-xl text-[13px] text-[var(--metis-fg-muted)]">
          Coaching-style prompts wake up reasoning: clarify intent, expose blind spots, and force the model to engage instead of waffle.
        </p>
        <div className="mt-4 grid gap-2.5 sm:grid-cols-2 sm:gap-3">
          {QUESTION_STARTERS.map(({ icon: Icon, label, prompt }) => (
            <button
              key={label}
              type="button"
              onClick={() => onPick(prompt)}
              suppressHydrationWarning
              className="group relative flex items-start gap-3 rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-bg)]/70 p-3.5 text-left transition hover:border-violet-400/35 hover:bg-[var(--metis-hover-surface)]"
            >
              <span className="rounded-lg border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-2 text-amber-300/90">
                <Icon className="h-4 w-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-[var(--metis-fg)] group-hover:text-violet-200">{label}</div>
                <p className="mt-1 line-clamp-2 text-xs text-[var(--metis-fg-dim)]">{prompt}</p>
              </div>
              <ArrowRight className="mt-1 h-4 w-4 text-[var(--metis-fg-dim)] opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-70" />
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
  agentName,
  onOpenArtifact,
  copiedMsgId,
  onCopy,
  onApproval,
}: {
  msg: Message;
  isLast: boolean;
  streaming: boolean;
  reduceMotion: boolean;
  agentName: string;
  onOpenArtifact: (id: string) => void;
  copiedMsgId: string | null;
  onCopy: (id: string, content: string) => void;
  onApproval?: (actionId: string, decision: 'approve' | 'deny') => void;
}) {
  const isUser = msg.role === 'user';
  const liveAgent = !isUser && streaming && isLast;
  const [expanded, setExpanded] = useState(false);
  // MVP 23: lightbox state for full-size view of a live screenshot.
  const [lightboxShot, setLightboxShot] = useState<string | null>(null);
  // Threshold: expand button appears when content exceeds ~1200 chars.
  const isLong = !liveAgent && msg.content.length > 1200;
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
    <motion.div className="group flex gap-3" {...motionProps}>
      <div className="shrink-0">
        <div className={`flex h-8 w-8 items-center justify-center rounded-full border border-[var(--metis-border)] bg-[var(--metis-elevated)] ${liveAgent ? 'ring-2 ring-violet-500/30' : ''}`}>
          <Sparkles className={`h-4 w-4 text-violet-400 ${liveAgent ? 'animate-pulse' : ''}`} />
        </div>
      </div>
      <div className="min-w-0 flex-1 text-[14px] leading-6">
        <div className="mb-1 flex items-center gap-2">
          <div className="text-[11px] font-medium text-[var(--metis-name-label)]">{agentName}</div>
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
          {msg.routedModel && msg.status === 'done' && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] px-1.5 py-0.5 text-[10px] text-[var(--metis-fg-dim)]"
              title={`Auto-routed to ${msg.routedModel}`}
            >
              via {prettyModel(msg.routedModel)}
            </span>
          )}
          <span className="ml-auto text-[10px] text-[var(--metis-fg-dim)]">{relTime(msg.ts)}</span>
          {msg.content && !liveAgent && (
            <button
              type="button"
              onClick={() => onCopy(msg.id, msg.content)}
              className="opacity-0 group-hover:opacity-100 inline-flex items-center gap-1 rounded-md border border-[var(--metis-border)] px-1.5 py-0.5 text-[10px] text-[var(--metis-fg-dim)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title="Copy message"
              aria-label="Copy message"
            >
              {copiedMsgId === msg.id ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
              {copiedMsgId === msg.id ? 'Copied' : 'Copy'}
            </button>
          )}
        </div>
        {msg.content ? (
          <div className="text-[var(--metis-bubble-fg)]">
            {liveAgent ? (
              <p className="whitespace-pre-wrap text-[14px] leading-6">{msg.content}</p>
            ) : (
              <div className={isLong && !expanded ? 'max-h-48 overflow-hidden' : ''}>
                <MarkdownView source={msg.content} />
              </div>
            )}
            {isLong && !liveAgent && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="mt-2 text-[11px] text-violet-400 hover:text-violet-300"
              >
                {expanded ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>
        ) : (
          <div className="flex gap-1 pt-1" aria-label="Loading">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '0ms' }} />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '150ms' }} />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '300ms' }} />
          </div>
        )}
        {msg.savedRelationship && (
          <div className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-200">
            <Users className="h-3 w-3" />
            Saved <span className="font-medium">{msg.savedRelationship.name}</span>
            <span className="text-[10px] text-violet-300/80">to Relationships</span>
          </div>
        )}
        {msg.savedArtifact && (
          <button
            type="button"
            onClick={() => onOpenArtifact(msg.savedArtifact!.id)}
            className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-200 transition hover:bg-emerald-500/15"
          >
            <FileText className="h-3 w-3" />
            Saved <span className="font-medium">{msg.savedArtifact.title}</span>
          </button>
        )}
        {/* MVP 23 — live agent viewport: thumbnail strip of screenshots */}
        {(msg.liveShots && msg.liveShots.length > 0) && (
          <div className="mt-2 flex flex-wrap items-start gap-1.5">
            {msg.liveShots.map((shot, i) => {
              const src = shot.image; // data: URI
              if (!src) {
                return (
                  <div key={i} className="flex h-16 w-24 items-center justify-center rounded-md border border-[var(--metis-border)] bg-[var(--metis-bg)] text-[10px] text-[var(--metis-fg-dim)]">
                    {shot.tool || 'shot'}
                  </div>
                );
              }
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => setLightboxShot(src)}
                  className="group relative overflow-hidden rounded-md border border-[var(--metis-border)] transition hover:border-violet-500/60 focus:outline-none focus:ring-2 focus:ring-violet-500/40"
                  title={`Step ${shot.step ?? '?'} · ${shot.tool ?? 'capture'}`}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={src}
                    alt={shot.title || shot.tool || 'live capture'}
                    className="h-16 w-24 object-cover"
                  />
                  {shot.step !== undefined && (
                    <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[9px] font-bold text-white">
                      {shot.step}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {/* MVP 23 — lightbox */}
        {lightboxShot && (
          <div
            className="fixed inset-0 z-[200] flex items-center justify-center p-4"
            onClick={() => setLightboxShot(null)}
            style={{ background: 'rgba(0,0,0,0.85)' }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={lightboxShot}
              alt="agent capture full size"
              className="max-h-[92vh] max-w-[92vw] rounded-lg shadow-2xl"
            />
          </div>
        )}
        {/* MVP 22 — autonomous mission step trail */}
        {(msg.missionSteps && msg.missionSteps.length > 0) && (
          <div className="mt-2 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-bg)] divide-y divide-[var(--metis-border)] text-[12px]">
            {msg.missionSteps.sort((a, b) => a.index - b.index).map((step) => (
              <div key={step.index} className="flex items-start gap-2 px-3 py-1.5">
                <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border text-[9px] font-bold ${
                  step.status === 'running'
                    ? 'border-violet-500/40 bg-violet-500/10 text-violet-300 animate-pulse'
                    : step.ok || step.status === 'done'
                      ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                      : 'border-rose-500/40 bg-rose-500/10 text-rose-200'
                }`}>
                  {step.index}
                </span>
                <div className="flex-1 leading-snug text-[var(--metis-fg-muted)]">
                  {step.description}
                  {step.tool && <code className="ml-1 rounded bg-[var(--metis-code-bg)] px-1 text-[10.5px] text-[var(--metis-code-fg)]">{step.tool}</code>}
                  {step.duration_ms ? <span className="ml-1 text-[10px] text-[var(--metis-fg-dim)]">{step.duration_ms}ms</span> : null}
                </div>
              </div>
            ))}
          </div>
        )}
        {/* MVP 14 — pending tool approvals */}
        {(msg.pendingApprovals || []).map((a) => (
          <div
            key={a.id}
            className="mt-2 grid gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-[12.5px] text-amber-100"
          >
            <div className="flex items-start gap-2">
              <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
              <div className="min-w-0 flex-1">
                <div className="text-[11px] uppercase tracking-widest text-amber-300/80">Approval needed</div>
                <code className="mt-0.5 block break-words font-mono text-[11.5px] text-amber-50">{a.summary}</code>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onApproval?.(a.id, 'deny')}
                className="rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1 text-[11.5px] text-amber-100 hover:bg-amber-500/20"
              >
                Deny
              </button>
              <button
                type="button"
                onClick={() => onApproval?.(a.id, 'approve')}
                className="ml-auto inline-flex items-center gap-1 rounded-md bg-emerald-500 px-2.5 py-1 text-[11.5px] font-medium text-white hover:brightness-110"
              >
                <Check className="h-3 w-3" /> Approve
              </button>
            </div>
          </div>
        ))}
        {(msg.approvalLog || []).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {(msg.approvalLog || []).map((a) => {
              const cls = a.outcome === 'approved'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
                : a.outcome === 'denied'
                ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
                : 'border-[var(--metis-border)] bg-[var(--metis-bg)] text-[var(--metis-fg-muted)]';
              return (
                <span
                  key={a.id}
                  className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] ${cls}`}
                  title={a.summary}
                >
                  {a.outcome === 'approved' ? '✓' : a.outcome === 'denied' ? '✗' : '⌛'} {a.tool}
                </span>
              );
            })}
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

// ── Sessions list (sidebar, when expanded) ───────────────────────────────

function stripHtml(value: string): string {
  return value.replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
}

function SessionsList({
  client, sessions, activeId, setActiveId, deleteSession, openPersistedSession, clearAll,
}: {
  client: MetisClient;
  sessions: Session[];
  activeId: string | null;
  setActiveId: (id: string) => void;
  deleteSession: (id: string) => void;
  openPersistedSession: (id: string, fallbackTitle?: string) => Promise<void>;
  clearAll: () => void;
}) {
  const [query, setQuery] = useState('');
  const [serverResults, setServerResults] = useState<SessionSearchResult[]>([]);
  const [serverSearching, setServerSearching] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) =>
      s.title.toLowerCase().includes(q) ||
      s.messages.some((m) => m.content.toLowerCase().includes(q)),
    );
  }, [sessions, query]);
  const serverOnly = useMemo(() => {
    const localIds = new Set(filtered.map((s) => s.id));
    return serverResults.filter((result) => !localIds.has(result.session_id));
  }, [filtered, serverResults]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      const reset = window.setTimeout(() => {
        setServerResults([]);
        setServerError(null);
        setServerSearching(false);
      }, 0);
      return () => window.clearTimeout(reset);
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      if (!cancelled) setServerSearching(true);
      try {
        const rows = await client.searchSessions(q, 8);
        if (!cancelled) {
          setServerResults(rows);
          setServerError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setServerResults([]);
          setServerError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setServerSearching(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [client, query]);

  return (
    <>
      <div className="px-3 pt-3 pb-2">
        <div className="flex items-center gap-2">
          <p className="text-[10px] font-medium uppercase tracking-widest text-[var(--metis-chats-label)]">
            Recent
          </p>
          {sessions.length > 0 && (
            <span className="text-[10px] text-[var(--metis-fg-dim)]">{sessions.length}</span>
          )}
          {sessions.length > 1 && (
            <button
              type="button"
              onClick={clearAll}
              className="ml-auto text-[10px] text-[var(--metis-fg-dim)] hover:text-rose-400"
              title="Delete all sessions"
            >
              Clear all
            </button>
          )}
        </div>
        <input
          type="search"
          placeholder="Search sessions..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="mt-2 w-full rounded-md border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-2 py-1 text-[12px] outline-none placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-1 focus:ring-[var(--metis-focus)]"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {sessions.length === 0 && query.trim().length < 2 ? (
          <div className="mx-2 mt-2 rounded-xl border border-dashed border-[var(--metis-border)] p-3 text-xs text-[var(--metis-fg-dim)]">
            Sessions will appear here as you chat.
          </div>
        ) : filtered.length === 0 && serverOnly.length === 0 && !serverSearching ? (
          <div className="mx-2 mt-2 rounded-xl border border-dashed border-[var(--metis-border)] p-3 text-xs text-[var(--metis-fg-dim)]">
            No matches for &ldquo;{query}&rdquo;.
          </div>
        ) : (
          <>
            <ul className="space-y-0.5">
              {filtered.map((s) => (
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
                  </button>
                </li>
              ))}
            </ul>
            {query.trim().length >= 2 && (
              <div className="mt-3 border-t border-[var(--metis-border)] pt-2">
                <div className="mb-1.5 flex items-center gap-1.5 px-1 text-[10px] font-medium uppercase tracking-widest text-[var(--metis-chats-label)]">
                  <Search className="h-3 w-3" />
                  Saved matches
                  {serverSearching && <Loader2 className="h-3 w-3 animate-spin text-violet-400" />}
                </div>
                {serverError ? (
                  <div className="mx-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1.5 text-[11px] text-rose-200">{serverError}</div>
                ) : serverOnly.length === 0 && !serverSearching ? (
                  <div className="px-1 text-[11px] text-[var(--metis-fg-dim)]">No saved history matches.</div>
                ) : (
                  <ul className="space-y-1">
                    {serverOnly.map((result) => (
                      <li key={`${result.session_id}-${result.created_at}`}>
                        <button
                          type="button"
                          onClick={() => { void openPersistedSession(result.session_id, result.session_title || 'Saved session'); }}
                          className="w-full rounded-lg border border-[var(--metis-border)] bg-[var(--metis-bg)] px-2 py-2 text-left hover:bg-[var(--metis-hover-surface)]"
                          title={stripHtml(result.snippet)}
                        >
                          <div className="truncate text-[12px] font-medium text-[var(--metis-fg)]">{result.session_title || result.session_id}</div>
                          <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-[var(--metis-fg-muted)]">{stripHtml(result.snippet)}</div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

// ── Settings body (rendered inside the Settings modal) ───────────────────

function SettingsBody({
  theme, effectiveTheme, setTheme, client, health, appVersion, onOpenConnections,
}: {
  theme: Theme;
  effectiveTheme: EffectiveTheme;
  setTheme: (t: Theme) => void;
  client: MetisClient;
  health: SystemHealth | null;
  appVersion: string;
  onOpenConnections: () => void;
}) {
  const [models, setModels] = useState<{ id: string; label: string; kind: 'local' | 'cloud'; note?: string }[] | null>(null);
  const [activeModel, setActiveModel] = useState<string>('');
  const [savingModel, setSavingModel] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Load models + current manager_model on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [m, c] = await Promise.all([client.listModels(), client.getManagerConfig()]);
        if (cancelled) return;
        setModels(m.models);
        setActiveModel(c.config.manager_model || '');
      } catch {/* ignore */}
    })();
    return () => { cancelled = true; };
  }, [client]);

  const pick = async (id: string) => {
    setSavingModel(true);
    try {
      await client.setManagerConfig({ manager_model: id });
      setActiveModel(id);
      setSavedAt(Date.now());
      setTimeout(() => setSavedAt(null), 1500);
    } catch {/* ignore */}
    finally { setSavingModel(false); }
  };

  return (
    <div className="grid gap-3">
      {/* Theme */}
      <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Theme</div>
          {theme === 'system' && (
            <span className="text-[10px] text-[var(--metis-fg-dim)]">following OS · {effectiveTheme}</span>
          )}
        </div>
        <div className="mt-2 inline-flex items-center gap-0.5 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5">
          {(['system', 'light', 'dark'] as Theme[]).map((t) => {
            const sel = theme === t;
            const Icon = t === 'light' ? Sun : t === 'dark' ? Moon : Monitor;
            return (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12px] capitalize transition ${
                  sel
                    ? 'border border-violet-500/40 bg-violet-500/10 text-violet-200'
                    : 'border border-transparent text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {t}
              </button>
            );
          })}
        </div>
      </div>

      {/* Manager model picker */}
      <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
        <div className="flex items-center justify-between">
          <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Manager model</div>
          {savingModel ? (
            <Loader2 className="h-3 w-3 animate-spin text-violet-400" />
          ) : savedAt ? (
            <span className="inline-flex items-center gap-1 text-[10px] text-emerald-400"><Check className="h-3 w-3" /> saved</span>
          ) : null}
        </div>
        <p className="mt-1 text-[11px] text-[var(--metis-fg-dim)]">
          Picks the brain that powers your chat. Cloud models are faster but need a key in <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">.env</code>.
        </p>
        {!models ? (
          <div className="mt-3 flex items-center gap-2 text-[12px] text-[var(--metis-fg-muted)]">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" /> Discovering models…
          </div>
        ) : models.length === 0 ? (
          <div className="mt-3 text-[12px] text-rose-300">No models available. Pull one with <code className="rounded bg-[var(--metis-code-bg)] px-1 text-[var(--metis-code-fg)]">ollama pull qwen2.5-coder:1.5b</code>.</div>
        ) : (
          <div className="mt-3 grid max-h-56 gap-1 overflow-y-auto pr-1">
            <button
              type="button"
              onClick={() => pick('')}
              className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[12px] transition ${
                activeModel === ''
                  ? 'border-violet-500/40 bg-violet-500/10 text-violet-200'
                  : 'border-[var(--metis-border)] bg-[var(--metis-bg)] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
              }`}
            >
              <Sparkles className="h-3.5 w-3.5 text-violet-400" />
              <span className="flex-1 font-medium">Auto</span>
              <span className="text-[10px] text-[var(--metis-fg-dim)]">first cloud → local</span>
            </button>
            {models.map((m) => {
              const sel = activeModel === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => pick(m.id)}
                  className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[12px] transition ${
                    sel
                      ? 'border-violet-500/40 bg-violet-500/10 text-violet-200'
                      : 'border-[var(--metis-border)] bg-[var(--metis-bg)] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
                  }`}
                >
                  <span className={`inline-block h-1.5 w-1.5 rounded-full ${m.kind === 'cloud' ? 'bg-emerald-400' : 'bg-violet-400'}`} />
                  <span className="flex-1 truncate">{m.label}</span>
                  {m.note && <span className="shrink-0 text-[10px] text-[var(--metis-fg-dim)]">{m.note}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Local browser + guarded shell MVP */}
      <HostAutomationMvp client={client} />

      {/* Connections quick-link */}
      <button
        type="button"
        onClick={onOpenConnections}
        className="flex items-center gap-3 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3 text-left transition hover:bg-[var(--metis-hover-surface)]"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/15 text-violet-300">
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] text-[var(--metis-fg)]">Connections + API keys</div>
          <div className="text-[11px] text-[var(--metis-fg-dim)]">
            {health?.preferred_manager
              ? `Currently using ${health.preferred_manager}`
              : 'Probe providers and configure keys'}
          </div>
        </div>
        <ArrowRight className="h-4 w-4 text-[var(--metis-fg-dim)]" />
      </button>

      {/* PWA install (MVP 10) */}
      <InstallAppButton />

      {/* Shortcuts */}
      <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
        <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Shortcuts</div>
        <div className="mt-2 space-y-1.5 text-sm text-[var(--metis-fg-muted)]">
          {[
            ['New session',       '⌘ N'],
            ['Focus message box', '⌘ K'],
            ['Toggle sidebar',    '⌘ B'],
            ['Toggle workspace',  '⌘ /'],
            ['Inbox',             '⌘ I'],
            ['Jobs panel',        '⌘ J'],
            ['Relationships',     '⌘ R'],
            ['Memory',            '⌘ M'],
            ['Reports',           '⌘ P'],
            ['Analytics',         '⌘ A'],
            ['Settings',          '⌘ ,'],
          ].map(([a, b]) => (
            <div key={a} className="flex items-center justify-between gap-4">
              <span>{a}</span>
              <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-2 py-0.5 text-xs text-[var(--metis-code-fg)]">{b}</kbd>
            </div>
          ))}
        </div>
      </div>

      {/* Version */}
      {appVersion && (
        <p className="text-center text-[10px] text-[var(--metis-fg-dim)]">
          Metis Command v{appVersion}
        </p>
      )}
    </div>
  );
}

// ── Connection health badge in chat header ────────────────────────────────

function ConnectionsBadge({ health, onOpen }: { health: SystemHealth | null; onOpen: () => void }) {
  // Color: green if any cloud is up, amber if local-only, rose if no
  // provider at all is reachable. Click opens the Connections panel.
  let color = 'text-[var(--metis-fg-dim)]';
  let dot   = 'bg-[var(--metis-fg-dim)]';
  let label = '…';
  if (health) {
    const cloud = health.groq.ok || health.glm.ok || health.openai.ok;
    if (cloud) {
      color = 'text-emerald-300';
      dot   = 'bg-emerald-400';
      label = (health.preferred_manager || 'cloud').toUpperCase();
    } else if (health.ollama.ok) {
      color = 'text-amber-300';
      dot   = 'bg-amber-400';
      label = 'LOCAL';
    } else {
      color = 'text-rose-300';
      dot   = 'bg-rose-400';
      label = 'OFFLINE';
    }
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      className={`metis-icon-btn inline-flex items-center gap-1.5 px-2 ${color}`}
      title="Connection health — click for details"
      aria-label="Connections"
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
      <span className="text-[10px] font-medium tracking-widest">{label}</span>
    </button>
  );
}

// ── Streaming header status pill ──────────────────────────────────────────

function HeaderStatus({ streaming, hasContent, content }: {
  streaming: boolean;
  hasContent: boolean;
  content: string;
}) {
  const label = useStreamingStatus(streaming, hasContent, content);
  if (!streaming) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-300">
      <Loader2 className="h-3 w-3 animate-spin" />
      {label}
    </span>
  );
}

// ── Splash (auth-resolution loader) ───────────────────────────────────────

function Splash({ reduceMotion }: { reduceMotion: boolean }) {
  // We show a "still working…" line after a beat so the user gets
  // feedback that we're waiting on something, plus an escape hatch
  // after 5s so they're never stranded if the probe doesn't resolve.
  const [phase, setPhase] = useState<'enter' | 'connecting' | 'stalled'>('enter');
  useEffect(() => {
    const t1 = setTimeout(() => setPhase('connecting'), 800);
    const t2 = setTimeout(() => setPhase('stalled'), 5000);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  const handleReset = () => {
    try {
      localStorage.removeItem('metis-token');
      localStorage.removeItem('metis-user');
      localStorage.removeItem('metis-auth-mode');
    } catch {}
    window.location.reload();
  };

  return (
    <div className="metis-app-bg relative flex min-h-screen w-full items-center justify-center overflow-hidden text-[var(--metis-fg)]">
      {/* Hero orb behind the mark */}
      <div
        className="pointer-events-none absolute inset-x-0 top-1/3 mx-auto h-80 w-full"
        style={{ background: 'var(--metis-orb-hero)' }}
        aria-hidden
      />
      <motion.div
        initial={reduceMotion ? false : { opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        className="relative flex flex-col items-center gap-4 px-4 text-center"
      >
        <motion.div
          animate={reduceMotion ? undefined : { scale: [1, 1.04, 1] }}
          transition={reduceMotion ? undefined : { duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
          className="relative"
        >
          <div
            className="absolute inset-0 -z-10 rounded-full blur-2xl"
            style={{ background: 'radial-gradient(circle, rgba(167,139,250,0.35), transparent 70%)' }}
            aria-hidden
          />
          <Mark size={56} />
        </motion.div>
        <Wordmark size="large" />
        <div className="mt-1 flex items-center gap-2 text-[12.5px] text-[var(--metis-fg-muted)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-400" />
          <AnimatePresence mode="wait">
            <motion.span
              key={phase}
              initial={reduceMotion ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
            >
              {phase === 'enter' ? 'Waking your agent…' : phase === 'connecting' ? 'Restoring your session…' : 'Still trying…'}
            </motion.span>
          </AnimatePresence>
        </div>
        {phase === 'stalled' && (
          <motion.button
            type="button"
            onClick={handleReset}
            initial={reduceMotion ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.25 }}
            className="mt-2 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] px-3 py-1.5 text-[11.5px] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
          >
            Reset and sign in fresh
          </motion.button>
        )}
      </motion.div>
    </div>
  );
}

// ── Tone selector (MVP 8: per-turn temperature preset) ─────────────────────

const TONE_META: Record<Tone, { label: string; tip: string }> = {
  precise:  { label: 'Precise',  tip: 'Lower temperature — focused, deterministic answers (0.2).' },
  balanced: { label: 'Balanced', tip: 'Default temperature — natural, varied (0.7).' },
  creative: { label: 'Creative', tip: 'Higher temperature — more diverse, exploratory (1.0).' },
};

function ToneSelector({ value, onChange }: { value: Tone; onChange: (v: Tone) => void }) {
  const order: Tone[] = ['precise', 'balanced', 'creative'];
  return (
    <div
      role="radiogroup"
      aria-label="Tone"
      className="inline-flex items-center gap-0.5 rounded-full border border-[var(--metis-border)] bg-[var(--metis-bg)] p-0.5"
    >
      {order.map((t) => {
        const meta = TONE_META[t];
        const sel  = value === t;
        return (
          <button
            key={t}
            type="button"
            role="radio"
            aria-checked={sel}
            onClick={() => onChange(t)}
            title={meta.tip}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] transition ${
              sel
                ? 'border border-violet-500/40 bg-violet-500/10 text-violet-200'
                : 'border border-transparent text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
            }`}
          >
            {meta.label}
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
