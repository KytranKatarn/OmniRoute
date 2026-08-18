"""Pure payload builder for the A.U.R.O.R.A. /weather map (project #393).

Deliberately free of Flask and SQLAlchemy so its honesty properties can be
unit-tested without a database or an app context. When this lived inside
consumer/routes.py every one of its guard tests SKIPPED on any machine without
Flask installed — and a skipped test is indistinguishable from a passing one in
the summary line. Keep this module importable with nothing but the stdlib.

Callers pass row mappings straight from psycopg2/SQLAlchemy; only key access is
used, so dicts work equally well in tests.
"""

# ── A.U.R.O.R.A. map payload ────────────────────────────────────────────────
# CWFIS still emits Newfoundland as the legacy "NF"; the GeoJSON (and every
# other page on this site) says "NL". Canonicalise ONCE, here, at the payload
# boundary — 60 stations silently vanished from the map before this existed,
# and a map that is quietly missing a province is worse than no map.
_PROV_CANON = {"NF": "NL", "PQ": "QC", "NF ": "NL"}
_PROV_ORDER = ["BC", "AB", "SK", "MB", "ON", "QC", "NB", "NS", "PE", "NL",
               "YT", "NT", "NU"]
_PROV_NAMES = {
    "BC": "British Columbia", "AB": "Alberta", "SK": "Saskatchewan",
    "MB": "Manitoba", "ON": "Ontario", "QC": "Quebec", "NB": "New Brunswick",
    "NS": "Nova Scotia", "PE": "Prince Edward Island",
    "NL": "Newfoundland & Labrador", "YT": "Yukon",
    "NT": "Northwest Territories", "NU": "Nunavut",
}


def _canon_prov(code):
    """Normalise a province code, or None when the source did not supply one.

    19 fire-weather stations carry a BLANK prov but valid coordinates. They are
    deliberately kept (they can be PLOTTED even though they cannot be
    ATTRIBUTED) and reported separately rather than dropped or guessed.
    """
    if not code:
        return None
    c = str(code).strip().upper()
    return _PROV_CANON.get(c, c) or None


def _r(v, nd=1):
    """Round for the wire; None stays None (never 0.0 — a missing reading and a
    zero reading are different facts and the map colours them differently)."""
    return None if v is None else round(float(v), nd)


def _aurora_map_payload(station_rows, station_provinces, fire_provinces, obs_time):
    """Build the /weather map payload.

    Pure apart from its arguments so the honesty properties can be unit-tested
    without a database. The contract that matters:

      * a province absent from a layer is ABSENT, never zero — the template
        renders it grey and says "no data on this layer";
      * both layers travel together with their own coverage counts, because
        they cover disjoint halves of the country (see weather() docstring).
    """
    provinces = {}

    def _slot(code):
        return provinces.setdefault(code, {
            "code": code, "name": _PROV_NAMES.get(code, code),
            "stations": None, "hotspots": None,
            "avg_temp": None, "max_temp": None, "min_temp": None,
            "max_wind": None, "max_fwi": None, "avg_rh": None,
            "fwi_source": None,
        })

    for r in station_provinces:
        code = _canon_prov(r["prov"])
        if not code:
            continue
        p = _slot(code)
        p["stations"] = int(r["stations"] or 0)
        p["avg_temp"] = _r(r["avg_temp"])
        p["max_temp"] = _r(r["max_temp"])
        p["min_temp"] = _r(r["min_temp"])
        p["max_wind"] = _r(r["max_wind"])
        p["avg_rh"] = _r(r["avg_rh"], 0)
        if r["max_fwi"] is not None:
            p["max_fwi"] = _r(r["max_fwi"])
            p["fwi_source"] = "stations"

    for r in fire_provinces:
        code = _canon_prov(r["prov"])
        if not code:
            continue
        p = _slot(code)
        p["hotspots"] = int(r["hotspots"] or 0)
        # The hotspot layer carries its own FWI. Only use it where the station
        # layer has none, and SAY which one is being shown — they are different
        # instruments and silently mixing them makes the number unauditable.
        if p["max_fwi"] is None and r["max_fwi"] is not None:
            p["max_fwi"] = _r(r["max_fwi"])
            p["fwi_source"] = "hotspots"

    stations = []
    unplaced = 0
    for s in station_rows:
        code = _canon_prov(s["prov"])
        if code is None:
            unplaced += 1
        stations.append({
            "n": s["station_name"] or "Unnamed station",
            "p": code, "lat": _r(s["lat"], 3), "lon": _r(s["lon"], 3),
            "t": _r(s["temp_c"]), "h": _r(s["rel_humidity"], 0),
            "w": _r(s["wind_speed_kmh"], 0), "g": _r(s["wind_gust_kmh"], 0),
            "f": _r(s["fwi"]),
        })

    temps = [s["t"] for s in stations if s["t"] is not None]
    winds = [s["w"] for s in stations if s["w"] is not None]
    fwis = [s["f"] for s in stations if s["f"] is not None]

    return {
        "provinces": provinces,
        "prov_order": _PROV_ORDER,
        "stations": stations,
        "obs_time": obs_time.isoformat() if obs_time else None,
        "coverage": {
            # Stated plainly so the page can render its own limits instead of
            # implying national coverage it does not have.
            "station_provinces": sorted(
                k for k, v in provinces.items() if v["stations"]),
            "hotspot_provinces": sorted(
                k for k, v in provinces.items() if v["hotspots"]),
            "stations_total": len(stations),
            "stations_unplaced": unplaced,
        },
        "national": {
            "stations": len(stations),
            "warmest": max(temps) if temps else None,
            "coldest": min(temps) if temps else None,
            "avg_temp": _r(sum(temps) / len(temps)) if temps else None,
            "max_wind": max(winds) if winds else None,
            "max_fwi": max(fwis) if fwis else None,
            "hotspots": sum(v["hotspots"] or 0 for v in provinces.values()),
        },
    }


