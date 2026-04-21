'use client';

import { useState, useEffect, useRef } from 'react';
import { Send, Terminal, Brain, Server, Shield, Sparkles, Activity } from 'lucide-react';
import { createLocalClient, StreamEvent } from '@/lib/metis-client';

export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<{role: string, content: string, reasoning?: string}[]>([]);
  const [thinking, setThinking] = useState(false);
  const [client, setClient] = useState<any>(null);
  const [tokenInput, setTokenInput] = useState('');
  
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Scroll to bottom whenever messages change
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, thinking]);

  const handleConnect = () => {
    if (tokenInput.trim()) {
      setClient(createLocalClient(tokenInput.trim()));
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !client) return;

    const userText = input.trim();
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userText }]);
    setThinking(true);

    let assistantContent = '';
    let reasoningContent = '';
    
    // Add empty assistant message skeleton
    setMessages(prev => [...prev, { role: 'assistant', content: '', reasoning: '' }]);

    try {
      // Hit the metis-client stream chat endpoint
      const stream = client.chat('manager', userText, 'desktop-session');
      
      for await (const ev of stream) {
        if (ev.type === 'token' && ev.delta) {
          assistantContent += ev.delta;
        } else if (ev.type === 'reasoning' && ev.delta) {
          reasoningContent += ev.delta;
        }
        
        // Update the last message in real-time
        setMessages(prev => {
          const newMsg = [...prev];
          newMsg[newMsg.length - 1] = {
            role: 'assistant',
            content: assistantContent,
            reasoning: reasoningContent
          };
          return newMsg;
        });
      }
    } catch (err) {
      setMessages(prev => {
        const newMsg = [...prev];
        newMsg[newMsg.length - 1] = {
          role: 'assistant',
          content: assistantContent + `\n\n[Error: ${err}]`,
          reasoning: reasoningContent
        };
        return newMsg;
      });
    } finally {
      setThinking(false);
    }
  };

  if (!client) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <div className="glass-panel p-8 rounded-2xl max-w-md w-full flex flex-col items-center animate-in fade-in slide-in-from-bottom-4 duration-1000">
          <div className="w-16 h-16 rounded-full bg-purple-500/20 flex items-center justify-center mb-6">
            <Shield className="text-purple-400 w-8 h-8" />
          </div>
          <h2 className="text-2xl font-light tracking-wide mb-2">Metis Command OS</h2>
          <p className="text-sm text-white/50 mb-8 text-center">
            Local zero-trust agentic environment. Enter your local_auth.token to connect via the API bridge.
          </p>
          <input 
            type="password"
            placeholder="Paste local_auth.token here"
            className="w-full bg-black/40 border border-white/10 rounded-lg px-4 py-3 mb-4 text-sm focus:outline-none focus:border-purple-500/50 transition-colors"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
          />
          <button 
            onClick={handleConnect}
            className="w-full bg-white/10 hover:bg-white/20 text-white rounded-lg px-4 py-3 text-sm font-medium transition-all"
          >
            Acknowledge & Connect
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full max-w-7xl mx-auto p-4 md:p-8 gap-6">
      
      {/* LEFT SIDEBAR: CONTEXT & STATS */}
      <div className="hidden md:flex flex-col w-64 shrink-0 gap-4">
        {/* Header Orb */}
        <div className="glass-panel rounded-2xl p-6 flex flex-col items-center">
          <div className="relative mb-4">
            <div className={`absolute inset-0 rounded-full blur-xl transition-all duration-1000 ${thinking ? 'bg-purple-500/50 scale-150' : 'bg-cyan-500/20 scale-100'}`}></div>
            <div className="relative w-16 h-16 rounded-full glass-panel flex items-center justify-center border-white/20">
              <Brain className={`w-8 h-8 ${thinking ? 'text-purple-400 animate-pulse' : 'text-cyan-400'}`} />
            </div>
          </div>
          <h1 className="text-sm tracking-[0.2em] font-medium text-white/90 mb-1 uppercase">Metis OS</h1>
          <p className="text-xs text-white/40">{thinking ? 'Processing...' : 'System Idle'}</p>
        </div>

        {/* System Vitals */}
        <div className="glass-panel rounded-2xl p-5 flex flex-col gap-4 flex-1">
          <h3 className="text-xs font-semibold tracking-wider text-white/30 uppercase mb-2">Vitals</h3>
          
          <div className="flex items-center gap-3">
            <Server className="w-4 h-4 text-green-400" />
            <div className="flex-1">
              <div className="text-xs text-white/70">Ollama Link</div>
              <div className="text-[10px] text-green-400/70">Connected (7ms)</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Activity className="w-4 h-4 text-cyan-400" />
            <div className="flex-1">
              <div className="text-xs text-white/70">Memory Sync</div>
              <div className="text-[10px] text-cyan-400/70">Cloud Synced</div>
            </div>
          </div>
        </div>
      </div>

      {/* MAIN THREAD CONTAINER */}
      <div className="flex flex-col flex-1 glass-panel rounded-3xl overflow-hidden relative">
        
        {/* Top bar */}
        <div className="h-14 border-b border-white/5 flex items-center justify-between px-6 bg-black/20">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-white/40" />
            <span className="text-xs font-medium text-white/60">Manager Agent // General Context</span>
          </div>
          <button className="text-white/40 hover:text-white transition-colors">
            <Settings className="w-4 h-4" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
          {messages.length === 0 && (
            <div className="m-auto text-center animate-in fade-in zoom-in duration-1000">
              <Sparkles className="w-12 h-12 text-white/10 mx-auto mb-4" />
              <h2 className="text-xl font-light text-white/80">How can I assist you today?</h2>
            </div>
          )}
          
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex flex-col max-w-[85%] ${msg.role === 'user' ? 'self-end items-end' : 'self-start items-start'}`}>
              <div className="flex items-center gap-2 mb-1 px-2">
                <span className="text-[10px] uppercase font-bold text-white/30 tracking-wider">
                  {msg.role === 'user' ? 'You' : 'Metis'}
                </span>
              </div>
              
              <div className={`px-5 py-4 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user' 
                  ? 'bg-white/10 text-white border border-white/5 rounded-tr-sm' 
                  : 'bg-black/40 text-white/90 border border-white/5 rounded-tl-sm shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]'
              }`}>
                {/* Rendering Reasoning Block if present */}
                {msg.reasoning && (
                  <div className="mb-3 p-3 bg-white/5 rounded-lg border border-white/5 text-xs text-white/50 font-mono">
                     💭 {msg.reasoning}
                  </div>
                )}
                
                {msg.content || (msg.role === 'assistant' && !msg.reasoning ? <span className="animate-pulse">...</span> : '')}
              </div>
            </div>
          ))}
          <div ref={bottomRef} className="h-1" />
        </div>

        {/* Input Bar */}
        <div className="p-4 bg-black/40 border-t border-white/5">
          <form onSubmit={handleSubmit} className="flex gap-2 relative">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Command the swarm..."
              className="flex-1 bg-white/5 hover:bg-white/10 transition-colors border border-white/10 focus:border-white/20 rounded-xl px-5 py-4 text-sm text-white placeholder:text-white/30 outline-none"
              disabled={thinking}
            />
            <button
              type="submit"
              disabled={!input.trim() || thinking}
              className="absolute right-2 top-2 bottom-2 aspect-square rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-50 disabled:hover:bg-white/10 transition-all flex items-center justify-center border border-white/5 shadow-lg"
            >
              <Send className="w-4 h-4 text-white" />
            </button>
          </form>
        </div>

      </div>

    </div>
  );
}
