"""GET /api/canlii/* — CanLII (Canadian Legal Information Institute) integration.

Requires CANLII_API_KEY in environment. Without it, returns a 503 stub with instructions.
Free API key: https://www.canlii.org/en/info/api.html
"""
import os
import requests
from flask import Blueprint, jsonify, request

canlii_bp = Blueprint("canlii", __name__)

CANLII_BASE = "https://api.canlii.org/v1"
_API_KEY = None


def _get_api_key():
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.environ.get("CANLII_API_KEY", "")
    return _API_KEY


def _no_key_response():
    return jsonify({
        "error": "CanLII API key required",
        "message": "Set CANLII_API_KEY in your .env file to enable Canadian case law search.",
        "signup_url": "https://www.canlii.org/en/info/api.html",
        "status": "stub",
    }), 503


@canlii_bp.route("/api/canlii/status")
def canlii_status():
    """Check if CanLII API key is configured."""
    key = _get_api_key()
    if not key:
        return jsonify({"configured": False, "message": "CANLII_API_KEY not set"})
    return jsonify({"configured": True, "message": "CanLII API key is configured"})


@canlii_bp.route("/api/canlii/recent")
def canlii_recent():
    """Fetch recent case decisions from CanLII.

    Query params:
      - jurisdiction: e.g. 'ca' (federal), 'on' (Ontario), 'bc' (BC). Default: 'ca'
      - language: 'en' or 'fr'. Default: 'en'
      - limit: max results (default 20, max 100)
    """
    key = _get_api_key()
    if not key:
        return _no_key_response()

    jurisdiction = request.args.get("jurisdiction", "ca")
    language = request.args.get("language", "en")
    limit = min(int(request.args.get("limit", 20)), 100)

    try:
        url = f"{CANLII_BASE}/caseBrowse/{language}/{jurisdiction}/"
        resp = requests.get(url, params={"api_key": key, "offset": 0, "resultCount": limit}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        cases = data.get("cases", [])
        return jsonify({
            "jurisdiction": jurisdiction,
            "language": language,
            "count": len(cases),
            "cases": cases,
        })
    except requests.HTTPError as e:
        return jsonify({"error": f"CanLII API error: {e.response.status_code}", "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "CanLII request failed", "detail": str(e)}), 500


@canlii_bp.route("/api/canlii/search")
def canlii_search():
    """Search CanLII case law by keyword.

    Query params:
      - q: search keyword (required)
      - jurisdiction: e.g. 'ca', 'on', 'bc'. Default: 'ca'
      - language: 'en' or 'fr'. Default: 'en'
      - limit: max results (default 20, max 100)
    """
    key = _get_api_key()
    if not key:
        return _no_key_response()

    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    jurisdiction = request.args.get("jurisdiction", "ca")
    language = request.args.get("language", "en")
    limit = min(int(request.args.get("limit", 20)), 100)

    try:
        url = f"{CANLII_BASE}/caseBrowse/{language}/{jurisdiction}/"
        resp = requests.get(url, params={
            "api_key": key,
            "offset": 0,
            "resultCount": limit,
            "keyword": q,
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        cases = data.get("cases", [])
        return jsonify({
            "query": q,
            "jurisdiction": jurisdiction,
            "count": len(cases),
            "cases": cases,
        })
    except requests.HTTPError as e:
        return jsonify({"error": f"CanLII API error: {e.response.status_code}", "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "CanLII search failed", "detail": str(e)}), 500


@canlii_bp.route("/api/canlii/databases")
def canlii_databases():
    """List available CanLII databases (jurisdictions and courts)."""
    key = _get_api_key()
    if not key:
        return _no_key_response()

    language = request.args.get("language", "en")

    try:
        url = f"{CANLII_BASE}/caseBrowse/{language}/"
        resp = requests.get(url, params={"api_key": key}, timeout=15)
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.HTTPError as e:
        return jsonify({"error": f"CanLII API error: {e.response.status_code}", "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"error": "CanLII databases request failed", "detail": str(e)}), 500
