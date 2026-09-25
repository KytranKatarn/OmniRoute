/* Agent Profile Detail Modal — Task #1916
 * window.agentProfileModal = { open, close }
 *
 * XSS policy: all dynamic values from the API are placed via .textContent
 * or element properties. No innerHTML setter on dynamic data.
 */
(function () {
  'use strict';

  const OVERLAY_ID = 'agentDetailOverlay';
  const EDITABLE_FIELDS = [
    'display_name', 'title', 'bio', 'acronym', 'acronym_expansion',
    'pronouns', 'current_grade',
    'department', 'floor', 'writing_tone', 'is_department_ai',
    'reports_to_agent_id',
    'model', 'temperature', 'max_tokens', 'system_prompt',
    'communication_style', 'appearance_notes',
    'age_range', 'gender', 'ethnicity',
    'social_topics', 'auto_approve_threshold',
  ];
  const SENSITIVE_FIELDS = new Set([
    'model', 'temperature', 'max_tokens', 'system_prompt',
    'is_department_ai', 'reports_to_agent_id',
  ]);
  const SECTIONS = [
    { title: 'Identity', sensitive: false, fields: [
      ['display_name', 'Display Name', 'text'],
      ['title', 'Title', 'text'],
      ['acronym', 'Acronym', 'text'],
      ['acronym_expansion', 'Acronym Meaning', 'text'],
      ['pronouns', 'Pronouns', 'text'],
      ['current_grade', 'Current Grade', 'text'],
      ['bio', 'Bio', 'textarea', 'full'],
    ]},
    { title: 'Classification', sensitive: false, fields: [
      ['department', 'Department', 'text'],
      ['floor', 'Floor', 'text'],
      ['writing_tone', 'Writing Tone', 'text'],
      ['is_department_ai', 'Department AI', 'bool'],
      ['reports_to_agent_id', 'Reports To (agent id)', 'int'],
    ]},
    { title: 'Dispatch', sensitive: true, fields: [
      ['model', 'Model', 'text'],
      ['temperature', 'Temperature', 'float'],
      ['max_tokens', 'Max Tokens', 'int'],
      ['system_prompt', 'System Prompt', 'textarea', 'full', 'prompt'],
    ]},
    { title: 'Appearance', sensitive: false, fields: [
      ['age_range', 'Age Range', 'text'],
      ['gender', 'Gender', 'text'],
      ['ethnicity', 'Ethnicity', 'text'],
      ['communication_style', 'Communication Style', 'text'],
      ['appearance_notes', 'Appearance Notes', 'textarea', 'full'],
    ]},
    { title: 'Voice & Social', sensitive: false, fields: [
      ['social_topics', 'Social Topics (comma-separated)', 'csvlist', 'full'],
      ['auto_approve_threshold', 'Auto-Approve $ Threshold', 'float'],
    ]},
  ];

  const state = { agentId: null, snapshot: null, mode: 'view' };

  // DOM builder — safe by construction. No innerHTML on user data.
  function el(tag, cls) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (let i = 2; i < arguments.length; i++) {
      const child = arguments[i];
      if (child === null || child === undefined) continue;
      if (typeof child === 'string') e.appendChild(document.createTextNode(child));
      else e.appendChild(child);
    }
    return e;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function toast(overlay, msg, kind) {
    let t = overlay.querySelector('.apm-toast');
    if (!t) {
      t = el('div', 'apm-toast');
      (overlay.querySelector('.bm-content') || overlay).appendChild(t);
    }
    t.className = 'apm-toast show ' + (kind || 'ok');
    t.textContent = msg;
    setTimeout(function () { t.className = 'apm-toast'; }, 2500);
  }

  async function fetchProfile(agentId) {
    const r = await fetch(
      '/tools/department-hq/api/agent/' + agentId + '/profile',
      { credentials: 'same-origin' }
    );
    if (!r.ok) throw new Error('profile fetch failed: ' + r.status);
    return r.json();
  }

  async function fetchPortrait(agentId) {
    try {
      const r = await fetch(
        '/tools/media-studio/api/portraits/' + agentId,
        { credentials: 'same-origin' }
      );
      if (!r.ok) return null;
      return r.json();
    } catch (_) {
      return null;
    }
  }

  function formatView(val, type) {
    if (val === null || val === undefined || val === '') return '—';
    if (type === 'bool') return val ? 'yes' : 'no';
    if (type === 'csvlist') return Array.isArray(val) ? val.join(', ') : String(val);
    return String(val);
  }

  function buildInput(name, type, val, extraCls) {
    let input;
    if (type === 'textarea') {
      input = document.createElement('textarea');
      input.value = (val === null || val === undefined) ? '' : String(val);
    } else if (type === 'bool') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = !!val;
    } else if (type === 'csvlist') {
      input = document.createElement('input');
      input.type = 'text';
      input.value = Array.isArray(val) ? val.join(', ') : (val || '');
      input.dataset.type = 'csvlist';
    } else {
      input = document.createElement('input');
      input.type = (type === 'int' || type === 'float') ? 'number' : 'text';
      if (type === 'float') input.step = '0.01';
      input.value = (val === null || val === undefined) ? '' : String(val);
      input.dataset.type = type;
    }
    input.className = 'apm-input' + (extraCls ? ' apm-' + extraCls : '');
    input.dataset.edit = name;
    return input;
  }

  function buildField(f, agent) {
    const [name, label, type, layout, extraCls] = f;
    const val = agent[name];
    const wrap = el('div', 'apm-field' + (layout === 'full' ? ' apm-field-full' : ''));
    wrap.appendChild(el('div', 'apm-field-label', label));

    const viewBox = el('div', 'apm-view-only apm-field-value');
    viewBox.dataset.view = name;
    viewBox.textContent = formatView(val, type);
    wrap.appendChild(viewBox);

    const editBox = el('div', 'apm-edit-only');
    editBox.appendChild(buildInput(name, type, val, extraCls));
    wrap.appendChild(editBox);
    return wrap;
  }

  function buildSection(sec, agent) {
    const section = el('div', 'apm-section');
    const titleRow = el('div', 'apm-section-title');
    titleRow.appendChild(document.createTextNode(sec.title));
    if (sec.sensitive) {
      titleRow.appendChild(el('span', 'apm-sensitive-mark',
        '⚠️ Changes affect routing'));
    }
    section.appendChild(titleRow);
    const grid = el('div', 'apm-grid');
    sec.fields.forEach(function (f) { grid.appendChild(buildField(f, agent)); });
    section.appendChild(grid);
    return section;
  }

  function buildHeaderBand(agent) {
    const band = el('div', 'apm-header-band');

    let portrait;
    if (agent.avatar_url) {
      portrait = document.createElement('img');
      portrait.className = 'apm-portrait';
      portrait.src = agent.avatar_url;
      portrait.alt = '';
    } else {
      portrait = el('div', 'apm-portrait');
    }
    band.appendChild(portrait);

    const col = el('div');
    col.appendChild(el('div', 'apm-name', agent.display_name || agent.name));
    const codeline = el('div', 'apm-codename', agent.name);
    if (agent.acronym) {
      codeline.appendChild(document.createTextNode(' · '));
      codeline.appendChild(document.createTextNode(agent.acronym));
    }
    col.appendChild(codeline);

    const sub = el('div', 'apm-subline');
    sub.appendChild(el('span', null, agent.department || '—'));
    sub.appendChild(el('span', null, '·'));
    sub.appendChild(el('span', null, agent.floor || '—'));
    const shift = el('button', 'apm-pill',
      String(agent.shift_state || 'unknown').toUpperCase());
    shift.dataset.action = 'toggle-shift';
    shift.title = 'Click to cycle shift state';
    sub.appendChild(shift);
    col.appendChild(sub);

    band.appendChild(col);

    const editCol = el('div', 'apm-view-only');
    const editBtn = el('button', 'apm-btn', 'EDIT');
    editBtn.dataset.action = 'edit';
    editCol.appendChild(editBtn);
    band.appendChild(editCol);
    return band;
  }

  // ── Skills (add/update — Task #10) ─────────────────────────────────────
  // Self-contained widget: renders current skills as chips + an add/update
  // form that POSTs {skill_name, level, category} to the existing endpoint
  // (note: `level`/`category`, NOT proficiency_level/skill_category — that's
  // the DB column naming, the API contract is different and must not change).
  function renderSkillChips(listEl, skills) {
    clear(listEl);
    if (skills && skills.length) {
      skills.slice(0, 30).forEach(function (s) {
        const label = (s.skill_name || s.name || s) +
          (s.proficiency_level ? ' · Lv' + s.proficiency_level : '') +
          (s.skill_category ? ' [' + s.skill_category + ']' : '');
        listEl.appendChild(el('span', 'apm-chip', label));
      });
    } else {
      const em = el('em'); em.style.opacity = '0.6';
      em.textContent = 'No skills recorded';
      listEl.appendChild(em);
    }
  }

  async function refreshSkillChips(agentId, listEl) {
    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + agentId + '/skills',
        { credentials: 'same-origin' }
      );
      const j = await r.json();
      renderSkillChips(listEl, (j && j.skills) || []);
    } catch (e) {
      // leave existing chips in place — the add form already reported the error
    }
  }

  function buildSkillsSection(agentId, skills) {
    const sk = el('div', 'apm-section');
    const skTitle = el('div', 'apm-section-title');
    skTitle.appendChild(document.createTextNode('Skills '));
    const skLink = el('a', 'apm-deeplink', '→ Academy');
    skLink.href = '/tools/agent-academy#skills';
    skTitle.appendChild(skLink);
    sk.appendChild(skTitle);

    const list = el('div', 'apm-skills-list');
    renderSkillChips(list, skills);
    sk.appendChild(list);

    const addRow = el('div', 'apm-facts-add');
    addRow.style.cssText = 'display:flex;gap:.4rem;margin-top:.6rem;' +
      'flex-wrap:wrap;align-items:center';

    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'apm-input';
    nameInput.placeholder = 'skill_name (e.g. research)';
    nameInput.style.cssText = 'flex:2;min-width:160px';

    const levelInput = document.createElement('input');
    levelInput.type = 'number';
    levelInput.className = 'apm-input';
    levelInput.min = '1'; levelInput.max = '5'; levelInput.value = '1';
    levelInput.title = 'level 1-5';
    levelInput.style.cssText = 'width:70px';

    const catInput = document.createElement('input');
    catInput.type = 'text';
    catInput.className = 'apm-input';
    catInput.placeholder = 'category';
    catInput.value = 'general';
    catInput.style.cssText = 'flex:1;min-width:120px';

    const addBtn = el('button', 'apm-btn apm-btn-primary', 'Add / Update Skill');
    const status = el('span');
    status.style.cssText = 'font-size:.72rem;flex-basis:100%';

    addBtn.onclick = async function () {
      const skill_name = nameInput.value.trim();
      const level = parseInt(levelInput.value, 10);
      const category = catInput.value.trim() || 'general';
      status.textContent = '';
      if (!skill_name) {
        status.textContent = 'skill_name is required';
        status.style.color = '#ff2244';
        return;
      }
      if (!Number.isInteger(level) || level < 1 || level > 5) {
        status.textContent = 'level must be 1-5';
        status.style.color = '#ff2244';
        return;
      }
      addBtn.disabled = true;
      const orig = addBtn.textContent;
      addBtn.textContent = 'Saving…';
      try {
        const r = await fetch(
          '/tools/department-hq/api/agent/' + agentId + '/skills',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
              skill_name: skill_name, level: level, category: category,
            }),
          }
        );
        const j = await r.json().catch(function () { return {}; });
        if (!r.ok || j.success === false) {
          status.textContent = 'Failed: ' + (j.error || r.status);
          status.style.color = '#ff2244';
        } else {
          status.textContent = j.message || 'Saved';
          status.style.color = '#00e58a';
          nameInput.value = '';
          await refreshSkillChips(agentId, list);
        }
      } catch (e) {
        status.textContent = 'Network error';
        status.style.color = '#ff2244';
      }
      addBtn.disabled = false;
      addBtn.textContent = orig;
    };

    addRow.appendChild(nameInput);
    addRow.appendChild(levelInput);
    addRow.appendChild(catInput);
    addRow.appendChild(addBtn);
    addRow.appendChild(status);
    sk.appendChild(addRow);

    return sk;
  }

  function buildReadOnlySections(welfare, perf, voice) {
    const frag = document.createDocumentFragment();

    const pct = function (v) { return v !== undefined && v !== null ?
      (Number(v) * 100).toFixed(0) + '%' : '—'; };
    const wfField = function (label, val) {
      const f = el('div', 'apm-field');
      f.appendChild(el('div', 'apm-field-label', label));
      f.appendChild(el('div', 'apm-field-value', val));
      return f;
    };

    const wf = el('div', 'apm-section');
    const wfTitle = el('div', 'apm-section-title');
    wfTitle.appendChild(document.createTextNode('Welfare '));
    const wfLink = el('a', 'apm-deeplink', '→ Performance');
    wfLink.href = '#performance';
    wfTitle.appendChild(wfLink);
    wf.appendChild(wfTitle);
    const wfGrid = el('div', 'apm-grid');
    wfGrid.appendChild(wfField('Stress', pct(welfare && welfare.stress_level)));
    wfGrid.appendChild(wfField('Energy', pct(welfare && welfare.energy_level)));
    wfGrid.appendChild(wfField('Mood', (welfare && welfare.current_mood) || '—'));
    wf.appendChild(wfGrid);
    frag.appendChild(wf);

    const pf = el('div', 'apm-section');
    const pfTitle = el('div', 'apm-section-title');
    pfTitle.appendChild(document.createTextNode('Performance '));
    const pfLink = el('a', 'apm-deeplink', '→ Performance');
    pfLink.href = '#performance';
    pfTitle.appendChild(pfLink);
    pf.appendChild(pfTitle);
    const pfGrid = el('div', 'apm-grid');
    pfGrid.appendChild(wfField('Tasks Completed',
      String((perf && perf.total_tasks_completed) || 0)));
    pfGrid.appendChild(wfField('Success Rate',
      pct(perf && perf.success_rate)));
    pfGrid.appendChild(wfField('Grade', (perf && perf.current_grade) || '—'));
    pf.appendChild(pfGrid);
    frag.appendChild(pf);

    const vf = el('div', 'apm-section');
    const vfTitle = el('div', 'apm-section-title');
    vfTitle.appendChild(document.createTextNode('TTS Voice '));
    const vfLink = el('a', 'apm-deeplink', '→ Consciousness');
    vfLink.href = '#voice';
    vfTitle.appendChild(vfLink);
    vf.appendChild(vfTitle);
    const vfGrid = el('div', 'apm-grid');
    vfGrid.appendChild(wfField('Profile', (voice && voice.profile_name) || 'Needs review'));
    vfGrid.appendChild(wfField('Speaker', (voice && voice.speaker) || 'Needs review'));
    vfGrid.appendChild(wfField('Emotion', (voice && voice.default_emotion) || 'Needs review'));
    vf.appendChild(vfGrid);
    frag.appendChild(vf);

    return frag;
  }

  // ── Curated Facts (persona grounding — #4959) ──────────────────────────
  // Owner-curated facts this persona may cite in email drafts. Reads/writes the
  // live /api/agent/<id>/facts endpoints. Self-contained; XSS-safe via el()/textContent.
  async function loadFacts(agentId, listEl) {
    clear(listEl);
    listEl.appendChild(el('em', null, 'Loading facts…'));
    let facts = [];
    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + agentId + '/facts',
        { credentials: 'same-origin' }
      );
      const j = await r.json();
      facts = (j && j.facts) || [];
    } catch (e) {
      clear(listEl);
      const em = el('em', null, 'Failed to load facts');
      em.style.color = '#f87171';
      listEl.appendChild(em);
      return;
    }
    clear(listEl);
    if (!facts.length) {
      const em = el('em', null,
        'No curated facts yet. Add facts this persona may cite in email drafts.');
      em.style.cssText = 'opacity:.6;font-size:.78rem';
      listEl.appendChild(em);
      return;
    }
    facts.forEach(function (f) {
      const row = el('div', 'apm-fact-row');
      row.style.cssText = 'display:flex;align-items:center;gap:.5rem;' +
        'padding:.3rem 0;border-bottom:1px solid rgba(255,255,255,.06)';
      if (!f.is_active) row.style.opacity = '0.5';
      const txt = el('span');
      txt.style.cssText = 'flex:1;font-size:.8rem;color:#e2e8f0';
      txt.textContent = f.fact_text + (f.category ? ' [' + f.category + ']' : '');
      row.appendChild(txt);

      const toggle = el('button', 'apm-btn', f.is_active ? 'Deactivate' : 'Activate');
      toggle.onclick = async function () {
        toggle.disabled = true;
        try {
          await fetch('/tools/department-hq/api/agent/facts/' + f.id + '/toggle', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin', body: JSON.stringify({ is_active: !f.is_active }),
          });
        } catch (e) { /* fall through to reload */ }
        loadFacts(agentId, listEl);
      };
      row.appendChild(toggle);

      const del = el('button', 'apm-btn', 'Delete');
      del.onclick = async function () {
        del.disabled = true;
        try {
          await fetch('/tools/department-hq/api/agent/facts/' + f.id + '/delete', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin', body: JSON.stringify({}),
          });
        } catch (e) { /* fall through to reload */ }
        loadFacts(agentId, listEl);
      };
      row.appendChild(del);
      listEl.appendChild(row);
    });
  }

  function buildFactsSection(agentId) {
    const sec = el('div', 'apm-section');
    const title = el('div', 'apm-section-title');
    title.appendChild(document.createTextNode('Curated Facts '));
    const hint = el('span', 'apm-deeplink', 'persona may cite these in email drafts');
    hint.style.cssText = 'font-size:.68rem;color:#64748b;text-decoration:none';
    title.appendChild(hint);
    sec.appendChild(title);

    const list = el('div', 'apm-facts-list');
    sec.appendChild(list);

    const addRow = el('div', 'apm-facts-add');
    addRow.style.cssText = 'display:flex;gap:.4rem;margin-top:.5rem;flex-wrap:wrap';
    const factInput = document.createElement('input');
    factInput.type = 'text';
    factInput.className = 'apm-input';
    factInput.placeholder = 'e.g. Standard onboarding SLA is 3 business days.';
    factInput.style.cssText = 'flex:2;min-width:180px';
    const catInput = document.createElement('input');
    catInput.type = 'text';
    catInput.className = 'apm-input';
    catInput.placeholder = 'category (optional)';
    catInput.style.cssText = 'flex:1;min-width:120px';
    const addBtn = el('button', 'apm-btn apm-btn-primary', 'Add');
    addBtn.onclick = async function () {
      const text = factInput.value.trim();
      if (!text) return;
      addBtn.disabled = true;
      try {
        await fetch('/tools/department-hq/api/agent/' + agentId + '/facts', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ fact_text: text, category: catInput.value.trim() || null }),
        });
        factInput.value = '';
        catInput.value = '';
        loadFacts(agentId, list);
      } catch (e) { /* ignore */ }
      addBtn.disabled = false;
    };
    addRow.appendChild(factInput);
    addRow.appendChild(catInput);
    addRow.appendChild(addBtn);
    sec.appendChild(addRow);

    loadFacts(agentId, list);
    return sec;
  }

  // ── Decommission (Task #10) ─────────────────────────────────────────────
  // Never deletes an agent — decommission_agent() only flips shift_state.
  // The precheck's warnings are shown VERBATIM before any confirmation is
  // possible; confirming re-POSTs with acknowledge_warnings:true. A 409
  // means the server did not accept that acknowledgement (e.g. the warning
  // set changed underneath us) — the fresh warnings are re-shown and the
  // operator must click Confirm again; nothing here auto-retries.
  // Built as a real DOM tree (el()/textContent only, no innerHTML on
  // dynamic data) per this file's XSS policy — NEVER window.confirm(),
  // which would freeze browser automation.
  function ensureDecommOverlay() {
    let ov = document.getElementById('apmDecommOverlay');
    if (ov) return ov;

    ov = el('div', 'bm-overlay');
    ov.id = 'apmDecommOverlay';
    // The generic .bm-overlay rule is z-index:1000, which sits BEHIND the
    // parent #agentDetailOverlay (z-index:9000) — this modal must render on
    // top of the profile modal it was opened from. #apmConfirmOverlay (the
    // existing sensitive-field confirm) uses 10000 for the same reason.
    ov.style.zIndex = '10000';
    ov.style.setProperty('--bm-accent', '#ff2244');
    ov.style.setProperty('--bm-accent-rgb', '255,34,68');

    const shell = el('div', 'bm-shell');
    shell.style.maxWidth = '480px';

    const frame = el('div', 'bm-frame');
    frame.appendChild(el('div', 'bm-frame-elbow-top'));
    frame.appendChild(el('div', 'bm-frame-seg'));
    frame.appendChild(el('div', 'bm-frame-seg dim'));
    frame.appendChild(el('div', 'bm-frame-light on'));
    frame.appendChild(el('div', 'bm-frame-light amber'));
    frame.appendChild(el('div', 'bm-frame-seg purple'));
    frame.appendChild(el('div', 'bm-frame-fill'));
    frame.appendChild(el('div', 'bm-frame-elbow-bottom'));
    shell.appendChild(frame);

    const content = el('div', 'bm-content');

    const header = el('div', 'bm-header');
    header.appendChild(el('span', 'bm-header-title', 'Confirm Decommission'));
    content.appendChild(header);

    const bodyDiv = el('div', 'bm-body');
    bodyDiv.id = 'apmDecommBody';
    bodyDiv.style.padding = '16px';
    content.appendChild(bodyDiv);

    const footer = el('div', 'bm-footer');
    footer.style.cssText = 'padding:12px 16px;display:flex;gap:8px;justify-content:flex-end';
    const cancelBtn = el('button', 'apm-btn', 'CANCEL');
    cancelBtn.dataset.dx = 'cancel';
    const confirmBtn = el('button', 'apm-btn apm-btn-primary', 'CONFIRM DECOMMISSION');
    confirmBtn.dataset.dx = 'confirm';
    footer.appendChild(cancelBtn);
    footer.appendChild(confirmBtn);
    content.appendChild(footer);

    shell.appendChild(content);
    ov.appendChild(shell);
    document.body.appendChild(ov);
    return ov;
  }

  function renderDecommWarnings(bodyDiv, agentInfo, warnings, extraNote) {
    clear(bodyDiv);
    const p = el('div');
    p.style.marginBottom = '.6rem';
    p.appendChild(document.createTextNode('Decommissioning '));
    const strong = document.createElement('strong');
    strong.textContent = (agentInfo && (agentInfo.display_name || agentInfo.name)) ||
      ('agent #' + (agentInfo && agentInfo.id));
    p.appendChild(strong);
    p.appendChild(document.createTextNode(
      ' sets shift_state to "decommissioned". Agents are never deleted.'));
    bodyDiv.appendChild(p);

    if (warnings && warnings.length) {
      const list = document.createElement('ul');
      list.style.cssText = 'margin:0 0 .5rem;padding-left:1.2rem;color:#ff8a00';
      warnings.forEach(function (w) {
        const li = document.createElement('li');
        li.style.marginBottom = '.4rem';
        li.textContent = (w && w.message) ? w.message : JSON.stringify(w);
        list.appendChild(li);
      });
      bodyDiv.appendChild(list);
    } else {
      const em = el('em', null, 'No warnings from the precheck.');
      em.style.opacity = '0.7';
      bodyDiv.appendChild(em);
    }

    if (extraNote) {
      const note = el('div', null, extraNote);
      note.style.cssText = 'color:#ff2244;margin-top:.5rem;font-size:.8rem';
      bodyDiv.appendChild(note);
    }
  }

  async function handleDecommissionClick(agentId, overlay, body, triggerBtn) {
    triggerBtn.disabled = true;
    let pre;
    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + agentId + '/decommission-precheck',
        { credentials: 'same-origin' }
      );
      pre = await r.json();
      if (!r.ok || pre.success === false) {
        toast(overlay, 'Precheck failed: ' + (pre.error || r.status), 'err');
        triggerBtn.disabled = false;
        return;
      }
    } catch (e) {
      toast(overlay, 'Precheck network error', 'err');
      triggerBtn.disabled = false;
      return;
    }

    const dov = ensureDecommOverlay();
    const dBody = dov.querySelector('#apmDecommBody');
    const confirmBtn = dov.querySelector('[data-dx="confirm"]');
    confirmBtn.disabled = false;
    confirmBtn.textContent = 'CONFIRM DECOMMISSION';
    renderDecommWarnings(dBody, pre.agent, pre.warnings, null);
    dov.classList.add('active');

    dov.onclick = async function (e) {
      const b = e.target.closest('[data-dx]');
      if (!b) return;
      if (b.getAttribute('data-dx') === 'cancel') {
        dov.classList.remove('active');
        triggerBtn.disabled = false;
        return;
      }
      // confirm — explicit, single POST per click; a 409 re-shows warnings
      // and requires another explicit click, never an automatic retry.
      b.disabled = true;
      b.textContent = 'Decommissioning…';
      try {
        const r2 = await fetch(
          '/tools/department-hq/api/agent/' + agentId + '/decommission',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ acknowledge_warnings: true }),
          }
        );
        const out = await r2.json().catch(function () { return {}; });
        if (r2.status === 409 || out.ok === false) {
          renderDecommWarnings(dBody, pre.agent, out.warnings || pre.warnings,
            'Not decommissioned — the server did not accept the ' +
            'acknowledgement. Review the warnings above and click ' +
            'Confirm again.');
          b.disabled = false;
          b.textContent = 'CONFIRM DECOMMISSION';
          triggerBtn.disabled = false;
          return;
        }
        dov.classList.remove('active');
        toast(overlay, 'Agent decommissioned', 'ok');
        state.snapshot = await fetchProfile(state.agentId);
        renderInto(body);
        bindActions(overlay, body);
      } catch (err) {
        b.disabled = false;
        b.textContent = 'CONFIRM DECOMMISSION';
        toast(overlay, 'Decommission network error', 'err');
        triggerBtn.disabled = false;
      }
    };
  }

  function buildDecommissionSection(agent) {
    const sec = el('div', 'apm-section');
    const title = el('div', 'apm-section-title');
    title.appendChild(document.createTextNode('Decommission'));
    sec.appendChild(title);

    const note = el('div');
    note.style.cssText = 'font-size:.78rem;opacity:.75;margin-bottom:.6rem';
    note.textContent = 'Retires the agent (shift_state → decommissioned). ' +
      'Agents are never deleted from the database.';
    sec.appendChild(note);

    const isDecommissioned = agent.shift_state === 'decommissioned';
    const btn = el('button', 'apm-btn',
      isDecommissioned ? 'Already Decommissioned' : 'Decommission Agent');
    btn.style.cssText = 'border-color:#ff2244;color:#ff2244';
    btn.dataset.action = 'decommission';
    if (isDecommissioned) btn.disabled = true;
    sec.appendChild(btn);
    return sec;
  }

  function buildFooter() {
    const f = el('div', 'apm-footer-actions');
    const viewCol = el('div', 'apm-view-only');
    const closeBtn = el('button', 'apm-btn', 'CLOSE');
    closeBtn.dataset.action = 'close';
    viewCol.appendChild(closeBtn);
    f.appendChild(viewCol);

    const editCol = el('div', 'apm-edit-only');
    const cancel = el('button', 'apm-btn', 'CANCEL');
    cancel.dataset.action = 'cancel';
    const save = el('button', 'apm-btn apm-btn-primary', 'SAVE CHANGES');
    save.dataset.action = 'save';
    editCol.appendChild(cancel);
    editCol.appendChild(save);
    f.appendChild(editCol);
    return f;
  }

  function buildPortraitSection(agent) {
    const wrap = document.createElement('div');
    wrap.className = 'apm-section';
    wrap.innerHTML = '<div class="apm-section-label">PORTRAIT</div>';

    // Portrait image
    const imgWrap = document.createElement('div');
    imgWrap.style.cssText = 'display:flex;align-items:flex-start;gap:1rem;margin-top:.5rem;margin-bottom:1rem';
    const img = document.createElement('img');
    const portraitSrc = agent.avatar_thumb_url || agent.avatar_url || '';
    img.src = portraitSrc || '';
    img.alt = agent.display_name + ' portrait';
    img.style.cssText = 'width:80px;height:80px;object-fit:cover;border-radius:8px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.05)';
    const infoWrap = document.createElement('div');
    infoWrap.style.cssText = 'display:flex;flex-direction:column;gap:.4rem;justify-content:center';
    const statusBadge = document.createElement('span');
    statusBadge.style.cssText = 'font-size:.7rem;color:#94a3b8';
    statusBadge.textContent = portraitSrc ? 'Portrait assigned' : 'No portrait yet';
    const msLink = document.createElement('a');
    msLink.href = '/tools/media-studio#portraits';
    msLink.className = 'apm-deeplink';
    msLink.textContent = 'Generate in Media Studio →';
    infoWrap.appendChild(statusBadge);
    infoWrap.appendChild(msLink);

    const regenRow = document.createElement('div');
    regenRow.style.cssText = 'display:flex;flex-direction:column;gap:.35rem;margin-top:.35rem';
    const regenBtn = document.createElement('button');
    regenBtn.className = 'apm-btn';
    regenBtn.textContent = 'Regenerate Portrait (queue for review)';
    regenBtn.title = 'Queues a new portrait. Review it in Media Studio before setting it as canonical.';
    const regenStatus = document.createElement('span');
    regenStatus.style.cssText = 'font-size:.72rem;color:#94a3b8';
    regenBtn.onclick = async function () {
      regenBtn.disabled = true;
      const origLabel = regenBtn.textContent;
      regenBtn.textContent = 'Queuing…';
      regenStatus.textContent = '';
      try {
        const res = await fetch(
          '/tools/department-hq/api/agents/' + agent.id + '/generate-portrait',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({}),
          }
        );
        const data = await res.json().catch(function () { return {}; });
        if (res.ok && data && data.success) {
          regenStatus.textContent = 'queued (queue_id ' + data.queue_id +
            ') — review the result in Media Studio when it completes.';
          regenStatus.style.color = '#00e5ff';
        } else {
          regenStatus.textContent = 'Failed: ' + (data.error || res.status);
          regenStatus.style.color = '#ff2244';
        }
      } catch (e) {
        regenStatus.textContent = 'Network error';
        regenStatus.style.color = '#ff2244';
      }
      regenBtn.disabled = false;
      regenBtn.textContent = origLabel;
    };
    regenRow.appendChild(regenBtn);
    regenRow.appendChild(regenStatus);
    infoWrap.appendChild(regenRow);

    imgWrap.appendChild(img);
    imgWrap.appendChild(infoWrap);
    wrap.appendChild(imgWrap);

    // Prompt editor
    const promptLabel = document.createElement('div');
    promptLabel.style.cssText = 'font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.35rem';
    promptLabel.textContent = 'IDENTITY PROMPT';
    wrap.appendChild(promptLabel);

    const promptTA = document.createElement('textarea');
    promptTA.style.cssText = 'width:100%;min-height:80px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:6px;color:#e2e8f0;font-size:.78rem;padding:.5rem;resize:vertical;font-family:inherit;line-height:1.5';
    promptTA.value = agent.identity_prompt || '';
    promptTA.placeholder = 'Describe this agent\'s portrait — appearance, enhancement, attire...';
    promptTA.disabled = true;
    wrap.appendChild(promptTA);

    // Edit/Save/Cancel row
    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:.5rem;margin-top:.4rem';

    const editBtn = document.createElement('button');
    editBtn.className = 'apm-btn';
    editBtn.textContent = 'Edit Prompt';
    editBtn.onclick = function() {
      promptTA.disabled = false;
      promptTA.focus();
      editBtn.style.display = 'none';
      saveBtn.style.display = '';
      cancelBtn.style.display = '';
    };
    btnRow.appendChild(editBtn);

    const origPrompt = promptTA.value;
    const saveBtn = document.createElement('button');
    saveBtn.className = 'apm-btn apm-btn-primary';
    saveBtn.textContent = 'Save';
    saveBtn.style.display = 'none';
    saveBtn.onclick = async function() {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving…';
      try {
        const res = await fetch('/tools/department-hq/api/agent/' + agent.id, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ identity_prompt: promptTA.value })
        });
        const data = await res.json();
        if (data.success !== false && !data.error) {
          promptTA.disabled = true;
          editBtn.style.display = '';
          saveBtn.style.display = 'none';
          cancelBtn.style.display = 'none';
          saveBtn.textContent = 'Save';
          saveBtn.disabled = false;
        } else {
          saveBtn.textContent = 'Error — retry';
          saveBtn.disabled = false;
        }
      } catch(e) {
        saveBtn.textContent = 'Error — retry';
        saveBtn.disabled = false;
      }
    };
    btnRow.appendChild(saveBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'apm-btn';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.style.display = 'none';
    cancelBtn.onclick = function() {
      promptTA.value = origPrompt;
      promptTA.disabled = true;
      editBtn.style.display = '';
      saveBtn.style.display = 'none';
      cancelBtn.style.display = 'none';
    };
    btnRow.appendChild(cancelBtn);
    wrap.appendChild(btnRow);

    return wrap;
  }

  function renderInto(body) {
    clear(body);
    const agent = state.snapshot.agent;
    const root = el('div', 'apm-root');
    root.appendChild(buildHeaderBand(agent));
    root.appendChild(buildPortraitSection(agent));
    SECTIONS.forEach(function (sec) { root.appendChild(buildSection(sec, agent)); });
    root.appendChild(buildSkillsSection(agent.id, state.snapshot.skills));
    root.appendChild(buildReadOnlySections(
      state.snapshot.welfare, state.snapshot.performance, agent.voice_profile
    ));
    root.appendChild(buildFactsSection(agent.id));
    root.appendChild(buildDecommissionSection(agent));
    root.appendChild(buildFooter());
    body.appendChild(root);
  }

  function bindActions(overlay, body) {
    body.onclick = function (e) {
      const t = e.target.closest('[data-action]');
      if (!t) return;
      const action = t.getAttribute('data-action');
      if (action === 'close') close();
      else if (action === 'cancel') {
        state.mode = 'view'; overlay.setAttribute('data-mode', 'view');
        renderInto(body); bindActions(overlay, body);
      }
      else if (action === 'edit') {
        state.mode = 'edit'; overlay.setAttribute('data-mode', 'edit');
      }
      else if (action === 'save') saveHandler(overlay, body);
      else if (action === 'toggle-shift') cycleShift(overlay, body);
      else if (action === 'decommission') handleDecommissionClick(state.agentId, overlay, body, t);
    };
  }

  function collectDirty(body) {
    const dirty = {};
    const agent = state.snapshot.agent;
    body.querySelectorAll('[data-edit]').forEach(function (ee) {
      const name = ee.getAttribute('data-edit');
      if (!EDITABLE_FIELDS.includes(name)) return;
      let val;
      const type = ee.getAttribute('data-type');
      if (ee.type === 'checkbox') val = ee.checked;
      else if (type === 'int') val = ee.value === '' ? null : parseInt(ee.value, 10);
      else if (type === 'float') val = ee.value === '' ? null : parseFloat(ee.value);
      else if (type === 'csvlist') {
        val = ee.value.split(',').map(function (s) { return s.trim(); })
          .filter(function (s) { return s.length; });
      } else val = ee.value;

      const orig = agent[name];
      const origCmp = Array.isArray(orig) ? orig.join('|') :
                      (orig === null || orig === undefined ? '' : String(orig));
      const newCmp = Array.isArray(val) ? val.join('|') :
                     (val === null || val === undefined ? '' : String(val));
      if (origCmp !== newCmp) dirty[name] = val;
    });
    return dirty;
  }

  async function saveHandler(overlay, body) {
    const dirty = collectDirty(body);
    if (Object.keys(dirty).length === 0) {
      toast(overlay, 'No changes', 'ok');
      state.mode = 'view';
      overlay.setAttribute('data-mode', 'view');
      return;
    }
    const hasSensitive = Object.keys(dirty).some(function (k) {
      return SENSITIVE_FIELDS.has(k);
    });
    const go = hasSensitive ? await confirmOverlay(dirty) : true;
    if (!go) return;

    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + state.agentId,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(dirty),
        }
      );
      const js = await r.json();
      if (!r.ok) {
        toast(overlay,
          'Save failed: ' + (js.error || r.status) +
          (js.field ? ' (' + js.field + ')' : ''), 'err');
        if (js.field) {
          const ee = body.querySelector('[data-edit="' + js.field + '"]');
          if (ee) ee.classList.add('apm-error');
        }
        return;
      }
      toast(overlay, 'Saved', 'ok');
      state.snapshot = await fetchProfile(state.agentId);
      state.mode = 'view';
      overlay.setAttribute('data-mode', 'view');
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      toast(overlay, 'Network error', 'err');
    }
  }

  async function cycleShift(overlay, body) {
    const order = ['active', 'barracked', 'off_duty'];
    const cur = state.snapshot.agent.shift_state;
    const next = order[(order.indexOf(cur) + 1) % order.length];
    try {
      const r = await fetch(
        '/tools/department-hq/api/agent/' + state.agentId + '/shift',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ shift_state: next }),
        }
      );
      if (!r.ok) throw new Error('shift POST ' + r.status);
      toast(overlay, 'Shift → ' + next, 'ok');
      state.snapshot = await fetchProfile(state.agentId);
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      toast(overlay, 'Shift change failed', 'err');
    }
  }

  function confirmOverlay(dirty) {
    return new Promise(function (resolve) {
      let cov = document.getElementById('apmConfirmOverlay');
      if (!cov) {
        cov = el('div');
        cov.id = 'apmConfirmOverlay';
        const shell = el('div', 'apm-confirm-shell');
        shell.appendChild(el('div', 'apm-confirm-title',
          'Confirm sensitive change'));
        const bodyDiv = el('div', 'apm-confirm-body');
        bodyDiv.id = 'apmConfirmBody';
        shell.appendChild(bodyDiv);
        const actions = el('div', 'apm-confirm-actions');
        const cancel = el('button', null, 'CANCEL');
        cancel.dataset.cx = 'cancel';
        const ok = el('button', null, 'CONFIRM');
        ok.dataset.cx = 'ok';
        actions.appendChild(cancel);
        actions.appendChild(ok);
        shell.appendChild(actions);
        cov.appendChild(shell);
        document.body.appendChild(cov);
      }
      const bodyDiv = cov.querySelector('#apmConfirmBody');
      bodyDiv.textContent = 'You are changing: ' + Object.keys(dirty)
        .filter(function (k) { return SENSITIVE_FIELDS.has(k); }).join(', ') +
        '. These affect dispatch/routing.';
      cov.classList.add('active');
      cov.onclick = function (e) {
        const b = e.target.closest('[data-cx]');
        if (!b) return;
        cov.classList.remove('active');
        resolve(b.getAttribute('data-cx') === 'ok');
      };
    });
  }

  async function open(agentId) {
    state.agentId = agentId;
    state.mode = 'view';
    const overlay = document.getElementById(OVERLAY_ID);
    if (!overlay) { console.warn('agentProfileModal: no overlay'); return; }
    overlay.setAttribute('data-mode', 'view');
    overlay.setAttribute('data-agent-id', String(agentId));
    overlay.style.display = 'flex';
    overlay.classList.add('active');

    const body = overlay.querySelector('#agentDetailBody') ||
                 overlay.querySelector('.bm-body');
    clear(body);
    body.appendChild(el('div', 'dhq-loading', 'Loading agent profile...'));

    try {
      const [profile, portrait] = await Promise.all([
        fetchProfile(agentId),
        fetchPortrait(agentId),
      ]);
      profile.portrait = portrait;
      state.snapshot = profile;
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      clear(body);
      body.appendChild(el('div', 'apm-error', 'Error: ' + err.message));
    }
  }

  function close() {
    const overlay = document.getElementById(OVERLAY_ID);
    if (!overlay) return;
    overlay.classList.remove('active');
    overlay.style.display = 'none';
    state.agentId = null;
    state.snapshot = null;
    state.mode = 'view';
    state.uploadFile = null;
  }

  window.agentProfileModal = { open: open, close: close };
  window.openAgentDetail = function (agentId) { open(agentId); };
  window.closeAgentDetail = function () { close(); };
})();
