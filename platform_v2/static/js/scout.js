// platform_v2/static/js/scout.js
// S.C.O.U.T. tab — Field Data Correspondent
'use strict';

function _scoutBadgeClass(status) {
  var map = {
    pending:      'dhq-badge-info',
    running:      'dhq-badge-warning',
    completed:    'dhq-badge-success',
    approved:     'dhq-badge-success',
    needs_review: 'dhq-badge-warning',
    failed:       'dhq-badge-danger',
    rejected:     'dhq-badge-danger',
  };
  return map[status] || 'dhq-badge-info';
}

async function loadScoutTab() {
  await Promise.all([_scoutLoadOverview(), _scoutLoadJobs(), _scoutLoadSessions()]);
}

/* ── Session vault (#3708 v1) — list cookie sessions + device-trust
   profiles, import cookies, expire stale sessions. Metadata only;
   cookie contents never reach the browser. ── */
var _SCOUT_IMPORT_PLATFORMS = ['linkedin', 'twitter', 'facebook', 'claude', 'deepseek', 'openai'];
// #4006: browser_platforms registry cache (null until first successful load;
// the static list above stays as the fallback).
var _scoutPlatforms = null;
// #4007: egress catalog (hub + online CPU outposts). null until first load.
var _scoutEgressNodes = null;

async function _scoutLoadSessions() {
  var el = document.getElementById('scout-sessions-content');
  if (!el) return;
  var d;
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions');
    d = await r.json();
  } catch (e) {
    el.innerHTML = '<div class="dhq-empty">Session vault unavailable</div>';
    return;
  }
  try {
    var prr = await fetch('/tools/department-hq/api/scout/platforms');
    var pdd = await prr.json();
    if (pdd.success && Array.isArray(pdd.platforms) && pdd.platforms.length) _scoutPlatforms = pdd.platforms;
  } catch (e) { /* registry unavailable — fall back to the static list */ }
  try {
    var enr = await fetch('/tools/department-hq/api/scout/egress-nodes');
    var edd = await enr.json();
    if (edd.success && Array.isArray(edd.nodes)) _scoutEgressNodes = edd.nodes;
  } catch (e) { /* catalog unavailable — egress dropdown falls back to hub-only */ }
  // Real escaper fallback — an identity function would silently disable
  // escaping if the shared esc() global is ever missing.
  var esc2 = (typeof esc === 'function') ? esc : function(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  // Dropdown sources: registry when loaded, static fallback otherwise.
  var importPlats = _scoutPlatforms
    ? _scoutPlatforms.map(function(p) { return p.platform; })
    : _SCOUT_IMPORT_PLATFORMS;
  var loginPlats = _scoutPlatforms
    ? _scoutPlatforms.filter(function(p) { return p.login_url; })
    : [];
  var profRows = (d.profiles || []).map(function(p) {
    // Slice 3 (#5627): ARMED means credentials are stored, so a logged-out profile
    // can repair itself instead of waiting for a human noVNC login.
    var armed;
    if (p.auto_relogin_armed === true) {
      armed = '<span style="color:#22c55e">● ARMED</span>';
    } else if (p.auto_relogin_armed === false) {
      armed = '<span style="color:#94a3b8">○ manual only</span>';
    } else {
      armed = '<span style="color:#f59e0b">? unknown</span>';
    }
    return '<tr><td>' + p.agent_id + '</td><td>' + esc2(p.platform) + '</td><td>'
      + (p.profile_established ? '<span style="color:#22c55e">● ESTABLISHED</span>'
         : (p.error ? '<span style="color:#f59e0b">' + esc2(p.error) + '</span>'
                    : '<span style="color:#ef4444">● not established</span>'))
      + '</td><td>' + armed + '</td></tr>';
  }).join('');
  // Arming form options — one per known profile.
  var armOptions = (d.profiles || []).map(function(p) {
    var v = p.agent_id + '|' + p.platform;
    return '<option value="' + esc2(v) + '">' + p.agent_id + ' · ' + esc2(p.platform) + '</option>';
  }).join('');
  // #4007 egress dropdown: hub default + each egress-READY node (others are
  // listed disabled so a dead proxy is never selectable). Established
  // device-trust profiles get a step-up-wall warning before moving off hub.
  var establishedKeys = {};
  (d.profiles || []).forEach(function(p) {
    if (p.profile_established) establishedKeys[p.agent_id + '|' + p.platform] = true;
  });
  function egressOptions(current) {
    var nodes = _scoutEgressNodes || [{ node_name: 'hub', country: 'Canada (hub direct)', egress_ready: true }];
    var cur = current || 'hub';
    return nodes.map(function(n) {
      var sel = (n.node_name === cur) ? ' selected' : '';
      var dis = n.egress_ready ? '' : ' disabled';
      var label = (n.node_name === 'hub') ? 'Hub (default)' : esc2(n.country || n.node_name);
      if (!n.egress_ready && n.node_name !== 'hub') label += ' — no proxy';
      return '<option value="' + esc2(n.node_name) + '"' + sel + dis + '>' + label + '</option>';
    }).join('');
  }
  var sessRows = (d.cookie_sessions || []).map(function(s) {
    var col = s.status === 'active' ? '#22c55e' : (s.status === 'stale' ? '#ef4444' : '#94a3b8');
    var estab = establishedKeys[s.agent_id + '|' + s.platform] ? '1' : '';
    return '<tr>'
      + '<td>' + s.agent_id + (s.agent_name ? '<div style="font-size:0.6rem;color:#64748b">' + esc2(s.agent_name) + '</div>' : '') + '</td>'
      + '<td>' + esc2(s.platform) + '</td>'
      + '<td><span style="color:' + col + '">● ' + esc2(s.status) + '</span>'
      + (s.last_failure_reason ? '<div style="font-size:0.6rem;color:#f59e0b">' + esc2(String(s.last_failure_reason).slice(0, 60)) + '</div>' : '') + '</td>'
      + '<td style="font-size:0.65rem">' + esc2(String(s.last_used_at || '—').slice(0, 16)) + '</td>'
      + '<td style="font-size:0.65rem">' + (s.last_probe_ok === true ? '✓' : (s.last_probe_ok === false ? '✗' : '—')) + '</td>'
      + '<td style="font-size:0.65rem">' + (s.state_bytes ? Math.round(s.state_bytes / 1024) + ' KB' : '—') + '</td>'
      + '<td><select class="dhq-select scout-egress-sel" style="font-size:0.6rem" data-agent="' + Number(s.agent_id) + '" data-platform="' + esc2(s.platform) + '" data-estab="' + estab + '" data-current="' + esc2(s.egress_pref || 'hub') + '">'
      + egressOptions(s.egress_pref) + '</select></td>'
      + '<td><button class="dhq-btn scout-expire-btn" style="font-size:0.6rem" data-agent="' + Number(s.agent_id) + '" data-platform="' + esc2(s.platform) + '">Expire</button></td>'
      + '</tr>';
  }).join('');
  el.classList.remove('dhq-loading');
  el.innerHTML =
    '<h4 style="margin:0 0 6px">DEVICE-TRUST PROFILES (persistent, noVNC one-time login)</h4>'
    + '<p style="font-size:0.7rem;color:rgba(255,255,255,0.5);margin:0 0 6px">Managed in S.I.G.N.A.L. → 🔐 Session. Kept warm daily at 12:30 ET.</p>'
    + '<table class="dhq-table" style="width:100%;margin-bottom:8px"><thead><tr><th>Agent</th><th>Platform</th><th>Profile</th><th>Auto re-login</th></tr></thead>'
    + '<tbody>' + (profRows || '<tr><td colspan="4">none</td></tr>') + '</tbody></table>'
    + '<div style="border:1px solid rgba(255,255,255,0.12);border-radius:4px;padding:8px;margin-bottom:14px">'
    + '<div style="font-size:0.7rem;font-weight:600;margin-bottom:4px">ARM AUTO RE-LOGIN</div>'
    + '<p style="font-size:0.65rem;color:rgba(255,255,255,0.5);margin:0 0 6px">'
    + 'Stores the login encrypted so a logged-out profile repairs itself instead of pausing posting. '
    + 'An email challenge is cleared automatically; phone/CAPTCHA still needs a noVNC login. '
    + 'Write-only — the password is never shown again.</p>'
    + '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
    + '<select id="scoutArmTarget" class="dhq-select" style="font-size:0.65rem">' + armOptions + '</select>'
    + '<input id="scoutArmUser" class="dhq-input" style="font-size:0.65rem" placeholder="login email" autocomplete="off">'
    + '<input id="scoutArmPass" class="dhq-input" style="font-size:0.65rem" placeholder="password" type="password" autocomplete="new-password">'
    + '<button class="dhq-btn" style="font-size:0.65rem" onclick="scoutArmRelogin()">Arm</button>'
    + '<span id="scoutArmMsg" style="font-size:0.65rem;color:rgba(255,255,255,0.6)"></span>'
    + '</div></div>'
    + '<div style="display:flex;justify-content:space-between;align-items:center;margin:0 0 6px">'
    + '<h4 style="margin:0">COOKIE SESSIONS (encrypted storage_state)</h4>'
    + '<button class="dhq-btn" style="font-size:0.6rem" onclick="scoutProbeSessions()">↻ Probe now</button></div>'
    + '<table class="dhq-table" style="width:100%;margin-bottom:14px"><thead><tr>'
    + '<th>Agent</th><th>Platform</th><th>Status</th><th>Last used</th><th>Probe</th><th>Size</th><th>Egress</th><th></th>'
    + '</tr></thead><tbody>' + (sessRows || '<tr><td colspan="8">none</td></tr>') + '</tbody></table>'
    + '<h4 style="margin:0 0 6px">IMPORT COOKIES</h4>'
    + '<p style="font-size:0.7rem;color:rgba(255,255,255,0.5);margin:0 0 6px">Paste a Cookie-Editor JSON export. Stored AES-encrypted server-side; used by session_fetch / skills for that agent+platform.</p>'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">'
    + '<input id="scoutImpAgent" type="number" min="1" placeholder="agent id" value="342" style="width:100px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit">'
    + '<select id="scoutImpPlatform" class="dhq-select">'
    + importPlats.map(function(p) { return '<option value="' + esc2(p) + '">' + esc2(p) + '</option>'; }).join('')
    + '</select>'
    + '<textarea id="scoutImpCookies" placeholder="[ { cookie JSON array } ]" rows="3" style="flex:1 1 320px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem"></textarea>'
    + '<button class="dhq-btn dhq-btn-primary" onclick="scoutImportCookies()">Import</button>'
    + '<span id="scoutImpStatus" style="font-size:0.7rem;color:#94a3b8"></span>'
    + '</div>'
    /* ── #4006 — interactive login capture for ANY registry platform ── */
    + '<h4 style="margin:14px 0 6px">CAPTURE NEW SESSION (interactive login)</h4>'
    + '<p style="font-size:0.7rem;color:rgba(255,255,255,0.5);margin:0 0 6px">'
    + 'Start a one-time headed login, complete it in the noVNC window (LAN/mesh only), then Stop &amp; save — '
    + 'the device-trust profile is flushed AND the session lands in the vault above (health-probed every 4h).</p>'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
    + '<input id="scoutCapAgent" type="number" min="1" placeholder="agent id" value="342" style="width:100px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit">'
    + '<select id="scoutCapPlatform" class="dhq-select">'
    + loginPlats.map(function(p) { return '<option value="' + esc2(p.platform) + '">' + esc2(p.display_name || p.platform) + '</option>'; }).join('')
    + '</select>'
    + '<button class="dhq-btn dhq-btn-primary" onclick="scoutLoginStart()">Start login</button>'
    + '<button class="dhq-btn" onclick="scoutLoginStop()">Stop &amp; save</button>'
    + '<span id="scoutCapStatus" style="font-size:0.7rem;color:#94a3b8"></span>'
    + '</div>'
    + '<div id="scoutCapSurface" style="font-size:0.7rem;color:#94a3b8;margin:6px 0 0"></div>'
    + '<details style="margin-top:8px"><summary style="font-size:0.7rem;color:#94a3b8;cursor:pointer">+ Add platform to registry</summary>'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:6px">'
    + '<input id="scoutNewKey" placeholder="key (a-z0-9_-)" style="width:130px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem">'
    + '<input id="scoutNewName" placeholder="display name" style="width:150px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem">'
    + '<input id="scoutNewHosts" placeholder="hosts, comma-separated" style="flex:1 1 220px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem">'
    + '<input id="scoutNewLogin" placeholder="https login URL" style="flex:1 1 220px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem">'
    + '<input id="scoutNewProbe" placeholder="https probe URL (optional)" style="flex:1 1 220px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem">'
    + '<button class="dhq-btn" onclick="scoutAddPlatform()">Add</button>'
    + '<span id="scoutNewStatus" style="font-size:0.7rem;color:#94a3b8"></span>'
    + '</div></details>';
  // Bind expire handlers via dataset — never string-concatenated inline JS
  // (HTML entity escaping does not protect a JS-in-attribute context).
  el.querySelectorAll('.scout-expire-btn').forEach(function(b) {
    b.addEventListener('click', function() {
      scoutExpireSession(parseInt(b.dataset.agent, 10), b.dataset.platform);
    });
  });
  el.querySelectorAll('.scout-egress-sel').forEach(function(sel) {
    sel.addEventListener('change', function() {
      scoutSetEgress(sel);
    });
  });
}

/* ── #4007 — per-session browse-from-country egress ── */
async function scoutSetEgress(sel) {
  var agentId = parseInt(sel.dataset.agent, 10);
  var platform = sel.dataset.platform;
  var pref = sel.value;
  var prev = sel.dataset.current || 'hub';
  // Step-up-wall guard (KB #272122): moving an ESTABLISHED device-trust profile
  // off hub egress changes its exit IP/country and can re-trigger login walls.
  if (sel.dataset.estab === '1' && pref !== 'hub' && pref !== prev) {
    if (!confirm('This platform has an ESTABLISHED device-trust profile (logged in from the hub IP). '
        + 'Routing it through another country changes the exit IP and may re-trigger a login/2FA wall. '
        + 'Switch egress anyway?')) {
      sel.value = prev;
      return;
    }
  }
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions/' + agentId + '/'
        + encodeURIComponent(platform) + '/egress', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ egress_pref: pref })
    });
    var d = await r.json();
    if (d.success) {
      sel.dataset.current = pref;
    } else {
      alert('Egress change failed: ' + (d.error || 'unknown'));
      sel.value = prev;
    }
  } catch (e) {
    alert('Egress change failed: ' + e);
    sel.value = prev;
  }
}

// Slice 3 (#5627) — store the login so the profile can repair itself.
// Deliberately NOT prompt()/alert()-driven for input: a modal dialog blocks the
// page for automation and makes this untestable. Status goes to an inline span.
async function scoutArmRelogin() {
  var target = document.getElementById('scoutArmTarget');
  var userEl = document.getElementById('scoutArmUser');
  var passEl = document.getElementById('scoutArmPass');
  var msg = document.getElementById('scoutArmMsg');
  if (!target || !userEl || !passEl || !msg) return;

  var parts = String(target.value || '').split('|');
  var agentId = parts[0];
  var platform = parts[1];
  if (!agentId || !platform) { msg.textContent = 'pick a profile'; return; }
  if (!userEl.value || !passEl.value) { msg.textContent = 'login and password required'; return; }

  msg.textContent = 'storing…';
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions/' + encodeURIComponent(agentId)
      + '/' + encodeURIComponent(platform) + '/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: userEl.value, password: passEl.value })
    });
    var d = await r.json();
    if (d.success) {
      msg.textContent = '✓ armed';
      // Clear immediately — never leave a password sitting in the DOM.
      userEl.value = '';
      passEl.value = '';
      await _scoutLoadSessions();
    } else {
      msg.textContent = 'failed: ' + (d.error || 'unknown');
    }
  } catch (e) {
    msg.textContent = 'failed: ' + e;
  }
}

async function scoutProbeSessions() {
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions/probe', { method: 'POST' });
    var d = await r.json();
    var n = d.results ? Object.keys(d.results).length : 0;
    alert('Probed ' + n + ' active session(s) — see updated statuses.');
  } catch (e) { alert('Probe failed: ' + e); }
  await _scoutLoadSessions();
}

async function scoutExpireSession(agentId, platform) {
  if (!confirm('Expire ' + agentId + '/' + platform + '? Skills stop trusting it until re-imported.')) return;
  try {
    await fetch('/tools/department-hq/api/scout/sessions/' + agentId + '/' + encodeURIComponent(platform) + '/expire', { method: 'POST' });
  } catch (e) { alert('Expire failed: ' + e); }
  await _scoutLoadSessions();
}

async function scoutImportCookies() {
  var st = document.getElementById('scoutImpStatus');
  var aid = parseInt(document.getElementById('scoutImpAgent').value, 10);
  var plat = document.getElementById('scoutImpPlatform').value;
  var cookies;
  try { cookies = JSON.parse(document.getElementById('scoutImpCookies').value); }
  catch (e) { st.textContent = 'Invalid JSON'; st.style.color = '#fca5a5'; return; }
  if (!aid || !Array.isArray(cookies) || !cookies.length) {
    st.textContent = 'agent id + non-empty cookie array required'; st.style.color = '#fca5a5'; return;
  }
  st.textContent = 'Importing…'; st.style.color = '#94a3b8';
  try {
    var r = await fetch('/tools/department-hq/api/sessions/' + aid + '/' + encodeURIComponent(plat) + '/import-cookies', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookies: cookies })
    });
    var d = await r.json();
    if (d.success) {
      st.textContent = '✓ ' + d.cookies_imported + ' cookies stored encrypted'; st.style.color = '#34d399';
      document.getElementById('scoutImpCookies').value = '';
      await _scoutLoadSessions();
    } else { st.textContent = d.error || 'Import failed'; st.style.color = '#fca5a5'; }
  } catch (e) { st.textContent = 'Network error'; st.style.color = '#fca5a5'; }
}

/* ── #4006 — interactive login capture ── */
async function scoutLoginStart() {
  var st = document.getElementById('scoutCapStatus');
  var aid = parseInt(document.getElementById('scoutCapAgent').value, 10);
  var plat = document.getElementById('scoutCapPlatform').value;
  if (!aid || !plat) { st.textContent = 'agent id + platform required'; st.style.color = '#fca5a5'; return; }
  st.textContent = 'Starting…'; st.style.color = '#94a3b8';
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions/login/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: aid, platform: plat })
    });
    var d = await r.json();
    if (d.started) {
      st.textContent = '✓ headed browser running — log in via noVNC, then Stop & save';
      st.style.color = '#34d399';
    } else {
      st.textContent = d.error || 'start failed'; st.style.color = '#fca5a5';
    }
  } catch (e) { st.textContent = 'Network error'; st.style.color = '#fca5a5'; }
  await scoutLoginSurface();
}

async function scoutLoginStop() {
  var st = document.getElementById('scoutCapStatus');
  st.textContent = 'Stopping (profile flush + vault export)…'; st.style.color = '#94a3b8';
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions/login/stop', { method: 'POST' });
    var d = await r.json();
    if (d.stopped) {
      st.textContent = '✓ saved — profile flushed; session exported to the vault';
      st.style.color = '#34d399';
    } else {
      st.textContent = d.error || 'nothing was running'; st.style.color = '#f59e0b';
    }
  } catch (e) { st.textContent = 'Network error'; st.style.color = '#fca5a5'; }
  await scoutLoginSurface();
  await _scoutLoadSessions();
}

async function scoutLoginSurface() {
  var el = document.getElementById('scoutCapSurface');
  if (!el) return;
  while (el.firstChild) el.removeChild(el.firstChild);
  try {
    var r = await fetch('/tools/department-hq/api/scout/sessions/login/status');
    var d = await r.json();
    var ls = d.login_surface || {};
    if (ls.login_browser_running) {
      var a = document.createElement('a');
      a.href = 'http://' + location.hostname + ':4280/vnc.html';
      a.target = '_blank';
      a.rel = 'noopener';
      a.style.color = '#22d3ee';
      a.textContent = 'Open noVNC (' + location.hostname + ':4280) — LAN/mesh only';
      el.appendChild(a);
      if (d.vnc_password) {
        var s = document.createElement('span');
        s.style.marginLeft = '10px';
        s.textContent = 'VNC password: ' + d.vnc_password;
        el.appendChild(s);
      }
      if (ls.target) {
        var t = document.createElement('span');
        t.style.cssText = 'margin-left:10px;color:#64748b';
        t.textContent = 'target: ' + (ls.target.agent_id || '?') + '/' + (ls.target.platform || '?');
        el.appendChild(t);
      }
    } else {
      el.textContent = 'no login browser running';
    }
  } catch (e) { el.textContent = 'login surface status unavailable'; }
}

async function scoutAddPlatform() {
  var st = document.getElementById('scoutNewStatus');
  var hosts = (document.getElementById('scoutNewHosts').value || '')
    .split(',').map(function(h) { return h.trim(); }).filter(Boolean);
  var payload = {
    platform: (document.getElementById('scoutNewKey').value || '').trim().toLowerCase(),
    display_name: (document.getElementById('scoutNewName').value || '').trim(),
    allowed_hosts: hosts,
    login_url: (document.getElementById('scoutNewLogin').value || '').trim(),
    probe_url: (document.getElementById('scoutNewProbe').value || '').trim()
  };
  if (!payload.platform || !payload.display_name || !hosts.length) {
    st.textContent = 'key, display name + at least one host required'; st.style.color = '#fca5a5'; return;
  }
  st.textContent = 'Adding…'; st.style.color = '#94a3b8';
  try {
    var r = await fetch('/tools/department-hq/api/scout/platforms', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    var d = await r.json();
    if (d.success) {
      st.textContent = '✓ added'; st.style.color = '#34d399';
      await _scoutLoadSessions(); // re-renders dropdowns from the registry
    } else {
      st.textContent = d.error || 'add failed'; st.style.color = '#fca5a5';
    }
  } catch (e) { st.textContent = 'Network error'; st.style.color = '#fca5a5'; }
}

async function _scoutLoadOverview() {
  try {
    var r = await fetch('/tools/department-hq/api/scout/overview');
    var d = await r.json();
    var pool = d.pool || {};

    var el = document.getElementById('scout-pool-status');
    if (el) {
      el.textContent =
        'Browser Pool: ' +
        (pool.slots_available != null ? pool.slots_available : '?') +
        '/' +
        (pool.pool_size != null ? pool.pool_size : '?') +
        ' slots free';
    }

    var countEl = document.getElementById('scout-job-counts');
    if (countEl) {
      while (countEl.firstChild) countEl.removeChild(countEl.firstChild);
      Object.entries(d.job_counts || {}).forEach(function(entry) {
        var status = entry[0], n = entry[1];
        var span = document.createElement('span');
        span.className = 'dhq-badge ' + _scoutBadgeClass(status);
        span.style.cssText = 'font-size:0.7rem;padding:2px 7px;border-radius:10px;';
        span.textContent = status + ': ' + n;
        countEl.appendChild(span);
      });
    }
  } catch (e) {
    var el = document.getElementById('scout-pool-status');
    if (el) el.textContent = 'Pool unavailable';
  }
}

async function _scoutLoadJobs(status) {
  var qs = status ? '?status=' + encodeURIComponent(status) : '';
  try {
    var r = await fetch('/tools/department-hq/api/scout/jobs' + qs);
    var d = await r.json();
    var tbody = document.getElementById('scout-jobs-tbody');
    if (!tbody) return;
    while (tbody.firstChild) tbody.removeChild(tbody.firstChild);

    var jobs = d.jobs || [];
    if (jobs.length === 0) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 7;
      td.style.cssText = 'text-align:center;color:rgba(255,255,255,0.4);padding:20px;font-size:0.8rem;';
      td.textContent = 'No jobs found.';
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    jobs.forEach(function(job) {
      var tr = document.createElement('tr');

      var fields = [
        { val: String(job.id || ''), cls: null },
        { val: String(job.job_type || ''), cls: null },
        { val: String(job.target_url || '').slice(0, 50), cls: null },
        { val: job.status, cls: 'badge' },
        { val: 'Tier ' + (job.egress_tier || '?'), cls: null },
        { val: String(job.created_at || '').slice(0, 16), cls: null },
        { val: String(job.findings || '').slice(0, 80), cls: null },
      ];

      fields.forEach(function(f) {
        var td = document.createElement('td');
        if (f.cls === 'badge') {
          var span = document.createElement('span');
          span.className = 'dhq-badge ' + _scoutBadgeClass(job.status);
          span.style.cssText = 'font-size:0.7rem;padding:2px 7px;border-radius:10px;';
          span.textContent = f.val;
          td.appendChild(span);
        } else {
          td.textContent = f.val;
        }
        tr.appendChild(td);
      });

      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error('Scout jobs load failed:', e);
  }
}

async function scoutRunNow(jobType, evt) {
  var btn = evt && evt.currentTarget ? evt.currentTarget : null;
  if (btn) { btn.disabled = true; }
  var orig = btn ? btn.textContent : '';
  if (btn) btn.textContent = 'Running...';
  try {
    var r = await fetch('/tools/department-hq/api/scout/run-now', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_type: jobType }),
    });
    var d = await r.json();
    if (d.job_id) {
      alert('Job #' + d.job_id + ' queued. Check Jobs tab.');
      await _scoutLoadJobs();
    } else {
      alert('Error: ' + (d.error || JSON.stringify(d)));
    }
  } catch (e) {
    alert('Request failed: ' + String(e));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = orig; }
  }
}

async function scoutRefresh() {
  await Promise.all([_scoutLoadOverview(), _scoutLoadJobs()]);
}

function scoutSubtab(btn, name) {
  document.querySelectorAll('.scout-subtab-panel').forEach(function(p) {
    p.style.display = 'none';
  });
  document.querySelectorAll('.scout-subtab-btn').forEach(function(b) {
    b.classList.remove('active');
  });
  var panel = document.getElementById('scout-panel-' + name);
  if (panel) panel.style.display = '';
  btn.classList.add('active');
  var statusMap = { reports: 'needs_review', procurement: 'approved' };
  _scoutLoadJobs(statusMap[name] || null);
}
