// Nibras GP PWA service worker.
// Deliberately do not cache private chats, files, tokens, or API responses.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
