// FLEET COMMAND render checks (task #5816).
//
// Run:  node platform_v2/tests/js/test_fleet_command_render.cjs
//
// ⚠️ CI does NOT run this — the suite is pytest. It exists because the
// Playwright backend was crashed when FLEET COMMAND was built, so the panel
// shipped WITHOUT a browser drive. It exercises the real render functions
// against the real payload shapes with a DOM stub; it proves the LOGIC
// (labels, colours, wording), never the pixels. A live visual check is owed.
//
// It has already earned its place twice:
//   1. caught the force-undock case reading "not armed — Starships take work
//      around the clock" while labelled FORCE-UNDOCK;
//   2. caught the ⚓ button rendering a confident "DOCKED" during a manual
//      force-undock, because the painter tested the SCHEDULE (enabled &&
//      active_now) instead of the combined is_starships_undocked() truth.
const fs = require('fs');
const SRC = 'platform_v2/tools/department_hq/static/js/department-hq.js';
const src = fs.readFileSync(SRC, 'utf8');

function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('missing ' + name);
  let d = 0, started = false;
  for (let k = i; k < src.length; k++) {
    if (src[k] === '{') { d++; started = true; }
    else if (src[k] === '}') { d--; if (started && d === 0) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced ' + name);
}

function mkEl(tag) {
  return {
    tagName: tag, textContent: '', title: '', htmlFor: '', id: '', value: '',
    type: '', checked: false, selected: false, disabled: false,
    dataset: {},
    style: new Proxy({ cssText: '' }, { set(t, p, v) { t[p] = v; return true; }, get(t, p) { return t[p] || ''; } }),
    children: [], appendChild(c) { this.children.push(c); return c; },
    addEventListener() {},
  };
}
const els = {};
['crBody', 'crSaveStatus', 'crSaveBtn', 'restModeBtn', 'restModeStatus'].forEach(id => {
  els[id] = mkEl('div'); els[id].id = id;
});
global.document = { createElement: mkEl, getElementById: id => els[id] || null };

function _crSave() {} function _crUndock() {}
eval(grab('_crMk')); eval(grab('_crHourSelect'));
eval(grab('updateRestModeUI'));   // the shared ⚓ button painter
eval(grab('_crRender'));

let failures = 0;
function check(cond, msg) { console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`); if (!cond) failures++; }
function flat(el, out = []) { out.push(el); (el.children || []).forEach(c => flat(c, out)); return out; }

const base = { start_hour: 20, end_hour: 6, window_label: '20:00–06:00 ET', now_et: '16:21 ET',
               next_transition: { kind: 'rest_start', at: '20:00 ET', in_minutes: 218 } };

// Mirror the REAL GET /api/fleet/rest-mode payload: the endpoint returns
// enabled/active_now/undocked/force_undock_until/rest_window at TOP level AND
// the nested `status` snapshot. Building only the nested half made every
// top-level read undefined — a fixture that cannot catch what it claims to.
function payload(status, { undocked = false, force = null } = {}) {
  return {
    success: true,
    enabled: status.enabled,
    start_hour: status.start_hour,
    end_hour: status.end_hour,
    active_now: status.active,
    undocked: undocked,
    force_undock_until: force,
    rest_window: status.window_label,
    status: status,
  };
}

function render(payload) {
  els.crBody.children = [];
  els.restModeBtn.textContent = ''; els.restModeBtn.style.color = '';
  _crRender(payload);
  return { btn: els.restModeBtn, text: flat(els.crBody).map(e => e.textContent).filter(Boolean).join(' ') };
}

// 1. live state: docked, schedule off — the healthy everyday case must be LIT
let r = render(payload({ ...base, enabled: false, in_window: false, active: false }));
check(r.btn.textContent === '⚓ DOCKED' && r.btn.style.color === '#00bcd4',
      `DOCKED (schedule off) is lit cyan — got "${r.btn.textContent}" ${r.btn.style.color}`);
check(r.btn.style.background === 'rgba(0,188,212,0.2)', '  …and filled like a selected PROFILE chip');

// 2. docked, schedule armed
r = render(payload({ ...base, enabled: true, in_window: false, active: false }));
check(r.btn.textContent === '⚓ DOCKED' && r.btn.style.color === '#00bcd4', 'DOCKED (armed, pre-window) is lit cyan');
check(r.text.includes('rest starts 20:00 ET'), '  …and says when rest starts');

// 3. resting inside the window
r = render(payload({ ...base, enabled: true, in_window: true, active: true,
                     next_transition: { kind: 'rest_end', at: '06:00 ET', in_minutes: 500 } },
                   { undocked: true }));
check(r.btn.textContent === '⚓ UNDOCKED' && r.btn.style.color === '#c4b5fd', 'UNDOCKED (resting) is violet');

// 4. THE REGRESSION: manual force-undock. Schedule is OFF, so a schedule-only
//    painter says DOCKED while the ships take no work.
r = render(payload({ ...base, enabled: false, in_window: false, active: false },
                   { undocked: true, force: '2026-08-20T06:00:00-04:00' }));
check(r.btn.textContent === '⚓ UNDOCKED', 'force-undock ⇒ button reads UNDOCKED (not the schedule)');
check(r.text.includes('manually undocked'), '  …and the body says manually undocked, not "takes work around the clock"');
check(!r.text.includes('take work around the clock'), '  …no contradicting clause');

// 5. the honest edge: clock inside the window but NOT armed
r = render(payload({ ...base, enabled: false, in_window: true, active: false }));
check(r.btn.textContent === '⚓ DOCKED', 'in-window but disarmed ⇒ still DOCKED');
check(r.text.includes('INSIDE the window') && r.text.includes('not armed'),
      '  …and says so explicitly rather than implying rest');

// 6. back-compat: a payload with no `undocked` falls back to the schedule test
els.restModeBtn.textContent = '';
updateRestModeUI({ enabled: true, active_now: true, rest_window: '20:00–06:00 ET' });
check(els.restModeBtn.textContent === '⚓ UNDOCKED', 'legacy payload (no `undocked`) still resolves via the schedule');

// dataset.enabled is what toggleRestMode() reads to decide the NEXT state, so a
// payload that never sets it would make the button always try to arm.
r = render(payload({ ...base, enabled: true, in_window: false, active: false }));
check(els.restModeBtn.dataset.enabled === 'true', 'button carries dataset.enabled=true when the schedule is armed');
r = render(payload({ ...base, enabled: false, in_window: false, active: false }));
check(els.restModeBtn.dataset.enabled === 'false', 'button carries dataset.enabled=false when disarmed');

console.log(failures ? `\n${failures} FAILED` : '\nall checks passed');
process.exitCode = failures ? 1 : 0;
