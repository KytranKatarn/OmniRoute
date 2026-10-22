"""
M.A.V.E.N. troubleshoot skill — task #2239.

Codifies the 2026-04-21 diagnostic that traced "nothing downloads in Sonarr"
to a Tailscale-MagicDNS trap inside Docker's embedded resolver. Packages the
same probe chain as a single HTTP call so future failures surface structured
findings with suggested fixes, instead of requiring manual shell archaeology.

Checks (in order — cheap → expensive):
    1. External DNS resolution from inside the container
    2. Each media_hub_services row: client.probe() + last_health_check age
    3. Sonarr /api/v3/health — indexer + import warnings
    4. Radarr /api/v3/health — same
    5. Prowlarr /api/v1/indexerstatus — currently-failing indexers
    6. SABnzbd queue status (paused? disk space?)
    7. SABnzbd warnings feed
    8. Radarr + Sonarr queue — importBlocked items (downloaded but not moved
       into library; common cause: hardlinks across different filesystems)

Exposed as:
    GET  /maven/api/troubleshoot  (JSON, admin-only)
    GET  /maven/troubleshoot       (rendered HTML, admin-only)
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

import requests
from flask import jsonify, render_template
from flask_login import current_user, login_required

from database import get_db_cursor
from . import maven_bp

log = logging.getLogger("media_hub.maven.troubleshoot")

# Hostnames we probe. api.nzbgeek.info is the canonical "Tailscale MagicDNS
# trap" signal — if it SERVFAILs inside the container we know the DNS chain
# is broken even if every LAN service is reachable.
_DNS_PROBE_TARGETS = ["api.nzbgeek.info", "1.1.1.1"]
_STALENESS_WARN_MIN = 60   # warn if a service hasn't been re-probed in 1h
_STALENESS_CRIT_MIN = 360  # critical if stale > 6h (matches arr sticky flag)


from .troubleshoot_checks import CheckResult, _rows_for_type, _decrypt_key, run_diagnostic



# --- routes ----------------------------------------------------------------

def _require_admin():
    from flask import abort
    if not getattr(current_user, "is_admin", False):
        abort(403)


@maven_bp.route("/api/status")
@login_required
def api_maven_status():
    """Return the last cached M.A.V.E.N. diagnostic summary (no re-run).
    Used by the nav badge to show a red dot when errors exist."""
    from health_observer import _last_diagnostic
    return jsonify({"success": True, "diagnostic": _last_diagnostic})


@maven_bp.route("/api/troubleshoot")
@login_required
def api_troubleshoot():
    _require_admin()
    return jsonify(run_diagnostic())


@maven_bp.route("/api/overseerr-sync", methods=["POST"])
@login_required
def api_overseerr_sync():
    """Trigger Overseerr availability-sync + radarr-scan so media that was
    manually imported gets marked available without waiting for the nightly run."""
    _require_admin()
    results = []
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("overseerr", "jellyseerr"):
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        for job in ("availability-sync", "radarr-scan"):
            try:
                r = requests.post(
                    f"{base}/api/v1/settings/jobs/{job}/run",
                    headers={"X-Api-Key": key},
                    timeout=8,
                )
                results.append({"service": name, "job": job, "ok": r.status_code == 200})
            except Exception as e:
                results.append({"service": name, "job": job, "ok": False, "error": str(e)})
    return jsonify({"success": True, "results": results})


@maven_bp.route("/api/retry-scan", methods=["POST"])
@login_required
def api_retry_scan():
    """Trigger DownloadedMoviesScan + DownloadedEpisodesScan on Radarr/Sonarr."""
    _require_admin()
    results = []
    for service_type, scan_cmd in [
        ("radarr", "DownloadedMoviesScan"),
        ("sonarr", "DownloadedEpisodesScan"),
    ]:
        for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type(service_type):
            key = _decrypt_key(enc)
            if not key:
                continue
            scheme = "https" if use_ssl else "http"
            try:
                r = requests.post(
                    f"{scheme}://{host}:{port}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": scan_cmd},
                    timeout=5,
                )
                results.append({"service": name, "ok": r.status_code in (200, 201)})
            except Exception as e:
                results.append({"service": name, "ok": False, "error": str(e)})

    # Also trigger Plex library scan so newly imported files appear immediately
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("plex"):
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            r = requests.get(
                f"{scheme}://{host}:{port}/library/sections/all/refresh",
                params={"X-Plex-Token": key},
                timeout=8,
                verify=False,
            )
            results.append({"service": name, "ok": r.status_code in (200, 201)})
        except Exception as e:
            results.append({"service": name, "ok": False, "error": str(e)})

    return jsonify({"success": True, "results": results})


@maven_bp.route("/api/fix-stuck-requests", methods=["POST"])
@login_required
def api_fix_stuck_requests():
    """Unstick approved-but-not-downloading requests.

    Strategy (in order):
    1. Pull approved requests from Overseerr, look each one up in Radarr/Sonarr
       by TMDB ID, and trigger a targeted search for items that are already
       monitored but have no queue entry.
    2. Run DownloadedMoviesScan + DownloadedEpisodesScan to import anything
       already downloaded but stuck in importBlocked.
    3. Run Overseerr availability-sync + radarr-scan to re-push any approved
       requests that never reached the arr services.
    4. Trigger a Plex library refresh so newly imported files appear immediately.
    """
    _require_admin()
    results = []

    # Step 1 — targeted arr searches for approved requests
    overseerr_rows = _rows_for_type("overseerr", "jellyseerr")
    approved_movies: list = []   # tmdb IDs
    approved_tv: list = []       # tmdb IDs

    for _, stype, name, host, port, use_ssl, enc, *_ in overseerr_rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            r = requests.get(
                f"{scheme}://{host}:{port}/api/v1/request",
                headers={"X-Api-Key": key},
                params={"take": 100, "skip": 0, "filter": "approved"},
                timeout=10,
            )
            if r.status_code != 200:
                results.append({"step": "overseerr_fetch", "ok": False,
                                 "error": f"HTTP {r.status_code}"})
                continue
            for req in r.json().get("results", []):
                media = req.get("media") or {}
                media_status = media.get("status", 0)
                if media_status in (3, 4, 5):
                    continue   # already progressing
                tmdb_id = media.get("tmdbId")
                if not tmdb_id:
                    continue
                if req.get("type") == "movie":
                    approved_movies.append(tmdb_id)
                else:
                    approved_tv.append(tmdb_id)
        except Exception as e:
            results.append({"step": "overseerr_fetch", "ok": False, "error": str(e)})

    # Trigger targeted Radarr search for each approved movie
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("radarr"):
        key = _decrypt_key(enc)
        if not key or not approved_movies:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            all_movies_r = requests.get(
                f"{base}/api/v3/movie",
                headers={"X-Api-Key": key},
                timeout=10,
            )
            if all_movies_r.status_code != 200:
                continue
            radarr_id_map = {m["tmdbId"]: m["id"] for m in all_movies_r.json()
                             if m.get("tmdbId") and m.get("id")}
            ids_to_search = [radarr_id_map[t] for t in approved_movies
                             if t in radarr_id_map]
            if ids_to_search:
                sr = requests.post(
                    f"{base}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": "MoviesSearch", "movieIds": ids_to_search},
                    timeout=8,
                )
                results.append({
                    "step": "radarr_search", "service": name,
                    "count": len(ids_to_search),
                    "ok": sr.status_code in (200, 201),
                })
        except Exception as e:
            results.append({"step": "radarr_search", "service": name,
                            "ok": False, "error": str(e)})

    # Trigger targeted Sonarr search for each approved TV request
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("sonarr"):
        key = _decrypt_key(enc)
        if not key or not approved_tv:
            continue
        scheme = "https" if use_ssl else "http"
        base = f"{scheme}://{host}:{port}"
        try:
            all_series_r = requests.get(
                f"{base}/api/v3/series",
                headers={"X-Api-Key": key},
                timeout=10,
            )
            if all_series_r.status_code != 200:
                continue
            sonarr_id_map = {s["tmdbId"]: s["id"] for s in all_series_r.json()
                             if s.get("tmdbId") and s.get("id")}
            for tmdb_id in approved_tv:
                sonarr_id = sonarr_id_map.get(tmdb_id)
                if not sonarr_id:
                    continue
                sr = requests.post(
                    f"{base}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": "SeriesSearch", "seriesId": sonarr_id},
                    timeout=8,
                )
                results.append({
                    "step": "sonarr_search", "service": name,
                    "tmdb_id": tmdb_id,
                    "ok": sr.status_code in (200, 201),
                })
        except Exception as e:
            results.append({"step": "sonarr_search", "service": name,
                            "ok": False, "error": str(e)})

    # Step 2 — scan for already-downloaded but not-imported files
    for service_type, scan_cmd in [
        ("radarr", "DownloadedMoviesScan"),
        ("sonarr", "DownloadedEpisodesScan"),
    ]:
        for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type(service_type):
            key = _decrypt_key(enc)
            if not key:
                continue
            scheme = "https" if use_ssl else "http"
            try:
                r = requests.post(
                    f"{scheme}://{host}:{port}/api/v3/command",
                    headers={"X-Api-Key": key},
                    json={"name": scan_cmd},
                    timeout=5,
                )
                results.append({"step": scan_cmd, "service": name,
                                 "ok": r.status_code in (200, 201)})
            except Exception as e:
                results.append({"step": scan_cmd, "service": name,
                                "ok": False, "error": str(e)})

    # Step 3 — Overseerr availability-sync + radarr-scan
    for _, stype, name, host, port, use_ssl, enc, *_ in overseerr_rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        for job in ("availability-sync", "radarr-scan"):
            try:
                r = requests.post(
                    f"{scheme}://{host}:{port}/api/v1/settings/jobs/{job}/run",
                    headers={"X-Api-Key": key},
                    timeout=8,
                )
                results.append({"step": f"overseerr_{job}", "service": name,
                                 "ok": r.status_code == 200})
            except Exception as e:
                results.append({"step": f"overseerr_{job}", "service": name,
                                "ok": False, "error": str(e)})

    # Step 4 — Plex library refresh
    for _, stype, name, host, port, use_ssl, enc, *_ in _rows_for_type("plex"):
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        try:
            r = requests.get(
                f"{scheme}://{host}:{port}/library/sections/all/refresh",
                params={"X-Plex-Token": key},
                timeout=8,
                verify=False,
            )
            results.append({"step": "plex_refresh", "service": name,
                             "ok": r.status_code in (200, 201)})
        except Exception as e:
            results.append({"step": "plex_refresh", "service": name,
                            "ok": False, "error": str(e)})

    ok_count = sum(1 for r in results if r.get("ok"))
    return jsonify({
        "success": True,
        "results": results,
        "summary": f"{ok_count}/{len(results)} actions succeeded",
        "note": (
            "Searches have been triggered. Downloads appear in SABnzbd within "
            "60–120s if Prowlarr finds results. Run /maven/api/troubleshoot "
            "again in a few minutes to verify progress."
        ),
    })


@maven_bp.route("/troubleshoot")
@login_required
def troubleshoot_page():
    _require_admin()
    report = run_diagnostic()
    return render_template("maven_troubleshoot.html", report=report)
