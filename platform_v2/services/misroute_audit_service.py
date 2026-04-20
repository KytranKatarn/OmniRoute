"""S.P.E.C.T.R.A. — Dispatch Misroute Audit Service.

Single source of truth for the nightly dispatch-routing audit introduced
in Project #272 Phase 1 / Task #2105. Scans the last N hours of dispatch
records in ``task_execution_log`` and ``dispatch_escalation_log`` for
four classes of anomaly and returns a structured findings payload.

Callers
-------
1. MCP tool ``mcp__archie__run_misroute_audit`` — invocable on demand.
2. Agent-loop job ``spectra_misroute_audit`` — scheduled nightly.
3. Future Dev HQ capability-routing dashboard (Phase 2 / #2110) — reads
   the most recent ``autonomy_loop_log`` row written by the agent-loop
   job.

Misroute classes
----------------
1. **Floor fallback** — dispatcher escalated beyond the home department
   (``dispatch_escalation_log`` rows grouped by capability + reason).
2. **Cloud escalation rate** — capabilities hitting paid-cloud tiers
   frequently in the window, with cost footprint.
3. **Missing capability tag** — ``task_execution_log`` rows where the
   caller passed an empty / ``unknown`` capability. Every such call is a
   bypass of the capability-routing system.
4. **High failure rate** — any (agent, capability) pair with ≥10 calls
   and >20% failure over the window.

Severity rollup (read by the agent-loop job to decide whether to raise
a ``system_notifications`` row):

* ``error``   — high_failure_agents > 0, OR cloud_cost_usd > $5, OR
                more than 50 missing-capability calls
* ``warning`` — floor_fallback > 20 OR cloud_hits > 10 OR
                any missing-capability call
* ``info``    — otherwise
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Thresholds — module-level so tests / callers can tune them without
# editing SQL. Matching the decision log naming convention.
MIN_CALLS_FOR_FAILURE_CHECK = 10
FAILURE_RATE_THRESHOLD = 0.20
FLOOR_FALLBACK_WARNING = 20
CLOUD_HITS_WARNING = 10
CLOUD_COST_ERROR_USD = 5.0
MISSING_CAP_ERROR = 50

# Providers considered "paid cloud" for the escalation-rate signal.
# Local (Ollama) escalations stay on the free tier and shouldn't count.
_PAID_CLOUD_PROVIDERS = (
    "claude",
    "anthropic",
    "openai",
    "gemini",
    "google",
    "openrouter",
    "openai-compatible",
)


def _get_conn():
    """Return a plain psycopg2 connection.

    Matches the pattern used in ``mcp_server/tools/ai_command_tools.py``
    — env-driven, no dependency on Flask app context so the same code
    path works under the MCP server and inside agent_loop.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ---------------------------------------------------------------------------
# Individual queries — each returns a list of plain dicts. Kept small and
# composable so Phase 2's dashboard can call them directly.
# ---------------------------------------------------------------------------


def _floor_fallback(cur, window_hours: int) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT capability,
               reason,
               count(*)::int AS count,
               count(DISTINCT original_agent_id)::int AS distinct_agents
        FROM dispatch_escalation_log
        WHERE created_at > now() - (%s || ' hours')::interval
        GROUP BY capability, reason
        ORDER BY count DESC
        LIMIT 50
        """,
        (str(window_hours),),
    )
    return [dict(row) for row in cur.fetchall()]


def _cloud_escalation(cur, window_hours: int) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT capability,
               count(*)::int AS cloud_hits,
               coalesce(sum(cost_usd), 0)::float AS total_cost_usd,
               count(DISTINCT escalated_model)::int AS distinct_models
        FROM dispatch_escalation_log
        WHERE created_at > now() - (%s || ' hours')::interval
          AND lower(escalated_provider) = ANY(%s)
        GROUP BY capability
        ORDER BY cloud_hits DESC
        LIMIT 50
        """,
        (str(window_hours), list(_PAID_CLOUD_PROVIDERS)),
    )
    return [dict(row) for row in cur.fetchall()]


def _missing_capability(cur, window_hours: int) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT module_source,
               count(*)::int AS missing_cap_calls
        FROM task_execution_log
        WHERE created_at > now() - (%s || ' hours')::interval
          AND (capability IS NULL OR capability = '' OR capability = 'unknown')
        GROUP BY module_source
        ORDER BY missing_cap_calls DESC
        LIMIT 50
        """,
        (str(window_hours),),
    )
    return [dict(row) for row in cur.fetchall()]


def _high_failure_agents(cur, window_hours: int) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT agent_name,
               capability,
               count(*)::int AS total_calls,
               sum(CASE WHEN NOT success THEN 1 ELSE 0 END)::int AS failures,
               round(
                   100.0 * sum(CASE WHEN NOT success THEN 1 ELSE 0 END)::numeric
                   / nullif(count(*), 0)::numeric,
                   1
               )::float AS failure_pct
        FROM task_execution_log
        WHERE created_at > now() - (%s || ' hours')::interval
          AND agent_name IS NOT NULL
        GROUP BY agent_name, capability
        HAVING count(*) >= %s
           AND sum(CASE WHEN NOT success THEN 1 ELSE 0 END)::float / count(*)::float > %s
        ORDER BY failure_pct DESC, total_calls DESC
        LIMIT 50
        """,
        (str(window_hours), MIN_CALLS_FOR_FAILURE_CHECK, FAILURE_RATE_THRESHOLD),
    )
    return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _compute_severity(findings: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Collapse the 4 finding lists into a single severity + count."""
    cloud_cost = sum(row.get("total_cost_usd", 0) or 0 for row in findings["cloud_escalation"])
    cloud_hits = sum(row.get("cloud_hits", 0) or 0 for row in findings["cloud_escalation"])
    floor_hits = sum(row.get("count", 0) or 0 for row in findings["floor_fallback"])
    missing_cap = sum(row.get("missing_cap_calls", 0) or 0 for row in findings["missing_capability"])
    high_fail = len(findings["high_failure_agents"])

    severity = "info"
    reasons: List[str] = []

    if high_fail > 0:
        severity = "error"
        reasons.append(f"{high_fail} agent/capability pair(s) >20% failure")
    if cloud_cost > CLOUD_COST_ERROR_USD:
        severity = "error"
        reasons.append(f"cloud spend ${cloud_cost:.2f} exceeds ${CLOUD_COST_ERROR_USD}")
    if missing_cap > MISSING_CAP_ERROR:
        severity = "error"
        reasons.append(f"{missing_cap} missing-capability calls")

    if severity != "error":
        if floor_hits > FLOOR_FALLBACK_WARNING:
            severity = "warning"
            reasons.append(f"{floor_hits} floor-fallback hits")
        if cloud_hits > CLOUD_HITS_WARNING:
            severity = "warning"
            reasons.append(f"{cloud_hits} cloud escalation(s)")
        if missing_cap > 0 and severity == "info":
            severity = "warning"
            reasons.append(f"{missing_cap} missing-capability call(s)")

    return {
        "severity": severity,
        "anomaly_count": high_fail + missing_cap + cloud_hits + floor_hits,
        "summary_metrics": {
            "floor_fallback_hits": floor_hits,
            "cloud_escalation_hits": cloud_hits,
            "cloud_cost_usd": round(cloud_cost, 4),
            "missing_capability_calls": missing_cap,
            "high_failure_pairs": high_fail,
        },
        "reasons": reasons,
    }


def run_misroute_audit(window_hours: int = 24) -> Dict[str, Any]:
    """Execute the 4 audit queries and return a structured findings dict.

    Caller decides what to do with the payload (log, notify, render).
    Safe to call repeatedly — no DB writes happen in this function.
    """
    if window_hours <= 0 or window_hours > 24 * 30:
        raise ValueError("window_hours must be in (0, 720]")

    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            findings = {
                "floor_fallback": _floor_fallback(cur, window_hours),
                "cloud_escalation": _cloud_escalation(cur, window_hours),
                "missing_capability": _missing_capability(cur, window_hours),
                "high_failure_agents": _high_failure_agents(cur, window_hours),
            }
    finally:
        conn.close()

    severity = _compute_severity(findings)
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "findings": findings,
        **severity,
    }


def format_alert_message(result: Dict[str, Any]) -> str:
    """Render a compact Telegram / system-notifications message from a
    ``run_misroute_audit()`` result. Plain text, Markdown-friendly."""
    metrics = result["summary_metrics"]
    lines = [
        f"S.P.E.C.T.R.A. — dispatch misroute audit ({result['window_hours']}h)",
        f"Severity: *{result['severity'].upper()}* · {result['anomaly_count']} anomalies",
        "",
        f"• floor fallback: {metrics['floor_fallback_hits']}",
        f"• cloud escalation: {metrics['cloud_escalation_hits']} (${metrics['cloud_cost_usd']})",
        f"• missing capability: {metrics['missing_capability_calls']}",
        f"• high-failure pairs: {metrics['high_failure_pairs']}",
    ]
    if result.get("reasons"):
        lines.append("")
        lines.append("Reasons:")
        for reason in result["reasons"]:
            lines.append(f"  – {reason}")
    return "\n".join(lines)
