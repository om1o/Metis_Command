'use client';

import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff } from 'lucide-react';

// Web Speech API types — TS doesn't ship them by default. We only need
// the surface we actually use, so this is intentionally narrow.
type SpeechResult = { isFinal: boolean; 0: { transcript: string } };
type SpeechResultList = { length: number; [i: number]: SpeechResult };
interface SpeechRecognitionEvent extends Event {
  resultIndex: number;
  results: SpeechResultList;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onstart: ((e: Event) => void) | null;
  onresult: ((e: SpeechRecognitionEvent) => void) | null;
  onerror: ((e: Event & { error?: string }) => void) | null;
  onend: ((e: Event) => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

interface Props {
  /** Append finalised transcript chunks to the composer */
  onAppend: (text: string) => void;
  /** Live preview while user is speaking (set to '' on stop) */
  onInterim?: (text: string) => void;
  disabled?: boolean;
}

/**
 * Microphone button using the Web Speech API. Renders only when the
 * browser can do speech-to-text on-device. No backend involved — the
 * browser sends audio to its own STT (Chrome → Google, Edge → MS, etc.).
 *
 * Click to start; click again to stop. Auto-stops on a network/permission
 * error and explains briefly. We append finalised chunks to the composer
 * (so partial dictation isn't lost on stop) and stream the in-progress
 * interim text to onInterim for live preview.
 */
export default function VoiceButton({ onAppend, onInterim, disabled }: Props) {
  const [supported, setSupported] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return !!(
      (window as unknown as { SpeechRecognition?: SpeechRecognitionCtor }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: SpeechRecognitionCtor }).webkitSpeechRecognition
    );
  });
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    return () => { try { recRef.current?.abort(); } catch {} };
  }, []);

  const start = () => {
    setError(null);
    const win = window as unknown as {
      SpeechRecognition?: SpeechRecognitionCtor;
      webkitSpeechRecognition?: SpeechRecognitionCtor;
    };
    const Ctor = win.SpeechRecognition || win.webkitSpeechRecognition;
    if (!Ctor) { setSupported(false); return; }
    try {
      const rec = new Ctor();
      rec.lang = navigator.language || 'en-US';
      rec.continuous = true;
      rec.interimResults = true;
      rec.onstart = () => setListening(true);
      rec.onresult = (e) => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          const chunk = r[0]?.transcript ?? '';
          if (r.isFinal) {
            // Append finalised text (with a leading space when needed)
            // so consecutive utterances flow naturally.
            onAppend(chunk);
          } else {
            interim += chunk;
          }
        }
        onInterim?.(interim);
      };
      rec.onerror = (e) => {
        const msg = (e as { error?: string }).error || 'voice input failed';
        setError(msg === 'not-allowed' ? 'Microphone permission denied' : msg);
        setListening(false);
      };
      rec.onend = () => {
        setListening(false);
        onInterim?.('');
      };
      recRef.current = rec;
      rec.start();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const stop = () => {
    try { recRef.current?.stop(); } catch {}
  };

  if (!supported) return null;

  return (
    <button
      type="button"
      onClick={() => (listening ? stop() : start())}
      disabled={disabled}
      title={
        error
          ? `Voice input: ${error}`
          : listening
          ? 'Stop listening'
          : 'Speak instead of typing'
      }
      aria-label={listening ? 'Stop voice input' : 'Start voice input'}
      className={`inline-flex h-9 w-9 items-center justify-center rounded-full border transition disabled:opacity-40 ${
        listening
          ? 'border-rose-500/40 bg-rose-500/10 text-rose-300'
          : 'border-[var(--metis-border)] bg-[var(--metis-bg)] text-[var(--metis-fg-muted)] hover:bg-[var(--metis-hover-surface)] hover:text-[var(--metis-fg)]'
      }`}
    >
      {listening ? (
        <span className="relative inline-flex">
          <Mic className="h-4 w-4" />
          <span className="absolute -right-0.5 -top-0.5 inline-flex h-1.5 w-1.5 rounded-full bg-rose-400 motion-safe:animate-pulse" />
        </span>
      ) : error ? (
        <MicOff className="h-4 w-4" />
      ) : (
        <Mic className="h-4 w-4" />
      )}
    </button>
  );
}
