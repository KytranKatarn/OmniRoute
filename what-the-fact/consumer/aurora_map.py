"""Pure payload builder for the A.U.R.O.R.A. /weather map (project #393).

Deliberately free of Flask and SQLAlchemy so its honesty properties can be
unit-tested without a database or an app context. When this lived inside
consumer/routes.py every one of its guard tests SKIPPED on any machine without
Flask installed — and a skipped test is indistinguishable from a passing one in
the summary line. Keep this module importable with nothing but the stdlib.

Callers pass row mappings straight from psycopg2/SQLAlchemy; only key access is
used, so dicts work equally well in tests.
"""

import re

# ── A.U.R.O.R.A. map payload ────────────────────────────────────────────────
# CWFIS still emits Newfoundland as the legacy "NF"; the GeoJSON (and every
# other page on this site) says "NL". Canonicalise ONCE, here, at the payload
# boundary — 60 stations silently vanished from the map before this existed,
# and a map that is quietly missing a province is worse than no map.
# One canonicalisation boundary for province codes — a second one is how a
# province goes missing.
#
# ⚠️ "SA" -> "SK" added 2026-08-30. CWFIS fire-weather emits SA for Saskatchewan
# (measured live: 1,542 rows across 129 stations) while Datamart, the hotspot
# feed and the GeoJSON all use SK. Unmapped, _canon_prov returned "SA"
# unchanged, which is in neither _PROV_ORDER nor _PROV_NAMES — so those stations
# were bucketed into a phantom province rendered as the bare string "SA", and
# the choropleth (keyed on SK) painted SASKATCHEWAN AS HAVING NO FIRE-WEATHER
# COVERAGE. Exactly the NF/NL defect this dict already existed to fix, one
# province over.
#
# Adding a code here is the ONLY correct place. If a source turns up with yet
# another spelling, extend this map — never special-case it at a call site.
_PROV_CANON = {"NF": "NL", "NF ": "NL", "PQ": "QC", "SA": "SK"}
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


# Provincial / territorial capitals, keyed by CANONICAL province code so this
# cannot drift from _canon_prov (the SA/SK bug is what that costs).
# All 13 are present in the 25-site ECCC set — verified 2026-08-30 — so the city
# grid partitions into 13 capitals + 12 other major cities with no remainder.
_CAPITALS = {
    "AB": "Edmonton", "BC": "Victoria", "MB": "Winnipeg", "NB": "Fredericton",
    "NL": "St. John's", "NS": "Halifax", "NT": "Yellowknife", "NU": "Iqaluit",
    "ON": "Toronto", "PE": "Charlottetown", "QC": "Québec", "SK": "Regina",
    "YT": "Whitehorse",
}


def _is_capital(name, prov):
    """Is this site the capital of its province/territory?

    Matched on the DISPLAY name, which is why the coalesce at the call site
    matters: ECCC ships "Ottawa (Kanata - Orléans)" and Ottawa is NOT Ontario's
    capital — Toronto is. A substring match either way would wrongly promote it.

    Accent-insensitive so "Québec"/"Quebec" and "Montréal"/"Montreal" behave the
    same regardless of which spelling a feed sends.
    """
    if not name or not prov:
        return False
    import unicodedata  # noqa: PLC0415

    def _fold(s):
        s = unicodedata.normalize("NFKD", str(s))
        return "".join(c for c in s if not unicodedata.combining(c)).strip().casefold()

    return _fold(name) == _fold(_CAPITALS.get(prov, ""))


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




# ── city cards (Phase 2) ────────────────────────────────────────────────────

def _aurora_city_payload(city_rows, forecast_rows):
    """Build the /weather city-card payload.

    Same discipline as the map payload above: a missing reading stays None and
    never becomes 0, and each card carries its OWN observation age so a stale
    city can say so individually rather than the page making one blanket claim.

    `wind_is_calm` is carried through as its own flag. "Calm" is a MEASUREMENT
    with no number; a missing wind reading is an ABSENCE. Rendering both as
    "0 km/h" — or both as "—" — would merge two different facts.
    """
    by_site = {}
    for f in forecast_rows:
        by_site.setdefault(f["site_code"], []).append({
            "label": f["period_label"],
            "high": _r(f["temp_high_c"]),
            "low": _r(f["temp_low_c"]),
            "pop": _r(f["pop_pct"], 0),
            "summary": f["abbrev_summary"] or f["text_summary"],
        })

    cities = []
    for r in city_rows:
        code = r["site_code"]
        _prov = _canon_prov(r["source_prov"])
        # ⚠️ display_name is the OVERRIDE, name_en the fallback — and it is
        # populated for exactly 1 of 25 sites (measured 2026-08-30). It exists to
        # shorten ECCC's label ("Ottawa (Kanata - Orléans)" -> "Ottawa"), so
        # reading display_name ALONE would blank 24 cards. The coalesce is
        # load-bearing, not defensive.
        _name = r["display_name"] or r["name_en"]
        cities.append({
            "code": code,
            "name": _name,
            "prov": _prov,
            # Capital of its province/territory. All 13 are in the 25-site set
            # (verified 2026-08-30), so this partitions the grid cleanly into
            # 13 capitals + 12 other major cities with nothing left over.
            "is_capital": _is_capital(_name, _prov),
            "lat": _r(r["lat"], 3),
            "lon": _r(r["lon"], 3),
            "status": r["last_obs_status"],
            "observed": r["observed_utc"].isoformat() if r.get("observed_utc") else None,
            "age_min": (int(r["age_min"]) if r.get("age_min") is not None else None),
            "temp": _r(r["temp_c"]),
            "condition": r["condition_text"],
            "humidity": _r(r["rel_humidity_pct"], 0),
            "wind": _r(r["wind_speed_kmh"], 0),
            "calm": bool(r["wind_is_calm"]),
            "gust": _r(r["wind_gust_kmh"], 0),
            "dir": r["wind_dir"],
            "humidex": _r(r["humidex"]),
            "pressure": _r(r["pressure_kpa"]),
            "forecast": by_site.get(code, [])[:4],
        })

    temps = [c["temp"] for c in cities if c["temp"] is not None]
    return {
        "cities": cities,
        "count": len(cities),
        "reporting": sum(1 for c in cities if c["temp"] is not None),
        "warmest": max(temps) if temps else None,
        "coldest": min(temps) if temps else None,
        "provinces": sorted({c["prov"] for c in cities if c["prov"]}),
    }


# ── Homepage weather strip + wildfire/alerts band (PORT-STATUS row 4) ─────────
# Pure so the honesty rules below are unit-tested without a database. The design's
# numbers are sample data; every figure here comes from a query, and a figure with
# no source renders as an em dash — never as 0 (same rule as measurement()).
import re as _re
import unicodedata as _ud

# First match wins, so ORDER IS LOAD-BEARING: "Partly cloudy" must reach cloudsun
# before the bare "cloud" rule, and "Mainly clear" before "clear". Snow has no
# glyph in the design set, so it falls to the generic cloud — the condition WORD
# beside the icon carries the meaning (an icon is decoration, never the label).
_GLYPH_RULES = (
    (("smoke", "haze"), "smoke"),
    (("fog", "mist"), "fog"),
    (("thunder", "rain", "shower", "drizzle"), "rain"),
    (("wind",), "wind"),
    (("partly", "mainly clear", "mainly sunny", "mix of sun"), "cloudsun"),
    (("clear", "sunny"), "sun"),
    (("cloud", "overcast"), "cloud"),
)


def wx_glyph(condition):
    """Icon-registry key for an ECCC condition string. Unknown/empty -> 'cloud'."""
    c = (condition or "").lower()
    for needles, key in _GLYPH_RULES:
        if any(n in c for n in needles):
            return key
    return "cloud"


def _fold(s):
    """Lower-case and strip accents so 'Montréal' matches 'Montreal'."""
    return _ud.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


_SEV_RANK = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}


def match_city_alerts(cities, alerts):
    """{city code: {'event', 'severity'}} for cities named in an active alert's area.

    Matches the city NAME as a whole word inside the alert's `area_desc` only. It is
    deliberately NOT matched on `coverage_name` (province-wide): flagging Halifax
    for an alert on Victoria County would assert something the feed did not say.
    The cost is honest under-flagging — an alert whose area names a county not a
    city will not mark that city; the full list stays on /weather.
    """
    out = {}
    for c in cities:
        name = _fold(c.get("name"))
        if not name:
            continue
        pat = _re.compile(r"(?<![a-z])" + _re.escape(name) + r"(?![a-z])")
        best = None
        for a in alerts:
            if not pat.search(_fold(a.get("area_desc"))):
                continue
            rank = _SEV_RANK.get(a.get("severity"), 4)
            if best is None or rank < best[0]:
                best = (rank, a)
        if best:
            out[c["code"]] = {"event": best[1].get("event"), "severity": best[1].get("severity")}
    return out


def is_warning(event):
    """A 'warning-level' alert = the event name says warning (not watch/advisory/statement)."""
    return "warning" in (event or "").lower()


_PROV_TERR_TOTAL = 13


def build_fire_alert_tiles(hotspot_rows, obs_date, alerts, evac_naad, evac_bc_orders,
                           reporting, total, silent_names, spread_rows=None):
    """Five tiles for the homepage 'Wildfire and alerts' band, six with ``spread_rows``.

    The design's sixth tile reads 'Spread pressure 84 · Extreme, next 48h' — a FORECAST.
    Nothing here forecasts, so the tile is built from ``spread_pressure()`` (the /weather
    index: current conditions, real rows only) and says so in its note instead of
    claiming a horizon. ``spread_rows=None`` (the default) keeps the original five tiles
    byte-for-byte; an empty list means "could not be measured" and renders an em dash,
    never 0.
    """
    def tile(key, label, value, note, tone):
        return {"key": key, "label": label, "value": value, "note": note, "tone": tone,
                "href": "/weather"}

    rows = [r for r in (hotspot_rows or []) if r.get("hotspots") is not None]
    if obs_date is None or not rows:
        tiles = [tile("hotspots", "Hotspots, 72h", "—", "no recent detection data", "fire"),
                 tile("worst", "Worst province", "—", "no recent detection data", "severe")]
    else:
        total_h = sum(int(r["hotspots"]) for r in rows)
        with_fire = sum(1 for r in rows if int(r["hotspots"]) > 0)
        tiles = [tile("hotspots", "Hotspots, 72h", f"{total_h:,}",
                      f"Across {with_fire} of {_PROV_TERR_TOTAL} provinces and territories", "fire")]
        worst = max(rows, key=lambda r: int(r["hotspots"]))
        fwi = worst.get("max_fwi")
        note = f"{int(worst['hotspots']):,} detections" + (f" · FWI {float(fwi):.1f}" if fwi else "")
        tiles.append(tile("worst", "Worst province", worst["prov"], note, "severe"))

    if alerts is None:
        tiles.append(tile("alerts", "Alerts in effect", "—", "alert feed unavailable", "warn"))
    else:
        w = sum(1 for a in alerts if is_warning(a.get("event")))
        tiles.append(tile("alerts", "Alerts in effect", str(len(alerts)),
                          f"{w} of them warnings" if w else "none are warnings", "warn"))

    if evac_naad is None or evac_bc_orders is None:
        tiles.append(tile("evac", "Under evacuation", "—", "evacuation feeds unavailable", "evac"))
    else:
        # Components stay visible: the national feed and BC's order list can describe
        # the same event, and a bare sum would hide that. No population figure — only
        # BC publishes one, and it would read as national.
        tiles.append(tile("evac", "Under evacuation", str(evac_naad + evac_bc_orders),
                          f"{evac_naad} Alert Ready · {evac_bc_orders} BC orders", "evac"))

    if not total:
        tiles.append(tile("cities", "Cities reporting", "—", "no city observations", "ok"))
    else:
        note = (", ".join(silent_names[:2]) + (" silent" if len(silent_names) <= 2 else f" +{len(silent_names) - 2} silent")
                if silent_names else "all reporting")
        tiles.append(tile("cities", "Cities reporting", f"{reporting} / {total}", note,
                          "ok" if reporting == total else "warn"))

    if spread_rows is not None:
        scored = [r for r in spread_rows if r.get("score") is not None]
        if not scored:
            tiles.append(tile("spread", "Spread pressure", "—",
                              "not enough measured inputs", "fire"))
        else:
            top = max(scored, key=lambda r: r["score"])  # rows arrive sorted; don't rely on it
            tone = {"extreme": "severe", "high": "severe", "moderate": "warn"}.get(top["band"], "ok")
            tiles.append(tile("spread", "Spread pressure", str(top["score"]),
                              f"{top['name']} · {top['band'].title()} · current conditions", tone))
    return tiles


# ── Alert text (weather page alert strip) ─────────────────────────────────────
# Environment Canada CAP descriptions sometimes carry MARKDOWN headings inline
# ("...monitor alerts. ### This warning is issued when ..."), which rendered raw as
# "###" on the live page. The text after the first heading marker is boilerplate
# explanation, not the alert itself, so the summary stops there.
_MD_HEADING = re.compile(r"\s*#{2,}\s")


def clean_alert_text(desc, limit: int = 220):
    """PURE. Raw CAP description in, a short plain-text summary (or None) out.

    Cuts at the first markdown heading marker, strips leftover ``#``/``*`` runs,
    collapses whitespace, and truncates on a word boundary with an ellipsis.
    Never invents text: an empty or all-markup input returns None so the caller can
    omit the line rather than render a blank one.
    """
    if not desc or not isinstance(desc, str):
        return None
    head = ""
    for chunk in _MD_HEADING.split(desc):
        head = re.sub(r"\s+", " ", re.sub(r"[#*_`]+", " ", chunk)).strip()
        if head:
            break  # first real chunk; a leading bare "###" must not blank the summary
    if not head:
        return None
    if len(head) <= limit:
        return head
    cut = head[:limit].rsplit(" ", 1)[0].rstrip(",;:- ")
    return cut + "\u2026"


def alert_counts(total: int, severities) -> dict:
    """PURE. Header numbers for the strip, from REAL rows only.

    ``total`` is the full count of active alerts (the list shown is capped);
    ``severe`` counts Severe/Extreme by the alert's own severity field. No province
    count is derived — CAP office codes span provinces (see routes.weather()).
    """
    severe = sum(1 for s in (severities or []) if str(s or "").lower() in ("severe", "extreme"))
    return {"total": int(total or 0), "severe": severe}


# ── Spread pressure — a CURRENT-CONDITIONS index, not a forecast ────────────────
# Editorial constants, published verbatim on the page (see SPREAD_FORMULA). Each
# input is scaled 0..1 against a fixed ceiling and the index is the mean of the
# inputs that were actually measured. Nothing is imputed: an unmeasured input is
# left out, and a province with fewer than SPREAD_MIN_INPUTS is "no data".
# The two fire layers cover disjoint halves of the country (stations east,
# hotspots west/north), so requiring every input would blank most provinces.
SPREAD_CEILINGS = {"fwi": 30.0, "wind": 50.0, "temp": (10.0, 35.0), "hotspots": 300.0}
SPREAD_MIN_INPUTS = 2
SPREAD_BANDS = ((75, "extreme"), (50, "high"), (25, "moderate"), (0, "low"))
SPREAD_FORMULA = (
    "Mean of the inputs measured for the province, each scaled 0–100% against a fixed "
    "ceiling: fire weather index (FWI) 30, peak wind 50 km/h, peak temperature 10–35°C, "
    "hotspots over 3 days 300. Needs at least 2 inputs. A reading of current conditions, "
    "not a forecast."
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def spread_pressure(fire_provinces, station_provinces) -> list[dict]:
    """PURE. Per-province spread-pressure index from REAL rows only.

    ``fire_provinces`` rows: prov, hotspots, max_fwi.  ``station_provinces`` rows:
    prov, max_wind, max_temp, max_fwi.  Province codes go through ``_canon_prov``
    (the one canonicalisation boundary). Returns rows sorted most-pressure first;
    under-measured provinces are returned with ``score=None`` so the page can say
    "no data" instead of omitting them.
    """
    by: dict[str, dict] = {}
    for r in fire_provinces or []:
        p = by.setdefault(_canon_prov(r.get("prov")), {})
        if r.get("hotspots") is not None:
            p["hotspots"] = float(r["hotspots"])
        if r.get("max_fwi") is not None:
            p["fwi"] = max(p.get("fwi", 0.0), float(r["max_fwi"]))
    for r in station_provinces or []:
        p = by.setdefault(_canon_prov(r.get("prov")), {})
        if r.get("max_wind") is not None:
            p["wind"] = float(r["max_wind"])
        if r.get("max_temp") is not None:
            p["temp"] = float(r["max_temp"])
        if r.get("max_fwi") is not None:
            p["fwi"] = max(p.get("fwi", 0.0), float(r["max_fwi"]))

    lo, hi = SPREAD_CEILINGS["temp"]
    rows = []
    for code, raw in by.items():
        if not code:
            continue
        norm = {}
        if "fwi" in raw:
            norm["fwi"] = _clamp01(raw["fwi"] / SPREAD_CEILINGS["fwi"])
        if "wind" in raw:
            norm["wind"] = _clamp01(raw["wind"] / SPREAD_CEILINGS["wind"])
        if "temp" in raw:
            norm["temp"] = _clamp01((raw["temp"] - lo) / (hi - lo))
        if "hotspots" in raw:
            norm["hotspots"] = _clamp01(raw["hotspots"] / SPREAD_CEILINGS["hotspots"])
        score = band = None
        if len(norm) >= SPREAD_MIN_INPUTS:
            score = round(100 * sum(norm.values()) / len(norm))
            band = next(name for floor, name in SPREAD_BANDS if score >= floor)
        rows.append({
            "code": code, "name": _PROV_NAMES.get(code, code), "score": score, "band": band,
            "inputs": {k: {"raw": raw[k], "pct": round(100 * v)} for k, v in norm.items()},
            "n_inputs": len(norm),
        })
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["name"]))
    return rows
