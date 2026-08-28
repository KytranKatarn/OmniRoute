"""
Backup Governance Service — owned by W.A.R.D.E.N.
Pre-deploy clearance checks + auto-snapshots before Repair Bay deploys.
"""

from __future__ import annotations
import json
import logging
from typing import Any
from database import get_db_cursor
from services.backup_service import get_health_summary, snapshot_module

logger = logging.getLogger(__name__)


def _load_gate_config() -> dict:
    defaults = {
        "critical": {"max_age_hours": 48, "gate_type": "soft", "override": "none"},
        "high": {"max_age_hours": 12, "gate_type": "soft", "override": "telegram_approval"},
        "medium": {"max_age_hours": 6, "gate_type": "hard", "override": "kytran_approval"},
        "low": {"max_age_hours": 24, "gate_type": "hard", "override": "kytran_approval"},
    }
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'backup_governance_gates'")
            row = cur.fetchone()
            if row and row["value"]:
                return json.loads(row["value"])
    except Exception as e:
        logger.warning("Could not load governance gate config: %s — using defaults", e)
    return defaults


def gate_age_hours(primary: dict) -> float | None:
    """Age (hours) of the last SUCCESSFUL primary backup — what a deploy gate must use.

    Pure: takes a `tier_health['primary']` dict, touches nothing. Returns None when no
    successful backup is known, which callers must treat as fail-CLOSED.

    WHY NOT `age_hours` (#5013): that is the newest row whatever its status, and
    `backup_log.status` carries 'failed' / 'partial' / 'skipped' / 'prune' as well as
    'success' — 171 tier-carrying rows were 'failed' as of 2026-07-20. Gating on it
    certifies a restore point that may not exist. That day the newest primary row WAS a
    failed 2.8 GB run; only a 6-minute gap to the preceding success made the gate
    accidentally right. A 'partial' backup is the worst case — plausible and unusable.

    The `age_hours` fallback fires ONLY when the key is absent (a payload predating this
    field). An explicit None means "no successful backup" and must NOT fall back, or the
    bug returns exactly when it matters most.
    """
    if "last_success_age_hours" in primary:
        return primary.get("last_success_age_hours")
    return primary.get("age_hours")


def _check_backup_freshness(age_hours: float, severity: str) -> dict[str, Any]:
    config = _load_gate_config()
    gate = config.get(severity, config["medium"])
    max_age, gate_type = gate["max_age_hours"], gate["gate_type"]
    if age_hours <= max_age:
        return {
            "approved": True,
            "reason": f"backup is {age_hours:.1f}h old (limit {max_age}h)",
            "gate_level": gate_type,
        }
    reason = f"backup age {age_hours:.1f}h exceeds {severity} limit of {max_age}h"
    if gate_type == "soft":
        logger.warning("W.A.R.D.E.N. soft gate: %s", reason)
        return {"approved": True, "reason": f"soft gate warning — {reason}", "gate_level": "soft"}
    return {"approved": False, "reason": reason, "gate_level": "hard"}


def request_deploy_clearance(
    module: str,
    severity: str,
    triggered_by: str = "probe",
    proposal_id: int | None = None,
    deploy_scope: str = "full",
) -> dict[str, Any]:
    """W.A.R.D.E.N. pre-deploy clearance. Returns approved + snapshot_id + reason.

    deploy_scope: 'full' (default — today's behavior) or 'scoped', meaning the deploy
    will take a FRESH module backup of the touched module seconds before applying.
    """
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"
    health = get_health_summary()
    age_hours = gate_age_hours(health["tier_health"].get("primary") or {})
    freshness = _check_backup_freshness(age_hours=age_hours if age_hours is not None else 9999.0, severity=severity)

    # #5279 / ADR-009: a SCOPED deploy takes a fresh module backup seconds before the
    # change — THAT is the restore point for what is being modified, so a stale FULL
    # snapshot becomes advisory instead of blocking. This ended the self-starvation
    # loop where keeping the full snapshot fresh cost 16 minutes a time and the drain
    # could never pass its own gate (approvals 5472-5474). The age LIMITS are untouched;
    # full-scope deploys keep the hard gate; and age_hours=None (NO successful full
    # backup at all) still denies even scoped — a module file-copy can roll back the
    # change but is not a platform restore point.
    if deploy_scope == "scoped" and not freshness["approved"] and age_hours is not None:
        logger.warning("W.A.R.D.E.N. scoped-deploy advisory (was a hard denial): %s", freshness["reason"])
        freshness = {
            "approved": True,
            "reason": (
                "scoped deploy — fresh module backup is the restore point for this change; "
                f"{freshness['reason']} (advisory; full-backup freshness is posture-monitored)"
            ),
            "gate_level": "soft",
        }

    snapshot_id = None
    try:
        snap = snapshot_module(
            module_name=module,
            snapshot_type="pre_deploy",
            trigger_source=triggered_by,
            metadata={"proposal_id": proposal_id, "severity": severity},
        )
        if snap["success"]:
            snapshot_id = snap["snapshot_id"]
    except Exception as e:
        logger.error("W.A.R.D.E.N. snapshot failed for %s: %s", module, e)
        if severity in ("medium", "low"):
            freshness = {"approved": False, "reason": f"snapshot failed: {e}", "gate_level": "hard"}

    if not freshness["approved"]:
        _notify_denial(module, severity, freshness["reason"])

    result = {
        "approved": freshness["approved"],
        "snapshot_id": snapshot_id,
        "gate_level": freshness["gate_level"],
        "reason": freshness["reason"],
        "backup_age_hours": age_hours,
        "severity": severity,
    }
    logger.info(
        "W.A.R.D.E.N. clearance %s — module=%s severity=%s",
        "GRANTED" if result["approved"] else "DENIED",
        module,
        severity,
    )
    return result


def _notify_denial(module: str, severity: str, reason: str) -> None:
    try:
        from services.telegram_service import send_info

        send_info(
            f"W.A.R.D.E.N. — Deploy clearance DENIED\nModule: {module} | Severity: {severity}\nReason: {reason}\nAction: Approve override or resolve backup issue first.",
            source_agent="W.A.R.D.E.N.",
        )
    except Exception as e:
        logger.warning("W.A.R.D.E.N. denial notification suppressed: %s", e)
