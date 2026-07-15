/* Media Hub theme switcher — single source of truth for the theme registry. */
(function (w, d) {
  var THEMES = [
    { key: 'neutral', label: 'Neutral',      swatch: { bg:'#0d0f13', surface:'#161a21', accent:'#6ea8fe' } },
    { key: 'lcars',   label: 'LCARS',        swatch: { bg:'#000000', surface:'#17130a', accent:'#ff9966' } },
    { key: 'light',   label: 'Light',        swatch: { bg:'#f4f6f9', surface:'#ffffff', accent:'#2f6bff' } },
    { key: 'plex',    label: 'Plex Classic', swatch: { bg:'#0a0a0f', surface:'#14141c', accent:'#e5a00d' } },
    { key: 'oled',    label: 'OLED',         swatch: { bg:'#000000', surface:'#141414', accent:'#22d3ee' } }
  ];
  var KEYS = THEMES.map(function (t) { return t.key; });
  function current() {
    var a = d.documentElement.getAttribute('data-mh-theme');
    return KEYS.indexOf(a) >= 0 ? a : 'neutral';
  }
  function applyTheme(name) {
    var key = KEYS.indexOf(name) >= 0 ? name : 'neutral';
    if (key === 'neutral') d.documentElement.removeAttribute('data-mh-theme');
    else d.documentElement.setAttribute('data-mh-theme', key);
    try { localStorage.setItem('mh-theme', key); } catch (e) {}
    try { w.dispatchEvent(new CustomEvent('mh:theme', { detail: { key: key } })); } catch (e) {}
    return key;
  }
  w.MHTheme = { THEMES: THEMES, applyTheme: applyTheme, current: current };
})(window, document);
