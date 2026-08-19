"""Capability alias normalization + unknown-capability observability (#5819).

An UNKNOWN capability does not fail: CAPABILITY_DEPARTMENT_MAP.get() falls back
to Engineering & Technology, and because no agent holds a skill by that literal
name the skill bonus never differentiates anyone — so selection silently lands
on whoever is least loaded. Measured 2026-08-19: `ui_verify` and `browser_test`
both routed to H.A.R.B.O.R. instead of P.R.O.B.E.

These tests are pure (no DB): they pin the alias table and the normalizer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.department_coordinator import (  # noqa: E402
    CAPABILITY_ALIASES,
    CAPABILITY_DEPARTMENT_MAP,
    normalize_capability,
)

# The canonical skill names P.R.O.B.E. actually holds (verified live 2026-08-19).
_PROBE_SKILLS = {
    "ui_testing",
    "browser_testing",
    "playwright_testing",
    "e2e_automation",
    "visual_regression",
    "qa_testing",
    "regression_detection",
}


def test_the_two_measured_misroutes_are_aliased():
    """ui_verify / browser_test are the exact names that hit H.A.R.B.O.R."""
    assert normalize_capability("ui_verify") == "ui_testing"
    assert normalize_capability("browser_test") == "browser_testing"


def test_every_alias_target_is_a_real_probe_skill():
    """An alias pointing at a name no agent holds just RELOCATES the misroute.

    This is the guard that keeps the table honest: adding
    `"foo": "does_not_exist"` would look like a fix and change nothing.
    """
    for alias, target in CAPABILITY_ALIASES.items():
        assert target in _PROBE_SKILLS, f"{alias} -> {target} is not a real P.R.O.B.E. skill"


def test_no_alias_shadows_a_mapped_capability():
    """An alias must never hijack a capability that already routes correctly."""
    for alias in CAPABILITY_ALIASES:
        assert alias not in CAPABILITY_DEPARTMENT_MAP, f"alias {alias!r} shadows a real capability"


def test_alias_lookup_is_case_and_whitespace_insensitive():
    assert normalize_capability("  UI_Verify ") == "ui_testing"


def test_unknown_capability_is_returned_UNCHANGED_not_lowercased():
    """Only the LOOKUP is case-insensitive. Returning a lower-cased string would
    silently break any exact-match caller or case-sensitive skill name."""
    assert normalize_capability("SomeUnknownThing") == "SomeUnknownThing"


def test_falsy_and_non_string_pass_through():
    for value in (None, "", 0, [], {}):
        assert normalize_capability(value) == value


def test_known_capabilities_are_untouched():
    """Regression guard: normalization must not perturb existing routing."""
    for cap in ("documentation", "security", "research", "code_review", "browser_testing"):
        assert normalize_capability(cap) == cap
