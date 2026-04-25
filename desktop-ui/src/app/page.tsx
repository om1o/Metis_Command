'use client';

import { useState, useEffect, useRef, FormEvent, KeyboardEvent } from 'react';
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
} from 'lucide-react';
import { createLocalClient } from '@/lib/metis-client';

const SUGGESTIONS: { t: string; s: string }[] = [
  { t: 'Get started', s: 'What can the manager agent do on my machine?' },
  { t: 'Status', s: 'Check local model and bridge status' },
  { t: 'Summarize', s: 'Summarize my open thread context' },
  { t: 'Swarm', s: 'How does the multi-agent roster work?' },
];

type MetisTheme = 'dark' | 'light';

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

  const handleConnect = () => {
    if (tokenInput.trim()) {
      setClient(createLocalClient(tokenInput.trim()));
    }
  };

  const handleNewChat = () => {
    setMessages([]);
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

  if (!client) {
    return (
      <div className="metis-app-bg metis-hero-ambient flex min-h-full flex-col items-center justify-center px-4 py-12 text-[var(--metis-fg)]">
        <div className="w-full max-w-[400px] rounded-2xl border border-[var(--metis-border)] bg-[var(--metis-elevated-2)] p-8 shadow-2xl backdrop-blur-sm">
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
            type="button"
            onClick={handleConnect}
            className="w-full rounded-xl py-2.5 text-sm font-medium transition hover:opacity-90"
            style={{ background: 'var(--metis-continue-bg)', color: 'var(--metis-continue-fg)' }}
          >
            Continue
          </button>
          <p className="mt-4 text-center text-xs text-[var(--metis-fg-dim)]">Runs on your device · local-first</p>
        </div>
      </div>
    );
  }

  return (
    <div className="metis-app-bg flex h-full w-full min-h-0 text-[var(--metis-fg)]">
      {/* Slim sidebar — chat-product pattern */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-[var(--metis-border)] bg-[var(--metis-bg-sidebar)]">
        <div className="p-2">
          <div className="flex items-center gap-2 rounded-lg px-2 py-1.5">
            <Image
              src="/metis-mark.png"
              width={28}
              height={28}
              alt=""
              className="h-7 w-7 rounded-md object-contain"
              unoptimized
            />
            <span className="truncate text-sm font-semibold tracking-tight">Metis Command</span>
          </div>
          <button
            type="button"
            onClick={handleNewChat}
            className="mt-2 flex w-full items-center gap-2 rounded-xl border border-[var(--metis-border)] bg-transparent px-3 py-2.5 text-left text-sm text-[var(--metis-fg)] transition hover:bg-[var(--metis-hover-surface)]"
          >
            <SquarePen className="h-4 w-4 shrink-0" />
            New chat
          </button>
        </div>
        <div className="px-2 pt-3">
          <p className="mb-1.5 px-2 text-[10px] font-medium uppercase tracking-widest text-[var(--metis-chats-label)]">
            Chats
          </p>
          <div className="flex cursor-default items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm text-[var(--metis-chats-item)]">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
            <span className="truncate">This session</span>
          </div>
        </div>
        <div className="min-h-0 flex-1" />
        <div className="border-t border-[var(--metis-border)] p-2">
          <div className="mb-1 rounded-md px-2 py-1 text-xs text-[var(--metis-fg-dim)]">Session</div>
          <div className="text-xs text-violet-300/90">Manager · local swarm</div>
        </div>
        <div className="flex gap-1 border-t border-[var(--metis-border)] p-2">
          <button
            type="button"
            onClick={handleDisconnect}
            className="flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-sm text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
            title="Disconnect"
          >
            <LogOut className="h-4 w-4" />
            Log out
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
            className="rounded-lg p-2 text-[var(--metis-fg-muted)] transition hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]"
            title="Settings"
            aria-label="Settings"
          >
            <Settings className="h-4 w-4" />
          </button>
        </div>
      </aside>

      {/* Main chat column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center border-b border-[var(--metis-border)] bg-[var(--metis-header-bg)] px-4 backdrop-blur-md sm:h-14 sm:px-5">
          <div className="inline-flex min-w-0 max-w-full items-center gap-2 sm:max-w-md">
            <h2 className="sr-only">Current model</h2>
            <button
              type="button"
              className="group inline-flex h-8 max-w-full items-center gap-0.5 rounded-2xl border border-transparent pl-0 pr-1.5 text-sm text-[var(--metis-header-button-fg)] transition hover:bg-[var(--metis-hover-surface)]"
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
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[48rem] px-4 py-6 sm:px-6">
            {messages.length === 0 && (
              <div className="relative overflow-hidden rounded-3xl pt-2 text-center sm:pt-8">
                <div
                  className="pointer-events-none absolute left-1/2 top-0 h-64 w-[min(100%,40rem)] -translate-x-1/2 sm:h-72"
                  style={{ background: 'var(--metis-orb-hero)' }}
                  aria-hidden
                />
                <h2 className="relative text-balance text-3xl font-light tracking-[-0.02em] text-[var(--metis-hero-title)] sm:text-5xl sm:leading-[1.08]">
                  What can Metis do for you?
                </h2>
                <p className="relative mx-auto mt-4 max-w-md text-balance text-sm text-[var(--metis-hero-sub)] sm:text-lg sm:leading-relaxed">
                  Local control plane — ask the manager, or start from a prompt below
                </p>
                <div className="relative mx-auto mt-10 grid max-w-2xl gap-2.5 sm:grid-cols-2 sm:gap-3">
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
            )}

            <div className="flex flex-col gap-5 pb-4 pt-2">
              {messages.map((msg, idx) => {
                const isUser = msg.role === 'user';
                const isLast = idx === messages.length - 1;
                const streaming = thinking && isLast && !isUser;
                if (isUser) {
                  return (
                    <div key={idx} className="flex flex-row justify-end pl-4 sm:pl-12">
                      <div
                        className="max-w-[min(100%,36rem)] rounded-3xl border border-[var(--metis-bubble-user-border)] bg-[var(--metis-bubble-user)] px-4 py-2.5 text-[15px] leading-7 text-[var(--metis-bubble-fg)]"
                        style={{ wordBreak: 'break-word' }}
                      >
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      </div>
                    </div>
                  );
                }
                return (
                  <div key={idx} className="group flex gap-2 sm:gap-3">
                    <div className="shrink-0 select-none">
                      <Image
                        src="/metis-mark.png"
                        width={32}
                        height={32}
                        className="mt-0.5 h-8 w-8 rounded-md object-contain"
                        alt="Metis"
                        unoptimized
                      />
                    </div>
                    <div className="min-w-0 flex-1 pl-0.5 text-[15px] leading-7 text-[var(--metis-bubble-fg)]">
                      <div className="mb-1.5 text-xs font-medium text-[var(--metis-name-label)]">Metis</div>
                      {msg.reasoning && (
                        <div
                          className="mb-3 rounded-lg border border-[var(--metis-border)] px-3 py-2"
                          style={{ background: 'var(--metis-reasoning-bg)' }}
                        >
                          <div className="mb-1 text-xs font-medium text-[var(--metis-fg-dim)]">Reasoning</div>
                          <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-[var(--metis-reasoning-code)]">
                            {msg.reasoning}
                          </pre>
                        </div>
                      )}
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
                  </div>
                );
              })}
            </div>
            <div ref={bottomRef} className="h-2" />
          </div>
        </div>

        {/* Rounded composer bar (common AI chat pattern) */}
        <div className="shrink-0 border-t border-[var(--metis-border)] bg-[var(--metis-bg)] p-3 sm:p-4">
          <form
            onSubmit={handleSubmit}
            className="metis-composer mx-auto w-full max-w-3xl rounded-3xl border border-[var(--metis-composer-border)] p-1.5 pl-2 transition-[box-shadow,border-color] duration-200 sm:pl-3"
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
                  className="rounded-lg p-2 opacity-60"
                  style={{ color: 'var(--metis-composer-icon)' }}
                  title="Attach (coming soon)"
                  tabIndex={-1}
                >
                  <Paperclip className="h-5 w-5" />
                </button>
                <button
                  type="button"
                  disabled
                  className="rounded-lg p-2 opacity-60"
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
                className="max-h-[200px] min-h-12 flex-1 resize-none bg-transparent py-3 text-sm text-[var(--metis-foreground)] placeholder:text-[var(--metis-fg-dim)] outline-none"
                aria-label="Message"
                autoComplete="off"
              />
              <div className="shrink-0 p-0.5 pb-0.5">
                <button
                  type="submit"
                  disabled={!input.trim() || thinking}
                  className="flex h-8 w-8 items-center justify-center rounded-full text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-35 sm:h-9 sm:w-9"
                  style={{ background: 'var(--metis-accent)' }}
                  title="Send"
                >
                  <Send className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <p className="px-2 pb-1 text-center text-[10px] text-[var(--metis-hint)] sm:text-left">
              Metis can make mistakes. Verify important actions on your device.
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
