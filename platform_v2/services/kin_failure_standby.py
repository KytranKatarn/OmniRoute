"""K.I.N. failure-standby candidate selection (#5165).

Extracted from the ``kin_failure_standby`` scheduler closure in
``tools/department_hq/jobs.py``. It lived there as raw inline SQL, which is
precisely why it drifted out of step with the other two consumers of the
"is this failure the agent's fault?" question and shipped a defect that benched
healthy agents (see :mod:`services.infra_failure_filter` for the full history).
A function can be tested; a closure could not.

Semantics — an agent is a standby candidate when, in the window, it has:

* at least ``min_dispatches`` REAL dispatches (infra sheds excluded), and
* a REAL failure ratio at or above ``fail_ratio``.

The threshold is applied AFTER sheds are removed, so a brand-new agent whose
first hour was mostly shed is judged on the handful of dispatches that actually
ran — and if that is too few to judge, it is not judged at all.
"""

from __future__ import annotations

from typing import Any

from services.infra_failure_filter import not_backpressure_sql

# Defaults preserved verbatim from the original job so this extraction is a
# behaviour change ONLY in the infra-shed exclusion.
DEFAULT_WINDOW_HOURS = 1
DEFAULT_MIN_DISPATCHES = 5
DEFAULT_FAIL_RATIO = 0.5


def failing_agents(
    cur: Any,
    *,
    hours: int = DEFAULT_WINDOW_HOURS,
    min_dispatches: int = DEFAULT_MIN_DISPATCHES,
    fail_ratio: float = DEFAULT_FAIL_RATIO,
) -> list[dict]:
    """Active AI agents whose REAL failure rate warrants failure-standby.

    Args:
        cur: an open ``RealDictCursor``.
        hours: look-back window.
        min_dispatches: minimum REAL dispatches before an agent can be judged.
        fail_ratio: REAL failure ratio at/above which the agent is benched.

    Returns:
        Rows of ``{id, name, total, fails}`` where ``total``/``fails`` already
        exclude infra sheds. Empty list when nothing qualifies.

    ``model_used <> 'internal'`` drops orchestration markers (0-token telemetry
    rows that were never inference) — the pre-existing carve-out, preserved.
    """
    # doubled_percent: this statement carries its own psycopg2 parameters, so the
    # ILIKE wildcards must be `%%` or psycopg2 reads `%h` of '%hub saturated%' as a
    # format placeholder and raises "IndexError: tuple index out of range".
    # (Same trap as agent_jobs.py; KB #268832 / #277249.)
    keep_real = not_backpressure_sql(
        success_col="tel.success",
        error_col="tel.error_message",
        doubled_percent=True,
    )

    cur.execute(
        f"""
        SELECT a.id, a.name,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE NOT tel.success) AS fails
        FROM agents a
        JOIN task_execution_log tel ON tel.agent_name = a.name
        WHERE a.worker_type = 'ai' AND a.shift_state = 'active'
          AND tel.created_at > NOW() - make_interval(hours => %s)
          AND COALESCE(tel.model_used, '') <> 'internal'
          AND {keep_real}
        GROUP BY a.id, a.name
        HAVING COUNT(*) >= %s
           AND COUNT(*) FILTER (WHERE NOT tel.success)::float / COUNT(*) >= %s
        """,
        (hours, min_dispatches, fail_ratio),
    )
    return [dict(r) for r in (cur.fetchall() or [])]
