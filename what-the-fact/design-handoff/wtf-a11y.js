/* Accessibility floor, applied on every page after render.
 *
 * - Anything clickable that is not a link or button becomes focusable and
 *   activates on Enter / Space.
 * - Every SVG without an accessible name gets role="img" and a label from the
 *   nearest heading, so a chart is never an anonymous graphic to a reader.
 * - Runs again when the DOM changes, since most pages render client-side. */
(function () {
  var SEL = '[data-go],[data-j],[data-org],[data-p],[data-save],.wtf-jr-card,.wtf-ch-exc,.wtf-ch-chip,.wtf-ch-sample:not([href]),.ix,.wtf-pl-card:not([href]),.wtf-pg-bars[data-org],tr.r,tr.l-row,.rd-provbar,.wtf-of-tag[onclick]';
  function apply(root) {
    root.querySelectorAll(SEL).forEach(function (el) {
      if (el.matches('a[href],button,input,select,textarea')) return;
      if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
      if (!el.hasAttribute('role')) el.setAttribute('role', 'button');
      if (!el.__wtfKey) {
        el.__wtfKey = true;
        el.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el.click(); }
        });
      }
    });
    root.querySelectorAll('svg').forEach(function (s) {
      if (s.getAttribute('aria-hidden') === 'true' || s.getAttribute('aria-label') || s.querySelector('title')) return;
      if (s.closest('button,a,.wtf-nav-ico,.brand')) { s.setAttribute('aria-hidden', 'true'); return; }
      var h = s.closest('section,div,article');
      var head = h && (h.querySelector('h1,h2,h3,.psec,.stat-l,.wtf-ec-in') || null);
      s.setAttribute('role', 'img');
      s.setAttribute('aria-label', head ? head.textContent.trim().replace(/\s+/g, ' ').slice(0, 120) : 'Chart');
    });
    /* SVG seat dots and shapes: make clickable ones reachable. */
    root.querySelectorAll('svg circle[style*="cursor"],svg path[style*="cursor"],svg g.pin').forEach(function (n) {
      if (!n.hasAttribute('tabindex')) { n.setAttribute('tabindex', '0'); n.setAttribute('role', 'button'); }
      if (!n.__wtfKey) { n.__wtfKey = true; n.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); n.dispatchEvent(new MouseEvent('click', { bubbles: true })); } }); }
    });
  }
  var t;
  var run = function () { clearTimeout(t); t = setTimeout(function () { apply(document); }, 60); };
  run();
  new MutationObserver(run).observe(document.body, { childList: true, subtree: true });
  /* visible focus everywhere, once */
  var css = document.createElement('style');
  css.textContent = '[tabindex="0"]:focus-visible,a:focus-visible,button:focus-visible{outline:2px solid var(--wtf-brand,#14bef0);outline-offset:2px}';
  document.head.appendChild(css);
})();
