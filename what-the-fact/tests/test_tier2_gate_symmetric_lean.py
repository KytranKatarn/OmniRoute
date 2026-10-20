"""The Tier-2 gate's source-lean special case is symmetric when flagged on, unchanged when off (#7340).

Measured 2026-10-19 on the live DB: 'right' = ONE outlet (Le Journal de Montréal, 254 articles/7d, all escalated
only because of its lean = ~28% of the 914/week deep-pass articles); the 6 'left' outlets (96 articles/7d) had no
equivalent. A symmetric rule newly escalates at most ~22 articles/week (~2.4%), so it ships behind
WTF_TIER2_GATE_SYMMETRIC_LEAN, default OFF.
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import tier_router  # noqa: E402


@pytest.fixture
def router(monkeypatch):
    """Reload tier_router with the flag in the requested state, then restore the default afterwards."""

    def load(flag):
        if flag is None:
            monkeypatch.delenv("WTF_TIER2_GATE_SYMMETRIC_LEAN", raising=False)
        else:
            monkeypatch.setenv("WTF_TIER2_GATE_SYMMETRIC_LEAN", flag)
        return importlib.reload(tier_router)

    yield load
    monkeypatch.delenv("WTF_TIER2_GATE_SYMMETRIC_LEAN", raising=False)
    importlib.reload(tier_router)


def _bias_gate(mod, lean, slug="some_outlet"):
    # centre band, short body, no cluster: nothing but the source lean can trigger it
    return mod._evaluate_gate({"band": "center"}, 200, slug, lean, 0)


def _fact_gate(mod, lean, slug="some_outlet"):
    return mod._factcheck_gate([], 200, slug, lean, 0)


def test_special_leans_pure_function():
    assert tier_router.special_leans(False) == {"right"}
    assert tier_router.special_leans(True) == {"right", "left"}


def test_default_is_unchanged_right_only(router):
    mod = router(None)
    assert mod._GATE_SPECIAL_LEANS == {"right"}
    for gate in (_bias_gate, _fact_gate):
        assert gate(mod, "right")[0] is True
        assert gate(mod, "left")[0] is False  # the asymmetry the owner asked to remove (only once enabled)


def test_flag_on_makes_both_gates_symmetric(router):
    mod = router("true")
    assert mod._GATE_SPECIAL_LEANS == {"right", "left"}
    for gate in (_bias_gate, _fact_gate):
        ok, reason = gate(mod, "left")
        assert ok is True and reason == "source_lean=left"
        assert gate(mod, "right")[0] is True


def test_the_centre_leans_are_never_special_cased(router):
    for flag in (None, "true"):
        mod = router(flag)
        for lean in ("center-left", "center-right", "center", "", None):
            assert _bias_gate(mod, lean)[0] is False and _fact_gate(mod, lean)[0] is False


def test_matching_is_case_insensitive(router):
    mod = router("true")
    assert _bias_gate(mod, "Left")[0] is True and _fact_gate(mod, "LEFT")[0] is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "garbage"])
def test_only_explicit_truthy_values_turn_it_on(router, value):
    assert router(value)._GATE_SPECIAL_LEANS == {"right"}


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_truthy_values_turn_it_on(router, value):
    assert router(value)._GATE_SPECIAL_LEANS == {"right", "left"}


def test_the_flag_does_not_touch_the_other_gate_rules(router):
    mod = router("true")
    assert mod._evaluate_gate({"band": "left"}, 200, "x", "", 0)[0] is True  # article-level band still works
    assert mod._evaluate_gate({"band": "center"}, 10**6, "x", "", 0)[0] is True  # long body still works
    assert mod._evaluate_gate({"band": "center"}, 200, "windspeaker", "", 0)[0] is True  # Indigenous press too
    assert mod._factcheck_gate(["c"] * 99, 10**6, "x", "", 0)[0] is True  # claims + body still works
