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

# Admission-control sheds are NOT agent failures. When the hub's 7B
# in-flight cap is reached the dispatcher refuses the dispatch and writes
# a success=false row (it raises {"backpressure": True}); the work was
# never handed to the agent. Counting those as failures reports a healthy
# agent caught in a saturation burst as broken — and, worse, lets shed
# volume dilute a genuine failure rate below the alert threshold.
# ``agent_jobs._check_cluster_saturation`` matches the same patterns and
# raises the cluster_saturation advisory that is the correct home for
# this signal.
#
# The list now lives in services.infra_failure_filter — the single source of
# truth. It used to be duplicated here, and "keep the lists in step" was left to
# discipline; the third consumer (kin_failure_standby) was never brought in step
# and benched healthy agents as a result (#5165). Import, do not re-type.
from services.infra_failure_filter import (  # noqa: E402
    BACKPRESSURE_ERROR_PATTERNS as _BACKPRESSURE_ERROR_PATTERNS,
)


def _get_db_password() -> str:
    """Read DB password from Docker secret file, fall back to env var.

    Mirrors ``services.dispatch_service.DispatchService._get_db_password`` so
    the audit works in every runtime context — MCP server (env-driven),
    agent_loop scheduler (secret-file via compose), and ad-hoc
    ``docker exec`` (secret-file bind-mounted).
    """
    secret_file = os.environ.get("DB_PASSWORD_FILE", "/run/secrets/db_password")
    try:
        with open(secret_file) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError):
        return os.environ.get("DB_PASSWORD", "")


def _get_conn():
    """Return a plain psycopg2 connection.

    Matches the pattern used in ``mcp_server/tools/ai_command_tools.py``
    — env-driven, no dependency on Flask app context so the same code
    path works under the MCP server and inside agent_loop. Resolves the
    DB password via ``_get_db_password`` so Docker secret setups work.
    """
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ---------------------------------------------------------------------------
# Individual queries — each returns a list of plain dicts. Kept small and
# composable so Phase 2's dashboard can call them directly.
# ---------------------------------------------------------------------------


def _floor_fallback(cur, window_hours: int) -> List[Dict[str, Any]]:
    """Same-floor department substitutions ONLY (migration 485).

    ⚠️ This selected EVERY row of dispatch_escalation_log until 2026-09-22 and reported the
    total as "floor_fallback_hits". The table's only writer was the cloud/throughput path, so
    the metric reported the CLOUD number under a floor-fallback name — measured over 24h:
    1,291 throughput escalations, ZERO floor fallbacks, alarm firing at 1,345 against a
    threshold of 20, every run. Genuine floor fallbacks were unmonitored while APPEARING
    monitored. Keep the escalation_type filter.
    """
    cur.execute(
        """
        SELECT capability,
               reason,
               count(*)::int AS count,
               count(DISTINCT original_agent_id)::int AS distinct_agents
        FROM dispatch_escalation_log
        WHERE created_at > now() - (%s || ' hours')::interval
          AND escalation_type = 'floor_fallback'
        GROUP BY capability, reason
        ORDER BY count DESC
        LIMIT 50
        """,
        (str(window_hours),),
    )
    return [dict(row) for row in cur.fetchall()]


def _throughput_escalation(cur, window_hours: int) -> List[Dict[str, Any]]:
    """Cloud/throughput escalations — the volume the floor-fallback metric used to report.

    Split out so renaming the metric does not SILENCE it: this is a real number (1,291 in the
    24h before the split) and it stays visible in summary_metrics and the alert body.

    ⚠️ Deliberately carries NO alarm threshold. One day of observation is not a basis for one,
    and a fabricated threshold is exactly how the original floor-fallback alarm became noise.
    Set one when there is evidence for a number.
    """
    cur.execute(
        """
        SELECT capability,
               reason,
               count(*)::int AS count,
               count(DISTINCT original_agent_id)::int AS distinct_agents
        FROM dispatch_escalation_log
        WHERE created_at > now() - (%s || ' hours')::interval
          AND escalation_type = 'throughput'
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
    # JOIN agents to get the authoritative name — task_execution_log.agent_name
    # can be stale (e.g. hardcoded to the dispatching router rather than the
    # executing agent). COALESCE falls back to the stored column for display, but
    # a row is only ADMITTED when agent_id is present -- see the WHERE note below.
    cur.execute(
        """
        SELECT COALESCE(a.name, tel.agent_name) AS agent_name,
               tel.agent_id,
               tel.capability,
               count(*)::int AS total_calls,
               sum(CASE WHEN NOT tel.success THEN 1 ELSE 0 END)::int AS failures,
               round(
                   100.0 * sum(CASE WHEN NOT tel.success THEN 1 ELSE 0 END)::numeric
                   / nullif(count(*), 0)::numeric,
                   1
               )::float AS failure_pct
        FROM task_execution_log tel
        LEFT JOIN agents a ON a.id = tel.agent_id
        WHERE tel.created_at > now() - (%s || ' hours')::interval
          -- #5809: agent_id IS NULL is not a legacy artifact -- the dispatcher
          -- assigns it DELIBERATELY for infrastructure work. department_dispatcher
          -- `is_warmup = module_id in ("fleet_warmup","kin_warmth")` sets
          -- log_agent_id = None while KEEPING agent_name purely as "an informational
          -- marker of which model was warmed". Admitting those rows scored keep-alive
          -- warm-ups as agent/capability failures: E.M.B.E.R. was reported misrouted
          -- to `documentation` having never been selected for it (select_agent
          -- correctly excludes it -- it holds no documentation skill).
          -- Measured 2026-08-22, 24h: 20 pairs over the failure threshold, 0 of
          -- which survive this filter. The ENTIRE alarm population was infrastructure.
          -- This audit groups BY agent; a row with no agent has no place in it.
          -- NOTE: those failures are real (they are #5925) and remain visible via
          -- dispatch-health, which measures infra. This narrows attribution, it does
          -- not hide the work -- do not let it become "unmonitored yet monitored".
          AND tel.agent_id IS NOT NULL
          -- Admission-control sheds never reached the agent, so they are
          -- neither a failure nor a call: drop them from the numerator AND
          -- the denominator. Leaving them in the denominator would let a
          -- saturation burst dilute a real failure rate under the threshold.
          AND NOT (NOT tel.success AND tel.error_message ILIKE ANY(%s))
        GROUP BY COALESCE(a.name, tel.agent_name), tel.agent_id, tel.capability
        HAVING count(*) >= %s
           AND sum(CASE WHEN NOT tel.success THEN 1 ELSE 0 END)::float / count(*)::float > %s
        ORDER BY failure_pct DESC, total_calls DESC
        LIMIT 50
        """,
        (
            str(window_hours),
            list(_BACKPRESSURE_ERROR_PATTERNS),
            MIN_CALLS_FOR_FAILURE_CHECK,
            FAILURE_RATE_THRESHOLD,
        ),
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
    # .get(): callers built before migration 485 pass a findings dict without this key.
    throughput_hits = sum(row.get("count", 0) or 0 for row in findings.get("throughput_escalation", []))
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
        # throughput escalations are COUNTED (they are real events) but never alarm on their
        # own — see _throughput_escalation on why no threshold is invented here.
        "anomaly_count": high_fail + missing_cap + cloud_hits + floor_hits + throughput_hits,
        "summary_metrics": {
            "floor_fallback_hits": floor_hits,
            "throughput_escalation_hits": throughput_hits,
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
                "throughput_escalation": _throughput_escalation(cur, window_hours),
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
        f"• throughput escalation: {metrics.get('throughput_escalation_hits', 0)}",
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
