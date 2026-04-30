(function () {
  'use strict';
  var _API = '/tools/media-studio';
  var _selectedImages = [];
  var _imageSource = 'gallery';

  function _get(path) {
    return fetch(_API + path, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function _post(path, body) {
    return fetch(_API + path, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function _el(id) { return document.getElementById(id); }

  window.msSocialVideo = {
    init: function () {
      msSocialVideo.loadQueue();
      msSocialVideo.loadImageSource();
    },

    switchImageSource: function (source) {
      _imageSource = source;
      document.querySelectorAll('.ms-sv-source-tab').forEach(function (el) {
        el.classList.toggle('active', el.dataset.source === source);
      });
      msSocialVideo.loadImageSource();
    },

    loadImageSource: function () {
      var params = _imageSource === 'gallery'
        ? '/api/gallery?owner_type=agent&per_page=30'
        : '/api/gallery?owner_type=agent&asset_type=portrait&per_page=30';
      _get(params).then(function (data) {
        msSocialVideo._renderImagePicker(data.items || []);
      }).catch(function (err) { console.warn('[msSV] loadImageSource failed:', err); });
    },

    _renderImagePicker: function (items) {
      var el = _el('msSvImagePickerGrid');
      if (!el) return;
      el.textContent = '';
      items.forEach(function (item) {
        var div = document.createElement('div');
        div.className = 'ms-sv-pick-thumb';
        div.dataset.mediaId = item.id;
        var sel = _selectedImages.indexOf(item.id) !== -1;
        if (sel) div.classList.add('selected');

        if (item.thumbnail_path || item.url) {
          var img = document.createElement('img');
          img.src = item.thumbnail_path || item.url;
          img.loading = 'lazy';
          div.appendChild(img);
        }

        var order = document.createElement('div');
        order.className = 'ms-sv-pick-order';
        var idx = _selectedImages.indexOf(item.id);
        order.textContent = idx !== -1 ? idx + 1 : '';
        div.appendChild(order);

        div.onclick = (function (id, el) {
          return function () { msSocialVideo.toggleImage(id, el); };
        })(item.id, div);
        el.appendChild(div);
      });
    },

    toggleImage: function (id, el) {
      var idx = _selectedImages.indexOf(id);
      if (idx === -1) {
        _selectedImages.push(id);
      } else {
        _selectedImages.splice(idx, 1);
      }
      // Refresh order badges on all thumbs
      var grid = _el('msSvImagePickerGrid');
      if (grid) {
        grid.querySelectorAll('.ms-sv-pick-thumb').forEach(function (thumb) {
          var mid = parseInt(thumb.dataset.mediaId, 10);
          var i = _selectedImages.indexOf(mid);
          var badge = thumb.querySelector('.ms-sv-pick-order');
          if (badge) badge.textContent = i !== -1 ? i + 1 : '';
          thumb.classList.toggle('selected', i !== -1);
        });
      }
      msSocialVideo._renderSelectedStrip();
    },

    _renderSelectedStrip: function () {
      var el = _el('msSvSelectedStrip');
      if (!el) return;
      el.textContent = '';
      _selectedImages.forEach(function (id, idx) {
        var div = document.createElement('div');
        div.style.cssText = 'width:48px;height:48px;background:#1a2a3a;border-radius:4px;border:1px solid rgba(139,92,246,.4);position:relative;flex-shrink:0;';
        var n = document.createElement('div');
        n.style.cssText = 'position:absolute;bottom:1px;right:1px;background:#8b5cf6;color:#fff;font-size:.5rem;padding:1px 3px;border-radius:2px;';
        n.textContent = idx + 1;
        div.appendChild(n);
        el.appendChild(div);
      });
    },

    selectAudio: function (mode, el) {
      document.querySelectorAll('.ms-sv-audio-btn').forEach(function (b) {
        b.classList.toggle('active', b === el);
      });
    },

    filterQueue: function (status, el) {
      document.querySelectorAll('.ms-sv-queue-filter').forEach(function (b) {
        b.classList.toggle('active', b === el);
      });
      msSocialVideo.loadQueue();
    },

    loadQueue: function () {
      var activeFilter = document.querySelector('.ms-sv-queue-filter.active');
      var status = activeFilter ? activeFilter.dataset.status : '';
      var path = '/api/social-video/queue' + (status ? '?status=' + status : '');
      _get(path).then(function (data) {
        msSocialVideo._renderQueue(data.items || []);
      }).catch(function (err) { console.warn('[msSV] loadQueue failed:', err); });
    },

    _renderQueue: function (items) {
      var el = _el('msSvQueueList');
      if (!el) return;
      el.textContent = '';
      if (!items.length) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color:#555;font-size:.7rem;padding:12px 0;';
        empty.textContent = 'No content yet.';
        el.appendChild(empty);
        return;
      }
      var statusColor = { draft: '#f59e0b', scheduled: '#22c55e', posted: '#555', pending_approval: '#a78bfa' };
      items.forEach(function (item) {
        var card = document.createElement('div');
        card.style.cssText = 'background:#0d1117;border:1px solid #1a1a3a;border-radius:5px;padding:10px;margin-bottom:7px;';

        var header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:5px;';
        var title = document.createElement('span');
        title.style.cssText = 'color:#ccc;font-size:.68rem;flex:1;';
        title.textContent = item.title || 'Untitled';
        var col = statusColor[item.status] || '#888';
        var badge = document.createElement('span');
        badge.style.cssText = 'font-size:.55rem;padding:2px 6px;border-radius:3px;background:' + col + '22;border:1px solid ' + col + '44;color:' + col + ';text-transform:uppercase;letter-spacing:1px;flex-shrink:0;';
        badge.textContent = item.status;
        header.appendChild(title);
        header.appendChild(badge);

        var sub = document.createElement('div');
        sub.style.cssText = 'color:#555;font-size:.6rem;';
        sub.textContent = (item.platform || 'LinkedIn') + (item.scheduled_at ? ' · ' + new Date(item.scheduled_at).toLocaleString() : '');

        card.appendChild(header);
        card.appendChild(sub);
        el.appendChild(card);
      });
    },

    queueForPosting: function () {
      var title = (_el('msSvTitle') || {}).value || '';
      var quote = (_el('msSvQuote') || {}).value || '';
      var audio = (document.querySelector('.ms-sv-audio-btn.active') || {}).dataset;
      var audioMode = audio ? audio.mode : 'music';
      var platform = (_el('msSvPlatform') || {}).value || 'linkedin';
      var scheduled = (_el('msSvScheduled') || {}).value || null;
      var statusEl = _el('msSvStatus');

      if (!quote && !title) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Add a quote or title first.'; }
        return;
      }

      _post('/api/social-video/queue', {
        title: title || 'Untitled',
        quote_text: quote,
        media_ids: _selectedImages.slice(),
        audio_mode: audioMode,
        platform: platform,
        scheduled_at: scheduled || null,
      }).then(function () {
        if (statusEl) { statusEl.style.color = 'rgba(34,197,94,.9)'; statusEl.textContent = '✓ Added to queue'; }
        msSocialVideo.loadQueue();
        // Reset form
        _selectedImages = [];
        msSocialVideo._renderSelectedStrip();
        var grid = _el('msSvImagePickerGrid');
        if (grid) grid.querySelectorAll('.ms-sv-pick-thumb').forEach(function (t) {
          t.classList.remove('selected');
          var b = t.querySelector('.ms-sv-pick-order');
          if (b) b.textContent = '';
        });
        if (_el('msSvTitle')) _el('msSvTitle').value = '';
        if (_el('msSvQuote')) _el('msSvQuote').value = '';
        setTimeout(function () { if (statusEl) statusEl.textContent = ''; }, 3000);
      }).catch(function (err) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Failed: ' + err.message; }
      });
    }
  };
})();
