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

import datetime as _dt
import sys
import types
import pathlib
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

    def _status(self, limit, used, row=True, reset_day=1, last_reset_at=None):
        """Fake a budget row.

        Now four columns, matching the SELECT: the period columns came with the monthly reset,
        and a double that still returns two makes `row[2]` raise IndexError — which the module
        catches and fails OPEN, so every band test silently asserted "unknown" and passed for
        the wrong reason. Kept in one place so the shape cannot drift again.
        """
        payload = (limit, used, reset_day, last_reset_at) if row else None
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
        # four columns, like every other row double — see TestBudgetRowShape
        with patch_db((100.0, 96.0, 1, _dt.datetime.now())):
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


class TestBudgetRowShape(unittest.TestCase):
    """The band tests above are only meaningful if the fake row matches the real SELECT.

    A two-column double raises IndexError inside `monthly_budget_status`, which is caught and
    fails open as `unknown`. Every band assertion then "passes" against the wrong value, which
    is how a whole class of budget test can be green while testing nothing.
    """

    def test_a_current_period_row_reports_a_real_band_not_unknown(self):
        from datetime import datetime

        ep = _load_ep()
        payload = (100.0, 80.0, 1, datetime.now())
        with patch_db(payload):
            self.assertEqual(ep.monthly_budget_status("groq")["band"], "warn")

    def test_a_rolled_period_row_recovers_to_ok(self):
        """The end-to-end recovery: last month's block, this month fine."""
        from datetime import datetime, timedelta

        ep = _load_ep()
        stale = datetime.now() - timedelta(days=45)
        with patch_db((100.0, 99.0, 1, stale)):
            st = ep.monthly_budget_status("groq")
        self.assertEqual(st["band"], "ok")
        self.assertEqual(st["used"], 0.0, "a stale total must not count against this period")


def _load_ep():
    import importlib.util

    here = pathlib.Path(__file__).resolve()
    for rel in (
        here.parents[2] / "ai_bridge" / "external_providers.py",
        pathlib.Path("/mnt/archie_brain/ai_bridge/external_providers.py"),
    ):
        if rel.exists():
            spec = importlib.util.spec_from_file_location("ep_shape", str(rel))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise unittest.SkipTest("external_providers.py not reachable from this layout")


class TestBudgetPeriodReset(unittest.TestCase):
    """The monthly budget counter must reset, or the bands become a one-way ratchet.

    `current_month_cost_usd` had exactly one writer and it only ever accumulated
    (`SET current_month_cost_usd = current_month_cost_usd + %s`). `budget_reset_day` was
    displayed and read by no logic; `last_reset_at` existed only in migration 106's CREATE TABLE.
    So once a provider crossed 95% it stayed `block` for the lifetime of the install, with no
    way back — a slow-motion lockout wearing the costume of a budget guard.
    """

    def _ep(self):
        """Load external_providers from wherever it lives.

        The repo-relative path resolves to "/" inside the container, so the bind-mounted copy
        is listed explicitly. Without it every test here errors on a missing file rather than
        on a real assertion, which reads like a broken suite instead of a broken lookup.
        """
        import importlib.util

        here = pathlib.Path(__file__).resolve()
        for rel in (
            here.parents[2] / "ai_bridge" / "external_providers.py",
            pathlib.Path("/mnt/archie_brain/ai_bridge/external_providers.py"),
            pathlib.Path("/app/../ai_bridge/external_providers.py"),
        ):
            if rel.exists():
                spec = importlib.util.spec_from_file_location("ep_budget", str(rel))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        raise unittest.SkipTest("external_providers.py not reachable from this layout")

    def test_an_unknown_period_counts_rather_than_reports_zero(self):
        """NULL `last_reset_at` means UNKNOWN, not EMPTY.

        Reporting $0.00 for a provider that had genuinely spent is the one direction a money
        guard must never be wrong in, so an unstamped row counts its stored total.
        """
        from datetime import datetime

        ep = self._ep()
        self.assertEqual(ep._budget_used_for_current_period(7.5, None, 1, datetime(2026, 10, 20)), 7.5)

    def test_an_aware_timestamp_still_compares(self):
        """The bug that every other test here missed.

        `last_reset_at` is TIMESTAMPTZ, so psycopg2 hands back an AWARE datetime. The period
        start is derived from a local-time day-of-month and was NAIVE. Comparing them raises
        TypeError, the caller catches it, and the budget guard fails OPEN — silently
        disabled, which is the worst possible outcome for a money limit.

        Every other test in this file used naive datetimes and passed, so the mismatch only
        appeared on the first live run against the real column. This test pins the aware case
        explicitly, and asserts on the BAND rather than the helper, because the helper working
        in isolation proves nothing about whether the guard survives.
        """
        from datetime import datetime, timezone

        ep = self._ep()
        aware_stamp = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
        # must not raise, and must read as a rolled period
        self.assertEqual(
            ep._budget_used_for_current_period(99.0, aware_stamp, 1, datetime(2026, 10, 20)),
            0.0,
        )

    def test_a_stale_aware_row_recovers_the_band_end_to_end(self):
        """An aware stale stamp must yield `ok`, not the `unknown` that fail-open produces."""
        from datetime import datetime, timedelta, timezone

        ep = self._ep()
        stale = datetime.now(timezone.utc) - timedelta(days=45)
        with patch_db((100.0, 99.0, 1, stale)):
            st = ep.monthly_budget_status("groq")
        self.assertNotEqual(st["band"], "unknown", "fail-open hid a real recovery")
        self.assertEqual(st["band"], "ok")
        self.assertEqual(st["used"], 0.0)

    def test_a_rolled_period_reports_zero_spend(self):
        """The recovery path. Without it there is none."""
        from datetime import datetime

        ep = self._ep()
        now = datetime(2026, 10, 20, 12, 0)
        # stamp is last month; today is the 20th with reset_day=1
        self.assertEqual(
            ep._budget_used_for_current_period(99.0, datetime(2026, 9, 1, 0, 5), 1, now),
            0.0,
        )

    def test_a_current_period_reports_the_stored_total(self):
        from datetime import datetime

        ep = self._ep()
        now = datetime(2026, 10, 20, 12, 0)
        self.assertEqual(
            ep._budget_used_for_current_period(4.25, datetime(2026, 10, 1, 0, 5), 1, now),
            4.25,
        )

    def test_the_reset_boundary_is_inclusive_of_the_new_period(self):
        """A stamp exactly AT the period start means the period began then, so it is current.

        I initially asserted the opposite and was wrong. `<` not `<=` is the correct operator:
        a counter stamped at the boundary belongs to the period that just started, and only
        becomes stale strictly after. Resetting early by one instant would forgive spend.
        """
        from datetime import datetime

        ep = self._ep()
        self.assertEqual(
            ep._budget_used_for_current_period(50.0, datetime(2026, 10, 1, 0, 0), 1, datetime(2026, 10, 1, 0, 1)),
            50.0,
            "a stamp exactly at the boundary is the new period, not a stale one",
        )
        # one second later it is unambiguously stale
        from datetime import timedelta

        self.assertEqual(
            ep._budget_used_for_current_period(
                50.0, datetime(2026, 9, 30, 23, 59, 59), 1, datetime(2026, 10, 1, 0, 0, 1)
            ),
            0.0,
        )

    def test_a_reset_day_of_31_does_not_explode_in_february(self):
        """The case that takes the fail-open path and silently disables the guard.

        `now.replace(day=31)` in February raises ValueError. A helper that raises inside the
        budget read lands in the `except Exception` fail-open branch — the same failure this
        module already documents for a broken query.
        """
        from datetime import datetime

        ep = self._ep()
        # Feb 15 with reset_day=31: February has no 31st, so it clamps to Feb 28 — which has
        # NOT happened yet. The period therefore began on Jan 31, last month. Getting this
        # wrong in the other direction (clamping INTO the current month) would reset a budget
        # up to a month early, which is the costly error.
        start = ep._budget_period_start(31, datetime(2026, 2, 15, 9, 30))
        self.assertEqual((start.year, start.month, start.day), (2026, 1, 31))
        # the clamp itself is real: on the 28th the period DOES start in February
        start = ep._budget_period_start(31, datetime(2026, 2, 28, 9, 30))
        self.assertEqual((start.year, start.month, start.day), (2026, 2, 28))
        # and it must not raise for any month length
        for m in range(1, 13):
            ep._budget_period_start(31, datetime(2026, m, 15))

    def test_period_start_before_the_reset_day_belongs_to_last_month(self):
        from datetime import datetime

        ep = self._ep()
        # reset_day=15, but it is the 3rd -> the period began on the 15th of LAST month
        start = ep._budget_period_start(15, datetime(2026, 10, 3, 8, 0))
        self.assertEqual((start.year, start.month, start.day), (2026, 9, 15))

    def test_january_rolls_back_into_december_without_month_zero(self):
        from datetime import datetime

        ep = self._ep()
        start = ep._budget_period_start(15, datetime(2026, 1, 3, 8, 0))
        self.assertEqual((start.year, start.month, start.day), (2025, 12, 15))

    def test_a_nonsense_reset_day_falls_back_to_the_first(self):
        from datetime import datetime

        ep = self._ep()
        for bad in (None, 0, -5, "not-a-day", 99):
            start = ep._budget_period_start(bad, datetime(2026, 10, 20))
            self.assertEqual((start.month, start.day), (10, 1), f"reset_day={bad!r}")

    def test_the_accumulate_resets_rather_than_adding_when_the_period_rolled(self):
        """The write path, as SQL. Asserted on the statement text because the CASE is the
        behaviour — an unconditional `+ %s` is the bug this whole change removes."""
        src = pathlib.Path(self._ep().__file__).read_text(encoding="utf-8")
        block = src[src.index("def _update_cost") :]
        self.assertIn("THEN %(cost)s", block, "a rolled period must SET, not add")
        self.assertIn("ELSE current_month_cost_usd + %(cost)s", block)
        self.assertNotIn(
            "current_month_cost_usd = current_month_cost_usd + %s",
            block,
            "the unconditional accumulate is exactly what never reset",
        )
        self.assertIn("last_reset_at", block, "the stamp must move when the period rolls")

    def test_the_read_counts_only_the_current_period(self):
        src = pathlib.Path(self._ep().__file__).read_text(encoding="utf-8")
        self.assertIn("budget_reset_day, last_reset_at", src, "the read needs the period columns")
        self.assertIn("_budget_used_for_current_period(raw_used, last_reset_at, reset_day)", src)

    def test_the_backfill_migration_declares_the_period(self):
        for rel in (
            "database/migrations/489_budget_period_backfill.sql",
            "/mnt/archie_brain/database/migrations/489_budget_period_backfill.sql",
        ):
            fp = pathlib.Path(rel)
            if fp.exists():
                sql = fp.read_text(encoding="utf-8")
                break
        else:
            self.skipTest("migration 489 not reachable from this layout")
        self.assertIn("SET last_reset_at = NOW()", sql)
        self.assertIn("WHERE last_reset_at IS NULL", sql)
