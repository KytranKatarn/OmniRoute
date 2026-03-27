"""Audit pipeline — auto-creates Repair Bay proposals from Code Health audit findings.

Called after audit_single_module() completes. Red (security) issues get individual
high-priority proposals with Tier 2 (human) approval. Yellow (quality) issues get
medium-priority proposals with Tier 1 (auto) approval. Info (style) issues are skipped.

Import:
    from services.audit_pipeline import process_audit_findings, dispatch_proposal_fix,
        dispatch_audit_proposals
"""

import json
import logging
import os
import sys

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Map audit severity tiers to proposal attributes
_TIER_CONFIG = {
    "red": {
        "priority": "critical",
        "risk_level": "high",
        "approval_tier": 2,
        "approval_priority": 3,
    },
    "yellow": {
        "priority": "medium",
        "risk_level": "medium",
        "approval_tier": 1,
        "approval_priority": 7,
    },
}


def process_audit_findings(module_name, issues_list):
    """Process audit findings and create Repair Bay proposals for red/yellow issues.

    Args:
        module_name: The module that was audited (e.g. 'consciousness')
        issues_list: List of issue dicts from audit_single_module, each with
                     code, severity (red/yellow/info), file, detail

    Returns:
        {"proposals_created": int, "skipped_duplicates": int, "info_skipped": int}
    """
    proposals_created = 0
    skipped = 0
    info_skipped = 0

    for issue in issues_list:
        severity = issue.get("severity", "info")

        # Skip info-tier issues — no proposals for style findings
        if severity not in _TIER_CONFIG:
            info_skipped += 1
            continue

        try:
            file_path = f"platform_v2/tools/{module_name}/{issue['file']}"
            issue_code = issue["code"]

            if _has_open_audit_proposal(file_path, issue_code):
                skipped += 1
                continue

            proposal_id = _create_audit_proposal(issue, module_name, file_path)
            if proposal_id:
                proposals_created += 1
        except Exception as e:
            logger.warning(
                "Failed to create audit proposal for %s/%s: %s",
                module_name,
                issue.get("code"),
                e,
            )

    logger.info(
        "Audit pipeline: %s — %d proposals created, %d duplicates skipped, %d info skipped",
        module_name,
        proposals_created,
        skipped,
        info_skipped,
    )

    return {
        "proposals_created": proposals_created,
        "skipped_duplicates": skipped,
        "info_skipped": info_skipped,
    }


def _has_open_audit_proposal(file_path, issue_code):
    """Check if an open proposal already exists for this file + issue code."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT id FROM improvement_proposals
            WHERE status NOT IN ('deployed', 'implemented', 'rejected', 'archived', 'failed')
              AND metadata->>'source' = 'code_health_audit'
              AND metadata->>'file_path' = %s
              AND metadata->>'issue_code' = %s
            LIMIT 1
            """,
            (file_path, issue_code),
        )
        return cur.fetchone() is not None


def _create_audit_proposal(issue, module_name, file_path):
    """Create an improvement proposal from a single audit finding. Returns proposal_id."""
    severity = issue["severity"]
    issue_code = issue["code"]
    detail = issue.get("detail", "")
    fname = issue.get("file", "")
    config = _TIER_CONFIG[severity]

    title = f"[{config['priority'].upper()}] {issue_code}: {fname}"
    if detail:
        title = f"{title} ({detail})"
    # Truncate title to reasonable length
    title = title[:120]

    description = (
        f"Code Health audit detected a **{severity}** issue in `{file_path}`.\n\n"
        f"**Check:** {issue_code}\n"
        f"**Module:** {module_name}\n"
    )
    if detail:
        description += f"**Detail:** {detail}\n"

    description += (
        f"\n**Severity tier:** {severity} "
        f"({'security — requires immediate attention' if severity == 'red' else 'quality — should be addressed'})\n"
    )

    metadata = json.dumps(
        {
            "source": "code_health_audit",
            "file_path": file_path,
            "issue_code": issue_code,
            "severity_tier": severity,
            "module_name": module_name,
            "detail": detail,
            "auto_generated": True,
        }
    )

    with get_db_cursor(commit=True) as (conn, cur):
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
                issue_code.lower(),
                description,
                "",
                f"Auto-detected by Code Health audit of {module_name}",
                config["priority"],
                config["risk_level"],
                metadata,
            ),
        )
        proposal_id = cur.fetchone()["id"]
        logger.info(
            "Created audit proposal #%d for %s %s in %s",
            proposal_id,
            severity,
            issue_code,
            file_path,
        )

    # Route through autonomy approval queue
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from agent_loop import request_approval

        request_approval(
            action_type="improvement_approve",
            action_data={
                "proposal_id": proposal_id,
                "title": title,
                "file_path": file_path,
                "severity": severity,
                "risk_level": config["risk_level"],
            },
            reason=f"Auto-generated from Code Health audit: {issue_code} in {module_name}",
            requested_by="audit_pipeline",
            priority=config["approval_priority"],
            tier=config["approval_tier"],
        )
    except Exception as approval_err:
        logger.warning(
            "Approval queue submission failed for audit proposal #%d: %s",
            proposal_id,
            approval_err,
        )

    return proposal_id


# Map issue codes to Bridge dispatch capabilities
_ISSUE_CAPABILITY_MAP = {
    "HARDCODED_SECRET": "vulnerability_scan",
    "SQL_INJECTION_RISK": "vulnerability_scan",
    "DIRECT_OLLAMA": "code_review",
    "DIRECT_CLOUD": "code_review",
    "BARE_EXCEPT": "code_review",
    "LARGE_FILE": "code_review",
    "MISSING_INIT": "code",
}

_FIX_PROMPTS = {
    "HARDCODED_SECRET": (
        "Replace the hardcoded secret with an os.getenv() call. "
        "Use a descriptive env var name. Keep all other code unchanged."
    ),
    "SQL_INJECTION_RISK": (
        "Replace f-string or %-formatting in .execute() calls with parameterized queries (%s placeholders). "
        "Keep all other code unchanged."
    ),
    "DIRECT_OLLAMA": (
        "Replace the direct call_ollama() call with Bridge dispatcher: "
        "from bridge_dispatcher import get_dispatcher; get_dispatcher().dispatch(). "
        "Keep all other code unchanged."
    ),
    "DIRECT_CLOUD": (
        "Replace the direct cloud API call with Bridge dispatcher: "
        "from bridge_dispatcher import get_dispatcher; get_dispatcher().dispatch(). "
        "Keep all other code unchanged."
    ),
    "BARE_EXCEPT": (
        "Replace bare 'except:' with 'except Exception:' (or a more specific exception type if obvious). "
        "Keep all other code unchanged."
    ),
    "LARGE_FILE": (
        "Analyze this large file and suggest how to split it into smaller modules. "
        "Identify logical groupings of functions that could become separate files. "
        "Return a plan, not a rewrite."
    ),
    "MISSING_INIT": ("Create an __init__.py that imports and exposes the module's public Blueprint and key functions."),
}


def dispatch_proposal_fix(proposal_id):
    """Dispatch a single audit proposal to a Bridge agent for AI-powered fix generation.

    Reads the source file, sends it to the appropriate department agent via Bridge,
    and stores the generated diff in the proposal's code_changes field.

    Args:
        proposal_id: The improvement_proposals.id to process

    Returns:
        {"success": bool, "proposal_id": int, "agent": str, "diff_lines": int}
        or {"success": False, "error": str}
    """
    # Load proposal + metadata
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, title, description, metadata, status
               FROM improvement_proposals WHERE id = %s""",
            (proposal_id,),
        )
        proposal = cur.fetchone()

    if not proposal:
        return {"success": False, "error": f"Proposal #{proposal_id} not found"}

    if proposal["status"] not in ("pending", "approved"):
        return {
            "success": False,
            "error": f"Proposal #{proposal_id} status is '{proposal['status']}', expected pending/approved",
        }

    meta = proposal["metadata"] if isinstance(proposal["metadata"], dict) else json.loads(proposal["metadata"] or "{}")
    if meta.get("source") != "code_health_audit":
        return {"success": False, "error": f"Proposal #{proposal_id} is not from code_health_audit"}

    file_path = meta.get("file_path", "")
    issue_code = meta.get("issue_code", "")
    module_name = meta.get("module_name", "")

    # Read source file
    abs_path = os.path.join("/mnt/archie_brain", file_path)
    if not os.path.isfile(abs_path):
        return {"success": False, "error": f"Source file not found: {file_path}"}

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            source_content = f.read()
    except Exception as e:
        return {"success": False, "error": f"Failed to read {file_path}: {e}"}

    # Determine capability and build prompt
    capability = _ISSUE_CAPABILITY_MAP.get(issue_code, "code_review")
    fix_instruction = _FIX_PROMPTS.get(issue_code, f"Fix the {issue_code} issue in this file.")

    prompt = (
        f"You are fixing a Code Health audit finding in the A.R.C.H.I.E. platform.\n\n"
        f"**Issue:** {issue_code}\n"
        f"**File:** {file_path}\n"
        f"**Module:** {module_name}\n"
        f"**Detail:** {meta.get('detail', '')}\n\n"
        f"**Instructions:** {fix_instruction}\n\n"
        f"Return ONLY the complete fixed file content. No explanations, no markdown fences.\n\n"
        f"--- SOURCE FILE ---\n{source_content}"
    )

    # Dispatch to Bridge
    try:
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            capability=capability,
            prompt=prompt,
            module_id="audit_pipeline",
            system_prompt=(
                "You are a code repair agent. Fix ONLY the specific issue described. "
                "Return the complete fixed file. Do not add comments, docstrings, or "
                "other changes beyond the fix. Preserve all existing code exactly."
            ),
            priority="high" if meta.get("severity_tier") == "red" else "normal",
        )
    except Exception as e:
        logger.error("Bridge dispatch failed for proposal #%d: %s", proposal_id, e)
        return {"success": False, "error": f"Bridge dispatch failed: {e}"}

    if not result or not getattr(result, "response", None):
        logger.warning("Bridge returned empty response for proposal #%d", proposal_id)
        return {"success": False, "error": "Bridge returned empty response"}

    fixed_content = result.response.strip()
    agent_name = getattr(result, "agent_name", "unknown")

    # Generate diff
    try:
        from code_diff_engine import CodeDiffEngine

        engine = CodeDiffEngine()
        diff_result = engine.generate_diff(
            old_content=source_content,
            new_content=fixed_content,
            filename=os.path.basename(file_path),
        )
        diff_text = diff_result.get("diff_text", "")
        diff_stats = diff_result.get("stats", {})
    except Exception as e:
        logger.warning("Diff generation failed for proposal #%d: %s", proposal_id, e)
        diff_text = f"--- Fix generated by {agent_name} ---\n(diff generation failed: {e})"
        diff_stats = {}

    # Update proposal with diff and mark ready for review
    with get_db_cursor(commit=True) as (conn, cur):
        updated_meta = {**meta, "agent_name": agent_name, "diff_stats": diff_stats}
        cur.execute(
            """UPDATE improvement_proposals
               SET code_changes = %s, status = 'ready_for_review',
                   metadata = %s::jsonb
               WHERE id = %s""",
            (diff_text, json.dumps(updated_meta), proposal_id),
        )

    logger.info(
        "Proposal #%d fix generated by %s — %d lines added, %d removed",
        proposal_id,
        agent_name,
        diff_stats.get("added", 0),
        diff_stats.get("removed", 0),
    )

    return {
        "success": True,
        "proposal_id": proposal_id,
        "agent": agent_name,
        "diff_lines": diff_stats.get("added", 0) + diff_stats.get("removed", 0),
    }


def dispatch_audit_proposals(limit=20):
    """Batch-dispatch pending audit proposals to Bridge agents for fix generation.

    Finds pending proposals sourced from code_health_audit and dispatches each one.
    Red (security) proposals are processed first.

    Args:
        limit: Max proposals to process in one batch

    Returns:
        {"dispatched": int, "failed": int, "skipped": int}
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, metadata FROM improvement_proposals
               WHERE status IN ('pending', 'approved')
                 AND metadata->>'source' = 'code_health_audit'
                 AND (metadata->>'dispatch_attempted') IS NULL
               ORDER BY
                 CASE WHEN priority = 'critical' THEN 0 ELSE 1 END,
                 created_at ASC
               LIMIT %s""",
            (limit,),
        )
        proposals = cur.fetchall()

    if not proposals:
        logger.info("Audit dispatch: no pending proposals to process")
        return {"dispatched": 0, "failed": 0, "skipped": 0}

    dispatched = 0
    failed = 0

    for row in proposals:
        proposal_id = row["id"]
        try:
            result = dispatch_proposal_fix(proposal_id)
            if result.get("success"):
                dispatched += 1
            else:
                failed += 1
                logger.warning(
                    "Proposal #%d dispatch failed: %s",
                    proposal_id,
                    result.get("error"),
                )
                # Mark as attempted to avoid retry loops
                _mark_dispatch_attempted(proposal_id, result.get("error", ""))
        except Exception as e:
            failed += 1
            logger.error("Proposal #%d dispatch error: %s", proposal_id, e)
            _mark_dispatch_attempted(proposal_id, str(e))

    logger.info(
        "Audit dispatch batch: %d dispatched, %d failed out of %d",
        dispatched,
        failed,
        len(proposals),
    )

    return {"dispatched": dispatched, "failed": failed, "skipped": 0}


def _mark_dispatch_attempted(proposal_id, error_msg):
    """Mark a proposal as dispatch-attempted to prevent retry loops."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE improvement_proposals
               SET metadata = metadata || %s::jsonb
               WHERE id = %s""",
            (json.dumps({"dispatch_attempted": True, "dispatch_error": error_msg[:200]}), proposal_id),
        )
