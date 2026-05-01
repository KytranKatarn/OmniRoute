(function () {
  'use strict';
  var _API = '/tools/media-studio';
  var _selectedImages = [];
  var _imageSource = 'gallery';
  var _selectedTheme = null;

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
      msSocialVideo.loadThemes();
      msSocialVideo.loadQueue();
      msSocialVideo.loadImageSource();
    },

    loadThemes: function () {
      _get('/api/themes').then(function (data) {
        var grid = _el('msSvThemeGrid');
        if (!grid) return;
        grid.textContent = '';
        (data.themes || []).forEach(function (theme) {
          var card = document.createElement('div');
          card.dataset.themeId = theme.id;
          card.style.cssText = 'background:#0d1117;border:1px solid ' +
            (theme.accent_color || '#333') + '44;border-radius:4px;padding:6px 5px;cursor:pointer;text-align:center;';
          var nameEl = document.createElement('div');
          nameEl.style.cssText = 'font-size:0.52rem;color:' + (theme.accent_color || '#888') +
            ';font-family:\'Orbitron\',sans-serif;letter-spacing:0.3px;line-height:1.3;';
          nameEl.textContent = theme.name;
          var curEl = document.createElement('div');
          curEl.style.cssText = 'font-size:0.48rem;color:#444;margin-top:2px;';
          curEl.textContent = theme.curator_name || '';
          card.appendChild(nameEl);
          card.appendChild(curEl);
          card.onclick = (function (t) { return function () { msSocialVideo.selectTheme(t); }; })(theme);
          grid.appendChild(card);
        });
      }).catch(function (err) { console.warn('[msSV] loadThemes failed:', err); });
    },

    selectTheme: function (theme) {
      _selectedTheme = theme;
      var grid = _el('msSvThemeGrid');
      if (grid) {
        grid.querySelectorAll('[data-theme-id]').forEach(function (c) {
          var active = String(c.dataset.themeId) === String(theme.id);
          c.style.borderColor = active ? (theme.accent_color || '#8b5cf6') : (theme.accent_color || '#333') + '44';
          c.style.background = active ? (theme.accent_color || '#8b5cf6') + '18' : '#0d1117';
        });
      }
      var sel = _el('msSvThemeSelected');
      var selName = _el('msSvThemeSelectedName');
      if (sel) sel.style.display = 'flex';
      if (selName) selName.textContent = theme.name;
    },

    selectThemeById: function (themeId) {
      _get('/api/themes/' + themeId + '/scenes').then(function (data) {
        if (data.theme) msSocialVideo.selectTheme(data.theme);
      }).catch(function (err) { console.warn('[msSV] selectThemeById failed:', err); });
    },

    clearTheme: function () {
      _selectedTheme = null;
      var grid = _el('msSvThemeGrid');
      if (grid) {
        grid.querySelectorAll('[data-theme-id]').forEach(function (c) {
          c.style.borderColor = '#33333344';
          c.style.background = '#0d1117';
        });
      }
      var sel = _el('msSvThemeSelected');
      if (sel) sel.style.display = 'none';
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
      var statusColor = { draft: '#f59e0b', rendering: '#60a5fa', pending_approval: '#a78bfa', scheduled: '#22c55e', posted: '#555', failed: '#ef4444' };
      var statusLabel = { draft: 'DRAFT', rendering: '⟳ RENDERING', pending_approval: 'READY', scheduled: 'SCHEDULED', posted: 'POSTED', failed: 'FAILED' };
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
        badge.textContent = statusLabel[item.status] || item.status;
        header.appendChild(title);
        header.appendChild(badge);

        var sub = document.createElement('div');
        sub.style.cssText = 'color:#555;font-size:.6rem;';
        sub.textContent = (item.platform || 'LinkedIn') + (item.scheduled_at ? ' · ' + new Date(item.scheduled_at).toLocaleString() : '');

        card.appendChild(header);
        card.appendChild(sub);

        // Video preview for ready items
        if (item.video_path && item.status === 'pending_approval') {
          var videoWrap = document.createElement('div');
          videoWrap.style.cssText = 'margin-top:8px;';
          var video = document.createElement('video');
          video.src = item.video_path;
          video.controls = true;
          video.style.cssText = 'width:100%;border-radius:4px;max-height:160px;';
          videoWrap.appendChild(video);
          card.appendChild(videoWrap);
        }

        // Error message for failed
        if (item.status === 'failed' && item.error_message) {
          var err = document.createElement('div');
          err.style.cssText = 'color:#ef4444;font-size:.58rem;margin-top:4px;';
          err.textContent = item.error_message.substring(0, 100);
          card.appendChild(err);
        }

        el.appendChild(card);
      });
    },

    queueAndRender: function () {
      var title = (_el('msSvTitle') || {}).value || '';
      var quote = (_el('msSvQuote') || {}).value || '';
      var statusEl = _el('msSvStatus');

      if (!_selectedImages.length) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Select at least 1 image first.'; }
        return;
      }
      if (!quote && !title) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Add a quote or title first.'; }
        return;
      }

      var audio = (document.querySelector('.ms-sv-audio-btn.active') || {}).dataset;
      var audioMode = audio ? audio.mode : 'music';
      var platform = (_el('msSvPlatform') || {}).value || 'linkedin';
      var scheduled = (_el('msSvScheduled') || {}).value || null;

      if (statusEl) { statusEl.style.color = '#a78bfa'; statusEl.textContent = '⏳ Queuing for render…'; }

      _post('/api/social-video/queue', {
        title: title || 'Untitled',
        quote_text: quote,
        media_ids: _selectedImages.slice(),
        audio_mode: audioMode,
        platform: platform,
        scheduled_at: scheduled || null,
        theme_id: _selectedTheme ? _selectedTheme.id : null,
      }).then(function (data) {
        if (statusEl) { statusEl.style.color = 'rgba(139,92,246,.9)'; statusEl.textContent = '🎬 Queued #' + data.id + ' — P.I.X.E.L. rendering in ~2 min…'; }
        msSocialVideo.loadQueue();
        msSocialVideo._resetForm();
        // Poll queue for status updates
        var poll = setInterval(function () { msSocialVideo.loadQueue(); }, 10000);
        setTimeout(function () { clearInterval(poll); }, 300000);
      }).catch(function (err) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Failed: ' + err.message; }
      });
    },

    _resetForm: function () {
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
        theme_id: _selectedTheme ? _selectedTheme.id : null,
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
