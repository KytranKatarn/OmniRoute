"""
M.A.V.E.N. quality skill — disk space + per-movie quality audit.

Checks:
    1. Disk space on /movies and /downloads volumes
    2. Every movie in Radarr with a file — flags oversized or
       now-blocked quality formats (BR-DISK, Remux-2160p) with
       a recommended action.

Exposed as:
    GET  /maven/api/quality-report   (JSON, admin-only)
    POST /maven/api/upgrade-oversized (JSON, admin-only)
         Body: {"movie_ids": [1,2,3]}  — omit to target all flagged movies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import List, Optional

import requests
from flask import jsonify, request
from flask_login import login_required

from . import maven_bp
from .troubleshoot import _rows_for_type, _decrypt_key, CheckResult, _require_admin

log = logging.getLogger("media_hub.maven.quality")

# Thresholds
_SIZE_WARN_GB = 20.0   # flag movies above this
_SIZE_CRIT_GB = 40.0   # critical flag
_BLOCKED_QUALITIES = {"BR-DISK", "Remux-2160p"}
_DISK_WARN_FREE_GB = 200.0
_DISK_CRIT_FREE_GB = 50.0

# Qualities considered optimal (good quality, reasonable size)
_PREFERRED_QUALITIES = {
    "WEBDL-1080p", "WEBDL-2160p",
    "Bluray-1080p", "Bluray-2160p",
    "HDTV-1080p", "HDTV-2160p",
}


@dataclass
class MovieQuality:
    radarr_id: int
    title: str
    year: Optional[int]
    size_gb: float
    quality: str
    flagged: bool
    reason: str
    recommendation: str

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Disk space check (used by run_diagnostic)
# ---------------------------------------------------------------------------

def check_disk_space() -> List[CheckResult]:
    """Check free space on /movies and /downloads volumes inside Radarr container."""
    results = []
    rows = _rows_for_type("radarr")
    if not rows:
        return results

    _, stype, name, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    if not key:
        return results

    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"
    headers = {"X-Api-Key": key}

    for volume_path, label in [("/movies", "Movies volume"), ("/downloads", "Downloads volume")]:
        try:
            r = requests.get(
                f"{base}/api/v3/diskspace",
                headers=headers,
                timeout=8,
            )
            if r.status_code != 200:
                continue
            for disk in r.json():
                if disk.get("path", "").startswith(volume_path.rstrip("/")):
                    free_gb = disk.get("freeSpace", 0) / 1024 ** 3
                    total_gb = disk.get("totalSpace", 0) / 1024 ** 3
                    used_pct = int((1 - free_gb / total_gb) * 100) if total_gb else 0

                    if free_gb < _DISK_CRIT_FREE_GB:
                        severity, fix = "error", "Urgently free space — delete or upgrade oversized movies via /maven/api/upgrade-oversized"
                    elif free_gb < _DISK_WARN_FREE_GB:
                        severity, fix = "warning", "Run /maven/api/quality-report to find oversized movies and reclaim space"
                    else:
                        severity, fix = "ok", None

                    results.append(CheckResult(
                        id=f"disk_{label.lower().replace(' ', '_')}",
                        title=f"{label} disk space",
                        severity=severity,
                        detail=f"{free_gb:.0f}GB free of {total_gb:.0f}GB ({used_pct}% used)",
                        fix=fix,
                        meta={"path": volume_path, "free_gb": round(free_gb, 1),
                              "total_gb": round(total_gb, 1)},
                    ))
        except Exception as e:
            results.append(CheckResult(
                id=f"disk_{label.lower().replace(' ', '_')}",
                title=f"{label} disk space",
                severity="warning",
                detail=f"Could not check: {e}",
            ))
    return results


# ---------------------------------------------------------------------------
# Per-movie quality audit
# ---------------------------------------------------------------------------

def _get_movie_quality_report() -> List[MovieQuality]:
    rows = _rows_for_type("radarr")
    if not rows:
        return []

    _, stype, name, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    if not key:
        return []

    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"
    headers = {"X-Api-Key": key}

    try:
        all_movies = requests.get(f"{base}/api/v3/movie", headers=headers, timeout=10).json()
    except Exception as e:
        log.error("Radarr movie list failed: %s", e)
        return []

    report: List[MovieQuality] = []
    for m in all_movies:
        if not m.get("hasFile"):
            continue

        size_gb = m.get("sizeOnDisk", 0) / 1024 ** 3
        mf = m.get("movieFile") or {}
        quality = (mf.get("quality") or {}).get("quality", {}).get("name", "Unknown")
        title = m.get("title", "?")
        year = m.get("year")

        flagged = False
        reason = ""
        recommendation = ""

        if quality in _BLOCKED_QUALITIES:
            flagged = True
            reason = f"{quality} is a raw disc image — huge file, no quality benefit over a proper encode"
            recommendation = "Delete and re-download as WEBDL-1080p or WEBDL-2160p (~5–25GB)"
        elif size_gb >= _SIZE_CRIT_GB and quality not in _PREFERRED_QUALITIES:
            flagged = True
            reason = f"{size_gb:.1f}GB is critically oversized for {quality}"
            recommendation = "Delete and re-download — Radarr will grab a proper encode with the updated quality profile"
        elif size_gb >= _SIZE_WARN_GB:
            if quality in _PREFERRED_QUALITIES:
                # WEBDL-2160p at >20GB is normal for 4K HDR — lower severity
                if "2160" in quality and size_gb < 40:
                    reason = f"{size_gb:.1f}GB — large but acceptable for 4K HDR"
                    recommendation = "OK to keep — 4K HDR WEB-DL is naturally large"
                else:
                    flagged = True
                    reason = f"{size_gb:.1f}GB is larger than needed for {quality}"
                    recommendation = "Consider re-downloading — a smaller encode may be available"
            else:
                flagged = True
                reason = f"{size_gb:.1f}GB {quality} exceeds recommended size"
                recommendation = "Delete and re-download with updated quality profile"

        report.append(MovieQuality(
            radarr_id=m["id"],
            title=title,
            year=year,
            size_gb=round(size_gb, 2),
            quality=quality,
            flagged=flagged,
            reason=reason,
            recommendation=recommendation,
        ))

    report.sort(key=lambda x: (-x.size_gb, x.flagged))
    return report


# ---------------------------------------------------------------------------
# Sonarr TV show quality audit
# ---------------------------------------------------------------------------

_TV_SIZE_WARN_GB = 50.0     # combined with per-ep threshold
_TV_SIZE_CRIT_GB = 100.0    # not used alone — see logic below
_TV_EP_WARN_GB = 1.1        # >1.1GB/ep is high (30-min shows ~300-600MB, 60-min ~600MB-1.5GB)
_TV_EP_CRIT_GB = 2.0        # >2GB/ep is definitely remux/disc level
_TV_EP_SD_OK_GB = 0.6       # <0.6GB/ep is fine even for massive old SD libraries


@dataclass
class ShowQuality:
    sonarr_id: int
    title: str
    year: Optional[int]
    season_count: int
    episode_count: int
    size_gb: float
    size_per_episode_gb: float
    flagged: bool
    reason: str
    recommendation: str

    def as_dict(self) -> dict:
        return asdict(self)


def _get_sonarr_quality_report() -> List[ShowQuality]:
    rows = _rows_for_type("sonarr")
    if not rows:
        return []

    _, stype, name, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    if not key:
        return []

    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"
    headers = {"X-Api-Key": key}

    try:
        series_list = requests.get(
            f"{base}/api/v3/series",
            headers=headers,
            params={"includeSeasonImages": "false"},
            timeout=10,
        ).json()
    except Exception as e:
        log.error("Sonarr series list failed: %s", e)
        return []

    report: List[ShowQuality] = []
    for s in series_list:
        stats = s.get("statistics") or {}
        size_bytes = stats.get("sizeOnDisk", 0)
        if size_bytes == 0:
            continue  # not downloaded yet

        size_gb = size_bytes / 1024 ** 3
        episode_count = stats.get("episodeFileCount", 1)
        size_per_ep = size_gb / max(episode_count, 1)
        season_count = stats.get("seasonCount", 0)

        flagged = False
        reason = ""
        recommendation = ""

        if size_per_ep >= _TV_EP_CRIT_GB:
            # Any show averaging >2GB/episode is definitely remux or disc quality
            flagged = True
            reason = f"{size_per_ep:.2f}GB/episode ({size_gb:.1f}GB total) — remux or disc format"
            recommendation = (
                "Delete and re-download with updated Sonarr quality profile "
                "(WEBDL-1080p ~300MB–1.5GB per episode)"
            )
        elif size_per_ep >= _TV_EP_WARN_GB and size_gb >= _TV_SIZE_WARN_GB:
            # Moderate oversize — high bitrate Bluray encodes for a long-running series
            flagged = True
            reason = f"{size_per_ep:.2f}GB/episode ({size_gb:.1f}GB total) — larger than needed"
            recommendation = (
                "Delete and re-download — Sonarr will now grab WEBDL-1080p "
                "under the 2GB/ep cap"
            )
        elif size_per_ep < _TV_EP_SD_OK_GB and size_gb >= _TV_SIZE_CRIT_GB:
            # Large total but low per-episode — classic old SD show with many seasons
            reason = (
                f"{size_gb:.1f}GB total but only {size_per_ep:.2f}GB/episode — "
                "normal for a long-running SD-era series"
            )
            recommendation = "OK to keep — per-episode size is fine"
        elif size_gb >= _TV_SIZE_WARN_GB:
            reason = f"{size_gb:.1f}GB total, {size_per_ep:.2f}GB/ep — within acceptable range"
            recommendation = "OK to keep"

        report.append(ShowQuality(
            sonarr_id=s["id"],
            title=s.get("title", "?"),
            year=s.get("year"),
            season_count=season_count,
            episode_count=episode_count,
            size_gb=round(size_gb, 2),
            size_per_episode_gb=round(size_per_ep, 3),
            flagged=flagged,
            reason=reason,
            recommendation=recommendation,
        ))

    report.sort(key=lambda x: (-x.size_gb, x.flagged))
    return report


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@maven_bp.route("/api/quality-report")
@login_required
def api_quality_report():
    """Full per-movie + per-show quality + size audit. Admin only."""
    _require_admin()

    # Movies
    movies = _get_movie_quality_report()
    flagged_movies = [m for m in movies if m.flagged]
    ok_movies = [m for m in movies if not m.flagged]
    total_movie_gb = sum(m.size_gb for m in movies)
    flagged_movie_gb = sum(m.size_gb for m in flagged_movies)

    # TV shows
    shows = _get_sonarr_quality_report()
    flagged_shows = [s for s in shows if s.flagged]
    ok_shows = [s for s in shows if not s.flagged]
    total_tv_gb = sum(s.size_gb for s in shows)
    flagged_tv_gb = sum(s.size_gb for s in flagged_shows)

    # Disk
    disk = check_disk_space()

    return jsonify({
        "success": True,
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "disk": [c.as_dict() for c in disk],
        "movies": {
            "summary": {
                "total": len(movies),
                "flagged": len(flagged_movies),
                "total_size_gb": round(total_movie_gb, 1),
                "flagged_size_gb": round(flagged_movie_gb, 1),
                "potential_savings_gb": round(flagged_movie_gb * 0.85, 1),
            },
            "flagged": [m.as_dict() for m in flagged_movies],
            "ok": [m.as_dict() for m in ok_movies],
        },
        "tv": {
            "summary": {
                "total": len(shows),
                "flagged": len(flagged_shows),
                "total_size_gb": round(total_tv_gb, 1),
                "flagged_size_gb": round(flagged_tv_gb, 1),
            },
            "flagged": [s.as_dict() for s in flagged_shows],
            "ok": [s.as_dict() for s in ok_shows],
        },
    })


@maven_bp.route("/api/upgrade-oversized", methods=["POST"])
@login_required
def api_upgrade_oversized():
    """Trigger quality upgrades for oversized/blocked-quality movies.

    SAFE MODE (default, force=false):
        Triggers a Radarr search only. Radarr will download the better-quality
        release and atomically replace the existing file — nothing is deleted
        until the replacement is fully imported. This is the recommended path.

    FORCE MODE (requires explicit opt-in):
        Deletes the existing file FIRST then searches. Only use for formats
        Radarr will never auto-upgrade (e.g. BR-DISK now blocked by profile).
        Requires: {"force": true, "confirmed": "yes-delete-existing"}

    Body (optional):
        {"movie_ids": [1,2,3]}         — target specific movies
        {"force": true, "confirmed": "yes-delete-existing"}  — enable force mode
    """
    _require_admin()
    data = request.get_json() or {}
    requested_ids = data.get("movie_ids")
    force_delete = (
        data.get("force") is True
        and data.get("confirmed") == "yes-delete-existing"
    )

    rows = _rows_for_type("radarr")
    if not rows:
        return jsonify({"success": False, "error": "Radarr not configured"}), 400

    _, stype, name, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    scheme = "https" if use_ssl else "http"
    base = f"{scheme}://{host}:{port}"
    headers = {"X-Api-Key": key}

    if requested_ids:
        report = [m for m in _get_movie_quality_report() if m.radarr_id in requested_ids]
    else:
        report = [m for m in _get_movie_quality_report() if m.flagged]

    if not report:
        return jsonify({"success": True, "message": "No flagged movies to upgrade", "results": []})

    results = []
    search_ids = []

    for movie in report:
        try:
            if force_delete:
                # Force mode: delete existing file first, then search.
                # WARNING: content is gone until replacement downloads.
                m = requests.get(f"{base}/api/v3/movie/{movie.radarr_id}",
                                 headers=headers, timeout=8).json()
                file_id = (m.get("movieFile") or {}).get("id")
                if file_id:
                    d = requests.delete(f"{base}/api/v3/moviefile/{file_id}",
                                        headers=headers, timeout=8)
                    ok = d.status_code == 200
                    results.append({
                        "title": movie.title,
                        "radarr_id": movie.radarr_id,
                        "action": "deleted_and_searching",
                        "freed_gb": movie.size_gb if ok else 0,
                        "quality_was": movie.quality,
                        "deleted": ok,
                        "error": None if ok else f"HTTP {d.status_code}",
                    })
                    if ok:
                        search_ids.append(movie.radarr_id)
                else:
                    results.append({
                        "title": movie.title,
                        "radarr_id": movie.radarr_id,
                        "action": "skipped",
                        "error": "No file on record",
                    })
            else:
                # Safe mode (default): trigger search only.
                # Radarr downloads replacement then removes old file atomically.
                search_ids.append(movie.radarr_id)
                results.append({
                    "title": movie.title,
                    "radarr_id": movie.radarr_id,
                    "action": "search_triggered",
                    "size_gb": movie.size_gb,
                    "quality_was": movie.quality,
                    "note": (
                        "Radarr will download the replacement and swap files "
                        "automatically — existing content stays until then."
                    ),
                })
        except Exception as e:
            results.append({
                "title": movie.title,
                "radarr_id": movie.radarr_id,
                "action": "error",
                "error": str(e),
            })

    search_result = None
    if search_ids:
        try:
            sr = requests.post(f"{base}/api/v3/command", headers=headers,
                               json={"name": "MoviesSearch", "movieIds": search_ids},
                               timeout=8)
            search_result = sr.status_code
        except Exception as e:
            search_result = str(e)

    freed_total = sum(r.get("freed_gb", 0) for r in results)
    mode = "force-delete" if force_delete else "safe-search-only"
    return jsonify({
        "success": True,
        "mode": mode,
        "results": results,
        "search_triggered": len(search_ids),
        "search_http": search_result,
        "total_freed_gb": round(freed_total, 1),
        "note": (
            "Force mode: files deleted, searching for replacements."
            if force_delete else
            "Safe mode: searches triggered. Radarr will swap files automatically "
            "once replacements are downloaded. Existing content is untouched."
        ),
    })
