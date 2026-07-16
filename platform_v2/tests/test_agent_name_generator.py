"""Unit tests for agent_name_generator (sovereign acronym name generator).

All DB + dispatch access goes through two seams (_existing_names,
_dispatch_name) which we patch — no real DB or dispatcher needed.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from services import agent_name_generator as ang  # noqa: E402


def test_normalize_strips_dots_and_uppercases():
    assert ang._normalize("v.e.r.i.f.y.") == "VERIFY"
    assert ang._normalize("F.O.R.G.E.") == "FORGE"


def test_dotify_formats_letters():
    assert ang._dotify("FORGE") == "F.O.R.G.E."
    assert ang._dotify("") == ""


def test_valid_letters_bounds():
    assert ang._valid_letters("FORGE")  # 5
    assert ang._valid_letters("QUILL")  # 5
    assert not ang._valid_letters("ABC")  # 3 too short
    assert not ang._valid_letters("ABCDEFGH")  # 8 too long


def test_suggest_name_accepts_valid_unique_llm_name():
    with patch.object(ang, "_existing_names", return_value={"FORGE", "VIGIL"}), patch.object(
        ang,
        "_dispatch_name",
        return_value={"name": "V.E.R.I.F.Y.", "expansion": "Validation Engine ...", "title": "Fact Checker"},
    ):
        out = ang.suggest_name("fact_check")
    assert out["name"] == "V.E.R.I.F.Y."
    assert out["source"] == "llm"
    assert out["expansion"] and out["title"]


def test_suggest_name_rejects_duplicate_then_retries():
    # First dispatch returns an existing name; second returns a fresh one.
    calls = [
        {"name": "FORGE", "expansion": "x", "title": "y"},  # dup -> rejected
        {"name": "S.C.R.I.B.E.", "expansion": "Scribe", "title": "Writer"},
    ]
    with patch.object(ang, "_existing_names", return_value={"FORGE"}), patch.object(
        ang, "_dispatch_name", side_effect=calls
    ):
        out = ang.suggest_name("documentation")
    assert out["name"] == "S.C.R.I.B.E."
    assert out["source"] == "llm"


def test_suggest_name_rejects_malformed_and_falls_back():
    # Every dispatch is malformed/too-short -> deterministic fallback.
    with patch.object(ang, "_existing_names", return_value=set()), patch.object(
        ang, "_dispatch_name", return_value={"name": "AB", "expansion": "", "title": ""}
    ):
        out = ang.suggest_name("security_audit", max_attempts=2)
    assert out["source"] == "fallback"
    assert ang._valid_letters(out["name"])
    assert out["name"].endswith(".")


def test_fallback_is_unique_against_avoid_set():
    with patch.object(ang, "_existing_names", return_value=set()), patch.object(
        ang, "_dispatch_name", return_value=None
    ):
        out = ang.suggest_name("support", avoid_names={"SUPRT", "SUPRTX"}, max_attempts=1)
    assert out["source"] == "fallback"
    assert ang._normalize(out["name"]) not in {"SUPRT", "SUPRTX"}


def test_dispatch_exception_does_not_raise():
    with patch.object(ang, "_existing_names", return_value=set()), patch.object(
        ang, "_dispatch_name", side_effect=RuntimeError("cold load")
    ):
        out = ang.suggest_name("general", max_attempts=1)
    assert out["source"] == "fallback"
    assert ang._valid_letters(out["name"])


def test_parse_json_plain():
    assert ang._parse_json('{"name": "V.E.R.I.F.Y.", "expansion": "x", "title": "y"}') == {
        "name": "V.E.R.I.F.Y.",
        "expansion": "x",
        "title": "y",
    }


def test_parse_json_fenced():
    fenced = '```json\n{"name": "F.O.R.G.E."}\n```'
    assert ang._parse_json(fenced) == {"name": "F.O.R.G.E."}


def test_parse_json_with_prose():
    msg = 'Sure! Here you go:\n{"name": "S.C.R.I.B.E.", "title": "Writer"}\nHope that helps.'
    assert ang._parse_json(msg) == {"name": "S.C.R.I.B.E.", "title": "Writer"}


def test_parse_json_garbage_returns_none():
    assert ang._parse_json("no json here") is None
    assert ang._parse_json("") is None
    assert ang._parse_json("[1, 2, 3]") is None  # not an object
