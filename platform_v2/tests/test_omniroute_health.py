"""Pin the OmniRoute gateway health verdict.

Built from a real three-day outage. Measured 2026-09-21: every call since
2026-09-18 returned zero tokens — 1,667 of them — and nothing alarmed, because
`omniroute_telemetry` was working perfectly and correctly skipping zero-token
rows as non-inference. The ledger went quiet and the quiet read as "nobody used
the coder lanes".

The distinctions these tests hold:

  no calls          -> NOT a fault. A lane nobody used must never page.
  calls, no tokens  -> the fault. Every request is failing.
  entitlement       -> 401/402/403: credentials/plan/policy. Retrying is futile.
  transient         -> 429/5xx: backoff, may clear itself.
  unreadable        -> UNKNOWN, never "healthy".
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.omniroute_health import (  # noqa: E402
    _classify,
    read_window,
    summarize,
)


def _row(status, tin=0, tout=0, err=None):
    r = {"timestamp": "2026-09-20T00:00:00Z", "status": status, "tokens_in": tin, "tokens_out": tout}
    if err:
        r["error_summary"] = err
    return r


class TestSilenceIsNotFailure(unittest.TestCase):
    def test_no_calls_is_not_a_condition(self):
        """Paging on silence trains people to ignore the channel."""
        s = summarize([])
        self.assertIsNone(s["condition"])
        self.assertIn("no calls", s["detail"])

    def test_too_few_calls_is_not_yet_evidence(self):
        """A couple of 429s while a lane warms up is normal."""
        s = summarize([_row(429) for _ in range(3)], min_calls=10)
        self.assertIsNone(s["condition"])
        self.assertIn("not enough", s["detail"])

    def test_a_healthy_window_raises_nothing(self):
        s = summarize([_row(200, 100, 50) for _ in range(20)])
        self.assertIsNone(s["condition"])
        self.assertEqual(s["with_tokens"], 20)


class TestTheMeasuredOutage(unittest.TestCase):
    """The live shape: many calls, not one token, mixed refusals."""

    def _outage(self):
        rows = []
        rows += [_row(403, err="[403]: OpenCode's free tier can only be used from within OpenCode") for _ in range(91)]
        rows += [_row(429, err="[429]: Felo thread creation failed with HTTP 429") for _ in range(816)]
        rows += [_row(402, err="[402]: This model requires an opencode API key") for _ in range(174)]
        return rows

    def test_zero_tokens_across_a_busy_window_is_no_inference(self):
        s = summarize(self._outage())
        self.assertEqual(s["condition"], "no_inference")
        self.assertEqual(s["with_tokens"], 0)
        self.assertGreater(s["window_calls"], 1000)

    def test_the_detail_QUOTES_the_upstream_refusal(self):
        """An alert saying 'unhealthy' starts an investigation; a quoted refusal
        ends it. This is the whole point of the module."""
        s = summarize(self._outage())
        self.assertIn("Felo thread creation failed", s["detail"])
        self.assertIn("ZERO tokens", s["detail"])

    def test_entitlement_and_transient_are_counted_SEPARATELY(self):
        """Reporting one number for both is how a closed free tier gets triaged
        as a transient blip for three days."""
        s = summarize(self._outage())
        self.assertEqual(s["entitlement"], 91 + 174)
        self.assertEqual(s["transient"], 816)

    def test_a_single_error_total_would_have_hidden_the_cause(self):
        """Non-vacuity: the naive metric cannot distinguish these two windows."""
        refused = [_row(403, err="free tier closed") for _ in range(50)]
        ratelimited = [_row(429, err="slow down") for _ in range(50)]
        naive_a = sum(1 for r in refused if int(r["status"]) >= 400)
        naive_b = sum(1 for r in ratelimited if int(r["status"]) >= 400)
        self.assertEqual(naive_a, naive_b, "control broken")
        a, b = summarize(refused), summarize(ratelimited)
        self.assertNotEqual(
            (a["entitlement"], a["transient"]),
            (b["entitlement"], b["transient"]),
            "the split failed to distinguish a refusal from a rate limit",
        )


class TestEntitlementAndDegraded(unittest.TestCase):
    def test_majority_refusals_with_some_tokens_is_entitlement(self):
        rows = [_row(402, err="needs an API key") for _ in range(30)] + [_row(200, 10, 10) for _ in range(5)]
        s = summarize(rows)
        self.assertEqual(s["condition"], "entitlement")
        self.assertIn("retrying cannot fix this", s["detail"])

    def test_mixed_errors_with_tokens_flowing_is_degraded_not_outage(self):
        rows = [_row(429, err="slow down") for _ in range(12)] + [_row(200, 10, 10) for _ in range(10)]
        s = summarize(rows)
        self.assertEqual(s["condition"], "degraded")
        self.assertIn("some tokens still", s["detail"])

    def test_one_token_bearing_call_prevents_the_outage_verdict(self):
        """A gateway that produced ANY inference is not producing zero."""
        rows = [_row(403, err="closed") for _ in range(40)] + [_row(200, 1, 1)]
        s = summarize(rows)
        self.assertNotEqual(s["condition"], "no_inference")


class TestClassification(unittest.TestCase):
    def test_status_buckets(self):
        for s in (401, 402, 403):
            self.assertEqual(_classify(s), "entitlement")
        for s in (429, 500, 502, 503, 504):
            self.assertEqual(_classify(s), "transient")
        for s in (200, 201, 204):
            self.assertEqual(_classify(s), "ok")
        self.assertEqual(_classify(404), "other")

    def test_unparseable_status_is_unknown_not_ok(self):
        for s in (None, "", "abc"):
            self.assertEqual(_classify(s), "unknown")


class TestUnknownIsNotHealthy(unittest.TestCase):
    def test_a_missing_db_reads_as_None_not_empty(self):
        """Empty would summarize to 'no calls' — a healthy quiet gateway — which
        is exactly the misreport this module exists to prevent (ADR-017)."""
        self.assertIsNone(read_window(hours=1, db_path="/nonexistent/none.sqlite"))

    def test_check_reports_unreadable_rather_than_healthy(self):
        from services import omniroute_health as oh

        real = oh.read_window
        oh.read_window = lambda *a, **k: None
        try:
            r = oh.check_gateway_health()
        finally:
            oh.read_window = real
        self.assertEqual(r["condition"], "unreadable")
        self.assertIn("UNKNOWN, not healthy", r["detail"])


class TestTheMessageStatesItsOwnWindow(unittest.TestCase):
    """A status line that misstates its own window is the bug this module is for.

    The first version printed the module default (6h) no matter what window was
    actually measured, so a 72h check read "in the last 6h".
    """

    def test_detail_quotes_the_window_it_was_given(self):
        rows = [_row(403, err="closed") for _ in range(40)]
        s = summarize(rows, hours=72)
        self.assertIn("last 72h", s["detail"])
        self.assertNotIn("last 6h", s["detail"])
        self.assertEqual(s["window_hours"], 72)

    def test_check_gateway_health_passes_its_window_through(self):
        from services import omniroute_health as oh

        real = oh.read_window
        oh.read_window = lambda hours=6, **k: [_row(402, err="needs key") for _ in range(40)]
        try:
            r = oh.check_gateway_health(hours=48)
        finally:
            oh.read_window = real
        self.assertEqual(r["window_hours"], 48)


if __name__ == "__main__":
    unittest.main(verbosity=2)


from services import omniroute_health as oh  # noqa: E402  (sys.path set above)


class TestInferencePathFilter(unittest.TestCase):
    """Management traffic must never read as failed inference (#3412 follow-up).

    The shipped version of this module selected no `path` column and counted
    every row, so a window of nothing but `/api/providers/test` pings -- which
    answer 200 with ZERO tokens by design -- reported `no_inference`, i.e. "every
    request is failing", on a gateway nobody had asked to infer.
    """

    def test_management_paths_are_not_inference(self):
        for p in ("/api/providers/test", "/api/provider-nodes", "/v1/models", "/v1/api-keys"):
            self.assertFalse(oh.is_inference_path(p), p)

    def test_v1_paths_are_inference(self):
        for p in ("/v1/chat/completions", "/v1/responses", "/v1/messages", "/v1/embeddings"):
            self.assertTrue(oh.is_inference_path(p), p)

    def test_unknown_path_fails_OPEN_and_is_counted(self):
        # A row we cannot classify must be COUNTED. Dropping it would let a
        # schema change render an outage as a quiet idle gateway.
        for p in (None, "", "   ", "weird"):
            self.assertTrue(oh.is_inference_path(p), repr(p))

    def test_health_pings_alone_do_NOT_alarm(self):
        rows = [{"status": 200, "tokens_in": 0, "tokens_out": 0, "path": "/api/providers/test"} for _ in range(30)]
        r = oh.summarize(rows, min_calls=10, hours=6)
        self.assertIsNone(r["condition"], r["detail"])
        self.assertEqual(r["window_calls"], 0)
        self.assertEqual(r["non_inference_excluded"], 30)
        self.assertIn("management", r["detail"])

    def test_a_real_outage_still_alarms_through_the_filter(self):
        # The filter must not blunt the detection it was added beside.
        rows = [{"status": 403, "tokens_in": 0, "tokens_out": 0, "path": "/v1/chat/completions"} for _ in range(20)]
        rows += [{"status": 200, "tokens_in": 0, "tokens_out": 0, "path": "/api/providers/test"} for _ in range(5)]
        r = oh.summarize(rows, min_calls=10, hours=6)
        self.assertEqual(r["condition"], "no_inference")
        self.assertEqual(r["window_calls"], 20)
        self.assertEqual(r["non_inference_excluded"], 5)

    def test_mixed_window_counts_only_inference_for_the_ratio(self):
        # 6 inference calls (below min_calls) buried in 40 health pings must
        # read as "not enough to judge", never as a 46-call catastrophe.
        rows = [{"status": 500, "tokens_in": 0, "tokens_out": 0, "path": "/v1/chat/completions"} for _ in range(6)]
        rows += [{"status": 200, "tokens_in": 0, "tokens_out": 0, "path": "/api/providers/test"} for _ in range(40)]
        r = oh.summarize(rows, min_calls=10, hours=6)
        self.assertIsNone(r["condition"])
        self.assertIn("not enough", r["detail"])
