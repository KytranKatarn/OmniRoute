var Translate = (function () {
  var API_URL = 'https://api.kytranempowerment.com/api/public/translate';
  var CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours in ms
  var currentLang = 'en';

  var RTL_LANGS = ['ar', 'he'];

  function setLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('ke-lang', lang);

    document.documentElement.dir = RTL_LANGS.indexOf(lang) !== -1 ? 'rtl' : 'ltr';
    document.documentElement.lang = lang;

    if (lang === 'en') {
      restoreOriginals();
      return;
    }

    var elements = document.querySelectorAll('[data-i18n]');
    elements.forEach(function (el) {
      var original = el.getAttribute('data-i18n-original') || el.textContent;
      el.setAttribute('data-i18n-original', original);

      var cached = getCache(original, lang);
      if (cached !== null) {
        el.textContent = cached;
        return;
      }

      translate(original, lang)
        .then(function (translated) {
          el.textContent = translated;
          setCache(original, lang, translated);
        })
        .catch(function (err) {
          console.warn('[Translate] Failed to translate element:', err);
        });
    });
  }

  function translate(text, targetLang) {
    return fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: text,
        target_lang: targetLang,
        source_lang: 'en'
      })
    }).then(function (res) {
      if (!res.ok) {
        throw new Error('[Translate] API error: ' + res.status + ' ' + res.statusText);
      }
      return res.json();
    }).then(function (data) {
      return data.translated_text;
    });
  }

  function restoreOriginals() {
    var elements = document.querySelectorAll('[data-i18n-original]');
    elements.forEach(function (el) {
      el.textContent = el.getAttribute('data-i18n-original');
    });
    document.documentElement.dir = 'ltr';
    document.documentElement.lang = 'en';
  }

  function getCache(key, lang) {
    var storageKey = 'ke-t-' + lang + '-' + key;
    try {
      var raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      var entry = JSON.parse(raw);
      if (Date.now() - entry.ts > CACHE_TTL) {
        localStorage.removeItem(storageKey);
        return null;
      }
      return entry.text;
    } catch (e) {
      return null;
    }
  }

  function setCache(key, lang, text) {
    var storageKey = 'ke-t-' + lang + '-' + key;
    try {
      localStorage.setItem(storageKey, JSON.stringify({ text: text, ts: Date.now() }));
    } catch (e) {
      console.warn('[Translate] localStorage quota exceeded, cache not saved.');
    }
  }

  function init() {
    var saved = localStorage.getItem('ke-lang');
    if (saved && saved !== 'en') {
      setLanguage(saved);
      var switcher = document.getElementById('langSwitcher');
      if (switcher) {
        switcher.textContent = saved.toUpperCase();
      }
    }
  }

  return {
    API_URL: API_URL,
    CACHE_TTL: CACHE_TTL,
    currentLang: currentLang,
    setLanguage: setLanguage,
    translate: translate,
    restoreOriginals: restoreOriginals,
    getCache: getCache,
    setCache: setCache,
    init: init
  };
})();
