/* Cockpit (#6653 Phase 4): Crew + Code Builder + Approvals. Vanilla JS. Every piece of
   server text is rendered with textContent — never innerHTML. All calls go to comms'
   /api/cockpit/* (session) and /api/approvals/* (existing); comms proxies to the hub. */
(function () {
  'use strict';
  const POLL_MS = 5000;
  const ROSTER_PAGE = 50;
  const $ = (id) => document.getElementById(id);
  const mk = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = String(text); return el; };

  // Genuinely on screen, asked of the LAYOUT — the same reasoning as workVisible() below.
  // `hidden` alone is not it: showPane() sets hidden=true on the entry forms without removing
  // .ck-show, and .ck-sheet.ck-show { display: flex } (0,0,2,0) beats the UA [hidden] rule, so
  // a form can be hidden-by-attribute and painted at the same time.
  function formOnScreen(id) { const el = $(id); return !!el && el.getClientRects().length > 0; }

  // #6679 L2 — a <select> the owner is mid-way through choosing must never be rebuilt under
  // their hands. Both entry-form dropdowns are refilled from a poll (projects every 30 s in
  // loadWork, departments on every roster load) and a refill is textContent='' + re-append,
  // which DISCARDS the selection while leaving every typed field intact — so the form still
  // looks complete and submits under the FIRST option. Measured: choose project 343, wait 35 s,
  // the select reads 270 and "Task #N created" reports success for a project the owner never
  // picked (that is how task #6682 landed in 270).
  // Chosen fix: skip the refill entirely while the form is on screen — the same call
  // taskSheetBusy() already makes for the task sheet, and the honest one. Restoring the saved
  // value instead would still have to invent a policy for "that project is gone now", and
  // silently landing on a different option is the defect, not the cure. Stated cost: a project
  // or department created while the form is open does not join the list until it is reopened.
  // The || options.length escape hatch keeps a never-populated select from staying empty.
  function keepChoice(id, sel) { return formOnScreen(id) && sel.options.length > 0; }

  // From 1024px up the forms are an in-flow panel at the BOTTOM of their pane column (they sit
  // after the list in the DOM, and an order:-1 to hoist them would divorce tab order from what
  // is on screen), so opening one can land it below the fold and read as "the button did
  // nothing". No-op for the phone's fixed inset:0 sheet, which already fills the viewport.
  function revealForm(el) { if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest' }); }

  // ---- transport -------------------------------------------------------------------
  async function api(path, opts) {
    const o = Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {});
    if (o.body && typeof o.body !== 'string') o.body = JSON.stringify(o.body);
    let r;
    try { r = await fetch(path, o); } catch (_) { return { ok: false, status: 0, data: { error: 'hub unreachable — retry' } }; }
    let data = {};
    try { data = await r.json(); } catch (_) { data = { error: 'HTTP ' + r.status }; }
    return { ok: r.ok, status: r.status, data };
  }
  let toastTimer = null;
  function toast(msg, isErr) {
    const t = $('ck-toast'); t.textContent = msg; t.classList.toggle('ck-err', !!isErr); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, isErr ? 6000 : 3000);
  }
  const errText = (res) => (res.data && (res.data.error || res.data.status)) || ('HTTP ' + res.status);

  // ---- panes / tabs ----------------------------------------------------------------
  const PANES = { crew: 'pane-crew', work: 'pane-work', builder: 'pane-builder', approvals: 'pane-approvals', terminal: 'pane-terminal' };
  let leftChoice = 'crew';
  try { leftChoice = localStorage.getItem('ck-left') === 'work' ? 'work' : 'crew'; } catch (e) { /* private mode */ }
  // Nothing may fetch before the boot block runs: `work` and `workLoaded` are declared further
  // down, so a loadWork() from this first setLeft() would hit their temporal dead zone. The
  // `booted` guard short-circuits before either name is evaluated.
  let booted = false;
  function setLeft(name, persist) {
    leftChoice = name === 'work' ? 'work' : 'crew';
    // Persist ONLY on a deliberate switch click. showPane('crew') also runs when the owner
    // merely arrives from Chat at /cockpit#crew, and writing there silently reset a saved
    // Work preference.
    if (persist) { try { localStorage.setItem('ck-left', leftChoice); } catch (e) { /* ignore */ } }
    document.body.classList.toggle('ck-left-work', leftChoice === 'work');
    document.querySelectorAll('#ck-switch button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.left === leftChoice)));
    // From tablet up the Work column is shown by body.ck-left-work, NOT by a pane tab, so
    // showPane('work') cannot be the only loader — with a saved 'work' preference and the hash
    // on #builder or #approvals the column rendered blank, with no data, no error and no poll.
    if (booted && leftChoice === 'work' && !workLoaded) loadWork(true);
  }
  setLeft(leftChoice, false);

  // ---- right column: Builder <-> Terminal (Phase 5) ---------------------------------
  // At >=768 .ck-tabs is display:none, so the tab bar cannot reach the Terminal on desktop
  // — this switcher is the only affordance there, exactly as #ck-switch is for the left
  // column. Below 768 it is hidden and the 5th tab does the job instead.
  let rightChoice = 'builder';
  try { rightChoice = localStorage.getItem('ck-right') === 'terminal' ? 'terminal' : 'builder'; } catch (e) { /* private mode */ }
  // Declared ABOVE setRight on purpose: setRight runs immediately below, and a `let` it
  // referenced from further down would be in its temporal dead zone — the same trap the
  // `booted` guard exists for in setLeft.
  let lanesLoaded = false;
  function setRight(name, persist) {
    rightChoice = name === 'terminal' ? 'terminal' : 'builder';
    // Persist ONLY on a deliberate click — same reason as setLeft: arriving at /cockpit#…
    // also runs the show path, and writing there silently reset a saved preference.
    if (persist) { try { localStorage.setItem('ck-right', rightChoice); } catch (e) { /* ignore */ } }
    document.body.classList.toggle('ck-right-terminal', rightChoice === 'terminal');
    document.querySelectorAll('.ck-switch-right button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.right === rightChoice)));
    // From tablet up the Terminal is shown by body.ck-right-terminal, NOT by a pane tab, so
    // showPane('terminal') cannot be the only loader — with a saved 'terminal' preference the
    // column would render with no lane status and no error. Same shape as setLeft/loadWork.
    if (rightChoice === 'terminal' && !lanesLoaded) { lanesLoaded = true; loadLanes(); }
  }
  setRight(rightChoice, false);
  document.querySelectorAll('.ck-switch-right button').forEach((b) => b.addEventListener('click', () => setRight(b.dataset.right, true)));

  // ---- terminal lanes ---------------------------------------------------------------
  // The cockpit mints a one-time, LANE-BOUND token; the iframe then talks to the ttyd proxy
  // directly. No terminal byte passes through comms — pointing at the existing proxy is what
  // keeps this from becoming a second gate for shell access.
  let laneChoice = 'claude';
  let laneStatus = {};

  function renderLaneNote() {
    const cfg = laneStatus[laneChoice] || {};
    const bits = [];
    if (cfg.sandboxed === false) bits.push('This is the HOST shell — no container boundary.');
    else if (cfg.sandboxed === true) bits.push('Sandboxed container.');
    // busy is null = UNKNOWN. The seat is not observable from outside without opening a
    // websocket, which would CONSUME it when free, so never render this as availability.
    if (cfg.single_seat) bits.push('Seat state unknown — one viewer at a time.');
    if (cfg.reachable === false) bits.push('This lane is not responding.');
    $('ck-lane-note').textContent = bits.join(' ');
  }

  function setLane(lane) {
    laneChoice = lane === 'codex' ? 'codex' : 'claude';
    document.querySelectorAll('#ck-lanes button').forEach((b) => b.classList.toggle('ck-lane-on', b.dataset.lane === laneChoice));
    // Switching lanes tears the old terminal down: one slot, never two live shells.
    const frame = $('ck-term');
    frame.removeAttribute('src'); frame.hidden = true;
    $('ck-lane-state').hidden = false;
    $('ck-lane-open').textContent = 'Open the ' + laneChoice + ' lane';
    renderLaneNote();
  }

  async function loadLanes() {
    const res = await api('/api/cockpit/terminal/lanes');
    if (!res.ok) { $('ck-lane-note').textContent = res.status === 403 ? 'A terminal needs an admin account.' : 'Lane status unavailable.'; return; }
    (res.data.lanes || []).forEach((l) => { laneStatus[l.lane] = l; });
    renderLaneNote();
  }

  async function mountLane(lane) {
    const state = $('ck-lane-state');
    state.textContent = 'Opening the ' + lane + ' lane…';
    const res = await api('/api/cockpit/terminal/' + encodeURIComponent(lane) + '/token', { method: 'POST' });
    if (!res.ok) {
      // Honest reason, never a blank frame (spec section 6).
      const why = res.status === 403 ? 'A terminal needs an admin account.'
        : res.status === 404 ? 'That lane does not exist.'
        : (res.data && res.data.error) || 'Could not open the lane.';
      state.textContent = '';
      const msg = mk('p', 'ck-muted', why);
      const retry = mk('button', 'ck-btn', 'Reconnect');
      retry.type = 'button';
      retry.addEventListener('click', () => mountLane(lane));
      state.appendChild(msg); state.appendChild(retry);
      return;
    }
    const frame = $('ck-term');
    frame.src = res.data.url;
    frame.hidden = false;
    state.hidden = true;
  }

  document.querySelectorAll('#ck-lanes button').forEach((b) => b.addEventListener('click', () => setLane(b.dataset.lane)));
  $('ck-lane-open').addEventListener('click', () => mountLane(laneChoice));
  function showPane(name) {
    Object.keys(PANES).forEach((k) => { $(PANES[k]).classList.toggle('ck-show', k === name); });
    document.querySelectorAll('#ck-tabs button').forEach((b) => b.classList.toggle('ck-tab-on', b.dataset.pane === name));
    if (name === 'crew' || name === 'work') setLeft(name, false);
    if (name !== 'crew') { $('ck-agent').classList.remove('ck-show'); $('ck-hire').hidden = true; }
    if (name !== 'work') { $('ck-task').classList.remove('ck-show'); $('ck-task-new').hidden = true; clearInterval(taskWatch); }
    if (name === 'work' && !workLoaded) loadWork(true);
    // Leaving the pane tears the shell down. A live terminal left running inside a hidden
    // pane is a websocket nobody can see and a session nobody knows is open.
    if (name !== 'terminal') { const f = $('ck-term'); if (f && !f.hidden) { f.removeAttribute('src'); f.hidden = true; $('ck-lane-state').hidden = false; } }
    if (name === 'terminal' && !lanesLoaded) { lanesLoaded = true; loadLanes(); }
  }
  document.querySelectorAll('#ck-switch button').forEach((b) => b.addEventListener('click', () => { setLeft(b.dataset.left, true); location.hash = b.dataset.left; showPane(b.dataset.left); }));
  document.querySelectorAll('#ck-tabs button').forEach((b) => b.addEventListener('click', () => { location.hash = b.dataset.pane; showPane(b.dataset.pane); }));
  function paneFromHash() { const h = (location.hash || ('#' + leftChoice)).slice(1); return PANES[h] ? h : 'crew'; }
  window.addEventListener('hashchange', () => showPane(paneFromHash()));

  // ---- Crew: roster ----------------------------------------------------------------
  const roster = { q: '', department: '', state: '', worker_type: '', offset: 0, total: 0, facets: { departments: {}, states: {} } };
  let searchTimer = null;
  $('ck-search').addEventListener('input', (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { roster.q = e.target.value.trim(); roster.offset = 0; loadRoster(true); }, 300); });
  $('ck-more').addEventListener('click', () => { roster.offset += ROSTER_PAGE; loadRoster(false); });

  function pill(state) { const p = mk('span', 'ck-pill ck-state-' + String(state || 'unknown').replace(/[^a-z_]/gi, ''), state || '—'); return p; }

  function renderChips() {
    const box = $('ck-chips'); box.textContent = '';
    const chip = (label, key, val) => {
      const b = mk('button', 'ck-chip', label); b.type = 'button';
      b.setAttribute('aria-pressed', String(roster[key] === val));
      b.addEventListener('click', () => { roster[key] = roster[key] === val ? '' : val; roster.offset = 0; loadRoster(true); });
      return b;
    };
    Object.keys(roster.facets.states).sort().forEach((s) => box.appendChild(chip(s + ' · ' + roster.facets.states[s], 'state', s)));
    Object.keys(roster.facets.departments).sort().forEach((d) => box.appendChild(chip(d, 'department', d)));
    ['ai', 'internal', 'contract'].forEach((w) => box.appendChild(chip(w, 'worker_type', w)));
  }

  async function loadRoster(reset) {
    if (reset) roster.offset = 0;
    const qs = new URLSearchParams({ q: roster.q, department: roster.department, state: roster.state, worker_type: roster.worker_type, limit: String(ROSTER_PAGE), offset: String(roster.offset) });
    const res = await api('/api/cockpit/agents?' + qs.toString());
    const list = $('ck-roster');
    if (!res.ok) { toast('Crew: ' + errText(res), true); return; }
    if (reset) list.textContent = '';
    roster.total = res.data.total || 0; roster.facets = res.data.facets || roster.facets;
    $('ck-total').textContent = '· ' + roster.total;
    renderChips();
    (res.data.agents || []).forEach((a) => {
      const card = mk('button', 'ck-card'); card.type = 'button';
      const row = mk('div', 'ck-row'); row.appendChild(mk('span', 'ck-name', a.display_name || a.name)); row.appendChild(pill(a.shift_state));
      card.appendChild(row);
      card.appendChild(mk('div', 'ck-sub', [a.department || '—', a.model || '—', a.success_rate != null ? Math.round(a.success_rate) + '%' : ''].filter(Boolean).join(' · ')));
      card.addEventListener('click', () => openAgent(a.id));
      list.appendChild(card);
    });
    if (!list.childElementCount) list.appendChild(mk('div', 'ck-empty', 'No agents match.'));
    $('ck-more').hidden = roster.offset + ROSTER_PAGE >= roster.total;
    // #6679 L2 — see keepChoice(). The roster polls while a hire is pending, so this refill
    // reset the department the owner had chosen; #ck-hire shipped in 4a with the same defect.
    const dept = $('ck-hire-dept');
    if (!keepChoice('ck-hire', dept)) { dept.textContent = ''; Object.keys(roster.facets.departments).sort().forEach((d) => { const o = mk('option', null, d); o.value = d; dept.appendChild(o); }); }
  }

  // ---- Crew: agent card ------------------------------------------------------------
  let currentAgent = null;
  async function openAgent(id) {
    const res = await api('/api/cockpit/agents/' + id);
    if (!res.ok) { toast('Agent: ' + errText(res), true); return; }
    currentAgent = res.data; renderAgent(res.data); $('ck-agent').hidden = false; $('ck-agent').classList.add('ck-show');
  }
  $('ck-agent-close').addEventListener('click', () => { $('ck-agent').classList.remove('ck-show'); });

  function kv(dl, k, v) { dl.appendChild(mk('dt', null, k)); dl.appendChild(mk('dd', 'ck-num', v == null || v === '' ? '—' : v)); }

  function renderAgent(d) {
    const a = d.agent || {}; const body = $('ck-agent-body'); body.textContent = '';
    $('ck-agent-name').textContent = a.display_name || a.name || ('#' + a.id);
    const st = $('ck-agent-state'); st.className = 'ck-pill ck-state-' + String(a.shift_state || '').replace(/[^a-z_]/gi, ''); st.textContent = a.shift_state || '—';
    body.appendChild(mk('div', 'ck-sub', [a.title, a.department, a.model].filter(Boolean).join(' · ')));
    const perf = mk('dl', 'ck-kv'); kv(perf, 'success', a.success_rate != null ? Math.round(a.success_rate) + '%' : null); kv(perf, 'score', a.performance_score); kv(perf, 'tasks', a.total_tasks_completed); kv(perf, 'last used', a.last_used ? new Date(a.last_used).toLocaleString() : null); body.appendChild(perf);

    // Skills
    body.appendChild(mk('div', 'ck-sect', 'Skills'));
    const skills = mk('div', 'ck-skills');
    (d.skills || []).forEach((s) => {
      const chip = mk('span', 'ck-skill'); chip.appendChild(mk('span', null, s.skill_name)); chip.appendChild(mk('em', null, 'Lv' + s.proficiency_level));
      const x = mk('button', null, '×'); x.type = 'button'; x.title = 'Remove ' + s.skill_name;
      x.addEventListener('click', () => act(a.id, 'skills/remove', { skill_name: s.skill_name }, 'Removed ' + s.skill_name));
      chip.appendChild(x); skills.appendChild(chip);
    });
    const add = mk('button', 'ck-skill', '+ add'); add.type = 'button'; add.style.color = '#00d4ff';
    add.addEventListener('click', () => {
      const name = window.prompt('Skill name (e.g. code_review)'); if (!name) return;
      const level = parseInt(window.prompt('Level 1–5', '3') || '3', 10); const category = window.prompt('Category', 'general') || 'general';
      act(a.id, 'skills/add', { skill_name: name.trim(), level, category }, 'Added ' + name.trim());
    });
    skills.appendChild(add); body.appendChild(skills);

    // Budget
    body.appendChild(mk('div', 'ck-sect', 'Budget'));
    const b = d.budget; const brow = mk('div', 'ck-row');
    brow.appendChild(mk('span', 'ck-num', b ? (fmtK(b.tokens_used_today) + ' / ' + fmtK(b.token_limit_per_day) + ' tokens today') : 'no budget row yet'));
    const setBtn = mk('button', 'ck-btn ck-small', 'Set limit'); setBtn.type = 'button';
    setBtn.addEventListener('click', () => { const v = window.prompt('Daily token limit (floor 50,000)', b ? String(b.token_limit_per_day) : '250000'); if (!v) return; act(a.id, 'budget', { token_limit_per_day: parseInt(v, 10) }, 'Budget set'); });
    brow.appendChild(setBtn); body.appendChild(brow);
    if (b) { const m = mk('div', 'ck-meter'); const i = mk('i'); i.style.width = Math.min(100, Math.round(100 * (b.tokens_used_today || 0) / Math.max(1, b.token_limit_per_day || 1))) + '%'; m.appendChild(i); body.appendChild(m); body.appendChild(mk('div', 'ck-sub ck-num', 'queue ' + (b.current_task_count ?? '—') + ' / ' + (b.task_queue_limit ?? '—'))); }

    // Actions
    body.appendChild(mk('div', 'ck-sect', 'Actions'));
    const dept = mk('select', 'ck-select'); Object.keys(roster.facets.departments).sort().forEach((dn) => { const o = mk('option', null, dn); o.value = dn; if (dn === a.department) o.selected = true; dept.appendChild(o); });
    const deptBtn = mk('button', 'ck-btn ck-small', 'Assign'); deptBtn.type = 'button'; deptBtn.addEventListener('click', () => act(a.id, 'assign', { department: dept.value }, 'Assigned to ' + dept.value));
    const drow = mk('div', 'ck-row'); drow.appendChild(dept); drow.appendChild(deptBtn); body.appendChild(drow);
    const states = ['active', 'deployed', 'barracked', 'off_duty', 'winding_down', 'cooldown'];
    const stSel = mk('select', 'ck-select'); states.forEach((s) => { const o = mk('option', null, s); o.value = s; if (s === a.shift_state) o.selected = true; stSel.appendChild(o); });
    const stBtn = mk('button', 'ck-btn ck-small', 'Set state'); stBtn.type = 'button';
    stBtn.addEventListener('click', () => { const reason = window.prompt('Reason', 'cockpit') || 'cockpit'; act(a.id, 'shift-state', { state: stSel.value, reason }, 'State → ' + stSel.value); });
    const srow = mk('div', 'ck-row'); srow.appendChild(stSel); srow.appendChild(stBtn); body.appendChild(srow);
    const dec = mk('button', 'ck-btn ck-danger ck-block', "Decommission — type the agent's name to confirm"); dec.type = 'button';
    dec.addEventListener('click', () => {
      const typed = window.prompt("This is terminal. Type the agent's name exactly to confirm:");
      if (typed == null) return;
      if (typed !== (a.display_name || a.name)) { toast('Name did not match — nothing changed', true); return; }
      act(a.id, 'shift-state', { state: 'decommissioned', reason: 'cockpit decommission' }, 'Decommissioned');
    });
    body.appendChild(dec);

    // Recent work
    body.appendChild(mk('div', 'ck-sect', 'Recent work'));
    const tbl = mk('table', 'ck-work');
    (d.recent_work || []).forEach((w) => { const tr = mk('tr'); tr.appendChild(mk('td', null, [w.capability, w.model_used, w.provider].filter(Boolean).join(' · '))); const td = mk('td'); td.appendChild(mk('span', w.success ? 'ck-ok' : 'ck-bad', w.success ? '✓' : '✗')); td.appendChild(document.createTextNode(' ' + (w.created_at ? new Date(w.created_at).toLocaleTimeString() : ''))); tr.appendChild(td); tbl.appendChild(tr); });
    if (!tbl.childElementCount) tbl.appendChild(mk('tr')).appendChild(mk('td', 'ck-empty', 'No dispatches yet'));
    body.appendChild(tbl);
  }
  const fmtK = (n) => n == null ? '—' : (n >= 1000 ? Math.round(n / 1000) + 'k' : String(n));

  async function act(id, action, body, okMsg) {
    const res = await api('/api/cockpit/agents/' + id + '/' + action, { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast(okMsg); openAgent(id); loadRoster(true);
  }

  // ---- Crew: hire ------------------------------------------------------------------
  $('ck-hire-open').addEventListener('click', () => { $('ck-hire').hidden = false; $('ck-hire').classList.add('ck-show'); revealForm($('ck-hire')); });
  document.querySelectorAll('[data-close="ck-hire"]').forEach((b) => b.addEventListener('click', () => { $('ck-hire').classList.remove('ck-show'); $('ck-hire').hidden = true; }));
  $('ck-hire').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target); const body = {};
    ['name', 'display_name', 'department', 'model', 'capability', 'reason'].forEach((k) => { body[k] = String(f.get(k) || '').trim(); });
    const sk = String(f.get('suggested_skills') || '').split(',').map((s) => s.trim()).filter(Boolean); if (sk.length) body.suggested_skills = sk;
    const res = await api('/api/cockpit/agents/create', { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast('Hire proposed — approval #' + (res.data.approval_id || '?') + ' is waiting in Approvals and Telegram');
    $('ck-hire').classList.remove('ck-show'); $('ck-hire').hidden = true; e.target.reset(); loadApprovals();
  });

  // ---- Builder ---------------------------------------------------------------------
  let providers = [];
  async function loadProviders() {
    const res = await api('/api/cockpit/build/providers');
    if (!res.ok) { toast('Providers: ' + errText(res), true); return; }
    providers = res.data.providers || [];
    const p = $('ck-provider'); p.textContent = '';
    providers.forEach((pr) => { const o = mk('option', null, pr.display_name || pr.provider_key); o.value = pr.provider_key; p.appendChild(o); });
    fillModels();
  }
  function fillModels() {
    const pr = providers.find((x) => x.provider_key === $('ck-provider').value) || providers[0]; const m = $('ck-model'); m.textContent = '';
    if (!pr) return;
    (pr.models || []).forEach((name) => { const o = mk('option', null, name); o.value = name; if (name === pr.default_model) o.selected = true; m.appendChild(o); });
  }
  $('ck-provider').addEventListener('change', fillModels);
  $('ck-compose').addEventListener('submit', async (e) => {
    e.preventDefault(); const btn = $('ck-run'); btn.disabled = true;
    const body = { prompt: $('ck-prompt').value.trim(), provider: $('ck-provider').value, model: $('ck-model').value };
    const target = $('ck-target').value.trim(); if (target) body.target_path = target;
    const sys = $('ck-system').value.trim(); if (sys) body.system_prompt = sys;
    const res = await api('/api/cockpit/build/run', { method: 'POST', body }); btn.disabled = false;
    if (res.status === 409 && res.data.status === 'approval_unavailable') { toast('Approve or deny the pending coding job first', true); return; }
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast('Job #' + res.data.job_id + ' waits for your approval — Approvals tab or Telegram');
    loadJobs(); loadApprovals();
  });
  $('ck-jobs-refresh').addEventListener('click', loadJobs);

  const ACTIVE = new Set(['pending', 'pending_approval', 'running', 'queued']);
  let jobs = []; let pollTimer = null; let expanded = null; let jobsErrToasted = false;
  async function loadJobs() {
    const res = await api('/api/cockpit/build/runs?limit=20');
    if (!res.ok) { if (!jobsErrToasted) { toast('Jobs: ' + errText(res), true); jobsErrToasted = true; } schedulePoll(); return; }
    jobsErrToasted = false;
    jobs = res.data.runs || []; renderJobs(); schedulePoll();
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    if (jobs.some((j) => ACTIVE.has(j.status))) pollTimer = setTimeout(loadJobs, POLL_MS);
  }
  // An apply approval that is DECIDED is not a live one. The hub's own dedup only refuses a
  // *pending* apply, so once a denial/expiry/failure lands a retry is accepted — but until the
  // list carried a status the cockpit only saw `apply_approval_id`, which is set in every one
  // of those cases, so a denied apply read "apply waits for approval #N" forever with the Apply
  // button suppressed and no way back.
  // 'approved' and 'executed' are deliberately NOT here: the executor is about to run, or has
  // run, and re-offering Apply there risks a second branch and a duplicate PR.
  //
  // 🔴 'rejected' IS THE ONE THAT MATTERS, and it was missing from the first cut of this fix.
  // EVERY deny path writes 'rejected' to autonomy_approval_queue — approvals_routes.py:254 (the
  // DHQ Approvals tab) and telegram_gateway.py 1034/1149/1232/2127. Nothing writes 'denied'
  // there; that is contractor_approval_requests' vocabulary (approvals_routes.py:307), and
  // telegram_gateway.py:1150 even sets rejected_reason='Denied via Telegram' so the WORD is in
  // the row while the STATUS is 'rejected'. Omitting it meant every Deny — the common settle
  // path — still read "apply waits for approval #N" forever with Apply suppressed, i.e. this
  // fix defeated its own purpose. 'denied' is kept because the contractor table does use it.
  const APPLY_SETTLED = ['rejected', 'denied', 'expired', 'failed', 'cancelled'];
  // 'pr' | 'none' | 'pending' | 'settled'. An absent or null status stays 'pending': absent
  // means an older hub that does not send the key, null means the queue row was purged or the
  // lookup failed — neither is evidence the apply is over.
  function applyPhase(j) {
    if (j.pr_number) return 'pr';
    if (!j.apply_approval_id) return 'none';
    return APPLY_SETTLED.indexOf(String(j.apply_approval_status || '')) >= 0 ? 'settled' : 'pending';
  }
  function renderJobs() {
    const list = $('ck-jobs'); list.textContent = '';
    if (!jobs.length) { list.appendChild(mk('div', 'ck-empty', 'No coding jobs yet.')); return; }
    jobs.forEach((j) => {
      const card = mk('div', 'ck-card'); card.setAttribute('role', 'listitem');
      const row = mk('div', 'ck-row'); row.appendChild(mk('span', 'ck-name ck-num', '#' + j.job_id));
      const label = j.status === 'pending' ? 'pending approval' : j.status; row.appendChild(mk('span', 'ck-pill ck-job-' + String(j.status).replace(/[^a-z_]/gi, ''), label));
      card.appendChild(row);
      const r = j.result || {};
      card.appendChild(mk('div', 'ck-sub ck-num', [j.model ? 'requested ' + j.model : '', r.model_used ? 'served ' + r.model_used + (r.served_model_resolved ? ' ✓' : ' (unresolved)') : '', r.prompt_tokens != null ? r.prompt_tokens + ' → ' + (r.completion_tokens ?? '?') + ' tok' : ''].filter(Boolean).join(' · ')));
      if (j.error || r.error) card.appendChild(mk('div', 'ck-sub ck-bad', j.error || r.error));
      if (j.status === 'pending') card.appendChild(mk('div', 'ck-sub', 'approve it in Approvals or Telegram'));
      if (j.target_path) card.appendChild(mk('div', 'ck-sub ck-num', 'target ' + j.target_path));
      const phase = applyPhase(j);
      if (phase === 'pr') { const a = mk('a', 'ck-sub', 'PR #' + j.pr_number); a.href = (typeof j.pr_url === 'string' && j.pr_url.startsWith('https://')) ? j.pr_url : '#'; a.target = '_blank'; a.rel = 'noopener'; card.appendChild(a); }
      else if (phase === 'settled') card.appendChild(mk('div', 'ck-sub ck-bad', 'apply ' + j.apply_approval_status + ' — try again' + (j.apply_error ? ': ' + j.apply_error : '')));
      else if (j.apply_error) card.appendChild(mk('div', 'ck-sub ck-bad', 'apply: ' + j.apply_error));
      else if (phase === 'pending') card.appendChild(mk('div', 'ck-sub', 'apply waits for approval #' + j.apply_approval_id));
      const open = mk('button', 'ck-btn ck-small', expanded === j.job_id ? 'Hide' : 'Open'); open.type = 'button';
      open.addEventListener('click', () => { expanded = expanded === j.job_id ? null : j.job_id; renderJobs(); });
      card.appendChild(open);
      if (j.status === 'completed' && j.target_path && (phase === 'none' || phase === 'settled')) {
        const ap = mk('button', 'ck-btn ck-primary ck-small', 'Apply — needs your approval'); ap.type = 'button';
        ap.addEventListener('click', () => applyJob(j.job_id)); card.appendChild(ap);
      }
      list.appendChild(card);
      if (expanded === j.job_id) showJobDetail(j.job_id, card);
    });
  }
  async function showJobDetail(id, card) {
    const res = await api('/api/cockpit/build/' + id);
    if (!res.ok) { toast('Job: ' + errText(res), true); return; }
    const r = res.data.result || {}; let pre = card.querySelector('pre');
    if (!pre) { pre = mk('pre', 'ck-code'); card.appendChild(pre); const cp = mk('button', 'ck-btn ck-small', 'Copy'); cp.type = 'button'; cp.addEventListener('click', () => { navigator.clipboard && navigator.clipboard.writeText(pre.textContent).then(() => toast('Copied')); }); card.appendChild(cp); }
    pre.textContent = r.response || (res.data.status === 'pending' ? 'Waiting for approval…' : (res.data.status === 'running' ? 'Running…' : (res.data.error || 'No output')));
    if (r.routing_decision) card.appendChild(mk('div', 'ck-sub', r.routing_decision));
  }
  async function applyJob(id) {
    const res = await api('/api/cockpit/build/' + id + '/apply', { method: 'POST', body: {} });
    if (!res.ok || res.data.success === false) { toast('Apply: ' + errText(res), true); return; }
    toast('Apply waits for your approval — #' + res.data.approval_id + ' in Approvals or Telegram');
    loadJobs(); loadApprovals();
  }

  // ---- Work: projects + tasks (#6679 Phase 4b) --------------------------------------
  const WORK_POLL_MS = 30000; const TASK_PAGE = 50;
  let workLoaded = false;
  const work = { q: '', project_id: '', status: 'pending,in_progress,blocked', min_priority: '', offset: 0, total: 0, projects: [], facets: { status: {}, projects: {}, capabilities: [] }, collapsed: new Set() };
  let workSearchTimer = null;
  $('ck-work-search').addEventListener('input', (e) => { clearTimeout(workSearchTimer); workSearchTimer = setTimeout(() => { work.q = e.target.value.trim(); loadWork(true); }, 250); });
  $('ck-work-more').addEventListener('click', () => { work.offset += TASK_PAGE; loadWork(false); });

  function workChip(label, on, onClick) { const b = mk('button', 'ck-chip', label); b.type = 'button'; b.setAttribute('aria-pressed', String(!!on)); b.addEventListener('click', onClick); return b; }
  function renderWorkChips() {
    const box = $('ck-work-chips'); box.textContent = '';
    const current = new Set(work.status.split(',').filter(Boolean));
    ['pending', 'in_progress', 'blocked', 'completed', 'cancelled'].forEach((s) => {
      const n = work.facets.status[s]; if (n == null && !current.has(s)) return;
      box.appendChild(workChip(s + (n != null ? ' · ' + n : ''), current.has(s), () => { if (current.has(s)) current.delete(s); else current.add(s); work.status = Array.from(current).join(',') || 'pending'; loadWork(true); }));
    });
    box.appendChild(workChip('priority ≥ 8', work.min_priority === '8', () => { work.min_priority = work.min_priority === '8' ? '' : '8'; loadWork(true); }));
    Object.keys(work.facets.projects).sort((a, b) => work.facets.projects[a].localeCompare(work.facets.projects[b])).forEach((pid) => {
      box.appendChild(workChip(work.facets.projects[pid], work.project_id === pid, () => { work.project_id = work.project_id === pid ? '' : pid; loadWork(true); }));
    });
  }
  function prioPill(p) { const el = mk('span', 'ck-pill ck-num', 'P' + (p == null ? '?' : p)); if (p >= 8) el.classList.add('ck-state-active'); return el; }
  // Re-fetch everything already on screen as ONE page, so the 30 s poll cannot silently throw
  // away pages the owner loaded with "Load more". task_service.MAX_LIMIT clamps at 200, so past
  // four pages we skip the auto-refresh rather than truncate the list behind the owner's back;
  // any filter change or a manual action still does a full reload.
  const WORK_MAX_REFRESH = 200;
  function refreshWork() {
    const loaded = work.offset + TASK_PAGE;
    if (loaded > WORK_MAX_REFRESH) return;
    loadWork(false, loaded);
  }
  // The signature of the request currently in flight, or null. `workLoaded` cannot do this job:
  // it is only set AFTER the awaits below, so one Work-switch click (setLeft -> showPane's
  // setLeft -> showPane's own -> the hashchange repeating all three) fired up to five
  // overlapping loads, and boot with #work fired two. Same final DOM, ~10 redundant requests
  // and visible flicker.
  //
  // Keyed on the QUERY, not on a bare boolean, deliberately: a bare flag would also refuse the
  // debounced search box and the filter chips, which call loadWork(true) with CHANGED filters
  // while a load is in flight — silently dropping what the owner just typed. Only a byte-identical
  // request is refused, and refusing that costs nothing since the one in flight is already
  // fetching exactly it.
  let workLoading = null;
  async function loadWork(reset, spanLimit) {
    if (reset) work.offset = 0;
    const from = spanLimit ? 0 : work.offset;
    const size = spanLimit || TASK_PAGE;
    const qs = new URLSearchParams({ q: work.q, project_id: work.project_id, status: work.status, min_priority: work.min_priority, limit: String(size), offset: String(from) });
    const sig = qs.toString() + (spanLimit ? '|span' : '');
    if (workLoading === sig) return;
    workLoading = sig;
    try { await _loadWork(qs, reset, spanLimit); } finally { if (workLoading === sig) workLoading = null; }
  }
  // Cleared in a `finally` above, so the early returns on a failed fetch below cannot strand the
  // flag and wedge Work loading forever.
  async function _loadWork(qs, reset, spanLimit) {
    const [pr, tr] = await Promise.all([api('/api/cockpit/projects?limit=200'), api('/api/cockpit/tasks?' + qs.toString())]);
    const list = $('ck-work-list');
    if (!pr.ok) { toast('Projects: ' + errText(pr), true); return; }
    if (!tr.ok) { toast('Tasks: ' + errText(tr), true); return; }
    workLoaded = true;
    work.projects = pr.data.projects || []; work.total = tr.data.total || 0; work.facets = tr.data.facets || work.facets;
    $('ck-work-total').textContent = '· ' + work.total;
    renderWorkChips();
    if (reset || spanLimit) list.textContent = '';
    const byProject = new Map();
    (tr.data.tasks || []).forEach((t) => { const k = String(t.project_id); if (!byProject.has(k)) byProject.set(k, []); byProject.get(k).push(t); });
    byProject.forEach((tasks, pid) => {
      let group = list.querySelector('[data-project="' + pid + '"]');
      if (!group) {
        group = mk('div', 'ck-group'); group.dataset.project = pid;
        const p = work.projects.find((x) => String(x.id) === pid) || {};
        const head = mk('div', 'ck-group-head');
        head.appendChild(mk('span', null, (tasks[0].project_name || p.name || 'project ' + pid) + (p.status ? ' · ' + p.status : '')));
        head.appendChild(mk('span', 'ck-num', (p.open_tasks != null ? p.open_tasks + ' open / ' + p.total_tasks : String(tasks.length))));
        head.addEventListener('click', () => { if (work.collapsed.has(pid)) work.collapsed.delete(pid); else work.collapsed.add(pid); group.classList.toggle('ck-collapsed', work.collapsed.has(pid)); });
        group.appendChild(head); group.appendChild(mk('div', 'ck-group-body'));
        group.classList.toggle('ck-collapsed', work.collapsed.has(pid));
        list.appendChild(group);
      }
      const body = group.querySelector('.ck-group-body');
      tasks.forEach((t) => {
        const card = mk('button', 'ck-card'); card.type = 'button';
        const row = mk('div', 'ck-row'); row.appendChild(mk('span', 'ck-name', t.title)); row.appendChild(prioPill(t.priority)); row.appendChild(pill(t.status));
        card.appendChild(row);
        card.appendChild(mk('div', 'ck-sub', [t.task_type || '—', t.agent_name || (t.delegation_source ? 'fleet · ' + t.delegation_source : '')].filter(Boolean).join(' · ')));
        card.addEventListener('click', () => openTask(t.id));
        body.appendChild(card);
      });
    });
    if (!list.childElementCount) list.appendChild(mk('div', 'ck-empty', 'No tasks match.'));
    $('ck-work-more').hidden = work.offset + TASK_PAGE >= work.total;
    // #6679 L2 — see keepChoice(). This refill is what filed task #6682 under project 270.
    const sel = $('ck-task-new-project');
    if (!keepChoice('ck-task-new', sel)) { sel.textContent = ''; work.projects.forEach((p) => { const o = mk('option', null, p.name); o.value = String(p.id); sel.appendChild(o); }); }
  }

  let currentTask = null; let taskWatch = null;
  // Live references to the sheet's inputs, so the poll can tell whether the owner has work in
  // progress in there. renderTask() rebuilds the whole body, so these are re-set on every render.
  const taskEls = { note: null, status: null, prio: null, statusAtRender: null, prioAtRender: null };
  // renderTask() does `body.textContent = ''` — a 10 s poll running that under the owner's hands
  // destroyed a half-typed note and any status/priority they had chosen but not yet applied.
  // Chosen fix: SKIP the refresh entirely while the sheet holds work, rather than patching
  // individual nodes. It is the honest option — a partial patch would still have to decide which
  // half of a rebuilt sheet is safe to touch. Cost, stated plainly: while the owner is focused in
  // the sheet or holds an unsent note/selection, the delegated-task status shown is the one from
  // the last clean refresh; it updates on their next action, or as soon as the sheet is idle.
  function taskSheetBusy() {
    const sheet = $('ck-task');
    if (sheet && sheet.contains(document.activeElement)) return true;
    if (taskEls.note && taskEls.note.value.trim()) return true;
    // Compare against the value AT RENDER, never against the task's own field. A <select> with
    // no matching option is not empty — the browser auto-selects the first one — so a task whose
    // priority is NULL or outside 1-10 makes prio.value read '1', which never equals
    // String(null), and the sheet would be "busy" forever with the 10 s poll dead for that task.
    // Measured 0 of 5,917 rows in that state today, but renderTask and prioPill both already
    // guard `priority == null`, so this codebase treats it as reachable. Same trap applies to
    // status if it ever holds a value outside the option list, and one mechanism covers both.
    if (taskEls.status && taskEls.status.value !== taskEls.statusAtRender) return true;
    if (taskEls.prio && taskEls.prio.value !== taskEls.prioAtRender) return true;
    return false;
  }
  async function openTask(id) {
    const res = await api('/api/cockpit/tasks/' + id);
    if (!res.ok) { toast('Task: ' + errText(res), true); return; }
    currentTask = res.data.task; renderTask(currentTask);
    $('ck-task').hidden = false; $('ck-task').classList.add('ck-show');
    clearInterval(taskWatch);
    if (currentTask.delegation_source && (currentTask.status === 'pending' || currentTask.status === 'in_progress')) taskWatch = setInterval(() => { if (!taskSheetBusy()) openTask(id); }, 10000);
  }
  $('ck-task-close').addEventListener('click', () => { $('ck-task').classList.remove('ck-show'); $('ck-task').hidden = true; clearInterval(taskWatch); });
  function renderTask(t) {
    $('ck-task-title').textContent = t.title || ('#' + t.id);
    const body = $('ck-task-body'); body.textContent = '';
    body.appendChild(mk('div', 'ck-sub', [t.project_name || '—', t.task_type || '—', 'priority ' + (t.priority == null ? '—' : t.priority), t.agent_name || ''].filter(Boolean).join(' · ')));
    const row0 = mk('div', 'ck-row'); row0.appendChild(pill(t.status)); if (t.delegation_source) row0.appendChild(mk('span', 'ck-sub', 'delegated · ' + ((t.delegation_args || {}).capability || '?') + ' · ' + t.status)); body.appendChild(row0);
    if (t.description) { const d = mk('div', 'ck-sub'); d.textContent = t.description; body.appendChild(d); }
    body.appendChild(mk('div', 'ck-sect', 'Actions'));
    const stSel = mk('select', 'ck-select'); ['pending', 'in_progress', 'blocked', 'completed', 'cancelled'].forEach((s) => { const o = mk('option', null, s); o.value = s; if (s === t.status) o.selected = true; stSel.appendChild(o); });
    taskEls.status = stSel; taskEls.statusAtRender = stSel.value;
    const stBtn = mk('button', 'ck-btn ck-small', 'Set'); stBtn.type = 'button'; stBtn.addEventListener('click', () => taskAct(t.id, 'status', { status: stSel.value }, 'Status → ' + stSel.value));
    const r1 = mk('div', 'ck-row'); r1.appendChild(stSel); r1.appendChild(stBtn); body.appendChild(r1);
    const prSel = mk('select', 'ck-select'); for (let i = 1; i <= 10; i++) { const o = mk('option', null, String(i)); o.value = String(i); if (i === t.priority) o.selected = true; prSel.appendChild(o); }
    taskEls.prio = prSel; taskEls.prioAtRender = prSel.value;
    const prBtn = mk('button', 'ck-btn ck-small', 'Set'); prBtn.type = 'button'; prBtn.addEventListener('click', () => taskAct(t.id, 'priority', { priority: parseInt(prSel.value, 10) }, 'Priority → ' + prSel.value));
    const r2 = mk('div', 'ck-row'); r2.appendChild(mk('span', 'ck-sub', 'priority')); r2.appendChild(prSel); r2.appendChild(prBtn); body.appendChild(r2);
    const noteBox = mk('textarea', 'ck-select'); noteBox.rows = 2; noteBox.placeholder = 'Add a note…'; noteBox.maxLength = 2000;
    taskEls.note = noteBox;
    const noteBtn = mk('button', 'ck-btn ck-small', 'Add note'); noteBtn.type = 'button';
    // Clear ONLY on success. This used to clear on both paths: on success the sheet had already
    // been rebuilt so it was a no-op, which meant the only text it ever actually destroyed was
    // the owner's unsaved note after a FAILED save.
    noteBtn.addEventListener('click', () => { const text = noteBox.value.trim(); if (!text) return; taskAct(t.id, 'note', { text }, 'Note added').then((ok) => { if (ok) noteBox.value = ''; }); });
    const r3 = mk('div', 'ck-row'); r3.appendChild(noteBox); r3.appendChild(noteBtn); body.appendChild(r3);
    const capSel = mk('select', 'ck-select'); (work.facets.capabilities || []).forEach((c) => { const o = mk('option', null, c); o.value = c; capSel.appendChild(o); });
    const dlBtn = mk('button', 'ck-btn ck-primary ck-small', 'Delegate to fleet'); dlBtn.type = 'button';
    dlBtn.disabled = !(t.status === 'pending' || t.status === 'blocked') || !!(t.delegation_source && t.status === 'pending');
    dlBtn.addEventListener('click', () => taskAct(t.id, 'delegate', { capability: capSel.value }, 'Delegated — the fleet claims it within 30 s'));
    const r4 = mk('div', 'ck-row'); r4.appendChild(capSel); r4.appendChild(dlBtn); body.appendChild(r4);
    body.appendChild(mk('div', 'ck-sect', 'Notes'));
    const notes = mk('div', 'ck-task-notes');
    (t.notes || []).forEach((n) => { const el = mk('div', 'ck-note', n.text); const ts = mk('span', 'ck-note-ts', (n.author || '') + ' · ' + (n.ts || '')); el.appendChild(ts); notes.appendChild(el); });
    if (!(t.notes || []).length) notes.appendChild(mk('div', 'ck-empty', 'No notes yet.'));
    body.appendChild(notes);
  }
  // Resolves TRUE only when the write landed, so callers can tell success from failure.
  async function taskAct(id, action, body, okMsg) {
    const res = await api('/api/cockpit/tasks/' + id + '/' + action, { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return false; }
    toast(okMsg);
    await openTask(id); loadWork(true);
    return true;
  }

  $('ck-task-open').addEventListener('click', () => { $('ck-task-new').hidden = false; $('ck-task-new').classList.add('ck-show'); revealForm($('ck-task-new')); });
  document.querySelectorAll('[data-close="ck-task-new"]').forEach((b) => b.addEventListener('click', () => { $('ck-task-new').classList.remove('ck-show'); $('ck-task-new').hidden = true; }));
  $('ck-task-new').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { project_id: parseInt(f.get('project_id'), 10), title: String(f.get('title') || '').trim(), description: String(f.get('description') || '').trim(), priority: parseInt(f.get('priority'), 10), task_type: String(f.get('task_type') || 'implementation') };
    const res = await api('/api/cockpit/tasks', { method: 'POST', body });
    if (!res.ok || res.data.success === false) { toast(errText(res), true); return; }
    toast('Task #' + res.data.task.id + ' created');
    $('ck-task-new').classList.remove('ck-show'); $('ck-task-new').hidden = true; e.target.reset(); loadWork(true);
  });
  // Genuinely visible by EITHER mechanism: the phone tab sets .ck-show, the tablet-and-up
  // layout shows the column from body.ck-left-work with no .ck-show at all. getClientRects()
  // asks the layout rather than re-encoding the 768px breakpoint here.
  function workVisible() { const el = $('pane-work'); return !!el && el.getClientRects().length > 0; }
  setInterval(() => { if (workLoaded && workVisible()) refreshWork(); }, WORK_POLL_MS);

  // ---- Approvals (tab on phone, strip on desktop) -----------------------------------
  let hirePending = false;
  async function loadApprovals() {
    const res = await api('/api/approvals/pending');
    const list = $('ck-approvals'); const strip = $('ck-strip'); list.textContent = ''; strip.textContent = '';
    if (!res.ok) { list.appendChild(mk('div', 'ck-empty', 'Approvals: ' + errText(res))); return; }
    const items = res.data.approvals || [];
    hirePending = items.some((a) => /create_agent|propose_hire/i.test(String(a.action_type || '')));
    $('ck-approvals-count').textContent = '· ' + items.length; const badge = $('ck-tab-badge'); badge.textContent = String(items.length); badge.hidden = !items.length;
    if (!items.length) list.appendChild(mk('div', 'ck-empty', 'No pending approvals'));
    items.forEach((a) => { list.appendChild(approvalCard(a, false)); strip.appendChild(approvalCard(a, true)); });
  }
  function approvalCard(a, compact) {
    const card = mk('div', 'ck-card'); card.setAttribute('role', 'listitem');
    const title = a.display_name || a.action_type || a.id;
    card.appendChild(mk(compact ? 'span' : 'div', compact ? 'ck-sub' : 'ck-name', title));
    if (!compact && a.reason) card.appendChild(mk('div', 'ck-sub', a.reason));
    const row = mk('div', 'ck-row');
    const ok = mk('button', 'ck-btn ck-primary ck-small', 'Approve'); ok.type = 'button'; ok.addEventListener('click', () => decide(a.id, 'approve', card));
    const no = mk('button', 'ck-btn ck-small', 'Deny'); no.type = 'button'; no.addEventListener('click', () => decide(a.id, 'deny', card));
    row.appendChild(ok); row.appendChild(no); card.appendChild(row);
    return card;
  }
  async function decide(id, verb, card) {
    card.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    const res = await api('/api/approvals/' + encodeURIComponent(id) + '/' + verb, { method: 'POST', body: {} });
    if (!res.ok || !res.data.ok) { card.querySelectorAll('button').forEach((b) => { b.disabled = false; }); toast('Approval: ' + errText(res), true); return; }
    toast(verb === 'approve' ? 'Approved' : 'Denied'); loadApprovals(); loadJobs(); loadRoster(true);
  }

  // ---- boot ------------------------------------------------------------------------
  booted = true;
  showPane(paneFromHash());
  // A saved 'work' preference with the hash on #builder/#approvals shows the Work column on
  // desktop without ever routing through showPane('work') — load it here too.
  if (leftChoice === 'work' && !workLoaded) loadWork(true);
  $('ck-agent-body').appendChild(mk('div', 'ck-empty', 'Pick an agent from the crew list.'));
  loadRoster(true); loadProviders(); loadJobs(); loadApprovals();
  setInterval(async () => { await loadApprovals(); if (hirePending) loadRoster(true); }, 30000);
})();
