# Roster Tab → One Configurable Table

**Date**: 2026-08-20
**Module**: Department HQ → Roster tab
**Status**: design approved, implementation plan pending
**Sub-project**: A of 2 (B = agent data integrity, separate spec)

---

## 1. Problem — measured, not assumed

The Roster renders the workforce correctly but offers almost no way to organise it. Every
measurement below was taken live on 2026-08-20 (code read + DB query + browser drive as
`claude` on `192.168.1.200:3000`).

| observation | measured |
|---|---|
| Agents rendered at once | **140** (no pagination, no virtualisation) |
| Card-view page height | **11,064 px** (~11 screens) |
| Primary grouping = `shift_state` | **ON DUTY 135** / WINDING DOWN 1 / OFF DUTY 4 |
| Sortable table columns | **0 of 6** |
| Department filter in UI | absent (the API already supports it) |
| `worker_type` filter | absent (API does not support it either) |
| Sort control anywhere | absent |
| Largest department | Engineering & Technology **53** (38% of roster) |

Roster composition: 140 non-decommissioned = 116 `ai` + 23 `internal` + 1 `contractor`,
across 17 departments.

**The core defect is the grouping.** `renderRosterCards` groups by `shift_state`, and 135 of
140 agents are `active`. The grouping is cosmetically present and functionally inert: one
"ON DUTY" header followed by 135 cards.

Three of six shift-filter options (Deployed, Barracked, Cooldown) match **zero** agents and
always return an empty roster, while `winding_down` — which has an agent — has no option at
all. The control disagrees with the data it filters.

## 2. Goals

1. Make 140 agents sortable, filterable and groupable along the axes that matter.
2. Surface the performance data that already exists and is not displayed.
3. Support bulk shift changes and CSV export without inventing a risky new write surface.
4. Serve four distinct jobs from one surface: audit health, find an agent fast, read org
   structure, and do bulk admin.

## 3. Non-goals

- **Pagination / virtualisation.** 140 rows is fine. Paginating would hide the grouping
  problem rather than fix it.
- **A new tab or module.** Everything fits the existing Roster surface. The tab bar already
  carries 14 tabs.
- **Anything depending on `last_used` or `reports_to_agent_id`** — see §9.
- **Bulk department / model / tier changes** — see §7.

## 4. Shape

One control bar, one table. The card / gallery / table view switcher is removed.

```
[search…] [Dept ▾] [Type ▾] [Floor ▾] [Shift ▾] [Group by ▾]        140 agents
─────────────────────────────────────────────────────────────────────────────
☐ 12 selected   [Set shift ▾]  [Export CSV]      ← only when selection non-empty
─────────────────────────────────────────────────────────────────────────────
☐ │ Agent ▲ │ Dept │ Floor │ Shift │ Role │ Type │ Perf │ Success │ Tasks │ ⋯
  ▼ Engineering & Technology (53)
☐ │ [av] F.O.R.G.E. │ Engineering & Technology │ ENGINEERING │ active │ …
```

The org-structure job does not depend on the card view. The **ORG CHART** button beside the
table (`toggleRosterView('list' | 'org-chart')`) is a separate display axis and is left
untouched. The table covers structure through collapsible department groups; the org chart
continues to cover reporting lines.

## 5. Columns and the NULL contract

| column | source | populated |
|---|---|---|
| select | — | — |
| Agent (avatar + display_name + acronym) | `avatar_url`, `display_name`, `acronym` | 131/140 avatars |
| Department | `department` | 140/140 |
| Floor | `floor` | 140/140 |
| Shift | `shift_state` (badge) | 140/140 |
| Role | `title` | 138/140 |
| Type | `worker_type` | 140/140 |
| Perf | `performance_score` | 123/140 |
| Success | `success_rate` | 123/140 |
| Tasks | `total_tasks_completed` | 122/140 |
| Actions | opens the existing agent profile modal | — |

### 5.1 NULL is not zero — load-bearing

`performance_score`, `success_rate` and `total_tasks_completed` are each missing on 17–18
agents.

- A missing value renders as **`—`**, never `0`, never blank.
- A missing value **sorts to the END in BOTH directions** — ascending and descending.

If NULL coerces to 0, the 17 agents that have never been scored render as the worst
performers in the fleet. That is a fabricated finding presented as data, and it is the
easiest way for this feature to lie. A unit test pins both directions.

## 6. Grouping, sorting, filtering

**Group by**: `Department` (default) | `Floor` | `Shift` | `Worker type` | `None` (flat).
Group headers are collapsible and show a headcount. Grouping is presentation-only — it never
changes which rows are in the payload.

**Sort**: click a column header. **Client-side.** The payload is already complete (140 of
140, default `limit=200`), so the browser holds every row and can sort instantly. A
server-side `sort` param is deliberately NOT added: it would create a second copy of ordering
logic beside the filter logic that is already duplicated in this file (§8).

- When grouped, sorting orders rows **within** each group; group order stays by the group-by key.
- **Truncation guard**: if `total > agents.length` the client sort disables itself and shows
  why. It must never silently sort a partial set. This is the condition under which the
  client-side decision stops being valid, and it is surfaced rather than assumed away.

**Filters**: server-side, extending what exists.

- `department` — already accepted by `/api/roster`, simply never exposed in the UI.
- `worker_type` — **new** param on `/api/roster`; validated against `ai | internal | contractor`.
- `floor`, `shift_state` — unchanged.
- `search` — widened from (`name`, `display_name`) to also cover `title`, `acronym` and
  `department`.
- The shift dropdown renders **every** valid state with its live count (`Barracked (0)`).
  Options are not hidden when empty: a zero-count option that is visible is honest, whereas a
  removed option is indistinguishable from a state that does not exist.

## 7. Bulk actions

Scope is deliberately narrow: **shift state only**, plus a read-only CSV export.

`department` is excluded from bulk on purpose. `update_agent` auto-derives `floor` from
`department`, and department is the home-department input to `CAPABILITY_DEPARTMENT_MAP`
dispatch routing — so a bulk department move silently re-routes work. Department reassignment
stays single-agent, where one decision is visible at a time. Model and tier changes are
likewise out of scope.

### 7.1 `POST /api/roster/bulk-shift`

```
request  { "agent_ids": [int, ...], "shift_state": "<state>" }
response { "success": true,
           "results": [ {"agent_id": 12, "name": "...", "ok": true,  "previous": "active"},
                        {"agent_id": 34, "name": "...", "ok": false, "error": "..."} ],
           "ok_count": N, "failed_count": M }
```

- `@admin_required`, mirroring the existing `/api/roster/shift`.
- Validates `shift_state` against the same `VALID_SHIFT_STATES` constant the single-agent
  endpoint uses. One vocabulary, one definition.
- Loops `agent_service.update_agent()` — no direct SQL on agent tables (platform rule).
- **Per-agent results are mandatory.** A partial failure must be visible per agent. Returning
  only an aggregate count is what makes a half-applied batch look like a success.
- Server-side loop, not N calls from the browser: N browser calls fail partially and
  invisibly, and there is no single place to report the outcome.

### 7.2 Confirmation

A batch over N targets is N decisions (`feedback_bulk-ops-are-n-decisions`). Before applying:

- name the count and the transition (`12 agents: active → barracked`);
- warn if any selected agent is a department director (`is_department_ai`), naming how many;
- after applying, report the per-agent outcome, not just a total.

### 7.3 CSV export

Client-side, from the rows already loaded. Exports the current filtered **and sorted** view
with the visible columns. No new endpoint. Missing values export as empty, consistent with
§5.1 rendering as `—`.

## 8. Cleanup carried in this change

**Duplicated filter logic in `/api/roster`** (`roster_routes.py` ~98–125). The endpoint
filters through `list_agents()`, then hand-rebuilds the same predicates for a `COUNT(*)`.
Two copies that must agree, and the count copy hardcodes `a.status = 'active'`. Collapse to
one definition so a future filter cannot be added to one and forgotten in the other.

**Decommissioned filtering** currently happens in Python after the fetch, so decommissioned
agents consume page slots and then vanish, under-filling the page. Harmless at 140, wrong at
500. Move into the query.

## 9. Explicitly out of scope — data integrity (sub-project B)

Verified and deliberately excluded:

- **`last_used` is 0/140 populated.** It is the obvious "who is idle" field and it is
  entirely empty. No idle/staleness column or sort is possible until the write path exists.
  Building one now would ship an empty column that looks broken.
- **`reports_to_agent_id` is 26/140.** The org-chart hierarchy is 81% incomplete.
- **`current_grade` is 3/140.** Unusable.

Every field this spec displays is ≥87% populated, so sub-project A does not depend on B.

## 10. Removals

Verified to have no consumer outside this module before listing:

| removed | evidence |
|---|---|
| `renderRosterCards` | only caller is `renderRoster` |
| `renderRosterGallery` | only caller is `renderRoster` |
| `setRosterView` | only callers are the 3 `.dhq-view-btn` buttons |
| `SHIFT_GROUPS` | 3 references, all inside `renderRosterCards` |
| `.dhq-view-btn` markup | `department_hq.html` ~104–106 |
| `dhq-crew-*` CSS | `department-hq.css` ~1240–1330, no other consumer |

`toggleRosterView` and the ORG CHART proxy are **kept** — a different axis, unrelated to this
change.

## 11. Files touched

| file | change |
|---|---|
| `platform_v2/tools/department_hq/roster_routes.py` | `worker_type` param, widened `search`, de-duplicated count, new `bulk-shift` endpoint |
| `platform_v2/tools/department_hq/static/js/department-hq.js` | new table renderer w/ grouping + sort + selection; remove card/gallery renderers |
| `platform_v2/tools/department_hq/templates/department_hq.html` | new control bar; remove view switcher |
| `platform_v2/tools/department_hq/static/css/department-hq.css` | table/group/selection styles; remove `dhq-crew-*` |
| `platform_v2/tests/` | new tests per §12 |

## 12. Testing

**Unit**
- `worker_type` filter accepts the three valid values and rejects others.
- `search` matches on title, acronym and department.
- Count and list agree under every filter combination (the §8 regression).
- `bulk-shift` returns per-agent results; a mid-batch failure yields `ok:false` for that agent
  and `ok:true` for the rest.
- `bulk-shift` rejects an invalid `shift_state`.
- **NULL sort ordering in both directions** (§5.1).

Per `repair-bay.md`: prove a new test fails against the unfixed code before claiming it
passes. Reintroduce the defect in a **copy** of the module (`importlib`), never by mutating
the live file.

**Live browser drive — required, not optional.** Per KB #292215 a green suite has proved
nothing for DHQ UI three times running; only a live drive caught those defects. Verify in the
browser: group headers and counts, every filter round-trip, sort in both directions including
where NULLs land, selection survives a re-render, the bulk confirm dialog, and CSV contents
matching the visible view.

## 13. Risks

| risk | mitigation |
|---|---|
| NULL renders/sorts as 0 → fabricated "worst performers" | §5.1 contract + test pinning both directions |
| Bulk shift partially applies and reads as success | per-agent results (§7.1); aggregate-only is forbidden |
| Client sort silently sorts a partial set | truncation guard disables sort and says why (§6) |
| Removing card/gallery loses the org-structure read | ORG CHART axis retained; department grouping in-table |
| Flask serves a cached template after edit | confirm the browser has the new markup before debugging logic |
| Count/list divergence reintroduced | collapsed to one definition (§8) + test |

## 14. Open questions

None. Bulk scope (shift-only + CSV) and the mega-view approach were decided with the owner on
2026-08-20 before this spec was written.
