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

  window.msDashboard = {
    load: function () {
      _get('/api/dashboard').then(function (d) {
        _setText('msDashStatGenerating', d.queue_active != null ? d.queue_active : (d.active_jobs || []).length);
        _setText('msDashStatApprovals', d.pending_approval_count != null ? d.pending_approval_count : (d.pending_approvals || []).length);
        _setText('msDashStatSocial', d.social_queue_count != null ? d.social_queue_count : (d.social_queue || []).length);
        _setText('msDashStatTotal', d.total_generated != null ? d.total_generated : 0);
        _setText('msDashStatFailed', d.queue_failed != null ? d.queue_failed : 0);
        _setText('msDashUpdated', 'Updated ' + new Date().toLocaleTimeString());
        msDashboard._renderGenerating(d.active_jobs || []);
        msDashboard._renderApprovals(d.pending_approvals || []);
        msDashboard._renderSocialQueue(d.social_queue || []);
        msDashboard._renderRecent(d.recent || []);
      }).catch(function (err) { console.warn('[msDashboard] load failed:', err); });
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
        empty.textContent = 'Nothing pending.';
        el.appendChild(empty);
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
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
        t.textContent = item.created_at ? new Date(item.created_at).toLocaleTimeString() : '';
        info.appendChild(n); info.appendChild(t);
        var btns = document.createElement('div');
        btns.style.cssText = 'display:flex;gap:3px;flex-shrink:0;';
        var approve = document.createElement('button');
        approve.style.cssText = 'background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.4);color:#22c55e;padding:3px 7px;border-radius:3px;font-size:0.6rem;cursor:pointer;';
        approve.textContent = '✓';
        approve.onclick = (function (agentId, mediaId) {
          return function () { msDashboard._approve(agentId, mediaId); };
        })(item.agent_id, item.media_id);
        btns.appendChild(approve);
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
    }
  };
})();
