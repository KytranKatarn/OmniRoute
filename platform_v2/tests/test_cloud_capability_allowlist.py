"""Cloud is for development and repairs — never for company data (#6653).

THE OWNER RULE (2026-09-09): coding and design work may use cloud contractors;
Watch-product / civic / gov / legal content may not, ever.

THE PROBLEM THAT MADE THIS NECESSARY: the DHQ Contractors "Cloud AI" toggle
writes ONE global value — `platform_settings.escalation_mode`, local_only <->
ask_first. It has no per-capability dimension, so flipping it ON opens cloud for
EVERYTHING. Measured 30-day volume sitting behind that button:

    fact_check           65,812      code_review     4,287
    beat_classification  36,626      documentation   3,059
    bias_analysis        29,605      creative        1,923
    translate            27,077
    geo_extraction       11,416

~220k company-data dispatches against ~9k of actual dev work. Ask-first Telegram
approval was the only thing between civic/gov/legal prompts and a third-party
wire — a human making the same judgement hundreds of thousands of times, where
one mis-tap is an irreversible disclosure. A policy someone remembers is not a
control; this makes the boundary mechanical.

⚠️ THE FAIL DIRECTION IS THE WHOLE POINT, and it is the OPPOSITE of the budget
gate it sits beside. `_cloud_budget_ok` fails OPEN and never raises, because a
counting bug must never block real work. `_cloud_capability_allowed` fails
CLOSED, because an unrecognised capability might be company data and the cost of
guessing wrong is a disclosure that cannot be taken back. Work that stays local
is merely slower. Both guards live at the same three call sites; do not
"harmonise" their defaults.

Run (host, repo checkout):
    DB_HOST=192.168.1.200 ... python3 -m pytest tests/test_cloud_capability_allowlist.py -v
"""

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parents[1]))

_DISPATCHER_SRC = _HERE.parents[1] / "tools" / "department_hq" / "services" / "department_dispatcher.py"

# Capabilities that carry Watch-product / platform / knowledge-base content.
# These are the ones a leak would actually matter for.
COMPANY_DATA_CAPABILITIES = [
    "fact_check",
    "factcheck_quick",
    "fact_check_backlog",
    "bias_analysis",
    "bias_quick",
    "bias_backlog",
    "beat_classification",
    "geo_extraction",
    "translate",
    "knowledge_analysis",
    "analyze",
    "classify",
    "web_scrape",
    "conversation",
    "workforce_planning",
    "welfare_monitoring",
    "security",
    "documentation",
]

DEV_CAPABILITIES = ["code", "code_review", "code_fix", "debug", "creative", "visual_design", "ux_scoring"]


@pytest.fixture(scope="module")
def dispatcher():
    try:
        from services.signal_calendar_service import _ensure_import_paths

        _ensure_import_paths()
    except Exception:  # pragma: no cover - path helper is best effort
        pass
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"dispatcher not importable here: {exc}")
    return get_dispatcher()


# ── the sovereignty guarantee ────────────────────────────────────────────────


@pytest.mark.parametrize("capability", COMPANY_DATA_CAPABILITIES)
def test_company_data_capabilities_never_reach_cloud(dispatcher, capability):
    """THE load-bearing assertion. If this fails, civic data can leave the cluster."""
    assert (
        dispatcher._cloud_capability_allowed(capability) is False
    ), f"'{capability}' carries company data and must never be cloud-eligible"


@pytest.mark.parametrize("capability", DEV_CAPABILITIES)
def test_development_capabilities_are_permitted(dispatcher, capability):
    """The other half — the allowlist has to actually allow the intended work,
    or the owner flips the whole guard off in frustration and we lose both."""
    assert (
        dispatcher._cloud_capability_allowed(capability) is True
    ), f"'{capability}' is development work and should be cloud-eligible"


# ── fail-closed, in every direction an input can be wrong ────────────────────


@pytest.mark.parametrize("capability", [None, "", "   ", "unknown", "not_a_real_capability", "fact_check_v2"])
def test_unclassifiable_input_is_refused(dispatcher, capability):
    """Cannot classify it ⇒ cannot ship it. A capability added later that nobody
    thought to review defaults to LOCAL, which is the safe side of the mistake."""
    assert dispatcher._cloud_capability_allowed(capability) is False


def test_case_and_whitespace_do_not_defeat_the_gate(dispatcher):
    """Both directions: sloppy input must not silently BLOCK legitimate dev work…"""
    assert dispatcher._cloud_capability_allowed("  CODE_REVIEW ") is True
    # …and casing must not be a way to smuggle a blocked capability past it.
    assert dispatcher._cloud_capability_allowed("FACT_CHECK") is False


def test_a_database_failure_blocks_rather_than_opens(dispatcher, monkeypatch):
    """A DB blip must never widen the sovereignty boundary.

    This is the asymmetry with `_cloud_budget_ok`, which deliberately fails OPEN.
    """
    monkeypatch.setattr(dispatcher, "_cloud_allowlist_cache", None, raising=False)

    def boom():
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(dispatcher, "_get_db", boom, raising=True)
    assert dispatcher._cloud_capability_allowed("code_review") is False


# ── config semantics that are easy to get backwards ──────────────────────────


def test_absent_setting_yields_the_dev_default_not_allow_all(dispatcher):
    """A fresh database must not be MORE permissive than a configured one."""
    src = _DISPATCHER_SRC.read_text(encoding="utf-8")
    assert "_CLOUD_ALLOWLIST_DEFAULT" in src
    for cap in DEV_CAPABILITIES:
        assert cap in src, f"{cap} missing from the built-in default"
    for cap in ("fact_check", "bias_analysis", "translate"):
        assert (
            f'"{cap}' not in src.split("_CLOUD_ALLOWLIST_DEFAULT")[1].split("\n")[0]
        ), f"{cap} must not be in the built-in default allowlist"


def test_empty_allowlist_blocks_everything_it_is_the_kill_switch(dispatcher, monkeypatch):
    """⚠️ INVERTS `fleet_resource_router.model_hardware_blocklist()`, where an
    empty string CLEARS the block (allow all). Same config shape, opposite
    meaning — an empty ALLOWlist admits nothing. Pinned so nobody unifies them."""
    monkeypatch.setattr(dispatcher, "_cloud_allowlist_cache", (9e9, set()), raising=False)
    for cap in DEV_CAPABILITIES:
        assert dispatcher._cloud_capability_allowed(cap) is False


# ── the structural guard: wire it at the CHOKE POINT ─────────────────────────


def test_every_cloud_budget_gate_is_paired_with_an_allowlist_gate():
    """A future 4th cloud path must not ship without the sovereignty check.

    This codebase's most-repeated defect is a correct guard that exists but is
    not wired where it binds (#5194, #5862, #2738, #6647). `_cloud_budget_ok`
    already marks every place a cloud text dispatch can escape, so pairing the
    two counts turns "remember to add the allowlist too" into a red test.
    """
    src = _DISPATCHER_SRC.read_text(encoding="utf-8")
    budget_calls = len(re.findall(r"self\._cloud_budget_ok\(", src))
    allow_calls = len(re.findall(r"self\._cloud_capability_allowed\(", src))
    # Each has exactly one definition line that is not a call site.
    assert budget_calls >= 3, "cloud budget call sites disappeared — did the escape paths move?"
    assert allow_calls >= budget_calls, (
        f"{budget_calls} cloud budget gates but only {allow_calls} allowlist gates — "
        "a cloud dispatch path can bypass the sovereignty check"
    )
