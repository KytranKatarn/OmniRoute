"""
Throttled, retry-aware HTTP client for GEDS-SAGE scraping.

Spec: docs/superpowers/specs/2026-05-04-civic-transparency-phase1-geds.md
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

log = logging.getLogger(__name__)

GEDS_BASE = "https://geds-sage.gc.ca/en/GEDS"
USER_AGENT = "ARCHIE-CivicWatch/1.0 (+https://civic.kytranempowerment.com/about)"


class GedsFetchError(Exception):
    pass


class GedsClient:
    def __init__(
        self,
        rate_per_sec: float = 2.0,
        max_retries: int = 3,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.rate_per_sec = rate_per_sec
        self.max_retries = max_retries
        self._min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._last_request_at: float = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            base_url=GEDS_BASE,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.9"},
            timeout=httpx.Timeout(20.0, connect=10.0),
            transport=transport,
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    async def _throttle(self):
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def get(self, path_or_query: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            await self._throttle()
            try:
                resp = await self._client.get(path_or_query)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_exc = e
                log.warning("GEDS transport error attempt %s: %s", attempt, e)
                await asyncio.sleep(2**attempt)
                continue

            if resp.status_code == 429:
                # Adaptive backoff: halve rate, wait 60s, retry once.
                self._min_interval = max(self._min_interval * 2, 0.5)
                log.warning("GEDS 429; halving rate to %.2f/s", 1 / self._min_interval)
                await asyncio.sleep(60.0)
                continue

            if 500 <= resp.status_code < 600:
                last_exc = GedsFetchError(f"HTTP {resp.status_code}")
                await asyncio.sleep(2**attempt)
                continue

            if 400 <= resp.status_code < 500:
                raise GedsFetchError(f"HTTP {resp.status_code} (no retry)")

            return resp.text

        raise GedsFetchError(f"max retries exhausted: {last_exc}")
