"""Media Hub scheduled health jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from health_observer_common import *  # noqa: F401,F403

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
                ok, detail = _arr_command(
                    base,
                    {"name": "DownloadedEpisodesScan", "path": "/downloads/complete/tv"},
                    headers={"X-Api-Key": key},
                )
                if ok:
                    actions.append(f"triggered Sonarr DownloadedEpisodesScan ({len(zero)} show(s)) — {detail}")
                else:
                    issues.append(f"Sonarr DownloadedEpisodesScan FAILED — {detail}")
                    log.error("library_coverage_probe: Sonarr scan failed — %s", detail)
            else:
                # #5386(a). This said "Sonarr coverage healthy" and was logged 97x
                # in 7 days while 121 episodes were missing. It never measured
                # coverage — the check above only finds series with **zero**
                # imported episodes, so a series with SOME files and specific
                # gaps is invisible to it by construction. Say what was actually
                # measured; a status must not describe more than it looked at.
                log.info(
                    "library_coverage_probe: Sonarr — no series with 0 imported episodes "
                    "(this does NOT mean coverage is complete; per-episode gaps are "
                    "counted by the aired-missing check below)"
                )
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
            records = wanted.get("records", [])
            recent = [r for r in records if (r.get("airDate") or "") >= cutoff]

            # #5386(a) — REPORT the whole gap, ACT on only part of it.
            # `totalRecords` is the true count; `records` is capped by pageSize
            # (100), so counting the page silently under-reports a large backlog
            # — the same cap that hid Sonarr blocklist entries. Anything aired
            # before the cutoff was previously invisible FOREVER: not searched
            # (deliberate) and not reported (a bug).
            #
            # ⚠️ The auto-search window stays at 30 days ON PURPOSE. Widening it
            # would auto-grab the aged backlog (~101 Impractical Jokers episodes,
            # ~120 GB) straight onto /dev/sdb, which has 1,736 uncorrectable
            # sectors and is pending replacement (#5385) — and the owner
            # explicitly put that backlog on hold. Do NOT "fix" this by raising
            # the window; visibility and action are separate decisions.
            total_missing = wanted.get("totalRecords")
            if total_missing is None:
                total_missing = len(records)
            aged = total_missing - len(recent)
            if aged > 0:
                issues.append(
                    f"Sonarr: {aged} monitored episode(s) aired >30d ago are still missing "
                    f"({total_missing} missing in total) — reported only, NOT auto-searched "
                    f"(pending disk replacement #5385)"
                )
                log.warning("library_coverage_probe: %s", issues[-1])

            if recent:
                q = requests.get(
                    f"{base}/queue", params={"pageSize": 200}, headers={"X-Api-Key": key}, timeout=10
                ).json()
                in_queue = {r.get("episodeId") for r in q.get("records", [])}
                ep_ids = [r["id"] for r in recent if r["id"] not in in_queue][:40]
                if ep_ids:
                    ok, detail = _arr_command(
                        base,
                        {"name": "EpisodeSearch", "episodeIds": ep_ids},
                        headers={"X-Api-Key": key},
                    )
                    issues.append(
                        f"Sonarr: {len(ep_ids)} recently-aired episode(s) missing files — searching"
                    )
                    if ok:
                        actions.append(
                            f"triggered Sonarr EpisodeSearch for {len(ep_ids)} aired-missing "
                            f"episode(s) — {detail}"
                        )
                    else:
                        issues.append(f"Sonarr EpisodeSearch FAILED — {detail}")
                        log.error("library_coverage_probe: EpisodeSearch failed — %s", detail)
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
                # #5386(a): this branch appended an ACTION but never an ISSUE, and
                # `if not issues: return` below then skipped _log_selfheal AND the
                # A.R.C.H.I.E. notify — so the scan it fired was invisible on both
                # surfaces. Work that is done unrecorded is indistinguishable from
                # work that was never done.
                issues.append(
                    f"Radarr: {len(missing)} monitored, available movie(s) have no file"
                )
                log.warning("library_coverage_probe: %s", issues[-1])
                ok, detail = _arr_command(
                    base, {"name": "DownloadedMoviesScan"}, headers={"X-Api-Key": key}
                )
                if ok:
                    actions.append(f"triggered Radarr DownloadedMoviesScan ({len(missing)} missing) — {detail}")
                else:
                    issues.append(f"Radarr DownloadedMoviesScan FAILED — {detail}")
                    log.error("library_coverage_probe: Radarr scan failed — %s", detail)
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
