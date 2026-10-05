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

    def test_no_key_beats_every_other_signal(self):
        """A provider with no credential cannot be judged on what it answered."""
        self.assertEqual(chs.classify_status(http_status=200, has_key=False), "no_key")

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
            chs.classify_provider_class(has_key=True, status="unsupported", is_cloud_proxy=False),
            "image_only",
        )

    def test_keyless_only_when_it_actually_answered(self):
        self.assertEqual(
            chs.classify_provider_class(has_key=False, status="ok", is_cloud_proxy=False),
            "keyless",
        )

    def test_no_key_and_no_answer_is_not_keyless(self):
        """A provider that failed for want of a credential is not keyless."""
        self.assertEqual(
            chs.classify_provider_class(has_key=False, status="unreachable", is_cloud_proxy=False),
            "local",
        )

    def test_a_credential_requiring_provider_is_not_called_paid_on_the_key_alone(self):
        """The six keyed providers span free-tier and metered; a key says neither.

        Claiming `paid` because a credential exists would put a free-tier provider into the
        paid bucket — and the whole point of the paid bucket is that it is opt-in.
        """
        self.assertEqual(
            chs.classify_provider_class(has_key=True, status="ok", is_cloud_proxy=False),
            "free_tier",
        )

    def test_failing_providers_are_not_reclassified(self):
        self.assertEqual(
            chs.classify_provider_class(has_key=True, status="auth_error", is_cloud_proxy=True),
            "free_tier",
        )


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

    def test_a_403_on_health_is_reported_as_auth_error_not_ok(self):
        """The exact OmniRoute failure: 200 on /models, 403 on a completion."""
        mod, get, post = self._patch_requests(self._resp(403))
        with mock.patch.dict(sys.modules, {"requests": mod}):
            out = chs._probe_one(self._provider(), "health", 5)
        self.assertEqual(out["status"], "auth_error")


if __name__ == "__main__":
    unittest.main()
