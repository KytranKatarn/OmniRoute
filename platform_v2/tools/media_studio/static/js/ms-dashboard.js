(function () {
  'use strict';
  var _API = '/tools/media-studio';
  var _timer = null;

  function _get(path) {
    return fetch(_API + path, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function _el(id) { return document.getElementById(id); }
  function _setText(id, val) { var el = _el(id); if (el) el.textContent = val != null ? val : '--'; }
  function _mediaSrc(item) {
    var path = item && (item.thumbnail_url || item.url || item.thumbnail_path || item.file_path);
    if (!path) return '';
    if (/^(https?:)?\/\//i.test(path) || path.charAt(0) === '/') return path;
    if (path.indexOf('static/') === 0) return '/' + path;
    return '/static/' + path;
  }

  // "6:25 PM" for today, "Oct 21, 6:25 PM" otherwise: a bare time is ambiguous once a row is a day old.
  function _when(iso) {
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return '';
    var time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    var now = new Date();
    if (d.toDateString() === now.toDateString()) return time;
    var opts = { month: 'short', day: 'numeric' };
    if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
    return d.toLocaleDateString([], opts) + ', ' + time;
  }

  window.msDashboard = {
    _showDismissed: false,
    _showTests: false,
    _failed24h: 0,
    _retryArmed: false,

    load: function () {
      var q = [];
      if (msDashboard._showDismissed) q.push('include_dismissed=1');
      if (msDashboard._showTests) q.push('include_tests=1');
      var url = '/api/dashboard' + (q.length ? '?' + q.join('&') : '');
      _get(url).then(function (d) {
        _setText('msDashStatGenerating', d.queue_active != null ? d.queue_active : (d.active_jobs || []).length);
        var pendingCount = d.pending_approval_count != null ? d.pending_approval_count : (d.pending_approvals || []).length;
        _setText('msDashStatApprovals', pendingCount);
        _setText('msDashStatSocial', d.social_queue_count != null ? d.social_queue_count : (d.social_queue || []).length);
        _setText('msDashStatTotal', d.total_generated != null ? d.total_generated : 0);
        msDashboard._failed24h = d.queue_failed_24h != null ? d.queue_failed_24h : (d.queue_failed || 0);
        _setText('msDashStatFailed', msDashboard._failed24h);
        _setText('msDashUpdated', 'Updated ' + new Date().toLocaleTimeString());
        msDashboard._renderSubLabels(d);
        msDashboard._renderGenerating(d.active_jobs || []);
        msDashboard._renderApprovals(d.pending_approvals || []);
        msDashboard._renderSocialQueue(d.social_queue || []);
        msDashboard._renderRecent(d.recent || []);
        msDashboard._renderShowDismissedToggle();
        msDashboard._renderRetryLink();
        msDashboard._loadGpuStrip();
      }).catch(function (err) { console.warn('[msDashboard] load failed:', err); });
    },

    _renderSubLabels: function (d) {
      var by = d.queue_by_status || {};
      var pending = (by.pending || 0) + (by.dispatched || 0);
      var running = by.generating || 0;
      _setText('msDashSubGenerating', pending + ' waiting \u00b7 ' + running + ' running');
      var pendingCount = d.pending_approval_count != null ? d.pending_approval_count : (d.pending_approvals || []).length;
      _setText('msDashSubApprovals', pendingCount + ' awaiting review');
      var sq = d.social_queue_by_status || {};
      var drafts = sq.draft || 0;
      var sched = sq.scheduled || 0;
      _setText('msDashSubSocial', drafts + ' draft \u00b7 ' + sched + ' scheduled');
      _setText('msDashSubTotal', (d.images || 0) + ' img \u00b7 ' + (d.videos || 0) + ' vid \u00b7 ' + (d.audio || 0) + ' aud');
      _setText('msDashSubFailed', (by.failed || 0) + ' all-time \u00b7 ' + (d.queue_completed_24h || 0) + ' completed (24h)');
    },

    toggleTests: function () {
      msDashboard._showTests = !msDashboard._showTests;
      msDashboard.load();
    },

    // Two-step confirm without a modal: the first click arms it ("click again"), the second one re-queues.
    _renderRetryLink: function () {
      var link = _el('msDashRetryFailed');
      if (!link) return;
      link.style.display = msDashboard._failed24h > 0 ? 'inline-block' : 'none';
      if (!msDashboard._retryArmed) link.textContent = '\u21BB Retry ' + msDashboard._failed24h + ' failed';
    },

    retryFailed: function () {
      var link = _el('msDashRetryFailed');
      if (!msDashboard._retryArmed) {
        msDashboard._retryArmed = true;
        if (link) link.textContent = 'Re-run ' + msDashboard._failed24h + ' jobs on the GPU? Click again to confirm';
        setTimeout(function () { msDashboard._retryArmed = false; msDashboard._renderRetryLink(); }, 5000);
        return;
      }
      msDashboard._retryArmed = false;
      fetch(_API + '/api/queue/retry-failed', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ hours: 24 })
      }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (res) {
        if (window.showMsToast) window.showMsToast('Re-queued ' + res.retried + ' of ' + res.found + ' failed jobs', 'success');
        msDashboard.load();
      }).catch(function (err) {
        if (window.showMsToast) window.showMsToast('Retry failed: ' + err, 'error');
      });
    },

    // One chip per GPU node: queue depth and the IMAGE SESSION tag. Text only (textContent), never innerHTML.
    _loadGpuStrip: function () {
      _get('/api/comfyui/queue').then(function (data) {
        var el = _el('msDashGpuStrip');
        if (!el) return;
        while (el.firstChild) el.removeChild(el.firstChild);
        (data.nodes || []).forEach(function (n) {
          var chip = document.createElement('span');
          chip.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:3px 8px;border-radius:4px;background:rgba(255,255,255,0.04);';
          var dot = document.createElement('span');
          var color = n.state === 'busy' ? '#22c55e' : (n.state === 'unreachable' ? '#ef4444' : '#6b7280');
          dot.style.cssText = 'width:7px;height:7px;border-radius:50%;background:' + color + ';';
          var label = String(n.name || '').replace(/^Starship - /, '').replace(/ - USS-\d+$/, '');
          var text = document.createElement('span');
          text.textContent = label + ' \u00b7 ' + (n.state === 'busy' ? (n.running + ' running, ' + n.pending + ' queued') : n.state);
          chip.appendChild(dot);
          chip.appendChild(text);
          if (n.lease_holder) {
            var tag = document.createElement('span');
            tag.textContent = 'IMAGE SESSION';
            tag.title = 'GPU leased to ' + n.lease_holder;
            tag.style.cssText = 'color:#ec4899;border:1px solid rgba(236,72,153,0.4);border-radius:3px;padding:0 4px;font-size:0.58rem;';
            chip.appendChild(tag);
          }
          el.appendChild(chip);
        });
      }).catch(function () {});
    },

    _renderShowDismissedToggle: function () {
      var link = _el('msDashShowDismissed');
      if (!link) return;
      if (msDashboard._showDismissed) {
        link.textContent = 'Hide dismissed';
        link.style.color = '#22c55e';
      } else {
        link.textContent = 'Show dismissed';
        link.style.color = '#555';
      }
      link.style.display = 'inline';
      var tests = _el('msDashShowTests');
      if (tests) {
        tests.textContent = msDashboard._showTests ? 'Hide tests' : 'Show tests';
        tests.style.color = msDashboard._showTests ? '#22c55e' : '#555';
      }
    },

    jumpTo: function (tab) {
      if (window.switchMsTab) {
        window.switchMsTab(tab);
        return;
      }
      var els = document.querySelectorAll('[data-ms-tab="' + tab + '"], .ms-tab-btn');
      if (els.length) {
        for (var i = 0; i < els.length; i++) {
          if (els[i].textContent.toLowerCase().indexOf(tab.replace('-', ' ')) !== -1) { els[i].click(); return; }
        }
      }
    },

    toggleDismissed: function () {
      msDashboard._showDismissed = !msDashboard._showDismissed;
      msDashboard.load();
    },

    start: function () {
      msDashboard.load();
      if (!_timer) _timer = setInterval(msDashboard.load, 10000);
    },

    stop: function () {
      if (_timer) { clearInterval(_timer); _timer = null; }
    },

    _renderGenerating: function (jobs) {
      var el = _el('msDashGeneratingList');
      if (!el) return;
      el.textContent = '';
      if (!jobs.length) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color:#555;font-size:0.7rem;padding:6px 0;';
        empty.textContent = 'No active jobs.';
        el.appendChild(empty);
        return;
      }
      jobs.forEach(function (job) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:5px;';
        var dot = document.createElement('div');
        dot.style.cssText = 'width:7px;height:7px;border-radius:50%;flex-shrink:0;background:' +
          (job.status === 'generating' ? '#22c55e' : '#f59e0b') + ';';
        var name = document.createElement('span');
        name.style.cssText = 'color:#ccc;font-size:0.68rem;flex:1;';
        name.textContent = (job.agent_name || 'User') + ' — ' + (job.media_type || 'image');
        var badge = document.createElement('span');
        badge.style.cssText = 'color:#555;font-size:0.62rem;';
        badge.textContent = job.status || 'pending';
        row.appendChild(dot); row.appendChild(name); row.appendChild(badge);
        el.appendChild(row);
      });
    },

    _renderApprovals: function (items) {
      var el = _el('msDashApprovalList');
      if (!el) return;
      el.textContent = '';
      if (!items.length) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color:#555;font-size:0.7rem;padding:6px 0;';
        empty.textContent = msDashboard._showDismissed ? 'No dismissed portraits to restore.' : 'Nothing pending.';
        el.appendChild(empty);
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:pointer;border-radius:4px;';
        row.onclick = function () { if (window.showMediaDetail && item.media_id) window.showMediaDetail(item.media_id); };
        row.title = 'Open media details';
        var thumb = document.createElement('div');
        thumb.style.cssText = 'width:36px;height:36px;border-radius:4px;background:#1a2a3a;flex-shrink:0;overflow:hidden;';
        if (item.thumbnail_url || item.file_path || item.thumbnail_path || item.canonical_image_path) {
          var img = document.createElement('img');
          img.src = _mediaSrc(item);
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;';
          thumb.appendChild(img);
        }
        var info = document.createElement('div');
        info.style.cssText = 'flex:1;min-width:0;';
        var n = document.createElement('div');
        n.style.cssText = 'color:#ccc;font-size:0.65rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        n.textContent = item.display_name || item.name || 'Agent';
        var t = document.createElement('div');
        t.style.cssText = 'color:#555;font-size:0.58rem;';
        t.textContent = _when(item.created_at);
        if (item.approval_dismissed) {
          t.textContent = (t.textContent ? t.textContent + ' · ' : '') + 'dismissed';
          t.style.color = '#ef4444';
        }
        info.appendChild(n); info.appendChild(t);
        var btns = document.createElement('div');
        btns.style.cssText = 'display:flex;gap:3px;flex-shrink:0;';
        btns.onclick = function (ev) { ev.stopPropagation(); };
        var approve = document.createElement('button');
        approve.style.cssText = 'background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.4);color:#22c55e;padding:3px 7px;border-radius:3px;font-size:0.6rem;cursor:pointer;';
        approve.textContent = '✓';
        approve.title = 'Approve as canonical portrait';
        approve.onclick = (function (agentId, mediaId) {
          return function () { msDashboard._approve(agentId, mediaId); };
        })(item.agent_id, item.media_id);
        btns.appendChild(approve);
        var dismiss = document.createElement('button');
        dismiss.style.cssText = 'background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.35);color:#ef4444;padding:3px 7px;border-radius:3px;font-size:0.6rem;cursor:pointer;';
        dismiss.textContent = item.approval_dismissed ? '↩' : '✗';
        dismiss.title = item.approval_dismissed ? 'Restore to the approvals list' : 'Soft-dismiss (keep image)';
        dismiss.onclick = (function (agentId, mediaId, cur) {
          return function () { msDashboard._dismiss(agentId, mediaId, !cur); };
        })(item.agent_id, item.media_id, item.approval_dismissed);
        btns.appendChild(dismiss);
        row.appendChild(thumb); row.appendChild(info); row.appendChild(btns);
        el.appendChild(row);
      });
    },

    _renderSocialQueue: function (items) {
      var el = _el('msDashSocialList');
      if (!el) return;
      el.textContent = '';
      if (!items.length) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color:#555;font-size:0.7rem;padding:6px 0;';
        empty.textContent = 'Queue empty.';
        el.appendChild(empty);
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement('div');
        row.style.cssText = 'margin-bottom:8px;';
        var title = document.createElement('div');
        title.style.cssText = 'color:#ccc;font-size:0.65rem;';
        title.textContent = item.title || 'Untitled';
        var sub = document.createElement('div');
        sub.style.cssText = 'color:#a78bfa;font-size:0.58rem;';
        sub.textContent = (item.platform || 'LinkedIn') + (item.scheduled_at ? ' · ' + new Date(item.scheduled_at).toLocaleString() : ' · draft');
        row.appendChild(title); row.appendChild(sub);
        el.appendChild(row);
      });
    },

    _renderRecent: function (items) {
      var el = _el('msDashRecentGrid');
      if (!el) return;
      el.textContent = '';
      if (!items.length) {
        var empty = document.createElement('div');
        empty.style.cssText = 'grid-column:1/-1;color:#555;font-size:0.7rem;padding:6px 0;';
        empty.textContent = 'No completed media yet.';
        el.appendChild(empty);
        return;
      }
      items.slice(0, 6).forEach(function (item) {
        var div = document.createElement('div');
        div.style.cssText = 'aspect-ratio:1;background:#1a2a3a;border-radius:4px;border:1px solid #222;overflow:hidden;cursor:pointer;';
        if (item.thumbnail_url || item.url || item.thumbnail_path || item.file_path) {
          var img = document.createElement('img');
          img.src = _mediaSrc(item);
          img.style.cssText = 'width:100%;height:100%;object-fit:cover;';
          img.loading = 'lazy';
          div.appendChild(img);
        }
        if (item.id && window.showMediaDetail) {
          div.onclick = (function (id) { return function () { showMediaDetail(id); }; })(item.id);
        }
        el.appendChild(div);
      });
    },

    _approve: function (agentId, mediaId) {
      if (!agentId || !mediaId) {
        console.warn('[msDashboard] approval item is missing agent_id or media_id');
        return;
      }
      fetch(_API + '/api/portraits/' + agentId + '/approve', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_id: mediaId })
      }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).then(function () { msDashboard.load(); }).catch(function (err) { console.warn('[msDashboard] approve failed:', err); });
    },

    _dismiss: function (agentId, mediaId, dismissed) {
      if (!agentId || !mediaId) return;
      fetch(_API + '/api/portraits/' + agentId + '/approval-dismiss', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_id: mediaId, dismissed: dismissed })
      }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).then(function () { msDashboard.load(); }).catch(function (err) { console.warn('[msDashboard] dismiss failed:', err); });
    }
  };
})();
