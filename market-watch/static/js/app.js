/* M.A.R.K.E.T. — Tab routing, DOM init, auto-refresh */
'use strict';

const App = {
  currentTab: 'dashboard',
  refreshIntervals: {},

  init() {
    this._bindTabs();
    this._bindViewAll();
    this._initTab('dashboard');
    this._startHealthCheck();
  },

  /** Bind tab click events */
  _bindTabs() {
    const tabs = document.querySelectorAll('.lcars-tab');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.getAttribute('data-tab');
        if (target) this.switchTab(target);
      });
    });
  },

  /** Bind "View All" links in widget panels */
  _bindViewAll() {
    document.querySelectorAll('.view-all[data-tab]').forEach(el => {
      el.addEventListener('click', () => {
        const target = el.getAttribute('data-tab');
        if (target) this.switchTab(target);
      });
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          const target = el.getAttribute('data-tab');
          if (target) this.switchTab(target);
        }
      });
    });
  },

  /** Switch active tab */
  switchTab(tabName) {
    document.querySelectorAll('.lcars-tab').forEach(t => {
      const isActive = t.getAttribute('data-tab') === tabName;
      t.classList.toggle('active', isActive);
      t.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    document.querySelectorAll('.tab-content').forEach(s => {
      s.classList.toggle('hidden', s.id !== 'tab-' + tabName);
    });

    this.currentTab = tabName;
    this._initTab(tabName);
  },

  /** Initialize tab data on first visit */
  _initTab(tabName) {
    switch (tabName) {
      case 'dashboard': if (typeof Dashboard !== 'undefined') Dashboard.load(); break;
      case 'watchlist': if (typeof Watchlist !== 'undefined') Watchlist.load(); break;
      case 'portfolio': if (typeof Portfolio !== 'undefined') Portfolio.load(); break;
      case 'alerts': if (typeof Alerts !== 'undefined') Alerts.load(); break;
      case 'analysis': if (typeof Analysis !== 'undefined') Analysis.load(); break;
      case 'trading': if (typeof Trading !== 'undefined') Trading.load(); break;
      case 'charts': if (typeof Charts !== 'undefined') Charts.init(); break;
      case 'backtest': if (typeof Backtest !== 'undefined') Backtest.init(); break;
    }
  },

  /** Health check every 30s */
  _startHealthCheck() {
    const update = async () => {
      try {
        await API.health();
        const el = document.getElementById('header-last-updated');
        if (el) el.textContent = new Date().toLocaleTimeString();
      } catch (_) { /* silent */ }
    };
    update();
    setInterval(update, 30000);
  },

  /** Show a toast notification */
  toast(message, type) {
    type = type || 'success';
    const el = document.createElement('div');
    el.className = 'toast toast--' + type;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => { el.remove(); }, 4000);
  },

  /** Format currency */
  formatCurrency(val) {
    if (val == null || isNaN(val)) return '--';
    return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },

  /** Format percentage */
  formatPct(val) {
    if (val == null || isNaN(val)) return '--';
    var sign = val >= 0 ? '+' : '';
    return sign + Number(val).toFixed(2) + '%';
  },

  /** Get CSS class for positive/negative values */
  pnlClass(val) {
    if (val > 0) return 'positive';
    if (val < 0) return 'negative';
    return '';
  },

  /** Format date string */
  formatDate(dateStr) {
    if (!dateStr) return '--';
    var d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  },

  /** Format datetime */
  formatDateTime(dateStr) {
    if (!dateStr) return '--';
    var d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
           d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  },

  /** Create a badge element */
  createBadge(text, type) {
    var span = document.createElement('span');
    span.className = 'badge badge--' + (type || text).toLowerCase();
    span.textContent = text;
    return span;
  },

  /** Remove all children from an element */
  clearEl(el) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
  },

  /** Set loading state in a table body */
  setLoading(tbodyId) {
    var tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    this.clearEl(tbody);
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.colSpan = tbody.closest('table').querySelectorAll('th').length;
    var div = document.createElement('div');
    div.className = 'loading';
    div.textContent = 'Loading\u2026';
    td.appendChild(div);
    tr.appendChild(td);
    tbody.appendChild(tr);
  },

  /** Show empty state in a table body */
  setEmpty(tbodyId, message, colSpan) {
    var tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    this.clearEl(tbody);
    var tr = document.createElement('tr');
    var td = document.createElement('td');
    td.colSpan = colSpan || tbody.closest('table').querySelectorAll('th').length;
    td.style.textAlign = 'center';
    td.style.padding = '20px';
    td.style.color = 'var(--text-dim)';
    td.textContent = message;
    tr.appendChild(td);
    tbody.appendChild(tr);
  },
};

document.addEventListener('DOMContentLoaded', function() { App.init(); });
