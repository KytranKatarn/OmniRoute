/**
 * Media Hub Module JavaScript
 * Enhanced with: Continue Watching, Collections, Quality Badges,
 * TMDB Integration, Download Controls, Statistics, Lazy Loading,
 * Keyboard Navigation, and Mobile Optimizations
 */

const API_BASE = '/tools/media-hub/api';
let currentTab = 'dashboard';
let moviesOffset = 0;
let showsOffset = 0;
let calendarWeekOffset = 0;
let searchTimeout = null;
let focusedIndex = -1;
let tmdbConfigured = false;
let primaryMediaServer = { type: 'plex', url: '', name: 'Plex' };
let availableMediaServers = [];

// ─────────────────────────────────────────────────────────────────────────────
// LOCAL STORAGE CACHE
// ─────────────────────────────────────────────────────────────────────────────

const CACHE_PREFIX = 'media-hub-cache-';
const CACHE_TTL = 60 * 60 * 1000; // 1 hour in milliseconds

function cacheSet(key, data) {
    try {
        const item = {
            data: data,
            timestamp: Date.now()
        };
        localStorage.setItem(CACHE_PREFIX + key, JSON.stringify(item));
    } catch (e) {
        console.warn('[Media Hub] Cache write failed:', e);
    }
}

function cacheGet(key, maxAge = CACHE_TTL) {
    try {
        const item = localStorage.getItem(CACHE_PREFIX + key);
        if (!item) return null;

        const parsed = JSON.parse(item);
        const age = Date.now() - parsed.timestamp;

        // Return data even if stale (for instant display), but include age
        return {
            data: parsed.data,
            age: age,
            isStale: age > maxAge
        };
    } catch (e) {
        return null;
    }
}

function cacheClear() {
    const keys = Object.keys(localStorage).filter(k => k.startsWith(CACHE_PREFIX));
    keys.forEach(k => localStorage.removeItem(k));
    console.log(`[Media Hub] Cleared ${keys.length} cached items`);
}

// ─────────────────────────────────────────────────────────────────────────────
// INITIALIZATION
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    lucide.createIcons();
    initTabs();
    initSearch();
    initFilterChips();
    initKeyboardNavigation();
    initLazyLoading();
    initTrendingTabs();
    checkTMDBStatus();
    loadPrimaryMediaServer();
    loadDashboard();
    loadSettings();
});

async function loadPrimaryMediaServer() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        const data = await response.json();

        if (data.services) {
            // Collect all available media servers
            availableMediaServers = [];
            for (const [type, svc] of Object.entries(data.services)) {
                if ((type === 'plex' || type === 'jellyfin') && svc.online && svc.is_enabled) {
                    const server = {
                        type: type,
                        url: svc.url,
                        name: svc.name,
                        is_primary: svc.is_primary
                    };
                    availableMediaServers.push(server);

                    // Set primary
                    if (svc.is_primary) {
                        primaryMediaServer = server;
                    }
                }
            }

            // Fallback if no primary set
            if (!primaryMediaServer.url && availableMediaServers.length > 0) {
                primaryMediaServer = availableMediaServers[0];
            }

            console.log(`[Media Hub] Available servers: ${availableMediaServers.map(s => s.name).join(', ')}`);
            console.log(`[Media Hub] Primary server: ${primaryMediaServer.name}`);
        }
    } catch (error) {
        console.error('[Media Hub] Failed to load primary server:', error);
    }
}

function initTrendingTabs() {
    document.querySelectorAll('.trending-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.trending-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            loadTrending(tab.dataset.type);
        });
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// KEYBOARD NAVIGATION
// ─────────────────────────────────────────────────────────────────────────────

function initKeyboardNavigation() {
    document.addEventListener('keydown', (e) => {
        // Focus search with /
        if (e.key === '/' && !e.target.matches('input, textarea')) {
            e.preventDefault();
            document.getElementById('globalSearch').focus();
        }

        // Close panels/modals with Escape
        if (e.key === 'Escape') {
            closeMediaPanel();
            closeServiceModal();
            closeSearchDropdown();
        }

        // Tab navigation with number keys
        if (e.altKey && e.key >= '1' && e.key <= '7') {
            e.preventDefault();
            const tabs = ['dashboard', 'movies', 'shows', 'collections', 'requests', 'calendar', 'stats'];
            const index = parseInt(e.key) - 1;
            if (tabs[index]) switchTab(tabs[index]);
        }

        // Grid navigation with arrow keys
        if (currentTab === 'movies' || currentTab === 'shows' || currentTab === 'collections') {
            handleGridNavigation(e);
        }
    });
}

function handleGridNavigation(e) {
    const grid = document.querySelector('.tab-panel.active .media-grid');
    if (!grid) return;

    const items = grid.querySelectorAll('.poster-card');
    if (items.length === 0) return;

    const cols = Math.floor(grid.offsetWidth / items[0].offsetWidth);

    if (e.key === 'ArrowRight') {
        e.preventDefault();
        focusedIndex = Math.min(focusedIndex + 1, items.length - 1);
    } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        focusedIndex = Math.max(focusedIndex - 1, 0);
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        focusedIndex = Math.min(focusedIndex + cols, items.length - 1);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        focusedIndex = Math.max(focusedIndex - cols, 0);
    } else if (e.key === 'Enter' && focusedIndex >= 0) {
        e.preventDefault();
        items[focusedIndex].click();
    }

    if (focusedIndex >= 0) {
        items.forEach((item, i) => item.classList.toggle('keyboard-focused', i === focusedIndex));
        items[focusedIndex].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// LAZY LOADING
// ─────────────────────────────────────────────────────────────────────────────

function initLazyLoading() {
    if ('IntersectionObserver' in window) {
        window.imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.classList.add('loaded');
                        observer.unobserve(img);
                    }
                }
            });
        }, { rootMargin: '50px' });
    }
}

function lazyLoadImage(img) {
    if (window.imageObserver) {
        window.imageObserver.observe(img);
    } else {
        // Fallback for older browsers
        img.src = img.dataset.src;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB NAVIGATION
// ─────────────────────────────────────────────────────────────────────────────

function initTabs() {
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });
}

function switchTab(tabId) {
    focusedIndex = -1; // Reset keyboard focus

    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    const targetTab = document.querySelector(`.nav-tab[data-tab="${tabId}"]`);
    if (targetTab) targetTab.classList.add('active');

    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const targetPanel = document.getElementById(`tab-${tabId}`);
    if (targetPanel) targetPanel.classList.add('active');

    currentTab = tabId;

    switch(tabId) {
        case 'movies':
            if (document.getElementById('moviesGrid')?.querySelector('.grid-loading')) {
                loadMovies();
            }
            break;
        case 'shows':
            if (document.getElementById('showsGrid')?.querySelector('.grid-loading')) {
                loadShows();
            }
            break;
        case 'collections':
            loadCollections();
            break;
        case 'requests':
            loadRequests();
            break;
        case 'calendar':
            loadCalendar();
            break;
        case 'stats':
            loadStatistics();
            break;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SEARCH
// ─────────────────────────────────────────────────────────────────────────────

function initSearch() {
    const searchInput = document.getElementById('globalSearch');
    const searchDropdown = document.getElementById('searchDropdown');

    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        const query = e.target.value.trim();

        if (query.length < 2) {
            closeSearchDropdown();
            return;
        }

        searchTimeout = setTimeout(() => performSearch(query), 300);
    });

    searchInput.addEventListener('focus', () => {
        if (searchDropdown && searchDropdown.children.length > 0) {
            searchDropdown.classList.add('active');
        }
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.header-search')) {
            closeSearchDropdown();
        }
    });
}

async function performSearch(query) {
    const dropdown = document.getElementById('searchDropdown');
    dropdown.textContent = '';

    const loading = createLoadingElement('Searching...');
    dropdown.appendChild(loading);
    dropdown.classList.add('active');

    try {
        // Search local library and TMDB in parallel
        const [localResponse, tmdbResponse] = await Promise.all([
            fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`),
            tmdbConfigured ? fetch(`${API_BASE}/tmdb/search?q=${encodeURIComponent(query)}`) : Promise.resolve(null)
        ]);

        const localData = await localResponse.json();
        const tmdbData = tmdbResponse ? await tmdbResponse.json() : null;

        dropdown.textContent = '';

        const allResults = localData.success ? localData.results : [];

        // Add TMDB results that aren't in library
        if (tmdbData?.success && tmdbData.results) {
            const localTitles = new Set(allResults.map(r => r.title.toLowerCase()));
            tmdbData.results.forEach(item => {
                if (!localTitles.has(item.title.toLowerCase()) && !item.in_library) {
                    item.source = 'tmdb';
                    allResults.push(item);
                }
            });
        }

        if (allResults.length > 0) {
            renderSearchResults(allResults);
        } else {
            const empty = createEmptyState(null, 'No results found');
            dropdown.appendChild(empty);
        }
    } catch (error) {
        dropdown.textContent = '';
        const empty = createEmptyState(null, 'Search failed');
        dropdown.appendChild(empty);
    }
}

function renderSearchResults(results) {
    const dropdown = document.getElementById('searchDropdown');
    dropdown.textContent = '';

    const inLibrary = results.filter(r => r.in_library);
    const notInLibrary = results.filter(r => !r.in_library);

    if (inLibrary.length > 0) {
        const section = document.createElement('div');
        section.className = 'search-section';

        const title = document.createElement('div');
        title.className = 'search-section-title';
        title.textContent = 'In Your Library';
        section.appendChild(title);

        inLibrary.forEach(item => {
            section.appendChild(createSearchResultElement(item, true));
        });
        dropdown.appendChild(section);
    }

    if (notInLibrary.length > 0) {
        const section = document.createElement('div');
        section.className = 'search-section';

        const title = document.createElement('div');
        title.className = 'search-section-title';
        title.textContent = 'Available to Request';
        section.appendChild(title);

        notInLibrary.slice(0, 10).forEach(item => {
            section.appendChild(createSearchResultElement(item, false));
        });
        dropdown.appendChild(section);
    }
}

function createSearchResultElement(item, inLibrary) {
    const el = document.createElement('div');
    el.className = 'search-result';
    el.onclick = () => openMediaDetails(item);

    const poster = document.createElement('img');
    poster.className = 'search-result-poster';
    poster.src = item.poster_url || '/static/img/no-poster.png';
    poster.alt = '';
    poster.onerror = function() { this.style.display = 'none'; };

    const info = document.createElement('div');
    info.className = 'search-result-info';

    const titleEl = document.createElement('div');
    titleEl.className = 'search-result-title';
    titleEl.textContent = item.title;

    const meta = document.createElement('div');
    meta.className = 'search-result-meta';
    const typeLabel = item.media_type === 'movie' ? 'Movie' : 'TV Show';
    const rating = item.rating ? ` • ★ ${item.rating.toFixed(1)}` : '';
    meta.textContent = `${item.year || ''} • ${typeLabel}${rating}`;

    info.appendChild(titleEl);
    info.appendChild(meta);

    el.appendChild(poster);
    el.appendChild(info);

    const badge = document.createElement('span');
    badge.className = inLibrary ? 'search-result-badge' : 'search-result-badge request';
    badge.textContent = inLibrary ? 'In Library' : 'Request';
    if (!inLibrary) {
        badge.onclick = (e) => {
            e.stopPropagation();
            requestMedia(item);
        };
    }
    el.appendChild(badge);

    return el;
}

function closeSearchDropdown() {
    const dropdown = document.getElementById('searchDropdown');
    if (dropdown) dropdown.classList.remove('active');
}

// ─────────────────────────────────────────────────────────────────────────────
// DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

async function loadDashboard() {
    loadStatus();
    loadStats();
    loadContinueWatching();
    loadRecentAdditions();
    loadDownloads();
    loadAiringToday();
    if (tmdbConfigured) loadTrending();
}

async function checkTMDBStatus() {
    try {
        const response = await fetch(`${API_BASE}/tmdb/status`);
        const data = await response.json();
        tmdbConfigured = data.configured;

        // Show/hide trending section based on TMDB availability
        const trendingSection = document.getElementById('trendingSection');
        if (trendingSection) {
            trendingSection.style.display = tmdbConfigured ? 'block' : 'none';
        }
    } catch (error) {
        tmdbConfigured = false;
    }
}

async function loadStatus() {
    try {
        const response = await fetch(`${API_BASE}/status`);
        const data = await response.json();

        if (data.success) {
            const services = Object.values(data.services);
            const onlineCount = services.filter(s => s.online).length;
            const totalCount = services.filter(s => s.is_enabled).length;

            const statusOrb = document.getElementById('systemStatus');
            const statusLabel = document.getElementById('statusLabel');

            if (statusOrb && statusLabel) {
                if (onlineCount === totalCount && totalCount > 0) {
                    statusOrb.className = 'status-orb online';
                    statusLabel.textContent = 'All Systems Online';
                } else if (onlineCount > 0) {
                    statusOrb.className = 'status-orb partial';
                    statusLabel.textContent = `${onlineCount}/${totalCount} Online`;
                } else {
                    statusOrb.className = 'status-orb offline';
                    statusLabel.textContent = 'Services Offline';
                }
            }
        }
    } catch (error) {
        console.error('Status load error:', error);
    }
}

async function loadStats() {
    const setEl = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };

    const updateStatsUI = (stats) => {
        setEl('statMovies', stats.movie_count || '0');
        setEl('statShows', stats.show_count || '0');
        setEl('statEpisodes', stats.episode_count || '0');
        setEl('statStorage', stats.total_size_formatted || '0 B');
        setEl('movieCount', stats.movie_count || '--');
        setEl('showCount', stats.show_count || '--');
    };

    // Load from cache first for instant display
    const cached = cacheGet('stats');
    if (cached && cached.data) {
        updateStatsUI(cached.data);
        console.log(`[Media Hub] Stats loaded from cache (age: ${Math.round(cached.age / 1000)}s)`);
    }

    // Fetch fresh data in background
    try {
        const response = await fetch(`${API_BASE}/library/stats`);
        const data = await response.json();

        if (data.success && data.stats) {
            updateStatsUI(data.stats);
            cacheSet('stats', data.stats);
        }
    } catch (error) {
        console.error('Stats load error:', error);
        // If fetch failed and no cache, show error state
        if (!cached) {
            setEl('statMovies', '--');
            setEl('statShows', '--');
        }
    }
}

async function loadContinueWatching() {
    const container = document.getElementById('continueWatching');
    const section = document.getElementById('continueWatchingSection');
    if (!container) return;

    try {
        const response = await fetch(`${API_BASE}/library/continue-watching?limit=10`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.items && data.items.length > 0) {
            data.items.forEach(item => {
                container.appendChild(createContinueWatchingCard(item));
            });
            // Show the section
            if (section) section.style.display = 'block';
        } else {
            // Hide if no items
            if (section) section.style.display = 'none';
        }
        lucide.createIcons();
    } catch (error) {
        if (section) section.style.display = 'none';
    }
}

function createContinueWatchingCard(item) {
    const card = document.createElement('div');
    card.className = 'continue-card';
    card.onclick = () => openMediaDetails(item);

    // Backdrop/thumb
    const thumb = document.createElement('div');
    thumb.className = 'continue-thumb';
    if (item.backdrop_url || item.poster_url) {
        thumb.style.backgroundImage = `url(${item.backdrop_url || item.poster_url})`;
    }

    // Progress bar
    const progress = item.metadata?.watch_progress || 0;
    const progressBar = document.createElement('div');
    progressBar.className = 'continue-progress';
    const progressFill = document.createElement('div');
    progressFill.className = 'continue-progress-fill';
    progressFill.style.width = `${progress}%`;
    progressBar.appendChild(progressFill);
    thumb.appendChild(progressBar);

    // Play icon
    const playIcon = document.createElement('div');
    playIcon.className = 'continue-play';
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', 'play');
    playIcon.appendChild(icon);
    thumb.appendChild(playIcon);

    // Info
    const info = document.createElement('div');
    info.className = 'continue-info';

    const title = document.createElement('div');
    title.className = 'continue-title';
    if (item.media_type === 'episode') {
        title.textContent = item.metadata?.show_title || item.title;
    } else {
        title.textContent = item.title;
    }

    const meta = document.createElement('div');
    meta.className = 'continue-meta';
    if (item.media_type === 'episode' && item.season_number && item.episode_number) {
        meta.textContent = `S${item.season_number}E${item.episode_number} • ${item.title}`;
    } else {
        meta.textContent = `${progress}% watched`;
    }

    info.appendChild(title);
    info.appendChild(meta);

    card.appendChild(thumb);
    card.appendChild(info);

    return card;
}

async function loadRecentAdditions() {
    const container = document.getElementById('recentAdditions');
    if (!container) return;

    const renderItems = (items) => {
        container.textContent = '';
        if (items && items.length > 0) {
            items.forEach(item => {
                container.appendChild(createPosterCard(item));
            });
            lucide.createIcons();
        } else {
            container.appendChild(createEmptyState('film', 'No recent additions'));
            lucide.createIcons();
        }
    };

    // Load from cache first for instant display
    const cached = cacheGet('recent-additions');
    if (cached && cached.data) {
        renderItems(cached.data);
        console.log(`[Media Hub] Recent additions loaded from cache (age: ${Math.round(cached.age / 1000)}s)`);
    }

    // Fetch fresh data
    try {
        const response = await fetch(`${API_BASE}/library/recent?limit=12`);
        const data = await response.json();

        if (data.success && data.items) {
            renderItems(data.items);
            cacheSet('recent-additions', data.items);
        }
    } catch (error) {
        // Only show error if no cached data
        if (!cached) {
            container.textContent = '';
            container.appendChild(createEmptyState('alert-circle', 'Failed to load'));
            lucide.createIcons();
        }
    }
}

async function loadTrending(type = 'all') {
    const container = document.getElementById('trendingContent');
    const section = document.getElementById('trendingSection');
    if (!container || !tmdbConfigured) return;

    try {
        const response = await fetch(`${API_BASE}/tmdb/trending?type=${type}&window=week`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.items && data.items.length > 0) {
            data.items.slice(0, 12).forEach(item => {
                container.appendChild(createPosterCard(item, true));
            });
            if (section) section.style.display = 'block';
            lucide.createIcons();
        } else {
            if (section) section.style.display = 'none';
        }
    } catch (error) {
        console.error('Trending load error:', error);
        if (section) section.style.display = 'none';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// POSTER CARDS WITH QUALITY BADGES
// ─────────────────────────────────────────────────────────────────────────────

function createPosterCard(item, showRequestButton = false) {
    const card = document.createElement('div');
    card.className = 'poster-card';
    card.onclick = () => openMediaDetails(item);

    // Image with lazy loading
    const imgContainer = document.createElement('div');
    imgContainer.className = 'poster-image';

    const img = document.createElement('img');
    img.className = 'lazy-image';
    img.alt = item.title || '';

    // Use placeholder initially
    img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450"%3E%3Crect fill="%231a1a2e" width="300" height="450"/%3E%3C/svg%3E';
    img.dataset.src = item.poster_url || '/static/img/no-poster.png';
    img.onerror = function() { this.src = '/static/img/no-poster.png'; };

    lazyLoadImage(img);
    imgContainer.appendChild(img);

    // Quality badges
    const badges = item.metadata?.quality_badges || [];
    if (badges.length > 0) {
        const badgeContainer = document.createElement('div');
        badgeContainer.className = 'quality-badges';

        badges.slice(0, 3).forEach(badge => {
            const badgeEl = document.createElement('span');
            badgeEl.className = 'quality-badge';
            if (badge === '4K') badgeEl.classList.add('badge-4k');
            else if (badge === 'DV' || badge.includes('HDR')) badgeEl.classList.add('badge-hdr');
            else if (badge === 'Atmos' || badge === 'DTS:X') badgeEl.classList.add('badge-audio');
            badgeEl.textContent = badge;
            badgeContainer.appendChild(badgeEl);
        });

        imgContainer.appendChild(badgeContainer);
    }

    // In library badge
    if (item.in_library) {
        const libraryBadge = document.createElement('div');
        libraryBadge.className = 'library-badge';
        const checkIcon = document.createElement('i');
        checkIcon.setAttribute('data-lucide', 'check');
        libraryBadge.appendChild(checkIcon);
        imgContainer.appendChild(libraryBadge);
    }

    // Request button for items not in library
    if (showRequestButton && !item.in_library) {
        const requestBtn = document.createElement('button');
        requestBtn.className = 'poster-request-btn';
        requestBtn.onclick = (e) => {
            e.stopPropagation();
            requestMedia(item);
        };
        const plusIcon = document.createElement('i');
        plusIcon.setAttribute('data-lucide', 'plus');
        requestBtn.appendChild(plusIcon);
        imgContainer.appendChild(requestBtn);
    }

    // Title
    const title = document.createElement('div');
    title.className = 'poster-title';
    title.textContent = item.title || 'Unknown';

    // Meta (year, type)
    const meta = document.createElement('div');
    meta.className = 'poster-meta';
    const parts = [];
    if (item.year) parts.push(item.year);
    if (item.media_type) parts.push(item.media_type === 'movie' ? 'Movie' : 'TV');
    if (item.rating) parts.push(`★ ${Number(item.rating).toFixed(1)}`);
    meta.textContent = parts.join(' • ');

    card.appendChild(imgContainer);
    card.appendChild(title);
    card.appendChild(meta);

    return card;
}

// ─────────────────────────────────────────────────────────────────────────────
// DOWNLOADS WITH CONTROLS
// ─────────────────────────────────────────────────────────────────────────────

async function loadDownloads() {
    const container = document.getElementById('downloadsPanel');
    if (!container) return;

    try {
        const response = await fetch(`${API_BASE}/downloads`);
        const data = await response.json();

        container.textContent = '';

        // Speed indicator
        const speedInfo = document.createElement('div');
        speedInfo.className = 'download-speed-info';
        if (data.speed) {
            const speedText = document.createElement('span');
            speedText.className = 'download-speed';
            speedText.textContent = data.speed.speed || '0 B/s';

            const controls = document.createElement('div');
            controls.className = 'download-controls';

            if (data.speed.paused) {
                const resumeBtn = createButton('play', 'Resume All', () => controlDownloads('resume'));
                controls.appendChild(resumeBtn);
            } else {
                const pauseBtn = createButton('pause', 'Pause All', () => controlDownloads('pause'));
                controls.appendChild(pauseBtn);
            }

            speedInfo.appendChild(speedText);
            speedInfo.appendChild(controls);
            container.appendChild(speedInfo);
        }

        if (data.success && data.queue && data.queue.length > 0) {
            data.queue.forEach(item => {
                container.appendChild(createDownloadItem(item));
            });
        } else {
            const empty = document.createElement('div');
            empty.className = 'download-empty';
            empty.textContent = 'No active downloads';
            container.appendChild(empty);
        }
        lucide.createIcons();
    } catch (error) {
        container.textContent = '';
        const empty = document.createElement('div');
        empty.className = 'download-empty';
        empty.textContent = 'Failed to load downloads';
        container.appendChild(empty);
    }
}

function createDownloadItem(item) {
    const el = document.createElement('div');
    el.className = 'download-item';

    const info = document.createElement('div');
    info.className = 'download-info';

    const name = document.createElement('div');
    name.className = 'download-name';
    name.textContent = item.filename || 'Unknown';
    name.title = item.filename;

    const meta = document.createElement('div');
    meta.className = 'download-meta';
    const sizeLeft = formatBytes(item.size_left_bytes || 0);
    const eta = item.eta_seconds ? formatETA(item.eta_seconds) : '';
    meta.textContent = `${sizeLeft} left${eta ? ' • ' + eta : ''}`;

    info.appendChild(name);
    info.appendChild(meta);

    const progress = document.createElement('div');
    progress.className = 'download-progress';
    const progressBar = document.createElement('div');
    progressBar.className = 'download-progress-bar';
    progressBar.style.width = `${item.progress_percent || 0}%`;
    progress.appendChild(progressBar);

    const progressText = document.createElement('span');
    progressText.className = 'download-progress-text';
    progressText.textContent = `${item.progress_percent || 0}%`;

    const controls = document.createElement('div');
    controls.className = 'download-item-controls';

    if (item.status === 'paused') {
        controls.appendChild(createButton('play', '', () => controlDownloadItem(item.id, 'resume'), 'small'));
    } else {
        controls.appendChild(createButton('pause', '', () => controlDownloadItem(item.id, 'pause'), 'small'));
    }
    controls.appendChild(createButton('trash-2', '', () => controlDownloadItem(item.id, 'delete'), 'small danger'));

    el.appendChild(info);
    el.appendChild(progress);
    el.appendChild(progressText);
    el.appendChild(controls);

    return el;
}

async function controlDownloads(action) {
    try {
        await fetch(`${API_BASE}/downloads/${action}`, { method: 'POST' });
        loadDownloads();
    } catch (error) {
        showToast('Failed to ' + action + ' downloads', 'error');
    }
}

async function controlDownloadItem(id, action) {
    try {
        if (action === 'delete') {
            await fetch(`${API_BASE}/downloads/${id}`, { method: 'DELETE' });
        } else {
            await fetch(`${API_BASE}/downloads/${id}/${action}`, { method: 'POST' });
        }
        loadDownloads();
    } catch (error) {
        showToast('Failed to ' + action + ' download', 'error');
    }
}

function createButton(icon, text, onClick, className = '') {
    const btn = document.createElement('button');
    btn.className = `btn-icon ${className}`;
    btn.onclick = onClick;

    const iconEl = document.createElement('i');
    iconEl.setAttribute('data-lucide', icon);
    btn.appendChild(iconEl);

    if (text) {
        const span = document.createElement('span');
        span.textContent = text;
        btn.appendChild(span);
    }

    return btn;
}

// ─────────────────────────────────────────────────────────────────────────────
// AIRING TODAY / CALENDAR
// ─────────────────────────────────────────────────────────────────────────────

async function loadAiringToday() {
    const container = document.getElementById('airingTodayPanel');
    if (!container) return;

    try {
        const response = await fetch(`${API_BASE}/calendar/upcoming?days=1`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.episodes && data.episodes.length > 0) {
            data.episodes.slice(0, 5).forEach(ep => {
                container.appendChild(createEpisodeCard(ep));
            });
        } else {
            const empty = document.createElement('div');
            empty.className = 'airing-empty';
            empty.textContent = 'Nothing airing today';
            container.appendChild(empty);
        }
        lucide.createIcons();
    } catch (error) {
        container.textContent = '';
        const empty = document.createElement('div');
        empty.className = 'airing-empty';
        empty.textContent = 'Calendar unavailable';
        container.appendChild(empty);
    }
}

function createEpisodeCard(ep) {
    const card = document.createElement('div');
    card.className = 'episode-card';

    const poster = document.createElement('img');
    poster.className = 'episode-poster';
    poster.src = ep.poster_url || '/static/img/no-poster.png';
    poster.alt = '';
    poster.onerror = function() { this.style.display = 'none'; };

    const info = document.createElement('div');
    info.className = 'episode-info';

    const title = document.createElement('div');
    title.className = 'episode-title';
    title.textContent = ep.series_title;

    const meta = document.createElement('div');
    meta.className = 'episode-meta';
    meta.textContent = `S${String(ep.season_number).padStart(2, '0')}E${String(ep.episode_number).padStart(2, '0')}`;
    if (ep.air_time) meta.textContent += ` • ${ep.air_time}`;

    const epTitle = document.createElement('div');
    epTitle.className = 'episode-name';
    epTitle.textContent = ep.episode_title;

    info.appendChild(title);
    info.appendChild(meta);
    info.appendChild(epTitle);

    const status = document.createElement('div');
    status.className = ep.has_file ? 'episode-status available' : 'episode-status pending';
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', ep.has_file ? 'check-circle' : 'clock');
    status.appendChild(icon);

    card.appendChild(poster);
    card.appendChild(info);
    card.appendChild(status);

    return card;
}

async function loadCalendar() {
    const container = document.getElementById('calendarGrid');
    if (!container) return;

    try {
        const response = await fetch(`${API_BASE}/calendar/upcoming?days=14`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.episodes && data.episodes.length > 0) {
            // Group by date
            const grouped = {};
            data.episodes.forEach(ep => {
                const date = ep.air_date || 'Unknown';
                if (!grouped[date]) grouped[date] = [];
                grouped[date].push(ep);
            });

            Object.entries(grouped).forEach(([date, episodes]) => {
                const daySection = document.createElement('div');
                daySection.className = 'calendar-day';

                const dateHeader = document.createElement('div');
                dateHeader.className = 'calendar-date';
                dateHeader.textContent = formatDate(date);
                daySection.appendChild(dateHeader);

                const episodesList = document.createElement('div');
                episodesList.className = 'calendar-episodes';
                episodes.forEach(ep => {
                    episodesList.appendChild(createEpisodeCard(ep));
                });
                daySection.appendChild(episodesList);

                container.appendChild(daySection);
            });
        } else {
            container.appendChild(createEmptyState('calendar', 'No upcoming episodes'));
        }
        lucide.createIcons();
    } catch (error) {
        container.textContent = '';
        container.appendChild(createEmptyState('alert-circle', 'Failed to load calendar'));
        lucide.createIcons();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// COLLECTIONS
// ─────────────────────────────────────────────────────────────────────────────

async function loadCollections() {
    const container = document.getElementById('collectionsGrid');
    if (!container) return;

    container.textContent = '';
    container.appendChild(createLoadingElement('Loading collections...'));

    try {
        const response = await fetch(`${API_BASE}/library/collections`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.collections && data.collections.length > 0) {
            data.collections.forEach(coll => {
                container.appendChild(createCollectionCard(coll));
            });
        } else {
            container.appendChild(createEmptyState('folder', 'No collections found'));
        }
        lucide.createIcons();
    } catch (error) {
        container.textContent = '';
        container.appendChild(createEmptyState('alert-circle', 'Failed to load collections'));
        lucide.createIcons();
    }
}

function createCollectionCard(collection) {
    const card = document.createElement('div');
    card.className = 'collection-card';
    card.onclick = () => openCollection(collection.id, collection.title);

    const imgContainer = document.createElement('div');
    imgContainer.className = 'collection-image';
    if (collection.poster_url) {
        const img = document.createElement('img');
        img.src = collection.poster_url;
        img.alt = '';
        img.onerror = function() { this.style.display = 'none'; };
        imgContainer.appendChild(img);
    }

    const count = document.createElement('div');
    count.className = 'collection-count';
    count.textContent = `${collection.child_count} items`;
    imgContainer.appendChild(count);

    const title = document.createElement('div');
    title.className = 'collection-title';
    title.textContent = collection.title;

    card.appendChild(imgContainer);
    card.appendChild(title);

    return card;
}

async function openCollection(collectionId, title) {
    const container = document.getElementById('collectionsGrid');
    container.textContent = '';

    // Back button
    const backBtn = document.createElement('button');
    backBtn.className = 'collection-back-btn';
    backBtn.onclick = loadCollections;
    const backIcon = document.createElement('i');
    backIcon.setAttribute('data-lucide', 'arrow-left');
    backBtn.appendChild(backIcon);
    const backText = document.createElement('span');
    backText.textContent = 'Back to Collections';
    backBtn.appendChild(backText);
    container.appendChild(backBtn);

    // Title
    const titleEl = document.createElement('h2');
    titleEl.className = 'collection-detail-title';
    titleEl.textContent = title;
    container.appendChild(titleEl);

    // Grid
    const grid = document.createElement('div');
    grid.className = 'media-grid';
    grid.appendChild(createLoadingElement('Loading...'));
    container.appendChild(grid);

    lucide.createIcons();

    try {
        const response = await fetch(`${API_BASE}/library/collections/${collectionId}`);
        const data = await response.json();

        grid.textContent = '';

        if (data.success && data.items && data.items.length > 0) {
            data.items.forEach(item => {
                grid.appendChild(createPosterCard(item));
            });
        } else {
            grid.appendChild(createEmptyState('film', 'Collection is empty'));
        }
        lucide.createIcons();
    } catch (error) {
        grid.textContent = '';
        grid.appendChild(createEmptyState('alert-circle', 'Failed to load'));
        lucide.createIcons();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// MOVIES & SHOWS
// ─────────────────────────────────────────────────────────────────────────────

async function loadMovies(append = false) {
    const grid = document.getElementById('moviesGrid');
    if (!grid) return;

    if (!append) {
        grid.textContent = '';
        moviesOffset = 0;
    }

    const loading = createLoadingElement('Loading movies...');
    grid.appendChild(loading);

    try {
        const response = await fetch(`${API_BASE}/library/movies?limit=50&offset=${moviesOffset}`);
        const data = await response.json();

        loading.remove();

        if (data.success && data.items) {
            data.items.forEach(item => {
                grid.appendChild(createPosterCard(item));
            });
            moviesOffset += data.items.length;

            // Load more button
            if (data.items.length === 50) {
                const loadMore = document.createElement('button');
                loadMore.className = 'load-more-btn';
                loadMore.textContent = 'Load More';
                loadMore.onclick = () => {
                    loadMore.remove();
                    loadMovies(true);
                };
                grid.appendChild(loadMore);
            }
        }
        lucide.createIcons();
    } catch (error) {
        loading.remove();
        grid.appendChild(createEmptyState('alert-circle', 'Failed to load movies'));
        lucide.createIcons();
    }
}

async function loadShows(append = false) {
    const grid = document.getElementById('showsGrid');
    if (!grid) return;

    if (!append) {
        grid.textContent = '';
        showsOffset = 0;
    }

    const loading = createLoadingElement('Loading shows...');
    grid.appendChild(loading);

    try {
        const response = await fetch(`${API_BASE}/library/shows?limit=50&offset=${showsOffset}`);
        const data = await response.json();

        loading.remove();

        if (data.success && data.items) {
            data.items.forEach(item => {
                grid.appendChild(createPosterCard(item));
            });
            showsOffset += data.items.length;

            if (data.items.length === 50) {
                const loadMore = document.createElement('button');
                loadMore.className = 'load-more-btn';
                loadMore.textContent = 'Load More';
                loadMore.onclick = () => {
                    loadMore.remove();
                    loadShows(true);
                };
                grid.appendChild(loadMore);
            }
        }
        lucide.createIcons();
    } catch (error) {
        loading.remove();
        grid.appendChild(createEmptyState('alert-circle', 'Failed to load shows'));
        lucide.createIcons();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// REQUESTS
// ─────────────────────────────────────────────────────────────────────────────

async function loadRequests() {
    const container = document.getElementById('requestsList');
    if (!container) return;

    container.textContent = '';
    container.appendChild(createLoadingElement('Loading requests...'));

    try {
        const response = await fetch(`${API_BASE}/requests`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.requests && data.requests.length > 0) {
            data.requests.forEach(req => {
                container.appendChild(createRequestCard(req));
            });
        } else {
            container.appendChild(createEmptyState('inbox', 'No pending requests'));
        }
        lucide.createIcons();
    } catch (error) {
        container.textContent = '';
        container.appendChild(createEmptyState('alert-circle', 'Failed to load requests'));
        lucide.createIcons();
    }
}

function createRequestCard(req) {
    const card = document.createElement('div');
    card.className = 'request-card';

    const poster = document.createElement('img');
    poster.className = 'request-poster';
    poster.src = req.poster_url || '/static/img/no-poster.png';
    poster.alt = '';

    const info = document.createElement('div');
    info.className = 'request-info';

    const title = document.createElement('div');
    title.className = 'request-title';
    title.textContent = req.title;

    const meta = document.createElement('div');
    meta.className = 'request-meta';
    meta.textContent = `${req.media_type === 'movie' ? 'Movie' : 'TV Show'} • ${req.year || 'N/A'}`;

    const status = document.createElement('div');
    status.className = `request-status status-${req.status}`;
    status.textContent = req.status_label || req.status;

    info.appendChild(title);
    info.appendChild(meta);
    info.appendChild(status);

    card.appendChild(poster);
    card.appendChild(info);

    return card;
}

async function requestMedia(item) {
    if (!item.tmdb_id && !item.id) {
        showToast('Cannot request this item', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/requests`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                media_type: item.media_type,
                tmdb_id: item.tmdb_id || item.id
            })
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Requested: ${item.title}`, 'success');
        } else {
            showToast(data.error || 'Request failed', 'error');
        }
    } catch (error) {
        showToast('Request failed', 'error');
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// STATISTICS
// ─────────────────────────────────────────────────────────────────────────────

async function loadStatistics() {
    const container = document.getElementById('statsContent');
    if (!container) return;

    container.textContent = '';
    container.appendChild(createLoadingElement('Loading statistics...'));

    try {
        const response = await fetch(`${API_BASE}/stats`);
        const data = await response.json();

        container.textContent = '';

        if (data.success) {
            // Quality breakdown chart
            const qualitySection = document.createElement('div');
            qualitySection.className = 'stats-section';

            const qualityTitle = document.createElement('h3');
            qualityTitle.textContent = 'Quality Breakdown';
            qualitySection.appendChild(qualityTitle);

            const qualityChart = createQualityChart(data.quality_breakdown);
            qualitySection.appendChild(qualityChart);

            // HDR/Atmos counts
            const specialSection = document.createElement('div');
            specialSection.className = 'stats-grid';

            specialSection.appendChild(createStatCard('HDR Content', data.hdr_count, 'sun'));
            specialSection.appendChild(createStatCard('Dolby Atmos', data.atmos_count, 'volume-2'));

            // Size breakdown
            const sizeSection = document.createElement('div');
            sizeSection.className = 'stats-section';

            const sizeTitle = document.createElement('h3');
            sizeTitle.textContent = 'Storage Breakdown';
            sizeSection.appendChild(sizeTitle);

            const sizeChart = createSizeChart(data.size_breakdown);
            sizeSection.appendChild(sizeChart);

            container.appendChild(qualitySection);
            container.appendChild(specialSection);
            container.appendChild(sizeSection);
        } else {
            container.appendChild(createEmptyState('bar-chart', 'Statistics unavailable'));
        }
        lucide.createIcons();
    } catch (error) {
        container.textContent = '';
        container.appendChild(createEmptyState('alert-circle', 'Failed to load statistics'));
        lucide.createIcons();
    }
}

function createQualityChart(breakdown) {
    const chart = document.createElement('div');
    chart.className = 'quality-chart';

    const total = Object.values(breakdown).reduce((a, b) => a + b, 0);

    Object.entries(breakdown).forEach(([quality, count]) => {
        const bar = document.createElement('div');
        bar.className = 'quality-bar';

        const label = document.createElement('span');
        label.className = 'quality-label';
        label.textContent = quality;

        const track = document.createElement('div');
        track.className = 'quality-track';

        const fill = document.createElement('div');
        fill.className = `quality-fill quality-${quality.toLowerCase().replace('p', '')}`;
        fill.style.width = total > 0 ? `${(count / total) * 100}%` : '0%';
        track.appendChild(fill);

        const value = document.createElement('span');
        value.className = 'quality-value';
        value.textContent = count;

        bar.appendChild(label);
        bar.appendChild(track);
        bar.appendChild(value);
        chart.appendChild(bar);
    });

    return chart;
}

function createSizeChart(breakdown) {
    const chart = document.createElement('div');
    chart.className = 'size-chart';

    const total = (breakdown.movies || 0) + (breakdown.shows || 0);

    const moviesPercent = total > 0 ? (breakdown.movies / total) * 100 : 50;
    const showsPercent = total > 0 ? (breakdown.shows / total) * 100 : 50;

    const bar = document.createElement('div');
    bar.className = 'size-bar';

    const moviesFill = document.createElement('div');
    moviesFill.className = 'size-fill movies';
    moviesFill.style.width = `${moviesPercent}%`;
    moviesFill.title = `Movies: ${formatBytes(breakdown.movies || 0)}`;

    const showsFill = document.createElement('div');
    showsFill.className = 'size-fill shows';
    showsFill.style.width = `${showsPercent}%`;
    showsFill.title = `TV Shows: ${formatBytes(breakdown.shows || 0)}`;

    bar.appendChild(moviesFill);
    bar.appendChild(showsFill);

    const legend = document.createElement('div');
    legend.className = 'size-legend';

    const moviesLegend = document.createElement('span');
    moviesLegend.className = 'legend-item movies';
    moviesLegend.textContent = `Movies: ${formatBytes(breakdown.movies || 0)}`;

    const showsLegend = document.createElement('span');
    showsLegend.className = 'legend-item shows';
    showsLegend.textContent = `TV Shows: ${formatBytes(breakdown.shows || 0)}`;

    legend.appendChild(moviesLegend);
    legend.appendChild(showsLegend);

    chart.appendChild(bar);
    chart.appendChild(legend);

    return chart;
}

function createStatCard(label, value, icon) {
    const card = document.createElement('div');
    card.className = 'stat-card';

    const iconEl = document.createElement('i');
    iconEl.setAttribute('data-lucide', icon);

    const valueEl = document.createElement('div');
    valueEl.className = 'stat-value';
    valueEl.textContent = value || 0;

    const labelEl = document.createElement('div');
    labelEl.className = 'stat-label';
    labelEl.textContent = label;

    card.appendChild(iconEl);
    card.appendChild(valueEl);
    card.appendChild(labelEl);

    return card;
}

// ─────────────────────────────────────────────────────────────────────────────
// MEDIA DETAILS PANEL
// ─────────────────────────────────────────────────────────────────────────────

function openMediaDetails(item) {
    const panel = document.getElementById('mediaPanel');
    const content = document.getElementById('mediaPanelContent');

    content.textContent = '';
    content.appendChild(createLoadingElement('Loading details...'));
    panel.classList.add('active');

    // Fetch additional details if needed
    if (item.in_library && item.id) {
        fetchLibraryDetails(item);
    } else if (item.tmdb_id || item.id) {
        fetchTMDBDetails(item);
    } else {
        renderMediaDetails(item);
    }
}

async function fetchLibraryDetails(item) {
    try {
        const [detailsResponse, qualityResponse] = await Promise.all([
            fetch(`${API_BASE}/media/${item.media_type}/${item.id}`),
            fetch(`${API_BASE}/media/${item.id}/quality`)
        ]);

        const detailsData = await detailsResponse.json();
        const qualityData = await qualityResponse.json();

        if (detailsData.success && detailsData.item) {
            const enrichedItem = { ...detailsData.item };
            if (qualityData.success) {
                enrichedItem.quality_info = qualityData.quality;
            }
            renderMediaDetails(enrichedItem);
        } else {
            renderMediaDetails(item);
        }
    } catch (error) {
        renderMediaDetails(item);
    }
}

async function fetchTMDBDetails(item) {
    if (!tmdbConfigured) {
        renderMediaDetails(item);
        return;
    }

    try {
        const endpoint = item.media_type === 'movie' ? 'movie' : 'tv';
        const id = item.tmdb_id || item.id;
        const response = await fetch(`${API_BASE}/tmdb/${endpoint}/${id}`);
        const data = await response.json();

        if (data.success) {
            const details = data.movie || data.show;
            renderMediaDetails({ ...item, ...details });
        } else {
            renderMediaDetails(item);
        }
    } catch (error) {
        renderMediaDetails(item);
    }
}

function renderMediaDetails(item) {
    const content = document.getElementById('mediaPanelContent');
    content.textContent = '';

    // Backdrop image
    if (item.backdrop_url) {
        const backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop-image';
        backdrop.style.backgroundImage = `url(${item.backdrop_url})`;
        content.appendChild(backdrop);
    }

    // Main content
    const main = document.createElement('div');
    main.className = 'modal-main';

    // Poster
    const posterContainer = document.createElement('div');
    posterContainer.className = 'modal-poster';
    const poster = document.createElement('img');
    poster.src = item.poster_url || '/static/img/no-poster.png';
    poster.alt = item.title;
    posterContainer.appendChild(poster);

    // Quality badges on poster
    const badges = item.metadata?.quality_badges || item.quality_info ? ['4K', 'HDR', 'Atmos'].filter(b => {
        if (b === '4K') return item.quality_info?.is_4k;
        if (b === 'HDR') return item.quality_info?.is_hdr;
        if (b === 'Atmos') return item.quality_info?.is_atmos;
        return false;
    }) : [];

    if (badges.length > 0 || item.metadata?.quality_badges?.length > 0) {
        const badgeContainer = document.createElement('div');
        badgeContainer.className = 'modal-badges';
        (item.metadata?.quality_badges || badges).forEach(badge => {
            const badgeEl = document.createElement('span');
            badgeEl.className = 'quality-badge';
            badgeEl.textContent = badge;
            badgeContainer.appendChild(badgeEl);
        });
        posterContainer.appendChild(badgeContainer);
    }

    main.appendChild(posterContainer);

    // Info
    const info = document.createElement('div');
    info.className = 'modal-info';

    // Title
    const title = document.createElement('h2');
    title.className = 'modal-title';
    title.textContent = item.title;
    info.appendChild(title);

    // Tagline
    if (item.tagline) {
        const tagline = document.createElement('div');
        tagline.className = 'modal-tagline';
        tagline.textContent = item.tagline;
        info.appendChild(tagline);
    }

    // Meta row
    const meta = document.createElement('div');
    meta.className = 'modal-meta';
    const metaParts = [];
    if (item.year) metaParts.push(item.year);
    if (item.runtime_minutes) metaParts.push(`${item.runtime_minutes} min`);
    if (item.rating) metaParts.push(`★ ${Number(item.rating).toFixed(1)}`);
    if (item.metadata?.contentRating) metaParts.push(item.metadata.contentRating);
    meta.textContent = metaParts.join(' • ');
    info.appendChild(meta);

    // Genres
    if (item.genres && item.genres.length > 0) {
        const genres = document.createElement('div');
        genres.className = 'modal-genres';
        item.genres.forEach(g => {
            const genre = document.createElement('span');
            genre.className = 'genre-tag';
            genre.textContent = g;
            genres.appendChild(genre);
        });
        info.appendChild(genres);
    }

    // Overview
    if (item.overview) {
        const overview = document.createElement('p');
        overview.className = 'modal-overview';
        overview.textContent = item.overview;
        info.appendChild(overview);
    }

    // Cast
    if (item.cast && item.cast.length > 0) {
        const castSection = document.createElement('div');
        castSection.className = 'modal-cast';

        const castTitle = document.createElement('h4');
        castTitle.textContent = 'Cast';
        castSection.appendChild(castTitle);

        const castList = document.createElement('div');
        castList.className = 'cast-list';
        item.cast.slice(0, 6).forEach(c => {
            const castItem = document.createElement('div');
            castItem.className = 'cast-item';
            castItem.textContent = c.name;
            if (c.character) {
                const role = document.createElement('span');
                role.className = 'cast-role';
                role.textContent = ` as ${c.character}`;
                castItem.appendChild(role);
            }
            castList.appendChild(castItem);
        });
        castSection.appendChild(castList);
        info.appendChild(castSection);
    }

    // File info (for library items)
    if (item.in_library && (item.file_path || item.file_size_bytes)) {
        const fileInfo = document.createElement('div');
        fileInfo.className = 'modal-file-info';

        if (item.quality_info) {
            const qi = item.quality_info;
            const techSpecs = [];
            if (qi.resolution) techSpecs.push(qi.resolution);
            if (qi.video_codec) techSpecs.push(qi.video_codec);
            if (qi.hdr_type) techSpecs.push(qi.hdr_type);
            if (qi.audio_codec) techSpecs.push(qi.audio_codec);
            if (qi.audio_channels) techSpecs.push(`${qi.audio_channels}ch`);

            if (techSpecs.length > 0) {
                const specs = document.createElement('div');
                specs.className = 'modal-specs';
                specs.textContent = techSpecs.join(' • ');
                fileInfo.appendChild(specs);
            }
        }

        if (item.file_size_bytes) {
            const size = document.createElement('div');
            size.className = 'modal-size';
            size.textContent = `File size: ${formatBytes(item.file_size_bytes)}`;
            fileInfo.appendChild(size);
        }

        info.appendChild(fileInfo);
    }

    // Episode browser for TV shows
    if (item.in_library && (item.media_type === 'show' || item.media_type === 'season')) {
        const episodeBrowser = document.createElement('div');
        episodeBrowser.className = 'episode-browser';
        episodeBrowser.id = 'episodeBrowser';

        const browserHeader = document.createElement('div');
        browserHeader.className = 'episode-browser-header';

        const browserTitle = document.createElement('h4');
        browserTitle.innerHTML = '<i data-lucide="list"></i> Episodes';
        browserHeader.appendChild(browserTitle);

        // Season selector
        const seasonSelector = document.createElement('select');
        seasonSelector.className = 'season-selector';
        seasonSelector.id = 'seasonSelector';
        seasonSelector.innerHTML = '<option value="">Loading seasons...</option>';
        browserHeader.appendChild(seasonSelector);

        episodeBrowser.appendChild(browserHeader);

        // Episode list container
        const episodeList = document.createElement('div');
        episodeList.className = 'episode-list';
        episodeList.id = 'episodeList';
        episodeList.innerHTML = '<div class="episode-loading">Loading episodes...</div>';
        episodeBrowser.appendChild(episodeList);

        info.appendChild(episodeBrowser);

        // Load seasons
        loadSeasonsForShow(item.id, seasonSelector, episodeList);
    }

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'modal-actions';

    if (item.in_library) {
        // Stream Now button - only for playable items (movies, episodes) not series/seasons
        const isPlayable = item.media_type === 'movie' || item.media_type === 'episode';
        const hasJellyfin = availableMediaServers.some(s => s.type === 'jellyfin') ||
                           availableMediaServers.length === 0;

        if (hasJellyfin && isPlayable) {
            const streamBtn = document.createElement('button');
            streamBtn.className = 'btn btn-stream';
            streamBtn.onclick = () => {
                closeMediaPanel();
                openVideoPlayer(item);
            };
            const streamIcon = document.createElement('i');
            streamIcon.setAttribute('data-lucide', 'monitor-play');
            streamBtn.appendChild(streamIcon);
            const streamText = document.createElement('span');
            streamText.textContent = 'Stream Now';
            streamBtn.appendChild(streamText);
            actions.appendChild(streamBtn);
        }

        // Ensure we have servers loaded, fallback to defaults if not
        const servers = availableMediaServers.length > 0 ? availableMediaServers : [
            { type: 'jellyfin', url: 'http://192.168.1.200:8096', name: 'Jellyfin' },
            { type: 'plex', url: 'http://192.168.1.200:32400', name: 'Plex' }
        ];

        // Show play button for each available media server
        servers.forEach((server, index) => {
            const playBtn = document.createElement('a');
            playBtn.className = 'btn btn-secondary';

            if (server.type === 'jellyfin') {
                // Jellyfin deep link to item
                playBtn.href = `${server.url}/web/index.html#!/details?id=${item.id}`;
            } else {
                // Plex - use GUID matching if TMDB/TVDB ID available, otherwise search
                if (item.tmdb_id && item.media_type === 'movie') {
                    // Plex can resolve TMDB GUIDs for movies
                    playBtn.href = `${server.url}/web/index.html#!/provider/tv.plex.provider.metadata/details?key=/library/metadata/plex://movie?guid=tmdb://${item.tmdb_id}`;
                } else if (item.tvdb_id && (item.media_type === 'show' || item.media_type === 'episode')) {
                    // Plex can resolve TVDB GUIDs for shows
                    playBtn.href = `${server.url}/web/index.html#!/provider/tv.plex.provider.metadata/details?key=/library/metadata/plex://show?guid=tvdb://${item.tvdb_id}`;
                } else {
                    // Fallback to search
                    playBtn.href = `${server.url}/web/index.html#!/search?query=${encodeURIComponent(item.title)}`;
                }
            }

            playBtn.target = '_blank';
            const playIcon = document.createElement('i');
            playIcon.setAttribute('data-lucide', 'external-link');
            playBtn.appendChild(playIcon);
            const playText = document.createElement('span');
            playText.textContent = server.name;
            playBtn.appendChild(playText);
            actions.appendChild(playBtn);
        });
    } else {
        // Request button
        const requestBtn = document.createElement('button');
        requestBtn.className = 'btn btn-primary';
        requestBtn.onclick = () => requestMedia(item);
        const reqIcon = document.createElement('i');
        reqIcon.setAttribute('data-lucide', 'plus');
        requestBtn.appendChild(reqIcon);
        const reqText = document.createElement('span');
        reqText.textContent = 'Request';
        requestBtn.appendChild(reqText);
        actions.appendChild(requestBtn);
    }

    // Trailer button
    if (item.trailer_url) {
        const trailerBtn = document.createElement('a');
        trailerBtn.className = 'btn btn-secondary';
        trailerBtn.href = item.trailer_url;
        trailerBtn.target = '_blank';
        const trailerIcon = document.createElement('i');
        trailerIcon.setAttribute('data-lucide', 'youtube');
        trailerBtn.appendChild(trailerIcon);
        const trailerText = document.createElement('span');
        trailerText.textContent = 'Trailer';
        trailerBtn.appendChild(trailerText);
        actions.appendChild(trailerBtn);
    }

    info.appendChild(actions);
    main.appendChild(info);
    content.appendChild(main);

    lucide.createIcons();
}

function closeMediaPanel() {
    document.getElementById('mediaPanel')?.classList.remove('active');
}

// ─────────────────────────────────────────────────────────────────────────────
// EPISODE BROWSER
// ─────────────────────────────────────────────────────────────────────────────

async function loadSeasonsForShow(seriesId, seasonSelector, episodeList) {
    try {
        const response = await fetch(`${API_BASE}/shows/${seriesId}/seasons`);
        const data = await response.json();

        if (data.success && data.seasons && data.seasons.length > 0) {
            seasonSelector.innerHTML = '';
            data.seasons.forEach((season, index) => {
                const option = document.createElement('option');
                option.value = season.season_number;
                option.textContent = season.name;
                if (index === 0) option.selected = true;
                seasonSelector.appendChild(option);
            });

            // Load first season's episodes
            loadEpisodesForSeason(seriesId, data.seasons[0].season_number, episodeList);

            // Add change listener
            seasonSelector.addEventListener('change', () => {
                loadEpisodesForSeason(seriesId, parseInt(seasonSelector.value), episodeList);
            });
        } else {
            seasonSelector.innerHTML = '<option value="">No seasons found</option>';
            episodeList.innerHTML = '<div class="episode-empty">No episodes available</div>';
        }
    } catch (error) {
        console.error('[Episode Browser] Error loading seasons:', error);
        seasonSelector.innerHTML = '<option value="">Error loading seasons</option>';
    }
    lucide.createIcons();
}

async function loadEpisodesForSeason(seriesId, seasonNumber, episodeList) {
    episodeList.innerHTML = '<div class="episode-loading"><div class="spinner"></div> Loading episodes...</div>';

    try {
        const response = await fetch(`${API_BASE}/shows/${seriesId}/episodes?season=${seasonNumber}`);
        const data = await response.json();

        if (data.success && data.episodes && data.episodes.length > 0) {
            episodeList.innerHTML = '';

            data.episodes.forEach(ep => {
                const episodeCard = document.createElement('div');
                episodeCard.className = 'episode-card' + (ep.has_file ? '' : ' unavailable');

                // Episode number badge
                const epNum = document.createElement('div');
                epNum.className = 'episode-number';
                epNum.textContent = ep.episode_number;
                episodeCard.appendChild(epNum);

                // Episode info
                const epInfo = document.createElement('div');
                epInfo.className = 'episode-info';

                const epTitle = document.createElement('div');
                epTitle.className = 'episode-title';
                epTitle.textContent = ep.title || `Episode ${ep.episode_number}`;
                epInfo.appendChild(epTitle);

                const epMeta = document.createElement('div');
                epMeta.className = 'episode-meta';
                const metaParts = [];
                if (ep.runtime_minutes) metaParts.push(`${ep.runtime_minutes}m`);
                if (ep.quality) metaParts.push(ep.quality);
                if (!ep.has_file) metaParts.push('Not downloaded');
                epMeta.textContent = metaParts.join(' • ');
                epInfo.appendChild(epMeta);

                episodeCard.appendChild(epInfo);

                // Action buttons
                const epActions = document.createElement('div');
                epActions.className = 'episode-actions';

                if (ep.has_file) {
                    // Stream button
                    const streamBtn = document.createElement('button');
                    streamBtn.className = 'btn-icon btn-stream-small';
                    streamBtn.title = 'Stream Now';
                    streamBtn.innerHTML = '<i data-lucide="play"></i>';
                    streamBtn.onclick = (e) => {
                        e.stopPropagation();
                        closeMediaPanel();
                        openVideoPlayer({
                            id: ep.id,
                            title: `${ep.title || 'Episode ' + ep.episode_number}`,
                            media_type: 'episode'
                        });
                    };
                    epActions.appendChild(streamBtn);

                    // Jellyfin link
                    const jellyfinBtn = document.createElement('a');
                    jellyfinBtn.className = 'btn-icon';
                    jellyfinBtn.title = 'Open in Jellyfin';
                    jellyfinBtn.href = `http://192.168.1.200:8096/web/index.html#!/details?id=${ep.id}`;
                    jellyfinBtn.target = '_blank';
                    jellyfinBtn.innerHTML = '<i data-lucide="external-link"></i>';
                    jellyfinBtn.onclick = (e) => e.stopPropagation();
                    epActions.appendChild(jellyfinBtn);
                }

                episodeCard.appendChild(epActions);
                episodeList.appendChild(episodeCard);
            });

            lucide.createIcons();
        } else {
            episodeList.innerHTML = '<div class="episode-empty">No episodes in this season</div>';
        }
    } catch (error) {
        console.error('[Episode Browser] Error loading episodes:', error);
        episodeList.innerHTML = '<div class="episode-error">Error loading episodes</div>';
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VIDEO PLAYER
// ─────────────────────────────────────────────────────────────────────────────

let currentStreamInfo = null;

async function openVideoPlayer(item) {
    const modal = document.getElementById('videoPlayerModal');
    const video = document.getElementById('videoPlayer');
    const loading = document.getElementById('videoLoading');
    const title = document.getElementById('videoPlayerTitle');
    const qualityInfo = document.getElementById('videoQualityInfo');
    const subtitleSelector = document.getElementById('videoSubtitleSelector');

    // Show modal with loading state
    modal.classList.add('active');
    loading.classList.remove('hidden');
    title.textContent = item.title || 'Now Playing';
    qualityInfo.innerHTML = '';
    subtitleSelector.innerHTML = '';

    try {
        // Get stream URL from API
        const response = await fetch(`${API_BASE}/stream/${item.id}`);
        const data = await response.json();

        if (!data.success || !data.stream) {
            throw new Error(data.error || 'Failed to get stream URL');
        }

        currentStreamInfo = data.stream;

        // Check if HLS (transcoded) stream
        if (data.stream.container === 'm3u8') {
            // Use HLS.js if available, otherwise native HLS (Safari)
            if (typeof Hls !== 'undefined' && Hls.isSupported()) {
                const hls = new Hls();
                hls.loadSource(data.stream.stream_url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, () => {
                    video.play();
                    loading.classList.add('hidden');
                });
                hls.on(Hls.Events.ERROR, (event, errorData) => {
                    console.error('[Video Player] HLS error:', errorData);
                    if (errorData.fatal) {
                        showToast('Playback error: ' + errorData.type, 'error');
                    }
                });
                // Store HLS instance for cleanup
                video.hlsInstance = hls;
            } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
                // Native HLS support (Safari)
                video.src = data.stream.stream_url;
                video.addEventListener('loadedmetadata', () => {
                    video.play();
                    loading.classList.add('hidden');
                }, { once: true });
            } else {
                throw new Error('HLS playback not supported in this browser');
            }
        } else {
            // Direct stream - standard video source
            video.src = data.stream.stream_url;
            video.addEventListener('loadedmetadata', () => {
                video.play();
                loading.classList.add('hidden');
            }, { once: true });
        }

        // Show quality info
        const qualityBadge = data.stream.transcode ? 'TRANSCODE' : 'DIRECT';
        qualityInfo.innerHTML = `
            <span class="quality-badge">${qualityBadge}</span>
            <span>${formatDuration(data.stream.duration_seconds)}</span>
        `;

        // Add subtitles if available
        if (data.stream.subtitles && data.stream.subtitles.length > 0) {
            const select = document.createElement('select');
            select.innerHTML = '<option value="">Subtitles: Off</option>';

            data.stream.subtitles.forEach((sub, index) => {
                const option = document.createElement('option');
                option.value = sub.url;
                option.textContent = sub.title;
                if (sub.default) option.selected = true;
                select.appendChild(option);
            });

            select.addEventListener('change', (e) => {
                // Remove existing tracks
                const existingTracks = video.querySelectorAll('track');
                existingTracks.forEach(t => t.remove());

                if (e.target.value) {
                    const track = document.createElement('track');
                    track.kind = 'subtitles';
                    track.src = e.target.value;
                    track.default = true;
                    video.appendChild(track);
                    // Enable the track
                    setTimeout(() => {
                        if (video.textTracks[0]) {
                            video.textTracks[0].mode = 'showing';
                        }
                    }, 100);
                }
            });

            subtitleSelector.appendChild(select);
        }

        // Handle video errors
        video.addEventListener('error', (e) => {
            console.error('[Video Player] Video error:', video.error);
            loading.classList.add('hidden');
            showToast('Video playback error', 'error');
        }, { once: true });

    } catch (error) {
        console.error('[Video Player] Error:', error);
        loading.classList.add('hidden');
        showToast(error.message || 'Failed to load video', 'error');
        closeVideoPlayer();
    }
}

function closeVideoPlayer() {
    const modal = document.getElementById('videoPlayerModal');
    const video = document.getElementById('videoPlayer');

    // Stop playback
    video.pause();
    video.src = '';

    // Cleanup HLS instance if exists
    if (video.hlsInstance) {
        video.hlsInstance.destroy();
        video.hlsInstance = null;
    }

    // Remove subtitle tracks
    const tracks = video.querySelectorAll('track');
    tracks.forEach(t => t.remove());

    modal.classList.remove('active');
    currentStreamInfo = null;
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
}

// Close video player on Escape (add to existing keyboard handler)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const videoModal = document.getElementById('videoPlayerModal');
        if (videoModal?.classList.contains('active')) {
            closeVideoPlayer();
            e.stopPropagation();
        }
    }
});

// ─────────────────────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────────────────────

async function loadSettings() {
    const container = document.getElementById('servicesGrid');
    if (!container) return;

    try {
        const response = await fetch(`${API_BASE}/settings`);
        const data = await response.json();

        container.textContent = '';

        if (data.success && data.services) {
            data.services.forEach(service => {
                container.appendChild(createServiceCard(service));
            });
        }
        lucide.createIcons();
    } catch (error) {
        console.error('Settings load error:', error);
    }
}

function createServiceCard(service) {
    const card = document.createElement('div');
    card.className = 'service-card';

    const header = document.createElement('div');
    header.className = 'service-header';

    const info = document.createElement('div');
    info.className = 'service-info';

    const name = document.createElement('div');
    name.className = 'service-name';
    name.textContent = service.name;

    const url = document.createElement('div');
    url.className = 'service-url';
    url.textContent = `${service.host}:${service.port}`;

    info.appendChild(name);
    info.appendChild(url);

    const status = document.createElement('div');
    status.className = `service-status ${service.health_status || 'unknown'}`;
    const statusIcon = document.createElement('i');
    statusIcon.setAttribute('data-lucide', service.health_status === 'healthy' ? 'check-circle' : 'alert-circle');
    status.appendChild(statusIcon);

    header.appendChild(info);
    header.appendChild(status);

    const actions = document.createElement('div');
    actions.className = 'service-actions';

    const testBtn = document.createElement('button');
    testBtn.className = 'btn-small';
    testBtn.textContent = 'Test';
    testBtn.onclick = () => testService(service.id);

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-small';
    editBtn.textContent = 'Edit';
    editBtn.onclick = () => openServiceModal(service);

    actions.appendChild(testBtn);
    actions.appendChild(editBtn);

    card.appendChild(header);
    card.appendChild(actions);

    return card;
}

async function testService(serviceId) {
    showToast('Testing connection...', 'info');

    try {
        const response = await fetch(`${API_BASE}/settings/test/${serviceId}`, { method: 'POST' });
        const data = await response.json();

        if (data.healthy) {
            showToast('Connection successful!', 'success');
        } else {
            showToast(data.message || 'Connection failed', 'error');
        }
        loadSettings();
    } catch (error) {
        showToast('Test failed', 'error');
    }
}

async function discoverServices() {
    showToast('Discovering services...', 'info');

    try {
        const response = await fetch(`${API_BASE}/settings/discover`, { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            showToast(`Found ${data.saved_count} API keys`, 'success');
            loadSettings();
        } else {
            showToast(data.error || 'Discovery failed', 'error');
        }
    } catch (error) {
        showToast('Discovery failed', 'error');
    }
}

function openServiceModal(service = null) {
    // Implementation for service modal
    showToast('Service configuration coming soon', 'info');
}

function closeServiceModal() {
    document.getElementById('serviceModal')?.classList.remove('active');
}

// ─────────────────────────────────────────────────────────────────────────────
// FILTER CHIPS
// ─────────────────────────────────────────────────────────────────────────────

function initFilterChips() {
    document.querySelectorAll('.filter-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const group = chip.closest('.filter-group');
            group?.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            // Apply filter based on chip data
        });
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// UTILITY FUNCTIONS
// ─────────────────────────────────────────────────────────────────────────────

function createLoadingElement(text = 'Loading...') {
    const el = document.createElement('div');
    el.className = 'grid-loading';

    const spinner = document.createElement('div');
    spinner.className = 'loading-spinner';

    const label = document.createElement('span');
    label.textContent = text;

    el.appendChild(spinner);
    el.appendChild(label);

    return el;
}

function createEmptyState(icon, message) {
    const el = document.createElement('div');
    el.className = 'empty-state';

    if (icon) {
        const iconEl = document.createElement('i');
        iconEl.setAttribute('data-lucide', icon);
        el.appendChild(iconEl);
    }

    const msg = document.createElement('span');
    msg.textContent = message;
    el.appendChild(msg);

    return el;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatDate(dateStr) {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    if (date.toDateString() === today.toDateString()) return 'Today';
    if (date.toDateString() === tomorrow.toDateString()) return 'Tomorrow';

    return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function formatETA(seconds) {
    if (!seconds || seconds <= 0) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function showToast(message, type = 'info') {
    // Remove existing toasts
    document.querySelectorAll('.toast').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ─────────────────────────────────────────────────────────────────────────────
// PWA SERVICE WORKER & INSTALL
// ─────────────────────────────────────────────────────────────────────────────

let deferredPrompt = null;

// Register service worker
if ('serviceWorker' in navigator) {
    window.addEventListener('load', async () => {
        try {
            const registration = await navigator.serviceWorker.register('/static/js/media-hub-sw.js', {
                scope: '/tools/media-hub'
            });
            console.log('[Media Hub] Service Worker registered:', registration.scope);

            // Check for updates
            registration.addEventListener('updatefound', () => {
                const newWorker = registration.installing;
                console.log('[Media Hub] Service Worker updating...');

                newWorker.addEventListener('statechange', () => {
                    if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                        showToast('Update available! Refresh to get the latest version.', 'info');
                    }
                });
            });
        } catch (error) {
            console.error('[Media Hub] Service Worker registration failed:', error);
        }
    });
}

// Detect TV mode (Fire TV, Android TV)
function detectTVMode() {
    const isTV = /AFT|AFTB|AFTT|AFTS|AFTM|FireTV|Roku|CrKey|AppleTV|BRAVIA|Tizen|WebOS|SmartTV/i.test(navigator.userAgent);
    const isLargeScreen = window.innerWidth >= 960;
    const hasNoPointer = !window.matchMedia('(hover: hover)').matches;

    if (isTV || (isLargeScreen && hasNoPointer)) {
        document.body.classList.add('tv-mode');
        enableTVNavigation();
        console.log('[Media Hub] TV mode enabled');
    }
}

function enableTVNavigation() {
    // Make all interactive elements focusable
    document.querySelectorAll('.poster-card, .collection-card, .continue-card, .media-card, .nav-tab, .btn, .filter-chip').forEach(el => {
        if (!el.hasAttribute('tabindex')) {
            el.setAttribute('tabindex', '0');
        }
    });

    // Enhanced keyboard navigation for TV remotes
    document.addEventListener('keydown', (e) => {
        const focused = document.activeElement;

        // Handle OK/Enter on remote
        if (e.key === 'Enter' && focused) {
            if (focused.classList.contains('poster-card') || focused.classList.contains('collection-card')) {
                focused.click();
            }
        }

        // Handle Back button on remote
        if (e.key === 'Escape' || e.key === 'GoBack' || e.keyCode === 10009) {
            const panel = document.getElementById('mediaPanel');
            if (panel && panel.classList.contains('open')) {
                closeMediaPanel();
                e.preventDefault();
            }
        }
    });
}

// PWA Install prompt handling
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    console.log('[Media Hub] Install prompt available');

    // Show the install button in header
    showInstallButton();

    // Don't show banner immediately on TV
    if (!document.body.classList.contains('tv-mode')) {
        setTimeout(() => showInstallBanner(), 3000);
    }
});

// Show install button in header
function showInstallButton() {
    const btn = document.getElementById('installAppBtn');
    if (btn && deferredPrompt) {
        btn.style.display = 'flex';
        // Re-initialize lucide icon
        lucide.createIcons({ icons: { download: lucide.icons.download }, attrs: {} });
        // Add pulse animation after a short delay
        setTimeout(() => btn.classList.add('pulse'), 500);
    }
}

// Hide install button
function hideInstallButton() {
    const btn = document.getElementById('installAppBtn');
    if (btn) {
        btn.style.display = 'none';
        btn.classList.remove('pulse');
    }
}

function showInstallBanner() {
    if (!deferredPrompt) return;

    // Check if already dismissed
    if (localStorage.getItem('media-hub-install-dismissed')) return;

    // Check if already installed
    if (window.matchMedia('(display-mode: standalone)').matches) return;

    // Build banner using DOM methods
    const banner = document.createElement('div');
    banner.className = 'pwa-install-banner';

    const iconDiv = document.createElement('div');
    iconDiv.className = 'pwa-install-icon';
    const iconEl = document.createElement('i');
    iconEl.setAttribute('data-lucide', 'download');
    iconDiv.appendChild(iconEl);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'pwa-install-content';
    const title = document.createElement('h3');
    title.className = 'pwa-install-title';
    title.textContent = 'Install Media Hub';
    const text = document.createElement('p');
    text.className = 'pwa-install-text';
    text.textContent = 'Add to your home screen for quick access';
    contentDiv.appendChild(title);
    contentDiv.appendChild(text);

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'pwa-install-actions';
    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'pwa-install-btn secondary';
    dismissBtn.textContent = 'Not now';
    dismissBtn.addEventListener('click', dismissInstallBanner);
    const installBtn = document.createElement('button');
    installBtn.className = 'pwa-install-btn primary';
    installBtn.textContent = 'Install';
    installBtn.addEventListener('click', installPWA);
    actionsDiv.appendChild(dismissBtn);
    actionsDiv.appendChild(installBtn);

    banner.appendChild(iconDiv);
    banner.appendChild(contentDiv);
    banner.appendChild(actionsDiv);

    document.body.appendChild(banner);
    lucide.createIcons({ icons: { download: lucide.icons.download }, attrs: {} });

    setTimeout(() => banner.classList.add('show'), 100);
}

function dismissInstallBanner() {
    const banner = document.querySelector('.pwa-install-banner');
    if (banner) {
        banner.classList.remove('show');
        setTimeout(() => banner.remove(), 400);
    }
    localStorage.setItem('media-hub-install-dismissed', 'true');
}

async function installPWA() {
    if (!deferredPrompt) {
        showToast('Install not available - try browser menu', 'info');
        return;
    }

    const banner = document.querySelector('.pwa-install-banner');
    if (banner) {
        banner.classList.remove('show');
        setTimeout(() => banner.remove(), 400);
    }

    try {
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;

        if (outcome === 'accepted') {
            showToast('Media Hub installed successfully!', 'success');
            console.log('[Media Hub] PWA installed');
            hideInstallButton();
        } else {
            console.log('[Media Hub] PWA install declined');
        }

        deferredPrompt = null;
    } catch (error) {
        console.error('[Media Hub] Install error:', error);
        showToast('Installation failed', 'error');
    }
}

// Listen for successful install
window.addEventListener('appinstalled', () => {
    console.log('[Media Hub] PWA was installed');
    deferredPrompt = null;
    hideInstallButton();
    showToast('Media Hub installed!', 'success');
});

// Initialize TV mode detection on load
document.addEventListener('DOMContentLoaded', () => {
    detectTVMode();

    // Hide install button if already in standalone mode (app already installed)
    if (window.matchMedia('(display-mode: standalone)').matches) {
        hideInstallButton();
        console.log('[Media Hub] Running in standalone mode - already installed');
    }
});
