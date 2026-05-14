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
  await Promise.all([_scoutLoadOverview(), _scoutLoadJobs()]);
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
