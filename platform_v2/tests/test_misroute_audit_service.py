"""S.P.E.C.T.R.A. misroute audit — backpressure must not read as agent failure.

When the hub's 7B in-flight admission cap is reached the dispatcher sheds
the dispatch and writes a ``success=false`` row carrying an explicit
backpressure error (``department_dispatcher`` raises it with
``{"backpressure": True}``). That is capacity control, not an agent
defect — ``agent_jobs._check_cluster_saturation`` already classifies the
very same rows as "NOT agent errors" and raises its own
``cluster_saturation`` advisory.

These tests pin that ``_high_failure_agents`` agrees with that reading:
sheds are excluded from BOTH the failure count and the call count, so a
healthy agent caught in a saturation burst is not reported as failing,
and shed volume cannot dilute a genuine failure rate below the alert
threshold.

Real-DB tests: the behaviour under test lives in SQL, so a mocked cursor
would prove nothing. Runs against the isolated ``archie_test`` schema
clone (see conftest ``_isolated_test_db``); ``db_conn`` rolls back.
"""

from __future__ import annotations

import pytest
from psycopg2.extras import RealDictCursor

from services import misroute_audit_service as svc

# Verbatim from department_dispatcher.py — the string the dispatcher writes.
SHED_ERROR = "hub saturated — 7B in-flight admission cap reached; " "shed to relieve the hub (retry shortly)"
REAL_ERROR = "model returned malformed JSON after 3 attempts"


@pytest.fixture
def cur(db_conn):
    with db_conn.cursor(cursor_factory=RealDictCursor) as c:
        yield c


def _agent(cur, agent_name):
    """Create a throwaway agents row and return its id.

    #5809: the audit now admits a row only when ``agent_id`` is populated, so a
    seed that sets ``agent_name`` alone no longer represents agent work — that is
    precisely the UNATTRIBUTED shape the dispatcher reserves for infrastructure.
    """
    cur.execute(
        """
        INSERT INTO agents (name, model, department, floor)
        VALUES (%s, 'qwen2.5:7b', 'Engineering & Technology', 'ENGINEERING')
        RETURNING id
        """,
        (agent_name,),
    )
    return cur.fetchone()["id"]


def _seed(cur, agent_name, capability="fact_check", ok=0, shed=0, real_fail=0, attributed=True):
    """Insert a synthetic dispatch history for one (agent, capability) pair.

    ``attributed=False`` reproduces an infrastructure row: agent_name present as an
    informational marker, agent_id NULL — what department_dispatcher writes for
    ``fleet_warmup`` / ``kin_warmth``.
    """
    agent_id = _agent(cur, agent_name) if attributed else None
    rows = [(True, None)] * ok + [(False, SHED_ERROR)] * shed + [(False, REAL_ERROR)] * real_fail
    for success, err in rows:
        cur.execute(
            """
            INSERT INTO task_execution_log
                (agent_id, agent_name, capability, success, error_message, created_at)
            VALUES (%s, %s, %s, %s, %s, now())
            """,
            (agent_id, agent_name, capability, success, err),
        )


def _flagged(cur, agent_name):
    return [r for r in svc._high_failure_agents(cur, 24) if r["agent_name"] == agent_name]


def test_backpressure_sheds_do_not_flag_a_healthy_agent(cur):
    """R.O.S.E.T.T.A.'s real 2026-07-17 shape: 30 clean calls, 26 shed in a burst.

    The audit reported her at 46.4% failure and escalated severity to
    'error'. Every one of those 'failures' was the hub shedding load.
    """
    _seed(cur, "T.E.S.T.rosetta", capability="knowledge_analysis", ok=30, shed=26)

    assert _flagged(cur, "T.E.S.T.rosetta") == []


def test_genuine_failures_still_flag_an_agent(cur):
    """Guard against over-filtering: real errors must survive the exclusion."""
    _seed(cur, "T.E.S.T.broken", ok=5, real_fail=10)

    flagged = _flagged(cur, "T.E.S.T.broken")

    assert len(flagged) == 1
    assert flagged[0]["failures"] == 10
    assert flagged[0]["total_calls"] == 15
    assert flagged[0]["failure_pct"] == pytest.approx(66.7, abs=0.1)


def test_shed_volume_cannot_dilute_a_genuine_failure_rate(cur):
    """Sheds must leave the denominator, not just the numerator.

    6 real failures in 11 real calls is 54.5% — a genuine problem. Counting
    50 sheds as 'calls' drops it to 9.8%, under the 20% threshold, and the
    agent silently stops being reported. Saturation must never mask a real
    defect.
    """
    _seed(cur, "T.E.S.T.diluted", ok=5, real_fail=6, shed=50)

    flagged = _flagged(cur, "T.E.S.T.diluted")

    assert len(flagged) == 1, "a real 54.5% failure rate was hidden by shed dilution"
    assert flagged[0]["total_calls"] == 11
    assert flagged[0]["failures"] == 6
    assert flagged[0]["failure_pct"] == pytest.approx(54.5, abs=0.1)


def test_min_call_threshold_applies_after_sheds_are_excluded(cur):
    """7 real calls is too little signal to judge, however many were shed."""
    _seed(cur, "T.E.S.T.lowvolume", ok=2, real_fail=5, shed=40)

    assert _flagged(cur, "T.E.S.T.lowvolume") == []


def test_warmup_keepalives_are_not_scored_as_agent_failures(cur):
    """#5809: E.M.B.E.R. was reported misrouted to `documentation` and failing 100%.

    She was never selected for it — ``select_agent`` correctly excludes her (she holds
    no documentation skill). The rows were ``fleet_warmup`` keep-alives, which
    department_dispatcher logs with ``log_agent_id = None`` while KEEPING agent_name
    as "an informational marker of which model was warmed". The audit admitted them
    and scored infrastructure as agent behaviour.

    Measured 2026-08-22 over 24h: 20 pairs above the 20% threshold, 0 of which had an
    agent_id. The entire alarm population was infra.
    """
    _seed(cur, "T.E.S.T.ember", capability="documentation", ok=0, real_fail=26, attributed=False)

    assert _flagged(cur, "T.E.S.T.ember") == []


def test_the_filter_does_not_silence_a_real_agent(cur):
    """The guard against over-correcting: identical failure volume, but attributed.

    If this ever goes green alongside the test above, the filter has stopped
    discriminating and is simply suppressing the audit.
    """
    _seed(cur, "T.E.S.T.attributed", capability="documentation", ok=0, real_fail=26, attributed=True)

    flagged = _flagged(cur, "T.E.S.T.attributed")

    assert len(flagged) == 1
    assert flagged[0]["failures"] == 26
    assert flagged[0]["agent_id"] is not None
