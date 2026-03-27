/* W.A.T.C.H. Events tab — unified civic event feed */
(function () {
  'use strict';

  const TYPE_COLORS = {
    contract: 'var(--contracts)',
    bill: 'var(--parliament)',
    vote: 'var(--red)',
    spending: 'var(--spending)',
  };

  function renderFeed(container, rows) {
    container.textContent = '';
    if (!rows.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      const icon = document.createElement('div');
      icon.className = 'empty-state__icon';
      icon.textContent = '\uD83D\uDD0D';
      const msg = document.createElement('p');
      msg.textContent = 'No events found for the selected filters.';
      empty.appendChild(icon);
      empty.appendChild(msg);
      container.appendChild(empty);
      return;
    }

    rows.forEach(r => {
      const card = document.createElement('div');
      card.style.cssText = 'background:var(--surface);border-radius:4px;padding:14px 16px;margin-bottom:10px;display:flex;gap:14px;align-items:flex-start;border-left:3px solid ' + (TYPE_COLORS[r.event_type] || 'var(--border)');

      // Type badge column
      const badgeCol = document.createElement('div');
      badgeCol.style.cssText = 'min-width:72px;padding-top:2px';
      const badge = document.createElement('span');
      badge.className = 'badge badge--' + (r.event_type || 'contract');
      badge.textContent = r.event_type || '?';
      badgeCol.appendChild(badge);

      // Content column
      const content = document.createElement('div');
      content.style.flex = '1';

      const titleRow = document.createElement('div');
      titleRow.style.cssText = 'display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:4px';

      const titleEl = document.createElement('div');
      titleEl.style.cssText = 'font-size:0.88rem;font-weight:500;line-height:1.4';
      if (r.source_url) {
        const a = document.createElement('a');
        a.href = r.source_url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = r.title || r.description || 'Civic Event';
        titleEl.appendChild(a);
      } else {
        titleEl.textContent = r.title || r.description || 'Civic Event';
      }

      const dateEl = document.createElement('div');
      dateEl.style.cssText = 'font-size:0.72rem;color:var(--text-dim);white-space:nowrap;font-family:var(--font-data)';
      dateEl.textContent = fmtDate(r.event_date);

      titleRow.appendChild(titleEl);
      titleRow.appendChild(dateEl);
      content.appendChild(titleRow);

      // Meta row
      const metaRow = document.createElement('div');
      metaRow.style.cssText = 'display:flex;gap:12px;flex-wrap:wrap;font-size:0.72rem;color:var(--text-dim)';

      if (r.jurisdiction) {
        const jur = document.createElement('span');
        jur.textContent = '\uD83D\uDDFA\uFE0F ' + r.jurisdiction;
        metaRow.appendChild(jur);
      }
      if (r.level) {
        const lvlBadge = document.createElement('span');
        lvlBadge.className = 'badge badge--' + r.level;
        lvlBadge.textContent = r.level;
        metaRow.appendChild(lvlBadge);
      }
      if (r.amount) {
        const amt = document.createElement('span');
        amt.style.color = TYPE_COLORS[r.event_type] || 'var(--text)';
        amt.style.fontFamily = 'var(--font-data)';
        amt.style.fontWeight = '600';
        amt.textContent = fmtAmount(r.amount);
        metaRow.appendChild(amt);
      }
      if (r.department) {
        const dept = document.createElement('span');
        dept.textContent = r.department;
        metaRow.appendChild(dept);
      }
      content.appendChild(metaRow);

      card.appendChild(badgeCol);
      card.appendChild(content);
      container.appendChild(card);
    });
  }

  async function loadEvents() {
    const feed = document.getElementById('events-feed');
    if (!feed) return;
    feed.textContent = '';
    const loading = document.createElement('div');
    loading.className = 'loading';
    loading.textContent = 'Loading events…';
    feed.appendChild(loading);

    try {
      // Collect checked types
      const typeCheckboxes = document.querySelectorAll('#events-filters input[name="type"]:checked');
      const types = Array.from(typeCheckboxes).map(cb => cb.value);
      const params = {
        type: types.join(','),
        level: document.getElementById('events-level')?.value || '',
        timespan: document.getElementById('events-timespan')?.value || '7d',
        limit: 100,
      };
      const rows = await API.events(params);
      renderFeed(feed, rows);
    } catch (err) {
      feed.textContent = '';
      const errDiv = document.createElement('div');
      errDiv.style.cssText = 'text-align:center;padding:32px;color:var(--red)';
      errDiv.textContent = 'Failed to load events: ' + err.message;
      feed.appendChild(errDiv);
    }
  }

  function init() {
    const form = document.getElementById('events-filters');
    if (form) {
      form.addEventListener('submit', e => { e.preventDefault(); loadEvents(); });
    }
    loadEvents();
  }

  if (typeof registerTabInit === 'function') {
    registerTabInit('events', init);
  }
})();
