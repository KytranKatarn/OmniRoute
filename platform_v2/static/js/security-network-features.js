/**
 * security-network-features.js
 * Powers all 15 new features: Topology, Supervision, Intel, Speed Test, etc.
 * Loaded after security-network-app.js which defines SN_API.
 */

/* ─── Helpers ─── */
function fmtBytes(b) {
    if (!b || b === 0) return '0 B';
    const u = ['B','KB','MB','GB','TB'];
    const i = Math.floor(Math.log(Math.abs(b)) / Math.log(1024));
    return (b / Math.pow(1024, i)).toFixed(1) + ' ' + u[Math.min(i, 4)];
}

function fmtNum(n) { return (n || 0).toLocaleString(); }

function sevColor(s) {
    return {critical:'#ef4444',high:'#f59e0b',medium:'#fbbf24',normal:'#6b7280',low:'#6b7280'}[s] || '#6b7280';
}
function sevBadge(s) {
    return `<span class="badge" style="background:${sevColor(s)};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.7rem">${s}</span>`;
}

const CAT_COLORS = {
    streaming:'#ef4444', social:'#e879f9', gaming:'#fbbf24', work:'#22d3ee',
    shopping:'#f97316', cloud:'#818cf8', education:'#10b981', news:'#6b7280',
    adult:'#dc2626', other:'#4b5563'
};
const CAT_ICONS = {
    streaming:'🎬', social:'🧠', gaming:'🎮', shopping:'🛒', work:'💼',
    cloud:'☁️', education:'📚', news:'📰', adult:'🔞', other:'📦'
};

/* ─── Chart instances (for cleanup) ─── */
let _sinkholeChart = null, _speedChart = null, _trafficClassChart = null;

/* ═══════════════════════════════════════════════════════════════════
   1. TOPOLOGY MAP (D3.js)
   ═══════════════════════════════════════════════════════════════════ */
function loadTopology() {
    // Stats
    fetch(SN_API + '/topology/stats').then(r=>r.json()).then(d => {
        if (!d.success) return;
        const s = d.stats || d;
        document.getElementById('topo-device-count').textContent = s.total_devices || s.device_count || '--';
        document.getElementById('topo-bandwidth').textContent = fmtBytes(s.total_bandwidth || s.total_bytes || 0);
        var tt = s.top_talker;
        document.getElementById('topo-top-talker').textContent = (tt && typeof tt === 'object') ? (tt.label || tt.name || tt.ip || JSON.stringify(tt)) : (tt || '--');
    }).catch(()=>{});

    // Graph
    fetch(SN_API + '/topology/graph').then(r=>r.json()).then(d => {
        if (!d.success) return;
        const g = d.graph || d;
        renderTopologyGraph(g.nodes || [], g.links || []);
    }).catch(e => console.error('Topology load error:', e));
}

function renderTopologyGraph(nodes, links) {
    const svg = d3.select('#topo-svg');
    svg.selectAll('*').remove();
    const container = document.getElementById('topology-graph');
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    svg.attr('viewBox', `0 0 ${w} ${h}`);

    const typeColor = {gateway:'#ef4444', hub:'#00e5ff', access_point:'#fbbf24', router:'#ef4444',
        phone:'#10b981', computer:'#8b5cf6', desktop:'#8b5cf6', laptop:'#8b5cf6', tablet:'#a78bfa',
        smart_tv:'#f472b6', camera:'#f59e0b', server:'#00e5ff', cloud:'#818cf8', outpost:'#f97316',
        starship:'#22d3ee'};

    const sizeScale = d3.scaleSqrt().domain([0, d3.max(nodes, n=>n.bytes_total||1)]).range([6, 30]);

    const sim = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(n=>n.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(w/2, h/2))
        .force('collision', d3.forceCollide().radius(n => sizeScale(n.bytes_total||0) + 5));

    const WIFI_AP = '192.168.1.251', INET = 'INTERNET';
    function linkType(l) {
        const s = l.source.id || l.source, t = l.target.id || l.target;
        if (s === INET || t === INET) return 'wan';
        if (s === WIFI_AP || t === WIFI_AP) return 'wifi';
        return 'wired';
    }
    const linkStyles = {wan: {color:'#818cf8', width:2, dash:'6,4'}, wifi: {color:'#fbbf24', width:1.5, dash:'4,3'}, wired: {color:'#00e5ff', width:2.5, dash:'none'}};
    const link = svg.append('g').selectAll('line').data(links).join('line')
        .attr('stroke', l => linkStyles[linkType(l)].color)
        .attr('stroke-width', l => linkStyles[linkType(l)].width)
        .attr('stroke-opacity', 0.5)
        .attr('stroke-dasharray', l => linkStyles[linkType(l)].dash);

    const node = svg.append('g').selectAll('g').data(nodes).join('g')
        .call(d3.drag().on('start', dragStart).on('drag', dragging).on('end', dragEnd));

    node.append('circle')
        .attr('r', n => sizeScale(n.bytes_total || 0))
        .attr('fill', n => n.is_gateway ? '#ef4444' : n.is_hub ? '#00e5ff' : typeColor[n.type] || '#6b7280')
        .attr('stroke', '#1e293b').attr('stroke-width', 2)
        .style('cursor', 'pointer')
        .on('click', (e, n) => { if (typeof openDeviceDetail === 'function') openDeviceDetail(n.id); });

    node.append('text')
        .text(n => n.label || n.id)
        .attr('dy', n => sizeScale(n.bytes_total||0) + 14)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8').attr('font-size', '10px');

    sim.on('tick', () => {
        link.attr('x1',l=>l.source.x).attr('y1',l=>l.source.y).attr('x2',l=>l.target.x).attr('y2',l=>l.target.y);
        node.attr('transform', n => `translate(${n.x},${n.y})`);
    });

    function dragStart(e,n) { if(!e.active) sim.alphaTarget(0.3).restart(); n.fx=n.x; n.fy=n.y; }
    function dragging(e,n) { n.fx=e.x; n.fy=e.y; }
    function dragEnd(e,n) { if(!e.active) sim.alphaTarget(0); n.fx=null; n.fy=null; }
}

/* ═══════════════════════════════════════════════════════════════════
   1b. DNS STATS DASHBOARD
   ═══════════════════════════════════════════════════════════════════ */
function _escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function _renderDnsListItem(label, count, color) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.05)';
    const nameSpan = document.createElement('span');
    nameSpan.style.color = color;
    nameSpan.textContent = label;
    const countSpan = document.createElement('span');
    countSpan.style.color = 'var(--archie-text-muted)';
    countSpan.textContent = count.toLocaleString();
    row.appendChild(nameSpan);
    row.appendChild(countSpan);
    return row;
}

function loadDnsStats() {
    fetch(SN_API + '/reports/dns-stats').then(r=>r.json()).then(d => {
        if (!d.success) return;
        const s = d.stats;
        document.getElementById('dns-total').textContent = (s.total_queries||0).toLocaleString();
        document.getElementById('rpt-dns-blocked').textContent = (s.blocked||0).toLocaleString();
        document.getElementById('dns-rate').textContent = (s.block_rate_pct||0) + '%';
        document.getElementById('dns-latency').textContent = (s.avg_processing_ms||0) + 'ms';

        // Top blocked domains
        const blockedEl = document.getElementById('rpt-dns-top-blocked');
        blockedEl.textContent = '';
        if (s.top_blocked && s.top_blocked.length) {
            s.top_blocked.slice(0,5).forEach(b => blockedEl.appendChild(_renderDnsListItem(b.domain, b.count, '#ef4444')));
        } else { blockedEl.textContent = 'None'; }

        // Top clients
        const clientsEl = document.getElementById('dns-top-clients');
        clientsEl.textContent = '';
        if (s.top_clients && s.top_clients.length) {
            s.top_clients.slice(0,5).forEach(c => clientsEl.appendChild(_renderDnsListItem(c.label, c.count, '#00e5ff')));
        } else { clientsEl.textContent = 'None'; }

        // 24h trend chart
        _renderDnsTrendChart(s.hourly_queries || [], s.hourly_blocked || []);
    }).catch(e => console.error('DNS stats error:', e));
}

function _renderDnsTrendChart(queries, blocked) {
    const container = document.getElementById('dns-trend-chart');
    if (!container || !queries.length) return;
    const svg = d3.select('#dns-trend-chart').selectAll('*').remove();
    const svgEl = d3.select('#dns-trend-chart').append('svg')
        .attr('width', '100%').attr('height', '100%')
        .attr('viewBox', '0 0 ' + (container.clientWidth || 600) + ' 120');
    const w = container.clientWidth || 600, h = 110, pad = 2;
    const barW = Math.max(2, (w - queries.length * pad) / queries.length);
    const maxQ = d3.max(queries) || 1;

    svgEl.selectAll('.q-bar').data(queries).join('rect')
        .attr('x', function(d,i) { return i * (barW + pad); })
        .attr('y', function(d) { return h - (d / maxQ) * h; })
        .attr('width', barW).attr('height', function(d) { return (d / maxQ) * h; })
        .attr('fill', '#00e5ff').attr('opacity', 0.3);

    svgEl.selectAll('.b-bar').data(blocked).join('rect')
        .attr('x', function(d,i) { return i * (barW + pad); })
        .attr('y', function(d) { return h - (d / maxQ) * h; })
        .attr('width', barW).attr('height', function(d) { return (d / maxQ) * h; })
        .attr('fill', '#ef4444').attr('opacity', 0.7);
}

/* ═══════════════════════════════════════════════════════════════════
   2. SUPERVISION CONTROLS
   ═══════════════════════════════════════════════════════════════════ */
function loadSupervisionSchedules() {
    const el = document.getElementById('supervision-schedules');
    el.innerHTML = '<div class="loading-state"><span class="spinner"></span> Loading...</div>';
    fetch(SN_API + '/supervision/schedules').then(r=>r.json()).then(d => {
        if (!d.success || !d.schedules || d.schedules.length === 0) {
            el.innerHTML = '<div class="empty-state">No supervision schedules configured. Click "Add Schedule" to create one.</div>';
            return;
        }
        let html = '<table class="data-table"><thead><tr><th>User/Device</th><th>Weekday Block</th><th>Weekend Block</th><th>Categories</th><th>Status</th><th>Actions</th></tr></thead><tbody>';
        d.schedules.forEach(s => {
            const sched = s.schedule || {};
            const wd = sched.weekday ? `${sched.weekday.start||'?'} - ${sched.weekday.end||'?'}` : 'None';
            const we = sched.weekend ? `${sched.weekend.start||'?'} - ${sched.weekend.end||'?'}` : 'None';
            const cats = (s.blocked_categories || []).map(c => `<span style="background:${CAT_COLORS[c]||'#555'};color:#fff;padding:1px 6px;border-radius:3px;font-size:0.7rem;margin:1px">${c}</span>`).join(' ');
            const status = s.enabled ? '<span style="color:#22c55e">Active</span>' : '<span style="color:#6b7280">Disabled</span>';
            html += `<tr>
                <td><strong>${s.user_name||'Unknown'}</strong><br><span style="font-size:0.7rem;color:#888">${s.device_mac||''}</span></td>
                <td>${wd}</td><td>${we}</td><td>${cats||'None'}</td><td>${status}</td>
                <td><button class="btn btn-sm" onclick="deleteSchedule(${s.id})" style="color:#ef4444">Delete</button></td>
            </tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    }).catch(() => { el.innerHTML = '<div class="empty-state">Failed to load schedules</div>'; });
}

function showAddScheduleModal() {
    const modal = document.getElementById('modal-content');
    const overlay = document.getElementById('modal-overlay');
    modal.innerHTML = `
        <div style="padding:20px;max-width:500px">
            <h3 style="margin:0 0 16px;color:#00e5ff">Add Supervision Schedule</h3>
            <div style="margin-bottom:12px">
                <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Device</label>
                <select id="ps-device" class="form-input" style="width:100%" onchange="(function(sel){var o=sel.options[sel.selectedIndex];document.getElementById('ps-mac').value=o.dataset.mac||'';document.getElementById('ps-user').value=o.dataset.user||'';})(this)">
                    <option value="">Loading devices...</option>
                </select>
            </div>
            <div style="margin-bottom:12px">
                <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">User Name</label>
                <input type="text" id="ps-user" class="form-input" placeholder="e.g. Kids" style="width:100%">
            </div>
            <input type="hidden" id="ps-mac">
            <div style="display:flex;gap:12px;margin-bottom:12px">
                <div style="flex:1">
                    <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Weekday Block Start</label>
                    <input type="time" id="ps-wd-start" class="form-input" value="22:00" style="width:100%">
                </div>
                <div style="flex:1">
                    <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Weekday Block End</label>
                    <input type="time" id="ps-wd-end" class="form-input" value="07:00" style="width:100%">
                </div>
            </div>
            <div style="display:flex;gap:12px;margin-bottom:12px">
                <div style="flex:1">
                    <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Weekend Block Start</label>
                    <input type="time" id="ps-we-start" class="form-input" value="23:00" style="width:100%">
                </div>
                <div style="flex:1">
                    <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Weekend Block End</label>
                    <input type="time" id="ps-we-end" class="form-input" value="09:00" style="width:100%">
                </div>
            </div>
            <div style="margin-bottom:16px">
                <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Block Categories</label>
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                    ${['social','gaming','streaming','adult','shopping'].map(c =>
                        `<label style="display:flex;align-items:center;gap:4px;font-size:0.8rem;color:#ccc">
                            <input type="checkbox" class="ps-cat" value="${c}"> ${CAT_ICONS[c]||''} ${c}
                        </label>`
                    ).join('')}
                </div>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button class="btn btn-sm" onclick="document.getElementById('modal-overlay').style.display='none'">Cancel</button>
                <button class="btn btn-primary" onclick="saveSchedule()">Save Schedule</button>
            </div>
        </div>`;
    overlay.style.display = 'flex';
    // Load known devices into dropdown
    fetch(SN_API + '/supervision/known-devices').then(r=>r.json()).then(d => {
        const sel = document.getElementById('ps-device');
        if (!sel) return;
        sel.textContent = '';
        var manualOpt = document.createElement('option');
        manualOpt.value = 'manual';
        manualOpt.textContent = '-- Manual entry --';
        manualOpt.dataset.mac = '';
        manualOpt.dataset.user = '';
        sel.appendChild(manualOpt);
        (d.devices || []).forEach(dev => {
            var opt = document.createElement('option');
            opt.value = dev.mac_address;
            opt.textContent = (dev.user_name || '') + ' - ' + (dev.device_label || dev.mac_address) + ' (' + (dev.device_type || '?') + ')';
            opt.dataset.mac = dev.mac_address;
            opt.dataset.user = dev.user_name || dev.device_label || '';
            sel.appendChild(opt);
        });
    }).catch(function() {
        var sel = document.getElementById('ps-device');
        if (sel) { sel.textContent = ''; var o = document.createElement('option'); o.textContent = 'Failed to load'; sel.appendChild(o); }
    });
}

function saveSchedule() {
    const cats = [...document.querySelectorAll('.ps-cat:checked')].map(c=>c.value);
    const body = {
        user_name: document.getElementById('ps-user').value,
        device_mac: document.getElementById('ps-mac').value,
        schedule: {
            weekday: {start: document.getElementById('ps-wd-start').value, end: document.getElementById('ps-wd-end').value},
            weekend: {start: document.getElementById('ps-we-start').value, end: document.getElementById('ps-we-end').value}
        },
        blocked_categories: cats
    };
    fetch(SN_API + '/supervision/schedules', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
        .then(r=>r.json()).then(d => {
            document.getElementById('modal-overlay').style.display = 'none';
            if (d.success) loadSupervisionSchedules();
            else alert('Error: ' + (d.error||'Unknown'));
        });
}

function deleteSchedule(id) {
    if (!confirm('Delete this schedule?')) return;
    fetch(SN_API + '/supervision/schedules/' + id, {method:'DELETE'}).then(r=>r.json()).then(() => loadSupervisionSchedules());
}

/* ─── Traffic by User ─── */
function loadTrafficByUser() {
    const el = document.getElementById('traffic-by-user');
    const hours = document.getElementById('traffic-period')?.value || 24;
    el.innerHTML = '<div class="loading-state"><span class="spinner"></span> Loading...</div>';
    fetch(SN_API + '/traffic/classification/by-user?hours=' + hours).then(r=>r.json()).then(d => {
        if (!d.success || !d.data || d.data.length === 0) { el.innerHTML = '<div class="empty-state">No traffic data</div>'; return; }
        let html = '<table class="data-table"><thead><tr><th>User</th>';
        const cats = [...new Set(d.data.map(r=>r.category))].sort();
        cats.forEach(c => { html += `<th style="color:${CAT_COLORS[c]||'#888'}">${CAT_ICONS[c]||''} ${c}</th>`; });
        html += '<th>Total</th></tr></thead><tbody>';
        // Group by user
        const users = {};
        d.data.forEach(r => {
            if (!users[r.user_name]) users[r.user_name] = {total:0};
            users[r.user_name][r.category] = (users[r.user_name][r.category]||0) + parseInt(r.queries||0);
            users[r.user_name].total += parseInt(r.queries||0);
        });
        Object.entries(users).sort((a,b)=>b[1].total-a[1].total).forEach(([user, data]) => {
            html += `<tr><td><strong>${user}</strong></td>`;
            cats.forEach(c => {
                const v = data[c]||0;
                if (v > 0) {
                    html += `<td><a href="#" onclick="showCategoryDomains('${user.replace(/'/g,"\\'")}','${c}',${hours});return false" style="color:${CAT_COLORS[c]||'#ccc'};text-decoration:underline;cursor:pointer">${fmtNum(v)}</a></td>`;
                } else {
                    html += `<td>0</td>`;
                }
            });
            html += `<td><strong>${fmtNum(data.total)}</strong></td></tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    }).catch(() => { el.innerHTML = '<div class="empty-state">Failed to load</div>'; });
}

/* ─── Brain Rot Leaderboard ─── */
function loadBrainRotBoard() {
    const el = document.getElementById('brain-rot-board');
    el.innerHTML = '<div class="loading-state"><span class="spinner"></span> Loading...</div>';
    fetch(SN_API + '/traffic/classification/by-user?hours=24').then(r=>r.json()).then(d => {
        if (!d.success || !d.data || d.data.length === 0) { el.innerHTML = '<div class="empty-state">No data</div>'; return; }
        const rotCats = ['social','streaming','gaming','shopping'];
        const users = {};
        d.data.forEach(r => {
            if (!users[r.user_name]) users[r.user_name] = {total:0, rot:0, cats:{}};
            const q = parseInt(r.queries||0);
            users[r.user_name].total += q;
            if (rotCats.includes(r.category)) {
                users[r.user_name].rot += q;
                users[r.user_name].cats[r.category] = (users[r.user_name].cats[r.category]||0) + q;
            }
        });
        const sorted = Object.entries(users).sort((a,b) => b[1].rot - a[1].rot);
        const maxRot = sorted[0]?.[1]?.rot || 1;
        let html = '<div style="display:flex;flex-direction:column;gap:12px;padding:8px">';
        sorted.forEach(([user, data], i) => {
            const pct = data.total > 0 ? Math.round(data.rot / data.total * 100) : 0;
            const barW = Math.round(data.rot / maxRot * 100);
            const catBreakdown = rotCats.map(c => {
                const v = data.cats[c] || 0;
                return v > 0 ? `<span style="color:${CAT_COLORS[c]}">${CAT_ICONS[c]} ${fmtNum(v)}</span>` : '';
            }).filter(Boolean).join(' &nbsp; ');
            html += `<div>
                <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                    <span style="font-weight:bold;color:${i===0?'#ef4444':'#ccc'}">${i===0?'👑 ':''}${user}</span>
                    <span style="color:#f59e0b;font-weight:bold">${pct}% brain rot</span>
                </div>
                <div style="background:rgba(255,255,255,0.05);border-radius:4px;height:24px;overflow:hidden">
                    <div style="height:100%;width:${barW}%;background:linear-gradient(90deg,${CAT_COLORS.social},${CAT_COLORS.gaming});border-radius:4px;transition:width 0.5s"></div>
                </div>
                <div style="font-size:0.72rem;color:#888;margin-top:2px">${catBreakdown} &nbsp; (${fmtNum(data.rot)} / ${fmtNum(data.total)} queries)</div>
            </div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    }).catch(() => { el.innerHTML = '<div class="empty-state">Failed to load</div>'; });
}

/* ─── DNS Device Activity (AdGuard-powered) ─── */
function loadDeviceActivity() {
    var el = document.getElementById('dns-device-activity');
    if (!el) return;
    el.textContent = '';
    var loading = document.createElement('div');
    loading.className = 'loading-state';
    loading.textContent = 'Loading DNS activity...';
    el.appendChild(loading);

    fetch(SN_API + '/supervision/device-activity').then(function(r) { return r.json(); }).then(function(d) {
        el.textContent = '';
        if (!d.success || !d.devices || !d.devices.length) {
            el.textContent = 'No DNS activity data';
            return;
        }
        var table = document.createElement('table');
        table.className = 'data-table';
        var thead = document.createElement('thead');
        var hrow = document.createElement('tr');
        ['Device', 'Queries', 'Blocked', 'Top Domains'].forEach(function(h) {
            var th = document.createElement('th');
            th.textContent = h;
            hrow.appendChild(th);
        });
        thead.appendChild(hrow);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        d.devices.forEach(function(dev) {
            var tr = document.createElement('tr');

            var tdName = document.createElement('td');
            var strong = document.createElement('strong');
            strong.textContent = dev.label;
            tdName.appendChild(strong);
            var ipSpan = document.createElement('span');
            ipSpan.style.cssText = 'display:block;font-size:0.7rem;color:#888';
            ipSpan.textContent = dev.ip + (dev.type ? ' (' + dev.type + ')' : '');
            tdName.appendChild(ipSpan);

            var tdQueries = document.createElement('td');
            tdQueries.style.color = '#00e5ff';
            tdQueries.textContent = (dev.total_queries || 0).toLocaleString();

            var tdBlocked = document.createElement('td');
            tdBlocked.style.color = dev.blocked > 0 ? '#ef4444' : '#6b7280';
            tdBlocked.textContent = (dev.blocked || 0).toLocaleString();

            var tdDomains = document.createElement('td');
            tdDomains.style.fontSize = '0.75rem';
            (dev.top_domains || []).forEach(function(dom) {
                var line = document.createElement('div');
                line.textContent = dom.domain + ' (' + dom.count + ')';
                tdDomains.appendChild(line);
            });
            if (!dev.top_domains || !dev.top_domains.length) tdDomains.textContent = '--';

            tr.appendChild(tdName);
            tr.appendChild(tdQueries);
            tr.appendChild(tdBlocked);
            tr.appendChild(tdDomains);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        el.appendChild(table);
    }).catch(function() { el.textContent = 'Failed to load DNS activity'; });
}

/* ─── Category Domain Drill-down (LCARS Modal) ─── */
function showCategoryDomains(user, category, hours) {
    const color = CAT_COLORS[category] || '#00e5ff';
    const rgb = _hexToRgb(color);
    const existing = document.getElementById('cat-domains-overlay');
    if (existing) existing.remove();

    const html = `<div class="bm-overlay active" id="cat-domains-overlay" style="--bm-accent:${color};--bm-accent-rgb:${rgb}">
        <div class="bm-shell" style="max-width:640px">
            <div class="bm-frame">
                <div class="bm-frame-elbow-top"></div><div class="bm-frame-seg"></div>
                <div class="bm-frame-seg dim"></div><div class="bm-frame-light on"></div>
                <div class="bm-frame-light amber"></div><div class="bm-frame-seg purple"></div>
                <div class="bm-frame-fill"></div><div class="bm-frame-elbow-bottom"></div>
            </div>
            <div class="bm-content">
                <div class="bm-header">
                    <span class="bm-header-title">${category.toUpperCase()} DOMAINS</span>
                    <div class="bm-header-strip">
                        <div class="bm-header-pip w1"></div><div class="bm-header-pip w2"></div>
                        <div class="bm-header-pip w3"></div>
                        <button class="bm-close" onclick="document.getElementById('cat-domains-overlay').remove()">&times;</button>
                    </div>
                </div>
                <div style="padding:8px 16px;border-bottom:1px solid rgba(${rgb},0.15);font-size:0.75rem;color:#888">
                    User: <strong style="color:#ccc">${user}</strong> &nbsp;|&nbsp; Last ${hours}h
                </div>
                <div class="bm-body" id="cat-domains-body" style="padding:12px 16px;max-height:55vh;overflow-y:auto">
                    <div style="text-align:center;padding:20px;color:#94a3b8">Loading domains...</div>
                </div>
                <div class="bm-footer" style="padding:8px 16px;display:flex;gap:8px;justify-content:flex-end">
                    <button class="btn" onclick="document.getElementById('cat-domains-overlay').remove()" style="opacity:0.7">Close</button>
                </div>
            </div>
        </div>
    </div>`;

    document.body.insertAdjacentHTML('beforeend', html);
    document.getElementById('cat-domains-overlay').addEventListener('click', function(e) {
        if (e.target === this) this.remove();
    });

    fetch(SN_API + '/traffic/classification/domains?user=' + encodeURIComponent(user) + '&category=' + encodeURIComponent(category) + '&hours=' + hours)
        .then(r => r.json()).then(d => {
            const el = document.getElementById('cat-domains-body');
            if (!d.success || !d.domains || d.domains.length === 0) {
                el.innerHTML = '<div class="empty-state">No domains found</div>';
                return;
            }
            let tbl = '<table class="data-table" style="font-size:0.8rem"><thead><tr><th>Domain</th><th>Queries</th><th>Blocked</th><th>Classify</th></tr></thead><tbody>';
            d.domains.forEach(dm => {
                const blocked = dm.ever_blocked ? '<span style="color:#ef4444">Blocked</span>' : '<span style="color:#22c55e">Allowed</span>';
                const safeDomain = dm.domain.replace(/[<>&"']/g, '');
                tbl += `<tr>
                    <td><a href="#" onclick="document.getElementById('cat-domains-overlay').remove();openDomainIntel('${safeDomain}');return false"
                        style="color:${color};text-decoration:underline;cursor:pointer;word-break:break-all">${safeDomain}</a></td>
                    <td>${fmtNum(dm.queries)}</td>
                    <td>${blocked}</td>
                    <td><select onchange="reclassifyDomain('${safeDomain}',this.value)" style="font-size:0.7rem;padding:2px 4px;background:#1a1a2e;color:#ccc;border:1px solid #333;border-radius:3px;cursor:pointer">
                        <option value="">-- ${category} --</option>
                        <option value="work">Work</option>
                        <option value="social">Social</option>
                        <option value="streaming">Streaming</option>
                        <option value="gaming">Gaming</option>
                        <option value="shopping">Shopping</option>
                        <option value="ads">Ads/Tracking</option>
                        <option value="adult">Adult</option>
                    </select></td>
                </tr>`;
            });
            tbl += '</tbody></table>';
            el.innerHTML = tbl;
        }).catch(() => {
            document.getElementById('cat-domains-body').innerHTML = '<div class="empty-state">Failed to load domains</div>';
        });
}

function reclassifyDomain(domain, newCategory) {
    if (!newCategory) return;
    fetch(SN_API + '/traffic/classification/reclassify', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({domain_pattern: domain.replace(/^.*?([^.]+\.[^.]+)$/, '$1'), category: newCategory})
    }).then(r => r.json()).then(d => {
        if (d.success) showToast('success', domain + ' → ' + newCategory);
        else showToast('error', d.message || 'Failed');
    }).catch(() => showToast('error', 'Network error'));
}

function _hexToRgb(hex) {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    return r+','+g+','+b;
}

/* ═══════════════════════════════════════════════════════════════════
   3. THREAT INTELLIGENCE
   ═══════════════════════════════════════════════════════════════════ */
function loadIntelTab() {
    loadThreatFeeds(); loadThreatHits(); loadIncidents();
    loadDnsThreatCrossref(); loadSeverityChart(); loadHoneypotEvents(); loadWeeklyReport();
}

function _feedHealthColor(lastUpdated) {
    if (!lastUpdated) return '#ef4444';
    var age = (Date.now() - new Date(lastUpdated).getTime()) / 3600000;
    if (age < 6) return '#22c55e';
    if (age < 24) return '#fbbf24';
    return '#ef4444';
}

function loadThreatFeeds() {
    fetch(SN_API + '/threat-intel/status').then(function(r) { return r.json(); }).then(function(d) {
        if (!d.success) return;
        var el = document.getElementById('intel-feeds');
        var feeds = d.feeds || d.status || {};
        var total = 0;
        var needsSync = false;
        el.textContent = '';
        var grid = document.createElement('div');
        grid.style.cssText = 'display:flex;gap:12px;flex-wrap:wrap;padding:8px';

        Object.entries(feeds).forEach(function(entry) {
            var name = entry[0], info = entry[1];
            var cnt = info.count || 0;
            total += cnt;
            var updated = info.last_updated ? new Date(info.last_updated).toLocaleString() : 'Never';
            var dotColor = _feedHealthColor(info.last_updated);
            if (dotColor !== '#22c55e') needsSync = true;

            var card = document.createElement('div');
            card.style.cssText = 'flex:1;min-width:200px;background:rgba(255,255,255,0.03);border-radius:8px;padding:12px;border:1px solid ' + dotColor + '33';
            var header = document.createElement('div');
            header.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px';
            var dot = document.createElement('span');
            dot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:' + dotColor;
            var strong = document.createElement('strong');
            strong.style.color = '#e2e8f0';
            strong.textContent = name;
            header.appendChild(dot);
            header.appendChild(strong);
            var countDiv = document.createElement('div');
            countDiv.style.cssText = 'font-size:0.8rem;color:#94a3b8';
            countDiv.textContent = fmtNum(cnt) + ' IOCs';
            var timeDiv = document.createElement('div');
            timeDiv.style.cssText = 'font-size:0.7rem;color:#64748b';
            timeDiv.textContent = 'Updated: ' + updated;
            card.appendChild(header);
            card.appendChild(countDiv);
            card.appendChild(timeDiv);
            grid.appendChild(card);
        });
        el.appendChild(grid);
        document.getElementById('intel-ioc-count').textContent = fmtNum(total);

        // Auto-sync if any feed is stale (>6h) and total IOCs < 100
        if (needsSync && total < 100) {
            syncThreatIntel();
        }
    }).catch(function() {});
}

function syncThreatIntel() {
    var el = document.getElementById('intel-feeds');
    el.textContent = '';
    var loading = document.createElement('div');
    loading.className = 'loading-state';
    loading.textContent = 'Syncing feeds...';
    el.appendChild(loading);
    fetch(SN_API + '/threat-intel/sync', {method:'POST'}).then(function(r) { return r.json(); }).then(function(d) {
        loadThreatFeeds(); loadThreatHits(); loadSeverityChart();
    }).catch(function() { el.textContent = 'Sync failed'; });
}

/* ─── IOC Search ─── */
function searchIOC() {
    var query = document.getElementById('ioc-search-input').value.trim();
    var el = document.getElementById('ioc-search-results');
    if (!query || query.length < 3) { el.textContent = 'Enter at least 3 characters'; return; }
    el.textContent = 'Searching...';
    fetch(SN_API + '/threat-intel/search?q=' + encodeURIComponent(query)).then(function(r) { return r.json(); }).then(function(d) {
        el.textContent = '';
        if (!d.success || !d.results.length) { el.textContent = 'No matches found — ' + query + ' is not in threat database'; el.style.color = '#22c55e'; return; }
        el.style.color = '';
        var table = document.createElement('table');
        table.className = 'data-table';
        var thead = document.createElement('thead');
        var hrow = document.createElement('tr');
        ['IOC', 'Type', 'Severity', 'Feed'].forEach(function(h) { var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th); });
        thead.appendChild(hrow);
        table.appendChild(thead);
        var tbody = document.createElement('tbody');
        d.results.forEach(function(r) {
            var tr = document.createElement('tr');
            [r.ioc_value, r.ioc_type, r.severity, r.feed].forEach(function(val, i) {
                var td = document.createElement('td');
                td.textContent = val;
                if (i === 2) td.style.color = val === 'critical' ? '#ef4444' : val === 'high' ? '#f59e0b' : '#94a3b8';
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        el.appendChild(table);
    }).catch(function() { el.textContent = 'Search failed'; });
}

/* ─── Severity Chart (D3 donut) ─── */
function loadSeverityChart() {
    var el = document.getElementById('intel-severity-chart');
    if (!el) return;
    fetch(SN_API + '/threat-intel/severity-stats').then(function(r) { return r.json(); }).then(function(d) {
        if (!d.success || !d.breakdown.length) return;
        el.textContent = '';
        var w = 200, h = 200, radius = 80;
        var colors = {critical:'#ef4444', high:'#f59e0b', medium:'#3b82f6', low:'#6b7280'};
        var svg = d3.select(el).append('svg').attr('width', w).attr('height', h)
            .append('g').attr('transform', 'translate(' + w/2 + ',' + h/2 + ')');
        var pie = d3.pie().value(function(x) { return x.count; }).sort(null);
        var arc = d3.arc().innerRadius(radius * 0.55).outerRadius(radius);
        svg.selectAll('path').data(pie(d.breakdown)).join('path')
            .attr('d', arc)
            .attr('fill', function(x) { return colors[x.data.severity] || '#6b7280'; })
            .attr('stroke', '#0a0a1a').attr('stroke-width', 2);
        // Center total
        svg.append('text').attr('text-anchor', 'middle').attr('dy', '-0.2em')
            .attr('fill', '#e2e8f0').attr('font-size', '1.2rem').attr('font-family', 'Orbitron')
            .text(fmtNum(d.total));
        svg.append('text').attr('text-anchor', 'middle').attr('dy', '1.2em')
            .attr('fill', '#64748b').attr('font-size', '0.65rem').text('IOCs');
        // Legend
        var legend = d3.select(el).append('div').style('display', 'flex').style('gap', '12px')
            .style('justify-content', 'center').style('margin-top', '8px').style('font-size', '0.75rem');
        d.breakdown.forEach(function(b) {
            var item = legend.append('span').style('color', colors[b.severity] || '#6b7280');
            item.text(b.severity + ': ' + fmtNum(b.count));
        });
    }).catch(function() {});
}

/* ─── Scan Query Log ─── */
function scanQueryLog() {
    var el = document.getElementById('querylog-scan-results');
    if (!el) return;
    el.textContent = 'Scanning DNS query log against IOC database...';
    fetch(SN_API + '/threat-intel/scan-querylog', {method:'POST'}).then(function(r) { return r.json(); }).then(function(d) {
        el.textContent = '';
        if (!d.success) { el.textContent = 'Scan failed'; return; }
        var summary = document.createElement('div');
        summary.style.cssText = 'padding:8px;font-size:0.85rem;color:#e2e8f0';
        summary.textContent = d.domains_scanned + ' domains scanned | ' + d.threat_count + ' threats found';
        el.appendChild(summary);
        if (d.threats_found && d.threats_found.length > 0) {
            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var hrow = document.createElement('tr');
            ['Domain', 'IOC Match', 'Severity', 'Feed', 'Threat'].forEach(function(h) { var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th); });
            thead.appendChild(hrow);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            d.threats_found.forEach(function(t) {
                var tr = document.createElement('tr');
                [t.domain, t.ioc_match, t.severity, t.feed, t.threat_type].forEach(function(val, i) {
                    var td = document.createElement('td');
                    td.textContent = val || '--';
                    if (i === 0) td.style.color = '#ef4444';
                    if (i === 2) td.style.color = val === 'critical' ? '#ef4444' : '#f59e0b';
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            el.appendChild(table);
        } else {
            var clean = document.createElement('div');
            clean.style.cssText = 'padding:8px;color:#22c55e;font-size:0.85rem';
            clean.textContent = 'All clear — no queried domains match known threats.';
            el.appendChild(clean);
        }
    }).catch(function() { el.textContent = 'Scan failed'; });
}

/* ─── Auto-Block IOC Domains ─── */
function autoBlockThreats() {
    if (!confirm('This will add high/critical threat domains to AdGuard block rules. Continue?')) return;
    var el = document.getElementById('auto-block-results');
    if (!el) return;
    el.textContent = 'Blocking threat domains...';
    fetch(SN_API + '/threat-intel/auto-block', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_severity:'high'})})
        .then(function(r) { return r.json(); }).then(function(d) {
            el.textContent = '';
            var msg = document.createElement('div');
            msg.style.cssText = 'padding:8px;font-size:0.85rem';
            if (d.success) {
                msg.style.color = '#22c55e';
                msg.textContent = d.blocked + ' domains blocked (of ' + d.total_eligible + ' eligible, min severity: ' + d.min_severity + ')';
            } else {
                msg.style.color = '#ef4444';
                msg.textContent = 'Failed: ' + (d.error || 'Unknown error');
            }
            el.appendChild(msg);
        }).catch(function() { el.textContent = 'Failed'; });
}

function loadThreatHits() {
    fetch(SN_API + '/threat-intel/hits?limit=20').then(r=>r.json()).then(d => {
        const el = document.getElementById('intel-hits');
        const hits = d.hits || [];
        document.getElementById('intel-hit-count').textContent = hits.length;
        if (!hits.length) { el.innerHTML = '<div class="empty-state">No threat intel hits - network is clean</div>'; return; }
        let html = '<table class="data-table"><thead><tr><th>Device</th><th>Matched</th><th>Severity</th><th>Feed</th><th>Time</th></tr></thead><tbody>';
        hits.forEach(h => {
            html += `<tr><td>${h.device_ip}</td><td>${h.domain||h.ioc_value||'?'}</td><td>${sevBadge(h.severity)}</td><td>${h.feed_name||'?'}</td><td>${h.detected_at ? new Date(h.detected_at).toLocaleString() : '?'}</td></tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    }).catch(() => {});
}

/* ─── DNS Threat Cross-Reference ─── */
function loadDnsThreatCrossref() {
    var el = document.getElementById('intel-dns-crossref');
    if (!el) return;
    el.textContent = '';
    var loading = document.createElement('div');
    loading.className = 'loading-state';
    loading.textContent = 'Analyzing...';
    el.appendChild(loading);

    fetch(SN_API + '/threat-intel/dns-crossref').then(function(r) { return r.json(); }).then(function(d) {
        el.textContent = '';
        if (!d.success) { el.textContent = 'Failed to load'; return; }

        // Update hero card
        var dnsEl = document.getElementById('intel-dns-blocked');
        if (dnsEl) dnsEl.textContent = (d.dns_blocked_24h || 0).toLocaleString();

        // Summary line
        var summary = document.createElement('div');
        summary.style.cssText = 'padding:8px 4px;font-size:0.85rem;color:#e2e8f0';
        summary.textContent = d.total_blocked_domains + ' domains blocked by AdGuard | ' + d.match_count + ' matched threat intel IOCs';
        el.appendChild(summary);

        if (d.ioc_matches && d.ioc_matches.length > 0) {
            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var hrow = document.createElement('tr');
            ['Domain', 'Blocked', 'Severity', 'Feed', 'Threat'].forEach(function(h) {
                var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th);
            });
            thead.appendChild(hrow);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            d.ioc_matches.forEach(function(m) {
                var tr = document.createElement('tr');
                var cells = [m.domain, m.blocked_count.toLocaleString(), m.severity, m.feed, m.threat_type || '--'];
                cells.forEach(function(val, i) {
                    var td = document.createElement('td');
                    td.textContent = val;
                    if (i === 2) td.style.color = val === 'critical' ? '#ef4444' : val === 'high' ? '#f59e0b' : '#94a3b8';
                    if (i === 0) td.style.color = '#ef4444';
                    tr.appendChild(td);
                });
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            el.appendChild(table);
        } else {
            var clean = document.createElement('div');
            clean.style.cssText = 'padding:12px;color:#22c55e;font-size:0.85rem';
            clean.textContent = 'No blocked domains match known threat feeds — network traffic is clean.';
            el.appendChild(clean);
        }
    }).catch(function() { el.textContent = 'Failed to load'; });
}

/* ─── Honeypot Monitor ─── */
function loadHoneypotEvents() {
    var el = document.getElementById('honeypot-events');
    if (!el) return;
    el.textContent = '';
    // Check if honeypot port is being probed via AdGuard or connection logs
    fetch(SN_API + '/threat-intel/dns-crossref').then(function(r) { return r.json(); }).then(function(d) {
        if (!d.success) { el.textContent = 'Honeypot offline'; return; }
        var div = document.createElement('div');
        div.style.cssText = 'padding:12px;font-size:0.85rem;color:#94a3b8';
        div.textContent = 'Honeypot monitoring via DNS threat correlation. ' +
            d.dns_blocked_24h + ' suspicious queries blocked in last 24h. ' +
            d.match_count + ' matched known threat IOCs.';
        el.appendChild(div);
    }).catch(function() {
        el.textContent = 'Honeypot not configured';
    });
}

/* ═══════════════════════════════════════════════════════════════════
   4. INCIDENTS
   ═══════════════════════════════════════════════════════════════════ */
function loadIncidents() {
    fetch(SN_API + '/incidents?status=open').then(r=>r.json()).then(d => {
        const el = document.getElementById('intel-incidents');
        const incidents = d.incidents || [];
        document.getElementById('intel-incident-count').textContent = incidents.length;
        if (!incidents.length) { el.innerHTML = '<div class="empty-state">No open incidents</div>'; return; }
        let html = '<table class="data-table"><thead><tr><th>Title</th><th>Severity</th><th>Device</th><th>Alerts</th><th>Time</th><th>Action</th></tr></thead><tbody>';
        incidents.forEach(inc => {
            const alertCnt = (inc.alert_ids || []).length;
            html += `<tr><td>${inc.title}</td><td>${sevBadge(inc.severity)}</td><td>${inc.device_ip||'Multiple'}</td>
                <td>${alertCnt}</td><td>${inc.created_at ? new Date(inc.created_at).toLocaleString() : '?'}</td>
                <td><button class="btn btn-sm" onclick="resolveIncident(${inc.id})" style="color:#22c55e">Resolve</button></td></tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    }).catch(() => {});
}

function correlateIncidents() {
    fetch(SN_API + '/incidents/correlate', {method:'POST'}).then(r=>r.json()).then(() => loadIncidents());
}

function resolveIncident(id) {
    fetch(SN_API + '/incidents/' + id + '/resolve', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({notes:'Resolved from dashboard'})})
        .then(r=>r.json()).then(() => loadIncidents());
}

/* ═══════════════════════════════════════════════════════════════════
   5. SPEED TEST
   ═══════════════════════════════════════════════════════════════════ */
function loadSpeedHistory() {
    fetch(SN_API + '/speed-test/history?limit=20').then(r=>r.json()).then(d => {
        const results = d.results || d.history || [];
        if (results.length > 0) {
            const latest = results[0];
            document.getElementById('intel-speed').textContent = `${latest.download_mbps||0}↓ / ${latest.upload_mbps||0}↑`;
        }
        const ctx = document.getElementById('speed-chart');
        if (!ctx) return;
        if (_speedChart) _speedChart.destroy();
        const labels = results.map(r => new Date(r.tested_at).toLocaleDateString()).reverse();
        _speedChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {label:'Download (Mbps)', data: results.map(r=>r.download_mbps).reverse(), borderColor:'#22d3ee', fill:false, tension:0.3},
                    {label:'Upload (Mbps)', data: results.map(r=>r.upload_mbps).reverse(), borderColor:'#a78bfa', fill:false, tension:0.3},
                    {label:'Ping (ms)', data: results.map(r=>r.ping_ms).reverse(), borderColor:'#f59e0b', fill:false, tension:0.3, yAxisID:'y1'}
                ]
            },
            options: {
                responsive:true, maintainAspectRatio:false,
                scales: {
                    y: {title:{display:true,text:'Mbps',color:'#888'}, grid:{color:'#222'}},
                    y1: {position:'right', title:{display:true,text:'ms',color:'#888'}, grid:{drawOnChartArea:false}},
                    x: {grid:{color:'#222'}}
                },
                plugins: {legend:{labels:{color:'#ccc'}}}
            }
        });
    }).catch(() => {});
}

function runSpeedTest() {
    const el = document.getElementById('speed-test-status');
    el.textContent = 'Running speed test... (this takes ~30 seconds)';
    el.style.color = '#fbbf24';
    fetch(SN_API + '/speed-test/run', {method:'POST'}).then(r=>r.json()).then(d => {
        if (d.success && d.result) {
            el.textContent = `Done! ${d.result.download_mbps}↓ / ${d.result.upload_mbps}↑ Mbps, ${d.result.ping_ms}ms ping`;
            el.style.color = '#22c55e';
            loadSpeedHistory();
        } else {
            el.textContent = 'Speed test failed: ' + (d.error || 'Unknown error');
            el.style.color = '#ef4444';
        }
    }).catch(e => { el.textContent = 'Error: ' + e.message; el.style.color = '#ef4444'; });
}

/* ═══════════════════════════════════════════════════════════════════
   6. HONEYPOT
   ═══════════════════════════════════════════════════════════════════ */
function loadHoneypotEvents() {
    fetch(SN_API + '/honeypot/config').then(r=>r.json()).then(d => {
        const running = d.config?.running || d.running || false;
        const el = document.getElementById('honeypot-events');
        if (!running) {
            fetch(SN_API + '/honeypot/events?limit=20').then(r=>r.json()).then(d2 => {
                const events = d2.events || [];
                if (!events.length) { el.innerHTML = '<div class="empty-state">Honeypot not running. Click "Start" to begin monitoring.</div>'; return; }
                renderHoneypotTable(events, el);
            });
            return;
        }
        fetch(SN_API + '/honeypot/events?limit=20').then(r=>r.json()).then(d2 => {
            const events = d2.events || [];
            if (!events.length) { el.innerHTML = '<div class="empty-state" style="color:#22c55e">Honeypot active — no events yet</div>'; return; }
            renderHoneypotTable(events, el);
        });
    }).catch(() => {});
}

function renderHoneypotTable(events, el) {
    let html = '<table class="data-table"><thead><tr><th>Source IP</th><th>Port</th><th>Protocol</th><th>Time</th></tr></thead><tbody>';
    events.forEach(e => {
        html += `<tr><td style="color:#ef4444">${e.source_ip}</td><td>${e.dest_port}</td><td>${e.protocol||'tcp'}</td><td>${e.detected_at ? new Date(e.detected_at).toLocaleString() : '?'}</td></tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
}

function startHoneypot() { fetch(SN_API + '/honeypot/start', {method:'POST'}).then(()=>loadHoneypotEvents()); }
function stopHoneypot() { fetch(SN_API + '/honeypot/stop', {method:'POST'}).then(()=>loadHoneypotEvents()); }

/* ═══════════════════════════════════════════════════════════════════
   7. WEEKLY REPORT
   ═══════════════════════════════════════════════════════════════════ */
function loadWeeklyReport() {
    const el = document.getElementById('weekly-report-preview');
    fetch(SN_API + '/reports/weekly').then(r=>r.json()).then(d => {
        if (!d.success || !d.report) { el.innerHTML = '<div class="empty-state">No report data</div>'; return; }
        const s = d.report.sections || {};
        let html = '<div style="padding:12px;font-size:0.82rem">';
        // Bandwidth by user
        const users = s.bandwidth_by_user || [];
        if (users.length) {
            html += '<h4 style="color:#00e5ff;margin:0 0 8px">Bandwidth by User</h4>';
            users.forEach(u => { html += `<div style="margin-bottom:4px"><strong>${u.user}</strong>: ${u.total} (${u.devices} devices)</div>`; });
            html += '<br>';
        }
        // DNS
        const dns = s.dns_summary || {};
        html += `<h4 style="color:#00e5ff;margin:0 0 8px">DNS Summary</h4>`;
        html += `<div>Queries: ${fmtNum(dns.total_queries)} | Blocked: ${fmtNum(dns.blocked_queries)} | Domains: ${fmtNum(dns.unique_domains)} | Devices: ${dns.active_devices}</div><br>`;
        // Incidents
        const inc = s.incidents || {};
        html += `<div>Incidents: ${inc.open||0} open, ${inc.resolved||0} resolved | Threat Intel Hits: ${s.threat_intel_hits||0}</div>`;
        html += '</div>';
        el.innerHTML = html;
    }).catch(() => { el.innerHTML = '<div class="empty-state">Failed to load report</div>'; });
}

function sendWeeklyReport() {
    fetch(SN_API + '/reports/weekly/send', {method:'POST'}).then(r=>r.json()).then(d => {
        alert(d.success ? 'Weekly report sent to Telegram!' : 'Failed: ' + (d.error||'Unknown'));
    });
}

/* ═══════════════════════════════════════════════════════════════════
   8. SINKHOLE ANALYTICS (DNS tab)
   ═══════════════════════════════════════════════════════════════════ */
function loadSinkholeStats() {
    var sel = document.getElementById('dns-period-select');
    // Restore saved period on first load
    if (sel && !sel._restored) {
        var saved = localStorage.getItem('sn_dns_period');
        if (saved && sel.querySelector('option[value="' + saved + '"]')) sel.value = saved;
        sel._restored = true;
    }
    var hours = sel ? sel.value : '24';
    if (sel) localStorage.setItem('sn_dns_period', hours);
    fetch(SN_API + '/dns/sinkhole-stats?hours=' + hours).then(r=>r.json()).then(d => {
        if (!d.success) return;
        // Pie chart by category
        const cats = d.categories || d.category_breakdown || [];
        const ctx = document.getElementById('sinkhole-chart');
        if (ctx && cats.length) {
            if (_sinkholeChart) _sinkholeChart.destroy();
            _sinkholeChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: cats.map(c => c.category),
                    datasets: [{
                        data: cats.map(c => c.block_count || c.count || c.queries),
                        backgroundColor: cats.map(c => CAT_COLORS[c.category] || '#555')
                    }]
                },
                options: {
                    responsive:true, maintainAspectRatio:false,
                    plugins: {legend:{position:'right',labels:{color:'#ccc',font:{size:11}}}},
                    onClick: function(evt, elements) {
                        if (!elements.length) return;
                        var idx = elements[0].index;
                        var category = cats[idx].category;
                        _showCategoryDomains(category, hours);
                    }
                }
            });
            // Also make legend items clickable (cursor hint)
            ctx.style.cursor = 'pointer';
        }
        // Top blocked domains table
        const domains = d.top_blocked || d.domains || [];
        const el = document.getElementById('sinkhole-table');
        if (domains.length) {
            let html = '<table class="data-table"><thead><tr><th>Domain</th><th>Blocked</th></tr></thead><tbody>';
            domains.slice(0,15).forEach(dd => { html += `<tr><td><a href="#" onclick="openDomainIntel('${dd.domain}');return false" style="color:#00e5ff;text-decoration:none;cursor:pointer">${dd.domain}</a></td><td>${fmtNum(dd.block_count||dd.count||dd.queries)}</td></tr>`; });
            html += '</tbody></table>';
            el.innerHTML = html;
        } else {
            el.innerHTML = '<div class="empty-state">No blocked domains</div>';
        }
    }).catch(() => {});
}

function _showCategoryDomains(category, hours) {
    // Remove any existing category modal
    var existing = document.getElementById('category-domains-overlay');
    if (existing) existing.remove();

    var safeCategory = category.replace(/[<>&"']/g, '');
    var color = CAT_COLORS[category] || '#00e5ff';

    var overlay = document.createElement('div');
    overlay.className = 'bm-overlay active';
    overlay.id = 'category-domains-overlay';
    overlay.style.cssText = '--bm-accent:' + color + ';--bm-accent-rgb:0,229,255';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    var shell = document.createElement('div');
    shell.className = 'bm-shell';
    shell.style.maxWidth = '540px';

    var frame = document.createElement('div');
    frame.className = 'bm-frame';
    ['bm-frame-elbow-top','bm-frame-seg','bm-frame-seg dim','bm-frame-light on','bm-frame-light amber','bm-frame-seg purple','bm-frame-fill','bm-frame-elbow-bottom'].forEach(function(cls) {
        var el = document.createElement('div');
        el.className = cls;
        frame.appendChild(el);
    });

    var content = document.createElement('div');
    content.className = 'bm-content';

    var header = document.createElement('div');
    header.className = 'bm-header';
    var title = document.createElement('span');
    title.className = 'bm-header-title';
    title.textContent = 'BLOCKED: ' + safeCategory.toUpperCase();
    var strip = document.createElement('div');
    strip.className = 'bm-header-strip';
    var closeX = document.createElement('button');
    closeX.className = 'bm-close';
    closeX.textContent = '\u00d7';
    closeX.addEventListener('click', function() { overlay.remove(); });
    strip.appendChild(closeX);
    header.appendChild(title);
    header.appendChild(strip);

    var body = document.createElement('div');
    body.className = 'bm-body';
    body.style.cssText = 'padding:16px;max-height:60vh;overflow-y:auto';
    body.textContent = 'Loading domains...';

    var footer = document.createElement('div');
    footer.className = 'bm-footer';
    footer.style.cssText = 'padding:12px 16px;display:flex;gap:8px;justify-content:flex-end';
    var closeBtn = document.createElement('button');
    closeBtn.className = 'btn';
    closeBtn.style.opacity = '0.7';
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', function() { overlay.remove(); });
    footer.appendChild(closeBtn);

    content.appendChild(header);
    content.appendChild(body);
    content.appendChild(footer);
    shell.appendChild(frame);
    shell.appendChild(content);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    // Fetch domains for this category
    fetch(SN_API + '/dns/sinkhole-stats/category?category=' + encodeURIComponent(category) + '&hours=' + hours)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (!d.success || !d.domains || !d.domains.length) {
                body.textContent = 'No domains found in this category.';
                return;
            }
            body.textContent = '';
            var countInfo = document.createElement('div');
            countInfo.style.cssText = 'color:#888;font-size:0.75rem;margin-bottom:12px';
            countInfo.textContent = d.domains.length + ' blocked domain' + (d.domains.length !== 1 ? 's' : '') + ' in "' + safeCategory + '"';
            body.appendChild(countInfo);

            d.domains.forEach(function(dom, idx) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;transition:background 0.15s';
                row.addEventListener('mouseenter', function() { row.style.background = 'rgba(255,255,255,0.04)'; });
                row.addEventListener('mouseleave', function() { row.style.background = 'transparent'; });
                row.addEventListener('click', function() { overlay.remove(); if (typeof openDomainIntel === 'function') openDomainIntel(dom.domain); });
                row.title = 'Click to investigate ' + dom.domain;

                var left = document.createElement('div');
                left.style.cssText = 'display:flex;align-items:center;gap:8px;min-width:0';
                var rank = document.createElement('span');
                rank.style.cssText = 'color:#555;font-size:0.7rem;min-width:20px;text-align:right';
                rank.textContent = (idx + 1) + '.';
                var name = document.createElement('span');
                name.style.cssText = 'color:#ccc;font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
                name.textContent = dom.domain;
                left.appendChild(rank);
                left.appendChild(name);

                var right = document.createElement('div');
                right.style.cssText = 'display:flex;align-items:center;gap:8px';
                var badge = document.createElement('span');
                badge.style.cssText = 'background:rgba(239,68,68,0.15);color:#ef4444;padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:600';
                badge.textContent = fmtNum(dom.block_count);
                var devBadge = document.createElement('span');
                devBadge.style.cssText = 'color:#94a3b8;font-size:0.65rem';
                devBadge.textContent = dom.unique_devices + ' device' + (dom.unique_devices !== 1 ? 's' : '');
                right.appendChild(badge);
                right.appendChild(devBadge);

                row.appendChild(left);
                row.appendChild(right);
                body.appendChild(row);
            });
        })
        .catch(function(e) { body.textContent = 'Error loading category domains: ' + e; });
}

function loadDnsTrend() {
    var sel = document.getElementById('dns-period-select');
    var hours = sel ? sel.value : '24';
    fetch(SN_API + '/dns/query-trend?hours=' + hours).then(r=>r.json()).then(d => {
        if (!d.success || !d.points || !d.points.length) return;
        _renderDnsTrendChart(d.points);
    }).catch(() => {});
}

function _renderDnsTrendChart(points) {
    var svg = document.getElementById('dns-trend-chart');
    if (!svg || !points.length) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    var w = svg.clientWidth || 500;
    var h = svg.clientHeight || 180;
    var ns = 'http://www.w3.org/2000/svg';
    var pad = {top: 8, right: 10, bottom: 24, left: 45};
    var cw = w - pad.left - pad.right;
    var ch = h - pad.top - pad.bottom;

    var max = 1;
    points.forEach(function(p) { if (p.total > max) max = p.total; });
    max *= 1.15;
    var step = cw / Math.max(points.length - 1, 1);

    // Gradient defs
    var defs = document.createElementNS(ns, 'defs');
    [['dns-total', '#00e5ff'], ['dns-blocked', '#ef4444']].forEach(function(pair) {
        var grad = document.createElementNS(ns, 'linearGradient');
        grad.setAttribute('id', pair[0]); grad.setAttribute('x1','0'); grad.setAttribute('y1','0');
        grad.setAttribute('x2','0'); grad.setAttribute('y2','1');
        var s1 = document.createElementNS(ns, 'stop');
        s1.setAttribute('offset','0%'); s1.setAttribute('stop-color', pair[1]); s1.setAttribute('stop-opacity','0.4');
        var s2 = document.createElementNS(ns, 'stop');
        s2.setAttribute('offset','100%'); s2.setAttribute('stop-color', pair[1]); s2.setAttribute('stop-opacity','0.02');
        grad.appendChild(s1); grad.appendChild(s2); defs.appendChild(grad);
    });
    svg.appendChild(defs);

    // Grid lines + Y-axis
    var fmtNum = function(n) { return n >= 1000 ? (n/1000).toFixed(1)+'K' : n.toString(); };
    for (var gi = 0; gi <= 4; gi++) {
        var gy = pad.top + ch - (gi / 4) * ch;
        var gLine = document.createElementNS(ns, 'line');
        gLine.setAttribute('x1', pad.left); gLine.setAttribute('y1', gy.toFixed(1));
        gLine.setAttribute('x2', w - pad.right); gLine.setAttribute('y2', gy.toFixed(1));
        gLine.setAttribute('stroke', 'rgba(255,255,255,0.06)'); gLine.setAttribute('stroke-width', '1');
        svg.appendChild(gLine);
        var yLabel = document.createElementNS(ns, 'text');
        yLabel.setAttribute('x', pad.left - 4); yLabel.setAttribute('y', (gy + 3).toFixed(1));
        yLabel.setAttribute('fill', '#666'); yLabel.setAttribute('font-size', '9');
        yLabel.setAttribute('text-anchor', 'end'); yLabel.setAttribute('font-family', '"IBM Plex Mono",monospace');
        yLabel.textContent = fmtNum(Math.round((gi / 4) * max));
        svg.appendChild(yLabel);
    }

    // X-axis labels
    var xCount = Math.min(points.length, 6);
    var xStep = Math.max(1, Math.floor((points.length - 1) / (xCount - 1)));
    for (var xi = 0; xi < points.length; xi += xStep) {
        var xx = pad.left + xi * step;
        var xLabel = document.createElementNS(ns, 'text');
        xLabel.setAttribute('x', xx.toFixed(1)); xLabel.setAttribute('y', (h - 4).toFixed(1));
        xLabel.setAttribute('fill', '#666'); xLabel.setAttribute('font-size', '9');
        xLabel.setAttribute('text-anchor', 'middle'); xLabel.setAttribute('font-family', '"IBM Plex Mono",monospace');
        xLabel.textContent = points[xi].label;
        svg.appendChild(xLabel);
    }

    // Draw both series
    [['total', '#00e5ff', 'dns-total'], ['blocked', '#ef4444', 'dns-blocked']].forEach(function(cfg) {
        var key = cfg[0], color = cfg[1], gradId = cfg[2];
        var pts = points.map(function(p, i) {
            return [pad.left + i * step, pad.top + ch - (p[key] / max) * ch];
        });
        // Area
        var areaStr = (pad.left).toFixed(1)+','+(pad.top+ch).toFixed(1)+' '+pts.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ')+' '+pts[pts.length-1][0].toFixed(1)+','+(pad.top+ch).toFixed(1);
        var area = document.createElementNS(ns, 'polygon');
        area.setAttribute('points', areaStr); area.setAttribute('fill', 'url(#'+gradId+')');
        svg.appendChild(area);
        // Line
        var line = document.createElementNS(ns, 'polyline');
        line.setAttribute('points', pts.map(function(p){return p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' '));
        line.setAttribute('fill','none'); line.setAttribute('stroke', color);
        line.setAttribute('stroke-width','2.5'); line.setAttribute('stroke-linejoin','round'); line.setAttribute('stroke-linecap','round');
        svg.appendChild(line);
        // Dots if few points
        if (pts.length <= 30) {
            pts.forEach(function(p) {
                var dot = document.createElementNS(ns, 'circle');
                dot.setAttribute('cx', p[0].toFixed(1)); dot.setAttribute('cy', p[1].toFixed(1));
                dot.setAttribute('r', '3'); dot.setAttribute('fill', color); dot.setAttribute('opacity', '0.7');
                svg.appendChild(dot);
            });
        }
    });
}

/* ═══════════════════════════════════════════════════════════════════
   9. TRAFFIC CLASSIFICATION (Devices tab)
   ═══════════════════════════════════════════════════════════════════ */
function loadTrafficClassification() {
    fetch(SN_API + '/traffic/classification?hours=24').then(r=>r.json()).then(d => {
        if (!d.success) return;
        const data = d.per_device || d.data || d.classification || [];
        // Aggregate chart
        const agg = {};
        data.forEach(r => { agg[r.category] = (agg[r.category]||0) + parseInt(r.query_count||r.queries||0); });
        const ctx = document.getElementById('traffic-class-chart');
        if (ctx && Object.keys(agg).length) {
            if (_trafficClassChart) _trafficClassChart.destroy();
            const sorted = Object.entries(agg).sort((a,b)=>b[1]-a[1]);
            _trafficClassChart = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: sorted.map(([c])=> (CAT_ICONS[c]||'') + ' ' + c),
                    datasets: [{data: sorted.map(([,v])=>v), backgroundColor: sorted.map(([c])=>CAT_COLORS[c]||'#555')}]
                },
                options: {
                    responsive:true, maintainAspectRatio:false,
                    plugins: {legend:{position:'right',labels:{color:'#ccc',font:{size:11}}}}
                }
            });
        }
        // Per-device table
        const devices = {};
        data.forEach(r => {
            const key = r.device_ip || 'unknown';
            if (!devices[key]) devices[key] = {total:0};
            devices[key][r.category] = (devices[key][r.category]||0) + parseInt(r.query_count||r.queries||0);
            devices[key].total += parseInt(r.query_count||r.queries||0);
        });
        const el = document.getElementById('traffic-class-table');
        const sortedDevs = Object.entries(devices).sort((a,b)=>b[1].total-a[1].total).slice(0,15);
        let html = '<table class="data-table"><thead><tr><th>Device</th><th>Top Category</th><th>Queries</th></tr></thead><tbody>';
        sortedDevs.forEach(([ip, dd]) => {
            const topCat = Object.entries(dd).filter(([k])=>k!=='total').sort((a,b)=>b[1]-a[1])[0];
            const catName = topCat ? topCat[0] : 'other';
            html += `<tr><td>${ip}</td><td><span style="color:${CAT_COLORS[catName]||'#888'}">${CAT_ICONS[catName]||''} ${catName}</span></td><td>${fmtNum(dd.total)}</td></tr>`;
        });
        html += '</tbody></table>';
        el.innerHTML = html;
    }).catch(() => {});
}

/* ═══════════════════════════════════════════════════════════════════
   DOMAIN INTELLIGENCE MODAL
   ═══════════════════════════════════════════════════════════════════ */
// Global state for domain intel modal
var _domainIntelAbort = null;
var _domainIntelLoading = false;

function openDomainIntel(domain) {
    // Cancel any in-flight investigation request
    if (_domainIntelAbort) { try { _domainIntelAbort.abort(); } catch(e){} }
    _domainIntelAbort = null;

    var existing = document.getElementById('domain-intel-overlay');
    if (existing) existing.remove();

    // Sanitize domain for display
    var safeDomain = domain.replace(/[<>&"']/g, '');

    var html =
      '<div class="bm-overlay active" id="domain-intel-overlay" style="--bm-accent:#00e5ff;--bm-accent-rgb:0,229,255">' +
        '<div class="bm-shell" style="max-width:640px">' +
          '<div class="bm-frame">' +
            '<div class="bm-frame-elbow-top"></div><div class="bm-frame-seg"></div>' +
            '<div class="bm-frame-seg dim"></div><div class="bm-frame-light on"></div>' +
            '<div class="bm-frame-light amber"></div><div class="bm-frame-seg purple"></div>' +
            '<div class="bm-frame-fill"></div><div class="bm-frame-elbow-bottom"></div>' +
          '</div>' +
          '<div class="bm-content">' +
            '<div class="bm-header">' +
              '<span class="bm-header-title">DOMAIN INTELLIGENCE</span>' +
              '<div class="bm-header-strip">' +
                '<div class="bm-header-pip w1"></div><div class="bm-header-pip w2"></div>' +
                '<div class="bm-header-pip w3"></div>' +
                '<button class="bm-close" onclick="document.getElementById(\'domain-intel-overlay\').remove()">&times;</button>' +
              '</div>' +
            '</div>' +
            '<div style="text-align:center;padding:12px 16px 4px;border-bottom:1px solid rgba(0,229,255,0.15)">' +
              '<div style="color:#fff;font-family:\'IBM Plex Mono\',monospace;font-size:1.2rem;font-weight:600">' + safeDomain + '</div>' +
            '</div>' +
            '<div class="bm-body" id="domain-intel-body" style="padding:16px;max-height:60vh;overflow-y:auto">' +
              '<div style="text-align:center;padding:30px;color:#94a3b8">Loading intelligence...</div>' +
            '</div>' +
            '<div class="bm-footer" id="domain-intel-footer" style="padding:12px 16px;display:flex;gap:8px;justify-content:flex-end">' +
              '<button class="btn" onclick="document.getElementById(\'domain-intel-overlay\').remove()" style="opacity:0.7">Close</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.insertAdjacentHTML('beforeend', html);
    var modal = document.getElementById('domain-intel-overlay');
    modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });

    var body = document.getElementById('domain-intel-body');
    fetch(SN_API + '/dns/domain-intel?domain=' + encodeURIComponent(domain))
        .then(function(r) { return r.json(); })
        .then(function(d) { if (!d.success) { body.textContent = 'Failed to load'; return; } _renderDomainIntel(body, d); })
        .catch(function(e) { body.textContent = 'Error: ' + e; });
}

function _renderDomainIntel(body, d) {
    body.textContent = '';
    var ag = d.adguard_status || {};
    var reason = ag.reason || '';
    var statusColor = '#10b981', statusText = 'Allowed';
    if (reason === 'FilteredBlackList' || reason === 'FilteredBlockedService') { statusColor = '#ef4444'; statusText = 'Blocked'; }
    else if (reason === 'Rewrite') { statusColor = '#00e5ff'; statusText = 'Rewritten'; }

    // Stats grid
    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px';
    [{val: fmtNum(d.total_queries||0), label: 'TOTAL QUERIES', color: '#00e5ff'},
     {val: fmtNum(d.blocked_queries||0), label: 'BLOCKED', color: '#ef4444'},
     {val: statusText, label: 'STATUS', color: statusColor}].forEach(function(s) {
        var card = document.createElement('div');
        card.style.cssText = 'background:rgba(255,255,255,0.04);padding:10px;border-radius:8px;text-align:center';
        var val = document.createElement('div');
        val.style.cssText = 'color:' + s.color + ';font-size:1.1rem;font-weight:700;font-family:Orbitron,sans-serif';
        val.textContent = s.val;
        var lbl = document.createElement('div');
        lbl.style.cssText = 'color:#888;font-size:0.7rem';
        lbl.textContent = s.label;
        card.appendChild(val); card.appendChild(lbl); grid.appendChild(card);
    });
    body.appendChild(grid);

    // Category + dates
    var meta = document.createElement('div');
    meta.style.cssText = 'display:flex;gap:16px;margin-bottom:16px;font-size:0.8rem;flex-wrap:wrap';
    var catSpan = document.createElement('span');
    catSpan.style.color = '#fbbf24';
    catSpan.textContent = 'Category: ' + (d.category || 'uncategorized');
    meta.appendChild(catSpan);
    if (d.first_seen) { var fs = document.createElement('span'); fs.style.color = '#888'; fs.textContent = 'First: ' + new Date(d.first_seen).toLocaleDateString(); meta.appendChild(fs); }
    if (d.last_seen) { var ls = document.createElement('span'); ls.style.color = '#888'; ls.textContent = 'Last: ' + new Date(d.last_seen).toLocaleDateString(); meta.appendChild(ls); }
    body.appendChild(meta);

    // Devices table
    if (d.devices && d.devices.length) {
        var devTitle = document.createElement('div');
        devTitle.style.cssText = 'color:#00e5ff;font-size:0.75rem;font-weight:600;margin-bottom:6px';
        devTitle.textContent = 'DEVICES QUERYING THIS DOMAIN';
        body.appendChild(devTitle);
        var table = document.createElement('table');
        table.className = 'data-table';
        table.style.fontSize = '0.78rem';
        table.style.marginBottom = '16px';
        var thead = document.createElement('thead');
        thead.appendChild(_tr(['Device','IP','Queries'], true));
        table.appendChild(thead);
        var tbody = document.createElement('tbody');
        d.devices.forEach(function(dev) { tbody.appendChild(_tr([dev.label||dev.ip, dev.ip, fmtNum(dev.queries)])); });
        table.appendChild(tbody);
        body.appendChild(table);
    }

    // AI Report section — always visible with predetermined area
    var aiSection = document.createElement('div');
    aiSection.style.cssText = 'border-top:1px solid rgba(139,92,246,0.3);padding-top:12px;margin-top:12px';
    var aiHeader = document.createElement('div');
    aiHeader.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px';
    var aiLabel = document.createElement('span');
    aiLabel.style.cssText = 'color:#8b5cf6;font-size:0.75rem;font-weight:700;letter-spacing:1px';
    aiLabel.textContent = 'AI SECURITY REPORT';
    var aiBtn = document.createElement('button');
    aiBtn.id = 'domain-investigate-btn';
    aiBtn.style.cssText = 'background:#8b5cf6;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.78rem;font-family:"IBM Plex Mono",monospace';
    aiBtn.textContent = 'Investigate';
    aiBtn.addEventListener('click', function() { investigateDomain(d.domain); });
    aiHeader.appendChild(aiLabel); aiHeader.appendChild(aiBtn);
    aiSection.appendChild(aiHeader);
    // Predetermined report box — always visible, show DB-persisted report if available
    var aiResult = document.createElement('div');
    aiResult.id = 'domain-investigate-result';
    if (d.last_report) {
        aiResult.style.cssText = 'background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.3);border-left:3px solid #8b5cf6;border-radius:8px;padding:16px;min-height:60px;color:#ccc;font-size:0.8rem;line-height:1.6;white-space:pre-wrap;font-style:normal';
        aiResult.textContent = d.last_report;
        var ageTag = document.createElement('div');
        ageTag.style.cssText = 'color:#94a3b8;font-size:0.65rem;margin-top:8px;font-style:italic';
        var ageText = 'Unknown age';
        if (d.report_age) {
            var ageMs = Date.now() - new Date(d.report_age).getTime();
            var ageMin = Math.round(ageMs / 60000);
            ageText = ageMin < 60 ? ageMin + ' min ago' : Math.round(ageMin / 60) + 'h ago';
        }
        ageTag.textContent = 'Investigated by ' + (d.report_by || 'AI Bridge') + ' — ' + ageText + ' — click Re-investigate for fresh analysis';
        aiResult.appendChild(ageTag);
        aiBtn.textContent = 'Re-investigate';
    } else {
        aiResult.style.cssText = 'background:rgba(139,92,246,0.06);border:1px dashed rgba(139,92,246,0.25);border-radius:8px;padding:16px;min-height:60px;color:#777;font-size:0.8rem;line-height:1.5;font-style:italic';
        aiResult.textContent = 'No report available. Click "Investigate" to request an AI security analysis of this domain.';
    }
    aiSection.appendChild(aiResult);
    body.appendChild(aiSection);

    // Quick actions — put in LCARS footer
    var footer = document.getElementById('domain-intel-footer');
    if (footer) {
        var closeBtn = footer.querySelector('.btn');
        [{label:'Block',color:'#ef4444',action:'block'},{label:'Unblock',color:'#10b981',action:'unblock'},{label:'Rewrite to Local',color:'#00e5ff',tcolor:'#000',action:'rewrite'}].forEach(function(a) {
            var btn = document.createElement('button');
            btn.style.cssText = 'background:'+a.color+';color:'+(a.tcolor||'#fff')+';border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:0.75rem';
            btn.textContent = a.label;
            btn.addEventListener('click', function() { dnsQuickAction(a.action, d.domain); });
            footer.insertBefore(btn, closeBtn);
        });
    }
}

function _tr(cells, isHeader) {
    var tr = document.createElement('tr');
    cells.forEach(function(c) { var td = document.createElement(isHeader ? 'th' : 'td'); td.textContent = c; tr.appendChild(td); });
    return tr;
}

function _setFooterButtonsState(disabled) {
    var footer = document.getElementById('domain-intel-footer');
    if (!footer) return;
    footer.querySelectorAll('button').forEach(function(b) {
        if (b.textContent !== 'Close') b.disabled = disabled;
        if (disabled) b.style.opacity = '0.5';
        else b.style.opacity = '1';
    });
}

var _investigateTimer = null;
function investigateDomain(domain) {
    if (_domainIntelLoading) return; // Prevent double-click
    _domainIntelLoading = true;

    // Cancel any previous in-flight request
    if (_domainIntelAbort) { try { _domainIntelAbort.abort(); } catch(e){} }
    _domainIntelAbort = new AbortController();
    if (_investigateTimer) { clearInterval(_investigateTimer); _investigateTimer = null; }

    var btn = document.getElementById('domain-investigate-btn');
    var result = document.getElementById('domain-investigate-result');
    if (btn) { btn.disabled = true; btn.textContent = 'Analyzing... 0s'; }
    _setFooterButtonsState(true);
    if (result) {
        result.style.cssText = 'background:rgba(139,92,246,0.06);border:1px solid rgba(139,92,246,0.3);border-radius:8px;padding:16px;min-height:60px;color:#8b5cf6;font-size:0.8rem;line-height:1.5;font-style:italic';
        result.textContent = 'AI is researching this domain... Please wait.';
    }

    // Elapsed timer on the button
    var startTime = Date.now();
    _investigateTimer = setInterval(function() {
        var elapsed = Math.round((Date.now() - startTime) / 1000);
        if (btn && btn.disabled) btn.textContent = 'Analyzing... ' + elapsed + 's';
    }, 1000);

    fetch(SN_API + '/dns/domain-investigate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({domain: domain}),
        signal: _domainIntelAbort.signal
    }).then(function(r) { return r.json(); }).then(function(d) {
        _domainIntelLoading = false;
        _domainIntelAbort = null;
        if (_investigateTimer) { clearInterval(_investigateTimer); _investigateTimer = null; }
        if (btn) { btn.disabled = false; btn.textContent = 'Re-investigate'; }
        _setFooterButtonsState(false);
        if (d.success && d.report) {
            result.style.cssText = 'background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.3);border-left:3px solid #8b5cf6;border-radius:8px;padding:16px;min-height:60px;color:#ccc;font-size:0.8rem;line-height:1.6;white-space:pre-wrap;font-style:normal';
            result.textContent = d.report;
        } else {
            result.style.cssText = 'background:rgba(249,115,22,0.06);border:1px dashed rgba(249,115,22,0.3);border-radius:8px;padding:16px;min-height:60px;color:#f97316;font-size:0.8rem;line-height:1.5;font-style:italic';
            result.textContent = (d.error || 'AI unavailable — try again later') + '\nTip: If a cached report was shown previously, it remains valid.';
        }
    }).catch(function(e) {
        _domainIntelLoading = false;
        _domainIntelAbort = null;
        if (_investigateTimer) { clearInterval(_investigateTimer); _investigateTimer = null; }
        if (e.name === 'AbortError') return; // Cancelled by new modal open — ignore
        if (btn) { btn.disabled = false; btn.textContent = 'Investigate'; }
        _setFooterButtonsState(false);
        if (result) {
            result.style.cssText = 'background:rgba(239,68,68,0.06);border:1px dashed rgba(239,68,68,0.3);border-radius:8px;padding:16px;min-height:60px;color:#ef4444;font-size:0.8rem;line-height:1.5;font-style:italic';
            result.textContent = 'Connection error — AI agents may be busy. Try again in a moment.';
        }
    });
}

var _quickActionBusy = false;
function dnsQuickAction(action, domain) {
    if (_quickActionBusy) return;
    _quickActionBusy = true;
    _setFooterButtonsState(true);

    var endpoint = action === 'block' ? '/dns/adguard/block' :
                   action === 'unblock' ? '/dns/adguard/unblock' :
                   '/dns/adguard/rewrites';
    var payload = action === 'rewrite' ?
        {domain: domain, answer: '192.168.1.200'} : {domain: domain};

    fetch(SN_API + endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    }).then(function(r) { return r.json(); }).then(function(d) {
        _quickActionBusy = false;
        if (d.success) {
            if (typeof showToast === 'function') showToast('success', domain + ' ' + action + 'ed');
            openDomainIntel(domain); // Refresh modal with updated status
        } else {
            _setFooterButtonsState(false);
            if (typeof showToast === 'function') showToast('error', d.error || 'Failed');
        }
    }).catch(function() {
        _quickActionBusy = false;
        _setFooterButtonsState(false);
    });
}

/* ═══════════════════════════════════════════════════════════════════
   TAB ACTIVATION HOOKS
   ═══════════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const tab = this.dataset.tab;
            if (tab === 'topology') loadTopology();
            if (tab === 'supervision') { loadSupervisionSchedules(); loadTrafficByUser(); loadBrainRotBoard(); }
            if (tab === 'intel') loadIntelTab();
            if (tab === 'dns') setTimeout(loadSinkholeStats, 300);
            if (tab === 'devices') setTimeout(loadTrafficClassification, 300);
        });
    });
});
