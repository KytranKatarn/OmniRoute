"""K.I.N. starving flags must be decided per-AGENT, not per-DEPARTMENT (#5376).

The old discriminator was ``has_loop_activity`` — whether the agent's DEPARTMENT logged
a successful autonomy_loop_log row in 24h. That says nothing about the agent, and
measured 2026-08-02 it was INVERTED on the two cases that matter:

    A.R.C.H.I.E.  101,828 runs, ran today  -> starving_no_llm
    F.A.C.T.       17,538 runs, ran today  -> starving_idle   ("routing gap")
    L.E.D.G.E.R.        0 runs, EVER       -> starving_no_llm ("expected, ignore")

The busiest agent on the platform was reported as starving while the only genuinely
never-dispatched one was filed as noise.

⚠️ The flag VOCABULARY is load-bearing and must not grow: ``welfare_load.kin_action_allowed``
is FAIL-OPEN on unknown flags, so a new flag string would silently become unconstrained and
let K.I.N. run any action against it. These tests pin the vocabulary as well as the logic.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from services import agent_service as svc
from services.welfare_load import kin_action_allowed

_BASE = {
    "id": 1,
    "name": "T.E.S.T.",
    "display_name": "Test",
    "department": "Engineering & Technology",
    "shift_state": "active",
    "tokens_used_today": 0,
    "token_limit_per_day": 100000,
    "current_task_count": 0,
    "stress_level": 0.2,
    "stress_7d_avg": 0.2,
    "runs_ever": 0,
    "last_run_days": None,
}


def _row(**kw):
    return dict(_BASE, **kw)


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = " ".join(str(sql).split())

    def fetchall(self):
        return self._rows


def _patch(rows):
    cur = FakeCursor(rows)

    @contextmanager
    def _fake(*_a, **_k):
        yield (None, cur)

    return patch.object(svc, "get_db_cursor", _fake), cur


def _flags_for(**kw):
    ctx, _cur = _patch([_row(**kw)])
    with ctx:
        return svc._get_agent_welfare_outliers()


def _flag_of(**kw):
    f = _flags_for(**kw)
    return f[0]["flag"] if f else None


# ---------------------------------------------------------------------------
# the per-agent discriminator
# ---------------------------------------------------------------------------


def test_never_executed_is_actionable():
    """L.E.D.G.E.R.: 0 runs ever. The strongest starving signal there is."""
    assert _flag_of(runs_ever=0, last_run_days=None) == "starving_idle"


def test_ran_today_is_not_a_routing_gap():
    """F.A.C.T.: 17,538 runs, ran today, zero tokens (0-token marker rows)."""
    assert _flag_of(runs_ever=17538, last_run_days=0.2) == "starving_no_llm"


def test_busiest_agent_on_the_platform_is_not_starving():
    """A.R.C.H.I.E.: 101,828 runs."""
    assert _flag_of(runs_ever=101828, last_run_days=0.1) == "starving_no_llm"


def test_long_stale_agent_is_actionable():
    """P.R.I.M.E.: 2 runs, last one ~60 days ago."""
    assert _flag_of(runs_ever=2, last_run_days=60.0) == "starving_idle"


@pytest.mark.parametrize(
    "age,expected",
    [
        (0.0, "starving_no_llm"),
        (6.9, "starving_no_llm"),
        (7.0, "starving_no_llm"),  # boundary is inclusive
        (7.1, "starving_idle"),
        (30.0, "starving_idle"),
    ],
)
def test_recency_boundary(age, expected):
    assert _flag_of(runs_ever=5, last_run_days=age) == expected


def test_null_age_with_nonzero_runs_fails_to_the_actionable_side():
    """Defensive: `None < 7` raises and `not None` would read as 'recent'."""
    assert _flag_of(runs_ever=9, last_run_days=None) == "starving_idle"


def test_department_is_no_longer_consulted():
    """Two identical agents in different departments must classify identically."""
    a = _flag_of(runs_ever=0, last_run_days=None, department="Finance & Accounting")
    b = _flag_of(runs_ever=0, last_run_days=None, department="News & Media")
    assert a == b == "starving_idle"


def test_the_query_no_longer_uses_dept_loop_activity():
    """The old per-department CTE must be gone, not merely unused."""
    ctx, cur = _patch([])
    with ctx:
        svc._get_agent_welfare_outliers()
    assert "dept_loop_activity" not in cur.sql
    assert "agent_exec" in cur.sql


def test_flags_carry_the_evidence_that_raised_them():
    f = _flags_for(runs_ever=0, last_run_days=None)[0]
    assert f["runs_ever"] == 0 and f["last_run_days"] is None
    g = _flags_for(runs_ever=42, last_run_days=3.14159)[0]
    assert g["runs_ever"] == 42 and g["last_run_days"] == 3.1


# ---------------------------------------------------------------------------
# invariants the rest of the platform depends on
# ---------------------------------------------------------------------------


def test_over_budget_still_wins_over_starving():
    """An over-budget agent must never be reported as starving."""
    assert _flag_of(tokens_used_today=99000, token_limit_per_day=100000) == "over_budget"


def test_vocabulary_is_unchanged_so_the_action_policy_still_binds():
    """kin_action_allowed is FAIL-OPEN: a new flag name would be unconstrained."""
    produced = {
        _flag_of(runs_ever=0, last_run_days=None),
        _flag_of(runs_ever=5, last_run_days=1.0),
        _flag_of(tokens_used_today=99000, token_limit_per_day=100000),
    }
    assert produced == {"starving_idle", "starving_no_llm", "over_budget"}
    # and the policy still discriminates between them
    assert kin_action_allowed("starving_no_llm", "welfare_recovery") is False
    assert kin_action_allowed("starving_idle", "welfare_recovery") is True


def test_inactive_or_busy_agents_are_not_flagged():
    assert _flag_of(shift_state="barracked", runs_ever=0, last_run_days=None) is None
    assert _flag_of(current_task_count=3, runs_ever=0, last_run_days=None) is None
