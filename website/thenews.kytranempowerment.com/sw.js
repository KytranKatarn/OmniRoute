/* ==========================================================================
   Kytran News — Service Worker
   Cache shell for offline use, network-first for API calls
   ========================================================================== */

var CACHE_NAME = 'kytran-news-v1';
var API_CACHE_NAME = 'kytran-news-api-v1';
var API_CACHE_MAX_AGE = 5 * 60 * 1000; /* 5 minutes */

var SHELL_ASSETS = [
    '/',
    '/index.html',
    '/favicon.svg',
    '/manifest.json',
    '/css/base.css',
    '/css/components.css',
    '/css/map.css',
    '/css/dashboard.css',
    '/css/responsive.css',
    '/css/reduced-motion.css',
    '/js/config.js',
    '/js/data/fetcher.js',
    '/js/data/scheduler.js',
    '/js/data/transforms.js',
    '/js/map.js',
    '/js/layers/conflicts.js',
    '/js/layers/disasters.js',
    '/js/layers/weather.js',
    '/js/layers/cyber.js',
    '/js/layers/outages.js',
    '/js/layers/sanctions.js',
    '/js/layers/military.js',
    '/js/layers/flights.js',
    '/js/layers/airquality.js',
    '/js/layers/disease.js',
    '/js/layers/ships.js',
    '/js/layers/spaceweather.js',
    '/js/layers/radiation.js',
    '/js/layers/protests.js',
    '/js/layers/internet.js',
    '/js/layers/terrorism.js',
    '/js/layers/economic.js',
    '/js/layers/social.js',
    '/js/panels/ticker.js',
    '/js/panels/defcon.js',
    '/js/panels/detail.js',
    '/js/panels/share.js',
    '/js/panels/search.js',
    '/js/panels/legend.js',
    '/js/panels/timeline.js',
    '/js/panels/regions.js',
    '/js/panels/shortcuts.js',
    '/js/effects.js',
    '/js/app.js'
];

/* -- Install: cache shell assets ----------------------------------------- */
self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.addAll(SHELL_ASSETS);
        }).then(function () {
            return self.skipWaiting();
        })
    );
});

/* -- Activate: clean old caches ------------------------------------------ */
self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(
                keys.filter(function (key) {
                    return key !== CACHE_NAME && key !== API_CACHE_NAME;
                }).map(function (key) {
                    return caches.delete(key);
                })
            );
        }).then(function () {
            return self.clients.claim();
        })
    );
});

/* -- Fetch: cache-first for shell, network-first for API ----------------- */
self.addEventListener('fetch', function (event) {
    var url = new URL(event.request.url);

    /* Skip non-GET requests */
    if (event.request.method !== 'GET') return;

    /* Skip cross-origin library requests (CDN) — let browser handle */
    if (url.origin !== self.location.origin) return;

    /* API calls: network-first with short-lived cache */
    if (url.pathname.indexOf('/api') === 0) {
        event.respondWith(
            fetch(event.request).then(function (response) {
                var clone = response.clone();
                caches.open(API_CACHE_NAME).then(function (cache) {
                    cache.put(event.request, clone);
                });
                return response;
            }).catch(function () {
                return caches.match(event.request).then(function (cached) {
                    if (cached) {
                        var dateHeader = cached.headers.get('date');
                        if (dateHeader) {
                            var age = Date.now() - new Date(dateHeader).getTime();
                            if (age > API_CACHE_MAX_AGE) {
                                return new Response('{"error":"offline","cached":true}', {
                                    status: 503,
                                    headers: { 'Content-Type': 'application/json' }
                                });
                            }
                        }
                        return cached;
                    }
                    return new Response('{"error":"offline"}', {
                        status: 503,
                        headers: { 'Content-Type': 'application/json' }
                    });
                });
            })
        );
        return;
    }

    /* Static assets: cache-first */
    event.respondWith(
        caches.match(event.request).then(function (cached) {
            return cached || fetch(event.request).then(function (response) {
                var clone = response.clone();
                caches.open(CACHE_NAME).then(function (cache) {
                    cache.put(event.request, clone);
                });
                return response;
            });
        })
    );
});
