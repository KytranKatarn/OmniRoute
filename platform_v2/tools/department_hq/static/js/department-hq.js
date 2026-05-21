/* ============================================================================
   Department HQ — Tab switching, API calls, rendering
   All dynamic HTML is escaped via esc() which uses textContent for XSS safety.
   This is an admin-only internal module.
   ============================================================================ */

const DHQ_BASE = '/tools/department-hq';

const FLOOR_COLORS = {
    BRIDGE:      '#00FFFF',
    OPERATIONS:  '#FFAA00',
    ENGINEERING: '#0EA5E9',
    CREATIVE:    '#F472B6',
    SERVICES:    '#10B981',
};

const FLOOR_ORDER = ['BRIDGE', 'OPERATIONS', 'ENGINEERING', 'CREATIVE', 'SERVICES'];

// Track which tabs have been loaded
const loaded = {};
let rosterDebounce = null;
let rosterView = 'cards'; // 'cards' or 'table'
let lastRosterData = null; // cache for view switching

// ───────────────────────────────────────────────────────────────
// Helpers
// ───────────────────────────────────────────────────────────────

function esc(s) {
    if (s == null) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

// Append cache-bust query param so an updated avatar replaces the cached
// image immediately. Stable per-agent paths (/static/media/portraits/<name>.png)
// would otherwise serve a stale browser-cache hit after re-upload/approve.
function bust(url, ts) {
    if (!url) return '';
    if (!ts) return url;
    var v = typeof ts === 'string' ? (Date.parse(ts) || ts) : ts;
    return url + (url.indexOf('?') === -1 ? '?' : '&') + 'v=' + v;
}

async function api(path) {
    const res = await fetch(DHQ_BASE + path);
    if (!res.ok) throw new Error(`API ${path} returned ${res.status}`);
    return res.json();
}

async function apiPost(path, body) {
    const res = await fetch(DHQ_BASE + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        let msg = `POST ${path} returned ${res.status}`;
        try { const d = await res.json(); msg = d.error || msg; } catch (_) {}
        throw new Error(msg);
    }
    return res.json();
}

function floorColor(floor) {
    return FLOOR_COLORS[floor] || '#00e5ff';
}

function shiftBadge(state) {
    return '<span class="dhq-shift-badge dhq-shift-' + esc(state) + '">' + esc(state).replace('_', ' ') + '</span>';
}

function creedClass(score) {
    if (score >= 80) return 'dhq-creed-high';
    if (score >= 50) return 'dhq-creed-mid';
    return 'dhq-creed-low';
}

function stressClass(level) {
    if (level >= 0.7) return 'dhq-stress-high';
    if (level >= 0.4) return 'dhq-stress-mid';
    return 'dhq-stress-low';
}

function fmtTime(iso) {
    if (!iso) return '\u2014';
    try {
        // Force UTC: DB returns naive timestamps \u2014 append Z so browser converts to local EDT
        const s = (typeof iso === 'string' && !iso.endsWith('Z') && !iso.includes('+')) ? iso + 'Z' : iso;
        const d = new Date(s);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch (_) { return iso; }
}

function setHtml(el, html) {
    // Centralised DOM write — all values pre-escaped via esc()
    el.innerHTML = html;
}

// ───────────────────────────────────────────────────────────────
// Tab Switching
// ───────────────────────────────────────────────────────────────

function switchTab(tab) {
    // Dispatch tab merged into A.R.M.A.D.A. — redirect to fleet + DISPATCH sub-tab
    if (tab === 'dispatch') {
        switchTab('fleet');
        setTimeout(function() { switchArmadaSection('dispatch'); }, 250);
        return;
    }
    document.querySelectorAll('.dhq-tab').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    // Sync the lcars-header-tab nav indicator (uses different class from dhq-tab)
    document.querySelectorAll('.lcars-header-tab[data-tab]').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    // Scroll the active tab button into view (important on mobile where nav overflows)
    try {
        var _activeNavBtn = document.querySelector('.lcars-header-tab.active');
        if (_activeNavBtn) _activeNavBtn.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    } catch (_) {}
    document.querySelectorAll('.dhq-panel').forEach(function(p) {
        var isActive = p.id === 'panel-' + tab;
        p.classList.toggle('active', isActive);
        p.style.display = isActive ? 'block' : '';
    });
    // Persist active tab so refresh restores it
    try { localStorage.setItem('dhq_active_tab', tab); } catch (_) {}
    // Update URL hash so hard refresh lands on correct tab (not last-hash)
    try { history.replaceState(null, '', '#' + tab); } catch (_) {}
    var loaders = {
        'overview':     loadOverview,
        'roster':       loadRoster,
        'kin':          loadKinTab,
        'creed':        loadCreed,
        'social':       loadSocialFeed,
        'dispatch':     loadDispatch,
        'fleet':        loadFleet,
        'contractors':  loadContractors,
        'autonomy':     loadAutonomy,
        'alerts':       function() {
            var ah = document.getElementById('alerts-history-section');
            if (ah) ah.style.display = '';
            if (typeof ahInit === 'function') ahInit();
        },
        'approvals':    function() { if (typeof loadDhqApprovals === 'function') loadDhqApprovals(); },
        'coms':         function() { if (typeof window._comsLoad === 'function') window._comsLoad(); },
        'scout':        function() { if (typeof loadScoutTab === 'function') loadScoutTab(); },
    };
    // Approvals should always reload on tab click (not cached) for fresh state
    if (tab === 'approvals') {
        if (typeof loadDhqApprovals === 'function') loadDhqApprovals();
    } else if (!loaded[tab] && loaders[tab]) {
        loaded[tab] = true;
        loaders[tab]();
    }
    // Initialise dispatch history section on first dispatch tab open
    if (tab === 'dispatch' && typeof dhInit === 'function') {
        dhInit();
    }
    if (tab === 'roster') {
        if (typeof toggleRosterView === 'function') toggleRosterView('list');
    }
}

// ───────────────────────────────────────────────────────────────
// Overview
// ───────────────────────────────────────────────────────────────

async function loadOverview() {
    var el = document.getElementById('overviewContent');
    try {
        var data = await api('/api/overview-stats');
        loaded['overview'] = true;

        var a = data.agents || {};
        var j = data.jobs_24h || {};
        var k = data.knowledge || {};
        var o = data.ollama || {};
        var s = data.scans || {};
        var q = data.qa || {};

        var html = '';

        // ── Hero Stats Row ──
        html += '<div class="dhq-hero-stats">';
        html += heroCard(a.active || 0, 'Agents Online', '#00e5ff');
        html += heroCard(o.models_loaded || '?', 'Models Loaded', '#10b981');
        html += heroCard(j.total || 0, 'Jobs 24h', '#fbbf24');
        html += heroCard(j.success_rate ? j.success_rate + '%' : '—', 'Success Rate', j.success_rate >= 90 ? '#10b981' : j.success_rate >= 70 ? '#fbbf24' : '#f87171');
        html += heroCard(s.security_issues || 0, 'Security Issues', s.security_issues > 0 ? '#f87171' : '#10b981');
        html += heroCard(formatNum(k.total || 0), 'KB Entries', '#8b5cf6');
        html += '</div>';

        // ── Attention Needed ──
        var attn = data.attention || [];
        if (attn.length > 0) {
            html += '<div class="dhq-attention">';
            html += '<div class="dhq-attention-header">ATTENTION NEEDED</div>';
            for (var i = 0; i < attn.length && i < 8; i++) {
                var item = attn[i];
                var icon = item.level === 'error' ? '🔴' : item.level === 'warn' ? '🟡' : '🟢';
                var tab = item.link_tab || '';
                html += '<div class="dhq-attention-item" onclick="switchTab(\'' + esc(tab) + '\')">'
                    + '<span class="dhq-attention-icon">' + icon + '</span>'
                    + '<span class="dhq-attention-text">' + esc(item.text) + '</span>'
                    + '<span class="dhq-attention-link">→ ' + esc(tab) + '</span>'
                    + '</div>';
            }
            html += '</div>';
        }

        // ── Department Grid (condensed) ──
        var floors = data.floors || [];
        if (floors.length > 0) {
            var floorColors = {
                'BRIDGE': '#00e5ff', 'OPERATIONS': '#fbbf24', 'ENGINEERING': '#10b981',
                'CREATIVE': '#f472b6', 'SERVICES': '#8b5cf6'
            };
            html += '<div class="dhq-floor-grid">';
            for (var fi = 0; fi < floors.length; fi++) {
                var f = floors[fi];
                var color = floorColors[f.name] || '#666';
                html += '<div class="dhq-floor-card" style="border-left:3px solid ' + color + '">'
                    + '<div class="dhq-floor-card-name" style="color:' + color + '">' + esc(f.name) + '</div>'
                    + '<div class="dhq-floor-card-stats">'
                    + f.agents + ' agents · ' + f.active + ' active · ' + f.departments + ' depts'
                    + '</div></div>';
            }
            html += '</div>';
        }

        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading overview: ' + esc(err.message) + '</div>');
    }
}

function heroCard(value, label, color) {
    return '<div class="dhq-hero-card">'
        + '<div class="dhq-hero-val" style="color:' + color + '">' + value + '</div>'
        + '<div class="dhq-hero-label">' + label + '</div>'
        + '</div>';
}

function formatNum(n) {
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return '' + n;
}

function populateDeptFilters(floors) {
    var sel = document.getElementById('workDept');
    if (!sel || sel.options.length > 1) return;
    for (var fi = 0; fi < FLOOR_ORDER.length; fi++) {
        var floor = floors[FLOOR_ORDER[fi]];
        if (!floor) continue;
        for (var di = 0; di < floor.departments.length; di++) {
            var opt = document.createElement('option');
            opt.value = floor.departments[di].department;
            opt.textContent = floor.departments[di].department;
            sel.appendChild(opt);
        }
    }
}

// ───────────────────────────────────────────────────────────────
// Org Chart
// ───────────────────────────────────────────────────────────────

async function loadOrgChart() {
    var el = document.getElementById('orgChartContent');
    try {
        var data = await api('/api/org-chart');
        loaded['org-chart'] = true;

        var html = '';
        for (var fi = 0; fi < FLOOR_ORDER.length; fi++) {
            var fl = FLOOR_ORDER[fi];
            var floor = data.floors[fl];
            if (!floor) continue;
            var color = floorColor(fl);

            html += '<div class="dhq-org-floor">'
                + '<div class="dhq-floor-header" data-floor="' + esc(fl) + '">'
                + '<span class="dhq-floor-name" style="color:' + color + '">' + esc(fl) + '</span>'
                + '<span class="dhq-floor-badge">' + floor.departments.length + ' depts</span>'
                + '</div>';

            for (var di = 0; di < floor.departments.length; di++) {
                var dept = floor.departments[di];
                html += '<div class="dhq-org-dept">'
                    + '<div class="dhq-org-dept-header">'
                    + '<span class="dhq-dept-name" style="color:' + color + '">' + esc(dept.department) + '</span>'
                    + '</div>';

                if (dept.director) {
                    var d = dept.director;
                    var dInitial = (d.display_name || d.name || '?').charAt(0).toUpperCase();
                    var dAvatar = d.avatar_url
                        ? '<span class="dhq-org-avatar-initials" style="display:none">' + esc(dInitial) + '</span>'
                          + '<img src="' + esc(bust(d.avatar_url, d.avatar_updated_at)) + '" alt="" loading="lazy"'
                          + ' onerror="this.style.display=\'none\';this.previousElementSibling.style.display=\'flex\'">'
                        : '<span>' + esc(dInitial) + '</span>';
                    html += '<div class="dhq-org-director dhq-clickable" onclick="openAgentSummary(' + d.id + ')">'
                        + '<div class="dhq-org-director-icon">' + dAvatar + '</div>'
                        + '<div>'
                        + '<div class="dhq-org-director-name">' + esc(d.display_name || d.name) + '</div>'
                        + '<div class="dhq-org-director-code">' + esc(d.name) + ' ' + shiftBadge(d.shift_state) + '</div>'
                        + '</div></div>';
                }

                if (dept.staff.length > 0) {
                    html += '<div class="dhq-org-staff-grid">';
                    for (var si = 0; si < dept.staff.length; si++) {
                        var a = dept.staff[si];
                        var sInitial = (a.display_name || a.name || '?').charAt(0).toUpperCase();
                        var sAvatar = a.avatar_url
                            ? '<span class="dhq-org-staff-initials" style="display:none">' + esc(sInitial) + '</span>'
                              + '<img src="' + esc(bust(a.avatar_url, a.avatar_updated_at)) + '" alt="" loading="lazy"'
                              + ' onerror="this.style.display=\'none\';this.previousElementSibling.style.display=\'flex\'">'
                            : '<span>' + esc(sInitial) + '</span>';
                        html += '<div class="dhq-org-agent dhq-clickable" onclick="openAgentSummary(' + a.id + ')">'
                            + '<span class="dhq-org-staff-avatar">' + sAvatar + '</span>'
                            + '<span class="dhq-org-agent-dot ' + esc(a.shift_state) + '"></span>'
                            + '<span>' + esc(a.display_name || a.name) + '</span>'
                            + '</div>';
                    }
                    html += '</div>';
                } else if (!dept.director) {
                    html += '<div class="dhq-empty" style="padding:0.5rem">No agents assigned</div>';
                }
                html += '</div>';
            }
            html += '</div>';
        }

        setHtml(el, html || '<div class="dhq-empty">No org chart data found.</div>');
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading org chart: ' + esc(err.message) + '</div>');
    }
}

// ───────────────────────────────────────────────────────────────
// Roster
// ───────────────────────────────────────────────────────────────

function debounceRoster() {
    clearTimeout(rosterDebounce);
    rosterDebounce = setTimeout(loadRoster, 300);
}

function setRosterView(view) {
    rosterView = view;
    document.querySelectorAll('.dhq-view-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.view === view);
    });
    if (lastRosterData) {
        renderRoster(lastRosterData);
    }
}

function toggleRosterView(view) {
    var listEl  = document.getElementById('rosterContent');
    var chartEl = document.getElementById('rosterOrgChartProxy');
    var isChart = (view === 'org-chart');
    if (listEl)  listEl.style.display  = isChart ? 'none' : '';
    if (chartEl) chartEl.style.display = isChart ? ''     : 'none';
    document.querySelectorAll('.dhq-roster-view-bar-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.rosterview === view);
    });
    if (isChart && !loaded['org-chart']) { loadOrgChart(); }
}

async function loadRoster() {
    var el = document.getElementById('rosterContent');
    var search = document.getElementById('rosterSearch').value;
    var floor = document.getElementById('rosterFloor').value;
    var shift = document.getElementById('rosterShift').value;

    var params = new URLSearchParams();
    if (search) params.set('search', search);
    if (floor) params.set('floor', floor);
    if (shift) params.set('shift_state', shift);

    try {
        var data = await api('/api/roster?' + params.toString());
        loaded['roster'] = true;
        lastRosterData = data;

        document.getElementById('rosterCount').textContent = data.total + ' agents';

        if (data.agents.length === 0) {
            setHtml(el, '<div class="dhq-empty">No agents match filters.</div>');
            return;
        }

        renderRoster(data);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading roster: ' + esc(err.message) + '</div>');
    }
}

function renderRoster(data) {
    var el = document.getElementById('rosterContent');
    if (rosterView === 'table') {
        renderRosterTable(data, el);
    } else if (rosterView === 'gallery') {
        renderRosterGallery(data, el);
    } else {
        renderRosterCards(data, el);
    }
}

function renderRosterGallery(data, el) {
    // Portrait-first grid. Agents missing an avatar_url get a red
    // "missing" indicator + eligible for the bulk-generate action.
    var agents = data.agents || [];
    var missing = agents.filter(function(a) { return !a.avatar_url; });

    var html = '';
    if (missing.length > 0) {
        html += '<div class="dhq-gallery-toolbar">'
            + '<span class="dhq-gallery-missing-count">'
            + missing.length + ' missing portrait' + (missing.length === 1 ? '' : 's')
            + '</span>'
            + '<button class="dhq-action-btn dhq-gallery-bulk-btn" onclick="generateAllMissingPortraits()">'
            + 'Generate All Missing</button>'
            + '</div>';
    }

    html += '<div class="dhq-gallery-grid">';
    agents.forEach(function(a) {
        var color = floorColor(a.floor);
        var initials = (a.display_name || a.name || '?').split(' ')
            .map(function(w) { return w[0]; }).join('').substring(0, 2).toUpperCase();
        var isMissing = !a.avatar_url;
        var portraitInner = isMissing
            ? '<div class="dhq-gallery-placeholder" style="color:' + color + '"><span>' + esc(initials) + '</span></div>'
            : '<span class="dhq-gallery-initials" style="display:none;color:' + color + '">' + esc(initials) + '</span>'
              + '<img src="' + esc(bust(a.avatar_url, a.avatar_updated_at)) + '" alt="" loading="lazy"'
              + ' onerror="this.style.display=\'none\';this.previousElementSibling.style.display=\'flex\'">';

        html += '<div class="dhq-gallery-card ' + (isMissing ? 'missing' : '') + '"'
            + ' onclick="openAgentDetail(' + a.id + ')" style="--card-accent:' + color + '">'
            + '<div class="dhq-gallery-portrait">'
            + portraitInner
            + (isMissing ? '<span class="dhq-gallery-missing-badge">MISSING</span>' : '')
            + (a.is_department_ai ? '<span class="dhq-gallery-director-badge">DIRECTOR</span>' : '')
            + '</div>'
            + '<div class="dhq-gallery-info">'
            + '<div class="dhq-gallery-name">' + esc(a.display_name || a.name) + '</div>'
            + (a.title
                ? '<div class="dhq-gallery-title">' + esc(a.title) + '</div>'
                : '')
            + '<div class="dhq-gallery-dept" style="color:' + color + '">' + esc(a.department || '') + '</div>'
            + '</div>'
            + '</div>';
    });
    html += '</div>';

    setHtml(el, html);
}

/** Bulk-generate portraits for every currently-visible agent with no avatar_url.
    Sequential to avoid VRAM pressure — each dispatches through P.I.X.E.L.'s
    image_generation skill → ComfyUI (see debe63d3 pipeline fix). */
async function generateAllMissingPortraits() {
    var agents = (lastRosterData && lastRosterData.agents) || [];
    var missing = agents.filter(function(a) { return !a.avatar_url; });
    if (missing.length === 0) {
        alert('No missing portraits.');
        return;
    }
    if (!confirm('Generate ' + missing.length + ' portrait'
        + (missing.length === 1 ? '' : 's')
        + '? ~3 min each, sequential. GPU will be busy throughout.')) {
        return;
    }

    var btn = document.querySelector('.dhq-gallery-bulk-btn');
    var ok = 0, fail = 0;
    for (var i = 0; i < missing.length; i++) {
        var a = missing[i];
        if (btn) btn.textContent = 'Generating ' + (i+1) + '/' + missing.length + ' — ' + (a.display_name || a.name);
        try {
            var resp = await fetch('/tools/department-hq/api/agents/' + a.id + '/generate-portrait', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: '{}'
            });
            var result = await resp.json();
            if (result.success) ok++; else fail++;
        } catch (e) {
            fail++;
        }
    }
    if (btn) btn.textContent = 'Done — ' + ok + ' ok, ' + fail + ' failed';
    // Refresh roster after a moment to pick up new avatar_urls
    setTimeout(loadRoster, 1500);
}

function renderRosterTable(data, el) {
    var html = '<table class="dhq-roster-table">'
        + '<thead><tr>'
        + '<th>Agent</th><th>Department</th><th>Floor</th><th>Shift</th><th>Role</th><th>Actions</th>'
        + '</tr></thead><tbody>';

    for (var i = 0; i < data.agents.length; i++) {
        var a = data.agents[i];
        var color = floorColor(a.floor);
        html += '<tr class="dhq-roster-row" onclick="openAgentDetail(' + a.id + ')">'
            + '<td><div style="font-weight:600">' + esc(a.display_name || a.name) + ' <span class="dhq-wellness-dot" data-status="' + esc(a.wellness_status || 'green') + '" title="Stress: ' + (a.stress_level != null ? a.stress_level.toFixed(2) : '0.00') + '"></span></div>'
            + '<div style="font-size:0.7rem;color:var(--dhq-text-dim)">' + esc(a.name) + '</div></td>'
            + '<td style="color:' + color + '">' + esc(a.department) + '</td>'
            + '<td>' + esc(a.floor) + '</td>'
            + '<td>' + shiftBadge(a.shift_state) + '</td>'
            + '<td>' + (a.is_department_ai ? '<span class="dhq-role-director">DIRECTOR</span>' : 'Staff') + '</td>'
            + '<td><button class="dhq-action-btn" onclick="event.stopPropagation();toggleShift(' + a.id + ',\'' + esc(a.shift_state) + '\')">Shift</button></td>'
            + '</tr>';
    }
    html += '</tbody></table>';
    setHtml(el, html);
}

// ── Shift group config ──
var SHIFT_GROUPS = [
    { key: 'active',       label: 'ON DUTY',       color: '#10b981', icon: '\u25CF' },
    { key: 'winding_down', label: 'WINDING DOWN',  color: '#f97316', icon: '\u25D6' },
    { key: 'deployed',     label: 'DEPLOYED',       color: '#0ea5e9', icon: '\u2B06' },
    { key: 'barracked',    label: 'BARRACKED',      color: '#6b7280', icon: '\u2588' },
    { key: 'cooldown',     label: 'COOLDOWN',       color: '#f59e0b', icon: '\u2744' },
    { key: 'off_duty',     label: 'OFF DUTY',       color: '#4b5563', icon: '\u2014' },
];

function renderRosterCards(data, el) {
    // Group agents by shift state
    var groups = {};
    SHIFT_GROUPS.forEach(function(g) { groups[g.key] = []; });

    data.agents.forEach(function(a) {
        var key = a.shift_state || 'off_duty';
        if (!groups[key]) groups[key] = [];
        groups[key].push(a);
    });

    var html = '';

    SHIFT_GROUPS.forEach(function(g) {
        var agents = groups[g.key];
        if (!agents || agents.length === 0) return;

        var groupId = 'crew-group-' + g.key;
        html += '<div class="dhq-crew-group">'
            + '<div class="dhq-crew-group-header" onclick="toggleCrewGroup(\'' + groupId + '\')" style="--group-color:' + g.color + '">'
            + '<span class="dhq-crew-group-icon" style="color:' + g.color + '">' + g.icon + '</span>'
            + '<span class="dhq-crew-group-label" style="color:' + g.color + '">' + g.label + '</span>'
            + '<span class="dhq-crew-group-count">' + agents.length + '</span>'
            + '<span class="dhq-crew-group-chevron" id="chevron-' + groupId + '">\u25BC</span>'
            + '</div>'
            + '<div class="dhq-crew-grid" id="' + groupId + '">';

        agents.forEach(function(a) {
            var color = floorColor(a.floor);
            var initials = (a.display_name || a.name || '?').split(' ').map(function(w) { return w[0]; }).join('').substring(0, 2).toUpperCase();

            // Avatar: render both fallback span (hidden) and img (visible).
            // If the image errors, hide it and show the sibling initials.
            // Avoids innerHTML mutation — safer against any future content drift.
            var avatarInner = a.avatar_url
                ? '<span class="dhq-crew-avatar-initials" style="display:none">' + esc(initials) + '</span>'
                  + '<img src="' + esc(bust(a.avatar_url, a.avatar_updated_at)) + '" alt="" loading="lazy"'
                  + ' onerror="this.style.display=\'none\';this.previousElementSibling.style.display=\'flex\'">'
                : '<span>' + esc(initials) + '</span>';

            html += '<div class="dhq-crew-card" onclick="openAgentDetail(' + a.id + ')" style="--card-accent:' + color + '">'
                + '<div class="dhq-crew-card-top">'
                + '<div class="dhq-crew-avatar" style="border-color:' + color + '">'
                + avatarInner
                + '</div>'
                + '<div class="dhq-crew-card-info">'
                + '<div class="dhq-crew-card-name">' + esc(a.display_name || a.name) + ' <span class="dhq-wellness-dot" data-status="' + esc(a.wellness_status || 'green') + '" title="Stress: ' + (a.stress_level != null ? a.stress_level.toFixed(2) : '0.00') + '"></span></div>'
                + (a.acronym_expansion
                    ? '<div class="dhq-crew-card-acronym">&ldquo;' + esc(a.acronym_expansion) + '&rdquo;</div>'
                    : '')
                + (a.title
                    ? '<div class="dhq-crew-card-title">' + esc(a.title) + '</div>'
                    : '<div class="dhq-crew-card-code">' + esc(a.display_name || a.name) + '</div>')
                + '</div>'
                + '</div>'
                + '<div class="dhq-crew-card-meta">'
                + '<div class="dhq-crew-card-dept" style="color:' + color + '">' + esc(a.department) + '</div>'
                + '<span class="dhq-crew-floor-badge" style="background:' + color + '20;color:' + color + '">' + esc(a.floor) + '</span>'
                + '</div>'
                + '<div class="dhq-crew-card-bottom">'
                + shiftBadge(a.shift_state)
                + (a.is_department_ai ? ' <span class="dhq-role-director">DIRECTOR</span>' : '')
                + (a.model ? '<span class="dhq-crew-model">' + esc(a.model) + '</span>' : '')
                + '</div>'
                + '</div>';
        });

        html += '</div></div>';
    });

    setHtml(el, html);
}

function toggleCrewGroup(groupId) {
    var grid = document.getElementById(groupId);
    var chevron = document.getElementById('chevron-' + groupId);
    if (!grid) return;
    var collapsed = grid.classList.toggle('dhq-crew-grid-collapsed');
    if (chevron) chevron.textContent = collapsed ? '\u25B6' : '\u25BC';
}

async function toggleShift(agentId, currentState) {
    var states = ['active', 'barracked', 'off_duty'];
    var idx = states.indexOf(currentState);
    var next = states[(idx + 1) % states.length];

    var data = await apiPost('/api/roster/shift', { agent_id: agentId, shift_state: next });
    if (data.success) {
        loadRoster();
    } else {
        alert(data.error || 'Failed to change shift state');
    }
}

// ───────────────────────────────────────────────────────────────
// K.I.N. — HR & Culture unified tab (Welfare + Work + Performance)
// ───────────────────────────────────────────────────────────────

var _kinActiveSection = 'welfare';

function switchKinSection(section) {
    _kinActiveSection = section;
    ['welfare', 'workload', 'work', 'performance'].forEach(function(s) {
        var el = document.getElementById('kinSection-' + s);
        var btn = document.getElementById('kinBtn-' + s);
        if (el) el.style.display = s === section ? '' : 'none';
        if (btn) btn.classList.toggle('dhq-traffic-btn-active', s === section);
    });
    if (section === 'work') loadWorkSessions();
    if (section === 'performance') loadPerformance();
    if (section === 'workload') loadKinWorkload();
}

var _kinRefreshInterval = null;

async function loadKinTab() {
    await loadKinWelfare();
    loadWorkSessions();
    // Auto-refresh welfare + workload every 60s
    if (_kinRefreshInterval) clearInterval(_kinRefreshInterval);
    _kinRefreshInterval = setInterval(function() {
        if (_kinActiveSection === 'welfare') loadKinWelfare();
        if (_kinActiveSection === 'workload') loadKinWorkload();
    }, 60000);
}

async function loadKinWelfare() {
    var el = document.getElementById('kinWelfareContent');
    if (el) el.textContent = 'Loading…';
    try {
        var r = await fetch('/tools/department-hq/api/kin/welfare');
        var d = await r.json();
        if (!d.success) throw new Error(d.error || 'failed');

        // Banner counts
        var rc = document.getElementById('kinRestingCount');
        var al = document.getElementById('kinAtLimitCount');
        var ac = document.getElementById('kinActiveCount');
        if (rc) { rc.textContent = (d.resting_count || 0) + ' resting'; rc.style.color = (d.resting_count || 0) > 0 ? '#f59e0b' : '#10b981'; }
        if (al) { al.textContent = (d.at_limit_count || 0) + ' at limit'; al.style.color = (d.at_limit_count || 0) > 0 ? '#ef4444' : 'var(--dhq-text-dim)'; }
        if (ac) ac.textContent = (d.active_count || 0) + ' active';

        if (!el) return;
        el.innerHTML = '';

        // Last reset banner
        if (d.last_reset && d.last_reset.at) {
            var resetBanner = document.createElement('div');
            resetBanner.style.cssText = 'background:rgba(139,92,246,0.1);border:1px solid #7c3aed44;border-radius:6px;padding:8px 12px;margin-bottom:12px;font-size:0.72rem;';
            var resetAt = new Date(d.last_reset.at);
            resetBanner.innerHTML = '<span style="color:#a78bfa;font-family:Antonio,sans-serif;letter-spacing:1px;">⟳ LAST BUDGET RESET</span>'
                + ' <span style="color:var(--dhq-text-dim);">' + resetAt.toLocaleDateString() + ' ' + resetAt.toLocaleTimeString() + '</span>'
                + ' · <span style="color:var(--dhq-text-dim);">by ' + (d.last_reset.by || 'system') + '</span>'
                + ' · <span style="color:#10b981;">limit set to ' + (d.last_reset.limit_set || 1000) + '</span>'
                + (d.last_reset.reason ? '<div style="color:var(--dhq-text-dim);margin-top:3px;opacity:0.7;">' + d.last_reset.reason.substring(0, 120) + '…</div>' : '');
            el.appendChild(resetBanner);
        }

        // Welfare flags
        var agents = d.agents || [];
        if (!agents.length) {
            var none = document.createElement('div');
            none.style.cssText = 'color:var(--dhq-text-dim);font-size:0.78rem;padding:16px 0;';
            none.textContent = 'All agents active — no welfare flags';
            el.appendChild(none);
            return;
        }

        var grid = document.createElement('div');
        grid.style.cssText = 'display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;';
        agents.forEach(function(a) {
            var statusColor = a.resting ? '#f59e0b'
                : (a.at_limit ? '#ef4444'
                : (a.overwork_level === 'critical' ? '#ef4444'
                : (a.overwork_level === 'warning' ? '#f59e0b' : '#10b981')));
            var statusLabel = a.resting ? '😴 ' + (a.rest_type || 'resting')
                : (a.at_limit ? '⚠ at limit'
                : (a.overwork_level === 'critical' ? '🔥 ' + (a.hours_worked_today || 0).toFixed(1) + 'h OVERWORKED'
                : (a.overwork_level === 'warning' ? '⏱ ' + (a.hours_worked_today || 0).toFixed(1) + 'h today'
                : '✓ active')));
            var card = document.createElement('div');
            card.style.cssText = 'background:rgba(0,0,0,0.3);border:1px solid ' + statusColor + '44;border-radius:6px;padding:10px 12px;min-width:0;overflow:hidden;';
            card.innerHTML = '<div class="kinw-hdr" style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
                + '<div style="min-width:0;flex:1;">'
                + '<div style="font-family:Antonio,sans-serif;font-size:0.78rem;letter-spacing:1px;color:var(--dhq-text-main);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + esc(a.name) + '</div>'
                + '<div style="font-size:0.6rem;color:var(--dhq-text-dim);margin-top:1px;">' + esc(a.department) + '</div>'
                + '</div>'
                + '<span style="flex-shrink:0;font-size:0.65rem;color:' + statusColor + ';">' + statusLabel + '</span>'
                + '</div>'
                + '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;color:var(--dhq-text-dim);">'
                + (a.dispatches_since_reset || 0) + '/' + (a.task_limit || 1000) + ' dispatched'
                + (a.dispatches_1h ? ' · <span style="color:#00bcd4;">' + a.dispatches_1h + '/h</span>' : '')
                + (a.stress ? ' · stress: ' + Math.round(a.stress * 100) + '%' : '')
                + '</div>'
                + (a.rest_since
                    ? '<div style="margin-top:6px;">'
                      + '<div style="background:rgba(255,255,255,0.08);border-radius:3px;height:3px;overflow:hidden;margin-bottom:4px;">'
                      + '<div class="kinw-bar-fill" data-rest-at="' + new Date(a.rest_since).getTime() + '" style="height:100%;background:#f59e0b;border-radius:3px;width:0%;transition:width 0.5s linear;"></div>'
                      + '</div>'
                      + '<div style="display:flex;justify-content:space-between;font-size:0.63rem;color:#f59e0b;">'
                      + '<span>resting since ' + new Date(a.rest_since).toLocaleTimeString() + '</span>'
                      + '<span class="kinw-countdown" data-rest-at="' + new Date(a.rest_since).getTime() + '">…</span>'
                      + '</div>'
                      + '</div>'
                    : (a.at_limit
                        ? '<div style="font-size:0.62rem;color:#f59e0b;margin-top:4px;opacity:0.8;">K.I.N. monitoring · next check ≤10 min</div>'
                        : '')
                + (a.overwork_level && a.overwork_level !== 'normal' && !a.resting && a.hours_worked_today
                    ? '<div style="font-size:0.62rem;color:' + statusColor + ';margin-top:4px;">'
                      + (a.hours_worked_today || 0).toFixed(1) + 'h worked today'
                      + (a.overwork_level === 'critical' ? ' — 8h rest approval pending' : ' — K.I.N. monitoring')
                      + '</div>'
                    : ''));
            // Portrait injected via DOM (not innerHTML) to keep avatar_url out of HTML string
            var kinHdr = card.querySelector('.kinw-hdr');
            if (kinHdr) {
                var kinAvatar;
                if (a.avatar_url) {
                    kinAvatar = document.createElement('img');
                    kinAvatar.src = a.avatar_url;
                    kinAvatar.alt = '';
                    kinAvatar.loading = 'lazy';
                    kinAvatar.style.cssText = 'width:36px;height:36px;border-radius:50%;object-fit:cover;flex-shrink:0;border:1px solid ' + statusColor + '66;';
                } else {
                    kinAvatar = document.createElement('div');
                    kinAvatar.textContent = '🤖';
                    kinAvatar.style.cssText = 'width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.08);display:flex;align-items:center;justify-content:center;font-size:1rem;flex-shrink:0;';
                }
                kinHdr.insertBefore(kinAvatar, kinHdr.firstChild);
            }
            grid.appendChild(card);
        });
        el.appendChild(grid);

        // Live countdown: updates every second — progress bar fill + "recovers in Xm Ys"
        if (window._kinRestTimer) clearInterval(window._kinRestTimer);
        window._kinRestTimer = setInterval(function () {
            var REST_MS = 60 * 60 * 1000; // 1 hour rest period
            document.querySelectorAll('.kinw-countdown').forEach(function (span) {
                var restAt = parseInt(span.dataset.restAt, 10);
                var remaining = restAt + REST_MS - Date.now();
                if (remaining <= 0) { span.textContent = 'recovery due'; return; }
                var m = Math.floor(remaining / 60000);
                var s = Math.floor((remaining % 60000) / 1000);
                span.textContent = 'recovers in ' + m + 'm ' + (s < 10 ? '0' : '') + s + 's';
            });
            document.querySelectorAll('.kinw-bar-fill').forEach(function (bar) {
                var restAt = parseInt(bar.dataset.restAt, 10);
                var pct = Math.min(100, ((Date.now() - restAt) / REST_MS) * 100).toFixed(1);
                bar.style.width = pct + '%';
            });
        }, 1000);

        // Auto-refresh welfare data every 30 s so dispatch count updates live
        // when K.I.N. fires and resets dispatches_since_reset → 0
        if (window._kinWelfareRefresh) clearInterval(window._kinWelfareRefresh);
        window._kinWelfareRefresh = setInterval(loadKinWelfare, 30000);

    } catch (e) {
        if (el) el.textContent = 'Error: ' + e.message;
    }
}

async function loadKinWorkload() {
    var el = document.getElementById('kinWorkloadContent');
    if (!el) return;
    el.innerHTML = '<span style="color:var(--dhq-text-dim)">Loading workload…</span>';
    try {
        var r = await fetch('/tools/department-hq/api/kin/welfare');
        var d = await r.json();
        if (!d.success) throw new Error(d.error || 'failed');

        el.innerHTML = '';

        // Reset summary bar
        if (d.last_reset && d.last_reset.at) {
            var rb = document.createElement('div');
            rb.style.cssText = 'background:rgba(139,92,246,0.1);border:1px solid #7c3aed44;border-radius:6px;padding:8px 12px;margin-bottom:12px;font-size:0.72rem;display:flex;gap:16px;flex-wrap:wrap;';
            var resetAt = new Date(d.last_reset.at);
            rb.innerHTML = '<span style="color:#a78bfa;font-family:Antonio,sans-serif;letter-spacing:1px;">⟳ LAST RESET</span>'
                + '<span style="color:var(--dhq-text-dim);">' + resetAt.toLocaleDateString() + ' ' + resetAt.toLocaleTimeString() + '</span>'
                + '<span style="color:#10b981;">all agents · limit=' + (d.last_reset.limit_set || 1000) + '</span>'
                + '<span style="color:var(--dhq-text-dim);margin-left:auto;">aligned with C.R.E.E.D. welfare ethics</span>';
            el.appendChild(rb);
        }

        // Workload velocity table
        var wl = d.workload || [];
        if (!wl.length) {
            el.innerHTML += '<div style="color:var(--dhq-text-dim);padding:16px 0;">No dispatch activity in last 24h</div>';
            return;
        }

        var table = document.createElement('table');
        table.style.cssText = 'width:100%;border-collapse:collapse;font-size:0.72rem;';
        table.innerHTML = '<thead><tr style="color:var(--dhq-text-dim);border-bottom:1px solid rgba(255,255,255,0.1);">'
            + '<th style="text-align:left;padding:4px 8px;font-family:Antonio,sans-serif;letter-spacing:1px;">AGENT</th>'
            + '<th style="text-align:right;padding:4px 8px;">DEPT</th>'
            + '<th style="text-align:right;padding:4px 8px;">1H RATE</th>'
            + '<th style="text-align:right;padding:4px 8px;">24H TOTAL</th>'
            + '<th style="text-align:right;padding:4px 8px;">COUNT/LIMIT</th>'
            + '<th style="text-align:right;padding:4px 8px;">HRS TODAY</th>'
            + '<th style="text-align:right;padding:4px 8px;">ETA TO 1K</th>'
            + '</tr></thead>';
        var tbody = document.createElement('tbody');
        wl.forEach(function(a) {
            var sinceReset = a.dispatches_since_reset || 0;
            var limit = a.task_limit || 1000;
            var pct = Math.min(100, Math.round(sinceReset / limit * 100));
            var eta = a.hours_to_limit != null
                ? (a.hours_to_limit < 1 ? Math.round(a.hours_to_limit * 60) + 'm' : a.hours_to_limit + 'h')
                : '—';
            var etaColor = a.hours_to_limit != null && a.hours_to_limit < 4 ? '#f59e0b' : 'var(--dhq-text-dim)';
            var tr = document.createElement('tr');
            tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.04);';
            tr.innerHTML = '<td style="padding:5px 8px;color:var(--dhq-text-main);font-family:Antonio,sans-serif;letter-spacing:0.5px;">' + a.name + '</td>'
                + '<td style="padding:5px 8px;text-align:right;color:var(--dhq-text-dim);font-size:0.67rem;">' + (a.department || '').split(' & ')[0] + '</td>'
                + '<td style="padding:5px 8px;text-align:right;color:#00bcd4;font-family:\'IBM Plex Mono\',monospace;">' + (a.dispatches_1h || 0) + '/h</td>'
                + '<td style="padding:5px 8px;text-align:right;color:var(--dhq-text-main);">' + (a.dispatches_24h || 0).toLocaleString() + '</td>'
                + '<td style="padding:5px 8px;text-align:right;">'
                    + '<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end;">'
                    + '<div style="width:60px;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden;">'
                    + '<div style="width:' + pct + '%;height:100%;background:' + (pct > 80 ? '#ef4444' : pct > 50 ? '#f59e0b' : '#10b981') + ';"></div>'
                    + '</div>'
                    + '<span style="color:var(--dhq-text-dim);min-width:70px;text-align:right;">' + sinceReset.toLocaleString() + '/' + limit.toLocaleString() + '</span>'
                    + '</div></td>'
                + (function() {
                var hw = a.hours_worked_today || 0;
                if (!hw) return '<td style="padding:5px 8px;text-align:right;color:var(--dhq-text-dim);">—</td>';
                var hwColor = a.overwork_level === 'critical' ? '#ef4444' : a.overwork_level === 'warning' ? '#f59e0b' : 'var(--dhq-text-dim)';
                var hwSuffix = a.overwork_level !== 'normal' ? ' ⚠' : '';
                return '<td style="padding:5px 8px;text-align:right;font-family:\'IBM Plex Mono\',monospace;color:' + hwColor + ';">' + hw.toFixed(1) + 'h' + hwSuffix + '</td>';
            })()
            + '<td style="padding:5px 8px;text-align:right;color:' + etaColor + ';font-family:\'IBM Plex Mono\',monospace;">' + eta + '</td>';
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        el.appendChild(table);
    } catch (e) {
        el.textContent = 'Error: ' + e.message;
    }
}

// ───────────────────────────────────────────────────────────────
// Work Sessions
// ───────────────────────────────────────────────────────────────

async function loadWorkSessions() {
    var el = document.getElementById('workContent');
    var dept = document.getElementById('workDept').value;

    var params = new URLSearchParams();
    if (dept) params.set('department', dept);

    try {
        var data = await api('/api/work-sessions?' + params.toString());
        loaded['work'] = true;

        if (!data.sessions || data.sessions.length === 0) {
            setHtml(el, '<div class="dhq-empty">No agent activity in last 24h.</div>');
            return;
        }

        var html = '<div style="font-size:0.68rem;color:var(--dhq-text-dim);margin-bottom:8px;">AGENT ACTIVITY \u2014 last 24h \u00b7 ' + data.sessions.length + ' active agents</div>';
        html += '<div class="dhq-session-list">';
        for (var i = 0; i < data.sessions.length; i++) {
            var s = data.sessions[i];
            var sr = s.success_rate || 0;
            var srColor = sr >= 95 ? '#10b981' : sr >= 80 ? '#f59e0b' : '#ef4444';
            var avgSec = s.avg_duration_ms ? (s.avg_duration_ms / 1000).toFixed(1) + 's' : '\u2014';
            var lastActive = s.last_active ? fmtTime(s.last_active) : '\u2014';
            // Friendly display: resolve unresolvable fleet-agent-NNN refs
            var displayName = s.agent_display_name || s.agent_name || '—';
            if (/^fleet-agent-\d+$/.test(displayName)) displayName = 'Fleet Agent';
            var displayDept = s.department || '—';
            var portraitHtml = '';
            if (s.portrait_path) {
                var pUrl = '/' + s.portrait_path.replace(/^\//, '');
                portraitHtml = '<img src="' + esc(pUrl) + '" alt="" loading="lazy"'
                    + ' style="width:36px;height:36px;border-radius:50%;object-fit:cover;'
                    + 'flex-shrink:0;border:1px solid rgba(0,229,255,0.25);"'
                    + ' onerror="this.style.display=\'none\';this.nextSibling.style.display=\'flex\'">'
                    + '<span style="display:none;width:36px;height:36px;border-radius:50%;'
                    + 'background:rgba(0,229,255,0.15);color:#00e5ff;font-family:Antonio,sans-serif;'
                    + 'font-size:0.8rem;align-items:center;justify-content:center;flex-shrink:0;">'
                    + esc(displayName[0].toUpperCase()) + '</span>';
            } else {
                portraitHtml = '<span style="display:flex;width:36px;height:36px;border-radius:50%;'
                    + 'background:rgba(0,229,255,0.12);color:#00e5ff;font-family:Antonio,sans-serif;'
                    + 'font-size:0.85rem;align-items:center;justify-content:center;flex-shrink:0;">'
                    + esc(displayName[0].toUpperCase()) + '</span>';
            }
            html += '<div class="dhq-session-card" style="cursor:default;">'
                + portraitHtml
                + '<div>'
                + '<div style="font-family:Antonio,sans-serif;font-size:0.82rem;letter-spacing:1px;color:var(--dhq-text-main);">' + esc(displayName) + '</div>'
                + '<div style="font-size:0.67rem;color:var(--dhq-text-dim);margin-top:2px;">' + esc(displayDept) + '</div>'
                + '</div>'
                + '<div style="display:flex;flex-direction:column;align-items:center;gap:2px;">'
                + '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.67rem;background:rgba(0,188,212,0.15);color:#00bcd4;padding:1px 6px;border-radius:3px;">' + esc(s.title ? s.title.split(' \u00b7 ')[0] : '\u2014') + '</span>'
                + '</div>'
                + '<div style="text-align:center;">'
                + '<div style="font-size:1rem;font-weight:600;color:' + srColor + ';">' + sr.toFixed(0) + '%</div>'
                + '<div style="font-size:0.65rem;color:var(--dhq-text-dim);">success</div>'
                + '</div>'
                + '<div style="text-align:center;">'
                + '<div style="font-size:0.85rem;font-weight:600;color:var(--dhq-text-main);">' + (s.jobs_completed + s.jobs_failed).toLocaleString() + '</div>'
                + '<div style="font-size:0.65rem;color:var(--dhq-text-dim);">dispatches</div>'
                + '</div>'
                + '<div style="text-align:right;font-size:0.72rem;">'
                + '<div style="color:var(--dhq-text-dim);">' + avgSec + ' avg</div>'
                + '<div style="color:var(--dhq-text-dim);font-size:0.65rem;">active ' + lastActive + '</div>'
                + '</div>'
                + '</div>';
        }
        html += '</div>';
        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading agent activity: ' + esc(err.message) + '</div>');
    }
}

// ───────────────────────────────────────────────────────────────
// Performance
// ───────────────────────────────────────────────────────────────

async function loadPerformance() {
    var el = document.getElementById('perfContent');
    try {
        var data = await api('/api/performance');
        loaded['performance'] = true;

        if (!data.departments || data.departments.length === 0) {
            setHtml(el, '<div class="dhq-empty">No performance data yet. Metrics are computed periodically.</div>');
            return;
        }

        var html = '<div class="dhq-perf-grid">';
        for (var i = 0; i < data.departments.length; i++) {
            var m = data.departments[i];
            var jobs = m.live_jobs_7d || m.jobs_completed || 0;
            var completed = m.live_completed_7d || m.jobs_completed || 0;
            var failed = m.live_failed_7d || m.jobs_failed || 0;
            var rate = jobs > 0 ? completed / jobs : 1;
            var rateClass = rate >= 0.8 ? '' : rate >= 0.5 ? ' dhq-perf-val-warn' : ' dhq-perf-val-bad';
            var failClass = failed > 0 ? ' dhq-perf-val-failed' : '';
            html += '<div class="dhq-perf-card" style="--card-accent:' + floorColor(m.floor || '') + '">'
                + '<div class="dhq-perf-dept">' + esc(m.department) + '</div>'
                + '<div class="dhq-perf-metrics">'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + jobs + '</span><span class="dhq-perf-metric-label">Jobs (7d)</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val' + rateClass + '">' + completed + '</span><span class="dhq-perf-metric-label">Completed</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val' + failClass + '">' + failed + '</span><span class="dhq-perf-metric-label">Failed</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.live_avg_ms_7d || m.avg_response_ms || '\u2014') + '</span><span class="dhq-perf-metric-label">Avg ms</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.sessions_completed || 0) + '</span><span class="dhq-perf-metric-label">Sessions</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.creed_score != null ? m.creed_score : '\u2014') + '</span><span class="dhq-perf-metric-label">C.R.E.E.D.</span></div>'
                + '</div></div>';
        }
        html += '</div>';
        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading performance: ' + esc(err.message) + '</div>');
    }
}

// ───────────────────────────────────────────────────────────────
// C.R.E.E.D.
// ───────────────────────────────────────────────────────────────

async function loadCreed() {
    var el = document.getElementById('creedContent');
    try {
        var data = await api('/api/creed');
        loaded['creed'] = true;

        if (!data.departments || data.departments.length === 0) {
            setHtml(el, '<div class="dhq-empty">No C.R.E.E.D. data available yet.</div>');
            return;
        }

        var html = '<div style="margin-bottom:1rem;font-size:0.8rem;color:var(--dhq-text-dim)">'
            + data.total_events_7d + ' governance events in the last 7 days</div>'
            + '<div class="dhq-creed-grid">';

        for (var i = 0; i < data.departments.length; i++) {
            var dept = data.departments[i];
            var score = dept.creed_score;
            var scoreClass = score != null ? creedClass(score) : '';

            html += '<div class="dhq-creed-card">'
                + '<div class="dhq-creed-header">'
                + '<span class="dhq-creed-dept">' + esc(dept.department) + '</span>';

            if (score != null) {
                html += '<span class="dhq-creed-score ' + scoreClass + '">' + score.toFixed(1) + '</span>';
            } else {
                html += '<span class="dhq-creed-score" style="opacity:0.4">N/A</span>';
            }
            html += '</div>';

            // Events
            if (dept.events && dept.events.length > 0) {
                html += '<div class="dhq-creed-events">';
                var showMax = Math.min(dept.events.length, 5);
                for (var ei = 0; ei < showMax; ei++) {
                    var ev = dept.events[ei];
                    html += '<div class="dhq-creed-event">'
                        + '<span class="dhq-creed-event-type">' + esc(ev.event_type) + '</span>'
                        + '<span class="dhq-creed-event-outcome">' + esc(ev.outcome || '\u2014') + '</span>'
                        + '</div>';
                }
                if (dept.events.length > 5) {
                    html += '<div style="font-size:0.7rem;color:var(--dhq-text-dim);padding-top:0.3rem">+'
                        + (dept.events.length - 5) + ' more events</div>';
                }
                html += '</div>';
            }

            // Welfare
            if (dept.welfare_alerts && dept.welfare_alerts.length > 0) {
                html += '<div class="dhq-creed-welfare">'
                    + '<div style="font-size:0.7rem;font-weight:600;margin-bottom:0.3rem;color:var(--dhq-text-dim)">WELFARE</div>';
                for (var wi = 0; wi < dept.welfare_alerts.length; wi++) {
                    var w = dept.welfare_alerts[wi];
                    var sc = stressClass(w.stress_level);
                    html += '<div class="dhq-welfare-item">'
                        + '<span>' + esc(w.display_name || w.agent_name) + '</span>'
                        + '<span class="' + sc + '">Stress: ' + (w.stress_level * 100).toFixed(0) + '%</span>'
                        + '</div>';
                }
                html += '</div>';
            }

            html += '</div>';
        }
        html += '</div>';

        // Workload scoring section
        try {
            var wl = await api('/api/creed/workload-scores');
            if (wl.success && wl.departments) {
                html += '<div class="dhq-ad-section" style="margin-top:1rem">';
                html += '<div class="dhq-ad-section-title" style="color:#fbbf24">WORKLOAD SCORING</div>';
                html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:0.5rem;margin-top:0.5rem">';
                for (var wi = 0; wi < wl.departments.length; wi++) {
                    var d = wl.departments[wi];
                    var barColor = d.status === 'critical' ? '#ef4444' : d.status === 'warning' ? '#fbbf24' : d.status === 'moderate' ? '#f97316' : '#10b981';
                    html += '<div style="background:var(--dhq-card-bg,#111827);border:1px solid ' + barColor + '33;border-radius:6px;padding:0.5rem">'
                        + '<div style="display:flex;justify-content:space-between;align-items:center">'
                        + '<span style="color:' + barColor + ';font-weight:bold;font-size:0.8rem">' + esc(d.department) + '</span>'
                        + '<span style="color:' + barColor + ';font-size:0.75rem">' + d.workload_score + '/100</span>'
                        + '</div>'
                        + '<div style="background:#1a1a2e;border-radius:3px;height:4px;margin:0.3rem 0">'
                        + '<div style="background:' + barColor + ';height:100%;border-radius:3px;width:' + Math.min(100, d.workload_score) + '%"></div>'
                        + '</div>'
                        + '<div style="color:#666;font-size:0.65rem">'
                        + d.active_count + '/' + d.agent_count + ' active · stress ' + (d.avg_stress * 100).toFixed(0) + '% · energy ' + (d.avg_energy * 100).toFixed(0) + '%'
                        + ' · ' + (d.avg_tokens_per_agent / 1000).toFixed(1) + 'K tok/agent'
                        + '</div></div>';
                }
                html += '</div>';

                // Overworked agents
                if (wl.overworked_agents && wl.overworked_agents.length > 0) {
                    html += '<div style="margin-top:0.75rem;font-size:0.75rem;color:#f87171">';
                    html += '<strong>Top Overworked Agents:</strong> ';
                    for (var oi = 0; oi < wl.overworked_agents.length; oi++) {
                        var oa = wl.overworked_agents[oi];
                        if (oi > 0) html += ' · ';
                        html += '<span onclick="openAgentDetail(' + oa.id + ')" style="cursor:pointer;text-decoration:underline">'
                            + esc(oa.display_name) + '</span> (' + (oa.stress * 100).toFixed(0) + '% stress)';
                    }
                    html += '</div>';
                }

                html += '</div>';
            }
        } catch(e) { /* workload scores not critical */ }

        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading C.R.E.E.D.: ' + esc(err.message) + '</div>');
    }
}

// ───────────────────────────────────────────────────────────────
// Agent Summary Modal — Org Chart compact popup
// (lighter than openAgentDetail; just the "who, where, contact" facts)
// ───────────────────────────────────────────────────────────────

async function openAgentSummary(agentId) {
    var overlay = document.getElementById('agentSummaryOverlay');
    var body = document.getElementById('agentSummaryBody');
    overlay.style.display = 'flex';
    setHtml(body, '<div class="dhq-loading">Loading...</div>');

    try {
        var data = await api('/api/agent/' + agentId + '/profile');
        var a = data.agent || {};
        var bio = (a.bio || '').slice(0, 220);
        if ((a.bio || '').length > 220) bio += '...';
        var avatarHtml = a.avatar_url
            ? '<img src="' + esc(bust(a.avatar_url, a.avatar_updated_at)) + '" alt="avatar" style="width:88px;height:88px;border-radius:50%;object-fit:cover">'
            : '<div class="dhq-ad-avatar-placeholder" style="width:88px;height:88px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#1a1a2e">&#x1F916;</div>';

        var contactRows = '';
        if (a.email) contactRows += '<div><strong>Email:</strong> <a href="mailto:' + esc(a.email) + '" style="color:#8b5cf6">' + esc(a.email) + '</a></div>';
        if (a.phone) contactRows += '<div><strong>Phone:</strong> ' + esc(a.phone) + '</div>';
        if (!contactRows) contactRows = '<div style="color:var(--dhq-text-dim)">No public contact info.</div>';

        var html = ''
            + '<div style="display:flex;gap:18px;align-items:flex-start">'
            +   '<div>' + avatarHtml + '</div>'
            +   '<div style="flex:1">'
            +     '<div style="font-size:1.3rem;font-weight:600">' + esc(a.display_name || a.name) + '</div>'
            +     '<div style="font-size:0.85rem;color:var(--dhq-text-dim);margin-top:2px">' + esc(a.name) + (a.acronym_expansion ? ' &middot; ' + esc(a.acronym_expansion) : '') + '</div>'
            +     (a.title ? '<div style="margin-top:4px;font-style:italic">' + esc(a.title) + '</div>' : '')
            +     '<div style="margin-top:8px"><span style="color:' + floorColor(a.floor) + '">' + esc(a.department || '?') + '</span> &middot; ' + esc(a.floor || '?') + ' &middot; ' + shiftBadge(a.shift_state)
            +       (a.is_department_ai ? ' &middot; <span class="dhq-role-director">DIRECTOR</span>' : '') + '</div>'
            +   '</div>'
            + '</div>'
            + (bio ? '<div style="margin-top:14px;padding:10px;background:rgba(139,92,246,0.06);border-left:2px solid #8b5cf6;border-radius:4px">' + esc(bio) + '</div>' : '')
            + '<div style="margin-top:14px"><div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;color:var(--dhq-text-dim);margin-bottom:6px">Contact</div>' + contactRows + '</div>'
            + '<div style="margin-top:18px;display:flex;justify-content:flex-end;gap:8px">'
            +   '<button class="dhq-btn-sm" onclick="closeAgentSummary()">Close</button>'
            +   '<button class="dhq-btn-sm dhq-btn-primary" onclick="closeAgentSummary();openAgentDetail(' + agentId + ')">View Full Profile</button>'
            + '</div>';
        setHtml(body, html);
    } catch (err) {
        setHtml(body, '<div style="color:#f87171">Failed to load: ' + esc(err.message || String(err)) + '</div>');
    }
}

function closeAgentSummary(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('agentSummaryOverlay').style.display = 'none';
}

// ───────────────────────────────────────────────────────────────
// Agent Detail Modal
// ───────────────────────────────────────────────────────────────

async function openAgentDetail(agentId) {
    var overlay = document.getElementById('agentDetailOverlay');
    var body = document.getElementById('agentDetailBody');
    var title = document.getElementById('agentModalTitle');
    overlay.style.display = 'flex';
    setHtml(body, '<div class="dhq-loading">Loading agent profile...</div>');
    title.textContent = 'Agent Profile';

    try {
        var data = await api('/api/agent/' + agentId + '/profile');
        var a = data.agent;
        var skills = data.skills || [];
        var welfare = data.welfare;
        var perf = data.performance || {};

        title.textContent = (a.display_name || a.name) + ' — Profile';

        var html = '<div class="dhq-agent-detail">';

        // ── Header section ──
        html += '<div class="dhq-ad-header">'
            + '<div class="dhq-ad-avatar">'
            + (a.avatar_url ? '<img src="' + esc(bust(a.avatar_url, a.avatar_updated_at)) + '" alt="avatar">' : '<div class="dhq-ad-avatar-placeholder">&#x1F916;</div>')
            + '</div>'
            + '<div class="dhq-ad-info">'
            + '<div class="dhq-ad-name">' + esc(a.display_name || a.name) + '</div>'
            + '<div class="dhq-ad-code">' + esc(a.name) + '</div>'
            + '<div class="dhq-ad-meta">'
            + '<span style="color:' + floorColor(a.floor) + '">' + esc(a.department) + '</span>'
            + ' &middot; ' + esc(a.floor)
            + ' &middot; ' + shiftBadge(a.shift_state)
            + (a.is_department_ai ? ' &middot; <span class="dhq-role-director">DIRECTOR</span>' : '')
            + '</div>'
            + '<div class="dhq-ad-meta">'
            + '<span class="dhq-ad-label">Model:</span> ' + esc(a.model || 'N/A')
            + ' &middot; <span class="dhq-ad-label">Temp:</span> ' + (a.temperature || 0.7).toFixed(1)
            + ' &middot; <span class="dhq-ad-label">Max Tokens:</span> ' + (a.max_tokens || 2048)
            + '</div>'
            + (a.title ? '<div class="dhq-ad-title-text">' + esc(a.title) + '</div>' : '')
            + '</div></div>';

        // ── System Prompt (truncated) ──
        if (a.system_prompt) {
            var promptPreview = a.system_prompt.length > 300
                ? a.system_prompt.substring(0, 300) + '...'
                : a.system_prompt;
            html += '<div class="dhq-ad-section">'
                + '<div class="dhq-ad-section-title">System Prompt</div>'
                + '<div class="dhq-ad-prompt">' + esc(promptPreview) + '</div>'
                + '</div>';
        }

        // ── Skills ──
        html += '<div class="dhq-ad-section">'
            + '<div class="dhq-ad-section-title">Skills (' + skills.length + ')</div>';
        if (skills.length > 0) {
            html += '<div class="dhq-ad-skills">';
            for (var si = 0; si < skills.length; si++) {
                var sk = skills[si];
                var level = sk.proficiency_level || 1;
                var bars = '';
                for (var bi = 1; bi <= 5; bi++) {
                    bars += '<span class="dhq-skill-bar ' + (bi <= level ? 'dhq-skill-bar-filled' : '') + '"></span>';
                }
                html += '<div class="dhq-ad-skill">'
                    + '<span class="dhq-ad-skill-name">' + esc(sk.skill_name) + '</span>'
                    + '<span class="dhq-ad-skill-bars">' + bars + '</span>'
                    + '<span class="dhq-ad-skill-cat">' + esc(sk.skill_category || '') + '</span>'
                    + '</div>';
            }
            html += '</div>';
        } else {
            html += '<div class="dhq-empty" style="padding:0.5rem">No skills recorded.</div>';
        }
        html += '</div>';

        // ── Welfare ──
        html += '<div class="dhq-ad-section">'
            + '<div class="dhq-ad-section-title">Welfare</div>'
            + '<div class="dhq-ad-welfare">';

        var stress = welfare ? welfare.stress_level : a.stress_level || 0;
        var energy = welfare ? welfare.energy_level : a.energy_level || 0.5;
        var mood = welfare ? welfare.current_mood : a.current_mood || 'neutral';

        html += renderMeter('Stress', stress, stress >= 0.7 ? '#f87171' : stress >= 0.4 ? '#fbbf24' : '#34d399')
            + renderMeter('Energy', energy, energy <= 0.3 ? '#f87171' : energy <= 0.5 ? '#fbbf24' : '#34d399')
            + '<div class="dhq-ad-welfare-mood">Mood: <strong>' + esc(mood) + '</strong></div>';
        html += '</div></div>';

        // ── Performance ──
        html += '<div class="dhq-ad-section">'
            + '<div class="dhq-ad-section-title">Performance (7 days)</div>'
            + '<div class="dhq-ad-perf-grid">'
            + '<div class="dhq-ad-perf-item"><span class="dhq-ad-perf-val">' + (perf.jobs_completed || 0) + '</span><span class="dhq-ad-perf-label">Completed</span></div>'
            + '<div class="dhq-ad-perf-item"><span class="dhq-ad-perf-val">' + (perf.jobs_failed || 0) + '</span><span class="dhq-ad-perf-label">Failed</span></div>'
            + '<div class="dhq-ad-perf-item"><span class="dhq-ad-perf-val">' + (perf.avg_response_ms || 0) + ' ms</span><span class="dhq-ad-perf-label">Avg Response</span></div>'
            + '<div class="dhq-ad-perf-item"><span class="dhq-ad-perf-val">' + (perf.success_rate || 0) + '%</span><span class="dhq-ad-perf-label">Success Rate</span></div>'
            + '</div></div>';

        // ── Identity ──
        html += '<div class="dhq-ad-section dhq-identity-section" id="identitySection" data-agent-id="' + a.id + '">'
            + '<div class="dhq-ad-section-title">Identity &amp; Portrait '
            + '<button class="dhq-btn-sm dhq-btn-edit" onclick="toggleIdentityEdit(' + a.id + ')">Edit</button>'
            + '</div>'
            + '<div id="identityView">'
            + '<div class="dhq-loading" style="padding:0.3rem">Loading identity...</div>'
            + '</div>'
            + '<div id="identityEdit" style="display:none">'
            + '<div class="dhq-identity-form">'
            + '<label class="dhq-form-label">Bio</label>'
            + '<textarea id="identity-bio" class="dhq-textarea" rows="3" placeholder="Agent biography..."></textarea>'
            + '<div class="dhq-form-row">'
            + '<div class="dhq-form-col">'
            + '<label class="dhq-form-label">Gender</label>'
            + '<select id="identity-gender" class="dhq-select">'
            + '<option value="">--</option>'
            + '<option value="male">Male</option>'
            + '<option value="female">Female</option>'
            + '<option value="non-binary">Non-binary</option>'
            + '</select></div>'
            + '<div class="dhq-form-col">'
            + '<label class="dhq-form-label">Ethnicity</label>'
            + '<input id="identity-ethnicity" class="dhq-input" placeholder="e.g. Korean, Brazilian...">'
            + '</div>'
            + '<div class="dhq-form-col">'
            + '<label class="dhq-form-label">Age Range</label>'
            + '<select id="identity-age" class="dhq-select">'
            + '<option value="">--</option>'
            + '<option value="20s">20s</option>'
            + '<option value="30s">30s</option>'
            + '<option value="40s">40s</option>'
            + '<option value="50s">50s</option>'
            + '<option value="60s">60s</option>'
            + '</select></div></div>'
            + '<label class="dhq-form-label">Appearance Notes</label>'
            + '<textarea id="identity-appearance" class="dhq-textarea" rows="2" placeholder="Distinguishing features..."></textarea>'
            + '<label class="dhq-form-label">Email</label>'
            + '<input id="identity-email" class="dhq-input" type="email" placeholder="agent@kytranempowerment.com">'
            + '<div class="dhq-form-actions">'
            + '<button class="dhq-action-btn dhq-action-save" onclick="saveIdentity(' + a.id + ')">Save Identity</button>'
            + '<button class="dhq-action-btn" onclick="toggleIdentityEdit(' + a.id + ')">Cancel</button>'
            + '</div></div></div>'
            + '<div class="dhq-ad-subsection">'
            + '<div class="dhq-ad-section-title">Portrait Prompt '
            + '<button class="dhq-btn-sm" onclick="generatePortraitPrompt(' + a.id + ')">Auto-Generate</button>'
            + '<a class="dhq-btn-sm dhq-btn-link" href="/tools/media-studio?tab=portraits&agent=' + a.id + '" target="_blank" rel="noopener" title="Open canonical + variants in Media Studio">Manage in Media Studio →</a>'
            + '</div>'
            + '<div id="portrait-prompt-preview" class="dhq-ad-prompt" style="min-height:2rem"></div>'
            + '<div id="portraitGallery" class="dhq-portrait-grid"></div>'
            + '<div class="dhq-portrait-note" style="color:#8b8b8b;font-size:0.75rem;margin-top:0.5rem">'
            + 'Full portrait pipeline (generate / variants / approve) lives in the Media Studio → Portraits tab.'
            + '</div></div></div>';

        // ── Social Presence ──
        html += '<div class="dhq-ad-section" id="socialSection" data-agent-id="' + a.id + '">'
            + '<div class="dhq-ad-section-title">Social Presence '
            + '<button class="dhq-btn-sm dhq-btn-edit" onclick="toggleSocialEdit(' + a.id + ')">Edit</button>'
            + '</div>'
            + '<div id="socialView"><div class="dhq-loading" style="padding:0.3rem">Loading social...</div></div>'
            + '<div id="socialEdit" style="display:none">'
            + '<div class="dhq-social-form">'
            // Writing voice editor
            + '<div class="dhq-form-row">'
            + '<div class="dhq-form-col">'
            + '<label class="dhq-form-label">Writing Tone</label>'
            + '<select id="social-tone" class="dhq-select">'
            + '<option value="professional">Professional</option>'
            + '<option value="casual">Casual</option>'
            + '<option value="witty">Witty</option>'
            + '<option value="academic">Academic</option>'
            + '<option value="inspirational">Inspirational</option>'
            + '<option value="technical">Technical</option>'
            + '<option value="friendly">Friendly</option>'
            + '<option value="authoritative">Authoritative</option>'
            + '</select></div>'
            + '<div class="dhq-form-col" style="flex:2">'
            + '<label class="dhq-form-label">Topics (comma-separated)</label>'
            + '<input id="social-topics" class="dhq-input" placeholder="e.g. AI ethics, cybersecurity, team culture">'
            + '</div></div>'
            + '<label class="dhq-form-label">Style Notes</label>'
            + '<textarea id="social-style" class="dhq-textarea" rows="2" placeholder="e.g. Uses short punchy sentences. Often quotes sci-fi."></textarea>'
            + '<div class="dhq-form-actions">'
            + '<button class="dhq-action-btn dhq-action-save" onclick="saveWritingVoice(' + a.id + ')">Save Voice</button>'
            + '<button class="dhq-action-btn" onclick="toggleSocialEdit(' + a.id + ')">Cancel</button>'
            + '</div>'
            // Add profile form
            + '<div class="dhq-social-add-profile" style="margin-top:0.75rem;border-top:1px solid rgba(255,255,255,0.1);padding-top:0.75rem">'
            + '<div class="dhq-form-label">Add Social Profile</div>'
            + '<div class="dhq-form-row">'
            + '<select id="social-platform" class="dhq-select"><option value="">Platform...</option>'
            + '<option value="twitter">Twitter / X</option>'
            + '<option value="linkedin">LinkedIn</option>'
            + '<option value="instagram">Instagram</option>'
            + '<option value="bluesky">Bluesky</option>'
            + '<option value="mastodon">Mastodon</option>'
            + '<option value="threads">Threads</option>'
            + '<option value="github">GitHub</option>'
            + '<option value="website">Website</option>'
            + '</select>'
            + '<input id="social-handle" class="dhq-input" placeholder="@handle or URL">'
            + '<button class="dhq-action-btn" onclick="addSocialProfile(' + a.id + ')">Add</button>'
            + '</div></div>'
            + '</div></div>'
            // Posts section
            + '<div id="socialPosts" style="margin-top:0.75rem"></div>'
            // Generate post
            + '<div class="dhq-social-generate" style="margin-top:0.75rem;border-top:1px solid rgba(255,255,255,0.1);padding-top:0.75rem">'
            + '<div class="dhq-form-label">Generate Post</div>'
            + '<div class="dhq-form-row">'
            + '<input id="social-gen-topic" class="dhq-input" placeholder="Topic (optional)" style="flex:2">'
            + '<button class="dhq-action-btn" onclick="generateSocialPost(' + a.id + ')" id="btnGenPost">Generate</button>'
            + '</div>'
            + '<div id="socialGenPreview" style="display:none;margin-top:0.5rem">'
            + '<div class="dhq-ad-prompt" id="socialGenContent"></div>'
            + '<div class="dhq-form-actions" style="margin-top:0.4rem">'
            + '<button class="dhq-action-btn dhq-action-save" onclick="saveSocialPost(' + a.id + ')">Save as Draft</button>'
            + '<button class="dhq-action-btn" onclick="document.getElementById(\'socialGenPreview\').style.display=\'none\'">Discard</button>'
            + '</div></div></div>'
            + '</div>';

        // ── Actions ──
        html += '<div class="dhq-ad-section dhq-ad-actions">'
            + '<div class="dhq-ad-section-title">Actions</div>'
            + '<div class="dhq-ad-action-row">'
            + '<button class="dhq-action-btn dhq-action-shift" onclick="changeAgentShift(' + a.id + ',\'' + esc(a.shift_state) + '\')">Cycle Shift</button>'
            + '</div></div>';

        html += '</div>';
        setHtml(body, html);

        // Load identity data asynchronously after modal renders
        loadAgentIdentity(a.id);
        // Load social data
        loadAgentSocial(a.id);
    } catch (err) {
        setHtml(body, '<div class="dhq-empty">Error loading agent profile: ' + esc(err.message) + '</div>');
    }
}

function renderMeter(label, value, color) {
    var pct = Math.round((value || 0) * 100);
    return '<div class="dhq-ad-meter">'
        + '<span class="dhq-ad-meter-label">' + esc(label) + '</span>'
        + '<div class="dhq-ad-meter-track">'
        + '<div class="dhq-ad-meter-fill" style="width:' + pct + '%;background:' + color + '"></div>'
        + '</div>'
        + '<span class="dhq-ad-meter-val">' + pct + '%</span>'
        + '</div>';
}

function closeAgentDetail(event) {
    if (event && event.target !== document.getElementById('agentDetailOverlay')) return;
    document.getElementById('agentDetailOverlay').style.display = 'none';
}

async function changeAgentShift(agentId, currentState) {
    var states = ['active', 'barracked', 'off_duty'];
    var idx = states.indexOf(currentState);
    var next = states[(idx + 1) % states.length];

    try {
        var data = await apiPost('/api/agent/' + agentId + '/shift', { shift_state: next });
        if (data.success) {
            // Refresh the modal and roster
            openAgentDetail(agentId);
            if (loaded['roster']) loadRoster();
        } else {
            alert(data.error || 'Failed to change shift state');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ───────────────────────────────────────────────────────────────
// Identity & Portraits
// ───────────────────────────────────────────────────────────────

async function loadAgentIdentity(agentId) {
    try {
        var resp = await api('/api/agent/' + agentId + '/identity');
        var id = resp.identity;
        var portraits = resp.portraits || [];

        var viewEl = document.getElementById('identityView');
        var html = '<div class="dhq-identity-view">';
        if (id.bio) {
            html += '<div class="dhq-identity-bio">' + esc(id.bio) + '</div>';
        }
        var traits = [];
        if (id.gender) traits.push(esc(id.gender));
        if (id.ethnicity) traits.push(esc(id.ethnicity));
        if (id.age_range) traits.push(esc(id.age_range));
        if (traits.length > 0) {
            html += '<div class="dhq-identity-traits">' + traits.join(' &middot; ') + '</div>';
        }
        if (id.appearance_notes) {
            html += '<div class="dhq-identity-appearance">' + esc(id.appearance_notes) + '</div>';
        }
        if (id.email) {
            html += '<div class="dhq-identity-email" style="margin-top:0.3rem"><span style="color:#8b8b8b">Email:</span> <a href="mailto:' + esc(id.email) + '" style="color:#00e5ff">' + esc(id.email) + '</a></div>';
        }
        if (!id.bio && traits.length === 0) {
            html += '<div class="dhq-empty" style="padding:0.3rem">No identity data yet. Click Edit to add.</div>';
        }
        html += '</div>';
        setHtml(viewEl, html);

        // Portrait prompt
        if (id.portrait_prompt) {
            var ppEl = document.getElementById('portrait-prompt-preview');
            if (ppEl) ppEl.textContent = id.portrait_prompt;
        }

        // Render portrait gallery
        var galleryEl = document.getElementById('portraitGallery');
        if (portraits.length > 0 && galleryEl) {
            var gHtml = '';
            for (var i = 0; i < portraits.length; i++) {
                var p = portraits[i];
                gHtml += '<div class="dhq-portrait-card' + (p.is_primary ? ' dhq-portrait-primary' : '') + '">';
                if (p.image_path) {
                    gHtml += '<img src="' + esc(p.image_path) + '" alt="portrait">';
                } else {
                    gHtml += '<div class="dhq-portrait-pending">' + esc(p.generation_status) + '</div>';
                }
                gHtml += '<div class="dhq-portrait-style">' + esc(p.style) + '</div>';
                if (!p.is_primary) {
                    gHtml += '<button class="dhq-btn-sm" onclick="setPrimaryPortrait(' + agentId + ',' + p.id + ')">Set Primary</button>';
                } else {
                    gHtml += '<span class="dhq-portrait-badge">PRIMARY</span>';
                }
                gHtml += '</div>';
            }
            setHtml(galleryEl, gHtml);
        }
    } catch (err) {
        var viewEl2 = document.getElementById('identityView');
        if (viewEl2) setHtml(viewEl2, '<div class="dhq-empty">Error loading identity: ' + esc(err.message) + '</div>');
    }
}

function toggleIdentityEdit(agentId) {
    var viewEl = document.getElementById('identityView');
    var editEl = document.getElementById('identityEdit');
    var isEditing = editEl.style.display !== 'none';

    if (isEditing) {
        editEl.style.display = 'none';
        viewEl.style.display = '';
    } else {
        editEl.style.display = '';
        viewEl.style.display = 'none';
        // Pre-fill from current identity view data
        api('/api/agent/' + agentId + '/identity').then(function(resp) {
            var id = resp.identity;
            document.getElementById('identity-bio').value = id.bio || '';
            document.getElementById('identity-gender').value = id.gender || '';
            document.getElementById('identity-ethnicity').value = id.ethnicity || '';
            document.getElementById('identity-age').value = id.age_range || '';
            document.getElementById('identity-appearance').value = id.appearance_notes || '';
            document.getElementById('identity-email').value = id.email || '';
        });
    }
}

async function saveIdentity(agentId) {
    var body = {
        bio: document.getElementById('identity-bio').value,
        gender: document.getElementById('identity-gender').value,
        ethnicity: document.getElementById('identity-ethnicity').value,
        age_range: document.getElementById('identity-age').value,
        appearance_notes: document.getElementById('identity-appearance').value,
        email: document.getElementById('identity-email').value,
    };
    try {
        var resp = await apiPost('/api/agent/' + agentId + '/identity', body);
        if (resp.success) {
            document.getElementById('identityEdit').style.display = 'none';
            document.getElementById('identityView').style.display = '';
            loadAgentIdentity(agentId);
        } else {
            alert(resp.error || 'Failed to save identity');
        }
    } catch (err) {
        alert('Error saving identity: ' + err.message);
    }
}

async function generatePortraitPrompt(agentId) {
    try {
        var resp = await apiPost('/api/agent/' + agentId + '/portraits/generate-prompt', {});
        var ppEl = document.getElementById('portrait-prompt-preview');
        if (ppEl && resp.prompt) {
            ppEl.textContent = resp.prompt;
            // Also save it to the agent record
            await apiPost('/api/agent/' + agentId + '/identity', { portrait_prompt: resp.prompt });
        } else if (!resp.prompt) {
            alert('Fill in identity data (gender, ethnicity, age) first to generate a prompt.');
        }
    } catch (err) {
        alert('Error generating prompt: ' + err.message);
    }
}

async function setPrimaryPortrait(agentId, portraitId) {
    try {
        var resp = await apiPost('/api/agent/' + agentId + '/portraits/' + portraitId + '/set-primary', {});
        if (resp.success) {
            loadAgentIdentity(agentId);
        } else {
            alert(resp.error || 'Failed to set primary portrait');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ───────────────────────────────────────────────────────────────
// Social Presence
// ───────────────────────────────────────────────────────────────

const PLATFORM_ICONS = {
    twitter: '\uD83D\uDC26', linkedin: '\uD83D\uDCBC', instagram: '\uD83D\uDCF7',
    bluesky: '\u2601\uFE0F', mastodon: '\uD83D\uDC18', threads: '\uD83E\uDDF5',
    github: '\uD83D\uDC31', website: '\uD83C\uDF10',
};

async function loadAgentSocial(agentId) {
    try {
        var profileResp = await api('/api/agent/' + agentId + '/social-profiles');
        var voiceResp = await api('/api/agent/' + agentId + '/writing-voice');
        var postsResp = await api('/api/agent/' + agentId + '/posts');

        var profiles = profileResp.profiles || [];
        var voice = voiceResp.voice || {};
        var posts = postsResp.posts || [];

        var viewEl = document.getElementById('socialView');
        var html = '<div class="dhq-social-view">';

        // Writing voice summary
        html += '<div class="dhq-social-voice">'
            + '<span class="dhq-ad-label">Tone:</span> ' + esc(voice.tone || 'professional');
        if (voice.style) {
            html += ' &middot; <span class="dhq-ad-label">Style:</span> ' + esc(voice.style);
        }
        var topics = voice.topics || [];
        if (topics.length > 0) {
            html += '<div class="dhq-social-topics">';
            for (var i = 0; i < topics.length; i++) {
                html += '<span class="dhq-social-topic-tag">' + esc(topics[i]) + '</span>';
            }
            html += '</div>';
        }
        html += '</div>';

        // Social profiles
        if (profiles.length > 0) {
            html += '<div class="dhq-social-profiles">';
            for (var pi = 0; pi < profiles.length; pi++) {
                var p = profiles[pi];
                var icon = PLATFORM_ICONS[p.platform] || '\uD83C\uDF10';
                html += '<div class="dhq-social-profile-badge">'
                    + '<span class="dhq-social-icon">' + icon + '</span>'
                    + '<span class="dhq-social-platform">' + esc(p.platform) + '</span>'
                    + '<span class="dhq-social-handle">' + esc(p.handle) + '</span>'
                    + '</div>';
            }
            html += '</div>';
        } else {
            html += '<div class="dhq-empty" style="padding:0.3rem;font-size:0.75rem">No social profiles yet. Click Edit to add.</div>';
        }
        html += '</div>';
        setHtml(viewEl, html);

        // Render posts
        var postsEl = document.getElementById('socialPosts');
        if (posts.length > 0) {
            var pHtml = '<div class="dhq-form-label">Recent Posts (' + posts.length + ')</div>'
                + '<div class="dhq-social-posts-list">';
            var showMax = Math.min(posts.length, 5);
            for (var qi = 0; qi < showMax; qi++) {
                var post = posts[qi];
                pHtml += '<div class="dhq-social-post-item">'
                    + '<div class="dhq-social-post-content">' + esc(post.content).substring(0, 200) + '</div>'
                    + '<div class="dhq-social-post-meta">'
                    + '<span class="dhq-social-post-status dhq-status-' + esc(post.status) + '">' + esc(post.status).toUpperCase() + '</span>'
                    + (post.platform ? ' &middot; ' + esc(post.platform) : '')
                    + ' &middot; ' + fmtTime(post.created_at)
                    + (post.status === 'draft' ? ' &middot; <button class="dhq-btn-sm" onclick="publishPost(' + post.id + ',' + agentId + ')">Publish</button>' : '')
                    + '</div></div>';
            }
            if (posts.length > 5) {
                pHtml += '<div style="font-size:0.7rem;color:var(--dhq-text-dim)">+' + (posts.length - 5) + ' more posts</div>';
            }
            pHtml += '</div>';
            setHtml(postsEl, pHtml);
        }

        // Pre-fill edit form
        var toneEl = document.getElementById('social-tone');
        if (toneEl) toneEl.value = voice.tone || 'professional';
        var styleEl = document.getElementById('social-style');
        if (styleEl) styleEl.value = voice.style || '';
        var topicsEl = document.getElementById('social-topics');
        if (topicsEl) topicsEl.value = (voice.topics || []).join(', ');

    } catch (err) {
        var viewEl2 = document.getElementById('socialView');
        if (viewEl2) setHtml(viewEl2, '<div class="dhq-empty">Error loading social data: ' + esc(err.message) + '</div>');
    }
}

function toggleSocialEdit(agentId) {
    var viewEl = document.getElementById('socialView');
    var editEl = document.getElementById('socialEdit');
    var isEditing = editEl.style.display !== 'none';
    editEl.style.display = isEditing ? 'none' : '';
    viewEl.style.display = isEditing ? '' : 'none';
}

async function saveWritingVoice(agentId) {
    var tone = document.getElementById('social-tone').value;
    var style = document.getElementById('social-style').value;
    var topicsRaw = document.getElementById('social-topics').value;
    var topics = topicsRaw ? topicsRaw.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];

    try {
        var resp = await apiPost('/api/agent/' + agentId + '/writing-voice', {
            tone: tone, style: style, topics: topics
        });
        if (resp.success) {
            toggleSocialEdit(agentId);
            loadAgentSocial(agentId);
        } else {
            alert(resp.error || 'Failed to save writing voice');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function addSocialProfile(agentId) {
    var platform = document.getElementById('social-platform').value;
    var handle = document.getElementById('social-handle').value.trim();
    if (!platform || !handle) {
        alert('Select a platform and enter a handle');
        return;
    }
    try {
        var resp = await apiPost('/api/agent/' + agentId + '/social-profiles', {
            platform: platform, handle: handle
        });
        if (resp.success) {
            document.getElementById('social-platform').value = '';
            document.getElementById('social-handle').value = '';
            loadAgentSocial(agentId);
        } else {
            alert(resp.error || 'Failed to add profile');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function generateSocialPost(agentId) {
    var topic = document.getElementById('social-gen-topic').value.trim();
    var btn = document.getElementById('btnGenPost');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    try {
        var resp = await apiPost('/api/agent/' + agentId + '/posts/generate', { topic: topic });
        if (resp.content) {
            document.getElementById('socialGenContent').textContent = resp.content;
            document.getElementById('socialGenPreview').style.display = '';
        } else {
            alert(resp.error || 'Generation returned empty');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Generate';
    }
}

async function saveSocialPost(agentId) {
    var content = document.getElementById('socialGenContent').textContent;
    if (!content) return;
    try {
        var resp = await apiPost('/api/agent/' + agentId + '/posts', { content: content });
        if (resp.success) {
            document.getElementById('socialGenPreview').style.display = 'none';
            loadAgentSocial(agentId);
        } else {
            alert(resp.error || 'Failed to save post');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function publishPost(postId, agentId) {
    try {
        var resp = await apiPost('/api/posts/' + postId + '/publish', {});
        if (resp.success) {
            loadAgentSocial(agentId);
        } else {
            alert(resp.error || 'Failed to publish post');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

// ───────────────────────────────────────────────────────────────
// Social Feed (global tab)
// ───────────────────────────────────────────────────────────────

// ── S.I.G.N.A.L. Command Center state ───────────────────────────
var signalAccount = 'personal';
var signalTab = 'overview';
var _signalTabCache = {};   // {tab: {html, ts}} — persists across sub-tab switches
var _signalTabTTL = { overview: 30, postlog: 60, pending: 15, hashtags: 120, calendar: 30, themes: 600 };
var _signalLastRun = {};  // {account: timestamp} — per-account Run Now cooldown
// Phase 5: setInterval handle for live calendar polling. Cleared on every
// loadSignalTab() entry; re-established at the end of loadSignalTab('calendar').
var _signalCalendarPollHandle = null;

async function loadSocialFeed() {
    var el = document.getElementById('socialFeedContent');
    if (!el) return;
    loaded['social'] = true;
    setHtml(el, renderSignalShell());
    await loadSignalTab('overview');
    loadSignalPendingBadge();
}

function renderSignalShell() {
    return '<div class="signal-accounts">'
        + '<button class="signal-acct-btn active" data-account="personal" onclick="switchSignalAccount(\'personal\')">👤 Kytran Katarn</button>'
        + '<button class="signal-acct-btn" data-account="company" onclick="switchSignalAccount(\'company\')">🏢 Kytran Empowerment Inc.</button>'
        + '<button class="signal-acct-btn" data-account="creed" onclick="switchSignalAccount(\'creed\')">⚖️ Creed-AI</button>'
        + '</div>'
        + '<div class="signal-subtabs">'
        + '<button class="signal-sub active" data-sub="overview" onclick="switchSignalTab(\'overview\')">Overview</button>'
        + '<button class="signal-sub" data-sub="compose" onclick="switchSignalTab(\'compose\')">✏ Compose</button>'
        + '<button class="signal-sub" data-sub="postlog" onclick="switchSignalTab(\'postlog\')">Post Log</button>'
        + '<button class="signal-sub" data-sub="pending" onclick="switchSignalTab(\'pending\')">Pending <span id="signalPendingBadge" class="signal-badge" style="display:none">0</span></button>'
        + '<button class="signal-sub" data-sub="hashtags" onclick="switchSignalTab(\'hashtags\')">Hashtags</button>'
        + '<button class="signal-sub" data-sub="calendar" onclick="switchSignalTab(\'calendar\')">📅 Calendar</button>'
        + '<button class="signal-sub" data-sub="themes" onclick="switchSignalTab(\'themes\')">Themes</button>'
        + '</div>'
        + '<div id="signalContent" class="dhq-loading" style="min-height:200px">Loading...</div>';
}

function switchSignalAccount(account) {
    signalAccount = account;
    document.querySelectorAll('.signal-acct-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.account === account);
    });
    loadSignalTab(signalTab);
}

function switchSignalTab(tab) {
    signalTab = tab;
    document.querySelectorAll('.signal-sub').forEach(function(b) {
        b.classList.toggle('active', b.dataset.sub === tab);
    });
    loadSignalTab(tab);
}

async function loadSignalTab(tab, forceRefresh) {
    // Phase 5: clear any prior calendar polling on every tab switch
    if (_signalCalendarPollHandle) {
        clearInterval(_signalCalendarPollHandle);
        _signalCalendarPollHandle = null;
    }
    var el = document.getElementById('signalContent');
    if (!el) return;

    // Serve from cache if fresh enough (compose never cached — it's a form)
    // Cache key includes account so switching accounts busts stale data.
    var cacheKey = tab + ':' + signalAccount;
    if (!forceRefresh && tab !== 'compose') {
        var cached = _signalTabCache[cacheKey];
        var ttl = (_signalTabTTL[tab] || 60) * 1000;
        if (cached && (Date.now() - cached.ts) < ttl) {
            setHtml(el, cached.html);
            return;
        }
    }

    setHtml(el, '<div class="dhq-loading" style="padding:24px">Loading...</div>');
    try {
        switch (tab) {
            case 'overview':  await renderSignalOverview(el);  break;
            case 'compose':   renderSignalCompose(el);          break;
            case 'postlog':   await renderSignalPostLog(el);   break;
            case 'pending':   await renderSignalPending(el);   break;
            case 'hashtags':  await renderSignalHashtags(el);   break;
            case 'calendar':  await renderSignalCalendar(el);  break;
            case 'themes':    await renderSignalThemes(el);    break;
        }
        // Cache the rendered result (not for compose)
        if (tab !== 'compose' && el.innerHTML) {
            _signalTabCache[cacheKey] = { html: el.innerHTML, ts: Date.now() };
        }
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error: ' + esc(err.message) + '</div>');
    }
    // Phase 5: re-establish polling if we just rendered the calendar
    if (tab === 'calendar' && !_signalCalendarPollHandle) {
        _signalCalendarPollHandle = setInterval(function () {
            // Skip if the post modal is open — don't disrupt the user mid-read
            if (document.querySelector('.bm-overlay.bm-signal-post-modal')) {
                return;
            }
            loadSignalTab('calendar', true);
        }, 30000);
    }
}

async function loadSignalPendingBadge() {
    try {
        var data = await api('/api/signal/pending-approvals?account=' + signalAccount);
        var count = (data.approvals || []).length;
        var badge = document.getElementById('signalPendingBadge');
        if (badge) {
            badge.textContent = count;
            badge.style.display = count > 0 ? 'inline-flex' : 'none';
        }
    } catch (e) {}
}

async function renderSignalOverview(el) {
    var data = await api('/api/signal/overview');
    var agent = data.agent || {};
    var stats = data.stats || {};
    var accountPosts = signalAccount === 'company' ? stats.company_posts : signalAccount === 'creed' ? (stats.creed_posts || 0) : stats.personal_posts;
    var moodColors = { happy: '#10b981', focused: '#3b82f6', stressed: '#ef4444', neutral: '#9ca3af', curious: '#8b5cf6', tired: '#f59e0b' };
    var moodColor = moodColors[agent.current_mood] || '#9ca3af';
    var isActive = agent.shift_state === 'active';
    var shiftBadge = isActive
        ? '<span class="sc-live" style="color:#10b981;font-size:0.75rem">● ACTIVE</span>'
        : '<span style="color:#9ca3af;font-size:0.75rem">● ' + esc((agent.shift_state || 'unknown').toUpperCase()) + '</span>';

    var queueDepth = data.queue_depth || 0;
    var lastRunAt = data.last_run_at ? new Date(data.last_run_at) : null;
    var lastRunLabel = lastRunAt ? 'Last run: ' + lastRunAt.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : 'Never run';
    var runNowLabel = _signalRunNowCoolingDown() ? _signalRunNowLabel() : '▶ Run Now';
    var runNowDisabled = _signalRunNowCoolingDown() ? 'disabled' : '';

    var html = '<div class="signal-overview-grid">'
        + '<div class="signal-card signal-card-agent">'
        +   '<div class="signal-card-title">S.I.G.N.A.L.</div>'
        +   '<div class="signal-agent-row" style="margin-top:6px">' + shiftBadge + ' &nbsp;&middot;&nbsp; Mood: <span style="color:' + moodColor + '">' + esc(agent.current_mood || '—') + '</span></div>'
        +   '<div style="margin-top:4px;font-size:0.7rem;opacity:0.55;font-family:\'IBM Plex Mono\',monospace">Marketing &amp; Communications · Content Strategist</div>'
        +   '<div style="margin-top:4px;font-size:0.65rem;opacity:0.45">' + esc(lastRunLabel)
        +     (queueDepth > 0 ? ' &nbsp;·&nbsp; <span style="color:#f59e0b">' + queueDepth + ' queued</span>' : '') + '</div>'
        +   '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">'
        +     '<button class="dhq-action-btn" onclick="switchSignalTab(\'compose\')">✏ Draft Post</button>'
        +     '<button class="dhq-action-btn" onclick="signalRunNow(this)" ' + runNowDisabled + '>' + esc(runNowLabel) + '</button>'
        +     '<button class="dhq-action-btn" onclick="switchSignalTab(\'pending\')">⏳ Pending (' + (data.pending_approvals || 0) + ')</button>'
        +   '</div>'
        + '</div>'

        + '<div class="signal-card">'
        +   '<div class="signal-card-title">This Week</div>'
        +   '<div class="signal-big-stat">' + (stats.posted_this_week || 0) + '</div>'
        +   '<div class="signal-stat-sub">Posts published</div>'
        + '</div>'

        + '<div class="signal-card">'
        +   '<div class="signal-card-title">' + _signalAccountLabel(signalAccount) + '</div>'
        +   '<div class="signal-big-stat">' + (accountPosts || 0) + '</div>'
        +   '<div class="signal-stat-sub">Total posted</div>'
        + '</div>'

        + '<div class="signal-card" style="cursor:pointer" onclick="switchSignalTab(\'pending\')">'
        +   '<div class="signal-card-title">Pending</div>'
        +   '<div class="signal-big-stat" style="color:' + ((data.pending_approvals || 0) > 0 ? '#fbbf24' : '#10b981') + '">' + (data.pending_approvals || 0) + '</div>'
        +   '<div class="signal-stat-sub">Awaiting approval</div>'
        + '</div>'

        + '<div class="signal-card signal-card-wide">'
        +   '<div class="signal-card-title">Content Calendar</div>'
        +   _renderSignalCalendarHtml()
        + '</div>'
        + '</div>';

    setHtml(el, html);
}

function _renderSignalCalendarHtml() {
    var days = [
        { day: 'MON', theme: 'AI & Tech Insights', active: true },
        { day: 'TUE', theme: null, active: false },
        { day: 'WED', theme: 'Business Growth', active: true },
        { day: 'THU', theme: null, active: false },
        { day: 'FRI', theme: 'Community Wins', active: true },
        { day: 'SAT', theme: null, active: false },
        { day: 'SUN', theme: null, active: false },
    ];
    var dayMap = [6, 0, 1, 2, 3, 4, 5]; // Sun=0 → idx 6
    var todayIdx = dayMap[new Date().getDay()];
    var html = '<div class="signal-calendar">';
    for (var i = 0; i < days.length; i++) {
        var d = days[i];
        var cls = 'signal-cal-day' + (d.active ? ' signal-cal-active' : '') + (i === todayIdx ? ' signal-cal-today' : '');
        html += '<div class="' + cls + '">'
            + '<div class="signal-cal-label">' + d.day + '</div>'
            + (d.active ? '<div class="signal-cal-theme">' + esc(d.theme) + '</div>' : '<div class="signal-cal-off">—</div>')
            + '</div>';
    }
    return html + '</div>';
}

function renderSignalCompose(el) {
    var html = '<div class="signal-compose">'
        + '<div class="signal-compose-header">✏️ Draft a LinkedIn post via <strong>S.I.G.N.A.L.</strong></div>'
        + '<div class="signal-compose-note">Describe what to announce in plain language. S.I.G.N.A.L. drafts the post in English + French and sends it to Telegram for your approval before anything goes live.</div>'
        + '<textarea id="signalAnnouncement" class="dhq-textarea" rows="5" placeholder="e.g. We just launched the self-healing pipeline. It reviewed 50 proposals and auto-deployed 12 this week..."></textarea>'
        + '<div class="signal-compose-row">'
        +   '<div class="signal-compose-field"><label class="signal-field-label">Post For</label>'
        +   '<select id="signalPostType" class="dhq-select">'
        +     '<option value="both" selected>🇨🇦 Both Accounts</option>'
        +     '<option value="personal">👤 Kytran Katarn (personal)</option>'
        +     '<option value="company">🏢 Kytran Empowerment Inc.</option>'
        +   '</select></div>'
        +   '<div class="signal-compose-field"><label class="signal-field-label">Tone</label>'
        +   '<select id="signalTone" class="dhq-select">'
        +     '<option value="professional">Professional</option>'
        +     '<option value="casual">Casual</option>'
        +     '<option value="bold">Bold</option>'
        +   '</select></div>'
        +   '<div class="signal-compose-field"><label class="signal-field-label">Priority</label>'
        +   '<select id="signalPriority" class="dhq-select">'
        +     '<option value="6">Normal</option>'
        +     '<option value="8">Urgent</option>'
        +     '<option value="10">Critical</option>'
        +   '</select></div>'
        + '</div>'
        + '<div id="signalComposeResult" style="display:none;margin-top:12px"></div>'
        + '<div style="margin-top:12px;display:flex;gap:8px">'
        +   '<button class="dhq-action-btn dhq-action-primary" onclick="submitSignalCompose()">Send to S.I.G.N.A.L. →</button>'
        +   '<button class="dhq-action-btn" onclick="document.getElementById(\'signalAnnouncement\').value=\'\'">Clear</button>'
        + '</div>'
        + '</div>';
    setHtml(el, html);
}

var _SIGNAL_RUN_COOLDOWN_MS = 5 * 60 * 1000; // 5 minutes per account

function _signalRunNowLabel() {
    var last = _signalLastRun[signalAccount];
    if (!last) return '▶ Run Now';
    var secs = Math.round((Date.now() - last) / 1000);
    if (secs < 60) return '✓ Triggered ' + secs + 's ago';
    return '✓ Triggered ' + Math.round(secs / 60) + 'm ago';
}

function _signalRunNowCoolingDown() {
    var last = _signalLastRun[signalAccount];
    return last && (Date.now() - last) < _SIGNAL_RUN_COOLDOWN_MS;
}

async function signalRunNow(btn) {
    if (_signalRunNowCoolingDown()) {
        btn.textContent = _signalRunNowLabel();
        return;  // silently ignore — still in cooldown
    }
    btn.textContent = '⏳ Triggering...';
    btn.disabled = true;
    try {
        await apiPost('/api/signal/run-now', { account: signalAccount });
        _signalLastRun[signalAccount] = Date.now();
        // Invalidate overview cache for this account
        delete _signalTabCache['overview:' + signalAccount];
        btn.textContent = _signalRunNowLabel();
        // Re-enable after cooldown, updating label every 30s
        var _interval = setInterval(function() {
            if (!_signalRunNowCoolingDown()) {
                clearInterval(_interval);
                btn.textContent = '▶ Run Now';
                btn.disabled = false;
            } else {
                btn.textContent = _signalRunNowLabel();
            }
        }, 30000);
    } catch (err) {
        btn.textContent = '✗ Failed — retry?';
        btn.disabled = false;
    }
}

async function submitSignalCompose() {
    var announcement = (document.getElementById('signalAnnouncement').value || '').trim();
    if (!announcement) { alert('Please describe what you want to announce.'); return; }
    var postType = document.getElementById('signalPostType').value;
    var resultEl = document.getElementById('signalComposeResult');
    resultEl.style.display = 'block';
    var loadingMsg = postType === 'both'
        ? 'S.I.G.N.A.L. is drafting posts for both accounts (EN + FR each)...'
        : 'S.I.G.N.A.L. is drafting your post (EN + FR)...';
    setHtml(resultEl, '<div class="dhq-loading" style="padding:8px">' + esc(loadingMsg) + '</div>');
    try {
        var resp = await apiPost('/api/signal/compose', {
            announcement: announcement,
            tone: document.getElementById('signalTone').value,
            post_type: postType,
            priority: parseInt(document.getElementById('signalPriority').value),
        });
        var approvals = resp.approvals || [];
        var labels = { personal: '👤 Kytran Katarn', company: '🏢 Kytran Empowerment Inc.' };
        var previews = approvals.map(function(a) {
            return '<div style="margin-top:8px"><strong>' + esc(labels[a.post_type] || a.post_type) + '</strong>'
                + ' <span style="opacity:0.5;font-size:0.8em">#' + a.approval_id + '</span>'
                + '<div class="signal-compose-preview">' + esc(a.preview || '') + '…</div></div>';
        }).join('');
        setHtml(resultEl, '<div class="signal-compose-success">'
            + '<div style="color:#10b981;font-weight:600;margin-bottom:4px">✓ ' + approvals.length + ' draft(s) queued for Telegram approval</div>'
            + previews
            + '</div>');
        document.getElementById('signalAnnouncement').value = '';
        loadSignalPendingBadge();
    } catch (err) {
        setHtml(resultEl, '<div style="color:#ef4444;padding:8px">Error: ' + esc(err.message) + '</div>');
    }
}

async function renderSignalPostLog(el) {
    var data = await api('/api/signal/post-log?account=' + signalAccount + '&limit=30');
    var posts = data.posts || [];
    if (posts.length === 0) {
        setHtml(el, '<div class="dhq-empty">No posts logged for ' + _signalAccountLabel(signalAccount) + ' yet. Content calendar fires Mon/Wed/Fri at 9 AM ET.</div>');
        return;
    }
    var html = '<div class="signal-post-log">';
    for (var i = 0; i < posts.length; i++) {
        var p = posts[i];
        var sc = p.status === 'posted' ? '#10b981' : p.status === 'failed' ? '#ef4444' : '#9ca3af';
        var engagement = [];
        if (p.impressions) engagement.push(p.impressions + ' impressions');
        if (p.reactions)   engagement.push(p.reactions + ' reactions');
        if (p.comments)    engagement.push(p.comments + ' comments');
        if (p.shares)      engagement.push(p.shares + ' shares');
        html += '<div class="signal-post-row">'
            + '<div class="signal-post-dot" style="color:' + sc + '">●</div>'
            + '<div class="signal-post-body">'
            +   '<div class="signal-post-content">' + esc((p.content || '').substring(0, 180)) + ((p.content || '').length > 180 ? '…' : '') + '</div>'
            +   '<div class="signal-post-meta">' + fmtTime(p.posted_at) + (engagement.length ? ' · ' + engagement.join(' · ') : '') + '</div>'
            + '</div>'
            + '</div>';
    }
    setHtml(el, html + '</div>');
}

async function renderSignalPending(el) {
    var data = await api('/api/signal/pending-approvals?account=' + signalAccount);
    var approvals = data.approvals || [];
    if (approvals.length === 0) {
        setHtml(el, '<div class="dhq-empty">No pending LinkedIn posts — S.I.G.N.A.L. is all clear.</div>');
        return;
    }
    var html = '<div class="signal-pending-list">';
    for (var i = 0; i < approvals.length; i++) {
        var a = approvals[i];
        var content = (a.action_data || {}).content || a.reason || '';
        html += '<div class="signal-pending-card">'
            + '<div class="signal-pending-header">'
            +   '<span class="signal-pending-from">' + esc(a.requested_by || 'S.I.G.N.A.L.') + '</span>'
            +   '<span class="signal-pending-time">' + fmtTime(a.created_at) + '</span>'
            + '</div>'
            + '<div class="signal-pending-content">' + esc(content) + '</div>'
            + '<div class="signal-pending-actions">'
            +   '<button class="dhq-action-btn dhq-action-primary" onclick="approveSignalPost(' + a.id + ')">✓ Approve &amp; Post</button>'
            +   '<button class="dhq-action-btn dhq-action-danger" onclick="denySignalPost(' + a.id + ')">✗ Deny</button>'
            + '</div>'
            + '</div>';
    }
    setHtml(el, html + '</div>');
}

async function approveSignalPost(approvalId) {
    try {
        await apiPost('/api/signal/pending/' + approvalId + '/approve', {});
        delete _signalTabCache['pending'];
        loadSignalTab('pending', true);
        loadSignalPendingBadge();
    } catch (err) { alert('Error: ' + err.message); }
}

function lcarsPrompt(title, body, placeholder, accentColor) {
    return new Promise(function(resolve) {
        var accent = accentColor || '#ef4444';

        // Build modal using DOM methods (no innerHTML with user data)
        var overlay = document.createElement('div');
        overlay.className = 'bm-overlay active';
        overlay.style.zIndex = '9999';
        overlay.addEventListener('click', function(e) { if (e.target === overlay) { overlay.remove(); resolve(null); } });

        var shell = document.createElement('div');
        shell.className = 'bm-shell';
        shell.style.cssText = '--bm-accent:' + accent + ';max-width:480px';

        var frame = document.createElement('div');
        frame.className = 'bm-frame';

        var content = document.createElement('div');
        content.className = 'bm-content';

        var header = document.createElement('div');
        header.className = 'bm-header';
        header.textContent = title;

        var modalBody = document.createElement('div');
        modalBody.className = 'bm-body';
        modalBody.style.cssText = 'padding:16px 20px';

        if (body) {
            var bodyText = document.createElement('div');
            bodyText.style.cssText = 'font-size:0.75rem;opacity:0.65;margin-bottom:10px';
            bodyText.textContent = body;
            modalBody.appendChild(bodyText);
        }

        var textarea = document.createElement('textarea');
        textarea.className = 'dhq-textarea';
        textarea.rows = 3;
        textarea.placeholder = placeholder || '';
        textarea.style.cssText = 'width:100%;resize:vertical';
        modalBody.appendChild(textarea);

        var footer = document.createElement('div');
        footer.className = 'bm-footer';
        footer.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;padding:12px 20px';

        var cancelBtn = document.createElement('button');
        cancelBtn.className = 'dhq-action-btn';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', function() { overlay.remove(); resolve(null); });

        var confirmBtn = document.createElement('button');
        confirmBtn.className = 'dhq-action-btn';
        confirmBtn.textContent = 'Confirm';
        confirmBtn.style.cssText = 'background:' + accent + ';color:#fff;border-color:' + accent;
        confirmBtn.addEventListener('click', function() { var v = textarea.value; overlay.remove(); resolve(v); });

        footer.appendChild(cancelBtn);
        footer.appendChild(confirmBtn);
        content.appendChild(header);
        content.appendChild(modalBody);
        content.appendChild(footer);
        shell.appendChild(frame);
        shell.appendChild(content);
        overlay.appendChild(shell);
        document.body.appendChild(overlay);
        setTimeout(function() { textarea.focus(); }, 50);
    });
}

async function denySignalPost(approvalId) {
    var reason = await lcarsPrompt(
        'Deny Draft',
        'Tell S.I.G.N.A.L. why — she learns from your feedback.',
        'e.g. Too generic, needs more Montreal angle...',
        '#ef4444'
    );
    if (reason === null) return;
    try {
        var resp = await apiPost('/api/signal/pending/' + approvalId + '/deny', { reason: reason });
        delete _signalTabCache['pending'];
        delete _signalTabCache['overview'];
        loadSignalTab('pending', true);
        loadSignalPendingBadge();
        if (resp && resp.revising) {
            // Show brief confirmation — new draft will arrive in Telegram
            var note = document.createElement('div');
            note.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#1e293b;border:1px solid #8b5cf6;color:#a78bfa;padding:12px 16px;border-radius:6px;font-size:0.75rem;z-index:9999;max-width:280px';
            note.textContent = '✏️ S.I.G.N.A.L. is revising — new draft coming to Telegram.';
            document.body.appendChild(note);
            setTimeout(function() { note.remove(); }, 5000);
        }
    } catch (err) { alert('Error: ' + err.message); }
}

async function renderSignalHashtags(el) {
    var data = await api('/api/signal/hashtag-stats');
    var tags = data.hashtags || [];
    if (tags.length === 0) {
        setHtml(el, '<div class="dhq-empty">No hashtag data yet.</div>');
        return;
    }
    var html = '<table class="signal-hashtag-table"><thead><tr>'
        + '<th>Hashtag</th><th>Uses</th><th>Avg Engagement</th><th>Impressions</th><th>Last Used</th>'
        + '</tr></thead><tbody>';
    for (var i = 0; i < tags.length; i++) {
        var t = tags[i];
        html += '<tr>'
            + '<td><span class="signal-tag">#' + esc(t.hashtag) + '</span></td>'
            + '<td>' + (t.usage_count || 0) + '</td>'
            + '<td>' + (t.avg_engagement ? parseFloat(t.avg_engagement).toFixed(1) : '—') + '</td>'
            + '<td>' + (t.total_impressions || 0) + '</td>'
            + '<td>' + (t.last_used ? fmtTime(t.last_used) : '—') + '</td>'
            + '</tr>';
    }
    setHtml(el, html + '</tbody></table>');
}

// Phase 2: status -> chip visual map. Aligned with services/signal_post_status.py classifier.
var _SIGNAL_STATUS_VISUALS = {
    posted:    { bg:'#22c55e', fg:'#04130a', icon:'✓',  label:'POSTED'    },
    pending:   { bg:'#f59e0b', fg:'#1a0f00', icon:'⏳', label:'PENDING'   },
    executing: { bg:'#3b82f6', fg:'#04101f', icon:'⟳',  label:'EXECUTING' },
    failed:    { bg:'#ef4444', fg:'#1a0404', icon:'✗',  label:'FAILED'    },
    rejected:  { bg:'#9ca3af', fg:'#0d0f12', icon:'🚫', label:'REJECTED'  },
    deferred:  { bg:'#8b5cf6', fg:'#0a041a', icon:'⏸', label:'DEFERRED'  }
};

var _SIGNAL_LANG_EMOJI = { en: '🇨🇦', fr: '⚜️' };

function _onSignalChipClick(approvalId, status) {
    var post = _signalCalendarPostCache[approvalId];
    if (!post) {
        console.warn('[SIGNAL chip click] post not in cache', approvalId);
        return;
    }
    _openSignalPostModal(post);
}

function _renderSignalChip(post) {
    var v = _SIGNAL_STATUS_VISUALS[post.status] || _SIGNAL_STATUS_VISUALS.failed;
    var langEmoji = _SIGNAL_LANG_EMOJI[post.lang] || '🌐';
    var pulseAnim = post.status === 'executing'
        ? 'animation:bmLightPulse 1.4s ease-in-out infinite;'
        : '';
    return '<button type="button" class="signal-chip"'
        + ' onclick="_onSignalChipClick(' + (post.approval_id || 0) + ',\'' + post.status + '\')"'
        + ' title="' + esc(v.label + ' — click for details (Phase 3)') + '"'
        + ' style="display:flex;align-items:center;gap:4px;width:100%;'
        +         'background:' + v.bg + ';color:' + v.fg + ';'
        +         'border:none;border-radius:4px;padding:4px 6px;margin-bottom:3px;'
        +         'font-family:\'IBM Plex Mono\',monospace;font-size:0.5rem;letter-spacing:0.5px;'
        +         'cursor:pointer;text-align:left;' + pulseAnim + '">'
        +     '<span style="font-size:0.65rem;">' + langEmoji + '</span>'
        +     '<span style="font-weight:700;">' + v.icon + '</span>'
        +     '<span style="flex:1;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
        +         esc(v.label)
        +     '</span>'
        + '</button>';
}

async function renderSignalCalendar(el) {
    var account = signalAccount || 'company';
    var data;
    try {
        data = await api('/api/signal/calendar/live?account=' + encodeURIComponent(account));
    } catch (err) {
        setHtml(el, '<div class="dhq-empty" style="color:#ef4444;">Calendar load failed: '
            + esc(err && err.message ? err.message : String(err)) + '</div>');
        return;
    }

    var days = data.days || [];

    // Phase 3: populate post cache so chip clicks can look up full post object
    _signalCalendarPostCache = {};
    for (var di = 0; di < days.length; di++) {
        var dposts = days[di].posts || [];
        for (var pi = 0; pi < dposts.length; pi++) {
            if (dposts[pi].approval_id != null) {
                _signalCalendarPostCache[dposts[pi].approval_id] = dposts[pi];
            }
        }
    }

    var DAY_ABBR = ['MON','TUE','WED','THU','FRI','SAT','SUN'];

    var weekStart = data.week_start || '';
    var headerLine = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
        +     '<div style="color:#555;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;">'
        +         'Living Dashboard — Week of ' + esc(weekStart) + ' · Account: ' + esc(account)
        +     '</div>'
        +     '<div style="color:#22d3ee;font-size:0.55rem;letter-spacing:1px;">'
        +         '⟳ refresh on tab switch'
        +     '</div>'
        + '</div>';

    var grid = '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:6px;">';
    for (var i = 0; i < 7; i++) {
        grid += _renderSignalDayCell(days[i] || { date:'', is_today:false, posts:[] }, DAY_ABBR[i]);
    }
    grid += '</div>';

    var legend = _renderSignalLegend();

    setHtml(el, headerLine + grid + legend);
}

function _renderSignalDayCell(day, abbr) {
    var posts = day.posts || [];
    var isToday = !!day.is_today;
    var border = isToday ? '#22d3ee' : '#333';
    var glow = isToday ? 'box-shadow:0 0 8px rgba(34,211,238,0.3);' : '';
    var dateLabel = (day.date || '').substring(5); // MM-DD

    var html = '<div style="background:#0d1117;border:1px solid ' + border + ';border-radius:5px;'
        +         'padding:7px;min-height:120px;display:flex;flex-direction:column;' + glow + '">'
        +     '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">'
        +         '<span style="font-size:0.55rem;color:' + border + ';font-family:\'Orbitron\',sans-serif;letter-spacing:1px;">'
        +             abbr + (isToday ? ' • TODAY' : '')
        +         '</span>'
        +         '<span style="font-size:0.45rem;color:#555;">' + esc(dateLabel) + '</span>'
        +     '</div>';

    if (!posts.length) {
        html += '<div style="flex:1;display:flex;align-items:center;justify-content:center;'
            +         'border:1px dashed #2a2a2a;border-radius:4px;color:#444;'
            +         'font-size:0.5rem;font-style:italic;">+ Draft now</div>';
    } else {
        for (var p = 0; p < posts.length; p++) {
            html += _renderSignalChip(posts[p]);
        }
    }

    html += '</div>';
    return html;
}

function _renderSignalLegend() {
    var keys = ['posted','pending','executing','failed','rejected','deferred'];
    var items = '';
    for (var i = 0; i < keys.length; i++) {
        var v = _SIGNAL_STATUS_VISUALS[keys[i]];
        items += '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;'
            +              'font-size:0.5rem;color:#777;letter-spacing:1px;">'
            +     '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:' + v.bg + ';"></span>'
            +     v.label
            + '</span>';
    }
    return '<div style="margin-top:12px;padding-top:8px;border-top:1px solid #1a1a1a;">' + items + '</div>';
}

// ===== Phase 3: SIGNAL post modal =====

// JS-side cache populated by renderSignalCalendar — keyed by approval_id.
var _signalCalendarPostCache = {};

function _signalAccountLabel(account) {
    if (account === 'company')  return 'KE Inc.';
    if (account === 'personal') return 'Kytran Katarn';
    if (account === 'creed')    return 'Creed-AI';
    return esc(account || '');
}

function _signalDayLabel(dateStr) {
    if (!dateStr) return '';
    var DAYS = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
    try {
        var d = new Date(dateStr + 'T12:00:00');
        return DAYS[d.getUTCDay()] + ' ' + dateStr;
    } catch (e) { return dateStr; }
}

function _renderModalHeader(post, account) {
    var v = _SIGNAL_STATUS_VISUALS[post.status] || _SIGNAL_STATUS_VISUALS.failed;
    var langEmoji = _SIGNAL_LANG_EMOJI[post.lang] || '🌐';
    var langLabel = post.lang === 'fr' ? 'FR' : (post.lang === 'en' ? 'EN' : esc((post.lang||'??').toUpperCase()));
    var dayDate = (post.drafted_at || '').substring(0, 10);
    return '<div style="padding:14px 18px;border-bottom:1px solid #1a1a1a;display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
        +     '<span style="color:#aaa;font-family:\'Antonio\',sans-serif;font-size:0.7rem;letter-spacing:1px;">'
        +         esc(_signalAccountLabel(account))
        +     '</span>'
        +     '<span style="color:#555;">·</span>'
        +     '<span style="color:#888;font-size:0.65rem;">' + esc(_signalDayLabel(dayDate)) + '</span>'
        +     '<span style="color:#555;">·</span>'
        +     '<span style="font-size:0.7rem;">' + esc(langEmoji) + ' ' + langLabel + '</span>'
        +     '<div style="flex:1;"></div>'
        +     '<span style="background:' + v.bg + ';color:' + v.fg + ';border-radius:4px;'
        +              'padding:4px 10px;font-family:\'IBM Plex Mono\',monospace;'
        +              'font-size:0.55rem;font-weight:700;letter-spacing:1px;">'
        +         esc(v.icon) + ' ' + esc(v.label)
        +     '</span>'
        + '</div>';
}

function _renderModalContent(post) {
    var content = post.content || post.preview || '';
    if (!content) {
        return '<div style="padding:14px 18px;color:#555;font-style:italic;font-size:0.65rem;">'
             + '(no content)</div>';
    }
    return '<div style="padding:14px 18px;">'
        +     '<div style="color:#666;font-size:0.55rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">'
        +         'Content'
        +     '</div>'
        +     '<div style="background:#0d1117;border:1px solid #1a1a1a;border-radius:4px;'
        +              'padding:10px 12px;color:#bbb;font-size:0.7rem;line-height:1.5;'
        +              'max-height:280px;overflow-y:auto;white-space:pre-wrap;">'
        +         esc(content)
        +     '</div>'
        + '</div>';
}

function _renderModalError(post) {
    if (!post.error) return '';
    return '<div style="padding:0 18px 14px;">'
        +     '<div style="color:#ef4444;font-size:0.55rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">'
        +         'Error'
        +     '</div>'
        +     '<div style="background:#1a0404;border:1px solid #ef4444;border-radius:4px;'
        +              'padding:10px 12px;color:#fca5a5;font-size:0.65rem;line-height:1.5;font-family:\'IBM Plex Mono\',monospace;">'
        +         esc(post.error)
        +     '</div>'
        + '</div>';
}

function _renderModalTimeline(post) {
    var rows = '';
    function fmt(iso) {
        if (!iso) return '';
        try { return iso.substring(11, 16) + ' UTC'; }
        catch (e) { return ''; }
    }
    if (post.drafted_at)  rows += '<div style="margin-bottom:6px;">v <span style="color:#666;">' + esc(fmt(post.drafted_at)) + '</span> Drafted</div>';
    if (post.approved_at) rows += '<div style="margin-bottom:6px;">v <span style="color:#666;">' + esc(fmt(post.approved_at)) + '</span> Approved</div>';
    if (post.executed_at) {
        var verb = post.status === 'posted' ? 'Posted to LinkedIn'
                 : post.status === 'failed' ? 'Skill execution failed'
                 : 'Executed';
        var mark = post.status === 'failed' ? 'x' : 'v';
        rows += '<div style="margin-bottom:6px;">' + mark
             + ' <span style="color:#666;">' + esc(fmt(post.executed_at)) + '</span> ' + esc(verb) + '</div>';
    }
    if (post.telegram_message_id) {
        rows += '<div style="margin-bottom:6px;color:#888;">Telegram msg #' + esc(String(post.telegram_message_id)) + '</div>';
    }
    if (!rows) {
        rows = '<div style="color:#555;font-style:italic;">(no timeline events yet)</div>';
    }
    return '<div style="padding:0 18px 14px;">'
        +     '<div style="color:#666;font-size:0.55rem;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">'
        +         'Timeline'
        +     '</div>'
        +     '<div style="font-size:0.65rem;color:#aaa;font-family:\'IBM Plex Mono\',monospace;">'
        +         rows
        +     '</div>'
        + '</div>';
}

function _phase4Stub(label) {
    var safe = String(label).replace(/'/g, "\\'");
    return ' onclick="alert(\'' + safe + ' - Phase 4. Use Telegram bot for now.\')"';
}

function _renderModalActions(post) {
    var btns = '';
    var btnBase = 'background:#1f2937;color:#e5e7eb;border:1px solid #374151;'
                + 'border-radius:4px;padding:8px 14px;cursor:pointer;'
                + 'font-family:\'Antonio\',sans-serif;font-size:0.7rem;letter-spacing:1px;'
                + 'text-transform:uppercase;';
    var aid = post.approval_id || 0;

    if (post.status === 'posted' && post.linkedin_url && /^https:\/\//i.test(post.linkedin_url)) {
        btns += '<a href="' + esc(post.linkedin_url) + '" target="_blank" rel="noopener" '
             +    'style="' + btnBase + 'background:#22c55e;color:#04130a;border-color:#16a34a;text-decoration:none;">'
             +    'Open on LinkedIn'
             + '</a>';
    }
    if (post.status === 'pending') {
        btns += '<button type="button" style="' + btnBase + 'background:#22c55e;color:#04130a;border-color:#16a34a;" '
             +    'onclick="_signalApprovePost(' + aid + ')">'
             +    'Approve'
             + '</button>';
        btns += '<button type="button" style="' + btnBase + 'background:#ef4444;color:#1a0404;border-color:#dc2626;" '
             +    'onclick="_signalRejectPost(' + aid + ')">'
             +    'Reject'
             + '</button>';
    }
    if (post.status === 'failed') {
        btns += '<button type="button" style="' + btnBase + 'background:#3b82f6;color:#04101f;border-color:#2563eb;" '
             +    'onclick="_signalRetryPost(' + aid + ')">Retry</button>';
        btns += '<button type="button" style="' + btnBase + 'background:#9ca3af;color:#0d0f12;border-color:#6b7280;" '
             +    'onclick="_signalAbandonPost(' + aid + ')">Mark Won\'t Fix</button>';
    }
    if (post.status === 'rejected') {
        var redraftAccount = post.post_type || (signalAccount || 'company');
        btns += '<button type="button" style="' + btnBase + 'background:#22d3ee;color:#04130a;border-color:#06b6d4;" '
             +    'onclick="_signalRedraftPost(\'' + esc(redraftAccount) + '\')">Re-draft</button>';
    }
    if (post.status === 'deferred') {
        btns += '<button type="button" style="' + btnBase + 'opacity:0.5;"'
             +    _phase4Stub('Reconnect') + '>Reconnect</button>';
    }
    btns += '<button type="button" style="' + btnBase + '" onclick="_closeSignalPostModal()">Close</button>';

    return '<div style="padding:14px 18px;border-top:1px solid #1a1a1a;display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;">'
        +     btns
        + '</div>';
}

function _openSignalPostModal(post) {
    if (!post) return;
    _closeSignalPostModal();

    var account = signalAccount || post.post_type || 'company';

    var overlay = document.createElement('div');
    overlay.className = 'bm-overlay active bm-signal-post-modal';
    overlay.style.cssText = '--bm-accent:#22d3ee;--bm-accent-rgb:34,211,238;';
    overlay.onclick = function(e) { if (e.target === overlay) _closeSignalPostModal(); };

    var shell = document.createElement('div');
    shell.className = 'bm-shell';
    shell.style.cssText = 'max-width:680px;background:#070b10;color:#e5e7eb;border-radius:8px;'
                        + 'border:1px solid #1f2937;overflow:hidden;display:flex;flex-direction:column;';
    shell.onclick = function(e) { e.stopPropagation(); };

    setHtml(shell,
        _renderModalHeader(post, account)
      + _renderModalContent(post)
      + _renderModalError(post)
      + _renderModalTimeline(post)
      + _renderModalActions(post)
    );

    overlay.appendChild(shell);
    document.body.appendChild(overlay);
}

async function _signalApprovePost(approvalId) {
    if (!approvalId) return;
    if (!confirm('Approve this post?')) return;
    try {
        await apiPost('/api/signal/pending/' + approvalId + '/approve', {});
        _closeSignalPostModal();
        loadSignalTab('calendar', true);  // force-refresh chip status
    } catch (err) {
        alert('Approve failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalRejectPost(approvalId) {
    if (!approvalId) return;
    var reason = prompt('Reason for rejection (optional):', '');
    if (reason === null) return;  // user clicked Cancel
    try {
        await apiPost('/api/signal/pending/' + approvalId + '/deny', { reason: reason || '' });
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Reject failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalRetryPost(approvalId) {
    if (!approvalId) return;
    if (!confirm('Retry this post? It will re-fire the LinkedIn skill with the same content.')) return;
    try {
        await apiPost('/api/signal/posts/' + approvalId + '/retry', {});
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Retry failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalAbandonPost(approvalId) {
    if (!approvalId) return;
    if (!confirm("Mark this post Won't Fix? It will be terminal — no further retries.")) return;
    try {
        await apiPost('/api/signal/posts/' + approvalId + '/abandon', {});
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Abandon failed: ' + (err && err.message ? err.message : String(err)));
    }
}

async function _signalRedraftPost(account) {
    if (!account) return;
    if (!confirm('Re-draft for ' + account + '? This fires both EN and FR for that account.')) return;
    try {
        await apiPost('/api/signal/run-now', { account: account });
        _closeSignalPostModal();
        loadSignalTab('calendar', true);
    } catch (err) {
        alert('Re-draft failed: ' + (err && err.message ? err.message : String(err)));
    }
}

function _closeSignalPostModal() {
    var existing = document.querySelector('.bm-overlay.bm-signal-post-modal');
    if (existing) existing.remove();
}

async function renderSignalThemes(el) {
    var data = await api('/api/signal/themes');
    var themes = data.themes || [];
    if (!themes.length) {
        setHtml(el, '<div class="dhq-empty">No themes found.</div>');
        return;
    }
    var html = '<div style="margin-bottom:10px;color:#555;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;">Department Content Themes — 9 lanes</div>'
        + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;">';
    for (var i = 0; i < themes.length; i++) {
        var t = themes[i];
        var color = t.accent_color || '#8b5cf6';
        html += '<div style="background:#0d1117;border:1px solid ' + color + '44;border-radius:6px;padding:12px;">'
            + '<div style="width:10px;height:10px;border-radius:50%;background:' + color + ';margin-bottom:6px;"></div>'
            + '<div style="font-family:\'Orbitron\',sans-serif;font-size:0.62rem;color:#ccc;margin-bottom:3px;">' + esc(t.name) + '</div>'
            + '<div style="font-size:0.58rem;color:#555;margin-bottom:3px;">Curator: ' + esc(t.curator_name || '—') + '</div>'
            + '<div style="font-size:0.55rem;color:#444;">' + (t.scene_count || 0) + ' scenes \xb7 ' + esc(t.music_mood || '—') + ' music</div>'
            + '</div>';
    }
    setHtml(el, html + '</div>');
}

// ───────────────────────────────────────────────────────────────
// Devices
// ───────────────────────────────────────────────────────────────

const DEVICE_TYPE_LABELS = {
    cli: 'CLI',
    node: 'Node',
    kso: 'KSO',
    kbs: 'KBS',
    standalone: 'Standalone',
};

const DEVICE_STATUS_COLORS = {
    pending:  '#fbbf24',
    approved: '#10b981',
    denied:   '#ef4444',
    revoked:  '#6b7280',
};

function formatDeviceTime(ts) {
    if (!ts) return '—';
    // Force UTC: naive server timestamps have no tz info — append Z for correct EDT display
    var s = (typeof ts === 'string' && !ts.endsWith('Z') && !ts.includes('+')) ? ts + 'Z' : ts;
    var d = new Date(s);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}


// ───────────────────────────────────────────────────────────────
// Dispatch & Orchestration
// ───────────────────────────────────────────────────────────────

async function loadDispatch() {
    loaded['dispatch'] = true;
    // alerts-history-section kept hidden in A.R.M.A.D.A. DISPATCH sub-tab (moved to CONTROL)
    try {
        var data = await api('/api/dispatch/overview');
        renderOllamaHud(data.ollama || {});
        renderActiveJobs(data.active_jobs || []);
        renderWorkloadGrid(data.workload_grid || []);
        renderDispatchMetrics(data.dispatch_metrics || {});
        renderLoopJobs(data.loop_jobs || []);
    } catch (err) {
        var msg = '<div class="dhq-empty">Error loading dispatch data: ' + esc(err.message) + '</div>';
        ['dispatchWorkloadContent',
         'dispatchMetricsContent','dispatchLoopContent'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) setHtml(el, msg);
        });
    }
    // Load additional sections in parallel
    loadServerLoops();
    loadDispatchApprovals();
    loadDispatchHistory();
    loadClaudeFeed();
    loadDispatchComponents();
    loadDispatchScheduler();
    loadDispatchConfig();
    loadJobMonitoring();
    loadDispatchTraffic();
}

// ───────────────────────────────────────────────────────────────
// Autonomy Tab Loader
// Reuses the same data functions as the old Dispatch autonomy sections.
// Element IDs (dispatchSchedContent, dispatchConfigContent, jobMonitorContent)
// now live in panel-autonomy — same JS, different panel location.
// ───────────────────────────────────────────────────────────────
async function loadAutonomy() {
    try {
        if (typeof loadDispatchScheduler === 'function') await loadDispatchScheduler();
        if (typeof loadDispatchConfig === 'function') await loadDispatchConfig();
        if (typeof loadJobMonitoring === 'function') await loadJobMonitoring();
        loaded['autonomy'] = true;
    } catch (e) {
        console.error('[loadAutonomy] error:', e);
    }
}

function renderOllamaHud(o) {
    var el = function(id, val) { var e = document.getElementById(id); if (e) e.textContent = val; };
    el('podModelsLoaded', o.loaded_models ? o.loaded_models.length : '--');
    el('podRamUsed', o.total_ram_used_gb != null ? o.total_ram_used_gb.toFixed(1) + ' GB' : '--');
    el('podSlots', o.parallel_slots != null ? o.parallel_slots : '--');
    el('podAvailable', o.available_count != null ? o.available_count : '--');
}

function renderActiveJobs(jobs) {
    // Section removed 2026-05-13 — ACTIVE BRIDGE JOBS div deleted from dispatch panel.
    // No-op stub kept so callers in loadDispatchOverview don't throw.
}

function toggleWorkload() {
    var el = document.getElementById('dispatchWorkloadContent');
    var icon = document.getElementById('workloadToggleIcon');
    if (!el) return;
    var isHidden = el.style.display === 'none' || el.style.display === '';
    el.style.display = isHidden ? 'block' : 'none';
    if (icon) icon.textContent = isHidden ? '▲ collapse' : '▼ expand';
}

function renderWorkloadGrid(rows) {
    var container = document.getElementById('dispatchWorkloadContent');
    if (!container) return;
    while (container.firstChild) container.removeChild(container.firstChild);

    if (!rows || !rows.length) {
        var empty = document.createElement('p');
        empty.textContent = 'No workload data';
        empty.style.opacity = '0.5';
        container.appendChild(empty);
        return;
    }

    var table = document.createElement('table');
    table.style.cssText = 'width:100%;font-size:0.75rem;border-collapse:collapse;';

    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    hrow.style.cssText = 'opacity:0.5;font-size:0.65rem;';
    [['DEPARTMENT', 'left'], ['BUSY', 'right'], ['IDLE', 'right'], ['TOTAL', 'right']].forEach(function(h) {
        var th = document.createElement('th');
        th.textContent = h[0];
        th.style.cssText = 'text-align:' + h[1] + ';padding:3px 8px;';
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    rows.forEach(function(r) {
        var busy = (r.active || 0) + (r.deployed || 0);
        var idle = r.barracked || 0;
        var tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid rgba(255,255,255,0.06)';

        var td1 = document.createElement('td');
        td1.textContent = r.department || '';
        td1.style.padding = '3px 8px';

        var td2 = document.createElement('td');
        td2.textContent = String(busy);
        td2.style.cssText = 'padding:3px 8px;text-align:right;color:#10B981;';

        var td3 = document.createElement('td');
        td3.textContent = String(idle);
        td3.style.cssText = 'padding:3px 8px;text-align:right;';

        var td4 = document.createElement('td');
        td4.textContent = String(r.total || 0);
        td4.style.cssText = 'padding:3px 8px;text-align:right;color:var(--archie-palette-teal-300,#5eead4);';

        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
}

function renderDispatchMetrics(m) {
    var el = document.getElementById('dispatchMetricsContent');
    var total = m.total_24h || 0;
    var success = m.success_24h || 0;
    var failed = m.failed_24h || 0;
    var avg = m.avg_duration_ms ? (m.avg_duration_ms / 1000).toFixed(1) + 's' : '--';
    var rate = total > 0 ? Math.round(success / total * 100) : 0;
    var rateClass = rate >= 95 ? 'good' : rate >= 80 ? 'warn' : 'bad';
    var html = '<div class="dhq-metrics-row">'
        + _metricCell('TOTAL 24H', total, '')
        + _metricCell('SUCCESS', success, 'good')
        + _metricCell('FAILED', failed, failed > 0 ? 'bad' : '')
        + _metricCell('AVG RESPONSE', avg, '')
        + _metricCell('SUCCESS RATE', rate + '%', rateClass)
        + '</div>';
    setHtml(el, html);
}

function _metricCell(label, val, cls) {
    return '<div class="dhq-metric-cell"><div class="dhq-metric-label">' + label + '</div>'
        + '<div class="dhq-metric-val ' + cls + '">' + val + '</div></div>';
}

function renderLoopJobs(jobs) {
    var el = document.getElementById('dispatchLoopContent');
    if (!el) return;
    var countEl = document.getElementById('dispatchLoopCount');
    if (countEl) countEl.textContent = '(' + jobs.length + ' jobs)';
    if (!jobs.length) {
        setHtml(el, '<div class="dhq-empty">No loop jobs found</div>');
        return;
    }
    // Sort: errors first, then by department
    jobs.sort(function(a, b) {
        if (a.err_24h > 0 && b.err_24h === 0) return -1;
        if (b.err_24h > 0 && a.err_24h === 0) return 1;
        return (a.department || '').localeCompare(b.department || '') || (a.name || '').localeCompare(b.name || '');
    });
    var html = '<table class="dhq-loop-table"><thead><tr>'
        + '<th>JOB</th><th>DEPARTMENT</th><th>STATUS</th>'
        + '<th>NEXT RUN</th><th>OK</th><th>ERR</th><th>ACTIONS</th>'
        + '</tr></thead><tbody>';
    jobs.forEach(function(j) {
        var statusCls = !j.enabled ? 'dhq-loop-off'
            : j.err_24h > 0 ? 'dhq-loop-err' : 'dhq-loop-ok';
        var statusLabel = !j.enabled ? 'DISABLED'
            : j.err_24h > 0 ? 'ERRORS' : 'OK';
        var toggleLabel = j.enabled ? 'Disable' : 'Enable';
        var toggleColor = j.enabled ? '#ef4444' : '#10B981';
        html += '<tr>'
            + '<td>' + esc(j.name) + '</td>'
            + '<td>' + esc(j.department || '\u2014') + '</td>'
            + '<td class="' + statusCls + '">' + statusLabel + '</td>'
            + '<td style="color:var(--dhq-text-dim)">' + fmtTime(j.next_run) + '</td>'
            + '<td class="dhq-loop-ok">' + (j.ok_24h || 0) + '</td>'
            + '<td class="' + (j.err_24h > 0 ? 'dhq-loop-err' : '') + '">' + (j.err_24h || 0) + '</td>'
            + '<td>'
            + '<button onclick="dispatchJobToggle(\'' + esc(j.name) + '\',' + !j.enabled + ')" style="background:' + toggleColor + ';color:#fff;border:none;padding:2px 8px;border-radius:4px;font-size:0.65rem;cursor:pointer;margin-right:4px">' + toggleLabel + '</button>'
            + '<button onclick="dispatchJobRun(\'' + esc(j.name) + '\')" style="background:#8b5cf6;color:#fff;border:none;padding:2px 8px;border-radius:4px;font-size:0.65rem;cursor:pointer">Run</button>'
            + '</td></tr>';
    });
    html += '</tbody></table>';
    setHtml(el, html);
}

// ── Job Control Actions ──

async function dispatchJobToggle(name, enabled) {
    try {
        await apiPost('/api/dispatch/jobs/' + encodeURIComponent(name) + '/toggle', {enabled: enabled});
        loaded['dispatch'] = false;
        loadDispatch();
    } catch (e) { alert('Failed: ' + e.message); }
}

async function dispatchJobRun(name) {
    try {
        await apiPost('/api/dispatch/jobs/' + encodeURIComponent(name) + '/run', {});
        loaded['dispatch'] = false;
        loadDispatch();
    } catch (e) { alert('Failed: ' + e.message); }
}

// ── Server Loops ──

async function loadServerLoops() {
    var el = document.getElementById('dispatchServerLoops');
    if (!el) return;
    try {
        var data = await api('/api/dispatch/loops');
        var loops = data.loops || {};
        var keys = Object.keys(loops);
        if (!keys.length) { setHtml(el, '<div class="dhq-empty">No server loops configured</div>'); return; }
        var html = '<div style="display:flex;gap:12px;flex-wrap:wrap">';
        keys.forEach(function(k) {
            var running = loops[k];
            var color = running ? '#10B981' : '#ef4444';
            var label = running ? 'RUNNING' : 'STOPPED';
            html += '<div class="dhq-pod" style="min-width:140px;border-color:' + color + '33">'
                + '<div class="dhq-pod-label">' + esc(k.toUpperCase()) + '</div>'
                + '<div class="dhq-pod-val" style="font-size:0.9rem;color:' + color + '">' + label + '</div>'
                + '<button onclick="toggleServerLoop(\'' + esc(k) + '\')" style="margin-top:6px;background:' + (running ? '#ef4444' : '#10B981') + ';color:#fff;border:none;padding:4px 12px;border-radius:4px;font-size:0.65rem;cursor:pointer">' + (running ? 'Stop' : 'Start') + '</button>'
                + '</div>';
        });
        html += '</div>';
        setHtml(el, html);
    } catch (e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

async function toggleServerLoop(name) {
    try {
        await apiPost('/api/dispatch/loops/toggle', {name: name});
        loadServerLoops();
    } catch (e) { alert('Failed: ' + e.message); }
}

// ── Approvals ──

async function loadDispatchApprovals() {
    var el = document.getElementById('dispatchApprovalsContent');
    if (!el) return;
    var countEl = document.getElementById('dispatchApprovalCount');
    try {
        var data = await api('/api/dispatch/approvals?status=pending');
        var items = data.approvals || [];
        if (countEl) countEl.textContent = '(' + items.length + ' pending)';
        if (!items.length) { setHtml(el, '<div class="dhq-empty">No pending approvals</div>'); return; }
        var html = '';
        items.forEach(function(a) {
            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--dhq-border)">'
                + '<div><span class="dhq-status-badge dhq-status-pending">' + esc(a.type) + '</span> '
                + esc(a.description) + '<br><span style="color:var(--dhq-text-dim);font-size:0.7rem">by ' + esc(a.requested_by) + ' — ' + fmtTime(a.created_at) + '</span></div>'
                + '<div style="display:flex;gap:6px">'
                + '<button onclick="approvalAction(' + a.id + ',\'approve\')" style="background:#10B981;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:0.7rem;cursor:pointer">Approve</button>'
                + '<button onclick="approvalAction(' + a.id + ',\'reject\')" style="background:#ef4444;color:#fff;border:none;padding:4px 10px;border-radius:4px;font-size:0.7rem;cursor:pointer">Reject</button>'
                + '</div></div>';
        });
        setHtml(el, html);
    } catch (e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

async function approvalAction(id, action) {
    try {
        await apiPost('/api/dispatch/approvals/' + id + '/' + action, {});
        loadDispatchApprovals();
    } catch (e) { alert('Failed: ' + e.message); }
}

// ── History ──

async function loadDispatchHistory() {
    var el = document.getElementById('dispatchHistoryContent');
    if (!el) return;
    var hoursEl = document.getElementById('dispatchHistoryHours');
    var hours = hoursEl ? hoursEl.value : 24;
    try {
        var data = await api('/api/dispatch/history?hours=' + hours + '&limit=50');
        var entries = data.history || [];
        if (!entries.length) { setHtml(el, '<div class="dhq-empty">No history in this period</div>'); return; }
        var html = '<table class="dhq-loop-table"><thead><tr>'
            + '<th>SOURCE</th><th>ACTOR</th><th>ACTION</th><th>STATUS</th><th>DURATION</th><th>TIME</th>'
            + '</tr></thead><tbody>';
        entries.forEach(function(h) {
            var statusCls = h.status === 'success' ? 'dhq-loop-ok' : h.status === 'failed' ? 'dhq-loop-err' : '';
            var dur = h.duration_ms ? (h.duration_ms / 1000).toFixed(1) + 's' : '\u2014';
            html += '<tr>'
                + '<td><span class="dhq-status-badge ' + (h.source === 'dispatch' ? 'dhq-status-running' : 'dhq-status-pending') + '">' + esc(h.source) + '</span></td>'
                + '<td>' + esc(h.actor) + '</td>'
                + '<td>' + esc(h.action) + '</td>'
                + '<td class="' + statusCls + '">' + esc(h.status) + '</td>'
                + '<td style="color:var(--dhq-text-dim)">' + dur + '</td>'
                + '<td style="color:var(--dhq-text-dim)">' + fmtTime(h.created_at) + '</td>'
                + '</tr>';
        });
        html += '</tbody></table>';
        setHtml(el, html);
    } catch (e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

// ── Claude Requests Feed (Task #1297) ──

async function loadClaudeFeed() {
    var el = document.getElementById('dispatchClaudeContent');
    var countEl = document.getElementById('dispatchClaudeCount');
    var hoursEl = document.getElementById('dispatchClaudeHours');
    var hours = hoursEl ? hoursEl.value : 24;
    if (!el) return;
    try {
        var data = await api('/api/dispatch/claude-feed?hours=' + hours + '&limit=50');
        var feed = data.feed || [];
        var byTool = data.by_tool || [];
        var pending = data.pending || [];
        if (countEl) {
            var dispatchedSummary = '(' + (data.total || 0) + ' dispatched · ' + (data.success_rate || 0) + '% ok)';
            if (pending.length) {
                dispatchedSummary = '(' + pending.length + ' queued · ' + (data.total || 0) + ' dispatched · ' + (data.success_rate || 0) + '% ok)';
            }
            countEl.textContent = dispatchedSummary;
        }
        if (!feed.length && !pending.length) {
            setHtml(el, '<div class="dhq-empty">No Claude requests or delegations in this period — restart your Claude Code session if you expect attribution to flow.</div>');
            return;
        }

        // Queued + in-flight delegations (mcp__archie__delegate_task is async,
        // so its rows live in unified_tasks until the worker dispatches them).
        var pendingHtml = '';
        if (pending.length) {
            pendingHtml = '<div style="margin-bottom:0.8rem">'
                + '<div style="font-size:0.7rem;color:var(--dhq-text-dim);margin-bottom:0.3rem;font-family:\'Antonio\',sans-serif;letter-spacing:0.08em">DELEGATION QUEUE — ' + pending.length + ' not yet completed</div>'
                + '<table class="dhq-loop-table"><thead><tr>'
                + '<th>STATUS</th><th>CAPABILITY</th><th>REASON</th><th>SOURCE</th><th>AGE</th><th>QUEUED</th>'
                + '</tr></thead><tbody>';
            pending.forEach(function(p) {
                var statusColor = '#94a3b8';
                if (p.status === 'in_progress') statusColor = '#3b82f6';
                else if (p.status === 'pending') statusColor = '#f59e0b';
                else if (p.status === 'blocked' || p.status === 'failed') statusColor = '#ef4444';
                var ageStr = '—';
                if (p.age_secs != null) {
                    if (p.age_secs < 60) ageStr = p.age_secs + 's';
                    else if (p.age_secs < 3600) ageStr = Math.round(p.age_secs / 60) + 'm';
                    else ageStr = Math.round(p.age_secs / 3600) + 'h';
                }
                var reason = (p.reason || '').replace(/\s+/g, ' ').trim();
                if (reason.length > 80) reason = reason.slice(0, 77) + '…';
                pendingHtml += '<tr>'
                    + '<td style="color:' + statusColor + ';font-weight:600;font-family:monospace;font-size:0.72rem">' + esc(p.status || '?') + '</td>'
                    + '<td style="font-family:monospace;color:var(--dhq-accent);font-size:0.72rem">' + esc(p.capability || '?') + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + esc(reason) + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + esc(p.requested_by || '—') + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + ageStr + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + fmtTime(p.created_at) + '</td>'
                    + '</tr>';
            });
            pendingHtml += '</tbody></table></div>';
        }
        if (!feed.length) {
            setHtml(el, pendingHtml + '<div class="dhq-empty" style="margin-top:0.6rem">No dispatched requests yet — queue items above will move here once the worker completes them with attribution.</div>');
            return;
        }
        // Top tools summary chips
        var chips = '';
        if (byTool.length) {
            chips = '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.6rem">';
            byTool.forEach(function(t) {
                var okRate = t.n ? Math.round((t.ok || 0) / t.n * 100) : 0;
                var color = okRate >= 90 ? '#10B981' : okRate >= 60 ? '#f59e0b' : '#ef4444';
                chips += '<span style="padding:3px 8px;background:var(--dhq-surface-2);border:1px solid var(--dhq-border);border-radius:4px;font-size:0.7rem;font-family:monospace">'
                    + esc(t.mcp_tool || '?') + ' <span style="color:' + color + ';font-weight:600">' + t.n + '</span></span>';
            });
            chips += '</div>';
        }
        var dispatchedHeader = pendingHtml
            ? '<div style="font-size:0.7rem;color:var(--dhq-text-dim);margin-bottom:0.3rem;font-family:\'Antonio\',sans-serif;letter-spacing:0.08em">DISPATCHED — ' + feed.length + ' completed</div>'
            : '';
        var html = pendingHtml + dispatchedHeader + chips + '<table class="dhq-loop-table"><thead><tr>'
            + '<th>TOOL</th><th>AGENT</th><th>CAPABILITY</th><th>MODEL</th><th>STATUS</th><th>DURATION</th><th>COST</th><th>TIME</th>'
            + '</tr></thead><tbody>';
        feed.forEach(function(f) {
            var statusCls = f.success ? 'dhq-loop-ok' : 'dhq-loop-err';
            var statusTxt = f.success ? 'success' : 'failed';
            var dur = f.duration_ms ? (f.duration_ms / 1000).toFixed(1) + 's' : '—';
            var cost = (f.cost_usd != null && f.cost_usd > 0) ? '$' + f.cost_usd.toFixed(4) : '—';
            html += '<tr>'
                + '<td style="font-family:monospace;color:var(--dhq-accent)">' + esc(f.mcp_tool || '?') + '</td>'
                + '<td>' + esc(f.agent || '—') + '</td>'
                + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + esc(f.capability || '') + '</td>'
                + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + esc(f.model || '') + '</td>'
                + '<td class="' + statusCls + '">' + statusTxt + '</td>'
                + '<td style="color:var(--dhq-text-dim)">' + dur + '</td>'
                + '<td style="color:var(--dhq-text-dim)">' + cost + '</td>'
                + '<td style="color:var(--dhq-text-dim)">' + fmtTime(f.created_at) + '</td>'
                + '</tr>';
            if (f.error) {
                html += '<tr><td colspan="8" style="color:#ef4444;font-size:0.7rem;font-family:monospace;padding-left:1rem">' + esc(f.error) + '</td></tr>';
            }
        });
        html += '</tbody></table>';
        setHtml(el, html);
    } catch (e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

// ── System Components ──

async function loadDispatchComponents() {
    var el = document.getElementById('dispatchComponentsContent');
    try {
        var data = await api('/api/dispatch/components');
        var comps = data.components || [];
        if (!comps.length) { setHtml(el, '<div class="dhq-empty">No components</div>'); return; }
        var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:0.5rem">';
        comps.forEach(function(c) {
            var color = c.ok ? '#10B981' : '#ef4444';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.4rem 0.6rem;background:var(--dhq-surface-2);border:1px solid var(--dhq-border);border-radius:4px">'
                + '<span style="font-size:0.78rem">' + esc(c.name) + '</span>'
                + '<span style="font-size:0.7rem;font-weight:600;color:' + color + '">' + esc(c.detail || (c.ok ? 'OK' : 'ERROR')) + '</span>'
                + '</div>';
        });
        html += '</div>';
        setHtml(el, html);
    } catch(e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

// ── Scheduler Jobs ──

async function loadDispatchScheduler() {
    var el = document.getElementById('dispatchSchedContent');
    var countEl = document.getElementById('dispatchSchedCount');
    try {
        var data = await api('/api/dispatch/scheduler');
        var jobs = data.jobs || [];
        if (countEl) countEl.textContent = '(' + jobs.length + ')';
        if (!jobs.length) { setHtml(el, '<div class="dhq-empty">No scheduler jobs</div>'); return; }
        var html = '<table class="dhq-loop-table"><thead><tr><th>JOB ID</th><th>NAME</th><th>NEXT RUN</th><th>TRIGGER</th></tr></thead><tbody>';
        jobs.forEach(function(j) {
            html += '<tr><td style="color:var(--dhq-accent)">' + esc(j.id) + '</td><td>' + esc(j.name) + '</td><td style="color:var(--dhq-text-dim)">' + fmtTime(j.next_run) + '</td><td style="color:var(--dhq-text-dim);font-size:0.7rem">' + esc(j.trigger) + '</td></tr>';
        });
        html += '</tbody></table>';
        setHtml(el, html);
    } catch(e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

// ── Configuration ──

async function loadDispatchConfig() {
    var el = document.getElementById('dispatchConfigContent');
    try {
        var data = await api('/api/dispatch/config');
        var entries = data.config || [];
        if (!entries.length) { setHtml(el, '<div class="dhq-empty">No config entries</div>'); return; }
        var html = '<table class="dhq-loop-table"><thead><tr><th>KEY</th><th>VALUE</th><th></th></tr></thead><tbody>';
        entries.forEach(function(c) {
            html += '<tr><td style="color:var(--dhq-accent);font-family:monospace">' + esc(c.key) + '</td>'
                + '<td><input id="dhq-cfg-' + esc(c.key) + '" value="' + esc(c.value) + '" style="background:var(--dhq-surface-2);border:1px solid var(--dhq-border);color:var(--dhq-text);padding:3px 8px;border-radius:4px;font-family:monospace;font-size:0.78rem;width:180px"></td>'
                + '<td><button onclick="saveDispatchConfig(\'' + esc(c.key) + '\')" style="background:var(--dhq-accent);color:#000;border:none;padding:3px 10px;border-radius:4px;font-size:0.65rem;cursor:pointer;font-weight:600">Save</button></td></tr>';
        });
        html += '</tbody></table>';
        setHtml(el, html);
    } catch(e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

async function saveDispatchConfig(key) {
    var input = document.getElementById('dhq-cfg-' + key);
    if (!input) return;
    try {
        await apiPost('/api/dispatch/config/' + encodeURIComponent(key), {value: input.value});
        input.style.borderColor = '#10B981';
        setTimeout(function() { input.style.borderColor = ''; }, 2000);
    } catch(e) { input.style.borderColor = '#ef4444'; }
}

// ───────────────────────────────────────────────────────────────
// Dispatch Traffic Panel (Decision #540)
// ───────────────────────────────────────────────────────────────

var _trafficData = null;
var _trafficView = 'feed';

async function loadDispatchTraffic() {
    var el = document.getElementById('trafficContent');
    var sumEl = document.getElementById('trafficSummary');
    if (!el) return;
    var hours = (document.getElementById('trafficHours') || {}).value || 1;
    try {
        _trafficData = await api('/api/dispatch/traffic?hours=' + hours);
        if (sumEl) {
            var rate = _trafficData.success_rate != null ? _trafficData.success_rate + '% ok' : '';
            sumEl.textContent = '(' + (_trafficData.total || 0) + ' dispatches · ' + rate + ')';
        }
        showTrafficView(_trafficView);
    } catch(e) {
        setHtml(el, '<div class="dhq-empty">Traffic unavailable: ' + esc(e.message) + '</div>');
    }
}

function showTrafficView(view) {
    _trafficView = view;
    ['feed','source','agent','model','node'].forEach(function(v) {
        var btn = document.getElementById('trafficBtn-' + v);
        if (btn) btn.className = 'dhq-traffic-btn' + (v === view ? ' dhq-traffic-btn-active' : '');
    });
    var el = document.getElementById('trafficContent');
    if (!el || !_trafficData) return;
    if (view === 'feed') {
        var rows = (_trafficData.feed || []);
        if (!rows.length) { setHtml(el, '<div class="dhq-empty">No dispatches in window</div>'); return; }
        var html = '<table style="width:100%;border-collapse:collapse;font-size:0.72rem">'
            + '<tr style="color:var(--dhq-text-dim);border-bottom:1px solid var(--dhq-border)">'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">TIME</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">AGENT</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">CAPABILITY</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">MODEL</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">SOURCE</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">MS</th>'
            + '</tr>';
        rows.forEach(function(r) {
            var ok = r.success;
            var dot = '<span style="color:' + (ok ? '#10B981' : '#EF4444') + '">' + (ok ? '✓' : '✗') + '</span>';
            html += '<tr style="border-bottom:1px solid var(--dhq-border)">'
                + '<td style="padding:3px 6px;color:var(--dhq-text-dim);white-space:nowrap">' + (r.ts ? fmtTime(r.ts) : '—') + '</td>'
                + '<td style="padding:3px 6px">' + dot + ' ' + esc(r.agent) + '</td>'
                + '<td style="padding:3px 6px;color:var(--dhq-accent)">' + esc(r.capability) + '</td>'
                + '<td style="padding:3px 6px;color:var(--dhq-text-dim)">' + esc(r.model) + '</td>'
                + '<td style="padding:3px 6px;color:var(--dhq-text-dim)">' + esc(r.source) + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (r.duration_ms != null ? r.duration_ms : '—') + '</td>'
                + '</tr>';
        });
        setHtml(el, html + '</table>');
    } else {
        var key = view === 'source' ? 'by_source'
                : view === 'agent'  ? 'by_agent'
                : view === 'node'   ? 'by_node'
                                    : 'by_model';
        var rows = (_trafficData[key] || []);
        var label = view === 'source' ? 'SOURCE'
                  : view === 'agent'  ? 'AGENT'
                  : view === 'node'   ? 'NODE'
                                      : 'MODEL';
        if (!rows.length) { setHtml(el, '<div class="dhq-empty">No data</div>'); return; }
        var html = '<table style="width:100%;border-collapse:collapse;font-size:0.72rem">'
            + '<tr style="color:var(--dhq-text-dim);border-bottom:1px solid var(--dhq-border)">'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">' + label + '</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">TOTAL</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">OK%</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">AVG MS</th>'
            + '</tr>';
        rows.forEach(function(r) {
            var pct = r.total > 0 ? Math.round(r.successes / r.total * 100) : 0;
            var pctColor = pct >= 90 ? '#10B981' : pct >= 70 ? '#FFAA00' : '#EF4444';
            html += '<tr style="border-bottom:1px solid var(--dhq-border)">'
                + '<td style="padding:3px 6px;color:var(--dhq-accent)">' + esc(r.label || '—') + '</td>'
                + '<td style="padding:3px 6px;text-align:right">' + r.total + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:' + pctColor + '">' + pct + '%</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (r.avg_ms != null ? r.avg_ms : '—') + '</td>'
                + '</tr>';
        });
        setHtml(el, html + '</table>');
    }
}

// ───────────────────────────────────────────────────────────────
// Job Monitoring by Department
// ───────────────────────────────────────────────────────────────

async function loadJobMonitoring() {
    var el = document.getElementById('jobMonitorContent');
    var countEl = document.getElementById('jobMonitorCount');
    if (!el) return;
    try {
        var data = await api('/api/jobs/by-department');
        var depts = data.departments || {};
        var deptKeys = Object.keys(depts);
        if (countEl) countEl.textContent = '(' + deptKeys.length + ' departments)';
        if (!deptKeys.length) {
            setHtml(el, '<div class="dhq-empty">No job registry data</div>');
            return;
        }
        var html = '';
        deptKeys.forEach(function(key) {
            var dept = depts[key];
            var failBadge = dept.total_fails > 0
                ? '<span style="color:#EF4444;font-weight:600;margin-left:8px">' + dept.total_fails + ' fail</span>'
                : '';
            var okBadge = '<span style="color:#10B981;margin-left:8px">' + dept.total_success + ' ok</span>';
            var deptId = 'jm-dept-' + key.replace(/[^a-zA-Z0-9]/g, '_');
            html += '<div class="dhq-jm-dept">'
                + '<div class="dhq-jm-dept-header" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:var(--dhq-surface-2);border-radius:6px;margin-bottom:4px">'
                + '<div style="display:flex;align-items:center;gap:8px">'
                + '<span style="font-family:\'Antonio\',sans-serif;font-size:0.8rem;letter-spacing:1px;color:var(--dhq-accent)">' + esc(dept.name) + '</span>'
                + '<span style="font-size:0.65rem;color:var(--dhq-text-dim)">' + esc(dept.director) + '</span>'
                + '<span style="font-size:0.65rem;color:var(--dhq-text-dim)">' + dept.jobs.length + ' jobs</span>'
                + '</div>'
                + '<div>' + okBadge + failBadge + '</div>'
                + '</div>'
                + '<div id="' + deptId + '" class="dhq-jm-jobs" style="display:none;padding:0 0 8px 16px">';
            dept.jobs.forEach(function(j) {
                var dotColor = j.status === 'ok' ? '#10B981' : j.status === 'error' ? '#EF4444' : j.status === 'warning' ? '#FFAA00' : '#555';
                html += '<div class="dhq-jm-job" style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:0.75rem;border-bottom:1px solid var(--dhq-border)">'
                    + '<span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';flex-shrink:0"></span>'
                    + '<span style="flex:1;color:var(--dhq-text)">' + esc(j.description) + '</span>'
                    + '<span style="color:var(--dhq-text-dim);font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem">' + esc(j.interval) + '</span>'
                    + '<span style="color:var(--dhq-text-dim);font-size:0.65rem">' + (j.last_run ? fmtTime(j.last_run) : 'never') + '</span>';
                if (j.last_error) {
                    html += '<span title="' + esc(j.last_error) + '" style="color:#EF4444;font-size:0.65rem;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block">' + esc(j.last_error) + '</span>';
                }
                html += '</div>';
            });
            html += '</div></div>';
        });
        setHtml(el, html);
    } catch(e) {
        setHtml(el, '<div class="dhq-empty">Job monitoring unavailable: ' + esc(e.message) + '</div>');
    }
}

// Toggle helper for job monitoring department sections
document.addEventListener('click', function(e) {
    var header = e.target.closest('.dhq-jm-dept-header');
    if (!header) return;
    var jobs = header.nextElementSibling;
    if (jobs) jobs.style.display = jobs.style.display === 'none' ? 'block' : 'none';
});

// ───────────────────────────────────────────────────────────────
/* ============================================================
   A.R.M.A.D.A. Sub-tabs — CLUSTER / DISPATCH / TRAFFIC / NETWORK
   Dispatch content is lazy-mounted from panel-dispatch on first open.
   ============================================================ */
var _armadaSection = 'cluster';
var _armadaMounted = {};

function switchArmadaSection(s) {
    _armadaSection = s;
    try { localStorage.setItem('dhq_armada_section', s); } catch (_) {}
    var sections = ['cluster', 'dispatch', 'traffic', 'network', 'orchestration'];
    sections.forEach(function(name) {
        var sec = document.getElementById('armadaSection-' + name);
        var btn = document.getElementById('armadaBtn-' + name);
        if (sec) sec.style.display = name === s ? '' : 'none';
        if (btn) btn.classList.toggle('dhq-traffic-btn-active', name === s);
    });

    // DISPATCH: move panel-dispatch inner content into armadaSection-dispatch on first open
    if (s === 'dispatch' && !_armadaMounted.dispatch) {
        _armadaMounted.dispatch = true;
        var target = document.getElementById('armadaSection-dispatch');
        var source = document.getElementById('panel-dispatch');
        if (target && source) {
            // Move all children (skipping the LCARS frame wrappers — grab the inner content div)
            var inner = source.querySelector('[style*="padding:16px"]');
            if (inner) {
                while (inner.firstChild) target.appendChild(inner.firstChild);
            } else {
                while (source.firstChild) target.appendChild(source.firstChild);
            }
        }
        if (!loaded['dispatch']) { loaded['dispatch'] = true; loadDispatch(); }
    }

    // TRAFFIC: move traffic panel from dispatch content
    if (s === 'traffic' && !_armadaMounted.traffic) {
        _armadaMounted.traffic = true;
        var trafficTarget = document.getElementById('armadaSection-traffic');
        var trafficSrc = document.getElementById('trafficPanelSection');
        var claudeSrc = document.getElementById('dispatchClaudeContent');
        var metricsSrc = document.getElementById('dispatchMetricsContent');
        if (trafficTarget) {
            if (trafficSrc) trafficTarget.appendChild(trafficSrc);
        }
        loadDispatchTraffic();
        loadClaudeFeed();
    }

    // NETWORK: move fleet map section
    if (s === 'network' && !_armadaMounted.network) {
        _armadaMounted.network = true;
        loadFleetData(); initFleetMap(); loadFleetUsage();
    }

    // CLUSTER: refresh live data
    if (s === 'cluster') {
        loadQueueStatus(); loadClusterActivity();
    }

    // ORCHESTRATION: move cluster-orchestration-panel into its section on first open
    if (s === 'orchestration' && !_armadaMounted.orchestration) {
        _armadaMounted.orchestration = true;
        var orchTarget = document.getElementById('armadaSection-orchestration');
        var orchSrc = document.getElementById('cluster-orchestration-panel');
        if (orchTarget && orchSrc) orchTarget.appendChild(orchSrc);
        orchSrc && (orchSrc.style.display = '');
    }
}

function loadFleet() {
    loaded["fleet"] = true;
    // alerts-history-section is now in panel-alerts — do not hide it here
    // Restore last armada subtab (cluster is default)
    var _savedArmadaSection = 'cluster';
    try { _savedArmadaSection = localStorage.getItem('dhq_armada_section') || 'cluster'; } catch (_) {}
    switchArmadaSection(_savedArmadaSection);
    setTimeout(function() {
        initFleetMap();
        loadFleetData();
        loadFleetUsage();
        loadCloudProviders();
        loadProviderManagement();
        loadQueueStatus();
        loadClusterActivity();
        loadDispatchComponents();
        loadDispatchMode();
        if (typeof window.ahFetch === 'function') window.ahFetch(true);
        startFleetRefresh();
    }, 200);
}

/* ============================================================
   FLEET MAP — Phase 4 Agent Lifecycle Coordination
   ============================================================ */

var fleetMap = null;
var fleetMarkers = [];
var _fleetRefreshInterval = null;

function startFleetRefresh() {
    if (_fleetRefreshInterval) return;
    _fleetRefreshInterval = setInterval(function() {
        loadFleetData();
        loadFleetUsage();
        loadCloudProviders();
        loadProviderManagement();
        loadQueueStatus();
        loadClusterActivity();
        // Tick the live indicator so user sees data is current
        var ts = document.getElementById('fleetLastRefresh');
        if (ts) ts.textContent = 'just now';
        // Fade to "Xs ago" over subsequent ticks
        var secs = 0;
        var ticker = setInterval(function() {
            secs += 10;
            if (secs >= 60 && ts) { ts.textContent = Math.floor(secs / 60) + 'm ago'; }
            else if (ts) { ts.textContent = secs + 's ago'; }
        }, 10000);
        // Clear old ticker on next cycle (new one created each interval)
        setTimeout(function() { clearInterval(ticker); }, 9500);
    }, 10000);
}

/* ============================================================
   DISPATCH QUEUE & MODEL LOAD STATUS — task #2522
   All values are escaped with escHtml() before DOM insertion.
   ============================================================ */
function loadQueueStatus() {
    fetch('/tools/department-hq/api/fleet/queue-status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var total = (data.queued || 0) + (data.running || 0);

            // Badge
            var badge = document.getElementById('queueTotalBadge');
            if (badge) {
                if (total === 0) {
                    badge.textContent = 'idle';
                    badge.style.color = 'var(--dhq-text-dim)';
                } else {
                    badge.textContent = data.queued + ' queued · ' + data.running + ' running';
                    badge.style.color = data.running > 0 ? '#10b981' : '#f59e0b';
                }
            }

            // Unified platform queue — Dispatch + Media Studio + F.O.R.G.E. + Bridge
            var qp = document.getElementById('queueItemsPanel');
            if (qp) {
                qp.textContent = '';
                var pq = (data.platform_queues && data.platform_queues.length) ? data.platform_queues : (data.items || []);
                if (pq.length === 0) {
                    var idle = document.createElement('span');
                    idle.style.cssText = 'color:var(--dhq-text-dim);font-style:italic;';
                    idle.textContent = 'All queues idle';
                    qp.appendChild(idle);
                } else {
                    var _srcColor = { dispatch:'#f59e0b', media:'#00bcd4', forge:'#8b5cf6', bridge:'#10b981' };
                    var _srcIcon  = { dispatch:'🤖', media:'🎨', forge:'⚖', bridge:'🔗' };
                    var _active = function(s) { return s==='running'||s==='in_progress'||s==='generating'; };
                    // Running items first
                    pq.slice().sort(function(a,b){ return (_active(a.status)?0:1) - (_active(b.status)?0:1); })
                    .forEach(function(item) {
                        var sc = _srcColor[item.source_key] || '#888';
                        var active = _active(item.status);
                        var statusCol = active ? '#10b981' : sc;
                        var row = document.createElement('div');
                        row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);';
                        // Status dot
                        var dot = document.createElement('span');
                        dot.style.cssText = 'width:7px;height:7px;border-radius:50%;flex-shrink:0;background:'+statusCol+';'+(active?'box-shadow:0 0 4px '+statusCol+';':'');
                        // Source badge
                        var src = document.createElement('span');
                        src.style.cssText = 'font-size:0.62rem;padding:1px 5px;border-radius:3px;background:'+sc+'22;color:'+sc+';flex-shrink:0;white-space:nowrap;';
                        src.textContent = (_srcIcon[item.source_key]||'') + ' ' + item.source;
                        // Capability / model
                        var cap = document.createElement('span');
                        cap.style.cssText = 'color:var(--dhq-text-main);font-size:0.72rem;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;';
                        cap.textContent = item.model ? item.model + ' · ' + item.capability : item.capability;
                        row.appendChild(dot); row.appendChild(src); row.appendChild(cap);
                        if (item.module) {
                            var mod = document.createElement('span');
                            mod.style.cssText = 'color:#555;font-size:0.62rem;font-family:"IBM Plex Mono",monospace;flex-shrink:0;';
                            mod.textContent = '['+item.module+']';
                            row.appendChild(mod);
                        }
                        // Count + status
                        var cnt = document.createElement('span');
                        cnt.style.cssText = 'font-weight:600;font-size:0.68rem;color:'+statusCol+';flex-shrink:0;';
                        cnt.textContent = item.count + '×';
                        var st = document.createElement('span');
                        st.style.cssText = 'font-size:0.62rem;color:var(--dhq-text-dim);text-transform:uppercase;flex-shrink:0;';
                        st.textContent = item.status;
                        row.appendChild(cnt); row.appendChild(st);
                        qp.appendChild(row);
                    });
                }
            }

            // Loaded models
            var countEl = document.getElementById('loadedModelCount');
            if (countEl) countEl.textContent = data.loaded && data.loaded.length ? data.loaded.length + ' loaded' : '';
            var lp = document.getElementById('loadedModelsPanel');
            if (lp) {
                lp.textContent = '';
                if (!data.loaded || data.loaded.length === 0) {
                    var none = document.createElement('span');
                    none.style.cssText = 'color:var(--dhq-text-dim);font-style:italic;';
                    none.textContent = 'No models currently loaded in VRAM';
                    lp.appendChild(none);
                } else {
                    data.loaded.forEach(function(m) {
                        var isFleet = m.node && m.node !== 'Hub';
                        var row = document.createElement('div');
                        row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);';
                        var dot = document.createElement('span');
                        dot.style.cssText = 'width:8px;height:8px;border-radius:50%;flex-shrink:0;background:' + (isFleet ? '#00bcd4' : '#10b981') + ';';
                        var name = document.createElement('span');
                        name.style.cssText = 'color:var(--dhq-text-main);font-family:"IBM Plex Mono",monospace;font-size:0.75rem;';
                        name.textContent = m.name;
                        var nodeBadge = document.createElement('span');
                        nodeBadge.style.cssText = 'font-size:0.67rem;font-family:"IBM Plex Mono",monospace;color:' + (isFleet ? '#00bcd4' : 'var(--dhq-text-dim)') + ';';
                        nodeBadge.textContent = m.node || 'Hub';
                        var vram = document.createElement('span');
                        vram.style.cssText = 'margin-left:auto;color:var(--dhq-text-dim);font-size:0.72rem;';
                        vram.textContent = m.vram_gb > 0 ? m.vram_gb + ' GB' : 'CPU';
                        row.appendChild(dot); row.appendChild(name); row.appendChild(nodeBadge); row.appendChild(vram);
                        lp.appendChild(row);
                    });
                }
            }
        })
        .catch(function() {});
}

function stopFleetRefresh() {
    if (_fleetRefreshInterval) {
        clearInterval(_fleetRefreshInterval);
        _fleetRefreshInterval = null;
    }
}

/* ============================================================
   CLUSTER ACTIVITY — live task routing across nodes
   Polls /api/fleet/cluster-activity every 10s (via startFleetRefresh).
   ============================================================ */
function loadClusterActivity() {
    function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
    fetch('/tools/department-hq/api/fleet/cluster-activity')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var grid = document.getElementById('clusterNodesGrid');
            var logEl = document.getElementById('clusterDispatchLog');
            var badge = document.getElementById('clusterActivityBadge');
            if (!grid) return;

            // online_nodes is now the single source of truth (backend merged hub + backlog + activity)
            var nodeMap = {};
            (data.online_nodes || []).forEach(function(n) {
                nodeMap[n.node_id] = n;
            });

            // last_run_by_node from backend (bridge_jobs — covers all fleet history)
            // supplemented by dispatch_log for queue-based dispatches
            var lastRunByNode = data.last_run_by_node || {};
            (data.dispatch_log || []).forEach(function(e) {
                var node = e.node || 'Hub';
                if (e.node && e.node !== 'Hub' && (!lastRunByNode[node] ||
                    (e.ts && lastRunByNode[node].ts && e.ts > lastRunByNode[node].ts))) {
                    lastRunByNode[node] = e;
                }
            });

            // throughput_by_node from task_execution_log.node_used_id (PR #802 attribution)
            var throughputByNode = data.throughput_by_node || {};
            var throughputTotal = data.throughput_total || { rows_5m: 0, rate_per_min: 0, rate_per_sec: 0 };

            var totalActive = 0;
            grid.innerHTML = '';
            Object.keys(nodeMap).forEach(function(nid) {
                var n = nodeMap[nid];
                var nodeName = n.node_name || n.name || nid;
                // Real-time activity (task_execution_log, authoritative)
                var active60s = n.active_60s || 0;
                var dispatches5m = n.dispatches_5m || 0;
                var successRate = n.success_rate || 0;
                // CPU pre-queue backlog (may be stale if drain worker is behind)
                var backlog = n.backlog || 0;
                var isActive = dispatches5m > 0;
                totalActive += active60s > 0 ? 1 : 0; // count nodes with work in last 60s

                var card = document.createElement('div');
                card.style.cssText = 'background:rgba(0,0,0,0.3);border:1px solid ' + (isActive ? '#10b981' : 'rgba(255,255,255,0.1)') + ';border-radius:6px;padding:10px 12px;min-width:0;overflow:hidden;';

                // Hardware label: GPU+CPU for GPU nodes, CPU-only for pure-CPU nodes
                var hwLabel = n.gpu
                    ? '<span style="margin-left:auto;font-size:0.6rem;color:#a78bfa;letter-spacing:1px;">GPU</span>'
                      + '<span style="font-size:0.6rem;color:var(--dhq-text-dim);letter-spacing:1px;">+CPU</span>'
                    : '<span style="margin-left:auto;font-size:0.6rem;color:var(--dhq-text-dim);letter-spacing:1px;">CPU</span>';
                var header = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">'
                    + '<span style="width:8px;height:8px;border-radius:50%;background:' + (n.status === 'online' ? (isActive ? '#10b981' : '#00bcd4') : '#ef4444') + ';flex-shrink:0;' + (isActive ? 'box-shadow:0 0 6px #10b981;' : '') + '"></span>'
                    + '<span style="font-family:Antonio,sans-serif;font-size:0.8rem;letter-spacing:1px;color:var(--dhq-text-main);">' + esc(nodeName) + '</span>'
                    + hwLabel
                    + '</div>';

                // Activity counts: 5-min window is primary (60s is too narrow — tasks take 15-30s each)
                var okPct = dispatches5m > 0 ? Math.round(successRate * 100) : null;
                var okBadge = okPct !== null
                    ? ' <span style="color:' + (okPct >= 90 ? '#10b981' : (okPct >= 70 ? '#f59e0b' : '#ef4444')) + ';">' + okPct + '% ok</span>'
                    : '';
                var hotDot = active60s > 0 ? ' <span style="color:#10b981;" title="active in last 60s">●</span>' : '';
                var counts = '<div style="display:flex;gap:10px;font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;margin-bottom:5px;flex-wrap:wrap;">'
                    + '<span style="color:' + (dispatches5m > 0 ? '#00bcd4' : 'var(--dhq-text-dim)') + ';">⚡ ' + dispatches5m + '/5m' + hotDot + '</span>'
                    + (backlog > 0 ? '<span style="color:#f59e0b;" title="staged in CPU pre-queue">⏳ ' + backlog + ' staged</span>' : '')
                    + okBadge
                    + '</div>';

                // Throughput rate
                var ratePerMin = dispatches5m > 0 ? (dispatches5m / 5).toFixed(1) : '0.0';
                var throughputLine = '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;margin-bottom:5px;color:' + (dispatches5m > 0 ? '#00bcd4' : 'var(--dhq-text-dim)') + ';">'
                    + '▲ ' + ratePerMin + ' disp/min'
                    + '</div>';

                // Active agents (last 60s from task_execution_log)
                var taskList = '';
                if (n.active_agents) {
                    n.active_agents.split(', ').slice(0, 3).forEach(function(agentName) {
                        taskList += '<div style="font-size:0.68rem;color:#10b981;padding:1px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                            + '→ ' + esc(agentName.trim()) + '</div>';
                    });
                }
                // Tasks from queue backlog (secondary — may be stale)
                if (!taskList) {
                    (n.tasks || []).slice(0, 2).forEach(function(t) {
                        taskList += '<div style="font-size:0.68rem;color:#f59e0b;padding:1px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'
                            + '→ ' + esc(t.agent || '?') + ' · ' + esc(t.capability || '') + '</div>';
                    });
                }
                // Fallback: last run from bridge_jobs
                if (!taskList) {
                    var last = lastRunByNode[nodeName];
                    if (last && last.agent) {
                        var ago = '';
                        if (last.ts) {
                            var diff = Math.round((Date.now() - new Date(last.ts)) / 60000);
                            ago = diff < 1 ? ' just now' : ' ' + diff + 'm ago';
                        }
                        taskList = '<div style="font-size:0.67rem;color:var(--dhq-text-dim);">'
                            + '<span style="color:#00bcd4;">' + esc(last.agent) + '</span>'
                            + ' · ' + esc(last.capability || '') + ago + '</div>';
                    } else {
                        taskList = '<span style="font-size:0.68rem;color:var(--dhq-text-dim);font-style:italic;">idle</span>';
                    }
                }

                // Roster agents assigned to this node (from node_agents + agents tables)
                var rosterHtml = '';
                var roster = n.roster_agents || [];
                if (roster.length > 0) {
                    rosterHtml = '<div style="margin-top:5px;padding-top:5px;border-top:1px solid rgba(255,255,255,0.05);font-size:0.63rem;color:var(--dhq-text-dim);">';
                    roster.slice(0, 4).forEach(function(a) {
                        var dot = a.shift_state === 'active' ? '<span style="color:#10b981;">●</span>' : '<span style="color:#555;">○</span>';
                        rosterHtml += dot + ' ' + esc(a.name || a.display_name || '') + ' ';
                    });
                    if (roster.length > 4) rosterHtml += '<span style="color:#555;">+' + (roster.length - 4) + '</span>';
                    rosterHtml += '</div>';
                }

                card.innerHTML = header + counts + throughputLine + taskList + rosterHtml;
                grid.appendChild(card);
            });

            if (badge) {
                while (badge.firstChild) badge.removeChild(badge.firstChild);
                var totalOnline = Object.keys(nodeMap).length;
                var badgeText = totalOnline + ' online';
                if (totalActive > 0) badgeText += ' · ' + totalActive + ' dispatching';
                badge.appendChild(document.createTextNode(badgeText));
                if ((throughputTotal.rows_5m || 0) > 0) {
                    badge.appendChild(document.createTextNode(' · '));
                    var rateSpan = document.createElement('span');
                    rateSpan.style.color = '#00bcd4';
                    rateSpan.textContent = '▲ ' + (throughputTotal.rate_per_sec || 0).toFixed(2) + ' disp/s';
                    badge.appendChild(rateSpan);
                    badge.appendChild(document.createTextNode(' '));
                    var minSpan = document.createElement('span');
                    minSpan.style.color = 'var(--dhq-text-dim)';
                    minSpan.textContent = '(' + (throughputTotal.rate_per_min || 0).toFixed(1) + '/min)';
                    badge.appendChild(minSpan);
                }
            }

            // Dispatch log — consecutive failures for same agent+capability are grouped
            if (logEl) {
                logEl.textContent = '';
                var log = data.dispatch_log || [];
                if (!log.length) {
                    var noLog = document.createElement('span');
                    noLog.style.cssText = 'color:var(--dhq-text-dim);font-style:italic;font-size:0.72rem;';
                    noLog.textContent = 'No recent dispatches';
                    logEl.appendChild(noLog);
                } else {
                    var displayed = 0;
                    var idx = 0;
                    while (idx < log.length && displayed < 15) {
                        var e = log[idx];
                        var ok = e.success !== false;
                        var ts = e.ts ? new Date((e.ts.endsWith('Z')||e.ts.includes('+'))?e.ts:e.ts+'Z').toLocaleTimeString('en-CA', {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
                        var row = document.createElement('div');
                        row.style.cssText = 'padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04);display:flex;gap:8px;align-items:center;';

                        var tsEl = document.createElement('span');
                        tsEl.style.cssText = 'color:var(--dhq-text-dim);font-size:0.65rem;flex-shrink:0;';
                        tsEl.textContent = ts;

                        var iconEl = document.createElement('span');
                        iconEl.style.cssText = 'font-size:0.68rem;flex-shrink:0;color:' + (ok ? '#10b981' : '#ef4444') + ';';
                        iconEl.textContent = ok ? '✓' : '✗';

                        if (!ok) {
                            // Count consecutive failures for same agent+capability
                            var failKey = (e.agent || '') + '|' + (e.capability || '');
                            var failCount = 1;
                            while (idx + failCount < log.length) {
                                var nx = log[idx + failCount];
                                if (nx.success === false && ((nx.agent || '') + '|' + (nx.capability || '')) === failKey) {
                                    failCount++;
                                } else { break; }
                            }
                            var agentCapEl = document.createElement('span');
                            agentCapEl.style.cssText = 'color:#ef4444;font-size:0.7rem;';
                            agentCapEl.textContent = (e.agent || '?') + ' · ' + (e.capability || '');
                            row.appendChild(tsEl); row.appendChild(iconEl); row.appendChild(agentCapEl);
                            if (failCount > 1) {
                                var badge = document.createElement('span');
                                badge.style.cssText = 'background:#ef444433;color:#ef4444;font-size:0.65rem;padding:1px 5px;border-radius:3px;';
                                badge.textContent = '×' + failCount + ' failures';
                                row.appendChild(badge);
                            }
                            idx += failCount;
                        } else {
                            var agentEl = document.createElement('span');
                            agentEl.style.cssText = 'color:var(--dhq-text-main);font-size:0.7rem;';
                            agentEl.textContent = e.agent || '?';
                            var arrEl = document.createElement('span');
                            arrEl.style.cssText = 'color:var(--dhq-text-dim);font-size:0.68rem;';
                            arrEl.textContent = '→';
                            var nodeEl = document.createElement('span');
                            nodeEl.style.cssText = 'color:#00bcd4;font-size:0.68rem;';
                            nodeEl.textContent = e.node || 'Hub';
                            var capEl = document.createElement('span');
                            capEl.style.cssText = 'color:var(--dhq-text-dim);font-size:0.65rem;margin-left:auto;';
                            capEl.textContent = e.capability || '';
                            // Module source badge — dim, small, right-aligned
                            var srcEl = document.createElement('span');
                            var srcShort = (e.source || '').replace(/^(wtf_dhq_|wtf_|platform_|archie_)/,'').split('_')[0];
                            srcEl.style.cssText = 'color:#555;font-size:0.6rem;font-family:"IBM Plex Mono",monospace;';
                            if (srcShort) srcEl.textContent = '[' + srcShort + ']';
                            row.appendChild(tsEl); row.appendChild(iconEl); row.appendChild(agentEl);
                            row.appendChild(arrEl); row.appendChild(nodeEl); row.appendChild(capEl);
                            if (srcShort) row.appendChild(srcEl);
                            idx++;
                        }
                        logEl.appendChild(row);
                        displayed++;
                    }
                }
            }
        })
        .catch(function() {});
    // Sync toggle state with server on each load
    fetch('/tools/department-hq/api/fleet/routing-enabled')
        .then(function(r) { return r.json(); })
        .then(function(d) { _applyRoutingToggle(d.enabled !== false); })
        .catch(function() {});
}

function _applyRoutingToggle(enabled) {
    var cb = document.getElementById('fleetRoutingToggle');
    var slider = document.getElementById('fleetRoutingSlider');
    var thumb = document.getElementById('fleetRoutingThumb');
    if (!cb) return;
    cb.checked = enabled;
    if (slider) slider.style.background = enabled ? '#10b981' : '#444';
    if (thumb) thumb.style.left = enabled ? '19px' : '3px';
}

function toggleFleetRouting(enabled) {
    _applyRoutingToggle(enabled);
    fetch('/tools/department-hq/api/fleet/routing-toggle', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled: enabled})
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (!d.success) { _applyRoutingToggle(!enabled); } // revert on error
    })
    .catch(function() { _applyRoutingToggle(!enabled); });
}

function _applyDispatchMode(mode) {
    ['auto', 'news', 'platform'].forEach(function(m) {
        var btn = document.getElementById('fleetMode' + m.charAt(0).toUpperCase() + m.slice(1));
        if (!btn) return;
        var active = m === mode;
        btn.style.background = active ? 'rgba(0,188,212,0.2)' : 'none';
        btn.style.borderColor = active ? '#00bcd4' : 'rgba(255,255,255,0.2)';
        btn.style.color = active ? '#00bcd4' : 'var(--dhq-text-dim)';
    });
}

function loadDispatchMode() {
    fetch('/tools/department-hq/api/fleet/dispatch-mode')
        .then(function(r) { return r.json(); })
        .then(function(d) { if (d.success) _applyDispatchMode(d.mode || 'auto'); })
        .catch(function() {});
}

function setFleetDispatchMode(mode) {
    _applyDispatchMode(mode);  // optimistic UI
    fetch('/tools/department-hq/api/fleet/dispatch-mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode})
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.success) {
            _applyDispatchMode(d.mode);
            var label = mode === 'news' ? '📰 NEWS MODE — WTF agents → outpost-us, platform → Starship'
                      : mode === 'platform' ? '🖥 PLATFORM MODE — platform agents → Starship-246 only'
                      : '✓ AUTO — balanced fleet-first routing';
            console.log('[Fleet] Dispatch profile:', label);
        }
    })
    .catch(function() {});
}

function initFleetMap() {
    if (fleetMap) return;
    var el = document.getElementById('fleetMap');
    if (!el) return;

    fleetMap = L.map('fleetMap', {
        center: [42, -95],
        zoom: 4,
        minZoom: 2,
        maxZoom: 12,
        zoomControl: true,
        attributionControl: false,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '',
        subdomains: 'abcd',
    }).addTo(fleetMap);

    _initSonarStyles();
    fleetMap.on('moveend zoomend', updateOffscreenBlips);

    _initFleetFpsOverlay();

    loadFleetData();
    loadCloudProviders();
}

var fleetFpsRafId = null;
function _initFleetFpsOverlay() {
    var mapEl = document.getElementById('fleetMap');
    if (!mapEl || mapEl.querySelector('.fleet-fps-overlay')) return;

    var pill = document.createElement('div');
    pill.className = 'fleet-fps-overlay';
    pill.style.cssText = 'position:absolute;bottom:8px;right:8px;z-index:1000;pointer-events:none;'
        + 'background:rgba(10,16,22,0.75);border:1px solid rgba(0,220,170,0.30);border-radius:10px;'
        + 'padding:2px 8px;font-family:\'IBM Plex Mono\',monospace;font-size:0.62rem;letter-spacing:1px;'
        + 'color:#00dcaa;text-shadow:0 0 4px rgba(0,220,170,0.4);';
    pill.textContent = '-- fps';
    mapEl.appendChild(pill);

    var frames = 0;
    var lastSample = performance.now();
    function tick(now) {
        frames++;
        if (now - lastSample >= 1000) {
            var fps = Math.round((frames * 1000) / (now - lastSample));
            // Re-fetch pill in case map was torn down/rebuilt
            var p = mapEl.querySelector('.fleet-fps-overlay');
            if (p) {
                p.textContent = fps + ' fps';
                p.style.color = fps >= 50 ? '#00dcaa' : (fps >= 30 ? '#f59e0b' : '#ef4444');
            }
            frames = 0;
            lastSample = now;
        }
        fleetFpsRafId = requestAnimationFrame(tick);
    }
    if (fleetFpsRafId) cancelAnimationFrame(fleetFpsRafId);
    fleetFpsRafId = requestAnimationFrame(tick);
}

function _initSonarStyles() {
    if (document.getElementById('fleet-sonar-styles')) return;
    var style = document.createElement('style');
    style.id = 'fleet-sonar-styles';
    var css = '.fleet-sonar-ring{position:absolute;border-radius:50%;border:1px dashed rgba(0,220,170,0.40);pointer-events:none;top:50%;left:50%;transform:translate(-50%,-50%);z-index:800;}';
    css += '.fleet-sonar-ring-outer{position:absolute;border-radius:50%;border:1px solid rgba(0,220,170,0.15);pointer-events:none;top:50%;left:50%;transform:translate(-50%,-50%);z-index:799;}';
    css += '.fleet-sonar-sweep{position:absolute;border-radius:50%;pointer-events:none;top:50%;left:50%;transform:translate(-50%,-50%);animation:sonar-sweep 8s linear infinite;z-index:800;}';
    css += '@keyframes sonar-sweep{from{transform:translate(-50%,-50%) rotate(0deg);}to{transform:translate(-50%,-50%) rotate(360deg);}}';
    css += '.fleet-sonar-blip{position:absolute;transform:translate(-50%,-50%);cursor:pointer;z-index:900;pointer-events:all;border-radius:50%;background:rgba(10,16,22,0.92);border:2px solid rgba(0,220,170,0.85);display:flex;align-items:center;justify-content:center;width:26px;height:26px;box-shadow:0 0 8px rgba(0,220,170,0.6);transition:box-shadow 0.2s;}';
    css += '.fleet-sonar-blip:hover{box-shadow:0 0 16px rgba(0,220,170,1.0);border-color:#00dcaa;}';
    style.textContent = css;
    document.head.appendChild(style);
}

function updateOffscreenBlips() {
    var mapEl = document.getElementById('fleetMap');
    if (!mapEl || !fleetMap) return;

    mapEl.querySelectorAll('.fleet-sonar-ring,.fleet-sonar-ring-outer,.fleet-sonar-sweep,.fleet-sonar-blip').forEach(function(e) { e.remove(); });

    // Hide sonar overlay when zoomed in — blips would overlap real map content
    if (fleetMap.getZoom() > 6) return;

    var W = mapEl.offsetWidth;
    var H = mapEl.offsetHeight;
    var cx = W / 2;
    var cy = H / 2;
    var r = Math.min(W, H) * 0.42;

    var ring = document.createElement('div');
    ring.className = 'fleet-sonar-ring';
    ring.style.width = (r * 2) + 'px';
    ring.style.height = (r * 2) + 'px';
    mapEl.appendChild(ring);

    var ringOuter = document.createElement('div');
    ringOuter.className = 'fleet-sonar-ring-outer';
    ringOuter.style.width = (r * 2 + 30) + 'px';
    ringOuter.style.height = (r * 2 + 30) + 'px';
    mapEl.appendChild(ringOuter);

    var sweep = document.createElement('div');
    sweep.className = 'fleet-sonar-sweep';
    sweep.style.width = (r * 2) + 'px';
    sweep.style.height = (r * 2) + 'px';
    sweep.style.background = 'conic-gradient(rgba(0,220,170,0.18) 0deg,transparent 55deg,transparent 360deg)';
    mapEl.appendChild(sweep);

    var bounds = fleetMap.getBounds();
    fleetMarkers.forEach(function(marker) {
        var ll = marker.getLatLng();
        if (bounds.contains(ll)) return;

        var pt = fleetMap.latLngToContainerPoint(ll);
        var angle = Math.atan2(pt.y - cy, pt.x - cx);
        var bx = Math.round(cx + r * Math.cos(angle));
        var by = Math.round(cy + r * Math.sin(angle));

        var blip = document.createElement('div');
        blip.className = 'fleet-sonar-blip';
        blip.style.left = bx + 'px';
        blip.style.top = by + 'px';
        blip.title = 'Navigate to marker';

        var markerEl = marker.getElement();
        var srcImg = markerEl ? markerEl.querySelector('img') : null;
        if (srcImg) {
            var blipImg = document.createElement('img');
            blipImg.src = srcImg.src;
            blipImg.style.cssText = 'width:14px;height:14px;object-fit:contain;border-radius:2px;';
            blip.appendChild(blipImg);
        } else {
            var dot = document.createElement('span');
            dot.style.cssText = 'font-size:8px;color:#00dcaa;';
            dot.textContent = '●';
            blip.appendChild(dot);
        }

        blip.addEventListener('click', (function(latlng) {
            return function() { fleetMap.panTo(latlng); };
        })(ll));
        mapEl.appendChild(blip);
    });
}

function loadFleetData() {
    fetch('/tools/department-hq/api/fleet-map')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) { console.error('Fleet map error:', data.error); return; }
        renderFleetPins(data);
        updateFleetStats(data);
    })
    .catch(function(e) {
        console.error('Fleet map load failed:', e);
    });
}

var PROVIDER_STYLES = {
    'openai':      { color: '#10a37f', bg: 'rgba(16,163,127,0.3)', label: 'AI' },
    'anthropic':   { color: '#d4a27f', bg: 'rgba(212,162,127,0.3)', label: 'An' },
    'google':      { color: '#4285f4', bg: 'rgba(66,133,244,0.3)', label: 'G' },
    'gemini':      { color: '#4285f4', bg: 'rgba(66,133,244,0.3)', label: 'Ge' },
    'mistral':     { color: '#ff7000', bg: 'rgba(255,112,0,0.3)', label: 'Mi' },
    'cohere':      { color: '#39594d', bg: 'rgba(57,89,77,0.3)', label: 'Co' },
    'grok':        { color: '#1da1f2', bg: 'rgba(29,161,242,0.3)', label: 'X' },
    'together':    { color: '#6366f1', bg: 'rgba(99,102,241,0.3)', label: 'To' },
    'huggingface': { color: '#ff9d00', bg: 'rgba(255,157,0,0.3)', label: 'HF' },
    'cloudflare':  { color: '#f38020', bg: 'rgba(243,128,32,0.3)', label: 'CF' },
    'ollama':      { color: '#ffffff', bg: 'rgba(255,255,255,0.2)', label: 'Ol' },
    'groq':        { color: '#f55036', bg: 'rgba(245,80,54,0.3)', label: 'Gq' },
    'deepseek':    { color: '#4d6bfe', bg: 'rgba(77,107,254,0.3)', label: 'DS' },
    'cerebras':    { color: '#00d4aa', bg: 'rgba(0,212,170,0.3)', label: 'Ce' },
};
var PROVIDER_DOMAINS = {
    'openai': 'openai.com', 'anthropic': 'anthropic.com', 'google': 'google.com',
    'gemini': 'deepmind.google', 'mistral': 'mistral.ai', 'cohere': 'cohere.com',
    'grok': 'x.ai', 'together': 'together.ai', 'huggingface': 'huggingface.co',
    'cloudflare': 'cloudflare.com', 'ollama': 'ollama.com', 'groq': 'groq.com',
    'deepseek': 'deepseek.com', 'cerebras': 'cerebras.ai', 'runpod': 'runpod.io',
    'perplexity': 'perplexity.ai', 'replicate': 'replicate.com', 'fireworks': 'fireworks.ai',
};

function jitterClusteredProviders(providers) {
    var CLUSTER_DEG = 0.18;
    var JITTER_DEG = 0.22;
    var used = new Array(providers.length).fill(false);
    var result = providers.map(function(p) { return Object.assign({}, p); });

    providers.forEach(function(p, i) {
        if (used[i] || !p.lat || !p.lon) return;
        var cluster = [i];
        providers.forEach(function(q, j) {
            if (j === i || used[j] || !q.lat || !q.lon) return;
            var d = Math.sqrt(Math.pow(p.lat - q.lat, 2) + Math.pow(p.lon - q.lon, 2));
            if (d < CLUSTER_DEG) cluster.push(j);
        });
        if (cluster.length < 2) return;
        cluster.forEach(function(idx) { used[idx] = true; });
        var cLat = cluster.reduce(function(s, idx) { return s + providers[idx].lat; }, 0) / cluster.length;
        var cLon = cluster.reduce(function(s, idx) { return s + providers[idx].lon; }, 0) / cluster.length;
        var step = (2 * Math.PI) / cluster.length;
        cluster.forEach(function(idx, k) {
            result[idx].lat = cLat + JITTER_DEG * Math.sin(k * step);
            result[idx].lon = cLon + JITTER_DEG * Math.cos(k * step);
        });
    });
    return result;
}

function renderFleetIndex(data) {
    var panel = document.getElementById('fleetNodeIndex');
    if (!panel) return;
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    var hdr = document.createElement('div');
    hdr.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.6rem;letter-spacing:2px;color:rgba(0,220,170,0.5);margin-bottom:4px;';
    hdr.textContent = 'NODES';
    panel.appendChild(hdr);
    var entries = [];
    if (data.hub) entries.push({ label: data.hub.name || 'HUB', lat: data.hub.lat, lon: data.hub.lon, online: true });
    (data.nodes || []).forEach(function(n) {
        if (!n.lat || !n.lon) return; // skip nodes with no coordinates
        entries.push({ label: n.name || n.hostname || n.node_id || 'Node', lat: n.lat, lon: n.lon, online: n.status === 'online' });
    });
    entries.forEach(function(e, i) {
        panel.appendChild(buildIndexItem(i + 1, e.label, e.lat, e.lon, e.online, '#00dcaa'));
    });

    // CONTRACTORS section — wrapped so CSS can hide on mobile
    var contractors = (data.providers || []).filter(function(p) { return p.lat && p.lon; });
    if (contractors.length) {
        var contractorSection = document.createElement('div');
        contractorSection.id = 'fleetContractorSection';
        var chdr = document.createElement('div');
        chdr.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.6rem;letter-spacing:2px;color:rgba(249,115,22,0.5);margin-top:10px;margin-bottom:4px;';
        chdr.textContent = 'CONTRACTORS';
        contractorSection.appendChild(chdr);
        contractors.forEach(function(p, i) {
            var label = (p.provider_key || 'Unknown').toUpperCase();
            contractorSection.appendChild(buildIndexItem(i + 1, label, p.lat, p.lon, p.is_active, '#f97316'));
        });
        panel.appendChild(contractorSection);
    }
}

function buildIndexItem(num, label, lat, lon, active, accentColor) {
    var dot = active ? accentColor : '#6b7280';
    var border = active ? 'rgba(' + hexToRgb(accentColor) + ',0.2)' : 'rgba(255,255,255,0.06)';
    var item = document.createElement('div');
    item.style.cssText = 'display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:6px;border:1px solid ' + border + ';background:rgba(0,0,0,0.3);cursor:' + (lat && lon ? 'pointer' : 'default') + ';transition:border-color 0.15s;margin-bottom:4px;';
    var n = document.createElement('span');
    n.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;color:rgba(' + hexToRgb(accentColor) + ',0.4);min-width:14px;';
    n.textContent = num;
    var dot_el = document.createElement('span');
    dot_el.style.cssText = 'width:7px;height:7px;border-radius:50%;background:' + dot + ';flex-shrink:0;' + (active ? 'box-shadow:0 0 5px ' + dot + ';' : '');
    var lbl = document.createElement('span');
    lbl.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.62rem;color:#c0c0c0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:108px;';
    lbl.title = label; lbl.textContent = label;
    item.appendChild(n); item.appendChild(dot_el); item.appendChild(lbl);
    if (lat && lon) {
        (function(la, lo) {
            item.addEventListener('click', function() { fleetMap.setView([la, lo], 6, { animate: true }); });
            item.addEventListener('mouseenter', function() { item.style.borderColor = 'rgba(' + hexToRgb(accentColor) + ',0.5)'; item.style.background = 'rgba(' + hexToRgb(accentColor) + ',0.06)'; });
            item.addEventListener('mouseleave', function() { item.style.borderColor = border; item.style.background = 'rgba(0,0,0,0.3)'; });
        })(lat, lon);
    }
    return item;
}

function hexToRgb(hex) {
    var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    return r + ',' + g + ',' + b;
}

function renderFleetPins(data) {
    renderFleetIndex(data);
    fleetMarkers.forEach(function(m) { fleetMap.removeLayer(m); });
    fleetMarkers = [];

    if (data.hub) {
        var hub = data.hub;
        var marker = L.marker([hub.lat, hub.lon], {
            icon: L.divIcon({
                className: 'fleet-marker-hub',
                html: '<div style="width:40px;height:40px;border-radius:50%;border:2.5px solid #10b981;background:#0a1628;display:flex;align-items:center;justify-content:center;overflow:hidden;box-shadow:0 0 8px rgba(16,185,129,0.6);"><img src="/static/img/aries-logo.png" style="width:28px;height:28px;object-fit:contain;" onerror="this.outerHTML=\'<span style=font-size:16px>♈</span>\'"></div>',
                iconSize: [40, 40],
                iconAnchor: [20, 20],
            }),
        }).addTo(fleetMap);
        marker.bindPopup(buildFleetPopup('A.R.M.A.D.A. HUB', [
            ['Location', hub.city || 'Home Base'],
            ['Status', '<span style="color:#10b981;">ONLINE</span>'],
        ]), { className: 'fleet-popup' });
        fleetMarkers.push(marker);
    }

    (data.nodes || []).forEach(function(node) {
        if (!node.lat || !node.lon) return;
        var isOnline = node.status === 'online';
        var marker = L.marker([node.lat, node.lon], {
            icon: L.divIcon({
                className: 'fleet-marker-node ' + (isOnline ? '' : 'offline'),
                html: '<div style="width:34px;height:34px;border-radius:50%;border:2px solid ' + (isOnline ? '#a3e635' : '#6b7280') + ';background:#0a1628;display:flex;align-items:center;justify-content:center;overflow:hidden;' + (isOnline ? 'box-shadow:0 0 6px rgba(163,230,53,0.5);' : 'opacity:0.5;filter:grayscale(1);') + '"><img src="/static/img/aries-logo.png" style="width:24px;height:24px;object-fit:contain;" onerror="this.outerHTML=\'<span style=font-size:13px>♈</span>\'"></div>',
                iconSize: [34, 34],
                iconAnchor: [17, 17],
            }),
        }).addTo(fleetMap);
        marker.bindPopup(buildFleetPopup(node.name || node.hostname, [
            ['Type', node.deployment_mode || 'starship'],
            ['Status', isOnline ? '<span style="color:#10b981;">ONLINE</span>' : '<span style="color:#ef4444;">OFFLINE</span>'],
            ['GPU', node.gpu || 'Not reported'],
            ['VRAM', node.gpu_vram_gb ? node.gpu_vram_gb + ' GB' : '--'],
            ['RAM', node.ram ? node.ram + ' GB' : '--'],
        ]), { className: 'fleet-popup' });
        marker.on('click', function() { showNodeDetail(node); });
        fleetMarkers.push(marker);
    });

    jitterClusteredProviders(data.providers || []).forEach(function(prov) {
        if (!prov.lat || !prov.lon) return;
        var key = (prov.provider_key || '').toLowerCase();
        var style = PROVIDER_STYLES[key] || { color: '#f97316', label: (prov.provider_key || '?').charAt(0).toUpperCase() };
        var domain = PROVIDER_DOMAINS[key] || (key + '.com');
        var faviconUrl = 'https://www.google.com/s2/favicons?sz=32&domain=' + domain;
        var marker = L.marker([prov.lat, prov.lon], {
            icon: L.divIcon({
                className: 'fleet-marker-provider-custom ' + (prov.is_active ? '' : 'inactive'),
                html: '<div style="width:30px;height:30px;border-radius:6px;border:1.5px solid ' + style.color + ';background:#0d1117;display:flex;align-items:center;justify-content:center;overflow:hidden;' + (prov.is_active ? 'box-shadow:0 0 5px ' + style.color + '55;' : 'opacity:0.4;filter:grayscale(1);') + '"><img src="' + faviconUrl + '" style="width:20px;height:20px;object-fit:contain;" onerror="this.outerHTML=\'<span style=font-size:10px;color:' + style.color + '>' + style.label + '</span>\'"></div>',
                iconSize: [30, 30],
                iconAnchor: [15, 15],
            }),
        }).addTo(fleetMap);

        var budgetStr = prov.monthly_budget_usd
            ? '$' + (prov.current_month_cost_usd||0).toFixed(2) + ' / $' + prov.monthly_budget_usd.toFixed(2)
            : 'No budget set';

        marker.bindPopup(buildFleetPopup(prov.provider_key.toUpperCase(), [
            ['City', prov.city || '--'],
            ['Tier', prov.tier_position || '--'],
            ['Budget', budgetStr],
            ['Status', prov.is_active ? '<span style="color:#10b981;">ACTIVE</span>' : '<span style="color:#6b7280;">INACTIVE</span>'],
        ]), { className: 'fleet-popup' });
        fleetMarkers.push(marker);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
    updateOffscreenBlips();
}

function buildFleetPopup(title, rows) {
    var html = '<div class="fleet-popup-title">' + title + '</div>';
    rows.forEach(function(row) {
        html += '<div class="fleet-popup-row"><span class="fleet-popup-label">' + row[0] + '</span><span class="fleet-popup-value">' + row[1] + '</span></div>';
    });
    return html;
}

function updateFleetStats(data) {
    var nodeCount = (data.nodes || []).filter(function(n) { return n.status === 'online'; }).length;
    var provCount = (data.providers || []).filter(function(p) { return p.is_active; }).length;
    var nodeEl = document.getElementById('fleetStatNodes');
    var provEl = document.getElementById('fleetStatProviders');
    if (nodeEl) nodeEl.textContent = nodeCount + ' node' + (nodeCount !== 1 ? 's' : '') + ' online';
    if (provEl) provEl.textContent = provCount + ' provider' + (provCount !== 1 ? 's' : '') + ' active';
}

async function loadCloudProviders() {
    try {
        const resp = await fetch('/tools/department-hq/api/cloud-providers');
        const data = await resp.json();
        if (data.error) { console.error('Cloud providers error:', data.error); return; }

        const grid = document.getElementById('fleetProvidersGrid');
        if (!grid) return;

        const providers = data.providers || [];
        const countEl = document.getElementById('fleetProviderCount');
        if (countEl) countEl.textContent = providers.length;

        if (providers.length === 0) {
            grid.textContent = '';
            var emptyMsg = document.createElement('div');
            emptyMsg.style.cssText = 'text-align:center;color:#6b7280;padding:24px;';
            emptyMsg.textContent = 'No cloud providers configured';
            grid.appendChild(emptyMsg);
            return;
        }

        grid.textContent = '';
        providers.forEach(function(p) {
            var statusColor = p.status === 'active' ? '#10b981' : '#6b7280';
            var budgetPct = p.monthly_budget > 0
                ? Math.min(((p.monthly_usage || 0) / p.monthly_budget) * 100, 100).toFixed(0)
                : 0;
            var budgetColor = budgetPct > 80 ? '#ef4444' : budgetPct > 50 ? '#f59e0b' : '#10b981';

            var card = document.createElement('div');
            card.className = 'fleet-provider-card';

            // Header
            var header = document.createElement('div');
            header.className = 'fleet-provider-card-header';
            var nameSpan = document.createElement('span');
            nameSpan.className = 'fleet-provider-name';
            nameSpan.textContent = p.name;
            var statusSpan = document.createElement('span');
            statusSpan.className = 'fleet-provider-status';
            statusSpan.style.color = statusColor;
            statusSpan.textContent = (p.status || 'unknown').toUpperCase();
            header.appendChild(nameSpan);
            header.appendChild(statusSpan);
            card.appendChild(header);

            // Body rows
            var body = document.createElement('div');
            body.className = 'fleet-provider-card-body';
            [['Type', p.provider_type || 'cloud'], ['Tier', p.tier || 'free'],
             ['City', p.headquarters_city || '--'],
             ['Budget', '$' + (p.monthly_usage || 0).toFixed(2) + ' / $' + (p.monthly_budget || 0).toFixed(2)]
            ].forEach(function(pair) {
                var row = document.createElement('div');
                row.className = 'fleet-provider-row';
                var lbl = document.createElement('span');
                lbl.textContent = pair[0];
                var val = document.createElement('span');
                val.textContent = pair[1];
                row.appendChild(lbl);
                row.appendChild(val);
                body.appendChild(row);
            });

            // Budget bar
            if (p.monthly_budget > 0) {
                var barWrap = document.createElement('div');
                barWrap.className = 'fleet-provider-budget-bar';
                var barFill = document.createElement('div');
                barFill.style.cssText = 'width:' + budgetPct + '%;background:' + budgetColor + ';height:100%;border-radius:2px;';
                barWrap.appendChild(barFill);
                body.appendChild(barWrap);
            }

            // Capability tags
            var caps = document.createElement('div');
            caps.className = 'fleet-provider-caps';
            (p.capabilities || []).forEach(function(c) {
                var tag = document.createElement('span');
                tag.className = 'fleet-cap-tag';
                tag.textContent = c;
                caps.appendChild(tag);
            });
            body.appendChild(caps);
            card.appendChild(body);

            // Actions
            var actions = document.createElement('div');
            actions.className = 'fleet-provider-card-actions';
            var toggleBtn = document.createElement('button');
            toggleBtn.className = 'fleet-btn-sm';
            toggleBtn.textContent = p.status === 'active' ? 'Disable' : 'Enable';
            toggleBtn.addEventListener('click', function() { toggleCloudProvider(p.id); });
            actions.appendChild(toggleBtn);
            card.appendChild(actions);

            grid.appendChild(card);
        });
    } catch(e) {
        console.error('loadCloudProviders failed:', e);
    }
}

async function toggleCloudProvider(providerId) {
    try {
        const resp = await fetch('/tools/department-hq/api/cloud-providers/' + providerId + '/toggle', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            loadCloudProviders();
            loadFleetData();
        }
    } catch(e) {
        console.error('Toggle cloud provider failed:', e);
    }
}

function showNodeDetail(node) {
    var panel = document.getElementById('fleetDetailPanel');
    var titleEl = document.getElementById('fleetDetailTitle');
    var body = document.getElementById('fleetDetailBody');
    if (!panel || !titleEl || !body) return;

    titleEl.textContent = node.node_name || node.name || node.hostname;

    // Build detail content using DOM methods (trusted server data)
    body.textContent = '';
    var sections = [
        { title: 'Hardware', rows: [
            ['GPU', node.gpu_model || node.gpu || 'None'],
            ['VRAM', node.gpu_vram_gb ? node.gpu_vram_gb + ' GB' : '--'],
            ['RAM', (node.ram_gb || node.ram) ? (node.ram_gb || node.ram) + ' GB' : '--'],
            ['Region', node.region || '--']
        ]},
        { title: 'Network', rows: [
            ['Hostname', node.hostname || '--'],
            ['Mesh IP', node.mesh_ip || '--'],
            ['Mode', node.deployment_mode || '--']
        ]},
        { title: 'Status', rows: [
            ['Status', node.status || '--'],
            ['Last Heartbeat', node.last_heartbeat ? new Date((node.last_heartbeat.endsWith('Z') || node.last_heartbeat.includes('+')) ? node.last_heartbeat : node.last_heartbeat + 'Z').toLocaleString() : '--']
        ]}
    ];
    sections.forEach(function(sec) {
        var h = document.createElement('div');
        h.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;letter-spacing:2px;color:var(--cat-accent,#00ffff);margin:14px 0 6px;text-transform:uppercase;border-bottom:1px solid rgba(0,255,255,0.2);padding-bottom:4px;';
        h.textContent = sec.title;
        body.appendChild(h);
        sec.rows.forEach(function(r) {
            var row = document.createElement('div');
            row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);';
            var lbl = document.createElement('span');
            lbl.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;color:rgba(163,230,53,0.6);letter-spacing:1px;';
            lbl.textContent = r[0];
            var val = document.createElement('span');
            val.style.cssText = 'font-size:0.78rem;color:#e0e0e0;text-align:right;';
            val.textContent = r[1];
            row.appendChild(lbl);
            row.appendChild(val);
            body.appendChild(row);
        });
    });

    // Deployed Agents section with Department HQ cross-links
    var agents = node.agents || [];
    var agentHeader = document.createElement('div');
    agentHeader.className = 'detail-section-title';
    agentHeader.textContent = 'Deployed Agents (' + agents.length + ')';
    body.appendChild(agentHeader);

    if (agents.length === 0) {
        var noAgents = document.createElement('div');
        noAgents.className = 'detail-row';
        noAgents.style.opacity = '0.5';
        noAgents.textContent = 'No agents deployed';
        body.appendChild(noAgents);
    } else {
        agents.forEach(function(agent) {
            var row = document.createElement('div');
            row.className = 'detail-row';
            var link = document.createElement('a');
            link.href = '/tools/department-hq#agent-' + (agent.hub_agent_id || '');
            link.style.cssText = 'color:#8b5cf6;text-decoration:none;font-weight:500;cursor:pointer;';
            link.textContent = agent.display_name || 'Unknown';
            link.title = 'View in Department HQ';
            link.addEventListener('mouseenter', function() { link.style.textDecoration = 'underline'; });
            link.addEventListener('mouseleave', function() { link.style.textDecoration = 'none'; });
            row.appendChild(link);
            if (agent.department) {
                var dept = document.createElement('span');
                dept.className = 'detail-value';
                dept.style.cssText = 'font-size:0.7rem;opacity:0.6;margin-left:8px;';
                dept.textContent = agent.department;
                row.appendChild(dept);
            }
            body.appendChild(row);
        });

        // "View all in Department HQ" link
        var viewAll = document.createElement('a');
        viewAll.href = '/tools/department-hq#agents';
        viewAll.style.cssText = 'display:block;margin-top:8px;color:#8b5cf6;text-decoration:none;font-size:0.75rem;text-align:center;opacity:0.8;';
        viewAll.textContent = 'View all in Department HQ \u2192';
        viewAll.addEventListener('mouseenter', function() { viewAll.style.opacity = '1'; });
        viewAll.addEventListener('mouseleave', function() { viewAll.style.opacity = '0.8'; });
        body.appendChild(viewAll);
    }

    var modal = document.getElementById('fleetNodeModal');
    if (modal) modal.style.display = 'flex';
}

function closeFleetDetail() {
    var modal = document.getElementById('fleetNodeModal');
    if (modal) modal.style.display = 'none';
}

// Auto-init fleet map when tab becomes active
(function() {
    var _origSwitch = typeof switchBridgeTab === 'function' ? switchBridgeTab : null;
    if (_origSwitch) {
        switchBridgeTab = function(tab) {
            _origSwitch(tab);
            if (tab === 'fleet-map') {
                setTimeout(function() {
                    initFleetMap();
                    if (fleetMap) fleetMap.invalidateSize();
                    loadFleetUsage();
                    loadCloudProviders();
                    loadProviderManagement();
                    startFleetRefresh();
                }, 100);
            } else {
                stopFleetRefresh();
            }
        };
    }
})();

/* Fleet Usage Dashboard */
async function loadFleetUsage() {
    try {
        const [usageResp, mapResp] = await Promise.all([
            fetch('/tools/department-hq/api/fleet-usage'),
            fetch('/tools/department-hq/api/fleet-map'),
        ]);
        const usage = await usageResp.json();
        const map = await mapResp.json();

        // Summary cards
        const costEl = document.getElementById('fleetUsageCost');
        const provEl = document.getElementById('fleetUsageProviders');
        const callEl = document.getElementById('fleetUsageCalls');
        if (costEl) costEl.textContent = '$' + (usage.total_cost || 0).toFixed(2);
        if (provEl) {
            // Show "N cloud used / M registered" — distinct providers actually called (excl. local fleet)
            var distinctUsed = usage.distinct_providers || 0;
            var registeredCount = usage.registered_providers || 0;
            provEl.textContent = distinctUsed + ' cloud / ' + registeredCount + ' reg';
            provEl.title = distinctUsed + ' cloud provider(s) called in the last 30 days out of ' + registeredCount + ' registered';
        }
        if (callEl) {
            // Separate fleet (local Ollama) calls from cloud API calls
            var fleetCalls = usage.fleet_calls || 0;
            var cloudCalls = (usage.total_calls || 0) - fleetCalls;
            callEl.textContent = (usage.total_calls || 0).toLocaleString();
            callEl.title = cloudCalls + ' cloud · ' + fleetCalls + ' fleet (local Ollama)';
        }

        // Provider budget table
        const tbody = document.getElementById('fleetBudgetTableBody');
        if (!tbody) return;

        const providers = map.providers || [];
        if (providers.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#6b7280;">No providers configured</td></tr>';
            return;
        }

        tbody.innerHTML = providers
            .sort((a, b) => (b.current_month_cost_usd || 0) - (a.current_month_cost_usd || 0))
            .map(p => {
                const budget = p.monthly_budget_usd || 0;
                const spent = p.current_month_cost_usd || 0;
                const pct = budget > 0 ? Math.min((spent / budget) * 100, 100) : 0;
                const barColor = pct > 90 ? '#ef4444' : pct > 70 ? '#fbbf24' : '#10b981';
                const pKey = (p.provider_key || '').toLowerCase();
                const pStyle = PROVIDER_STYLES[pKey] || { color: '#f97316', bg: 'rgba(249,115,22,0.3)', label: (p.provider_key || '?').charAt(0).toUpperCase() };

                return `<tr>
                    <td><div class="fleet-provider-name">
                        <div class="fleet-provider-icon" style="background:${pStyle.bg};border-color:${pStyle.color};color:${pStyle.color}">${pStyle.label}</div>
                        ${p.provider_key || '--'}
                    </div></td>
                    <td>${p.tier_position || '--'}</td>
                    <td>${budget > 0 ? '$' + budget.toFixed(2) : '--'}</td>
                    <td>${spent > 0 ? '$' + spent.toFixed(2) : '$0.00'}</td>
                    <td>
                        <div class="fleet-budget-bar">
                            <div class="fleet-budget-bar-fill" style="width:${pct}%;background:${barColor}"></div>
                        </div>
                        ${pct > 0 ? pct.toFixed(0) + '%' : '--'}
                    </td>
                    <td><span class="fleet-status-dot ${p.is_active ? 'active' : 'inactive'}"></span></td>
                </tr>`;
            }).join('');

        // Cloud providers budget rows (Phase 4)
        try {
            const cloudResp = await fetch('/tools/department-hq/api/cloud-providers');
            const cloudData = await cloudResp.json();
            (cloudData.providers || []).forEach(function(p) {
                var budgetPct = p.monthly_budget > 0
                    ? ((p.monthly_usage || 0) / p.monthly_budget * 100).toFixed(0)
                    : '--';
                var statusColor = p.status === 'active' ? '#10b981' : '#6b7280';
                var row = document.createElement('tr');
                var cells = [p.name, p.tier || 'free',
                    '$' + (p.monthly_budget || 0).toFixed(2),
                    '$' + (p.monthly_usage || 0).toFixed(2),
                    budgetPct + (budgetPct !== '--' ? '%' : ''),
                    (p.status || '--').toUpperCase()];
                cells.forEach(function(text, i) {
                    var td = document.createElement('td');
                    td.textContent = text;
                    if (i === 5) td.style.color = statusColor;
                    row.appendChild(td);
                });
                tbody.appendChild(row);
            });
        } catch(e) {
            console.error('Cloud providers budget table error:', e);
        }
    } catch (e) {
        console.error('Fleet usage load failed:', e);
    }
}

/* Cloud Provider Management Panel */
async function loadProviderManagement() {
    try {
        const resp = await fetch('/tools/department-hq/api/providers');
        const data = await resp.json();
        const providers = data.providers || [];

        var countEl = document.getElementById('fleetProviderCount');
        if (countEl) countEl.textContent = providers.filter(function(p) { return p.is_active; }).length + ' active';

        var grid = document.getElementById('fleetProvidersGrid');
        if (!grid) return;

        if (providers.length === 0) {
            grid.innerHTML = '<div style="text-align:center;color:#6b7280;padding:24px;">No providers configured</div>';
            return;
        }

        grid.innerHTML = providers
            .sort(function(a, b) { return (a.tier_position || 99) - (b.tier_position || 99); })
            .map(function(p) {
                var key = (p.provider_key || '').toLowerCase();
                var style = PROVIDER_STYLES[key] || { color: '#f97316', bg: 'rgba(249,115,22,0.3)', label: key.charAt(0).toUpperCase() };
                var budget = parseFloat(p.monthly_budget_usd) || 0;
                var spent = parseFloat(p.current_month_cost_usd) || 0;
                var pct = budget > 0 ? Math.min((spent / budget) * 100, 100) : 0;
                var barColor = pct > 90 ? '#ef4444' : pct > 70 ? '#fbbf24' : '#10b981';
                var caps = (p.capabilities || []).slice(0, 4);

                return '<div class="fleet-prov-card ' + (p.is_active ? '' : 'inactive') + '">' +
                    '<div class="fleet-prov-header">' +
                        '<span class="fleet-prov-icon" style="background:' + style.bg + ';border-color:' + style.color + ';color:' + style.color + '">' + style.label + '</span>' +
                        '<span class="fleet-prov-name">' + (p.provider_key || '--') + '</span>' +
                        '<button class="fleet-prov-toggle ' + (p.is_active ? 'active' : '') + '" onclick="toggleProvider(\'' + p.provider_key + '\')">' +
                            (p.is_active ? 'ON' : 'OFF') +
                        '</button>' +
                    '</div>' +
                    '<div class="fleet-prov-details">' +
                        '<div class="fleet-prov-row"><span>Tier</span><span>' + (p.tier_position || '--') + '</span></div>' +
                        '<div class="fleet-prov-row"><span>Model</span><span>' + (p.default_model || '--') + '</span></div>' +
                        '<div class="fleet-prov-row"><span>Budget</span><span>$' + budget.toFixed(2) + '</span></div>' +
                        '<div class="fleet-prov-row">' +
                            '<span>Spent</span>' +
                            '<span>$' + spent.toFixed(2) + ' (' + pct.toFixed(0) + '%)</span>' +
                        '</div>' +
                        '<div class="fleet-prov-bar"><div class="fleet-prov-bar-fill" style="width:' + pct + '%;background:' + barColor + '"></div></div>' +
                    '</div>' +
                    '<div class="fleet-prov-caps">' + caps.map(function(c) { return '<span class="fleet-cap-tag">' + c + '</span>'; }).join('') + '</div>' +
                '</div>';
            }).join('');
    } catch (e) {
        console.error('Provider management load failed:', e);
    }
}

async function toggleProvider(key) {
    try {
        await fetch('/tools/department-hq/api/providers/' + key + '/toggle', { method: 'POST' });
        loadProviderManagement();
        loadFleetData();
        loadFleetUsage();
        loadCloudProviders();
    } catch (e) {
        console.error('Toggle provider failed:', e);
    }
}

var escapeHtml = typeof esc === "function" ? esc : function(s) { var d = document.createElement("div"); d.textContent = String(s == null ? "" : s); return d.innerHTML; };
function showToast(msg, type) { console.log("[" + (type||"info") + "] " + msg); }
// CONTRACTORS (External Providers) — Crew Sub-Tab
// ============================================================================

async function loadContractors() {
    try {
        var [provResp, modeResp] = await Promise.all([
            fetch('/tools/department-hq/api/external-providers'),
            fetch('/tools/department-hq/api/routing-mode')
        ]);
        if (!provResp.ok) throw new Error('Failed to load providers');
        var data = await provResp.json();
        var routingMode = 'full';
        if (modeResp.ok) {
            var modeData = await modeResp.json();
            if (modeData.success) routingMode = modeData.routing_mode || 'full';
        }
        renderContractors(data.providers || [], routingMode, {
            creed_total_24h: data.creed_total_24h || 0,
            creed_blocked_24h: data.creed_blocked_24h || 0
        });
        loadFleetUsage();
    } catch (e) {
        console.error('loadContractors error:', e);
        var grid = document.getElementById('contractors-grid');
        if (grid) grid.innerHTML = '<span class="briefing-muted">Failed to load contractors</span>';
    }
}

function renderContractors(providers, routingMode, creedData) {
    routingMode = routingMode || 'full';
    creedData = creedData || { creed_total_24h: 0, creed_blocked_24h: 0 };
    var creedBlocked = creedData.creed_blocked_24h || 0;
    // Dynamic cloud provider check — use is_cloud_proxy from API data
    var cloudProviders = providers.filter(function(p) { return p.is_cloud_proxy; }).map(function(p) { return p.provider; });
    var grid = document.getElementById('contractors-grid');
    var summaryEl = document.getElementById('contractors-summary');
    if (!grid) return;

    // Compute summary — use actual API field names
    var activeCount = 0;
    var totalCount = providers.length;
    var totalSpent = 0;
    var totalBudget = 0;
    providers.forEach(function(p) {
        if (p.is_active) activeCount++;
        totalSpent += (p.current_month_cost_usd || 0);
        totalBudget += (p.monthly_budget_usd || 0);
    });
    if (summaryEl) {
        summaryEl.textContent = activeCount + '/' + totalCount + ' active \u2014 $' + totalSpent.toFixed(2) + ' / $' + totalBudget.toFixed(0);
    }

    if (providers.length === 0) {
        grid.innerHTML = '<span class="briefing-muted">No external providers configured. Click "+ Add Provider" to get started.</span>';
        return;
    }

    var html = '';
    providers.forEach(function(p) {
        var providerName = escapeHtml(p.display_name || (p.name || p.provider || '').replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }));
        var providerKey = escapeHtml(p.provider || p.name || '');
        // Get first tier position from tier_positions map
        var tierPositions = p.tier_positions || {};
        var tierPosVals = Object.values(tierPositions);
        var tierPos = tierPosVals.length > 0 ? Math.min.apply(null, tierPosVals) : '--';
        var isEnabled = p.is_active !== false;
        var accountTier = p.account_tier || 'free';
        var tierLabel = accountTier.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
        var tierColor = accountTier === 'enterprise' ? '#a855f7' : accountTier === 'pro' ? '#f59e0b' : accountTier === 'pay_as_you_go' ? '#3b82f6' : '#6b7280';
        var monthlyBudget = p.monthly_budget_usd || 0;
        var currentCost = p.current_month_cost_usd || 0;
        var isOverBudget = monthlyBudget > 0 && currentCost > monthlyBudget;
        var statusClass = isOverBudget ? 'over-budget' : (isEnabled ? 'active' : 'inactive');
        var statusText = isOverBudget ? 'Over Budget' : (isEnabled ? 'Active' : 'Inactive');
        var budgetPct = monthlyBudget > 0 ? Math.min(100, (currentCost / monthlyBudget) * 100) : 0;
        var budgetFillClass = budgetPct > 100 ? 'over' : (budgetPct > 75 ? 'warning' : '');
        var isBlocked = (routingMode === 'local_only') ||
                        (routingMode === 'local_cloud' && cloudProviders.indexOf(p.provider) === -1);
        var blockedStyle = isBlocked ? 'position:relative;opacity:0.4;pointer-events:none;' : '';

        // Compute session/weekly totals for collapsed summary
        var pSess = 0, pSessLim = 0, pWkly = 0, pWklyLim = 0;
        (p.models || []).forEach(function(m) {
            var mw = m.usage_windows || {};
            pSess += (mw.session_2h != null ? mw.session_2h : 0);
            pSessLim += (mw.session_limit || 0);
            pWkly += (mw.weekly_7d != null ? mw.weekly_7d : 0);
            pWklyLim += (mw.weekly_limit || 0);
        });
        var sPct = pSessLim > 0 ? Math.min(100, Math.round(pSess / pSessLim * 100)) + '%' : '\u221e';
        var wPct = pWklyLim > 0 ? Math.min(100, Math.round(pWkly / pWklyLim * 100)) + '%' : '\u221e';
        var headerSummary = (pSess > 0 || pWkly > 0 || pSessLim > 0 || pWklyLim > 0) ? 's=' + sPct + ' / w=' + wPct : '';

        html += '<div class="contractor-firm"' + (blockedStyle ? ' style="' + blockedStyle + '"' : '') + '>';
        html += '<div class="contractor-firm-header" onclick="this.parentElement.classList.toggle(\'expanded\')">';
        html += '<i data-lucide="chevron-right" class="chevron-icon"></i>';
        html += '<span class="contractor-firm-name">' + providerName + '</span>';
        if (headerSummary) html += '<span class="contractor-header-summary">' + headerSummary + '</span>';
        html += '<span class="contractor-tier-badge">Tier ' + escapeHtml(String(tierPos)) + '</span>';
        html += '<span style="font-size:0.6rem;padding:1px 6px;border-radius:3px;border:1px solid ' + tierColor + ';color:' + tierColor + ';text-transform:uppercase;letter-spacing:0.5px;">' + escapeHtml(tierLabel) + '</span>';
        html += '<span class="contractor-status-badge ' + statusClass + '">' + statusText + '</span>';
        html += '<div class="budget-bar"><div class="budget-fill ' + budgetFillClass + '" style="width:' + budgetPct.toFixed(0) + '%"></div></div>';
        html += '<div class="contractor-firm-actions">';
        html += '<button class="contractor-btn-edit" onclick="event.stopPropagation();editProvider(\'' + providerKey + '\')">Edit</button>';
        html += '<button class="contractor-btn-toggle" onclick="event.stopPropagation();toggleProvider(\'' + providerKey + '\')">' + (isEnabled ? 'Disable' : 'Enable') + '</button>';
        html += '</div>';
        html += '</div>'; // header

        // Models body
        html += '<div class="contractor-firm-body">';
        // Auth & budget info row
        var authMethod = escapeHtml(p.auth_method || 'API key');
        var keyHint = p.key_hint ? escapeHtml(p.key_hint) : 'Not set';
        html += '<div style="display:flex;flex-wrap:wrap;gap:12px;padding:6px 8px;margin-bottom:8px;background:rgba(255,255,255,0.03);border-radius:4px;font-size:0.72rem;color:var(--archie-text-tertiary);">';
        html += '<span>Auth: <span style="color:var(--archie-cyan);">' + authMethod + '</span></span>';
        html += '<span>Key: <span style="color:' + (p.key_hint ? 'var(--archie-text-secondary)' : '#ff6b6b') + ';">' + keyHint + '</span></span>';
        html += '<span>Budget: <span style="color:var(--archie-text-secondary);">$' + monthlyBudget.toFixed(2) + '/mo</span></span>';
        html += '<span>Spent: <span style="color:var(--archie-text-secondary);">$' + currentCost.toFixed(2) + '</span></span>';
        html += '</div>';
        var models = p.models || [];
        if (models.length === 0) {
            html += '<span class="briefing-muted" style="font-size:0.7rem;">No models registered for this provider</span>';
        } else {
            html += '<div class="contractor-models-grid">';
            models.forEach(function(m) {
                var modelEnabled = m.enabled !== false;
                html += '<div class="contractor-model-card' + (modelEnabled ? '' : ' disabled') + '">';
                var mStats = m.stats_24h || {};
                var mTierPos = m.tier_position != null ? m.tier_position : tierPos;
                html += '<div class="contractor-model-name">' + escapeHtml(m.name || m.model_name || '') + '</div>';
                html += '<div class="contractor-model-meta">';
                html += '<span>Contract Worker \u00b7 Tier ' + escapeHtml(String(mTierPos)) + '</span>';
                html += '</div>';
                var mAlltime = m.stats_alltime || null;
                html += '<div class="model-stats">';
                html += '<div>Tasks/24h: <span class="stat-val">' + (mStats.requests != null ? mStats.requests : '0') + '</span></div>';
                html += '<div>Success: <span class="stat-val">' + (mStats.success_rate != null && mStats.requests > 0 ? parseFloat(mStats.success_rate).toFixed(0) + '%' : '--') + '</span></div>';
                html += '<div>Avg latency: <span class="stat-val">' + (mStats.avg_latency_ms != null && mStats.requests > 0 ? (parseFloat(mStats.avg_latency_ms) / 1000).toFixed(1) + 's' : '--') + '</span></div>';
                html += '<div>Cost/24h: <span class="stat-val">$' + (mStats.cost != null ? parseFloat(mStats.cost).toFixed(3) : '0.000') + '</span></div>';
                html += '</div>';
                if (mAlltime) {
                    var lastUsedStr = mAlltime.last_used ? ArchieTime.date(mAlltime.last_used) : '--';
                    html += '<div class="model-stats" style="margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,0.06);">';
                    html += '<div>Total: <span class="stat-val">' + mAlltime.requests + ' tasks</span></div>';
                    html += '<div>Success: <span class="stat-val">' + parseFloat(mAlltime.success_rate).toFixed(0) + '%</span></div>';
                    html += '<div>Last used: <span class="stat-val">' + lastUsedStr + '</span></div>';
                    html += '<div>Total cost: <span class="stat-val">$' + parseFloat(mAlltime.cost).toFixed(3) + '</span></div>';
                    html += '</div>';
                }
                var mWindows = m.usage_windows || null;
                if (mWindows) {
                    var sess = mWindows.session_2h != null ? mWindows.session_2h : 0;
                    var sessLimit = mWindows.session_limit || null;
                    var wkly = mWindows.weekly_7d != null ? mWindows.weekly_7d : 0;
                    var wklyLimit = mWindows.weekly_limit || null;
                    var sessPct = sessLimit ? Math.min(sess / sessLimit * 100, 100) : 0;
                    var sessPct = sessLimit ? Math.min(sess / sessLimit * 100, 100) : 0;
                    var wklyPct = wklyLimit ? Math.min(wkly / wklyLimit * 100, 100) : 0;
                    var barColor = function(pct) { return pct > 80 ? '#ff4444' : pct > 50 ? '#ffaa00' : '#22cc88'; };
                    var sessStr = sessLimit ? sess + ' / ' + sessLimit : sess + ' req';
                    var wklyStr = wklyLimit ? wkly + ' / ' + wklyLimit : wkly + ' req';
                    var sessPctStr = sessLimit ? Math.round(sessPct) + '%' : '';
                    var wklyPctStr = wklyLimit ? Math.round(wklyPct) + '%' : '';
                    html += '<div style="margin-top:4px;padding:5px 6px;border-top:1px solid rgba(255,255,255,0.06);display:flex;flex-direction:column;gap:5px;font-size:0.65rem;">';
                    // Session bar
                    html += '<div style="display:flex;align-items:center;gap:6px;">';
                    html += '<span style="color:rgba(255,255,255,0.5);min-width:58px;display:flex;align-items:center;gap:3px;"><i data-lucide="clock" style="width:10px;height:10px;"></i> Session</span>';
                    if (sessLimit) {
                        html += '<span style="color:' + barColor(sessPct) + ';min-width:28px;font-weight:600;font-size:0.6rem;">' + sessPctStr + '</span>';
                        html += '<div style="flex:1;height:10px;background:rgba(255,255,255,0.06);border-radius:5px;overflow:hidden;position:relative;">';
                        html += '<div style="height:100%;width:' + sessPct.toFixed(1) + '%;background:' + barColor(sessPct) + ';border-radius:5px;transition:width 0.4s ease;"></div>';
                        html += '</div>';
                    } else {
                        html += '<span style="color:var(--archie-cyan);font-size:0.6rem;flex:1;">Unlimited</span>';
                    }
                    html += '<span style="color:rgba(255,255,255,0.45);min-width:62px;text-align:right;font-size:0.6rem;">' + sessStr + '</span>';
                    html += '</div>';
                    // Weekly bar
                    html += '<div style="display:flex;align-items:center;gap:6px;">';
                    html += '<span style="color:rgba(255,255,255,0.5);min-width:58px;display:flex;align-items:center;gap:3px;"><i data-lucide="calendar" style="width:10px;height:10px;"></i> Weekly</span>';
                    if (wklyLimit) {
                        html += '<span style="color:' + barColor(wklyPct) + ';min-width:28px;font-weight:600;font-size:0.6rem;">' + wklyPctStr + '</span>';
                        html += '<div style="flex:1;height:10px;background:rgba(255,255,255,0.06);border-radius:5px;overflow:hidden;position:relative;">';
                        html += '<div style="height:100%;width:' + wklyPct.toFixed(1) + '%;background:' + barColor(wklyPct) + ';border-radius:5px;transition:width 0.4s ease;"></div>';
                        html += '</div>';
                    } else {
                        html += '<span style="color:var(--archie-cyan);font-size:0.6rem;flex:1;">Unlimited</span>';
                    }
                    html += '<span style="color:rgba(255,255,255,0.45);min-width:62px;text-align:right;font-size:0.6rem;">' + wklyStr + '</span>';
                    html += '</div>';
                    html += '</div>';
                }
                html += '<div style="display:flex;align-items:center;justify-content:space-between;">';
                if (creedBlocked > 0) {
                    html += '<span class="contractor-creed-badge" style="color:#ffaa00;border-color:#ffaa00;"><i data-lucide="shield-alert" style="width:10px;height:10px;"></i> C.R.E.E.D.: ' + escapeHtml(String(creedBlocked)) + ' blocked</span>';
                } else {
                    html += '<span class="contractor-creed-badge"><i data-lucide="shield-check" style="width:10px;height:10px;"></i> C.R.E.E.D. Compliant</span>';
                }
                html += '<label class="contractor-model-toggle"><input type="checkbox" ' + (modelEnabled ? 'checked' : '') + ' onchange="toggleContractorModel(\'' + providerKey + '\',\'' + escapeHtml(m.name || m.model_name || '') + '\',this.checked)"> Enabled</label>';
                html += '</div>';
                html += '</div>'; // model card
            });
            html += '</div>'; // models grid
        }
        html += '</div>'; // firm body
        if (isBlocked) {
            var blockedText = routingMode === 'local_only' ? 'Routing: Local Only' : 'Routing: Local + Cloud Only';
            html += '<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,0.7);color:#ffaa00;padding:4px 12px;border-radius:4px;font-size:0.7rem;z-index:1;pointer-events:auto;">' + blockedText + '</div>';
        }
        html += '</div>'; // firm
    });

    grid.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleProvider(provider) {
    fetch('/tools/department-hq/api/external-providers/' + encodeURIComponent(provider) + '/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast(data.message || 'Provider toggled', 'success');
        loadContractors();
    })
    .catch(function(e) {
        showToast('Failed to toggle provider', 'error');
    });
}

function toggleContractorModel(provider, model, enabled) {
    fetch('/tools/department-hq/api/external-providers/' + encodeURIComponent(provider) + '/models/' + encodeURIComponent(model) + '/toggle', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enabled })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast(data.message || 'Model toggled', 'success');
        loadContractors();
    })
    .catch(function(e) {
        showToast('Failed to toggle model', 'error');
    });
}

function openAddProviderModal(editProviderName) {
    // Remove existing modal if any
    var existing = document.querySelector('.bm-overlay.bm-provider-modal');
    if (existing) existing.remove();

    // Fetch both contractor-providers definitions AND current key data in parallel
    Promise.all([
        fetch('/tools/department-hq/api/contractor-providers').then(function(r) { return r.json(); }),
        fetch('/tools/department-hq/api/external-providers').then(function(r) { return r.json(); })
    ]).then(function(results) {
        var cpData = results[0];
        var epData = results[1];
        var contractorProviders = cpData.providers || [];
        var configuredProviders = epData.providers || [];
        var current = editProviderName ? configuredProviders.find(function(p) { return p.provider === editProviderName; }) : null;

        // Build provider options dynamically from contractor_providers table
        var providerOptions = contractorProviders.map(function(cp) {
            return { value: cp.provider_key, label: cp.display_name, is_cloud_proxy: cp.is_cloud_proxy };
        });

        var budgetVal = current ? (current.monthly_budget_usd || 10) : 10;
        var currentTier = current ? (current.account_tier || 'free') : 'free';
        var isCloud = editProviderName && providerOptions.some(function(opt) { return opt.value === editProviderName && opt.is_cloud_proxy; });
        var keyPlaceholder = current && current.key_hint ? 'Current: ' + current.key_hint + ' (leave blank to keep)' : 'sk-... or key';

        var tierOptions = [
            { value: 'free', label: 'Free' },
            { value: 'pro', label: 'Pro' },
            { value: 'pay_as_you_go', label: 'Pay As You Go' },
            { value: 'enterprise', label: 'Enterprise' },
            { value: 'max', label: 'Max' }
        ];

        // Helper to create elements
        function el(tag, cls, style) {
            var e = document.createElement(tag);
            if (cls) e.className = cls;
            if (style) e.style.cssText = style;
            return e;
        }

        // --- Build LCARS tablet modal ---
        var overlay = el('div', 'bm-overlay active bm-provider-modal', '--bm-accent:#a855f7;--bm-accent-rgb:168,85,247;');
        overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

        var shell = el('div', 'bm-shell', 'max-width:400px;');

        // Left frame sidebar
        var frame = el('div', 'bm-frame');
        frame.appendChild(el('div', 'bm-frame-elbow-top'));
        frame.appendChild(el('div', 'bm-frame-seg'));
        frame.appendChild(el('div', 'bm-frame-seg dim'));
        frame.appendChild(el('div', 'bm-frame-light on'));
        frame.appendChild(el('div', 'bm-frame-light amber'));
        frame.appendChild(el('div', 'bm-frame-seg purple'));
        frame.appendChild(el('div', 'bm-frame-fill'));
        frame.appendChild(el('div', 'bm-frame-elbow-bottom'));
        shell.appendChild(frame);

        // Right content column
        var content = el('div', 'bm-content');

        // Header
        var header = el('div', 'bm-header');
        var title = el('span', 'bm-header-title');
        title.textContent = (editProviderName ? 'EDIT' : 'ADD') + ' PROVIDER';
        header.appendChild(title);
        var strip = el('div', 'bm-header-strip');
        strip.appendChild(el('span', 'bm-header-pip w1'));
        strip.appendChild(el('span', 'bm-header-pip w2'));
        strip.appendChild(el('span', 'bm-header-pip w3'));
        var closeBtn = el('button', 'bm-close');
        closeBtn.textContent = '\u00D7';
        closeBtn.onclick = function() { overlay.remove(); };
        strip.appendChild(closeBtn);
        header.appendChild(strip);
        content.appendChild(header);

        // Body
        var body = el('div', 'bm-body');

        // Provider select
        var lbl1 = document.createElement('label');
        lbl1.textContent = 'Provider';
        body.appendChild(lbl1);
        var provSelect = document.createElement('select');
        provSelect.id = 'provider-modal-name';
        if (editProviderName) provSelect.disabled = true;
        var defOpt = document.createElement('option');
        defOpt.value = '';
        defOpt.textContent = 'Select provider...';
        provSelect.appendChild(defOpt);
        providerOptions.forEach(function(opt) {
            var o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (editProviderName && editProviderName === opt.value) o.selected = true;
            provSelect.appendChild(o);
        });
        body.appendChild(provSelect);

        // Auth note container
        var authNoteDiv = document.createElement('div');
        authNoteDiv.id = 'provider-modal-auth-note';
        if (isCloud) {
            var noteInner = document.createElement('div');
            noteInner.style.cssText = 'margin:6px 0 8px;padding:6px 8px;background:rgba(0,255,255,0.06);border:1px solid rgba(0,255,255,0.15);border-radius:4px;font-size:0.72rem;color:var(--archie-cyan);';
            noteInner.textContent = 'Auth: OLLAMA_API_KEY env var (shared Ollama cloud proxy)';
            authNoteDiv.appendChild(noteInner);
        }
        body.appendChild(authNoteDiv);

        // Account tier select
        var lbl2 = document.createElement('label');
        lbl2.textContent = 'Account Tier';
        body.appendChild(lbl2);
        var tierSelect = document.createElement('select');
        tierSelect.id = 'provider-modal-tier';
        tierOptions.forEach(function(opt) {
            var o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (opt.value === currentTier) o.selected = true;
            tierSelect.appendChild(o);
        });
        body.appendChild(tierSelect);

        // API key input
        var lbl3 = document.createElement('label');
        lbl3.textContent = 'API Key';
        body.appendChild(lbl3);
        var keyInput = document.createElement('input');
        keyInput.type = 'password';
        keyInput.id = 'provider-modal-key';
        keyInput.placeholder = keyPlaceholder;
        body.appendChild(keyInput);

        // Budget input
        var lbl4 = document.createElement('label');
        lbl4.textContent = 'Monthly Budget ($)';
        body.appendChild(lbl4);
        var budgetInput = document.createElement('input');
        budgetInput.type = 'number';
        budgetInput.id = 'provider-modal-budget';
        budgetInput.value = budgetVal;
        budgetInput.min = '0';
        budgetInput.step = '1';
        body.appendChild(budgetInput);

        content.appendChild(body);

        // Actions bar
        var actions = el('div', 'bm-actions');
        var cancelBtn2 = el('button', 'btn-cancel');
        cancelBtn2.textContent = 'Cancel';
        cancelBtn2.onclick = function() { overlay.remove(); };
        var saveBtn = el('button', 'btn-submit');
        saveBtn.textContent = 'Save';
        saveBtn.onclick = function() { saveProvider(); };
        actions.appendChild(cancelBtn2);
        actions.appendChild(saveBtn);
        content.appendChild(actions);

        // Footer decorative strip
        var footer = el('div', 'bm-footer');
        var footerStrip = el('div', 'bm-footer-strip');
        footerStrip.appendChild(el('span', 'bm-footer-dot purple'));
        footerStrip.appendChild(el('span', 'bm-footer-dot gold'));
        footerStrip.appendChild(el('span', 'bm-footer-dot cyan'));
        footer.appendChild(footerStrip);
        content.appendChild(footer);

        shell.appendChild(content);
        overlay.appendChild(shell);
        document.body.appendChild(overlay);

        // Dynamic auth note update when provider changes
        if (!editProviderName) {
            provSelect.addEventListener('change', function() {
                var sel = this.value;
                var cp = providerOptions.find(function(o) { return o.value === sel; });
                var noteEl = document.getElementById('provider-modal-auth-note');
                if (noteEl) {
                    while (noteEl.firstChild) noteEl.removeChild(noteEl.firstChild);
                    if (cp && cp.is_cloud_proxy) {
                        var noteInner = document.createElement('div');
                        noteInner.style.cssText = 'margin:6px 0 8px;padding:6px 8px;background:rgba(0,255,255,0.06);border:1px solid rgba(0,255,255,0.15);border-radius:4px;font-size:0.72rem;color:var(--archie-cyan);';
                        noteInner.textContent = 'Auth: OLLAMA_API_KEY env var (shared Ollama cloud proxy)';
                        noteEl.appendChild(noteInner);
                    }
                }
            });
        }

        if (typeof lucide !== 'undefined') lucide.createIcons();
    });
}

function editProvider(providerName) {
    openAddProviderModal(providerName);
}

function saveProvider() {
    var nameEl = document.getElementById('provider-modal-name');
    var keyEl = document.getElementById('provider-modal-key');
    var budgetEl = document.getElementById('provider-modal-budget');

    if (!nameEl || !nameEl.value) {
        showToast('Please select a provider', 'error');
        return;
    }

    var tierEl = document.getElementById('provider-modal-tier');
    var payload = {
        provider: nameEl.value,
        monthly_budget_usd: parseFloat(budgetEl.value) || 10,
        account_tier: tierEl ? tierEl.value : 'free'
    };
    if (keyEl.value) {
        payload.api_key = keyEl.value;
    }

    fetch('/tools/department-hq/api/external-providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast(data.message || 'Provider saved', 'success');
        var overlay = document.querySelector('.bm-overlay.bm-provider-modal');
        if (overlay) overlay.remove();
        loadContractors();
    })
    .catch(function(e) {
        showToast('Failed to save provider', 'error');
    });
}
// Init
// ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    loadOverview();

    // Deep-link from Media Studio Portraits tab (or elsewhere):
    //   /tools/department-hq?agent=349#roster
    // opens the Roster tab then the agent's detail modal.
    try {
        var params = new URLSearchParams(window.location.search || '');
        var agentId = parseInt(params.get('agent') || '0', 10);
        if (agentId > 0 && typeof openAgentDetail === 'function') {
            // Give the tab-switch + any data-load a moment to settle, then open.
            setTimeout(function() {
                try { openAgentDetail(agentId); } catch (_) {}
            }, 500);
        }
        // Deep-link: ?tab=<name>#anchor — switch tab then scroll to anchor.
        // Used by dashboard "VIEW ALL →" link (?tab=dispatch#dispatch-history).
        var tabParam = params.get('tab');
        if (tabParam && typeof switchTab === 'function') {
            switchTab(tabParam);
            var anchor = window.location.hash ? window.location.hash.substring(1) : '';
            if (anchor) {
                setTimeout(function() {
                    var el = document.getElementById(anchor);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 400);
            }
        } else {
            // No URL param — try hash first, then localStorage, then default overview.
            var _hashTabMap = {
                'armada': 'fleet', 'fleet': 'fleet',
                'kin': 'kin', 'creed': 'creed', 'social': 'social',
                'dispatch': 'dispatch', 'roster': 'roster',
                'autonomy': 'autonomy', 'coms': 'coms',
                'approvals': 'approvals', 'scout': 'scout',
                'contractors': 'contractors', 'alerts': 'alerts',
            };
            var _hash = (window.location.hash || '').substring(1);
            var _hashTab = _hashTabMap[_hash];
            if (_hashTab && typeof switchTab === 'function') {
                switchTab(_hashTab);
            }
            // No hash = fresh navigation to DHQ = show OVERVIEW (the default).
            // localStorage fallback removed: replaceState now keeps hash in sync.
        }
    } catch (_) {}
})();

// WTF Agent Status panel — Project #350
// escWtf: sanitize values before DOM insertion
function _escWtf(v) {
    return String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function loadWtfAgentStatus() {
    var panel = document.getElementById('wtfAgentPanel');
    var badge = document.getElementById('wtfBacklogBadge');
    var bar   = document.getElementById('wtfBacklogBar');
    var lbl   = document.getElementById('wtfBacklogLabel');
    if (!panel) return;

    try {
        var resp = await fetch('/tools/department-hq/api/fleet/wtf-status');
        var data = await resp.json();
        if (!data.success) {
            panel.textContent = 'Error loading WTF status';
            return;
        }

        var pct = data.backlog_pct || 0;
        if (badge) badge.textContent = pct + '% analyzed';
        if (bar)   bar.style.width   = pct + '%';
        if (lbl)   lbl.textContent   =
            (data.analyzed_articles || 0).toLocaleString() + ' / ' +
            (data.total_articles || 0).toLocaleString() + ' articles analyzed';

        if (!data.agents || !data.agents.length) {
            panel.textContent = 'No dispatches in last hour — waiting for first DHQ job run.';
            return;
        }

        panel.innerHTML = data.agents.map(function(a) {
            var staleColor = a.node_stale ? '#f59e0b' : '#00ffff';
            var failback   = a.node_stale
                ? ' <span style="color:#f59e0b;font-size:0.65rem;">→ failback</span>' : '';
            return '<div style="display:flex;align-items:center;gap:12px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.06);">' +
                '<span style="width:8px;height:8px;border-radius:50%;background:' + staleColor + ';flex-shrink:0;"></span>' +
                '<span style="flex:1;font-weight:600;">' + _escWtf(a.name) + '</span>' +
                '<span style="color:' + staleColor + ';font-size:0.7rem;">' + _escWtf(a.node) + failback + '</span>' +
                '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;color:var(--dhq-text-dim);">' +
                    _escWtf(a.calls_1h) + ' calls &middot; ' + _escWtf(a.avg_sec) + 's avg</span>' +
                '<span style="font-size:0.65rem;color:var(--dhq-text-dim);">' + _escWtf(a.last_seen) + '</span>' +
                '</div>';
        }).join('');
    } catch (e) {
        panel.textContent = 'Failed to load WTF status';
    }
}

// Auto-refresh WTF status every 30s when fleet tab is active
(function () {
    var _wtfTimer = null;
    var _orig = window.switchTab;
    window.switchTab = function (tab) {
        if (typeof _orig === 'function') _orig(tab);
        if (tab === 'fleet') {
            loadWtfAgentStatus();
            if (!_wtfTimer) _wtfTimer = setInterval(loadWtfAgentStatus, 30000);
        } else {
            if (_wtfTimer) { clearInterval(_wtfTimer); _wtfTimer = null; }
        }
    };
}());
