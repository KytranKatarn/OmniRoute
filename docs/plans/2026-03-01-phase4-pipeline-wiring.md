# Phase 4: Self-Improvement Pipeline Wiring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire Code Sentinel scan results into automatic Improvement Labs proposals, and auto-execute the code generation→sandbox→test pipeline after proposal approval.

**Architecture:** Event-driven hooks at natural transition points — `scan_pipeline.py` service creates proposals after scans; `_auto_execute_proposal()` background thread runs code gen→sandbox→test after approval. No new framework, just function calls.

**Tech Stack:** Python, psycopg2, threading, existing ImprovementManager + CodeGenerationEngine + SandboxManager

---

### Task 1: Create scan_pipeline.py service

**Files:**
- Create: `platform_v2/services/scan_pipeline.py`

**Step 1: Write scan_pipeline.py**

This service is the glue between Code Sentinel and Improvement Labs. It's called after a scan completes and creates improvement proposals for critical/high issues.

```python
"""Scan pipeline — auto-creates improvement proposals from Code Sentinel findings.

Called after scan_file() completes. Critical/high issues get individual proposals.
Medium issues are tagged for weekly batch collection.

Import:
    from services.scan_pipeline import process_scan_results, batch_medium_issues
"""

import json
import logging

from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def process_scan_results(scan_id, issues, file_path):
    """Process scan results and create improvement proposals for critical/high issues.

    Args:
        scan_id: The code_scans.id from the completed scan
        issues: List of issue dicts from the scan analysis
        file_path: The scanned file path

    Returns:
        {"proposals_created": int, "medium_queued": int, "skipped_duplicates": int}
    """
    proposals_created = 0
    medium_queued = 0
    skipped = 0

    high_severity = [i for i in issues if i.get("severity") in ("critical", "high")]
    medium_severity = [i for i in issues if i.get("severity") == "medium"]

    # Critical/High: create individual proposals
    for issue in high_severity:
        try:
            if _has_open_proposal(file_path, issue.get("type", "quality")):
                skipped += 1
                continue

            proposal_id = _create_proposal_for_issue(scan_id, issue, file_path)
            if proposal_id:
                _link_issue_to_proposal(scan_id, issue, proposal_id)
                proposals_created += 1
        except Exception as e:
            logger.warning(f"Failed to create proposal for issue in {file_path}: {e}")

    # Medium: tag for weekly batch
    if medium_severity:
        medium_queued = _tag_issues_for_batch(scan_id, medium_severity)

    logger.info(
        f"Scan pipeline: {file_path} — "
        f"{proposals_created} proposals created, "
        f"{medium_queued} medium queued, "
        f"{skipped} duplicates skipped"
    )

    return {
        "proposals_created": proposals_created,
        "medium_queued": medium_queued,
        "skipped_duplicates": skipped,
    }


def _has_open_proposal(file_path, issue_type):
    """Check if an open proposal already exists for this file + issue type."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT id FROM improvement_proposals
                WHERE status NOT IN ('deployed', 'implemented', 'rejected', 'archived', 'failed')
                  AND metadata->>'source' = 'code_sentinel'
                  AND metadata->>'file_path' = %s
                  AND metadata->>'issue_type' = %s
                LIMIT 1
                """,
                (file_path, issue_type),
            )
            return cur.fetchone() is not None
        finally:
            cur.close()


def _create_proposal_for_issue(scan_id, issue, file_path):
    """Create an improvement proposal from a single scan issue. Returns proposal_id."""
    severity = issue.get("severity", "medium")
    issue_type = issue.get("type", "quality")
    message = issue.get("message", "Code issue detected")
    suggestion = issue.get("suggestion", "")
    line_number = issue.get("line")

    title = f"[{severity.upper()}] {issue_type}: {message[:80]}"
    description = (
        f"Code Sentinel detected a {severity} {issue_type} issue in `{file_path}`"
        f"{f' at line {line_number}' if line_number else ''}.\n\n"
        f"**Issue:** {message}\n\n"
    )
    if suggestion:
        description += f"**Suggested fix:** {suggestion}\n"

    priority = "critical" if severity == "critical" else "high"
    risk_level = "high" if severity == "critical" else "medium"

    metadata = json.dumps({
        "source": "code_sentinel",
        "scan_id": scan_id,
        "file_path": file_path,
        "issue_type": issue_type,
        "severity": severity,
        "line_number": line_number,
        "auto_generated": True,
    })

    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO improvement_proposals
                (title, category, description, code_changes, rationale,
                 priority, risk_level, status, metadata, collaboration_enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s::jsonb, false)
                RETURNING id
                """,
                (
                    title,
                    issue_type,
                    description,
                    suggestion,
                    f"Auto-detected by Code Sentinel scan #{scan_id}",
                    priority,
                    risk_level,
                    metadata,
                ),
            )
            proposal_id = cur.fetchone()["id"]
            conn.commit()
            logger.info(f"Created proposal #{proposal_id} for {severity} {issue_type} in {file_path}")
            return proposal_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def _link_issue_to_proposal(scan_id, issue, proposal_id):
    """Set code_issues.proposal_id for the matching issue."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE code_issues
                SET proposal_id = %s
                WHERE scan_id = %s
                  AND file_path = %s
                  AND COALESCE(line_number, 0) = %s
                  AND issue_type = %s
                  AND proposal_id IS NULL
                """,
                (
                    proposal_id,
                    scan_id,
                    issue.get("file_path", ""),
                    issue.get("line", 0),
                    issue.get("type", "quality"),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            cur.close()


def _tag_issues_for_batch(scan_id, medium_issues):
    """Tag medium-severity issues for weekly batch processing.

    Uses the code_issues.status field — sets to 'batch_eligible' for unlinked medium issues.
    Returns count of tagged issues.
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE code_issues
                SET status = 'batch_eligible'
                WHERE scan_id = %s
                  AND severity = 'medium'
                  AND proposal_id IS NULL
                  AND status = 'open'
                """,
                (scan_id,),
            )
            count = cur.rowcount
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            return 0
        finally:
            cur.close()


def batch_medium_issues():
    """Weekly job: collect batch_eligible medium issues and create cleanup proposals.

    Groups issues by file_path, creates one proposal per file.
    Called by the consciousness scheduler (Sunday 02:00).
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            # Get all batch-eligible issues grouped by file
            cur.execute(
                """
                SELECT file_path, COUNT(*) as issue_count,
                       array_agg(id) as issue_ids,
                       array_agg(message) as messages
                FROM code_issues
                WHERE status = 'batch_eligible'
                  AND proposal_id IS NULL
                GROUP BY file_path
                ORDER BY issue_count DESC
                """
            )
            groups = cur.fetchall()
        finally:
            cur.close()

    if not groups:
        logger.info("Batch medium issues: no eligible issues found")
        return {"proposals_created": 0}

    proposals_created = 0
    for group in groups:
        try:
            file_path = group["file_path"]
            issue_count = group["issue_count"]
            issue_ids = group["issue_ids"]
            messages = group["messages"]

            if _has_open_proposal(file_path, "cleanup"):
                continue

            # Build description from all issues
            issue_list = "\n".join(f"- {m}" for m in messages[:10])
            if issue_count > 10:
                issue_list += f"\n- ... and {issue_count - 10} more"

            title = f"Code Cleanup: {file_path} ({issue_count} issues)"
            description = (
                f"Weekly batch: {issue_count} medium-severity issues in `{file_path}`.\n\n"
                f"**Issues:**\n{issue_list}"
            )

            metadata = json.dumps({
                "source": "code_sentinel",
                "batch": True,
                "file_path": file_path,
                "issue_type": "cleanup",
                "issue_count": issue_count,
                "auto_generated": True,
            })

            with get_db_connection() as conn:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                try:
                    cur.execute(
                        """
                        INSERT INTO improvement_proposals
                        (title, category, description, rationale, priority, risk_level,
                         status, metadata, collaboration_enabled)
                        VALUES (%s, 'cleanup', %s, 'Weekly batch from Code Sentinel medium issues',
                                'medium', 'low', 'pending', %s::jsonb, false)
                        RETURNING id
                        """,
                        (title, description, metadata),
                    )
                    proposal_id = cur.fetchone()["id"]

                    # Link all issues to this proposal
                    cur.execute(
                        """
                        UPDATE code_issues
                        SET proposal_id = %s, status = 'open'
                        WHERE id = ANY(%s)
                        """,
                        (proposal_id, issue_ids),
                    )
                    conn.commit()
                    proposals_created += 1
                    logger.info(f"Batch proposal #{proposal_id}: {issue_count} issues in {file_path}")
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    cur.close()

        except Exception as e:
            logger.warning(f"Failed to batch issues for {group['file_path']}: {e}")

    logger.info(f"Batch medium issues complete: {proposals_created} proposals created")
    return {"proposals_created": proposals_created}
```

**Step 2: Commit**

```bash
git add platform_v2/services/scan_pipeline.py
git commit -m "feat(services): add scan_pipeline.py for Code Sentinel → Improvement Labs"
```

---

### Task 2: Wire Code Sentinel scan hooks

**Files:**
- Modify: `platform_v2/tools/code_sentinel/routes.py`

**Step 1: Add hook call after scan_file() DB insert**

At line 578 (after `conn.commit()` / `cur.close()` / `conn.close()`), add the pipeline hook call.
The hook runs AFTER the scan response is returned — use a background approach to avoid slowing down the scan API response.

Insert after line 580 (`conn.close()`), before the `return jsonify(...)`:

```python
        # --- Pipeline hook: auto-create proposals for critical/high issues ---
        try:
            from services.scan_pipeline import process_scan_results

            process_scan_results(scan_id, issues, file_path)
        except Exception as pipeline_err:
            logger.warning(f"Scan pipeline hook failed: {pipeline_err}")
```

**Step 2: Add hook call after batch_scan_files() individual scan**

In the `scan_single_file()` inner function (around line 670, after `conn.commit()`), add the same hook.
The batch function already stores issues, but the inner function doesn't insert individual `code_issues` rows — it only inserts `code_scans`. So we need to also insert issues in batch mode, then call the pipeline.

Actually, looking at the batch scan code more carefully (lines 640-689), it does NOT insert `code_issues` rows — only `code_scans`. The pipeline needs `code_issues` to exist first.

**Solution**: Add `code_issues` insert to the batch scan inner function (matching the single scan pattern at lines 560-576), then call the pipeline.

Insert after line 670 (`conn.commit()`), before the `return`:

```python
            # Insert individual issues (matching single scan pattern)
            for issue in issues:
                cur.execute(
                    """
                    INSERT INTO code_issues (scan_id, file_path, line_number, issue_type,
                                            severity, message, suggestion)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        scan_id,
                        file_path,
                        issue.get("line"),
                        issue.get("type", "quality"),
                        issue.get("severity", "medium"),
                        issue.get("message", ""),
                        issue.get("suggestion", ""),
                    ),
                )
            conn.commit()

            # Pipeline hook
            try:
                from services.scan_pipeline import process_scan_results

                process_scan_results(scan_id, issues, file_path)
            except Exception as pipeline_err:
                logger.warning(f"Batch scan pipeline hook failed for {file_path}: {pipeline_err}")
```

**Step 3: Commit**

```bash
git add platform_v2/tools/code_sentinel/routes.py
git commit -m "feat(code_sentinel): wire scan results to improvement proposal pipeline"
```

---

### Task 3: Wire auto-execution after approval

**Files:**
- Modify: `platform_v2/tools/improvements/routes.py`

**Step 1: Add _auto_execute_proposal() function**

Add this function near the top of the file (after imports, before route definitions). This runs in a background thread after approval.

```python
def _auto_execute_proposal(proposal_id):
    """Background thread: auto-execute approved proposal through code gen → sandbox → test.

    Status transitions: approved → code_generating → testing → tested / fix_requested
    """
    import threading

    logger.info(f"[AutoExec] Starting auto-execution for proposal #{proposal_id}")

    try:
        # Step 1: Generate code
        _update_proposal_status(proposal_id, "code_generating")

        try:
            from ai_bridge.code_generation_engine import CodeGenerationEngine

            engine = CodeGenerationEngine()
            gen_result = engine.generate_code(proposal_id)
        except Exception as e:
            logger.error(f"[AutoExec] Code generation failed for #{proposal_id}: {e}")
            _update_proposal_status(proposal_id, "fix_requested", error=str(e))
            _notify_admin(proposal_id, "error", f"Code generation failed: {e}")
            return

        if not gen_result or not gen_result.get("success", True):
            error_msg = gen_result.get("error", "Code generation returned no results") if gen_result else "No result"
            _update_proposal_status(proposal_id, "fix_requested", error=error_msg)
            _notify_admin(proposal_id, "warning", f"Code generation issue: {error_msg}")
            return

        # Step 2: Run tests in sandbox
        _update_proposal_status(proposal_id, "testing")

        try:
            from sandbox_manager import SandboxManager

            manager = SandboxManager()
            # Get the sandbox for this proposal
            test_result = manager.run_tests_for_proposal(proposal_id)
        except Exception as e:
            logger.warning(f"[AutoExec] Sandbox testing failed for #{proposal_id}: {e}")
            # Testing failure is non-fatal — mark as tested with warning
            _update_proposal_status(proposal_id, "tested", error=f"Tests unavailable: {e}")
            _notify_admin(proposal_id, "info", f"Proposal #{proposal_id} approved — sandbox tests unavailable, ready for manual review")
            return

        # Step 3: Check results and update status
        if test_result and test_result.get("overall_status") == "passed":
            _update_proposal_status(proposal_id, "tested")
            _notify_admin(proposal_id, "success", f"Proposal #{proposal_id} passed all tests — ready for deployment")
        else:
            error_detail = test_result.get("summary", "Tests failed") if test_result else "No test results"
            _update_proposal_status(proposal_id, "fix_requested", error=str(error_detail))
            _notify_admin(proposal_id, "warning", f"Proposal #{proposal_id} failed tests: {error_detail}")

    except Exception as e:
        logger.error(f"[AutoExec] Unexpected error for #{proposal_id}: {e}")
        _update_proposal_status(proposal_id, "fix_requested", error=str(e))
        _notify_admin(proposal_id, "error", f"Auto-execution failed: {e}")


def _update_proposal_status(proposal_id, status, error=None):
    """Update proposal status and optionally log error to metadata."""
    try:
        conn = get_db()
        cur = conn.cursor()
        if error:
            cur.execute(
                """
                UPDATE improvement_proposals
                SET status = %s,
                    metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (
                    status,
                    json.dumps({"execution_log": error, "last_status_change": status}),
                    proposal_id,
                ),
            )
        else:
            cur.execute(
                "UPDATE improvement_proposals SET status = %s WHERE id = %s",
                (status, proposal_id),
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update proposal #{proposal_id} status to {status}: {e}")


def _notify_admin(proposal_id, notif_type, message):
    """Insert a system notification for the admin."""
    type_map = {"success": "success", "warning": "warning", "error": "error", "info": "info"}
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO system_notifications (type, title, message, source, visibility)
            VALUES (%s, %s, %s, 'improvement_pipeline', 'admin')
            """,
            (
                type_map.get(notif_type, "info"),
                f"Improvement #{proposal_id}",
                message,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to create notification for proposal #{proposal_id}: {e}")
```

**Step 2: Add the auto-execute trigger to the approve endpoint**

In the `improvements_approve_proposal()` function (line 1198), add the background thread spawn AFTER the sandbox creation block and BEFORE the `return jsonify(...)` (around line 1333).

Insert before line 1334 (`return jsonify(...)`):

```python
        # =====================================================================
        # AUTO-EXECUTE: Run code gen → sandbox → test in background (Phase 4)
        # =====================================================================
        import threading

        auto_exec_thread = threading.Thread(
            target=_auto_execute_proposal,
            args=(proposal_id,),
            daemon=True,
        )
        auto_exec_thread.start()
        logger.info(f"Auto-execution thread started for proposal #{proposal_id}")
```

Update the return jsonify to include the auto-execute info:

```python
        return jsonify(
            {
                "success": True,
                "message": "Proposal approved — auto-execution started",
                "proposal_id": proposal_id,
                "plan_generated": existing_plan is None,
                "steps_count": len(plan_steps) if plan_steps else 0,
                "sandbox": sandbox_info,
                "auto_execution": True,
            }
        )
```

**Step 3: Commit**

```bash
git add platform_v2/tools/improvements/routes.py
git commit -m "feat(improvements): auto-execute code gen → sandbox → test after approval"
```

---

### Task 4: Add weekly batch scheduler job

**Files:**
- Modify: `platform_v2/app.py`

**Step 1: Add batch_medium_issues to the scheduler**

In `init_consciousness_scheduler()` (line 3291 of app.py), add the weekly batch job.

Add the import (after the existing imports around line 3307):
```python
        from services.scan_pipeline import batch_medium_issues
```

Add the job (after the existing weekly_memory_consolidation job, around line 3345):
```python
        # Weekly medium-issue batch (Sundays at 2 AM)
        scheduler.add_job(
            batch_medium_issues,
            trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
            id="batch_medium_issues",
            name="Weekly Code Issue Batch",
            replace_existing=True,
        )
```

**Step 2: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(scheduler): add weekly batch job for medium code issues"
```

---

### Task 5: Integration verification

**Step 1: Syntax check all modified files**

```bash
python3 -c "import ast; ast.parse(open('platform_v2/services/scan_pipeline.py').read()); print('scan_pipeline.py: OK')"
python3 -c "import ast; ast.parse(open('platform_v2/tools/code_sentinel/routes.py').read()); print('code_sentinel: OK')"
python3 -c "import ast; ast.parse(open('platform_v2/tools/improvements/routes.py').read()); print('improvements: OK')"
python3 -c "import ast; ast.parse(open('platform_v2/app.py').read()); print('app.py: OK')"
```

**Step 2: Test scan_pipeline functions directly in container**

```bash
docker compose restart archie_platform
sleep 15
docker exec archie_platform python3 -c "
from services.scan_pipeline import process_scan_results, batch_medium_issues
# Test with mock issues
result = process_scan_results(
    scan_id=99999,
    issues=[
        {'type': 'security', 'severity': 'critical', 'message': 'Test issue', 'line': 1},
        {'type': 'quality', 'severity': 'medium', 'message': 'Style issue', 'line': 2},
    ],
    file_path='test/fake_file.py'
)
print('process_scan_results:', result)

batch_result = batch_medium_issues()
print('batch_medium_issues:', batch_result)
"
```

Expected: `proposals_created: 1, medium_queued: 0` (medium won't have code_issues rows for scan 99999), batch returns `proposals_created: 0`

**Step 3: Test all modules load**

```bash
# Verify all modules return 200
curl -s -w "%{http_code}" http://192.168.1.200:3000/dev-hq/ -o /dev/null -b /tmp/archie_cookies.txt
curl -s -w "%{http_code}" http://192.168.1.200:3000/tools/code_sentinel/ -o /dev/null -b /tmp/archie_cookies.txt
curl -s -w "%{http_code}" http://192.168.1.200:3000/tools/improvements-lab/ -o /dev/null -b /tmp/archie_cookies.txt
```

All should return 200.

**Step 4: End-to-end test — run a real scan**

```bash
curl -s -X POST http://192.168.1.200:3000/tools/code_sentinel/api/health/scan \
  -H "Content-Type: application/json" \
  -b /tmp/archie_cookies.txt \
  -d '{"file_path": "platform_v2/services/scan_pipeline.py"}' | python3 -m json.tool | head -15
```

Verify: scan completes, check if any proposals were auto-created (depends on whether the scan finds critical/high issues).

**Step 5: Final commit and push**

```bash
git add -A
git push
```

**Step 6: Update Dev HQ**

- Complete tasks #709 and #710
- Log ADR for the pipeline wiring
- Update project understanding
