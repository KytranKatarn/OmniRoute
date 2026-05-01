(function () {
  'use strict';
  var _API = '/tools/media-studio';
  var _type = 'portrait';
  var _agentId = null;
  var _mode = 'lifestyle';
  var _themeId = null;
  var _sceneId = null;
  var _lifestyleResult = null;

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
      var lifestyleStep = _el('msGenLifestyleStep');
      var preview = _el('msGenLifestylePreview');
      if (type === 'lifestyle') {
        if (lifestyleStep) lifestyleStep.style.display = 'block';
        var step2 = _el('msGenStep2');
        if (step2) step2.style.display = 'block';
        var step3 = _el('msGenStep3');
        if (step3) step3.style.display = 'none';
        msGenerate._loadThemesForLifestyle();
        return;
      }
      if (lifestyleStep) lifestyleStep.style.display = 'none';
      if (preview) preview.style.display = 'none';
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

    selectMode: function (mode) {
      _mode = mode;
      document.querySelectorAll('.ms-gen-mode-btn').forEach(function (b) {
        var active = b.dataset.mode === mode;
        b.style.background = active ? 'rgba(59,130,246,0.12)' : 'transparent';
        b.style.borderColor = active ? 'rgba(59,130,246,0.4)' : '#333';
        b.style.color = active ? '#60a5fa' : '#555';
      });
    },

    _loadThemesForLifestyle: function () {
      var picker = _el('msGenThemePicker');
      if (!picker || picker.childElementCount > 0) return;
      _get('/api/themes').then(function (data) {
        picker.textContent = '';
        (data.themes || []).forEach(function (theme) {
          var btn = document.createElement('button');
          btn.dataset.themeId = theme.id;
          btn.style.cssText = 'background:#0d1117;border:1px solid ' + (theme.accent_color || '#333') +
            '44;color:' + (theme.accent_color || '#888') + ';padding:4px 10px;border-radius:3px;font-size:0.58rem;cursor:pointer;';
          btn.textContent = theme.name;
          btn.onclick = (function (t) { return function () { msGenerate.selectThemeForScene(t.id, t.accent_color); }; })(theme);
          picker.appendChild(btn);
        });
      }).catch(function (err) { console.warn('[msGen] loadThemes failed:', err); });
    },

    selectThemeForScene: function (themeId, accentColor) {
      _themeId = themeId;
      _sceneId = null;
      document.querySelectorAll('#msGenThemePicker button').forEach(function (b) {
        var active = String(b.dataset.themeId) === String(themeId);
        b.style.background = active ? (accentColor || '#3b82f6') + '22' : '#0d1117';
        b.style.borderColor = active ? (accentColor || '#3b82f6') : (accentColor || '#333') + '44';
      });
      var wrap = _el('msGenScenePickerWrap');
      var scenePicker = _el('msGenScenePicker');
      if (wrap) wrap.style.display = 'none';
      if (scenePicker) scenePicker.textContent = '';
      _get('/api/themes/' + themeId + '/scenes').then(function (data) {
        if (!scenePicker) return;
        (data.scenes || []).forEach(function (scene) {
          var btn = document.createElement('button');
          btn.dataset.sceneId = scene.id;
          btn.style.cssText = 'background:#0d1117;border:1px solid #1a2a3a;color:#888;padding:5px 10px;border-radius:3px;font-size:0.6rem;cursor:pointer;';
          btn.textContent = scene.name + (scene.generation_type === 'selfie' ? ' 🤳' : '');
          btn.onclick = (function (s) { return function () { msGenerate.selectScene(s); }; })(scene);
          scenePicker.appendChild(btn);
        });
        if (wrap) wrap.style.display = 'block';
      }).catch(function (err) { console.warn('[msGen] loadScenes failed:', err); });
    },

    selectScene: function (scene) {
      _sceneId = scene.id;
      document.querySelectorAll('#msGenScenePicker button').forEach(function (b) {
        var active = String(b.dataset.sceneId) === String(scene.id);
        b.style.background = active ? 'rgba(59,130,246,0.12)' : '#0d1117';
        b.style.borderColor = active ? '#3b82f6' : '#1a2a3a';
        b.style.color = active ? '#60a5fa' : '#888';
      });
      if (scene.generation_type) msGenerate.selectMode(scene.generation_type);
    },

    submitLifestyle: function () {
      var statusEl = _el('msGenStatus');
      if (!_agentId) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Select an agent first.'; }
        return;
      }
      if (!_sceneId) {
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Select a scene first.'; }
        return;
      }
      var btn = _el('msGenBtn');
      if (btn) btn.disabled = true;
      if (statusEl) { statusEl.style.color = '#888'; statusEl.textContent = '⏳ M.U.S.E. refining → P.I.X.E.L. generating…'; }
      _post('/api/generate/lifestyle', {
        agent_id: _agentId,
        scene_id: _sceneId,
        generation_type: _mode,
        refine: true,
      }).then(function (data) {
        _lifestyleResult = data;
        if (btn) btn.disabled = false;
        if (statusEl) { statusEl.style.color = 'rgba(34,197,94,.9)'; statusEl.textContent = '✓ Queued #' + data.queue_id + ' — check Queue tab'; }
        var preview = _el('msGenLifestylePreview');
        var captionEl = _el('msGenLifestyleCaption');
        if (preview) preview.style.display = 'block';
        if (captionEl) captionEl.textContent = data.caption || '(S.I.G.N.A.L. generating caption…)';
        setTimeout(function () { switchMsTab('queue'); }, 2000);
      }).catch(function (err) {
        if (btn) btn.disabled = false;
        if (statusEl) { statusEl.style.color = 'rgba(239,68,68,.9)'; statusEl.textContent = '⚠ Failed: ' + err.message; }
      });
    },

    sendToSocialVideo: function () {
      if (!_lifestyleResult) return;
      switchMsTab('social-video');
      setTimeout(function () {
        if (_themeId && window.msSocialVideo) msSocialVideo.selectThemeById(_themeId);
        var quoteEl = document.getElementById('msSvQuote');
        if (quoteEl && _lifestyleResult.caption) quoteEl.value = _lifestyleResult.caption;
      }, 350);
    },

    submit: function () {
      if (_type === 'lifestyle') { msGenerate.submitLifestyle(); return; }
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
