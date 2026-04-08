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
        const d = new Date(iso);
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
    document.querySelectorAll('.dhq-tab').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.querySelectorAll('.dhq-panel').forEach(function(p) {
        p.classList.toggle('active', p.id === 'panel-' + tab);
    });
    var loaders = {
        'overview':     loadOverview,
        'org-chart':    loadOrgChart,
        'roster':       loadRoster,
        'work':         loadWorkSessions,
        'performance':  loadPerformance,
        'creed':        loadCreed,
        'social':       loadSocialFeed,
        'devices':      loadDevices,
        'dispatch':     loadDispatch,
    };
    if (!loaded[tab] && loaders[tab]) {
        loaders[tab]();
    }
}

// ───────────────────────────────────────────────────────────────
// Overview
// ───────────────────────────────────────────────────────────────

async function loadOverview() {
    var el = document.getElementById('overviewContent');
    try {
        var data = await api('/api/overview');
        loaded['overview'] = true;

        document.getElementById('statDepts').textContent = data.totals.departments;
        document.getElementById('statAgents').textContent = data.totals.agents;
        document.getElementById('statActive').textContent = data.totals.active;

        populateDeptFilters(data.floors);

        var html = '';
        for (var fi = 0; fi < FLOOR_ORDER.length; fi++) {
            var fl = FLOOR_ORDER[fi];
            var floor = data.floors[fl];
            if (!floor) continue;
            var color = floorColor(fl);

            html += '<div class="dhq-floor-section">'
                + '<div class="dhq-floor-header" data-floor="' + esc(fl) + '">'
                + '<span class="dhq-floor-name" style="color:' + color + '">' + esc(fl) + '</span>'
                + '<span class="dhq-floor-badge">' + floor.total_agents + ' agents</span>'
                + '<span class="dhq-floor-badge">' + floor.active_agents + ' active</span>'
                + '</div>'
                + '<div class="dhq-dept-grid">';

            for (var di = 0; di < floor.departments.length; di++) {
                var dept = floor.departments[di];
                html += '<div class="dhq-dept-card" style="--card-accent:' + color + '">'
                    + '<div class="dhq-dept-name">' + esc(dept.department) + '</div>'
                    + '<div class="dhq-dept-stats">'
                    + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Total</span><span class="dhq-dept-stat-val">' + dept.total_agents + '</span></div>'
                    + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Active</span><span class="dhq-dept-stat-val">' + dept.active + '</span></div>'
                    + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Sessions</span><span class="dhq-dept-stat-val">' + dept.active_sessions + '</span></div>'
                    + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Jobs 24h</span><span class="dhq-dept-stat-val">' + dept.jobs_24h + '</span></div>'
                    + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Completed</span><span class="dhq-dept-stat-val">' + dept.completed_24h + '</span></div>'
                    + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Failed</span><span class="dhq-dept-stat-val">' + dept.failed_24h + '</span></div>'
                    + '</div>'
                    + (dept.directors > 0 ? '<span class="dhq-director-tag">AI Director</span>' : '')
                    + '</div>';
            }
            html += '</div></div>';
        }

        // Unknown floors
        var floorKeys = Object.keys(data.floors);
        for (var ki = 0; ki < floorKeys.length; ki++) {
            var fk = floorKeys[ki];
            if (FLOOR_ORDER.indexOf(fk) === -1) {
                var uf = data.floors[fk];
                html += '<div class="dhq-floor-section">'
                    + '<div class="dhq-floor-header"><span class="dhq-floor-name">' + esc(fk) + '</span>'
                    + '<span class="dhq-floor-badge">' + uf.total_agents + ' agents</span></div>'
                    + '<div class="dhq-dept-grid">';
                for (var ui = 0; ui < uf.departments.length; ui++) {
                    var ud = uf.departments[ui];
                    html += '<div class="dhq-dept-card"><div class="dhq-dept-name">' + esc(ud.department) + '</div>'
                        + '<div class="dhq-dept-stats">'
                        + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Total</span><span class="dhq-dept-stat-val">' + ud.total_agents + '</span></div>'
                        + '<div class="dhq-dept-stat"><span class="dhq-dept-stat-label">Active</span><span class="dhq-dept-stat-val">' + ud.active + '</span></div>'
                        + '</div></div>';
                }
                html += '</div></div>';
            }
        }

        setHtml(el, html || '<div class="dhq-empty">No department data found.</div>');
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading overview: ' + esc(err.message) + '</div>');
    }
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
                    html += '<div class="dhq-org-director dhq-clickable" onclick="openAgentDetail(' + d.id + ')">'
                        + '<div class="dhq-org-director-icon">AI</div>'
                        + '<div>'
                        + '<div class="dhq-org-director-name">' + esc(d.display_name || d.name) + '</div>'
                        + '<div class="dhq-org-director-code">' + esc(d.name) + ' ' + shiftBadge(d.shift_state) + '</div>'
                        + '</div></div>';
                }

                if (dept.staff.length > 0) {
                    html += '<div class="dhq-org-staff-grid">';
                    for (var si = 0; si < dept.staff.length; si++) {
                        var a = dept.staff[si];
                        html += '<div class="dhq-org-agent dhq-clickable" onclick="openAgentDetail(' + a.id + ')">'
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
    } else {
        renderRosterCards(data, el);
    }
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
            + '<td><div style="font-weight:600">' + esc(a.display_name || a.name) + '</div>'
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

            html += '<div class="dhq-crew-card" onclick="openAgentDetail(' + a.id + ')" style="--card-accent:' + color + '">'
                + '<div class="dhq-crew-card-top">'
                + '<div class="dhq-crew-avatar" style="border-color:' + color + '">'
                + '<span>' + esc(initials) + '</span>'
                + '</div>'
                + '<div class="dhq-crew-card-info">'
                + '<div class="dhq-crew-card-name">' + esc(a.display_name || a.name) + '</div>'
                + '<div class="dhq-crew-card-code">' + esc(a.name) + '</div>'
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
// Work Sessions
// ───────────────────────────────────────────────────────────────

async function loadWorkSessions() {
    var el = document.getElementById('workContent');
    var dept = document.getElementById('workDept').value;
    var status = document.getElementById('workStatus').value;

    var params = new URLSearchParams();
    if (dept) params.set('department', dept);
    if (status) params.set('status', status);

    try {
        var data = await api('/api/work-sessions?' + params.toString());
        loaded['work'] = true;

        if (data.sessions.length === 0) {
            setHtml(el, '<div class="dhq-empty">No work sessions found.</div>');
            return;
        }

        var html = '<div class="dhq-session-list">';
        for (var i = 0; i < data.sessions.length; i++) {
            var s = data.sessions[i];
            html += '<div class="dhq-session-card">'
                + '<div>'
                + '<div class="dhq-session-title">' + esc(s.title || s.session_type || 'Untitled') + '</div>'
                + '<div class="dhq-session-agent">' + esc(s.agent_display_name || s.agent_name || '\u2014') + ' &middot; ' + esc(s.department) + '</div>'
                + '</div>'
                + '<div class="dhq-session-status dhq-status-' + esc(s.status) + '">' + esc(s.status).toUpperCase() + '</div>'
                + '<div><div style="font-size:0.7rem;color:var(--dhq-text-dim)">Jobs</div><div>' + (s.jobs_completed || 0) + ' done / ' + (s.jobs_failed || 0) + ' fail</div></div>'
                + '<div><div style="font-size:0.7rem;color:var(--dhq-text-dim)">Started</div><div>' + fmtTime(s.started_at) + '</div></div>'
                + '</div>';
        }
        html += '</div>';
        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading work sessions: ' + esc(err.message) + '</div>');
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
            html += '<div class="dhq-perf-card" style="--card-accent:' + floorColor(m.floor || '') + '">'
                + '<div class="dhq-perf-dept">' + esc(m.department) + '</div>'
                + '<div class="dhq-perf-metrics">'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.live_jobs_7d || m.jobs_completed || 0) + '</span><span class="dhq-perf-metric-label">Jobs (7d)</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.live_completed_7d || m.jobs_completed || 0) + '</span><span class="dhq-perf-metric-label">Completed</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.live_failed_7d || m.jobs_failed || 0) + '</span><span class="dhq-perf-metric-label">Failed</span></div>'
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
        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading C.R.E.E.D.: ' + esc(err.message) + '</div>');
    }
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
            + (a.avatar_url ? '<img src="' + esc(a.avatar_url) + '" alt="avatar">' : '<div class="dhq-ad-avatar-placeholder">&#x1F916;</div>')
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
            + '</div>'
            + '<div id="portrait-prompt-preview" class="dhq-ad-prompt" style="min-height:2rem"></div>'
            + '<div id="portraitGallery" class="dhq-portrait-grid"></div>'
            + '<div class="dhq-portrait-note" style="color:#8b8b8b;font-size:0.75rem;margin-top:0.5rem">'
            + 'ComfyUI portrait generation coming soon (pending disk space cleanup).'
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

async function loadSocialFeed() {
    var el = document.getElementById('socialFeedContent');
    if (!el) return;
    try {
        var feedResp = await api('/api/social/feed?limit=30');
        var statsResp = await api('/api/social/stats');
        loaded['social'] = true;

        var stats = statsResp;
        var posts = feedResp.posts || [];

        var html = '<div class="dhq-social-stats-bar">'
            + '<span class="dhq-stat"><span class="dhq-stat-val">' + stats.agents_with_profiles + '</span> Agents with Profiles</span>'
            + '<span class="dhq-stat"><span class="dhq-stat-val">' + stats.total_profiles + '</span> Profiles</span>'
            + '<span class="dhq-stat"><span class="dhq-stat-val">' + stats.platforms_used + '</span> Platforms</span>'
            + '<span class="dhq-stat"><span class="dhq-stat-val">' + stats.posts_this_week + '</span> Posts (7d)</span>'
            + '<span class="dhq-stat"><span class="dhq-stat-val">' + stats.total_published + '</span> Published</span>'
            + '</div>';

        if (posts.length === 0) {
            html += '<div class="dhq-empty">No posts yet. Open an agent profile and generate content.</div>';
        } else {
            html += '<div class="dhq-social-feed">';
            for (var i = 0; i < posts.length; i++) {
                var p = posts[i];
                html += '<div class="dhq-social-feed-card">'
                    + '<div class="dhq-social-feed-header">'
                    + '<span class="dhq-social-feed-author dhq-clickable" onclick="openAgentDetail(' + p.agent_id + ')">'
                    + esc(p.display_name || p.name) + '</span>'
                    + '<span class="dhq-social-feed-dept">' + esc(p.department) + '</span>'
                    + '<span class="dhq-social-post-status dhq-status-' + esc(p.status) + '">' + esc(p.status) + '</span>'
                    + '</div>'
                    + '<div class="dhq-social-feed-body">' + esc(p.content) + '</div>'
                    + '<div class="dhq-social-feed-footer">'
                    + (p.platform ? esc(p.platform) + ' &middot; ' : '')
                    + fmtTime(p.created_at)
                    + '</div></div>';
            }
            html += '</div>';
        }

        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading social feed: ' + esc(err.message) + '</div>');
    }
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
    var d = new Date(ts);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

async function loadDevices() {
    var el = document.getElementById('devicesContent');
    var countEl = document.getElementById('deviceCount');
    try {
        var statusFilter = document.getElementById('deviceStatusFilter').value;
        var url = '/api/auth/devices';
        if (statusFilter) url += '?status=' + statusFilter;
        var devices = await api(url);
        loaded['devices'] = true;

        if (countEl) countEl.textContent = devices.length + ' device' + (devices.length !== 1 ? 's' : '');

        if (!devices.length) {
            setHtml(el, '<div class="dhq-empty">No devices found</div>');
            return;
        }

        var html = '<div class="dhq-devices-grid">';
        for (var i = 0; i < devices.length; i++) {
            var d = devices[i];
            var statusColor = DEVICE_STATUS_COLORS[d.status] || '#6b7280';
            var typeLabel = DEVICE_TYPE_LABELS[d.device_type] || d.device_type;
            html += '<div class="dhq-device-card">'
                + '<div class="dhq-device-header">'
                + '<span class="dhq-device-name">' + esc(d.device_name) + '</span>'
                + '<span class="dhq-device-badge" style="background:' + statusColor + '">' + esc(d.status.toUpperCase()) + '</span>'
                + '</div>'
                + '<div class="dhq-device-info">'
                + '<div><span class="dhq-device-label">Type:</span> ' + esc(typeLabel) + '</div>'
                + '<div><span class="dhq-device-label">Hostname:</span> ' + esc(d.hostname || '—') + '</div>'
                + '<div><span class="dhq-device-label">Purpose:</span> ' + esc(d.purpose || '—') + '</div>'
                + '<div><span class="dhq-device-label">Registered:</span> ' + formatDeviceTime(d.registered_at) + '</div>'
                + '<div><span class="dhq-device-label">Last Seen:</span> ' + formatDeviceTime(d.last_seen) + '</div>'
                + '<div><span class="dhq-device-label">Requests:</span> ' + (d.request_count || 0) + '</div>'
                + '</div>'
                + '<div class="dhq-device-actions">';

            if (d.status === 'pending') {
                html += '<button class="dhq-btn dhq-btn-approve" onclick="approveDevice(' + d.id + ')">Approve</button>'
                    + '<button class="dhq-btn dhq-btn-deny" onclick="denyDevice(' + d.id + ')">Deny</button>';
            } else if (d.status === 'approved') {
                html += '<button class="dhq-btn dhq-btn-revoke" onclick="revokeDevice(' + d.id + ')">Revoke</button>';
            }

            html += '</div></div>';
        }
        html += '</div>';
        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading devices: ' + esc(err.message) + '</div>');
    }
}

async function approveDevice(deviceId) {
    try {
        var resp = await fetch(DHQ_BASE + '/api/auth/approve/' + deviceId, {method: 'POST'});
        var data = await resp.json();
        if (data.api_key) {
            // Show in a prompt so user can copy — alert may truncate
            prompt('API Key (copy this — shown once only):', data.api_key);
        }
        loadDevices();
    } catch (err) {
        alert('Error approving device: ' + err.message);
    }
}

async function denyDevice(deviceId) {
    if (!confirm('Deny this device registration?')) return;
    try {
        await fetch(DHQ_BASE + '/api/auth/deny/' + deviceId, {method: 'POST'});
        loadDevices();
    } catch (err) {
        alert('Error denying device: ' + err.message);
    }
}

async function revokeDevice(deviceId) {
    if (!confirm('Revoke this device? It will lose all access immediately.')) return;
    try {
        await fetch(DHQ_BASE + '/api/auth/revoke/' + deviceId, {method: 'POST'});
        loadDevices();
    } catch (err) {
        alert('Error revoking device: ' + err.message);
    }
}

// ───────────────────────────────────────────────────────────────
// Dispatch & Orchestration
// ───────────────────────────────────────────────────────────────

async function loadDispatch() {
    loaded['dispatch'] = true;
    try {
        var data = await api('/api/dispatch/overview');
        renderOllamaHud(data.ollama || {});
        renderActiveJobs(data.active_jobs || []);
        renderWorkloadGrid(data.workload_grid || []);
        renderDispatchMetrics(data.dispatch_metrics || {});
        renderLoopJobs(data.loop_jobs || []);
    } catch (err) {
        var msg = '<div class="dhq-empty">Error loading dispatch data: ' + esc(err.message) + '</div>';
        ['dispatchJobsContent','dispatchWorkloadContent',
         'dispatchMetricsContent','dispatchLoopContent'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) setHtml(el, msg);
        });
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
    var el = document.getElementById('dispatchJobsContent');
    var countEl = document.getElementById('dispatchJobCount');
    var running = jobs.filter(function(j) { return j.status === 'running' || j.status === 'pending'; });
    if (countEl) countEl.textContent = '(' + running.length + ' active)';
    if (!jobs.length) {
        setHtml(el, '<div class="dhq-empty">No active bridge jobs</div>');
        return;
    }
    var html = '';
    jobs.forEach(function(j) {
        var pct = j.progress_pct || 0;
        var statusCls = 'dhq-status-' + (j.status || 'pending');
        html += '<div class="dhq-job-row">'
            + '<div><span class="dhq-status-badge ' + statusCls + '">' + esc(j.status) + '</span> '
            + esc(j.description || j.job_type) + '</div>'
            + '<div style="color:var(--dhq-accent)">' + esc(j.agent_name || 'unassigned') + '</div>'
            + '<div class="dhq-progress-row"><div class="dhq-progress-wrap">'
            + '<div class="dhq-progress-fill" style="width:' + pct + '%"></div></div>'
            + '<span style="font-size:0.7rem;color:var(--dhq-text-dim)">' + pct + '%</span></div>'
            + '<div style="color:var(--dhq-text-dim);font-size:0.7rem">' + esc(j.station_code || '') + '</div>'
            + '</div>';
    });
    setHtml(el, html);
}

function renderWorkloadGrid(rows) {
    var el = document.getElementById('dispatchWorkloadContent');
    if (!rows.length) {
        setHtml(el, '<div class="dhq-empty">No workload data</div>');
        return;
    }
    var html = '<div class="dhq-workload-grid">';
    rows.forEach(function(r) {
        var color = floorColor(r.floor);
        var busy = r.active + r.deployed;
        var idle = r.barracked;
        html += '<div class="dhq-workload-card" style="border-left-color:' + color + '">'
            + '<div class="dhq-workload-dept" style="color:' + color + '">' + esc(r.department) + '</div>'
            + '<div class="dhq-workload-counts">'
            + '<span style="color:#10B981">' + busy + ' busy</span>'
            + '<span>' + idle + ' idle</span>'
            + (r.cooldown ? '<span style="color:#FFAA00">' + r.cooldown + ' cooldown</span>' : '')
            + '<span style="color:var(--dhq-text-dim)">' + r.total + ' total</span>'
            + '</div></div>';
    });
    html += '</div>';
    setHtml(el, html);
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
        + '<th>NEXT RUN</th><th>OK</th><th>ERR</th>'
        + '</tr></thead><tbody>';
    jobs.forEach(function(j) {
        var statusCls = !j.enabled ? 'dhq-loop-off'
            : j.err_24h > 0 ? 'dhq-loop-err' : 'dhq-loop-ok';
        var statusLabel = !j.enabled ? 'DISABLED'
            : j.err_24h > 0 ? 'ERRORS' : 'OK';
        html += '<tr>'
            + '<td>' + esc(j.name) + '</td>'
            + '<td>' + esc(j.department || '\u2014') + '</td>'
            + '<td class="' + statusCls + '">' + statusLabel + '</td>'
            + '<td style="color:var(--dhq-text-dim)">' + fmtTime(j.next_run) + '</td>'
            + '<td class="dhq-loop-ok">' + (j.ok_24h || 0) + '</td>'
            + '<td class="' + (j.err_24h > 0 ? 'dhq-loop-err' : '') + '">' + (j.err_24h || 0) + '</td>'
            + '</tr>';
    });
    html += '</tbody></table>';
    setHtml(el, html);
}

// ───────────────────────────────────────────────────────────────
// Init
// ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    loadOverview();
});
