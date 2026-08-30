"""UA-blind faceted-/news ceiling — the 2026-08-30 outage guard.

WHAT HAPPENED. A fleet walked /news facet permutations
(band x beat x province x riding x scope) at ~378 req/min sustained from
17:42-18:05, saturating all four gunicorn workers. what-the-fact.com served
502 to real readers.

WHY THE EXISTING GUARDS DID NOT FIRE — measured, not assumed:
  * ``_is_crawler_ua`` matches a NAMED-BOT ALLOWLIST (gptbot, claudebot,
    googlebot, bingbot, ...). The flooding UAs were ordinary browser strings —
    "Chrome/145.0.0.0 Edg/145.0.0.0" (6,913 hits) and "Mac OS X 10_15_7"
    (2,264) — which match NOTHING in it. So the tight 6/min/worker faceted
    guard never engaged. **A User-Agent is attacker-controlled; a guard keyed
    on one is opt-in.**
  * They therefore fell through to ``_news_rate_ok``, which is a deliberately
    generous 180/min PER IP. A handful of source IPs clears ~378/min easily.
  * ``_news_cache`` misses by construction: every distinct facet tuple is a new
    key, so each request is a fresh DB query. That is the whole point of a
    facet crawl.

THE FIX. ``_facet_any_rate_ok`` asks only "is this a faceted request?" — which
is what actually costs a query — and is blind to who claims to be sending it.

These tests pin BOTH directions. A limiter that only proves it blocks is half a
test: the far more likely production failure is throttling real readers, and
that would be invisible until someone complains.
"""

import importlib.util
import pathlib
import sys
import time
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def rl(monkeypatch):
    """Load ONLY the limiter functions out of routes.py.

    routes.py imports flask/db at module scope, so it cannot be imported in a
    bare unit test. The limiter is self-contained (time + a module-level list),
    so exec just those definitions — this keeps the test honest about testing
    THE SHIPPED CODE rather than a re-implementation of it.
    """
    src = (ROOT / "consumer" / "routes.py").read_text()
    start = src.index("_FACET_ANY_BUCKET: list = []")
    end = src.index("def _news_cache_get")
    mod = types.ModuleType("facet_rl")
    mod.__dict__["time"] = time
    mod.__dict__["os"] = __import__("os")
    exec(compile(src[start:end], "routes_facet_slice", "exec"), mod.__dict__)
    mod._FACET_ANY_BUCKET[:] = []
    return mod


class TestBlocksTheFlood:
    def test_bucket_stops_at_the_limit(self, rl):
        limit = rl._FACET_ANY_LIMIT
        allowed = sum(1 for _ in range(limit * 4) if rl._facet_any_rate_ok())
        assert allowed == limit, (
            f"expected exactly {limit} allowed in one window, got {allowed}"
        )

    def test_the_incident_rate_is_actually_bounded(self, rl):
        """~378 req/min hit the site. Per worker that is ~95/min against a
        30/min ceiling — the flood must be cut by roughly two thirds or more."""
        incident_per_worker = 95
        allowed = sum(1 for _ in range(incident_per_worker) if rl._facet_any_rate_ok())
        assert allowed <= rl._FACET_ANY_LIMIT
        assert allowed / incident_per_worker < 0.4, "flood not meaningfully bounded"

    def test_a_browser_ua_is_no_longer_a_bypass(self):
        """The whole point: this guard never inspects the User-Agent.

        Read from the file rather than inspect.getsource — the fixture execs a
        slice, so the function object carries no retrievable source.
        """
        src = (ROOT / "consumer" / "routes.py").read_text()
        start = src.index("def _facet_any_rate_ok")
        body = src[start:src.index("\ndef ", start + 1)]
        assert "User-Agent" not in body and "_is_crawler_ua" not in body, (
            "the ceiling must stay UA-blind — a UA is attacker-controlled"
        )


class TestDoesNotThrottleRealReaders:
    def test_a_human_changing_filters_is_never_blocked(self, rl):
        """A reader flipping through filters does maybe 10 faceted views a
        minute. That must sail through with room to spare."""
        human = 10
        assert all(rl._facet_any_rate_ok() for _ in range(human))

    def test_the_window_rolls_so_traffic_recovers(self, rl, monkeypatch):
        fake = {"t": 1_000_000.0}
        monkeypatch.setattr(rl.time, "time", lambda: fake["t"])
        for _ in range(rl._FACET_ANY_LIMIT):
            rl._facet_any_rate_ok()
        assert rl._facet_any_rate_ok() is False, "should be saturated"
        fake["t"] += 61  # window passes
        assert rl._facet_any_rate_ok() is True, "must recover after the window"

    def test_limit_sits_well_above_human_and_below_the_flood(self, rl):
        assert 10 < rl._FACET_ANY_LIMIT < 95, (
            f"{rl._FACET_ANY_LIMIT}/min/worker should exceed human browsing but "
            "bind the incident rate"
        )


class TestFailsOpen:
    def test_a_broken_limiter_never_takes_the_page_down(self, rl, monkeypatch):
        """Fail-open is deliberate: a bug in the guard must not cause the very
        outage the guard exists to prevent."""
        def boom():
            raise RuntimeError("clock exploded")
        monkeypatch.setattr(rl.time, "time", boom)
        assert rl._facet_any_rate_ok() is True


class TestWiredIntoTheRoute:
    """A limiter that is never called is not a limiter."""

    def test_route_calls_the_ceiling_for_faceted_requests(self):
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert "_facet_any_rate_ok()" in src
        news = src[src.index("def news():"):src.index("def news():") + 4000]
        assert "_facet_any_rate_ok" in news, "ceiling not wired into /news"
        assert "_req.args and not _facet_any_rate_ok()" in news, (
            "must gate on the presence of query args — clean /news is never throttled"
        )

    def test_clean_news_is_never_throttled(self):
        """Only faceted requests are bounded; the plain page must stay open."""
        src = (ROOT / "consumer" / "routes.py").read_text()
        assert "_req.args and not _facet_any_rate_ok()" in src


class TestWorkerRecycling:
    """The flood stopped at 18:05; the site was still 502 at 18:15 on 2-9
    req/min. The workers were WEDGED, not busy — they never self-healed."""

    def test_dockerfile_recycles_workers(self):
        df = (ROOT / "Dockerfile.consumer").read_text()
        assert "--max-requests" in df, "workers must recycle so the pool self-heals"
        assert "--max-requests-jitter" in df, (
            "without jitter all workers recycle together and hand Caddy a 502"
        )
