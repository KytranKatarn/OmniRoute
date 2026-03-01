# Phase 4: Self-Improvement Pipeline Wiring — Design

**Project**: #101 ARCHIE Self-Evolution Pipeline
**Tasks**: #709 (Code Sentinel → Improvement Labs), #710 (Improvement Labs → Sandbox → Deploy)
**Date**: 2026-03-01
**Status**: Approved

---

## Problem

Code Sentinel scans produce issues that sit in the `code_issues` table with no automatic path to improvement proposals. Improvement Labs has a complete proposal→sandbox→test→deploy pipeline, but each step requires manual button clicks. The self-improvement loop is broken in two places.

## Approach: Event-Driven Pipeline (Approach A)

Add hook functions at the end of existing workflows that trigger the next step automatically. No new framework — just function calls at natural transition points.

## Part 1: Code Sentinel → Improvement Labs (Task #709)

### New file: `platform_v2/services/scan_pipeline.py`

Glue service called at the end of `scan_file()` in Code Sentinel.

**Functions:**
- `process_scan_results(scan_id, issues, file_path)` — main entry point
  - Filters issues by severity
  - Critical/High: creates individual proposal per issue via `ImprovementManager.create_proposal()`
  - Medium: tags `code_issues` for weekly batch collection
  - Returns: `{"proposals_created": N, "medium_queued": M}`

- `batch_medium_issues()` — called weekly by scheduler
  - Collects all medium issues not yet linked to a proposal
  - Groups by file_path, creates one "Code Cleanup" proposal per file (or single bundled proposal)
  - Links `code_issues.proposal_id` to new proposal

**Deduplication:**
- Before creating a proposal, check if an open proposal already exists for same file + issue_type
- Skip if found, log as duplicate

**Proposal metadata:**
```json
{
  "source": "code_sentinel",
  "scan_id": 123,
  "file_path": "platform_v2/app.py",
  "issue_type": "security",
  "severity": "critical",
  "line_number": 42,
  "auto_generated": true
}
```

**Integration points:**
- Code Sentinel `scan_file()`: add call to `process_scan_results()` after DB insert
- Code Sentinel `batch_scan_files()`: add call after each file scan completes
- Consciousness scheduler: add weekly `batch_medium_issues()` job

## Part 2: Auto-Execution After Approval (Task #710)

### Modified: `platform_v2/tools/improvements/routes.py` (approve endpoint)

After approval, spawn a background thread that runs the full execution pipeline.

**New function: `_auto_execute_proposal(proposal_id)`**

Pipeline steps (each updates proposal status):
1. `approved` → `code_generating`: Call `CodeGenerationEngine.generate_code()`
2. `code_generating` → `testing`: Apply code to sandbox, run tests via `sandbox_test_runner`
3. `testing` → `tested` or `fix_requested`: Check test results

**Status transitions:**
```
approved → code_generating → testing → tested (ready for deploy)
                                     → fix_requested (tests failed)
```

**Error handling:**
- If any step fails, set status to `fix_requested` with error details in metadata
- No auto-retry — admin can manually re-trigger via existing UI buttons
- All errors logged to `improvement_proposals.metadata.execution_log`

**Notifications:**
- On success: insert `system_notifications` row ("Proposal #N ready for deployment")
- On failure: insert `system_notifications` row ("Proposal #N failed: {reason}")

**Background thread pattern:**
- Uses same pattern as Consciousness async batch jobs (ADR-048/049/050)
- Thread-safe DB connections (new connection per thread)
- No Flask request context dependency

## Part 3: What Stays Manual

- **Deploy**: Always requires admin approval click (safety gate)
- **Low severity issues**: Stay as tracked `code_issues` only — no proposals created
- **Proposal rejection**: Admin can reject any auto-created proposal at any time

## Part 4: Scheduler Integration

Add to consciousness scheduler (existing APScheduler in routes.py):
- `batch_medium_issues()` — weekly (Sunday 02:00)

## Files Changed

| File | Change |
|------|--------|
| Create: `platform_v2/services/scan_pipeline.py` | New glue service |
| Modify: `platform_v2/tools/code_sentinel/routes.py` | Add hook after scan_file() and batch_scan_files() |
| Modify: `platform_v2/tools/improvements/routes.py` | Add _auto_execute_proposal() background thread after approve |
| Modify: `platform_v2/tools/consciousness/routes.py` | Add weekly batch_medium_issues scheduler job |

## What Doesn't Change

- ImprovementManager.create_proposal() — used as-is
- CodeGenerationEngine.generate_code() — used as-is
- SandboxManager — used as-is
- sandbox_test_runner — used as-is
- All existing UI/API endpoints — unchanged
- Deploy workflow — stays manual
