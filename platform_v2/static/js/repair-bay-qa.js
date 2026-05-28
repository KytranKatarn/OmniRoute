/* P.R.O.B.E. QA Tab — Repair Bay */
var _qaLoaded = false;
var _qaLastRunId = null;
var QA_API = '/tools/repair-bay/api';

function loadQaTab() {
    if (_qaLoaded) return;
    _qaLoaded = true;
    loadQaSuites();
    loadQaHistory();
    loadModuleHealth();
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

            // Inject detail-panel styles once
            if (!document.getElementById('qa-detail-styles')) {
                var styleEl = document.createElement('style');
                styleEl.id = 'qa-detail-styles';
                styleEl.textContent = [
                    '.qa-main-row { cursor: pointer; }',
                    '.qa-main-row:hover { background: rgba(0,212,255,0.06); }',
                    '.qa-main-row td:first-child::before { content: "▶ "; font-size:10px; color:#555; margin-right:4px; transition: transform 0.15s; display:inline-block; }',
                    '.qa-main-row.qa-expanded td:first-child::before { content: "▼ "; color:#00d4ff; }',
                    '.qa-detail-row { display:none; }',
                    '.qa-detail-row.qa-open { display:table-row; }',
                    '.qa-detail-cell { padding: 10px 14px 14px 24px !important; background: #0d1117; border-top: none !important; }',
                    '.qa-detail-grid { display:grid; grid-template-columns: 1fr 1fr; gap:8px 20px; font-size:12px; }',
                    '.qa-detail-label { color:#6b7280; font-size:11px; text-transform:uppercase; letter-spacing:.05em; margin-bottom:2px; }',
                    '.qa-detail-value { color:#e5e7eb; word-break:break-all; font-family:monospace; }',
                    '.qa-error-full { color:#fca5a5; white-space:pre-wrap; word-break:break-all; max-height:120px; overflow-y:auto; background:#1a0a0a; padding:6px 8px; border-radius:3px; border-left:2px solid #ef4444; }',
                    '.qa-rt-bar-wrap { display:flex; align-items:center; gap:8px; }',
                    '.qa-rt-bar { height:8px; border-radius:4px; min-width:4px; max-width:160px; }',
                    '.qa-screenshot-thumb { max-width:220px; max-height:130px; border:1px solid #334155; border-radius:4px; margin-top:6px; cursor:zoom-in; display:block; }',
                    '.qa-screenshot-wrap { grid-column: 1 / -1; }',
                ].join('\n');
                document.head.appendChild(styleEl);
            }

            var tbody = document.querySelector('#qaResultsTable tbody');
            tbody.textContent = '';
            (run.results || []).forEach(function(r, idx) {
                var colors = {pass: '#10b981', fail: '#ef4444', error: '#f59e0b', skip: '#6b7280'};
                var color = colors[r.status] || '#6b7280';

                /* --- Summary row (clickable) --- */
                var tr = document.createElement('tr');
                tr.className = 'qa-main-row';

                var tdName = document.createElement('td');
                tdName.textContent = r.test_name || '';
                var tdType = document.createElement('td');
                tdType.textContent = r.test_type || '';
                var tdStatus = document.createElement('td');
                tdStatus.textContent = (r.status || '').toUpperCase();
                tdStatus.style.color = color;
                tdStatus.style.fontWeight = 'bold';
                var tdTime = document.createElement('td');
                tdTime.textContent = (r.response_time_ms != null ? r.response_time_ms : '—') + (r.response_time_ms != null ? 'ms' : '');
                var tdDetail = document.createElement('td');
                tdDetail.style.fontSize = '12px';
                tdDetail.style.maxWidth = '250px';
                tdDetail.style.overflow = 'hidden';
                tdDetail.style.textOverflow = 'ellipsis';
                tdDetail.style.whiteSpace = 'nowrap';
                tdDetail.textContent = r.error_message || '';
                // Blank action cell (screenshot now inside detail panel)
                var tdAction = document.createElement('td');

                tr.appendChild(tdName);
                tr.appendChild(tdType);
                tr.appendChild(tdStatus);
                tr.appendChild(tdTime);
                tr.appendChild(tdDetail);
                tr.appendChild(tdAction);

                /* --- Detail row --- */
                var detailTr = document.createElement('tr');
                detailTr.className = 'qa-detail-row';
                var detailTd = document.createElement('td');
                detailTd.className = 'qa-detail-cell';
                detailTd.colSpan = 6;

                // Response-time bar
                var rtMs = r.response_time_ms;
                var rtColor = rtMs == null ? '#4b5563'
                    : rtMs < 500  ? '#10b981'
                    : rtMs < 2000 ? '#f59e0b'
                    : '#ef4444';
                var rtWidth = rtMs == null ? 0 : Math.min(160, Math.round(rtMs / 50));

                var grid = document.createElement('div');
                grid.className = 'qa-detail-grid';

                function detailBlock(label, value, extraClass) {
                    var wrap = document.createElement('div');
                    var lbl = document.createElement('div');
                    lbl.className = 'qa-detail-label';
                    lbl.textContent = label;
                    var val = document.createElement('div');
                    val.className = 'qa-detail-value' + (extraClass ? ' ' + extraClass : '');
                    val.textContent = value || '—';
                    wrap.appendChild(lbl);
                    wrap.appendChild(val);
                    return wrap;
                }

                // URL / endpoint
                grid.appendChild(detailBlock('URL / Endpoint', r.url || ''));

                // Selector / assertion
                var assertions = r.assertions || {};
                var selectorVal = assertions.selector || assertions.element || assertions.xpath || '';
                grid.appendChild(detailBlock('Selector / Assertion', selectorVal));

                // Response-time with visual bar
                var rtWrap = document.createElement('div');
                var rtLbl = document.createElement('div');
                rtLbl.className = 'qa-detail-label';
                rtLbl.textContent = 'Response Time';
                var rtBarWrap = document.createElement('div');
                rtBarWrap.className = 'qa-rt-bar-wrap';
                var rtBar = document.createElement('div');
                rtBar.className = 'qa-rt-bar';
                rtBar.style.background = rtColor;
                rtBar.style.width = rtWidth + 'px';
                var rtLabel = document.createElement('span');
                rtLabel.style.color = rtColor;
                rtLabel.style.fontSize = '12px';
                rtLabel.textContent = rtMs != null ? rtMs + 'ms' : '—';
                rtBarWrap.appendChild(rtBar);
                rtBarWrap.appendChild(rtLabel);
                rtWrap.appendChild(rtLbl);
                rtWrap.appendChild(rtBarWrap);
                grid.appendChild(rtWrap);

                // Method / status codes
                var codeVal = '';
                if (r.method) codeVal += r.method;
                if (r.expected_status) codeVal += '  expected ' + r.expected_status;
                if (r.actual_status) codeVal += '  got ' + r.actual_status;
                grid.appendChild(detailBlock('Method / Status', codeVal));

                // Full error message (full row width)
                if (r.error_message) {
                    var errWrap = document.createElement('div');
                    errWrap.className = 'qa-screenshot-wrap'; // spans full width
                    var errLbl = document.createElement('div');
                    errLbl.className = 'qa-detail-label';
                    errLbl.textContent = 'Error Detail';
                    var errVal = document.createElement('pre');
                    errVal.className = 'qa-error-full';
                    errVal.textContent = r.error_message;
                    errWrap.appendChild(errLbl);
                    errWrap.appendChild(errVal);
                    grid.appendChild(errWrap);
                }

                // Screenshot preview (full row width)
                var screenshotPath = r.screenshot_path || (r.screenshot_url ? null : null);
                if (r.screenshot_path) {
                    var ssWrap = document.createElement('div');
                    ssWrap.className = 'qa-screenshot-wrap';
                    var ssLbl = document.createElement('div');
                    ssLbl.className = 'qa-detail-label';
                    ssLbl.textContent = 'Screenshot';
                    var ssImg = document.createElement('img');
                    ssImg.className = 'qa-screenshot-thumb';
                    ssImg.src = '/tools/repair-bay/api/qa/screenshot?path=' + encodeURIComponent(r.screenshot_path);
                    ssImg.alt = 'test screenshot';
                    ssImg.onerror = function() { ssWrap.style.display = 'none'; };
                    ssImg.onclick = function() { window.open(ssImg.src, '_blank'); };
                    ssWrap.appendChild(ssLbl);
                    ssWrap.appendChild(ssImg);
                    grid.appendChild(ssWrap);
                }

                detailTd.appendChild(grid);
                detailTr.appendChild(detailTd);

                // Toggle on row click
                tr.onclick = function() {
                    tr.classList.toggle('qa-expanded');
                    detailTr.classList.toggle('qa-open');
                };

                tbody.appendChild(tr);
                tbody.appendChild(detailTr);
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

/* Module Health — per-suite at-a-glance grid */
function loadModuleHealth() {
    var grid = document.getElementById('moduleHealthGrid');
    if (!grid) return;
    fetch(QA_API + '/qa/suite-health')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            grid.textContent = '';
            if (!data.success || !data.suites || data.suites.length === 0) {
                var msg = document.createElement('div');
                msg.style.cssText = 'color:#94a3b8;font-family:IBM Plex Mono,monospace;font-size:0.75rem;padding:16px;text-align:center;grid-column:1/-1;';
                msg.textContent = 'No active suites found.';
                grid.appendChild(msg);
                return;
            }
            data.suites.forEach(function(s) {
                var card = document.createElement('div');
                card.style.cssText = 'background:rgba(0,0,0,0.3);border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;';

                // Status colour + icon
                var st = (s.last_run_status || '').toLowerCase();
                var statusColor, statusIcon, statusLabel;
                if (!s.last_run_at) {
                    statusColor = '#6b7280'; statusIcon = '○'; statusLabel = 'NEVER RUN';
                } else if (st === 'completed') {
                    statusColor = '#10b981'; statusIcon = '✅'; statusLabel = 'PASS';
                } else if (st === 'failed') {
                    statusColor = '#ef4444'; statusIcon = '❌'; statusLabel = 'FAIL';
                } else if (st === 'running') {
                    statusColor = '#f59e0b'; statusIcon = '⚠'; statusLabel = 'RUNNING';
                } else {
                    statusColor = '#6b7280'; statusIcon = '○'; statusLabel = (st || 'UNKNOWN').toUpperCase();
                }

                // Suite name row
                var nameEl = document.createElement('div');
                nameEl.style.cssText = 'font-family:IBM Plex Mono,monospace;font-size:0.72rem;font-weight:bold;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
                nameEl.title = s.suite_name;
                nameEl.textContent = s.suite_name;

                // Status badge row
                var statusRow = document.createElement('div');
                statusRow.style.cssText = 'display:flex;align-items:center;gap:6px;';
                var badge = document.createElement('span');
                badge.style.cssText = 'font-family:IBM Plex Mono,monospace;font-size:0.65rem;font-weight:bold;color:' + statusColor + ';letter-spacing:1px;';
                badge.textContent = statusIcon + ' ' + statusLabel;
                statusRow.appendChild(badge);

                // Pass rate bar
                var barWrap = document.createElement('div');
                barWrap.style.cssText = 'background:rgba(255,255,255,0.07);border-radius:3px;height:5px;overflow:hidden;';
                var bar = document.createElement('div');
                var pct = s.last_pass_rate != null ? parseFloat(s.last_pass_rate) : 0;
                var barColor = pct >= 90 ? '#10b981' : pct >= 70 ? '#f59e0b' : '#ef4444';
                if (!s.last_run_at) barColor = '#374151';
                bar.style.cssText = 'height:100%;width:' + (s.last_run_at ? pct : 0) + '%;background:' + barColor + ';border-radius:3px;transition:width 0.4s;';
                barWrap.appendChild(bar);

                // Meta row: pass rate % + timestamp
                var metaRow = document.createElement('div');
                metaRow.style.cssText = 'display:flex;justify-content:space-between;align-items:center;';
                var rateEl = document.createElement('span');
                rateEl.style.cssText = 'font-family:IBM Plex Mono,monospace;font-size:0.65rem;color:#94a3b8;';
                rateEl.textContent = s.last_run_at ? pct + '% pass · ' + s.total_runs + ' runs' : 'No runs yet';
                var timeEl = document.createElement('span');
                timeEl.style.cssText = 'font-family:IBM Plex Mono,monospace;font-size:0.6rem;color:#64748b;';
                if (s.last_run_at) {
                    var d = new Date(s.last_run_at);
                    timeEl.textContent = d.toLocaleDateString([], {month:'short',day:'numeric'});
                    timeEl.title = d.toLocaleString();
                }
                metaRow.appendChild(rateEl);
                metaRow.appendChild(timeEl);

                card.appendChild(nameEl);
                card.appendChild(statusRow);
                card.appendChild(barWrap);
                card.appendChild(metaRow);
                grid.appendChild(card);
            });
        })
        .catch(function(e) {
            console.error('Module health load failed:', e);
            if (grid) {
                grid.textContent = '';
                var err = document.createElement('div');
                err.style.cssText = 'color:#ef4444;font-family:IBM Plex Mono,monospace;font-size:0.75rem;padding:12px;grid-column:1/-1;';
                err.textContent = 'Failed to load suite health.';
                grid.appendChild(err);
            }
        });
}
window.loadModuleHealth = loadModuleHealth;
