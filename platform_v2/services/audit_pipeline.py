"""Audit pipeline — auto-creates Repair Bay proposals from Code Health audit findings.

Called after audit_single_module() completes. Red (security) issues get individual
high-priority proposals with Tier 2 (human) approval. Yellow (quality) issues get
medium-priority proposals with Tier 1 (auto) approval. Info (style) issues are skipped.

Import:
    from services.audit_pipeline import process_audit_findings
"""

import json
import logging

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
