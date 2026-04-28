/* What The Fact — Consumer i18n */
const I18n = (() => {
  const STORAGE_KEY = 'wtf-lang';
  const RTL_LANGS = ['ar', 'he'];
  let translations = {};
  let currentLang = localStorage.getItem(STORAGE_KEY) || 'en';

  function setDirection(lang) {
    document.documentElement.setAttribute('dir', RTL_LANGS.includes(lang) ? 'rtl' : 'ltr');
    document.documentElement.setAttribute('lang', lang);
  }

  function applyTranslations(lang) {
    if (lang === 'en') {
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const orig = el.getAttribute('data-i18n-original');
        if (orig) el.textContent = orig;
      });
      document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        const orig = el.getAttribute('data-i18n-placeholder-original');
        if (orig) el.setAttribute('placeholder', orig);
      });
      return;
    }
    const langData = translations[lang] || {};
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (!el.getAttribute('data-i18n-original')) {
        el.setAttribute('data-i18n-original', el.textContent);
      }
      if (langData[key]) el.textContent = langData[key];
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      if (!el.getAttribute('data-i18n-placeholder-original')) {
        el.setAttribute('data-i18n-placeholder-original', el.getAttribute('placeholder') || '');
      }
      if (langData[key]) el.setAttribute('placeholder', langData[key]);
    });
  }

  function setLang(lang) {
    currentLang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    setDirection(lang);
    applyTranslations(lang);
    document.querySelectorAll('.lang-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.lang === lang);
    });
  }

  function init(data) {
    translations = data || {};
    setDirection(currentLang);
    applyTranslations(currentLang);
    document.querySelectorAll('.lang-btn').forEach(btn => {
      btn.addEventListener('click', () => setLang(btn.dataset.lang));
      btn.classList.toggle('active', btn.dataset.lang === currentLang);
    });
  }

  return { init, setLang, getCurrentLang: () => currentLang };
})();
