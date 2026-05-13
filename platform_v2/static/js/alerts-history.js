/* alerts-history.js — fetch, render, filter, paginate DHQ System Alerts History */
/* All innerHTML calls pass content through _esc() — same pattern as dispatch-history.js */
(function () {
  'use strict';

  var BASE = '/tools/department-hq/api/alerts/history';
  var _page = 1;
  var _debounceTimer = null;

  var TYPE_COLORS = {
    error:   '#ef4444',
    warning: '#f59e0b',
    alert:   '#f97316',
    info:    '#00e5ff',
    success: '#10b981'
  };

  /* Public API */

  window.ahFetch = function (resetPage) {
    if (resetPage) _page = 1;
    fetch(BASE + '?' + _params())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _renderStats(data.stats || {});
        _renderTable(data.rows || []);
        _renderPagination(data.page, data.pages, data.total);
      })
      .catch(function (err) { console.error('Alerts history fetch failed', err); });
  };

  window.ahPage = function (delta) {
    _page = Math.max(1, _page + delta);
    window.ahFetch();
  };

  window.ahReset = function () {
    document.getElementById('ahFilterType').value = 'all';
    document.getElementById('ahFilterPriority').value = 'all';
    document.getElementById('ahFilterStatus').value = 'all';
    document.getElementById('ahFilterQ').value = '';
    _setDefaultDates();
    window.ahFetch(true);
  };

  window.ahDebounce = function () {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(function () { window.ahFetch(true); }, 400);
  };

  window.ahToggleRow = function (id) {
    var detail = document.getElementById('ah-detail-' + id);
    var row = document.getElementById('ah-row-' + id);
    if (!detail || !row) return;
    var hidden = detail.style.display === 'none' || detail.style.display === '';
    detail.style.display = hidden ? 'table-row' : 'none';
    row.style.opacity = hidden ? '0.8' : '1';
  };

  window.ahInit = function () {
    if (window._ahInitDone) return;
    window._ahInitDone = true;
    _setDefaultDates();
    window.ahFetch(true);
  };

  /* Private */

  function _params() {
    var p = new URLSearchParams();
    p.set('type',      _val('ahFilterType'));
    p.set('priority',  _val('ahFilterPriority'));
    p.set('status',    _val('ahFilterStatus'));
    p.set('from_date', _val('ahFilterFrom'));
    p.set('to_date',   _val('ahFilterTo'));
    p.set('q',         _val('ahFilterQ'));
    p.set('page', _page);
    return p.toString();
  }

  function _val(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function _renderStats(s) {
    var el = document.getElementById('ahStats');
    if (!el) return;
    el.innerHTML =
      _chip('TOTAL',      s.total        || 0, '#00e5ff') + ' ' +
      _chip('UNREAD',     s.unread       || 0, '#f59e0b') + ' ' +
      _chip('ERRORS 24H', s.errors_24h   || 0, '#ef4444') + ' ' +
      _chip('WARN 24H',   s.warnings_24h || 0, '#f97316');
    var badge = document.getElementById('ahTotalBadge');
    if (badge) badge.textContent = '(' + (s.total || 0) + ')';
  }

  function _chip(label, value, color) {
    return '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;' +
      'padding:3px 8px;border-radius:3px;background:rgba(0,0,0,0.3);' +
      'border:1px solid ' + color + '40;display:inline-block;">' +
      '<span style="color:' + color + ';font-weight:600;">' + Number(value) + '</span>' +
      ' <span style="color:var(--dhq-text-dim);letter-spacing:1px;">' + label + '</span>' +
      '</span>';
  }

  function _renderTable(rows) {
    var tbody = document.getElementById('ahTableBody');
    if (!tbody) return;
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="padding:16px;text-align:center;' +
        'color:var(--dhq-text-dim);font-size:0.78rem;">No alerts in this range</td></tr>';
      return;
    }
    var html = '';
    rows.forEach(function (r) {
      var ts = r.created_at ? _esc(r.created_at.replace('T', ' ').slice(0, 16)) : '—';
      var dot = !r.is_read
        ? '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;' +
          'background:#00e5ff;margin-right:5px;vertical-align:middle;"></span>'
        : '';
      html +=
        '<tr id="ah-row-' + Number(r.id) + '" onclick="ahToggleRow(' + Number(r.id) + ')" ' +
        'style="cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.05);" ' +
        'onmouseover="this.style.background=\'rgba(0,229,255,0.03)\'" ' +
        'onmouseout="this.style.background=\'\'">' +
        '<td style="padding:6px 8px;white-space:nowrap;color:var(--dhq-text-dim);' +
          'font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;">' + ts + '</td>' +
        '<td style="padding:6px 8px;font-size:0.72rem;">' +
          _esc(r.source_icon || '📋') + ' ' + _esc(r.source || '') + '</td>' +
        '<td style="padding:6px 8px;">' + _typeBadge(r.type) + '</td>' +
        '<td style="padding:6px 8px;">' + _priorityBadge(r.priority) + '</td>' +
        '<td style="padding:6px 8px;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
          dot + _esc(r.title || r.message || '') + '</td>' +
        '<td style="padding:6px 8px;text-align:center;font-size:0.75rem;">' +
          (r.telegram_forwarded ? '<span title="Telegram forwarded" style="opacity:0.5;">&#x2708;</span>' : '') +
        '</td></tr>' +
        '<tr id="ah-detail-' + Number(r.id) + '" style="display:none;background:rgba(0,0,0,0.2);">' +
        '<td colspan="6" style="padding:8px 14px;">' + _renderDetail(r) + '</td></tr>';
    });
    tbody.innerHTML = html;
  }

  function _renderDetail(r) {
    var parts = [];
    if (r.message && r.message !== r.title) {
      parts.push('<div style="font-size:0.78rem;margin-bottom:6px;line-height:1.4;">' +
        _esc(r.message) + '</div>');
    }
    if (r.related_action) {
      parts.push('<div style="font-size:0.7rem;color:var(--dhq-text-dim);">Action: ' +
        _esc(r.related_action) + '</div>');
    }
    if (r.grouped_count && r.grouped_count > 1) {
      parts.push('<div style="font-size:0.7rem;color:var(--dhq-text-dim);">Grouped: ' +
        Number(r.grouped_count) + ' events</div>');
    }
    if (r.metadata && typeof r.metadata === 'object' && Object.keys(r.metadata).length) {
      parts.push('<pre style="font-size:0.65rem;color:var(--dhq-text-dim);margin:4px 0;' +
        'white-space:pre-wrap;word-break:break-all;">' +
        _esc(JSON.stringify(r.metadata, null, 2)) + '</pre>');
    }
    return parts.length
      ? parts.join('')
      : '<span style="color:var(--dhq-text-dim);font-size:0.75rem;">No additional details</span>';
  }

  function _renderPagination(page, pages, total) {
    var el = document.getElementById('ahPagination');
    if (!el) return;
    if (!pages || pages <= 1) { el.innerHTML = ''; return; }
    var btnStyle = 'background:none;border:1px solid rgba(255,255,255,0.2);' +
      'color:var(--dhq-text-dim);padding:2px 10px;border-radius:3px;cursor:pointer;';
    el.innerHTML =
      '<button onclick="ahPage(-1)" ' + (page <= 1 ? 'disabled' : '') +
        ' style="' + btnStyle + '">&#9664;</button>' +
      '<span style="color:var(--dhq-text-dim);font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;">' +
        'Page ' + Number(page) + ' / ' + Number(pages) + ' — ' + Number(total) + ' total</span>' +
      '<button onclick="ahPage(1)" ' + (page >= pages ? 'disabled' : '') +
        ' style="' + btnStyle + '">&#9654;</button>';
  }

  function _typeBadge(type) {
    var safeType = _esc((type || '').toUpperCase());
    var color = TYPE_COLORS[type] || '#888888';
    return '<span style="font-size:0.65rem;font-family:\'IBM Plex Mono\',monospace;' +
      'padding:1px 6px;border-radius:3px;background:' + color + '22;color:' + color + ';' +
      'border:1px solid ' + color + '44;letter-spacing:1px;">' + safeType + '</span>';
  }

  function _priorityBadge(priority) {
    if (!priority || priority === 'normal') return '';
    var safePriority = _esc(priority.toUpperCase());
    var color = priority === 'critical' ? '#ef4444' : '#f97316';
    return '<span style="font-size:0.6rem;font-family:\'IBM Plex Mono\',monospace;' +
      'padding:1px 5px;border-radius:3px;background:' + color + '22;color:' + color + ';' +
      'border:1px solid ' + color + '44;letter-spacing:1px;margin-left:4px;">' +
      safePriority + '</span>';
  }

  function _setDefaultDates() {
    var now = new Date();
    var toEl  = document.getElementById('ahFilterTo');
    var fromEl = document.getElementById('ahFilterFrom');
    if (toEl)   toEl.value   = now.toISOString().slice(0, 10);
    if (fromEl) fromEl.value = new Date(now - 7 * 86400000).toISOString().slice(0, 10);
  }

  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

}());
