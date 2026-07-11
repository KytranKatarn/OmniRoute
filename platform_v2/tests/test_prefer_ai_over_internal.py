"""Tests for the durable 'prefer AI over internal' dispatch rule
(DepartmentCoordinator._drop_internal_when_ai_holds_skill).

The rule generalizes the per-capability internal-skill retirements (migration 457):
when a capability has a worker_type='ai' holder, the dispatcher must not bill the
work to a legacy worker_type='internal' persona (invisible to the AI budget/welfare/
K.I.N. accounting). Internal agents stay a fallback ONLY when no AI holds the skill,
so internal-only capabilities are unaffected. Pure function — no DB.
"""

from __future__ import annotations

from services.department_coordinator import DepartmentCoordinator

_drop = DepartmentCoordinator._drop_internal_when_ai_holds_skill


def _cand(score, name, worker_type, skills):
    return (score, name, {"worker_type": worker_type, "skills": {s: {} for s in skills}})


def test_drops_internal_when_an_ai_holds_the_skill():
    cands = [_cand(2.5, "Nexus", "internal", ["analyze"]), _cand(1.8, "W.A.T.C.H.", "ai", ["analyze"])]
    names = {n for _s, n, _i in _drop(cands, "analyze")}
    assert names == {"W.A.T.C.H."}, "internal must be dropped when an AI holds the skill"


def test_keeps_internal_when_no_ai_holder():
    cands = [_cand(2.0, "Sage", "internal", ["community_law"])]
    names = {n for _s, n, _i in _drop(cands, "community_law")}
    assert names == {"Sage"}, "internal-only capability must be untouched"


def test_ai_present_but_lacking_skill_does_not_trigger_drop():
    # An AI director that scored on welfare/director bonuses but does NOT hold the
    # skill must not cause the internal skilled holder to be dropped.
    cands = [_cand(2.0, "Sage", "internal", ["research_synthesis"]), _cand(2.2, "Director", "ai", [])]
    names = {n for _s, n, _i in _drop(cands, "research_synthesis")}
    assert "Sage" in names, "no AI holds the skill → internal stays"


def test_empty_capability_is_noop():
    cands = [_cand(1.0, "X", "internal", [])]
    assert _drop(cands, "") == cands
    assert _drop(cands, None) == cands


def test_retains_ai_and_contractor_drops_only_internal():
    cands = [
        _cand(3.0, "Nexus", "internal", ["x"]),
        _cand(1.0, "AIagent", "ai", ["x"]),
        _cand(0.5, "Contractor", "contract", ["x"]),
    ]
    names = {n for _s, n, _i in _drop(cands, "x")}
    assert names == {"AIagent", "Contractor"}, "only worker_type='internal' is dropped"


def test_never_empties_when_ai_holds_skill():
    cands = [_cand(3.0, "Nexus", "internal", ["x"]), _cand(1.0, "AIagent", "ai", ["x"])]
    out = _drop(cands, "x")
    assert len(out) >= 1, "the AI holder that triggers the drop is always retained"
