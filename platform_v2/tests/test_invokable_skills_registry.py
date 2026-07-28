"""#5291 skill bridge: the invokable-skills registry must be GENERATED, not curated.

Pins the spec's core rule (2026-07-27-tui-skills-sovereign-bridge.md): membership
comes from KNOWN_TOOL_CAPABILITIES + CAPABILITY_DEPARTMENT_MAP at call time — a
capability added to either source appears in the registry with no further edits,
and a hand-maintained parallel list can never drift.
"""

import services.delegation_service as ds
from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP


def _registry(directors=None):
    return ds.build_invokable_skills_registry(directors)


def test_every_known_tool_is_listed_as_known_tool():
    reg = _registry()
    by_cap = {s["capability"]: s for s in reg["skills"]}
    for cap in ds.KNOWN_TOOL_CAPABILITIES:
        assert cap in by_cap, f"known tool {cap} missing from registry"
        assert by_cap[cap]["kind"] == "known_tool"


def test_every_capability_map_entry_is_listed_once():
    reg = _registry()
    caps = [s["capability"] for s in reg["skills"]]
    assert len(caps) == len(set(caps)), "registry contains duplicate capabilities"
    by_cap = {s["capability"]: s for s in reg["skills"]}
    for cap, dept in CAPABILITY_DEPARTMENT_MAP.items():
        assert cap in by_cap, f"capability {cap} missing from registry"
        if cap not in ds.KNOWN_TOOL_CAPABILITIES:
            assert by_cap[cap]["kind"] == "llm"
            assert by_cap[cap]["home_department"] == dept


def test_known_tool_wins_on_collision():
    # Mirrors execute_delegated_task precedence: the shortcut runs, not the LLM.
    overlap = ds.KNOWN_TOOL_CAPABILITIES & set(CAPABILITY_DEPARTMENT_MAP)
    reg = _registry()
    by_cap = {s["capability"]: s for s in reg["skills"]}
    for cap in overlap:
        assert by_cap[cap]["kind"] == "known_tool"


def test_directors_injected_not_queried():
    reg = _registry({"Engineering & Technology": "F.O.R.G.E."})
    eng = [s for s in reg["skills"] if s["home_department"] == "Engineering & Technology"]
    assert eng and all(s["director_agent"] == "F.O.R.G.E." for s in eng)
    # Pure function: no directors injected -> None, never a crash or a DB call.
    reg2 = _registry()
    assert all(s["director_agent"] is None for s in reg2["skills"] if s["kind"] == "llm")


def test_tui_and_cockpit_are_valid_delegation_sources():
    assert {"tui", "cockpit"} <= ds.VALID_DELEGATION_SOURCES
    reg = _registry()
    assert "tui" in reg["delegation_sources"] and "cockpit" in reg["delegation_sources"]


def test_counts_are_honest():
    reg = _registry()
    known = [s for s in reg["skills"] if s["kind"] == "known_tool"]
    llm = [s for s in reg["skills"] if s["kind"] == "llm"]
    assert reg["known_tool_count"] == len(known)
    assert reg["llm_count"] == len(llm)
