"""Canonical definition of "this failure was NOT the agent's fault" (#5165).

A ``task_execution_log`` row with ``success = false`` does not necessarily mean
the agent failed. When the hub's 7B in-flight admission cap is reached the
dispatcher REFUSES the dispatch and writes a ``success=false`` row carrying an
explicit backpressure error (it raises ``{"backpressure": True}``), with 0 tokens
and no inference. The work was never handed to the agent.

Reading those rows as agent failures has bitten this platform three times:

* ``agent_jobs`` — a saturation burst fired a storm of false "high error rate"
  HR alerts (#4538 class).
* ``misroute_audit_service`` — reported a healthy R.O.S.E.T.T.A. at 46.4%
  failure and escalated severity to 'error' (2026-07-17).
* ``kin_failure_standby`` — BENCHED healthy agents to 'barracked' (#5165,
  2026-07-24). Replaying the live 24h window, R.O.S.E.T.T.A. scored 993/1045 =
  95% -> bench; excluding sheds she is 0/52 = 0%. The fresh News hires
  G.A.M.B.I.T. and C.O.N.D.U.I.T. were benched within an hour of going active
  on 40/40 and 40/40 sheds respectively — zero real failures between them.

Each site had fixed it locally and the copies drifted; the third one was never
brought in step. This module is that single source of truth. Import it rather
than re-typing the patterns.

TWO RULES when counting failures for any agent-quality judgement:

1. Exclude sheds from the NUMERATOR — a shed is not a defect.
2. Exclude them from the DENOMINATOR too. Leaving them in lets shed volume
   dilute a genuine failure rate below the alert/bench threshold, which would
   MASK a real defect. Saturation must never hide a broken agent.

Rule 2 also removes a structural bias against new hires: because the judgement
is a RATE, the same absolute shed count is a large fraction of a newcomer's
traffic (40 of G.A.M.B.I.T.'s 95 = 42%) but a rounding error for a veteran
(56 of B.I.A.S.'s 8,164 = 0.7%). Counting sheds preferentially destroys exactly
the agents the hiring loop has just created.

The correct home for a saturation signal is
``agent_jobs._check_cluster_saturation``, which raises the ``cluster_saturation``
advisory — an INFRASTRUCTURE alert, not an agent-performance one.
"""

from __future__ import annotations

# ILIKE patterns matching the dispatcher's admission-control / backpressure sheds.
# Keep in step with department_dispatcher.py's shed error string.
BACKPRESSURE_ERROR_PATTERNS: tuple[str, ...] = (
    "%hub saturated%",
    "%admission cap%",
    "%shed to relieve%",
    "%backpressure%",
)

# Infra failures that are also not the agent's fault, but come from the queue /
# reaper rather than admission control. dispatch_health_service splits these as
# `failed_timeout` (#4538). Kept separate: a caller may legitimately want to
# count a timeout against an agent (it did get the work) while never counting a
# shed (it did not).
TIMEOUT_ERROR_PATTERNS: tuple[str, ...] = (
    "%timeout%",
    "%timed out%",
    "%did not respond%",
    "%reaped%",
    "%auto-killed%",
)


def not_backpressure_sql(
    *,
    success_col: str = "tel.success",
    error_col: str = "tel.error_message",
    include_timeouts: bool = False,
    doubled_percent: bool = False,
) -> str:
    """Return a SQL predicate that is TRUE for rows to KEEP.

    Excludes only *failed* rows whose error matches an infra pattern — a
    successful row is always kept, and a failed row with any other message
    (a real agent defect) is always kept.

    Args:
        success_col: qualified boolean success column.
        error_col: qualified error-message column.
        include_timeouts: also drop queue-timeout/reaper rows.
        doubled_percent: double the ``%`` wildcards for callers passing this
            through a psycopg2 format string that has its own parameters
            (otherwise psycopg2 reads ``%h`` as a placeholder and raises
            "unsupported format character"). See KB #268832 / #277249.

    The predicate is built from module constants only — never from caller
    input — so it carries no injection surface.
    """
    patterns = list(BACKPRESSURE_ERROR_PATTERNS)
    if include_timeouts:
        patterns += list(TIMEOUT_ERROR_PATTERNS)

    clauses = " OR ".join(f"{error_col} ILIKE '{p}'" for p in patterns)
    predicate = f"NOT (NOT {success_col} AND ({clauses}))"
    return predicate.replace("%", "%%") if doubled_percent else predicate


def is_infra_failure(error_message: str | None, *, include_timeouts: bool = False) -> bool:
    """Python-side mirror of :func:`not_backpressure_sql` for non-SQL callers."""
    if not error_message:
        return False
    lowered = error_message.lower()
    patterns = list(BACKPRESSURE_ERROR_PATTERNS)
    if include_timeouts:
        patterns += list(TIMEOUT_ERROR_PATTERNS)
    return any(p.strip("%").lower() in lowered for p in patterns)
