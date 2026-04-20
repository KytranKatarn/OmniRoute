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

  function buildReadOnlySections(skills, welfare, perf) {
    const frag = document.createDocumentFragment();

    const sk = el('div', 'apm-section');
    const skTitle = el('div', 'apm-section-title');
    skTitle.appendChild(document.createTextNode('Skills '));
    const skLink = el('a', 'apm-deeplink', '→ Academy');
    skLink.href = '/tools/agent-academy#skills';
    skTitle.appendChild(skLink);
    sk.appendChild(skTitle);
    if (skills && skills.length) {
      skills.slice(0, 30).forEach(function (s) {
        const label = (s.skill_name || s.name || s) +
          (s.proficiency_level ? ' · Lv' + s.proficiency_level : '');
        sk.appendChild(el('span', 'apm-chip', label));
      });
    } else {
      const em = el('em'); em.style.opacity = '0.6';
      em.textContent = 'No skills recorded';
      sk.appendChild(em);
    }
    frag.appendChild(sk);

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

    return frag;
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

  function buildPortraitSection(agent, portrait) {
    const section = el('div', 'apm-section apm-portrait-section');
    const titleRow = el('div', 'apm-section-title');
    titleRow.appendChild(document.createTextNode('Portrait '));
    const link = el('a', 'apm-deeplink', '→ Media Studio');
    link.href = '/tools/media-studio#portraits';
    titleRow.appendChild(link);
    section.appendChild(titleRow);

    const row = el('div', 'apm-portrait-row');

    const canonical = el('div', 'apm-portrait-canonical-wrap');
    const hasCanonical = !!(agent.avatar_url);
    if (hasCanonical) {
      const img = document.createElement('img');
      img.className = 'apm-portrait-canonical';
      img.src = agent.avatar_url;
      img.alt = '';
      canonical.appendChild(img);
    } else {
      const ph = el('div', 'apm-portrait-placeholder');
      ph.appendChild(el('div', 'apm-portrait-placeholder-icon', '◉'));
      ph.appendChild(el('div', 'apm-portrait-placeholder-label', 'NO CANONICAL'));
      canonical.appendChild(ph);
    }
    row.appendChild(canonical);

    const meta = el('div', 'apm-portrait-meta');

    const variantCount = (portrait && Array.isArray(portrait.variants)) ?
      portrait.variants.length : 0;
    const trackedCanonical = !!(portrait && portrait.canonical_image_path);
    const statusRow = el('div', 'apm-portrait-status');
    if (trackedCanonical && portrait.approved) {
      statusRow.appendChild(el('span', 'apm-portrait-badge apm-badge-ok',
        'CANONICAL ✓'));
    } else if (trackedCanonical) {
      statusRow.appendChild(el('span', 'apm-portrait-badge apm-badge-warn',
        'PENDING APPROVAL'));
    } else if (hasCanonical) {
      statusRow.appendChild(el('span', 'apm-portrait-badge apm-badge-muted',
        'LEGACY'));
    } else {
      statusRow.appendChild(el('span', 'apm-portrait-badge apm-badge-muted',
        'NOT GENERATED'));
    }
    statusRow.appendChild(el('span', 'apm-portrait-badge apm-badge-muted',
      variantCount + (variantCount === 1 ? ' variant' : ' variants')));
    meta.appendChild(statusRow);

    const promptWrap = el('div', 'apm-portrait-prompt-wrap');
    promptWrap.appendChild(el('div', 'apm-field-label', 'Identity prompt'));
    const promptTA = document.createElement('textarea');
    promptTA.className = 'apm-input apm-portrait-prompt';
    promptTA.dataset.portraitPrompt = '1';
    promptTA.rows = 3;
    promptTA.placeholder =
      'Describe this agent\'s face, uniform, and style. Used by ComfyUI + IP-Adapter.';
    promptTA.value =
      (portrait && (portrait.identity_prompt || portrait.default_identity_prompt)) || '';
    promptWrap.appendChild(promptTA);
    meta.appendChild(promptWrap);

    const actions = el('div', 'apm-portrait-actions');

    // Hidden file input + "UPLOAD IMAGE" button pair. The button just
    // triggers a click on the input; the actual work happens in the
    // 'portrait-file-picked' change handler wired in bindActions().
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = 'image/jpeg,image/png,image/webp';
    fileInput.dataset.portraitFile = '1';
    fileInput.style.display = 'none';
    actions.appendChild(fileInput);

    const uploadBtn = el('button', 'apm-btn', 'UPLOAD IMAGE');
    uploadBtn.dataset.action = 'upload-pick';
    actions.appendChild(uploadBtn);

    if (!hasCanonical) {
      const gen = el('button', 'apm-btn apm-btn-primary', 'GENERATE CANONICAL');
      gen.dataset.action = 'generate-canonical';
      actions.appendChild(gen);
    }
    const savePrompt = el('button', 'apm-btn', 'SAVE PROMPT');
    savePrompt.dataset.action = 'save-identity-prompt';
    actions.appendChild(savePrompt);
    meta.appendChild(actions);

    // Upload-mode area (hidden by default). Revealed once a file is picked
    // and the vision-describe call starts. Holds preview + auto-filled
    // prompt + CONFIRM / CANCEL buttons.
    const uploadZone = el('div', 'apm-upload-zone');
    uploadZone.style.display = 'none';
    uploadZone.dataset.portraitUploadZone = '1';
    meta.appendChild(uploadZone);

    row.appendChild(meta);
    section.appendChild(row);
    return section;
  }

  function renderInto(body) {
    clear(body);
    const agent = state.snapshot.agent;
    const root = el('div', 'apm-root');
    root.appendChild(buildHeaderBand(agent));
    root.appendChild(buildPortraitSection(agent, state.snapshot.portrait));
    SECTIONS.forEach(function (sec) { root.appendChild(buildSection(sec, agent)); });
    root.appendChild(buildReadOnlySections(
      state.snapshot.skills, state.snapshot.welfare, state.snapshot.performance
    ));
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
      else if (action === 'generate-canonical') generateCanonical(overlay, body);
      else if (action === 'save-identity-prompt') saveIdentityPrompt(overlay, body);
      else if (action === 'upload-pick') {
        const fi = body.querySelector('[data-portrait-file="1"]');
        if (fi) fi.click();
      }
      else if (action === 'confirm-upload') confirmUpload(overlay, body);
      else if (action === 'cancel-upload') cancelUpload(overlay, body);
    };

    // File-input change handler (not a data-action — triggered by the
    // hidden <input type=file> when user picks a file).
    body.onchange = function (e) {
      const t = e.target;
      if (t && t.dataset && t.dataset.portraitFile === '1') {
        onUploadFileSelected(overlay, body, t.files && t.files[0]);
      }
    };
  }

  function resetUploadZone(body) {
    const zone = body.querySelector('[data-portrait-upload-zone="1"]');
    if (zone) { clear(zone); zone.style.display = 'none'; }
    const fi = body.querySelector('[data-portrait-file="1"]');
    if (fi) fi.value = '';
    state.uploadFile = null;
  }

  async function onUploadFileSelected(overlay, body, file) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      toast(overlay, 'File too large (max 10 MB)', 'err');
      resetUploadZone(body);
      return;
    }
    state.uploadFile = file;

    const zone = body.querySelector('[data-portrait-upload-zone="1"]');
    if (!zone) return;
    clear(zone);
    zone.style.display = 'block';

    // Preview (object URL)
    const previewWrap = el('div', 'apm-upload-preview-wrap');
    const preview = document.createElement('img');
    preview.className = 'apm-upload-preview';
    preview.src = URL.createObjectURL(file);
    preview.alt = '';
    previewWrap.appendChild(preview);
    zone.appendChild(previewWrap);

    // Status + prompt
    const status = el('div', 'apm-upload-status',
      '✨ Analyzing image with vision model — this takes 5–15 seconds…');
    zone.appendChild(status);

    const promptWrap = el('div', 'apm-portrait-prompt-wrap');
    promptWrap.appendChild(el('div', 'apm-field-label', 'Identity prompt (edit before confirming)'));
    const ta = document.createElement('textarea');
    ta.className = 'apm-input apm-portrait-prompt';
    ta.dataset.uploadPrompt = '1';
    ta.rows = 4;
    ta.disabled = true;
    ta.value = 'analyzing…';
    promptWrap.appendChild(ta);
    zone.appendChild(promptWrap);

    const actions = el('div', 'apm-portrait-actions');
    const confirmBtn = el('button', 'apm-btn apm-btn-primary', 'CONFIRM UPLOAD');
    confirmBtn.dataset.action = 'confirm-upload';
    confirmBtn.disabled = true;
    const cancelBtn = el('button', 'apm-btn', 'CANCEL');
    cancelBtn.dataset.action = 'cancel-upload';
    actions.appendChild(confirmBtn);
    actions.appendChild(cancelBtn);
    zone.appendChild(actions);

    // Kick off vision describe in parallel with preview render
    try {
      const b64 = await fileToBase64(file);
      const r = await fetch('/tools/media-studio/api/portraits/describe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ image: b64 }),
      });
      const js = await r.json();
      if (js.success && js.prompt) {
        ta.value = js.prompt;
        status.textContent = '✓ Review + edit the prompt, then confirm.';
      } else {
        ta.value = '';
        status.textContent =
          '⚠ Auto-describe failed — write the prompt manually, then confirm.';
      }
    } catch (err) {
      ta.value = '';
      status.textContent =
        '⚠ Auto-describe failed (' + err.message + '). Write prompt manually.';
    }
    ta.disabled = false;
    confirmBtn.disabled = false;
  }

  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      const r = new FileReader();
      r.onload = function () {
        const result = r.result || '';
        // result looks like "data:image/png;base64,....."
        const comma = result.indexOf(',');
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      r.onerror = function () { reject(new Error('FileReader failed')); };
      r.readAsDataURL(file);
    });
  }

  async function confirmUpload(overlay, body) {
    const file = state.uploadFile;
    if (!file) { toast(overlay, 'No file picked', 'err'); return; }
    const ta = body.querySelector('[data-upload-prompt="1"]');
    const prompt = ta ? ta.value.trim() : '';
    if (!prompt) { toast(overlay, 'Identity prompt is required', 'err'); return; }

    const confirmBtn = body.querySelector('[data-action="confirm-upload"]');
    if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = 'UPLOADING…'; }

    try {
      const fd = new FormData();
      fd.append('file', file, file.name);
      fd.append('identity_prompt', prompt);
      const r = await fetch(
        '/tools/media-studio/api/portraits/' + state.agentId + '/upload',
        { method: 'POST', credentials: 'same-origin', body: fd }
      );
      const js = await r.json().catch(function () { return {}; });
      if (!r.ok || !js.success) {
        toast(overlay, 'Upload failed: ' + (js.error || r.status), 'err');
        if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = 'CONFIRM UPLOAD'; }
        return;
      }
      toast(overlay, 'Portrait uploaded ✓', 'ok');
      resetUploadZone(body);
      // Refresh modal with new canonical
      const [profile, portrait] = await Promise.all([
        fetchProfile(state.agentId),
        fetchPortrait(state.agentId),
      ]);
      profile.portrait = portrait;
      state.snapshot = profile;
      renderInto(body);
      bindActions(overlay, body);
    } catch (err) {
      toast(overlay, 'Network error: ' + err.message, 'err');
      if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = 'CONFIRM UPLOAD'; }
    }
  }

  function cancelUpload(overlay, body) {
    resetUploadZone(body);
    toast(overlay, 'Upload cancelled', 'ok');
  }

  async function generateCanonical(overlay, body) {
    const btn = body.querySelector('[data-action="generate-canonical"]');
    if (btn) btn.disabled = true;
    try {
      const ta = body.querySelector('[data-portrait-prompt="1"]');
      const promptOverride = ta && ta.value.trim() ? ta.value.trim() : null;
      const r = await fetch(
        '/tools/media-studio/api/portraits/' + state.agentId + '/generate-canonical',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify(promptOverride ? { prompt: promptOverride } : {}),
        }
      );
      const js = await r.json();
      if (!r.ok) {
        toast(overlay, 'Generate failed: ' + (js.error || r.status), 'err');
        return;
      }
      const jobId = js.job_id || js.id || '';
      toast(overlay,
        'Canonical queued' + (jobId ? ' · job ' + jobId : '') +
        ' · watch Media Studio', 'ok');
    } catch (_) {
      toast(overlay, 'Network error', 'err');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveIdentityPrompt(overlay, body) {
    const ta = body.querySelector('[data-portrait-prompt="1"]');
    if (!ta) return;
    const prompt = ta.value.trim();
    if (!prompt) { toast(overlay, 'Prompt is empty', 'err'); return; }
    try {
      const r = await fetch(
        '/tools/media-studio/api/portraits/' + state.agentId + '/identity-prompt',
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ prompt: prompt }),
        }
      );
      if (!r.ok) {
        const js = await r.json().catch(function () { return {}; });
        toast(overlay, 'Save failed: ' + (js.error || r.status), 'err');
        return;
      }
      toast(overlay, 'Identity prompt saved', 'ok');
      state.snapshot.portrait = await fetchPortrait(state.agentId);
      renderInto(body);
      bindActions(overlay, body);
    } catch (_) {
      toast(overlay, 'Network error', 'err');
    }
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
