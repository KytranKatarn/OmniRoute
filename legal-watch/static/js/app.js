/* G.A.V.E.L. Legal Watch — Tab routing + init */

const TABS = ['dashboard', 'regulations', 'court', 'news', 'legislation'];

function switchTab(tab) {
  if (!TABS.includes(tab)) tab = 'dashboard';

  // Update tabs
  document.querySelectorAll('.lcars-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
    btn.setAttribute('aria-selected', btn.dataset.tab === tab);
  });

  // Update panels
  document.querySelectorAll('.tab-content').forEach(sec => {
    sec.classList.toggle('hidden', sec.id !== `tab-${tab}`);
  });

  // Load data
  switch (tab) {
    case 'dashboard': loadDashboard(); break;
    case 'regulations': loadRegulations(); break;
    case 'court': loadCourt(); break;
    case 'news': loadNews(); break;
    case 'legislation': loadLegislation(); break;
  }

  window.location.hash = tab;
}

// Tab click handlers
document.querySelectorAll('.lcars-tab').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// View-all links
document.querySelectorAll('.view-all').forEach(link => {
  link.addEventListener('click', () => switchTab(link.dataset.tab));
});

// Hash routing
function initFromHash() {
  const hash = window.location.hash.replace('#', '');
  switchTab(hash || 'dashboard');
}

window.addEventListener('hashchange', initFromHash);

// Boot
document.addEventListener('DOMContentLoaded', () => {
  initFromHash();
  // Update status
  API.getHealth().then(h => {
    const el = document.getElementById('header-last-updated');
    if (el && h.last_ingest && h.last_ingest.completed_at) {
      el.textContent = `Last ingest: ${h.last_ingest.completed_at.substring(0, 16)}`;
    }
  }).catch(() => {});
});

// Escape HTML helper
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Format date
function fmtDate(d) {
  if (!d) return '—';
  return d.substring(0, 10);
}
