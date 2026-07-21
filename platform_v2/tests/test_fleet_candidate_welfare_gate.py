"""Fleet-tier selection must obey the same welfare/skill predicate as every other tier.

Regression cover for #5028b.

`_find_fleet_agent()` selected on `department` + node health ALONE. Its SQL has no
welfare join, and `capability` was accepted as a parameter but never referenced in the
query. So the fleet escalation tier bypassed every hard block `score_agent` enforces:
an agent with an OPEN REST CYCLE stayed selectable, and because the ORDER BY is node
`bridge_priority DESC`, the department's first-listed agent won every time.

Observed live: for 'Engineering & Technology' the query returns F.O.R.G.E. first and
P.R.O.B.E. second, both on the priority-100 node — so P.R.O.B.E. was structurally
unreachable regardless of its state, and F.O.R.G.E. was dispatched while resting.

That is also why hiring a standby would not have helped: a new agent sorts behind the
incumbent on this path and is never reached.
"""

import sys
from pathlib import Path

import pytest

_PV2 = Path(__file__).resolve().parents[1]
# ai_bridge is only on sys.path via app.py at boot; the dispatcher's import chain does
# `from db import ...`, so a non-app-boot process needs it explicitly (KB #272154).
for _p in (str(_PV2), str(_PV2.parent / "ai_bridge")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

dd = pytest.importorskip(
    "tools.department_hq.services.department_dispatcher",
    reason="dispatcher import chain unavailable outside the app environment",
)


class _FakeCoordinator:
    """Stands in for the real coordinator; records what it was asked."""

    def __init__(self, scores):
        self.scores = scores  # {agent_name: (score, block_reason)}
        self.seen = []

    def score_agent(self, name, info, capability, department, recommended_tier=None):
        self.seen.append((name, capability, department))
        return self.scores.get(name, (1.0, None))


def _candidate(name, node, priority):
    return {"agent_name": name, "node_name": node, "bridge_priority": priority, "model": "qwen2.5:7b"}


@pytest.fixture()
def rank(monkeypatch):
    """Returns a callable that ranks candidates against a supplied cache + scores."""

    def _run(candidates, scores, cache=None, cache_raises=False):
        import services.agent_service as agent_service

        if cache is None:
            cache = {c["agent_name"]: {"id": i, "status": "active"} for i, c in enumerate(candidates)}

        if cache_raises:

            def _boom():
                raise RuntimeError("agent cache unavailable")

            monkeypatch.setattr(agent_service, "get_agent_cache", _boom)
        else:
            monkeypatch.setattr(agent_service, "get_agent_cache", lambda: cache)

        coord = _FakeCoordinator(scores)
        monkeypatch.setattr(dd, "get_dept_coordinator", lambda: coord)

        # The method never touches instance state.
        out = dd.DepartmentDispatcher._rank_fleet_candidates(object(), candidates, "Engineering & Technology", "code")
        return out, coord

    return _run


class TestFleetWelfareGate:
    def test_resting_incumbent_is_dropped_and_rested_peer_wins(self, rank):
        """THE bug: F.O.R.G.E. resting on the priority-100 node must not be selected."""
        candidates = [
            _candidate("F.O.R.G.E.", "Archie Starbase", 100),
            _candidate("P.R.O.B.E.", "Archie Starbase", 100),
        ]
        scores = {
            "F.O.R.G.E.": (0.0, "F.O.R.G.E. is in active rest cycle (micro_rest) — K.I.N. enforced"),
            "P.R.O.B.E.": (2.4, None),
        }
        out, _ = rank(candidates, scores)

        assert [c["agent_name"] for c in out] == ["P.R.O.B.E."]

    def test_all_blocked_yields_empty_so_caller_returns_none(self, rank):
        candidates = [
            _candidate("F.O.R.G.E.", "Archie Starbase", 100),
            _candidate("P.R.O.B.E.", "Archie Starbase", 100),
        ]
        scores = {"F.O.R.G.E.": (0.0, "resting"), "P.R.O.B.E.": (0.0, "task queue limit")}

        out, _ = rank(candidates, scores)

        assert out == []

    def test_higher_score_outranks_node_priority(self, rank):
        """Skill/welfare score decides; node priority is only the tiebreak."""
        candidates = [
            _candidate("F.O.R.G.E.", "Archie Starbase", 100),
            _candidate("P.R.O.B.E.", "Starship - Defiant - USS-246", 50),
        ]
        scores = {"F.O.R.G.E.": (1.0, None), "P.R.O.B.E.": (3.0, None)}

        out, _ = rank(candidates, scores)

        assert [c["agent_name"] for c in out] == ["P.R.O.B.E.", "F.O.R.G.E."]

    def test_equal_scores_preserve_original_node_ordering(self, rank):
        candidates = [
            _candidate("F.O.R.G.E.", "Archie Starbase", 100),
            _candidate("P.R.O.B.E.", "Starship - Defiant - USS-246", 50),
        ]
        scores = {"F.O.R.G.E.": (2.0, None), "P.R.O.B.E.": (2.0, None)}

        out, _ = rank(candidates, scores)

        assert [c["agent_name"] for c in out] == ["F.O.R.G.E.", "P.R.O.B.E."]

    def test_capability_is_actually_passed_to_the_scorer(self, rank):
        """It used to be accepted and silently ignored — that was half the bug."""
        candidates = [_candidate("F.O.R.G.E.", "Archie Starbase", 100)]

        _, coord = rank(candidates, {"F.O.R.G.E.": (1.5, None)})

        assert coord.seen == [("F.O.R.G.E.", "code", "Engineering & Technology")]

    def test_candidate_absent_from_cache_is_dropped(self, rank):
        candidates = [
            _candidate("F.O.R.G.E.", "Archie Starbase", 100),
            _candidate("GHOST", "Archie Starbase", 100),
        ]
        cache = {"F.O.R.G.E.": {"id": 1, "status": "active"}}

        out, _ = rank(candidates, {"F.O.R.G.E.": (1.5, None)}, cache=cache)

        assert [c["agent_name"] for c in out] == ["F.O.R.G.E."]

    def test_fails_open_when_the_cache_is_unavailable(self, rank):
        """An environment failure is not a verdict (ADR-016) — don't starve the tier."""
        candidates = [
            _candidate("F.O.R.G.E.", "Archie Starbase", 100),
            _candidate("P.R.O.B.E.", "Archie Starbase", 100),
        ]

        out, _ = rank(candidates, {}, cache_raises=True)

        assert [c["agent_name"] for c in out] == ["F.O.R.G.E.", "P.R.O.B.E."]

    def test_empty_cache_fails_open_rather_than_blocking_everything(self, rank):
        candidates = [_candidate("F.O.R.G.E.", "Archie Starbase", 100)]

        out, _ = rank(candidates, {}, cache={})

        assert [c["agent_name"] for c in out] == ["F.O.R.G.E."]
