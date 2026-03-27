/* W.A.T.C.H. App — tab routing, global init */

(function () {
  'use strict';

  // ── Tab system ──────────────────────────────────────────────────────────────

  const tabs = document.querySelectorAll('.lcars-tab');
  const panels = document.querySelectorAll('.tab-content');

  // Map tab names to their init functions (registered by each module)
  const tabInitFns = {};

  /**
   * Register a function to run the first time a tab is shown.
   * Called by each module JS file.
   */
  window.registerTabInit = function (tabName, fn) {
    tabInitFns[tabName] = fn;
  };

  const initialised = new Set();

  function showTab(name) {
    // Update tab buttons
    tabs.forEach(t => {
      const active = t.dataset.tab === name;
      t.classList.toggle('active', active);
      t.setAttribute('aria-selected', String(active));
    });

    // Show/hide panels
    panels.forEach(p => {
      const active = p.id === `tab-${name}`;
      p.classList.toggle('hidden', !active);
    });

    // Run init function once per tab
    if (!initialised.has(name) && tabInitFns[name]) {
      initialised.add(name);
      tabInitFns[name]();
    }

    // Update URL hash without scrolling
    history.replaceState(null, '', `#${name}`);
  }

  // Tab click handlers
  tabs.forEach(t => {
    t.addEventListener('click', () => showTab(t.dataset.tab));
  });

  // "View All →" links inside widgets
  document.addEventListener('click', e => {
    const el = e.target.closest('[data-tab]');
    if (el && !el.classList.contains('lcars-tab')) {
      showTab(el.dataset.tab);
    }
  });

  // Keyboard: Enter/Space on view-all spans
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      const el = e.target.closest('.view-all[data-tab]');
      if (el) { e.preventDefault(); showTab(el.dataset.tab); }
    }
  });

  // ── Header last-updated ──────────────────────────────────────────────────────

  function updateTimestamp() {
    const el = document.getElementById('header-last-updated');
    if (el) {
      el.textContent = new Date().toLocaleTimeString('en-CA', { hour: '2-digit', minute: '2-digit' });
    }
  }

  updateTimestamp();
  setInterval(updateTimestamp, 60_000);

  // ── Boot ─────────────────────────────────────────────────────────────────────

  function boot() {
    // Restore tab from URL hash
    const hash = window.location.hash.slice(1);
    const validTabs = ['dashboard', 'contracts', 'parliament', 'spending', 'events'];
    const startTab = validTabs.includes(hash) ? hash : 'dashboard';
    showTab(startTab);
  }

  // Wait for DOM + all module scripts
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
