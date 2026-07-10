"""Tests that the legacy background loops route through the AI capability-owner
(a budgeted worker_type='ai' agent) instead of a legacy INTERNAL persona, so their
inference is honestly attributed + visible to the K.I.N./welfare accounting.

Pure constant checks (no DB) for the routing tables; the end-to-end dispatch
attribution is live-verified separately.
"""

from __future__ import annotations

from services.department_coordinator import CAPABILITY_SPECIALIST_MAP
from tools.consciousness.translation_scanners.generator import (
    _DEFAULT_ROUTING,
    _LANG_ROUTING,
)


def test_translate_pins_route_to_ai_owner_not_internal_persona():
    # ar/he/de must route to the AI translate owner R.O.S.E.T.T.A., never the internal
    # persona 'Amina' — while keeping gemma3:12b (model decoupled from agent).
    for lang in ("ar", "he", "de"):
        model, agent = _LANG_ROUTING[lang]
        assert agent == "R.O.S.E.T.T.A.", f"{lang} routed to {agent}, expected R.O.S.E.T.T.A."
        assert model == "gemma3:12b", f"{lang} lost its quality model: {model}"
    assert _DEFAULT_ROUTING[1] == "R.O.S.E.T.T.A."


def test_no_internal_persona_remains_in_translate_routing():
    agents = {agent for _model, agent in _LANG_ROUTING.values()} | {_DEFAULT_ROUTING[1]}
    assert "Amina" not in agents, "translate must not route to the internal persona Amina"


def test_specialist_map_pins_capabilities_to_ai_owners():
    # These pins are what make knowledge_analysis / research_synthesis prefer the AI
    # owner over the legacy internal skill-holders (Nexus/Oracle, Sage).
    assert CAPABILITY_SPECIALIST_MAP["translate"] == "R.O.S.E.T.T.A."
    assert CAPABILITY_SPECIALIST_MAP["knowledge_analysis"] == "S.P.E.C.T.R.A."
    assert CAPABILITY_SPECIALIST_MAP["research_synthesis"] == "D.A.R.W.I.N."


def test_specialist_targets_are_acronym_ai_agents():
    # Every specialist target is an A.C.R.O.N.Y.M.-style AI agent name (dotted caps),
    # never a human-named internal persona (Amina/Nexus/Oracle/Sage).
    internal_personas = {"Amina", "Nexus", "Oracle", "Sage"}
    for cap, owner in CAPABILITY_SPECIALIST_MAP.items():
        assert owner not in internal_personas, f"{cap} pinned to internal persona {owner}"
