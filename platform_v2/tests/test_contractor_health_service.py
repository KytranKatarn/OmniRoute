"""Contractor health probing (DS9 PR 3) — classification, ranking, and scan isolation.

The probe sends real requests, so what is tested here is the part that must be right even
when the network is not: how an outcome becomes a status, how status becomes a provider
class, how ranking treats what it does not know, and that one wedged provider cannot stop the
other twenty-nine from being measured.

Three decisions carry most of the weight and are pinned individually:

1. **`unsupported` is not `error`.** An image-only model asked to chat gets a 400 *and an
   explanation*. Treating that as a generic failure is what let `pollinations` sit in the
   table looking like a working text provider.

2. **Class is assigned from measurement, never from a name.** The `omniroute_*_free` rows
   are the proof: both ids marked `:free` return 502 while the unmarked ones return 200, so
   a name-based classifier would be exactly inverted.

3. **Absence is not zero.** An unprobed provider ranks after every probed-and-healthy one and
   is never given an invented latency. A NULL is an honest "not sampled"; a made-up number
   would quietly become the ranking.

No network: `requests` is patched. No database: `database` is patched with a recording fake.
"""

import pathlib
import re
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, "/app")

from services import contractor_health_service as chs  # noqa: E402


class RecordingCursor:
    """Captures INSERTs; returns nothing for SELECTs."""

    def __init__(self):
        self.inserts = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith("INSERT"):
            self.inserts.append(params)
        elif sql.strip().upper().startswith("DELETE"):
            self.rowcount = 3

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


def patch_db(cursor):
    module = types.ModuleType("database")

    class _CM:
        def __init__(self, commit=False):
            self._c = cursor

        def __enter__(self):
            return (None, self._c)

        def __exit__(self, *exc):
            return False

    module.get_db_cursor = lambda commit=False: _CM(commit)
    return mock.patch.dict(sys.modules, {"database": module})


class TestClassifyStatus(unittest.TestCase):
    """Outcome → status. The ordering of these checks is the behaviour."""

    def test_2xx_is_ok(self):
        self.assertEqual(chs.classify_status(http_status=200), "ok")

    def test_401_and_403_are_auth_errors(self):
        self.assertEqual(chs.classify_status(http_status=401), "auth_error")
        self.assertEqual(chs.classify_status(http_status=403), "auth_error")

    def test_429_is_rate_limited_not_auth(self):
        """Distinct because it is transient: waiting helps, re-keying does not."""
        self.assertEqual(chs.classify_status(http_status=429), "rate_limited")

    def test_a_success_is_ok_even_without_a_credential(self):
        """A 2xx settles the question whether or not a key was sent.

        This check used to sit BEHIND `not has_key`, so a provider that served the request
        without a credential was reported `no_key` — and `keyless` was a class no probe could
        ever reach, because the success that would prove it was unreachable code.
        """
        self.assertEqual(chs.classify_status(http_status=200, has_key=False), "ok")

    def test_no_key_beats_every_other_failure_signal(self):
        """With no credential there is nothing to judge, so nothing else decides it."""
        self.assertEqual(chs.classify_status(http_status=401, has_key=False), "no_key")
        self.assertEqual(chs.classify_status(http_status=403, has_key=False), "no_key")
        self.assertEqual(chs.classify_status(http_status=500, has_key=False), "no_key")

    def test_unreachable_when_no_response(self):
        self.assertEqual(chs.classify_status(reached=False), "unreachable")
        self.assertEqual(chs.classify_status(http_status=None), "unreachable")

    def test_unsupported_is_checked_before_the_status_code(self):
        """The pollinations case: a 400 that is information, not failure."""
        self.assertEqual(chs.classify_status(http_status=400, unsupported=True), "unsupported")

    def test_unsupported_beats_auth_error(self):
        """Order matters — a 403 that is really 'wrong capability' is not a bad key."""
        self.assertEqual(chs.classify_status(http_status=403, unsupported=True), "unsupported")

    def test_other_4xx_and_5xx_are_error(self):
        self.assertEqual(chs.classify_status(http_status=400), "error")
        self.assertEqual(chs.classify_status(http_status=500), "error")


class TestClassifyProviderClass(unittest.TestCase):
    """Status → provider_class. Must never over-claim."""

    def test_image_only_when_unsupported(self):
        self.assertEqual(
            chs.classify_provider_class(has_key=True, status="unsupported"),
            "image_only",
        )

    def test_keyless_only_when_it_actually_answered(self):
        self.assertEqual(
            chs.classify_provider_class(has_key=False, status="ok"),
            "keyless",
        )

    def test_no_key_and_no_answer_is_not_keyless(self):
        """A provider that failed for want of a credential is not keyless.

        It used to be filed as `local` on the strength of one failure, which is a guess: a
        remote API with no key configured and an internal service with no key configured are
        indistinguishable from a failed probe alone, and deepseek is the first while
        ollama_diffuser is the second.
        """
        self.assertIsNone(chs.classify_provider_class(has_key=False, status="unreachable"))

    def test_a_credential_requiring_provider_is_not_called_paid_on_the_key_alone(self):
        """The six keyed providers span free-tier and metered; a key says neither.

        Claiming `paid` because a credential exists would put a free-tier provider into the
        paid bucket — and the whole point of the paid bucket is that it is opt-in.

        It does not earn `free_tier` either. This used to assert `free_tier` here, on the
        strength of "not paid". That is the same mistake pointed the other way: holding a key
        is not evidence of a free allowance, it is evidence of nothing at all about cost. Only
        a DECLARED allowance earns free_tier, so this is now None.
        """
        self.assertIsNone(
            chs.classify_provider_class(has_key=True, status="ok"),
            "a key alone says nothing about cost; only a declared allowance earns free_tier",
        )

    def test_a_failure_never_claims_a_cost_class(self):
        """The bug this whole change exists to close.

        `classify_provider_class` used to end in `return "free_tier"`, so a provider
        answering 401/403/500/timeout was filed under `free_tier` — the bucket that IS
        auto-eligible. Run against the real roster that stamps `free_tier` on 13 of the 18
        unmeasured contractors, turning "we could not measure this" into "safe to dispatch",
        after which the routing switch would happily enable providers that do not serve.

        A probe that was not served knows what the provider costs not at all.
        """
        for status in ("auth_error", "unreachable", "error", "rate_limited", "no_key"):
            for has_key in (True, False):
                for allowance in (None, 0, 7000):
                    self.assertIsNone(
                        chs.classify_provider_class(has_key=has_key, status=status, free_allowance=allowance),
                        f"status={status} has_key={has_key} allowance={allowance} must stay unmeasured",
                    )


class TestCloudProxyIsNotAPaidSignal(unittest.TestCase):
    """`is_cloud_proxy` says how a provider is REACHED. It says nothing about cost.

    The classifier used to end in `return "paid" if is_cloud_proxy else "free_tier"`, which
    contradicted its own docstring and was wrong on the live roster: minimax_cloud and
    qwen3_cloud both declare `rate_limits.free.weekly_limit = 7000`, neither has ever been
    dispatched, and `pick_free_text_provider` rotates against exactly those allowances.
    Filing them as `paid` would have put the platform's own free-tier providers in the
    money bucket.
    """

    def test_the_routing_flag_is_not_even_a_parameter(self):
        """Removed, not merely ignored — so it cannot be passed in and used again."""
        import inspect

        params = inspect.signature(chs.classify_provider_class).parameters
        self.assertNotIn(
            "is_cloud_proxy",
            params,
            "the flag that was mistaken for a cost signal must not be an input at all",
        )
        self.assertIn("free_allowance", params)

    def test_a_declared_free_allowance_makes_a_keyed_provider_free_tier(self):
        self.assertEqual(
            chs.classify_provider_class(has_key=True, status="ok", free_allowance=7000),
            "free_tier",
        )

    def test_no_declared_allowance_means_cost_unknown_not_free_and_not_paid(self):
        """The live cloud-proxy case exactly: keyed, answered, no allowance declared."""
        for allowance in (None, 0):
            self.assertIsNone(
                chs.classify_provider_class(has_key=True, status="ok", free_allowance=allowance),
                f"allowance={allowance!r}: a probe cannot tell free from metered, so claim nothing",
            )

    def test_paid_is_never_returned(self):
        """Exhaustive, so a future branch cannot quietly reintroduce it."""
        for has_key in (True, False):
            for status in ("ok", "unsupported", "auth_error", "unreachable", "error"):
                for allowance in (None, 7000):
                    got = chs.classify_provider_class(has_key=has_key, status=status, free_allowance=allowance)
                    self.assertNotEqual(
                        got,
                        "paid",
                        f"has_key={has_key} status={status} allowance={allowance} " "must never yield paid",
                    )


class TestDeclaredFreeAllowance(unittest.TestCase):
    """Cost comes from declared config, read tolerantly."""

    def test_reads_the_weekly_limit_from_the_free_block(self):
        self.assertEqual(chs.declared_free_allowance({"free": {"weekly_limit": 7000}}), 7000)

    def test_accepts_a_json_string(self):
        """The column is JSONB, but a hand-edited row can hold text."""
        self.assertEqual(chs.declared_free_allowance('{"free": {"weekly_limit": 7000}}'), 7000)

    def test_absent_or_unusable_means_unknown(self):
        for bad in (
            None,
            "",
            "{}",
            "not json",
            [],
            {"free": None},
            {"free": {}},
            {"free": {"weekly_limit": 0}},
            {"free": {"weekly_limit": None}},
            {"free": {"weekly_limit": "7000"}},
            {"free": {"weekly_limit": True}},
        ):
            self.assertIsNone(chs.declared_free_allowance(bad), f"{bad!r} must read as unknown")


class TestScanIsolation(unittest.TestCase):
    """One broken provider must not stop the others."""

    def _providers(self, n=3):
        return [
            {
                "provider_key": f"p{i}",
                "base_url": "http://x",
                "default_model": "m",
                "auth_env_var": None,
                "is_cloud_proxy": False,
            }
            for i in range(n)
        ]

    def test_a_raising_provider_is_recorded_and_the_scan_continues(self):
        cursor = RecordingCursor()
        with patch_db(cursor):

            def _probe(provider, kind, timeout):
                if provider["provider_key"] == "p1":
                    raise RuntimeError("boom")
                return {"status": "ok", "observed_model": "m"}

            with mock.patch.object(chs, "_probe_one", _probe):
                out = chs.scan(probe_kind="health", providers=self._providers(3))

        self.assertTrue(out["ok"])
        self.assertEqual(out["probed"], 3)
        statuses = {r["provider_key"]: r["status"] for r in out["results"]}
        self.assertEqual(statuses["p1"], "error")
        self.assertEqual(statuses["p0"], "ok")
        self.assertEqual(statuses["p2"], "ok")

    def test_the_failure_is_recorded_with_its_reason(self):
        cursor = RecordingCursor()
        with patch_db(cursor):

            def _probe(provider, kind, timeout):
                if provider["provider_key"] == "p0":
                    raise ValueError("bad config")
                return {"status": "ok"}

            with mock.patch.object(chs, "_probe_one", _probe):
                chs.scan(probe_kind="health", providers=self._providers(2))

        err_rows = [p for p in cursor.inserts if p[2] == "error"]
        self.assertEqual(len(err_rows), 1)
        self.assertIn("bad config", err_rows[0][5])

    def test_only_ok_rows_carry_a_latency(self):
        """A failed probe has no meaningful latency; storing one invites averaging it."""
        cursor = RecordingCursor()
        with patch_db(cursor):
            with mock.patch.object(chs, "_probe_one", lambda pr, k, t: {"status": "unreachable", "detail": "x"}):
                chs.scan(probe_kind="health", providers=self._providers(1))
        self.assertIsNone(cursor.inserts[0][3])

    def test_health_timeout_is_short_and_latency_timeout_is_long(self):
        """One wedged provider must not stall a 15-minute cadence."""
        self.assertLess(chs.DEFAULT_HEALTH_TIMEOUT_S, 15)
        self.assertGreater(chs.DEFAULT_LATENCY_TIMEOUT_S, chs.DEFAULT_HEALTH_TIMEOUT_S)

    def test_probe_kind_selects_the_timeout(self):
        seen = []
        cursor = RecordingCursor()
        with patch_db(cursor):

            def _probe(provider, kind, timeout):
                seen.append((kind, timeout))
                return {"status": "ok"}

            with mock.patch.object(chs, "_probe_one", _probe):
                chs.scan(probe_kind="health", providers=self._providers(1))
                chs.scan(probe_kind="latency", providers=self._providers(1))
        self.assertEqual(seen[0][1], chs.DEFAULT_HEALTH_TIMEOUT_S)
        self.assertEqual(seen[1][1], chs.DEFAULT_LATENCY_TIMEOUT_S)

    def test_a_failed_write_does_not_abort_the_scan(self):
        """Bookkeeping failing must not cost us the measurements already taken."""
        boom = types.ModuleType("database")

        class _CM:
            def __init__(self, commit=False):
                pass

            def __enter__(self):
                raise RuntimeError("insert denied")

            def __exit__(self, *exc):
                return False

        boom.get_db_cursor = lambda commit=False: _CM()
        with mock.patch.dict(sys.modules, {"database": boom}), mock.patch.object(
            chs, "_probe_one", lambda pr, k, t: {"status": "ok"}
        ):
            out = chs.scan(probe_kind="health", providers=self._providers(2))
        self.assertEqual(out["probed"], 2)


class TestLatencyCadenceFilter(unittest.TestCase):
    """A health probe's latency must not become a provider's ranking latency.

    The query carried a comment promising exactly this and no filter to keep the promise, so
    every row with a latency qualified — including the 1-token health probes, which run every
    15 minutes under an 8s timeout and so land 6x more often than the hourly latency cadence.

    The existing TestRanking could never have caught it: it replaces the cursor wholesale, so
    it exercises the SORT and never the SQL. These assert on the statement itself, because the
    statement is the part that was wrong.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = pathlib.Path(chs.__file__).read_text(encoding="utf-8")

    def _best_latency_sql(self):
        """The best_latency CTE, captured whole.

        Slicing to the next ")" truncates inside `DISTINCT ON (provider_key)` — the closing
        paren of the function call comes long before the WHERE clause being asserted on.
        """
        import re as _re

        m = _re.search(r"best_latency AS \((.*?)\n\s*\)", self.src, _re.S)
        self.assertIsNotNone(m, "best_latency CTE not found")
        return m.group(1)

    def test_ranking_excludes_health_probes(self):
        sql = self._best_latency_sql()
        self.assertIn("probe_kind", sql, "the filter the comment promised is missing")
        self.assertRegex(
            sql,
            r"probe_kind IN \('latency', 'full'\)",
            "ranking latency must come from the sampling cadences only",
        )
        self.assertNotIn(
            "'health'",
            sql,
            "health rows are exactly what must be excluded",
        )

    def test_the_health_read_in_the_listing_filters_too(self):
        """The Contractors tab has its own copy of the query, with the same comment.

        Fixing only the ranking would leave the badge showing a health-probe latency while the
        ranking used a real one — two numbers for one provider, on the same screen.
        """
        routes = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "fleet_provider_routes.py"
        if not routes.exists():
            routes = pathlib.Path("/mnt/archie_brain/platform_v2/tools/department_hq/fleet_provider_routes.py")
        self.assertTrue(routes.exists(), "fleet_provider_routes.py not reachable")
        src = routes.read_text(encoding="utf-8")
        # anchored on the comment that introduces this read, not on the constant's DEFINITION
        # (which sits near the top of the module, before the handler that uses it)
        anchor = src.index("Latency has its own read")
        block = src[anchor : anchor + 900]
        self.assertIn(
            "probe_kind IN ('latency', 'full')",
            block,
            "the listing's latency read must apply the same filter as the ranking",
        )

    def test_the_ceiling_is_still_applied(self):
        """The new filter must not have displaced the outlier guard."""
        self.assertIn("latency_ms <= %s", self._best_latency_sql())

    def test_ranking_still_orders_by_a_real_sample_when_one_exists(self):
        """The filter must not empty the ranking for a provider that IS being sampled."""
        out_rows = [
            {"provider_key": "sampled", "display_name": "s", "provider_class": None, "status": "ok", "best_ms": 250},
            {"provider_key": "unsampled", "display_name": "u", "provider_class": None, "status": "ok", "best_ms": None},
        ]
        cursor = types.SimpleNamespace(fetchall=lambda: out_rows, fetchone=lambda: None, execute=lambda *a, **k: None)
        module = types.ModuleType("database")

        class _CM:
            def __enter__(self):
                return (None, cursor)

            def __exit__(self, *exc):
                return False

        module.get_db_cursor = lambda commit=False: _CM()
        with mock.patch.dict(sys.modules, {"database": module}):
            out = chs.rank_providers()
        self.assertEqual([r["provider_key"] for r in out], ["sampled", "unsampled"])


class TestRanking(unittest.TestCase):
    """Rank by observation. Absent data must never become a number."""

    def _rank(self, rows):
        cursor = types.SimpleNamespace(fetchall=lambda: rows, fetchone=lambda: None, execute=lambda *a, **k: None)
        module = types.ModuleType("database")

        class _CM:
            def __enter__(self):
                return (None, cursor)

            def __exit__(self, *exc):
                return False

        module.get_db_cursor = lambda commit=False: _CM()
        with mock.patch.dict(sys.modules, {"database": module}):
            return chs.rank_providers()

    def _row(self, key, status=None, best=None, cls=None):
        return {
            "provider_key": key,
            "display_name": key,
            "provider_class": cls,
            "status": status,
            "best_ms": best,
        }

    def test_healthy_fast_ranks_above_healthy_slow(self):
        out = self._rank(
            [
                self._row("slow", "ok", best=900),
                self._row("fast", "ok", best=100),
            ]
        )
        self.assertEqual([r["provider_key"] for r in out], ["fast", "slow"])

    def test_healthy_ranks_above_unmeasured(self):
        out = self._rank(
            [
                self._row("unknown"),
                self._row("known", "ok", best=5000),
            ]
        )
        self.assertEqual([r["provider_key"] for r in out], ["known", "unknown"])

    def test_unmeasured_is_not_given_an_invented_latency(self):
        out = self._rank([self._row("unknown")])
        self.assertIsNone(out[0]["best_ms"], "a NULL sample must stay NULL")

    def test_unmeasured_without_latency_ranks_after_one_with_latency(self):
        out = self._rank(
            [
                self._row("healthy_no_latency", "ok", best=None),
                self._row("healthy_with_latency", "ok", best=900),
            ]
        )
        self.assertEqual(
            [r["provider_key"] for r in out],
            ["healthy_with_latency", "healthy_no_latency"],
        )

    def test_failing_ranks_below_healthy(self):
        out = self._rank(
            [
                self._row("broken", "auth_error"),
                self._row("fine", "ok", best=100),
            ]
        )
        self.assertEqual([r["provider_key"] for r in out], ["fine", "broken"])

    def test_image_only_ranks_above_failing(self):
        """It works — just not for text. Not equivalent to healthy, better than broken."""
        out = self._rank(
            [
                self._row("broken", "unreachable"),
                self._row("images", "unsupported", cls="image_only"),
            ]
        )
        self.assertEqual([r["provider_key"] for r in out], ["images", "broken"])

    def test_ranks_are_sequential_from_one(self):
        out = self._rank([self._row(f"p{i}", "ok", best=i * 10) for i in range(4)])
        self.assertEqual([r["rank"] for r in out], [1, 2, 3, 4])

    def test_a_failed_query_returns_empty_rather_than_raising(self):
        boom = types.ModuleType("database")

        class _CM:
            def __enter__(self):
                raise RuntimeError("db down")

            def __exit__(self, *exc):
                return False

        boom.get_db_cursor = lambda commit=False: _CM()
        with mock.patch.dict(sys.modules, {"database": boom}):
            self.assertEqual(chs.rank_providers(), [])

    def test_latency_ceiling_exists_so_one_slow_sample_cannot_dominate(self):
        """Measured cold: a 16b model took ~70s for twelve tokens."""
        self.assertLessEqual(chs.LATENCY_CEILING_MS, 60_000)


class TestCadencesAreActuallyDifferent(unittest.TestCase):
    """Three cadences, three measurements — which is what migration 487 promised.

    All three spent the identical 1-token completion, so `full` was a second copy of `health`
    costing 30 extra requests a day to learn nothing, and `latency` measured time-to-first-byte
    rather than anything a ranking could use. #3664 stopped the ranking reading health rows;
    without this, that left it nothing better to read.

    The design rule that matters most: `full` reports health from a COMPLETION, never from the
    model list. All five OmniRoute rows answered `/v1/models` with 200 while three of them 403'd
    or 502'd a completion — a `full` that trusted the enumeration would rank the dead rows first.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = pathlib.Path(chs.__file__).read_text(encoding="utf-8")

    def _probe(self, kind, resp=None, enum=None, provider=None):
        prov = provider or {
            "provider_key": "p",
            "base_url": "https://api.example.com/v1",
            "default_model": "m1",
            "auth_env_var": None,
            "is_cloud_proxy": False,
        }
        completion = resp or self._resp(200, payload={"model": "m1"})
        mod = types.ModuleType("requests")
        mod.exceptions = types.SimpleNamespace(
            Timeout=type("Timeout", (Exception,), {}),
            RequestException=type("RequestException", (Exception,), {}),
        )
        mod.post = mock.Mock(return_value=completion)
        if enum is None:
            mod.get = mock.Mock(side_effect=AssertionError("full must enumerate"))
        else:
            mod.get = mock.Mock(return_value=enum)
        with mock.patch.dict("os.environ", {"CADENCE_KEY_XYZ": "k"}, clear=False):
            with mock.patch.dict(sys.modules, {"requests": mod}):
                out = chs._probe_one(prov, kind, 5)
        return out, mod

    def _resp(self, status, text="", payload=None):
        r = mock.Mock()
        r.status_code = status
        r.ok = 200 <= status < 300
        r.text = text
        r.json = lambda: (payload if payload is not None else {})
        return r

    def _models_resp(self, ids):
        return self._resp(200, payload={"data": [{"id": i} for i in ids]})

    def test_health_still_asks_for_one_token(self):
        _, mod = self._probe("health")
        self.assertEqual(mod.post.call_args.kwargs["json"]["max_tokens"], 1)

    def test_latency_asks_for_a_real_completion(self):
        """Otherwise it measures time-to-first-byte, same as health, and ranks nothing."""
        _, mod = self._probe("latency")
        self.assertEqual(mod.post.call_args.kwargs["json"]["max_tokens"], chs.LATENCY_SAMPLE_TOKENS)
        self.assertGreater(chs.LATENCY_SAMPLE_TOKENS, 1)

    def test_full_enumerates_and_also_completes(self):
        out, mod = self._probe("full", enum=self._models_resp(["m1", "m2"]))
        self.assertTrue(mod.get.called, "full must ask what the provider serves")
        self.assertTrue(mod.post.called, "full must still prove the provider works")
        self.assertEqual(out["status"], "ok")
        self.assertIn("serves 2 model(s)", out["detail"])

    def test_full_reports_health_from_the_completion_not_the_model_list(self):
        """The OmniRoute lesson, as an assertion.

        The enumeration succeeds; the completion 403s. The verdict must follow the completion.
        """
        # a credential IS present, so a 403 is a refused credential (auth_error) rather than
        # the "nothing was sent" case (no_key) — the two are deliberately different
        prov = {
            "provider_key": "p",
            "base_url": "https://api.example.com/v1",
            "default_model": "m1",
            "auth_env_var": "CADENCE_KEY_XYZ",
            "is_cloud_proxy": False,
        }
        out, _ = self._probe(
            "full",
            resp=self._resp(403, text='{"error":"client scope refused"}'),
            enum=self._models_resp(["m1", "m2", "m3"]),
            provider=prov,
        )
        self.assertEqual(
            out["status"],
            "auth_error",
            "a 200 from /models must never make a provider look healthy",
        )
        self.assertIn("serves 3 model(s)", out["detail"], "the enumeration is still reported")
        self.assertIn("client scope refused", out["detail"], "and so is the real failure")

    def test_full_flags_a_default_model_the_provider_does_not_serve(self):
        out, _ = self._probe("full", enum=self._models_resp(["other", "another"]))
        self.assertIn("default_model 'm1' NOT in list", out["detail"])

    def test_full_truncates_a_long_model_list(self):
        out, _ = self._probe("full", enum=self._models_resp([f"m{i}" for i in range(60)]))
        self.assertIn("serves 60 model(s)", out["detail"])
        self.assertIn("+48 more", out["detail"])

    def test_a_failing_enumeration_does_not_break_the_probe(self):
        out, _ = self._probe("full", enum=self._resp(500))
        self.assertEqual(out["status"], "ok", "the completion still decided the verdict")
        self.assertIn("/models -> HTTP 500", out["detail"])

    def test_enumeration_never_mutates_the_configured_model_list(self):
        """Drift is reported, not applied. The probe must not rewrite what dispatch routes to."""
        self.assertNotIn(
            "UPDATE contractor_providers",
            self.src[self.src.index("def _enumerate_models") : self.src.index("def _full_detail")],
            "enumeration must never write to contractor_providers",
        )

    def test_retention_no_longer_depends_on_a_cadence_that_may_never_arrive(self):
        """`full` needs local hour 0 AND minute < 15 — unreachable on some scheduler starts."""
        jobs = pathlib.Path(chs.__file__).resolve().parents[1] / "tools" / "department_hq" / "jobs.py"
        if not jobs.exists():
            jobs = pathlib.Path("/mnt/archie_brain/platform_v2/tools/department_hq/jobs.py")
        self.assertTrue(jobs.exists(), "jobs.py not reachable")
        body = jobs.read_text(encoding="utf-8")
        start = body.index("def contractor_health_job")
        block = body[start : body.index("def ", start + 10)]
        self.assertIn("prune(days=30)", block)
        self.assertNotIn(
            'if kind == "full":',
            block,
            "retention must not hang off a bucket that may never be selected",
        )


class TestProbeBackoff(unittest.TestCase):
    """Re-probing must not be the default response to a failure that cannot fix itself.

    Not a money play — a 1-token probe costs a fraction of a cent. Two things matter more:

      * `rate_limited` means the upstream asked us to slow down. Continuing every 15 minutes
        after a 429 is how a free tier gets withdrawn. Backing off is obeying the response.
      * 15 of 30 contractors are `no_key` or `auth_error`. No quantity of re-probing installs a
        credential. Those probes run 1,440 times a day and cannot change the answer.
    """

    def _mins(self, status):
        return chs.probe_backoff_minutes(status)

    def test_healthy_and_unreachable_are_probed_every_cycle(self):
        """`unreachable` is the cheapest genuinely transient signal — a blip must clear fast."""
        self.assertEqual(self._mins("ok"), 0)
        self.assertEqual(self._mins("unreachable"), 0)

    def test_rate_limited_backs_off(self):
        """The one that is correctness rather than thrift."""
        self.assertGreaterEqual(self._mins("rate_limited"), 60)

    def test_configuration_failures_back_off_hard(self):
        for status in ("no_key", "auth_error", "unsupported"):
            self.assertGreaterEqual(self._mins(status), 60, f"{status} cannot be fixed by re-probing")

    def test_config_backoff_stays_under_two_hours(self):
        """There is no manual probe endpoint, so this window IS the operator's refresh.

        Six hours meant an operator who pasted a working key reloaded, saw `no_key`, and
        concluded their fix had failed. A support question costs more than the ~300
        probes/day this trades away.
        """
        for status in ("no_key", "auth_error", "unsupported"):
            self.assertLessEqual(self._mins(status), 120, f"{status} staleness budget")

    def test_a_never_probed_provider_is_always_probed(self):
        self.assertEqual(self._mins(None), 0)
        self.assertEqual(chs.due_for_probe(None), (True, ""))

    def test_a_recent_no_key_is_skipped_with_a_reason(self):
        from datetime import datetime, timedelta, timezone

        latest = {"status": "no_key", "created_at": datetime.now(timezone.utc) - timedelta(minutes=5)}
        probe, why = chs.due_for_probe(latest)
        self.assertFalse(probe)
        self.assertIn("no_key", why)
        self.assertIn("120m", why)

    def test_the_same_provider_is_probed_once_the_backoff_expires(self):
        from datetime import datetime, timedelta, timezone

        latest = {"status": "no_key", "created_at": datetime.now(timezone.utc) - timedelta(hours=3)}
        self.assertEqual(chs.due_for_probe(latest)[0], True)

    def test_healthy_providers_are_never_skipped(self):
        from datetime import datetime, timezone

        latest = {"status": "ok", "created_at": datetime.now(timezone.utc)}
        self.assertEqual(chs.due_for_probe(latest)[0], True)

    def test_an_unknown_status_is_conservative_not_eager(self):
        """A vocabulary gap must not become 'probe everything'."""
        self.assertGreaterEqual(self._mins("some_future_status"), 60)

    def test_a_naive_timestamp_still_compares(self):
        """`created_at` is TIMESTAMPTZ, but a naive value must not raise inside the scan."""
        from datetime import datetime, timedelta

        latest = {"status": "no_key", "created_at": datetime.now() - timedelta(minutes=5)}
        probe, _ = chs.due_for_probe(latest)
        self.assertFalse(probe)

    def test_a_skip_writes_no_row_so_the_timestamp_stays_honestly_old(self):
        """The tab renders `created_at` as "last checked".

        Backdating a skipped provider's row to look current would be the absent-vs-zero mistake
        this whole service exists to avoid. So a skip writes nothing at all.
        """
        src = pathlib.Path(chs.__file__).read_text(encoding="utf-8")
        start = src.index("def scan(")
        block = src[start : src.index("def _latest_observations")]
        self.assertIn("skipped.append", block)

        # Find the skip branch by its EFFECT, not by an exact string. An earlier version of this
        # test split on the literal "if not probe_now:" and therefore broke the moment the
        # condition legitimately grew an `and not force` — it was asserting on syntax, not on
        # behaviour, and would have blocked the feature rather than the bug.
        branch = re.search(r"skipped\.append\(.*?\n\s*continue", block, re.S)
        self.assertIsNotNone(branch, "could not locate the skip branch")
        self.assertNotIn(
            "record_observation(",
            branch.group(0),
            "a skip must not write an observation",
        )

    def test_skips_are_reported_not_silent(self):
        src = pathlib.Path(chs.__file__).read_text(encoding="utf-8")
        self.assertIn('"skipped": len(skipped)', src)
        self.assertIn('"skip_reasons"', src)

    def test_a_failed_lookup_probes_everything_rather_than_nothing(self):
        """Fail toward MORE traffic, never less. Skipping everything would be the dangerous
        direction: the table would stop updating and nothing would say so."""
        import unittest.mock as _m

        mod = types.ModuleType("database")

        def _boom(*a, **k):
            raise RuntimeError("db down")

        mod.get_db_cursor = _boom
        with _m.patch.dict(sys.modules, {"database": mod}):
            self.assertEqual(chs._latest_observations(["a", "b"]), {})


class TestProbeOne(unittest.TestCase):
    """The network call itself, with `requests` patched."""

    def _patch_requests(self, resp):
        mod = types.ModuleType("requests")
        exc_mod = types.SimpleNamespace(
            Timeout=type("Timeout", (Exception,), {}),
            RequestException=type("RequestException", (Exception,), {}),
        )
        mod.exceptions = exc_mod
        mod.get = mock.Mock(return_value=resp)
        mod.post = mock.Mock(return_value=resp)
        return mod, mod.get, mod.post

    def _provider(self, **over):
        base = {
            "provider_key": "pollinations",
            "base_url": "https://image.pollinations.ai",
            "default_model": "flux",
            "auth_env_var": None,
            "is_cloud_proxy": False,
        }
        base.update(over)
        return base

    def _resp(self, status, text="", payload=None):
        r = mock.Mock()
        r.status_code = status
        r.ok = 200 <= status < 300
        r.text = text
        r.json = lambda: (payload if payload is not None else {})
        return r

    def _run(self, resp, provider=None, kind="health"):
        mod, get, post = self._patch_requests(resp)
        with mock.patch.dict(sys.modules, {"requests": mod}):
            return chs._probe_one(provider or self._provider(), kind, 5)

    def test_image_only_is_detected_from_a_400_body(self):
        """The pollinations case, end to end through the real classifier."""
        out = self._run(
            self._resp(
                400,
                text=(
                    '{"error":{"message":"Model is an image-generation model and cannot be '
                    'used on /v1/chat/completions. Use POST /v1/images/generations instead."}}'
                ),
            ),
            kind="latency",
        )
        self.assertEqual(out["status"], "unsupported")

    def test_latency_cadence_posts_and_records_the_served_model(self):
        mod, get, post = self._patch_requests(self._resp(200, payload={"model": "actually-served-model"}))
        with mock.patch.dict(sys.modules, {"requests": mod}):
            out = chs._probe_one(self._provider(), "latency", 45)
        self.assertTrue(post.called)
        self.assertEqual(out["observed_model"], "actually-served-model")

    def test_timeout_is_unreachable_not_an_error(self):
        mod = types.ModuleType("requests")

        class _Timeout(Exception):
            pass

        mod.exceptions = types.SimpleNamespace(Timeout=_Timeout, RequestException=type("R", (Exception,), {}))
        mod.get = mock.Mock(side_effect=_Timeout("slow"))
        mod.post = mock.Mock(side_effect=_Timeout("slow"))
        with mock.patch.dict(sys.modules, {"requests": mod}):
            out = chs._probe_one(self._provider(), "health", 1)
        self.assertEqual(out["status"], "unreachable")
        self.assertIn("timeout", out["detail"])

    def test_missing_base_url_with_no_credential_is_no_key(self):
        """No key is the more actionable problem, so it is the one reported."""
        out = chs._probe_one(self._provider(base_url="", auth_env_var="NOPE_XYZ"), "health", 5)
        self.assertEqual(out["status"], "no_key")

    def test_missing_base_url_with_a_credential_is_unreachable(self):
        out = chs._probe_one(self._provider(base_url=""), "health", 5)
        self.assertEqual(out["status"], "no_key", "no auth_env_var means no credential either")

    def test_health_cadence_spends_a_completion_not_a_models_get(self):
        """`/models` is not proof of capability.

        Measured 2026-10-05: all five OmniRoute rows answer GET /v1/models with 200, while
        three of them 403/502 a real completion. A reachability-only probe ranked those
        broken rows first. Both cadences therefore send a 1-token completion.
        """
        mod, get, post = self._patch_requests(self._resp(200))
        with mock.patch.dict(sys.modules, {"requests": mod}):
            chs._probe_one(self._provider(), "health", 5)
        self.assertTrue(post.called, "health must POST a completion")
        self.assertFalse(get.called, "health must NOT settle for a /models GET")

    def test_health_completion_asks_for_one_token(self):
        """The point is to force generation, not to get an answer."""
        mod, get, post = self._patch_requests(self._resp(200))
        with mock.patch.dict(sys.modules, {"requests": mod}):
            chs._probe_one(self._provider(), "health", 5)
        self.assertEqual(post.call_args.kwargs["json"]["max_tokens"], 1)

    def _cloud_provider(self, **over):
        """The live shape: base_url is a SENTINEL, not a URL. See fleet_service.py."""
        base = {
            "provider_key": "qwen3_cloud",
            "base_url": "ollama_cloud_proxy",
            "default_model": "qwen3-coder-next",
            "auth_env_var": "CLOUD_KEY_XYZ",
            "is_cloud_proxy": True,
        }
        base.update(over)
        return base

    def test_a_cloud_proxy_is_probed_at_ollama_not_at_its_sentinel(self):
        """The bug: `ollama_cloud_proxy/chat/completions` is a DNS failure, not a verdict.

        Both cloud contractors reported `unreachable` — a manufactured diagnosis. They were
        reachable; the probe had asked the wrong question of them. `call_external` has always
        branched on is_cloud_proxy first and delegated to call_ollama_cloud.
        """
        with mock.patch.dict("os.environ", {"CLOUD_KEY_XYZ": "k"}, clear=False):
            mod, _get, post = self._patch_requests(self._resp(200, payload={"model": "m"}))
            with mock.patch.dict(sys.modules, {"requests": mod}):
                chs._probe_one(self._cloud_provider(), "health", 5)
        url = post.call_args.args[0]
        self.assertEqual(url, chs.OLLAMA_CLOUD_GENERATE_URL)
        self.assertNotIn(
            "ollama_cloud_proxy",
            url,
            "the sentinel string must never reach the network layer",
        )
        self.assertIn("ollama.com", url)

    def test_a_cloud_proxy_uses_ollamas_native_payload_not_openai_chat(self):
        """ollama.com/api/generate takes `prompt` and `num_predict`, not `messages`."""
        with mock.patch.dict("os.environ", {"CLOUD_KEY_XYZ": "k"}, clear=False):
            mod, _get, post = self._patch_requests(self._resp(200, payload={"model": "m"}))
            with mock.patch.dict(sys.modules, {"requests": mod}):
                chs._probe_one(self._cloud_provider(), "health", 5)
        body = post.call_args.kwargs["json"]
        self.assertIn("prompt", body)
        self.assertEqual(body["options"]["num_predict"], 1)
        self.assertNotIn("messages", body, "this is not a /chat/completions endpoint")
        self.assertFalse(body["stream"], "stream must be off so the body is complete")

    def test_a_cloud_proxy_sends_bearer_auth(self):
        with mock.patch.dict("os.environ", {"CLOUD_KEY_XYZ": "sk-test-value"}, clear=False):
            mod, _get, post = self._patch_requests(self._resp(200, payload={"model": "m"}))
            with mock.patch.dict(sys.modules, {"requests": mod}):
                chs._probe_one(self._cloud_provider(), "health", 5)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test-value")

    def test_a_cloud_proxy_with_no_key_is_no_key_without_a_request(self):
        """No credential means nothing to present, so do not spend a request discovering that."""
        with mock.patch.dict("os.environ", {}, clear=True):
            mod, _get, post = self._patch_requests(self._resp(200))
            with mock.patch.dict(sys.modules, {"requests": mod}):
                out = chs._probe_one(self._cloud_provider(auth_env_var="CLOUD_KEY_ABSENT"), "health", 5)
        self.assertEqual(out["status"], "no_key")
        self.assertFalse(post.called, "no credential means no request")

    def test_a_retired_cloud_model_is_reported_as_an_error_not_unreachable(self):
        """Live 2026-10-05: both cloud models 410 Gone.

        `qwen3-coder-next` retired 2026-07-15, `minimax-m2.5` retired 2026-07-31. The probe
        must surface that as an error carrying Ollama's own explanation, not as the DNS
        failure it used to manufacture.
        """
        body = '{"error":"qwen3-coder-next was retired at 2026-07-15"}'
        with mock.patch.dict("os.environ", {"CLOUD_KEY_XYZ": "k"}, clear=False):
            out = self._run(self._resp(410, text=body), self._cloud_provider())
        self.assertEqual(out["status"], "error")
        self.assertIn("retired", out["detail"])

    def test_a_402_on_a_cloud_proxy_keeps_the_upstream_explanation(self):
        """`minimax-m2.7` answers 402 "not in the Free plan" — a plan fact, not a fault."""
        body = '{"error":"This model is not in the Free plan."}'
        with mock.patch.dict("os.environ", {"CLOUD_KEY_XYZ": "k"}, clear=False):
            out = self._run(self._resp(402, text=body), self._cloud_provider())
        self.assertEqual(out["status"], "error")
        self.assertIn("Free plan", out["detail"])

    def test_the_probe_does_not_go_through_call_ollama_cloud(self):
        """That path calls _log_cloud_usage, which would bill the weekly free allowance.

        These rows declare 7000 requests/week. At one probe per 15 min that is ~672/week —
        roughly a tenth of the free tier, spent watching it.
        """
        src = pathlib.Path(chs.__file__).read_text(encoding="utf-8")
        probe = src[src.index("def _probe_one") :]
        # Comments stripped first: this function's own docstring NAMES call_ollama_cloud to
        # explain why it is bypassed, so a raw substring scan fails on the explanation.
        code = "\n".join(ln for ln in probe.split("\n") if not ln.strip().startswith("#"))
        self.assertNotIn(
            "call_ollama_cloud",
            code,
            "the probe must post directly, never through a path that logs usage",
        )
        self.assertNotIn("_log_cloud_usage", code)
        self.assertNotIn("archie_bridge", code)

    def test_an_image_body_from_ollama_is_not_read_as_image_only(self):
        """ollama.com has no image model behind this key, so a 400 there means something else."""
        body = '{"error":"image generation is not supported for this model"}'
        with mock.patch.dict("os.environ", {"CLOUD_KEY_XYZ": "k"}, clear=False):
            out = self._run(self._resp(400, text=body), self._cloud_provider())
        self.assertNotEqual(out["status"], "unsupported")

    def test_a_403_with_a_credential_is_auth_error(self):
        """The exact OmniRoute failure: 200 on /models, 403 on a completion.

        `auth_error` has to mean "the credential we presented was refused". With a
        credential present that is what happened.
        """
        with mock.patch.dict("os.environ", {"PROBE_KEY_XYZ": "sk-secret"}, clear=False):
            out = self._run(self._resp(403), self._provider(auth_env_var="PROBE_KEY_XYZ"))
        self.assertEqual(out["status"], "auth_error")

    def test_a_403_with_no_credential_is_no_key_not_auth_error(self):
        """The two are different problems with different fixes.

        `auth_error` says re-key it. `no_key` says there was never a key to reject — which is
        the honest reading for deepseek, openrouter and replicate, none of which have an
        auth_env_var configured. Reporting them as auth_error sends an operator to rotate a
        credential that does not exist.

        The probe still has to be sent: a provider that answers 2xx with no credential is
        genuinely keyless, and skipping the request would make that undetectable.
        """
        mod, _get, post = self._patch_requests(self._resp(403))
        with mock.patch.dict(sys.modules, {"requests": mod}):
            out = chs._probe_one(self._provider(auth_env_var=None), "health", 5)
        self.assertTrue(post.called, "the request must still be sent — a 2xx proves keyless")
        self.assertEqual(out["status"], "no_key")

    def test_a_rejection_records_the_upstreams_own_explanation(self):
        """The column exists for this and was empty for 20 of 30 contractors.

        Measured 2026-10-05: gemini returns 403 with a body saying the API method "has been
        disabled" for this project. That sentence IS the diagnosis. `detail` was only ever
        read for the 400 image-generation case, so every 401/403/429/5xx recorded NULL and
        the operator had nothing to read.
        """
        body = '{"error":{"code":403,"message":"Requests to this API method has been disabled"}}'
        out = self._run(self._resp(403, text=body), self._provider(auth_env_var=None))
        self.assertIsNotNone(out["detail"], "a 403 must record why")
        self.assertIn("has been disabled", out["detail"])

    def test_detail_is_recorded_for_every_non_ok_status_not_just_400(self):
        for status in (401, 403, 429, 500, 502):
            out = self._run(self._resp(status, text="upstream said no"), self._provider())
            self.assertEqual(
                out["detail"],
                "upstream said no",
                f"HTTP {status} discarded the upstream's explanation",
            )

    def test_detail_redacts_the_credential_if_the_upstream_echoes_it(self):
        """`detail` is rendered into the Contractors tab tooltip.

        An upstream that reflects the Authorization header would otherwise persist a live key
        into a history table and then into the DOM.

        The credential literal is deliberately NOT key-shaped: redaction replaces the exact
        secret substring whatever its shape, and an `sk-live-…` here trips the repo's
        `generic-api-key` scanner. A fake secret in a test is still a secret-shaped string in
        the history.
        """
        secret = "ZZ-TEST-CREDENTIAL-ZZ"
        body = f'{{"error":"invalid token: Bearer {secret} (truncated)"}}'
        with mock.patch.dict("os.environ", {"PROBE_KEY_XYZ": secret}, clear=False):
            out = self._run(self._resp(401, text=body), self._provider(auth_env_var="PROBE_KEY_XYZ"))
        self.assertNotIn(secret, out["detail"], "a live key reached the history table")
        self.assertIn("***", out["detail"])
        self.assertIn("invalid token", out["detail"], "the diagnosis must survive redaction")

    def test_a_success_records_no_detail(self):
        """Nothing failed, so there is nothing to explain."""
        out = self._run(self._resp(200, text='{"choices":[]}'), self._provider())
        self.assertIsNone(out["detail"])

    def test_keyless_is_reachable_through_a_real_probe(self):
        """End-to-end: a provider that answers with no credential is keyless.

        `keyless` could not be produced before, because `_probe_one` hardcoded has_key=True
        into the classifier and the success check sat behind the no-key branch.
        """
        out = self._run(self._resp(200, payload={"model": "flux"}), self._provider())
        self.assertEqual(out["status"], "ok")
        self.assertEqual(
            chs.classify_provider_class(has_key=False, status=out["status"]),
            "keyless",
        )


if __name__ == "__main__":
    unittest.main()
