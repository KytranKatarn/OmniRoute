/**
 * A.R.C.H.I.E. Internationalization Engine
 * Client-side translation system with caching and live language switching.
 *
 * Exposes: window.archieI18n
 * Supported: { en: "English", fr: "Quebecois French" }
 */
(function() {
    'use strict';

    var SUPPORTED_LANGUAGES = { en: 'English', fr: 'Québécois French' };
    var CACHE_TTL = 5 * 60 * 1000; // 5 minutes

    /**
     * JS string registry — every translatable string generated in JavaScript.
     * The backend scan endpoint reads this via archieI18n.getTranslationKeys()
     * so these keys are discoverable without HTML template scanning.
     */
    var TRANSLATION_KEYS = {
        // Boot sequence
        'js.boot.initializing':      '> INITIALIZING A.R.C.H.I.E. CORE...',
        'js.boot.database':          'DATABASE',
        'js.boot.connected':         'CONNECTED',
        'js.boot.ai_bridge':         'AI BRIDGE',
        'js.boot.online':            'ONLINE',
        'js.boot.modules':           'MODULES',
        'js.boot.loaded':            'LOADED',
        'js.boot.network':           'NETWORK',
        'js.boot.secure':            'SECURE',
        'js.boot.agents':            'AGENTS',
        'js.boot.active':            'ACTIVE',
        'js.boot.consciousness':     'CONSCIOUSNESS',
        'js.boot.aware':             'AWARE',
        'boot.threat_level':         'THREAT LEVEL:',
        'boot.midnight':             'MIDNIGHT',

        // Status labels
        'js.status.online':          'ONLINE',
        'js.status.offline':         'OFFLINE',
        'js.status.checking':        'CHECKING...',

        // Time formatting
        'js.time.seconds_ago':       's ago',
        'js.time.minutes_ago':       'm ago',
        'js.time.hours_ago':         'h ago',
        'js.time.days_ago':          'd ago',

        // Mission briefing
        'js.briefing.loading_activity':     'Loading activity...',
        'js.briefing.no_recent_activity':   'No recent activity',
        'js.briefing.checking_alerts':      'Checking alerts...',
        'js.briefing.loading_insights':     'Loading insights...',
        'js.briefing.all_nominal':          'ALL SYSTEMS NOMINAL',
        'js.briefing.unable_load_activity': 'Unable to load activity',
        'js.briefing.unable_load_alerts':   'Unable to load alerts',
        'js.briefing.ai_unavailable':       'AI data unavailable',

        // AI Insights
        'js.insights.interactions_today':   'Interactions Today',
        'js.insights.active_agents':        'Active Agents',
        'js.insights.ai_online':            'AI Systems Online',
        'js.insights.ai_offline':           'AI Systems Offline',

        // Pin actions
        'js.pin.pin_to':             'Pin to Priority Stations',
        'js.pin.unpin_from':         'Unpin from Priority Stations',
        'js.pin.pin_module':         'Pin module',
        'js.pin.unpin_module':       'Unpin module',

        // Footer
        'js.footer.last_refreshed':  'Last refreshed',

        // Badges
        'js.badge.beta':             'BETA',
        'js.badge.coming_soon':      'COMING SOON',
        'js.badge.admin':            'ADMIN',

        // Button titles / nav
        'js.nav.notifications':      'Notifications',
        'js.nav.toggle_theme':       'Toggle Theme',
        'js.nav.language':           'Language',
        'js.nav.dev_hq':             'Dev HQ',
        'js.nav.logout':             'Logout',

        // Login page
        'login.show_password':       'Show password',
        'login.hide_password':       'Hide password',
        'login.authenticating':      'AUTHENTICATING...',
        'login.access_system':       'Access System',

        // Signup page
        'signup.show_password':       'Show password',
        'signup.hide_password':       'Hide password',
        'signup.registering':         'REGISTERING...',
        'signup.password_hint':       'Minimum 8 characters',
        'signup.submit':              'Submit Registration',
        'signup.strength_very_weak':  'Very weak',
        'signup.strength_weak':       'Weak',
        'signup.strength_fair':       'Fair',
        'signup.strength_strong':     'Strong',
        'signup.strength_very_strong':'Very strong'
    };

    var currentLanguage = 'en';
    var translationCache = {};      // { lang: { data: {}, timestamp: number } }
    var originalsMap = new Map();    // element -> original textContent
    var originalsStored = false;

    // ── Hydrate from localStorage for instant t() on page load ──
    try {
        var _savedLang = localStorage.getItem('archie-language');
        var _savedData = localStorage.getItem('archie-translations');
        if (_savedLang && _savedLang !== 'en' && _savedData) {
            var _parsed = JSON.parse(_savedData);
            if (_parsed && typeof _parsed === 'object' && Object.keys(_parsed).length > 0) {
                translationCache[_savedLang] = { data: _parsed, timestamp: Date.now() };
                currentLanguage = _savedLang;
            }
        }
    } catch (e) { /* ignore parse errors */ }

    // ── Helpers ──

    function isSupported(lang) {
        return lang && SUPPORTED_LANGUAGES.hasOwnProperty(lang);
    }

    function isCacheValid(lang) {
        var entry = translationCache[lang];
        return entry && (Date.now() - entry.timestamp) < CACHE_TTL;
    }

    // ── Core Methods ──

    /**
     * Fetch translations for a language from the server.
     * Returns a promise resolving to the translations object.
     */
    function fetchTranslations(lang) {
        if (isCacheValid(lang)) {
            return Promise.resolve(translationCache[lang].data);
        }

        return fetch('/api/translations/' + encodeURIComponent(lang))
            .then(function(resp) {
                if (!resp.ok) throw new Error('Failed to fetch translations for ' + lang);
                return resp.json();
            })
            .then(function(data) {
                var translations = data.translations || data;
                translationCache[lang] = {
                    data: translations,
                    timestamp: Date.now()
                };
                // Persist to localStorage for instant hydration on next page load
                try {
                    localStorage.setItem('archie-translations', JSON.stringify(translations));
                } catch (e) { /* ignore quota errors */ }
                return translations;
            });
    }

    /**
     * Store original English text from all [data-i18n] elements.
     * Only runs once — subsequent calls are no-ops.
     */
    function storeOriginals() {
        if (originalsStored) return;

        document.querySelectorAll('[data-i18n]').forEach(function(el) {
            if (!originalsMap.has(el)) {
                originalsMap.set(el, el.textContent);
            }
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
            if (!originalsMap.has(el)) {
                originalsMap.set(el, el.getAttribute('placeholder') || '');
            }
        });
        document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
            var key = 'title:' + (el.getAttribute('data-i18n-title') || '');
            if (!originalsMap.has(key)) {
                originalsMap.set(key, el.getAttribute('title') || '');
            }
        });

        originalsStored = true;
    }

    /**
     * Apply a translations dictionary to the page.
     * Walks [data-i18n], [data-i18n-placeholder], and [data-i18n-title] elements.
     */
    function applyTranslations(translations) {
        if (!translations || typeof translations !== 'object') return;

        document.querySelectorAll('[data-i18n]').forEach(function(el) {
            var key = el.getAttribute('data-i18n');
            if (key && translations[key] !== undefined) {
                el.textContent = translations[key];
            }
        });

        document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
            var key = el.getAttribute('data-i18n-placeholder');
            if (key && translations[key] !== undefined) {
                el.setAttribute('placeholder', translations[key]);
            }
        });

        document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
            var key = el.getAttribute('data-i18n-title');
            if (key && translations[key] !== undefined) {
                el.setAttribute('title', translations[key]);
            }
        });
    }

    /**
     * Revert all translated elements back to their original English text.
     */
    function revertToEnglish() {
        document.querySelectorAll('[data-i18n]').forEach(function(el) {
            if (originalsMap.has(el)) {
                el.textContent = originalsMap.get(el);
            }
        });

        document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
            if (originalsMap.has(el)) {
                el.setAttribute('placeholder', originalsMap.get(el));
            }
        });

        document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
            var key = 'title:' + (el.getAttribute('data-i18n-title') || '');
            if (originalsMap.has(key)) {
                el.setAttribute('title', originalsMap.get(key));
            }
        });

        currentLanguage = 'en';
    }

    /**
     * Switch language: save preference, fetch translations, apply.
     * No page reload.
     */
    function switchLanguage(lang) {
        if (!isSupported(lang)) {
            console.warn('[archieI18n] Unsupported language:', lang);
            return Promise.resolve();
        }

        // Save preference to localStorage immediately
        try {
            localStorage.setItem('archie-language', lang);
        } catch (e) { /* ignore */ }

        // Save preference to server (skip on login/signup — no session yet)
        var path = window.location.pathname;
        if (path !== '/login' && path !== '/signup') {
            fetch('/api/user/language', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ language: lang })
            }).catch(function(err) {
                console.warn('[archieI18n] Failed to save language preference:', err);
            });
        }

        if (lang === 'en') {
            revertToEnglish();
            try { localStorage.removeItem('archie-translations'); } catch (e) { /* ignore */ }
            return Promise.resolve();
        }

        storeOriginals();

        return fetchTranslations(lang)
            .then(function(translations) {
                applyTranslations(translations);
                currentLanguage = lang;
            })
            .catch(function(err) {
                console.warn('[archieI18n] Failed to switch language:', err);
            });
    }

    /**
     * Look up a translated string by key. Falls back to the provided fallback
     * or the key itself.
     */
    function t(key, fallback) {
        if (currentLanguage === 'en') {
            return fallback !== undefined ? fallback : key;
        }

        var entry = translationCache[currentLanguage];
        if (entry && entry.data && entry.data[key] !== undefined) {
            return entry.data[key];
        }

        return fallback !== undefined ? fallback : key;
    }

    /**
     * Return the current language code.
     */
    function getCurrentLanguage() {
        return currentLanguage;
    }

    /**
     * Re-apply current language translations.
     * Useful after dynamic content has been added to the DOM.
     */
    function refresh() {
        if (currentLanguage === 'en') return Promise.resolve();

        storeOriginals();

        return fetchTranslations(currentLanguage)
            .then(function(translations) {
                applyTranslations(translations);
            })
            .catch(function(err) {
                console.warn('[archieI18n] Failed to refresh translations:', err);
            });
    }

    /**
     * Initialize i18n on page load.
     * Fetches user language preference from the server and applies if not English.
     */
    function init() {
        // Try localStorage first for instant application
        var savedLang;
        try {
            savedLang = localStorage.getItem('archie-language');
        } catch (e) { /* ignore */ }

        // On login/signup pages, skip server fetch (no session) — use localStorage only
        var path = window.location.pathname;
        if (path === '/login' || path === '/signup') {
            if (savedLang && savedLang !== 'en' && isSupported(savedLang)) {
                switchLanguage(savedLang);
            }
            return;
        }

        // Fetch authoritative preference from server
        fetch('/api/user/language')
            .then(function(resp) {
                if (!resp.ok) throw new Error('Failed to fetch language pref');
                return resp.json();
            })
            .then(function(data) {
                var serverLang = data.language || 'en';
                if (serverLang !== 'en' && isSupported(serverLang)) {
                    return switchLanguage(serverLang);
                }
                // Server says EN but localStorage has a different preference
                // (e.g. user switched language on login page before authenticating)
                // → sync localStorage preference to server and apply it
                if (serverLang === 'en' && savedLang && savedLang !== 'en' && isSupported(savedLang)) {
                    return switchLanguage(savedLang);
                }
            })
            .catch(function() {
                // Server fetch failed — fall back to localStorage
                if (savedLang && savedLang !== 'en' && isSupported(savedLang)) {
                    switchLanguage(savedLang);
                }
            });
    }

    // ── Public API ──

    window.archieI18n = {
        init: init,
        fetchTranslations: fetchTranslations,
        applyTranslations: applyTranslations,
        storeOriginals: storeOriginals,
        revertToEnglish: revertToEnglish,
        switchLanguage: switchLanguage,
        t: t,
        getCurrentLanguage: getCurrentLanguage,
        refresh: refresh,
        getTranslationKeys: function() { return TRANSLATION_KEYS; }
    };

})();
