// API base — canonical definition is SN_API in security-network.js (loaded first)
var API = typeof SN_API !== 'undefined' ? SN_API : '/tools/security-network/api';

/* ========== Utility aliases — canonical implementations in security-network.js ========== */
// security-network.js loads with defer, so sn* functions may not exist yet at parse time.
// These lazy wrappers resolve on first call to avoid the load-order race condition.
function esc(s) { return typeof snEsc === 'function' ? snEsc(s) : (s == null ? '' : String(s)); }
function buildTable(headers, rows) { return typeof snBuildTable === 'function' ? snBuildTable(headers, rows) : document.createElement('table'); }
function createBadge(t, cls) { return typeof snCreateBadge === 'function' ? snCreateBadge(t, cls) : (function() { var s = document.createElement('span'); s.textContent = t; return s; })(); }
function showLoading(el) { if (typeof snShowLoading === 'function') snShowLoading(el); }
function showEmpty(el, msg) { if (typeof snShowEmpty === 'function') snShowEmpty(el, msg); }
// formatNum and setBadge are already defined (without sn- prefix) in security-network.js — no alias needed.

function formatTime(t) {
    if (!t) return '-';
    return typeof ArchieTime !== 'undefined' ? ArchieTime.format(t, 'short') : String(t);
}
function closeModal() { document.getElementById('modal-overlay').classList.remove('open'); }

/* ========== Tab Management ========== */
/* Tab load flags managed by security-network.js — skipping re-declaration */
var accessTabLoaded = false, reportsTabLoaded = false;
var qlOffset = 0, activeScannerType = 'nmap';

/* initTabs + initSubtabs handled by security-network.js */

function switchToTab(tabName) {
    /* remap old tab names to new 8-tab names */
    var _remap = {
        'dashboard':    'overview',
        'surveillance': 'scanners',
        'recon':        'scanners',
        'scanning':     'scanners',
        'access':       'defense',
        'hardening':    'compliance',
        'domains':      'dns'
    };
    switchSecurityTab(_remap[tabName] || tabName);
}

/* ========== Dashboard ========== */
async function loadDashboard() {
    try {
        const r = await fetch(API + '/dashboard/stats');
        const d = await r.json();
        if (!d.success) return;
        document.getElementById('dash-dns-queries').textContent = formatNum(d.dns_queries_24h || 0);
        document.getElementById('dash-dns-blocked').textContent = formatNum(d.dns_blocked_24h || 0);
        document.getElementById('dash-cameras').textContent = d.camera_count || 0;
        document.getElementById('dash-suggestions').textContent = d.pending_suggestions || 0;
        setBadge('svc-adguard', d.services && d.services.adguard);
        setBadge('svc-hostinger', d.services && d.services.hostinger);
        setBadge('svc-surveillance', d.services && d.services.surveillance);
        setBadge('svc-ssh', d.services && d.services.ssh);
        setBadge('svc-fail2ban', d.services && d.services.fail2ban);
        setBadge('svc-ddns', d.services && d.services.ddns);
        setBadge('svc-argus', d.services && d.services.argus);
        setBadge('svc-agent', d.services && d.services.agent);
        // Set DNS protection toggle state
        if (d.dns_protection_enabled !== undefined) {
            updateDnsToggleUI(d.dns_protection_enabled);
        }

        const feed = document.getElementById('dash-activity');
        feed.textContent = '';
        if (d.recent_activity && d.recent_activity.length) {
            d.recent_activity.forEach(a => {
                const item = document.createElement('div');
                item.className = 'activity-item';
                const iconDiv = document.createElement('div');
                iconDiv.className = 'activity-icon';
                iconDiv.style.background = 'var(--archie-accent-alpha-10)';
                const textDiv = document.createElement('div');
                const txt = document.createElement('div');
                txt.className = 'activity-text';
                txt.textContent = a.text || '';
                const tm = document.createElement('div');
                tm.className = 'activity-time';
                tm.textContent = a.time ? formatTime(a.time) : '';
                textDiv.appendChild(txt);
                textDiv.appendChild(tm);
                item.appendChild(iconDiv);
                item.appendChild(textDiv);
                feed.appendChild(item);
            });
        } else {
            showEmpty(feed, 'No recent activity');
        }
    } catch(e) { console.error('Dashboard error:', e); }

    // Compliance summary
    try {
        const cr = await fetch(API + '/compliance/scores');
        const cd = await cr.json();
        if (cd.success) {
            const score = cd.score || 0;
            const scoreEl = document.getElementById('compliance-dash-score');
            scoreEl.textContent = score.toFixed(1) + '%';
            scoreEl.style.color = score >= 80 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444';
            const grade = score >= 95 ? 'A+' : score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 70 ? 'C' : 'F';
            document.getElementById('compliance-dash-grade').textContent = grade;
            // Per-pack scores
            const packs = cd.packs || {};
            ['ubuntu','docker','network'].forEach(p => {
                const el = document.getElementById('compliance-dash-' + p);
                if (el && packs[p] !== undefined) {
                    const ps = packs[p];
                    el.textContent = ps.toFixed(0) + '%';
                    el.style.color = ps >= 80 ? '#22c55e' : ps >= 50 ? '#f59e0b' : '#ef4444';
                }
            });
            if (cd.last_scan) {
                document.getElementById('compliance-dash-time').textContent = formatTime(cd.last_scan);
            }
        }
    } catch(e) { console.debug('Compliance dash:', e); }
}

var _dnsProtectionOn = true;
function updateDnsToggleUI(enabled) {
    _dnsProtectionOn = enabled;
    var btn = document.getElementById('dash-dns-toggle');
    var txt = document.getElementById('dash-dns-toggle-text');
    if (!btn || !txt) return;
    if (enabled) {
        btn.style.cssText = 'background:rgba(34,197,94,0.15);border:1px solid rgba(34,197,94,0.4);color:#22c55e;';
        txt.textContent = 'DNS Protection ON';
    } else {
        btn.style.cssText = 'background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);color:#ef4444;';
        txt.textContent = 'DNS Protection OFF';
    }
}

function openQuickScanModal(module, title, fieldLabel, placeholder) {
    var existing = document.getElementById('quick-scan-modal');
    if (existing) existing.remove();

    var html =
      '<div class="bm-overlay active" id="quick-scan-modal" style="--bm-accent:#fbbf24;--bm-accent-rgb:251,191,36">' +
        '<div class="bm-shell" style="max-width:420px">' +
          '<div class="bm-frame">' +
            '<div class="bm-frame-elbow-top"></div><div class="bm-frame-seg"></div>' +
            '<div class="bm-frame-seg dim"></div><div class="bm-frame-light on"></div>' +
            '<div class="bm-frame-light amber"></div><div class="bm-frame-seg purple"></div>' +
            '<div class="bm-frame-fill"></div><div class="bm-frame-elbow-bottom"></div>' +
          '</div>' +
          '<div class="bm-content">' +
            '<div class="bm-header">' +
              '<span class="bm-header-title">' + title + '</span>' +
              '<div class="bm-header-strip">' +
                '<div class="bm-header-pip w1"></div><div class="bm-header-pip w2"></div>' +
                '<div class="bm-header-pip w3"></div>' +
                '<button class="bm-close" onclick="document.getElementById(\'quick-scan-modal\').remove()">&times;</button>' +
              '</div>' +
            '</div>' +
            '<div class="bm-body" style="padding:16px">' +
              '<label style="display:block;font-size:0.75rem;color:var(--archie-text-muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px">' + fieldLabel + '</label>' +
              '<input type="text" id="quick-scan-target" placeholder="' + placeholder + '" style="width:100%;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);color:var(--archie-text);padding:10px 12px;border-radius:4px;font-family:\'IBM Plex Mono\',monospace;font-size:0.9rem">' +
              '<div id="quick-scan-error" style="display:none;color:#ef4444;font-size:0.8rem;margin-top:6px"></div>' +
            '</div>' +
            '<div class="bm-footer" style="padding:12px 16px;display:flex;gap:8px;justify-content:flex-end">' +
              '<button class="btn" onclick="document.getElementById(\'quick-scan-modal\').remove()" style="opacity:0.7">Cancel</button>' +
              '<button class="btn-submit" id="quick-scan-submit" style="background:rgba(251,191,36,0.2);border-color:rgba(251,191,36,0.5);color:#fbbf24">Run ' + title + '</button>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.insertAdjacentHTML('beforeend', html);
    var modal = document.getElementById('quick-scan-modal');
    modal.addEventListener('click', function(e) { if (e.target === modal) modal.remove(); });
    setTimeout(function() { document.getElementById('quick-scan-target').focus(); }, 100);

    document.getElementById('quick-scan-submit').addEventListener('click', function() {
        var target = document.getElementById('quick-scan-target').value.trim();
        if (!target) {
            var err = document.getElementById('quick-scan-error');
            err.textContent = 'Please enter a target.';
            err.style.display = 'block';
            return;
        }
        modal.remove();
        showToast('info', 'Starting ' + title + ' on ' + target + '...');
        fetch(API + '/recon/scan', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({target: target, module: module})
        }).then(function(r) { return r.json(); })
          .then(function(d) {
              if (d.success) {
                  showToast('success', title + ' started — check Scanners tab for results');
                  switchSecurityTab('scanners');
              } else {
                  showToast('error', d.error || 'Scan failed');
              }
          }).catch(function(e) { showToast('error', e.message); });
    });
}

function quickToggleProtection() {
    var newState = !_dnsProtectionOn;
    fetch(API + '/dns/adguard/protection', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({enabled:newState})
    }).then(function(r){return r.json();}).then(function(d){
        if(d.success) {
            updateDnsToggleUI(newState);
            showToast('success','DNS protection '+(newState?'enabled':'disabled'));
        } else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

function openBlockDomainModal() {
    var input = document.getElementById('block-domain-input');
    input.value = '';
    input.style.borderColor = '';
    var errDiv = document.getElementById('block-domain-error');
    if (errDiv) errDiv.style.display = 'none';
    document.getElementById('block-domain-modal').classList.add('active');
    setTimeout(function() { input.focus(); }, 300);
}

function closeBlockDomainModal() {
    document.getElementById('block-domain-modal').classList.remove('active');
}

function submitBlockDomain() {
    var domain = document.getElementById('block-domain-input').value.trim();
    if(!domain) return showToast('error','Enter a domain');
    var btn = document.getElementById('block-domain-submit');
    if (btn) btn.textContent = 'Blocking...';
    fetch(API+'/dns/adguard/block',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({domain:domain})
    }).then(function(r){
        return r.json();
    }).then(function(d){
        if (btn) btn.textContent = 'Block Domain';
        if(d.success) {
            closeBlockDomainModal();
            showToast('success',domain+' blocked — added to Rules');
            var dnsBtn = document.querySelector('.tab-btn[data-tab="dns"]');
            if (dnsBtn) dnsBtn.click();
            setTimeout(function() {
                var rulesBtn = document.querySelector('.subtab-btn[data-subtab="dns-rules"]');
                if (rulesBtn) rulesBtn.click();
            }, 200);
        } else {
            // Keep modal open, show inline error with shake
            var errDiv = document.getElementById('block-domain-error');
            var input = document.getElementById('block-domain-input');
            if (errDiv) {
                errDiv.textContent = d.error || 'Failed to block domain';
                errDiv.style.display = 'block';
                errDiv.style.animation = 'none';
                void errDiv.offsetWidth;
                errDiv.style.animation = 'shake 0.3s ease-in-out';
            }
            if (input) input.style.borderColor = '#ef4444';
        }
    }).catch(function(e){
        if (btn) btn.textContent = 'Block Domain';
        var errDiv = document.getElementById('block-domain-error');
        if (errDiv) {
            errDiv.textContent = 'Error: ' + e.message;
            errDiv.style.display = 'block';
        }
    });
}

// Block domain modal — button click + Enter key
document.addEventListener('DOMContentLoaded', function() {
    var blockBtn = document.getElementById('block-domain-submit');
    if (blockBtn) {
        blockBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            submitBlockDomain();
        });
    }
    var blockInput = document.getElementById('block-domain-input');
    if (blockInput) {
        blockInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') { e.preventDefault(); submitBlockDomain(); }
        });
    }
});

/* ========== DNS Management ========== */
async function loadDNSOverview() {
    try {
        const r = await fetch(API + '/dns/adguard/stats');
        const d = await r.json();
        if (d.success && d.stats) {
            const s = d.stats;
            document.getElementById('dns-total-queries').textContent = formatNum(s.num_dns_queries || 0);
            document.getElementById('dns-blocked').textContent = formatNum(s.num_blocked_filtering || 0);
            document.getElementById('dns-safe-browsing').textContent = formatNum(s.num_replaced_safebrowsing || 0);
            var protEnabled = d.status && d.status.protection_enabled !== undefined ? d.status.protection_enabled : true;
            const pEl = document.getElementById('dns-protection-status');
            pEl.textContent = protEnabled ? 'ON' : 'OFF';
            pEl.style.color = protEnabled ? 'var(--archie-green)' : 'var(--archie-red)';

            // Render Top Queried Domains
            _renderTopDomainList('dns-top-queried', 'dns-top-queried-count', s.top_queried_domains, '#00e5ff', 15);
            // Render Top Blocked Domains
            _renderTopDomainList('dns-top-blocked', 'dns-top-blocked-count', s.top_blocked_domains, '#ef4444', 24);
        }
    } catch(e) { console.error('DNS overview error:', e); }
}

function _renderTopDomainList(containerId, countId, domainList, accentColor, maxItems) {
    var container = document.getElementById(containerId);
    var countEl = document.getElementById(countId);
    if (!container) return;
    if (!domainList || !domainList.length) {
        container.textContent = '';
        var empty = document.createElement('div');
        empty.style.cssText = 'color:#666;padding:12px;font-size:0.8rem;text-align:center';
        empty.textContent = 'No data available';
        container.appendChild(empty);
        if (countEl) countEl.textContent = '0';
        return;
    }
    if (countEl) countEl.textContent = domainList.length + ' domains';
    container.textContent = '';
    var items = domainList.slice(0, maxItems);
    items.forEach(function(entry, idx) {
        // Each entry is {domain: count} — extract key/value
        var domain = Object.keys(entry)[0];
        var count = entry[domain];
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:6px 12px;border-bottom:1px solid rgba(255,255,255,0.04);cursor:pointer;transition:background 0.15s';
        row.addEventListener('mouseenter', function() { row.style.background = 'rgba(255,255,255,0.04)'; });
        row.addEventListener('mouseleave', function() { row.style.background = 'transparent'; });
        row.addEventListener('click', function() { if (typeof openDomainIntel === 'function') openDomainIntel(domain); });
        row.title = 'Click to investigate ' + domain;

        var left = document.createElement('div');
        left.style.cssText = 'display:flex;align-items:center;gap:8px;min-width:0';
        var rank = document.createElement('span');
        rank.style.cssText = 'color:#555;font-size:0.7rem;min-width:20px;text-align:right';
        rank.textContent = (idx + 1) + '.';
        var name = document.createElement('span');
        name.style.cssText = 'color:#ccc;font-size:0.78rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
        name.textContent = domain;
        left.appendChild(rank);
        left.appendChild(name);

        var badge = document.createElement('span');
        badge.style.cssText = 'background:' + accentColor + '22;color:' + accentColor + ';padding:2px 8px;border-radius:4px;font-size:0.7rem;font-weight:600;white-space:nowrap';
        badge.textContent = formatNum(count);

        row.appendChild(left);
        row.appendChild(badge);
        container.appendChild(row);
    });
}

function dnsBlockDomain() {
    const domain = document.getElementById('dns-quick-domain').value.trim();
    if(!domain) return showToast('error','Enter a domain');
    fetch(API+'/dns/adguard/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain})})
    .then(r=>r.json()).then(d=>{
        if(d.success){showToast('success',domain+' blocked');document.getElementById('dns-quick-domain').value='';}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

function dnsUnblockDomain() {
    const domain = document.getElementById('dns-quick-domain').value.trim();
    if(!domain) return showToast('error','Enter a domain');
    fetch(API+'/dns/adguard/unblock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain})})
    .then(r=>r.json()).then(d=>{
        if(d.success){showToast('success',domain+' unblocked');document.getElementById('dns-quick-domain').value='';}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

/* Query Log */
var _qlDeviceMap = null;
async function _getDeviceMap() {
    if (_qlDeviceMap) return _qlDeviceMap;
    try {
        var r = await fetch(API + '/devices');
        var d = await r.json();
        _qlDeviceMap = {};
        if (d.success && d.devices) {
            d.devices.forEach(function(dev) {
                if (dev.ip_address && dev.friendly_name) {
                    _qlDeviceMap[dev.ip_address] = {name: dev.friendly_name, type: dev.device_type, owner: dev.owner};
                }
            });
        }
    } catch(e) { _qlDeviceMap = {}; }
    return _qlDeviceMap;
}

async function loadQueryLog(offset) {
    qlOffset = Math.max(0, offset || 0);
    const search = document.getElementById('ql-search').value;
    const status = document.getElementById('ql-status').value;
    const container = document.getElementById('querylog-container');
    showLoading(container);
    try {
        var deviceMap = await _getDeviceMap();
        const params = new URLSearchParams({limit:50,offset:qlOffset});
        if(search) params.set('search',search);
        if(status) params.set('response_status',status);
        const r = await fetch(API+'/dns/adguard/querylog?'+params);
        const d = await r.json();
        if(d.success && d.data) {
            const entries = d.data.data || d.data || [];
            if(!entries.length) { showEmpty(container,'No query log entries'); document.getElementById('ql-pagination').style.display='none'; return; }

            // Build table manually for row-level styling
            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var headerRow = document.createElement('tr');
            ['Time','Domain','Client','Type','Status'].forEach(function(h) {
                var th = document.createElement('th');
                th.textContent = h;
                headerRow.appendChild(th);
            });
            thead.appendChild(headerRow);
            table.appendChild(thead);

            var tbody = document.createElement('tbody');
            entries.forEach(function(e) {
                var q = e.question || {};
                var reason = e.reason || '';
                var notBlocked = !reason || reason === 'NotFilteredNotFound' || reason === 'NotFilteredWhiteList' || reason === 'Rewrite';
                var blocked = !notBlocked;
                var isRewrite = reason === 'Rewrite';
                var clientIp = e.client || '-';
                var domain = q.name || '-';

                var tr = document.createElement('tr');
                // Red tint on blocked rows, cyan tint on rewrites
                if (blocked) {
                    tr.style.background = 'rgba(239,68,68,0.06)';
                    tr.style.borderLeft = '3px solid rgba(239,68,68,0.4)';
                } else if (isRewrite) {
                    tr.style.background = 'rgba(0,229,255,0.04)';
                    tr.style.borderLeft = '3px solid rgba(0,229,255,0.25)';
                }

                // Time
                var tdTime = document.createElement('td');
                tdTime.textContent = formatTime(e.time);
                tdTime.style.fontSize = '0.78rem';
                tr.appendChild(tdTime);

                // Domain — clickable to block
                var tdDomain = document.createElement('td');
                var domLink = document.createElement('span');
                domLink.textContent = domain;
                domLink.style.cursor = 'pointer';
                domLink.style.color = 'var(--archie-accent, #00e5ff)';
                domLink.style.textDecoration = 'underline';
                domLink.style.textDecorationColor = 'rgba(0,229,255,0.3)';
                domLink.title = 'Click to view domain intelligence';
                domLink.addEventListener('click', function() {
                    if (typeof openDomainIntel === 'function') openDomainIntel(domain);
                });
                tdDomain.appendChild(domLink);
                tr.appendChild(tdDomain);

                // Client — with device tag + clickable to filter
                var tdClient = document.createElement('td');
                var dev = deviceMap[clientIp];
                var ipSpan = document.createElement('span');
                ipSpan.textContent = clientIp;
                ipSpan.style.cursor = 'pointer';
                ipSpan.title = 'Click to filter by this client';
                ipSpan.addEventListener('click', function() {
                    document.getElementById('ql-search').value = clientIp;
                    loadQueryLog(0);
                });
                tdClient.appendChild(ipSpan);
                if (dev) {
                    var spacer = document.createTextNode(' ');
                    tdClient.appendChild(spacer);
                    var tag = document.createElement('span');
                    tag.textContent = dev.name;
                    tag.style.cssText = 'background:rgba(34,197,94,0.15);color:#22c55e;padding:1px 6px;border-radius:3px;font-size:0.7rem;border:1px solid rgba(34,197,94,0.3);cursor:pointer;';
                    tag.title = 'Click to filter by ' + dev.name;
                    tag.addEventListener('click', function() {
                        document.getElementById('ql-search').value = clientIp;
                        loadQueryLog(0);
                    });
                    tdClient.appendChild(tag);
                }
                tr.appendChild(tdClient);

                // Type
                var tdType = document.createElement('td');
                tdType.textContent = q.type || '-';
                tr.appendChild(tdType);

                // Status badge
                var tdStatus = document.createElement('td');
                var statusLabel = blocked ? 'Blocked' : isRewrite ? 'Rewrite' : 'OK';
                var statusType = blocked ? 'danger' : isRewrite ? 'info' : 'success';
                tdStatus.appendChild(createBadge(statusLabel, statusType));
                tr.appendChild(tdStatus);

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);

            container.textContent = '';
            container.appendChild(table);
            const pag = document.getElementById('ql-pagination');
            pag.style.display = 'flex';
            document.getElementById('ql-prev').disabled = qlOffset === 0;
            document.getElementById('ql-page-info').textContent = 'Showing '+(qlOffset+1)+' - '+(qlOffset+entries.length);
        } else { showEmpty(container, 'Could not load query log'); }
    } catch(e) { showEmpty(container, 'Error loading query log'); }
}

/* Filters */
async function loadFilters() {
    const container = document.getElementById('filters-list');
    showLoading(container);
    try {
        const r = await fetch(API+'/dns/adguard/filters');
        const d = await r.json();
        if(d.success && d.filters) {
            if(!d.filters.length) { showEmpty(container,'No filters configured — add a filter list above'); return; }
            container.textContent = '';

            // Summary bar
            var totalRules = 0;
            var enabledCount = 0;
            d.filters.forEach(function(f) { totalRules += (f.rules_count || 0); if (f.enabled) enabledCount++; });
            var summary = document.createElement('div');
            summary.style.cssText = 'display:flex;gap:16px;padding:8px 12px;margin-bottom:8px;font-size:0.8rem;border-bottom:1px solid rgba(255,255,255,0.06)';
            var s1 = document.createElement('span');
            s1.style.color = '#00e5ff';
            s1.textContent = d.filters.length + ' filter lists';
            var s2 = document.createElement('span');
            s2.style.color = '#22c55e';
            s2.textContent = enabledCount + ' active';
            var s3 = document.createElement('span');
            s3.style.color = '#f97316';
            s3.textContent = formatNum(totalRules) + ' total rules';
            summary.appendChild(s1); summary.appendChild(s2); summary.appendChild(s3);
            container.appendChild(summary);

            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var hrow = document.createElement('tr');
            ['Enabled','Name','URL','Rules',''].forEach(function(h) {
                var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th);
            });
            thead.appendChild(hrow);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            d.filters.forEach(function(f) {
                var tr = document.createElement('tr');

                var tdToggle = document.createElement('td');
                var toggle = document.createElement('label');
                toggle.className = 'toggle-switch';
                var input = document.createElement('input');
                input.type = 'checkbox';
                input.checked = f.enabled;
                input.addEventListener('change', function() { toggleFilter(f.url, this.checked); });
                var slider = document.createElement('span');
                slider.className = 'toggle-slider';
                toggle.appendChild(input);
                toggle.appendChild(slider);
                tdToggle.appendChild(toggle);
                tr.appendChild(tdToggle);

                var tdName = document.createElement('td');
                tdName.style.fontWeight = '500';
                var nameLink = document.createElement('span');
                nameLink.textContent = f.name;
                nameLink.style.cssText = 'cursor:pointer;color:#00e5ff;text-decoration:underline;text-decoration-color:rgba(0,229,255,0.3)';
                nameLink.title = 'Click to view domains in this filter';
                nameLink.addEventListener('click', function() { _showFilterRules(f.id, f.name, f.rules_count); });
                tdName.appendChild(nameLink);
                tr.appendChild(tdName);

                var tdUrl = document.createElement('td');
                tdUrl.style.cssText = 'font-size:0.72rem;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                tdUrl.textContent = f.url;
                tdUrl.title = f.url;
                tr.appendChild(tdUrl);

                var tdRules = document.createElement('td');
                tdRules.textContent = formatNum(f.rules_count || 0);
                tr.appendChild(tdRules);

                var tdAction = document.createElement('td');
                var delBtn = document.createElement('button');
                delBtn.className = 'btn btn-danger btn-sm';
                delBtn.textContent = 'Remove';
                delBtn.addEventListener('click', function() { removeFilter(f.url); });
                tdAction.appendChild(delBtn);
                tr.appendChild(tdAction);

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            container.appendChild(table);
        } else {
            showEmpty(container, (d.error || 'Could not load filters') + ' — check AdGuard connection');
        }
    } catch(e) { showEmpty(container, 'Error loading filters: ' + e.message); }
}

function addFilter() {
    const name = document.getElementById('filter-name').value.trim();
    const url = document.getElementById('filter-url').value.trim();
    if(!name||!url) return showToast('error','Name and URL required');
    fetch(API+'/dns/adguard/filters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,url:url,enabled:true})})
    .then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Filter added');loadFilters();document.getElementById('filter-name').value='';document.getElementById('filter-url').value='';}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

function toggleFilter(url, enabled) {
    fetch(API+'/dns/adguard/filters/'+encodeURIComponent(url),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:enabled})})
    .then(r=>r.json()).then(d=>{if(!d.success){showToast('error',d.error||'Failed');loadFilters();}})
    .catch(e=>showToast('error',e.message));
}

function removeFilter(url) {
    if(!confirm('Remove this filter?')) return;
    fetch(API+'/dns/adguard/filters/'+encodeURIComponent(url),{method:'DELETE'})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Filter removed');loadFilters();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

function _showFilterRules(filterId, filterName, totalRules) {
    var existing = document.getElementById('filter-rules-overlay');
    if (existing) existing.remove();

    var safeName = filterName.replace(/[<>&"']/g, '');

    var overlay = document.createElement('div');
    overlay.className = 'bm-overlay active';
    overlay.id = 'filter-rules-overlay';
    overlay.style.cssText = '--bm-accent:#f97316;--bm-accent-rgb:249,115,22';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    var shell = document.createElement('div');
    shell.className = 'bm-shell';
    shell.style.maxWidth = '600px';

    var frame = document.createElement('div');
    frame.className = 'bm-frame';
    ['bm-frame-elbow-top','bm-frame-seg','bm-frame-seg dim','bm-frame-light on','bm-frame-light amber','bm-frame-seg purple','bm-frame-fill','bm-frame-elbow-bottom'].forEach(function(cls) {
        var el = document.createElement('div'); el.className = cls; frame.appendChild(el);
    });

    var content = document.createElement('div');
    content.className = 'bm-content';

    var header = document.createElement('div');
    header.className = 'bm-header';
    var title = document.createElement('span');
    title.className = 'bm-header-title';
    title.textContent = safeName;
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
    body.style.cssText = 'padding:16px;max-height:65vh;overflow-y:auto';

    // Info bar
    var info = document.createElement('div');
    info.style.cssText = 'display:flex;gap:16px;margin-bottom:12px;font-size:0.8rem;flex-wrap:wrap';
    var s1 = document.createElement('span');
    s1.style.color = '#f97316';
    s1.textContent = formatNum(totalRules) + ' total rules';
    info.appendChild(s1);
    body.appendChild(info);

    // Search bar
    var searchRow = document.createElement('div');
    searchRow.style.cssText = 'display:flex;gap:8px;margin-bottom:12px';
    var searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'form-input';
    searchInput.placeholder = 'Search domains in this filter...';
    searchInput.style.cssText = 'flex:1;font-size:0.78rem';
    var searchBtn = document.createElement('button');
    searchBtn.className = 'btn btn-primary btn-sm';
    searchBtn.textContent = 'Search';
    searchBtn.addEventListener('click', function() { _fetchFilterRules(filterId, listContainer, searchInput.value); });
    searchInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') { e.preventDefault(); _fetchFilterRules(filterId, listContainer, searchInput.value); } });
    searchRow.appendChild(searchInput);
    searchRow.appendChild(searchBtn);
    body.appendChild(searchRow);

    var listContainer = document.createElement('div');
    listContainer.style.cssText = 'font-size:0.78rem';
    listContainer.textContent = 'Loading domains...';
    body.appendChild(listContainer);

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

    _fetchFilterRules(filterId, listContainer, '');
}

function _fetchFilterRules(filterId, container, search) {
    container.textContent = 'Loading...';
    var params = 'limit=200';
    if (search) params += '&search=' + encodeURIComponent(search);
    fetch(API + '/dns/adguard/filters/' + filterId + '/rules?' + params)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            container.textContent = '';
            if (!d.success) {
                container.textContent = 'Error: ' + (d.error || 'Failed to load');
                return;
            }
            if (!d.domains || !d.domains.length) {
                container.textContent = search ? 'No domains matching "' + search + '"' : 'No domains found';
                return;
            }
            var note = document.createElement('div');
            note.style.cssText = 'color:#888;font-size:0.7rem;margin-bottom:8px';
            note.textContent = 'Showing ' + d.domains.length + ' of ' + formatNum(d.filter.rules_count) + ' rules' + (d.search ? ' matching "' + d.search + '"' : '');
            container.appendChild(note);

            d.domains.forEach(function(domain, idx) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.03);cursor:pointer;transition:background 0.15s';
                row.addEventListener('mouseenter', function() { row.style.background = 'rgba(255,255,255,0.04)'; });
                row.addEventListener('mouseleave', function() { row.style.background = 'transparent'; });
                row.title = 'Click to investigate';
                row.addEventListener('click', function() {
                    var overlay = document.getElementById('filter-rules-overlay');
                    if (overlay) overlay.remove();
                    if (typeof openDomainIntel === 'function') openDomainIntel(domain);
                });

                var rank = document.createElement('span');
                rank.style.cssText = 'color:#555;font-size:0.68rem;min-width:28px;text-align:right;margin-right:8px';
                rank.textContent = (idx + 1) + '.';
                var name = document.createElement('span');
                name.style.cssText = 'color:#ccc;font-size:0.76rem';
                name.textContent = domain;

                row.appendChild(rank);
                row.appendChild(name);
                container.appendChild(row);
            });
        })
        .catch(function(e) { container.textContent = 'Error: ' + e; });
}

function refreshAllFilters() {
    fetch(API+'/dns/adguard/filters/refresh',{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Filters refreshed');loadFilters();}else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

/* Rewrites */
async function loadRewrites() {
    const container = document.getElementById('rewrites-list');
    showLoading(container);
    try {
        const r = await fetch(API+'/dns/adguard/rewrites');
        const d = await r.json();
        if(d.success && d.rewrites) {
            if(!d.rewrites.length){showEmpty(container,'No DNS rewrites configured — use the form above to map domains to custom IPs');return;}
            container.textContent='';

            // Description + count
            var info = document.createElement('div');
            info.style.cssText = 'padding:8px 12px;margin-bottom:8px;font-size:0.78rem;color:#888;border-bottom:1px solid rgba(255,255,255,0.06)';
            info.textContent = d.rewrites.length + ' rewrite' + (d.rewrites.length !== 1 ? 's' : '') + ' active \u2014 DNS rewrites map domains to custom IPs. Used for split DNS (internal services resolve to local IPs).';
            container.appendChild(info);

            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var hrow = document.createElement('tr');
            ['Domain','Answer (IP)',''].forEach(function(h) {
                var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th);
            });
            thead.appendChild(hrow);
            table.appendChild(thead);
            var tbd = document.createElement('tbody');
            d.rewrites.forEach(function(rw) {
                var tr = document.createElement('tr');
                var tdDom = document.createElement('td');
                tdDom.textContent = rw.domain;
                tdDom.style.color = '#00e5ff';
                tr.appendChild(tdDom);
                var tdAns = document.createElement('td');
                tdAns.textContent = rw.answer;
                tr.appendChild(tdAns);
                var tdAct = document.createElement('td');
                var delBtn = document.createElement('button');
                delBtn.className = 'btn btn-danger btn-sm';
                delBtn.textContent = 'Delete';
                delBtn.addEventListener('click', function() { deleteRewrite(rw.domain, rw.answer); });
                tdAct.appendChild(delBtn);
                tr.appendChild(tdAct);
                tbd.appendChild(tr);
            });
            table.appendChild(tbd);
            container.appendChild(table);
        } else {
            showEmpty(container, (d.error || 'Could not load rewrites') + ' — check AdGuard connection');
        }
    } catch(e) { showEmpty(container,'Error loading rewrites: ' + e.message); }
}

function addRewrite() {
    const domain = document.getElementById('rw-domain').value.trim();
    const answer = document.getElementById('rw-answer').value.trim();
    if(!domain||!answer) return showToast('error','Domain and answer required');
    fetch(API+'/dns/adguard/rewrites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain,answer:answer})})
    .then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Rewrite added');loadRewrites();document.getElementById('rw-domain').value='';document.getElementById('rw-answer').value='';}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

function deleteRewrite(domain, answer) {
    if(!confirm('Delete rewrite '+domain+'?')) return;
    fetch(API+'/dns/adguard/rewrites',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain,answer:answer})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Rewrite deleted');loadRewrites();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

/* Hostinger */
async function loadHostingerRecords() {
    try {
        const r = await fetch(API+'/dns/hostinger/records');
        const d = await r.json();
        if(!d.success && (d.error||'').indexOf('not configured')>=0) {
            document.getElementById('hostinger-not-configured').style.display='block';
            document.getElementById('hostinger-configured').style.display='none';
            lucide.createIcons();
            return;
        }
        document.getElementById('hostinger-not-configured').style.display='none';
        document.getElementById('hostinger-configured').style.display='block';
        const container = document.getElementById('hostinger-records');
        if(d.success && d.records) {
            if(!d.records.length){showEmpty(container,'No DNS records');return;}
            container.textContent='';
            const rows = d.records.map(rec=>{
                const delBtn=document.createElement('button');
                delBtn.className='btn btn-danger btn-sm';
                delBtn.textContent='Delete';
                delBtn.addEventListener('click',function(){deleteHostingerRecord(rec.id);});
                return [createBadge(rec.type||rec.record_type,'info'), rec.name, rec.content||rec.value, rec.ttl||'-', delBtn];
            });
            container.appendChild(buildTable(['Type','Name','Content','TTL',''], rows));
        } else { showEmpty(container,'Could not load records'); }
    } catch(e) { showEmpty(document.getElementById('hostinger-records'),'Error loading records'); }
}

function addHostingerRecord() {
    const record_type=document.getElementById('host-type').value;
    const name=document.getElementById('host-name').value.trim();
    const content=document.getElementById('host-content').value.trim();
    const ttl=parseInt(document.getElementById('host-ttl').value)||3600;
    if(!name||!content) return showToast('error','Name and content required');
    fetch(API+'/dns/hostinger/records',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({record_type:record_type,name:name,content:content,ttl:ttl})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Record added');loadHostingerRecords();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

function deleteHostingerRecord(id) {
    if(!confirm('Delete this DNS record?')) return;
    fetch(API+'/dns/hostinger/records/'+id,{method:'DELETE'})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Record deleted');loadHostingerRecords();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

/* User Rules */
async function loadUserRules() {
    try {
        const r = await fetch(API+'/dns/adguard/rules');
        const d = await r.json();
        if(d.success) {
            var rulesText = d.rules || '';
            document.getElementById('user-rules').value = rulesText;
            _renderRulesSummary(rulesText);
        }
    } catch(e){console.error('Rules load error:',e);}
}

function _renderRulesSummary(rulesText) {
    var lines = rulesText.split('\n').filter(function(l) { return l.trim(); });
    var blocked = [], allowed = [], comments = 0;
    lines.forEach(function(line) {
        var t = line.trim();
        if (t.startsWith('#') || t.startsWith('!')) { comments++; }
        else if (t.startsWith('@@||')) {
            var m = t.match(/^@@\|\|(.+?)\^/);
            if (m) allowed.push(m[1]);
        } else if (t.startsWith('||')) {
            var m2 = t.match(/^\|\|(.+?)\^/);
            if (m2) blocked.push(m2[1]);
        }
    });

    var bcEl = document.getElementById('rules-blocked-count');
    var acEl = document.getElementById('rules-allowed-count');
    var ccEl = document.getElementById('rules-comment-count');
    if (bcEl) bcEl.textContent = blocked.length;
    if (acEl) acEl.textContent = allowed.length;
    if (ccEl) ccEl.textContent = comments;

    var chips = document.getElementById('rules-domain-chips');
    if (!chips) return;
    chips.textContent = '';

    if (!blocked.length && !allowed.length) {
        var empty = document.createElement('span');
        empty.style.cssText = 'color:#666;font-size:0.78rem';
        empty.textContent = 'No custom domain rules. Use Quick Block above or edit the textarea below.';
        chips.appendChild(empty);
        return;
    }

    blocked.forEach(function(domain) {
        var chip = document.createElement('span');
        chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;background:rgba(239,68,68,0.12);color:#ef4444;padding:3px 8px;border-radius:4px;font-size:0.72rem;border:1px solid rgba(239,68,68,0.25)';
        var txt = document.createTextNode(domain);
        var x = document.createElement('span');
        x.style.cssText = 'cursor:pointer;font-weight:700;margin-left:2px;opacity:0.7';
        x.textContent = '\u00d7';
        x.title = 'Remove block rule for ' + domain;
        x.addEventListener('click', function(e) {
            e.stopPropagation();
            _removeRule('||' + domain + '^');
        });
        chip.appendChild(txt);
        chip.appendChild(x);
        chip.style.cursor = 'pointer';
        chip.title = 'Click to investigate ' + domain;
        chip.addEventListener('click', function() { if (typeof openDomainIntel === 'function') openDomainIntel(domain); });
        chips.appendChild(chip);
    });

    allowed.forEach(function(domain) {
        var chip = document.createElement('span');
        chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;background:rgba(34,197,94,0.12);color:#22c55e;padding:3px 8px;border-radius:4px;font-size:0.72rem;border:1px solid rgba(34,197,94,0.25)';
        var txt = document.createTextNode(domain);
        var x = document.createElement('span');
        x.style.cssText = 'cursor:pointer;font-weight:700;margin-left:2px;opacity:0.7';
        x.textContent = '\u00d7';
        x.title = 'Remove whitelist rule for ' + domain;
        x.addEventListener('click', function(e) {
            e.stopPropagation();
            _removeRule('@@||' + domain + '^');
        });
        chip.appendChild(txt);
        chip.appendChild(x);
        chips.appendChild(chip);
    });
}

function _removeRule(rule) {
    var textarea = document.getElementById('user-rules');
    if (!textarea) return;
    var lines = textarea.value.split('\n');
    var filtered = lines.filter(function(l) { return l.trim() !== rule; });
    textarea.value = filtered.join('\n');
    // Auto-save and refresh summary
    saveUserRules();
    _renderRulesSummary(textarea.value);
}

function saveUserRules() {
    const rules = document.getElementById('user-rules').value;
    fetch(API+'/dns/adguard/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rules:rules})})
    .then(r=>r.json()).then(d=>{
        if(d.success) { showToast('success','Rules saved'); _renderRulesSummary(rules); }
        else showToast('error',d.error||'Failed');
    })
    .catch(e=>showToast('error',e.message));
}

/* ========== Surveillance ========== */
let survAutoRefreshTimer = null;

async function loadSurveillanceStatus() {
    try {
        const r = await fetch(API+'/surveillance/status');
        const d = await r.json();
        if(d.success && d.status) {
            const s = d.status;
            if(!s.connected) {
                /* Hide the status bar entirely when HA is not available */
                var bar = document.getElementById('surv-status-bar');
                if(bar) bar.style.display = 'none';
                return;
            }
            var bar = document.getElementById('surv-status-bar');
            if(bar) bar.style.display = 'flex';
            var dot = document.getElementById('surv-ha-dot');
            var ver = document.getElementById('surv-ha-version');
            var cnt = document.getElementById('surv-cam-count');
            dot.style.background = '#22c55e';
            dot.style.boxShadow = '0 0 8px rgba(34,197,94,0.6)';
            ver.textContent = 'v' + (s.ha_version||'?');
            cnt.textContent = s.cameras_online + '/' + s.camera_count + ' online';
        }
    } catch(e) { /* status bar best-effort */ }
}

function _showSurvNotConfigured() {
    document.getElementById('surv-not-configured').style.display='block';
    document.getElementById('surv-configured').style.display='none';
    if(typeof lucide!=='undefined') lucide.createIcons();
    stopSurvAutoRefresh();
}

async function loadSurveillance() {
    try {
        const [camRes] = await Promise.all([
            fetch(API+'/surveillance/cameras'),
            loadSurveillanceStatus()
        ]);
        const d = await camRes.json();
        if(!d.success || !d.cameras || !d.cameras.length) {
            _showSurvNotConfigured();
            return;
        }
        document.getElementById('surv-not-configured').style.display='none';
        document.getElementById('surv-configured').style.display='block';
        // Update alarm badge from camera response
        if (d.alarm && d.alarm.state) {
            _updateAlarmBadge(d.alarm.state);
        }
        const grid = document.getElementById('camera-grid');
        grid.textContent='';
        if(d.success && d.cameras && d.cameras.length) {
            d.cameras.forEach(cam=>{
                const entityId = cam.entity_id;
                const isOnline = cam.state && cam.state !== 'unavailable' && cam.state !== 'unknown';
                const card = document.createElement('div');
                card.className = 'camera-card' + (isOnline ? '' : ' offline');
                card.addEventListener('click', function(e){
                    if(e.target.tagName==='BUTTON') return;
                    openCameraModal(entityId, cam.name||entityId, cam.state);
                });

                // Status dot
                const statusDot = document.createElement('div');
                statusDot.className = 'camera-status-dot ' + (isOnline ? 'online' : 'offline');
                card.appendChild(statusDot);

                const img = document.createElement('img');
                img.src = API+'/surveillance/camera/'+encodeURIComponent(entityId)+'/snapshot?t='+Date.now();
                img.alt = cam.name||entityId;
                img.onerror = function(){
                    this.style.background='var(--archie-bg-tertiary)';
                    this.style.opacity='0.3';
                };
                const info = document.createElement('div');
                info.className = 'camera-info';
                const nameDiv = document.createElement('div');
                const nameSpan = document.createElement('div');
                nameSpan.className = 'camera-name';
                nameSpan.textContent = cam.name||entityId;
                const locSpan = document.createElement('div');
                locSpan.className = 'camera-location';
                locSpan.textContent = isOnline ? cam.state : 'OFFLINE';
                locSpan.style.color = isOnline ? '' : '#ef4444';
                nameDiv.appendChild(nameSpan);
                nameDiv.appendChild(locSpan);
                info.appendChild(nameDiv);
                card.appendChild(img);
                card.appendChild(info);
                grid.appendChild(card);
            });
            startSurvAutoRefresh();
        } else {
            showEmpty(grid,'No cameras discovered');
            stopSurvAutoRefresh();
        }
        loadSurveillanceEvents();
    } catch(e) {
        _showSurvNotConfigured();
    }
}

function startSurvAutoRefresh() {
    stopSurvAutoRefresh();
    survAutoRefreshTimer = setInterval(refreshCameraSnapshots, 10000);
}

function stopSurvAutoRefresh() {
    if(survAutoRefreshTimer) { clearInterval(survAutoRefreshTimer); survAutoRefreshTimer = null; }
}

function refreshCameraSnapshots() {
    const imgs = document.querySelectorAll('#camera-grid .camera-card img');
    const t = Date.now();
    imgs.forEach(img=>{
        const base = img.src.split('?')[0];
        img.src = base + '?t=' + t;
    });
}

async function loadSurveillanceEvents() {
    const container = document.getElementById('surv-events');
    try {
        const r = await fetch(API+'/surveillance/events?hours=24');
        const d = await r.json();
        if(d.success && d.events && d.events.length) {
            container.textContent='';
            const rows = d.events.map(ev=>[formatTime(ev.timestamp), ev.camera_entity||'-', createBadge(ev.event_type,'warning'), ev.location||'-']);
            container.appendChild(buildTable(['Time','Camera','Event','Location'], rows));
        } else { showEmpty(container,'No recent events'); }
    } catch(e) { showEmpty(container,'Error loading events'); }
}

var _cameraModalStreaming = false;
var _cameraModalEntityId = null;

function openCameraModal(entityId, name, state) {
    _cameraModalEntityId = entityId;
    _cameraModalStreaming = false;
    const modal = document.getElementById('camera-modal');
    document.getElementById('camera-modal-title').textContent = name.toUpperCase();
    const img = document.getElementById('camera-modal-img');
    img.src = API+'/surveillance/camera/'+encodeURIComponent(entityId)+'/snapshot?t='+Date.now();
    document.getElementById('camera-modal-state').textContent = 'Entity: '+entityId+' | State: '+(state||'unknown');
    document.getElementById('camera-modal-refresh').onclick = function(){
        img.src = API+'/surveillance/camera/'+encodeURIComponent(entityId)+'/snapshot?t='+Date.now();
    };
    // Update stream toggle button
    var streamBtn = document.getElementById('camera-modal-stream');
    if (!streamBtn) {
        streamBtn = document.createElement('button');
        streamBtn.id = 'camera-modal-stream';
        streamBtn.className = 'btn btn-sm';
        streamBtn.style.cssText = 'background:rgba(0,212,255,0.2);border:1px solid rgba(0,212,255,0.4);color:#00d4ff;';
        document.getElementById('camera-modal-refresh').parentNode.appendChild(streamBtn);
    }
    streamBtn.textContent = 'Live Stream';
    streamBtn.onclick = function(){ toggleCameraStream(); };
    modal.classList.add('active');
}

function toggleCameraStream() {
    var img = document.getElementById('camera-modal-img');
    var btn = document.getElementById('camera-modal-stream');
    if (_cameraModalStreaming) {
        _cameraModalStreaming = false;
        img.src = API+'/surveillance/camera/'+_cameraModalEntityId+'/snapshot?t='+Date.now();
        btn.textContent = 'Live Stream';
        btn.style.cssText = 'background:rgba(0,212,255,0.2);border:1px solid rgba(0,212,255,0.4);color:#00d4ff;';
    } else {
        _cameraModalStreaming = true;
        btn.textContent = 'Connecting...';
        btn.style.cssText = 'background:rgba(239,68,68,0.2);border:1px solid rgba(239,68,68,0.4);color:#ef4444;';
        img.onerror = function() {
            btn.textContent = 'Stream Failed — Retry';
            _cameraModalStreaming = false;
        };
        img.onload = function() {
            btn.textContent = 'Stop Stream';
        };
        img.src = API+'/surveillance/camera/'+_cameraModalEntityId+'/stream-proxy';
    }
}

function closeCameraModal() {
    _cameraModalStreaming = false;
    var img = document.getElementById('camera-modal-img');
    if (img) img.src = '';
    document.getElementById('camera-modal').classList.remove('active');
}

function _updateAlarmBadge(state) {
    var badge = document.getElementById('surv-alarm-badge');
    if (!badge) return;
    badge.style.display = 'inline-block';
    if (state === 'armed_away' || state === 'armed_home') {
        badge.textContent = 'ARMED';
        badge.style.cssText = 'font-size:0.72rem;padding:2px 8px;border-radius:4px;background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);';
    } else {
        badge.textContent = 'DISARMED';
        badge.style.cssText = 'font-size:0.72rem;padding:2px 8px;border-radius:4px;background:rgba(34,197,94,0.15);color:#22c55e;border:1px solid rgba(34,197,94,0.3);';
    }
}

function armSystem() {
    var btn = document.getElementById('surv-arm-btn');
    if (btn) btn.textContent = 'Arming...';
    fetch(API+'/surveillance/system/arm',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
        if (btn) btn.innerHTML = '<i data-lucide="shield" style="width:12px;height:12px"></i> Arm';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        if(d.success) {
            showToast('success','System armed — all cameras active');
            _updateAlarmBadge('armed_away');
        } else showToast('error',d.error||'Failed to arm');
    }).catch(function(e){
        if (btn) btn.innerHTML = '<i data-lucide="shield" style="width:12px;height:12px"></i> Arm';
        showToast('error','Error: '+e.message);
    });
}

function disarmSystem() {
    var btn = document.getElementById('surv-disarm-btn');
    if (btn) btn.textContent = 'Disarming...';
    fetch(API+'/surveillance/system/disarm',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
        if (btn) btn.innerHTML = '<i data-lucide="shield-off" style="width:12px;height:12px"></i> Disarm';
        if (typeof lucide !== 'undefined') lucide.createIcons();
        if(d.success) {
            showToast('success','System disarmed');
            _updateAlarmBadge('disarmed');
        } else showToast('error',d.error||'Failed to disarm');
    }).catch(function(e){
        if (btn) btn.innerHTML = '<i data-lucide="shield-off" style="width:12px;height:12px"></i> Disarm';
        showToast('error','Error: '+e.message);
    });
}

function refreshSurveillance() {
    showToast('success','Refreshing cameras...');
    loadSurveillance();
}

/* ========== Reconnaissance ========== */
/* ========== VULNERABILITY SCANNERS — LCARS Cards + Profiles ========== */
var activeScannerType = '';
var scannerData = {};
var runningPollTimer = null;
var scanElapsedTimers = {};

var SCANNER_COLORS = {
    nmap:   {color:'#00ffff', rgb:'0,255,255'},
    nikto:  {color:'#ffaa00', rgb:'255,170,0'},
    nuclei: {color:'#00ff41', rgb:'0,255,65'},
    ssl:    {color:'#0ea5e9', rgb:'14,165,233'},
    zap:    {color:'#ff6b6b', rgb:'239,68,68'}
};

var SCANNER_ICONS = {nmap:'network', nikto:'bug', nuclei:'atom', ssl:'lock', zap:'zap'};

function _lucideIcon(name, size, color) {
    var i = document.createElement('i');
    i.setAttribute('data-lucide', name);
    i.style.width = (size||16)+'px';
    i.style.height = (size||16)+'px';
    if(color) i.style.color = color;
    return i;
}

async function loadScannerCards() {
    var grid = document.getElementById('scanner-cards-grid');
    if(!grid) return;
    try {
        var r = await fetch(API+'/scanner/summary');
        var d = await r.json();
        if(!d.success) { showEmpty(grid,'Failed to load scanners'); return; }
        scannerData = d.scanners;
        grid.textContent = '';
        var order = ['nmap','nikto','nuclei','ssl','zap'];
        order.forEach(function(id) {
            var s = scannerData[id];
            if(!s) return;
            var sc = SCANNER_COLORS[id] || {color:'#00ffff',rgb:'0,255,255'};
            var card = document.createElement('div');
            card.className = 'sn-scanner-card';
            card.id = 'scanner-card-'+id;
            card.style.setProperty('--sc-color', sc.color);
            card.style.setProperty('--sc-color-rgb', sc.rgb);
            card.addEventListener('click', function(){ selectScanner(id); });

            /* Header: icon + status dot */
            var header = document.createElement('div');
            header.className = 'sn-sc-header';
            var iconWrap = document.createElement('div');
            iconWrap.className = 'sn-sc-icon';
            iconWrap.appendChild(_lucideIcon(SCANNER_ICONS[id]||'scan', 20));
            header.appendChild(iconWrap);
            var dot = document.createElement('div');
            dot.className = 'sn-sc-status '+(s.container_status==='running'?'online':s.container_status==='exited'?'offline':'unknown');
            header.appendChild(dot);
            card.appendChild(header);

            /* Name + subtitle */
            var name = document.createElement('div');
            name.className = 'sn-sc-name';
            name.textContent = s.label || id.toUpperCase();
            card.appendChild(name);
            var sub = document.createElement('div');
            sub.className = 'sn-sc-subtitle';
            sub.textContent = s.subtitle || '';
            card.appendChild(sub);

            /* Description */
            if(s.description) {
                var desc = document.createElement('div');
                desc.className = 'sn-sc-desc';
                desc.textContent = s.description;
                card.appendChild(desc);
            }

            /* Stats badges */
            var stats = document.createElement('div');
            stats.className = 'sn-sc-stats';
            var total = s.total_findings || 0;
            if(total > 0) {
                var fb = document.createElement('span');
                fb.className = 'sn-sc-stat findings';
                fb.textContent = total + ' finding' + (total!==1?'s':'');
                stats.appendChild(fb);
            }
            var findings = s.findings || {};
            ['critical','high','medium'].forEach(function(sev){
                if(findings[sev]) {
                    var b = document.createElement('span');
                    b.className = 'sn-sev-badge '+sev;
                    b.textContent = findings[sev]+' '+sev;
                    stats.appendChild(b);
                }
            });
            card.appendChild(stats);

            /* Last scan info */
            if(s.last_scan) {
                var ls = document.createElement('div');
                ls.className = 'sn-sc-last-scan';
                ls.textContent = (s.last_scan.target||'—') + ' \u2022 ' + (s.last_scan.started_at ? ArchieTime.format(s.last_scan.started_at,'short') : '—');
                card.appendChild(ls);
            }

            /* Elapsed timer placeholder */
            var elapsed = document.createElement('div');
            elapsed.className = 'sn-sc-elapsed';
            elapsed.id = 'scanner-elapsed-'+id;
            elapsed.style.display = 'none';
            card.appendChild(elapsed);

            grid.appendChild(card);
        });
        if(typeof lucide !== 'undefined') lucide.createIcons();
        /* Check for running scans */
        pollRunningScans();
    } catch(e) { showEmpty(grid,'Error loading scanners: '+e.message); }
}

function selectScanner(type) {
    activeScannerType = type;
    /* Highlight active card */
    document.querySelectorAll('.sn-scanner-card').forEach(function(c){ c.classList.remove('active'); });
    var card = document.getElementById('scanner-card-'+type);
    if(card) card.classList.add('active');

    /* Open LCARS modal */
    var modal = document.getElementById('scan-launch-modal');
    var sc = SCANNER_COLORS[type] || {color:'#00ffff', rgb:'0,255,255'};
    modal.style.setProperty('--bm-accent', sc.color);
    modal.style.setProperty('--bm-accent-rgb', sc.rgb);
    var meta = scannerData[type] || {};
    document.getElementById('scan-launch-title').textContent = (meta.label || type.toUpperCase()) + ' SCAN';
    document.getElementById('scan-target').placeholder = type==='ssl'?'example.com':'IP, hostname, or URL';
    document.getElementById('scan-target').value = '';
    document.getElementById('scan-confirm-internal').style.display = 'none';

    /* Update profile options */
    var profileSel = document.getElementById('scan-profile');
    profileSel.textContent = '';
    var profiles = meta.profiles || {quick:{label:'Quick'},standard:{label:'Standard'},full:{label:'Full'}};
    Object.keys(profiles).forEach(function(k){
        var opt = document.createElement('option');
        opt.value = k;
        opt.textContent = profiles[k].label || k;
        if(k==='standard') opt.selected = true;
        profileSel.appendChild(opt);
    });
    updateProfileDesc();
    profileSel.onchange = updateProfileDesc;

    modal.classList.add('active');
    if(typeof lucide !== 'undefined') lucide.createIcons();
    setTimeout(function(){ document.getElementById('scan-target').focus(); }, 200);
}

function updateProfileDesc() {
    var profiles = (scannerData[activeScannerType] || {}).profiles || {};
    var sel = document.getElementById('scan-profile').value;
    var desc = document.getElementById('scan-profile-desc');
    var p = profiles[sel];
    desc.textContent = p ? (p.label || sel) : '';
}

function closeScanLaunch() {
    var modal = document.getElementById('scan-launch-modal');
    if(modal) modal.classList.remove('active');
    document.querySelectorAll('.sn-scanner-card').forEach(function(c){ c.classList.remove('active'); });
    activeScannerType = '';
}

function runVulnScan() {
    var target = document.getElementById('scan-target').value.trim();
    if(!target) return showToast('error','Enter a target');
    if(!activeScannerType) return showToast('error','Select a scanner first');

    var internal = ['127.','localhost','192.168.','10.','172.'].some(function(p){return target.indexOf(p)===0;});
    if(internal && !document.getElementById('scan-confirm-checkbox').checked) {
        document.getElementById('scan-confirm-internal').style.display='block';
        return showToast('warning','Confirm internal target scan');
    }

    var profile = document.getElementById('scan-profile').value;
    var body = {target: target, profile: profile};
    if(activeScannerType==='ssl') body.domain = target;
    if(internal) body.confirm_internal = true;

    var endpoint = activeScannerType==='ssl'?'/scanner/ssl':'/scanner/'+activeScannerType;

    /* Set card to scanning state */
    var card = document.getElementById('scanner-card-'+activeScannerType);
    if(card) card.classList.add('scanning');
    startElapsedTimer(activeScannerType);

    showToast('info','Starting '+activeScannerType+' '+profile+' scan...');
    var scanType = activeScannerType;
    fetch(API+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();}).then(function(d){
        stopElapsedTimer(scanType);
        var c = document.getElementById('scanner-card-'+scanType);
        if(c) c.classList.remove('scanning');
        if(d.success){
            showToast('success', scanType.toUpperCase()+' scan complete \u2014 '+(d.findings_count||0)+' findings');
            loadScannerCards();
            loadScanHistory();
        } else {
            showToast('error',d.error||'Scan failed');
        }
    }).catch(function(e){
        stopElapsedTimer(scanType);
        var c = document.getElementById('scanner-card-'+scanType);
        if(c) c.classList.remove('scanning');
        showToast('error',e.message);
    });
}

function startElapsedTimer(scannerId) {
    var start = Date.now();
    var el = document.getElementById('scanner-elapsed-'+scannerId);
    if(el) el.style.display = 'block';
    scanElapsedTimers[scannerId] = setInterval(function(){
        var secs = Math.floor((Date.now()-start)/1000);
        var m = Math.floor(secs/60);
        var s = secs%60;
        if(el) el.textContent = 'SCANNING '+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
    }, 1000);
}

function stopElapsedTimer(scannerId) {
    if(scanElapsedTimers[scannerId]) {
        clearInterval(scanElapsedTimers[scannerId]);
        delete scanElapsedTimers[scannerId];
    }
    var el = document.getElementById('scanner-elapsed-'+scannerId);
    if(el) el.style.display = 'none';
}

async function pollRunningScans() {
    try {
        var r = await fetch(API+'/scanner/running');
        var d = await r.json();
        if(d.success && d.running && d.running.length) {
            d.running.forEach(function(s){
                var scannerId = s.scanner;
                var card = document.getElementById('scanner-card-'+scannerId);
                if(card && !card.classList.contains('scanning')) {
                    card.classList.add('scanning');
                    startElapsedTimer(scannerId);
                }
            });
        }
    } catch(e) { /* silent */ }
}

/* ========== SCAN HISTORY / REPORTS ========== */
async function loadScanHistory() {
    var container = document.getElementById('scan-history-list');
    if(!container) return;
    var filterScanner = (document.getElementById('scan-filter-scanner')||{}).value || '';
    try {
        /* Fetch DB scans + filesystem scans in parallel */
        var results = await Promise.allSettled([
            fetch(API+'/recon/history?limit=50').then(function(r){return r.json();}),
            fetch(API+'/scans').then(function(r){return r.json();})
        ]);
        var dbRes = results[0];
        var fileRes = results[1];
        var dbScans = (dbRes.status==='fulfilled' && dbRes.value.success && dbRes.value.history) ? dbRes.value.history : [];
        var fileScans = (fileRes.status==='fulfilled' && fileRes.value.success && fileRes.value.scans) ? fileRes.value.scans : [];

        /* Normalize */
        var allScans = [];
        dbScans.forEach(function(s){
            allScans.push({
                id: s.id, scanner: s.module_name, target: s.target, status: s.status,
                started_at: s.started_at, completed_at: s.completed_at, source: 'db',
                ts: s.started_at ? new Date(s.started_at).getTime() : 0
            });
        });
        fileScans.forEach(function(s){
            allScans.push({
                scanner: s.scan_type, target: s.filename, status: 'completed',
                started_at: s.created_at ? new Date(s.created_at*1000).toISOString() : null,
                source: 'file', filename: s.filename,
                ts: (s.created_at||0)*1000
            });
        });

        /* Filter */
        if(filterScanner) {
            allScans = allScans.filter(function(s){ return s.scanner === filterScanner; });
        }

        /* Sort newest first */
        allScans.sort(function(a,b){ return (b.ts||0)-(a.ts||0); });

        container.textContent = '';
        if(!allScans.length) { showEmpty(container,'No scan reports yet. Run a scan above.'); return; }

        allScans.slice(0, 50).forEach(function(s) {
            var sc = SCANNER_COLORS[s.scanner] || {color:'#00ffff', rgb:'0,255,255'};
            var card = document.createElement('div');
            card.className = 'sn-report-card';

            var header = document.createElement('div');
            header.className = 'sn-report-header';

            /* Info: icon + scanner + target */
            var info = document.createElement('div');
            info.className = 'sn-report-info';
            var icon = document.createElement('div');
            icon.className = 'sn-report-scanner-icon';
            icon.style.background = 'rgba('+sc.rgb+',0.12)';
            icon.appendChild(_lucideIcon(SCANNER_ICONS[s.scanner]||'scan', 16, sc.color));
            info.appendChild(icon);

            var details = document.createElement('div');
            var title = document.createElement('div');
            title.className = 'sn-report-title';
            title.textContent = (s.scanner||'scan').toUpperCase() + ' \u2014 ' + (s.target||'?');
            details.appendChild(title);

            var meta = document.createElement('div');
            meta.className = 'sn-report-meta';
            var statusBadge = document.createElement('span');
            statusBadge.className = 'sn-sev-badge '+(s.status==='completed'?'low':s.status==='running'?'info':'high');
            statusBadge.textContent = s.status||'unknown';
            meta.appendChild(statusBadge);
            var timeSpan = document.createElement('span');
            timeSpan.textContent = s.started_at ? ArchieTime.format(s.started_at,'short') : '\u2014';
            meta.appendChild(timeSpan);
            details.appendChild(meta);
            info.appendChild(details);
            header.appendChild(info);

            /* Actions */
            var actions = document.createElement('div');
            actions.className = 'sn-report-actions';
            var viewBtn = document.createElement('button');
            viewBtn.className = 'btn btn-sm';
            viewBtn.textContent = 'View';
            if(s.source === 'file') {
                viewBtn.addEventListener('click', function(ev){ ev.stopPropagation(); viewScanFile(s.filename); });
            } else {
                viewBtn.addEventListener('click', function(ev){ ev.stopPropagation(); viewScanReport(s.id); });
            }
            actions.appendChild(viewBtn);

            if(s.source === 'db' && s.id) {
                var delBtn = document.createElement('button');
                delBtn.className = 'btn btn-danger btn-sm';
                delBtn.textContent = 'Del';
                delBtn.addEventListener('click', function(ev){ ev.stopPropagation(); deleteReconScan(s.id); });
                actions.appendChild(delBtn);
            }
            header.appendChild(actions);
            card.appendChild(header);

            /* Expandable detail area */
            var detail = document.createElement('div');
            detail.className = 'sn-report-detail';
            detail.id = 'report-detail-'+(s.id||s.filename);
            card.appendChild(detail);

            card.addEventListener('click', function(){
                detail.classList.toggle('open');
                if(detail.classList.contains('open') && !detail.dataset.loaded) {
                    loadReportDetail(detail, s);
                }
            });

            container.appendChild(card);
        });
        if(typeof lucide !== 'undefined') lucide.createIcons();
    } catch(e) { showEmpty(container,'Error loading scan reports'); }
}

async function loadReportDetail(detailEl, scan) {
    detailEl.dataset.loaded = '1';
    var spinner = document.createElement('div');
    spinner.className = 'loading-state';
    var sp = document.createElement('span');
    sp.className = 'spinner';
    spinner.appendChild(sp);
    spinner.appendChild(document.createTextNode(' Loading...'));
    detailEl.textContent = '';
    detailEl.appendChild(spinner);
    try {
        if(scan.source === 'file') {
            var r = await fetch(API+'/scans/'+encodeURIComponent(scan.filename));
            var d = await r.json();
            if(d.success) {
                var pre = document.createElement('pre');
                pre.textContent = typeof d.content === 'object' ? JSON.stringify(d.content,null,2) : d.content;
                detailEl.textContent = '';
                detailEl.appendChild(pre);
            }
        } else if(scan.id) {
            /* Load findings from DB */
            var results = await Promise.allSettled([
                fetch(API+'/recon/scan/'+scan.id).then(function(r){return r.json();}),
                fetch(API+'/scanner/findings?scanner='+encodeURIComponent(scan.scanner||'')+'&limit=50').then(function(r){return r.json();})
            ]);
            var scanRes = results[0];
            var findingsRes = results[1];
            detailEl.textContent = '';

            /* Findings table */
            var findings = (findingsRes.status==='fulfilled' && findingsRes.value.success) ? findingsRes.value.findings : [];
            var scanFindings = findings.filter(function(f){ return f.scan_id === scan.id; });
            if(scanFindings.length) {
                var rows = scanFindings.map(function(f){
                    var sevBadge = document.createElement('span');
                    sevBadge.className = 'sn-sev-badge '+(f.severity||'info');
                    sevBadge.textContent = f.severity||'info';
                    return [sevBadge, f.finding||'\u2014', f.target||'\u2014'];
                });
                detailEl.appendChild(buildTable(['Severity','Finding','Target'], rows));
            }

            /* Raw results */
            var scanData = (scanRes.status==='fulfilled' && scanRes.value.success) ? scanRes.value.scan : null;
            if(scanData && scanData.results) {
                var pre = document.createElement('pre');
                pre.textContent = typeof scanData.results === 'object' ? JSON.stringify(scanData.results,null,2) : String(scanData.results);
                detailEl.appendChild(pre);
            }
            if(!scanFindings.length && !scanData) {
                detailEl.textContent = 'No detailed results available.';
            }
        }
    } catch(e) {
        detailEl.textContent = 'Error loading details: '+e.message;
    }
}

function viewScanReport(scanId) {
    fetch(API+'/recon/scan/'+scanId).then(function(r){return r.json();}).then(function(d){
        if(!d.success) return showToast('error',d.error||'Failed');
        var modal = document.getElementById('modal-content');
        modal.textContent = '';
        var header = document.createElement('div');
        header.className = 'modal-header';
        var h3 = document.createElement('h3');
        h3.textContent = 'Scan #'+scanId+' \u2014 '+(d.scan?d.scan.module_name:'')+ ' \u2192 '+(d.scan?d.scan.target:'');
        var closeBtn = document.createElement('button');
        closeBtn.className='btn btn-sm'; closeBtn.textContent='Close';
        closeBtn.addEventListener('click', closeModal);
        header.appendChild(h3); header.appendChild(closeBtn);
        modal.appendChild(header);

        var info = document.createElement('div');
        info.style.marginBottom='10px';
        info.appendChild(createBadge(d.scan?d.scan.status:'', d.scan&&d.scan.status==='completed'?'success':'warning'));
        if(d.scan && d.scan.started_at) {
            var ts = document.createElement('span');
            ts.style.cssText='font-size:0.78rem;color:var(--archie-text-muted);margin-left:10px';
            ts.textContent = ArchieTime.format(d.scan.started_at,'short');
            info.appendChild(ts);
        }
        modal.appendChild(info);

        var pre = document.createElement('pre');
        pre.style.cssText='background:var(--archie-bg-tertiary);padding:12px;border-radius:8px;font-size:0.72rem;max-height:450px;overflow:auto;color:var(--archie-text-secondary)';
        var content = d.scan ? (d.scan.results || d.scan.raw_output || d.scan) : {};
        pre.textContent = typeof content==='object'?JSON.stringify(content,null,2):String(content);
        modal.appendChild(pre);
        document.getElementById('modal-overlay').classList.add('open');
    }).catch(function(e){showToast('error',e.message);});
}

function viewScanFile(filename) {
    fetch(API+'/scans/'+encodeURIComponent(filename)).then(function(r){return r.json();}).then(function(d){
        if(!d.success) return;
        var modal = document.getElementById('modal-content');
        modal.textContent='';
        var header = document.createElement('div');
        header.className='modal-header';
        var h3 = document.createElement('h3');
        h3.textContent=filename;
        var closeBtn = document.createElement('button');
        closeBtn.className='btn btn-sm'; closeBtn.textContent='Close';
        closeBtn.addEventListener('click',closeModal);
        header.appendChild(h3); header.appendChild(closeBtn);
        modal.appendChild(header);
        var pre = document.createElement('pre');
        pre.style.cssText='background:var(--archie-bg-tertiary);padding:12px;border-radius:8px;font-size:0.72rem;max-height:450px;overflow:auto;color:var(--archie-text-secondary)';
        pre.textContent = typeof d.content==='object'?JSON.stringify(d.content,null,2):d.content;
        modal.appendChild(pre);
        document.getElementById('modal-overlay').classList.add('open');
    }).catch(function(e){showToast('error',e.message);});
}

function deleteReconScan(scanId) {
    if(!confirm('Delete scan #'+scanId+'?')) return;
    fetch(API+'/recon/scan/'+scanId,{method:'DELETE'}).then(function(r){return r.json();}).then(function(d){
        if(d.success){showToast('success','Scan deleted');loadScanHistory();loadReconHistory();}else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

/* ========== RECONNAISSANCE — Categorized Module Grid ========== */
var RECON_CAT_COLORS = {
    network:   {color:'#00ffff', rgb:'0,255,255'},
    web:       {color:'#ffaa00', rgb:'255,170,0'},
    threat:    {color:'#ff6b6b', rgb:'239,68,68'},
    discovery: {color:'#8b5cf6', rgb:'139,92,246'},
    scanning:  {color:'#00ff41', rgb:'0,255,65'}
};

async function loadReconModules() {
    var container = document.getElementById('recon-modules-container');
    var select = document.getElementById('recon-module');
    if(!container) return;
    try {
        var r = await fetch(API+'/recon/modules');
        var d = await r.json();
        if(!d.success || !d.modules) { showEmpty(container,'Failed to load modules'); return; }

        container.textContent = '';
        select.textContent = '';
        var mods = d.modules;
        /* Populate recon campaign checkboxes */
        populateReconCampaignChecks(mods);
        var categories = (typeof mods === 'object' && !Array.isArray(mods)) ? mods : {other: mods};

        Object.keys(categories).forEach(function(cat) {
            var catColor = RECON_CAT_COLORS[cat] || {color:'#00ffff', rgb:'0,255,255'};
            var section = document.createElement('div');
            section.className = 'sn-recon-category';
            section.style.setProperty('--cat-color', catColor.color);
            section.style.setProperty('--cat-color-rgb', catColor.rgb);

            var header = document.createElement('div');
            header.className = 'sn-recon-cat-header';
            header.textContent = cat.toUpperCase() + ' (' + (categories[cat]||[]).length + ')';
            section.appendChild(header);

            var grid = document.createElement('div');
            grid.className = 'sn-recon-module-grid';

            (categories[cat]||[]).forEach(function(m) {
                var moduleId = m.id || m.name;
                /* Add to dropdown */
                var opt = document.createElement('option');
                opt.value = moduleId;
                opt.textContent = m.name + ' ('+cat+')';
                select.appendChild(opt);

                /* Module card */
                var card = document.createElement('div');
                card.className = 'sn-recon-mod';
                card.addEventListener('click', function(){
                    document.querySelectorAll('.sn-recon-mod').forEach(function(c){c.classList.remove('selected');});
                    card.classList.add('selected');
                    select.value = moduleId;
                    openReconLaunch(m, cat);
                });

                var modName = document.createElement('div');
                modName.className = 'sn-recon-mod-name';
                modName.textContent = m.name;
                card.appendChild(modName);

                var desc = document.createElement('div');
                desc.className = 'sn-recon-mod-desc';
                desc.textContent = m.description || '';
                card.appendChild(desc);

                grid.appendChild(card);
            });

            section.appendChild(grid);
            container.appendChild(section);
        });
    } catch(e) { showEmpty(container,'Error loading modules: '+e.message); }
}

async function loadReconHistory() {
    var container = document.getElementById('recon-history');
    if(!container) return;
    try {
        var r = await fetch(API+'/recon/history?limit=30');
        var d = await r.json();
        if(d.success && d.history && d.history.length) {
            container.textContent='';
            var rows = d.history.map(function(s){
                var statusCls = s.status==='completed'?'success':s.status==='running'?'warning':'danger';
                var actions = document.createElement('div');
                actions.style.display='flex'; actions.style.gap='4px';
                var viewBtn = document.createElement('button');
                viewBtn.className='btn btn-sm'; viewBtn.textContent='View';
                viewBtn.addEventListener('click',function(){viewScanReport(s.id);});
                var delBtn = document.createElement('button');
                delBtn.className='btn btn-danger btn-sm'; delBtn.textContent='Del';
                delBtn.addEventListener('click',function(){deleteReconScan(s.id);});
                actions.appendChild(viewBtn); actions.appendChild(delBtn);
                return ['#'+s.id, s.module_name, s.target, createBadge(s.status,statusCls), formatTime(s.started_at), actions];
            });
            container.appendChild(buildTable(['ID','Module','Target','Status','Started',''], rows));
        } else { showEmpty(container,'No scan history yet. Select a module above and run a scan.'); }
    } catch(e) { showEmpty(container,'Error loading scan history'); }
}

function openReconLaunch(moduleData, category) {
    var modal = document.getElementById('recon-launch-modal');
    var catColor = RECON_CAT_COLORS[category] || {color:'#8b5cf6', rgb:'139,92,246'};
    modal.style.setProperty('--bm-accent', catColor.color);
    modal.style.setProperty('--bm-accent-rgb', catColor.rgb);
    document.getElementById('recon-launch-title').textContent = (moduleData.name || 'SCAN').toUpperCase();
    document.getElementById('recon-launch-desc').textContent = moduleData.description || '';
    document.getElementById('recon-target').value = '';
    modal.classList.add('active');
    if(typeof lucide !== 'undefined') lucide.createIcons();
    setTimeout(function(){ document.getElementById('recon-target').focus(); }, 200);
}

function closeReconLaunch() {
    var modal = document.getElementById('recon-launch-modal');
    if(modal) modal.classList.remove('active');
    document.querySelectorAll('.sn-recon-mod').forEach(function(c){c.classList.remove('selected');});
}

function startReconScan() {
    closeReconLaunch();
    var module_name = document.getElementById('recon-module').value;
    var target = document.getElementById('recon-target').value.trim();
    if(!module_name||!target) return showToast('error','Select a module and enter a target');
    showToast('info','Starting '+module_name+' scan...');
    fetch(API+'/recon/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({module_name:module_name,target:target})})
    .then(function(r){return r.json();}).then(function(d){
        if(d.success){showToast('success','Scan started (ID: '+d.scan_id+')');setTimeout(loadReconHistory,2000);}
        else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

/* ========== RECON CAMPAIGN ========== */
function populateReconCampaignChecks(modules) {
    var container = document.getElementById('recon-campaign-checks');
    if(!container) return;
    container.textContent = '';
    var categories = (typeof modules === 'object' && !Array.isArray(modules)) ? modules : {other: modules};
    var catColors = {network:'#00ffff', web:'#ffaa00', threat:'#ff6b6b', discovery:'#8b5cf6', scanning:'#00ff41'};
    Object.keys(categories).forEach(function(cat){
        (categories[cat]||[]).forEach(function(m){
            var moduleId = m.id || m.name;
            var color = catColors[cat] || '#00ffff';
            var label = document.createElement('label');
            label.className = 'sn-check-item';
            label.style.setProperty('--chk-color', color);
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = moduleId;
            /* Default check popular ones */
            if(['dns_lookup','whois','port_scan','header_analysis','tls_check'].indexOf(moduleId) !== -1) cb.checked = true;
            label.appendChild(cb);
            var txt = document.createTextNode(' ' + m.name);
            label.appendChild(txt);
            container.appendChild(label);
        });
    });
}

function launchReconCampaign() {
    var client = document.getElementById('recon-campaign-client').value.trim();
    var target = document.getElementById('recon-campaign-target').value.trim();
    if(!client) return showToast('error','Enter a client or company name');
    if(!target) return showToast('error','Enter a target');

    var recon_modules = [];
    document.querySelectorAll('#recon-campaign-checks input[type="checkbox"]:checked').forEach(function(cb){
        recon_modules.push(cb.value);
    });
    if(!recon_modules.length) return showToast('error','Select at least one module');

    showToast('info','Launching recon campaign for '+client+' ('+recon_modules.length+' modules)...');
    fetch(API+'/scanner/campaign',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({client_name:client, target:target, profile:'standard', scanners:[], recon_modules:recon_modules})
    }).then(function(r){return r.json();}).then(function(d){
        if(d.success){
            showToast('success','Recon campaign #'+d.campaign_id+' launched: '+recon_modules.length+' modules');
            document.getElementById('recon-campaign-client').value = '';
            document.getElementById('recon-campaign-target').value = '';
            loadReconHistory();
        } else {
            showToast('error',d.error||'Failed');
        }
    }).catch(function(e){showToast('error',e.message);});
}

/* ========== NAGIOS MONITORING ========== */
var nagiosLoaded = false;

async function loadNagiosData() {
    try {
        var [statusRes, hostsRes, servicesRes, problemsRes] = await Promise.allSettled([
            fetch(API+'/nagios/status').then(function(r){return r.json();}),
            fetch(API+'/nagios/hosts').then(function(r){return r.json();}),
            fetch(API+'/nagios/services').then(function(r){return r.json();}),
            fetch(API+'/nagios/problems').then(function(r){return r.json();})
        ]);

        /* Hero stats */
        if(statusRes.status === 'fulfilled' && statusRes.value.success) {
            var s = statusRes.value;
            var hc = (s.hosts && s.hosts.count) ? s.hosts.count : (s.hosts || {});
            var sc = (s.services && s.services.count) ? s.services.count : (s.services || {});
            document.getElementById('nagios-hosts-up').textContent = hc.up || 0;
            document.getElementById('nagios-hosts-down').textContent = hc.down || 0;
            document.getElementById('nagios-svc-ok').textContent = sc.ok || 0;
            document.getElementById('nagios-svc-warn').textContent = sc.warning || 0;
            document.getElementById('nagios-svc-crit').textContent = sc.critical || 0;
        }

        /* Problems */
        var problemsContainer = document.getElementById('nagios-problems');
        if(problemsRes.status === 'fulfilled' && problemsRes.value.success) {
            var p = problemsRes.value.problems;
            var allProblems = (p.hosts || []).concat(p.services || []);
            problemsContainer.textContent = '';
            if(!allProblems.length) {
                var ok = document.createElement('div');
                ok.style.cssText = 'text-align:center;padding:20px;color:var(--archie-green);font-family:Antonio,sans-serif;font-size:0.9rem;letter-spacing:0.1em';
                ok.textContent = 'ALL SYSTEMS OPERATIONAL';
                problemsContainer.appendChild(ok);
            } else {
                allProblems.forEach(function(prob) {
                    var card = document.createElement('div');
                    var status = (prob.status || '').toLowerCase();
                    card.className = 'sn-nagios-problem' + (status === 'warning' ? ' warning' : '');
                    var badge = document.createElement('span');
                    badge.className = 'sn-nagios-status-badge ' + status;
                    badge.textContent = prob.status || 'UNKNOWN';
                    card.appendChild(badge);
                    var name = document.createElement('span');
                    name.className = 'sn-nagios-host-name';
                    name.textContent = (prob.host || prob.name || '') + (prob.service ? ' / ' + prob.service : '');
                    card.appendChild(name);
                    var output = document.createElement('span');
                    output.className = 'sn-nagios-output';
                    output.textContent = prob.plugin_output || '';
                    card.appendChild(output);
                    problemsContainer.appendChild(card);
                });
            }
        }

        /* Hosts */
        var hostsContainer = document.getElementById('nagios-hosts');
        if(hostsRes.status === 'fulfilled' && hostsRes.value.success) {
            hostsContainer.textContent = '';
            (hostsRes.value.hosts || []).forEach(function(h) {
                var card = document.createElement('div');
                card.className = 'sn-nagios-host-card ' + (h.status || '').toLowerCase();
                var badge = document.createElement('span');
                badge.className = 'sn-nagios-status-badge ' + (h.status || '').toLowerCase();
                badge.textContent = h.status || '?';
                card.appendChild(badge);
                var name = document.createElement('span');
                name.className = 'sn-nagios-host-name';
                name.textContent = h.name || '?';
                card.appendChild(name);
                var output = document.createElement('span');
                output.className = 'sn-nagios-output';
                output.textContent = h.plugin_output || '';
                card.appendChild(output);
                hostsContainer.appendChild(card);
            });
            if(!(hostsRes.value.hosts || []).length) showEmpty(hostsContainer, 'No hosts found');
        }

        /* Services */
        var servicesContainer = document.getElementById('nagios-services');
        if(servicesRes.status === 'fulfilled' && servicesRes.value.success) {
            servicesContainer.textContent = '';
            var svcs = servicesRes.value.services || [];
            if(svcs.length) {
                var rows = svcs.map(function(s) {
                    var badge = document.createElement('span');
                    badge.className = 'sn-nagios-status-badge ' + (s.status || '').toLowerCase();
                    badge.textContent = s.status || '?';
                    return [s.host || '?', s.service || '?', badge, s.plugin_output || ''];
                });
                servicesContainer.appendChild(buildTable(['Host', 'Service', 'Status', 'Output'], rows));
            } else {
                showEmpty(servicesContainer, 'No services found');
            }
        }

        nagiosLoaded = true;
    } catch(e) {
        showToast('error', 'Nagios error: ' + e.message);
    }
}

/* ========== SCAN CAMPAIGNS ========== */
function launchCampaign() {
    var client = document.getElementById('campaign-client').value.trim();
    var target = document.getElementById('campaign-target').value.trim();
    var profile = document.getElementById('campaign-profile').value;
    if(!client) return showToast('error','Enter a client or company name');
    if(!target) return showToast('error','Enter a target');

    var scanners = [];
    document.querySelectorAll('.sn-campaign-checks input[type="checkbox"]:checked').forEach(function(cb){
        scanners.push(cb.value);
    });
    if(!scanners.length) return showToast('error','Select at least one scanner');

    showToast('info','Launching campaign for '+client+'...');
    fetch(API+'/scanner/campaign',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({client_name:client, target:target, profile:profile, scanners:scanners})
    }).then(function(r){return r.json();}).then(function(d){
        if(d.success){
            showToast('success','Campaign #'+d.campaign_id+' launched: '+d.scanners_launched.length+' scanners');
            document.getElementById('campaign-client').value = '';
            document.getElementById('campaign-target').value = '';
            loadCampaigns();
            loadScannerCards();
        } else {
            showToast('error',d.error||'Failed to launch campaign');
        }
    }).catch(function(e){showToast('error',e.message);});
}

async function loadCampaigns() {
    var container = document.getElementById('campaign-list');
    if(!container) return;
    try {
        var r = await fetch(API+'/scanner/campaigns');
        var d = await r.json();
        if(!d.success || !d.campaigns || !d.campaigns.length) {
            showEmpty(container,'No campaigns yet. Launch one above.');
            return;
        }
        container.textContent = '';
        d.campaigns.forEach(function(c) {
            var card = document.createElement('div');
            card.className = 'sn-campaign-card';
            card.addEventListener('click', function(){ viewCampaignReport(c.id); });

            var header = document.createElement('div');
            header.className = 'sn-campaign-card-header';
            var left = document.createElement('div');
            var clientEl = document.createElement('div');
            clientEl.className = 'sn-campaign-client';
            clientEl.textContent = c.client_name;
            left.appendChild(clientEl);
            var meta = document.createElement('div');
            meta.className = 'sn-campaign-meta';
            var statusBadge = document.createElement('span');
            statusBadge.className = 'sn-sev-badge '+(c.status==='completed'?'low':c.status==='running'?'info':'high');
            statusBadge.textContent = c.status;
            meta.appendChild(statusBadge);
            var targetSpan = document.createElement('span');
            targetSpan.textContent = c.target;
            meta.appendChild(targetSpan);
            var timeSpan = document.createElement('span');
            timeSpan.textContent = c.created_at ? ArchieTime.format(c.created_at,'short') : '';
            meta.appendChild(timeSpan);
            left.appendChild(meta);
            header.appendChild(left);

            var viewBtn = document.createElement('button');
            viewBtn.className = 'btn btn-sm';
            viewBtn.textContent = 'Report';
            viewBtn.addEventListener('click', function(ev){ ev.stopPropagation(); viewCampaignReport(c.id); });
            header.appendChild(viewBtn);
            card.appendChild(header);

            /* Scanner badges */
            var scanners = document.createElement('div');
            scanners.className = 'sn-campaign-scanners';
            (c.scanners||[]).forEach(function(s){
                var sc = SCANNER_COLORS[s] || {color:'#00ffff'};
                var badge = document.createElement('span');
                badge.className = 'sn-sev-badge';
                badge.style.background = 'rgba('+((SCANNER_COLORS[s]||{}).rgb||'0,255,255')+',0.15)';
                badge.style.color = sc.color;
                badge.textContent = s;
                scanners.appendChild(badge);
            });
            card.appendChild(scanners);
            container.appendChild(card);
        });
    } catch(e) { showEmpty(container,'Error loading campaigns'); }
}

function viewCampaignReport(campaignId) {
    fetch(API+'/scanner/campaign/'+campaignId).then(function(r){return r.json();}).then(function(d){
        if(!d.success) return showToast('error',d.error||'Failed');
        var modal = document.getElementById('modal-content');
        modal.textContent = '';

        /* Header */
        var header = document.createElement('div');
        header.className = 'modal-header';
        var h3 = document.createElement('h3');
        h3.textContent = d.campaign.client_name + ' \u2014 Campaign Report';
        var closeBtn = document.createElement('button');
        closeBtn.className='btn btn-sm'; closeBtn.textContent='Close';
        closeBtn.addEventListener('click', closeModal);
        header.appendChild(h3); header.appendChild(closeBtn);
        modal.appendChild(header);

        /* Campaign info */
        var info = document.createElement('div');
        info.style.cssText = 'margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center';
        info.appendChild(createBadge(d.campaign.status, d.campaign.status==='completed'?'success':'warning'));
        var tgt = document.createElement('span');
        tgt.style.cssText = 'font-size:0.78rem;color:var(--archie-text-muted)';
        tgt.textContent = 'Target: '+d.campaign.target+' | Profile: '+d.campaign.profile;
        info.appendChild(tgt);
        if(d.campaign.created_at) {
            var ts = document.createElement('span');
            ts.style.cssText = 'font-size:0.72rem;color:var(--archie-text-muted)';
            ts.textContent = ArchieTime.format(d.campaign.created_at,'short');
            info.appendChild(ts);
        }
        modal.appendChild(info);

        /* Scan results summary */
        if(d.scans && d.scans.length) {
            var scanHeader = document.createElement('div');
            scanHeader.style.cssText = 'font-family:Antonio,sans-serif;font-size:0.82rem;letter-spacing:0.1em;color:var(--archie-cyan);margin:12px 0 8px';
            scanHeader.textContent = 'SCANS ('+d.scans.length+')';
            modal.appendChild(scanHeader);

            var scanRows = d.scans.map(function(s){
                var statusBadge = document.createElement('span');
                statusBadge.className = 'sn-sev-badge '+(s.status==='completed'?'low':s.status==='running'?'info':'high');
                statusBadge.textContent = s.status;
                return [(s.scanner||'').toUpperCase(), s.target, statusBadge,
                        s.started_at ? ArchieTime.format(s.started_at,'short') : '\u2014'];
            });
            modal.appendChild(buildTable(['Scanner','Target','Status','Started'], scanRows));
        }

        /* Findings */
        if(d.findings && d.findings.length) {
            var findHeader = document.createElement('div');
            findHeader.style.cssText = 'font-family:Antonio,sans-serif;font-size:0.82rem;letter-spacing:0.1em;color:var(--archie-orange);margin:16px 0 8px';
            findHeader.textContent = 'FINDINGS ('+d.findings.length+')';
            modal.appendChild(findHeader);

            var findRows = d.findings.map(function(f){
                var sevBadge = document.createElement('span');
                sevBadge.className = 'sn-sev-badge '+(f.severity||'info');
                sevBadge.textContent = f.severity||'info';
                return [sevBadge, (f.scanner||'').toUpperCase(), f.finding||'\u2014', f.target||''];
            });
            modal.appendChild(buildTable(['Severity','Scanner','Finding','Target'], findRows));
        } else {
            var noFind = document.createElement('div');
            noFind.style.cssText = 'padding:16px;text-align:center;color:var(--archie-text-muted);font-size:0.8rem';
            noFind.textContent = d.campaign.status==='running' ? 'Scans still running...' : 'No findings recorded.';
            modal.appendChild(noFind);
        }

        document.getElementById('modal-overlay').classList.add('open');
    }).catch(function(e){showToast('error',e.message);});
}

/* ========== SSL Monitors ========== */
async function loadSSLMonitors() {
    var container = document.getElementById('ssl-monitors-list');
    if(!container) return;
    try {
        var r = await fetch(API+'/ssl/monitors');
        var d = await r.json();
        if(d.success && d.monitors && d.monitors.length) {
            container.textContent='';
            d.monitors.forEach(function(m){
                var card = document.createElement('div');
                card.className = 'sn-ssl-card';
                var left = document.createElement('div');
                var domain = document.createElement('div');
                domain.className = 'sn-ssl-domain';
                domain.textContent = m.domain;
                left.appendChild(domain);
                var issuer = document.createElement('div');
                issuer.className = 'sn-ssl-issuer';
                issuer.textContent = m.issuer||'Unknown issuer';
                left.appendChild(issuer);
                card.appendChild(left);

                var days = m.days_until_expiry || 0;
                var expiry = document.createElement('div');
                expiry.className = 'sn-ssl-expiry '+(days>30?'safe':days>7?'warning':'danger');
                expiry.textContent = days+'d remaining';
                card.appendChild(expiry);

                if(m.grade) {
                    card.appendChild(createBadge(m.grade, (m.grade==='A'||m.grade==='A+')?'success':'warning'));
                }
                container.appendChild(card);
            });
        } else {
            container.textContent='';
            var wrap = document.createElement('div');
            wrap.style.cssText='text-align:center;padding:24px;color:var(--archie-text-muted)';
            var msg = document.createElement('p');
            msg.textContent='No SSL monitors configured.';
            wrap.appendChild(msg);
            container.appendChild(wrap);
        }
    } catch(e) { showEmpty(container,'Error loading SSL monitors'); }
}

function showAddSSLModal() {
    var domain = prompt('Enter domain to monitor (e.g., example.com):');
    if(!domain) return;
    fetch(API+'/ssl/monitors',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain})})
    .then(function(r){return r.json();}).then(function(d){if(d.success){showToast('success','SSL monitor added');loadSSLMonitors();}else showToast('error',d.error||'Failed');})
    .catch(function(e){showToast('error',e.message);});
}

function refreshSSLMonitors() {
    fetch(API+'/ssl/refresh',{method:'POST'}).then(function(r){return r.json();}).then(function(d){
        if(d.success){showToast('success','SSL monitors refreshed');loadSSLMonitors();}else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

/* ========== Access Control ========== */
// SYSOPS_API alias — same base URL as SN_API / API
var SYSOPS_API = typeof SN_API !== 'undefined' ? SN_API : '/tools/security-network/api';

function _renderFirewallPanel(panel, fw) {
    panel.textContent = '';
    var wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;gap:16px;flex-wrap:wrap';
    var isActive = fw.active || fw.enabled || fw.status === 'active';
    var items = [
        {label:'STATUS', badge:isActive?'Active':'Inactive', type:isActive?'success':'danger'},
        {label:'RULES', text:String(fw.rules_count||fw.rule_count||(fw.rules?fw.rules.length:0)||0)},
        {label:'DEFAULT', text:fw.default_policy||fw.default_incoming||'-'}
    ];
    items.forEach(function(item){
        var cell = document.createElement('div');
        var lbl = document.createElement('span');
        lbl.style.cssText='font-size:0.72rem;color:var(--archie-text-muted)';
        lbl.textContent = item.label;
        cell.appendChild(lbl);
        cell.appendChild(document.createElement('br'));
        if(item.badge){cell.appendChild(createBadge(item.badge,item.type));}
        else{var v=document.createElement('span');v.style.cssText='font-family:var(--archie-font-mono);color:var(--archie-text-primary)';v.textContent=item.text;cell.appendChild(v);}
        wrap.appendChild(cell);
    });
    panel.appendChild(wrap);
}

async function loadFirewall() {
    var panel = document.getElementById('firewall-panel');
    var rulesDiv = document.getElementById('firewall-rules');

    // Show cached firewall status immediately
    try {
        var cached = localStorage.getItem('sn_firewall_cache');
        if (cached) {
            var cdata = JSON.parse(cached);
            _renderFirewallPanel(panel, cdata.fw);
            var note = document.createElement('div');
            note.style.cssText = 'font-size:0.65rem;color:#666;text-align:right;margin-top:4px';
            note.textContent = 'Cached — refreshing...';
            note.id = 'fw-cache-note';
            panel.appendChild(note);
            if (cdata.rules && cdata.rules.length) {
                _renderFirewallRules(rulesDiv, cdata.rules);
            }
        }
    } catch(e) {}

    // Fetch fresh status
    try {
        var r = await fetch(SYSOPS_API+'/firewall/status');
        var d = await r.json();
        if(d.success) {
            var fw = d.firewall || d;
            _renderFirewallPanel(panel, fw);
            try { var cache = JSON.parse(localStorage.getItem('sn_firewall_cache') || '{}'); cache.fw = fw; cache.ts = Date.now(); localStorage.setItem('sn_firewall_cache', JSON.stringify(cache)); } catch(e) {}
        } else if (!localStorage.getItem('sn_firewall_cache')) {
            showEmpty(panel,'Firewall status unavailable — host agent may be busy');
        } else {
            var n = document.getElementById('fw-cache-note');
            if (n) n.textContent = 'Cached — live refresh failed';
        }
    } catch(e) {
        if (!localStorage.getItem('sn_firewall_cache')) showEmpty(panel,'Error loading firewall');
    }

    // Load rules
    try {
        var r2 = await fetch(SYSOPS_API+'/firewall/rules');
        var d2 = await r2.json();
        var rules = d2.rules || [];
        _renderFirewallRules(rulesDiv, rules);
        try { var cache = JSON.parse(localStorage.getItem('sn_firewall_cache') || '{}'); cache.rules = rules; localStorage.setItem('sn_firewall_cache', JSON.stringify(cache)); } catch(e) {}
    } catch(e) {
        if (!localStorage.getItem('sn_firewall_cache')) showEmpty(rulesDiv,'Error loading rules');
    }
}

function _renderFirewallRules(rulesDiv, rules) {
    rulesDiv.textContent = '';
    if (rules.length === 0) { showEmpty(rulesDiv, 'No firewall rules'); return; }
    var rows = rules.map(function(rule) {
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn-danger btn-sm';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', function(){ deleteFirewallRule(rule.number || rule.id); });
        return [
            rule.number || rule.id || '-',
            createBadge(rule.action || 'allow', (rule.action||'allow')==='allow'?'success':'danger'),
            rule.to || rule.port || '-',
            rule.from || 'Anywhere',
            rule.protocol || '-',
            rule.comment || '-',
            delBtn
        ];
    });
    rulesDiv.appendChild(buildTable(['#','Action','Port','From','Proto','Comment',''], rows));
}

function toggleFirewall(enable) {
    var endpoint = enable ? '/firewall/enable' : '/firewall/disable';
    showToast('success', enable ? 'Enabling firewall...' : 'Disabling firewall...');
    fetch(SYSOPS_API+endpoint,{method:'POST',headers:{'Content-Type':'application/json'}})
    .then(function(r){return r.json();}).then(function(d){
        if(d.success) { showToast('success','Firewall '+(enable?'enabled':'disabled')); loadFirewall(); }
        else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

function addFirewallRule() {
    var port = document.getElementById('fw-port').value.trim();
    var proto = document.getElementById('fw-proto').value;
    var action = document.getElementById('fw-action').value;
    var from = document.getElementById('fw-from').value.trim();
    if(!port) return showToast('error','Port is required');
    var body = {port:parseInt(port), protocol:proto, action:action};
    if(from) body.from = from;
    fetch(SYSOPS_API+'/firewall/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();}).then(function(d){
        if(d.success) { showToast('success','Rule added'); document.getElementById('fw-port').value=''; document.getElementById('fw-from').value=''; loadFirewall(); }
        else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

function deleteFirewallRule(ruleNumber) {
    if(!confirm('Delete firewall rule #'+ruleNumber+'?')) return;
    fetch(SYSOPS_API+'/firewall/delete',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({rule_number:ruleNumber})})
    .then(function(r){return r.json();}).then(function(d){
        if(d.success) { showToast('success','Rule deleted'); loadFirewall(); }
        else showToast('error',d.error||'Failed');
    }).catch(function(e){showToast('error',e.message);});
}

async function loadAutoBlockSettings() {
    const panel = document.getElementById('autoblock-panel');
    try {
        const r = await fetch(API+'/auto-block/settings');
        const d = await r.json();
        if(d.success && d.settings) {
            const s = d.settings;
            panel.textContent='';
            const wrap = document.createElement('div');
            wrap.style.cssText='display:flex;flex-direction:column;gap:8px';
            const lbl = document.createElement('label');
            lbl.style.cssText='display:flex;align-items:center;gap:8px;font-size:0.82rem;color:var(--archie-text-secondary)';
            const toggle = document.createElement('label');
            toggle.className='toggle-switch';
            const input = document.createElement('input');
            input.type='checkbox'; input.checked=s.enabled;
            input.addEventListener('change',function(){updateAutoBlock({enabled:this.checked});});
            const slider = document.createElement('span');
            slider.className='toggle-slider';
            toggle.appendChild(input); toggle.appendChild(slider);
            lbl.appendChild(toggle);
            lbl.appendChild(document.createTextNode('Auto-block enabled'));
            wrap.appendChild(lbl);
            const info = document.createElement('div');
            info.style.cssText='font-size:0.78rem;color:var(--archie-text-muted)';
            info.textContent='Threshold: '+(s.threshold||5)+' failed attempts | Window: '+(s.window_hours||24)+'h';
            wrap.appendChild(info);
            panel.appendChild(wrap);
        } else { showEmpty(panel,'Auto-block settings unavailable'); }
    } catch(e) { showEmpty(panel,'Error loading auto-block'); }
}

function updateAutoBlock(settings) {
    fetch(API+'/auto-block/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)})
    .then(r=>r.json()).then(d=>{if(d.success)showToast('success','Settings updated');else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

async function loadIPAccess() {
    try {
        const r = await fetch(API+'/ip-access');
        const d = await r.json();
        if(!d.success) return;
        const blockedEl = document.getElementById('blocked-ips-list');
        const whiteEl = document.getElementById('whitelisted-ips-list');
        blockedEl.textContent='';
        whiteEl.textContent='';
        if(d.blocked && d.blocked.length) {
            d.blocked.forEach(ip=>{
                const ipStr = typeof ip==='string'?ip:ip.ip_address||ip.ip||'';
                const row = document.createElement('div');
                row.style.cssText='display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--archie-border-muted)';
                const txt = document.createElement('span');
                txt.className='mono'; txt.style.fontSize='0.8rem'; txt.textContent=ipStr;
                const btn = document.createElement('button');
                btn.className='btn btn-success btn-sm'; btn.style.padding='2px 6px'; btn.textContent='Unblock';
                btn.addEventListener('click',function(){unblockIP(ipStr);});
                row.appendChild(txt); row.appendChild(btn);
                blockedEl.appendChild(row);
            });
        } else { const n=document.createElement('div');n.style.cssText='font-size:0.78rem;color:var(--archie-text-muted)';n.textContent='None';blockedEl.appendChild(n); }
        if(d.whitelisted && d.whitelisted.length) {
            d.whitelisted.forEach(ip=>{
                const ipStr = typeof ip==='string'?ip:ip.ip_address||ip.ip||'';
                const row = document.createElement('div');
                row.style.cssText='padding:4px 0;border-bottom:1px solid var(--archie-border-muted)';
                const txt = document.createElement('span');
                txt.className='mono'; txt.style.fontSize='0.8rem'; txt.textContent=ipStr;
                row.appendChild(txt);
                whiteEl.appendChild(row);
            });
        } else { const n=document.createElement('div');n.style.cssText='font-size:0.78rem;color:var(--archie-text-muted)';n.textContent='None';whiteEl.appendChild(n); }
    } catch(e){console.error('IP access error:',e);}
}

function blockIP(ipParam) {
    const ip = ipParam||document.getElementById('ip-input').value.trim();
    const reason = document.getElementById('ip-reason')?document.getElementById('ip-reason').value.trim():'Manually blocked';
    if(!ip) return showToast('error','Enter an IP address');
    fetch(API+'/ip-access/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip_address:ip,reason:reason||'Manually blocked'})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success',ip+' blocked');loadIPAccess();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

function unblockIP(ipParam) {
    const ip = ipParam||document.getElementById('ip-input').value.trim();
    if(!ip) return showToast('error','Enter an IP address');
    fetch(API+'/ip-access/unblock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip_address:ip})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success',ip+' unblocked');loadIPAccess();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

async function loadSecurityEvents() {
    const container = document.getElementById('security-events-list');
    try {
        const r = await fetch(API+'/events?limit=20');
        const d = await r.json();
        if(d.success && d.events && d.events.length) {
            container.textContent='';
            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var hrow = document.createElement('tr');
            ['Time','Type','Severity','Details',''].forEach(function(h) {
                var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th);
            });
            thead.appendChild(hrow);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            d.events.forEach(function(ev) {
                var tr = document.createElement('tr');
                var sevCls = ev.severity==='critical'||ev.severity==='high'?'danger':ev.severity==='medium'?'warning':'info';

                var tdTime = document.createElement('td');
                tdTime.textContent = formatTime(ev.created_at);
                tdTime.style.fontSize = '0.78rem';
                tr.appendChild(tdTime);

                var tdType = document.createElement('td');
                tdType.textContent = ev.event_type || ev.type || '-';
                tr.appendChild(tdType);

                var tdSev = document.createElement('td');
                tdSev.appendChild(createBadge(ev.severity || '-', sevCls));
                tr.appendChild(tdSev);

                var tdDesc = document.createElement('td');
                tdDesc.textContent = ev.description || '';
                tdDesc.style.cssText = 'max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                tdDesc.title = ev.description || '';
                tr.appendChild(tdDesc);

                var tdAction = document.createElement('td');
                if (ev.status !== 'resolved') {
                    var btn = document.createElement('button');
                    btn.className = 'btn btn-success btn-sm';
                    btn.textContent = 'Resolve';
                    btn.addEventListener('click', function() { resolveEvent(ev.id); });
                    tdAction.appendChild(btn);
                } else {
                    tdAction.appendChild(createBadge('Resolved', 'success'));
                }
                tr.appendChild(tdAction);

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            container.appendChild(table);
        } else { showEmpty(container,'No security events recorded'); }
    } catch(e) { showEmpty(container,'Error loading events: ' + e.message); }
}

function resolveEvent(eventId) {
    const notes = prompt('Resolution notes (optional):')||'';
    fetch(API+'/events/'+eventId+'/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:notes})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Event resolved');loadSecurityEvents();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

// Known internal service labels
var _CONN_LABELS = {
    '127.0.0.11': 'Docker DNS',
    '0.0.0.0:3000': 'ARCHIE Platform',
    '0.0.0.0:5000': 'Flask Dev',
    '172.26.0': 'AdGuard Network',
    '172.27.0': 'Docker Bridge',
    '192.168.1.200': 'Hub Server',
    ':5432': 'PostgreSQL',
    ':6379': 'Redis',
    ':11434': 'Ollama',
    ':8188': 'ComfyUI',
    ':53': 'DNS'
};

function _labelConnection(addr) {
    if (!addr || addr === '-') return '';
    for (var pattern in _CONN_LABELS) {
        if (addr.indexOf(pattern) >= 0) return _CONN_LABELS[pattern];
    }
    return '';
}

function _isInternalConn(c) {
    var local = c.local_address || c.laddr || '';
    var remote = c.foreign_address || c.remote_address || c.raddr || '';
    // Internal: Docker DNS, loopback, Docker bridge with no remote
    if (local.indexOf('127.0.0.11') >= 0) return true;
    if (remote === '0.0.0.0:*' || remote === ':::*' || remote === '' || remote === '-') return false; // LISTEN = keep
    if (remote.indexOf('127.') === 0) return true;
    return false;
}

async function loadConnections() {
    var container = document.getElementById('connections-list');
    try {
        var r = await fetch(API+'/connections/active');
        var d = await r.json();
        if(d.success && d.connections && d.connections.length) {
            container.textContent='';

            // Separate into listeners, external, and internal
            var listeners = [], external = [], internal = [];
            d.connections.forEach(function(c) {
                var remote = c.foreign_address || c.remote_address || c.raddr || '';
                var state = c.state || c.status || '';
                if (state === 'LISTEN' || remote === '0.0.0.0:*' || remote === ':::*') {
                    listeners.push(c);
                } else if (_isInternalConn(c)) {
                    internal.push(c);
                } else {
                    external.push(c);
                }
            });

            // Summary stats
            var stats = document.createElement('div');
            stats.style.cssText = 'display:flex;gap:16px;margin-bottom:10px;font-size:0.78rem';
            var s1 = document.createElement('span');
            s1.style.color = '#22c55e';
            s1.textContent = listeners.length + ' listening';
            var s2 = document.createElement('span');
            s2.style.color = '#00e5ff';
            s2.textContent = external.length + ' external';
            var s3 = document.createElement('span');
            s3.style.color = '#888';
            s3.textContent = internal.length + ' internal (hidden)';
            stats.appendChild(s1); stats.appendChild(s2); stats.appendChild(s3);
            container.appendChild(stats);

            // Build table — show listeners + external only
            var visible = listeners.concat(external).slice(0, 40);
            var table = document.createElement('table');
            table.className = 'data-table';
            var thead = document.createElement('thead');
            var hrow = document.createElement('tr');
            ['Proto','Local','Remote','Service','Status'].forEach(function(h) {
                var th = document.createElement('th'); th.textContent = h; hrow.appendChild(th);
            });
            thead.appendChild(hrow);
            table.appendChild(thead);
            var tbody = document.createElement('tbody');
            visible.forEach(function(c) {
                var local = c.local_address || c.laddr || '-';
                var remote = c.foreign_address || c.remote_address || c.raddr || '-';
                var state = c.state || c.status || '-';
                var proto = c.protocol || c.proto || c.type || '-';
                var label = _labelConnection(local) || _labelConnection(remote);

                var tr = document.createElement('tr');
                if (state === 'LISTEN') tr.style.borderLeft = '3px solid rgba(34,197,94,0.4)';

                var tdProto = document.createElement('td');
                tdProto.textContent = proto;
                tr.appendChild(tdProto);

                var tdLocal = document.createElement('td');
                tdLocal.textContent = local;
                tdLocal.style.cssText = 'font-family:monospace;font-size:0.73rem';
                tr.appendChild(tdLocal);

                var tdRemote = document.createElement('td');
                tdRemote.textContent = (remote === '0.0.0.0:*' || remote === ':::*') ? '*' : remote;
                tdRemote.style.cssText = 'font-family:monospace;font-size:0.73rem';
                tr.appendChild(tdRemote);

                var tdService = document.createElement('td');
                if (label) {
                    var tag = document.createElement('span');
                    tag.style.cssText = 'background:rgba(0,229,255,0.1);color:#00e5ff;padding:1px 6px;border-radius:3px;font-size:0.68rem';
                    tag.textContent = label;
                    tdService.appendChild(tag);
                } else {
                    tdService.textContent = '-';
                }
                tr.appendChild(tdService);

                var tdStatus = document.createElement('td');
                var statType = state === 'LISTEN' ? 'success' : state === 'ESTABLISHED' ? 'info' : 'muted';
                tdStatus.appendChild(createBadge(state, statType));
                tr.appendChild(tdStatus);

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            container.appendChild(table);
        } else { showEmpty(container,'No active connections data available'); }
    } catch(e) { showEmpty(container,'Error loading connections: ' + e.message); }
}

/* ========== Reports ========== */
const REPORT_TYPE_LABELS = {
    daily_summary: 'Daily Summary',
    weekly_report: 'Weekly Report',
    device_audit: 'Device Audit',
    dns_analysis: 'DNS Analysis'
};

async function loadReports() {
    const container = document.getElementById('reports-list');
    try {
        const r = await fetch(API+'/reports');
        const d = await r.json();
        const allReports = [];
        if(d.success && d.reports) d.reports.forEach(rp=>allReports.push(rp));
        if(d.success && d.file_reports) d.file_reports.forEach(rp=>allReports.push(rp));

        if(allReports.length) {
            container.textContent='';
            const tbl = document.createElement('table');
            tbl.className='data-table';
            const thead = document.createElement('thead');
            thead.innerHTML='<tr><th>Title</th><th>Type</th><th>Generated</th><th>Actions</th></tr>';
            tbl.appendChild(thead);
            const tbody = document.createElement('tbody');

            allReports.forEach(report=>{
                const tr = document.createElement('tr');
                const tdTitle = document.createElement('td');
                tdTitle.textContent = report.title || report.filename || 'Untitled';
                tr.appendChild(tdTitle);

                const tdType = document.createElement('td');
                const badge = document.createElement('span');
                badge.className='svc-badge';
                badge.textContent = REPORT_TYPE_LABELS[report.report_type] || report.report_type || 'Scan';
                tdType.appendChild(badge);
                tr.appendChild(tdType);

                const tdDate = document.createElement('td');
                if(report.created_at) {
                    const ts = typeof report.created_at==='number' ? new Date(report.created_at*1000).toISOString() : report.created_at;
                    tdDate.textContent = ArchieTime.format(ts, 'short');
                } else { tdDate.textContent = '-'; }
                tr.appendChild(tdDate);

                const tdActions = document.createElement('td');
                tdActions.style.cssText='display:flex;gap:6px';
                if(report.source==='db' && report.id) {
                    const viewBtn = document.createElement('button');
                    viewBtn.className='btn btn-sm';
                    viewBtn.textContent='View';
                    viewBtn.onclick=function(){viewReport(report.id);};
                    tdActions.appendChild(viewBtn);
                }
                if(report.source==='file' && report.filename) {
                    const dlBtn = document.createElement('a');
                    dlBtn.href=API+'/reports/download/'+encodeURIComponent(report.filename);
                    dlBtn.className='btn btn-sm';
                    dlBtn.textContent='Download';
                    tdActions.appendChild(dlBtn);
                }
                tr.appendChild(tdActions);
                tbody.appendChild(tr);
            });
            tbl.appendChild(tbody);
            container.appendChild(tbl);
        } else { showEmpty(container,'No reports generated yet. Use the form above to generate your first report.'); }
    } catch(e) { showEmpty(container,'Error loading reports: '+e.message); }
}

async function generateReport() {
    const btn = document.getElementById('btn-generate-report');
    const reportType = document.getElementById('report-type').value;
    const dateStart = document.getElementById('report-date-start').value || null;
    const dateEnd = document.getElementById('report-date-end').value || null;

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:14px;height:14px"></span> Generating...';

    try {
        const r = await fetch(API+'/reports/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({report_type: reportType, date_start: dateStart, date_end: dateEnd})
        });
        const d = await r.json();
        if(d.success) {
            showToast('success', 'Report generated: ' + d.title);
            loadReports();
        } else {
            showToast('error', d.error || 'Failed to generate report');
        }
    } catch(e) {
        showToast('error', 'Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="file-plus" style="width:14px;height:14px"></i> Generate';
        if(typeof lucide !== 'undefined') lucide.createIcons();
    }
}

async function viewReport(reportId) {
    try {
        const r = await fetch(API+'/reports/'+reportId);
        const d = await r.json();
        if(!d.success) { showToast('error', d.error||'Failed to load report'); return; }
        const rpt = d.report;
        const content = rpt.content || {};

        // XSS guard: report content is built from network/DNS/device-discovery
        // data (hostnames, DNS domains, event descriptions) that an attacker can
        // influence, then injected via innerHTML below. Escape every value.
        const esc = (typeof window !== 'undefined' && window.escHtml) ? window.escHtml : function(v) {
            return String(v == null ? '' : v).replace(/[&<>"']/g, function(c) {
                return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
            });
        };

        let html = '<div style="padding:16px;max-height:70vh;overflow-y:auto">';
        html += '<h2 style="color:var(--archie-text-primary);margin:0 0 4px">' + esc(rpt.title||'Report') + '</h2>';
        html += '<p style="color:var(--archie-text-muted);font-size:0.82rem;margin:0 0 16px">Generated: ' + esc(rpt.created_at||'-') + '</p>';

        if(content.events_by_severity && content.events_by_severity.length) {
            html += '<h3 style="color:var(--archie-accent)">Events by Severity</h3><ul>';
            content.events_by_severity.forEach(e=>{ html += '<li><strong>'+esc(e.severity)+'</strong>: '+esc(e.count)+'</li>'; });
            html += '</ul>';
        }
        if(content.recent_events && content.recent_events.length) {
            html += '<h3 style="color:var(--archie-accent)">Recent Events ('+content.recent_events.length+')</h3>';
            html += '<table class="data-table"><thead><tr><th>Type</th><th>Severity</th><th>Status</th><th>Description</th></tr></thead><tbody>';
            content.recent_events.forEach(e=>{
                html += '<tr><td>'+esc(e.type)+'</td><td>'+esc(e.severity)+'</td><td>'+esc(e.status)+'</td><td>'+esc(e.description||'-')+'</td></tr>';
            });
            html += '</tbody></table>';
        }
        if(content.daily_breakdown) {
            html += '<h3 style="color:var(--archie-accent)">Daily Breakdown</h3><pre style="background:var(--archie-bg-tertiary);padding:12px;border-radius:6px;overflow-x:auto;color:var(--archie-text-secondary)">' + esc(JSON.stringify(content.daily_breakdown, null, 2)) + '</pre>';
        }
        if(content.devices && content.devices.length) {
            html += '<h3 style="color:var(--archie-accent)">Devices ('+esc(content.total_devices)+')</h3>';
            html += '<table class="data-table"><thead><tr><th>Hostname</th><th>IP</th><th>Type</th><th>Zone</th><th>Status</th></tr></thead><tbody>';
            content.devices.forEach(dev=>{
                html += '<tr><td>'+esc(dev.hostname||'-')+'</td><td>'+esc(dev.ip)+'</td><td>'+esc(dev.type||'-')+'</td><td>'+esc(dev.zone||'-')+'</td><td>'+esc(dev.status)+'</td></tr>';
            });
            html += '</tbody></table>';
        }
        if(content.zone_summary && content.zone_summary.length) {
            html += '<h3 style="color:var(--archie-accent)">Zone Summary</h3><ul>';
            content.zone_summary.forEach(z=>{ html += '<li><strong>'+esc(z.zone)+'</strong>: '+esc(z.count)+' devices</li>'; });
            html += '</ul>';
        }
        if(content.dns_changes && content.dns_changes.length) {
            html += '<h3 style="color:var(--archie-accent)">DNS Changes ('+content.dns_changes.length+')</h3>';
            html += '<table class="data-table"><thead><tr><th>Source</th><th>Action</th><th>Domain</th><th>By</th><th>Date</th></tr></thead><tbody>';
            content.dns_changes.forEach(c=>{
                html += '<tr><td>'+esc(c.source)+'</td><td>'+esc(c.action)+'</td><td>'+esc(c.domain||'-')+'</td><td>'+esc(c.changed_by||'-')+'</td><td>'+esc(c.created_at||'-')+'</td></tr>';
            });
            html += '</tbody></table>';
        }
        if(content.dns_providers && content.dns_providers.length) {
            html += '<h3 style="color:var(--archie-accent)">DNS Providers</h3><ul>';
            content.dns_providers.forEach(p=>{ html += '<li><strong>'+esc(p.name)+'</strong> ('+esc(p.type)+') — '+(p.active?'Active':'Inactive')+'</li>'; });
            html += '</ul>';
        }
        if(content.scan_findings && content.scan_findings.length) {
            html += '<h3 style="color:var(--archie-accent)">Scan Findings</h3><ul>';
            content.scan_findings.forEach(f=>{ html += '<li><strong>'+esc(f.severity)+'</strong>: '+esc(f.count)+'</li>'; });
            html += '</ul>';
        }

        // Fallback: show raw JSON if no specific sections rendered
        const hasContent = (content.events_by_severity||[]).length || (content.recent_events||[]).length ||
            content.daily_breakdown || (content.devices||[]).length || (content.dns_changes||[]).length;
        if(!hasContent) {
            html += '<pre style="background:var(--archie-bg-tertiary);padding:12px;border-radius:6px;overflow-x:auto;color:var(--archie-text-secondary)">' + esc(JSON.stringify(content, null, 2)) + '</pre>';
        }

        html += '</div>';

        // Use a simple overlay modal
        const overlay = document.createElement('div');
        overlay.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center';
        overlay.onclick=function(e){if(e.target===overlay)overlay.remove();};
        const modal = document.createElement('div');
        modal.style.cssText='background:var(--archie-bg-secondary);border:1px solid var(--archie-border-muted);border-radius:12px;width:90%;max-width:900px;max-height:85vh;overflow:hidden;position:relative';
        const closeBtn = document.createElement('button');
        closeBtn.textContent='\u00d7';
        closeBtn.style.cssText='position:absolute;top:8px;right:12px;background:none;border:none;color:var(--archie-text-muted);font-size:1.5rem;cursor:pointer;z-index:1';
        closeBtn.onclick=function(){overlay.remove();};
        modal.innerHTML = html;
        modal.appendChild(closeBtn);
        overlay.appendChild(modal);
        document.body.appendChild(overlay);
    } catch(e) { showToast('error', 'Error viewing report: '+e.message); }
}

/* ========== Agent Automation ========== */
let agentPaused = false;

function toggleAgentPanel() {
    const panel = document.getElementById('agent-panel');
    panel.classList.toggle('open');
    if(panel.classList.contains('open')){loadAgentSuggestions();loadAgentActions();loadAgentConfig();}
}

async function loadAgentConfig() {
    try {
        const r = await fetch(API+'/agent/config');
        const d = await r.json();
        if(d.success && d.config) {
            document.getElementById('agent-mode').textContent = d.config.mode||'suggest';
            agentPaused = d.config.paused||false;
            document.getElementById('agent-pause-btn').textContent = agentPaused?'Resume':'Pause';
        }
    } catch(e){console.error('Agent config error:',e);}
}

async function loadAgentSuggestions() {
    try {
        const r = await fetch(API+'/agent/suggestions?limit=10');
        const d = await r.json();
        const container = document.getElementById('agent-suggestions');
        const badge = document.getElementById('agent-badge');
        if(d.success && d.suggestions && d.suggestions.length) {
            badge.style.display='flex'; badge.textContent=d.suggestions.length;
            container.textContent='';
            d.suggestions.forEach(s=>{
                const card = document.createElement('div');
                card.className='suggestion-card';
                const title = document.createElement('div');
                title.className='sg-title'; title.textContent=s.title;
                const desc = document.createElement('div');
                desc.className='sg-desc'; desc.textContent=s.description||'';
                const reason = document.createElement('div');
                reason.className='sg-reason'; reason.textContent=s.reasoning||'';
                const actions = document.createElement('div');
                actions.className='suggestion-actions';
                const approveBtn = document.createElement('button');
                approveBtn.className='btn btn-success btn-sm'; approveBtn.textContent='Approve';
                approveBtn.addEventListener('click',function(){approveSuggestion(s.id);});
                const dismissBtn = document.createElement('button');
                dismissBtn.className='btn btn-sm'; dismissBtn.textContent='Dismiss';
                dismissBtn.addEventListener('click',function(){dismissSuggestion(s.id);});
                actions.appendChild(approveBtn); actions.appendChild(dismissBtn);
                card.appendChild(title); card.appendChild(desc); card.appendChild(reason); card.appendChild(actions);
                container.appendChild(card);
            });
        } else {
            badge.style.display='none';
            showEmpty(container,'No pending suggestions');
        }
    } catch(e){console.error('Suggestions error:',e);}
}

async function loadAgentActions() {
    try {
        const r = await fetch(API+'/agent/actions?limit=10');
        const d = await r.json();
        const container = document.getElementById('agent-actions');
        if(d.success && d.actions && d.actions.length) {
            container.textContent='';
            d.actions.forEach(a=>{
                const item = document.createElement('div');
                item.style.cssText='padding:6px 0;border-bottom:1px solid var(--archie-border-muted)';
                const row = document.createElement('div');
                row.style.cssText='display:flex;justify-content:space-between';
                const txt = document.createElement('span');
                txt.style.cssText='font-size:0.78rem;color:var(--archie-text-secondary)';
                txt.textContent = a.title;
                const statusCls = a.status==='executed'?'success':a.status==='dismissed'?'muted':'warning';
                row.appendChild(txt); row.appendChild(createBadge(a.status,statusCls));
                const tm = document.createElement('div');
                tm.style.cssText='font-size:0.7rem;color:var(--archie-text-muted)';
                tm.textContent = formatTime(a.created_at);
                item.appendChild(row); item.appendChild(tm);
                container.appendChild(item);
            });
        } else { showEmpty(container,'No recent actions'); }
    } catch(e){console.error('Actions error:',e);}
}

function approveSuggestion(id) {
    fetch(API+'/agent/suggestions/'+id+'/approve',{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Suggestion approved');loadAgentSuggestions();loadAgentActions();}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

function dismissSuggestion(id) {
    const reason = prompt('Reason for dismissing (optional):')||'';
    fetch(API+'/agent/suggestions/'+id+'/dismiss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reason:reason})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Suggestion dismissed');loadAgentSuggestions();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

function toggleAgentPause() {
    const endpoint = agentPaused?'/agent/resume':'/agent/pause';
    fetch(API+endpoint,{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){agentPaused=!agentPaused;document.getElementById('agent-pause-btn').textContent=agentPaused?'Resume':'Pause';
        showToast('success',agentPaused?'Agent paused':'Agent resumed');}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

/* ========== Domain Management ========== */
async function loadDomainsOverview() {
    try {
        const r = await fetch(API + '/domains/overview');
        const d = await r.json();
        if (!d.success) {
            // Show error in stats instead of just a toast
            var errMsg = d.error || 'Failed to load';
            document.getElementById('domains-public-ip').textContent = 'Error';
            document.getElementById('domains-dns-count').textContent = '--';
            var errBody = document.getElementById('domains-unified-body');
            if (errBody) {
                errBody.textContent = '';
                var tr = document.createElement('tr');
                var td = document.createElement('td');
                td.colSpan = 2;
                td.style.cssText = 'text-align:center;color:#f97316;padding:20px';
                td.textContent = 'Could not load domain data: ' + errMsg + '. Check Hostinger API configuration in Security Network settings.';
                tr.appendChild(td);
                errBody.appendChild(tr);
            }
            showToast('error', errMsg);
            return;
        }

        document.getElementById('domains-public-ip').textContent = d.public_ip || 'Unknown';
        document.getElementById('domains-dns-count').textContent = Array.isArray(d.dns_records) ? d.dns_records.length : '0';

        // Build unified subdomain map from DNS A records
        const dnsRecords = Array.isArray(d.dns_records) ? d.dns_records : [];
        const subdomains = {};
        dnsRecords.filter(function(r) { return r.type === 'A'; }).forEach(function(r) {
            const name = r.name || '@';
            if (!subdomains[name]) subdomains[name] = {};
            subdomains[name].dnsIP = (r.records && r.records[0] && r.records[0].content) || r.content || '--';
            subdomains[name].ttl = r.ttl;
        });

        const tbody = document.getElementById('domains-unified-body');
        const keys = Object.keys(subdomains).sort();
        if (keys.length === 0) {
            tbody.textContent = '';
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 2;
            td.style.textAlign = 'center';
            td.style.color = 'var(--text-dim)';
            td.textContent = 'No subdomains found';
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
        }

        tbody.textContent = '';
        keys.forEach(function(name) {
            const s = subdomains[name];
            const tr = document.createElement('tr');

            const tdName = document.createElement('td');
            const strong = document.createElement('strong');
            strong.textContent = name;
            tdName.appendChild(strong);
            tr.appendChild(tdName);

            const tdDns = document.createElement('td');
            tdDns.textContent = s.dnsIP || '--';
            tr.appendChild(tdDns);

            tbody.appendChild(tr);
        });

        // Managed Servers
        const servers = Array.isArray(d.servers) ? d.servers : [];
        const serverBody = document.getElementById('domains-servers-body');
        if (serverBody) {
            serverBody.textContent = '';
            if (!servers.length) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = 6; td.style.textAlign = 'center'; td.style.color = 'var(--text-dim)';
                td.textContent = 'No servers registered';
                tr.appendChild(td); serverBody.appendChild(tr);
            } else {
                // Count subdomains per IP for each server
                servers.forEach(function(srv) {
                    const tr = document.createElement('tr');
                    const ip = srv.public_ip || srv.hostname || '--';
                    const meshIp = srv.vpn_ip || '--';

                    // Count how many subdomains point to this server's IP
                    const srvSubdomains = keys.filter(function(k) {
                        return subdomains[k].dnsIP === ip || subdomains[k].dnsIP === srv.hostname;
                    });

                    const tdName = document.createElement('td');
                    const strong = document.createElement('strong');
                    strong.textContent = srv.node_name || 'Unknown';
                    strong.style.color = srv.status === 'online' ? '#10b981' : '#ef4444';
                    tdName.appendChild(strong);
                    if (srv.description) { const desc = document.createElement('div'); desc.style.cssText = 'font-size:0.7rem;color:var(--text-dim)'; desc.textContent = srv.description; tdName.appendChild(desc); }
                    tr.appendChild(tdName);

                    const tdPub = document.createElement('td');
                    tdPub.style.fontFamily = '"IBM Plex Mono",monospace';
                    tdPub.textContent = ip;
                    tr.appendChild(tdPub);

                    const tdMesh = document.createElement('td');
                    tdMesh.style.fontFamily = '"IBM Plex Mono",monospace';
                    tdMesh.textContent = meshIp;
                    tr.appendChild(tdMesh);

                    const tdRole = document.createElement('td');
                    tdRole.textContent = srv.gpu_available ? 'GPU Node' : 'Compute';
                    tr.appendChild(tdRole);

                    const tdStatus = document.createElement('td');
                    const statusSpan = document.createElement('span');
                    statusSpan.style.color = srv.status === 'online' ? '#10b981' : '#ef4444';
                    statusSpan.textContent = '\u25CF ' + (srv.status || 'unknown').toUpperCase();
                    tdStatus.appendChild(statusSpan);
                    tr.appendChild(tdStatus);

                    const tdSubs = document.createElement('td');
                    tdSubs.textContent = srvSubdomains.length ? srvSubdomains.join(', ') : '--';
                    tdSubs.style.cssText = 'font-size:0.75rem;max-width:200px;overflow:hidden;text-overflow:ellipsis';
                    tr.appendChild(tdSubs);

                    serverBody.appendChild(tr);
                });
            }
        }

        // IP Change History
        const ipHistory = Array.isArray(d.ip_history) ? d.ip_history : [];
        const ipBody = document.getElementById('domains-ip-history-body');
        if (ipBody) {
            ipBody.textContent = '';
            if (!ipHistory.length) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = 2; td.style.textAlign = 'center'; td.style.color = 'var(--text-dim)';
                td.textContent = 'No IP changes recorded';
                tr.appendChild(td); ipBody.appendChild(tr);
            } else {
                ipHistory.forEach(function(entry) {
                    const tr = document.createElement('tr');
                    const tdIp = document.createElement('td');
                    tdIp.style.fontFamily = '"IBM Plex Mono",monospace';
                    tdIp.textContent = entry.ip || '--';
                    if (entry.ip === (d.public_ip || '')) { tdIp.style.color = '#10b981'; tdIp.textContent += ' (current)'; }
                    tr.appendChild(tdIp);

                    const tdDate = document.createElement('td');
                    tdDate.textContent = entry.detected_at ? new Date(entry.detected_at).toLocaleString() : '--';
                    tr.appendChild(tdDate);

                    ipBody.appendChild(tr);
                });
            }
        }

        lucide.createIcons();
    } catch (e) {
        showToast('error', 'Failed to load domains overview: ' + e.message);
    }
}

async function refreshPublicIP() {
    try {
        const r = await fetch(API + '/domains/overview');
        const d = await r.json();
        if (d.success && d.public_ip) {
            document.getElementById('domains-public-ip').textContent = d.public_ip;
            showToast('success', 'Public IP refreshed');
        }
    } catch (e) { showToast('error', e.message); }
}

async function loadDomainDnsRecords() {
    try {
        const r = await fetch(API + '/dns/hostinger/records');
        const d = await r.json();
        if (!d.success) { showToast('error', d.error || 'Failed'); return; }

        const records = Array.isArray(d.records) ? d.records : [];
        const tbody = document.getElementById('domains-dns-body');
        tbody.textContent = '';

        if (records.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 4; td.style.textAlign = 'center'; td.style.color = 'var(--text-dim)';
            td.textContent = 'No DNS records';
            tr.appendChild(td); tbody.appendChild(tr);
            return;
        }

        records.forEach(function(rec) {
            const tr = document.createElement('tr');
            tr.addEventListener('click', function() { openDnsModal(rec); });

            const tdType = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge';
            badge.textContent = rec.type || '--';
            tdType.appendChild(badge);
            tr.appendChild(tdType);

            const tdName = document.createElement('td');
            tdName.textContent = rec.name || '--';
            tr.appendChild(tdName);

            const tdContent = document.createElement('td');
            tdContent.style.wordBreak = 'break-all';
            const content = (rec.records && rec.records.map(function(x){return x.content;}).join(', ')) || rec.content || '--';
            tdContent.textContent = content;
            tr.appendChild(tdContent);

            const tdTtl = document.createElement('td');
            tdTtl.textContent = rec.ttl || '--';
            tr.appendChild(tdTtl);

            tbody.appendChild(tr);
        });
    } catch (e) {
        showToast('error', 'Failed to load DNS records: ' + e.message);
    }
}

async function addDomainDnsRecord() {
    const record_type = document.getElementById('dns-add-type').value;
    const name = document.getElementById('dns-add-name').value.trim();
    const content = document.getElementById('dns-add-content').value.trim();
    const ttl = parseInt(document.getElementById('dns-add-ttl').value) || 3600;

    if (!name || !content) { showToast('error', 'Name and content are required'); return; }

    try {
        const r = await fetch(API + '/dns/hostinger/records', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({record_type: record_type, name: name, content: content, ttl: ttl})
        });
        const d = await r.json();
        if (d.success) {
            showToast('success', 'DNS record added');
            document.getElementById('dns-add-name').value = '';
            document.getElementById('dns-add-content').value = '';
            loadDomainDnsRecords();
        } else {
            showToast('error', d.error || 'Failed to add record');
        }
    } catch (e) { showToast('error', e.message); }
}

function _certsTbodyLoading(tbody) {
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'loading-state';
    const sp = document.createElement('span');
    sp.className = 'spinner';
    td.appendChild(sp);
    td.appendChild(document.createTextNode(' Loading...'));
    tr.appendChild(td);
    tbody.appendChild(tr);
}

function _certsTbodyMsg(tbody, msg) {
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.textContent = msg;
    td.style.color = 'var(--archie-text-muted)';
    td.style.textAlign = 'center';
    td.style.padding = '24px';
    tr.appendChild(td);
    tbody.appendChild(tr);
}

async function loadDomainCertificates() {
    const tbody = document.getElementById('domains-certs-body');
    _certsTbodyLoading(tbody);
    try {
        const r = await fetch(API + '/domains/certificates');
        const d = await r.json();
        if (!d.success) { _certsTbodyMsg(tbody, 'Failed to load certificates'); return; }
        const certs = Array.isArray(d.certificates) ? d.certificates : [];
        while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
        if (!certs.length) {
            _certsTbodyMsg(tbody, 'No SSL certificates found');
            return;
        }
        certs.forEach(function(c) {
            const tr = document.createElement('tr');

            const tdDomain = document.createElement('td');
            tdDomain.className = 'mono';
            tdDomain.textContent = Array.isArray(c.domain_names) ? c.domain_names.join(', ') : '--';
            tr.appendChild(tdDomain);

            const tdProvider = document.createElement('td');
            tdProvider.textContent = c.provider || 'custom';
            tr.appendChild(tdProvider);

            const tdFrom = document.createElement('td');
            if (c.expires_on) {
                const created = c.created_on ? new Date(c.created_on).toLocaleDateString() : '--';
                tdFrom.textContent = created;
            } else { tdFrom.textContent = '--'; }
            tr.appendChild(tdFrom);

            const tdExpires = document.createElement('td');
            if (c.expires_on) {
                const exp = new Date(c.expires_on);
                const now = new Date();
                const daysLeft = Math.ceil((exp - now) / 86400000);
                tdExpires.textContent = exp.toLocaleDateString();
                if (daysLeft <= 7) { tdExpires.style.color = '#ef4444'; }
                else if (daysLeft <= 30) { tdExpires.style.color = '#f59e0b'; }
                else { tdExpires.style.color = '#22c55e'; }
            } else { tdExpires.textContent = '--'; }
            tr.appendChild(tdExpires);

            const tdStatus = document.createElement('td');
            const statusSpan = document.createElement('span');
            if (c.expires_on) {
                const exp = new Date(c.expires_on);
                const daysLeft = Math.ceil((exp - new Date()) / 86400000);
                if (daysLeft <= 0) { statusSpan.style.color = '#ef4444'; statusSpan.textContent = '\u25CF Expired'; }
                else if (daysLeft <= 7) { statusSpan.style.color = '#ef4444'; statusSpan.textContent = '\u25CF Expiring (' + daysLeft + 'd)'; }
                else if (daysLeft <= 30) { statusSpan.style.color = '#f59e0b'; statusSpan.textContent = '\u25CF Renew Soon (' + daysLeft + 'd)'; }
                else { statusSpan.style.color = '#22c55e'; statusSpan.textContent = '\u25CF Valid (' + daysLeft + 'd)'; }
            } else { statusSpan.style.color = '#6b7280'; statusSpan.textContent = '\u25CF Unknown'; }
            tdStatus.appendChild(statusSpan);
            tr.appendChild(tdStatus);

            tbody.appendChild(tr);
        });
    } catch (e) {
        showToast('error', 'Failed to load certificates: ' + e.message);
        _certsTbodyMsg(tbody, 'Error loading certificates');
    }
}

async function quickSetupDomain() {
    const subdomain = document.getElementById('qs-subdomain').value.trim();
    const forward_host = document.getElementById('qs-forward-host').value.trim();
    const forward_port = parseInt(document.getElementById('qs-forward-port').value) || 3000;

    if (!subdomain) { showToast('error', 'Subdomain is required'); return; }

    const btn = document.getElementById('qs-btn');
    btn.disabled = true;
    btn.textContent = 'Setting up...';
    const resultDiv = document.getElementById('qs-result');
    resultDiv.style.display = 'none';

    try {
        const r = await fetch(API + '/domains/quick-setup', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({subdomain: subdomain, forward_host: forward_host, forward_port: forward_port})
        });
        const d = await r.json();

        resultDiv.style.display = 'block';
        resultDiv.textContent = '';

        if (d.success) {
            showToast('success', d.message || 'Subdomain created!');
            const heading = document.createElement('div');
            heading.style.cssText = 'color:#22c55e;font-weight:bold;margin-bottom:8px';
            heading.textContent = '\u2713 Setup Complete';
            resultDiv.appendChild(heading);

            const domainInfo = document.createElement('div');
            domainInfo.style.color = 'var(--text)';
            domainInfo.textContent = 'Domain: ' + (d.domain || '');
            resultDiv.appendChild(domainInfo);

            if (d.steps) {
                const stepsInfo = document.createElement('div');
                stepsInfo.style.cssText = 'margin-top:8px;font-size:0.8rem;color:var(--text-dim)';
                stepsInfo.textContent = 'DNS: ' + (d.steps.dns && d.steps.dns.success ? '\u2713' : '\u2717')
                    + ' | Proxy: ' + (d.steps.proxy && d.steps.proxy.success ? '\u2713' : '\u2717')
                    + ' | SSL: ' + (d.steps.ssl && d.steps.ssl.success ? '\u2713' : '\u2717');
                resultDiv.appendChild(stepsInfo);
            }

            document.getElementById('qs-subdomain').value = '';
            domainsTabLoaded = false;
            loadDomainsOverview();
        } else {
            showToast('error', d.error || 'Setup failed');
            const heading = document.createElement('div');
            heading.style.cssText = 'color:#ef4444;font-weight:bold';
            heading.textContent = '\u2717 Setup Failed';
            resultDiv.appendChild(heading);

            const errInfo = document.createElement('div');
            errInfo.style.cssText = 'color:var(--text-dim);font-size:0.85rem';
            errInfo.textContent = d.error || 'Unknown error';
            resultDiv.appendChild(errInfo);
        }
    } catch (e) {
        showToast('error', 'Setup failed: ' + e.message);
        resultDiv.style.display = 'block';
        resultDiv.textContent = 'Error: ' + e.message;
    } finally {
        btn.disabled = false;
        btn.textContent = '';
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'rocket');
        icon.style.cssText = 'width:14px;height:14px';
        btn.appendChild(icon);
        btn.appendChild(document.createTextNode(' Create Subdomain'));
        lucide.createIcons();
    }
}

/* ========== DNS Record Modal ========== */
let dnsEditState = { name: null, type: null, isNew: false };

function openDnsModal(record) {
    dnsEditState.name = record ? record.name : null;
    dnsEditState.type = record ? record.type : null;
    dnsEditState.isNew = !record;

    const title = document.getElementById('dns-modal-title');
    const delBtn = document.getElementById('dns-delete-btn');
    title.textContent = record ? 'EDIT DNS RECORD' : 'ADD DNS RECORD';
    delBtn.style.display = record ? '' : 'none';

    document.getElementById('dns-edit-type').value = record ? record.type : 'A';
    document.getElementById('dns-edit-name').value = record ? record.name : '';
    document.getElementById('dns-edit-content').value = record ? ((record.records && record.records[0]) ? record.records[0].content : record.content || '') : '';
    document.getElementById('dns-edit-ttl').value = record ? (record.ttl || 300) : 300;

    document.getElementById('dns-edit-modal').classList.add('active');
}

function closeDnsModal() {
    document.getElementById('dns-edit-modal').classList.remove('active');
}

async function saveDnsRecord() {
    const type = document.getElementById('dns-edit-type').value;
    const name = document.getElementById('dns-edit-name').value.trim();
    const content = document.getElementById('dns-edit-content').value.trim();
    const ttl = parseInt(document.getElementById('dns-edit-ttl').value) || 300;

    if (!name || !content) { showToast('error', 'Name and content are required'); return; }

    try {
        const r = await fetch(API + '/dns/hostinger/records', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ type: type, name: name, content: content, ttl: ttl })
        });
        const d = await r.json();
        if (d.success) {
            showToast('success', 'DNS record saved');
            closeDnsModal();
            loadDomainDnsRecords();
            loadDomainsOverview();
        } else {
            showToast('error', d.error || 'Failed to save');
        }
    } catch (e) { showToast('error', e.message); }
}

async function deleteDnsRecord() {
    if (!dnsEditState.name) return;
    if (!confirm('Delete DNS record "' + dnsEditState.name + '"?')) return;

    try {
        const r = await fetch(API + '/dns/hostinger/records/' + encodeURIComponent(dnsEditState.name), {
            method: 'DELETE'
        });
        const d = await r.json();
        if (d.success) {
            showToast('success', 'DNS record deleted');
            closeDnsModal();
            loadDomainDnsRecords();
            loadDomainsOverview();
        } else {
            showToast('error', d.error || 'Failed to delete');
        }
    } catch (e) { showToast('error', e.message); }
}

/* Close modals on Escape */
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeDnsModal(); closeDeviceModal(); closeBlockDomainModal(); if(typeof closeReportModal==='function') closeReportModal(); if(typeof closeCameraModal==='function') closeCameraModal(); }
});

/* ========== Security Station Ops ========== */
/* ── Security Station Ops (matches Consciousness pattern) ── */
var _secOps = null;

function _getSecOps() {
    if (!_secOps) {
        if (typeof DepartmentOps === 'undefined') return null;
        _secOps = new DepartmentOps({
            stationCode: 'SECURITY',
            moduleSource: 'security_network',
            agentsElId: 'secOpsAgents',
            jobsElId: 'secOpsJobs',
            commandsElId: 'secOpsCommands',
            statusElId: 'secOpsOnline',
            commands: [
                { label: 'NMAP SCAN', cls: 'amber', fn: "openQuickScanModal('nmap_scan','NMAP SCAN','Target IP/Host','192.168.1.0/24')", id: 'secCmdNmap' },
                { label: 'SSL CHECK', cls: 'green', fn: "openQuickScanModal('testssl_scan','SSL CHECK','Domain','platform.kytranempowerment.com')", id: 'secCmdSsl' },
                { label: 'DEVICE AUDIT', cls: 'cyan', fn: "switchSecurityTab('devices')", id: 'secCmdDevices' },
                { label: 'DNS REPORT', cls: 'purple', fn: "switchSecurityTab('dns')", id: 'secCmdDns' }
            ],
            onCapacityChange: function(atCap) {
                ['secCmdNmap','secCmdSsl','secCmdDevices','secCmdDns'].forEach(function(id) {
                    var btn = document.getElementById(id);
                    if (btn) { btn.disabled = atCap; btn.title = atCap ? 'Station at capacity — all agents busy' : ''; }
                });
                var status = document.getElementById('secOpsOnline');
                if (status) {
                    var dot = status.querySelector('.cs-ops-dot');
                    var txt = status.childNodes[status.childNodes.length - 1];
                    if (atCap) {
                        if (dot) { dot.style.background = '#f59e0b'; dot.style.boxShadow = '0 0 4px #f59e0b'; }
                        if (txt && txt.nodeType === 3) txt.textContent = ' AT CAPACITY';
                        status.style.color = '#f59e0b';
                    } else {
                        if (dot) { dot.style.background = ''; dot.style.boxShadow = ''; }
                        if (txt && txt.nodeType === 3) txt.textContent = ' ONLINE';
                        status.style.color = '';
                    }
                }
            }
        });
    }
    return _secOps;
}

function renderSecurityOps(jobData) {
    var ops = _getSecOps();
    if (ops) ops.render(jobData);
}

function initSecurityStation() {
    renderSecurityOps();
}

/* ========== Device Registry ========== */
var _deviceEditId = null;
var _deviceIsRegistered = false;

var _zoneColors = {trusted:'#22c55e',family:'#3b82f6',guest:'#f59e0b',iot:'#8b5cf6',quarantined:'#ef4444'};

function _zoneBadge(zone) {
    var span = document.createElement('span');
    span.textContent = zone || 'unknown';
    span.style.cssText = 'display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.72rem;color:#fff;background:' + (_zoneColors[zone] || '#666');
    return span;
}

function _onlineIndicator(lastSeen) {
    var span = document.createElement('span');
    span.style.cssText = 'display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;';
    if (lastSeen) {
        var diff = (Date.now() - new Date(lastSeen).getTime()) / 60000;
        span.style.background = diff <= 15 ? '#22c55e' : '#666';
    } else {
        span.style.background = '#666';
    }
    return span;
}

function _timeAgo(timestamp) {
    if (!timestamp) return 'Never';
    var diff = (Date.now() - new Date(timestamp).getTime()) / 1000;
    if (diff < 60) return 'Just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return formatTime(timestamp);
}

async function loadDeviceClients() {
    var zone = document.getElementById('dev-filter-zone').value;
    var dtype = document.getElementById('dev-filter-type').value;
    try {
        var statsRes = await fetch(API + '/devices/stats');
        var statsData = await statsRes.json();
        if (statsData.success) {
            var s = statsData.stats || statsData;
            document.getElementById('dev-total').textContent = s.total || 0;
            document.getElementById('dev-online').textContent = s.online || 0;
            document.getElementById('dev-unreg').textContent = s.unregistered || 0;
        }
    } catch(e) { console.warn('Device stats error:', e); }

    // Unregistered devices
    try {
        var unregRes = await fetch(API + '/devices/unregistered');
        var unregData = await unregRes.json();
        var unregSection = document.getElementById('dev-unreg-section');
        var unregBody = document.getElementById('dev-unreg-body');
        unregBody.textContent = '';
        if (unregData.success && unregData.devices && unregData.devices.length > 0) {
            unregSection.style.display = '';
            unregData.devices.forEach(function(d) {
                var tr = document.createElement('tr');
                tr.style.cursor = 'pointer';
                tr.addEventListener('click', function() { openDeviceModal(d); });
                var cells = [d.ip_address||'', d.mac_address||'', d.manufacturer||'Unknown'];
                cells.forEach(function(val) {
                    var td = document.createElement('td');
                    td.textContent = val;
                    tr.appendChild(td);
                });
                // DNS active tag
                var tdDnsU = document.createElement('td');
                if (d.dns_active) {
                    var dnsBadgeU = document.createElement('span');
                    dnsBadgeU.textContent = '\u2714 Protected';
                    dnsBadgeU.style.cssText = 'background:rgba(34,197,94,0.15);color:#22c55e;padding:2px 8px;border-radius:4px;font-size:0.72rem;border:1px solid rgba(34,197,94,0.3);';
                    dnsBadgeU.title = d.dns_query_count ? d.dns_query_count.toLocaleString() + ' DNS queries' : 'Using AdGuard DNS';
                    tdDnsU.appendChild(dnsBadgeU);
                } else {
                    var noTagU = document.createElement('span');
                    noTagU.textContent = '\u26A0 Unprotected';
                    noTagU.style.cssText = 'background:rgba(239,68,68,0.1);color:#ef4444;padding:2px 8px;border-radius:4px;font-size:0.72rem;border:1px solid rgba(239,68,68,0.2);';
                    tdDnsU.appendChild(noTagU);
                }
                tr.appendChild(tdDnsU);
                // Time cells
                var timeCells = [_timeAgo(d.first_seen_at), _timeAgo(d.last_seen_at)];
                timeCells.forEach(function(val) {
                    var td = document.createElement('td');
                    td.textContent = val;
                    tr.appendChild(td);
                });
                unregBody.appendChild(tr);
            });
        } else {
            unregSection.style.display = 'none';
        }
    } catch(e) { console.warn('Unregistered devices error:', e); }

    // Registered devices
    var regBody = document.getElementById('dev-reg-body');
    regBody.textContent = '';
    var loadTr = document.createElement('tr');
    var loadTd = document.createElement('td');
    loadTd.setAttribute('colspan', '7');
    loadTd.className = 'loading-state';
    loadTd.innerHTML = '<span class="spinner"></span> Loading...';
    loadTr.appendChild(loadTd);
    regBody.appendChild(loadTr);
    try {
        var params = new URLSearchParams();
        if (zone) params.set('zone', zone);
        if (dtype) params.set('type', dtype);
        var regRes = await fetch(API + '/devices?' + params.toString());
        var regData = await regRes.json();
        regBody.textContent = '';
        if (regData.success && regData.devices && regData.devices.length > 0) {
            regData.devices.forEach(function(d) {
                var tr = document.createElement('tr');
                tr.style.cursor = 'pointer';
                tr.addEventListener('click', function() { openDeviceModal(d); });

                var tdName = document.createElement('td');
                tdName.textContent = d.friendly_name || d.hostname || 'Unknown';
                tr.appendChild(tdName);

                var tdIp = document.createElement('td');
                tdIp.textContent = d.ip_address || '';
                tr.appendChild(tdIp);

                var tdType = document.createElement('td');
                tdType.textContent = d.device_type || '';
                tr.appendChild(tdType);

                var tdOwner = document.createElement('td');
                tdOwner.textContent = d.owner || '';
                tr.appendChild(tdOwner);

                var tdZone = document.createElement('td');
                tdZone.appendChild(_zoneBadge(d.security_zone));
                var spacer = document.createTextNode(' ');
                tdZone.appendChild(spacer);
                if (d.dns_active) {
                    var dnsBadge = document.createElement('span');
                    dnsBadge.textContent = '\u2714 ' + (d.dns_query_count ? d.dns_query_count.toLocaleString() : 'Protected');
                    dnsBadge.style.cssText = 'background:rgba(34,197,94,0.15);color:#22c55e;padding:1px 6px;border-radius:3px;font-size:0.68rem;border:1px solid rgba(34,197,94,0.3);margin-left:4px;';
                    dnsBadge.title = d.dns_query_count ? d.dns_query_count.toLocaleString() + ' DNS queries — Protected by AdGuard' : 'Using AdGuard DNS';
                    tdZone.appendChild(dnsBadge);
                } else {
                    var noTag = document.createElement('span');
                    noTag.textContent = '\u26A0 Unprotected';
                    noTag.style.cssText = 'background:rgba(239,68,68,0.1);color:#ef4444;padding:1px 6px;border-radius:3px;font-size:0.68rem;border:1px solid rgba(239,68,68,0.2);margin-left:4px;';
                    noTag.title = 'Not using AdGuard DNS';
                    tdZone.appendChild(noTag);
                }
                tr.appendChild(tdZone);

                var tdSeen = document.createElement('td');
                tdSeen.appendChild(_onlineIndicator(d.last_seen_at));
                var seenText = document.createTextNode(_timeAgo(d.last_seen_at));
                tdSeen.title = d.last_seen_at ? formatTime(d.last_seen_at) : '';
                tdSeen.appendChild(seenText);
                tr.appendChild(tdSeen);

                var tdStatus = document.createElement('td');
                tdStatus.textContent = d.status || 'active';
                tr.appendChild(tdStatus);

                regBody.appendChild(tr);
            });
        } else {
            var emptyTr = document.createElement('tr');
            var emptyTd = document.createElement('td');
            emptyTd.setAttribute('colspan', '7');
            emptyTd.textContent = 'No registered devices found.';
            emptyTd.style.textAlign = 'center';
            emptyTd.style.padding = '24px';
            emptyTd.style.color = 'var(--archie-text-muted)';
            emptyTr.appendChild(emptyTd);
            regBody.appendChild(emptyTr);
        }
    } catch(e) {
        regBody.textContent = '';
        var errTr = document.createElement('tr');
        var errTd = document.createElement('td');
        errTd.setAttribute('colspan', '7');
        errTd.textContent = 'Error loading devices: ' + e.message;
        errTd.style.color = '#ef4444';
        errTr.appendChild(errTd);
        regBody.appendChild(errTr);
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function openDeviceModal(device) {
    _deviceEditId = device ? device.id : null;
    _deviceIsRegistered = device ? !!device.is_registered : false;
    var modal = document.getElementById('device-edit-modal');
    var title = document.getElementById('device-modal-title');
    title.textContent = _deviceIsRegistered ? 'EDIT DEVICE' : 'REGISTER DEVICE';

    document.getElementById('dev-edit-name').value = device ? (device.friendly_name || device.hostname || '') : '';
    document.getElementById('dev-edit-type').value = device ? (device.device_type || 'other') : 'other';
    document.getElementById('dev-edit-owner').value = device ? (device.owner || '') : '';
    document.getElementById('dev-edit-zone').value = device ? (device.security_zone || 'guest') : 'guest';
    document.getElementById('dev-edit-status').value = device ? (device.status || 'active') : 'active';
    document.getElementById('dev-edit-mac').value = device ? (device.mac_address || '') : '';
    document.getElementById('dev-edit-ip').value = device ? (device.ip_address || '') : '';
    document.getElementById('dev-edit-manufacturer').value = device ? (device.manufacturer || '') : '';
    document.getElementById('dev-edit-notes').value = device ? (device.notes || '') : '';

    // Show/hide status row and delete button for unregistered devices
    document.getElementById('dev-edit-status-row').style.display = _deviceIsRegistered ? '' : 'none';
    document.getElementById('dev-delete-btn').style.display = _deviceIsRegistered ? '' : 'none';
    document.getElementById('dev-report-btn').style.display = _deviceIsRegistered ? '' : 'none';

    // Set accent color based on zone
    var zone = device ? (device.security_zone || 'guest') : 'guest';
    var accent = _zoneColors[zone] || '#22c55e';
    var r = parseInt(accent.slice(1,3),16), g = parseInt(accent.slice(3,5),16), b = parseInt(accent.slice(5,7),16);
    modal.style.setProperty('--bm-accent', accent);
    modal.style.setProperty('--bm-accent-rgb', r+','+g+','+b);

    modal.classList.add('active');
}

function closeDeviceModal() {
    document.getElementById('device-edit-modal').classList.remove('active');
}

async function saveDevice() {
    var payload = {
        friendly_name: document.getElementById('dev-edit-name').value.trim(),
        device_type: document.getElementById('dev-edit-type').value,
        owner: document.getElementById('dev-edit-owner').value.trim(),
        security_zone: document.getElementById('dev-edit-zone').value,
        status: document.getElementById('dev-edit-status').value,
        mac_address: document.getElementById('dev-edit-mac').value.trim(),
        ip_address: document.getElementById('dev-edit-ip').value.trim(),
        manufacturer: document.getElementById('dev-edit-manufacturer').value.trim(),
        notes: document.getElementById('dev-edit-notes').value.trim()
    };
    if (!payload.friendly_name) return showToast('error', 'Device name is required');
    // Include device ID for registration
    if (_deviceEditId) payload.id = _deviceEditId;
    try {
        var url, method;
        if (_deviceIsRegistered && _deviceEditId) {
            url = API + '/devices/' + _deviceEditId;
            method = 'PUT';
        } else {
            url = API + '/devices/register';
            method = 'POST';
        }
        var res = await fetch(url, {method: method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)});
        var data = await res.json();
        if (data.success) {
            showToast('success', _deviceIsRegistered ? 'Device updated' : 'Device registered');
            closeDeviceModal();
            loadDeviceClients();
        } else {
            showToast('error', data.error || 'Failed to save device');
        }
    } catch(e) {
        showToast('error', 'Error: ' + e.message);
    }
}

async function deleteDeviceFromModal() {
    if (!_deviceEditId) return;
    if (!confirm('Delete this device from the registry?')) return;
    try {
        var res = await fetch(API + '/devices/' + _deviceEditId, {method: 'DELETE'});
        var data = await res.json();
        if (data.success) {
            showToast('success', 'Device deleted');
            closeDeviceModal();
            loadDeviceClients();
        } else {
            showToast('error', data.error || 'Failed to delete device');
        }
    } catch(e) {
        showToast('error', 'Error: ' + e.message);
    }
}

async function syncDevicesToAdguard() {
    try {
        var res = await fetch(API + '/devices/sync', {method: 'POST'});
        var data = await res.json();
        if (data.success) {
            showToast('success', 'Synced ' + (data.synced || 0) + ' devices to AdGuard');
        } else {
            showToast('error', data.error || 'Sync failed');
        }
    } catch(e) {
        showToast('error', 'Error: ' + e.message);
    }
}

/* ========== DNS Report ========== */
function closeReportModal() {
    document.getElementById('device-report-modal').classList.remove('active');
}

async function viewDeviceReport(deviceId) {
    if (!deviceId) return showToast('error', 'No device selected');
    var modal = document.getElementById('device-report-modal');
    var body = document.getElementById('dns-report-body');
    var title = document.getElementById('dns-report-title');
    body.innerHTML = '<p style="color:var(--archie-text-muted)">Loading report...</p>';
    modal.classList.add('active');

    try {
        var res = await fetch(API + '/devices/' + deviceId + '/dns-report');
        var data = await res.json();
        if (!data.success) {
            body.innerHTML = '<p style="color:#ef4444">' + (data.error || 'Failed to load report') + '</p>';
            return;
        }
        var r = data.report;
        title.textContent = 'DNS REPORT — ' + (data.device_name || 'DEVICE').toUpperCase();
        var blockRate = r.total > 0 ? ((r.blocked / r.total) * 100).toFixed(1) : '0.0';

        var html = '';
        // Device info
        html += '<div style="margin-bottom:12px;color:var(--archie-text-muted);font-size:0.82rem">';
        html += '<span style="color:#3b82f6;font-weight:600">' + escapeHtml(data.device_name) + '</span>';
        html += ' &nbsp;|&nbsp; ' + escapeHtml(data.ip_address);
        html += '</div>';

        // Stats row
        html += '<div style="display:flex;gap:16px;margin-bottom:18px">';
        html += '<div style="flex:1;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.3);border-radius:6px;padding:12px;text-align:center">';
        html += '<div style="font-size:1.6rem;font-weight:700;color:#3b82f6">' + r.total + '</div>';
        html += '<div style="font-size:0.72rem;color:var(--archie-text-muted)">TOTAL QUERIES</div></div>';
        html += '<div style="flex:1;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:6px;padding:12px;text-align:center">';
        html += '<div style="font-size:1.6rem;font-weight:700;color:#ef4444">' + r.blocked + '</div>';
        html += '<div style="font-size:0.72rem;color:var(--archie-text-muted)">BLOCKED</div></div>';
        html += '<div style="flex:1;background:rgba(234,179,8,0.1);border:1px solid rgba(234,179,8,0.3);border-radius:6px;padding:12px;text-align:center">';
        html += '<div style="font-size:1.6rem;font-weight:700;color:#eab308">' + blockRate + '%</div>';
        html += '<div style="font-size:0.72rem;color:var(--archie-text-muted)">BLOCK RATE</div></div>';
        html += '</div>';

        // Top Domains
        if (r.top_domains && r.top_domains.length > 0) {
            html += '<div style="margin-bottom:14px">';
            html += '<div style="font-size:0.78rem;font-weight:600;color:#3b82f6;margin-bottom:6px;text-transform:uppercase">Top Domains</div>';
            html += '<table style="width:100%;font-size:0.78rem;border-collapse:collapse">';
            html += '<thead><tr style="border-bottom:1px solid rgba(59,130,246,0.2)"><th style="text-align:left;padding:4px 8px;color:var(--archie-text-muted)">Domain</th><th style="text-align:right;padding:4px 8px;color:var(--archie-text-muted)">Count</th></tr></thead><tbody>';
            for (var i = 0; i < r.top_domains.length; i++) {
                var d = r.top_domains[i];
                html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05)"><td style="padding:4px 8px;word-break:break-all">' + escapeHtml(d.domain) + '</td><td style="text-align:right;padding:4px 8px;font-weight:600">' + d.count + '</td></tr>';
            }
            html += '</tbody></table></div>';
        }

        // Top Blocked
        if (r.top_blocked && r.top_blocked.length > 0) {
            html += '<div style="margin-bottom:14px">';
            html += '<div style="font-size:0.78rem;font-weight:600;color:#ef4444;margin-bottom:6px;text-transform:uppercase">Top Blocked Domains</div>';
            html += '<table style="width:100%;font-size:0.78rem;border-collapse:collapse">';
            html += '<thead><tr style="border-bottom:1px solid rgba(239,68,68,0.2)"><th style="text-align:left;padding:4px 8px;color:var(--archie-text-muted)">Domain</th><th style="text-align:right;padding:4px 8px;color:var(--archie-text-muted)">Count</th></tr></thead><tbody>';
            for (var j = 0; j < r.top_blocked.length; j++) {
                var b = r.top_blocked[j];
                html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05)"><td style="padding:4px 8px;word-break:break-all;color:#ef4444">' + escapeHtml(b.domain) + '</td><td style="text-align:right;padding:4px 8px;font-weight:600">' + b.count + '</td></tr>';
            }
            html += '</tbody></table></div>';
        }

        // Recent Queries
        if (r.recent && r.recent.length > 0) {
            html += '<div>';
            html += '<div style="font-size:0.78rem;font-weight:600;color:var(--archie-text-muted);margin-bottom:6px;text-transform:uppercase">Recent Queries</div>';
            html += '<table style="width:100%;font-size:0.75rem;border-collapse:collapse">';
            html += '<thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)"><th style="text-align:left;padding:4px 6px;color:var(--archie-text-muted)">Time</th><th style="text-align:left;padding:4px 6px;color:var(--archie-text-muted)">Domain</th><th style="text-align:left;padding:4px 6px;color:var(--archie-text-muted)">Type</th><th style="text-align:center;padding:4px 6px;color:var(--archie-text-muted)">Status</th></tr></thead><tbody>';
            for (var k = 0; k < r.recent.length; k++) {
                var q = r.recent[k];
                var badge = q.blocked
                    ? '<span style="background:rgba(239,68,68,0.2);color:#ef4444;padding:2px 6px;border-radius:3px;font-size:0.7rem">BLOCKED</span>'
                    : '<span style="background:rgba(34,197,94,0.2);color:#22c55e;padding:2px 6px;border-radius:3px;font-size:0.7rem">OK</span>';
                var timeStr = q.time ? formatTime(q.time) : '';
                html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.05)">';
                html += '<td style="padding:4px 6px;white-space:nowrap;color:var(--archie-text-muted)">' + escapeHtml(timeStr) + '</td>';
                html += '<td style="padding:4px 6px;word-break:break-all">' + escapeHtml(q.domain) + '</td>';
                html += '<td style="padding:4px 6px">' + escapeHtml(q.type) + '</td>';
                html += '<td style="text-align:center;padding:4px 6px">' + badge + '</td>';
                html += '</tr>';
            }
            html += '</tbody></table></div>';
        }

        if (r.total === 0) {
            html += '<p style="color:var(--archie-text-muted);text-align:center;margin-top:20px">No DNS queries found for this device.</p>';
        }

        body.innerHTML = html;
    } catch(e) {
        body.innerHTML = '<p style="color:#ef4444">Error: ' + e.message + '</p>';
    }
}

function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

/* ========== Init ========== */
document.addEventListener('DOMContentLoaded', function() {
    if(typeof lucide!=='undefined') lucide.createIcons();
    /* initTabs/initSubtabs handled by security-network.js */
    /* loadDashboard removed — overview handled by security-network.js loadNocOverview */
    if (typeof switchSecurityTab === 'function') { switchSecurityTab('overview'); }
    initSecurityStation();
});

setInterval(function(){
    var active = document.querySelector('.tab-btn.active');
    /* 60s poll: overview tab handled by security-network.js _nocPollTimer */
}, 60000);

document.addEventListener('keydown', function(e){ if(e.key==='Escape'){ closeModal(); closeDeviceModal(); } });

// ═══════ COMPLIANCE TAB ═══════
let _complianceResults = [];
let _complianceScanId = null;
let _lastScanId = null;
let _compHistoryChart = null;
let _compliancePendingByRule = {};  // rule_id -> {approval_id, scan_id}

function _compScoreColor(score) { return score >= 80 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'; }
function _compGrade(score) { return score >= 95 ? 'A+' : score >= 90 ? 'A' : score >= 85 ? 'B+' : score >= 80 ? 'B' : score >= 70 ? 'C' : score >= 60 ? 'D' : 'F'; }
function _compEsc(s) { return (s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function _complianceFixButtonHtml(ruleId) {
    var safe = _compEsc(ruleId);
    var pending = _compliancePendingByRule[ruleId];
    if (pending) {
        return '<a class="comp-finding-fix" style="color:#fbbf24;cursor:default" title="Approval #' + pending.approval_id + ' pending — see Department HQ > Approvals" onclick="return false;" href="#">Pending \u23F3</a>';
    }
    return '<a class="comp-finding-fix" onclick="openComplianceActionModal(\'' + safe + '\');return false;" href="#">Review \u25B6</a>';
}

async function runComplianceScan() {
    const statusEl = document.getElementById('compliance-scan-status');
    const btn = document.getElementById('comp-scan-btn');
    statusEl.textContent = 'Scanning all frameworks...';
    statusEl.style.color = 'var(--archie-accent)';
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Scanning...';

    try {
        const resp = await fetch('/tools/security-network/api/compliance/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}'
        });
        const data = await resp.json();

        if (data.scan_id) {
            _lastScanId = data.scan_id;
            statusEl.textContent = 'Last scan: ' + data.score + '% \u2022 ' + data.passed + ' passed \u2022 ' + data.failed + ' failed';
            statusEl.style.color = _compScoreColor(data.score);

            renderScoreCards(data);
            renderFrameworks(data);
            loadComplianceResults(data.scan_id);
            loadComplianceScanHistory();
            loadEvidenceStatus();
            loadHardeningContent(data.scan_id);
        } else {
            statusEl.textContent = 'Scan failed: ' + (data.error || 'Unknown error');
            statusEl.style.color = '#ef4444';
        }
    } catch (e) {
        statusEl.textContent = 'Error: ' + e.message;
        statusEl.style.color = '#ef4444';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-radar"></i> Run Scan';
    }
}

function _buildRingSvg(score, color, size) {
    const dash = Math.round(score);
    return '<svg viewBox="0 0 36 36" class="compliance-ring" style="width:' + (size||90) + 'px;height:' + (size||90) + 'px;">'
        + '<path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="2.5" stroke-linecap="round"/>'
        + '<path class="ring-progress" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="' + color + '" stroke-width="2.5" stroke-dasharray="' + dash + ', 100" stroke-linecap="round"/>'
        + '<text x="18" y="20" text-anchor="middle" fill="' + color + '" font-size="8" font-weight="700">' + score + '%</text>'
        + '</svg>';
}

function renderScoreCards(data) {
    const el = document.getElementById('compliance-scores');
    if (!data.pack_scores) return;

    const overall = { name: 'Overall', score: data.score, passed: data.passed, total: data.total || data.total_rules };
    const packs = [overall, ...Object.entries(data.pack_scores).map(([id, p]) => ({
        name: p.name, score: p.score, passed: p.passed, total: p.total
    }))];

    let html = packs.map(p => {
        const color = _compScoreColor(p.score);
        const grade = _compGrade(p.score);
        return '<div class="comp-ring-card" style="--ring-color: ' + color + ';">'
            + '<div class="ring-label">' + _compEsc(p.name) + '</div>'
            + _buildRingSvg(p.score, color, 90)
            + '<div class="ring-grade" style="color: ' + color + ';">Grade: ' + grade + '</div>'
            + '<div class="ring-count">' + p.passed + ' / ' + p.total + ' passed</div>'
            + '</div>';
    }).join('');

    /* SOC 2 score ring */
    if (data.soc2 && data.soc2.score != null) {
        const s2 = data.soc2;
        const color = _compScoreColor(s2.score);
        const grade = _compGrade(s2.score);
        const covered = Object.keys(s2.criteria || {}).filter(k => s2.criteria[k].score != null).length;
        html += '<div class="comp-ring-card" style="--ring-color: ' + color + '; border-color: rgba(59,130,246,0.2);">'
            + '<div class="ring-label">SOC 2 Type II</div>'
            + _buildRingSvg(s2.score, color, 90)
            + '<div class="ring-grade" style="color: ' + color + ';">Grade: ' + grade + '</div>'
            + '<div class="ring-count">' + covered + '/5 criteria covered</div>'
            + '</div>';
    }
    el.innerHTML = html;
}

function renderFrameworks(data) {
    const el = document.getElementById('compliance-frameworks');
    if (!data.pack_scores) return;

    const frameworkMeta = {
        'ubuntu-22.04-stig': { icon: 'fab fa-ubuntu', desc: 'Ubuntu 22.04 Server STIG' },
        'docker-stig': { icon: 'fab fa-docker', desc: 'Docker Enterprise STIG' },
        'network-stig': { icon: 'fas fa-network-wired', desc: 'Network Infrastructure STIG' },
        'hipaa-security': { icon: 'fas fa-hospital', desc: '\u00A7164.312 Technical Safeguards' },
    };

    const entries = Object.entries(data.pack_scores);
    el.innerHTML = entries.map(([id, p]) => {
        const color = _compScoreColor(p.score);
        const meta = frameworkMeta[id] || { icon: 'fas fa-shield-alt', desc: id };
        return '<div class="comp-framework">'
            + '<div class="comp-framework-top">'
            + '<span class="comp-framework-name"><i class="' + meta.icon + '" style="color:' + color + '; margin-right: 8px;"></i>' + _compEsc(p.name) + '</span>'
            + '<span class="comp-framework-score" style="color:' + color + ';">'
            + '<span class="comp-framework-bar"><span class="comp-framework-bar-fill" style="width:' + p.score + '%; background:' + color + ';"></span></span>'
            + p.score + '%</span>'
            + '</div>'
            + '<div class="comp-framework-meta">' + p.total + ' rules \u00B7 ' + meta.desc + '</div>'
            + '</div>';
    }).join('');

    /* SOC 2 — show real score if available */
    if (data.soc2 && data.soc2.score != null) {
        const s2 = data.soc2;
        const s2color = _compScoreColor(s2.score);
        const criteria = s2.criteria || {};
        const tscNames = ['Security', 'Availability', 'Processing Integrity', 'Confidentiality', 'Privacy'];
        let tscHtml = tscNames.map(name => {
            const c = criteria[name];
            if (!c || c.score == null) return '<span style="color:#475569;font-size:0.75rem;">' + _compEsc(name) + ': N/A</span>';
            const cc = _compScoreColor(c.score);
            return '<span style="color:' + cc + ';font-size:0.75rem;">' + _compEsc(name) + ': ' + c.score + '%</span>';
        }).join(' \u00B7 ');

        el.innerHTML += '<div class="comp-framework">'
            + '<div class="comp-framework-top">'
            + '<span class="comp-framework-name"><i class="fas fa-clipboard-check" style="color: ' + s2color + '; margin-right: 8px;"></i>SOC 2 Type II</span>'
            + '<span class="comp-framework-score" style="color:' + s2color + ';">'
            + '<span class="comp-framework-bar"><span class="comp-framework-bar-fill" style="width:' + s2.score + '%; background:' + s2color + ';"></span></span>'
            + s2.score + '%</span>'
            + '</div>'
            + '<div class="comp-framework-meta">' + tscHtml + '</div>'
            + '</div>';
    } else {
        el.innerHTML += '<div class="comp-framework" style="opacity: 0.5;">'
            + '<div class="comp-framework-top">'
            + '<span class="comp-framework-name"><i class="fas fa-clipboard-check" style="color: #3b82f6; margin-right: 8px;"></i>SOC 2 Type II</span>'
            + '<span class="comp-framework-score" style="color: #3b82f6;">Run scan first</span>'
            + '</div>'
            + '<div class="comp-framework-meta">5 Trust Service Criteria \u00B7 Mapped from STIG/CIS/HIPAA rules</div>'
            + '</div>';
    }
}

async function loadComplianceResults(scanId) {
    try {
        // Fetch results + pending approvals in parallel
        const [resultsResp, pendingResp] = await Promise.all([
            fetch('/tools/security-network/api/compliance/scans/' + scanId),
            fetch('/tools/security-network/api/compliance/pending-fixes').catch(function() { return null; })
        ]);
        const data = await resultsResp.json();
        _complianceResults = data.results || [];
        _complianceScanId = scanId;

        // Build pending map: rule_id -> approval info
        _compliancePendingByRule = {};
        if (pendingResp && pendingResp.ok) {
            const pendingData = await pendingResp.json();
            if (pendingData.success && pendingData.pending) {
                pendingData.pending.forEach(function(p) {
                    _compliancePendingByRule[p.rule_id] = p;
                });
            }
        }

        filterComplianceResults();
    } catch (e) {
        console.error('Failed to load compliance results:', e);
    }
}

function _stageRow(label, stage) {
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid rgba(0,229,255,0.08);font-size:0.85rem';
    var icon = document.createElement('span');
    icon.style.cssText = 'width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:bold';
    var name = document.createElement('span');
    name.style.cssText = 'flex:1;color:#e2e8f0';
    name.textContent = label;
    var status = document.createElement('span');
    status.style.cssText = 'font-size:0.75rem;font-family:"IBM Plex Mono",monospace';

    if (!stage) {
        icon.textContent = '-';
        icon.style.cssText += ';background:rgba(100,116,139,0.2);color:#64748b';
        status.textContent = 'skipped';
        status.style.color = '#64748b';
    } else if (stage.success || stage.approve) {
        icon.textContent = '\u2713';
        icon.style.cssText += ';background:rgba(34,197,94,0.2);color:#22c55e';
        status.textContent = 'ok';
        status.style.color = '#22c55e';
    } else if (stage.approval_id || stage.status === 'pending') {
        icon.textContent = '\u23F3';
        icon.style.cssText += ';background:rgba(251,191,36,0.2);color:#fbbf24';
        status.textContent = 'pending';
        status.style.color = '#fbbf24';
    } else {
        icon.textContent = '\u2717';
        icon.style.cssText += ';background:rgba(239,68,68,0.2);color:#ef4444';
        status.textContent = 'failed';
        status.style.color = '#ef4444';
    }

    row.appendChild(icon);
    row.appendChild(name);
    row.appendChild(status);
    return row;
}

function _showFixResultModal(ruleId, data) {
    var existing = document.getElementById('fix-result-overlay');
    if (existing) existing.remove();

    var stages = data.stages || {};
    var isSuccess = data.success;
    var isPending = data.pending_approval;
    var isManualOnly = data.manual_only;
    var accent = isSuccess ? '#22c55e' : (isPending ? '#fbbf24' : (isManualOnly ? '#8b5cf6' : '#ef4444'));
    var rgb = isSuccess ? '34,197,94' : (isPending ? '251,191,36' : (isManualOnly ? '139,92,246' : '239,68,68'));

    var overlay = document.createElement('div');
    overlay.id = 'fix-result-overlay';
    overlay.className = 'bm-overlay active';
    overlay.style.cssText = '--bm-accent:' + accent + ';--bm-accent-rgb:' + rgb;

    var shell = document.createElement('div');
    shell.className = 'bm-shell';
    shell.style.maxWidth = '560px';
    shell.style.maxHeight = '90vh';
    var frame = document.createElement('div');
    frame.className = 'bm-frame';
    ['bm-frame-elbow-top','bm-frame-seg','bm-frame-seg dim','bm-frame-light on','bm-frame-light amber','bm-frame-seg purple','bm-frame-fill','bm-frame-elbow-bottom'].forEach(function(cls){
        var el = document.createElement('div');
        el.className = cls;
        frame.appendChild(el);
    });

    var content = document.createElement('div');
    content.className = 'bm-content';
    content.style.maxHeight = '90vh';
    content.style.display = 'flex';
    content.style.flexDirection = 'column';

    var header = document.createElement('div');
    header.className = 'bm-header';
    var headerTitle = document.createElement('span');
    headerTitle.className = 'bm-header-title';
    headerTitle.textContent = isSuccess ? 'FIX APPLIED' : (isPending ? 'APPROVAL PENDING' : (isManualOnly ? 'MANUAL ONLY' : 'FIX FAILED'));
    var headerStrip = document.createElement('div');
    headerStrip.className = 'bm-header-strip';
    ['w1','w2','w3'].forEach(function(w){
        var p = document.createElement('div');
        p.className = 'bm-header-pip ' + w;
        headerStrip.appendChild(p);
    });
    var closeBtn = document.createElement('button');
    closeBtn.className = 'bm-close';
    closeBtn.textContent = '\u00D7';
    closeBtn.onclick = function() { overlay.remove(); };
    headerStrip.appendChild(closeBtn);
    header.appendChild(headerTitle);
    header.appendChild(headerStrip);

    var subtitle = document.createElement('div');
    subtitle.style.cssText = 'padding:8px 16px;border-bottom:1px solid rgba(' + rgb + ',0.15);font-size:0.75rem;color:#94a3b8';
    subtitle.textContent = 'Rule: ' + ruleId + (data.proposal_id ? '  |  Proposal #' + data.proposal_id : '') + (data.approval_id ? '  |  Approval #' + data.approval_id : '');

    var body = document.createElement('div');
    body.className = 'bm-body';
    body.style.cssText = 'padding:12px 20px;flex:1 1 auto;min-height:0;overflow-y:auto';

    var stagesTitle = document.createElement('div');
    stagesTitle.style.cssText = 'font-size:0.7rem;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:4px';
    stagesTitle.textContent = 'Pipeline Stages';
    body.appendChild(stagesTitle);

    body.appendChild(_stageRow('AI Review', stages.review));
    body.appendChild(_stageRow('Dry-run', stages.dry_run));
    body.appendChild(_stageRow('Apply', stages.applied));
    body.appendChild(_stageRow('Verify', stages.verified));
    if (stages.snapshot) body.appendChild(_stageRow('Snapshot', stages.snapshot));
    if (stages.escalation) body.appendChild(_stageRow('Telegram Escalation', stages.escalation));
    if (stages.rollback) body.appendChild(_stageRow('Auto-Rollback', stages.rollback));

    if (stages.review && stages.review.reasoning) {
        var reasoningBlock = document.createElement('div');
        reasoningBlock.style.cssText = 'margin-top:16px;padding:10px;background:rgba(0,229,255,0.05);border-left:3px solid ' + accent + ';font-size:0.8rem;color:#cbd5e1';
        var rTitle = document.createElement('div');
        rTitle.style.cssText = 'font-size:0.7rem;color:#64748b;text-transform:uppercase;margin-bottom:4px';
        rTitle.textContent = 'AI Reasoning';
        var rText = document.createElement('div');
        rText.textContent = stages.review.reasoning;
        reasoningBlock.appendChild(rTitle);
        reasoningBlock.appendChild(rText);
        body.appendChild(reasoningBlock);
    }

    if (data.error) {
        var errorBlock = document.createElement('div');
        errorBlock.style.cssText = 'margin-top:12px;padding:10px;background:rgba(239,68,68,0.08);border-left:3px solid #ef4444;font-size:0.8rem;color:#fca5a5';
        var eTitle = document.createElement('div');
        eTitle.style.cssText = 'font-size:0.7rem;color:#ef4444;text-transform:uppercase;margin-bottom:4px';
        eTitle.textContent = 'Error';
        var eText = document.createElement('div');
        eText.textContent = data.error;
        errorBlock.appendChild(eTitle);
        errorBlock.appendChild(eText);
        body.appendChild(errorBlock);
    }

    if (isPending) {
        var noteBlock = document.createElement('div');
        noteBlock.style.cssText = 'margin-top:12px;padding:10px;background:rgba(251,191,36,0.08);border-left:3px solid #fbbf24;font-size:0.8rem;color:#fde68a';
        noteBlock.textContent = 'Check your Telegram for approval buttons. The agent loop will execute the fix automatically once approved.';
        body.appendChild(noteBlock);
    }

    if (isManualOnly) {
        var entry = data.blocklist_entry || {};
        var reasonBlock = document.createElement('div');
        reasonBlock.style.cssText = 'margin-top:12px;padding:10px;background:rgba(139,92,246,0.08);border-left:3px solid #8b5cf6;font-size:0.8rem;color:#c4b5fd';
        var rt = document.createElement('div');
        rt.style.cssText = 'font-size:0.7rem;color:#8b5cf6;text-transform:uppercase;margin-bottom:4px;font-weight:bold';
        rt.textContent = 'Why This Is Blocked';
        var rx = document.createElement('div');
        rx.textContent = entry.reason || data.error || '';
        reasonBlock.appendChild(rt);
        reasonBlock.appendChild(rx);
        body.appendChild(reasonBlock);

        var planHost = document.createElement('div');
        planHost.id = 'comp-plan-host-' + ruleId;
        planHost.style.cssText = 'margin-top:12px';
        body.appendChild(planHost);

        var aiBtnRow = document.createElement('div');
        aiBtnRow.style.cssText = 'margin-top:12px;display:flex;gap:8px;flex-wrap:wrap';
        var aiBtn = document.createElement('button');
        aiBtn.className = 'btn';
        aiBtn.style.cssText = 'background:linear-gradient(135deg,#8b5cf6,#6366f1);color:#fff;border:none;padding:8px 14px;border-radius:4px;cursor:pointer;font-family:"Antonio",sans-serif;text-transform:uppercase;font-size:0.78rem;letter-spacing:0.5px';
        aiBtn.innerHTML = '<i class="fas fa-brain"></i> Ask F.O.R.G.E. for a Custom Plan';
        aiBtn.onclick = function() { _requestAiRemediationPlan(ruleId, aiBtn, planHost); };
        aiBtnRow.appendChild(aiBtn);
        body.appendChild(aiBtnRow);

        if (data.manual_steps) {
            var stepsBlock = document.createElement('div');
            stepsBlock.style.cssText = 'margin-top:12px;padding:10px;background:rgba(0,0,0,0.3);border-left:3px solid #64748b;font-size:0.78rem;color:#cbd5e1;font-family:"IBM Plex Mono",monospace;white-space:pre-wrap;max-height:220px;overflow-y:auto';
            var st = document.createElement('div');
            st.style.cssText = 'font-size:0.7rem;color:#64748b;text-transform:uppercase;margin-bottom:6px;font-weight:bold;font-family:"Antonio",sans-serif';
            st.textContent = 'Fallback Manual Steps (static)';
            stepsBlock.appendChild(st);
            var stx = document.createElement('div');
            stx.textContent = data.manual_steps;
            stepsBlock.appendChild(stx);
            body.appendChild(stepsBlock);
        }

        if (entry.manually_applied_at) {
            var appliedBlock = document.createElement('div');
            appliedBlock.style.cssText = 'margin-top:12px;padding:10px;background:rgba(34,197,94,0.08);border-left:3px solid #22c55e;font-size:0.8rem;color:#86efac';
            appliedBlock.textContent = 'Already marked as manually applied at ' + entry.manually_applied_at;
            body.appendChild(appliedBlock);
        }
    }

    var footer = document.createElement('div');
    footer.className = 'bm-footer';
    footer.style.cssText = 'padding:10px 20px;display:flex;gap:8px;justify-content:flex-end';
    var closeButton = document.createElement('button');
    closeButton.className = 'btn';
    closeButton.style.opacity = '0.85';
    closeButton.textContent = 'Close';
    closeButton.onclick = function() { overlay.remove(); };
    footer.appendChild(closeButton);

    content.appendChild(header);
    content.appendChild(subtitle);
    content.appendChild(body);
    content.appendChild(footer);
    shell.appendChild(frame);
    shell.appendChild(content);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.remove();
    });

    /* Auto-scroll the "Ask F.O.R.G.E." button into view on manual-only modals */
    if (isManualOnly) {
        setTimeout(function() {
            var ab = Array.from(overlay.querySelectorAll('button')).find(function(b) {
                return b.textContent.indexOf('Ask F.O.R.G.E.') >= 0;
            });
            if (ab) ab.scrollIntoView({block: 'center', behavior: 'smooth'});
        }, 120);
    }
}

async function _requestAiRemediationPlan(ruleId, btn, host) {
    if (!_complianceScanId) {
        host.innerHTML = '<div style="color:#ef4444;padding:10px">No active scan selected</div>';
        return;
    }
    var origHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> F.O.R.G.E. is analyzing your deployment...';
    btn.style.pointerEvents = 'none';
    btn.style.opacity = '0.7';
    host.innerHTML = '<div style="padding:10px;color:#a78bfa;font-size:0.8rem"><i class="fas fa-brain"></i> Reading docker-compose, inspecting containers, generating runbook (may take 30-60s)...</div>';
    try {
        const resp = await fetch('/tools/security-network/api/compliance/plan/' + encodeURIComponent(ruleId), {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scan_id: _complianceScanId})
        });
        const data = await resp.json();
        if (data.success && data.plan) {
            _renderAiRemediationPlan(host, data);
            btn.innerHTML = '<i class="fas fa-check"></i> Plan Generated (#' + data.plan_id + ')';
            btn.style.background = 'linear-gradient(135deg,#22c55e,#16a34a)';
        } else {
            host.innerHTML = '<div style="padding:10px;color:#ef4444;font-size:0.8rem">Plan generation failed: ' + (data.error || 'unknown error') + '</div>';
            btn.innerHTML = origHtml;
            btn.style.pointerEvents = 'auto';
            btn.style.opacity = '1';
        }
    } catch (e) {
        host.innerHTML = '<div style="padding:10px;color:#ef4444;font-size:0.8rem">Network error: ' + e.message + '</div>';
        btn.innerHTML = origHtml;
        btn.style.pointerEvents = 'auto';
        btn.style.opacity = '1';
    }
}

function _renderAiRemediationPlan(host, data) {
    var plan = data.plan || {};
    var isFallback = !!data.fallback;
    host.innerHTML = '';

    var wrap = document.createElement('div');
    wrap.style.cssText = 'padding:12px;background:rgba(139,92,246,0.06);border-left:3px solid #8b5cf6;border-radius:2px';

    var hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px';
    var hdrL = document.createElement('div');
    hdrL.style.cssText = 'font-size:0.75rem;color:#a78bfa;text-transform:uppercase;font-weight:bold;font-family:"Antonio",sans-serif;letter-spacing:0.5px';
    hdrL.innerHTML = '<i class="fas fa-brain"></i> ' + (isFallback ? 'Fallback Plan (AI unavailable)' : 'F.O.R.G.E. Custom Runbook');
    var hdrR = document.createElement('div');
    hdrR.style.cssText = 'font-size:0.68rem;color:#64748b';
    hdrR.textContent = 'Plan #' + (data.plan_id || '?');
    hdr.appendChild(hdrL);
    hdr.appendChild(hdrR);
    wrap.appendChild(hdr);

    function section(label, color, text) {
        if (!text) return;
        var s = document.createElement('div');
        s.style.cssText = 'margin-top:10px;padding:8px 10px;background:rgba(0,0,0,0.25);border-left:2px solid ' + color + ';font-size:0.78rem;color:#e2e8f0';
        var l = document.createElement('div');
        l.style.cssText = 'font-size:0.65rem;color:' + color + ';text-transform:uppercase;margin-bottom:4px;font-weight:bold;font-family:"Antonio",sans-serif';
        l.textContent = label;
        var v = document.createElement('div');
        v.style.whiteSpace = 'pre-wrap';
        v.textContent = text;
        s.appendChild(l);
        s.appendChild(v);
        wrap.appendChild(s);
    }

    /* Meta row */
    var meta = document.createElement('div');
    meta.style.cssText = 'display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;font-size:0.72rem';
    function chip(label, val, color) {
        if (!val) return;
        var c = document.createElement('div');
        c.style.cssText = 'padding:4px 8px;background:rgba(0,0,0,0.3);border:1px solid ' + color + ';border-radius:2px;color:#e2e8f0';
        c.innerHTML = '<span style="color:' + color + ';font-weight:bold">' + label + ':</span> ' + val;
        meta.appendChild(c);
    }
    chip('DOWNTIME', plan.estimated_downtime, '#fbbf24');
    chip('WINDOW', plan.best_window, '#00e5ff');
    if (plan.exemption_candidate) chip('EXEMPTION', 'CANDIDATE', '#f472b6');
    if (meta.children.length) wrap.appendChild(meta);

    section('Impact Analysis', '#fbbf24', plan.impact_analysis);

    if (Array.isArray(plan.affected_containers) && plan.affected_containers.length) {
        section('Affected Containers', '#ef4444', plan.affected_containers.join(', '));
    }

    if (Array.isArray(plan.prerequisites) && plan.prerequisites.length) {
        var pre = document.createElement('div');
        pre.style.cssText = 'margin-top:10px;padding:8px 10px;background:rgba(0,0,0,0.25);border-left:2px solid #22d3ee;font-size:0.78rem;color:#e2e8f0';
        var pl = document.createElement('div');
        pl.style.cssText = 'font-size:0.65rem;color:#22d3ee;text-transform:uppercase;margin-bottom:4px;font-weight:bold;font-family:"Antonio",sans-serif';
        pl.textContent = 'Prerequisites';
        pre.appendChild(pl);
        var ul = document.createElement('ul');
        ul.style.cssText = 'margin:4px 0 0 16px;padding:0';
        plan.prerequisites.forEach(function(p) {
            var li = document.createElement('li');
            li.textContent = p;
            ul.appendChild(li);
        });
        pre.appendChild(ul);
        wrap.appendChild(pre);
    }

    /* Steps */
    if (Array.isArray(plan.steps) && plan.steps.length) {
        var stepsWrap = document.createElement('div');
        stepsWrap.style.cssText = 'margin-top:10px;padding:10px;background:rgba(0,0,0,0.3);border-left:3px solid #00e5ff';
        var sl = document.createElement('div');
        sl.style.cssText = 'font-size:0.7rem;color:#00e5ff;text-transform:uppercase;margin-bottom:8px;font-weight:bold;font-family:"Antonio",sans-serif';
        sl.textContent = 'Step-by-Step Runbook';
        stepsWrap.appendChild(sl);
        plan.steps.forEach(function(step, idx) {
            var sRow = document.createElement('div');
            sRow.style.cssText = 'margin-top:8px;padding:8px;background:rgba(0,0,0,0.4);border-radius:2px;font-size:0.75rem;color:#e2e8f0';
            var num = document.createElement('div');
            num.style.cssText = 'font-family:"Antonio",sans-serif;color:#00e5ff;font-size:0.7rem;margin-bottom:4px;font-weight:bold';
            var autoTag = step.safe_auto ? ' <span style="color:#22c55e">[SAFE-AUTO]</span>' : ' <span style="color:#fbbf24">[MANUAL]</span>';
            num.innerHTML = 'STEP ' + (idx + 1) + autoTag;
            sRow.appendChild(num);
            var act = document.createElement('div');
            act.style.cssText = 'font-family:"IBM Plex Mono",monospace;color:#e2e8f0;white-space:pre-wrap;word-break:break-word';
            act.textContent = step.action || '';
            sRow.appendChild(act);
            if (step.why) {
                var why = document.createElement('div');
                why.style.cssText = 'margin-top:4px;color:#94a3b8;font-size:0.7rem;font-style:italic';
                why.textContent = 'Why: ' + step.why;
                sRow.appendChild(why);
            }
            stepsWrap.appendChild(sRow);
        });
        wrap.appendChild(stepsWrap);
    }

    section('Rollback Plan', '#ef4444', plan.rollback_plan);
    if (plan.exemption_reason) section('Exemption Reason', '#f472b6', plan.exemption_reason);

    host.appendChild(wrap);
}

async function applyComplianceFix(ruleId, btn) {
    if (!_complianceScanId) {
        _showFixResultModal(ruleId, {success: false, error: 'No active scan selected', stages: {}});
        return;
    }
    if (btn) {
        btn.textContent = 'Reviewing...';
        btn.style.pointerEvents = 'none';
        btn.style.color = '#94a3b8';
    }
    try {
        const resp = await fetch('/tools/security-network/api/compliance/fix', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({scan_id: _complianceScanId, rule_id: ruleId})
        });
        const data = await resp.json();

        if (data.success) {
            if (btn) {
                btn.textContent = 'Fixed \u2713';
                btn.style.color = '#22c55e';
            }
            _showFixResultModal(ruleId, data);
            setTimeout(function() { loadComplianceResults(_complianceScanId); }, 3000);
        } else if (data.pending_approval) {
            if (btn) {
                btn.textContent = 'Pending \u23F3';
                btn.style.color = '#fbbf24';
                btn.title = 'Awaiting Telegram approval #' + data.approval_id;
            }
            _showFixResultModal(ruleId, data);
        } else {
            if (btn) {
                btn.textContent = 'Failed';
                btn.style.color = '#ef4444';
                btn.style.pointerEvents = 'auto';
            }
            _showFixResultModal(ruleId, data);
        }
    } catch (e) {
        if (btn) {
            btn.textContent = 'Error';
            btn.style.color = '#ef4444';
            btn.style.pointerEvents = 'auto';
        }
        _showFixResultModal(ruleId, {success: false, error: 'Network error: ' + e.message, stages: {}});
    }
}

/* ── Repair Bay approval card: Apply Once / Apply + Always Allow / Dismiss ── */
async function openComplianceActionModal(ruleId) {
    if (!_complianceScanId) {
        showToast('error', 'No active scan selected');
        return;
    }
    var existing = document.getElementById('comp-action-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'comp-action-overlay';
    overlay.className = 'bm-overlay active';
    overlay.style.cssText = '--bm-accent:#00e5ff;--bm-accent-rgb:0,229,255';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    var shell = document.createElement('div');
    shell.className = 'bm-shell';
    shell.style.maxWidth = '600px';
    shell.style.maxHeight = '90vh';

    var frame = document.createElement('div');
    frame.className = 'bm-frame';
    ['bm-frame-elbow-top','bm-frame-seg','bm-frame-seg dim','bm-frame-light on','bm-frame-light amber','bm-frame-seg purple','bm-frame-fill','bm-frame-elbow-bottom'].forEach(function(cls){
        var el = document.createElement('div');
        el.className = cls;
        frame.appendChild(el);
    });

    var content = document.createElement('div');
    content.className = 'bm-content';
    content.style.cssText = 'max-height:90vh;display:flex;flex-direction:column';

    var header = document.createElement('div');
    header.className = 'bm-header';
    var headerTitle = document.createElement('span');
    headerTitle.className = 'bm-header-title';
    headerTitle.textContent = 'COMPLIANCE REVIEW \u2014 ' + ruleId;
    var headerStrip = document.createElement('div');
    headerStrip.className = 'bm-header-strip';
    ['w1','w2','w3'].forEach(function(w){
        var p = document.createElement('div');
        p.className = 'bm-header-pip ' + w;
        headerStrip.appendChild(p);
    });
    var closeBtn = document.createElement('button');
    closeBtn.className = 'bm-close';
    closeBtn.textContent = '\u00D7';
    closeBtn.onclick = function() { overlay.remove(); };
    headerStrip.appendChild(closeBtn);
    header.appendChild(headerTitle);
    header.appendChild(headerStrip);

    var body = document.createElement('div');
    body.className = 'bm-body';
    body.style.cssText = 'padding:14px 20px;flex:1 1 auto;min-height:0;overflow-y:auto';

    var loading = document.createElement('div');
    loading.style.cssText = 'text-align:center;padding:24px;color:#94a3b8;font-size:0.85rem';
    loading.textContent = 'Loading rule details\u2026';
    body.appendChild(loading);

    content.appendChild(header);
    content.appendChild(body);
    shell.appendChild(frame);
    shell.appendChild(content);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    /* Fetch action-info from backend */
    try {
        var url = '/tools/security-network/api/compliance/scans/' + encodeURIComponent(_complianceScanId)
                + '/findings/' + encodeURIComponent(ruleId) + '/action-info';
        var resp = await fetch(url);
        var data = await resp.json();
        if (!data.success) {
            body.textContent = '';
            var err = document.createElement('div');
            err.style.cssText = 'padding:14px;background:rgba(239,68,68,0.08);border-left:3px solid #ef4444;color:#fca5a5;font-size:0.85rem';
            err.textContent = 'Error: ' + (data.error || 'failed to load finding');
            body.appendChild(err);
            return;
        }

        body.textContent = '';
        var f = data.finding || {};

        function _section(label, value, color) {
            var s = document.createElement('div');
            s.style.cssText = 'margin-bottom:10px';
            var lbl = document.createElement('div');
            lbl.style.cssText = 'font-size:0.7rem;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:3px';
            lbl.textContent = label;
            var val = document.createElement('div');
            val.style.cssText = 'font-size:0.85rem;color:' + (color || '#e2e8f0') + ';font-family:"IBM Plex Mono",monospace;word-break:break-word';
            val.textContent = value || '\u2014';
            s.appendChild(lbl);
            s.appendChild(val);
            return s;
        }

        var sevColor = f.severity === 'critical' ? '#ef4444' : f.severity === 'high' ? '#f97316' : f.severity === 'medium' ? '#fbbf24' : '#64748b';
        body.appendChild(_section('Severity', (f.severity || 'info').toUpperCase(), sevColor));
        body.appendChild(_section('Pack', f.pack_id));
        body.appendChild(_section('Details', f.details || f.actual_value));
        body.appendChild(_section('Fix Type', f.fix_type));
        if (f.fix_summary) body.appendChild(_section('Fix Summary', f.fix_summary));

        if (data.auto_approval_status) {
            var aa = document.createElement('div');
            aa.style.cssText = 'margin:10px 0;padding:8px 12px;background:rgba(0,229,255,0.06);border-left:3px solid #00e5ff;font-size:0.78rem;color:#cbd5e1';
            aa.textContent = 'Auto-approval state: ' + data.auto_approval_status;
            body.appendChild(aa);
        }

        if (data.blocklist_reason) {
            var bl = document.createElement('div');
            bl.style.cssText = 'margin:10px 0;padding:10px 12px;background:rgba(239,68,68,0.08);border-left:3px solid #ef4444;font-size:0.78rem;color:#fca5a5';
            var blTitle = document.createElement('div');
            blTitle.style.cssText = 'font-size:0.7rem;color:#ef4444;text-transform:uppercase;margin-bottom:3px;font-weight:600';
            blTitle.textContent = 'BLOCKLIST WARNING';
            var blText = document.createElement('div');
            blText.textContent = data.blocklist_reason;
            bl.appendChild(blTitle);
            bl.appendChild(blText);
            body.appendChild(bl);
        }

        if (!data.proposal_id) {
            var noProp = document.createElement('div');
            noProp.style.cssText = 'margin-top:14px;padding:12px;background:rgba(251,191,36,0.08);border-left:3px solid #fbbf24;color:#fcd34d;font-size:0.82rem';
            noProp.textContent = 'No open proposal for this rule yet. Generate a remediation plan from the Fix tab first, or run the compliance enqueuer.';
            body.appendChild(noProp);
            return;
        }

        var pidNote = document.createElement('div');
        pidNote.style.cssText = 'margin:8px 0 14px;font-size:0.72rem;color:#64748b';
        pidNote.textContent = 'Proposal #' + data.proposal_id + ' \u2014 status: ' + (data.proposal_status || 'proposed');
        body.appendChild(pidNote);

        var btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;flex-direction:column;gap:8px;margin-top:8px';

        function _mkBtn(label, color, action, title) {
            var b = document.createElement('button');
            b.className = 'btn';
            b.style.cssText = 'padding:10px 14px;font-size:0.82rem;background:' + color + ';color:#0a0e1a;border:none;border-radius:4px;cursor:pointer;font-weight:600;text-align:left';
            b.textContent = label;
            if (title) b.title = title;
            b.onclick = function() { _complianceCardAction(data.proposal_id, action, ruleId, overlay); };
            return b;
        }

        btnRow.appendChild(_mkBtn('\u25B6  Apply Once', '#22c55e', 'apply_once',
            'Run the safe-exec orchestrator for this rule one time. Snapshot \u2192 apply \u2192 health gate \u2192 auto-rollback on failure.'));
        btnRow.appendChild(_mkBtn('\u2713  Apply + Always Allow', '#00e5ff', 'apply_and_allow',
            'Run safe-exec now AND mark this rule as auto-allowed for the Sunday 03:00 EDT window.'));
        btnRow.appendChild(_mkBtn('\u2717  Dismiss (Mark Exempt)', '#94a3b8', 'exempt',
            'Mark this rule as exempt. The proposal will be resolved and the rule will not auto-apply.'));

        body.appendChild(btnRow);
    } catch (e) {
        body.textContent = '';
        var err = document.createElement('div');
        err.style.cssText = 'padding:14px;background:rgba(239,68,68,0.08);border-left:3px solid #ef4444;color:#fca5a5;font-size:0.85rem';
        err.textContent = 'Network error: ' + e.message;
        body.appendChild(err);
    }
}

async function _complianceCardAction(proposalId, action, ruleId, overlay) {
    /* Disable buttons during request */
    var buttons = overlay.querySelectorAll('button.btn');
    buttons.forEach(function(b) { b.disabled = true; b.style.opacity = '0.5'; b.style.pointerEvents = 'none'; });

    try {
        var resp = await fetch('/tools/repair-bay/api/proposals/' + proposalId + '/compliance-action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: action})
        });
        var data = await resp.json();
        overlay.remove();

        /* Show pipeline result via the existing fix-result modal */
        var resultData = data.result || data;
        resultData.proposal_id = proposalId;
        if (action === 'exempt') {
            resultData.success = data.success !== false;
            resultData.manual_only = true;
            resultData.stages = resultData.stages || {};
        }
        _showFixResultModal(ruleId, resultData);

        /* Refresh findings list after a beat */
        setTimeout(function() {
            if (_complianceScanId) loadComplianceResults(_complianceScanId);
        }, 1500);
    } catch (e) {
        overlay.remove();
        _showFixResultModal(ruleId, {success: false, error: 'Network error: ' + e.message, stages: {}});
    }
}

function filterComplianceResults() {
    const pack = document.getElementById('compliance-pack-filter').value;
    const severity = document.getElementById('compliance-severity-filter').value;
    const status = document.getElementById('compliance-status-filter').value;
    const container = document.getElementById('compliance-findings');

    let filtered = _complianceResults;
    if (pack) filtered = filtered.filter(r => r.pack_id === pack);
    if (severity) filtered = filtered.filter(r => r.severity === severity);
    if (status) filtered = filtered.filter(r => r.status === status);

    if (filtered.length === 0 && _complianceResults.length === 0) {
        container.innerHTML = '<div style="text-align: center; color: #475569; padding: 40px 0; font-size: 0.85rem;">'
            + '<i class="fas fa-shield-alt" style="font-size: 2rem; margin-bottom: 12px; display: block; opacity: 0.3;"></i>'
            + 'Run a compliance scan to see findings</div>';
        return;
    }
    if (filtered.length === 0) {
        container.innerHTML = '<div style="text-align: center; color: #475569; padding: 30px 0; font-size: 0.85rem;">No results match current filters</div>';
        return;
    }

    const sevOrder = ['critical', 'high', 'medium', 'low'];
    const sevColors = { critical: '#dc2626', high: '#ef4444', medium: '#f59e0b', low: '#94a3b8' };
    const sevIcons = { critical: 'fas fa-skull-crossbones', high: 'fas fa-exclamation-triangle', medium: 'fas fa-exclamation-circle', low: 'fas fa-info-circle' };

    /* Group by severity, only show fails/errors by default (pass hidden unless filter says pass) */
    const showFails = !status || status === 'fail' || status === 'error';
    const groups = {};
    filtered.forEach(r => {
        const sev = r.severity || 'medium';
        if (!groups[sev]) groups[sev] = { pass: [], fail: [] };
        if (r.status === 'pass') groups[sev].pass.push(r);
        else groups[sev].fail.push(r);
    });

    let html = '';
    for (const sev of sevOrder) {
        if (!groups[sev]) continue;
        const items = status === 'pass' ? groups[sev].pass : (status === 'fail' || status === 'error') ? groups[sev].fail : [...groups[sev].fail, ...groups[sev].pass];
        if (items.length === 0) continue;

        const failCount = groups[sev].fail.length;
        const passCount = groups[sev].pass.length;
        const color = sevColors[sev] || '#94a3b8';
        const expanded = sev === 'critical' || sev === 'high';

        html += '<div class="comp-sev-group">'
            + '<div class="comp-sev-header' + (expanded ? ' expanded' : '') + '" onclick="this.classList.toggle(\'expanded\'); this.nextElementSibling.classList.toggle(\'show\');">'
            + '<span class="sev-dot" style="background:' + color + ';"></span>'
            + '<span class="sev-label" style="color:' + color + ';">' + sev + '</span>'
            + '<span class="sev-count">' + failCount + ' fail \u00B7 ' + passCount + ' pass</span>'
            + '<i class="fas fa-chevron-right sev-chevron"></i>'
            + '</div>'
            + '<div class="comp-sev-body' + (expanded ? ' show' : '') + '">';

        for (const r of items) {
            const isPass = r.status === 'pass';
            const icon = isPass ? 'fas fa-check-circle' : (sevIcons[sev] || 'fas fa-exclamation-circle');
            const iconColor = isPass ? '#22c55e' : color;
            const detailText = _compEsc(r.details || r.actual_value || r.rule_id);

            html += '<div class="comp-finding-row">'
                + '<span class="comp-finding-icon" style="color:' + iconColor + ';"><i class="' + icon + '"></i></span>'
                + '<span class="comp-finding-id">' + _compEsc(r.rule_id) + '</span>'
                + '<span class="comp-finding-desc" title="' + detailText.replace(/"/g, '&quot;') + '">' + detailText + '</span>'
                + '<span class="comp-finding-pack">' + _compEsc((r.pack_id || '').replace('-stig', '').replace('-security', '')) + '</span>'
                + (!isPass ? _complianceFixButtonHtml(r.rule_id) : '')
                + '</div>';
        }

        html += '</div></div>';
    }

    container.innerHTML = html;
}

async function loadComplianceScanHistory() {
    try {
        const resp = await fetch('/tools/security-network/api/compliance/scans');
        const data = await resp.json();
        const scans = (data.scans || []).slice(0, 20).reverse();
        if (scans.length === 0) return;

        const canvas = document.getElementById('compliance-history-chart');
        if (!canvas) return;

        const labels = scans.map(s => {
            if (!s.completed_at) return '...';
            const d = new Date(s.completed_at);
            return (d.getMonth()+1) + '/' + d.getDate() + ' ' + d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
        });
        const scores = scans.map(s => s.score != null ? s.score : null);

        if (_compHistoryChart) { _compHistoryChart.destroy(); }
        /* Also destroy any orphaned chart on this canvas */
        const existingChart = Chart.getChart(canvas);
        if (existingChart) { existingChart.destroy(); }

        /* Parse scores to numbers (API returns strings) */
        const numScores = scores.map(s => s != null ? parseFloat(s) : null);

        _compHistoryChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Compliance Score',
                    data: numScores,
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    borderWidth: 2,
                    pointBackgroundColor: numScores.map(s => _compScoreColor(s || 0)),
                    pointBorderColor: numScores.map(s => _compScoreColor(s || 0)),
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    fill: true,
                    tension: 0.3,
                    spanGaps: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.95)',
                        titleColor: '#e2e8f0',
                        bodyColor: '#cbd5e1',
                        borderColor: 'rgba(255,255,255,0.1)',
                        borderWidth: 1,
                        cornerRadius: 8,
                        padding: 10,
                        callbacks: {
                            label: function(ctx) { return 'Score: ' + ctx.parsed.y + '%'; }
                        }
                    }
                },
                scales: {
                    y: {
                        min: 0, max: 100,
                        grid: { color: 'rgba(255,255,255,0.04)' },
                        ticks: { color: '#475569', font: { size: 10 }, callback: function(v) { return v + '%'; } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#475569', font: { size: 9 }, maxRotation: 45 }
                    }
                }
            }
        });
    } catch (e) { console.error(e); }
}

async function loadEvidenceStatus() {
    const el = document.getElementById('compliance-evidence');
    try {
        const resp = await fetch('/tools/security-network/api/compliance/evidence');
        const data = await resp.json();
        const items = data.evidence || data.items || [];

        if (items.length === 0) {
            /* Show default evidence categories */
            const defaults = [
                { name: 'Access Control Config', collected: false },
                { name: 'Audit Log (90 days)', collected: false },
                { name: 'SSL Certificate Status', collected: false },
                { name: 'System Health', collected: false },
                { name: 'Firewall Config', collected: false },
                { name: 'Docker Config', collected: false },
                { name: 'User Permissions', collected: false },
                { name: 'Network Config', collected: false },
            ];
            el.innerHTML = defaults.map(d => _renderEvidenceItem(d.name, d.collected)).join('');
            return;
        }

        /* Deduplicate by artifact_type — keep latest (first in desc order) */
        const seen = new Set();
        const unique = items.filter(i => {
            const key = i.artifact_type || i.artifact_name || 'unknown';
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
        el.innerHTML = unique.map(i => {
            const collected = i.status === 'collected' || !!i.collected_at || !!i.data;
            const name = i.artifact_name || i.artifact_type || i.evidence_type || i.name || 'Unknown';
            const age = i.collected_at ? _evidenceAge(i.collected_at) : null;
            return _renderEvidenceItem(name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), collected, age);
        }).join('');
    } catch (e) {
        /* Show defaults on error */
        const defaults = ['Access Control', 'Audit Logs', 'SSL Certs', 'System Health', 'Firewall', 'Docker', 'Users', 'Network'];
        el.innerHTML = defaults.map(d => _renderEvidenceItem(d, false)).join('');
    }
}

function _evidenceAge(isoDate) {
    if (!isoDate) return null;
    const ms = Date.now() - new Date(isoDate).getTime();
    const hours = Math.floor(ms / 3600000);
    if (hours < 1) return 'just now';
    if (hours < 24) return hours + 'h ago';
    const days = Math.floor(hours / 24);
    if (days < 30) return days + 'd ago';
    return Math.floor(days / 30) + 'mo ago';
}

function _renderEvidenceItem(name, collected, age) {
    const cls = collected ? 'collected' : 'pending';
    const icon = collected ? '<i class="fas fa-check-circle"></i>' : '<i class="far fa-circle"></i>';
    const stale = age && (age.includes('mo') || (age.includes('d') && parseInt(age) > 30));
    const ageHtml = age ? '<span style="margin-left:auto;font-size:0.7rem;color:' + (stale ? '#ef4444' : '#475569') + ';">' + _compEsc(age) + (stale ? ' \u26A0' : '') + '</span>' : '';
    return '<div class="comp-evidence-item ' + cls + '"><span class="ev-icon">' + icon + '</span> ' + _compEsc(name) + ageHtml + '</div>';
}

async function collectEvidence() {
    const btn = document.getElementById('comp-collect-btn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Collecting...';
    try {
        const resp = await fetch('/tools/security-network/api/compliance/evidence/collect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}'
        });
        const data = await resp.json();
        if (data.success || data.evidence) {
            loadEvidenceStatus();
        }
    } catch (e) {
        console.error('Evidence collection error:', e);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-download"></i> Collect Evidence';
    }
}

// ═══════ HARDENING TAB ═══════
async function loadHardeningContent(scanId) {
    const el = document.getElementById('hardening-content');
    try {
        const resp = await fetch('/tools/security-network/api/compliance/scans/' + scanId + '?status=fail');
        const data = await resp.json();
        const fails = (data.results || []).sort((a, b) => {
            const sev = { critical: 0, high: 1, medium: 2, low: 3 };
            return (sev[a.severity] || 2) - (sev[b.severity] || 2);
        });

        if (fails.length === 0) {
            el.innerHTML = '<div style="text-align: center; color: #22c55e; padding: 40px;"><i class="fas fa-check-circle" style="font-size: 3rem;"></i><br><br>All checks passing!</div>';
            return;
        }

        const groups = {};
        fails.forEach(f => {
            const sev = f.severity || 'medium';
            if (!groups[sev]) groups[sev] = [];
            groups[sev].push(f);
        });

        const sevOrder = ['critical', 'high', 'medium', 'low'];
        const sevColors = { critical: '#dc2626', high: '#ef4444', medium: '#f59e0b', low: '#94a3b8' };

        let html = '';
        for (const sev of sevOrder) {
            if (!groups[sev]) continue;
            html += '<div style="margin-bottom: 20px;">'
                + '<h4 style="color: ' + sevColors[sev] + '; text-transform: uppercase; font-size: 0.85rem; margin-bottom: 10px;">'
                + '<i class="fas fa-exclamation-triangle"></i> ' + sev + ' (' + groups[sev].length + ' findings)'
                + '</h4>';

            for (const f of groups[sev]) {
                const detailText = (f.details || 'No details').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const actualVal = f.actual_value ? f.actual_value.substring(0, 100).replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
                const expectedVal = f.expected_value ? f.expected_value.substring(0, 100).replace(/</g, '&lt;').replace(/>/g, '&gt;') : '';
                html += '<div style="background: var(--archie-bg-secondary); border: 1px solid var(--archie-border-default); border-left: 3px solid ' + sevColors[sev] + '; border-radius: 6px; padding: 12px 15px; margin-bottom: 8px;">'
                    + '<div style="display: flex; justify-content: space-between; align-items: start;">'
                    + '<div>'
                    + '<span class="mono" style="font-size: 0.8rem; color: var(--archie-text-muted);">' + f.rule_id + '</span>'
                    + '<span style="font-size: 0.8rem; color: var(--archie-text-muted); margin-left: 8px;">' + (f.pack_id || '').replace('-stig', '') + '</span>'
                    + '</div>'
                    + '</div>'
                    + '<div style="font-size: 0.85rem; color: var(--archie-text-primary); margin-top: 6px;">' + detailText + '</div>'
                    + (actualVal ? '<div style="font-size: 0.8rem; color: var(--archie-text-muted); margin-top: 4px;">Current: <code style="background: var(--archie-bg-tertiary); padding: 2px 6px; border-radius: 3px;">' + actualVal + '</code></div>' : '')
                    + (expectedVal ? '<div style="font-size: 0.8rem; color: var(--archie-text-muted); margin-top: 2px;">Expected: <code style="background: var(--archie-bg-tertiary); padding: 2px 6px; border-radius: 3px;">' + expectedVal + '</code></div>' : '')
                    + '</div>';
            }
            html += '</div>';
        }

        el.innerHTML = html;
    } catch (e) {
        el.textContent = 'Error loading hardening data: ' + e.message;
    }
}

function onComplianceTabShown() {
    loadComplianceScanHistory();
    loadEvidenceStatus();
    fetch('/tools/security-network/api/compliance/scores')
        .then(r => r.json())
        .then(data => {
            const sid = data.latest_scan_id || data.scan_id;
            if (data.success && sid) {
                _lastScanId = sid;
                const statusEl = document.getElementById('compliance-scan-status');
                statusEl.textContent = 'Last scan: ' + data.score + '% \u2022 ' + data.passed + ' passed \u2022 ' + data.failed + ' failed';
                statusEl.style.color = _compScoreColor(data.score);
                renderScoreCards(data);
                renderFrameworks(data);
                loadComplianceResults(sid);
            }
        })
        .catch(function() {});
}

function openComplianceReport() {
    const scanId = _lastScanId;
    if (!scanId) { alert('Run a scan first'); return; }
    const client = prompt('Client name for the report:', 'System Assessment');
    if (client !== null) {
        window.open('/tools/security-network/api/compliance/report/' + scanId + '?client=' + encodeURIComponent(client));
    }
}

function exportCkl() {
    const scanId = _lastScanId;
    if (!scanId) { alert('Run a scan first'); return; }
    window.open('/tools/security-network/api/compliance/export/ckl?scan_id=' + scanId);
}

function exportEvidence() {
    const scanId = _lastScanId;
    if (!scanId) { alert('Run a scan first'); return; }
    window.open('/tools/security-network/api/compliance/export/evidence?scan_id=' + scanId);
}

function onHardeningTabShown() {
    fetch('/tools/security-network/api/compliance/scores')
        .then(r => r.json())
        .then(data => {
            const sid = data.latest_scan_id || data.scan_id;
            if (sid) {
                _lastScanId = sid;
                loadHardeningContent(sid);
            }
        })
        .catch(function() {});
}

// ========== NETWORK MONITOR ==========

var _netMonDevices = [];
async function loadNetworkMonitor() {
    var container = document.getElementById('network-monitor-table');
    if (!container) return;
    container.textContent = '';

    try {
        var resp = await fetch(SN_API + '/devices/list?hours=24');
        var d = await resp.json();
        if (!d.success || !d.devices || d.devices.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = 'No device activity in the last 24 hours';
            container.appendChild(empty);
            return;
        }

        // Sort by total traffic descending
        _netMonDevices = d.devices.sort(function(a, b) { return (b.total || 0) - (a.total || 0); });

        // Search bar
        var searchBar = document.createElement('div');
        searchBar.style.cssText = 'display:flex;gap:8px;margin-bottom:10px;align-items:center';
        var searchInput = document.createElement('input');
        searchInput.type = 'text';
        searchInput.className = 'form-input';
        searchInput.id = 'netmon-search';
        searchInput.placeholder = 'Filter by name, IP, or MAC...';
        searchInput.style.cssText = 'flex:1;max-width:300px;font-size:0.78rem';
        searchInput.addEventListener('input', function() { _renderNetMonTable(container, searchInput.value.toLowerCase()); });
        var countLabel = document.createElement('span');
        countLabel.style.cssText = 'color:#888;font-size:0.75rem';
        countLabel.id = 'netmon-count';
        countLabel.textContent = _netMonDevices.length + ' devices';
        searchBar.appendChild(searchInput);
        searchBar.appendChild(countLabel);
        container.appendChild(searchBar);

        _renderNetMonTable(container, '');

    } catch(e) {
        console.error('loadNetworkMonitor error:', e);
        var errDiv = document.createElement('div');
        errDiv.className = 'empty-state';
        errDiv.textContent = 'Error loading network monitor: ' + e.message;
        container.appendChild(errDiv);
    }
}

function _renderNetMonTable(container, filter) {
    // Remove old table if exists
    var oldTable = container.querySelector('table');
    if (oldTable) oldTable.remove();

    var filtered = _netMonDevices;
    if (filter) {
        filtered = _netMonDevices.filter(function(dev) {
            var label = (dev.device_label || dev.user_name || '').toLowerCase();
            var ip = (dev.device_ip || '').toLowerCase();
            var mac = (dev.device_mac || '').toLowerCase();
            return label.indexOf(filter) >= 0 || ip.indexOf(filter) >= 0 || mac.indexOf(filter) >= 0;
        });
    }
    var countEl = document.getElementById('netmon-count');
    if (countEl) countEl.textContent = filtered.length + ' of ' + _netMonDevices.length + ' devices';

    var table = document.createElement('table');
    table.className = 'data-table';

    var thead = document.createElement('thead');
    var headerRow = document.createElement('tr');
    ['Device', 'IP', 'MAC', 'Download', 'Upload', 'Total', 'DNS Queries', ''].forEach(function(h) {
        var th = document.createElement('th');
        th.textContent = h;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    filtered.forEach(function(dev) {
        var isUnknown = !dev.device_label && !dev.user_name;
        var tr = document.createElement('tr');
        tr.style.cursor = 'pointer';
        if (isUnknown) tr.style.opacity = '0.75';
        tr.addEventListener('click', function(e) {
            if (e.target.tagName === 'BUTTON') return; // Don't open detail when clicking Name button
            openDeviceDetail(dev.device_ip);
        });

        // Device name/label
        var tdName = document.createElement('td');
        var nameSpan = document.createElement('span');
        nameSpan.style.fontWeight = '600';
        nameSpan.textContent = dev.device_label || dev.user_name || 'Unknown';
        if (isUnknown) nameSpan.style.color = '#f59e0b';
        tdName.appendChild(nameSpan);
        if (dev.device_type) {
            var typeSpan = document.createElement('span');
            typeSpan.style.cssText = 'display:block;font-size:11px;opacity:0.6';
            typeSpan.textContent = dev.device_type;
            tdName.appendChild(typeSpan);
        }
        tr.appendChild(tdName);

        // IP
        var tdIp = document.createElement('td');
        tdIp.textContent = dev.device_ip;
        tdIp.style.fontFamily = 'monospace';
        tr.appendChild(tdIp);

        // MAC
        var tdMac = document.createElement('td');
        tdMac.textContent = dev.device_mac || '-';
        tdMac.style.cssText = 'font-family:monospace;font-size:11px';
        tr.appendChild(tdMac);

        // Download
        var tdDown = document.createElement('td');
        tdDown.textContent = formatBytes(dev.total_in || 0);
        tdDown.style.color = '#22d3ee';
        tr.appendChild(tdDown);

        // Upload
        var tdUp = document.createElement('td');
        tdUp.textContent = formatBytes(dev.total_out || 0);
        tdUp.style.color = '#f472b6';
        tr.appendChild(tdUp);

        // Total
        var tdTotal = document.createElement('td');
        tdTotal.textContent = formatBytes(dev.total || 0);
        tdTotal.style.fontWeight = '600';
        tr.appendChild(tdTotal);

        // DNS Queries (unique_domains)
        var tdDns = document.createElement('td');
        var dnsCount = dev.unique_domains || 0;
        tdDns.textContent = dnsCount;
        if (dnsCount > 50) tdDns.style.color = '#00e5ff';
        tr.appendChild(tdDns);

        // Actions — Name button for unknown devices
        var tdAction = document.createElement('td');
        if (isUnknown) {
            var nameBtn = document.createElement('button');
            nameBtn.className = 'btn btn-sm';
            nameBtn.style.cssText = 'font-size:0.68rem;padding:2px 8px;background:#f59e0b;color:#000;border:none;border-radius:4px';
            nameBtn.textContent = 'Name';
            nameBtn.title = 'Give this device a friendly name';
            nameBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                _quickNameDevice(dev.device_mac || '', dev.device_ip || '');
            });
            tdAction.appendChild(nameBtn);
        }
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
}

function _quickNameDevice(mac, ip) {
    // Pre-fill the Add Device Mapping form and scroll to it
    var macEl = document.getElementById('device-mac');
    var ipEl = document.getElementById('device-ip');
    if (macEl) macEl.value = mac;
    if (ipEl) ipEl.value = ip;
    var nameEl = document.getElementById('device-name');
    if (nameEl) { nameEl.focus(); nameEl.scrollIntoView({behavior: 'smooth', block: 'center'}); }
    showToast('info', 'Fill in username and device name, then click Add Mapping');
}

async function openDeviceDetail(deviceIp) {
    var modal = document.getElementById('device-detail-modal');
    var body = document.getElementById('device-detail-body');
    var title = document.getElementById('device-detail-title');
    if (!modal || !body) return;

    modal.classList.add('active');
    body.textContent = '';
    var spinner = document.createElement('div');
    spinner.className = 'loading-state';
    spinner.textContent = 'Loading device detail...';
    body.appendChild(spinner);

    try {
        var resp = await fetch(SN_API + '/devices/detail/' + deviceIp);
        var d = await resp.json();
        if (!d.success) throw new Error(d.error || 'Failed to load');

        body.textContent = '';

        // Title
        title.textContent = (d.device.device_label || d.device.user_name || deviceIp) + ' \u2014 DEVICE DETAIL';

        // === Info Section ===
        var infoCard = document.createElement('div');
        infoCard.style.cssText = 'background:rgba(0,229,255,0.05);border:1px solid rgba(0,229,255,0.2);border-radius:8px;padding:16px;margin-bottom:16px';

        var infoGrid = document.createElement('div');
        infoGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:8px';

        var infoItems = [
            {label: 'IP Address', value: d.device.ip},
            {label: 'MAC Address', value: d.device.mac || 'Unknown'},
            {label: 'Label', value: d.device.device_label || '-'},
            {label: 'Type', value: d.device.device_type || 'Unknown'}
        ];
        infoItems.forEach(function(item) {
            var div = document.createElement('div');
            var label = document.createElement('div');
            label.style.cssText = 'font-size:11px;opacity:0.5;text-transform:uppercase';
            label.textContent = item.label;
            var val = document.createElement('div');
            val.style.cssText = 'font-family:monospace;font-size:14px';
            val.textContent = item.value;
            div.appendChild(label);
            div.appendChild(val);
            infoGrid.appendChild(div);
        });
        infoCard.appendChild(infoGrid);
        body.appendChild(infoCard);

        // === Bandwidth Section ===
        var bwCard = document.createElement('div');
        bwCard.style.cssText = 'background:rgba(0,229,255,0.05);border:1px solid rgba(0,229,255,0.2);border-radius:8px;padding:16px;margin-bottom:16px';

        var bwTitle = document.createElement('div');
        bwTitle.style.cssText = 'font-weight:600;margin-bottom:12px;color:var(--archie-text-primary)';
        bwTitle.textContent = 'Bandwidth (Last 24h)';
        bwCard.appendChild(bwTitle);

        var bwGrid = document.createElement('div');
        bwGrid.style.cssText = 'display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;text-align:center';

        [{label:'Download', val: d.bandwidth.total_in, color:'#22d3ee'},
         {label:'Upload', val: d.bandwidth.total_out, color:'#f472b6'},
         {label:'Total', val: d.bandwidth.total, color:'#fbbf24'}].forEach(function(b) {
            var div = document.createElement('div');
            var valDiv = document.createElement('div');
            valDiv.style.cssText = 'font-size:24px;font-weight:700;font-family:"Antonio",sans-serif;color:' + b.color;
            valDiv.textContent = formatBytes(b.val);
            var labelDiv = document.createElement('div');
            labelDiv.style.cssText = 'font-size:11px;opacity:0.5;text-transform:uppercase';
            labelDiv.textContent = b.label;
            div.appendChild(valDiv);
            div.appendChild(labelDiv);
            bwGrid.appendChild(div);
        });
        bwCard.appendChild(bwGrid);
        body.appendChild(bwCard);

        // === Top Domains Section ===
        if (d.top_domains && d.top_domains.length > 0) {
            var domCard = document.createElement('div');
            domCard.style.cssText = 'background:rgba(0,229,255,0.05);border:1px solid rgba(0,229,255,0.2);border-radius:8px;padding:16px;margin-bottom:16px';

            var domTitle = document.createElement('div');
            domTitle.style.cssText = 'font-weight:600;margin-bottom:12px;color:var(--archie-text-primary)';
            domTitle.textContent = 'Top Domains (Last 24h)';
            domCard.appendChild(domTitle);

            var domTable = document.createElement('table');
            domTable.className = 'data-table';
            domTable.style.fontSize = '13px';

            var domHead = document.createElement('thead');
            var domHr = document.createElement('tr');
            ['Domain', 'Queries', 'Status'].forEach(function(h) {
                var th = document.createElement('th');
                th.textContent = h;
                domHr.appendChild(th);
            });
            domHead.appendChild(domHr);
            domTable.appendChild(domHead);

            var domBody = document.createElement('tbody');
            d.top_domains.forEach(function(dom) {
                var tr = document.createElement('tr');

                var tdDom = document.createElement('td');
                tdDom.textContent = dom.domain;
                tdDom.style.fontFamily = 'monospace';
                tr.appendChild(tdDom);

                var tdQ = document.createElement('td');
                tdQ.textContent = dom.queries;
                tr.appendChild(tdQ);

                var tdStatus = document.createElement('td');
                var badge = document.createElement('span');
                badge.style.cssText = 'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;' +
                    (dom.blocked ? 'background:rgba(239,68,68,0.2);color:#ef4444' : 'background:rgba(34,197,94,0.2);color:#22c55e');
                badge.textContent = dom.blocked ? 'BLOCKED' : 'ALLOWED';
                tdStatus.appendChild(badge);
                tr.appendChild(tdStatus);

                domBody.appendChild(tr);
            });
            domTable.appendChild(domBody);
            domCard.appendChild(domTable);
            body.appendChild(domCard);
        }

        // === Timeline Section ===
        if (d.timeline && d.timeline.length > 1) {
            var tlCard = document.createElement('div');
            tlCard.style.cssText = 'background:rgba(0,229,255,0.05);border:1px solid rgba(0,229,255,0.2);border-radius:8px;padding:16px';

            var tlTitle = document.createElement('div');
            tlTitle.style.cssText = 'font-weight:600;margin-bottom:12px;color:var(--archie-text-primary)';
            tlTitle.textContent = 'Hourly Bandwidth Timeline';
            tlCard.appendChild(tlTitle);

            var tlTable = document.createElement('table');
            tlTable.className = 'data-table';
            tlTable.style.fontSize = '12px';

            var tlHead = document.createElement('thead');
            var tlHr = document.createElement('tr');
            ['Hour', 'Download', 'Upload'].forEach(function(h) {
                var th = document.createElement('th');
                th.textContent = h;
                tlHr.appendChild(th);
            });
            tlHead.appendChild(tlHr);
            tlTable.appendChild(tlHead);

            var tlBody = document.createElement('tbody');
            d.timeline.forEach(function(t) {
                var tr = document.createElement('tr');
                var tdH = document.createElement('td');
                tdH.textContent = t.hour ? new Date(t.hour).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '-';
                tr.appendChild(tdH);
                var tdIn = document.createElement('td');
                tdIn.textContent = formatBytes(t.bytes_in);
                tdIn.style.color = '#22d3ee';
                tr.appendChild(tdIn);
                var tdOut = document.createElement('td');
                tdOut.textContent = formatBytes(t.bytes_out);
                tdOut.style.color = '#f472b6';
                tr.appendChild(tdOut);
                tlBody.appendChild(tr);
            });
            tlTable.appendChild(tlBody);
            tlCard.appendChild(tlTable);
            body.appendChild(tlCard);
        }

    } catch(e) {
        body.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.className = 'empty-state';
        errDiv.textContent = 'Error: ' + e.message;
        body.appendChild(errDiv);
    }
}

function closeDeviceDetail() {
    var modal = document.getElementById('device-detail-modal');
    if (modal) modal.classList.remove('active');
}
