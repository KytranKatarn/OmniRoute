/**
 * Ops Alert Bar — Unified Ops Center persistent alert strip
 * Polls /tools/autonomy/api/ops-summary every 30s
 * SECURITY: All rendering uses createElement + textContent (no innerHTML)
 */
(function () {
    'use strict';

    var POLL_INTERVAL = 30000;
    var API_URL = '/tools/autonomy/api/ops-summary';
    var LS_SOUND = 'opsSoundEnabled';
    var LS_SNOOZE = 'opsSnoozedUntil';
    var LS_LAST_ALERTS = 'opsLastAlertIds';

    var bar = null;
    var audioCtx = null;
    var pollTimer = null;

    // --- Helpers ---

    function isSnoozed() {
        var until = localStorage.getItem(LS_SNOOZE);
        if (!until) return false;
        if (Date.now() < parseInt(until, 10)) return true;
        localStorage.removeItem(LS_SNOOZE);
        return false;
    }

    function isSoundEnabled() {
        var val = localStorage.getItem(LS_SOUND);
        return val === null ? true : val === 'true';
    }

    function setSoundEnabled(enabled) {
        localStorage.setItem(LS_SOUND, String(enabled));
    }

    function snooze() {
        localStorage.setItem(LS_SNOOZE, String(Date.now() + 3600000));
        if (bar) {
            bar.classList.remove('visible');
            bar.classList.remove('collapsed');
        }
    }

    // --- Web Audio chime ---

    function playChime() {
        if (!isSoundEnabled()) return;
        try {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            var now = audioCtx.currentTime;
            // Ascending two-tone beep
            [520, 780].forEach(function (freq, i) {
                var osc = audioCtx.createOscillator();
                var gain = audioCtx.createGain();
                osc.type = 'sine';
                osc.frequency.value = freq;
                gain.gain.value = 0.3;
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15 + i * 0.12);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start(now + i * 0.12);
                osc.stop(now + 0.15 + i * 0.12);
            });
        } catch (e) {
            // Audio not available — ignore silently
        }
    }

    function checkNewHighAlerts(data) {
        var currentIds = [];
        var pending = (data.approvals && data.approvals.pending) || 0;
        var e1h = data.errors_1h || {};
        var errCount = (e1h.bridge_failed || 0) + (e1h.loop_errors || 0);
        if (pending > 0) {
            currentIds.push('approvals:' + pending);
        }
        if (errCount > 0) {
            currentIds.push('errors:' + errCount);
        }
        var sig = currentIds.join('|');
        var lastSig = localStorage.getItem(LS_LAST_ALERTS) || '';
        localStorage.setItem(LS_LAST_ALERTS, sig);

        if (sig && sig !== lastSig && pending > 0) {
            playChime();
        }
    }

    // --- DOM rendering (safe methods only) ---

    function createSection(severity, label, value, href) {
        var section = document.createElement('div');
        section.className = 'ops-alert-section ' + severity;
        section.onclick = function () {
            location.href = href;
        };

        var dot = document.createElement('span');
        dot.className = 'ops-alert-dot';
        section.appendChild(dot);

        var labelEl = document.createElement('span');
        labelEl.className = 'ops-alert-label';
        labelEl.textContent = label;
        section.appendChild(labelEl);

        var valueEl = document.createElement('span');
        valueEl.className = 'ops-alert-value';
        valueEl.textContent = value;
        section.appendChild(valueEl);

        return section;
    }

    function createButton(text, title, onclick) {
        var btn = document.createElement('button');
        btn.className = 'ops-alert-btn';
        btn.title = title;
        btn.textContent = text;
        btn.onclick = onclick;
        return btn;
    }

    function renderBar(data) {
        if (!bar) return;

        // Clear existing content
        while (bar.firstChild) {
            bar.removeChild(bar.firstChild);
        }

        // Map nested API response to display values
        var approvals = (data.approvals && data.approvals.pending) || 0;
        var aj = data.active_jobs || {};
        var jobs = (aj.bridge_running || 0) + (aj.bridge_pending || 0);
        var loops = 0;
        if (aj.server_loops) {
            Object.keys(aj.server_loops).forEach(function (k) {
                if (aj.server_loops[k]) loops++;
            });
        }
        var e1h = data.errors_1h || {};
        var errors = (e1h.bridge_failed || 0) + (e1h.loop_errors || 0);

        var hasActionable = approvals > 0 || errors > 0;

        if (!hasActionable && (jobs > 0 || loops > 0)) {
            // Collapsed info-only state
            bar.classList.add('visible');
            bar.classList.add('collapsed');
            return;
        }

        if (!hasActionable && jobs === 0 && loops === 0) {
            // Nothing to show
            bar.classList.remove('visible');
            bar.classList.remove('collapsed');
            return;
        }

        // Full bar
        bar.classList.add('visible');
        bar.classList.remove('collapsed');

        // Approvals
        if (approvals > 0) {
            bar.appendChild(createSection(
                'severity-high',
                'APPROVALS',
                String(approvals) + ' PENDING',
                '/tools/department-hq/?tab=dispatch'
            ));
        }

        // Jobs running
        bar.appendChild(createSection(
            'ok',
            'JOBS',
            String(jobs) + ' RUNNING',
            '/tools/department-hq/?tab=dispatch'
        ));

        // Loops active
        bar.appendChild(createSection(
            'ok',
            'LOOPS',
            String(loops) + ' ACTIVE',
            '/tools/department-hq/?tab=dispatch'
        ));

        // Errors
        if (errors > 0) {
            bar.appendChild(createSection(
                'severity-low',
                'ERRORS',
                String(errors),
                '/tools/department-hq/?tab=dispatch'
            ));
        }

        // Right controls
        var right = document.createElement('div');
        right.className = 'ops-alert-right';

        var soundBtn = createButton(
            isSoundEnabled() ? '\uD83D\uDD0A' : '\uD83D\uDD07',
            'Toggle alert sound',
            function () {
                var nowEnabled = !isSoundEnabled();
                setSoundEnabled(nowEnabled);
                this.textContent = nowEnabled ? '\uD83D\uDD0A' : '\uD83D\uDD07';
            }
        );
        right.appendChild(soundBtn);

        var snoozeBtn = createButton(
            'SNOOZE 1H',
            'Hide alerts for 1 hour',
            function () {
                snooze();
            }
        );
        right.appendChild(snoozeBtn);

        bar.appendChild(right);
    }

    // --- Polling ---

    function fetchSummary() {
        if (isSnoozed()) {
            if (bar) {
                bar.classList.remove('visible');
                bar.classList.remove('collapsed');
            }
            return;
        }

        fetch(API_URL, { credentials: 'same-origin' })
            .then(function (res) {
                if (res.status === 401 || res.status === 403) {
                    // Not authorized — hide silently
                    if (bar) {
                        bar.classList.remove('visible');
                        bar.classList.remove('collapsed');
                    }
                    return null;
                }
                if (!res.ok) return null;
                return res.json();
            })
            .then(function (data) {
                if (!data) return;
                checkNewHighAlerts(data);
                renderBar(data);
            })
            .catch(function () {
                // Network error — hide silently
                if (bar) {
                    bar.classList.remove('visible');
                    bar.classList.remove('collapsed');
                }
            });
    }

    // --- Init ---

    function init() {
        bar = document.getElementById('opsAlertBar');
        if (!bar) return;

        fetchSummary();
        pollTimer = setInterval(fetchSummary, POLL_INTERVAL);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
