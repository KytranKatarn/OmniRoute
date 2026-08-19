"""Bounded concurrency + in-flight dedup for on-demand article analysis (#5791).

STDLIB ONLY — no Flask, no SQLAlchemy, no project imports. That constraint is
deliberate: a guard test can ``exec_module`` this by path and can never silently
skip, which is how a whole suite once reported "passed" while every test in it was
skipping (KB #290497).

Why this exists. ``tech/routes.py:analyze_article`` spawned a daemon thread per
POST with no cap, no semaphore and no dedup — the only brake was the
``ai_analyzed`` cache hit, which by definition only helps for work already done.
On a 512m container that is unbounded work accepted from an unbounded caller.

PR #2687 bounded the TRIGGER at the consumer edge (``/api/proxy/articles/<id>/
analyze``, 5/hour), verified live. That reduces arrival rate; it does not bound
this. A caller spread across IPs, or any internal path reaching tech directly
rather than through the consumer proxy, still lands here.

Two independent protections, because they fail differently:

  * DEDUP — N simultaneous requests for the SAME article collapse to one thread.
    This is the common case (a user mashing the button, or several readers opening
    the same story) and costs nothing to serve: the second caller gets the same
    "queued" answer and polls the same status.
  * CAPACITY — a ceiling on DISTINCT articles analysing at once. This is the
    abuse/stampede case, and the honest answer is to refuse rather than accept
    work that will not complete.

PER-WORKER, like every other in-process limit in this codebase. ``Dockerfile.tech``
runs ``--workers 2``, so each gunicorn process holds its own guard and the true
aggregate is ``max_concurrent * workers``. ``effective_cap()`` divides an advertised
aggregate down so the number we reason about is the number that is real.
"""

from __future__ import annotations

import math
import threading

ACCEPTED = "accepted"
ALREADY_RUNNING = "already_running"
AT_CAPACITY = "at_capacity"


def effective_cap(total: int, workers: int) -> int:
    """Per-worker ceiling from an ADVERTISED aggregate.

    Never returns 0 — a rounding artifact must not make the endpoint permanently
    refuse every request.
    """
    if workers < 1:
        workers = 1
    if total < 1:
        return 1
    return max(1, math.floor(total / workers))


class AnalyzeGuard:
    """Thread-safe. One instance per gunicorn worker, held at module scope."""

    def __init__(self, max_concurrent: int = 3, workers: int = 1):
        self._max = effective_cap(max_concurrent, workers)
        self._lock = threading.Lock()
        self._inflight: set[int] = set()

    @property
    def max_concurrent(self) -> int:
        return self._max

    def try_acquire(self, article_id: int) -> str:
        """Reserve a slot. Returns ACCEPTED / ALREADY_RUNNING / AT_CAPACITY.

        Only ACCEPTED means the caller owns a slot and MUST later release it.
        The dedup check runs BEFORE the capacity check on purpose: a duplicate
        request for an already-running article should never be refused for
        capacity, since serving it costs no additional work.
        """
        with self._lock:
            if article_id in self._inflight:
                return ALREADY_RUNNING
            if len(self._inflight) >= self._max:
                return AT_CAPACITY
            self._inflight.add(article_id)
            return ACCEPTED

    def release(self, article_id: int) -> None:
        """Free a slot. Idempotent — releasing an unheld id is a no-op, never an
        error, so a double-release in an error path cannot corrupt the count."""
        with self._lock:
            self._inflight.discard(article_id)

    def in_flight(self) -> int:
        with self._lock:
            return len(self._inflight)

    def is_running(self, article_id: int) -> bool:
        with self._lock:
            return article_id in self._inflight
