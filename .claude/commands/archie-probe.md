---
name: archie-probe
description: Show P.R.O.B.E. QA platform status — active suites, last run summary, recent regression proposals, and coverage map. Use to assess QA health before shipping or after a session.
allowed-tools: Bash, mcp__archie__run_qa_suite
argument: Optional — "suites" (list all), "proposals" (regression proposals), "coverage" (module map). Default shows full dashboard.
---

# P.R.O.B.E. Status Dashboard

Run the following and display a formatted report.

## Step 1 — Suite summary

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT
  s.id,
  s.name,
  (SELECT COUNT(*) FROM jsonb_array_elements(s.spec->'tests')) as test_count,
  r.status as last_status,
  r.passed,
  r.failed + r.errors as problems,
  r.started_at
FROM qa_test_suites s
LEFT JOIN LATERAL (
  SELECT status, passed, failed, errors, started_at
  FROM qa_test_runs
  WHERE suite_id = s.id
  ORDER BY started_at DESC LIMIT 1
) r ON true
WHERE s.is_active = true
ORDER BY r.started_at DESC NULLS LAST
LIMIT 30;
"
```

## Step 2 — Recent regression proposals

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, title, status, metadata->>'suite_name' as suite,
       metadata->>'is_regression' as regression
FROM improvement_proposals
WHERE metadata->>'source' = 'qa_pipeline'
  AND status NOT IN ('deployed','archived','rejected')
ORDER BY id DESC LIMIT 10;
"
```

## Step 3 — Coverage map

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import MODULE_SUITE_MAP
print(f'Modules mapped: {len(MODULE_SUITE_MAP)}')
for mod, ids in sorted(MODULE_SUITE_MAP.items()):
    print(f'  {mod:<28} suites: {ids}')
"
```

## Display format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 P.R.O.B.E. QA STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Active suites:  54
 Last full run:  581/690 tests passing (84%)

 SUITE HEALTH (recent runs)
  ✅ Admin Ops — Account Center       35/35
  ✅ AI Command — Media Studio        30/30
  ❌ fitness.yaml                      6/7  ← 1 failure
  ...

 OPEN REGRESSION PROPOSALS
  #1042 QA Failure: fitness-api-stats  [pending]
  ...

 MODULE COVERAGE (28 modules mapped)
  account_center → [16, 31]
  media_studio   → [23, 50]
  ...

 QUICK ACTIONS
  /archie-scan <module>   Run targeted scan for one module
  /archie-qa all          Run full suite
  /archie-qa <suite-name> Run single suite
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## If argument is "suites"

Show only the suite table with test counts and last run status.

## If argument is "proposals"

Show only the regression proposals table, grouped by suite.

## If argument is "coverage"

Show only the MODULE_SUITE_MAP coverage table.

## Notes

- Repair Bay auto-files proposals when P.R.O.B.E. detects a regression
- `is_regression: true` = test was passing before, now failing
- `is_regression: false/null` = first-time failure or known issue
- Suites run automatically every 6h via `qa_scheduled_run` job (P.R.O.B.E.)
