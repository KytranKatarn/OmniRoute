"""Contractor budget bands and dispatch gating (DS9 PR 2).

The behaviours pinned here are the ones that decide whether the platform spends money
without being asked. Three, in order of consequence:

1. `paid ⇒ dispatchable`. A paid provider must be refused at BOTH the selector and the call
   site. Gating only the selector leaves `call_external(provider=...)` — which callers use
   directly — an open door, and "never dispatch a paid provider unless enabled" becomes
   true only of the path someone remembered to check.

2. The monthly budget is three-state, not boolean: `ok` / `warn` (80%) / `block` (95%).
   The old single boolean refused at 100%, so the only signal was the refusal — the budget
   was already spent before anyone heard. The stop is 95% rather than 100% so an in-flight
   task can finish and the month does not overshoot.

3. A failed budget query fails OPEN, but is logged. It used to return `True` silently, which
   is indistinguishable from "no budget configured" — so a broken query disabled the budget
   entirely without anyone noticing.

No database. `get_db` is patched to a fake, so these are hermetic and assert the decision
function rather than the plumbing.
"""

import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, "/app")

import ai_bridge.external_providers as ep  # noqa: E402


class FakeCursor:
    """Returns one row (or none) and nothing else. Enough for the budget query."""

    def __init__(self, row):
        self._row = row
        self.closed = False

    def execute(self, *_a, **_k):
        return None

    def fetchone(self):
        return self._row

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, row):
        self._cur = FakeCursor(row)
        self.closed = False

    def cursor(self):
        return self._cur

    def close(self):
        self.closed = True


def patch_db(row):
    """Patch the `database` module's get_db, which external_providers imports lazily."""
    module = types.ModuleType("database")
    module.get_db = lambda: FakeConn(row)
    return mock.patch.dict(sys.modules, {"database": module})


class TestBudgetBands(unittest.TestCase):
    """The 80 / 95 thresholds and the fail-open contract."""

    def _status(self, limit, used, row=True):
        payload = (limit, used) if row else None
        with patch_db(payload):
            return ep.monthly_budget_status("groq")

    def test_under_eighty_is_ok(self):
        """7.99 of 10 is 79.9%, so it must be ok and not warn."""
        st = self._status(10.0, 7.99)
        self.assertEqual(st["band"], "ok")
        self.assertLess(st["fraction"], ep.BUDGET_WARN_FRACTION)

    def test_exactly_eighty_warns(self):
        """Boundary: 80% must warn, not slip through as ok."""
        self.assertEqual(self._status(100.0, 80.0)["band"], "warn")

    def test_just_below_eighty_is_ok(self):
        self.assertEqual(self._status(100.0, 79.99)["band"], "ok")

    def test_ninety_five_blocks(self):
        """Boundary: 95% must block. The stop is deliberately not 100%."""
        self.assertEqual(self._status(100.0, 95.0)["band"], "block")

    def test_just_below_ninety_five_still_warns_rather_than_blocks(self):
        self.assertEqual(self._status(100.0, 94.99)["band"], "warn")

    def test_warn_band_does_not_refuse(self):
        """A warning is a notification, not a stop."""
        with patch_db((100.0, 85.0)):
            self.assertTrue(ep._check_budget("groq"))

    def test_block_band_refuses(self):
        with patch_db((100.0, 96.0)):
            self.assertFalse(ep._check_budget("groq"))

    def test_thresholds_are_the_agreed_values(self):
        self.assertEqual(ep.BUDGET_WARN_FRACTION, 0.80)
        self.assertEqual(ep.BUDGET_BLOCK_FRACTION, 0.95)

    def test_no_budget_row_is_unconfigured_and_allowed(self):
        st = self._status(None, None, row=False)
        self.assertEqual(st["band"], "unconfigured")
        with patch_db(None):
            self.assertTrue(ep._check_budget("groq"))

    def test_null_budget_falls_back_to_the_documented_default(self):
        """Matches the historical behaviour, named explicitly so it is a decision."""
        st = self._status(None, 1.0)
        self.assertEqual(st["limit"], ep.DEFAULT_MONTHLY_BUDGET_USD)
        self.assertEqual(ep.DEFAULT_MONTHLY_BUDGET_USD, 10.0)

    def test_null_cost_reads_as_zero(self):
        self.assertEqual(self._status(100.0, None)["used"], 0.0)

    def test_zero_budget_does_not_divide_by_zero(self):
        st = self._status(0.0, 5.0)
        self.assertEqual(st["fraction"], 0.0)

    def test_failed_query_fails_open_but_is_logged(self):
        """The regression this fixes.

        `except: return True` is indistinguishable from "no budget configured", so a
        persistently broken query silently disabled the budget with no signal at all.
        """
        boom = types.ModuleType("database")

        def _raise():
            raise RuntimeError("connection refused")

        boom.get_db = _raise
        with mock.patch.dict(sys.modules, {"database": boom}), self.assertLogs(ep.logger, level="WARNING") as captured:
            st = ep.monthly_budget_status("groq")
        self.assertEqual(st["band"], ep.BUDGET_UNKNOWN)
        self.assertTrue(
            any("budget query failed" in m for m in captured.output),
            "a failed budget query must be logged, not swallowed",
        )

    def test_failed_query_is_never_block(self):
        """Fail-open means allowed, whatever else it is."""
        boom = types.ModuleType("database")
        boom.get_db = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        with mock.patch.dict(sys.modules, {"database": boom}):
            self.assertTrue(ep._check_budget("groq"))


class TestDispatchGate(unittest.TestCase):
    """`paid ⇒ dispatchable`, enforced at the call site as well as the selector."""

    def _cfg(self, **over):
        base = {
            "base_url": "http://omniroute:20128/v1",
            "default_model": "auto/coding",
            "dispatchable": True,
            "provider_class": "free_tier",
        }
        base.update(over)
        return base

    def _call(self, cfg):
        """Run the real call site with everything except the provider config stubbed."""
        with mock.patch.object(ep, "_get_provider_config", lambda p: cfg), mock.patch.object(
            ep, "_get_api_key", lambda p: "k"
        ), mock.patch.object(ep, "_check_budget", lambda p: True), mock.patch.object(
            ep, "check_weekly_budget", lambda p: True
        ), mock.patch.object(
            ep, "_omniroute_quota_gate", lambda m, b: {"allow": True}
        ), mock.patch.object(
            ep, "_update_cost", lambda *a, **k: None
        ), mock.patch.object(
            ep, "_log_usage", lambda *a, **k: None
        ), mock.patch.object(
            ep, "_calculate_cost", lambda *a, **k: 0.0
        ), mock.patch.object(
            ep.requests, "post", side_effect=OSError("no network")
        ):
            return ep._call_openai_compatible("omniroute", "hi")

    def test_non_dispatchable_is_refused_before_any_request(self):
        out = self._call(self._cfg(dispatchable=False))
        self.assertFalse(out["success"])
        self.assertIn("not enabled for dispatch", out["error"])

    def test_refusal_names_the_column_an_operator_can_flip(self):
        """The operator needs to know WHERE to act, not just that it failed."""
        out = self._call(self._cfg(dispatchable=False))
        self.assertIn("dispatchable", out["error"])

    def test_dispatchable_passes_the_gate(self):
        """A refusal must be the gate's doing, not a downstream network error."""
        out = self._call(self._cfg(dispatchable=True))
        self.assertNotIn("not enabled for dispatch", out.get("error", ""))

    def test_paid_and_not_dispatchable_is_refused(self):
        """The rule as stated: a paid provider is never dispatched unless enabled."""
        out = self._call(self._cfg(dispatchable=False, provider_class="paid"))
        self.assertFalse(out["success"])
        self.assertIn("not enabled for dispatch", out["error"])

    def test_paid_and_dispatchable_is_allowed(self):
        out = self._call(self._cfg(dispatchable=True, provider_class="paid"))
        self.assertNotIn("not enabled for dispatch", out.get("error", ""))

    def test_absent_dispatchable_key_is_treated_as_disabled(self):
        """Every row defaults FALSE, so a missing key must fail closed.

        `provider.get("dispatchable", False)` — not `.get(..., True)`. Defaulting to True
        would make the gate a no-op for any provider added before the column existed.
        """
        out = self._call({"base_url": "http://x/v1", "default_model": "m"})
        self.assertFalse(out["success"])
        self.assertIn("not enabled for dispatch", out["error"])


class TestSelectorGate(unittest.TestCase):
    """The capability map must not offer anything not dispatchable."""

    def _map(self, providers):
        with mock.patch.object(ep, "_load_all_providers", lambda: None), mock.patch.dict(
            ep.__dict__, {"_provider_cache": dict(providers)}
        ):
            return ep.get_all_capabilities()

    def test_non_dispatchable_provider_is_not_offered(self):
        caps = self._map(
            {
                "groq": {
                    "is_active": True,
                    "dispatchable": False,
                    "provider_class": "paid",
                    "capabilities": ["text_chat"],
                }
            }
        )
        self.assertEqual(caps.get("text_chat", []), [])

    def test_dispatchable_provider_is_offered(self):
        caps = self._map(
            {
                "groq": {
                    "is_active": True,
                    "dispatchable": True,
                    "provider_class": "paid",
                    "capabilities": ["text_chat"],
                    "tier_position": 6,
                }
            }
        )
        self.assertEqual(len(caps["text_chat"]), 1)

    def test_inactive_is_still_excluded(self):
        caps = self._map({"groq": {"is_active": False, "dispatchable": True, "capabilities": ["text_chat"]}})
        self.assertEqual(caps.get("text_chat", []), [])

    def test_both_switches_are_required(self):
        """Configured but not enabled must not appear — that is the whole point."""
        caps = self._map({"groq": {"is_active": True, "dispatchable": False, "capabilities": ["text_chat"]}})
        self.assertEqual(caps.get("text_chat", []), [])

    def test_selector_treats_a_missing_dispatchable_key_as_disabled(self):
        """The fail-CLOSED default, on the selector path too.

        A provider row that predates the column has no `dispatchable` key at all. If the
        selector reads `.get("dispatchable", True)` the gate is a no-op for exactly those
        rows — the ones nobody has consciously enabled. Both gates must default to False.
        """
        with mock.patch.object(ep, "_load_all_providers", lambda: None), mock.patch.dict(
            ep.__dict__,
            {
                "_provider_cache": {
                    "legacy": {
                        "is_active": True,
                        # no dispatchable key at all
                        "capabilities": ["text_chat"],
                    }
                }
            },
        ):
            self.assertEqual(ep.get_all_capabilities().get("text_chat", []), [])
            self.assertEqual(ep.get_providers_with_capability("text_chat"), [])

    def test_get_providers_with_capability_agrees(self):
        with mock.patch.object(ep, "_load_all_providers", lambda: None), mock.patch.dict(
            ep.__dict__,
            {
                "_provider_cache": {
                    "groq": {
                        "is_active": True,
                        "dispatchable": False,
                        "capabilities": ["text_chat"],
                        "tier_position": 6,
                    }
                }
            },
        ):
            self.assertEqual(ep.get_providers_with_capability("text_chat"), [])


if __name__ == "__main__":
    unittest.main()
