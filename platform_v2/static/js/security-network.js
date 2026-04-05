/* security-network.js — A.R.C.H.I.E. Security & Network Module */
/* globals: lucide, ArchieTime, qlOffset, activeScannerType, API */

var SN_API = '/tools/security-network/api';

/* ── Load-once flags ───────────────────────────────── */
var _nocLoaded = false;
var _trafficLoaded = false;
var dnsTabLoaded = false;
var _devicesLoaded = false;
var _defenseLoaded = false;
var survTabLoaded = false;
var reconTabLoaded = false;
var scanTabLoaded = false;
var domainsTabLoaded = false;

/* ── Poll timers ───────────────────────────────────── */
var _nocPollTimer = null;
var _trafficPollTimer = null;
var _activeTab = 'overview';

/* ═══════════════════════════════════════════════════
   UTILITIES
═══════════════════════════════════════════════════ */

function snApi(endpoint) {
    return fetch(SN_API + endpoint, { credentials: 'same-origin' }).then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    });
}

function snApiPost(endpoint, body) {
    return fetch(SN_API + endpoint, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
    }).then(function(r) { return r.json(); });
}

function snEsc(s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

function snSetText(id, text) {
    var e = typeof id === 'string' ? document.getElementById(id) : id;
    if (e) e.textContent = String(text == null ? '' : text);
}

function formatNum(n) {
    n = Number(n) || 0;
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
}

function formatBytes(bytes) {
    bytes = Number(bytes) || 0;
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' B';
}

function snFormatTime(t) {
    if (!t) return '-';
    if (typeof ArchieTime !== 'undefined') return ArchieTime.format(t, 'short');
    return String(t);
}

function setBadge(id, online) {
    var e = document.getElementById(id);
    if (e) e.className = 'svc-badge ' + (online ? 'online' : 'offline');
}

function showToast(type, msg) {
    var toast = document.createElement('div');
    toast.className = 'sn-toast sn-toast-' + type;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(function() { toast.classList.add('sn-toast-show'); }, 10);
    setTimeout(function() {
        toast.classList.remove('sn-toast-show');
        setTimeout(function() { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 300);
    }, 3500);
}

function snShowLoading(elOrId) {
    var el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
    if (!el) return;
    var d = document.createElement('div');
    d.className = 'loading-state';
    var sp = document.createElement('span');
    sp.className = 'spinner';
    d.appendChild(sp);
    d.appendChild(document.createTextNode(' Loading...'));
    el.textContent = '';
    el.appendChild(d);
}

function snShowEmpty(elOrId, msg) {
    var el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
    if (!el) return;
    var d = document.createElement('div');
    d.className = 'empty-state';
    d.textContent = msg || 'No data';
    el.textContent = '';
    el.appendChild(d);
}

function snRefreshIcons() {
    if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons();
}

function snBuildTable(headers, rows) {
    var table = document.createElement('table');
    table.className = 'data-table';
    var thead = document.createElement('thead');
    var headRow = document.createElement('tr');
    headers.forEach(function(h) {
        var th = document.createElement('th');
        th.textContent = h;
        headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = document.createElement('tbody');
    rows.forEach(function(row) {
        var tr = document.createElement('tr');
        row.forEach(function(cell) {
            var td = document.createElement('td');
            if (cell instanceof HTMLElement) {
                td.appendChild(cell);
            } else {
                td.textContent = cell == null ? '' : String(cell);
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    return table;
}

function snCreateBadge(text, type) {
    var span = document.createElement('span');
    span.className = 'badge badge-' + type;
    span.textContent = text;
    return span;
}

/* ═══════════════════════════════════════════════════
   TAB MANAGEMENT
═══════════════════════════════════════════════════ */

function switchSecurityTab(tabName) {
    /* stop existing polls */
    if (_nocPollTimer) { clearInterval(_nocPollTimer); _nocPollTimer = null; }
    if (_trafficPollTimer) { clearInterval(_trafficPollTimer); _trafficPollTimer = null; }
    if (typeof stopSurvAutoRefresh === 'function') stopSurvAutoRefresh();

    /* deactivate all */
    document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
    document.querySelectorAll('.tab-content').forEach(function(c) { c.classList.remove('active'); });

    /* activate selected */
    var btn = document.querySelector('.tab-btn[data-tab="' + tabName + '"]');
    var panel = document.getElementById('tab-' + tabName);
    if (btn) btn.classList.add('active');
    if (panel) panel.classList.add('active');
    _activeTab = tabName;

    /* scroll to top of tab content */
    if (panel) panel.scrollIntoView({ behavior: 'instant', block: 'start' });
    window.scrollTo(0, 0);

    /* load data for tab */
    switch (tabName) {
        case 'overview':
            loadNocOverview();
            _nocPollTimer = setInterval(loadNocOverview, 30000);
            break;
        case 'traffic':
            loadTraffic();
            _trafficPollTimer = setInterval(loadTraffic, 10000);
            break;
        case 'dns':
            if (!dnsTabLoaded) { dnsTabLoaded = true; loadDNSOverview(); loadUserRules(); }
            break;
        case 'devices':
            loadDevices();
            break;
        case 'defense':
            loadDefense();
            break;
        case 'scanners':
            if (!survTabLoaded) { survTabLoaded = true; }
            loadSurveillance();
            if (!reconTabLoaded) { reconTabLoaded = true; loadReconModules(); loadReconHistory(); }
            if (!scanTabLoaded) { scanTabLoaded = true; loadScanResults(); loadSSLMonitors(); }
            break;
        case 'compliance':
            onComplianceTabShown();
            break;
        case 'reports':
            loadReports();
            loadReportsList();
            break;
    }

    snRefreshIcons();
}

function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            switchSecurityTab(btn.dataset.tab);
        });
    });
}

function initSubtabs() {
    document.querySelectorAll('.subtab-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var parent = btn.closest('.tab-content');
            parent.querySelectorAll('.subtab-btn').forEach(function(b) { b.classList.remove('active'); });
            parent.querySelectorAll('.subtab-content').forEach(function(c) { c.classList.remove('active'); });
            btn.classList.add('active');
            var subtabEl = document.getElementById('subtab-' + btn.dataset.subtab);
            if (subtabEl) subtabEl.classList.add('active');
            var st = btn.dataset.subtab;
            if (st === 'dns-querylog') loadQueryLog(0);
            if (st === 'dns-filters') loadFilters();
            if (st === 'dns-rewrites') loadRewrites();
            if (st === 'dns-rules') loadUserRules();
            if (st === 'dns-clients') loadDeviceClients();
            if (st === 'domains-overview') loadDomainsOverview();
            if (st === 'domains-dns') loadDomainDnsRecords();
            if (st === 'domains-proxy') loadDomainProxyHosts();
            if (st === 'domains-certs') loadDomainCertificates();
            if (st === 'scanners-vuln') { if (!scanTabLoaded) { scanTabLoaded = true; loadScanResults(); loadSSLMonitors(); } }
            if (st === 'scanners-recon') { if (!reconTabLoaded) { reconTabLoaded = true; loadReconModules(); loadReconHistory(); } }
            if (st === 'scanners-surv') { loadSurveillance(); }
            snRefreshIcons();
        });
    });
}

function switchToTab(tabName) {
    switchSecurityTab(tabName);
}

/* ═══════════════════════════════════════════════════
   TAB 1: NOC OVERVIEW
═══════════════════════════════════════════════════ */

function loadNocOverview() {
    snApi('/noc/overview').then(function(d) {
        if (!d.success) return;

        /* hero stats */
        var stats = d.hero_stats || {};
        snSetText('noc-dns-queries', formatNum(stats.dns_queries_24h || 0));
        snSetText('noc-threats', formatNum(stats.threats_blocked_24h || 0));
        snSetText('noc-traffic', formatBytes(stats.traffic_bytes || 0));
        snSetText('noc-banned', formatNum(stats.currently_banned || 0));

        /* service badges in header */
        var svc = d.services || {};
        Object.keys(svc).forEach(function(k) {
            setBadge('svc-' + k, svc[k] && svc[k].status === 'online');
        });

        /* service health panel */
        _renderNocServiceHealth(svc);

        /* recent activity feed */
        _renderNocActivity(d.recent_activity || []);

    }).catch(function(e) {
        console.warn('NOC overview error:', e);
    });
}

function _renderNocServiceHealth(svc) {
    var container = document.getElementById('noc-service-health');
    if (!container) return;
    var services = [
        { key: 'adguard', label: 'AdGuard DNS' },
        { key: 'ntopng', label: 'ntopng Traffic' },
        { key: 'nagios', label: 'Nagios Monitor' },
        { key: 'fail2ban', label: 'fail2ban' },
        { key: 'ddns', label: 'DDNS' }
    ];
    container.textContent = '';
    services.forEach(function(s) {
        var info = svc[s.key] || {};
        var status = info.status || 'unknown';
        var row = document.createElement('div');
        row.className = 'sn-svc-row';

        var dot = document.createElement('span');
        dot.className = 'sn-svc-dot sn-svc-' + status;
        row.appendChild(dot);

        var label = document.createElement('span');
        label.className = 'sn-svc-label';
        label.textContent = s.label;
        row.appendChild(label);

        var statusSpan = document.createElement('span');
        statusSpan.className = 'badge badge-' + (status === 'online' ? 'success' : status === 'offline' ? 'danger' : 'secondary');
        statusSpan.textContent = status.toUpperCase();
        row.appendChild(statusSpan);

        container.appendChild(row);
    });
}

function _renderNocActivity(alerts) {
    var feed = document.getElementById('noc-activity-feed');
    if (!feed) return;
    feed.textContent = '';
    if (!alerts.length) {
        snShowEmpty(feed, 'No recent activity');
        return;
    }
    alerts.forEach(function(a) {
        /* Route returns: type (info/warning/error/alert), text, time (ISO string) */
        var t = a.type || a.severity || 'info';
        var cls = (t === 'error' || t === 'alert' || t === 'high') ? 'danger'
                : (t === 'warning' || t === 'medium') ? 'warning'
                : 'info';
        var item = document.createElement('div');
        item.className = 'sn-activity-item sn-activity-' + cls;

        var timeSpan = document.createElement('span');
        timeSpan.className = 'sn-activity-time';
        var rawTime = a.time || a.timestamp || '';
        timeSpan.textContent = rawTime ? snFormatTime(rawTime) : '';
        item.appendChild(timeSpan);

        var msgSpan = document.createElement('span');
        msgSpan.className = 'sn-activity-msg';
        msgSpan.textContent = a.text || a.message || a.msg || '';
        item.appendChild(msgSpan);

        feed.appendChild(item);
    });
}

/* ═══════════════════════════════════════════════════
   TAB 2: TRAFFIC
═══════════════════════════════════════════════════ */

function loadTraffic() {
    /* Per-client activity from AdGuard DNS — primary data source */
    snApi('/traffic/activity?limit=5000').then(function(d) {
        if (!d.success) return;
        var clients = d.clients || [];
        _renderClientActivity(clients);
        _renderServiceBreakdown(clients);

        /* Update hero stats from activity data */
        var totalQueries = 0, totalBlocked = 0;
        clients.forEach(function(c) { totalQueries += c.total_queries || 0; totalBlocked += c.blocked || 0; });
        snSetText('traffic-bytes-in', formatNum(totalQueries) + ' queries');
        snSetText('traffic-bytes-out', formatNum(totalBlocked) + ' blocked');
        snSetText('traffic-pkts', formatNum(clients.length));
        snSetText('traffic-iface', d.query_count + ' log entries');

        /* Render bandwidth bar as queries vs blocked */
        var total = totalQueries || 1;
        var pctClean = Math.round((totalQueries - totalBlocked) / total * 100);
        _renderBandwidthBar({ bytes_rcvd: totalQueries - totalBlocked, bytes_sent: totalBlocked, _labelIn: 'Clean: ' + formatNum(totalQueries - totalBlocked), _labelOut: 'Blocked: ' + formatNum(totalBlocked) });
    }).catch(function(e) {
        snShowEmpty(document.getElementById('traffic-hosts-table'), 'Failed to load activity');
    });
}

function _renderClientActivity(clients) {
    var container = document.getElementById('traffic-hosts-table');
    if (!container || !clients.length) return;
    container.textContent = '';

    var rows = clients.map(function(c) {
        var svcs = Object.keys(c.services || {}).sort(function(a, b) {
            return (c.services[b] || 0) - (c.services[a] || 0);
        }).slice(0, 4);
        var svcText = svcs.length ? svcs.join(', ') : 'general';
        var svcBadges = document.createElement('span');
        svcs.forEach(function(s) {
            var b = document.createElement('span');
            b.textContent = s;
            b.className = 'badge badge-info';
            b.style.cssText = 'margin-right:4px;font-size:0.7rem;';
            svcBadges.appendChild(b);
        });
        if (!svcs.length) { svcBadges.textContent = 'general'; svcBadges.style.color = '#666'; }
        return [c.ip, formatNum(c.total_queries), formatNum(c.blocked), svcBadges];
    });

    var headers = ['Client IP', 'DNS Queries', 'Blocked', 'Services Detected'];
    container.appendChild(snBuildTable(headers, rows));
}

function _renderServiceBreakdown(clients) {
    var container = document.getElementById('traffic-protocols');
    if (!container) return;
    container.textContent = '';

    /* Aggregate services across all clients */
    var totals = {};
    clients.forEach(function(c) {
        Object.keys(c.services || {}).forEach(function(s) {
            totals[s] = (totals[s] || 0) + c.services[s];
        });
    });

    var sorted = Object.entries(totals).sort(function(a, b) { return b[1] - a[1]; });
    if (!sorted.length) { snShowEmpty(container, 'No service activity detected'); return; }

    var maxVal = sorted[0][1] || 1;
    sorted.slice(0, 15).forEach(function(pair) {
        var name = pair[0], count = pair[1];
        var pct = Math.round(count / maxVal * 100);
        var row = document.createElement('div');
        row.className = 'sn-proto-row';

        var label = document.createElement('span');
        label.className = 'sn-proto-name';
        label.textContent = name;
        row.appendChild(label);

        var track = document.createElement('div');
        track.className = 'sn-proto-track';
        var fill = document.createElement('div');
        fill.className = 'sn-proto-fill';
        fill.style.width = pct + '%';
        if (name === 'Porn') fill.style.background = '#ef4444';
        track.appendChild(fill);
        row.appendChild(track);

        var val = document.createElement('span');
        val.className = 'sn-proto-val';
        val.textContent = formatNum(count);
        row.appendChild(val);

        container.appendChild(row);
    });
}

function _renderBandwidthBar(bw) {
    var bar = document.getElementById('traffic-bw-bar');
    if (!bar) return;
    bar.textContent = '';

    var labelRow = document.createElement('div');
    labelRow.className = 'sn-bw-label';
    var inLabel = document.createElement('span');
    inLabel.textContent = bw._labelIn || ('IN: ' + formatBytes(bw.bytes_rcvd || 0));
    var outLabel = document.createElement('span');
    outLabel.textContent = bw._labelOut || ('OUT: ' + formatBytes(bw.bytes_sent || 0));
    labelRow.appendChild(inLabel);
    labelRow.appendChild(outLabel);
    bar.appendChild(labelRow);

    var total = (bw.bytes_rcvd || 0) + (bw.bytes_sent || 0);
    var pctIn = total > 0 ? Math.round((bw.bytes_rcvd || 0) / total * 100) : 50;
    var track = document.createElement('div');
    track.className = 'sn-bw-track';
    var fill = document.createElement('div');
    fill.className = 'sn-bw-fill-in';
    fill.style.width = pctIn + '%';
    track.appendChild(fill);
    bar.appendChild(track);
}

function _renderProtocolBreakdown(protocols) {
    var container = document.getElementById('traffic-protocols');
    if (!container) return;
    if (!protocols.length) { snShowEmpty(container, 'No protocol data'); return; }
    container.textContent = '';
    var top = protocols.slice(0, 10);
    var maxBytes = Math.max.apply(null, top.map(function(p) { return p.bytes || 0; })) || 1;
    top.forEach(function(p) {
        var pct = Math.round((p.bytes || 0) / maxBytes * 100);
        var row = document.createElement('div');
        row.className = 'sn-proto-row';

        var name = document.createElement('span');
        name.className = 'sn-proto-name';
        name.textContent = p.name || p.proto_name || p.id || '-';
        row.appendChild(name);

        var track = document.createElement('div');
        track.className = 'sn-proto-bar-track';
        var fillEl = document.createElement('div');
        fillEl.className = 'sn-proto-bar-fill';
        fillEl.style.width = pct + '%';
        track.appendChild(fillEl);
        row.appendChild(track);

        var val = document.createElement('span');
        val.className = 'sn-proto-val';
        val.textContent = formatBytes(p.bytes || 0);
        row.appendChild(val);

        container.appendChild(row);
    });
}

/* ═══════════════════════════════════════════════════
   TAB 4: DEVICES
═══════════════════════════════════════════════════ */

function loadDevices() {
    snApi('/devices/users').then(function(d) {
        var container = document.getElementById('devices-users-table');
        if (!container) return;
        var users = d.users || d.mappings || [];
        if (!users.length) { snShowEmpty(container, 'No device mappings'); return; }
        var rows = users.map(function(u) {
            var delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger btn-sm';
            delBtn.textContent = 'Remove';
            (function(uid) {
                delBtn.addEventListener('click', function() { deleteDeviceMapping(uid); });
            }(u.id));
            return [u.mac || '-', u.ip || '-', u.username || '-', u.device_name || '-', delBtn];
        });
        container.textContent = '';
        container.appendChild(snBuildTable(['MAC', 'IP', 'Username', 'Device Name', ''], rows));
    }).catch(function() { snShowEmpty('devices-users-table', 'Error loading device mappings'); });

    snApi('/devices/consumption').then(function(d) {
        var container = document.getElementById('devices-consumption-table');
        if (!container) return;
        var items = d.consumption || d.devices || [];
        if (!items.length) { snShowEmpty(container, 'No consumption data'); return; }
        var rows = items.slice(0, 20).map(function(item) {
            return [item.mac || '-', item.ip || '-', item.hostname || '-', formatBytes(item.bytes_sent || 0), formatBytes(item.bytes_rcvd || 0), snFormatTime(item.last_seen)];
        });
        container.textContent = '';
        container.appendChild(snBuildTable(['MAC', 'IP', 'Hostname', 'Sent', 'Rcvd', 'Last Seen'], rows));
    }).catch(function() { snShowEmpty('devices-consumption-table', 'Error loading consumption data'); });
}

function addDeviceMapping() {
    var mac = document.getElementById('device-mac').value.trim();
    var ip = document.getElementById('device-ip').value.trim();
    var username = document.getElementById('device-username').value.trim();
    var deviceName = document.getElementById('device-name').value.trim();
    if (!mac || !username) { showToast('error', 'MAC address and username are required'); return; }
    snApiPost('/devices/users', { mac: mac, ip: ip, username: username, device_name: deviceName })
        .then(function(d) {
            if (d.success) {
                showToast('success', 'Device mapping added');
                ['device-mac', 'device-ip', 'device-username', 'device-name'].forEach(function(id) {
                    var el = document.getElementById(id);
                    if (el) el.value = '';
                });
                loadDevices();
            } else {
                showToast('error', d.error || 'Failed to add mapping');
            }
        }).catch(function(e) { showToast('error', e.message); });
}

function deleteDeviceMapping(id) {
    if (!confirm('Remove this device mapping?')) return;
    fetch(SN_API + '/devices/users/' + id, { method: 'DELETE', credentials: 'same-origin' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.success) { showToast('success', 'Mapping removed'); loadDevices(); }
            else showToast('error', d.error || 'Failed');
        }).catch(function(e) { showToast('error', e.message); });
}

/* ═══════════════════════════════════════════════════
   TAB 5: DEFENSE
═══════════════════════════════════════════════════ */

function loadDefense() {
    loadFail2banJails();
    loadDdnsStatus();
    loadFirewall();
    loadIPAccess();
    loadAutoBlockSettings();
    loadSecurityEvents();
    loadConnections();
}

function loadFail2banJails() {
    snApi('/fail2ban/jails').then(function(d) {
        var container = document.getElementById('defense-fail2ban-jails');
        if (!container) return;
        var jails = d.jails || [];
        if (!jails.length) { snShowEmpty(container, 'No jails data'); return; }
        container.textContent = '';
        jails.forEach(function(j) {
            var online = j.status === 'active' || j.active;
            var row = document.createElement('div');
            row.className = 'sn-jail-row';

            var name = document.createElement('span');
            name.className = 'sn-jail-name';
            name.textContent = j.name || j.jail_name || '-';
            row.appendChild(name);

            var stat1 = document.createElement('span');
            stat1.className = 'sn-jail-stat';
            stat1.textContent = 'Banned: ' + (j.currently_banned || 0);
            row.appendChild(stat1);

            var stat2 = document.createElement('span');
            stat2.className = 'sn-jail-stat';
            stat2.textContent = 'Total: ' + (j.total_banned || 0);
            row.appendChild(stat2);

            var badge = snCreateBadge(online ? 'ACTIVE' : 'INACTIVE', online ? 'success' : 'danger');
            row.appendChild(badge);

            container.appendChild(row);
        });
    }).catch(function() { snShowEmpty('defense-fail2ban-jails', 'fail2ban unavailable'); });
}

function loadDdnsStatus() {
    snApi('/ddns/status').then(function(d) {
        var container = document.getElementById('defense-ddns-status');
        if (!container) return;
        var status = d.status || d;
        var isActive = !!(status.stored_ip || status.script_exists);
        container.textContent = '';

        var rows = [
            ['Status', isActive ? 'ACTIVE' : 'DISABLED', isActive ? 'success' : 'secondary'],
            ['Public IP', d.live_ip || status.stored_ip || '-', null],
            ['Stored IP', status.stored_ip || '-', null],
            ['IP Match', (d.live_ip === status.stored_ip) ? 'YES' : 'CHANGED', (d.live_ip === status.stored_ip) ? 'success' : 'warning'],
            ['Last Updated', snFormatTime(status.last_updated), null]
        ];
        rows.forEach(function(r) {
            var row = document.createElement('div');
            row.className = 'sn-ddns-row';
            var label = document.createElement('span');
            label.textContent = r[0];
            row.appendChild(label);
            if (r[2]) {
                var badge = snCreateBadge(r[1], r[2]);
                row.appendChild(badge);
            } else {
                var val = document.createElement('span');
                val.textContent = r[1];
                row.appendChild(val);
            }
            container.appendChild(row);
        });
        setBadge('svc-ddns', isActive);
    }).catch(function() { snShowEmpty('defense-ddns-status', 'DDNS unavailable'); });
}

function triggerDdnsUpdate() {
    snApiPost('/ddns/update', {})
        .then(function(d) {
            if (d.success) { showToast('success', 'DDNS update triggered'); setTimeout(loadDdnsStatus, 2000); }
            else showToast('error', d.error || 'Failed');
        }).catch(function(e) { showToast('error', e.message); });
}

/* ═══════════════════════════════════════════════════
   TAB 8: REPORTS
═══════════════════════════════════════════════════ */

function loadReportsList() {
    var container = document.getElementById('sn-reports-list');
    if (!container) return;
    snShowLoading(container);
    snApi('/reports/list').then(function(d) {
        var reports = d.reports || [];
        if (!reports.length) { snShowEmpty(container, 'No reports yet'); return; }
        var rows = reports.map(function(r) {
            var viewBtn = document.createElement('button');
            viewBtn.className = 'btn btn-sm';
            viewBtn.textContent = 'View';
            (function(rid) {
                viewBtn.addEventListener('click', function() { viewSnReport(rid); });
            }(r.id));
            return ['#' + (r.id || '-'), r.report_type || r.type || '-', r.report_date || r.date || '-', snFormatTime(r.generated_at || r.created_at), viewBtn];
        });
        container.textContent = '';
        container.appendChild(snBuildTable(['ID', 'Type', 'Date', 'Generated', ''], rows));
    }).catch(function() { snShowEmpty(container, 'Error loading reports'); });
}

function viewSnReport(reportId) {
    snApi('/reports/' + reportId).then(function(d) {
        if (!d.success) { showToast('error', d.error || 'Report not found'); return; }
        var report = d.report || {};
        var modal = document.getElementById('modal-content');
        if (!modal) return;
        modal.textContent = '';

        var header = document.createElement('div');
        header.className = 'modal-header';
        var h3 = document.createElement('h3');
        h3.textContent = 'Report #' + reportId + ' — ' + (report.report_type || '');
        var closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-sm';
        closeBtn.textContent = 'Close';
        closeBtn.addEventListener('click', closeModal);
        header.appendChild(h3);
        header.appendChild(closeBtn);
        modal.appendChild(header);

        var body = document.createElement('div');
        body.style.cssText = 'max-height:60vh;overflow-y:auto;padding:16px;';
        var pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.8rem;white-space:pre-wrap;';
        pre.textContent = JSON.stringify(report.data || report, null, 2);
        body.appendChild(pre);
        modal.appendChild(body);

        document.getElementById('modal-overlay').classList.add('open');
    }).catch(function(e) { showToast('error', e.message); });
}

function generateDailyReport(type) {
    var btn = document.getElementById('btn-gen-' + type);
    if (btn) btn.textContent = 'Generating...';
    snApiPost('/reports/generate', { type: type })
        .then(function(d) {
            var label = type === 'daily_device' ? 'Device Report' : 'User Report';
            if (btn) btn.textContent = 'Generate ' + label;
            if (d.success) { showToast('success', 'Report generated'); loadReportsList(); }
            else showToast('error', d.error || 'Failed');
        }).catch(function(e) {
            if (btn) btn.textContent = 'Generate';
            showToast('error', e.message);
        });
}

/* ═══════════════════════════════════════════════════
   MODAL HELPERS
═══════════════════════════════════════════════════ */

function closeModal() {
    var o = document.getElementById('modal-overlay');
    if (o) o.classList.remove('open');
}

/* ═══════════════════════════════════════════════════
   INIT
═══════════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', function() {
    initTabs();
    initSubtabs();
    switchSecurityTab('overview');
    snRefreshIcons();
});
