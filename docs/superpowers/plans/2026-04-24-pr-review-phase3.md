# PR Review Phase 3 — Repair Bay UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PR Review tab to the Repair Bay with a split-pane UI — PR list on the left, AI review detail + actions on the right.

**Architecture:** One new backend route (GitHub merge), new CSS classes in repair-bay.css, new JS functions in repair-bay-main.js, and a new tab div + switchTab wire-up in repair_bay.html. All dynamic DOM content uses textContent/createElement — no innerHTML with API data.

**Tech Stack:** Flask/Jinja2, vanilla JS, GitHub REST API (GITHUB_TOKEN), PostgreSQL (pr_reviews table), existing LCARS/dp- CSS design system.

**Security note:** All dynamic content uses `textContent` or `createElement`. The only `innerHTML` usage is resetting static container strings (empty or literal text). The helper `_prClear(el)` removes children via `removeChild` to be fully innerHTML-free.

---

## File Map

| File | Action | Change |
|------|--------|--------|
| `platform_v2/tools/repair_bay/github_routes.py` | Modify | Add `POST /api/forge/pr-reviews/<n>/merge` route |
| `platform_v2/static/css/repair-bay.css` | Modify | Append `dp-pr-*` split pane CSS classes |
| `platform_v2/static/js/repair-bay-main.js` | Modify | Append PR Review functions |
| `platform_v2/templates/tools/repair_bay.html` | Modify | Add tab entry, tab content div, switchTab wire-up |

---

## Task 1: Add merge route

**Files:**
- Modify: `platform_v2/tools/repair_bay/github_routes.py` (after line 655)

- [ ] **Step 1: Read the end of github_routes.py to find the insertion point**

  ```bash
  tail -15 /mnt/archie_brain/platform_v2/tools/repair_bay/github_routes.py
  ```

  The file ends inside `register_github_routes(bp, admin_required)`. Add the merge route as the last route before the function closes.

- [ ] **Step 2: Add the merge route**

  Add immediately after the existing `forge_pr_reviews_skip` function:

  ```python
      @bp.route("/api/forge/pr-reviews/<int:pr_number>/merge", methods=["POST"])
      @login_required
      @admin_required
      def forge_pr_review_merge(pr_number):
          """Merge a PR via GitHub API (squash merge). State syncs on next poll cycle."""
          import requests as _req
          import os

          from .services.pr_review_service import get_review

          review = get_review(pr_number)
          if not review:
              return jsonify({"error": f"PR #{pr_number} not found"}), 404

          github_token = os.getenv("GITHUB_TOKEN", "")
          if not github_token:
              return jsonify({"error": "GITHUB_TOKEN not configured"}), 500

          repo = review.get("repo", "KytranKatarn/archie-platform")
          title = review.get("title", f"PR #{pr_number}")

          resp = _req.put(
              f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
              headers={
                  "Authorization": f"token {github_token}",
                  "Accept": "application/vnd.github.v3+json",
              },
              json={
                  "commit_title": f"Merge PR #{pr_number}: {title}",
                  "merge_method": "squash",
              },
              timeout=15,
          )

          if resp.status_code in (200, 201):
              return jsonify({"success": True, "merged": True, "message": resp.json().get("message", "Merged")})
          else:
              err = resp.json().get("message", resp.text[:200])
              return jsonify({"success": False, "merged": False, "error": err}), resp.status_code
  ```

- [ ] **Step 3: Restart platform and verify route registered**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  sleep 5
  docker exec archie_platform python3 -c "
  from app import app
  rules = [str(r) for r in app.url_map.iter_rules() if 'merge' in str(r)]
  print(rules)
  "
  ```

  Expected: includes `/tools/repair-bay/api/forge/pr-reviews/<pr_number>/merge`

- [ ] **Step 4: Test route shape — missing PR → 404**

  ```bash
  # Confirm the route handles missing PR gracefully
  docker exec archie_platform python3 -c "
  from app import app
  with app.test_client() as c:
      c.get('/')  # warm up session
      r = c.post('/tools/repair-bay/api/forge/pr-reviews/99999/merge')
      print('Status:', r.status_code)  # expect 302 (login redirect) or 404
  "
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add platform_v2/tools/repair_bay/github_routes.py
  git commit -m "feat(pr-review): merge route POST /api/forge/pr-reviews/<n>/merge (#1801)"
  ```

---

## Task 2: Add CSS

**Files:**
- Modify: `platform_v2/static/css/repair-bay.css`

- [ ] **Step 1: Append split-pane CSS to repair-bay.css**

  Append to the end of `/mnt/archie_brain/platform_v2/static/css/repair-bay.css`:

  ```css
  /* ── PR Review Tab — split pane (#1801) ───────────────────────── */
  .dp-pr-split {
    display: flex;
    height: 520px;
    border: 1px solid var(--archie-border, #1e293b);
    border-radius: 6px;
    overflow: hidden;
    margin-top: 8px;
  }
  .dp-pr-list {
    width: 240px;
    flex-shrink: 0;
    overflow-y: auto;
    border-right: 1px solid var(--archie-border, #1e293b);
    background: var(--archie-surface, #0f172a);
  }
  .dp-pr-list::-webkit-scrollbar { width: 4px; }
  .dp-pr-list::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px; }
  .dp-pr-row {
    padding: 10px 14px;
    border-bottom: 1px solid var(--archie-border, #1e293b);
    cursor: pointer;
    transition: background .1s;
  }
  .dp-pr-row:hover { background: #1e293b44; }
  .dp-pr-row--active { background: #1e3a5f; border-left: 3px solid #00d4ff; }
  .dp-pr-row-number { font-size: 10px; color: var(--archie-muted, #64748b); margin-bottom: 2px; }
  .dp-pr-row-title { font-size: 12px; color: var(--archie-text, #e2e8f0); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .dp-pr-row-meta { font-size: 10px; color: var(--archie-muted, #64748b); margin-top: 3px; }
  .dp-pr-detail {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    background: var(--archie-bg, #0a0e1a);
  }
  .dp-pr-detail--empty {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--archie-muted, #64748b);
    font-size: 13px;
  }
  .dp-pr-title { font-size: 16px; font-weight: 600; color: var(--archie-text, #e2e8f0); margin-bottom: 4px; }
  .dp-pr-meta { font-size: 11px; color: var(--archie-muted, #64748b); margin-bottom: 16px; }
  .dp-pr-verdict { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
  .dp-pr-verdict--approve    { color: #22c55e; }
  .dp-pr-verdict--request    { color: #f59e0b; }
  .dp-pr-verdict--needs      { color: #7eb8f7; }
  .dp-pr-verdict--pending    { color: #64748b; }
  .dp-pr-section-label { font-size: 10px; font-weight: 600; color: var(--archie-muted, #64748b); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
  .dp-pr-summary { font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 14px; }
  .dp-pr-issues { margin-bottom: 16px; }
  .dp-pr-issue { font-size: 12px; color: #94a3b8; margin-bottom: 4px; line-height: 1.5; }
  .dp-pr-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; margin-bottom: 10px; }
  .dp-pr-btn {
    padding: 6px 14px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    border: 1px solid;
    background: transparent;
    transition: opacity .15s;
  }
  .dp-pr-btn:hover { opacity: 0.8; }
  .dp-pr-btn--merge  { border-color: #22c55e; color: #22c55e; }
  .dp-pr-btn--review { border-color: #7eb8f7; color: #7eb8f7; }
  .dp-pr-btn--skip   { border-color: #64748b; color: #64748b; }
  .dp-pr-github-link {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: #00d4ff;
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color .15s;
  }
  .dp-pr-github-link:hover { border-bottom-color: #00d4ff; }
  .dp-pr-analyze-btn {
    padding: 3px 10px;
    border: 1px solid #7eb8f7;
    color: #7eb8f7;
    border-radius: 3px;
    font-size: 10px;
    cursor: pointer;
    background: transparent;
    margin-top: 4px;
  }
  .dp-pr-analyze-btn:hover { opacity: 0.8; }
  .dp-pr-empty-state {
    padding: 30px 14px;
    text-align: center;
    color: var(--archie-muted, #64748b);
    font-size: 12px;
  }
  ```

- [ ] **Step 2: Restart and verify no visual regressions**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

  Open http://192.168.1.200:3000/tools/repair-bay — existing tabs look unchanged.

- [ ] **Step 3: Commit**

  ```bash
  git add platform_v2/static/css/repair-bay.css
  git commit -m "feat(pr-review): dp-pr-* split pane CSS (#1801)"
  ```

---

## Task 3: Add JavaScript

**Files:**
- Modify: `platform_v2/static/js/repair-bay-main.js`

- [ ] **Step 1: Read the end of repair-bay-main.js**

  ```bash
  tail -10 /mnt/archie_brain/platform_v2/static/js/repair-bay-main.js
  ```

- [ ] **Step 2: Append PR Review JS to repair-bay-main.js**

  Append to the end of the file:

  ```javascript
  /* ── PR Review Tab (#1801) ─────────────────────────────────────── */
  window._prSelectedId = null;
  window._prReviewsTimer = null;

  // Remove all children without using innerHTML
  function _prClear(el) {
    while (el && el.firstChild) { el.removeChild(el.firstChild); }
  }

  function _prVerdictClass(summary) {
    if (!summary) return 'dp-pr-verdict--pending';
    var u = summary.toUpperCase();
    if (u.indexOf('VERDICT: APPROVE') !== -1) return 'dp-pr-verdict--approve';
    if (u.indexOf('VERDICT: REQUEST CHANGES') !== -1) return 'dp-pr-verdict--request';
    if (u.indexOf('VERDICT: NEEDS REVIEW') !== -1) return 'dp-pr-verdict--needs';
    return 'dp-pr-verdict--pending';
  }

  function _prVerdictText(summary) {
    if (!summary) return '⏳ PENDING REVIEW';
    var u = summary.toUpperCase();
    if (u.indexOf('VERDICT: APPROVE') !== -1) return '✅ VERDICT: APPROVE';
    if (u.indexOf('VERDICT: REQUEST CHANGES') !== -1) return '⚠ VERDICT: REQUEST CHANGES';
    if (u.indexOf('VERDICT: NEEDS REVIEW') !== -1) return '🔵 VERDICT: NEEDS REVIEW';
    return '⏳ PENDING REVIEW';
  }

  function _prParseSummary(aiSummary) {
    if (!aiSummary) return { summary: '', issues: [] };
    var summaryMatch = aiSummary.match(/SUMMARY\s*([\s\S]*?)(?=ISSUES|VERDICT|$)/i);
    var issuesMatch  = aiSummary.match(/ISSUES\s*([\s\S]*?)(?=VERDICT|$)/i);
    var summary = summaryMatch ? summaryMatch[1].trim() : aiSummary;
    var issuesText = issuesMatch ? issuesMatch[1].trim() : '';
    var issues = issuesText
      ? issuesText.split('\n').map(function(l) { return l.trim(); }).filter(function(l) { return l.charAt(0) === '-' || l.charAt(0) === '•'; })
      : [];
    return { summary: summary, issues: issues };
  }

  window.loadPRReviews = function() {
    fetch('/tools/repair-bay/api/forge/pr-reviews?state=open&limit=50')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var reviews = data.reviews || [];
        var listEl = document.getElementById('prReviewList');
        if (!listEl) return;
        _prClear(listEl);

        if (reviews.length === 0) {
          var empty = document.createElement('div');
          empty.className = 'dp-pr-empty-state';
          empty.textContent = 'No open PRs tracked yet. Click Poll GitHub to sync.';
          listEl.appendChild(empty);
          return;
        }

        reviews.sort(function(a, b) {
          var order = { reviewed: 0, in_progress: 1, pending: 2, skipped: 3 };
          return (order[a.review_status] || 2) - (order[b.review_status] || 2);
        });

        reviews.forEach(function(pr) {
          var row = document.createElement('div');
          row.className = 'dp-pr-row' + (pr.pr_number === window._prSelectedId ? ' dp-pr-row--active' : '');
          row.dataset.prNumber = pr.pr_number;
          row.onclick = (function(p, all) { return function() { window.prSelectReview(p, all); }; }(pr, reviews));

          var num = document.createElement('div');
          num.className = 'dp-pr-row-number';
          num.textContent = '#' + pr.pr_number + ' · ' + _prVerdictText(pr.ai_summary);

          var title = document.createElement('div');
          title.className = 'dp-pr-row-title';
          title.textContent = pr.title || '(untitled)';

          var meta = document.createElement('div');
          meta.className = 'dp-pr-row-meta';

          if (pr.review_status === 'pending' || pr.review_status === 'skipped') {
            var btn = document.createElement('button');
            btn.className = 'dp-pr-analyze-btn';
            btn.textContent = pr.review_status === 'skipped' ? 'Re-analyze' : 'Analyze Now';
            btn.onclick = (function(n) { return function(e) { e.stopPropagation(); window.prAnalyze(n); }; }(pr.pr_number));
            meta.appendChild(btn);
          } else if (pr.author) {
            meta.textContent = 'by ' + pr.author;
          }

          row.appendChild(num);
          row.appendChild(title);
          row.appendChild(meta);
          listEl.appendChild(row);
        });

        if (!window._prSelectedId && reviews.length > 0) {
          var first = null;
          for (var i = 0; i < reviews.length; i++) {
            if (reviews[i].review_status === 'reviewed') { first = reviews[i]; break; }
          }
          window.prSelectReview(first || reviews[0], reviews);
        }
      })
      .catch(function(err) { console.error('[PR Review] load failed:', err); });
  };

  window.prSelectReview = function(pr, allReviews) {
    window._prSelectedId = pr.pr_number;
    document.querySelectorAll('.dp-pr-row').forEach(function(el) {
      el.classList.toggle('dp-pr-row--active', parseInt(el.dataset.prNumber, 10) === pr.pr_number);
    });
    window._prRenderDetail(pr);
  };

  window._prRenderDetail = function(pr) {
    var el = document.getElementById('prReviewDetail');
    if (!el) return;
    el.className = 'dp-pr-detail';
    _prClear(el);

    var parsed = _prParseSummary(pr.ai_summary);

    var titleEl = document.createElement('div');
    titleEl.className = 'dp-pr-title';
    titleEl.textContent = '#' + pr.pr_number + ' — ' + (pr.title || '(untitled)');
    el.appendChild(titleEl);

    var metaEl = document.createElement('div');
    metaEl.className = 'dp-pr-meta';
    var metaParts = [];
    if (pr.author) metaParts.push('by ' + pr.author);
    if (pr.base_branch && pr.head_branch) metaParts.push(pr.base_branch + ' ← ' + pr.head_branch);
    if (pr.additions != null) metaParts.push('+' + pr.additions + ' -' + (pr.deletions || 0));
    if (pr.changed_files != null) metaParts.push(pr.changed_files + ' files');
    metaEl.textContent = metaParts.join(' · ');
    el.appendChild(metaEl);

    var verdict = document.createElement('div');
    verdict.className = 'dp-pr-verdict ' + _prVerdictClass(pr.ai_summary);
    verdict.textContent = _prVerdictText(pr.ai_summary);
    el.appendChild(verdict);

    if (parsed.summary) {
      var sumLabel = document.createElement('div');
      sumLabel.className = 'dp-pr-section-label';
      sumLabel.textContent = 'Summary';
      el.appendChild(sumLabel);

      var sumEl = document.createElement('div');
      sumEl.className = 'dp-pr-summary';
      sumEl.textContent = parsed.summary;
      el.appendChild(sumEl);
    }

    if (parsed.issues.length > 0) {
      var issLabel = document.createElement('div');
      issLabel.className = 'dp-pr-section-label';
      issLabel.textContent = 'Issues';
      el.appendChild(issLabel);

      var issEl = document.createElement('div');
      issEl.className = 'dp-pr-issues';
      parsed.issues.forEach(function(issue) {
        var li = document.createElement('div');
        li.className = 'dp-pr-issue';
        li.textContent = issue;
        issEl.appendChild(li);
      });
      el.appendChild(issEl);
    }

    var actions = document.createElement('div');
    actions.className = 'dp-pr-actions';

    if (pr.state === 'open') {
      var mergeBtn = document.createElement('button');
      mergeBtn.className = 'dp-pr-btn dp-pr-btn--merge';
      mergeBtn.textContent = 'Merge PR';
      mergeBtn.onclick = (function(n, repo) { return function() { window.prMerge(n, repo); }; }(pr.pr_number, pr.repo));
      actions.appendChild(mergeBtn);
    }

    var reviewBtn = document.createElement('button');
    reviewBtn.className = 'dp-pr-btn dp-pr-btn--review';
    reviewBtn.textContent = pr.ai_summary ? 'Re-review' : 'Analyze Now';
    reviewBtn.onclick = (function(n) { return function() { window.prAnalyze(n); }; }(pr.pr_number));
    actions.appendChild(reviewBtn);

    if (pr.review_status !== 'skipped') {
      var skipBtn = document.createElement('button');
      skipBtn.className = 'dp-pr-btn dp-pr-btn--skip';
      skipBtn.textContent = 'Skip';
      skipBtn.onclick = (function(n) { return function() { window.prSkip(n); }; }(pr.pr_number));
      actions.appendChild(skipBtn);
    }

    el.appendChild(actions);

    if (pr.pr_number && pr.repo) {
      var link = document.createElement('a');
      link.className = 'dp-pr-github-link';
      link.href = 'https://github.com/' + pr.repo + '/pull/' + pr.pr_number + '/files';
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'View Diff on GitHub ↗';
      el.appendChild(link);
    }
  };

  window.prMerge = function(prNumber, repo) {
    if (!confirm('Merge PR #' + prNumber + ' via squash merge?')) return;
    fetch('/tools/repair-bay/api/forge/pr-reviews/' + prNumber + '/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.success) {
        window._prSelectedId = null;
        var detail = document.getElementById('prReviewDetail');
        if (detail) {
          _prClear(detail);
          var msg = document.createElement('p');
          msg.textContent = 'PR #' + prNumber + ' merged. Refreshing list...';
          detail.appendChild(msg);
        }
        setTimeout(window.loadPRReviews, 2000);
      } else {
        alert('Merge failed: ' + (data.error || 'unknown error'));
      }
    })
    .catch(function(err) { alert('Merge request failed: ' + err); });
  };

  window.prAnalyze = function(prNumber) {
    var detail = document.getElementById('prReviewDetail');
    if (detail) {
      _prClear(detail);
      var msg = document.createElement('p');
      msg.style.padding = '20px';
      msg.style.color = '#64748b';
      msg.textContent = 'Dispatching F.O.R.G.E. review for PR #' + prNumber + '...';
      detail.appendChild(msg);
    }
    fetch('/tools/repair-bay/api/forge/pr-reviews/' + prNumber + '/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.success) {
        window.loadPRReviews();
      } else {
        if (detail) {
          _prClear(detail);
          var errMsg = document.createElement('p');
          errMsg.style.padding = '20px';
          errMsg.style.color = '#ef4444';
          errMsg.textContent = 'Analysis failed: ' + (data.error || 'check platform logs');
          detail.appendChild(errMsg);
        }
      }
    })
    .catch(function(err) {
      if (detail) {
        _prClear(detail);
        var errMsg = document.createElement('p');
        errMsg.style.padding = '20px';
        errMsg.style.color = '#ef4444';
        errMsg.textContent = 'Request failed: ' + err;
        detail.appendChild(errMsg);
      }
    });
  };

  window.prSkip = function(prNumber) {
    fetch('/tools/repair-bay/api/forge/pr-reviews/' + prNumber + '/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
    .then(function(r) { return r.json(); })
    .then(function() { window._prSelectedId = null; window.loadPRReviews(); })
    .catch(function(err) { console.error('[PR Skip] failed:', err); });
  };

  window._startPRReviewPoll = function() {
    window.loadPRReviews();
    clearInterval(window._prReviewsTimer);
    window._prReviewsTimer = setInterval(window.loadPRReviews, 30000);
  };

  window._stopPRReviewPoll = function() {
    clearInterval(window._prReviewsTimer);
  };
  /* ─────────────────────────────────────────────────────────────── */
  ```

- [ ] **Step 3: Restart platform**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

- [ ] **Step 4: Verify JS served**

  ```bash
  curl -s http://192.168.1.200:3000/static/js/repair-bay-main.js | grep "_startPRReviewPoll" | head -2
  ```

  Expected: line containing `_startPRReviewPoll`

- [ ] **Step 5: Commit**

  ```bash
  git add platform_v2/static/js/repair-bay-main.js
  git commit -m "feat(pr-review): split-pane JS for PR Review tab (#1801)"
  ```

---

## Task 4: Add HTML tab

**Files:**
- Modify: `platform_v2/templates/tools/repair_bay.html`

- [ ] **Step 1: Read header_tabs and first tab structure**

  ```bash
  sed -n '20,35p' /mnt/archie_brain/platform_v2/templates/tools/repair_bay.html
  ```

  ```bash
  grep -n "id=\"tab-reviews\"\|id=\"tab-proposals\"" \
    /mnt/archie_brain/platform_v2/templates/tools/repair_bay.html | head -4
  ```

- [ ] **Step 2: Add pr-review to header_tabs**

  In `repair_bay.html`, find the line with `("reviews", "Reviews", "message-square"),` and add the entry immediately after:

  ```
      ("pr-review", "PR Review", "git-pull-request"),
  ```

  Result (first two entries):
  ```
  {% set header_tabs = [
      ("reviews", "Reviews", "message-square"),
      ("pr-review", "PR Review", "git-pull-request"),
      ("proposals", "Repairs", "wrench"),
  ```

- [ ] **Step 3: Insert the tab content div before tab-proposals**

  Find the line with `id="tab-proposals"`. Insert the following block immediately before that line:

  ```html
          <!-- ── PR Review Tab (#1801) ── -->
          <div id="tab-pr-review" class="tab-content">
            <div class="lcars-frame">
              <div class="lcars-sidebar" style="background:var(--cat-accent,#00ffff)">
                <div class="lcars-bar"></div><div class="lcars-bar"></div>
              </div>
              <div class="lcars-main">
                <div class="lcars-header-bar" style="border-color:var(--cat-accent,#00ffff)">
                  <span class="lcars-title">PR REVIEWS</span>
                  <div style="display:flex;gap:8px;align-items:center">
                    <button class="dp-btn" onclick="window.loadPRReviews()">
                      <i data-lucide="refresh-cw" style="width:14px;height:14px"></i> Refresh
                    </button>
                    <button class="dp-btn"
                      onclick="fetch('/tools/repair-bay/api/forge/pr-reviews/poll',{method:'POST'}).then(function(){window.loadPRReviews();})">
                      Poll GitHub
                    </button>
                  </div>
                </div>
                <div style="padding:12px">
                  <div class="dp-pr-split">
                    <div class="dp-pr-list" id="prReviewList">
                      <div class="dp-pr-empty-state">Loading...</div>
                    </div>
                    <div class="dp-pr-detail dp-pr-detail--empty" id="prReviewDetail">
                      Select a PR to view the review
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- ── End PR Review Tab ── -->
  ```

- [ ] **Step 4: Read the switchTab function**

  ```bash
  START=$(grep -n "function switchTab" /mnt/archie_brain/platform_v2/templates/tools/repair_bay.html | head -1 | cut -d: -f1)
  sed -n "${START},$((START+40))p" /mnt/archie_brain/platform_v2/templates/tools/repair_bay.html
  ```

- [ ] **Step 5: Wire up switchTab**

  Add `window._stopPRReviewPoll();` as the FIRST line inside `switchTab(tabId)` (before any existing logic), so switching away always stops the poll.

  Then add the PR Review activate branch alongside the other tab loaders:

  ```javascript
  else if (tabId === 'pr-review') { window._startPRReviewPoll(); }
  ```

  Place it after the `if (tabId === 'reviews') { loadReviews(); }` branch.

- [ ] **Step 6: Restart and browser test**

  ```bash
  cd /mnt/archie_brain && docker compose restart archie_platform
  ```

  Open http://192.168.1.200:3000/tools/repair-bay. Verify:
  - "PR Review" tab appears between Reviews and Repairs
  - Clicking the tab loads the split pane
  - Left pane shows PR rows or "No open PRs" message
  - Clicking a reviewed PR shows verdict + summary + issues + buttons in right pane
  - "View Diff on GitHub ↗" link opens `https://github.com/{repo}/pull/{n}/files`
  - Merge PR shows confirm dialog before posting
  - Switching to another tab stops the 30s poll (no console polling after tab switch)
  - No console errors

- [ ] **Step 7: Commit**

  ```bash
  git add platform_v2/templates/tools/repair_bay.html
  git commit -m "feat(pr-review): PR Review tab in Repair Bay — split pane UI (#1801)"
  ```

---

## Final: PR and Dev HQ

- [ ] **Step 1: Create branch and push**

  ```bash
  git checkout -b feat/pr-review-phase3-1801
  git push -u origin feat/pr-review-phase3-1801
  gh pr create \
    --title "feat(pr-review): Phase 3 — Repair Bay PR Review tab (#1801)" \
    --base main \
    --body "$(cat <<'EOF'
  ## Summary
  - New **PR Review** tab in Repair Bay (between Reviews and Repairs)
  - Split-pane: PR list left, AI review detail + actions right
  - One new route: POST /api/forge/pr-reviews/<n>/merge (squash merge via GitHub API)
  - ai_summary parsed at SUMMARY/ISSUES/VERDICT markers — verdict badge colour-coded
  - View Diff on GitHub link (no in-app diff rendering)
  - All DOM content via textContent/createElement — XSS safe, no innerHTML with API data
  - 30s poll stops when switching away from tab

  ## Test plan
  - [ ] PR Review tab appears between Reviews and Repairs in tab bar
  - [ ] Split pane renders — list left, empty detail right
  - [ ] Reviewed PRs show coloured verdict badge + summary + issues
  - [ ] Pending PRs show Analyze Now button
  - [ ] Merge PR: confirm dialog shown, POST to merge route
  - [ ] View Diff on GitHub opens correct URL in new tab
  - [ ] Switching tabs stops 30s poll (no more console requests)
  - [ ] No console errors

  🤖 Generated with [Claude Code](https://claude.ai/claude-code)
  EOF
  )"
  ```

- [ ] **Step 2: Update Dev HQ**

  ```
  mcp complete_task #1801
  mcp update_project_understanding #247
  ```
