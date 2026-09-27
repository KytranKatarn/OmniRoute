(function () {
  'use strict';
  var _API = '/tools/media-studio';
  var _subject = null;
  var _assetFilter = 'all';
  var _sort = 'newest';
  var _subjectName = '';

  function _get(path) {
    return fetch(_API + path, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function _el(id) { return document.getElementById(id); }

  // last_run is an ISO string that already carries its UTC offset, so blindly
  // appending 'Z' yields "…+00:00Z" — not a valid date. Only assume UTC when the
  // string has no offset at all.
  function _parseUtc(s) {
    if (!s) return null;
    var d = new Date(s);
    if (isNaN(d.getTime()) && !/[Zz]|[+-]\d\d:?\d\d$/.test(s)) { d = new Date(s + 'Z'); }
    return isNaN(d.getTime()) ? null : d;
  }

  function _ago(d) {
    var mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
    if (mins < 60) return mins + 'm ago';
    var hrs = Math.round(mins / 60);
    if (hrs < 48) return hrs + 'h ago';
    return Math.round(hrs / 24) + 'd ago';
  }

  window.msGallery = {
    init: function () {
      try {
        var saved = sessionStorage.getItem('ms_gallery_subject');
        if (saved) _subject = JSON.parse(saved);
      } catch (e) {}
        msGallery.loadSubjects();
        // Surface where the last publish landed, so an approved portrait's
        // journey to the public site is visible from where it was approved.
        msGallery.loadPublishStatus();
    },

    loadSubjects: function () {
      _get('/api/agents/gallery-subjects').then(function (data) {
        msGallery._renderSidebar(data);
        if (!_subject && data.humans && data.humans.length) {
          msGallery.selectSubject('agent', data.humans[0].id);
        } else if (_subject) {
          msGallery._highlightSidebar();
          msGallery.loadAssets();
        }
      }).catch(function (err) { console.warn('[msGallery] loadSubjects failed:', err); });
    },

    selectSubject: function (type, id) {
      _subject = { type: type, id: id };
      try { sessionStorage.setItem('ms_gallery_subject', JSON.stringify(_subject)); } catch (e) {}
      msGallery._highlightSidebar();
      msGallery.loadAssets();
      history.replaceState(null, '', '#gallery/' + type + '/' + (id || 'brand'));
    },

    _highlightSidebar: function () {
      document.querySelectorAll('.ms-gallery-subject-item').forEach(function (el) {
        var match = _subject &&
          el.dataset.subjectType === _subject.type &&
          String(el.dataset.subjectId) === String(_subject.id || '');
        el.classList.toggle('ms-gallery-subject-active', !!match);
      });
    },

    _renderSidebar: function (data) {
      var sidebar = _el('msGallerySidebarSubjects');
      if (!sidebar) return;
      sidebar.textContent = '';

      function _section(label, items, type) {
        var hdr = document.createElement('div');
        hdr.className = 'ms-gallery-sidebar-section-label';
        hdr.textContent = label;
        sidebar.appendChild(hdr);
        items.forEach(function (agent) {
          var item = document.createElement('div');
          item.className = 'ms-gallery-subject-item';
          item.dataset.subjectType = type;
          item.dataset.subjectId = agent.id || '';
          item.onclick = function () { msGallery.selectSubject(type, agent.id); };

          var avatar = document.createElement('div');
          avatar.className = 'ms-gallery-subject-avatar';
          if (agent.avatar_thumb_url) {
            var img = document.createElement('img');
            img.src = agent.avatar_thumb_url;
            img.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:50%;';
            img.loading = 'lazy';
            avatar.appendChild(img);
          }
          var name = document.createElement('span');
          name.className = 'ms-gallery-subject-name';
          name.textContent = agent.display_name || agent.name;
          var count = document.createElement('span');
          count.className = 'ms-gallery-subject-count';
          count.textContent = agent.asset_count || 0;

          item.appendChild(avatar);
          item.appendChild(name);
          item.appendChild(count);
          sidebar.appendChild(item);
        });
      }

      _section('HUMAN AGENTS', data.humans || [], 'agent');
      _section('AI AGENTS', data.ai_agents || [], 'agent');

      var brandHdr = document.createElement('div');
      brandHdr.className = 'ms-gallery-sidebar-section-label';
      brandHdr.textContent = 'BRANDS';
      sidebar.appendChild(brandHdr);

      var brands = data.brands || (data.brand ? [data.brand] : []);
      brands.forEach(function (b) {
        var brandItem = document.createElement('div');
        brandItem.className = 'ms-gallery-subject-item';
        brandItem.dataset.subjectType = 'brand';
        brandItem.dataset.subjectId = b.id || '';
        brandItem.onclick = (function (bid) {
          return function () { msGallery.selectSubject('brand', bid); };
        })(b.id || null);
        if (b.accent_color) brandItem.style.borderLeft = '3px solid ' + b.accent_color;
        var brandName = document.createElement('span');
        brandName.className = 'ms-gallery-subject-name';
        brandName.textContent = b.name || 'Brand';
        var brandCount = document.createElement('span');
        brandCount.className = 'ms-gallery-subject-count';
        brandCount.textContent = b.asset_count || 0;
        brandItem.appendChild(brandName);
        brandItem.appendChild(brandCount);
        sidebar.appendChild(brandItem);
      });

      msGallery._highlightSidebar();
    },

    loadAssets: function () {
      if (!_subject) return;
      // Brand subject: no id → legacy themes view; with an id → its asset grid
      if (_subject.type === 'brand' && !_subject.id) {
        msGallery.loadBrandThemes();
        return;
      }
      // Restore grid, hide brand panel when switching to agent
      var gridEl = _el('msGallerySubjectGrid');
      var themeEl = _el('msGalleryBrandThemes');
      var filterEl = document.querySelector('.ms-gallery-type-tab');
      if (gridEl) gridEl.style.display = '';
      if (themeEl) themeEl.style.display = 'none';
      if (filterEl) {
        var filterRow = filterEl.closest('[style*="border-bottom"]');
        if (filterRow) filterRow.style.display = '';
      }
      var el = _el('msGallerySubjectGrid');
      var headerEl = _el('msGallerySubjectHeader');
      if (el) {
        el.textContent = '';
        var loading = document.createElement('div');
        loading.style.cssText = 'color:#555;font-size:0.7rem;padding:12px;';
        loading.textContent = 'Loading…';
        el.appendChild(loading);
      }

      var params = '?per_page=50';
      if (_subject.type === 'agent' && _subject.id) {
        params += '&owner_type=agent&owner_id=' + _subject.id;
        _get('/api/agents/gallery-subjects').then(function (d) {
          var all = (d.humans || []).concat(d.ai_agents || []);
          var agent = all.filter(function (a) { return String(a.id) === String(_subject.id); })[0];
          if (agent && headerEl) msGallery._renderSubjectHeader(agent);
        }).catch(function () {});
      } else {
        params += '&owner_type=brand';
        if (_subject.id) params += '&owner_id=' + _subject.id;
        if (headerEl) headerEl.textContent = '';
      }

      if (_assetFilter !== 'all') params += '&asset_type=' + _assetFilter;
      if (_sort && _sort !== 'newest') params += '&sort=' + _sort;

      _get('/api/gallery' + params).then(function (data) {
        msGallery._renderGrid(data.items || []);
      }).catch(function (err) { console.warn('[msGallery] loadAssets failed:', err); });
    },

    _renderSubjectHeader: function (agent) {
      var el = _el('msGallerySubjectHeader');
      if (!el) return;
      el.textContent = '';
      el.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:14px;';

      var avatar = document.createElement('div');
      avatar.style.cssText = 'width:40px;height:40px;border-radius:50%;background:#1a2a3a;overflow:hidden;flex-shrink:0;border:1px solid rgba(34,197,94,0.3);';
      if (agent.avatar_thumb_url) {
        var img = document.createElement('img');
        img.src = agent.avatar_thumb_url;
        img.style.cssText = 'width:100%;height:100%;object-fit:cover;';
        avatar.appendChild(img);
      }

      var info = document.createElement('div');
      info.style.cssText = 'flex:1;';
      _subjectName = agent.display_name || agent.name;
      var nameEl = document.createElement('div');
      nameEl.style.cssText = 'color:#fff;font-size:0.85rem;font-family:"Orbitron",sans-serif;';
      nameEl.textContent = _subjectName;
      var deptEl = document.createElement('div');
      deptEl.style.cssText = 'color:#555;font-size:0.65rem;margin-top:2px;';
      deptEl.textContent = (agent.worker_type === 'internal' ? 'Human Agent' : 'AI Agent') +
        (agent.department ? ' · ' + agent.department : '') +
        ' · ' + (agent.asset_count || 0) + ' assets';
      info.appendChild(nameEl);
      info.appendChild(deptEl);

      var genBtn = document.createElement('button');
      genBtn.style.cssText = 'background:rgba(34,197,94,0.1);border:1px solid rgba(34,197,94,0.3);color:#22c55e;padding:5px 12px;border-radius:4px;font-size:0.65rem;font-family:"Orbitron",sans-serif;letter-spacing:1px;cursor:pointer;flex-shrink:0;';
      genBtn.textContent = '+ Generate';
      genBtn.onclick = function () {
        if (window.msGenerate) msGenerate.preselectAgent(_subject.id);
        switchMsTab('generate');
      };

      el.appendChild(avatar);
      el.appendChild(info);
      el.appendChild(genBtn);
    },

    _renderGrid: function (items) {
      var el = _el('msGallerySubjectGrid');
      if (!el) return;
      el.textContent = '';

      if (!items.length) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color:#555;font-size:0.75rem;padding:16px 0;';
        empty.textContent = 'No assets yet. Click + Generate to create some.';
        el.appendChild(empty);
        return;
      }

      items.forEach(function (item) {
        var card = document.createElement('div');
        card.className = 'ms-gallery-subject-card';
        card.dataset.mediaId = item.id;

        var thumb = document.createElement('div');
        thumb.className = 'ms-gallery-subject-thumb';
        if (item.thumbnail_path || item.url) {
          var img = document.createElement('img');
          img.src = item.thumbnail_path || item.url;
          img.loading = 'lazy';
          thumb.appendChild(img);
        }
        if (item.metadata && item.metadata.featured) {
          var star = document.createElement('div');
          star.className = 'ms-gallery-subject-star';
          star.textContent = '★';
          thumb.appendChild(star);
        }
        card.appendChild(thumb);

        var prompt = document.createElement('div');
        prompt.className = 'ms-gallery-subject-prompt';
        var isCanonical = item.metadata && item.metadata.featured && String(item.id).indexOf('portrait_') === 0;
        var agentLabel = item.metadata && item.metadata.agent_name ? item.metadata.agent_name : _subjectName;
        prompt.textContent = isCanonical
          ? '★ ' + agentLabel
          : (agentLabel || (item.prompt || '').substring(0, 50));
        card.appendChild(prompt);

        card.onclick = (function (id) {
          return function () { if (window.showMediaDetail) showMediaDetail(id); };
        })(item.id);

        el.appendChild(card);
      });
    },

    loadBrandThemes: function () {
      var themeEl = _el('msGalleryBrandThemes');
      var gridEl = _el('msGallerySubjectGrid');
      var headerEl = _el('msGallerySubjectHeader');
      if (!themeEl) return;
      themeEl.style.display = 'block';
      if (gridEl) gridEl.style.display = 'none';
      if (headerEl) {
        headerEl.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:14px;';
        while (headerEl.firstChild) headerEl.removeChild(headerEl.firstChild);
        var nameEl = document.createElement('div');
        nameEl.style.cssText = 'font-size:0.85rem;font-family:\'Orbitron\',sans-serif;color:#22c55e;';
        nameEl.textContent = 'Kytran Empowerment';
        var deptEl = document.createElement('div');
        deptEl.style.cssText = 'color:#555;font-size:0.65rem;';
        deptEl.textContent = 'Brand \xb7 Content Themes';
        headerEl.appendChild(nameEl);
        headerEl.appendChild(deptEl);
      }
      fetch('/tools/media-studio/api/themes', {credentials: 'same-origin'})
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var cards = _el('msGalleryThemeCards');
          if (!cards) return;
          cards.textContent = '';
          (data.themes || []).forEach(function (theme) {
            var card = document.createElement('div');
            card.style.cssText = 'background:#0d1117;border:1px solid ' +
              (theme.accent_color || '#333') + '44;border-radius:6px;padding:12px;cursor:pointer;';
            var dot = document.createElement('div');
            dot.style.cssText = 'width:28px;height:4px;background:' +
              (theme.accent_color || '#8b5cf6') + ';border-radius:2px;margin-bottom:8px;';
            var nameEl = document.createElement('div');
            nameEl.style.cssText = 'font-family:\'Orbitron\',sans-serif;font-size:0.6rem;color:#ccc;margin-bottom:3px;';
            nameEl.textContent = theme.name;
            var curEl = document.createElement('div');
            curEl.style.cssText = 'font-size:0.55rem;color:#555;margin-bottom:3px;';
            curEl.textContent = theme.curator_name || '';
            var cntEl = document.createElement('div');
            cntEl.style.cssText = 'font-size:0.52rem;color:#444;';
            cntEl.textContent = (theme.scene_count || 0) + ' scenes';
            card.appendChild(dot);
            card.appendChild(nameEl);
            card.appendChild(curEl);
            card.appendChild(cntEl);
            card.onclick = (function (t) {
              return function () {
                if (window.switchMsTab) switchMsTab('social-video');
                setTimeout(function () {
                  if (window.msSocialVideo) msSocialVideo.selectThemeById(t.id);
                }, 350);
              };
            })(theme);
            cards.appendChild(card);
          });
        })
        .catch(function (err) { console.warn('[msGallery] loadBrandThemes failed:', err); });
    },

    setFilter: function (filter) {
      _assetFilter = filter;
      document.querySelectorAll('.ms-gallery-type-tab').forEach(function (el) {
        el.classList.toggle('active', el.dataset.filter === filter);
      });
      msGallery.loadAssets();
    },

    setSort: function (sort) {
      _sort = sort || 'newest';
      msGallery.loadAssets();
    },

    // ── Publish portraits to the public sites ──────────────────────────────
    //
    // The endpoint lives in Repair Bay, NOT under /tools/media-studio, so it
    // needs its own base. Both routes are @login_required @admin_required; a
    // non-admin gets 403 and is told so rather than shown a silent failure.
    //
    // An empty body means "all sites" — the trigger queues one deploy per
    // configured domain. It runs in a background thread server-side, so this
    // returns as soon as the queue is accepted; the status poll below is how
    // you find out it landed.
    publishPortraits: function () {
      var btn = _el('msPublishSitesBtn');
      var out = _el('msPublishSitesStatus');
      if (btn) { btn.disabled = true; btn.textContent = 'QUEUEING…'; }
      if (out) { out.textContent = 'Queueing deploy…'; out.style.color = '#9ca3af'; }

      fetch('/tools/repair-bay/api/deploy/website-trigger', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
        .then(function (r) {
          if (r.status === 403) { var e = new Error('forbidden'); e.forbidden = true; throw e; }
          if (!r.ok) throw new Error(r.status);
          return r.json();
        })
        .then(function (data) {
          if (btn) { btn.disabled = false; btn.textContent = 'PUBLISH PORTRAITS'; }
          if (out) {
            out.textContent = data.success
              ? 'Queued: ' + (data.queued || []).join(', ')
              : 'Queue failed: ' + (data.error || 'unknown');
            out.style.color = data.success ? '#22c55e' : '#ef4444';
          }
          // The queue is async and the status watermark only moves when bytes
          // actually land, so poll rather than claiming success.
          setTimeout(msGallery.loadPublishStatus, 3000);
        })
        .catch(function (err) {
          if (btn) { btn.disabled = false; btn.textContent = 'PUBLISH PORTRAITS'; }
          if (out) {
            out.textContent = err.forbidden
              ? 'Admin only — ask the owner to queue the deploy'
              : 'Queue failed (' + err.message + ')';
            out.style.color = '#ef4444';
          }
        });
    },

    // Status labels mirror what deploy_service actually WRITES. Deliberately not
    // keyed on 'success': the daily worker is forbidden from writing that (it
    // used to, which read as a completed deploy for a push that never happened —
    // #2533). Real values are 'deployed' (bytes landed, written only by
    // mark_deploy_pushed), 'deploy_pending'/'dispatched' (queued, not pushed),
    // and 'failed'.
    loadPublishStatus: function () {
      var out = _el('msPublishSitesStatus');
      if (!out) return;
      fetch('/tools/repair-bay/api/deploy/website-status', { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) {
          var sites = data.sites || [];
          if (!sites.length) { out.textContent = 'No sites configured.'; return; }
          out.textContent = sites.map(function (s) {
            var label = s.last_status === 'deployed' ? 'deployed'
              : s.last_status === 'failed' ? 'FAILED'
              : (s.last_status === 'dispatched' || s.last_status === 'deploy_pending') ? 'queued (not pushed)'
              : (s.last_status || 'never');
            var bits = [s.domain + ': ' + label];
            var run = _parseUtc(s.last_run);
            if (run) { bits.push('last run ' + _ago(run)); }
            if (s.pending_portraits) { bits.push(s.pending_portraits + ' portrait(s) since last run'); }
            return bits.join(' · ');
          }).join('   |   ');
          out.style.color = sites.some(function (s) { return s.last_status === 'failed'; }) ? '#ef4444' : '#9ca3af';
        })
        .catch(function (err) {
          out.textContent = 'status unavailable (' + err.message + ')';
          out.style.color = '#6b7280';
        });
    }
  };
})();
