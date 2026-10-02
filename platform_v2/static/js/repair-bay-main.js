/* Repair Bay — main tab dispatcher + shared loaders
 *
 * Companion to repair-bay-qa.js. This file owns:
 *   - Tab init + DOMContentLoaded bootstrap
 *   - Reviews tab (GitHub PR list with check + CodeRabbit status)
 *   - Repairs tab (improvement_proposals list + review modal)
 *   - Diagnose tab (scan status + run)
 *   - Test Bay tab (sandbox list)
 *   - Ship tab (deploy ready + history + F.O.R.G.E. stats)
 *
 * Agent-related data MUST come from Department HQ via the station proxy
 * (/api/station/crew) — never from raw DB queries. See Project #242.
 */

var RB_API = '/tools/repair-bay/api';
var _reviewsLoaded = false;
var _repairsLoaded = false;
var _diagnoseLoaded = false;
var _testBayLoaded = false;
var _shipLoaded = false;

/* Reviews tab silent-refresh polling.
 * Runs every REVIEWS_POLL_INTERVAL_MS while the Reviews tab is active.
 * Cleared when user switches to any other tab. Project #242 follow-up. */
var _reviewsPollTimer = null;
var REVIEWS_POLL_INTERVAL_MS = 60000;  // 60s
var _reviewsLastLoadedAt = null;

/* ── Shared helpers ───────────────────────────────────────────── */
function _rbFetchJson(url, opts) {
    return fetch(url, opts || {}).then(function(r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
        return r.json();
    });
}

function _rbClear(el) {
    while (el && el.firstChild) el.removeChild(el.firstChild);
}

function _rbMakeEl(tag, opts) {
    var el = document.createElement(tag);
    if (opts) {
        if (opts.cls) el.className = opts.cls;
        if (opts.style) el.style.cssText = opts.style;
        if (opts.text) el.textContent = opts.text;
        if (opts.href) el.href = opts.href;
        if (opts.target) el.target = opts.target;
        if (opts.rel) el.rel = opts.rel;
        if (opts.onclick) el.onclick = opts.onclick;
    }
    return el;
}

function _rbEmpty(container, msg, colorOverride) {
    _rbClear(container);
    var wrap = _rbMakeEl('div', {cls: 'dp-empty', style: 'padding:40px;'});
    var body = _rbMakeEl('div', {
        cls: 'dp-empty-desc',
        text: msg,
        style: colorOverride ? 'color:' + colorOverride + ';' : ''
    });
    wrap.appendChild(body);
    container.appendChild(wrap);
}

function _rbFmtDate(iso) {
    if (!iso) return '—';
    try {
        var d = new Date(iso);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
    } catch (e) { return iso; }
}

function _rbShowToast(kind, msg) {
    if (typeof showToast === 'function') {
        showToast(kind, msg);
    } else {
        console.log('[' + kind + '] ' + msg);
    }
}

/* ── Tab dispatcher — called from switchTab() in repair_bay.html ── */
function rbOnTabSwitch(tabId) {
    // Stop the Reviews poll timer whenever we leave that tab so we're
    // not burning GitHub API quota in the background.
    if (tabId !== 'reviews') {
        _stopReviewsPoll();
    }
    switch (tabId) {
        case 'reviews':   loadReviews(); break;
        case 'proposals': loadRepairs(); break;
        case 'scan':      loadDiagnose(); break;
        case 'sandbox':   loadTestBay(); break;
        case 'deploy':    loadShip(); break;
        case 'qa':
            if (typeof loadQaTab === 'function') loadQaTab();
            break;
    }
}

function _startReviewsPoll() {
    if (_reviewsPollTimer) return;  // already running
    _reviewsPollTimer = setInterval(function() {
        // Only poll if the Reviews tab is still the active surface —
        // the rbOnTabSwitch dispatcher clears the timer on leave but
        // double-check in case the user navigated via the URL hash.
        var activePanel = document.getElementById('tab-reviews');
        if (!activePanel || !activePanel.classList.contains('active')) {
            _stopReviewsPoll();
            return;
        }
        loadReviews(true);  // silent refresh
    }, REVIEWS_POLL_INTERVAL_MS);
}

function _stopReviewsPoll() {
    if (_reviewsPollTimer) {
        clearInterval(_reviewsPollTimer);
        _reviewsPollTimer = null;
    }
}

/* ── Reviews tab — GitHub PR list ─────────────────────────────── */
var _REVIEWS_CACHE_KEY = 'rb_reviews_cache_v1';

function loadReviews(silent) {
    _reviewsLoaded = true;
    var container = document.getElementById('reviewsList');
    var countEl = document.getElementById('reviewsCount');
    var state = (document.getElementById('reviewsStateFilter') || {}).value || 'open';
    if (!container) return;

    // Render cached data instantly so the user sees content on arrival.
    // The live fetch below will silently update it.
    var cached = null;
    try { cached = JSON.parse(sessionStorage.getItem(_REVIEWS_CACHE_KEY + '_' + state)); } catch(e) {}
    if (cached && cached.prs && cached.prs.length && !silent) {
        _renderReviewCards(container, countEl, cached.prs, true /* from cache */);
    } else if (!silent && !cached) {
        _rbEmpty(container, 'Loading PRs…');
    }

    // Start the poll timer on first load (not on silent refreshes to
    // avoid stacking timers) when this tab is actually active.
    if (!silent) {
        _startReviewsPoll();
    }

    _rbFetchJson(RB_API + '/forge/prs?state=' + encodeURIComponent(state))
        .then(function(data) {
            // If API returned an error, keep whatever is already showing (cache or blank)
            if (!data.success && data.error) return;
            var prs = data.prs || data.pull_requests || [];
            if (!prs.length) {
                // Only show empty state if nothing is currently cached/displayed
                var hasCards = container && container.querySelector('.dp-proposal-card');
                if (!hasCards) {
                    if (countEl) countEl.textContent = '0 PRs';
                    _rbEmpty(container, 'No ' + state + ' PRs found.');
                }
                return;
            }
            // Save to session cache so next arrival renders instantly
            try {
                var cacheKey = _REVIEWS_CACHE_KEY + '_' + state;
                sessionStorage.setItem(cacheKey, JSON.stringify({prs: prs}));
            } catch(e) {}
            _renderReviewCards(container, countEl, prs, false);
        })
        .catch(function(e) {
            // Don't clear the container if cards are already showing from cache
            var hasCards = container && container.querySelector('.dp-proposal-card');
            if (!hasCards) {
                _rbEmpty(container, 'Failed to load PRs: ' + e.message, '#ef4444');
            }
        });
}

function _renderReviewCards(container, countEl, prs, fromCache) {
    if (!prs || !prs.length) {
        _rbEmpty(container, 'No PRs found.');
        return;
    }
    var mergeable = [];
    var others = [];
    prs.forEach(function(pr) {
        if (pr.mergeable === 'MERGEABLE') mergeable.push(pr);
        else others.push(pr);
    });
    mergeable.sort(function(a, b) {
        var ta = a.updated_at || a.created_at || '';
        var tb = b.updated_at || b.created_at || '';
        return ta < tb ? -1 : ta > tb ? 1 : 0;
    });
    mergeable.forEach(function(pr, i) { pr._mergeRank = i + 1; });
    var ordered = mergeable.concat(others);

    _reviewsLastLoadedAt = fromCache ? _reviewsLastLoadedAt : new Date();
    if (countEl) {
        var ts = fromCache ? 'cached' : (_reviewsLastLoadedAt || new Date()).toLocaleTimeString([], {
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
        countEl.textContent =
            prs.length + ' PR' + (prs.length !== 1 ? 's' : '') +
            ' · ' + mergeable.length + ' ready to merge' +
            ' · auto-refresh ' + (REVIEWS_POLL_INTERVAL_MS / 1000) + 's · last ' + ts;
    }

    _rbClear(container);
    ordered.forEach(function(pr) {
        container.appendChild(_buildReviewCard(pr));
    });
    if (typeof lucide !== 'undefined' && lucide.createIcons) {
        try { lucide.createIcons(); } catch (e) { /* ok */ }
    }
}

function _buildReviewCard(pr) {
    var card = _rbMakeEl('div', {
        cls: 'dp-proposal-card',
        style: 'padding:14px 16px; margin-bottom:10px; border-left:3px solid #00d4ff; background:rgba(0,212,255,0.04); border-radius:4px; overflow:hidden; flex-direction:column; align-items:stretch;'
    });

    /* Header row: [rank] + number + title + external link */
    var header = _rbMakeEl('div', {style: 'display:flex; align-items:flex-start; gap:10px; margin-bottom:8px;'});

    // Merge order rank — purple pill, only on MERGEABLE PRs
    if (pr._mergeRank) {
        var rankPill = _rbMakeEl('span', {
            style:
                'display:inline-flex; align-items:center; justify-content:center; ' +
                'min-width:26px; height:22px; padding:0 7px; margin-top:1px; ' +
                'background:#8b5cf6; color:#0a0e1a; font-weight:800; ' +
                'font-family:"IBM Plex Mono",monospace; font-size:0.72rem; ' +
                'border-radius:4px; flex-shrink:0;',
            text: '#' + pr._mergeRank
        });
        rankPill.title = 'Merge order: ' + pr._mergeRank +
            ' (oldest ready-to-merge first). Conflicting PRs are not ranked.';
        header.appendChild(rankPill);
    }

    var numBadge = _rbMakeEl('span', {
        style: 'color:#00d4ff; font-family:"IBM Plex Mono",monospace; font-size:0.8rem; padding-top:2px;',
        text: '#' + (pr.number || '?')
    });
    header.appendChild(numBadge);

    var titleWrap = _rbMakeEl('div', {style: 'flex:1 1 auto; min-width:0;'});
    var title = _rbMakeEl('div', {
        style: 'color:#e2e8f0; font-weight:600; font-size:0.9rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;',
        text: pr.title || '(untitled)'
    });
    titleWrap.appendChild(title);

    var parts = [];
    if (pr.user) parts.push('by ' + pr.user);
    var ref = pr.head_ref || pr.head || '';
    if (ref) parts.push(ref.length > 32 ? ref.slice(0, 32) + '…' : ref);
    if (pr.updated_at) parts.push('updated ' + _rbFmtDate(pr.updated_at));
    var sub = _rbMakeEl('div', {
        style: 'color:#94a3b8; font-size:0.72rem; margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;',
        text: parts.join(' · ')
    });
    titleWrap.appendChild(sub);
    header.appendChild(titleWrap);

    var ghLink = _rbMakeEl('a', {
        href: pr.html_url || pr.url || '#',
        target: '_blank',
        rel: 'noopener',
        style: 'color:#00d4ff; font-size:0.75rem; text-decoration:none; flex-shrink:0;',
        text: 'GitHub ↗'
    });
    header.appendChild(ghLink);
    card.appendChild(header);

    /* Status badge row: mergeable + review decision + checks */
    var badges = _rbMakeEl('div', {style: 'display:flex; gap:6px; flex-wrap:wrap; margin-top:8px;'});

    badges.appendChild(_statusPill('merge', pr.mergeable, {
        MERGEABLE: ['#22c55e', 'mergeable'],
        CONFLICTING: ['#ef4444', 'conflict'],
        UNKNOWN: ['#64748b', 'checking']
    }));

    badges.appendChild(_statusPill('review', pr.review_decision || pr.reviewDecision, {
        APPROVED: ['#22c55e', 'approved'],
        CHANGES_REQUESTED: ['#ef4444', 'changes requested'],
        REVIEW_REQUIRED: ['#fbbf24', 'review required'],
        NONE: ['#64748b', 'no reviews']
    }));

    var checks = pr.checks || pr.check_runs || {};
    if (checks.lint !== undefined) badges.appendChild(_checkPill('lint', checks.lint));
    if (checks.test !== undefined) badges.appendChild(_checkPill('test', checks.test));
    if (checks.docker_build !== undefined || checks.docker !== undefined) {
        badges.appendChild(_checkPill('docker', checks.docker_build || checks.docker));
    }
    if (checks.coderabbit !== undefined || pr.coderabbit_status) {
        badges.appendChild(_checkPill('coderabbit', checks.coderabbit || pr.coderabbit_status));
    }

    card.appendChild(badges);

    /* Optional CodeRabbit summary */
    if (pr.coderabbit_summary) {
        var cr = _rbMakeEl('div', {
            style: 'margin-top:10px; padding:8px 10px; background:rgba(139,92,246,0.06); border-left:2px solid #8b5cf6; font-size:0.78rem; color:#cbd5e1;',
            text: '[CodeRabbit] ' + String(pr.coderabbit_summary).slice(0, 300)
        });
        card.appendChild(cr);
    }

    /* Action row */
    var actions = _rbMakeEl('div', {style: 'display:flex; gap:8px; margin-top:10px; justify-content:flex-end; flex-wrap:wrap; align-items:center;'});

    var viewBtn = _rbMakeEl('a', {
        href: pr.html_url || '#',
        target: '_blank',
        rel: 'noopener',
        cls: 'dp-btn',
        style: 'padding:6px 12px; font-size:0.78rem; background:rgba(0,212,255,0.15); border:1px solid #00d4ff; color:#00d4ff; text-decoration:none; border-radius:3px; white-space:nowrap;',
        text: 'Review ↗'
    });
    actions.appendChild(viewBtn);

    // #5853: render the SERVER's merge_state, never GitHub's fields.
    // The old condition was `pr.mergeable === 'MERGEABLE' && pr.review_decision !==
    // 'CHANGES_REQUESTED'`. Both are GitHub's own — and F.O.R.G.E. posts NO GitHub
    // review (its verdict lives in pr_reviews.ai_summary), so review_decision is
    // ~always null and the test collapsed to "mergeable => enabled green button".
    // A REQUEST CHANGES, a coverage demotion and a never-reviewed PR all rendered
    // identically, and you only learned the truth from a 422 after clicking.
    // The verdict rule stays SERVER-side (tests/test_merge_state_ui.py pins that);
    // this reads a decision it did not make.
    var ms = pr.merge_state || {};
    var msOk = !!ms.mergeable;
    var ghOk = pr.mergeable === 'MERGEABLE';
    // MERGE ORDER — server-computed (merge_order_service); this only renders it.
    var mo = pr.merge_order || null;
    var orderBlocked = !!(mo && mo.blocked);
    if (mo && (mo.label || mo.unavailable)) {
        var moCol = orderBlocked ? '#f97316' : (mo.unavailable ? '#64748b' : ((mo.after || []).length ? '#f59e0b' : '#94a3b8'));
        var orderBadge = _rbMakeEl('span', {
            style: 'padding:6px 10px; font-size:0.72rem; font-family:"IBM Plex Mono",monospace; color:' + moCol + '; border:1px solid ' + moCol + '55; border-radius:3px; white-space:nowrap;',
            text: mo.unavailable ? 'order n/a' : mo.label
        });
        orderBadge.title = mo.reason || '';
        actions.appendChild(orderBadge);
    }

    if (pr.mergeable === 'CONFLICTING') {
        // Checked FIRST: a conflict blocks the merge whatever the verdict says.
        var conflictBadge = _rbMakeEl('span', {
            style: 'padding:6px 12px; font-size:0.75rem; background:rgba(239,68,68,0.15); color:#ef4444; border:1px solid #ef4444; border-radius:3px;',
            text: 'Needs rebase'
        });
        actions.appendChild(conflictBadge);
    } else if (orderBlocked) {
        // A declared dependency that is still open: the server refuses this merge for
        // every actor (github_service._dependency_refusal); say so before the click.
        var orderBtn = _rbMakeEl('button', {
            cls: 'dp-btn',
            style: 'padding:6px 14px; font-size:0.8rem; background:rgba(249,115,22,0.12); color:#f97316; border:1px solid #f9731655; border-radius:3px; cursor:not-allowed; white-space:nowrap;',
            text: 'Blocked \u2014 after #' + (mo.declared_after || []).join(', #')
        });
        orderBtn.disabled = true;
        orderBtn.title = mo.reason || '';
        actions.appendChild(orderBtn);
    } else if (msOk && ghOk) {
        // coverage_only is mergeable ONLY with an explicit ack. _doMergePr already
        // handles that round-trip (422 -> _rbCoverageAckPrompt naming the files), so
        // the amber colour is a HONEST PREVIEW of the confirm, not a second gate.
        var coverage = ms.state === 'coverage_only';
        var nDropped = (ms.dropped_files || []).length;
        var mergeBtn = _rbMakeEl('button', {
            cls: 'dp-btn',
            style: 'padding:6px 14px; font-size:0.8rem; background:' +
                (coverage ? '#f59e0b' : '#22c55e') +
                '; color:#0a0e1a; border:none; border-radius:3px; cursor:pointer; font-weight:700; white-space:nowrap;',
            text: coverage ? ('Merge (' + nDropped + ' unread)') : 'Merge ✓',
            onclick: function() { _mergePr(pr.number, mergeBtn, pr.repo); }
        });
        if (ms.hint) mergeBtn.title = ms.hint;
        actions.appendChild(mergeBtn);
    } else {
        // Disabled, and it SAYS WHY. Two distinct reasons, never conflated:
        // the verdict does not authorize it, or GitHub has not called it mergeable.
        var blockedBtn = _rbMakeEl('button', {
            cls: 'dp-btn',
            style: 'padding:6px 14px; font-size:0.8rem; background:rgba(100,116,139,0.15); color:#64748b; border:1px solid #64748b55; border-radius:3px; cursor:not-allowed; font-weight:700; white-space:nowrap;',
            text: msOk
                ? ('GitHub: ' + String(pr.mergeable || 'unknown').toLowerCase())
                : (ms.label || 'WAITING FOR REVIEW')
        });
        blockedBtn.disabled = true;
        blockedBtn.title = msOk
            ? 'GitHub has not reported this PR as mergeable yet.'
            : (ms.hint || 'No stored verdict yet — nothing has reviewed this PR.');
        actions.appendChild(blockedBtn);
    }

    card.appendChild(actions);
    return card;
}

function _statusPill(label, value, colorMap) {
    var mapped = (colorMap && colorMap[value]) || ['#64748b', String(value || '—').toLowerCase()];
    return _rbMakeEl('span', {
        style:
            'display:inline-flex; align-items:center; gap:4px; padding:2px 8px; ' +
            'border-radius:10px; font-size:0.68rem; font-family:"IBM Plex Mono",monospace; ' +
            'white-space:nowrap; ' +
            'background:' + mapped[0] + '22; color:' + mapped[0] + '; border:1px solid ' + mapped[0] + '55;',
        text: label + ': ' + mapped[1]
    });
}

function _checkPill(label, status) {
    var color = '#64748b';
    var txt = String(status || '—').toLowerCase();
    if (txt === 'success' || txt === 'pass' || txt === 'passed') color = '#22c55e';
    else if (txt === 'failure' || txt === 'fail' || txt === 'failed') color = '#ef4444';
    else if (txt === 'pending' || txt === 'in_progress' || txt === 'queued') color = '#fbbf24';
    return _rbMakeEl('span', {
        style:
            'display:inline-flex; align-items:center; gap:4px; padding:2px 8px; ' +
            'border-radius:10px; font-size:0.68rem; font-family:"IBM Plex Mono",monospace; ' +
            'white-space:nowrap; ' +
            'background:' + color + '22; color:' + color + '; border:1px solid ' + color + '55;',
        text: label + ': ' + txt
    });
}

/* LCARS confirmation modal — returns a Promise<boolean>.
 * Replaces native window.confirm() for Repair Bay action prompts.
 * Usage: _rbLcarsConfirm({title, message, confirmText, cancelText, accent}).then(ok => {...})
 */
function _rbLcarsConfirm(opts) {
    opts = opts || {};
    var title = opts.title || 'Confirm';
    var message = opts.message || 'Are you sure?';
    var confirmText = opts.confirmText || 'Confirm';
    var cancelText = opts.cancelText === null ? null : (opts.cancelText || 'Cancel');
    var accent = opts.accent || '#22d3ee';
    var accentRgb = opts.accentRgb || '34,211,238';

    return new Promise(function(resolve) {
        var overlay = _rbMakeEl('div', {
            cls: 'bm-overlay active',
            style: '--bm-accent:' + accent + '; --bm-accent-rgb:' + accentRgb + ';'
        });
        function close(result) {
            document.removeEventListener('keydown', onKey);
            overlay.remove();
            resolve(result);
        }
        function onKey(e) {
            if (e.key === 'Escape') close(false);
            else if (e.key === 'Enter') close(true);
        }
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) close(false);
        });

        var shell = _rbMakeEl('div', {cls: 'bm-shell', style: 'max-width:480px;'});

        var frame = _rbMakeEl('div', {cls: 'bm-frame'});
        ['bm-frame-elbow-top', 'bm-frame-seg', 'bm-frame-seg dim', 'bm-frame-light on',
         'bm-frame-light amber', 'bm-frame-seg purple', 'bm-frame-fill',
         'bm-frame-elbow-bottom'].forEach(function(cls) {
            frame.appendChild(_rbMakeEl('div', {cls: cls}));
        });

        var content = _rbMakeEl('div', {cls: 'bm-content'});

        var header = _rbMakeEl('div', {cls: 'bm-header'});
        header.appendChild(_rbMakeEl('span', {cls: 'bm-header-title', text: title}));
        var headerStrip = _rbMakeEl('div', {cls: 'bm-header-strip'});
        ['w1', 'w2', 'w3'].forEach(function(w) {
            headerStrip.appendChild(_rbMakeEl('div', {cls: 'bm-header-pip ' + w}));
        });
        headerStrip.appendChild(_rbMakeEl('button', {
            cls: 'bm-close', text: '\u00D7',
            onclick: function() { close(false); }
        }));
        header.appendChild(headerStrip);

        var body = _rbMakeEl('div', {
            cls: 'bm-body',
            style: 'padding:22px 24px; color:#e2e8f0; font-size:0.9rem; line-height:1.55; white-space:pre-line;'
        });
        body.appendChild(_rbMakeEl('div', {text: message}));

        var footer = _rbMakeEl('div', {
            cls: 'bm-footer',
            style: 'display:flex; justify-content:flex-end; gap:10px; padding:14px 24px; border-top:1px solid rgba(' + accentRgb + ',0.2);'
        });
        if (cancelText !== null) {
            footer.appendChild(_rbMakeEl('button', {
                text: cancelText,
                style: 'padding:8px 18px; background:rgba(100,116,139,0.15); border:1px solid #64748b; color:#cbd5e1; ' +
                       'font-family:"IBM Plex Mono",monospace; font-size:0.78rem; letter-spacing:0.08em; ' +
                       'text-transform:uppercase; cursor:pointer; border-radius:2px;',
                onclick: function() { close(false); }
            }));
        }
        footer.appendChild(_rbMakeEl('button', {
            text: confirmText,
            style: 'padding:8px 18px; background:' + accent + '; border:1px solid ' + accent + '; color:#0b1120; ' +
                   'font-family:"IBM Plex Mono",monospace; font-size:0.78rem; letter-spacing:0.08em; ' +
                   'text-transform:uppercase; font-weight:600; cursor:pointer; border-radius:2px;',
            onclick: function() { close(true); }
        }));

        content.appendChild(header);
        content.appendChild(body);
        content.appendChild(footer);
        shell.appendChild(frame);
        shell.appendChild(content);
        overlay.appendChild(shell);
        document.body.appendChild(overlay);
        document.addEventListener('keydown', onKey);
    });
}

/* LCARS prompt modal — free-text input. Returns a Promise<string|null>.
 * Sibling of _rbLcarsConfirm above: same shell/frame/header/footer build, plus a
 * textarea. Resolves with the trimmed text, or null when cancelled or left blank.
 *
 * Used where an action must be ATTRIBUTED in writing — closing a PR posts the
 * operator's reason onto the PR itself, so the server requires it and this modal
 * must not be able to submit an empty one. That is why the confirm button starts
 * disabled and only enables on non-whitespace input, rather than validating on
 * click and showing an error afterwards.
 */
function _rbLcarsPrompt(opts) {
    opts = opts || {};
    var title = opts.title || 'Input';
    var message = opts.message || '';
    var placeholder = opts.placeholder || '';
    var confirmText = opts.confirmText || 'Confirm';
    var accent = opts.accent || '#22d3ee';
    var accentRgb = opts.accentRgb || '34,211,238';

    return new Promise(function(resolve) {
        var overlay = _rbMakeEl('div', {
            cls: 'bm-overlay active',
            style: '--bm-accent:' + accent + '; --bm-accent-rgb:' + accentRgb + ';'
        });
        function close(result) {
            document.removeEventListener('keydown', onKey);
            overlay.remove();
            resolve(result);
        }
        function onKey(e) {
            if (e.key === 'Escape') { close(null); return; }
            // Enter submits, but only through the confirm button so the disabled
            // state stays honest — never close(true) with an empty value.
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
            }
        }
        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) close(null);
        });

        function submit() {
            var val = (input.value || '').trim();
            if (!val) return;          // empty reason is not a valid answer
            close(val);
        }

        var shell = _rbMakeEl('div', {cls: 'bm-shell', style: 'max-width:480px;'});

        var frame = _rbMakeEl('div', {cls: 'bm-frame'});
        ['bm-frame-elbow-top', 'bm-frame-seg', 'bm-frame-seg dim', 'bm-frame-light on',
         'bm-frame-light amber', 'bm-frame-seg purple', 'bm-frame-fill',
         'bm-frame-elbow-bottom'].forEach(function(cls) {
            frame.appendChild(_rbMakeEl('div', {cls: cls}));
        });

        var content = _rbMakeEl('div', {cls: 'bm-content'});

        var header = _rbMakeEl('div', {cls: 'bm-header'});
        header.appendChild(_rbMakeEl('span', {cls: 'bm-header-title', text: title}));
        var headerStrip = _rbMakeEl('div', {cls: 'bm-header-strip'});
        ['w1', 'w2', 'w3'].forEach(function(w) {
            headerStrip.appendChild(_rbMakeEl('div', {cls: 'bm-header-pip ' + w}));
        });
        headerStrip.appendChild(_rbMakeEl('button', {
            cls: 'bm-close', text: '\u00D7',
            onclick: function() { close(null); }
        }));
        header.appendChild(headerStrip);

        var body = _rbMakeEl('div', {
            cls: 'bm-body',
            style: 'padding:22px 24px; color:#e2e8f0; font-size:0.9rem; line-height:1.55;'
        });
        if (message) {
            body.appendChild(_rbMakeEl('div', {style: 'white-space:pre-line;', text: message}));
        }
        var input = document.createElement('textarea');
        input.rows = 4;
        input.placeholder = placeholder;
        input.style.cssText = 'width:100%; margin-top:14px; box-sizing:border-box; padding:10px 12px; ' +
            'background:rgba(15,23,42,0.9); border:1px solid rgba(' + accentRgb + ',0.35); ' +
            'border-radius:3px; color:#e2e8f0; font-family:"IBM Plex Mono",monospace; font-size:0.8rem; ' +
            'line-height:1.5; resize:vertical;';
        body.appendChild(input);

        var hint = _rbMakeEl('div', {
            style: 'margin-top:8px; font-size:0.68rem; color:rgba(148,163,184,0.85);'
        });
        hint.textContent = 'Required — it is posted on the PR as the record of why.';
        body.appendChild(hint);

        var confirmBtn = _rbMakeEl('button', {
            text: confirmText,
            style: 'padding:8px 18px; background:' + accent + '; border:1px solid ' + accent + '; color:#0b1120; ' +
                   'font-family:"IBM Plex Mono",monospace; font-size:0.78rem; letter-spacing:0.08em; ' +
                   'text-transform:uppercase; font-weight:600; cursor:not-allowed; opacity:0.45; border-radius:2px;',
            onclick: submit
        });
        function syncEnabled() {
            var has = !!(input.value || '').trim();
            confirmBtn.disabled = !has;
            confirmBtn.style.opacity = has ? '1' : '0.45';
            confirmBtn.style.cursor = has ? 'pointer' : 'not-allowed';
        }
        input.addEventListener('input', syncEnabled);
        input.addEventListener('keydown', function(e) {
            // Plain Enter is a newline inside the reason; Cmd/Ctrl+Enter submits.
            e.stopPropagation();
        });
        setTimeout(function() { input.focus(); syncEnabled(); }, 0);

        var footer = _rbMakeEl('div', {
            cls: 'bm-footer',
            style: 'display:flex; justify-content:flex-end; gap:10px; padding:14px 24px; border-top:1px solid rgba(' + accentRgb + ',0.2);'
        });
        footer.appendChild(_rbMakeEl('button', {
            text: 'Cancel',
            style: 'padding:8px 18px; background:rgba(100,116,139,0.15); border:1px solid #64748b; color:#cbd5e1; ' +
                   'font-family:"IBM Plex Mono",monospace; font-size:0.78rem; letter-spacing:0.08em; ' +
                   'text-transform:uppercase; cursor:pointer; border-radius:2px;',
            onclick: function() { close(null); }
        }));
        footer.appendChild(confirmBtn);

        content.appendChild(header);
        content.appendChild(body);
        content.appendChild(footer);
        shell.appendChild(frame);
        shell.appendChild(content);
        overlay.appendChild(shell);
        document.body.appendChild(overlay);
        document.addEventListener('keydown', onKey);
    });
}

/* Derive the merge button's label/colour/enabled state from a stamped merge_state.
 *
 * ONE source of truth, because #5853's own comment states the intent — "stamp the
 * SAME merge_state that list_reviews() uses so both surfaces agree" — and the
 * server half of that landed while only the Reviews-tab renderer was updated. The
 * F.O.R.G.E. stats panel kept rendering an unconditional green Merge on PRs the
 * server would refuse. Same payload, two renderers, two answers.
 *
 * Parameters:
 *   ms            — the server-stamped merge_state object (may be null/absent)
 *   orderBlocked  — bool from the row's merge_order
 *   droppedCount  — count for the "n unread" coverage suffix
 *
 * Returns {text, col, bg, br, can, title}. When `ms` is absent the caller gets the
 * legacy permissive result, because an unstamped row means the stamp FAILED
 * (best-effort by design) and a stale payload must not silently disable every button
 * on the panel — the server is still the authority either way.
 *
 * ⚠️ This predicts the F.O.R.G.E. verdict gate only. deploy_via_merge additionally
 * applies the unattended AUTHORITY gate (tier ceiling + path allowlist,
 * _automerge_governance_ok), so a button this renders as enabled can still be
 * refused. It is an honest preview, never a second gate — same contract as
 * merge_state.hint and the merge-order badge.
 */
function _prMergeAffordance(ms, orderBlocked, droppedCount, orderLabel) {
    var d = droppedCount || 0;
    var o = {
        text: 'Merge', col: '#4ade80', bg: 'rgba(34,197,94,0.15)', br: 'rgba(34,197,94,0.4)',
        can: true, title: ''
    };
    // Dependency order is checked FIRST, and before any merge_state fallback.
    // merge_state and merge_order are stamped by two INDEPENDENT best-effort
    // steps server-side, each with its own try/except — so a PR can arrive with
    // no merge_state (the stamp raised) while still carrying a live
    // merge_order.blocked. Returning the legacy green Merge there would advertise
    // an enabled button for a dependency the server refuses to merge. The Reviews
    // tab got this right by applying the block unconditionally; keep that order.
    if (orderBlocked) {
        o.can = false;
        o.text = orderLabel || 'Blocked';
        o.col = '#f97316';
        o.bg = 'rgba(249,115,22,0.10)';
        o.br = 'rgba(249,115,22,0.35)';
        return o;
    }
    if (!ms) return o;                                  // unstamped/stale => legacy
    o.can = !!ms.mergeable;
    switch (ms.state) {
        case 'coverage_only':
            o.text = 'Merge (' + d + ' unread)'; o.col = '#fbbf24';
            o.bg = 'rgba(251,191,36,0.15)'; o.br = 'rgba(251,191,36,0.45)'; break;
        case 'changes_requested':
            o.text = 'Blocked — re-review'; o.col = '#ef4444';
            o.bg = 'rgba(239,68,68,0.10)'; o.br = 'rgba(239,68,68,0.35)'; break;
        // NEEDS REVIEW is the model declining to pick a side, not a code objection.
        // It shares awaiting_review's non-mergeable posture but keeps its own label so
        // a reviewer that found nothing is never reported as "Changes requested"
        // (PR #3572: complete read, correct head, "No issues found.").
        case 'needs_review':
            o.text = 'Awaiting human read'; o.col = '#fbbf24';
            o.bg = 'rgba(251,191,36,0.10)'; o.br = 'rgba(251,191,36,0.35)'; break;
        case 'awaiting_review':
            o.text = 'Waiting for review'; o.col = '#94a3b8';
            o.bg = 'rgba(148,163,184,0.10)'; o.br = 'rgba(148,163,184,0.30)'; break;
        case 'reviewing':
            o.text = 'Reviewing…'; o.col = '#67e8f9';
            o.bg = 'rgba(34,211,238,0.10)'; o.br = 'rgba(34,211,238,0.30)'; break;
    }
    o.title = ms.hint || '';
    return o;
}

/* Style + bind a merge button from an affordance produced above.
 * `onClick` is only wired when the button is enabled, so a disabled button cannot
 * fire — the Reviews tab used to set onclick unconditionally and rely on the server.
 */
function _prStyleMergeBtn(btn, aff) {
    btn.style.cssText = 'font-size:0.6rem;padding:2px 8px;background:' + aff.bg +
        ';border:1px solid ' + aff.br + ';color:' + aff.col + ';border-radius:4px;cursor:' +
        (aff.can ? 'pointer' : 'not-allowed') + ';' + (aff.can ? '' : 'opacity:0.6;');
    btn.textContent = aff.text;
    if (aff.title) btn.title = aff.title;
    if (!aff.can) btn.disabled = true;
    return btn;
}

/* Close a PR from Repair Bay with a WRITTEN reason.
 *
 * The reason is not decoration: github_service.close_pr refuses without one and posts
 * it onto the PR before closing, so the operator's justification is attributed and
 * survives the close. A confirm/alert pair cannot collect that, hence _rbLcarsPrompt.
 *
 * Human-only by contract — this control is admin-gated server-side and there is
 * deliberately no unattended caller.
 */
function forgeClosePR(prNumber, repo) {
    _rbLcarsPrompt({
        title: 'CLOSE PR #' + prNumber,
        message: 'Close PR #' + prNumber + (repo ? ' (' + repo + ')' : '') +
                 ' WITHOUT merging.\n\nThe branch is left in place — this is not a revert. ' +
                 'Anyone can reopen it.',
        placeholder: 'e.g. superseded by #1234 / abandoned lane branch / duplicate of #1234',
        confirmText: 'Close PR',
        accent: '#f97316',
        accentRgb: '249,115,22'
    }).then(function(reason) {
        if (!reason) return;                            // cancelled or blank
        fetch('/tools/repair-bay/api/forge/pr/' + prNumber + '/close',
              {method: 'POST', headers: {'Content-Type': 'application/json'},
               body: JSON.stringify({reason: reason, repo: repo || null})})
            .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, d: d}; }); })
            .then(function(res) {
                if (res.ok && res.d.success) {
                    if (typeof loadForgeStats === 'function') loadForgeStats();
                    if (typeof loadPRReviews === 'function') {
                        loadPRReviews(typeof _prStateFilter === 'string' ? _prStateFilter : 'open');
                    }
                    _rbLcarsAlert({
                        title: 'PR CLOSED',
                        message: 'PR #' + prNumber + ' closed.\n\nReason recorded on the PR:\n"' +
                                 res.d.reason + '"',
                        okText: 'Done', accent: '#f97316', accentRgb: '249,115,22'
                    });
                } else {
                    _rbLcarsAlert({
                        title: 'CLOSE REFUSED',
                        message: 'PR #' + prNumber + ' was not closed.\n\n' +
                                 (res.d.error || 'Unknown error'),
                        okText: 'OK', accent: '#ef4444', accentRgb: '239,68,68'
                    });
                }
            })
            .catch(function(e) {
                _rbLcarsAlert({
                    title: 'CLOSE FAILED',
                    message: 'Could not reach Repair Bay: ' + e,
                    okText: 'OK', accent: '#ef4444', accentRgb: '239,68,68'
                });
            });
    });
}

/* LCARS info modal — single "OK" button, no Cancel. Returns a Promise<void>.
 * Replaces native window.alert() for Repair Bay notices.
 * Usage: _rbLcarsAlert({title, message, okText, accent}).then(() => {...})
 */
function _rbLcarsAlert(opts) {
    opts = opts || {};
    return _rbLcarsConfirm({
        title: opts.title || 'Notice',
        message: opts.message || '',
        confirmText: opts.okText || 'OK',
        cancelText: null,
        accent: opts.accent || '#22d3ee',
        accentRgb: opts.accentRgb || '34,211,238'
    });
}

function _mergePr(prNumber, btn, repo) {
    // Name the repo in the confirm itself. A PR number is not an identity:
    // #61 exists in archie-code, archie-platform AND kytran-business-suite, so
    // "merge PR #61" is ambiguous until the repo is on screen.
    var where = repo ? repo.replace('KytranKatarn/', '') : 'archie-platform';
    _rbLcarsConfirm({
        title: 'APPROVE & MERGE PR #' + prNumber,
        message: 'This will squash-merge PR #' + prNumber + ' in ' + where +
            ' via the F.O.R.G.E. pipeline and deploy to main.\n\nProceed?',
        confirmText: 'Merge',
        cancelText: 'Cancel',
        accent: '#22c55e',
        accentRgb: '34,197,94'
    }).then(function(ok) {
        if (!ok) return;
        _doMergePr(prNumber, btn, false, repo);
    });
}

function _rbCoverageAckPrompt(prNumber, files) {
    var list = (files || []);
    var shown = list.length
        ? '\n\n' + list.map(function (f) { return '  \u2022 ' + f; }).join('\n')
        : '\n\n  (the review did not name them)';
    return 'PR #' + prNumber + ' \u2014 COVERAGE ONLY\n\n'
        + 'F.O.R.G.E. APPROVED everything it read, but ' + list.length
        + ' file(s) were truncated away before it saw them:' + shown
        + '\n\nMerging now means YOU have read those files. '
        + 'Cancel to re-review instead.';
}

function _doMergePr(prNumber, btn, coverageAck, repo) {
    btn.disabled = true;
    btn.textContent = 'Merging…';
    // `repo` MUST travel with the click (2026-09-11 cross-repo fix, client half).
    // Both /forge/prs/<n>/merge and /forge/pr-reviews/<n>/merge resolve the row by
    // (pr_number, repo); omit it and they fall back to archie-platform, which for
    // KBS #61 meant asking GitHub to merge archie-platform #61 — a PR merged back
    // in April, hence the bare 404. The routes documented the hazard; this caller
    // never sent the field.
    _rbFetchJson(RB_API + '/forge/prs/' + prNumber + '/merge', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: 'squash', coverage_ack: !!coverageAck, repo: repo || null})
    })
    .then(function(data) {
        if (data.success) {
            btn.textContent = 'Merged ✓';
            btn.style.background = '#16a34a';
            _rbShowToast('success', 'PR #' + prNumber + ' merged');
            setTimeout(loadReviews, 1500);
        } else if (data.coverage_only && !coverageAck) {
            // The reviewer APPROVED what it read; only truncated files demoted the verdict.
            // That is dischargeable by a human who reads them — but the confirm must NAME
            // the files, or the click is uninformed and the gate is theatre.
            btn.disabled = false;
            btn.textContent = 'Merge';
            if (confirm(_rbCoverageAckPrompt(prNumber, data.dropped_files))) {
                _doMergePr(prNumber, btn, true, repo);   // one retry only, guarded by coverageAck
            }
        } else {
            btn.disabled = false;
            btn.textContent = 'Merge failed';
            btn.style.background = '#ef4444';
            _rbShowToast('error', data.error || 'Merge failed');
        }
    })
    .catch(function(e) {
        btn.disabled = false;
        btn.textContent = 'Error';
        btn.style.background = '#ef4444';
        _rbShowToast('error', 'Merge error: ' + e.message);
    });
}

/* ── Repairs tab — improvement_proposals + compliance action modal ───
 * Task 4 (Project #242): the inline template script owns the list render
 * (loadProposals + renderProposals) — this file nudges it on tab switch
 * and provides the compliance action modal that cards open when a
 * compliance_fix proposal's "Review ▶" button is clicked.
 */
function loadRepairs() {
    if (typeof loadProposals === 'function') {
        try { loadProposals(); } catch (e) { console.warn('loadProposals error:', e); }
    }
    _repairsLoaded = true;
}

var SAFE_FIX_TYPES_JS = ['sysctl', 'file_line', 'service'];

async function openRepairsComplianceModal(proposalId) {
    var existing = document.getElementById('rb-compliance-modal');
    if (existing) existing.remove();

    var overlay = _rbMakeEl('div', {
        cls: 'bm-overlay active',
        style: '--bm-accent:#8b5cf6; --bm-accent-rgb:139,92,246;'
    });
    overlay.id = 'rb-compliance-modal';
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) overlay.remove();
    });

    var shell = _rbMakeEl('div', {cls: 'bm-shell', style: 'max-width:620px; max-height:90vh;'});

    var frame = _rbMakeEl('div', {cls: 'bm-frame'});
    ['bm-frame-elbow-top', 'bm-frame-seg', 'bm-frame-seg dim', 'bm-frame-light on',
     'bm-frame-light amber', 'bm-frame-seg purple', 'bm-frame-fill', 'bm-frame-elbow-bottom'].forEach(function(cls) {
        frame.appendChild(_rbMakeEl('div', {cls: cls}));
    });

    var content = _rbMakeEl('div', {cls: 'bm-content', style: 'max-height:90vh; display:flex; flex-direction:column;'});

    var header = _rbMakeEl('div', {cls: 'bm-header'});
    header.appendChild(_rbMakeEl('span', {cls: 'bm-header-title', text: 'COMPLIANCE REVIEW \u2014 #' + proposalId}));
    var headerStrip = _rbMakeEl('div', {cls: 'bm-header-strip'});
    ['w1', 'w2', 'w3'].forEach(function(w) {
        headerStrip.appendChild(_rbMakeEl('div', {cls: 'bm-header-pip ' + w}));
    });
    headerStrip.appendChild(_rbMakeEl('button', {
        cls: 'bm-close',
        text: '\u00D7',
        onclick: function() { overlay.remove(); }
    }));
    header.appendChild(headerStrip);

    var body = _rbMakeEl('div', {
        cls: 'bm-body',
        style: 'padding:16px 22px; flex:1 1 auto; min-height:0; overflow-y:auto;'
    });
    body.appendChild(_rbMakeEl('div', {
        style: 'text-align:center; padding:24px; color:#94a3b8; font-size:0.85rem;',
        text: 'Loading proposal \u2026'
    }));

    content.appendChild(header);
    content.appendChild(body);
    shell.appendChild(frame);
    shell.appendChild(content);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    try {
        var resp = await _rbFetchJson(RB_API + '/proposals/' + proposalId);
        var proposal = resp.proposal || resp;
        _rbClear(body);

        if (proposal.category !== 'compliance_fix') {
            body.appendChild(_rbMakeEl('div', {
                style: 'padding:14px; background:rgba(239,68,68,0.08); border-left:3px solid #ef4444; color:#fca5a5; font-size:0.82rem;',
                text: 'Not a compliance_fix proposal (category="' + (proposal.category || 'unknown') + '"). Use legacy Approve/Reject on the card.'
            }));
            return;
        }

        var meta = proposal.metadata || {};
        var fix_def = meta.fix_def || {};
        var fix_type = fix_def.type;
        var isSafe = SAFE_FIX_TYPES_JS.indexOf(fix_type) >= 0;

        function _section(label, value, color) {
            var s = _rbMakeEl('div', {style: 'margin-bottom:10px;'});
            s.appendChild(_rbMakeEl('div', {
                style: 'font-size:0.68rem; color:#64748b; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:3px;',
                text: label
            }));
            s.appendChild(_rbMakeEl('div', {
                style: 'font-size:0.85rem; color:' + (color || '#e2e8f0') +
                       '; font-family:"IBM Plex Mono",monospace; word-break:break-word;',
                text: value || '\u2014'
            }));
            return s;
        }

        var severity = proposal.priority || 'medium';
        var sevColor = severity === 'critical' ? '#ef4444' :
                       severity === 'high' ? '#f97316' :
                       severity === 'medium' ? '#fbbf24' : '#64748b';

        body.appendChild(_section('Rule ID', meta.rule_id || '?', '#8b5cf6'));
        body.appendChild(_section('Severity', String(severity).toUpperCase(), sevColor));
        body.appendChild(_section('Title', proposal.title));
        body.appendChild(_section('Fix Type', fix_type || 'unknown'));

        var summary = '\u2014';
        if (fix_type === 'sysctl') summary = 'sysctl ' + (fix_def.parameter || '?') + ' = ' + (fix_def.value || '?');
        else if (fix_type === 'file_line') summary = (fix_def.path || '?') + ' \u2192 ' + (fix_def.line || '?');
        else if (fix_type === 'service') summary = (fix_def.action || 'enable') + ' ' + (fix_def.name || fix_def.service || '?');
        else if (fix_type === 'command') {
            var cmd = fix_def.command || '';
            summary = cmd.length > 200 ? cmd.slice(0, 200) + '\u2026' : cmd;
        }
        body.appendChild(_section('Fix Summary', summary));

        if (meta.blocklist_reason) {
            var bl = _rbMakeEl('div', {
                style: 'margin:12px 0; padding:10px 12px; background:rgba(239,68,68,0.08); border-left:3px solid #ef4444; font-size:0.78rem; color:#fca5a5;'
            });
            bl.appendChild(_rbMakeEl('div', {
                style: 'font-size:0.68rem; color:#ef4444; text-transform:uppercase; margin-bottom:3px; font-weight:700;',
                text: 'BLOCKLIST WARNING'
            }));
            bl.appendChild(_rbMakeEl('div', {text: meta.blocklist_reason}));
            body.appendChild(bl);
        }

        var btnRow = _rbMakeEl('div', {
            style: 'display:flex; flex-direction:column; gap:8px; margin-top:14px;'
        });

        function _mkBtn(label, bg, action, title, disabled) {
            var b = _rbMakeEl('button', {
                cls: 'btn',
                style: 'padding:10px 14px; font-size:0.82rem; background:' + bg +
                       '; color:#0a0e1a; border:none; border-radius:4px; font-weight:700; ' +
                       'text-align:left; cursor:' + (disabled ? 'not-allowed' : 'pointer') +
                       '; opacity:' + (disabled ? '0.45' : '1') + ';',
                text: label
            });
            b.disabled = !!disabled;
            if (title) b.title = title;
            if (!disabled) {
                b.onclick = function() { _rbComplianceAction(proposalId, action, overlay); };
            }
            return b;
        }

        btnRow.appendChild(_mkBtn(
            '\u25B6  Apply Once',
            isSafe ? '#22c55e' : '#374151',
            'apply_once',
            isSafe
                ? 'Run safe-exec once: snapshot \u2192 apply \u2192 health gate \u2192 auto-rollback on failure.'
                : 'Disabled: fix_type "' + fix_type + '" is not in SAFE_FIX_TYPES (sysctl/file_line/service).',
            !isSafe
        ));
        btnRow.appendChild(_mkBtn(
            '\u2713  Apply + Always Allow',
            isSafe ? '#00e5ff' : '#374151',
            'apply_and_allow',
            isSafe
                ? 'Run safe-exec now AND mark rule auto-allow for the Sunday 03:00 EDT window.'
                : 'Disabled: fix_type "' + fix_type + '" is not auto-apply safe.',
            !isSafe
        ));
        btnRow.appendChild(_mkBtn(
            '\u2717  Dismiss (Mark Exempt)',
            '#94a3b8',
            'exempt',
            'Mark rule exempt. Proposal moves to resolved. Always available.',
            false
        ));

        body.appendChild(btnRow);
    } catch (e) {
        _rbClear(body);
        body.appendChild(_rbMakeEl('div', {
            style: 'padding:14px; background:rgba(239,68,68,0.08); border-left:3px solid #ef4444; color:#fca5a5; font-size:0.85rem;',
            text: 'Failed to load proposal: ' + e.message
        }));
    }
}

async function _rbComplianceAction(proposalId, action, overlay) {
    var buttons = overlay.querySelectorAll('button.btn');
    buttons.forEach(function(b) {
        b.disabled = true;
        b.style.opacity = '0.5';
        b.style.pointerEvents = 'none';
    });

    try {
        var resp = await fetch(RB_API + '/proposals/' + proposalId + '/compliance-action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: action})
        });
        var data = await resp.json();
        overlay.remove();
        _rbShowComplianceResult(proposalId, action, data);
        setTimeout(function() {
            if (typeof loadProposals === 'function') loadProposals();
        }, 1500);
    } catch (e) {
        overlay.remove();
        _rbShowToast('error', 'Action failed: ' + e.message);
    }
}

function _rbShowComplianceResult(proposalId, action, data) {
    var existing = document.getElementById('rb-compliance-result');
    if (existing) existing.remove();

    var success = data.success !== false;
    var accent = success ? '#22c55e' : '#ef4444';
    var rgb = success ? '34,197,94' : '239,68,68';

    var overlay = _rbMakeEl('div', {
        cls: 'bm-overlay active',
        style: '--bm-accent:' + accent + '; --bm-accent-rgb:' + rgb + ';'
    });
    overlay.id = 'rb-compliance-result';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    var shell = _rbMakeEl('div', {cls: 'bm-shell', style: 'max-width:520px; max-height:80vh;'});
    var frame = _rbMakeEl('div', {cls: 'bm-frame'});
    ['bm-frame-elbow-top', 'bm-frame-seg', 'bm-frame-seg dim', 'bm-frame-light on',
     'bm-frame-light amber', 'bm-frame-seg purple', 'bm-frame-fill', 'bm-frame-elbow-bottom'].forEach(function(cls) {
        frame.appendChild(_rbMakeEl('div', {cls: cls}));
    });

    var content = _rbMakeEl('div', {cls: 'bm-content', style: 'display:flex; flex-direction:column;'});
    var header = _rbMakeEl('div', {cls: 'bm-header'});
    header.appendChild(_rbMakeEl('span', {
        cls: 'bm-header-title',
        text: success ? (action === 'exempt' ? 'EXEMPTED' : 'APPLIED') : 'FAILED'
    }));
    var strip = _rbMakeEl('div', {cls: 'bm-header-strip'});
    ['w1', 'w2', 'w3'].forEach(function(w) {
        strip.appendChild(_rbMakeEl('div', {cls: 'bm-header-pip ' + w}));
    });
    strip.appendChild(_rbMakeEl('button', {
        cls: 'bm-close',
        text: '\u00D7',
        onclick: function() { overlay.remove(); }
    }));
    header.appendChild(strip);

    var body = _rbMakeEl('div', {cls: 'bm-body', style: 'padding:16px 22px;'});
    body.appendChild(_rbMakeEl('div', {
        style: 'font-size:0.82rem; color:#cbd5e1; margin-bottom:10px;',
        text: 'Proposal #' + proposalId + ' \u2014 action: ' + action
    }));
    if (data.status) {
        body.appendChild(_rbMakeEl('div', {
            style: 'font-size:0.78rem; color:#94a3b8; font-family:"IBM Plex Mono",monospace;',
            text: 'Status: ' + data.status
        }));
    }
    if (data.detail || data.error) {
        body.appendChild(_rbMakeEl('div', {
            style: 'margin-top:10px; padding:10px 12px; background:rgba(' + rgb + ',0.08); border-left:3px solid ' + accent + '; font-size:0.78rem; color:#cbd5e1; font-family:"IBM Plex Mono",monospace; word-break:break-word;',
            text: data.detail || data.error
        }));
    }
    if (data.rule_id) {
        body.appendChild(_rbMakeEl('div', {
            style: 'margin-top:10px; font-size:0.72rem; color:#64748b;',
            text: 'Rule: ' + data.rule_id
        }));
    }

    content.appendChild(header);
    content.appendChild(body);
    shell.appendChild(frame);
    shell.appendChild(content);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    if (success) {
        setTimeout(function() {
            if (document.getElementById('rb-compliance-result')) overlay.remove();
        }, 5000);
    }
}

/* ── Diagnose tab — stats banner + AI routing status ────────────
 * The inline template script owns the scanner UI (file browser, scan
 * modes, run actions, history). This loader just injects a compact
 * stats summary row at the top of the scanner sub-tab on first entry
 * so users see the shape of things before clicking into files.
 * Project #242 Task 5.
 */
async function loadDiagnose() {
    _diagnoseLoaded = true;

    // Re-use existing checkScanAi if present (loads AI routing status)
    if (typeof checkScanAi === 'function') {
        try { checkScanAi(); } catch (e) { /* ok */ }
    }

    var scannerTab = document.getElementById('scan-subtab-scanner');
    if (!scannerTab) return;

    // Idempotent: remove prior banner before re-rendering
    var existing = document.getElementById('rb-diagnose-stats');
    if (existing) existing.remove();

    var banner = _rbMakeEl('div', {
        style: 'display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; padding:10px 12px; ' +
               'background:rgba(0,212,255,0.04); border-left:3px solid #00d4ff; border-radius:3px; ' +
               'font-size:0.78rem;'
    });
    banner.id = 'rb-diagnose-stats';

    var title = _rbMakeEl('div', {
        style: 'width:100%; color:#94a3b8; font-size:0.68rem; text-transform:uppercase; ' +
               'letter-spacing:0.1em; margin-bottom:4px;',
        text: 'Scan Summary'
    });
    banner.appendChild(title);

    var loading = _rbMakeEl('span', {
        style: 'color:#64748b;',
        text: 'Loading stats\u2026'
    });
    banner.appendChild(loading);

    // Insert banner as the first child of the scanner subtab
    scannerTab.insertBefore(banner, scannerTab.firstChild);

    try {
        var data = await _rbFetchJson(RB_API + '/scan/stats');
        if (!data.success) throw new Error(data.error || 'stats fetch failed');

        _rbClear(banner);
        banner.appendChild(title);

        function _stat(label, value, color) {
            var chip = _rbMakeEl('span', {
                style: 'display:inline-flex; align-items:center; gap:6px; padding:4px 10px; ' +
                       'background:' + color + '22; color:' + color + '; border:1px solid ' + color + '55; ' +
                       'border-radius:12px; font-family:"IBM Plex Mono",monospace; font-size:0.74rem;'
            });
            chip.appendChild(_rbMakeEl('span', {style: 'opacity:0.7;', text: label}));
            chip.appendChild(_rbMakeEl('strong', {text: String(value)}));
            return chip;
        }

        var issueStats = data.issue_stats || {};
        var scanStats = data.scan_stats || {};

        banner.appendChild(_stat('open',     issueStats.open     || 0, '#00d4ff'));
        banner.appendChild(_stat('critical', issueStats.critical || 0, '#ef4444'));
        banner.appendChild(_stat('high',     issueStats.high     || 0, '#f97316'));
        banner.appendChild(_stat('medium',   issueStats.medium   || 0, '#fbbf24'));
        banner.appendChild(_stat('low',      issueStats.low      || 0, '#22c55e'));
        banner.appendChild(_stat('fixed',    issueStats.fixed    || 0, '#8b5cf6'));

        var sep = _rbMakeEl('span', {style: 'width:1px; background:#334155; align-self:stretch; margin:0 4px;'});
        banner.appendChild(sep);

        banner.appendChild(_stat('scans', scanStats.total_scans || 0, '#64748b'));
        banner.appendChild(_stat('files', scanStats.files_scanned || 0, '#64748b'));
        banner.appendChild(_stat('security', scanStats.security_issues || 0, '#ef4444'));

        var avg = scanStats.avg_quality_score;
        if (avg != null) {
            var avgNum = typeof avg === 'number' ? avg : parseFloat(avg);
            var grade = avgNum >= 90 ? '#22c55e' : avgNum >= 75 ? '#fbbf24' : '#ef4444';
            banner.appendChild(_stat('avg quality', avgNum.toFixed(1) + '%', grade));
        }
    } catch (e) {
        _rbClear(banner);
        banner.appendChild(title);
        banner.appendChild(_rbMakeEl('span', {
            style: 'color:#ef4444;',
            text: 'Failed to load scan stats: ' + e.message
        }));
    }

    // Trigger file list load (setScanMode handles all three modes)
    if (typeof setScanMode === 'function') {
        var prefs;
        try { prefs = JSON.parse(localStorage.getItem('dp_scan_prefs') || '{}'); } catch(_) { prefs = {}; }
        setScanMode(prefs.mode || 'browse', true);
    }
}

/* ── Test Bay tab — sandbox stats banner + auto-load ─────────────
 * Inline template owns the sandbox list render (loadSandboxes),
 * test runs history (loadTestRuns), and runNewTest triggers. This
 * loader adds a compact stats banner at the top of the Environments
 * sub-tab on first view and nudges the inline loaders so users don't
 * have to manually click Refresh. Project #242 Task 6.
 */
async function loadTestBay() {
    _testBayLoaded = true;

    if (typeof loadStagingStatus === 'function') {
        try { loadStagingStatus(); } catch (e) { console.warn('loadStagingStatus error:', e); }
    }
    if (typeof loadSandboxes === 'function') {
        try { loadSandboxes(); } catch (e) { console.warn('loadSandboxes error:', e); }
    }
    if (typeof loadTestRuns === 'function') {
        try { loadTestRuns(); } catch (e) { /* may not exist on first tab switch */ }
    }

    var envTab = document.getElementById('sandbox-subtab-environments');
    if (!envTab) return;

    var existing = document.getElementById('rb-testbay-stats');
    if (existing) existing.remove();

    var banner = _rbMakeEl('div', {
        style: 'display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; padding:10px 12px; ' +
               'background:rgba(139,92,246,0.05); border-left:3px solid #8b5cf6; border-radius:3px; ' +
               'font-size:0.78rem;'
    });
    banner.id = 'rb-testbay-stats';
    banner.appendChild(_rbMakeEl('div', {
        style: 'width:100%; color:#94a3b8; font-size:0.68rem; text-transform:uppercase; ' +
               'letter-spacing:0.1em; margin-bottom:4px;',
        text: 'Test Bay Summary'
    }));
    banner.appendChild(_rbMakeEl('span', {style: 'color:#64748b;', text: 'Loading sandboxes\u2026'}));

    envTab.insertBefore(banner, envTab.firstChild);

    try {
        var data = await _rbFetchJson(RB_API + '/sandbox/list');
        var sandboxes = data.sandboxes || [];

        _rbClear(banner);
        banner.appendChild(_rbMakeEl('div', {
            style: 'width:100%; color:#94a3b8; font-size:0.68rem; text-transform:uppercase; ' +
                   'letter-spacing:0.1em; margin-bottom:4px;',
            text: 'Test Bay Summary'
        }));

        function _stat(label, value, color) {
            var chip = _rbMakeEl('span', {
                style: 'display:inline-flex; align-items:center; gap:6px; padding:4px 10px; ' +
                       'background:' + color + '22; color:' + color + '; border:1px solid ' + color + '55; ' +
                       'border-radius:12px; font-family:"IBM Plex Mono",monospace; font-size:0.74rem;'
            });
            chip.appendChild(_rbMakeEl('span', {style: 'opacity:0.7;', text: label}));
            chip.appendChild(_rbMakeEl('strong', {text: String(value)}));
            return chip;
        }

        // Aggregate counts
        var total = sandboxes.length;
        var active = sandboxes.filter(function(s) { return s.status === 'active' || s.status === 'running'; }).length;
        var inactive = sandboxes.filter(function(s) { return s.status === 'inactive'; }).length;
        var withProposal = sandboxes.filter(function(s) { return s.current_proposal_id; }).length;

        var totalRuns = 0;
        var totalPassed = 0;
        var totalFailed = 0;
        sandboxes.forEach(function(s) {
            totalRuns += parseInt(s.total_tests_run || 0, 10);
            totalPassed += parseInt(s.tests_passed || 0, 10);
            totalFailed += parseInt(s.tests_failed || 0, 10);
        });
        var passRate = totalRuns > 0 ? ((totalPassed / totalRuns) * 100).toFixed(1) + '%' : 'n/a';
        var passColor = totalRuns === 0 ? '#64748b' :
                        (totalPassed / totalRuns) >= 0.9 ? '#22c55e' :
                        (totalPassed / totalRuns) >= 0.6 ? '#fbbf24' : '#ef4444';

        banner.appendChild(_stat('sandboxes', total, '#8b5cf6'));
        banner.appendChild(_stat('active', active, '#22c55e'));
        banner.appendChild(_stat('inactive', inactive, '#64748b'));
        banner.appendChild(_stat('with proposal', withProposal, '#00d4ff'));

        banner.appendChild(_rbMakeEl('span', {
            style: 'width:1px; background:#334155; align-self:stretch; margin:0 4px;'
        }));

        banner.appendChild(_stat('total runs', totalRuns, '#64748b'));
        banner.appendChild(_stat('passed', totalPassed, '#22c55e'));
        banner.appendChild(_stat('failed', totalFailed, '#ef4444'));
        banner.appendChild(_stat('pass rate', passRate, passColor));
    } catch (e) {
        _rbClear(banner);
        banner.appendChild(_rbMakeEl('span', {
            style: 'color:#ef4444;',
            text: 'Failed to load sandbox stats: ' + e.message
        }));
    }
}

/* ── Ship tab — populate top stat cards + nudge inline loaders ──
 * The Ship tab has 3 top stat cards (#deployTotalCount, #deployReadyCount,
 * #deployFailedCount) already in the HTML but static at 0. Inline
 * loadDeployReady / loadDeployHistory / loadForgeStats also exist. This
 * loader fills the top cards with real numbers from deploy/history +
 * deploy/ready and nudges the inline loaders so sub-tabs auto-populate.
 * Project #242 Task 7.
 *
 * Note: /api/forge/stats is broken on main (SQL error: relation
 * "agent_loop_cycles" does not exist). Filed as follow-up; the F.O.R.G.E.
 * sub-tab inline loader will just fail silently until that's fixed.
 */
async function loadShip() {
    _shipLoaded = true;

    if (typeof loadDeployReady === 'function') {
        try { loadDeployReady(); } catch (e) { /* ok */ }
    }
    if (typeof loadDeployHistory === 'function') {
        try { loadDeployHistory(); } catch (e) { /* ok */ }
    }

    // Populate the 3 top stat cards from real data
    try {
        var ready = await _rbFetchJson(RB_API + '/deploy/ready');
        var readyCount = 0;
        if (ready && ready.proposals) readyCount = ready.proposals.length;
        else if (ready && Array.isArray(ready)) readyCount = ready.length;
        else if (ready && typeof ready.count === 'number') readyCount = ready.count;
        var readyEl = document.getElementById('deployReadyCount');
        if (readyEl) readyEl.textContent = readyCount;
    } catch (e) {
        console.warn('loadShip: /deploy/ready failed:', e.message);
    }

    try {
        var hist = await _rbFetchJson(RB_API + '/deploy/history');
        var deployments = (hist && hist.deployments) || [];
        var total = deployments.length;
        var failed = deployments.filter(function(d) {
            var s = (d.status || '').toLowerCase();
            return s === 'failed' || s === 'rolled_back' || s === 'rollback_failed';
        }).length;
        var totalEl = document.getElementById('deployTotalCount');
        var failedEl = document.getElementById('deployFailedCount');
        if (totalEl) totalEl.textContent = total;
        if (failedEl) failedEl.textContent = failed;
    } catch (e) {
        console.warn('loadShip: /deploy/history failed:', e.message);
    }

    // F.O.R.G.E. sub-tab has its own inline loader; nudge it but swallow
    // errors because /api/forge/stats has a pre-existing SQL bug on main.
    if (typeof loadForgeStats === 'function') {
        try { loadForgeStats(); } catch (e) { /* ok */ }
    }
}

/* ── Bootstrap ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
    loadReviews();
});

/* ── PR Review Tab (#1801) ─────────────────────────────────────── */
// _prReviewsTimer is retained: the inline implementation in repair_bay.html
// calls window._stopPRReviewPoll() (defined below) which clears this timer.
window._prReviewsTimer = null;

// NOTE: window._startPRReviewPoll / window.loadPRReviews and their PR-review
// render helpers (_prVerdictText, _prParseSummary, prSelectReview,
// _prRenderDetail, prMerge, prAnalyze, prSkip, _prVerdictClass, _prClear) were
// removed here (T3507 H-9). The active implementations are defined inline in
// templates/tools/repair_bay.html, which loads AFTER this file and wins.
// window._stopPRReviewPoll is kept because the inline template calls it but does
// NOT redefine it.
window._stopPRReviewPoll = function() {
  clearInterval(window._prReviewsTimer);
};
/* ─────────────────────────────────────────────────────────────── */
