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

from flask import request

from . import rate_policy

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
        advertised, window = rate_policy.limits_for(tier)
        per_worker = rate_policy.effective_limit(advertised, WORKERS)

        now = time.time()
        key = f"{tier}:{client_ip()}"
        bucket = BUCKETS.setdefault(key, [])
        allowed, retry = rate_policy.bucket_allow(bucket, now, per_worker, window)

        _calls_since_prune += 1
        if _calls_since_prune >= _PRUNE_EVERY:
            _calls_since_prune = 0
            # Prune against the LONGEST window in the policy: a short-window key
            # is expired by definition once the longest window has passed, but
            # the reverse is not true — pruning on 60s would forget an hourly
            # write budget after a minute and hand an abuser a fresh one.
            longest = max(w for _, w in rate_policy.POLICY.values())
            rate_policy.prune(BUCKETS, now, longest, MAX_BUCKET_KEYS)

        return allowed, retry, advertised, window
    except Exception:  # pragma: no cover - defensive
        return True, 0, 0, 0
