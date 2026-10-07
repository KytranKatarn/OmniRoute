"""Advance stored Code Health patches through the existing governed ship path."""

import hashlib
import json
import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)
ACTIVE_STAGES = {"submitting", "awaiting_review", "awaiting_approval", "sandbox_testing", "sandbox_passed", "pr_open"}


def metadata(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def update_stage(proposal_id, stage, **details):
    """Track Code Health submissions without changing other proposal workflows."""
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT metadata FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        meta = metadata(row and row.get("metadata"))
        if meta.get("source") != "code_health_audit" or not meta.get("repair_submission"):
            return
        submission = dict(meta["repair_submission"], stage=stage, **details)
        cur.execute(
            "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s::jsonb WHERE id=%s",
            (json.dumps({"repair_submission": submission}), proposal_id),
        )


def request_submission(proposal_id):
    """Queue approval/testing of the saved patch; never infer, test or regenerate here."""
    from services.audit_pipeline import creed_gate_pre_dispatch
    from services.proposal_service import request_tiered_deploy_approval
    from tools.repair_bay.services.forge_pipeline import _patched_content, _proposal_fix_fields

    gate = creed_gate_pre_dispatch(proposal_id)
    if not gate.get("approved"):
        return {"success": False, "error": gate.get("reason", "Governance denied submission")}
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT * FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Proposal not found"}
        meta = metadata(row.get("metadata"))
        if meta.get("source") != "code_health_audit":
            return {"success": False, "error": "Only Code Health patches support this action"}
        previous = meta.get("repair_submission") or {}
        if previous.get("stage") in ACTIVE_STAGES and progress(dict(row))["stage"] != "blocked":
            return {"success": True, "queued": True, "already_queued": True, "submission": previous}
        if row.get("status") != "ready_for_review":
            return {"success": False, "error": "Generate and review a patch before submitting"}
        if row.get("code_diff") and row["code_diff"] != row.get("code_changes"):
            return {"success": False, "error": "Stored patch fields disagree; regenerate and review the patch"}
        fields = _proposal_fix_fields(dict(row))
        if not fields["code_diff"].strip():
            return {"success": False, "error": "No saved patch to submit"}
        patched = _patched_content(fields["file_path"], fields["code_diff"])
        if patched is None:
            return {"success": False, "error": "Saved patch no longer applies or failed validation"}
        # The existing async gate owns approval, sandbox testing and PR creation.
        result = request_tiered_deploy_approval(proposal_id)
        if not result.get("success") or not (result.get("queue_id") or result.get("approval_id")):
            return {"success": False, "error": result.get("error", "Unable to queue patch submission")}
        submission = {
            "stage": "awaiting_approval" if result.get("approval_id") else "awaiting_review",
            "queue_id": result.get("queue_id"),
            "approval_id": result.get("approval_id"),
            "approval_queue_tier": result.get("tier"),
            "approver": result.get("approver"),
            "patch_sha256": hashlib.sha256(fields["code_diff"].encode()).hexdigest(),
            "target_sha256": hashlib.sha256(patched.encode()).hexdigest(),
        }
        cur.execute(
            "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s::jsonb WHERE id=%s",
            (json.dumps({"repair_submission": submission}), proposal_id),
        )
    return {
        "success": True,
        "queued": True,
        "submission": submission,
        "message": "Saved patch queued for approval, sandbox tests and PR creation.",
    }


def approval_response_is_positive(response):
    """An empty/ambiguous review must not approve patch shipping."""
    import re

    text = (response or "").strip().upper()
    return bool(re.match(r"^(?:VERDICT:\s*)?APPROVE(?:D)?\b", text)) and not bool(
        re.search(r"\b(?:REJECT(?:ED)?|DENIED)\b|\bNOT\s+APPROVED\b", text)
    )


def patch_snapshot_matches(proposal):
    submission = metadata(proposal.get("metadata")).get("repair_submission") or {}
    if not submission.get("patch_sha256"):
        return True
    patch = proposal.get("code_changes") or ""
    return hashlib.sha256(patch.encode()).hexdigest() == submission["patch_sha256"]


def record_code_health_merge(proposal_id, pr_number):
    """Return None for legacy workflows; Code Health merge is not deployment."""
    from services.time_utils import now_utc

    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT status,metadata FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        meta = metadata(row and row.get("metadata"))
        if meta.get("source") != "code_health_audit":
            return None
        if row["status"] != "pr_open" or meta.get("merged_pr"):
            return False
        submission = dict(meta.get("repair_submission") or {}, stage="merged_awaiting_verification")
        cur.execute(
            "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s::jsonb WHERE id=%s",
            (
                json.dumps(
                    {
                        "merged_pr": pr_number,
                        "merged_at": now_utc().isoformat(),
                        "code_applied": False,
                        "repair_submission": submission,
                    }
                ),
                proposal_id,
            ),
        )
    return True


def ensure_patch_snapshot(proposal_id, proposal):
    """Capture the same receipt when an existing approval worker starts testing."""
    meta = metadata(proposal.get("metadata"))
    if meta.get("source") != "code_health_audit" or meta.get("repair_submission"):
        return meta
    from tools.repair_bay.services.forge_pipeline import _patched_content, _proposal_fix_fields

    fields = _proposal_fix_fields(proposal)
    patch = proposal.get("code_changes") or ""
    if not patch or fields["code_diff"] != patch:
        raise ValueError("A consistent saved Code Health patch is required")
    patched = _patched_content(fields["file_path"], patch)
    if patched is None:
        raise ValueError("Saved patch no longer applies")
    submission = {
        "stage": "sandbox_testing",
        "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "target_sha256": hashlib.sha256(patched.encode()).hexdigest(),
    }
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT metadata,code_changes FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        if not row or row.get("code_changes") != patch:
            raise ValueError("Saved patch changed before testing")
        current = metadata(row.get("metadata"))
        if current.get("repair_submission"):
            if not patch_snapshot_matches(dict(row)):
                raise ValueError("Saved patch changed after submission")
            return current
        cur.execute(
            "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s::jsonb WHERE id=%s",
            (json.dumps({"repair_submission": submission}), proposal_id),
        )
    return dict(meta, repair_submission=submission)


# Preserve the existing service entry points.
from services.repair_progress import progress  # noqa: E402,F401
from services.repair_verification import verify_completion  # noqa: E402,F401
