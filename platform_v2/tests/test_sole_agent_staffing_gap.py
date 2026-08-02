"""A lone maxed agent must reach the Hiring Queue, not just the digest text.

MEASURED 2026-08-02. P.U.B.L.I.S.H. is the ONLY holder of ``beat_classification`` and ran
654,032 tokens against a 150,000/day budget (4.36x), 3,024 runs, zero failures. K.I.N. SAW
it — ``gather_sole_agent_capabilities`` returns the capability and ``recommend()`` raises a
``staffing_gap`` — but that rec is advisory TEXT. The only path to
``hiring_service.propose_for_gap`` (and so to the DHQ Hiring Queue) was
``recommend_pool_staffing_gaps``, which requires ``COUNT(DISTINCT agent) >= 2``.

Result: every ``hiring_candidates`` row on the platform carried a ``pool_saturation:``
reason and not one a sole-agent reason. The most overloaded agent on the platform could be
described forever and never queued for hire.

THE ASYMMETRY THAT MATTERS (the first test below pins it):
the pool signal requires >= ``welfare:staffing:min_backlog`` (default 3) queued dispatches.
``beat_classification`` had **ZERO** queued dispatches in the same 24h — a lone agent has
nothing to queue behind and simply absorbs the load. The empty queue is a SYMPTOM of the
overwork. Copying the backlog gate would have produced a signal that could never fire for
the case that motivated it.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import welfare_governance_service as wgs  # noqa: E402

SOLO_ROW = {"skill": "beat_classification", "agent_id": 372, "agent_name": "P.U.B.L.I.S.H."}


def _cursor_returning(rows):
    """Patch get_db_cursor so the function under test sees `rows`."""
    cur = MagicMock()
    cur.fetchall.return_value = rows
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), cur))
    ctx.__exit__ = MagicMock(return_value=False)
    return patch("database.get_db_cursor", return_value=ctx)


def test_fires_with_zero_backlog_the_whole_point():
    """A sole agent over budget must be flagged even with an EMPTY dispatch queue.

    This is the regression that matters. dispatch_pending_queue is never consulted here;
    if someone later adds a backlog gate "for consistency with the pool path", this fails.
    """
    with _cursor_returning([SOLO_ROW]), patch.object(wgs, "pool_over_budget_by_skill", return_value=True):
        gaps = wgs.recommend_sole_agent_staffing_gaps()

    assert len(gaps) == 1
    assert gaps[0]["capability"] == "beat_classification"
    assert gaps[0]["agent_name"] == "P.U.B.L.I.S.H."
    assert gaps[0]["pool_size"] == 1
    assert gaps[0]["signal"] == "sole_agent_saturation"
    assert gaps[0]["gap_reason"].startswith("sole_agent_saturation:")


def test_does_not_fire_when_the_sole_agent_is_within_budget():
    """Being alone is not itself a gap — the agent must actually be saturated."""
    with _cursor_returning([SOLO_ROW]), patch.object(wgs, "pool_over_budget_by_skill", return_value=False):
        assert wgs.recommend_sole_agent_staffing_gaps() == []


def test_gap_reason_is_distinguishable_from_pool_saturation():
    """hiring_candidates.gap_reason must say WHICH signal fired.

    Both signals write to the same table; an operator has to be able to tell a jointly-maxed
    pool from a single point of failure, because the remedies differ.
    """
    with _cursor_returning([SOLO_ROW]), patch.object(wgs, "pool_over_budget_by_skill", return_value=True):
        reason = wgs.recommend_sole_agent_staffing_gaps()[0]["gap_reason"]

    assert "pool_saturation:" not in reason
    assert "only active agent" in reason


def test_fails_open_on_a_db_error():
    """Never fabricate a hiring signal from a DB hiccup."""
    with patch("database.get_db_cursor", side_effect=RuntimeError("db down")):
        assert wgs.recommend_sole_agent_staffing_gaps() == []


def test_fails_open_when_the_budget_check_raises():
    with _cursor_returning([SOLO_ROW]), patch.object(
        wgs, "pool_over_budget_by_skill", side_effect=RuntimeError("boom")
    ):
        assert wgs.recommend_sole_agent_staffing_gaps() == []


def test_pool_signal_still_requires_two_agents():
    """The pool path must keep its >= 2 HAVING clause — the two signals stay distinct.

    Source-level so it cannot be quietly relaxed to >= 1, which would double-file every
    sole-agent capability into hiring_candidates under the wrong reason.
    """
    import inspect

    src = inspect.getsource(wgs.recommend_pool_staffing_gaps)
    assert "COUNT(DISTINCT a.id) >= 2" in src
    solo_src = inspect.getsource(wgs.recommend_sole_agent_staffing_gaps)
    assert "COUNT(DISTINCT a.id) = 1" in solo_src


def test_alert_does_not_borrow_pool_wording_for_a_sole_agent():
    """The alert must not read 'all 1 active agent(s) ... with None dispatch(es) queued'.

    _emit_pool_staffing_alert reads backlog with .get(), so a sole-agent gap (which has no
    backlog by design) rendered a literal 'None' and stamped signal=pool_saturation — an
    alert that misdescribes its own cause.
    """
    from services import agent_jobs

    sent = {}

    def _capture(title, msg):
        sent["title"], sent["msg"] = title, msg

    gap = {
        "capability": "beat_classification",
        "pool_size": 1,
        "agent_name": "P.U.B.L.I.S.H.",
        "signal": "sole_agent_saturation",
    }
    with patch("services.creed_emit.emit_event") as emit, patch(
        "services.telegram_service.send_info", side_effect=_capture
    ):
        agent_jobs._emit_pool_staffing_alert("beat_classification", gap, 999)

    assert "None dispatch" not in sent["msg"]
    assert "queued in the last 24h" not in sent["msg"]
    assert "single point of failure" in sent["msg"]
    assert "P.U.B.L.I.S.H." in sent["msg"]
    assert emit.call_args.kwargs["metadata"]["signal"] == "sole_agent_saturation"


def test_alert_keeps_pool_wording_for_a_real_pool_gap():
    """The pool message must be untouched — this change adds a branch, it does not replace one."""
    from services import agent_jobs

    sent = {}
    gap = {"capability": "fact_check", "pool_size": 3, "backlog": 7}
    with patch("services.creed_emit.emit_event") as emit, patch(
        "services.telegram_service.send_info", side_effect=lambda t, m: sent.update(msg=m)
    ):
        agent_jobs._emit_pool_staffing_alert("fact_check", gap, 1000)

    assert "all 3 active agent(s)" in sent["msg"]
    assert "7 dispatch(es) queued in the last 24h" in sent["msg"]
    assert emit.call_args.kwargs["metadata"]["signal"] == "pool_saturation"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
