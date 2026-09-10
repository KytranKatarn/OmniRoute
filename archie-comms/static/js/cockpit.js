/* Cockpit (#6653 Phase 4): Crew + Code Builder + Approvals. Vanilla JS. Every piece of
   server text is rendered with textContent — never innerHTML. All calls go to comms'
   /api/cockpit/* (session) and /api/approvals/* (existing); comms proxies to the hub. */
(function () {
  'use strict';
  const POLL_MS = 5000;
  const ROSTER_PAGE = 50;
  const $ = (id) => document.getElementById(id);
  const mk = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text != null) el.textContent = String(text); return el; };

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
  const PANES = { crew: 'pane-crew', builder: 'pane-builder', approvals: 'pane-approvals' };
  function showPane(name) {
    Object.keys(PANES).forEach((k) => { $(PANES[k]).classList.toggle('ck-show', k === name); });
    document.querySelectorAll('#ck-tabs button').forEach((b) => b.classList.toggle('ck-tab-on', b.dataset.pane === name));
    if (name !== 'crew') { $('ck-agent').classList.remove('ck-show'); $('ck-hire').hidden = true; }
  }
  document.querySelectorAll('#ck-tabs button').forEach((b) => b.addEventListener('click', () => { location.hash = b.dataset.pane; showPane(b.dataset.pane); }));
  function paneFromHash() { const h = (location.hash || '#crew').slice(1); return PANES[h] ? h : 'crew'; }
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
    const dept = $('ck-hire-dept'); dept.textContent = '';
    Object.keys(roster.facets.departments).sort().forEach((d) => { const o = mk('option', null, d); o.value = d; dept.appendChild(o); });
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
  $('ck-hire-open').addEventListener('click', () => { $('ck-hire').hidden = false; $('ck-hire').classList.add('ck-show'); });
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
      const open = mk('button', 'ck-btn ck-small', expanded === j.job_id ? 'Hide' : 'Open'); open.type = 'button';
      open.addEventListener('click', () => { expanded = expanded === j.job_id ? null : j.job_id; renderJobs(); });
      card.appendChild(open);
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
  showPane(paneFromHash());
  $('ck-agent-body').appendChild(mk('div', 'ck-empty', 'Pick an agent from the crew list.'));
  loadRoster(true); loadProviders(); loadJobs(); loadApprovals();
  setInterval(async () => { await loadApprovals(); if (hirePending) loadRoster(true); }, 30000);
})();
