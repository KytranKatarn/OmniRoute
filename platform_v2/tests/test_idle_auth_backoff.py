r"""#5845 — a permanently-rejected credential must back off, not hammer the mail server.

Measured 2026-08-19: `kytran@kytranempowerment.com` produced 215 IMAP auth failures in 3
hours while every other mailbox authenticated fine. The IDLE loop treated
`[AUTHENTICATIONFAILED]` exactly like a socket timeout — `time.sleep(60)` and retry, forever.

That is not resilience, it is a credential-guessing loop, and it is dangerous HERE
specifically: KB #290279 records a single "Invalid IMAP command" causing Stalwart to ban an
internal IP for 20 HOURS across EVERY listener, which took all 156 mailboxes down. A
hundreds-per-day failed-auth stream from one container IP is that same shape.

The fix backs OFF without giving UP: 5 min -> 1 h, resetting on the next successful login so
a corrected password self-heals with no restart. The classifier is deliberately narrow — only
an explicit credential rejection is "permanent", because misreading a transient fault that way
would silently slow a healthy mailbox.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.email_manager import idle_worker  # noqa: E402
from tools.email_manager.idle_worker import (  # noqa: E402
    _AUTH_FAIL_BACKOFF_MAX,
    _AUTH_FAIL_BACKOFF_START,
    _RETRY_DELAY,
    _TRANSIENT_FAST_ATTEMPTS,
    is_permanent_auth_failure,
    retry_delay_for,
)


class TestClassifier(unittest.TestCase):
    def test_credential_rejection_is_permanent(self):
        for t in (
            "[AUTHENTICATIONFAILED] Authentication failed",
            b"[AUTHENTICATIONFAILED] Authentication failed",
            "AUTHORIZATIONFAILED",
            "Invalid credentials",
            "authentication failed",
        ):
            self.assertTrue(is_permanent_auth_failure(t), t)

    def test_transient_faults_are_not_permanent(self):
        """Misreading these as permanent would silently slow a HEALTHY mailbox — the
        direction that costs mail delivery rather than log noise."""
        for t in (
            "socket timeout",
            "BYE Server shutting down",
            "command SELECT illegal in state AUTH",
            "connection reset by peer",
            "",
            None,
        ):
            self.assertFalse(is_permanent_auth_failure(t), t)

    def test_backoff_window_is_sane(self):
        self.assertGreater(_AUTH_FAIL_BACKOFF_START, _RETRY_DELAY)
        self.assertGreater(_AUTH_FAIL_BACKOFF_MAX, _AUTH_FAIL_BACKOFF_START)


class TestRetryDelayLadder(unittest.TestCase):
    """Raised in review of PR #2718: the classifier is deliberately narrow, so a credential
    rejection phrased some OTHER way would read as transient and fall back to retrying every
    60s forever — exactly the hammering this change exists to stop. Widening the regex would
    trade a false negative for a false POSITIVE, and a false positive silently slows a
    HEALTHY mailbox. So EVERY persistent failure escalates; the classifier only sets the
    speed."""

    def test_permanent_starts_long_and_caps(self):
        d = [retry_delay_for(n, True) for n in range(1, 9)]
        self.assertEqual(d[0], _AUTH_FAIL_BACKOFF_START)
        self.assertEqual(d, sorted(d), "must be monotonic")
        self.assertEqual(max(d), _AUTH_FAIL_BACKOFF_MAX)

    def test_transient_gets_fast_tries_then_escalates(self):
        fast = [retry_delay_for(n, False) for n in range(1, _TRANSIENT_FAST_ATTEMPTS + 1)]
        self.assertTrue(all(x == _RETRY_DELAY for x in fast), fast)
        self.assertGreater(retry_delay_for(_TRANSIENT_FAST_ATTEMPTS + 1, False), _RETRY_DELAY)

    def test_an_UNRECOGNISED_permanent_failure_cannot_hammer_forever(self):
        """The review's actual concern: a rejection the regex misses still stops hammering."""
        self.assertEqual(retry_delay_for(50, False), _AUTH_FAIL_BACKOFF_MAX)

    def test_transient_is_capped_too(self):
        self.assertLessEqual(max(retry_delay_for(n, False) for n in range(1, 40)), _AUTH_FAIL_BACKOFF_MAX)

    def test_zero_and_negative_are_safe(self):
        self.assertEqual(retry_delay_for(0, False), _RETRY_DELAY)
        self.assertEqual(retry_delay_for(-3, True), _AUTH_FAIL_BACKOFF_START)


class _Stop(Exception):
    """Breaks the worker's `while True` after enough iterations."""


class TestIdleLoopBackoff(unittest.TestCase):
    """Drives the real loop with a mocked imaplib, so this pins BEHAVIOUR, not constants."""

    def _run(self, login_error, iterations=5):
        slept = []

        def fake_sleep(n):
            slept.append(n)
            if len(slept) >= iterations:
                raise _Stop()

        class FakeIMAP:
            def __init__(self, *a, **k):
                pass

            def login(self, u, p):
                raise login_error

            def send(self, *a, **k):
                pass

            def logout(self):
                pass

        with mock.patch.object(idle_worker.imaplib, "IMAP4_SSL", FakeIMAP), mock.patch.object(
            idle_worker.time, "sleep", fake_sleep
        ):
            try:
                idle_worker._idle_loop(1, "someone@example.com", "pw")
            except _Stop:
                pass
        return slept

    def test_permanent_failure_backs_off_and_caps(self):
        err = idle_worker.imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Authentication failed")
        slept = self._run(err, iterations=8)
        self.assertEqual(slept[0], _AUTH_FAIL_BACKOFF_START)
        self.assertGreater(slept[1], slept[0], "delay must grow")
        self.assertLessEqual(max(slept), _AUTH_FAIL_BACKOFF_MAX, "must be capped")
        # Total wait across 8 attempts is vastly larger than the old fixed 60s loop.
        self.assertGreater(sum(slept), 8 * _RETRY_DELAY * 5)

    def test_transient_failure_keeps_the_fast_retry(self):
        """A healthy-but-flaky mailbox must NOT be slowed to the auth backoff."""
        err = idle_worker.imaplib.IMAP4.error("command SELECT illegal in state AUTH")
        slept = self._run(err, iterations=4)
        self.assertTrue(all(s == _RETRY_DELAY for s in slept), slept)

    def test_non_imap_exception_keeps_the_fast_retry(self):
        slept = self._run(OSError("connection reset"), iterations=3)
        self.assertTrue(all(s == _RETRY_DELAY for s in slept), slept)


if __name__ == "__main__":
    unittest.main()
