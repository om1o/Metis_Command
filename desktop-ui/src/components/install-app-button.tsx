'use client';

import { useEffect, useState } from 'react';
import { Download, Check, Smartphone } from 'lucide-react';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

/**
 * Install Metis as a PWA. Shows itself only when the browser has
 * actually fired `beforeinstallprompt` — which means the page is
 * installable AND the user isn't already running the installed app.
 * On Safari and Firefox the event never fires; this component then
 * just renders nothing.
 */
export default function InstallAppButton() {
  // Lazy initializers read from window once at mount and avoid the
  // React 19 set-state-in-effect rule.
  const [available, setAvailable] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return !!(window as { __metisInstallPrompt?: unknown }).__metisInstallPrompt;
  });
  const [installed, setInstalled] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    return !!window.matchMedia?.('(display-mode: standalone)').matches;
  });

  useEffect(() => {
    const onAvail = () => setAvailable(true);
    const onDone = () => { setAvailable(false); setInstalled(true); };
    window.addEventListener('metis:install-available', onAvail);
    window.addEventListener('metis:install-completed', onDone);
    return () => {
      window.removeEventListener('metis:install-available', onAvail);
      window.removeEventListener('metis:install-completed', onDone);
    };
  }, []);

  const onClick = async () => {
    const evt = (window as { __metisInstallPrompt?: BeforeInstallPromptEvent | null }).__metisInstallPrompt;
    if (!evt) return;
    try {
      await evt.prompt();
      const choice = await evt.userChoice;
      if (choice.outcome === 'accepted') {
        setInstalled(true);
      }
    } catch {/* user dismissed */}
    finally {
      (window as { __metisInstallPrompt?: BeforeInstallPromptEvent | null }).__metisInstallPrompt = null;
      setAvailable(false);
    }
  };

  if (installed) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3 text-[12.5px] text-emerald-200">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15">
          <Check className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-medium">Metis is installed.</div>
          <div className="text-[11px] text-emerald-300/70">Open the standalone app from your launcher.</div>
        </div>
      </div>
    );
  }

  if (!available) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-[var(--metis-border)] bg-[var(--metis-elevated)] p-3 text-[12.5px] text-[var(--metis-fg-muted)]">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--metis-hover-surface)]">
          <Smartphone className="h-4 w-4 text-violet-400" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[var(--metis-fg)]">Install Metis as an app</div>
          <div className="text-[11px] text-[var(--metis-fg-dim)]">
            Your browser hasn&apos;t offered an install prompt yet. On Chromium browsers it shows up after a few visits.
            Safari/Firefox don&apos;t support this; use <em>Add to Home Screen</em> from the share menu instead.
          </div>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-center gap-3 rounded-xl border border-violet-500/40 bg-violet-500/10 p-3 text-left transition hover:bg-violet-500/15"
    >
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/20 text-violet-200">
        <Download className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-violet-100">Install Metis</div>
        <div className="text-[11px] text-violet-200/80">
          Adds Metis to your apps so it opens like a native window with no browser chrome.
        </div>
      </div>
    </button>
  );
}
