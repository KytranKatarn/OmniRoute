"""Scan pipeline — auto-creates improvement proposals from Code Sentinel findings.

Called after scan_file() completes. Critical/high issues get individual proposals.
Medium issues are tagged for weekly batch collection.

Import:
    from services.scan_pipeline import process_scan_results, batch_medium_issues
"""

import json
import logging

from database import get_db_cursor

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
    with get_db_cursor(commit=False) as (conn, cur):
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

    metadata = json.dumps(
        {
            "source": "code_sentinel",
            "scan_id": scan_id,
            "file_path": file_path,
            "issue_type": issue_type,
            "severity": severity,
            "line_number": line_number,
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
        logger.info(f"Created proposal #{proposal_id} for {severity} {issue_type} in {file_path}")

    # Route through autonomy approval queue
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from agent_loop import request_approval

        # Low/medium risk → Tier 1 (auto-approve)
        # High/critical risk → Tier 2 (human via Telegram)
        is_low_risk = risk_level in ("low", "medium") and priority in (
            "low",
            "medium",
        )
        approval_tier = 1 if is_low_risk else 2
        approval_priority = 3 if priority == "critical" else 5 if priority == "high" else 7

        request_approval(
            action_type="improvement_approve",
            action_data={
                "proposal_id": proposal_id,
                "title": title,
                "file_path": file_path,
                "severity": severity,
                "risk_level": risk_level,
            },
            reason=f"Auto-generated from Code Sentinel scan: {message[:100]}",
            requested_by="scan_pipeline",
            priority=approval_priority,
            tier=approval_tier,
        )
    except Exception as approval_err:
        logger.warning(f"Approval queue submission failed for proposal #{proposal_id}: {approval_err}")

    return proposal_id


def _link_issue_to_proposal(scan_id, issue, proposal_id):
    """Set code_issues.proposal_id for the matching issue."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE code_issues
            SET proposal_id = %s
            WHERE scan_id = %s
              AND COALESCE(line_number, 0) = %s
              AND issue_type = %s
              AND proposal_id IS NULL
            """,
            (
                proposal_id,
                scan_id,
                issue.get("line", 0),
                issue.get("type", "quality"),
            ),
        )


def _tag_issues_for_batch(scan_id, medium_issues):
    """Tag medium-severity issues for weekly batch processing.

    Uses the code_issues.status field — sets to 'batch_eligible' for unlinked medium issues.
    Returns count of tagged issues.
    """
    with get_db_cursor(commit=True) as (conn, cur):
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
        return cur.rowcount


def batch_medium_issues():
    """Weekly job: collect batch_eligible medium issues and create cleanup proposals.

    Groups issues by file_path, creates one proposal per file.
    Called by the consciousness scheduler (Sunday 02:00).
    """
    with get_db_cursor(commit=False) as (conn, cur):
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

            issue_list = "\n".join(f"- {m}" for m in messages[:10])
            if issue_count > 10:
                issue_list += f"\n- ... and {issue_count - 10} more"

            title = f"Code Cleanup: {file_path} ({issue_count} issues)"
            description = (
                f"Weekly batch: {issue_count} medium-severity issues in `{file_path}`.\n\n" f"**Issues:**\n{issue_list}"
            )

            metadata = json.dumps(
                {
                    "source": "code_sentinel",
                    "batch": True,
                    "file_path": file_path,
                    "issue_type": "cleanup",
                    "issue_count": issue_count,
                    "auto_generated": True,
                }
            )

            with get_db_cursor(commit=True) as (conn, cur):
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

                cur.execute(
                    """
                    UPDATE code_issues
                    SET proposal_id = %s, status = 'open'
                    WHERE id = ANY(%s)
                    """,
                    (proposal_id, issue_ids),
                )
                proposals_created += 1
                logger.info(f"Batch proposal #{proposal_id}: {issue_count} issues in {file_path}")

        except Exception as e:
            logger.warning(f"Failed to batch issues for {group['file_path']}: {e}")

    logger.info(f"Batch medium issues complete: {proposals_created} proposals created")
    return {"proposals_created": proposals_created}
