/* W.A.T.C.H. Contracts tab */
(function () {
  'use strict';

  let currentParams = {};

  // ── Table rendering ──────────────────────────────────────────────────────────

  function renderRows(tbody, rows) {
    tbody.textContent = '';
    if (!rows.length) {
      const tr = tbody.insertRow();
      const td = tr.insertCell();
      td.colSpan = 6;
      td.textContent = 'No contracts found.';
      td.style.cssText = 'text-align:center;padding:32px;color:var(--text-dim)';
      return;
    }
    rows.forEach(r => {
      const tr = tbody.insertRow();
      // Title (with optional source link)
      const tdTitle = tr.insertCell();
      if (r.source_url) {
        const a = document.createElement('a');
        a.href = r.source_url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.textContent = r.title || 'Untitled';
        tdTitle.appendChild(a);
      } else {
        tdTitle.textContent = r.title || 'Untitled';
      }
      // Department
      tr.insertCell().textContent = r.department || '—';
      // Jurisdiction
      tr.insertCell().textContent = r.jurisdiction || '—';
      // Level badge
      const tdLevel = tr.insertCell();
      const badge = document.createElement('span');
      const lvl = r.level || 'federal';
      badge.className = 'badge badge--' + lvl;
      badge.textContent = lvl;
      tdLevel.appendChild(badge);
      // Amount
      const tdAmt = tr.insertCell();
      tdAmt.className = 'amount';
      tdAmt.textContent = fmtAmount(r.amount);
      // Date
      tr.insertCell().textContent = fmtDate(r.event_date);
    });
  }

  async function loadContracts(params) {
    const tbody = document.getElementById('contracts-tbody');
    if (!tbody) return;
    tbody.textContent = '';
    const tr = tbody.insertRow();
    const td = tr.insertCell();
    td.colSpan = 6;
    td.textContent = 'Loading…';
    td.style.cssText = 'text-align:center;padding:32px;color:var(--text-dim)';
    try {
      const rows = await API.contracts(params);
      renderRows(tbody, rows);
    } catch (err) {
      tbody.textContent = '';
      const tr2 = tbody.insertRow();
      const td2 = tr2.insertCell();
      td2.colSpan = 6;
      td2.textContent = 'Failed to load contracts: ' + err.message;
      td2.style.cssText = 'text-align:center;padding:32px;color:var(--red)';
    }
  }

  // ── Filters ──────────────────────────────────────────────────────────────────

  function getFilterParams() {
    return {
      level: document.getElementById('contracts-level')?.value || '',
      jurisdiction: document.getElementById('contracts-jurisdiction')?.value || '',
      department: document.getElementById('contracts-department')?.value || '',
      min_amount: document.getElementById('contracts-amount-min')?.value || '',
      limit: 50,
      timespan: '90d',
    };
  }

  // ── CSV Export ───────────────────────────────────────────────────────────────

  function exportCSV(rows) {
    const headers = ['Title', 'Department', 'Jurisdiction', 'Level', 'Amount', 'Date'];
    const lines = [headers.join(',')];
    rows.forEach(r => {
      lines.push([
        JSON.stringify(r.title || ''),
        JSON.stringify(r.department || ''),
        JSON.stringify(r.jurisdiction || ''),
        r.level || '',
        r.amount || '',
        r.event_date || '',
      ].join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'watch-contracts.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Init ─────────────────────────────────────────────────────────────────────

  function init() {
    const form = document.getElementById('contracts-filters');
    if (form) {
      form.addEventListener('submit', e => {
        e.preventDefault();
        currentParams = getFilterParams();
        loadContracts(currentParams);
      });
    }

    const exportBtn = document.getElementById('contracts-export');
    if (exportBtn) {
      exportBtn.addEventListener('click', async () => {
        try {
          const rows = await API.contracts({ ...currentParams, limit: 500 });
          exportCSV(rows);
        } catch (err) {
          alert('Export failed: ' + err.message);
        }
      });
    }

    currentParams = getFilterParams();
    loadContracts(currentParams);
  }

  if (typeof registerTabInit === 'function') {
    registerTabInit('contracts', init);
  }
})();
