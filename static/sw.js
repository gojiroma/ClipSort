const CACHE = 'plug-v1';
const OFFLINE_URLS = ['/', '/static/manifest.json', '/static/icon-192.png', '/static/icon-512.png'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE_URLS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
    e.waitUntil(caches.keys()
        .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
        .then(() => self.clients.claim()));
});

// ネットワーク優先。API と共有ページはキャッシュしない。失敗時のみキャッシュを返す。
self.addEventListener('fetch', e => {
    const req = e.request, url = new URL(req.url);
    if (req.method !== 'GET' || url.origin !== location.origin) return;
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/share/')) return;
    e.respondWith(fetch(req).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
        return res;
    }).catch(() => caches.match(req).then(r => r || caches.match('/'))));
});
