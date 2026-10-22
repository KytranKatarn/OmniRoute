"""Media Hub scheduled health jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from health_observer_common import *  # noqa: F401,F403

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
                ok, detail = _arr_command(
                    base, {"name": "DownloadedEpisodesScan"}, params={"apikey": key}
                )
                if ok:
                    actions.append(f"triggered Sonarr DownloadedEpisodesScan ({len(stuck)} items) — {detail}")
                else:
                    # #5383: this used to append a success line regardless.
                    issues.append(f"Sonarr DownloadedEpisodesScan FAILED — {detail}")
                    log.error("download_pipeline_probe: Sonarr scan failed — %s", detail)
                    needs_human = True
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
                ok, detail = _arr_command(
                    base, {"name": "DownloadedMoviesScan"}, params={"apikey": key}
                )
                if ok:
                    actions.append(f"triggered Radarr DownloadedMoviesScan ({len(stuck)} items) — {detail}")
                else:
                    # #5383: this is the call that failed instantly every 30 min
                    # for 20 days while the probe logged that it had healed.
                    issues.append(f"Radarr DownloadedMoviesScan FAILED — {detail}")
                    log.error("download_pipeline_probe: Radarr scan failed — %s", detail)
                    needs_human = True
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
