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

  function buildCard(director, floorColor, floorName) {
    var card = document.createElement('div');
    card.className = 'glass-panel dir-card';
    card.style.setProperty('--floor-accent', floorColor);

    // Avatar
    card.appendChild(buildAvatar(director, floorColor));

    // Top row: acronym + floor badge (matches Design's AiDirectors.dc.html)
    var topRow = document.createElement('div');
    topRow.className = 'dir-card__top-row';

    var acronym = document.createElement('span');
    acronym.className = 'dir-card__acronym';
    acronym.style.color = floorColor;
    acronym.textContent = director.acronym || director.display_name || director.name;
    topRow.appendChild(acronym);

    var floorBadge = document.createElement('span');
    floorBadge.className = 'dir-card__floor-badge';
    floorBadge.style.color = floorColor;
    floorBadge.textContent = floorName;
    topRow.appendChild(floorBadge);

    card.appendChild(topRow);

    // Acronym expansion
    var expansion = document.createElement('span');
    expansion.className = 'dir-card__name';
    expansion.textContent = director.acronym_expansion || '';
    card.appendChild(expansion);

    // Department
    var dept = document.createElement('span');
    dept.className = 'dir-card__dept';
    dept.textContent = director.department || '';
    card.appendChild(dept);

    // Title (role) — colored by floor, per Design
    if (director.title) {
      var titleEl = document.createElement('span');
      titleEl.className = 'dir-card__title';
      titleEl.style.color = floorColor;
      titleEl.textContent = director.title;
      card.appendChild(titleEl);
    }

    // Bio / description
    var desc = document.createElement('p');
    desc.className = 'dir-card__desc';
    desc.textContent = director.description || director.bio || '';
    card.appendChild(desc);

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

  /* Single flat grid, per AiDirectors.dc.html — Design shows one grid of
     cards (each carrying its own floor badge + colored left border), not
     grouped floor sections with headers. Directors are still sorted in
     floor order so the visual grouping reads top-to-bottom even without
     section breaks. */
  function render(directors) {
    var container = document.getElementById('directorsContainer');
    if (!container) return;

    var sorted = directors.slice().sort(function (a, b) {
      var fa = FLOOR_ORDER.indexOf((a.floor || 'SERVICES').toUpperCase());
      var fb = FLOOR_ORDER.indexOf((b.floor || 'SERVICES').toUpperCase());
      if (fa === -1) fa = FLOOR_ORDER.length;
      if (fb === -1) fb = FLOOR_ORDER.length;
      return fa - fb;
    });

    clearChildren(container);

    var grid = document.createElement('div');
    grid.className = 'dir-grid';
    grid.setAttribute('data-stagger', '');

    sorted.forEach(function (d) {
      var floorKey = (d.floor || 'SERVICES').toUpperCase();
      var cfg = FLOOR_CONFIG[floorKey] || { name: d.floor || 'Services', color: '#8892a4' };
      grid.appendChild(buildCard(d, cfg.color, cfg.name));
    });

    container.appendChild(grid);

    // Update the hero + CTA counts from the real fetched roster — never
    // hardcode a director/staff count in HTML (see today's "13 agents"
    // and "50+ agents" copy bugs).
    var heroSub = document.getElementById('dirHeroSubtitle');
    if (heroSub) {
      heroSub.textContent = sorted.length + ' autonomous leaders managing every aspect of your business under C.R.E.E.D. ethical governance.';
    }
    var ctaCount = document.getElementById('dirCtaCount');
    if (ctaCount) {
      ctaCount.textContent = 'See what ' + sorted.length + ' AI Directors and 130+ staff agents can do for your business.';
    }
  }

  var API_URL = 'data/directors.json';
  var FALLBACK_URL = 'https://platform.kytranempowerment.com/api/public/directory';

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
