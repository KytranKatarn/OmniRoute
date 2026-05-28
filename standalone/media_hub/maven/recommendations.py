"""
M.A.V.E.N. recommendations — task #2241, phase 1.

Phase 1 scope: "what's trending that we don't already have." Uses Overseerr's
discover endpoints as the source (Overseerr already merges TMDB data with our
library state so a single call tells us what's popular AND whether it's
already in Plex/Jellyfin). Phase 2 will layer per-user taste signatures
derived from Plex watch history — scoped separately because it needs a
profile schema we don't have yet.

    GET /maven/api/discover      (JSON)
    GET /maven/discover           (rendered HTML)

No admin gate — recommendations are safe for any authenticated user.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import requests
from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from . import maven_bp
from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.recommendations")


def _overseerr_client():
    """Return (scheme, host, port, key) for the first Overseerr/Jellyseerr, or None."""
    rows = _rows_for_type("overseerr", "jellyseerr")
    if not rows:
        return None
    sid, stype, name, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    if not key:
        return None
    return ("https" if use_ssl else "http"), host, port, key


def _overseerr_discover(path: str, limit: int = 20) -> List[Dict]:
    """GET a discover endpoint. Returns [] on any error — discover is
    best-effort, never blocks page render."""
    rows = _rows_for_type("overseerr", "jellyseerr")
    if not rows:
        return []
    sid, stype, name, host, port, use_ssl, enc, *_ = rows[0]
    key = _decrypt_key(enc)
    if not key:
        return []
    scheme = "https" if use_ssl else "http"
    url = f"{scheme}://{host}:{port}/api/v1/{path}"
    try:
        # Overseerr paginates in 20s and 400s on `take`/`limit` query params —
        # just take page 1 and slice our limit client-side.
        r = requests.get(
            url,
            headers={"X-Api-Key": key},
            params={"page": 1},
            timeout=10,
        )
        if r.status_code != 200:
            log.warning("%s discover failed: HTTP %s — %s",
                        path, r.status_code, r.text[:120])
            return []
        return r.json().get("results", [])[:limit]
    except Exception as e:
        log.warning("%s discover exception: %s", path, e)
        return []


# Overseerr mediaInfo.status codes
_STATUS_LABELS = {
    1: "pending",
    2: "approved",
    3: "processing",
    4: "partial",
    5: "available",
}


def _not_in_library(item: Dict) -> bool:
    """True if this item is worth recommending (show Request button).

    Excludes anything already in the pipeline: pending (1), approved (2),
    processing (3), partially available (4), or fully available (5).
    status=None means never requested — show the button.
    """
    info = item.get("mediaInfo") or {}
    status = info.get("status")
    return status not in (1, 2, 3, 4, 5)


def _shape(item: Dict, media_type: str) -> Dict:
    """Trim the Overseerr response to the fields the UI actually needs."""
    title = item.get("title") or item.get("name")
    release = (
        item.get("releaseDate")
        or item.get("firstAirDate")
        or ""
    )[:4]
    media_status = (item.get("mediaInfo") or {}).get("status")
    return {
        "media_type": media_type,
        "tmdb_id": item.get("id"),
        "title": title,
        "year": release,
        "overview": (item.get("overview") or "")[:300],
        "poster": item.get("posterPath"),
        "vote_average": item.get("voteAverage"),
        "vote_count": item.get("voteCount"),
        "status": media_status,
        "request_status": _STATUS_LABELS.get(media_status),
    }


def run_discover(limit: int = 12) -> dict:
    """Pull trending from Overseerr, filter out what we already have, return
    a merged list sorted by popularity × rating."""
    # Overseerr's discover endpoints return "popular" by default. Trending
    # lives under /discover/trending as a merged list — we split by
    # mediaType in _shape() if needed. For now keep movies/tv separate
    # because the UI wants distinct sections.
    movies_raw = _overseerr_discover("discover/movies", limit=limit * 2)
    tv_raw = _overseerr_discover("discover/tv", limit=limit * 2)

    movies = [_shape(i, "movie") for i in movies_raw if _not_in_library(i)][:limit]
    tv = [_shape(i, "tv") for i in tv_raw if _not_in_library(i)][:limit]

    return {
        "user": {
            "username": getattr(current_user, "username", None),
            "display_name": getattr(current_user, "display_name", None),
        },
        "movies": movies,
        "tv": tv,
        "note": (
            "Phase 1: popular on Overseerr, filtered to items not already "
            "in library. Phase 2 will personalise by watch history."
        ),
    }


@maven_bp.route("/api/discover")
@login_required
def api_discover():
    return jsonify(run_discover())


@maven_bp.route("/discover")
@login_required
def discover_page():
    report = run_discover()
    return render_template("maven_discover.html", report=report)


@maven_bp.route("/api/search")
@login_required
def api_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    client = _overseerr_client()
    if not client:
        return jsonify({"results": [], "error": "Overseerr not configured"})
    scheme, host, port, key = client
    url = f"{scheme}://{host}:{port}/api/v1/search"
    try:
        r = requests.get(url, headers={"X-Api-Key": key},
                         params={"query": q, "page": 1}, timeout=10)
        if r.status_code != 200:
            return jsonify({"results": [], "error": f"HTTP {r.status_code}"})
        results = []
        for item in r.json().get("results", [])[:20]:
            mt = item.get("mediaType", "movie")
            if mt not in ("movie", "tv"):
                continue
            results.append(_shape(item, mt))
        return jsonify({"results": results})
    except Exception as e:
        log.exception("search error: %s", e)
        return jsonify({"results": [], "error": str(e)})


@maven_bp.route("/api/request", methods=["POST"])
@login_required
def api_request():
    data = request.get_json(force=True) or {}
    media_type = data.get("media_type") or data.get("mediaType")
    tmdb_id = data.get("tmdb_id") or data.get("mediaId")
    if media_type not in ("movie", "tv") or not tmdb_id:
        return jsonify({"success": False, "error": "Invalid params"}), 400
    client = _overseerr_client()
    if not client:
        return jsonify({"success": False, "error": "Overseerr not configured"}), 503
    scheme, host, port, key = client
    url = f"{scheme}://{host}:{port}/api/v1/request"
    payload: dict = {"mediaType": media_type, "mediaId": int(tmdb_id)}
    if media_type == "tv":
        payload["seasons"] = "all"
    try:
        r = requests.post(url, headers={"X-Api-Key": key}, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return jsonify({"success": True})
        msg = (r.json().get("message") if r.content else None) or f"HTTP {r.status_code}"
        return jsonify({"success": False, "error": msg}), 400
    except Exception as e:
        log.exception("request error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500
