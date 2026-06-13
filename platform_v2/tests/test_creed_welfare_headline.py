"""Tests for the DHQ C.R.E.E.D. welfare-card headline helper (audit 2026-06-13, #4130).

`_welfare_headline` makes /api/creed/welfare show the PERSISTED EWMA (honest, matches
/governance) as the headline while preserving the LIVE recompute as live_score/live_grade.
These tests pin that contract — and assert live_score is NOT redundant with score (it
holds the live value captured before score is overwritten with the persisted EWMA).
"""

from __future__ import annotations

from tools.department_hq.creed_routes import _welfare_headline


def _live():
    return {
        "score": 94,
        "grade": "A",
        "recommendations": [{"type": "info", "msg": "x"}],
        "agents": [{"id": 1}],
    }


def test_headline_uses_persisted_ewma_not_live():
    out = _welfare_headline(
        _live(),
        {"ewma_score": 62.0, "ewma_grade": "D", "score": 60, "grade": "D"},
    )
    assert out["score"] == 62.0
    assert out["grade"] == "D"
    assert out["headline_source"] == "persisted_ewma"
    assert out["ewma_score"] == 62.0
    assert out["ewma_grade"] == "D"


def test_live_score_is_preserved_and_distinct_from_headline():
    # Refutes the "live_score is redundant with score" reading: after the EWMA
    # override they differ, and live_score retains the live recompute.
    out = _welfare_headline(_live(), {"ewma_score": 62.0, "ewma_grade": "D"})
    assert out["live_score"] == 94 and out["live_grade"] == "A"
    assert out["score"] == 62.0
    assert out["live_score"] != out["score"]


def test_falls_back_to_persisted_raw_score_when_no_ewma():
    out = _welfare_headline(_live(), {"ewma_score": None, "ewma_grade": None, "score": 71, "grade": "C"})
    assert out["score"] == 71
    assert out["grade"] == "C"
    assert out["headline_source"] == "persisted_ewma"


def test_headline_is_live_when_no_persisted_row():
    out = _welfare_headline(_live(), None)
    assert out["score"] == 94 and out["grade"] == "A"
    assert out["live_score"] == 94 and out["live_grade"] == "A"
    assert out["headline_source"] == "live"


def test_passthrough_preserves_recommendations_and_agents():
    out = _welfare_headline(_live(), {"ewma_score": 62.0, "ewma_grade": "D"})
    assert out["recommendations"] == [{"type": "info", "msg": "x"}]
    assert out["agents"] == [{"id": 1}]


def test_does_not_mutate_input_live_dict():
    live = _live()
    _welfare_headline(live, {"ewma_score": 62.0, "ewma_grade": "D"})
    assert live["score"] == 94  # original untouched
