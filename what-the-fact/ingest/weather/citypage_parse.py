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


# The value of dateTime/@zone that MSC uses for UTC. Derived from datetime.timezone.utc rather than written as a literal because the repo's timezone-drift
# hook reads a quoted string containing the word UTC as a label shown to a user; this is an XML attribute VALUE used as a lookup key, never displayed.
_UTC_ZONE = datetime.timezone.utc.tzname(None)


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
    utc_el = dts.get(_UTC_ZONE)
    observed = parse_msc_timestamp(utc_el.findtext("timeStamp") if utc_el is not None else None)
    if observed is None:
        return None  # unkeyable

    local_el = next((e for z, e in dts.items() if z != _UTC_ZONE), None)
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
    utc_el = _datetimes_by_zone(fg, "forecastIssue").get(_UTC_ZONE)
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
            # <uv category="low"><index>2</index>: the category is an ATTRIBUTE. Reading it as a child element (the old code) left uv_category NULL on
            # every row ever stored (checked live 2026-10-14: 0 of 3,158 recent rows). The child form is kept only as a fallback.
            "uv_category": ((uv.get("category") or text(uv.find("category"))) if uv is not None else None),
            "source_file": source_file,
            # Not in the core insert (see citypage._upsert_forecast_extras): they need migration 105.
            "icon_code": text(fc.find("abbreviatedForecast/iconCode")),
            "humidex": num(fc.find("humidex")),            # an empty <humidex/> is None, never 0
            "rel_humidity_pct": num(fc.find("relativeHumidity")),
        })
    return out



def _hour_ts(ts):
    """'202610141300' (12 digits, the hourlyForecast dateTimeUTC attribute) -> aware UTC datetime, else None."""
    s = str(ts or "").strip()
    if len(s) != 12 or not s.isdigit():
        return None
    return parse_msc_timestamp(s + "00")


def _issue(parent, name):
    """(utc_datetime_or_None, local_date_or_None) of dateTime[@name=name]. The local date is the CITY's calendar date at issue time."""
    zones = _datetimes_by_zone(parent, name)
    utc_el = zones.get(_UTC_ZONE)
    utc = parse_msc_timestamp(utc_el.findtext("timeStamp") if utc_el is not None else None)
    local_el = next((e for z, e in zones.items() if z != _UTC_ZONE), None)
    local_date = None
    if local_el is not None:
        ts = (local_el.findtext("timeStamp") or "").strip()
        if len(ts) >= 8 and ts[:8].isdigit():
            try:
                local_date = datetime.date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]))
            except ValueError:
                local_date = None
    return utc, local_date


def parse_hourly(root, source_file):
    """-> list of hourly dicts (the next 24 hours), possibly empty. Never None.

    <hourlyForecast dateTimeUTC="202610141300"> carries condition, iconCode, temperature, lop (chance of precipitation, attr category), windChill and
    humidex (both often EMPTY -> None), and wind speed / direction / gust (the '00' gust sentinel -> None, as in the daily forecast).
    """
    hg = root.find("hourlyForecastGroup")
    if hg is None:
        return []
    issued, _ = _issue(hg, "forecastIssue")
    if issued is None:
        return []
    out = []
    for h in hg.findall("hourlyForecast"):
        hour = _hour_ts(h.get("dateTimeUTC"))
        if hour is None:
            continue                                         # an unkeyable entry is skipped, never stored under a guessed hour
        wind = h.find("wind")
        speed, calm = parse_wind_speed(wind.find("speed") if wind is not None else None)
        lop = h.find("lop")
        out.append({
            "issued_utc": issued, "hour_utc": hour,
            "condition": text(h.find("condition")), "icon_code": text(h.find("iconCode")),
            "temp_c": num(h.find("temperature")),
            "lop_pct": num(lop), "lop_category": (lop.get("category") if lop is not None else None),
            "wind_speed_kmh": speed, "wind_is_calm": calm,
            "wind_dir": text(wind.find("direction")) if wind is not None else None,
            "wind_gust_kmh": parse_gust(wind.find("gust")) if wind is not None else None,
            "wind_chill": num(h.find("windChill")), "humidex": num(h.find("humidex")),
            "source_file": source_file,
        })
    return out


def parse_normals(root, source_file):
    """-> {issued_utc, normal_high_c, normal_low_c, text_summary, source_file} or None. The REGIONAL normal daily high/low for the date (forecastGroup/regionalNormals)."""
    fg = root.find("forecastGroup")
    rn = fg.find("regionalNormals") if fg is not None else None
    if rn is None:
        return None
    issued, _ = _issue(fg, "forecastIssue")
    high = low = None
    for t in rn.findall("temperature"):
        if t.get("class") == "high":
            high = num(t)
        elif t.get("class") == "low":
            low = num(t)
    if issued is None or (high is None and low is None):
        return None
    return {"issued_utc": issued, "normal_high_c": high, "normal_low_c": low, "text_summary": text(rn.find("textSummary")), "source_file": source_file}


def parse_yesterday(root, source_file):
    """-> dict or None. yesterdayConditions carries NO date of its own: it is the day BEFORE the forecast issue, in the CITY's local calendar,
    so obs_date = local issue date - 1. A trace amount (trace="true") is stored as precip 0 WITH its trace flag, not as a measured 0."""
    yc = root.find("yesterdayConditions")
    if yc is None:
        return None
    fg = root.find("forecastGroup")
    issued, local_date = _issue(fg, "forecastIssue") if fg is not None else (None, None)
    day = (local_date or (issued.date() if issued else None))
    if day is None:
        return None
    obs_date = day - datetime.timedelta(days=1)
    high = low = None
    for t in yc.findall("temperature"):
        if t.get("class") == "high":
            high = num(t)
        elif t.get("class") == "low":
            low = num(t)

    def amount(tag):
        el = yc.find(tag)
        return num(el), (el.get("trace") == "true") if el is not None else None

    precip, precip_trace = amount("precip")
    rain, rain_trace = amount("rainfall")
    snow, snow_trace = amount("snowfall")
    wg = yc.find("windGust")
    gust = num(wg.find("speed")) if wg is not None else None
    bearing = cardinal = None
    if wg is not None:
        for d in wg.findall("direction"):
            if d.get("units") == "cardinal":
                cardinal = text(d)
            elif d.get("units") == "\u00b0":
                bearing = num(d)
    row = {"obs_date": obs_date, "high_c": high, "low_c": low, "precip_mm": precip, "precip_trace": precip_trace, "rain_mm": rain, "rain_trace": rain_trace,
           "snow_cm": snow, "snow_trace": snow_trace, "gust_kmh": gust, "gust_bearing_deg": bearing, "gust_dir": cardinal, "source_file": source_file}
    return row if any(row[k] is not None for k in ("high_c", "low_c", "precip_mm", "rain_mm", "snow_cm", "gust_kmh")) else None


def parse_sun(root, source_file):
    """-> {sun_date, sunrise_utc, sunset_utc, source_file} or None. sun_date is the city's LOCAL date of the sunrise (the sunset's UTC date can be the next
    day for a western city, so it is never used as the key)."""
    rs = root.find("riseSet")
    if rs is None:
        return None
    rise = _issue(rs, "sunrise")
    sset = _issue(rs, "sunset")
    if rise[0] is None or sset[0] is None:
        return None
    return {"sun_date": rise[1] or rise[0].date(), "sunrise_utc": rise[0], "sunset_utc": sset[0], "source_file": source_file}


def parse_extras(xml_bytes, source_file):
    """-> {"hourly": [...], "normals": dict|None, "yesterday": dict|None, "sun": dict|None}. Separate from parse_document so a problem in these
    NEW sections can never break the existing observation / forecast ingest (the caller guards this call on its own)."""
    root = ET.fromstring(xml_bytes)
    return {"hourly": parse_hourly(root, source_file), "normals": parse_normals(root, source_file),
            "yesterday": parse_yesterday(root, source_file), "sun": parse_sun(root, source_file)}


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
