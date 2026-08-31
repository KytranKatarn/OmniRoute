"""Unit tests for agent_name_generator (sovereign acronym name generator).

All DB + dispatch access goes through two seams (_existing_names,
_dispatch_name) which we patch — no real DB or dispatcher needed.
"""

from __future__ import annotations

import random
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


# --- Task #4960: pronounceability + curated fallback pool -------------------


def test_valid_letters_rejects_unpronounceable_blobs():
    assert not ang._valid_letters("BCDFG")  # no vowel + 5-consonant run
    assert not ang._valid_letters("AB")  # too short
    assert ang._valid_letters("FORGE")
    assert ang._valid_letters("BEACON")


def test_fallback_name_uses_curated_pool_not_padding():
    # "image_ai" -> initials "IA" (too short) used to pad to "IAAG" via the old
    # AGENTCOREUNIT blob (task #4960). It must now fall to the curated pool.
    out = ang._fallback_name("image_ai", set())
    assert out["source"] == "fallback"
    letters = ang._normalize(out["name"])
    assert letters != "IAAG"
    assert "AGENTCOREUNIT" not in letters
    assert letters in {acronym for acronym, _ in ang._FALLBACK_POOL}
    # the expansion's word-initials must spell the returned acronym exactly
    initials = "".join(word[0] for word in out["expansion"].split())
    assert initials == letters


def test_fallback_name_respects_avoid_never_returns_avoided_entries():
    # Task #4969: the pool pick is now RANDOMIZED (no longer "first unused"),
    # so we can't assert a specific next entry — but every avoided acronym
    # must never come back, across many draws.
    first_acronym = ang._FALLBACK_POOL[0][0]
    second_acronym = ang._FALLBACK_POOL[1][0]
    avoided = {first_acronym, second_acronym}
    random.seed(4242)
    for _ in range(15):
        out = ang._fallback_name("image_ai", set(avoided))
        assert ang._normalize(out["name"]) not in avoided


def test_fallback_name_randomizes_across_repeated_calls():
    # Task #4969: same capability + empty avoid must no longer always return
    # the same pool entry (the old bug: always "PORTAL"). Initials for
    # "security_audit" ("SA") are too short -> always falls to the pool.
    random.seed(1234)
    names = {ang._normalize(ang._fallback_name("security_audit", set())["name"]) for _ in range(15)}
    assert len(names) >= 3
    for letters in names:
        assert ang._valid_letters(letters)


def test_fallback_name_randomization_respects_avoid_set():
    avoid = {ang._FALLBACK_POOL[0][0], ang._FALLBACK_POOL[1][0]}
    random.seed(2026)
    names = set()
    for _ in range(15):
        out = ang._fallback_name("security_audit", set(avoid))
        letters = ang._normalize(out["name"])
        assert ang._valid_letters(letters)
        assert letters not in avoid
        names.add(letters)
    assert len(names) >= 3


def test_fallback_name_initials_branch_still_wins_when_valid():
    # The capability's own word-initials branch must still take priority over
    # the (now randomized) curated pool whenever it yields a valid acronym.
    out = ang._fallback_name("vivid_echo_matrix_engine", set())
    assert out["source"] == "fallback"
    assert ang._normalize(out["name"]) == "VEME"
    assert out["expansion"] == "Vivid Echo Matrix Engine"


def test_department_for_capability_analyze_maps_to_analytics():
    # Task #4969 root cause: the old import path
    # (tools.department_hq.services.department_coordinator) does not exist,
    # so every hire silently defaulted to Engineering & Technology. The
    # correct module is services.department_coordinator.
    assert ang._department_for_capability("analyze") == "Analytics & Intelligence"


def test_department_for_capability_unknown_falls_back_to_engineering():
    assert ang._department_for_capability("__not_a_real_capability__") == "Engineering & Technology"


def test_fallback_pool_expansions_spell_their_acronyms():
    # Every curated pool entry must be internally consistent + pronounceable +
    # unique, or the fallback could silently regress to gibberish again.
    seen = set()
    for acronym, expansion in ang._FALLBACK_POOL:
        assert ang._valid_letters(acronym), f"{acronym} fails _valid_letters"
        initials = "".join(word[0] for word in expansion.split())
        assert initials == acronym, f"{acronym}: {expansion!r} spells {initials!r}"
        assert acronym.isascii(), f"{acronym} is not all-ASCII"
        assert acronym not in seen, f"{acronym} duplicated in _FALLBACK_POOL"
        seen.add(acronym)


# ── #6237: the P.O.R.T.A.L. family ───────────────────────────────────────────
# On 2026-08-04 a ~40-agent batch exhausted the 30-entry _FALLBACK_POOL and the
# last-resort suffix loop emitted P.O.R.T.A.L., P.O.R.T.A.L.A. ... P.O.R.T.A.L.Y.
# — ten unrelated specialists sharing one name stem AND one expansion. The suffix
# order in that loop is "AEIOUYBCD...", which is exactly the sequence found in the
# roster. Root cause: _valid_letters requires 4-7 letters, so a TWO-WORD capability
# ("edge_computing" -> initials "EC") could never use the meaningful branch and
# went straight to a generic pool slot.


def _pool_exhausted():
    """The Aug-4 condition: every curated pool entry already taken."""
    from services.agent_name_generator import _FALLBACK_POOL, _normalize

    return {_normalize(a) for a, _ in _FALLBACK_POOL}


def _suffix_clones(names):
    """Names that are another name plus appended letters — the ACTUAL defect.

    P.O.R.T.A.L. on its own is a legitimate curated pool entry. What was wrong on
    2026-08-04 was the FAMILY: P.O.R.T.A.L.A. / .B. / .C. ... ten unrelated jobs
    wearing one stem. An earlier version of this test asserted
    `not name.startswith("P.O.R.T.A.L")`, which also forbids the valid base name —
    it encoded the symptom instead of the property, and failed on correct output.
    """
    from services.agent_name_generator import _normalize

    keys = {_normalize(n) for n in names}
    return {k for k in keys if any(other != k and k.startswith(other) for other in keys)}


def test_exhausted_pool_falls_back_to_the_capability_not_a_suffixed_stem():
    """With the pool drained, each capability must yield a name derived from its
    OWN words rather than a pool entry with a letter stapled on."""
    from services.agent_name_generator import _fallback_name, _normalize, _valid_letters

    caps = [
        "edge_computing",
        "container_orchestration",
        "distributed_systems",
        "failure_analysis",
        "deployment_automation",
    ]
    avoid = _pool_exhausted()
    names = []
    for cap in caps:
        got = _fallback_name(cap, set(avoid))
        assert _valid_letters(_normalize(got["name"])), f"{cap} -> invalid {got['name']}"
        names.append(got["name"])
    assert not _suffix_clones(names), f"suffixed clone family returned: {_suffix_clones(names)}"


def test_expansion_initials_always_spell_the_name():
    """House contract (#4960): the expansion's word-initials spell the acronym.
    A capability-derived name must honour it too — 'Edge Computing' for E.D.G.E.
    spells EC, which is why build_backronym composes per letter."""
    from services.agent_name_generator import _fallback_name, _normalize

    avoid = _pool_exhausted()
    for cap in ["edge_computing", "failure_analysis", "container_orchestration", "api_testing"]:
        got = _fallback_name(cap, set(avoid))
        initials = "".join(w[0] for w in got["expansion"].split())
        assert initials == _normalize(got["name"]), (
            f"{cap}: expansion {got['expansion']!r} spells {initials}, " f"name is {_normalize(got['name'])}"
        )


def test_a_large_batch_yields_unique_names_with_no_clone_family():
    """40 net-new hires in one batch — the shape that broke. Unique, valid, and
    no stem reused with suffixes."""
    from services.agent_name_generator import _fallback_name, _normalize, _valid_letters

    caps = [
        "edge_computing",
        "api_testing",
        "container_orchestration",
        "distributed_systems",
        "failure_analysis",
        "deployment_automation",
        "code_quality_analysis",
        "ci_cd_pipeline",
        "database_validation",
        "api_integration",
        "api_architecture",
        "framework_implementation",
        "load_testing",
        "secret_scanning",
        "log_aggregation",
        "service_mesh",
        "chaos_engineering",
        "schema_migration",
        "cache_strategy",
        "queue_management",
        "observability_tracing",
        "incident_response",
        "capacity_planning",
        "cost_optimization",
        "access_review",
        "patch_management",
        "backup_verification",
        "network_policy",
        "image_scanning",
        "runtime_security",
        "config_drift",
        "release_orchestration",
        "feature_flagging",
        "canary_analysis",
        "rollback_automation",
        "dependency_audit",
        "e2e_automation",
        "interface_design",
        "qa_sandbox_restore",
        "infrastructure_architecture",
    ]
    avoid, seen = set(), []
    for cap in caps:
        got = _fallback_name(cap, avoid)
        letters = _normalize(got["name"])
        assert _valid_letters(letters), f"{cap} produced invalid {got['name']}"
        assert letters not in avoid, f"{cap} produced duplicate {got['name']}"
        avoid.add(letters)
        seen.append(got["name"])
    assert len(set(seen)) == len(caps)
    assert not _suffix_clones(seen), f"clone family: {_suffix_clones(seen)}"


def test_digits_survive_in_capability_words():
    """'e2e_automation' rendered as 'E E Automation' — [^a-z ] deleted the digit."""
    from services.agent_name_generator import capability_phrase, capability_words

    assert capability_phrase(capability_words("e2e_automation")) == "E2E Automation"
    assert capability_phrase(capability_words("s3_lifecycle")) == "S3 Lifecycle"
    assert capability_phrase(capability_words("edge_computing")) == "Edge Computing"
