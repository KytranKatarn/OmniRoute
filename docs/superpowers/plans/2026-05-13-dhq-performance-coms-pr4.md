# DHQ Performance Colour Coding + COMs Data Fix — Implementation Plan (PR 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add success-rate colour coding to Performance tab metric cards, and fix the COMs tab 4 metric stats that permanently show "—" due to a JavaScript hook overwrite bug.

**Architecture:** Two independent frontend-only fixes — (1) CSS + JS rendering change in `loadPerformance()` to inject colour classes based on computed success rate; (2) a template fix at line 1822 that restores the COMs `onLcarsTabSwitch` hook chain which is overwritten on every page load. No backend changes, no migrations.

**Tech Stack:** Vanilla JS, LCARS CSS (`dhq-` prefix), Flask/Jinja2 template. Data layer is already correct — both bugs are pure frontend.

---

## File Map

| File | Lines Touched | Change |
|---|---|---|
| `platform_v2/tools/department_hq/static/css/department-hq.css` | After line 578 | Add 3 colour override classes |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Lines 647-658, line 124 | Replace card loop; add `'coms'` loaders entry |
| `platform_v2/tools/department_hq/templates/department_hq.html` | Line 1822 + COMs IIFE | Chain hook + expose `_comsLoad` |

---

## Task 1: Performance CSS — Add Colour Override Classes

**Files:**
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css` (after line 578)

- [ ] **Step 1: Read lines 566–580 to confirm the existing `.dhq-perf-metric-val` block**

Confirm `.dhq-perf-metric-val` ends around line 571 and `.dhq-perf-metric-label` ends around line 578.

- [ ] **Step 2: Append three CSS classes after line 578**

```css
/* Performance metric colour coding — success rate thresholds */
.dhq-perf-val-warn {
    color: #fbbf24 !important; /* amber — success rate 50–79% */
}
.dhq-perf-val-bad {
    color: #f87171 !important; /* red — success rate < 50% */
}
.dhq-perf-val-failed {
    color: #f87171 !important; /* red — applied to Failed count when > 0 */
}
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/static/css/department-hq.css
git commit -m "style(dhq): add perf metric colour classes — amber warn, red bad/failed"
```

---

## Task 2: Performance JS — Inject Colour Classes in loadPerformance()

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js:647-658, 124`

The `/api/performance` endpoint already returns `live_jobs_7d`, `live_completed_7d`, `live_failed_7d` per department — no backend changes needed.

- [ ] **Step 1: Read lines 647–660 to see the current card loop**

Confirm the loop structure — it builds `html +=` string with hardcoded `dhq-perf-metric-val` class on every value span.

- [ ] **Step 2: Replace the card loop (lines 647–658)**

Replace the existing loop body with a version that computes `rate` and injects colour classes:

```javascript
        for (var i = 0; i < data.departments.length; i++) {
            var m = data.departments[i];
            var jobs = m.live_jobs_7d || m.jobs_completed || 0;
            var completed = m.live_completed_7d || m.jobs_completed || 0;
            var failed = m.live_failed_7d || m.jobs_failed || 0;
            var rate = jobs > 0 ? completed / jobs : 1;
            var rateClass = rate >= 0.8 ? '' : rate >= 0.5 ? ' dhq-perf-val-warn' : ' dhq-perf-val-bad';
            var failClass = failed > 0 ? ' dhq-perf-val-failed' : '';
            html += '<div class="dhq-perf-card" style="--card-accent:' + floorColor(m.floor || '') + '">'
                + '<div class="dhq-perf-dept">' + esc(m.department) + '</div>'
                + '<div class="dhq-perf-metrics">'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + jobs + '</span><span class="dhq-perf-metric-label">Jobs (7d)</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val' + rateClass + '">' + completed + '</span><span class="dhq-perf-metric-label">Completed</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val' + failClass + '">' + failed + '</span><span class="dhq-perf-metric-label">Failed</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.live_avg_ms_7d || m.avg_response_ms || '—') + '</span><span class="dhq-perf-metric-label">Avg ms</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.sessions_completed || 0) + '</span><span class="dhq-perf-metric-label">Sessions</span></div>'
                + '<div class="dhq-perf-metric"><span class="dhq-perf-metric-val">' + (m.creed_score != null ? m.creed_score : '—') + '</span><span class="dhq-perf-metric-label">C.R.E.E.D.</span></div>'
                + '</div></div>';
        }
```

Logic: `rateClass` on Completed span signals completion rate health. `failClass` on Failed span is red whenever any failure exists. When `jobs === 0` (no data), rate defaults to 1 so no colour class applied.

- [ ] **Step 3: Add 'coms' to loaders map (line 124)**

Find the loaders map in `switchTab()`. After the `'approvals'` entry, add before the closing `};`:

```javascript
        'coms':         function() { if (typeof window._comsLoad === 'function') window._comsLoad(); },
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq): performance metric colour coding + COMs loaders map entry"
```

---

## Task 3: COMs Fix — Restore the onLcarsTabSwitch Hook Chain

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:1268-1327, 1822`

**Root cause:** The COMs inline `<script>` IIFE (lines 1268–1327) installs a custom `window.onLcarsTabSwitch` hook that calls `loadComsFeed()`, `loadComsReports()`, etc. But the final script block at line 1822 then overwrites it:

```javascript
window.onLcarsTabSwitch = function(tabId) { switchTab(tabId); };
```

This replaces the COMs hook — so clicking the COMs tab shows the panel but never loads data. All 4 stat elements (`coms-stat-total`, `coms-stat-telegram`, `coms-stat-platform`, `coms-stat-reports`) stay at "—".

- [ ] **Step 1: Read the COMs IIFE (lines 1268–1330)**

Read to understand what `loadComsFeed()`, `loadComsReports()`, `window.loadComsPolicies()`, and `window._startComsInboxPoll()` are called. Note the `comsLoaded` variable scope.

- [ ] **Step 2: Expose window._comsLoad in the COMs IIFE**

Inside the COMs IIFE, after the `window.onLcarsTabSwitch = function(tabId) {...}` assignment (around line 1327), add:

```javascript
    window._comsLoad = function() {
        if (!comsLoaded) {
            loadComsFeed();
            loadComsReports();
            if (typeof window.loadComsPolicies === 'function') window.loadComsPolicies();
            comsLoaded = true;
        }
        if (typeof window._startComsInboxPoll === 'function') window._startComsInboxPoll();
    };
```

- [ ] **Step 3: Chain rather than overwrite at line 1822**

Find line 1822:
```javascript
  window.onLcarsTabSwitch = function(tabId) { switchTab(tabId); };
```

Replace with:
```javascript
  var _comsHook = window.onLcarsTabSwitch || function(){};
  window.onLcarsTabSwitch = function(tabId) { switchTab(tabId); _comsHook(tabId); };
```

This preserves whatever hook the COMs IIFE installed while still wiring the main `switchTab()` dispatcher.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "fix(dhq): restore COMs tab metrics — chain onLcarsTabSwitch, expose window._comsLoad"
```

---

## Task 4: Deploy and Verify

- [ ] **Step 1: Restart**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 5
```

- [ ] **Step 2: Verify Performance colour coding**

Navigate to Performance tab. Confirm:
- Departments with 100% success rate → Completed value is teal (no colour class)
- Departments with 50–79% success rate → Completed value is amber `#fbbf24`
- Departments with <50% success rate → Completed value is red `#f87171`
- Any department with `failed > 0` → Failed count is red
- Jobs, Avg ms, Sessions, C.R.E.E.D. metrics remain teal

- [ ] **Step 3: Verify COMs metrics load**

Navigate to COMs tab. Confirm:
- `coms-stat-total` shows a number (not "—")
- `coms-stat-telegram` shows a number
- `coms-stat-platform` shows a number (0 is valid if no platform messages)
- `coms-stat-reports` shows a number

If any stat still shows "—", check browser console for fetch to `/api/department-hq/api/coms/messages`. If 401, ensure logged in as admin. If 500:
```bash
docker logs --tail 30 archie_platform 2>&1 | grep -i "telegram_message"
```

- [ ] **Step 4: Push and create PR**

```bash
git push origin feat/dispatch-history
gh pr create \
  --title "feat(dhq): performance colour coding + COMs metrics fix (PR 4/5)" \
  --body "$(cat <<'EOF'
## Summary

### Performance Tab — Colour Coding
- Added `.dhq-perf-val-warn` (amber) and `.dhq-perf-val-bad` (red) CSS classes for success rate thresholds
- `.dhq-perf-val-failed` (red) applied to Failed count when > 0
- Card loop in `loadPerformance()` computes `rate = completed / jobs` and injects classes on Completed + Failed spans
- When `jobs === 0`, rate defaults to 1 (no colour applied — no data = healthy assumption)

### COMs Tab — Metrics Fix
**Root cause:** `window.onLcarsTabSwitch` at template line 1822 overwrote the COMs IIFE hook that fires `loadComsFeed()` + `loadComsReports()`.
**Fix:** Chained the hook at line 1822 instead of replacing it. Exposed `window._comsLoad()` wrapper in COMs IIFE for belt-and-suspenders coverage via loaders map.

No migrations. No backend changes.

## Colour Logic
| Metric | Rate | Colour |
|---|---|---|
| Completed | ≥ 80% | teal (default) |
| Completed | 50–79% | amber #fbbf24 |
| Completed | < 50% | red #f87171 |
| Failed | > 0 | red #f87171 |
| Failed | = 0 | teal (default) |

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Merge via /merge-pr**

Use `/merge-pr <PR_NUMBER>` — never `gh pr merge` directly.

---

## Colour Logic Reference

| Metric | Condition | CSS class | Colour |
|---|---|---|---|
| Completed | rate ≥ 0.80 | _(none)_ | teal `#00e5ff` |
| Completed | 0.50 ≤ rate < 0.80 | `dhq-perf-val-warn` | amber `#fbbf24` |
| Completed | rate < 0.50 | `dhq-perf-val-bad` | red `#f87171` |
| Failed | failed > 0 | `dhq-perf-val-failed` | red `#f87171` |
| Failed | failed = 0 | _(none)_ | teal `#00e5ff` |
| All others | always | _(none)_ | teal `#00e5ff` |
