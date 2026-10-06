"""Retry a single HTTP fetch across a short outage — and ONLY a short, transient one.

2026-10-04: ourcommons.ca had a brief outage and two weekly feeds each failed on their first request
(committees: HTTP 403 on the list page; mp_expenses: nothing fetched, "upserted 0 rows"). Both worked
again within hours with no code change, but the drift guard had already paged on a ``last run FAILED``
row. One request, no retry, turned a blip into an alarm.

What is retried: connection errors, timeouts, and HTTP 403/408/429/5xx (403 is included because it WAS the
transient symptom here, and the cost of one extra try against a real block is two short sleeps).
What is NOT retried: any other 4xx. A 404 is an answer — four committee pages (AMAD, BCAN, BILI, REGS)
404 permanently and must fail fast, not three times each.

The last exception is re-raised unchanged, so callers' existing ``except`` blocks and error messages
(``committee list fetch failed: HTTP Error 403: Forbidden``) read exactly as before.
"""
from __future__ import annotations

import logging
import socket
import time
import urllib.error

logger = logging.getLogger(__name__)

RETRY_HTTP_CODES = frozenset({403, 408, 429, 500, 502, 503, 504})
DEFAULT_DELAYS = (2.0, 6.0)  # sleeps between attempts => 3 attempts, ~8s worst case


def _transient(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):  # must precede URLError: HTTPError subclasses it
        return exc.code in RETRY_HTTP_CODES
    return isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError))


def fetch_with_retry(fetch, *, delays=DEFAULT_DELAYS, label: str = "fetch"):
    """Call ``fetch()`` (a zero-argument callable); retry transient failures after each delay in ``delays``."""
    attempts = len(delays) + 1
    for attempt in range(attempts):
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001 — classified just below, re-raised if not transient
            if attempt == attempts - 1 or not _transient(exc):
                raise
            logger.warning("%s: transient failure (%s) — retry %d/%d in %.0fs",
                           label, exc, attempt + 1, attempts - 1, delays[attempt])
            time.sleep(delays[attempt])
