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
    initSortDropdowns();
    initViewToggles();
    initGenreFilters();
    initKeyboardNavigation();
    initLazyLoading();
    initTrendingTabs();
    checkTMDBStatus();
    loadPrimaryMediaServer();
    loadDashboard();
    loadSettings();

    // Allow M.A.V.E.N. pages (and any external link) to deep-link into a tab
    // via ?tab=movies, ?tab=requests, etc.
    const urlTab = new URLSearchParams(window.location.search).get('tab');
    if (urlTab) switchTab(urlTab);
});

// Sort dropdown initialization
let currentMovieSort = 'added';
let currentShowSort = 'added';

// View mode state (grid or list)
let currentMovieView = 'grid';
let currentShowView = 'grid';

// Genre filter state
let currentMovieGenre = 'all';
let currentShowGenre = 'all';
let allMoviesCache = [];
let allShowsCache = [];

function initSortDropdowns() {
    const movieSort = document.getElementById('movieSort');
    const showSort = document.getElementById('showSort');

    if (movieSort) {
        movieSort.addEventListener('change', (e) => {
            currentMovieSort = e.target.value;
            loadMovies();
        });
    }

    if (showSort) {
        showSort.addEventListener('change', (e) => {
            currentShowSort = e.target.value;
            loadShows();
        });
    }
}

function initViewToggles() {
    // Movies tab view toggle
    const movieViewBtns = document.querySelectorAll('#tab-movies .view-btn');
    movieViewBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            if (view === currentMovieView) return;

            currentMovieView = view;
            movieViewBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const grid = document.getElementById('moviesGrid');
            if (grid) {
                grid.className = view === 'list' ? 'media-list' : 'media-grid';
            }
            loadMovies();
        });
    });

    // TV Shows tab view toggle
    const showViewBtns = document.querySelectorAll('#tab-shows .view-btn');
    showViewBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            if (view === currentShowView) return;

            currentShowView = view;
            showViewBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const grid = document.getElementById('showsGrid');
            if (grid) {
                grid.className = view === 'list' ? 'media-list' : 'media-grid';
            }
            loadShows();
        });
    });
}

function initGenreFilters() {
    // Movie genre filter clicks
    const movieFilters = document.getElementById('movieGenreFilters');
    if (movieFilters) {
        movieFilters.addEventListener('click', (e) => {
            const chip = e.target.closest('.filter-chip');
            if (!chip) return;

            const genre = chip.dataset.genre;
            if (genre === currentMovieGenre) return;

            currentMovieGenre = genre;
            movieFilters.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            renderFilteredMovies();
        });
    }

    // Show genre filter clicks
    const showFilters = document.getElementById('showGenreFilters');
    if (showFilters) {
        showFilters.addEventListener('click', (e) => {
            const chip = e.target.closest('.filter-chip');
            if (!chip) return;

            const genre = chip.dataset.genre;
            if (genre === currentShowGenre) return;

            currentShowGenre = genre;
            showFilters.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            renderFilteredShows();
        });
    }
}

function populateGenreFilters(items, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Extract unique genres
    const genreSet = new Set();
    items.forEach(item => {
        (item.genres || []).forEach(g => genreSet.add(g));
    });

    // Sort genres alphabetically
    const genres = Array.from(genreSet).sort();

    // Keep the "All" button, add genre buttons
    container.innerHTML = '<button class="filter-chip active" data-genre="all">All</button>';

    genres.forEach(genre => {
        const chip = document.createElement('button');
        chip.className = 'filter-chip';
        chip.dataset.genre = genre;
        chip.textContent = genre;
        container.appendChild(chip);
    });
}

function renderFilteredMovies() {
    const grid = document.getElementById('moviesGrid');
    if (!grid || allMoviesCache.length === 0) return;

    grid.textContent = '';
    grid.className = currentMovieView === 'list' ? 'media-list' : 'media-grid';

    const filtered = currentMovieGenre === 'all'
        ? allMoviesCache
        : allMoviesCache.filter(m => (m.genres || []).includes(currentMovieGenre));

    if (filtered.length === 0) {
        grid.appendChild(createEmptyState('film', `No ${currentMovieGenre} movies found`));
    } else {
        const createCard = currentMovieView === 'list' ? createListCard : createPosterCard;
        filtered.forEach(item => grid.appendChild(createCard(item)));
    }
    lucide.createIcons();
}

function renderFilteredShows() {
    const grid = document.getElementById('showsGrid');
    if (!grid || allShowsCache.length === 0) return;

    grid.textContent = '';
    grid.className = currentShowView === 'list' ? 'media-list' : 'media-grid';

    const filtered = currentShowGenre === 'all'
        ? allShowsCache
        : allShowsCache.filter(s => (s.genres || []).includes(currentShowGenre));

    if (filtered.length === 0) {
        grid.appendChild(createEmptyState('tv', `No ${currentShowGenre} shows found`));
    } else {
        const createCard = currentShowView === 'list' ? createListCard : createPosterCard;
        filtered.forEach(item => grid.appendChild(createCard(item)));
    }
    lucide.createIcons();
}

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

function _activateLcarsTab(tabId) {
    document.querySelectorAll('.lcars-header-tab').forEach(t => t.classList.remove('active'));
    const t = document.querySelector(`.lcars-header-tab[data-tab="${tabId}"]`);
    if (t) t.classList.add('active');
}

// Bridge for LCARS header tab buttons (onclick="lcarsHeaderSwitchTab(id)")
window.lcarsHeaderSwitchTab = function(tabId) {
    if (tabId === 'discover') { window.location.href = '/maven/discover'; return; }
    if (tabId === 'chat')     { window.location.href = '/maven/chat';     return; }
    _activateLcarsTab(tabId);
    switchTab(tabId);
};

function switchTab(tabId) {
    if (tabId === 'discover') { window.location.href = '/maven/discover'; return; }
    if (tabId === 'chat')     { window.location.href = '/maven/chat';     return; }
    focusedIndex = -1; // Reset keyboard focus

    _activateLcarsTab(tabId);
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    const targetTab = document.querySelector(`.nav-tab[data-tab="${tabId}"]`);
    if (targetTab) targetTab.classList.add('active');

    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    const targetPanel = document.getElementById(`tab-${tabId}`);
    if (targetPanel) targetPanel.classList.add('active');

    currentTab = tabId;

    // Stop download refresh when leaving dashboard
    if (tabId !== 'dashboard') {
        stopDownloadRefresh();
    }

    switch(tabId) {
        case 'dashboard':
            // Refresh downloads when returning to dashboard
            loadDownloads();
            break;
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
        case 'requests':
            loadRequests();
            break;
        case 'calendar':
            loadCalendar();
            break;
        case 'stats':
            loadStatistics(); // cache-first: render cached instantly, refresh in background
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
    loadWatchHistory();
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

        // Load trending immediately if TMDB is configured
        if (tmdbConfigured) {
            // Ensure "All" tab is active
            const allTab = document.querySelector('.trending-tab[data-type="all"]');
            if (allTab && !allTab.classList.contains('active')) {
                document.querySelectorAll('.trending-tab').forEach(t => t.classList.remove('active'));
                allTab.classList.add('active');
            }
            loadTrending('all');
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

async function loadWatchHistory() {
    const container = document.getElementById('watchHistory');
    const section = document.getElementById('watchHistorySection');
    if (!container) return;

    const renderItems = (items) => {
        container.textContent = '';
        if (items && items.length > 0) {
            items.forEach(item => {
                container.appendChild(createWatchHistoryCard(item));
            });
            lucide.createIcons();
            if (section) section.style.display = 'block';
        } else {
            if (section) section.style.display = 'none';
        }
    };

    // Load from cache first
    const cached = cacheGet('watch-history');
    if (cached && cached.data) {
        renderItems(cached.data);
    }

    try {
        const response = await fetch(`${API_BASE}/library/history?limit=12`);
        const data = await response.json();

        if (data.success && data.items && data.items.length > 0) {
            renderItems(data.items);
            cacheSet('watch-history', data.items);
        } else if (!cached) {
            if (section) section.style.display = 'none';
        }
    } catch (error) {
        if (!cached && section) {
            section.style.display = 'none';
        }
    }
}

function createWatchHistoryCard(item) {
    const card = document.createElement('div');
    card.className = 'poster-card';
    card.onclick = () => openMediaDetails(item);

    // Image container
    const imgContainer = document.createElement('div');
    imgContainer.className = 'poster-image';

    // Lazy-loaded image
    const img = document.createElement('img');
    img.className = 'lazy-image';
    img.alt = item.title || '';
    img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 450"%3E%3Crect fill="%231a1a2e" width="300" height="450"/%3E%3C/svg%3E';
    img.dataset.src = item.poster_url || '/static/img/no-poster.png';
    img.onerror = function() { this.src = '/static/img/no-poster.png'; };
    lazyLoadImage(img);
    imgContainer.appendChild(img);

    // Watched badge (blue eye - top left) - always show for watch history
    const watchedBadge = document.createElement('span');
    watchedBadge.className = 'poster-badge badge-watched';
    const eyeIcon = document.createElement('i');
    eyeIcon.setAttribute('data-lucide', 'eye');
    watchedBadge.appendChild(eyeIcon);
    imgContainer.appendChild(watchedBadge);

    // Series name overlay for episodes
    if (item.media_type === 'episode' && item.metadata?.show_title) {
        const seriesOverlay = document.createElement('div');
        seriesOverlay.className = 'poster-series-overlay';
        seriesOverlay.textContent = item.metadata.show_title;
        imgContainer.appendChild(seriesOverlay);
    }

    const info = document.createElement('div');
    info.className = 'poster-info';

    const title = document.createElement('div');
    title.className = 'poster-title';
    if (item.media_type === 'episode') {
        title.textContent = item.title || `S${item.season_number}E${item.episode_number}`;
    } else {
        title.textContent = item.title;
    }

    const meta = document.createElement('div');
    meta.className = 'poster-meta';
    if (item.media_type === 'episode' && item.season_number && item.episode_number) {
        meta.textContent = `S${item.season_number}E${item.episode_number}`;
    } else if (item.year) {
        meta.textContent = item.year;
    }

    info.appendChild(title);
    info.appendChild(meta);

    card.appendChild(imgContainer);
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

    const renderTrending = (items) => {
        container.textContent = '';
        if (items && items.length > 0) {
            items.slice(0, 12).forEach(item => {
                container.appendChild(createPosterCard(item, true));
            });
            if (section) section.style.display = 'block';
            lucide.createIcons();
        } else {
            if (section) section.style.display = 'none';
        }
    };

    // Load from cache first for instant display
    const cacheKey = `trending-${type}`;
    const cached = cacheGet(cacheKey, 1800000); // 30 min cache for trending
    if (cached && cached.data) {
        renderTrending(cached.data);
        console.log(`[Media Hub] Trending '${type}' loaded from cache`);
    }

    // Fetch fresh data
    try {
        const response = await fetch(`${API_BASE}/tmdb/trending?type=${type}&window=week`);
        const data = await response.json();

        if (data.success && data.items && data.items.length > 0) {
            renderTrending(data.items);
            cacheSet(cacheKey, data.items);
        } else if (!cached) {
            if (section) section.style.display = 'none';
        }
    } catch (error) {
        console.error('Trending load error:', error);
        if (!cached && section) section.style.display = 'none';
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
    img.dataset.src = item.poster_url || '';
    img.onerror = function() { this.style.opacity = '0'; };

    if (img.dataset.src) lazyLoadImage(img);
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

    // Watched badge (blue eye - top left) - only if played
    if (item.played || item.metadata?.played) {
        const watchedBadge = document.createElement('div');
        watchedBadge.className = 'library-badge badge-watched';
        const eyeIcon = document.createElement('i');
        eyeIcon.setAttribute('data-lucide', 'eye');
        watchedBadge.appendChild(eyeIcon);
        imgContainer.appendChild(watchedBadge);
    }

    // Series name overlay for episodes/shows in recently added
    if ((item.media_type === 'episode' || item.media_type === 'show') && item.metadata?.show_title) {
        const seriesOverlay = document.createElement('div');
        seriesOverlay.className = 'poster-series-overlay';
        seriesOverlay.textContent = item.metadata.show_title;
        imgContainer.appendChild(seriesOverlay);
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
// LIST CARDS (Detail View)
// ─────────────────────────────────────────────────────────────────────────────

function createListCard(item) {
    const card = document.createElement('div');
    card.className = 'list-card';
    card.onclick = () => openMediaDetails(item);

    // Poster thumbnail
    const posterContainer = document.createElement('div');
    posterContainer.className = 'list-card-poster';

    const img = document.createElement('img');
    img.className = 'lazy-image';
    img.alt = item.title || '';
    img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 90"%3E%3Crect fill="%231a1a2e" width="60" height="90"/%3E%3C/svg%3E';
    img.dataset.src = item.poster_url || '/static/img/no-poster.png';
    img.onerror = function() { this.src = '/static/img/no-poster.png'; };
    lazyLoadImage(img);
    posterContainer.appendChild(img);

    // Watched indicator
    if (item.played || item.metadata?.played) {
        const watchedDot = document.createElement('div');
        watchedDot.className = 'list-card-watched';
        const eyeIcon = document.createElement('i');
        eyeIcon.setAttribute('data-lucide', 'eye');
        watchedDot.appendChild(eyeIcon);
        posterContainer.appendChild(watchedDot);
    }

    card.appendChild(posterContainer);

    // Info section
    const info = document.createElement('div');
    info.className = 'list-card-info';

    // Title row
    const titleRow = document.createElement('div');
    titleRow.className = 'list-card-title-row';

    const title = document.createElement('h3');
    title.className = 'list-card-title';
    title.textContent = item.title || 'Unknown';
    titleRow.appendChild(title);

    // Quality badges inline with title
    const badges = item.metadata?.quality_badges || [];
    if (badges.length > 0) {
        const badgeContainer = document.createElement('div');
        badgeContainer.className = 'list-card-badges';
        badges.slice(0, 3).forEach(badge => {
            const badgeEl = document.createElement('span');
            badgeEl.className = 'quality-badge';
            if (badge === '4K') badgeEl.classList.add('badge-4k');
            else if (badge === 'DV' || badge.includes('HDR')) badgeEl.classList.add('badge-hdr');
            else if (badge === 'Atmos' || badge === 'DTS:X') badgeEl.classList.add('badge-audio');
            badgeEl.textContent = badge;
            badgeContainer.appendChild(badgeEl);
        });
        titleRow.appendChild(badgeContainer);
    }

    info.appendChild(titleRow);

    // Meta row (year, type, rating, runtime)
    const meta = document.createElement('div');
    meta.className = 'list-card-meta';
    const parts = [];
    if (item.year) parts.push(item.year);
    if (item.media_type) parts.push(item.media_type === 'movie' ? 'Movie' : 'TV Series');
    if (item.runtime_minutes) parts.push(`${item.runtime_minutes} min`);
    if (item.rating) parts.push(`★ ${Number(item.rating).toFixed(1)}`);
    meta.textContent = parts.join(' • ');
    info.appendChild(meta);

    // Overview/description
    if (item.overview) {
        const overview = document.createElement('p');
        overview.className = 'list-card-overview';
        overview.textContent = item.overview.length > 200
            ? item.overview.substring(0, 200) + '...'
            : item.overview;
        info.appendChild(overview);
    }

    // Genres
    if (item.genres && item.genres.length > 0) {
        const genres = document.createElement('div');
        genres.className = 'list-card-genres';
        item.genres.slice(0, 4).forEach(genre => {
            const tag = document.createElement('span');
            tag.className = 'genre-tag';
            tag.textContent = genre;
            genres.appendChild(tag);
        });
        info.appendChild(genres);
    }

    card.appendChild(info);

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'list-card-actions';

    // Play button
    const playBtn = document.createElement('button');
    playBtn.className = 'list-card-play';
    playBtn.onclick = (e) => {
        e.stopPropagation();
        if (item.in_library && (item.media_type === 'movie' || item.media_type === 'episode')) {
            openVideoPlayer(item);
        } else {
            openMediaDetails(item);
        }
    };
    const playIcon = document.createElement('i');
    playIcon.setAttribute('data-lucide', item.in_library ? 'play' : 'info');
    playBtn.appendChild(playIcon);
    actions.appendChild(playBtn);

    card.appendChild(actions);

    return card;
}

// ─────────────────────────────────────────────────────────────────────────────
// DOWNLOADS WITH CONTROLS
// ─────────────────────────────────────────────────────────────────────────────

let downloadRefreshInterval = null;
const DOWNLOAD_REFRESH_RATE = 5000; // Refresh every 5 seconds

function startDownloadRefresh() {
    if (!downloadRefreshInterval) {
        downloadRefreshInterval = setInterval(loadDownloads, DOWNLOAD_REFRESH_RATE);
    }
}

function stopDownloadRefresh() {
    if (downloadRefreshInterval) {
        clearInterval(downloadRefreshInterval);
        downloadRefreshInterval = null;
    }
}

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
            // Start auto-refresh when downloads are active
            startDownloadRefresh();
        } else {
            const empty = document.createElement('div');
            empty.className = 'download-empty';
            empty.textContent = 'No active downloads';
            container.appendChild(empty);
            // Stop auto-refresh when no downloads
            stopDownloadRefresh();
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

    if (ep.overview) {
        const overview = document.createElement('div');
        overview.className = 'episode-overview';
        overview.textContent = ep.overview.length > 180 ? ep.overview.substring(0, 180) + '…' : ep.overview;
        info.appendChild(overview);
    }

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

// Calendar view state
let calendarViewMode = 'week'; // 'week' or 'month'
let calendarMonthOffset = 0;   // For month navigation

function setCalendarView(mode) {
    calendarViewMode = mode;

    // Update toggle buttons
    document.querySelectorAll('.calendar-view-toggle .view-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === mode);
    });

    // Show/hide views
    const weekView = document.getElementById('calendarWeekView');
    const monthView = document.getElementById('calendarMonthView');

    if (weekView && monthView) {
        weekView.classList.toggle('hidden', mode !== 'week');
        monthView.classList.toggle('hidden', mode !== 'month');
    }

    // Reset offsets when switching
    if (mode === 'week') {
        calendarWeekOffset = 0;
    } else {
        calendarMonthOffset = 0;
    }

    loadCalendar();
    lucide.createIcons();
}

function changeCalendarPeriod(direction) {
    if (calendarViewMode === 'week') {
        calendarWeekOffset += direction;
    } else {
        calendarMonthOffset += direction;
    }
    loadCalendar();
}

function goToToday() {
    calendarWeekOffset = 0;
    calendarMonthOffset = 0;
    loadCalendar();
}

function updateCalendarRange() {
    const rangeEl = document.getElementById('calendarRange');
    if (!rangeEl) return;

    if (calendarViewMode === 'week') {
        const today = new Date();
        const startDate = new Date(today);
        startDate.setDate(startDate.getDate() + (calendarWeekOffset * 7));

        const endDate = new Date(startDate);
        endDate.setDate(endDate.getDate() + 6);

        if (calendarWeekOffset === 0) {
            rangeEl.textContent = 'This Week';
        } else if (calendarWeekOffset === 1) {
            rangeEl.textContent = 'Next Week';
        } else if (calendarWeekOffset === -1) {
            rangeEl.textContent = 'Last Week';
        } else {
            const options = { month: 'short', day: 'numeric' };
            rangeEl.textContent = `${startDate.toLocaleDateString('en-US', options)} - ${endDate.toLocaleDateString('en-US', options)}`;
        }
    } else {
        // Month view
        const today = new Date();
        const targetMonth = new Date(today.getFullYear(), today.getMonth() + calendarMonthOffset, 1);
        rangeEl.textContent = targetMonth.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    }
}

async function loadCalendar() {
    updateCalendarRange();

    if (calendarViewMode === 'week') {
        await loadWeekView();
    } else {
        await loadMonthView();
    }
}

// Render the 7-day week grid from a list of episodes (pure DOM build, for the
// CURRENT calendarWeekOffset). Extracted so loadWeekView can paint from cache. #4772.
function renderWeek(episodes) {
    const container = document.getElementById('calendarGrid');
    if (!container) return;
    const today = new Date();
    const startDate = new Date(today);
    startDate.setDate(startDate.getDate() + (calendarWeekOffset * 7));
    const todayStr = today.toISOString().split('T')[0];

    const grouped = {};
    (episodes || []).forEach(ep => {
        const date = ep.air_date || 'Unknown';
        if (!grouped[date]) grouped[date] = [];
        grouped[date].push(ep);
    });

    container.textContent = '';
    for (let i = 0; i < 7; i++) {
        const cellDate = new Date(startDate);
        cellDate.setDate(cellDate.getDate() + i);
        const dateStr = cellDate.toISOString().split('T')[0];
        const dayEpisodes = grouped[dateStr] || [];

        const daySection = document.createElement('div');
        daySection.className = 'calendar-day' + (dateStr === todayStr ? ' today' : '');

        const dayHeader = document.createElement('div');
        dayHeader.className = 'calendar-day-header';
        dayHeader.innerHTML = `<div>${cellDate.toLocaleDateString('en-US', { weekday: 'short' })}</div>
                               <div>${cellDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div>`;
        daySection.appendChild(dayHeader);

        const dayContent = document.createElement('div');
        dayContent.className = 'calendar-day-content';
        if (dayEpisodes.length > 0) {
            dayEpisodes.forEach(ep => dayContent.appendChild(createCalendarEpisode(ep)));
        } else {
            const empty = document.createElement('div');
            empty.className = 'calendar-empty';
            empty.textContent = 'No episodes';
            dayContent.appendChild(empty);
        }

        daySection.appendChild(dayContent);
        container.appendChild(daySection);
    }
    lucide.createIcons();
}

async function loadWeekView() {
    const container = document.getElementById('calendarGrid');
    if (!container) return;

    const startDate = new Date();
    startDate.setDate(startDate.getDate() + (calendarWeekOffset * 7));
    const startStr = startDate.toISOString().split('T')[0];
    const cacheKey = 'calendar-week-' + startStr;

    // Cache-first (stale-while-revalidate): paint the last-known episodes for THIS week
    // from localStorage INSTANTLY (no "Loading calendar..." flash), then refresh and only
    // re-render if changed. Per-week cache key so navigation stays correct. #4772.
    const cachedW = cacheGet(cacheKey);
    const hadCache = !!(cachedW && Array.isArray(cachedW.data));
    if (hadCache) {
        renderWeek(cachedW.data);
        container.dataset.mhSig = JSON.stringify(cachedW.data);
    } else {
        container.innerHTML = '<div class="calendar-loading"><div class="loading-pulse"></div><span>Loading calendar...</span></div>';
    }

    try {
        const response = await fetch(`${API_BASE}/calendar/upcoming?days=7&start=${startStr}`);
        const data = await response.json();
        if (data.success) {
            const eps = data.episodes || [];
            cacheSet(cacheKey, eps);
            const sig = JSON.stringify(eps);
            if (sig !== container.dataset.mhSig) {
                renderWeek(eps);
                container.dataset.mhSig = sig;
            }
        } else if (!hadCache) {
            renderWeek([]); // still show the empty 7-day grid
        }
    } catch (error) {
        // Keep any cached render on error rather than blanking.
        if (!hadCache) {
            container.textContent = '';
            container.appendChild(createEmptyState('alert-circle', 'Failed to load calendar'));
            lucide.createIcons();
        }
    }
}

// Month-grid geometry for the CURRENT calendarMonthOffset (start-of-grid + total days).
function _monthGridRange() {
    const today = new Date();
    const targetMonth = new Date(today.getFullYear(), today.getMonth() + calendarMonthOffset, 1);
    const year = targetMonth.getFullYear();
    const month = targetMonth.getMonth();
    const firstDayOfMonth = new Date(year, month, 1);
    const lastDayOfMonth = new Date(year, month + 1, 0);
    const startOfGrid = new Date(firstDayOfMonth);
    startOfGrid.setDate(startOfGrid.getDate() - firstDayOfMonth.getDay());
    const endOfGrid = new Date(lastDayOfMonth);
    endOfGrid.setDate(endOfGrid.getDate() + (6 - lastDayOfMonth.getDay()));
    const totalDays = Math.ceil((endOfGrid - startOfGrid) / (1000 * 60 * 60 * 24)) + 1;
    return { today, month, startOfGrid, totalDays, startStr: startOfGrid.toISOString().split('T')[0] };
}

// Render the month grid from a list of episodes (pure DOM build). Extracted so
// loadMonthView can paint from cache. #4772.
function renderMonth(episodes) {
    const container = document.getElementById('monthGrid');
    if (!container) return;
    const { today, month, startOfGrid, totalDays } = _monthGridRange();
    const todayStr = today.toISOString().split('T')[0];

    const episodesByDate = {};
    (episodes || []).forEach(ep => {
        const date = ep.air_date || '';
        if (date) {
            if (!episodesByDate[date]) episodesByDate[date] = [];
            episodesByDate[date].push(ep);
        }
    });

    container.textContent = '';
    for (let i = 0; i < totalDays; i++) {
        const cellDate = new Date(startOfGrid);
        cellDate.setDate(cellDate.getDate() + i);
        const dateStr = cellDate.toISOString().split('T')[0];
        const isOtherMonth = cellDate.getMonth() !== month;
        const isToday = dateStr === todayStr;
        const cellEpisodes = episodesByDate[dateStr] || [];

        const cell = document.createElement('div');
        cell.className = 'month-cell';
        if (isOtherMonth) cell.classList.add('other-month');
        if (isToday) cell.classList.add('today');
        if (cellEpisodes.length > 0) cell.classList.add('has-episodes');

        const dateNum = document.createElement('div');
        dateNum.className = 'month-cell-date';
        dateNum.textContent = cellDate.getDate();
        cell.appendChild(dateNum);

        if (cellEpisodes.length > 0) {
            const epList = document.createElement('div');
            epList.className = 'month-cell-episodes';
            const maxShow = 3;
            cellEpisodes.slice(0, maxShow).forEach(ep => {
                const epEl = document.createElement('div');
                epEl.className = 'month-episode ' + (ep.has_file ? 'has-file' : 'no-file');
                epEl.textContent = ep.series_title || 'Unknown';
                epEl.title = `${ep.series_title} S${ep.season_number}E${ep.episode_number}`;
                epEl.onclick = () => showDayDetail(dateStr, cellEpisodes);
                epList.appendChild(epEl);
            });
            if (cellEpisodes.length > maxShow) {
                const more = document.createElement('div');
                more.className = 'month-cell-more';
                more.textContent = `+${cellEpisodes.length - maxShow} more`;
                more.onclick = () => showDayDetail(dateStr, cellEpisodes);
                epList.appendChild(more);
            }
            cell.appendChild(epList);
        }

        cell.onclick = (e) => {
            if ((e.target === cell || e.target === dateNum) && cellEpisodes.length > 0) {
                showDayDetail(dateStr, cellEpisodes);
            }
        };

        container.appendChild(cell);
    }
    lucide.createIcons();
}

async function loadMonthView() {
    const container = document.getElementById('monthGrid');
    if (!container) return;

    const { totalDays, startStr } = _monthGridRange();
    const cacheKey = 'calendar-month-' + startStr;

    // Cache-first (stale-while-revalidate): paint the last-known episodes for THIS month
    // grid from localStorage INSTANTLY, then refresh and only re-render if changed. #4772.
    const cachedM = cacheGet(cacheKey);
    const hadCache = !!(cachedM && Array.isArray(cachedM.data));
    if (hadCache) {
        renderMonth(cachedM.data);
        container.dataset.mhSig = JSON.stringify(cachedM.data);
    } else {
        container.innerHTML = '<div class="calendar-loading" style="grid-column: 1/-1;"><div class="loading-pulse"></div><span>Loading calendar...</span></div>';
    }

    try {
        const response = await fetch(`${API_BASE}/calendar/upcoming?days=${totalDays}&start=${startStr}`);
        const data = await response.json();
        if (data.success) {
            const eps = data.episodes || [];
            cacheSet(cacheKey, eps);
            const sig = JSON.stringify(eps);
            if (sig !== container.dataset.mhSig) {
                renderMonth(eps);
                container.dataset.mhSig = sig;
            }
        } else if (!hadCache) {
            renderMonth([]); // still show the empty month grid
        }
    } catch (error) {
        // Keep any cached render on error rather than blanking.
        if (!hadCache) {
            container.textContent = '';
            const errorMsg = document.createElement('div');
            errorMsg.style.cssText = 'grid-column: 1/-1; text-align: center; color: var(--archie-text-muted); padding: 40px;';
            errorMsg.textContent = 'Failed to load calendar';
            container.appendChild(errorMsg);
        }
    }
}

function createCalendarEpisode(ep) {
    const div = document.createElement('div');
    div.className = 'calendar-episode';
    div.onclick = () => openMediaDetails({
        id: ep.series_id,
        title: ep.series_title,
        media_type: 'show',
        poster_url: ep.poster_url
    });

    const poster = document.createElement('img');
    poster.className = 'calendar-ep-poster';
    poster.src = ep.poster_url || '/static/img/no-poster.png';
    poster.alt = '';
    poster.onerror = function() { this.style.display = 'none'; };

    const info = document.createElement('div');
    info.className = 'calendar-ep-info';

    const title = document.createElement('div');
    title.className = 'calendar-ep-title';
    title.textContent = ep.series_title;

    const meta = document.createElement('div');
    meta.className = 'calendar-ep-meta';
    meta.textContent = `S${String(ep.season_number).padStart(2, '0')}E${String(ep.episode_number).padStart(2, '0')}`;

    info.appendChild(title);
    info.appendChild(meta);

    const status = document.createElement('div');
    status.className = 'calendar-ep-status ' + (ep.has_file ? 'available' : 'pending');
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', ep.has_file ? 'check-circle' : 'clock');
    status.appendChild(icon);

    div.appendChild(poster);
    div.appendChild(info);
    div.appendChild(status);

    return div;
}

function showDayDetail(dateStr, episodes) {
    // Remove existing modal
    document.getElementById('dayDetailModal')?.remove();

    const modal = document.createElement('div');
    modal.id = 'dayDetailModal';
    modal.className = 'day-detail-modal';

    const overlay = document.createElement('div');
    overlay.className = 'day-detail-overlay';
    overlay.onclick = () => modal.remove();
    modal.appendChild(overlay);

    const content = document.createElement('div');
    content.className = 'day-detail-content';

    // Header
    const header = document.createElement('div');
    header.className = 'day-detail-header';

    const dateDisplay = new Date(dateStr + 'T00:00:00');
    const title = document.createElement('h3');
    title.textContent = dateDisplay.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
    header.appendChild(title);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'day-detail-close';
    closeBtn.innerHTML = '<i data-lucide="x"></i>';
    closeBtn.onclick = () => modal.remove();
    header.appendChild(closeBtn);

    content.appendChild(header);

    // Episodes list
    const list = document.createElement('div');
    list.className = 'day-detail-list';

    episodes.forEach(ep => {
        list.appendChild(createEpisodeCard(ep));
    });

    content.appendChild(list);
    modal.appendChild(content);
    document.body.appendChild(modal);

    requestAnimationFrame(() => modal.classList.add('active'));
    lucide.createIcons();
}

// Keep old function name for backward compatibility
function changeCalendarWeek(direction) {
    changeCalendarPeriod(direction);
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

    const cardFn = () => (currentMovieView === 'list' ? createListCard : createPosterCard);
    const addLoadMore = (count) => {
        if (count === 200) {
            const loadMore = document.createElement('button');
            loadMore.className = 'load-more-btn';
            loadMore.textContent = 'Load More';
            loadMore.onclick = () => { loadMore.remove(); loadMovies(true); };
            grid.appendChild(loadMore);
        }
    };

    if (!append) {
        grid.textContent = '';
        grid.className = currentMovieView === 'list' ? 'media-list' : 'media-grid';
        moviesOffset = 0;
        currentMovieGenre = 'all'; // Reset genre filter

        // Cache-first (stale-while-revalidate): paint the last-known first page from
        // localStorage INSTANTLY, then refresh below and only re-render if it changed
        // (flash-free). project #385 #4746.
        const cachedM = cacheGet('movies-firstpage');
        if (cachedM && cachedM.data && cachedM.data.length) {
            allMoviesCache = cachedM.data;
            populateGenreFilters(allMoviesCache, 'movieGenreFilters');
            const cc = cardFn();
            cachedM.data.forEach(item => grid.appendChild(cc(item)));
            addLoadMore(cachedM.data.length);
            grid.dataset.mhSig = cachedM.data.map(i => i.id).join(',');
            moviesOffset = cachedM.data.length;
            lucide.createIcons();
        }
    }

    // Blocking spinner ONLY when nothing is on screen (i.e. no cached render).
    let loading = null;
    if (grid.children.length === 0) {
        loading = createLoadingElement('Loading movies...');
        grid.appendChild(loading);
    }

    try {
        const sort = currentMovieSort || 'added';
        const response = await fetch(`${API_BASE}/library/movies?limit=200&offset=${moviesOffset}&sort=${sort}`);
        const data = await response.json();

        if (loading) loading.remove();

        if (data.success && data.items) {
            if (!append) {
                const sig = data.items.map(i => i.id).join(',');
                allMoviesCache = data.items;
                cacheSet('movies-firstpage', data.items);
                if (sig !== grid.dataset.mhSig) {
                    // Fresh differs from the cached render → rebuild the grid.
                    grid.textContent = '';
                    grid.className = currentMovieView === 'list' ? 'media-list' : 'media-grid';
                    populateGenreFilters(allMoviesCache, 'movieGenreFilters');
                    const cc = cardFn();
                    data.items.forEach(item => grid.appendChild(cc(item)));
                    addLoadMore(data.items.length);
                    grid.dataset.mhSig = sig;
                }
                moviesOffset = data.items.length;
            } else {
                allMoviesCache = [...allMoviesCache, ...data.items];
                populateGenreFilters(allMoviesCache, 'movieGenreFilters');
                const cc = cardFn();
                data.items.forEach(item => grid.appendChild(cc(item)));
                moviesOffset += data.items.length;
                addLoadMore(data.items.length);
            }
        }
        lucide.createIcons();
    } catch (error) {
        if (loading) loading.remove();
        // Keep any cached render on error rather than blanking to an error state.
        if (grid.children.length === 0) {
            grid.appendChild(createEmptyState('alert-circle', 'Failed to load movies'));
            lucide.createIcons();
        }
    }
}

async function loadShows(append = false) {
    const grid = document.getElementById('showsGrid');
    if (!grid) return;

    const cardFn = () => (currentShowView === 'list' ? createListCard : createPosterCard);
    const addLoadMore = (count) => {
        if (count === 200) {
            const loadMore = document.createElement('button');
            loadMore.className = 'load-more-btn';
            loadMore.textContent = 'Load More';
            loadMore.onclick = () => { loadMore.remove(); loadShows(true); };
            grid.appendChild(loadMore);
        }
    };

    if (!append) {
        grid.textContent = '';
        grid.className = currentShowView === 'list' ? 'media-list' : 'media-grid';
        showsOffset = 0;
        currentShowGenre = 'all'; // Reset genre filter

        // Cache-first (stale-while-revalidate): paint the last-known first page from
        // localStorage INSTANTLY, then refresh and only re-render if changed. #4746.
        const cachedS = cacheGet('shows-firstpage');
        if (cachedS && cachedS.data && cachedS.data.length) {
            allShowsCache = cachedS.data;
            populateGenreFilters(allShowsCache, 'showGenreFilters');
            const cc = cardFn();
            cachedS.data.forEach(item => grid.appendChild(cc(item)));
            addLoadMore(cachedS.data.length);
            grid.dataset.mhSig = cachedS.data.map(i => i.id).join(',');
            showsOffset = cachedS.data.length;
            lucide.createIcons();
        }
    }

    // Blocking spinner ONLY when nothing is on screen (no cached render).
    let loading = null;
    if (grid.children.length === 0) {
        loading = createLoadingElement('Loading shows...');
        grid.appendChild(loading);
    }

    try {
        const sort = currentShowSort || 'added';
        const response = await fetch(`${API_BASE}/library/shows?limit=200&offset=${showsOffset}&sort=${sort}`);
        const data = await response.json();

        if (loading) loading.remove();

        if (data.success && data.items) {
            if (!append) {
                const sig = data.items.map(i => i.id).join(',');
                allShowsCache = data.items;
                cacheSet('shows-firstpage', data.items);
                if (sig !== grid.dataset.mhSig) {
                    grid.textContent = '';
                    grid.className = currentShowView === 'list' ? 'media-list' : 'media-grid';
                    populateGenreFilters(allShowsCache, 'showGenreFilters');
                    const cc = cardFn();
                    data.items.forEach(item => grid.appendChild(cc(item)));
                    addLoadMore(data.items.length);
                    grid.dataset.mhSig = sig;
                }
                showsOffset = data.items.length;
            } else {
                allShowsCache = [...allShowsCache, ...data.items];
                populateGenreFilters(allShowsCache, 'showGenreFilters');
                const cc = cardFn();
                data.items.forEach(item => grid.appendChild(cc(item)));
                showsOffset += data.items.length;
                addLoadMore(data.items.length);
            }
        }
        lucide.createIcons();
    } catch (error) {
        if (loading) loading.remove();
        if (grid.children.length === 0) {
            grid.appendChild(createEmptyState('alert-circle', 'Failed to load shows'));
            lucide.createIcons();
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// REQUESTS
// ─────────────────────────────────────────────────────────────────────────────

// Requests state
let allRequests = [];
let currentRequestsFilter = 'active';
let currentRequestsLimit = 10;
let queueProgress = {};
let requestRefreshInterval = null;
const REQUEST_REFRESH_RATE = 30000; // 30s — polls while any item is processing

function startRequestRefresh() {
    if (!requestRefreshInterval) {
        requestRefreshInterval = setInterval(loadRequests, REQUEST_REFRESH_RATE);
    }
}

function stopRequestRefresh() {
    if (requestRefreshInterval) {
        clearInterval(requestRefreshInterval);
        requestRefreshInterval = null;
    }
}

async function loadRequests() {
    const container = document.getElementById('requestsList');
    if (!container) return;

    // Cache-first (stale-while-revalidate): paint the last-known requests from
    // localStorage INSTANTLY (no "Loading requests..." flash), then refresh and only
    // re-render if the set changed or live progress needs updating. #4746.
    const sigOf = (reqs) => (reqs || []).map(r => `${r.id}:${r.status}`).join(',');
    const cachedR = cacheGet('requests');
    const hadCache = !!(cachedR && cachedR.data && cachedR.data.length);
    if (hadCache) {
        allRequests = cachedR.data;
        renderFilteredRequests();
        container.dataset.mhSig = sigOf(cachedR.data);
    } else {
        container.textContent = '';
        container.appendChild(createLoadingElement('Loading requests...'));
    }

    try {
        const [response, progressResponse] = await Promise.all([
            fetch(`${API_BASE}/requests`),
            fetch(`${API_BASE}/requests/queue-progress`).catch(() => null)
        ]);
        const data = await response.json();
        if (progressResponse?.ok) {
            const pd = await progressResponse.json();
            if (pd.success) queueProgress = pd.progress || {};
        }

        if (data.success && data.requests) {
            allRequests = data.requests;
            cacheSet('requests', data.requests);
            // Re-render if the fresh set differs from what's on screen, OR whenever live
            // progress is present (progress bars must refresh even if id/status is unchanged).
            const sig = sigOf(data.requests);
            if (sig !== container.dataset.mhSig || Object.keys(queueProgress || {}).length) {
                renderFilteredRequests();
                container.dataset.mhSig = sig;
            }
            // Auto-refresh while any request is in-flight (approved = grabbed by arr,
            // processing = importing, either can transition to available)
            const inFlight = allRequests.some(r => ['processing', 'approved'].includes(r.status));
            inFlight ? startRequestRefresh() : stopRequestRefresh();
        } else if (!hadCache) {
            container.textContent = '';
            container.appendChild(createEmptyState('inbox', 'No media requests'));
        }
        lucide.createIcons();
    } catch (error) {
        // Keep any cached render on error rather than blanking to an error state.
        if (!hadCache) {
            container.textContent = '';
            container.appendChild(createEmptyState('alert-circle', 'Failed to load requests'));
            lucide.createIcons();
        }
    }
}

function filterRequests(status) {
    currentRequestsFilter = status;
    // Update active button
    document.querySelectorAll('#requestsFilterGroup .filter-chip').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.status === status);
    });
    renderFilteredRequests();
}

function setRequestsLimit(limit) {
    currentRequestsLimit = limit;
    // Update active button
    document.querySelectorAll('.limit-btn').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.textContent) === limit);
    });
    renderFilteredRequests();
}

function renderFilteredRequests() {
    const container = document.getElementById('requestsList');
    const summary = document.getElementById('requestsSummary');
    if (!container) return;

    container.textContent = '';

    // Filter based on status
    let filtered = allRequests;
    if (currentRequestsFilter === 'active') {
        // Active = pending, approved, processing (not completed/available)
        filtered = allRequests.filter(r => ['pending', 'approved', 'processing'].includes(r.status));
    } else if (currentRequestsFilter !== 'all') {
        filtered = allRequests.filter(r => r.status === currentRequestsFilter);
    }

    // Update summary — break the blanket "processing" bucket into honest
    // downloading / importing / searching counts so a stalled or import-pending
    // request is never miscounted as an active download (see requestProgressState).
    if (summary) {
        let dl = 0, imp = 0, srch = 0;
        allRequests.filter(r => r.status === 'processing').forEach(r => {
            const st = requestProgressState(r);
            if (!st) return;
            if (st.key === 'downloading') dl++;
            else if (st.key === 'importing') imp++;
            else srch++;
        });
        const counts = {
            pending: allRequests.filter(r => r.status === 'pending').length,
            approved: allRequests.filter(r => r.status === 'approved').length,
            available: allRequests.filter(r => r.status === 'available').length
        };
        const chips = [
            `<span class="summary-item"><span class="dot pending"></span>${counts.pending} pending</span>`,
            `<span class="summary-item"><span class="dot approved"></span>${counts.approved} approved</span>`
        ];
        if (dl)   chips.push(`<span class="summary-item"><span class="dot processing"></span>${dl} downloading</span>`);
        if (imp)  chips.push(`<span class="summary-item"><span class="dot processing"></span>${imp} importing</span>`);
        if (srch) chips.push(`<span class="summary-item"><span class="dot approved"></span>${srch} searching</span>`);
        chips.push(`<span class="summary-item"><span class="dot available"></span>${counts.available} completed</span>`);
        summary.innerHTML = chips.join('\n');
    }

    // Sort and limit
    const statusOrder = ['processing', 'pending', 'approved', 'available', 'declined'];
    const sorted = filtered.sort((a, b) => statusOrder.indexOf(a.status) - statusOrder.indexOf(b.status));
    const limited = sorted.slice(0, currentRequestsLimit);

    if (limited.length > 0) {
        limited.forEach(req => {
            container.appendChild(createRequestCard(req));
        });
        // Show "showing X of Y" if limited
        if (filtered.length > currentRequestsLimit) {
            const more = document.createElement('div');
            more.className = 'requests-more';
            more.textContent = `Showing ${currentRequestsLimit} of ${filtered.length} requests`;
            container.appendChild(more);
        }
    } else {
        container.appendChild(createEmptyState('inbox', 'No requests match this filter'));
    }
    lucide.createIcons();
}

// Derive the REAL sub-state of a 'processing' request from live queue progress.
// Overseerr flips a request to 'processing' the instant it's approved and handed
// to Radarr/Sonarr — long before (or entirely without) an actual download. So a
// flat "Downloading" label lies: an approved-but-not-yet-grabbed item shows
// "Downloading" with no progress bar, and a finished-but-not-imported item shows
// the same. This maps to what is really happening:
//   downloading — bytes are transferring (percent < 100)
//   importing   — download finished, waiting on the library import (importPending)
//   searching   — approved, nothing grabbed yet (no queue entry)
// Returns null for non-processing requests (callers fall back to the flat map).
function requestProgressState(req) {
    if (req.status !== 'processing') return null;
    const p = req.tmdb_id ? queueProgress[String(req.tmdb_id)] : null;
    if (!p) {
        return { key: 'searching', label: 'Searching…', icon: 'search', percent: null };
    }
    const st = String(p.status || '').toLowerCase();
    if (st.indexOf('import') !== -1 || (typeof p.percent === 'number' && p.percent >= 100)) {
        return { key: 'importing', label: 'Importing…', icon: 'folder-input', percent: 100 };
    }
    return {
        key: 'downloading',
        label: 'Downloading',
        icon: 'download',
        percent: (typeof p.percent === 'number' && p.percent >= 0) ? p.percent : null,
        eta: p.eta
    };
}

function createRequestCard(req) {
    const card = document.createElement('div');
    card.className = 'request-card';
    card.style.cursor = 'pointer';
    card.onclick = () => showRequestDetail(req);

    const poster = document.createElement('img');
    poster.className = 'request-poster';
    poster.src = req.poster_url || '';
    poster.alt = '';
    poster.loading = 'lazy';
    poster.onerror = function() { this.style.display = 'none'; };

    const info = document.createElement('div');
    info.className = 'request-info';

    const title = document.createElement('div');
    title.className = 'request-title';
    title.textContent = req.title;

    const meta = document.createElement('div');
    meta.className = 'request-meta';
    const typeIcon = req.media_type === 'movie' ? 'film' : 'tv';
    const runtime = req.runtime_minutes ? ` • ${req.runtime_minutes} min` : '';
    const rating = req.rating ? ` • ⭐ ${req.rating.toFixed(1)}` : '';
    meta.innerHTML = `<i data-lucide="${typeIcon}" style="width:14px;height:14px;display:inline;vertical-align:middle;margin-right:4px;"></i>${req.year || 'N/A'}${runtime}${rating}`;

    // Status badge with icon — for a 'processing' request, show its REAL sub-state
    // (downloading / importing / searching) rather than a blanket "Downloading".
    const status = document.createElement('div');
    status.className = `request-status status-${req.status}`;
    const pstate = requestProgressState(req);
    let sIcon, sLabel;
    if (pstate) {
        sIcon = pstate.icon;
        sLabel = pstate.label;
    } else {
        const statusIcons = {
            'pending': 'clock',
            'approved': 'check',
            'processing': 'download',
            'available': 'check-circle',
            'declined': 'x-circle'
        };
        const statusLabels = {
            'pending': 'Pending',
            'approved': 'Approved',
            'processing': 'Downloading',
            'available': 'Available',
            'declined': 'Declined'
        };
        sIcon = statusIcons[req.status] || 'circle';
        sLabel = statusLabels[req.status] || req.status;
    }
    status.innerHTML = `<i data-lucide="${sIcon}" style="width:12px;height:12px;"></i> ${sLabel}`;

    // Overview preview
    if (req.overview) {
        const overview = document.createElement('div');
        overview.className = 'request-overview';
        overview.textContent = req.overview.length > 220 ? req.overview.substring(0, 220) + '…' : req.overview;
        info.appendChild(overview);
    }

    info.appendChild(title);
    info.appendChild(meta);
    info.appendChild(status);

    // Progress indicator — only render a bar when something is really happening:
    //   downloading → live percent + ETA
    //   importing   → full bar labelled "Importing…" (download done, awaiting import)
    //   searching   → nothing (no fake bar for a request that isn't transferring)
    if (pstate && pstate.key === 'downloading' && pstate.percent !== null) {
        const bar = document.createElement('div');
        bar.className = 'download-progress';
        const fill = document.createElement('div');
        fill.className = 'download-progress-bar';
        fill.style.width = `${pstate.percent}%`;
        bar.appendChild(fill);
        const label = document.createElement('span');
        label.className = 'download-progress-text';
        label.textContent = pstate.eta ? `${pstate.percent}% · ${pstate.eta}` : `${pstate.percent}%`;
        info.appendChild(bar);
        info.appendChild(label);
    } else if (pstate && pstate.key === 'importing') {
        const bar = document.createElement('div');
        bar.className = 'download-progress';
        const fill = document.createElement('div');
        fill.className = 'download-progress-bar';
        fill.style.width = '100%';
        bar.appendChild(fill);
        const label = document.createElement('span');
        label.className = 'download-progress-text';
        label.textContent = 'Importing to library…';
        info.appendChild(bar);
        info.appendChild(label);
    }

    card.appendChild(poster);
    card.appendChild(info);

    return card;
}

function showRequestDetail(req) {
    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.className = 'request-modal-overlay';
    overlay.onclick = (e) => {
        if (e.target === overlay) overlay.remove();
    };

    const modal = document.createElement('div');
    modal.className = 'request-modal';

    // Backdrop
    if (req.backdrop_url) {
        const backdrop = document.createElement('div');
        backdrop.className = 'request-modal-backdrop';
        backdrop.style.backgroundImage = `url(${req.backdrop_url})`;
        modal.appendChild(backdrop);
    }

    // Content
    const content = document.createElement('div');
    content.className = 'request-modal-content';

    // Header with poster and info
    const header = document.createElement('div');
    header.className = 'request-modal-header';

    const poster = document.createElement('img');
    poster.className = 'request-modal-poster';
    poster.src = req.poster_url || '/static/img/no-poster.png';

    const headerInfo = document.createElement('div');
    headerInfo.className = 'request-modal-header-info';

    // Title
    const title = document.createElement('h2');
    title.className = 'request-modal-title';
    title.textContent = req.title;

    // Tagline
    if (req.tagline) {
        const tagline = document.createElement('div');
        tagline.className = 'request-modal-tagline';
        tagline.textContent = `"${req.tagline}"`;
        headerInfo.appendChild(tagline);
    }

    // Meta info row
    const metaRow = document.createElement('div');
    metaRow.className = 'request-modal-meta';

    const badges = [];
    badges.push(`<span class="meta-badge">${req.media_type === 'movie' ? '🎬 Movie' : '📺 TV Show'}</span>`);
    if (req.year) badges.push(`<span class="meta-badge">📅 ${req.year}</span>`);
    if (req.runtime_minutes) badges.push(`<span class="meta-badge">⏱️ ${req.runtime_minutes} min</span>`);
    if (req.rating) badges.push(`<span class="meta-badge">⭐ ${req.rating.toFixed(1)}</span>`);
    metaRow.innerHTML = badges.join('');

    // Genres
    if (req.genres && req.genres.length > 0) {
        const genres = document.createElement('div');
        genres.className = 'request-modal-genres';
        genres.innerHTML = req.genres.map(g => `<span class="genre-tag">${_mhEsc(g)}</span>`).join('');
        headerInfo.appendChild(genres);
    }

    // Status badge — reflect the real sub-state for a 'processing' request.
    const status = document.createElement('div');
    status.className = `request-modal-status status-${req.status}`;
    const mstate = requestProgressState(req);
    if (mstate) {
        const emoji = mstate.key === 'downloading' ? '⬇️' : (mstate.key === 'importing' ? '📥' : '🔎');
        status.textContent = `${emoji} ${mstate.label}`;
    } else {
        const statusLabels = {
            'pending': '⏳ Pending Approval',
            'approved': '✓ Approved',
            'processing': '⬇️ Downloading',
            'available': '✅ Available',
            'declined': '❌ Declined'
        };
        status.textContent = statusLabels[req.status] || req.status;
    }

    headerInfo.appendChild(title);
    headerInfo.appendChild(metaRow);
    headerInfo.appendChild(status);
    header.appendChild(poster);
    header.appendChild(headerInfo);

    // Overview
    const overviewSection = document.createElement('div');
    overviewSection.className = 'request-modal-overview';
    overviewSection.innerHTML = `<h3>Overview</h3><p>${_mhEsc(req.overview) || 'No overview available.'}</p>`;

    // Request details
    const detailsSection = document.createElement('div');
    detailsSection.className = 'request-modal-details';
    detailsSection.innerHTML = `
        <h3>Request Details</h3>
        <div class="detail-row"><span>Requested by:</span> <strong>${_mhEsc(req.requested_by) || 'Unknown'}</strong></div>
        <div class="detail-row"><span>Requested:</span> <strong>${formatDate(req.requested_at)}</strong></div>
        <div class="detail-row"><span>TMDB ID:</span> <strong>${req.tmdb_id || 'N/A'}</strong></div>
        ${req.seasons_requested && req.seasons_requested.length > 0 ?
            `<div class="detail-row"><span>Seasons:</span> <strong>${req.seasons_requested.filter(s => s > 0).join(', ') || 'All'}</strong></div>` : ''}
    `;

    // Library status check section (for non-available items)
    const librarySection = document.createElement('div');
    librarySection.className = 'request-library-status';
    librarySection.innerHTML = '<span class="checking"><i data-lucide="loader" class="spin"></i> Checking library...</span>';

    // Check if item is in library
    if (req.status !== 'available') {
        checkLibraryStatus(req, librarySection);
    }

    // Action buttons
    const actionsSection = document.createElement('div');
    actionsSection.className = 'request-modal-actions';

    // Check Library / Mark Available button (for approved/processing items)
    if (['approved', 'processing', 'pending'].includes(req.status)) {
        const checkBtn = document.createElement('button');
        checkBtn.className = 'btn btn-primary';
        checkBtn.innerHTML = '<i data-lucide="library"></i> Check & Sync Status';
        checkBtn.onclick = async () => {
            checkBtn.disabled = true;
            checkBtn.innerHTML = '<i data-lucide="loader"></i> Checking...';
            try {
                const resp = await fetch(`${API_BASE}/requests/${req.id}/check-library`, { method: 'POST' });
                const result = await resp.json();
                if (result.success) {
                    if (result.in_library) {
                        showToast(`"${req.title}" found in library! Status updated.`, 'success');
                        overlay.remove();
                        loadRequests();
                    } else {
                        showToast(`"${req.title}" not found in library yet`, 'info');
                        checkBtn.disabled = false;
                        checkBtn.innerHTML = '<i data-lucide="library"></i> Check & Sync Status';
                    }
                } else {
                    showToast(result.error || 'Check failed', 'error');
                    checkBtn.disabled = false;
                    checkBtn.innerHTML = '<i data-lucide="library"></i> Check & Sync Status';
                }
            } catch (e) {
                showToast('Failed to check library', 'error');
                checkBtn.disabled = false;
                checkBtn.innerHTML = '<i data-lucide="library"></i> Check & Sync Status';
            }
            lucide.createIcons();
        };
        actionsSection.appendChild(checkBtn);
    }

    // Retry search button (for approved/processing items)
    if (['approved', 'processing'].includes(req.status)) {
        const retryBtn = document.createElement('button');
        retryBtn.className = 'btn btn-secondary';
        retryBtn.innerHTML = '<i data-lucide="refresh-cw"></i> Retry Search';
        retryBtn.onclick = async () => {
            retryBtn.disabled = true;
            retryBtn.innerHTML = '<i data-lucide="loader"></i> Searching...';
            try {
                const resp = await fetch(`${API_BASE}/requests/${req.id}/retry`, { method: 'POST' });
                const result = await resp.json();
                if (result.success) {
                    showToast('Search triggered successfully', 'success');
                } else {
                    showToast(result.error || 'Retry failed', 'error');
                }
            } catch (e) {
                showToast('Failed to trigger search', 'error');
            }
            retryBtn.disabled = false;
            retryBtn.innerHTML = '<i data-lucide="refresh-cw"></i> Retry Search';
            lucide.createIcons();
        };
        actionsSection.appendChild(retryBtn);
    }

    // Delete button
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-danger';
    deleteBtn.innerHTML = '<i data-lucide="trash-2"></i> Delete Request';
    deleteBtn.onclick = async () => {
        if (!confirm(`Delete request for "${req.title}"?`)) return;
        deleteBtn.disabled = true;
        deleteBtn.innerHTML = '<i data-lucide="loader"></i> Deleting...';
        try {
            const resp = await fetch(`${API_BASE}/requests/${req.id}`, { method: 'DELETE' });
            const result = await resp.json();
            if (result.success) {
                showToast('Request deleted', 'success');
                overlay.remove();
                loadRequests(); // Refresh list
            } else {
                showToast(result.error || 'Delete failed', 'error');
                deleteBtn.disabled = false;
                deleteBtn.innerHTML = '<i data-lucide="trash-2"></i> Delete Request';
            }
        } catch (e) {
            showToast('Failed to delete request', 'error');
            deleteBtn.disabled = false;
            deleteBtn.innerHTML = '<i data-lucide="trash-2"></i> Delete Request';
        }
        lucide.createIcons();
    };
    actionsSection.appendChild(deleteBtn);

    // Close button
    const closeBtn = document.createElement('button');
    closeBtn.className = 'request-modal-close';
    closeBtn.innerHTML = '<i data-lucide="x"></i>';
    closeBtn.onclick = () => overlay.remove();

    content.appendChild(header);
    content.appendChild(overviewSection);
    content.appendChild(detailsSection);
    if (req.status !== 'available') {
        content.appendChild(librarySection);
    }
    content.appendChild(actionsSection);
    modal.appendChild(closeBtn);
    modal.appendChild(content);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    lucide.createIcons();

    // Close on escape
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            overlay.remove();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

async function checkLibraryStatus(req, container) {
    try {
        // Search library for this title
        const searchType = req.media_type === 'movie' ? 'movies' : 'shows';
        const response = await fetch(`${API_BASE}/library/${searchType}?limit=200`);
        const data = await response.json();

        if (data.success && data.items) {
            // Check if item exists by title match or TMDB ID
            const found = data.items.find(item => {
                const titleMatch = item.title?.toLowerCase() === req.title?.toLowerCase();
                const tmdbMatch = item.tmdb_id && req.tmdb_id && item.tmdb_id === req.tmdb_id;
                return titleMatch || tmdbMatch;
            });

            if (found) {
                container.innerHTML = `
                    <div class="library-found">
                        <i data-lucide="check-circle"></i>
                        <span><strong>Already in library!</strong> Click "Check & Sync Status" to update Overseerr.</span>
                    </div>
                `;
            } else {
                container.innerHTML = `
                    <div class="library-not-found">
                        <i data-lucide="clock"></i>
                        <span>Not yet in library - waiting for download</span>
                    </div>
                `;
            }
        } else {
            container.innerHTML = '';
        }
        lucide.createIcons();
    } catch (e) {
        container.innerHTML = '';
    }
}

async function requestMedia(item) {
    if (!item.tmdb_id) {
        showToast('Cannot request: TMDB ID not found for this item', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/requests`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                media_type: item.media_type,
                tmdb_id: item.tmdb_id
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

// Subtle "updating…" pill shown while the Stats tab refreshes over cached data.
// Self-contained (creates its own element) so it needs no template/CSS changes.
function setStatsUpdating(on) {
    let badge = document.getElementById('statsUpdatingBadge');
    if (on) {
        if (!badge) {
            const host = document.getElementById('tab-stats') || document.body;
            if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
            badge = document.createElement('div');
            badge.id = 'statsUpdatingBadge';
            badge.textContent = '⟳ Updating…';
            badge.style.cssText = 'position:absolute;top:8px;right:12px;z-index:5;font-size:12px;'
                + 'opacity:0.75;padding:2px 10px;border-radius:12px;background:rgba(0,0,0,0.35);'
                + 'color:var(--archie-text,#cfe);pointer-events:none;';
            host.appendChild(badge);
        }
        badge.style.display = 'block';
    } else if (badge) {
        badge.style.display = 'none';
    }
}

async function loadStatistics(forceRefresh = false) {
    const sections = ['qualityBreakdown', 'featuresGrid', 'storageBreakdown', 'genresBreakdown', 'statsRecentAdditions', 'topRatedGrid'];

    // Cache-first (stale-while-revalidate): render cached data INSTANTLY if present,
    // and only paint "Loading..." on a first-ever load with no cache. forceRefresh
    // still refetches (and bypasses the SERVER cache) but no longer blanks the screen.
    const cached = cacheGet('statistics', 300000); // 5 min freshness window (still returns stale)
    if (cached && cached.data) {
        renderStatistics(cached.data);
        setStatsUpdating(true); // subtle "updating…" while we refresh in the background
    } else {
        sections.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = '<div class="breakdown-placeholder">Loading...</div>';
        });
    }

    // Fetch fresh data in the background
    try {
        const q = forceRefresh ? '?refresh=true' : '';
        const [statsResponse, recentResponse, topRatedResponse] = await Promise.all([
            fetch(`${API_BASE}/stats${q}`),
            fetch(`${API_BASE}/library/recent-activity?days=7`),
            fetch(`${API_BASE}/library/top-rated?limit=10`)
        ]);

        const statsData = await statsResponse.json();
        const recentData = await recentResponse.json();
        const topRatedData = await topRatedResponse.json();

        if (statsData.success) {
            const fullData = {
                ...statsData,
                recent: recentData.success ? recentData : null,
                topRated: topRatedData.success ? topRatedData : null
            };
            renderStatistics(fullData);
            cacheSet('statistics', fullData);
        } else if (!(cached && cached.data)) {
            showStatsError('Statistics unavailable');
        }
    } catch (error) {
        console.error('Failed to load statistics:', error);
        if (!(cached && cached.data)) {
            showStatsError('Failed to load statistics');
        }
    } finally {
        setStatsUpdating(false);
    }
}

function showStatsError(message) {
    const sections = ['qualityBreakdown', 'featuresGrid', 'storageBreakdown', 'genresBreakdown', 'statsRecentAdditions', 'topRatedGrid'];
    sections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = `<div class="breakdown-placeholder">${message}</div>`;
    });
}

function renderStatistics(data) {
    // Update overview cards
    const stats = data.stats || {};
    updateElement('statsTotalMovies', formatNumber(stats.movie_count || 0));
    updateElement('statsTotalShows', formatNumber(stats.show_count || 0));
    updateElement('statsTotalEpisodes', formatNumber(stats.episode_count || 0));
    updateElement('statsTotalStorage', formatBytes(stats.total_size_bytes || 0));

    // Quality breakdown
    renderQualityBreakdown(data.quality_breakdown || {});

    // Premium features
    renderFeaturesGrid(data);

    // Storage breakdown
    renderStorageBreakdown(data.size_breakdown || {});

    // Genre distribution
    renderGenresBreakdown(data.genres || {});

    // Recent additions
    renderRecentAdditions(data.recent);

    // Top rated
    renderTopRated(data.topRated);

    lucide.createIcons();
}

function updateElement(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}

function renderQualityBreakdown(breakdown) {
    const container = document.getElementById('qualityBreakdown');
    if (!container) return;

    const total = Object.values(breakdown).reduce((a, b) => a + b, 0);
    if (total === 0) {
        container.innerHTML = '<div class="breakdown-placeholder">No quality data available</div>';
        return;
    }

    const qualities = ['4K', '1080p', '720p', 'SD'];
    container.innerHTML = '';

    qualities.forEach(quality => {
        const count = breakdown[quality] || 0;
        const percent = total > 0 ? (count / total) * 100 : 0;

        const row = document.createElement('div');
        row.className = 'quality-bar-row';

        row.innerHTML = `
            <span class="quality-bar-label">${quality}</span>
            <div class="quality-bar-container">
                <div class="quality-bar-fill quality-${quality.toLowerCase().replace('p', '')}" style="width: ${percent}%">
                    ${count > 0 && percent >= 8 ? Math.round(percent) + '%' : ''}
                </div>
            </div>
            <span class="quality-bar-count">${count}</span>
        `;
        container.appendChild(row);
    });
}

function renderFeaturesGrid(data) {
    const container = document.getElementById('featuresGrid');
    if (!container) return;

    container.innerHTML = `
        <div class="feature-card">
            <div class="feature-icon hdr">HDR</div>
            <div class="feature-info">
                <span class="feature-value">${data.hdr_count || 0}</span>
                <span class="feature-label">HDR Content</span>
            </div>
        </div>
        <div class="feature-card">
            <div class="feature-icon atmos">DA</div>
            <div class="feature-info">
                <span class="feature-value">${data.atmos_count || 0}</span>
                <span class="feature-label">Dolby Atmos</span>
            </div>
        </div>
        <div class="feature-card">
            <div class="feature-icon dv">DV</div>
            <div class="feature-info">
                <span class="feature-value">${data.dolby_vision_count || 0}</span>
                <span class="feature-label">Dolby Vision</span>
            </div>
        </div>
        <div class="feature-card">
            <div class="feature-icon hd">HD+</div>
            <div class="feature-info">
                <span class="feature-value">${(data.quality_breakdown?.['4K'] || 0) + (data.quality_breakdown?.['1080p'] || 0) + (data.quality_breakdown?.['720p'] || 0)}</span>
                <span class="feature-label">HD or Better</span>
            </div>
        </div>
    `;
}

function renderStorageBreakdown(breakdown) {
    const container = document.getElementById('storageBreakdown');
    if (!container) return;

    const moviesSize = breakdown.movies || 0;
    const showsSize = breakdown.shows || 0;
    const total = moviesSize + showsSize;

    if (total === 0) {
        container.innerHTML = '<div class="breakdown-placeholder">No storage data available</div>';
        return;
    }

    const moviesPercent = (moviesSize / total) * 100;
    const showsPercent = (showsSize / total) * 100;

    container.innerHTML = `
        <div class="storage-bar">
            <div class="storage-segment movies" style="flex: ${moviesPercent}" title="Movies: ${formatBytes(moviesSize)}">
                ${moviesPercent > 15 ? formatBytes(moviesSize) : ''}
            </div>
            <div class="storage-segment shows" style="flex: ${showsPercent}" title="TV Shows: ${formatBytes(showsSize)}">
                ${showsPercent > 15 ? formatBytes(showsSize) : ''}
            </div>
        </div>
        <div class="storage-legend">
            <div class="storage-legend-item">
                <span class="storage-legend-dot movies"></span>
                <span>Movies: ${formatBytes(moviesSize)} (${Math.round(moviesPercent)}%)</span>
            </div>
            <div class="storage-legend-item">
                <span class="storage-legend-dot shows"></span>
                <span>TV Shows: ${formatBytes(showsSize)} (${Math.round(showsPercent)}%)</span>
            </div>
        </div>
    `;
}

function renderGenresBreakdown(genres) {
    const container = document.getElementById('genresBreakdown');
    if (!container) return;

    if (!genres || Object.keys(genres).length === 0) {
        container.innerHTML = '<div class="breakdown-placeholder">No genre data available</div>';
        return;
    }

    // Sort genres by count and take top 8
    const sorted = Object.entries(genres)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8);

    const maxCount = sorted[0]?.[1] || 1;
    container.innerHTML = '';

    sorted.forEach(([genre, count]) => {
        const percent = (count / maxCount) * 100;
        const row = document.createElement('div');
        row.className = 'genre-bar-row';
        row.innerHTML = `
            <span class="genre-label" title="${_mhEsc(genre)}">${_mhEsc(genre)}</span>
            <div class="genre-bar-container">
                <div class="genre-bar-fill" style="width: ${percent}%"></div>
            </div>
            <span class="genre-count">${count}</span>
        `;
        container.appendChild(row);
    });
}

function renderRecentAdditions(recentData) {
    const container = document.getElementById('statsRecentAdditions');
    if (!container) return;

    if (!recentData || !recentData.by_day) {
        container.innerHTML = '<div class="breakdown-placeholder">No recent additions data</div>';
        return;
    }

    const days = recentData.by_day || {};
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const today = new Date();

    // Build last 7 days
    const last7Days = [];
    for (let i = 6; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        const dateStr = d.toISOString().split('T')[0];
        last7Days.push({
            date: dateStr,
            dayName: dayNames[d.getDay()],
            count: days[dateStr] || 0,
            isToday: i === 0
        });
    }

    const maxCount = Math.max(...last7Days.map(d => d.count), 1);
    const totalMovies = recentData.movies_count || 0;
    const totalEpisodes = recentData.episodes_count || 0;

    let html = '<div class="recent-additions-chart">';
    last7Days.forEach(day => {
        const height = day.count > 0 ? Math.max((day.count / maxCount) * 80, 8) : 4;
        html += `
            <div class="recent-day">
                <div class="recent-day-bar" style="height: ${height}px" title="${day.date}: ${day.count} items"></div>
                <span class="recent-day-label">${day.isToday ? 'Today' : day.dayName}</span>
                ${day.count > 0 ? `<span class="recent-day-count">${day.count}</span>` : ''}
            </div>
        `;
    });
    html += '</div>';

    html += `
        <div class="recent-summary">
            <div class="recent-summary-item">
                <i data-lucide="film"></i>
                <span>${totalMovies} movies added</span>
            </div>
            <div class="recent-summary-item">
                <i data-lucide="tv"></i>
                <span>${totalEpisodes} episodes added</span>
            </div>
        </div>
    `;

    container.innerHTML = html;
}

function renderTopRated(topRatedData) {
    const container = document.getElementById('topRatedGrid');
    if (!container) return;

    if (!topRatedData || !topRatedData.items || topRatedData.items.length === 0) {
        container.innerHTML = '<div class="breakdown-placeholder">No top rated data available</div>';
        return;
    }

    container.innerHTML = '';
    topRatedData.items.slice(0, 10).forEach(item => {
        const card = document.createElement('div');
        card.className = 'top-rated-card';
        card.onclick = () => openMediaDetails(item);

        card.innerHTML = `
            <img class="top-rated-poster" src="${_mhEsc(item.poster_url || '/static/img/no-poster.png')}" alt="${_mhEsc(item.title)}" loading="lazy" onerror="this.src='/static/img/no-poster.png'">
            <div class="top-rated-info">
                <div class="top-rated-title" title="${_mhEsc(item.title)}">${_mhEsc(item.title)}</div>
                <div class="top-rated-rating">
                    <i data-lucide="star"></i>
                    <span>${item.rating ? item.rating.toFixed(1) : 'N/A'}</span>
                </div>
            </div>
        `;
        container.appendChild(card);
    });
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
        const titleIcon = document.createElement('i');
        titleIcon.setAttribute('data-lucide', 'list');
        browserTitle.appendChild(titleIcon);
        browserTitle.appendChild(document.createTextNode(' Episodes'));
        browserHeader.appendChild(browserTitle);

        episodeBrowser.appendChild(browserHeader);

        // Season tabs container (horizontal scrolling)
        const seasonTabs = document.createElement('div');
        seasonTabs.className = 'season-tabs';
        seasonTabs.id = 'seasonTabs';
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'season-tabs-loading';
        loadingDiv.textContent = 'Loading seasons...';
        seasonTabs.appendChild(loadingDiv);
        episodeBrowser.appendChild(seasonTabs);

        // Episode list container
        const episodeList = document.createElement('div');
        episodeList.className = 'episode-list';
        episodeList.id = 'episodeList';
        const selectDiv = document.createElement('div');
        selectDiv.className = 'episode-loading';
        selectDiv.textContent = 'Select a season';
        episodeList.appendChild(selectDiv);
        episodeBrowser.appendChild(episodeList);

        info.appendChild(episodeBrowser);

        // Load seasons as tabs
        loadSeasonsAsTabs(item.id, item.title, seasonTabs, episodeList);
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

        // Remove from library (admin-only backend + double "are you sure?").
        // Series/movie-level only — NOT a single episode/season (that would delete
        // the whole show). project #385 task #4745.
        const removableType = item.media_type === 'movie' ? 'movie'
            : (item.media_type === 'show' || item.media_type === 'tv' || item.media_type === 'series') ? 'tv'
            : null;
        if (removableType) {
            const removeBtn = document.createElement('button');
            removeBtn.className = 'btn btn-danger';
            removeBtn.onclick = () => confirmRemoveMedia(item, removableType);
            const rmIcon = document.createElement('i');
            rmIcon.setAttribute('data-lucide', 'trash-2');
            removeBtn.appendChild(rmIcon);
            const rmText = document.createElement('span');
            rmText.textContent = window.MEDIA_HUB_IS_ADMIN === true ? 'Remove' : 'Request Removal';
            removeBtn.appendChild(rmText);
            actions.appendChild(removeBtn);
        }
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

// Removal flow (project #385 #4745/#4746). Role-aware via window.MEDIA_HUB_IS_ADMIN,
// backed by POST /api/library/remove which decides by role:
//   • admin        → two-step "are you sure?" → deletes the movie/show + files now.
//   • regular user → single confirm → a REQUEST that pings Kytran on Telegram to
//     approve; NOTHING is deleted until he approves.
// All titles rendered via textContent — never innerHTML (external strings).
function confirmRemoveMedia(item, mediaType) {
    const title = item.title || 'this item';
    const isAdmin = window.MEDIA_HUB_IS_ADMIN === true;
    const whatFiles = mediaType === 'movie' ? 'the movie file' : 'the show and all its episode files';

    const overlay = document.createElement('div');
    overlay.className = 'request-modal-overlay';
    const box = document.createElement('div');
    box.className = 'request-modal';
    box.style.maxWidth = '440px';
    box.style.padding = '24px';
    overlay.appendChild(box);
    const close = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) close(); };

    const render = (heading, body, confirmLabel, onConfirm) => {
        box.textContent = '';
        const h = document.createElement('h3');
        h.textContent = heading;
        h.style.margin = '0 0 12px';
        const p = document.createElement('p');
        p.textContent = body;
        p.style.margin = '0 0 20px';
        p.style.opacity = '0.85';
        const row = document.createElement('div');
        row.className = 'request-modal-actions';
        const cancel = document.createElement('button');
        cancel.className = 'btn btn-secondary';
        cancel.textContent = 'Cancel';
        cancel.onclick = close;
        const go = document.createElement('button');
        go.className = 'btn btn-danger';
        go.textContent = confirmLabel;
        go.onclick = onConfirm;
        row.appendChild(cancel);
        row.appendChild(go);
        box.appendChild(h);
        box.appendChild(p);
        box.appendChild(row);
    };

    const step1 = () => {
        if (isAdmin) {
            render(`Remove "${title}"?`,
                `This permanently deletes ${whatFiles} from your library. This cannot be undone.`,
                'Continue', step2);
        } else {
            render(`Request removal of "${title}"?`,
                `This sends a request to Kytran to approve removing ${whatFiles}. Nothing is deleted until he approves.`,
                'Send Request', doRemove);
        }
    };

    function step2() {
        render('Are you absolutely sure?',
            `Second confirmation required — "${title}" and its file(s) will be permanently deleted.`,
            'Delete Permanently', doRemove);
    }

    async function doRemove(e) {
        const btn = e.target;
        const label = btn.textContent;
        btn.disabled = true;
        btn.textContent = isAdmin ? 'Deleting…' : 'Sending…';
        try {
            const resp = await fetch(`${API_BASE}/library/remove`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    media_type: mediaType, tmdb_id: item.tmdb_id,
                    title: item.title, year: item.year,
                }),
            });
            const data = await resp.json().catch(() => ({}));
            if (resp.ok && data.success) {
                if (data.mode === 'requested') {
                    showToast(`Removal request sent to Kytran for "${title}"`, 'success');
                    close();
                    closeMediaPanel();
                } else {
                    showToast(`Removed "${title}"`, 'success');
                    close();
                    closeMediaPanel();
                    if (mediaType === 'movie') { loadMovies(); } else { loadShows(); }
                }
            } else {
                showToast(data.error || 'Removal failed', 'error');
                btn.disabled = false;
                btn.textContent = label;
            }
        } catch (err) {
            showToast('Request failed', 'error');
            btn.disabled = false;
            btn.textContent = label;
        }
    }

    step1();
    document.body.appendChild(overlay);
}

function closeMediaPanel() {
    document.getElementById('mediaPanel')?.classList.remove('active');
}

// ─────────────────────────────────────────────────────────────────────────────
// EPISODE BROWSER
// ─────────────────────────────────────────────────────────────────────────────

// Store current show context for episode detail modal
let currentShowContext = { seriesId: null, showTitle: '' };

async function loadSeasonsAsTabs(seriesId, showTitle, seasonTabs, episodeList) {
    currentShowContext = { seriesId, showTitle };

    try {
        const response = await fetch(`${API_BASE}/shows/${seriesId}/seasons`);
        const data = await response.json();

        if (data.success && data.seasons && data.seasons.length > 0) {
            seasonTabs.innerHTML = '';

            data.seasons.forEach((season, index) => {
                const tab = document.createElement('button');
                tab.className = 'season-tab' + (index === 0 ? ' active' : '');
                tab.dataset.seasonNumber = season.season_number;
                tab.textContent = season.season_number === 0 ? 'Sp' : `S${season.season_number}`;

                // Episode count badge
                if (season.episode_count) {
                    const badge = document.createElement('span');
                    badge.className = 'season-tab-badge';
                    badge.textContent = season.episode_count;
                    tab.appendChild(badge);
                }

                tab.onclick = () => {
                    // Update active state
                    seasonTabs.querySelectorAll('.season-tab').forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    // Load episodes
                    loadEpisodesForSeason(seriesId, season.season_number, episodeList);
                };

                seasonTabs.appendChild(tab);
            });

            // Load first season's episodes
            loadEpisodesForSeason(seriesId, data.seasons[0].season_number, episodeList);
        } else {
            const noSeasons = document.createElement('div');
            noSeasons.className = 'season-tabs-empty';
            noSeasons.textContent = 'No seasons found';
            seasonTabs.innerHTML = '';
            seasonTabs.appendChild(noSeasons);

            const noEpisodes = document.createElement('div');
            noEpisodes.className = 'episode-empty';
            noEpisodes.textContent = 'No episodes available';
            episodeList.innerHTML = '';
            episodeList.appendChild(noEpisodes);
        }
    } catch (error) {
        console.error('[Episode Browser] Error loading seasons:', error);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'season-tabs-error';
        errorDiv.textContent = 'Error loading seasons';
        seasonTabs.innerHTML = '';
        seasonTabs.appendChild(errorDiv);
    }
    lucide.createIcons();
}

async function loadEpisodesForSeason(seriesId, seasonNumber, episodeList) {
    episodeList.innerHTML = '';
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'episode-loading';
    const spinner = document.createElement('div');
    spinner.className = 'spinner';
    loadingDiv.appendChild(spinner);
    loadingDiv.appendChild(document.createTextNode(' Loading episodes...'));
    episodeList.appendChild(loadingDiv);

    try {
        const response = await fetch(`${API_BASE}/shows/${seriesId}/episodes?season=${seasonNumber}`);
        const data = await response.json();

        if (data.success && data.episodes && data.episodes.length > 0) {
            episodeList.innerHTML = '';

            data.episodes.forEach(ep => {
                // Create Continue Watching-style card
                const episodeCard = document.createElement('div');
                episodeCard.className = 'episode-tile' + (ep.has_file ? '' : ' unavailable') + (ep.played ? ' watched' : '');

                // Click to open episode detail modal
                episodeCard.onclick = () => {
                    openEpisodeDetailModal(ep, seasonNumber);
                };

                // Thumbnail container
                const thumb = document.createElement('div');
                thumb.className = 'episode-tile-thumb';
                if (ep.poster_url) {
                    thumb.style.backgroundImage = `url(${ep.poster_url})`;
                }

                // Episode number badge (top-left)
                const epBadge = document.createElement('div');
                epBadge.className = 'episode-tile-badge';
                epBadge.textContent = ep.episode_number;
                thumb.appendChild(epBadge);

                // Watched indicator (top-right)
                if (ep.played) {
                    const watchedBadge = document.createElement('div');
                    watchedBadge.className = 'episode-tile-watched';
                    const eyeIcon = document.createElement('i');
                    eyeIcon.setAttribute('data-lucide', 'eye');
                    watchedBadge.appendChild(eyeIcon);
                    thumb.appendChild(watchedBadge);
                }

                // Play icon overlay (center)
                if (ep.has_file) {
                    const playIcon = document.createElement('div');
                    playIcon.className = 'episode-tile-play';
                    const icon = document.createElement('i');
                    icon.setAttribute('data-lucide', 'play');
                    playIcon.appendChild(icon);
                    thumb.appendChild(playIcon);
                }

                // Progress bar (if partially watched)
                if (ep.watch_progress && ep.watch_progress > 0 && ep.watch_progress < 100) {
                    const progressBar = document.createElement('div');
                    progressBar.className = 'episode-tile-progress';
                    const progressFill = document.createElement('div');
                    progressFill.className = 'episode-tile-progress-fill';
                    progressFill.style.width = `${ep.watch_progress}%`;
                    progressBar.appendChild(progressFill);
                    thumb.appendChild(progressBar);
                }

                episodeCard.appendChild(thumb);

                // Info section
                const info = document.createElement('div');
                info.className = 'episode-tile-info';

                const epTitle = document.createElement('div');
                epTitle.className = 'episode-tile-title';
                epTitle.textContent = ep.title || `Episode ${ep.episode_number}`;
                info.appendChild(epTitle);

                const epMeta = document.createElement('div');
                epMeta.className = 'episode-tile-meta';
                const metaParts = [];
                if (ep.runtime_minutes) metaParts.push(`${ep.runtime_minutes}m`);
                if (ep.quality) metaParts.push(ep.quality);
                if (!ep.has_file) metaParts.push('Not downloaded');
                epMeta.textContent = metaParts.join(' • ');
                info.appendChild(epMeta);

                episodeCard.appendChild(info);
                episodeList.appendChild(episodeCard);
            });

            lucide.createIcons();
        } else {
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'episode-empty';
            emptyDiv.textContent = 'No episodes in this season';
            episodeList.innerHTML = '';
            episodeList.appendChild(emptyDiv);
        }
    } catch (error) {
        console.error('[Episode Browser] Error loading episodes:', error);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'episode-error';
        errorDiv.textContent = 'Error loading episodes';
        episodeList.innerHTML = '';
        episodeList.appendChild(errorDiv);
    }
}

// Episode Detail Modal - matches Continue Watching modal design
function openEpisodeDetailModal(episode, seasonNumber) {
    // Remove existing modal if any
    document.getElementById('episodeDetailModal')?.remove();

    const modal = document.createElement('div');
    modal.id = 'episodeDetailModal';
    modal.className = 'episode-detail-modal';

    const overlay = document.createElement('div');
    overlay.className = 'episode-detail-overlay';
    overlay.onclick = closeEpisodeDetailModal;
    modal.appendChild(overlay);

    const content = document.createElement('div');
    content.className = 'episode-detail-content';

    // Backdrop/thumbnail image - matches Continue Watching modal
    if (episode.poster_url) {
        const backdrop = document.createElement('div');
        backdrop.className = 'episode-detail-backdrop';
        backdrop.style.backgroundImage = `url(${episode.poster_url})`;
        content.appendChild(backdrop);
    }

    // Close button overlaid on backdrop
    const closeBtn = document.createElement('button');
    closeBtn.className = 'episode-detail-close';
    const closeIcon = document.createElement('i');
    closeIcon.setAttribute('data-lucide', 'x');
    closeBtn.appendChild(closeIcon);
    closeBtn.onclick = closeEpisodeDetailModal;
    content.appendChild(closeBtn);

    // Main content area
    const main = document.createElement('div');
    main.className = 'episode-detail-main';

    // Episode title
    const title = document.createElement('h3');
    title.className = 'episode-detail-title';
    title.textContent = `S${seasonNumber}E${episode.episode_number}: ${episode.title || 'Episode ' + episode.episode_number}`;
    main.appendChild(title);

    // Show title (smaller, muted)
    const showInfo = document.createElement('div');
    showInfo.className = 'episode-detail-show';
    showInfo.textContent = currentShowContext.showTitle;
    main.appendChild(showInfo);

    // Meta info row (runtime, quality, air date)
    const metaRow = document.createElement('div');
    metaRow.className = 'episode-detail-meta';
    const metaParts = [];
    if (episode.runtime_minutes) metaParts.push(`${episode.runtime_minutes} min`);
    if (episode.quality) metaParts.push(episode.quality);
    if (episode.air_date) {
        const airDate = new Date(episode.air_date);
        if (!isNaN(airDate)) {
            metaParts.push(airDate.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }));
        }
    }
    metaRow.textContent = metaParts.join(' • ');
    main.appendChild(metaRow);

    // Watch status badge
    const statusRow = document.createElement('div');
    statusRow.className = 'episode-detail-status';
    const statusBadge = document.createElement('span');
    statusBadge.className = 'status-badge ' + (episode.played ? 'watched' : 'unwatched');
    const statusIcon = document.createElement('i');
    statusIcon.setAttribute('data-lucide', episode.played ? 'eye' : 'eye-off');
    statusBadge.appendChild(statusIcon);
    statusBadge.appendChild(document.createTextNode(episode.played ? ' Watched' : ' Unwatched'));
    if (episode.view_count && episode.view_count > 1) {
        statusBadge.appendChild(document.createTextNode(` (${episode.view_count}x)`));
    }
    statusRow.appendChild(statusBadge);
    main.appendChild(statusRow);

    // Overview/description
    if (episode.overview) {
        const overview = document.createElement('p');
        overview.className = 'episode-detail-overview';
        overview.textContent = episode.overview;
        main.appendChild(overview);
    }

    content.appendChild(main);

    // Action buttons - match Continue Watching modal design
    const actions = document.createElement('div');
    actions.className = 'episode-detail-actions';

    if (episode.has_file) {
        // Stream Now button - matches Continue Watching modal
        const hasJellyfin = availableMediaServers.some(s => s.type === 'jellyfin') ||
                           availableMediaServers.length === 0;

        if (hasJellyfin) {
            const streamBtn = document.createElement('button');
            streamBtn.className = 'btn btn-stream';
            streamBtn.onclick = () => {
                closeEpisodeDetailModal();
                closeMediaPanel();
                openVideoPlayer({
                    id: episode.id,
                    title: `${episode.title || 'Episode ' + episode.episode_number}`,
                    media_type: 'episode'
                });
            };
            const streamIcon = document.createElement('i');
            streamIcon.setAttribute('data-lucide', 'monitor-play');
            streamBtn.appendChild(streamIcon);
            const streamText = document.createElement('span');
            streamText.textContent = 'Stream Now';
            streamBtn.appendChild(streamText);
            actions.appendChild(streamBtn);
        }

        // Toggle watched button
        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'btn btn-secondary';
        toggleBtn.id = 'toggleWatchedBtn';
        const toggleIcon = document.createElement('i');
        toggleIcon.setAttribute('data-lucide', episode.played ? 'eye-off' : 'eye');
        toggleBtn.appendChild(toggleIcon);
        const toggleText = document.createElement('span');
        toggleText.textContent = episode.played ? 'Mark Unwatched' : 'Mark Watched';
        toggleBtn.appendChild(toggleText);
        toggleBtn.onclick = () => toggleEpisodeWatched(episode, seasonNumber, toggleBtn, statusBadge);
        actions.appendChild(toggleBtn);

        // Server buttons for all available media servers (same as Continue Watching)
        const servers = availableMediaServers.length > 0 ? availableMediaServers : [
            { type: 'jellyfin', url: 'http://192.168.1.200:8096', name: 'Jellyfin' },
            { type: 'plex', url: 'http://192.168.1.200:32400', name: 'Plex' }
        ];

        servers.forEach((server) => {
            const serverBtn = document.createElement('a');
            serverBtn.className = 'btn btn-secondary';

            if (server.type === 'jellyfin') {
                // Jellyfin deep link to episode
                serverBtn.href = `${server.url}/web/index.html#!/details?id=${episode.id}`;
            } else {
                // Plex - search for the show
                const showTitle = currentShowContext?.showTitle || '';
                if (currentShowContext?.tvdb_id) {
                    serverBtn.href = `${server.url}/web/index.html#!/provider/tv.plex.provider.metadata/details?key=/library/metadata/plex://show?guid=tvdb://${currentShowContext.tvdb_id}`;
                } else {
                    serverBtn.href = `${server.url}/web/index.html#!/search?query=${encodeURIComponent(showTitle)}`;
                }
            }

            serverBtn.target = '_blank';
            const serverIcon = document.createElement('i');
            serverIcon.setAttribute('data-lucide', 'external-link');
            serverBtn.appendChild(serverIcon);
            const serverText = document.createElement('span');
            serverText.textContent = server.name;
            serverBtn.appendChild(serverText);
            actions.appendChild(serverBtn);
        });
    } else {
        // Not available message
        const unavailable = document.createElement('div');
        unavailable.className = 'episode-unavailable-msg';
        unavailable.textContent = 'This episode is not downloaded yet';
        actions.appendChild(unavailable);
    }

    content.appendChild(actions);
    modal.appendChild(content);
    document.body.appendChild(modal);

    // Trigger animation
    requestAnimationFrame(() => modal.classList.add('active'));
    lucide.createIcons();
}

function closeEpisodeDetailModal() {
    const modal = document.getElementById('episodeDetailModal');
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => modal.remove(), 200);
    }
}

async function toggleEpisodeWatched(episode, seasonNumber, toggleBtn, statusBadge) {
    const newWatchedState = !episode.played;

    // Optimistic UI update
    toggleBtn.disabled = true;
    const originalText = toggleBtn.textContent;
    toggleBtn.textContent = newWatchedState ? ' Marking watched...' : ' Marking unwatched...';

    try {
        const response = await fetch(`${API_BASE}/episodes/${episode.id}/watched`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ watched: newWatchedState })
        });
        const data = await response.json();

        if (data.success) {
            // Update episode state
            episode.played = newWatchedState;

            // Update button
            toggleBtn.innerHTML = '';
            const icon = document.createElement('i');
            icon.setAttribute('data-lucide', newWatchedState ? 'eye-off' : 'eye');
            toggleBtn.appendChild(icon);
            toggleBtn.appendChild(document.createTextNode(newWatchedState ? ' Mark Unwatched' : ' Mark Watched'));

            // Update status badge
            statusBadge.className = 'status-badge ' + (newWatchedState ? 'watched' : 'unwatched');
            statusBadge.innerHTML = '';
            const statusIcon = document.createElement('i');
            statusIcon.setAttribute('data-lucide', newWatchedState ? 'eye' : 'eye-off');
            statusBadge.appendChild(statusIcon);
            statusBadge.appendChild(document.createTextNode(newWatchedState ? ' Watched' : ' Unwatched'));

            // Refresh episode list in background
            const episodeList = document.getElementById('episodeList');
            if (episodeList) {
                loadEpisodesForSeason(currentShowContext.seriesId, seasonNumber, episodeList);
            }

            lucide.createIcons();
            showToast(newWatchedState ? 'Marked as watched' : 'Marked as unwatched', 'success');
        } else {
            throw new Error(data.error || 'Failed to update');
        }
    } catch (error) {
        console.error('[Episode Detail] Error toggling watched:', error);
        showToast('Failed to update watch status', 'error');
        toggleBtn.textContent = originalText;
    }

    toggleBtn.disabled = false;
}

// ─────────────────────────────────────────────────────────────────────────────
// VIDEO PLAYER
// ─────────────────────────────────────────────────────────────────────────────

let currentStreamInfo = null;
let currentPlayerItem = null;
let _mhUpNextTimer = null;
let _mhUpNextCountdown = null;

function _mhGetAutoplayNext() {
    try {
        const v = localStorage.getItem('mh_autoplay_next');
        return v === null ? true : v === '1';
    } catch (e) {
        return true;
    }
}

function _mhSetAutoplayNext(checked) {
    try {
        localStorage.setItem('mh_autoplay_next', checked ? '1' : '0');
    } catch (e) {
        // localStorage unavailable (private mode etc.) - setting just won't persist
    }
}

function _mhCancelUpNext() {
    if (_mhUpNextTimer) { clearInterval(_mhUpNextTimer); _mhUpNextTimer = null; }
    const banner = document.getElementById('videoUpNextBanner');
    if (banner) banner.style.display = 'none';
}

function _mhPlayUpNextNow() {
    const episode = _mhUpNextEpisode;
    _mhCancelUpNext();
    if (episode) {
        openVideoPlayer({
            id: episode.id,
            title: episode.title || `Episode ${episode.episode_number}`,
            media_type: 'episode',
            season_number: episode.season_number,
            episode_number: episode.episode_number,
        });
    }
}

let _mhUpNextEpisode = null;

function _mhShowUpNextBanner(episode) {
    _mhUpNextEpisode = episode;
    const banner = document.getElementById('videoUpNextBanner');
    const titleEl = document.getElementById('videoUpNextTitle');
    const countdownEl = document.getElementById('videoUpNextCountdown');
    if (!banner || !titleEl || !countdownEl) return;

    const label = (episode.season_number !== undefined && episode.episode_number !== undefined)
        ? `S${episode.season_number}E${episode.episode_number} - ${episode.title || ''}`
        : (episode.title || 'Next Episode');
    titleEl.textContent = label;
    banner.style.display = 'block';

    _mhUpNextCountdown = 5;
    countdownEl.textContent = String(_mhUpNextCountdown);
    if (_mhUpNextTimer) clearInterval(_mhUpNextTimer);
    _mhUpNextTimer = setInterval(() => {
        _mhUpNextCountdown -= 1;
        if (_mhUpNextCountdown <= 0) {
            _mhPlayUpNextNow();
            return;
        }
        countdownEl.textContent = String(_mhUpNextCountdown);
    }, 1000);
}

async function _mhHandleVideoEnded() {
    if (!_mhGetAutoplayNext()) return;
    if (!currentPlayerItem || currentPlayerItem.media_type !== 'episode') return;

    try {
        const response = await fetch(`${API_BASE}/episodes/${currentPlayerItem.id}/next`);
        const data = await response.json();
        if (data.success && data.episode && data.episode.has_file) {
            _mhShowUpNextBanner(data.episode);
        }
    } catch (error) {
        console.error('[Autoplay Next] Failed to resolve next episode:', error);
    }
}

// HTML-escape untrusted strings before innerHTML interpolation (audit XSS fix #385).
function _mhEsc(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

// ── Phone fullscreen + landscape rotation + idle chrome-fade for the player (#4739) ──
let _mhChromeTimer = null;
function _mhIsPhone() {
    return !!(window.matchMedia
        && window.matchMedia('(max-width: 768px)').matches
        && window.matchMedia('(pointer: coarse)').matches);
}
function _mhLockLandscape() {
    try { if (screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape').catch(function(){}); } catch (e) {}
}
function _mhUnlockOrientation() {
    try { if (screen.orientation && screen.orientation.unlock) screen.orientation.unlock(); } catch (e) {}
}
function _mhEnterFullscreen() {
    // Called within the tap gesture (before any await) so Android honours it; iOS ignores container FS gracefully.
    const modal = document.getElementById('videoPlayerModal');
    const el = (modal && modal.querySelector('.video-player-container')) || modal;
    if (!el) return;
    try {
        if (el.requestFullscreen) { el.requestFullscreen().then(_mhLockLandscape).catch(function(){}); }
        else if (el.webkitRequestFullscreen) { el.webkitRequestFullscreen(); }
    } catch (e) {}
}
function _mhExitFullscreen() {
    try {
        if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function(){});
        else if (document.webkitFullscreenElement && document.webkitExitFullscreen) document.webkitExitFullscreen();
    } catch (e) {}
    _mhUnlockOrientation();
}
function _mhShowChrome() {
    const modal = document.getElementById('videoPlayerModal');
    if (!modal) return;
    modal.classList.remove('chrome-hidden');
    if (_mhChromeTimer) clearTimeout(_mhChromeTimer);
    _mhChromeTimer = setTimeout(function () {
        const v = document.getElementById('videoPlayer');
        if (v && !v.paused) modal.classList.add('chrome-hidden');   // only auto-hide while playing
    }, 3500);
}
function _mhSetupChromeFade() {
    const modal = document.getElementById('videoPlayerModal');
    if (!modal || modal._mhFadeBound) return;
    modal._mhFadeBound = true;
    ['mousemove', 'touchstart', 'click'].forEach(function (ev) {
        modal.addEventListener(ev, _mhShowChrome, { passive: true });
    });
    // Also lock landscape when the native <video> fullscreen button is used (covers iOS).
    document.addEventListener('fullscreenchange', function () {
        if (document.fullscreenElement) _mhLockLandscape(); else _mhUnlockOrientation();
    });
}

async function openVideoPlayer(item) {
    const modal = document.getElementById('videoPlayerModal');
    const video = document.getElementById('videoPlayer');
    const loading = document.getElementById('videoLoading');
    const title = document.getElementById('videoPlayerTitle');
    const qualityInfo = document.getElementById('videoQualityInfo');
    const subtitleSelector = document.getElementById('videoSubtitleSelector');

    // Chaining into a new episode (autoplay-next) - cancel any pending banner/timer
    // from the episode that just ended before we start the new one.
    _mhCancelUpNext();
    currentPlayerItem = item;

    const autoplayToggle = document.getElementById('videoAutoplayToggle');
    const autoplayCheckbox = document.getElementById('videoAutoplayNextCheckbox');
    if (autoplayToggle && autoplayCheckbox) {
        if (item.media_type === 'episode') {
            autoplayToggle.style.display = 'flex';
            autoplayCheckbox.checked = _mhGetAutoplayNext();
        } else {
            autoplayToggle.style.display = 'none';
        }
    }
    video.onended = _mhHandleVideoEnded;

    // Show modal with loading state
    modal.classList.add('active');
    loading.classList.remove('hidden');
    // Phone: request full screen + landscape NOW (still inside the tap gesture, before the
    // async fetch below), and arm the idle chrome-fade. Best-effort — wrapped in try/catch.
    _mhSetupChromeFade();
    _mhShowChrome();
    if (_mhIsPhone()) _mhEnterFullscreen();
    title.textContent = item.title || 'Now Playing';
    qualityInfo.innerHTML = '';
    subtitleSelector.innerHTML = '';

    try {
        // Get stream URL from API - pass title/year for fallback lookup (Plex IDs need Jellyfin lookup)
        const params = new URLSearchParams();
        if (item.title) params.set('title', item.title);
        if (item.year) params.set('year', item.year);
        if (item.media_type) params.set('type', item.media_type);
        // Episode-specific params for show/season/episode lookup
        if (item.media_type === 'episode') {
            const showTitle = item.metadata?.show_title || item.show_title;
            if (showTitle) params.set('show_title', showTitle);
            if (item.season_number !== undefined) params.set('season', item.season_number);
            if (item.episode_number !== undefined) params.set('episode', item.episode_number);
        }
        const queryString = params.toString();
        const streamUrl = `${API_BASE}/stream/${item.id}${queryString ? '?' + queryString : ''}`;
        const response = await fetch(streamUrl);
        const data = await response.json();

        if (!data.success || !data.stream) {
            throw new Error(data.error || 'Failed to get stream URL');
        }

        currentStreamInfo = data.stream;

        // Notify cast module (no-op if Cast SDK not loaded)
        if (typeof window.castSetCurrentItem === 'function') {
            window.castSetCurrentItem(item);
        }

        // Resume position (in seconds)
        const resumePosition = data.stream.resume_position_seconds || 0;

        // Check if HLS (transcoded) stream
        if (data.stream.container === 'm3u8') {
            // Use HLS.js if available, otherwise native HLS (Safari)
            if (typeof Hls !== 'undefined' && Hls.isSupported()) {
                const hls = new Hls();
                hls.loadSource(data.stream.stream_url);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, () => {
                    // Seek to resume position if available
                    if (resumePosition > 0) {
                        video.currentTime = resumePosition;
                        showToast(`Resuming from ${formatDuration(resumePosition)}`, 'info');
                    }
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
                    if (resumePosition > 0) {
                        video.currentTime = resumePosition;
                        showToast(`Resuming from ${formatDuration(resumePosition)}`, 'info');
                    }
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
                if (resumePosition > 0) {
                    video.currentTime = resumePosition;
                    showToast(`Resuming from ${formatDuration(resumePosition)}`, 'info');
                }
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

    // Cancel any pending autoplay-next banner/countdown and detach its handler.
    _mhCancelUpNext();
    video.onended = null;
    currentPlayerItem = null;

    // Leave fullscreen, release the landscape lock, and stop the idle-fade timer (#4739).
    _mhExitFullscreen();
    if (_mhChromeTimer) { clearTimeout(_mhChromeTimer); _mhChromeTimer = null; }
    if (modal) modal.classList.remove('chrome-hidden');

    // Cleanup HLS instance FIRST if exists (before touching video element)
    if (video.hlsInstance) {
        video.hlsInstance.destroy();
        video.hlsInstance = null;
    }

    // Stop playback safely
    try {
        video.pause();
    } catch (e) {
        // Ignore pause errors
    }

    // Remove subtitle tracks
    const tracks = video.querySelectorAll('track');
    tracks.forEach(t => t.remove());

    // Clear source properly to avoid playback errors
    video.removeAttribute('src');
    video.load();

    modal.classList.remove('active');
    currentStreamInfo = null;

    // Notify cast module (no-op if Cast SDK not loaded)
    if (typeof window.castClearCurrentItem === 'function') {
        window.castClearCurrentItem();
    }
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

    // Cache-first (stale-while-revalidate): paint the last-known services from
    // localStorage INSTANTLY, then refresh and only re-render if changed (flash-free). #4746.
    const sigOf = (svcs) => (svcs || []).map(s => `${s.id}:${s.host}:${s.port}:${s.health_status || ''}`).join(',');
    const renderServices = (svcs) => {
        container.textContent = '';
        svcs.forEach(service => container.appendChild(createServiceCard(service)));
        lucide.createIcons();
    };
    const cachedS = cacheGet('settings-services');
    if (cachedS && cachedS.data && cachedS.data.length) {
        renderServices(cachedS.data);
        container.dataset.mhSig = sigOf(cachedS.data);
    }

    try {
        const response = await fetch(`${API_BASE}/settings`);
        const data = await response.json();

        if (data.success && data.services) {
            cacheSet('settings-services', data.services);
            const sig = sigOf(data.services);
            if (sig !== container.dataset.mhSig) {
                renderServices(data.services);
                container.dataset.mhSig = sig;
            }
        }
    } catch (error) {
        console.error('Settings load error:', error);
        // Keep any cached render on error rather than blanking.
    }

    renderThemePicker();
}

function renderThemePicker() {
  var host = document.getElementById('mh-theme-picker');
  if (!host || !window.MHTheme) return;
  var cur = window.MHTheme.current();
  host.innerHTML = '';
  window.MHTheme.THEMES.forEach(function (t) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'theme-card';
    b.dataset.key = t.key;
    b.setAttribute('aria-pressed', String(t.key === cur));
    var sw = document.createElement('span');
    sw.className = 'theme-card-swatch';
    sw.style.background = t.swatch.bg;
    sw.style.borderColor = t.swatch.accent;
    var dot = document.createElement('span');
    dot.className = 'theme-card-dot';
    dot.style.background = t.swatch.accent;
    sw.appendChild(dot);
    var label = document.createElement('span');
    label.className = 'theme-card-label';
    label.textContent = t.label;              // static label — textContent (XSS rule)
    b.appendChild(sw); b.appendChild(label);
    b.addEventListener('click', function () {
      window.MHTheme.applyTheme(t.key);
      host.querySelectorAll('.theme-card').forEach(function (c) {
        c.setAttribute('aria-pressed', String(c.dataset.key === t.key));
      });
    });
    host.appendChild(b);
  });
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

// iOS 'Add to Home Screen' hint. iOS Safari NEVER fires beforeinstallprompt, so the
// Android install button/banner above never appears on iPhone/iPad — the app looked
// "missing" to iOS users. Show a manual, dismissible hint instead. Safari-only can
// actually install; other iOS browsers get an "open in Safari" nudge. project #385.
function maybeShowIosInstallHint() {
    try {
        const ua = navigator.userAgent || '';
        const isIOS = /iPad|iPhone|iPod/.test(ua) ||
            (navigator.platform === 'MacIntel' && (navigator.maxTouchPoints || 0) > 1); // iPadOS 13+
        if (!isIOS) return;                                    // Android has its own prompt
        if (window.navigator.standalone === true ||
            window.matchMedia('(display-mode: standalone)').matches) return;  // already installed
        if (localStorage.getItem('media-hub-ios-install-dismissed') === '1') return;
        if (document.body.classList.contains('tv-mode')) return;

        // Only Safari can install a PWA on iOS; Chrome/Firefox/Edge on iOS cannot.
        const isSafari = /Safari/.test(ua) && !/(CriOS|FxiOS|EdgiOS|OPiOS|GSA)/.test(ua);

        const banner = document.createElement('div');
        banner.className = 'pwa-install-banner';  // reuse the existing banner styling

        const iconDiv = document.createElement('div');
        iconDiv.className = 'pwa-install-icon';
        const iconEl = document.createElement('i');
        iconEl.setAttribute('data-lucide', isSafari ? 'share' : 'compass');
        iconDiv.appendChild(iconEl);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'pwa-install-content';
        const title = document.createElement('h3');
        title.className = 'pwa-install-title';
        const text = document.createElement('p');
        text.className = 'pwa-install-text';
        if (isSafari) {
            title.textContent = 'Install Media Hub';
            text.textContent = "Tap the Share button, then “Add to Home Screen”.";
        } else {
            title.textContent = 'Open in Safari to install';
            text.textContent = 'On iPhone, apps install from Safari — open this page in Safari, then Share → Add to Home Screen.';
        }
        contentDiv.appendChild(title);
        contentDiv.appendChild(text);

        const actionsDiv = document.createElement('div');
        actionsDiv.className = 'pwa-install-actions';
        const okBtn = document.createElement('button');
        okBtn.className = 'pwa-install-btn primary';
        okBtn.textContent = 'Got it';
        okBtn.addEventListener('click', () => {
            banner.classList.remove('show');
            setTimeout(() => banner.remove(), 400);
            try { localStorage.setItem('media-hub-ios-install-dismissed', '1'); } catch (e) { /* ignore */ }
        });
        actionsDiv.appendChild(okBtn);

        banner.appendChild(iconDiv);
        banner.appendChild(contentDiv);
        banner.appendChild(actionsDiv);
        document.body.appendChild(banner);
        if (window.lucide && lucide.createIcons) lucide.createIcons();
        setTimeout(() => banner.classList.add('show'), 100);
    } catch (e) {
        /* never break the app over an install hint */
    }
}

// Initialize TV mode detection on load
document.addEventListener('DOMContentLoaded', () => {
    detectTVMode();

    // Hide install button if already in standalone mode (app already installed)
    if (window.matchMedia('(display-mode: standalone)').matches) {
        hideInstallButton();
        console.log('[Media Hub] Running in standalone mode - already installed');
    }

    // iOS install hint (Android is covered by beforeinstallprompt above). Small
    // delay so the app paints first — smoother than popping on first frame.
    setTimeout(maybeShowIosInstallHint, 2500);
});

// ── Slim the decorative LCARS sidebars on phones so content uses the full width (#4740) ──
// The sidebars carry inline `width:56px !important`, which external CSS can't override,
// so nudge them here. Phone-only; captures the original width to restore on desktop/rotate.
function _mhSlimLcarsSidebars() {
    var phone = window.matchMedia && window.matchMedia('(max-width: 600px)').matches;
    document.querySelectorAll('.lcars-sidebar').forEach(function (sb) {
        if (!sb.dataset.mhOrigW) sb.dataset.mhOrigW = sb.style.width || '56px';
        sb.style.setProperty('width', phone ? '12px' : sb.dataset.mhOrigW, 'important');
    });
}
if (document.readyState !== 'loading') _mhSlimLcarsSidebars();
else document.addEventListener('DOMContentLoaded', _mhSlimLcarsSidebars);
window.addEventListener('resize', _mhSlimLcarsSidebars);
setTimeout(_mhSlimLcarsSidebars, 600);
