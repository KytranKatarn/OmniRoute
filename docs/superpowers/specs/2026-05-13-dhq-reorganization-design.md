# DHQ Reorganization — Design Spec
**Date:** 2026-05-13
**Status:** Approved
**Scope:** Full Department HQ tab-by-tab content reorganization

---

## Problem

The DHQ module has 14 tabs with content in the wrong places:
- Dispatch tab is 21,514px tall because 181 scheduler jobs render unpaganated
- Table columns overflow off-screen on mobile/Fold 5 (no `overflow-x:auto`)
- Autonomy loop jobs, repair pipeline, and system components live in Dispatch but belong elsewhere
- Org Chart and Roster duplicate agent data — two tabs for one dataset
- COMs metrics are empty — data feed broken
- Online Presence is an empty stub shown as a real tab
- Contractors (Tier 3 cloud AI) lacks its Provider Budgets which are buried in Fleet

---

## Goals

- Dispatch tab: 21,514px → ~3,500px focused on dispatch activity only
- Create a proper "Autonomy" tab home for scheduler jobs, autonomy config, jobs by dept
- Merge Org Chart into Roster as a view toggle (net: same 14 tabs after adding Autonomy)
- Fix all table overflow (Fold 5 / mobile)
- Fix COMs data feed
- Mark Online Presence as Coming Soon
- Move content to its conceptually correct tab

---

## Tab Count: Stays at 14

Old 14 → remove Org Chart (merged) → add Autonomy tab = new 14.

---

## Changes by Tab

### 1. Roster — absorbs Org Chart

**File:** `platform_v2/tools/department_hq/templates/department_hq.html` (roster panel)

Add a view toggle button in the Roster panel header: `[LIST VIEW] [ORG CHART]`

- **LIST VIEW** (default): existing agent card grid — no change
- **ORG CHART**: show the existing org chart HTML (currently in `panel-org-chart`) inline within the Roster panel via JS swap

The `panel-org-chart` tab and button are hidden (`display:none`) in the tab bar. The org chart content stays in the DOM but is moved inside the roster panel and toggled by JS.

**JS change** (`department-hq.js`): add `toggleRosterView(view)` — switches between `#rosterContent` (list) and `#rosterOrgContent` (chart).

**Tab bar change**: Hide the Org Chart tab button (do not delete — content stays for the toggle).

---

### 2. Dispatch — Major Cleanup

**File:** `platform_v2/tools/department_hq/templates/department_hq.html` (dispatch panel)

**REMOVE these sections entirely** (delete HTML blocks):
- `ACTIVE BRIDGE JOBS` — always shows 0, count merges into Dispatch Metrics badge
- `REPAIR PIPELINE` — belongs in Repair Bay, not DHQ

**MOVE these sections** (cut from Dispatch, paste into Autonomy):
- `SCHEDULER JOBS (181)` → Autonomy tab
- `AUTONOMY CONFIGURATION` → Autonomy tab
- `JOBS BY DEPARTMENT` → Autonomy tab

**MOVE to Fleet:**
- `SYSTEM COMPONENTS` → Fleet panel (append at bottom)

**COMPACT:**
- `OLLAMA ENGINE`: Replace 4 full-height cards with inline chips row. Format: `● 3 loaded · 11.1 GB RAM · 3 slots · 23 available`. CSS: single flex row, small font, no card borders.
- `DISPATCH METRICS (24H)`: Move to TOP of Dispatch panel (immediately after the compact Ollama chips). Keep the 5 metric cards but reduce card height.
- `AGENT WORKLOAD BY DEPARTMENT`: Replace big box grid with a compact 2-column table (Dept name | Agent count). Add `overflow-x:auto` wrapper. Collapsible (default: collapsed with toggle to expand).

**REORDER remaining sections** (top → bottom after cleanup):
1. Ollama chips (compact, inline)
2. Dispatch Metrics 24H (moved up from position 4)
3. Claude Requests
4. Dispatch Traffic (moved up from buried bottom)
5. Dispatch History ✨

**Table overflow fix (ALL tables in Dispatch panel):**
Wrap every `<table>` inside a `<div style="overflow-x:auto;">` container.

---

### 3. New "Autonomy" Tab

**File:** `platform_v2/tools/department_hq/templates/department_hq.html`

Add new tab button between Dispatch and Fleet:
```html
<button class="dhq-tab" data-tab="autonomy">
  <span class="dhq-tab-icon">⚙</span> Autonomy
  <span class="dhq-tab-short">AUTO</span>
</button>
```

Add panel `id="panel-autonomy"` containing:
1. **SCHEDULER JOBS** — moved from Dispatch. Add pagination: 25 rows/page, Prev/Next buttons, page indicator. Add `overflow-x:auto` on table. Filter bar: department dropdown + status filter.
2. **JOBS BY DEPARTMENT** — moved from Dispatch (unchanged content)
3. **AUTONOMY CONFIGURATION** — moved from Dispatch (unchanged content)

**JS change** (`department-hq.js`): Add `'autonomy': loadAutonomy` to the `loaders` map. `loadAutonomy()` calls the existing dispatch data endpoints and renders into the new panel.

---

### 4. Fleet — Receives System Components

**File:** `platform_v2/tools/department_hq/templates/department_hq.html` (fleet panel)

Append `SYSTEM COMPONENTS` section (cut from Dispatch) to the bottom of `panel-fleet`. No content change — just relocated.

Remove `PROVIDER BUDGETS` from Fleet → it moves to Contractors.

---

### 5. Contractors — Receives Provider Budgets

**File:** `platform_v2/tools/department_hq/templates/department_hq.html` (contractors panel)

Append `PROVIDER BUDGETS` section (cut from Fleet) after the existing contractor list.

No other changes — name "Contractors" stays correct (these are Tier 3 cloud AI services with Telegram budget approval).

---

### 6. Performance — Add Colour Coding

**File:** `platform_v2/tools/department_hq/templates/department_hq.html` (performance panel) or linked CSS

For each department metric card, colour the value by threshold:
- Success rate ≥ 80% → teal/green
- Success rate 50–79% → amber
- Success rate < 50% → red

One CSS rule per threshold class. The JS that renders the card injects the class based on value.

---

### 7. COMs — Fix Data Feed

**File:** `platform_v2/tools/department_hq/` (coms routes / `coms_routes.py` + template)

The 4 metric cards (Total Messages, Telegram, Platform Chat, Director Reports) show "—". This is a broken data endpoint. Fix: trace the API call that populates these cards, identify why it returns 0/null, fix the endpoint or the data source. (Specific fix identified during implementation — read `coms_routes.py` to find the broken query.)

---

### 8. Online Presence — Mark Coming Soon

**File:** `platform_v2/tools/department_hq/templates/department_hq.html` (online-presence panel)

Replace the stub content (agent dropdown with no data) with a Coming Soon placeholder:

```html
<div style="display:flex;align-items:center;justify-content:center;min-height:300px;flex-direction:column;gap:1rem;opacity:0.5">
  <div style="font-size:2rem">🌐</div>
  <div style="font-family:'Orbitron',sans-serif;letter-spacing:0.1em">COMING SOON</div>
  <div style="font-size:0.8rem">Human agent social media visibility — Instagram, Facebook</div>
</div>
```

Tab stays visible — the feature has a clear purpose and will be built.

---

### 9. Global Table Overflow Fix (Fold 5 / Mobile)

**File:** `platform_v2/tools/department_hq/static/css/department-hq.css`

Add:
```css
.dhq-dispatch-section table,
.dhq-section table {
    min-width: 500px;
}
.dhq-dispatch-section,
.dhq-section {
    overflow-x: auto;
}
```

This ensures ALL tables in any DHQ section scroll horizontally on narrow screens instead of overflowing.

---

## Files to Modify

| File | Changes |
|---|---|
| `tools/department_hq/templates/department_hq.html` | Roster toggle, Dispatch cleanup, new Autonomy panel, Fleet + Contractors content moves, Online Presence placeholder, tab bar changes |
| `tools/department_hq/static/js/department-hq.js` | `toggleRosterView()`, `loadAutonomy()`, add autonomy to loaders map |
| `tools/department_hq/static/css/department-hq.css` | Ollama chips compact style, table overflow fix, performance colour classes |
| `tools/department_hq/coms_routes.py` | Fix broken metric endpoints |

---

## Implementation Order (separate PRs)

1. **PR 1 — Dispatch cleanup + Autonomy tab** (highest impact — fixes 21K px problem)
2. **PR 2 — Roster + Org Chart merge** (UI toggle)
3. **PR 3 — Contractors + Fleet content swap**
4. **PR 4 — Performance colour coding + COMs data fix**
5. **PR 5 — Online Presence Coming Soon + global overflow fix**

---

## Out of Scope

- Devices tab: investigate in a separate session — could be future IoT/CLI auth or can be hidden
- System Alerts History: separate spec (already designed, follow-up to Dispatch History)
- Content within each section (data quality, endpoint improvements): tracked separately per tab
