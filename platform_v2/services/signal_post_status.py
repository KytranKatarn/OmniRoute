"""SIGNAL post status classifier (Phase 1).

Pure function. Maps (approval_row, post_log_row) -> one of 6 states:
  pending | executing | posted | failed | rejected | deferred

Used by signal_calendar_live_service when assembling the 7-day calendar view.
The frontend's 'no_draft' state is virtual (no DB row) and generated client-side.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _normalize_execution_result(result: Any) -> Optional[Dict[str, Any]]:
    """psycopg2 sometimes returns jsonb as a string. Normalise to dict or None."""
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return None
    return None


def classify(
    approval_row: Dict[str, Any],
    post_log: Optional[Dict[str, Any]] = None,
) -> str:
    """Classify a post into one of the 6 visible states.

    Returns one of: 'pending', 'executing', 'posted', 'failed',
                    'rejected', 'deferred'
    """
    status = approval_row.get("status")

    # Terminal / non-execution states
    if status == "rejected":
        return "rejected"
    if status == "deferred_session":
        return "deferred"
    if status == "approved":
        # Approved but execution_result not yet recorded — running now
        return "executing"
    if status == "pending":
        return "pending"

    # 'executed' status — success or failure determined by execution_result
    if status == "executed":
        # Prefer post_log if it exists (final source of truth)
        if post_log and post_log.get("status") == "posted":
            return "posted"

        result = _normalize_execution_result(approval_row.get("execution_result"))

        # Some flows nest the actual skill output under 'result'
        if result and "result" in result and isinstance(result["result"], dict):
            inner = result["result"]
            if inner.get("success") is True:
                return "posted"
            if inner.get("success") is False:
                return "failed"
            if inner.get("_status") in ("failed", "timeout"):
                return "failed"

        # Top-level success/failure
        if result:
            if result.get("success") is True:
                return "posted"
            if result.get("success") is False:
                return "failed"
            if result.get("_status") in ("failed", "timeout"):
                return "failed"
            if result.get("executed") is True and not result.get("error"):
                return "posted"

        # No clear signal — landed in executed without success
        return "failed"

    # Unknown/legacy status — default to pending so it stays visible
    return "pending"
