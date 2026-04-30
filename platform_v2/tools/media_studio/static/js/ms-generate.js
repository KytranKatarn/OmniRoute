(function () {
  'use strict';
  var _API = '/tools/media-studio';
  var _type = 'portrait';
  var _agentId = null;

  function _get(path) {
    return fetch(_API + path, { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function _post(path, body) {
    return fetch(_API + path, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function _el(id) { return document.getElementById(id); }

  window.msGenerate = {
    init: function () {
      msGenerate._loadPicker();
      msGenerate._loadModels();
      if (_agentId) msGenerate.selectAgent(_agentId);
    },

    preselectAgent: function (agentId) {
      _agentId = agentId;
    },

    selectType: function (type) {
      _type = type;
      document.querySelectorAll('.ms-gen-type-card').forEach(function (el) {
        el.classList.toggle('ms-gen-type-active', el.dataset.type === type);
      });
      if (type === 'social') {
        switchMsTab('social-video');
        return;
      }
      var step2 = _el('msGenStep2');
      if (step2) step2.style.display = 'block';
      var promptEl = _el('msGenPrompt');
      if (promptEl) promptEl.value = '';
      var prefill = _el('msGenPromptPrefill');
      if (prefill) prefill.textContent = '';
    },

    _loadPicker: function () {
      _get('/api/agents/picker').then(function (data) {
        var el = _el('msGenAgentPicker');
        if (!el) return;
        el.textContent = '';
        var all = (data.humans || []).concat(data.ai_agents || []);
        all.forEach(function (agent) {
          var pill = document.createElement('button');
          pill.className = 'ms-gen-agent-pill';
          pill.dataset.agentId = agent.id;
          pill.textContent = agent.display_name || agent.name;
          pill.onclick = function () { msGenerate.selectAgent(agent.id); };
          el.appendChild(pill);
        });
        if (_agentId) msGenerate.selectAgent(_agentId);
      }).catch(function (err) { console.warn('[msGenerate] picker load failed:', err); });
    },

    _loadModels: function () {
      _get('/api/models').then(function (data) {
        var sel = _el('msGenModel');
        if (!sel) return;
        sel.textContent = '';
        (data.models || []).forEach(function (m) {
          var opt = document.createElement('option');
          opt.value = m.id || m.name;
          opt.textContent = m.display_name || m.name;
          sel.appendChild(opt);
        });
      }).catch(function () {});
    },

    selectAgent: function (agentId) {
      _agentId = agentId;
      document.querySelectorAll('.ms-gen-agent-pill').forEach(function (el) {
        el.classList.toggle('ms-gen-agent-active', String(el.dataset.agentId) === String(agentId));
      });
      var step3 = _el('msGenStep3');
      if (step3) step3.style.display = 'block';
      _get('/api/portraits/' + agentId + '/identity').then(function (d) {
        var promptEl = _el('msGenPrompt');
        if (promptEl && d.identity_prompt) {
          promptEl.value = d.identity_prompt;
        }
        var prefill = _el('msGenPromptPrefill');
        if (prefill) {
          prefill.textContent = d.identity_prompt
            ? '← pre-filled from ' + d.agent_name + '\'s identity — edit to refine'
            : '';
        }
      }).catch(function (err) { console.warn('[msGenerate] identity load failed:', err); });
    },

    submit: function () {
      var promptEl = _el('msGenPrompt');
      var prompt = promptEl ? promptEl.value.trim() : '';
      var statusEl = _el('msGenStatus');

      if (!prompt) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,0.9)'; statusEl.textContent = '⚠ Prompt is required.'; }
        return;
      }

      var btn = _el('msGenBtn');
      if (btn) btn.disabled = true;
      if (statusEl) { statusEl.style.color = '#888'; statusEl.textContent = 'Queuing via P.I.X.E.L. → Department HQ…'; }

      var negPromptEl = _el('msGenNegPrompt');
      var modelEl = _el('msGenModel');

      var payload = {
        prompt: prompt,
        media_type: 'image',
        negative_prompt: negPromptEl ? negPromptEl.value.trim() : '',
        model: modelEl ? modelEl.value : '',
        width: 1024,
        height: 1024,
        steps: 30,
        seed: -1
      };
      if (_agentId) payload.agent_id = _agentId;

      _post('/api/generate', payload).then(function (data) {
        if (btn) btn.disabled = false;
        if (statusEl) {
          statusEl.style.color = 'rgba(34,197,94,0.9)';
          statusEl.textContent = '✓ Queued #' + (data.queue_id || '—') + ' — P.I.X.E.L. generating via DHQ';
        }
        setTimeout(function () {
          switchMsTab('queue');
          if (statusEl) statusEl.textContent = '';
        }, 1200);
      }).catch(function (err) {
        if (btn) btn.disabled = false;
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,0.9)'; statusEl.textContent = '⚠ Failed: ' + err.message; }
      });
    }
  };
})();
