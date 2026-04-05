// API base — canonical definition is SN_API in security-network.js (loaded first)
var API = typeof SN_API !== 'undefined' ? SN_API : '/tools/security-network/api';

/* ========== Utility aliases — canonical implementations in security-network.js ========== */
// security-network.js (loaded first) defines: formatNum, setBadge, formatBytes, showToast
// It also defines snEsc, snBuildTable, snCreateBadge, snShowLoading, snShowEmpty with sn- prefix.
// These aliases let existing app.js call-sites work without renaming.
var esc        = typeof snEsc         !== 'undefined' ? snEsc         : function(s) { return s == null ? '' : String(s); };
var buildTable = typeof snBuildTable  !== 'undefined' ? snBuildTable  : function() { return document.createElement('table'); };
var createBadge= typeof snCreateBadge !== 'undefined' ? snCreateBadge : function(t) { var s=document.createElement('span'); s.textContent=t; return s; };
var showLoading= typeof snShowLoading !== 'undefined' ? snShowLoading : function() {};
var showEmpty  = typeof snShowEmpty   !== 'undefined' ? snShowEmpty   : function() {};
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
        setBadge('svc-npm', d.services && d.services.npm);
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
            const pEl = document.getElementById('dns-protection-status');
            pEl.textContent = d.protection_enabled !== false ? 'ON' : 'OFF';
            pEl.style.color = d.protection_enabled !== false ? 'var(--archie-green)' : 'var(--archie-red)';
        }
    } catch(e) { console.error('DNS overview error:', e); }
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
                var blocked = e.reason && e.reason !== 'NotFilteredNotFound';
                var clientIp = e.client || '-';
                var domain = q.name || '-';

                var tr = document.createElement('tr');
                // Red tint on blocked rows
                if (blocked) {
                    tr.style.background = 'rgba(239,68,68,0.06)';
                    tr.style.borderLeft = '3px solid rgba(239,68,68,0.4)';
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
                domLink.title = 'Click to block this domain';
                domLink.addEventListener('click', function() {
                    if (confirm('Block domain: ' + domain + '?')) {
                        fetch(API+'/dns/adguard/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain})})
                        .then(function(r){return r.json();}).then(function(d){
                            if(d.success) showToast('success',domain+' blocked');
                            else showToast('error',d.error||'Failed');
                        });
                    }
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
                tdStatus.appendChild(createBadge(blocked?'Blocked':'OK', blocked?'danger':'success'));
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
            if(!d.filters.length) { showEmpty(container,'No filters configured'); return; }
            container.textContent = '';
            const rows = d.filters.map(f => {
                const toggle = document.createElement('label');
                toggle.className = 'toggle-switch';
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.checked = f.enabled;
                input.addEventListener('change', function() { toggleFilter(f.url, this.checked); });
                const slider = document.createElement('span');
                slider.className = 'toggle-slider';
                toggle.appendChild(input);
                toggle.appendChild(slider);
                const delBtn = document.createElement('button');
                delBtn.className = 'btn btn-danger btn-sm';
                delBtn.textContent = 'Remove';
                delBtn.addEventListener('click', function() { removeFilter(f.url); });
                return [toggle, f.name, f.url, f.rules_count||0, delBtn];
            });
            container.appendChild(buildTable(['Enabled','Name','URL','Rules',''], rows));
        }
    } catch(e) { showEmpty(container, 'Error loading filters'); }
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
            if(!d.rewrites.length){showEmpty(container,'No DNS rewrites');return;}
            container.textContent='';
            const rows = d.rewrites.map(rw => {
                const delBtn = document.createElement('button');
                delBtn.className='btn btn-danger btn-sm';
                delBtn.textContent='Delete';
                delBtn.addEventListener('click', function(){deleteRewrite(rw.domain,rw.answer);});
                return [rw.domain, rw.answer, delBtn];
            });
            container.appendChild(buildTable(['Domain','Answer',''], rows));
        }
    } catch(e) { showEmpty(container,'Error loading rewrites'); }
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
        if(d.success) document.getElementById('user-rules').value = d.rules||'';
    } catch(e){console.error('Rules load error:',e);}
}

function saveUserRules() {
    const rules = document.getElementById('user-rules').value;
    fetch(API+'/dns/adguard/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rules:rules})})
    .then(r=>r.json()).then(d=>{if(d.success) showToast('success','Rules saved'); else showToast('error',d.error||'Failed');})
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
async function loadReconModules() {
    const grid = document.getElementById('recon-modules');
    const select = document.getElementById('recon-module');
    try {
        const r = await fetch(API+'/recon/modules');
        const d = await r.json();
        if(d.success && d.modules) {
            grid.textContent='';
            select.textContent='';
            // Flatten categories dict into flat list
            var allModules = [];
            var mods = d.modules;
            if (Array.isArray(mods)) {
                allModules = mods;
            } else if (typeof mods === 'object') {
                Object.keys(mods).forEach(function(cat) {
                    (mods[cat] || []).forEach(function(m) {
                        m.category = cat;
                        allModules.push(m);
                    });
                });
            }
            allModules.forEach(function(m) {
                var opt = document.createElement('option');
                opt.value = m.id || m.name;
                opt.textContent = m.name;
                select.appendChild(opt);
                var card = document.createElement('div');
                card.className='module-card';
                card.addEventListener('click', function(){select.value=m.id||m.name;document.getElementById('recon-target').focus();});
                var cat = document.createElement('div');
                cat.className='mod-cat'; cat.textContent=m.category||'other';
                var name = document.createElement('div');
                name.className='mod-name'; name.textContent=m.name;
                var desc = document.createElement('div');
                desc.className='mod-desc'; desc.textContent=m.description||'';
                card.appendChild(cat); card.appendChild(name); card.appendChild(desc);
                grid.appendChild(card);
            });
        }
    } catch(e) { showEmpty(grid,'Error loading modules'); }
}

async function loadReconHistory() {
    const container = document.getElementById('recon-history');
    try {
        const r = await fetch(API+'/recon/history?limit=20');
        const d = await r.json();
        if(d.success && d.scans && d.scans.length) {
            container.textContent='';
            const rows = d.scans.map(s=>{
                const statusCls = s.status==='completed'?'success':s.status==='running'?'warning':'danger';
                const actions = document.createElement('div');
                actions.style.display='flex'; actions.style.gap='4px';
                const viewBtn = document.createElement('button');
                viewBtn.className='btn btn-sm'; viewBtn.textContent='View';
                viewBtn.addEventListener('click',function(){viewScanResult(s.id);});
                const delBtn = document.createElement('button');
                delBtn.className='btn btn-danger btn-sm'; delBtn.textContent='Del';
                delBtn.addEventListener('click',function(){deleteReconScan(s.id);});
                actions.appendChild(viewBtn); actions.appendChild(delBtn);
                return ['#'+s.id, s.module_name, s.target, createBadge(s.status,statusCls), formatTime(s.started_at), actions];
            });
            container.appendChild(buildTable(['ID','Module','Target','Status','Started',''], rows));
        } else { showEmpty(container,'No scan history yet'); }
    } catch(e) { showEmpty(container,'Error loading scan history'); }
}

function startReconScan() {
    const module_name = document.getElementById('recon-module').value;
    const target = document.getElementById('recon-target').value.trim();
    if(!module_name||!target) return showToast('error','Select a module and enter a target');
    showToast('info','Starting scan...');
    fetch(API+'/recon/scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({module_name:module_name,target:target})})
    .then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Scan started (ID: '+d.scan_id+')');setTimeout(loadReconHistory,2000);}
        else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

function viewScanResult(scanId) {
    fetch(API+'/recon/scan/'+scanId).then(r=>r.json()).then(d=>{
        if(!d.success) return showToast('error',d.error||'Failed');
        const modal = document.getElementById('modal-content');
        modal.textContent = '';
        const header = document.createElement('div');
        header.className = 'modal-header';
        const h3 = document.createElement('h3');
        h3.textContent = 'Scan #'+scanId+' - '+(d.scan?d.scan.module_name:'');
        const closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-sm';
        closeBtn.textContent = 'Close';
        closeBtn.addEventListener('click', closeModal);
        header.appendChild(h3); header.appendChild(closeBtn);
        modal.appendChild(header);
        const info = document.createElement('div');
        info.style.marginBottom = '8px';
        info.appendChild(createBadge(d.scan?d.scan.status:'', d.scan&&d.scan.status==='completed'?'success':'warning'));
        const targetSpan = document.createElement('span');
        targetSpan.style.cssText = 'font-size:0.78rem;color:var(--archie-text-muted);margin-left:8px';
        targetSpan.textContent = 'Target: '+(d.scan?d.scan.target:'');
        info.appendChild(targetSpan);
        modal.appendChild(info);
        const pre = document.createElement('pre');
        pre.style.cssText = 'background:var(--archie-bg-tertiary);padding:12px;border-radius:8px;font-size:0.75rem;max-height:400px;overflow:auto;color:var(--archie-text-secondary)';
        pre.textContent = JSON.stringify(d.scan?d.scan.results:{}, null, 2);
        modal.appendChild(pre);
        document.getElementById('modal-overlay').classList.add('open');
    }).catch(e=>showToast('error',e.message));
}

function deleteReconScan(scanId) {
    if(!confirm('Delete scan #'+scanId+'?')) return;
    fetch(API+'/recon/scan/'+scanId,{method:'DELETE'}).then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Scan deleted');loadReconHistory();}else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

/* ========== Vulnerability Scanning ========== */
function showScannerForm(type) {
    activeScannerType = type;
    var titles = {nmap:'Nmap Port Scanner',nikto:'Nikto Web Scanner',nuclei:'Nuclei Template Scanner',ssl:'SSL/TLS Check',zap:'ZAP Web App Scanner'};
    document.getElementById('scanner-form-title').textContent = titles[type]||type;
    document.getElementById('scanner-form-card').style.display = 'block';
    document.getElementById('scan-type-group').style.display = (type==='nmap'||type==='zap')?'flex':'none';
    document.getElementById('scan-confirm-internal').style.display = 'none';
    document.getElementById('scan-target').placeholder = type==='ssl'?'example.com':'IP, hostname, or URL';
    if(type==='zap') {
        var sel = document.getElementById('scan-type');
        sel.textContent = '';
        ['spider','active','ajax'].forEach(function(v){var o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o);});
    } else {
        var sel = document.getElementById('scan-type');
        sel.textContent = '';
        ['quick','full','stealth'].forEach(function(v){var o=document.createElement('option');o.value=v;o.textContent=v;sel.appendChild(o);});
    }
}

function runVulnScan() {
    const target = document.getElementById('scan-target').value.trim();
    if(!target) return showToast('error','Enter a target');
    const internal = ['127.','localhost','192.168.','10.','172.'].some(function(p){return target.indexOf(p)===0;});
    if(internal && !document.getElementById('scan-confirm-checkbox').checked) {
        document.getElementById('scan-confirm-internal').style.display='block';
        return showToast('warning','Confirm internal target scan');
    }
    var body = {target:target};
    if(activeScannerType==='nmap'||activeScannerType==='zap') body.scan_type = document.getElementById('scan-type').value;
    if(activeScannerType==='ssl') body.domain = target;
    if(internal) body.confirm_internal = true;
    var endpoint = activeScannerType==='ssl'?'/scanner/ssl':'/scanner/'+activeScannerType;
    showToast('info','Starting '+activeScannerType+' scan...');
    fetch(API+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','Scan complete');loadScanResults();}else showToast('error',d.error||'Scan failed');
    }).catch(e=>showToast('error',e.message));
}

async function loadScanResults() {
    const container = document.getElementById('scan-results-list');
    try {
        /* Fetch both filesystem scans and DB recon scans in parallel */
        const [fileRes, reconRes] = await Promise.allSettled([
            fetch(API+'/scans').then(r=>r.json()),
            fetch(API+'/recon/history').then(r=>r.json())
        ]);
        const fileScans = (fileRes.status==='fulfilled' && fileRes.value.success && fileRes.value.scans) ? fileRes.value.scans : [];
        const reconScans = (reconRes.status==='fulfilled' && reconRes.value.success && reconRes.value.history) ? reconRes.value.history : [];

        /* Normalise recon scans to same shape as file scans */
        const normRecon = reconScans.map(s=>({
            id: s.id,
            filename: s.module_name+' → '+s.target,
            scan_type: s.module_name||'recon',
            created_at: s.started_at ? new Date(s.started_at).getTime()/1000 : 0,
            status: s.status,
            source: 'db'
        }));
        const normFile = fileScans.map(s=>({...s, source:'file'}));

        /* Merge and sort by time descending */
        const allScans = normFile.concat(normRecon).sort((a,b)=>(b.created_at||0)-(a.created_at||0));

        if(allScans.length) {
            container.textContent='';
            allScans.forEach(s=>{
                const card = document.createElement('div');
                card.className='scan-card';
                const info = document.createElement('div');
                const nameEl = document.createElement('strong');
                nameEl.textContent = s.filename;
                const meta = document.createElement('small');
                meta.style.color='var(--archie-text-muted)';
                const timeStr = s.created_at ? ArchieTime.format(new Date(s.created_at*1000).toISOString(), 'short') : '-';
                meta.textContent = ' | '+s.scan_type+' | '+timeStr;
                if(s.status) {
                    const badge = document.createElement('span');
                    badge.style.cssText='margin-left:6px;padding:1px 6px;border-radius:4px;font-size:0.7rem;background:'+
                        (s.status==='completed'?'var(--archie-green)':s.status==='running'?'var(--archie-cyan)':'var(--archie-orange)')+
                        ';color:#000';
                    badge.textContent=s.status;
                    meta.appendChild(badge);
                }
                info.appendChild(nameEl);
                info.appendChild(meta);
                const actions = document.createElement('div');
                actions.style.display='flex'; actions.style.gap='6px';
                if(s.source==='file') {
                    const viewBtn = document.createElement('button');
                    viewBtn.className='btn btn-sm'; viewBtn.textContent='View';
                    viewBtn.addEventListener('click',function(){viewScanFile(s.filename);});
                    actions.appendChild(viewBtn);
                    const dlLink = document.createElement('a');
                    dlLink.href=API+'/reports/download/'+encodeURIComponent(s.filename);
                    dlLink.className='btn btn-sm'; dlLink.textContent='Download';
                    actions.appendChild(dlLink);
                } else if(s.source==='db' && s.id) {
                    const viewBtn = document.createElement('button');
                    viewBtn.className='btn btn-sm'; viewBtn.textContent='View';
                    viewBtn.addEventListener('click',function(){viewReconScan(s.id);});
                    actions.appendChild(viewBtn);
                    const delBtn = document.createElement('button');
                    delBtn.className='btn btn-sm btn-danger'; delBtn.textContent='Delete';
                    delBtn.addEventListener('click',function(){deleteReconScan(s.id);});
                    actions.appendChild(delBtn);
                }
                card.appendChild(info); card.appendChild(actions);
                container.appendChild(card);
            });
        } else { showEmpty(container,'No scan results yet'); }
    } catch(e) { showEmpty(container,'Error loading scan results'); }
}

function viewScanFile(filename) {
    fetch(API+'/scans/'+encodeURIComponent(filename)).then(r=>r.json()).then(d=>{
        if(!d.success) return;
        const modal = document.getElementById('modal-content');
        modal.textContent='';
        const header = document.createElement('div');
        header.className='modal-header';
        const h3 = document.createElement('h3');
        h3.textContent=filename;
        const closeBtn = document.createElement('button');
        closeBtn.className='btn btn-sm'; closeBtn.textContent='Close';
        closeBtn.addEventListener('click',closeModal);
        header.appendChild(h3); header.appendChild(closeBtn);
        modal.appendChild(header);
        const pre = document.createElement('pre');
        pre.style.cssText='background:var(--archie-bg-tertiary);padding:12px;border-radius:8px;font-size:0.75rem;max-height:500px;overflow:auto;color:var(--archie-text-secondary)';
        pre.textContent = typeof d.content==='object'?JSON.stringify(d.content,null,2):d.content;
        modal.appendChild(pre);
        document.getElementById('modal-overlay').classList.add('open');
    }).catch(e=>showToast('error',e.message));
}

function viewReconScan(scanId) {
    fetch(API+'/recon/scan/'+scanId).then(r=>r.json()).then(d=>{
        if(!d.success) return showToast('error',d.error||'Failed to load scan');
        const modal = document.getElementById('modal-content');
        modal.textContent='';
        const header = document.createElement('div');
        header.className='modal-header';
        const h3 = document.createElement('h3');
        h3.textContent=(d.scan.module_name||'Scan')+' — '+(d.scan.target||'');
        const closeBtn = document.createElement('button');
        closeBtn.className='btn btn-sm'; closeBtn.textContent='Close';
        closeBtn.addEventListener('click',closeModal);
        header.appendChild(h3); header.appendChild(closeBtn);
        modal.appendChild(header);
        const pre = document.createElement('pre');
        pre.style.cssText='background:var(--archie-bg-tertiary);padding:12px;border-radius:8px;font-size:0.75rem;max-height:500px;overflow:auto;color:var(--archie-text-secondary)';
        const content = d.scan.results || d.scan.raw_output || d.scan;
        pre.textContent = typeof content==='object'?JSON.stringify(content,null,2):String(content);
        modal.appendChild(pre);
        document.getElementById('modal-overlay').classList.add('open');
    }).catch(e=>showToast('error',e.message));
}

/* SSL Monitors */
async function loadSSLMonitors() {
    const container = document.getElementById('ssl-monitors-list');
    try {
        const r = await fetch(API+'/ssl/monitors');
        const d = await r.json();
        if(d.success && d.monitors && d.monitors.length) {
            container.textContent='';
            const rows = d.monitors.map(m=>{
                const daysColor = (m.days_until_expiry||0)<30?'danger':'success';
                const expiry = document.createElement('span');
                expiry.style.color = daysColor==='danger'?'var(--archie-red)':'var(--archie-green)';
                expiry.textContent = (m.valid_until?ArchieTime.date(m.valid_until):'-')+' ('+(m.days_until_expiry||'?')+'d)';
                return [m.domain, m.issuer||'-', expiry, createBadge(m.grade||'?', (m.grade==='A'||m.grade==='A+')?'success':'warning')];
            });
            container.appendChild(buildTable(['Domain','Issuer','Expires','Grade'], rows));
        } else {
            /* No monitors — offer to auto-seed from NPM proxy hosts */
            container.textContent='';
            const wrap = document.createElement('div');
            wrap.style.cssText='text-align:center;padding:24px;color:var(--archie-text-muted)';
            const msg = document.createElement('p');
            msg.textContent='No SSL monitors configured.';
            wrap.appendChild(msg);
            const seedBtn = document.createElement('button');
            seedBtn.className='btn btn-primary btn-sm';
            seedBtn.textContent='Auto-add from NPM Proxy Hosts';
            seedBtn.addEventListener('click', seedSSLFromProxyHosts);
            wrap.appendChild(seedBtn);
            container.appendChild(wrap);
        }
    } catch(e) { showEmpty(container,'Error loading SSL monitors'); }
}

async function seedSSLFromProxyHosts() {
    try {
        showToast('info','Fetching proxy hosts...');
        const r = await fetch(API+'/domains/proxy-hosts');
        const d = await r.json();
        if(!d.success || !d.proxy_hosts || !d.proxy_hosts.length) {
            return showToast('warning','No proxy hosts found in NPM');
        }
        /* Extract unique domains from proxy hosts */
        const domains = [];
        d.proxy_hosts.forEach(h=>{
            (h.domain_names||[]).forEach(dn=>{
                if(dn && !domains.includes(dn)) domains.push(dn);
            });
        });
        if(!domains.length) return showToast('warning','No domains found in proxy hosts');
        let added=0, failed=0;
        for(const domain of domains) {
            try {
                const ar = await fetch(API+'/ssl/monitors',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain})});
                const ad = await ar.json();
                if(ad.success) added++; else failed++;
            } catch(e) { failed++; }
        }
        showToast('success','Added '+added+' SSL monitor(s)'+(failed?' ('+failed+' failed)':''));
        loadSSLMonitors();
    } catch(e) { showToast('error','Failed to seed: '+e.message); }
}

function showAddSSLModal() {
    const domain = prompt('Enter domain to monitor (e.g., example.com):');
    if(!domain) return;
    fetch(API+'/ssl/monitors',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({domain:domain})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','SSL monitor added');loadSSLMonitors();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

function refreshSSLMonitors() {
    fetch(API+'/ssl/refresh',{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){showToast('success','SSL monitors refreshed');loadSSLMonitors();}else showToast('error',d.error||'Failed');
    }).catch(e=>showToast('error',e.message));
}

/* ========== Access Control ========== */
// SYSOPS_API alias — same base URL as SN_API / API
var SYSOPS_API = typeof SN_API !== 'undefined' ? SN_API : '/tools/security-network/api';

async function loadFirewall() {
    var panel = document.getElementById('firewall-panel');
    var rulesDiv = document.getElementById('firewall-rules');
    try {
        var r = await fetch(SYSOPS_API+'/firewall/status');
        var d = await r.json();
        if(d.success) {
            var fw = d.firewall || d;
            panel.textContent='';
            var wrap = document.createElement('div');
            wrap.style.cssText='display:flex;gap:16px;flex-wrap:wrap';
            var items = [
                {label:'STATUS', badge:fw.active?'Active':'Inactive', type:fw.active?'success':'danger'},
                {label:'RULES', text:String(fw.rules_count||fw.rule_count||0)},
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
        } else { showEmpty(panel,'Firewall status unavailable'); }
    } catch(e) { showEmpty(panel,'Error loading firewall'); }

    // Load rules
    try {
        var r2 = await fetch(SYSOPS_API+'/firewall/rules');
        var d2 = await r2.json();
        rulesDiv.textContent='';
        var rules = d2.rules || [];
        if(rules.length === 0) { showEmpty(rulesDiv,'No firewall rules'); return; }
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
    } catch(e) { showEmpty(rulesDiv,'Error loading rules'); }
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
            const rows = d.events.map(ev=>{
                const sevCls = ev.severity==='critical'||ev.severity==='high'?'danger':ev.severity==='medium'?'warning':'info';
                const actions = document.createElement('span');
                if(ev.status!=='resolved'){
                    const btn = document.createElement('button');
                    btn.className='btn btn-success btn-sm'; btn.textContent='Resolve';
                    btn.addEventListener('click',function(){resolveEvent(ev.id);});
                    actions.appendChild(btn);
                } else { actions.appendChild(createBadge('Resolved','success')); }
                return [formatTime(ev.created_at), ev.event_type||ev.type||'-', createBadge(ev.severity||'-',sevCls), ev.description||'', actions];
            });
            container.appendChild(buildTable(['Time','Type','Severity','Details',''], rows));
        } else { showEmpty(container,'No security events'); }
    } catch(e) { showEmpty(container,'Error loading events'); }
}

function resolveEvent(eventId) {
    const notes = prompt('Resolution notes (optional):')||'';
    fetch(API+'/events/'+eventId+'/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:notes})})
    .then(r=>r.json()).then(d=>{if(d.success){showToast('success','Event resolved');loadSecurityEvents();}else showToast('error',d.error||'Failed');})
    .catch(e=>showToast('error',e.message));
}

async function loadConnections() {
    const container = document.getElementById('connections-list');
    try {
        const r = await fetch(API+'/connections/active');
        const d = await r.json();
        if(d.success && d.connections && d.connections.length) {
            container.textContent='';
            const rows = d.connections.slice(0,50).map(c=>[
                c.proto||c.type||'-', c.local_address||c.laddr||'-',
                c.remote_address||c.raddr||'-', createBadge(c.status||'-','muted'), c.pid||'-'
            ]);
            container.appendChild(buildTable(['Proto','Local','Remote','Status','PID'], rows));
        } else { showEmpty(container,'No active connections data'); }
    } catch(e) { showEmpty(container,'Error loading connections'); }
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

        let html = '<div style="padding:16px;max-height:70vh;overflow-y:auto">';
        html += '<h2 style="color:var(--archie-text-primary);margin:0 0 4px">' + (rpt.title||'Report') + '</h2>';
        html += '<p style="color:var(--archie-text-muted);font-size:0.82rem;margin:0 0 16px">Generated: ' + (rpt.created_at||'-') + '</p>';

        if(content.events_by_severity && content.events_by_severity.length) {
            html += '<h3 style="color:var(--archie-accent)">Events by Severity</h3><ul>';
            content.events_by_severity.forEach(e=>{ html += '<li><strong>'+e.severity+'</strong>: '+e.count+'</li>'; });
            html += '</ul>';
        }
        if(content.recent_events && content.recent_events.length) {
            html += '<h3 style="color:var(--archie-accent)">Recent Events ('+content.recent_events.length+')</h3>';
            html += '<table class="data-table"><thead><tr><th>Type</th><th>Severity</th><th>Status</th><th>Description</th></tr></thead><tbody>';
            content.recent_events.forEach(e=>{
                html += '<tr><td>'+e.type+'</td><td>'+e.severity+'</td><td>'+e.status+'</td><td>'+(e.description||'-')+'</td></tr>';
            });
            html += '</tbody></table>';
        }
        if(content.daily_breakdown) {
            html += '<h3 style="color:var(--archie-accent)">Daily Breakdown</h3><pre style="background:var(--archie-bg-tertiary);padding:12px;border-radius:6px;overflow-x:auto;color:var(--archie-text-secondary)">' + JSON.stringify(content.daily_breakdown, null, 2) + '</pre>';
        }
        if(content.devices && content.devices.length) {
            html += '<h3 style="color:var(--archie-accent)">Devices ('+content.total_devices+')</h3>';
            html += '<table class="data-table"><thead><tr><th>Hostname</th><th>IP</th><th>Type</th><th>Zone</th><th>Status</th></tr></thead><tbody>';
            content.devices.forEach(dev=>{
                html += '<tr><td>'+(dev.hostname||'-')+'</td><td>'+dev.ip+'</td><td>'+(dev.type||'-')+'</td><td>'+(dev.zone||'-')+'</td><td>'+dev.status+'</td></tr>';
            });
            html += '</tbody></table>';
        }
        if(content.zone_summary && content.zone_summary.length) {
            html += '<h3 style="color:var(--archie-accent)">Zone Summary</h3><ul>';
            content.zone_summary.forEach(z=>{ html += '<li><strong>'+z.zone+'</strong>: '+z.count+' devices</li>'; });
            html += '</ul>';
        }
        if(content.dns_changes && content.dns_changes.length) {
            html += '<h3 style="color:var(--archie-accent)">DNS Changes ('+content.dns_changes.length+')</h3>';
            html += '<table class="data-table"><thead><tr><th>Source</th><th>Action</th><th>Domain</th><th>By</th><th>Date</th></tr></thead><tbody>';
            content.dns_changes.forEach(c=>{
                html += '<tr><td>'+c.source+'</td><td>'+c.action+'</td><td>'+(c.domain||'-')+'</td><td>'+(c.changed_by||'-')+'</td><td>'+(c.created_at||'-')+'</td></tr>';
            });
            html += '</tbody></table>';
        }
        if(content.dns_providers && content.dns_providers.length) {
            html += '<h3 style="color:var(--archie-accent)">DNS Providers</h3><ul>';
            content.dns_providers.forEach(p=>{ html += '<li><strong>'+p.name+'</strong> ('+p.type+') — '+(p.active?'Active':'Inactive')+'</li>'; });
            html += '</ul>';
        }
        if(content.scan_findings && content.scan_findings.length) {
            html += '<h3 style="color:var(--archie-accent)">Scan Findings</h3><ul>';
            content.scan_findings.forEach(f=>{ html += '<li><strong>'+f.severity+'</strong>: '+f.count+'</li>'; });
            html += '</ul>';
        }

        // Fallback: show raw JSON if no specific sections rendered
        const hasContent = (content.events_by_severity||[]).length || (content.recent_events||[]).length ||
            content.daily_breakdown || (content.devices||[]).length || (content.dns_changes||[]).length;
        if(!hasContent) {
            html += '<pre style="background:var(--archie-bg-tertiary);padding:12px;border-radius:6px;overflow-x:auto;color:var(--archie-text-secondary)">' + JSON.stringify(content, null, 2) + '</pre>';
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
        if (!d.success) { showToast('error', d.error || 'Failed to load domains overview'); return; }

        document.getElementById('domains-public-ip').textContent = d.public_ip || 'Unknown';
        document.getElementById('domains-dns-count').textContent = Array.isArray(d.dns_records) ? d.dns_records.length : '--';
        document.getElementById('domains-proxy-count').textContent = Array.isArray(d.proxy_hosts) ? d.proxy_hosts.length : '--';

        /* Certificate count from overview response */
        document.getElementById('domains-cert-count').textContent = Array.isArray(d.certificates) ? d.certificates.length : '--';

        // Build unified subdomain map
        const dnsRecords = Array.isArray(d.dns_records) ? d.dns_records : [];
        const proxyHosts = Array.isArray(d.proxy_hosts) ? d.proxy_hosts : [];

        // Index proxy hosts by domain name
        const proxyMap = {};
        proxyHosts.forEach(function(h) {
            (h.domain_names || []).forEach(function(dn) { proxyMap[dn] = h; });
        });

        // Build rows from DNS A records + proxy hosts
        const subdomains = {};
        dnsRecords.filter(function(r) { return r.type === 'A'; }).forEach(function(r) {
            const name = r.name || '@';
            if (!subdomains[name]) subdomains[name] = {};
            subdomains[name].dnsIP = (r.records && r.records[0] && r.records[0].content) || r.content || '--';
            subdomains[name].ttl = r.ttl;
        });

        // Match proxy hosts
        proxyHosts.forEach(function(h) {
            (h.domain_names || []).forEach(function(dn) {
                const parts = dn.split('.');
                const sub = parts.length > 2 ? parts[0] : '@';
                if (!subdomains[sub]) subdomains[sub] = {};
                subdomains[sub].npmTarget = h.forward_host + ':' + h.forward_port;
                subdomains[sub].ssl = h.ssl_forced ? 'Active' : (h.certificate_id ? 'Cert Only' : 'None');
                subdomains[sub].proxyId = h.id;
                subdomains[sub].fullDomain = dn;
            });
        });

        const tbody = document.getElementById('domains-unified-body');
        const keys = Object.keys(subdomains).sort();
        if (keys.length === 0) {
            tbody.textContent = '';
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 5;
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

            const tdNpm = document.createElement('td');
            tdNpm.textContent = s.npmTarget || '--';
            tr.appendChild(tdNpm);

            const tdSsl = document.createElement('td');
            const sslSpan = document.createElement('span');
            if (s.ssl === 'Active') { sslSpan.style.color = '#22c55e'; sslSpan.textContent = '\u25CF Active'; }
            else if (s.ssl === 'Cert Only') { sslSpan.style.color = '#f59e0b'; sslSpan.textContent = '\u25CF Cert Only'; }
            else { sslSpan.style.color = 'var(--text-dim)'; sslSpan.textContent = '\u25CF None'; }
            tdSsl.appendChild(sslSpan);
            tr.appendChild(tdSsl);

            const tdActions = document.createElement('td');
            if (s.proxyId) {
                const btn = document.createElement('button');
                btn.className = 'btn btn-sm btn-danger';
                btn.textContent = 'Delete Proxy';
                btn.addEventListener('click', function() { deleteProxyHost(s.proxyId); });
                tdActions.appendChild(btn);
            }
            tr.appendChild(tdActions);

            tbody.appendChild(tr);
        });

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

async function loadDomainProxyHosts() {
    try {
        const r = await fetch(API + '/domains/proxy-hosts');
        const d = await r.json();
        if (!d.success) { showToast('error', d.error || 'Failed'); return; }

        const hosts = Array.isArray(d.proxy_hosts) ? d.proxy_hosts : [];
        const tbody = document.getElementById('domains-proxy-body');
        tbody.textContent = '';

        if (hosts.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 5; td.style.textAlign = 'center'; td.style.color = 'var(--text-dim)';
            td.textContent = 'No proxy hosts';
            tr.appendChild(td); tbody.appendChild(tr);
            return;
        }

        hosts.forEach(function(h) {
            const tr = document.createElement('tr');
            tr.addEventListener('click', function(e) {
                if (e.target.tagName === 'BUTTON') return;
                openProxyModal(h);
            });

            const tdDomain = document.createElement('td');
            tdDomain.textContent = (h.domain_names || []).join(', ');
            tr.appendChild(tdDomain);

            const tdTarget = document.createElement('td');
            tdTarget.textContent = (h.forward_scheme || 'http') + '://' + h.forward_host + ':' + h.forward_port;
            tr.appendChild(tdTarget);

            const tdSsl = document.createElement('td');
            const sslSpan = document.createElement('span');
            if (h.ssl_forced) { sslSpan.style.color = '#22c55e'; sslSpan.textContent = '\u25CF Forced'; }
            else if (h.certificate_id) { sslSpan.style.color = '#f59e0b'; sslSpan.textContent = '\u25CF Cert Only'; }
            else { sslSpan.style.color = 'var(--text-dim)'; sslSpan.textContent = '\u25CF None'; }
            tdSsl.appendChild(sslSpan);
            tr.appendChild(tdSsl);

            const tdStatus = document.createElement('td');
            const statusSpan = document.createElement('span');
            if (h.enabled !== false) { statusSpan.style.color = '#22c55e'; statusSpan.textContent = 'Active'; }
            else { statusSpan.style.color = 'var(--text-dim)'; statusSpan.textContent = 'Disabled'; }
            tdStatus.appendChild(statusSpan);
            tr.appendChild(tdStatus);

            const tdActions = document.createElement('td');
            const delBtn = document.createElement('button');
            delBtn.className = 'btn btn-sm btn-danger';
            delBtn.textContent = 'Delete';
            delBtn.addEventListener('click', function(e) { e.stopPropagation(); deleteProxyHost(h.id); });
            tdActions.appendChild(delBtn);
            tr.appendChild(tdActions);

            tbody.appendChild(tr);
        });
    } catch (e) {
        showToast('error', 'Failed to load proxy hosts: ' + e.message);
    }
}

async function deleteProxyHost(id) {
    if (!confirm('Delete this proxy host? This cannot be undone.')) return;
    try {
        const r = await fetch(API + '/domains/proxy-hosts/' + id, {method: 'DELETE'});
        const d = await r.json();
        if (d.success) {
            showToast('success', 'Proxy host deleted');
            loadDomainProxyHosts();
            loadDomainsOverview();
        } else {
            showToast('error', d.error || 'Failed to delete');
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

/* ========== Proxy Host Modal ========== */
let proxyEditState = { id: null };

function openProxyModal(host) {
    proxyEditState.id = host ? host.id : null;

    const domains = (host && host.domain_names) ? host.domain_names.join(', ') : '';
    document.getElementById('proxy-edit-domain').value = domains;
    document.getElementById('proxy-edit-host').value = host ? (host.forward_host || '') : '192.168.1.200';
    document.getElementById('proxy-edit-port').value = host ? (host.forward_port || 3000) : 3000;
    document.getElementById('proxy-edit-ssl').value = host ? (host.ssl_forced ? 'Active (Forced)' : host.certificate_id ? 'Certificate Only' : 'None') : 'None';

    document.getElementById('proxy-edit-modal').classList.add('active');
}

function closeProxyModal() {
    document.getElementById('proxy-edit-modal').classList.remove('active');
}

async function saveProxyHost() {
    if (!proxyEditState.id) return;
    const host = document.getElementById('proxy-edit-host').value.trim();
    const port = parseInt(document.getElementById('proxy-edit-port').value) || 3000;

    try {
        const r = await fetch(API + '/domains/proxy-hosts/' + proxyEditState.id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ forward_host: host, forward_port: port })
        });
        const d = await r.json();
        if (d.success) {
            showToast('success', 'Proxy host updated');
            closeProxyModal();
            loadDomainProxyHosts();
            loadDomainsOverview();
        } else {
            showToast('error', d.error || 'Failed to update');
        }
    } catch (e) { showToast('error', e.message); }
}

async function deleteProxyFromModal() {
    if (!proxyEditState.id) return;
    if (!confirm('Delete this proxy host?')) return;

    try {
        const r = await fetch(API + '/domains/proxy-hosts/' + proxyEditState.id, { method: 'DELETE' });
        const d = await r.json();
        if (d.success) {
            showToast('success', 'Proxy host deleted');
            closeProxyModal();
            loadDomainProxyHosts();
            loadDomainsOverview();
        } else {
            showToast('error', d.error || 'Failed to delete');
        }
    } catch (e) { showToast('error', e.message); }
}

/* Close modals on Escape */
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeDnsModal(); closeProxyModal(); closeDeviceModal(); closeBlockDomainModal(); if(typeof closeReportModal==='function') closeReportModal(); if(typeof closeCameraModal==='function') closeCameraModal(); }
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
                { label: 'NMAP SCAN', cls: 'amber', fn: "switchToTab('recon')", id: 'secCmdNmap' },
                { label: 'SSL CHECK', cls: 'green', fn: "switchToTab('scanning')", id: 'secCmdSsl' },
                { label: 'DEVICE AUDIT', cls: 'cyan', fn: "loadDeviceClients()", id: 'secCmdDevices' },
                { label: 'DNS REPORT', cls: 'purple', fn: "switchToTab('dns')", id: 'secCmdDns' }
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
let _lastScanId = null;
let _compHistoryChart = null;

function _compScoreColor(score) { return score >= 80 ? '#22c55e' : score >= 50 ? '#f59e0b' : '#ef4444'; }
function _compGrade(score) { return score >= 95 ? 'A+' : score >= 90 ? 'A' : score >= 85 ? 'B+' : score >= 80 ? 'B' : score >= 70 ? 'C' : score >= 60 ? 'D' : 'F'; }
function _compEsc(s) { return (s || '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

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
            loadScanHistory();
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
        const resp = await fetch('/tools/security-network/api/compliance/scans/' + scanId);
        const data = await resp.json();
        _complianceResults = data.results || [];
        filterComplianceResults();
    } catch (e) {
        console.error('Failed to load compliance results:', e);
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
                + (!isPass ? '<a class="comp-finding-fix" onclick="switchTab(\'hardening\');return false;" href="#">Fix \u25B6</a>' : '')
                + '</div>';
        }

        html += '</div></div>';
    }

    container.innerHTML = html;
}

async function loadScanHistory() {
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
    loadScanHistory();
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

async function loadNetworkMonitor() {
    var container = document.getElementById('network-monitor-table');
    if (!container) return;
    container.textContent = '';

    try {
        var resp = await fetch(SN_API + '/api/devices/list?hours=24');
        var d = await resp.json();
        if (!d.success || !d.devices || d.devices.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = 'No device activity in the last 24 hours';
            container.appendChild(empty);
            return;
        }

        var table = document.createElement('table');
        table.className = 'data-table';

        // Header
        var thead = document.createElement('thead');
        var headerRow = document.createElement('tr');
        ['Device', 'IP', 'MAC', 'Download', 'Upload', 'Total', 'Domains'].forEach(function(h) {
            var th = document.createElement('th');
            th.textContent = h;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        // Body
        var tbody = document.createElement('tbody');
        d.devices.forEach(function(dev) {
            var tr = document.createElement('tr');
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', function() { openDeviceDetail(dev.device_ip); });

            // Device name/label
            var tdName = document.createElement('td');
            var nameSpan = document.createElement('span');
            nameSpan.style.fontWeight = '600';
            nameSpan.textContent = dev.device_label || dev.user_name || 'Unknown';
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

            // Download (bytes_in = received from network)
            var tdDown = document.createElement('td');
            tdDown.textContent = formatBytes(dev.total_in || 0);
            tdDown.style.color = '#22d3ee';
            tr.appendChild(tdDown);

            // Upload (bytes_out = sent to network)
            var tdUp = document.createElement('td');
            tdUp.textContent = formatBytes(dev.total_out || 0);
            tdUp.style.color = '#f472b6';
            tr.appendChild(tdUp);

            // Total
            var tdTotal = document.createElement('td');
            tdTotal.textContent = formatBytes(dev.total || 0);
            tdTotal.style.fontWeight = '600';
            tr.appendChild(tdTotal);

            // Domains count
            var tdDomains = document.createElement('td');
            tdDomains.textContent = dev.unique_domains || '0';
            tr.appendChild(tdDomains);

            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        container.appendChild(table);

    } catch(e) {
        console.error('loadNetworkMonitor error:', e);
        var errDiv = document.createElement('div');
        errDiv.className = 'empty-state';
        errDiv.textContent = 'Error loading network monitor: ' + e.message;
        container.appendChild(errDiv);
    }
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
        var resp = await fetch(SN_API + '/api/devices/detail/' + deviceIp);
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
