'use client';

import { useMemo, useState, useEffect, useRef, FormEvent, KeyboardEvent } from 'react';
import Image from 'next/image';
import {
  Send,
  Settings,
  LogOut,
  Paperclip,
  Mic,
  SquarePen,
  ChevronDown,
  Sun,
  Moon,
  PanelLeft,
  Copy,
  Check,
  X,
  PanelRightOpen,
  PanelRightClose,
  Info,
  Square,
} from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { createLocalClient } from '@/lib/metis-client';

const SUGGESTIONS: { t: string; s: string }[] = [
  { t: 'Get started', s: 'What can the manager agent do on my machine?' },
  { t: 'Status', s: 'Check local model and bridge status' },
  { t: 'Summarize', s: 'Summarize my open thread context' },
  { t: 'Swarm', s: 'How does the multi-agent roster work?' },
];

type MetisTheme = 'dark' | 'light';

function CanvasStatus({ thinking, hasMessages }: { thinking: boolean; hasMessages: boolean }) {
  if (thinking) {
    return (
      <div className="inline-flex items-center gap-2 text-xs text-[var(--metis-fg-dim)]" aria-live="polite">
        <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-violet-500" aria-hidden />
        Generating
      </div>
    );
  }
  if (!hasMessages) {
    return <div className="text-xs text-[var(--metis-fg-dim)]">Ready</div>;
  }
  return <div className="text-xs text-[var(--metis-fg-dim)]">Live</div>;
}

export default function App() {
  const [theme, setTheme] = useState<MetisTheme>('dark');
  const [themeReady, setThemeReady] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<
    { role: string; content: string; reasoning?: string }[]
  >([]);
  const [thinking, setThinking] = useState(false);
  const [client, setClient] = useState<ReturnType<typeof createLocalClient> | null>(null);
  const [tokenInput, setTokenInput] = useState('');

  const bottomRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const reduceMotion = useReducedMotion();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [chatPanelOpen, setChatPanelOpen] = useState(true);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem('metis-theme') as MetisTheme | null;
    if (stored === 'light' || stored === 'dark') {
      setTheme(stored);
    } else {
      const prefersLight =
        typeof window !== 'undefined' &&
        window.matchMedia('(prefers-color-scheme: light)').matches;
      setTheme(prefersLight ? 'light' : 'dark');
    }
    setThemeReady(true);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    if (!themeReady) return;
    try {
      localStorage.setItem('metis-theme', theme);
    } catch {
      /* private mode */
    }
  }, [theme, themeReady]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking]);

  useEffect(() => {
    if (!client) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'k') return;
      if (!e.metaKey && !e.ctrlKey) return;
      e.preventDefault();
      areaRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [client]);

  useEffect(() => {
    if (!client) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== ',' || (!e.metaKey && !e.ctrlKey)) return;
      e.preventDefault();
      setSettingsOpen(true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [client]);

  const canCopy = typeof navigator !== 'undefined' && !!navigator.clipboard;

  const copyText = async (idx: number, text: string) => {
    if (!canCopy) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIdx(idx);
      window.setTimeout(() => setCopiedIdx((v) => (v === idx ? null : v)), 1200);
    } catch {
      // ignore
    }
  };

  const handleConnect = () => {
    if (tokenInput.trim()) {
      setClient(createLocalClient(tokenInput.trim()));
    }
  };

  const handleNewChat = () => {
    setMessages([]);
    if (areaRef.current) {
      areaRef.current.style.height = 'auto';
    }
  };

  const handleDisconnect = () => {
    setClient(null);
    setMessages([]);
    setInput('');
  };

  const onConnectKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleConnect();
  };

  const runSend = () => {
    if (!input.trim() || !client || thinking) return;
    const userText = input.trim();
    setInput('');
    if (areaRef.current) {
      areaRef.current.style.height = 'auto';
    }
    setMessages((prev) => [...prev, { role: 'user', content: userText }]);
    setThinking(true);
    setMessages((prev) => [...prev, { role: 'assistant', content: '', reasoning: '' }]);

    let assistantContent = '';
    let reasoningContent = '';

    (async () => {
      try {
        const stream = client.chat('manager', userText, 'desktop-session');
        for await (const ev of stream) {
          if (ev.type === 'token' && ev.delta) assistantContent += ev.delta;
          else if (ev.type === 'reasoning' && ev.delta) reasoningContent += ev.delta;
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              role: 'assistant',
              content: assistantContent,
              reasoning: reasoningContent,
            };
            return next;
          });
        }
      } catch (err) {
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: 'assistant',
            content: assistantContent + `\n\n[Error: ${String(err)}]`,
            reasoning: reasoningContent,
          };
          return next;
        });
      } finally {
        setThinking(false);
      }
    })();
  };

  // Best-effort stop: closes the client and forces reconnect (simple + reliable).
  const handleStop = () => {
    setThinking(false);
    setClient(null);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    runSend();
  };

  const onComposerKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      runSend();
    }
  };

  const msgMotion = {
    initial: reduceMotion ? false : { opacity: 0, y: 6 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] as const },
  };

  const panelMotion = {
    initial: reduceMotion ? false : { opacity: 0, x: 10, scale: 0.995 },
    animate: { opacity: 1, x: 0, scale: 1 },
    exit: reduceMotion ? { opacity: 0 } : { opacity: 0, x: 10, scale: 0.995 },
    transition: { duration: 0.18, ease: [0.25, 0.46, 0.45, 0.94] as const },
  };

  const sidebarWidth = useMemo(() => (sidebarCollapsed ? 'w-[72px]' : 'w-72'), [sidebarCollapsed]);
  const inspectorWidth = 'w-[320px]';

  const hasMessages = messages.length > 0;
  const centerGridClass = useMemo(() => {
    if (!chatPanelOpen) return 'grid-cols-1';
    return 'lg:grid-cols-[1fr_380px]';
  }, [chatPanelOpen]);

  if (!client) {
    return (
      <div className="metis-app-bg metis-hero-ambient flex min-h-full flex-col items-center justify-center px-4 py-12 text-[var(--metis-fg)]">
        <form
          className="w-full max-w-[400px] rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-8 shadow-2xl backdrop-blur-sm"
          onSubmit={(e) => {
            e.preventDefault();
            handleConnect();
          }}
          aria-label="Connect to Metis"
        >
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--metis-fg-dim)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
              title={theme === 'dark' ? 'Light' : 'Dark'}
              aria-label="Toggle color theme"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
          <div className="mb-6 flex flex-col items-center text-center">
            <Image
              src="/metis-mark.png"
              width={48}
              height={48}
              alt="Metis Command"
              className="mb-4 h-12 w-12 rounded-xl object-contain"
              unoptimized
            />
            <h1 className="text-2xl font-semibold tracking-tight text-[var(--metis-foreground)]">Metis Command</h1>
            <p className="mt-2 text-balance text-sm text-[var(--metis-fg-muted)]">
              Connect with your{' '}
              <code className="rounded bg-[var(--metis-code-bg)] px-1.5 py-0.5 text-xs text-[var(--metis-code-fg)]">local_auth.token</code> to
              use the local API bridge.
            </p>
          </div>
          <label className="mb-1 block text-xs text-[var(--metis-fg-dim)]">Token</label>
          <input
            type="password"
            autoComplete="off"
            placeholder="Paste token"
            className="mb-4 w-full rounded-xl border border-[var(--metis-border)] bg-[var(--metis-input-bg)] px-3 py-2.5 text-sm text-[var(--metis-foreground)] outline-none ring-0 transition-shadow placeholder:text-[var(--metis-fg-dim)] focus:border-violet-500/50 focus:ring-2 focus:ring-[var(--metis-focus)]"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            onKeyDown={onConnectKeyDown}
          />
          <button
            type="submit"
            className="w-full rounded-xl py-2.5 text-sm font-medium transition hover:opacity-90"
            style={{ background: 'var(--metis-continue-bg)', color: 'var(--metis-continue-fg)' }}
          >
            Continue
          </button>
          <p className="mt-4 text-center text-xs text-[var(--metis-fg-dim)]">Runs on your device · local-first</p>
        </form>
      </div>
    );
  }

  return (
    <div className="metis-app-bg flex h-full w-full min-h-0 text-[var(--metis-fg)]">
      <a
        className="metis-skip-link"
        href="#metis-composer"
      >
        Skip to message
      </a>
      {/* Metis: navigation rail (not a clone of any third-party UI) */}
      <aside
        className={`flex shrink-0 flex-col border-r border-[var(--metis-border)] bg-[var(--metis-bg-sidebar)] ${sidebarWidth}`}
        aria-label="Metis Command"
      >
        <div className="p-2">
          <div className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5">
            <Image
              src="/metis-mark.png"
              width={28}
              height={28}
              alt=""
              className="h-7 w-7 rounded-md object-contain"
              unoptimized
            />
            {!sidebarCollapsed && (
              <span className="truncate text-sm font-semibold tracking-tight">Metis Command</span>
            )}
            <button
              type="button"
              onClick={() => setSidebarCollapsed((v) => !v)}
              className="metis-icon-btn"
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          </div>
          <button
              type="button"
              onClick={handleNewChat}
              className={`mt-2 flex w-full items-center gap-2 rounded-xl border border-[var(--metis-border)] bg-transparent px-3 py-2.5 text-left text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--metis-focus-ring)] ${sidebarCollapsed ? 'justify-center px-2' : ''}`}
            >
            <SquarePen className="h-4 w-4 shrink-0" />
            {!sidebarCollapsed && 'New chat'}
          </button>
        </div>
        <div className="px-2 pt-3">
          {!sidebarCollapsed && (
            <p className="mb-1.5 px-2 text-[10px] font-medium uppercase tracking-widest text-[var(--metis-chats-label)]">
              Chats
            </p>
          )}
          <div
            className={`flex cursor-default items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-[var(--metis-chats-item)] ${sidebarCollapsed ? 'justify-center' : ''}`}
          >
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
            {!sidebarCollapsed && <span className="truncate">This session</span>}
          </div>
        </div>
        <div className="min-h-0 flex-1" />
        <div className="border-t border-[var(--metis-border)] p-2">
          {!sidebarCollapsed && (
            <div className="mb-1 rounded-md px-2 py-1 text-xs text-[var(--metis-fg-dim)]">Session</div>
          )}
          <div className="text-xs" style={{ color: 'var(--metis-session-line)' }}>
            {sidebarCollapsed ? 'Manager' : 'Manager · local swarm'}
          </div>
        </div>
        <div className="flex gap-1 border-t border-[var(--metis-border)] p-2">
          <button
            type="button"
            onClick={handleDisconnect}
            className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)] ${sidebarCollapsed ? 'px-0' : ''}`}
            title="Disconnect"
          >
            <LogOut className="h-4 w-4" />
            {!sidebarCollapsed && 'Log out'}
          </button>
          <button
            type="button"
            onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
            className="rounded-lg p-2 text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
            title={theme === 'dark' ? 'Light' : 'Dark'}
            aria-label="Toggle color theme"
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="rounded-lg p-2 text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
            title="Settings"
            aria-label="Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </aside>

      <main
        className="flex min-w-0 flex-1 flex-col"
        id="metis-main"
        aria-label="Chat with Metis"
      >
        {settingsOpen && (
          <div
            className="fixed inset-0 z-[120] flex items-center justify-center p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Settings"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setSettingsOpen(false);
            }}
            style={{ background: 'rgba(0,0,0,0.45)' }}
          >
            <motion.div
              initial={reduceMotion ? false : { opacity: 0, y: 10, scale: 0.99 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.18 }}
              className="metis-glow-border w-full max-w-lg rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-4 shadow-2xl backdrop-blur"
            >
              <div className="flex items-center gap-2">
                <div className="text-sm font-semibold text-[var(--metis-foreground)]">Settings</div>
                <div className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setSettingsOpen(false)}
                    className="metis-icon-btn"
                    aria-label="Close"
                    title="Close"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>

              <div className="mt-3 grid gap-3">
                <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
                  <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Theme</div>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setTheme('dark')}
                      className={`rounded-lg px-3 py-2 text-sm transition ${
                        theme === 'dark'
                          ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-foreground)]'
                          : 'text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
                      }`}
                    >
                      Dark
                    </button>
                    <button
                      type="button"
                      onClick={() => setTheme('light')}
                      className={`rounded-lg px-3 py-2 text-sm transition ${
                        theme === 'light'
                          ? 'bg-[var(--metis-hover-surface)] text-[var(--metis-foreground)]'
                          : 'text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)]'
                      }`}
                    >
                      Light
                    </button>
                  </div>
                </div>

                <div className="rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
                  <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Shortcuts</div>
                  <div className="mt-2 space-y-1 text-sm text-[var(--metis-fg-muted)]">
                    <div className="flex items-center justify-between gap-4">
                      <span>Focus composer</span>
                      <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-2 py-0.5 text-xs text-[var(--metis-code-fg)]">
                        Ctrl/⌘ + K
                      </kbd>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <span>Open settings</span>
                      <kbd className="rounded border border-[var(--metis-border)] bg-[var(--metis-code-bg)] px-2 py-0.5 text-xs text-[var(--metis-code-fg)]">
                        Ctrl/⌘ + ,
                      </kbd>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        )}

        <header
          className="flex h-12 shrink-0 items-center border-b border-[var(--metis-border)] bg-[var(--metis-header-bg)] px-4 backdrop-blur-md sm:h-14 sm:px-5"
          style={{ paddingTop: 'max(0px, env(safe-area-inset-top, 0px))' }}
        >
          <div className="inline-flex min-w-0 max-w-full items-center gap-2 sm:max-w-md">
            <h2 className="sr-only">Current model</h2>
            <button
              type="button"
              className="group inline-flex h-8 max-w-full items-center gap-0.5 rounded-2xl border border-transparent pl-0 pr-1.5 text-sm text-[var(--metis-header-button-fg)] transition hover:bg-[var(--metis-hover-surface)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--metis-focus-ring)]"
              title="Manager · local (single endpoint for now)"
            >
              <span className="truncate pl-0.5 font-medium">Manager</span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[var(--metis-chevron)] group-hover:text-[var(--metis-chevron-hover)]" />
            </button>
            {thinking && (
              <span
                className="inline-flex items-center gap-1.5 pl-0.5 text-xs text-[var(--metis-fg-dim)]"
                aria-live="polite"
              >
                <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-500" />
                Generating
              </span>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={() => setInspectorOpen((v) => !v)}
              className="metis-icon-btn hidden md:inline-flex"
              title={inspectorOpen ? 'Hide info panel' : 'Show info panel'}
              aria-label={inspectorOpen ? 'Hide info panel' : 'Show info panel'}
            >
              {inspectorOpen ? (
                <PanelRightClose className="h-4 w-4" />
              ) : (
                <PanelRightOpen className="h-4 w-4" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setSettingsOpen(true)}
              className="metis-icon-btn"
              title="Settings (Ctrl/⌘+,)"
              aria-label="Open settings"
            >
              <Settings className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div
          className="min-h-0 flex-1 p-3 sm:p-4"
        >
          <section
            className="metis-glow-border flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] shadow-2xl backdrop-blur-md"
            aria-label="Canvas"
          >
            <div className="flex items-center gap-2 border-b border-[var(--metis-border)] px-4 py-3">
              <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Canvas</div>
              <div className="ml-2">
                <CanvasStatus thinking={thinking} hasMessages={hasMessages} />
              </div>
              <div className="ml-auto flex items-center gap-1">
                <div className="hidden items-center gap-2 text-xs text-[var(--metis-fg-dim)] sm:flex">
                  <span>Ctrl/⌘ + K</span>
                  <span className="text-[var(--metis-fg-faint)]">focus</span>
                </div>
                <button
                  type="button"
                  onClick={() => setChatPanelOpen((v) => !v)}
                  className="metis-icon-btn"
                  title={chatPanelOpen ? 'Hide chat panel' : 'Show chat panel'}
                  aria-label={chatPanelOpen ? 'Hide chat panel' : 'Show chat panel'}
                >
                  {chatPanelOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <div className={`grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 sm:gap-4 sm:p-4 ${centerGridClass}`}>
              {/* Preview hero */}
              <section
                className="metis-glow-border metis-surface relative flex min-h-0 flex-col overflow-hidden"
                aria-label="Preview"
              >
                <div className="metis-surface-header flex items-center gap-2 px-4 py-3">
                  <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Preview</div>
                  <div className="ml-auto flex items-center gap-1.5">
                    <div className="hidden text-xs text-[var(--metis-fg-dim)] sm:block">Coming next: renderables</div>
                    <button
                      type="button"
                      onClick={handleNewChat}
                      className="metis-icon-btn"
                      title="Clear chat"
                      aria-label="Clear chat"
                    >
                      <SquarePen className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <div className="min-h-0 flex-1 p-5 sm:p-6">
                  {!hasMessages ? (
                    <div className="relative h-full overflow-hidden rounded-[22px] border border-[var(--metis-border)] bg-[var(--metis-bg)] p-6 sm:p-8">
                      <div
                        className="pointer-events-none absolute inset-x-0 top-[-25%] mx-auto h-80 w-[min(100%,52rem)]"
                        style={{ background: 'var(--metis-orb-hero)' }}
                        aria-hidden
                      />
                      <div className="relative max-w-2xl">
                        <div className="text-xs font-medium tracking-wide text-[var(--metis-fg-dim)]">Metis Make</div>
                        <h2 className="mt-3 text-balance text-3xl font-light tracking-[-0.02em] text-[var(--metis-hero-title)] sm:text-5xl sm:leading-[1.08]">
                          Your preview appears here
                        </h2>
                        <p className="mt-4 text-balance text-sm text-[var(--metis-hero-sub)] sm:text-base sm:leading-relaxed">
                          Start from a prompt below. Metis will generate a plan, then run it locally on your machine.
                        </p>
                        <div className="mt-7 grid gap-2.5 sm:grid-cols-2 sm:gap-3">
                          {SUGGESTIONS.map(({ t, s }) => (
                            <button
                              key={s}
                              type="button"
                              onClick={() => {
                                setInput(s);
                                areaRef.current?.focus();
                              }}
                              className="group rounded-2xl border border-[var(--metis-sugg-border)] bg-[var(--metis-sugg-bg)] px-4 py-3.5 text-left text-sm text-[var(--metis-sugg-text)] transition duration-200 shadow-[var(--metis-sugg-shadow)] hover:scale-[1.01] hover:border-violet-500/25"
                            >
                              <span className="mb-1.5 block text-xs font-medium text-[var(--metis-sugg-title)] group-hover:text-[var(--metis-sugg-title-hover)]">
                                {t}
                              </span>
                              <span className="line-clamp-2 text-[13px] leading-relaxed text-[var(--metis-sugg-muted)] group-hover:opacity-90">
                                {s}
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : thinking ? (
                    <div className="h-full overflow-hidden rounded-[22px] border border-[var(--metis-border)] bg-[var(--metis-bg)] p-6 sm:p-8">
                      <div className="text-sm font-medium text-[var(--metis-fg)]">Generating layout…</div>
                      <div className="mt-4 grid max-w-xl gap-2">
                        <div className="h-3 w-[42%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                        <div className="h-3 w-[68%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                        <div className="h-3 w-[54%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                        <div className="mt-3 h-3 w-[62%] animate-pulse rounded-full bg-[var(--metis-hover-surface)]" />
                      </div>
                    </div>
                  ) : (
                    <div className="h-full overflow-hidden rounded-[22px] border border-[var(--metis-border)] bg-[var(--metis-bg)] p-6 sm:p-8">
                      <div className="text-sm font-medium text-[var(--metis-fg)]">Preview</div>
                      <p className="mt-2 max-w-xl text-sm text-[var(--metis-fg-muted)]">
                        Next step: wire the manager stream to produce structured “renderables” we can display here (cards, plans, UI diffs).
                      </p>
                      <div className="mt-6 grid gap-2">
                        <div className="h-14 w-full rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated)]" />
                        <div className="h-14 w-[86%] rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated)]" />
                        <div className="h-14 w-[72%] rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated)]" />
                      </div>
                    </div>
                  )}
                </div>
              </section>

              {/* Chat panel (secondary) */}
              <AnimatePresence initial={false}>
                {chatPanelOpen && (
                  <motion.section
                    {...panelMotion}
                    className="metis-glow-border metis-surface flex min-h-0 flex-col overflow-hidden"
                    aria-label="Chat"
                  >
                    <div className="metis-surface-header flex items-center gap-2 px-4 py-3">
                      <div className="text-xs font-medium text-[var(--metis-fg-dim)]">Chat</div>
                      <div className="ml-auto text-xs text-[var(--metis-fg-dim)]">Manager</div>
                    </div>

                    <div className="min-h-0 flex-1 overflow-y-auto">
                      <div className="px-4 py-5">
                        <div className="flex flex-col gap-4">
                          {messages.map((msg, idx) => {
                            const isUser = msg.role === 'user';
                            const isLast = idx === messages.length - 1;
                            const streaming = thinking && isLast && !isUser;

                            if (isUser) {
                              return (
                                <motion.div
                                  key={idx}
                                  className="flex justify-end"
                                  {...msgMotion}
                                >
                                  <div
                                    className="max-w-[min(100%,18rem)] rounded-2xl border border-[var(--metis-bubble-user-border)] bg-[var(--metis-bubble-user)] px-3 py-2 text-[13px] leading-6 text-[var(--metis-bubble-fg)]"
                                    style={{ wordBreak: 'break-word' }}
                                  >
                                    <p className="whitespace-pre-wrap">{msg.content}</p>
                                  </div>
                                </motion.div>
                              );
                            }

                            return (
                              <motion.div key={idx} className="group flex gap-2" {...msgMotion}>
                                <div className="shrink-0 select-none">
                                  <Image
                                    src="/metis-mark.png"
                                    width={24}
                                    height={24}
                                    className="mt-0.5 h-6 w-6 rounded-md object-contain"
                                    alt="Metis"
                                    unoptimized
                                  />
                                </div>
                                <div className="min-w-0 flex-1 text-[13px] leading-6 text-[var(--metis-bubble-fg)]">
                                  <div className="mb-1 flex items-center gap-2">
                                    <div className="text-[11px] font-medium text-[var(--metis-name-label)]">Metis</div>
                                    <div className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                                      <button
                                        type="button"
                                        onClick={() => copyText(idx, msg.content)}
                                        disabled={!canCopy}
                                        className="metis-icon-btn"
                                        title={canCopy ? 'Copy' : 'Copy unavailable'}
                                        aria-label="Copy message"
                                      >
                                        {copiedIdx === idx ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                                      </button>
                                    </div>
                                  </div>
                                  {msg.content ? (
                                    <p className="whitespace-pre-wrap">{msg.content}</p>
                                  ) : (
                                    streaming && (
                                      <div className="flex gap-1 pt-1" aria-label="Loading">
                                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '0ms' }} />
                                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '150ms' }} />
                                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-violet-400" style={{ animationDelay: '300ms' }} />
                                      </div>
                                    )
                                  )}
                                </div>
                              </motion.div>
                            );
                          })}
                        </div>
                        <div ref={bottomRef} className="h-2" />
                      </div>
                    </div>
                  </motion.section>
                )}
              </AnimatePresence>
            </div>
          </section>
        </div>

        {/* Rounded composer bar (common AI chat pattern) */}
        <div
          className="shrink-0 bg-transparent p-3 sm:p-4"
          style={{
            paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom, 0px))',
          }}
        >
          <div
            className="pointer-events-none absolute inset-x-0 bottom-0 h-36"
            style={{
              background:
                'linear-gradient(to top, color-mix(in srgb, var(--metis-bg) 85%, transparent), transparent)',
            }}
            aria-hidden
          />
          <div className="mx-auto mb-2 w-full max-w-[56rem] px-1">
            <div className="flex items-center gap-2">
              <div className="-mx-1 flex min-w-0 flex-1 gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {SUGGESTIONS.map(({ t, s }) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => {
                      setInput(s);
                      areaRef.current?.focus();
                    }}
                    className="metis-chip shrink-0 rounded-full px-3 py-1.5 text-xs"
                    title={s}
                  >
                    {t}
                  </button>
                ))}
              </div>
              <div className="ml-auto hidden text-xs text-[var(--metis-fg-dim)] sm:block">
                Enter to send · Shift+Enter new line
              </div>
            </div>
          </div>
          <form
            id="metis-composer"
            onSubmit={handleSubmit}
            aria-busy={thinking}
            aria-label="Message composer"
            className="metis-composer metis-glow-border mx-auto w-full max-w-[56rem] rounded-[28px] border border-[var(--metis-composer-border)] p-1.5 pl-2 transition-[box-shadow,border-color] duration-200 sm:pl-3"
            style={{
              background: 'var(--metis-composer-bg)',
              boxShadow: 'var(--metis-composer-shadow)',
            }}
          >
            <div className="flex min-h-[3rem] items-end gap-1 sm:gap-2">
              <div className="mb-0.5 flex gap-0.5">
                <button
                  type="button"
                  disabled
                  className="metis-icon-btn opacity-60"
                  style={{ color: 'var(--metis-composer-icon)' }}
                  title="Attach (coming soon)"
                  tabIndex={-1}
                >
                  <Paperclip className="h-5 w-5" />
                </button>
                <button
                  type="button"
                  disabled
                  className="metis-icon-btn opacity-60"
                  style={{ color: 'var(--metis-composer-icon)' }}
                  title="Voice (coming soon)"
                  tabIndex={-1}
                >
                  <Mic className="h-5 w-5" />
                </button>
              </div>
              <textarea
                ref={areaRef}
                rows={1}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  const t = e.target;
                  t.style.height = 'auto';
                  t.style.height = `${Math.min(t.scrollHeight, 200)}px`;
                }}
                onKeyDown={onComposerKeyDown}
                placeholder="Message Metis…"
                disabled={thinking}
                className="max-h-[220px] min-h-12 flex-1 resize-none bg-transparent py-3 text-sm text-[var(--metis-foreground)] placeholder:text-[var(--metis-fg-dim)] outline-none"
                aria-label="Message"
                autoComplete="off"
              />
              <div className="shrink-0 p-0.5 pb-0.5">
                {thinking ? (
                  <button
                    type="button"
                    onClick={handleStop}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-white transition hover:brightness-110 sm:h-9 sm:w-9"
                    style={{ background: 'var(--metis-accent)' }}
                    title="Stop"
                    aria-label="Stop generating"
                  >
                    <Square className="h-3.5 w-3.5" />
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim()}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-35 sm:h-9 sm:w-9"
                    style={{ background: 'var(--metis-accent)' }}
                    title="Send"
                    aria-label="Send message"
                  >
                    <Send className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>
            <p className="px-2 pb-1 text-center text-[10px] leading-relaxed text-[var(--metis-hint)] sm:text-left">
              <span className="block sm:inline">Metis can make mistakes. Verify important actions on your device.</span>
              <span className="mt-0.5 block text-[var(--metis-fg-dim)] sm:mt-0 sm:ml-2 sm:inline">
                Enter to send · Shift+Enter for a new line · Ctrl/⌘+K focus · Ctrl/⌘+, settings
              </span>
            </p>
          </form>
        </div>
      </main>

      {/* Right inspector — premium “control panel” feel */}
      <aside
        className={`hidden shrink-0 border-l border-[var(--metis-border)] bg-[var(--metis-bg-sidebar)] md:flex ${inspectorOpen ? inspectorWidth : 'w-0'} transition-[width] duration-200`}
        aria-label="Info panel"
      >
        {inspectorOpen && (
          <div className="flex min-w-0 flex-1 flex-col p-3">
            <div className="flex items-center gap-2 px-1 py-1">
              <Info className="h-4 w-4 text-[var(--metis-fg-dim)]" />
              <div className="text-sm font-semibold text-[var(--metis-foreground)]">Session</div>
            </div>
            <div className="mt-2 rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
              <div className="text-xs text-[var(--metis-fg-dim)]">Agent</div>
              <div className="mt-1 text-sm text-[var(--metis-foreground)]">Manager</div>
              <div className="mt-3 text-xs text-[var(--metis-fg-dim)]">Shortcuts</div>
              <div className="mt-1 space-y-1 text-xs text-[var(--metis-fg-muted)]">
                <div className="flex items-center justify-between gap-3">
                  <span>Focus composer</span>
                  <span className="text-[var(--metis-code-fg)]">Ctrl/⌘ K</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span>Settings</span>
                  <span className="text-[var(--metis-code-fg)]">Ctrl/⌘ ,</span>
                </div>
              </div>
            </div>
            <div className="mt-3 rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3">
              <div className="text-xs text-[var(--metis-fg-dim)]">Status</div>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-xs text-[var(--metis-fg-muted)]">Bridge</span>
                <span className="text-xs text-emerald-400">Connected</span>
              </div>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-xs text-[var(--metis-fg-muted)]">Streaming</span>
                <span className="text-xs text-[var(--metis-fg)]">{thinking ? 'Yes' : 'Idle'}</span>
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
