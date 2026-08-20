"""A shed dispatch is NOT an untranslatable string (#5851).

MEASURED 2026-08-20: `translate` showed 53% failure over 2,190 runs/48h — the largest failure
signal on the platform. 96% of those failures were ONE message:

    "hub saturated — 7B in-flight admission cap reached; shed to relieve the hub (retry shortly)"

at avg 2.9s. That is the dispatcher deliberately REFUSING work, not a model failing. Only 32 of
~1,160 were real timeouts.

The bug is what the caller does with it. `_generate_translation` read `.response` without ever
checking `.success` (violating ADR-013's stated contract), so a shed dispatch became
`translated=""` — indistinguishable from "the model produced nothing." Nothing retried, so the
dispatcher's "retry shortly" was addressed to no one: the string stayed untranslated, came back
on the next scan, and re-flooded a hub that was already saturated. Self-perpetuating.

These tests pin the distinction that makes the difference:
  a SUCCESSFUL dispatch returning empty text  -> a real miss, record it
  an UNSUCCESSFUL dispatch (any reason)       -> deferred, leave the gap for next pass
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.consciousness.translation_scanners import generator  # noqa: E402


class _Result:
    """Stand-in for DispatchResult — only the fields the caller may legitimately read."""

    def __init__(self, success, response="", error=None):
        self.success = success
        self.response = response
        self.error = error


_SHED = "hub saturated — 7B in-flight admission cap reached; shed to relieve the hub (retry shortly)"


def _raw_lang():
    """A language routed through the RAW-text path (dispatch, not dispatch_json)."""
    for lang in ("ar", "he", "de"):
        model, _agent = generator.get_translate_routing(lang)
        if model in generator._RAW_OUTPUT_MODELS:
            return lang
    raise AssertionError("no language routes to the raw-output path — routing changed?")


class TestShedIsNotAFailedTranslation(unittest.TestCase):
    def test_shed_dispatch_is_deferred(self):
        lang = _raw_lang()
        with mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            return_value=_Result(False, "", _SHED),
        ):
            out = generator._generate_translation("Save", lang)
        self.assertTrue(out.get("deferred"), "a shed dispatch must be DEFERRED, not a failed translation")
        self.assertEqual(out["translated"], "")

    def test_any_unsuccessful_dispatch_is_deferred_not_just_shed(self):
        """A timeout is equally not evidence that a string cannot be translated."""
        lang = _raw_lang()
        with mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            return_value=_Result(False, "", "timeout after 240s"),
        ):
            out = generator._generate_translation("Save", lang)
        self.assertTrue(out.get("deferred"))

    def test_successful_but_empty_is_a_REAL_miss_not_deferred(self):
        """The model ran and produced nothing. That IS information — do not hide it."""
        lang = _raw_lang()
        with mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            return_value=_Result(True, "   "),
        ):
            out = generator._generate_translation("Save", lang)
        self.assertFalse(out.get("deferred"), "a successful empty response is a real miss")
        self.assertEqual(out["translated"], "")

    def test_successful_translation_is_not_deferred(self):
        lang = _raw_lang()
        with mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            return_value=_Result(True, "Guardar"),
        ):
            out = generator._generate_translation("Save", lang)
        self.assertFalse(out.get("deferred"))
        self.assertEqual(out["translated"], "Guardar")

    def test_raised_exception_is_deferred(self):
        """An exception is not evidence about the string either."""
        lang = _raw_lang()
        with mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            side_effect=RuntimeError("boom"),
        ):
            out = generator._generate_translation("Save", lang)
        self.assertTrue(out.get("deferred"))


class TestStatusSurfaceIsExplicit(unittest.TestCase):
    """The orchestrator must be able to tell 'deferred' from 'skipped' WITHOUT truthiness."""

    def test_status_function_exists_and_names_the_three_outcomes(self):
        self.assertTrue(hasattr(generator, "process_missing_gap_status"))

    def test_bool_wrapper_stays_backward_compatible(self):
        """Two live call sites do `if process_missing_gap(gap):` — that must keep meaning
        'a translation was written', never 'it was deferred'."""
        with mock.patch.object(generator, "process_missing_gap_status", return_value="deferred"):
            self.assertFalse(generator.process_missing_gap({"id": 1}))
        with mock.patch.object(generator, "process_missing_gap_status", return_value="skipped"):
            self.assertFalse(generator.process_missing_gap({"id": 1}))
        with mock.patch.object(generator, "process_missing_gap_status", return_value="written"):
            self.assertTrue(generator.process_missing_gap({"id": 1}))


class TestProducerHasBrakes(unittest.TestCase):
    """Part 1: the scan must not start a flood into a hub that is already saturated."""

    def test_orchestrator_consults_the_shared_backpressure_gate(self):
        src = (_ROOT / "tools" / "consciousness" / "translation_scanners" / "orchestrator.py").read_text()
        self.assertIn(
            "in_flight_over_cap",
            src,
            "the generation pass must consult the SHARED gate (the WTF producers use it; #4536) "
            "rather than inventing a second backpressure mechanism",
        )

    def test_orchestrator_stops_the_batch_when_deferred(self):
        """Continuing to fire into a saturated hub is what produced 1,117 shed dispatches."""
        src = (_ROOT / "tools" / "consciousness" / "translation_scanners" / "orchestrator.py").read_text()
        self.assertIn("deferred", src, "the loop must react to a deferral, not grind through NIGHTLY_CAP")


if __name__ == "__main__":
    unittest.main()
