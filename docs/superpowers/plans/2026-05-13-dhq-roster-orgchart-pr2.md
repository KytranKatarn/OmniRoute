# DHQ Roster + Org Chart Merge — Implementation Plan (PR 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the Org Chart tab into the Roster tab as a LIST VIEW / ORG CHART toggle, eliminating a redundant top-level tab while preserving all org chart functionality.

**Architecture:** The `orgChartContent` div is relocated from `panel-org-chart` into a proxy container inside `panel-roster`. Since `loadOrgChart()` (JS line 243) targets `document.getElementById('orgChartContent')` directly, moving the div — not the function — means zero changes to data-loading logic. The Org Chart tab button is hidden via CSS (`[data-tab="org-chart"]`); the `panel-org-chart` shell is also hidden. A new `toggleRosterView(view)` function switches between sub-views within the roster panel.

**Tech Stack:** Jinja2 HTML template, vanilla JavaScript, CSS (`department-hq.css`, `dhq-` prefix).

---

## Files Modified

| File | Change |
|---|---|
| `platform_v2/tools/department_hq/templates/department_hq.html` | Defuse original orgChartContent (line 71); insert toggle bar + proxy div (between lines 109-110) |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Add `toggleRosterView()`; remove `'org-chart'` from loaders map (line 114); reset on roster tab switch |
| `platform_v2/tools/department_hq/static/css/department-hq.css` | Hide tab button + panel; add toggle bar styles |

**Key line references (verified from source):**
- Template: tab array lines 27–42, `orgChartContent` at line 71, roster controls close at line 109, `rosterContent` at line 110
- JS: loaders map lines 112–125, `'org-chart': loadOrgChart` at line 114, `setRosterView` ends at line 332
- CSS: accent `#00e5ff`, prefix `dhq-`

---

## Task 1: CSS — Hide Org Chart Tab + Panel, Add Toggle Bar Styles

**Files:**
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css`

- [ ] **Step 1: Verify no existing lcars-header-tab selector in this file**

```bash
grep -n "lcars-header-tab" /mnt/archie_brain/platform_v2/tools/department_hq/static/css/department-hq.css
```

Expected: 0 results before your addition (the class is defined in `lcars-header.css`, not this file).

- [ ] **Step 2: Append CSS block at the end of the file**

```css
/* ── PR 2: Org Chart merged into Roster ─────────────────────── */
.lcars-header-tab[data-tab="org-chart"] { display: none !important; }
#panel-org-chart { display: none !important; }

.dhq-roster-view-bar {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 12px; padding: 6px 10px;
    background: var(--dhq-surface-2, #141b24);
    border: 1px solid var(--dhq-border, #1e293b);
    border-radius: 8px;
}
.dhq-roster-view-bar-btn {
    font-family: 'Antonio', sans-serif; font-size: 0.75rem;
    letter-spacing: 1.5px; text-transform: uppercase;
    padding: 4px 14px; border-radius: 6px;
    border: 1px solid var(--dhq-border, #1e293b);
    background: transparent; color: var(--dhq-text-dim, #94a3b8);
    cursor: pointer; transition: all 0.15s ease;
}
.dhq-roster-view-bar-btn.active,
.dhq-roster-view-bar-btn:hover {
    background: var(--dhq-accent, #00e5ff); color: #010409;
    border-color: var(--dhq-accent, #00e5ff);
}
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/static/css/department-hq.css
git commit -m "style(dhq): hide org-chart tab button and panel, add roster view-bar styles (PR 2)"
```

---

## Task 2: HTML — Relocate orgChartContent + Add Toggle Bar

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:71, 109-110`

- [ ] **Step 1: Defuse the original orgChartContent div (line 71)**

Line 71 currently reads:
```html
<div id="orgChartContent" class="dhq-loading">Loading org chart...</div>
```

Change to:
```html
<div id="orgChartContent-legacy" class="dhq-loading"></div>
```

This prevents a duplicate-id conflict. The element is inside `#panel-org-chart` which is CSS-hidden and never queried.

- [ ] **Step 2: Insert toggle bar + proxy div between lines 109 and 110**

Line 109 is the closing `</div>` of `.dhq-roster-controls`. Line 110 is `<div id="rosterContent" class="dhq-loading">`. Insert between them:

```html
    <!-- Roster / Org Chart view toggle (PR 2) -->
    <div class="dhq-roster-view-bar">
      <button class="dhq-roster-view-bar-btn active" data-rosterview="list"
              onclick="toggleRosterView('list')">LIST VIEW</button>
      <button class="dhq-roster-view-bar-btn" data-rosterview="org-chart"
              onclick="toggleRosterView('org-chart')">ORG CHART</button>
    </div>
    <!-- Proxy div: loadOrgChart() targets #orgChartContent here (PR 2) -->
    <div id="rosterOrgChartProxy" style="display:none;">
      <div id="orgChartContent" class="dhq-loading">Loading org chart...</div>
    </div>
```

- [ ] **Step 3: Verify exactly one orgChartContent exists**

```bash
grep -c 'id="orgChartContent"' /mnt/archie_brain/platform_v2/tools/department_hq/templates/department_hq.html
```

Expected: `1` (the proxy div; the original at line 71 now has id `orgChartContent-legacy`).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): relocate orgChartContent into roster proxy div, add view toggle bar (PR 2)"
```

---

## Task 3: JS — toggleRosterView + Remove Dead Loader + Tab Reset

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

- [ ] **Step 1: Remove dead org-chart entry from loaders map (line 114)**

Find and delete this line from the loaders map inside `switchTab()`:
```javascript
'org-chart':    loadOrgChart,
```

The loaders map should no longer contain an `'org-chart'` key.

- [ ] **Step 2: Reset roster view when Roster tab activates**

Inside `switchTab()`, after the `if (tab === 'approvals') { ... } else if (!loaded[tab] && loaders[tab]) { loaders[tab](); }` block (around lines 127–131), add:

```javascript
    // PR 2: reset roster to LIST VIEW when navigating to the roster tab
    if (tab === 'roster') {
        if (typeof toggleRosterView === 'function') toggleRosterView('list');
    }
```

Insert after the closing `}` of the loader block, before the dispatch history init comment.

- [ ] **Step 3: Add toggleRosterView function after line 332**

Line 332 is the closing `}` of `setRosterView`. Insert immediately after it:

```javascript
// ── PR 2: Toggle between list view and org chart within the roster panel ──
function toggleRosterView(view) {
    var listEl  = document.getElementById('rosterContent');
    var chartEl = document.getElementById('rosterOrgChartProxy');
    var isChart = (view === 'org-chart');

    if (listEl)  listEl.style.display  = isChart ? 'none' : '';
    if (chartEl) chartEl.style.display = isChart ? ''     : 'none';

    document.querySelectorAll('.dhq-roster-view-bar-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.rosterview === view);
    });

    // Load on first open — loadOrgChart() writes to #orgChartContent in the proxy div
    if (isChart && !loaded['org-chart']) {
        loadOrgChart();
    }
}
```

- [ ] **Step 4: Verify**

```bash
grep -n "toggleRosterView" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js
```

Expected: 2 results (function definition + tab-switch reset call).

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq): add toggleRosterView(), remove dead org-chart loader, reset on tab switch (PR 2)"
```

---

## Task 4: Deploy, Verify, and Open PR

- [ ] **Step 1: Restart**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 5
```

- [ ] **Step 2: Visual verification checklist**

Navigate to `http://192.168.1.200:3000/tools/department-hq`:

- [ ] "Org Chart" tab button is **absent** from the tab bar
- [ ] Roster tab shows agent grid with LIST VIEW button active by default
- [ ] Toggle bar ("LIST VIEW" / "ORG CHART") appears below the filter controls
- [ ] Clicking "ORG CHART" hides the agent grid and renders the org chart hierarchy
- [ ] Clicking "LIST VIEW" returns to the agent grid
- [ ] Switching to another tab and back to Roster resets to LIST VIEW
- [ ] No JS console errors
- [ ] `document.querySelectorAll('#orgChartContent').length === 1` in browser console

- [ ] **Step 3: Push and create PR**

```bash
git push origin feat/dispatch-history
gh pr create \
  --title "feat(dhq): merge Org Chart tab into Roster as view toggle (PR 2/5)" \
  --body "$(cat <<'EOF'
## Summary
- Hides the standalone Org Chart tab button via CSS (`[data-tab="org-chart"]`)
- Relocates `#orgChartContent` into a proxy div inside `panel-roster` — `loadOrgChart()` requires zero changes (still targets the same element ID)
- Adds LIST VIEW / ORG CHART toggle bar to Roster tab
- Roster tab resets to LIST VIEW when navigating away and back
- Part of DHQ reorganization series (PR 2 of 5)

## Files
- `department_hq.html` — lines 71, 109-110
- `department-hq.js` — line 114 (remove dead loader), line ~332 (add toggleRosterView)
- `department-hq.css` — append toggle bar + hide rules

## Test Plan
- [ ] Org Chart tab button not visible
- [ ] Roster LIST VIEW works
- [ ] ORG CHART toggle shows hierarchy data
- [ ] No duplicate IDs in DOM
- [ ] No JS console errors

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge via /merge-pr**

Use `/merge-pr <PR_NUMBER>` — never `gh pr merge` directly.
