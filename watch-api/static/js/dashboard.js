/* W.A.T.C.H. Dashboard tab — hero stats + widget panels */
(function () {
  'use strict';

  async function loadStats() {
    try {
      const stats = await API.stats();
      const cv = document.getElementById('stat-contracts-value');
      const bv = document.getElementById('stat-bills-value');
      const sv = document.getElementById('stat-spending-value');
      const vv = document.getElementById('stat-votes-value');
      if (cv) cv.textContent = Number(stats.contracts || 0).toLocaleString('en-CA');
      if (bv) bv.textContent = Number(stats.bills_active || 0).toLocaleString('en-CA');
      if (sv) sv.textContent = fmtAmount(stats.spending_total || 0);
      if (vv) vv.textContent = Number(stats.votes_recent || 0).toLocaleString('en-CA');
    } catch (err) {
      console.warn('[WATCH] Stats load failed:', err.message);
    }
  }

  function renderWidgetItems(rows, renderFn) {
    const frag = document.createDocumentFragment();
    rows.forEach(r => {
      const div = document.createElement('div');
      div.className = 'widget-item';
      renderFn(div, r);
      frag.appendChild(div);
    });
    return frag;
  }

  async function loadContractsWidget() {
    const el = document.getElementById('widget-contracts-list');
    if (!el) return;
    try {
      const rows = await API.contracts({ limit: 5, timespan: '30d' });
      el.textContent = '';
      if (!rows.length) { el.textContent = 'No contracts in the last 30 days.'; return; }
      el.appendChild(renderWidgetItems(rows, (div, r) => {
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        title.title = r.title || '';
        title.textContent = r.title || 'Untitled';
        const amt = document.createElement('span');
        amt.className = 'widget-item__amount';
        amt.style.color = 'var(--contracts)';
        amt.textContent = fmtAmount(r.amount);
        div.appendChild(title);
        div.appendChild(amt);
      }));
    } catch (err) {
      el.textContent = 'Failed to load contracts.';
      console.warn('[WATCH] Contracts widget error:', err.message);
    }
  }

  async function loadParliamentWidget() {
    const el = document.getElementById('widget-parliament-list');
    if (!el) return;
    try {
      const rows = await API.bills({ limit: 5 });
      el.textContent = '';
      if (!rows.length) { el.textContent = 'No recent bills.'; return; }
      el.appendChild(renderWidgetItems(rows, (div, r) => {
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        const prefix = r.bill_number ? r.bill_number + ' \u2014 ' : '';
        title.textContent = prefix + (r.title || 'Untitled');
        title.title = title.textContent;
        const badge = document.createElement('span');
        badge.className = 'widget-item__meta';
        const b = document.createElement('span');
        const status = r.status || 'unknown';
        const statusMap = { passed: 'passed', defeated: 'defeated', introduced: 'introduced', committee: 'committee', royal_assent: 'passed' };
        b.className = 'badge badge--' + (statusMap[status] || 'introduced');
        b.textContent = status.replace(/_/g, ' ');
        badge.appendChild(b);
        div.appendChild(title);
        div.appendChild(badge);
      }));
    } catch (err) {
      el.textContent = 'Failed to load parliament data.';
      console.warn('[WATCH] Parliament widget error:', err.message);
    }
  }

  async function loadSpendingWidget() {
    const el = document.getElementById('widget-spending-list');
    if (!el) return;
    try {
      const rows = await API.spending({ limit: 5 });
      el.textContent = '';
      if (!rows.length) { el.textContent = 'No spending records.'; return; }
      el.appendChild(renderWidgetItems(rows, (div, r) => {
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        title.textContent = r.department || 'Unknown';
        title.title = r.department || '';
        const amt = document.createElement('span');
        amt.className = 'widget-item__amount';
        amt.style.color = 'var(--spending)';
        amt.textContent = fmtAmount(r.amount);
        div.appendChild(title);
        div.appendChild(amt);
      }));
    } catch (err) {
      el.textContent = 'Failed to load spending data.';
      console.warn('[WATCH] Spending widget error:', err.message);
    }
  }

  async function loadEventsWidget() {
    const el = document.getElementById('widget-events-list');
    if (!el) return;
    try {
      const rows = await API.events({ limit: 5, timespan: '7d' });
      el.textContent = '';
      if (!rows.length) { el.textContent = 'No events in the last 7 days.'; return; }
      el.appendChild(renderWidgetItems(rows, (div, r) => {
        const title = document.createElement('span');
        title.className = 'widget-item__title';
        const type = r.event_type || '?';
        const typeSpan = document.createElement('span');
        const typeMap = { contract: 'contract', bill: 'bill', vote: 'vote', spending: 'spending' };
        typeSpan.className = 'badge badge--' + (typeMap[type] || 'contract');
        typeSpan.textContent = type;
        title.appendChild(typeSpan);
        title.appendChild(document.createTextNode(' ' + (r.title || r.description || 'Event')));
        const meta = document.createElement('span');
        meta.className = 'widget-item__meta';
        meta.textContent = fmtDate(r.event_date);
        div.appendChild(title);
        div.appendChild(meta);
      }));
    } catch (err) {
      el.textContent = 'Failed to load events.';
      console.warn('[WATCH] Events widget error:', err.message);
    }
  }

  function init() {
    loadStats();
    loadContractsWidget();
    loadParliamentWidget();
    loadSpendingWidget();
    loadEventsWidget();
  }

  if (typeof registerTabInit === 'function') {
    registerTabInit('dashboard', init);
  }
})();
