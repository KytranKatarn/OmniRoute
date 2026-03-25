"""Public Compliance Badge API — no auth required."""

import logging
from flask import jsonify, Response, Blueprint
from database import get_db_cursor

logger = logging.getLogger(__name__)

badge_bp = Blueprint("compliance_badges", __name__, url_prefix="/api/public/compliance")


def _get_latest_scan():
    """Get most recent completed scan with per-pack breakdown."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT scan_id, score, passed, failed, errors, total_rules, completed_at
                FROM compliance_scans
                WHERE completed_at IS NOT NULL
                ORDER BY completed_at DESC LIMIT 1
            """
            )
            scan = cur.fetchone()
            if not scan:
                return None

            cur.execute(
                """
                SELECT pack_id,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status='pass') as passed,
                    COUNT(*) FILTER (WHERE status='fail') as failed
                FROM compliance_scan_results
                WHERE scan_id = %s
                GROUP BY pack_id
            """,
                (scan["scan_id"],),
            )
            packs = {}
            for row in cur.fetchall():
                total = row["total"]
                passed = row["passed"]
                score = round((passed / total) * 100, 1) if total > 0 else 0
                packs[row["pack_id"]] = {
                    "score": score,
                    "passed": passed,
                    "total": total,
                }

            return {
                "score": float(scan["score"]) if scan["score"] else 0,
                "passed": scan["passed"],
                "failed": scan["failed"],
                "errors": scan["errors"],
                "total": scan["total_rules"],
                "completed_at": (scan["completed_at"].isoformat() if scan["completed_at"] else None),
                "packs": packs,
            }
    except Exception as e:
        logger.error("Badge API error: %s", e)
        return None


def _grade(score):
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 85:
        return "B+"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _badge_color(score):
    if score >= 90:
        return "#22c55e"  # green
    if score >= 80:
        return "#3b82f6"  # blue
    if score >= 70:
        return "#f59e0b"  # yellow
    if score >= 60:
        return "#f97316"  # orange
    return "#ef4444"  # red


def _render_svg_badge(label, value, color):
    """Render a shields.io-style SVG badge."""
    label_width = len(label) * 6.5 + 12
    value_width = len(value) * 6.5 + 12
    total_width = label_width + value_width

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="a">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#a)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + value_width / 2}" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="{label_width + value_width / 2}" y="14">{value}</text>
  </g>
</svg>"""


@badge_bp.route("/badges")
def api_badges_json():
    """Public JSON endpoint -- compliance scores."""
    data = _get_latest_scan()
    if not data:
        return jsonify({"stig": {"score": None, "message": "No scan data available"}}), 200

    score = data["score"]
    return jsonify(
        {
            "stig": {
                "score": score,
                "grade": _grade(score),
                "passed": data["passed"],
                "failed": data["failed"],
                "total": data["total"],
                "last_scan": data["completed_at"],
                "packs": data["packs"],
            }
        }
    )


@badge_bp.route("/badge/stig.svg")
def badge_stig_svg():
    """SVG badge: STIG | score% grade"""
    data = _get_latest_scan()
    score = data["score"] if data else 0
    grade = _grade(score)
    color = _badge_color(score)
    svg = _render_svg_badge("STIG", f"{score}% {grade}", color)
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@badge_bp.route("/badge/soc2.svg")
def badge_soc2_svg():
    """SVG badge: SOC 2 | score (placeholder until SOC 2 matrix is built)"""
    data = _get_latest_scan()
    score = data["score"] if data else 0
    grade = _grade(score)
    color = _badge_color(score)
    svg = _render_svg_badge("SOC 2", f"{score}% {grade}", color)
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@badge_bp.route("/badge/ubuntu.svg")
def badge_ubuntu_svg():
    """SVG badge: Ubuntu STIG | score%"""
    data = _get_latest_scan()
    pack = (data or {}).get("packs", {}).get("ubuntu-22.04-stig", {})
    score = pack.get("score", 0)
    color = _badge_color(score)
    svg = _render_svg_badge("Ubuntu STIG", f"{score}%", color)
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@badge_bp.route("/badge/docker.svg")
def badge_docker_svg():
    """SVG badge: Docker STIG | score%"""
    data = _get_latest_scan()
    pack = (data or {}).get("packs", {}).get("docker-stig", {})
    score = pack.get("score", 0)
    color = _badge_color(score)
    svg = _render_svg_badge("Docker STIG", f"{score}%", color)
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@badge_bp.route("/badge/network.svg")
def badge_network_svg():
    """SVG badge: Network STIG | score%"""
    data = _get_latest_scan()
    pack = (data or {}).get("packs", {}).get("network-stig", {})
    score = pack.get("score", 0)
    color = _badge_color(score)
    svg = _render_svg_badge("Network STIG", f"{score}%", color)
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@badge_bp.route("/badge/cis.svg")
def badge_cis_svg():
    """SVG badge: CIS Benchmark | score%"""
    data = _get_latest_scan()
    pack = (data or {}).get("packs", {}).get("cis-ubuntu-22.04", {})
    score = pack.get("score", 0)
    color = _badge_color(score)
    svg = _render_svg_badge("CIS Benchmark", f"{score}%", color)
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@badge_bp.route("/badge/hipaa.svg")
def badge_hipaa_svg():
    """Placeholder for HIPAA -- Phase 11"""
    svg = _render_svg_badge("HIPAA", "pending", "#94a3b8")
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )
