"""Hub-side access to What The Fact now that the hub `wtf` database is RETIRED.

On 2026-10-02 (PR #3591) the hub's `wtf` database was dropped: Citadel owns it. Eight places on the hub kept dialing it
(`dbname="wtf"` on archie_database) and failed ~3,000 times a day for 18 days (task #7372):

  * seven WTF backlog jobs + two orchestration "inject backlog depth" blocks   -> redundant, Citadel's wtf-ingest runs them
  * the ingest-freshness WATCHDOG (#4890)                                        -> was blind, so a real outage would not alert
  * signal_calendar_service headline grounding                                   -> fail-open, so posts were ungrounded
  * alert details / cross-watch search                                           -> best effort

This module is the single replacement. It deliberately uses NO database credential:
  * the PUBLIC API (`/api/v1/articles`, `/api/stats`) for liveness and headlines;
  * a default-OFF flag (`wtf_hub_backlog:enabled`) for the hub backlog jobs;
  * an optional `WTF_HUB_DATABASE_URL` (Citadel over the mesh, a READ-ONLY role, Phase B) for anything that truly needs SQL.
Never point this at the exposed `wtfuser` superuser.

WHY THE WATCHDOG USES THE ARTICLE COUNT AND NOT A TIMESTAMP (measured 2026-10-20, Citadel):
  * `published_at` cannot be trusted: 69% of recent rows have published_at = ingested_at + EXACTLY 2h (task #7373);
    it read 125 minutes "stale" while ingestion was 5 minutes old.
  * `ingested_at` is not exposed publicly, and its real gaps are large: p99.9 = 116 min, MAX = 202 min, 46 gaps > 90 min in
    14 days, around the clock (task #7374). The old 90-minute rule would have fired 46 times.
  * So the signal is "the published article count has not changed", and it only alerts after STALE_AFTER_MIN = 240 min
    (above the largest gap ever seen). It is a COARSE net for multi-hour outages (the 2026-07-14 freeze), not a replacement
    for the 90-minute DB check; the classifier-coverage check needs SQL and stays off until a read-only role exists.
"""

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: The work-control key (services/work_control_service.BACKLOGS): shows as a toggle in the DHQ Autonomy control center
#: and A.R.M.A.D.A. dispatch backlogs. platform_settings row: `work:wtf_hub_backlog:enabled`.
CONTROL_KEY = "wtf_hub_backlog"
FLAG_HUB_BACKLOG = f"work:{CONTROL_KEY}:enabled"

#: Largest ingestion gap observed in 14 days was 202 min; alert only beyond it.
STALE_AFTER_MIN = 240.0
#: Do not poll the public API more often than this, however often the watchdog ticks.
MIN_POLL_INTERVAL_S = 300.0
STALE_REALERT_S = 3600.0
BLIND_REALERT_S = 86400.0


class WtfApiError(RuntimeError):
    """The public WTF API could not be read. Carries no URL/credentials."""


class HubBacklogDisabled(Exception):
    """Control flow for guarded blocks: the hub WTF backlog is off (the normal state)."""


class WtfDbNotConfigured(RuntimeError):
    """No WTF_HUB_DATABASE_URL: nothing on the hub may dial a hub-local `wtf` database (it no longer exists)."""


# ── settings / config ────────────────────────────────────────────────────────────────────────────────
def hub_backlog_enabled() -> bool:
    """Default OFF, FAIL CLOSED. Citadel's wtf-ingest runs every backlog producer (verified 2026-10-20); the hub copies
    are retired. Reads the same work-control toggle the Autonomy control center writes, with default=False so the
    toggle can never render ON while the code is off (the 'switch that lies' pattern documented in work_control_service).
    """
    try:
        from services import work_control_service

        return bool(work_control_service.is_enabled(CONTROL_KEY, default=False))
    except Exception as exc:  # noqa: BLE001
        logger.debug("wtf_remote: work-control read failed (%s); treating hub backlog as OFF", type(exc).__name__)
        return False


def db_url() -> Optional[str]:
    return os.environ.get("WTF_HUB_DATABASE_URL") or None


def connect():
    """psycopg2 connection to the CONFIGURED WTF database, else WtfDbNotConfigured. Never logs the DSN."""
    url = db_url()
    if not url:
        raise WtfDbNotConfigured("WTF_HUB_DATABASE_URL is not set (the hub has no local wtf database since 2026-10-02)")
    import psycopg2

    return psycopg2.connect(url.replace("+psycopg2", ""), connect_timeout=8)


def api_base() -> str:
    return (os.environ.get("WTF_API_URL") or "https://what-the-fact.com").rstrip("/")


# ── public API ───────────────────────────────────────────────────────────────────────────────────────
def _get_json(path: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(api_base() + path, headers={"User-Agent": "archie-hub-watchdog/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https base
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        raise WtfApiError(f"{type(exc).__name__} reading {path.split('?')[0]}") from None
    if not isinstance(body, dict):
        raise WtfApiError(f"unexpected payload from {path.split('?')[0]}")
    return body


def article_count(timeout: float = 10.0) -> int:
    """Published (unsuppressed) article count: a live, uncached COUNT on Citadel."""
    body = _get_json("/api/stats", timeout)
    try:
        return int(body["articles"])
    except (KeyError, TypeError, ValueError):
        raise WtfApiError("no article count in /api/stats") from None


def latest_headlines(limit: int = 12, days: int = 2, timeout: float = 10.0) -> List[Tuple[str, str]]:
    """[(title, outlet_name)] newest first, from the public API. Used to GROUND generated posts in real coverage.

    `since` is applied on published_at, which is unreliable by up to a few hours (task #7373) but fine for a 2-day window.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%dT%H:%M:%S")
    query = urllib.parse.urlencode({"limit": max(1, min(100, int(limit))), "since": since})
    body = _get_json("/api/v1/articles?" + query, timeout)
    out: List[Tuple[str, str]] = []
    for item in body.get("articles") or []:
        title = str((item or {}).get("title") or "").strip()
        source = (item or {}).get("source") or {}
        outlet = (
            str(source.get("name") or source.get("slug") or "outlet").strip() if isinstance(source, dict) else "outlet"
        )
        if title:
            out.append((title, outlet))
    return out


# ── watchdog decision (pure) ─────────────────────────────────────────────────────────────────────────
@dataclass
class WatchdogState:
    # None == "never": a 0.0 sentinel would silently suppress the first alert on any small clock value.
    last_count: Optional[int] = None
    last_change_ts: float = 0.0
    last_poll_ts: Optional[float] = None
    last_stale_alert_ts: Optional[float] = None
    last_blind_alert_ts: Optional[float] = None


def watchdog_step(
    state: WatchdogState,
    now: float,
    fetch_count: Callable[[], int] = article_count,
    stale_after_min: float = STALE_AFTER_MIN,
) -> dict:
    """One watchdog tick. Returns {alert: None|'stale'|'blind', minutes_unchanged, error, polled}.

    * first observation after a (re)start is a BASELINE, never an alert: we cannot know how long it was unchanged;
    * ANY change in the count (up, or down via suppression) proves the pipeline is alive;
    * 'stale' fires once the count has not changed for > stale_after_min, then at most hourly;
    * 'blind' fires when the public API cannot be read at all, at most once a day: a monitor that cannot see must
      say so, loudly and once, instead of logging a warning every tick (that is how it stayed blind for 18 days).
    """
    if state.last_poll_ts is not None and now - state.last_poll_ts < MIN_POLL_INTERVAL_S:
        return {"alert": None, "minutes_unchanged": None, "error": None, "polled": False}
    state.last_poll_ts = now
    try:
        count = int(fetch_count())
    except Exception as exc:  # noqa: BLE001
        error = type(exc).__name__
        if state.last_blind_alert_ts is None or now - state.last_blind_alert_ts > BLIND_REALERT_S:
            state.last_blind_alert_ts = now
            return {"alert": "blind", "minutes_unchanged": None, "error": error, "polled": True}
        return {"alert": None, "minutes_unchanged": None, "error": error, "polled": True}

    if state.last_count is None or count != state.last_count:
        state.last_count, state.last_change_ts = count, now
        return {"alert": None, "minutes_unchanged": 0.0, "error": None, "polled": True}

    minutes = (now - state.last_change_ts) / 60.0
    if minutes > stale_after_min and (
        state.last_stale_alert_ts is None or now - state.last_stale_alert_ts > STALE_REALERT_S
    ):
        state.last_stale_alert_ts = now
        return {"alert": "stale", "minutes_unchanged": minutes, "error": None, "polled": True}
    return {"alert": None, "minutes_unchanged": minutes, "error": None, "polled": True}
