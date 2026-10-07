# Department HQ SQL findings review — 2026-10-07

Reviewed proposals #417 (work_routes.py), #536 (fleet_node_routes.py), #2181
(dispatch_routes.py), and #2498 (creed_routes.py). The protected dispatcher
finding #3391 is excluded from this review and from Codex edits.

## Result

No SQL injection was confirmed in the reviewed query construction. This is a
scoped source review with selected live GET probes, not proof that the entire
module is vulnerability-free. Existing SQL findings remain open: the conservative
checker cannot prove arbitrary query builders safe. No scanner exemption, manual
completion, or auto-fix eligibility bypass was added.

| File | SQL structure sources | Request values |
|---|---|---|
| work_routes.py | Department clause chosen between two fixed strings; welfare fragment called with literal alias `tel` and fixed exclusion constants | Department is bound separately; pagination is bound |
| fleet_node_routes.py | Fixed node-list clauses; update keys filtered through a fixed allowed_fields list; station/settings clauses appended as literals | Status, approval, node IDs, field values and assignment IDs are bound |
| dispatch_routes.py | Fixed backlog query map; fixed filter clauses and CTE templates; CO2 fragments from the shared helper using defaults or literal column arguments | Agent, capability, status, search, notification filters and pagination are bound |
| creed_routes.py | Optional fixed outcome clause; literal roster subqueries; erasure/count table names from fixed local sequences | Outcome, user IDs and pagination are bound |

Changing f-strings to concatenation or hiding SQL in helpers would not establish
security and would not justify closing a finding. Large-file findings are separate
planned refactors; they were not changed.

## Live evidence through P.R.O.B.E.

P.R.O.B.E.'s native E2ERunner authenticated through `/api/qa/auth` as `probe`.
Read-only GET requests used `__probe_absent__' OR '1'='1` as a filter value:

- `/api/work-sessions`: HTTP 200, empty sessions.
- `/api/nodes/all`: HTTP 200, empty nodes.
- `/api/creed/coordination-events`: HTTP 500, error `0`.
- `/api/alerts/history`: HTTP 200, empty rows.

The coordination failure is a dictionary-cursor indexing bug: the count query
returns a named row, but the endpoint accessed index 0. The associated fix aliases
COUNT(*) as `total` and reads `row['total']`. It leaves the SQL filter parameterized.
Tests execute the actual endpoint body with dictionary cursor rows for unfiltered,
ordinary filtered, and SQL-like filtered requests. No erasure/update controls were
clicked or production personal data included in the report.

Completion of this fix requires human merge, deployment, and a live endpoint
retest. It does not by itself resolve the four conservative SQL findings.
