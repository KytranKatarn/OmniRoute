"""geocoder.py — L.O.C.A.L. geo extraction wrapper with province centroid fallback."""
import re

from .ai_dispatcher import analyze

PROVINCE_CENTROIDS = {
    "AB": (53.9333, -116.5765),
    "BC": (53.7267, -127.6476),
    "MB": (56.4152, -98.7394),
    "NB": (46.5653, -66.4619),
    "NL": (53.1355, -57.6604),
    "NS": (44.6820, -63.7443),
    "NT": (64.2823, -119.1820),
    "NU": (70.2998, -83.1076),
    "ON": (51.2538, -85.3232),
    "PE": (46.5107, -63.4168),
    "QC": (53.0000, -70.0000),
    "SK": (52.9399, -106.4509),
    "YT": (64.2823, -135.0000),
}

VALID_PROVINCES = set(PROVINCE_CENTROIDS.keys())

_PROVINCE_PATTERNS = {
    "ON": r"\b(ontario|toronto|ottawa|hamilton|london|windsor)\b",
    "QC": r"\b(quebec|qu[eé]bec|montreal|montr[eé]al|laval|gatineau|longueuil)\b",
    "BC": r"\b(british columbia|vancouver|surrey|burnaby|victoria)\b",
    "AB": r"\b(alberta|calgary|edmonton|red deer|lethbridge)\b",
    "SK": r"\b(saskatchewan|regina|saskatoon)\b",
    "MB": r"\b(manitoba|winnipeg|brandon)\b",
    "NS": r"\b(nova scotia|halifax|dartmouth)\b",
    "NB": r"\b(new brunswick|moncton|saint john|fredericton)\b",
    "NL": r"\b(newfoundland|labrador|st\.? john'?s)\b",
    "PE": r"\b(prince edward island|pei|charlottetown)\b",
    "YT": r"\b(yukon|whitehorse)\b",
    "NT": r"\b(northwest territories|yellowknife)\b",
    "NU": r"\b(nunavut|iqaluit)\b",
}


def extract_geo(article_id: int, title: str, body: str) -> dict:
    """Extract geo info via L.O.C.A.L. agent. Falls back to heuristic if agent unavailable.

    Always returns a dict with a terminal geo_scope so the backlog worker won't
    re-dispatch the same article. 'unmappable' is the terminal state when
    neither LLM nor heuristic finds a Canadian location — see #2959.
    """
    result = analyze("geo", article_id, title, body)
    if result and isinstance(result, dict) and result.get("province_code") in VALID_PROVINCES:
        pc = result["province_code"]
        if not result.get("lat") and pc in PROVINCE_CENTROIDS:
            result["lat"], result["lng"] = PROVINCE_CENTROIDS[pc]
        result.setdefault("country_code", "CA")
        return result

    # Heuristic fallback: province name in title or first 500 chars of body
    text = f"{title} {body[:500]}".lower()
    for pc, pattern in _PROVINCE_PATTERNS.items():
        if re.search(pattern, text):
            lat, lng = PROVINCE_CENTROIDS[pc]
            return {
                "province_code": pc,
                "city": None,
                "lat": lat,
                "lng": lng,
                "country_code": "CA",
                "geo_scope": "provincial",
                "geo_confidence": 0.5,
            }
    # Nothing matched — terminal state, prevents re-fetch loop (#2959).
    return {
        "province_code": None,
        "city": None,
        "lat": None,
        "lng": None,
        "country_code": None,
        "geo_scope": "unmappable",
        "geo_confidence": 0.0,
    }
