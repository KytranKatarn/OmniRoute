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
                    html += '<div class="dhq-org-director">'
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
                        html += '<div class="dhq-org-agent">'
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

        document.getElementById('rosterCount').textContent = data.total + ' agents';

        if (data.agents.length === 0) {
            setHtml(el, '<div class="dhq-empty">No agents match filters.</div>');
            return;
        }

        var html = '<table class="dhq-roster-table">'
            + '<thead><tr>'
            + '<th>Agent</th><th>Department</th><th>Floor</th><th>Shift</th><th>Role</th><th>Actions</th>'
            + '</tr></thead><tbody>';

        for (var i = 0; i < data.agents.length; i++) {
            var a = data.agents[i];
            var color = floorColor(a.floor);
            html += '<tr>'
                + '<td><div style="font-weight:600">' + esc(a.display_name || a.name) + '</div>'
                + '<div style="font-size:0.7rem;color:var(--dhq-text-dim)">' + esc(a.name) + '</div></td>'
                + '<td style="color:' + color + '">' + esc(a.department) + '</td>'
                + '<td>' + esc(a.floor) + '</td>'
                + '<td>' + shiftBadge(a.shift_state) + '</td>'
                + '<td>' + (a.is_department_ai ? '<span class="dhq-role-director">DIRECTOR</span>' : 'Staff') + '</td>'
                + '<td><button class="dhq-action-btn" onclick="toggleShift(' + a.id + ',\'' + esc(a.shift_state) + '\')">Shift</button></td>'
                + '</tr>';
        }
        html += '</tbody></table>';
        setHtml(el, html);
    } catch (err) {
        setHtml(el, '<div class="dhq-empty">Error loading roster: ' + esc(err.message) + '</div>');
    }
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
// Init
// ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
    loadOverview();
});
