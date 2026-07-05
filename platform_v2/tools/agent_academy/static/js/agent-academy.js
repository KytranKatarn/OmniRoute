/**
 * Agent Academy — Training, Benchmarking & Model Testing Center
 *
 * Note: All user-provided data is sanitized via esc() before DOM insertion.
 * innerHTML is used for rendering structured HTML templates with escaped content.
 */

const AA_BASE = '/tools/agent-academy';
let aaAgents = [];
let aaModels = [];
let aaTabLoaded = {};
let aaLastABResults = null;
let aaDiffShown = false;

// ============================================================
// Init
// ============================================================

document.addEventListener('DOMContentLoaded', function() {
    loadAgentList();
    loadAvailableModels();
    populateModelSelects();
    switchTab('benchmarks');
    if (typeof lucide !== 'undefined') lucide.createIcons();
});

function api(path, opts) {
    opts = opts || {};
    var url = AA_BASE + path;
    return fetch(url, {
        headers: Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {}),
        method: opts.method || 'GET',
        body: opts.body || undefined,
    }).then(function(resp) {
        if (!resp.ok) {
            return resp.json().catch(function() {
                return { error: resp.statusText };
            }).then(function(err) {
                throw new Error(err.error || resp.statusText);
            });
        }
        return resp.json();
    });
}

function esc(s) {
    if (!s) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
}

// Alias — Cloud Comparison Lane (#4661) judge/diff renderers call escHtml();
// reuse the existing esc() implementation rather than duplicating it.
function escHtml(s) {
    return esc(s);
}

function setContent(el, safeHtml) {
    if (typeof el === 'string') el = document.getElementById(el);
    if (el) el.innerHTML = safeHtml;
}

// ============================================================
// Agent & Model List (shared across tabs)
// ============================================================

function loadAgentList() {
    return api('/api/models/agents').then(function(data) {
        aaAgents = data.agents || [];
        var aCnt = document.getElementById('aa-agent-count');
        if (aCnt) aCnt.textContent = aaAgents.length;
        populateAgentSelects();
        populateDeptFilter();
    }).catch(function(e) {
        console.error('Failed to load agents:', e);
    });
}

function loadAvailableModels() {
    return api('/api/models/available').then(function(data) {
        aaModels = data.available || [];
        document.getElementById('loaded-count').textContent = data.loaded_count || 0;
        document.getElementById('available-count').textContent = data.available_count || 0;
        populateModelEditSelect(data.available || [], data.loaded_names || []);
    }).catch(function(e) {
        console.error('Failed to load models:', e);
    });
}

function populateAgentSelects() {
    var selects = ['bench-agent', 'train-agent'];
    selects.forEach(function(id) {
        var el = document.getElementById(id);
        if (!el) return;
        var val = el.value;
        el.textContent = '';
        var defOpt = document.createElement('option');
        defOpt.value = '';
        defOpt.textContent = 'Select Agent...';
        el.appendChild(defOpt);
        aaAgents.forEach(function(a) {
            var opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = (a.display_name || a.name) + ' (' + (a.department || 'N/A') + ')';
            el.appendChild(opt);
        });
        if (val) el.value = val;
    });
}

function populateDeptFilter() {
    var el = document.getElementById('model-dept-filter');
    if (!el) return;
    var seen = {};
    var depts = [];
    aaAgents.forEach(function(a) {
        if (a.department && !seen[a.department]) {
            seen[a.department] = true;
            depts.push(a.department);
        }
    });
    depts.sort();
    el.textContent = '';
    var defOpt = document.createElement('option');
    defOpt.value = '';
    defOpt.textContent = 'All Departments';
    el.appendChild(defOpt);
    depts.forEach(function(d) {
        var opt = document.createElement('option');
        opt.value = d;
        opt.textContent = d;
        el.appendChild(opt);
    });
}

function populateModelEditSelect(models, loadedNames) {
    var el = document.getElementById('modal-model');
    if (!el) return;
    var val = el.value;
    el.textContent = '';
    var defOpt = document.createElement('option');
    defOpt.value = '';
    defOpt.textContent = 'Select Model...';
    el.appendChild(defOpt);
    models.forEach(function(m) {
        var opt = document.createElement('option');
        opt.value = m.name;
        var loaded = loadedNames.indexOf(m.name) >= 0 ? ' [LOADED]' : '';
        opt.textContent = m.name + loaded + ' (' + (m.parameter_size || '?') + ')';
        el.appendChild(opt);
    });
    if (val) el.value = val;
}

// Cloud Comparison Lane (#4661): local + cloud optgroups for the A/B model
// pickers. Built via DOM API (not innerHTML string concat) so untrusted
// model/provider names can't break out of an attribute value.
function populateModelSelects() {
    api('/api/ab-test/models').then(function(d) {
        var localModels = d.local || [];
        var cloudModels = d.cloud || [];
        ['ab-model-a', 'ab-model-b'].forEach(function(id) {
            var el = document.getElementById(id);
            if (!el) return;
            var val = el.value;
            el.textContent = '';

            var localGroup = document.createElement('optgroup');
            localGroup.label = 'Local (sovereign)';
            localModels.forEach(function(m) {
                var opt = document.createElement('option');
                opt.value = m.name;
                opt.textContent = m.name;
                localGroup.appendChild(opt);
            });
            el.appendChild(localGroup);

            var cloudGroup = document.createElement('optgroup');
            cloudGroup.label = 'Cloud (ask-first)';
            cloudModels.forEach(function(c) {
                var rem = (c.weekly_remaining === null || c.weekly_remaining === undefined) ? '∞' : c.weekly_remaining;
                var opt = document.createElement('option');
                opt.value = 'provider:' + c.provider_key + ':' + c.model;
                opt.textContent = '☁ ' + c.display_name + ' (' + c.model + ') — ' + rem + ' left';
                if (c.disabled) opt.disabled = true;
                cloudGroup.appendChild(opt);
            });
            el.appendChild(cloudGroup);

            if (val) el.value = val;
        });
    }).catch(function(e) {
        console.error('Failed to load AB test models:', e);
    });
}

// ============================================================
// Tab Switching
// ============================================================

function switchTab(tabName) {
    document.querySelectorAll('.aa-tab').forEach(function(t) { t.classList.remove('active'); });
    document.querySelectorAll('.aa-panel').forEach(function(p) { p.classList.remove('active'); });

    var tab = document.querySelector('.aa-tab[data-tab="' + tabName + '"]');
    var panel = document.getElementById('panel-' + tabName);
    if (tab) tab.classList.add('active');
    if (panel) panel.classList.add('active');

    if (!aaTabLoaded[tabName]) {
        aaTabLoaded[tabName] = true;
        switch (tabName) {
            case 'benchmarks': loadBenchmarks(); loadRankings(); break;
            case 'training': loadTrainingGaps(); loadTrainingStatus(); break;
            case 'models': loadModelAgents(); break;
            case 'ab-test': loadABHistory(); break;
            case 'knowledge': loadKnowledgeAgents(); break;
        }
    }
}

// ============================================================
// Benchmarks Tab
// ============================================================

function loadBenchmarks() {
    setContent('benchmarks-container', '<div class="aa-empty"><span class="aa-loading"></span> Loading...</div>');
    api('/api/benchmarks?limit=15').then(function(data) {
        var runs = data.runs || [];
        if (!runs.length) {
            setContent('benchmarks-container', '<div class="aa-empty">No benchmark runs yet. Run your first benchmark above.</div>');
            return;
        }
        var html = '<table class="aa-table"><thead><tr><th>ID</th><th>Capability</th><th>Status</th><th>Agents</th><th>Date</th><th>Top Score</th></tr></thead><tbody>';
        runs.forEach(function(r) {
            var cap = (r.test_config && r.test_config.capability) || r.action_key || '-';
            var topScore = r.results && r.results.length ? Math.max.apply(null, r.results.map(function(x) { return x.score || 0; })) : 0;
            html += '<tr>'
                + '<td>#' + r.id + '</td>'
                + '<td>' + esc(cap) + '</td>'
                + '<td><span class="aa-badge ' + (r.status === 'completed' ? 'aa-badge-green' : r.status === 'failed' ? 'aa-badge-red' : 'aa-badge-yellow') + '">' + esc(r.status) + '</span></td>'
                + '<td>' + (r.completed_agents || 0) + '/' + (r.total_agents || 0) + '</td>'
                + '<td>' + (r.started_at ? new Date(r.started_at).toLocaleDateString() : '-') + '</td>'
                + '<td class="aa-score ' + scoreClass(topScore) + '">' + topScore.toFixed(3) + '</td>'
                + '</tr>';
        });
        html += '</tbody></table>';
        setContent('benchmarks-container', html);
    }).catch(function(e) {
        setContent('benchmarks-container', '<div class="aa-empty">Error loading benchmarks: ' + esc(e.message) + '</div>');
    });
}

function loadRankings() {
    setContent('rankings-container', '<div class="aa-empty"><span class="aa-loading"></span> Loading rankings...</div>');
    api('/api/benchmarks/rankings').then(function(data) {
        var caps = data.capabilities || {};
        var skills = Object.keys(caps);
        var sCnt = document.getElementById('aa-skill-count');
        if (sCnt) sCnt.textContent = skills.length;

        if (!skills.length) {
            setContent('rankings-container', '<div class="aa-empty">No skills data yet. Run benchmarks to populate rankings.</div>');
            return;
        }
        var html = '';
        skills.forEach(function(skill) {
            var agents = caps[skill];
            html += '<div class="aa-card">'
                + '<div class="aa-card-header">'
                + '<span class="aa-card-name">' + esc(skill) + '</span>'
                + '<span class="aa-badge aa-badge-purple">' + agents.length + ' agents</span>'
                + '</div>';
            agents.slice(0, 5).forEach(function(a, i) {
                html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0;font-size:0.78rem">'
                    + '<span>' + (i + 1) + '. ' + esc(a.display_name || a.name) + ' <span class="aa-card-dept">' + esc(a.department || '') + '</span></span>'
                    + '<span>' + renderLevelBar(a.proficiency_level || 1) + '</span>'
                    + '</div>';
            });
            html += '</div>';
        });
        setContent('rankings-container', html);
    }).catch(function(e) {
        setContent('rankings-container', '<div class="aa-empty">Error: ' + esc(e.message) + '</div>');
    });
}

function runBenchmark() {
    var agentId = document.getElementById('bench-agent').value;
    var capability = document.getElementById('bench-capability').value.trim() || 'general';
    var prompt = document.getElementById('bench-prompt').value.trim();
    if (!agentId || !prompt) { alert('Select an agent and enter a test prompt.'); return; }

    var btn = document.getElementById('btn-run-bench');
    btn.disabled = true;
    btn.textContent = 'RUNNING...';

    api('/api/benchmarks/run', {
        method: 'POST',
        body: JSON.stringify({ agent_id: parseInt(agentId), capability: capability, test_prompt: prompt }),
    }).then(function(result) {
        alert('Benchmark complete!\nScore: ' + result.score + '\nTime: ' + result.duration_ms + 'ms\nSuccess: ' + result.success);
        aaTabLoaded['benchmarks'] = false;
        switchTab('benchmarks');
    }).catch(function(e) {
        alert('Benchmark failed: ' + e.message);
    }).finally(function() {
        btn.disabled = false;
        btn.textContent = 'RUN BENCHMARK';
    });
}

// ============================================================
// Training Tab
// ============================================================

function loadTrainingGaps() {
    setContent('gaps-container', '<div class="aa-empty"><span class="aa-loading"></span> Loading...</div>');
    api('/api/training/gaps').then(function(data) {
        if (!data.gaps.length && !data.covered.length) {
            setContent('gaps-container', '<div class="aa-empty">No skills data found. Run benchmarks first.</div>');
            return;
        }
        var html = '';
        if (data.gaps.length) {
            html += '<div style="margin-bottom:0.5rem"><span class="aa-badge aa-badge-red">' + data.gap_count + ' GAPS</span></div>';
            data.gaps.forEach(function(g) {
                html += '<div class="aa-gap-card is-gap">'
                    + '<span>' + esc(g.skill_name) + '</span>'
                    + renderLevelBar(g.max_level || 0)
                    + '<span class="aa-card-dept">' + g.agent_count + ' agents</span>'
                    + '</div>';
            });
        }
        if (data.covered.length) {
            html += '<div style="margin-top:1rem;margin-bottom:0.5rem"><span class="aa-badge aa-badge-green">' + data.covered.length + ' COVERED (Lv4+)</span></div>';
            data.covered.forEach(function(g) {
                html += '<div class="aa-gap-card is-covered">'
                    + '<span>' + esc(g.skill_name) + '</span>'
                    + renderLevelBar(g.max_level || 0)
                    + '<span class="aa-card-dept">' + g.agent_count + ' agents</span>'
                    + '</div>';
            });
        }
        setContent('gaps-container', html);
    }).catch(function(e) {
        setContent('gaps-container', '<div class="aa-empty">Error: ' + esc(e.message) + '</div>');
    });
}

function loadTrainingStatus() {
    setContent('training-status-container', '<div class="aa-empty"><span class="aa-loading"></span> Loading...</div>');
    api('/api/training/status').then(function(data) {
        var depts = data.departments || {};
        var deptNames = Object.keys(depts).sort();
        if (!deptNames.length) {
            setContent('training-status-container', '<div class="aa-empty">No active agents found.</div>');
            return;
        }
        var html = '';
        deptNames.forEach(function(dept) {
            var d = depts[dept];
            var dist = d.skill_distribution || {};
            html += '<div class="aa-dept-section">'
                + '<div class="aa-dept-header">'
                + '<span>' + esc(dept) + ' <span class="aa-badge aa-badge-dim">' + d.agents.length + ' agents</span></span>'
                + '<div class="aa-dist-bar">'
                + '<span class="aa-dist-item aa-badge-red">L1:' + (dist[1] || 0) + '</span>'
                + '<span class="aa-dist-item aa-badge-yellow">L2:' + (dist[2] || 0) + '</span>'
                + '<span class="aa-dist-item aa-badge-yellow">L3:' + (dist[3] || 0) + '</span>'
                + '<span class="aa-dist-item aa-badge-green">L4:' + (dist[4] || 0) + '</span>'
                + '<span class="aa-dist-item aa-badge-teal">L5:' + (dist[5] || 0) + '</span>'
                + '</div></div>';
            d.agents.forEach(function(a) {
                html += '<div class="aa-card">'
                    + '<div class="aa-card-header">'
                    + '<span class="aa-card-name">' + esc(a.display_name || a.name) + '</span>'
                    + '<span class="aa-badge ' + (a.shift_state === 'active' ? 'aa-badge-green' : 'aa-badge-dim') + '">' + esc(a.shift_state) + '</span>'
                    + '</div>';
                if (a.skills && a.skills.length) {
                    a.skills.forEach(function(s) {
                        html += '<div style="display:flex;justify-content:space-between;align-items:center;font-size:0.75rem;padding:2px 0">'
                            + '<span>' + esc(s.name) + '</span>'
                            + renderLevelBar(s.level || 1)
                            + '</div>';
                    });
                } else {
                    html += '<div class="aa-card-dept">No skills assigned</div>';
                }
                html += '</div>';
            });
            html += '</div>';
        });
        setContent('training-status-container', html);
    }).catch(function(e) {
        setContent('training-status-container', '<div class="aa-empty">Error: ' + esc(e.message) + '</div>');
    });
}

function assignTraining() {
    var agentId = document.getElementById('train-agent').value;
    var skill = document.getElementById('train-skill').value.trim();
    var level = parseInt(document.getElementById('train-level').value);
    if (!agentId || !skill) { alert('Select an agent and enter a skill name.'); return; }

    api('/api/training/assign', {
        method: 'POST',
        body: JSON.stringify({ agent_id: parseInt(agentId), skill_name: skill, target_level: level }),
    }).then(function(result) {
        alert('Training assigned!\n' + result.agent_name + ': ' + result.skill_name + ' Lv' + result.current_level + ' -> Lv' + result.target_level);
        document.getElementById('train-skill').value = '';
    }).catch(function(e) {
        alert('Failed: ' + e.message);
    });
}

// ============================================================
// Models Tab
// ============================================================

function loadModelAgents() {
    var container = document.getElementById('models-container');
    var dept = document.getElementById('model-dept-filter').value;
    setContent(container, '<div class="aa-empty"><span class="aa-loading"></span> Loading...</div>');
    var url = dept ? '/api/models/agents?department=' + encodeURIComponent(dept) : '/api/models/agents';
    api(url).then(function(data) {
        var agents = data.agents || [];
        if (!agents.length) {
            setContent(container, '<div class="aa-empty">No agents found.</div>');
            return;
        }
        var html = '<div class="aa-card-grid">';
        agents.forEach(function(a) {
            html += '<div class="aa-card" style="cursor:pointer" onclick="openModelModal(' + a.id + ')">'
                + '<div class="aa-card-header">'
                + '<span class="aa-card-name">' + esc(a.display_name || a.name) + '</span>'
                + '<span class="aa-badge ' + (a.shift_state === 'active' ? 'aa-badge-green' : 'aa-badge-dim') + '">' + esc(a.shift_state) + '</span>'
                + '</div>'
                + '<div class="aa-card-dept">' + esc(a.department || 'N/A') + '</div>'
                + '<div class="aa-card-model">' + esc(a.model || 'No model') + '</div>'
                + '<div style="font-size:0.7rem;color:var(--aa-text-dim);margin-top:0.35rem">'
                + 'temp: ' + a.temperature + ' | tokens: ' + (a.max_tokens || '-')
                + '</div>'
                + (a.system_prompt_preview
                    ? '<div class="aa-prompt-preview">' + esc(a.system_prompt_preview) + '</div>'
                    : '<div class="aa-no-prompt">No system prompt</div>')
                + '</div>';
        });
        html += '</div>';
        setContent(container, html);
    }).catch(function(e) {
        setContent(container, '<div class="aa-empty">Error: ' + esc(e.message) + '</div>');
    });
}

function openModelModal(agentId) {
    var agent = null;
    for (var i = 0; i < aaAgents.length; i++) {
        if (aaAgents[i].id === agentId) { agent = aaAgents[i]; break; }
    }
    if (!agent) return;

    document.getElementById('modal-agent-id').value = agentId;
    document.getElementById('modal-agent-name').textContent = agent.display_name || agent.name;
    document.getElementById('modal-model').value = agent.model || '';
    document.getElementById('modal-temp').value = agent.temperature || 0.7;
    document.getElementById('modal-tokens').value = agent.max_tokens || 2048;
    document.getElementById('modal-system-prompt').value = agent.system_prompt || '';
    document.getElementById('model-edit-modal').style.display = 'flex';
}

function closeModelModal() {
    document.getElementById('model-edit-modal').style.display = 'none';
}

function saveModelConfig() {
    var agentId = parseInt(document.getElementById('modal-agent-id').value);
    var model = document.getElementById('modal-model').value;
    var temperature = parseFloat(document.getElementById('modal-temp').value);
    var maxTokens = parseInt(document.getElementById('modal-tokens').value);
    var systemPrompt = document.getElementById('modal-system-prompt').value;

    api('/api/models/update', {
        method: 'POST',
        body: JSON.stringify({
            agent_id: agentId,
            model: model,
            temperature: temperature,
            max_tokens: maxTokens,
            system_prompt: systemPrompt,
        }),
    }).then(function() {
        closeModelModal();
        loadAgentList().then(function() {
            aaTabLoaded['models'] = false;
            switchTab('models');
        });
    }).catch(function(e) {
        alert('Save failed: ' + e.message);
    });
}

// ============================================================
// A/B Testing Tab
// ============================================================

function runABTest() {
    var modelA = document.getElementById('ab-model-a').value;
    var modelB = document.getElementById('ab-model-b').value;
    var prompt = document.getElementById('ab-prompt').value.trim();
    var capability = document.getElementById('ab-capability').value.trim() || 'general';

    if (!modelA || !modelB || !prompt) { alert('Select both models and enter a test prompt.'); return; }

    var btn = document.getElementById('btn-run-ab');
    btn.disabled = true;
    btn.textContent = 'TESTING...';
    showABMessage('');
    renderJudge(null);

    api('/api/ab-test/run', {
        method: 'POST',
        body: JSON.stringify({ model_a: modelA, model_b: modelB, test_prompt: prompt, capability: capability }),
    }).then(function(data) {
        if (data.status === 'budget_exhausted') {
            showABMessage('Cloud provider ' + data.provider + ' is out of free weekly budget (' + data.weekly_remaining + ' left).');
            return;
        }
        if (data.status === 'approval_unavailable') {
            showABMessage(data.message || 'Cloud comparison approval is unavailable right now.');
            return;
        }
        if (data.status === 'pending_approval') {
            showABMessage('⏳ Pending your Telegram approval… results will appear when you approve.');
            pollABRun(data.run_id);
            return;
        }
        // existing synchronous both-local path (no `status` field on this response)
        renderABResults(data.results);
        aaTabLoaded['ab-test'] = false;
        loadABHistory();
    }).catch(function(e) {
        alert('A/B test failed: ' + e.message);
    }).finally(function() {
        btn.disabled = false;
        btn.textContent = 'RUN A/B TEST';
    });
}

// Renders one {a, b} result pair into the comparison panel. Shared by the
// synchronous both-local path and pollABRun()'s 'completed' branch.
function renderABResults(results) {
    aaLastABResults = results || {};
    aaDiffShown = false;
    var diffBtn = document.getElementById('btn-toggle-diff');
    if (diffBtn) diffBtn.textContent = 'Show divergence';

    var resultContainer = document.getElementById('ab-result-container');
    resultContainer.style.display = 'block';

    ['a', 'b'].forEach(function(side) {
        var r = (results && results[side]) || {};
        document.getElementById('ab-name-' + side).textContent = r.model || '-';
        var stats = (r.duration_ms != null ? r.duration_ms + 'ms' : '-')
            + ' | ' + ((r.prompt_tokens || 0) + (r.completion_tokens || 0)) + ' tokens'
            + ' | ' + (r.success ? 'OK' : 'FAILED');
        if (r.provider) { stats += ' | ☁ ' + r.provider; }
        document.getElementById('ab-stats-' + side).textContent = stats;
        document.getElementById('ab-response-' + side).textContent = r.response || r.error || 'No response';
    });
}

// Poll a cloud-comparison run until the async worker finishes (or cancels).
function pollABRun(runId) {
    var tries = 0;
    var iv = setInterval(function() {
        tries++;
        api('/api/ab-test/run/' + runId).then(function(d) {
            if (d.status === 'completed') {
                clearInterval(iv);
                renderABResults(d.results);
                renderJudge(d.judge);
                showABMessage('');
                aaTabLoaded['ab-test'] = false;
                loadABHistory();
            } else if (d.status === 'cancelled') {
                clearInterval(iv);
                showABMessage('Cloud comparison ' + (d.cancelled_reason || 'cancelled') + '.');
            } else if (tries > 100) {
                clearInterval(iv);
                showABMessage('Timed out waiting for results.');
            }
        }).catch(function(e) {
            if (tries > 100) {
                clearInterval(iv);
                showABMessage('Error polling for results: ' + e.message);
            }
        });
    }, 3000);
}

// Local-judge (qwen2.5:7b) verdict card. Pass null/undefined to clear it.
function renderJudge(j) {
    var el = document.getElementById('ab-judge-card');
    if (!el) return;
    if (!j || (j.score_a == null && j.score_b == null)) { el.innerHTML = ''; return; }
    var win = j.winner === 'a' ? 'Model A' : j.winner === 'b' ? 'Model B' : 'Tie';
    el.innerHTML = '<div class="aa-card"><b>Local judge (qwen2.5:7b)</b> — '
        + 'A: ' + (j.score_a != null ? j.score_a : '—') + ' · B: ' + (j.score_b != null ? j.score_b : '—')
        + ' · Winner: <b>' + win + '</b><br>'
        + '<span class="aa-badge-dim"></span>' + escHtml(j.rationale || '') + '</div>';
}

// Word-level diff — no external lib (strict CSP). Highlights tokens in A
// that aren't in B, and vice-versa, via <mark class="aa-diff">.
function wordDiff(a, b) {
    var at = new Set((a || '').split(/\s+/));
    var bt = new Set((b || '').split(/\s+/));
    var mark = function(text, other) {
        return (text || '').split(/\s+/).map(function(w) {
            return other.has(w) ? escHtml(w) : '<mark class="aa-diff">' + escHtml(w) + '</mark>';
        }).join(' ');
    };
    return { a: mark(a, bt), b: mark(b, at) };
}

// Toggles #ab-response-{a,b} between raw text and the word-diff HTML view.
function toggleDiff() {
    if (!aaLastABResults) return;
    aaDiffShown = !aaDiffShown;
    var btn = document.getElementById('btn-toggle-diff');
    var ra = aaLastABResults.a || {};
    var rb = aaLastABResults.b || {};
    if (aaDiffShown) {
        var diff = wordDiff(ra.response || '', rb.response || '');
        setContent('ab-response-a', diff.a);
        setContent('ab-response-b', diff.b);
        if (btn) btn.textContent = 'Hide divergence';
    } else {
        document.getElementById('ab-response-a').textContent = ra.response || ra.error || 'No response';
        document.getElementById('ab-response-b').textContent = rb.response || rb.error || 'No response';
        if (btn) btn.textContent = 'Show divergence';
    }
}

// Status/progress line above the history table (pending approval, budget
// exhausted, cancelled, timeout). textContent-only — no HTML rendering, so
// no escaping concerns even though messages interpolate provider/model text.
function showABMessage(msg) {
    var el = document.getElementById('ab-message');
    if (el) el.textContent = msg || '';
}

function loadABHistory() {
    setContent('ab-history-container', '<div class="aa-empty"><span class="aa-loading"></span> Loading...</div>');
    api('/api/ab-test/history').then(function(data) {
        var tests = data.tests || [];
        if (!tests.length) {
            setContent('ab-history-container', '<div class="aa-empty">No A/B tests yet.</div>');
            return;
        }
        var html = '<table class="aa-table"><thead><tr><th>ID</th><th>Model A</th><th>Model B</th><th>Capability</th><th>Date</th></tr></thead><tbody>';
        tests.forEach(function(t) {
            var cfg = t.test_config || {};
            var resA = t.results && t.results[0] ? t.results[0] : {};
            var resB = t.results && t.results[1] ? t.results[1] : {};
            html += '<tr>'
                + '<td>#' + t.id + '</td>'
                + '<td>' + esc(cfg.model_a || resA.model || '-') + ' <span class="aa-card-dept">' + (resA.duration_ms || 0) + 'ms</span></td>'
                + '<td>' + esc(cfg.model_b || resB.model || '-') + ' <span class="aa-card-dept">' + (resB.duration_ms || 0) + 'ms</span></td>'
                + '<td>' + esc(cfg.capability || '-') + '</td>'
                + '<td>' + (t.started_at ? new Date(t.started_at).toLocaleDateString() : '-') + '</td>'
                + '</tr>';
        });
        html += '</tbody></table>';
        setContent('ab-history-container', html);
    }).catch(function(e) {
        setContent('ab-history-container', '<div class="aa-empty">Error: ' + esc(e.message) + '</div>');
    });
}

// ============================================================
// Knowledge Tab
// ============================================================

function loadKnowledgeAgents() {
    setContent('knowledge-container', '<div class="aa-empty"><span class="aa-loading"></span> Loading...</div>');
    api('/api/knowledge/agents').then(function(data) {
        var agents = data.agents || [];
        if (!agents.length) {
            setContent('knowledge-container', '<div class="aa-empty">No active agents found.</div>');
            return;
        }

        var depts = {};
        agents.forEach(function(a) {
            var d = a.department || 'Unassigned';
            if (!depts[d]) depts[d] = [];
            depts[d].push(a);
        });

        var html = '';
        Object.keys(depts).sort().forEach(function(dept) {
            html += '<div class="aa-dept-section">'
                + '<div class="aa-dept-header"><span>' + esc(dept) + '</span></div>';
            depts[dept].forEach(function(a) {
                html += '<div class="aa-prompt-card" data-agent-id="' + a.id + '">'
                    + '<div class="aa-card-header">'
                    + '<span class="aa-card-name">' + esc(a.display_name || a.name) + '</span>'
                    + '<span class="aa-card-model">' + esc(a.model || '') + '</span>'
                    + '</div>'
                    + (a.has_system_prompt
                        ? '<div class="aa-prompt-preview">' + esc(a.system_prompt_preview) + '</div>'
                            + '<div class="aa-prompt-stats">' + a.system_prompt_length + ' characters</div>'
                        : '<div class="aa-no-prompt">No system prompt configured</div>')
                    + '</div>';
            });
            html += '</div>';
        });
        setContent('knowledge-container', html);

        // Attach click handlers via delegation (avoids inline JS with backtick escaping)
        document.getElementById('knowledge-container').addEventListener('click', function(e) {
            var card = e.target.closest('.aa-prompt-card');
            if (!card) return;
            var aid = parseInt(card.getAttribute('data-agent-id'));
            var agent = null;
            for (var i = 0; i < aaAgents.length; i++) {
                if (aaAgents[i].id === aid) { agent = aaAgents[i]; break; }
            }
            if (agent) {
                openPromptModal(aid, agent.display_name || agent.name, agent.system_prompt || '');
            }
        });
    }).catch(function(e) {
        setContent('knowledge-container', '<div class="aa-empty">Error: ' + esc(e.message) + '</div>');
    });
}

function openPromptModal(agentId, name, prompt) {
    document.getElementById('prompt-modal-agent-id').value = agentId;
    document.getElementById('prompt-modal-name').textContent = name;
    document.getElementById('prompt-modal-text').value = prompt;
    document.getElementById('prompt-char-count').textContent = prompt.length;
    document.getElementById('prompt-edit-modal').style.display = 'flex';

    document.getElementById('prompt-modal-text').oninput = function() {
        document.getElementById('prompt-char-count').textContent = this.value.length;
    };
}

function closePromptModal() {
    document.getElementById('prompt-edit-modal').style.display = 'none';
}

function savePrompt() {
    var agentId = parseInt(document.getElementById('prompt-modal-agent-id').value);
    var prompt = document.getElementById('prompt-modal-text').value;

    api('/api/knowledge/update-prompt', {
        method: 'POST',
        body: JSON.stringify({ agent_id: agentId, system_prompt: prompt }),
    }).then(function() {
        closePromptModal();
        loadAgentList().then(function() {
            aaTabLoaded['knowledge'] = false;
            switchTab('knowledge');
        });
    }).catch(function(e) {
        alert('Save failed: ' + e.message);
    });
}

// ============================================================
// Helpers
// ============================================================

function renderLevelBar(level) {
    var html = '<div class="aa-level-bar">';
    for (var i = 1; i <= 5; i++) {
        var filled = i <= level ? 'filled lv' + level : '';
        html += '<div class="aa-level-pip ' + filled + '"></div>';
    }
    html += '<span style="font-size:0.65rem;margin-left:4px;color:var(--aa-text-dim)">Lv' + level + '</span></div>';
    return html;
}

function scoreClass(score) {
    if (score >= 0.7) return 'aa-score-high';
    if (score >= 0.4) return 'aa-score-mid';
    return 'aa-score-low';
}
