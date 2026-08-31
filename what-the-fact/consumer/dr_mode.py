"""DR degraded mode — serve the archive from the local replica when the hub is gone.

OWNER DECISION 2026-08-31 (#6216). Citadel is the DR warm-standby and serves five
live products, so it does NOT carry an 8GB inference model. WTF was previously
FIRST in _WTF_CPU_FIRST on the theory that it could take over if the LAN cluster
went down — but `can_node_run_model(Citadel, 'qwen2.5:7b')` is False (cap 6 <
required 8.0), so that fallback never existed. Citadel has been removed from that
tier; this module is what replaces it.

WHAT IS ACTUALLY AVAILABLE (measured on Citadel 2026-08-31, not assumed):

    wtf database on archie_dr_replica ...... 5,937 MB
    articles ............................... 122,202  (newest 13:19 same day)
    bias_scores ............................ 122,202  (every article scored)
    story_clusters .........................  95,285
    pg_is_in_recovery ...................... t
    replay lag ............................. 1.7 seconds

So a hub outage does NOT mean "WTF is down". It means the SITE IS READ-ONLY and
~seconds stale: every article, every bias score and every cluster is already
replicated locally, and all the AI analysis was computed BEFORE the outage, so
displaying it needs no LLM at all.

WHAT IS GENUINELY LOST while degraded:
  - new articles (ingest needs the hub bridge)
  - new analysis — no LLM, by design
  - ALL WRITES. The replica is a physical standby; Postgres rejects writes on it.
    Newsletter signup, alerts and anything else that INSERTs must fail visibly and
    politely, not 500.

⚠️ THE HONEST BANNER IS "live updates paused", NOT "we are down". Telling readers
the site is down while serving them 122k complete articles is its own kind of lie.

⚠️ NO FALLBACK CONFIGURED == TODAY'S BEHAVIOUR, EXACTLY. If WTF_DATABASE_URL_FALLBACK
is unset this module returns the primary engine and nothing else changes — no probe,
no extra latency, no new failure mode.
"""
import logging
import os
import threading
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

logger = logging.getLogger(__name__)

# How long to wait before re-probing the primary once degraded. Recovery must be
# AUTOMATIC — a site that stays on the replica after the hub returns is an outage
# nobody is paged for.
_REPROBE_SECONDS = 60

_lock = threading.Lock()
_primary = None
_fallback = None
_state = {
    "mode": "primary",      # primary | degraded
    "since": None,          # epoch seconds when degraded began
    "last_probe": 0.0,
    "last_error": None,
}


def _url_primary():
    return os.environ.get("WTF_DATABASE_URL")


def _url_fallback():
    """The local DR replica, read-only. Unset in normal deployments."""
    return os.environ.get("WTF_DATABASE_URL_FALLBACK")


def _engine_for(url):
    # pool_pre_ping so a connection killed during an outage is discarded rather
    # than handed to a request.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


def _probe(engine) -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_engine():
    """Return the engine to use right now.

    Fails FORWARD: the primary is used until it actually errors, so the happy
    path costs nothing extra — no per-request probe.
    """
    global _primary, _fallback
    with _lock:
        if _primary is None:
            _primary = _engine_for(_url_primary())

        fb_url = _url_fallback()
        if not fb_url:
            return _primary        # unconfigured -> today's behaviour, exactly

        if _state["mode"] == "primary":
            return _primary

        # Degraded: periodically check whether the hub is back.
        now = time.time()
        if now - _state["last_probe"] >= _REPROBE_SECONDS:
            _state["last_probe"] = now
            if _probe(_primary):
                logger.warning("dr_mode: primary recovered — leaving degraded mode")
                _state.update(mode="primary", since=None, last_error=None)
                return _primary

        if _fallback is None:
            _fallback = _engine_for(fb_url)
        return _fallback


def note_failure(exc: Exception) -> bool:
    """Record a DB failure; return True if we switched to the replica.

    ⚠️ Only CONNECTION-level failures trigger degradation. A bad query, a missing
    column or a constraint violation is a BUG, and silently rerouting it to the
    replica would hide the bug and produce two different behaviours for the same
    request depending on invisible state.
    """
    if not _url_fallback():
        return False
    if not isinstance(exc, (OperationalError, DBAPIError)):
        return False
    # OperationalError covers connection refused / server closed / timeout.
    # A DBAPIError that is NOT connection-related must not degrade us.
    if isinstance(exc, DBAPIError) and not isinstance(exc, OperationalError):
        if not getattr(exc, "connection_invalidated", False):
            return False

    with _lock:
        if _state["mode"] == "degraded":
            return True
        logger.error("dr_mode: primary unreachable (%s) — serving read-only archive "
                     "from the DR replica", exc.__class__.__name__)
        _state.update(mode="degraded", since=time.time(),
                      last_probe=0.0, last_error=str(exc)[:200])
    return True


def is_degraded() -> bool:
    return _state["mode"] == "degraded"


def status() -> dict:
    """For the banner, /health and the ops surface.

    `configured` is reported separately from `degraded` on purpose: a deployment
    with no fallback is not "healthy", it is UNPROTECTED, and those are different
    facts an operator needs to tell apart.
    """
    since = _state["since"]
    return {
        "mode": _state["mode"],
        "degraded": _state["mode"] == "degraded",
        "configured": bool(_url_fallback()),
        "degraded_since": since,
        "degraded_seconds": int(time.time() - since) if since else 0,
        "last_error": _state["last_error"],
        # Said plainly so no caller has to invent the wording — and so the two
        # honest facts (complete archive / no live updates) stay together.
        "banner": (
            "Live updates paused — showing the complete archive as last "
            "synchronised. New articles and AI analysis resume when the "
            "newsroom reconnects."
        ) if _state["mode"] == "degraded" else None,
    }


def reset_for_tests():
    global _primary, _fallback
    with _lock:
        _primary = None
        _fallback = None
        _state.update(mode="primary", since=None, last_probe=0.0, last_error=None)
