// Metis Service Worker — minimal install scaffold so the browser
// considers this site "installable" (manifest + a registered SW are
// the two requirements). We deliberately don't aggressively cache app
// shell yet — Next.js dev mode regenerates chunk URLs on every build,
// which would make a stale cache worse than no cache. The hook is
// here for future offline support (Phase 18).

const CACHE = 'metis-v1';

self.addEventListener('install', (event) => {
  // Take over immediately so updates apply on the next page load.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Pass-through for now. Future: cache /metis-mark.png + /manifest +
  // /_next/static/*.css under cache-first; everything else network-first.
  return;
});
