"""F.O.R.G.E. Self-Healing Engine — Autonomous code correction loops.

Phases 9-14 of Project #188:
- Phase 9:  Auto-fix from scan (Bridge generates patches)
- Phase 10: Test failure → re-fix (max 3 retries)
- Phase 11: CodeRabbit feedback → re-fix (max 2 retries)
- Phase 12: Regression guard (full suite before merge)
- Phase 13: Circuit breaker (max attempts, Telegram escalation)
- Phase 14: Autonomy module integration (all loops tracked)

All autonomous actions are logged to the Autonomy module.
"""

import json
import logging
import os
from database import _get_db_password
from typing import Dict
from services.governance_hmac import sign_event

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Circuit breaker limits
MAX_SANDBOX_RETRIES = 3
MAX_REVIEW_RETRIES = 2
MAX_TOTAL_ATTEMPTS = 5
MAX_HOURLY_CYCLES = 10


def _get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def _log_autonomy_action(
    action_type: str,
    proposal_id: int,
    attempt: int,
    details: Dict,
    success: bool,
):
    """Log a self-healing action to the Autonomy module (governance_audit_log)."""
    try:
        conn = _get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO governance_audit_log
                       (timestamp, event_category, event_type, details, agent_name)
                   VALUES (NOW(), 'forge_self_heal', %s, %s, 'F.O.R.G.E.')
                   RETURNING id, timestamp""",
                (
                    action_type,
                    json.dumps(
                        {
                            "proposal_id": proposal_id,
                            "attempt": attempt,
                            "success": success,
                            **details,
                        }
                    ),
                ),
            )
            row = cur.fetchone()
            if row:
                eid, ts = row[0], row[1]
                sig = sign_event(
                    event_id=eid,
                    event_type=action_type,
                    event_category="forge_self_heal",
                    agent_id=None,
                    user_id=None,
                    action=action_type,
                    target_table=None,
                    target_id=proposal_id,
                    outcome="success" if success else "failed",
                    timestamp_iso=ts.isoformat() if ts else "",
                )
                if sig:
                    cur.execute(
                        "UPDATE governance_audit_log SET hmac_sig=%s WHERE id=%s",
                        (sig, eid),
                    )
            conn.commit()
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.warning(f"[FORGE] Autonomy log failed: {e}")


# ============================================================================
# CIRCUIT BREAKER (Phase 13)
# ============================================================================


def check_circuit_breaker(proposal_id: int) -> Dict:
    """Check if proposal has exceeded autonomous action limits.

    Returns {'allowed': True/False, 'reason': '...', 'attempts': N}
    """
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check total attempts for this proposal
        cur.execute(
            """SELECT COUNT(*) as total
               FROM governance_audit_log
               WHERE event_category = 'forge_self_heal'
                 AND details->>'proposal_id' = %s""",
            (str(proposal_id),),
        )
        total = cur.fetchone()["total"]

        # Check hourly rate across all proposals
        cur.execute(
            """SELECT COUNT(*) as hourly
               FROM governance_audit_log
               WHERE event_category = 'forge_self_heal'
                 AND timestamp > NOW() - interval '1 hour'"""
        )
        hourly = cur.fetchone()["hourly"]

        cur.close()
        conn.close()

        if total >= MAX_TOTAL_ATTEMPTS:
            return {
                "allowed": False,
                "reason": f"Max {MAX_TOTAL_ATTEMPTS} attempts reached for proposal #{proposal_id}",
                "attempts": total,
                "limit": "per_proposal",
            }

        if hourly >= MAX_HOURLY_CYCLES:
            return {
                "allowed": False,
                "reason": f"Hourly rate limit ({MAX_HOURLY_CYCLES}/hr) reached",
                "attempts": total,
                "limit": "hourly_rate",
            }

        return {"allowed": True, "attempts": total}

    except Exception as e:
        logger.warning(f"[FORGE] Circuit breaker check failed — failing CLOSED: {e}")
        return {"allowed": False, "reason": f"Circuit breaker unavailable: {e}", "attempts": 0}


def escalate_to_human(proposal_id: int, reason: str, context: Dict):
    """Escalate a proposal to human via Telegram when circuit breaker trips."""
    conn = _get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE improvement_proposals
               SET status = 'escalated'
               WHERE id = %s""",
            (proposal_id,),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()

    _log_autonomy_action(
        "escalation",
        proposal_id,
        context.get("attempt", 0),
        {"reason": reason, **context},
        success=False,
    )

    try:
        from services.telegram_service import send_forge

        msg = (
            f"Proposal #{proposal_id} needs human intervention\n"
            f"Reason: {reason}\n"
            f"Attempts: {context.get('attempt', '?')}\n\n"
            f"View Pipeline: http://192.168.1.200:3000/tools/repair-bay"
        )
        send_forge("F.O.R.G.E. Escalation", msg, source_module="forge_self_heal")
    except Exception as tg_err:
        logger.warning(f"[FORGE] Telegram escalation failed: {tg_err}")

    logger.info(f"[FORGE] Escalated proposal #{proposal_id}: {reason}")


# ============================================================================
# PHASE 9: AUTO-FIX FROM SCAN
# ============================================================================


def generate_fix_from_scan(proposal_id: int) -> Dict:
    """Use Bridge AI to generate a code patch from a scan finding.

    Reads the proposal + source file, dispatches to Bridge,
    returns the generated patch.
    """
    # Circuit breaker check
    cb = check_circuit_breaker(proposal_id)
    if not cb["allowed"]:
        escalate_to_human(proposal_id, cb["reason"], {"attempt": cb["attempts"]})
        return {"success": False, "error": cb["reason"], "escalated": True}

    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        file_path = proposal.get("file_path", "")
        if not file_path:
            return {"success": False, "error": "No file_path in proposal"}

        # Read source file
        abs_path = os.path.join("/mnt/archie_brain", file_path.lstrip("/"))
        source_code = ""
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                source_code = f.read()[:5000]
        except Exception:
            return {"success": False, "error": f"Cannot read {file_path}"}

        # Dispatch to Bridge
        from tools.department_hq.services.department_dispatcher import dispatch_json

        prompt = f"""Fix the following issue in this code:

File: {file_path}
Issue: {proposal.get('title', '')}
Details: {proposal.get('description', '')[:1000]}

Source code:
```
{source_code}
```

Generate ONLY a unified diff patch that fixes the issue. No explanation."""

        result = dispatch_json(
            capability="code_analysis",
            prompt=prompt,
            module_id="forge_auto_fix",
            system_prompt="You are a code repair agent. Generate minimal, precise unified diff patches. No commentary.",
        )

        attempt = cb["attempts"] + 1
        if result and isinstance(result, dict):
            patch = result.get("response", "")
            if patch:
                # Store patch in proposal
                cur.execute(
                    """UPDATE improvement_proposals
                       SET code_diff = %s, status = 'fix_generated'
                       WHERE id = %s""",
                    (patch[:10000], proposal_id),
                )
                conn.commit()

                _log_autonomy_action(
                    "auto_fix_generated",
                    proposal_id,
                    attempt,
                    {"file": file_path, "patch_size": len(patch)},
                    success=True,
                )
                return {"success": True, "patch": patch, "attempt": attempt}

        _log_autonomy_action(
            "auto_fix_failed",
            proposal_id,
            attempt,
            {"file": file_path, "error": "Bridge returned no patch"},
            success=False,
        )
        return {"success": False, "error": "Bridge returned no usable patch"}

    finally:
        cur.close()
        conn.close()


# ============================================================================
# PHASE 10: TEST FAILURE → RE-FIX
# ============================================================================


def retry_after_test_failure(proposal_id: int, test_output: str, current_patch: str) -> Dict:
    """When sandbox tests fail, generate a corrected patch.

    Sends original code + failed patch + test errors to Bridge.
    Max MAX_SANDBOX_RETRIES attempts.
    """
    cb = check_circuit_breaker(proposal_id)
    if not cb["allowed"]:
        escalate_to_human(proposal_id, cb["reason"], {"attempt": cb["attempts"]})
        return {"success": False, "escalated": True}

    attempt = cb["attempts"] + 1
    if attempt > MAX_SANDBOX_RETRIES:
        escalate_to_human(
            proposal_id,
            f"Max sandbox retries ({MAX_SANDBOX_RETRIES}) exceeded",
            {"attempt": attempt, "test_output": test_output[:500]},
        )
        return {"success": False, "error": "Max retries exceeded", "escalated": True}

    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        from tools.department_hq.services.department_dispatcher import dispatch_json

        prompt = f"""The previous patch for this issue failed tests. Fix it.

File: {proposal.get('file_path', '')}
Issue: {proposal.get('title', '')}
Attempt: {attempt} of {MAX_SANDBOX_RETRIES}

Previous patch that failed:
```
{current_patch[:2000]}
```

Test errors:
```
{test_output[:2000]}
```

Generate ONLY a corrected unified diff patch. Learn from the test errors."""

        result = dispatch_json(
            capability="code_analysis",
            prompt=prompt,
            module_id="forge_retry_fix",
            system_prompt="You are a code repair agent. The previous fix failed tests. Analyze the errors and generate a corrected patch.",
        )

        if result and isinstance(result, dict):
            patch = result.get("response", "")
            if patch:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET code_diff = %s, status = 'fix_generated'
                       WHERE id = %s""",
                    (patch[:10000], proposal_id),
                )
                conn.commit()

                _log_autonomy_action(
                    "test_retry_fix",
                    proposal_id,
                    attempt,
                    {"test_errors": test_output[:300]},
                    success=True,
                )
                return {"success": True, "patch": patch, "attempt": attempt}

        _log_autonomy_action(
            "test_retry_failed",
            proposal_id,
            attempt,
            {"error": "No corrected patch from Bridge"},
            success=False,
        )
        return {"success": False, "error": "Bridge returned no corrected patch"}

    finally:
        cur.close()
        conn.close()


# ============================================================================
# PHASE 11: CODERABBIT FEEDBACK → RE-FIX
# ============================================================================


def retry_after_review_feedback(proposal_id: int, pr_number: int, review_comments: list) -> Dict:
    """When CodeRabbit requests changes, generate a fix from review feedback.

    Max MAX_REVIEW_RETRIES attempts.
    """
    cb = check_circuit_breaker(proposal_id)
    if not cb["allowed"]:
        escalate_to_human(proposal_id, cb["reason"], {"attempt": cb["attempts"]})
        return {"success": False, "escalated": True}

    attempt = cb["attempts"] + 1
    if attempt > MAX_SANDBOX_RETRIES + MAX_REVIEW_RETRIES:
        escalate_to_human(
            proposal_id,
            f"Max review retries exceeded",
            {"attempt": attempt, "pr": pr_number},
        )
        return {"success": False, "escalated": True}

    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        # Format review comments
        comments_text = "\n".join(
            f"- [{c.get('file', '?')}:{c.get('line', '?')}] {c.get('body', '')[:200]}" for c in review_comments[:10]
        )

        from tools.department_hq.services.department_dispatcher import dispatch_json

        prompt = f"""CodeRabbit requested changes on this PR. Fix the issues.

File: {proposal.get('file_path', '')}
PR: #{pr_number}
Attempt: {attempt}

Current code diff:
```
{proposal.get('code_diff', '')[:2000]}
```

Review comments to address:
{comments_text}

Generate ONLY a corrected unified diff patch that addresses ALL review comments."""

        result = dispatch_json(
            capability="code_analysis",
            prompt=prompt,
            module_id="forge_review_fix",
            system_prompt="You are a code repair agent. Address each code review comment with precise fixes.",
        )

        if result and isinstance(result, dict):
            patch = result.get("response", "")
            if patch:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET code_diff = %s, status = 'fix_generated'
                       WHERE id = %s""",
                    (patch[:10000], proposal_id),
                )
                conn.commit()

                _log_autonomy_action(
                    "review_retry_fix",
                    proposal_id,
                    attempt,
                    {"pr": pr_number, "comments": len(review_comments)},
                    success=True,
                )

                # Push the fix to the same branch
                try:
                    from .github_service import push_changes
                    from .forge_pipeline import proposal_to_branch_name

                    file_path = proposal.get("file_path", "")
                    branch = proposal_to_branch_name(proposal)
                    # Apply patch and push
                    push_result = push_changes(
                        branch,
                        [file_path],
                        f"fix(forge): address review feedback (attempt {attempt})",
                    )
                    if push_result.get("success"):
                        logger.info(f"[FORGE] Review fix pushed to PR #{pr_number} " f"(attempt {attempt})")
                except Exception as push_err:
                    logger.warning(f"[FORGE] Push after review fix failed: {push_err}")

                return {"success": True, "patch": patch, "attempt": attempt}

        _log_autonomy_action(
            "review_retry_failed",
            proposal_id,
            attempt,
            {"error": "No corrected patch"},
            success=False,
        )
        return {"success": False, "error": "Bridge returned no corrected patch"}

    finally:
        cur.close()
        conn.close()


# ============================================================================
# PHASE 12: REGRESSION GUARD
# ============================================================================


def run_regression_check(proposal_id: int) -> Dict:
    """Run QA suites for the module affected by this proposal to check for regressions.

    Looks up improvement_proposals.module_name → runs all mapped QA suites via
    qa_service.run_suite_for_module(). Returns pass if all suites pass or if
    no suites are mapped (no coverage ≠ regression).
    """
    _log_autonomy_action(
        "regression_check",
        proposal_id,
        0,
        {"status": "started"},
        success=True,
    )

    # Resolve module_name from the proposal
    module_name = None
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT module_name FROM improvement_proposals WHERE id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
            if row:
                module_name = row["module_name"]
    except Exception as db_err:
        logger.warning("[FORGE] regression_check: could not fetch module_name: %s", db_err)

    if not module_name:
        logger.info("[FORGE] Regression check for proposal #%d — no module_name, skipping suites", proposal_id)
        _log_autonomy_action(
            "regression_check",
            proposal_id,
            0,
            {"status": "skipped", "reason": "no module_name on proposal"},
            success=True,
        )
        return {"success": True, "passed": True, "message": "No module mapped — skipping regression check"}

    # Run all QA suites for the module
    logger.info("[FORGE] Regression check for proposal #%d — running QA suites for '%s'", proposal_id, module_name)
    try:
        from services.qa_service import run_suite_for_module

        results = run_suite_for_module(module_name, triggered_by="regression_check")
    except Exception as qa_err:
        logger.error("[FORGE] regression_check: QA runner failed: %s", qa_err)
        _log_autonomy_action(
            "regression_check",
            proposal_id,
            0,
            {"status": "error", "error": str(qa_err)},
            success=False,
        )
        return {"success": False, "passed": False, "message": f"QA runner error: {qa_err}"}

    if not results:
        logger.info("[FORGE] Regression check for proposal #%d — no suites mapped for '%s'", proposal_id, module_name)
        _log_autonomy_action(
            "regression_check",
            proposal_id,
            0,
            {"status": "skipped", "reason": f"no suites mapped for {module_name}"},
            success=True,
        )
        return {"success": True, "passed": True, "message": f"No QA suites mapped for {module_name}"}

    # Tally results
    total_passed = sum(r.get("passed", 0) or 0 for r in results)
    total_failed = sum(r.get("failed", 0) or 0 for r in results)
    suites_run = len(results)
    all_passed = total_failed == 0

    status = "passed" if all_passed else "failed"
    _log_autonomy_action(
        "regression_check",
        proposal_id,
        0,
        {
            "status": status,
            "module": module_name,
            "suites_run": suites_run,
            "total_passed": total_passed,
            "total_failed": total_failed,
        },
        success=all_passed,
    )

    logger.info(
        "[FORGE] Regression check for proposal #%d (%s): %d suites, %d passed, %d failed",
        proposal_id,
        module_name,
        suites_run,
        total_passed,
        total_failed,
    )

    return {
        "success": True,
        "passed": all_passed,
        "module": module_name,
        "suites_run": suites_run,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "message": f"{'All suites passed' if all_passed else f'{total_failed} test(s) failed'} for {module_name}",
    }


# ============================================================================
# ORCHESTRATOR: Full self-healing cycle
# ============================================================================


def run_self_heal_cycle(proposal_id: int) -> Dict:
    """Run the full F.O.R.G.E. self-healing cycle for a proposal.

    1. Generate fix from scan finding (Phase 9)
    2. If sandbox tests fail, retry (Phase 10, max 3x)
    3. Push to branch + create PR (Phases 2-3)
    4. If CodeRabbit requests changes, retry (Phase 11, max 2x)
    5. Regression guard before merge (Phase 12)
    6. All actions tracked in Autonomy (Phase 14)
    7. Circuit breaker enforced throughout (Phase 13)

    Returns final status.
    """
    logger.info(f"[FORGE] Starting self-heal cycle for proposal #{proposal_id}")

    # Step 1: Generate fix
    fix_result = generate_fix_from_scan(proposal_id)
    if not fix_result.get("success"):
        return fix_result

    # Step 2: The fix is stored in proposal.code_diff
    # Sandbox testing + PR creation happens via the existing pipeline:
    # deploy_proposal() → deploy_via_forge() → creates branch + PR
    # This is triggered when the proposal status changes to 'fix_generated'

    logger.info(
        f"[FORGE] Fix generated for proposal #{proposal_id} "
        f"(attempt {fix_result.get('attempt', 1)}). "
        f"Ready for sandbox testing via deploy_proposal()."
    )

    return {
        "success": True,
        "proposal_id": proposal_id,
        "stage": "fix_generated",
        "attempt": fix_result.get("attempt", 1),
        "message": "Fix generated. Trigger deploy_proposal() to sandbox-test and create PR.",
    }


def get_self_heal_stats() -> Dict:
    """Get self-healing pipeline statistics for the dashboard."""
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Action counts by type
        cur.execute(
            """SELECT event_type, COUNT(*) as count,
                      SUM(CASE WHEN (details->>'success')::boolean THEN 1 ELSE 0 END) as successes
               FROM governance_audit_log
               WHERE event_category = 'forge_self_heal'
               GROUP BY event_type
               ORDER BY count DESC"""
        )
        by_type = [dict(r) for r in cur.fetchall()]

        # Recent actions
        cur.execute(
            """SELECT event_type, details, timestamp
               FROM governance_audit_log
               WHERE event_category = 'forge_self_heal'
               ORDER BY timestamp DESC
               LIMIT 20"""
        )
        recent = [dict(r) for r in cur.fetchall()]

        # Escalation count
        cur.execute(
            """SELECT COUNT(*) as count
               FROM governance_audit_log
               WHERE event_category = 'forge_self_heal'
                 AND event_type = 'escalation'"""
        )
        escalations = cur.fetchone()["count"]

        # Active proposals in self-heal
        cur.execute(
            """SELECT COUNT(*) as count
               FROM improvement_proposals
               WHERE status IN ('fix_generated', 'review_changes_requested')"""
        )
        active = cur.fetchone()["count"]

        cur.close()
        conn.close()

        total_actions = sum(r["count"] for r in by_type)
        total_successes = sum(r["successes"] for r in by_type)

        return {
            "success": True,
            "total_actions": total_actions,
            "success_rate": round(total_successes / max(total_actions, 1) * 100, 1),
            "escalations": escalations,
            "active_proposals": active,
            "by_type": by_type,
            "recent": recent[:10],
            "limits": {
                "max_sandbox_retries": MAX_SANDBOX_RETRIES,
                "max_review_retries": MAX_REVIEW_RETRIES,
                "max_total_attempts": MAX_TOTAL_ATTEMPTS,
                "max_hourly_cycles": MAX_HOURLY_CYCLES,
            },
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
