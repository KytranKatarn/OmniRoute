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
  // Real escaper fallback — an identity function would silently disable
  // escaping if the shared esc() global is ever missing.
  var esc2 = (typeof esc === 'function') ? esc : function(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var profRows = (d.profiles || []).map(function(p) {
    return '<tr><td>' + p.agent_id + '</td><td>' + esc2(p.platform) + '</td><td>'
      + (p.profile_established ? '<span style="color:#22c55e">● ESTABLISHED</span>'
         : (p.error ? '<span style="color:#f59e0b">' + esc2(p.error) + '</span>'
                    : '<span style="color:#ef4444">● not established</span>'))
      + '</td></tr>';
  }).join('');
  var sessRows = (d.cookie_sessions || []).map(function(s) {
    var col = s.status === 'active' ? '#22c55e' : (s.status === 'stale' ? '#ef4444' : '#94a3b8');
    return '<tr>'
      + '<td>' + s.agent_id + (s.agent_name ? '<div style="font-size:0.6rem;color:#64748b">' + esc2(s.agent_name) + '</div>' : '') + '</td>'
      + '<td>' + esc2(s.platform) + '</td>'
      + '<td><span style="color:' + col + '">● ' + esc2(s.status) + '</span>'
      + (s.last_failure_reason ? '<div style="font-size:0.6rem;color:#f59e0b">' + esc2(String(s.last_failure_reason).slice(0, 60)) + '</div>' : '') + '</td>'
      + '<td style="font-size:0.65rem">' + esc2(String(s.last_used_at || '—').slice(0, 16)) + '</td>'
      + '<td style="font-size:0.65rem">' + (s.last_probe_ok === true ? '✓' : (s.last_probe_ok === false ? '✗' : '—')) + '</td>'
      + '<td style="font-size:0.65rem">' + (s.state_bytes ? Math.round(s.state_bytes / 1024) + ' KB' : '—') + '</td>'
      + '<td><button class="dhq-btn scout-expire-btn" style="font-size:0.6rem" data-agent="' + Number(s.agent_id) + '" data-platform="' + esc2(s.platform) + '">Expire</button></td>'
      + '</tr>';
  }).join('');
  el.classList.remove('dhq-loading');
  el.innerHTML =
    '<h4 style="margin:0 0 6px">DEVICE-TRUST PROFILES (persistent, noVNC one-time login)</h4>'
    + '<p style="font-size:0.7rem;color:rgba(255,255,255,0.5);margin:0 0 6px">Managed in S.I.G.N.A.L. → 🔐 Session. Kept warm daily at 12:30 ET.</p>'
    + '<table class="dhq-table" style="width:100%;margin-bottom:14px"><thead><tr><th>Agent</th><th>Platform</th><th>Profile</th></tr></thead>'
    + '<tbody>' + (profRows || '<tr><td colspan="3">none</td></tr>') + '</tbody></table>'
    + '<h4 style="margin:0 0 6px">COOKIE SESSIONS (encrypted storage_state)</h4>'
    + '<table class="dhq-table" style="width:100%;margin-bottom:14px"><thead><tr>'
    + '<th>Agent</th><th>Platform</th><th>Status</th><th>Last used</th><th>Probe</th><th>Size</th><th></th>'
    + '</tr></thead><tbody>' + (sessRows || '<tr><td colspan="7">none</td></tr>') + '</tbody></table>'
    + '<h4 style="margin:0 0 6px">IMPORT COOKIES</h4>'
    + '<p style="font-size:0.7rem;color:rgba(255,255,255,0.5);margin:0 0 6px">Paste a Cookie-Editor JSON export. Stored AES-encrypted server-side; used by session_fetch / skills for that agent+platform.</p>'
    + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">'
    + '<input id="scoutImpAgent" type="number" min="1" placeholder="agent id" value="342" style="width:100px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit">'
    + '<select id="scoutImpPlatform" class="dhq-select">'
    + _SCOUT_IMPORT_PLATFORMS.map(function(p) { return '<option value="' + p + '">' + p + '</option>'; }).join('')
    + '</select>'
    + '<textarea id="scoutImpCookies" placeholder="[ { cookie JSON array } ]" rows="3" style="flex:1 1 320px;background:#0d1117;border:1px solid #333;border-radius:6px;color:#e2e8f0;padding:6px 9px;font:inherit;font-size:0.7rem"></textarea>'
    + '<button class="dhq-btn dhq-btn-primary" onclick="scoutImportCookies()">Import</button>'
    + '<span id="scoutImpStatus" style="font-size:0.7rem;color:#94a3b8"></span>'
    + '</div>';
  // Bind expire handlers via dataset — never string-concatenated inline JS
  // (HTML entity escaping does not protect a JS-in-attribute context).
  el.querySelectorAll('.scout-expire-btn').forEach(function(b) {
    b.addEventListener('click', function() {
      scoutExpireSession(parseInt(b.dataset.agent, 10), b.dataset.platform);
    });
  });
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
