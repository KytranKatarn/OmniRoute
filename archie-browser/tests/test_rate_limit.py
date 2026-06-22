"""Unit tests for the sidecar per-profile token bucket (S6-P1-7a).

The old global ``_rate_lock`` + per-hour cap did ``time.sleep(up to 3600s)`` UNDER
the lock, serializing every profile — the mechanism behind the 2-day timeout cascade.
The bucket admits immediately or raises a NON-BLOCKING ``RateLimitError`` per key, so a
saturated profile never stalls the others. These tests inject time so they are fast +
deterministic and assert: bucket math, per-key isolation, retry_after, legacy fallback.

Run from archie-browser/:
    python3 -m pytest tests/test_rate_limit.py -v
"""

import os
import sys
import threading
from collections import deque
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")

import app as appmod  # noqa: E402


def _fake_app(max_per_hour=3, mode="bucket"):
    """Minimal app stand-in with only the attrs the rate limiter touches — avoids
    spinning up Flask / the create_app(testing=True) mock injection."""
    return SimpleNamespace(
        _rate_lock=threading.Lock(),
        _profile_buckets={},
        _rate_mode=mode,
        _max_per_hour=max_per_hour,
        _min_delay_s=0.0,  # no human-pacing sleep in tests
        _max_delay_s=0.0,
        _exec_times=deque(maxlen=100),
    )


class TestTokenBucket:
    def test_starts_full_admits_capacity(self):
        b = appmod._TokenBucket(3, now=0.0)
        assert b.consume(0.0) is None
        assert b.consume(0.0) is None
        assert b.consume(0.0) is None

    def test_rejects_after_capacity_with_retry_after(self):
        b = appmod._TokenBucket(3, now=0.0)
        for _ in range(3):
            b.consume(0.0)
        ra = b.consume(0.0)
        assert ra is not None and ra > 0
        # refill rate = 3/3600 tokens/sec → 1 token in 1200s
        assert abs(ra - 1200.0) < 1.0

    def test_refills_over_time(self):
        b = appmod._TokenBucket(3, now=0.0)
        for _ in range(3):
            b.consume(0.0)
        assert b.consume(0.0) is not None  # empty now
        assert b.consume(1200.0) is None  # one token back after 1200s

    def test_capacity_never_exceeds_max(self):
        b = appmod._TokenBucket(2, now=0.0)
        b.consume(0.0)
        # idle a long time — refill must cap at capacity, not overflow
        assert b.consume(1_000_000.0) is None
        assert b.consume(1_000_000.0) is None
        assert b.consume(1_000_000.0) is not None  # only 2 available, not 277


class TestApplyRateLimit:
    def test_bucket_per_key_isolation(self):
        a = _fake_app(max_per_hour=2)
        appmod._apply_rate_limit(a, 342)
        appmod._apply_rate_limit(a, 342)
        with pytest.raises(appmod.RateLimitError):
            appmod._apply_rate_limit(a, 342)
        # a DIFFERENT identity is unaffected — the whole point of the fix
        appmod._apply_rate_limit(a, 377)  # must NOT raise

    def test_rate_limit_error_carries_retry_after(self):
        a = _fake_app(max_per_hour=1)
        appmod._apply_rate_limit(a, 99)
        with pytest.raises(appmod.RateLimitError) as ei:
            appmod._apply_rate_limit(a, 99)
        assert ei.value.retry_after_s > 0

    def test_none_key_uses_default_bucket(self):
        a = _fake_app(max_per_hour=1)
        appmod._apply_rate_limit(a, None)
        with pytest.raises(appmod.RateLimitError):
            appmod._apply_rate_limit(a, None)

    def test_legacy_mode_does_not_raise_under_cap(self):
        # legacy mode keeps the old global behaviour; under the cap it never raises.
        a = _fake_app(max_per_hour=3, mode="legacy")
        appmod._apply_rate_limit(a, 1)
        appmod._apply_rate_limit(a, 1)
        assert len(a._exec_times) == 2  # legacy path appends to the global window
        assert a._profile_buckets == {}  # bucket path untouched in legacy mode
