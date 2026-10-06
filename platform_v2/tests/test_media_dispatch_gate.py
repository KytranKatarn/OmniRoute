"""Media cloud generation must honour the same operator switches as text routing.

`_call_openai_compatible` — the shared text egress — has enforced `dispatchable` at its call site
since DS9 PR 1, with a comment explaining why: gating only the selector leaves every direct caller an
open door. Media was that open door.

The Media Studio cloud path is not unguarded — it checks the master cloud toggle, the capability
allowlist, and the weekly free budget. Three real gates. It then walked past the per-provider switch
an operator flips in the Contractors tab. Turning routing OFF for `gemini` or `together` changed the
text fleet and left media spending.

These tests are static. They read the function body and assert the gate is present and correctly
ordered, because the alternative is a live test that spends money to prove a refusal works.
"""

import ast
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, "/app")

import ai_bridge.external_providers as ep  # noqa: E402


def _body(name: str) -> str:
    src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
    i = src.index(f"def {name}(")
    rest = src[i:]
    j = re.search(r"\n(?:def |@)", rest[1:])
    return rest[: j.start() + 1] if j else rest


def _first_call_line(body: str, needle: str) -> int:
    """1-indexed line of the first call to `needle`, or a large number if absent."""
    for n, line in enumerate(body.split("\n"), start=1):
        if needle in line:
            return n
    return 10**6


class TestMediaDispatchGate(unittest.TestCase):
    """The switch an operator flips must mean the same thing on every egress."""

    # ---- both switches are enforced -------------------------------------------

    def test_dispatchable_is_checked(self):
        self.assertIn("dispatchable", _body("generate_media"))

    def test_is_active_is_checked(self):
        self.assertIn("is_active", _body("generate_media"))

    def test_a_refusal_returns_success_false(self):
        self.assertIn('"success": False', _body("generate_media"))

    def test_the_dispatchable_refusal_names_the_column(self):
        """The operator reading this needs to know which switch to flip."""
        body = _body("generate_media")
        self.assertIn("contractor_providers.dispatchable is false", body)

    def test_the_inactive_refusal_names_the_column(self):
        self.assertIn("contractor_providers.is_active is false", _body("generate_media"))

    # ---- ordering: the gate must precede any dispatch -------------------------

    def test_the_gate_precedes_the_adapter_call(self):
        body = _body("generate_media")
        gate = _first_call_line(body, "_get_provider_config")
        dispatch = _first_call_line(body, "adapter(request)")
        self.assertLess(gate, dispatch, "the gate must run before the adapter is called")
        self.assertLess(dispatch, 10**6, "adapter(request) not found in generate_media")

    def test_the_gate_precedes_the_adapter_lookup(self):
        """Refusing must name the switch, not 'no media adapter'."""
        body = _body("generate_media")
        self.assertLess(
            _first_call_line(body, "_get_provider_config"),
            _first_call_line(body, "adapters.get(provider_key)"),
        )

    # ---- absence is not refusal ----------------------------------------------

    def test_a_provider_with_no_row_is_not_gated(self):
        """`local_tts` has no contractor row: it is local and free.

        Gating it on a config that does not exist would break local text-to-speech to enforce a
        switch it was never subject to. Mirrors `call_external`'s `_cfg is not None`.
        """
        body = _body("generate_media")
        self.assertIn("_cfg is not None", body)
        # and both refusals live inside that guard
        i = body.index("_cfg is not None")
        guarded = body[i:]
        self.assertIn("is_active", guarded)
        self.assertIn("dispatchable", guarded)

    def test_it_mirrors_the_text_paths_none_guard(self):
        """Both paths must agree on what an absent row means.

        The text gate lives in `_call_openai_compatible`, the shared egress — naming it wrongly
        here made this test pass vacuously against the wrong function.
        """
        self.assertIn(
            "_cfg is not None",
            _body("_call_openai_compatible"),
            "the text egress's guard shape changed — keep the two in step",
        )

    def test_the_text_egress_enforces_dispatchable_at_all(self):
        """Guards the premise of the whole change.

        If `_call_openai_compatible` ever stops enforcing the switch, media would be the ONLY path
        that does — and this file's framing would be backwards.
        """
        self.assertIn("dispatchable", _body("_call_openai_compatible"))

    # ---- it is a real gate, not a log -----------------------------------------

    def test_no_adapter_runs_when_the_switch_is_off(self):
        """Structural: the refusals `return`, so control never reaches `adapter(request)`."""
        tree = ast.parse(pathlib.Path(ep.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "generate_media")
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        self.assertGreaterEqual(len(returns), 4, "expected two refusals plus the adapter/no-adapter returns")
        # every refusal returns a dict literal whose success is the constant False
        refusals = [
            n
            for n in returns
            if isinstance(n.value, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == "success" for k in n.value.keys if k is not None)
        ]
        self.assertGreaterEqual(len(refusals), 3)
        for r in refusals:
            success = next(
                v for k, v in zip(r.value.keys, r.value.values) if isinstance(k, ast.Constant) and k.value == "success"
            )
            self.assertIsInstance(success, ast.Constant)
            # Unconditional. An earlier version skipped string values, which was a loophole: it
            # meant a refusal carrying success="false" (a truthy string) would have passed.
            self.assertIs(success.value, False, "a refusal must report success=False exactly")

    # ---- live behaviour, without spending -------------------------------------

    def test_a_non_dispatchable_provider_is_refused_without_calling_the_adapter(self):
        """The one behavioural test: proves the refusal happens BEFORE any spend."""
        cfg = {"is_active": True, "dispatchable": False}
        with mock.patch.object(ep, "_get_provider_config", return_value=cfg):
            with mock.patch.object(ep, "_gemini_media_adapter") as adapter:
                result = ep.generate_media("gemini", {"prompt": "x"})
        self.assertFalse(result["success"])
        self.assertFalse(result["dispatchable"])
        self.assertIn("dispatchable is false", result["error"])
        self.assertFalse(adapter.called, "the adapter must never be reached")

    def test_an_inactive_provider_is_refused_without_calling_the_adapter(self):
        cfg = {"is_active": False, "dispatchable": True}
        with mock.patch.object(ep, "_get_provider_config", return_value=cfg):
            with mock.patch.object(ep, "_gemini_media_adapter") as adapter:
                result = ep.generate_media("gemini", {"prompt": "x"})
        self.assertFalse(result["success"])
        self.assertFalse(result["is_active"])
        self.assertFalse(adapter.called)

    def test_a_provider_with_no_row_still_reaches_the_adapter(self):
        """The local_tts case. The adapter is stubbed, so nothing is dispatched or spent."""
        with mock.patch.object(ep, "_get_provider_config", return_value=None):
            with mock.patch.object(ep, "_local_tts_adapter", return_value={"success": True}) as ad:
                result = ep.generate_media("local_tts", {"text": "x"})
        self.assertTrue(result["success"])
        self.assertTrue(ad.called)

    def test_a_dispatchable_provider_reaches_the_adapter(self):
        cfg = {"is_active": True, "dispatchable": True}
        with mock.patch.object(ep, "_get_provider_config", return_value=cfg):
            with mock.patch.object(ep, "_gemini_media_adapter", return_value={"success": True}) as ad:
                result = ep.generate_media("gemini", {"prompt": "x"})
        self.assertTrue(result["success"])
        self.assertTrue(ad.called)

    def test_the_refusal_never_raises(self):
        """A refusal is a normal outcome. Media Studio handles success=False; an exception
        would become an unhandled job failure."""
        with mock.patch.object(ep, "_get_provider_config", return_value=None):
            with mock.patch.object(ep, "_gemini_media_adapter", side_effect=RuntimeError("boom")):
                result = ep.generate_media("gemini", {"prompt": "x"})
        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])


if __name__ == "__main__":
    unittest.main()
