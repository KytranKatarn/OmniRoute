/* AI Directors — dynamic renderer from directors.json */
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
    img.src = director.avatar_url || '';
    img.alt = (director.display_name || director.name) + ' portrait';
    img.loading = 'lazy';

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

    return card;
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

  function init() {
    fetch('data/directors.json')
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(render)
      .catch(function (err) {
        console.error('[ai-directors] Failed to load directors:', err);
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
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
