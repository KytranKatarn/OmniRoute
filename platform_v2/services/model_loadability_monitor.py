"""services/model_loadability_monitor.py — can a node still LOAD a model? (#6688)

THE INCIDENT THIS EXISTS FOR (2026-09-11, KB #315235)
-----------------------------------------------------
For 2+ days the hub could not cold-load ANY model outside its resident set.
``qwen2.5-coder:7b`` sat at 0 successes / 401s average, so Repair Bay's code
generation was dead in production — and NOTHING alerted, because the
high-volume models were already loaded and kept succeeding. Every dashboard,
every success-rate query and every health check read green throughout.

Root cause was ollama scheduler state accumulated over 2d16h of uptime: every
model had been placed on GPU0 (84% full, 96% util) while GPU1 held one model at
0% util with 7.1GB free, and escaping required evicting a model that continuous
traffic kept touching. A restart cleared it (coder 420s timeout -> 3.7s).

WHY THE EXISTING OBSERVER DOES NOT COVER THIS
---------------------------------------------
``services/residency_monitor.py`` answers "what is resident?" and deliberately
treats an absent model as an OBSERVATION, never a fault — correctly, because
models load on demand. Throughout the incident the hub's four residents were
present and healthy, so that observer would have reported everything fine.

The thing that broke was LOADABILITY, and nothing measured it.

WHY THIS IS PASSIVE
-------------------
An active prober would have to load a model every cycle, causing exactly the
eviction churn it is trying to detect — and on a node at capacity it would
evict something real to prove a point. The freeze is already visible in
``task_execution_log``; this reads it. No loading, no eviction, no routing
change, no LLM. Alert-only, like ``backup_posture_monitor``.

THE RULE, AND WHY IT IS SHAPED THIS WAY (each clause was validated against the
real incident window, 2026-09-10 08:00 -> 2026-09-11 08:00)
-----------------------------------------------------------------------------
A finding needs ALL of:

  1. PER NODE. Fleet-wide is vacuous: ``llama3.2:3b`` read 19 attempts / 17 ok
     (89%, healthy) fleet-wide during the incident because it was succeeding on
     the Starships while failing on the hub. Scoped to the hub the same model
     shows the fault. A fleet-wide rule sees nothing.
  2. THE MODEL HAS WORKED HERE BEFORE. Without this, a model merely absent from
     a node (never pulled, wrong tier) alarms forever — the ``node_has_model``
     fail-open trap in reverse.
  3. RECENT ATTEMPTS, ZERO SUCCESSES. Hub-only in the incident window,
     ``qwen2.5-coder:7b`` was the ONLY model at 0% (2 attempts, 0 ok) while
     everything else ran 88-100%.
  4. FAILURES LOOK LIKE TIMEOUTS, NOT FAST ERRORS. The coder's failures
     averaged 401s. A model failing in milliseconds is a different fault
     (MODEL_NOT_FOUND, a bad request) and must not be reported as a freeze.
  5. THE NODE IS OTHERWISE HEALTHY. If everything on the node is failing, the
     node is down — a different alert owned by fleet health. This one is
     specifically "this node works, but it can no longer load THIS model".

⚠️ The attempts threshold is deliberately LOW (2). A frozen model is one almost
nothing asks for — that is WHY it stays broken and unnoticed. Requiring the 3+
attempts that feel statistically comfortable would have missed this incident
entirely: the coder managed 2 attempts on the hub in 24 hours.

⚠️ Admission-gate sheds are excluded via ``infra_failure_filter`` — those rows
carry a ``model_used`` with zero inference and would measure the GATE, not the
model (.claude/rules/fleet.md). Counting them would manufacture findings during
any traffic burst.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_loop")

# --- thresholds (overridable live via platform_settings, no deploy) ----------

# How far back to look for attempts. Long enough that a low-volume model
# accumulates the 2 attempts the rule needs; short enough to alert same-day.
DEFAULT_WINDOW_HOURS = 12.0

# Minimum failed attempts before we will speak. See the low-threshold note above.
DEFAULT_MIN_ATTEMPTS = 2

# A model that succeeded here more recently than this is not stuck.
DEFAULT_STALE_SUCCESS_HOURS = 6.0

# Mean failure duration at or above this reads as "timed out waiting on a load"
# rather than "errored immediately". The observed incident averaged 401s.
DEFAULT_MIN_FAIL_SECONDS = 60.0

# If the node's OTHER models are below this, the node itself is sick — not a
# per-model loadability fault. Stay quiet and let fleet health own it.
DEFAULT_NODE_HEALTHY_PCT = 70.0

_SETTING_PREFIX = "loadability:"


def _thresholds() -> Dict[str, float]:
    """platform_settings overrides on top of the defaults. Never raises."""
    out = {
        "window_hours": DEFAULT_WINDOW_HOURS,
        "min_attempts": float(DEFAULT_MIN_ATTEMPTS),
        "stale_success_hours": DEFAULT_STALE_SUCCESS_HOURS,
        "min_fail_seconds": DEFAULT_MIN_FAIL_SECONDS,
        "node_healthy_pct": DEFAULT_NODE_HEALTHY_PCT,
    }
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute("SELECT key, value FROM platform_settings WHERE key LIKE %s", (_SETTING_PREFIX + "%",))
            for row in cur.fetchall() or []:
                name = str(row["key"]).split(":", 1)[1]
                if name in out:
                    out[name] = float(row["value"])
    except Exception as exc:  # noqa: BLE001 — an observer never breaks its caller
        logger.debug("loadability: threshold read failed, using defaults: %s", exc)
    return out


def derive_findings(rows: List[Dict[str, Any]], thresholds: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """PURE. No DB, no clock, no Flask — so it is testable and cannot drift.

    ``rows``: one dict per (node, model) over the window, each carrying
        node_name, model_used, attempts, successes, avg_fail_seconds,
        hours_since_success (None = never succeeded here),
        node_success_pct (that node's overall rate across ALL its models).

    Returns a list of findings. Empty list = nothing to say, which is the
    normal and expected result.
    """
    t = {
        "window_hours": DEFAULT_WINDOW_HOURS,
        "min_attempts": float(DEFAULT_MIN_ATTEMPTS),
        "stale_success_hours": DEFAULT_STALE_SUCCESS_HOURS,
        "min_fail_seconds": DEFAULT_MIN_FAIL_SECONDS,
        "node_healthy_pct": DEFAULT_NODE_HEALTHY_PCT,
        **(thresholds or {}),
    }
    findings: List[Dict[str, Any]] = []

    for r in rows or []:
        try:
            attempts = int(r.get("attempts") or 0)
            successes = int(r.get("successes") or 0)
            node_pct = float(r.get("node_success_pct") or 0.0)
            hours_since = r.get("hours_since_success")
            avg_fail = float(r.get("avg_fail_seconds") or 0.0)
        except (TypeError, ValueError):
            continue  # a malformed row is skipped, never guessed at

        # (3) recent attempts, zero successes
        if successes > 0 or attempts < t["min_attempts"]:
            continue
        # (2) it has worked on this node before — otherwise it was never placeable here
        if hours_since is None:
            continue
        if float(hours_since) < t["stale_success_hours"]:
            continue
        # (4) timeouts, not fast errors
        if avg_fail < t["min_fail_seconds"]:
            continue
        # (5) the node itself is fine
        if node_pct < t["node_healthy_pct"]:
            continue

        # TWO DIFFERENT FAULTS, and conflating them sends people to the wrong fix.
        #
        # Measured 2026-09-11, both present on the same fleet at the same time:
        #
        #   cannot_load — qwen2.5-coder:7b on the hub. Nothing completes at all;
        #       VRAM never moves, no runner spawns. Fix is the SCHEDULER (a
        #       restart cleared it: 420s timeout -> 3.7s).
        #
        #   too_slow    — dolphin3:latest on USS-246. It DOES complete, at
        #       325-392s, against a 300s wall. Its failures sit at exactly 300.1s
        #       because that is the deadline killing it, not the model hanging.
        #       Fix is the DEADLINE, the placement, or the model choice — a
        #       restart would change nothing.
        #
        # The discriminator is the success DURATION: if the model, when it does
        # work on this node, takes LONGER than the wall its failures are dying
        # at, then the wall is the fault. Same shape fleet.md records for
        # gemma3:12b on fact_check ("too SLOW for that wall, not wrong").
        succ_s = r.get("success_seconds")
        try:
            too_slow = succ_s is not None and float(succ_s) >= avg_fail
        except (TypeError, ValueError):
            too_slow = False

        model, node = r.get("model_used"), r.get("node_name")
        if too_slow:
            detail = (
                f"{model} on {node}: {attempts} attempts, 0 succeeded — but it DOES "
                f"run here, at {round(float(succ_s))}s, against a wall that kills it "
                f"at {round(avg_fail)}s. Too slow for its deadline, not broken. Last "
                f"success {round(float(hours_since))}h ago; the node runs "
                f"{round(node_pct)}% overall. Fix the deadline, the placement, or "
                f"the model choice — restarting will not help."
            )
        else:
            detail = (
                f"{model} on {node}: {attempts} attempts, 0 succeeded, mean "
                f"{round(avg_fail)}s (timeouts), last success "
                f"{round(float(hours_since))}h ago — while the node runs "
                f"{round(node_pct)}% overall. The node is healthy but can no "
                f"longer load this model."
            )

        findings.append(
            {
                "node_name": node,
                "model": model,
                "kind": "too_slow" if too_slow else "cannot_load",
                "attempts": attempts,
                "avg_fail_seconds": round(avg_fail, 1),
                "success_seconds": round(float(succ_s), 1) if succ_s is not None else None,
                "hours_since_success": round(float(hours_since), 1),
                "node_success_pct": round(node_pct),
                "confidence": "certain",
                "detail": detail,
            }
        )

    return findings


_SQL = """
WITH scoped AS (
    SELECT COALESCE(r.node_name, 'hub') AS node_name,
           t.model_used,
           t.success,
           t.duration_ms,
           t.created_at
      FROM task_execution_log t
      LEFT JOIN remote_nodes r ON r.id = t.node_used_id
     WHERE t.created_at > now() - (%(window)s || ' hours')::interval
       AND t.model_used IS NOT NULL
       AND t.model_used NOT IN ('bridge-managed', 'internal', 'batch', 'browser')
       AND NOT (NOT t.success AND (
                t.error_message ILIKE '%%hub saturated%%'
             OR t.error_message ILIKE '%%admission cap%%'
             OR t.error_message ILIKE '%%shed to relieve%%'
             OR t.error_message ILIKE '%%backpressure%%'))
),
per_node AS (
    SELECT node_name,
           100.0 * count(*) FILTER (WHERE success) / NULLIF(count(*), 0) AS node_success_pct
      FROM scoped GROUP BY node_name
)
SELECT s.node_name,
       s.model_used,
       count(*) AS attempts,
       count(*) FILTER (WHERE s.success) AS successes,
       COALESCE(avg(s.duration_ms) FILTER (WHERE NOT s.success), 0) / 1000.0 AS avg_fail_seconds,
       p.node_success_pct,
       -- ⚠️ BOUNDED DELIBERATELY, and ONE lateral rather than two correlated
       -- subqueries. Unbounded this scanned task_execution_log once per
       -- (node, model) and measured 16.0s; the bound plus the lateral keeps the
       -- JOB around 10s. It must never run on a request path — see
       -- findings_for_display().
       --
       -- The 30-day bound costs nothing real: a model whose last success here is
       -- older than that reads as NULL, which the rule already treats as "never
       -- succeeded on this node" and therefore not-a-finding. Correct anyway — a
       -- model idle for a month is unused, not frozen.
       succ.hours_since_success,
       succ.success_seconds
  FROM scoped s
  JOIN per_node p ON p.node_name = s.node_name
  LEFT JOIN LATERAL (
      -- BOTH halves of the success picture in one pass: WHEN it last worked, and
      -- HOW LONG it takes when it does. The duration is what separates "will not
      -- load" from "runs fine but misses its deadline" — see derive_findings.
      SELECT EXTRACT(EPOCH FROM (now() - max(t2.created_at))) / 3600.0 AS hours_since_success,
             avg(t2.duration_ms) / 1000.0                              AS success_seconds
        FROM task_execution_log t2
        LEFT JOIN remote_nodes r2 ON r2.id = t2.node_used_id
       WHERE t2.created_at > now() - interval '30 days'
         AND COALESCE(r2.node_name, 'hub') = s.node_name
         AND t2.model_used = s.model_used
         AND t2.success
  ) succ ON TRUE
 GROUP BY s.node_name, s.model_used, p.node_success_pct,
          succ.hours_since_success, succ.success_seconds
"""


def _load_rows(window_hours: float) -> List[Dict[str, Any]]:
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (_c, cur):
        cur.execute(_SQL, {"window": str(window_hours)})
        return [dict(r) for r in (cur.fetchall() or [])]


_SETTING_LAST = "loadability:last_findings"


def _persist(findings: List[Dict[str, Any]]) -> None:
    """Store the job's findings so a UI panel never has to compute them."""
    import json

    from services.time_utils import now_utc

    try:
        from database import get_db_cursor

        payload = json.dumps({"at": now_utc().isoformat(), "findings": findings})
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                """INSERT INTO system_config (key, value) VALUES (%s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (_SETTING_LAST, payload),
            )
    except Exception as exc:  # noqa: BLE001 — a failed write must not kill the check
        # ⚠️ WARNING, not debug. This write IS the panel's data source: if it
        # fails, the Cluster tab keeps rendering the last successful findings
        # forever and nothing says so — stale data presented as current, which
        # is the failure mode this whole module exists to detect. At debug level
        # (below the configured threshold) that would be invisible. Found while
        # diagnosing #6694, where exactly this kind of silence cost hours.
        logger.warning("loadability: persist FAILED — panel will show stale findings: %s", exc)


def findings_for_display() -> List[Dict[str, Any]]:
    """The LAST COMPUTED findings, for a UI panel. One row read. Never raises.

    ⚠️ THE PANEL MUST NOT COMPUTE THIS. Measured on the live table, the query
    behind it takes **12-16 seconds**: its hours_since_success is a correlated
    subquery over task_execution_log, run once per (node, model). Bounding it to
    30 days barely moved the number, because the table is enormous even over 30
    days. A per-worker TTL cache does not save you either — it just means every
    worker eats the 12s once per window, on a request the operator is waiting on.
    So the producer is the 30-minute job and this is a pure read.

    An empty list means EITHER nothing is wrong OR the job has not run yet. The
    caller cannot tell them apart, which is correct for a warning surface: it
    shows a warning when there is one and stays silent otherwise. Do not invert
    it into a health claim.
    """
    import json

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute("SELECT value FROM system_config WHERE key = %s", (_SETTING_LAST,))
            row = cur.fetchone()
        if not row:
            return []
        return list(json.loads(row["value"]).get("findings") or [])
    except Exception as exc:  # noqa: BLE001 — a panel must never break on its own warning
        logger.debug("loadability: display read failed: %s", exc)
        return []


def check_model_loadability() -> Dict[str, Any]:
    """Entry point. NEVER raises — an observer that can break its caller is
    worse than no observer (same contract as residency_monitor.check_residency).
    """
    # #6694 — an observer whose RUNS are invisible cannot be told apart from one
    # that never runs. This line is the difference: a clean cycle writes [] and
    # would otherwise leave no trace anywhere a human looks.
    logger.info("loadability: check starting")
    try:
        t = _thresholds()
        rows = _load_rows(t["window_hours"])
        findings = derive_findings(rows, t)
    except Exception as exc:  # noqa: BLE001
        logger.warning("loadability: check failed: %s", exc)
        return {"ok": False, "error": str(exc), "findings": [], "alerted": []}

    # Persist BEFORE alerting: the UI surface must reflect the latest state even
    # if Telegram is down, and a failed alert must not cost the panel its data.
    # Writing [] is deliberate — it CLEARS a finding once the fault is fixed.
    _persist(findings)

    alerted: List[str] = []
    if findings:
        try:
            from services.telegram_service import send_system

            for f in findings:
                # Node+model in the TITLE: send_system dedups on (title, source),
                # so a shared title would mute every node after the first — the
                # exact trap backup_posture_monitor documents for tiers.
                # The TITLE carries the fault kind: send_system dedups on
                # (title, source), and a node flipping between the two faults
                # must not be muted by the other's cooldown.
                _what = "too slow for deadline" if f.get("kind") == "too_slow" else "cannot load"
                send_system(
                    title=f"Model {_what}: {f['model']} on {f['node_name']}",
                    message=f["detail"],
                    source="model_loadability_monitor",
                    severity="warning",
                    cooldown_hours=6.0,
                )
                alerted.append(f"{f['node_name']}/{f['model']}")
        except Exception as exc:  # noqa: BLE001 — comms down must not break the loop
            logger.warning("loadability: telegram unavailable: %s", exc)

    logger.info(
        "loadability: checked %d node/model pairs, %d finding(s), %d alerted",
        len(rows),
        len(findings),
        len(alerted),
    )
    return {"ok": True, "checked": len(rows), "findings": findings, "alerted": alerted}
