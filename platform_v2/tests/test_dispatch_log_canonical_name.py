"""task_execution_log.agent_name must be the agent's CANONICAL name (#6238).

`agent_name` is joined as a STRING across the platform (A.R.M.A.D.A. breakdowns,
/activity, roster run-counts). Different dispatch paths wrote different fields for
the same agent — `_find_fleet_agent` selects
`COALESCE(na.display_name, a_hub.display_name, na.name)` while the hub path writes
`name` — so one agent's history split across two strings.

Measured on live data 2026-08-31, 10,266 rows were filed under a display_name:

    S.I.F.T.      630 as 'S.I.F.T.'  vs  9,752 as 'Sift — Beat Classification Specialist'
    T.R.I.A.G.E.  12,672             vs    116 as 'Classify Specialist'
    T.A.L.O.N.    7,327              vs    369 as 'Fact Check Specialist'
    H.A.V.E.N.    3                  vs     25 as 'Welfare Specialist'
    A.T.L.A.S.    1                  vs      4 as 'Model Ops Specialist'

These tests use a STUB cache — no DB, no fixtures — so they run even while the
conftest admin-seed is broken on archie_test.
"""

import sys
import types

import pytest


@pytest.fixture
def resolve(monkeypatch):
    """_canonical_agent_name bound to a stub agent cache."""
    from tools.department_hq.services import department_dispatcher as dd

    fake = types.ModuleType("services.agent_service")
    fake.get_agent_cache = lambda: {
        "S.I.F.T.": {"id": 432, "name": "S.I.F.T."},
        "T.R.I.A.G.E.": {"id": 416, "name": "T.R.I.A.G.E."},
        "A.R.C.H.I.E.": {"id": 2, "name": "A.R.C.H.I.E."},
    }
    # the helper imports lazily inside the function, so patch the module entry
    monkeypatch.setitem(sys.modules, "services.agent_service", fake)
    dd._CANON_NAME_BY_ID.clear()
    dd._CANON_NAME_REFRESHED[0] = 0.0
    return dd.BridgeDispatcher.__dict__["_canonical_agent_name"].__get__(
        object.__new__(dd.BridgeDispatcher), dd.BridgeDispatcher
    )


def test_a_display_name_is_rewritten_to_the_canonical_name(resolve):
    """The actual defect: the fleet path handed us a display_name."""
    assert resolve(432, "Sift — Beat Classification Specialist") == "S.I.F.T."
    assert resolve(416, "Classify Specialist") == "T.R.I.A.G.E."


def test_an_already_canonical_name_is_unchanged(resolve):
    assert resolve(432, "S.I.F.T.") == "S.I.F.T."


def test_warmup_and_other_unattributed_markers_are_never_rewritten(resolve):
    """agent_id is NULL on purpose for infrastructure warm-up — the name is a note
    of which MODEL was warmed. Inventing an owner here would corrupt the very
    accounting this fix exists to protect."""
    assert resolve(None, "warmup:qwen2.5:7b") == "warmup:qwen2.5:7b"
    assert resolve(None, "CONTRACTOR→claude") == "CONTRACTOR→claude"
    assert resolve(0, "CLOUD→gpt") == "CLOUD→gpt"


def test_a_composed_escalation_label_is_left_intact(resolve):
    """'<director> →<contractor>' is deliberately synthetic (C.R.E.E.D. accounting
    Fix #3) — it is not an agent name and must survive verbatim."""
    assert resolve(2, "A.R.C.H.I.E. →CLOUD:gpt-4") == "A.R.C.H.I.E. →CLOUD:gpt-4"


def test_an_unresolvable_id_fails_OPEN(resolve):
    """A wrong-but-present name beats losing the row's only identifier."""
    assert resolve(99999, "Some Unknown Agent") == "Some Unknown Agent"
    assert resolve(99999, None) is None


def test_a_broken_cache_never_raises_into_the_dispatch_path(monkeypatch):
    """_log_execution runs on every dispatch; this helper must never be the thing
    that breaks one."""
    from tools.department_hq.services import department_dispatcher as dd

    boom = types.ModuleType("services.agent_service")

    def _raise():
        raise RuntimeError("cache exploded")

    boom.get_agent_cache = _raise
    monkeypatch.setitem(sys.modules, "services.agent_service", boom)
    dd._CANON_NAME_BY_ID.clear()
    dd._CANON_NAME_REFRESHED[0] = 0.0
    fn = dd.BridgeDispatcher.__dict__["_canonical_agent_name"].__get__(
        object.__new__(dd.BridgeDispatcher), dd.BridgeDispatcher
    )
    assert fn(432, "Sift — Beat Classification Specialist") == "Sift — Beat Classification Specialist"


def test_an_empty_cache_read_does_not_blank_a_populated_index(monkeypatch):
    """A momentarily empty cache must not wipe good mappings — otherwise a single
    bad read degrades every subsequent log row until the next refresh."""
    from tools.department_hq.services import department_dispatcher as dd

    good = types.ModuleType("services.agent_service")
    good.get_agent_cache = lambda: {"S.I.F.T.": {"id": 432, "name": "S.I.F.T."}}
    monkeypatch.setitem(sys.modules, "services.agent_service", good)
    dd._CANON_NAME_BY_ID.clear()
    dd._CANON_NAME_REFRESHED[0] = 0.0
    fn = dd.BridgeDispatcher.__dict__["_canonical_agent_name"].__get__(
        object.__new__(dd.BridgeDispatcher), dd.BridgeDispatcher
    )
    assert fn(432, "x") == "S.I.F.T."

    empty = types.ModuleType("services.agent_service")
    empty.get_agent_cache = lambda: {}
    monkeypatch.setitem(sys.modules, "services.agent_service", empty)
    dd._CANON_NAME_REFRESHED[0] = 0.0  # force a refresh attempt
    assert fn(432, "x") == "S.I.F.T."  # retained, not blanked
