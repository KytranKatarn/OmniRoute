# DHQ Dispatch Cleanup + Autonomy Tab — Implementation Plan (PR 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean the Dispatch tab from 21,514px to ~3,500px by removing dead sections, moving 3 sections to a new Autonomy tab, compacting Ollama Engine to chips, reordering sections, and fixing mobile table overflow.

**Architecture:** All changes are in `department_hq.html` (HTML), `department-hq.js` (tab loader), and `department-hq.css` (compact Ollama style + overflow fix). No backend changes. No new routes. The Autonomy tab reuses existing data endpoints that already populate the moved sections.

**Tech Stack:** Jinja2 HTML templates, vanilla JS, CSS. Platform is Flask in Docker at 192.168.1.200:3000. Restart: `docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform`.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `platform_v2/tools/department_hq/templates/department_hq.html` | Modify | Remove 2 sections, move 4 sections, add Autonomy tab + panel, reorder Dispatch sections |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | Modify | Add `loadAutonomy()` + add `'autonomy'` to loaders map + DOM-safe `renderWorkloadTable()` |
| `platform_v2/tools/department_hq/static/css/department-hq.css` | Modify | Ollama compact chip styles + global table overflow fix |

**Key file facts (current state, on branch feat/dispatch-history):**
- `department_hq.html` — 1,810 lines total
- `panel-dispatch` — lines 209–388
- `panel-fleet` — lines 390–464
- Tab buttons — lines 27–44
- Section container CSS class: `dhq-dispatch-section`

---

## Task 1: Remove ACTIVE BRIDGE JOBS and REPAIR PIPELINE

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html:226-230, 351-355`

- [ ] **Step 1: Read both sections to confirm content**

Read lines 224–232 and 349–357 of `department_hq.html`. Confirm both are self-contained `dhq-dispatch-section` divs.

- [ ] **Step 2: Check for JS references before deleting**

```bash
grep -n "dispatchJobCount\|dispatchJobsContent\|dispatchRepairContent" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js | head -20
```

If found, note the line numbers — remove those JS lines too.

- [ ] **Step 3: Delete ACTIVE BRIDGE JOBS section**

Remove the block starting with `<!-- Active Bridge Jobs -->` at ~line 225 — the full `<div class="dhq-dispatch-section">` through its closing `</div>`. It contains a `dhq-section-title` with "ACTIVE BRIDGE JOBS" and a div with id `dispatchJobsContent`.

- [ ] **Step 4: Delete REPAIR PIPELINE section**

Remove the block with "REPAIR PIPELINE" title and its `dispatchRepairContent` div.

- [ ] **Step 5: Remove any dangling JS references found in Step 2**

For each line found in Step 2, read the surrounding context and remove only the lines that reference the deleted element IDs. Do not remove functions that also serve other purposes.

- [ ] **Step 6: Restart and verify sections are gone**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Navigate to `http://192.168.1.200:3000/tools/department-hq?tab=dispatch`. Confirm neither "ACTIVE BRIDGE JOBS" nor "REPAIR PIPELINE" appear.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq-dispatch): remove Active Bridge Jobs and Repair Pipeline dead sections"
```

---

## Task 2: Move SCHEDULER JOBS + AUTONOMY CONFIG + JOBS BY DEPT Out of Dispatch

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

- [ ] **Step 1: Read the 3 sections from panel-dispatch**

Read the current file starting at what is now ~line 341 (after Task 1 shift). Find and copy the exact HTML for:
- SCHEDULER JOBS (the `dhq-dispatch-section` with "SCHEDULER JOBS" or "AUTONOMY LOOP JOBS" title)
- AUTONOMY CONFIGURATION section
- JOBS BY DEPARTMENT section

Save these 3 HTML blocks — you'll paste them into the Autonomy panel in Task 4.

- [ ] **Step 2: Find JS references for the moved sections**

```bash
grep -n "dispatchLoopCount\|dispatchLoopContent\|dispatchAutonomyConfig\|dispatchJobsByDept" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js | head -20
```

Note the lines. The JS that populates these IDs will be reused in `loadAutonomy()` (Task 5) — do NOT remove it yet.

- [ ] **Step 3: Delete the 3 sections from panel-dispatch**

Remove all three `<div class="dhq-dispatch-section">` blocks for SCHEDULER JOBS, AUTONOMY CONFIGURATION, and JOBS BY DEPARTMENT from inside `panel-dispatch`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq-dispatch): move Scheduler Jobs + Autonomy Config + Jobs By Dept out of Dispatch"
```

---

## Task 3: Move SYSTEM COMPONENTS to Fleet Panel

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

- [ ] **Step 1: Read and cut the SYSTEM COMPONENTS section**

Find the SYSTEM COMPONENTS `dhq-dispatch-section` block in `panel-dispatch` (currently ~line 333 before Task shifts). Read its exact HTML. Remove it from `panel-dispatch`.

- [ ] **Step 2: Append to panel-fleet**

Find the closing `</div>` tag of `panel-fleet` (currently ~line 464, shifted after earlier tasks). Insert just before it:

```html
      <!-- System Components (moved from Dispatch — infrastructure belongs with Fleet) -->
      [PASTE THE EXACT HTML CUT IN STEP 1]
```

- [ ] **Step 3: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

1. Dispatch tab → SYSTEM COMPONENTS is gone
2. Fleet tab → SYSTEM COMPONENTS section appears at the bottom

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): move System Components from Dispatch to Fleet panel"
```

---

## Task 4: Add Autonomy Tab Button + Panel

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`

- [ ] **Step 1: Read the Fleet tab button to copy its structure**

Read lines 27–44 (tab buttons area). Find the Fleet tab button — it uses class `dhq-tab lcars-header-tab` with a `data-tab` attribute. Copy its structure exactly.

- [ ] **Step 2: Add the Autonomy tab button before Fleet**

Insert a new tab button immediately before the Fleet button, using the same class pattern:

```html
<button class="dhq-tab lcars-header-tab" data-tab="autonomy" onclick="switchTab('autonomy')">
  <svg class="dhq-tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
  </svg>
  <span>Autonomy</span>
  <span class="dhq-tab-short">AUTO</span>
</button>
```

If the Fleet tab button uses different inner structure (e.g. a span instead of SVG), match that pattern exactly.

- [ ] **Step 3: Add the Autonomy panel**

Find where `panel-dispatch` ends and `panel-fleet` begins. Insert a new panel between them:

```html
<!-- AUTONOMY TAB PANEL -->
<div id="panel-autonomy" class="dhq-panel" style="display:none;">
  <div class="dhq-panel-header">
    <span>AUTONOMY</span>
    <span class="dhq-panel-tag">SCHEDULER</span>
    <div class="dhq-panel-dots"><span></span><span></span><span></span></div>
  </div>

  [PASTE SCHEDULER JOBS SECTION HTML FROM TASK 2 STEP 1]

  [PASTE AUTONOMY CONFIGURATION SECTION HTML FROM TASK 2 STEP 1]

  [PASTE JOBS BY DEPARTMENT SECTION HTML FROM TASK 2 STEP 1]

</div>
<!-- END AUTONOMY TAB PANEL -->
```

Check what `dhq-panel-header`/`dhq-panel-tag` look like in the Dispatch panel header and match that exact structure.

- [ ] **Step 4: Restart and verify tab button and panel appear**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Navigate to `http://192.168.1.200:3000/tools/department-hq`. Confirm:
- "Autonomy" tab button appears between Dispatch and Fleet
- Clicking it opens a panel (may show "Loading..." — JS not wired yet)

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat(dhq): add Autonomy tab button and panel with moved sections"
```

---

## Task 5: Wire Autonomy Tab in JS

**Files:**
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

- [ ] **Step 1: Find the loaders map in switchTab()**

```bash
grep -n "loaders\s*=" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js | head -5
```

Read the loaders map. Note the `'dispatch': loadDispatch` entry pattern.

- [ ] **Step 2: Find what JS populates the moved element IDs**

```bash
grep -n "dispatchLoopContent\|dispatchAutonomyConfig\|dispatchJobsByDept" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js | head -20
```

Note the function calls or fetch blocks that write to these IDs. These are the calls `loadAutonomy()` will invoke.

- [ ] **Step 3: Add 'autonomy' to the loaders map**

Inside `switchTab()`, find the `loaders` object and add:

```javascript
'autonomy': loadAutonomy,
```

- [ ] **Step 4: Add loadAutonomy() function**

After the `loadDispatch()` function definition, add:

```javascript
function loadAutonomy() {
    // Reuses the same fetch calls that previously ran inside loadDispatch().
    // The element IDs (dispatchLoopContent etc.) are unchanged — same JS, new panel location.
    var loopEl = document.getElementById('dispatchLoopContent');
    var configEl = document.getElementById('dispatchAutonomyConfig');
    var deptEl = document.getElementById('dispatchJobsByDept');

    if (loopEl && loopEl.textContent.trim().includes('Loading')) {
        loadSchedulerJobs();   // Replace with actual function name from Step 2
    }
    if (configEl && configEl.textContent.trim().includes('Loading')) {
        loadAutonomyConfig();  // Replace with actual function name from Step 2
    }
    if (deptEl && deptEl.textContent.trim().includes('Loading')) {
        loadJobsByDepartment(); // Replace with actual function name from Step 2
    }
    loaded['autonomy'] = true;
}
```

Replace `loadSchedulerJobs()`, `loadAutonomyConfig()`, `loadJobsByDepartment()` with the actual function names you found in Step 2. If the data is fetched inline (not in a named function), replicate the fetch call directly.

- [ ] **Step 5: Restart and verify Autonomy tab loads data**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Click the Autonomy tab. Confirm Scheduler Jobs populates (shows job list rows, not "Loading..."). Check the browser console for JS errors if it stays on "Loading...".

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq): wire Autonomy tab loader, add loadAutonomy() function"
```

---

## Task 6: Compact Ollama Engine + Reorder Dispatch Sections

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css`

- [ ] **Step 1: Read the Ollama ENGINE section**

Read the OLLAMA ENGINE `dhq-dispatch-section` block. Note the exact IDs of the value spans (`podModelsLoaded`, `podRamUsed`, `podSlots`, `podAvailable` — or whatever the actual IDs are). These must be preserved so the existing JS continues to populate them.

- [ ] **Step 2: Replace Ollama section with compact chips**

Replace the entire inner content of the Ollama `dhq-dispatch-section` (keep the outer div wrapper) with:

```html
      <div class="dhq-dispatch-section dhq-ollama-compact">
        <div class="dhq-section-title">DISPATCH CENTER</div>
        <div class="dhq-ollama-chips">
          <span class="dhq-chip">
            <span class="dhq-chip-dot" id="ollamaStatusDot">&#9679;</span>
            <span id="podModelsLoaded">--</span> loaded
          </span>
          <span class="dhq-chip-sep">&#183;</span>
          <span class="dhq-chip"><span id="podRamUsed">--</span> RAM</span>
          <span class="dhq-chip-sep">&#183;</span>
          <span class="dhq-chip"><span id="podSlots">--</span> slots</span>
          <span class="dhq-chip-sep">&#183;</span>
          <span class="dhq-chip"><span id="podAvailable">--</span> available</span>
        </div>
      </div>
```

Use the exact element IDs you found in Step 1 — `podModelsLoaded` etc. are placeholders; use the real IDs.

- [ ] **Step 3: Add compact chips CSS**

Append to `platform_v2/tools/department_hq/static/css/department-hq.css`:

```css
/* Ollama compact chips */
.dhq-ollama-compact { padding: 0.4rem 0.75rem !important; }
.dhq-ollama-chips {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    font-size: 0.75rem;
    font-family: 'IBM Plex Mono', monospace;
    color: var(--archie-palette-teal-300, #5eead4);
    margin-top: 0.2rem;
}
.dhq-chip { display: inline-flex; align-items: center; gap: 0.25rem; }
.dhq-chip-sep { opacity: 0.3; }
.dhq-chip-dot { font-size: 0.6rem; }
```

- [ ] **Step 4: Reorder Dispatch sections**

After the cleanup from Tasks 1–3, the remaining sections in `panel-dispatch` are in this order:
1. OLLAMA ENGINE (now chips)
2. AGENT WORKLOAD BY DEPARTMENT
3. DISPATCH METRICS (24H)
4. CLAUDE REQUESTS
5. DISPATCH HISTORY (id="dispatch-history")
6. DISPATCH TRAFFIC (id="trafficPanelSection")

Cut-and-paste to achieve this target order:
1. OLLAMA CHIPS (already top)
2. DISPATCH METRICS (24H) ← move up from position 3
3. AGENT WORKLOAD BY DEPARTMENT ← move down from position 2
4. CLAUDE REQUESTS
5. DISPATCH TRAFFIC ← move up from position 6
6. DISPATCH HISTORY ✨ ← stays at bottom

- [ ] **Step 5: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Navigate to Dispatch tab. Confirm:
- Top: "DISPATCH CENTER" with inline chips (values populate from Ollama)
- Second: DISPATCH METRICS 24H cards
- No Scheduler Jobs, no Repair Pipeline, no Active Bridge Jobs
- Dispatch Traffic appears above Dispatch History

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html platform_v2/tools/department_hq/static/css/department-hq.css
git commit -m "feat(dhq-dispatch): compact Ollama to chips, reorder sections (Metrics up, Traffic up)"
```

---

## Task 7: Compact Agent Workload to Collapsible Table

**Files:**
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html`
- Modify: `platform_v2/tools/department_hq/static/js/department-hq.js`

- [ ] **Step 1: Find the workload render function**

```bash
grep -n "dispatchWorkloadContent\|workload" /mnt/archie_brain/platform_v2/tools/department_hq/static/js/department-hq.js | head -20
```

Find the JS that populates `dispatchWorkloadContent`. Note the data structure (field names for department name and agent count).

- [ ] **Step 2: Update the HTML container to be collapsible**

In the AGENT WORKLOAD section of `panel-dispatch`, change the section to start collapsed:

```html
      <div class="dhq-dispatch-section">
        <div class="dhq-section-title" onclick="toggleWorkload()" style="cursor:pointer;">
          AGENT WORKLOAD BY DEPARTMENT
          <span id="workloadToggleIcon" style="opacity:0.5;font-size:0.7rem;margin-left:0.5rem">&#9660; expand</span>
        </div>
        <div id="dispatchWorkloadContent" style="display:none;"></div>
      </div>
```

- [ ] **Step 3: Add toggleWorkload() function**

Add after `loadAutonomy()` in `department-hq.js`:

```javascript
function toggleWorkload() {
    var el = document.getElementById('dispatchWorkloadContent');
    var icon = document.getElementById('workloadToggleIcon');
    if (!el) return;
    var isHidden = el.style.display === 'none' || el.style.display === '';
    el.style.display = isHidden ? 'block' : 'none';
    if (icon) icon.textContent = isHidden ? '▲ collapse' : '▼ expand';
}
```

- [ ] **Step 4: Replace the workload render function with a DOM-safe table**

Find the existing render function for `dispatchWorkloadContent` (from Step 1). Replace its output logic with a DOM-built table — all user data via `textContent`, no string concatenation into markup:

```javascript
function renderWorkloadTable(departments) {
    var container = document.getElementById('dispatchWorkloadContent');
    if (!container) return;
    // Clear safely
    while (container.firstChild) container.removeChild(container.firstChild);

    if (!departments || !departments.length) {
        var empty = document.createElement('p');
        empty.textContent = 'No workload data';
        empty.style.opacity = '0.5';
        container.appendChild(empty);
        return;
    }

    var table = document.createElement('table');
    table.style.cssText = 'width:100%;font-size:0.75rem;border-collapse:collapse;';

    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    hrow.style.cssText = 'opacity:0.5;font-size:0.65rem;';
    var th1 = document.createElement('th');
    th1.textContent = 'DEPARTMENT';
    th1.style.cssText = 'text-align:left;padding:3px 8px;';
    var th2 = document.createElement('th');
    th2.textContent = 'AGENTS';
    th2.style.cssText = 'text-align:right;padding:3px 8px;';
    hrow.appendChild(th1);
    hrow.appendChild(th2);
    thead.appendChild(hrow);
    table.appendChild(thead);

    var tbody = document.createElement('tbody');
    departments.forEach(function (d) {
        var tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid rgba(255,255,255,0.06)';
        var td1 = document.createElement('td');
        td1.textContent = d.name || d.department || '';  // use actual field name
        td1.style.padding = '3px 8px';
        var td2 = document.createElement('td');
        td2.textContent = String(d.agent_count || d.agents || d.count || 0);
        td2.style.cssText = 'padding:3px 8px;text-align:right;color:var(--archie-palette-teal-300,#5eead4);';
        tr.appendChild(td1);
        tr.appendChild(td2);
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
}
```

Adjust `d.name`, `d.agent_count` etc. to match the actual field names in the data from Step 1.

Replace the existing render call inside the workload loader with `renderWorkloadTable(data)`.

- [ ] **Step 5: Restart and verify**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 4
```

Navigate to Dispatch tab. Confirm Agent Workload shows collapsed with "▼ expand". Click it — confirm a compact 2-column table renders with department names and agent counts as plain text.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/department_hq/templates/department_hq.html platform_v2/tools/department_hq/static/js/department-hq.js
git commit -m "feat(dhq-dispatch): compact Agent Workload to collapsible DOM-safe table"
```

---

## Task 8: Global Table Overflow Fix (Fold 5 / Mobile)

**Files:**
- Modify: `platform_v2/tools/department_hq/static/css/department-hq.css`

- [ ] **Step 1: Append overflow rules to CSS**

```css
/* Mobile / Fold 5 table overflow fix */
.dhq-dispatch-section,
.dhq-section {
    overflow-x: auto;
}
.dhq-dispatch-section table,
.dhq-section table {
    min-width: 480px;
}
```

- [ ] **Step 2: Verify at narrow viewport**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform && sleep 3
```

In Playwright, navigate to Autonomy tab at 480px width and confirm the Scheduler Jobs table scrolls horizontally instead of overflowing:

```javascript
// Run in browser console or Playwright:
document.querySelector('[data-tab="autonomy"]').click();
// The table should be contained and scrollable, not overflowing the right edge
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/department_hq/static/css/department-hq.css
git commit -m "fix(dhq): add overflow-x:auto to section containers for Fold 5 / mobile"
```

---

## Task 9: PR + Merge

- [ ] **Step 1: Run regression tests**

```bash
docker exec archie_platform python3 -m pytest /app/tests/test_dispatch_history_routes.py -v 2>&1 | tail -10
```

Expected: all 9 tests pass.

- [ ] **Step 2: Visual verification checklist**

| Tab | Check |
|---|---|
| Dispatch | Compact chips at top, Metrics second, Traffic before History, no Scheduler Jobs, no Repair Pipeline, no Active Bridge Jobs, no System Components |
| Autonomy | Tab visible between Dispatch and Fleet, data loads (not Loading...) |
| Fleet | System Components section present at bottom |
| Any tab | No JS console errors on load |

- [ ] **Step 3: Push and create PR**

```bash
git push origin feat/dispatch-history
gh pr create \
  --title "feat(dhq): Dispatch cleanup + Autonomy tab (PR 1/5)" \
  --body "$(cat <<'EOF'
## Summary
- Removes Active Bridge Jobs (always 0) and Repair Pipeline (belongs in Repair Bay)
- Moves Scheduler Jobs (181) + Autonomy Config + Jobs By Dept to new Autonomy tab
- Moves System Components to Fleet tab
- Compacts Ollama Engine from 4 large cards to inline chip row
- Moves Dispatch Metrics to top, Dispatch Traffic up above History
- Compacts Agent Workload to collapsible 2-column table (DOM-safe, no innerHTML)
- Adds overflow-x:auto to all section containers (Fold 5 mobile fix)
- Dispatch tab: 21,514px to ~3,500px

## Test Plan
- [x] 9/9 dispatch history route tests pass
- [ ] Dispatch: compact chips, Metrics top, no dead sections
- [ ] Autonomy: tab visible, data loads
- [ ] Fleet: System Components at bottom
- [ ] 480px viewport: Scheduler Jobs table scrolls horizontally

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge via /merge-pr**

Use `/merge-pr <PR_NUMBER>` — never `gh pr merge` directly.

---

## Notes

- `loadAutonomy()` in Task 5 reuses the same function calls as `loadDispatch()` — no new API endpoints
- Element IDs (`dispatchLoopContent`, `dispatchAutonomyConfig`, `dispatchJobsByDept`) are unchanged — same JS works in the new Autonomy panel location
- Scheduler Jobs pagination (full 25/page JS) is a follow-up; this PR just moves the section and fixes the overflow
- PRs 2–5 cover: Roster+OrgChart merge, Contractors+Fleet swap, Performance colours+COMs fix, Online Presence Coming Soon
