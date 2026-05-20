/* dispatch-history.js — fetch, render, paginate the DHQ Dispatch History section */
(function () {
  'use strict';

  var BASE = '/tools/department-hq/api/dispatch/history';
  var _page = 1;
  var _debounceTimer = null;

  /* Public API — called from onclick attrs in the template */

  window.dhFetch = function (resetPage) {
    if (resetPage) _page = 1;
    fetch(BASE + '?' + _params())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _renderStats(data.stats || {});
        _renderTable(data.rows || []);
        _renderPagination(data.page, data.pages, data.total);
      })
      .catch(function (err) { console.error('Dispatch history fetch failed', err); });
  };

  window.dhPage = function (delta) {
    _page = Math.max(1, _page + delta);
    window.dhFetch();
  };

  window.dhReset = function () {
    document.getElementById('dhFilterAgent').value = '';
    document.getElementById('dhFilterCapability').value = '';
    document.getElementById('dhFilterSource').value = 'all';
    document.getElementById('dhFilterQ').value = '';
    _setDefaultDates();
    window.dhFetch(true);
  };

  window.dhDebounce = function () {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(function () { window.dhFetch(true); }, 400);
  };

  window.dhToggleRow = function (idx) {
    var detail = document.getElementById('dh-detail-' + idx);
    var row = document.getElementById('dh-row-' + idx);
    if (!detail || !row) return;
    var hidden = detail.style.display === 'none' || detail.style.display === '';
    detail.style.display = hidden ? 'table-row' : 'none';
    row.classList.toggle('dh-row-expanded', hidden);
  };

  /* Init — call once when Dispatch tab first opens */

  window.dhInit = function () {
    if (window._dhInitDone) return;
    window._dhInitDone = true;

    /* Set default date range: last 7 days */
    _setDefaultDates();

    /* Populate agent dropdown */
    fetch(BASE + '/agents')
      .then(function (r) { return r.json(); })
      .then(function (agents) {
        var sel = document.getElementById('dhFilterAgent');
        agents.forEach(function (a) {
          var opt = document.createElement('option');
          opt.value = a;
          opt.textContent = a;
          sel.appendChild(opt);
        });
      })
      .catch(function (err) { console.error('Failed to load dispatch history agents', err); });

    /* Populate capability dropdown */
    fetch(BASE + '/capabilities')
      .then(function (r) { return r.json(); })
      .then(function (caps) {
        var sel = document.getElementById('dhFilterCapability');
        caps.forEach(function (c) {
          var opt = document.createElement('option');
          opt.value = c;
          opt.textContent = c;
          sel.appendChild(opt);
        });
      })
      .catch(function (err) { console.error('Failed to load dispatch history capabilities', err); });

    window.dhFetch();
  };

  /* Private helpers */

  function _params() {
    return new URLSearchParams({
      agent:      document.getElementById('dhFilterAgent').value,
      capability: document.getElementById('dhFilterCapability').value,
      source:     document.getElementById('dhFilterSource').value,
      from:       document.getElementById('dhFilterFrom').value,
      to:         document.getElementById('dhFilterTo').value,
      q:          document.getElementById('dhFilterQ').value,
      page:       _page,
      per_page:   document.getElementById('dhPerPage').value,
    }).toString();
  }

  function _renderStats(s) {
    _setVal('dhStatTotal',    '.dh-stat-value', String((s.total_calls || 0).toLocaleString()));
    _setVal('dhStatSuccess',  '.dh-stat-value', (s.success_rate  || 0).toFixed(1) + '%');
    _setVal('dhStatDuration', '.dh-stat-value', (s.avg_duration_s || 0).toFixed(1) + 's');
    var ag = document.getElementById('dhStatTopAgent');
    var mo = document.getElementById('dhStatTopModule');
    if (ag) ag.textContent = s.top_agent  || '—';
    if (mo) mo.textContent = s.top_module || '—';
  }

  function _renderTable(rows) {
    var tbody = document.getElementById('dhHistoryBody');
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

    if (!rows.length) {
      var emptyTr = document.createElement('tr');
      var emptyTd = document.createElement('td');
      emptyTd.colSpan = 9;
      emptyTd.style.cssText = 'text-align:center;opacity:0.5;';
      emptyTd.textContent = 'No records found';
      emptyTr.appendChild(emptyTd);
      tbody.appendChild(emptyTr);
      return;
    }

    rows.forEach(function (r, i) {
      /* Data row — all user-derived values via textContent */
      var tr = document.createElement('tr');
      tr.className = 'dh-row';
      tr.id = 'dh-row-' + i;
      tr.setAttribute('onclick', 'dhToggleRow(' + i + ')');

      /* Time — ArchieTime can't parse +00:00 suffix; strip it first */
      var timeTd = document.createElement('td');
      var timeStr = '—';
      if (r.created_at) {
        try {
          var tsClean = r.created_at.replace(/([+-]\d{2}:\d{2}|Z)$/, '');
          timeStr = (typeof ArchieTime !== 'undefined' && typeof ArchieTime.format === 'function')
            ? ArchieTime.format(tsClean, 'datetime')
            : tsClean.replace('T', ' ').substring(0, 16);
        } catch (_) {
          timeStr = r.created_at.replace('T', ' ').substring(0, 16);
        }
      }
      timeTd.textContent = timeStr;
      tr.appendChild(timeTd);

      /* Source badge */
      var srcTd = document.createElement('td');
      var srcSpan = document.createElement('span');
      srcSpan.className = r.source === 'task' ? 'dh-badge-task' : 'dh-badge-job';
      srcSpan.textContent = r.source === 'task' ? 'TASK' : 'JOB';
      srcTd.appendChild(srcSpan);
      tr.appendChild(srcTd);

      /* Text cells — textContent only */
      _appendTd(tr, r.agent_name);
      _appendTd(tr, r.capability);
      _appendTd(tr, r.module);
      // Node column — shows which fleet node handled the request
      var nodeTd = document.createElement('td');
      var nodeVal = r.node_name || 'Hub';
      // Short labels for fleet nodes
      nodeVal = nodeVal.replace('Archie Starbase', 'Hub').replace('Starship-', '.').replace('outpost-us', 'outpost');
      nodeTd.textContent = nodeVal;
      nodeTd.style.color = nodeVal === 'Hub' ? 'var(--dhq-text-dim)' : '#00bcd4';
      nodeTd.style.fontFamily = '\'IBM Plex Mono\',monospace';
      nodeTd.style.fontSize = '0.68rem';
      tr.appendChild(nodeTd);
      _appendTd(tr, r.model_used ? r.model_used.split(':')[0] : '—');

      /* Duration — colour-coded */
      var durTd = document.createElement('td');
      durTd.appendChild(_durSpan(r.duration_ms));
      tr.appendChild(durTd);

      /* Status */
      var statTd = document.createElement('td');
      statTd.textContent = r.success ? '✅' : '❌';
      statTd.style.color  = r.success ? '#4ade80' : '#f87171';
      tr.appendChild(statTd);

      tbody.appendChild(tr);

      /* Detail row (hidden, expands on click) */
      var detailTr = document.createElement('tr');
      detailTr.className = 'dh-detail-row';
      detailTr.id = 'dh-detail-' + i;
      detailTr.style.display = 'none';
      var detailTd = document.createElement('td');
      detailTd.colSpan = 9;
      var div = document.createElement('div');
      div.className = 'dh-expand-details';

      if (r.error_message) {
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'color:#f87171;margin-bottom:4px;';
        errDiv.textContent = 'Error: ' + r.error_message;
        div.appendChild(errDiv);
      }
      var meta = document.createElement('span');
      var cost = typeof r.cost === 'number' ? r.cost.toFixed(4) : '0.0000';
      meta.textContent = 'Tokens: ' + (r.tokens_used || 0)
        + '  |  Cost: $' + cost
        + '  |  ' + (r.created_at || '—');
      div.appendChild(meta);
      detailTd.appendChild(div);
      detailTr.appendChild(detailTd);
      tbody.appendChild(detailTr);
    });
  }

  function _renderPagination(page, pages, total) {
    var info = document.getElementById('dhPageInfo');
    if (info) info.textContent = 'Page ' + page + ' of ' + pages
      + ' (' + (total || 0).toLocaleString() + ' total)';
    var prev = document.getElementById('dhPrevBtn');
    var next = document.getElementById('dhNextBtn');
    if (prev) prev.disabled = page <= 1;
    if (next) next.disabled = page >= pages;
    _page = page;
  }

  function _appendTd(tr, text) {
    var td = document.createElement('td');
    td.textContent = text || '—';
    tr.appendChild(td);
  }

  function _durSpan(ms) {
    var span = document.createElement('span');
    if (!ms) { span.style.opacity = '0.4'; span.textContent = '—'; return span; }
    span.className = ms < 30000 ? 'dh-dur-ok' : ms < 120000 ? 'dh-dur-mid' : 'dh-dur-bad';
    span.textContent = (ms / 1000).toFixed(1) + 's';
    return span;
  }

  function _setVal(parentId, sel, text) {
    var el = document.querySelector('#' + parentId + ' ' + sel);
    if (el) el.textContent = text;
  }

  function _fmtDate(d) {
    return d.toISOString().split('T')[0];
  }

  function _setDefaultDates() {
    var now = new Date();
    document.getElementById('dhFilterTo').value = _fmtDate(now);
    var from = new Date(now);
    from.setDate(from.getDate() - 7);
    document.getElementById('dhFilterFrom').value = _fmtDate(from);
  }

})();
