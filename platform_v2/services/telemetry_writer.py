"""Shared telemetry writer for NON-LLM orchestration / job markers (#4344).

Background
----------
`task_execution_log` is written by two kinds of producers:

  1. REAL per-inference rows — written ONLY by the DHQ dispatcher's
     ``_log_execution`` (the "sole per-inference logger", #1391). Those carry a
     non-NULL ``worker_type`` ('internal' for local agents, 'contract' for
     external CLIs) and real ``model_used`` + ``tokens_used``.

  2. ORCHESTRATION / JOB MARKERS — 0-token bookkeeping rows a scheduled job
     writes once per cycle (cluster_orchestration, workforce_planning,
     welfare_monitoring, the wtf_*_orchestration markers, …). These are NOT
     inference and must be EXCLUDED from every "real LLM" view.

The Token Economy display (code_health_routes.py, PR #1816) already excludes
markers two ways: ``worker_type IS NOT NULL`` AND a ``model_used`` sentinel
allow-list (``NOT IN ('internal','batch','bridge-managed','browser')`` /
``NOT ILIKE '%embed%'``). Historically each marker was a hand-rolled direct
INSERT with an INCONSISTENT ``model_used`` (sometimes the agent's real model,
sometimes the ``'internal'`` sentinel) — drift-prone and the exact "lying INSERT"
class #1391 cleaned up 18 of.

This helper is the ONE canonical way to write a marker. It bakes in the
convention so callers can't get it wrong and future code can't reintroduce the
drift:

  * ``worker_type`` LEFT NULL  → marker convention (NULL == orchestration row,
    excluded by ``worker_type IS NOT NULL``).
  * ``model_used = 'bridge-managed'`` → an established non-LLM sentinel ALREADY
    in the display exclude-list, so markers are self-evidently non-LLM and stay
    excluded even by a query that forgets the worker_type guard (defense in
    depth — no display/filter change needed).
  * ``tokens_used`` LEFT 0      → never pollutes token sums.

It is STRICTLY FAIL-SAFE: telemetry must never break the calling job, so any DB
error is swallowed (logged at debug) and the function returns False.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# The canonical non-LLM marker sentinel. MUST stay inside the Token Economy
# exclude-list in code_health_routes.py (model_used NOT IN (...,'bridge-managed',...)).
MARKER_MODEL_SENTINEL = "bridge-managed"


def log_marker(
    *,
    capability: str,
    agent_name: str,
    agent_id: Optional[int] = None,
    duration_ms: int = 0,
    success: bool = True,
    node_used_id: Optional[int] = None,
    module_source: str = "agent_loop",
    model_used: str = MARKER_MODEL_SENTINEL,
) -> bool:
    """Write ONE non-LLM orchestration/job marker row to task_execution_log.

    Convention (see module docstring): worker_type NULL, model_used sentinel,
    tokens_used 0. Returns True on success, False on any error (never raises —
    a telemetry failure must not break the caller's job).

    Args:
        capability: the marker capability tag (e.g. 'cluster_orchestration').
        agent_name: the owning agent display/code name (e.g. 'K.I.N.').
        agent_id:   optional agents.id for attribution.
        duration_ms: wall-clock of the cycle being marked.
        success:    whether the cycle succeeded.
        node_used_id: optional remote_nodes.id (NULL = hub).
        module_source: optional source tag (e.g. 'agent_loop', 'wtf_dhq_llm').
        model_used: defaults to the non-LLM sentinel; override only with another
            sentinel already in the exclude-list — NEVER a real model name.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_conn, cur):
            # COALESCE: use an explicit agent_id when given, else resolve from
            # agent_name (preserves the subquery attribution the hand-rolled
            # marker INSERTs used) — NULL only if the name doesn't resolve.
            cur.execute(
                """INSERT INTO task_execution_log
                       (agent_id, agent_name, model_used, duration_ms, success,
                        capability, module_source, node_used_id, tokens_used)
                   VALUES (COALESCE(%s, (SELECT id FROM agents WHERE name=%s LIMIT 1)),
                           %s, %s, %s, %s, %s, %s, %s, 0)""",
                (
                    agent_id,
                    agent_name,
                    agent_name,
                    model_used,
                    int(duration_ms or 0),
                    bool(success),
                    capability,
                    module_source,
                    node_used_id,
                ),
            )
        return True
    except Exception as exc:  # telemetry must never break the caller
        logger.debug("telemetry_writer.log_marker failed for %s/%s: %s", agent_name, capability, exc)
        return False
