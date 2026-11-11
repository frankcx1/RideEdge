"use strict";
const CACHE = 'rideedge-offline-v1';
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.add('/offline.html'))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('rideedge-offline-') && key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener('fetch', event => {
  // APIs, audio, and live recommendations are never cached by the service worker.
  // Leave other applications on the same Tailscale origin (such as /desk/) alone.
  const path = new URL(event.request.url).pathname;
  if (event.request.mode !== 'navigate' || !['/', '/awareness', '/demo'].includes(path)) return;
  event.respondWith(fetch(event.request).catch(() => caches.match('/offline.html')));
});
