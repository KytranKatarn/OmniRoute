/* i18n.js — Translation engine for C.R.E.E.D. (static bundle)
 * 8 languages: en, fr, es, pt, de, zh, ar, he
 */
const I18n = (() => {
    const STORAGE_KEY = 'creed-lang';
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

        document.querySelectorAll('[data-i18n]').forEach(function (el) {
            var key = el.getAttribute('data-i18n');
            if (!el.hasAttribute('data-i18n-original')) {
                el.setAttribute('data-i18n-original', el.textContent.trim());
            }
            if (langBundle[key]) {
                el.textContent = langBundle[key];
            }
        });
    }

    function getLang() { return currentLang; }

    return { init: init, setLang: setLang, getLang: getLang };
})();

window.I18n = I18n;
