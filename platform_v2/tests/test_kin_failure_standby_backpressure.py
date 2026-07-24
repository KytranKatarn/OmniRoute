"""K.I.N. failure-standby — hub backpressure must not read as agent failure (#5165).

Root cause (2026-07-24): ``_run_kin_failure_standby`` benched any active AI agent
with >=5 dispatches and >=50% ``success=false`` in the last hour. It excluded
``model_used='internal'`` but NOT admission-control sheds — the ``success=false``
rows the dispatcher writes, with 0 tokens and no inference, when the hub's 7B
in-flight cap is reached. The work never reached the agent.

Measured impact: 40/40 of G.A.M.B.I.T.'s and 40/40 of C.O.N.D.U.I.T.'s "failures"
were sheds (0 real failures); both fresh News hires were benched to 'barracked'
within an hour of going active, so the approved hires never joined the
dispatchable pool and ``recommend_pool_staffing_gaps`` re-proposed the same News
skills the next day. Replaying the live 24h window, the old logic scored a
perfectly healthy R.O.S.E.T.T.A. at 993/1045 = 95% -> BENCH; excluding sheds she
is 0/52 = 0% -> keep.

Because it is a RATE, shedding is structurally biased against new hires: the same
absolute shed count (40 vs B.I.A.S.'s 56) is 42% of a newcomer's traffic but 0.7%
of a veteran's. So the bencher preferentially destroyed exactly the agents the
hiring loop had just created.

``misroute_audit_service`` and ``agent_jobs`` already classify these same rows as
"NOT agent errors"; this pins the third consumer to that shared reading. The four
properties below mirror ``test_misroute_audit_service.py`` deliberately — the two
call sites must agree.

Real-DB tests: the behaviour lives in SQL, so a mocked cursor would prove nothing.
Runs against the isolated ``archie_test`` schema clone (conftest
``_isolated_test_db``); ``db_conn`` rolls back.
"""

from __future__ import annotations

import pytest
from psycopg2.extras import RealDictCursor

from services import kin_failure_standby as svc

# Verbatim from department_dispatcher.py — the string the dispatcher writes.
SHED_ERROR = "hub saturated — 7B in-flight admission cap reached; " "shed to relieve the hub (retry shortly)"
REAL_ERROR = "model returned malformed JSON after 3 attempts"


@pytest.fixture
def cur(db_conn):
    with db_conn.cursor(cursor_factory=RealDictCursor) as c:
        yield c


def _agent(cur, name, shift_state="active", worker_type="ai"):
    """Create a synthetic active AI agent and return its id."""
    cur.execute(
        """
        INSERT INTO agents (name, model, department, floor, worker_type, shift_state, status)
        VALUES (%s, 'qwen2.5:7b', 'News & Media', 'MEDIA', %s, %s, 'active')
        RETURNING id
        """,
        (name, worker_type, shift_state),
    )
    return cur.fetchone()["id"]


def _seed(cur, agent_name, ok=0, shed=0, real_fail=0, model="qwen2.5:7b"):
    """Insert a synthetic dispatch history for one agent."""
    rows = [(True, None)] * ok + [(False, SHED_ERROR)] * shed + [(False, REAL_ERROR)] * real_fail
    for success, err in rows:
        cur.execute(
            """
            INSERT INTO task_execution_log
                (agent_name, capability, success, error_message, model_used, created_at)
            VALUES (%s, 'bias_analysis', %s, %s, %s, now())
            """,
            (agent_name, success, err, model),
        )


def _flagged(cur, name):
    return [r for r in svc.failing_agents(cur) if r["name"] == name]


def test_backpressure_sheds_do_not_bench_a_healthy_agent(cur):
    """G.A.M.B.I.T.'s real 2026-07-24 shape: 55 clean dispatches, 40 shed.

    The old logic benched her at 42% 'failure'. Every one of those was the hub
    shedding load before the work reached her.
    """
    _agent(cur, "T.E.S.T.gambit")
    _seed(cur, "T.E.S.T.gambit", ok=55, shed=40)

    assert _flagged(cur, "T.E.S.T.gambit") == []


def test_genuine_failures_still_bench_an_agent(cur):
    """Guard against over-filtering: the bencher must keep its teeth."""
    _agent(cur, "T.E.S.T.broken")
    _seed(cur, "T.E.S.T.broken", ok=2, real_fail=8)

    flagged = _flagged(cur, "T.E.S.T.broken")

    assert len(flagged) == 1
    assert flagged[0]["fails"] == 8
    assert flagged[0]["total"] == 10


def test_shed_volume_cannot_dilute_a_genuine_failure_rate(cur):
    """Sheds must leave the denominator, not just the numerator.

    6 real failures in 10 real dispatches is 60% — a genuine problem. Counting
    50 sheds as dispatches drops it to 9.3%, under the 50% gate, and a broken
    agent would keep taking work. Saturation must never MASK a real defect.
    """
    _agent(cur, "T.E.S.T.diluted")
    _seed(cur, "T.E.S.T.diluted", ok=4, real_fail=6, shed=50)

    flagged = _flagged(cur, "T.E.S.T.diluted")

    assert len(flagged) == 1, "a real 60% failure rate was hidden by shed dilution"
    assert flagged[0]["total"] == 10
    assert flagged[0]["fails"] == 6


def test_min_dispatch_threshold_applies_after_sheds_are_excluded(cur):
    """4 real dispatches is too little signal to bench on, however many were shed.

    This is the fresh-hire case: a brand-new agent shed 40 times in its first hour
    must not be judged on the 4 dispatches that actually ran.
    """
    _agent(cur, "T.E.S.T.freshhire")
    _seed(cur, "T.E.S.T.freshhire", ok=1, real_fail=3, shed=40)

    assert _flagged(cur, "T.E.S.T.freshhire") == []


def test_only_active_ai_agents_are_considered(cur):
    """Preserve the original scope: barracked agents and non-AI workers are out."""
    _agent(cur, "T.E.S.T.already_benched", shift_state="barracked")
    _seed(cur, "T.E.S.T.already_benched", ok=1, real_fail=9)
    _agent(cur, "T.E.S.T.human", worker_type="internal")
    _seed(cur, "T.E.S.T.human", ok=1, real_fail=9)

    assert _flagged(cur, "T.E.S.T.already_benched") == []
    assert _flagged(cur, "T.E.S.T.human") == []


def test_internal_marker_rows_are_still_excluded(cur):
    """The pre-existing model_used='internal' carve-out must survive the change.

    Orchestration markers (worker_type NULL, model 'internal', 0 tokens) are not
    inference and were never meant to count.
    """
    _agent(cur, "T.E.S.T.markers")
    _seed(cur, "T.E.S.T.markers", real_fail=9, model="internal")
    _seed(cur, "T.E.S.T.markers", ok=1)

    assert _flagged(cur, "T.E.S.T.markers") == []
