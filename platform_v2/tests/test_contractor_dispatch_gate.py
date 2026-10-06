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
import re
import unittest
from unittest import mock

sys.path.insert(0, "/app")

import ai_bridge.external_providers as ep  # noqa: E402

#: Where the repo's own tree is visible from inside the platform container.
#:
#: NOT /app. `/app` is `platform_v2` (plus a build-time `database/` package with 80 migrations of
#: its own), so `/app/database/migrations/490_...` does not exist and a lookup there fails for a
#: reason that has nothing to do with the file being wrong. The repo's 411-migration
#: `database/` tree is mounted at its real path.
_REPO_ROOTS = (
    pathlib.Path(__file__).resolve().parents[2],
    pathlib.Path("/mnt/archie_brain"),
)


def _repo_file(rel: str) -> pathlib.Path:
    """First existing candidate for a repo-relative file, or the last guess for a clear error."""
    candidates = [root / rel for root in _REPO_ROOTS]
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


MIGRATION_490 = "database/migrations/490_budget_warn_once.sql"


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


class TestWarnOncePerPeriod(unittest.TestCase):
    """A crossing is an EVENT; being at 85% is a STATE.

    `monthly_budget_status` has returned `warn` at >= 80% since migration 106, and nothing ever
    read it. #3661 made the band recoverable, which made the missing half of the feature visible:
    the obvious way to surface a warn is to notify, and the obvious notification re-announces the
    same provider on every dispatch for the rest of the month. One crossing, hundreds of alerts.

    So the notification is claimed atomically in `_update_cost`, once per budget period.
    """

    # ------------------------------------------------------------------ #
    # the claim statement
    # ------------------------------------------------------------------ #

    def test_the_claim_is_scoped_to_the_current_period(self):
        """The whole mechanism. A stamp from last month must not silence this month."""
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        self.assertIn("budget_warned_at IS NULL OR budget_warned_at < %(period)s", src)

    def test_null_counts_as_never_warned(self):
        """A provider that crossed 80% with no prior stamp MUST be announced.

        Treating NULL as 'already warned' would silently swallow the first, and often only,
        crossing of a provider's month.
        """
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        self.assertIn("budget_warned_at IS NULL", src)

    def test_the_claim_and_the_increment_share_one_transaction(self):
        """Two dispatches can cross 80% in the same instant.

        If the claim commits separately, both can read 'not warned yet' and both notify — which is
        the bug being fixed, just arriving faster. One transaction, one winner.
        """
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        body = src[src.index("def _update_cost(") : src.index("def _log_usage(")]
        self.assertLess(
            body.index("SET budget_warned_at = NOW()"),
            body.index("conn.commit()"),
            "the claim must commit with the increment, not after it",
        )
        self.assertEqual(body.count("conn.commit()"), 1, "one transaction, one commit")

    def test_only_the_winner_notifies(self):
        """The notify is gated on the claim returning a row."""
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        body = src[src.index("def _update_cost(") : src.index("def _log_usage(")]
        self.assertIn("if claimed:", body)
        self.assertIn("_notify_budget_warn(provider", body.split("if claimed:")[1])

    def test_the_claim_thresholds_on_the_warn_band_not_the_block_band(self):
        """95% blocks traffic on its own — the gate does that, loudly, every time. The
        notification exists for the 80% band that blocks nothing."""
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        self.assertIn("limit * BUDGET_WARN_FRACTION", src)
        body = src[src.index("def _warn_threshold_for(") : src.index("def _notify_budget_warn(")]
        self.assertNotIn("BUDGET_BLOCK_FRACTION", body)

    def test_the_period_roll_does_not_clear_the_stamp(self):
        """One mechanism, not two that can disagree.

        The comparison against `period_start` already resets the warning. Clearing the column in
        the roll as well would be redundant, and if the two ever disagreed about whether a period
        rolled, the provider would either warn twice or never warn at all.
        """
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        roll = src[src.index("last_reset_at = CASE") : src.index("updated_at = NOW()")]
        self.assertNotIn("budget_warned_at", roll, "the comparison is the reset; do not clear")

    def test_the_migration_adds_exactly_the_column_the_code_writes(self):
        """The two can drift apart silently, and nothing else would notice.

        A migration that adds `budget_warn_notified_at` while the code writes
        `budget_warned_at` still applies cleanly, still lints, and still passes every other test
        here. It fails at runtime, on the first provider that crosses 80%, as an undefined column.
        """
        mig = _repo_file(MIGRATION_490).read_text(encoding="utf-8")
        code = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        added = re.search(r"ADD COLUMN IF NOT EXISTS\s+(\w+)", mig)
        self.assertIsNotNone(added, "migration 490 must add a column")
        self.assertEqual(
            added.group(1),
            "budget_warned_at",
            "migration and code disagree on the column name",
        )
        self.assertIn(added.group(1) + " = NOW()", code)

    def test_the_migration_backfills_nothing(self):
        """Backfilling from last_reset_at would mean "already warned about a crossing we never
        announced" — silencing the next real crossing."""
        mig = _repo_file(MIGRATION_490).read_text(encoding="utf-8")
        self.assertNotIn("UPDATE ", mig)
        self.assertIn("Backfill: deliberately NONE", mig)

    # ------------------------------------------------------------------ #
    # the threshold read
    # ------------------------------------------------------------------ #

    def test_no_budget_row_means_no_warning_ever(self):
        """There is no limit to be near, so there is nothing to announce."""
        self.assertEqual(ep._warn_threshold_for.__doc__ is not None, True)
        with mock.patch.dict(sys.modules, {"database": _db_with_limit(None)}):
            limit, threshold = ep._warn_threshold_for("nobody")
        self.assertEqual(limit, float("inf"))
        self.assertEqual(threshold, float("inf"))

    def test_a_zero_or_negative_limit_means_no_warning(self):
        with mock.patch.dict(sys.modules, {"database": _db_with_limit(0)}):
            self.assertEqual(ep._warn_threshold_for("p")[0], float("inf"))
        with mock.patch.dict(sys.modules, {"database": _db_with_limit(-5)}):
            self.assertEqual(ep._warn_threshold_for("p")[0], float("inf"))

    def test_a_real_limit_produces_the_80_percent_threshold(self):
        with mock.patch.dict(sys.modules, {"database": _db_with_limit(10.0)}):
            limit, threshold = ep._warn_threshold_for("cohere")
        self.assertEqual(limit, 10.0)
        self.assertAlmostEqual(threshold, 8.0)

    def test_a_broken_threshold_read_skills_the_warning_rather_than_raising(self):
        """A dispatch must not fail because the warning could not be computed."""
        with mock.patch.dict(sys.modules, {"database": _db_that_raises()}):
            self.assertEqual(ep._warn_threshold_for("p"), (float("inf"), float("inf")))

    # ------------------------------------------------------------------ #
    # the notification itself
    # ------------------------------------------------------------------ #

    def test_a_failed_notification_is_logged_not_raised(self):
        """Observability must never break the dispatch that paid for it."""
        with mock.patch.object(ep, "logger") as log:
            with mock.patch.dict(sys.modules, {"database": _db_that_raises_on_insert()}):
                ep._notify_budget_warn("cohere", 8.5, 10.0)  # must not raise
            self.assertTrue(log.warning.called)

    def test_the_notification_says_traffic_is_still_allowed(self):
        """An operator reading an 80% warning should not think requests are already being
        refused — they are not, until 95%."""
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        self.assertIn("Traffic is still allowed", src)

    def test_the_notification_is_announced_once_per_period(self):
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        self.assertIn("Announced once per budget period.", src)

    def test_no_telegram_forward_on_a_budget_warning(self):
        """These are informational. Paging the owner about a provider hitting 80% would train
        them to ignore budget warnings, which is worse than not sending them.

        Checks the params tuple by shape rather than by a bare substring: the earlier version
        asserted `"True,"` appears somewhere near the INSERT, which proved nothing about which
        column that value belonged to.
        """
        src = pathlib.Path(ep.__file__).read_text(encoding="utf-8")
        block = src[src.index("def _notify_budget_warn(") : src.index("def _update_cost(")]
        m = re.search(r'\(\s*"budget_warning".*?"high",\s*(\w+),', block, re.S)
        self.assertIsNotNone(m, "could not locate the INSERT parameter tuple")
        # The INSERT lists 7 columns and this is the 7th value: telegram_forwarded. Capturing the
        # value that FOLLOWS the priority is what makes the claim specific — asserting `"True,"`
        # appears nearby proved nothing about which column it belonged to.
        self.assertEqual(m.group(1), "True", "telegram_forwarded must be True so the daemon skips it")


def _db_with_limit(limit):
    """A fake `database` module whose get_db_cursor yields one budget row."""
    row = {"monthly_budget_usd": limit}

    class _Cur:
        def __enter__(self):
            return None, self

        def __exit__(self, *_a):
            return False

        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return row

    module = types.ModuleType("database")
    module.get_db_cursor = lambda commit=False: _Cur()
    return module


def _db_that_raises():
    module = types.ModuleType("database")

    def _boom(*_a, **_k):
        raise RuntimeError("db down")

    module.get_db_cursor = _boom
    return module


def _db_that_raises_on_insert():
    module = types.ModuleType("database")

    class _Cur:
        def __enter__(self):
            return None, self

        def __exit__(self, *_a):
            return False

        def execute(self, *_a, **_k):
            raise RuntimeError("insert failed")

    module.get_db_cursor = lambda commit=False: _Cur()
    return module


class TestOmniRouteCostClass(unittest.TestCase):
    """A row must not claim to be free when its own gateway asks for payment.

    Five contractor rows share one OmniRoute gateway with different `auto/*` aliases. A
    verification pass found the gateway UP (HTTP 200, 540 models) and every configured alias
    present — so the failures are upstream model availability, not stale configuration, and
    nothing should be retired. But two rows were labelled `free_tier` while the gateway answered
    `402 "This model requires an opencode API key"`. `omniroute_coding_free` is the sharpest: the
    alias literally says `:free`.
    """

    MIGRATION_492 = "database/migrations/492_omniroute_paid_reclassification.sql"
    REPO_ROOTS = (
        pathlib.Path(__file__).resolve().parents[2],
        pathlib.Path("/mnt/archie_brain"),
    )

    def _sql(self) -> str:
        for root in self.REPO_ROOTS:
            cand = root / self.MIGRATION_492
            if cand.exists():
                return cand.read_text(encoding="utf-8")
        self.fail(f"could not locate {self.MIGRATION_492}")

    def test_it_reclassifies_exactly_the_two_that_402(self):
        sql = self._sql()
        block = sql[sql.index("targets text[]") : sql.index("];", sql.index("targets text[]"))]
        targets = set(re.findall(r"'([a-z0-9_]+)'", block))
        self.assertEqual(targets, {"omniroute_coding", "omniroute_coding_free"}, targets)

    def test_it_leaves_the_three_free_rows_alone(self):
        """`omniroute` is genuinely free but client-restricted; `best_free` and `reasoning` fail
        on upstream availability, not cost. Neither is a known-false free claim."""
        sql = self._sql()
        for keep in ("omniroute_best_free", "omniroute_reasoning"):
            self.assertNotIn(f"'{keep}'", sql.split("targets text[]")[1].split("];")[0])

    def test_it_writes_paid(self):
        """Not just WHICH rows — the value.

        A mutation turning the target back to 'free_tier' left every other test green: the list was
        still the right two, the guard was still there, the evidence was still quoted. Only the
        correction itself would have silently not happened.
        """
        sql = self._sql()
        self.assertIn("SET provider_class = 'paid'", sql)
        self.assertNotIn("SET provider_class = 'free_tier'", sql)

    def test_it_deletes_nothing(self):
        """Retiring a row whose alias is valid, because the model behind it is unavailable this
        afternoon, is the same category error as deleting a provider that is merely down."""
        self.assertNotIn("DELETE", self._sql().upper())

    def test_the_guard_only_rewrites_free_tier(self):
        """So a hand correction is not stomped, and a re-run is a no-op."""
        self.assertIn("AND provider_class = 'free_tier'", self._sql())

    def test_it_records_why_paid_is_operator_assigned(self):
        """`classify_provider_class` deliberately cannot return paid — a probe sees a 402 but
        cannot prove the price behind it. This file is that operator decision, so the reasoning
        must travel with it."""
        self.assertIn("classify_provider_class", self._sql())

    def test_the_evidence_is_quoted(self):
        self.assertIn("requires an opencode API key", self._sql())

    def test_the_classifier_still_cannot_infer_paid(self):
        """If this ever changes, the migration stops being an operator decision and becomes a
        guess — which is what #3651 removed."""
        import ai_bridge.external_providers  # noqa: F401
        from services.contractor_health_service import classify_provider_class

        for status in ("error", "unreachable", "rate_limited", "auth_error", "no_key", "ok"):
            with mock.patch.dict(sys.modules, {"database": types.ModuleType("database")}):
                got = classify_provider_class(has_key=True, status=status)
            self.assertNotEqual(got, "paid", f"status {status} must not infer paid")
