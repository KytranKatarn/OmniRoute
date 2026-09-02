/* One tier check for every gate on the site.
 *
 * Design files: the tier comes from the review toggle in sessionStorage.
 * Production: base.html injects `window.__WTF_TIER = {{ tier|tojson }}` from
 * consumer/access.py and this file's sessionStorage branch is never reached.
 * Nothing else on any page may decide what a subscriber sees. */
(function () {
  var KEY = 'wtf-gate-preview';
  function fromStorage() { try { return sessionStorage.getItem(KEY) === '1'; } catch (e) { return false; } }
  var T = {
    tier: function () {
      if (typeof window.__WTF_TIER === 'string') return window.__WTF_TIER;
      return fromStorage() ? 'starter' : 'free';
    },
    isSubscriber: function () { return T.tier() !== 'free'; },
    /* Review toggle only — a no-op when the server has set the tier. */
    set: function (on) {
      if (typeof window.__WTF_TIER === 'string') return;
      try { on ? sessionStorage.setItem(KEY, '1') : sessionStorage.removeItem(KEY); } catch (e) {}
    },
    /* Wire a "Show subscriber view" button; hidden entirely in production. */
    bind: function (btn, redraw) {
      if (typeof btn === 'string') btn = document.getElementById(btn);
      if (!btn) return;
      if (typeof window.__WTF_TIER === 'string') { var bar = btn.closest('.wtf-pv'); if (bar) bar.remove(); else btn.remove(); return; }
      var label = function () { var on = T.isSubscriber(); btn.textContent = on ? 'Show the gate' : 'Show subscriber view'; btn.style.color = on ? 'var(--wtf-accent)' : ''; };
      label();
      btn.addEventListener('click', function () { T.set(!T.isSubscriber()); label(); if (redraw) redraw(); });
    }
  };
  window.WTFTier = T;
})();
