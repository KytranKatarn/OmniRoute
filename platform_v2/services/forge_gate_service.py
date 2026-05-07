"""
F.O.R.G.E. Gate Service — PR compliance check before Repair Bay deploys.
Soft gate: never blocks if GitHub is unreachable or commit unknown.
Logs compliance for audit; GitHub API wire-up is a future enhancement.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from database import get_db_cursor

logger = logging.getLogger(__name__)

_DEFAULTS: dict[str, dict[str, str]] = {
    "critical": {"gate_type": "soft"},
    "high": {"gate_type": "soft"},
    "medium": {"gate_type": "soft"},
    "low": {"gate_type": "soft"},
}


def _load_gate_config() -> dict[str, dict[str, str]]:
    """Load F.O.R.G.E. gate config from system_config. Defaults to soft gates."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'forge_gate_config'")
            row = cur.fetchone()
            if row and row["value"]:
                return json.loads(row["value"])
    except Exception as e:
        logger.warning("Could not load forge gate config: %s", e)
    return _DEFAULTS


def request_pr_clearance(
    git_commit: str | None,
    severity: str,
    proposal_id: int | None = None,
) -> dict[str, Any]:
    """
    F.O.R.G.E. pre-deploy PR clearance check.
    Currently a soft gate — logs compliance, never blocks deploys.
    Future: wire to GitHub API to verify merged PR for commit.

    Returns:
        {approved: bool, gate_level: str, reason: str, severity: str, pr_number: int|None}
    """
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"

    if not git_commit:
        return {
            "approved": True,
            "gate_level": "soft",
            "reason": "no_commit — git context unavailable, fail-open",
            "severity": severity,
            "pr_number": None,
        }

    config = _load_gate_config()
    gate_type = config.get(severity, {}).get("gate_type", "soft")

    # TODO: Wire GitHub API check here when GITHUB_TOKEN env var is available
    # For now: soft gate — log and approve. Compliance tracked in backup_log.pr_number.
    logger.info(
        "F.O.R.G.E. gate (soft): commit=%s severity=%s proposal=%s",
        git_commit,
        severity,
        proposal_id,
    )
    return {
        "approved": True,
        "gate_level": gate_type,
        "reason": f"soft gate: PR check logged for commit {git_commit[:8] if git_commit else 'unknown'}",
        "severity": severity,
        "pr_number": None,
    }
