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
let lastRosterData = null; // cache of the last /api/roster response, reused for re-sort/re-group/export

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
        html += heroCard(j.total || 0, 'Dispatches 24h', '#fbbf24');
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
                // Items outside DHQ (QA / security → Repair Bay) carry link_url
                // instead of link_tab — navigate rather than switchTab (#5706).
                var go = item.link_url
                    ? "window.location.href='" + esc(item.link_url) + "'"
                    : "switchTab('" + esc(tab) + "')";
                var label = item.link_label || tab;
                html += '<div class="dhq-attention-item" onclick="' + go + '">'
                    + '<span class="dhq-attention-icon">' + icon + '</span>'
                    + '<span class="dhq-attention-text">' + esc(item.text) + '</span>'
                    + '<span class="dhq-attention-link">→ ' + esc(label) + '</span>'
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

var ALL_SHIFT_STATES = ['active','deployed','barracked','off_duty','winding_down','cooldown'];
let rosterFilterOptionsData = null; // first UNFILTERED /api/roster payload — the filter dropdowns
                                     // are always (re)built from this, never from a filtered
                                     // response. Rebuilding options from e.g. a department=Engineering
                                     // response would erase every other department and trap the user.

// Rebuilds the Shift/Department/Floor filter selects + the bulk-shift select from live
// roster data. `agents` MUST be an unfiltered roster snapshot — see rosterFilterOptionsData.
function populateRosterFilters(agents) {
    var counts = {};
    agents.forEach(function(a){ counts[a.shift_state] = (counts[a.shift_state] || 0) + 1; });

    // Every valid state is listed WITH its count. A zero-count option that is
    // visible is honest; a removed one is indistinguishable from a state that
    // does not exist (spec A §6).
    var shift = document.getElementById('rosterShift');
    var keep = shift.value;
    shift.innerHTML = '<option value="">All Shifts</option>';
    ALL_SHIFT_STATES.forEach(function(s){
        var o = document.createElement('option');
        o.value = s; o.textContent = s + ' (' + (counts[s] || 0) + ')';
        shift.appendChild(o);
    });
    shift.value = keep;

    var depts = Array.from(new Set(agents.map(function(a){ return a.department; }).filter(Boolean))).sort();
    var dsel = document.getElementById('rosterDept'), dkeep = dsel.value;
    dsel.innerHTML = '<option value="">All Departments</option>';
    depts.forEach(function(d){
        var o = document.createElement('option');
        o.value = d; o.textContent = d;
        dsel.appendChild(o);
    });
    dsel.value = dkeep;

    // rosterFloor lost its hardcoded BRIDGE/OPERATIONS/ENGINEERING/CREATIVE/SERVICES
    // options in a prior task and today renders "All Floors" only — a dead control
    // until populated here, the same way as department. Order by the canonical
    // FLOOR_ORDER used elsewhere in this file; anything unrecognized sorts after,
    // alphabetically, rather than being dropped.
    var floors = Array.from(new Set(agents.map(function(a){ return a.floor; }).filter(Boolean)));
    floors.sort(function(a, b){
        var ia = FLOOR_ORDER.indexOf(a), ib = FLOOR_ORDER.indexOf(b);
        if (ia === -1 && ib === -1) return a.localeCompare(b);
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
    });
    var fsel = document.getElementById('rosterFloor'), fkeep = fsel.value;
    fsel.innerHTML = '<option value="">All Floors</option>';
    floors.forEach(function(f){
        var o = document.createElement('option');
        o.value = f; o.textContent = f;
        fsel.appendChild(o);
    });
    fsel.value = fkeep;

    var bulk = document.getElementById('rosterBulkShift');
    if (bulk && bulk.options.length <= 1) {
        ALL_SHIFT_STATES.forEach(function(s){
            var o = document.createElement('option'); o.value = s; o.textContent = s;
            bulk.appendChild(o);
        });
    }
}

// ───────────────────────────────────────────────────────────────
// Needed-agents strip — pending hiring_candidates surfaced where the
// workforce is managed (Roster) and where its health is shown (K.I.N.).
// ONE renderer, two mounts — never duplicate this to keep them from
// drifting apart later.
// ───────────────────────────────────────────────────────────────

// Candidate objects backing the strip's "Create from this" buttons, keyed by
// hiring_candidates.id. The buttons carry ONLY a numeric data-hire-id — never
// candidate text — so the click handler can look up the REAL fetched object
// and hand it to openAgentCreate() directly, with no candidate-authored text
// ever passing through an HTML attribute or being parsed as JS (an inline
// onclick built from this text was a stored-XSS hole: an HTML attribute is
// entity-decoded BEFORE its contents are compiled as JS, so a candidate
// narrative containing e.g. `&quot;});alert(1);//` survives JSON.stringify,
// gets decoded to a real `"` by the attribute parser, and only then executes
// as JS — no single-stage escaping scheme defends against that).
var _hiringCandidatesById = {};

function _hiringStripClickHandler(e) {
    var btn = e.target.closest('button[data-hire-id]');
    if (!btn) return;
    var id = Number(btn.getAttribute('data-hire-id'));
    var c = _hiringCandidatesById[id];
    if (!c) return;
    openAgentCreate({capability: c.capability, narrative: c.narrative || '', hire_id: c.id});
}

function renderHiringStrip(elId, data) {
    var el = document.getElementById(elId);
    if (!el) return;
    // Bind the delegated handler ONCE on the container; it survives setHtml()
    // re-renders (innerHTML replaces children, not the element) — same
    // pattern as loadClaudeFeed's _delegationClickHandler.
    el.onclick = _hiringStripClickHandler;
    // Always render something. An absent panel is indistinguishable from a
    // failed load; an explicit empty state is honest (spec B §5.2).
    if (!data || !data.count) {
        setHtml(el, '<div class="dhq-hiring-strip dhq-hiring-empty">No agents proposed</div>');
        return;
    }
    var rows = data.candidates.map(function(c){
        _hiringCandidatesById[c.id] = c;
        var age = (c.age_hours === null || c.age_hours === undefined) ? '—' : (String(c.age_hours) + 'h');
        return '<li><b>' + esc(c.capability || '—') + '</b> — ' + esc(c.gap_reason || '')
             + ' <span class="dhq-precheck">' + esc(c.precheck_status || '') + '</span>'
             + ' <span class="dhq-age">' + esc(age) + '</span>'
             + ' <button class="dhq-btn-sm" data-hire-id="' + (Number(c.id) || 0) + '">Create from this</button></li>';
    }).join('');
    var more = data.count > data.candidates.length
        ? '<li>… ' + (data.count - data.candidates.length) + ' more</li>' : '';
    setHtml(el, '<div class="dhq-hiring-strip">⚠ ' + data.count
        + ' agent(s) proposed but not hired<ul>' + rows + more + '</ul></div>');
}

async function loadHiringStrip() {
    try {
        var data = await api('/api/hiring/pending');
        renderHiringStrip('rosterHiringStrip', data);
        renderHiringStrip('kinHiringStrip', data);
    } catch (err) {
        renderHiringStrip('rosterHiringStrip', null);
        renderHiringStrip('kinHiringStrip', null);
    }
}

async function loadRoster() {
    loadHiringStrip();
    var el = document.getElementById('rosterContent');

    var filterIds = ['rosterSearch','rosterDept','rosterType','rosterFloor','rosterShift'];
    var params = new URLSearchParams();
    var anyFilterActive = false;
    filterIds.forEach(function(id){
        var v = (document.getElementById(id) || {}).value;
        if (v) {
            anyFilterActive = true;
            params.set({rosterSearch:'search', rosterDept:'department', rosterType:'worker_type',
                       rosterFloor:'floor', rosterShift:'shift_state'}[id], v);
        }
    });

    try {
        var data = await api('/api/roster?' + params.toString());
        loaded['roster'] = true;
        lastRosterData = data;

        // Populate the filter dropdowns from the first (or latest) unfiltered
        // payload only. On a filtered request, keep using whatever unfiltered
        // snapshot was already cached — never rebuild options from a subset.
        if (!anyFilterActive) {
            rosterFilterOptionsData = data.agents;
        }
        if (rosterFilterOptionsData) {
            populateRosterFilters(rosterFilterOptionsData);
        }

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

var rosterSortKey = 'display_name', rosterSortDir = 'asc';
// Map of id -> full agent object, captured at selection time (item A). Selections
// must survive a filter/department change, so we cannot re-derive the selected
// agents from the currently-visible page — the Map stores the actual objects.
var rosterSelection = new Map();

var ROSTER_COLS = [
    {key:'display_name',          label:'Agent'},
    {key:'department',            label:'Dept'},
    {key:'floor',                 label:'Floor'},
    {key:'shift_state',           label:'Shift'},
    {key:'title',                 label:'Role'},
    {key:'skill_count',           label:'Skills'},
    {key:'worker_type',           label:'Type'},
    {key:'performance_score',     label:'Perf'},
    {key:'success_rate',          label:'Success'},
    {key:'total_tasks_completed', label:'Tasks'}
];

function fmtCell(v) {
    // NULL renders as an em dash. Never 0, never blank — see spec A §5.1.
    return (v === null || v === undefined || v === '') ? '—' : String(v);
}

function sortRosterBy(key) {
    if (rosterSortKey === key) rosterSortDir = (rosterSortDir === 'asc' ? 'desc' : 'asc');
    else { rosterSortKey = key; rosterSortDir = 'asc'; }
    renderRoster(lastRosterData);
}

// Regression fix (PR #2740/19a9debbc dropped this): the roster row-click
// wiring to openAgentDetail(id) was lost in the table-redesign rewrite,
// leaving all 140 agents unopenable from the Roster tab. Delegated on the
// container (same pattern as _hiringStripClickHandler /
// _delegationClickHandler) so it survives setHtml() re-renders — binding
// el.onclick is idempotent, safe to reassign on every renderRoster() call.
// Guards on input/label/button/a so the select checkbox keeps working
// (click -> select via its own onchange, NOT open) and never fires for
// .dhq-group-row (no data-agent-id to match).
function _rosterRowClickHandler(e) {
    if (e.target.closest('input, label, button, a')) return;
    var row = e.target.closest('tr[data-agent-id]');
    if (!row) return;
    var id = Number(row.getAttribute('data-agent-id'));
    if (id && typeof openAgentDetail === 'function') openAgentDetail(id);
}

function renderRoster(data) {
    var el = document.getElementById('rosterContent');
    if (!data) return;
    el.onclick = _rosterRowClickHandler;
    var truncated = data.total > data.agents.length;
    var groupKey = (document.getElementById('rosterGroupBy') || {}).value || '';
    var rows = truncated ? data.agents : sortAgents(data.agents, rosterSortKey, rosterSortDir);

    var head = '<tr><th></th>' + ROSTER_COLS.map(function(c){
        var arrow = (c.key === rosterSortKey && !truncated) ? (rosterSortDir === 'asc' ? ' ▲' : ' ▼') : '';
        return truncated
            ? '<th>' + esc(c.label) + '</th>'
            : '<th class="dhq-sortable" onclick="sortRosterBy(\'' + c.key + '\')">' + esc(c.label) + arrow + '</th>';
    }).join('') + '</tr>';

    function agentCell(a) {
        // Avatar thumb + name + acronym (spec A §5). 131/140 have an avatar;
        // the rest fall back to initials, same pattern the old card used.
        // Initials for the no-portrait fallback badge. Splitting on SPACES works for
        // a human name ("Maya Singh" -> MS) but yields ONE letter for a dotted
        // acronym, which is a single token: "A.T.L.A.S." -> "A". That regressed when
        // five agents were renamed from a job title to their acronym — "Model Ops
        // Specialist" had given MO, "A.T.L.A.S." gives A.
        // Dotted acronyms therefore take their first two LETTERS (A.T.L.A.S. -> AT);
        // everything else keeps the word-initials behaviour unchanged.
        // A SINGLE-word name ("Oracle", "Sage", "Nexus") also yielded one letter —
        // pre-existing, not caused by the rename, but the same weak badge. When the
        // word-initials give fewer than two characters, take the name's first two
        // letters instead. '?' has none and stays '?'.
        var _nm = (a.display_name || a.name || '?');
        var _letters = _nm.replace(/[^A-Za-z0-9]/g, '');
        var initials = /^([A-Za-z]\.){2,}$/.test(_nm)
            ? _letters.substring(0, 2).toUpperCase()          // dotted acronym
            : (function () {
                  // Keep only alphanumeric word-initials: "Codex (CLI)" gave "C(" —
                  // two chars, so a length check alone accepts the punctuation.
                  var words = _nm.split(' ')
                      .map(function (w) { return w[0]; })
                      .join('')
                      .replace(/[^A-Za-z0-9]/g, '');
                  return (words.length >= 2 ? words : _letters || _nm).substring(0, 2).toUpperCase();
              })();
        var av = a.avatar_url
            ? '<img class="dhq-row-av" src="' + esc(bust(a.avatar_url, a.avatar_updated_at))
              + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">'
            : '<span class="dhq-row-av dhq-row-av-fallback">' + esc(initials) + '</span>';
        var shownName = a.display_name || a.name || '—';
        // Only append the acronym when it adds information beyond the name
        // already shown — for AI agents display_name IS the acronym, so
        // appending it duplicated the text on 106/140 rows.
        var acr = (a.acronym && a.acronym !== shownName) ? ' <span class="dhq-acr">' + esc(a.acronym) + '</span>' : '';
        return '<td>' + av + esc(shownName) + acr + '</td>';
    }

    function skillCell(a) {
        // An agent with no skills renders an em dash, matching fmtCell's rule that
        // absent is NOT zero. The top few names ride along as a title tooltip; the
        // full list stays in the agent profile modal rather than bloating the row.
        var n = a.skill_count;
        if (n === null || n === undefined || n === 0) return '<td>\u2014</td>';
        var top = Array.isArray(a.skill_top) ? a.skill_top : [];
        var tip = top.length ? top.join(', ') + (n > top.length ? ', +' + (n - top.length) + ' more' : '') : '';
        return '<td><span class="dhq-skill-count"' + (tip ? ' title="' + esc(tip) + '"' : '') + '>'
             + esc(String(n)) + '</span></td>';
    }

    function bodyFor(list) {
        // dhq-roster-row + data-agent-id: the row is clickable to open the
        // profile modal (see _rosterRowClickHandler, delegated on the
        // container) — .dhq-roster-row already carries cursor:pointer +
        // hover styling in department-hq.css from the pre-redesign renderer.
        return list.map(function(a){
            return '<tr class="dhq-roster-row" data-agent-id="' + a.id + '">'
                 + '<td><input type="checkbox" class="dhq-row-sel" data-id="' + a.id + '"'
                 + (rosterSelection.has(a.id) ? ' checked' : '') + ' onchange="toggleRosterSel(' + a.id + ',this.checked)"></td>'
                 + ROSTER_COLS.map(function(c){
                       if (c.key === 'display_name') return agentCell(a);
                       if (c.key === 'skill_count') return skillCell(a);
                       return '<td>' + esc(fmtCell(a[c.key])) + '</td>';
                   }).join('') + '</tr>';
        }).join('');
    }

    var body;
    if (groupKey) {
        var groups = groupAgents(rows, groupKey);
        body = Object.keys(groups).sort().map(function(k){
            return '<tr class="dhq-group-row"><td colspan="' + (ROSTER_COLS.length + 1) + '">'
                 + esc(k) + ' (' + groups[k].length + ')</td></tr>' + bodyFor(groups[k]);
        }).join('');
    } else {
        body = bodyFor(rows);
    }

    var notice = truncated
        ? '<div class="dhq-warn">Showing ' + data.agents.length + ' of ' + data.total
          + ' — sorting disabled on a partial list. Narrow the filters.</div>' : '';
    setHtml(el, notice + '<table class="dhq-roster-table"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>');
}

function toggleRosterSel(id, on) {
    if (on) {
        // Capture the agent OBJECT now, while it is still part of the currently
        // rendered view — a later filter/department change must not lose it
        // (item A: re-deriving from lastRosterData.agents at apply-time let a
        // selected department director silently vanish from the warning).
        var agent = ((lastRosterData && lastRosterData.agents) || []).filter(function(a){ return a.id === id; })[0];
        if (agent) rosterSelection.set(id, agent);
    } else {
        rosterSelection.delete(id);
    }
    var bar = document.getElementById('rosterBulkBar');
    document.getElementById('rosterSelCount').textContent = rosterSelection.size + ' selected';
    bar.style.display = rosterSelection.size ? 'flex' : 'none';
}

async function applyBulkShift() {
    var state = document.getElementById('rosterBulkShift').value;
    if (!state || !rosterSelection.size) return;
    var ids = Array.from(rosterSelection.keys());
    var chosen = Array.from(rosterSelection.values());
    var directors = chosen.filter(function(a){ return a.is_department_ai; });

    // A batch over N targets is N decisions — name the count, the transition,
    // and anything unusual in the selection before acting.
    var msg = 'Change shift for ' + ids.length + ' agent(s) to "' + state + '".';
    if (directors.length) msg += '\n\n⚠ ' + directors.length + ' of them are department directors.';
    if (!confirm(msg)) return;

    var res = await apiPost('/api/roster/bulk-shift', {agent_ids: ids, shift_state: state});
    var failed = (res.results || []).filter(function(r){ return !r.ok; });
    alert('Applied: ' + res.ok_count + ' ok, ' + res.failed_count + ' failed'
          + (failed.length ? '\n\n' + failed.map(function(f){
                return '#' + f.agent_id + ': ' + f.error; }).join('\n') : ''));
    rosterSelection.clear();
    toggleRosterSel(null, false);
    loadRoster();
}

function exportRosterCsv() {
    var groupKey = (document.getElementById('rosterGroupBy') || {}).value || '';
    var data = lastRosterData || {agents: [], total: 0};
    var agents = data.agents || [];
    // Match renderRoster's predicate exactly: a truncated (partial) list is
    // shown in unsorted server order, so the export must not silently
    // re-sort it into something that doesn't match what was on screen.
    var truncated = data.total > agents.length;
    var rows = truncated ? agents : sortAgents(agents, rosterSortKey, rosterSortDir);
    if (groupKey) {
        var g = groupAgents(rows, groupKey);
        rows = Object.keys(g).sort().reduce(function(acc, k){ return acc.concat(g[k]); }, []);
    }
    var q = function(v){ return '"' + String(v === null || v === undefined ? '' : v).replace(/"/g, '""') + '"'; };
    var csv = [ROSTER_COLS.map(function(c){ return q(c.label); }).join(',')]
        .concat(rows.map(function(a){
            return ROSTER_COLS.map(function(c){ return q(a[c.key]); }).join(',');
        })).join('\n');
    var url = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
    var link = document.createElement('a');
    link.href = url; link.download = 'roster.csv';
    document.body.appendChild(link); link.click();
    document.body.removeChild(link); URL.revokeObjectURL(url);
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

    var btn = document.getElementById('rosterGenPortraitsBtn');
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
    if (btn) btn.textContent = 'Queued ' + ok + ' for review — ' + fail + ' failed';
    // Refresh roster after a moment to pick up new avatar_urls
    setTimeout(loadRoster, 1500);
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
    ['welfare', 'workload', 'work', 'performance', 'calendar'].forEach(function(s) {
        var el = document.getElementById('kinSection-' + s);
        var btn = document.getElementById('kinBtn-' + s);
        if (el) el.style.display = s === section ? '' : 'none';
        if (btn) btn.classList.toggle('dhq-traffic-btn-active', s === section);
    });
    if (section === 'work') loadWorkSessions();
    if (section === 'performance') loadPerformance();
    if (section === 'workload') loadKinWorkload();
    if (section === 'calendar') loadKinCalendar();
}

var _kinRefreshInterval = null;

async function loadKinTab() {
    loadHiringStrip();
    await loadKinWelfare();
    loadWorkSessions();
    // Auto-refresh welfare + workload every 60s
    if (_kinRefreshInterval) clearInterval(_kinRefreshInterval);
    _kinRefreshInterval = setInterval(function() {
        if (_kinActiveSection === 'welfare') loadKinWelfare();
        if (_kinActiveSection === 'workload') loadKinWorkload();
        if (_kinActiveSection === 'calendar') loadKinCalendar();
    }, 60000);
}

// ── K.I.N. Shift Calendar (reactive state-timeline, PR #1662 backend) ─────────
// GET /api/kin/shift-calendar returns per-agent current_state + timestamped
// transitions + rest cycles + the advisory hardware-rest window — i.e. EVENTS,
// not pre-bucketed cells. Each agent's day-timeline is reconstructed here, then
// rendered as a continuous 24h track positioned by ET minute. Owner decision
// 2026-06-13: reactive timeline only; hardware-rest window is advisory overlay.
var _kinCalDate = '';  // '' = today; 'YYYY-MM-DD' for a past day
var KIN_STATE_COLORS = {
    active: '#00e5ff', deployed: '#0ea5e9', winding_down: '#fbbf24',
    cooldown: '#6b7280', off_duty: 'rgba(255,255,255,0.14)',
    barracked: 'rgba(255,255,255,0.14)'
};
var KIN_DIM = 'rgba(255,255,255,0.14)';

function _kinEtHM(ms) {
    return new Date(ms).toLocaleTimeString('en-CA', {
        timeZone: 'America/Toronto', hour: '2-digit', minute: '2-digit', hour12: false
    });
}

// Reconstruct an agent's base shift-state segments across the day from the
// transition log. No transitions today → state held all day (current_state).
function _kinBaseSegments(a, dayStart, renderEnd) {
    var tr = (a.transitions || []).map(function(t) {
        return { atMs: Date.parse(t.at), from: t.from, to: t.to, reason: t.reason };
    }).filter(function(t) { return !isNaN(t.atMs); })
      .sort(function(x, y) { return x.atMs - y.atMs; });
    if (!tr.length) {
        return [{ startMs: dayStart, endMs: renderEnd, state: a.current_state, reason: 'no change logged today' }];
    }
    var segs = [{ startMs: dayStart, endMs: Math.min(tr[0].atMs, renderEnd),
                  state: tr[0].from || a.current_state, reason: 'carry-over from prior day' }];
    for (var i = 0; i < tr.length; i++) {
        var segEnd = (i + 1 < tr.length) ? tr[i + 1].atMs : renderEnd;
        segs.push({ startMs: tr[i].atMs, endMs: Math.min(segEnd, renderEnd),
                    state: tr[i].to, reason: tr[i].reason });
    }
    return segs.filter(function(s) { return s.endMs > s.startMs; });
}

async function loadKinCalendar(dateOverride) {
    if (typeof dateOverride === 'string') _kinCalDate = dateOverride;
    var host = document.getElementById('kinCalendarContent');
    if (!host) return;
    var url = '/tools/department-hq/api/kin/shift-calendar' +
              (_kinCalDate ? ('?date=' + encodeURIComponent(_kinCalDate)) : '');
    try {
        var r = await fetch(url);
        if (!r.ok) {
            host.className = 'dhq-loading';
            host.textContent = 'Calendar unavailable (HTTP ' + r.status + ')';
            return;
        }
        _renderKinCalendar(host, await r.json());
    } catch (e) {
        host.className = 'dhq-loading';
        host.textContent = 'Failed to load shift calendar: ' + e;
    }
}

function _renderKinCalendar(host, data) {
    host.className = '';
    host.textContent = '';
    var agents = (data && data.agents) || [];
    var dayStart = Date.parse(data.day_start);
    var dayEnd = Date.parse(data.day_end);
    var dayMs = (dayEnd - dayStart) || 86400000;
    var isToday = !!data.is_today;
    var nowMs = data.now ? Date.parse(data.now) : dayEnd;
    var renderEnd = isToday ? nowMs : dayEnd;
    var hw = data.hardware_rest || null;
    function pct(ms) { return Math.max(0, Math.min(100, (ms - dayStart) / dayMs * 100)); }

    // hardware-rest slabs (window wraps midnight → up to two within a day)
    var hwSlabs = [];
    if (hw && hw.enabled) {
        var s = hw.start_hour, e = hw.end_hour;
        if (s < e) hwSlabs.push([s, e]); else { hwSlabs.push([0, e]); hwSlabs.push([s, 24]); }
    }
    function addGridlines(track) {
        for (var h = 0; h <= 24; h++) {
            var gl = document.createElement('div');
            gl.className = 'kin-cal-gridline';
            gl.style.left = (h / 24 * 100) + '%';
            track.appendChild(gl);
        }
    }
    function addHwBands(track) {
        hwSlabs.forEach(function(sl) {
            var band = document.createElement('div');
            band.className = 'kin-cal-hwband';
            band.style.left = (sl[0] / 24 * 100) + '%';
            band.style.width = ((sl[1] - sl[0]) / 24 * 100) + '%';
            track.appendChild(band);
        });
    }

    // controls: date picker + Today + legend
    var controls = document.createElement('div');
    controls.className = 'kin-cal-controls';
    var dateInput = document.createElement('input');
    dateInput.type = 'date';
    dateInput.className = 'kin-cal-date';
    dateInput.value = data.date || '';
    dateInput.onchange = function() { loadKinCalendar(this.value); };
    var todayBtn = document.createElement('button');
    todayBtn.className = 'dhq-traffic-btn';
    todayBtn.textContent = 'TODAY';
    todayBtn.onclick = function() { loadKinCalendar(''); };
    controls.appendChild(dateInput);
    controls.appendChild(todayBtn);
    var legend = document.createElement('div');
    legend.className = 'kin-cal-legend';
    [['Active', KIN_STATE_COLORS.active], ['Deployed', KIN_STATE_COLORS.deployed],
     ['Winding down', KIN_STATE_COLORS.winding_down], ['Resting', '#f59e0b'],
     ['Cooldown', KIN_STATE_COLORS.cooldown], ['Off/Barracked', KIN_DIM],
     ['HW rest', 'rgba(239,68,68,0.45)']].forEach(function(it) {
        var item = document.createElement('span');
        item.className = 'kin-cal-legend-item';
        var sw = document.createElement('i');
        sw.className = 'kin-cal-swatch';
        sw.style.background = it[1];
        item.appendChild(sw);
        item.appendChild(document.createTextNode(it[0]));
        legend.appendChild(item);
    });
    controls.appendChild(legend);
    host.appendChild(controls);

    if (!agents.length) {
        var empty = document.createElement('div');
        empty.className = 'dhq-loading';
        empty.textContent = 'No agents for this day.';
        host.appendChild(empty);
        return;
    }

    var grid = document.createElement('div');
    grid.className = 'kin-cal-grid';

    // hour-axis header
    var headRow = document.createElement('div');
    headRow.className = 'kin-cal-row kin-cal-head';
    var headLabel = document.createElement('div');
    headLabel.className = 'kin-cal-label';
    headLabel.textContent = (data.date || '') + (isToday ? ' · today' : '');
    var headTrack = document.createElement('div');
    headTrack.className = 'kin-cal-track kin-cal-axis';
    addHwBands(headTrack);
    for (var hh = 0; hh <= 24; hh += 3) {
        var lbl = document.createElement('span');
        lbl.className = 'kin-cal-hourlabel';
        lbl.style.left = (hh / 24 * 100) + '%';
        lbl.textContent = (hh === 24 ? '24' : String(hh).padStart(2, '0'));
        headTrack.appendChild(lbl);
    }
    headRow.appendChild(headLabel);
    headRow.appendChild(headTrack);
    grid.appendChild(headRow);

    // agent rows, grouped by department
    var lastDept = null;
    agents.forEach(function(a) {
        if (a.department !== lastDept) {
            lastDept = a.department;
            var dh = document.createElement('div');
            dh.className = 'kin-cal-dept';
            dh.textContent = a.department || 'Unassigned';
            grid.appendChild(dh);
        }
        var row = document.createElement('div');
        row.className = 'kin-cal-row';

        var label = document.createElement('div');
        label.className = 'kin-cal-label';
        var dot = document.createElement('i');
        dot.className = 'kin-cal-swatch';
        dot.style.background = KIN_STATE_COLORS[a.current_state] || KIN_DIM;
        label.appendChild(dot);
        var nm = document.createElement('span');
        nm.className = 'kin-cal-name';
        nm.textContent = a.name;
        label.appendChild(nm);
        if (a.hours_today != null) {
            var hrs = document.createElement('span');
            hrs.className = 'kin-cal-hours';
            hrs.textContent = a.hours_today + 'h';
            label.appendChild(hrs);
        }
        label.title = a.name + ' — now: ' + (a.current_state || 'unknown') +
            (a.hours_today != null ? ' · ' + a.hours_today + 'h today' : '');

        var track = document.createElement('div');
        track.className = 'kin-cal-track';
        addGridlines(track);
        _kinBaseSegments(a, dayStart, renderEnd).forEach(function(sg) {
            var d = document.createElement('div');
            d.className = 'kin-cal-seg';
            d.style.left = pct(sg.startMs) + '%';
            d.style.width = Math.max(0, pct(sg.endMs) - pct(sg.startMs)) + '%';
            d.style.background = KIN_STATE_COLORS[sg.state] || KIN_DIM;
            d.title = (sg.state || 'unknown') + ' · ' + _kinEtHM(sg.startMs) + '–' + _kinEtHM(sg.endMs) +
                (sg.reason ? ' · ' + sg.reason : '');
            track.appendChild(d);
        });
        (a.rests || []).forEach(function(rst) {
            var rs = Math.max(Date.parse(rst.start), dayStart);
            var re = Math.min(rst.end ? Date.parse(rst.end) : renderEnd, renderEnd);
            if (isNaN(rs) || re <= rs) return;
            var d = document.createElement('div');
            d.className = 'kin-cal-seg kin-cal-rest';
            d.style.left = pct(rs) + '%';
            d.style.width = Math.max(0, pct(re) - pct(rs)) + '%';
            d.style.background = (rst.type === 'cooldown') ? KIN_STATE_COLORS.cooldown : '#f59e0b';
            d.title = 'resting' + (rst.type ? ' (' + rst.type + ')' : '') + ' · ' + _kinEtHM(rs) + '–' + _kinEtHM(re);
            track.appendChild(d);
        });
        addHwBands(track);  // advisory red tint on top of states during the rest window
        if (isToday) {
            var nowLine = document.createElement('div');
            nowLine.className = 'kin-cal-now';
            nowLine.style.left = pct(nowMs) + '%';
            nowLine.title = 'now · ' + _kinEtHM(nowMs);
            track.appendChild(nowLine);
        }
        row.appendChild(label);
        row.appendChild(track);
        grid.appendChild(row);
    });
    host.appendChild(grid);
}

// Approve/Deny an 8h-rest welfare approval directly from the K.I.N. welfare card.
// Hits the SAME endpoint as the Approvals tab + Telegram buttons, so all three surfaces
// stay in sync (the approval is enforced on the agent by _approve_autonomy).
async function _kinWelfareApprove(approvalId, approve, okBtn, noBtn) {
    if (okBtn) okBtn.disabled = true;
    if (noBtn) noBtn.disabled = true;
    if (okBtn) okBtn.textContent = approve ? 'Approving…' : 'Denying…';
    try {
        var url = '/tools/department-hq/api/approvals/' + approvalId + '/' + (approve ? 'approve' : 'deny');
        var opts = { method: 'POST' };
        if (!approve) {
            opts.headers = { 'Content-Type': 'application/json' };
            opts.body = JSON.stringify({ reason: 'Denied from K.I.N. welfare card' });
        }
        var resp = await fetch(url, opts);
        var data = await resp.json();
        if (data && data.success) {
            if (okBtn) okBtn.textContent = approve ? 'Rest granted ✓' : 'Denied ✓';
            setTimeout(loadKinWelfare, 800);
        } else {
            if (okBtn) { okBtn.disabled = false; okBtn.textContent = '✅ Approve 8h rest'; }
            if (noBtn) noBtn.disabled = false;
            alert('Failed: ' + ((data && data.error) || 'unknown'));
        }
    } catch (e) {
        if (okBtn) { okBtn.disabled = false; okBtn.textContent = '✅ Approve 8h rest'; }
        if (noBtn) noBtn.disabled = false;
        alert('Error: ' + e.message);
    }
}

// K.I.N. Welfare 2.0 — manual state control with C.R.E.E.D. consequences. "Force wake"
// of an overworked/resting agent warns + confirms, then logs a NEGATIVE governance
// event (penalty scaled by the 3-layer load: hours + tokens + dispatches). "Put on
// break" is welfare-positive. Backend: POST /api/kin/agent/<id>/state.
async function _kinAgentState(agentId, action, confirmed) {
    try {
        var resp = await fetch('/tools/department-hq/api/kin/agent/' + agentId + '/state', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action, confirm: !!confirmed })
        });
        var data = await resp.json();
        if (data && data.needs_confirm && data.breach) {
            if (window.confirm('⚠️ C.R.E.E.D. WELFARE BREACH\n\n' + data.breach.message + '\n\nForce anyway and log the penalty?')) {
                return _kinAgentState(agentId, action, true);
            }
            return;
        }
        if (data && data.success) { setTimeout(loadKinWelfare, 600); }
        else { alert('State change failed: ' + ((data && data.error) || 'unknown')); }
    } catch (e) { alert('State change failed: ' + (e.message || e)); }
}

// Task #3798: layered 24h recovery sparkline — per-hour token (purple) + dispatch
// (cyan) layers over the rolling window. As the window advances on each 30s refresh,
// the oldest bars age out, so recovery is VISIBLE as the layers drain left-to-right.
function _kinRecoverySpark(a) {
    var hist = a.recovery_24h || [];
    if (!hist.length) return '';
    var maxTok = 0, maxDisp = 0, any = false;
    hist.forEach(function (b) {
        if (b.tokens > maxTok) maxTok = b.tokens;
        if (b.dispatches > maxDisp) maxDisp = b.dispatches;
        if (b.tokens || b.dispatches) any = true;
    });
    if (!any) return '';
    var bars = '';
    hist.forEach(function (b) {
        var th = maxTok ? Math.round(b.tokens / maxTok * 70) : 0;
        var dh = maxDisp ? Math.round(b.dispatches / maxDisp * 25) : 0;
        var hh = new Date(b.t).getHours();
        bars += '<div title="' + (hh < 10 ? '0' : '') + hh + ':00 — ' + _dhqFmtTok(b.tokens) + ' tok · ' + b.dispatches + ' disp"'
            + ' style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:1px;height:100%;min-width:2px;">'
            + '<div style="height:' + th + '%;min-height:' + (b.tokens ? 1 : 0) + 'px;background:#a78bfa;border-radius:1px;"></div>'
            + '<div style="height:' + dh + '%;min-height:' + (b.dispatches ? 1 : 0) + 'px;background:#00bcd4;border-radius:1px;"></div>'
            + '</div>';
    });
    return '<div style="margin-top:6px;">'
        + '<div style="display:flex;align-items:flex-end;gap:1px;height:26px;">' + bars + '</div>'
        + '<div style="display:flex;justify-content:space-between;font-size:0.55rem;color:var(--dhq-text-dim);opacity:0.7;margin-top:2px;">'
        + '<span>−24h</span><span style="color:#a78bfa;">■ tok</span><span style="color:#00bcd4;">■ disp</span><span>now</span>'
        + '</div></div>';
}

/* #5157: compact age for bench/stat-freshness labels. Hours in, "3h"/"2.1d" out. */
function _kinAge(hours) {
    if (hours === null || hours === undefined) return '';
    var h = Number(hours);
    if (!isFinite(h) || h < 0) return '';
    if (h < 1) return Math.max(1, Math.round(h * 60)) + 'm';
    if (h < 48) return (h < 10 ? h.toFixed(1) : Math.round(h)) + 'h';
    return (h / 24).toFixed(1) + 'd';
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
        var mq = document.getElementById('kinMediaQueueCount');
        if (mq) {
            var mediaQueue = d.media_queue || {};
            mq.textContent = (mediaQueue.active || 0) + ' media active · ' + (mediaQueue.failed || 0) + ' failed 24h';
            mq.style.color = (mediaQueue.failed || 0) > 0 ? '#ef4444' : ((mediaQueue.active || 0) > 0 ? '#a78bfa' : 'var(--dhq-text-dim)');
        }

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
        /* T3179: Fold5 unfolded (~882px) forces 3 cols and overflows — use 2-col at ≤900px */
        var gridCols = window.innerWidth <= 900 ? 'repeat(2,1fr)' : 'repeat(auto-fill,minmax(240px,1fr))';
        grid.style.cssText = 'display:grid;grid-template-columns:' + gridCols + ';gap:10px;';
        agents.forEach(function(a) {
            /* #5157(3): BENCHED must be tested FIRST. A barracked agent has no active
               rest cycle, is not at-limit and is not overworked, so it fell through
               every branch to the final else and rendered '✓ active' in GREEN —
               pixel-identical to a healthy agent. That is how F.A.C.T. and four others
               sat benched unnoticed. 'barracked' does NOT self-recover (unlike
               cooldown), so it is the most urgent state on this tab, not the least. */
            var statusColor = a.benched ? '#ef4444'
                : (a.resting ? '#f59e0b'
                : (a.at_limit ? '#ef4444'
                : (a.overwork_level === 'critical' ? '#ef4444'
                : (a.overwork_level === 'warning' ? '#f59e0b' : '#10b981'))));
            var statusLabel = a.benched
                    ? (a.bench_reason === 'failure'
                        ? '⛔ BENCHED ' + _kinAge(a.bench_age_hours)
                        /* #5829: 'stranded_working' is the LOUDEST of the three — the agent
                           is flagged off the floor yet still dispatching, so it is excluded
                           from skill-based selection while pinned paths keep feeding it.
                           Four agents sat like this for days (P.U.B.L.I.S.H. 582 runs/24h),
                           rendering as an ordinary bench. Show the run count so the claim is
                           auditable on the card instead of merely asserted. */
                        : (a.bench_reason === 'stranded_working'
                            ? '⛔ BENCHED BUT WORKING · ' + (a.bench_recent_runs || 0) + '/hr'
                            : '⛔ STRANDED'))
                : (a.resting ? '😴 ' + (a.rest_type || 'resting')
                : (a.at_limit ? (a.limit_dimension === 'task'
                        ? '⚠ QUEUE ' + (a.task_count || 0) + '/' + (a.task_limit || 0)
                        : '⚠ TOKEN ' + Math.round((a.token_ratio || 0) * 100) + '% throttled')
                : (a.overwork_level === 'critical' ? '🔥 ' + (a.hours_worked_today || 0).toFixed(1) + 'h OVERWORKED'
                : (a.overwork_level === 'warning' ? '⏱ ' + (a.hours_worked_today || 0).toFixed(1) + 'h today'
                : '✓ active'))));
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
                /* Task #3799: token budget is the primary welfare signal (per-LLM
                   C.R.E.E.D. capacity model); dispatch count is secondary context. */
                + '<span style="color:#a78bfa;">' + _dhqFmtTok(a.tokens_24h || 0) + '/' + (a.token_limit_per_day ? _dhqFmtTok(a.token_limit_per_day) : 'no budget') + ' tok</span>'
                + (a.token_limit_per_day ? ' (' + Math.round((a.token_ratio || 0) * 100) + '%)' : '')
                + (a.dispatches_1h ? ' · <span style="color:#00bcd4;">' + a.dispatches_1h + ' disp/h</span>' : '')
                + ' · ' + (a.dispatches_24h || 0) + ' disp/24h'
                + (a.stress ? ' · stress: ' + Math.round(a.stress * 100) + '%' : '')
                /* #5157(2): the welfare loop only advances ACTIVE agents, so a benched
                   or idle agent's stress/energy/mood freeze at their last snapshot.
                   Without this the frozen number reads as a live one — which is how a
                   stranded agent looked "fine" indefinitely. */
                + (a.stats_stale ? ' <span style="color:#f59e0b;" title="Welfare stats stop advancing while an agent is off the floor — this reading is a snapshot, not current.">⧖ stats ' + _kinAge(a.stats_age_hours) + ' old</span>' : '')
                + '</div>'
                + _kinRecoverySpark(a)
                + (a.rest_since
                    ? '<div style="margin-top:6px;">'
                      + '<div style="background:rgba(255,255,255,0.08);border-radius:3px;height:3px;overflow:hidden;margin-bottom:4px;">'
                      + '<div class="kinw-bar-fill" data-rest-at="' + new Date(a.rest_since).getTime() + '" data-rest-until="' + (a.rest_until ? new Date(a.rest_until).getTime() : '') + '" style="height:100%;background:#f59e0b;border-radius:3px;width:0%;transition:width 0.5s linear;"></div>'
                      + '</div>'
                      + '<div style="display:flex;justify-content:space-between;font-size:0.63rem;color:#f59e0b;">'
                      + '<span>resting since ' + new Date(a.rest_since).toLocaleTimeString() + '</span>'
                      + '<span class="kinw-countdown" data-rest-at="' + new Date(a.rest_since).getTime() + '" data-rest-until="' + (a.rest_until ? new Date(a.rest_until).getTime() : '') + '">…</span>'
                      + '</div>'
                      + '</div>'
                    : (a.at_limit
                        ? '<div style="font-size:0.62rem;color:#f59e0b;margin-top:4px;opacity:0.85;">'
                          + (a.limit_dimension === 'task'
                              ? 'Queue full — new work routes to peers'
                              : '🚦 Throttled — over 24h token budget; recovers as work ages out'
                                + (a.token_recovery_eta_min != null
                                    ? ' · ~' + (a.token_recovery_eta_min >= 60 ? Math.round(a.token_recovery_eta_min / 60) + 'h' : a.token_recovery_eta_min + 'm') + ' to clear'
                                    : '')
                                + ' (no rest needed for tokens)')
                          + '</div>'
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
            // K.I.N. welfare approval — when an 8h-rest approval is pending for this
            // agent, surface Approve/Deny right on the card (same backend as the Approvals
            // tab + Telegram, "same result"). Previously the card only showed "rest
            // approval pending" with no way to act here.
            if (a.rest_approval_id) {
                var actRow = document.createElement('div');
                actRow.style.cssText = 'display:flex;gap:6px;margin-top:8px;';
                var okBtn = document.createElement('button');
                okBtn.textContent = '✅ Approve 8h rest';
                okBtn.style.cssText = 'flex:1;font-size:0.62rem;background:#10b981;color:#04241a;border:none;border-radius:4px;padding:5px 6px;cursor:pointer;font-weight:600;';
                var noBtn = document.createElement('button');
                noBtn.textContent = 'Deny';
                noBtn.style.cssText = 'font-size:0.62rem;background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid #ef444455;border-radius:4px;padding:5px 12px;cursor:pointer;';
                okBtn.onclick = function () { _kinWelfareApprove(a.rest_approval_id, true, okBtn, noBtn); };
                noBtn.onclick = function () { _kinWelfareApprove(a.rest_approval_id, false, okBtn, noBtn); };
                actRow.appendChild(okBtn);
                actRow.appendChild(noBtn);
                card.appendChild(actRow);
            }
            // Welfare 2.0 — manual state control (contextual): "Put on break" when active,
            // "Force wake" when resting/overworked (warns + logs a C.R.E.E.D. penalty).
            var _ov = a.overwork_level && a.overwork_level !== 'normal';
            var stateRow = document.createElement('div');
            stateRow.style.cssText = 'display:flex;gap:6px;margin-top:8px;';
            if (!a.resting) {
                var breakBtn = document.createElement('button');
                breakBtn.textContent = '💤 Put on break';
                breakBtn.title = 'Grant an 8h rest (welfare-positive)';
                breakBtn.style.cssText = 'flex:1;font-size:0.6rem;background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid #f59e0b55;border-radius:4px;padding:4px 6px;cursor:pointer;';
                breakBtn.onclick = function () { _kinAgentState(a.id, 'rest', false); };
                stateRow.appendChild(breakBtn);
            }
            if (a.resting || _ov) {
                var wakeBtn = document.createElement('button');
                wakeBtn.textContent = '⚡ Force wake';
                wakeBtn.title = 'Force back to work — breaches C.R.E.E.D. if overworked (logs a penalty)';
                wakeBtn.style.cssText = 'flex:1;font-size:0.6rem;background:rgba(239,68,68,0.12);color:#ef4444;border:1px solid #ef444455;border-radius:4px;padding:4px 6px;cursor:pointer;';
                wakeBtn.onclick = function () { _kinAgentState(a.id, 'wake', false); };
                stateRow.appendChild(wakeBtn);
            }
            if (stateRow.children.length) card.appendChild(stateRow);
            grid.appendChild(card);
        });
        el.appendChild(grid);

        // Live countdown: updates every second — progress bar fill + "recovers in Xm Ys"
        if (window._kinRestTimer) clearInterval(window._kinRestTimer);
        window._kinRestTimer = setInterval(function () {
            var now = Date.now();
            document.querySelectorAll('.kinw-countdown').forEach(function (span) {
                var startAt = parseInt(span.dataset.restAt, 10);
                // Use the REAL rest end time when present (rests vary 30 min – 8h); fall
                // back to start+1h only for legacy open-ended cycles with no end time.
                var endAt = parseInt(span.dataset.restUntil, 10) || (startAt + 3600000);
                var remaining = endAt - now;
                if (remaining <= 0) { span.textContent = 'recovery due'; return; }
                var h = Math.floor(remaining / 3600000);
                var m = Math.floor((remaining % 3600000) / 60000);
                var s = Math.floor((remaining % 60000) / 1000);
                span.textContent = 'recovers in ' + (h > 0 ? h + 'h ' + m + 'm' : m + 'm ' + (s < 10 ? '0' : '') + s + 's');
            });
            document.querySelectorAll('.kinw-bar-fill').forEach(function (bar) {
                var startAt = parseInt(bar.dataset.restAt, 10);
                var endAt = parseInt(bar.dataset.restUntil, 10) || (startAt + 3600000);
                var span = endAt - startAt;
                bar.style.width = (span > 0 ? Math.min(100, ((now - startAt) / span) * 100).toFixed(1) : 0) + '%';
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
            + '<th style="text-align:right;padding:4px 8px;">TOK/H</th>'
            + '<th style="text-align:right;padding:4px 8px;">TOKENS 24H</th>'
            + '<th style="text-align:right;padding:4px 8px;">TOKEN BUDGET</th>'
            + '<th style="text-align:right;padding:4px 8px;" title="Wall-clock busy hours since the last COMPLETED rest today — not hours worked today. The window deliberately restarts after each rest (KB #270628) so a just-rested agent cannot re-trip the hours_cap break on stale hours. An agent resting every ~30min therefore reads near zero while still working hard: read DISPATCH 24H / TOKENS 24H for actual load.">HRS SINCE REST</th>'
            + '<th style="text-align:right;padding:4px 8px;">DISPATCH 24H</th>'
            + '</tr></thead>';
        var tbody = document.createElement('tbody');
        wl.forEach(function(a) {
            // Token-based workload (KB #270619): capacity is the agent's DAILY TOKEN BUDGET
            // (model-aware — small models get a smaller budget), not a dispatch count.
            var tok24 = a.tokens_24h || 0;
            var tokBudget = a.token_limit_per_day || 150000;
            var tokPct = Math.min(100, Math.round(tok24 / tokBudget * 100));
            var tokBarColor = tokPct > 90 ? '#ef4444' : tokPct > 70 ? '#f59e0b' : '#10b981';
            var tr = document.createElement('tr');
            tr.style.cssText = 'border-bottom:1px solid rgba(255,255,255,0.04);';
            tr.innerHTML = '<td style="padding:5px 8px;color:var(--dhq-text-main);font-family:Antonio,sans-serif;letter-spacing:0.5px;">' + a.name + '</td>'
                + '<td style="padding:5px 8px;text-align:right;color:var(--dhq-text-dim);font-size:0.67rem;">' + (a.department || '').split(' & ')[0] + '</td>'
                + '<td style="padding:5px 8px;text-align:right;color:#a78bfa;font-family:\'IBM Plex Mono\',monospace;">' + _dhqFmtTok(a.tokens_1h) + '/h</td>'
                + '<td style="padding:5px 8px;text-align:right;color:#a78bfa;font-family:\'IBM Plex Mono\',monospace;">' + _dhqFmtTok(tok24) + '</td>'
                + '<td style="padding:5px 8px;text-align:right;">'
                    + '<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end;">'
                    + '<div style="width:60px;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden;">'
                    + '<div style="width:' + tokPct + '%;height:100%;background:' + tokBarColor + ';"></div>'
                    + '</div>'
                    + '<span style="color:var(--dhq-text-dim);min-width:80px;text-align:right;font-size:0.67rem;">' + _dhqFmtTok(tok24) + '/' + _dhqFmtTok(tokBudget) + '</span>'
                    + '</div></td>'
                + (function() {
                var hw = a.hours_worked_today || 0;
                var hwColor = a.overwork_level === 'critical' ? '#ef4444' : a.overwork_level === 'warning' ? '#f59e0b' : 'var(--dhq-text-dim)';
                var hwSuffix = a.overwork_level && a.overwork_level !== 'normal' ? ' ⚠' : '';
                return '<td style="padding:5px 8px;text-align:right;font-family:\'IBM Plex Mono\',monospace;color:' + hwColor + ';">' + (hw ? hw.toFixed(1) + 'h' + hwSuffix : '—') + '</td>';
            })()
            + '<td style="padding:5px 8px;text-align:right;color:var(--dhq-text-dim);font-size:0.7rem;">' + (a.dispatches_24h || 0).toLocaleString() + '</td>';
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
                + '<div style="text-align:center;">'
                + '<div style="font-size:0.85rem;font-weight:600;color:#a78bfa;">' + _dhqFmtTok(s.tokens_used) + '</div>'
                + '<div style="font-size:0.65rem;color:var(--dhq-text-dim);">tokens</div>'
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

// Compact token formatter (1.1M / 125k / 940) — COORD-5, so K.I.N. WELFARE/PERFORMANCE
// show the same token signal as the ARMADA tab.
function _dhqFmtTok(n) {
    n = Number(n) || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return Math.round(n / 1e3) + 'k';
    return String(n);
}

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
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val" style="color:#a78bfa;">' + _dhqFmtTok(m.live_tokens_7d) + '</span><span class="dhq-perf-metric-label">Tokens (7d)</span></div>'
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

        // #3947: per-product tenant scores + compute carbon (multi-tenant launch).
        // Both sections fail soft — the rest of the tab renders without them.
        var tenantHtml = '';
        try {
            var td = await api('/api/creed/tenants');
            if (td.success && td.tenants && td.tenants.length) {
                tenantHtml += '<div class="dhq-ad-section-title" style="color:#00ffff">PRODUCT TENANT SCORES — C.R.E.E.D.</div>'
                    + '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:0.5rem;margin:0.5rem 0 0.8rem">';
                for (var ti = 0; ti < td.tenants.length; ti++) {
                    var t = td.tenants[ti];
                    if (t.status !== 'active') continue;
                    var pub = t.listing === 'public';
                    var scoreTxt = t.provisional
                        ? 'PROVISIONAL · ' + (t.events_30d || 0) + ' ev'
                        : (t.overall != null ? t.overall.toFixed(1) + ' · ' + esc(t.grade || '') : '—');
                    tenantHtml += '<div class="dhq-creed-card">'
                        + '<div class="dhq-creed-header"><span class="dhq-creed-dept">' + esc(t.name || t.slug) + '</span>'
                        + '<span style="font-size:0.6rem;padding:1px 6px;border-radius:8px;border:1px solid '
                        + (pub ? '#22c55e' : 'rgba(255,255,255,0.25)') + ';color:' + (pub ? '#22c55e' : 'var(--dhq-text-dim)') + '">'
                        + (pub ? 'PUBLIC' : 'PREVIEW') + '</span></div>'
                        + '<div style="display:flex;justify-content:space-between;font-size:0.75rem;margin-top:0.3rem">'
                        + '<span class="' + (t.provisional || t.overall == null ? '' : creedClass(t.overall)) + '">' + scoreTxt + '</span>'
                        + '<span style="color:var(--dhq-text-dim)">' + (t.events_30d != null ? t.events_30d + ' ev/30d' : '') + '</span></div>'
                        + (t.last_event_at
                            ? '<div style="font-size:0.65rem;color:var(--dhq-text-dim);margin-top:0.2rem">last event ' + esc(String(t.last_event_at).slice(0, 16).replace('T', ' ')) + '</div>'
                            : '')
                        + '</div>';
                }
                tenantHtml += '</div>';
            }
        } catch (e) { /* tenant panel optional */ }
        try {
            var cs = await api('/api/creed/carbon-summary');
            if (cs.success) {
                var ep = cs.env_pillar || {};
                tenantHtml += '<div style="display:flex;gap:1.2rem;flex-wrap:wrap;align-items:center;font-size:0.75rem;margin-bottom:1rem;padding:0.5rem 0.8rem;border:1px solid rgba(34,197,94,0.3);border-radius:8px">'
                    + '<span style="color:#22c55e;font-weight:600">🌱 COMPUTE CARBON 24H</span>'
                    + '<span>' + cs.kwh_24h + ' kWh</span>'
                    + '<span>' + (cs.co2_kg_24h * 1000).toFixed(0) + ' g CO₂e</span>'
                    + '<span>' + cs.runs_24h + ' inference runs</span>'
                    + '<span style="color:var(--dhq-text-dim)">env pillar: ' + (ep.events != null ? ep.events : '?') + '/' + (ep.min_events || 100) + ' events'
                    + (ep.provisional ? ' (provisional)' : '') + '</span>'
                    + '</div>';
            }
        } catch (e) { /* carbon strip optional */ }

        // AI-workforce welfare score (#379 Phase 5) — the org's self-accountability surface.
        try {
            var wf = await api('/api/creed/welfare');
            if (wf.success) {
                var wc = wf.score >= 90 ? '#22c55e' : wf.score >= 80 ? '#22d3ee' : wf.score >= 70 ? '#f59e0b' : '#ef4444';
                var wfHtml = '<div class="dhq-ad-section-title" style="color:#00ffff">AI-WORKFORCE WELFARE — how we treat our own agents</div>'
                    + '<div style="border:1px solid rgba(255,255,255,0.14);border-radius:10px;padding:0.7rem 0.9rem;margin:0.4rem 0 1rem">'
                    + '<div style="display:flex;align-items:center;gap:0.8rem;flex-wrap:wrap">'
                    + '<span style="font-family:Orbitron,sans-serif;font-size:1.3rem;font-weight:700;color:' + wc + '">' + (wf.score != null ? wf.score : '—') + ' · ' + esc(wf.grade || '') + '</span>'
                    + '<span style="font-size:0.75rem;color:var(--dhq-text-dim)">' + (wf.active_agents || 0) + ' active · ' + (wf.healthy_pct != null ? wf.healthy_pct : '—') + '% within bounds · ' + (wf.break_honored_pct != null ? wf.break_honored_pct : '—') + '% breaks honored' + (wf.needed_break ? ' · ' + wf.needed_break + ' over a limit' : '') + '</span>'
                    + '</div>';
                var wrecs = wf.recommendations || [];
                if (wrecs.length) {
                    wfHtml += '<div style="margin-top:0.5rem">';
                    for (var ri = 0; ri < wrecs.length; ri++) {
                        var rsev = wrecs[ri].severity === 'critical' ? '#ef4444' : '#f59e0b';
                        wfHtml += '<div style="font-size:0.78rem;color:#cbd5e1;padding:0.3rem 0;border-top:1px solid rgba(255,255,255,0.06)">'
                            + '<span style="color:' + rsev + ';font-size:0.6rem;text-transform:uppercase;letter-spacing:0.05em;margin-right:0.5rem">' + esc(wrecs[ri].severity || '') + '</span>'
                            + esc(wrecs[ri].detail || '') + '</div>';
                    }
                    wfHtml += '</div>';
                } else {
                    wfHtml += '<div style="font-size:0.75rem;color:#22c55e;margin-top:0.4rem">No issues — workforce within healthy bounds.</div>';
                }
                wfHtml += '</div>';
                tenantHtml += wfHtml;
            }
        } catch (e) { /* welfare panel optional */ }

        if (!data.departments || data.departments.length === 0) {
            setHtml(el, tenantHtml + '<div class="dhq-empty">No C.R.E.E.D. data available yet.</div>');
            return;
        }

        var html = tenantHtml
            + '<div style="margin-bottom:1rem;font-size:0.8rem;color:var(--dhq-text-dim)">'
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

        // ── Fleet Node Health Grid ─────────────────────────────────
        try {
            var fleet = await api('/api/creed/fleet-agents');
            if (fleet.success && fleet.nodes && fleet.nodes.length > 0) {
                html += '<div class="dhq-ad-section" style="margin-top:1rem">';
                html += '<div class="dhq-ad-section-title" style="color:#22d3ee">FLEET NODE HEALTH</div>';
                html += '<div style="font-size:0.72rem;color:var(--dhq-text-dim);margin-bottom:0.5rem">'
                    + fleet.total_nodes + ' nodes · ' + fleet.total_agents + ' AI agents across cluster</div>';
                html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:0.5rem">';
                for (var fi = 0; fi < fleet.nodes.length; fi++) {
                    var nd = fleet.nodes[fi];
                    var ndColor = nd.status === 'red' ? '#ef4444' : nd.status === 'yellow' ? '#fbbf24' : '#10b981';
                    html += '<div style="background:var(--dhq-card-bg,#111827);border:1px solid ' + ndColor + '55;border-radius:6px;padding:0.5rem">'
                        + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem">'
                        + '<span style="color:' + ndColor + ';font-weight:bold;font-size:0.8rem;text-transform:uppercase">'
                        + esc(nd.node_name) + '</span>'
                        + '<span style="color:' + ndColor + ';font-size:0.7rem">' + nd.online_count + ' online</span>'
                        + '</div>'
                        + '<div style="background:#1a1a2e;border-radius:3px;height:4px;margin:0.25rem 0">'
                        + '<div style="background:' + ndColor + ';height:100%;border-radius:3px;width:' + Math.min(100, Math.round(nd.avg_stress * 100)) + '%"></div>'
                        + '</div>'
                        + '<div style="color:#666;font-size:0.65rem">'
                        + 'avg stress ' + (nd.avg_stress * 100).toFixed(0) + '%'
                        + (nd.in_rest_count > 0 ? ' · ' + nd.in_rest_count + ' resting' : '')
                        + (nd.active_overflow_bids > 0 ? ' · ' + nd.active_overflow_bids + ' overflow bids' : '')
                        + '</div></div>';
                }
                html += '</div></div>';
            }
        } catch(e) { /* fleet data not critical */ }

        // ── Overflow Activation Timeline ──────────────────────────
        try {
            var ov = await api('/api/creed/overflow-activations');
            if (ov.success && ov.events && ov.events.length > 0) {
                html += '<div class="dhq-ad-section" style="margin-top:1rem">';
                html += '<div class="dhq-ad-section-title" style="color:#a78bfa">OVERFLOW SKILL ACTIVATIONS</div>';
                html += '<div style="font-size:0.72rem;color:var(--dhq-text-dim);margin-bottom:0.5rem">'
                    + ov.count + ' events logged · last 50 shown</div>';
                html += '<div id="creedOverflowRows">';
                var ovShow = Math.min(10, ov.events.length);
                for (var oi2 = 0; oi2 < ov.events.length; oi2++) {
                    var ovEv = ov.events[oi2];
                    var ovColor = '#6b7280';
                    var ovLabel = ovEv.event_type;
                    if (ovEv.event_type === 'overflow_skill_activated')   { ovColor = '#22d3ee'; ovLabel = 'ACTIVATED'; }
                    if (ovEv.event_type === 'overflow_skill_deactivated') { ovColor = '#6b7280'; ovLabel = 'DEACTIVATED'; }
                    if (ovEv.event_type === 'overflow_welfare_blocked')   { ovColor = '#f97316'; ovLabel = 'WELFARE BLOCKED'; }
                    if (ovEv.event_type === 'overflow_mass_activation')   { ovColor = '#fbbf24'; ovLabel = 'MASS ACTIVATION'; }
                    var capability = (ovEv.new_value && ovEv.new_value.capability)
                        ? ovEv.new_value.capability
                        : (ovEv.old_value && ovEv.old_value.capability ? ovEv.old_value.capability : '');
                    var tsFormatted = ovEv.timestamp
                        ? (typeof ArchieTime !== 'undefined' ? ArchieTime.format(ovEv.timestamp, 'datetime') : ovEv.timestamp)
                        : '';
                    var rowStyle = oi2 >= ovShow ? 'display:none' : '';
                    html += '<div class="dhq-welfare-item" style="' + rowStyle + 'padding:0.3rem 0;border-bottom:1px solid #ffffff0a">'
                        + '<span style="background:' + ovColor + '22;color:' + ovColor + ';border:1px solid ' + ovColor + '44;'
                        + 'border-radius:3px;padding:0.1rem 0.3rem;font-size:0.65rem;font-weight:600;min-width:130px;display:inline-block">'
                        + esc(ovLabel) + '</span>'
                        + '<span style="color:#ccc;margin:0 0.5rem;font-size:0.75rem">'
                        + esc(ovEv.display_name || ovEv.agent_name) + '</span>'
                        + (capability ? '<span style="color:#22d3ee;font-size:0.7rem">' + esc(capability) + '</span>' : '')
                        + '<span style="color:#666;font-size:0.65rem;margin-left:auto;float:right">' + esc(tsFormatted) + '</span>'
                        + '</div>';
                }
                html += '</div>';
                if (ov.events.length > 10) {
                    html += '<div style="margin-top:0.4rem">'
                        + '<button onclick="creedToggleOverflow(this,' + ov.events.length + ')" '
                        + 'style="background:transparent;border:1px solid #a78bfa55;color:#a78bfa;'
                        + 'padding:0.2rem 0.6rem;border-radius:4px;font-size:0.7rem;cursor:pointer">'
                        + 'Show all ' + ov.events.length + ' events</button></div>';
                }
                html += '</div>';
            }
        } catch(e) { /* overflow timeline not critical */ }

        // ── Standalone Link ────────────────────────────────────────
        html += '<div style="margin-top:1.25rem;padding:0.75rem;background:#0a0a1a;border:1px solid #22d3ee33;'
            + 'border-radius:6px;display:flex;align-items:center;justify-content:space-between">'
            + '<div>'
            + '<div style="color:#22d3ee;font-weight:bold;font-size:0.8rem">C.R.E.E.D. INSTITUTE</div>'
            + '<div style="color:#666;font-size:0.7rem;margin-top:0.2rem">Public governance dashboard · creed-ai.org</div>'
            + '</div>'
            + '<a href="https://creed.kytranempowerment.com" target="_blank" rel="noopener" '
            + 'style="background:#22d3ee22;border:1px solid #22d3ee66;color:#22d3ee;padding:0.3rem 0.8rem;'
            + 'border-radius:4px;font-size:0.75rem;text-decoration:none;white-space:nowrap">'
            + 'Open C.R.E.E.D. Institute →</a>'
            + '</div>';

        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading C.R.E.E.D.: ' + esc(err.message) + '</div>');
    }
}

function creedToggleOverflow(btn, total) {
    var rows = document.querySelectorAll('#creedOverflowRows .dhq-welfare-item');
    var hidden = Array.prototype.some.call(rows, function(r) { return r.style.display === 'none'; });
    rows.forEach(function(r) { r.style.display = hidden ? '' : 'none'; });
    if (hidden) {
        btn.textContent = 'Show fewer';
        // re-show first 10 is already done (all revealed)
    } else {
        for (var i = 0; i < Math.min(10, rows.length); i++) rows[i].style.display = '';
        btn.textContent = 'Show all ' + total + ' events';
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

        // ── Curated Facts (persona grounding — #4959) ──
        html += '<div class="dhq-ad-section" id="factsSection" data-agent-id="' + a.id + '">'
            + '<div class="dhq-ad-section-title">Curated Facts '
            + '<span style="font-weight:normal;font-size:0.7rem;color:var(--dhq-text-dim)">(persona may cite these in email drafts)</span>'
            + '</div>'
            + '<div id="agentFactsList"><div class="dhq-loading" style="padding:0.3rem">Loading facts...</div></div>'
            + '<div class="dhq-fact-add" style="display:flex;gap:0.4rem;margin-top:0.5rem;flex-wrap:wrap">'
            + '<input id="agentFactInput" class="dhq-input" type="text" placeholder="e.g. Standard onboarding SLA is 3 business days." style="flex:2;min-width:180px">'
            + '<input id="agentFactCategory" class="dhq-input" type="text" placeholder="category (optional)" style="flex:1;min-width:120px">'
            + '<button class="dhq-btn-sm" onclick="addAgentFact(' + a.id + ')">Add</button>'
            + '</div></div>';

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
        // Load curated facts (persona grounding — #4959)
        loadAgentFacts(a.id);
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
// Curated Facts (persona grounding — #4959)
// ───────────────────────────────────────────────────────────────

async function loadAgentFacts(agentId) {
    var host = document.getElementById('agentFactsList');
    if (!host) return;
    host.textContent = 'Loading…';
    var resp = await api('/api/agent/' + agentId + '/facts');
    var facts = (resp && resp.facts) || [];
    host.textContent = '';
    if (!facts.length) {
        var empty = document.createElement('div');
        empty.className = 'dhq-muted';
        empty.textContent = 'No curated facts yet. Add facts this persona may cite in email drafts.';
        host.appendChild(empty);
        return;
    }
    facts.forEach(function (f) {
        var row = document.createElement('div');
        row.className = 'dhq-fact-row' + (f.is_active ? '' : ' dhq-fact-inactive');
        var txt = document.createElement('span');
        txt.className = 'dhq-fact-text';
        txt.textContent = f.fact_text + (f.category ? ' [' + f.category + ']' : '');
        var toggle = document.createElement('button');
        toggle.className = 'dhq-btn-sm';
        toggle.textContent = f.is_active ? 'Deactivate' : 'Activate';
        toggle.onclick = async function () {
            await apiPost('/api/agent/facts/' + f.id + '/toggle', { is_active: !f.is_active });
            loadAgentFacts(agentId);
        };
        var del = document.createElement('button');
        del.className = 'dhq-btn-sm dhq-btn-danger';
        del.textContent = 'Delete';
        del.onclick = async function () {
            await apiPost('/api/agent/facts/' + f.id + '/delete', {});
            loadAgentFacts(agentId);
        };
        row.appendChild(txt);
        row.appendChild(toggle);
        row.appendChild(del);
        host.appendChild(row);
    });
}

async function addAgentFact(agentId) {
    var input = document.getElementById('agentFactInput');
    var cat = document.getElementById('agentFactCategory');
    var text = (input && input.value || '').trim();
    if (!text) return;
    await apiPost('/api/agent/' + agentId + '/facts', {
        fact_text: text,
        category: (cat && cat.value || '').trim() || null,
    });
    if (input) input.value = '';
    if (cat) cat.value = '';
    loadAgentFacts(agentId);
}

// ───────────────────────────────────────────────────────────────
// Social Feed (global tab)
// ───────────────────────────────────────────────────────────────

// ── S.I.G.N.A.L. Command Center state ───────────────────────────
var signalAccount = 'personal';
var signalTab = 'overview';
var _signalTabCache = {};   // {tab: {html, ts}} — persists across sub-tab switches
var _signalTabTTL = { overview: 30, postlog: 60, pending: 15, hashtags: 120, calendar: 30, themes: 600, session: 10, comments: 30 };
var _signalLastRun = {};  // {account: timestamp} — per-account Run Now cooldown
// Phase 5: setInterval handle for live calendar polling. Cleared on every
// loadSignalTab() entry; re-established at the end of loadSignalTab('calendar').
var _signalCalendarPollHandle = null;

async function loadSocialFeed() {
    var el = document.getElementById('socialFeedContent');
    if (!el) return;
    loaded['social'] = true;
    setHtml(el, renderSignalShell());
    refreshSignalAccountBar();  // 5b: data-driven roster + health dots (non-blocking; fallback-safe)
    await loadSignalTab('overview');
    loadSignalPendingBadge();
}

function renderSignalShell() {
    return '<div class="signal-accounts">'
        + '<button class="signal-acct-btn active" data-account="personal" onclick="switchSignalAccount(\'personal\')">👤 Kytran Katarn</button>'
        + '<button class="signal-acct-btn" data-account="terry" onclick="switchSignalAccount(\'terry\')">👤 Terry Caetano</button>'
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
        + '<button class="signal-sub" data-sub="comments" onclick="switchSignalTab(\'comments\')">💬 Comments</button>'
        + '<button class="signal-sub" data-sub="engage" onclick="switchSignalTab(\'engage\')">🎯 Engage</button>'
        + '<button class="signal-sub" data-sub="themes" onclick="switchSignalTab(\'themes\')">Themes</button>'
        + '<button class="signal-sub" data-sub="session" onclick="switchSignalTab(\'session\')">🔐 Session</button>'
        + '</div>'
        + '<div id="signalContent" class="dhq-loading" style="min-height:200px">Loading...</div>';
}

// ── 5b: data-driven account bar + per-account health dot (scale roster) ──
// renderSignalShell() paints a hardcoded fallback bar synchronously; this then
// rebuilds it from the registry roster (GET /api/signal/accounts/health) so ARCHIE +
// any supporting agent appear as DATA with an honest status dot. On ANY API failure the
// hardcoded fallback bar is left intact — no regression.
// #5627: `posting_failing` is the OUTPUT-derived state — the session row claims it is
// authed but no post has actually published in 24h while failures have. On 2026-08-15
// this bar showed a GREEN dot for Kytran/342 all day while every post hit a login wall,
// because health was read purely from the profile's self-report. A dot must never be
// greener than the thing it describes.
var _signalHealthColors = {
    healthy: '#22c55e', probe_warn: '#f59e0b', posting_failing: '#ef4444',
    logged_out: '#ef4444', not_established: '#9ca3af', unknown: '#9ca3af'
};
var _signalHealthTitle = {
    healthy: 'Authed + posting', probe_warn: 'Authed on disk — probe flaky (#4372)',
    posting_failing: 'Session looks authed but posts are FAILING — check the post log',
    logged_out: 'Logged out — re-auth via the Session tab',
    not_established: 'Registered — awaiting one-time login', unknown: 'Unknown'
};

async function refreshSignalAccountBar() {
    var bar = document.querySelector('.signal-accounts');
    if (!bar) return;
    var data;
    try { data = await api('/api/signal/accounts/health'); } catch (e) { return; }
    var accts = (data && data.accounts) || [];
    if (!accts.length) return;   // keep the hardcoded fallback bar
    var html = '';
    accts.forEach(function(a) {
        var color = _signalHealthColors[a.health] || '#9ca3af';
        var dot = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            + 'background:' + color + ';margin-right:6px;vertical-align:middle"></span>';
        var clickable = a.profile_established && a.can_post;
        var fa = Number(a.failing_approvals) || 0;
        var cls = 'signal-acct-btn' + (a.account_key === signalAccount ? ' active' : '');
        var title = esc((_signalHealthTitle[a.health] || a.health || '') + (fa ? ' — ' + fa + ' failing' : ''));
        // NO inline onclick built from data (XSS-safe) — clicks are handled by the
        // delegated listener below, which reads the esc()'d data-account attribute.
        var attrs = ' data-account="' + esc(a.account_key) + '" title="' + title + '"';
        if (!clickable) { attrs += ' disabled style="opacity:0.5;cursor:default"'; }
        var warn = fa ? ' <span style="color:#ef4444;font-weight:600">&#9888;' + fa + '</span>' : '';
        html += '<button class="' + cls + '"' + attrs + '>' + dot + esc(a.label || a.account_key) + warn + '</button>';
    });
    setHtml(bar, html);
    // Event delegation — one idempotent listener reads the data-account attribute and
    // calls switchSignalAccount. No executable string is ever built from registry data.
    bar.onclick = function(e) {
        var btn = e.target.closest('button[data-account]');
        if (!btn || btn.disabled) return;
        switchSignalAccount(btn.getAttribute('data-account'));
    };
}

/* ── S.I.G.N.A.L. SESSION sub-tab (#3953/#3948/#3982) — persistent trusted
   LinkedIn sessions, one card per browser identity. Profile 342 = the Kytran
   login (personal + KE Inc. + Creed-AI pages, actor-switched inside one
   session). Profile 377 = Terry Caetano (a SEPARATE LinkedIn login → its own
   persistent profile + one-time noVNC login). Only one login browser runs at
   a time. ── */
var SIGNAL_SESSION_IDENTITIES = [
    { agentId: 342, platform: 'linkedin', label: 'KYTRAN SESSION — PROFILE 342', note: 'Kytran Katarn personal + KE Inc. + Creed-AI pages (one login, actor-switched)' },
    { agentId: 377, platform: 'linkedin', label: 'TERRY CAETANO SESSION — PROFILE 377', note: 'Terry Caetano personal account (separate LinkedIn login)' },
    { agentId: 379, platform: 'linkedin', label: 'S.T.R.I.N.G.E.R. SESSION — PROFILE 379', note: 'What The Fact journalist account, press@what-the-fact.com (separate LinkedIn login, #4610)' }
];
// #3982 multi-site: mirrors the login sidecar's platform allowlist.
var SIGNAL_SESSION_PLATFORMS = ['linkedin', 'x', 'claude', 'deepseek'];
// Extra (agent, platform) combo loaded via the picker — S.C.O.U.T./multi-site.
var _signalExtraSession = null;

async function renderSignalSession(el) {
    // Account-aware: the selected account's session card renders FIRST and is
    // badged. terry = its own login (377); Kytran/KE/Creed all post through
    // the Kytran session (342) via the actor switcher.
    var activeId = (signalAccount === 'terry') ? 377 : (signalAccount === 'stringer') ? 379 : 342;
    var idns = SIGNAL_SESSION_IDENTITIES.slice().sort(function(a, b) {
        return (b.agentId === activeId ? 1 : 0) - (a.agentId === activeId ? 1 : 0);
    });
    if (_signalExtraSession) {
        idns.push({
            agentId: _signalExtraSession.agentId,
            platform: _signalExtraSession.platform,
            label: 'AGENT ' + _signalExtraSession.agentId + ' — ' + _signalExtraSession.platform.toUpperCase() + ' (picker)',
            note: 'Loaded via the session picker — S.C.O.U.T. / multi-site device-trust profile'
        });
    }
    var blocks = await Promise.all(idns.map(async function(idn) {
        var plat = idn.platform || 'linkedin';
        try {
            var r = await fetch('/tools/department-hq/api/social/linkedin/session-status?agent_id=' + idn.agentId
                + '&platform=' + encodeURIComponent(plat));
            return renderOneSignalSession(idn, await r.json(), idn.agentId === activeId && plat === 'linkedin');
        } catch (e) {
            return '<div class="dhq-empty" style="text-align:left">' + esc(idn.label) + ': status unavailable</div>';
        }
    }));
    var picker = '<div style="margin-top:18px;padding-top:12px;border-top:2px solid #1e293b">'
        + '<h4 style="font-family:Antonio,sans-serif;letter-spacing:1px;margin:0 0 6px">LOAD ANOTHER SESSION (#3982)</h4>'
        + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
        + '<input id="sessPickAgent" type="number" min="1" placeholder="agent id" value="' + (_signalExtraSession ? _signalExtraSession.agentId : '') + '" '
        + 'style="width:110px;background:#0b1220;border:1px solid #1e293b;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit">'
        + '<select id="sessPickPlatform" class="dhq-select">'
        + SIGNAL_SESSION_PLATFORMS.map(function(p) {
            return '<option value="' + p + '"' + (_signalExtraSession && _signalExtraSession.platform === p ? ' selected' : '') + '>' + p + '</option>';
        }).join('')
        + '</select>'
        + '<button class="dhq-btn" onclick="signalSessionLookup()">Load session card</button>'
        + '</div></div>';
    setHtml(el, '<div style="max-width:720px">'
        + '<h3 style="font-family:Antonio,sans-serif;letter-spacing:1px;margin:0 0 10px">TRUSTED BROWSER SESSIONS</h3>'
        + blocks.join('<hr style="border:none;border-top:2px solid #1e293b;margin:22px 0">')
        + picker
        + '</div>');
}

async function signalSessionLookup() {
    var aid = parseInt(document.getElementById('sessPickAgent').value, 10);
    var plat = document.getElementById('sessPickPlatform').value;
    if (!aid || aid < 1) { alert('Enter a valid agent id'); return; }
    _signalExtraSession = { agentId: aid, platform: plat };
    await loadSignalTab('session', true);
}

function _signalIdentityBanner(d, aid, plat) {
    // "Which login is this, and what goes down with it?" — the two questions the
    // card could not answer (#5627 follow-up). Profile 342 alone carries Kytran
    // Katarn + Kytran Empowerment Inc. + Creed-AI, which is why ONE logged-out
    // profile read as four broken accounts on 2026-08-15.
    var accts = d.serves_accounts || [];
    if (!accts.length) return '';
    var posting = accts.filter(function(a) { return a.can_post; });
    var stale = (d.db_session || {}).status === 'stale';
    var names = accts.map(function(a) {
        return '<span style="display:inline-block;background:#0b1220;border:1px solid #1e293b;'
            + 'border-radius:4px;padding:1px 7px;margin:2px 4px 2px 0;font-size:0.72rem">'
            + esc(a.display_label || a.account_key)
            + (a.can_post ? '' : ' <span style="color:#64748b">(no post)</span>') + '</span>';
    }).join('');
    var head = stale
        ? '<span style="color:#ef4444">⛔ ' + posting.length + ' account'
          + (posting.length === 1 ? '' : 's') + ' PAUSED — this profile is logged out</span>'
        : '<span style="color:#22c55e">● ' + posting.length + ' account'
          + (posting.length === 1 ? '' : 's') + ' post through this one login</span>';
    return '<div style="border:1px solid ' + (stale ? '#7f1d1d' : '#1e293b') + ';border-radius:6px;'
        + 'padding:8px 10px;margin:0 0 10px;background:' + (stale ? 'rgba(127,29,29,0.12)' : 'transparent') + '">'
        + '<div style="font-size:0.78rem;margin-bottom:4px">' + head + '</div>'
        + '<div>' + names + '</div>'
        + (stale
            ? '<div style="font-size:0.72rem;color:#f59e0b;margin-top:6px">Their posts stay <b>scheduled</b> '
              + '(not failed) until this profile is authenticated again — nothing is lost.</div>'
            : '')
        + '</div>';
}

function renderOneSignalSession(idn, d, isActive) {
    var aid = idn.agentId;
    var plat = idn.platform || 'linkedin';
    var key = aid + '_' + plat;
    var db = d.db_session || {};
    var ls = d.login_surface || {};
    var profileOk = !!ls.profile_established;
    var loginRunning = !!ls.login_browser_running;
    // #5712: noVNC is LAN/mesh-ONLY by design (headed browser with logged-in
    // social sessions) — the public domain fronts through Beacon, which has no
    // :4280 listener. Inheriting location.hostname handed anyone browsing via
    // platform.kytranempowerment.com a dead link with no explanation (owner
    // hit ERR_CONNECTION_ABORTED live during the #5627 re-login). Only keep
    // the page hostname when it is ALREADY the LAN or mesh IP; otherwise
    // default to the LAN IP and show the mesh alternative beside the button.
    var _vncHost = (location.hostname === '192.168.1.200' || location.hostname === '100.64.0.4')
        ? location.hostname : '192.168.1.200';
    var novncUrl = 'http://' + _vncHost + ':4280/vnc.html';
    var novncMeshUrl = 'http://100.64.0.4:4280/vnc.html';

    return '<h4 style="font-family:Antonio,sans-serif;letter-spacing:1px;margin:0 0 4px">' + esc(idn.label)
        + (isActive
            ? ' <span style="font-size:0.62rem;color:#0b1220;background:#22d3ee;border-radius:4px;'
              + 'padding:2px 7px;vertical-align:middle;letter-spacing:1px">'
              + esc(_signalAccountLabel(signalAccount)) + ' POSTS WITH THIS SESSION</span>'
            : '')
        + '</h4>'
        + '<p class="dhq-empty" style="text-align:left;margin:0 0 8px;font-size:0.78rem">' + esc(idn.note) + '</p>'
        // WHICH LOGIN + WHAT IT TAKES DOWN (#5627 follow-up). Without these two lines
        // the card said "342 · stale" and left you to work out both the account to log
        // in as and the fact that THREE S.I.G.N.A.L. accounts ride this one profile.
        + _signalIdentityBanner(d, aid, plat)
        + '<table class="dhq-table" style="width:100%;margin-bottom:14px"><tbody>'
        + '<tr><td>Log in as</td><td>' + (d.stored_login
            ? '<code style="background:#0b1220;border:1px solid #1e293b;border-radius:4px;padding:1px 6px;'
              + 'font-family:IBM Plex Mono,monospace;color:#e2e8f0">' + esc(d.stored_login) + '</code>'
            : '<span style="color:#94a3b8">not recorded — enter it under STORE LOGIN below</span>') + '</td></tr>'
        + '<tr><td>Automated re-login</td><td>' + (d.auto_relogin_armed === true
            ? '<span style="color:#22c55e">● ARMED</span> <span style="color:#94a3b8;font-size:0.75rem">'
              + '— repairs itself on the next logged-out run; noVNC only if LinkedIn asks for phone/CAPTCHA</span>'
            : (d.auto_relogin_armed === false
                ? '<span style="color:#94a3b8">○ manual only</span> <span style="color:#94a3b8;font-size:0.75rem">'
                  + '— every logout needs a hand-done noVNC login until a password is stored</span>'
                : '<span style="color:#f59e0b">? unknown</span>')) + '</td></tr>'
        + '<tr><td>Persistent profile (device-trusted)</td><td>'
        + (profileOk ? '<span style="color:#22c55e">● ESTABLISHED</span>'
                     : '<span style="color:#ef4444">● NOT ESTABLISHED — one-time login required</span>') + '</td></tr>'
        + '<tr><td>DB session (storage_state export)</td><td>' + esc(db.status || 'none')
        + (db.last_used_at ? ' · last used ' + esc(String(db.last_used_at).slice(0, 16)) : '') + '</td></tr>'
        + (db.last_failure_reason ? '<tr><td>Last failure</td><td style="color:#f59e0b">' + esc(db.last_failure_reason) + '</td></tr>' : '')
        + '<tr><td>Login browser</td><td>' + (loginRunning
            ? '<span style="color:#22d3ee">RUNNING (' + (ls.seconds_running || 0) + 's) — finish in noVNC, then Stop</span>'
            : 'idle') + '</td></tr>'
        + '</tbody></table>'
        + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
        + (loginRunning
            ? '<a class="dhq-btn dhq-btn-primary" target="_blank" rel="noopener" href="' + novncUrl + '">Open noVNC → log in</a>'
              + '<span style="font-size:0.72rem;color:#94a3b8">LAN/mesh only — plain http. Away from home? use '
              + '<a target="_blank" rel="noopener" style="color:#22d3ee" href="' + novncMeshUrl + '">the mesh address</a></span>'
              + '<button class="dhq-btn" onclick="signalSessionLoginStop()">Stop & save profile</button>'
            : '<button class="dhq-btn dhq-btn-primary" onclick="signalSessionLoginStart(' + aid + ', \'' + plat + '\')">Start one-time login</button>')
        + '<button class="dhq-btn" onclick="loadSignalTab(\'session\', true)">↻ Refresh</button>'
        + '</div>'
        + (loginRunning && d.vnc_password
            ? '<p style="margin-top:10px;text-align:left;font-size:0.8rem">noVNC password (paste when prompted): '
              + '<code style="background:#0b1220;border:1px solid #1e293b;border-radius:4px;padding:2px 8px;'
              + 'font-family:IBM Plex Mono,monospace;color:#22d3ee">' + esc(d.vnc_password) + '</code></p>'
            : '')
        + '<p class="dhq-empty" style="margin-top:12px;text-align:left">Start → a headed browser opens on the hub\'s '
        + 'trusted home egress using THIS profile. Open noVNC, log into the matching ' + esc(plat) + ' account (complete any '
        + '2FA), then Stop — the profile keeps the device fingerprint and this account\'s posting flows use it '
        + 'automatically. Auto-stops after ' + Math.round((ls.idle_timeout_s || 900) / 60) + ' min idle.</p>'
        + (d.login_surface_error ? '<p class="dhq-empty" style="text-align:left;color:#f59e0b">Login surface: ' + esc(d.login_surface_error) + '</p>' : '')
        + '<h4 style="font-family:Antonio,sans-serif;letter-spacing:1px;margin:14px 0 6px">STORE LOGIN (encrypted)</h4>'
        + '<p class="dhq-empty" style="text-align:left;margin:0 0 8px;font-size:0.78rem">Stored AES-encrypted in the browser credential store — NOT in .env. '
        + 'Used by the fleet for automated re-login; the one-time trusted login above is still done by hand in noVNC.</p>'
        + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;max-width:560px">'
        // Prefilled with the login already on file so re-arming is one field, and so
        // the account this profile belongs to is visible without guessing.
        + '<input id="liCredUser_' + key + '" type="text" autocomplete="off" placeholder="' + esc(plat) + ' email" '
        + 'value="' + esc(d.stored_login || '') + '" '
        + 'style="flex:1 1 200px;background:#0b1220;border:1px solid #1e293b;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit">'
        + '<input id="liCredPass_' + key + '" type="password" autocomplete="new-password" placeholder="' + esc(plat) + ' password" '
        + 'style="flex:1 1 200px;background:#0b1220;border:1px solid #1e293b;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit">'
        + '<button class="dhq-btn" onclick="signalSaveLinkedInCreds(' + aid + ', \'' + plat + '\')">Save encrypted</button>'
        + '<span id="liCredStatus_' + key + '" style="font-size:0.78rem;color:#94a3b8"></span>'
        + '</div>';
}

async function signalSaveLinkedInCreds(agentId, platform) {
    platform = platform || 'linkedin';
    var key = agentId + '_' + platform;
    var u = document.getElementById('liCredUser_' + key);
    var p = document.getElementById('liCredPass_' + key);
    var st = document.getElementById('liCredStatus_' + key);
    if (!u.value.trim() || !p.value) { st.textContent = 'Enter email + password.'; st.style.color = '#fca5a5'; return; }
    st.textContent = 'Saving…'; st.style.color = '#94a3b8';
    try {
        var r = await fetch('/tools/department-hq/api/social/linkedin/credentials', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: u.value.trim(), password: p.value, agent_id: agentId, platform: platform })
        });
        var d = await r.json();
        if (d.saved) { st.textContent = '✓ Stored encrypted'; st.style.color = '#34d399'; p.value = ''; }
        else { st.textContent = d.error || 'Save failed'; st.style.color = '#fca5a5'; }
    } catch (e) { st.textContent = 'Network error'; st.style.color = '#fca5a5'; }
}

async function signalSessionLoginStart(agentId, platform) {
    var r = await fetch('/tools/department-hq/api/social/linkedin/session-login/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId || 342, platform: platform || 'linkedin' })
    });
    var d = await r.json();
    if (!d.started && d.error) alert('Could not start login browser: ' + d.error);
    await loadSignalTab('session', true);
    if (d.started) window.open('http://' + location.hostname + ':4280/vnc.html', '_blank');
}

async function signalSessionLoginStop() {
    await fetch('/tools/department-hq/api/social/linkedin/session-login/stop', { method: 'POST' });
    await loadSignalTab('session', true);
}

/* ── S.I.G.N.A.L. COMMENTS sub-tab (#3992) — comment threads on our posts:
   READ ingest + draft-reply status. Replies post only via Telegram approve. ── */
var _SIGNAL_REPLY_STATUS_COLORS = {
    none: '#94a3b8', drafted: '#22d3ee', replied: '#22c55e',
    reply_failed: '#ef4444', skipped_own: '#555'
};

async function renderSignalComments(el) {
    var d;
    try {
        d = await api('/api/social/linkedin/comments?limit=50');
    } catch (e) {
        setHtml(el, '<div class="dhq-empty">Comments unavailable: ' + esc(e && e.message ? e.message : e) + '</div>');
        return;
    }
    var comments = d.comments || [];
    var rows = comments.map(function(c) {
        var col = _SIGNAL_REPLY_STATUS_COLORS[c.reply_status] || '#94a3b8';
        return '<tr>'
            + '<td style="white-space:nowrap">' + esc(c.author || '?')
            + '<div style="font-size:0.62rem;color:#64748b">' + esc((c.author_headline || '').slice(0, 60)) + '</div></td>'
            + '<td style="font-size:0.72rem">' + esc((c.body || '').slice(0, 180)) + ((c.body || '').length > 180 ? '…' : '')
            + (c.draft_reply ? '<div style="margin-top:4px;padding:4px 8px;border-left:2px solid #22d3ee;color:#94a3b8;font-size:0.68rem">↳ draft: '
              + esc(c.draft_reply.slice(0, 140)) + '…</div>' : '') + '</td>'
            + '<td style="white-space:nowrap"><span style="color:' + col + '">● ' + esc(c.reply_status || 'none') + '</span>'
            + '<div style="font-size:0.6rem;color:#64748b">' + esc(c.account || '') + '</div></td>'
            + '<td style="white-space:nowrap;font-size:0.62rem;color:#64748b">' + esc(String(c.first_seen_at || '').slice(0, 10)) + '</td>'
            + '</tr>';
    }).join('');
    setHtml(el, '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
        + '<h4 style="font-family:Antonio,sans-serif;letter-spacing:1px;margin:0">COMMENTS ON OUR POSTS (' + comments.length + ')</h4>'
        + '<div style="display:flex;gap:8px">'
        + '<button class="dhq-btn" onclick="signalCommentsPoll()">↻ Poll threads</button>'
        + '<button class="dhq-btn dhq-btn-primary" onclick="signalCommentsDraft()">✍ Draft replies</button>'
        + '</div></div>'
        + (comments.length
            ? '<table class="dhq-table" style="width:100%"><tbody>' + rows + '</tbody></table>'
            : '<div class="dhq-empty" style="text-align:left">No comments ingested yet. The 6-hour pipeline polls every '
              + 'post with a captured URL; Poll threads runs it now. Drafted replies go to Telegram for approval — '
              + 'nothing posts on its own.</div>'));
}

async function signalCommentsPoll() {
    try {
        var r = await apiPost('/api/social/linkedin/comments/refresh', {});
        alert('Polled ' + (r.posts_polled || 0) + ' post(s) — ' + (r.new_comments || 0) + ' new comment(s)');
    } catch (e) { alert('Poll failed: ' + (e && e.message ? e.message : e)); }
    await loadSignalTab('comments', true);
}

async function signalCommentsDraft() {
    try {
        var r = await apiPost('/api/social/linkedin/comments/draft-replies', {});
        alert('Drafted ' + (r.drafted || 0) + ' of ' + (r.candidates || 0) + ' candidate(s) — drafts await Telegram approval');
    } catch (e) { alert('Draft failed: ' + (e && e.message ? e.message : e)); }
    await loadSignalTab('comments', true);
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
            case 'session':   await renderSignalSession(el);   break;
            case 'comments':  await renderSignalComments(el);  break;
            case 'engage':    await renderSignalEngage(el);    break;
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
    refreshSignalCalendarStrip(signalAccount);  // fill the week strip with real scheduled counts
}

function _renderSignalCalendarHtml() {
    // Real current week (Mon→Sun), no fabricated themes. Each day carries a data-date so
    // refreshSignalCalendarStrip() can fill in the ACTUAL scheduled-post count per day for
    // the selected account (from /api/signal/calendar/scheduled). Empty days stay '—'.
    var labels = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
    var now = new Date();
    var dow = (now.getDay() + 6) % 7;  // Mon=0 … Sun=6
    var monday = new Date(now);
    monday.setDate(now.getDate() - dow);
    var html = '<div class="signal-calendar">';
    for (var i = 0; i < 7; i++) {
        var d = new Date(monday);
        d.setDate(monday.getDate() + i);
        var iso = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
        var cls = 'signal-cal-day' + (i === dow ? ' signal-cal-today' : '');
        html += '<div class="' + cls + '" data-date="' + iso + '">'
            + '<div class="signal-cal-label">' + labels[i] + '</div>'
            + '<div class="signal-cal-theme signal-cal-slot">—</div>'
            + '</div>';
    }
    return html + '</div>';
}

// Fill the Overview week strip with the REAL per-day scheduled-post count for `account`.
// Reads data only (numbers) — no executable string built from data. On API failure the
// strip stays as rendered (all '—') — honest empty, never fabricated.
async function refreshSignalCalendarStrip(account) {
    var strip = document.querySelector('.signal-calendar');
    if (!strip) return;
    var data;
    try { data = await api('/api/signal/calendar/scheduled?account=' + encodeURIComponent(account)); }
    catch (e) { return; }
    var posts = (data && data.posts) || [];
    var byDate = {};
    posts.forEach(function(p) {
        var d = (p.scheduled_at || '').slice(0, 10);
        if (d) byDate[d] = (byDate[d] || 0) + 1;
    });
    Array.prototype.forEach.call(strip.querySelectorAll('.signal-cal-day'), function(cell) {
        var n = byDate[cell.getAttribute('data-date')] || 0;
        var slot = cell.querySelector('.signal-cal-slot');
        if (n > 0) {
            cell.classList.add('signal-cal-active');
            if (slot) setHtml(slot, '● ' + n + (n > 1 ? ' posts' : ' post'));
        } else {
            cell.classList.remove('signal-cal-active');
            if (slot) setHtml(slot, '—');
        }
    });
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
        +     '<option value="terry">👤 Terry Caetano (personal)</option>'
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
        var labels = { personal: '👤 Kytran Katarn', terry: '👤 Terry Caetano', company: '🏢 Kytran Empowerment Inc.', creed: '⚖️ Creed-AI' };
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

/* ── S.I.G.N.A.L. ENGAGE sub-tab — approval-gated likes/comments + the auto
   engagement monitor. Everything only PROPOSES; actions fire after a Telegram/tab
   Approve. Acts as the selected account (top buttons). ── */
async function renderSignalEngage(el) {
    var st;
    try { st = await api('/api/social/signal/engagement'); }
    catch (e) { st = { targets: [], monitor_enabled: false, comments_enabled: false }; }
    var targets = (st.targets || []).join('\n');
    var _inputStyle = 'width:100%;padding:8px;margin-top:4px;background:#0a0e14;color:#e5e7eb;border:1px solid #243044;border-radius:4px;box-sizing:border-box';
    function _toggleBtn(flag, on, label) {
        return on
            ? '<button class="dhq-action-btn" style="background:#10b981;color:#04120b" onclick="toggleSignalEngagement(\'' + flag + '\', false, this)">' + label + ': ON</button>'
            : '<button class="dhq-action-btn" onclick="toggleSignalEngagement(\'' + flag + '\', true, this)">' + label + ': OFF</button>';
    }
    var html = '<div class="signal-compose">'
        + '<div class="signal-compose-header">🎯 Engage on LinkedIn via <strong>S.I.G.N.A.L.</strong></div>'
        + '<div class="signal-compose-note">Everything here only <strong>proposes</strong> — likes &amp; comments go to Telegram for your approval before anything posts. Acting as the account selected at the top.</div>'
        // ── Manual engage ──
        + '<div class="signal-compose-header" style="margin-top:16px;font-size:0.95em">Engage with a post</div>'
        + '<input id="signalEngageUrl" type="text" placeholder="LinkedIn post URL (…/feed/update/urn:li:activity:…)" style="' + _inputStyle + '">'
        + '<textarea id="signalEngageComment" class="dhq-textarea" rows="3" placeholder="(optional) comment text — leave blank to just propose a like" style="margin-top:8px"></textarea>'
        + '<div style="margin-top:8px;display:flex;gap:8px">'
        +   '<button class="dhq-action-btn dhq-action-primary" onclick="submitSignalEngage(\'like\')">👍 Propose Like</button>'
        +   '<button class="dhq-action-btn dhq-action-primary" onclick="submitSignalEngage(\'comment\')">💬 Propose Comment</button>'
        + '</div>'
        + '<div id="signalEngageResult" style="display:none;margin-top:10px"></div>'
        // ── Auto monitor ──
        + '<div class="signal-compose-header" style="margin-top:22px;font-size:0.95em">Auto-engagement monitor</div>'
        + '<div class="signal-compose-note">When ON, every 8h S.I.G.N.A.L. reads each target\'s latest post and proposes a like (plus a drafted comment if Auto-Comments is ON) — each queued for your Telegram approval.</div>'
        + '<div style="margin:8px 0;display:flex;gap:8px">' + _toggleBtn('monitor', st.monitor_enabled, 'Monitor') + _toggleBtn('comments', st.comments_enabled, 'Auto-Comments') + '</div>'
        + '<label class="signal-field-label">Target profiles / companies (one LinkedIn URL per line)</label>'
        + '<textarea id="signalEngageTargets" class="dhq-textarea" rows="4" placeholder="https://www.linkedin.com/in/someone&#10;https://www.linkedin.com/company/123456">' + esc(targets) + '</textarea>'
        + '<div style="margin-top:8px"><button class="dhq-action-btn dhq-action-primary" onclick="saveSignalEngageTargets()">Save Targets</button> <span id="signalTargetsResult" style="opacity:0.75;margin-left:8px"></span></div>'
        + '</div>';
    setHtml(el, html);
}

async function submitSignalEngage(action) {
    var url = (document.getElementById('signalEngageUrl').value || '').trim();
    var resultEl = document.getElementById('signalEngageResult');
    resultEl.style.display = 'block';
    if (!url) { setHtml(resultEl, '<div style="color:#ef4444">Enter a post URL.</div>'); return; }
    var body = { action: action, post_url: url, account: signalAccount };
    if (action === 'comment') {
        var c = (document.getElementById('signalEngageComment').value || '').trim();
        if (!c) { setHtml(resultEl, '<div style="color:#ef4444">Enter comment text to propose a comment.</div>'); return; }
        body.comment = c;
    }
    setHtml(resultEl, '<div class="dhq-loading" style="padding:6px">Proposing…</div>');
    try {
        var r = await apiPost('/api/social/signal/engage', body);
        setHtml(resultEl, '<div style="color:#10b981">✓ ' + esc(action) + ' queued for Telegram approval (#' + r.approval_id + ') — approve it to post.</div>');
        if (typeof loadSignalPendingBadge === 'function') loadSignalPendingBadge();
    } catch (err) {
        setHtml(resultEl, '<div style="color:#ef4444">Error: ' + esc(err.message) + '</div>');
    }
}

async function saveSignalEngageTargets() {
    var raw = (document.getElementById('signalEngageTargets').value || '')
        .split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    var out = document.getElementById('signalTargetsResult');
    out.textContent = 'Saving…';
    try {
        var r = await apiPost('/api/social/signal/targets', { targets: raw });
        out.textContent = '✓ Saved ' + r.count + ' target(s)';
        delete _signalTabCache['engage:' + signalAccount];
    } catch (err) {
        out.textContent = 'Error: ' + err.message;
    }
}

async function toggleSignalEngagement(flag, enabled, btn) {
    btn.disabled = true;
    try {
        await apiPost('/api/social/signal/engagement-toggle', { flag: flag, enabled: enabled });
        delete _signalTabCache['engage:' + signalAccount];
        loadSignalTab('engage', true);
    } catch (err) {
        btn.disabled = false;
        alert('Toggle failed: ' + err.message);
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

    // Phase 1 (#3989): per-account scheduled queue (forward 1/day backlog)
    var schedPanel = '';
    try {
        var sched = await api('/api/signal/calendar/scheduled?account=' + encodeURIComponent(account));
        schedPanel = _renderSignalScheduledQueue(sched.posts || [], account);
    } catch (e) {
        schedPanel = '<div class="dhq-empty" style="margin-top:14px">Scheduled queue unavailable</div>';
    }

    setHtml(el, headerLine + grid + legend + schedPanel);
}

function _renderSignalScheduledQueue(posts, account) {
    var rows = '';
    for (var i = 0; i < posts.length; i++) {
        var p = posts[i];
        var when = (p.scheduled_at || '').slice(0, 10);
        var preview = (p.content || '').slice(0, 140);
        rows += '<tr>'
            + '<td style="white-space:nowrap;color:#22d3ee">' + esc(when) + '</td>'
            + '<td style="font-size:0.72rem">' + esc(preview) + (p.content && p.content.length > 140 ? '…' : '') + '</td>'
            + '<td><button class="dhq-btn" style="font-size:0.6rem" onclick="signalCalendarCancel(' + p.id + ')">✕ Cancel</button></td>'
            + '</tr>';
    }
    return '<div style="margin-top:16px">'
        + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
        + '<h4 style="font-family:Antonio,sans-serif;letter-spacing:1px;margin:0">SCHEDULED QUEUE — ' + esc(_signalAccountLabel(account)) + ' (' + posts.length + ')</h4>'
        + '<button class="dhq-btn" onclick="signalCalendarBackfill()">⟳ Backfill backlog → calendar</button>'
        + '</div>'
        + (posts.length
            ? '<table class="dhq-table" style="width:100%"><tbody>' + rows + '</tbody></table>'
            : '<div class="dhq-empty" style="text-align:left">Nothing scheduled for this account. '
              + 'Backfill fans the unique failed/staged backlog forward, 1 post per day per account — '
              + 'release to approval is Phase 2; nothing publishes by itself.</div>')
        + '</div>';
}

async function signalCalendarBackfill() {
    try {
        var r = await apiPost('/api/signal/calendar/backfill', {});
        var by = r.by_account || {};
        var parts = Object.keys(by).map(function(a) { return a + ': +' + by[a].scheduled; });
        alert('Backfill done — ' + (r.total_scheduled || 0) + ' scheduled (' + parts.join(', ') + ')');
    } catch (e) {
        alert('Backfill failed: ' + (e && e.message ? e.message : e));
    }
    await loadSignalTab('calendar', true);
}

async function signalCalendarCancel(id) {
    try { await apiPost('/api/signal/calendar/scheduled/' + id + '/cancel', {}); }
    catch (e) { alert('Cancel failed: ' + (e && e.message ? e.message : e)); }
    await loadSignalTab('calendar', true);
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
    if (account === 'terry')    return 'Terry Caetano';
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
        if (typeof loadAutonomyBacklogs === 'function') await loadAutonomyBacklogs();
        if (typeof loadInterruptedJobs === 'function') await loadInterruptedJobs();
        loaded['autonomy'] = true;
    } catch (e) {
        console.error('[loadAutonomy] error:', e);
    }
}

// Backlogs control (decision #676) — see + toggle every module backlog on/off.
async function loadAutonomyBacklogs() {
    var el = document.getElementById('backlogContent');
    if (!el) return;
    function esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }
    try {
        var data = await api('/api/dispatch/backlogs');
        var rows = (data && data.backlogs) || [];
        var cnt = document.getElementById('backlogCount');
        if (cnt) cnt.textContent = rows.length + ' backlogs';
        if (!rows.length) { el.className = ''; el.textContent = 'No backlogs registered.'; return; }
        el.className = '';
        var html = '<table class="dhq-table" style="width:100%;font-size:0.78rem;"><thead><tr>' +
            '<th style="text-align:left;">Backlog</th><th style="text-align:left;">Module</th>' +
            '<th style="text-align:left;">Drains</th><th>Queue</th><th>On</th></tr></thead><tbody>';
        rows.forEach(function (b) {
            var depth = (b.queue_depth == null) ? '—' : b.queue_depth;
            var note = (b.backend === 'env') ? ' title="VPS env-gated — toggle records desired-state; redeploy to apply"' : '';
            var envTag = (b.backend === 'env') ? ' <span style="color:var(--dhq-text-dim);font-size:0.62rem;">(env)</span>' : '';
            html += '<tr>' +
                '<td style="font-family:\'IBM Plex Mono\',monospace;">' + esc(b.key) + envTag + '</td>' +
                '<td>' + esc(b.module) + '</td>' +
                '<td style="color:var(--dhq-text-dim);">' + esc(b.drains) + '</td>' +
                '<td style="text-align:center;">' + esc(depth) + '</td>' +
                '<td style="text-align:center;"><input type="checkbox" ' + (b.enabled ? 'checked' : '') + note +
                ' onchange="toggleBacklog(\'' + esc(b.key) + '\', this.checked, this)"></td></tr>';
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    } catch (e) {
        el.className = ''; el.textContent = 'Could not load backlogs.';
    }
}

async function toggleBacklog(key, enabled, cb) {
    try {
        if (cb) cb.disabled = true;
        await apiPost('/api/dispatch/backlogs/' + encodeURIComponent(key) + '/toggle', { enabled: enabled });
    } catch (e) {
        if (cb) cb.checked = !enabled;
    } finally {
        if (cb) cb.disabled = false;
    }
}

// Interrupted jobs (#1716 durable execution / #4500) — list crash-orphaned
// bridge_jobs and replay them (backend: GET interrupted-jobs / POST replay-job).
async function loadInterruptedJobs() {
    var el = document.getElementById('interruptedJobsContent');
    if (!el) return;
    function esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }
    function when(ts) {
        if (!ts) return '';
        if (window.ArchieTime && ArchieTime.format) return esc(ArchieTime.format(ts, 'datetime'));
        return esc(String(ts).replace('T', ' ').slice(0, 16));
    }
    try {
        var data = await api('/api/dispatch/interrupted-jobs');
        var rows = (data && data.jobs) || [];
        var cnt = document.getElementById('interruptedJobsCount');
        if (cnt) cnt.textContent = rows.length + ' interrupted';
        if (!rows.length) { el.className = ''; el.textContent = 'No interrupted jobs — all clear.'; return; }
        el.className = '';
        var html = '<table class="dhq-table" style="width:100%;font-size:0.78rem;"><thead><tr>' +
            '<th style="text-align:left;">#</th><th style="text-align:left;">Job Type</th>' +
            '<th style="text-align:left;">Module</th><th style="text-align:left;">Progress</th>' +
            '<th style="text-align:left;">Interrupted</th><th>Action</th></tr></thead><tbody>';
        rows.forEach(function (j) {
            var cp = j.checkpoint || {};
            var hasCp = (cp.completed_steps != null || cp.total_steps != null);
            var prog = hasCp
                ? (esc(cp.completed_steps == null ? '?' : cp.completed_steps) + '/' + esc(cp.total_steps == null ? '?' : cp.total_steps) +
                   (cp.reason ? ' <span style="color:var(--dhq-text-dim);font-size:0.62rem;">(' + esc(cp.reason) + ')</span>' : ''))
                : '<span style="color:var(--dhq-text-dim);">—</span>';
            var action = j.replayed_at
                ? '<span style="color:var(--dhq-text-dim);font-size:0.7rem;">↻ replayed</span>'
                : '<button style="font-size:0.7rem;padding:3px 12px;cursor:pointer;background:var(--cat-accent,#00ffff);color:#010409;border:none;border-radius:10px;font-family:\'Antonio\',sans-serif;letter-spacing:1px;" onclick="replayInterruptedJob(' + esc(j.id) + ', this)">REPLAY</button>';
            html += '<tr>' +
                '<td style="font-family:\'IBM Plex Mono\',monospace;">' + esc(j.id) + '</td>' +
                '<td style="font-family:\'IBM Plex Mono\',monospace;">' + esc(j.job_type) + '</td>' +
                '<td>' + esc(j.module_source) + '</td>' +
                '<td>' + prog + '</td>' +
                '<td style="color:var(--dhq-text-dim);">' + when(j.updated_at) + '</td>' +
                '<td style="text-align:center;">' + action + '</td></tr>';
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    } catch (e) {
        el.className = ''; el.textContent = 'Could not load interrupted jobs.';
    }
}

async function replayInterruptedJob(jobId, btn) {
    var status = document.getElementById('interruptedJobsStatus');
    try {
        if (btn) { btn.disabled = true; btn.textContent = '…'; }
        var res = await apiPost('/api/dispatch/replay-job/' + encodeURIComponent(jobId), {});
        if (status) {
            if (res && res.success) {
                var how = res.resumed ? 'resumed in place'
                    : (res.executed ? 're-dispatched' : 'cloned to pending (needs handler)');
                var nid = res.new_job_id ? (' → new job #' + res.new_job_id) : '';
                status.textContent = 'Job #' + jobId + ' ' + how + nid + (res.detail ? ' — ' + res.detail : '');
            } else {
                status.textContent = 'Replay of job #' + jobId + ' failed' + (res && res.error ? ': ' + res.error : '.');
            }
        }
    } catch (e) {
        if (status) status.textContent = 'Replay of job #' + jobId + ' failed (network error).';
    } finally {
        if (typeof loadInterruptedJobs === 'function') loadInterruptedJobs();
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
    // #4538: split the FAILED bucket — genuine dispatch errors vs infra queue/timeouts
    // (240s GPU-contention timeouts + reaped/orphaned jobs). Back-compat: fall back to
    // the combined failed_24h when the server hasn't shipped the split yet.
    var failedReal = (typeof m.failed_real_24h === 'number') ? m.failed_real_24h : (m.failed_24h || 0);
    var failedTimeout = m.failed_timeout_24h || 0;
    var pending = m.pending_24h || 0;
    var avg = m.avg_duration_ms ? (m.avg_duration_ms / 1000).toFixed(1) + 's' : '--';
    // Prefer the REAL success rate (infra queue/timeouts excluded from the denominator)
    // so a backlog-load event doesn't read as a dispatch regression; fall back to the
    // combined server rate, then to a local estimate, so old payloads still work.
    var rate = (typeof m.success_rate_real === 'number')
        ? m.success_rate_real
        : (typeof m.success_rate === 'number')
            ? m.success_rate
            : ((success + failedReal) > 0 ? Math.round(success / (success + failedReal) * 100) : 0);
    var rateClass = rate >= 95 ? 'good' : rate >= 80 ? 'warn' : 'bad';
    var tokens = m.tokens_24h || 0;  // reported model tokens (prompt+completion, lower bound)
    var html = '<div class="dhq-metrics-row">'
        + _metricCell('DISPATCHES 24H', total, '')
        + _metricCell('SUCCESS', success, 'good')
        + _metricCell('FAILED', failedReal, failedReal > 0 ? 'bad' : '')
        + (failedTimeout > 0 ? _metricCell('QUEUE TIMEOUT', failedTimeout, 'warn') : '')
        + (pending > 0 ? _metricCell('IN-FLIGHT', pending, 'warn') : '')
        + _metricCell('AVG RESPONSE', avg, '')
        + _metricCell('TOKENS 24H', formatNum(tokens), '')
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

// Classify a dispatch row's model: real LLM inference vs a non-LLM marker.
// Markers (orchestration/job bookkeeping = 'bridge-managed'/'internal', scrape =
// 'browser', image = 'comfyui', embeddings = 'batch'/*embed*) ran NO model — their
// duration is cycle wall-clock, so tokens/CO2/Wh are n/a, not 0. Mirrors the
// backend carbon_footprint_service._is_llm_model + Token Economy exclude-list.
function _dhqModelKind(model) {
    var m = (model == null ? '' : String(model)).trim().toLowerCase();
    if (m === 'bridge-managed' || m === 'internal') return { label: '⚙ orchestration', llm: false };
    if (m === 'browser') return { label: '🌐 scrape', llm: false };
    if (m === 'comfyui') return { label: '🎨 image', llm: false };
    if (m === 'batch' || m.indexOf('embed') >= 0) return { label: 'embedding', llm: false };
    if (!m) return { label: '—', llm: false };
    return { label: model, llm: true };
}

// Friendly DISPLAY label for a dispatch module_source. The stored value is an
// internal tag (used by filters/queries/history — never renamed); this only
// prettifies the feed + BY SOURCE breakdown. Unmapped tags pass through as-is.
function _dhqSourceLabel(source) {
    var s = (source == null ? '' : String(source)).trim();
    var MAP = {
        'agent_loop': 'Autonomy · jobs',
        'scraper': 'S.C.O.U.T. · browser',
        'media_hub': 'M.A.V.E.N. · media',
        'fleet_warmup': 'Fleet warm-up',
        'kin_warmth': 'K.I.N. warm-up',
        'model_dispatch': 'Cold-load queue',
        'coverage_scan': 'Coverage scan',
        // #6763 — codex/opencode/host-CLI token spend, mirrored out of OmniRoute's
        // own call log. Attributed to the GATEWAY, not a lane: one shared API key
        // means the gateway cannot say which interface called.
        'omniroute_gateway': 'OmniRoute \u00b7 gateway'
    };
    return MAP[s.toLowerCase()] || s || '—';
}

// ── History ──

async function loadDispatchHistory() {
    var el = document.getElementById('dispatchHistoryContent');
    if (!el) return;
    try {
        // Backend = /api/dispatch/history -> { stats, rows, lifetime, total, page, pages }
        var data = await api('/api/dispatch/history?per_page=50');
        var rows = data.rows || [];
        var st = data.stats || {};
        var lt = data.lifetime || {};
        var fmtN = function(n) { return (n == null ? 0 : Number(n)).toLocaleString(); };
        var head = '<div style="display:flex;flex-wrap:wrap;gap:6px 16px;padding:8px 10px;margin-bottom:8px;background:var(--dhq-surface-2);border-radius:6px;font-size:0.72rem">'
            + '<div><span style="color:var(--dhq-text-dim);letter-spacing:0.04em">TOTAL SO FAR</span> &nbsp;'
            + '<b>' + fmtN(lt.dispatches) + '</b> dispatches &middot; '
            + '<b>' + fmtN(lt.tokens) + '</b> tokens &middot; '
            + '<b>' + (lt.co2_kg != null ? Number(lt.co2_kg).toFixed(2) : '\u2014') + '</b> kg CO2 &middot; '
            + '<b>' + (lt.energy_kwh != null ? Number(lt.energy_kwh).toFixed(1) : '\u2014') + '</b> kWh</div>'
            + '<div style="margin-left:auto;color:var(--dhq-text-dim)">window: '
            + fmtN(st.total_calls) + ' calls &middot; ' + fmtN(st.total_tokens) + ' tok &middot; '
            + (st.total_co2_g != null ? Number(st.total_co2_g).toFixed(1) : '\u2014') + ' gCO2 &middot; '
            + (st.success_rate != null ? st.success_rate : 0) + '% ok</div>'
            + '</div>';
        if (!rows.length) { setHtml(el, head + '<div class="dhq-empty">No dispatches in this period</div>'); return; }
        var html = head + '<table class="dhq-loop-table"><thead><tr>'
            + '<th>TIME</th><th>SOURCE</th><th>ACTOR</th><th>ACTION</th><th>STATUS</th><th>MODEL</th>'
            + '<th style="text-align:right">DUR</th><th style="text-align:right">TOKENS</th><th style="text-align:right">gCO2</th><th style="text-align:right">Wh</th>'
            + '</tr></thead><tbody>';
        rows.forEach(function(r) {
            var ok = r.success;
            var statusCls = ok === true ? 'dhq-loop-ok' : ok === false ? 'dhq-loop-err' : '';
            var statusTxt = ok === true ? 'success' : ok === false ? 'failed' : 'pending';
            var dur = r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + 's' : '\u2014';
            var mk = _dhqModelKind(r.model_used);
            html += '<tr>'
                + '<td style="color:var(--dhq-text-dim);white-space:nowrap">' + fmtTime(r.created_at) + '</td>'
                + '<td><span class="dhq-status-badge ' + (r.source === 'task' ? 'dhq-status-running' : 'dhq-status-pending') + '">' + esc(r.source) + '</span></td>'
                + '<td>' + esc(r.agent_name || '\u2014') + '</td>'
                + '<td>' + esc(r.capability || '\u2014') + '</td>'
                + '<td class="' + statusCls + '">' + statusTxt + '</td>'
                + '<td style="color:var(--dhq-text-dim)">' + esc(mk.label) + '</td>'
                + '<td style="text-align:right;color:var(--dhq-text-dim)">' + dur + '</td>'
                + '<td style="text-align:right;color:var(--dhq-text-dim)">' + (mk.llm ? (r.tokens_used ? fmtN(r.tokens_used) : '\u2014') : 'n/a') + '</td>'
                + '<td style="text-align:right;color:var(--dhq-text-dim)">' + (mk.llm ? (r.co2_g != null && r.co2_g > 0 ? Number(r.co2_g).toFixed(3) : '\u2014') : 'n/a') + '</td>'
                + '<td style="text-align:right;color:var(--dhq-text-dim)">' + (mk.llm ? (r.energy_wh != null && r.energy_wh > 0 ? Number(r.energy_wh).toFixed(3) : '\u2014') : 'n/a') + '</td>'
                + '</tr>';
        });
        html += '</tbody></table>';
        setHtml(el, html);
    } catch (e) { setHtml(el, '<div class="dhq-empty">Error: ' + esc(e.message) + '</div>'); }
}

// ── Blocked-job queue actions (owner Retry / Fix / Dismiss) ──
// XSS-safe per PR #1861: buttons carry data-* attrs only (task id is
// Number()-coerced; action is a static literal) — NO inline onclick built
// from row data. Clicks are handled by the single delegated
// _delegationClickHandler bound to the feed container, which survives the
// setHtml() re-render because the container element itself is not replaced.
function _delegBtn(action, tid, label, title, color) {
    return '<button data-deleg-action="' + action + '" data-task-id="' + (Number(tid) || 0) + '"'
        + ' title="' + esc(title) + '"'
        + ' style="cursor:pointer;font-family:\'Antonio\',sans-serif;font-size:0.64rem;'
        + 'letter-spacing:0.04em;padding:2px 7px;margin-right:4px;border-radius:3px;'
        + 'border:1px solid ' + color + ';background:transparent;color:' + color + '">'
        + label + '</button>';
}

function _delegationActionsCell(p) {
    if (p.status !== 'blocked' && p.status !== 'failed') {
        return '<span style="color:var(--dhq-text-dim);font-size:0.7rem">—</span>';
    }
    var cap = p.capability || '';
    var html = _delegBtn('retry', p.id, '↻ Retry', 'Re-queue — the worker re-attempts it', '#f59e0b');
    if (cap === 'documentation' || cap === 'document_pr') {
        html += _delegBtn('fix', p.id, '✓ Fix', 'Persist the PR doc deterministically (no slow LLM)', '#22c55e');
    }
    html += _delegBtn('dismiss', p.id, '✕ Dismiss', 'Cancel + remove from the queue (auditable)', '#ef4444');
    return html;
}

function _delegationClickHandler(e) {
    var btn = e.target.closest('button[data-deleg-action]');
    if (!btn || btn.disabled) return;
    _delegationAction(Number(btn.getAttribute('data-task-id')), btn.getAttribute('data-deleg-action'), btn);
}

async function _delegationAction(taskId, action, btn) {
    if (!taskId || !action) return;
    if (action === 'dismiss'
        && !window.confirm('Dismiss this delegation?\n\nIt will be cancelled and removed from the queue (auditable, not deleted).')) {
        return;
    }
    var busy = { retry: 'Re-queuing…', fix: 'Fixing…', dismiss: 'Dismissing…' };
    var orig = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.textContent = busy[action] || '…'; }
    try {
        var data = await apiPost('/api/dispatch/delegations/' + taskId + '/' + action, {});
        if (data && data.success) {
            if (btn) btn.textContent = '✓';
            setTimeout(loadClaudeFeed, 700);
        } else {
            if (btn) { btn.disabled = false; btn.innerHTML = orig; }
            alert('Failed: ' + ((data && data.error) || 'unknown'));
        }
    } catch (err) {
        if (btn) { btn.disabled = false; btn.innerHTML = orig; }
        alert('Error: ' + (err.message || err));
    }
}

// ── Claude Requests Feed (Task #1297) ──

async function loadClaudeFeed() {
    var el = document.getElementById('dispatchClaudeContent');
    var countEl = document.getElementById('dispatchClaudeCount');
    var hoursEl = document.getElementById('dispatchClaudeHours');
    var hours = hoursEl ? hoursEl.value : 24;
    if (!el) return;
    // Bind the delegated action handler ONCE on the container; it survives
    // setHtml() re-renders (innerHTML replaces children, not the element).
    el.onclick = _delegationClickHandler;
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
            // "BLOCKED BY" appears ONLY when a row actually carries a blocker,
            // so the common (nothing-stuck) table keeps its original width.
            var anyBlocked = pending.some(function(p) { return !!(p.blockers || '').trim(); });
            var hdr = '<th>STATUS</th><th>CAPABILITY</th><th>REASON</th>'
                + (anyBlocked ? '<th>BLOCKED BY</th>' : '')
                + '<th>SOURCE</th><th>AGE</th><th>QUEUED</th><th>ACTIONS</th>';
            pendingHtml = '<div style="margin-bottom:0.8rem">'
                + '<div style="font-size:0.7rem;color:var(--dhq-text-dim);margin-bottom:0.3rem;font-family:\'Antonio\',sans-serif;letter-spacing:0.08em">DELEGATION QUEUE — ' + pending.length + ' not yet completed</div>'
                + '<table class="dhq-loop-table"><thead><tr>'
                + hdr
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
                // The refusal itself, e.g. "Dispatcher refused: Ollama Cloud API
                // error: 410 - minimax-m2.5 was retired at 2026-07-31". This is
                // the difference between "blocked" and knowing WHY, and it is
                // what tells a retryable stall from a dead-end one.
                var blockerCell = '';
                if (anyBlocked) {
                    var b = (p.blockers || '').replace(/\s+/g, ' ').trim();
                    if (b.length > 120) b = b.slice(0, 117) + '…';
                    blockerCell = '<td title="' + esc(p.blockers || '') + '" style="color:#ef4444;font-size:0.7rem;max-width:22rem">'
                        + (b ? esc(b) : '<span style="color:var(--dhq-text-dim)">—</span>') + '</td>';
                }
                pendingHtml += '<tr>'
                    + '<td style="color:' + statusColor + ';font-weight:600;font-family:monospace;font-size:0.72rem">' + esc(p.status || '?') + '</td>'
                    + '<td style="font-family:monospace;color:var(--dhq-accent);font-size:0.72rem">' + esc(p.capability || '?') + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + esc(reason) + '</td>'
                    + blockerCell
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + esc(p.requested_by || p.delegation_source || '—') + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + ageStr + '</td>'
                    + '<td style="color:var(--dhq-text-dim);font-size:0.72rem">' + fmtTime(p.created_at) + '</td>'
                    + '<td style="white-space:nowrap">' + _delegationActionsCell(p) + '</td>'
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
var _trafficFilter = null;  // #4345 drill-down: {dim:'source'|'agent'|'model'|'node', value:'...'}
var _trafficRealOnly = true;  // feed default: real LLM inference only (hide orchestration markers)

// Drill into a breakdown row -> filter the feed to that entity's recent actions.
function dhqTrafficDrill(dim, value) {
    if (!dim || !value) return;
    _trafficFilter = { dim: dim, value: value };
    _trafficView = 'feed';
    loadDispatchTraffic();
}
function dhqTrafficClearFilter() {
    _trafficFilter = null;
    loadDispatchTraffic();
}
// Feed toggle: real LLM inference only (default) vs include orchestration markers.
function dhqTrafficToggleMarkers() {
    _trafficRealOnly = !_trafficRealOnly;
    loadDispatchTraffic();
}

async function loadDispatchTraffic() {
    var el = document.getElementById('trafficContent');
    var sumEl = document.getElementById('trafficSummary');
    if (!el) return;
    var hours = (document.getElementById('trafficHours') || {}).value || 1;
    try {
        var _turl = '/api/dispatch/traffic?hours=' + hours;
        if (_trafficFilter) _turl += '&f' + _trafficFilter.dim + '=' + encodeURIComponent(_trafficFilter.value);
        if (!_trafficRealOnly) _turl += '&markers=all';
        _trafficData = await api(_turl);
        if (sumEl) {
            // page_* keys are scoped to the fetched feed page (LIMIT 30) — not
            // the whole window; the old total/success_rate keys implied window
            // totals beside window-scoped failure tiles (#5706).
            var rate = _trafficData.page_success_rate != null ? _trafficData.page_success_rate + '% ok' : '';
            sumEl.textContent = '(' + (_trafficData.page_total || 0) + ' on this page · ' + rate + ')';
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
        var _chip = '<div style="margin-bottom:6px"><label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;font-size:0.72rem;color:var(--dhq-text-dim)">'
            + '<input type="checkbox" ' + (_trafficRealOnly ? 'checked' : '') + ' onchange="dhqTrafficToggleMarkers()" style="cursor:pointer">'
            + 'Real inference only <span style="opacity:0.6">— hide orchestration markers</span></label></div>';
        if (_trafficFilter) {
            _chip += '<div style="padding:5px 8px;margin-bottom:6px;background:var(--dhq-surface-2);border-radius:5px;font-size:0.72rem;display:flex;align-items:center;gap:8px">'
                + '<span style="color:var(--dhq-text-dim)">▸ ' + esc(_trafficFilter.dim.toUpperCase()) + ' =</span>'
                + '<span style="color:var(--dhq-accent)">' + esc(_trafficFilter.value) + '</span>'
                + '<span style="cursor:pointer;color:#EF4444;margin-left:auto" onclick="dhqTrafficClearFilter()">✕ clear</span>'
                + '</div>';
        }
        if (!rows.length) { setHtml(el, _chip + '<div class="dhq-empty">' + (_trafficFilter ? 'No recent actions for this ' + esc(_trafficFilter.dim) : 'No dispatches in window') + '</div>'); return; }
        var html = _chip + '<table style="width:100%;border-collapse:collapse;font-size:0.72rem">'
            + '<tr style="color:var(--dhq-text-dim);border-bottom:1px solid var(--dhq-border)">'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">TIME</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">AGENT</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">CAPABILITY</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">MODEL</th>'
            + '<th style="text-align:left;padding:2px 6px;font-weight:400">SOURCE</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">TOKENS</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">gCO2</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">Wh</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">MS</th>'
            + '</tr>';
        rows.forEach(function(r) {
            var ok = r.success;
            var dot = '<span style="color:' + (ok ? '#10B981' : '#EF4444') + '">' + (ok ? '✓' : '✗') + '</span>';
            var mk = _dhqModelKind(r.model);
            html += '<tr style="border-bottom:1px solid var(--dhq-border)">'
                + '<td style="padding:3px 6px;color:var(--dhq-text-dim);white-space:nowrap">' + (r.ts ? fmtTime(r.ts) : '—') + '</td>'
                + '<td style="padding:3px 6px">' + dot + ' ' + esc(r.agent) + '</td>'
                + '<td style="padding:3px 6px;color:var(--dhq-accent)">' + esc(r.capability) + '</td>'
                + '<td style="padding:3px 6px;color:var(--dhq-text-dim)">' + esc(mk.label) + '</td>'
                + '<td style="padding:3px 6px;color:var(--dhq-text-dim)">' + esc(_dhqSourceLabel(r.source)) + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (mk.llm ? (r.tokens != null && r.tokens > 0 ? Number(r.tokens).toLocaleString() : '—') : 'n/a') + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (mk.llm ? (r.co2_g != null && r.co2_g > 0 ? Number(r.co2_g).toFixed(3) : '—') : 'n/a') + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (mk.llm ? (r.energy_wh != null && r.energy_wh > 0 ? Number(r.energy_wh).toFixed(3) : '—') : 'n/a') + '</td>'
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
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">TOKENS</th>'
            + '<th style="text-align:right;padding:2px 6px;font-weight:400">gCO2</th>'
            + '</tr>';
        rows.forEach(function(r) {
            var pct = r.total > 0 ? Math.round(r.successes / r.total * 100) : 0;
            var pctColor = pct >= 90 ? '#10B981' : pct >= 70 ? '#FFAA00' : '#EF4444';
            html += '<tr style="border-bottom:1px solid var(--dhq-border);cursor:pointer" data-dim="' + view + '" data-val="' + esc(r.label || '') + '" onclick="dhqTrafficDrill(this.dataset.dim, this.dataset.val)" title="Click to see this ' + esc(view) + " actions\">"
                + '<td style="padding:3px 6px;color:var(--dhq-accent)">' + esc(view === 'source' ? _dhqSourceLabel(r.label) : (r.label || '—')) + '</td>'
                + '<td style="padding:3px 6px;text-align:right">' + r.total + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:' + pctColor + '">' + pct + '%</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (r.avg_ms != null ? r.avg_ms : '—') + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + formatNum(r.tokens || 0) + '</td>'
                + '<td style="padding:3px 6px;text-align:right;color:var(--dhq-text-dim)">' + (r.co2_g > 0 ? Number(r.co2_g).toFixed(2) : '—') + '</td>'
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
    // NETWORK retired 2026-09-11 — its map + node buttons moved into CLUSTER,
    // its usage panel into Contractors. A stored preference of 'network' would
    // otherwise match NO section and blank the whole tab, so normalise first.
    var sections = ['cluster', 'dispatch', 'traffic', 'orchestration'];
    if (sections.indexOf(s) === -1) s = 'cluster';
    _armadaSection = s;
    try { localStorage.setItem('dhq_armada_section', s); } catch (_) {}
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
            var inner = source.querySelector('[style*="padding:16px"]') || source;
            // Move ONLY this sub-tab's content. SKIP trafficPanelSection — it
            // belongs to the TRAFFIC sub-tab; the old greedy move dragged the
            // "DISPATCH TRAFFIC" panel in here, leaking it into the dispatch view.
            Array.prototype.slice.call(inner.childNodes).forEach(function(ch) {
                if (ch.id !== 'trafficPanelSection') target.appendChild(ch);
            });
        }
        if (!loaded['dispatch']) { loaded['dispatch'] = true; loadDispatch(); }
        // The Dispatch History panel now lives only inside this A.R.M.A.D.A.
        // sub-tab (there is no top-level 'dispatch' tab anymore), so dhInit()
        // — which fires the first dhFetch() — was never called and the panel
        // sat on "Loading…" / "—" forever. Init it on first mount.
        if (typeof dhInit === 'function') dhInit();
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

    // CLUSTER: refresh live data + the fleet map (inherited from NETWORK)
    if (s === 'cluster') {
        loadQueueStatus(); loadClusterActivity(); loadClusterStats(); loadWtfAgentStatus();
        loadClusterRest();
        // The map now lives here. initFleetMap() self-guards (if (fleetMap) return),
        // so this is idempotent; invalidateSize is still required because Leaflet
        // measures 0x0 while the section is display:none and never re-measures.
        loadFleetData(); initFleetMap();
        setTimeout(function() { if (fleetMap) fleetMap.invalidateSize(); }, 50);
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
// #5321b: click-to-edit for the hardware-rest strip. The GET/POST
// /api/fleet/rest-mode endpoint existed with NO UI caller — which is exactly
// how the schedule went invisible. Inline editor, textContent-only labels;
// Save POSTs then re-renders the strip from fresh server state.
// ── Hardware rest — the cluster's sleep schedule, managed in the CLUSTER tab (#5816)
//
// The schedule binds EIGHT real dispatch gates — dispatcher candidate
// selection, cold-load queue drain, fleet resource router, ComfyUI routing,
// model-control, fleet jobs, and two agent-loop legs — all via the single
// is_starships_undocked() predicate. Despite that reach it could only be seen
// and changed through a one-line strip and a tiny pencil glyph in FLEET DOCK,
// which is how it sat DISABLED without anyone noticing.
//
// ONE source of truth: /api/fleet/rest-mode serves rest_status_snapshot() —
// the SAME dict the FLEET DOCK strip renders. Neither surface recomputes the
// window locally; a second implementation of "are we in the window" is exactly
// what #5321 was filed for.
//
// All text goes in via textContent — never innerHTML.
var _crSaving = false;

function _crMk(tag, txt, css) {
    var e = document.createElement(tag);
    if (txt !== undefined && txt !== null) e.textContent = txt;
    if (css) e.style.cssText = css;
    return e;
}

function _crHourSelect(selected, id) {
    var sel = document.createElement('select');
    sel.id = id;
    sel.style.cssText = 'font-size:0.75rem;background:rgba(0,0,0,0.35);color:var(--dhq-text);' +
                        'border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:2px 4px;';
    for (var h = 0; h < 24; h++) {
        var o = _crMk('option', (h < 10 ? '0' : '') + h + ':00');
        o.value = h;
        if (h === selected) o.selected = true;
        sel.appendChild(o);
    }
    return sel;
}

function loadClusterRest() {
    var body = document.getElementById('crBody');
    if (!body) return;
    fetch('/tools/department-hq/api/fleet/rest-mode')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (!d || !d.success) { body.textContent = 'Rest schedule unavailable.'; return; }
            _crRender(d);
        })
        .catch(function() { body.textContent = 'Rest schedule unavailable.'; });
}

function _crRender(d) {
    var body = document.getElementById('crBody');
    if (!body) return;
    var st = d.status || {};
    var forced = !!d.force_undock_until;
    body.textContent = '';

    // #5816: the ⚓ button now lives in this panel, so paint it from the SAME
    // payload rather than leaving it to a separate poll. One fetch, one truth —
    // the button and the lines below cannot disagree with each other.
    if (typeof updateRestModeUI === 'function') {
        try { updateRestModeUI(d); } catch (_e) {}
    }

    // ── state pill. Four DISTINCT states — the point of #5321 was that
    //    "in the window" and "armed" are different facts and conflating
    //    them produced two wrong beliefs in one day.
    // ── line 1: window / now / next transition
    var nt = st.next_transition || {};
    var mins = nt.in_minutes || 0;
    var l1 = _crMk('div', null, 'margin-bottom:8px;');
    var schedLabel = forced ? 'FORCE-UNDOCK' : (st.active ? 'RESTING' : (st.enabled ? 'ARMED' : 'DISABLED'));
    var schedColor = forced || st.active ? '#c4b5fd' : (st.enabled ? '#00e5c0' : '#f59e0b');
    l1.appendChild(_crMk('span', 'Schedule ', 'opacity:0.8;'));
    l1.appendChild(_crMk('span', schedLabel, 'color:' + schedColor + ';font-weight:600;letter-spacing:0.5px;'));
    l1.appendChild(_crMk('span', '  ·  window ' + (st.window_label || '--') + '  ·  now ' + (st.now_et || '--')));
    if (forced) {
        // A manual force outranks the schedule: saying "takes work around the
        // clock" here would flatly contradict the FORCE-UNDOCK label beside it.
        l1.appendChild(_crMk('span', '  ·  manually undocked — ships detached until the next window end',
                             'color:#c4b5fd;'));
    } else if (st.enabled) {
        l1.appendChild(_crMk('span',
            '  ·  ' + (nt.kind === 'rest_end' ? 'wake' : 'rest starts') + ' ' + (nt.at || '--') +
            ' (in ' + Math.floor(mins / 60) + 'h ' + (mins % 60) + 'm)'));
    } else if (st.in_window) {
        // The honest case that used to read as "resting": the clock IS inside
        // the window, but nothing is suppressed because the toggle is off.
        l1.appendChild(_crMk('span', '  ·  clock is INSIDE the window, but rest is not armed — nothing is suppressed',
                             'color:#f59e0b;'));
    } else {
        l1.appendChild(_crMk('span', '  ·  not armed — Starships take work around the clock', 'color:#f59e0b;'));
    }
    body.appendChild(l1);

    // ── line 2: the controls
    var l2 = _crMk('div', null, 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;');
    var chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.id = 'crEnabled';
    chk.checked = !!st.enabled;
    chk.style.cssText = 'cursor:pointer;';
    var chkLab = _crMk('label', 'Arm rest schedule', 'cursor:pointer;color:var(--dhq-text);');
    chkLab.htmlFor = 'crEnabled';
    l2.appendChild(chk);
    l2.appendChild(chkLab);
    l2.appendChild(_crMk('span', 'window', 'margin-left:12px;'));
    l2.appendChild(_crHourSelect(st.start_hour, 'crStart'));
    l2.appendChild(_crMk('span', '→'));
    l2.appendChild(_crHourSelect(st.end_hour, 'crEnd'));
    l2.appendChild(_crMk('span', 'ET'));
    var save = _crMk('button', 'SAVE',
        'margin-left:10px;padding:3px 14px;font-size:0.7rem;letter-spacing:1px;border-radius:4px;' +
        'cursor:pointer;background:rgba(0,229,192,0.15);color:#00e5c0;border:1px solid rgba(0,229,192,0.45);');
    save.id = 'crSaveBtn';
    save.addEventListener('click', _crSave);
    l2.appendChild(save);
    var status = _crMk('span', '', 'margin-left:8px;font-size:0.72rem;');
    status.id = 'crSaveStatus';
    l2.appendChild(status);
    body.appendChild(l2);

    // ── line 3: force undock (manual, auto-expiring)
    var l3 = _crMk('div', null, 'display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px;');
    l3.appendChild(_crMk('span', 'Force undock:'));
    if (forced) {
        l3.appendChild(_crMk('span', 'ACTIVE until ' + String(d.force_undock_until).slice(11, 16) + ' ET (auto-expires)',
                             'color:#c4b5fd;'));
        var clr = _crMk('button', 'REDOCK NOW',
            'padding:2px 12px;font-size:0.7rem;border-radius:4px;cursor:pointer;' +
            'background:rgba(0,229,192,0.12);color:#00e5c0;border:1px solid rgba(0,229,192,0.4);');
        clr.addEventListener('click', function() { _crUndock('clear'); });
        l3.appendChild(clr);
    } else {
        l3.appendChild(_crMk('span', 'none'));
        var und = _crMk('button', 'UNDOCK NOW',
            'padding:2px 12px;font-size:0.7rem;border-radius:4px;cursor:pointer;' +
            'background:rgba(139,92,246,0.15);color:#c4b5fd;border:1px solid rgba(139,92,246,0.45);');
        und.title = 'Detach the Starships immediately. Auto-expires at the next window end — a manual force can never permanently strand a node.';
        und.addEventListener('click', function() { _crUndock('undock'); });
        l3.appendChild(und);
    }
    body.appendChild(l3);

    // ── line 4: scope. Say what rest DOES and does NOT stop, so nobody has to
    //    guess how far the switch reaches.
    var note = _crMk('div', null,
        'font-size:0.7rem;line-height:1.5;color:var(--dhq-text-dim);opacity:0.85;border-top:1px solid rgba(255,255,255,0.08);padding-top:6px;');
    note.appendChild(_crMk('div', 'Scope: detaches the LAN Starships only. Hub and outposts keep taking work — the cluster never goes idle.'));
    note.appendChild(_crMk('div', 'Binds 8 gates: dispatcher selection · queue drain · resource router · ComfyUI · model-control · fleet jobs · agent loop (×2).'));
    body.appendChild(note);
}

function _crSave() {
    if (_crSaving) return;
    var chk = document.getElementById('crEnabled');
    var s = document.getElementById('crStart');
    var e = document.getElementById('crEnd');
    var st = document.getElementById('crSaveStatus');
    var btn = document.getElementById('crSaveBtn');
    if (!chk || !s || !e) return;
    _crSaving = true;
    if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
    if (st) { st.textContent = 'saving…'; st.style.color = 'var(--dhq-text-dim)'; }
    fetch('/tools/department-hq/api/fleet/rest-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            enabled: chk.checked,
            start_hour: parseInt(s.value, 10),
            end_hour: parseInt(e.value, 10),
        }),
    })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            _crSaving = false;
            if (!d || !d.success) {
                if (st) { st.textContent = 'save failed'; st.style.color = '#ef4444'; }
                if (btn) { btn.disabled = false; btn.style.opacity = ''; }
                return;
            }
            // The response carries a snapshot RE-READ from system_config, so
            // this renders what actually persisted — not what we asked for.
            _crRender(d);
            var st2 = document.getElementById('crSaveStatus');
            if (st2) { st2.textContent = '✓ saved'; st2.style.color = '#22c55e'; }
            if (typeof loadQueueStatus === 'function') loadQueueStatus();  // keep the FLEET DOCK strip in step
        })
        .catch(function() {
            _crSaving = false;
            if (st) { st.textContent = 'save failed'; st.style.color = '#ef4444'; }
            if (btn) { btn.disabled = false; btn.style.opacity = ''; }
        });
}

function _crUndock(action) {
    fetch('/tools/department-hq/api/fleet/force-undock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: action }),
    })
        .then(function(r) { return r.json(); })
        .then(function() {
            loadClusterRest();
            if (typeof loadQueueStatus === 'function') loadQueueStatus();
        })
        .catch(function() { loadClusterRest(); });
}

function loadQueueStatus() {
    fetch('/tools/department-hq/api/fleet/queue-status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var queued = data.platform_queued != null ? data.platform_queued : (data.queued || 0);
            var running = data.platform_running != null ? data.platform_running : (data.running || 0);
            var total = queued + running;

            // Badge
            var badge = document.getElementById('queueTotalBadge');
            if (badge) {
                if (total === 0) {
                    badge.textContent = 'idle';
                    badge.style.color = 'var(--dhq-text-dim)';
                } else {
                    badge.textContent = queued + ' queued · ' + running + ' running';
                    badge.style.color = running > 0 ? '#10b981' : '#f59e0b';
                }
            }

            // #5816: the hardware-rest strip USED to render here, duplicating what
            // FLEET COMMAND now owns — and both render in the SAME Cluster
            // sub-tab, so the window and its ✎ editor appeared twice on one
            // screen. Two editors over one system_config key is exactly the
            // divergence #5321 was filed to end, so the strip is retired
            // rather than kept in sync. Remove any node a cached page left
            // behind, so a stale DOM cannot resurrect the duplicate.
            var _staleRestStrip = document.getElementById('fleetRestStrip');
            if (_staleRestStrip && _staleRestStrip.parentNode) {
                _staleRestStrip.parentNode.removeChild(_staleRestStrip);
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

                    if (data.media_jobs && data.media_jobs.length) {
                        var mediaHeader = document.createElement('div');
                        mediaHeader.style.cssText = 'margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.08);color:#00bcd4;font-size:0.62rem;letter-spacing:1px;';
                        mediaHeader.textContent = 'MEDIA STUDIO JOBS';
                        qp.appendChild(mediaHeader);
                        data.media_jobs.forEach(function(job) {
                            var mediaRow = document.createElement('div');
                            var mediaActive = job.status === 'pending' || job.status === 'dispatched' || job.status === 'generating';
                            var mediaColor = mediaActive ? '#10b981' : '#ef4444';
                            mediaRow.style.cssText = 'display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.68rem;';
                            var mediaDot = document.createElement('span');
                            mediaDot.style.cssText = 'width:7px;height:7px;border-radius:50%;flex-shrink:0;background:' + mediaColor + ';';
                            var mediaName = document.createElement('span');
                            mediaName.style.cssText = 'color:var(--dhq-text-main);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
                            mediaName.textContent = '#' + job.id + ' · ' + (job.agent_name || 'User') + ' · ' + (job.media_type || 'image');
                            var mediaModel = document.createElement('span');
                            mediaModel.style.cssText = 'color:var(--dhq-text-dim);font-size:0.6rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
                            mediaModel.textContent = job.model || job.provider || '—';
                            var mediaStatus = document.createElement('span');
                            mediaStatus.style.cssText = 'color:' + mediaColor + ';font-size:0.6rem;text-transform:uppercase;';
                            mediaStatus.textContent = job.status || '';
                            mediaRow.appendChild(mediaDot);
                            mediaRow.appendChild(mediaName);
                            mediaRow.appendChild(mediaModel);
                            mediaRow.appendChild(mediaStatus);
                            qp.appendChild(mediaRow);
                        });
                    }
                }
            }

            // Loaded models
            var countEl = document.getElementById('loadedModelCount');
            if (countEl) countEl.textContent = data.loaded && data.loaded.length ? data.loaded.length + ' loaded' : '';
            var lp = document.getElementById('loadedModelsPanel');
            if (lp) {
                lp.textContent = '';

                // #6688 — CAN anything still LOAD? The counterweight to the list below.
                //
                // On 2026-09-11 this panel showed 4 healthy resident models on the hub
                // for two days while NOTHING new could load: Repair Bay's code-gen sat
                // at 0 successes and every view here read green. "What is loaded" and
                // "what can load" are different questions and only the first was asked.
                // Rendered FIRST and in red, above the reassuring list, because the
                // whole failure mode was reassurance.
                //
                // textContent throughout — this panel is XSS-safe DOM building and
                // model/node names come from the DB. Do not switch it to innerHTML.
                if (data.loadability && data.loadability.length) {
                    var warn = document.createElement('div');
                    warn.style.cssText = 'margin-bottom:8px;padding:6px 8px;border-left:3px solid #ef4444;'
                        + 'background:rgba(239,68,68,0.08);border-radius:4px;font-size:0.72rem;';
                    var wh = document.createElement('div');
                    wh.style.cssText = 'color:#ef4444;font-weight:600;margin-bottom:3px;letter-spacing:0.03em;';
                    // Two different faults — see model_loadability_monitor.derive_findings.
                    // "cannot load" is a scheduler problem (a restart fixed the hub);
                    // "too slow" means the model DOES run, just past its deadline, where
                    // a restart changes nothing. Naming them apart is the whole point.
                    var nSlow = data.loadability.filter(function(x){ return x.kind === 'too_slow'; }).length;
                    var nDead = data.loadability.length - nSlow;
                    var parts = [];
                    if (nDead) parts.push(nDead + ' cannot load');
                    if (nSlow) parts.push(nSlow + ' too slow for deadline');
                    wh.textContent = '⚠ ' + parts.join(' · ');
                    warn.appendChild(wh);
                    data.loadability.forEach(function(f) {
                        var line = document.createElement('div');
                        line.style.cssText = 'display:flex;align-items:center;gap:6px;color:var(--dhq-text-dim);font-family:\'IBM Plex Mono\',monospace;';
                        var text = document.createElement('span');
                        text.textContent = (f.model || '?') + ' on ' + (f.node_name || '?')
                            + (f.kind === 'too_slow'
                                ? ' · runs at ' + Math.round(f.success_seconds || 0) + 's vs a '
                                  + Math.round(f.avg_fail_seconds || 0) + 's wall'
                                : ' · ' + (f.attempts || 0) + ' attempts, 0 ok')
                            + ' · last success ' + Math.round(f.hours_since_success || 0) + 'h ago';
                        line.title = f.detail || '';
                        line.appendChild(text);
                        // Retry only makes sense for "cannot load" (a scheduler/VRAM
                        // fault a fresh attempt can clear) — NOT "too slow", where the
                        // model already loads fine and just misses its deadline; a
                        // restart changes nothing there (see the kind comment above).
                        if (f.kind !== 'too_slow') {
                            var btn = document.createElement('button');
                            btn.textContent = 'Retry Load';
                            btn.style.cssText = 'margin-left:auto;flex-shrink:0;background:rgba(239,68,68,0.15);'
                                + 'color:#ef4444;border:1px solid #ef4444;border-radius:3px;padding:1px 8px;'
                                + 'font-size:0.62rem;cursor:pointer;font-family:inherit;';
                            btn.addEventListener('click', function() {
                                btn.disabled = true;
                                btn.textContent = 'Loading…';
                                fetch('/tools/department-hq/api/models/control', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ model: f.model, action: 'load' })
                                })
                                .then(function(r) { return r.json(); })
                                .then(function(res) {
                                    btn.textContent = res.success ? 'Done ✓' : 'Failed ✗';
                                    btn.title = res.success ? (res.message || '') : (res.error || '');
                                    setTimeout(loadQueueStatus, 1500);
                                })
                                .catch(function() {
                                    btn.textContent = 'Failed ✗';
                                })
                                .finally(function() {
                                    setTimeout(function() { btn.disabled = false; btn.textContent = 'Retry Load'; }, 4000);
                                });
                            });
                            line.appendChild(btn);
                        }
                        warn.appendChild(line);
                    });
                    lp.appendChild(warn);
                }

                if (!data.loaded || data.loaded.length === 0) {
                    var none = document.createElement('span');
                    none.style.cssText = 'color:var(--dhq-text-dim);font-style:italic;';
                    none.textContent = 'No models currently loaded';
                    lp.appendChild(none);
                } else if (data.nodes && data.nodes.length) {
                    _dhqRenderLoadedByNode(lp, data.nodes);
                } else {
                    // Fallback for a payload without `nodes` (older worker mid-deploy,
                    // or the per-node build failing). A flat list is worse but true.
                    _dhqRenderLoadedFlat(lp, data);
                }
            }
        })
        .catch(function() {});
}

/* ============================================================
   LOADED MODELS — per-node, per-CARD rendering
   ------------------------------------------------------------
   GPU and CPU are now SEPARATE sections, and inside GPU each model sits
   under the card actually carrying it. That question is not answerable from
   Ollama alone: /api/ps reports size/size_vram and no device at all, so the
   card comes from nvidia-smi's per-process VRAM, matched to a model's
   size_vram server-side (services/gpu_residency.py).

   Two confidence levels arrive in the payload and are deliberately rendered
   DIFFERENTLY -- conflating them is how a panel starts lying:
     card.measured === true   nvidia-smi on that host: real used VRAM.
     card.measured === false  a remote node publishes capacity only, so the
                              figure is the resident models' FOOTPRINT. Marked
                              with a '~' and an explanatory title.

   A card may also carry MEASURED bytes whose model could not be named (two
   7B models at the same quant allocate identical VRAM, so naming either
   would be a coin flip presented as fact). Those render as "unidentified
   allocation" with their real size. A card is called idle ONLY when it holds
   neither -- an earlier build printed "idle" over a Quadro sitting at
   6.8/8 GB, which is simply false.
   ============================================================ */

function _dhqUsageColor(pct) {
    return pct >= 90 ? '#ef4444' : pct >= 70 ? '#f59e0b' : '#10b981';
}

function _dhqCapacityBar(opts) {
    var known = opts.total > 0;
    var pct = known ? Math.min(100, Math.round(opts.used / opts.total * 100)) : 0;
    var wrap = document.createElement('div');
    wrap.style.cssText = 'padding:3px 0 7px ' + (opts.indent || 16) + 'px;';
    var lbl = document.createElement('div');
    lbl.style.cssText = 'display:flex;gap:5px;align-items:baseline;flex-wrap:wrap;'
        + 'font-size:0.62rem;color:var(--dhq-text-dim);margin-bottom:3px;';
    var ln = document.createElement('span');
    ln.textContent = opts.label;
    ln.style.cssText = 'color:var(--dhq-text-main);font-weight:600;';
    lbl.appendChild(ln);
    if (opts.measured === false) {
        var der = document.createElement('span');
        der.textContent = '~derived';
        der.title = 'This node reports capacity only, not measured use. '
            + 'Shown value is the footprint of its resident models.';
        der.style.cssText = 'color:#f59e0b;font-size:0.58rem;';
        lbl.appendChild(der);
    }
    var lv = document.createElement('span');
    lv.style.cssText = 'margin-left:auto;white-space:nowrap;';
    lv.textContent = known
        ? (opts.used + ' / ' + opts.total + ' GB · ' + pct + '%')
        : 'capacity unknown';
    lbl.appendChild(lv);
    var track = document.createElement('div');
    track.style.cssText = 'height:5px;border-radius:3px;background:rgba(255,255,255,0.08);overflow:hidden;';
    var fill = document.createElement('div');
    fill.style.cssText = 'height:100%;width:' + (known ? pct : 0) + '%;'
        + 'background:' + _dhqUsageColor(pct) + ';transition:width 0.3s;';
    track.appendChild(fill);
    wrap.appendChild(lbl);
    wrap.appendChild(track);
    if (opts.footnote) {
        var fn = document.createElement('div');
        fn.style.cssText = 'font-size:0.58rem;color:var(--dhq-text-dim);margin-top:2px;';
        fn.textContent = opts.footnote;
        wrap.appendChild(fn);
    }
    return wrap;
}

function _dhqModelRow(name, gb, kind, badgeText) {
    var color = kind === 'gpu' ? '#10b981'
        : kind === 'cpu' ? 'var(--dhq-text-dim)' : '#6b7280';
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:3px 0 3px 30px;'
        + 'border-bottom:1px solid rgba(255,255,255,0.04);';
    var dot = document.createElement('span');
    dot.style.cssText = 'width:5px;height:5px;border-radius:50%;flex-shrink:0;background:' + color + ';';
    var nm = document.createElement('span');
    nm.style.cssText = 'font-family:"IBM Plex Mono",monospace;font-size:0.72rem;color:'
        + (kind === 'unknown' ? 'var(--dhq-text-dim)' : 'var(--dhq-text-main)')
        + (kind === 'unknown' ? ';font-style:italic' : '');
    nm.textContent = name;
    var sz = document.createElement('span');
    sz.style.cssText = 'margin-left:auto;color:var(--dhq-text-dim);font-size:0.68rem;white-space:nowrap;';
    sz.textContent = (gb || gb === 0) ? gb + ' GB' : '';
    row.appendChild(dot);
    row.appendChild(nm);
    row.appendChild(sz);
    if (badgeText) {
        var b = document.createElement('span');
        b.style.cssText = 'flex-shrink:0;font-size:0.56rem;font-weight:600;letter-spacing:0.05em;'
            + 'padding:1px 4px;border-radius:3px;color:' + color + ';border:1px solid ' + color + ';opacity:0.85;';
        b.textContent = badgeText;
        row.appendChild(b);
    }
    return row;
}

function _dhqSubhead(text, color) {
    var h = document.createElement('div');
    h.style.cssText = 'margin:7px 0 1px 12px;font-size:0.58rem;font-weight:700;'
        + 'letter-spacing:0.1em;color:' + color + ';';
    h.textContent = text;
    return h;
}

function _dhqNote(text, color) {
    var n = document.createElement('div');
    n.style.cssText = 'padding:2px 0 3px 30px;font-size:0.6rem;font-style:italic;color:'
        + (color || 'var(--dhq-text-dim)') + ';';
    n.textContent = text;
    return n;
}

function _dhqRenderLoadedByNode(lp, nodes) {
    nodes.forEach(function(n) {
        var cards = n.cards || [];
        var cpu = n.cpu_models || [];
        var unplaced = n.gpu_unplaced || [];
        var gpuNamed = 0;
        cards.forEach(function(c) { gpuNamed += (c.models || []).length; });
        var total = gpuNamed + unplaced.length + cpu.length;

        var header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:6px;margin:10px 0 2px;'
            + 'padding-top:5px;border-top:1px solid rgba(255,255,255,0.08);';
        var hdot = document.createElement('span');
        hdot.style.cssText = 'width:6px;height:6px;border-radius:50%;flex-shrink:0;background:'
            + (n.is_hub ? '#10b981' : '#00bcd4') + ';';
        var hname = document.createElement('span');
        hname.style.cssText = 'font-size:0.68rem;font-weight:700;letter-spacing:0.04em;color:'
            + (n.is_hub ? 'var(--dhq-text-main)' : '#00bcd4') + ';';
        hname.textContent = (n.label || n.key || '').toUpperCase();
        var hcount = document.createElement('span');
        hcount.style.cssText = 'margin-left:auto;font-size:0.62rem;color:var(--dhq-text-dim);white-space:nowrap;';
        hcount.textContent = total + (total === 1 ? ' model' : ' models');
        header.appendChild(hdot);
        header.appendChild(hname);
        header.appendChild(hcount);
        lp.appendChild(header);

        // ---- GPU ----
        if (cards.length || unplaced.length) {
            // Name the attribution SOURCE and, on the exact path, how old the
            // snapshot is — the exporter runs on a 60s cron, so "2s ago" and
            // "4 min ago" must not look identical.
            var gpuHead = 'GPU';
            if (n.gpu_attribution === 'exact') {
                // Figures are always live; only the NAME lookup can lag, so say
                // how much of the picture it actually covered.
                gpuHead = 'GPU \u00b7 ' + (n.gpu_named_procs || 0) + ' named';
            } else if (n.gpu_attribution === 'inferred') {
                gpuHead = 'GPU \u00b7 card inferred';
            } else if (n.gpu_attribution === 'declared') {
                gpuHead = 'GPU \u00b7 declared';
            }
            lp.appendChild(_dhqSubhead(gpuHead, '#10b981'));
            cards.forEach(function(c) {
                lp.appendChild(_dhqCapacityBar({
                    label: c.name || 'GPU',
                    used: c.vram_used_gb,
                    total: c.vram_total_gb,
                    measured: c.measured,
                    // A resident footprint bigger than the card means the model did
                    // not fully fit and part of it lives in CPU RAM. Saying so beats
                    // printing "4.5 / 4 GB", which is impossible on its face.
                    footnote: (c.overflow_gb > 0)
                        ? ('footprint ' + c.footprint_gb + ' GB exceeds this card by '
                           + c.overflow_gb + ' GB — partially offloaded to CPU')
                        : null
                }));
                (c.models || []).forEach(function(m) {
                    lp.appendChild(_dhqModelRow(m.name, m.gb, 'gpu', 'GPU'));
                });
                (c.unnamed || []).forEach(function(u) {
                    // The exporter can narrow a SHARED weights blob to a few tags
                    // without reaching one. Naming them all is honest; picking one
                    // would be a coin flip printed as fact.
                    var label = (u.candidates && u.candidates.length)
                        ? 'one of: ' + u.candidates.join(' / ')
                        : 'unidentified allocation';
                    lp.appendChild(_dhqModelRow(label, u.gb, 'unknown'));
                });
                if (!(c.models || []).length && !(c.unnamed || []).length) {
                    lp.appendChild(_dhqNote('no model resident on this card'));
                }
            });
            if (unplaced.length) {
                // The REASON depends on which attribution path answered. On the
                // exact path "identical VRAM footprints" is simply false — the
                // exporter names by manifest, not by size — so an unplaced model
                // there means no GPU process accounted for it.
                var why = (n.gpu_attribution === 'exact')
                    ? ' GPU-resident per Ollama, but no GPU process accounted for it '
                      + '(a load or unload in flight):'
                    : ' GPU-resident but cannot be pinned to a card '
                      + '(identical VRAM footprints — naming one would be a guess):';
                lp.appendChild(_dhqNote(
                    unplaced.length + (unplaced.length === 1 ? ' model is' : ' models are')
                    + why, '#f59e0b'));
                unplaced.forEach(function(m) {
                    lp.appendChild(_dhqModelRow(m.name, m.gb, 'gpu', 'GPU'));
                });
            }
        }

        // ---- CPU ----
        lp.appendChild(_dhqSubhead('CPU', '#94a3b8'));
        if (n.ram_total_gb) {
            lp.appendChild(_dhqCapacityBar({
                label: n.ram_measured ? 'System RAM' : 'RAM — resident models',
                used: n.ram_measured ? n.ram_used_gb : n.ram_models_gb,
                total: n.ram_total_gb,
                measured: n.ram_measured,
                footnote: n.ram_measured
                    ? ('of which ' + n.ram_models_gb + ' GB is loaded models')
                    : null
            }));
        }
        if (cpu.length) {
            cpu.forEach(function(m) {
                lp.appendChild(_dhqModelRow(m.name, m.gb, 'cpu', 'CPU'));
            });
        } else {
            lp.appendChild(_dhqNote('no CPU-resident models'));
        }
    });
}

function _dhqRenderLoadedFlat(lp, data) {
    var byNode = {};
    var nodeOrder = [];
    data.loaded.forEach(function(m) {
        var node = m.node || 'Hub';
        if (!byNode[node]) { byNode[node] = []; nodeOrder.push(node); }
        byNode[node].push(m);
    });
    nodeOrder.forEach(function(node) {
        var isFleet = node !== 'Hub';
        var header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;gap:6px;margin:8px 0 2px;'
            + 'padding-top:4px;border-top:1px solid rgba(255,255,255,0.06);';
        var hdot = document.createElement('span');
        hdot.style.cssText = 'width:6px;height:6px;border-radius:50%;flex-shrink:0;background:'
            + (isFleet ? '#00bcd4' : '#10b981') + ';';
        var hname = document.createElement('span');
        hname.style.cssText = 'font-size:0.68rem;font-weight:600;letter-spacing:0.04em;color:'
            + (isFleet ? '#00bcd4' : 'var(--dhq-text-main)') + ';';
        hname.textContent = (isFleet ? node : 'Starbase - A.R.C.H.I.E.').toUpperCase();
        header.appendChild(hdot);
        header.appendChild(hname);
        lp.appendChild(header);
        var _rank = { gpu: 0, split: 1, cpu: 2, unknown: 3 };
        byNode[node].slice().sort(function(a, b) {
            var ra = _rank[a.processor] === undefined ? 3 : _rank[a.processor];
            var rb = _rank[b.processor] === undefined ? 3 : _rank[b.processor];
            if (ra !== rb) { return ra - rb; }
            return (b.vram_gb || b.size_gb || 0) - (a.vram_gb || a.size_gb || 0);
        }).forEach(function(m) {
            var proc = m.processor || (m.vram_gb > 0 ? 'gpu' : 'unknown');
            var gb = (proc === 'cpu' || proc === 'unknown') ? m.size_gb : m.vram_gb;
            var txt = proc === 'gpu' ? 'GPU'
                : proc === 'split' ? (m.gpu_pct + '% GPU')
                : proc === 'cpu' ? 'CPU' : 'unknown';
            lp.appendChild(_dhqModelRow(m.name, gb, proc === 'split' ? 'gpu' : proc, txt));
        });
    });
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
            grid.style.gridTemplateColumns = 'repeat(3, 1fr)';
            var allCards = [];
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
                var hasHeartbeat = !!n.last_heartbeat; // false for registered-but-no-agent-stack nodes
                totalActive += active60s > 0 ? 1 : 0; // count nodes with work in last 60s

                var card = document.createElement('div');
                card.style.cssText = 'background:rgba(0,0,0,0.3);border:1px solid ' + (!hasHeartbeat ? 'rgba(255,165,0,0.25)' : (isActive ? '#10b981' : 'rgba(255,255,255,0.1)')) + ';border-radius:6px;padding:10px 12px;min-width:0;overflow:hidden;';

                // Hardware label: GPU+CPU for GPU nodes, CPU-only for pure-CPU nodes
                var hwLabel = n.gpu
                    ? '<span style="margin-left:auto;font-size:0.6rem;color:#a78bfa;letter-spacing:1px;">GPU</span>'
                      + '<span style="font-size:0.6rem;color:var(--dhq-text-dim);letter-spacing:1px;">+CPU</span>'
                    : '<span style="margin-left:auto;font-size:0.6rem;color:var(--dhq-text-dim);letter-spacing:1px;">CPU</span>';
                // Dot color: grey for no-heartbeat (registered only), green/cyan/red for live nodes
                var dotColor = !hasHeartbeat ? '#888' : (n.status === 'online' ? (isActive ? '#10b981' : '#00bcd4') : '#ef4444');
                var dotGlow = isActive && hasHeartbeat ? 'box-shadow:0 0 6px #10b981;' : '';
                var header = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">'
                    + '<span style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';flex-shrink:0;' + dotGlow + '"></span>'
                    + '<span style="font-family:Antonio,sans-serif;font-size:0.8rem;letter-spacing:1px;color:var(--dhq-text-main);">' + esc(nodeName) + '</span>'
                    + hwLabel
                    + '</div>';

                // Activity counts: 5-min window is primary (60s is too narrow — tasks take 15-30s each)
                // For nodes with no heartbeat (registered but agent stack not yet running), show status label
                // ⚠️ A PERCENTAGE OVER A TINY SAMPLE IS NOISE, NOT A HEALTH SIGNAL.
                // Measured 2026-09-11: USS-246 rendered a red "0% ok" off 2 dispatches
                // in the 5-minute window while it was actually running 98-99% over the
                // preceding 2 hours (331/324 and 157/156). Shown beside the hub's 100%
                // from n=214, it read as a node in trouble. Below the floor we show the
                // raw counts instead — honest, and still tells you it is quiet.
                var OK_PCT_MIN_SAMPLE = 5;
                var okPct = dispatches5m >= OK_PCT_MIN_SAMPLE ? Math.round(successRate * 100) : null;
                var okBadge = okPct !== null
                    ? ' <span style="color:' + (okPct >= 90 ? '#10b981' : (okPct >= 70 ? '#f59e0b' : '#ef4444')) + ';">' + okPct + '% ok</span>'
                    : '';
                var hotDot = active60s > 0 ? ' <span style="color:#10b981;" title="active in last 60s">●</span>' : '';
                var counts = hasHeartbeat
                    ? '<div style="display:flex;gap:10px;font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;margin-bottom:5px;flex-wrap:wrap;">'
                      + '<span style="color:' + (dispatches5m > 0 ? '#00bcd4' : 'var(--dhq-text-dim)') + ';">⚡ ' + dispatches5m + '/5m' + hotDot + '</span>'
                      + (backlog > 0 ? '<span style="color:#f59e0b;" title="staged in CPU pre-queue">⏳ ' + backlog + ' staged</span>' : '')
                      + okBadge
                      + '</div>'
                    : '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;color:#888;margin-bottom:5px;letter-spacing:0.5px;">REGISTERED · AGENT STACK PENDING</div>';

                // Throughput rate (hidden for no-heartbeat nodes)
                var ratePerMin = dispatches5m > 0 ? (dispatches5m / 5).toFixed(1) : '0.0';
                var throughputLine = hasHeartbeat
                    ? '<div style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;margin-bottom:5px;color:' + (dispatches5m > 0 ? '#00bcd4' : 'var(--dhq-text-dim)') + ';">'
                      + '▲ ' + ratePerMin + ' disp/min'
                      + '</div>'
                    : '';

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
                allCards.push(card);
            });

            // Render with fold-at-5: show first 5, "+N more" button if total > 5
            var FOLD_LIMIT = 5;
            allCards.forEach(function(c, i) {
                if (i >= FOLD_LIMIT) c.style.display = 'none';
                grid.appendChild(c);
            });
            var existingToggle = document.getElementById('clusterGridFoldBtn');
            if (existingToggle) existingToggle.remove();
            if (allCards.length > FOLD_LIMIT) {
                var hidden = allCards.length - FOLD_LIMIT;
                var toggleBtn = document.createElement('button');
                toggleBtn.id = 'clusterGridFoldBtn';
                toggleBtn.style.cssText = 'grid-column:1/-1;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);color:var(--dhq-text-dim);border-radius:4px;padding:5px 12px;font-size:0.68rem;cursor:pointer;letter-spacing:1px;font-family:"IBM Plex Mono",monospace;';
                var _folded = true;
                function updateToggleLabel() {
                    toggleBtn.textContent = _folded ? ('+ ' + hidden + ' MORE') : '▲ SHOW LESS';
                }
                updateToggleLabel();
                toggleBtn.onclick = function() {
                    _folded = !_folded;
                    allCards.forEach(function(c, i) { if (i >= FOLD_LIMIT) c.style.display = _folded ? 'none' : ''; });
                    updateToggleLabel();
                };
                grid.appendChild(toggleBtn);
            }

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
                            if (e.dr_mode) {
                                var drpBadge = document.createElement('span');
                                drpBadge.style.cssText = 'background:#ef444433;color:#ef4444;font-size:0.6rem;padding:1px 5px;border-radius:3px;font-weight:600;font-family:"IBM Plex Mono",monospace;flex-shrink:0;';
                                drpBadge.textContent = 'DRP';
                                row.appendChild(drpBadge);
                            }
                            idx++;
                        }
                        logEl.appendChild(row);
                        displayed++;
                    }
                }
            }

            // Sync rest mode button state from cluster-activity response
            if (typeof data.rest_enabled !== 'undefined') {
                updateRestModeUI({enabled: data.rest_enabled, active_now: data.rest_active, rest_window: data.rest_window});
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

function _applyDispatchMode(mode, focus) {
    ['auto', 'news', 'platform'].forEach(function(m) {
        var btn = document.getElementById('fleetMode' + m.charAt(0).toUpperCase() + m.slice(1));
        if (!btn) return;
        var active = m === mode;
        btn.style.background = active ? 'rgba(0,188,212,0.2)' : 'none';
        btn.style.borderColor = active ? '#00bcd4' : 'rgba(255,255,255,0.2)';
        btn.style.color = active ? '#00bcd4' : 'var(--dhq-text-dim)';
    });
    // #6080 AUX POWER: the focus sub-selector is a PLATFORM-only control.
    var aux = document.getElementById('fleetAuxPower');
    if (aux) aux.style.display = mode === 'platform' ? 'inline-flex' : 'none';
    var sel = document.getElementById('fleetFocusSelect');
    if (sel && focus !== undefined) sel.value = focus || '';
    var activeFocus = (mode === 'platform' && sel) ? (sel.value || '') : '';
    // Read-back: show what the active profile is prioritising across
    // warmth (K.I.N.), routing, and the backlog runner.
    var status = document.getElementById('fleetModeStatus');
    if (status) {
        var msg = mode === 'news'
                ? '→ News & Media agents prioritised: warm slots + routing (outpost-us) + WTF/Watch/CREED backlog first'
            : mode === 'platform'
                ? (activeFocus
                    ? '→ ⚡ AUX POWER → ' + activeFocus.replace(/_/g, ' ').toUpperCase()
                      + ': that family\'s queued LLM work drains FIRST (stable split — everything else still drains)'
                    : '→ Platform agents prioritised: warm GPU slots (incl. translate) + Starship routing + platform backlog first')
                : '→ Demand-driven: each node warms its hottest model; routing & backlog by priority';
        status.textContent = msg;
    }
}

function _populateFocusOptions(available) {
    var sel = document.getElementById('fleetFocusSelect');
    if (!sel || !Array.isArray(available)) return;
    var current = sel.value;
    while (sel.options.length > 1) sel.remove(1);  // keep "— none —"
    available.forEach(function(fam) {
        var opt = document.createElement('option');
        opt.value = fam;                                  // textContent only — XSS-safe
        opt.textContent = fam.replace(/_/g, ' ').toUpperCase();
        sel.appendChild(opt);
    });
    sel.value = current || '';
}

function loadDispatchMode() {
    fetch('/tools/department-hq/api/fleet/dispatch-mode')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (!d.success) return;
            _populateFocusOptions(d.available_focus);
            _applyDispatchMode(d.mode || 'auto', d.focus || '');
        })
        .catch(function() {});
}

function setFleetDispatchMode(mode) {
    var sel = document.getElementById('fleetFocusSelect');
    var focus = (mode === 'platform' && sel) ? (sel.value || '') : '';
    _applyDispatchMode(mode, focus);  // optimistic UI
    fetch('/tools/department-hq/api/fleet/dispatch-mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode, focus: focus})
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.success) {
            _populateFocusOptions(d.available_focus);
            _applyDispatchMode(d.mode, d.focus || '');
            var label = mode === 'news' ? '📰 NEWS MODE — WTF agents → outpost-us, platform → Starship'
                      : mode === 'platform' ? '🖥 PLATFORM MODE — platform agents → Starship-246 only'
                      : '✓ AUTO — balanced fleet-first routing';
            console.log('[Fleet] Dispatch profile:', label);
        }
    })
    .catch(function() {});
}

function setFleetDispatchFocus(focus) {
    _applyDispatchMode('platform', focus || '');  // optimistic UI
    fetch('/tools/department-hq/api/fleet/dispatch-mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: 'platform', focus: focus || ''})
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.success) {
            _applyDispatchMode(d.mode, d.focus || '');
            console.log('[Fleet] AUX POWER →', d.focus || '(none)');
        }
    })
    .catch(function() {});
}

async function toggleRestMode() {
    var btn = document.getElementById('restModeBtn');
    if (!btn) return;
    var currentlyEnabled = btn.dataset.enabled === 'true';
    try {
        var r = await fetch('/tools/department-hq/api/fleet/rest-mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enabled: !currentlyEnabled})
        });
        var d = await r.json();
        if (d.success) updateRestModeUI(d);
    } catch(e) { console.error('[Fleet] rest mode toggle failed', e); }
}

function updateRestModeUI(data) {
    var btn = document.getElementById('restModeBtn');
    var status = document.getElementById('restModeStatus');
    if (!btn) return;
    btn.dataset.enabled = data.enabled ? 'true' : 'false';
    // #5321d: dock semantics per the owner — DOCKED = connected to the cluster
    // and serving; UNDOCKED = Starships detached (resting). The lit state is
    // UNDOCKED ("light up when agents are on rest"). Real window from the API.
    var windowLabel = data.rest_window || '';
    // #5816: prefer the COMBINED predicate the gates actually read. A manual
    // force-undock detaches the ships while enabled/active_now are both false,
    // so the schedule-only test rendered a confident "⚓ DOCKED" over a fleet
    // that was taking no work. Fall back to the schedule test when the payload
    // predates `undocked`.
    var _undocked = (data.undocked !== undefined && data.undocked !== null)
        ? !!data.undocked
        : !!(data.enabled && data.active_now);
    if (_undocked) {
        // UNDOCKED — Starships detached from the cluster, resting.
        // #5816: violet, NOT blue. Blue now means DOCKED (see below), so the
        // two states must not share a hue or the highlight says nothing.
        btn.textContent = '⚓ UNDOCKED';
        btn.style.background = 'rgba(139,92,246,0.18)';
        btn.style.color = '#c4b5fd';
        btn.style.borderColor = '#8b5cf6';
        btn.style.boxShadow = '0 0 6px #8b5cf666';
        if (status) {
            status.style.display = 'inline-block';
            status.style.whiteSpace = 'pre-line';
            status.style.lineHeight = '1.3';
            status.style.color = '#60a5fa';
            status.textContent = '● STARSHIPS UNDOCKED' + (windowLabel ? '\n' + windowLabel : '');
        }
    } else if (data.enabled) {
        // DOCKED, undock scheduled — ships serving, will detach in the window.
        // #5816 (owner): DOCKED is the GOOD state and reads as SELECTED —
        // same treatment as an active PROFILE chip (rgba(0,188,212,0.2) /
        // #00bcd4). The "will detach later" nuance stays, but it moves to the
        // status text beside the button so the dock state itself is never dim.
        btn.textContent = '⚓ DOCKED';
        btn.style.background = 'rgba(0,188,212,0.2)';
        btn.style.color = '#00bcd4';
        btn.style.borderColor = '#00bcd4';
        btn.style.boxShadow = 'none';
        if (status) {
            status.style.display = 'inline-block';
            status.style.whiteSpace = 'pre-line';
            status.style.lineHeight = '1.3';
            status.style.color = '#f59e0b';
            status.textContent = '🕐 undock ' + (windowLabel || 'scheduled');
        }
    } else {
        // DOCKED — schedule off, ships connected around the clock.
        // #5816 (owner): was dim slate, which made the healthy everyday state
        // look inert. Highlighted like a selected PROFILE chip.
        btn.textContent = '⚓ DOCKED';
        btn.style.background = 'rgba(0,188,212,0.2)';
        btn.style.color = '#00bcd4';
        btn.style.borderColor = '#00bcd4';
        btn.style.boxShadow = 'none';
        if (status) {
            status.style.display = 'none';
            status.textContent = '';
        }
    }
}

function initFleetMap() {
    if (fleetMap) return;
    var el = document.getElementById('fleetMap');
    if (!el) return;

    fleetMap = L.map('fleetMap', {
        // Centre on Kytran Empowerment's Starbase, not a generic mid-continent point.
        // [42, -95] is central Kansas — roughly 2,400 km from anything we own, so the
        // fleet opened off to one side of an empty map. Every live node sits in the
        // Montreal/Boston corridor (`remote_nodes.extra_capabilities.geo_lat/geo_lon`):
        //   Starbase - A.R.C.H.I.E.        45.5019 / -73.5674   Montreal
        //   Starship - Defiant  USS-246    45.5447 / -73.5779   Rosemont
        //   Starship - Runabout USS-245    45.5048 / -73.6726   Saint-Laurent
        //   Citadel / Outpost - US         42.36   / -71.06     Boston
        // Deliberately a CONSTANT and not read from the node payload: the map is built
        // before the fleet data arrives, and re-centring on every refresh would yank
        // the view out from under someone mid-pan. Clicking a node in the list still
        // flies to it (see the list click handler further down).
        center: [45.5019, -73.5674],
        zoom: 5,
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
/* Cluster World Map (#3230) — REMOVED 2026-09-11. Its #clusterGeoMap
   container is gone: the richer circular fleet map (initFleetMap) took its
   place in the CLUSTER tab and draws the same /api/fleet-map response with
   node logos, live online/offline styling and the contractor favicons. */

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
        _dhqRefreshOpenNodePanel(data);
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

// Spread markers that share a point so each one can be seen and clicked.
// ⚠️ The RADIUS is the whole argument. Providers are continental (two SF offices
// 24 km apart is meaningless), but USS-245 and USS-246 sit at BYTE-IDENTICAL
// coordinates — 45.5017/-73.667, the same house — so no zoom level separates
// them and the provider-sized 0.22° would claim they are in different towns.
// Nodes get a radius that is visible at max zoom and honest at low zoom:
// ~1.3 km reads as ~40 px apart at zoom 12 and as one point when zoomed out,
// which is exactly what they are.
function spreadCoincident(items, clusterDeg, spreadDeg) {
    var used = new Array(items.length).fill(false);
    var result = items.map(function(p) { return Object.assign({}, p); });

    items.forEach(function(p, i) {
        if (used[i] || !p.lat || !p.lon) return;
        var cluster = [i];
        items.forEach(function(q, j) {
            if (j === i || used[j] || !q.lat || !q.lon) return;
            var d = Math.sqrt(Math.pow(p.lat - q.lat, 2) + Math.pow(p.lon - q.lon, 2));
            if (d < clusterDeg) cluster.push(j);
        });
        if (cluster.length < 2) return;
        cluster.forEach(function(idx) { used[idx] = true; });
        var cLat = cluster.reduce(function(s, idx) { return s + items[idx].lat; }, 0) / cluster.length;
        var cLon = cluster.reduce(function(s, idx) { return s + items[idx].lon; }, 0) / cluster.length;
        var step = (2 * Math.PI) / cluster.length;
        cluster.forEach(function(idx, k) {
            result[idx].lat = cLat + spreadDeg * Math.sin(k * step);
            result[idx].lon = cLon + spreadDeg * Math.cos(k * step);
            // the pin moved — say so, and keep the true position readable
            result[idx].spread_from = [items[idx].lat, items[idx].lon];
        });
    });
    return result;
}

// Unchanged provider behaviour, now expressed through the shared spreader.
function jitterClusteredProviders(providers) {
    return spreadCoincident(providers, 0.18, 0.22);
}

// ~2 km grouping, ~1.3 km spread — only genuinely co-located machines move.
function spreadCoincidentNodes(nodes) {
    return spreadCoincident(nodes, 0.02, 0.012);
}

function renderFleetIndex(data) {
    var panel = document.getElementById('fleetNodeIndex');
    if (!panel) return;
    while (panel.firstChild) panel.removeChild(panel.firstChild);
    function indexHead(text, color) {
        var h = document.createElement('div');
        h.className = 'fleet-index-head';  // grid-column: 1 / -1 — see department-hq.css
        h.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.6rem;letter-spacing:2px;color:'
            + color + ';margin-bottom:4px;';
        h.textContent = text;
        return h;
    }

    // STARBASE — the hub gets its own heading above NODES. It is the tier above
    // them (Starbase > Citadel / Outpost / Starship) and the one machine that is
    // not a remote node, so listing it as node #1 flattened the hierarchy.
    // data.hub is now enriched from its OWN remote_nodes row (see
    // fleet_service.get_fleet_map_data), which is why the row below carries a
    // real status instead of the hardcoded `online: true` this used to assert —
    // the hub rendered green even when its row said otherwise.
    if (data.hub) {
        panel.appendChild(indexHead('STARBASE', 'rgba(245,166,35,0.6)'));
        panel.appendChild(buildIndexItem(
            1, data.hub.name || 'HUB', data.hub.lat, data.hub.lon,
            (data.hub.status || 'online') === 'online', '#f5a623'));
    }

    // NODES — everything else. is_hub is the SAME machine as data.hub above; the
    // tab used to list "A.R.C.H.I.E. Hub" and "Archie Starbase" as two rows for
    // one computer, which is why the index showed 6 while the stat said 5.
    var entries = [];
    spreadCoincidentNodes((data.nodes || []).filter(function(n) { return !n.is_hub; }))
        .forEach(function(n) {
            if (!n.lat || !n.lon) return; // skip nodes with no coordinates
            entries.push({ label: n.name || n.hostname || n.node_id || 'Node', lat: n.lat, lon: n.lon, online: n.status === 'online' });
        });
    if (entries.length) {
        panel.appendChild(indexHead('NODES', 'rgba(0,220,170,0.5)'));
        entries.forEach(function(e, i) {
            panel.appendChild(buildIndexItem(i + 1, e.label, e.lat, e.lon, e.online, '#00dcaa'));
        });
    }

    // MESH — devices on the Headscale tailnet that are NOT fleet nodes. The map
    // reads remote_nodes, so these could never appear at any zoom: measured
    // 2026-09-11, headscale had 7 members online while the tab drew 5. The two
    // missing were shuttle-kytran (a personal device) and archie-starbase-subnet
    // (the archie_tailscale LAN subnet router). They are connected but they run
    // no work, which is exactly why they belong in their own section rather than
    // among NODES. No coordinates, so no pin and no click-to-zoom.
    var meshOnly = data.mesh || [];
    if (meshOnly.length) {
        var meshSection = document.createElement('div');
        meshSection.id = 'fleetMeshSection';
        meshSection.appendChild(indexHead('MESH', 'rgba(59,130,246,0.6)'));
        meshOnly.forEach(function(m, i) {
            var item = buildIndexItem(i + 1, (m.name || 'unknown').toUpperCase(),
                                      null, null, m.online, '#3b82f6');
            var ipTag = document.createElement('span');
            ipTag.style.cssText = 'font-size:0.52rem;letter-spacing:0.5px;margin-left:4px;color:rgba(59,130,246,0.6);';
            ipTag.textContent = m.mesh_ip || '';
            ipTag.title = 'On the mesh, not a fleet node — no agents, no inference.';
            item.appendChild(ipTag);
            meshSection.appendChild(item);
        });
        panel.appendChild(meshSection);
    }

    // HOSTED section — providers we reach at an address on our OWN infrastructure
    // (docker service name / loopback / private IP). They sit at the hub, so they
    // get no pin of their own: four markers stacked on the hub marker is worse
    // than none. self_hosted is derived from base_url server-side.
    // ⚠️ local_compute is the STRONGER claim and only two qualify — omniroute and
    // claude answer here but think elsewhere. The row says which, because
    // "hosted" alone would read as "we run Claude", which we do not.
    var hosted = (data.providers || []).filter(function(p) { return p.self_hosted; });
    if (hosted.length) {
        var hostedSection = document.createElement('div');
        hostedSection.id = 'fleetHostedSection';
        var hhdr = document.createElement('div');
        hhdr.className = 'fleet-index-head';
        hhdr.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.6rem;letter-spacing:2px;color:rgba(0,220,170,0.5);margin-top:10px;margin-bottom:4px;';
        hhdr.textContent = 'HOSTED';
        hostedSection.appendChild(hhdr);
        hosted.forEach(function(h, i) {
            var label = (h.provider_key || 'Unknown').toUpperCase();
            var item = buildIndexItem(i + 1, label, null, null, h.is_active, '#00dcaa');
            var kind = document.createElement('span');
            kind.style.cssText = 'font-size:0.52rem;letter-spacing:0.5px;margin-left:4px;color:'
                + (h.local_compute ? 'rgba(0,220,170,0.65)' : 'rgba(249,115,22,0.7)') + ';';
            kind.textContent = h.local_compute ? 'local gpu' : 'gateway';
            kind.title = h.local_compute
                ? 'Runs on our own hardware.'
                : 'Endpoint is ours; the inference happens at an external provider.';
            item.appendChild(kind);
            hostedSection.appendChild(item);
        });
        panel.appendChild(hostedSection);
    }

    // CONTRACTORS section — EXTERNAL providers only; the hosted ones above are
    // not contractors and counting them here double-counted the fleet.
    var contractors = (data.providers || []).filter(function(p) { return !p.self_hosted && p.lat && p.lon; });
    if (contractors.length) {
        var contractorSection = document.createElement('div');
        contractorSection.id = 'fleetContractorSection';
        var chdr = document.createElement('div');
        chdr.className = 'fleet-index-head';
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
        // The Starbase now opens the SAME LCARS panel as every other node. Two
        // reasons this is not just consistency:
        //  1. the popup it replaces hardcoded `Status: ONLINE` — the hub pin claimed
        //     green regardless of what its own remote_nodes row said. The index row
        //     above was fixed for exactly this; the pin was missed.
        //  2. the popup showed two fields (city, status) for the machine that has the
        //     most hardware to show — 20 cores, 128 GB, two cards, the full warm set.
        // Prefer the is_hub row from data.nodes: data.hub is a thin pin record, while
        // that row is the Starbase's full remote_nodes payload. The panel degrades
        // honestly on the fallback ('--' rows), and _dhqRenderNodeModels already
        // guards a missing node_id.
        var hubFull = (data.nodes || []).filter(function(n) { return n.is_hub; })[0];
        marker.on('click', function() { showNodeDetail(hubFull || hub); });
        fleetMarkers.push(marker);
    }

    window._fleetNodeRegistry = window._fleetNodeRegistry || {};
    // Skip the hub's own node row (its pin is drawn above) and spread the rest,
    // so the two Starships at identical coordinates are both clickable.
    spreadCoincidentNodes((data.nodes || []).filter(function(n) { return !n.is_hub; }))
        .forEach(function(node) {
        if (!node.lat || !node.lon) return;
        var isOnline = node.status === 'online';
        // (An `isOutpost` flag used to be computed here and was never read — every
        // marker renders the same aries icon and only `isOnline` changes its colour.
        // Removed rather than left looking load-bearing. Node TIER is conveyed by the
        // index headings and the panel's Mode/Inference rows.)
        // Store node in registry so popup buttons can reference it by id
        if (node.node_id) window._fleetNodeRegistry[node.node_id] = node;

        var marker = L.marker([node.lat, node.lon], {
            icon: L.divIcon({
                className: 'fleet-marker-node ' + (isOnline ? '' : 'offline'),
                html: '<div style="width:34px;height:34px;border-radius:50%;border:2px solid ' + (isOnline ? '#a3e635' : '#6b7280') + ';background:#0a1628;display:flex;align-items:center;justify-content:center;overflow:hidden;' + (isOnline ? 'box-shadow:0 0 6px rgba(163,230,53,0.5);' : 'opacity:0.5;filter:grayscale(1);') + '"><img src="/static/img/aries-logo.png" style="width:24px;height:24px;object-fit:contain;" onerror="this.outerHTML=\'<span style=font-size:13px>♈</span>\'"></div>',
                iconSize: [34, 34],
                iconAnchor: [17, 17],
            }),
        }).addTo(fleetMap);


        // ONE detail surface per click. This marker used to bind a Leaflet popup AND
        // open the LCARS panel, so a single click produced both, overlapping — the
        // popup covering the panel it had just opened. The LCARS panel wins: it is the
        // richer surface, it carries the agent cross-links, and it is the one the rest
        // of Department HQ uses. Everything the popup showed now lives in it (Location,
        // Provider, Max model and Models were the four fields only the popup had).
        //
        // The popup CONTENT builders (`nodeLabel`, `popupRows`, `popupFooter`,
        // `nodeIdStr`, `inferLabel`) went with it — once nothing reads them they are
        // dead weight, and dead code with a comment claiming it is live is worse than
        // either. `buildFleetPopup` itself STAYS: the hub pin and the cloud-provider
        // pins still use popups, and only the node markers changed.
        // `isOnline` also stays — the marker icon above colours itself from it.
        marker.on('click', function() { showNodeDetail(node); });
        fleetMarkers.push(marker);
    });

    // Self-hosted providers live AT the hub — pinning them drops extra markers on
    // top of the hub's own pin and makes the cluster look bigger than it is.
    var pinnable = (data.providers || []).filter(function(p) { return !p.self_hosted; });
    jitterClusteredProviders(pinnable).forEach(function(prov) {
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

function buildFleetPopup(title, rows, footer) {
    var html = '<div class="fleet-popup-title">' + title + '</div>';
    rows.forEach(function(row) {
        html += '<div class="fleet-popup-row"><span class="fleet-popup-label">' + row[0] + '</span><span class="fleet-popup-value">' + row[1] + '</span></div>';
    });
    if (footer) html += footer;
    return html;
}

function updateFleetStats(data) {
    var nodeCount = (data.nodes || []).filter(function(n) { return n.status === 'online'; }).length;
    // ⚠️ HONESTY: this label sits beside the MAP, so it must count what the map
    // can actually draw. It used to read "26 providers active" while six pins
    // were rendered — every provider whose key is absent from
    // fleet_service.PROVIDER_LOCATIONS has no lat/lon and is silently dropped by
    // the pin filter below. Same shape as the "14 loaded models" and "0% ok"
    // defects: an honest number describing a different population.
    var activeProviders = (data.providers || []).filter(function(p) { return p.is_active; });
    var hostedCount = activeProviders.filter(function(p) { return p.self_hosted; }).length;
    var external = activeProviders.filter(function(p) { return !p.self_hosted; });
    var mappable = external.filter(function(p) { return p.lat && p.lon; }).length;
    var provCount = external.length;
    var nodeEl = document.getElementById('fleetStatNodes');
    var provEl = document.getElementById('fleetStatProviders');
    if (nodeEl) nodeEl.textContent = nodeCount + ' node' + (nodeCount !== 1 ? 's' : '') + ' online';
    if (provEl) {
        var label = (mappable === provCount)
            ? provCount + ' contractor' + (provCount !== 1 ? 's' : '') + ' active'
            : mappable + ' of ' + provCount + ' contractors mapped';
        if (hostedCount) label += ' · ' + hostedCount + ' hosted';
        provEl.textContent = label;
        provEl.title = provCount + ' external contractors (the same contractor_providers '
            + 'list the Contractors tab shows), ' + (provCount - mappable) + ' with no '
            + 'location on file; plus ' + hostedCount + ' hosted on our own '
            + 'infrastructure, listed above the contractors and not pinned because they '
            + 'sit at the hub.';
    }
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

// The parts of a node row that MOVE. Hardware is excluded deliberately: it changes
// only on real re-provisioning, and including it would repaint the panel on a
// heartbeat that merely re-reported the same card.
function _dhqNodeSig(node) {
    return JSON.stringify([
        node.status, node.last_heartbeat, node.ollama_models,
        (node.agents || []).length, node.gpu_vram_gb, node.max_model_gb,
    ]);
}

// A fleet poll has just produced a newer row for whatever node is open. Without this
// the panel is frozen at the instant it was clicked: a node that goes offline, or whose
// heartbeat goes stale, keeps reading healthy for as long as the modal stays open —
// which is exactly the window in which someone is looking at it to decide something.
//
// ⚠️ Signature-gated, per the Approvals-tab precedent: an UNCHANGED payload must not
// touch the DOM. Repainting every poll would fight the reader for scroll position and
// re-run the models render on every cycle.
// ⚠️ A node missing from the fresh payload (retired mid-view) leaves the last known
// state on screen. Blanking the panel would look like a UI fault rather than a node
// that no longer exists.
function _dhqRefreshOpenNodePanel(data) {
    var modal = document.getElementById('fleetNodeModal');
    if (!modal || modal.style.display === 'none') return;
    if (!window._dhqOpenNodeId) return;
    var fresh = (data.nodes || []).filter(function(n) {
        return String(n.node_id) === String(window._dhqOpenNodeId);
    })[0];
    if (!fresh) return;
    if (_dhqNodeSig(fresh) === window._dhqOpenNodeSig) return;
    showNodeDetail(fresh);
}

function showNodeDetail(node) {
    var panel = document.getElementById('fleetDetailPanel');
    var titleEl = document.getElementById('fleetDetailTitle');
    var body = document.getElementById('fleetDetailBody');
    if (!panel || !titleEl || !body) return;

    titleEl.textContent = node.node_name || node.name || node.hostname;

    // Which node this panel is showing, and a signature of the parts that move, so a
    // fleet poll can refresh it in place — see _dhqRefreshOpenNodePanel.
    window._dhqOpenNodeId = node.node_id || null;
    window._dhqOpenNodeSig = _dhqNodeSig(node);

    // Build detail content using DOM methods (trusted server data)
    body.textContent = '';

    // Offline leads, rather than sitting in the last section. check_fleet_health returns
    // an offline node's agents to barracks (fleet.md -> Node Health + Lifecycle), so the
    // Deployed Agents list further down is describing assignments that are NOT running.
    // A reader who skimmed the top of this panel had no way to know that.
    if ((node.status || '').toLowerCase() !== 'online') {
        var offBanner = document.createElement('div');
        offBanner.style.cssText = 'margin:0 0 10px;padding:7px 10px;border-left:3px solid #ef4444;'
            + 'background:rgba(239,68,68,0.12);font-size:0.72rem;color:#fca5a5;line-height:1.45;';
        offBanner.textContent = 'Node is ' + String(node.status || 'unknown').toUpperCase()
            + '. Its agents return to barracks while it is down, so any assignment listed'
            + ' below is not currently running.';
        body.appendChild(offBanner);
    }
    // Consolidated from the retired map popup — these four were the only fields it
    // showed that this panel did not, so removing the popup would otherwise have LOST
    // them. Same derivations the popup used.
    var locationStr = [node.location_city, node.location_country].filter(Boolean).join(', ') || '--';

    // VRAM. fleet.md is emphatic that `gpu_vram_gb` is the LARGEST SINGLE card and
    // never the sum — it is the safety input `_fits()` and `get_agents_for_hardware()`
    // size ONE model against. This row rendered a flat "12 GB" for the Starbase, which
    // reads as the whole machine when it actually holds 20 GB across two cards. The
    // total is shown ONLY when the node declared one
    // (extra_capabilities.gpu_vram_total_gb); an undeclared total is not inferred to
    // equal the largest card, because absence of a declaration is not proof of one card.
    var vramStr = '--';
    if (node.gpu_vram_gb) {
        vramStr = node.gpu_vram_gb + ' GB (largest card)';
        var vramTotal = parseFloat(node.gpu_vram_total_gb);
        if (vramTotal && vramTotal > parseFloat(node.gpu_vram_gb)) {
            vramStr += ' \u00b7 ' + vramTotal + ' GB total';
        }
    }

    // Heartbeat staleness, on the SAME 2-minute threshold `check_fleet_health` uses to
    // move a node's agents to barracks (fleet.md -> Node Health). A bare timestamp
    // carried no information: "2026-09-21, 11:04:02" looks identical whether it is 8
    // seconds or 8 days old, so a dead node read the same as a healthy one.
    // Math.max(0, ...) keeps a clock-skewed future heartbeat from rendering "-3s ago".
    var hbStr = '--';
    var hbColour = null;
    if (node.last_heartbeat) {
        var hbIso = (node.last_heartbeat.endsWith('Z') || node.last_heartbeat.indexOf('+') !== -1)
            ? node.last_heartbeat : node.last_heartbeat + 'Z';
        var hbAgeS = Math.max(0, (Date.now() - new Date(hbIso).getTime()) / 1000);
        var hbRel = hbAgeS < 60 ? Math.round(hbAgeS) + 's ago'
            : hbAgeS < 3600 ? Math.round(hbAgeS / 60) + 'm ago'
            : hbAgeS < 86400 ? Math.round(hbAgeS / 3600) + 'h ago'
            : Math.round(hbAgeS / 86400) + 'd ago';
        hbStr = new Date(hbIso).toLocaleString() + ' \u00b7 ' + hbRel;
        hbColour = hbAgeS < 120 ? '#10b981' : (hbAgeS < 600 ? '#f59e0b' : '#ef4444');
    }

    var sections = [
        { title: 'Hardware', rows: [
            ['GPU', node.gpu_model || node.gpu || 'None'],
            ['VRAM', vramStr],
            ['CPU', (node.cpu_cores ? node.cpu_cores + ' cores' : '--') + (node.cpu_model ? ' · ' + node.cpu_model : '')],
            ['RAM', (node.ram_gb || node.ram) ? (node.ram_gb || node.ram) + ' GB' : '--'],
            // Max model is the CPU ceiling from `remote_nodes.max_model_gb`, not a disk
            // size — see fleet.md. '--' means uncapped (GPU nodes are deliberately so).
            ['Max model', node.max_model_gb ? node.max_model_gb + ' GB' : '-- (uncapped)'],
            // Derived server-side from gpu_available + gpu_vram_gb when the node
            // declares no extra_capabilities.inference_type — see
            // fleet_service.derive_inference_type. Before that, the payload defaulted
            // to the bare literal 'gpu', so Citadel (no GPU, 31.3 GB RAM, capped at
            // 6 GB) reported GPU. DISPLAY ONLY: placement reads the hardware columns.
            ['Inference', node.inference_type ? String(node.inference_type).toUpperCase() : '--']
        ]},
        { title: 'Network', rows: [
            ['Hostname', node.hostname || '--'],
            ['Mesh IP', node.mesh_ip || '--'],
            ['Mode', node.deployment_mode || '--'],
            ['Location', locationStr],
            // Region belongs with the other placement/topology fields, not under
            // Hardware where it sat between VRAM and RAM.
            ['Region', node.region || '--'],
            ['Provider', node.provider || '--']
        ]},
        { title: 'Status', rows: [
            ['Status', node.status || '--'],
            ['Last Heartbeat', hbStr, hbColour]
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
            // Optional third element = value colour. Rows stay 2-element by default,
            // so nothing existing changes.
            if (r[2]) val.style.color = r[2];
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

    // Hardware-aware AI model recommendation (#3731)
    var modelsContainer = document.createElement('div');
    body.appendChild(modelsContainer);
    _dhqRenderNodeModels(node, modelsContainer);

    var modal = document.getElementById('fleetNodeModal');
    if (modal) modal.style.display = 'flex';
}

// #3731 — hardware-aware model recommendation panel inside the node detail modal.
// Reads GET /api/nodes/<node_id>/model-recommendation, renders the warm set, and
// offers a one-click "download recommended" that POSTs to provision-warm-set
// (which fans out to the OTA model_pull/checkpoint_pull queue).
function _dhqRenderNodeModels(node, container) {
    container.textContent = '';
    var h = document.createElement('div');
    h.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;letter-spacing:2px;color:var(--cat-accent,#00ffff);margin:14px 0 6px;text-transform:uppercase;border-bottom:1px solid rgba(0,255,255,0.2);padding-bottom:4px;';
    h.textContent = 'AI Models';
    container.appendChild(h);

    var loading = document.createElement('div');
    loading.style.cssText = 'font-size:0.7rem;color:rgba(163,230,53,0.6);padding:6px 0;';
    loading.textContent = 'Analyzing hardware…';
    container.appendChild(loading);

    // node_key, NOT node_id: this endpoint keys on the VARCHAR remote_nodes.node_id
    // while the payload's `node_id` is the int PK every other node route wants. Passing
    // the int here returns a clean 404 that renders as "Recommendation unavailable" —
    // indistinguishable from a node the planner has nothing to say about.
    var nid = node.node_key;
    if (!nid) { loading.textContent = 'No node key — cannot compute recommendation.'; return; }

    // Cached on the HARDWARE FINGERPRINT, not on a timer. The endpoint is a pure
    // derivation from cpu_cores/ram_gb/gpu_available/gpu_vram_gb/gpu_model
    // (fleet_node_routes.get_node_model_recommendation -> recommend_from_node_row) and
    // reads no live model state, so its answer cannot go stale while those inputs hold.
    // A fingerprint invalidates exactly when they change; a TTL would do strictly worse
    // in both directions — re-fetching an unchanged answer, and serving a stale one for
    // the rest of the window after a card was added.
    // ⚠️ The "Loaded now" chips are NOT cached: they come from node.ollama_models on the
    // map payload, which refreshes every poll. Only the hardware half is reused, and
    // only a SUCCESSFUL response is stored — caching a failure would make one blip
    // permanent for the session.
    window._dhqRecCache = window._dhqRecCache || {};
    var recFp = [nid, node.cpu_cores, node.ram_gb || node.ram,
                 node.gpu_vram_gb, node.gpu_model || node.gpu].join('|');
    var recPromise = window._dhqRecCache[recFp]
        ? Promise.resolve(window._dhqRecCache[recFp])
        : fetch('/tools/department-hq/api/nodes/' + encodeURIComponent(nid) + '/model-recommendation')
            .then(function(r){ return r.json(); })
            .then(function(d){ if (d && d.success) window._dhqRecCache[recFp] = d; return d; });
    recPromise
      .then(function(data){
        if (!data || !data.success) { loading.textContent = 'Recommendation unavailable.'; return; }
        loading.remove();
        var rec = data.recommendation || {};

        var tierRow = document.createElement('div');
        tierRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);';
        var tl = document.createElement('span'); tl.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.7rem;color:rgba(163,230,53,0.6);letter-spacing:1px;'; tl.textContent = 'Tier';
        var tv = document.createElement('span'); tv.style.cssText = 'font-size:0.78rem;color:#e0e0e0;text-align:right;'; tv.textContent = rec.tier || '--';
        tierRow.appendChild(tl); tierRow.appendChild(tv); container.appendChild(tierRow);

        // WHAT IT ACTUALLY HAS, before what it should have. This panel showed only the
        // recommendation, so it answered "what belongs here" and never "what is here" —
        // and the gap between those two is the only actionable thing on the screen.
        //
        // ⚠️ THREE states, not two. `ollama_models` ABSENT means the heartbeat never
        // reported an inventory; that is UNKNOWN and must not render as "None loaded",
        // which would read as a node sitting empty. An empty ARRAY is a real "none".
        var loadedKnown = Array.isArray(node.ollama_models);
        var loaded = loadedKnown ? node.ollama_models : [];
        // ⚠️ Ollama treats `name` and `name:latest` as the SAME model, and the two
        // sides of this diff use different spellings: the node's heartbeat reports
        // `nomic-embed-text:latest` while the recommended warm set names
        // `nomic-embed-text`. Measured live on USS-246, comparing raw strings produced
        // BOTH halves of the error at once — the loaded chip rendered grey (read: "extra,
        // not recommended") AND the model was listed under "Missing from warm set (1)"
        // with a button offering to pull what was already there. A diff that invents work
        // is worse than no diff, so normalise both sides before comparing.
        var _tagNorm = function(m){
            m = String(m == null ? '' : m).trim();
            return m && m.indexOf(':') === -1 ? m + ':latest' : m;
        };
        var recSet = {};
        (rec.recommended_ollama || []).forEach(function(m){ recSet[_tagNorm(m)] = true; });
        var loadedSet = {};
        loaded.forEach(function(m){ loadedSet[_tagNorm(m)] = true; });

        var loadedLbl = document.createElement('div');
        loadedLbl.style.cssText = 'font-size:0.68rem;color:rgba(163,230,53,0.6);letter-spacing:1px;margin:8px 0 4px;';
        loadedLbl.textContent = 'Loaded now:';
        container.appendChild(loadedLbl);

        var loadedChips = document.createElement('div');
        loadedChips.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;';
        if (!loadedKnown) {
            var unk = document.createElement('span');
            unk.style.cssText = 'font-size:0.7rem;color:#888;';
            unk.textContent = 'Not reported by this node.';
            loadedChips.appendChild(unk);
        } else if (!loaded.length) {
            var non = document.createElement('span');
            non.style.cssText = 'font-size:0.7rem;color:#888;';
            non.textContent = 'None loaded.';
            loadedChips.appendChild(non);
        } else {
            loaded.forEach(function(m){
                // green = in the warm set · grey = present but not recommended (extra,
                // not wrong — an operator may have pulled it deliberately).
                var inSet = !!recSet[_tagNorm(m)];
                var c = document.createElement('span');
                c.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;border-radius:10px;padding:2px 8px;'
                    + (inSet
                        ? 'color:#10b981;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.35);'
                        : 'color:#9ca3af;background:rgba(156,163,175,0.08);border:1px solid rgba(156,163,175,0.25);');
                c.textContent = m + (inSet ? ' \u2713' : '');
                loadedChips.appendChild(c);
            });
        }
        container.appendChild(loadedChips);

        // The gap, stated plainly — this is what the download button below acts on.
        var missing = (rec.recommended_ollama || []).filter(function(m){ return !loadedSet[_tagNorm(m)]; });
        if (loadedKnown && missing.length) {
            var missLbl = document.createElement('div');
            missLbl.style.cssText = 'font-size:0.68rem;color:rgba(251,191,36,0.75);letter-spacing:1px;margin:8px 0 4px;';
            missLbl.textContent = 'Missing from warm set (' + missing.length + '):';
            container.appendChild(missLbl);
            var missChips = document.createElement('div');
            missChips.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;';
            missing.forEach(function(m){
                var c = document.createElement('span');
                c.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;color:#fbbf24;background:rgba(251,191,36,0.1);border:1px solid rgba(251,191,36,0.35);border-radius:10px;padding:2px 8px;';
                c.textContent = m; missChips.appendChild(c);
            });
            container.appendChild(missChips);
        }

        var warmLbl = document.createElement('div');
        warmLbl.style.cssText = 'font-size:0.68rem;color:rgba(163,230,53,0.6);letter-spacing:1px;margin:8px 0 4px;';
        warmLbl.textContent = 'Recommended (warm set):';
        container.appendChild(warmLbl);

        var chips = document.createElement('div');
        chips.style.cssText = 'display:flex;flex-wrap:wrap;gap:5px;';
        (rec.recommended_ollama || []).forEach(function(m){
            var c = document.createElement('span');
            c.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;color:#00ffff;background:rgba(0,255,255,0.1);border:1px solid rgba(0,255,255,0.3);border-radius:10px;padding:2px 8px;';
            c.textContent = m; chips.appendChild(c);
        });
        if (rec.recommended_comfyui) {
            var cc = document.createElement('span');
            cc.style.cssText = 'font-family:\'IBM Plex Mono\',monospace;font-size:0.65rem;color:#a855f7;background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.3);border-radius:10px;padding:2px 8px;';
            cc.textContent = '🎨 ' + rec.recommended_comfyui; chips.appendChild(cc);
        }
        if (!(rec.recommended_ollama || []).length && !rec.recommended_comfyui) {
            var none = document.createElement('span'); none.style.cssText = 'font-size:0.7rem;color:#888;'; none.textContent = 'Nothing fits this hardware.'; chips.appendChild(none);
        }
        container.appendChild(chips);

        if ((rec.cannot_run_ollama || []).length) {
            var cant = document.createElement('div');
            cant.style.cssText = 'font-size:0.62rem;color:#888;margin-top:6px;';
            cant.textContent = 'Can’t run: ' + rec.cannot_run_ollama.join(', ');
            container.appendChild(cant);
        }

        if ((rec.recommended_ollama || []).length || rec.recommended_comfyui) {
            var btn = document.createElement('button');
            btn.style.cssText = 'margin-top:10px;width:100%;background:rgba(0,255,255,0.15);border:1px solid rgba(0,255,255,0.5);color:#00ffff;padding:8px;border-radius:4px;cursor:pointer;font-size:0.72rem;letter-spacing:1px;font-family:\'IBM Plex Mono\',monospace;';
            // Name the gap: "download 2 missing" is actionable, "download recommended"
            // is not — and when nothing is missing the button says so instead of
            // implying there is work to do.
            btn.textContent = (loadedKnown && missing.length)
                ? '\u2b07 DOWNLOAD ' + missing.length + ' MISSING MODEL' + (missing.length === 1 ? '' : 'S')
                : (loadedKnown && !missing.length
                    ? '\u2713 WARM SET COMPLETE \u2014 RE-PULL ANYWAY'
                    : '\u2b07 DOWNLOAD RECOMMENDED MODELS');
            btn.addEventListener('click', function(){ _dhqProvisionWarmSet(node, btn); });
            container.appendChild(btn);
        }
      })
      .catch(function(){ loading.textContent = 'Recommendation request failed.'; });
}

function _dhqProvisionWarmSet(node, btn) {
    if (node.id === undefined || node.id === null) { alert('Node has no numeric id; cannot queue pulls.'); return; }
    if (!confirm('Queue download of the recommended models onto ' + (node.node_name || node.node_id) + '? They pull over the mesh in the background.')) return;
    btn.disabled = true; btn.textContent = 'QUEUEING…';
    fetch('/tools/department-hq/api/nodes/' + encodeURIComponent(node.id) + '/provision-warm-set', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({include_comfyui: true})
    }).then(function(r){ return r.json(); }).then(function(data){
        if (data && data.success) {
            var n = (data.queued && data.queued.models ? data.queued.models.length : 0) + (data.queued && data.queued.checkpoint ? 1 : 0);
            btn.textContent = '✓ QUEUED ' + n + ' DOWNLOAD' + (n === 1 ? '' : 'S');
            btn.style.color = '#10b981'; btn.style.borderColor = 'rgba(16,185,129,0.5)';
        } else {
            btn.disabled = false; btn.textContent = 'ERROR — RETRY'; btn.style.color = '#ef4444';
        }
    }).catch(function(){ btn.disabled = false; btn.textContent = 'ERROR — RETRY'; btn.style.color = '#ef4444'; });
}

function closeFleetDetail() {
    var modal = document.getElementById('fleetNodeModal');
    if (modal) modal.style.display = 'none';
    // Stop the poll refreshing a panel nobody is looking at.
    window._dhqOpenNodeId = null;
    window._dhqOpenNodeSig = null;
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
        var [provResp, modeResp, escResp] = await Promise.all([
            fetch('/tools/department-hq/api/external-providers'),
            fetch('/tools/department-hq/api/routing-mode'),
            fetch('/tools/department-hq/api/escalation-mode')
        ]);
        if (!provResp.ok) throw new Error('Failed to load providers');
        var data = await provResp.json();
        var routingMode = 'full';
        if (modeResp.ok) {
            var modeData = await modeResp.json();
            if (modeData.success) routingMode = modeData.routing_mode || 'full';
        }
        // #4659 — Cloud AI master toggle reflects escalation_mode (sovereign default).
        var escalationMode = 'local_only';
        if (escResp.ok) {
            var escData = await escResp.json();
            if (escData.success) escalationMode = escData.escalation_mode || 'local_only';
        }
        renderCloudMasterToggle(escalationMode);
        renderContractors(data.providers || [], routingMode, {
            creed_total_24h: data.creed_total_24h || 0,
            creed_blocked_24h: data.creed_blocked_24h || 0
        });
        loadFleetUsage();
        loadOmnirouteQuota();
    } catch (e) {
        console.error('loadContractors error:', e);
        var grid = document.getElementById('contractors-grid');
        if (grid) grid.innerHTML = '<span class="briefing-muted">Failed to load contractors</span>';
    }
}

// DS9 Phase 2 — OmniRoute quota awareness card. Reads the per-provider throttle
// snapshot (observes only). The card is deliberately self-contained: a failed or
// empty read lands on "no data yet" and never disturbs the providers grid.
async function loadOmnirouteQuota() {
    var el = document.getElementById('omnirouteQuotaCard');
    if (el) el.innerHTML = '<span class="briefing-muted">OmniRoute quota: loading…</span>';
    try {
        var resp = await fetch('/tools/department-hq/api/contractors/omniroute-quota');
        var res = await resp.json();
        if (!res || !res.success) {
            if (el) el.innerHTML = '<span class="briefing-muted">OmniRoute quota: unavailable</span>';
            return;
        }
        var providers = Object.keys(res.providers || {});
        if (providers.length === 0) {
            if (el) el.innerHTML = '<span class="briefing-muted">OmniRoute quota: no calls in window yet</span>';
            return;
        }
        var order = { exhausted: 0, degraded: 1, ok: 2, unknown: 3 };
        providers.sort(function(a, b) {
            var sa = res.providers[a].status, sb = res.providers[b].status;
            return (order[sa] == null ? 9 : order[sa]) - (order[sb] == null ? 9 : order[sb]);
        });
        var rows = providers.map(function(p) {
            var d = res.providers[p];
            var color = d.status === 'exhausted' ? '#ff6b6b'
                      : d.status === 'degraded' ? '#f5a623'
                      : d.status === 'ok' ? '#00ffcc' : 'var(--dhq-text-dim,#9aa)';
            var rate = (d.throttle_rate == null) ? '—' : (d.throttle_rate * 100).toFixed(0) + '%';
            var when = d.window_hours ? 'last ' + d.window_hours + 'h' : '—';
            return '<div style="display:flex;align-items:center;gap:12px;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.08);">' +
                '<span style="width:10px;height:10px;border-radius:50%;background:' + color + ';flex-shrink:0;"></span>' +
                '<span style="flex:1;font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;">' + escapeHtml(d.display_name || p) + '</span>' +
                '<span style="font-size:0.7rem;color:var(--dhq-text-dim,#9aa);">' + when + '</span>' +
                '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;color:' + color + ';width:48px;text-align:right;">' + escapeHtml(d.status) + '</span>' +
                '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;width:44px;text-align:right;">' + rate + '</span>' +
            '</div>';
        }).join('');
        if (el) el.innerHTML =
            '<div class="dhq-dispatch-section">' +
              '<div class="dhq-section-title">OMNIROUTE QUOTA</div>' +
              '<div style="font-size:0.68rem;color:var(--dhq-text-dim,#9aa);padding:2px 12px;">throttled share of calls per upstream — refreshed every 15 min</div>' +
              rows +
            '</div>';
    } catch (e) {
        console.error('loadOmnirouteQuota error:', e);
        if (el) el.innerHTML = '<span class="briefing-muted">OmniRoute quota: unavailable</span>';
    }
}

// #4659 — Cloud AI master toggle. OFF = Sovereign (local_only, default).
// ON = Ask-first: cloud available for testing/reviewing/comparing other AI,
// every cloud call waits for Telegram Approve/Deny. Wired to escalation_mode.
function renderCloudMasterToggle(mode) {
    var el = document.getElementById('cloudMasterToggle');
    if (!el) return;
    var on = (mode === 'ask_first' || mode === 'auto');
    var stateLabel = on ? 'ON · Ask-first' : 'OFF · Sovereign';
    var stateColor = on ? '#f5a623' : '#00ffcc';
    var sub = on
        ? 'Cloud AI is available for testing / reviewing / comparing against other AI. Every cloud call waits for your Telegram Approve/Deny — nothing leaves the cluster silently. Free tiers are budget-guarded.'
        : 'Local &amp; sovereign. Your systems and data stay on-cluster — no external AI is used. Turn on only to test / review / compare against other AI.';
    var toggle = document.createElement('div');
    toggle.style.cssText = 'border:1px solid rgba(255,255,255,0.12);border-radius:10px;padding:14px 16px;background:rgba(0,0,0,0.25);display:flex;align-items:center;gap:16px;flex-wrap:wrap;';
    toggle.innerHTML =
        '<div style="flex:1;min-width:220px;">' +
          '<div style="font-family:\'Antonio\',sans-serif;letter-spacing:2px;text-transform:uppercase;font-size:0.95rem;color:' + stateColor + ';">☁️ Cloud AI &nbsp;·&nbsp; ' + stateLabel + '</div>' +
          '<div style="font-size:0.72rem;color:var(--dhq-text-dim,#9aa);margin-top:6px;line-height:1.4;">' + sub + '</div>' +
        '</div>' +
        '<button id="cloudMasterBtn" type="button" role="switch" aria-checked="' + on + '" ' +
          'title="' + (on ? 'Disable cloud (return to Sovereign)' : 'Enable cloud (Ask-first)') + '" ' +
          'style="cursor:pointer;border:none;border-radius:22px;width:88px;height:36px;position:relative;flex-shrink:0;' +
          'background:' + (on ? '#f5a623' : 'rgba(255,255,255,0.15)') + ';transition:background 0.2s;">' +
          '<span style="position:absolute;top:3px;left:' + (on ? '55px' : '3px') + ';width:30px;height:30px;border-radius:50%;background:#010409;transition:left 0.2s;"></span>' +
        '</button>';
    el.innerHTML = '';
    el.appendChild(toggle);
    var btn = document.getElementById('cloudMasterBtn');
    if (btn) btn.addEventListener('click', function() { setCloudMaster(!on); });
}

async function setCloudMaster(turnOn) {
    var target = turnOn ? 'ask_first' : 'local_only';
    try {
        var resp = await fetch('/tools/department-hq/api/escalation-mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ escalation_mode: target })
        });
        var res = await resp.json();
        if (res && res.success) {
            renderCloudMasterToggle(res.escalation_mode || target);
            if (typeof showToast === 'function') {
                showToast(turnOn ? 'Cloud AI enabled (Ask-first)' : 'Cloud AI disabled — Sovereign / local', 'success');
            }
        } else if (typeof showToast === 'function') {
            showToast('Failed to change cloud mode', 'error');
        }
    } catch (e) {
        console.error('setCloudMaster failed:', e);
        if (typeof showToast === 'function') showToast('Failed to change cloud mode', 'error');
    }
}

// DS9 PR 4 — class badges, measured health, and the second switch.
//
// Everything here reads fields the PR 3 probe writes. A provider that has never been
// probed has health_status === null, which renders as "unknown" and NEVER as a number:
// an unmeasured provider is not a fast one, and inventing a latency is how a fabricated
// figure becomes the ranking.

var CONTRACTOR_CLASS_META = {
    paid:       { label: 'PAID',       color: '#f59e0b', title: 'Requires a paid key. Never auto-dispatched unless you enable routing below.' },
    free_tier:  { label: 'FREE TIER',  color: '#38bdf8', title: 'No paid key, but the upstream imposes real limits.' },
    keyless:    { label: 'KEYLESS',    color: '#4ade80', title: 'No API key required. Convenient, often capability-limited.' },
    image_only: { label: 'IMAGE ONLY', color: '#a78bfa', title: 'Serves image generation, not text. Cannot back a roster agent.' },
    local:      { label: 'LOCAL',      color: '#94a3b8', title: 'Runs on the mesh.' }
};

var CONTRACTOR_HEALTH_META = {
    ok:           { label: 'OK',         color: '#4ade80' },
    rate_limited: { label: 'RATE LIM',   color: '#fbbf24', title: 'Refused for volume (429). Transient.' },
    auth_error:   { label: 'AUTH ERR',   color: '#f87171', title: 'The credential was refused (401/403). Fix the key or disable it.' },
    no_key:       { label: 'NO KEY',     color: '#f87171', title: 'Configured but no credential is available.' },
    unsupported:  { label: 'UNSUPPORTED', color: '#a78bfa', title: 'Answered, but not for this capability.' },
    unreachable:  { label: 'UNREACHABLE', color: '#f87171', title: 'No response at all.' },
    error:        { label: 'ERROR',      color: '#f87171' }
};

function contractorClassBadge(p) {
    var meta = CONTRACTOR_CLASS_META[p.provider_class];
    if (!meta) {
        return '<span class="contractor-meta-badge" style="border-color:rgba(148,163,184,0.45);color:#94a3b8"'
            + ' title="Not yet classified — the health probe has not measured this provider yet.">UNMEASURED</span>';
    }
    return '<span class="contractor-meta-badge" style="border-color:' + meta.color + '55;color:' + meta.color + '"'
        + ' title="' + escapeHtml(meta.title) + '">' + meta.label + '</span>';
}

function contractorHealthBadge(p) {
    var st = p.health_status;
    if (st === null || st === undefined) {
        return '<span class="contractor-meta-badge" style="border-color:rgba(148,163,184,0.35);color:#64748b"'
            + ' title="Never probed. Unknown is not the same as fast.">UNKNOWN</span>';
    }
    var meta = CONTRACTOR_HEALTH_META[st];
    if (!meta) meta = { label: String(st).toUpperCase(), color: '#94a3b8', title: '' };
    var ms = p.health_latency_ms;
    var suffix = (ms !== null && ms !== undefined) ? ' · ' + ms + 'ms' : '';
    var title = meta.title || ('Last probe: ' + st);
    if (p.health_observed_model) title += ' · served ' + p.health_observed_model;
    return '<span class="contractor-meta-badge" style="border-color:' + meta.color + '55;color:' + meta.color + '"'
        + ' title="' + escapeHtml(title) + '">' + meta.label + suffix + '</span>';
}

// Force one probe now, ignoring the backoff window. Synchronous on purpose: the operator is
// watching a button and wants an answer in this click, not a poll loop. One probe is bounded
// by its own timeout, so this is not the long-inference case the 202+poll rule is about.
async function probeProviderNow(key, btn) {
    var original = btn ? btn.innerHTML : null;
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader-2" style="width:12px;height:12px"></i>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    try {
        var res = await fetch('/tools/department-hq/api/providers/' + encodeURIComponent(key) + '/probe', {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        var data = await res.json();
        if (!res.ok || data.success === false) {
            showToast((data.error || 'Probe failed') + ' — ' + key, 'error');
        } else {
            var st = (data.result && data.result.status) || 'unknown';
            showToast(key + ': ' + st, st === 'ok' ? 'success' : 'warning');
        }
        loadContractors();
    } catch (e) {
        showToast('Probe request failed: ' + key, 'error');
    } finally {
        // loadContractors() re-renders the row, so this button is usually already gone. Restore
        // anyway for the failure path where the re-render may not have happened.
        if (btn && document.body.contains(btn)) {
            btn.disabled = false;
            btn.innerHTML = original;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
}

// The second switch. Separate from toggleProvider because `is_active` means configured
// and `dispatchable` means "route here" — a provider can be set up, holding a key and
// passing its probe, while still receiving nothing.
async function toggleDispatchable(key) {
    try {
        var res = await fetch('/tools/department-hq/api/providers/' + key + '/dispatchable', {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' }, body: '{}'
        });
        var data = await res.json();
        if (!res.ok || data.success === false) {
            showToast(data.error || 'Could not change routing switch', 'error');
        }
        loadContractors();
    } catch (e) {
        console.error('Toggle dispatchable failed:', e);
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
        // Strictly === true, not `!== false`. If the server ever omits the field, the
        // honest reading is "we were not told it is configured", and defaulting that to
        // enabled would show a green switch we cannot justify.
        var isEnabled = p.is_active === true;
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
        // DS9 PR 4 — what the probe measured, and what kind of provider this is.
        html += contractorHealthBadge(p);
        // The escape hatch from the backoff window. A `no_key` provider cannot become healthy
        // on a timer — only a person can fix it, by pasting a key. Without this button the
        // 120-minute window is the operator's only refresh, so fixing the config and reloading
        // shows the OLD `no_key` and reads as "the fix didn't work".
        // Key via data attribute, never spliced into the onclick JS (&#39; decodes back to ' first).
        html += '<button class="contractor-btn-probe" title="Probe now (ignore the backoff window)"'
            + ' data-provider-key="' + escapeHtml(p.provider_key) + '"'
            + ' onclick="event.stopPropagation();probeProviderNow(this.dataset.providerKey, this)">'
            + '<i data-lucide="refresh-cw" style="width:12px;height:12px"></i></button>';
        html += contractorClassBadge(p);
        html += '<div class="budget-bar"><div class="budget-fill ' + budgetFillClass + '" style="width:' + budgetPct.toFixed(0) + '%"></div></div>';
        html += '<div class="contractor-firm-actions">';
        html += '<button class="contractor-btn-edit" onclick="event.stopPropagation();editProvider(\'' + providerKey + '\')">Edit</button>';
        var _disp = p.dispatchable === true;
        // DS9 PR 4 — the second switch. `is_active` says CONFIGURED; this says
        // "route here". A provider can hold a key and pass its probe while still
        // receiving nothing, and that state has to be expressible.
        //
        // Both switches now carry their state as a CLASS, not only as text. Two buttons on
        // one row both reading "OFF"/"Disable" with identical grey styling is genuinely
        // unreadable — you cannot tell which switch you are about to throw, and on a paid
        // provider the difference is the difference between spending money and not.
        // `.on` / `.off` follow the convention already in fleet.css (.fleet-prov-toggle.active
        // is green, :not(.active) is grey) so the Fleet and Contractors tabs look identical.
        // aria-pressed carries the same state to a screen reader.
        html += '<button class="contractor-btn-toggle contractor-routing-toggle ' + (_disp ? 'on' : 'off')
            + '" aria-pressed="' + _disp + '" title="'
            + (_disp ? 'Routing is ON — the dispatcher may send work here.'
                     : 'Routing is OFF — configured, but nothing is dispatched here.')
            + '" onclick="event.stopPropagation();toggleDispatchable(\'' + providerKey + '\')">'
            + (_disp ? 'ROUTING ON' : 'ROUTING OFF') + '</button>';
        html += '<button class="contractor-btn-toggle contractor-active-toggle ' + (isEnabled ? 'on' : 'off')
            + '" aria-pressed="' + isEnabled + '" title="'
            + (isEnabled ? 'Configured — this contractor is set up. Click to disable it.'
                         : 'Not configured — clicks enable it.')
            + '" onclick="event.stopPropagation();toggleProvider(\'' + providerKey + '\')">'
            + (isEnabled ? 'Disable' : 'Enable') + '</button>';
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
});

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
    if (!panel) return;
    if (badge) badge.textContent = '';  // cleared — no WTF-specific backlog metric here

    try {
        var resp = await fetch('/tools/department-hq/api/fleet/wtf-status');
        var data = await resp.json();
        if (!data.success) { panel.textContent = 'Error loading agent status'; return; }

        if (!data.agents || !data.agents.length) {
            panel.textContent = 'No dispatches in last 2h — fleet may be idle.';
            return;
        }

        panel.innerHTML = data.agents.map(function(a) {
            var staleColor = a.node_stale ? '#f59e0b' : '#00ffff';
            var failback   = a.node_stale ? ' <span style="color:#f59e0b;font-size:0.65rem;">→ failback</span>' : '';
            // Cold-load warning: avg > 60s means model is cold-loading or overloaded
            var coldWarn   = a.avg_sec > 60 && a.avg_sec < 600
                ? ' <span style="color:#f59e0b;font-size:0.6rem;" title="Slow response — model may be cold-loading">⏳</span>' : '';
            var very_slow  = a.avg_sec >= 600
                ? ' <span style="color:#ef4444;font-size:0.6rem;" title="Cold-loading from disk (>10 min avg)">🔴</span>' : '';
            var avgColor   = a.avg_sec >= 600 ? '#ef4444' : (a.avg_sec > 60 ? '#f59e0b' : 'var(--dhq-text-dim)');
            return '<div style="display:flex;align-items:center;gap:10px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.06);">' +
                '<span style="width:7px;height:7px;border-radius:50%;background:' + staleColor + ';flex-shrink:0;"></span>' +
                '<span style="flex:1;font-weight:600;font-size:0.8rem;">' + _escWtf(a.name) + coldWarn + very_slow + '</span>' +
                '<span style="color:' + staleColor + ';font-size:0.7rem;">' + _escWtf(a.node) + failback + '</span>' +
                '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;color:var(--dhq-text-dim);">' +
                    _escWtf(a.calls_1h) + ' calls</span>' +
                '<span style="font-family:\'IBM Plex Mono\',monospace;font-size:0.68rem;color:' + avgColor + ';">' +
                    _escWtf(a.avg_sec) + 's avg</span>' +
                '<span style="font-size:0.6rem;color:var(--dhq-text-dim);">' + _escWtf(a.last_seen) + '</span>' +
                '</div>';
        }).join('');
    } catch (e) {
        panel.textContent = 'Failed to load agent status';
    }
}

async function loadClusterStats() {
    try {
        var resp = await fetch('/tools/department-hq/api/fleet/cluster-stats');
        var d = await resp.json();
        if (!d.success) return;

        // 1. Node Health Table
        var ht = document.getElementById('nodeHealthTable');
        if (ht && d.node_health && d.node_health.length) {
            var rows = d.node_health.map(function(n) {
                var tier = n.gpu ? '<span style="color:#a3e635;font-size:0.65rem;">GPU</span>' : '<span style="color:#94a3b8;font-size:0.65rem;">CPU</span>';
                var hbColor = n.stale ? '#f59e0b' : '#10b981';
                var hbAge = n.hb_age_s != null ? (n.hb_age_s < 60 ? n.hb_age_s + 's' : Math.round(n.hb_age_s/60) + 'm') : '?';
                var loadPct = n.max_conc > 0 ? Math.round(n.load / n.max_conc * 100) : 0;
                var loadColor = loadPct > 150 ? '#ef4444' : loadPct > 80 ? '#f59e0b' : '#10b981';
                // Models cell: "X avail · Y loaded". Available = on-disk, ready to
                // serve (live-reconciled). Loaded = warm in RAM now (0 when idle is
                // normal). Available colored red only when genuinely 0 (real problem).
                var avail = (n.models_available != null) ? n.models_available : 0;
                var availColor = avail > 0 ? '#e2e8f0' : '#ef4444';
                var modelsCell = '<span style="color:' + availColor + ';font-weight:600;">' + _escWtf(avail) + '</span>' +
                    '<span style="color:var(--dhq-text-dim);font-size:0.6rem;"> avail · ' + _escWtf(n.models) + ' loaded</span>';
                return '<tr style="border-bottom:1px solid rgba(255,255,255,0.04);">' +
                    '<td style="padding:3px 6px;font-weight:600;white-space:nowrap;">' + _escWtf(n.name) + '</td>' +
                    '<td style="padding:3px 6px;text-align:center;">' + tier + '</td>' +
                    '<td style="padding:3px 6px;color:var(--dhq-text-dim);text-align:right;">' + _escWtf(n.ram_gb.toFixed(0)) + 'GB</td>' +
                    '<td style="padding:3px 6px;text-align:right;white-space:nowrap;">' + modelsCell + '</td>' +
                    '<td style="padding:3px 6px;text-align:right;color:' + loadColor + ';">' + _escWtf(n.disp_5m) + '/5m</td>' +
                    '<td style="padding:3px 6px;text-align:right;color:' + hbColor + ';font-size:0.65rem;">' + _escWtf(hbAge) + '</td>' +
                    '</tr>';
            }).join('');
            ht.innerHTML = '<table style="width:100%;border-collapse:collapse;font-family:\'IBM Plex Mono\',monospace;">' +
                '<thead><tr style="color:rgba(0,220,170,0.5);font-size:0.6rem;letter-spacing:1px;">' +
                '<th style="padding:2px 6px;text-align:left;">NODE</th><th>TYPE</th><th style="text-align:right;">RAM</th>' +
                '<th style="text-align:right;">MODELS</th><th style="text-align:right;">RATE</th><th style="text-align:right;">HB</th>' +
                '</tr></thead><tbody>' + rows + '</tbody></table>';
        }

        // 2. Top Capabilities Bar
        var capEl = document.getElementById('topCapabilitiesBar');
        var totalEl = document.getElementById('totalDispatchBadge');
        if (capEl && d.top_capabilities && d.top_capabilities.length) {
            if (totalEl) totalEl.textContent = '(' + (d.total_dispatches || 0).toLocaleString() + ' dispatches/hr)';
            var maxCnt = d.top_capabilities[0].cnt || 1;
            capEl.innerHTML = d.top_capabilities.slice(0, 8).map(function(c) {
                var pct = Math.round(c.cnt / maxCnt * 100);
                var okColor = c.ok_rate > 0.95 ? '#10b981' : c.ok_rate > 0.8 ? '#f59e0b' : '#ef4444';
                return '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">' +
                    '<span style="width:110px;font-size:0.65rem;color:#e2e8f0;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + _escWtf(c.cap) + '">' + _escWtf(c.cap) + '</span>' +
                    '<div style="flex:1;background:rgba(0,220,170,0.08);border-radius:2px;height:10px;">' +
                    '<div style="width:' + pct + '%;height:100%;background:rgba(0,220,170,0.5);border-radius:2px;"></div></div>' +
                    '<span style="font-size:0.62rem;color:' + okColor + ';width:28px;text-align:right;">' + c.cnt + '</span>' +
                    '</div>';
            }).join('');
        }

        // 3. Module Source Breakdown
        var modEl = document.getElementById('moduleBreakdownBar');
        if (modEl && d.modules && d.modules.length) {
            var modMax = d.modules[0].cnt || 1;
            modEl.innerHTML = d.modules.slice(0, 6).map(function(m) {
                var pct = Math.round(m.cnt / modMax * 100);
                var srcShort = m.src.replace('wtf_dhq_', 'wtf.').replace('_backlog', '↩').replace('fleet_warmup', '🔥warmup');
                return '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">' +
                    '<span style="width:90px;font-size:0.62rem;color:#94a3b8;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="' + _escWtf(m.src) + '">' + _escWtf(srcShort) + '</span>' +
                    '<div style="flex:1;background:rgba(0,255,255,0.06);border-radius:2px;height:10px;">' +
                    '<div style="width:' + pct + '%;height:100%;background:rgba(0,255,255,0.35);border-radius:2px;"></div></div>' +
                    '<span style="font-size:0.62rem;color:var(--dhq-text-dim);width:28px;text-align:right;">' + m.cnt + '</span>' +
                    '</div>';
            }).join('');
        }

        // 4. Throughput Sparkline (SVG)
        var spkEl = document.getElementById('throughputSparkline');
        var spkPeak = document.getElementById('sparklinePeak');
        if (spkEl && d.sparkline && d.sparkline.length > 1) {
            var vals = d.sparkline.map(function(b) { return b.cnt; });
            var peak = Math.max.apply(null, vals);
            var minV = Math.min.apply(null, vals);
            if (spkPeak) spkPeak.textContent = 'peak ' + peak + '/2min';
            var W = 400, H = 40, pad = 2;
            var pts = vals.map(function(v, i) {
                var x = pad + (i / (vals.length - 1)) * (W - 2*pad);
                var y = H - pad - ((v - minV) / Math.max(peak - minV, 1)) * (H - 2*pad);
                return x.toFixed(1) + ',' + y.toFixed(1);
            }).join(' ');
            spkEl.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" style="width:100%;height:48px;">' +
                '<polyline points="' + pts + '" fill="none" stroke="rgba(0,220,170,0.7)" stroke-width="1.5" stroke-linejoin="round"/>' +
                '<polyline points="' + pad + ',' + H + ' ' + pts + ' ' + (W-pad) + ',' + H + '" fill="rgba(0,220,170,0.1)" stroke="none"/>' +
                '</svg>';
        }
    } catch (e) {
        console.warn('loadClusterStats error:', e);
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
