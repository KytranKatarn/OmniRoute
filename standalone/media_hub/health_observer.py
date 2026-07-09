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
from datetime import datetime, timezone
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
_seen_grab_ids: set = set()  # in-memory dedup for grab notifications


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
            hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
            api_key = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
            if api_key:
                try:
                    requests.post(
                        f"{hub_url}/api/internal/notify",
                        json={
                            "type": "warning",
                            "title": "M.A.V.E.N. — Media Hub alert",
                            "message": f"{len(error_titles)} issue(s): {', '.join(error_titles[:3])}",
                            "source": "media_hub_maven",
                            "priority": "high",
                        },
                        headers={"Authorization": f"Bearer {api_key}"},
                        timeout=5,
                    )
                except Exception:
                    pass  # Platform unreachable — stdout log above is the fallback
        else:
            log.info("M.A.V.E.N. diagnostic: %s", report["overall"])
    except Exception as exc:
        log.error("maven_diagnostic_probe failed: %s", exc)


# --- quality probe (every 12h) --------------------------------------------

def quality_probe() -> None:
    """Run movie quality + disk space audit every 12h.

    Logs flagged movies and attempts to notify the A.R.C.H.I.E. hub so
    A.R.C.H.I.E. can escalate to Kytran via Telegram.
    """
    import os

    try:
        from maven.quality import _get_movie_quality_report, check_disk_space

        flagged = [m for m in _get_movie_quality_report() if m.flagged]
        disk_issues = [c for c in check_disk_space() if c.severity != "ok"]

        if not flagged and not disk_issues:
            log.info("quality_probe: all movies within guidelines, disk healthy")
            return

        msgs = []
        for c in disk_issues:
            log.warning("quality_probe: disk — %s: %s", c.title, c.detail)
            msgs.append(f"{c.title}: {c.detail}")

        for m in flagged[:5]:
            log.warning(
                "quality_probe: flagged — %s (%s) %s %.1fGB: %s",
                m.title, m.year, m.quality, m.size_gb, m.reason,
            )
            msgs.append(f"{m.title} {m.size_gb:.0f}GB")

        if len(flagged) > 5:
            msgs.append(f"…+{len(flagged) - 5} more")

        hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
        api_key = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
        if api_key:
            try:
                requests.post(
                    f"{hub_url}/api/notifications",
                    json={
                        "type": "warning",
                        "title": "M.A.V.E.N. — Quality alert",
                        "message": (
                            f"{len(flagged)} oversized movie(s). "
                            f"{'; '.join(msgs[:3])}. "
                            f"Run /maven/api/upgrade-oversized to fix."
                        ),
                        "source": "media_hub_maven_quality",
                        "priority": "normal",
                    },
                    headers={"X-Internal-Key": api_key},
                    timeout=5,
                )
            except Exception:
                pass  # hub unreachable — stdout log is the fallback

    except Exception as exc:
        log.error("quality_probe failed: %s", exc)


# --- A.R.M.A.D.A. visibility helper (#4757) --------------------------------

def _log_selfheal(probe: str, capability: str, actions: list) -> None:
    """Record an autonomous self-heal in the DHQ A.R.M.A.D.A. dispatch feed
    (#4757) — one 0-token task_execution_log row per probe run that actually
    took a corrective action. No-op when the probe only observed or escalated
    without fixing (empty actions). Best-effort; never breaks the probe."""
    if not actions:
        return
    try:
        from archie_coordination import log_dispatch

        log_dispatch(
            probe,
            capability=capability,
            description=f"{probe}: " + "; ".join(str(a) for a in actions),
            success=True,
            metadata={"actions": list(actions)},
        )
    except Exception:  # noqa: BLE001 — visibility logging must never break a probe
        pass


# --- download pipeline probe (every 30 min) --------------------------------

def download_pipeline_probe() -> None:
    """Detect and auto-fix the download-to-import pipeline.

    Catches two failure modes discovered in production (2026-04-26):

    1. Import backlog — SABnzbd completed downloads but Sonarr/Radarr never
       imported them. Symptom: queue items stuck at ``timeleft == "00:00:00"``
       or ``status == "completed"``. Auto-fix: DownloadedEpisodesScan /
       DownloadedMoviesScan. Notifies A.R.C.H.I.E. either way so Kytran
       knows it happened.

    2. SABnzbd post-processing stall — active queue is empty but history has
       items stuck in ``"Queued"`` state, meaning the completion callback to
       arr services never fired. Cannot auto-fix; escalates to A.R.C.H.I.E.
       for Telegram alert to Kytran.
    """
    import os

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}

    issues: list[str] = []
    actions: list[str] = []
    needs_human = False

    # ---- SABnzbd stall check ----
    sab_row = by_type.get("sabnzbd")
    if sab_row:
        _, _, sab_name, host, port, use_ssl, enc, _ = sab_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api"
        try:
            q_resp = requests.get(base, params={"mode": "queue", "output": "json", "apikey": key}, timeout=8)
            queue = q_resp.json().get("queue", {})

            # ---- SABnzbd PAUSED auto-resume (task #4721) ----
            # A globally-paused download client silently stalls the ENTIRE
            # library (found 2026-07-07: 12 items stuck for days, incl. Rick &
            # Morty S9). Auto-resume instead of waiting for the owner to notice.
            # Recorded as issue+action so A.R.C.H.I.E. still notifies below (a
            # bare 'action' with no 'issue' returns before the notify block).
            if queue.get("paused") or queue.get("status") == "Paused":
                n_stuck = queue.get("noofslots", 0)
                issues.append(f"SABnzbd was PAUSED with {n_stuck} item(s) queued — downloads were stalled")
                log.warning("download_pipeline_probe: SABnzbd paused (%s queued) — auto-resuming", n_stuck)
                try:
                    r_res = requests.get(base, params={"mode": "resume", "apikey": key}, timeout=8)
                    if r_res.ok and r_res.json().get("status"):
                        actions.append("auto-resumed SABnzbd")
                    else:
                        needs_human = True
                except Exception as e:
                    log.warning("download_pipeline_probe: SABnzbd resume failed: %s", e)
                    needs_human = True

            sab_idle = queue.get("status") == "Idle" and not queue.get("slots")

            if sab_idle:
                h_resp = requests.get(base, params={"mode": "history", "limit": 50, "output": "json", "apikey": key}, timeout=8)
                stuck = [s for s in h_resp.json().get("history", {}).get("slots", []) if s.get("status") == "Queued"]
                if stuck:
                    msg = f"SABnzbd idle but {len(stuck)} item(s) stuck in post-processing ('Queued' in history)"
                    issues.append(msg)
                    log.warning("download_pipeline_probe: %s — attempting restart", msg)
                    import shutil, subprocess as _sp
                    if shutil.which("docker"):
                        res = _sp.run(["docker", "restart", "media_sabnzbd"], capture_output=True, timeout=30)
                        if res.returncode == 0:
                            actions.append("restarted SABnzbd to clear post-processing stall")
                        else:
                            needs_human = True
                    else:
                        needs_human = True
        except Exception as e:
            log.warning("download_pipeline_probe: SABnzbd check error: %s", e)

    # ---- Sonarr import gap check + auto-fix ----
    sonarr_row = by_type.get("sonarr")
    if sonarr_row:
        _, _, sonarr_name, host, port, use_ssl, enc, _ = sonarr_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"
        try:
            r = requests.get(
                f"{base}/queue",
                params={"apikey": key, "pageSize": 200, "includeSeries": "true", "includeEpisode": "true"},
                timeout=10,
            )
            records = r.json().get("records", [])
            stuck = [
                rec for rec in records
                if rec.get("status") in ("completed", "downloading") and rec.get("timeleft") == "00:00:00"
            ]
            if stuck:
                msg = f"Sonarr: {len(stuck)} episode(s) downloaded but not imported"
                issues.append(msg)
                log.warning("download_pipeline_probe: %s — triggering DownloadedEpisodesScan", msg)
                requests.post(f"{base}/command?apikey={key}", json={"name": "DownloadedEpisodesScan"}, timeout=10)
                actions.append(f"triggered Sonarr DownloadedEpisodesScan ({len(stuck)} items)")
        except Exception as e:
            log.warning("download_pipeline_probe: Sonarr check error: %s", e)

    # ---- Radarr import gap check + auto-fix ----
    radarr_row = by_type.get("radarr")
    if radarr_row:
        _, _, radarr_name, host, port, use_ssl, enc, _ = radarr_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"
        try:
            r = requests.get(
                f"{base}/queue",
                params={"apikey": key, "pageSize": 200},
                timeout=10,
            )
            records = r.json().get("records", [])
            stuck = [
                rec for rec in records
                if rec.get("status") in ("completed", "downloading") and rec.get("timeleft") == "00:00:00"
            ]
            if stuck:
                msg = f"Radarr: {len(stuck)} movie(s) downloaded but not imported"
                issues.append(msg)
                log.warning("download_pipeline_probe: %s — triggering DownloadedMoviesScan", msg)
                requests.post(f"{base}/command?apikey={key}", json={"name": "DownloadedMoviesScan"}, timeout=10)
                actions.append(f"triggered Radarr DownloadedMoviesScan ({len(stuck)} items)")
        except Exception as e:
            log.warning("download_pipeline_probe: Radarr check error: %s", e)

    if not issues:
        log.info("download_pipeline_probe: pipeline healthy")
        return

    _log_selfheal("download_pipeline", "media_pipeline_heal", actions)

    # Notify A.R.C.H.I.E. — auto-fixes get 'normal' priority (informational),
    # stalls that need human eyes get 'high' so A.R.C.H.I.E. escalates via Telegram.
    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
    if api_key_env:
        action_str = (" Auto-fixed: " + "; ".join(actions) + ".") if actions else ""
        human_str = " Manual intervention required — check SABnzbd web UI." if needs_human else ""
        priority = "high" if needs_human else "normal"
        try:
            requests.post(
                f"{hub_url}/api/notifications",
                json={
                    "type": "warning",
                    "title": "M.A.V.E.N. — Download pipeline issue",
                    "message": "; ".join(issues) + action_str + human_str,
                    "source": "media_hub_maven_pipeline",
                    "priority": priority,
                },
                headers={"Authorization": f"Bearer {api_key_env}"},
                timeout=5,
            )
        except Exception:
            pass  # hub unreachable — stdout log above is the fallback


# --- download client health probe (every 30 min) ---------------------------

def download_client_health_probe() -> None:
    """Test Sonarr/Radarr → SABnzbd connection. If broken, auto-sync API key.

    Root cause of 2026-04-26 import failure: Sonarr's SABnzbd API key was
    stale so every DownloadedEpisodesScan silently failed. This probe catches
    it within 30 min and self-heals by reading the authoritative key from
    media_hub_services and PUTting it back into Sonarr/Radarr.
    """
    import os

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}
    issues: list[str] = []
    actions: list[str] = []

    for arr_type in ("sonarr", "radarr"):
        arr_row = by_type.get(arr_type)
        if not arr_row:
            continue
        _, _, arr_name, host, port, use_ssl, enc, _ = arr_row
        arr_key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"

        try:
            clients = requests.get(
                f"{base}/downloadclient", headers={"X-Api-Key": arr_key}, timeout=8
            ).json()

            for client in clients:
                if not client.get("enable"):
                    continue
                test = requests.post(
                    f"{base}/downloadclient/test",
                    json=client,
                    headers={"X-Api-Key": arr_key},
                    timeout=10,
                )
                if test.status_code == 200:
                    continue

                log.warning(
                    "download_client_health_probe: %s client '%s' test failed (HTTP %s)",
                    arr_name, client.get("name"), test.status_code,
                )

                # Auto-fix for SABnzbd: re-sync API key from media_hub_services
                if client.get("implementation", "").lower() == "sabnzbd":
                    sab_row = by_type.get("sabnzbd")
                    if sab_row:
                        real_key = _decrypt(sab_row[6])
                        for field in client.get("fields", []):
                            if field.get("name") == "apiKey":
                                field["value"] = real_key
                                break
                        requests.put(
                            f"{base}/downloadclient/{client['id']}",
                            json=client,
                            headers={"X-Api-Key": arr_key},
                            timeout=10,
                        )
                        retest = requests.post(
                            f"{base}/downloadclient/test",
                            json=client,
                            headers={"X-Api-Key": arr_key},
                            timeout=10,
                        )
                        if retest.status_code == 200:
                            actions.append(f"{arr_name}: SABnzbd API key was stale — auto-synced")
                            log.warning("download_client_health_probe: %s SABnzbd key resynced", arr_name)
                        else:
                            issues.append(f"{arr_name}: SABnzbd still broken after key sync")
                    else:
                        issues.append(f"{arr_name}: SABnzbd client broken, no service row to sync from")
                else:
                    issues.append(f"{arr_name}: download client '{client.get('name')}' broken")

        except Exception as e:
            log.warning("download_client_health_probe: %s error: %s", arr_type, e)

    if not issues and not actions:
        log.info("download_client_health_probe: all download clients healthy")
        return

    _log_selfheal("download_client_health", "media_client_heal", actions)

    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
    if api_key_env:
        try:
            requests.post(
                f"{hub_url}/api/notifications",
                json={
                    "type": "warning" if issues else "info",
                    "title": "M.A.V.E.N. — Download client health",
                    "message": "; ".join(actions + issues),
                    "source": "media_hub_maven_dlclient",
                    "priority": "high" if issues else "normal",
                },
                headers={"Authorization": f"Bearer {api_key_env}"},
                timeout=5,
            )
        except Exception:
            pass


# --- stale queue probe (every 30 minutes) ----------------------------------

def stale_queue_probe() -> None:
    """Remove Sonarr queue items stuck as completed/warning with no eligible files.

    Root cause: manual file moves (or import failures) leave download folders
    empty while Sonarr still tracks them as 'completed/warning'. Sonarr re-adds
    them from SABnzbd history on every RefreshMonitoredDownloads cycle, creating
    a permanent warning loop. This probe detects and clears both sides.
    """
    import os

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}
    sonarr_row = by_type.get("sonarr")
    if not sonarr_row:
        return

    _, _, _, host, port, use_ssl, enc, _ = sonarr_row
    sonarr_key = _decrypt(enc)
    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}/api/v3"

    VIDEO_EXT = {".mkv", ".mp4", ".avi", ".m4v"}

    try:
        queue = requests.get(
            f"{base}/queue", params={"pageSize": 200}, headers={"X-Api-Key": sonarr_key}, timeout=10
        ).json()

        stale_ids: list[int] = []
        stale_download_ids: list[str] = []
        for item in queue.get("records", []):
            if item.get("status") != "completed" or item.get("trackedDownloadStatus") != "warning":
                continue
            # Check if the download folder is empty of video files
            for msg in item.get("statusMessages", []):
                for text in msg.get("messages", []):
                    if "No files found are eligible for import" in text:
                        # Extract folder path and check disk
                        import re as _re
                        m = _re.search(r"import in (.+?)$", text)
                        if m:
                            folder = m.group(1).strip().rstrip("/")
                            # SAFETY (audit 2026-07-08): this container has NO download-folder
                            # mount, so it cannot verify emptiness. Only act when the folder is
                            # actually readable HERE; if we can't see it, SKIP — never delete on
                            # an unverifiable check (old code failed OPEN → blind deletion).
                            if not os.path.isdir(folder):
                                continue
                            has_video = False
                            try:
                                for root, _, files in os.walk(folder):
                                    if any(
                                        os.path.splitext(f)[1].lower() in VIDEO_EXT
                                        for f in files
                                    ):
                                        has_video = True
                                        break
                            except OSError:
                                continue  # cannot read folder → do NOT delete
                            if not has_video:
                                stale_ids.append(item["id"])
                                if item.get("downloadId"):
                                    stale_download_ids.append(item["downloadId"])

        if not stale_ids:
            log.info("stale_queue_probe: queue clean")
            return

        # Bulk-remove stale items from Sonarr queue (keep files, no blocklist)
        requests.delete(
            f"{base}/queue/bulk",
            json={"ids": stale_ids, "removeFromClient": False, "blocklist": False},
            headers={"X-Api-Key": sonarr_key},
            timeout=15,
        )
        log.warning("stale_queue_probe: removed %d stale completed/warning item(s)", len(stale_ids))

        # Purge ONLY the matching SABnzbd history entries so Sonarr doesn't re-add them.
        # SAFETY (audit 2026-07-08): scoped to the specific stale nzo_ids — NEVER value="all"
        # (old code purged the ENTIRE history, nuking unrelated/in-flight downloads).
        sab_row = by_type.get("sabnzbd")
        if sab_row and stale_download_ids:
            _, _, _, sab_host, sab_port, sab_ssl, sab_enc, _ = sab_row
            sab_key = _decrypt(sab_enc)
            sab_scheme = "https" if sab_ssl else "http"
            sab_base = f"{sab_scheme}://{sab_host}:{sab_port}"
            purged = 0
            for nzo in stale_download_ids:
                try:
                    resp = requests.get(
                        f"{sab_base}/api",
                        params={"mode": "history", "name": "delete", "value": nzo,
                                "del_files": "0", "output": "json", "apikey": sab_key},
                        timeout=10,
                    )
                    if resp.json().get("status"):
                        purged += 1
                except Exception as e:
                    log.warning("stale_queue_probe: SAB history delete %s failed: %s", nzo, e)
            if purged:
                log.warning("stale_queue_probe: purged %d matching SABnzbd history item(s)", purged)

        _log_selfheal("stale_queue", "media_queue_purge",
                      [f"removed {len(stale_ids)} stale completed/warning queue item(s)"])

        # Notify hub
        hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
        api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
        if api_key_env:
            try:
                requests.post(
                    f"{hub_url}/api/notifications",
                    json={
                        "type": "info",
                        "title": "M.A.V.E.N. — Stale queue cleared",
                        "message": f"{len(stale_ids)} completed/warning item(s) had empty download folders — removed from queue and SABnzbd history",
                        "source": "media_hub_maven_stale_queue",
                        "priority": "normal",
                    },
                    headers={"Authorization": f"Bearer {api_key_env}"},
                    timeout=5,
                )
            except Exception:
                pass

    except Exception as e:
        log.warning("stale_queue_probe: error: %s", e)


# --- library coverage probe (every 2 hours) --------------------------------

def library_coverage_probe() -> None:
    """Detect monitored shows/movies with 0% coverage and trigger import.

    Catches the failure mode where files were downloaded but the import
    pipeline never ran: Sonarr shows 0/N episodes for a monitored series.
    Triggers DownloadedEpisodesScan and notifies A.R.C.H.I.E. so Kytran
    is aware even when the auto-fix fires.
    """
    import os

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}
    issues: list[str] = []
    actions: list[str] = []

    # ---- Sonarr: monitored series with 0 imported episodes ----
    sonarr_row = by_type.get("sonarr")
    if sonarr_row:
        _, _, name, host, port, use_ssl, enc, _ = sonarr_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"
        try:
            series_list = requests.get(
                f"{base}/series", headers={"X-Api-Key": key}, timeout=10
            ).json()
            zero = [
                s for s in series_list
                if s.get("monitored")
                and s.get("statistics", {}).get("episodeCount", 0) > 0
                and s.get("statistics", {}).get("episodeFileCount", 0) == 0
            ]
            if zero:
                titles = ", ".join(s["title"] for s in zero[:4])
                extra = f" (+{len(zero)-4} more)" if len(zero) > 4 else ""
                issues.append(f"Sonarr: {len(zero)} monitored show(s) have 0 imported episodes: {titles}{extra}")
                log.warning("library_coverage_probe: %s", issues[-1])
                # Trigger scan on the download complete folder
                requests.post(
                    f"{base}/command",
                    json={"name": "DownloadedEpisodesScan", "path": "/downloads/complete/tv"},
                    headers={"X-Api-Key": key},
                    timeout=10,
                )
                actions.append(f"triggered Sonarr DownloadedEpisodesScan ({len(zero)} show(s))")
            else:
                log.info("library_coverage_probe: Sonarr coverage healthy")
        except Exception as e:
            log.warning("library_coverage_probe: Sonarr error: %s", e)

        # ---- Aired-but-missing episodes -> auto-search (task #4724) ----
        # The 0%-coverage check above only catches series with NO files. It
        # misses the Rick & Morty S9 case: a series with SOME files where
        # specific AIRED episodes were never grabbed (SABnzbd paused / bad
        # releases). Search for recently-aired missing episodes only (last 30d,
        # so we don't hammer indexers for ancient unavailable specials in the
        # backlog), skipping any already in the download queue.
        try:
            from datetime import datetime as _dtm, timedelta as _tdl, timezone as _tzu

            cutoff = (_dtm.now(_tzu.utc) - _tdl(days=30)).date().isoformat()
            wanted = requests.get(
                f"{base}/wanted/missing",
                params={"pageSize": 100, "monitored": "true"},
                headers={"X-Api-Key": key},
                timeout=10,
            ).json()
            recent = [r for r in wanted.get("records", []) if (r.get("airDate") or "") >= cutoff]
            if recent:
                q = requests.get(
                    f"{base}/queue", params={"pageSize": 200}, headers={"X-Api-Key": key}, timeout=10
                ).json()
                in_queue = {r.get("episodeId") for r in q.get("records", [])}
                ep_ids = [r["id"] for r in recent if r["id"] not in in_queue][:40]
                if ep_ids:
                    requests.post(
                        f"{base}/command",
                        json={"name": "EpisodeSearch", "episodeIds": ep_ids},
                        headers={"X-Api-Key": key},
                        timeout=10,
                    )
                    issues.append(
                        f"Sonarr: {len(ep_ids)} recently-aired episode(s) missing files — searching"
                    )
                    actions.append(
                        f"triggered Sonarr EpisodeSearch for {len(ep_ids)} aired-missing episode(s)"
                    )
                    log.warning("library_coverage_probe: %s", issues[-1])
        except Exception as e:
            log.warning("library_coverage_probe: aired-missing search error: %s", e)

    # ---- Radarr: monitored movies without files ----
    radarr_row = by_type.get("radarr")
    if radarr_row:
        _, _, name, host, port, use_ssl, enc, _ = radarr_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"
        try:
            movies = requests.get(
                f"{base}/movie", headers={"X-Api-Key": key}, timeout=10
            ).json()
            # Only flag movies that are available but have no file (genuine gap)
            missing = [
                m for m in movies
                if m.get("monitored") and not m.get("hasFile") and m.get("isAvailable")
            ]
            if missing:
                log.info("library_coverage_probe: Radarr %d monitored movie(s) missing files", len(missing))
                requests.post(
                    f"{base}/command",
                    json={"name": "DownloadedMoviesScan"},
                    headers={"X-Api-Key": key},
                    timeout=10,
                )
                actions.append(f"triggered Radarr DownloadedMoviesScan ({len(missing)} missing)")
        except Exception as e:
            log.warning("library_coverage_probe: Radarr error: %s", e)

    if not issues:
        return

    _log_selfheal("library_coverage", "media_coverage_search", actions)

    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
    if api_key_env:
        action_str = (" Auto-triggered: " + "; ".join(actions) + ".") if actions else " No auto-fix available."
        try:
            requests.post(
                f"{hub_url}/api/notifications",
                json={
                    "type": "warning",
                    "title": "M.A.V.E.N. — Library coverage gap",
                    "message": "; ".join(issues) + action_str,
                    "source": "media_hub_maven_coverage",
                    "priority": "high",
                },
                headers={"Authorization": f"Bearer {api_key_env}"},
                timeout=5,
            )
        except Exception:
            pass


# --- arr database probe (every 30 min) -------------------------------------

def arr_database_probe() -> None:
    """Detect Sonarr/Radarr DB errors and auto-restart the container.

    Polls /api/v3/health. On a database/vacuum error: restarts the container
    via Docker CLI (if available), waits up to 30s for recovery, then notifies
    A.R.C.H.I.E. Kytran only hears about it if the auto-restart fails.
    """
    import os, shutil, subprocess as sp, time

    CONTAINERS = {"sonarr": "media_sonarr", "radarr": "media_radarr"}
    rows = _services_rows()
    by_type = {r[1]: r for r in rows}
    issues: list[str] = []
    actions: list[str] = []

    for arr_type in ("sonarr", "radarr"):
        arr_row = by_type.get(arr_type)
        if not arr_row:
            continue
        _, _, arr_name, host, port, use_ssl, enc, _ = arr_row
        key = _decrypt(enc)
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}/api/v3"

        try:
            health = requests.get(
                f"{base}/health", headers={"X-Api-Key": key}, timeout=8
            ).json()
        except Exception as e:
            log.warning("arr_database_probe: %s unreachable: %s", arr_name, e)
            continue

        db_errors = [
            h for h in health
            if h.get("type") in ("error", "warning")
            and any(kw in h.get("message", "").lower() for kw in ("database", "vacuum", "sqlite"))
        ]
        if not db_errors:
            log.info("arr_database_probe: %s healthy", arr_name)
            continue

        for h in db_errors:
            log.warning("arr_database_probe: %s DB issue: %s", arr_name, h.get("message"))

        container = CONTAINERS.get(arr_type)
        if container and shutil.which("docker"):
            log.warning("arr_database_probe: restarting %s to recover DB", container)
            result = sp.run(["docker", "restart", container], capture_output=True, timeout=30)
            if result.returncode == 0:
                recovered = False
                for _ in range(6):
                    time.sleep(5)
                    try:
                        requests.get(f"{base}/health", headers={"X-Api-Key": key}, timeout=5)
                        recovered = True
                        break
                    except Exception:
                        pass
                if recovered:
                    actions.append(f"restarted {arr_name} for DB error — service recovered")
                else:
                    issues.append(f"{arr_name}: restarted but did not recover in 30s")
            else:
                issues.append(f"{arr_name}: DB error, docker restart failed")
        else:
            issues.append(f"{arr_name}: DB error — manual restart required (Docker CLI unavailable)")

    all_msgs = issues + actions
    if not all_msgs:
        return

    _log_selfheal("arr_database", "media_db_recover", actions)

    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")
    if api_key_env:
        try:
            requests.post(
                f"{hub_url}/api/notifications",
                json={
                    "type": "warning",
                    "title": "M.A.V.E.N. — Arr database issue",
                    "message": "; ".join(all_msgs),
                    "source": "media_hub_maven_arrdb",
                    "priority": "high" if issues else "normal",
                },
                headers={"Authorization": f"Bearer {api_key_env}"},
                timeout=5,
            )
        except Exception:
            pass


# --- grab notify probe (every 5 min) ----------------------------------------

def grab_notify_probe() -> None:
    """Detect Overseerr requests that transitioned to processing (3) or
    available (5) in the last 10 minutes and fire a Telegram notification
    via the A.R.C.H.I.E. hub notification API. In-memory dedup prevents
    duplicate alerts within a container lifecycle."""
    import os
    from datetime import timezone

    global _seen_grab_ids

    rows = _services_rows()
    by_type = {r[1]: r for r in rows}

    overseerr_row = by_type.get("overseerr") or by_type.get("jellyseerr")
    if not overseerr_row:
        return

    _, stype, _, host, port, use_ssl, enc, _ = overseerr_row
    key = _decrypt(enc)
    if not key:
        return

    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"

    try:
        r = requests.get(
            f"{base}/api/v1/request",
            params={"sort": "modified", "take": 20},
            headers={"X-Api-Key": key},
            timeout=8,
        )
        if r.status_code != 200:
            log.warning("grab_notify_probe: overseerr HTTP %s", r.status_code)
            return
        results = r.json().get("results", [])
    except Exception as e:
        log.warning("grab_notify_probe: request failed: %s", e)
        return

    cutoff = datetime.now(tz=timezone.utc).timestamp() - 600  # 10 min
    STATUS_LABEL = {3: "downloading now 📥", 5: "available ✅"}

    hub_url = os.getenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000")
    api_key_env = os.getenv("ARCHIE_INTERNAL_API_KEY", "")

    for req in results:
        req_id = req.get("id")
        status = req.get("status")
        if req_id is None or status not in STATUS_LABEL:
            continue
        if req_id in _seen_grab_ids:
            continue

        updated_raw = req.get("updatedAt", "")
        try:
            if isinstance(updated_raw, (int, float)):
                updated_ts = float(updated_raw)
            else:
                from datetime import datetime as _dt
                updated_ts = _dt.fromisoformat(
                    str(updated_raw).replace("Z", "+00:00")
                ).timestamp()
        except Exception:
            continue

        if updated_ts < cutoff:
            continue

        _seen_grab_ids.add(req_id)
        media = req.get("media", {})
        title = media.get("title") or media.get("originalTitle") or f"request #{req_id}"
        media_type = "movie" if media.get("mediaType") == "movie" else "TV"
        label = STATUS_LABEL[status]
        message = f"M.A.V.E.N. grabbed {title} ({media_type}) — {label}"
        log.info("grab_notify_probe: %s", message)

        if api_key_env:
            try:
                requests.post(
                    f"{hub_url}/api/notifications",
                    json={
                        "type": "info",
                        "title": "M.A.V.E.N. — Media grabbed",
                        "message": message,
                        "source": "media_hub_maven_grab",
                        "priority": "normal",
                    },
                    headers={"Authorization": f"Bearer {api_key_env}"},
                    timeout=5,
                )
            except Exception:
                pass


# --- M.A.V.E.N. approved-removal executor ----------------------------------

def _maven_removal_executor() -> None:
    """Execute A.R.C.H.I.E.-approved M.A.V.E.N. removals; drop denied ones.
    project #385 task #4745. Wrapped so a failure never kills the scheduler."""
    try:
        from maven_manager import process_approved_removals

        process_approved_removals()
    except Exception as exc:  # noqa: BLE001
        log.error("maven_removal_executor failed: %s", exc)


def _maven_optimize_executor() -> None:
    """Queue A.R.C.H.I.E.-approved Tdarr transcodes; drop denied. project #385 Phase 3."""
    try:
        from maven_manager import process_approved_optimizes

        process_approved_optimizes()
    except Exception as exc:  # noqa: BLE001
        log.error("maven_optimize_executor failed: %s", exc)


def _tdarr_library_review() -> None:
    """Periodic Tdarr rescan + library review — M.A.V.E.N. refreshes her own view
    of the library (#4754) then reports space-optimize candidates on the fresh
    data. Phase 3."""
    try:
        from maven_manager import library_scan, video_review

        library_scan()  # #4754 — pick up newly-downloaded/removed files first
        video_review()
    except Exception as exc:  # noqa: BLE001
        log.error("tdarr_library_review failed: %s", exc)


# --- scheduler wiring ------------------------------------------------------

_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler() -> BackgroundScheduler:
    """Idempotent — safe to call on every app boot; subsequent calls return
    the already-running scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True, timezone=timezone.utc)
    _scheduler.add_job(
        service_health_probe,
        "interval",
        minutes=30,
        id="service_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # fire once at startup
    )
    _scheduler.add_job(
        indexer_health_probe,
        "interval",
        minutes=30,
        id="indexer_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # Execute A.R.C.H.I.E.-approved M.A.V.E.N. removals (project #385 task #4745).
    # No startup fire — a pending approval can wait the first 5 min.
    _scheduler.add_job(
        _maven_removal_executor,
        "interval",
        minutes=5,
        id="maven_removal_executor",
        max_instances=1,
        coalesce=True,
    )
    # Tdarr video optimize (project #385 Phase 3): drain approved transcodes + periodic review.
    _scheduler.add_job(
        _maven_optimize_executor,
        "interval",
        minutes=5,
        id="maven_optimize_executor",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _tdarr_library_review,
        "interval",
        hours=6,
        id="tdarr_library_review",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        maven_diagnostic_probe,
        "interval",
        minutes=30,
        id="maven_diagnostic",
        max_instances=1,
        coalesce=True,
        # Offset 5 min from startup so service health runs first
        next_run_time=datetime.now(timezone.utc).replace(second=0, microsecond=0),
    )
    _scheduler.add_job(
        quality_probe,
        "interval",
        hours=12,
        id="quality_probe",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        download_pipeline_probe,
        "interval",
        minutes=30,
        id="download_pipeline",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        download_client_health_probe,
        "interval",
        minutes=30,
        id="download_client_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        library_coverage_probe,
        "interval",
        hours=2,
        id="library_coverage",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        arr_database_probe,
        "interval",
        minutes=30,
        id="arr_database",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        stale_queue_probe,
        "interval",
        minutes=30,
        id="stale_queue",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        grab_notify_probe,
        "interval",
        minutes=5,
        id="grab_notify",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.start()
    log.info(
        "media hub observer scheduler started ("
        "every 5m: grab_notify; "
        "every 30m: service_health, indexer_health, maven_diagnostic, download_pipeline, "
        "download_client_health, arr_database, stale_queue; "
        "every 2h: library_coverage; every 12h: quality_probe)"
    )
    return _scheduler
