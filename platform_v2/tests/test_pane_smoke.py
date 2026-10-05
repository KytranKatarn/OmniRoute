"""Repair Bay PR Review pane smoke check — unit tests for the DECISION logic.

The Playwright driving cannot be unit-tested, so it is not: `judge_pane` is a pure
function over a DOM snapshot precisely so the part that decides pass/fail can be tested
without a browser. These tests cover that function and the surrounding contract.

The contract that matters most: a check that CANNOT RUN must never read as a pass. That
is not hypothetical — the Node version of this check shipped pointed at 127.0.0.1, which
the platform's security layer blocks, so it could not run at all and would have reported
nothing while appearing installed.
"""

import unittest
from unittest import mock

from tools.repair_bay.services.pane_smoke import (
    ENDPOINT_TIMEOUT_MS,
    MIN_PANE_BYTES,
    PANE_ENDPOINTS,
    _classify,
    format_alert_message,
    judge_pane,
)


class TestJudgePane(unittest.TestCase):
    def _snapshot(self, **kw):
        base = {
            "missing": False,
            "still_empty": False,
            "bytes": 6000,
            "text": "PR #1",
            "page_errors": [],
            "endpoint_errors": {},
        }
        base.update(kw)
        return base

    def test_healthy_pane_has_no_reasons(self):
        self.assertEqual(judge_pane(self._snapshot()), [])

    def test_missing_element_is_the_only_reason_reported(self):
        """One root cause, one message — not a cascade of derived complaints."""
        self.assertEqual(judge_pane(self._snapshot(missing=True)), ["#prReviewDetail is missing from the DOM"])

    def test_empty_flag_is_a_distinct_failure(self):
        """The showPRDetail() crash fingerprint: --empty cleared, then the handler died.

        `bytes` is large here on purpose: the pane genuinely has content, it just never
        got any. Only the flag catches it."""
        reasons = judge_pane(self._snapshot(still_empty=True))
        self.assertTrue(any("still flagged empty" in r for r in reasons), reasons)

    def test_blank_pane_is_caught_by_size(self):
        reasons = judge_pane(self._snapshot(bytes=70))
        self.assertTrue(any("rendered only 70 bytes" in r for r in reasons), reasons)

    def test_size_boundary(self):
        just_under = judge_pane(self._snapshot(bytes=MIN_PANE_BYTES - 1))
        at_limit = judge_pane(self._snapshot(bytes=MIN_PANE_BYTES))
        self.assertTrue(any("below" in r for r in just_under), just_under)
        self.assertEqual(at_limit, [])

    def test_zero_and_none_bytes_are_handled(self):
        for value in (0, None):
            reasons = judge_pane(self._snapshot(bytes=value))
            self.assertTrue(any("below" in r for r in reasons), (value, reasons))

    def test_sub_fetch_failure_is_reported_even_though_the_pane_rendered(self):
        """The check that would have caught the CodeRabbit NameError.

        The pane renders 6 KB of report AND the endpoint 502'd. A "did it render?"
        assertion passes this; the endpoint assertion must not."""
        snap = self._snapshot(endpoint_errors={"coderabbit": "HTTP 502"})
        reasons = judge_pane(snap)
        self.assertTrue(any("/coderabbit failed" in r for r in reasons), reasons)
        self.assertTrue(any("HTTP 502" in r for r in reasons), reasons)

    def test_both_pane_endpoints_are_probed(self):
        """If a new pane is added and not probed, it is silently unchecked."""
        self.assertIn("coderabbit", PANE_ENDPOINTS)
        self.assertIn("codex", PANE_ENDPOINTS)

    def test_multiple_endpoint_failures_are_all_reported(self):
        snap = self._snapshot(endpoint_errors={"coderabbit": "HTTP 502", "codex": "boom"})
        self.assertEqual(len(judge_pane(snap)), 2)

    def test_error_text_is_bounded(self):
        snap = self._snapshot(endpoint_errors={"codex": "x" * 500})
        reason = [r for r in judge_pane(snap) if "/codex failed" in r][0]
        self.assertLess(len(reason), 180, "the notification body must stay bounded")

    def test_review_prose_mentioning_a_failure_is_not_a_failure(self):
        """Regression guard for the first implementation.

        It scraped the pane TEXT for 'Could not load', so a CODEX review whose findings
        discuss that phrase made the check cry wolf on real content. The endpoint contract
        is asserted instead, so prose can say anything."""
        body = (
            "The pane reports Could not load the CodeRabbit review when the token is stale, "
            "and HTTP 502 is returned. Consider caching."
        )
        self.assertEqual(judge_pane(self._snapshot(text=body)), [])

    def test_js_errors_are_reported(self):
        reasons = judge_pane(self._snapshot(page_errors=["TypeError: x is not defined"]))
        self.assertTrue(any("TypeError" in r for r in reasons), reasons)

    def test_every_failure_mode_reports_at_once(self):
        snap = self._snapshot(
            still_empty=True,
            bytes=10,
            page_errors=["boom"],
            endpoint_errors={"coderabbit": "HTTP 502"},
        )
        self.assertEqual(len(judge_pane(snap)), 4)

    def test_real_findings_text_is_not_mistaken_for_a_failure(self):
        """A review whose BODY contains the words must not trip the check."""
        body = (
            "The pane reports Could not load the CodeRabbit review when the token is stale. "
            "Consider caching the result."
        )
        self.assertEqual(judge_pane(self._snapshot(text=body)), [])


class TestClassify(unittest.TestCase):
    def test_skipped_is_never_a_pass(self):
        """severity must not be 'info' AND indistinguishable from success.

        A skip is info severity but carries skipped=1 and a reason, so the job logs
        'skipped: ...' rather than 'all checked panes rendered'."""
        r = _classify([], 0, "skipped: no credential")
        self.assertEqual(r["severity"], "info")
        self.assertEqual(r["summary_metrics"]["skipped"], 1)
        self.assertNotIn("all checked panes rendered", r["reasons"][0])

    def test_failures_are_error_severity(self):
        r = _classify(["[open] pane still flagged empty after clicking a row"], 1, None)
        self.assertEqual(r["severity"], "error")
        self.assertEqual(r["summary_metrics"]["failed"], 1)

    def test_clean_run(self):
        r = _classify([], 2, None)
        self.assertEqual(r["severity"], "info")
        self.assertEqual(r["summary_metrics"], {"checked": 2, "failed": 0, "skipped": 0})


class TestTimeoutBudget(unittest.TestCase):
    """CODEX [high] on the first version: page.evaluate() does NOT inherit the page
    timeout, so a server that accepts a connection and never answers hung the job
    forever — and max_instances=1 meant it never ran again."""

    def test_a_bounded_timeout_is_defined(self):
        self.assertGreater(ENDPOINT_TIMEOUT_MS, 0)
        self.assertLessEqual(ENDPOINT_TIMEOUT_MS, 30000, "must fail fast, not hang")

    def test_probe_uses_an_abort_controller(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pane_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertIn("AbortController", src)
        self.assertIn("signal: ctl.signal", src)
        self.assertIn("AbortError", src)

    def test_abort_is_reported_distinctly(self):
        """A timeout must read as a timeout, not as a generic network error."""
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pane_smoke.py"
        ).read_text(encoding="utf-8")
        self.assertIn("no response in", src)


class TestSingleCountPerFailure(unittest.TestCase):
    """CODEX [low]: endpoint failures were appended twice, so one 502 counted as two
    findings and consumed two of the ten notification slots."""

    def test_judge_pane_reports_each_endpoint_once(self):
        import pathlib

        src = (
            pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pane_smoke.py"
        ).read_text(encoding="utf-8")
        live = src.split("endpoint_errors = page.evaluate(", 1)
        self.assertEqual(len(live), 2, "probe should appear once")
        tail = live[1]
        self.assertNotIn(
            "failures.append",
            tail.split("snapshot = page.evaluate(", 1)[0],
            "endpoint failures must be left to judge_pane, not appended as well",
        )

    def test_a_single_failure_yields_a_single_reason(self):
        reasons = judge_pane(
            {
                "missing": False,
                "still_empty": False,
                "bytes": 6000,
                "text": "",
                "page_errors": [],
                "endpoint_errors": {"codex": "HTTP 502"},
            }
        )
        self.assertEqual(len(reasons), 1)


class TestHostProbeRejectsTheBlockPage(unittest.TestCase):
    """CODEX [medium]: the security layer answers HTTP 200 with an ACCESS DENIED page,
    so a status-only probe accepted a blocked host and stopped."""

    def test_blocked_host_is_not_selected(self):
        import tools.repair_bay.services.pane_smoke as m

        BLOCKED = (
            "<html><head><title>ACCESS DENIED - A.R.C.H.I.E. Security</title></head>"
            "<body>BLOCKED DOMAIN</body></html>"
        )
        LOGIN = '<form><input name="username"><input type="password"></form>'

        calls = []

        class _Resp:
            def __init__(self, body):
                self.status = 200
                self._b = body

            def read(self, *_a):
                return self._b.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(url, timeout=None):
            calls.append(url)
            if "blocked" in url:
                return _Resp(BLOCKED)
            return _Resp(LOGIN)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            base = m._reachable_base(["http://blocked:3000", "http://good:3000"])
        self.assertEqual(base, "http://good:3000", "a 200 ACCESS DENIED page must not be accepted as the platform")
        self.assertEqual(len(calls), 2, "it must fall through to the next candidate")


class TestAlertMessage(unittest.TestCase):
    def test_includes_counts_and_reasons(self):
        msg = format_alert_message(_classify(["[open] a", "[merged] b"], 2, None))
        self.assertIn("2 failure(s)", msg)
        self.assertIn("across 2 filter(s)", msg)
        self.assertIn("- [open] a", msg)
        self.assertIn("- [merged] b", msg)

    def test_reason_list_is_capped(self):
        msg = format_alert_message(_classify([f"r{i}" for i in range(50)], 2, None))
        self.assertLessEqual(msg.count("\n  - "), 10)

    def test_clean_run_has_no_reasons_to_report(self):
        """A clean run carries no reasons, so format_alert_message cannot invent any.

        It is only called when severity >= warning; a stray default reason would put a
        reassuring line in a notification that exists precisely because something broke.
        """
        clean = _classify([], 2, None)
        self.assertEqual(clean["reasons"], [])
        self.assertNotIn("\n  - ", format_alert_message(clean))


if __name__ == "__main__":
    unittest.main()
