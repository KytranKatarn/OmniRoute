# Dispatch History — Design Spec
**Date:** 2026-05-13
**Status:** Approved
**Scope:** Dashboard "View all" link + DHQ Dispatch History section

---

## Problem

Mission Briefing → Recent Activity is capped at 15 items showing the last ~1 hour of platform activity. There is no way to review historical dispatch calls, measure agent workload, track LLM performance, or audit business load over time. The DHQ Dispatch tab has live panels only — no historical log with pagination.

System Alerts history is deferred (follow-up task, same design pattern).

---

## Goals

- Add a "VIEW ALL →" shortcut from Mission Briefing to the new history section
- Give operators a filterable, paginated log of all AI dispatch activity
- Surface summary metrics (workload, success rate, LLM performance) that update with filters
- Enable use cases: agent load review, business load by module, LLM performance audit, failure investigation

---

## Architecture

### 1. Dashboard Link (dashboard_dynamic.html)

**File:** `platform_v2/templates/dashboard_dynamic.html`

Add a right-aligned `VIEW ALL →` link inside the `#briefingSectionActivity` header row, next to the badge. Links to `/tools/department-hq#dispatch-history`. Styled as a small dim text link (no button, no accent — stays subtle).

```html
<!-- inside .briefing-section header for activity -->
<a href="/tools/department-hq#dispatch-history" class="briefing-view-all">VIEW ALL →</a>
```

One CSS rule in `dashboard.css`: `briefing-view-all` — small, right-aligned, muted teal, no underline, hover brightens.

---

### 2. Backend Endpoint

**File:** `platform_v2/tools/department_hq/dispatch_routes.py` (new route added here)

```
GET /tools/department-hq/api/dispatch/history
```

**Query params:**
| Param | Type | Default | Description |
|---|---|---|---|
| `agent` | string | all | Filter by agent_name |
| `capability` | string | all | Filter by capability |
| `from` | date (YYYY-MM-DD) | 7 days ago | Start of range |
| `to` | date (YYYY-MM-DD) | today | End of range |
| `q` | string | — | Text search: agent_name, capability, module_source, error_message |
| `source` | enum: all/task/job | all | Which log table |
| `page` | int | 1 | Page number |
| `per_page` | int | 25 | Rows per page (25/50/100) |

**Response:**
```json
{
  "stats": {
    "total_calls": 1842,
    "success_rate": 94.2,
    "avg_duration_s": 28.4,
    "top_agent": "F.O.R.G.E.",
    "top_module": "repair_bay"
  },
  "rows": [...],
  "total": 1842,
  "page": 1,
  "pages": 74
}
```

**Query strategy:** `UNION ALL` of two CTEs:

```sql
-- CTE 1: task_execution_log
SELECT 'task' AS source, agent_name, capability, module_source AS module,
       model_used, duration_ms, success, error_message, created_at
FROM task_execution_log
WHERE created_at BETWEEN :from AND :to
  AND (:agent = '' OR agent_name ILIKE :agent)
  AND (:capability = '' OR capability = :capability)
  AND (:q = '' OR (agent_name || capability || module_source || COALESCE(error_message,'')) ILIKE :q)

UNION ALL

-- CTE 2: bridge_jobs
SELECT 'job' AS source, agent_name, task_type AS capability, module_id AS module,
       NULL AS model_used, duration_ms, (status = 'completed') AS success,
       error_message, created_at
FROM bridge_jobs
WHERE created_at BETWEEN :from AND :to
  AND (:agent = '' OR agent_name ILIKE :agent)
  AND (:capability = '' OR task_type = :capability)
  AND (:q = '' OR (agent_name || task_type || module_id || COALESCE(error_message,'')) ILIKE :q)

ORDER BY created_at DESC
LIMIT :per_page OFFSET :offset
```

Stats computed in a separate `COUNT / AVG / MODE()` query over the same WHERE conditions. Both queries run in one DB call using two CTEs + a stats subquery.

**Dropdown population:** Two lightweight endpoints for filter dropdowns (called once on page load, cached 60s):
- `GET /api/dispatch/history/agents` → `["F.O.R.G.E.", "P.R.O.B.E.", ...]`
- `GET /api/dispatch/history/capabilities` → `["code_review", "fact_check", ...]`

---

### 3. Frontend — New Dispatch History Section

**File:** `platform_v2/tools/department_hq/templates/department_hq.html`

Added as a new collapsible LCARS section at the bottom of the Dispatch tab, with anchor `id="dispatch-history"`. Sits below the existing live dispatch panels.

#### 3a. Stats Bar (4 cards, flex row)

```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐
│ 1,842       │ │ 94.2%       │ │ 28.4s       │ │ F.O.R.G.E.          │
│ Total Calls │ │ Success     │ │ Avg Duration│ │ repair_bay           │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘
```

Cards use existing LCARS stat-card styling. Fourth card shows top agent + top module stacked. All 4 re-render on filter change.

#### 3b. Filter Bar (horizontal, single row)

```
[Agent ▼] [Capability ▼] [From: date] [To: date] [🔍 Search...] [RESET]
```

- Agent and Capability: `<select>` dropdowns populated from the two lightweight endpoints
- Date inputs: `<input type="date">` defaulting to last 7 days
- Search: debounced 400ms text input
- Reset: clears all filters back to defaults and re-fetches
- Any change triggers a fresh fetch (stats + rows)

#### 3c. Paginated Table

Columns: **Time** | **Source** | **Agent** | **Capability** | **Module** | **Model** | **Duration** | **Status**

- Time: formatted EDT via `ArchieTime.format()`
- Source: badge — `TASK` (teal) or `JOB` (amber)
- Status: ✅ green dot / ❌ red dot
- Duration: colour-coded — green <30s, amber 30-120s, red >120s
- Clicking a row toggles an inline expansion showing: full error message, prompt/completion tokens, cost, request metadata JSON (collapsible)
- Rows striped with existing DHQ table styles

#### 3d. Pagination Controls

```
[← PREV]  Page 3 of 74  [NEXT →]   Per page: [25 ▼]
```

Prev/Next disabled at boundaries. Per-page change re-fetches from page 1.

---

## JS Module

New function block in `department_hq.js` (or extracted to `dispatch_history.js` if the main file is large):

- `initDispatchHistory()` — called on Dispatch tab activate, sets up listeners
- `fetchDispatchHistory(params)` — builds query string, calls endpoint, updates stats + table
- `renderHistoryStats(stats)` — updates 4 stat cards
- `renderHistoryTable(rows)` — builds table rows, attaches expand listeners
- `renderHistoryPagination(page, pages)` — updates pagination controls
- State held in a plain `dispatchHistoryState` object (current filters + page)

---

## Files to Create / Modify

| File | Change |
|---|---|
| `templates/dashboard_dynamic.html` | Add `VIEW ALL →` link in `#briefingSectionActivity` header |
| `static/css/dashboard.css` | Add `.briefing-view-all` rule |
| `tools/department_hq/dispatch_routes.py` | Add 3 new routes: `/api/dispatch/history`, `/api/dispatch/history/agents`, `/api/dispatch/history/capabilities` |
| `tools/department_hq/templates/department_hq.html` | Add `#dispatch-history` section with stats + filter bar + table + pagination |
| `static/js/department_hq.js` (or new `dispatch_history.js`) | Add JS module for history fetch/render |

No new DB tables, no migrations required.

---

## Out of Scope

- System Alerts history (follow-up task, same design pattern)
- Export to CSV (can be added later as a button in the filter bar)
- Real-time auto-refresh of history (history is static; live panels handle real-time)
- Edit or delete of log rows (read-only audit view)
