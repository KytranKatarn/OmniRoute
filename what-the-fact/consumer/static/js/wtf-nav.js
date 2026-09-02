/* Nav group dropdowns — tap support.
 *
 * Ported from design-handoff/wtf-nav.js, adapted to this app's class names
 * (.wtf-navgrp / .wtf-navgrp-btn, not .navgrp / .grp).
 *
 * WHY THIS EXISTS. The menus opened on :hover and :focus-within only. A touch
 * device fires no :hover, and :focus-within needs the button focused first —
 * so on a phone or tablet in the 1080-1200px band, where the desktop bar is
 * still shown rather than the drawer, the first tap appeared to do nothing.
 *
 * Two differences from the design version, both deliberate:
 *
 *  1. Our group header is a <button>, not an <a>, so there is no navigation to
 *     suppress. preventDefault() is kept anyway — it costs nothing and stops a
 *     future change of element type from silently reintroducing the bug.
 *
 *  2. The button carries aria-expanded, hardcoded "false" in the template and
 *     never updated. Hover opened the menu while the attribute still said
 *     closed, so assistive tech was told the opposite of what sighted users
 *     saw. This syncs it on every toggle. It is still not updated on pure
 *     hover — CSS opens the menu without JS knowing — which is why the button
 *     is focusable: keyboard and AT users go through this path.
 */
(function () {
  'use strict';

  function closeAll(except) {
    document.querySelectorAll('.wtf-navgrp.open').forEach(function (g) {
      if (g !== except) {
        g.classList.remove('open');
        var b = g.querySelector('.wtf-navgrp-btn');
        if (b) b.setAttribute('aria-expanded', 'false');
      }
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.wtf-navgrp > .wtf-navgrp-btn');
    if (btn) {
      var box = btn.parentElement;
      if (box.querySelector('.wtf-navgrp-menu')) {
        e.preventDefault();
        var wasOpen = box.classList.contains('open');
        closeAll(box);
        box.classList.toggle('open', !wasOpen);
        btn.setAttribute('aria-expanded', String(!wasOpen));
        return;
      }
    }
    // A click inside an open menu is a real navigation — leave it alone.
    if (!e.target.closest('.wtf-navgrp-menu')) closeAll(null);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll(null);
  });

  document.querySelectorAll('.wtf-navgrp').forEach(function (g) {
    g.addEventListener('mouseleave', function () {
      g.classList.remove('open');
      var b = g.querySelector('.wtf-navgrp-btn');
      if (b) b.setAttribute('aria-expanded', 'false');
    });
  });
})();
