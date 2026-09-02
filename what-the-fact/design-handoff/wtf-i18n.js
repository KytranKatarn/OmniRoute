/* Language toggle on the repo's i18n contract (static/js/i18n.js):
   localStorage['wtf-lang'], .lang-btn[data-lang], data-i18n keys, RTL for ar/he.
   On the live site I18n.init(translations) runs with static/data/translations.json;
   here the same object runs with an empty table, so the page switches language
   and direction and says what is not yet translated. Eight platform languages:
   en fr es pt de zh ar he — managed on platform.kytranempowerment.com. */
(function () {
  var KEY = 'wtf-lang', RTL = ['ar', 'he'];
  var NAMES = { en:'English', fr:'Français', es:'Español', pt:'Português', de:'Deutsch', zh:'中文', ar:'العربية', he:'עברית' };
  var CODES = { en:'EN', fr:'FR', es:'ES', pt:'PT', de:'DE', zh:'中文', ar:'عربي', he:'עברית' };
  var translations = {};
  var cur = (function () { try { return localStorage.getItem(KEY) || 'en'; } catch (e) { return 'en'; } })();
  function dir(l) { document.documentElement.setAttribute('dir', RTL.indexOf(l) >= 0 ? 'rtl' : 'ltr'); document.documentElement.setAttribute('lang', l); }
  function apply(l) {
    var data = translations[l] || {};
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var k = el.getAttribute('data-i18n');
      if (!el.getAttribute('data-i18n-original')) el.setAttribute('data-i18n-original', el.textContent);
      el.textContent = (l !== 'en' && data[k]) ? data[k] : el.getAttribute('data-i18n-original');
    });
    var note = document.getElementById('wtf-i18n-note');
    var untranslated = l !== 'en' && !Object.keys(data).length;
    if (untranslated && !note) {
      note = document.createElement('div'); note.id = 'wtf-i18n-note';
      note.style.cssText = 'font-family:var(--wtf-font-mono),monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--wtf-developing);background:var(--wtf-bg-card);border-bottom:1px solid var(--wtf-border);padding:7px var(--gut,18px);text-align:center';
      note.textContent = NAMES[l] + ' \u2014 translation served by the platform when live; this design shows the English copy';
      var n = document.querySelector('nav.nav'); if (n && n.parentNode) n.parentNode.insertBefore(note, n.nextSibling);
    } else if (!untranslated && note) note.remove();
  }
  function set(l) {
    cur = l; try { localStorage.setItem(KEY, l); } catch (e) {}
    dir(l); apply(l);
    document.querySelectorAll('.lang-btn').forEach(function (b) { var on = b.dataset.lang === l; b.classList.toggle('active', on); b.setAttribute('aria-checked', String(on)); });
    document.querySelectorAll('.wtf-lang-cur').forEach(function (s) { s.textContent = CODES[l] || l.toUpperCase(); });
  }
  function init(data) {
    translations = data || {};
    document.querySelectorAll('.lang-btn').forEach(function (b) { b.addEventListener('click', function () { set(b.dataset.lang); var g = b.closest('.navgrp'); if (g) g.classList.remove('open'); }); });
    set(cur);
  }
  window.I18n = { init: init, setLang: set, getCurrentLang: function () { return cur; } };
  /* served: the real table; design: empty */
  fetch('static/data/translations.json', { cache:'no-store' }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; }).then(init);
})();
