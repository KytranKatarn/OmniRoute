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

_DD = "tools.department_hq.services.department_dispatcher"

# ── Get the REAL dispatcher even when another test module has stubbed it (#6017) ──────
# FIVE test modules do, at IMPORT time and permanently:
#     sys.modules["tools.department_hq.services.department_dispatcher"] = _stub_dispatcher
# (test_delegation_service, test_delegation_async_callback, test_delegation_worker_concurrency,
#  test_delegate_late_result_salvage, test_coldload_gpu_routing)
#
# pytest imports every test module during COLLECTION, and those names sort BEFORE this one,
# so a plain importorskip here returned the STUB — which has no DepartmentDispatcher — and
# all 8 tests in this file failed. Alone they pass 8/8, which is exactly what made this look
# like a flaky test rather than a fixture collision. Measured: alone 8 passed; run after
# test_delegation_service.py, 8 failed.
#
# conftest already defends the neighbouring case (#5665) by eagerly importing the real
# PARENT packages, so a synthetic parent cannot win. It does not — and cannot — undo a LEAF
# stub that a module installs at import time.
#
# We pop the stub, import the real module, then PUT THE STUB BACK. The five stubbing modules
# depend on their stub still being in sys.modules when their own tests run, so removing it
# would just move the breakage onto them. Global state ends exactly as we found it; `dd`
# holds a direct reference to the real module.
# ⚠️ BOTH bindings must be restored, not just sys.modules. Importing the real module also
# rebinds the PARENT PACKAGE ATTRIBUTE (`tools.department_hq.services.department_dispatcher`),
# and `from tools.department_hq.services import department_dispatcher` reads THAT, not
# sys.modules. Restoring only sys.modules regressed 6 tests in test_dhq_chat_routing,
# test_coo_consult and test_mail_hq — they silently got the real dispatcher instead of their
# stub. Same trap as #5987 (see tests/modstub.py).
import importlib as _importlib

_DD_PARENT, _DD_LEAF = _DD.rsplit(".", 1)
_saved_dd = sys.modules.pop(_DD, None)
_parent_mod = sys.modules.get(_DD_PARENT)
_saved_attr = getattr(_parent_mod, _DD_LEAF, None) if _parent_mod is not None else None
try:
    dd = pytest.importorskip(
        _DD,
        reason="dispatcher import chain unavailable outside the app environment",
    )
finally:
    if _saved_dd is not None:
        sys.modules[_DD] = _saved_dd  # restore the other modules' stub, untouched
    if _saved_attr is not None and _parent_mod is not None:
        setattr(_parent_mod, _DD_LEAF, _saved_attr)


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


def test_dd_is_the_REAL_dispatcher_not_another_module_s_stub():
    """Guard for #6017.

    Five test modules install a permanent stub at
    `sys.modules["tools.department_hq.services.department_dispatcher"]` during collection.
    If the pop/restore above regresses, `dd` silently becomes that stub and all 8 tests in
    this file fail together — which reads as a flaky suite, because they pass 8/8 alone.

    Asserting on the SYMBOL rather than the module identity: what this file actually needs
    is the real `_rank_fleet_candidates`, and a stub that grew one would be fine.
    """
    assert hasattr(dd, "DepartmentDispatcher"), (
        "dd is a stub, not the real dispatcher — another test module's "
        "sys.modules assignment won; see the pop/restore at the top of this file"
    )
    assert hasattr(dd.DepartmentDispatcher, "_rank_fleet_candidates")


def test_the_other_modules_stub_is_left_intact():
    """The pop/restore must not become a fix that breaks its neighbours.

    Five modules depend on their stub STILL being in sys.modules when their own tests run.
    If a stub was present at import time, we must have put it back exactly.
    """
    if _saved_dd is None:
        pytest.skip("no stub was installed — this file was collected first")
    assert sys.modules.get(_DD) is _saved_dd, (
        "the stub another module installed was not restored — removing it moves the "
        "breakage onto test_delegation_service and friends instead of fixing it"
    )
    parent = sys.modules.get(_DD_PARENT)
    if _saved_attr is not None and parent is not None:
        assert getattr(parent, _DD_LEAF, None) is _saved_attr, (
            "the PARENT PACKAGE ATTRIBUTE was not restored — "
            "`from ...services import department_dispatcher` reads this, not sys.modules, "
            "so leaving the real module bound here silently breaks 6 other tests (#5987)"
        )
