/* Starship Command — Fleet management JS */
var selectedNodeId = null;
var selectedNodeDbId = null;
var nodeCache = {};
var pendingConfig = null;
var nodeConnectionPoller = null;
var _opsSelectedNodeDbId = null;

// ── Hero Starbase Stats ──
function _setLive(el, value, isLive) {
    if (!el) return;
    el.textContent = value;
    el.classList.toggle('sc-live', !!isLive);
    el.classList.toggle('sc-static', !isLive);
}

async function loadHeroStats() {
    try {
        var resp = await fetch('/tools/starship/api/starbase-stats');
        var data = await resp.json();
        var el = function(id) { return document.getElementById(id); };
        var ok = data.success;
        _setLive(el('hero-agents'), ok ? (data.total_agents || 0) : '--', ok);
        _setLive(el('hero-models'), ok ? (data.loaded_models || 0) : '--', ok);
        _setLive(el('hero-jobs'), ok ? (data.active_jobs || 0) : '--', ok);
        _setLive(el('hero-nodes'), ok ? ((data.online_nodes || 0) + '/' + (data.total_nodes || 0)) : '--', ok);
    } catch(e) {
        console.warn('Hero stats load failed:', e);
        var el = function(id) { return document.getElementById(id); };
        ['hero-agents','hero-models','hero-jobs','hero-nodes'].forEach(function(id) {
            _setLive(el(id), '--', false);
        });
    }
}

// ── Docked Fleet — load agent counts per node ──
async function loadDockedFleetStats() {
    try {
        var resp = await fetch('/tools/starship/api/nodes');
        var data = await resp.json();
        if (!data.success) return;
        data.nodes.forEach(function(n) {
            var agentEl = document.getElementById('dock-agents-' + n.node_id);
            if (agentEl) {
                // Fetch agent count for this node
                fetch('/tools/starship/api/nodes/' + n.node_id + '/status')
                    .then(function(r) { return r.json(); })
                    .then(function(s) {
                        if (s.success) {
                            _setLive(agentEl, s.agent_count || 0, true);
                        }
                    }).catch(function() {});
            }
        });
    } catch(e) {
        console.warn('Docked fleet stats failed:', e);
    }
}

// ── Page-Level Tab Switching ──
function switchPageTab(tab) {
    document.querySelectorAll('.sc-page-tab').forEach(function(t) {
        t.classList.toggle('active', t.getAttribute('data-page-tab') === tab);
    });
    document.querySelectorAll('.sc-page-panel').forEach(function(p) {
        p.classList.toggle('active', p.id === 'page-' + tab);
    });
    if (tab === 'operations') {
        loadOpsModelCatalog();
    }
}

// ── Operations Tab: Node Selector ──
function onOpsNodeSelect(nodeId) {
    var content = document.getElementById('ops-content');
    if (!nodeId) {
        content.style.display = 'none';
        _opsSelectedNodeDbId = null;
        return;
    }
    content.style.display = '';
    // Look up the DB id for this node from the fleet
    fetch('/tools/starship/api/nodes/' + nodeId + '/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success && data.node) {
                _opsSelectedNodeDbId = data.node.id;
                opsLoadSyncStatus();
                opsLoadSyncLog();
            }
        }).catch(function() {});
}

// ── Operations Tab: OTA Push ──
function opsOtaPush(type) {
    if (!_opsSelectedNodeDbId) { scToast('Select a node first', 'error'); return; }
    var endpoint = type === 'update'
        ? '/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/push-update'
        : '/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/push-config';
    var body = type === 'config' ? JSON.stringify({type: 'agent_config'}) : '{}';
    if (type === 'update' && !confirm('Push a code update to this node?')) return;
    fetch(endpoint, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: body })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                scToast('Push successful' + (data.sync_id ? ' (ID: ' + data.sync_id + ')' : ''), 'success');
                opsLoadSyncStatus();
                opsLoadSyncLog();
            } else {
                scToast(data.error || 'Push failed', 'error');
            }
        }).catch(function() { scToast('Network error', 'error'); });
}

// ── Operations Tab: Pull Model ──
function opsPullModel() {
    if (!_opsSelectedNodeDbId) { scToast('Select a node first', 'error'); return; }
    var sel = document.getElementById('ops-pull-model-select');
    var model = sel.value;
    if (!model) { scToast('Select a model', 'error'); return; }
    fetch('/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/pull-model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model_name: model})
    }).then(function(r) { return r.json(); })
      .then(function(data) {
          if (data.success) { scToast('Model pull queued', 'success'); }
          else { scToast(data.error || 'Failed', 'error'); }
      }).catch(function() { scToast('Network error', 'error'); });
}

// ── Operations Tab: Sync Status + Log ──
function opsLoadSyncStatus() {
    if (!_opsSelectedNodeDbId) return;
    fetch('/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/sync-status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var dot = document.getElementById('ops-sync-dot');
            var ind = document.getElementById('ops-sync-indicator');
            if (!dot || !ind) return;
            if (data.pending_count === 0) {
                dot.style.background = '#00ff41';
                ind.style.color = 'rgba(0,255,65,0.7)';
                ind.textContent = 'All synced \u2014 v' + (data.config_version || 1);
            } else {
                dot.style.background = '#ffaa00';
                ind.style.color = 'rgba(255,170,0,0.8)';
                ind.textContent = data.pending_count + ' change' + (data.pending_count > 1 ? 's' : '') + ' pending';
            }
        }).catch(function() {});
}

function opsLoadSyncLog() {
    if (!_opsSelectedNodeDbId) return;
    fetch('/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/sync-log')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var tbody = document.getElementById('ops-sync-log-body');
            if (!tbody) return;
            tbody.textContent = '';
            var logs = data.logs || [];
            if (logs.length === 0) {
                var row = document.createElement('tr');
                var td = document.createElement('td');
                td.colSpan = 3; td.textContent = 'No sync activity yet.';
                td.style.color = 'rgba(255,255,255,0.3)';
                row.appendChild(td); tbody.appendChild(row);
                return;
            }
            logs.forEach(function(log) {
                var row = document.createElement('tr');
                var typeTd = document.createElement('td');
                typeTd.textContent = log.sync_type || '\u2014';
                typeTd.style.cssText = 'padding:6px;color:var(--sc-accent);font-family:IBM Plex Mono,monospace;font-size:0.8rem;';
                var statusTd = document.createElement('td');
                statusTd.textContent = log.status || '\u2014';
                statusTd.className = 'sync-status-' + (log.status || '');
                statusTd.style.cssText = 'padding:6px;font-family:IBM Plex Mono,monospace;font-size:0.8rem;';
                var timeTd = document.createElement('td');
                timeTd.textContent = log.created_at ? new Date(log.created_at).toLocaleString() : '\u2014';
                timeTd.style.cssText = 'padding:6px;color:rgba(255,255,255,0.5);font-family:IBM Plex Mono,monospace;font-size:0.8rem;';
                row.appendChild(typeTd); row.appendChild(statusTd); row.appendChild(timeTd);
                tbody.appendChild(row);
            });
        }).catch(function() {});
}

var _opsModelCatalogLoaded = false;
function loadOpsModelCatalog() {
    if (_opsModelCatalogLoaded) return;
    _opsModelCatalogLoaded = true;
    fetch('/tools/starship/api/model-catalog')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var sel = document.getElementById('ops-pull-model-select');
            if (!sel) return;
            (data.models || []).forEach(function(m) {
                var opt = document.createElement('option');
                opt.value = m.name || m;
                opt.textContent = m.name || m;
                sel.appendChild(opt);
            });
        }).catch(function() {});
}

// ── Helper: render ops gauge (CPU/RAM/GPU) ──
function renderOpsGauge(valId, barId, pct) {
    pct = pct || 0;
    var valEl = document.getElementById(valId);
    var barEl = document.getElementById(barId);
    valEl.textContent = Math.round(pct) + '%';
    valEl.className = 'sc-ops-metric-val' + (pct >= 90 ? ' crit' : pct >= 70 ? ' warn' : '');
    barEl.style.width = Math.min(pct, 100) + '%';
    barEl.style.background = pct >= 90 ? 'var(--sc-red)' : pct >= 70 ? 'var(--sc-amber)' : 'var(--sc-green)';
}

// ── Helper: build summary span (<strong>N</strong> label) ──
function buildSummarySpan(parent, value, label) {
    var span = document.createElement('span');
    var strong = document.createElement('strong');
    strong.textContent = value;
    span.appendChild(strong);
    span.appendChild(document.createTextNode(' ' + label));
    parent.appendChild(span);
}

// ── Add Node Modal ──
function openAddNodeModal() {
    document.getElementById('add-node-modal').classList.add('active');
    document.getElementById('modal-step-1').style.display = '';
    document.getElementById('modal-step-2').style.display = 'none';
    document.getElementById('new-node-name').value = '';
    document.getElementById('new-node-name').focus();
}

function closeAddNodeModal() {
    document.getElementById('add-node-modal').classList.remove('active');
    pendingConfig = null;
    if (nodeConnectionPoller) { clearInterval(nodeConnectionPoller); nodeConnectionPoller = null; }
}

// Resync modal
function showResyncModal() {
    var serverUrl = window.location.origin;
    var winCmd = document.getElementById('resync-cmd-win');
    var linuxCmd = document.getElementById('resync-cmd-linux');
    // Keep the copy buttons, set text before them
    var winText = 'iwr -useb ' + serverUrl + '/tools/bridge/api/nodes/update.ps1 | iex';
    var linuxText = 'curl -sL ' + serverUrl + '/tools/bridge/api/nodes/heartbeat.sh -o /opt/archie-node/heartbeat.sh && chmod +x /opt/archie-node/heartbeat.sh && systemctl restart archie-node';
    // Clear and rebuild
    var winCopy = winCmd.querySelector('.sc-copy-btn');
    var linuxCopy = linuxCmd.querySelector('.sc-copy-btn');
    winCmd.textContent = winText;
    winCmd.appendChild(winCopy);
    linuxCmd.textContent = linuxText;
    linuxCmd.appendChild(linuxCopy);
    document.getElementById('resync-modal').classList.add('active');
}
function closeResyncModal() {
    document.getElementById('resync-modal').classList.remove('active');
}
function copyResyncCmd(os) {
    var el = document.getElementById('resync-cmd-' + (os === 'win' ? 'win' : 'linux'));
    var text = el.textContent.replace('COPY', '').trim();
    // Fallback for HTTP (navigator.clipboard requires HTTPS)
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    scToast('Copied to clipboard', 'success');
}

// Close modal on overlay click
document.addEventListener('click', function(e) {
    if (e.target.id === 'add-node-modal') closeAddNodeModal();
    if (e.target.id === 'resync-modal') closeResyncModal();
});

// Close on Escape
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') { closeAddNodeModal(); closeResyncModal(); closeDetail(); closeStarbaseDetail(); }
});

async function createNode() {
    var name = document.getElementById('new-node-name').value.trim();
    var btn = document.getElementById('btn-create-node');
    btn.disabled = true;
    btn.textContent = 'CREATING...';

    try {
        var resp = await fetch('/tools/starship/api/request-node', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({node_name: name || undefined})
        });
        var data = await resp.json();
        if (!data.success) {
            scToast(data.error || 'Failed to create node', 'error');
            btn.disabled = false;
            btn.textContent = 'CREATE NODE';
            return;
        }

        pendingConfig = data.config;

        // Show step 2
        document.getElementById('modal-step-1').style.display = 'none';
        document.getElementById('modal-step-2').style.display = '';
        document.getElementById('setup-node-name').textContent = data.node_name;
        document.getElementById('setup-config').textContent = JSON.stringify(data.config, null, 2);

        // Populate install commands
        var hubUrl = (data.config && data.config.hub_url) || 'https://archie.kytranempowerment.com';
        var token = data.setup_token || '';
        var winCmd = 'irm "' + hubUrl + '/starship/install?token=' + token + '" | iex';
        var linuxCmd = 'curl -fsSL "' + hubUrl + '/starship/install?token=' + token + '" | bash';

        var winEl = document.getElementById('install-cmd-win');
        var linuxEl = document.getElementById('install-cmd-linux');
        var winCopy = winEl.querySelector('.sc-copy-btn');
        var linuxCopy = linuxEl.querySelector('.sc-copy-btn');
        winEl.textContent = winCmd;
        winEl.appendChild(winCopy);
        linuxEl.textContent = linuxCmd;
        linuxEl.appendChild(linuxCopy);

        // Start polling for connection
        var statusEl = document.getElementById('node-connection-status');
        statusEl.innerHTML = '<span style="color: var(--sc-amber);">&#9679;</span> Waiting for node to connect...';
        pollNodeConnection(data.node_id, statusEl);

        scToast('Node "' + data.node_name + '" registered', 'success');
    } catch (e) {
        scToast('Request failed', 'error');
    }
    btn.disabled = false;
    btn.textContent = 'CREATE NODE';
}

function copyCode(btn) {
    var block = btn.parentElement;
    var text = block.textContent.replace('COPY', '').trim();
    navigator.clipboard.writeText(text).then(function() {
        btn.textContent = 'COPIED';
        setTimeout(function() { btn.textContent = 'COPY'; }, 1500);
    });
}

function copyConfig() {
    if (!pendingConfig) return;
    navigator.clipboard.writeText(JSON.stringify(pendingConfig, null, 2)).then(function() {
        scToast('Config copied to clipboard', 'success');
    });
}

// ── Install tab switcher ──
function switchInstallTab(os) {
    document.getElementById('install-tab-win').classList.toggle('active', os === 'win');
    document.getElementById('install-tab-linux').classList.toggle('active', os === 'linux');
    document.getElementById('install-panel-win').style.display = os === 'win' ? '' : 'none';
    document.getElementById('install-panel-linux').style.display = os === 'linux' ? '' : 'none';
}

function copyInstallCmd(os) {
    var el = document.getElementById('install-cmd-' + (os === 'win' ? 'win' : 'linux'));
    var text = el.textContent.replace('COPY', '').replace('COPIED', '').trim();
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    var btn = el.querySelector('.sc-copy-btn');
    if (btn) { btn.textContent = 'COPIED'; setTimeout(function() { btn.textContent = 'COPY'; }, 1500); }
    scToast('Copied to clipboard', 'success');
}

// ── Poll for node connection after creation ──
function pollNodeConnection(nodeId, statusEl) {
    if (nodeConnectionPoller) clearInterval(nodeConnectionPoller);
    nodeConnectionPoller = setInterval(async function() {
        try {
            var resp = await fetch('/tools/starship/api/nodes/' + encodeURIComponent(nodeId) + '/status');
            var data = await resp.json();
            if (data.status === 'online') {
                clearInterval(nodeConnectionPoller);
                nodeConnectionPoller = null;
                statusEl.innerHTML = '<span style="color: #4ade80;">&#10003; Node connected!</span>';
                setTimeout(function() { location.reload(); }, 2000);
            }
        } catch(e) {}
    }, 5000);
    // Stop polling after 5 minutes
    setTimeout(function() {
        if (nodeConnectionPoller) {
            clearInterval(nodeConnectionPoller);
            nodeConnectionPoller = null;
            statusEl.innerHTML = '<span style="color: rgba(255,255,255,0.4);">Polling timed out. Refresh the page to check status.</span>';
        }
    }, 300000);
}

function scToast(msg, type) {
    var el = document.createElement('div');
    el.className = 'sc-toast ' + (type || 'success');
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function() { el.remove(); }, 3000);
}

function switchTab(tab) {
    var modal = document.getElementById('sc-detail-overlay');
    modal.querySelectorAll('.sc-tab[data-tab]').forEach(function(t) { t.classList.remove('active'); });
    modal.querySelectorAll('.sc-panel').forEach(function(p) { p.classList.remove('active'); });
    var tabBtn = modal.querySelector('.sc-tab[data-tab="' + tab + '"]');
    if (tabBtn) tabBtn.classList.add('active');
    var panel = document.getElementById('panel-' + tab);
    if (panel) panel.classList.add('active');
    if (tab === 'ota' && selectedNodeDbId) {
        startSyncPolling();
    }
    if (tab === 'stations' && selectedNodeDbId) {
        loadNodeStations(selectedNodeDbId);
    }
}

function closeDetail() {
    document.getElementById('sc-detail-overlay').classList.remove('active');
    document.getElementById('sc-starbase-overlay').classList.remove('active');
    document.querySelectorAll('.sc-node-card').forEach(function(c) { c.classList.remove('selected'); });
    selectedNodeId = null;
}

async function selectNode(nodeId) {
    var isNewNode = (selectedNodeId !== nodeId);
    selectedNodeId = nodeId;

    // Close starbase modal if open
    document.getElementById('sc-starbase-overlay').classList.remove('active');

    // Highlight card
    document.querySelectorAll('.sc-node-card').forEach(function(c) { c.classList.remove('selected'); });
    var card = document.getElementById('card-' + nodeId);
    if (card) card.classList.add('selected');

    // Show node detail modal
    document.getElementById('sc-detail-overlay').classList.add('active');
    document.getElementById('detail-title').textContent = 'LOADING...';

    // Only reset to status tab when selecting a different node
    if (isNewNode) {
        switchTab('status');
    }

    try {
        var resp = await fetch('/tools/starship/api/nodes/' + encodeURIComponent(nodeId) + '/status');
        var data = await resp.json();
        if (!data.success) {
            scToast(data.error || 'Failed to load node', 'error');
            return;
        }
        nodeCache[nodeId] = data;
        selectedNodeDbId = data.node.db_id || null;
        window._lastNodeData = data;
        renderDetail(data);
        if (selectedNodeDbId) {
            loadRecommendations(selectedNodeDbId);
            loadSyncLog(selectedNodeDbId);
            populatePullModelDropdown();
            pollSyncStatus();
            startSyncPolling();
        }
    } catch (e) {
        scToast('Failed to load node data', 'error');
    }
}

function renderDetail(data) {
    var n = data.node;
    var hw = data.hardware;

    // Header
    document.getElementById('detail-title').textContent = n.node_name;
    var dot = document.getElementById('detail-dot');
    dot.className = 'sc-node-dot ' + (n.status === 'online' ? 'online' : 'offline');

    // Status tab
    document.getElementById('d-status').textContent = (n.status || 'unknown').toUpperCase();
    document.getElementById('d-mode').textContent = (n.deployment_mode || '—').toUpperCase();
    document.getElementById('d-priority').textContent = n.bridge_priority || '—';
    document.getElementById('d-heartbeat').textContent = n.last_heartbeat ? new Date(n.last_heartbeat).toLocaleString() : 'Never';

    // Version
    var verEl = document.getElementById('d-version');
    verEl.textContent = '';
    if (data.version) {
        var badge = document.createElement('span');
        badge.className = 'sc-version-badge ' + (data.version.update_available ? 'outdated' : 'current');
        badge.textContent = 'v' + data.version.current;
        if (data.version.update_available) {
            badge.textContent += ' \u2192 v' + data.version.latest;
            badge.title = 'Click to push update to this node';
            badge.style.cursor = 'pointer';
            badge.addEventListener('click', function() {
                if (!confirm('Push update v' + data.version.latest + ' to this node?\n\nThe node will download and install the update on its next heartbeat (~30s).')) return;
                fetch('/tools/starship/api/nodes/' + encodeURIComponent(selectedNodeId) + '/request-update', {method:'POST',headers:{'Content-Type':'application/json'}})
                .then(function(r){return r.json()})
                .then(function(d){
                    if (d.success) {
                        scToast('Update queued — node will update on next heartbeat', 'success');
                        badge.textContent = 'v' + data.version.current + ' \u2192 UPDATING...';
                        badge.className = 'sc-version-badge outdated';
                    } else {
                        scToast('Failed: ' + (d.error || 'Unknown error'), 'error');
                    }
                });
            });
        }
        verEl.appendChild(badge);
    }

    // System Ops gauges (live metrics from heartbeat)
    var lm = data.live_metrics || {};
    renderOpsGauge('ops-cpu', 'ops-cpu-bar', lm.cpu_usage);
    renderOpsGauge('ops-ram', 'ops-ram-bar', lm.memory_usage);
    renderOpsGauge('ops-gpu', 'ops-gpu-bar', lm.gpu_usage);

    // Fleet Summary
    var ss = data.station_summary || {};
    var ms = data.model_summary || {};
    var allowedAgents = (data.agents || []).filter(function(a) { return a.allowed; }).length;
    document.getElementById('d-active-stations').textContent = (ss.active || 0) + ' / ' + (ss.total || 0);
    document.getElementById('d-models-avail').textContent = (ms.available || 0) + ' / ' + (ms.total || 0);
    document.getElementById('d-models-size').textContent = (ms.total_size_gb || 0) + ' GB';
    document.getElementById('d-agents-allowed').textContent = allowedAgents + ' / ' + (data.agents || []).length;

    // Populate inline settings
    var nameEl = document.getElementById('settings-name');
    if (nameEl) nameEl.value = n.node_name || '';
    var modeEl = document.getElementById('settings-mode');
    if (modeEl) modeEl.value = n.deployment_mode || 'starship';
    var prioEl = document.getElementById('settings-priority');
    if (prioEl) prioEl.value = n.bridge_priority || 0;

    // Crew tab — manifest-style cards (fetched separately)
    renderNodeManifest(selectedNodeDbId);
}

// ── Node STATIONS tab — group node agents by station ──
var _nodeStationsLoaded = {};
async function loadNodeStations(nodeDbId) {
    var grid = document.getElementById('d-node-stations-grid');
    if (!grid) return;
    if (_nodeStationsLoaded[nodeDbId]) return;
    grid.innerHTML = '<span class="sc-label">Loading stations...</span>';

    try {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeDbId + '/crew-manifest');
        var data = await resp.json();
        if (!data.success) { grid.innerHTML = '<span class="sc-label">Failed to load</span>'; return; }

        var crew = data.crew || [];
        _nodeStationsLoaded[nodeDbId] = true;

        // Group agents by station
        var stationMap = {};
        crew.forEach(function(a) {
            var codes = a.station_codes || [a.station || 'UNASSIGNED'];
            codes.forEach(function(code) {
                if (!stationMap[code]) stationMap[code] = { agents: [], color: '#00e5ff' };
                stationMap[code].agents.push(a);
                // Use station color from the agent's station_colors if available
                var idx = codes.indexOf(code);
                var colors = a.station_colors || [];
                if (colors[idx]) stationMap[code].color = colors[idx];
            });
        });

        // Also fetch bridge stations for names and colors of empty stations
        var stResp = await fetch('/tools/bridge/api/stations');
        var stData = await stResp.json();
        var stationNames = {};
        if (stData.success) {
            (stData.stations || []).forEach(function(s) {
                stationNames[s.code] = s.name || s.code;
                if (!stationMap[s.code]) return; // Only show stations this node has agents for
                if (s.color) stationMap[s.code].color = s.color;
            });
        }

        var stationCodes = Object.keys(stationMap).sort();
        if (!stationCodes.length) {
            grid.innerHTML = '<span class="sc-label">No stations — assign agents to stations first</span>';
            return;
        }

        grid.innerHTML = stationCodes.map(function(code) {
            var st = stationMap[code];
            var color = st.color;
            var agents = st.agents;
            var stName = stationNames[code] || code;

            var crewHtml = agents.map(function(a) {
                var displayName = a.full_name || a.name;
                var isActive = a.status === 'active';
                var dotColor = isActive ? 'var(--sc-green)' : 'rgba(255,255,255,0.3)';
                var llmClass = a.llm_status || 'barracked';
                var llmLabels = { loaded: 'LOADED', swap: 'SWAP', barracked: 'OFFLINE', cloud: 'CLOUD' };
                var llmLabel = llmLabels[llmClass] || llmClass.toUpperCase();
                var model = (a.model || '').replace(':latest', '');

                return '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;">' +
                    '<span style="width:6px;height:6px;border-radius:50%;background:' + dotColor + ';flex-shrink:0;"></span>' +
                    '<span style="color:rgba(255,255,255,0.8);font-size:0.8rem;flex:1;">' + escHtml(displayName) + '</span>' +
                    '<span class="crew-llm-badge ' + llmClass + '" style="font-size:0.5rem;">' + llmLabel + '</span>' +
                    '<span style="font-size:0.65rem;color:rgba(255,255,255,0.3);">' + escHtml(model) + '</span>' +
                '</div>';
            }).join('');

            return '<div style="background:rgba(0,0,0,0.3);border:1px solid ' + color + '33;border-radius:8px;overflow:hidden;">' +
                '<div style="display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid ' + color + '22;">' +
                    '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';"></span>' +
                    '<span style="font-family:Antonio,sans-serif;color:' + color + ';font-size:0.9rem;letter-spacing:2px;">' + escHtml(stName) + '</span>' +
                    '<span style="margin-left:auto;font-size:0.7rem;color:rgba(255,255,255,0.4);">' + agents.length + ' crew</span>' +
                '</div>' +
                '<div style="padding:10px 14px;">' + crewHtml + '</div>' +
            '</div>';
        }).join('');
    } catch (e) {
        grid.innerHTML = '<span class="sc-label">Failed to load stations</span>';
        console.error('Node stations load failed:', e);
    }
}

async function renderNodeManifest(nodeDbId) {
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeDbId + '/crew-manifest');
        var data = await resp.json();
        if (!data.success) return;

        var crew = data.crew || [];
        var grid = document.getElementById('d-agents-manifest');
        grid.textContent = '';

        var agSummary = document.getElementById('d-agent-summary');
        agSummary.textContent = '';
        var allowed = crew.filter(function(a) { return a.allowed; }).length;
        var modelReady = crew.filter(function(a) { return a.llm_status === 'loaded'; }).length;
        buildSummarySpan(agSummary, allowed, 'active');
        buildSummarySpan(agSummary, modelReady, 'models ready');
        buildSummarySpan(agSummary, crew.length, 'total crew');

        crew.forEach(function(agent) {
            grid.appendChild(_renderStarshipAgentCard(agent));
        });

        if (crew.length === 0) {
            var empty = document.createElement('span');
            empty.className = 'sc-label';
            empty.textContent = 'No agents assigned to this node.';
            grid.appendChild(empty);
        }
    } catch (e) {
        console.error('Manifest load failed:', e);
    }
}

function _renderStarshipAgentCard(agent) {
    var card = document.createElement('div');
    card.className = 'crew-agent-card';
    card.style.cursor = 'pointer';
    card.onclick = function(e) {
        // Don't trigger on button clicks
        if (e.target.tagName === 'BUTTON') return;
        openNodeAgentProfile(agent.agent_id);
    };
    card.setAttribute('data-station', agent.station);

    var colors = agent.station_colors || [];
    if (colors.length > 0) {
        card.style.borderLeftColor = colors[0];
    }

    // Top row: name + badges
    var top = document.createElement('div');
    top.className = 'crew-agent-top';

    var name = document.createElement('span');
    name.className = 'crew-agent-name';
    name.textContent = agent.full_name || agent.name;

    var badges = document.createElement('div');
    badges.className = 'crew-agent-badges';

    // Status badge
    var statusBadge = document.createElement('span');
    statusBadge.className = 'crew-status-badge ' + agent.status;
    statusBadge.textContent = agent.status.toUpperCase();
    badges.appendChild(statusBadge);

    // LLM readiness badge
    var llmBadge = document.createElement('span');
    if (agent.llm_status === 'loaded') {
        llmBadge.className = 'crew-llm-badge loaded';
        llmBadge.textContent = 'MODEL READY';
        llmBadge.title = 'Model available on this node';
    } else {
        llmBadge.className = 'crew-llm-badge barracked';
        llmBadge.textContent = 'MODEL OFFLINE';
        llmBadge.title = 'Model not available on this node';
    }
    badges.appendChild(llmBadge);

    // Sharing badge
    var shareBadge = document.createElement('span');
    shareBadge.className = 'crew-status-badge ' + (agent.allowed ? 'active' : 'idle');
    shareBadge.textContent = agent.allowed ? 'ENABLED' : 'DISABLED';
    badges.appendChild(shareBadge);

    top.appendChild(name);
    top.appendChild(badges);
    card.appendChild(top);

    // Callsign subtitle
    if (agent.full_name && agent.full_name !== agent.name) {
        var subtitle = document.createElement('div');
        subtitle.style.cssText = 'font-size: 0.6rem; color: rgba(255,255,255,0.35); margin-top: -2px;';
        subtitle.textContent = agent.name + (agent.title ? ' \u2014 ' + agent.title : '');
        card.appendChild(subtitle);
    }

    // Meta row: station + model
    var meta = document.createElement('div');
    meta.className = 'crew-agent-meta';

    var stationSpan = document.createElement('span');
    stationSpan.textContent = agent.station;
    if (colors.length > 0) stationSpan.style.color = colors[0];
    meta.appendChild(stationSpan);

    var modelSpan = document.createElement('span');
    modelSpan.textContent = (agent.model || '').replace(':latest', '');
    meta.appendChild(modelSpan);

    card.appendChild(meta);

    // Station tags
    if (agent.station_codes && agent.station_codes.length > 0) {
        var tagsRow = document.createElement('div');
        tagsRow.style.cssText = 'display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px;';
        agent.station_codes.forEach(function(sc, i) {
            var tag = document.createElement('span');
            tag.className = 'sc-agent-station-tag';
            tag.textContent = sc;
            var c = (agent.station_colors || [])[i];
            if (c) { tag.style.borderColor = c + '44'; tag.style.color = c; }
            tagsRow.appendChild(tag);
        });
        card.appendChild(tagsRow);
    }

    // Active job progress bar (if any)
    if (agent.current_job) {
        var jobRow = document.createElement('div');
        jobRow.className = 'crew-agent-job';
        var jobDesc = document.createElement('span');
        jobDesc.textContent = agent.current_job.description || 'Working...';
        jobDesc.style.cssText = 'max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
        var jobBar = document.createElement('div');
        jobBar.className = 'crew-job-bar';
        var jobFill = document.createElement('div');
        jobFill.className = 'crew-job-bar-fill';
        jobFill.style.width = Math.min(agent.current_job.progress_pct || 0, 100) + '%';
        jobBar.appendChild(jobFill);
        jobRow.appendChild(jobDesc);
        jobRow.appendChild(jobBar);
        card.appendChild(jobRow);
    }

    return card;
}

// ── Escape HTML helper ──
function escHtml(str) {
    if (!str) return '';
    var d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

// ── Recommendations ──
async function loadRecommendations(nodeDbId) {
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeDbId + '/recommendations');
        var data = await resp.json();
        if (data.success) {
            renderRecommendations(data);
        }
    } catch (e) {
        // silently fail
    }
}

function renderRecommendations(data) {
    var panel = document.getElementById('agent-recommendations');
    var container = document.getElementById('recommendation-cards');
    var sugBox = document.getElementById('station-suggestions');
    container.textContent = '';
    sugBox.textContent = '';

    var recs = data.recommendations || [];
    if (recs.length === 0) {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = '';

    recs.forEach(function(rec) {
        var card = document.createElement('div');
        card.style.cssText = 'background:rgba(167,139,250,0.06);border:1px solid rgba(167,139,250,0.15);border-radius:6px;padding:8px 10px;display:flex;align-items:center;gap:8px;min-width:200px;max-width:300px;';
        card.setAttribute('data-agent-id', rec.agent_id);

        // Avatar
        var avatar = document.createElement('div');
        var codeName = rec.name || '';
        avatar.style.cssText = 'width:28px;height:28px;border-radius:4px;background:rgba(167,139,250,0.15);color:#a78bfa;display:flex;align-items:center;justify-content:center;font-size:0.65rem;font-weight:bold;flex-shrink:0;';
        avatar.textContent = codeName.substring(0, 2).toUpperCase();
        card.appendChild(avatar);

        // Info column
        var info = document.createElement('div');
        info.style.cssText = 'flex:1;min-width:0;';
        var nameEl = document.createElement('div');
        nameEl.style.cssText = 'color:#a78bfa;font-size:0.75rem;font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        nameEl.textContent = rec.display_name || rec.name;
        info.appendChild(nameEl);
        var metaEl = document.createElement('div');
        metaEl.style.cssText = 'color:rgba(255,255,255,0.35);font-size:0.65rem;font-family:"IBM Plex Mono",monospace;';
        var score = rec.score || 0;
        metaEl.textContent = Math.round(score * 100) + '% match \u2022 ' + (rec.station_codes || []).join(', ');
        info.appendChild(metaEl);
        card.appendChild(info);

        container.appendChild(card);
    });

    // Station suggestions
    var suggestions = data.station_suggestions || [];
    if (suggestions.length > 0) {
        suggestions.forEach(function(s) {
            var tip = document.createElement('div');
            tip.style.cssText = 'color:rgba(255,255,255,0.35);font-size:0.75rem;font-family:"IBM Plex Mono",monospace;padding:4px 0;';
            tip.textContent = escHtml(s.station_code) + ' — ' + escHtml(s.reason);
            sugBox.appendChild(tip);
        });
    }
}


async function pushAgentConfig() {
    if (!selectedNodeDbId) return;
    var indicator = document.getElementById('sync-indicator') || document.getElementById('ops-sync-indicator');
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/push-config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: 'agent_config'})
        });
        var data = await resp.json();
        if (data.success) {
            indicator.textContent = 'Config pushed — ' + data.agent_count + ' agents synced (ID: ' + data.sync_id + ')';
            indicator.style.color = 'var(--sc-green)';
            scToast('Agent config pushed to node', 'success');
            loadSyncLog(selectedNodeDbId);
            setTimeout(pollSyncStatus, 2000);
        } else {
            indicator.textContent = 'Push failed: ' + escHtml(data.error || 'Unknown');
            indicator.style.color = 'var(--sc-red)';
            scToast(data.error || 'Push failed', 'error');
        }
    } catch (e) {
        indicator.textContent = 'Push failed — network error';
        indicator.style.color = 'var(--sc-red)';
        scToast('Failed to push config', 'error');
    }
}

// ── OTA Code Update + Sync Log ──
async function pushCodeUpdate() {
    if (!selectedNodeDbId) return;
    if (!confirm('Push a code update to this node? The node will download and install on its next heartbeat.')) return;
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/push-update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        var data = await resp.json();
        if (data.success) {
            scToast('Code update v' + escHtml(data.version) + ' pushed (sync ID: ' + data.sync_id + ')', 'success');
            loadSyncLog(selectedNodeDbId);
        } else {
            scToast(data.error || 'Failed to push update', 'error');
        }
    } catch (e) {
        scToast('Failed to push code update', 'error');
    }
}

async function loadSyncLog(nodeDbId) {
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeDbId + '/sync-log');
        var data = await resp.json();
        if (data.success) {
            renderSyncLog(data.logs || []);
        }
    } catch (e) {
        // silently fail
    }
}

function renderSyncLog(logs) {
    var tbody = document.getElementById('sync-log-body');
    tbody.textContent = '';
    if (logs.length === 0) {
        var row = document.createElement('tr');
        var td = document.createElement('td');
        td.colSpan = 3;
        td.textContent = 'No sync activity yet.';
        td.style.color = 'rgba(255,255,255,0.3)';
        row.appendChild(td);
        tbody.appendChild(row);
        return;
    }
    logs.forEach(function(log) {
        var row = document.createElement('tr');

        var typeTd = document.createElement('td');
        typeTd.textContent = log.sync_type || '—';
        typeTd.style.color = 'var(--sc-accent)';

        var statusTd = document.createElement('td');
        var statusClass = 'sync-status-sent';
        if (log.status === 'acknowledged') statusClass = 'sync-status-acked';
        else if (log.status === 'error') statusClass = 'sync-status-failed';
        statusTd.className = statusClass;
        statusTd.textContent = (log.status || '—').toUpperCase();

        var timeTd = document.createElement('td');
        timeTd.textContent = log.sent_at ? new Date(log.sent_at).toLocaleString() : '—';

        row.appendChild(typeTd);
        row.appendChild(statusTd);
        row.appendChild(timeTd);
        tbody.appendChild(row);
    });
}

// ── Save Node Settings (inline on STATUS tab) ──
async function saveNodeSettings() {
    if (!selectedNodeDbId) return;
    var name = document.getElementById('settings-name').value.trim();
    var mode = document.getElementById('settings-mode').value;
    var priority = parseInt(document.getElementById('settings-priority').value) || 0;
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/settings', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({node_name: name, deployment_mode: mode, bridge_priority: priority})
        });
        var data = await resp.json();
        if (data.success) {
            scToast('Settings saved', 'success');
            // Update card name + detail title
            document.getElementById('detail-title').textContent = name;
            var card = document.getElementById('card-' + selectedNodeId);
            if (card) {
                var nameEl = card.querySelector('.sc-node-name');
                if (nameEl) nameEl.textContent = name;
            }
        }
        else scToast(data.error || 'Save failed', 'error');
    } catch(e) { scToast('Network error', 'error'); }
}

// Auto-refresh fleet data every 30s
async function refreshFleet() {
    try {
        var resp = await fetch('/tools/starship/api/nodes');
        var data = await resp.json();
        if (!data.success) return;
        data.nodes.forEach(function(n) {
            var card = document.getElementById('card-' + n.node_id);
            if (!card) return;
            var dot = card.querySelector('.sc-node-dot');
            if (dot) {
                dot.className = 'sc-node-dot ' + (n.status === 'online' && n.is_active ? 'online' : n.status === 'offline' ? 'offline' : 'pending');
            }
        });
        // Refresh selected node detail
        if (selectedNodeId) selectNode(selectedNodeId);
    } catch (e) { /* silent */ }
}
setInterval(refreshFleet, 30000);


function pullModelToNode(modelName, btn) {
    if (!selectedNodeDbId) return;
    btn.disabled = true;
    btn.textContent = 'PULLING...';
    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/pull-model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model_name: modelName})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            btn.textContent = 'QUEUED';
            btn.style.color = '#4caf50';
        } else {
            btn.textContent = 'FAILED';
            btn.style.color = '#f44336';
            setTimeout(function() { btn.textContent = 'PULL'; btn.disabled = false; btn.style.color = ''; }, 3000);
        }
    })
    .catch(function() {
        btn.textContent = 'FAILED';
        btn.style.color = '#f44336';
        setTimeout(function() { btn.textContent = 'PULL'; btn.disabled = false; btn.style.color = ''; }, 3000);
    });
}

// ============================================================================
// AGENT PROFILE MODAL (shared by Starbase + Node agents)
// ============================================================================
var _nodeProfileAgentId = null;

function openHubAgentProfile(hubAgentId) {
    _nodeProfileAgentId = hubAgentId;
    var modal = document.getElementById('node-agent-profile-modal');
    var body = document.getElementById('node-profile-body');
    var title = document.getElementById('node-profile-title');
    modal.classList.add('active');
    body.innerHTML = '<span class="sc-label">Loading profile...</span>';
    title.textContent = 'AGENT PROFILE';

    fetch('/tools/bridge/api/agents/' + parseInt(hubAgentId) + '/profile')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                body.textContent = data.error || 'Failed to load profile';
                return;
            }
            _renderNodeAgentProfile(data, body, title);
        }).catch(function(err) {
            body.textContent = 'Failed to load profile: ' + err;
        });
}

function openNodeAgentProfile(agentId) {
    _nodeProfileAgentId = agentId;
    var modal = document.getElementById('node-agent-profile-modal');
    var body = document.getElementById('node-profile-body');
    var title = document.getElementById('node-profile-title');
    modal.classList.add('active');
    body.innerHTML = '<span class="sc-label">Loading profile...</span>';
    title.textContent = 'AGENT PROFILE';

    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/agents/' + agentId + '/profile')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                body.textContent = data.error || 'Failed to load profile';
                return;
            }
            _renderNodeAgentProfile(data, body, title);
        }).catch(function(err) {
            body.textContent = 'Failed to load profile: ' + err;
        });
}

function closeNodeAgentProfile() {
    document.getElementById('node-agent-profile-modal').classList.remove('active');
}

function _renderNodeAgentProfile(data, body, title) {
    var a = data.agent;
    var esc = function(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
    var fullName = ((a.first_name || '') + ' ' + (a.last_name || '')).trim() || a.name;
    title.textContent = fullName;

    var html = '';

    // Agent header — portrait with fallback (matches Bridge)
    var stColor = a.station_color || '#00e5ff';
    var portraitSrc = (data.portraits && data.portraits.portrait) || '';
    var initial = (a.first_name || a.name || '?')[0].toUpperCase();
    html += '<div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.1);">';
    if (portraitSrc) {
        html += '<img style="width:48px;height:48px;border-radius:50%;object-fit:cover;border:2px solid ' + esc(stColor) + ';" src="' + esc(portraitSrc) + '" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';">';
    }
    html += '<div style="width:48px;height:48px;border-radius:50%;background:' + esc(stColor) + ';display:flex;align-items:center;justify-content:center;font-size:1.2rem;font-weight:700;color:#000;' + (portraitSrc ? 'display:none;' : '') + '">';
    html += esc(initial);
    html += '</div>';
    html += '<div style="flex:1;">';
    html += '<div style="font-size:1rem;font-weight:600;color:#fff;">' + esc(fullName) + '</div>';
    html += '<div style="font-size:0.75rem;color:rgba(255,255,255,0.5);">' + esc(a.name) + (a.title ? ' — ' + esc(a.title) : '') + '</div>';
    html += '<div style="font-size:0.7rem;color:rgba(255,255,255,0.3);">';
    html += esc(a.department || '') + ' • ' + esc(a.model || '') + ' • ' + esc(a.worker_type || '') + (a.pronouns ? ' • ' + esc(a.pronouns) : '');
    html += '</div></div>';
    html += '<span class="crew-status-badge ' + esc(a.status) + '" style="font-size:0.7rem;">' + esc(a.status || 'active').toUpperCase() + '</span>';
    html += '</div>';

    // Bio
    if (a.bio) {
        html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:' + esc(stColor) + ';">Bio</span></div>';
        html += '<div style="font-size:0.75rem;color:rgba(255,255,255,0.6);line-height:1.4;">' + esc(a.bio) + '</div></div>';
    }

    // Station assignment
    if (a.station_code) {
        html += '<div style="display:flex;gap:6px;align-items:center;margin-bottom:10px;font-size:0.75rem;">';
        html += '<span style="color:' + esc(stColor) + ';font-weight:600;">■ ' + esc(a.station_name || a.station_code) + '</span>';
        html += '</div>';
    }

    // Two-column: Performance + Wellness
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">';

    // Performance
    var p = data.performance_24h || {};
    html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#00ff41;">Performance (24h)</span></div>';
    html += '<div class="profile-row"><span class="label">Tasks</span><span class="value" style="color:#00e5ff;">' + (p.tasks || 0) + '</span></div>';
    html += '<div class="profile-row"><span class="label">Completed</span><span class="value" style="color:#00ff41;">' + (p.completed || 0) + '</span></div>';
    html += '<div class="profile-row"><span class="label">Failed</span><span class="value" style="color:#ff4444;">' + (p.failed || 0) + '</span></div>';
    html += '<div class="profile-row"><span class="label">Avg Duration</span><span class="value">' + Math.round(p.avg_duration_ms || 0) + 'ms</span></div>';
    html += '</div>';

    // Wellness
    var em = data.emotional_state;
    html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#8b5cf6;">Wellness</span></div>';
    if (em) {
        var moodColor = (em.stress_level || 0) <= 0.4 ? '#00ff41' : (em.stress_level || 0) <= 0.7 ? '#ffaa00' : '#ff4444';
        html += '<div class="profile-row"><span class="label">Mood</span><span class="value" style="text-transform:capitalize;">' + esc(em.current_mood || 'neutral') + '</span></div>';
        html += '<div class="profile-row"><span class="label">Stress</span><span class="value" style="color:' + moodColor + ';">' + Math.round((em.stress_level || 0) * 100) + '%</span></div>';
        html += '<div class="profile-row"><span class="label">Energy</span><span class="value">' + Math.round((em.energy_level || 0) * 100) + '%</span></div>';
        html += '<div class="profile-row"><span class="label">Intensity</span><span class="value">' + Math.round((em.mood_intensity || 0) * 100) + '%</span></div>';
    } else {
        html += '<span style="font-size:0.75rem;color:rgba(255,255,255,0.3);">No wellness data</span>';
    }
    html += '</div>';
    html += '</div>';

    // Identity traits
    if (data.identity && data.identity.length > 0) {
        html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#e879f9;">Identity Traits</span></div>';
        data.identity.forEach(function(t) {
            html += '<div class="profile-row"><span class="label" style="text-transform:capitalize;">' + esc(t.identity_key) + '</span><span class="value">' + esc(t.identity_value) + '</span></div>';
        });
        html += '</div>';
    }

    // Voice DNA + Emotional History side by side
    var hasVoice = data.voice;
    var hasEmHist = data.emotional_history && data.emotional_history.length > 0;
    if (hasVoice || hasEmHist) {
        var cols = (hasVoice && hasEmHist) ? '1fr 1fr' : '1fr';
        html += '<div style="display:grid;grid-template-columns:' + cols + ';gap:10px;margin-bottom:10px;">';
        if (hasVoice) {
            var v = data.voice;
            html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#06b6d4;">Voice DNA</span></div>';
            if (v.engine) html += '<div class="profile-row"><span class="label">Engine</span><span class="value">' + esc(v.engine) + '</span></div>';
            if (v.language) html += '<div class="profile-row"><span class="label">Language</span><span class="value">' + esc(v.language) + '</span></div>';
            if (v.profile_name) html += '<div class="profile-row"><span class="label">Profile</span><span class="value">' + esc(v.profile_name) + '</span></div>';
            html += '</div>';
        }
        if (hasEmHist) {
            html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#8b5cf6;">Emotional History</span></div>';
            html += '<div style="max-height:140px;overflow-y:auto;">';
            data.emotional_history.forEach(function(e) {
                var sColor = (e.stress_level || 0) <= 0.4 ? '#00ff41' : (e.stress_level || 0) <= 0.7 ? '#ffaa00' : '#ff4444';
                html += '<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;">';
                html += '<span style="text-transform:capitalize;color:rgba(255,255,255,0.6);">' + esc(e.current_mood || 'neutral') + '</span>';
                html += '<span style="color:' + sColor + ';font-size:0.65rem;">stress ' + Math.round((e.stress_level || 0) * 100) + '%</span>';
                html += '</div>';
            });
            html += '</div></div>';
        }
        html += '</div>';
    }

    // Rest Cycles
    if (data.rest_cycles && data.rest_cycles.length > 0) {
        html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#a78bfa;">Rest Cycles</span></div>';
        data.rest_cycles.forEach(function(rc) {
            html += '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;">';
            html += '<span style="color:rgba(255,255,255,0.6);">' + esc(rc.rest_type || 'break') + '</span>';
            html += '<span style="color:rgba(255,255,255,0.35);">' + esc(rc.reason || '') + '</span>';
            html += '</div>';
        });
        html += '</div>';
    }

    // Skills
    html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#ffaa00;">Skills</span></div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px;">';
    if (data.skills && data.skills.length > 0) {
        data.skills.forEach(function(s) {
            var level = parseInt(s.proficiency_level) || 1;
            var dots = '';
            for (var i = 0; i < 5; i++) dots += i < level ? '●' : '○';
            html += '<span style="display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;font-size:0.7rem;color:rgba(255,255,255,0.7);">';
            html += esc(s.skill_name) + ' <span style="color:#ffaa00;font-size:0.6rem;">' + dots + '</span>';
            html += '</span>';
        });
    } else {
        html += '<span style="font-size:0.7rem;color:rgba(255,255,255,0.3);">No skills recorded</span>';
    }
    html += '</div></div>';

    // Memories
    if (data.memories && data.memories.length > 0) {
        html += '<div class="profile-card"><div class="profile-card-header"><span style="border-color:#00e5ff;">Memory Highlights</span></div>';
        data.memories.forEach(function(m) {
            html += '<div style="padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;">';
            html += '<span style="color:rgba(255,255,255,0.3);font-size:0.65rem;">' + esc(m.memory_type || '') + '</span> ';
            html += '<span style="color:rgba(255,255,255,0.6);">' + esc((m.content || '').substring(0, 120)) + '</span>';
            html += '</div>';
        });
        html += '</div>';
    }

    body.innerHTML = html;
}

// ── Populate Pull Model Dropdown (OTA tab) ──
async function populatePullModelDropdown() {
    try {
        var resp = await fetch('/tools/starship/api/model-catalog');
        var data = await resp.json();
        if (!data.success) return;
        var sel = document.getElementById('pull-model-select');
        while (sel.firstChild) sel.removeChild(sel.firstChild);
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = 'Select model...';
        sel.appendChild(defaultOpt);
        data.models.forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.name || m.model_name;
            opt.textContent = (m.name || m.model_name) + ' (' + (m.size_gb || '?') + ' GB)';
            sel.appendChild(opt);
        });
    } catch(e) { console.warn('Model catalog load failed:', e); }
}

// ── Starbase Stats (Hub card + detail panel) ──
var _starbaseData = null;

async function loadStarbaseStats() {
    try {
        var resp = await fetch('/tools/bridge/api/bridge/crew/manifest');
        var data = await resp.json();
        if (!data.success) return;
        _starbaseData = data;

        var crew = data.crew || [];
        var activeJobs = crew.filter(function(a) { return a.current_job; }).length;
        var cap = data.capacity || {};

        // Card stats — hardware summary (guard: old starbase card may be removed)
        _setLive(document.getElementById('sb-cores'), '20', false);
        _setLive(document.getElementById('sb-ram'), cap.ram ? cap.ram.total_gb : '128', !!cap.ram);
        _setLive(document.getElementById('sb-vram'), cap.gpu ? cap.gpu.vram_total_gb : '8', !!cap.gpu);

        // Detail panel stats (if open)
        _populateStarbaseDetail(crew, activeJobs, cap);
    } catch(e) {
        console.warn('Starbase stats load failed:', e);
    }
}

function _populateStarbaseDetail(crew, activeJobs, cap) {
    var el = function(id) { return document.getElementById(id); };
    if (!el('sbd-agents')) return;

    // Fleet overview — always live from manifest
    _setLive(el('sbd-agents'), crew.length, true);
    _setLive(el('sbd-jobs'), activeJobs, true);
    _setLive(el('sbd-models'), cap.models_loaded || '--', !!cap.models_loaded);

    // Hardware — glow if from real capacity data, static if fallback
    _setLive(el('sbd-cpu'), 'Xeon E5-2658 v2 (10c/20t)', false);
    if (cap.ram) {
        _setLive(el('sbd-ram'), cap.ram.total_gb + ' GB', true);
        _setLive(el('sbd-ram-avail'), (cap.ram.available_gb || '--') + ' GB', !!cap.ram.available_gb);
    } else {
        _setLive(el('sbd-ram'), '128 GB', false);
        _setLive(el('sbd-ram-avail'), '-- GB', false);
    }
    // GPU — nvidia-smi may not be in Docker, fall back to known hardware
    var gpuName = cap.gpu ? cap.gpu.name : 'Quadro M4000';
    var gpuVram = cap.gpu ? cap.gpu.vram_total_gb : 8.0;
    _setLive(el('sbd-gpu'), gpuName, !!cap.gpu);
    _setLive(el('sbd-vram'), gpuVram + ' GB', !!cap.gpu);
    _setLive(el('sbd-models-ram'), (cap.models_ram_gb || '--') + ' GB', !!cap.models_ram_gb);

    // RAM budget (ADR-078: 80% LLM, 20% reserve)
    var totalRam = cap.ram ? cap.ram.total_gb : 128;
    var llmBudget = Math.round(totalRam * 0.8);
    var agentBudget = Math.round(llmBudget * 0.9);
    var swapBuffer = Math.round(llmBudget * 0.1);
    var reserve = Math.round(totalRam * 0.2);
    el('sbd-llm-budget').textContent = llmBudget + ' GB';
    el('sbd-agent-budget').textContent = agentBudget + ' GB';
    el('sbd-swap-buffer').textContent = swapBuffer + ' GB';
    el('sbd-reserve').textContent = reserve + ' GB';
    var availGb = cap.ram ? cap.ram.available_gb : 0;
    if (availGb > reserve) {
        el('sbd-ram-status').textContent = 'NOMINAL';
        el('sbd-ram-status').style.color = 'var(--sc-green)';
    } else {
        el('sbd-ram-status').textContent = 'LOW';
        el('sbd-ram-status').style.color = 'var(--sc-amber)';
    }

    // GPU model badges (cap.gpu_models = [{name, size_gb, vram_gb}, ...])
    var gpuDiv = el('sbd-gpu-models');
    var gpuList = cap.gpu_models || (cap.gpu ? cap.gpu.models : []) || [];
    if (gpuDiv) {
        gpuDiv.innerHTML = gpuList.length ? gpuList.map(function(m) {
            var label = (m.name || m) + (m.vram_gb ? ' (' + m.vram_gb + 'GB)' : '');
            return '<span style="padding:3px 10px;border-radius:4px;font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;background:rgba(0,229,255,0.08);border:1px solid rgba(0,229,255,0.2);color:var(--sc-accent);">' + label + '</span>';
        }).join('') : '<span class="sc-label">None loaded</span>';
    }

    // CPU model badges (cap.cpu_models = [{name, size_gb}, ...])
    var cpuDiv = el('sbd-cpu-models');
    var cpuList = cap.cpu_models || [];
    if (cpuDiv) {
        cpuDiv.innerHTML = cpuList.length ? cpuList.map(function(m) {
            var label = (m.name || m) + (m.size_gb ? ' (' + m.size_gb + 'GB)' : '');
            return '<span style="padding:3px 10px;border-radius:4px;font-family:\'IBM Plex Mono\',monospace;font-size:0.75rem;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.7);">' + label + '</span>';
        }).join('') : '<span class="sc-label">None loaded</span>';
    }
}

function openStarbaseDetail() {
    // Close any open node modal
    document.getElementById('sc-detail-overlay').classList.remove('active');
    // Deselect node cards
    document.querySelectorAll('.sc-node-card.selected').forEach(function(c) { c.classList.remove('selected'); });
    // Select starbase card
    var _sbCard = document.getElementById('starbase-card') || document.getElementById('starbase-hero');
    if (_sbCard) _sbCard.classList.add('selected');
    // Show starbase modal
    document.getElementById('sc-starbase-overlay').classList.add('active');
    // Reset stations cache so next tab click re-fetches
    _sbStationsLoaded = false;
    // Populate from cached data or re-fetch
    if (_starbaseData) {
        var crew = _starbaseData.crew || [];
        var activeJobs = crew.filter(function(a) { return a.current_job; }).length;
        _populateStarbaseDetail(crew, activeJobs, _starbaseData.capacity || {});
    } else {
        loadStarbaseStats();
    }
}

function closeStarbaseDetail() {
    document.getElementById('sc-starbase-overlay').classList.remove('active');
    var _sbCard2 = document.getElementById('starbase-card') || document.getElementById('starbase-hero');
    if (_sbCard2) _sbCard2.classList.remove('selected');
}

// ── Starbase tab switching ──
function switchSbTab(tabId) {
    document.querySelectorAll('#sc-starbase-overlay .sc-tab').forEach(function(t) {
        t.classList.toggle('active', t.getAttribute('data-sbtab') === tabId);
    });
    document.querySelectorAll('#sc-starbase-overlay .sc-panel').forEach(function(p) {
        p.classList.toggle('active', p.id === 'panel-' + tabId);
    });
    if (tabId === 'sb-stations') loadStarbaseStations();
    if (tabId === 'sb-agents') renderStarbaseCrew();
}

// ── Stations tab — use shared StationOps component ──
var _sbStationsLoaded = false;
var _sbStationOps = {};
var _sbStationsData = null;

var _stationConfigs = [
    {code: 'COMMAND', name: 'COMMAND'},
    {code: 'ANALYTICS', name: 'ANALYTICS'},
    {code: 'CREATIVE', name: 'CREATIVE'},
    {code: 'ENGINEERING', name: 'ENGINEERING'},
    {code: 'COMMUNICATIONS', name: 'COMMUNICATIONS'},
    {code: 'RESEARCH', name: 'RESEARCH'},
    {code: 'SECURITY', name: 'SECURITY'},
    {code: 'LOGISTICS', name: 'LOGISTICS'},
    {code: 'DIPLOMATIC', name: 'DIPLOMATIC'},
    {code: 'OPERATIONS', name: 'OPERATIONS'}
];

var _sbStationPollInterval = null;

function loadStarbaseStations() {
    if (_sbStationsLoaded) return;
    _sbStationsLoaded = true;

    // Create StationOps instances for all 10 stations
    _stationConfigs.forEach(function(cfg) {
        _sbStationOps[cfg.code] = new StationOps({
            stationCode: cfg.code,
            moduleSource: 'starship',
            agentsElId: 'sb-stn-' + cfg.code + '-agents',
            jobsElId: 'sb-stn-' + cfg.code + '-jobs',
            commandsElId: 'sb-stn-' + cfg.code + '-commands',
            statusElId: 'sb-stn-' + cfg.code + '-status',
            commands: []
        });
    });

    // Fetch running jobs from Bridge and render all stations with live data
    _refreshStarbaseStations();

    // Poll every 10 seconds to keep stations alive
    _sbStationPollInterval = setInterval(_refreshStarbaseStations, 10000);
}

function _refreshStarbaseStations() {
    fetch('/tools/bridge/api/bridge/jobs?status=running')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var allJobs = (data.success && data.jobs) ? data.jobs : [];
            Object.keys(_sbStationOps).forEach(function(code) {
                _sbStationOps[code].render(allJobs);
            });
        })
        .catch(function() {
            // Still render agents even if jobs fetch fails
            Object.keys(_sbStationOps).forEach(function(code) {
                _sbStationOps[code].render([]);
            });
        });
}

function executeStationCommand(cmdId) {
    var prompt = window.prompt('Enter task details (or leave blank for default):');
    if (prompt === null) return;
    fetch('/tools/starship/api/station-commands/execute', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({command_id: parseInt(cmdId), prompt: prompt}),
    }).then(function(r) { return r.json(); }).then(function(result) {
        if (result.result) {
            showToast('Command dispatched to ' + result.station, 'success');
        } else {
            showToast('Command failed: ' + (result.error || 'unknown'), 'error');
        }
    }).catch(function(e) { showToast('Command failed: ' + e, 'error'); });
}

// ── Station color map (populated by loadStarbaseStations or inline) ──
var _stationColorMap = {
    COMMAND: '#00e5ff', ANALYTICS: '#8b5cf6', CREATIVE: '#f472b6',
    ENGINEERING: '#fbbf24', COMMUNICATIONS: '#22d3ee', RESEARCH: '#10b981',
    SECURITY: '#ef4444', LOGISTICS: '#f97316', DIPLOMATIC: '#818cf8',
    OPERATIONS: '#a3e635'
};

// ── Agents tab — render active crew manifest ──
function renderStarbaseCrew() {
    var grid = document.getElementById('sb-crew-manifest');
    if (!grid) return;
    var data = _starbaseData;
    if (!data) { grid.innerHTML = '<span class="sc-label">Loading...</span>'; loadStarbaseStats(); return; }
    var crew = data.crew || [];
    if (!crew.length) { grid.innerHTML = '<span class="sc-label">No agents in manifest</span>'; return; }

    // Update station color map from stations data if available
    if (_sbStationsData) {
        _sbStationsData.forEach(function(s) { if (s.color) _stationColorMap[s.code] = s.color; });
    }

    grid.textContent = '';
    crew.forEach(function(a) {
        var card = document.createElement('div');
        card.className = 'crew-agent-card';
        card.style.cursor = 'pointer';
        var agentId = a.agent_id || a.id;
        if (agentId) {
            card.onclick = (function(id) { return function() { openHubAgentProfile(id); }; })(agentId);
        }
        var stColor = _stationColorMap[a.station] || '#00e5ff';
        card.style.borderLeftColor = stColor;

        // Top row: name + badges
        var top = document.createElement('div');
        top.className = 'crew-agent-top';

        var nameEl = document.createElement('span');
        nameEl.className = 'crew-agent-name';
        nameEl.textContent = a.full_name || a.display_name || a.name || 'Unknown';
        top.appendChild(nameEl);

        var badges = document.createElement('div');
        badges.className = 'crew-agent-badges';

        // Status badge (working/idle/resting)
        var statusBadge = document.createElement('span');
        statusBadge.className = 'crew-status-badge ' + (a.status || 'idle');
        statusBadge.textContent = (a.status || 'idle').toUpperCase();
        badges.appendChild(statusBadge);

        // Shift state badge
        var shift = a.shift_state || 'active';
        if (shift !== 'active' && shift !== a.status) {
            var shiftBadge = document.createElement('span');
            shiftBadge.className = 'crew-status-badge ' + shift;
            shiftBadge.textContent = shift.replace('_', ' ').toUpperCase();
            badges.appendChild(shiftBadge);
        }

        // LLM readiness badge
        var llmBadge = document.createElement('span');
        var llmStatus = a.llm_status || 'barracked';
        llmBadge.className = 'crew-llm-badge ' + llmStatus;
        var llmLabels = { loaded: 'LOADED', swap: 'SWAP', barracked: 'OFFLINE', cloud: 'CLOUD' };
        llmBadge.textContent = llmLabels[llmStatus] || llmStatus.toUpperCase();
        if (a.llm_size_gb) llmBadge.title = a.llm_size_gb + ' GB';
        badges.appendChild(llmBadge);

        // Hardware badge
        if (a.hardware) {
            var hwBadge = document.createElement('span');
            hwBadge.className = 'crew-status-badge ' + (a.hardware === 'GPU' ? 'active' : 'idle');
            hwBadge.textContent = a.hardware;
            badges.appendChild(hwBadge);
        }

        top.appendChild(badges);
        card.appendChild(top);

        // Callsign subtitle
        if (a.full_name && a.full_name !== a.name) {
            var sub = document.createElement('div');
            sub.style.cssText = 'font-size:0.6rem;color:rgba(255,255,255,0.35);margin-top:-2px;';
            sub.textContent = a.name + (a.title ? ' \u2014 ' + a.title : '');
            card.appendChild(sub);
        }

        // Meta row: station + model
        var meta = document.createElement('div');
        meta.className = 'crew-agent-meta';
        var stSpan = document.createElement('span');
        stSpan.textContent = a.station || '--';
        stSpan.style.color = stColor;
        meta.appendChild(stSpan);
        var mdSpan = document.createElement('span');
        mdSpan.textContent = (a.model || '').replace(':latest', '');
        meta.appendChild(mdSpan);
        // Workload risk
        var wl = a.workload || {};
        if (wl.risk_level) {
            var riskSpan = document.createElement('span');
            var riskColors = { healthy: '#4ade80', elevated: '#fbbf24', critical: '#ef4444', overloaded: '#ef4444' };
            riskSpan.style.color = riskColors[wl.risk_level] || 'rgba(255,255,255,0.4)';
            riskSpan.textContent = wl.risk_level.toUpperCase();
            meta.appendChild(riskSpan);
        }
        card.appendChild(meta);

        // Station tag
        if (a.station) {
            var tagRow = document.createElement('div');
            tagRow.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;';
            var tag = document.createElement('span');
            tag.className = 'sc-agent-station-tag';
            tag.textContent = a.station;
            tag.style.borderColor = stColor + '44';
            tag.style.color = stColor;
            tagRow.appendChild(tag);
            card.appendChild(tagRow);
        }

        // Active job with progress bar
        if (a.current_job) {
            var jobRow = document.createElement('div');
            jobRow.className = 'crew-agent-job';
            var jobDesc = document.createElement('span');
            jobDesc.textContent = a.current_job.description || 'Working...';
            jobDesc.style.cssText = 'max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
            var jobBar = document.createElement('div');
            jobBar.className = 'crew-job-bar';
            var jobFill = document.createElement('div');
            jobFill.className = 'crew-job-bar-fill';
            jobFill.style.width = Math.min(a.current_job.progress_pct || 0, 100) + '%';
            jobBar.appendChild(jobFill);
            jobRow.appendChild(jobDesc);
            jobRow.appendChild(jobBar);
            card.appendChild(jobRow);
        }

        grid.appendChild(card);
    });
}

function _escSb(str) {
    if (!str) return '';
    var d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

// Load starbase stats + docked fleet on page load + interval
loadStarbaseStats();
loadDockedFleetStats();
setInterval(loadStarbaseStats, 30000);
setInterval(loadDockedFleetStats, 30000);

// Load hero stats on page load + interval
loadHeroStats();
setInterval(loadHeroStats, 30000);

// ── Sync Status Polling ──
var _syncPollTimer = null;

function pollSyncStatus() {
    if (!selectedNodeDbId) return;
    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/sync-status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var dot = document.getElementById('sync-dot');
            var indicator = document.getElementById('sync-indicator');
            if (!dot || !indicator) return;

            if (data.pending_count === 0) {
                dot.style.background = '#00ff41';
                indicator.style.color = 'rgba(0,255,65,0.7)';
                indicator.textContent = 'All synced \u2014 v' + (data.config_version || 1);
            } else {
                dot.style.background = '#ffaa00';
                indicator.style.color = 'rgba(255,170,0,0.8)';
                indicator.textContent = data.pending_count + ' change' + (data.pending_count > 1 ? 's' : '') + ' pending';
            }
        }).catch(function() {
            // Silently ignore poll failures
        });
}

function startSyncPolling() {
    if (_syncPollTimer) clearInterval(_syncPollTimer);
    pollSyncStatus();
    _syncPollTimer = setInterval(pollSyncStatus, 30000);
}
