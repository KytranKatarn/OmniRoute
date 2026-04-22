"""
M.A.V.E.N. duplicate triage — task #2242.

Plex's `/library/sections/<id>/all?duplicate=1` endpoint already knows which
items in each library section have more than one matched file. We just query
it for every movie + show section and flatten the shape into something a
family member can act on (keep the highest-quality file, delete the others).

    GET /maven/duplicates            (HTML, admin-only)
    GET /maven/api/duplicates        (JSON,  admin-only)

Phase 1: Plex only. Jellyfin has a different duplicate model (merge-by-name)
that we'd want to layer on top separately — deferred.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import requests
from flask import jsonify, render_template
from flask_login import current_user, login_required

from . import maven_bp
from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.duplicates")


def _plex_sections(scheme: str, host: str, port: int, token: str) -> List[Dict]:
    url = f"{scheme}://{host}:{port}/library/sections"
    r = requests.get(
        url,
        headers={"X-Plex-Token": token, "Accept": "application/json"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("MediaContainer", {}).get("Directory", []) or []


def _plex_duplicates(
    scheme: str, host: str, port: int, token: str, section_key: str
) -> List[Dict]:
    """Plex's built-in duplicate filter — only returns items with >1 matched
    file in the library."""
    url = f"{scheme}://{host}:{port}/library/sections/{section_key}/all"
    r = requests.get(
        url,
        params={"duplicate": 1},
        headers={"X-Plex-Token": token, "Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("MediaContainer", {}).get("Metadata", []) or []


def _flatten(item: Dict) -> Dict:
    """Trim a Plex Metadata blob to what the UI needs. Sums file sizes and
    keeps per-file paths + resolution so humans can pick the winner."""
    files: List[Dict] = []
    total_bytes = 0
    for media in item.get("Media", []) or []:
        resolution = media.get("videoResolution") or ""
        bitrate = media.get("bitrate")
        container = media.get("container")
        for part in media.get("Part", []) or []:
            size = int(part.get("size") or 0)
            total_bytes += size
            files.append({
                "path": part.get("file") or "",
                "size_bytes": size,
                "size_gb": round(size / 1024 / 1024 / 1024, 2),
                "resolution": resolution,
                "container": container,
                "bitrate": bitrate,
            })
    # Sort files by size descending — the big one is usually the "keeper"
    files.sort(key=lambda f: f["size_bytes"], reverse=True)
    return {
        "rating_key": item.get("ratingKey"),
        "title": item.get("title"),
        "year": item.get("year"),
        "type": item.get("type"),  # movie | episode
        "file_count": len(files),
        "total_size_gb": round(total_bytes / 1024 / 1024 / 1024, 2),
        "files": files,
    }


def run_duplicate_scan() -> Dict:
    """Scan every Plex movie + show section for items with duplicate files.
    Returns a shape usable by HTML + JSON + future agent dispatch."""
    rows = _rows_for_type("plex")
    if not rows:
        return {"error": "Plex not configured"}
    _, _, name, host, port, use_ssl, enc, *_ = rows[0]
    token = _decrypt_key(enc)
    if not token:
        return {"error": "Plex API key missing"}
    scheme = "https" if use_ssl else "http"

    try:
        sections = _plex_sections(scheme, host, port, token)
    except Exception as e:
        log.warning("plex sections failed: %s", e)
        return {"error": f"Plex unreachable: {e}"}

    movie_dupes: List[Dict] = []
    show_dupes: List[Dict] = []
    potential_savings_bytes = 0

    for sec in sections:
        sec_type = sec.get("type")
        if sec_type not in ("movie", "show"):
            continue
        try:
            items = _plex_duplicates(scheme, host, port, token, sec["key"])
        except Exception as e:
            log.warning("plex duplicate scan (section %s) failed: %s",
                        sec.get("title"), e)
            continue
        for it in items:
            flat = _flatten(it)
            # Savings = total minus the keeper (biggest) file.
            if flat["file_count"] > 1 and flat["files"]:
                keeper = flat["files"][0]["size_bytes"]
                potential_savings_bytes += max(
                    0, sum(f["size_bytes"] for f in flat["files"]) - keeper,
                )
            if sec_type == "movie":
                movie_dupes.append(flat)
            else:
                show_dupes.append(flat)

    return {
        "source": name,
        "movies": movie_dupes,
        "shows": show_dupes,
        "summary": {
            "movie_count": len(movie_dupes),
            "show_count": len(show_dupes),
            "potential_savings_gb": round(
                potential_savings_bytes / 1024 / 1024 / 1024, 2
            ),
        },
    }


def _require_admin():
    from flask import abort
    if not getattr(current_user, "is_admin", False):
        abort(403)


@maven_bp.route("/api/duplicates")
@login_required
def api_duplicates():
    _require_admin()
    return jsonify(run_duplicate_scan())


@maven_bp.route("/duplicates")
@login_required
def duplicates_page():
    _require_admin()
    report = run_duplicate_scan()
    return render_template("maven_duplicates.html", report=report)
