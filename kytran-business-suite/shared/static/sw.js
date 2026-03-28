/* KBS Service Worker — offline caching for static assets. */

const CACHE_NAME = "kbs-v1";
const STATIC_ASSETS = [
    "/static/lcars.css",
    "/static/manifest.json",
];

/* Install — pre-cache critical static assets */
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

/* Activate — clean old caches */
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

/* Fetch — cache-first for static, network-first for everything else */
self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    /* Cache-first for static assets */
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(event.request).then((cached) => {
                if (cached) return cached;
                return fetch(event.request).then((resp) => {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    return resp;
                });
            })
        );
        return;
    }

    /* Network-first for everything else */
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
