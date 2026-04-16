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
            if (typeof loadVpnDetect === 'function') setTimeout(loadVpnDetect, 1000);
            _trafficPollTimer = setInterval(loadTraffic, 10000);
            break;
        case 'dns':
            if (!dnsTabLoaded) { dnsTabLoaded = true; loadDNSOverview(); loadUserRules(); }
            if (typeof loadSinkholeStats === 'function') setTimeout(loadSinkholeStats, 300);
            if (typeof loadDnsTrend === 'function') setTimeout(loadDnsTrend, 500);
            break;
        case 'devices':
            loadDevices();
            loadNetworkMonitor();
            if (typeof loadTrafficClassification === 'function') setTimeout(loadTrafficClassification, 300);
            break;
        case 'defense':
            loadDefense();
            break;
        case 'scanners':
            if (!survTabLoaded) { survTabLoaded = true; }
            loadSurveillance();
            if (!reconTabLoaded) { reconTabLoaded = true; loadReconModules(); loadReconHistory(); }
            if (!scanTabLoaded) { scanTabLoaded = true; loadScannerCards(); loadScanHistory(); loadSSLMonitors(); loadCampaigns(); }
            break;
        case 'compliance':
            onComplianceTabShown();
            break;
        case 'reports':
            loadReports();
            loadReportsList();
            if (typeof loadDnsStats === 'function') loadDnsStats();
            break;
        case 'topology':
            if (typeof loadTopology === 'function') loadTopology();
            break;
        case 'supervision':
            if (typeof loadSupervisionSchedules === 'function') loadSupervisionSchedules();
            if (typeof loadTrafficByUser === 'function') loadTrafficByUser();
            if (typeof loadBrainRotBoard === 'function') loadBrainRotBoard();
            if (typeof loadDeviceActivity === 'function') loadDeviceActivity();
            break;
        case 'intel':
            if (typeof loadIntelTab === 'function') loadIntelTab();
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

    // Bridge LCARS header tabs → module switchSecurityTab
    window.onLcarsTabSwitch = function(tabId) { switchSecurityTab(tabId); };
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
            if (st === 'scanners-vuln') { if (!scanTabLoaded) { scanTabLoaded = true; loadScannerCards(); loadScanHistory(); loadSSLMonitors(); loadCampaigns(); } }
            if (st === 'scanners-recon') { if (!reconTabLoaded) { reconTabLoaded = true; loadReconModules(); loadReconHistory(); } }
            if (st === 'scanners-surv') { loadSurveillance(); }
            if (st === 'scanners-monitor') { if (typeof loadNagiosData === 'function' && !nagiosLoaded) loadNagiosData(); }
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
        snSetText('noc-active-devices', formatNum(stats.active_devices || 0));

        /* DNS protection indicator */
        var shieldEl = document.getElementById('noc-dns-shield');
        if (shieldEl) {
            var dot = document.createElement('span');
            dot.textContent = stats.dns_protection_on ? '\u25CF ON' : '\u25CF OFF';
            dot.style.color = stats.dns_protection_on ? '#22c55e' : '#ef4444';
            shieldEl.textContent = '';
            shieldEl.appendChild(dot);
        }

        /* last scan */
        var scan = d.last_scan;
        if (scan) {
            var scanTime = scan.time ? new Date(scan.time) : null;
            var scanAgo = scanTime ? _timeAgo(scanTime) : '';
            snSetText('noc-last-scan', scan.module + ' \u2014 ' + scan.status);
            var scanCard = document.getElementById('noc-last-scan-card');
            if (scanCard) {
                var lbl = scanCard.querySelector('.noc-hero-label');
                if (lbl) lbl.textContent = 'Last Scan' + (scanAgo ? ' (' + scanAgo + ')' : '');
            }
        }

        /* top bandwidth consumers */
        _renderTopConsumers(d.top_consumers || []);

        /* traffic sparkline */
        _renderSparkline(d.traffic_sparkline || []);

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

    /* compliance summary panel */
    snApi('/compliance/scores').then(function(cd) {
        if (!cd || !cd.success) return;
        var score = cd.score || 0;
        var scoreEl = document.getElementById('compliance-dash-score');
        if (scoreEl) {
            scoreEl.textContent = score.toFixed(1) + '%';
            scoreEl.style.color = score >= 80 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444';
        }
        var grade = score >= 95 ? 'A+' : score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 70 ? 'C' : 'F';
        snSetText('compliance-dash-grade', grade);
        var packs = cd.packs || {};
        ['ubuntu', 'docker', 'network'].forEach(function(p) {
            var el = document.getElementById('compliance-dash-' + p);
            if (el && packs[p] !== undefined) {
                var ps = packs[p];
                el.textContent = ps.toFixed(0) + '%';
                el.style.color = ps >= 80 ? '#22c55e' : ps >= 50 ? '#f59e0b' : '#ef4444';
            }
        });
        if (cd.last_scan) {
            snSetText('compliance-dash-time', formatTime(cd.last_scan));
        }
    }).catch(function(e) {
        console.debug('Compliance panel error:', e);
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

function _timeAgo(date) {
    var seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return 'just now';
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + 'm ago';
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + 'h ago';
    var days = Math.floor(hours / 24);
    return days + 'd ago';
}

function _renderTopConsumers(consumers) {
    var el = document.getElementById('noc-top-consumers');
    if (!el) return;
    el.textContent = '';
    if (!consumers.length) {
        snShowEmpty(el, 'No traffic data yet');
        return;
    }
    var maxBytes = consumers[0].bytes || 1;
    consumers.forEach(function(c) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px';

        var label = document.createElement('span');
        label.style.cssText = 'min-width:100px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--archie-text)';
        label.textContent = c.label || c.ip;
        label.title = c.ip;
        row.appendChild(label);

        var barOuter = document.createElement('div');
        barOuter.style.cssText = 'flex:1;height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden';
        var barInner = document.createElement('div');
        var pct = Math.max(2, (c.bytes / maxBytes) * 100);
        barInner.style.cssText = 'height:100%;border-radius:3px;background:linear-gradient(90deg,#00e5ff,#8b5cf6);width:' + pct + '%';
        barOuter.appendChild(barInner);
        row.appendChild(barOuter);

        var val = document.createElement('span');
        val.style.cssText = 'min-width:60px;text-align:right;color:var(--archie-text-muted);font-family:"IBM Plex Mono",monospace;font-size:0.75rem';
        val.textContent = formatBytes(c.bytes || 0);
        row.appendChild(val);

        el.appendChild(row);
    });
}

function _renderSparkline(data) {
    var svg = document.getElementById('noc-sparkline');
    if (!svg || !data.length) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    var w = svg.clientWidth || 300;
    var h = svg.clientHeight || 80;
    var max = Math.max.apply(null, data.map(function(d) { return d.bytes; })) || 1;
    var step = w / Math.max(data.length - 1, 1);

    var points = data.map(function(d, i) {
        var x = i * step;
        var y = h - (d.bytes / max) * (h - 4) - 2;
        return x.toFixed(1) + ',' + y.toFixed(1);
    });

    // Gradient definition
    var ns = 'http://www.w3.org/2000/svg';
    var defs = document.createElementNS(ns, 'defs');
    var grad = document.createElementNS(ns, 'linearGradient');
    grad.setAttribute('id', 'spark-grad');
    grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0');
    grad.setAttribute('x2', '0'); grad.setAttribute('y2', '1');
    var s1 = document.createElementNS(ns, 'stop');
    s1.setAttribute('offset', '0%'); s1.setAttribute('stop-color', '#00e5ff'); s1.setAttribute('stop-opacity', '0.3');
    var s2 = document.createElementNS(ns, 'stop');
    s2.setAttribute('offset', '100%'); s2.setAttribute('stop-color', '#00e5ff'); s2.setAttribute('stop-opacity', '0.02');
    grad.appendChild(s1); grad.appendChild(s2);
    defs.appendChild(grad);
    svg.appendChild(defs);

    // Fill area
    var area = document.createElementNS(ns, 'polygon');
    var areaPoints = '0,' + h + ' ' + points.join(' ') + ' ' + ((data.length - 1) * step).toFixed(1) + ',' + h;
    area.setAttribute('points', areaPoints);
    area.setAttribute('fill', 'url(#spark-grad)');
    svg.appendChild(area);

    // Line
    var line = document.createElementNS(ns, 'polyline');
    line.setAttribute('points', points.join(' '));
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', '#00e5ff');
    line.setAttribute('stroke-width', '2');
    line.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(line);
}

/* ═══════════════════════════════════════════════════
   TAB 2: TRAFFIC
═══════════════════════════════════════════════════ */

function loadTraffic() {
    /* Real bandwidth data from ntopng + DB */
    var sel = document.getElementById('traffic-period-select');
    // Restore saved period on first load
    if (sel && !sel._restored) {
        var saved = localStorage.getItem('sn_traffic_period');
        if (saved && sel.querySelector('option[value="' + saved + '"]')) sel.value = saved;
        sel._restored = true;
    }
    var period = sel ? sel.value : '24h';
    // Save selection
    if (sel) localStorage.setItem('sn_traffic_period', period);
    var periodLabels = {'24h': '24h', '7d': '7 Days', '30d': '30 Days', '90d': '90 Days', 'all': 'All Time'};
    var lbl = periodLabels[period] || period;

    // Update all period labels in the UI
    ['traffic-period-label-dl','traffic-period-label-up','traffic-period-label-hist','traffic-period-label-dev'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.textContent = lbl;
    });

    snApi('/noc/traffic-tab?period=' + period).then(function(d) {
        if (!d.success) return;

        /* Hero stats — actual bytes */
        snSetText('traffic-bytes-in', formatBytes(d.bytes_in || 0));
        snSetText('traffic-bytes-out', formatBytes(d.bytes_out || 0));
        snSetText('traffic-flows', formatNum(d.active_flows || 0));
        snSetText('traffic-devices', formatNum(d.active_devices || 0));

        /* Bandwidth bar — real in/out */
        _renderBandwidthBar({
            bytes_rcvd: d.bytes_in || 0,
            bytes_sent: d.bytes_out || 0,
            _labelIn: 'Download: ' + formatBytes(d.bytes_in || 0),
            _labelOut: 'Upload: ' + formatBytes(d.bytes_out || 0)
        });

        /* Per-device bandwidth table */
        _renderPerDeviceBandwidth(d.per_device || []);

        /* Traffic history chart */
        _renderTrafficHistory(d.hourly || []);

    }).catch(function(e) {
        console.warn('Traffic tab bandwidth error:', e);
    });

    /* DNS activity (secondary) */
    snApi('/traffic/activity?limit=5000').then(function(d) {
        if (!d.success) return;
        _renderClientActivity(d.clients || []);
    }).catch(function(e) {
        snShowEmpty(document.getElementById('traffic-hosts-table'), 'No DNS activity data');
    });

    /* L7 Protocol breakdown from ntopng (replaces DNS-based service detection) */
    snApi('/noc/l7-protocols').then(function(d) {
        if (!d.success) return;
        _renderL7Protocols(d.protocols || []);
    }).catch(function(e) {
        snShowEmpty(document.getElementById('traffic-protocols'), 'No protocol data');
    });
}

function _renderPerDeviceBandwidth(devices) {
    var el = document.getElementById('traffic-per-device');
    if (!el) return;
    el.textContent = '';
    if (!devices.length) { snShowEmpty(el, 'No bandwidth data yet'); return; }

    var maxBytes = devices[0].total || 1;
    devices.forEach(function(dev) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:8px';

        // Bandwidth thresholds: >100GB red, >10GB orange, >1GB yellow
        var total = dev.total || 0;
        var isHeavy = total > 1073741824; // 1 GB
        var isVeryHeavy = total > 10737418240; // 10 GB
        var isExtreme = total > 107374182400; // 100 GB
        if (isExtreme) row.style.cssText += ';border-left:3px solid #ef4444;padding-left:4px';
        else if (isVeryHeavy) row.style.cssText += ';border-left:3px solid #f97316;padding-left:4px';
        else if (isHeavy) row.style.cssText += ';border-left:3px solid #fbbf24;padding-left:4px';

        var label = document.createElement('span');
        label.style.cssText = 'min-width:90px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:0.78rem';
        label.style.color = isExtreme ? '#ef4444' : isVeryHeavy ? '#f97316' : isHeavy ? '#fbbf24' : 'var(--archie-text)';
        label.textContent = dev.label || dev.ip;
        label.title = dev.ip + (dev.mac ? ' (' + dev.mac + ')' : '');
        row.appendChild(label);

        var barOuter = document.createElement('div');
        barOuter.style.cssText = 'flex:1;height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;display:flex';
        var pctIn = (dev.bytes_in / maxBytes) * 100;
        var pctOut = (dev.bytes_out / maxBytes) * 100;
        var barIn = document.createElement('div');
        barIn.style.cssText = 'height:100%;background:#00e5ff;width:' + pctIn.toFixed(1) + '%';
        barIn.title = 'Download: ' + formatBytes(dev.bytes_in);
        var barOut = document.createElement('div');
        barOut.style.cssText = 'height:100%;background:#8b5cf6;width:' + pctOut.toFixed(1) + '%';
        barOut.title = 'Upload: ' + formatBytes(dev.bytes_out);
        barOuter.appendChild(barIn);
        barOuter.appendChild(barOut);
        row.appendChild(barOuter);

        var val = document.createElement('span');
        val.style.cssText = 'min-width:55px;text-align:right;color:var(--archie-text-muted);font-family:"IBM Plex Mono",monospace;font-size:0.72rem';
        val.textContent = formatBytes(dev.total || 0);
        row.appendChild(val);

        el.appendChild(row);
    });
}

function _renderTrafficHistory(hourly) {
    var svg = document.getElementById('traffic-history-chart');
    if (!svg || !hourly.length) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    var w = svg.clientWidth || 500;
    var h = svg.clientHeight || 200;
    var ns = 'http://www.w3.org/2000/svg';
    var pad = {top: 24, right: 10, bottom: 28, left: 55};
    var cw = w - pad.left - pad.right;
    var ch = h - pad.top - pad.bottom;

    var max = 1;
    hourly.forEach(function(d) {
        if (d.bytes_in > max) max = d.bytes_in;
        if (d.bytes_out > max) max = d.bytes_out;
    });
    max *= 1.15; // headroom
    var step = cw / Math.max(hourly.length - 1, 1);

    // Gradient defs
    var defs = document.createElementNS(ns, 'defs');
    [['traf-in', '#00e5ff'], ['traf-out', '#8b5cf6']].forEach(function(pair) {
        var grad = document.createElementNS(ns, 'linearGradient');
        grad.setAttribute('id', pair[0]);
        grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0');
        grad.setAttribute('x2', '0'); grad.setAttribute('y2', '1');
        var s1 = document.createElementNS(ns, 'stop');
        s1.setAttribute('offset', '0%'); s1.setAttribute('stop-color', pair[1]); s1.setAttribute('stop-opacity', '0.4');
        var s2 = document.createElementNS(ns, 'stop');
        s2.setAttribute('offset', '100%'); s2.setAttribute('stop-color', pair[1]); s2.setAttribute('stop-opacity', '0.02');
        grad.appendChild(s1); grad.appendChild(s2); defs.appendChild(grad);
    });
    svg.appendChild(defs);

    // Horizontal grid lines + Y-axis labels
    var gridLines = 4;
    for (var gi = 0; gi <= gridLines; gi++) {
        var gy = pad.top + ch - (gi / gridLines) * ch;
        var gLine = document.createElementNS(ns, 'line');
        gLine.setAttribute('x1', pad.left); gLine.setAttribute('y1', gy.toFixed(1));
        gLine.setAttribute('x2', w - pad.right); gLine.setAttribute('y2', gy.toFixed(1));
        gLine.setAttribute('stroke', 'rgba(255,255,255,0.06)'); gLine.setAttribute('stroke-width', '1');
        svg.appendChild(gLine);
        var yLabel = document.createElementNS(ns, 'text');
        yLabel.setAttribute('x', pad.left - 6); yLabel.setAttribute('y', (gy + 3).toFixed(1));
        yLabel.setAttribute('fill', '#666'); yLabel.setAttribute('font-size', '9');
        yLabel.setAttribute('text-anchor', 'end'); yLabel.setAttribute('font-family', '"IBM Plex Mono",monospace');
        yLabel.textContent = formatBytes((gi / gridLines) * max);
        svg.appendChild(yLabel);
    }

    // X-axis labels (show ~6 evenly spaced)
    var xLabelCount = Math.min(hourly.length, 6);
    var xLabelStep = Math.max(1, Math.floor((hourly.length - 1) / (xLabelCount - 1)));
    for (var xi = 0; xi < hourly.length; xi += xLabelStep) {
        var xx = pad.left + xi * step;
        var xLabel = document.createElementNS(ns, 'text');
        xLabel.setAttribute('x', xx.toFixed(1)); xLabel.setAttribute('y', (h - 6).toFixed(1));
        xLabel.setAttribute('fill', '#666'); xLabel.setAttribute('font-size', '9');
        xLabel.setAttribute('text-anchor', 'middle'); xLabel.setAttribute('font-family', '"IBM Plex Mono",monospace');
        xLabel.textContent = hourly[xi].hour;
        svg.appendChild(xLabel);
        // Vertical grid
        var vLine = document.createElementNS(ns, 'line');
        vLine.setAttribute('x1', xx.toFixed(1)); vLine.setAttribute('y1', pad.top.toFixed(1));
        vLine.setAttribute('x2', xx.toFixed(1)); vLine.setAttribute('y2', (h - pad.bottom).toFixed(1));
        vLine.setAttribute('stroke', 'rgba(255,255,255,0.03)'); vLine.setAttribute('stroke-width', '1');
        svg.appendChild(vLine);
    }

    // Draw areas + smooth lines for both in and out
    ['bytes_in', 'bytes_out'].forEach(function(key, idx) {
        var color = idx === 0 ? '#00e5ff' : '#8b5cf6';
        var gradId = idx === 0 ? 'traf-in' : 'traf-out';
        var pts = hourly.map(function(d, i) {
            var x = pad.left + i * step;
            var y = pad.top + ch - (d[key] / max) * ch;
            return [x, y];
        });

        // Area fill
        var areaStr = pts.map(function(p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
        areaStr = (pad.left).toFixed(1) + ',' + (pad.top + ch).toFixed(1) + ' ' + areaStr + ' ' + pts[pts.length-1][0].toFixed(1) + ',' + (pad.top + ch).toFixed(1);
        var area = document.createElementNS(ns, 'polygon');
        area.setAttribute('points', areaStr);
        area.setAttribute('fill', 'url(#' + gradId + ')');
        svg.appendChild(area);

        // Line
        var lineStr = pts.map(function(p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
        var line = document.createElementNS(ns, 'polyline');
        line.setAttribute('points', lineStr);
        line.setAttribute('fill', 'none');
        line.setAttribute('stroke', color);
        line.setAttribute('stroke-width', '2.5');
        line.setAttribute('stroke-linejoin', 'round');
        line.setAttribute('stroke-linecap', 'round');
        svg.appendChild(line);

        // Data point dots (if few enough)
        if (pts.length <= 30) {
            pts.forEach(function(p) {
                var dot = document.createElementNS(ns, 'circle');
                dot.setAttribute('cx', p[0].toFixed(1)); dot.setAttribute('cy', p[1].toFixed(1));
                dot.setAttribute('r', '3'); dot.setAttribute('fill', color);
                dot.setAttribute('opacity', '0.7');
                svg.appendChild(dot);
            });
        }
    });

    // Legend (top right)
    var lx = w - pad.right - 140;
    [['Download', '#00e5ff'], ['Upload', '#8b5cf6']].forEach(function(pair, i) {
        var lt = document.createElementNS(ns, 'text');
        lt.setAttribute('x', (lx + i * 80).toFixed(0)); lt.setAttribute('y', '14');
        lt.setAttribute('fill', pair[1]); lt.setAttribute('font-size', '10');
        lt.setAttribute('font-family', '"IBM Plex Mono",monospace');
        lt.textContent = '\u25CF ' + pair[0];
        svg.appendChild(lt);
    });
}

function _renderL7Protocols(protocols) {
    var el = document.getElementById('traffic-protocols');
    if (!el) return;
    el.textContent = '';
    if (!protocols.length) { snShowEmpty(el, 'No protocol data'); return; }

    var maxBytes = protocols[0].bytes || 1;
    var colors = ['#00e5ff','#8b5cf6','#10b981','#f472b6','#fbbf24','#ef4444','#22d3ee','#a3e635','#f97316','#818cf8'];
    var top = protocols.slice(0, 15);
    top.forEach(function(p, i) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:6px';

        var name = document.createElement('span');
        name.style.cssText = 'min-width:100px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:' + colors[i % colors.length] + ';font-size:0.78rem;font-family:"IBM Plex Mono",monospace';
        name.textContent = p.name;
        row.appendChild(name);

        var barOuter = document.createElement('div');
        barOuter.style.cssText = 'flex:1;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden';
        var bar = document.createElement('div');
        var pct = (p.bytes / maxBytes) * 100;
        bar.style.cssText = 'height:100%;border-radius:3px;background:' + colors[i % colors.length] + ';width:' + pct.toFixed(1) + '%';
        barOuter.appendChild(bar);
        row.appendChild(barOuter);

        var val = document.createElement('span');
        val.style.cssText = 'min-width:55px;text-align:right;color:var(--archie-text-muted);font-family:"IBM Plex Mono",monospace;font-size:0.72rem';
        val.textContent = formatBytes(p.bytes);
        row.appendChild(val);

        el.appendChild(row);
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

/* VPN Detection */
function loadVpnDetect() {
    var el = document.getElementById('vpn-detect-results');
    if (!el) return;
    el.innerHTML = '<div class="loading-state"><span class="spinner"></span> Scanning flows...</div>';

    snApi('/noc/vpn-detect').then(function(d) {
        if (!d.success) { el.innerHTML = '<div style="color:#ef4444">Scan failed</div>'; return; }

        if (!d.total_vpn_flows) {
            el.innerHTML = '<div style="color:#10b981;padding:8px 0">&#x2705; No VPN/tunnel traffic detected — ' +
                (d.total_active_flows || 0) + ' active flows scanned</div>';
            return;
        }

        var html = '<div style="color:#fbbf24;margin-bottom:12px">&#x26a0;&#xfe0f; <strong>' + d.total_vpn_flows +
            ' VPN/tunnel flow(s) detected</strong> out of ' + (d.total_active_flows || '?') + ' active flows</div>';

        if (d.suspicious_devices && d.suspicious_devices.length) {
            html += '<table class="data-table"><thead><tr><th>Device</th><th>IP</th><th>Protocol</th><th>Flows</th><th>Data</th></tr></thead><tbody>';
            d.suspicious_devices.forEach(function(dev) {
                html += '<tr><td><strong>' + (dev.label || dev.ip) + '</strong></td><td style="font-family:monospace">' + dev.ip + '</td><td>' +
                    dev.protocols.map(function(p) { return '<span style="color:#fbbf24">' + p + '</span>'; }).join(', ') +
                    '</td><td>' + dev.flow_count + '</td><td>' + formatBytes(dev.total_bytes) + '</td></tr>';
            });
            html += '</tbody></table>';
        }

        if (d.vpn_flows && d.vpn_flows.length) {
            html += '<details style="margin-top:8px"><summary style="cursor:pointer;color:var(--archie-text-muted)">Flow details (' + d.vpn_flows.length + ')</summary>';
            html += '<table class="data-table" style="margin-top:4px"><thead><tr><th>Client</th><th>Server</th><th>L7 Proto</th><th>Port</th><th>Data</th><th>Duration</th></tr></thead><tbody>';
            d.vpn_flows.forEach(function(f) {
                var dur = f.duration ? Math.round(f.duration / 60) + 'm' : '--';
                html += '<tr><td>' + (f.client_name || f.client) + '</td><td>' + (f.server_name || f.server) +
                    '</td><td style="color:#fbbf24">' + f.l7 + '</td><td>' + f.port +
                    '</td><td>' + formatBytes(f.bytes) + '</td><td>' + dur + '</td></tr>';
            });
            html += '</tbody></table></details>';
        }

        el.innerHTML = html;
    }).catch(function(e) {
        el.innerHTML = '<div style="color:#ef4444">Error: ' + e + '</div>';
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
        if (!users.length) { snShowEmpty(container, 'No device mappings — use the form above or click "Name" on a device below'); return; }
        var rows = users.map(function(u) {
            var delBtn = document.createElement('button');
            delBtn.className = 'btn btn-danger btn-sm';
            delBtn.textContent = 'Remove';
            (function(uid) {
                delBtn.addEventListener('click', function() { deleteDeviceMapping(uid); });
            }(u.id));
            return [u.mac_address || u.mac || '-', u.ip_address || u.ip || '-', u.user_name || u.username || '-', u.device_label || u.device_name || '-', delBtn];
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
            return [item.device_mac || item.mac || '-', item.device_ip || item.ip || '-', item.device_label || item.user_name || item.hostname || '-', formatBytes(item.bytes_sent || 0), formatBytes(item.bytes_recv || item.bytes_rcvd || 0), snFormatTime(item.last_seen)];
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
    // Fast local-only loads first (no host agent queue)
    loadDdnsStatus();
    loadIPAccess();
    loadAutoBlockSettings();
    loadSecurityEvents();
    loadConnections();
    // Slow host-agent loads last (use cached data while waiting)
    loadFail2banJails();
    loadFirewall();
}

function _renderFail2banJails(container, jails) {
    container.textContent = '';
    if (!jails.length) { snShowEmpty(container, 'No jails data'); return; }
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
}

function loadFail2banJails() {
    var container = document.getElementById('defense-fail2ban-jails');
    if (!container) return;

    // Show cached data immediately
    try {
        var cached = localStorage.getItem('sn_fail2ban_cache');
        if (cached) {
            var cdata = JSON.parse(cached);
            _renderFail2banJails(container, cdata.jails || []);
            var age = document.createElement('div');
            age.style.cssText = 'font-size:0.65rem;color:#666;text-align:right;margin-top:4px';
            age.textContent = 'Cached — refreshing...';
            age.id = 'f2b-cache-note';
            container.appendChild(age);
        }
    } catch(e) { /* ignore cache errors */ }

    // Fetch fresh data in background
    snApi('/fail2ban/jails').then(function(d) {
        var jails = d.jails || [];
        _renderFail2banJails(container, jails);
        // Cache for next load
        try { localStorage.setItem('sn_fail2ban_cache', JSON.stringify({jails: jails, ts: Date.now()})); } catch(e) {}
    }).catch(function() {
        // If no cached data was shown, show error
        if (!localStorage.getItem('sn_fail2ban_cache')) {
            snShowEmpty(container, 'fail2ban unavailable — host agent may be busy');
        } else {
            var note = document.getElementById('f2b-cache-note');
            if (note) note.textContent = 'Cached — live refresh failed (host agent busy)';
        }
    });
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
