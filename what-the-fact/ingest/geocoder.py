"""geocoder.py — L.O.C.A.L. geo extraction wrapper with province centroid fallback."""
import os
import re

from .ai_dispatcher import analyze

# When true, skip the LLM call entirely and use heuristic-only geo.
# Set WTF_GEO_LIVE_SKIP=true when the fleet is under backlog load to prevent
# the ingest thread from blocking 240s per article. The geo backlog worker
# (WTF_GEO_BACKLOG_ENABLED) handles LLM geo for articles marked pending.
_GEO_LIVE_SKIP = os.environ.get("WTF_GEO_LIVE_SKIP", "false").lower() == "true"

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


# Country centroids for major non-Canadian geographies (#2960 Phase B).
# Used when L.O.C.A.L. returns country_code but no lat/lng. Centroids are
# rough country centers — good enough for map rendering at country scale.
_COUNTRY_CENTROIDS = {
    "US": (39.8283, -98.5795),
    "GB": (54.7024, -3.2766),
    "FR": (46.6034, 1.8883),
    "DE": (51.1657, 10.4515),
    "MX": (23.6345, -102.5528),
    "AU": (-25.2744, 133.7751),
    "CN": (35.8617, 104.1954),
    "IN": (20.5937, 78.9629),
    "JP": (36.2048, 138.2529),
    "BR": (-14.2350, -51.9253),
    "RU": (61.5240, 105.3188),
    "UA": (48.3794, 31.1656),
    "IL": (31.0461, 34.8516),
    "PS": (31.9522, 35.2332),
    "IR": (32.4279, 53.6880),
    "AE": (23.4241, 53.8478),
    "SA": (23.8859, 45.0792),
    "EG": (26.8206, 30.8025),
    "NG": (9.0820, 8.6753),
    "ZA": (-30.5595, 22.9375),
}

# Option A: national broadcasters — when content analysis finds no location,
# these outlets produce national Canadian stories, not truly unmappable ones.
_SOURCE_NATIONAL_OUTLETS = frozenset({
    "aptn_news", "bnn_bloomberg", "cbc_english", "cbc_north", "canadaland",
    "ctv_news", "financial_post", "global_news", "globe_mail", "ipolitics",
    "national_post", "press_progress", "the_conversation_canada",
    "the_hub_canada", "the_narwhal", "true_north",
})

# Option B: regional outlets with a known home province — low-confidence
# provincial fallback when content analysis finds no location signal.
_SOURCE_PROVINCE_MAP = {
    "calgary_herald": "AB", "edmonton_journal": "AB", "windspeaker": "AB",
    "journal_de_montreal": "QC", "la_presse": "QC", "lactualite": "QC",
    "le_devoir": "QC", "le_quotidien": "QC", "le_soleil": "QC",
    "montreal_gazette": "QC", "ricochet_media": "QC",
    "ottawa_citizen": "ON", "toronto_star": "ON", "turtle_island_news": "ON",
    "indiginews": "BC", "the_tyee": "BC", "vancouver_sun": "BC",
    "winnipeg_free_press": "MB",
    "regina_leaderpost": "SK", "saskatoon_starphoenix": "SK",
    "halifax_examiner": "NS", "kukukwes_news": "NS",
    "saltwire_news": "NS", "the_coast_halifax": "NS",
    "nb_media_coop": "NB",
    "nunatsiaq_news": "NU",
    "cabin_radio": "NT",
    "yukon_news": "YT",
}

# Heuristic country patterns — only fire when no LLM result and no Canadian
# province match. Keep narrow so we don't false-positive on Canadian articles
# that mention foreign countries in passing.
_COUNTRY_PATTERNS = {
    "US": r"\b(united states|u\.?s\.?a?\.?|washington d\.?c|white house|capitol hill|biden|trump|congress|nasdaq|s&p 500)\b",
    "GB": r"\b(united kingdom|britain|england|scotland|wales|northern ireland|london|downing street|parliament uk|bbc)\b",
    "FR": r"\b(france|paris|macron|élysée|elysee)\b",
    "DE": r"\b(germany|berlin|bundestag|merkel|scholz)\b",
    "MX": r"\b(mexico|mexico city|amlo|sheinbaum)\b",
    "AU": r"\b(australia|sydney|canberra|melbourne)\b",
    "CN": r"\b(china|beijing|shanghai|xi jinping|ccp)\b",
    "IN": r"\b(india|new delhi|mumbai|modi)\b",
    "UA": r"\b(ukraine|kyiv|zelensky|donbas)\b",
    "IL": r"\b(israel|jerusalem|tel aviv|netanyahu|knesset)\b",
    "PS": r"\b(palestine|gaza|west bank|hamas)\b",
}


def _sanitize(result: dict) -> dict:
    """Convert LLM string 'null'/'none' to Python None; coerce lat/lng to float.

    L.O.C.A.L. occasionally returns the literal string "null" for fields it
    can't populate (e.g. city="null", lat="null"). Passing those to a numeric
    Postgres column raises InvalidTextRepresentation. This sanitizer runs once
    on every LLM result before any downstream use.
    """
    cleaned = {}
    for k, v in result.items():
        if isinstance(v, str) and v.strip().lower() in ("null", "none", ""):
            cleaned[k] = None
        elif k in ("lat", "lng") and isinstance(v, str):
            try:
                cleaned[k] = float(v)
            except (ValueError, TypeError):
                cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


def _fill_if_blank(result: dict, key: str, value):
    """Apply a default when `key` is missing OR present-but-empty.

    ⚠️ NEVER use dict.setdefault() on a dict that has been through _sanitize().
    Sanitize's entire job is turning the LLM's "null"/"none"/"" into a real
    None, which leaves the KEY PRESENT. setdefault only fills a MISSING key, so
    it silently does nothing and the default never lands.

    That is not hypothetical (#6210): L.O.C.A.L. returns country_code="null" on
    the ordinary Canadian path, so `result.setdefault("country_code", "CA")` was
    a no-op for 21 days straight — 4,460 provincial articles in one week, ONE of
    which had a country. /map then coloured every pin the same "unknown" grey.
    """
    if result.get(key) is None:
        result[key] = value


def extract_geo(article_id, title, body, source_slug=None):
    """Extract geo info via L.O.C.A.L. agent. Falls back to heuristic if agent unavailable.

    Always returns a dict with a terminal geo_scope so the backlog worker won't
    re-dispatch the same article. 'unmappable' is the terminal state when
    neither LLM nor heuristic finds a usable location — see #2959.

    Phase B (#2960): also returns non-Canadian country_code when the article
    is about a foreign country. country_code='US'/'GB'/'FR'/etc. with
    geo_scope='international' and lat/lng from _COUNTRY_CENTROIDS where known.
    """
    result = None
    if not _GEO_LIVE_SKIP:
        result = analyze("geo", article_id, title, body)
        if result and isinstance(result, dict):
            result = _sanitize(result)
    # Canadian province path (existing behaviour)
    if result and isinstance(result, dict) and result.get("province_code") in VALID_PROVINCES:
        pc = result["province_code"]
        if not result.get("lat") and pc in PROVINCE_CENTROIDS:
            result["lat"], result["lng"] = PROVINCE_CENTROIDS[pc]
        # A valid Canadian province IS in Canada — this is definitional, not a
        # guess, so it overwrites a blank rather than merely defaulting one.
        _fill_if_blank(result, "country_code", "CA")
        return result

    # International path (#2960 Phase B): country_code set, no province
    if result and isinstance(result, dict):
        cc = (result.get("country_code") or "").upper()
        if cc and cc != "CA" and len(cc) == 2:
            if not result.get("lat") and cc in _COUNTRY_CENTROIDS:
                result["lat"], result["lng"] = _COUNTRY_CENTROIDS[cc]
            result["province_code"] = None
            # Same trap as above — latent here only because this path is rare
            # (14 rows/week). A sanitized geo_scope="null" would have left the
            # column NULL rather than "international".
            _fill_if_blank(result, "geo_scope", "international")
            return result

    # Heuristic fallback — Canadian province first (preserve existing logic)
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
    # Then non-Canadian country heuristics (#2960 Phase B)
    for cc, pattern in _COUNTRY_PATTERNS.items():
        if re.search(pattern, text):
            lat, lng = _COUNTRY_CENTROIDS.get(cc, (None, None))
            return {
                "province_code": None,
                "city": None,
                "lat": lat,
                "lng": lng,
                "country_code": cc,
                "geo_scope": "international",
                "geo_confidence": 0.3,  # lower — keyword match only
            }
    slug = (source_slug or "").strip()

    # Option B: regional outlet → province fallback (low confidence, beats unmappable).
    if slug in _SOURCE_PROVINCE_MAP:
        pc = _SOURCE_PROVINCE_MAP[slug]
        lat, lng = PROVINCE_CENTROIDS[pc]
        return {
            "province_code": pc,
            "city": None,
            "lat": lat,
            "lng": lng,
            "country_code": "CA",
            "geo_scope": "provincial",
            "geo_confidence": 0.35,
        }

    # Option A: national broadcaster → national (not unmappable).
    if slug in _SOURCE_NATIONAL_OUTLETS:
        return {
            "province_code": None,
            "city": None,
            "lat": None,
            "lng": None,
            "country_code": "CA",
            "geo_scope": "national",
            "geo_confidence": 0.2,
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
