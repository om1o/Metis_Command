'use client';

import { useState, useEffect, useRef, FormEvent, KeyboardEvent } from 'react';
import {
  Send,
  Terminal,
  Brain,
  Server,
  Activity,
  Settings,
  LogOut,
  Command,
  Sparkles,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { createLocalClient } from '@/lib/metis-client';

const SUGGESTIONS = [
  'Summarize my open threads',
  'Check local model status',
  'What can the manager agent do?',
];

export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<
    { role: string; content: string; reasoning?: string }[]
  >([]);
  const [thinking, setThinking] = useState(false);
  const [client, setClient] = useState<ReturnType<typeof createLocalClient> | null>(null);
  const [tokenInput, setTokenInput] = useState('');

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking]);

  const handleConnect = () => {
    if (tokenInput.trim()) {
      setClient(createLocalClient(tokenInput.trim()));
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

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !client) return;

    const userText = input.trim();
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: userText }]);
    setThinking(true);

    let assistantContent = '';
    let reasoningContent = '';

    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', reasoning: '' },
    ]);

    try {
      const stream = client.chat('manager', userText, 'desktop-session');

      for await (const ev of stream) {
        if (ev.type === 'token' && ev.delta) {
          assistantContent += ev.delta;
        } else if (ev.type === 'reasoning' && ev.delta) {
          reasoningContent += ev.delta;
        }

        setMessages((prev) => {
          const newMsg = [...prev];
          newMsg[newMsg.length - 1] = {
            role: 'assistant',
            content: assistantContent,
            reasoning: reasoningContent,
          };
          return newMsg;
        });
      }
    } catch (err) {
      setMessages((prev) => {
        const newMsg = [...prev];
        newMsg[newMsg.length - 1] = {
          role: 'assistant',
          content: assistantContent + `\n\n[Error: ${String(err)}]`,
          reasoning: reasoningContent,
        };
        return newMsg;
      });
    } finally {
      setThinking(false);
    }
  };

  if (!client) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center px-4 py-10">
        <motion.div
          className="glass-panel relative w-full max-w-md overflow-hidden rounded-2xl p-0.5"
          initial={{ opacity: 0, y: 16, filter: 'blur(2px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <div
            className="rounded-[0.9rem] bg-zinc-950/90 px-8 pb-8 pt-10"
            style={{
              backgroundImage: `radial-gradient(80% 60% at 50% 0%, var(--accent-muted) 0%, transparent 60%)`,
            }}
          >
            <div className="mb-8 flex flex-col items-center text-center">
              <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.04] shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
                <Command className="h-7 w-7 text-violet-300/90" strokeWidth={1.5} />
              </div>
              <h1 className="text-2xl font-light tracking-tight text-white/95">
                Metis Command
              </h1>
              <p className="mt-2 text-pretty text-sm leading-relaxed text-zinc-400">
                Local-first control plane. Connect with your{' '}
                <code className="rounded bg-white/5 px-1.5 py-0.5 text-[0.8rem] text-violet-200/90">
                  local_auth.token
                </code>{' '}
                to use the API bridge.
              </p>
            </div>
            <label className="block text-left">
              <span className="mb-2 block text-xs font-medium uppercase tracking-widest text-zinc-500">
                Token
              </span>
              <input
                type="password"
                autoComplete="off"
                placeholder="Paste token"
                className="w-full rounded-xl border border-white/10 bg-black/50 px-4 py-3 text-sm text-zinc-100 shadow-inner outline-none transition-[border,box-shadow] placeholder:text-zinc-600 focus:border-violet-500/40 focus:ring-2 focus:ring-violet-500/25"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                onKeyDown={onConnectKeyDown}
              />
            </label>
            <button
              type="button"
              onClick={handleConnect}
              className="mt-5 w-full rounded-xl border border-violet-500/25 bg-violet-600/90 py-3 text-sm font-medium text-white shadow-lg shadow-violet-950/40 transition-[background,box-shadow,transform] hover:bg-violet-600 active:scale-[0.99]"
            >
              Connect
            </button>
            <p className="mt-6 text-center text-[11px] leading-relaxed text-zinc-500">
              Runs on your hardware. No account required for the local stack.
            </p>
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl gap-5 p-4 md:gap-6 md:p-8">
      {/* Context rail */}
      <aside className="hidden w-[220px] shrink-0 flex-col gap-3 md:flex lg:w-56">
        <div className="glass-panel flex flex-col rounded-2xl p-5">
          <div className="relative mb-4 flex items-center justify-center">
            <div
              className={`pointer-events-none absolute inset-0 rounded-2xl blur-2xl transition-all duration-700 ${
                thinking
                  ? 'bg-violet-500/30 scale-110'
                  : 'bg-emerald-500/10 scale-100'
              }`}
            />
            <div
              className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 glass-tight"
              aria-hidden
            >
              <Brain
                className={`h-7 w-7 ${
                  thinking
                    ? 'text-violet-300 shimmer-sheen'
                    : 'text-emerald-300/90'
                }`}
                strokeWidth={1.5}
              />
            </div>
          </div>
          <p className="text-center text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
            Metis
          </p>
          <p
            className="mt-1 text-center text-xs text-zinc-300"
            title="Orchestrator state"
          >
            {thinking ? 'Generating…' : 'Ready'}
          </p>
        </div>

        <div className="glass-panel flex flex-1 flex-col gap-0 rounded-2xl p-4">
          <h3 className="mb-3 text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
            Vitals
          </h3>
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-lg border border-white/5 bg-white/[0.03] p-1.5">
                <Server className="h-3.5 w-3.5 text-emerald-400" />
              </div>
              <div>
                <div className="text-xs text-zinc-200">API bridge</div>
                <div className="text-[10px] text-emerald-400/90">Connected</div>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <div className="mt-0.5 rounded-lg border border-white/5 bg-white/[0.03] p-1.5">
                <Activity className="h-3.5 w-3.5 text-violet-300/80" />
              </div>
              <div>
                <div className="text-xs text-zinc-200">Session</div>
                <div className="text-[10px] text-zinc-500">Desktop</div>
              </div>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden glass-panel rounded-2xl md:rounded-3xl">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] bg-black/20 px-4 md:h-14 md:px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="hidden rounded-md border border-white/10 bg-white/[0.04] p-1.5 sm:block">
              <Terminal className="h-3.5 w-3.5 text-zinc-400" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-zinc-100">
                  Manager
                </span>
                <span
                  className="hidden h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(52,211,153,0.5)] sm:inline"
                  title="Session active"
                />
              </div>
              <p className="truncate text-[10px] text-zinc-500 sm:text-xs">
                General context · local swarm
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={handleDisconnect}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/0 px-2 text-zinc-500 transition-colors hover:border-white/10 hover:bg-white/5 hover:text-zinc-200"
              title="Disconnect"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span className="hidden text-xs sm:inline">Disconnect</span>
            </button>
            <button
              type="button"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-500 transition-colors hover:bg-white/5 hover:text-zinc-200"
              title="Settings (soon)"
            >
              <Settings className="h-3.5 w-3.5" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="flex min-h-full flex-col gap-4 px-4 py-5 md:px-6 md:py-6">
            {messages.length === 0 && (
              <div className="m-auto max-w-md text-center">
                <div className="mb-4 inline-flex rounded-2xl border border-white/10 bg-violet-500/10 p-3">
                  <Sparkles
                    className="h-8 w-8 text-violet-200/50"
                    strokeWidth={1.25}
                  />
                </div>
                <h2 className="text-lg font-light tracking-tight text-zinc-200">
                  What do you want to do?
                </h2>
                <p className="mt-1 text-pretty text-sm text-zinc-500">
                  Ask the manager, or start from a suggestion.
                </p>
                <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-center">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => {
                        setInput(s);
                        inputRef.current?.focus();
                      }}
                      className="rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-2 text-left text-xs text-zinc-300 transition-colors hover:border-violet-500/30 hover:bg-violet-500/10 hover:text-zinc-100"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, idx) => {
              const isUser = msg.role === 'user';
              const isLast = idx === messages.length - 1;
              const streaming = thinking && isLast && !isUser;
              return (
                <div
                  key={idx}
                  className={`flex w-full max-w-3xl flex-col gap-1.5 ${
                    isUser ? 'ml-auto items-end' : 'mr-auto items-start'
                  }`}
                >
                  <span className="px-1 text-[10px] font-medium uppercase tracking-widest text-zinc-500">
                    {isUser ? 'You' : 'Metis'}
                  </span>
                  <div
                    className={`w-full rounded-2xl border px-4 py-3 text-sm leading-relaxed shadow-sm ${
                      isUser
                        ? 'max-w-[min(100%,40rem)] rounded-tr-md border-violet-500/15 bg-violet-600/15 text-zinc-100'
                        : 'max-w-[min(100%,48rem)] rounded-tl-md border-white/[0.07] bg-zinc-950/70 text-zinc-100 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
                    } ${streaming ? 'shimmer-sheen' : ''}`}
                  >
                    {msg.reasoning && (
                      <div className="mb-3 rounded-lg border border-white/[0.06] bg-black/35 px-3 py-2">
                        <div className="mb-1.5 text-[10px] font-medium uppercase tracking-widest text-zinc-500">
                          Thinking
                        </div>
                        <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-zinc-400">
                          {msg.reasoning}
                        </pre>
                      </div>
                    )}

                    {isUser ? (
                      <p className="whitespace-pre-wrap text-pretty">{msg.content}</p>
                    ) : (
                      <p className="whitespace-pre-wrap text-pretty">
                        {msg.content}
                        {streaming && !msg.content && (
                          <span className="ml-0.5 inline-block h-1 w-1 animate-pulse rounded-full bg-violet-400 align-middle" />
                        )}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={bottomRef} className="h-1 shrink-0" />
          </div>
        </div>

        <footer className="shrink-0 border-t border-white/[0.06] bg-black/35 p-3 md:p-4">
          <form onSubmit={handleSubmit} className="mx-auto max-w-3xl">
            <div className="flex gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Message the manager…"
                className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-zinc-100 shadow-inner outline-none transition-[border,box-shadow] placeholder:text-zinc-600 focus:border-violet-500/35 focus:ring-2 focus:ring-violet-500/20"
                disabled={thinking}
                autoComplete="off"
                aria-label="Message input"
              />
              <button
                type="submit"
                disabled={!input.trim() || thinking}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-violet-500/20 bg-violet-600/85 px-4 py-3 text-sm font-medium text-white shadow-md shadow-violet-950/30 transition-[background,transform,opacity] hover:bg-violet-600 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Send className="h-4 w-4" />
                <span className="hidden sm:inline">Send</span>
              </button>
            </div>
          </form>
        </footer>
      </div>
    </div>
  );
}
