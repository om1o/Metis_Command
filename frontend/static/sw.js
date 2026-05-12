/**
 * Metis Command Service Worker — Phase 18 (Mobile PWA)
 * Provides offline shell caching + background sync groundwork.
 */

const CACHE_VERSION = 'metis-v1';
const STATIC_ASSETS = [
  '/app',
  '/login',
  '/static/js/api.js',
  '/static/js/wordmark.js',
  '/static/polish/global-polish.v2.css',
  '/static/polish/global-polish.v2.js',
  '/static/styles/wordmark.css',
  '/static/assets/favicon.svg',
  '/static/assets/metis-logomark-transparent.png',
  '/static/assets/metis-wordmark.svg',
];

// ── Install: pre-cache static shell ─────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) =>
      cache.addAll(STATIC_ASSETS).catch(() => {
        // Some assets may not exist yet — install anyway
      })
    ).then(() => self.skipWaiting())
  );
});

// ── Activate: clean up old caches ────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_VERSION)
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first for API, cache-first for static assets ──────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  // API + SSE routes: always go to network (never cache)
  if (
    url.pathname.startsWith('/chat') ||
    url.pathname.startsWith('/auth/') ||
    url.pathname.startsWith('/sessions') ||
    url.pathname.startsWith('/notifications') ||
    url.pathname.startsWith('/analytics') ||
    url.pathname.startsWith('/webhooks') ||
    url.pathname.startsWith('/agents') ||
    url.pathname.startsWith('/brains') ||
    url.pathname.startsWith('/wallet') ||
    url.pathname.startsWith('/schedules') ||
    url.pathname.startsWith('/inbox') ||
    url.pathname.startsWith('/relationships') ||
    url.pathname.startsWith('/marketplace') ||
    url.pathname.startsWith('/models') ||
    url.pathname.startsWith('/ollama') ||
    url.pathname.startsWith('/status') ||
    url.pathname.startsWith('/health') ||
    url.pathname.startsWith('/version') ||
    url.pathname.startsWith('/generate') ||
    url.pathname.startsWith('/skills') ||
    url.pathname.startsWith('/forge') ||
    url.pathname.startsWith('/missions') ||
    url.pathname.startsWith('/search') ||
    url.pathname.startsWith('/files') ||
    url.pathname.startsWith('/usage') ||
    url.pathname.startsWith('/tiers') ||
    url.pathname.startsWith('/manager') ||
    url.pathname.startsWith('/memory')
  ) {
    return; // let the browser handle API calls naturally
  }

  // Static assets: cache-first, fall back to network
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // HTML pages: network-first, fall back to cached shell
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match('/app')))
  );
});

// ── Push notifications ────────────────────────────────────────────────────────
self.addEventListener('push', (event) => {
  if (!event.data) return;
  let data;
  try { data = event.data.json(); } catch { data = { title: 'Metis', body: event.data.text() }; }

  event.waitUntil(
    self.registration.showNotification(data.title || 'Metis Command', {
      body: data.body || '',
      icon: '/static/assets/metis-logomark-transparent.png',
      badge: '/static/assets/favicon.svg',
      tag: data.tag || 'metis-notification',
      renotify: true,
      data: { url: data.url || '/app' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = event.notification.data?.url || '/app';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});
