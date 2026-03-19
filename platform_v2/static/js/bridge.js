/* bridge.js — Bridge Command module logic (extracted from bridge.html) */
// === IAAE Capacity Modal ===
function showIaaeCapacityModal(level, info) {
    var modal = document.getElementById('iaae-capacity-modal');
    var title = document.getElementById('iaae-capacity-title');
    var body = document.getElementById('iaae-capacity-body');
    var actions = document.getElementById('iaae-capacity-actions');

    // Fleet mode confirmations
    if (level === 'fleet-weekend') {
        modal.style.setProperty('--bm-accent', '#ffaa00');
        modal.style.setProperty('--bm-accent-rgb', '255,170,0');
        title.textContent = 'SWITCH TO WEEKEND MODE';
        body.innerHTML =
            '<div style="background:rgba(255,170,0,0.1);border:1px solid rgba(255,170,0,0.3);border-radius:6px;padding:12px;margin-bottom:12px;">' +
            '<strong style="color:#ffaa00;">&#9790; Weekend Mode</strong><br>' +
            'All LLM models will be unloaded from RAM to free resources.' +
            '</div>' +
            '<div style="font-size:0.75rem;color:var(--archie-text-secondary);line-height:1.7;">' +
            '&#8226; All agents will show as <strong>barracked</strong><br>' +
            '&#8226; No inference available until workday mode is restored<br>' +
            '&#8226; ComfyUI image generation unaffected (loads on-demand)<br>' +
            '&#8226; Frees ~90GB RAM for other tasks' +
            '</div>';
        actions.innerHTML =
            '<button class="bm-btn" onclick="closeIaaeCapacityModal()" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:var(--archie-text-secondary);">Cancel</button>' +
            '<button class="bm-btn" onclick="executeFleetModeToggle(\'weekend\')" style="background:rgba(255,170,0,0.15);border:1px solid rgba(255,170,0,0.3);color:#ffaa00;">&#9790; Activate Weekend</button>';
        modal.classList.add('active');
        return;
    }

    if (level === 'fleet-workday') {
        modal.style.setProperty('--bm-accent', '#00ff41');
        modal.style.setProperty('--bm-accent-rgb', '0,255,65');
        title.textContent = 'SWITCH TO WORKDAY MODE';
        body.innerHTML =
            '<div style="background:rgba(0,255,65,0.1);border:1px solid rgba(0,255,65,0.3);border-radius:6px;padding:12px;margin-bottom:12px;">' +
            '<strong style="color:#00ff41;">&#9788; Workday Mode</strong><br>' +
            'All agent LLM models will be warmed up and loaded into RAM.' +
            '</div>' +
            '<div style="font-size:0.75rem;color:var(--archie-text-secondary);line-height:1.7;">' +
            '&#8226; Models load sequentially by dispatch priority<br>' +
            '&#8226; Stops at 25GB free RAM (host reserve)<br>' +
            '&#8226; Full warmup takes 2\u20135 minutes<br>' +
            '&#8226; Agents become available as their model loads' +
            '</div>';
        actions.innerHTML =
            '<button class="bm-btn" onclick="closeIaaeCapacityModal()" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:var(--archie-text-secondary);">Cancel</button>' +
            '<button class="bm-btn" onclick="executeFleetModeToggle(\'workday\')" style="background:rgba(0,255,65,0.15);border:1px solid rgba(0,255,65,0.3);color:#00ff41;">&#9788; Activate Workday</button>';
        modal.classList.add('active');
        return;
    }

    modal.style.setProperty('--bm-accent', level === 'red' ? '#FF4444' : '#ffaa00');
    modal.style.setProperty('--bm-accent-rgb', level === 'red' ? '255,68,68' : '255,170,0');
    title.textContent = level === 'red' ? 'IAAE POLICY BLOCK' : 'IAAE CAPACITY WARNING';

    if (level === 'red') {
        body.innerHTML =
            '<div style="background:rgba(255,68,68,0.1);border:1px solid rgba(255,68,68,0.3);border-radius:6px;padding:12px;margin-bottom:12px;">' +
            '<strong style="color:#FF4444;">&#9888; Cannot add agent</strong><br>' +
            'RAM host reserve (' + info.reserveGB + 'GB) is being consumed.' +
            '</div>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;font-size:0.75rem;">' +
            '<span style="color:var(--archie-text-muted);">Available RAM</span><span>' + info.availableGB + 'GB</span>' +
            '<span style="color:var(--archie-text-muted);">Host Reserve</span><span style="color:#FF4444;">' + info.reserveGB + 'GB</span>' +
            '<span style="color:var(--archie-text-muted);">Models Loaded</span><span>' + info.modelsGB + 'GB</span>' +
            '<span style="color:var(--archie-text-muted);">Swap Buffer</span><span>' + info.swapUsed + '/' + info.swapTotal + 'GB used</span>' +
            '</div>' +
            '<div style="margin-top:12px;font-size:0.7rem;color:var(--archie-text-muted);border-top:1px solid rgba(255,255,255,0.06);padding-top:8px;">' +
            'Remove or barrack an existing agent to free capacity.' +
            '</div>';
        actions.innerHTML = '<button class="bm-btn" onclick="closeIaaeCapacityModal()" style="background:rgba(255,68,68,0.15);border:1px solid rgba(255,68,68,0.3);color:#FF4444;">Understood</button>';
    } else {
        body.innerHTML =
            '<div style="background:rgba(255,170,0,0.1);border:1px solid rgba(255,170,0,0.3);border-radius:6px;padding:12px;margin-bottom:12px;">' +
            '<strong style="color:#ffaa00;">&#9888; Limited RAM capacity</strong><br>' +
            'Swap buffer is partially consumed. New agent must fit in remaining space.' +
            '</div>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px 16px;font-size:0.75rem;">' +
            '<span style="color:var(--archie-text-muted);">Available RAM</span><span>' + info.availableGB + 'GB</span>' +
            '<span style="color:var(--archie-text-muted);">Usable (after reserve)</span><span>' + info.usableGB + 'GB</span>' +
            '<span style="color:var(--archie-text-muted);">Swap Buffer</span><span style="color:#ffaa00;">' + info.swapUsed + '/' + info.swapTotal + 'GB used</span>' +
            '<span style="color:var(--archie-text-muted);">Swap Remaining</span><span>' + info.swapFree + 'GB</span>' +
            '</div>' +
            '<div style="margin-top:12px;font-size:0.7rem;color:var(--archie-text-muted);border-top:1px solid rgba(255,255,255,0.06);padding-top:8px;">' +
            'New agent LLM must fit within ' + info.swapFree + 'GB swap remaining or use a cloud model.' +
            '</div>';
        actions.innerHTML =
            '<button class="bm-btn" onclick="closeIaaeCapacityModal()" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:var(--archie-text-secondary);">Cancel</button>' +
            '<button class="bm-btn" onclick="closeIaaeCapacityModal();openAgentFormModal();" style="background:rgba(255,170,0,0.15);border:1px solid rgba(255,170,0,0.3);color:#ffaa00;">Continue Anyway</button>';
    }
    modal.classList.add('active');
}
function closeIaaeCapacityModal() {
    document.getElementById('iaae-capacity-modal').classList.remove('active');
}

// === Fleet Mode Toggle (Workday / Weekend) ===
function updateFleetModeButton(mode) {
    var btn = document.getElementById('btn-fleet-mode');
    if (!btn) return;
    btn.classList.remove('workday', 'weekend', 'transitioning');
    btn.classList.add(mode);
}

function toggleFleetMode() {
    var btn = document.getElementById('btn-fleet-mode');
    var current = btn.classList.contains('weekend') ? 'weekend' : 'workday';
    var next = current === 'workday' ? 'weekend' : 'workday';
    showIaaeCapacityModal(next === 'weekend' ? 'fleet-weekend' : 'fleet-workday', {next: next});
}

function executeFleetModeToggle(mode) {
    var btn = document.getElementById('btn-fleet-mode');
    btn.classList.add('transitioning');
    closeIaaeCapacityModal();

    fetch('/tools/bridge/api/bridge/fleet-mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            updateFleetModeButton(mode);
            // Refresh manifest after delay to show changes
            setTimeout(function() { loadCrewManifest(); }, mode === 'weekend' ? 5000 : 15000);
        } else {
            alert('Failed: ' + (data.error || 'unknown'));
            btn.classList.remove('transitioning');
        }
    })
    .catch(function(err) {
        alert('Error: ' + err);
        btn.classList.remove('transitioning');
    });
}

// === Mobile Controls Toggle ===
function toggleBridgeControls() {
    var controls = document.getElementById('bridgeHeaderControls');
    var toggle = document.getElementById('bridgeControlsToggle');
    if (!controls || !toggle) return;
    var isVisible = controls.classList.toggle('mobile-visible');
    toggle.classList.toggle('expanded', isVisible);
}

// === Overview Tab Data ===
function loadOverviewData() {
    // 1. AI Bridge Status card (live Ollama + external providers)
    fetch('/tools/bridge/api/llm/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById('overviewAiStatus');
            if (!el) return;
            if (!data.success) {
                el.innerHTML = '<span class="briefing-muted">Unable to load</span>';
                return;
            }
            // Helper: sanitize text for safe DOM insertion
            function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
            var html = '';
            // Ollama status + routing mode header
            var ollamaDot = data.ollama_status === 'online' ? '🟢' : '🔴';
            var mode = esc(String(data.routing_mode || 'full'));
            html += '<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.1);margin-bottom:4px;">';
            html += '<span>' + ollamaDot + ' Ollama</span>';
            html += '<span style="color:var(--archie-cyan);font-size:0.8em;text-transform:uppercase;">' + mode + '</span>';
            html += '</div>';
            // Build VRAM lookup from loaded_models (for active memory usage)
            var vramMap = {};
            (data.loaded_models || []).forEach(function(m) {
                var sizeMB = m.vram ? Math.round(m.vram / 1048576) : Math.round((m.size || 0) / 1048576);
                vramMap[m.name] = sizeMB;
            });
            // Helper: format bytes to human-readable size
            function fmtSize(bytes) {
                if (!bytes || bytes < 1024) return '';
                var gb = bytes / (1024 * 1024 * 1024);
                if (gb >= 1) return gb.toFixed(1) + ' GB';
                return Math.round(bytes / (1024 * 1024)) + ' MB';
            }
            // Unified model list — assigned (green) first, then unassigned (gray)
            var allModels = (data.models || []).sort(function(a, b) {
                if (a.assigned && !b.assigned) return -1;
                if (!a.assigned && b.assigned) return 1;
                return a.name.localeCompare(b.name);
            });
            var assignedCount = allModels.filter(function(m) { return m.assigned; }).length;
            var unassignedCount = allModels.length - assignedCount;
            html += '<div style="font-size:0.7rem;color:var(--archie-text-tertiary);padding:2px 0 4px;border-bottom:1px solid rgba(255,255,255,0.06);margin-bottom:4px;">';
            html += 'Models &mdash; <span style="color:#00ff41;">' + assignedCount + ' assigned</span>, ' + unassignedCount + ' idle';
            html += '</div>';
            html += '<div style="max-height:160px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.15) transparent;">';
            allModels.forEach(function(m) {
                var rawName = String(m.name || 'unknown');
                var parts = rawName.split(':');
                var name = esc(parts[0]) + (parts[1] && parts[1] !== 'latest' ? '<span style="color:var(--archie-text-tertiary);font-size:0.85em;">:' + esc(parts[1]) + '</span>' : '');
                var isAssigned = m.assigned;
                var nameColor = isAssigned ? '#00ff41' : 'var(--archie-text-secondary)';
                var label = isAssigned ? 'assigned' : 'idle';
                var sizeStr = fmtSize(m.size || 0);
                html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:0.8em;">';
                html += '<span style="color:' + nameColor + ';">&#9679; ' + name + '</span>';
                html += '<span style="color:var(--archie-text-tertiary);font-size:0.85em;">' + (sizeStr ? sizeStr + ' &middot; ' : '') + label + '</span>';
                html += '</div>';
            });
            html += '</div>';
            // External API providers (paid services with API keys)
            var extProviders = (data.external || []).filter(function(ext) {
                return ext.status !== 'no_key';
            });
            if (extProviders.length > 0) {
                html += '<div style="font-size:0.7rem;color:var(--archie-text-tertiary);padding:4px 0 4px;border-top:1px solid rgba(255,255,255,0.06);margin-top:4px;">API Providers</div>';
            }
            extProviders.forEach(function(ext) {
                var dot = ext.status === 'active' ? '🟢' : '🟡';
                var extName = esc(String(ext.name || 'Unknown'));
                var extStatus = esc(String(ext.status || 'unknown').replace('_', ' '));
                var budgetStr = '';
                if (ext.budget_pct !== undefined && ext.budget_pct !== null) {
                    budgetStr = ' (' + parseFloat(ext.budget_pct).toFixed(1) + '%)';
                }
                html += '<div style="display:flex;justify-content:space-between;padding:2px 0;">';
                html += '<span>' + dot + ' ' + extName + '</span>';
                html += '<span style="color:var(--archie-text-tertiary);font-size:0.85em;">' + extStatus + budgetStr + '</span>';
                html += '</div>';
            });
            el.innerHTML = html;
        }).catch(function() {
            var el = document.getElementById('overviewAiStatus');
            if (el) el.innerHTML = '<span class="briefing-muted">Unable to load</span>';
        });

    // 2. Station Summary card
    fetch('/tools/bridge/api/stations')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById('overviewStationSummary');
            if (!el) return;
            var stations = Array.isArray(data) ? data : (data.stations || []);
            var totalAgents = 0;
            stations.forEach(function(s) {
                totalAgents += (s.assigned_agents || s.agents || []).length;
            });
            // Note: innerHTML used here with integer-only values from internal API (no user input)
            var html = '<div style="display:flex;justify-content:space-between;padding:3px 0;">';
            html += '<span>Active Stations</span><span style="color:var(--archie-cyan)">' + parseInt(stations.length) + '</span></div>';
            html += '<div style="display:flex;justify-content:space-between;padding:3px 0;">';
            html += '<span>Assigned Agents</span><span style="color:var(--archie-cyan)">' + parseInt(totalAgents) + '</span></div>';
            el.innerHTML = html;
        }).catch(function() {
            var el = document.getElementById('overviewStationSummary');
            if (el) el.textContent = 'Unable to load';
        });

    // 2b. HUD pod: Agent Utilization (real 24h activity rate)
    fetch('/tools/bridge/api/agent-utilization')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var utilEl = document.getElementById('hudAgentUtil');
            if (utilEl && data.success) {
                utilEl.textContent = data.utilization_pct + '%';
            }
        }).catch(function() {});

    // 3. IAAE Health card (real welfare + workload data)
    Promise.all([
        fetch('/tools/bridge/api/agents/welfare').then(function(r) { return r.json(); }),
        fetch('/tools/bridge/api/agents/workload').then(function(r) { return r.json(); })
    ]).then(function(results) {
        var welfareData = results[0];
        var workloadData = results[1];
        var el = document.getElementById('overviewIAAE');
        var iaaeEl = document.getElementById('hudIAAEScore');
        if (!el) return;

        if (!welfareData.success) {
            el.textContent = 'Unable to load';
            if (iaaeEl) iaaeEl.textContent = 'N/A';
            return;
        }

        var fh = welfareData.fleet_health || {};
        // HUD pod
        if (iaaeEl) {
            iaaeEl.textContent = fh.compliance_pct !== null && fh.compliance_pct !== undefined ? fh.compliance_pct + '%' : 'N/A';
        }

        // Build rich IAAE card via DOM
        el.textContent = '';

        // Helper: make a gauge bar
        function makeGauge(label, pct, color) {
            var wrap = document.createElement('div');
            wrap.style.cssText = 'margin-bottom:6px;';
            var top = document.createElement('div');
            top.style.cssText = 'display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;';
            var lbl = document.createElement('span');
            lbl.textContent = label;
            var val = document.createElement('span');
            val.textContent = pct + '%';
            val.style.color = color;
            top.appendChild(lbl);
            top.appendChild(val);
            wrap.appendChild(top);
            var bar = document.createElement('div');
            bar.style.cssText = 'height:5px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden;';
            var fill = document.createElement('div');
            fill.style.cssText = 'height:100%;border-radius:3px;width:' + Math.min(pct, 100) + '%;background:' + color + ';';
            bar.appendChild(fill);
            wrap.appendChild(bar);
            return wrap;
        }

        // Fleet stress
        var stressPct = fh.avg_stress !== null ? Math.round(fh.avg_stress * 100) : 0;
        var stressColor = stressPct <= 40 ? '#00ff41' : stressPct <= 70 ? '#ffaa00' : '#ff4444';
        el.appendChild(makeGauge('Fleet Stress', stressPct, stressColor));

        // Fleet energy
        var energyPct = fh.avg_energy !== null ? Math.round(fh.avg_energy * 100) : 0;
        var energyColor = energyPct >= 60 ? '#00ff41' : energyPct >= 30 ? '#ffaa00' : '#ff4444';
        el.appendChild(makeGauge('Fleet Energy', energyPct, energyColor));

        // Stats row
        var stats = document.createElement('div');
        stats.style.cssText = 'display:flex;gap:10px;font-size:0.7rem;margin-bottom:6px;';
        var riskSpan = document.createElement('span');
        var riskCount = fh.agents_at_risk || 0;
        riskSpan.innerHTML = 'At Risk: <span style="color:' + (riskCount > 0 ? '#ff4444' : '#00ff41') + ';">' + parseInt(riskCount) + '</span>';
        riskSpan.style.cursor = 'pointer';
        riskSpan.onclick = function() { switchBridgeTab('crew'); };
        stats.appendChild(riskSpan);
        var restSpan = document.createElement('span');
        restSpan.textContent = 'Resting: ' + parseInt(fh.agents_resting || 0);
        stats.appendChild(restSpan);
        var govSpan = document.createElement('span');
        govSpan.textContent = 'Events: ' + parseInt(fh.total_governance_events || 0);
        stats.appendChild(govSpan);
        el.appendChild(stats);

        // Workload mini-bars (top agents from workload data)
        if (workloadData.success && workloadData.agents && workloadData.agents.length > 0) {
            var wLabel = document.createElement('div');
            wLabel.style.cssText = 'font-size:0.65rem;color:var(--archie-text-muted);margin-bottom:3px;';
            wLabel.textContent = 'Agent Workload (24h)';
            el.appendChild(wLabel);

            var topAgents = workloadData.agents.slice(0, 8);
            topAgents.forEach(function(ag) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:2px;font-size:0.65rem;';
                var nm = document.createElement('span');
                nm.style.cssText = 'width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
                nm.textContent = ag.first_name || ag.name;
                nm.title = ag.name;
                row.appendChild(nm);
                var barWrap = document.createElement('div');
                barWrap.style.cssText = 'flex:1;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;';
                var barFill = document.createElement('div');
                var wPct = ag.workload_pct || 0;
                var wCol = wPct < 60 ? '#00ff41' : wPct < 80 ? '#ffaa00' : '#ff4444';
                barFill.style.cssText = 'height:100%;border-radius:2px;width:' + Math.min(wPct, 100) + '%;background:' + wCol + ';';
                barWrap.appendChild(barFill);
                row.appendChild(barWrap);
                var pctLabel = document.createElement('span');
                pctLabel.style.cssText = 'width:28px;text-align:right;color:' + wCol + ';';
                pctLabel.textContent = Math.round(wPct) + '%';
                row.appendChild(pctLabel);
                el.appendChild(row);
            });
        }
    }).catch(function() {
        var el = document.getElementById('overviewIAAE');
        if (el) el.textContent = 'IAAE Governance Active';
        var iaaeEl = document.getElementById('hudIAAEScore');
        if (iaaeEl) iaaeEl.textContent = 'N/A';
    });

    // 3b. Vigil's Log (enforcement events)
    fetch('/tools/bridge/api/iaae/enforcement-log')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById('overviewVigilLog');
            if (!el) return;
            if (!data.success || !data.events || data.events.length === 0) {
                el.textContent = '';
                var msg = document.createElement('div');
                msg.style.cssText = 'font-size:0.75rem;color:var(--archie-text-muted);padding:4px 0;';
                msg.textContent = 'No interventions needed \u2014 all agents within healthy parameters';
                el.appendChild(msg);
                return;
            }
            el.textContent = '';
            var sevColors = { critical: '#ff4444', warning: '#ffaa00', info: '#00ff41' };
            var sevIcons = { critical: '\u26a0', warning: '\u25cf', info: '\u25cf' };
            var catIcons = { welfare: '\u2764', governance: '\u26a1', autonomy: '\u26a1', archie_wellness: '\u2606', dispatch: '\u2716' };
            var shown = data.events.slice(0, 7);
            shown.forEach(function(ev) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.7rem;gap:6px;min-width:0;';
                var left = document.createElement('div');
                left.style.cssText = 'display:flex;align-items:center;gap:4px;overflow:hidden;min-width:0;flex:1;';
                var color = sevColors[ev.severity] || '#888';
                var icon = document.createElement('span');
                icon.style.cssText = 'color:' + color + ';flex-shrink:0;';
                icon.textContent = catIcons[ev.event_category] || sevIcons[ev.severity] || '\u25cf';
                left.appendChild(icon);
                if (ev.agent_name) {
                    var nameEl = document.createElement('span');
                    nameEl.style.cssText = 'color:var(--archie-cyan);white-space:nowrap;flex-shrink:0;';
                    nameEl.textContent = ev.agent_name;
                    left.appendChild(nameEl);
                }
                var desc = document.createElement('span');
                desc.style.cssText = 'color:' + color + ';overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;flex:1;';
                desc.textContent = ev.label || 'event';
                left.appendChild(desc);
                row.appendChild(left);
                if (ev.timestamp) {
                    var ts = document.createElement('span');
                    ts.style.cssText = 'color:var(--archie-text-tertiary);font-size:0.65rem;white-space:nowrap;flex-shrink:0;';
                    ts.textContent = ArchieTime.time(ev.timestamp);
                    row.appendChild(ts);
                }
                el.appendChild(row);
            });
            if (data.total > 7) {
                var more = document.createElement('a');
                more.href = '#';
                more.style.cssText = 'display:block;font-size:0.65rem;color:var(--archie-text-muted);padding-top:3px;text-decoration:none;cursor:pointer;';
                more.textContent = '+ ' + (data.total - 7) + ' more events';
                more.addEventListener('click', function(e) { e.preventDefault(); openVigilLogModal(); });
                el.appendChild(more);
            }
        }).catch(function() {
            var el = document.getElementById('overviewVigilLog');
            if (el) el.textContent = 'IAAE Governance Active';
        });

    // 4. Mini Activity Feed (last 5 dispatches)
    fetch('/tools/bridge/api/dispatch/activity-history')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById('overviewMiniActivity');
            if (!el) return;
            var items = Array.isArray(data) ? data : (data.activities || data.history || []);
            if (items.length === 0) {
                el.innerHTML = '<span class="briefing-muted">No recent activity</span>';
                return;
            }
            var html = '';
            items.slice(0, 8).forEach(function(item) {
                var agent = item.agent_name || 'Unknown';
                var module = item.module_source || '';
                var cap = item.capability || item.task_type || '';
                var detail = module + (cap ? ' / ' + cap : '');
                var dot = item.success === false ? '🔴' : '🟢';
                // Relative time (timestamps are UTC)
                var timeAgo = '';
                if (item.created_at) {
                    var diff = Date.now() - new Date(item.created_at).getTime();
                    var mins = Math.max(0, Math.floor(diff / 60000));
                    if (mins < 1) timeAgo = 'now';
                    else if (mins < 60) timeAgo = mins + 'm';
                    else if (mins < 1440) timeAgo = Math.floor(mins / 60) + 'h';
                    else timeAgo = Math.floor(mins / 1440) + 'd';
                }
                html += '<div style="display:flex;align-items:center;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);gap:6px;font-size:0.8em">';
                html += '<span style="flex-shrink:0">' + dot + '</span>';
                html += '<span style="color:var(--archie-cyan);white-space:nowrap;min-width:60px">' + agent + '</span>';
                html += '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;color:var(--archie-text-tertiary);font-size:0.85em">' + detail + '</span>';
                if (timeAgo) html += '<span style="color:var(--archie-text-muted);font-size:0.8em;white-space:nowrap">' + timeAgo + '</span>';
                html += '</div>';
            });
            el.innerHTML = html;
        }).catch(function() {
            var el = document.getElementById('overviewMiniActivity');
            if (el) el.innerHTML = '<span class="briefing-muted">Unable to load activity</span>';
        });

    // 5. HUD pod: Throughput (24h)
    fetch('/tools/bridge/api/traffic')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                var el = document.getElementById('hudBridgeThroughput');
                var unitEl = document.getElementById('hudThroughputUnit');
                var total = data.total_24h || 0;
                var rpm = data.requests_per_minute || 0;
                if (el) el.textContent = total;
                if (unitEl) unitEl.textContent = 'tasks · ' + rpm + ' req/min';
            }
        }).catch(function() {});

    // 6. HUD pod: Model count (live Ollama)
    fetch('/tools/bridge/api/models/live')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var el = document.getElementById('hudModelCount');
            if (el && data.success) el.textContent = data.count;
        }).catch(function() {});
}

// === Vigil's Log Modal (paginated full view) ===
var _vigilState = { page: 1, perPage: 20, filter: 'all', totalPages: 1 };

function openVigilLogModal() {
    _vigilState.page = 1;
    _vigilState.filter = 'all';
    document.querySelectorAll('.vigil-filter-btn').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-filter') === 'all');
    });
    document.getElementById('vigil-log-modal').classList.add('active');
    loadVigilLogPage();
}

function closeVigilLogModal() {
    document.getElementById('vigil-log-modal').classList.remove('active');
}

function filterVigilLog(cat) {
    _vigilState.filter = cat;
    _vigilState.page = 1;
    document.querySelectorAll('.vigil-filter-btn').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-filter') === cat);
    });
    loadVigilLogPage();
}

function vigilLogPage(delta) {
    _vigilState.page = Math.max(1, Math.min(_vigilState.totalPages, _vigilState.page + delta));
    loadVigilLogPage();
}

function _vigilMakeText(tag, text, style) {
    var el = document.createElement(tag);
    el.textContent = text;
    if (style) el.style.cssText = style;
    return el;
}

function loadVigilLogPage() {
    var body = document.getElementById('vigil-log-modal-body');
    body.textContent = '';
    body.appendChild(_vigilMakeText('div', 'Loading...', 'text-align:center;color:var(--archie-text-muted);padding:2rem;'));

    var url = '/tools/bridge/api/iaae/enforcement-log-full?page=' + _vigilState.page +
              '&per_page=' + _vigilState.perPage +
              '&filter=' + _vigilState.filter;
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            body.textContent = '';
            if (!data.success) {
                body.appendChild(_vigilMakeText('div', 'Error loading log', 'color:#ff4444;padding:1rem;'));
                return;
            }
            _vigilState.totalPages = data.total_pages || 1;
            var events = data.events || [];
            if (events.length === 0) {
                body.appendChild(_vigilMakeText('div', 'No events found', 'text-align:center;color:var(--archie-text-muted);padding:2rem;'));
                updateVigilPagination(data);
                return;
            }
            var sevColors = { critical: '#ff4444', warning: '#ffaa00', info: '#00ff41' };
            var catLabels = { welfare: 'Welfare', governance: 'Governance', autonomy: 'Autonomy', archie_wellness: 'ARCHIE', dispatch: 'Dispatch' };

            var table = document.createElement('table');
            table.className = 'vigil-log-table';
            var thead = document.createElement('thead');
            var headerRow = document.createElement('tr');
            ['', 'Time', 'Category', 'Agent', 'Details'].forEach(function(h) {
                headerRow.appendChild(_vigilMakeText('th', h, ''));
            });
            thead.appendChild(headerRow);
            table.appendChild(thead);

            var tbody = document.createElement('tbody');
            events.forEach(function(ev) {
                var color = sevColors[ev.severity] || '#888';
                var tr = document.createElement('tr');

                // Severity dot
                var tdDot = document.createElement('td');
                var dot = document.createElement('span');
                dot.className = 'vigil-sev-dot vigil-sev-' + (ev.severity || 'info');
                tdDot.appendChild(dot);
                tr.appendChild(tdDot);

                // Time
                var ts = '';
                if (ev.timestamp) {
                    ts = ArchieTime.format(ev.timestamp, 'short');
                }
                tr.appendChild(_vigilMakeText('td', ts, 'white-space:nowrap;font-size:0.7rem;color:var(--archie-text-tertiary);'));

                // Category
                tr.appendChild(_vigilMakeText('td', catLabels[ev.event_category] || ev.event_category || '\u2014', 'font-size:0.7rem;'));

                // Agent
                tr.appendChild(_vigilMakeText('td', ev.agent_name || '\u2014', 'color:var(--archie-cyan);white-space:nowrap;'));

                // Details
                tr.appendChild(_vigilMakeText('td', ev.label || '', 'max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:' + color + ';'));

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            body.appendChild(table);
            updateVigilPagination(data);
        })
        .catch(function() {
            body.textContent = '';
            body.appendChild(_vigilMakeText('div', 'Failed to load enforcement log', 'color:#ff4444;padding:1rem;'));
        });
}

function updateVigilPagination(data) {
    var info = document.getElementById('vigil-log-page-info');
    var prevBtn = document.getElementById('vigil-prev-btn');
    var nextBtn = document.getElementById('vigil-next-btn');
    if (info) info.textContent = 'Page ' + (data.page || 1) + ' of ' + (data.total_pages || 1) + ' (' + (data.total || 0) + ' events)';
    if (prevBtn) prevBtn.disabled = (data.page || 1) <= 1;
    if (nextBtn) nextBtn.disabled = (data.page || 1) >= (data.total_pages || 1);
}

// Close vigil modal on overlay click
document.getElementById('vigil-log-modal').addEventListener('click', function(e) {
    if (e.target === this) closeVigilLogModal();
});

// === Tab Navigation ===
function switchBridgeTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.bridge-tab').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    // Update panels
    document.querySelectorAll('.bridge-tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.dataset.panel === tabName);
    });
    // Toggle stations-active on container (hides header on stations tab)
    document.querySelector('.bridge-container').classList.toggle('stations-active', tabName === 'stations');
    // Update URL hash
    history.replaceState(null, '', '#' + tabName);
    // Trigger data load for the tab if needed
    if (tabName === 'overview') loadOverviewData();
    if (tabName === 'stations') {
        loadStations();
        // Trigger warp-in intro + entrance animations
        triggerWarpIntro();
    }
    if (tabName === 'dispatch') { startDispatchRefresh(); } else { stopDispatchRefresh(); }
    if (tabName === 'crew') { startCrewRefresh(); } else { stopCrewRefresh(); }
    if (tabName === 'network') { loadNodes(); loadModelAvailability(); loadMeshLoans(); loadMeshLearning(); loadMeshAvailableAgents(); }
    // Re-render Lucide icons for any new content
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Restore tab from URL hash on page load
(function() {
    var hash = window.location.hash.replace('#', '');
    var validTabs = ['stations', 'overview', 'dispatch', 'crew', 'network'];
    if (hash && validTabs.indexOf(hash) !== -1) {
        setTimeout(function() { switchBridgeTab(hash); }, 100);
    } else {
        // Default: load stations tab data (warp-in animation)
        setTimeout(function() { switchBridgeTab('stations'); }, 100);
    }
})();

// === i18n helper ===
function _t(key, fallback) {
    if (window.archieI18n && typeof archieI18n.t === 'function') {
        return archieI18n.t(key, fallback);
    }
    return fallback;
}

// === Routing Mode Toggle ===
async function loadRoutingMode() {
    try {
        const res = await fetch('/tools/bridge/api/routing-mode');
        const data = await res.json();
        if (data.success) {
            document.querySelectorAll('.routing-btn').forEach(function(btn) {
                btn.classList.toggle('active', btn.dataset.mode === data.routing_mode);
            });
        }
    } catch (e) { console.error('Failed to load routing mode:', e); }
}

document.querySelectorAll('.routing-btn').forEach(function(btn) {
    btn.addEventListener('click', async function() {
        var mode = this.dataset.mode;
        try {
            var res = await fetch('/tools/bridge/api/routing-mode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({routing_mode: mode}),
            });
            var data = await res.json();
            if (data.success) {
                document.querySelectorAll('.routing-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                document.getElementById('routingModeStatus').textContent = 'Mode: ' + mode;
            }
        } catch (e) { console.error('Failed to set routing mode:', e); }
    });
});

loadRoutingMode();

// === Escalation Mode Toggle ===
async function loadEscalationMode() {
    try {
        const res = await fetch('/tools/bridge/api/escalation-mode');
        const data = await res.json();
        if (data.success) {
            document.querySelectorAll('.escalation-btn').forEach(function(btn) {
                btn.classList.toggle('active', btn.dataset.mode === data.escalation_mode);
            });
        }
    } catch (e) { console.error('Failed to load escalation mode:', e); }
}

document.querySelectorAll('.escalation-btn').forEach(function(btn) {
    btn.addEventListener('click', async function() {
        var mode = this.dataset.mode;
        try {
            var res = await fetch('/tools/bridge/api/escalation-mode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({escalation_mode: mode}),
            });
            var data = await res.json();
            if (data.success) {
                document.querySelectorAll('.escalation-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                document.getElementById('escalationModeStatus').textContent = 'Mode: ' + mode;
            }
        } catch (e) { console.error('Failed to set escalation mode:', e); }
    });
});

loadEscalationMode();

// ============================================================================
// A.R.C.H.I.E. BRIDGE - JavaScript Controller
// ============================================================================

// Module info mapping for icons
const MODULE_INFO = {
    // CREATION TOOLS
    'project_builder': { icon: 'building-2', route: '/tools/project-builder', name: 'Project Builder' },
    'game_studio': { icon: 'gamepad-2', route: '/tools/game-studio', name: 'Game Studio' },
    'media_studio': { icon: 'video', route: '/tools/media-studio', name: 'Media Studio' },
    'content_studio': { icon: 'pen-tool', route: '/tools/content-studio', name: 'Content Studio' },
    'app_builder': { icon: 'smartphone', route: '/tools/app-builder', name: 'App Builder' },
    'website_builder': { icon: 'globe-2', route: '/tools/website-builder', name: 'Website Builder' },
    'website_designer': { icon: 'globe', route: '/tools/website-designer', name: 'Website Designer' },
    'book_builder': { icon: 'book-open', route: '/tools/book-builder', name: 'Book Builder' },
    'picture_generation': { icon: 'image', route: '/tools/picture-generation', name: 'Picture Generation' },
    'video_generation': { icon: 'film', route: '/tools/video-generation', name: 'Video Generation' },
    'story_generation': { icon: 'scroll', route: '/tools/story-generation', name: 'Story Generation' },

    // DEVELOPMENT TOOLS
    'code_editor': { icon: 'code-2', route: '/tools/code-editor', name: 'Code Editor' },
    'dev_pipeline': { icon: 'workflow', route: '/tools/dev-pipeline', name: 'Dev Pipeline' },
    'blueprint': { icon: 'layout-dashboard', route: '/tools/blueprint', name: 'Blueprint' },
    'testing_suite': { icon: 'test-tube-2', route: '/tools/testing-suite', name: 'Testing Suite' },
    'cursor_integration': { icon: 'mouse-pointer', route: '/tools/cursor-integration', name: 'Cursor Integration' },
    'fine_tuning': { icon: 'sliders', route: '/tools/fine-tuning', name: 'Fine Tuning' },
    'api_docs': { icon: 'file-json', route: '/tools/api-docs', name: 'API Documentation' },

    // BUSINESS TOOLS
    'crm': { icon: 'users', route: '/tools/crm', name: 'CRM' },
    'invoicing': { icon: 'receipt', route: '/tools/invoicing', name: 'Invoicing' },
    'scheduler': { icon: 'calendar', route: '/tools/scheduler', name: 'Scheduler' },
    'email_manager': { icon: 'mail', route: '/tools/email-manager', name: 'Email Manager' },
    'automations': { icon: 'workflow', route: '/tools/automations', name: 'Automations' },
    'google_workspace': { icon: 'mail-check', route: '/tools/google-workspace', name: 'Google Workspace' },
    'task_planner': { icon: 'check-square', route: '/tools/task-planner', name: 'Task Planner' },
    'site_manager': { icon: 'layout', route: '/tools/site-manager', name: 'Site Manager' },
    'call_center': { icon: 'phone', route: '/tools/call-center', name: 'Call Center' },
    'store_builder': { icon: 'shopping-cart', route: '/tools/store-builder', name: 'Store Builder' },
    'social_media': { icon: 'share-2', route: '/tools/social-media', name: 'Social Media' },
    'github_manager': { icon: 'github', route: '/tools/github-manager', name: 'GitHub Manager' },
    'analytics_dashboard': { icon: 'bar-chart-3', route: '/tools/analytics', name: 'Analytics Dashboard' },

    // STANDALONE APPS
    'archie_chat': { icon: 'message-circle', route: '/tools/archie-chat', name: 'A.R.C.H.I.E. Chat' },
    'archie_pool': { icon: 'droplets', route: '/tools/archie-pool', name: 'Archie Pool' },
    'pool_management': { icon: 'waves', route: '/tools/pool-management', name: 'Pool Management' },
    'doc': { icon: 'file-text', route: '/tools/doc', name: 'DOC Medical' },
    'therapy': { icon: 'heart-pulse', route: '/tools/therapy', name: 'Therapy' },
    'fitness': { icon: 'dumbbell', route: '/tools/fitness', name: 'Fitness' },
    'stockbot': { icon: 'trending-up', route: '/tools/stockbot', name: 'StockBot' },

    // ADMIN OPS
    'team_management': { icon: 'users-2', route: '/tools/team-management', name: 'Team Management' },
    // hr_management merged into team_management - 2026-02-03
    'consciousness': { icon: 'brain', route: '/tools/consciousness', name: 'Consciousness' },
    'obsidian_vault': { icon: 'book-open', route: '/tools/consciousness', name: 'Obsidian Vault' },

    // ADMIN TOOLS
    'admin_tools': { icon: 'settings', route: '/tools/admin', name: 'Admin Tools' },
    'general_tasks': { icon: 'list-todo', route: '/tools/admin', name: 'General Tasks' },
    'backup_manager': { icon: 'hard-drive', route: '/tools/backup-manager', name: 'Backup Manager' },
    'security_network': { icon: 'shield', route: '/tools/security-network', name: 'Security & Network' },
    'account_center': { icon: 'user-cog', route: '/tools/account-center', name: 'Account Center' },
    'automation_services': { icon: 'cog', route: '/tools/automations', name: 'Automation Services' },

    // INFRASTRUCTURE
    'network_monitor': { icon: 'activity', route: '/tools/network-monitor', name: 'Network Monitor' },
    'server_dashboard': { icon: 'server', route: '/tools/server-dashboard', name: 'Server Dashboard' },
    'home_automation': { icon: 'home', route: '/tools/home-automation', name: 'Home Automation' },

    // DOCUMENTATION
    'docs_manager': { icon: 'file-text', route: '/tools/docs-manager', name: 'Docs Manager' },
    'technical_writing': { icon: 'pencil', route: '/tools/technical-writing', name: 'Technical Writing' },

    // QA
    'qa_dashboard': { icon: 'clipboard-check', route: '/tools/qa-dashboard', name: 'QA Dashboard' },
    'test_runner': { icon: 'play-circle', route: '/tools/test-runner', name: 'Test Runner' },

    // RESEARCH
    'web_scraper': { icon: 'globe-2', route: '/tools/web-scraper', name: 'Web Scraper' },
    'research_agent': { icon: 'search', route: '/tools/research', name: 'Research Agent' },
    'data_collector': { icon: 'database', route: '/tools/data-collector', name: 'Data Collector' },
};

// Station color mapping
const STATION_COLORS = {
    'COMMAND': '#FFD700',
    'CONSCIOUSNESS': '#FF00FF',
    'HR': '#10B981',
    'RND': '#8B5CF6',
    'RND_CORE': '#8B5CF6',
    'RND_AI': '#06B6D4',
    'ENGINEERING': '#0EA5E9',
    'ENGINEERING_BUILD': '#0EA5E9',
    'ENGINEERING_CODE': '#06B6D4',
    'OPERATIONS': '#FFAA00',
    'OPERATIONS_CORE': '#FFAA00',
    'OPERATIONS_AUTO': '#F59E0B',
    'CREATIVE': '#F472B6',
    'CREATIVE_MEDIA': '#F472B6',
    'CREATIVE_CONTENT': '#EC4899',
    'SECURITY': '#EF4444',
    'MEDICAL': '#84CC16',
    'AWAY_TEAM': '#F59E0B',
    'INFRASTRUCTURE': '#3B82F6',
    'FINANCE': '#A855F7',
    'DOCUMENTATION': '#8B5CF6',
    'QA': '#10B981',
    'ADMIN': '#6366F1',
    'SUPPORT': '#F43F5E'
};

// ── Isometric zone grouping (10 active stations → 10 zones) ──
const ISOMETRIC_ZONE_MAP = {
    'COMMAND':       { stations: ['COMMAND'],             color: '#FFD700', label: 'Command',       abbr: 'CMD' },
    'CREATIVE':      { stations: ['CREATIVE'],            color: '#FF69B4', label: 'Creative',      abbr: 'CRE' },
    'ENGINEERING':   { stations: ['ENGINEERING'],         color: '#32CD32', label: 'Engineering',   abbr: 'ENG' },
    'OPERATIONS':    { stations: ['OPERATIONS'],          color: '#FF8C00', label: 'Operations',    abbr: 'OPS' },
    'ANALYTICS':     { stations: ['ANALYTICS'],           color: '#00CED1', label: 'Analytics',     abbr: 'ANA' },
    'RESEARCH':      { stations: ['RESEARCH'],            color: '#6495ED', label: 'Research',      abbr: 'RES' },
    'DOCUMENTATION': { stations: ['DOCUMENTATION'],       color: '#8B5CF6', label: 'Documentation', abbr: 'DOC' },
    'RND_AI':        { stations: ['RND_AI'],              color: '#06B6D4', label: 'R&D - AI',      abbr: 'R&D' },
    'SECURITY':      { stations: ['SECURITY'],            color: '#F43F5E', label: 'Security',      abbr: 'SEC' },
    'QA':            { stations: ['QA'],                  color: '#10B981', label: 'QA',            abbr: 'QA'  }
};

// Reverse lookup: station code → zone name
const STATION_TO_ISO_ZONE = {};
for (const [zoneName, zoneInfo] of Object.entries(ISOMETRIC_ZONE_MAP)) {
    for (const sc of zoneInfo.stations) {
        STATION_TO_ISO_ZONE[sc] = zoneName;
    }
}

// ── Cloud contractor provider branding ──
const CLOUD_PROVIDER_BRANDS = {
    'minimax':   { color: '#7C3AED', rgb: '124,58,237',  label: 'MiniMax' },
    'qwen':      { color: '#6366F1', rgb: '99,102,241',  label: 'Qwen' },
    'groq':      { color: '#F97316', rgb: '249,115,22',  label: 'Groq' },
    'cerebras':  { color: '#3B82F6', rgb: '59,130,246',  label: 'Cerebras' },
    'cohere':    { color: '#06B6D4', rgb: '6,182,212',   label: 'Cohere' },
    'gemini':    { color: '#4285F4', rgb: '66,133,244',  label: 'Gemini' },
    'mistral':   { color: '#FF6B35', rgb: '255,107,53',  label: 'Mistral' },
    'openai':    { color: '#10A37F', rgb: '16,163,127',  label: 'OpenAI' },
    'anthropic': { color: '#D4A26E', rgb: '212,162,110', label: 'Anthropic' },
    'ollama':    { color: '#9333EA', rgb: '147,51,234',  label: 'Ollama Cloud' },
};
function getProviderBrand(agentName) {
    // Parse cloud model from agent_name like "CLOUD→minimax-m2.5:cloud"
    if (!agentName) return null;
    const name = agentName.toLowerCase();
    for (const [key, brand] of Object.entries(CLOUD_PROVIDER_BRANDS)) {
        if (name.includes(key)) return brand;
    }
    // Fallback for any cloud model
    if (name.startsWith('cloud')) return { color: '#9333EA', rgb: '147,51,234', label: 'Cloud' };
    return null;
}

// Global state
let allStations = [];
let stationNodeCoverage = {}; // Maps station_id to node data

// ============================================================================
// STATUS BAR
// ============================================================================

// Helper to update both status bar + ops strip elements by ID pair
function _setStatusText(primaryId, opsId, text) {
    var el = document.getElementById(primaryId);
    if (el) el.textContent = text;
    var opsEl = document.getElementById(opsId);
    if (opsEl) opsEl.textContent = text;
}

function updateStatusBar() {
    // Routing mode - read from existing header controls state
    var activeBtn = document.querySelector('.routing-btn.active');
    if (activeBtn) {
        _setStatusText('statusRoutingMode', 'opsRoutingMode', activeBtn.textContent.trim());
    }

    // Clock
    var now = new Date();
    var timeStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    _setStatusText('statusBarClock', 'opsBarClock', timeStr);
}

function loadStatusBarStats() {
    fetch('/tools/bridge/api/traffic')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                var el = document.getElementById('statusInteractions');
                if (el) el.textContent = data.total_24h || 0;
            }
        }).catch(function() {});

    fetch('/tools/bridge/api/agents')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success !== false) {
                var agents = Array.isArray(data) ? data : (data.agents || []);
                var active = agents.filter(function(a) { return a.status === 'active'; });
                _setStatusText('statusAgentCount', 'opsAgentCount', active.length);
            }
        }).catch(function() {});
}

// ============================================================================
// MISSION PROFILES
// ============================================================================

function loadMissionBanner() {
    fetch('/tools/bridge/api/mission/active').then(function(r){return r.json();}).then(function(d) {
        if (!d.success || !d.profile) return;
        var banner = document.getElementById('mission-banner');
        var p = d.profile;
        banner.style.display = 'flex';
        banner.style.background = 'rgba(' + hexToRgb(p.color) + ',0.1)';
        banner.style.border = '1px solid rgba(' + hexToRgb(p.color) + ',0.3)';
        banner.style.color = p.color;
        document.getElementById('mission-dot').style.background = p.color;
        document.getElementById('mission-dot').style.boxShadow = '0 0 8px ' + p.color;
        document.getElementById('mission-name').textContent = 'MISSION: ' + p.display_name;
    }).catch(function(){});
}

function hexToRgb(hex) {
    hex = hex.replace('#','');
    return parseInt(hex.substring(0,2),16)+','+parseInt(hex.substring(2,4),16)+','+parseInt(hex.substring(4,6),16);
}

function openMissionSelector() {
    var modal = document.getElementById('mission-modal');
    var list = document.getElementById('mission-profile-list');
    list.textContent = '';
    var loading = document.createElement('div');
    loading.style.cssText = 'text-align:center;padding:20px;opacity:0.5;';
    loading.textContent = 'Loading profiles...';
    list.appendChild(loading);
    modal.classList.add('active');

    fetch('/tools/bridge/api/mission/profiles').then(function(r){return r.json();}).then(function(d) {
        if (!d.success) return;
        list.textContent = '';
        d.profiles.forEach(function(p) {
            var card = document.createElement('div');
            card.style.cssText = 'display:flex;align-items:center;gap:12px;padding:10px 14px;margin-bottom:6px;border-radius:8px;cursor:pointer;border:1px solid rgba(255,255,255,0.06);background:rgba(255,255,255,0.02);transition:all 0.15s;';
            card.addEventListener('mouseenter', function(){ card.style.background='rgba('+hexToRgb(p.color)+',0.1)'; card.style.borderColor='rgba('+hexToRgb(p.color)+',0.3)'; });
            card.addEventListener('mouseleave', function(){ card.style.background='rgba(255,255,255,0.02)'; card.style.borderColor='rgba(255,255,255,0.06)'; });
            card.addEventListener('click', function(){ activateMissionProfile(p.id, p.display_name); });

            var dot = document.createElement('span');
            dot.style.cssText = 'width:12px;height:12px;border-radius:50%;flex-shrink:0;background:'+p.color+';box-shadow:0 0 8px '+p.color+';';
            card.appendChild(dot);

            var info = document.createElement('div');
            info.style.cssText = 'flex:1;';
            var name = document.createElement('div');
            name.style.cssText = 'font-size:0.85rem;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:#fff;';
            name.textContent = p.display_name;
            var desc = document.createElement('div');
            desc.style.cssText = 'font-size:0.7rem;color:rgba(255,255,255,0.5);margin-top:2px;';
            desc.textContent = p.description || '';
            info.appendChild(name);
            info.appendChild(desc);
            card.appendChild(info);

            if (p.is_default) {
                var badge = document.createElement('span');
                badge.style.cssText = 'font-size:0.6rem;padding:2px 6px;border-radius:3px;background:rgba(0,212,255,0.15);color:#00d4ff;border:1px solid rgba(0,212,255,0.3);';
                badge.textContent = 'CURRENT';
                card.appendChild(badge);
            }

            list.appendChild(card);
        });
    }).catch(function(){ list.textContent = 'Error loading profiles'; });
}

function closeMissionModal() {
    document.getElementById('mission-modal').classList.remove('active');
}

function activateMissionProfile(profileId, displayName) {
    fetch('/tools/bridge/api/mission/activate/' + profileId, {method:'PUT'})
    .then(function(r){return r.json();}).then(function(d) {
        closeMissionModal();
        if (d.success) {
            if (typeof showToast === 'function') showToast('success', 'Mission profile: ' + displayName);
            loadMissionBanner();
        } else {
            if (typeof showToast === 'function') showToast('error', d.error || 'Failed');
        }
    }).catch(function(e){
        closeMissionModal();
    });
}

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Initialize i18n for translations
    if (window.archieI18n) {
        archieI18n.init();
    }

    updateClock();
    setInterval(updateClock, 1000);

    // Status bar
    updateStatusBar();
    loadStatusBarStats();
    setInterval(updateStatusBar, 1000);
    setInterval(loadStatusBarStats, 30000);

    loadOverviewData();
    loadStations();
    loadIAAEStatus();
    loadStaffingStatus();

    // Mission profile banner
    loadMissionBanner();
    setInterval(loadMissionBanner, 60000);

    // Check for running benchmarks on page load + periodic recheck
    setTimeout(_checkActiveBenchmark, 1500);
    setInterval(function() {
        if (_activeBenchmarkRun) _checkActiveBenchmark();
    }, 5000);

    // Refresh intervals
    setInterval(loadOverviewData, 60000);
    setInterval(loadStations, 30000);
    setInterval(loadIAAEStatus, 30000);
    setInterval(loadStaffingStatus, 60000);
    setInterval(loadViewscreenData, 30000);

    // Initialize Lucide icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});

// ============================================================================
// CLOCK
// ============================================================================

function updateClock() {
    const now = new Date();
    const time = now.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('bridge-time').textContent = time;
}

// ============================================================================
// LOAD STATIONS
// ============================================================================

async function loadStations() {
    try {
        const [stationResp, jobsResp] = await Promise.all([
            fetch('/tools/bridge/api/stations'),
            fetch('/tools/bridge/api/bridge/jobs?status=running')
        ]);
        const data = await stationResp.json();
        if (!data.success) return;

        allStations = data.stations;

        // Build coverage map from inline data (no separate API call needed)
        stationNodeCoverage = {};
        for (const s of data.stations) {
            if (s.node_coverage) {
                stationNodeCoverage[s.code] = s.node_coverage;
            }
        }

        // Parse running jobs
        let runningJobs = [];
        try {
            const jobsData = await jobsResp.json();
            if (jobsData.success) runningJobs = jobsData.jobs || [];
        } catch (e) { /* ignore job fetch failures */ }

        renderStations(data.stations, runningJobs);
        renderOpsStrip(data.stations, runningJobs);
        updateStationStats(data.stations);
        loadViewscreenData();
    } catch (error) {
        console.error('Error loading stations:', error);
    }
}

// ── Isometric bridge render functions ──

function renderStations(stations, runningJobs) {
    const container = document.getElementById('bridgeSpatialStations');
    if (!container) return;
    container.textContent = '';
    runningJobs = runningJobs || [];

    // Build lookup: agent code name → list of running jobs
    const agentJobMap = {};
    for (const job of runningJobs) {
        const callsign = job.agent_callsign;
        if (callsign) {
            if (!agentJobMap[callsign]) agentJobMap[callsign] = [];
            agentJobMap[callsign].push(job);
        }
    }

    // Group stations by isometric zone
    const zoneData = {};
    for (const [zoneName, zoneInfo] of Object.entries(ISOMETRIC_ZONE_MAP)) {
        zoneData[zoneName] = {
            agents: [],
            modules: [],
            totalNodes: 0,
            primaryStation: null,
            activeJobs: []
        };
    }

    for (const station of stations) {
        const zoneName = STATION_TO_ISO_ZONE[station.code];
        if (!zoneName || !zoneData[zoneName]) continue;
        const zd = zoneData[zoneName];
        if (!zd.primaryStation) zd.primaryStation = station;
        zd.modules = zd.modules.concat(station.modules || []);
        zd.agents = zd.agents.concat(station.assigned_agents || []);
        zd.maxPrimary = station.max_primary || 2;
        zd.maxAuxiliary = station.max_auxiliary || 1;
        const cov = stationNodeCoverage[station.code] || {};
        zd.totalNodes += (cov.total_nodes || 0);
    }

    // Match running jobs to zones via agent callsign OR station_code fallback
    const matchedJobIds = new Set();
    for (const [zoneName, zd] of Object.entries(zoneData)) {
        for (const agent of zd.agents) {
            const jobs = agentJobMap[agent.name];
            if (jobs) {
                zd.activeJobs = zd.activeJobs.concat(jobs);
                jobs.forEach(j => matchedJobIds.add(j.id));
            }
        }
    }
    // Cross-station jobs: also add to DISPATCH zone so destination sees the helper
    for (const job of runningJobs) {
        const meta = job.metadata || {};
        if (!meta.is_cross_station || !meta.dispatch_station) continue;
        const dispatchZone = STATION_TO_ISO_ZONE[meta.dispatch_station];
        const homeZone = STATION_TO_ISO_ZONE[meta.home_station];
        if (dispatchZone && zoneData[dispatchZone] && dispatchZone !== homeZone) {
            // Add to dispatch zone as helper job (avoid duplicate)
            if (!zoneData[dispatchZone].activeJobs.some(j => j.id === job.id)) {
                zoneData[dispatchZone].activeJobs.push(job);
            }
        }
    }
    // Fallback: jobs with station_code but no agent (budget-blocked dispatch)
    for (const job of runningJobs) {
        if (matchedJobIds.has(job.id)) continue;
        const sc = job.station_code || (job.metadata && job.metadata.dispatch_station);
        if (!sc) continue;
        const zoneName = STATION_TO_ISO_ZONE[sc];
        if (zoneName && zoneData[zoneName]) {
            zoneData[zoneName].activeJobs.push(job);
        }
    }

    // Create an isometric zone element for each of the 6 zones
    for (const [zoneName, zoneInfo] of Object.entries(ISOMETRIC_ZONE_MAP)) {
        const zd = zoneData[zoneName];
        const zoneEl = createIsometricZone(zoneName, zoneInfo, zd);
        container.appendChild(zoneEl);
    }

    // Draw cross-station connector lines for active cross-station jobs
    drawCrossStationLines(runningJobs);
}

/**
 * Draw SVG dashed lines between stations when an agent is helping another station.
 * Scans running jobs for metadata.is_cross_station=true and draws connectors
 * from the home station zone to the dispatch station zone.
 */
function drawCrossStationLines(runningJobs) {
    const overlay = document.getElementById('dispatchArcOverlay');
    const container = document.getElementById('bridgeSpatialLayout');
    if (!overlay || !container || window.innerWidth < 500) return;

    // Clear any previous cross-station lines (keep dispatch arcs)
    overlay.querySelectorAll('.cross-station-group').forEach(function(g) { g.remove(); });

    if (!runningJobs || !runningJobs.length) return;

    // Use local coordinates (offsetLeft/Top) to avoid CSS 3D transform distortion
    const inner = overlay.parentElement; // iso-bridge-room-inner
    const vw = inner ? inner.offsetWidth : container.offsetWidth;
    const vh = inner ? inner.offsetHeight : container.offsetHeight;
    overlay.setAttribute('viewBox', '0 0 ' + vw + ' ' + vh);

    for (const job of runningJobs) {
        const meta = job.metadata || {};
        if (!meta.is_cross_station) continue;

        // Determine source (home) and target (dispatch) zones
        const homeStation = meta.home_station;
        const dispatchStation = meta.dispatch_station;
        if (!homeStation || !dispatchStation) continue;
        if (dispatchStation === 'CLOUD') continue; // Cloud handled by contractor badge

        const homeZone = STATION_TO_ISO_ZONE[homeStation];
        const dispatchZone = STATION_TO_ISO_ZONE[dispatchStation];
        if (!homeZone || !dispatchZone || homeZone === dispatchZone) continue;

        const fromEl = document.querySelector('.iso-station-zone[data-station-code="' + homeZone + '"]');
        const toEl = document.querySelector('.iso-station-zone[data-station-code="' + dispatchZone + '"]');
        if (!fromEl || !toEl) continue;

        // Use offsetLeft/Top for coordinates in the untransformed container space
        const fromX = fromEl.offsetLeft + fromEl.offsetWidth / 2;
        const fromY = fromEl.offsetTop + fromEl.offsetHeight / 2;
        const toX = toEl.offsetLeft + toEl.offsetWidth / 2;
        const toY = toEl.offsetTop + toEl.offsetHeight / 2;

        // Determine colors: use dispatch zone color
        const zoneColor = (ISOMETRIC_ZONE_MAP[dispatchZone] && ISOMETRIC_ZONE_MAP[dispatchZone].color) || '#00FFFF';

        // Create a group for line + label + dots
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', 'cross-station-group');

        // Dashed line
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', fromX);
        line.setAttribute('y1', fromY);
        line.setAttribute('x2', toX);
        line.setAttribute('y2', toY);
        line.setAttribute('stroke', zoneColor);
        line.setAttribute('class', 'bridge-cross-station-line');
        g.appendChild(line);

        // Pulsing dots at each end
        var dot1 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot1.setAttribute('cx', fromX);
        dot1.setAttribute('cy', fromY);
        dot1.setAttribute('r', '3');
        dot1.setAttribute('fill', zoneColor);
        dot1.setAttribute('class', 'bridge-cross-station-dot');
        g.appendChild(dot1);
        var dot2 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        dot2.setAttribute('cx', toX);
        dot2.setAttribute('cy', toY);
        dot2.setAttribute('r', '3');
        dot2.setAttribute('fill', zoneColor);
        dot2.setAttribute('class', 'bridge-cross-station-dot');
        g.appendChild(dot2);

        // Task label at midpoint
        const midX = (fromX + toX) / 2;
        const midY = (fromY + toY) / 2;
        const taskLabel = job.description || job.job_type || 'Cross-station';
        // Label background (dark pill behind text)
        const labelBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        const textLen = Math.min(taskLabel.length * 5.5, 120);
        labelBg.setAttribute('x', midX - textLen / 2 - 4);
        labelBg.setAttribute('y', midY - 8);
        labelBg.setAttribute('width', textLen + 8);
        labelBg.setAttribute('height', 16);
        labelBg.setAttribute('rx', '4');
        labelBg.setAttribute('fill', 'rgba(0,0,0,0.8)');
        labelBg.setAttribute('stroke', zoneColor);
        labelBg.setAttribute('stroke-width', '0.5');
        labelBg.setAttribute('stroke-opacity', '0.4');
        g.appendChild(labelBg);

        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', midX);
        text.setAttribute('y', midY);
        text.setAttribute('class', 'bridge-cross-station-label');
        text.setAttribute('fill', zoneColor);
        text.textContent = taskLabel.length > 22 ? taskLabel.substring(0, 20) + '..' : taskLabel;
        g.appendChild(text);

        overlay.appendChild(g);
    }
}

function renderOpsStrip(stations, runningJobs) {
    const strip = document.getElementById('bridgeOpsStrip');
    if (!strip) return;
    runningJobs = runningJobs || [];

    // Build agent callsign → jobs lookup
    const agentJobMap = {};
    for (const job of runningJobs) {
        if (job.agent_callsign) {
            if (!agentJobMap[job.agent_callsign]) agentJobMap[job.agent_callsign] = [];
            agentJobMap[job.agent_callsign].push(job);
        }
    }

    // Build zone data with jobs (same logic as renderStations)
    const zoneJobs = {};
    const zoneAgents = {};
    for (const zoneName of Object.keys(ISOMETRIC_ZONE_MAP)) {
        zoneJobs[zoneName] = [];
        zoneAgents[zoneName] = [];
    }
    for (const station of stations) {
        const zoneName = STATION_TO_ISO_ZONE[station.code];
        if (!zoneName) continue;
        zoneAgents[zoneName] = (zoneAgents[zoneName] || []).concat(station.assigned_agents || []);
    }
    const opsMatchedIds = new Set();
    for (const [zoneName, agents] of Object.entries(zoneAgents)) {
        for (const agent of agents) {
            const jobs = agentJobMap[agent.name];
            if (jobs) {
                zoneJobs[zoneName] = zoneJobs[zoneName].concat(jobs);
                jobs.forEach(j => opsMatchedIds.add(j.id));
            }
        }
    }
    // Fallback: match unassigned jobs by station_code
    for (const job of runningJobs) {
        if (opsMatchedIds.has(job.id)) continue;
        const sc = job.station_code || (job.metadata && job.metadata.dispatch_station);
        if (!sc) continue;
        const zoneName = STATION_TO_ISO_ZONE[sc];
        if (zoneName && zoneJobs[zoneName]) {
            zoneJobs[zoneName].push(job);
        }
    }

    // Build status section only once — persist across rebuilds to avoid flicker
    if (!document.getElementById('opsRoutingMode')) {
        strip.textContent = '';

        var statusSec = document.createElement('div');
        statusSec.className = 'bridge-ops-status';

        // Online dot + text (ops- prefix to avoid duplicate IDs with status bar HTML)
        var s1 = document.createElement('div'); s1.className = 'bridge-ops-status-item';
        var statusDot = document.createElement('span'); statusDot.className = 'bridge-ops-status-dot'; statusDot.id = 'opsBridgeStatusDot';
        var dtx = document.createElement('span'); dtx.className = 'bridge-ops-status-value'; dtx.id = 'opsBridgeStatusText'; dtx.textContent = 'Online';
        s1.appendChild(statusDot); s1.appendChild(dtx); statusSec.appendChild(s1);

        // Route mode — seed from hidden status bar if available
        var s2 = document.createElement('div'); s2.className = 'bridge-ops-status-item';
        var ri = document.createElement('i'); ri.setAttribute('data-lucide', 'route'); ri.className = 'bridge-ops-status-icon';
        var rv = document.createElement('span'); rv.className = 'bridge-ops-status-value'; rv.id = 'opsRoutingMode';
        rv.textContent = (document.getElementById('statusRoutingMode') || {}).textContent || '--';
        s2.appendChild(ri); s2.appendChild(rv); statusSec.appendChild(s2);

        // Agent count — seed from hidden status bar (server-side rendered)
        var s3 = document.createElement('div'); s3.className = 'bridge-ops-status-item';
        var ai = document.createElement('i'); ai.setAttribute('data-lucide', 'users'); ai.className = 'bridge-ops-status-icon';
        var av = document.createElement('span'); av.className = 'bridge-ops-status-value'; av.id = 'opsAgentCount';
        av.textContent = (document.getElementById('statusAgentCount') || {}).textContent || '--';
        s3.appendChild(ai); s3.appendChild(av); statusSec.appendChild(s3);

        // Clock
        var s4 = document.createElement('div'); s4.className = 'bridge-ops-status-item';
        var ci = document.createElement('i'); ci.setAttribute('data-lucide', 'clock'); ci.className = 'bridge-ops-status-icon';
        var cv = document.createElement('span'); cv.className = 'bridge-ops-status-value'; cv.id = 'opsBarClock';
        cv.textContent = (document.getElementById('statusBarClock') || {}).textContent || '--:--';
        s4.appendChild(ci); s4.appendChild(cv); statusSec.appendChild(s4);

        strip.appendChild(statusSec);
        if (typeof lucide !== 'undefined') lucide.createIcons();

        // Label
        var label = document.createElement('div');
        label.className = 'bridge-ops-label';
        label.textContent = 'STATIONS';
        strip.appendChild(label);
    }

    // Remove old zones row and rebuild (status section + label persist)
    var oldZones = strip.querySelector('.bridge-ops-zones');
    if (oldZones) oldZones.remove();

    // Zone squares container
    var zonesRow = document.createElement('div');
    zonesRow.className = 'bridge-ops-zones';

    for (const [zoneName, zoneInfo] of Object.entries(ISOMETRIC_ZONE_MAP)) {
        var jobs = zoneJobs[zoneName] || [];
        var hasJob = jobs.length > 0;

        var zoneEl = document.createElement('div');
        zoneEl.className = 'bridge-ops-zone' + (hasJob ? ' has-job' : '');

        // Zone status dot
        var zoneDot = document.createElement('div');
        zoneDot.className = 'bridge-ops-zone-dot';
        if (!hasJob) {
            var hex = zoneInfo.color;
            var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
            zoneDot.style.background = 'rgba(' + r + ',' + g + ',' + b + ',0.2)';
        }
        zoneEl.appendChild(zoneDot);

        // Zone name
        var nameEl = document.createElement('div');
        nameEl.className = 'bridge-ops-zone-name';
        nameEl.textContent = zoneInfo.abbr;
        if (!hasJob) nameEl.style.color = zoneInfo.color;
        zoneEl.appendChild(nameEl);

        // Progress bar (only visible when has-job)
        if (hasJob) {
            var job = jobs[0];
            var pct = job.total_steps > 0 ? Math.round((job.completed_steps / job.total_steps) * 100) : 0;

            var progTrack = document.createElement('div');
            progTrack.className = 'bridge-ops-zone-progress';
            var progBar = document.createElement('div');
            progBar.className = 'bridge-ops-zone-bar';
            progBar.style.width = pct + '%';
            progTrack.appendChild(progBar);
            zoneEl.appendChild(progTrack);

            // Job summary text
            var jobText = document.createElement('div');
            jobText.className = 'bridge-ops-zone-job';
            jobText.textContent = pct + '% ' + (job.completed_steps + '/' + job.total_steps);
            zoneEl.appendChild(jobText);
        }

        // Click → open LCARS console for this zone
        (function(zn, zi) {
            zoneEl.addEventListener('click', function() {
                // Build zd from current allStations
                var zd = { agents: [], modules: [], totalNodes: 0, primaryStation: null, activeJobs: zoneJobs[zn] || [] };
                for (var s of allStations) {
                    if (STATION_TO_ISO_ZONE[s.code] === zn) {
                        if (!zd.primaryStation) zd.primaryStation = s;
                        zd.modules = zd.modules.concat(s.modules || []);
                        zd.agents = zd.agents.concat(s.assigned_agents || []);
                    }
                }
                openStationConsole(zn, zi, zd);
            });
        })(zoneName, zoneInfo);

        zonesRow.appendChild(zoneEl);
    }

    strip.appendChild(zonesRow);
}

function createIsometricZone(zoneName, zoneInfo, zd) {
    const el = document.createElement('div');
    const zoneKey = zoneName.toLowerCase();
    el.className = 'iso-station-zone iso-zone-' + zoneKey;
    el.dataset.stationCode = zoneName;
    if (zd.primaryStation) el.dataset.stationId = zd.primaryStation.id;

    const hasAgents = zd.agents.length > 0;
    const hasActiveJobs = zd.activeJobs && zd.activeJobs.length > 0;
    el.classList.add(hasAgents ? 'is-active' : 'is-idle');
    if (hasActiveJobs) el.classList.add('has-active-job');

    const moduleCount = zd.modules.length;
    const utilPct = Math.min(100, Math.round(moduleCount * 10));

    // Build DOM elements instead of innerHTML for security
    // -- Station name row --
    const nameDiv = document.createElement('div');
    nameDiv.className = 'iso-station-name';
    const dot = document.createElement('span');
    dot.className = 'iso-status-dot';
    nameDiv.appendChild(dot);
    nameDiv.appendChild(document.createTextNode(' ' + zoneInfo.label + ' '));
    const modSpan = document.createElement('span');
    modSpan.className = 'iso-module-count';
    modSpan.textContent = moduleCount + ' mod';
    nameDiv.appendChild(modSpan);
    el.appendChild(nameDiv);

    // -- Crew avatars --
    const isDual = zd.agents.length > 1;
    const crewRow = document.createElement('div');
    crewRow.className = 'iso-crew-row' + (isDual ? ' dual' : '');

    if (hasAgents) {
        const displayed = zd.agents.slice(0, 2);
        let commanderAssigned = false;
        for (const agent of displayed) {
            const firstName = agent.first_name || '';
            const lastName = agent.last_name || '';
            const fullName = (firstName + ' ' + lastName).trim() || agent.name || 'Unknown';
            const displayName = firstName || fullName.split(' ')[0];
            const isPrimary = agent.assignment_type === 'primary';
            // Only the first primary agent at COMMAND gets the commander badge
            const isCommander = zoneName === 'COMMAND' && isPrimary && !commanderAssigned;
            if (isCommander) commanderAssigned = true;

            // Check if agent is away on cross-station duty
            const awayJob = (zd.activeJobs || []).find(function(j) {
                const m = j.metadata || {};
                return m.is_cross_station && (j.agent_callsign || j.agent_name || '').toLowerCase() === agent.name.toLowerCase()
                    && STATION_TO_ISO_ZONE[m.home_station] === zoneName
                    && STATION_TO_ISO_ZONE[m.dispatch_station] !== zoneName;
            });
            const isAway = !!awayJob;

            const avatarSlug = displayName.toLowerCase();
            const dicebearFallback = 'https://api.dicebear.com/9.x/adventurer/svg?seed=' + encodeURIComponent(displayName) + '&backgroundColor=transparent';

            const member = document.createElement('div');
            member.className = 'iso-crew-member';
            if (isAway) member.style.opacity = '0.35';
            if (isAway) member.style.filter = 'grayscale(0.8)';

            const ring = document.createElement('div');
            ring.className = 'iso-avatar-ring';
            if (isAway) ring.style.animationPlayState = 'paused';

            const img = document.createElement('img');
            img.className = 'iso-avatar-img';
            img.src = '/static/avatars/' + avatarSlug + '.svg';
            img.alt = displayName;
            img.loading = 'lazy';
            img.onerror = function() { this.src = dicebearFallback; };
            ring.appendChild(img);

            if (isCommander) {
                const badge = document.createElement('span');
                badge.className = 'iso-commander-badge';
                badge.title = 'Commander';
                badge.textContent = '\u2605';
                ring.appendChild(badge);
            }

            member.appendChild(ring);

            const nameSpan = document.createElement('span');
            nameSpan.className = 'iso-crew-name';
            nameSpan.textContent = displayName;
            if (isCommander) {
                nameSpan.style.color = '#FFD700';
                nameSpan.style.opacity = '1';
            }
            member.appendChild(nameSpan);
            crewRow.appendChild(member);
        }
    } else {
        const member = document.createElement('div');
        member.className = 'iso-crew-member';
        const ring = document.createElement('div');
        ring.className = 'iso-avatar-ring';
        ring.style.opacity = '0.3';
        const placeholder = document.createElement('div');
        placeholder.className = 'iso-avatar-img';
        placeholder.style.cssText = 'display:flex;align-items:center;justify-content:center;font-size:0.5rem;opacity:0.4;';
        placeholder.textContent = '--';
        ring.appendChild(placeholder);
        member.appendChild(ring);
        const nameSpan = document.createElement('span');
        nameSpan.className = 'iso-crew-name';
        nameSpan.style.opacity = '0.3';
        nameSpan.textContent = 'Unstaffed';
        member.appendChild(nameSpan);
        crewRow.appendChild(member);
    }
    el.appendChild(crewRow);

    // -- Console --
    const console = document.createElement('div');
    console.className = 'iso-console';
    const screen = document.createElement('div');
    screen.className = 'iso-console-screen';

    const statusDiv = document.createElement('div');
    statusDiv.className = 'iso-console-status ' + (hasAgents ? 'active' : 'idle');
    const iconSpan = document.createElement('span');
    iconSpan.textContent = hasActiveJobs ? '\u2699' : (hasAgents ? '\u25B6' : '\u25FC');
    statusDiv.appendChild(iconSpan);
    statusDiv.appendChild(document.createTextNode(' ' + (hasAgents ? moduleCount + ' modules active' : 'Standing by')));
    if (hasAgents && !hasActiveJobs) {
        const cursor = document.createElement('span');
        cursor.className = 'iso-typing-cursor';
        statusDiv.appendChild(cursor);
    }
    screen.appendChild(statusDiv);

    // Show active job info + progress bars (one per running job)
    if (hasActiveJobs) {
        for (var ji = 0; ji < zd.activeJobs.length; ji++) {
            const job = zd.activeJobs[ji];
            const jobLine = document.createElement('div');
            jobLine.className = 'iso-job-status-line';
            var jobText = (job.description || job.job_type || 'Working');
            if (job.total_steps > 0) {
                jobText += ' ' + job.completed_steps + '/' + job.total_steps;
            }
            jobLine.textContent = jobText;
            screen.appendChild(jobLine);

            const progressTrack = document.createElement('div');
            progressTrack.className = 'iso-console-progress';
            const progressBar = document.createElement('div');
            progressBar.className = 'iso-console-progress-bar';
            const jobPct = job.total_steps > 0 ? Math.round((job.completed_steps / job.total_steps) * 100) : 0;
            progressBar.style.width = jobPct + '%';
            progressBar.style.background = '#10b981';
            progressTrack.appendChild(progressBar);
            screen.appendChild(progressTrack);
        }
    }

    console.appendChild(screen);

    const glow = document.createElement('div');
    glow.className = 'iso-console-glow';
    console.appendChild(glow);
    el.appendChild(console);

    // -- Contractor badge (cloud provider indicator, below console) --
    if (hasActiveJobs) {
        const cloudJob = zd.activeJobs.find(function(j) {
            const name = (j.agent_callsign || '').toLowerCase();
            const meta = j.metadata || {};
            return name.startsWith('cloud') || meta.is_cloud || meta.dispatch_station === 'CLOUD';
        });
        if (cloudJob) {
            const brand = getProviderBrand(cloudJob.agent_callsign || cloudJob.metadata.cloud_model || '');
            if (brand) {
                const badge = document.createElement('div');
                badge.className = 'iso-contractor-badge';
                badge.style.setProperty('--contractor-color', brand.color);
                badge.style.setProperty('--contractor-rgb', brand.rgb);
                const icon = document.createElement('span');
                icon.className = 'contractor-icon';
                icon.textContent = '\u2601'; // cloud icon
                badge.appendChild(icon);
                const dot = document.createElement('span');
                dot.className = 'contractor-dot';
                badge.appendChild(dot);
                const nameEl = document.createElement('span');
                nameEl.className = 'contractor-name';
                nameEl.textContent = brand.label;
                badge.appendChild(nameEl);
                el.appendChild(badge);
            }
        }
    }

    // -- Floor glow --
    const floorGlow = document.createElement('div');
    floorGlow.className = 'iso-station-floor-glow';
    el.appendChild(floorGlow);

    // Click handler → open LCARS station console
    el.addEventListener('click', function() {
        openStationConsole(zoneName, zoneInfo, zd);
    });

    return el;
}

function showZoneInfo(zoneName, zoneInfo, zd) {
    const modal = document.getElementById('iso-zone-info-modal');
    const title = document.getElementById('iso-zone-info-title');
    const body = document.getElementById('iso-zone-info-body');
    if (!modal || !title || !body) return;

    title.textContent = zoneInfo.label + ' Station';
    title.style.color = zoneInfo.color;
    body.textContent = '';

    // -- Status summary --
    const statusDiv = document.createElement('div');
    statusDiv.style.cssText = 'display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap;';

    const statItems = [
        { label: 'Modules', value: zd.modules.length, color: zoneInfo.color },
        { label: 'Crew', value: zd.agents.length, color: zoneInfo.color },
        { label: 'Nodes', value: zd.totalNodes, color: zoneInfo.color }
    ];
    for (const si of statItems) {
        const pill = document.createElement('div');
        pill.style.cssText = 'background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:8px 14px;text-align:center;flex:1;min-width:80px;';
        const val = document.createElement('div');
        val.style.cssText = 'font-size:1.3rem;font-weight:700;font-family:Orbitron,sans-serif;color:' + si.color + ';';
        val.textContent = si.value;
        const lbl = document.createElement('div');
        lbl.style.cssText = 'font-size:0.65rem;opacity:0.5;margin-top:2px;letter-spacing:0.1em;text-transform:uppercase;';
        lbl.textContent = si.label;
        pill.appendChild(val);
        pill.appendChild(lbl);
        statusDiv.appendChild(pill);
    }
    body.appendChild(statusDiv);

    // -- Crew section --
    if (zd.agents.length > 0) {
        const crewHeader = document.createElement('div');
        crewHeader.style.cssText = 'font-size:0.7rem;font-weight:600;opacity:0.5;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:8px;';
        crewHeader.textContent = 'CREW';
        body.appendChild(crewHeader);

        const crewList = document.createElement('div');
        crewList.style.cssText = 'display:flex;flex-direction:column;gap:6px;margin-bottom:16px;';

        for (const agent of zd.agents) {
            const firstName = agent.first_name || '';
            const lastName = agent.last_name || '';
            const fullName = (firstName + ' ' + lastName).trim() || agent.name || 'Unknown';
            const displayName = firstName || fullName.split(' ')[0];
            const role = agent.title || agent.name || 'Staff';
            const isPrimary = agent.assignment_type === 'primary';
            const avatarSlug = displayName.toLowerCase();
            const fallback = 'https://api.dicebear.com/9.x/adventurer/svg?seed=' + encodeURIComponent(displayName) + '&backgroundColor=transparent';

            const row = document.createElement('div');
            row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 10px;background:rgba(255,255,255,0.03);border-radius:8px;border-left:3px solid ' + zoneInfo.color + ';';

            const img = document.createElement('img');
            img.src = '/static/avatars/' + avatarSlug + '.svg';
            img.alt = displayName;
            img.style.cssText = 'width:36px;height:36px;border-radius:50%;background:rgba(10,14,20,0.9);flex-shrink:0;';
            img.onerror = function() { this.src = fallback; };
            row.appendChild(img);

            const info = document.createElement('div');
            info.style.cssText = 'flex:1;min-width:0;';

            const nameEl = document.createElement('div');
            nameEl.style.cssText = 'font-weight:600;font-size:0.85rem;';
            nameEl.textContent = fullName;
            info.appendChild(nameEl);

            const roleEl = document.createElement('div');
            roleEl.style.cssText = 'font-size:0.7rem;opacity:0.5;';
            roleEl.textContent = role;
            info.appendChild(roleEl);

            row.appendChild(info);

            if (isPrimary) {
                const badge = document.createElement('span');
                badge.style.cssText = 'font-size:0.6rem;padding:2px 8px;border-radius:10px;background:rgba(255,255,255,0.06);color:' + zoneInfo.color + ';white-space:nowrap;';
                badge.textContent = 'Primary';
                row.appendChild(badge);
            }

            crewList.appendChild(row);
        }
        body.appendChild(crewList);
    }

    // -- Modules section --
    if (zd.modules.length > 0) {
        const modHeader = document.createElement('div');
        modHeader.style.cssText = 'font-size:0.7rem;font-weight:600;opacity:0.5;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:8px;';
        modHeader.textContent = 'MODULES';
        body.appendChild(modHeader);

        const modGrid = document.createElement('div');
        modGrid.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';

        for (const mod of zd.modules) {
            const chip = document.createElement('span');
            chip.style.cssText = 'font-size:0.7rem;padding:4px 10px;border-radius:6px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);white-space:nowrap;';
            chip.textContent = mod;
            modGrid.appendChild(chip);
        }
        body.appendChild(modGrid);
    }

    modal.classList.add('active');
}

// === LCARS STATION CONSOLE ===

let _consoleCurrentZone = null;
let _consoleDispatchTimer = null;
let _consoleEventSource = null;
let _consoleNodeCache = {};

function openStationConsole(zoneName, zoneInfo, zd) {
    const panel = document.getElementById('lcarsConsole');
    const backdrop = document.getElementById('lcarsConsoleBackdrop');
    if (!panel || !backdrop) return;

    _consoleCurrentZone = { zoneName, zoneInfo, zd };

    // Show CTRL and BENCH tabs only for COMMAND zone
    var ctrlTab = document.getElementById('lcarsRoutingTab');
    if (ctrlTab) ctrlTab.style.display = (zoneName === 'COMMAND') ? '' : 'none';
    var benchTab = document.getElementById('lcarsBenchTab');
    if (benchTab) benchTab.style.display = (zoneName === 'COMMAND') ? '' : 'none';

    // Set station color
    panel.style.setProperty('--station-color', zoneInfo.color);

    // Set title
    document.getElementById('lcarsConsoleTitle').textContent = zoneInfo.label + ' Station';
    document.getElementById('lcarsConsoleSubtitle').textContent = zoneInfo.stations.join(' \u2022 ');

    // Build module rail
    buildModuleRail(zd.modules, zoneInfo.color);

    // Load crew tab (default, no API call needed)
    renderCrewTab(zd.agents, zoneInfo.color, zd.maxPrimary || 2, zd.maxAuxiliary || 1);

    // Reset to crew tab
    switchConsoleTab('crew');

    // Open panel
    backdrop.classList.add('active');
    panel.classList.add('open');

    // Close handlers
    backdrop.onclick = closeStationConsole;
    document.getElementById('lcarsConsoleClose').onclick = closeStationConsole;

    // Escape key
    document.addEventListener('keydown', _consoleEscHandler);
}

function closeStationConsole() {
    const panel = document.getElementById('lcarsConsole');
    const backdrop = document.getElementById('lcarsConsoleBackdrop');
    if (panel) panel.classList.remove('open');
    if (backdrop) backdrop.classList.remove('active');
    document.removeEventListener('keydown', _consoleEscHandler);

    // Stop dispatch auto-refresh
    if (_consoleDispatchTimer) {
        clearInterval(_consoleDispatchTimer);
        _consoleDispatchTimer = null;
    }
    if (_consoleEventSource) {
        _consoleEventSource.close();
        _consoleEventSource = null;
    }
    // Stop action job polling
    _clearActionPolls();
    _consoleCurrentZone = null;
}

function _consoleEscHandler(e) {
    if (e.key === 'Escape') closeStationConsole();
}

function switchConsoleTab(tabName) {
    // Update pills
    document.querySelectorAll('.lcars-tab-pill').forEach(function(pill) {
        pill.classList.toggle('active', pill.dataset.consoleTab === tabName);
    });
    // Update panels
    document.querySelectorAll('.lcars-tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.dataset.consolePanel === tabName);
    });
    // Deselect any active module icon
    document.querySelectorAll('.lcars-module-icon').forEach(function(icon) {
        icon.classList.remove('active');
    });

    // Load data for tab
    if (!_consoleCurrentZone) return;
    var zd = _consoleCurrentZone.zd;
    var zoneInfo = _consoleCurrentZone.zoneInfo;

    if (tabName === 'dispatch') loadConsoleDispatch(zoneInfo.stations);
    if (tabName === 'nodes') loadConsoleNodes(zd, zoneInfo.color);
    if (tabName === 'metrics') loadConsoleMetrics(zoneInfo.stations);
    if (tabName === 'memory') loadConsoleMemory();
    if (tabName === 'actions') loadConsoleActions(zoneInfo.stations);
    if (tabName === 'benchmarks') loadConsoleBenchmarks();
    if (tabName === 'routing') renderRoutingTab();
}

function _syncBenchContractorSetting(enabled) {
    // Setting is stored in localStorage and read when starting benchmarks.
    // No backend call needed — the flag is sent with each benchmark start request.
    console.log('Benchmark contractors:', enabled ? 'enabled' : 'disabled');
}

function renderRoutingTab() {
    var panel = document.getElementById('lcarsRoutingPanel');
    if (!panel) return;
    panel.textContent = '';

    // Routing Mode section
    var section = document.createElement('div');
    section.style.cssText = 'padding:12px;';

    var label = document.createElement('div');
    label.style.cssText = 'font-size:0.65rem;text-transform:uppercase;letter-spacing:0.1em;opacity:0.5;margin-bottom:8px;';
    label.textContent = 'Routing Mode';
    section.appendChild(label);

    var btnGroup = document.createElement('div');
    btnGroup.style.cssText = 'display:flex;gap:0;';

    var modes = [
        { mode: 'local_only', text: 'Local Only' },
        { mode: 'local_cloud', text: 'Local + Cloud' },
        { mode: 'full', text: 'Full' }
    ];

    modes.forEach(function(m) {
        var btn = document.createElement('button');
        btn.className = 'routing-btn';
        btn.dataset.mode = m.mode;
        btn.textContent = m.text;
        btn.addEventListener('click', async function() {
            try {
                var res = await fetch('/tools/bridge/api/routing-mode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({routing_mode: m.mode}),
                });
                var data = await res.json();
                if (data.success) {
                    // Update all routing-btn elements (header + console)
                    document.querySelectorAll('.routing-btn').forEach(function(b) {
                        b.classList.toggle('active', b.dataset.mode === m.mode);
                    });
                    var st = document.getElementById('routingModeStatus');
                    if (st) st.textContent = 'Mode: ' + m.mode;
                }
            } catch (e) { console.error('Failed to set routing mode:', e); }
        });
        btnGroup.appendChild(btn);
    });
    section.appendChild(btnGroup);

    // Escalation section
    var escLabel = document.createElement('div');
    escLabel.style.cssText = 'font-size:0.65rem;text-transform:uppercase;letter-spacing:0.1em;opacity:0.5;margin:16px 0 8px;';
    escLabel.textContent = 'Escalation';
    section.appendChild(escLabel);

    var escGroup = document.createElement('div');
    escGroup.style.cssText = 'display:flex;gap:0;';

    var escModes = [
        { mode: 'auto', text: 'Auto' },
        { mode: 'ask_first', text: 'Ask First' }
    ];

    escModes.forEach(function(m) {
        var btn = document.createElement('button');
        btn.className = 'escalation-btn';
        btn.dataset.mode = m.mode;
        btn.textContent = m.text;
        btn.addEventListener('click', async function() {
            try {
                var res = await fetch('/tools/bridge/api/escalation-mode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({escalation_mode: m.mode}),
                });
                var data = await res.json();
                if (data.success) {
                    document.querySelectorAll('.escalation-btn').forEach(function(b) {
                        b.classList.toggle('active', b.dataset.mode === m.mode);
                    });
                }
            } catch (e) { console.error('Failed to set escalation mode:', e); }
        });
        escGroup.appendChild(btn);
    });
    section.appendChild(escGroup);

    // Benchmark Contractors toggle
    var benchLabel = document.createElement('div');
    benchLabel.style.cssText = 'font-size:0.65rem;text-transform:uppercase;letter-spacing:0.1em;opacity:0.5;margin:16px 0 8px;';
    benchLabel.textContent = 'Benchmark Settings';
    section.appendChild(benchLabel);

    var toggleRow = document.createElement('div');
    toggleRow.style.cssText = 'display:flex;align-items:center;gap:10px;';

    var toggleLabel = document.createElement('span');
    toggleLabel.style.cssText = 'font-size:0.6rem;color:rgba(255,255,255,0.7);';
    toggleLabel.textContent = 'Include External Contractors';
    toggleRow.appendChild(toggleLabel);

    var toggle = document.createElement('label');
    toggle.className = 'ctrl-toggle';
    var tInput = document.createElement('input');
    tInput.type = 'checkbox';
    tInput.id = 'benchContractorsToggle';
    // Load saved state
    tInput.checked = localStorage.getItem('archie_bench_contractors') === 'true';
    tInput.addEventListener('change', function() {
        localStorage.setItem('archie_bench_contractors', tInput.checked ? 'true' : 'false');
        // Update all active benchmark test_configs
        _syncBenchContractorSetting(tInput.checked);
    });
    var tSlider = document.createElement('span');
    tSlider.className = 'ctrl-toggle-slider';
    toggle.appendChild(tInput);
    toggle.appendChild(tSlider);
    toggleRow.appendChild(toggle);

    var toggleStatus = document.createElement('span');
    toggleStatus.style.cssText = 'font-size:0.5rem;opacity:0.4;';
    toggleStatus.textContent = tInput.checked ? 'ON — contractors tested in benchmarks' : 'OFF — local only';
    toggleRow.appendChild(toggleStatus);
    tInput.addEventListener('change', function() {
        toggleStatus.textContent = tInput.checked ? 'ON — contractors tested in benchmarks' : 'OFF — local only';
    });

    section.appendChild(toggleRow);

    panel.appendChild(section);

    // Sync active state from header buttons
    document.querySelectorAll('.bridge-header-controls .routing-btn.active').forEach(function(b) {
        var match = panel.querySelector('.routing-btn[data-mode="' + b.dataset.mode + '"]');
        if (match) match.classList.add('active');
    });
    document.querySelectorAll('.bridge-header-controls .escalation-btn.active').forEach(function(b) {
        var match = panel.querySelector('.escalation-btn[data-mode="' + b.dataset.mode + '"]');
        if (match) match.classList.add('active');
    });

    // Also fetch current routing mode from API
    fetch('/tools/bridge/api/routing-mode')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                panel.querySelectorAll('.routing-btn').forEach(function(b) {
                    b.classList.toggle('active', b.dataset.mode === data.routing_mode);
                });
            }
        }).catch(function() {});
}

// Wire up tab pill clicks
document.getElementById('lcarsTabRail').addEventListener('click', function(e) {
    var pill = e.target.closest('.lcars-tab-pill');
    if (pill) switchConsoleTab(pill.dataset.consoleTab);
});

// === MODULE ICON RAIL ===

// Module metadata cache
var _moduleMetadataCache = {};

async function buildModuleRail(moduleNames, stationColor) {
    var rail = document.getElementById('lcarsModuleRail');
    if (!rail) return;
    rail.textContent = '';

    if (!moduleNames || moduleNames.length === 0) {
        rail.style.display = 'none';
        return;
    }
    rail.style.display = 'flex';

    // Fetch uncached module metadata
    var uncached = moduleNames.filter(function(n) { return !_moduleMetadataCache[n]; });
    if (uncached.length > 0) {
        try {
            var resp = await fetch('/tools/bridge/api/modules/metadata', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modules: uncached })
            });
            var data = await resp.json();
            if (data.success) {
                for (var i = 0; i < data.modules.length; i++) {
                    var m = data.modules[i];
                    _moduleMetadataCache[m.id] = m;
                    // Also cache by original request name
                    if (uncached[i]) _moduleMetadataCache[uncached[i]] = m;
                }
            }
        } catch (e) {
            console.error('Error fetching module metadata:', e);
        }
    }

    // Build icon elements
    for (var j = 0; j < moduleNames.length; j++) {
        var name = moduleNames[j];
        var mod = _moduleMetadataCache[name] || { id: name, name: name, icon: 'box', route: null, description: '' };

        var iconEl = document.createElement('div');
        iconEl.className = 'lcars-module-icon';
        iconEl.dataset.moduleId = mod.id || name;

        var lucideIcon = document.createElement('i');
        lucideIcon.setAttribute('data-lucide', mod.icon || 'box');
        iconEl.appendChild(lucideIcon);

        var tooltip = document.createElement('div');
        tooltip.className = 'lcars-module-tooltip';
        tooltip.textContent = mod.name;
        iconEl.appendChild(tooltip);

        // Click handler (use closure to capture mod)
        (function(capturedMod, capturedIconEl) {
            capturedIconEl.addEventListener('click', function() {
                showModulePreview(capturedMod);
                document.querySelectorAll('.lcars-module-icon').forEach(function(el) { el.classList.remove('active'); });
                capturedIconEl.classList.add('active');
                document.querySelectorAll('.lcars-tab-pill').forEach(function(p) { p.classList.remove('active'); });
            });
        })(mod, iconEl);

        rail.appendChild(iconEl);
    }

    // Re-render Lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// === ACTIONS TAB CONTENT ===
// Renders per-module stn-ops-terminal blocks (same pattern as Consciousness GitHub tab).
// All DOM built via createElement — no innerHTML with user data.

var _actionJobPolls = {};

function _clearActionPolls() {
    for (var k in _actionJobPolls) { clearInterval(_actionJobPolls[k]); }
    _actionJobPolls = {};
}

function loadConsoleActions(stationCodes) {
    var panel = document.getElementById('lcarsActionsPanel');
    if (!panel) return;
    panel.textContent = '';

    var codes = stationCodes.join(',');

    // Fetch actions + running jobs in parallel
    Promise.all([
        fetch('/tools/bridge/api/station-actions?station_code=' + encodeURIComponent(codes)).then(function(r) { return r.json(); }),
        fetch('/tools/bridge/api/bridge/jobs?status=running').then(function(r) { return r.json(); }).catch(function() { return { success: true, jobs: [] }; })
    ]).then(function(results) {
        _renderModuleActions(panel, results[0], results[1]);
    }).catch(function(err) {
        console.error('Failed to load station actions:', err);
        var errEl = document.createElement('div');
        errEl.className = 'stn-ops-loading';
        errEl.style.cssText = 'padding:20px 12px;text-align:center;';
        errEl.textContent = 'Failed to load actions';
        panel.appendChild(errEl);
    });
}

// ── BENCH tab: All-stations benchmark & assignment hub ──

function loadConsoleBenchmarks() {
    var panel = document.getElementById('lcarsBenchPanel');
    if (!panel) return;
    panel.textContent = '';

    // Resource bar (Phase 4)
    _renderResourceBar(panel);
    // Score heatmap matrix (Phase 3)
    _renderScoreHeatmap(panel);
    // Existing station overview
    _loadBenchmarkOverview(panel);
}

// ── Resource Bar ──
function _renderResourceBar(panel) {
    var bar = document.createElement('div');
    bar.className = 'bench-resource-bar';
    bar.id = 'benchResourceBar';
    var loadMsg = document.createElement('div');
    loadMsg.className = 'bench-resource-loading';
    loadMsg.textContent = 'Loading system resources...';
    bar.appendChild(loadMsg);
    panel.appendChild(bar);

    fetch('/tools/bridge/api/bridge/resources')
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (!d.success) { bar.textContent = 'Failed to load resources'; return; }
        bar.textContent = '';

        function makeResourceItem(label, labelDetail, pct, valueText, colorClass) {
            var item = document.createElement('div');
            item.className = 'bench-resource-item';
            var lbl = document.createElement('div');
            lbl.className = 'bench-resource-label';
            lbl.textContent = label + ' ';
            if (labelDetail) {
                var detail = document.createElement('span');
                detail.className = 'bench-resource-name';
                detail.textContent = labelDetail;
                lbl.appendChild(detail);
            }
            item.appendChild(lbl);
            var track = document.createElement('div');
            track.className = 'bench-resource-bar-track';
            var fill = document.createElement('div');
            fill.className = 'bench-resource-bar-fill ' + colorClass;
            fill.style.width = Math.min(pct, 100) + '%';
            track.appendChild(fill);
            item.appendChild(track);
            var val = document.createElement('div');
            val.className = 'bench-resource-value';
            val.textContent = valueText;
            item.appendChild(val);
            return item;
        }

        // GPU — real data from host monitor
        var gpuPct = d.gpu.vram_total_mb > 0 ? Math.round((d.gpu.vram_used_mb / d.gpu.vram_total_mb) * 100) : 0;
        var gpuDetail = d.gpu.name;
        if (d.gpu.temperature) gpuDetail += ' ' + d.gpu.temperature + '\u00B0C';
        bar.appendChild(makeResourceItem('GPU VRAM', gpuDetail, gpuPct, d.gpu.vram_used_mb + '/' + d.gpu.vram_total_mb + ' MB', 'gpu'));

        // RAM — with model RAM usage overlay
        var ramDetail = d.ram.models_ram_gb ? d.ram.models_ram_gb + 'GB by models' : null;
        bar.appendChild(makeResourceItem('RAM', ramDetail, d.ram.pct, d.ram.used_gb + '/' + d.ram.total_gb + ' GB (' + d.ram.available_gb + ' free)', 'ram'));

        // CPU
        var cpuDetail = d.cpu.model ? d.cpu.model.replace(/\(R\)/g,'').replace(/CPU /,'').trim() : d.cpu.cores + ' cores';
        if (cpuDetail.length > 40) cpuDetail = cpuDetail.substring(0, 37) + '...';
        bar.appendChild(makeResourceItem('CPU', cpuDetail, d.cpu.usage_pct, d.cpu.usage_pct + '%', 'cpu'));

        // ── Ollama Model Roster ──
        var roster = document.createElement('div');
        roster.className = 'bench-resource-item models';

        // Header: MODELS (loaded/max) — config
        var rosterHeader = document.createElement('div');
        rosterHeader.className = 'bench-resource-label';
        rosterHeader.textContent = 'OLLAMA MODELS ';
        var rosterMeta = document.createElement('span');
        rosterMeta.className = 'bench-resource-name';
        var cfg = d.ollama_config || {};
        var cap = d.capacity || {};
        rosterMeta.textContent = cap.loaded_count + '/' + cap.max_slots + ' loaded \u2022 ' +
            cap.local_count + ' local \u2022 ' + cap.cloud_count + ' cloud \u2022 ' +
            'keep_alive=' + (cfg.keep_alive || '?') + ' \u2022 parallel=' + (cfg.num_parallel || '?');
        rosterHeader.appendChild(rosterMeta);
        roster.appendChild(rosterHeader);

        // Slot usage bar
        var slotPct = cap.max_slots > 0 ? Math.round((cap.loaded_count / cap.max_slots) * 100) : 0;
        var slotTrack = document.createElement('div');
        slotTrack.className = 'bench-resource-bar-track';
        slotTrack.style.marginBottom = '6px';
        var slotFill = document.createElement('div');
        slotFill.className = 'bench-resource-bar-fill gpu';
        slotFill.style.width = slotPct + '%';
        slotTrack.appendChild(slotFill);
        roster.appendChild(slotTrack);

        // Model grid: all models with loaded/unloaded status
        var modList = document.createElement('div');
        modList.className = 'bench-model-list';

        var allModels = d.ollama_available || [];
        // Sort: loaded first, then by name
        allModels.sort(function(a, b) {
            if (a.loaded && !b.loaded) return -1;
            if (!a.loaded && b.loaded) return 1;
            return a.name.localeCompare(b.name);
        });

        allModels.forEach(function(m) {
            var tag = document.createElement('span');
            if (m.cloud) {
                tag.className = 'bench-model-tag cloud';
            } else if (m.loaded) {
                // Find device info from loaded list
                var loadedInfo = (d.ollama_loaded || []).find(function(l) { return l.name === m.name; });
                var device = loadedInfo ? loadedInfo.device : 'cpu';
                tag.className = 'bench-model-tag ' + device + ' loaded';
            } else {
                tag.className = 'bench-model-tag unloaded';
            }
            tag.textContent = m.name.replace(':latest', '') + ' ';
            var small = document.createElement('small');
            if (m.cloud) {
                small.textContent = 'CLOUD';
            } else if (m.loaded) {
                var li = (d.ollama_loaded || []).find(function(l) { return l.name === m.name; });
                if (li && li.vram_gb > 0) {
                    small.textContent = m.size_gb + 'GB \u2022 GPU:' + li.vram_gb + 'GB RAM:' + li.ram_gb + 'GB';
                } else {
                    small.textContent = m.size_gb + 'GB \u2022 CPU';
                }
            } else {
                small.textContent = m.size_gb + 'GB';
            }
            tag.appendChild(small);
            modList.appendChild(tag);
        });
        roster.appendChild(modList);

        // Capacity summary
        if (cap.free_slots > 0 || cap.could_load && cap.could_load.length > 0) {
            var capDiv = document.createElement('div');
            capDiv.className = 'bench-resource-capacity';
            if (cap.free_slots > 0 && cap.ram_available_gb > 5) {
                capDiv.textContent = cap.free_slots + ' slot(s) free \u2022 ' + cap.ram_available_gb + 'GB RAM available';
                if (cap.could_load && cap.could_load.length > 0) {
                    capDiv.textContent += ' \u2022 Could load: ' + cap.could_load.map(function(n) { return n.replace(':latest',''); }).join(', ');
                }
            } else if (cap.free_slots === 0) {
                capDiv.textContent = 'All ' + cap.max_slots + ' model slots in use (OLLAMA_MAX_LOADED_MODELS=' + cap.max_slots + ')';
            }
            roster.appendChild(capDiv);
        }

        bar.appendChild(roster);
    })
    .catch(function() { bar.textContent = 'Resource data unavailable'; });
}

// ── Score Heatmap Matrix ──
function _renderScoreHeatmap(panel) {
    var section = document.createElement('div');
    section.className = 'bench-heatmap-section';
    section.id = 'benchHeatmapSection';
    var loadMsg = document.createElement('div');
    loadMsg.className = 'bench-resource-loading';
    loadMsg.textContent = 'Loading score matrix...';
    section.appendChild(loadMsg);
    panel.appendChild(section);

    fetch('/tools/bridge/api/benchmarks/score-matrix')
    .then(function(r) { return r.json(); })
    .then(function(d) {
        section.textContent = '';
        if (!d.success || !d.stations || d.stations.length === 0) {
            var noData = document.createElement('div');
            noData.className = 'bench-resource-loading';
            noData.textContent = 'No benchmark data available for heatmap.';
            section.appendChild(noData);
            return;
        }

        // Header with auto-place button
        var header = document.createElement('div');
        header.className = 'bench-heatmap-header';
        var title = document.createElement('span');
        title.className = 'bench-heatmap-title';
        title.textContent = 'AGENT \u00D7 STATION SCORE MATRIX';
        header.appendChild(title);

        var autoBtn = document.createElement('button');
        autoBtn.className = 'bench-rec-generate-btn';
        autoBtn.textContent = 'GENERATE OPTIMAL PLACEMENT';
        autoBtn.onclick = function() { _runOptimalPlacement(section); };
        header.appendChild(autoBtn);
        section.appendChild(header);

        // Build heatmap table
        var table = document.createElement('table');
        table.className = 'bench-heatmap-table';

        // Header row
        var thead = document.createElement('thead');
        var hrow = document.createElement('tr');
        var corner = document.createElement('th');
        corner.textContent = 'AGENT';
        hrow.appendChild(corner);
        d.stations.forEach(function(stn) {
            var th = document.createElement('th');
            th.textContent = stn.replace(/_/g, ' ');
            th.title = stn;
            hrow.appendChild(th);
        });
        thead.appendChild(hrow);
        table.appendChild(thead);

        // Filter agents with scores, sort by avg
        var agentsWithScores = d.agents.filter(function(a) { return d.scores[a.name]; });
        agentsWithScores.sort(function(a, b) {
            var aS = d.scores[a.name] || {}, bS = d.scores[b.name] || {};
            var aAvg = 0, aC = 0, bAvg = 0, bC = 0;
            for (var k in aS) { aAvg += aS[k]; aC++; }
            for (var k2 in bS) { bAvg += bS[k2]; bC++; }
            return (bC ? bAvg/bC : 0) - (aC ? aAvg/aC : 0);
        });

        // Body rows
        var tbody = document.createElement('tbody');
        agentsWithScores.forEach(function(agent) {
            var row = document.createElement('tr');
            var nameCell = document.createElement('td');
            nameCell.className = 'bench-heatmap-agent';
            nameCell.textContent = agent.display_name || agent.name;
            row.appendChild(nameCell);

            d.stations.forEach(function(stn) {
                var cell = document.createElement('td');
                var score = (d.scores[agent.name] || {})[stn];
                var isPrimary = false, isAuxiliary = false;
                (d.current_assignments[stn] || []).forEach(function(ca) {
                    if (ca.agent_name === agent.name) {
                        if (ca.type === 'primary') isPrimary = true;
                        else isAuxiliary = true;
                    }
                });
                var isHumanPick = (d.human_picks[agent.name] || {})[stn];

                if (score !== undefined && score !== null) {
                    cell.className = 'bench-heatmap-cell';
                    if (score >= 80) cell.classList.add('score-high');
                    else if (score >= 60) cell.classList.add('score-mid');
                    else cell.classList.add('score-low');
                    if (isPrimary) cell.classList.add('is-primary');
                    if (isAuxiliary) cell.classList.add('is-auxiliary');
                    cell.textContent = score.toFixed(1);
                    if (isHumanPick) {
                        var star = document.createElement('span');
                        star.className = 'bench-heatmap-star';
                        star.textContent = '\u2605';
                        star.title = 'Human Pick';
                        cell.appendChild(star);
                    }
                } else {
                    cell.className = 'bench-heatmap-cell score-none';
                    cell.textContent = '\u2014';
                }
                row.appendChild(cell);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        section.appendChild(table);

        // Legend
        var legend = document.createElement('div');
        legend.className = 'bench-heatmap-legend';
        var legendItems = [
            { cls: 'score-high', text: '80+' },
            { cls: 'score-mid', text: '60-79' },
            { cls: 'score-low', text: '<60' },
            { cls: 'score-none', text: 'No data' }
        ];
        legendItems.forEach(function(li) {
            var item = document.createElement('span');
            item.className = 'bench-legend-item';
            var swatch = document.createElement('span');
            swatch.className = 'bench-legend-swatch ' + li.cls;
            item.appendChild(swatch);
            item.appendChild(document.createTextNode(' ' + li.text));
            legend.appendChild(item);
        });
        // Primary/auxiliary borders
        var pItem = document.createElement('span');
        pItem.className = 'bench-legend-item';
        var pBorder = document.createElement('span');
        pBorder.className = 'bench-legend-border primary';
        pItem.appendChild(pBorder);
        pItem.appendChild(document.createTextNode(' Primary'));
        legend.appendChild(pItem);
        var aItem = document.createElement('span');
        aItem.className = 'bench-legend-item';
        var aBorder = document.createElement('span');
        aBorder.className = 'bench-legend-border auxiliary';
        aItem.appendChild(aBorder);
        aItem.appendChild(document.createTextNode(' Auxiliary'));
        legend.appendChild(aItem);
        var hpItem = document.createElement('span');
        hpItem.className = 'bench-legend-item';
        hpItem.textContent = '\u2605 Human Pick';
        legend.appendChild(hpItem);
        section.appendChild(legend);
    })
    .catch(function(err) {
        section.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.className = 'bench-resource-loading';
        errDiv.textContent = 'Failed to load score matrix';
        section.appendChild(errDiv);
        console.error('Heatmap load error:', err);
    });
}

// ── Optimal Placement ──
function _runOptimalPlacement(container) {
    var overlay = document.getElementById('benchPlacementOverlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'benchPlacementOverlay';
    overlay.className = 'bench-placement-overlay';
    var loadMsg = document.createElement('div');
    loadMsg.className = 'bench-resource-loading';
    loadMsg.textContent = 'Generating optimal placement...';
    overlay.appendChild(loadMsg);
    container.appendChild(overlay);

    fetch('/tools/bridge/api/benchmarks/placement/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (!d.success) {
            overlay.textContent = '';
            var errMsg = document.createElement('div');
            errMsg.className = 'bench-resource-loading';
            errMsg.textContent = 'Failed: ' + (d.error || 'Unknown error');
            overlay.appendChild(errMsg);
            return;
        }

        overlay.textContent = '';

        // Header with approve/cancel
        var header = document.createElement('div');
        header.className = 'bench-placement-header';
        var headerTitle = document.createElement('span');
        headerTitle.className = 'bench-heatmap-title';
        headerTitle.textContent = 'PROPOSED OPTIMAL PLACEMENT';
        header.appendChild(headerTitle);

        var actions = document.createElement('div');
        actions.className = 'bench-placement-actions';

        var applyBtn = document.createElement('button');
        applyBtn.className = 'bench-rec-approve-btn';
        applyBtn.textContent = 'APPROVE & APPLY';
        applyBtn.onclick = function() {
            applyBtn.disabled = true;
            applyBtn.textContent = 'APPLYING...';
            fetch('/tools/bridge/api/benchmarks/placement/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(d)
            })
            .then(function(r) { return r.json(); })
            .then(function(result) {
                if (result.success) {
                    overlay.remove();
                    loadConsoleBenchmarks();
                    loadStations();  // Refresh isometric view with new assignments
                } else {
                    applyBtn.textContent = 'FAILED';
                    setTimeout(function() { applyBtn.textContent = 'APPROVE & APPLY'; applyBtn.disabled = false; }, 2000);
                }
            })
            .catch(function() { applyBtn.textContent = 'ERROR'; applyBtn.disabled = false; });
        };
        actions.appendChild(applyBtn);

        var cancelBtn = document.createElement('button');
        cancelBtn.className = 'bench-rec-reject-btn';
        cancelBtn.textContent = 'CANCEL';
        cancelBtn.onclick = function() { overlay.remove(); };
        actions.appendChild(cancelBtn);
        header.appendChild(actions);
        overlay.appendChild(header);

        // Placement cards grid
        var grid = document.createElement('div');
        grid.className = 'bench-placement-grid';

        d.placements.forEach(function(p) {
            var card = document.createElement('div');
            card.className = 'bench-placement-card';
            if (p.changed) card.classList.add('changed');

            var stnName = document.createElement('div');
            stnName.className = 'bench-placement-station';
            stnName.textContent = p.station_code.replace(/_/g, ' ');
            if (p.human_locked) {
                var lock = document.createElement('span');
                lock.textContent = ' \uD83D\uDD12';
                lock.title = 'Human-locked';
                stnName.appendChild(lock);
            }
            card.appendChild(stnName);

            var currentName = p.current_primary ? (p.current_primary.display_name || p.current_primary.agent_name) : 'None';
            var proposedName = p.primary ? (p.primary.display_name || p.primary.agent_name) : 'None';
            var proposedScore = p.primary ? p.primary.avg_score : 0;

            var detail = document.createElement('div');
            detail.className = 'bench-placement-detail';

            if (p.changed) {
                var curDiv = document.createElement('div');
                curDiv.className = 'bench-placement-current';
                curDiv.textContent = 'Current: ';
                var curStrong = document.createElement('strong');
                curStrong.textContent = currentName;
                curDiv.appendChild(curStrong);
                detail.appendChild(curDiv);

                var arrow = document.createElement('div');
                arrow.className = 'bench-placement-arrow';
                arrow.textContent = '\u2192';
                detail.appendChild(arrow);

                var propDiv = document.createElement('div');
                propDiv.className = 'bench-placement-proposed';
                propDiv.textContent = 'Proposed: ';
                var propStrong = document.createElement('strong');
                propStrong.textContent = proposedName;
                propDiv.appendChild(propStrong);
                var scoreSpan = document.createElement('span');
                scoreSpan.className = 'bench-placement-score';
                scoreSpan.textContent = ' ' + proposedScore.toFixed(1);
                propDiv.appendChild(scoreSpan);
                detail.appendChild(propDiv);
            } else {
                var optDiv = document.createElement('div');
                optDiv.className = 'bench-placement-current';
                optDiv.textContent = 'Current: ';
                var optStrong = document.createElement('strong');
                optStrong.textContent = currentName;
                optDiv.appendChild(optStrong);
                var checkMark = document.createElement('span');
                checkMark.className = 'bench-placement-optimal';
                checkMark.textContent = ' \u2713 OPTIMAL';
                optDiv.appendChild(checkMark);
                detail.appendChild(optDiv);
            }
            card.appendChild(detail);

            if (p.secondary) {
                var secDiv = document.createElement('div');
                secDiv.className = 'bench-placement-secondary';
                secDiv.textContent = 'Secondary: ' + (p.secondary.display_name || p.secondary.agent_name) + ' (' + p.secondary.avg_score.toFixed(1) + ')';
                card.appendChild(secDiv);
            }

            grid.appendChild(card);
        });
        overlay.appendChild(grid);

        if (d.unassigned && d.unassigned.length > 0) {
            var unDiv = document.createElement('div');
            unDiv.className = 'bench-placement-unassigned';
            unDiv.textContent = 'Auxiliary pool: ' + d.unassigned.map(function(a) { return a.display_name || a.name; }).join(', ');
            overlay.appendChild(unDiv);
        }
    })
    .catch(function(err) {
        overlay.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.className = 'bench-resource-loading';
        errDiv.textContent = 'Error generating placement';
        overlay.appendChild(errDiv);
        console.error('Placement error:', err);
    });
}

function _loadBenchmarkOverview(panel) {
    Promise.all([
        fetch('/tools/bridge/api/stations').then(function(r) { return r.json(); }),
        fetch('/tools/bridge/api/station-actions').then(function(r) { return r.json(); }),
        fetch('/tools/bridge/api/bridge/jobs?status=running').then(function(r) { return r.json(); }).catch(function() { return { success: true, jobs: [] }; })
    ]).then(function(results) {
        var stationsData = results[0];
        var actData = results[1];
        var jobData = results[2];

        var stations = (stationsData.success && stationsData.stations) ? stationsData.stations : [];
        var allActions = (actData.success && actData.actions) ? actData.actions : [];
        var runningJobs = (jobData.success && jobData.jobs) ? jobData.jobs : [];

        // Index actions by station_code
        var actionsByStation = {};
        allActions.forEach(function(a) {
            if (!actionsByStation[a.station_code]) actionsByStation[a.station_code] = [];
            actionsByStation[a.station_code].push(a);
        });

        // Index jobs by station_code
        var jobsByStation = {};
        runningJobs.forEach(function(j) {
            var sc = j.station_code || '';
            if (!jobsByStation[sc]) jobsByStation[sc] = [];
            jobsByStation[sc].push(j);
        });

        // Viewscreen colors — the canonical station colors from the bridge map
        var VIEWSCREEN_COLORS = {
            COMMAND: '#FFD700',
            OPERATIONS: '#FF8C00',
            CREATIVE: '#FF69B4',
            ENGINEERING: '#32CD32',
            ANALYTICS: '#00CED1',
            RESEARCH: '#6495ED',
            DOCUMENTATION: '#8B5CF6',
            RND_AI: '#06B6D4',
            SUPPORT: '#F43F5E',
            QA: '#10B981'
        };

        // Show all stations — COMMAND first, then alphabetical
        var stationsToShow = stations.slice().sort(function(a, b) {
            if (a.code === 'COMMAND') return -1;
            if (b.code === 'COMMAND') return 1;
            return a.code.localeCompare(b.code);
        });

        if (stationsToShow.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'stn-ops-loading';
            empty.style.cssText = 'padding:20px;text-align:center;';
            empty.textContent = 'No stations to display';
            panel.appendChild(empty);
            return;
        }

        // Color helper — extract RGB from hex
        function hexToRgb(hex) {
            hex = hex.replace('#', '');
            if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
            var r = parseInt(hex.substring(0,2),16);
            var g = parseInt(hex.substring(2,4),16);
            var b = parseInt(hex.substring(4,6),16);
            return r+','+g+','+b;
        }

        // ── Recommendations Panel (top of COMMAND overview) ──
        _renderRecommendationsPanel(panel, VIEWSCREEN_COLORS);

        stationsToShow.forEach(function(stn) {
            var stnColor = VIEWSCREEN_COLORS[stn.code] || stn.color || '#00ffff';
            var stnRgb = hexToRgb(stnColor);
            var agents = stn.assigned_agents || [];
            var stnJobs = jobsByStation[stn.code] || [];
            var stnActions = actionsByStation[stn.code] || [];
            var crewCount = agents.length;
            var maxCrew = stn.max_primary || 2;

            // Terminal container
            var terminal = document.createElement('div');
            terminal.className = 'stn-ops-terminal';
            terminal.style.setProperty('--stn-accent', stnColor);
            terminal.style.setProperty('--stn-accent-rgb', stnRgb);

            // Header
            var header = document.createElement('div');
            header.className = 'stn-ops-header';
            var elbow = document.createElement('div');
            elbow.className = 'stn-ops-elbow';
            header.appendChild(elbow);
            var title = document.createElement('div');
            title.className = 'stn-ops-title';
            title.textContent = (stn.name || stn.code).toUpperCase();
            header.appendChild(title);
            var status = document.createElement('div');
            status.className = 'stn-ops-status';
            var dot = document.createElement('span');
            dot.className = 'stn-ops-dot';
            if (stnJobs.length > 0) {
                dot.style.background = '#f59e0b';
                dot.style.boxShadow = '0 0 4px #f59e0b';
            }
            status.appendChild(dot);
            status.appendChild(document.createTextNode(stnJobs.length > 0 ? ' ACTIVE' : crewCount > 0 ? ' ONLINE' : ' UNMANNED'));
            header.appendChild(status);
            terminal.appendChild(header);

            // Body
            var body = document.createElement('div');
            body.className = 'stn-ops-body';

            // Crew row (compact — single line per agent)
            var crewLabel = document.createElement('div');
            crewLabel.className = 'stn-ops-section-label';
            crewLabel.textContent = 'CREW (' + crewCount + '/' + maxCrew + ')';
            body.appendChild(crewLabel);

            if (crewCount > 0) {
                agents.forEach(function(a) {
                    var row = document.createElement('div');
                    row.className = 'stn-ops-agent-row';
                    var name = document.createElement('span');
                    name.className = 'stn-ops-agent-name';
                    name.textContent = (a.first_name && a.last_name) ? a.first_name + ' ' + a.last_name : (a.name || 'Agent');
                    row.appendChild(name);
                    // Check if this agent has a running job
                    var agentJob = stnJobs.find(function(j) { return j.agent_callsign === a.name || j.agent_display_name === (a.first_name + ' ' + a.last_name); });
                    if (agentJob) {
                        var badge = document.createElement('span');
                        badge.className = 'stn-ops-agent-badge working';
                        badge.textContent = 'WORKING';
                        row.appendChild(badge);
                    }
                    var role = document.createElement('span');
                    role.className = 'stn-ops-agent-role';
                    role.textContent = a.title || a.assignment_type || 'agent';
                    row.appendChild(role);
                    body.appendChild(row);
                });
            } else {
                var noAgent = document.createElement('div');
                noAgent.className = 'stn-ops-loading';
                noAgent.textContent = 'No crew assigned';
                body.appendChild(noAgent);
            }

            // Active jobs
            if (stnJobs.length > 0) {
                var jobLabel = document.createElement('div');
                jobLabel.className = 'stn-ops-section-label';
                jobLabel.style.marginTop = '10px';
                jobLabel.textContent = 'ACTIVE JOBS (' + stnJobs.length + ')';
                body.appendChild(jobLabel);

                stnJobs.forEach(function(j) {
                    var pct = j.total_steps > 0 ? Math.round(((j.completed_steps || 0) / j.total_steps) * 100) : 0;
                    var row = document.createElement('div');
                    row.className = 'stn-ops-job-row';

                    var info = document.createElement('div');
                    info.className = 'stn-ops-job-info';
                    var desc = document.createElement('div');
                    desc.className = 'stn-ops-job-desc';
                    desc.textContent = j.description || j.job_type || 'Processing';
                    info.appendChild(desc);
                    row.appendChild(info);

                    var bar = document.createElement('div');
                    bar.className = 'stn-ops-job-bar';
                    var fill = document.createElement('div');
                    fill.className = 'stn-ops-job-fill';
                    fill.style.width = pct + '%';
                    bar.appendChild(fill);
                    row.appendChild(bar);

                    var cnt = document.createElement('div');
                    cnt.className = 'stn-ops-job-count';
                    cnt.textContent = (j.completed_steps || 0) + '/' + (j.total_steps || 0);
                    row.appendChild(cnt);

                    var pctEl = document.createElement('div');
                    pctEl.className = 'stn-ops-job-pct';
                    pctEl.textContent = pct + '%';
                    row.appendChild(pctEl);

                    body.appendChild(row);
                });
            }

            // Action buttons — one 3-col row per action
            if (stnActions.length > 0) {
                var cmds = document.createElement('div');
                cmds.className = 'stn-ops-commands';

                stnActions.forEach(function(action) {
                    var hasParams = action.params_schema && action.params_schema.length > 0;
                    var isRunning = stnJobs.some(function(j) { return j.job_type === action.job_type; });

                    // Row wrapper: ACTION | TEST | RESULTS
                    var row = document.createElement('div');
                    row.className = 'stn-action-row';

                    // Col 1: Action button — use station-accent to match station color
                    var btn = document.createElement('button');
                    btn.className = 'stn-ops-cmd station-accent';
                    btn.textContent = action.label;
                    btn.title = action.description || '';
                    btn.dataset.actionKey = action.action_key;
                    if (isRunning) {
                        btn.disabled = true;
                        btn.textContent = action.label + ' \u25B6';
                    }
                    if (hasParams) {
                        btn.addEventListener('click', (function(ak) {
                            return function() { toggleActionParams(ak, this); };
                        })(action.action_key));
                    } else {
                        btn.addEventListener('click', (function(a) {
                            return function() { executeStationAction(a.action_key, a.endpoint_path, a.http_method || 'POST', a.creates_job, this); };
                        })(action));
                    }
                    row.appendChild(btn);

                    // Col 2: TEST button
                    if (action.test_config) {
                        var tbtn = document.createElement('button');
                        tbtn.className = 'stn-bench-btn';
                        tbtn.textContent = 'TEST';
                        tbtn.title = 'Benchmark: ' + (action.test_config.description || action.label);
                        tbtn.dataset.actionKey = action.action_key;
                        tbtn.addEventListener('click', (function(ak) {
                            return function() { startActionBenchmark(ak, this); };
                        })(action.action_key));
                        row.appendChild(tbtn);
                    }

                    // Col 3: RESULTS button
                    if (action.test_config) {
                        var rbtn = document.createElement('button');
                        rbtn.className = 'stn-bench-results-btn no-results';
                        rbtn.textContent = 'RESULTS';
                        rbtn.title = 'View latest benchmark results';
                        rbtn.dataset.actionKey = action.action_key;
                        rbtn.addEventListener('click', (function(ak) {
                            return function() { loadLatestBenchmark(ak); };
                        })(action.action_key));
                        row.appendChild(rbtn);
                    }

                    cmds.appendChild(row);

                    // Benchmark container after each row
                    if (action.test_config) {
                        var benchEl = document.createElement('div');
                        benchEl.id = 'bench-' + action.action_key;
                        benchEl.className = 'bench-container';
                        cmds.appendChild(benchEl);
                        _checkExistingBenchmark(action.action_key);
                    }
                });

                body.appendChild(cmds);

                // Params forms
                stnActions.forEach(function(action) {
                    if (!action.params_schema || action.params_schema.length === 0) return;
                    var paramsDiv = document.createElement('div');
                    paramsDiv.className = 'actn-params';
                    paramsDiv.id = 'params-' + action.action_key;
                    action.params_schema.forEach(function(p) {
                        var field = document.createElement('div');
                        field.className = 'actn-field';
                        var lbl = document.createElement('label');
                        lbl.textContent = p.label || p.key;
                        field.appendChild(lbl);
                        if (p.options && p.options.length) {
                            var sel = document.createElement('select');
                            sel.dataset.param = p.key;
                            p.options.forEach(function(opt) {
                                var o = document.createElement('option');
                                o.value = opt; o.textContent = opt;
                                sel.appendChild(o);
                            });
                            field.appendChild(sel);
                        } else {
                            var inp = document.createElement('input');
                            inp.type = p.type === 'number' ? 'number' : 'text';
                            inp.dataset.param = p.key;
                            inp.value = p.default != null ? p.default : '';
                            inp.placeholder = p.label || p.key;
                            field.appendChild(inp);
                        }
                        paramsDiv.appendChild(field);
                    });
                    body.appendChild(paramsDiv);
                });

                // Job progress placeholders
                stnActions.forEach(function(action) {
                    var jobEl = document.createElement('div');
                    jobEl.id = 'job-' + action.action_key;
                    body.appendChild(jobEl);
                });

                // Auto-attach polls for running jobs
                stnJobs.forEach(function(j) {
                    var match = stnActions.find(function(a) { return a.job_type === j.job_type; });
                    if (match) {
                        var mbtn = cmds.querySelector('[data-action-key="' + match.action_key + '"]');
                        _startActionJobPoll(match.action_key, j.id, mbtn);
                    }
                });
            } else {
                // Station has no registered actions — show modules list
                var mods = stn.modules || [];
                if (mods.length > 0) {
                    var modLabel = document.createElement('div');
                    modLabel.className = 'stn-ops-section-label';
                    modLabel.style.marginTop = '10px';
                    modLabel.textContent = 'MODULES (' + mods.length + ')';
                    body.appendChild(modLabel);
                    var modText = document.createElement('div');
                    modText.className = 'stn-ops-loading';
                    modText.textContent = mods.map(function(m) { return m.replace(/_/g, ' '); }).join(' \u2022 ');
                    body.appendChild(modText);
                }
            }

            terminal.appendChild(body);
            panel.appendChild(terminal);
        });
    }).catch(function(err) {
        console.error('Command overview error:', err);
        var errEl = document.createElement('div');
        errEl.className = 'stn-ops-loading';
        errEl.style.cssText = 'padding:20px;text-align:center;';
        errEl.textContent = 'Failed to load station overview';
        panel.appendChild(errEl);
    });
}

// ── Benchmark Recommendations Panel (COMMAND overview) ──

function _renderRecommendationsPanel(panel, VIEWSCREEN_COLORS) {
    var section = document.createElement('div');
    section.className = 'bench-rec-section';
    section.id = 'benchRecSection';

    // Header
    var header = document.createElement('div');
    header.className = 'bench-rec-header';

    var title = document.createElement('span');
    title.textContent = 'STATION ASSIGNMENT RECOMMENDATIONS';
    header.appendChild(title);

    var headerActions = document.createElement('div');
    headerActions.className = 'bench-rec-header-actions';

    var genBtn = document.createElement('button');
    genBtn.className = 'bench-rec-generate-btn';
    genBtn.textContent = 'GENERATE';
    genBtn.onclick = function() {
        genBtn.textContent = 'GENERATING...';
        genBtn.disabled = true;
        fetch('/tools/bridge/api/benchmarks/recommendations/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            genBtn.textContent = 'GENERATE';
            genBtn.disabled = false;
            if (d.success) {
                _loadRecommendationsContent(body, VIEWSCREEN_COLORS);
            }
        })
        .catch(function() { genBtn.textContent = 'GENERATE'; genBtn.disabled = false; });
    };
    headerActions.appendChild(genBtn);
    header.appendChild(headerActions);
    section.appendChild(header);

    // Body
    var body = document.createElement('div');
    body.className = 'bench-rec-body';
    body.id = 'benchRecBody';
    section.appendChild(body);

    panel.appendChild(section);

    // Load content
    _loadRecommendationsContent(body, VIEWSCREEN_COLORS);
}

function _loadRecommendationsContent(body, VIEWSCREEN_COLORS) {
    body.textContent = '';
    var loading = document.createElement('div');
    loading.className = 'bench-rec-empty';
    loading.textContent = 'Loading recommendations...';
    body.appendChild(loading);

    fetch('/tools/bridge/api/benchmarks/station-summary')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        body.textContent = '';
        if (!data.success || !data.stations || data.stations.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'bench-rec-empty';
            empty.textContent = 'No benchmark data available. Run benchmarks first to generate recommendations.';
            body.appendChild(empty);
            return;
        }

        data.stations.forEach(function(stn) {
            var card = document.createElement('div');
            card.className = 'bench-rec-card';

            var stnColor = VIEWSCREEN_COLORS[stn.station_code] || '#00ffff';

            // Station name row
            var nameEl = document.createElement('div');
            nameEl.className = 'bench-rec-station-name';
            nameEl.style.color = stnColor;
            var stnLabel = stn.station_code.replace(/_/g, ' ');
            nameEl.textContent = stnLabel;

            // Add action count + benchmark date
            if (stn.action_count || stn.latest_benchmark) {
                var meta = document.createElement('span');
                meta.style.cssText = 'font-family:"IBM Plex Mono",monospace;font-size:0.45rem;color:rgba(255,255,255,0.3);margin-left:8px;letter-spacing:0.04em;';
                var parts = [];
                if (stn.action_count) parts.push(stn.action_count + ' actions');
                if (stn.latest_benchmark) {
                    var d = new Date(stn.latest_benchmark);
                    parts.push('last bench: ' + d.toLocaleDateString());
                }
                meta.textContent = parts.join(' \u2022 ');
                nameEl.appendChild(meta);
            }
            card.appendChild(nameEl);

            // Pending recommendation alert
            var rec = stn.pending_recommendation;
            if (rec) {
                var alert = document.createElement('div');
                alert.className = 'bench-rec-alert';

                var icon = document.createElement('span');
                icon.className = 'bench-rec-alert-icon';
                icon.textContent = '\u26A0';
                alert.appendChild(icon);

                var text = document.createElement('div');
                text.className = 'bench-rec-alert-text';

                // Build alert text safely with DOM (no innerHTML)
                var recName = rec.recommended_agent_name;
                var top3 = rec.top_3 || [];
                if (top3.length > 0 && top3[0].display_name) recName = top3[0].display_name;

                text.appendChild(document.createTextNode('Benchmark suggests '));
                var strong = document.createElement('strong');
                strong.textContent = recName;
                text.appendChild(strong);
                text.appendChild(document.createTextNode(' for ' + stnLabel));
                if (rec.score_delta > 0) {
                    text.appendChild(document.createTextNode(' (+' + rec.score_delta.toFixed(1) + ' pts)'));
                }
                alert.appendChild(text);

                var actions = document.createElement('div');
                actions.className = 'bench-rec-alert-actions';

                var approveBtn = document.createElement('button');
                approveBtn.className = 'bench-rec-approve-btn';
                approveBtn.textContent = 'APPROVE';
                approveBtn.onclick = function() {
                    _resolveRecommendation(rec.id, true, body, VIEWSCREEN_COLORS);
                };
                actions.appendChild(approveBtn);

                var rejectBtn = document.createElement('button');
                rejectBtn.className = 'bench-rec-reject-btn';
                rejectBtn.textContent = 'REJECT';
                rejectBtn.onclick = function() {
                    _resolveRecommendation(rec.id, false, body, VIEWSCREEN_COLORS);
                };
                actions.appendChild(rejectBtn);

                alert.appendChild(actions);
                card.appendChild(alert);
            }

            // Top 3 agent rows
            var top3Data = rec ? (rec.top_3 || []) : [];
            var currentAgents = stn.assigned_agents || [];
            var currentNames = currentAgents.map(function(a) { return a.name; });

            if (top3Data.length > 0) {
                var top3El = document.createElement('div');
                top3El.className = 'bench-rec-top3';

                top3Data.forEach(function(agent, idx) {
                    var row = document.createElement('div');
                    row.className = 'bench-rec-agent-row';
                    if (currentNames.indexOf(agent.agent_name) !== -1) {
                        row.classList.add('rec-current');
                    }
                    if (idx === 0 && rec) {
                        row.classList.add('rec-recommended');
                    }

                    var rankEl = document.createElement('span');
                    rankEl.className = 'bench-rec-rank';
                    rankEl.textContent = '#' + (idx + 1);
                    row.appendChild(rankEl);

                    var nameSpan = document.createElement('span');
                    nameSpan.className = 'bench-rec-agent-name';
                    nameSpan.textContent = agent.display_name || agent.agent_name;
                    if (currentNames.indexOf(agent.agent_name) !== -1) {
                        var curLabel = document.createElement('span');
                        curLabel.className = 'bench-rec-current-label';
                        curLabel.textContent = 'CURRENT';
                        nameSpan.appendChild(curLabel);
                    }
                    row.appendChild(nameSpan);

                    var scoreEl = document.createElement('span');
                    scoreEl.className = 'bench-rec-score';
                    scoreEl.textContent = (agent.avg_score || 0).toFixed(1);
                    row.appendChild(scoreEl);

                    var hpEl = document.createElement('span');
                    hpEl.className = 'bench-rec-hp';
                    hpEl.textContent = agent.human_pick ? '\u2605' : '';
                    row.appendChild(hpEl);

                    top3El.appendChild(row);
                });

                card.appendChild(top3El);
            } else if (currentAgents.length > 0) {
                // No benchmark data, just show current assignment
                var curRow = document.createElement('div');
                curRow.style.cssText = 'padding:4px 6px;font-family:"IBM Plex Mono",monospace;font-size:0.55rem;color:rgba(255,255,255,0.4);';
                curRow.textContent = 'Assigned: ' + currentAgents.map(function(a) { return a.display_name || a.name; }).join(', ') + ' \u2022 No benchmarks yet';
                card.appendChild(curRow);
            } else {
                var noData = document.createElement('div');
                noData.style.cssText = 'padding:4px 6px;font-family:"IBM Plex Mono",monospace;font-size:0.55rem;color:rgba(255,255,255,0.25);';
                noData.textContent = 'No assignments \u2022 No benchmarks yet';
                card.appendChild(noData);
            }

            body.appendChild(card);
        });
    })
    .catch(function(err) {
        body.textContent = '';
        var errEl = document.createElement('div');
        errEl.className = 'bench-rec-empty';
        errEl.textContent = 'Failed to load recommendations';
        body.appendChild(errEl);
        console.error('Recommendations load error:', err);
    });
}

function _resolveRecommendation(recId, approved, body, VIEWSCREEN_COLORS) {
    fetch('/tools/bridge/api/benchmarks/recommendations/' + recId + '/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: approved })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.success) {
            // Reload recommendations
            _loadRecommendationsContent(body, VIEWSCREEN_COLORS);
            // If approved, also refresh the station overview to show new assignments
            if (approved) {
                setTimeout(function() { loadConsoleActions(); }, 500);
            }
        }
    })
    .catch(function(err) {
        console.error('Resolve recommendation error:', err);
    });
}

// ── Standard per-module action rendering (non-COMMAND zones) ──

function _renderModuleActions(panel, actData, jobData) {
    var runningJobs = (jobData.success && jobData.jobs) ? jobData.jobs : [];

    if (!actData.success || !actData.actions || actData.actions.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'stn-ops-loading';
        empty.style.cssText = 'padding:20px 12px;text-align:center;';
        empty.textContent = 'No registered actions for this station';
        panel.appendChild(empty);
        return;
    }

    // Group by module_source
    var groups = {};
    actData.actions.forEach(function(a) {
        if (!groups[a.module_source]) groups[a.module_source] = [];
        groups[a.module_source].push(a);
    });

    var colorMap = {
        green: { hex: '#32CD32', rgb: '50,205,50' },
        cyan: { hex: '#00CED1', rgb: '0,206,209' },
        purple: { hex: '#8b5cf6', rgb: '139,92,246' },
        gold: { hex: '#FFD700', rgb: '255,215,0' },
        orange: { hex: '#FF8C00', rgb: '255,140,0' },
        pink: { hex: '#FF69B4', rgb: '255,105,180' },
        red: { hex: '#ef4444', rgb: '239,68,68' },
        blue: { hex: '#6495ED', rgb: '100,149,237' }
    };

    var runMap = {};
    runningJobs.forEach(function(j) {
        if (!runMap[j.module_source]) runMap[j.module_source] = [];
        runMap[j.module_source].push(j);
    });

    for (var mod in groups) {
        var actions = groups[mod];
        var firstColor = colorMap[actions[0].color_class] || { hex: 'var(--station-color,#00ffff)', rgb: '0,206,209' };
        var modRunning = runMap[mod] || [];
        var modLabel = mod.replace(/_/g, ' ').toUpperCase();

        var terminal = document.createElement('div');
        terminal.className = 'stn-ops-terminal';
        terminal.style.setProperty('--stn-accent', firstColor.hex);
        terminal.style.setProperty('--stn-accent-rgb', firstColor.rgb);

        // Header
        var header = document.createElement('div');
        header.className = 'stn-ops-header';
        var elbow = document.createElement('div');
        elbow.className = 'stn-ops-elbow';
        header.appendChild(elbow);
        var title = document.createElement('div');
        title.className = 'stn-ops-title';
        title.textContent = modLabel + ' OPERATIONS';
        header.appendChild(title);
        var status = document.createElement('div');
        status.className = 'stn-ops-status';
        var dot = document.createElement('span');
        dot.className = 'stn-ops-dot';
        if (modRunning.length > 0) { dot.style.background = '#f59e0b'; dot.style.boxShadow = '0 0 4px #f59e0b'; }
        status.appendChild(dot);
        status.appendChild(document.createTextNode(modRunning.length > 0 ? ' ACTIVE' : ' READY'));
        header.appendChild(status);
        terminal.appendChild(header);

        var body = document.createElement('div');
        body.className = 'stn-ops-body';

        // Summary
        var summary = document.createElement('div');
        summary.className = 'actn-summary';
        var s1 = document.createElement('span'); s1.className = 'actn-stat';
        var b1 = document.createElement('b'); b1.textContent = actions.length;
        s1.appendChild(b1); s1.appendChild(document.createTextNode(' actions'));
        summary.appendChild(s1);
        if (modRunning.length > 0) {
            var s2 = document.createElement('span'); s2.className = 'actn-stat';
            var b2 = document.createElement('b'); b2.textContent = modRunning.length; b2.style.color = '#f59e0b';
            s2.appendChild(b2); s2.appendChild(document.createTextNode(' running'));
            summary.appendChild(s2);
        }
        body.appendChild(summary);

        // Running jobs
        if (modRunning.length > 0) {
            modRunning.forEach(function(j) {
                var pct = j.total_steps > 0 ? Math.round(((j.completed_steps || 0) / j.total_steps) * 100) : 0;
                var row = document.createElement('div'); row.className = 'stn-ops-job-row';
                var info = document.createElement('div'); info.className = 'stn-ops-job-info';
                var desc = document.createElement('div'); desc.className = 'stn-ops-job-desc';
                desc.textContent = j.description || j.job_type || 'Processing'; info.appendChild(desc);
                var agent = document.createElement('div'); agent.className = 'stn-ops-job-agent';
                agent.textContent = j.agent_display_name || j.agent_name || 'Queued'; info.appendChild(agent);
                row.appendChild(info);
                var bar = document.createElement('div'); bar.className = 'stn-ops-job-bar';
                var fill = document.createElement('div'); fill.className = 'stn-ops-job-fill'; fill.style.width = pct + '%';
                bar.appendChild(fill); row.appendChild(bar);
                var pctEl = document.createElement('div'); pctEl.className = 'stn-ops-job-pct'; pctEl.textContent = pct + '%';
                row.appendChild(pctEl);
                body.appendChild(row);
            });
        }

        // Command buttons — one 3-col row per action
        var cmds = document.createElement('div');
        cmds.className = 'stn-ops-commands';
        actions.forEach(function(action) {
            var hasParams = action.params_schema && action.params_schema.length > 0;
            var isRunning = modRunning.some(function(j) { return j.job_type === action.job_type; });

            // Row wrapper: ACTION | TEST | RESULTS
            var row = document.createElement('div');
            row.className = 'stn-action-row';

            // Col 1: Action button — use station-accent to match station color
            var btn = document.createElement('button');
            btn.className = 'stn-ops-cmd station-accent';
            btn.textContent = action.label; btn.title = action.description || '';
            btn.dataset.actionKey = action.action_key;
            if (isRunning) { btn.disabled = true; btn.textContent = action.label + ' \u25B6'; }
            if (hasParams) {
                btn.addEventListener('click', (function(ak) { return function() { toggleActionParams(ak, this); }; })(action.action_key));
            } else {
                btn.addEventListener('click', (function(a) { return function() { executeStationAction(a.action_key, a.endpoint_path, a.http_method || 'POST', a.creates_job, this); }; })(action));
            }
            row.appendChild(btn);

            // Col 2: TEST button
            if (action.test_config) {
                var tbtn = document.createElement('button');
                tbtn.className = 'stn-bench-btn';
                tbtn.textContent = 'TEST';
                tbtn.title = 'Benchmark: ' + (action.test_config.description || action.label);
                tbtn.dataset.actionKey = action.action_key;
                tbtn.addEventListener('click', (function(ak) {
                    return function() { startActionBenchmark(ak, this); };
                })(action.action_key));
                row.appendChild(tbtn);
            }

            // Col 3: RESULTS button
            if (action.test_config) {
                var rbtn = document.createElement('button');
                rbtn.className = 'stn-bench-results-btn no-results';
                rbtn.textContent = 'RESULTS';
                rbtn.title = 'View latest benchmark results';
                rbtn.dataset.actionKey = action.action_key;
                rbtn.addEventListener('click', (function(ak) {
                    return function() { loadLatestBenchmark(ak); };
                })(action.action_key));
                row.appendChild(rbtn);
            }

            cmds.appendChild(row);

            // Benchmark container after each row
            if (action.test_config) {
                var benchEl = document.createElement('div');
                benchEl.id = 'bench-' + action.action_key;
                benchEl.className = 'bench-container';
                cmds.appendChild(benchEl);
                _checkExistingBenchmark(action.action_key);
            }
        });
        body.appendChild(cmds);

        // If we already know a benchmark is running, apply state to new buttons
        // Otherwise check the server
        if (_activeBenchmarkRun) {
            setTimeout(_applyBenchmarkState, 100);
        } else {
            setTimeout(_checkActiveBenchmark, 500);
        }

        // Params forms + job placeholders
        actions.forEach(function(action) {
            if (action.params_schema && action.params_schema.length > 0) {
                var paramsDiv = document.createElement('div');
                paramsDiv.className = 'actn-params'; paramsDiv.id = 'params-' + action.action_key;
                action.params_schema.forEach(function(p) {
                    var field = document.createElement('div'); field.className = 'actn-field';
                    var lbl = document.createElement('label'); lbl.textContent = p.label || p.key; field.appendChild(lbl);
                    if (p.options && p.options.length) {
                        var sel = document.createElement('select'); sel.dataset.param = p.key;
                        p.options.forEach(function(opt) { var o = document.createElement('option'); o.value = opt; o.textContent = opt; sel.appendChild(o); });
                        field.appendChild(sel);
                    } else {
                        var inp = document.createElement('input'); inp.type = p.type === 'number' ? 'number' : 'text';
                        inp.dataset.param = p.key; inp.value = p.default != null ? p.default : ''; inp.placeholder = p.label || p.key;
                        field.appendChild(inp);
                    }
                    paramsDiv.appendChild(field);
                });
                body.appendChild(paramsDiv);
            }
            var jobEl = document.createElement('div'); jobEl.id = 'job-' + action.action_key;
            body.appendChild(jobEl);
        });

        terminal.appendChild(body);
        panel.appendChild(terminal);

        // Auto-attach polls
        modRunning.forEach(function(j) {
            var match = actions.find(function(a) { return a.job_type === j.job_type; });
            if (match) {
                var mbtn = cmds.querySelector('[data-action-key="' + match.action_key + '"]');
                _startActionJobPoll(match.action_key, j.id, mbtn);
            }
        });
    }
}

function toggleActionParams(actionKey, btn) {
    var paramsEl = document.getElementById('params-' + actionKey);
    if (!paramsEl) return;

    if (paramsEl.classList.contains('open')) {
        // Gather params and execute
        var params = {};
        paramsEl.querySelectorAll('[data-param]').forEach(function(input) {
            if (input.value) params[input.dataset.param] = input.value;
        });
        // Find action details from cached data
        var codes = _consoleCurrentZone ? _consoleCurrentZone.zoneInfo.stations.join(',') : '';
        fetch('/tools/bridge/api/station-actions?station_code=' + encodeURIComponent(codes))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var action = (data.actions || []).find(function(a) { return a.action_key === actionKey; });
                if (action) {
                    executeStationAction(actionKey, action.endpoint_path, action.http_method || 'POST', action.creates_job, btn, params);
                }
            });
        paramsEl.classList.remove('open');
    } else {
        paramsEl.classList.add('open');
        var firstInput = paramsEl.querySelector('input, select');
        if (firstInput) firstInput.focus();
    }
}

function executeStationAction(actionKey, endpointPath, httpMethod, createsJob, btn, params) {
    if (btn) { btn.disabled = true; var origText = btn.textContent; btn.textContent = origText + ' \u25B6'; }

    var fetchOpts = { method: httpMethod || 'POST', headers: { 'Content-Type': 'application/json' } };
    if (params && Object.keys(params).length > 0) fetchOpts.body = JSON.stringify(params);

    fetch(endpointPath, fetchOpts)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var jobEl = document.getElementById('job-' + actionKey);
            if (data.success === false) {
                if (jobEl) { jobEl.textContent = data.error || 'Action failed'; jobEl.style.cssText = 'color:#ef4444;font-size:0.7rem;padding:4px 0;'; }
                if (btn) { btn.disabled = false; btn.textContent = btn.textContent.replace(' \u25B6', ''); }
                return;
            }
            var jobId = data.job_id || data.jobId || data.id;
            if (createsJob && jobId) {
                _startActionJobPoll(actionKey, jobId, btn);
            } else {
                if (jobEl) { jobEl.textContent = 'Started'; jobEl.style.cssText = 'color:#10b981;font-size:0.7rem;padding:4px 0;'; }
                if (btn) setTimeout(function() { btn.disabled = false; btn.textContent = btn.textContent.replace(' \u25B6', ''); if (jobEl) { jobEl.textContent = ''; jobEl.style.cssText = ''; } }, 3000);
            }
        })
        .catch(function() {
            var jobEl = document.getElementById('job-' + actionKey);
            if (jobEl) { jobEl.textContent = 'Network error'; jobEl.style.cssText = 'color:#ef4444;font-size:0.7rem;padding:4px 0;'; }
            if (btn) { btn.disabled = false; btn.textContent = btn.textContent.replace(' \u25B6', ''); }
        });
}

// ── Benchmark functions (Project #110) ──

function _checkExistingBenchmark(actionKey) {
    fetch('/tools/bridge/api/benchmarks/latest/' + encodeURIComponent(actionKey))
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success && data.results && data.results.length > 0) {
            // Activate the RESULTS button
            var btns = document.querySelectorAll('.stn-bench-results-btn[data-action-key="' + actionKey + '"]');
            btns.forEach(function(b) { b.classList.remove('no-results'); });
        }
    })
    .catch(function() {});
}

function loadLatestBenchmark(actionKey) {
    fetch('/tools/bridge/api/benchmarks/latest/' + encodeURIComponent(actionKey))
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success && data.results) {
            _showBenchmarkCompareModal(data.results, data.run);
        }
    })
    .catch(function(err) { console.error('Load benchmark error:', err); });
}

/* ── Benchmark lock: only one benchmark at a time ── */
var _activeBenchmarkKey = null;  // action_key of currently running benchmark

function _lockBenchmarkButtons(activeKey) {
    _activeBenchmarkKey = activeKey;
    document.querySelectorAll('.stn-bench-btn').forEach(function(b) {
        if (b.dataset.actionKey !== activeKey) {
            b.disabled = true;
            b.classList.add('bench-locked');
            b.title = 'Benchmark in progress — wait for completion';
        }
    });
}

function _unlockBenchmarkButtons() {
    _activeBenchmarkKey = null;
    _activeBenchmarkRun = null;
    _benchmarkPollActive = false;
    document.querySelectorAll('.stn-bench-btn').forEach(function(b) {
        b.disabled = false;
        b.classList.remove('bench-locked', 'running');
        if (!b.classList.contains('bench-done')) {
            b.textContent = 'TEST';
        }
    });
}

/* Cached active benchmark state — survives re-renders */
var _activeBenchmarkRun = null;
var _benchmarkPollActive = false;

function _checkActiveBenchmark() {
    fetch('/tools/bridge/api/benchmarks/active')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success && data.active) {
            var run = data.run;
            _activeBenchmarkRun = run;
            _applyBenchmarkState();
        } else {
            _activeBenchmarkRun = null;
            _benchmarkPollActive = false;
            _unlockBenchmarkButtons();
        }
    })
    .catch(function() {});
}

function _applyBenchmarkState() {
    if (!_activeBenchmarkRun) return;
    var run = _activeBenchmarkRun;
    var done = (run.completed_agents || 0) + (run.failed_agents || 0);

    _lockBenchmarkButtons(run.action_key);
    var btn = document.querySelector('.stn-bench-btn[data-action-key="' + run.action_key + '"]');
    if (btn) {
        btn.disabled = true;
        btn.classList.add('running');
        btn.textContent = 'TESTING ' + done + '/' + run.total_agents;
        if (!_benchmarkPollActive) {
            _benchmarkPollActive = true;
            _startBenchmarkPoll(run.action_key, run.id, null, btn, run.total_agents);
        }
    }
}

function startActionBenchmark(actionKey, btn) {
    if (btn.disabled) return;
    if (_activeBenchmarkKey) {
        alert('A benchmark is already running. Wait for it to finish.');
        return;
    }
    btn.disabled = true;
    btn.classList.add('running');
    btn.textContent = 'TESTING...';
    _lockBenchmarkButtons(actionKey);

    var benchPayload = { action_key: actionKey };
    if (localStorage.getItem('archie_bench_contractors') === 'true') {
        benchPayload.include_contractors = true;
    }
    fetch('/tools/bridge/api/benchmarks/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(benchPayload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success) {
            btn.disabled = false;
            btn.classList.remove('running');
            btn.textContent = 'TEST';
            _unlockBenchmarkButtons();
            alert('Benchmark failed: ' + (data.error || 'Unknown error'));
            return;
        }
        btn.textContent = 'TESTING 0/' + data.total_agents;
        _startBenchmarkPoll(actionKey, data.run_id, data.job_id, btn, data.total_agents);
    })
    .catch(function(err) {
        btn.disabled = false;
        btn.classList.remove('running');
        btn.textContent = 'TEST';
        _unlockBenchmarkButtons();
        console.error('Benchmark start error:', err);
    });
}

function _startBenchmarkPoll(actionKey, runId, jobId, btn, totalAgents) {
    var pollInterval = setInterval(function() {
        if (jobId) {
            fetch('/tools/bridge/api/bridge/jobs/' + jobId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success && data.job) {
                    var j = data.job;
                    var done = (j.completed_steps || 0);
                    btn.textContent = 'TESTING ' + done + '/' + totalAgents;
                    if (j.status !== 'running') {
                        clearInterval(pollInterval);
                        _unlockBenchmarkButtons();
                        _fetchBenchmarkResults(actionKey, runId, btn);
                    }
                }
            })
            .catch(function() {});
        } else {
            fetch('/tools/bridge/api/benchmarks/' + runId + '/status')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success && data.run) {
                    var done = (data.run.completed_agents || 0) + (data.run.failed_agents || 0);
                    btn.textContent = 'TESTING ' + done + '/' + totalAgents;
                    if (data.run.status !== 'running') {
                        clearInterval(pollInterval);
                        _unlockBenchmarkButtons();
                        fetch('/tools/bridge/api/benchmarks/' + runId)
                        .then(function(r2) { return r2.json(); })
                        .then(function(fullData) {
                            if (fullData.success) {
                                _renderBenchmarkFromData(actionKey, fullData, btn);
                            } else {
                                btn.disabled = false;
                                btn.classList.remove('running');
                                btn.textContent = 'TEST';
                            }
                        })
                        .catch(function() {
                            btn.disabled = false;
                            btn.classList.remove('running');
                            btn.textContent = 'TEST';
                        });
                    }
                }
            })
            .catch(function() {});
        }
    }, 2000);
}

function _fetchBenchmarkResults(actionKey, runId, btn) {
    fetch('/tools/bridge/api/benchmarks/' + runId)
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            _renderBenchmarkFromData(actionKey, data, btn);
        } else {
            btn.disabled = false;
            btn.classList.remove('running');
            btn.textContent = 'TEST';
        }
    })
    .catch(function() {
        btn.disabled = false;
        btn.classList.remove('running');
        btn.textContent = 'TEST';
    });
}

function _renderBenchmarkFromData(actionKey, data, btn) {
    btn.disabled = false;
    btn.classList.remove('running');
    btn.textContent = 'TEST';

    // Activate RESULTS button now that we have data
    var rbtns = document.querySelectorAll('.stn-bench-results-btn[data-action-key="' + actionKey + '"]');
    rbtns.forEach(function(b) { b.classList.remove('no-results'); });

    var container = document.getElementById('bench-' + actionKey);
    if (!container) {
        container = document.createElement('div');
        container.id = 'bench-' + actionKey;
        container.className = 'bench-container';
        btn.parentElement.parentElement.appendChild(container);
    }
    _renderBenchmarkLeaderboard(container, data.results || [], data.run || {});
}

function _clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
}

function _renderBenchmarkLeaderboard(containerEl, results, runInfo) {
    _clearChildren(containerEl);
    if (!results || results.length === 0) return;

    var board = document.createElement('div');
    board.className = 'bench-leaderboard';

    // Header
    var header = document.createElement('div');
    header.className = 'bench-header';
    var title = document.createElement('span');
    title.className = 'bench-header-title';
    title.textContent = 'BENCHMARK RESULTS';
    header.appendChild(title);
    var close = document.createElement('span');
    close.className = 'bench-header-close';
    close.textContent = '\u2715';
    close.addEventListener('click', function() { _clearChildren(containerEl); });
    header.appendChild(close);
    board.appendChild(header);

    // Result rows
    results.forEach(function(r, i) {
        var row = document.createElement('div');
        row.className = 'bench-row';
        if (i === 0 && r.success) row.classList.add('bench-gold');
        if (!r.success) row.classList.add('bench-failed');

        // Mini thumbnail for image benchmarks
        var inlineImg = r.success && r.response_preview && r.response_preview.match(/File:\s*(\/static\/media\/[^\s]+)/);
        if (inlineImg) {
            row.classList.add('has-thumb');
            var miniThumb = document.createElement('img');
            miniThumb.className = 'bench-row-thumb';
            miniThumb.src = inlineImg[1];
            miniThumb.alt = '';
            row.appendChild(miniThumb);
        }

        var rank = document.createElement('div');
        rank.className = 'bench-rank';
        rank.textContent = r.rank || (i + 1);
        row.appendChild(rank);

        var agent = document.createElement('div');
        agent.className = 'bench-agent';
        agent.textContent = r.display_name || r.agent_name;
        agent.title = (r.model_used || '') + ' (' + (r.provider || '') + ')';
        row.appendChild(agent);

        var time = document.createElement('div');
        time.className = 'bench-time';
        time.textContent = r.success ? ((r.duration_ms / 1000).toFixed(1) + 's') : 'FAIL';
        row.appendChild(time);

        var tokens = document.createElement('div');
        tokens.className = 'bench-tokens';
        if (inlineImg && r.success) {
            tokens.textContent = ((r.total_tokens || 0) / 1024).toFixed(0) + 'KB';
        } else {
            tokens.textContent = r.success ? (r.total_tokens || 0) + 'tk' : '--';
        }

        var score = document.createElement('div');
        score.className = 'bench-score';
        score.textContent = r.success ? r.score.toFixed(1) : '0.0';
        row.appendChild(score);

        board.appendChild(row);
    });

    // Footer
    var footer = document.createElement('div');
    footer.className = 'bench-footer';
    var ts = runInfo.completed_at || runInfo.started_at || '';
    if (ts) {
        try { ts = new Date(ts).toLocaleString(); } catch(e) {}
    }
    var left = document.createElement('span');
    left.textContent = ts;
    footer.appendChild(left);

    var mid = document.createElement('span');
    var passed = results.filter(function(r) { return r.success; }).length;
    mid.textContent = passed + '/' + results.length + ' passed';
    footer.appendChild(mid);

    // RESULTS button for side-by-side comparison
    var resultsBtn = document.createElement('button');
    resultsBtn.className = 'stn-bench-results-btn';
    resultsBtn.textContent = 'COMPARE';
    resultsBtn.title = 'View side-by-side response comparison';
    resultsBtn.addEventListener('click', function() {
        _showBenchmarkCompareModal(results, runInfo);
    });
    footer.appendChild(resultsBtn);

    board.appendChild(footer);
    containerEl.appendChild(board);
}

function _showBenchmarkCompareModal(results, runInfo) {
    // Remove existing modal
    var existing = document.getElementById('benchCompareModal');
    if (existing) existing.parentElement.removeChild(existing);

    var overlay = document.createElement('div');
    overlay.className = 'bench-modal-overlay';
    overlay.id = 'benchCompareModal';
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.parentElement.removeChild(overlay);
    });

    var modal = document.createElement('div');
    modal.className = 'bench-modal';

    // ── Header ──
    var header = document.createElement('div');
    header.className = 'bench-modal-header';
    var titleText = document.createElement('span');
    titleText.textContent = 'BENCHMARK — ' + (runInfo.action_key || '').replace(/\./g, ' ').toUpperCase();
    header.appendChild(titleText);
    var closeBtn = document.createElement('span');
    closeBtn.className = 'bench-modal-close';
    closeBtn.textContent = '\u2715';
    closeBtn.addEventListener('click', function() {
        overlay.parentElement.removeChild(overlay);
    });
    header.appendChild(closeBtn);
    modal.appendChild(header);

    // ── Body (scrollable) ──
    var body = document.createElement('div');
    body.className = 'bench-modal-body';

    // ── 1. Leaderboard summary table (top) ──
    var table = document.createElement('table');
    table.className = 'bench-summary-table';
    var thead = document.createElement('thead');
    var thRow = document.createElement('tr');
    var _isImgBench = results.some(function(r) {
        return r.success && r.response_preview && r.response_preview.indexOf('/static/media/') !== -1;
    });
    ['RANK', 'AGENT', 'MODEL', 'TIME', _isImgBench ? 'SIZE' : 'TOKENS', 'SCORE'].forEach(function(h) {
        var th = document.createElement('th');
        th.textContent = h;
        thRow.appendChild(th);
    });
    thead.appendChild(thRow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    var tableRows = [];
    results.forEach(function(r, i) {
        var tr = document.createElement('tr');
        if (i === 0 && r.success) tr.className = 'bench-row-gold';
        if (!r.success) tr.className = 'bench-row-failed';
        tr.setAttribute('data-bench-idx', i);

        var tdRank = document.createElement('td');
        tdRank.className = 'bench-summary-rank';
        tdRank.textContent = '#' + (r.rank || (i + 1));
        tr.appendChild(tdRank);

        var tdAgent = document.createElement('td');
        tdAgent.textContent = r.display_name || r.agent_name;
        tr.appendChild(tdAgent);

        var tdModel = document.createElement('td');
        tdModel.textContent = r.model_used || '';
        tdModel.style.opacity = '0.5';
        tdModel.style.fontSize = '0.55rem';
        tr.appendChild(tdModel);

        var tdTime = document.createElement('td');
        tdTime.textContent = r.success ? (r.duration_ms / 1000).toFixed(1) + 's' : '--';
        tr.appendChild(tdTime);

        var tdTokens = document.createElement('td');
        if (_isImgBench && r.success) {
            var kb = ((r.total_tokens || 0) / 1024).toFixed(0);
            tdTokens.textContent = kb + 'KB';
        } else {
            tdTokens.textContent = r.success ? (r.total_tokens || 0) : '--';
        }
        tr.appendChild(tdTokens);

        var tdScore = document.createElement('td');
        tdScore.className = 'bench-summary-score';
        tdScore.textContent = r.success ? r.score.toFixed(1) : 'FAIL';
        tr.appendChild(tdScore);

        // Click row to switch to that agent's tab
        tr.addEventListener('click', function() { _switchBenchTab(i); });
        tableRows.push(tr);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    body.appendChild(table);

    // ── 1b. Image gallery (for image benchmarks) ──
    var isImageBenchmark = results.some(function(r) {
        return r.success && r.response_preview && r.response_preview.indexOf('/static/media/') !== -1;
    });
    if (isImageBenchmark) {
        var gallery = document.createElement('div');
        gallery.className = 'bench-image-gallery';

        var galleryTitle = document.createElement('div');
        galleryTitle.className = 'bench-gallery-title';
        galleryTitle.textContent = 'GENERATED IMAGES';
        gallery.appendChild(galleryTitle);

        var galleryGrid = document.createElement('div');
        galleryGrid.className = 'bench-gallery-grid';

        results.forEach(function(r, i) {
            var card = document.createElement('div');
            card.className = 'bench-gallery-card';
            if (!r.success) card.classList.add('bench-gallery-failed');
            card.addEventListener('click', function() { _switchBenchTab(i); });

            if (r.success) {
                var imgM = r.response_preview.match(/File:\s*(\/static\/media\/[^\s]+)/);
                if (imgM) {
                    var thumb = document.createElement('img');
                    thumb.className = 'bench-gallery-thumb';
                    thumb.src = imgM[1];
                    thumb.alt = r.agent_name;
                    thumb.loading = 'lazy';
                    card.appendChild(thumb);
                }
            } else {
                var failIcon = document.createElement('div');
                failIcon.className = 'bench-gallery-fail-icon';
                failIcon.textContent = '\u2717';
                card.appendChild(failIcon);
            }

            var label = document.createElement('div');
            label.className = 'bench-gallery-label';
            var catMatch = r.response_preview && r.response_preview.match(/Category:\s*(\w+)/);
            label.textContent = catMatch ? catMatch[1] : (r.agent_name || 'Image ' + (i + 1));
            card.appendChild(label);

            var scoreLabel = document.createElement('div');
            scoreLabel.className = 'bench-gallery-score';
            scoreLabel.textContent = r.success ? r.score.toFixed(1) : 'FAIL';
            card.appendChild(scoreLabel);

            galleryGrid.appendChild(card);
        });

        gallery.appendChild(galleryGrid);
        body.appendChild(gallery);
    }

    // ── 2. Skill updates (between table and responses) ──
    var skillFooter = document.createElement('div');
    skillFooter.className = 'bench-skill-footer';
    skillFooter.style.display = 'none';
    body.appendChild(skillFooter);

    if (runInfo && runInfo.id) {
        fetch('/tools/bridge/api/benchmarks/' + runInfo.id + '/skill-updates')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success || !data.updates || data.updates.length === 0) return;
                skillFooter.style.display = '';

                var title = document.createElement('div');
                title.className = 'bench-skill-title';
                title.textContent = 'SKILLS UPDATED (' + data.total_updated + ' agents)';
                skillFooter.appendChild(title);

                data.updates.forEach(function(u) {
                    var row = document.createElement('div');
                    row.className = 'bench-skill-row';

                    var agentSpan = document.createElement('span');
                    agentSpan.className = 'bench-skill-agent';
                    agentSpan.textContent = u.agent_name;
                    row.appendChild(agentSpan);

                    var skill = document.createElement('span');
                    skill.textContent = u.skill_name;
                    row.appendChild(skill);

                    var oldLvl = document.createElement('span');
                    oldLvl.className = 'bench-skill-level-old';
                    oldLvl.textContent = u.old_level != null ? 'Lv' + u.old_level : 'NEW';
                    row.appendChild(oldLvl);

                    var arrow = document.createElement('span');
                    arrow.className = 'bench-skill-arrow';
                    arrow.textContent = '\u2192';
                    row.appendChild(arrow);

                    var newLvl = document.createElement('span');
                    var lvlClass = 'bench-skill-level';
                    if (u.old_level != null && u.new_level > u.old_level) lvlClass += ' bench-skill-level-up';
                    else if (u.old_level != null && u.new_level < u.old_level) lvlClass += ' bench-skill-level-down';
                    newLvl.className = lvlClass;
                    newLvl.textContent = 'Lv' + u.new_level;
                    row.appendChild(newLvl);

                    skillFooter.appendChild(row);
                });
            })
            .catch(function(err) { console.error('Skill updates fetch error:', err); });
    }

    // ── 3. Prev/Next agent navigator + response panel ──
    var currentIdx = 0;
    var nav = document.createElement('div');
    nav.className = 'bench-agent-nav';

    var prevBtn = document.createElement('button');
    prevBtn.className = 'bench-nav-btn';
    prevBtn.textContent = '\u25C0';
    prevBtn.addEventListener('click', function() { if (currentIdx > 0) _switchBenchTab(currentIdx - 1); });
    nav.appendChild(prevBtn);

    var navCurrent = document.createElement('div');
    navCurrent.className = 'bench-nav-current';
    nav.appendChild(navCurrent);

    var nextBtn = document.createElement('button');
    nextBtn.className = 'bench-nav-btn';
    nextBtn.textContent = '\u25B6';
    nextBtn.addEventListener('click', function() { if (currentIdx < results.length - 1) _switchBenchTab(currentIdx + 1); });
    nav.appendChild(nextBtn);

    var pickBtn = document.createElement('button');
    pickBtn.className = 'bench-pick-btn';
    pickBtn.textContent = 'BEST';
    pickBtn.addEventListener('click', function() {
        var r = results[currentIdx];
        pickBtn.disabled = true;
        pickBtn.textContent = '...';
        fetch('/tools/bridge/api/benchmarks/' + runInfo.id + '/pick', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({agent_name: r.agent_name})
        })
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            if (data.success) {
                // Clear all picks, set current
                results.forEach(function(x) { x.is_human_pick = false; });
                r.is_human_pick = true;
                _updatePickState();
                // Flash the table row
                tableRows[currentIdx].style.outline = '1px solid #10b981';
                setTimeout(function() { tableRows[currentIdx].style.outline = ''; }, 1200);
            }
            pickBtn.disabled = false;
        })
        .catch(function() { pickBtn.disabled = false; pickBtn.textContent = 'BEST'; });
    });
    nav.appendChild(pickBtn);

    body.appendChild(nav);

    var responsePanel = document.createElement('div');
    responsePanel.className = 'bench-response-panel';
    body.appendChild(responsePanel);

    // Navigation + tab switching logic
    function _updatePickState() {
        var r = results[currentIdx];
        if (r.is_human_pick) {
            pickBtn.classList.add('picked');
            pickBtn.textContent = '\u2713 BEST';
        } else {
            pickBtn.classList.remove('picked');
            pickBtn.textContent = 'BEST';
        }
        // Also show badge on table rows with pick
        tableRows.forEach(function(tr, j) {
            var existing = tr.querySelector('.bench-pick-badge');
            if (existing) existing.remove();
            if (results[j].is_human_pick) {
                var badge = document.createElement('span');
                badge.className = 'bench-pick-badge';
                badge.textContent = '\u2713 PICK';
                tr.querySelector('td').appendChild(badge);
            }
        });
    }

    function _updateNav(idx) {
        currentIdx = idx;
        var r = results[idx];
        var name = (r.display_name || r.agent_name).split('(')[0].trim();
        navCurrent.textContent = '';
        var rankSpan = document.createElement('span');
        rankSpan.className = 'bench-nav-rank';
        rankSpan.textContent = '#' + (r.rank || (idx + 1));
        navCurrent.appendChild(rankSpan);
        navCurrent.appendChild(document.createTextNode(name));
        if (r.is_human_pick) {
            var pickBadge = document.createElement('span');
            pickBadge.className = 'bench-pick-badge';
            pickBadge.textContent = '\u2713 PICK';
            navCurrent.appendChild(pickBadge);
        }
        var countLine = document.createElement('span');
        countLine.className = 'bench-nav-count';
        countLine.textContent = (idx + 1) + ' of ' + results.length;
        navCurrent.appendChild(countLine);
        prevBtn.disabled = (idx === 0);
        nextBtn.disabled = (idx === results.length - 1);
        _updatePickState();
    }

    function _switchBenchTab(idx) {
        var r = results[idx];
        _updateNav(idx);
        // Update table row highlight
        tableRows.forEach(function(tr, j) {
            tr.classList.toggle('bench-tab-active', j === idx);
        });
        // Render response panel
        responsePanel.textContent = '';

        var meta = document.createElement('div');
        meta.className = 'bench-response-meta';
        var spans = [
            (r.display_name || r.agent_name),
            r.model_used || '',
            r.success ? (r.duration_ms / 1000).toFixed(1) + 's' : 'FAILED',
            isImageBenchmark ? (((r.total_tokens || 0) / 1024).toFixed(0) + ' KB') : ((r.total_tokens || 0) + ' tokens'),
            'Score: ' + (r.success ? r.score.toFixed(1) : '0.0')
        ];
        spans.forEach(function(txt) {
            var s = document.createElement('span');
            s.textContent = txt;
            meta.appendChild(s);
        });
        responsePanel.appendChild(meta);

        // Check if this is an image benchmark (response_preview contains "File: /static/media/")
        var imgMatch = r.success && r.response_preview && r.response_preview.match(/File:\s*(\/static\/media\/[^\s]+)/);
        if (imgMatch) {
            // Image benchmark — show the generated image
            var imgWrap = document.createElement('div');
            imgWrap.className = 'bench-image-wrap';

            var img = document.createElement('img');
            img.className = 'bench-image-preview';
            img.src = imgMatch[1];
            img.alt = (r.agent_name || 'Generated image');
            img.loading = 'lazy';
            img.addEventListener('click', function() {
                window.open(imgMatch[1], '_blank');
            });
            imgWrap.appendChild(img);

            // Show prompt below image
            var promptMatch = r.response_preview.match(/Prompt:\s*(.+)/);
            if (promptMatch) {
                var promptEl = document.createElement('div');
                promptEl.className = 'bench-image-prompt';
                promptEl.textContent = promptMatch[1];
                imgWrap.appendChild(promptEl);
            }

            responsePanel.appendChild(imgWrap);
        } else {
            var resp = document.createElement('div');
            resp.className = 'bench-response-text';
            resp.textContent = r.success
                ? (r.response_preview || '(no response captured)')
                : ('Error: ' + (r.error_message || 'unknown'));
            responsePanel.appendChild(resp);
        }
    }

    // Show first agent by default
    if (results.length > 0) _switchBenchTab(0);

    modal.appendChild(body);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // ESC to close
    var escHandler = function(e) {
        if (e.key === 'Escape') {
            var el = document.getElementById('benchCompareModal');
            if (el) el.parentElement.removeChild(el);
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);
}

function _startActionJobPoll(actionKey, jobId, btn) {
    var jobEl = document.getElementById('job-' + actionKey);
    if (!jobEl) return;
    if (_actionJobPolls[actionKey]) clearInterval(_actionJobPolls[actionKey]);

    _actionJobPolls[actionKey] = setInterval(function() {
        fetch('/tools/bridge/api/bridge/jobs/' + jobId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                var j = data.job;
                var pct = j.total_steps > 0 ? Math.round(((j.completed_steps || 0) / j.total_steps) * 100) : 0;
                var barColor = j.status === 'failed' ? '#ef4444' : j.status === 'completed' ? '#10b981' : 'var(--stn-accent,#8b5cf6)';
                var countStr = (j.completed_steps || 0) + ' / ' + (j.total_steps || 0);

                jobEl.textContent = '';
                var row = document.createElement('div');
                row.className = 'stn-ops-job-row';
                row.style.marginTop = '6px';

                var info = document.createElement('div');
                info.className = 'stn-ops-job-info';
                var desc = document.createElement('div');
                desc.className = 'stn-ops-job-desc';
                desc.textContent = j.description || actionKey;
                info.appendChild(desc);
                row.appendChild(info);

                var bar = document.createElement('div');
                bar.className = 'stn-ops-job-bar';
                var fill = document.createElement('div');
                fill.className = 'stn-ops-job-fill';
                fill.style.width = pct + '%';
                fill.style.background = barColor;
                bar.appendChild(fill);
                row.appendChild(bar);

                var cnt = document.createElement('div');
                cnt.className = 'stn-ops-job-count';
                cnt.textContent = countStr;
                row.appendChild(cnt);

                var pctEl = document.createElement('div');
                pctEl.className = 'stn-ops-job-pct';
                pctEl.textContent = pct + '%';
                row.appendChild(pctEl);

                jobEl.appendChild(row);

                if (j.status === 'completed' || j.status === 'failed' || j.status === 'cancelled') {
                    clearInterval(_actionJobPolls[actionKey]);
                    delete _actionJobPolls[actionKey];
                    if (btn) { btn.disabled = false; btn.textContent = btn.textContent.replace(' \u25B6', ''); }
                }
            })
            .catch(function() {});
    }, 3000);
}

// === CREW TAB CONTENT ===

function renderCrewTab(agents, stationColor, maxPrimary, maxAuxiliary) {
    var panel = document.getElementById('lcarsCrewPanel');
    if (!panel) return;
    panel.textContent = '';

    var zoneCtx = _consoleCurrentZone;
    var zoneName = zoneCtx ? zoneCtx.zoneName : '';
    var activeJobs = (zoneCtx && zoneCtx.zd && zoneCtx.zd.activeJobs) || [];

    // Separate jobs: local station jobs vs cross-station away jobs
    var stationJobs = [];    // Jobs done AT this station (including by helpers/contractors)
    var awayAgentMap = {};   // agent_callsign → { job, dispatchZone }
    for (var ji = 0; ji < activeJobs.length; ji++) {
        var j = activeJobs[ji];
        var m = j.metadata || {};
        if (m.is_cross_station && STATION_TO_ISO_ZONE[m.home_station] === zoneName && STATION_TO_ISO_ZONE[m.dispatch_station] !== zoneName) {
            // This agent is AWAY from this zone, working elsewhere
            awayAgentMap[(j.agent_callsign || '').toLowerCase()] = { job: j, dispatchZone: STATION_TO_ISO_ZONE[m.dispatch_station], dispatchLabel: (ISOMETRIC_ZONE_MAP[STATION_TO_ISO_ZONE[m.dispatch_station]] || {}).label || m.dispatch_station };
        } else {
            // Job is being worked AT this station (by local agent, helper, or contractor)
            stationJobs.push(j);
        }
    }

    // -- Active jobs banner (only jobs being done AT this station) --
    if (stationJobs.length > 0) {
        var jobBanner = document.createElement('div');
        jobBanner.style.cssText = 'background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:8px;padding:10px 12px;margin-bottom:12px;';

        var bannerHeader = document.createElement('div');
        bannerHeader.style.cssText = 'font-size:0.65rem;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:#10b981;margin-bottom:6px;';
        bannerHeader.textContent = '\u2699 ACTIVE JOBS (' + stationJobs.length + ')';
        jobBanner.appendChild(bannerHeader);

        for (var si = 0; si < stationJobs.length; si++) {
            var ajob = stationJobs[si];
            var jobRow = document.createElement('div');
            jobRow.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 0;' + (si > 0 ? 'border-top:1px solid rgba(255,255,255,0.05);' : '');

            var jobInfo = document.createElement('div');
            jobInfo.style.cssText = 'flex:1;min-width:0;';

            var jobDesc = document.createElement('div');
            jobDesc.style.cssText = 'font-size:0.8rem;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
            jobDesc.textContent = ajob.description || ajob.job_type || 'Working...';
            jobInfo.appendChild(jobDesc);

            var jobAgent = document.createElement('div');
            jobAgent.style.cssText = 'font-size:0.7rem;opacity:0.5;';
            var agentLabel = ajob.agent_name || '';
            var ajMeta = ajob.metadata || {};
            if (ajMeta.is_cross_station) agentLabel += ' (cross-station)';
            if (ajMeta.is_cloud) agentLabel = '\u2601 ' + (ajMeta.cloud_provider || 'Cloud').toUpperCase();
            jobAgent.textContent = agentLabel;
            jobInfo.appendChild(jobAgent);

            jobRow.appendChild(jobInfo);

            var jobProg = document.createElement('div');
            jobProg.style.cssText = 'text-align:right;flex-shrink:0;';
            var jobPct = ajob.total_steps > 0 ? Math.round((ajob.completed_steps / ajob.total_steps) * 100) : 0;

            var pctEl = document.createElement('div');
            pctEl.style.cssText = 'font-size:0.85rem;font-weight:700;font-family:Orbitron,sans-serif;color:#10b981;';
            pctEl.textContent = jobPct + '%';
            jobProg.appendChild(pctEl);

            var stepsEl = document.createElement('div');
            stepsEl.style.cssText = 'font-size:0.6rem;opacity:0.5;';
            stepsEl.textContent = ajob.completed_steps + '/' + ajob.total_steps;
            jobProg.appendChild(stepsEl);

            jobRow.appendChild(jobProg);
            jobBanner.appendChild(jobRow);
        }
        panel.appendChild(jobBanner);
    }

    // -- Assigned Crew: all station_assignments are station crew (Primary/Secondary by position)
    // Only additional_support (temporary helpers) are separated out
    var stationCrew = [];
    var dbAuxAgents = [];
    if (agents && agents.length) {
        for (var si = 0; si < agents.length; si++) {
            var atype = (agents[si].assignment_type || 'primary').toLowerCase();
            if (atype === 'additional_support') {
                dbAuxAgents.push(agents[si]);
            } else {
                stationCrew.push(agents[si]);
            }
        }
    }

    // Always show all slots (Primary, Secondary, Auxiliary)
    {
        var label = document.createElement('div');
        label.className = 'lcars-section-label';
        label.textContent = 'STATION CREW (' + stationCrew.length + '/' + (maxPrimary || 2) + ')';
        panel.appendChild(label);

        var slotNames = ['PRIMARY', 'SECONDARY'];
        var slotStyles = [
            'background:rgba(16,185,129,0.15);color:#10b981;border-color:rgba(16,185,129,0.3);',
            'background:rgba(59,130,246,0.15);color:#3b82f6;border-color:rgba(59,130,246,0.3);'
        ];

        for (var i = 0; i < (maxPrimary || 2); i++) {
            var agent = stationCrew[i];

            if (!agent) {
                // Empty slot placeholder
                var emptyRow = document.createElement('div');
                emptyRow.className = 'lcars-crew-row';
                emptyRow.style.cssText = 'opacity:0.3;';

                var emptyAvatar = document.createElement('div');
                emptyAvatar.className = 'lcars-crew-avatar';
                emptyAvatar.style.cssText = 'background:rgba(255,255,255,0.05);border:1px dashed rgba(255,255,255,0.15);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.2rem;color:rgba(255,255,255,0.2);';
                emptyAvatar.textContent = '?';
                emptyRow.appendChild(emptyAvatar);

                var emptyInfo = document.createElement('div');
                emptyInfo.style.cssText = 'flex:1;min-width:0;';
                var emptyName = document.createElement('div');
                emptyName.className = 'lcars-crew-name';
                emptyName.style.fontStyle = 'italic';
                emptyName.textContent = '— vacant —';
                emptyInfo.appendChild(emptyName);
                emptyRow.appendChild(emptyInfo);

                var emptyBadge = document.createElement('span');
                emptyBadge.className = 'lcars-role-badge';
                emptyBadge.style.cssText = slotStyles[i] || slotStyles[1];
                emptyBadge.textContent = slotNames[i] || ('CREW ' + (i + 1));
                emptyRow.appendChild(emptyBadge);

                panel.appendChild(emptyRow);
                continue;
            }
            var awayInfo = awayAgentMap[(agent.name || '').toLowerCase()];
            var isAway = !!awayInfo;

            var isPaused = agent.status && agent.status !== 'active';
            var row = document.createElement('div');
            row.className = 'lcars-crew-row';
            if (isAway || isPaused) { row.style.opacity = '0.4'; row.style.filter = 'grayscale(0.7)'; }

            var avatarUrl = agent.avatar_url || ('https://api.dicebear.com/7.x/bottts/svg?seed=' + encodeURIComponent(agent.name || 'agent'));
            var img = document.createElement('img');
            img.className = 'lcars-crew-avatar';
            img.src = avatarUrl;
            img.alt = agent.name || '';
            img.onerror = function() { this.src = 'https://api.dicebear.com/7.x/bottts/svg?seed=fallback'; };
            row.appendChild(img);

            var info = document.createElement('div');
            info.style.cssText = 'flex:1;min-width:0;';

            var nameEl = document.createElement('div');
            nameEl.className = 'lcars-crew-name';
            var displayName = [agent.first_name, agent.last_name].filter(Boolean).join(' ') || agent.name || 'Unknown';
            nameEl.textContent = displayName;
            info.appendChild(nameEl);

            if (isAway) {
                // Show "Assigned to [STATION]" link instead of title/model
                var awayEl = document.createElement('div');
                awayEl.style.cssText = 'font-size:0.7rem;color:#F59E0B;cursor:pointer;';
                awayEl.textContent = '\u2192 Working at ' + awayInfo.dispatchLabel + ' Station';
                awayEl.title = 'Click to view ' + awayInfo.dispatchLabel;
                (function(destZone) {
                    awayEl.addEventListener('click', function(e) {
                        e.stopPropagation();
                        closeStationConsole();
                        // Find and click the destination zone element
                        var destEl = document.querySelector('.iso-station-zone[data-station-code="' + destZone + '"]');
                        if (destEl) setTimeout(function() { destEl.click(); }, 300);
                    });
                })(awayInfo.dispatchZone);
                info.appendChild(awayEl);

                var taskEl = document.createElement('div');
                taskEl.style.cssText = 'font-size:0.65rem;opacity:0.5;font-style:italic;';
                taskEl.textContent = awayInfo.job.description || awayInfo.job.job_type || '';
                info.appendChild(taskEl);
            } else {
                if (agent.title) {
                    var titleEl = document.createElement('div');
                    titleEl.style.cssText = 'font-size:0.7rem;opacity:0.5;';
                    titleEl.textContent = agent.title;
                    info.appendChild(titleEl);
                }

                var modelEl = document.createElement('div');
                modelEl.className = 'lcars-crew-model';
                modelEl.textContent = agent.model || 'No model';
                info.appendChild(modelEl);
            }

            row.appendChild(info);

            if (isPaused) {
                var pausedBadge = document.createElement('span');
                pausedBadge.className = 'lcars-role-badge';
                pausedBadge.style.cssText = 'background:rgba(255,165,0,0.15);color:#FFA500;border-color:rgba(255,165,0,0.3);';
                pausedBadge.textContent = (agent.status || 'PAUSED').toUpperCase();
                row.appendChild(pausedBadge);
            } else if (isAway) {
                var awayBadge = document.createElement('span');
                awayBadge.className = 'lcars-role-badge';
                awayBadge.style.cssText = 'background:rgba(245,158,11,0.15);color:#F59E0B;border-color:rgba(245,158,11,0.3);';
                awayBadge.textContent = 'AWAY';
                row.appendChild(awayBadge);
            } else {
                // Label: 1st crew member = PRIMARY, 2nd = SECONDARY
                var roleBadge = document.createElement('span');
                roleBadge.className = 'lcars-role-badge';
                roleBadge.style.cssText = slotStyles[i] || slotStyles[1];
                roleBadge.textContent = slotNames[i] || ('CREW ' + (i + 1));
                row.appendChild(roleBadge);
            }

            panel.appendChild(row);
        }
    }

    // -- DB-assigned auxiliary agents (separate from cross-station helpers) --
    if (dbAuxAgents.length > 0) {
        var dbAuxLabel = document.createElement('div');
        dbAuxLabel.className = 'lcars-section-label';
        dbAuxLabel.style.cssText = 'margin-top:12px;color:#a78bfa;';
        dbAuxLabel.textContent = 'ASSIGNED AUXILIARY (' + dbAuxAgents.length + ')';
        panel.appendChild(dbAuxLabel);

        for (var di = 0; di < dbAuxAgents.length; di++) {
            var dAgent = dbAuxAgents[di];
            var dRow = document.createElement('div');
            dRow.className = 'lcars-crew-row';
            dRow.style.opacity = '0.7';

            var dAvatarUrl = dAgent.avatar_url || ('https://api.dicebear.com/7.x/bottts/svg?seed=' + encodeURIComponent(dAgent.name || 'agent'));
            var dImg = document.createElement('img');
            dImg.className = 'lcars-crew-avatar';
            dImg.src = dAvatarUrl;
            dImg.alt = dAgent.name || '';
            dImg.onerror = function() { this.src = 'https://api.dicebear.com/7.x/bottts/svg?seed=fallback'; };
            dRow.appendChild(dImg);

            var dInfo = document.createElement('div');
            dInfo.style.cssText = 'flex:1;min-width:0;';

            var dName = document.createElement('div');
            dName.className = 'lcars-crew-name';
            dName.textContent = [dAgent.first_name, dAgent.last_name].filter(Boolean).join(' ') || dAgent.name || 'Unknown';
            dInfo.appendChild(dName);

            if (dAgent.title) {
                var dTitle = document.createElement('div');
                dTitle.style.cssText = 'font-size:0.7rem;opacity:0.5;';
                dTitle.textContent = dAgent.title;
                dInfo.appendChild(dTitle);
            }

            dRow.appendChild(dInfo);

            var dBadge = document.createElement('span');
            dBadge.className = 'lcars-role-badge';
            dBadge.style.cssText = 'background:rgba(167,139,250,0.15);color:#a78bfa;border-color:rgba(167,139,250,0.3);';
            dBadge.textContent = (dAgent.assignment_type || 'AUXILIARY').toUpperCase();
            dRow.appendChild(dBadge);

            panel.appendChild(dRow);
        }
    }

    // -- AUXILIARY (cross-station agents, non-cloud) --
    var auxHelpers = [];
    var cloudHelpers = [];
    for (var hi = 0; hi < stationJobs.length; hi++) {
        var hj = stationJobs[hi];
        var hm = hj.metadata || {};
        if (hm.is_cloud) {
            cloudHelpers.push(hj);
        } else if (hm.is_cross_station) {
            auxHelpers.push(hj);
        }
    }

    // AUXILIARY section
    var auxLabel = document.createElement('div');
    auxLabel.className = 'lcars-section-label';
    auxLabel.style.cssText = 'margin-top:16px;color:#F59E0B;';
    auxLabel.textContent = '\u2693 AUXILIARY (' + auxHelpers.length + '/' + (maxAuxiliary || 1) + ')';
    panel.appendChild(auxLabel);

    if (auxHelpers.length > 0) {
        for (var ai = 0; ai < auxHelpers.length; ai++) {
            var aJob = auxHelpers[ai];
            var aMeta = aJob.metadata || {};
            var aRow = document.createElement('div');
            aRow.className = 'lcars-crew-row';

            // Cross-station agent avatar
            var aHelperName = (aJob.agent_callsign || aJob.agent_name || '').split(' ')[0];
            var aHelperSlug = aHelperName.toLowerCase();
            var aImg = document.createElement('img');
            aImg.className = 'lcars-crew-avatar';
            aImg.src = '/static/avatars/' + aHelperSlug + '.svg';
            aImg.alt = aHelperName;
            aImg.onerror = function() { this.src = 'https://api.dicebear.com/7.x/bottts/svg?seed=' + encodeURIComponent(this.alt); };
            aRow.appendChild(aImg);

            var aInfo = document.createElement('div');
            aInfo.style.cssText = 'flex:1;min-width:0;';

            var aName = document.createElement('div');
            aName.className = 'lcars-crew-name';
            aName.textContent = aJob.agent_name || aJob.agent_callsign || 'Unknown';
            aInfo.appendChild(aName);

            var aFrom = document.createElement('div');
            aFrom.style.cssText = 'font-size:0.7rem;opacity:0.5;cursor:pointer;color:#6495ED;';
            var aHomeLabel = (ISOMETRIC_ZONE_MAP[STATION_TO_ISO_ZONE[aMeta.home_station]] || {}).label || aMeta.home_station || '';
            aFrom.textContent = 'From ' + aHomeLabel + ' Station';
            (function(homeZone) {
                aFrom.addEventListener('click', function(e) {
                    e.stopPropagation();
                    closeStationConsole();
                    var srcEl = document.querySelector('.iso-station-zone[data-station-code="' + homeZone + '"]');
                    if (srcEl) setTimeout(function() { srcEl.click(); }, 300);
                });
            })(STATION_TO_ISO_ZONE[aMeta.home_station]);
            aInfo.appendChild(aFrom);

            aRow.appendChild(aInfo);

            var aBadge = document.createElement('span');
            aBadge.className = 'lcars-role-badge';
            aBadge.style.cssText = 'background:rgba(100,149,237,0.15);color:#6495ED;border-color:rgba(100,149,237,0.3);';
            aBadge.textContent = 'HELPING';
            aRow.appendChild(aBadge);

            panel.appendChild(aRow);
        }
    } else {
        // Empty auxiliary slot placeholder
        var auxRow = document.createElement('div');
        auxRow.className = 'lcars-crew-row';
        auxRow.style.cssText = 'opacity:0.3;';

        var auxAvatar = document.createElement('div');
        auxAvatar.className = 'lcars-crew-avatar';
        auxAvatar.style.cssText = 'background:rgba(255,255,255,0.05);border:1px dashed rgba(245,158,11,0.3);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.2rem;color:rgba(245,158,11,0.3);';
        auxAvatar.textContent = '?';
        auxRow.appendChild(auxAvatar);

        var auxInfo = document.createElement('div');
        auxInfo.style.cssText = 'flex:1;min-width:0;';
        var auxName = document.createElement('div');
        auxName.className = 'lcars-crew-name';
        auxName.style.fontStyle = 'italic';
        auxName.textContent = '— vacant —';
        auxInfo.appendChild(auxName);
        auxRow.appendChild(auxInfo);

        var auxBadge = document.createElement('span');
        auxBadge.className = 'lcars-role-badge';
        auxBadge.style.cssText = 'background:rgba(245,158,11,0.1);color:#F59E0B;border-color:rgba(245,158,11,0.2);';
        auxBadge.textContent = 'AUX';
        auxRow.appendChild(auxBadge);

        panel.appendChild(auxRow);
    }

    // CONTRACTOR section (only if cloud helpers exist)
    if (cloudHelpers.length > 0) {
        var cLabel = document.createElement('div');
        cLabel.className = 'lcars-section-label';
        cLabel.style.cssText = 'margin-top:16px;color:#9333EA;';
        cLabel.textContent = '\u2601 CONTRACTOR (' + cloudHelpers.length + ')';
        panel.appendChild(cLabel);

        for (var ci = 0; ci < cloudHelpers.length; ci++) {
            var cJob = cloudHelpers[ci];
            var cMeta = cJob.metadata || {};
            var cRow = document.createElement('div');
            cRow.className = 'lcars-crew-row';

            var cImg = document.createElement('div');
            cImg.style.cssText = 'width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.2rem;flex-shrink:0;';
            var brand = getProviderBrand(cJob.agent_callsign || cMeta.cloud_model || '');
            cImg.style.background = 'rgba(' + ((brand && brand.rgb) || '147,51,234') + ',0.15)';
            cImg.style.border = '1px solid ' + ((brand && brand.color) || '#9333EA');
            cImg.textContent = '\u2601';
            cRow.appendChild(cImg);

            var cInfo = document.createElement('div');
            cInfo.style.cssText = 'flex:1;min-width:0;';

            var cName = document.createElement('div');
            cName.className = 'lcars-crew-name';
            var cBrand = getProviderBrand(cJob.agent_callsign || cMeta.cloud_model || '');
            cName.textContent = (cBrand && cBrand.label) || 'Cloud Provider';
            cName.style.color = (cBrand && cBrand.color) || '#9333EA';
            cInfo.appendChild(cName);

            var cModel = document.createElement('div');
            cModel.style.cssText = 'font-size:0.7rem;opacity:0.5;';
            cModel.textContent = cMeta.cloud_model || 'Cloud model';
            cInfo.appendChild(cModel);

            cRow.appendChild(cInfo);

            var cBadge = document.createElement('span');
            cBadge.className = 'lcars-role-badge';
            cBadge.style.cssText = 'background:rgba(147,51,234,0.15);color:#9333EA;border-color:rgba(147,51,234,0.3);';
            cBadge.textContent = 'CONTRACTOR';
            cRow.appendChild(cBadge);

            panel.appendChild(cRow);
        }
    }
}

// === CONSOLE STUBS (Tasks 7-10) ===

async function loadConsoleDispatch(stationCodes) {
    var panel = document.getElementById('lcarsDispatchPanel');
    if (!panel) return;
    panel.textContent = '';
    var loadingEl = document.createElement('div');
    loadingEl.className = 'lcars-empty';
    loadingEl.textContent = 'Loading dispatch activity...';
    panel.appendChild(loadingEl);

    // Stop any existing timer
    if (_consoleDispatchTimer) clearInterval(_consoleDispatchTimer);

    async function fetchAndRender() {
        try {
            // Fetch for each station code and merge
            var allEvents = [];
            for (var i = 0; i < stationCodes.length; i++) {
                var resp = await fetch('/tools/bridge/api/stations/' + encodeURIComponent(stationCodes[i]) + '/dispatch');
                var events = await resp.json();
                if (Array.isArray(events)) allEvents = allEvents.concat(events);
            }

            // Sort by time descending, limit to 20
            allEvents.sort(function(a, b) {
                return (b.created_at || '').localeCompare(a.created_at || '');
            });
            allEvents = allEvents.slice(0, 20);

            panel.textContent = '';

            if (allEvents.length === 0) {
                var emptyEl = document.createElement('div');
                emptyEl.className = 'lcars-empty';
                emptyEl.textContent = 'No recent dispatch activity';
                panel.appendChild(emptyEl);
                return;
            }

            var label = document.createElement('div');
            label.className = 'lcars-section-label';
            label.textContent = 'RECENT DISPATCHES';
            panel.appendChild(label);

            for (var j = 0; j < allEvents.length; j++) {
                var ev = allEvents[j];
                var row = document.createElement('div');
                row.className = 'lcars-dispatch-row';

                var timeEl = document.createElement('div');
                timeEl.className = 'lcars-dispatch-time';
                timeEl.textContent = ev.created_at ? ArchieTime.time(ev.created_at) : '--:--';
                row.appendChild(timeEl);

                var statusEl = document.createElement('div');
                statusEl.className = 'lcars-dispatch-status';
                statusEl.textContent = ev.success ? '\u2713' : '\u2717';
                statusEl.style.color = ev.success ? '#10b981' : '#ef4444';
                row.appendChild(statusEl);

                var modelEl = document.createElement('div');
                modelEl.className = 'lcars-dispatch-model';
                modelEl.textContent = (ev.model_used || 'unknown') + ' \u2014 ' + (ev.task_type || ev.capability || '');
                row.appendChild(modelEl);

                var latencyEl = document.createElement('div');
                latencyEl.className = 'lcars-dispatch-latency';
                latencyEl.textContent = ev.duration_ms ? ev.duration_ms + 'ms' : '';
                row.appendChild(latencyEl);

                panel.appendChild(row);
            }
        } catch (e) {
            console.error('Console dispatch error:', e);
            panel.textContent = '';
            var errEl = document.createElement('div');
            errEl.className = 'lcars-empty';
            errEl.textContent = 'Error loading dispatch data';
            panel.appendChild(errEl);
        }
    }

    // Initial load via fetch (immediate data)
    await fetchAndRender();

    // Real-time updates via SSE
    try {
        if (_consoleEventSource) _consoleEventSource.close();
        _consoleEventSource = new EventSource('/tools/bridge/api/dispatch/stream');
        _consoleEventSource.onmessage = function(e) {
            try {
                var evt = JSON.parse(e.data);
                var stationMatch = stationCodes.some(function(code) {
                    return evt.data && evt.data.station_code === code;
                });
                if (stationMatch || !evt.data || !evt.data.station_code) {
                    fetchAndRender();
                }
            } catch(err) { /* ignore parse errors */ }
        };
        _consoleEventSource.onerror = function() {
            if (_consoleEventSource) _consoleEventSource.close();
            _consoleEventSource = null;
            _consoleDispatchTimer = setInterval(fetchAndRender, 15000);
        };
    } catch(sseErr) {
        _consoleDispatchTimer = setInterval(fetchAndRender, 15000);
    }

    // Load skill gaps section
    loadSkillGaps(panel);
}

async function loadSkillGaps(parentPanel) {
    try {
        var resp = await fetch('/tools/bridge/api/dispatch/agent-gaps');
        var data = await resp.json();
        var gaps = (data.gaps || []).filter(function(g) { return g.status === 'pending'; });

        // Remove existing gaps section if any
        var existing = document.getElementById('console-skill-gaps');
        if (existing) existing.remove();

        if (gaps.length === 0) return;

        var section = document.createElement('div');
        section.id = 'console-skill-gaps';
        section.style.marginTop = '16px';

        var header = document.createElement('div');
        header.className = 'lcars-section-label';
        header.style.display = 'flex';
        header.style.justifyContent = 'space-between';
        header.style.alignItems = 'center';

        var headerText = document.createElement('span');
        headerText.textContent = 'SKILL GAPS';
        header.appendChild(headerText);

        var badge = document.createElement('span');
        badge.className = 'badge badge-warning';
        badge.style.cssText = 'font-size:0.75em;padding:2px 8px;border-radius:10px;background:#f59e0b;color:#000;';
        badge.textContent = gaps.length;
        header.appendChild(badge);

        section.appendChild(header);

        for (var i = 0; i < gaps.length; i++) {
            var g = gaps[i];
            var row = document.createElement('div');
            row.className = 'lcars-dispatch-row';
            row.style.cssText = 'flex-direction:column;align-items:flex-start;gap:4px;padding:8px;';

            var info = document.createElement('div');
            info.style.fontWeight = 'bold';
            info.textContent = (g.capability || 'unknown') + ' @ ' + (g.station || '?') + ' \u2192 ' + (g.suggested_name || '');
            row.appendChild(info);

            if (g.reason) {
                var reason = document.createElement('div');
                reason.style.cssText = 'font-size:0.85em;opacity:0.7;';
                reason.textContent = g.reason;
                row.appendChild(reason);
            }

            var btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-outline-success';
            btn.style.cssText = 'margin-top:4px;font-size:0.8em;padding:2px 10px;';
            btn.textContent = 'Approve & Create';
            btn.dataset.gapId = g.id;
            btn.addEventListener('click', function() {
                var gapBtn = this;
                var gapId = parseInt(gapBtn.dataset.gapId);
                gapBtn.disabled = true;
                gapBtn.textContent = 'Creating...';
                fetch('/tools/bridge/api/agents/create-from-gap', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({approval_id: gapId})
                }).then(function(r) { return r.json(); }).then(function(d) {
                    if (d.success) {
                        gapBtn.textContent = 'Created';
                        gapBtn.className = 'btn btn-sm btn-success';
                        setTimeout(function() { loadSkillGaps(parentPanel); }, 2000);
                    } else {
                        gapBtn.textContent = d.error || 'Failed';
                        gapBtn.disabled = false;
                    }
                }).catch(function() {
                    gapBtn.textContent = 'Error';
                    gapBtn.disabled = false;
                });
            });
            row.appendChild(btn);

            section.appendChild(row);
        }

        parentPanel.appendChild(section);
    } catch (e) {
        console.debug('Skill gaps load error:', e);
    }
}

async function loadConsoleNodes(zd, stationColor) {
    var panel = document.getElementById('lcarsNodesPanel');
    if (!panel) return;
    panel.textContent = '';

    // Find station IDs for this zone
    var stationIds = [];
    if (_consoleCurrentZone) {
        for (var i = 0; i < _consoleCurrentZone.zoneInfo.stations.length; i++) {
            var code = _consoleCurrentZone.zoneInfo.stations[i];
            var station = allStations.find(function(s) { return s.code === code; });
            if (station) stationIds.push(station.id);
        }
    }

    if (stationIds.length === 0 || zd.totalNodes === 0) {
        var emptyEl = document.createElement('div');
        emptyEl.className = 'lcars-empty';
        emptyEl.textContent = 'No compute nodes assigned';
        panel.appendChild(emptyEl);
        return;
    }

    // Check cache
    var cacheKey = stationIds.join(',');
    if (_consoleNodeCache[cacheKey]) {
        renderNodeCards(panel, _consoleNodeCache[cacheKey], stationColor);
        return;
    }

    var loadingEl = document.createElement('div');
    loadingEl.className = 'lcars-empty';
    loadingEl.textContent = 'Loading node data...';
    panel.appendChild(loadingEl);

    try {
        var resp = await fetch('/tools/bridge/api/stations/batch-nodes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ station_ids: stationIds })
        });
        var data = await resp.json();
        if (data.success) {
            var allNodes = [];
            for (var sid in data.stations) {
                for (var j = 0; j < data.stations[sid].length; j++) {
                    allNodes.push(data.stations[sid][j]);
                }
            }
            _consoleNodeCache[cacheKey] = allNodes;
            panel.textContent = '';
            var label = document.createElement('div');
            label.className = 'lcars-section-label';
            label.textContent = 'COMPUTE NODES (' + allNodes.length + ')';
            panel.appendChild(label);
            renderNodeCards(panel, allNodes, stationColor);
        }
    } catch (e) {
        console.error('Console nodes error:', e);
    }
}

function renderNodeCards(container, nodes, stationColor) {
    var roleOrder = ['primary', 'backup', 'relief', 'worker'];
    var grouped = {};
    for (var i = 0; i < nodes.length; i++) {
        var role = nodes[i].role || 'worker';
        if (!grouped[role]) grouped[role] = [];
        grouped[role].push(nodes[i]);
    }

    for (var r = 0; r < roleOrder.length; r++) {
        var roleName = roleOrder[r];
        if (!grouped[roleName] || grouped[roleName].length === 0) continue;

        var roleLabel = document.createElement('div');
        roleLabel.className = 'lcars-section-label';
        roleLabel.textContent = roleName.toUpperCase();
        container.appendChild(roleLabel);

        for (var j = 0; j < grouped[roleName].length; j++) {
            var node = grouped[roleName][j];
            var card = document.createElement('div');
            card.className = 'lcars-node-card';

            var header = document.createElement('div');
            header.className = 'lcars-node-header';

            var dot = document.createElement('span');
            dot.className = 'iso-status-dot';
            dot.style.background = node.status === 'online' ? '#10b981' : node.status === 'offline' ? '#ef4444' : '#f59e0b';
            header.appendChild(dot);

            var hostname = document.createElement('span');
            hostname.className = 'lcars-node-hostname';
            hostname.textContent = node.node_name || node.hostname || 'Node';
            header.appendChild(hostname);

            card.appendChild(header);

            var specs = document.createElement('div');
            specs.className = 'lcars-node-specs';
            var specItems = [];
            if (node.cpu_cores) specItems.push(node.cpu_cores + ' CPU');
            if (node.ram_gb) specItems.push(node.ram_gb + 'GB RAM');
            if (node.gpu_model) specItems.push(node.gpu_model);
            specs.textContent = specItems.join(' \u2022 ');
            card.appendChild(specs);

            if (typeof node.current_load === 'number') {
                var loadBar = document.createElement('div');
                loadBar.className = 'lcars-node-load';
                var bar = document.createElement('div');
                bar.className = 'lcars-node-load-bar';
                bar.style.width = Math.min(node.current_load, 100) + '%';
                bar.style.background = stationColor;
                loadBar.appendChild(bar);
                card.appendChild(loadBar);
            }

            container.appendChild(card);
        }
    }
}
async function loadConsoleMetrics(stationCodes) {
    var panel = document.getElementById('lcarsMetricsPanel');
    if (!panel) return;
    panel.textContent = '';

    var loadingEl = document.createElement('div');
    loadingEl.className = 'lcars-empty';
    loadingEl.textContent = 'Loading metrics...';
    panel.appendChild(loadingEl);

    var totals = { requests_24h: 0, avg_response_ms: 0, tokens_24h: 0, success_rate: 0 };
    var fetchCount = 0;

    for (var i = 0; i < stationCodes.length; i++) {
        try {
            var resp = await fetch('/tools/bridge/api/stations/' + encodeURIComponent(stationCodes[i]) + '/metrics');
            var data = await resp.json();
            if (data.success && data.metrics) {
                totals.requests_24h += data.metrics.requests_24h;
                totals.avg_response_ms += data.metrics.avg_response_ms;
                totals.tokens_24h += data.metrics.tokens_24h;
                totals.success_rate += data.metrics.success_rate;
                fetchCount++;
            }
        } catch (e) {
            console.error('Metrics fetch error for', stationCodes[i], e);
        }
    }
    if (fetchCount > 1) {
        totals.avg_response_ms = Math.round(totals.avg_response_ms / fetchCount);
        totals.success_rate = Math.round((totals.success_rate / fetchCount) * 10) / 10;
    }

    panel.textContent = '';

    var grid = document.createElement('div');
    grid.className = 'lcars-metrics-grid';

    var cards = [
        { label: 'Requests (24h)', value: totals.requests_24h.toLocaleString() },
        { label: 'Avg Response', value: totals.avg_response_ms + 'ms' },
        { label: 'Tokens Used', value: totals.tokens_24h.toLocaleString() },
        { label: 'Success Rate', value: totals.success_rate + '%' }
    ];

    for (var j = 0; j < cards.length; j++) {
        var cardData = cards[j];
        var el = document.createElement('div');
        el.className = 'lcars-metric-card';

        var val = document.createElement('div');
        val.className = 'lcars-metric-value';
        val.textContent = cardData.value;
        el.appendChild(val);

        var lbl = document.createElement('div');
        lbl.className = 'lcars-metric-label';
        lbl.textContent = cardData.label;
        el.appendChild(lbl);

        grid.appendChild(el);
    }

    panel.appendChild(grid);
}

// === CONSOLE MEMORY TAB ===

var _consoleMemoryData = [];   // cached across filter calls
var _consoleMemoryAgents = []; // agent list for the current zone

var MEMORY_TYPE_COLORS = {
    general:     '#6ee7b7',
    skill:       '#93c5fd',
    preference:  '#c4b5fd',
    interaction: '#fca5a5'
};

function memoryTypeColor(type) {
    return MEMORY_TYPE_COLORS[type] || '#94a3b8';
}

async function loadConsoleMemory() {
    var panel = document.getElementById('lcarsMemoryPanel');
    if (!panel) return;
    panel.textContent = '';

    var loadingEl = document.createElement('div');
    loadingEl.className = 'lcars-empty';
    loadingEl.textContent = 'Loading memories\u2026';
    panel.appendChild(loadingEl);

    // Gather agents from the current zone
    var agents = [];
    if (_consoleCurrentZone && _consoleCurrentZone.zd && _consoleCurrentZone.zd.agents) {
        agents = _consoleCurrentZone.zd.agents;
    }
    _consoleMemoryAgents = agents;

    if (agents.length === 0) {
        panel.textContent = '';
        var emptyEl = document.createElement('div');
        emptyEl.className = 'lcars-empty';
        emptyEl.textContent = 'No crew assigned \u2014 no memories to display';
        panel.appendChild(emptyEl);
        return;
    }

    // Fetch memories for all agents in this zone
    var allMemories = [];
    for (var i = 0; i < agents.length; i++) {
        var agent = agents[i];
        try {
            var resp = await fetch('/tools/bridge/api/agents/' + encodeURIComponent(agent.id) + '/memory?per_page=50');
            var json = await resp.json();
            if (json.success && json.data) {
                for (var j = 0; j < json.data.length; j++) {
                    var m = json.data[j];
                    m._agent_name = [agent.first_name, agent.last_name].filter(Boolean).join(' ') || agent.name || 'Agent ' + agent.id;
                    m._agent_id = agent.id;
                    allMemories.push(m);
                }
            }
        } catch (e) {
            console.error('Memory fetch error for agent', agent.id, e);
        }
    }

    // Sort by importance descending
    allMemories.sort(function(a, b) {
        return (b.importance_score || 0) - (a.importance_score || 0);
    });

    _consoleMemoryData = allMemories;
    panel.textContent = '';
    renderConsoleMemoryUI(panel, allMemories);
}

function renderConsoleMemoryUI(panel, memories) {
    // --- Header row: count + ADD button ---
    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;padding:0 2px;';

    var countLabel = document.createElement('div');
    countLabel.style.cssText = 'font-family:var(--font-mono);font-size:0.7rem;color:rgba(255,255,255,0.5);text-transform:uppercase;letter-spacing:0.08em;';
    countLabel.textContent = memories.length + ' MEMOR' + (memories.length === 1 ? 'Y' : 'IES');
    header.appendChild(countLabel);

    var addBtn = document.createElement('button');
    addBtn.style.cssText = 'background:rgba(0,255,255,0.15);border:1px solid rgba(0,255,255,0.3);color:#0ff;font-size:0.65rem;padding:3px 10px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);letter-spacing:0.06em;';
    addBtn.textContent = '+ ADD';
    addBtn.addEventListener('click', showAddMemoryForm);
    header.appendChild(addBtn);

    panel.appendChild(header);

    // --- Filter bar: type dropdown + search ---
    var filterBar = document.createElement('div');
    filterBar.style.cssText = 'display:flex;gap:6px;margin-bottom:10px;';

    var typeSelect = document.createElement('select');
    typeSelect.id = 'memoryFilterType';
    typeSelect.style.cssText = 'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);color:#fff;font-size:0.65rem;padding:4px 6px;border-radius:4px;font-family:var(--font-mono);flex:0 0 auto;';
    var typeOptions = ['all', 'general', 'skill', 'preference', 'interaction'];
    for (var t = 0; t < typeOptions.length; t++) {
        var opt = document.createElement('option');
        opt.value = typeOptions[t];
        opt.textContent = typeOptions[t].toUpperCase();
        typeSelect.appendChild(opt);
    }
    typeSelect.addEventListener('change', filterConsoleMemories);
    filterBar.appendChild(typeSelect);

    var searchInput = document.createElement('input');
    searchInput.id = 'memoryFilterSearch';
    searchInput.type = 'text';
    searchInput.placeholder = 'Search\u2026';
    searchInput.style.cssText = 'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);color:#fff;font-size:0.65rem;padding:4px 8px;border-radius:4px;font-family:var(--font-mono);flex:1;min-width:0;';
    searchInput.addEventListener('input', filterConsoleMemories);
    filterBar.appendChild(searchInput);

    panel.appendChild(filterBar);

    // --- Cards container ---
    var cardsContainer = document.createElement('div');
    cardsContainer.id = 'memoryCardsContainer';
    panel.appendChild(cardsContainer);

    renderMemoryCards(cardsContainer, memories);
}

function renderMemoryCards(container, memories) {
    container.textContent = '';

    if (memories.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'lcars-empty';
        empty.textContent = 'No memories match the current filter';
        container.appendChild(empty);
        return;
    }

    for (var i = 0; i < memories.length; i++) {
        var m = memories[i];
        var card = document.createElement('div');
        card.style.cssText = 'background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px;margin-bottom:8px;';

        // Top row: content + type badge
        var topRow = document.createElement('div');
        topRow.style.cssText = 'display:flex;align-items:flex-start;gap:8px;margin-bottom:6px;';

        var contentEl = document.createElement('div');
        contentEl.style.cssText = 'flex:1;font-size:0.72rem;color:rgba(255,255,255,0.85);line-height:1.4;word-break:break-word;';
        var contentText = m.content || '';
        if (contentText.length > 120) contentText = contentText.substring(0, 120) + '\u2026';
        contentEl.textContent = contentText;
        topRow.appendChild(contentEl);

        var typeBadge = document.createElement('span');
        var tColor = memoryTypeColor(m.memory_type);
        typeBadge.style.cssText = 'flex-shrink:0;font-size:0.55rem;padding:2px 6px;border-radius:3px;border:1px solid ' + tColor + ';color:' + tColor + ';text-transform:uppercase;letter-spacing:0.05em;font-family:var(--font-mono);';
        typeBadge.textContent = m.memory_type || 'unknown';
        topRow.appendChild(typeBadge);

        card.appendChild(topRow);

        // Importance bar
        var impScore = Math.max(0, Math.min(1, m.importance_score || 0));
        var barOuter = document.createElement('div');
        barOuter.style.cssText = 'height:3px;background:rgba(255,255,255,0.08);border-radius:2px;margin-bottom:6px;overflow:hidden;';
        var barInner = document.createElement('div');
        barInner.style.cssText = 'height:100%;border-radius:2px;background:var(--station-color,#0ff);width:' + (impScore * 100) + '%;transition:width 0.3s;';
        barOuter.appendChild(barInner);
        card.appendChild(barOuter);

        // Bottom row: agent name + score + actions
        var bottomRow = document.createElement('div');
        bottomRow.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:0.6rem;';

        var agentLabel = document.createElement('span');
        agentLabel.style.cssText = 'color:rgba(255,255,255,0.45);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
        agentLabel.textContent = m._agent_name || 'Agent';
        bottomRow.appendChild(agentLabel);

        var scoreLabel = document.createElement('span');
        scoreLabel.style.cssText = 'color:var(--station-color,#0ff);font-family:var(--font-mono);font-size:0.6rem;';
        scoreLabel.textContent = (impScore * 100).toFixed(0) + '%';
        bottomRow.appendChild(scoreLabel);

        // Edit button
        var editBtn = document.createElement('button');
        editBtn.style.cssText = 'background:none;border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.5);font-size:0.55rem;padding:2px 6px;border-radius:3px;cursor:pointer;font-family:var(--font-mono);';
        editBtn.textContent = 'EDIT';
        editBtn.dataset.memoryId = m.id;
        editBtn.dataset.agentId = m._agent_id;
        editBtn.addEventListener('click', function() {
            editMemory(parseInt(this.dataset.memoryId), parseInt(this.dataset.agentId));
        });
        bottomRow.appendChild(editBtn);

        // Delete button
        var delBtn = document.createElement('button');
        delBtn.style.cssText = 'background:none;border:1px solid rgba(255,100,100,0.25);color:rgba(255,100,100,0.6);font-size:0.55rem;padding:2px 6px;border-radius:3px;cursor:pointer;font-family:var(--font-mono);';
        delBtn.textContent = 'DEL';
        delBtn.dataset.memoryId = m.id;
        delBtn.dataset.agentId = m._agent_id;
        delBtn.addEventListener('click', function() {
            deleteMemory(parseInt(this.dataset.memoryId), parseInt(this.dataset.agentId));
        });
        bottomRow.appendChild(delBtn);

        card.appendChild(bottomRow);
        container.appendChild(card);
    }
}

function filterConsoleMemories() {
    var typeEl = document.getElementById('memoryFilterType');
    var searchEl = document.getElementById('memoryFilterSearch');
    var container = document.getElementById('memoryCardsContainer');
    if (!container) return;

    var filterType = typeEl ? typeEl.value : 'all';
    var searchText = searchEl ? searchEl.value.toLowerCase().trim() : '';

    var filtered = _consoleMemoryData.filter(function(m) {
        if (filterType !== 'all' && m.memory_type !== filterType) return false;
        if (searchText && (m.content || '').toLowerCase().indexOf(searchText) === -1) return false;
        return true;
    });

    renderMemoryCards(container, filtered);
}

function showAddMemoryForm() {
    // Build overlay
    var overlay = document.createElement('div');
    overlay.id = 'memoryFormOverlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:10001;display:flex;align-items:center;justify-content:center;';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:rgba(12,16,28,0.98);border:1px solid rgba(0,255,255,0.2);border-radius:10px;padding:20px;width:340px;max-width:90vw;max-height:80vh;overflow-y:auto;';

    // Title
    var title = document.createElement('div');
    title.style.cssText = 'font-family:var(--font-mono);font-size:0.8rem;color:#0ff;margin-bottom:14px;text-transform:uppercase;letter-spacing:0.1em;';
    title.textContent = 'Add Memory';
    modal.appendChild(title);

    // Agent selector
    var agentLabel = document.createElement('label');
    agentLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
    agentLabel.textContent = 'Agent';
    modal.appendChild(agentLabel);

    var agentSelect = document.createElement('select');
    agentSelect.id = 'memoryFormAgent';
    agentSelect.style.cssText = 'width:100%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:#fff;font-size:0.7rem;padding:6px 8px;border-radius:4px;margin-bottom:12px;font-family:var(--font-mono);';
    for (var a = 0; a < _consoleMemoryAgents.length; a++) {
        var ag = _consoleMemoryAgents[a];
        var opt = document.createElement('option');
        opt.value = ag.id;
        opt.textContent = [ag.first_name, ag.last_name].filter(Boolean).join(' ') || ag.name || 'Agent ' + ag.id;
        agentSelect.appendChild(opt);
    }
    modal.appendChild(agentSelect);

    // Content textarea
    var contentLabel = document.createElement('label');
    contentLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
    contentLabel.textContent = 'Content';
    modal.appendChild(contentLabel);

    var contentArea = document.createElement('textarea');
    contentArea.id = 'memoryFormContent';
    contentArea.rows = 4;
    contentArea.style.cssText = 'width:100%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:#fff;font-size:0.7rem;padding:8px;border-radius:4px;margin-bottom:12px;font-family:var(--font-mono);resize:vertical;box-sizing:border-box;';
    contentArea.placeholder = 'Memory content\u2026';
    modal.appendChild(contentArea);

    // Type dropdown
    var typeLabel = document.createElement('label');
    typeLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
    typeLabel.textContent = 'Type';
    modal.appendChild(typeLabel);

    var typeSelect = document.createElement('select');
    typeSelect.id = 'memoryFormType';
    typeSelect.style.cssText = 'width:100%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:#fff;font-size:0.7rem;padding:6px 8px;border-radius:4px;margin-bottom:12px;font-family:var(--font-mono);';
    var types = ['general', 'skill', 'preference', 'interaction'];
    for (var ti = 0; ti < types.length; ti++) {
        var tOpt = document.createElement('option');
        tOpt.value = types[ti];
        tOpt.textContent = types[ti].charAt(0).toUpperCase() + types[ti].slice(1);
        typeSelect.appendChild(tOpt);
    }
    modal.appendChild(typeSelect);

    // Importance slider
    var impLabel = document.createElement('label');
    impLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
    impLabel.textContent = 'Importance';
    modal.appendChild(impLabel);

    var impRow = document.createElement('div');
    impRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:16px;';

    var impSlider = document.createElement('input');
    impSlider.type = 'range';
    impSlider.id = 'memoryFormImportance';
    impSlider.min = '0';
    impSlider.max = '100';
    impSlider.value = '50';
    impSlider.style.cssText = 'flex:1;accent-color:#0ff;';

    var impVal = document.createElement('span');
    impVal.id = 'memoryFormImpVal';
    impVal.style.cssText = 'font-family:var(--font-mono);font-size:0.7rem;color:var(--station-color,#0ff);min-width:32px;text-align:right;';
    impVal.textContent = '50%';

    impSlider.addEventListener('input', function() {
        document.getElementById('memoryFormImpVal').textContent = this.value + '%';
    });

    impRow.appendChild(impSlider);
    impRow.appendChild(impVal);
    modal.appendChild(impRow);

    // Buttons
    var btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;';

    var cancelBtn = document.createElement('button');
    cancelBtn.style.cssText = 'background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.6);font-size:0.65rem;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);';
    cancelBtn.textContent = 'CANCEL';
    cancelBtn.addEventListener('click', function() {
        var ov = document.getElementById('memoryFormOverlay');
        if (ov) ov.remove();
    });
    btnRow.appendChild(cancelBtn);

    var saveBtn = document.createElement('button');
    saveBtn.style.cssText = 'background:rgba(0,255,255,0.15);border:1px solid rgba(0,255,255,0.3);color:#0ff;font-size:0.65rem;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);';
    saveBtn.textContent = 'SAVE';
    saveBtn.addEventListener('click', submitNewMemory);
    btnRow.appendChild(saveBtn);

    modal.appendChild(btnRow);
    overlay.appendChild(modal);

    // Click overlay backdrop to close
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.remove();
    });

    document.body.appendChild(overlay);
}

async function submitNewMemory() {
    var agentId = document.getElementById('memoryFormAgent').value;
    var content = document.getElementById('memoryFormContent').value.trim();
    var memoryType = document.getElementById('memoryFormType').value;
    var importance = parseInt(document.getElementById('memoryFormImportance').value) / 100;

    if (!content) {
        showToast('Content is required', 'error');
        return;
    }

    try {
        var resp = await fetch('/tools/bridge/api/agents/' + encodeURIComponent(agentId) + '/memory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content, memory_type: memoryType, importance_score: importance })
        });
        var json = await resp.json();
        if (json.success) {
            showToast('Memory created', 'success');
            var ov = document.getElementById('memoryFormOverlay');
            if (ov) ov.remove();
            loadConsoleMemory();
        } else {
            showToast('Error: ' + (json.error || 'Failed'), 'error');
        }
    } catch (e) {
        showToast('Network error: ' + e.message, 'error');
    }
}

async function editMemory(memoryId, agentId) {
    // Fetch current memory
    try {
        var resp = await fetch('/tools/bridge/api/agents/' + encodeURIComponent(agentId) + '/memory/' + encodeURIComponent(memoryId));
        var json = await resp.json();
        if (!json.success || !json.data) {
            showToast('Could not load memory', 'error');
            return;
        }
        var mem = json.data;

        // Build overlay
        var overlay = document.createElement('div');
        overlay.id = 'memoryFormOverlay';
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:10001;display:flex;align-items:center;justify-content:center;';

        var modal = document.createElement('div');
        modal.style.cssText = 'background:rgba(12,16,28,0.98);border:1px solid rgba(0,255,255,0.2);border-radius:10px;padding:20px;width:340px;max-width:90vw;max-height:80vh;overflow-y:auto;';

        // Title
        var title = document.createElement('div');
        title.style.cssText = 'font-family:var(--font-mono);font-size:0.8rem;color:#0ff;margin-bottom:14px;text-transform:uppercase;letter-spacing:0.1em;';
        title.textContent = 'Edit Memory #' + memoryId;
        modal.appendChild(title);

        // Content textarea
        var contentLabel = document.createElement('label');
        contentLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
        contentLabel.textContent = 'Content';
        modal.appendChild(contentLabel);

        var contentArea = document.createElement('textarea');
        contentArea.id = 'memoryEditContent';
        contentArea.rows = 4;
        contentArea.style.cssText = 'width:100%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:#fff;font-size:0.7rem;padding:8px;border-radius:4px;margin-bottom:12px;font-family:var(--font-mono);resize:vertical;box-sizing:border-box;';
        contentArea.value = mem.content || '';
        modal.appendChild(contentArea);

        // Type dropdown
        var typeLabel = document.createElement('label');
        typeLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
        typeLabel.textContent = 'Type';
        modal.appendChild(typeLabel);

        var typeSelect = document.createElement('select');
        typeSelect.id = 'memoryEditType';
        typeSelect.style.cssText = 'width:100%;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:#fff;font-size:0.7rem;padding:6px 8px;border-radius:4px;margin-bottom:12px;font-family:var(--font-mono);';
        var types = ['general', 'skill', 'preference', 'interaction'];
        for (var ti = 0; ti < types.length; ti++) {
            var tOpt = document.createElement('option');
            tOpt.value = types[ti];
            tOpt.textContent = types[ti].charAt(0).toUpperCase() + types[ti].slice(1);
            if (types[ti] === mem.memory_type) tOpt.selected = true;
            typeSelect.appendChild(tOpt);
        }
        modal.appendChild(typeSelect);

        // Importance slider
        var impLabel = document.createElement('label');
        impLabel.style.cssText = 'display:block;font-size:0.6rem;color:rgba(255,255,255,0.5);margin-bottom:4px;font-family:var(--font-mono);text-transform:uppercase;letter-spacing:0.06em;';
        impLabel.textContent = 'Importance';
        modal.appendChild(impLabel);

        var impRow = document.createElement('div');
        impRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:16px;';

        var currentImp = Math.round((mem.importance_score || 0.5) * 100);
        var impSlider = document.createElement('input');
        impSlider.type = 'range';
        impSlider.id = 'memoryEditImportance';
        impSlider.min = '0';
        impSlider.max = '100';
        impSlider.value = String(currentImp);
        impSlider.style.cssText = 'flex:1;accent-color:#0ff;';

        var impVal = document.createElement('span');
        impVal.id = 'memoryEditImpVal';
        impVal.style.cssText = 'font-family:var(--font-mono);font-size:0.7rem;color:var(--station-color,#0ff);min-width:32px;text-align:right;';
        impVal.textContent = currentImp + '%';

        impSlider.addEventListener('input', function() {
            document.getElementById('memoryEditImpVal').textContent = this.value + '%';
        });

        impRow.appendChild(impSlider);
        impRow.appendChild(impVal);
        modal.appendChild(impRow);

        // Buttons
        var btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;';

        var cancelBtn = document.createElement('button');
        cancelBtn.style.cssText = 'background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);color:rgba(255,255,255,0.6);font-size:0.65rem;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);';
        cancelBtn.textContent = 'CANCEL';
        cancelBtn.addEventListener('click', function() {
            var ov = document.getElementById('memoryFormOverlay');
            if (ov) ov.remove();
        });
        btnRow.appendChild(cancelBtn);

        var saveBtn = document.createElement('button');
        saveBtn.style.cssText = 'background:rgba(0,255,255,0.15);border:1px solid rgba(0,255,255,0.3);color:#0ff;font-size:0.65rem;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);';
        saveBtn.textContent = 'SAVE';
        saveBtn.addEventListener('click', function() {
            submitEditMemory(memoryId, agentId);
        });
        btnRow.appendChild(saveBtn);

        modal.appendChild(btnRow);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) overlay.remove();
        });

        document.body.appendChild(overlay);
    } catch (e) {
        showToast('Error loading memory: ' + e.message, 'error');
    }
}

async function submitEditMemory(memoryId, agentId) {
    var content = document.getElementById('memoryEditContent').value.trim();
    var memoryType = document.getElementById('memoryEditType').value;
    var importance = parseInt(document.getElementById('memoryEditImportance').value) / 100;

    if (!content) {
        showToast('Content is required', 'error');
        return;
    }

    try {
        var resp = await fetch('/tools/bridge/api/agents/' + encodeURIComponent(agentId) + '/memory/' + encodeURIComponent(memoryId), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content, memory_type: memoryType, importance_score: importance })
        });
        var json = await resp.json();
        if (json.success) {
            showToast('Memory updated', 'success');
            var ov = document.getElementById('memoryFormOverlay');
            if (ov) ov.remove();
            loadConsoleMemory();
        } else {
            showToast('Error: ' + (json.error || 'Failed'), 'error');
        }
    } catch (e) {
        showToast('Network error: ' + e.message, 'error');
    }
}

async function deleteMemory(memoryId, agentId) {
    if (!confirm('Delete memory #' + memoryId + '? This is a soft delete.')) return;

    var reason = prompt('Deletion reason (optional):', 'Manual deletion from Bridge console');
    if (reason === null) return; // user cancelled

    try {
        var resp = await fetch('/tools/bridge/api/agents/' + encodeURIComponent(agentId) + '/memory/' + encodeURIComponent(memoryId), {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: reason || 'Manual deletion from Bridge console' })
        });
        var json = await resp.json();
        if (json.success) {
            showToast('Memory deleted', 'success');
            loadConsoleMemory();
        } else {
            showToast('Error: ' + (json.error || 'Failed'), 'error');
        }
    } catch (e) {
        showToast('Network error: ' + e.message, 'error');
    }
}

// === END CONSOLE MEMORY TAB ===

async function showModulePreview(mod) {
    var panel = document.getElementById('lcarsModulePreviewPanel');
    if (!panel) return;

    // Switch to preview panel
    document.querySelectorAll('.lcars-tab-panel').forEach(function(p) {
        p.classList.toggle('active', p.dataset.consolePanel === 'module-preview');
    });

    panel.textContent = '';

    // Back link
    var backLink = document.createElement('div');
    backLink.className = 'lcars-back-link';
    backLink.textContent = '\u2190 Back to Station';
    backLink.addEventListener('click', function() {
        switchConsoleTab('crew');
    });
    panel.appendChild(backLink);

    var card = document.createElement('div');
    card.className = 'lcars-module-preview';

    // Header with icon + name
    var header = document.createElement('div');
    header.className = 'lcars-module-preview-header';
    var icon = document.createElement('i');
    icon.setAttribute('data-lucide', mod.icon || 'box');
    header.appendChild(icon);
    var name = document.createElement('div');
    name.className = 'lcars-module-preview-name';
    name.textContent = mod.name;
    header.appendChild(name);
    card.appendChild(header);

    // Description (strip HTML tags safely)
    if (mod.description) {
        var desc = document.createElement('div');
        desc.className = 'lcars-module-preview-desc';
        // Strip HTML by creating a temp element
        var tempEl = document.createElement('div');
        tempEl.textContent = mod.description;
        // If description contains HTML entities, parse them
        var cleanText = mod.description.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
        desc.textContent = cleanText;
        card.appendChild(desc);
    }

    // Fetch preview stats if we have a station context
    if (_consoleCurrentZone && mod.id) {
        try {
            var stationCode = _consoleCurrentZone.zoneInfo.stations[0];
            var resp = await fetch('/tools/bridge/api/stations/' + encodeURIComponent(stationCode) + '/module-preview/' + encodeURIComponent(mod.id));
            var data = await resp.json();
            if (data.success && data.module && data.module.stats) {
                var statsKeys = Object.keys(data.module.stats);
                if (statsKeys.length > 0) {
                    var statsDiv = document.createElement('div');
                    statsDiv.style.cssText = 'display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px;';
                    for (var k = 0; k < statsKeys.length; k++) {
                        var key = statsKeys[k];
                        var statVal = data.module.stats[key];
                        var pill = document.createElement('div');
                        pill.style.cssText = 'background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:6px 12px;text-align:center;';

                        var pillVal = document.createElement('div');
                        pillVal.style.cssText = 'font-family:Orbitron,sans-serif;font-weight:700;color:var(--station-color);';
                        pillVal.textContent = String(statVal);
                        pill.appendChild(pillVal);

                        var pillLabel = document.createElement('div');
                        pillLabel.style.cssText = 'font-size:0.6rem;opacity:0.5;text-transform:uppercase;letter-spacing:0.05em;';
                        pillLabel.textContent = key.replace(/_/g, ' ');
                        pill.appendChild(pillLabel);

                        statsDiv.appendChild(pill);
                    }
                    card.appendChild(statsDiv);
                }
            }
        } catch (e) {
            // Stats are optional — silently skip
        }
    }

    // Open Module button
    if (mod.route) {
        var btn = document.createElement('a');
        btn.className = 'lcars-module-open-btn';
        btn.href = mod.route;
        btn.textContent = 'Open Module \u2192';
        card.appendChild(btn);
    }

    panel.appendChild(card);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// ── Warp-In Intro ──
function triggerWarpIntro() {
    const overlay = document.getElementById('isoWarpOverlay');
    const room = document.getElementById('bridgeSpatialLayout');
    if (!overlay || !room) return;

    // Add warp-active to delay hull/viewscreen/station animations
    room.classList.add('warp-active');

    // Reset overlay: remove played class, make visible, force reflow
    overlay.classList.remove('played');
    overlay.style.opacity = '1';
    overlay.style.visibility = 'visible';
    overlay.offsetHeight; // force reflow

    // Reset hull/viewscreen/station animations so they replay after warp
    const hull = document.querySelector('.iso-bridge-hull');
    const vs = document.querySelector('.iso-viewscreen');
    if (hull) { hull.style.animation = 'none'; hull.offsetHeight; hull.style.animation = ''; }
    if (vs) { vs.style.animation = 'none'; vs.offsetHeight; vs.style.animation = ''; }
    document.querySelectorAll('.iso-station-zone').forEach(function(z) {
        z.style.animation = 'none'; z.offsetHeight; z.style.animation = '';
    });

    // Start the warp sequence
    overlay.classList.add('played');

    // Remove warp-active after all animations complete (~2.5s)
    setTimeout(function() {
        room.classList.remove('warp-active');
    }, 2500);
}

function getInitials(name) {
    if (!name) return '??';
    const parts = name.trim().split(/\s+/);
    if (parts.length === 1) {
        return parts[0].substring(0, 2).toUpperCase();
    }
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function updateStationStats(stations) {
    const totalAgents = stations.reduce((sum, s) => sum + (s.assigned_agents?.length || 0), 0);

    // Update viewscreen agent count
    const agentCountEl = document.getElementById('viewscreenAgentCount');
    if (agentCountEl) {
        agentCountEl.textContent = totalAgents + ' agents';
    }

    // Also update overview HUD counters if they exist
    const stationCountEl = document.getElementById('station-count');
    if (stationCountEl) stationCountEl.textContent = stations.length;
    const agentHudEl = document.getElementById('agent-count');
    if (agentHudEl) agentHudEl.textContent = totalAgents;
}

// ============================================================================
// VIEWSCREEN DATA LOADING
// ============================================================================

function getStationForModule(moduleName) {
    if (!moduleName) return 'COMMAND';

    // First: check allStations for an exact module match
    if (allStations && allStations.length > 0) {
        for (const station of allStations) {
            if (station.modules && station.modules.includes(moduleName)) {
                return station.code;
            }
        }
    }

    // Fallback heuristics on lowercased name
    const lower = moduleName.toLowerCase();
    if (lower.includes('consciousness') || lower.includes('knowledge')) return 'CONSCIOUSNESS';
    if (lower.includes('security') || lower.includes('vigil')) return 'SECURITY';
    if (lower.includes('bridge') || lower.includes('chat')) return 'COMMAND';
    if (lower.includes('email') || lower.includes('telegram')) return 'OPERATIONS';
    return 'COMMAND';
}

function renderViewscreen(events, trafficData) {
    const feedEl = document.getElementById('viewscreenFeed');
    if (!feedEl) return;

    // Handle empty state
    if (!events || events.length === 0) {
        feedEl.innerHTML = '<div class="bridge-viewscreen-empty">No recent dispatch activity</div>';
    } else {
        let html = '';
        for (const evt of events) {
            const rawStationCode = getStationForModule(evt.module_source);
            // Map to isometric zone for arc targeting and display
            const zoneName = STATION_TO_ISO_ZONE[rawStationCode] || rawStationCode;
            const zoneInfo = ISOMETRIC_ZONE_MAP[zoneName];
            const zoneColor = zoneInfo ? zoneInfo.color : (STATION_COLORS[rawStationCode] || '#00FFFF');
            const zoneAbbr = zoneInfo ? zoneInfo.abbr : rawStationCode;

            // Parse time from created_at (ISO string)
            let timeStr = '--:--:--';
            if (evt.created_at) {
                timeStr = ArchieTime.time(evt.created_at);
            }

            // Success status icon
            let statusHtml = '<span class="viewscreen-status pending">&hellip;</span>';
            if (evt.success === true) {
                statusHtml = '<span class="viewscreen-status success">&check;</span>';
            } else if (evt.success === false) {
                statusHtml = '<span class="viewscreen-status fail">&cross;</span>';
            }

            // Build short task description from task_type/capability
            var taskDesc = evt.task_type || evt.capability || '';
            // Clean up common prefixes and make readable
            taskDesc = taskDesc.replace(/_/g, ' ');

            html += '<div class="bridge-viewscreen-event" data-station-code="' + escapeHtml(zoneName) + '">'
                + '<span class="viewscreen-time">' + escapeHtml(timeStr) + '</span>'
                + '<span class="viewscreen-agent">' + escapeHtml(evt.agent_name || 'Unknown') + '</span>'
                + '<span class="viewscreen-arrow">&rarr;</span>'
                + '<span class="viewscreen-station" style="color:' + zoneColor + '">' + escapeHtml(zoneAbbr) + '</span>'
                + '<span class="viewscreen-task">' + escapeHtml(taskDesc) + '</span>'
                + statusHtml
                + '</div>';
        }
        feedEl.innerHTML = html;
    }

    // Update statusbar: throughput
    const throughputEl = document.getElementById('viewscreenThroughput');
    if (throughputEl && trafficData) {
        const rpm = parseFloat(trafficData.requests_per_minute) || 0;
        throughputEl.textContent = rpm.toFixed(1) + ' req/min';
    }

    // Update statusbar: success rate from events
    const successEl = document.getElementById('viewscreenSuccess');
    if (successEl && events && events.length > 0) {
        const successCount = events.filter(function(e) { return e.success === true; }).length;
        const pct = Math.round(successCount / events.length * 100);
        successEl.textContent = pct + '% success';
    }

    // Trigger arc animation for newest event
    setTimeout(triggerArcsFromViewscreen, 100);
}

async function loadViewscreenData() {
    try {
        const [activityResp, trafficResp] = await Promise.all([
            fetch('/tools/bridge/api/dispatch/activity-history'),
            fetch('/tools/bridge/api/traffic')
        ]);

        const activityData = await activityResp.json();
        const trafficData = await trafficResp.json();

        const events = Array.isArray(activityData) ? activityData : (activityData.events || []);
        renderViewscreen(events.slice(0, 5), trafficData);
    } catch (error) {
        console.error('Error loading viewscreen data:', error);
    }
}

// ============================================================================
// DISPATCH ARC ANIMATIONS
// ============================================================================

const MAX_ACTIVE_ARCS = 3;
let activeArcs = [];
let _lastViewscreenEventId = null;

/**
 * Creates an animated SVG bezier arc from the viewscreen to a target station zone.
 */
function createDispatchArc(stationCode) {
    // Skip on mobile — arcs hidden by CSS anyway
    if (window.innerWidth < 768) return;

    // Map raw station code to isometric zone
    const zoneName = STATION_TO_ISO_ZONE[stationCode] || stationCode;

    const overlay = document.getElementById('dispatchArcOverlay');
    const viewscreen = document.getElementById('bridgeViewscreen');
    const stationZone = document.querySelector('.iso-station-zone[data-station-code="' + zoneName + '"]');
    const container = document.getElementById('bridgeSpatialLayout');

    if (!overlay || !viewscreen || !stationZone || !container) return;

    const containerRect = container.getBoundingClientRect();
    const vsRect = viewscreen.getBoundingClientRect();
    const szRect = stationZone.getBoundingClientRect();

    // Positions relative to the spatial layout container
    const fromX = (vsRect.left + vsRect.width / 2) - containerRect.left;
    const fromY = vsRect.bottom - containerRect.top;
    const toX = (szRect.left + szRect.width / 2) - containerRect.left;
    const toY = szRect.top - containerRect.top;

    // Set SVG viewBox to container dimensions
    overlay.setAttribute('viewBox', '0 0 ' + containerRect.width + ' ' + containerRect.height);

    // Create quadratic bezier path
    const midY = (fromY + toY) / 2;
    const cpX = (fromX + toX) / 2 + (fromX > toX ? 40 : -40);
    const d = 'M ' + fromX + ' ' + fromY + ' Q ' + cpX + ' ' + midY + ' ' + toX + ' ' + toY;

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('class', 'bridge-dispatch-arc');
    const arcColor = (ISOMETRIC_ZONE_MAP[zoneName] && ISOMETRIC_ZONE_MAP[zoneName].color) || STATION_COLORS[stationCode] || '#00FFFF';
    path.setAttribute('stroke', arcColor);

    // Estimate path length for dash animation
    const pathLen = Math.sqrt((toX - fromX) ** 2 + (toY - fromY) ** 2) * 1.3;
    path.setAttribute('stroke-dasharray', pathLen);
    path.setAttribute('stroke-dashoffset', pathLen);
    path.style.setProperty('--arc-length', pathLen);
    path.style.animation = 'arc-draw 0.8s ease forwards';

    // Cap active arcs — remove oldest if at limit
    if (activeArcs.length >= MAX_ACTIVE_ARCS) {
        const oldest = activeArcs.shift();
        if (oldest && oldest.parentNode) {
            oldest.parentNode.removeChild(oldest);
        }
    }

    overlay.appendChild(path);
    activeArcs.push(path);

    // Highlight the target station zone
    stationZone.classList.add('dispatch-active');

    // Fade out after 2.8s
    setTimeout(function() {
        path.classList.add('fading');
        stationZone.classList.remove('dispatch-active');
    }, 2800);

    // Remove from DOM after 4s
    setTimeout(function() {
        if (path.parentNode) {
            path.parentNode.removeChild(path);
        }
        const idx = activeArcs.indexOf(path);
        if (idx !== -1) activeArcs.splice(idx, 1);
    }, 4000);
}

/**
 * Check if the viewscreen has new events since last call and trigger an arc.
 */
function triggerArcsFromViewscreen() {
    const firstEvent = document.querySelector('.bridge-viewscreen-event');
    if (!firstEvent) return;

    const stationCode = firstEvent.getAttribute('data-station-code');
    const timeEl = firstEvent.querySelector('.viewscreen-time');
    const eventKey = stationCode + '|' + (timeEl ? timeEl.textContent : '');

    if (eventKey !== _lastViewscreenEventId) {
        _lastViewscreenEventId = eventKey;
        if (stationCode) {
            createDispatchArc(stationCode);
        }
    }
}

// Clear arcs + cross-station lines on window resize (positions become stale)
let _resizeTimer = null;
window.addEventListener('resize', function() {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(function() {
        const overlay = document.getElementById('dispatchArcOverlay');
        if (overlay) overlay.innerHTML = '';
        activeArcs = [];
    }, 250);
});

// ============================================================================
// IAAE STATUS
// ============================================================================

async function loadIAAEStatus() {
    try {
        const response = await fetch('/tools/bridge/api/agents/welfare');
        const data = await response.json();

        if (data.success) {
            const statusEl = document.getElementById('iaae-status');
            if (statusEl) {
                var fh = data.fleet_health || {};
                var atRisk = fh.agents_at_risk || 0;
                var resting = fh.agents_resting || 0;
                if (atRisk > 0) {
                    statusEl.textContent = atRisk + ' At Risk';
                    statusEl.style.color = 'var(--archie-danger)';
                } else if (resting > 0) {
                    statusEl.textContent = resting + ' Resting';
                    statusEl.style.color = 'var(--archie-warning)';
                } else {
                    statusEl.textContent = 'All Clear';
                    statusEl.style.color = 'var(--archie-success)';
                }
            }
        }
    } catch (error) {
        console.error('Error loading IAAE status:', error);
    }
}

// ============================================================================
// STAFFING STATUS
// ============================================================================

async function loadStaffingStatus() {
    try {
        const response = await fetch('/tools/bridge/api/agents/workload');
        const data = await response.json();

        if (data.success) {
            const badge = document.getElementById('staffing-badge');
            const text = document.getElementById('staffing-text');
            var agents = data.agents || [];
            var active = agents.filter(function(a) { return a.status === 'active'; }).length;
            var total = agents.length;

            if (badge && text) {
                if (active === total && total > 0) {
                    badge.className = 'staffing-badge full-staff';
                    text.textContent = 'Full Staff';
                } else {
                    badge.className = 'staffing-badge reduced-staff';
                    text.textContent = active + '/' + total + ' Active';
                }
            }
        }
    } catch (error) {
        console.error('Error loading staffing status:', error);
    }
}

// ============================================================================
// NODE NETWORK MANAGEMENT
// ============================================================================

async function loadNodes() {
    try {
        const response = await fetch('/tools/bridge/api/nodes');
        const data = await response.json();

        if (data.success) {
            renderNodeStats(data.summary);
            renderNodeGrid(data.nodes);
        }
    } catch (error) {
        console.error('Error loading nodes:', error);
    }
}

function renderNodeStats(summary) {
    document.getElementById('nodes-online').textContent = summary.online || 0;
    document.getElementById('nodes-offline').textContent = summary.offline || 0;
    document.getElementById('nodes-pending').textContent = summary.pending || 0;
}

function renderNodeGrid(nodes) {
    const pendingGrid = document.getElementById('pending-nodes-grid');
    const activeGrid = document.getElementById('active-nodes-grid');
    const pendingSection = document.getElementById('pending-nodes-section');

    const pendingNodes = nodes.filter(n => n.approval_status === 'pending');
    const approvedNodes = nodes.filter(n => n.approval_status === 'approved');

    // Show/hide pending section
    pendingSection.style.display = pendingNodes.length > 0 ? 'block' : 'none';

    // Render pending nodes
    pendingGrid.innerHTML = pendingNodes.map(renderNodeCard).join('');

    // Render approved nodes
    activeGrid.innerHTML = approvedNodes.length > 0
        ? approvedNodes.map(renderNodeCard).join('')
        : '';

    // Initialize lucide icons for new elements
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function renderNodeCard(node) {
    const status = node.approval_status === 'pending' ? 'pending' : (node.status || 'offline');
    const currentLoad = node.current_load || 0;
    const maxConcurrent = node.max_concurrent || 5;
    const loadPercent = maxConcurrent > 0 ? (currentLoad / maxConcurrent * 100) : 0;
    const available = maxConcurrent - currentLoad;
    const isPending = node.approval_status === 'pending';
    const bridgeEnabled = node.bridge_enabled || false;
    const hasOllama = node.ollama_available || false;

    // Friendly capacity status
    let capacityStatus, capacityClass;
    if (currentLoad === 0) {
        capacityStatus = 'Idle';
        capacityClass = 'idle';
    } else if (currentLoad >= maxConcurrent) {
        capacityStatus = 'At Capacity';
        capacityClass = 'full';
    } else {
        capacityStatus = `${currentLoad} Active`;
        capacityClass = 'active';
    }

    return `
        <div class="node-card ${status}" data-node-id="${node.node_id}">
            <div class="node-header">
                <span class="status-dot ${status}"></span>
                <span class="node-id">${node.node_id.substring(0, 16)}...</span>
                <span class="status-badge ${status}">${status.toUpperCase()}</span>
            </div>
            <div class="node-body">
                <div class="node-name">${escapeHtml(node.node_name)}</div>
                ${node.org_name ? `<div class="node-org-badge"><i data-lucide="building" style="width:11px;height:11px;"></i> ${escapeHtml(node.org_name)}</div>` : ''}
                <div class="node-connection">${node.vpn_ip || node.hostname || 'Unknown'}:${node.port || 11434}</div>
                <div class="node-specs">
                    <span><i data-lucide="cpu" style="width:12px;height:12px;"></i> ${node.cpu_cores || '?'} cores</span>
                    <span><i data-lucide="memory-stick" style="width:12px;height:12px;"></i> ${node.ram_gb || '?'}GB</span>
                    ${node.gpu_model ? `<span><i data-lucide="monitor" style="width:12px;height:12px;"></i> ${node.gpu_model}</span>` : ''}
                </div>
            </div>
            ${!isPending ? `
            <div class="node-load">
                <div class="load-bar-container">
                    <div class="load-bar ${capacityClass}" style="width: ${loadPercent}%"></div>
                </div>
                <div class="load-text">
                    <span class="capacity-status ${capacityClass}">${capacityStatus}</span>
                    <span class="capacity-available">${available} of ${maxConcurrent} available</span>
                </div>
                <div class="load-latency">${node.avg_latency_ms ? Math.round(node.avg_latency_ms) + 'ms latency' : ''}</div>
            </div>
            ${hasOllama ? `
            <div class="bridge-toggle">
                <div class="bridge-toggle-label ${bridgeEnabled ? 'enabled' : ''}">
                    <i data-lucide="share-2"></i>
                    <span>Bridge LLM</span>
                </div>
                <label class="toggle-switch">
                    <input type="checkbox"
                           id="bridge-${node.node_id}"
                           ${bridgeEnabled ? 'checked' : ''}
                           onchange="toggleBridgeSharing('${node.node_id}', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            ` : ''}
            ` : ''}
            <div class="node-actions">
                ${isPending ? `
                    <button class="approve" onclick="approveNode('${node.node_id}')">APPROVE</button>
                    <button class="reject" onclick="rejectNode('${node.node_id}')">REJECT</button>
                ` : `
                    <button onclick="testNode(event, '${node.node_id}')">TEST</button>
                    ${currentLoad > 0 ? '<button style="background: rgba(139,92,246,0.2); color: #a78bfa; border-color: rgba(139,92,246,0.3);" onclick="showRequestHelpModal(\'' + escapeHtml(node.node_id) + '\', \'' + escapeHtml(node.node_name || node.node_id) + '\', ' + currentLoad + ', ' + maxConcurrent + ')">HELP</button>' : ''}
                    <button onclick="showNodeDetail('${node.node_id}')">DETAIL</button>
                    <button class="danger" onclick="removeNode('${node.node_id}', '${escapeHtml(node.node_name || node.node_id)}')">REMOVE</button>
                `}
            </div>
        </div>
    `;
}

async function approveNode(nodeId) {
    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/approve`, { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            showToast(`Node approved: ${data.node_name}`, 'success');
            loadNodes();
        } else {
            showToast(`Failed to approve: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error approving node:', error);
        showToast('Error approving node', 'error');
    }
}

async function rejectNode(nodeId) {
    const reason = prompt('Reason for rejection (optional):');

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: reason || 'Rejected by admin' })
        });
        const data = await response.json();

        if (data.success) {
            showToast(`Node rejected: ${data.node_name}`, 'warning');
            loadNodes();
        } else {
            showToast(`Failed to reject: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error rejecting node:', error);
        showToast('Error rejecting node', 'error');
    }
}

async function testNode(event, nodeId) {
    const btn = event.target;
    btn.textContent = 'TESTING...';
    btn.disabled = true;

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/test`, { method: 'POST' });
        const data = await response.json();

        if (data.reachable) {
            showToast(`Node reachable! Latency: ${data.latency_ms}ms, ${data.models_count} models`, 'success');
        } else {
            showToast(`Node unreachable: ${data.error}`, 'error');
        }
    } catch (error) {
        console.error('Error testing node:', error);
        showToast('Error testing node', 'error');
    } finally {
        btn.textContent = 'TEST';
        btn.disabled = false;
    }
}

async function removeNode(nodeId, nodeName) {
    if (!confirm('Remove node "' + nodeName + '"? This will delete the node and all its model registrations.')) return;
    try {
        var response = await fetch('/tools/bridge/api/nodes/' + nodeId, { method: 'DELETE' });
        var data = await response.json();
        if (data.success) {
            showToast('Node removed: ' + escapeHtml(nodeName), 'success');
            loadNodes();
            loadModelAvailability();
        } else {
            showToast('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error removing node:', error);
        showToast('Error removing node', 'error');
    }
}

// ============================================================================
// NODE DETAILS MODAL
// ============================================================================

let currentNodeId = null;
let currentNodeData = null;
let healthChart = null;

async function showNodeDetail(nodeId) {
    currentNodeId = nodeId;

    try {
        // Fetch node details, models, and stations in parallel
        const [nodeResp, stationsResp, modelsResp] = await Promise.all([
            fetch(`/tools/bridge/api/nodes/${nodeId}`),
            fetch(`/tools/bridge/api/nodes/${nodeId}/stations`),
            fetch(`/tools/bridge/api/nodes/${nodeId}/models`)
        ]);

        const nodeData = await nodeResp.json();
        const stationsData = await stationsResp.json();
        const modelsData = await modelsResp.json();

        if (!nodeData.success) {
            showToast('Failed to load node details', 'error');
            return;
        }

        currentNodeData = nodeData;

        // Populate Overview Tab
        const node = nodeData.node;
        document.getElementById('node-detail-title').textContent = node.node_name || 'Unknown Node';
        document.getElementById('node-detail-status').className = `node-detail-status ${node.status || 'offline'}`;

        document.getElementById('nd-node-id').textContent = node.node_id || '--';
        document.getElementById('nd-hostname').textContent = node.hostname || '--';
        document.getElementById('nd-ip').textContent = node.vpn_ip || '--';
        document.getElementById('nd-port').textContent = node.port || '11434';
        document.getElementById('nd-os').textContent = node.os_info || '--';
        document.getElementById('nd-registered').textContent = node.created_at ? ArchieTime.date(node.created_at) : '--';
        document.getElementById('nd-heartbeat').textContent = node.last_heartbeat ? formatTimeAgo(node.last_heartbeat) : '--';

        document.getElementById('nd-cpu').textContent = node.cpu_model || '--';
        document.getElementById('nd-cores').textContent = node.cpu_cores || '--';
        document.getElementById('nd-ram').textContent = node.ram_gb ? `${node.ram_gb} GB` : '--';
        document.getElementById('nd-disk').textContent = node.disk_gb ? `${node.disk_gb} GB` : '--';
        document.getElementById('nd-gpu').textContent = node.gpu_model || 'None';
        document.getElementById('nd-vram').textContent = node.gpu_vram_gb ? `${node.gpu_vram_gb} GB` : '--';

        // Status cards
        document.getElementById('nd-status-load').textContent = `${node.current_load || 0}/${node.max_concurrent || 5}`;
        document.getElementById('nd-status-latency').textContent = node.avg_latency_ms ? `${Math.round(node.avg_latency_ms)}ms` : '--';
        document.getElementById('nd-status-models').textContent = (nodeData.capabilities || []).length;
        document.getElementById('nd-status-stations').textContent = (stationsData.stations || []).length;

        // Populate Stations Tab
        renderNodeStations(stationsData.stations || []);

        // Populate Models/Services Tab
        renderNodeServices(node);  // Render AI services grid
        renderNodeModels(nodeData.capabilities || [], modelsData.models || []);

        // Populate Health Tab
        renderNodeHealth(nodeData.heartbeats || []);

        // Populate Config Tab
        document.getElementById('nd-config-name').value = node.node_name || '';
        document.getElementById('nd-config-desc').value = node.description || '';
        document.getElementById('nd-config-max').value = node.max_concurrent || 5;
        document.getElementById('nd-config-priority').value = node.priority || 10;
        document.getElementById('nd-config-weight').value = node.weight || 100;
        document.getElementById('nd-config-bridge').checked = node.bridge_enabled || false;

        // Load available stations for assignment dropdown
        await loadStationsForAssignment();

        // Show modal
        document.getElementById('node-detail-modal').classList.add('active');
        switchNodeTab('overview');

        // Reinitialize Lucide icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }

    } catch (error) {
        console.error('Error loading node details:', error);
        showToast('Error loading node details', 'error');
    }
}

function closeNodeDetailModal() {
    document.getElementById('node-detail-modal').classList.remove('active');
    currentNodeId = null;
    currentNodeData = null;
    hideAddStationToNode();
}

function switchNodeTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.node-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Update tab content
    document.querySelectorAll('.node-tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `tab-${tabName}`);
    });

    // Reinitialize icons
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function formatTimeAgo(dateStr) {
    return ArchieTime.age(dateStr);
}

// Store for all stations with assignment status
let allStationsForNode = [];

async function renderNodeStations(assignedStations) {
    const container = document.getElementById('node-stations-list');

    const stationColors = {
        'COMMAND': '#FFD700', 'CONSCIOUSNESS': '#FF00FF', 'HR': '#10B981',
        'RND': '#8B5CF6', 'ENGINEERING': '#0EA5E9', 'OPERATIONS': '#FFAA00',
        'CREATIVE': '#F472B6', 'SECURITY': '#EF4444', 'MEDICAL': '#84CC16',
        'AWAY_TEAM': '#F59E0B', 'INFRASTRUCTURE': '#3B82F6', 'FINANCE': '#A855F7',
        'DOCUMENTATION': '#22C55E', 'QA': '#F97316', 'ADMIN': '#6366F1'
    };

    // Fetch all stations if not cached
    if (allStationsForNode.length === 0) {
        try {
            const resp = await fetch('/tools/bridge/api/stations');
            const data = await resp.json();
            if (data.success) {
                allStationsForNode = data.stations;
            }
        } catch (e) {
            console.error('Error fetching stations:', e);
        }
    }

    // Create a map of assigned stations by station_id
    const assignedMap = new Map();
    (assignedStations || []).forEach(s => {
        assignedMap.set(s.station_id, s);
    });

    // Render all stations with toggle switches
    container.innerHTML = allStationsForNode.map(station => {
        const assigned = assignedMap.get(station.id);
        const isActive = !!assigned;
        const role = assigned?.role || 'worker';
        const color = stationColors[station.code] || '#6e7681';

        return `
            <div class="station-toggle-row ${isActive ? 'active' : ''}" data-station-id="${station.id}">
                <div class="station-toggle-info">
                    <div class="station-color-dot" style="background: ${color}"></div>
                    <span class="station-toggle-name">${escapeHtml(station.name)}</span>
                </div>
                <select class="station-role-select"
                        id="role-${station.id}"
                        ${!isActive ? 'disabled' : ''}
                        onchange="updateNodeStationRole(${station.id}, this.value)">
                    <option value="worker" ${role === 'worker' ? 'selected' : ''}>Worker</option>
                    <option value="primary" ${role === 'primary' ? 'selected' : ''}>Primary</option>
                    <option value="backup" ${role === 'backup' ? 'selected' : ''}>Backup</option>
                </select>
                <label class="toggle-switch-small">
                    <input type="checkbox"
                           ${isActive ? 'checked' : ''}
                           onchange="toggleNodeStation(${station.id}, this.checked)">
                    <span class="toggle-slider-small"></span>
                </label>
            </div>
        `;
    }).join('');
}

async function toggleNodeStation(stationId, enabled) {
    if (enabled) {
        // Assign node to station
        const role = document.getElementById(`role-${stationId}`).value || 'worker';
        try {
            const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}/stations`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    station_id: stationId,
                    role: role,
                    priority: 10
                })
            });
            const data = await response.json();
            if (data.success) {
                showToast('Node assigned to station', 'success');
                // Enable role select and update row style
                const row = document.querySelector(`[data-station-id="${stationId}"]`);
                row.classList.add('active');
                document.getElementById(`role-${stationId}`).disabled = false;
                loadStations(); // Refresh main view
            } else {
                showToast(data.error || 'Failed to assign', 'error');
                // Revert toggle
                event.target.checked = false;
            }
        } catch (error) {
            console.error('Error assigning:', error);
            showToast('Error assigning node', 'error');
            event.target.checked = false;
        }
    } else {
        // Remove node from station
        try {
            const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}/stations/${stationId}`, {
                method: 'DELETE'
            });
            const data = await response.json();
            if (data.success) {
                showToast('Node removed from station', 'success');
                // Disable role select and update row style
                const row = document.querySelector(`[data-station-id="${stationId}"]`);
                row.classList.remove('active');
                document.getElementById(`role-${stationId}`).disabled = true;
                loadStations(); // Refresh main view
            } else {
                showToast(data.error || 'Failed to remove', 'error');
                event.target.checked = true;
            }
        } catch (error) {
            console.error('Error removing:', error);
            showToast('Error removing node', 'error');
            event.target.checked = true;
        }
    }
}

async function updateNodeStationRole(stationId, newRole) {
    try {
        const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}/stations/${stationId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole })
        });
        const data = await response.json();
        if (data.success) {
            showToast(`Role updated to ${newRole}`, 'success');
            loadStations();
        } else {
            showToast(data.error || 'Failed to update role', 'error');
        }
    } catch (error) {
        console.error('Error updating role:', error);
        showToast('Error updating role', 'error');
    }
}

function renderNodeServices(node) {
    const container = document.getElementById('node-services-grid');

    const services = [
        {
            id: 'ollama',
            name: 'Ollama',
            icon: '🦙',
            available: node.ollama_available,
            status: node.ollama_available ? 'Online' : 'Not detected'
        },
        {
            id: 'foocus',
            name: 'Foocus',
            icon: '🎨',
            available: node.foocus_available,
            status: node.foocus_available ? 'Online' : 'Not detected'
        },
        {
            id: 'comfyui',
            name: 'ComfyUI',
            icon: '🔗',
            available: node.comfyui_available,
            status: node.comfyui_available ? 'Online' : 'Not detected'
        },
        {
            id: 'auto1111',
            name: 'Auto1111',
            icon: '🖼️',
            available: node.auto1111_available,
            status: node.auto1111_available ? 'Online' : 'Not detected'
        },
        {
            id: 'docker',
            name: 'Docker',
            icon: '🐳',
            available: node.docker_available,
            status: node.docker_available
                ? `v${node.docker_version || '?'}${node.nvidia_docker ? ' + NVIDIA' : ''}`
                : 'Not installed'
        },
        {
            id: 'wsl',
            name: 'WSL',
            icon: '🪟',
            available: node.wsl_available,
            status: node.wsl_available ? 'Available' : 'N/A'
        }
    ];

    container.innerHTML = services.map(svc => `
        <div class="service-card ${svc.available ? 'online' : 'offline'}">
            <div class="service-icon ${svc.id}">
                ${svc.icon}
            </div>
            <div class="service-info">
                <div class="service-name">${svc.name}</div>
                <div class="service-status">${svc.status}</div>
            </div>
        </div>
    `).join('');
}

function renderNodeModels(capabilities, models) {
    const container = document.getElementById('node-models-list');

    // Merge capabilities and live models
    const allModels = new Map();

    // Add from capabilities (database)
    capabilities.forEach(cap => {
        allModels.set(cap.model_name, {
            name: cap.model_name,
            provider: cap.provider,
            available: cap.is_available,
            tokens_per_sec: cap.avg_tokens_per_sec
        });
    });

    // Add from live models (Ollama)
    if (models && models.length > 0) {
        models.forEach(m => {
            if (!allModels.has(m.name)) {
                allModels.set(m.name, {
                    name: m.name,
                    provider: 'ollama',
                    available: true,
                    size: m.size
                });
            }
        });
    }

    if (allModels.size === 0) {
        container.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1;">
                <i data-lucide="box"></i>
                <p>No models detected</p>
                <p style="font-size:0.7rem;">Make sure Ollama is running on this node</p>
            </div>
        `;
        return;
    }

    container.innerHTML = Array.from(allModels.values()).map(model => `
        <div class="model-card ${model.available ? 'available' : 'unavailable'}">
            <div class="model-icon">
                <i data-lucide="box"></i>
            </div>
            <div class="model-info">
                <div class="model-name">${escapeHtml(model.name)}</div>
                <div class="model-provider">${model.provider}${model.tokens_per_sec ? ` · ${model.tokens_per_sec.toFixed(1)} t/s` : ''}</div>
            </div>
        </div>
    `).join('');
}

function renderNodeHealth(heartbeats) {
    const tableContainer = document.getElementById('node-health-table');

    if (!heartbeats || heartbeats.length === 0) {
        tableContainer.innerHTML = `
            <div class="empty-state">
                <i data-lucide="activity"></i>
                <p>No health data available</p>
            </div>
        `;
        return;
    }

    // Create health chart
    const canvas = document.getElementById('health-chart');
    const ctx = canvas.getContext('2d');

    if (healthChart) {
        healthChart.destroy();
    }

    const labels = heartbeats.slice(0, 20).reverse().map((h, i) => i + 1);
    const cpuData = heartbeats.slice(0, 20).reverse().map(h => h.cpu_usage || 0);
    const memData = heartbeats.slice(0, 20).reverse().map(h => h.memory_usage || 0);
    const gpuData = heartbeats.slice(0, 20).reverse().map(h => h.gpu_usage || 0);

    healthChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'CPU %',
                    data: cpuData,
                    borderColor: '#00FFFF',
                    backgroundColor: 'rgba(0, 255, 255, 0.1)',
                    fill: true,
                    tension: 0.4
                },
                {
                    label: 'Memory %',
                    data: memData,
                    borderColor: '#8B5CF6',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    fill: true,
                    tension: 0.4
                },
                {
                    label: 'GPU %',
                    data: gpuData,
                    borderColor: '#10B981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: '#9ca3af', font: { size: 10 } }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#6e7681' }
                },
                y: {
                    min: 0,
                    max: 100,
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: '#6e7681' }
                }
            }
        }
    });

    // Create table
    tableContainer.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Status</th>
                    <th>CPU</th>
                    <th>Memory</th>
                    <th>GPU</th>
                    <th>Load</th>
                    <th>Latency</th>
                </tr>
            </thead>
            <tbody>
                ${heartbeats.slice(0, 10).map(h => `
                    <tr>
                        <td>${formatTimeAgo(h.created_at)}</td>
                        <td><span style="color:${h.status === 'online' ? 'var(--archie-success)' : 'var(--archie-text-muted)'}">${h.status}</span></td>
                        <td>${h.cpu_usage ? h.cpu_usage.toFixed(1) + '%' : '--'}</td>
                        <td>${h.memory_usage ? h.memory_usage.toFixed(1) + '%' : '--'}</td>
                        <td>${h.gpu_usage ? h.gpu_usage.toFixed(1) + '%' : '--'}</td>
                        <td>${h.current_load || 0}</td>
                        <td>${h.latency_ms ? h.latency_ms + 'ms' : '--'}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

async function loadStationsForAssignment() {
    try {
        const response = await fetch('/tools/bridge/api/stations');
        const data = await response.json();

        if (data.success) {
            const select = document.getElementById('nd-station-select');
            select.innerHTML = data.stations.map(s =>
                `<option value="${s.id}">${escapeHtml(s.name)} (${s.code})</option>`
            ).join('');
        }
    } catch (error) {
        console.error('Error loading stations:', error);
    }
}

function showAddStationToNode() {
    document.getElementById('add-station-form').style.display = 'block';
}

function hideAddStationToNode() {
    document.getElementById('add-station-form').style.display = 'none';
}

async function assignNodeToStationFromDetail() {
    const stationId = document.getElementById('nd-station-select').value;
    const role = document.getElementById('nd-role-select').value;
    const priority = document.getElementById('nd-priority-input').value;

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}/stations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                station_id: parseInt(stationId),
                role: role,
                priority: parseInt(priority)
            })
        });

        const data = await response.json();

        if (data.success) {
            showToast('Node assigned to station', 'success');
            hideAddStationToNode();
            // Refresh the node details
            showNodeDetail(currentNodeId);
            // Refresh stations in main view
            loadStations();
        } else {
            showToast(data.error || 'Failed to assign', 'error');
        }
    } catch (error) {
        console.error('Error assigning node:', error);
        showToast('Error assigning node', 'error');
    }
}

async function removeNodeFromStation(stationId) {
    if (!confirm('Remove this node from the station?')) return;

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}/stations/${stationId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast('Node removed from station', 'success');
            showNodeDetail(currentNodeId);
            loadStations();
        } else {
            showToast(data.error || 'Failed to remove', 'error');
        }
    } catch (error) {
        console.error('Error removing node:', error);
        showToast('Error removing node', 'error');
    }
}

async function syncNodeModels(event) {
    const btn = event.target.closest('button');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader"></i> Syncing...';

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}/models/sync`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.success) {
            showToast(`Synced ${data.models_count} models`, 'success');
            showNodeDetail(currentNodeId);
        } else {
            showToast(data.error || 'Failed to sync', 'error');
        }
    } catch (error) {
        console.error('Error syncing models:', error);
        showToast('Error syncing models', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="refresh-cw"></i> Sync';
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

async function saveNodeConfig() {
    const config = {
        node_name: document.getElementById('nd-config-name').value,
        description: document.getElementById('nd-config-desc').value,
        max_concurrent: parseInt(document.getElementById('nd-config-max').value),
        priority: parseInt(document.getElementById('nd-config-priority').value),
        weight: parseInt(document.getElementById('nd-config-weight').value)
    };

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.success) {
            showToast('Node configuration saved', 'success');
            document.getElementById('node-detail-title').textContent = config.node_name;
            loadNodes();
        } else {
            showToast(data.error || 'Failed to save', 'error');
        }
    } catch (error) {
        console.error('Error saving config:', error);
        showToast('Error saving configuration', 'error');
    }

    // Handle bridge toggle separately
    const bridgeEnabled = document.getElementById('nd-config-bridge').checked;
    if (currentNodeData && currentNodeData.node.bridge_enabled !== bridgeEnabled) {
        toggleBridgeSharing(currentNodeId, bridgeEnabled);
    }
}

async function confirmDeleteNode() {
    const nodeName = currentNodeData?.node?.node_name || currentNodeId;

    if (!confirm(`Are you sure you want to delete node "${nodeName}"?\n\nThis will remove all station assignments and history.`)) {
        return;
    }

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${currentNodeId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast('Node deleted', 'success');
            closeNodeDetailModal();
            loadNodes();
            loadStations();
        } else {
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (error) {
        console.error('Error deleting node:', error);
        showToast('Error deleting node', 'error');
    }
}

// Toggle Bridge LLM sharing for a node (Phase 72)
async function toggleBridgeSharing(nodeId, enabled) {
    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/bridge-sharing`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled, priority: 50 })
        });
        const data = await response.json();

        if (data.success) {
            showToast(`Bridge LLM ${enabled ? 'enabled' : 'disabled'}`, 'success');
            // Update the label color
            const label = document.querySelector(`#bridge-${nodeId}`).closest('.bridge-toggle').querySelector('.bridge-toggle-label');
            if (enabled) {
                label.classList.add('enabled');
            } else {
                label.classList.remove('enabled');
            }
            // Refresh model availability
            loadModelAvailability();
        } else {
            showToast(`Failed: ${data.error}`, 'error');
            // Revert checkbox
            document.getElementById(`bridge-${nodeId}`).checked = !enabled;
        }
    } catch (error) {
        console.error('Error toggling bridge sharing:', error);
        showToast('Error updating bridge sharing', 'error');
        document.getElementById(`bridge-${nodeId}`).checked = !enabled;
    }
}

// Load and display available models across bridge-enabled nodes (Phase 72)
async function loadModelAvailability() {
    try {
        var response = await fetch('/tools/bridge/api/bridge/models');
        var data = await response.json();

        if (data.success) {
            renderLocalModels(data.local_models || []);
            renderRemoteModels(data.all_models || [], data.summary || {});
        }
    } catch (error) {
        console.error('Error loading model availability:', error);
    }
}

function renderLocalModels(models) {
    var grid = document.getElementById('local-models-grid');
    var countEl = document.getElementById('local-model-count');
    if (!grid) return;

    if (countEl) countEl.textContent = models.length + ' model' + (models.length !== 1 ? 's' : '');

    if (models.length === 0) {
        grid.innerHTML = '<div style="color: var(--archie-text-muted); font-size: 0.8rem; grid-column: 1/-1; text-align: center; padding: 2rem;">Local Ollama not reachable or no models installed.</div>';
        return;
    }

    grid.innerHTML = models.map(function(m) {
        return '<div class="model-card">' +
            '<div class="model-name">' + escapeHtml(m.name) + '</div>' +
            '<div class="model-meta">' +
                (m.family ? '<span class="tag">' + escapeHtml(m.family) + '</span>' : '') +
                (m.parameter_size ? '<span class="tag">' + escapeHtml(m.parameter_size) + '</span>' : '') +
                (m.size_gb ? '<span class="requests">' + m.size_gb + ' GB</span>' : '') +
            '</div>' +
        '</div>';
    }).join('');
}

function renderRemoteModels(allModels, summary) {
    var grid = document.getElementById('remote-models-grid');
    var statsEl = document.getElementById('remote-model-stats');
    if (!grid) return;

    if (statsEl) {
        statsEl.innerHTML = '<span>' + (summary.total_models || 0) + '</span> models &middot; <span>' + (summary.total_nodes || 0) + '</span> nodes';
    }

    if (allModels.length === 0) {
        grid.innerHTML = '<div style="color: var(--archie-text-muted); font-size: 0.8rem; grid-column: 1/-1; text-align: center; padding: 2rem;">No remote node models registered. Enable Bridge LLM on nodes with Ollama.</div>';
        return;
    }

    grid.innerHTML = allModels.map(function(m) {
        var disabled = !m.is_available;
        var checkAttr = m.is_available ? ' checked' : '';
        return '<div class="model-card' + (disabled ? ' disabled' : '') + '">' +
            '<div class="model-name">' + escapeHtml(m.model_name) + '</div>' +
            '<div class="model-meta">' +
                (m.model_family ? '<span class="tag">' + escapeHtml(m.model_family) + '</span>' : '') +
                (m.parameter_size ? '<span class="tag">' + escapeHtml(m.parameter_size) + '</span>' : '') +
                '<span class="nodes">' + escapeHtml(m.node_name) + '</span>' +
                (m.total_requests > 0 ? '<span class="requests">' + m.total_requests + ' req</span>' : '') +
            '</div>' +
            '<div class="model-toggle">' +
                '<span>' + (m.is_available ? 'Enabled' : 'Disabled') + '</span>' +
                '<label class="toggle-switch">' +
                    '<input type="checkbox"' + checkAttr +
                        ' onchange="toggleModelAvailability(\'' + escapeHtml(m.node_id) + '\',' + m.id + ',this.checked)">' +
                    '<span class="toggle-slider"></span>' +
                '</label>' +
            '</div>' +
        '</div>';
    }).join('');
}

async function toggleModelAvailability(nodeId, modelId, enabled) {
    try {
        var response = await fetch('/tools/bridge/api/nodes/' + nodeId + '/models/' + modelId + '/toggle', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        var data = await response.json();
        if (data.success) {
            showToast('Model ' + escapeHtml(data.model_name) + ' ' + (enabled ? 'enabled' : 'disabled'), 'success');
            loadModelAvailability();
        } else {
            showToast('Failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error toggling model:', error);
        showToast('Error toggling model', 'error');
    }
}

function showAddNodeModal() {
    const modal = document.createElement('div');
    modal.className = 'node-modal-overlay active';
    modal.innerHTML = `
        <div class="node-modal" style="max-width: 600px;">
            <h2><i data-lucide="plus-circle"></i> Add New Node</h2>

            <div style="margin-bottom: 1.5rem;">
                <h3 style="color: var(--archie-success); font-size: 0.9rem; margin-bottom: 0.5rem;">
                    <i data-lucide="terminal" style="width: 16px; height: 16px; display: inline;"></i> Linux / macOS
                </h3>
                <p style="font-size: 0.8rem; color: var(--archie-text-muted); margin-bottom: 0.5rem;">
                    Run this command on the target machine:
                </p>
                <code style="font-size: 0.7rem;">curl -sSL http://192.168.1.200:3000/tools/bridge/api/nodes/install.sh | sudo bash</code>
            </div>

            <div style="margin-bottom: 1.5rem;">
                <h3 style="color: #58a6ff; font-size: 0.9rem; margin-bottom: 0.5rem;">
                    <i data-lucide="monitor" style="width: 16px; height: 16px; display: inline;"></i> Windows (PowerShell Admin)
                </h3>
                <p style="font-size: 0.8rem; color: var(--archie-text-muted); margin-bottom: 0.5rem;">
                    Run in PowerShell as Administrator:
                </p>
                <code style="font-size: 0.7rem;">iwr -useb http://192.168.1.200:3000/tools/bridge/api/nodes/install.ps1 | iex</code>
            </div>

            <p style="color: var(--archie-text-muted); font-size: 0.75rem; margin-top: 1rem; padding: 0.75rem; background: rgba(0,255,255,0.05); border-radius: 4px;">
                <i data-lucide="info" style="width: 14px; height: 14px; display: inline;"></i>
                The installer will collect system info (CPU, RAM, GPU, Ollama models) and register the node.
                It will appear in "Pending Approval" for you to approve.
            </p>

            <hr>
            <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 1rem;">
                <button onclick="this.closest('.node-modal-overlay').remove()"
                        style="padding: 8px 16px; background: var(--archie-border-default); border: none; color: var(--archie-text-secondary); border-radius: 4px; cursor: pointer;">
                    Close
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // Close on overlay click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escHtml(s) {
    if (typeof s !== 'string') s = String(s == null ? '' : s);
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showToast(message, type = 'info') {
    // Simple toast notification
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 4px;
        color: #fff;
        font-size: 0.85rem;
        z-index: 9999;
        animation: fadeIn 0.3s ease;
        background: ${type === 'success' ? 'var(--archie-success)' : type === 'error' ? 'var(--archie-danger)' : type === 'warning' ? 'var(--archie-warning)' : 'var(--archie-cyan)'};
    `;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ============================================================================
// STATION ASSIGNMENTS MANAGEMENT
// ============================================================================

let currentStationId = null;
let currentAssignmentId = null;
let availableNodes = [];


async function showStationDetail(stationId, stationName) {
    currentStationId = stationId;

    try {
        const response = await fetch(`/tools/bridge/api/stations/${stationId}/nodes`);
        const data = await response.json();

        if (data.success) {
            document.getElementById('station-detail-title').textContent = `${stationName} - Assigned Nodes`;

            const body = document.getElementById('station-detail-body');

            if (data.nodes.length === 0) {
                body.innerHTML = `
                    <div style="text-align:center;padding:2rem;color:var(--archie-text-muted);">
                        <i data-lucide="inbox" style="width:48px;height:48px;margin-bottom:1rem;"></i>
                        <p>No nodes assigned to this station</p>
                    </div>
                `;
            } else {
                body.innerHTML = `
                    <table style="width:100%;font-size:0.8rem;border-collapse:collapse;">
                        <thead>
                            <tr style="border-bottom:1px solid var(--archie-border-default);text-align:left;">
                                <th style="padding:8px;">Node</th>
                                <th style="padding:8px;">Role</th>
                                <th style="padding:8px;">Priority</th>
                                <th style="padding:8px;">Status</th>
                                <th style="padding:8px;">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.nodes.map(node => `
                                <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
                                    <td style="padding:8px;">
                                        <strong>${escapeHtml(node.node_name)}</strong>
                                        <div style="font-size:0.7rem;color:var(--archie-text-muted);">${node.hostname || ''}</div>
                                    </td>
                                    <td style="padding:8px;">
                                        <span class="role-badge ${node.role}" style="padding:2px 8px;border-radius:4px;">${node.role}</span>
                                    </td>
                                    <td style="padding:8px;">${node.priority}</td>
                                    <td style="padding:8px;">
                                        <span style="color:${node.status === 'online' ? 'var(--archie-success)' : 'var(--archie-text-muted)'};">
                                            ${node.status}
                                        </span>
                                    </td>
                                    <td style="padding:8px;">
                                        <button onclick="editAssignment('${node.node_id}', ${stationId})" style="padding:4px 8px;font-size:0.7rem;background:rgba(139,92,246,0.2);border:1px solid rgba(139,92,246,0.3);color:#fff;border-radius:3px;cursor:pointer;margin-right:4px;">Edit</button>
                                        <button onclick="removeAssignment('${node.node_id}', ${stationId})" style="padding:4px 8px;font-size:0.7rem;background:rgba(239,68,68,0.2);border:1px solid rgba(239,68,68,0.3);color:#fff;border-radius:3px;cursor:pointer;">Remove</button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                `;
            }

            document.getElementById('station-detail-modal').classList.add('active');

            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
    } catch (error) {
        console.error('Error loading station detail:', error);
        showToast('Error loading station details', 'error');
    }
}

function closeStationDetailModal() {
    document.getElementById('station-detail-modal').classList.remove('active');
}

function openAssignModalForStation() {
    closeStationDetailModal();
    if (currentStationId) {
        openAssignModal(currentStationId);
    }
}

async function openAssignModal(stationId, stationName = null) {
    currentStationId = stationId;
    currentAssignmentId = null;

    document.getElementById('assignment-modal-title').textContent = stationName
        ? `Assign Node to ${stationName}`
        : 'Assign Node to Station';

    // Load available nodes
    try {
        const response = await fetch('/tools/bridge/api/nodes');
        const data = await response.json();

        if (data.success) {
            availableNodes = data.nodes.filter(n => n.approval_status === 'approved');

            const nodeSelect = document.getElementById('assignment-node-select');
            nodeSelect.innerHTML = '<option value="">Select a node...</option>' +
                availableNodes.map(n => `<option value="${n.node_id}">${escapeHtml(n.node_name)} (${n.status})</option>`).join('');
        }
    } catch (error) {
        console.error('Error loading nodes:', error);
    }

    // Set station select
    const stationSelect = document.getElementById('assignment-station-select');
    stationSelect.innerHTML = `<option value="${stationId}">${stationName || 'Station #' + stationId}</option>`;
    stationSelect.value = stationId;

    // Reset other fields
    document.getElementById('assignment-role-select').value = 'worker';
    document.getElementById('assignment-priority').value = '10';
    document.getElementById('assignment-shift-select').value = 'any';

    // Hide delete button for new assignments
    document.getElementById('assignment-delete-btn').style.display = 'none';
    document.getElementById('assignment-submit-btn').textContent = 'Assign';

    document.getElementById('assignment-modal').classList.add('active');
}

async function editAssignment(nodeId, stationId) {
    currentStationId = stationId;

    // Get node's current assignments
    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/stations`);
        const data = await response.json();

        if (data.success) {
            const assignment = data.assignments.find(a => a.station_id === stationId);

            if (assignment) {
                currentAssignmentId = assignment.assignment_id;

                document.getElementById('assignment-modal-title').textContent = `Edit Assignment: ${data.node_name}`;

                // Set node (disabled for editing)
                const nodeSelect = document.getElementById('assignment-node-select');
                nodeSelect.innerHTML = `<option value="${nodeId}">${escapeHtml(data.node_name)}</option>`;
                nodeSelect.value = nodeId;
                nodeSelect.disabled = true;

                // Set station
                const stationSelect = document.getElementById('assignment-station-select');
                stationSelect.innerHTML = `<option value="${stationId}">${assignment.station_name}</option>`;
                stationSelect.value = stationId;

                // Set current values
                document.getElementById('assignment-role-select').value = assignment.role;
                document.getElementById('assignment-priority').value = assignment.priority;
                document.getElementById('assignment-shift-select').value = assignment.shift_preference;

                // Show delete button
                document.getElementById('assignment-delete-btn').style.display = 'block';
                document.getElementById('assignment-submit-btn').textContent = 'Update';

                document.getElementById('assignment-modal').classList.add('active');
            }
        }
    } catch (error) {
        console.error('Error loading assignment:', error);
        showToast('Error loading assignment', 'error');
    }
}

function closeAssignmentModal() {
    document.getElementById('assignment-modal').classList.remove('active');
    document.getElementById('assignment-node-select').disabled = false;
    currentAssignmentId = null;
}

async function submitAssignment() {
    const nodeId = document.getElementById('assignment-node-select').value;
    const stationId = document.getElementById('assignment-station-select').value;
    const role = document.getElementById('assignment-role-select').value;
    const priority = parseInt(document.getElementById('assignment-priority').value) || 10;
    const shiftPreference = document.getElementById('assignment-shift-select').value;

    if (!nodeId || !stationId) {
        showToast('Please select a node and station', 'warning');
        return;
    }

    const isEdit = currentAssignmentId !== null;
    const url = isEdit
        ? `/tools/bridge/api/nodes/${nodeId}/stations/${stationId}`
        : `/tools/bridge/api/nodes/${nodeId}/stations`;

    try {
        const response = await fetch(url, {
            method: isEdit ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                station_id: parseInt(stationId),
                role: role,
                priority: priority,
                shift_preference: shiftPreference
            })
        });

        const data = await response.json();

        if (data.success) {
            showToast(data.message || (isEdit ? 'Assignment updated!' : 'Node assigned!'), 'success');
            closeAssignmentModal();
            loadStations(); // Refresh stations to show updated node assignments
        } else {
            showToast(data.error || 'Failed to save assignment', 'error');
        }
    } catch (error) {
        console.error('Error saving assignment:', error);
        showToast('Error saving assignment', 'error');
    }
}

async function deleteAssignment() {
    const nodeId = document.getElementById('assignment-node-select').value;
    const stationId = document.getElementById('assignment-station-select').value;

    if (!confirm('Remove this node from the station?')) return;

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/stations/${stationId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast(data.message || 'Assignment removed', 'success');
            closeAssignmentModal();
            loadStations(); // Refresh stations to show updated node assignments
        } else {
            showToast(data.error || 'Failed to remove assignment', 'error');
        }
    } catch (error) {
        console.error('Error removing assignment:', error);
        showToast('Error removing assignment', 'error');
    }
}

async function removeAssignment(nodeId, stationId) {
    if (!confirm('Remove this node from the station?')) return;

    try {
        const response = await fetch(`/tools/bridge/api/nodes/${nodeId}/stations/${stationId}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showToast(data.message || 'Assignment removed', 'success');
            showStationDetail(stationId, document.getElementById('station-detail-title').textContent.split(' - ')[0]);
            loadStations(); // Refresh stations to show updated node assignments
        } else {
            showToast(data.error || 'Failed to remove assignment', 'error');
        }
    } catch (error) {
        console.error('Error removing assignment:', error);
        showToast('Error removing assignment', 'error');
    }
}

function showNodeAssignmentDetail(nodeId, stationId) {
    editAssignment(nodeId, stationId);
}

// ============================================================================
// MESH SUB-SECTIONS (Agent Loans + Learning Patterns)
// ============================================================================

function toggleMeshSection(sectionId) {
    const header = document.getElementById(sectionId + '-header');
    if (header) {
        header.classList.toggle('collapsed');
    }
}

function formatMeshAge(isoStr) {
    return ArchieTime.age(isoStr);
}

// ============================================================================
// MESH DATA LOADING + RENDERING (Tasks 2-6)
// ============================================================================

async function loadMeshLoans() {
    try {
        const response = await fetch('/tools/bridge/api/mesh/agents/loans');
        const data = await response.json();
        if (data.success) renderMeshLoans(data.loans || []);
    } catch (error) { console.error('Error loading mesh loans:', error); }
}

async function loadMeshLearning() {
    try {
        const response = await fetch('/tools/bridge/api/mesh/learning');
        const data = await response.json();
        if (data.success) renderMeshLearning(data.patterns || []);
    } catch (error) { console.error('Error loading mesh learning:', error); }
}

async function loadMeshAvailableAgents() {
    try {
        const response = await fetch('/tools/bridge/api/mesh/agents/available');
        const data = await response.json();
        if (data.success) {
            window._meshAvailableAgents = data.available_agents || [];
            window._meshSummary = data.summary || {};
            updateMeshHeaderStats(data.summary);
        }
    } catch (error) { console.error('Error loading mesh available agents:', error); }
}

function updateMeshHeaderStats(summary) {
    if (!summary) return;
    const loansEl = document.getElementById('mesh-loans-count');
    const availEl = document.getElementById('mesh-available-count');
    if (loansEl && summary.active_loans !== undefined) loansEl.textContent = summary.active_loans;
    if (availEl && summary.total_available !== undefined) availEl.textContent = summary.total_available;
}

function renderMeshLoans(loans) {
    const container = document.getElementById('mesh-loans-container');
    if (!container) return;

    // Update accordion header with active count
    const activeLoans = loans.filter(l => l.status === 'active');
    const subCount = document.getElementById('mesh-loans-sub-count');
    if (subCount) subCount.textContent = activeLoans.length + ' active';

    if (loans.length === 0) {
        container.innerHTML = '<div class="mesh-empty-state">No agent loans recorded. Use Request Help on a node card to borrow an idle agent.</div>';
        return;
    }

    let html = `<table style="width:100%; border-collapse:collapse; font-size:0.8rem;">
        <thead>
            <tr style="border-bottom:1px solid rgba(255,255,255,0.1); color:var(--archie-text-muted);">
                <th style="text-align:left; padding:6px 8px;">Agent</th>
                <th style="text-align:left; padding:6px 8px;">Source → Target</th>
                <th style="text-align:left; padding:6px 8px;">Status</th>
                <th style="text-align:left; padding:6px 8px;">Duration</th>
                <th style="text-align:right; padding:6px 8px;">Actions</th>
            </tr>
        </thead>
        <tbody>`;

    loans.forEach(loan => {
        const statusColor = loan.status === 'active' ? '#00ff41' : (loan.status === 'returned' ? '#888' : '#ffaa00');
        html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:6px 8px; color:#e0e0e0;">${escapeHtml(loan.agent_display_name || loan.agent_name || 'Unknown')}</td>
            <td style="padding:6px 8px; color:var(--archie-text-muted);">${escapeHtml(loan.source_node_name || loan.source_node_id || '?')} → ${escapeHtml(loan.target_node_name || loan.target_node_id || '?')}</td>
            <td style="padding:6px 8px;"><span style="color:${statusColor}; font-weight:600;">${escapeHtml(loan.status || 'unknown')}</span></td>
            <td style="padding:6px 8px; color:var(--archie-text-muted);">${loan.created_at ? formatMeshAge(loan.created_at) : '—'}</td>
            <td style="padding:6px 8px; text-align:right;">
                ${loan.status === 'active' ? '<button onclick="returnMeshAgent(' + loan.id + ')" style="padding:3px 10px; font-size:0.7rem; background:rgba(239,68,68,0.15); color:#ef4444; border:1px solid rgba(239,68,68,0.3); border-radius:3px; cursor:pointer;">Return</button>' : ''}
            </td>
        </tr>`;
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

async function returnMeshAgent(loanId) {
    if (!confirm('Return this agent to their home node?')) return;
    try {
        const response = await fetch('/tools/bridge/api/mesh/agents/return-admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ loan_id: loanId })
        });
        const data = await response.json();
        if (data.success) {
            showToast('Agent returned successfully', 'success');
            loadMeshLoans();
            loadMeshAvailableAgents();
        } else {
            showToast('Failed to return agent: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error returning mesh agent:', error);
        showToast('Error returning agent', 'error');
    }
}

function renderMeshLearning(patterns) {
    const container = document.getElementById('mesh-learnings-container');
    if (!container) return;

    // Update accordion header with count
    const subCount = document.getElementById('mesh-learning-sub-count');
    if (subCount) subCount.textContent = patterns.length + ' patterns';

    // Update header stat
    const countEl = document.getElementById('mesh-learning-count');
    if (countEl) countEl.textContent = patterns.length;

    if (patterns.length === 0) {
        container.innerHTML = '<div class="mesh-empty-state">No learning patterns shared yet.</div>';
        return;
    }

    const typeColors = {
        optimization: '#00ff41',
        error_pattern: '#ef4444',
        performance: '#00e5ff',
        security: '#ffaa00'
    };

    let html = '';
    patterns.forEach(p => {
        const color = typeColors[p.type] || '#888';
        html += `<div style="padding:10px 12px; margin-bottom:6px; background:rgba(255,255,255,0.03); border-radius:6px; border-left:3px solid ${color};">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                <span style="font-size:0.65rem; padding:2px 6px; border-radius:3px; background:${color}22; color:${color}; font-weight:600; text-transform:uppercase;">${escapeHtml(p.type || 'unknown')}</span>
                ${p.category ? '<span style="font-size:0.7rem; color:var(--archie-text-muted);">' + escapeHtml(p.category) + '</span>' : ''}
            </div>
            <div style="font-size:0.8rem; color:#e0e0e0; margin-bottom:4px;">${escapeHtml(p.insight || p.description || 'No details')}</div>
            <div style="display:flex; justify-content:space-between; font-size:0.7rem; color:var(--archie-text-muted);">
                ${p.metric ? '<span>Metric: ' + escapeHtml(String(p.metric)) + '</span>' : '<span></span>'}
                <span>${p.created_at ? formatMeshAge(p.created_at) : ''}</span>
            </div>
        </div>`;
    });
    container.innerHTML = html;
}

function showRequestHelpModal(targetNodeId, targetNodeName, currentLoad, maxConcurrent) {
    const agents = window._meshAvailableAgents || [];
    // Filter out agents from the target node
    const available = agents.filter(a => a.node_id !== targetNodeId);

    // Group agents by node
    const byNode = {};
    available.forEach(a => {
        const nid = a.node_id || 'unknown';
        if (!byNode[nid]) byNode[nid] = { name: a.node_name || nid, agents: [] };
        byNode[nid].agents.push(a);
    });

    let agentsHtml = '';
    if (Object.keys(byNode).length === 0) {
        agentsHtml = '<div class="mesh-empty-state" style="padding:20px; text-align:center; color:var(--archie-text-muted);">No agents available from other nodes right now.</div>';
    } else {
        Object.entries(byNode).forEach(([nid, group]) => {
            agentsHtml += `<div style="margin-bottom:12px;">
                <div style="font-size:0.75rem; color:var(--archie-text-muted); margin-bottom:6px; padding-bottom:4px; border-bottom:1px solid rgba(255,255,255,0.08);">
                    <i data-lucide="server" style="width:12px;height:12px;display:inline;"></i> ${escapeHtml(group.name)}
                </div>`;
            group.agents.forEach(a => {
                const stationBadges = (a.station_codes || []).map(s => '<span style="font-size:0.6rem; padding:1px 4px; background:rgba(0,255,255,0.1); color:#00e5ff; border-radius:2px;">' + escapeHtml(s) + '</span>').join(' ');
                const privacyIcon = a.privacy_level !== 'open' ? ' <i data-lucide="shield" style="width:11px;height:11px;display:inline;color:#ffaa00;" title="Privacy: ' + escapeHtml(a.privacy_level || 'restricted') + '"></i>' : '';
                agentsHtml += `<label style="display:flex; align-items:flex-start; gap:8px; padding:8px; margin:4px 0; background:rgba(255,255,255,0.03); border-radius:4px; cursor:pointer;">
                    <input type="checkbox" class="mesh-agent-cb" value="${a.agent_id}" data-source-node="${escapeHtml(nid)}" style="margin-top:3px;">
                    <div style="flex:1;">
                        <div style="font-size:0.8rem; color:#e0e0e0;">${escapeHtml(a.display_name || a.name)}${privacyIcon}</div>
                        <div style="font-size:0.7rem; color:var(--archie-text-muted);">${escapeHtml(a.title || '')} · ${escapeHtml(a.model || 'unknown')}</div>
                        <div style="margin-top:3px;">${stationBadges}</div>
                    </div>
                </label>`;
            });
            agentsHtml += '</div>';
        });
    }

    const modal = document.createElement('div');
    modal.className = 'node-modal-overlay active';
    modal.innerHTML = `
        <div class="node-modal" style="max-width: 560px;">
            <h2 style="display:flex; align-items:center; gap:8px;">
                <i data-lucide="life-buoy"></i> Request Help
            </h2>
            <div style="margin-bottom:12px; padding:10px; background:rgba(139,92,246,0.1); border-radius:6px; border:1px solid rgba(139,92,246,0.2);">
                <div style="font-size:0.8rem; color:#a78bfa; margin-bottom:4px;">Target: <strong>${escapeHtml(targetNodeName)}</strong></div>
                <div style="font-size:0.75rem; color:var(--archie-text-muted);">Current load: ${currentLoad} / ${maxConcurrent}</div>
            </div>

            <div style="margin-bottom:12px;">
                <label style="font-size:0.75rem; color:var(--archie-text-muted); display:block; margin-bottom:4px;">Available Agents from Other Nodes</label>
                <div style="max-height:280px; overflow-y:auto;" id="mesh-help-agents-list">
                    ${agentsHtml}
                </div>
            </div>

            <div style="margin-bottom:16px;">
                <label style="font-size:0.75rem; color:var(--archie-text-muted); display:block; margin-bottom:4px;">Task Description (optional)</label>
                <textarea id="mesh-help-task-desc" style="width:100%; min-height:60px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:4px; color:#e0e0e0; padding:8px; font-size:0.8rem; resize:vertical;" placeholder="Describe what help is needed..."></textarea>
            </div>

            <div style="display:flex; justify-content:flex-end; gap:10px;">
                <button onclick="this.closest('.node-modal-overlay').remove()"
                        style="padding:8px 16px; background:var(--archie-border-default); border:none; color:var(--archie-text-secondary); border-radius:4px; cursor:pointer;">
                    Cancel
                </button>
                ${Object.keys(byNode).length > 0 ? '<button onclick="submitHelpRequest(\'' + targetNodeId + '\')" style="padding:8px 16px; background:rgba(139,92,246,0.3); border:1px solid rgba(139,92,246,0.4); color:#a78bfa; border-radius:4px; cursor:pointer; font-weight:600;">Send Request</button>' : ''}
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function submitHelpRequest(targetNodeId) {
    const checkboxes = document.querySelectorAll('.mesh-agent-cb:checked');
    if (checkboxes.length === 0) {
        alert('Please select at least one agent.');
        return;
    }

    const taskDesc = (document.getElementById('mesh-help-task-desc') || {}).value || '';
    let successCount = 0;
    let failCount = 0;

    for (const cb of checkboxes) {
        try {
            const response = await fetch('/tools/bridge/api/mesh/agents/lend', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    agent_id: parseInt(cb.value),
                    source_node_id: cb.dataset.sourceNode,
                    target_node_id: targetNodeId,
                    task_description: taskDesc
                })
            });
            const data = await response.json();
            if (data.success) successCount++;
            else failCount++;
        } catch (err) {
            console.error('Error lending agent:', err);
            failCount++;
        }
    }

    // Close modal
    const overlay = document.querySelector('.node-modal-overlay.active');
    if (overlay) overlay.remove();

    // Refresh mesh data
    loadMeshLoans();
    loadMeshAvailableAgents();

    if (failCount === 0) {
        showToast(successCount + ' agent(s) dispatched successfully', 'success');
    } else {
        showToast(successCount + ' dispatched, ' + failCount + ' failed', 'warning');
    }
}

// Load nodes, models, dispatch, and crew on page load (stations loaded separately via main init)
document.addEventListener('DOMContentLoaded', function() {
    loadNodes();
    loadModelAvailability();
    loadDispatchActivity();
    loadCrewManifest();
    loadMeshLoans();
    loadMeshLearning();
    loadMeshAvailableAgents();
    setInterval(loadNodes, 30000);
    setInterval(loadModelAvailability, 60000);
    setInterval(loadDispatchActivity, 15000);
    setInterval(loadCrewManifest, 15000);
    setInterval(loadMeshLoans, 30000);
    setInterval(loadMeshLearning, 60000);
    setInterval(loadMeshAvailableAgents, 30000);
});

// ============================================================================
// DISPATCH ACTIVITY (Project #91 — Phase 6)
// ============================================================================

var _dispatchRefreshTimer = null;

async function loadDispatchActivity() {
    try {
        const resp = await fetch('/tools/bridge/api/bridge/dispatch-overview?limit=20&jobs_limit=10');
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.success) return;

        renderDispatchStats(data.dispatch_stats);
        renderStationActivity(data.station_activity);
        renderDispatchHistory(data.history);
        renderActiveJobs(data.jobs || []);
    } catch (e) {
        // Silently fail — dispatch panel is supplementary
    }
}

function startDispatchRefresh() {
    if (_dispatchRefreshTimer) return;
    loadDispatchActivity();
    _dispatchRefreshTimer = setInterval(loadDispatchActivity, 30000);
}

function stopDispatchRefresh() {
    if (_dispatchRefreshTimer) {
        clearInterval(_dispatchRefreshTimer);
        _dispatchRefreshTimer = null;
    }
}

function formatDuration(ms) {
    if (ms == null) return '--';
    ms = Number(ms);
    if (ms < 1000) return ms + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
    var m = Math.floor(ms / 60000);
    var s = Math.round((ms % 60000) / 1000);
    return m + 'm ' + s + 's';
}

function renderDispatchStats(stats) {
    const totalEl = document.getElementById('dispatch-total');
    const successEl = document.getElementById('dispatch-success');
    const failedEl = document.getElementById('dispatch-failed');
    const avgEl = document.getElementById('dispatch-avg-ms');

    if (totalEl) totalEl.textContent = stats.total_24h || stats.total_1h || '0';
    if (successEl) successEl.textContent = stats.successful_24h || stats.successful_1h || '0';
    if (failedEl) failedEl.textContent = stats.failed_24h || stats.failed_1h || '0';
    if (avgEl) avgEl.textContent = formatDuration(stats.avg_duration_ms);
}

function renderDispatchHistory(history) {
    const container = document.getElementById('dispatch-history-list');
    if (!container) return;

    container.replaceChildren();

    if (!history || history.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'dispatch-empty';
        empty.textContent = _t('bridge.empty.no_dispatches', 'No dispatch activity yet');
        container.appendChild(empty);
        return;
    }

    history.forEach(function(item) {
        const row = document.createElement('div');
        row.className = 'dispatch-history-item' + (item.success === false ? ' failed' : '');
        if (item.station_color) {
            row.style.borderLeftColor = item.station_color;
        }

        const agent = document.createElement('span');
        agent.className = 'dispatch-history-agent';
        agent.textContent = item.agent_name || 'Unknown';

        const module = document.createElement('span');
        module.className = 'dispatch-history-module';
        module.textContent = (item.module || '') + (item.capability ? ' / ' + item.capability : '');

        const duration = document.createElement('span');
        duration.className = 'dispatch-history-duration';
        duration.textContent = formatDuration(item.duration_ms);

        const time = document.createElement('span');
        time.className = 'dispatch-history-time';
        if (item.timestamp) {
            time.textContent = ArchieTime.time(item.timestamp);
        }

        row.appendChild(agent);
        row.appendChild(module);
        row.appendChild(duration);
        row.appendChild(time);
        container.appendChild(row);
    });
}

function renderStationActivity(stations) {
    const container = document.getElementById('dispatch-station-bars');
    if (!container) return;

    container.replaceChildren();

    if (!stations || stations.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'dispatch-empty';
        empty.textContent = _t('bridge.empty.no_station_activity', 'No station activity recorded');
        container.appendChild(empty);
        return;
    }

    const maxCount = Math.max(...stations.map(function(s) { return s.dispatch_count; }), 1);

    stations.forEach(function(station) {
        const bar = document.createElement('div');
        bar.className = 'dispatch-station-bar';

        const label = document.createElement('span');
        label.className = 'dispatch-station-label';
        label.textContent = station.station_name;

        const fillBg = document.createElement('div');
        fillBg.className = 'dispatch-station-fill-bg';

        const fill = document.createElement('div');
        fill.className = 'dispatch-station-fill';
        fill.style.width = Math.round((station.dispatch_count / maxCount) * 100) + '%';
        fill.style.background = station.color || 'var(--archie-cyan)';
        fillBg.appendChild(fill);

        const count = document.createElement('span');
        count.className = 'dispatch-station-count';
        count.textContent = station.dispatch_count;

        bar.appendChild(label);
        bar.appendChild(fillBg);
        bar.appendChild(count);
        container.appendChild(bar);
    });
}

// ============================================================================
// ACTIVE JOBS (Bridge Job Tracking)
// ============================================================================

function renderActiveJobs(jobs) {
    const section = document.getElementById('dispatch-jobs-section');
    const container = document.getElementById('dispatch-jobs-list');
    const countEl = document.getElementById('dispatch-jobs-count');
    if (!section || !container) return;

    // Filter: show running/pending jobs + recently finished (last 2 min)
    const now = Date.now();
    const visible = jobs.filter(function(j) {
        if (j.status === 'running' || j.status === 'pending') return true;
        if (j.completed_at) {
            var age = now - new Date(j.completed_at).getTime();
            return age < 120000; // 2 minutes
        }
        return false;
    });

    if (visible.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    if (countEl) {
        var running = visible.filter(function(j) { return j.status === 'running'; }).length;
        countEl.textContent = running > 0 ? running + ' running' : '';
    }

    container.replaceChildren();

    visible.forEach(function(job) {
        var card = document.createElement('div');
        card.className = 'dispatch-job-card status-' + job.status;

        // Info column (description + agent)
        var info = document.createElement('div');
        info.className = 'dispatch-job-info';

        var desc = document.createElement('div');
        desc.className = 'dispatch-job-desc';
        desc.textContent = job.description || job.job_type;
        desc.title = job.description || '';
        info.appendChild(desc);

        var agent = document.createElement('div');
        agent.className = 'dispatch-job-agent';
        agent.textContent = job.agent_name || (job.status === 'pending' ? '(queued)' : '—');
        info.appendChild(agent);

        // Step counter
        var steps = document.createElement('div');
        steps.className = 'dispatch-job-steps';
        var stepText = job.completed_steps + '/' + job.total_steps;
        if (job.failed_steps > 0 && job.status !== 'running') {
            stepText += ' (' + job.failed_steps + ' failed)';
        }
        steps.textContent = stepText;

        // Progress bar
        var progress = document.createElement('div');
        progress.className = 'dispatch-job-progress';

        var barBg = document.createElement('div');
        barBg.className = 'dispatch-job-bar';

        var barFill = document.createElement('div');
        barFill.className = 'dispatch-job-bar-fill';
        barFill.style.width = Math.min(job.progress_pct, 100) + '%';
        barBg.appendChild(barFill);

        var pct = document.createElement('span');
        pct.className = 'dispatch-job-pct';
        pct.textContent = Math.round(job.progress_pct) + '%';

        progress.appendChild(barBg);
        progress.appendChild(pct);

        // ETA
        var eta = document.createElement('div');
        eta.className = 'dispatch-job-eta';
        if (job.status === 'running' && job.eta_seconds) {
            eta.textContent = formatEta(job.eta_seconds);
        } else if (job.status === 'completed') {
            eta.textContent = 'done';
        } else if (job.status === 'failed') {
            eta.textContent = 'FAILED';
            eta.style.color = 'var(--archie-danger)';
        } else if (job.status === 'cancelled') {
            eta.textContent = 'cancelled';
            eta.style.color = 'var(--archie-text-muted)';
        } else {
            eta.textContent = '--';
        }

        card.appendChild(info);
        card.appendChild(steps);
        card.appendChild(progress);
        card.appendChild(eta);
        container.appendChild(card);
    });
}

function formatEta(seconds) {
    if (!seconds || seconds <= 0) return '--';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.round(seconds / 60) + 'm';
    var h = Math.floor(seconds / 3600);
    var m = Math.round((seconds % 3600) / 60);
    return h + 'h ' + m + 'm';
}

// ============================================================================
// CREW SUB-TAB SWITCHING
// ============================================================================

function switchCrewSubtab(name) {
    document.querySelectorAll('.crew-subtab').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.subtab === name);
    });
    document.querySelectorAll('.crew-subpanel').forEach(function(panel) {
        panel.classList.toggle('active', panel.dataset.subpanel === name);
    });
    if (name === 'contractors') loadContractors();
    if (name === 'leaderboard') loadLeaderboard();
    if (name === 'training') loadTrainingTab();
    if (name === 'lounge') loadLoungeTab();
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// ============================================================================
// LEADERBOARD
// ============================================================================

async function loadLeaderboard() {
    var container = document.getElementById('leaderboard-container');
    if (!container) return;
    container.textContent = '';
    var loading = document.createElement('span');
    loading.className = 'briefing-muted';
    loading.textContent = 'Loading leaderboard...';
    container.appendChild(loading);

    try {
        var resp = await fetch('/tools/bridge/api/agents/performance/leaderboard?limit=10');
        var data = await resp.json();
        container.textContent = '';

        if (!data.success || !data.leaderboard || data.leaderboard.length === 0) {
            var empty = document.createElement('span');
            empty.className = 'briefing-muted';
            empty.textContent = 'No performance data available yet.';
            container.appendChild(empty);
            return;
        }

        var list = document.createElement('div');
        list.style.cssText = 'display:flex;flex-direction:column;gap:6px;';

        data.leaderboard.forEach(function(entry, idx) {
            var rank = idx + 1;
            var row = document.createElement('div');
            var accentRgb = rank === 1 ? '251,191,36' : rank === 2 ? '192,192,192' : rank === 3 ? '205,127,50' : '0,255,255';
            row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(255,255,255,0.03);border:1px solid rgba(' + accentRgb + ',0.12);border-left:3px solid rgba(' + accentRgb + ',0.4);border-radius:2px 8px 8px 2px;font-size:0.75rem;position:relative;';

            // Medal / rank
            var medal = document.createElement('span');
            medal.style.cssText = 'width:24px;text-align:center;font-size:0.85rem;';
            if (rank === 1) { medal.textContent = '\u2B50'; medal.title = 'Gold'; }
            else if (rank === 2) { medal.textContent = '\uD83E\uDD48'; medal.title = 'Silver'; medal.style.fontSize = '0.85rem'; }
            else if (rank === 3) { medal.textContent = '\uD83E\uDD49'; medal.title = 'Bronze'; medal.style.fontSize = '0.85rem'; }
            else { medal.textContent = '#' + rank; medal.style.color = 'var(--archie-text-muted)'; medal.style.fontSize = '0.7rem'; }
            row.appendChild(medal);

            // Agent name
            var name = document.createElement('span');
            name.style.cssText = 'flex:1;font-weight:600;color:var(--archie-text-primary);';
            name.textContent = (entry.first_name || '') + ' ' + (entry.last_name || entry.agent_name || '');
            row.appendChild(name);

            // Tasks completed
            var tasks = document.createElement('span');
            tasks.style.cssText = 'color:var(--archie-cyan);font-size:0.7rem;min-width:50px;text-align:right;';
            tasks.textContent = (parseInt(entry.total_tasks_completed) || 0) + ' tasks';
            row.appendChild(tasks);

            // Success rate
            var rate = document.createElement('span');
            var sr = parseFloat(entry.success_rate) || 0;
            var pct = sr <= 1 ? sr * 100 : sr;
            var rateColor = pct >= 90 ? '#00ff41' : pct >= 70 ? '#ffaa00' : '#ff4444';
            rate.style.cssText = 'min-width:45px;text-align:right;font-size:0.7rem;color:' + rateColor + ';';
            rate.textContent = pct.toFixed(0) + '%';
            row.appendChild(rate);

            // Score
            var score = document.createElement('span');
            score.style.cssText = 'min-width:40px;text-align:right;font-size:0.7rem;color:var(--archie-gold);font-weight:600;';
            score.textContent = parseFloat(entry.performance_score || entry.score || 0).toFixed(1);
            row.appendChild(score);

            list.appendChild(row);
        });

        container.appendChild(list);
    } catch (e) {
        container.textContent = '';
        var err = document.createElement('span');
        err.className = 'briefing-muted';
        err.textContent = 'No performance data available yet.';
        container.appendChild(err);
    }
}

// ============================================================================
// CREW MANIFEST (Phase B)
// ============================================================================

var _crewWorkloadMap = {};
var _crewRefreshTimer = null;

async function loadCrewManifest() {
    try {
        const crewResp = await fetch('/tools/bridge/api/bridge/crew/manifest');
        if (!crewResp.ok) return;
        const data = await crewResp.json();
        // Build workload lookup from merged response
        _crewWorkloadMap = {};
        if (data.success) {
            (data.crew || []).forEach(function(a) {
                if (a.workload) _crewWorkloadMap[a.agent_id || a.id] = a.workload;
            });
            window._lastFleetMode = data.fleet_mode || 'workday';
            // Update fleet overview bar
            if (data.fleet_overview) {
                var fo = data.fleet_overview;
                document.getElementById('fleet-active').textContent = fo.active || 0;
                var deployedEl = document.getElementById('fleet-deployed');
                if (deployedEl) deployedEl.textContent = fo.deployed || 0;
                document.getElementById('fleet-winding').textContent = fo.winding_down || 0;
                document.getElementById('fleet-cooldown').textContent = fo.cooldown || 0;
                document.getElementById('fleet-reserves').textContent = fo.reserves || 0;
            }
            renderCrewManifest(data.crew || [], data.capacity || null, data.node_capacities || []);
            if (data.fleet_mode) updateFleetModeButton(data.fleet_mode);
            // Auto-refresh rotation log if expanded
            var rlBody = document.getElementById('rotation-log-body');
            if (rlBody && rlBody.style.display !== 'none') loadRotationLog();
        }
    } catch (e) {
        // Silently fail — crew manifest is supplementary
    }
}

function toggleRotationLog() {
    var body = document.getElementById('rotation-log-body');
    var toggle = document.getElementById('rotation-log-toggle');
    if (body.style.display === 'none') {
        body.style.display = 'block';
        toggle.textContent = '\u25BE';
        loadRotationLog();
    } else {
        body.style.display = 'none';
        toggle.textContent = '\u25B8';
    }
}

function loadRotationLog() {
    fetch('/tools/bridge/api/bridge/rotation-log?limit=20')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var container = document.getElementById('rotation-log-entries');
            container.replaceChildren();
            if (data.events.length === 0) {
                var empty = document.createElement('div');
                empty.className = 'rotation-log-entry';
                empty.textContent = 'No rotation events yet';
                container.appendChild(empty);
                return;
            }
            data.events.forEach(function(e) {
                var entry = document.createElement('div');
                entry.className = 'rotation-log-entry';

                var time = new Date(e.started_at).toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit'});
                var timeSpan = document.createElement('span');
                timeSpan.textContent = time + ' ';
                entry.appendChild(timeSpan);

                var nameEl = document.createElement('strong');
                nameEl.textContent = e.agent_name;
                entry.appendChild(nameEl);

                entry.appendChild(document.createTextNode(' \u2192 '));

                var stateColors = {active:'#32CD32', winding_down:'#FFD700', cooldown:'#FF6347', off_duty:'#666'};
                var stateSpan = document.createElement('span');
                stateSpan.textContent = e.shift_state.toUpperCase();
                stateSpan.style.color = stateColors[e.shift_state] || '#999';
                entry.appendChild(stateSpan);

                var suffix = ' at ' + (e.station_code || '?') + ' (' + (e.reason || 'manual') + ')';
                if (e.replaced_by_name) suffix += ' \u2192 replaced by ' + e.replaced_by_name;
                entry.appendChild(document.createTextNode(suffix));

                container.appendChild(entry);
            });
        })
        .catch(function(err) { console.error('Rotation log error:', err); });
}

function startCrewRefresh() {
    if (_crewRefreshTimer) return;
    loadCrewManifest();
    _crewRefreshTimer = setInterval(loadCrewManifest, 30000);
}

function stopCrewRefresh() {
    if (_crewRefreshTimer) {
        clearInterval(_crewRefreshTimer);
        _crewRefreshTimer = null;
    }
}

var _activeShiftFilter = null;
function filterCrewByState(state) {
    var bar = document.getElementById('fleet-overview-bar');
    var grid = document.getElementById('crew-manifest-grid');
    if (!grid) return;
    // Toggle filter off if clicking same state
    if (_activeShiftFilter === state) {
        _activeShiftFilter = null;
        // Show all cards
        var allCards = grid.querySelectorAll('.crew-agent-card');
        allCards.forEach(function(c) { c.style.display = ''; });
        // Remove selected class from all stats
        if (bar) bar.querySelectorAll('.fleet-stat').forEach(function(s) { s.classList.remove('selected'); });
        return;
    }
    _activeShiftFilter = state;
    // Highlight selected stat
    if (bar) {
        bar.querySelectorAll('.fleet-stat').forEach(function(s) { s.classList.remove('selected'); });
        bar.querySelectorAll('.fleet-stat.' + state.replace('_', '-')).forEach(function(s) { s.classList.add('selected'); });
    }
    // Filter cards
    var cards = grid.querySelectorAll('.crew-agent-card');
    cards.forEach(function(c) {
        var cardState = c.getAttribute('data-shift-state') || 'active';
        c.style.display = (cardState === state) ? '' : 'none';
    });
}

function makeStatSpan(val, label) {
    var span = document.createElement('span');
    var valEl = document.createElement('span');
    valEl.className = 'stat-val';
    valEl.textContent = val;
    span.appendChild(valEl);
    span.appendChild(document.createTextNode(' ' + label));
    return span;
}

function renderCrewManifest(crew, capacity, nodeCapacities) {
    var grid = document.getElementById('crew-manifest-grid');
    var countEl = document.getElementById('crew-manifest-count');
    if (!grid) return;
    // Store crew data for instant profile previews
    window._lastCrewData = crew;
    // Also populate training/lounge selects
    populateTrainingLoungeSelects(crew);

    // --- Hardware capacity bars (GPU + CPU/RAM, insert before grid) ---
    var capBarId = 'roster-capacity-bar';
    var existingCap = document.getElementById(capBarId);
    if (existingCap) existingCap.remove();
    if (capacity) {
        var ram = capacity.ram || {};
        var gpuCap = capacity.gpu || null;
        var cpuModelList = capacity.cpu_models || [];

        var capWrap = document.createElement('div');
        capWrap.id = capBarId;
        capWrap.style.cssText = 'margin-bottom: 6px;';

        // GPU / VRAM section — segmented bar
        if (gpuCap) {
            var gpuBar = document.createElement('div');
            gpuBar.className = 'roster-capacity-bar';
            gpuBar.style.flexWrap = 'wrap';

            var gpuLbl = document.createElement('span');
            gpuLbl.className = 'roster-capacity-label';
            gpuLbl.style.fontWeight = '600';
            gpuLbl.textContent = '\u26A1 GPU';
            gpuBar.appendChild(gpuLbl);

            var vramTotal = gpuCap.vram_total_gb || 8.0;
            var ollamaGpuModels = gpuCap.models || [];
            var ollamaVram = ollamaGpuModels.reduce(function(s, m) { return s + (m.vram_gb || 0); }, 0);
            var comfyVram = gpuCap.comfyui_vram_gb || 0;
            var comfyStatus = gpuCap.comfyui_status || 'idle';
            var comfyReserved = gpuCap.comfyui_reserved_gb || 0;
            // Show real usage when active, reserved estimate when idle
            var comfyDisplay = comfyStatus === 'loaded' ? comfyVram : comfyReserved;
            var comfyIsActive = comfyStatus === 'loaded';
            var gpuFreeVram = Math.max(0, vramTotal - ollamaVram - comfyDisplay);

            var gpuTrack = document.createElement('div');
            gpuTrack.className = 'roster-capacity-track';

            // Segment: Ollama GPU models (green)
            if (ollamaVram > 0) {
                var gSeg1 = document.createElement('div');
                gSeg1.className = 'roster-capacity-seg models';
                gSeg1.style.width = ((ollamaVram / vramTotal) * 100).toFixed(1) + '%';
                gSeg1.title = 'Ollama GPU: ' + ollamaVram.toFixed(1) + 'GB';
                gpuTrack.appendChild(gSeg1);
            }

            // Segment: ComfyUI — solid purple when active, dashed purple when reserved/idle
            if (comfyDisplay > 0) {
                var gSeg2 = document.createElement('div');
                gSeg2.className = 'roster-capacity-seg';
                if (comfyIsActive) {
                    gSeg2.style.background = '#8b5cf6';
                    gSeg2.title = 'ComfyUI SDXL: ' + comfyVram.toFixed(1) + 'GB (generating)';
                } else {
                    gSeg2.style.background = 'rgba(139,92,246,0.2)';
                    gSeg2.style.borderTop = '1px dashed rgba(139,92,246,0.5)';
                    gSeg2.style.borderBottom = '1px dashed rgba(139,92,246,0.5)';
                    gSeg2.title = 'ComfyUI SDXL: ~' + comfyReserved.toFixed(1) + 'GB reserved (on-demand)';
                }
                gSeg2.style.width = ((comfyDisplay / vramTotal) * 100).toFixed(1) + '%';
                gpuTrack.appendChild(gSeg2);
            }

            gpuBar.appendChild(gpuTrack);

            // Compact label
            var gpuPct = document.createElement('span');
            gpuPct.className = 'roster-capacity-label';
            gpuPct.textContent = gpuCap.vram_used_gb + '/' + vramTotal + 'GB';
            gpuBar.appendChild(gpuPct);

            // Legend row
            var gpuLegend = document.createElement('div');
            gpuLegend.className = 'roster-capacity-legend';
            var legendParts = [];
            if (ollamaVram > 0) legendParts.push('<span class="leg-models">' + ollamaVram.toFixed(1) + 'GB Ollama</span>');
            var comfyDot = comfyIsActive ? '#8b5cf6' : 'rgba(139,92,246,0.25)';
            var comfyBorder = comfyIsActive ? '' : 'border:1px dashed rgba(139,92,246,0.5);';
            var comfyLabel = comfyIsActive
                ? comfyVram.toFixed(1) + 'GB active'
                : '~' + comfyReserved.toFixed(1) + 'GB reserved';
            legendParts.push('<span><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + comfyDot + ';margin-right:3px;vertical-align:middle;' + comfyBorder + '"></span>ComfyUI ' + comfyLabel + '</span>');
            legendParts.push('<span style="color:var(--archie-text-muted);">' + gpuFreeVram.toFixed(1) + 'GB free</span>');
            gpuLegend.innerHTML = legendParts.join('');
            gpuBar.appendChild(gpuLegend);

            capWrap.appendChild(gpuBar);

            // --- ComfyUI Checkpoint Control Panel ---
            var comfyPanel = document.createElement('div');
            comfyPanel.className = 'roster-capacity-bar';
            comfyPanel.id = 'comfyui-checkpoint-panel';
            comfyPanel.style.flexWrap = 'wrap';
            comfyPanel.style.borderLeft = '3px solid #8b5cf6';

            var comfyHdr = document.createElement('span');
            comfyHdr.className = 'roster-capacity-label';
            comfyHdr.style.fontWeight = '600';
            comfyHdr.innerHTML = '<span style="color:#8b5cf6;">&#9670;</span> ComfyUI Checkpoints';
            comfyPanel.appendChild(comfyHdr);

            var comfyBody = document.createElement('div');
            comfyBody.id = 'comfyui-checkpoint-body';
            comfyBody.style.cssText = 'width:100%;font-size:12px;color:var(--archie-text-muted);';
            comfyBody.textContent = 'Loading...';
            comfyPanel.appendChild(comfyBody);
            capWrap.appendChild(comfyPanel);

            // Fetch ComfyUI models and populate
            _loadComfyCheckpoints();
        }

        // CPU / RAM section — segmented bar
        var cpuBar = document.createElement('div');
        cpuBar.className = 'roster-capacity-bar';
        cpuBar.style.flexWrap = 'wrap';

        var cpuLbl = document.createElement('span');
        cpuLbl.className = 'roster-capacity-label';
        cpuLbl.style.fontWeight = '600';
        cpuLbl.textContent = '\uD83D\uDCBB RAM';
        cpuBar.appendChild(cpuLbl);

        // Calculate segments as % of total RAM
        var totalGB = ram.total_gb || 1;
        var modelsGB = capacity.models_ram_gb || 0;
        var swapTotal = ram.swap_buffer_gb || 0;
        var agentBudget = ram.agent_budget_gb || 0;
        var swapUsed = Math.max(0, Math.round((modelsGB - agentBudget) * 10) / 10);
        var swapFree = Math.max(0, Math.round((swapTotal - swapUsed) * 10) / 10);
        var reserveGB = ram.reserve_gb || 0;
        var securityGB = ram.security_gb || 0;
        // Models segment = min(modelsGB, agentBudget) — what fits in agent budget
        var modelsSeg = Math.min(modelsGB, agentBudget);

        var cpuTrack = document.createElement('div');
        cpuTrack.className = 'roster-capacity-track';

        // Segment 1: Loaded models (green)
        var seg1 = document.createElement('div');
        seg1.className = 'roster-capacity-seg models';
        seg1.style.width = ((modelsSeg / totalGB) * 100).toFixed(1) + '%';
        seg1.title = 'Loaded models: ' + modelsSeg.toFixed(0) + 'GB';
        cpuTrack.appendChild(seg1);

        // Segment 2: Swap used (solid yellow)
        if (swapUsed > 0) {
            var seg2 = document.createElement('div');
            seg2.className = 'roster-capacity-seg swap-used';
            seg2.style.width = ((swapUsed / totalGB) * 100).toFixed(1) + '%';
            seg2.title = 'Swap used: ' + swapUsed.toFixed(1) + 'GB';
            cpuTrack.appendChild(seg2);
        }

        // Segment 3: Swap free (dashed yellow)
        if (swapFree > 0) {
            var seg3 = document.createElement('div');
            seg3.className = 'roster-capacity-seg swap-free';
            seg3.style.width = ((swapFree / totalGB) * 100).toFixed(1) + '%';
            seg3.title = 'Swap available: ' + swapFree.toFixed(1) + 'GB';
            cpuTrack.appendChild(seg3);
        }

        // Segment 4: Security services (cyan)
        if (securityGB > 0) {
            var seg4 = document.createElement('div');
            seg4.className = 'roster-capacity-seg';
            seg4.style.background = 'rgba(0,212,255,0.3)';
            seg4.style.borderTop = '1px solid rgba(0,212,255,0.5)';
            seg4.style.borderBottom = '1px solid rgba(0,212,255,0.5)';
            seg4.style.width = ((securityGB / totalGB) * 100).toFixed(1) + '%';
            seg4.title = 'Security services: ' + securityGB + 'GB';
            cpuTrack.appendChild(seg4);
        }

        // Segment 5: Host reserve (dashed red)
        if (reserveGB > 0) {
            var seg5 = document.createElement('div');
            seg5.className = 'roster-capacity-seg host-reserve';
            seg5.style.width = ((reserveGB / totalGB) * 100).toFixed(1) + '%';
            seg5.title = 'Host reserve: ' + reserveGB + 'GB';
            cpuTrack.appendChild(seg5);
        }

        cpuBar.appendChild(cpuTrack);

        // Compact size label
        var cpuPct = document.createElement('span');
        cpuPct.className = 'roster-capacity-label';
        cpuPct.textContent = modelsGB.toFixed(0) + '/' + totalGB.toFixed(0) + 'GB';
        cpuBar.appendChild(cpuPct);

        // Color legend (second row) — using existing innerHTML pattern from this file
        var legend = document.createElement('div');
        legend.className = 'roster-capacity-legend';
        legend.innerHTML = '<span class="leg-models">' + modelsSeg.toFixed(0) + 'GB agents</span>'
            + '<span class="leg-swap-used">' + swapUsed.toFixed(1) + 'GB swap</span>'
            + '<span class="leg-swap-free">' + swapFree.toFixed(1) + 'GB swap free</span>'
            + '<span style="color:#00d4ff;">\u25CF ' + securityGB + 'GB security</span>'
            + '<span class="leg-reserve">' + reserveGB + 'GB host</span>';
        cpuBar.appendChild(legend);

        capWrap.appendChild(cpuBar);
        grid.parentNode.insertBefore(capWrap, grid);

        // Gate the Add Agent button based on RAM budget + IAAE policy
        var addBtn = document.getElementById('btn-add-agent');
        if (addBtn) {
            addBtn.classList.remove('amber', 'red');
            addBtn.removeAttribute('title');
            var usableGB = Math.max(0, (ram.available_gb || 0) - reserveGB - securityGB);
            var _capInfo = {
                availableGB: (ram.available_gb || 0).toFixed(1),
                reserveGB: reserveGB,
                modelsGB: modelsGB.toFixed(0),
                usableGB: usableGB.toFixed(1),
                swapUsed: swapUsed.toFixed(1),
                swapTotal: swapTotal,
                swapFree: swapFree.toFixed(1)
            };
            if (ram.status === 'red') {
                addBtn.classList.add('red');
                addBtn.title = 'IAAE Policy: RAM reserve breached';
                addBtn.onclick = function(e) { e.preventDefault(); showIaaeCapacityModal('red', _capInfo); };
            } else if (ram.status === 'amber') {
                addBtn.classList.add('amber');
                addBtn.title = 'Limited capacity \u2014 ' + usableGB.toFixed(1) + 'GB usable';
                addBtn.onclick = function(e) { e.preventDefault(); showIaaeCapacityModal('amber', _capInfo); };
            } else {
                addBtn.onclick = function() { openAgentFormModal(); };
            }
        }
    }

    if (countEl) {
        var working = crew.filter(function(a) { return a.status === 'working'; }).length;
        var idle = crew.filter(function(a) { return a.status === 'idle'; }).length;
        var llmReady = crew.filter(function(a) { return a.llm_status === 'loaded' || a.llm_status === 'cloud'; }).length;
        var llmSwap = crew.filter(function(a) { return a.llm_status === 'swap'; }).length;
        var llmBarracked = crew.filter(function(a) { return a.llm_status === 'barracked'; }).length;
        var summary = crew.length + ' agents \u2014 ' + working + ' working, ' + idle + ' idle | ' + llmReady + ' LLM ready';
        if (llmSwap > 0) summary += ', ' + llmSwap + ' swap';
        if (llmBarracked > 0) summary += ', ' + llmBarracked + ' barracked';
        countEl.textContent = summary;
    }

    grid.replaceChildren();

    if (!crew || crew.length === 0) {
        var empty = document.createElement('div');
        empty.style.cssText = 'color: var(--archie-text-muted); font-size: 0.75rem; grid-column: 1/-1; text-align: center; padding: 2rem;';
        empty.textContent = 'No agents registered';
        grid.appendChild(empty);
        return;
    }

    // Sort within groups: working first, then idle, then resting
    var statusOrder = { working: 0, idle: 1, resting: 2, offline: 3 };
    crew.sort(function(a, b) {
        return (statusOrder[a.status] || 9) - (statusOrder[b.status] || 9);
    });

    // Group by hardware: GPU, CPU, Cloud, SWAP
    // GPU group: agents with LLM on GPU OR agents with GPU tools (ComfyUI)
    var gpuAgents = crew.filter(function(a) {
        var isGpuHw = (a.hardware || '').toUpperCase() === 'GPU';
        var hasGpuTools = a.gpu_tools && a.gpu_tools.length > 0;
        return (isGpuHw || hasGpuTools) && a.llm_status !== 'cloud';
    });
    var gpuIds = new Set(gpuAgents.map(function(a) { return a.agent_id || a.id; }));
    var cpuAgents = crew.filter(function(a) { return !gpuIds.has(a.agent_id || a.id) && (a.hardware || 'CPU').toUpperCase() === 'CPU' && a.llm_status === 'loaded'; });
    var cloudAgents = crew.filter(function(a) { return a.llm_status === 'cloud'; });
    var swapAgents = crew.filter(function(a) { return !gpuIds.has(a.agent_id || a.id) && a.llm_status === 'swap'; });
    var deployedAgents = crew.filter(function(a) { return a.shift_state === 'deployed'; });
    var deployedIds = new Set(deployedAgents.map(function(a) { return a.agent_id || a.id; }));
    var barrackedAgents = crew.filter(function(a) { return a.llm_status === 'barracked' && !deployedIds.has(a.agent_id || a.id); });

    function _addRosterDivider(icon, label, count, cssClass) {
        var div = document.createElement('div');
        div.className = 'roster-hw-divider ' + cssClass;
        var iconEl = document.createElement('span');
        iconEl.className = 'rhd-icon';
        iconEl.textContent = icon;
        div.appendChild(iconEl);
        div.appendChild(document.createTextNode(label));
        var countEl = document.createElement('span');
        countEl.className = 'rhd-count';
        countEl.textContent = '(' + count + ')';
        div.appendChild(countEl);
        grid.appendChild(div);
    }

    function _renderAgentCard(agent) {
        var card = document.createElement('div');
        card.className = 'crew-agent-card';
        card.setAttribute('data-station', agent.station);
        card.style.cursor = 'pointer';
        card.onclick = (function(id) { return function() { openAgentProfile(id); }; })(agent.agent_id);

        // Top row: name + badges
        var top = document.createElement('div');
        top.className = 'crew-agent-top';

        var name = document.createElement('span');
        name.className = 'crew-agent-name';
        name.textContent = agent.full_name || agent.name;
        if (agent.full_name && agent.full_name !== agent.name) {
            name.title = agent.name + (agent.title ? ' \u2014 ' + agent.title : '');
        }

        var badges = document.createElement('div');
        badges.className = 'crew-agent-badges';

        // Wellness dot
        var wellness = agent.wellness || {};
        var stress = wellness.stress || 0;
        var dotClass = stress <= 0.4 ? 'green' : (stress <= 0.7 ? 'yellow' : 'red');
        var dot = document.createElement('span');
        dot.className = 'crew-wellness-dot ' + dotClass;
        dot.title = 'Stress: ' + (stress * 100).toFixed(0) + '% | Energy: ' + ((wellness.energy || 0) * 100).toFixed(0) + '% | ' + (wellness.mood || 'neutral');
        badges.appendChild(dot);

        // Status badge
        var statusBadge = document.createElement('span');
        statusBadge.className = 'crew-status-badge ' + agent.status;
        statusBadge.textContent = agent.status;
        badges.appendChild(statusBadge);

        // LLM readiness badge
        if (agent.llm_status) {
            var llmBadge = document.createElement('span');
            var isResting = agent.status === 'resting';
            var fleetMode = window._lastFleetMode || 'workday';
            var isWeekend = fleetMode === 'weekend';

            if (isResting) {
                // Resting agents — LLM unloaded for break
                llmBadge.className = 'crew-llm-badge resting';
                llmBadge.textContent = '\u263E REST';
                llmBadge.title = 'LLM unloaded \u2014 agent on break (' + (agent.llm_size_gb || '?') + 'GB freed)';
            } else if (isWeekend && agent.llm_status !== 'cloud') {
                // Weekend mode — everything unloaded
                llmBadge.className = 'crew-llm-badge weekend';
                llmBadge.textContent = '\u263E WKE';
                llmBadge.title = 'Weekend mode \u2014 LLM unloaded (' + (agent.llm_size_gb || '?') + 'GB freed)';
            } else {
                llmBadge.className = 'crew-llm-badge ' + agent.llm_status;
                if (agent.llm_status === 'loaded') {
                    llmBadge.textContent = 'LLM \u2713';
                    llmBadge.title = 'Model loaded in RAM (' + (agent.llm_size_gb || 0) + 'GB)';
                } else if (agent.llm_status === 'swap') {
                    llmBadge.textContent = 'SWAP';
                    llmBadge.title = 'Can load on-demand (~' + (agent.llm_size_gb || '?') + 'GB) \u2014 fits in swap buffer';
                } else if (agent.llm_status === 'cloud') {
                    llmBadge.textContent = 'CLOUD';
                    llmBadge.title = 'Cloud model \u2014 no local RAM needed';
                } else if (agent.llm_status === 'barracked') {
                    llmBadge.textContent = 'BARRACKED';
                    llmBadge.title = 'Model too large for swap buffer (~' + (agent.llm_size_gb || '?') + 'GB) \u2014 needs agent budget space';
                }
            }
            badges.appendChild(llmBadge);
        }

        // Load/Unload toggle button
        if (agent.llm_status === 'loaded' || agent.llm_status === 'swap' || agent.llm_status === 'barracked') {
            var toggleBtn = document.createElement('button');
            toggleBtn.className = 'crew-llm-toggle ' + agent.llm_status;
            if (agent.llm_status === 'loaded') {
                toggleBtn.textContent = 'Unload';
                toggleBtn.title = 'Unload ' + (agent.model || '').replace(':latest', '') + ' from memory';
            } else {
                toggleBtn.textContent = 'Load';
                toggleBtn.title = 'Load ' + (agent.model || '').replace(':latest', '') + ' into memory';
            }
            toggleBtn.onclick = (function(ag, btn) {
                return function(e) {
                    e.stopPropagation();
                    _toggleAgentModel(ag, btn);
                };
            })(agent, toggleBtn);
            badges.appendChild(toggleBtn);
        }

        // Performance tags
        var agentStats = agent.stats_24h || {};
        if (agent.llm_status === 'loaded' && (agentStats.dispatches || 0) === 0) {
            var perfTag = document.createElement('span');
            perfTag.className = 'crew-perf-tag underutilized';
            perfTag.textContent = 'UNDERUTILIZED';
            perfTag.title = 'Model loaded but 0 dispatches in 24h';
            badges.appendChild(perfTag);
            card.classList.add('underutilized');
        } else if ((agentStats.dispatches || 0) >= 3 && (agentStats.success_rate || 0) < 0.5) {
            var perfTag2 = document.createElement('span');
            perfTag2.className = 'crew-perf-tag low-success';
            perfTag2.textContent = 'LOW SUCCESS';
            perfTag2.title = 'Success rate below 50% (' + Math.round((agentStats.success_rate || 0) * 100) + '%)';
            badges.appendChild(perfTag2);
        }

        // Shift state badge
        var shiftState = agent.shift_state || 'active';
        card.setAttribute('data-shift-state', shiftState);
        var shiftLabels = {active: 'ON DUTY', winding_down: 'WINDING DOWN', cooldown: 'COOLDOWN', off_duty: 'OFF DUTY'};
        var shiftColors = {active: '#32CD32', winding_down: '#FFD700', cooldown: '#FF6347', off_duty: '#666'};
        var shiftBadge = document.createElement('span');
        shiftBadge.className = 'crew-shift-badge';
        shiftBadge.textContent = shiftLabels[shiftState] || shiftState.toUpperCase();
        shiftBadge.style.color = shiftColors[shiftState] || '#888';
        shiftBadge.style.background = (shiftColors[shiftState] || '#888').replace(')', ',0.15)').replace('rgb', 'rgba').replace('#', '');
        // Use proper rgba background
        var sc = shiftColors[shiftState] || '#888';
        if (sc === '#32CD32') shiftBadge.style.background = 'rgba(50,205,50,0.15)';
        else if (sc === '#FFD700') shiftBadge.style.background = 'rgba(255,215,0,0.15)';
        else if (sc === '#FF6347') shiftBadge.style.background = 'rgba(255,99,71,0.15)';
        else shiftBadge.style.background = 'rgba(102,102,102,0.15)';
        badges.appendChild(shiftBadge);

        top.appendChild(name);
        top.appendChild(badges);
        card.appendChild(top);

        // Callsign + title subtitle
        if (agent.full_name && agent.full_name !== agent.name) {
            var subtitle = document.createElement('div');
            subtitle.style.cssText = 'font-size: 0.6rem; color: var(--archie-text-muted); margin-top: -2px;';
            subtitle.textContent = agent.name + (agent.title ? ' \u2014 ' + agent.title : '');
            card.appendChild(subtitle);
        }

        // Meta row: station + model + hardware
        var meta = document.createElement('div');
        meta.className = 'crew-agent-meta';

        var stationSpan = document.createElement('span');
        stationSpan.textContent = agent.station;
        meta.appendChild(stationSpan);

        var modelSpan = document.createElement('span');
        modelSpan.textContent = (agent.model || '').replace(':latest', '');
        meta.appendChild(modelSpan);

        // For agents with GPU tools: show LLM as CPU, then tool row below
        var hasGpuTools = agent.gpu_tools && agent.gpu_tools.length > 0;
        var llmHw = hasGpuTools ? 'CPU' : (agent.hardware || 'CPU');
        var hwBadge = document.createElement('span');
        hwBadge.className = 'crew-hw-badge ' + llmHw.toLowerCase();
        hwBadge.textContent = llmHw;
        meta.appendChild(hwBadge);

        card.appendChild(meta);

        // GPU tools row (separate line: ComfyUI + model + IMG badge)
        if (hasGpuTools) {
            agent.gpu_tools.forEach(function(tool) {
                var toolRow = document.createElement('div');
                toolRow.className = 'crew-agent-meta crew-tool-row';

                var providerSpan = document.createElement('span');
                providerSpan.textContent = (tool.provider || 'gpu').charAt(0).toUpperCase() + (tool.provider || 'gpu').slice(1);
                providerSpan.style.color = '#ffaa00';
                toolRow.appendChild(providerSpan);

                var toolModelSpan = document.createElement('span');
                var shortModel = (tool.model || '').replace('.safetensors', '').replace('.ckpt', '');
                toolModelSpan.textContent = shortModel;
                toolRow.appendChild(toolModelSpan);

                var gpuBadge = document.createElement('span');
                gpuBadge.className = 'crew-hw-badge gpu';
                gpuBadge.textContent = 'GPU';
                toolRow.appendChild(gpuBadge);

                var toolBadge = document.createElement('span');
                toolBadge.className = 'crew-tool-badge';
                var toolIcon = tool.type === 'image_generation' ? '\uD83C\uDFA8' : '\uD83C\uDFAC';
                var toolLabel = tool.type === 'image_generation' ? 'IMG' : 'VID';
                toolBadge.textContent = toolIcon + ' ' + toolLabel;
                toolBadge.title = tool.type.replace('_', ' ') + ' via ' + (tool.provider || 'gpu');
                toolRow.appendChild(toolBadge);

                card.appendChild(toolRow);
            });
        }

        // Active job (if any)
        if (agent.current_job) {
            var jobRow = document.createElement('div');
            jobRow.className = 'crew-agent-job';

            var jobDesc = document.createElement('span');
            jobDesc.textContent = agent.current_job.description || 'Working...';
            jobDesc.style.cssText = 'max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
            jobDesc.title = agent.current_job.description || '';

            var jobBar = document.createElement('div');
            jobBar.className = 'crew-job-bar';

            var jobFill = document.createElement('div');
            jobFill.className = 'crew-job-bar-fill';
            jobFill.style.width = Math.min(agent.current_job.progress_pct || 0, 100) + '%';
            jobBar.appendChild(jobFill);

            var jobPct = document.createElement('span');
            jobPct.textContent = Math.round(agent.current_job.progress_pct || 0) + '%';
            jobPct.style.fontSize = '0.6rem';

            jobRow.appendChild(jobDesc);
            jobRow.appendChild(jobBar);
            jobRow.appendChild(jobPct);
            card.appendChild(jobRow);
        }

        // Stats row
        var stats = agent.stats_24h || {};
        var statsRow = document.createElement('div');
        statsRow.className = 'crew-agent-stats';

        statsRow.appendChild(makeStatSpan(stats.dispatches || 0, 'dispatches'));
        statsRow.appendChild(makeStatSpan(Math.round((stats.success_rate || 0) * 100) + '%', 'success'));

        if (agent.learning_count > 0) {
            statsRow.appendChild(makeStatSpan(agent.learning_count, 'learnings'));
        }

        card.appendChild(statsRow);

        // Workload bar + risk glow (from parallel workload fetch)
        var wl = _crewWorkloadMap[agent.agent_id];
        if (wl) {
            var wPct = wl.workload_pct || 0;
            var wCol = wPct < 60 ? '#00ff41' : wPct < 80 ? '#ffaa00' : '#ff4444';
            var wBar = document.createElement('div');
            wBar.style.cssText = 'height:3px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;margin-top:4px;';
            var wFill = document.createElement('div');
            wFill.style.cssText = 'height:100%;border-radius:2px;width:' + Math.min(wPct, 100) + '%;background:' + wCol + ';';
            wBar.appendChild(wFill);
            card.appendChild(wBar);

            // Risk glow
            if (wl.risk_level === 'critical' || wl.risk_level === 'overloaded') {
                card.style.boxShadow = '0 0 8px rgba(255,68,68,0.3)';
                card.style.borderColor = 'rgba(255,68,68,0.4)';
            } else if (wl.risk_level === 'elevated') {
                card.style.boxShadow = '0 0 6px rgba(255,170,0,0.2)';
            }
        }

        grid.appendChild(card);
    }

    // Render all hardware groups
    if (gpuAgents.length > 0) {
        _addRosterDivider('\u26A1', 'GPU Agents', gpuAgents.length, 'gpu');
        gpuAgents.forEach(_renderAgentCard);
    }

    if (cpuAgents.length > 0) {
        _addRosterDivider('\uD83D\uDCBB', 'CPU Agents', cpuAgents.length, 'cpu');
        cpuAgents.forEach(_renderAgentCard);
    }

    if (cloudAgents.length > 0) {
        _addRosterDivider('\u2601', 'Cloud Agents', cloudAgents.length, 'cloud');
        cloudAgents.forEach(_renderAgentCard);
    }

    if (swapAgents.length > 0) {
        var _swapTotal = (capacity && capacity.ram) ? capacity.ram.swap_buffer_gb : 0;
        var _swapUsed = Math.max(0, (capacity ? capacity.models_ram_gb || 0 : 0) - ((capacity && capacity.ram) ? capacity.ram.agent_budget_gb || 0 : 0));
        _swapUsed = Math.round(_swapUsed * 10) / 10;
        var _swapFree = Math.max(0, Math.round((_swapTotal - _swapUsed) * 10) / 10);
        _addRosterDivider('\u23F3', 'Swap \u2014 On-Demand (' + _swapFree + '/' + _swapTotal + 'GB free)', swapAgents.length, 'swap');
        swapAgents.forEach(_renderAgentCard);
    }

    if (deployedAgents.length > 0) {
        _addRosterDivider('\uD83D\uDE80', 'Deployed \u2014 On Fleet Nodes', deployedAgents.length, 'deployed');
        deployedAgents.forEach(_renderAgentCard);

        // Node capacity bars — safe DOM construction, no innerHTML
        if (nodeCapacities && nodeCapacities.length > 0) {
            nodeCapacities.forEach(function(nc) {
                var nodeBar = document.createElement('div');
                nodeBar.className = 'roster-capacity-bar node-capacity';
                nodeBar.style.cssText = 'margin:8px 0 4px;padding:8px 12px;background:rgba(34,211,238,0.05);border:1px solid rgba(34,211,238,0.15);border-radius:6px;';

                // Header
                var header = document.createElement('div');
                header.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px;';
                var hName = document.createElement('span');
                hName.style.cssText = 'color:#22d3ee;font-family:Antonio,sans-serif;font-size:0.8rem;letter-spacing:1px;';
                hName.textContent = '\uD83D\uDE80 ' + (nc.node_name || 'Node');
                var hCount = document.createElement('span');
                hCount.style.cssText = 'margin-left:auto;font-size:0.65rem;color:rgba(255,255,255,0.4);';
                hCount.textContent = (nc.agent_count || 0) + ' agents';
                header.appendChild(hName);
                header.appendChild(hCount);
                nodeBar.appendChild(header);

                // GPU VRAM bar
                if (nc.gpu_model) {
                    var gpuRow = document.createElement('div');
                    gpuRow.style.cssText = 'margin-bottom:6px;';
                    var gpuHeader = document.createElement('div');
                    gpuHeader.style.cssText = 'display:flex;justify-content:space-between;font-size:0.65rem;margin-bottom:2px;';
                    var gpuLbl = document.createElement('span');
                    gpuLbl.style.color = 'rgba(255,255,255,0.5)';
                    gpuLbl.textContent = 'GPU VRAM \u2014 ' + nc.gpu_model;
                    var gpuStats = document.createElement('span');
                    gpuStats.style.color = '#22d3ee';
                    gpuStats.textContent = (nc.gpu_vram_used_gb || 0) + ' / ' + (nc.gpu_vram_gb || 0) + ' GB';
                    gpuHeader.appendChild(gpuLbl);
                    gpuHeader.appendChild(gpuStats);
                    gpuRow.appendChild(gpuHeader);
                    var gpuTrack = document.createElement('div');
                    gpuTrack.style.cssText = 'height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;';
                    var gpuFill = document.createElement('div');
                    var gpuPct = nc.gpu_vram_gb > 0 ? Math.round((nc.gpu_vram_used_gb / nc.gpu_vram_gb) * 100) : 0;
                    gpuFill.style.cssText = 'height:100%;border-radius:3px;background:linear-gradient(90deg,#22d3ee,#06b6d4);width:' + gpuPct + '%;transition:width 0.5s;';
                    gpuTrack.appendChild(gpuFill);
                    gpuRow.appendChild(gpuTrack);
                    nodeBar.appendChild(gpuRow);
                }

                // RAM bar
                var ramRow = document.createElement('div');
                ramRow.style.cssText = 'margin-bottom:6px;';
                var ramHeader = document.createElement('div');
                ramHeader.style.cssText = 'display:flex;justify-content:space-between;font-size:0.65rem;margin-bottom:2px;';
                var ramLbl = document.createElement('span');
                ramLbl.style.color = 'rgba(255,255,255,0.5)';
                ramLbl.textContent = 'RAM \u2014 ' + (nc.cpu_cores || 0) + ' cores';
                var ramStats = document.createElement('span');
                ramStats.style.color = '#4ade80';
                ramStats.textContent = (nc.ram_used_gb || 0) + ' / ' + (nc.ram_gb || 0) + ' GB';
                ramHeader.appendChild(ramLbl);
                ramHeader.appendChild(ramStats);
                ramRow.appendChild(ramHeader);
                var ramTrack = document.createElement('div');
                ramTrack.style.cssText = 'height:6px;background:rgba(255,255,255,0.08);border-radius:3px;overflow:hidden;';
                var ramFill = document.createElement('div');
                var ramPct = nc.ram_gb > 0 ? Math.round((nc.ram_used_gb / nc.ram_gb) * 100) : 0;
                ramFill.style.cssText = 'height:100%;border-radius:3px;background:linear-gradient(90deg,#4ade80,#22c55e);width:' + ramPct + '%;transition:width 0.5s;';
                ramTrack.appendChild(ramFill);
                ramRow.appendChild(ramTrack);
                nodeBar.appendChild(ramRow);

                // Loaded vs installed models
                var modHeader = document.createElement('div');
                modHeader.style.cssText = 'display:flex;justify-content:space-between;font-size:0.65rem;margin-bottom:4px;';
                var modLbl = document.createElement('span');
                modLbl.style.color = 'rgba(255,255,255,0.5)';
                modLbl.textContent = 'Models: ' + (nc.models_loaded_count || 0) + ' loaded / ' + (nc.models_installed_count || 0) + ' installed';
                modHeader.appendChild(modLbl);
                nodeBar.appendChild(modHeader);

                // Model badges — loaded glow, installed dim
                var loadedNames = {};
                (nc.models_loaded || []).forEach(function(m) { loadedNames[m.name] = m; });
                if (nc.models_installed && nc.models_installed.length > 0) {
                    var modRow = document.createElement('div');
                    modRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;';
                    nc.models_installed.forEach(function(m) {
                        var isLoaded = !!loadedNames[m.name];
                        var badge = document.createElement('span');
                        badge.style.cssText = 'padding:2px 6px;border-radius:3px;font-size:0.6rem;font-family:IBM Plex Mono,monospace;' +
                            (isLoaded
                                ? 'background:rgba(34,211,238,0.15);border:1px solid rgba(34,211,238,0.4);color:#22d3ee;text-shadow:0 0 6px rgba(34,211,238,0.3);'
                                : 'background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.1);color:rgba(255,255,255,0.35);');
                        badge.textContent = (m.name || '').replace(':latest', '') + ' (' + (m.size_gb || 0) + 'GB)';
                        badge.title = isLoaded ? 'LOADED in memory' : 'Installed, not loaded';
                        modRow.appendChild(badge);
                    });
                    nodeBar.appendChild(modRow);
                }

                grid.appendChild(nodeBar);
            });
        }
    }

    if (barrackedAgents.length > 0) {
        _addRosterDivider('\uD83C\uDFDA', 'Barracked \u2014 Reserve Pool', barrackedAgents.length, 'barracked');
        barrackedAgents.forEach(_renderAgentCard);
    }
}

// === Model Load/Unload Control ===
function _toggleAgentModel(agent, btn) {
    var model = agent.model || '';
    var isLoaded = agent.llm_status === 'loaded';
    var action = isLoaded ? 'unload' : 'load';
    var hw = (agent.hardware || 'CPU').toUpperCase();

    // Confirm unload if agent is working
    if (isLoaded && agent.status === 'working') {
        if (!confirm('Warning: ' + (agent.full_name || agent.name) + ' is currently working.\n\nUnloading their model will interrupt any active dispatch.\n\nContinue?')) return;
    }

    // Confirm load — show estimated impact
    if (!isLoaded) {
        var sizeNote = agent.llm_size_gb ? ' (~' + agent.llm_size_gb + 'GB)' : '';
        if (!confirm('Load ' + model.replace(':latest', '') + sizeNote + ' into memory?\n\nThis may take a moment for cold-load models.')) return;
    }

    btn.disabled = true;
    btn.textContent = isLoaded ? 'Unloading...' : 'Loading...';

    fetch('/tools/bridge/api/bridge/model-control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            model: model,
            action: action,
            num_gpu: hw === 'GPU' ? 99 : 0
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            loadCrewManifest();
        } else {
            alert('Failed: ' + (data.error || 'Unknown error'));
            btn.disabled = false;
            btn.textContent = isLoaded ? 'Unload' : 'Load';
        }
    })
    .catch(function() {
        alert('Request failed — check network');
        btn.disabled = false;
        btn.textContent = isLoaded ? 'Unload' : 'Load';
    });
}

// === ComfyUI Checkpoint Control ===
function _loadComfyCheckpoints() {
    var body = document.getElementById('comfyui-checkpoint-body');
    if (!body) return;

    fetch('/tools/bridge/api/bridge/comfyui/models')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (!data.success && data.error) {
            body.textContent = 'Error: ' + data.error;
            return;
        }
        if (!data.online) {
            body.innerHTML = '<span style="color:#ef4444;">&#9679;</span> ComfyUI offline';
            return;
        }

        var models = data.models || [];
        var current = data.current_model;
        var vram = data.vram_used_gb || 0;
        var queue = data.queue || {};

        var html = '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
            + '<span style="color:#22c55e;">&#9679;</span> Online'
            + (vram > 0.5 ? ' &mdash; ' + vram.toFixed(1) + 'GB VRAM' : '')
            + (queue.running > 0 ? ' &mdash; <span style="color:#f59e0b;">' + queue.running + ' generating</span>' : '')
            + '</div>';

        if (models.length === 0) {
            html += '<div style="color:var(--archie-text-muted);">No checkpoints installed</div>';
        } else {
            html += '<div style="display:flex;flex-wrap:wrap;gap:4px;">';
            models.forEach(function(m) {
                var short = m.replace('.safetensors', '').replace('.ckpt', '');
                var isXl = m.toLowerCase().indexOf('xl') >= 0;
                var isLoaded = current && m === current;
                var bgColor = isLoaded ? 'rgba(139,92,246,0.3)' : 'rgba(255,255,255,0.05)';
                var border = isLoaded ? '1px solid #8b5cf6' : '1px solid rgba(255,255,255,0.1)';
                var badge = isXl ? ' <span style="font-size:9px;background:#8b5cf6;padding:1px 4px;border-radius:3px;">XL</span>' : '';

                html += '<div style="display:inline-flex;align-items:center;gap:4px;padding:3px 8px;'
                    + 'background:' + bgColor + ';border:' + border + ';border-radius:4px;font-size:11px;">'
                    + '<span>' + short + badge + '</span>'
                    + '<button onclick="_comfyControl(\'' + m.replace(/'/g, "\\'") + '\', ' + (isLoaded ? "'unload'" : "'load'") + ', this)" '
                    + 'style="background:none;border:none;cursor:pointer;padding:2px 4px;font-size:10px;'
                    + 'color:' + (isLoaded ? '#ef4444' : '#22c55e') + ';">'
                    + (isLoaded ? '&#9632; Unload' : '&#9654; Load')
                    + '</button></div>';
            });
            html += '</div>';
        }
        body.innerHTML = html;
    })
    .catch(function() {
        body.textContent = 'Failed to load';
    });
}

function _comfyControl(model, action, btn) {
    var short = model.replace('.safetensors', '').replace('.ckpt', '');
    var msg = action === 'load'
        ? 'Load ' + short + ' into GPU VRAM?\n\nThis runs a warmup generation (~30s for SDXL).'
        : 'Unload all ComfyUI models from VRAM?';
    if (!confirm(msg)) return;

    btn.disabled = true;
    btn.textContent = action === 'load' ? 'Loading...' : 'Unloading...';

    fetch('/tools/bridge/api/bridge/comfyui/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model, action: action })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            _loadComfyCheckpoints();
            loadCrewManifest();
        } else {
            alert('Failed: ' + (data.error || 'Unknown error'));
            btn.disabled = false;
            btn.textContent = action === 'load' ? '▶ Load' : '■ Unload';
        }
    })
    .catch(function() {
        alert('Request failed');
        btn.disabled = false;
        btn.textContent = action === 'load' ? '▶ Load' : '■ Unload';
    });
}

// === Agent Profile Modal (with client-side cache + manifest preload) ===
var _profileCache = {};      // agentId -> { ts: timestamp, data: response }
var _profileCacheTTL = 30;   // seconds

function _getManifestAgent(agentId) {
    // Pull instant data from crew manifest (already loaded, no network call)
    var grid = document.getElementById('crew-manifest-grid');
    if (!grid || !window._lastCrewData) return null;
    for (var i = 0; i < window._lastCrewData.length; i++) {
        if (window._lastCrewData[i].agent_id === agentId || window._lastCrewData[i].id === agentId) {
            return window._lastCrewData[i];
        }
    }
    return null;
}

function _renderProfilePreview(agentId, body, title) {
    // Show instant preview from manifest data while full profile loads
    var manifest = _getManifestAgent(agentId);
    if (!manifest) return;
    var name = manifest.full_name || manifest.name || '';
    title.textContent = name;
    var previewEl = document.createElement('div');
    previewEl.style.cssText = 'opacity:0.7;';

    var hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;gap:12px;align-items:center;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.1);';
    var avatar = document.createElement('div');
    avatar.style.cssText = 'width:48px;height:48px;border-radius:50%;background:var(--archie-cyan);display:flex;align-items:center;justify-content:center;font-size:1.2rem;font-weight:700;color:#000;';
    avatar.textContent = (name[0] || '?').toUpperCase();
    hdr.appendChild(avatar);
    var info = document.createElement('div');
    info.style.flex = '1';
    var nameEl = document.createElement('div');
    nameEl.style.cssText = 'font-size:1rem;font-weight:600;';
    nameEl.textContent = name;
    info.appendChild(nameEl);
    var subEl = document.createElement('div');
    subEl.style.cssText = 'font-size:0.75rem;color:var(--archie-text-muted);';
    subEl.textContent = (manifest.name || '') + (manifest.title ? ' \u2014 ' + manifest.title : '');
    info.appendChild(subEl);
    var metaEl = document.createElement('div');
    metaEl.style.cssText = 'font-size:0.7rem;color:var(--archie-text-tertiary);';
    metaEl.textContent = (manifest.station || '') + ' \u2022 ' + (manifest.model || '').replace(':latest', '') + ' \u2022 ' + (manifest.hardware || 'CPU');
    info.appendChild(metaEl);
    hdr.appendChild(info);
    previewEl.appendChild(hdr);

    var loadingEl = document.createElement('div');
    loadingEl.style.cssText = 'text-align:center;padding:1rem;color:var(--archie-text-muted);font-size:0.75rem;';
    loadingEl.textContent = 'Loading full profile...';
    previewEl.appendChild(loadingEl);

    body.replaceChildren(previewEl);
}

function openAgentProfile(agentId) {
    _profileAgentId = agentId;
    var modal = document.getElementById('agent-profile-modal');
    var body = document.getElementById('agent-profile-body');
    var title = document.getElementById('agent-profile-title');
    if (!modal || !body) return;
    title.textContent = 'Agent Profile';
    modal.classList.add('active');

    // Check client-side cache first
    var cached = _profileCache[agentId];
    if (cached && (Date.now() - cached.ts) < _profileCacheTTL * 1000) {
        _renderFullProfile(cached.data, body, title);
        return;
    }

    // Show instant preview from manifest while fetching
    _renderProfilePreview(agentId, body, title);

    fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/profile')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            // Cache the response
            _profileCache[agentId] = { ts: Date.now(), data: data };
            _renderFullProfile(data, body, title);
        }).catch(function() {
            body.textContent = 'Failed to load profile';
        });
}

function _renderFullProfile(data, body, title) {
            var agentId = _profileAgentId;
            if (!data.success) {
                body.textContent = 'Failed to load profile';
                return;
            }
            var a = data.agent;
            var esc = function(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
            var fullName = esc((a.first_name || '') + ' ' + (a.last_name || '')).trim() || esc(a.name);
            title.textContent = fullName;

            var html = '';

            // Agent header — portrait with fallback
            var stColor = a.station_color || 'var(--archie-cyan)';
            var portraitSrc = (data.portraits && data.portraits.portrait) || '';
            var initial = (a.first_name || a.name || '?')[0].toUpperCase();
            html += '<div style="display:flex;gap:12px;align-items:center;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid rgba(255,255,255,0.1);">';
            html += '<img class="crew-profile-portrait" src="' + esc(portraitSrc) + '" alt="' + esc(initial) + '" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';">';
            html += '<div class="crew-profile-portrait-fallback" style="display:none;background:' + esc(stColor) + ';">' + esc(initial) + '</div>';
            html += '<div style="flex:1;">';
            html += '<div style="font-size:1rem;font-weight:600;">' + fullName + '</div>';
            html += '<div style="font-size:0.75rem;color:var(--archie-text-muted);">' + esc(a.name) + (a.title ? ' &mdash; ' + esc(a.title) : '') + '</div>';
            html += '<div style="font-size:0.7rem;color:var(--archie-text-tertiary);">';
            html += esc(a.department || '') + ' &bull; ' + esc(a.model || '') + ' &bull; ' + esc(a.worker_type || '') + ' &bull; ' + esc(a.pronouns || '');
            html += '</div></div>';
            html += '<span class="crew-status-badge ' + esc(a.status) + '" style="font-size:0.7rem;">' + esc(a.status) + '</span>';
            html += '</div>';

            // Bio
            if (a.bio) {
                html += '<div class="briefing-card" style="--card-accent:' + esc(stColor) + ';margin-bottom:10px;">';
                html += '<div class="briefing-card-body" style="font-size:0.75rem;color:var(--archie-text-secondary);">' + esc(a.bio) + '</div>';
                html += '</div>';
            }

            // Station assignment
            if (a.station_code) {
                html += '<div style="display:flex;gap:6px;align-items:center;margin-bottom:10px;font-size:0.75rem;">';
                html += '<span style="color:' + esc(stColor) + ';font-weight:600;">&#9632; ' + esc(a.station_name || a.station_code) + '</span>';
                html += '</div>';
            }

            // Two-column layout: Performance + Emotional State
            html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">';

            // Performance (24h)
            var p = data.performance_24h;
            html += '<div class="briefing-card" style="--card-accent:#00ff41;">';
            html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Performance (24h)</span></div>';
            html += '<div class="briefing-card-body">';
            html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
            html += '<span>Tasks</span><span style="color:var(--archie-cyan);">' + parseInt(p.tasks) + '</span></div>';
            html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
            html += '<span>Completed</span><span style="color:#00ff41;">' + parseInt(p.completed) + '</span></div>';
            html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
            html += '<span>Failed</span><span style="color:#ff4444;">' + parseInt(p.failed) + '</span></div>';
            html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
            html += '<span>Avg Duration</span><span>' + formatDuration(p.avg_duration_ms) + '</span></div>';
            html += '</div></div>';

            // Emotional State
            var em = data.emotional_state;
            html += '<div class="briefing-card" style="--card-accent:#8b5cf6;">';
            html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Wellness</span></div>';
            html += '<div class="briefing-card-body">';
            if (em) {
                var moodColor = (em.stress_level || 0) <= 0.4 ? '#00ff41' : (em.stress_level || 0) <= 0.7 ? '#ffaa00' : '#ff4444';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                html += '<span>Mood</span><span style="text-transform:capitalize;">' + esc(em.current_mood || 'neutral') + '</span></div>';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                html += '<span>Stress</span><span style="color:' + moodColor + ';">' + Math.round((em.stress_level || 0) * 100) + '%</span></div>';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                html += '<span>Energy</span><span>' + Math.round((em.energy_level || 0) * 100) + '%</span></div>';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                html += '<span>Intensity</span><span>' + Math.round((em.mood_intensity || 0) * 100) + '%</span></div>';
            } else {
                html += '<span style="font-size:0.75rem;color:var(--archie-text-muted);">No emotional data</span>';
            }
            html += '</div></div>';
            html += '</div>';

            // Identity traits (from agent_identity table)
            if (data.identity && data.identity.length > 0) {
                html += '<div class="briefing-card" style="--card-accent:#e879f9;margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Identity Traits</span></div>';
                html += '<div class="briefing-card-body">';
                data.identity.forEach(function(t) {
                    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:0.75rem;">';
                    html += '<span style="color:var(--archie-text-secondary);text-transform:capitalize;">' + esc(t.identity_key) + '</span>';
                    html += '<span>' + esc(t.identity_value) + '</span>';
                    html += '</div>';
                });
                html += '</div></div>';
            }

            // Voice DNA + Emotional History — side by side
            var hasVoice = data.voice;
            var hasEmHistory = data.emotional_history && data.emotional_history.length > 0;
            if (hasVoice || hasEmHistory) {
                var cols = (hasVoice && hasEmHistory) ? '1fr 1fr' : '1fr';
                html += '<div style="display:grid;grid-template-columns:' + cols + ';gap:10px;margin-bottom:10px;">';

                if (hasVoice) {
                    var v = data.voice;
                    html += '<div class="briefing-card" style="--card-accent:#06b6d4;">';
                    html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Voice DNA</span></div>';
                    html += '<div class="briefing-card-body">';
                    if (v.engine) {
                        html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                        html += '<span>Engine</span><span>' + esc(v.engine) + '</span></div>';
                    }
                    if (v.language) {
                        html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                        html += '<span>Language</span><span>' + esc(v.language) + '</span></div>';
                    }
                    if (v.profile_name) {
                        html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                        html += '<span>Profile</span><span>' + esc(v.profile_name) + '</span></div>';
                    }
                    if (v.speaker) {
                        html += '<div style="display:flex;justify-content:space-between;font-size:0.75rem;padding:2px 0;">';
                        html += '<span>Speaker</span><span style="font-size:0.65rem;color:var(--archie-text-muted);">' + esc(v.speaker) + '</span></div>';
                    }
                    html += '</div></div>';
                }

                if (hasEmHistory) {
                    html += '<div class="briefing-card" style="--card-accent:#8b5cf6;">';
                    html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Emotional History</span></div>';
                    html += '<div class="briefing-card-body" style="max-height:160px;overflow-y:auto;">';
                    data.emotional_history.forEach(function(e) {
                        var stressColor = (e.stress_level || 0) <= 0.4 ? '#00ff41' : (e.stress_level || 0) <= 0.7 ? '#ffaa00' : '#ff4444';
                        html += '<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;">';
                        html += '<span style="text-transform:capitalize;">' + esc(e.current_mood || 'neutral') + '</span>';
                        html += '<span style="color:' + stressColor + ';font-size:0.65rem;">stress ' + Math.round((e.stress_level || 0) * 100) + '%</span>';
                        html += '<span style="color:var(--archie-text-tertiary);font-size:0.65rem;">' + ArchieTime.age(e.timestamp) + '</span>';
                        html += '</div>';
                    });
                    html += '</div></div>';
                }

                html += '</div>';
            }

            // Rest Cycles
            if (data.rest_cycles && data.rest_cycles.length > 0) {
                html += '<div class="briefing-card" style="--card-accent:#a78bfa;margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Rest Cycles</span></div>';
                html += '<div class="briefing-card-body">';
                data.rest_cycles.forEach(function(rc) {
                    var ended = rc.ended_at ? ArchieTime.age(rc.ended_at) : '<span style="color:#ffaa00;">ongoing</span>';
                    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.04);font-size:0.72rem;">';
                    html += '<span>' + esc(rc.rest_type || 'break') + '</span>';
                    html += '<span style="color:var(--archie-text-muted);">' + esc(rc.reason || '') + '</span>';
                    html += '<span style="color:var(--archie-text-tertiary);font-size:0.65rem;">' + ended + '</span>';
                    html += '</div>';
                });
                html += '</div></div>';
            }

            // Skills (with add/remove)
            html += '<div class="briefing-card" style="--card-accent:#ffaa00;margin-bottom:10px;">';
            html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Skills</span></div>';
            html += '<div class="briefing-card-body">';
            html += '<div id="profile-skills-list" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px;">';
            if (data.skills && data.skills.length > 0) {
                data.skills.forEach(function(s) {
                    var level = parseInt(s.proficiency_level) || 1;
                    var dots = '';
                    for (var i = 0; i < 5; i++) dots += i < level ? '&#9679;' : '&#9675;';
                    html += '<span style="display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;font-size:0.7rem;">';
                    html += esc(s.skill_name) + ' <span style="color:var(--archie-gold);font-size:0.6rem;">' + dots + '</span>';
                    html += ' <span onclick="removeSkill(' + parseInt(agentId) + ',\'' + esc(String(s.id)) + '\')" style="cursor:pointer;color:#ff4444;font-size:0.6rem;margin-left:2px;" title="Remove">&times;</span>';
                    html += '</span>';
                });
            } else {
                html += '<span style="font-size:0.7rem;color:var(--archie-text-muted);">No skills</span>';
            }
            html += '</div>';
            // Add skill inline form
            html += '<div style="display:flex;gap:4px;align-items:center;">';
            html += '<input type="text" id="add-skill-name" placeholder="Skill name" style="flex:1;padding:2px 6px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:3px;color:inherit;font-size:0.65rem;">';
            html += '<select id="add-skill-level" style="padding:2px 4px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:3px;color:inherit;font-size:0.65rem;">';
            html += '<option value="1">1</option><option value="2">2</option><option value="3" selected>3</option><option value="4">4</option><option value="5">5</option>';
            html += '</select>';
            html += '<button onclick="addSkill(' + parseInt(agentId) + ')" style="background:rgba(0,255,65,0.15);border:1px solid rgba(0,255,65,0.3);color:#00ff41;padding:2px 6px;border-radius:3px;font-size:0.6rem;cursor:pointer;">Add</button>';
            html += '</div>';
            html += '</div></div>';

            // Recent Tasks
            if (data.recent_tasks && data.recent_tasks.length > 0) {
                html += '<div class="briefing-card" style="--card-accent:var(--archie-cyan);margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Recent Tasks</span></div>';
                html += '<div class="briefing-card-body">';
                data.recent_tasks.forEach(function(t) {
                    var icon = t.success === true ? '&#9679;' : t.success === false ? '&#9679;' : '&#9675;';
                    var color = t.success === true ? '#00ff41' : t.success === false ? '#ff4444' : 'var(--archie-text-muted)';
                    html += '<div style="display:flex;justify-content:space-between;padding:2px 0;font-size:0.7rem;">';
                    html += '<span style="color:' + color + ';">' + icon + ' ' + esc(t.module_source || '') + (t.capability ? ' / ' + esc(t.capability) : '') + '</span>';
                    html += '<span style="color:var(--archie-text-tertiary);">' + formatDuration(t.duration_ms) + '</span>';
                    html += '</div>';
                });
                html += '</div></div>';
            }

            // Memory highlights
            if (data.memories && data.memories.length > 0) {
                html += '<div class="briefing-card" style="--card-accent:#e879f9;margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Memory Highlights</span></div>';
                html += '<div class="briefing-card-body">';
                data.memories.forEach(function(m) {
                    var score = m.importance_score ? parseFloat(m.importance_score).toFixed(2) : '--';
                    html += '<div style="padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.7rem;">';
                    html += '<div style="display:flex;justify-content:space-between;">';
                    html += '<span style="color:var(--archie-text-secondary);text-transform:capitalize;">' + esc(m.memory_type || '') + '</span>';
                    html += '<span style="color:var(--archie-gold);">' + score + '</span>';
                    html += '</div>';
                    var preview = (m.content || '').substring(0, 120);
                    html += '<div style="color:var(--archie-text-muted);font-size:0.65rem;margin-top:1px;">' + esc(preview) + (m.content && m.content.length > 120 ? '...' : '') + '</div>';
                    html += '</div>';
                });
                html += '</div></div>';
            }

            // Performance Rankings
            if (data.rankings && data.rankings.length > 0) {
                html += '<div class="briefing-card" style="--card-accent:#00d4ff;margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Performance Rankings</span></div>';
                html += '<div class="briefing-card-body">';
                data.rankings.forEach(function(rk) {
                    html += '<div class="crew-profile-ranking">';
                    html += '<span>' + esc(rk.capability || '') + '</span>';
                    html += '<span style="display:flex;gap:8px;">';
                    html += '<span class="rank-pos">#' + parseInt(rk.rank_position || 0) + '</span>';
                    html += '<span style="color:var(--archie-gold);">' + (rk.rank_score != null ? parseFloat(rk.rank_score).toFixed(2) : '--') + '</span>';
                    html += '<span style="color:var(--archie-text-muted);">' + parseInt(rk.tasks_completed || 0) + ' tasks</span>';
                    var sr = rk.success_rate != null ? Math.round(rk.success_rate * 100) : 0;
                    var srColor = sr >= 90 ? '#00ff41' : sr >= 70 ? '#ffaa00' : '#ff4444';
                    html += '<span style="color:' + srColor + ';">' + sr + '%</span>';
                    html += '</span></div>';
                });
                html += '</div></div>';
            }

            // Shift History (from agent_rotation_log)
            if (data.shift_history && data.shift_history.length > 0) {
                html += '<div class="briefing-card" style="--card-accent:#f59e0b;margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Shift History</span></div>';
                html += '<div class="briefing-card-body" style="max-height:180px;overflow-y:auto;">';
                data.shift_history.forEach(function(sh) {
                    var stateColors = { active: '#00ff41', winding_down: '#ffaa00', cooldown: '#60a5fa', off_duty: '#888' };
                    var sColor = stateColors[sh.shift_state] || '#888';
                    html += '<div class="crew-profile-shift-row">';
                    html += '<span style="color:' + sColor + ';text-transform:uppercase;font-weight:600;min-width:80px;">' + esc(sh.shift_state || '') + '</span>';
                    html += '<span style="min-width:70px;">' + esc(sh.station_code || '—') + '</span>';
                    html += '<span style="flex:1;color:var(--archie-text-muted);">' + esc(sh.reason || '') + '</span>';
                    html += '<span>' + (sh.tasks_completed ? parseInt(sh.tasks_completed) + '/' + (parseInt(sh.tasks_completed) + parseInt(sh.tasks_failed || 0)) : '') + '</span>';
                    if (sh.replaced_by_name) {
                        html += '<span style="color:#e879f9;margin-left:4px;" title="Replaced by">&rarr; ' + esc(sh.replaced_by_name) + '</span>';
                    }
                    html += '<span style="min-width:60px;text-align:right;">' + (sh.started_at ? ArchieTime.age(sh.started_at) : '') + '</span>';
                    html += '</div>';
                });
                html += '</div></div>';
            }

            // Welfare Gauges (stress + energy bars)
            var wellEm = data.emotional_state;
            if (wellEm) {
                var stress = Math.round((wellEm.stress_level || 0) * 100);
                var energy = Math.round((wellEm.energy_level || 0) * 100);
                var stressColor = stress <= 40 ? '#00ff41' : stress <= 70 ? '#ffaa00' : '#ff4444';
                var energyColor = energy >= 60 ? '#00ff41' : energy >= 30 ? '#ffaa00' : '#ff4444';
                html += '<div class="briefing-card" style="--card-accent:' + stressColor + ';margin-bottom:10px;">';
                html += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>Welfare Gauges</span></div>';
                html += '<div class="briefing-card-body">';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;"><span>Stress</span><span>' + stress + '%</span></div>';
                html += '<div class="crew-profile-welfare-bar"><div class="crew-profile-welfare-fill" style="width:' + stress + '%;background:' + stressColor + ';"></div></div>';
                html += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;margin-top:8px;"><span>Energy</span><span>' + energy + '%</span></div>';
                html += '<div class="crew-profile-welfare-bar"><div class="crew-profile-welfare-fill" style="width:' + energy + '%;background:' + energyColor + ';"></div></div>';
                html += '</div></div>';
            }

            // IAAE Welfare & Compliance section (placeholder, filled async)
            html += '<div id="profile-iaae-section"></div>';

            // Work History section (placeholder, filled async)
            html += '<div id="profile-work-history-section"></div>';

            body.innerHTML = html;

            // Async fetch work history for this agent
            fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/work-history')
                .then(function(r) { return r.json(); })
                .then(function(whData) {
                    var whSection = document.getElementById('profile-work-history-section');
                    if (!whSection || !whData.success) return;
                    var proposals = whData.proposals || [];
                    if (proposals.length === 0) return;

                    var card = document.createElement('div');
                    card.className = 'briefing-card';
                    card.style.cssText = '--card-accent:#60a5fa;margin-bottom:10px;';

                    var header = document.createElement('div');
                    header.className = 'briefing-card-header';
                    header.style.cssText = 'font-size:0.7rem;';
                    var headerSpan = document.createElement('span');
                    headerSpan.textContent = 'Work History \u2014 Proposals';
                    header.appendChild(headerSpan);
                    card.appendChild(header);

                    var cardBody = document.createElement('div');
                    cardBody.className = 'briefing-card-body';

                    // Show last 5 proposals
                    var shown = proposals.slice(0, 5);
                    shown.forEach(function(p) {
                        var row = document.createElement('div');
                        row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.7rem;';

                        var badge = document.createElement('span');
                        var statusText = (p.status || 'unknown').toLowerCase();
                        var statusColor = statusText === 'deployed' ? '#6ee7b7' : statusText === 'approved' ? '#93c5fd' : 'rgba(255,255,255,0.3)';
                        badge.style.cssText = 'display:inline-block;width:8px;height:8px;border-radius:50%;background:' + statusColor + ';flex-shrink:0;';
                        badge.title = statusText;
                        row.appendChild(badge);

                        var titleSpan = document.createElement('span');
                        titleSpan.style.cssText = 'flex:1;color:var(--archie-text-secondary);';
                        titleSpan.textContent = p.title || 'Untitled';
                        row.appendChild(titleSpan);

                        var statusSpan = document.createElement('span');
                        statusSpan.style.cssText = 'color:' + statusColor + ';font-size:0.65rem;text-transform:capitalize;';
                        statusSpan.textContent = statusText;
                        row.appendChild(statusSpan);

                        cardBody.appendChild(row);
                    });

                    // Aggregate summary
                    var deployed = proposals.filter(function(p) { return (p.status || '').toLowerCase() === 'deployed'; }).length;
                    var summary = document.createElement('div');
                    summary.style.cssText = 'margin-top:6px;font-size:0.65rem;color:var(--archie-text-muted);';
                    summary.textContent = deployed + '/' + proposals.length + ' proposals deployed';
                    cardBody.appendChild(summary);

                    card.appendChild(cardBody);
                    whSection.appendChild(card);
                }).catch(function() {});

            // Async fetch workload data for this agent
            fetch('/tools/bridge/api/agents/workload')
                .then(function(r) { return r.json(); })
                .then(function(wData) {
                    var section = document.getElementById('profile-iaae-section');
                    if (!section || !wData.success) return;
                    var me = null;
                    (wData.agents || []).forEach(function(w) { if (w.id === parseInt(agentId)) me = w; });
                    if (!me) return;

                    var iHtml = '<div class="briefing-card" style="--card-accent:#ff6b6b;margin-bottom:10px;">';
                    iHtml += '<div class="briefing-card-header" style="font-size:0.7rem;"><span>IAAE Welfare & Compliance</span>';

                    // Risk badge
                    var riskColors = { healthy: '#00ff41', elevated: '#ffaa00', critical: '#ff6b6b', overloaded: '#ff0000' };
                    var riskColor = riskColors[me.risk_level] || '#888';
                    iHtml += '<span style="background:' + riskColor + '22;color:' + riskColor + ';padding:1px 6px;border-radius:3px;font-size:0.6rem;text-transform:uppercase;border:1px solid ' + riskColor + '44;">' + esc(me.risk_level) + '</span>';
                    iHtml += '</div>';
                    iHtml += '<div class="briefing-card-body">';

                    // Workload gauge
                    var wPct = me.workload_pct || 0;
                    var wColor = wPct < 60 ? '#00ff41' : wPct < 80 ? '#ffaa00' : '#ff4444';
                    iHtml += '<div style="margin-bottom:8px;">';
                    iHtml += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;">';
                    iHtml += '<span>Workload (24h)</span><span>' + parseInt(me.tasks_24h) + ' / ' + parseInt(me.daily_cap) + ' tasks</span></div>';
                    iHtml += '<div style="height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden;">';
                    iHtml += '<div style="height:100%;width:' + Math.min(wPct, 100) + '%;background:' + wColor + ';border-radius:3px;transition:width 0.3s;"></div></div></div>';

                    // Token gauge
                    var tPct = me.token_usage_pct || 0;
                    var tColor = tPct < 60 ? '#00ff41' : tPct < 80 ? '#ffaa00' : '#ff4444';
                    iHtml += '<div style="margin-bottom:8px;">';
                    iHtml += '<div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:2px;">';
                    iHtml += '<span>Token Usage</span><span>' + parseInt(me.tokens_used_24h).toLocaleString() + ' / ' + parseInt(me.token_cap).toLocaleString() + '</span></div>';
                    iHtml += '<div style="height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden;">';
                    iHtml += '<div style="height:100%;width:' + Math.min(tPct, 100) + '%;background:' + tColor + ';border-radius:3px;transition:width 0.3s;"></div></div></div>';

                    // Performance stats
                    iHtml += '<div style="display:flex;gap:12px;font-size:0.7rem;margin-bottom:8px;">';
                    iHtml += '<span>Completed: <span style="color:#00ff41;">' + parseInt(me.completed_24h) + '</span></span>';
                    iHtml += '<span>Failed: <span style="color:#ff4444;">' + parseInt(me.failed_24h) + '</span></span>';
                    iHtml += '<span>Avg: <span style="color:var(--archie-cyan);">' + formatDuration(me.avg_duration_ms) + '</span></span>';
                    iHtml += '</div>';

                    // Send to rest button if at risk
                    if (wPct >= 80 || (em && (em.stress_level || 0) > 0.7)) {
                        iHtml += '<button onclick="sendToLoungeById(' + parseInt(agentId) + ');closeAgentProfile();" style="background:rgba(255,107,107,0.15);border:1px solid rgba(255,107,107,0.3);color:#ff6b6b;padding:4px 10px;border-radius:4px;font-size:0.7rem;cursor:pointer;width:100%;">Send to Rest (Recommended)</button>';
                    }

                    iHtml += '</div></div>';
                    section.innerHTML = iHtml;
                }).catch(function() {});
}

function closeAgentProfile() {
    var modal = document.getElementById('agent-profile-modal');
    if (modal) modal.classList.remove('active');
}

// Store current profile agent ID for edit/delete/toggle
var _profileAgentId = null;

function viewPersonnelFile() {
    if (!_profileAgentId) return;
    window.location.href = '/tools/consciousness#team';
}

function editAgentFromProfile() {
    if (!_profileAgentId) return;
    closeAgentProfile();
    // Fetch current data and populate form
    fetch('/tools/bridge/api/agents/' + parseInt(_profileAgentId) + '/profile')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var a = data.agent;
            document.getElementById('agent-form-id').value = a.id;
            document.getElementById('agent-form-name').value = a.name || '';
            document.getElementById('agent-form-first').value = a.first_name || '';
            document.getElementById('agent-form-last').value = a.last_name || '';
            document.getElementById('agent-form-title-input').value = a.title || '';
            document.getElementById('agent-form-dept').value = a.department || '';
            document.getElementById('agent-form-worker').value = a.worker_type || 'ai';
            document.getElementById('agent-form-bio').value = a.bio || '';
            document.getElementById('agent-form-prompt').value = '';
            document.getElementById('agent-form-title').textContent = 'Edit Agent';
            document.getElementById('agent-form-modal').classList.add('active');
            // Set model and load context
            document.getElementById('agent-form-model').value = a.model || '';
            fetch('/tools/bridge/api/bridge/agent-form-context')
                .then(function(r) { return r.json(); })
                .then(function(ctxData) {
                    if (!ctxData.success) return;
                    _agentFormContext = ctxData;
                    _renderAgentFormContext(ctxData, true);
                    // Highlight the current model in dropdown
                    var currentModel = a.model || '';
                    var dd = document.getElementById('agent-form-model-dropdown');
                    if (dd && currentModel) {
                        dd.querySelectorAll('.model-dd-item').forEach(function(item) {
                            var name = item.getAttribute('data-model') || '';
                            if (name === currentModel || name.replace(':latest', '') === currentModel) {
                                item.classList.add('selected');
                            }
                        });
                    }
                });
        });
}

function deleteAgentFromProfile() {
    if (!_profileAgentId) return;
    if (!confirm('Delete this agent permanently?')) return;
    fetch('/tools/bridge/api/agents/' + parseInt(_profileAgentId), { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                closeAgentProfile();
                loadCrewManifest();
            }
        });
}

function toggleAgentFromProfile() {
    if (!_profileAgentId) return;
    fetch('/tools/bridge/api/agents/' + parseInt(_profileAgentId) + '/toggle', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                closeAgentProfile();
                loadCrewManifest();
            }
        });
}

// === Agent Form Modal (Create/Edit) ===
var _agentFormContext = null; // cached context from API
var _agentFormMaxSwap = 3;   // max agents in swap state allowed

function openAgentFormModal(agentId) {
    document.getElementById('agent-form-id').value = agentId || '';
    document.getElementById('agent-form-name').value = '';
    document.getElementById('agent-form-first').value = '';
    document.getElementById('agent-form-last').value = '';
    document.getElementById('agent-form-title-input').value = '';
    document.getElementById('agent-form-dept').value = '';
    document.getElementById('agent-form-model').value = '';
    document.getElementById('agent-form-model-value').value = '';
    document.getElementById('agent-form-worker').value = 'ai';
    document.getElementById('agent-form-bio').value = '';
    document.getElementById('agent-form-prompt').value = '';
    document.getElementById('agent-form-title').textContent = agentId ? 'Edit Agent' : 'Add Agent';
    document.getElementById('agent-form-modal').classList.add('active');

    // Clear previous state
    var banner = document.getElementById('agent-form-ram-banner');
    banner.style.display = 'none';
    var hwOverview = document.getElementById('agent-form-hw-overview');
    hwOverview.style.display = 'none';
    hwOverview.textContent = '';
    var mediaSec = document.getElementById('agent-form-media-section');
    mediaSec.style.display = 'none';
    mediaSec.textContent = '';
    var dropdown = document.getElementById('agent-form-model-dropdown');
    dropdown.style.display = 'none';
    dropdown.textContent = '';
    var infoBox = document.getElementById('agent-form-model-info');
    infoBox.style.display = 'none';

    // Fetch model catalog for descriptions (non-blocking, best-effort)
    if (!window._modelCatalog) {
        fetch('/tools/bridge/api/model-catalog')
            .then(function(r) { return r.json(); })
            .then(function(d) { if (d.success) window._modelCatalog = d.catalog || {}; })
            .catch(function() { window._modelCatalog = {}; });
    }

    // Fetch context
    fetch('/tools/bridge/api/bridge/agent-form-context')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            _agentFormContext = data;
            _renderAgentFormContext(data, agentId);
        })
        .catch(function() {
            picker.textContent = 'Could not load model data';
        });
}

function _renderAgentFormContext(ctx, isEdit) {
    var banner = document.getElementById('agent-form-ram-banner');
    var picker = document.getElementById('agent-form-model-picker');
    var ram = ctx.ram || {};
    var gpu = ctx.gpu || {};

    // Count current swap agents
    var swapCount = 0;
    try {
        var crewGrid = document.getElementById('crew-manifest-grid');
        if (crewGrid) {
            var cards = crewGrid.querySelectorAll('.crew-llm-badge.swap');
            swapCount = cards.length;
        }
    } catch(e) {}

    // Critical RAM warning only
    if (ram.status === 'red') {
        banner.className = 'agent-form-ram-warn red';
        banner.textContent = '\u26A0 Critical: Only ' + ram.available_gb + 'GB RAM free (reserve: ' + ram.reserve_gb + 'GB). Adding agents with unloaded models risks system instability.';
        banner.style.display = 'flex';
    } else {
        banner.style.display = 'none';
    }

    // Swap limit warning
    if (swapCount >= _agentFormMaxSwap && !isEdit) {
        var swapWarn = document.createElement('div');
        swapWarn.className = 'agent-form-ram-warn amber';
        swapWarn.textContent = '\u26A0 Swap limit: ' + swapCount + '/' + _agentFormMaxSwap + ' agents already in SWAP state. Choose a loaded model to avoid cold-load contention.';
        swapWarn.style.display = 'flex';
        banner.parentNode.insertBefore(swapWarn, banner.nextSibling);
        swapWarn.setAttribute('data-swap-warn', '1');
    }

    // Hardware overview — GPU + RAM
    var hwOverview = document.getElementById('agent-form-hw-overview');
    hwOverview.style.display = 'block';
    hwOverview.className = 'agent-form-hw-overview';
    while (hwOverview.firstChild) hwOverview.removeChild(hwOverview.firstChild);

    // GPU section
    if (gpu.available) {
        var gpuSec = document.createElement('div');
        gpuSec.className = 'hw-section';
        var gpuHdr = document.createElement('div');
        gpuHdr.className = 'hw-section-hdr';
        var gpuDot = document.createElement('span');
        gpuDot.className = 'hw-dot ' + gpu.status;
        gpuHdr.appendChild(gpuDot);
        gpuHdr.appendChild(document.createTextNode('VIDEO CARD \u2014 ' + gpu.name));
        gpuSec.appendChild(gpuHdr);

        var gpuTrack = document.createElement('div');
        gpuTrack.className = 'hw-bar-track';
        var gpuFill = document.createElement('div');
        gpuFill.className = 'hw-bar-fill ' + gpu.status;
        gpuFill.style.width = gpu.usage_pct + '%';
        gpuTrack.appendChild(gpuFill);
        gpuSec.appendChild(gpuTrack);

        var gpuDetail = document.createElement('div');
        gpuDetail.className = 'hw-detail';
        gpuDetail.textContent = gpu.vram_used_gb + '/' + gpu.vram_total_gb + 'GB VRAM used'
            + (gpu.occupied_by ? ' \u2014 ' + gpu.occupied_by : '')
            + ' \u00B7 ' + gpu.vram_free_gb + 'GB free';
        gpuSec.appendChild(gpuDetail);
        hwOverview.appendChild(gpuSec);

        // Divider
        var div1 = document.createElement('div');
        div1.className = 'hw-divider';
        hwOverview.appendChild(div1);
    }

    // CPU / RAM section
    var cpuSec = document.createElement('div');
    cpuSec.className = 'hw-section';
    var cpuHdr = document.createElement('div');
    cpuHdr.className = 'hw-section-hdr';
    var cpuDot = document.createElement('span');
    cpuDot.className = 'hw-dot ' + ram.status;
    cpuHdr.appendChild(cpuDot);
    cpuHdr.appendChild(document.createTextNode('CPU / SYSTEM RAM'));
    cpuSec.appendChild(cpuHdr);

    var cpuTrack = document.createElement('div');
    cpuTrack.className = 'hw-bar-track';
    var cpuFill = document.createElement('div');
    cpuFill.className = 'hw-bar-fill ' + (ram.status === 'red' ? 'red' : ram.status === 'amber' ? 'amber' : 'blue');
    cpuFill.style.width = ram.usage_pct + '%';
    cpuTrack.appendChild(cpuFill);
    cpuSec.appendChild(cpuTrack);

    // Count CPU-loaded models
    var cpuModels = (ctx.models || []).filter(function(m) { return m.loaded && !m.on_gpu; });
    var cpuUsed = 0;
    cpuModels.forEach(function(m) { cpuUsed += m.size_gb; });

    var cpuDetail = document.createElement('div');
    cpuDetail.className = 'hw-detail';
    cpuDetail.textContent = (ram.total_gb - ram.available_gb).toFixed(0) + '/' + ram.total_gb + 'GB used'
        + ' \u00B7 ' + ram.available_gb + 'GB free'
        + ' \u00B7 ' + cpuModels.length + ' models (' + cpuUsed.toFixed(0) + 'GB)';
    cpuSec.appendChild(cpuDetail);
    hwOverview.appendChild(cpuSec);

    // Media generation — local services + cloud contractors
    var mediaContractors = ctx.media_contractors || [];
    var mediaSec = document.getElementById('agent-form-media-section');
    if (mediaContractors.length > 0) {
        mediaSec.style.display = 'block';
        while (mediaSec.firstChild) mediaSec.removeChild(mediaSec.firstChild);
        var mhdr = document.createElement('div');
        mhdr.className = 'media-section-hdr';
        mhdr.textContent = 'Media Generation';
        mediaSec.appendChild(mhdr);

        // Split into local vs cloud
        var localProviders = mediaContractors.filter(function(mc) { return mc.location === 'local'; });
        var cloudProviders = mediaContractors.filter(function(mc) { return mc.location !== 'local'; });

        function _renderMediaRow(mc, container) {
            var isLocal = mc.location === 'local';
            var wrapper = document.createElement('div');

            var row = document.createElement('div');
            row.className = 'media-provider-row' + (isLocal ? ' local' : '');

            // Dot: green=ready, yellow=degraded (CPU fallback), red=offline, gray=unconfigured
            var dotClass = 'unconfigured';
            if (isLocal) {
                if (!mc.service_online) dotClass = 'offline';
                else if (!mc.gpu_available) dotClass = 'degraded';
                else dotClass = 'configured';
            } else {
                dotClass = (mc.has_key && mc.is_active) ? 'configured' : 'unconfigured';
            }
            var mDot = document.createElement('span');
            mDot.className = 'mp-dot ' + dotClass;
            row.appendChild(mDot);

            var mName = document.createElement('span');
            mName.className = 'mp-name';
            mName.textContent = mc.display_name;
            row.appendChild(mName);

            var mCost = document.createElement('span');
            mCost.className = 'mp-cost';
            mCost.textContent = mc.is_free ? 'free' : 'paid';
            row.appendChild(mCost);

            var mStatus = document.createElement('span');
            if (isLocal) {
                if (!mc.service_online) {
                    mStatus.className = 'mp-status inactive';
                    mStatus.textContent = 'Container offline';
                } else {
                    var mdl = (mc.models && mc.models[0]) ? mc.models[0].name : '';
                    mStatus.className = 'mp-status active';
                    mStatus.textContent = mdl;
                }
            } else {
                mStatus.className = 'mp-status ' + ((mc.has_key && mc.is_active) ? 'active' : 'inactive');
                mStatus.textContent = (mc.has_key && mc.is_active) ? '\u2713 configured' : 'Configure in Contractors';
            }
            row.appendChild(mStatus);
            wrapper.appendChild(row);

            // VRAM conflict note for local providers
            if (isLocal && mc.service_online && !mc.gpu_available && mc.cpu_fallback) {
                var hwNote = document.createElement('div');
                hwNote.className = 'mp-hw-note';
                var occupant = mc.gpu_occupied_by || 'another model';
                hwNote.textContent = '\u26A0 GPU occupied by ' + occupant + ' \u2014 will run on CPU (~2-5 min)';
                wrapper.appendChild(hwNote);
            } else if (isLocal && !mc.service_online) {
                var hwNote2 = document.createElement('div');
                hwNote2.className = 'mp-hw-note';
                hwNote2.style.color = '#FF4444';
                hwNote2.textContent = 'Start container: docker compose up -d archie_diffuser';
                wrapper.appendChild(hwNote2);
            }

            container.appendChild(wrapper);
        }

        // Render local group
        if (localProviders.length > 0) {
            var localLbl = document.createElement('div');
            localLbl.className = 'media-cap-label';
            localLbl.textContent = 'Local Generation';
            mediaSec.appendChild(localLbl);
            localProviders.forEach(function(mc) { _renderMediaRow(mc, mediaSec); });
        }

        // Render cloud group
        if (cloudProviders.length > 0) {
            var cloudLbl = document.createElement('div');
            cloudLbl.className = 'media-cap-label';
            cloudLbl.textContent = 'Cloud APIs';
            mediaSec.appendChild(cloudLbl);
            cloudProviders.forEach(function(mc) { _renderMediaRow(mc, mediaSec); });
        }
    }

    // Build model dropdown
    var dropdown = document.getElementById('agent-form-model-dropdown');
    var modelInput = document.getElementById('agent-form-model');
    dropdown.textContent = '';

    var models = ctx.models || [];
    var gpu = ctx.gpu || {};

    if (models.length === 0) {
        var emptyEl = document.createElement('div');
        emptyEl.className = 'model-dd-empty';
        emptyEl.textContent = 'No models found';
        dropdown.appendChild(emptyEl);
    } else {
        // Split models into groups
        var gpuModels = models.filter(function(m) { return m.loaded && m.on_gpu; });
        var cpuModels = models.filter(function(m) { return m.loaded && !m.on_gpu; });
        var availModels = models.filter(function(m) { return !m.loaded; });

        function _addDdGroup(label, icon, cssClass) {
            var g = document.createElement('div');
            g.className = 'model-dd-group ' + cssClass;
            g.textContent = icon + ' ' + label;
            dropdown.appendChild(g);
        }

        function _addDdItem(model) {
            var item = document.createElement('div');
            item.className = 'model-dd-item';
            item.setAttribute('data-model', model.name);

            var dot = document.createElement('span');
            dot.className = 'dd-dot ' + (model.loaded ? 'loaded' : 'swap');
            item.appendChild(dot);

            var nameEl = document.createElement('span');
            nameEl.className = 'dd-name';
            var cleanName = model.name.replace(':latest', '');
            var catInfo = (window._modelCatalog || {})[model.name] || (window._modelCatalog || {})[cleanName];
            if (catInfo && catInfo.display_name) {
                nameEl.textContent = catInfo.display_name + (catInfo.parameter_size ? ' (' + catInfo.parameter_size + ')' : '');
                var subName = document.createElement('span');
                subName.className = 'dd-model-id';
                subName.textContent = cleanName;
                nameEl.appendChild(subName);
            } else {
                nameEl.textContent = cleanName;
            }
            if (catInfo && catInfo.description) {
                item.title = catInfo.description;
                item.setAttribute('data-catalog-name', (catInfo.display_name || '').toLowerCase());
            }
            item.appendChild(nameEl);

            // HW badge — show current location + GPU eligibility
            var hwTag = document.createElement('span');
            var isGpu = model.on_gpu && model.loaded;
            var vramTotalGb = (ctx.gpu || {}).vram_total_gb || 0;
            var couldFitGpu = vramTotalGb > 0 && model.size_gb <= vramTotalGb;
            if (isGpu) {
                hwTag.className = 'hw-tag gpu';
                hwTag.textContent = 'GPU';
            } else if (couldFitGpu) {
                hwTag.className = 'hw-tag gpu-eligible';
                hwTag.textContent = 'GPU \u2713';
                hwTag.title = 'Could run on GPU (' + model.size_gb + 'GB fits in ' + vramTotalGb + 'GB VRAM)';
            } else {
                hwTag.className = 'hw-tag cpu';
                hwTag.textContent = 'CPU';
                if (vramTotalGb > 0) hwTag.title = 'Too large for GPU (' + model.size_gb + 'GB > ' + vramTotalGb + 'GB VRAM)';
            }
            item.appendChild(hwTag);

            // Agents using this model
            var agents = ctx.model_agents[model.name] || ctx.model_agents[model.name.replace(':latest', '')] || [];
            if (agents.length > 0) {
                var agEl = document.createElement('span');
                agEl.className = 'dd-agents';
                agEl.textContent = agents.join(', ');
                agEl.title = 'Used by: ' + agents.join(', ');
                item.appendChild(agEl);
            }

            var sizeEl = document.createElement('span');
            sizeEl.className = 'dd-size';
            sizeEl.textContent = model.size_gb + 'GB';
            item.appendChild(sizeEl);

            item.addEventListener('click', function() {
                modelInput.value = model.name.replace(':latest', '');
                document.getElementById('agent-form-model-value').value = model.name;
                dropdown.style.display = 'none';
                // Highlight selected
                dropdown.querySelectorAll('.model-dd-item').forEach(function(r) { r.classList.remove('selected'); });
                item.classList.add('selected');
                _showModelInfo(model, ctx);
            });

            dropdown.appendChild(item);
        }

        var vramTotalGb = (gpu.vram_total_gb || 0);

        // GPU eligible = fits in VRAM (whether currently on GPU, CPU, or not loaded)
        var cpuGpuEligible = cpuModels.filter(function(m) { return vramTotalGb > 0 && m.size_gb <= vramTotalGb; });
        var cpuOnly = cpuModels.filter(function(m) { return !(vramTotalGb > 0 && m.size_gb <= vramTotalGb); });
        var availGpuEligible = availModels.filter(function(m) { return vramTotalGb > 0 && m.size_gb <= vramTotalGb; });
        var availCpuOnly = availModels.filter(function(m) { return !(vramTotalGb > 0 && m.size_gb <= vramTotalGb); });

        // Group 1: Currently on GPU
        if (gpuModels.length > 0) {
            var vramInfo = gpu.available ? ' \u2014 ' + (gpu.vram_used_gb || 0) + '/' + vramTotalGb + 'GB VRAM' : '';
            _addDdGroup('On GPU (' + gpuModels.length + ')' + vramInfo, '\u26A1', 'gpu');
            gpuModels.forEach(_addDdItem);
        }

        // Group 2: Loaded on CPU but could run on GPU
        if (cpuGpuEligible.length > 0) {
            _addDdGroup('CPU \u2014 GPU eligible (' + cpuGpuEligible.length + ') \u2014 fits in ' + vramTotalGb + 'GB VRAM', '\u26A1', 'gpu');
            cpuGpuEligible.forEach(_addDdItem);
        }

        // Group 3: Loaded on CPU, too large for GPU
        if (cpuOnly.length > 0) {
            var ramInfo = ' \u2014 ' + (ctx.ram.available_gb || 0) + 'GB free';
            _addDdGroup('CPU only (' + cpuOnly.length + ')' + ramInfo, '\uD83D\uDCBB', 'cpu');
            cpuOnly.forEach(_addDdItem);
        }

        // Group 4: Not loaded, GPU eligible
        if (availGpuEligible.length > 0) {
            _addDdGroup('Available \u2014 GPU eligible (' + availGpuEligible.length + ')', '\u23F3', 'avail');
            availGpuEligible.forEach(_addDdItem);
        }

        // Group 5: Not loaded, CPU only
        if (availCpuOnly.length > 0) {
            _addDdGroup('Available \u2014 CPU only (' + availCpuOnly.length + ')', '\u23F3', 'avail');
            availCpuOnly.forEach(_addDdItem);
        }
    }

    // Show dropdown on focus/click
    modelInput.addEventListener('focus', function() {
        dropdown.style.display = 'block';
    });

    // Filter on typing
    modelInput.addEventListener('input', function() {
        dropdown.style.display = 'block';
        var q = modelInput.value.toLowerCase();
        var hasVisible = false;
        dropdown.querySelectorAll('.model-dd-item').forEach(function(item) {
            var name = (item.getAttribute('data-model') || '').toLowerCase();
            var catalogName = (item.getAttribute('data-catalog-name') || '').toLowerCase();
            var show = !q || name.indexOf(q) >= 0 || catalogName.indexOf(q) >= 0;
            item.style.display = show ? '' : 'none';
            if (show) hasVisible = true;
        });
        // Show/hide group headers based on visible children
        dropdown.querySelectorAll('.model-dd-group').forEach(function(grp) {
            var next = grp.nextElementSibling;
            var groupHasVisible = false;
            while (next && !next.classList.contains('model-dd-group')) {
                if (next.style.display !== 'none') groupHasVisible = true;
                next = next.nextElementSibling;
            }
            grp.style.display = groupHasVisible ? '' : 'none';
        });
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', function _closeDD(e) {
        if (!modelInput.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.style.display = 'none';
        }
    });

    // If editing, pre-select current model
    var currentVal = modelInput.value;
    if (currentVal) {
        dropdown.querySelectorAll('.model-dd-item').forEach(function(item) {
            var name = item.getAttribute('data-model') || '';
            if (name === currentVal || name.replace(':latest', '') === currentVal) {
                item.classList.add('selected');
            }
        });
    }
}

function _makeModelRow(model, ctx) {
    var row = document.createElement('div');
    row.className = 'agent-form-model-row';
    row.setAttribute('data-model', model.name);

    var dot = document.createElement('span');
    dot.className = 'model-status-dot ' + (model.loaded ? 'loaded' : 'swap');
    dot.title = model.loaded ? 'Loaded in RAM' : 'Not loaded \u2014 cold-load required';
    row.appendChild(dot);

    var nameEl = document.createElement('span');
    nameEl.className = 'model-name';
    nameEl.textContent = model.name.replace(':latest', '');
    row.appendChild(nameEl);

    // Hardware badge (GPU/CPU)
    var hwTag = document.createElement('span');
    var isGpu = model.on_gpu && model.loaded;
    hwTag.className = 'hw-tag ' + (isGpu ? 'gpu' : 'cpu');
    hwTag.textContent = isGpu ? 'GPU' : 'CPU';
    if (isGpu && model.vram_gb) hwTag.textContent += ' ' + model.vram_gb + 'GB';
    row.appendChild(hwTag);

    // Agents using this model
    var agents = ctx.model_agents[model.name] || ctx.model_agents[model.name.replace(':latest', '')] || [];
    if (agents.length > 0) {
        var agentsEl = document.createElement('span');
        agentsEl.className = 'model-agents';
        agentsEl.textContent = agents.join(', ');
        agentsEl.title = 'Used by: ' + agents.join(', ');
        row.appendChild(agentsEl);
    }

    var sizeEl = document.createElement('span');
    sizeEl.className = 'model-size';
    sizeEl.textContent = model.size_gb + 'GB';
    if (model.parameter_size) sizeEl.textContent += ' \u00B7 ' + model.parameter_size;
    row.appendChild(sizeEl);

    row.addEventListener('click', function() {
        // Select this model
        document.getElementById('agent-form-model').value = model.name;
        // Highlight selected row
        var picker = document.getElementById('agent-form-model-picker');
        picker.querySelectorAll('.agent-form-model-row').forEach(function(r) { r.classList.remove('selected'); });
        row.classList.add('selected');
        // Show model info
        _showModelInfo(model, ctx);
    });

    return row;
}

var _agentFormNumGpu = 0;  // 0=CPU, 99=GPU — set by hardware toggle

function _showModelInfo(model, ctx) {
    var info = document.getElementById('agent-form-model-info');
    info.style.display = 'block';
    while (info.firstChild) info.removeChild(info.firstChild);

    var vramTotalGb = (ctx.gpu || {}).vram_total_gb || 0;
    var isOnGpu = model.on_gpu && model.loaded;
    var couldFitGpu = vramTotalGb > 0 && model.size_gb <= vramTotalGb;

    // Default: keep current hw, or CPU for new
    _agentFormNumGpu = isOnGpu ? 99 : 0;

    // Model summary line
    var summaryParts = [];
    summaryParts.push(model.name.replace(':latest', ''));
    if (model.parameter_size) summaryParts.push(model.parameter_size);
    summaryParts.push(model.size_gb + 'GB');
    summaryParts.push(model.loaded ? '\u2705 Loaded' : '\u26A0 Not loaded');
    var summaryEl = document.createElement('div');
    summaryEl.textContent = summaryParts.join(' \u2022 ');
    info.appendChild(summaryEl);

    // GPU/CPU hardware toggle (for GPU-eligible models)
    if (couldFitGpu || isOnGpu) {
        var toggleRow = document.createElement('div');
        toggleRow.style.cssText = 'display:flex;align-items:center;gap:8px;margin-top:5px;';

        var lbl = document.createElement('span');
        lbl.textContent = 'Load on:';
        lbl.style.cssText = 'font-weight:600;color:var(--archie-text-secondary);';
        toggleRow.appendChild(lbl);

        var gpuBtn = document.createElement('button');
        gpuBtn.type = 'button';
        gpuBtn.textContent = '\u26A1 GPU (' + vramTotalGb + 'GB VRAM)';
        gpuBtn.className = 'hw-toggle-btn' + (isOnGpu ? ' active' : '');
        gpuBtn.style.cssText = 'padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;border:1px solid rgba(255,170,0,0.3);background:' + (isOnGpu ? 'rgba(255,170,0,0.2)' : 'transparent') + ';color:#FFD700;';

        var cpuBtn = document.createElement('button');
        cpuBtn.type = 'button';
        cpuBtn.textContent = '\uD83D\uDCBB CPU (128GB RAM)';
        cpuBtn.className = 'hw-toggle-btn' + (!isOnGpu ? ' active' : '');
        cpuBtn.style.cssText = 'padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;border:1px solid rgba(50,205,50,0.3);background:' + (!isOnGpu ? 'rgba(50,205,50,0.2)' : 'transparent') + ';color:#32CD32;';

        gpuBtn.onclick = function() {
            _agentFormNumGpu = 99;
            gpuBtn.style.background = 'rgba(255,170,0,0.2)';
            cpuBtn.style.background = 'transparent';
        };
        cpuBtn.onclick = function() {
            _agentFormNumGpu = 0;
            cpuBtn.style.background = 'rgba(50,205,50,0.2)';
            gpuBtn.style.background = 'transparent';
        };

        toggleRow.appendChild(gpuBtn);
        toggleRow.appendChild(cpuBtn);
        info.appendChild(toggleRow);
    } else {
        // CPU only — too large for GPU
        var cpuNote = document.createElement('div');
        cpuNote.style.cssText = 'margin-top:3px;color:var(--archie-text-muted);';
        cpuNote.textContent = '\uD83D\uDCBB CPU only \u2014 ' + model.size_gb + 'GB exceeds ' + vramTotalGb + 'GB VRAM';
        info.appendChild(cpuNote);
        _agentFormNumGpu = 0;
    }

    // Agents using this model
    var agents = ctx.model_agents[model.name] || ctx.model_agents[model.name.replace(':latest', '')] || [];
    if (agents.length > 0) {
        var agNote = document.createElement('div');
        agNote.style.cssText = 'margin-top:3px;color:var(--archie-text-muted);';
        agNote.textContent = 'Shared with: ' + agents.join(', ');
        info.appendChild(agNote);
    } else if (model.loaded) {
        var orphanNote = document.createElement('div');
        orphanNote.style.cssText = 'margin-top:3px;color:#FFD700;';
        orphanNote.textContent = '\u26A0 Not assigned to any agent \u2014 will be auto-unloaded if you choose this model';
        info.appendChild(orphanNote);
    }

    // Swap limit check
    if (!model.loaded) {
        var swapBadges = document.querySelectorAll('.crew-llm-badge.swap');
        var currentSwap = swapBadges ? swapBadges.length : 0;
        if (currentSwap >= _agentFormMaxSwap) {
            var swapNote = document.createElement('div');
            swapNote.style.cssText = 'margin-top:3px;color:#FF4444;font-weight:600;';
            swapNote.textContent = '\u26D4 Swap limit reached (' + currentSwap + '/' + _agentFormMaxSwap + ')';
            info.appendChild(swapNote);
            info.style.borderColor = 'rgba(255,68,68,0.3)';
            info.style.background = 'rgba(255,68,68,0.08)';
        } else {
            info.style.borderColor = 'rgba(255,170,0,0.2)';
            info.style.background = 'rgba(255,170,0,0.08)';
        }
    } else {
        info.style.borderColor = 'rgba(139,92,246,0.15)';
        info.style.background = 'rgba(139,92,246,0.08)';
    }
}

function closeAgentFormModal() {
    document.getElementById('agent-form-modal').classList.remove('active');
    // Clean up swap warning if present
    var swapWarns = document.querySelectorAll('[data-swap-warn]');
    swapWarns.forEach(function(el) { el.remove(); });
}

function saveAgent() {
    var id = document.getElementById('agent-form-id').value;
    var modelVal = document.getElementById('agent-form-model-value').value || document.getElementById('agent-form-model').value;

    // Swap limit check (only for new agents or model changes)
    if (_agentFormContext && modelVal) {
        var loadedSet = new Set();
        (_agentFormContext.models || []).forEach(function(m) {
            if (m.loaded) { loadedSet.add(m.name); loadedSet.add(m.name.replace(':latest', '')); }
        });
        var isLoaded = loadedSet.has(modelVal) || loadedSet.has(modelVal.replace(':latest', ''));
        if (!isLoaded && !id) {
            // Count current swap agents
            var swapBadges = document.querySelectorAll('.crew-llm-badge.swap');
            var currentSwap = swapBadges ? swapBadges.length : 0;
            if (currentSwap >= _agentFormMaxSwap) {
                if (!confirm('Swap limit reached (' + currentSwap + '/' + _agentFormMaxSwap + ' agents in SWAP state).\n\nAdding another swap agent risks cold-load contention and model eviction.\n\nProceed anyway?')) {
                    return;
                }
            }
        }
    }

    var payload = {
        first_name: document.getElementById('agent-form-first').value,
        last_name: document.getElementById('agent-form-last').value,
        title: document.getElementById('agent-form-title-input').value,
        department: document.getElementById('agent-form-dept').value,
        model: modelVal,
        worker_type: document.getElementById('agent-form-worker').value,
        bio: document.getElementById('agent-form-bio').value,
        num_gpu: _agentFormNumGpu || 0,
    };
    var nameVal = document.getElementById('agent-form-name').value.trim();
    if (nameVal) payload.name = nameVal;
    var prompt = document.getElementById('agent-form-prompt').value;
    if (prompt) payload.system_prompt = prompt;

    var url = id ? '/tools/bridge/api/agents/' + parseInt(id) : '/tools/bridge/api/agents';
    var method = id ? 'PUT' : 'POST';

    // Disable save button during request (model load can take a while)
    var saveBtn = document.getElementById('agent-form-save-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving...'; }

    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Agent'; }
        if (data.success) {
            closeAgentFormModal();
            // Invalidate profile cache for edited agent
            if (id) delete _profileCache[parseInt(id)];
            loadCrewManifest();
            // Show model operations feedback if any
            if (data.model_ops && data.model_ops.length > 0) {
                var msg = 'Model operations:\n' + data.model_ops.join('\n');
                setTimeout(function() { alert(msg); }, 300);
            }
        } else {
            alert(data.error || 'Failed to save');
        }
    })
    .catch(function() {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save Agent'; }
        alert('Request failed — model load may have timed out');
    });
}

// === Skills Management ===
function addSkill(agentId) {
    var nameEl = document.getElementById('add-skill-name');
    var levelEl = document.getElementById('add-skill-level');
    if (!nameEl || !nameEl.value.trim()) return;
    fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_name: nameEl.value.trim(), proficiency_level: parseInt(levelEl.value) })
    }).then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) openAgentProfile(agentId);
    });
}

function removeSkill(agentId, skillId) {
    fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/skills/' + skillId, { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) openAgentProfile(agentId);
        });
}

// === Training / Lounge Button UX ===
function populateTrainingLoungeSelects(crew) {
    // Separate agents by status
    var active = [], training = [], resting = [];
    (crew || []).forEach(function(a) {
        if (a.status === 'training') training.push(a);
        else if (a.status === 'resting') resting.push(a);
        else active.push(a);
    });

    // Render training agents list
    var trainList = document.getElementById('training-agents-list');
    if (trainList) {
        if (training.length === 0) {
            trainList.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No agents in training</span>';
        } else {
            var html = '';
            training.forEach(function(a) {
                html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);font-size:0.75rem;">';
                html += '<span>' + (a.full_name || a.name || '').split(' ')[0] + '</span>';
                html += '<button onclick="returnFromLounge(' + parseInt(a.id) + ')" style="background:rgba(0,255,65,0.15);border:1px solid rgba(0,255,65,0.3);color:#00ff41;padding:2px 6px;border-radius:3px;font-size:0.6rem;cursor:pointer;">Return to Duty</button>';
                html += '</div>';
            });
            trainList.innerHTML = html;
        }
    }

}

function sendToLounge() {
    var sel = document.getElementById('lounge-agent-select');
    if (!sel || !sel.value) return;
    var reasonEl = document.getElementById('lounge-reason-input');
    var reason = (reasonEl && reasonEl.value.trim()) ? reasonEl.value.trim() : 'rest';
    fetch('/tools/bridge/api/agents/' + parseInt(sel.value) + '/send-to-lounge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason, rest_type: 'voluntary' })
    }).then(function(r) { return r.json(); })
    .then(function() {
        sel.value = '';
        var chipRow = document.getElementById('lounge-agent-chips');
        if (chipRow) { var s = chipRow.querySelector('.training-chip.selected'); if (s) s.classList.remove('selected'); }
        if (reasonEl) reasonEl.value = '';
        loadCrewManifest();
        if (typeof loadLoungeTab === 'function') loadLoungeTab();
    });
}

function sendToLoungeById(agentId) {
    fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/send-to-lounge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'rest', rest_type: 'voluntary' })
    }).then(function(r) { return r.json(); })
    .then(function() {
        loadCrewManifest();
        if (typeof loadLoungeTab === 'function') loadLoungeTab();
    });
}

function returnFromLounge(agentId) {
    fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/return-from-lounge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    }).then(function(r) { return r.json(); })
    .then(function() {
        loadCrewManifest();
        if (typeof loadLoungeTab === 'function') loadLoungeTab();
    });
}

// ============================================================================
// TRAINING TAB — Skill Gaps, Assignments, Progress, History
// ============================================================================

var _trainingHoursPerLevel = {2: 1, 3: 2, 4: 4, 5: 8};
var _trainingHistoryLoaded = false;

function _getTrainingTierInfo(level) {
    if (level <= 2) return {tier: 'novice', label: 'Basic', tooltip: 'Basic instructions — standard local model'};
    if (level === 3) return {tier: 'intermediate', label: 'Enhanced', tooltip: 'Enhanced techniques — deeper context + 3 learning cards'};
    if (level === 4) return {tier: 'advanced-cloud', label: 'Cloud Access', tooltip: 'Expert strategies — free cloud model for complex tasks + 4 learning cards'};
    return {tier: 'advanced-premium', label: 'Premium', tooltip: 'Expert strategies — premium model for complex tasks + 5 learning cards'};
}

function loadTrainingTab() {
    loadTrainingRecommendations();
    loadActiveTraining();
    populateTrainingAgentSelect();
}

async function populateTrainingAgentSelect() {
    var container = document.getElementById('training-agent-chips');
    var hiddenInput = document.getElementById('training-agent-select');
    if (!container || !hiddenInput) return;
    try {
        var resp = await fetch('/tools/bridge/api/bridge/crew/manifest');
        var data = await resp.json();
        if (!data.success) return;
        container.textContent = '';
        hiddenInput.value = '';
        var crew = data.crew || [];
        if (crew.length === 0) {
            var empty = document.createElement('span');
            empty.className = 'briefing-muted';
            empty.style.fontSize = '0.75rem';
            empty.textContent = 'No agents available';
            container.appendChild(empty);
            return;
        }
        crew.forEach(function(agent) {
            var firstName = (agent.full_name || agent.name || 'agent').split(' ')[0];
            var avatarSlug = firstName.toLowerCase();
            var dicebearFallback = 'https://api.dicebear.com/9.x/adventurer/svg?seed=' + encodeURIComponent(firstName) + '&backgroundColor=transparent';

            var chip = document.createElement('div');
            chip.className = 'training-chip';
            chip.dataset.agentId = agent.id;

            var img = document.createElement('img');
            img.className = 'training-chip-avatar';
            img.src = '/static/avatars/' + avatarSlug + '.svg';
            img.alt = firstName;
            img.onerror = function() { this.onerror = null; this.src = dicebearFallback; };
            chip.appendChild(img);

            var nameSpan = document.createElement('span');
            nameSpan.className = 'training-chip-name';
            nameSpan.textContent = firstName;
            chip.appendChild(nameSpan);

            var stationSpan = document.createElement('span');
            stationSpan.className = 'training-chip-station';
            stationSpan.textContent = agent.station || '';
            chip.appendChild(stationSpan);

            chip.addEventListener('click', function() {
                var wasSelected = chip.classList.contains('selected');
                var prev = container.querySelector('.training-chip.selected');
                if (prev) prev.classList.remove('selected');
                if (wasSelected) {
                    hiddenInput.value = '';
                } else {
                    chip.classList.add('selected');
                    hiddenInput.value = agent.id;
                }
                hiddenInput.dispatchEvent(new Event('change'));
            });

            container.appendChild(chip);
        });
    } catch (e) {
        console.error('populateTrainingAgentSelect error:', e);
    }
}

// When agent is selected, populate skill chips with their current skills
document.addEventListener('DOMContentLoaded', function() {
    var agentSel = document.getElementById('training-agent-select');
    if (agentSel) {
        agentSel.addEventListener('change', async function() {
            var skillContainer = document.getElementById('training-skill-chips');
            var skillInput = document.getElementById('training-skill-select');
            if (!skillContainer || !skillInput) return;
            var agentId = agentSel.value;
            if (!agentId) {
                skillContainer.textContent = '';
                var emptySpan = document.createElement('span');
                emptySpan.className = 'training-skill-empty';
                emptySpan.textContent = 'Select an agent first';
                skillContainer.appendChild(emptySpan);
                skillInput.value = '';
                _resetTrainingLevelPills();
                return;
            }
            try {
                skillContainer.textContent = '';
                skillInput.value = '';
                _resetTrainingLevelPills();
                var resp = await fetch('/tools/bridge/api/agents/' + parseInt(agentId) + '/profile');
                var data = await resp.json();
                var skills = (data.profile && data.profile.skills) || data.skills || [];
                if (!data.success || skills.length === 0) {
                    var noSkills = document.createElement('span');
                    noSkills.className = 'training-skill-empty';
                    noSkills.textContent = 'No skills found';
                    skillContainer.appendChild(noSkills);
                    return;
                }
                skills.forEach(function(sk) {
                    var chip = document.createElement('div');
                    chip.className = 'training-skill-chip';
                    chip.dataset.skill = sk.skill_name;
                    chip.dataset.currentLevel = sk.proficiency_level || 1;

                    var nameSpan = document.createElement('span');
                    nameSpan.textContent = sk.skill_name;
                    chip.appendChild(nameSpan);

                    var lvlBadge = document.createElement('span');
                    lvlBadge.className = 'skill-chip-lvl';
                    lvlBadge.textContent = 'Lv' + (sk.proficiency_level || 1);
                    chip.appendChild(lvlBadge);

                    var skTier = _getTrainingTierInfo(sk.proficiency_level || 1);
                    var tierLabel = document.createElement('span');
                    tierLabel.className = 'training-tier-badge';
                    tierLabel.dataset.tier = skTier.tier;
                    tierLabel.title = skTier.tooltip;
                    tierLabel.textContent = skTier.label;
                    chip.appendChild(tierLabel);

                    if (sk.degradation_count && sk.degradation_count > 0) {
                        var degBadge = document.createElement('span');
                        degBadge.className = 'training-degradation-count';
                        degBadge.title = sk.degradation_count + ' degradation(s)';
                        degBadge.textContent = sk.degradation_count;
                        chip.appendChild(degBadge);
                    }

                    chip.addEventListener('click', function() {
                        var wasSelected = chip.classList.contains('selected');
                        var prev = skillContainer.querySelector('.training-skill-chip.selected');
                        if (prev) prev.classList.remove('selected');
                        if (wasSelected) {
                            skillInput.value = '';
                            _resetTrainingLevelPills();
                        } else {
                            chip.classList.add('selected');
                            skillInput.value = sk.skill_name;
                            _updateTrainingLevelPills(parseInt(sk.proficiency_level) || 1);
                        }
                    });
                    skillContainer.appendChild(chip);
                });
            } catch (e) {
                console.error('Load agent skills error:', e);
                skillContainer.textContent = '';
                var errSpan = document.createElement('span');
                errSpan.className = 'training-skill-empty';
                errSpan.textContent = 'Error loading skills';
                skillContainer.appendChild(errSpan);
            }
        });
    }

    // Level pill click handlers
    var levelPills = document.querySelectorAll('.training-level-pill');
    var targetInput = document.getElementById('training-target-select');
    levelPills.forEach(function(pill) {
        pill.addEventListener('click', function() {
            if (pill.classList.contains('disabled')) return;
            var wasSelected = pill.classList.contains('selected');
            levelPills.forEach(function(p) { p.classList.remove('selected'); });
            if (wasSelected) {
                if (targetInput) targetInput.value = '';
            } else {
                pill.classList.add('selected');
                if (targetInput) targetInput.value = pill.dataset.level;
            }
        });
    });
});

// Reset all level pills to unselected + enabled
function _resetTrainingLevelPills() {
    var pills = document.querySelectorAll('.training-level-pill');
    var targetInput = document.getElementById('training-target-select');
    pills.forEach(function(p) { p.classList.remove('selected', 'disabled'); });
    if (targetInput) targetInput.value = '';
}

// Update level pills based on current skill level — disable levels at or below current
function _updateTrainingLevelPills(currentLevel) {
    var pills = document.querySelectorAll('.training-level-pill');
    var targetInput = document.getElementById('training-target-select');
    var autoSelected = false;
    pills.forEach(function(p) {
        var lvl = parseInt(p.dataset.level);
        p.classList.remove('selected', 'disabled');
        if (lvl <= currentLevel) {
            p.classList.add('disabled');
        } else if (!autoSelected) {
            // Auto-select the next level above current
            p.classList.add('selected');
            if (targetInput) targetInput.value = p.dataset.level;
            autoSelected = true;
        }
    });
}

async function assignTraining() {
    var agentSel = document.getElementById('training-agent-select');
    var skillSel = document.getElementById('training-skill-select');
    var targetSel = document.getElementById('training-target-select');
    if (!agentSel || !agentSel.value) return;
    if (!skillSel || !skillSel.value) return;
    if (!targetSel || !targetSel.value) return;

    try {
        var resp = await fetch('/tools/bridge/api/training/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent_id: parseInt(agentSel.value),
                skill_name: skillSel.value,
                target_proficiency: parseInt(targetSel.value)
            })
        });
        var data = await resp.json();
        if (data.success) {
            agentSel.value = '';
            var chipRow = document.getElementById('training-agent-chips');
            if (chipRow) { var sel = chipRow.querySelector('.training-chip.selected'); if (sel) sel.classList.remove('selected'); }
            // Reset skill chips
            var skillChips = document.getElementById('training-skill-chips');
            if (skillChips) { skillChips.textContent = ''; var e = document.createElement('span'); e.className = 'training-skill-empty'; e.textContent = 'Select an agent first'; skillChips.appendChild(e); }
            skillSel.value = '';
            // Reset level pills
            _resetTrainingLevelPills();
            loadActiveTraining();
            loadTrainingRecommendations();
        } else {
            console.error('assignTraining failed:', data.error);
        }
    } catch (e) {
        console.error('assignTraining error:', e);
    }
}

async function loadActiveTraining() {
    var container = document.getElementById('training-active-list');
    var countBadge = document.getElementById('training-active-count');
    if (!container) return;

    try {
        var resp = await fetch('/tools/bridge/api/training/active');
        var data = await resp.json();
        var training = data.training || [];

        if (countBadge) countBadge.textContent = training.length + ' active';

        if (training.length === 0) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No active training sessions</span>';
            return;
        }

        var html = '';
        training.forEach(function(t) {
            var current = t.current_proficiency || 1;
            var target = t.target_proficiency || 2;
            var hoursNeeded = _trainingHoursPerLevel[target] || 2;
            var hoursElapsed = t.hours_training || 0;
            var pct = Math.min(100, Math.round((hoursElapsed / hoursNeeded) * 100));
            var hoursLeft = Math.max(0, hoursNeeded - hoursElapsed);
            var displayName = t.first_name && t.last_name ? t.first_name + ' ' + t.last_name : (t.agent_name || 'Unknown');
            var tierInfo = _getTrainingTierInfo(target);
            var isDegraded = t.degradation_triggered === true;
            var borderColor = isDegraded ? 'rgba(255,60,60,0.25)' : 'rgba(255,170,0,0.15)';
            var bgColor = isDegraded ? 'rgba(255,60,60,0.05)' : 'rgba(255,170,0,0.05)';

            html += '<div style="padding:8px;margin-bottom:6px;background:' + bgColor + ';border:1px solid ' + borderColor + ';border-radius:6px;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">';
            html += '<span style="font-size:0.75rem;color:#ffaa00;font-weight:600;">' + escapeHtml(displayName) + '</span>';
            html += '<div style="display:flex;align-items:center;gap:4px;">';
            if (isDegraded) {
                html += '<span class="training-degraded-badge">DEGRADED</span>';
            }
            html += '<span class="training-tier-badge" data-tier="' + tierInfo.tier + '" title="' + tierInfo.tooltip + '">' + tierInfo.label + '</span>';
            html += '<button onclick="cancelTraining(' + parseInt(t.training_id) + ')" style="background:rgba(255,107,107,0.15);border:1px solid rgba(255,107,107,0.3);color:#ff6b6b;padding:1px 6px;border-radius:3px;font-size:0.6rem;cursor:pointer;">Cancel</button>';
            html += '</div></div>';
            html += '<div style="font-size:0.7rem;color:rgba(255,255,255,0.7);margin-bottom:4px;">';
            html += '<span>' + (t.skill_name || 'Unknown skill') + '</span>';
            html += ' &mdash; Level ' + current + ' &rarr; ' + target;
            html += '</div>';
            // Failure analysis (expandable, only for degradation-triggered training)
            if (isDegraded && t.failure_analysis) {
                var tId = parseInt(t.training_id);
                html += '<div class="training-failure-analysis" id="tfa-' + tId + '" onclick="this.classList.toggle(\'expanded\')" title="Click to expand">';
                html += escapeHtml(t.failure_analysis);
                html += '</div>';
            }
            // Progress bar
            html += '<div style="height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden;margin-bottom:3px;margin-top:4px;">';
            html += '<div style="height:100%;width:' + pct + '%;background:linear-gradient(90deg,' + (isDegraded ? '#ff6b6b,#ff9999' : '#ffaa00,#ffcc00') + ');border-radius:3px;transition:width 0.3s;"></div>';
            html += '</div>';
            html += '<div style="display:flex;justify-content:space-between;font-size:0.65rem;color:rgba(255,255,255,0.5);">';
            html += '<span>' + pct + '% complete</span>';
            html += '<span>' + hoursLeft.toFixed(1) + 'h remaining</span>';
            html += '</div>';
            html += '</div>';
        });
        container.innerHTML = html;
    } catch (e) {
        console.error('loadActiveTraining error:', e);
        if (container) container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading training</span>';
    }
}

async function cancelTraining(id) {
    try {
        var resp = await fetch('/tools/bridge/api/training/' + parseInt(id) + '/cancel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        var data = await resp.json();
        if (data.success) {
            loadActiveTraining();
        }
    } catch (e) {
        console.error('cancelTraining error:', e);
    }
}

async function loadTrainingRecommendations() {
    var container = document.getElementById('training-recommendations');
    var countBadge = document.getElementById('training-rec-count');
    if (!container) return;

    try {
        var [resp, crewResp] = await Promise.all([
            fetch('/tools/bridge/api/training/recommendations'),
            fetch('/tools/bridge/api/bridge/crew/manifest')
        ]);
        var data = await resp.json();
        var recs = data.recommendations || [];
        var nameMap = {};
        try {
            var crewData = await crewResp.json();
            (crewData.crew || []).forEach(function(a) { nameMap[a.id] = (a.full_name || a.name || '').split(' ')[0]; });
        } catch(e) {}

        if (countBadge) countBadge.textContent = recs.length;

        if (recs.length === 0) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No skill gaps detected &mdash; all agents performing well</span>';
            return;
        }

        var html = '';
        recs.forEach(function(r) {
            var displayName = nameMap[r.agent_id] || r.full_name || r.agent_name || 'Unknown';
            var skillName = r.skill_name || r.capability || 'Unknown';
            var currentLvl = r.current_proficiency || r.current_level || 1;
            var targetLvl = Math.min(5, currentLvl + 1);

            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05);">';
            html += '<div style="flex:1;">';
            html += '<div style="font-size:0.75rem;color:#ff6b6b;">' + displayName + '</div>';
            html += '<div style="font-size:0.65rem;color:rgba(255,255,255,0.5);">' + escapeHtml(skillName) + ' &mdash; ' + (r.failure_count || 0) + ' failures, Lv ' + currentLvl + '</div>';
            html += '</div>';
            html += '<button onclick="quickAssignTraining(' + parseInt(r.agent_id) + ',\'' + skillName.replace(/'/g, "\\'") + '\',' + targetLvl + ')" style="background:rgba(255,170,0,0.15);border:1px solid rgba(255,170,0,0.3);color:#ffaa00;padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;white-space:nowrap;">Train &rarr; Lv ' + targetLvl + '</button>';
            html += '</div>';
        });
        container.innerHTML = html;
    } catch (e) {
        console.error('loadTrainingRecommendations error:', e);
        if (container) container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading recommendations</span>';
    }
}

async function quickAssignTraining(agentId, skill, target) {
    try {
        var resp = await fetch('/tools/bridge/api/training/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent_id: parseInt(agentId),
                skill_name: skill,
                target_proficiency: parseInt(target)
            })
        });
        var data = await resp.json();
        if (data.success) {
            loadActiveTraining();
            loadTrainingRecommendations();
        } else {
            console.error('quickAssignTraining failed:', data.error);
        }
    } catch (e) {
        console.error('quickAssignTraining error:', e);
    }
}

function toggleTrainingHistory() {
    var body = document.getElementById('training-history-body');
    var toggle = document.getElementById('training-history-toggle');
    if (!body) return;
    var isHidden = body.style.display === 'none';
    body.style.display = isHidden ? 'block' : 'none';
    if (toggle) toggle.innerHTML = isHidden ? 'Hide &#9652;' : 'Show &#9662;';
    if (isHidden && !_trainingHistoryLoaded) {
        loadTrainingHistory();
    }
}

async function loadTrainingHistory() {
    var container = document.getElementById('training-history-list');
    if (!container) return;

    try {
        var resp = await fetch('/tools/bridge/api/training/history');
        var data = await resp.json();
        var history = data.history || [];
        _trainingHistoryLoaded = true;

        if (history.length === 0) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No training history yet</span>';
            return;
        }

        var html = '';
        history.forEach(function(h) {
            var displayName = h.full_name || h.agent_name || 'Unknown';
            var statusColor = h.status === 'completed' ? '#00ff41' : (h.status === 'cancelled' ? '#ff6b6b' : 'rgba(255,255,255,0.5)');
            var statusLabel = h.status === 'completed' ? 'Completed' : (h.status === 'cancelled' ? 'Cancelled' : (h.status || 'Unknown'));
            var dateStr = h.completed_at ? ArchieTime.date(h.completed_at) : '--';

            html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.05);">';
            html += '<div>';
            html += '<div style="font-size:0.7rem;">' + displayName + '</div>';
            html += '<div style="font-size:0.65rem;color:rgba(255,255,255,0.5);">' + (h.skill_name || '?') + ' Lv ' + (h.current_proficiency || '?') + ' &rarr; ' + (h.target_proficiency || '?') + '</div>';
            html += '</div>';
            html += '<div style="text-align:right;">';
            html += '<div style="font-size:0.65rem;color:' + statusColor + ';">' + statusLabel + '</div>';
            html += '<div style="font-size:0.6rem;color:rgba(255,255,255,0.4);">' + dateStr + '</div>';
            html += '</div>';
            html += '</div>';
        });
        container.innerHTML = html;
    } catch (e) {
        console.error('loadTrainingHistory error:', e);
        if (container) container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading history</span>';
    }
}

// ============================================================================
// LOUNGE TAB — Wellness Dashboard, Burnout Alerts, Rest Cards, History
// ============================================================================

var _restHistoryLoaded = false;

function loadLoungeTab() {
    loadWellnessSummary();
    loadLoungeAgents();
    populateLoungeAgentSelect();
}

async function populateLoungeAgentSelect() {
    var container = document.getElementById('lounge-agent-chips');
    var hiddenInput = document.getElementById('lounge-agent-select');
    if (!container || !hiddenInput) return;
    try {
        var resp = await fetch('/tools/bridge/api/bridge/crew/manifest');
        var data = await resp.json();
        if (!data.success) return;
        container.textContent = '';
        hiddenInput.value = '';
        var crew = (data.crew || []).filter(function(a) { return a.status !== 'resting'; });
        if (crew.length === 0) {
            var empty = document.createElement('span');
            empty.className = 'briefing-muted';
            empty.style.fontSize = '0.75rem';
            empty.textContent = 'No agents available';
            container.appendChild(empty);
            return;
        }
        crew.forEach(function(agent) {
            var firstName = (agent.full_name || agent.name || 'agent').split(' ')[0];
            var avatarSlug = firstName.toLowerCase();
            var dicebearFallback = 'https://api.dicebear.com/9.x/adventurer/svg?seed=' + encodeURIComponent(firstName) + '&backgroundColor=transparent';

            var chip = document.createElement('div');
            chip.className = 'training-chip';
            chip.dataset.agentId = agent.id;

            var img = document.createElement('img');
            img.className = 'training-chip-avatar';
            img.src = '/static/avatars/' + avatarSlug + '.svg';
            img.alt = firstName;
            img.onerror = function() { this.onerror = null; this.src = dicebearFallback; };
            chip.appendChild(img);

            var nameSpan = document.createElement('span');
            nameSpan.className = 'training-chip-name';
            nameSpan.textContent = firstName;
            chip.appendChild(nameSpan);

            var stationSpan = document.createElement('span');
            stationSpan.className = 'training-chip-station';
            stationSpan.textContent = agent.station || '';
            chip.appendChild(stationSpan);

            chip.addEventListener('click', function() {
                var wasSelected = chip.classList.contains('selected');
                var prev = container.querySelector('.training-chip.selected');
                if (prev) prev.classList.remove('selected');
                if (wasSelected) {
                    hiddenInput.value = '';
                } else {
                    chip.classList.add('selected');
                    hiddenInput.value = agent.id;
                }
            });

            container.appendChild(chip);
        });
    } catch (e) {
        console.error('populateLoungeAgentSelect error:', e);
    }
}

async function loadWellnessSummary() {
    var healthyEl = document.getElementById('wellness-healthy');
    var atRiskEl = document.getElementById('wellness-at-risk');
    var restingEl = document.getElementById('wellness-resting');
    var alertsEl = document.getElementById('burnout-alerts');
    try {
        var [resp, crewResp] = await Promise.all([
            fetch('/tools/bridge/api/lounge/wellness'),
            fetch('/tools/bridge/api/bridge/crew/manifest')
        ]);
        var data = await resp.json();
        var nameMap = {}, codeNameMap = {};
        try { var cd = await crewResp.json(); (cd.crew || []).forEach(function(c) { var fn = (c.full_name || c.name || '').split(' ')[0]; nameMap[c.id] = fn; codeNameMap[c.name] = fn; }); } catch(e) {}
        if (!data.success) return;

        var s = data.summary || {};
        if (healthyEl) healthyEl.querySelector('div').textContent = (s.healthy != null) ? s.healthy : 0;
        if (atRiskEl) atRiskEl.querySelector('div').textContent = (s.at_risk != null) ? s.at_risk : 0;
        if (restingEl) restingEl.querySelector('div').textContent = (s.resting != null) ? s.resting : 0;

        // Burnout alerts
        if (!alertsEl) return;
        var alerts = data.burnout_alerts || [];
        if (alerts.length === 0) {
            alertsEl.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No burnout risks detected</span>';
            return;
        }
        var html = '';
        alerts.forEach(function(a) {
            var stressColor = a.stress > 80 ? '#ef4444' : a.stress > 60 ? '#f59e0b' : '#00ff41';
            var energyColor = a.energy < 20 ? '#ef4444' : a.energy < 40 ? '#f59e0b' : '#00ff41';
            html += '<div style="padding:8px;margin-bottom:6px;background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.15);border-radius:6px;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">';
            html += '<span style="font-size:0.75rem;font-weight:600;color:#fbbf24;">' + (nameMap[a.agent_id] || codeNameMap[a.agent_name] || a.full_name || a.agent_name) + '</span>';
            html += '<button onclick="sendToLoungeById(' + parseInt(a.agent_id) + ')" style="background:rgba(139,92,246,0.15);border:1px solid rgba(139,92,246,0.3);color:#8b5cf6;padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;">Send to Rest</button>';
            html += '</div>';
            // Stress gauge
            html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">';
            html += '<span style="font-size:0.65rem;color:rgba(255,255,255,0.5);width:42px;">Stress</span>';
            html += '<div style="flex:1;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;">';
            html += '<div style="width:' + Math.min(a.stress || 0, 100) + '%;height:100%;background:' + stressColor + ';border-radius:2px;"></div>';
            html += '</div>';
            html += '<span style="font-size:0.6rem;color:' + stressColor + ';">' + (a.stress || 0) + '%</span>';
            html += '</div>';
            // Energy gauge
            html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px;">';
            html += '<span style="font-size:0.65rem;color:rgba(255,255,255,0.5);width:42px;">Energy</span>';
            html += '<div style="flex:1;height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden;">';
            html += '<div style="width:' + Math.min(a.energy || 0, 100) + '%;height:100%;background:' + energyColor + ';border-radius:2px;"></div>';
            html += '</div>';
            html += '<span style="font-size:0.6rem;color:' + energyColor + ';">' + (a.energy || 0) + '%</span>';
            html += '</div>';
            // Reasons
            if (a.reasons && a.reasons.length > 0) {
                html += '<div style="font-size:0.65rem;color:rgba(255,255,255,0.4);margin-top:2px;">' + a.reasons.join(', ') + '</div>';
            }
            html += '</div>';
        });
        alertsEl.innerHTML = html;
    } catch (e) {
        console.error('loadWellnessSummary error:', e);
        if (alertsEl) alertsEl.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading wellness data</span>';
    }
}

async function loadLoungeAgents() {
    var container = document.getElementById('lounge-agents-list');
    if (!container) return;
    try {
        var resp = await fetch('/tools/bridge/api/lounge');
        var data = await resp.json();
        if (!data.success) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading lounge</span>';
            return;
        }
        var agents = data.agents || [];
        if (agents.length === 0) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No agents currently resting</span>';
            return;
        }
        var html = '';
        agents.forEach(function(a) {
            var displayName = a.display_name ? a.display_name.split(' ')[0] : (a.agent_name || 'Agent');
            var hours = a.hours_resting ? parseFloat(a.hours_resting).toFixed(1) : '0.0';
            var stressPct = Math.round(parseFloat(a.stress_at_start || 0) * 100);
            var stressColor = stressPct > 80 ? '#ef4444' : stressPct > 60 ? '#f59e0b' : '#00ff41';
            html += '<div style="padding:8px;margin-bottom:6px;background:rgba(139,92,246,0.06);border:1px solid rgba(139,92,246,0.15);border-radius:6px;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">';
            html += '<span style="font-size:0.75rem;font-weight:600;color:#c4b5fd;">' + String.fromCodePoint(0x2615) + ' ' + displayName + '</span>';
            html += '<button onclick="returnFromLounge(' + parseInt(a.agent_id) + ')" style="background:rgba(0,255,65,0.15);border:1px solid rgba(0,255,65,0.3);color:#00ff41;padding:2px 8px;border-radius:3px;font-size:0.6rem;cursor:pointer;">Return to Duty</button>';
            html += '</div>';
            html += '<div style="display:flex;gap:12px;font-size:0.65rem;color:rgba(255,255,255,0.5);">';
            html += '<span>' + String.fromCodePoint(0x23F1) + ' ' + hours + 'h</span>';
            if (a.rest_type) html += '<span style="text-transform:capitalize;">' + a.rest_type + '</span>';
            if (a.stress_at_start != null) html += '<span>Stress@entry: <span style="color:' + stressColor + ';">' + stressPct + '%</span></span>';
            html += '</div>';
            if (a.rest_reason && a.rest_reason !== 'rest') {
                html += '<div style="font-size:0.65rem;color:rgba(255,255,255,0.4);margin-top:3px;font-style:italic;">' + a.rest_reason + '</div>';
            }
            html += '</div>';
        });
        container.innerHTML = html;
    } catch (e) {
        console.error('loadLoungeAgents error:', e);
        container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading lounge agents</span>';
    }
}

function toggleRestHistory() {
    var body = document.getElementById('rest-history-body');
    var label = document.getElementById('rest-history-toggle-label');
    if (!body) return;
    var isHidden = body.style.display === 'none';
    body.style.display = isHidden ? 'block' : 'none';
    if (label) label.textContent = isHidden ? 'Hide' : 'Show';
    if (isHidden && !_restHistoryLoaded) {
        loadRestHistory();
    }
}

async function loadRestHistory() {
    var container = document.getElementById('rest-history-list');
    if (!container) return;
    _restHistoryLoaded = true;
    container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Loading history...</span>';
    try {
        var resp = await fetch('/tools/bridge/api/lounge/history');
        var data = await resp.json();
        if (!data.success) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading history</span>';
            return;
        }
        var history = data.history || [];
        if (history.length === 0) {
            container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">No rest history yet</span>';
            return;
        }
        var html = '';
        history.forEach(function(h) {
            var hours = h.hours_rested ? parseFloat(h.hours_rested).toFixed(1) : '?';
            var stressDelta = '';
            if (h.stress_at_start != null && h.stress_at_end != null) {
                var sStart = Math.round(parseFloat(h.stress_at_start) * 100);
                var sEnd = Math.round(parseFloat(h.stress_at_end) * 100);
                var diffColor = (sEnd - sStart) <= 0 ? '#00ff41' : '#ef4444';
                stressDelta = '<span style="color:' + diffColor + ';">' + sStart + '% ' + String.fromCodePoint(0x2192) + ' ' + sEnd + '%</span>';
            }
            var energyDelta = '';
            if (h.energy_at_start != null && h.energy_at_end != null) {
                var eStart = Math.round(parseFloat(h.energy_at_start) * 100);
                var eEnd = Math.round(parseFloat(h.energy_at_end) * 100);
                var eDiffColor = (eEnd - eStart) >= 0 ? '#00ff41' : '#ef4444';
                energyDelta = '<span style="color:' + eDiffColor + ';">' + eStart + '% ' + String.fromCodePoint(0x2192) + ' ' + eEnd + '%</span>';
            }
            var endDate = h.ended_at ? ArchieTime.format(h.ended_at, 'short') : 'ongoing';
            html += '<div style="padding:6px 8px;margin-bottom:4px;background:rgba(139,92,246,0.04);border:1px solid rgba(139,92,246,0.1);border-radius:5px;">';
            html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;">';
            html += '<span style="font-size:0.7rem;font-weight:600;color:rgba(255,255,255,0.7);">' + (h.full_name || h.agent_name) + '</span>';
            html += '<span style="font-size:0.6rem;color:rgba(255,255,255,0.35);">' + endDate + '</span>';
            html += '</div>';
            html += '<div style="display:flex;gap:10px;font-size:0.6rem;color:rgba(255,255,255,0.45);flex-wrap:wrap;">';
            html += '<span>' + hours + 'h rested</span>';
            if (h.rest_type) html += '<span style="text-transform:capitalize;">' + h.rest_type + '</span>';
            if (stressDelta) html += '<span>Stress: ' + stressDelta + '</span>';
            if (energyDelta) html += '<span>Energy: ' + energyDelta + '</span>';
            html += '</div>';
            if (h.reason && h.reason !== 'rest') {
                html += '<div style="font-size:0.6rem;color:rgba(255,255,255,0.3);margin-top:2px;font-style:italic;">' + h.reason + '</div>';
            }
            html += '</div>';
        });
        container.innerHTML = html;
    } catch (e) {
        console.error('loadRestHistory error:', e);
        container.innerHTML = '<span class="briefing-muted" style="font-size:0.75rem;">Error loading history</span>';
    }
}

// ============================================================================
// CONTRACTORS (External Providers) — Crew Sub-Tab
// ============================================================================

async function loadContractors() {
    try {
        var [provResp, modeResp] = await Promise.all([
            fetch('/tools/bridge/api/external-providers'),
            fetch('/tools/bridge/api/routing-mode')
        ]);
        if (!provResp.ok) throw new Error('Failed to load providers');
        var data = await provResp.json();
        var routingMode = 'full';
        if (modeResp.ok) {
            var modeData = await modeResp.json();
            if (modeData.success) routingMode = modeData.routing_mode || 'full';
        }
        renderContractors(data.providers || [], routingMode, {
            iaae_total_24h: data.iaae_total_24h || 0,
            iaae_blocked_24h: data.iaae_blocked_24h || 0
        });
    } catch (e) {
        console.error('loadContractors error:', e);
        var grid = document.getElementById('contractors-grid');
        if (grid) grid.innerHTML = '<span class="briefing-muted">Failed to load contractors</span>';
    }
}

function renderContractors(providers, routingMode, iaaeData) {
    routingMode = routingMode || 'full';
    iaaeData = iaaeData || { iaae_total_24h: 0, iaae_blocked_24h: 0 };
    var iaaeBlocked = iaaeData.iaae_blocked_24h || 0;
    // Dynamic cloud provider check — use is_cloud_proxy from API data
    var cloudProviders = providers.filter(function(p) { return p.is_cloud_proxy; }).map(function(p) { return p.provider; });
    var grid = document.getElementById('contractors-grid');
    var summaryEl = document.getElementById('contractors-summary');
    if (!grid) return;

    // Compute summary — use actual API field names
    var activeCount = 0;
    var totalCount = providers.length;
    var totalSpent = 0;
    var totalBudget = 0;
    providers.forEach(function(p) {
        if (p.is_active) activeCount++;
        totalSpent += (p.current_month_cost_usd || 0);
        totalBudget += (p.monthly_budget_usd || 0);
    });
    if (summaryEl) {
        summaryEl.textContent = activeCount + '/' + totalCount + ' active \u2014 $' + totalSpent.toFixed(2) + ' / $' + totalBudget.toFixed(0);
    }

    if (providers.length === 0) {
        grid.innerHTML = '<span class="briefing-muted">No external providers configured. Click "+ Add Provider" to get started.</span>';
        return;
    }

    var html = '';
    providers.forEach(function(p) {
        var providerName = escapeHtml(p.display_name || (p.name || p.provider || '').replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); }));
        var providerKey = escapeHtml(p.provider || p.name || '');
        // Get first tier position from tier_positions map
        var tierPositions = p.tier_positions || {};
        var tierPosVals = Object.values(tierPositions);
        var tierPos = tierPosVals.length > 0 ? Math.min.apply(null, tierPosVals) : '--';
        var isEnabled = p.is_active !== false;
        var accountTier = p.account_tier || 'free';
        var tierLabel = accountTier.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
        var tierColor = accountTier === 'enterprise' ? '#a855f7' : accountTier === 'pro' ? '#f59e0b' : accountTier === 'pay_as_you_go' ? '#3b82f6' : '#6b7280';
        var monthlyBudget = p.monthly_budget_usd || 0;
        var currentCost = p.current_month_cost_usd || 0;
        var isOverBudget = monthlyBudget > 0 && currentCost > monthlyBudget;
        var statusClass = isOverBudget ? 'over-budget' : (isEnabled ? 'active' : 'inactive');
        var statusText = isOverBudget ? 'Over Budget' : (isEnabled ? 'Active' : 'Inactive');
        var budgetPct = monthlyBudget > 0 ? Math.min(100, (currentCost / monthlyBudget) * 100) : 0;
        var budgetFillClass = budgetPct > 100 ? 'over' : (budgetPct > 75 ? 'warning' : '');
        var isBlocked = (routingMode === 'local_only') ||
                        (routingMode === 'local_cloud' && cloudProviders.indexOf(p.provider) === -1);
        var blockedStyle = isBlocked ? 'position:relative;opacity:0.4;pointer-events:none;' : '';

        // Compute session/weekly totals for collapsed summary
        var pSess = 0, pSessLim = 0, pWkly = 0, pWklyLim = 0;
        (p.models || []).forEach(function(m) {
            var mw = m.usage_windows || {};
            pSess += (mw.session_2h != null ? mw.session_2h : 0);
            pSessLim += (mw.session_limit || 0);
            pWkly += (mw.weekly_7d != null ? mw.weekly_7d : 0);
            pWklyLim += (mw.weekly_limit || 0);
        });
        var sPct = pSessLim > 0 ? Math.min(100, Math.round(pSess / pSessLim * 100)) + '%' : '\u221e';
        var wPct = pWklyLim > 0 ? Math.min(100, Math.round(pWkly / pWklyLim * 100)) + '%' : '\u221e';
        var headerSummary = (pSess > 0 || pWkly > 0 || pSessLim > 0 || pWklyLim > 0) ? 's=' + sPct + ' / w=' + wPct : '';

        html += '<div class="contractor-firm"' + (blockedStyle ? ' style="' + blockedStyle + '"' : '') + '>';
        html += '<div class="contractor-firm-header" onclick="this.parentElement.classList.toggle(\'expanded\')">';
        html += '<i data-lucide="chevron-right" class="chevron-icon"></i>';
        html += '<span class="contractor-firm-name">' + providerName + '</span>';
        if (headerSummary) html += '<span class="contractor-header-summary">' + headerSummary + '</span>';
        html += '<span class="contractor-tier-badge">Tier ' + escapeHtml(String(tierPos)) + '</span>';
        html += '<span style="font-size:0.6rem;padding:1px 6px;border-radius:3px;border:1px solid ' + tierColor + ';color:' + tierColor + ';text-transform:uppercase;letter-spacing:0.5px;">' + escapeHtml(tierLabel) + '</span>';
        html += '<span class="contractor-status-badge ' + statusClass + '">' + statusText + '</span>';
        html += '<div class="budget-bar"><div class="budget-fill ' + budgetFillClass + '" style="width:' + budgetPct.toFixed(0) + '%"></div></div>';
        html += '<div class="contractor-firm-actions">';
        html += '<button class="contractor-btn-edit" onclick="event.stopPropagation();editProvider(\'' + providerKey + '\')">Edit</button>';
        html += '<button class="contractor-btn-toggle" onclick="event.stopPropagation();toggleProvider(\'' + providerKey + '\')">' + (isEnabled ? 'Disable' : 'Enable') + '</button>';
        html += '</div>';
        html += '</div>'; // header

        // Models body
        html += '<div class="contractor-firm-body">';
        // Auth & budget info row
        var authMethod = escapeHtml(p.auth_method || 'API key');
        var keyHint = p.key_hint ? escapeHtml(p.key_hint) : 'Not set';
        html += '<div style="display:flex;flex-wrap:wrap;gap:12px;padding:6px 8px;margin-bottom:8px;background:rgba(255,255,255,0.03);border-radius:4px;font-size:0.72rem;color:var(--archie-text-tertiary);">';
        html += '<span>Auth: <span style="color:var(--archie-cyan);">' + authMethod + '</span></span>';
        html += '<span>Key: <span style="color:' + (p.key_hint ? 'var(--archie-text-secondary)' : '#ff6b6b') + ';">' + keyHint + '</span></span>';
        html += '<span>Budget: <span style="color:var(--archie-text-secondary);">$' + monthlyBudget.toFixed(2) + '/mo</span></span>';
        html += '<span>Spent: <span style="color:var(--archie-text-secondary);">$' + currentCost.toFixed(2) + '</span></span>';
        html += '</div>';
        var models = p.models || [];
        if (models.length === 0) {
            html += '<span class="briefing-muted" style="font-size:0.7rem;">No models registered for this provider</span>';
        } else {
            html += '<div class="contractor-models-grid">';
            models.forEach(function(m) {
                var modelEnabled = m.enabled !== false;
                html += '<div class="contractor-model-card' + (modelEnabled ? '' : ' disabled') + '">';
                var mStats = m.stats_24h || {};
                var mTierPos = m.tier_position != null ? m.tier_position : tierPos;
                html += '<div class="contractor-model-name">' + escapeHtml(m.name || m.model_name || '') + '</div>';
                html += '<div class="contractor-model-meta">';
                html += '<span>Contract Worker \u00b7 Tier ' + escapeHtml(String(mTierPos)) + '</span>';
                html += '</div>';
                var mAlltime = m.stats_alltime || null;
                html += '<div class="model-stats">';
                html += '<div>Tasks/24h: <span class="stat-val">' + (mStats.requests != null ? mStats.requests : '0') + '</span></div>';
                html += '<div>Success: <span class="stat-val">' + (mStats.success_rate != null && mStats.requests > 0 ? parseFloat(mStats.success_rate).toFixed(0) + '%' : '--') + '</span></div>';
                html += '<div>Avg latency: <span class="stat-val">' + (mStats.avg_latency_ms != null && mStats.requests > 0 ? (parseFloat(mStats.avg_latency_ms) / 1000).toFixed(1) + 's' : '--') + '</span></div>';
                html += '<div>Cost/24h: <span class="stat-val">$' + (mStats.cost != null ? parseFloat(mStats.cost).toFixed(3) : '0.000') + '</span></div>';
                html += '</div>';
                if (mAlltime) {
                    var lastUsedStr = mAlltime.last_used ? ArchieTime.date(mAlltime.last_used) : '--';
                    html += '<div class="model-stats" style="margin-top:4px;padding-top:4px;border-top:1px solid rgba(255,255,255,0.06);">';
                    html += '<div>Total: <span class="stat-val">' + mAlltime.requests + ' tasks</span></div>';
                    html += '<div>Success: <span class="stat-val">' + parseFloat(mAlltime.success_rate).toFixed(0) + '%</span></div>';
                    html += '<div>Last used: <span class="stat-val">' + lastUsedStr + '</span></div>';
                    html += '<div>Total cost: <span class="stat-val">$' + parseFloat(mAlltime.cost).toFixed(3) + '</span></div>';
                    html += '</div>';
                }
                var mWindows = m.usage_windows || null;
                if (mWindows) {
                    var sess = mWindows.session_2h != null ? mWindows.session_2h : 0;
                    var sessLimit = mWindows.session_limit || null;
                    var wkly = mWindows.weekly_7d != null ? mWindows.weekly_7d : 0;
                    var wklyLimit = mWindows.weekly_limit || null;
                    var sessPct = sessLimit ? Math.min(sess / sessLimit * 100, 100) : 0;
                    var sessPct = sessLimit ? Math.min(sess / sessLimit * 100, 100) : 0;
                    var wklyPct = wklyLimit ? Math.min(wkly / wklyLimit * 100, 100) : 0;
                    var barColor = function(pct) { return pct > 80 ? '#ff4444' : pct > 50 ? '#ffaa00' : '#22cc88'; };
                    var sessStr = sessLimit ? sess + ' / ' + sessLimit : sess + ' req';
                    var wklyStr = wklyLimit ? wkly + ' / ' + wklyLimit : wkly + ' req';
                    var sessPctStr = sessLimit ? Math.round(sessPct) + '%' : '';
                    var wklyPctStr = wklyLimit ? Math.round(wklyPct) + '%' : '';
                    html += '<div style="margin-top:4px;padding:5px 6px;border-top:1px solid rgba(255,255,255,0.06);display:flex;flex-direction:column;gap:5px;font-size:0.65rem;">';
                    // Session bar
                    html += '<div style="display:flex;align-items:center;gap:6px;">';
                    html += '<span style="color:rgba(255,255,255,0.5);min-width:58px;display:flex;align-items:center;gap:3px;"><i data-lucide="clock" style="width:10px;height:10px;"></i> Session</span>';
                    if (sessLimit) {
                        html += '<span style="color:' + barColor(sessPct) + ';min-width:28px;font-weight:600;font-size:0.6rem;">' + sessPctStr + '</span>';
                        html += '<div style="flex:1;height:10px;background:rgba(255,255,255,0.06);border-radius:5px;overflow:hidden;position:relative;">';
                        html += '<div style="height:100%;width:' + sessPct.toFixed(1) + '%;background:' + barColor(sessPct) + ';border-radius:5px;transition:width 0.4s ease;"></div>';
                        html += '</div>';
                    } else {
                        html += '<span style="color:var(--archie-cyan);font-size:0.6rem;flex:1;">Unlimited</span>';
                    }
                    html += '<span style="color:rgba(255,255,255,0.45);min-width:62px;text-align:right;font-size:0.6rem;">' + sessStr + '</span>';
                    html += '</div>';
                    // Weekly bar
                    html += '<div style="display:flex;align-items:center;gap:6px;">';
                    html += '<span style="color:rgba(255,255,255,0.5);min-width:58px;display:flex;align-items:center;gap:3px;"><i data-lucide="calendar" style="width:10px;height:10px;"></i> Weekly</span>';
                    if (wklyLimit) {
                        html += '<span style="color:' + barColor(wklyPct) + ';min-width:28px;font-weight:600;font-size:0.6rem;">' + wklyPctStr + '</span>';
                        html += '<div style="flex:1;height:10px;background:rgba(255,255,255,0.06);border-radius:5px;overflow:hidden;position:relative;">';
                        html += '<div style="height:100%;width:' + wklyPct.toFixed(1) + '%;background:' + barColor(wklyPct) + ';border-radius:5px;transition:width 0.4s ease;"></div>';
                        html += '</div>';
                    } else {
                        html += '<span style="color:var(--archie-cyan);font-size:0.6rem;flex:1;">Unlimited</span>';
                    }
                    html += '<span style="color:rgba(255,255,255,0.45);min-width:62px;text-align:right;font-size:0.6rem;">' + wklyStr + '</span>';
                    html += '</div>';
                    html += '</div>';
                }
                html += '<div style="display:flex;align-items:center;justify-content:space-between;">';
                if (iaaeBlocked > 0) {
                    html += '<span class="contractor-iaae-badge" style="color:#ffaa00;border-color:#ffaa00;"><i data-lucide="shield-alert" style="width:10px;height:10px;"></i> IAAE: ' + escapeHtml(String(iaaeBlocked)) + ' blocked</span>';
                } else {
                    html += '<span class="contractor-iaae-badge"><i data-lucide="shield-check" style="width:10px;height:10px;"></i> IAAE Compliant</span>';
                }
                html += '<label class="contractor-model-toggle"><input type="checkbox" ' + (modelEnabled ? 'checked' : '') + ' onchange="toggleContractorModel(\'' + providerKey + '\',\'' + escapeHtml(m.name || m.model_name || '') + '\',this.checked)"> Enabled</label>';
                html += '</div>';
                html += '</div>'; // model card
            });
            html += '</div>'; // models grid
        }
        html += '</div>'; // firm body
        if (isBlocked) {
            var blockedText = routingMode === 'local_only' ? 'Routing: Local Only' : 'Routing: Local + Cloud Only';
            html += '<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,0.7);color:#ffaa00;padding:4px 12px;border-radius:4px;font-size:0.7rem;z-index:1;pointer-events:auto;">' + blockedText + '</div>';
        }
        html += '</div>'; // firm
    });

    grid.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleProvider(provider) {
    fetch('/tools/bridge/api/external-providers/' + encodeURIComponent(provider) + '/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast(data.message || 'Provider toggled', 'success');
        loadContractors();
    })
    .catch(function(e) {
        showToast('Failed to toggle provider', 'error');
    });
}

function toggleContractorModel(provider, model, enabled) {
    fetch('/tools/bridge/api/external-providers/' + encodeURIComponent(provider) + '/models/' + encodeURIComponent(model) + '/toggle', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: enabled })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast(data.message || 'Model toggled', 'success');
        loadContractors();
    })
    .catch(function(e) {
        showToast('Failed to toggle model', 'error');
    });
}

function openAddProviderModal(editProviderName) {
    // Remove existing modal if any
    var existing = document.querySelector('.bm-overlay.bm-provider-modal');
    if (existing) existing.remove();

    // Fetch both contractor-providers definitions AND current key data in parallel
    Promise.all([
        fetch('/tools/bridge/api/contractor-providers').then(function(r) { return r.json(); }),
        fetch('/tools/bridge/api/external-providers').then(function(r) { return r.json(); })
    ]).then(function(results) {
        var cpData = results[0];
        var epData = results[1];
        var contractorProviders = cpData.providers || [];
        var configuredProviders = epData.providers || [];
        var current = editProviderName ? configuredProviders.find(function(p) { return p.provider === editProviderName; }) : null;

        // Build provider options dynamically from contractor_providers table
        var providerOptions = contractorProviders.map(function(cp) {
            return { value: cp.provider_key, label: cp.display_name, is_cloud_proxy: cp.is_cloud_proxy };
        });

        var budgetVal = current ? (current.monthly_budget_usd || 10) : 10;
        var currentTier = current ? (current.account_tier || 'free') : 'free';
        var isCloud = editProviderName && providerOptions.some(function(opt) { return opt.value === editProviderName && opt.is_cloud_proxy; });
        var keyPlaceholder = current && current.key_hint ? 'Current: ' + current.key_hint + ' (leave blank to keep)' : 'sk-... or key';

        var tierOptions = [
            { value: 'free', label: 'Free' },
            { value: 'pro', label: 'Pro' },
            { value: 'pay_as_you_go', label: 'Pay As You Go' },
            { value: 'enterprise', label: 'Enterprise' },
            { value: 'max', label: 'Max' }
        ];

        // Helper to create elements
        function el(tag, cls, style) {
            var e = document.createElement(tag);
            if (cls) e.className = cls;
            if (style) e.style.cssText = style;
            return e;
        }

        // --- Build LCARS tablet modal ---
        var overlay = el('div', 'bm-overlay active bm-provider-modal', '--bm-accent:#a855f7;--bm-accent-rgb:168,85,247;');
        overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };

        var shell = el('div', 'bm-shell', 'max-width:400px;');

        // Left frame sidebar
        var frame = el('div', 'bm-frame');
        frame.appendChild(el('div', 'bm-frame-elbow-top'));
        frame.appendChild(el('div', 'bm-frame-seg'));
        frame.appendChild(el('div', 'bm-frame-seg dim'));
        frame.appendChild(el('div', 'bm-frame-light on'));
        frame.appendChild(el('div', 'bm-frame-light amber'));
        frame.appendChild(el('div', 'bm-frame-seg purple'));
        frame.appendChild(el('div', 'bm-frame-fill'));
        frame.appendChild(el('div', 'bm-frame-elbow-bottom'));
        shell.appendChild(frame);

        // Right content column
        var content = el('div', 'bm-content');

        // Header
        var header = el('div', 'bm-header');
        var title = el('span', 'bm-header-title');
        title.textContent = (editProviderName ? 'EDIT' : 'ADD') + ' PROVIDER';
        header.appendChild(title);
        var strip = el('div', 'bm-header-strip');
        strip.appendChild(el('span', 'bm-header-pip w1'));
        strip.appendChild(el('span', 'bm-header-pip w2'));
        strip.appendChild(el('span', 'bm-header-pip w3'));
        var closeBtn = el('button', 'bm-close');
        closeBtn.textContent = '\u00D7';
        closeBtn.onclick = function() { overlay.remove(); };
        strip.appendChild(closeBtn);
        header.appendChild(strip);
        content.appendChild(header);

        // Body
        var body = el('div', 'bm-body');

        // Provider select
        var lbl1 = document.createElement('label');
        lbl1.textContent = 'Provider';
        body.appendChild(lbl1);
        var provSelect = document.createElement('select');
        provSelect.id = 'provider-modal-name';
        if (editProviderName) provSelect.disabled = true;
        var defOpt = document.createElement('option');
        defOpt.value = '';
        defOpt.textContent = 'Select provider...';
        provSelect.appendChild(defOpt);
        providerOptions.forEach(function(opt) {
            var o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (editProviderName && editProviderName === opt.value) o.selected = true;
            provSelect.appendChild(o);
        });
        body.appendChild(provSelect);

        // Auth note container
        var authNoteDiv = document.createElement('div');
        authNoteDiv.id = 'provider-modal-auth-note';
        if (isCloud) {
            var noteInner = document.createElement('div');
            noteInner.style.cssText = 'margin:6px 0 8px;padding:6px 8px;background:rgba(0,255,255,0.06);border:1px solid rgba(0,255,255,0.15);border-radius:4px;font-size:0.72rem;color:var(--archie-cyan);';
            noteInner.textContent = 'Auth: OLLAMA_API_KEY env var (shared Ollama cloud proxy)';
            authNoteDiv.appendChild(noteInner);
        }
        body.appendChild(authNoteDiv);

        // Account tier select
        var lbl2 = document.createElement('label');
        lbl2.textContent = 'Account Tier';
        body.appendChild(lbl2);
        var tierSelect = document.createElement('select');
        tierSelect.id = 'provider-modal-tier';
        tierOptions.forEach(function(opt) {
            var o = document.createElement('option');
            o.value = opt.value;
            o.textContent = opt.label;
            if (opt.value === currentTier) o.selected = true;
            tierSelect.appendChild(o);
        });
        body.appendChild(tierSelect);

        // API key input
        var lbl3 = document.createElement('label');
        lbl3.textContent = 'API Key';
        body.appendChild(lbl3);
        var keyInput = document.createElement('input');
        keyInput.type = 'password';
        keyInput.id = 'provider-modal-key';
        keyInput.placeholder = keyPlaceholder;
        body.appendChild(keyInput);

        // Budget input
        var lbl4 = document.createElement('label');
        lbl4.textContent = 'Monthly Budget ($)';
        body.appendChild(lbl4);
        var budgetInput = document.createElement('input');
        budgetInput.type = 'number';
        budgetInput.id = 'provider-modal-budget';
        budgetInput.value = budgetVal;
        budgetInput.min = '0';
        budgetInput.step = '1';
        body.appendChild(budgetInput);

        content.appendChild(body);

        // Actions bar
        var actions = el('div', 'bm-actions');
        var cancelBtn2 = el('button', 'btn-cancel');
        cancelBtn2.textContent = 'Cancel';
        cancelBtn2.onclick = function() { overlay.remove(); };
        var saveBtn = el('button', 'btn-submit');
        saveBtn.textContent = 'Save';
        saveBtn.onclick = function() { saveProvider(); };
        actions.appendChild(cancelBtn2);
        actions.appendChild(saveBtn);
        content.appendChild(actions);

        // Footer decorative strip
        var footer = el('div', 'bm-footer');
        var footerStrip = el('div', 'bm-footer-strip');
        footerStrip.appendChild(el('span', 'bm-footer-dot purple'));
        footerStrip.appendChild(el('span', 'bm-footer-dot gold'));
        footerStrip.appendChild(el('span', 'bm-footer-dot cyan'));
        footer.appendChild(footerStrip);
        content.appendChild(footer);

        shell.appendChild(content);
        overlay.appendChild(shell);
        document.body.appendChild(overlay);

        // Dynamic auth note update when provider changes
        if (!editProviderName) {
            provSelect.addEventListener('change', function() {
                var sel = this.value;
                var cp = providerOptions.find(function(o) { return o.value === sel; });
                var noteEl = document.getElementById('provider-modal-auth-note');
                if (noteEl) {
                    while (noteEl.firstChild) noteEl.removeChild(noteEl.firstChild);
                    if (cp && cp.is_cloud_proxy) {
                        var noteInner = document.createElement('div');
                        noteInner.style.cssText = 'margin:6px 0 8px;padding:6px 8px;background:rgba(0,255,255,0.06);border:1px solid rgba(0,255,255,0.15);border-radius:4px;font-size:0.72rem;color:var(--archie-cyan);';
                        noteInner.textContent = 'Auth: OLLAMA_API_KEY env var (shared Ollama cloud proxy)';
                        noteEl.appendChild(noteInner);
                    }
                }
            });
        }

        if (typeof lucide !== 'undefined') lucide.createIcons();
    });
}

function editProvider(providerName) {
    openAddProviderModal(providerName);
}

function saveProvider() {
    var nameEl = document.getElementById('provider-modal-name');
    var keyEl = document.getElementById('provider-modal-key');
    var budgetEl = document.getElementById('provider-modal-budget');

    if (!nameEl || !nameEl.value) {
        showToast('Please select a provider', 'error');
        return;
    }

    var tierEl = document.getElementById('provider-modal-tier');
    var payload = {
        provider: nameEl.value,
        monthly_budget_usd: parseFloat(budgetEl.value) || 10,
        account_tier: tierEl ? tierEl.value : 'free'
    };
    if (keyEl.value) {
        payload.api_key = keyEl.value;
    }

    fetch('/tools/bridge/api/external-providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        showToast(data.message || 'Provider saved', 'success');
        var overlay = document.querySelector('.bm-overlay.bm-provider-modal');
        if (overlay) overlay.remove();
        loadContractors();
    })
    .catch(function(e) {
        showToast('Failed to save provider', 'error');
    });
}
