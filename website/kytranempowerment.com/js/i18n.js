/* i18n.js — Hybrid translation engine (static bundle + API overlay)
 * 8 languages: en, fr, es, pt, de, zh, ar, he
 */
const I18n = (() => {
    const API_URL = 'https://api.kytranempowerment.com/api/public/translate';
    const CACHE_TTL = 24 * 60 * 60 * 1000;
    const STORAGE_KEY = 'ke-lang';
    const RTL_LANGS = ['ar', 'he'];

    let staticBundle = {};
    let currentLang = 'en';

    async function init() {
        currentLang = localStorage.getItem(STORAGE_KEY) || 'en';
        try {
            const resp = await fetch('data/translations.json');
            staticBundle = await resp.json();
        } catch (e) {
            console.warn('[I18n] Static bundle failed to load:', e);
        }
        if (currentLang !== 'en') {
            applyTranslations(currentLang);
        }
        setDirection(currentLang);
    }

    function setLang(lang) {
        currentLang = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        setDirection(lang);
        applyTranslations(lang);
    }

    function setDirection(lang) {
        document.documentElement.dir = RTL_LANGS.includes(lang) ? 'rtl' : 'ltr';
        document.documentElement.lang = lang;
    }

    function applyTranslations(lang) {
        if (lang === 'en') {
            document.querySelectorAll('[data-i18n]').forEach(function (el) {
                var original = el.getAttribute('data-i18n-original');
                if (original) el.textContent = original;
            });
            return;
        }

        var langBundle = staticBundle[lang] || {};
        var missingKeys = [];

        document.querySelectorAll('[data-i18n]').forEach(function (el) {
            var key = el.getAttribute('data-i18n');
            if (!el.hasAttribute('data-i18n-original')) {
                el.setAttribute('data-i18n-original', el.textContent.trim());
            }
            if (langBundle[key]) {
                el.textContent = langBundle[key];
            } else {
                var cached = getCachedTranslation(key, lang);
                if (cached) {
                    el.textContent = cached;
                } else {
                    missingKeys.push({ el: el, key: key, original: el.getAttribute('data-i18n-original') });
                }
            }
        });

        if (missingKeys.length > 0) {
            fetchFromAPI(missingKeys, lang);
        }
    }

    async function fetchFromAPI(missingKeys, lang) {
        for (var i = 0; i < missingKeys.length; i++) {
            var item = missingKeys[i];
            try {
                var resp = await fetch(API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: item.original, target_lang: lang, source_lang: 'en' })
                });
                if (resp.ok) {
                    var data = await resp.json();
                    if (data.translated_text) {
                        item.el.textContent = data.translated_text;
                        cacheTranslation(item.key, lang, data.translated_text);
                    }
                }
            } catch (e) {
                console.debug('[I18n] API fallback for key:', item.key);
            }
        }
    }

    function getCachedTranslation(key, lang) {
        try {
            var raw = localStorage.getItem('ke-t-' + lang + '-' + key);
            if (!raw) return null;
            var parsed = JSON.parse(raw);
            if (Date.now() - parsed.ts > CACHE_TTL) {
                localStorage.removeItem('ke-t-' + lang + '-' + key);
                return null;
            }
            return parsed.text;
        } catch (e) { return null; }
    }

    function cacheTranslation(key, lang, text) {
        try {
            localStorage.setItem('ke-t-' + lang + '-' + key, JSON.stringify({ text: text, ts: Date.now() }));
        } catch (e) { /* localStorage full */ }
    }

    function getLang() { return currentLang; }

    return { init: init, setLang: setLang, getLang: getLang };
})();

// Expose globally for nav.js language switcher
window.I18n = I18n;
