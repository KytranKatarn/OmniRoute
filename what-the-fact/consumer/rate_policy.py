"""Rate-limit and route-classification policy for the public WTF edge.

STDLIB ONLY — no Flask, no SQLAlchemy, no project imports.

That constraint is load-bearing, not stylistic.  ``tests/test_aurora_provenance.py``
records that a guard helper which exec'd ``consumer/routes.py`` pulled in Flask, and on
any machine without it *every* test below it reported ``s`` (skipped) while the suite
still printed "passed" (KB #290497).  A test can ``exec_module`` this file by path and
can never skip, so the decisions below are actually verified.

Why this module exists (measured 2026-08-18, tasks #5747 / #5748):

  * 19 of 29 ``/api/*`` routes in ``consumer/routes.py`` had no rate limit at all.
    ``/api/proxy/articles/<id>/analyze`` is a POST with no auth and no limit that
    enqueues LLM work on the hub — the hub that runs the whole platform.
  * ``featured_story`` bucketed by ``request.remote_addr``, which behind Caddy is the
    *gateway* IP for every visitor, so all traffic worldwide shared ONE bucket and a
    single caller could 429 everybody.
  * ``_API_RATE_BUCKETS`` never evicted idle IPs, so the limiter's own dict grew without
    bound.

The bucket algorithm here is lifted verbatim from the original ``_api_rate_ok`` so that
behaviour on the ``default`` tier is unchanged.
"""

from __future__ import annotations

import math

# ── Policy table ──────────────────────────────────────────────────────────────
#
# tier -> (requests, window_seconds).  These are AGGREGATE limits — the value a
# caller actually experiences across all gunicorn workers.  effective_limit()
# converts each to the per-worker number the in-process buckets enforce.
#
# Read tiers keep the long-standing 60/60s so no existing public consumer is
# newly throttled.  Only work that costs the hub real compute, or that writes,
# gets a small budget.
POLICY: dict[str, tuple[int, int]] = {
    "default": (60, 60),        # /api/v1/* reads — unchanged from before
    "proxy_read": (60, 60),     # cross-watch + /api/proxy/* reads (hub DB queries)
    "write": (10, 3600),        # /flag, /newsletter/subscribe — anonymous writes
    "expensive": (5, 3600),     # /analyze — spawns LLM work on the hub
}

DEFAULT_TIER = "default"

# Route classification.  Order matters: the first matching rule wins, so the
# expensive/write rules are checked before the generic read prefixes.
#
# Matching is on the URL PATH, using the concrete request path (e.g.
# "/api/proxy/articles/12345/analyze"), not the Flask rule template — the caller
# has the real path and templates vary ("<int:article_id>" vs "<article_id>").
_RULES: tuple[tuple[str, str], ...] = (
    # (needle, tier) — needle is a substring test against the path
    ("/analyze", "expensive"),
    ("/flag", "write"),
    ("/newsletter/subscribe", "write"),
    ("/api/cross-watch/", "proxy_read"),
    ("/api/proxy/", "proxy_read"),
)

# An "/analyze/status" poll is a cheap read — it must NOT inherit the expensive
# tier from the "/analyze" needle, or the UI's own progress polling would 429
# itself after 5 checks.  Checked before _RULES.
_EXEMPT_SUFFIXES: tuple[str, ...] = ("/analyze/status",)


def classify(path: str) -> str:
    """Map a request path to a policy tier name.

    Unknown paths fall back to ``default`` — never to "unlimited".  A route that
    nobody classified should still be bounded.
    """
    if not path:
        return DEFAULT_TIER
    for suffix in _EXEMPT_SUFFIXES:
        if path.endswith(suffix):
            return "proxy_read"
    for needle, tier in _RULES:
        if needle in path:
            return tier
    return DEFAULT_TIER


def limits_for(tier: str) -> tuple[int, int]:
    """Return (limit, window_seconds) for a tier, falling back to default."""
    return POLICY.get(tier, POLICY[DEFAULT_TIER])


def effective_limit(total_limit: int, workers: int) -> int:
    """Convert an ADVERTISED aggregate limit into the per-worker limit to enforce.

    The buckets are per-gunicorn-process dicts and the consumer runs
    ``--workers 4`` (``Dockerfile.consumer``), so a limit of 60 enforced in each
    worker let a caller through roughly 240 times.  Dividing makes the number we
    publish the number that is actually true.

    This is statistical, not exact: gunicorn spreads a single client's
    connections across workers, so a caller sending the aggregate limit lands
    ~limit/workers on each.  A client unlucky enough to be pinned to one worker
    gets the per-worker share.  That approximation is deliberate and is why the
    read tiers stay generous.

    Never returns 0 — a rounding artifact must not lock everyone out.
    """
    if workers < 1:
        workers = 1
    if total_limit < 1:
        return 1
    return max(1, math.floor(total_limit / workers))


def bucket_allow(
    bucket: list, now: float, limit: int, window: int
) -> tuple[bool, int]:
    """Rolling-window check against one caller's timestamp list.

    Mutates ``bucket`` in place: expired entries are dropped, and an allowed
    request appends ``now``.  Returns ``(allowed, retry_after_seconds)``;
    ``retry_after`` is 0 when allowed.

    Algorithm preserved verbatim from the original ``_api_rate_ok`` so the
    default tier behaves exactly as it did before this module existed.
    """
    cutoff = now - window
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= limit:
        oldest = bucket[0]
        retry = int(window - (now - oldest)) + 1
        return False, max(1, retry)
    bucket.append(now)
    return True, 0


def prune(buckets: dict, now: float, window: int, max_keys: int) -> int:
    """Bound the bucket dict. Returns the number of keys removed.

    Two passes, cheapest first:

    1. Drop any caller whose most recent request is older than the window — they
       are fully expired and carry no state.
    2. If still over ``max_keys``, drop the least-recently-active callers until
       under the cap.

    Step 2 is deliberately last-resort: evicting a live caller resets their
    budget, so it only happens under genuine key pressure, and it evicts the
    QUIETEST callers first — an active abuser is the last one to have their
    bucket forgiven.
    """
    if not buckets:
        return 0

    removed = 0
    cutoff = now - window

    for ip in [ip for ip, ts in buckets.items() if not ts or ts[-1] <= cutoff]:
        del buckets[ip]
        removed += 1

    if len(buckets) > max_keys:
        # Sort by last-seen ascending; the quietest go first.
        ordered = sorted(buckets.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
        for ip, _ in ordered[: len(buckets) - max_keys]:
            del buckets[ip]
            removed += 1

    return removed
