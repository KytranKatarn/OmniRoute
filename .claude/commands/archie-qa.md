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

## DOM-level coverage (`type: e2e`) — read this before writing a new suite

**An HTTP 200 is NOT evidence a UI renders.** Most suites are `page_load`/`api`, run by
`qa_spec_runner`, which **cannot assert DOM**. A page can return 200 with correct JSON while
the screen shows nothing — that is mistake **#281727** (a card passed page-load AND API QA
while rendering nowhere, because a shared JS file shadowed its handler at load), and it is how
the Backup Manager's blank "Last run:" captions went unnoticed.

To assert what the user actually sees, write `type: e2e` tests (run by `qa_e2e_runner`):

1. **Discover selectors by DRIVING THE LIVE PAGE — never from the template.** Controls built
   dynamically or bound by event delegation have no inline `onclick`, so grepping the HTML
   finds nothing and invented selectors produce a permanently-red suite (worse than no suite —
   people learn to ignore it).
2. Author the YAML in `platform_v2/qa_suites/<name>.yaml`. Vocabulary + copy-paste template:
   **KB #283138**. Reference spec: `qa_suites/backup-manager-backups-tab-e2e.yaml`.
3. Register it so anything can run it — **a YAML on disk alone is NOT runnable**:
   ```bash
   docker exec archie_platform python3 -c "import sys;sys.path.insert(0,'/app');\
   from services.qa_service import create_suite_from_yaml;\
   print(create_suite_from_yaml('/app/qa_suites/<name>.yaml'))"
   ```
4. Run it: `/archie-qa <suite-name>` or `mcp__archie__run_qa_suite(suite_id=N)`.

**Verify the run actually authenticated.** A suite that never logged in proves nothing —
look for `E2E auth via /api/qa/auth ok (user=probe)`. P.R.O.B.E. authenticates with its OWN
credentials (`${ARCHIE_TEST_USERNAME}` / `${ARCHIE_TEST_PASSWORD}`, resolved by
`qa_spec_runner._resolve_env_vars`). Claude must never type them.

**Assertion must be able to FAIL.** Before trusting a new assertion, break the condition in the
live DOM and confirm it flips to false. A test that cannot fail manufactures confidence.

### ⚠️ SAFETY — destructive controls are asserted, never clicked

A scheduled suite runs unattended, forever. **Never `click:` a control with real-world effects.**
Assert wiring instead (`typeof fn === 'function'`, button present, correct destructive styling).

Known hazards on Backup Manager alone: each Quick Backup button starts a **real** multi-GB backup
(2,471 MB / 2,358 MB / 1,596 MB, ~14-17 min each) and would steal `/backups/.backup_lock` from the
nightly cron; per-row **Download** pulls up to 2.4 GB; **Sync USB** and **Cloud** start real
transfers (Cloud against a 15 GB quota that already filled once and killed off-site backups for
~3 weeks); **Delete** destroys a restore point. Only **Inspect** is read-only.
Anything that must genuinely exercise a backup/restore belongs in a manual, on-demand suite.

## Delegating to P.R.O.B.E. (A.R.C.H.I.E. can run this herself — no Claude turn)

`run_qa_suite` is a **known-tool capability** (`delegation_service.KNOWN_TOOL_CAPABILITIES`), so
it executes deterministically with **no LLM**:

```python
mcp__archie__delegate_task(capability='run_qa_suite',
                           reason='Run QA suite <N> (<name>) — <what it proves>')
# -> unified_tasks -> delegate_task_worker (30s) -> qa_service, hub-local compute
```

Prefer this over running suites through Claude: same code path, free local compute, and it works
when Claude is absent. Claude's job is authoring specs and judging results, not being the trigger.

## Notes

- Tests run inside Docker (`archie_platform` container)
- Platform must be running at 192.168.1.200:3000
- First run may be slow (Playwright browser cold start)
- Screenshots saved to `platform_v2/qa/test-screenshots/`; e2e action screenshots go to
  `/tmp/qa_reports/screenshots/<run_id>_<name>.png` **inside the container** — that path is a
  **tmpfs**, so `docker cp` cannot read it; pipe it out with
  `docker exec <c> base64 -w0 <path> | base64 -d > out.png`
- PDF reports saved to `platform_v2/static/qa_reports/`
