/**
 * Media Hub Service Worker
 * Enables PWA functionality with offline caching
 */

// Bump these version tags on any precache list change so browsers with an
// older SW pick up the fresh files (old caches are purged in the activate
// handler below).
const CACHE_NAME = 'media-hub-v3';
const STATIC_CACHE = 'media-hub-static-v3';
const DYNAMIC_CACHE = 'media-hub-dynamic-v3';
const IMAGE_CACHE = 'media-hub-images-v3';

// Static assets to cache immediately. cache.addAll() fails the ENTIRE install
// if any single entry 404s — so every path here must exist in both platform
// and standalone builds. archie-design-system.css was removed on 2026-04-19
// after it silently broke SW install on the Media Hub standalone.
// v3: the two icon paths below (media-hub-192/512.png) never existed on disk
// (actual files are kytran-ram-*.png) — this was silently failing SW install
// on every platform since the icons were added. Cache version bumped so
// already-installed clients pick up a SW that can actually install.
const STATIC_ASSETS = [
    '/tools/media-hub/',
    '/static/js/media-hub.js',
    '/static/css/media-hub.css',
    '/static/manifest.json',
    '/static/icons/kytran-ram-192.png',
    '/static/icons/kytran-ram-512.png'
];

// API routes to cache with network-first strategy
const API_ROUTES = [
    '/tools/media-hub/api/library/stats',
    '/tools/media-hub/api/status'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[Media Hub SW] Installing...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[Media Hub SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
            .catch((error) => {
                console.error('[Media Hub SW] Install failed:', error);
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[Media Hub SW] Activating...');
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames
                        .filter((name) => {
                            return name.startsWith('media-hub-') &&
                                   name !== STATIC_CACHE &&
                                   name !== DYNAMIC_CACHE &&
                                   name !== IMAGE_CACHE;
                        })
                        .map((name) => {
                            console.log('[Media Hub SW] Deleting old cache:', name);
                            return caches.delete(name);
                        })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch event - serve from cache with network fallback
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Skip cross-origin requests (except images)
    if (url.origin !== location.origin && !isImageRequest(event.request)) {
        return;
    }

    // Handle different request types
    if (isImageRequest(event.request)) {
        event.respondWith(cacheFirstWithExpiry(event.request, IMAGE_CACHE, 7 * 24 * 60 * 60 * 1000)); // 7 days
    } else if (isAPIRequest(event.request)) {
        event.respondWith(networkFirstWithCache(event.request, DYNAMIC_CACHE));
    } else if (isStaticAsset(event.request)) {
        event.respondWith(cacheFirst(event.request, STATIC_CACHE));
    } else {
        event.respondWith(networkFirstWithCache(event.request, DYNAMIC_CACHE));
    }
});

// Check if request is for an image
function isImageRequest(request) {
    const url = new URL(request.url);
    return request.destination === 'image' ||
           url.pathname.match(/\.(jpg|jpeg|png|gif|webp|svg)$/i) ||
           url.hostname === 'image.tmdb.org';
}

// Check if request is for API
function isAPIRequest(request) {
    return request.url.includes('/api/');
}

// Check if request is for static asset
function isStaticAsset(request) {
    const url = new URL(request.url);
    return url.pathname.match(/\.(js|css|woff2?|ttf|eot)$/i) ||
           STATIC_ASSETS.some(asset => url.pathname.includes(asset));
}

// Cache-first strategy
async function cacheFirst(request, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);

    if (cached) {
        return cached;
    }

    try {
        const response = await fetch(request);
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        console.error('[Media Hub SW] Fetch failed:', error);
        return new Response('Offline', { status: 503 });
    }
}

// Cache-first with expiry for images
async function cacheFirstWithExpiry(request, cacheName, maxAge) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(request);

    if (cached) {
        const cachedDate = cached.headers.get('sw-cache-date');
        if (cachedDate) {
            const age = Date.now() - parseInt(cachedDate);
            if (age < maxAge) {
                return cached;
            }
        } else {
            return cached;
        }
    }

    try {
        const response = await fetch(request);
        if (response.ok) {
            // Clone response and add cache date header
            const headers = new Headers(response.headers);
            headers.set('sw-cache-date', Date.now().toString());
            const cachedResponse = new Response(await response.clone().blob(), {
                status: response.status,
                statusText: response.statusText,
                headers: headers
            });
            cache.put(request, cachedResponse);
        }
        return response;
    } catch (error) {
        if (cached) {
            return cached; // Return stale cache if network fails
        }
        return new Response('', { status: 503 });
    }
}

// Network-first with cache fallback
async function networkFirstWithCache(request, cacheName) {
    const cache = await caches.open(cacheName);

    try {
        const response = await fetch(request);
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        const cached = await cache.match(request);
        if (cached) {
            return cached;
        }

        // Return offline page for navigation requests
        if (request.mode === 'navigate') {
            return caches.match('/tools/media-hub');
        }

        return new Response(JSON.stringify({
            success: false,
            error: 'Offline',
            cached: false
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

// Handle background sync for requests made offline
self.addEventListener('sync', (event) => {
    console.log('[Media Hub SW] Background sync:', event.tag);
    if (event.tag === 'media-request') {
        event.waitUntil(syncMediaRequests());
    }
});

// Sync queued media requests
async function syncMediaRequests() {
    // Implementation for syncing offline requests
    console.log('[Media Hub SW] Syncing media requests...');
}

// Handle push notifications (for future use)
self.addEventListener('push', (event) => {
    if (!event.data) return;

    const data = event.data.json();
    const options = {
        body: data.body || 'New content available',
        icon: '/static/icons/kytran-ram-192.png',
        badge: '/static/icons/kytran-ram-72.png',
        vibrate: [100, 50, 100],
        data: {
            url: data.url || '/tools/media-hub'
        },
        actions: [
            { action: 'open', title: 'Open' },
            { action: 'dismiss', title: 'Dismiss' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(data.title || 'Media Hub', options)
    );
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'dismiss') return;

    const url = event.notification.data?.url || '/tools/media-hub';

    event.waitUntil(
        clients.matchAll({ type: 'window' })
            .then((windowClients) => {
                // Focus existing window if available
                for (const client of windowClients) {
                    if (client.url.includes('/tools/media-hub') && 'focus' in client) {
                        return client.focus();
                    }
                }
                // Open new window
                if (clients.openWindow) {
                    return clients.openWindow(url);
                }
            })
    );
});

console.log('[Media Hub SW] Service Worker loaded');
