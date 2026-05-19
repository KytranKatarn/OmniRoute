/* department-hq-orchestration.js — Cluster Orchestration Fleet Panel (Project #352) */

/* Safe string escape for any API string used in attribute context */
function _coEsc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

let _coGlobalPaused = false;
let _coDrawerScope = null;

async function coRefresh() {
  try {
    const r = await fetch('/tools/department-hq/api/orchestration/status');
    if (!r.ok) return;
    const d = await r.json();
    _coGlobalPaused = d.global_paused;
    _coRenderStatus(d);
  } catch (_) { /* silent — fleet tab may not be visible */ }
}

function _coRenderStatus(d) {
  const agents = d.agents || [];
  const queues = d.queues || [];
  const active = agents.filter(a => a.is_active).length;

  /* Status badge */
  const badge = document.getElementById('co-status-badge');
  if (badge) {
    badge.className  = active > 0 ? 'sc-live' : 'sc-static';
    badge.textContent = active > 0 ? ('● ACTIVE (' + active + ')') : '● STANDBY';
  }

  /* Pause button label */
  const pb = document.getElementById('co-pause-btn');
  if (pb) pb.textContent = _coGlobalPaused ? '▶ RESUME' : '⏸ PAUSE';

  /* Queue pressure grid */
  const qg = document.getElementById('co-queue-grid');
  if (qg) {
    qg.textContent = '';
    if (!queues.length) {
      const msg = document.createElement('div');
      msg.style.cssText = 'color:#555;font-size:10px;';
      msg.textContent = 'no pending work';
      qg.appendChild(msg);
    } else {
      queues.forEach(function(q) {
        const pct   = Math.min(100, Math.round((q.depth / 10) * 100));
        const color = pct >= 80 ? '#ef4444' : pct >= 50 ? '#f59e0b' : '#00ffff';

        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:10px;margin-bottom:4px;';

        const lbl = document.createElement('span');
        lbl.style.cssText = 'width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aaa;';
        lbl.textContent = q.capability;

        const bw = document.createElement('div');
        bw.style.cssText = 'flex:1;height:6px;background:#1a1a2e;border-radius:3px;overflow:hidden;';
        const bf = document.createElement('div');
        bf.style.cssText = 'height:100%;border-radius:3px;background:' + color + ';width:' + pct + '%;transition:width 0.3s;';
        bw.appendChild(bf);

        const cnt = document.createElement('span');
        cnt.style.cssText = 'width:35px;text-align:right;color:' + color + ';';
        cnt.textContent = String(q.depth);

        const btn = document.createElement('button');
        btn.textContent = '⚙';
        btn.style.cssText = 'font-size:9px;padding:1px 4px;background:#1a1a2e;border:1px solid #333;color:#aaa;cursor:pointer;border-radius:2px;';
        const cap = q.capability;
        btn.addEventListener('click', function() { coOpenCapabilityConfig(cap); });

        row.append(lbl, bw, cnt, btn);
        qg.appendChild(row);
      });
    }
  }

  /* Agent overflow grid */
  const ag = document.getElementById('co-agent-grid');
  if (ag) {
    ag.textContent = '';
    if (!agents.length) {
      const msg = document.createElement('div');
      msg.style.cssText = 'color:#555;font-size:10px;';
      msg.textContent = 'no agents scored yet — waiting for next cycle';
      ag.appendChild(msg);
    } else {
      agents.forEach(function(a) {
        const scoreColor  = a.score >= 0.5 ? '#00ffff' : '#555';
        const borderColor = a.is_active ? '#00ffff44' : '#1a1a2e';

        const card = document.createElement('div');
        card.style.cssText = 'background:#0a0a1a;border:1px solid ' + borderColor + ';border-radius:4px;padding:8px;font-size:10px;';

        const head = document.createElement('div');
        head.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';

        const nameEl = document.createElement('span');
        nameEl.style.color = a.is_active ? '#00ffff' : '#888';
        nameEl.textContent = a.agent_name;

        const modeEl = document.createElement('span');
        modeEl.style.cssText = 'font-size:9px;color:#00ffff;';
        modeEl.textContent = a.is_active ? '⟳ overflow' : '';

        head.append(nameEl, modeEl);

        const deptEl = document.createElement('div');
        deptEl.style.cssText = 'color:#555;font-size:9px;margin-top:2px;';
        deptEl.textContent = a.department;

        const capRow = document.createElement('div');
        capRow.style.cssText = 'color:#666;font-size:9px;margin-top:4px;';
        const capVal = document.createElement('span');
        capVal.style.color = '#aaa';
        capVal.textContent = a.capability;
        capRow.append(document.createTextNode('cap: '), capVal);

        const barRow = document.createElement('div');
        barRow.style.cssText = 'display:flex;align-items:center;gap:6px;margin-top:4px;';
        const scoreLbl = document.createElement('span');
        scoreLbl.style.cssText = 'font-size:9px;color:#555;';
        scoreLbl.textContent = 'score';
        const bw2 = document.createElement('div');
        bw2.style.cssText = 'flex:1;height:4px;background:#1a1a2e;border-radius:2px;';
        const bf2 = document.createElement('div');
        bf2.style.cssText = 'height:100%;border-radius:2px;background:' + scoreColor + ';width:' + Math.round(a.score * 100) + '%;';
        bw2.appendChild(bf2);
        const scoreNum = document.createElement('span');
        scoreNum.style.cssText = 'font-size:9px;color:' + scoreColor + ';';
        scoreNum.textContent = a.score.toFixed(2);
        barRow.append(scoreLbl, bw2, scoreNum);

        const pauseBtn = document.createElement('button');
        pauseBtn.textContent = '⏸ PAUSE';
        pauseBtn.style.cssText = 'margin-top:6px;width:100%;font-size:9px;padding:2px;background:#1a1a2e;border:1px solid #333;color:#aaa;cursor:pointer;border-radius:2px;';
        const aid = a.agent_id;
        const cap2 = a.capability;
        pauseBtn.addEventListener('click', function() { coPauseAgent(aid, cap2); });

        card.append(head, deptEl, capRow, barRow, pauseBtn);
        ag.appendChild(card);
      });
    }
  }
}

async function coTriggerScan() {
  const btn = document.getElementById('co-trigger-btn');
  const orig = btn ? btn.textContent : null;
  if (btn) { btn.textContent = '⟳ SCANNING…'; btn.disabled = true; }
  try {
    const r = await fetch('/tools/department-hq/api/orchestration/trigger', {method: 'POST'});
    const d = await r.json();
    if (btn) {
      btn.textContent = d.ok ? ('✓ ' + (d.scored || 0) + ' scored') : '✗ ERROR';
      btn.disabled = false;
      setTimeout(() => { if (btn) btn.textContent = orig || '▶ TRIGGER'; }, 3000);
    }
    if (d.ok) setTimeout(coRefresh, 500);
  } catch (e) {
    if (btn) { btn.textContent = '✗ FAILED'; btn.disabled = false;
      setTimeout(() => { if (btn) btn.textContent = orig || '▶ TRIGGER'; }, 3000); }
    console.warn('[orchestration] trigger failed:', e);
  }
}

async function coToggleGlobalPause() {
  const btn = document.getElementById('co-pause-btn');
  if (btn) { btn.disabled = true; }
  try {
    const r = await fetch('/tools/department-hq/api/orchestration/pause', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({scope: 'global', paused: !_coGlobalPaused}),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'pause failed');
    await coRefresh();
  } catch (e) {
    console.warn('[orchestration] global pause failed:', e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function coPauseAgent(agentId, capability) {
  try {
    await fetch('/tools/department-hq/api/orchestration/pause', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({scope: 'agent', agent_id: agentId, capability: capability, paused: true}),
    });
    await coRefresh();
  } catch (_) {}
}

function coOpenCapabilityConfig(capability) {
  _coDrawerScope = {scope: 'capability', capability: capability, agent_id: null, node_id: null};
  _coRenderDrawer('CAPABILITY: ' + _coEsc(capability));
}

async function _coRenderDrawer(title) {
  const drawer  = document.getElementById('co-config-drawer');
  const overlay = document.getElementById('co-drawer-overlay');
  const titleEl = document.getElementById('co-drawer-title');
  const content = document.getElementById('co-drawer-content');

  if (titleEl) titleEl.textContent = title;
  if (!drawer || !overlay || !content) return;

  let cfg = {};
  try {
    const r  = await fetch('/tools/department-hq/api/orchestration/config');
    const d  = await r.json();
    const s  = _coDrawerScope;
    cfg = (d.configs || []).find(function(c) {
      return c.scope === s.scope &&
             c.capability == s.capability &&
             c.agent_id   == s.agent_id;
    }) || {};
  } catch (_) {}

  const val = function(k, def) { return (cfg[k] !== undefined && cfg[k] !== null) ? cfg[k] : def; };

  content.textContent = '';

  function makeSlider(fieldName, labelText, min, max, defaultVal) {
    const wrap = document.createElement('label');
    wrap.style.cssText = 'display:block;margin-bottom:14px;font-size:10px;color:#666;cursor:pointer;';
    const lbl = document.createElement('span');
    lbl.textContent = labelText + ' ';
    const input = document.createElement('input');
    input.type  = 'range'; input.id = 'co-field-' + fieldName;
    input.min   = String(min); input.max = String(max);
    input.value = String(val(fieldName, defaultVal));
    input.style.cssText = 'width:100%;margin-top:4px;display:block;';
    const display = document.createElement('span');
    display.id    = 'co-disp-' + fieldName;
    display.style.color = '#00ffff';
    display.textContent = input.value;
    input.addEventListener('input', function() { display.textContent = this.value; });
    wrap.append(lbl, input, display);
    return wrap;
  }

  content.append(
    makeSlider('idle_threshold_minutes',    'IDLE THRESHOLD (min)',      1, 30,  5),
    makeSlider('utilization_threshold_pct', 'UTILIZATION THRESHOLD (%)', 10, 95, 60),
    makeSlider('queue_pressure_threshold',  'QUEUE PRESSURE THRESHOLD',  1, 100, 10),
  );

  const concWrap = document.createElement('label');
  concWrap.style.cssText = 'display:block;margin-bottom:14px;font-size:10px;color:#666;';
  concWrap.textContent = 'MAX OVERFLOW CONCURRENT ';
  const concInput = document.createElement('input');
  concInput.type = 'number'; concInput.id = 'co-field-max_overflow_concurrent';
  concInput.min = '1'; concInput.max = '20';
  concInput.value = String(val('max_overflow_concurrent', 3));
  concInput.style.cssText = 'width:60px;background:#0a0a1a;border:1px solid #333;color:#fff;padding:2px 4px;';
  concWrap.appendChild(concInput);
  content.appendChild(concWrap);

  const enabledWrap = document.createElement('label');
  enabledWrap.style.cssText = 'display:flex;align-items:center;gap:8px;font-size:10px;color:#666;margin-bottom:16px;cursor:pointer;';
  const enabledCb = document.createElement('input');
  enabledCb.type = 'checkbox'; enabledCb.id = 'co-field-overflow_enabled';
  enabledCb.checked = val('overflow_enabled', true);
  enabledWrap.append(enabledCb, document.createTextNode('OVERFLOW ENABLED'));
  content.appendChild(enabledWrap);

  const saveBtn = document.createElement('button');
  saveBtn.textContent = 'SAVE CONFIG';
  saveBtn.style.cssText = 'width:100%;padding:8px;background:#00ffff22;border:1px solid #00ffff44;color:#00ffff;cursor:pointer;font-size:10px;letter-spacing:1px;border-radius:2px;';
  saveBtn.addEventListener('click', coSaveConfig);
  content.appendChild(saveBtn);

  overlay.style.display = 'block';
  drawer.style.right = '0';
}

function coCloseDrawer() {
  const d = document.getElementById('co-config-drawer');
  const o = document.getElementById('co-drawer-overlay');
  if (d) d.style.right = '-360px';
  if (o) o.style.display = 'none';
}

async function coSaveConfig() {
  function getVal(id, def) {
    const el = document.getElementById(id);
    return el ? el.value : def;
  }
  const body = Object.assign({}, _coDrawerScope, {
    idle_threshold_minutes:    parseInt(getVal('co-field-idle_threshold_minutes', '5')),
    utilization_threshold_pct: parseInt(getVal('co-field-utilization_threshold_pct', '60')),
    queue_pressure_threshold:  parseInt(getVal('co-field-queue_pressure_threshold', '10')),
    max_overflow_concurrent:   parseInt(getVal('co-field-max_overflow_concurrent', '3')),
    overflow_enabled: document.getElementById('co-field-overflow_enabled') ?
                      document.getElementById('co-field-overflow_enabled').checked : true,
  });
  const saveBtn = document.querySelector('#co-drawer-content button');
  if (saveBtn) { saveBtn.textContent = 'SAVING…'; saveBtn.disabled = true; }
  try {
    const r = await fetch('/tools/department-hq/api/orchestration/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'save failed');
    coCloseDrawer();
    await coRefresh();
  } catch (e) {
    if (saveBtn) {
      saveBtn.textContent = 'SAVE FAILED';
      saveBtn.style.borderColor = '#ef4444';
      saveBtn.style.color = '#ef4444';
      saveBtn.disabled = false;
      setTimeout(() => {
        if (saveBtn) {
          saveBtn.textContent = 'SAVE CONFIG';
          saveBtn.style.borderColor = '';
          saveBtn.style.color = '';
        }
      }, 3000);
    }
    console.warn('[orchestration] save config failed:', e);
  }
}

/* Initial load after DOM ready */
document.addEventListener('DOMContentLoaded', function() {
  /* Attach button listeners (avoids inline onclick in HTML) */
  const pb = document.getElementById('co-pause-btn');
  if (pb) pb.addEventListener('click', coToggleGlobalPause);
  const tb = document.getElementById('co-trigger-btn');
  if (tb) tb.addEventListener('click', coTriggerScan);
  /* Auto-refresh every 30s */
  setInterval(coRefresh, 30000);
  setTimeout(coRefresh, 2000);
});
