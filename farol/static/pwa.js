"use strict";
if (window.isSecureContext && 'serviceWorker' in navigator) navigator.serviceWorker.register('/service-worker.js').catch(() => {});
let installEvent;
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault(); installEvent=event;
  document.getElementById('install-app')?.classList.remove('hidden');
});
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('install-app')?.addEventListener('click', async () => {
    if (!installEvent) return;
    await installEvent.prompt(); await installEvent.userChoice; installEvent=null;
    document.getElementById('install-app').classList.add('hidden');
  });
});
