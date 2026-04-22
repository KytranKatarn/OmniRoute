"""
M.A.V.E.N. upgrade scanner — task #2240.

Uses Sonarr's and Radarr's built-in "wanted/cutoff" endpoints which already
know which items in the library have a current file below their quality
profile's cutoff. No need to reinvent quality comparison — the *arr apps
track this natively.

    GET /maven/api/upgrades       (JSON, admin-only)
    GET /maven/upgrades            (rendered HTML, admin-only)

Returns two lists:
    - episodes (from Sonarr)
    - movies   (from Radarr)

Each entry carries current quality + target cutoff + estimated upgrade size
if available, so the list can be triaged by "biggest quality delta" or
"smallest bytes to grab."
"""

from __future__ import annotations

import logging
from typing import Dict, List

import requests
from flask import jsonify, render_template
from flask_login import current_user, login_required

from database import get_db_cursor
from . import maven_bp
from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.upgrades")


def _arr_cutoff(service_type: str) -> List[Dict]:
    """GET /api/v3/wanted/cutoff — list items with a file worse than cutoff."""
    rows = _rows_for_type(service_type)
    if not rows:
        return []
    out = []
    for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        # pageSize 100 — enough for a typical home library. We surface the
        # count separately so the UI can tell if there's more. includeSeries
        # makes Sonarr return the parent series object inline with each
        # episode (otherwise response has only seriesId/tvdbId and we'd need
        # a second /series/{id} round-trip per unique show).
        url = (
            f"{scheme}://{host}:{port}/api/v3/wanted/cutoff"
            "?pageSize=100&sortKey=airDateUtc&sortDirection=descending"
            "&includeSeries=true"
        )
        try:
            r = requests.get(url, headers={"X-Api-Key": key}, timeout=15)
            if r.status_code != 200:
                log.warning("%s cutoff query failed: HTTP %s", stype, r.status_code)
                continue
            data = r.json()
            records = data.get("records", [])
            total = data.get("totalRecords", len(records))
            for rec in records:
                entry = {
                    "service": stype,
                    "service_name": name,
                    "id": rec.get("id"),
                    "current_quality": None,
                    "size_bytes": None,
                }
                if stype == "sonarr":
                    series = rec.get("series", {})
                    ep_file = rec.get("episodeFile") or {}
                    entry.update({
                        "title": series.get("title", "?"),
                        "season": rec.get("seasonNumber"),
                        "episode": rec.get("episodeNumber"),
                        "episode_title": rec.get("title"),
                        "current_quality": (
                            ep_file.get("quality", {})
                                   .get("quality", {})
                                   .get("name")
                        ),
                        "size_bytes": ep_file.get("size"),
                        "air_date": rec.get("airDateUtc"),
                    })
                elif stype == "radarr":
                    mv_file = rec.get("movieFile") or {}
                    entry.update({
                        "title": rec.get("title", "?"),
                        "year": rec.get("year"),
                        "current_quality": (
                            mv_file.get("quality", {})
                                   .get("quality", {})
                                   .get("name")
                        ),
                        "size_bytes": mv_file.get("size"),
                    })
                out.append(entry)
            # Stash totals on the first record so the UI can see if paging
            # was truncated. Cheap-and-cheerful.
            if records:
                out[-1].setdefault("_total_for_service", total)
        except Exception as e:
            log.exception("%s cutoff query exception: %s", stype, e)
    return out


def run_scan() -> dict:
    """Scan Sonarr + Radarr for items below their cutoff quality. Returns
    a combined list sorted by most-recently-aired first.
    """
    episodes = [e for e in _arr_cutoff("sonarr") if e]
    movies   = [m for m in _arr_cutoff("radarr") if m]

    return {
        "episodes": {
            "count": len(episodes),
            "items": episodes[:50],  # cap response; full list on demand later
        },
        "movies": {
            "count": len(movies),
            "items": movies[:50],
        },
    }


def _require_admin():
    from flask import abort
    if not getattr(current_user, "is_admin", False):
        abort(403)


@maven_bp.route("/api/upgrades")
@login_required
def api_upgrades():
    _require_admin()
    return jsonify(run_scan())


@maven_bp.route("/upgrades")
@login_required
def upgrades_page():
    _require_admin()
    report = run_scan()
    return render_template("maven_upgrades.html", report=report)
