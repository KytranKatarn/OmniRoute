"""Audit pipeline — auto-creates Repair Bay proposals from Code Health audit findings.

Called after audit_single_module() completes. Red (security) issues get individual
high-priority proposals with Tier 2 (human) approval. Yellow (quality) issues get
medium-priority proposals with Tier 1 (auto) approval. Info (style) issues are skipped.

Import:
    from services.audit_pipeline import process_audit_findings, dispatch_proposal_fix,
        dispatch_audit_proposals, verify_fix_deployment
"""

import json
import logging
import os
import sys

from database import get_db_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# C.R.E.E.D. Governance Gates
# ---------------------------------------------------------------------------

# Department-to-module mapping for self-modification detection
_DEPARTMENT_MODULE_MAP = {
    "Engineering & Technology": [
        "repair_bay",
        "consciousness",
        "dev_hq",
    ],
    "Security & Compliance": [
        "security_network",
        "backup_manager",
    ],
    "Operations & Infrastructure": [
        "system_operations",
        "media_hub",
    ],
    "Creative & Design": [
        "media_studio",
        "game_studio",
        "content_studio",
    ],
}


def creed_gate_pre_fix(proposal_id, agent_id):
    """C.R.E.E.D. Gate 1 — called BEFORE an agent generates a fix.

    Checks:
        1. Self-modification constraint (agent cannot fix its own department's module)
        2. Welfare check (stress/energy thresholds)
        3. Capability check (agent exists and is active)

    Returns:
        {"approved": bool, "reason": str}
    """
    reason = "all checks passed"
    approved = True

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # --- Load proposal metadata ---
            cur.execute(
                "SELECT metadata FROM improvement_proposals WHERE id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
            if not row:
                approved = False
                reason = f"proposal #{proposal_id} not found"
                _log_creed_gate(
                    "repair_fix_generation",
                    "denied" if not approved else "approved",
                    agent_id,
                    reason,
                )
                return {"approved": approved, "reason": reason}

            meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            module_name = meta.get("module_name", "")

            # --- 1. Self-modification constraint ---
            cur.execute(
                """SELECT a.name, a.display_name, a.department
                   FROM agents a WHERE a.id = %s""",
                (agent_id,),
            )
            agent = cur.fetchone()

            if not agent:
                approved = False
                reason = f"agent id={agent_id} not found"
                _log_creed_gate(
                    "repair_fix_generation",
                    "denied",
                    agent_id,
                    reason,
                )
                return {"approved": approved, "reason": reason}

            agent_dept = (agent.get("department") or "").strip()
            dept_modules = _DEPARTMENT_MODULE_MAP.get(agent_dept, [])
            if module_name and module_name in dept_modules:
                approved = False
                reason = (
                    f"self-modification blocked — agent '{agent.get('display_name', agent['name'])}' "
                    f"(dept: {agent_dept}) cannot fix module '{module_name}'"
                )
                _log_creed_gate(
                    "repair_fix_generation",
                    "denied",
                    agent_id,
                    reason,
                )
                return {"approved": approved, "reason": reason}

            # --- 2. Welfare check ---
            cur.execute(
                """SELECT stress_level, energy_level
                   FROM agent_emotional_state
                   WHERE agent_id = %s
                   ORDER BY id DESC LIMIT 1""",
                (agent_id,),
            )
            welfare = cur.fetchone()
            if welfare:
                stress = float(welfare.get("stress_level") or 0)
                energy = float(welfare.get("energy_level") or 1)
                if stress >= 0.8 or energy <= 0.2:
                    approved = False
                    reason = (
                        f"agent welfare threshold exceeded — "
                        f"stress={stress:.2f} (max 0.8), energy={energy:.2f} (min 0.2)"
                    )
                    _log_creed_gate(
                        "repair_fix_generation",
                        "denied",
                        agent_id,
                        reason,
                    )
                    return {"approved": approved, "reason": reason}

            # --- 3. Capability check (agent exists and active) ---
            shift = (agent.get("shift_state") or "").strip()
            if shift not in ("active", "deployed"):
                approved = False
                reason = f"agent shift_state is '{shift}', expected active or deployed"
                _log_creed_gate(
                    "repair_fix_generation",
                    "denied",
                    agent_id,
                    reason,
                )
                return {"approved": approved, "reason": reason}

    except Exception as e:
        logger.error("C.R.E.E.D. Gate 1 error for proposal #%d: %s", proposal_id, e)
        approved = False
        reason = f"gate error: {e}"

    _log_creed_gate(
        "repair_fix_generation",
        "approved" if approved else "denied",
        agent_id,
        reason,
    )
    return {"approved": approved, "reason": reason}


def creed_gate_pre_apply(proposal_id):
    """C.R.E.E.D. Gate 2 — called BEFORE a generated fix is applied to the codebase.

    Checks:
        1. Scope check (diff only touches the target file)
        2. Severity-based approval tier

    Returns:
        {"approved": bool, "reason": str, "tier": int}
    """
    approved = True
    reason = "all checks passed"
    tier = 1

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT code_changes, metadata, priority
                   FROM improvement_proposals WHERE id = %s""",
                (proposal_id,),
            )
            row = cur.fetchone()

        if not row:
            _log_creed_gate_apply("denied", f"proposal #{proposal_id} not found")
            return {"approved": False, "reason": f"proposal #{proposal_id} not found", "tier": 0}

        meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        target_file = meta.get("file_path", "")
        severity_tier = meta.get("severity_tier", "yellow")
        diff_text = row.get("code_changes") or ""

        # --- 1. Scope check — diff should only reference the target file ---
        if diff_text and target_file:
            # Look for diff headers like "--- a/path" or "+++ b/path"
            import re

            file_refs = re.findall(r"^(?:---|\+\+\+)\s+[ab]/(.+)$", diff_text, re.MULTILINE)
            target_basename = os.path.basename(target_file)
            for ref in file_refs:
                ref_basename = os.path.basename(ref)
                if ref_basename != target_basename and ref != "/dev/null":
                    approved = False
                    reason = f"scope violation — diff references '{ref}' " f"but target is '{target_file}'"
                    _log_creed_gate_apply("denied", reason)
                    return {"approved": False, "reason": reason, "tier": 0}

        # --- 2. Severity-based approval tier ---
        if severity_tier == "red":
            tier = 2
            approved = False
            reason = "red severity requires human approval"
            _log_creed_gate_apply("denied", reason)
            return {"approved": False, "reason": reason, "tier": 2}

        # Yellow: auto-approve if diff is short enough (< 50 lines)
        diff_line_count = len(diff_text.strip().splitlines()) if diff_text else 0
        if diff_line_count >= 50:
            tier = 2
            approved = False
            reason = f"diff too large ({diff_line_count} lines >= 50) — requires human review"
            _log_creed_gate_apply("denied", reason)
            return {"approved": False, "reason": reason, "tier": 2}

    except Exception as e:
        logger.error("C.R.E.E.D. Gate 2 error for proposal #%d: %s", proposal_id, e)
        _log_creed_gate_apply("denied", f"gate error: {e}")
        return {"approved": False, "reason": f"gate error: {e}", "tier": 0}

    _log_creed_gate_apply("approved", reason)
    return {"approved": approved, "reason": reason, "tier": tier}


def _log_creed_gate(event_type, outcome, agent_id, reason):
    """Log a C.R.E.E.D. gate decision to governance_audit_log."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                   (event_type, event_category, action, outcome, agent_id, reason, timestamp)
                   VALUES (%s, 'creed_gate', 'pre_fix_check', %s, %s, %s, NOW())""",
                (event_type, outcome, agent_id, (reason or "")[:500]),
            )
    except Exception as e:
        logger.warning("Failed to log C.R.E.E.D. gate event: %s", e)


def _log_creed_gate_apply(outcome, reason):
    """Log a C.R.E.E.D. Gate 2 (pre-apply) decision to governance_audit_log."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                   (event_type, event_category, action, outcome, agent_id, reason, timestamp)
                   VALUES ('repair_fix_apply', 'creed_gate', 'pre_apply_check', %s, NULL, %s, NOW())""",
                (outcome, (reason or "")[:500]),
            )
    except Exception as e:
        logger.warning("Failed to log C.R.E.E.D. Gate 2 event: %s", e)


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
            # Build file path — handle platform modules, standalone, and website products
            issue_file = issue.get("file", module_name)
            if module_name.startswith("standalone_") or module_name.startswith("website_"):
                file_path = f"{module_name}/{issue_file}"
            elif module_name.startswith("["):
                file_path = f"{module_name}/{issue_file}"
            else:
                file_path = f"platform_v2/tools/{module_name}/{issue_file}"
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

    title = f"[{config['priority'].upper()}] {issue_code}: {module_name}/{fname}"
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
    from services.work_tracking_service import (
        create_work_session,
        complete_work_session,
        fail_work_session,
    )

    session_id = None

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

    if proposal["status"] not in ("pending", "approved", "fix_requested"):
        return {
            "success": False,
            "error": f"Proposal #{proposal_id} status is '{proposal['status']}', expected pending/approved/fix_requested",
        }

    meta = proposal["metadata"] if isinstance(proposal["metadata"], dict) else json.loads(proposal["metadata"] or "{}")
    if meta.get("source") != "code_health_audit":
        return {"success": False, "error": f"Proposal #{proposal_id} is not from code_health_audit"}

    file_path = meta.get("file_path", "")
    issue_code = meta.get("issue_code", "")
    module_name = meta.get("module_name", "")

    # Create work session for tracking
    try:
        session_id = create_work_session(
            agent_id=None,
            department="Engineering & Technology",
            session_type="fix",
            title=f"Fix {issue_code} in {file_path}",
            metadata={"proposal_id": proposal_id, "issue_code": issue_code, "module": module_name},
        )
    except Exception as ws_err:
        logger.warning("Work session creation failed (non-blocking): %s", ws_err)

    # Read source file
    # Resolve path: file_path is "platform_v2/tools/..." but inside Docker root is /app/ (= platform_v2/)
    # Try /mnt/archie_brain first (host), fall back to /app/ (Docker) with prefix stripped
    abs_path = os.path.join("/mnt/archie_brain", file_path)
    if not os.path.isfile(abs_path) and file_path.startswith("platform_v2/"):
        abs_path = os.path.join("/app", file_path[len("platform_v2/") :])
    if not os.path.isfile(abs_path):
        if session_id:
            fail_work_session(session_id, error_msg=f"Source file not found: {file_path}")
        return {"success": False, "error": f"Source file not found: {file_path}"}

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            source_content = f.read()
    except Exception as e:
        if session_id:
            fail_work_session(session_id, error_msg=f"Failed to read {file_path}: {e}")
        return {"success": False, "error": f"Failed to read {file_path}: {e}"}

    # Determine capability and build prompt
    capability = _ISSUE_CAPABILITY_MAP.get(issue_code, "code_review")
    fix_instruction = _FIX_PROMPTS.get(issue_code, f"Fix the {issue_code} issue in this file.")

    # Truncate source to avoid overwhelming the model
    # For targeted fixes (SQL injection, bare except), extract relevant lines
    # For analysis (large file), send first 150 lines
    source_lines = source_content.split("\n")
    detail_str = meta.get("detail", "")
    if issue_code in ("SQL_INJECTION_RISK", "BARE_EXCEPT", "HARDCODED_SECRET") and "line" in detail_str:
        try:
            line_num = int("".join(c for c in detail_str.split("line")[-1].strip() if c.isdigit())[:5])
            start_line = max(0, line_num - 20)
            end_line = min(len(source_lines), line_num + 30)
            excerpt = "\n".join(
                f"{i+1}: {l}" for i, l in enumerate(source_lines[start_line:end_line], start=start_line)
            )
            source_excerpt = f"(showing lines {start_line+1}-{end_line} of {len(source_lines)})\n{excerpt}"
        except (ValueError, IndexError):
            source_excerpt = "\n".join(source_lines[:200])
    elif issue_code == "LARGE_FILE":
        source_excerpt = f"(file has {len(source_lines)} lines, showing first 100)\n" + "\n".join(source_lines[:100])
    else:
        source_excerpt = "\n".join(source_lines[:200])

    prompt = (
        f"You are fixing a Code Health audit finding in the A.R.C.H.I.E. platform.\n\n"
        f"**Issue:** {issue_code}\n"
        f"**File:** {file_path}\n"
        f"**Module:** {module_name}\n"
        f"**Detail:** {meta.get('detail', '')}\n\n"
        f"**Instructions:** {fix_instruction}\n\n"
        f"Return a brief, targeted fix or plan. No full file rewrites.\n\n"
        f"--- SOURCE EXCERPT ---\n{source_excerpt}"
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
        if session_id:
            fail_work_session(session_id, error_msg=f"Bridge dispatch failed: {e}")
        return {"success": False, "error": f"Bridge dispatch failed: {e}"}

    if not result or not getattr(result, "response", None):
        logger.warning("Bridge returned empty response for proposal #%d", proposal_id)
        if session_id:
            fail_work_session(session_id, error_msg="Bridge returned empty response")
        return {"success": False, "error": "Bridge returned empty response"}

    fixed_content = result.response.strip()
    agent_name = getattr(result, "agent_name", "unknown")

    # C.R.E.E.D. Gate 1: Can this agent fix this code?
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM agents WHERE name = %s OR display_name = %s LIMIT 1",
                (agent_name, agent_name),
            )
            agent_row = cur.fetchone()

        if agent_row:
            gate1 = creed_gate_pre_fix(proposal_id, agent_row["id"])
            if not gate1["approved"]:
                logger.warning(
                    "C.R.E.E.D. Gate 1 denied proposal #%d agent %s: %s",
                    proposal_id,
                    agent_name,
                    gate1["reason"],
                )
                if session_id:
                    fail_work_session(session_id, error_msg=f"C.R.E.E.D. Gate 1 denied: {gate1['reason']}")
                return {
                    "success": False,
                    "error": f"C.R.E.E.D. Gate 1 denied: {gate1['reason']}",
                }
        else:
            logger.info(
                "C.R.E.E.D. Gate 1 skipped — agent '%s' not found in agents table",
                agent_name,
            )
    except Exception as gate_err:
        logger.warning("C.R.E.E.D. Gate 1 check failed (non-blocking): %s", gate_err)

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

    if session_id:
        complete_work_session(session_id, jobs_completed=1)

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
               WHERE status IN ('pending', 'approved', 'fix_requested')
                 AND metadata->>'source' = 'code_health_audit'
                 AND (metadata->>'dispatch_attempted') IS NULL
               ORDER BY
                 CASE WHEN priority = 'critical' THEN 0 ELSE 1 END,
                 proposed_at ASC
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


def verify_fix_deployment(module_name, proposal_id, pre_issue_count):
    """Re-audit a module after a fix is deployed to verify it improved.

    Compares before/after issue counts. Logs result to governance_audit_log.

    Args:
        module_name: Module that was fixed
        proposal_id: The proposal that was deployed
        pre_issue_count: Issue count before the fix

    Returns:
        {"verified": bool, "pre_count": int, "post_count": int, "delta": int}
    """
    # Fresh audit of the module
    try:
        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from services.code_metrics_service import audit_single_module

        _issues_found, _notes, _status, issues_list, *_ = audit_single_module(module_name)
    except Exception as e:
        logger.error("verify_fix_deployment: re-audit of %s failed: %s", module_name, e)
        return {"verified": False, "pre_count": pre_issue_count, "post_count": -1, "delta": 0}

    post_count = len(issues_list)
    delta = pre_issue_count - post_count
    verified = post_count < pre_issue_count

    # Log to governance_audit_log
    if verified:
        event_type = "repair_fix_verified"
        outcome = "success"
        reason = (
            f"Module '{module_name}' improved: {pre_issue_count} → {post_count} issues "
            f"(delta={delta}) after proposal #{proposal_id}"
        )
    else:
        event_type = "repair_fix_regression"
        outcome = "regression"
        reason = (
            f"Module '{module_name}' did NOT improve: {pre_issue_count} → {post_count} issues "
            f"(delta={delta}) after proposal #{proposal_id}"
        )

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                   (event_type, event_category, action, outcome, reason, timestamp)
                   VALUES (%s, 'repair_pipeline', 'verify_fix', %s, %s, NOW())""",
                (event_type, outcome, reason[:500]),
            )
    except Exception as log_err:
        logger.warning("Failed to log verify_fix_deployment event: %s", log_err)

    # Update proposal status based on verification result
    new_status = "deployed" if verified else "regression"
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE improvement_proposals SET status = %s WHERE id = %s",
                (new_status, proposal_id),
            )
    except Exception as update_err:
        logger.warning(
            "Failed to update proposal #%d status to '%s': %s",
            proposal_id,
            new_status,
            update_err,
        )

    logger.info(
        "verify_fix_deployment: module=%s proposal=#%d verified=%s (%d → %d, delta=%d)",
        module_name,
        proposal_id,
        verified,
        pre_issue_count,
        post_count,
        delta,
    )

    return {"verified": verified, "pre_count": pre_issue_count, "post_count": post_count, "delta": delta}


def _mark_dispatch_attempted(proposal_id, error_msg):
    """Mark a proposal as dispatch-attempted to prevent retry loops."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE improvement_proposals
               SET metadata = metadata || %s::jsonb
               WHERE id = %s""",
            (json.dumps({"dispatch_attempted": True, "dispatch_error": error_msg[:200]}), proposal_id),
        )
