"""Distress opt-out must not blame an agent for infrastructure (#5129).

CONTEXT. `department_coordinator._refresh_distress()` scores an agent down by 1.5 on a
capability it is failing sustainedly. It originally counted EVERY `NOT success` row.
On 2026-07-23 that scored F.O.R.G.E. down on 'code_review' — its own core capability —
during hub saturation: a 240s fleet timeout against a model with a measured 600s cold
load (`warm_boot_ms = 600104`), hub 7B lane gated at 9-12 in-flight vs a cap of 8.
The agent was penalised for a GPU queue it did not cause.

THE TWO PROPERTIES THAT MATTER, AND THEY PULL IN OPPOSITE DIRECTIONS:
  * infra timeouts must NOT count against the agent   (else contention looks like incompetence)
  * genuine failures MUST still trigger the step-back  (else welfare silently stops working)

A fix that only satisfies the first is a welfare REGRESSION, not a fix. Both are pinned
below, and `test_genuine_failures_still_trigger` is the one that must never be deleted.

WHY INFRA ROWS LEAVE THE DENOMINATOR TOO: a request that never reached the model tells
us nothing about the agent in EITHER direction. Leaving it in the denominator would
dilute a real failure rate below 0.6 and mask an agent that genuinely is struggling —
the opposite failure, and a quieter one.
"""

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import db_or_skip  # noqa: E402

# The exact predicate shipped in department_coordinator._refresh_distress. Kept verbatim
# so a drift between this test and the query is a RED test, not a silent divergence.
_SQL = """
WITH classified AS (
    SELECT agent_id, capability, success,
           (NOT success AND COALESCE(error_message, '') ~*
             'timeout|timed out|did not respond|reaped|stale|auto-killed') AS is_infra
    FROM _rows
)
SELECT agent_id, capability,
       COUNT(*) FILTER (WHERE NOT is_infra) AS attributable,
       COUNT(*) FILTER (WHERE NOT success AND NOT is_infra) AS fails
FROM classified
GROUP BY agent_id, capability
HAVING COUNT(*) FILTER (WHERE NOT is_infra) >= 5
   AND COUNT(*) FILTER (WHERE NOT success AND NOT is_infra)::float
       / NULLIF(COUNT(*) FILTER (WHERE NOT is_infra), 0) >= 0.6
"""


def _distressed(cur, rows):
    """Feed (success, error_message) rows through the real predicate via a VALUES CTE."""
    values = ", ".join(cur.mogrify("(1, 'code_review', %s, %s)", (s, e)).decode() for s, e in rows)
    cur.execute(_SQL.replace("_rows", f"(VALUES {values}) AS t(agent_id, capability, success, error_message)"))
    return cur.fetchall()


@pytest.fixture()
def cur():
    try:
        from database import get_db_cursor
    except Exception as exc:  # pragma: no cover
        db_or_skip(exc)
    try:
        with get_db_cursor() as (_conn, c):
            yield c
    except Exception as exc:  # pragma: no cover
        db_or_skip(exc)


_TIMEOUT = "fleet dispatch timeout after 240s"
_REAL = "model returned unparseable JSON"


# ------------------------------------------------- infra must not be blamed ---
def test_pure_infra_timeouts_never_trigger_distress(cur):
    """THE #5129 CASE. Ten straight timeouts, zero genuine failures -> not distress."""
    assert _distressed(cur, [(False, _TIMEOUT)] * 10) == []


def test_infra_leaves_the_denominator_not_just_the_numerator(cur):
    """8 infra + 5 attributable of which 3 genuinely failed = 3/5 = 60% -> DISTRESS.

    If infra rows stayed in the denominator this would be 3/13 = 23% and the agent
    would be masked. That is the quiet failure this test exists to prevent."""
    rows = [(False, _TIMEOUT)] * 8 + [(False, _REAL)] * 3 + [(True, None)] * 2
    out = _distressed(cur, rows)
    assert len(out) == 1, "a genuinely struggling agent was masked by surrounding timeouts"
    # get_db_cursor() is a RealDictCursor — rows are dicts, NOT tuples. Indexing them
    # positionally yields the KEYS, which reads as a baffling assertion failure.
    assert (out[0]["attributable"], out[0]["fails"]) == (5, 3)


# ------------------------------------------ welfare must still work ----------
def test_genuine_failures_still_trigger(cur):
    """DO NOT DELETE. The step-back is a welfare feature; suppressing it entirely would
    be a regression dressed up as a fix."""
    out = _distressed(cur, [(False, _REAL)] * 4 + [(True, None)] * 1)
    assert len(out) == 1
    assert out[0]["fails"] == 4


def test_healthy_agent_is_not_flagged(cur):
    assert _distressed(cur, [(True, None)] * 10) == []


def test_just_under_the_rate_threshold_is_not_flagged(cur):
    """0.5 < 0.6 -> no distress. Threshold unchanged by #5129."""
    assert _distressed(cur, [(False, _REAL)] * 3 + [(True, None)] * 3) == []


# ------------------------------------------------- sample-size floor ---------
def test_minimum_applies_to_attributable_not_total(cur):
    """20 timeouts + 2 real failures: 100% of attributable, but only 2 attempts.

    Pre-fix this had 22 rows and would clear a >=5 floor measured on the total. Measuring
    the floor on ATTRIBUTABLE makes the gate strictly more conservative than before."""
    assert _distressed(cur, [(False, _TIMEOUT)] * 20 + [(False, _REAL)] * 2) == []


# ------------------------------------------------- signature guard -----------
def test_advisory_signature_still_matches():
    """The advisory sits inside a broad `except`, so a signature drift would be SWALLOWED
    and the alert would silently never fire — an unmonitored monitor. Pin it."""
    import inspect

    try:
        from services.telegram_service import send_system
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"telegram_service unavailable: {exc}")

    params = inspect.signature(send_system).parameters
    assert "title" in params and "message" in params


def test_query_and_enforcement_stay_together():
    """The scoring penalty and the refresh must both keep referencing _distress."""
    import inspect

    try:
        from services import department_coordinator as dc
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"coordinator unavailable: {exc}")

    src = inspect.getsource(dc)
    assert "is_infra" in src, "infra classification missing from _refresh_distress"
    assert "auto-killed" in src, "timeout signature drifted from dispatch_health_service (#4538)"
    assert "score -= 1.5" in src, "the distress penalty was removed — welfare no longer acts"
