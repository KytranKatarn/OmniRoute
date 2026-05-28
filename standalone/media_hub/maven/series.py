"""
M.A.V.E.N. series completeness — T3299.

Queries Sonarr /api/v3/series for every tracked show and surfaces how many
episodes are on disk vs how many have aired, so you can see at a glance which
series are incomplete.

    GET /maven/api/series    (JSON, login required)
    GET /maven/series         (HTML, login required)

Each entry includes:
    title, status, season_count,
    episode_file_count (files on disk),
    episode_count      (monitored aired episodes),
    total_episode_count (including unaired future eps),
    percent            (episode_file_count / episode_count * 100),
    size_gb
"""

from __future__ import annotations

import logging
from typing import Dict, List

import requests
from flask import jsonify, render_template
from flask_login import login_required

from . import maven_bp
from .troubleshoot import _decrypt_key, _rows_for_type

log = logging.getLogger("media_hub.maven.series")


def _fetch_series() -> List[Dict]:
    rows = _rows_for_type("sonarr")
    if not rows:
        return []
    out = []
    for sid, stype, name, host, port, use_ssl, enc, *_ in rows:
        key = _decrypt_key(enc)
        if not key:
            continue
        scheme = "https" if use_ssl else "http"
        url = f"{scheme}://{host}:{port}/api/v3/series"
        try:
            r = requests.get(url, headers={"X-Api-Key": key}, timeout=15)
            if r.status_code != 200:
                log.warning("Sonarr series query failed: HTTP %s", r.status_code)
                continue
            for s in r.json():
                stats = s.get("statistics") or {}
                ep_file = stats.get("episodeFileCount", 0)
                ep_count = stats.get("episodeCount", 0)
                percent = round((ep_file / ep_count * 100) if ep_count else 0, 1)
                out.append({
                    "title": s.get("title", "?"),
                    "status": s.get("status", "unknown"),
                    "season_count": stats.get("seasonCount") or s.get("seasonCount", 0),
                    "episode_file_count": ep_file,
                    "episode_count": ep_count,
                    "total_episode_count": stats.get("totalEpisodeCount", ep_count),
                    "percent": percent,
                    "size_gb": round(stats.get("sizeOnDisk", 0) / 1_073_741_824, 2),
                })
        except Exception as e:
            log.exception("Sonarr series fetch error: %s", e)

    out.sort(key=lambda x: (x["percent"], x["title"]))
    return out


def run_scan() -> dict:
    series = _fetch_series()
    total_files = sum(s["episode_file_count"] for s in series)
    total_aired = sum(s["episode_count"] for s in series)
    total_size = round(sum(s["size_gb"] for s in series), 2)
    complete = sum(1 for s in series if s["percent"] >= 100)
    return {
        "series": series,
        "total_series": len(series),
        "complete_series": complete,
        "total_episode_files": total_files,
        "total_episode_count": total_aired,
        "total_size_gb": total_size,
    }


@maven_bp.route("/api/series")
@login_required
def api_series():
    return jsonify(run_scan())


@maven_bp.route("/series")
@login_required
def series_page():
    report = run_scan()
    return render_template("maven_series.html", report=report)
