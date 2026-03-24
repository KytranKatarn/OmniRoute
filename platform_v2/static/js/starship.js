/* Starship Command — Fleet management JS */
var selectedNodeId = null;
var selectedNodeDbId = null;
var nodeCache = {};
var pendingConfig = null;
var nodeConnectionPoller = null;
var _opsSelectedNodeDbId = null;

// ══════════════════════════════════════════════════════════════
// LCARS CONFIRM / ALERT — replaces native confirm() and alert()
// ══════════════════════════════════════════════════════════════

/**
 * LCARS-styled confirmation dialog — replaces native confirm()/alert()
 * @param {string} message - The message to display
 * @param {Object} opts - Options
 * @param {string} opts.title - Modal title (default: 'CONFIRM')
 * @param {string} opts.confirmText - Confirm button text (default: 'CONFIRM')
 * @param {string} opts.cancelText - Cancel button text (default: 'CANCEL')
 * @param {string} opts.confirmColor - Confirm button color (default: '#00e5ff')
 * @param {boolean} opts.alert - If true, only show OK button (default: false)
 * @returns {Promise<boolean>}
 */
function lcarsConfirm(message, opts) {
    opts = opts || {};
    var title = opts.title || 'CONFIRM';
    var confirmText = opts.confirmText || 'CONFIRM';
    var cancelText = opts.cancelText || 'CANCEL';
    var confirmColor = opts.confirmColor || '#00e5ff';
    var isAlert = opts.alert || false;

    return new Promise(function(resolve) {
        var overlay = document.createElement('div');
        overlay.className = 'bm-overlay active';
        overlay.style.zIndex = '10000';

        var shell = document.createElement('div');
        shell.style.cssText = 'max-width:450px;width:90%;margin:15vh auto 0;background:#0d0d1a;border:1px solid ' + confirmColor + '44;border-radius:8px;box-shadow:0 0 30px rgba(0,0,0,0.6),0 0 15px ' + confirmColor + '22;';

        var content = document.createElement('div');
        content.style.cssText = 'padding:28px;text-align:center;';

        var titleEl = document.createElement('h3');
        titleEl.style.cssText = 'color:' + confirmColor + ';font-family:Orbitron,monospace;font-size:16px;margin:0 0 16px;text-align:center;';
        titleEl.textContent = title;
        content.appendChild(titleEl);

        var msgEl = document.createElement('p');
        msgEl.style.cssText = 'color:#e0e0e0;font-size:14px;line-height:1.6;margin:0 0 28px;white-space:pre-wrap;text-align:center;';
        msgEl.textContent = message;
        content.appendChild(msgEl);

        var btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;justify-content:center;gap:12px;';

        function closeModal(result) {
            document.removeEventListener('keydown', onKey);
            overlay.remove();
            resolve(result);
        }

        if (!isAlert) {
            var cancelBtn = document.createElement('button');
            cancelBtn.style.cssText = 'background:#1a1a2e;color:#999;border:1px solid #444;padding:10px 24px;cursor:pointer;font-family:Orbitron,monospace;font-size:13px;border-radius:4px;';
            cancelBtn.textContent = cancelText;
            cancelBtn.onclick = function() { closeModal(false); };
            btnRow.appendChild(cancelBtn);
        }

        var okBtn = document.createElement('button');
        okBtn.style.cssText = 'background:' + confirmColor + ';color:#0a0a12;border:none;padding:10px 28px;cursor:pointer;font-family:Orbitron,monospace;font-size:13px;font-weight:bold;border-radius:4px;';
        okBtn.textContent = isAlert ? 'OK' : confirmText;
        okBtn.onclick = function() { closeModal(true); };
        btnRow.appendChild(okBtn);

        content.appendChild(btnRow);
        shell.appendChild(content);
        overlay.appendChild(shell);
        document.body.appendChild(overlay);

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) closeModal(false);
        });

        function onKey(e) {
            if (e.key === 'Escape') closeModal(false);
        }
        document.addEventListener('keydown', onKey);
    });
}

function lcarsAlert(message, opts) {
    opts = opts || {};
    opts.alert = true;
    opts.title = opts.title || 'NOTICE';
    return lcarsConfirm(message, opts);
}

// ══════════════════════════════════════════════════════════════
// BROWSER NODE CLIENT — no install, the browser IS the node
// ══════════════════════════════════════════════════════════════
var _browserNode = { active: false, nodeId: null, apiKey: null, interval: null, ollamaUrl: 'http://localhost:11434' };

function browserNodeConnect() {
    var statusEl = document.getElementById('browser-node-status');
    var btnEl = document.getElementById('browser-node-btn');
    if (_browserNode.active) { browserNodeDisconnect(); return; }

    if (statusEl) statusEl.textContent = 'Detecting Ollama...';
    if (btnEl) btnEl.disabled = true;

    // Step 1: Check if Ollama is running locally
    fetch(_browserNode.ollamaUrl + '/api/tags', { signal: AbortSignal.timeout(3000) })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        var modelCount = (data.models || []).length;
        if (statusEl) statusEl.textContent = 'Ollama found (' + modelCount + ' models). Registering...';

        // Step 2: Register with hub
        return fetch('/tools/starbase/api/nodes/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                node_name: 'Browser-' + navigator.userAgent.split(/[()]/)[1].split(';')[0].trim().replace(/\s+/g, '-'),
                deployment_mode: 'starship',
                ram_gb: navigator.deviceMemory || 8,
                cpu_cores: navigator.hardwareConcurrency || 4,
                ollama_models: data.models || []
            })
        });
    })
    .then(function(r) { return r.json(); })
    .then(function(reg) {
        if (!reg.success && !reg.node_id) { throw new Error(reg.error || 'Registration failed'); }
        _browserNode.nodeId = reg.node_id;
        _browserNode.apiKey = reg.api_key;
        _browserNode.active = true;

        // Save to localStorage so it survives page refresh
        localStorage.setItem('archie_browser_node', JSON.stringify({ nodeId: reg.node_id, apiKey: reg.api_key }));

        if (statusEl) statusEl.textContent = 'ONLINE — ' + reg.node_id;
        if (statusEl) statusEl.style.color = '#22c55e';
        if (btnEl) { btnEl.textContent = 'DISCONNECT'; btnEl.disabled = false; btnEl.style.background = '#ef4444'; }

        // Step 3: Start heartbeat loop
        _browserNodeHeartbeat();
        _browserNode.interval = setInterval(_browserNodeHeartbeat, 30000);
    })
    .catch(function(err) {
        if (statusEl) { statusEl.textContent = 'Failed: ' + err.message; statusEl.style.color = '#ef4444'; }
        if (btnEl) { btnEl.disabled = false; }
        if (err.message && err.message.indexOf('Ollama') === -1 && err.message.indexOf('fetch') === -1) return;
        if (statusEl) statusEl.textContent = 'Ollama not found at localhost:11434. Is it running?';
    });
}

function _browserNodeHeartbeat() {
    if (!_browserNode.active || !_browserNode.nodeId) return;
    var ollamaUrl = _browserNode.ollamaUrl;

    // Collect metrics
    Promise.all([
        fetch(ollamaUrl + '/api/tags', { signal: AbortSignal.timeout(3000) }).then(function(r) { return r.json(); }).catch(function() { return { models: [] }; }),
        fetch(ollamaUrl + '/api/ps', { signal: AbortSignal.timeout(3000) }).then(function(r) { return r.json(); }).catch(function() { return { models: [] }; })
    ]).then(function(results) {
        var tags = results[0];
        var ps = results[1];
        return fetch('/tools/starbase/api/nodes/' + _browserNode.nodeId + '/heartbeat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Node-API-Key': _browserNode.apiKey || '' },
            body: JSON.stringify({
                status: 'online',
                client_version: 'browser-1.0',
                ollama_online: true,
                ollama_models: tags.models || [],
                ram_gb: navigator.deviceMemory || 8,
                cpu_cores: navigator.hardwareConcurrency || 4,
                cpu_usage: 0,
                memory_usage: 0,
                gpu_usage: 0,
                details: { hostname: location.hostname, userAgent: navigator.userAgent, type: 'browser_node' }
            })
        });
    }).then(function(r) { return r.json(); }).then(function(resp) {
        var el = document.getElementById('browser-node-status');
        if (el && _browserNode.active) {
            el.textContent = 'ONLINE — heartbeat OK';
            el.style.color = '#22c55e';
        }
    }).catch(function() {
        var el = document.getElementById('browser-node-status');
        if (el) { el.textContent = 'Heartbeat failed — retrying...'; el.style.color = '#f59e0b'; }
    });
}

function browserNodeDisconnect() {
    _browserNode.active = false;
    if (_browserNode.interval) clearInterval(_browserNode.interval);
    _browserNode.interval = null;
    localStorage.removeItem('archie_browser_node');
    var statusEl = document.getElementById('browser-node-status');
    var btnEl = document.getElementById('browser-node-btn');
    if (statusEl) { statusEl.textContent = 'Disconnected'; statusEl.style.color = '#888'; }
    if (btnEl) { btnEl.textContent = 'CONNECT THIS MACHINE'; btnEl.style.background = ''; btnEl.disabled = false; }
}

// Auto-resume browser node on page load
(function() {
    var saved = localStorage.getItem('archie_browser_node');
    if (saved) {
        try {
            var data = JSON.parse(saved);
            _browserNode.nodeId = data.nodeId;
            _browserNode.apiKey = data.apiKey;
            _browserNode.active = true;
            _browserNodeHeartbeat();
            _browserNode.interval = setInterval(_browserNodeHeartbeat, 30000);
            setTimeout(function() {
                var el = document.getElementById('browser-node-status');
                var btn = document.getElementById('browser-node-btn');
                if (el) { el.textContent = 'ONLINE — resumed'; el.style.color = '#22c55e'; }
                if (btn) { btn.textContent = 'DISCONNECT'; btn.style.background = '#ef4444'; }
            }, 500);
        } catch(e) { localStorage.removeItem('archie_browser_node'); }
    }
})();

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
        _setLive(el('hero-agents'), ok ? (data.active_agents || 0) : '--', ok);
        _setLive(el('hero-deployed'), ok ? (data.deployed_agents || 0) : '--', ok);
        _setLive(el('hero-barracked'), ok ? (data.barracked_agents || 0) : '--', ok);
        _setLive(el('hero-models'), ok ? (data.loaded_models || 0) : '--', ok);
        _setLive(el('hero-jobs'), ok ? (data.active_jobs || 0) : '--', ok);
        _setLive(el('hero-nodes'), ok ? ((data.online_nodes || 0) + '/' + (data.total_nodes || 0)) : '--', ok);
    } catch(e) {
        console.warn('Hero stats load failed:', e);
        var el = function(id) { return document.getElementById(id); };
        ['hero-agents','hero-deployed','hero-barracked','hero-models','hero-jobs','hero-nodes'].forEach(function(id) {
            _setLive(el(id), '--', false);
        });
    }
}

// ── Docked Fleet — mark all values as live + load agent counts ──
function loadDockedFleetStats() {
    // Mark GPU/RAM values from Jinja as live (they came from DB)
    document.querySelectorAll('.docked-ship').forEach(function(ship) {
        var nodeId = ship.getAttribute('data-node-id');
        var gpuEl = document.getElementById('dock-gpu-' + nodeId);
        var vramEl = document.getElementById('dock-vram-' + nodeId);
        var ramEl = document.getElementById('dock-ram-' + nodeId);
        if (gpuEl && gpuEl.textContent !== '--') _setLive(gpuEl, gpuEl.textContent, true);
        if (vramEl && vramEl.textContent !== '-- GB') _setLive(vramEl, vramEl.textContent, true);
        if (ramEl && ramEl.textContent !== '-- GB') _setLive(ramEl, ramEl.textContent, true);
    });

    // Fetch agent counts from public starbase stats API
    fetch('/tools/starship/api/starbase-stats')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            // Get node agent counts via the fleet endpoint
            return fetch('/tools/starship/api/fleet-agents');
        })
        .then(function(r) { return r ? r.json() : null; })
        .then(function(data) {
            if (!data || !data.success) return;
            (data.nodes || []).forEach(function(n) {
                // Docked fleet strip
                var agentEl = document.getElementById('dock-agents-' + n.node_id);
                if (agentEl) _setLive(agentEl, n.agent_count, true);
                var vramEl = document.getElementById('dock-vram-' + n.node_id);
                if (vramEl) _setLive(vramEl, n.vram_used + '/' + n.vram_total + ' GB', true);
                var ramEl = document.getElementById('dock-ram-' + n.node_id);
                if (ramEl) _setLive(ramEl, n.ram_used + '/' + n.ram_total + ' GB', true);
                // Fleet grid cards (same data)
                _setLive(document.getElementById('fleet-agents-' + n.node_id), n.agent_count, true);
                _setLive(document.getElementById('fleet-ram-' + n.node_id), n.ram_used + '/' + n.ram_total, true);
                _setLive(document.getElementById('fleet-vram-' + n.node_id), n.vram_used + '/' + n.vram_total, true);
                _setLive(document.getElementById('fleet-models-' + n.node_id), n.models_loaded, true);
            });
        })
        .catch(function(e) {
            console.warn('Docked fleet stats failed:', e);
        });
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
    function doOtaPush() {
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
    if (type === 'update') {
        lcarsConfirm('Push a code update to this node?', {
            title: 'CODE UPDATE',
            confirmText: 'PUSH UPDATE',
            confirmColor: '#fbbf24'
        }).then(function(ok) { if (ok) doOtaPush(); });
    } else {
        doOtaPush();
    }
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

// ══════════════════════════════════════════════════════════════
// MODAL OTA TAB — functions for per-node OTA inside detail modal
// ══════════════════════════════════════════════════════════════

function modalOtaPush(type) {
    if (!selectedNodeDbId) { scToast('No node selected', 'error'); return; }
    var endpoint = type === 'update'
        ? '/tools/starship/api/nodes/' + selectedNodeDbId + '/push-update'
        : '/tools/starship/api/nodes/' + selectedNodeDbId + '/push-config';
    var body = type === 'config' ? JSON.stringify({type: 'agent_config'}) : '{}';
    function doIt() {
        fetch(endpoint, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: body })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    scToast('Push successful' + (data.sync_id ? ' (ID: ' + data.sync_id + ')' : ''), 'success');
                    modalLoadSyncStatus();
                    modalLoadSyncLog();
                } else {
                    scToast(data.error || 'Push failed', 'error');
                }
            }).catch(function() { scToast('Network error', 'error'); });
    }
    if (type === 'update') {
        lcarsConfirm('Push a code update to this node?', {
            title: 'CODE UPDATE',
            confirmText: 'PUSH UPDATE',
            confirmColor: '#fbbf24'
        }).then(function(ok) { if (ok) doIt(); });
    } else {
        doIt();
    }
}

function modalPullModel() {
    if (!selectedNodeDbId) { scToast('No node selected', 'error'); return; }
    var sel = document.getElementById('modal-pull-model-select');
    var model = sel.value;
    if (!model) { scToast('Select a model', 'error'); return; }
    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/pull-model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model_name: model})
    }).then(function(r) { return r.json(); })
      .then(function(data) {
          if (data.success) { scToast('Model pull queued', 'success'); modalLoadSyncLog(); }
          else { scToast(data.error || 'Failed', 'error'); }
      }).catch(function() { scToast('Network error', 'error'); });
}

function modalLoadSyncStatus() {
    if (!selectedNodeDbId) return;
    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/sync-status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var dot = document.getElementById('modal-sync-dot');
            var ind = document.getElementById('modal-sync-indicator');
            if (!dot || !ind) return;
            if (data.pending_count === 0) {
                dot.style.background = '#00ff41';
                ind.style.color = 'rgba(0,255,65,0.7)';
                ind.textContent = 'All synced \u2014 v' + (data.config_version || '?');
            } else {
                dot.style.background = '#ffaa00';
                ind.style.color = 'rgba(255,170,0,0.8)';
                ind.textContent = data.pending_count + ' change' + (data.pending_count > 1 ? 's' : '') + ' pending';
            }
        }).catch(function() {});
}

function modalLoadSyncLog() {
    if (!selectedNodeDbId) return;
    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/sync-log')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var tbody = document.getElementById('modal-sync-log-body');
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
                statusTd.style.cssText = 'padding:6px;font-family:IBM Plex Mono,monospace;font-size:0.8rem;';
                var timeTd = document.createElement('td');
                timeTd.textContent = log.created_at ? new Date(log.created_at).toLocaleString() : '\u2014';
                timeTd.style.cssText = 'padding:6px;color:rgba(255,255,255,0.5);font-family:IBM Plex Mono,monospace;font-size:0.8rem;';
                row.appendChild(typeTd); row.appendChild(statusTd); row.appendChild(timeTd);
                tbody.appendChild(row);
            });
        }).catch(function() {});
}

var _modalModelCatalogLoaded = false;
function loadModalModelCatalog() {
    if (_modalModelCatalogLoaded) return;
    _modalModelCatalogLoaded = true;
    fetch('/tools/starship/api/model-catalog')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var sel = document.getElementById('modal-pull-model-select');
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

// ── Add Node Modal (legacy — kept for backward compat) ──
function openAddNodeModal() { openConnectNodeModal(); }
function closeAddNodeModal() { closeConnectModal(); }

// ── Connect a Machine Modal (LCARS) ──
function openConnectNodeModal() {
    document.getElementById('connectNodeModal').style.display = 'flex';
    // Reset ZIP download link
    var zipBtn = document.getElementById('cn-zip-download');
    if (zipBtn) {
        zipBtn.href = '#';
        zipBtn.style.opacity = '0.4';
        zipBtn.style.pointerEvents = 'none';
        zipBtn.textContent = 'Request a node first';
    }
    loadPendingNodes();
    loadApprovedNodesForDownload();
}

function loadApprovedNodesForDownload() {
    // Load approved nodes so user can download ZIP for any of them
    fetch('/tools/starship/api/nodes')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var nodes = (data.nodes || []).filter(function(n) {
                return n.approval_status === 'approved' || n.approval_status === 'pending';
            });
            var zipBtn = document.getElementById('cn-zip-download');
            if (!zipBtn || nodes.length === 0) return;
            // Use the most recent node for the download link
            var latest = nodes[0];
            zipBtn.href = '/tools/starship/api/nodes/' + encodeURIComponent(latest.node_id) + '/download-zip';
            zipBtn.style.opacity = '1';
            zipBtn.style.pointerEvents = 'auto';
            zipBtn.textContent = 'Download Node ZIP (' + (latest.node_name || latest.node_id) + ')';
        })
        .catch(function() {});
}

function closeConnectModal() {
    document.getElementById('connectNodeModal').style.display = 'none';
    pendingConfig = null;
    if (nodeConnectionPoller) { clearInterval(nodeConnectionPoller); nodeConnectionPoller = null; }
}

// showConnectTab removed — Docker-only deployment has no platform tabs

function copyConnectCmd(elementId) {
    var el = document.getElementById(elementId);
    if (!el) return;
    var text = el.textContent;
    // Fallback copy for HTTP (navigator.clipboard requires HTTPS)
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    var btn = el.parentElement.querySelector('.cn-copy-btn');
    if (btn) {
        btn.textContent = 'COPIED';
        setTimeout(function() { btn.textContent = 'COPY'; }, 2000);
    }
    scToast('Copied to clipboard', 'success');
}

function loadPendingNodes() {
    var container = document.getElementById('cn-pending-nodes');
    if (!container) return;
    // Clear existing
    while (container.firstChild) container.removeChild(container.firstChild);

    fetch('/tools/starship/api/nodes')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var nodes = (data.nodes || []).filter(function(n) { return n.approval_status === 'pending'; });
            if (nodes.length === 0) {
                var p = document.createElement('p');
                p.className = 'cn-note';
                p.textContent = 'No pending nodes';
                container.appendChild(p);
                return;
            }
            nodes.forEach(function(n) {
                var card = document.createElement('div');
                card.className = 'cn-pending-card';

                var nameEl = document.createElement('span');
                nameEl.className = 'cn-pending-name';
                nameEl.textContent = n.node_name || 'Unknown';
                card.appendChild(nameEl);

                var gpuEl = document.createElement('span');
                gpuEl.className = 'cn-pending-gpu';
                gpuEl.textContent = n.gpu_model || 'No GPU';
                card.appendChild(gpuEl);

                var ramEl = document.createElement('span');
                ramEl.className = 'cn-pending-ram';
                ramEl.textContent = (n.ram_gb || '?') + ' GB RAM';
                card.appendChild(ramEl);

                var approveBtn = document.createElement('button');
                approveBtn.className = 'cn-approve-btn';
                approveBtn.textContent = 'APPROVE';
                approveBtn.onclick = function() { approveNodeFromModal(n.node_id, card); };
                card.appendChild(approveBtn);

                var denyBtn = document.createElement('button');
                denyBtn.className = 'cn-deny-btn';
                denyBtn.textContent = 'DENY';
                denyBtn.onclick = function() { denyNodeFromModal(n.node_id, card); };
                card.appendChild(denyBtn);

                container.appendChild(card);
            });
        })
        .catch(function() {
            var p = document.createElement('p');
            p.className = 'cn-note';
            p.textContent = 'Failed to load pending nodes';
            p.style.color = '#ef4444';
            container.appendChild(p);
        });
}

function approveNodeFromModal(nodeId, cardEl) {
    fetch('/tools/starbase/api/nodes/' + nodeId + '/approve', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success || data.status === 'approved') {
                cardEl.style.opacity = '0.5';
                var btn = cardEl.querySelector('.cn-approve-btn');
                if (btn) { btn.textContent = 'APPROVED'; btn.disabled = true; }
                scToast('Node approved', 'success');
            }
        })
        .catch(function() { scToast('Failed to approve node', 'error'); });
}

function denyNodeFromModal(nodeId, cardEl) {
    lcarsConfirm('Deny this node? It will be permanently removed.', {
        title: 'DENY NODE',
        confirmText: 'DENY',
        confirmColor: '#ef4444'
    }).then(function(ok) {
        if (!ok) return;
        fetch('/tools/starbase/api/nodes/' + nodeId + '/deny', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function() {
                cardEl.remove();
                scToast('Node denied', 'success');
            })
            .catch(function() { scToast('Failed to deny node', 'error'); });
    });
}

// Resync modal (manual commands for offline resync)
function showResyncModal() {
    var serverUrl = window.location.origin;
    var winCmd = document.getElementById('resync-cmd-win');
    var linuxCmd = document.getElementById('resync-cmd-linux');
    // Keep the copy buttons, set text before them
    var winText = 'iwr -useb ' + serverUrl + '/tools/starship/api/nodes/update.ps1 | iex';
    var linuxText = 'curl -sL ' + serverUrl + '/tools/starship/api/nodes/heartbeat.sh -o /opt/archie-node/heartbeat.sh && chmod +x /opt/archie-node/heartbeat.sh && systemctl restart archie-node';
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

// API-driven resync: push config_update + code_update to node via OTA
async function resyncNode() {
    if (!selectedNodeDbId) { scToast('No node selected', 'error'); return; }
    var btn = document.getElementById('d-resync-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'RESYNCING...'; }
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/resync', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        var data = await resp.json();
        if (data.success) {
            var count = (data.sync_ids || []).length;
            scToast('Resync pushed \u2014 ' + count + ' sync command' + (count !== 1 ? 's' : '') + ' queued', 'success');
            // Refresh sync displays
            if (selectedNodeDbId) {
                pollSyncStatus();
                loadSyncLog(selectedNodeDbId);
                opsLoadSyncStatus();
                opsLoadSyncLog();
            }
        } else {
            scToast(data.error || 'Resync failed', 'error');
        }
    } catch (e) {
        scToast('Network error during resync', 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = 'RESYNC NODE'; }
}

// Operations tab resync (uses the ops-selected node)
async function opsResyncNode() {
    if (!_opsSelectedNodeDbId) { scToast('Select a node first', 'error'); return; }
    var btn = document.getElementById('ops-resync-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'RESYNCING...'; }
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/resync', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        var data = await resp.json();
        if (data.success) {
            var count = (data.sync_ids || []).length;
            scToast('Resync pushed \u2014 ' + count + ' sync command' + (count !== 1 ? 's' : '') + ' queued', 'success');
            opsLoadSyncStatus();
            opsLoadSyncLog();
        } else {
            scToast(data.error || 'Resync failed', 'error');
        }
    } catch (e) {
        scToast('Network error during resync', 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = 'RESYNC'; }
}

// V3.0 upgrade from fleet detail panel
async function upgradeNodeV3() {
    if (!selectedNodeDbId) { scToast('No node selected', 'error'); return; }
    var ok = await lcarsConfirm('Push v3.0 upgrade to this node? Containers will restart.', {
        title: 'UPGRADE NODE',
        confirmText: 'UPGRADE',
        confirmColor: '#fbbf24'
    });
    if (!ok) return;
    var btn = document.getElementById('d-upgrade-v3-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'UPGRADING...'; }
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/upgrade-v3', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        var data = await resp.json();
        if (data.success) {
            scToast('Upgrade queued: ' + data.syncs_queued + ' sync commands sent', 'success');
            if (selectedNodeDbId) {
                pollSyncStatus();
                loadSyncLog(selectedNodeDbId);
                opsLoadSyncStatus();
                opsLoadSyncLog();
            }
        } else {
            scToast(data.error || 'Upgrade failed', 'error');
        }
    } catch (e) {
        scToast('Request failed: ' + e, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = 'UPGRADE TO v3.0'; }
}

// V3.0 upgrade from Operations tab
async function opsUpgradeNodeV3() {
    if (!_opsSelectedNodeDbId) { scToast('Select a node first', 'error'); return; }
    var ok = await lcarsConfirm('Push v3.0 upgrade to this node? Containers will restart.', {
        title: 'UPGRADE NODE',
        confirmText: 'UPGRADE',
        confirmColor: '#fbbf24'
    });
    if (!ok) return;
    var btn = document.getElementById('ops-upgrade-v3-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'UPGRADING...'; }
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + _opsSelectedNodeDbId + '/upgrade-v3', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        var data = await resp.json();
        if (data.success) {
            scToast('Upgrade queued: ' + data.syncs_queued + ' sync commands sent', 'success');
            opsLoadSyncStatus();
            opsLoadSyncLog();
        } else {
            scToast(data.error || 'Upgrade failed', 'error');
        }
    } catch (e) {
        scToast('Request failed: ' + e, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = 'UPGRADE v3.0'; }
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
    if (tab === 'diag' && selectedNodeDbId) {
        loadDiagnostics();
    }
    if (tab === 'ota' && selectedNodeDbId) {
        loadModalModelCatalog();
        modalLoadSyncStatus();
        modalLoadSyncLog();
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

    // Status tab — all live from node status API
    _setLive(document.getElementById('d-status'), (n.status || 'unknown').toUpperCase(), !!n.status);
    _setLive(document.getElementById('d-mode'), (n.deployment_mode || '—').toUpperCase(), true);
    _setLive(document.getElementById('d-priority'), n.bridge_priority || '—', true);
    _setLive(document.getElementById('d-heartbeat'), n.last_heartbeat ? new Date(n.last_heartbeat).toLocaleString() : 'Never', !!n.last_heartbeat);

    // Mesh VPN status
    var meshEl = document.getElementById('d-mesh');
    if (meshEl) {
        if (n.mesh_ip) {
            var connType = n.mesh_connection_type === 'direct' ? ' (DIRECT)' : n.mesh_connection_type === 'relay' ? ' (RELAY)' : '';
            _setLive(meshEl, n.mesh_ip + connType, true);
        } else {
            meshEl.textContent = 'Not connected';
            meshEl.className = 'sc-static';
        }
    }

    // BEACON link
    var beaconEl = document.getElementById('d-beacon');
    if (beaconEl) {
        var slug = (n.node_name || '').toLowerCase().replace(/ /g, '-').replace(/[^a-z0-9\-]/g, '');
        if (slug) {
            beaconEl.textContent = '';
            var link = document.createElement('a');
            link.href = 'http://' + slug + '.fleet.kytranempowerment.com';
            link.target = '_blank';
            link.textContent = slug + '.fleet';
            link.style.cssText = 'color:#00e5ff;text-decoration:none;';
            beaconEl.appendChild(link);
            beaconEl.className = 'sc-live';
        } else {
            beaconEl.textContent = 'Not configured';
            beaconEl.className = 'sc-static';
        }
    }

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
                lcarsConfirm('Push update v' + data.version.latest + ' to this node?\n\nThe node will download and install the update on its next heartbeat (~30s).', {
                    title: 'PUSH UPDATE',
                    confirmText: 'UPDATE',
                    confirmColor: '#fbbf24'
                }).then(function(ok) {
                    if (!ok) return;
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
            });
        }
        verEl.appendChild(badge);
    }

    // System Ops gauges (live metrics from heartbeat)
    var lm = data.live_metrics || {};
    renderOpsGauge('ops-cpu', 'ops-cpu-bar', lm.cpu_usage);
    renderOpsGauge('ops-ram', 'ops-ram-bar', lm.memory_usage);
    renderOpsGauge('ops-gpu', 'ops-gpu-bar', lm.gpu_usage);

    // Fleet Summary — live from node status
    var ss = data.station_summary || {};
    var ms = data.model_summary || {};
    var allowedAgents = (data.agents || []).filter(function(a) { return a.allowed; }).length;
    _setLive(document.getElementById('d-active-stations'), (ss.active || 0) + ' / ' + (ss.total || 0), true);
    _setLive(document.getElementById('d-models-avail'), (ms.available || 0) + ' / ' + (ms.total || 0), !!ms.total);
    _setLive(document.getElementById('d-models-size'), (ms.total_size_gb || 0) + ' GB', !!ms.total_size_gb);
    _setLive(document.getElementById('d-agents-allowed'), allowedAgents + ' / ' + (data.agents || []).length, true);

    // Populate inline settings
    var nameEl = document.getElementById('settings-name');
    if (nameEl) nameEl.value = n.node_name || '';
    var modeEl = document.getElementById('settings-mode');
    var currentMode = n.deployment_mode || 'starship';
    if (modeEl) modeEl.value = currentMode;
    selectMode(currentMode);
    var prioEl = document.getElementById('settings-priority');
    var prioVal = n.bridge_priority || 0;
    if (prioEl) { prioEl.value = prioVal; }
    var prioLabel = document.getElementById('priority-val');
    if (prioLabel) prioLabel.textContent = prioVal + '%';

    // Show/hide offline update section
    var offlinePanel = document.getElementById('d-offline-update');
    if (offlinePanel) {
        offlinePanel.style.display = (n.status === 'offline') ? '' : 'none';
    }

    // Crew tab — manifest-style cards (fetched separately)
    renderNodeManifest(selectedNodeDbId);

    // Disconnect button (only for non-starbase nodes)
    var disconnectArea = document.getElementById('d-disconnect-area');
    if (disconnectArea && n.deployment_mode !== 'starbase') {
        disconnectArea.textContent = '';
        var disconnectBtn = document.createElement('button');
        disconnectBtn.style.cssText = 'background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);color:#ef4444;padding:6px 16px;border-radius:4px;cursor:pointer;font-size:0.75rem;font-family:Antonio,sans-serif;letter-spacing:1px;text-transform:uppercase;';
        disconnectBtn.textContent = '\u26A0 DISCONNECT NODE';
        disconnectBtn.onclick = function() { showDisconnectModal(selectedNodeId, n.node_name); };
        disconnectArea.appendChild(disconnectBtn);
    }
}

// ── Node STATIONS tab — DepartmentOps terminals per node station ──
var _nodeStationsLoaded = {};
var _nodeDepartmentOps = {};

// Station color map for LCARS terminals
var _stationColorMap = {
    'COMMAND':        {hex: '#00e5ff', rgb: '0,229,255'},
    'ANALYTICS':      {hex: '#8b5cf6', rgb: '139,92,246'},
    'CREATIVE':       {hex: '#f472b6', rgb: '244,114,182'},
    'ENGINEERING':    {hex: '#fbbf24', rgb: '251,191,36'},
    'COMMUNICATIONS': {hex: '#22d3ee', rgb: '34,211,238'},
    'RESEARCH':       {hex: '#10b981', rgb: '16,185,129'},
    'SECURITY':       {hex: '#ef4444', rgb: '239,68,68'},
    'LOGISTICS':      {hex: '#f97316', rgb: '249,115,22'},
    'DIPLOMATIC':     {hex: '#818cf8', rgb: '129,140,248'},
    'OPERATIONS':     {hex: '#a3e635', rgb: '163,230,53'}
};

async function loadNodeStations(nodeDbId) {
    var grid = document.getElementById('d-node-stations-grid');
    if (!grid) return;
    if (_nodeStationsLoaded[nodeDbId]) {
        // Re-render with fresh job data
        _refreshNodeStations(nodeDbId);
        return;
    }

    grid.textContent = '';

    // Get this node's crew to find which stations it has
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + nodeDbId + '/crew-manifest');
        var data = await resp.json();
        if (!data.success) { grid.innerHTML = '<span class="sc-label">Failed to load</span>'; return; }  // nosemgrep

        var crew = data.crew || [];
        // Collect unique station codes from node agents
        var stationCodes = {};
        crew.forEach(function(a) {
            var codes = a.station_codes || [a.station || 'UNASSIGNED'];
            codes.forEach(function(c) { stationCodes[c] = true; });
        });

        var codes = Object.keys(stationCodes).sort();
        if (!codes.length) {
            grid.innerHTML = '<span class="sc-label">No stations assigned</span>';  // nosemgrep
            return;
        }

        // Create DepartmentOps terminal HTML + instances for each station
        _nodeDepartmentOps[nodeDbId] = {};
        codes.forEach(function(code) {
            var colors = _stationColorMap[code] || {hex: '#00e5ff', rgb: '0,229,255'};
            var termId = 'node-stn-' + nodeDbId + '-' + code;

            // Create terminal HTML container
            var terminal = document.createElement('div');
            terminal.className = 'stn-ops-terminal';
            terminal.id = termId;
            terminal.style.cssText = '--stn-accent:' + colors.hex + ';--stn-accent-rgb:' + colors.rgb + ';';
            // Starship COMMAND gets a unique name and single-slot config
            var isShipCommand = (code === 'COMMAND');
            var stationLabel = isShipCommand ? 'STARSHIP COMMAND OPS' : (code + ' OPERATIONS');

            terminal.innerHTML =  // nosemgrep: static HTML structure, no user data
                '<div class="stn-ops-header">' +
                    '<div class="stn-ops-elbow"></div>' +
                    '<div class="stn-ops-title">' + stationLabel + '</div>' +
                    '<div class="stn-ops-status" id="' + termId + '-status"><span class="stn-ops-dot"></span> OFFLINE</div>' +
                '</div>' +
                '<div class="stn-ops-body">' +
                    '<div id="' + termId + '-agents"></div>' +
                    '<div id="' + termId + '-jobs"></div>' +
                    '<div class="stn-ops-commands" id="' + termId + '-commands"></div>' +
                '</div>';
            grid.appendChild(terminal);

            // Create DepartmentOps instance — uses NODE stations endpoint, not hub
            var stationConfig = {
                stationCode: code,
                moduleSource: 'starship',
                agentsElId: termId + '-agents',
                jobsElId: termId + '-jobs',
                commandsElId: termId + '-commands',
                statusElId: termId + '-status',
                dataUrl: '/tools/starship/api/nodes/' + nodeDbId + '/stations',
                commands: []
            };
            if (isShipCommand) {
                stationConfig.maxPrimary = 1;
                stationConfig.maxAux = 0;
            }
            _nodeDepartmentOps[nodeDbId][code] = new DepartmentOps(stationConfig);
        });

        _nodeStationsLoaded[nodeDbId] = true;
        _refreshNodeStations(nodeDbId);
    } catch (e) {
        grid.innerHTML = '<span class="sc-label">Failed to load stations</span>';  // nosemgrep
        console.error('Node stations load failed:', e);
    }
}

function _refreshNodeStations(nodeDbId) {
    var ops = _nodeDepartmentOps[nodeDbId];
    if (!ops) return;
    fetch('/tools/starbase/api/bridge/jobs?status=running')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var allJobs = (data.success && data.jobs) ? data.jobs : [];
            Object.keys(ops).forEach(function(code) {
                ops[code].render(allJobs);
            });
        })
        .catch(function() {
            Object.keys(ops).forEach(function(code) {
                ops[code].render([]);
            });
        });
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

// Unified agent card renderer — same card for hub AGENTS tab, node CREW tab, everywhere
function _renderStarshipAgentCard(agent) {
    var hubId = agent.hub_agent_id || agent.agent_id || agent.id;
    return _renderUnifiedAgentCard(agent, function() { openAgentProfileFromBridge(hubId); });

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
    var ok = await lcarsConfirm('Push a code update to this node? The node will download and install on its next heartbeat.', {
        title: 'CODE UPDATE',
        confirmText: 'PUSH UPDATE',
        confirmColor: '#fbbf24'
    });
    if (!ok) return;
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

// ══════════════════════════════════════════════════════════════
// DIAGNOSTICS TAB — remote node health snapshot (v3.0)
// ══════════════════════════════════════════════════════════════

function _diagStatus(online) {
    var span = document.createElement('span');
    span.style.color = online ? 'var(--sc-green)' : 'var(--sc-red)';
    span.textContent = online ? 'ONLINE' : 'OFFLINE';
    return span;
}

function loadDiagnostics() {
    if (!selectedNodeDbId) return;
    var loading = document.getElementById('diag-loading');
    var error = document.getElementById('diag-error');
    var content = document.getElementById('diag-content');
    var btn = document.getElementById('diag-refresh-btn');

    loading.style.display = '';
    error.style.display = 'none';
    content.style.display = 'none';
    if (btn) btn.disabled = true;

    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/diagnostics')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            loading.style.display = 'none';
            if (btn) btn.disabled = false;

            if (!data.success) {
                error.style.display = '';
                document.getElementById('diag-error-msg').textContent = data.error || 'Failed to reach node';
                return;
            }

            content.style.display = '';
            var d = data.diagnostics;

            // Disk
            if (d.disk && !d.disk.error) {
                var diskPct = d.disk.percent_used || 0;
                renderOpsGauge('diag-disk-val', 'diag-disk-bar', diskPct);
                document.getElementById('diag-disk-free').textContent = d.disk.free_gb + ' GB free of ' + d.disk.total_gb + ' GB';
            }

            // GPU
            if (d.gpu && d.gpu.model) {
                document.getElementById('diag-gpu-model').textContent = d.gpu.model;
                var vramPct = d.gpu.vram_total_mb > 0 ? Math.round((d.gpu.vram_used_mb / d.gpu.vram_total_mb) * 100) : 0;
                renderOpsGauge('diag-vram-val', 'diag-vram-bar', vramPct);
                document.getElementById('diag-gpu-temp').textContent = d.gpu.temperature_c + '\u00B0C';
            } else {
                document.getElementById('diag-gpu-model').textContent = 'No GPU detected';
                document.getElementById('diag-gpu-temp').textContent = '\u2014';
            }

            // Ollama
            if (d.ollama) {
                var ollamaEl = document.getElementById('diag-ollama-status');
                ollamaEl.textContent = '';
                ollamaEl.appendChild(_diagStatus(d.ollama.online));
                document.getElementById('diag-ollama-count').textContent = d.ollama.model_count || 0;
                var loadedNames = (d.ollama.loaded || []).map(function(m) { return m.name; }).join(', ');
                document.getElementById('diag-ollama-loaded').textContent = loadedNames || 'None';

                var modelsDiv = document.getElementById('diag-ollama-models');
                modelsDiv.textContent = '';
                (d.ollama.models || []).forEach(function(m) {
                    var tag = document.createElement('span');
                    tag.style.cssText = 'padding:3px 8px;border-radius:4px;font-size:0.7rem;font-family:IBM Plex Mono,monospace;background:rgba(0,229,255,0.08);border:1px solid rgba(0,229,255,0.2);color:var(--sc-accent);';
                    tag.textContent = m.name + ' (' + m.size_gb + 'GB)';
                    modelsDiv.appendChild(tag);
                });
            }

            // ComfyUI
            if (d.comfyui) {
                var comfyEl = document.getElementById('diag-comfy-status');
                comfyEl.textContent = '';
                comfyEl.appendChild(_diagStatus(d.comfyui.online));
                if (d.comfyui.online) {
                    document.getElementById('diag-comfy-vram').textContent =
                        Math.round(d.comfyui.vram_free_mb) + ' MB / ' + Math.round(d.comfyui.vram_total_mb) + ' MB';
                }
            }

            // Database
            if (d.database) {
                var dbEl = document.getElementById('diag-db-status');
                dbEl.textContent = '';
                dbEl.appendChild(_diagStatus(d.database.connected));
                document.getElementById('diag-db-agents').textContent = d.database.agents || 0;
                document.getElementById('diag-db-jobs').textContent = d.database.pending_jobs || 0;
            }

            // System
            document.getElementById('diag-version').textContent = d.client_version || '\u2014';
            document.getElementById('diag-python').textContent = d.python_version || '\u2014';
            document.getElementById('diag-platform').textContent = d.platform || '\u2014';
            var upSec = d.uptime_seconds || 0;
            var hours = Math.floor(upSec / 3600);
            var mins = Math.floor((upSec % 3600) / 60);
            document.getElementById('diag-uptime').textContent = hours + 'h ' + mins + 'm';
        })
        .catch(function(e) {
            loading.style.display = 'none';
            error.style.display = '';
            if (btn) btn.disabled = false;
            document.getElementById('diag-error-msg').textContent = 'Network error: ' + e.message;
        });
}

// ── Save Node Settings (inline on STATUS tab) ──
function selectMode(mode) {
    document.querySelectorAll('.sc-mode-option').forEach(function(btn) {
        btn.classList.toggle('active', btn.getAttribute('data-mode') === mode);
    });
    var hidden = document.getElementById('settings-mode');
    if (hidden) hidden.value = mode;
}

async function saveNodeSettings() {
    if (!selectedNodeId) return;
    var name = document.getElementById('settings-name').value.trim();
    var mode = document.getElementById('settings-mode').value;
    var priority = parseInt(document.getElementById('settings-priority').value) || 0;
    try {
        var resp = await fetch('/tools/starship/api/nodes/' + encodeURIComponent(selectedNodeId) + '/settings', {
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

// Unified agent profile — always fetches from Bridge (single source of truth)
function openAgentProfileFromBridge(hubAgentId) {
    _nodeProfileAgentId = hubAgentId;
    var modal = document.getElementById('node-agent-profile-modal');
    var body = document.getElementById('node-profile-body');
    var title = document.getElementById('node-profile-title');
    modal.classList.add('active');
    body.innerHTML = '<span class="sc-label">Loading profile...</span>';  // nosemgrep
    title.textContent = 'AGENT PROFILE';

    fetch('/tools/starbase/api/agents/' + parseInt(hubAgentId) + '/profile')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                body.textContent = data.error || 'Failed to load profile';
                return;
            }
            renderAgentProfile(data, body, title, { onClose: 'closeNodeAgentProfile', showPersonnelLink: true });
        }).catch(function(err) {
            body.textContent = 'Failed to load profile: ' + err;
        });
}

// Hub agents tab — calls Bridge directly
function openHubAgentProfile(hubAgentId) {
    openAgentProfileFromBridge(hubAgentId);
}

// Node crew tab — looks up hub_agent_id first, then calls Bridge
function openNodeAgentProfile(nodeAgentId) {
    // Fetch hub_agent_id from the node agent, then open Bridge profile
    fetch('/tools/starship/api/nodes/' + selectedNodeDbId + '/agents/' + nodeAgentId + '/profile')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success && data.agent && data.agent.hub_agent_id) {
                openAgentProfileFromBridge(data.agent.hub_agent_id);
            } else if (data.success && data.agent && data.agent.id) {
                // Fallback: use the agent id directly
                openAgentProfileFromBridge(data.agent.id);
            } else {
                var body = document.getElementById('node-profile-body');
                body.textContent = data.error || 'Agent not linked to hub';
            }
        }).catch(function(err) {
            var body = document.getElementById('node-profile-body');
            body.textContent = 'Failed: ' + err;
        });
}

function closeNodeAgentProfile() {
    document.getElementById('node-agent-profile-modal').classList.remove('active');
}

// _renderNodeAgentProfile removed — now using shared renderAgentProfile() from agent-profile.js
function _renderNodeAgentProfile_REMOVED() { /* see agent-profile.js */ }
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
        var resp = await fetch('/tools/starbase/api/bridge/crew/manifest');
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

    // Station count — fetch live from Bridge
    fetch('/tools/starbase/api/stations').then(function(r) { return r.json(); }).then(function(sdata) {
        if (sdata.success) {
            var active = (sdata.stations || []).filter(function(s) { return s.assigned_agents && s.assigned_agents.length > 0; }).length;
            var total = (sdata.stations || []).length;
            _setLive(el('sbd-stations'), active + ' / ' + total, true);
        }
    }).catch(function() {});

    // Hardware — all from Bridge capacity API
    var cpuModels = cap.cpu_models || [];
    var cpuLabel = cpuModels.length + ' model' + (cpuModels.length !== 1 ? 's' : '') + ' on CPU';
    _setLive(el('sbd-cpu'), cpuModels.length ? cpuLabel : '--', cpuModels.length > 0);
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

    // RAM budget — pull directly from Bridge capacity (ADR-078)
    var hasRam = !!cap.ram;
    var llmBudget = hasRam ? cap.ram.llm_budget_gb : '--';
    var agentBudget = hasRam ? cap.ram.agent_budget_gb : '--';
    var swapBuffer = hasRam ? cap.ram.swap_buffer_gb : '--';
    var reserve = hasRam ? cap.ram.reserve_gb : '--';
    _setLive(el('sbd-llm-budget'), (hasRam ? Math.round(llmBudget) : '--') + ' GB', hasRam);
    _setLive(el('sbd-agent-budget'), (hasRam ? Math.round(agentBudget) : '--') + ' GB', hasRam);
    _setLive(el('sbd-swap-buffer'), (hasRam ? Math.round(swapBuffer) : '--') + ' GB', hasRam);
    _setLive(el('sbd-reserve'), (hasRam ? Math.round(reserve) : '--') + ' GB', hasRam);
    var availGb = hasRam ? cap.ram.available_gb : 0;
    var ramStatus = hasRam ? cap.ram.status : 'unknown';
    if (ramStatus === 'green') {
        _setLive(el('sbd-ram-status'), 'NOMINAL', true);
        if (el('sbd-ram-status')) el('sbd-ram-status').style.color = 'var(--sc-green)';
    } else if (ramStatus === 'amber') {
        _setLive(el('sbd-ram-status'), 'CAUTION', true);
        if (el('sbd-ram-status')) el('sbd-ram-status').style.color = 'var(--sc-amber)';
    } else if (ramStatus === 'red') {
        _setLive(el('sbd-ram-status'), 'CRITICAL', true);
        if (el('sbd-ram-status')) el('sbd-ram-status').style.color = 'var(--sc-red)';
    } else {
        _setLive(el('sbd-ram-status'), '--', false);
    }

    // GPU model badges (cap.gpu_models = [{name, size_gb, vram_gb}, ...])
    // Note: innerHTML with pre-escaped content via _escSb — matches Consciousness pattern
    var gpuDiv = el('sbd-gpu-models');
    var gpuList = cap.gpu_models || (cap.gpu ? cap.gpu.models : []) || [];
    if (gpuDiv) {
        gpuDiv.innerHTML = gpuList.length ? gpuList.map(function(m) {  // nosemgrep: innerHTML with escaped content
            var label = _escSb((m.name || m) + (m.vram_gb ? ' (' + m.vram_gb + 'GB)' : ''));
            return '<span class="sc-model-badge sc-live">' + label + '</span>';
        }).join('') : (cap.gpu && cap.gpu.comfyui_vram_gb
            ? '<span class="sc-model-badge sc-live">ComfyUI (' + cap.gpu.comfyui_vram_gb + ' GB VRAM)</span>'
            : '<span class="sc-label sc-static">None on GPU</span>');
    }

    // CPU model badges (cap.cpu_models = [{name, size_gb}, ...])
    var cpuDiv = el('sbd-cpu-models');
    var cpuList = cap.cpu_models || [];
    if (cpuDiv) {
        cpuDiv.innerHTML = cpuList.length ? cpuList.map(function(m) {  // nosemgrep: innerHTML with escaped content
            var label = _escSb((m.name || m) + (m.size_gb ? ' (' + m.size_gb + 'GB)' : ''));
            return '<span class="sc-model-badge sc-model-badge-cpu sc-live">' + label + '</span>';
        }).join('') : '<span class="sc-label sc-static">None on CPU</span>';
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

// ── Stations tab — use shared DepartmentOps component ──
var _sbStationsLoaded = false;
var _sbDepartmentOps = {};
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

    // Create DepartmentOps instances for all 10 stations
    _stationConfigs.forEach(function(cfg) {
        _sbDepartmentOps[cfg.code] = new DepartmentOps({
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
    fetch('/tools/starbase/api/bridge/jobs?status=running')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var allJobs = (data.success && data.jobs) ? data.jobs : [];
            Object.keys(_sbDepartmentOps).forEach(function(code) {
                _sbDepartmentOps[code].render(allJobs);
            });
        })
        .catch(function() {
            // Still render agents even if jobs fetch fails
            Object.keys(_sbDepartmentOps).forEach(function(code) {
                _sbDepartmentOps[code].render([]);
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
        var hubId = a.agent_id || a.id;
        var card = _renderUnifiedAgentCard(a, function() { openAgentProfileFromBridge(hubId); });
        grid.appendChild(card);
    });
}

// ── Unified Agent Card — one renderer for hub, node, everywhere ──
function _renderUnifiedAgentCard(a, onClickFn) {
    var card = document.createElement('div');
    card.className = 'crew-agent-card';
    card.style.cursor = 'pointer';
    card.onclick = function(e) {
        if (e.target.tagName === 'BUTTON') return;
        if (onClickFn) onClickFn();
    };

    // Station color
    var stCodes = a.station_codes || [a.station || 'UNASSIGNED'];
    var stColors = a.station_colors || [];
    var stColor = stColors[0] || (_stationColorMap[stCodes[0]] || {}).hex || '#00e5ff';
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

    // Single status badge — show the most relevant state
    var shift = a.shift_state || 'active';
    var statusBadge = document.createElement('span');
    if (shift === 'barracked') {
        statusBadge.className = 'crew-status-badge barracked';
        statusBadge.textContent = 'BARRACKED';
    } else if (shift === 'deployed') {
        statusBadge.className = 'crew-status-badge deployed';
        statusBadge.textContent = 'DEPLOYED';
    } else if (a.status === 'working' || a.current_job) {
        statusBadge.className = 'crew-status-badge active';
        statusBadge.textContent = 'WORKING';
    } else if (shift === 'off_duty') {
        statusBadge.className = 'crew-status-badge idle';
        statusBadge.textContent = 'OFF DUTY';
    } else {
        statusBadge.className = 'crew-status-badge active';
        statusBadge.textContent = 'ON DUTY';
    }
    badges.appendChild(statusBadge);

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
    var displayName = a.full_name || a.display_name || '';
    if (displayName && displayName !== a.name) {
        var sub = document.createElement('div');
        sub.style.cssText = 'font-size:0.6rem;color:rgba(255,255,255,0.35);margin-top:-2px;';
        sub.textContent = a.name + (a.title ? ' \u2014 ' + a.title : '');
        card.appendChild(sub);
    }

    // Meta row: station + model + workload risk
    var meta = document.createElement('div');
    meta.className = 'crew-agent-meta';
    var stSpan = document.createElement('span');
    stSpan.textContent = stCodes[0] || '--';
    stSpan.style.color = stColor;
    meta.appendChild(stSpan);
    var mdSpan = document.createElement('span');
    mdSpan.textContent = (a.model || '').replace(':latest', '');
    meta.appendChild(mdSpan);
    var wl = a.workload || {};
    if (wl.risk_level) {
        var riskSpan = document.createElement('span');
        var riskColors = { healthy: '#4ade80', elevated: '#fbbf24', critical: '#ef4444', overloaded: '#ef4444' };
        riskSpan.style.color = riskColors[wl.risk_level] || 'rgba(255,255,255,0.4)';
        riskSpan.textContent = wl.risk_level.toUpperCase();
        meta.appendChild(riskSpan);
    }
    card.appendChild(meta);

    // Station tags
    if (stCodes.length > 0 && stCodes[0] !== 'UNASSIGNED') {
        var tagRow = document.createElement('div');
        tagRow.style.cssText = 'display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;';
        stCodes.forEach(function(sc, i) {
            var tag = document.createElement('span');
            tag.className = 'sc-agent-station-tag';
            tag.textContent = sc;
            var c = stColors[i] || (_stationColorMap[sc] || {}).hex || stColor;
            tag.style.borderColor = c + '44';
            tag.style.color = c;
            tagRow.appendChild(tag);
        });
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

    return card;
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

// ── Node Disconnect ──
var _disconnectNodeId = null;

function showDisconnectModal(nodeId, nodeName) {
    _disconnectNodeId = nodeId;
    var modal = document.getElementById('disconnect-node-modal');
    var body = document.getElementById('disconnect-node-body');
    var actions = document.getElementById('disconnect-node-actions');

    body.textContent = '';
    var warn = document.createElement('div');
    warn.style.cssText = 'margin-bottom:12px;padding:10px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:4px;';

    var title = document.createElement('div');
    title.style.cssText = 'font-size:1rem;font-weight:600;color:#ef4444;margin-bottom:6px;';
    title.textContent = '\u26A0 DISCONNECT ' + (nodeName || 'NODE').toUpperCase();
    warn.appendChild(title);

    var msg = document.createElement('div');
    msg.style.cssText = 'font-size:0.8rem;color:rgba(255,255,255,0.6);line-height:1.5;';
    msg.textContent = 'This will permanently remove the node from the fleet. All deployed agents will return to barracks. The node must be re-registered to reconnect.';
    warn.appendChild(msg);
    body.appendChild(warn);

    actions.textContent = '';
    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'bm-btn';
    cancelBtn.style.cssText = 'background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.2);color:rgba(255,255,255,0.6);';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.onclick = closeDisconnectModal;
    actions.appendChild(cancelBtn);

    var confirmBtn = document.createElement('button');
    confirmBtn.className = 'bm-btn';
    confirmBtn.style.cssText = 'background:rgba(239,68,68,0.2);border:1px solid rgba(239,68,68,0.5);color:#ef4444;font-weight:600;';
    confirmBtn.textContent = 'DISCONNECT NODE';
    confirmBtn.onclick = function() {
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Disconnecting...';
        fetch('/tools/starship/api/nodes/' + encodeURIComponent(_disconnectNodeId) + '/disconnect', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'}
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            closeDisconnectModal();
            if (data.success) {
                scToast(data.message || 'Node disconnected', 'success');
                setTimeout(function() { location.reload(); }, 1500);
            } else {
                scToast('Failed: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(function() {
            closeDisconnectModal();
            scToast('Request failed', 'error');
        });
    };
    actions.appendChild(confirmBtn);

    modal.classList.add('active');
}

function closeDisconnectModal() {
    document.getElementById('disconnect-node-modal').classList.remove('active');
    _disconnectNodeId = null;
}

// ── Sync Status Polling ──
var _syncPollTimer = null;

function pollSyncStatus() {
    if (!selectedNodeDbId) return;
    modalLoadSyncStatus();
    modalLoadSyncLog();
}

function startSyncPolling() {
    if (_syncPollTimer) clearInterval(_syncPollTimer);
    pollSyncStatus();
    _syncPollTimer = setInterval(pollSyncStatus, 30000);
}

// ============================================================================
// ONE-CLICK NODE SETUP
// ============================================================================

// Toggle the setup panel open/closed
function toggleSetupPanel() {
    var body = document.getElementById('node-setup-body');
    var toggle = document.getElementById('node-setup-toggle');
    if (body.classList.contains('collapsed')) {
        body.classList.remove('collapsed');
        toggle.classList.remove('collapsed');
        localStorage.setItem('archie-setup-panel', 'open');
    } else {
        body.classList.add('collapsed');
        toggle.classList.add('collapsed');
        localStorage.setItem('archie-setup-panel', 'closed');
    }
}

// Restore panel state from localStorage
(function initSetupPanel() {
    var state = localStorage.getItem('archie-setup-panel');
    if (state === 'closed') {
        var body = document.getElementById('node-setup-body');
        var toggle = document.getElementById('node-setup-toggle');
        if (body) { body.classList.add('collapsed'); }
        if (toggle) { toggle.classList.add('collapsed'); }
    }
    // Populate one-liner commands
    var hubUrl = window.location.origin;
    var winEl = document.getElementById('setup-oneliner-win');
    var linuxEl = document.getElementById('setup-oneliner-linux');
    if (winEl) {
        var winText = winEl.querySelector('.setup-cmd-text');
        if (winText) winText.textContent = 'powershell -ExecutionPolicy Bypass -Command "iwr -useb \'' + hubUrl + '/tools/starship/api/nodes/new-setup-script?os=windows\' -OutFile archie-setup.ps1; .\\archie-setup.ps1"';
    }
    if (linuxEl) {
        var linuxText = linuxEl.querySelector('.setup-cmd-text');
        if (linuxText) linuxText.textContent = 'curl -fsSL "' + hubUrl + '/tools/starship/api/nodes/new-setup-script?os=linux" -o archie-setup.sh && sudo bash archie-setup.sh';
    }
})();

// Download a new node setup script (registers a new node first)
function downloadNewNodeScript(os) {
    var hubUrl = window.location.origin;
    var url = hubUrl + '/tools/starship/api/nodes/new-setup-script?os=' + encodeURIComponent(os);
    // Trigger download via hidden link
    var a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    scToast('Downloading setup script... A new node has been registered.', 'success');
}

// Download a setup/update script for an existing node (from detail modal)
function downloadExistingNodeScript(os) {
    if (!selectedNodeId) { scToast('No node selected', 'error'); return; }
    var hubUrl = window.location.origin;
    var url = hubUrl + '/tools/starship/api/nodes/' + encodeURIComponent(selectedNodeId) + '/setup-script?os=' + encodeURIComponent(os);
    var a = document.createElement('a');
    a.href = url;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    scToast('Downloading update script for this node...', 'success');
}

// Switch between Windows/Linux one-liner tabs
function switchSetupCmdTab(os) {
    document.getElementById('setup-cmd-tab-win').classList.toggle('active', os === 'win');
    document.getElementById('setup-cmd-tab-linux').classList.toggle('active', os === 'linux');
    document.getElementById('setup-cmd-panel-win').style.display = os === 'win' ? '' : 'none';
    document.getElementById('setup-cmd-panel-linux').style.display = os === 'linux' ? '' : 'none';
}

// Copy one-liner to clipboard
function copySetupOneliner(os) {
    var el = document.getElementById('setup-oneliner-' + os);
    var textEl = el.querySelector('.setup-cmd-text');
    var text = textEl ? textEl.textContent : el.textContent.replace('COPY', '').replace('COPIED', '').trim();
    // Fallback copy for HTTP (navigator.clipboard requires HTTPS)
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    var btn = el.querySelector('.sc-copy-btn');
    if (btn) { btn.textContent = 'COPIED'; setTimeout(function() { btn.textContent = 'COPY'; }, 2000); }
    scToast('Copied to clipboard', 'success');
}
