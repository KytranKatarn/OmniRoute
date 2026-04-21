"""S.P.E.C.T.R.A. → Audit Pipeline adapter (Project #272 / Task #2186).

Converts the dispatch-routing audit findings produced by
``services.misroute_audit_service.run_misroute_audit`` into audit proposals
via ``services.audit_pipeline.process_audit_findings``.

Closes the observation→proactive-fix loop (Task #2112) by plumbing the only
missing input signal: dispatch misroutes. Everything downstream
(proposal creation, C.R.E.E.D. ethics gate, F.O.R.G.E. fix generation,
approval queue, post-deploy verification) is existing infrastructure.

Output contract matches the Task #2185 research brief:
    * severity map:   red    → paid-cloud bypass-class, ≥50% agent failures,
                              missing-capability bypass (routing violation)
                      yellow → floor fallback, 20–50% agent failures,
                              modest cloud escalation
    * dedup:          ``(metadata.file_path, metadata.issue_code)`` handled
                      by ``audit_pipeline._has_open_audit_proposal``
    * module prefix:  ``[dispatch_routing]`` — triggers the bracket branch in
                      ``process_audit_findings`` so file_path is stored as
                      ``[dispatch_routing]/<file>`` (no platform_v2/tools/ prefix)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MODULE_NAME = "[dispatch_routing]"

# Cap the worst N findings per class per run. Prevents a single bad day
# (e.g. ARCHIE/translate 3,268 failures) from flooding improvement_proposals.
MAX_PER_CLASS = 5

# Cloud escalation cost threshold — ignore cheap hits. Paid cloud is expected
# occasionally; only file a proposal if the spend is material.
CLOUD_COST_ESCALATE_USD = 1.0

# Agent-failure severity split.
RED_FAILURE_PCT = 50.0


def run(window_hours: int = 24) -> Dict[str, Any]:
    """Execute the adapter: audit → convert → process.

    Returns a summary dict suitable for the agent-loop job to log.
    """
    from services.audit_pipeline import process_audit_findings
    from services.misroute_audit_service import run_misroute_audit

    audit = run_misroute_audit(window_hours=window_hours)
    issues = _convert_findings(audit["findings"])

    summary: Dict[str, Any] = {
        "input_anomalies": audit["anomaly_count"],
        "audit_severity": audit["severity"],
        "issues_generated": len(issues),
        "proposals_created": 0,
        "skipped_duplicates": 0,
        "info_skipped": 0,
        "window_hours": window_hours,
        "issues_by_code": _count_by_code(issues),
    }

    if not issues:
        logger.info(
            "misroute_to_proposal_adapter: no findings (anomalies=%d severity=%s)",
            audit["anomaly_count"],
            audit["severity"],
        )
        return summary

    result = process_audit_findings(MODULE_NAME, issues)
    summary["proposals_created"] = result.get("proposals_created", 0)
    summary["skipped_duplicates"] = result.get("skipped_duplicates", 0)
    summary["info_skipped"] = result.get("info_skipped", 0)

    logger.info(
        "misroute_to_proposal_adapter: anomalies=%d issues=%d proposals=%d dup=%d",
        audit["anomaly_count"],
        len(issues),
        summary["proposals_created"],
        summary["skipped_duplicates"],
    )
    return summary


def _convert_findings(findings: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    issues.extend(_from_floor_fallback(findings.get("floor_fallback", [])))
    issues.extend(_from_cloud_escalation(findings.get("cloud_escalation", [])))
    issues.extend(_from_missing_capability(findings.get("missing_capability", [])))
    issues.extend(_from_high_failure(findings.get("high_failure_agents", [])))
    return issues


def _from_floor_fallback(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "code": "DISPATCH_FLOOR_FALLBACK",
            "severity": "yellow",
            "file": f"smart_router.py:{row['capability']}",
            "detail": (
                f"Capability '{row['capability']}' triggered floor fallback "
                f"{row['count']}× in window (reason: {row['reason']}; "
                f"{row['distinct_agents']} distinct agents)"
            ),
        }
        for row in rows[:MAX_PER_CLASS]
    ]


def _from_cloud_escalation(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "code": "DISPATCH_CLOUD_ESCALATION",
            "severity": "yellow",
            "file": f"department_dispatcher.py:{row['capability']}",
            "detail": (
                f"Capability '{row['capability']}' hit paid cloud "
                f"{row['cloud_hits']}× costing ${row['total_cost_usd']:.2f} "
                f"across {row['distinct_models']} model(s)"
            ),
        }
        for row in rows[:MAX_PER_CLASS]
        if (row.get("total_cost_usd") or 0) > CLOUD_COST_ESCALATE_USD
    ]


def _from_missing_capability(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "code": "DISPATCH_MISSING_CAPABILITY",
            "severity": "red",
            "file": row.get("module_source") or "unknown_caller",
            "detail": (
                f"Module '{row.get('module_source') or 'unknown'}' made "
                f"{row['missing_cap_calls']} dispatch call(s) without a "
                f"capability tag (bypasses capability-routing)"
            ),
        }
        for row in rows[:MAX_PER_CLASS]
    ]


def _from_high_failure(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for row in rows[:MAX_PER_CLASS]:
        agent = row.get("agent_name") or "unknown_agent"
        capability = row.get("capability") or "unknown"
        pct = row.get("failure_pct") or 0.0
        issues.append(
            {
                "code": "AGENT_HIGH_FAILURE_RATE",
                "severity": "red" if pct >= RED_FAILURE_PCT else "yellow",
                "file": f"agents/{agent}/{capability}",
                "detail": (
                    f"Agent {agent} on capability '{capability}' failing "
                    f"{pct}% ({row['failures']}/{row['total_calls']} calls)"
                ),
            }
        )
    return issues


def _count_by_code(issues: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for issue in issues:
        counts[issue["code"]] = counts.get(issue["code"], 0) + 1
    return counts
