/* P.R.O.B.E. QA Tab — Repair Bay */
var _qaLoaded = false;
var _qaLastRunId = null;
var QA_API = '/tools/repair-bay/api';

function loadQaTab() {
    if (_qaLoaded) return;
    _qaLoaded = true;
    loadQaSuites();
    loadQaHistory();
}

function loadQaSuites() {
    fetch(QA_API + '/qa/suites')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var sel = document.getElementById('qaSuiteSelect');
            sel.textContent = '';
            if (data.suites && data.suites.length > 0) {
                data.suites.forEach(function(s) {
                    var opt = document.createElement('option');
                    opt.value = s.id;
                    opt.textContent = s.name + ' (' + s.suite_type + ')';
                    sel.appendChild(opt);
                });
                document.getElementById('qaCurrentSuite').textContent = data.suites.length;
            } else {
                var opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'No suites available';
                sel.appendChild(opt);
            }
        })
        .catch(function(e) { console.error('QA suites load failed:', e); });
}

function runQaSuite() {
    var suiteId = document.getElementById('qaSuiteSelect').value;
    if (!suiteId) return;
    var btn = document.getElementById('qaRunBtn');
    btn.disabled = true;
    btn.textContent = 'Running...';
    document.getElementById('qaLastStatus').textContent = '...';

    fetch(QA_API + '/qa/run/' + suiteId, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({triggered_by: 'manual'})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            _qaLastRunId = data.run_id;
            loadQaRunDetail(data.run_id);
            loadQaHistory();
            var pct = data.total > 0 ? Math.round(data.passed / data.total * 100) : 0;
            document.getElementById('qaPassRate').textContent = pct + '%';
            if (data.status === 'completed') {
                document.getElementById('qaLastStatus').textContent = 'PASS';
                document.getElementById('qaLastStatus').style.color = '#10b981';
            } else {
                document.getElementById('qaLastStatus').textContent = data.failed + ' FAIL';
                document.getElementById('qaLastStatus').style.color = '#ef4444';
            }
        } else {
            document.getElementById('qaLastStatus').textContent = 'ERROR';
            document.getElementById('qaLastStatus').style.color = '#ef4444';
        }
    })
    .catch(function(e) {
        document.getElementById('qaLastStatus').textContent = 'ERROR';
    })
    .finally(function() {
        btn.disabled = false;
        btn.textContent = 'Run Now';
    });
}

function loadQaRunDetail(runId) {
    fetch(QA_API + '/qa/runs/' + runId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) return;
            var panel = document.getElementById('qaResultsPanel');
            panel.style.display = 'block';
            var run = data.run;
            document.getElementById('qaRunSummary').textContent =
                run.passed + '/' + run.total_tests + ' passed | ' + (run.duration_ms || 0) + 'ms';

            var tbody = document.querySelector('#qaResultsTable tbody');
            tbody.textContent = '';
            (run.results || []).forEach(function(r) {
                var colors = {pass: '#10b981', fail: '#ef4444', error: '#f59e0b', skip: '#6b7280'};
                var color = colors[r.status] || '#6b7280';
                var tr = document.createElement('tr');

                var tdName = document.createElement('td');
                tdName.textContent = r.test_name || '';
                var tdType = document.createElement('td');
                tdType.textContent = r.test_type || '';
                var tdStatus = document.createElement('td');
                tdStatus.textContent = (r.status || '').toUpperCase();
                tdStatus.style.color = color;
                tdStatus.style.fontWeight = 'bold';
                var tdTime = document.createElement('td');
                tdTime.textContent = (r.response_time_ms || '—') + 'ms';
                var tdDetail = document.createElement('td');
                tdDetail.textContent = r.error_message || '';
                tdDetail.style.fontSize = '12px';
                tdDetail.style.maxWidth = '250px';
                tdDetail.style.overflow = 'hidden';
                tdDetail.style.textOverflow = 'ellipsis';
                tdDetail.style.whiteSpace = 'nowrap';
                var tdAction = document.createElement('td');
                if (r.screenshot_path) {
                    var a = document.createElement('a');
                    a.href = '/static/qa_screenshots/' + r.screenshot_path.split('/').pop();
                    a.target = '_blank';
                    a.style.color = '#00d4ff';
                    a.textContent = 'screenshot';
                    tdAction.appendChild(a);
                }

                tr.appendChild(tdName);
                tr.appendChild(tdType);
                tr.appendChild(tdStatus);
                tr.appendChild(tdTime);
                tr.appendChild(tdDetail);
                tr.appendChild(tdAction);
                tbody.appendChild(tr);
            });
        })
        .catch(function(e) { console.error('QA run detail failed:', e); });
}

function loadQaHistory() {
    fetch(QA_API + '/qa/runs?limit=10')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var tbody = document.querySelector('#qaHistoryTable tbody');
            tbody.textContent = '';
            if (!data.runs || data.runs.length === 0) {
                var tr = document.createElement('tr');
                var td = document.createElement('td');
                td.colSpan = 8;
                td.style.textAlign = 'center';
                td.style.color = '#666';
                td.style.padding = '20px';
                td.textContent = 'No runs yet';
                tr.appendChild(td);
                tbody.appendChild(tr);
                return;
            }
            data.runs.forEach(function(r) {
                var color = r.status === 'completed' ? '#10b981' : '#ef4444';
                var when = r.started_at ? new Date(r.started_at).toLocaleString() : '';
                var tr = document.createElement('tr');

                var cells = [
                    '#' + r.id,
                    r.suite_name || '',
                    r.triggered_by || '',
                    null, // status cell (special)
                    r.passed + '/' + r.total_tests,
                    (r.duration_ms || '—') + 'ms',
                    when
                ];
                cells.forEach(function(text, i) {
                    var td = document.createElement('td');
                    if (i === 3) {
                        td.textContent = (r.status || '').toUpperCase();
                        td.style.color = color;
                        td.style.fontWeight = 'bold';
                    } else if (i === 6) {
                        td.textContent = text;
                        td.style.fontSize = '12px';
                    } else {
                        td.textContent = text;
                    }
                    tr.appendChild(td);
                });

                var tdBtn = document.createElement('td');
                var btn = document.createElement('button');
                btn.className = 'dp-btn';
                btn.style.padding = '4px 8px';
                btn.style.fontSize = '11px';
                btn.textContent = 'View';
                btn.onclick = (function(id) {
                    return function() { loadQaRunDetail(id); };
                })(r.id);
                tdBtn.appendChild(btn);
                tr.appendChild(tdBtn);
                tbody.appendChild(tr);
            });
        })
        .catch(function(e) { console.error('QA history failed:', e); });
}

function generateQaReport() {
    if (!_qaLastRunId) { alert('Run a test first'); return; }
    var btn = document.getElementById('qaReportBtn');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    fetch(QA_API + '/qa/runs/' + _qaLastRunId + '/report', {method: 'POST'})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                window.open(QA_API + '/qa/runs/' + _qaLastRunId + '/report/download', '_blank');
            } else {
                alert('Report failed: ' + (data.error || 'unknown'));
            }
        })
        .catch(function(e) { alert('Report failed: ' + e.message); })
        .finally(function() {
            btn.disabled = false;
            btn.textContent = 'PDF Report';
        });
}
