"""Flask glue for the public-edge rate limiter (tasks #5747 / #5748).

Thin by design: all the decision logic lives in the stdlib-only
``consumer.rate_policy`` so it can be unit-tested without Flask (KB #290497).
This module owns only the process-local bucket store and the request plumbing.

It deliberately returns a plain tuple rather than a Flask ``Response``: the two
callers render errors differently (``routes.py`` uses ``_api_cors_response``,
``cross_watch.py`` uses bare ``jsonify``), and keeping response shape out of here
avoids importing ``routes`` from ``cross_watch`` — which would be an import cycle.

STATE IS PER-WORKER.  ``Dockerfile.consumer`` runs ``--workers 4``, so each
gunicorn process holds its own ``BUCKETS``.  ``rate_policy.effective_limit()``
divides the advertised aggregate limit by the worker count so the number we
publish is the number a caller actually experiences.  See the docstring there for
why that is statistical rather than exact.
"""

from __future__ import annotations

import os
import time

from flask import g, request

from . import rate_policy

# Header the public API reads a key from. Authorization: Bearer <key> is accepted
# too, because that is what every HTTP client already knows how to send.
API_KEY_HEADER = "X-API-Key"

# Shared bucket store: caller-key -> [timestamps].
# `routes.py` aliases this as _API_RATE_BUCKETS so its existing /news and
# crawler-facet buckets keep working against the same dict.
BUCKETS: dict = {}

# How many gunicorn workers are serving this app. Must match the --workers value
# in Dockerfile.consumer (4) / the ingest-api override (2), else the advertised
# limit drifts from the enforced one again.
WORKERS = int(os.environ.get("WTF_GUNICORN_WORKERS", "4"))

# Bound the bucket dict. The old limiter never evicted idle IPs, so its own
# growth was a slow memory-exhaustion vector on a 512m container.
MAX_BUCKET_KEYS = int(os.environ.get("WTF_RATE_BUCKET_MAX_KEYS", "20000"))
_PRUNE_EVERY = int(os.environ.get("WTF_RATE_PRUNE_EVERY", "500"))
_calls_since_prune = 0


def client_ip() -> str:
    """Real client IP behind Caddy.

    ``request.remote_addr`` is the GATEWAY for every visitor — using it buckets
    the whole internet together, which is exactly the bug this work fixes in
    ``featured_story``. X-Forwarded-For first hop is the client.
    """
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def presented_key() -> str | None:
    """Pull an API key off the request, from either accepted header."""
    raw = request.headers.get(API_KEY_HEADER)
    if raw:
        return raw.strip()
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def caller_plan() -> tuple[str, str | None]:
    """(plan, key_prefix) for this request, resolved at most ONCE.

    Cached on ``flask.g`` because a request can consult the limiter more than
    once and each miss would otherwise be a fresh DB round-trip on the hot path.

    Fails toward LESS privilege in every direction: no key, bad key, revoked key,
    unreachable database, or an import problem all yield ``anonymous``. The
    limiter fails open for AVAILABILITY; privilege must fail closed, or an outage
    becomes an escalation.
    """
    cached = getattr(g, "_wtf_caller_plan", None)
    if cached is not None:
        return cached

    plan, prefix = "anonymous", None
    try:
        raw = presented_key()
        if raw:
            from .routes import _db
            from . import api_keys as _ak
            plan, prefix = _ak.resolve_plan(_db(), raw)
            if prefix:
                _ak.touch(_db(), prefix)
    except Exception:  # pragma: no cover - defensive
        plan, prefix = "anonymous", None

    # A paid browser session upgrades a caller even without a key, so an
    # entitlement someone paid for is never withheld pending a setup step.
    try:
        from .auth import is_subscriber
        if is_subscriber():
            plan = rate_policy.higher_plan(plan, "paid")
    except Exception:  # pragma: no cover - defensive
        pass

    result = (plan, prefix)
    try:
        g._wtf_caller_plan = result
    except Exception:  # pragma: no cover - outside an app context
        pass
    return result


def check(path: str | None = None, tier: str | None = None) -> tuple[bool, int, int, int]:
    """Consume one unit of the caller's budget for this route.

    Returns ``(allowed, retry_after, advertised_limit, window_seconds)``.
    ``advertised_limit`` is the aggregate figure to show a caller — not the
    per-worker number actually enforced — so error bodies and the public API
    docs agree with each other.

    Fail-open: any unexpected error allows the request. A limiter bug must never
    take the public site down.
    """
    global _calls_since_prune
    try:
        if tier is None:
            tier = rate_policy.classify(path or request.path)
        plan, prefix = caller_plan()
        advertised, window = rate_policy.limits_for(tier, plan)
        per_worker = rate_policy.effective_limit(advertised, WORKERS)

        now = time.time()
        # Bucket keyed callers by their KEY, not their IP: that is the whole
        # point of issuing keys. Two colleagues behind one NAT stop sharing a
        # budget, and one abusive client can be revoked without throttling the
        # office. Anonymous callers still bucket by IP.
        identity = f"key:{prefix}" if prefix else client_ip()
        key = f"{plan}:{tier}:{identity}"
        bucket = BUCKETS.setdefault(key, [])
        allowed, retry = rate_policy.bucket_allow(bucket, now, per_worker, window)

        _calls_since_prune += 1
        if _calls_since_prune >= _PRUNE_EVERY:
            _calls_since_prune = 0
            # Prune against the LONGEST window in the policy: a short-window key
            # is expired by definition once the longest window has passed, but
            # the reverse is not true — pruning on 60s would forget an hourly
            # write budget after a minute and hand an abuser a fresh one.
            # Must span EVERY plan, not just POLICY: the `score` tier runs on a
            # 86400s window while POLICY tops out at 3600, and pruning on the
            # shorter one hands an abuser a fresh daily budget every hour.
            rate_policy.prune(
                BUCKETS, now, rate_policy.longest_window(), MAX_BUCKET_KEYS
            )

        return allowed, retry, advertised, window
    except Exception:  # pragma: no cover - defensive
        return True, 0, 0, 0
