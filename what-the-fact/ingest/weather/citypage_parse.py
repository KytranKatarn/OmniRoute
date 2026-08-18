"""Pure parser for MSC Datamart citypage_weather XML (project #393, task #5760).

STDLIB ONLY — no requests, no SQLAlchemy, no Flask. Its guard tests must run on
any machine. When the Phase 1 payload builder lived inside a module that imported
Flask, every one of its honesty tests SKIPPED while the suite still printed
"passed" (KB #290497). Keep this importable with nothing installed.

═══ THE THING THIS FILE EXISTS FOR ═══
This feed encodes "no value" FIVE different ways, and they are not
interchangeable. All five verified first-hand against live documents:

  1. <gust>00</gust>          the literal string "00" meaning NO GUST. Parses
                              cleanly as int 0 — no exception, no empty-check
                              triggered. `int(x or 0)` silently converts "no
                              gust" into "a measured 0 km/h". This is the only
                              one that defeats a truthiness guard.
  2. <windChill></windChill>  element PRESENT, text empty.
  3. <humidex></humidex>      same shape, different field.
  4. (element absent)         e.g. visibility is simply missing on most sites.
  5. <speed>calm</speed>      a MEASURED calm. float() raises on it. Writing 0
                              asserts a reading that was never taken.

(1)-(4) are ABSENCE and must become None. (5) is a MEASUREMENT and gets its own
boolean, because "no wind was measured" and "wind was measured at zero" are
different facts and the UI colours them differently.

═══ AND ONE MORE ═══
Station coordinates are hemisphere-SUFFIXED strings: lat="43.68N" lon="79.63W".
float() raises. Stripping the letter yields +79.63 — which is in China. W and S
must become negative.
"""
import datetime
import xml.etree.ElementTree as ET

# The daily forecast's "no gust" sentinel. Kept as a literal set rather than an
# int comparison: "00" is meaningful, a genuine 0 would be written "0".
_GUST_SENTINELS = {"00"}
_CALM = {"calm", "calme"}


def parse_latlon(raw):
    """'43.68N' -> 43.68 ; '79.63W' -> -79.63 ; None/'' -> None.

    W and S are NEGATIVE. Every Canadian longitude is W, so dropping the sign
    puts the entire country in Kazakhstan/China and a map would silently plot
    nothing where anyone is looking.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    hemi = s[-1].upper()
    if hemi in ("N", "S", "E", "W"):
        s = s[:-1]
    else:
        hemi = ""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return -v if hemi in ("S", "W") else v


def num(el):
    """Float from an element, or None for every flavour of absence.

    Handles cases 2, 3 and 4 above: a missing element, and a present-but-empty
    one, are both None. Never returns 0 for an absent reading.
    """
    if el is None:
        return None
    txt = (el.text or "").strip()
    if not txt:
        return None
    try:
        return float(txt)
    except (TypeError, ValueError):
        return None


def text(el):
    """Stripped text, or None when absent/empty. '' is never stored."""
    if el is None:
        return None
    t = (el.text or "").strip()
    return t or None


def parse_wind_speed(el):
    """-> (speed_kmh_or_None, is_calm).

    A literal 'calm' is a MEASUREMENT with no number, so it returns
    (None, True) — distinguishable from a missing reading, which is
    (None, False). Collapsing calm to 0.0 would make a measured stillness
    indistinguishable from an instrument that reported nothing.
    """
    if el is None:
        return None, False
    raw = (el.text or "").strip()
    if not raw:
        return None, False
    if raw.lower() in _CALM:
        return None, True
    try:
        return float(raw), False
    except (TypeError, ValueError):
        return None, False


def parse_gust(el):
    """Forecast gust, with the '00' sentinel mapped to None.

    Checked as a STRING before any numeric conversion — that is the whole point.
    By the time '00' has been through float() it is 0.0 and indistinguishable
    from a real (if implausible) measured zero.
    """
    if el is None:
        return None
    raw = (el.text or "").strip()
    if not raw or raw in _GUST_SENTINELS:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_msc_timestamp(ts):
    """'20260818192549' -> aware UTC datetime. None on anything unparseable."""
    if not ts:
        return None
    s = str(ts).strip()
    if len(s) < 14 or not s.isdigit():
        return None
    try:
        return datetime.datetime(
            int(s[0:4]), int(s[4:6]), int(s[6:8]),
            int(s[8:10]), int(s[10:12]), int(s[12:14]),
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        return None


def _datetimes_by_zone(parent, name):
    """{'UTC': el, 'EDT': el, ...} for dateTime[@name=name]. The element appears
    TWICE — once UTC, once local — and only the UTC one is safe to key on."""
    out = {}
    if parent is None:
        return out
    for d in parent.findall("dateTime"):
        if d.get("name") == name:
            out[d.get("zone")] = d
    return out


def parse_current_conditions(root, source_file):
    """-> dict, or None when the document carries no keyable observation.

    Returns None (not an empty dict, not zeros) for a self-closed
    <currentConditions/>: with no observation timestamp there is nothing to key
    on. The CALLER records that as 'no_observations' on the site registry, so the
    page can say "MSC published no observations for this site" rather than "we
    could not reach the source" — two different facts.
    """
    cc = root.find("currentConditions")
    if cc is None or len(list(cc)) == 0:
        return None

    dts = _datetimes_by_zone(cc, "observation")
    utc_el = dts.get("UTC")
    observed = parse_msc_timestamp(utc_el.findtext("timeStamp") if utc_el is not None else None)
    if observed is None:
        return None  # unkeyable

    local_el = next((e for z, e in dts.items() if z != "UTC"), None)
    station = cc.find("station")
    wind = cc.find("wind")
    pressure = cc.find("pressure")

    speed, is_calm = parse_wind_speed(wind.find("speed") if wind is not None else None)

    offset = None
    if local_el is not None:
        try:
            offset = int(local_el.get("UTCOffset"))
        except (TypeError, ValueError):
            offset = None

    return {
        "observed_utc": observed,
        "observed_local_ts": (local_el.findtext("timeStamp") if local_el is not None else None),
        "local_zone": (local_el.get("zone") if local_el is not None else None),
        "local_utc_offset": offset,
        "station_code": (station.get("code") if station is not None else None),
        "station_name": text(station),
        "station_lat": parse_latlon(station.get("lat") if station is not None else None),
        "station_lon": parse_latlon(station.get("lon") if station is not None else None),
        "condition_text": text(cc.find("condition")),
        "icon_code": text(cc.find("iconCode")),
        "temp_c": num(cc.find("temperature")),
        "dewpoint_c": num(cc.find("dewpoint")),
        "rel_humidity_pct": num(cc.find("relativeHumidity")),
        "humidex": num(cc.find("humidex")),
        "wind_chill": num(cc.find("windChill")),
        "pressure_kpa": num(pressure),
        # `change` and `tendency` are ATTRIBUTES of <pressure>, and `change` can
        # be the empty string — hence the same None discipline as element text.
        "pressure_change_kpa": _attr_float(pressure, "change"),
        "pressure_tendency": _attr_text(pressure, "tendency"),
        "visibility_km": num(cc.find("visibility")),
        "wind_speed_kmh": speed,
        "wind_is_calm": is_calm,
        "wind_gust_kmh": num(wind.find("gust")) if wind is not None else None,
        "wind_dir": text(wind.find("direction")) if wind is not None else None,
        "wind_bearing_deg": num(wind.find("bearing")) if wind is not None else None,
        "source_file": source_file,
    }


def _attr_float(el, key):
    if el is None:
        return None
    raw = (el.get(key) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _attr_text(el, key):
    if el is None:
        return None
    return (el.get(key) or "").strip() or None


def parse_forecasts(root, source_file):
    """-> list of period dicts (possibly empty). Never returns None.

    Keyed on forecastIssue UTC, which is a real issue time, so history accretes
    instead of overwriting a rolling slot.
    """
    fg = root.find("forecastGroup")
    if fg is None:
        return []
    utc_el = _datetimes_by_zone(fg, "forecastIssue").get("UTC")
    issued = parse_msc_timestamp(utc_el.findtext("timeStamp") if utc_el is not None else None)
    if issued is None:
        return []

    out = []
    for idx, fc in enumerate(fg.findall("forecast")):
        period = fc.find("period")
        temps = fc.find("temperatures")
        winds = fc.find("winds")
        uv = fc.find("uv")

        high = low = None
        if temps is not None:
            for t in temps.findall("temperature"):
                # maxOccurs=2 — a period can carry BOTH a high and a low, which
                # is why these are separate columns and not (value, class).
                if t.get("class") == "high":
                    high = num(t)
                elif t.get("class") == "low":
                    low = num(t)

        gust = None
        if winds is not None:
            for g in winds.iter("gust"):
                v = parse_gust(g)      # '00' -> None, deliberately
                if v is not None:
                    gust = max(gust, v) if gust is not None else v

        out.append({
            "issued_utc": issued,
            "period_index": idx,
            "period_label": (period.get("textForecastName") if period is not None else None),
            "period_weekday": text(period),
            "temp_high_c": high,
            "temp_low_c": low,
            "text_summary": text(fc.find("textSummary")),
            "abbrev_summary": text(fc.find("abbreviatedForecast/textSummary")),
            # abbreviatedForecast/pop — verified location. The feed leaves it
            # EMPTY rather than writing 0 when there is no chance of
            # precipitation, so absence must NOT render as "0%".
            "pop_pct": num(fc.find("abbreviatedForecast/pop")),
            "wind_summary": text(winds.find("textSummary")) if winds is not None else None,
            "wind_gust_kmh": gust,
            "uv_index": num(uv.find("index")) if uv is not None else None,
            "uv_category": text(uv.find("category")) if uv is not None else None,
            "source_file": source_file,
        })
    return out



def parse_document(xml_bytes, source_file):
    """-> (site_meta, current_or_None, [forecasts]).

    Raises nothing for a well-formed document with missing sections; a caller
    that gets an exception here has a genuinely broken file and should record
    'parse_error' rather than silently skipping.
    """
    root = ET.fromstring(xml_bytes)
    loc = root.find("location")
    name_el = loc.find("name") if loc is not None else None
    # ⚠️ The DOCUMENT's <province> is the FULL NAME ("Ontario"), while
    # siteList.xml — and therefore aurora_city_site.source_prov — carries the
    # two-letter code ("ON"). They are different vocabularies for the same
    # field. Exposed under a DIFFERENT key so nothing can join or overwrite the
    # registry code with it by accident.
    meta = {
        "name_en": text(name_el),
        "province_long": (loc.findtext("province") if loc is not None else None),
        "lat": parse_latlon(name_el.get("lat") if name_el is not None else None),
        "lon": parse_latlon(name_el.get("lon") if name_el is not None else None),
    }
    return meta, parse_current_conditions(root, source_file), parse_forecasts(root, source_file)
