// Nibras GP PWA service worker.
// Network-only navigation handling helps installation eligibility on some browsers.
// No requests, private conversations, files, or credentials are cached.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
    if (event.request.method === 'GET' && event.request.mode === 'navigate'
        && new URL(event.request.url).origin === self.location.origin) {
        event.respondWith(fetch(event.request));
    }
});
