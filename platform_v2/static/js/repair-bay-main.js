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

/* ── Reviews tab — GitHub PR list ─────────────────────────────── */
function loadReviews() {
    _reviewsLoaded = true;
    var container = document.getElementById('reviewsList');
    var countEl = document.getElementById('reviewsCount');
    var state = (document.getElementById('reviewsStateFilter') || {}).value || 'open';
    if (!container) return;

    _rbEmpty(container, 'Loading PRs from GitHub…');

    _rbFetchJson(RB_API + '/forge/prs?state=' + encodeURIComponent(state))
        .then(function(data) {
            var prs = data.prs || data.pull_requests || [];
            if (!prs.length) {
                if (countEl) countEl.textContent = '0 PRs';
                _rbEmpty(container, 'No ' + state + ' PRs found.');
                return;
            }

            // Sort + rank: mergeable PRs get a merge-order rank (1..N) sorted
            // oldest-ready-first so the most senior ready-to-merge work
            // appears at the top. Conflicting/unknown sink to the bottom.
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

            if (countEl) {
                countEl.textContent =
                    prs.length + ' PR' + (prs.length !== 1 ? 's' : '') +
                    ' · ' + mergeable.length + ' ready to merge';
            }

            _rbClear(container);
            ordered.forEach(function(pr) {
                container.appendChild(_buildReviewCard(pr));
            });
            if (typeof lucide !== 'undefined' && lucide.createIcons) {
                try { lucide.createIcons(); } catch (e) { /* ok */ }
            }
        })
        .catch(function(e) {
            _rbEmpty(container, 'Failed to load PRs: ' + e.message, '#ef4444');
        });
}

function _buildReviewCard(pr) {
    var card = _rbMakeEl('div', {
        cls: 'dp-proposal-card',
        style: 'padding:14px 16px; margin-bottom:10px; border-left:3px solid #00d4ff; background:rgba(0,212,255,0.04); border-radius:4px;'
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
        style: 'color:#e2e8f0; font-weight:600; font-size:0.9rem; overflow:hidden; text-overflow:ellipsis;',
        text: pr.title || '(untitled)'
    });
    titleWrap.appendChild(title);

    var parts = [];
    if (pr.user) parts.push('by ' + pr.user);
    if (pr.head_ref || pr.head) parts.push(pr.head_ref || pr.head);
    if (pr.updated_at) parts.push('updated ' + _rbFmtDate(pr.updated_at));
    var sub = _rbMakeEl('div', {
        style: 'color:#94a3b8; font-size:0.72rem; margin-top:2px;',
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
    var actions = _rbMakeEl('div', {style: 'display:flex; gap:8px; margin-top:10px; justify-content:flex-end;'});

    var viewBtn = _rbMakeEl('a', {
        href: pr.html_url || '#',
        target: '_blank',
        rel: 'noopener',
        cls: 'dp-btn',
        style: 'padding:6px 12px; font-size:0.78rem; background:rgba(0,212,255,0.15); border:1px solid #00d4ff; color:#00d4ff; text-decoration:none; border-radius:3px;',
        text: 'Review on GitHub'
    });
    actions.appendChild(viewBtn);

    // Show merge button if mergeable AND no one requested changes.
    // Admin (user) can merge their own PRs without requiring a separate
    // review decision — which is the common case for solo dev flow.
    if (pr.mergeable === 'MERGEABLE' && pr.review_decision !== 'CHANGES_REQUESTED') {
        var mergeBtn = _rbMakeEl('button', {
            cls: 'dp-btn',
            style: 'padding:6px 14px; font-size:0.8rem; background:#22c55e; color:#0a0e1a; border:none; border-radius:3px; cursor:pointer; font-weight:700;',
            text: 'Approve & Merge ✓',
            onclick: function() { _mergePr(pr.number, mergeBtn); }
        });
        actions.appendChild(mergeBtn);
    } else if (pr.mergeable === 'CONFLICTING') {
        var conflictBadge = _rbMakeEl('span', {
            style: 'padding:6px 12px; font-size:0.75rem; background:rgba(239,68,68,0.15); color:#ef4444; border:1px solid #ef4444; border-radius:3px;',
            text: 'Needs rebase'
        });
        actions.appendChild(conflictBadge);
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
            'background:' + color + '22; color:' + color + '; border:1px solid ' + color + '55;',
        text: label + ': ' + txt
    });
}

function _mergePr(prNumber, btn) {
    if (!confirm('Approve and merge PR #' + prNumber + '?\n\nThis will squash-merge via the F.O.R.G.E. pipeline.')) return;
    btn.disabled = true;
    btn.textContent = 'Merging…';
    _rbFetchJson(RB_API + '/forge/prs/' + prNumber + '/merge', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({method: 'squash'})
    })
    .then(function(data) {
        if (data.success) {
            btn.textContent = 'Merged ✓';
            btn.style.background = '#16a34a';
            _rbShowToast('success', 'PR #' + prNumber + ' merged');
            setTimeout(loadReviews, 1500);
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

/* ── Stub loaders for other tabs (filled in Tasks 4-7) ────────── */
function loadRepairs() {
    if (_repairsLoaded) return;
    _repairsLoaded = true;
    if (typeof filterProposals === 'function') {
        try { filterProposals(); } catch (e) { console.warn('filterProposals error:', e); }
    }
}

function loadDiagnose() {
    if (_diagnoseLoaded) return;
    _diagnoseLoaded = true;
}

function loadTestBay() {
    if (_testBayLoaded) return;
    _testBayLoaded = true;
    if (typeof loadSandboxes === 'function') {
        try { loadSandboxes(); } catch (e) { console.warn('loadSandboxes error:', e); }
    }
}

function loadShip() {
    if (_shipLoaded) return;
    _shipLoaded = true;
    if (typeof loadForgeStats === 'function') {
        try { loadForgeStats(); } catch (e) { console.warn('loadForgeStats error:', e); }
    }
}

/* ── Bootstrap ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function() {
    loadReviews();
});
