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

    var currentLanguage = 'en';
    var translationCache = {};      // { lang: { data: {}, timestamp: number } }
    var originalsMap = new Map();    // element -> original textContent
    var originalsStored = false;

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

        // Save preference to server
        fetch('/api/user/language', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language: lang })
        }).catch(function(err) {
            console.warn('[archieI18n] Failed to save language preference:', err);
        });

        if (lang === 'en') {
            revertToEnglish();
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
                // If server says English but localStorage had something else, respect server
                if (serverLang === 'en' && currentLanguage !== 'en') {
                    revertToEnglish();
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
        refresh: refresh
    };

})();
