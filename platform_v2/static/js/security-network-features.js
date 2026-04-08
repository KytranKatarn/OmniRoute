/**
 * security-network-features.js
 * Powers all 15 new features: Topology, Parental, Intel, Speed Test, etc.
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
        renderTopologyGraph(d.nodes || [], d.links || []);
    }).catch(e => console.error('Topology load error:', e));
}

function renderTopologyGraph(nodes, links) {
    const svg = d3.select('#topo-svg');
    svg.selectAll('*').remove();
    const container = document.getElementById('topology-graph');
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    svg.attr('viewBox', `0 0 ${w} ${h}`);

    const typeColor = {gateway:'#ef4444', hub:'#00e5ff', phone:'#10b981', computer:'#8b5cf6',
        laptop:'#8b5cf6', tablet:'#a78bfa', smart_tv:'#f472b6', camera:'#f59e0b', server:'#00e5ff'};

    const sizeScale = d3.scaleSqrt().domain([0, d3.max(nodes, n=>n.bytes_total||1)]).range([6, 30]);

    const sim = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(n=>n.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(w/2, h/2))
        .force('collision', d3.forceCollide().radius(n => sizeScale(n.bytes_total||0) + 5));

    const link = svg.append('g').selectAll('line').data(links).join('line')
        .attr('stroke', '#334155').attr('stroke-width', 1.5)
        .attr('stroke-opacity', l => Math.min(0.8, 0.1 + (l.bytes||0) / (d3.max(links, x=>x.bytes)||1) * 0.7));

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
   2. PARENTAL CONTROLS
   ═══════════════════════════════════════════════════════════════════ */
function loadParentalSchedules() {
    const el = document.getElementById('parental-schedules');
    el.innerHTML = '<div class="loading-state"><span class="spinner"></span> Loading...</div>';
    fetch(SN_API + '/parental/schedules').then(r=>r.json()).then(d => {
        if (!d.success || !d.schedules || d.schedules.length === 0) {
            el.innerHTML = '<div class="empty-state">No parental schedules configured. Click "Add Schedule" to create one.</div>';
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
            <h3 style="margin:0 0 16px;color:#00e5ff">Add Parental Schedule</h3>
            <div style="margin-bottom:12px">
                <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">User Name</label>
                <input type="text" id="ps-user" class="form-input" placeholder="e.g. Kids" style="width:100%">
            </div>
            <div style="margin-bottom:12px">
                <label style="display:block;font-size:0.75rem;color:#888;margin-bottom:4px">Device MAC</label>
                <input type="text" id="ps-mac" class="form-input" placeholder="AA:BB:CC:DD:EE:FF" style="width:100%">
            </div>
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
    fetch(SN_API + '/parental/schedules', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})
        .then(r=>r.json()).then(d => {
            document.getElementById('modal-overlay').style.display = 'none';
            if (d.success) loadParentalSchedules();
            else alert('Error: ' + (d.error||'Unknown'));
        });
}

function deleteSchedule(id) {
    if (!confirm('Delete this schedule?')) return;
    fetch(SN_API + '/parental/schedules/' + id, {method:'DELETE'}).then(r=>r.json()).then(() => loadParentalSchedules());
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
            cats.forEach(c => { html += `<td>${fmtNum(data[c]||0)}</td>`; });
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

/* ═══════════════════════════════════════════════════════════════════
   3. THREAT INTELLIGENCE
   ═══════════════════════════════════════════════════════════════════ */
function loadIntelTab() {
    loadThreatFeeds(); loadThreatHits(); loadIncidents();
    loadSpeedHistory(); loadHoneypotEvents(); loadWeeklyReport();
}

function loadThreatFeeds() {
    fetch(SN_API + '/threat-intel/status').then(r=>r.json()).then(d => {
        if (!d.success) return;
        const el = document.getElementById('intel-feeds');
        const feeds = d.feeds || d.status || {};
        let total = 0;
        let html = '<div style="display:flex;gap:12px;flex-wrap:wrap;padding:8px">';
        Object.entries(feeds).forEach(([name, info]) => {
            const cnt = info.count || 0;
            total += cnt;
            const updated = info.last_updated ? new Date(info.last_updated).toLocaleString() : 'Never';
            const dot = cnt > 0 ? '#22c55e' : '#f59e0b';
            html += `<div style="flex:1;min-width:200px;background:rgba(255,255,255,0.03);border-radius:8px;padding:12px;border:1px solid #333">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
                    <span style="width:8px;height:8px;border-radius:50%;background:${dot}"></span>
                    <strong style="color:#ccc">${name}</strong>
                </div>
                <div style="font-size:0.8rem;color:#888">${fmtNum(cnt)} IOCs</div>
                <div style="font-size:0.7rem;color:#666">Updated: ${updated}</div>
            </div>`;
        });
        html += '</div>';
        el.innerHTML = html;
        document.getElementById('intel-ioc-count').textContent = fmtNum(total);
    }).catch(() => {});
}

function syncThreatIntel() {
    const el = document.getElementById('intel-feeds');
    el.innerHTML = '<div class="loading-state"><span class="spinner"></span> Syncing feeds...</div>';
    fetch(SN_API + '/threat-intel/sync', {method:'POST'}).then(r=>r.json()).then(d => {
        loadThreatFeeds(); loadThreatHits();
    }).catch(() => { el.innerHTML = '<div class="empty-state">Sync failed</div>'; });
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
                    plugins: {legend:{position:'right',labels:{color:'#ccc',font:{size:11}}}}
                }
            });
        }
        // Top blocked domains table
        const domains = d.top_blocked || d.domains || [];
        const el = document.getElementById('sinkhole-table');
        if (domains.length) {
            let html = '<table class="data-table"><thead><tr><th>Domain</th><th>Blocked</th></tr></thead><tbody>';
            domains.slice(0,15).forEach(dd => { html += `<tr><td>${dd.domain}</td><td>${fmtNum(dd.block_count||dd.count||dd.queries)}</td></tr>`; });
            html += '</tbody></table>';
            el.innerHTML = html;
        } else {
            el.innerHTML = '<div class="empty-state">No blocked domains</div>';
        }
    }).catch(() => {});
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
   TAB ACTIVATION HOOKS
   ═══════════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const tab = this.dataset.tab;
            if (tab === 'topology') loadTopology();
            if (tab === 'parental') { loadParentalSchedules(); loadTrafficByUser(); loadBrainRotBoard(); }
            if (tab === 'intel') loadIntelTab();
            if (tab === 'dns') setTimeout(loadSinkholeStats, 300);
            if (tab === 'devices') setTimeout(loadTrafficClassification, 300);
        });
    });
});
