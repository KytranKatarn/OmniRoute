"""Tests for agent_identity_builder.enrich_identity — Phase 2 backfill core.

Enrich = preserve every non-empty existing field, fill only the gaps from a
freshly built candidate, ALWAYS rebuild the system prompt from the merged
fields (>=400 chars). Protects a live agent's established persona.
"""

from unittest.mock import patch

from services import agent_identity_builder as aib

_CANDIDATE = {
    "name": "PLACEHOLDER",
    "expansion": "Candidate Expansion Words Here",
    "title": "Candidate Title",
    "bio": "Candidate bio sentence one. Sentence two.",
    "personality": "candidate personality traits",
    "system_prompt": "C" * 500,
    "portrait_prompt": "candidate sci-fi portrait",
    "source": "llm",
}


def _mock_build(capability, department=None, *, existing_name=None, **k):
    return dict(_CANDIDATE, name=existing_name or _CANDIDATE["name"])


def test_enrich_preserves_existing_and_fills_gaps():
    current = {
        "name": "P.R.O.B.E.",
        "expansion": "Existing Expansion",
        "title": "Existing Title",
        "bio": "Existing bio.",
        "personality": "",
        "portrait_prompt": "",
        "has_portrait": True,
    }
    with patch.object(aib, "build_identity", _mock_build):
        out = aib.enrich_identity(current, "code", "Engineering & Technology")
    a = out["after"]
    assert a["expansion"] == "Existing Expansion"  # preserved
    assert a["title"] == "Existing Title"  # preserved
    assert a["bio"] == "Existing bio."  # preserved
    assert a["personality"] == "candidate personality traits"  # filled from candidate
    assert a["portrait_prompt"] == "candidate sci-fi portrait"  # filled
    assert len(a["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS
    assert "P.R.O.B.E." in a["system_prompt"]
    assert "Existing Expansion" in a["system_prompt"]  # preserved expansion woven in
    assert out["portrait_needed"] is False  # already has a portrait


def test_enrich_broken_agent_fully_filled():
    current = {
        "name": "V.E.T.",
        "expansion": "Verify Evidence Truthfully",
        "title": "",
        "bio": "",
        "personality": "",
        "portrait_prompt": "",
        "has_portrait": False,
    }
    with patch.object(aib, "build_identity", _mock_build):
        out = aib.enrich_identity(current, "fact_check", "News & Media")
    a = out["after"]
    assert a["expansion"] == "Verify Evidence Truthfully"  # kept (non-empty)
    assert a["title"] and a["bio"] and a["personality"]  # all filled
    assert len(a["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS
    assert out["portrait_needed"] is True  # no portrait + a prompt now exists
    assert "bio" in out["changed"] and "personality" in out["changed"]


def test_enrich_changed_lists_only_real_diffs():
    current = {
        "name": "X.Y.Z.Q.",
        "expansion": "Existing Expansion",
        "title": "Existing Title",
        "bio": "Existing bio.",
        "personality": "existing pers",
        "portrait_prompt": "existing portrait",
        "has_portrait": True,
    }
    with patch.object(aib, "build_identity", _mock_build):
        out = aib.enrich_identity(current, "general", "Engineering & Technology")
    # every content field preserved; only the (absent) system prompt is (re)built
    assert out["changed"] == ["system_prompt"]
    assert out["portrait_needed"] is False


def test_apply_backfill_maps_fields_and_queues_portrait(monkeypatch):
    from services import agent_backfill, agent_service

    calls = {}
    monkeypatch.setattr(agent_service, "update_agent", lambda aid, **f: calls.setdefault("update", (aid, f)))
    monkeypatch.setattr(agent_service, "add_portrait", lambda aid, p, **k: calls.setdefault("portrait", (aid, p)))
    after = {
        "system_prompt": "S" * 500,
        "expansion": "E",
        "title": "T",
        "bio": "B",
        "personality": "P",
        "portrait_prompt": "PP",
    }
    agent_backfill.apply_backfill(42, after, portrait_needed=True)
    aid, f = calls["update"]
    assert aid == 42
    assert f["system_prompt"] == "S" * 500 and f["bio"] == "B"
    assert f["personality_prompt"] == "P"  # personality -> personality_prompt column
    assert f["acronym_expansion"] == "E" and f["title"] == "T" and f["portrait_prompt"] == "PP"
    assert calls["portrait"] == (42, "PP")


def test_apply_backfill_skips_portrait_when_not_needed(monkeypatch):
    from services import agent_backfill, agent_service

    calls = {}
    monkeypatch.setattr(agent_service, "update_agent", lambda aid, **f: None)
    monkeypatch.setattr(agent_service, "add_portrait", lambda *a, **k: calls.setdefault("portrait", True))
    after = {
        "system_prompt": "S" * 500,
        "expansion": "",
        "title": "",
        "bio": "",
        "personality": "",
        "portrait_prompt": "PP",
    }
    agent_backfill.apply_backfill(42, after, portrait_needed=False)
    assert "portrait" not in calls  # gated off
