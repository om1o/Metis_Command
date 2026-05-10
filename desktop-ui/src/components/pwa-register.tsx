'use client';

import { useEffect } from 'react';

/**
 * Registers the service worker once on mount and stashes the
 * `beforeinstallprompt` event globally so the InstallButton can fire
 * it later. Designed to be a no-op when the page isn't served over
 * https/localhost (where SW registration fails) and on browsers that
 * don't fire `beforeinstallprompt` (Safari).
 */
export default function PwaRegister() {
  useEffect(() => {
    // Service worker — registered as soon as the document is ready.
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
    const onLoad = () => {
      navigator.serviceWorker
        .register('/sw.js', { scope: '/' })
        .catch((err) => {
          // Localhost http or private mode → silent no-op; PWA buttons
          // simply won't appear, the rest of the app works.
          console.warn('[metis] SW registration failed:', err);
        });
    };
    if (document.readyState === 'complete') onLoad();
    else window.addEventListener('load', onLoad, { once: true });

    // Capture the install prompt for the InstallButton component to
    // fire later. The browser only fires this once per session, and
    // only when it's decided the page is installable.
    const onBefore = (e: Event) => {
      e.preventDefault();
      // Non-standard window property; Chromium-only beforeinstallprompt event.
      (window as { __metisInstallPrompt?: Event }).__metisInstallPrompt = e;
      window.dispatchEvent(new Event('metis:install-available'));
    };
    window.addEventListener('beforeinstallprompt', onBefore);

    const onInstalled = () => {
      (window as { __metisInstallPrompt?: Event | null }).__metisInstallPrompt = null;
      window.dispatchEvent(new Event('metis:install-completed'));
    };
    window.addEventListener('appinstalled', onInstalled);

    return () => {
      window.removeEventListener('beforeinstallprompt', onBefore);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  return null;
}
