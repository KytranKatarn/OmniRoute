/* AI Directors — live data from A.R.C.H.I.E. public roster API */
(function () {
  'use strict';

  var FLOOR_ORDER = ['BRIDGE', 'OPERATIONS', 'ENGINEERING', 'CREATIVE', 'SERVICES'];
  var FLOOR_CONFIG = {
    BRIDGE:      { name: 'Bridge',      color: '#00e5ff' },
    OPERATIONS:  { name: 'Operations',  color: '#fbbf24' },
    ENGINEERING: { name: 'Engineering', color: '#8b5cf6' },
    CREATIVE:    { name: 'Creative',    color: '#f472b6' },
    SERVICES:    { name: 'Services',    color: '#10b981' }
  };

  var FLOOR_CSS_CLASS = {
    BRIDGE:      'dir-floor--bridge',
    OPERATIONS:  'dir-floor--ops',
    ENGINEERING: 'dir-floor--eng',
    CREATIVE:    'dir-floor--creative',
    SERVICES:    'dir-floor--services'
  };

  var STATE_LABELS = {
    active:      'On Duty',
    barracked:   'Reserve',
    deployed:    'Deployed',
    winding_down:'Winding Down',
    off_duty:    'Off Duty',
    cooldown:    'Cooldown'
  };

  /** Remove all child nodes from an element safely */
  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function buildAvatar(director, floorColor) {
    var wrap = document.createElement('div');
    wrap.className = 'dir-card__avatar';

    var img = document.createElement('img');
    // Prefer the same-origin thumb (~20KB JPEG) over cross-origin full-res PNG.
    // Falls back to full if thumb not yet generated for this agent.
    img.src = director.avatar_thumb_url || director.avatar_url || '';
    img.alt = (director.display_name || director.name) + ' portrait';
    img.loading = 'lazy';
    img.decoding = 'async';

    img.onerror = function () {
      wrap.removeChild(img);
      var fb = document.createElement('div');
      fb.className = 'dir-card__avatar-fallback';
      fb.style.backgroundColor = floorColor;
      fb.style.color = '#0a0a1a';
      fb.textContent = (director.name || '?').charAt(0);
      wrap.appendChild(fb);
    };

    wrap.appendChild(img);
    return wrap;
  }

  function buildCard(director, floorColor) {
    var card = document.createElement('div');
    card.className = 'glass-panel dir-card';

    // Avatar
    card.appendChild(buildAvatar(director, floorColor));

    // Acronym
    var acronym = document.createElement('span');
    acronym.className = 'dir-card__acronym';
    acronym.style.color = floorColor;
    acronym.textContent = director.acronym || director.display_name || director.name;
    card.appendChild(acronym);

    // Acronym expansion
    var expansion = document.createElement('span');
    expansion.className = 'dir-card__name';
    expansion.style.color = '#fff';
    expansion.textContent = director.acronym_expansion || '';
    card.appendChild(expansion);

    // Department
    var dept = document.createElement('span');
    dept.className = 'dir-card__dept';
    dept.textContent = director.department || '';
    card.appendChild(dept);

    // Bio / description
    var desc = document.createElement('p');
    desc.className = 'dir-card__desc';
    desc.textContent = director.description || director.bio || '';
    card.appendChild(desc);

    // Shift state badge
    var state = director.shift_state || 'active';
    var badge = document.createElement('span');
    badge.className = 'dir-card__status';
    badge.setAttribute('data-state', state);
    badge.textContent = STATE_LABELS[state] || state;
    card.appendChild(badge);

    // Click-to-showcase — open a full detail modal for the director
    card.style.cursor = 'pointer';
    card.setAttribute('tabindex', '0');
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', 'Open showcase for ' + (director.acronym || director.display_name || director.name));
    card.addEventListener('click', function () { openShowcase(director, floorColor); });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openShowcase(director, floorColor); }
    });

    return card;
  }

  function openShowcase(director, floorColor) {
    var existing = document.getElementById('directorShowcaseModal');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'directorShowcaseModal';
    overlay.className = 'dir-modal';
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) overlay.remove();
    });

    var panel = document.createElement('div');
    panel.className = 'dir-modal__panel';
    if (floorColor) panel.style.borderColor = floorColor;

    var closeBtn = document.createElement('button');
    closeBtn.className = 'dir-modal__close';
    closeBtn.setAttribute('aria-label', 'Close');
    closeBtn.textContent = '\u00D7';
    closeBtn.addEventListener('click', function () { overlay.remove(); });
    panel.appendChild(closeBtn);

    // Avatar
    var avatarWrap = document.createElement('div');
    avatarWrap.className = 'dir-modal__avatar';
    if (director.avatar_thumb_url || director.avatar_url) {
      var img = document.createElement('img');
      img.src = director.avatar_thumb_url || director.avatar_url;
      img.alt = (director.acronym || director.display_name || 'Director') + ' portrait';
      img.onerror = function () {
        var ph = document.createElement('div');
        ph.className = 'dir-modal__avatar-fallback';
        if (floorColor) ph.style.background = floorColor;
        ph.textContent = (director.acronym || director.display_name || '?').charAt(0);
        this.replaceWith(ph);
      };
      avatarWrap.appendChild(img);
    } else {
      var ph = document.createElement('div');
      ph.className = 'dir-modal__avatar-fallback';
      if (floorColor) ph.style.background = floorColor;
      ph.textContent = (director.acronym || director.display_name || '?').charAt(0);
      avatarWrap.appendChild(ph);
    }
    panel.appendChild(avatarWrap);

    // Acronym + expansion
    var acrH = document.createElement('h2');
    acrH.className = 'dir-modal__acronym';
    if (floorColor) acrH.style.color = floorColor;
    acrH.textContent = director.acronym || director.display_name || director.name || '';
    panel.appendChild(acrH);

    if (director.acronym_expansion) {
      var exp = document.createElement('p');
      exp.className = 'dir-modal__expansion';
      exp.textContent = director.acronym_expansion;
      panel.appendChild(exp);
    }

    // Bio
    if (director.bio) {
      var bioH = document.createElement('h3');
      bioH.className = 'dir-modal__bio-heading';
      bioH.textContent = 'About';
      panel.appendChild(bioH);

      var bioP = document.createElement('p');
      bioP.className = 'dir-modal__bio';
      bioP.textContent = director.bio;
      panel.appendChild(bioP);
    }

    // Info rows
    var fields = [
      { label: 'Role',       value: director.title },
      { label: 'Department', value: director.department },
      { label: 'Floor',      value: director.floor },
      { label: 'Status',     value: director.shift_state }
    ];

    var infoGrid = document.createElement('div');
    infoGrid.className = 'dir-modal__info';
    fields.forEach(function (f) {
      if (!f.value) return;
      var row = document.createElement('div');
      row.className = 'dir-modal__row';

      var label = document.createElement('span');
      label.className = 'dir-modal__label';
      label.textContent = f.label;
      row.appendChild(label);

      var val = document.createElement('span');
      val.className = 'dir-modal__value';
      if (f.label === 'Status') {
        var s = document.createElement('span');
        s.className = 'dir-modal__status dir-modal__status--' + f.value;
        s.textContent = STATE_LABELS[f.value] || f.value;
        val.appendChild(s);
      } else {
        val.textContent = f.value;
      }
      row.appendChild(val);
      infoGrid.appendChild(row);
    });
    panel.appendChild(infoGrid);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    var escHandler = function (e) {
      if (e.key === 'Escape') {
        overlay.remove();
        document.removeEventListener('keydown', escHandler);
      }
    };
    document.addEventListener('keydown', escHandler);
  }

  function buildFloorSection(floorKey, directors) {
    var cfg = FLOOR_CONFIG[floorKey] || { name: floorKey, color: '#8892a4' };
    var cssClass = FLOOR_CSS_CLASS[floorKey] || '';

    var section = document.createElement('div');
    section.className = 'dir-floor ' + cssClass;

    // Header
    var header = document.createElement('div');
    header.className = 'dir-floor__header';

    var bar = document.createElement('div');
    bar.className = 'dir-floor__bar';
    bar.style.background = cfg.color;
    header.appendChild(bar);

    var name = document.createElement('span');
    name.className = 'dir-floor__name';
    name.style.color = cfg.color;
    name.textContent = cfg.name;
    header.appendChild(name);

    var badge = document.createElement('span');
    badge.className = 'dir-floor__badge';
    badge.style.color = cfg.color;
    badge.style.borderColor = cfg.color.replace(')', ',0.25)').replace('rgb', 'rgba');
    badge.textContent = directors.length + (directors.length === 1 ? ' Director' : ' Directors');
    header.appendChild(badge);

    section.appendChild(header);

    // Grid
    var grid = document.createElement('div');
    grid.className = 'dir-grid' + (directors.length === 1 ? ' dir-grid--single' : '');
    grid.setAttribute('data-stagger', '');

    directors.forEach(function (d) {
      grid.appendChild(buildCard(d, cfg.color));
    });

    section.appendChild(grid);
    return section;
  }

  function render(directors) {
    var container = document.getElementById('directorsContainer');
    if (!container) return;

    // Group by floor
    var grouped = {};
    directors.forEach(function (d) {
      var floor = (d.floor || 'SERVICES').toUpperCase();
      if (!grouped[floor]) grouped[floor] = [];
      grouped[floor].push(d);
    });

    // Clear loading text
    clearChildren(container);

    // Render in floor order
    FLOOR_ORDER.forEach(function (floorKey) {
      var list = grouped[floorKey];
      if (list && list.length) {
        container.appendChild(buildFloorSection(floorKey, list));
      }
    });
  }

  var API_URL = 'https://platform.kytranempowerment.com/api/public/directory';
  var FALLBACK_URL = 'data/directors.json';

  function init() {
    fetch(API_URL)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        // API returns {success, agents: [...], summary}
        var agents = data.agents || data;
        // Filter to directors only
        var directors = agents.filter(function (a) { return a.is_director; });
        if (directors.length === 0) directors = agents.filter(function (a) { return !!a.acronym; });
        render(directors);
      })
      .catch(function (err) {
        console.warn('[ai-directors] API unavailable, falling back to static JSON:', err.message);
        // Fallback to static file if API is unreachable (e.g., local dev)
        fetch(FALLBACK_URL)
          .then(function (res) {
            if (!res.ok) throw new Error('HTTP ' + res.status);
            return res.json();
          })
          .then(function (data) {
            var agents = data.agents || data;
            var directors = agents.filter(function (a) { return a.is_director; });
            if (directors.length === 0) directors = agents.filter(function (a) { return !!a.acronym; });
            render(directors);
          })
          .catch(function (err2) {
            console.error('[ai-directors] Failed to load directors:', err2);
            var container = document.getElementById('directorsContainer');
            if (container) {
              clearChildren(container);
              var msg = document.createElement('p');
              msg.style.textAlign = 'center';
              msg.style.color = '#ef4444';
              msg.textContent = 'Unable to load directors. Please refresh the page.';
              container.appendChild(msg);
            }
          });
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
