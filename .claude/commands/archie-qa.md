---
name: archie-qa
description: Run P.R.O.B.E. QA tests — list suites, run by suite name or ID, generate PDF reports. For module-scoped scans after editing code use /archie-scan. For full dashboard use /archie-probe.
allowed-tools: Bash, mcp__archie__run_qa_suite, mcp__archie__list_qa_suites, mcp__archie__get_qa_results
argument: Suite name (e.g., "consciousness"), suite ID (e.g., "23"), "all", or "list". Add --pdf for PDF report. Add --branded for client report.
---

# P.R.O.B.E. QA Runner

## Related skills
- `/archie-scan <module>` — run only the suites for one module (faster, targeted)
- `/archie-probe` — full P.R.O.B.E. status dashboard (all suites + proposals + coverage)

## Parse Arguments

Parse `$ARGUMENTS`:
- Empty or "list" → list available suites
- Suite name (e.g., "consciousness") or ID (e.g., "23") → run that suite
- "all" → run all active suites (54 suites, ~20 min including Playwright)
- `--pdf` flag → generate PDF report after run
- `--branded` flag → generate branded (client-facing) PDF

## If "list" or empty

Call `mcp__archie__list_qa_suites` and display:

```
P.R.O.B.E. QA Suites:
  1. [name] ([suite_type]) — [description]
  ...

Usage: /archie-qa <suite-name> [--pdf] [--branded]
```

## If suite name provided

1. Call `mcp__archie__run_qa_suite` with `suite_name` matching the argument
2. Display results inline:
```
P.R.O.B.E. QA: [suite_name]
  PASS  test_name (234ms)
  FAIL  test_name — error message
  ...

Result: X/Y passed (Z%) — N failures
```

3. If `--pdf` flag present OR any failures found:
   - Determine branded flag: `--branded` in arguments → `branded=True`
   - Run: `docker exec archie_platform python3 -c "from services.qa_report_service import generate_report; print(generate_report(RUN_ID, branded=BRANDED_BOOL))"`
   - Replace RUN_ID with the actual run_id from the suite results
   - Display: `PDF report: [path]`

## If "all"

Run each active suite in sequence using `mcp__archie__run_qa_suite` without suite_id (runs all).
Display per-suite summary, then final totals.

## Notes

- Tests run inside Docker (`archie_platform` container)
- Platform must be running at 192.168.1.200:3000
- First run may be slow (Playwright browser cold start)
- Screenshots saved to `platform_v2/qa/test-screenshots/`
- PDF reports saved to `platform_v2/static/qa_reports/`
