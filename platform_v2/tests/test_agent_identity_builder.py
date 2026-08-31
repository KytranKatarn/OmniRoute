import re
from unittest.mock import patch
from services import agent_identity_builder as aib


def _fake_parts(name="V.E.R.I.F.Y."):
    return {
        "name": name,
        "expansion": "Validation Engine Reviewing Information For Yield",
        "title": "Fact Checker",
        "bio": "Two sentence backstory. Second sentence.",
        "personality": "Skeptical, rigorous, calm.",
        "voice": "precise and neutral",
        "portrait_hint": "a vigilant analyst with a data visor",
    }


def test_build_identity_llm_full_package():
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts()), patch.object(
        aib, "_existing_names", return_value=set()
    ):
        out = aib.build_identity("fact_check", department="News & Media")
    assert out["source"] == "llm"
    assert out["name"] == "V.E.R.I.F.Y."
    assert out["expansion"]
    assert out["title"]
    assert out["bio"]
    assert len(out["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS
    assert "Validation Engine" in out["system_prompt"]  # expansion woven in
    assert out["portrait_prompt"]


def test_build_identity_fallback_is_still_complete():
    # dispatch times out -> deterministic fallback, STILL a full identity
    with patch.object(aib, "_dispatch_identity", return_value=None), patch.object(
        aib, "_existing_names", return_value=set()
    ):
        out = aib.build_identity("classify", department="Analytics & Intelligence")
    assert out["source"] == "fallback"
    assert re.match(r"^([A-Z]\.){4,7}$", out["name"])
    assert len(out["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS
    assert out["portrait_prompt"]


def test_build_identity_existing_name_is_kept():
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts(name="X.X.X.")), patch.object(
        aib, "_existing_names", return_value={"FORGE"}
    ):
        out = aib.build_identity("code", department="Engineering & Technology", existing_name="P.R.O.B.E.")
    assert out["name"] == "P.R.O.B.E."  # kept, not the LLM's name
    assert len(out["system_prompt"]) >= aib.MIN_SYSTEM_PROMPT_CHARS


def test_build_identity_dedupes_against_existing():
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts(name="F.O.R.G.E.")), patch.object(
        aib, "_existing_names", return_value={"FORGE"}
    ):
        out = aib.build_identity("code", department="Engineering & Technology", max_attempts=1)
    # collided name rejected -> falls back to a unique deterministic name
    assert out["name"] != "F.O.R.G.E."


def test_build_identity_normalizes_avoid_names():
    # caller-supplied avoid_names uses the dotted agents.name format (e.g. "F.O.R.G.E.")
    # rather than the normalized letters-only form -- it must still be normalized so
    # the collision check (`letters not in avoid`) catches it.
    with patch.object(aib, "_dispatch_identity", return_value=_fake_parts(name="F.O.R.G.E.")), patch.object(
        aib, "_existing_names", return_value=set()
    ):
        out = aib.build_identity(
            "code",
            department="Engineering & Technology",
            avoid_names={"F.O.R.G.E."},
            max_attempts=1,
        )
    # dotted avoid entry was normalized + deduped -> collision rejected, falls back
    assert out["name"] != "F.O.R.G.E."


# ── #6237: the model answers with an ARRAY, not a string ─────────────────────
# The prompt asks for `"expansion":"..."`, but a local model regularly returns a
# JSON array of the per-letter words. The old code did str(value), which writes the
# PYTHON REPR to the DB — 17 live agents carried exactly that, and the roster card
# renders acronym_expansion verbatim, so users saw "['Architect', 'Engine', 'Lead']".


def test_coerce_expansion_flattens_a_list_instead_of_writing_its_repr():
    from services.agent_identity_builder import _coerce_expansion

    out = _coerce_expansion(["Architect", "Engine", "Lead"])
    assert out == "Architect · Engine · Lead"
    # The whole point: never the repr. `str(["Architect", ...])` starts with "[".
    assert not out.startswith("[")


def test_coerce_expansion_strips_split_artifacts():
    """Real observed value: ['Integrator', 'Agent', ' Bridge'] — the leading space
    on ' Bridge' is an upstream split(',') with no strip."""
    from services.agent_identity_builder import _coerce_expansion

    assert _coerce_expansion(["Integrator", "Agent", " Bridge"]) == "Integrator · Agent · Bridge"


def test_coerce_expansion_leaves_a_plain_string_untouched():
    from services.agent_identity_builder import _coerce_expansion

    assert _coerce_expansion("Process Operations Router") == "Process Operations Router"
    assert _coerce_expansion(None) == ""
    assert _coerce_expansion({"A": "Architect", "E": "Engine"}) == "Architect · Engine"


def test_the_old_str_coercion_would_fail_this_test():
    """Proof the test catches the ACTUAL defect rather than passing vacuously —
    reproduce the old one-liner and confirm it produces the broken value."""
    old = str(["Architect", "Engine", "Lead"] or "").strip()
    assert old == "['Architect', 'Engine', 'Lead']"
    assert old.startswith("[")
