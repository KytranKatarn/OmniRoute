"""The /weather/city/<name> window: the next 24 hours, sunrise/sunset, yesterday and the regional normal (task 7235).

Pure and stdlib-only (zoneinfo), like aurora_tz: the route hands it rows, it returns plain dicts the template renders. Every figure comes from the
S2 tables (ingest/weather/citypage.py); nothing is computed that the feed did not state, except two differences shown to the reader as such
(today's high against the regional normal, and the length of daylight). A missing value stays None and renders as an absence, never as 0.
"""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from . import aurora_tz

_UTC = timezone.utc
HOURS_SHOWN = 24


def _zone(prov):
    return ZoneInfo(aurora_tz.PROV_TZ.get((prov or "").strip().upper(), aurora_tz.DEFAULT_TZ))


def _num(v, digits=0):
    if v is None:
        return None
    r = round(float(v), digits)
    return int(r) if digits == 0 else r


def _clock(dt, zone):
    """'3 PM' / '12 AM' in the city's own zone: no leading zero, no UTC, no zone suffix on a row that is all one zone."""
    local = dt.astimezone(zone)
    hour12 = local.hour % 12 or 12
    return f"{hour12} {'AM' if local.hour < 12 else 'PM'}"


def _clock_minutes(dt, zone):
    local = dt.astimezone(zone)
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def build_hourly(rows, prov, now, wx_symbol):
    """Up to 24 upcoming hours, in the city's local time. `now` is an aware datetime (injected so tests do not depend on the clock)."""
    zone = _zone(prov)
    floor = now.astimezone(_UTC) - timedelta(minutes=59)
    out = []
    for r in sorted(rows, key=lambda x: x["hour_utc"]):
        if r["hour_utc"] < floor:
            continue
        calm = bool(r.get("wind_is_calm"))
        out.append({
            "label": "Now" if not out else _clock(r["hour_utc"], zone),
            "day_break": (not out) or r["hour_utc"].astimezone(zone).hour == 0,
            "weekday": r["hour_utc"].astimezone(zone).strftime("%a"),
            "temp": _num(r.get("temp_c")),
            "condition": r.get("condition"),
            "glyph": wx_symbol(r.get("icon_code"), r.get("condition")),
            "lop": _num(r.get("lop_pct")),
            "wind": None if calm else _num(r.get("wind_speed_kmh")),
            "calm": calm,
            "wind_dir": r.get("wind_dir"),
            "gust": _num(r.get("wind_gust_kmh")),
        })
        if len(out) == HOURS_SHOWN:
            break
    return out


def temp_line(hours, width=720, height=120, pad=14):
    """SVG point string for the temperature line over the hours that HAVE a temperature, or None when fewer than two do.

    Gaps are not bridged: a run is only drawn between hours that each carry a reading, so a missing hour never becomes an interpolated figure.
    Returns {"points": [...], "min": int, "max": int}; the template draws constant geometry from these numbers only.
    """
    temps = [h["temp"] for h in hours if h["temp"] is not None]
    if len(temps) < 2 or len(hours) < 2:
        return None
    lo, hi = min(temps), max(temps)
    span = (hi - lo) or 1
    step = (width - 2 * pad) / (len(hours) - 1)
    pts = []
    for i, h in enumerate(hours):
        if h["temp"] is None:
            continue
        x = pad + i * step
        y = pad + (hi - h["temp"]) / span * (height - 2 * pad)
        pts.append({"x": round(x, 1), "y": round(y, 1), "temp": h["temp"], "i": i})
    return {"points": pts, "min": lo, "max": hi, "width": width, "height": height}


def build_sun(rows, prov, now):
    """Sunrise, sunset and the length of daylight for the city's local TODAY, or None when the feed has no row for it."""
    zone = _zone(prov)
    today = now.astimezone(zone).date()
    row = next((r for r in rows if r["sun_date"] == today), None)
    if row is None:
        return None
    rise, sset = row["sunrise_utc"], row["sunset_utc"]
    minutes = int((sset - rise).total_seconds() // 60)
    return {
        "sunrise": _clock_minutes(rise, zone),
        "sunset": _clock_minutes(sset, zone),
        "daylight": f"{minutes // 60} h {minutes % 60:02d} min" if minutes > 0 else None,
    }


def build_yesterday(row):
    """Yesterday's observed high/low/precipitation/gust. A 'trace' is a measurement with no number, distinct from a dry day and from no reading."""
    if row is None:
        return None

    def amount(value, trace, unit):
        if value is not None:
            return f"{_num(value, 1)} {unit}"
        return "trace" if trace else None

    gust = _num(row.get("gust_kmh"))
    return {
        "date": row["obs_date"],
        "high": _num(row.get("high_c")),
        "low": _num(row.get("low_c")),
        "rain": amount(row.get("rain_mm"), row.get("rain_trace"), "mm"),
        "snow": amount(row.get("snow_cm"), row.get("snow_trace"), "cm"),
        "gust": gust,
        "gust_dir": row.get("gust_dir"),
    }


def build_normals(row, today_high):
    """The regional normal high/low, and how today's forecast high sits against it. The normal is ECCC's for the REGION, not the station."""
    if row is None:
        return None
    nh = _num(row.get("normal_high_c"))
    delta = None
    if today_high is not None and nh is not None:
        delta = int(today_high) - nh
    return {"high": nh, "low": _num(row.get("normal_low_c")), "today_vs_normal": delta}


def build_window(city, hourly_rows, sun_rows, yesterday_row, normals_row, now, wx_symbol):
    """Everything the city page adds, as one dict. `city` is the _aurora_city_payload entry."""
    hours = build_hourly(hourly_rows, city.get("prov"), now, wx_symbol)
    # Only the FIRST period counts, and only when it is a daytime one with a high: once it is evening the first period is "Tonight" (a low), and
    # comparing the next day's high to a normal would label tomorrow as today.
    first = (city.get("forecast") or [None])[0]
    today_high = first.get("high") if first else None
    return {
        "hours": hours,
        "line": temp_line(hours),
        "sun": build_sun(sun_rows, city.get("prov"), now),
        "yesterday": build_yesterday(yesterday_row),
        "normals": build_normals(normals_row, today_high),
        "any": bool(hours or sun_rows or yesterday_row or normals_row),
    }
