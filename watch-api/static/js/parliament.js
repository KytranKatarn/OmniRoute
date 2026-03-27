/* W.A.T.C.H. Parliament tab — Bills + Votes toggle */
(function () {
  'use strict';

  // ── Bills ────────────────────────────────────────────────────────────────────

  function renderBills(tbody, rows) {
    tbody.textContent = '';
    if (!rows.length) {
      const tr = tbody.insertRow(); const td = tr.insertCell();
      td.colSpan = 5; td.textContent = 'No bills found.';
      td.style.cssText = 'text-align:center;padding:32px;color:var(--text-dim)';
      return;
    }
    rows.forEach(r => {
      const tr = tbody.insertRow();
      // Bill number
      tr.insertCell().textContent = r.bill_number || '—';
      // Title with optional link
      const tdTitle = tr.insertCell();
      if (r.source_url) {
        const a = document.createElement('a');
        a.href = r.source_url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = r.title || 'Untitled';
        tdTitle.appendChild(a);
      } else {
        tdTitle.textContent = r.title || 'Untitled';
      }
      // Sponsor
      tr.insertCell().textContent = r.sponsor || '—';
      // Status badge
      const tdStatus = tr.insertCell();
      const badge = document.createElement('span');
      const statusMap = { passed: 'passed', defeated: 'defeated', introduced: 'introduced', committee: 'committee', royal_assent: 'passed' };
      const s = r.status || 'introduced';
      badge.className = 'badge badge--' + (statusMap[s] || 'introduced');
      badge.textContent = s.replace(/_/g, ' ');
      tdStatus.appendChild(badge);
      // Date
      tr.insertCell().textContent = fmtDate(r.last_activity_date);
    });
  }

  async function loadBills() {
    const tbody = document.getElementById('bills-tbody');
    if (!tbody) return;
    tbody.textContent = '';
    const tr = tbody.insertRow(); const td = tr.insertCell();
    td.colSpan = 5; td.textContent = 'Loading bills…';
    td.style.cssText = 'text-align:center;padding:24px;color:var(--text-dim)';
    try {
      const params = {
        status: document.getElementById('bills-status')?.value || '',
        sponsor: document.getElementById('bills-sponsor')?.value || '',
        keyword: document.getElementById('bills-keyword')?.value || '',
        limit: 50,
      };
      const rows = await API.bills(params);
      renderBills(tbody, rows);
    } catch (err) {
      tbody.textContent = '';
      const tr2 = tbody.insertRow(); const td2 = tr2.insertCell();
      td2.colSpan = 5; td2.textContent = 'Failed to load bills: ' + err.message;
      td2.style.cssText = 'text-align:center;padding:24px;color:var(--red)';
    }
  }

  // ── Votes ────────────────────────────────────────────────────────────────────

  function renderVotes(tbody, rows) {
    tbody.textContent = '';
    if (!rows.length) {
      const tr = tbody.insertRow(); const td = tr.insertCell();
      td.colSpan = 5; td.textContent = 'No votes found.';
      td.style.cssText = 'text-align:center;padding:32px;color:var(--text-dim)';
      return;
    }
    rows.forEach(r => {
      const tr = tbody.insertRow();
      // Vote number
      tr.insertCell().textContent = r.vote_number || '—';
      // Description
      tr.insertCell().textContent = r.description || '—';
      // Result badge
      const tdResult = tr.insertCell();
      const badge = document.createElement('span');
      const res = (r.result || '').toLowerCase();
      badge.className = 'badge badge--' + (res === 'passed' ? 'passed' : 'defeated');
      badge.textContent = r.result || '—';
      tdResult.appendChild(badge);
      // Yeas / Nays with vote bar
      const tdVotes = tr.insertCell();
      const yeas = Number(r.yeas || 0);
      const nays = Number(r.nays || 0);
      const total = yeas + nays || 1;
      const bar = document.createElement('div');
      bar.className = 'vote-bar';
      bar.title = `Yeas: ${yeas} / Nays: ${nays}`;
      const yeaFill = document.createElement('div');
      yeaFill.className = 'vote-bar__yea';
      yeaFill.style.width = ((yeas / total) * 100).toFixed(1) + '%';
      const nayFill = document.createElement('div');
      nayFill.className = 'vote-bar__nay';
      nayFill.style.flex = '1';
      bar.appendChild(yeaFill);
      bar.appendChild(nayFill);
      const label = document.createElement('div');
      label.style.cssText = 'font-size:0.7rem;color:var(--text-dim);margin-top:2px';
      label.textContent = yeas + ' / ' + nays;
      tdVotes.appendChild(bar);
      tdVotes.appendChild(label);
      // Date
      tr.insertCell().textContent = fmtDate(r.vote_date);
    });
  }

  async function loadVotes() {
    const tbody = document.getElementById('votes-tbody');
    if (!tbody) return;
    tbody.textContent = '';
    const tr = tbody.insertRow(); const td = tr.insertCell();
    td.colSpan = 5; td.textContent = 'Loading votes…';
    td.style.cssText = 'text-align:center;padding:24px;color:var(--text-dim)';
    try {
      const params = {
        result: document.getElementById('votes-result')?.value || '',
        keyword: document.getElementById('votes-keyword')?.value || '',
        recent: 'true',
        limit: 50,
      };
      const rows = await API.votes(params);
      renderVotes(tbody, rows);
    } catch (err) {
      tbody.textContent = '';
      const tr2 = tbody.insertRow(); const td2 = tr2.insertCell();
      td2.colSpan = 5; td2.textContent = 'Failed to load votes: ' + err.message;
      td2.style.cssText = 'text-align:center;padding:24px;color:var(--red)';
    }
  }

  // ── Toggle ───────────────────────────────────────────────────────────────────

  function setupToggle() {
    const toggleBtns = document.querySelectorAll('[data-parliament-view]');
    const billsSection = document.getElementById('parliament-bills-section');
    const votesSection = document.getElementById('parliament-votes-section');
    let votesLoaded = false;

    toggleBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.parliamentView;
        toggleBtns.forEach(b => b.classList.toggle('active', b === btn));
        if (view === 'bills') {
          billsSection && billsSection.classList.remove('hidden');
          votesSection && votesSection.classList.add('hidden');
        } else {
          billsSection && billsSection.classList.add('hidden');
          votesSection && votesSection.classList.remove('hidden');
          if (!votesLoaded) { votesLoaded = true; loadVotes(); }
        }
      });
    });
  }

  // ── Filters ──────────────────────────────────────────────────────────────────

  function setupFilters() {
    const billsForm = document.getElementById('bills-filters');
    if (billsForm) billsForm.addEventListener('submit', e => { e.preventDefault(); loadBills(); });
    const votesForm = document.getElementById('votes-filters');
    if (votesForm) votesForm.addEventListener('submit', e => { e.preventDefault(); loadVotes(); });
  }

  // ── Init ─────────────────────────────────────────────────────────────────────

  function init() {
    setupToggle();
    setupFilters();
    loadBills();
  }

  if (typeof registerTabInit === 'function') {
    registerTabInit('parliament', init);
  }
})();
