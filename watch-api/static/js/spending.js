/* W.A.T.C.H. Spending tab */
(function () {
  'use strict';

  let currentParams = {};

  function renderRows(tbody, rows) {
    tbody.textContent = '';
    if (!rows.length) {
      const tr = tbody.insertRow(); const td = tr.insertCell();
      td.colSpan = 6; td.textContent = 'No spending records found.';
      td.style.cssText = 'text-align:center;padding:32px;color:var(--text-dim)';
      return;
    }
    rows.forEach(r => {
      const tr = tbody.insertRow();
      tr.insertCell().textContent = r.department || '—';
      tr.insertCell().textContent = r.jurisdiction || '—';
      // Level badge
      const tdLevel = tr.insertCell();
      const lvl = r.level || 'federal';
      const badge = document.createElement('span');
      badge.className = 'badge badge--' + lvl;
      badge.textContent = lvl;
      tdLevel.appendChild(badge);
      tr.insertCell().textContent = r.category || '—';
      const tdAmt = tr.insertCell();
      tdAmt.className = 'amount';
      tdAmt.textContent = fmtAmount(r.amount);
      tr.insertCell().textContent = r.fiscal_year || '—';
    });
  }

  async function loadSpending(params) {
    const tbody = document.getElementById('spending-tbody');
    if (!tbody) return;
    tbody.textContent = '';
    const tr = tbody.insertRow(); const td = tr.insertCell();
    td.colSpan = 6; td.textContent = 'Loading…';
    td.style.cssText = 'text-align:center;padding:32px;color:var(--text-dim)';
    try {
      const rows = await API.spending(params);
      renderRows(tbody, rows);
    } catch (err) {
      tbody.textContent = '';
      const tr2 = tbody.insertRow(); const td2 = tr2.insertCell();
      td2.colSpan = 6; td2.textContent = 'Failed to load spending: ' + err.message;
      td2.style.cssText = 'text-align:center;padding:32px;color:var(--red)';
    }
  }

  function getFilterParams() {
    return {
      level: document.getElementById('spending-level')?.value || '',
      jurisdiction: document.getElementById('spending-jurisdiction')?.value || '',
      department: document.getElementById('spending-department')?.value || '',
      category: document.getElementById('spending-category')?.value || '',
      limit: 50,
    };
  }

  function exportCSV(rows) {
    const headers = ['Department', 'Jurisdiction', 'Level', 'Category', 'Amount', 'Fiscal Year'];
    const lines = [headers.join(',')];
    rows.forEach(r => {
      lines.push([
        JSON.stringify(r.department || ''),
        JSON.stringify(r.jurisdiction || ''),
        r.level || '',
        r.category || '',
        r.amount || '',
        r.fiscal_year || '',
      ].join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'watch-spending.csv'; a.click();
    URL.revokeObjectURL(url);
  }

  function init() {
    const form = document.getElementById('spending-filters');
    if (form) {
      form.addEventListener('submit', e => {
        e.preventDefault();
        currentParams = getFilterParams();
        loadSpending(currentParams);
      });
    }
    const exportBtn = document.getElementById('spending-export');
    if (exportBtn) {
      exportBtn.addEventListener('click', async () => {
        try {
          const rows = await API.spending({ ...currentParams, limit: 500 });
          exportCSV(rows);
        } catch (err) { alert('Export failed: ' + err.message); }
      });
    }
    currentParams = getFilterParams();
    loadSpending(currentParams);
  }

  if (typeof registerTabInit === 'function') {
    registerTabInit('spending', init);
  }
})();
