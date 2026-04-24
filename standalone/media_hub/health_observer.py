"""
Media Hub health observer — scheduled probes against configured services.

Two jobs, both running every 30 minutes on APScheduler:

1. ``service_health_probe`` — iterates ``media_hub_services`` rows, calls each
   client's ``probe()`` method, writes ``health_status`` + ``health_message`` +
   ``last_health_check`` back to the row. Catches the "row says healthy 2 days
   ago but the underlying service died" failure mode that let Prowlarr go blind
   for 7 days against NZBgeek (discovered 2026-04-21).

2. ``indexer_health_probe`` — polls Sonarr + Radarr ``/api/v3/health`` and
   Prowlarr ``/api/v1/indexerstatus`` directly so we catch long-term indexer
   failures before the user does. Alerts via stdout log (a hub-webhook
   integration comes later — see project #279).

Transitions (healthy ↔ unhealthy) are logged at WARNING so they show up in
``docker logs mediahub_app`` even without a hub-side alert channel.

Project #279 / tasks #2243 (indexer re-checker) + #2244 (services staleness).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger("media_hub.observer")


# --- shared helpers ---------------------------------------------------------

def _decrypt(key_encrypted: Optional[str]) -> str:
    if not key_encrypted:
        return ""
    from tools.media_hub.encryption import decrypt_api_key  # lazy

    try:
        return decrypt_api_key(key_encrypted)
    except Exception as e:
        log.error("decrypt_api_key failed: %s", e)
        return ""


def _services_rows():
    """Yield enabled service rows. Own DB connection so observer is
    independent of Flask app context (APScheduler threads have none)."""
    from database import get_db_cursor

    with get_db_cursor(cursor_factory=None) as (_conn, cur):
        cur.execute(
            """
            SELECT id, service_type, name, host, port, use_ssl,
                   api_key_encrypted, health_status
            FROM media_hub_services
            WHERE is_enabled = TRUE
            ORDER BY service_type
            """
        )
        return cur.fetchall()


def _write_health(service_id: int, status: str, message: str) -> None:
    from database import get_db_cursor

    with get_db_cursor(cursor_factory=None, commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE media_hub_services
               SET health_status = %s,
                   health_message = %s,
                   last_health_check = CURRENT_TIMESTAMP
             WHERE id = %s
            """,
            (status, message[:500], service_id),
        )


# --- observer job 1: services ---------------------------------------------

def service_health_probe() -> None:
    """Call each client's probe() and update media_hub_services row."""
    from tools.media_hub.services import get_service_client

    rows = _services_rows()
    log.info("service_health_probe: %d service(s) to check", len(rows))

    for row in rows:
        sid, stype, name, host, port, use_ssl, enc, prev_status = row
        try:
            client = get_service_client(stype, host, port, _decrypt(enc), use_ssl)
            ok, msg = client.probe()
            new_status = "healthy" if ok else "unhealthy"
            if new_status != (prev_status or "unknown"):
                log.warning(
                    "health transition: %s (%s) %s → %s: %s",
                    name, stype, prev_status, new_status, msg,
                )
            else:
                log.info("health ok: %s (%s): %s", name, stype, msg)
            _write_health(sid, new_status, msg)
        except Exception as e:
            log.exception("probe failed: %s (%s)", name, stype)
            _write_health(sid, "error", f"probe exception: {e}")


# --- observer job 2: indexers ---------------------------------------------

def _arr_health(stype: str, host: str, port: int, api_key: str, use_ssl: bool):
    """GET /api/v3/health on Sonarr/Radarr. Returns list of warnings/errors."""
    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/api/v3/health"
    try:
        r = requests.get(url, headers={"X-Api-Key": api_key}, timeout=8)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _prowlarr_indexer_status(host: str, port: int, api_key: str, use_ssl: bool):
    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/api/v1/indexerstatus"
    try:
        r = requests.get(url, headers={"X-Api-Key": api_key}, timeout=8)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as e:
        return None, str(e)


def indexer_health_probe() -> None:
    """Probe Sonarr/Radarr health + Prowlarr indexerstatus. Log anything
    that's been failing. Alerts land in docker logs for now — project #279
    tracks the hub-webhook integration."""
    rows = _services_rows()

    for row in rows:
        sid, stype, name, host, port, use_ssl, enc, _ = row
        key = _decrypt(enc)
        if not key:
            continue

        if stype in ("sonarr", "radarr"):
            health, err = _arr_health(stype, host, port, key, use_ssl)
            if err is not None:
                log.warning("indexer probe: %s unreachable (%s)", name, err)
                continue
            if not health:
                log.info("indexer probe: %s health = clean", name)
                continue
            for h in health:
                severity = (h.get("type") or "info").upper()
                source = h.get("source", "?")
                msg = h.get("message", "")
                log.warning(
                    "indexer probe: %s [%s] %s → %s",
                    name, severity, source, msg,
                )

        elif stype == "prowlarr":
            statuses, err = _prowlarr_indexer_status(host, port, key, use_ssl)
            if err is not None:
                log.warning("indexer probe: %s unreachable (%s)", name, err)
                continue
            if not statuses:
                log.info("indexer probe: %s indexerstatus = clean", name)
                continue
            # Prowlarr only lists indexers that are CURRENTLY failing.
            # Presence here = problem.
            for st in statuses:
                indexer_id = st.get("indexerId", "?")
                disabled_till = st.get("disabledTill", "?")
                cause = st.get("mostRecentFailure") or st.get("initialFailure") or "?"
                log.warning(
                    "indexer probe: prowlarr indexer %s failing (disabled until %s, cause=%s)",
                    indexer_id, disabled_till, cause,
                )


# --- M.A.V.E.N. diagnostic probe -------------------------------------------

# Shared cache so GET /maven/api/status can return the last probe result
# without re-running the full diagnostic on every request.
_last_diagnostic: dict = {"overall": "unknown", "summary": {}, "generated_at": None, "errors": []}


def maven_diagnostic_probe() -> None:
    """Run the full M.A.V.E.N. troubleshoot diagnostic chain every 30 min.

    On error-level findings:
    - Logs each error to stdout (captured by docker logs / V.I.G.I.L.)
    - Attempts to notify the platform hub via POST /api/notifications so
      A.R.C.H.I.E. can escalate to the user via Telegram.
    """
    import os

    global _last_diagnostic
    try:
        from maven.troubleshoot import run_diagnostic

        report = run_diagnostic()
        _last_diagnostic = {
            "overall": report["overall"],
            "summary": report["summary"],
            "generated_at": report["generated_at"],
            "errors": [c for c in report["checks"] if c["severity"] == "error"],
        }

        if report["overall"] == "error":
            error_titles = [c["title"] for c in _last_diagnostic["errors"]]
            log.warning(
                "M.A.V.E.N. diagnostic: %d error(s) — %s",
                len(error_titles),
                ", ".join(error_titles[:3]),
            )

            # Best-effort: notify the A.R.C.H.I.E. platform hub
            hub_url = os.getenv("ARCHIE_HUB_URL", "http://192.168.1.200:3000")
            api_key = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
            if api_key:
                try:
                    requests.post(
                        f"{hub_url}/api/notifications",
                        json={
                            "type": "warning",
                            "title": "M.A.V.E.N. — Media Hub alert",
                            "message": f"{len(error_titles)} issue(s): {', '.join(error_titles[:3])}",
                            "source": "media_hub_maven",
                            "priority": "high",
                        },
                        headers={"X-Internal-Key": api_key},
                        timeout=5,
                    )
                except Exception:
                    pass  # Platform unreachable — stdout log above is the fallback
        else:
            log.info("M.A.V.E.N. diagnostic: %s", report["overall"])
    except Exception as exc:
        log.error("maven_diagnostic_probe failed: %s", exc)


# --- scheduler wiring ------------------------------------------------------

_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler() -> BackgroundScheduler:
    """Idempotent — safe to call on every app boot; subsequent calls return
    the already-running scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    _scheduler.add_job(
        service_health_probe,
        "interval",
        minutes=30,
        id="service_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.utcnow(),  # fire once at startup
    )
    _scheduler.add_job(
        indexer_health_probe,
        "interval",
        minutes=30,
        id="indexer_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.utcnow(),
    )
    _scheduler.add_job(
        maven_diagnostic_probe,
        "interval",
        minutes=30,
        id="maven_diagnostic",
        max_instances=1,
        coalesce=True,
        # Offset 5 min from startup so service health runs first
        next_run_time=datetime.utcnow().replace(second=0, microsecond=0),
    )
    _scheduler.start()
    log.info("media hub observer scheduler started (jobs: service_health, indexer_health, maven_diagnostic, every 30m)")
    return _scheduler
