"""Weather symbols for the /weather city cards: Environment Canada icon_code -> a glyph key, and the SVG artwork for each key.

Single source of truth: the table is passed to the template and drawn by the page's JS, so there is no hand-kept twin to drift (the older wx_icon
macro / _WXI pair has exactly that problem). The artwork follows the design mockup's own glyphs (design-handoff/wtf-weather.html: amber sun, slate cloud,
sky-blue drops; "iconography, not illustration") and adds what OUR data needs and the design lacks: snow, thunderstorm, ice pellets, freezing drizzle and
the night variants (a moon, not a sun, after dark).

Honesty rules (each pinned by a test):
  * Only icon codes actually seen in the data are mapped. Any other non-empty code falls back to the condition TEXT.
  * No code AND no condition text (no observation) -> None: never a default sun.
  * An ambiguous "Clear" / "Mainly clear" with NO code could be a sun or a moon, so it returns None instead of guessing; "Sunny" is a day word.
  * The symbol is decoration beside the condition WORD, which always stays on the card.
"""

SUN_C, CLOUD_C, RAIN_C = "#f59e0b", "#8798b3", "#5b7397"
DROP_C, DRIZZLE_C, FREEZE_C, SNOW_C, BOLT_C, MOON_C = "#38bdf8", "#7dd3fc", "#a5f3fc", "#e0f2fe", "#facc15", "#cbd5e1"
HAZE_C, SMOKE_C, WIND_C = "#a1a99b", "#b45309", "#14b8a6"


def _sun():
    return (f'<circle cx="12" cy="12" r="4.2" fill="none" stroke="{SUN_C}" stroke-width="1.8" stroke-dasharray="1 3.6" stroke-linecap="round"/>'
            f'<circle cx="12" cy="12" r="2.6" fill="{SUN_C}"/>')


def _sun_sm():
    return (f'<circle cx="8.6" cy="8.6" r="3.4" fill="none" stroke="{SUN_C}" stroke-width="1.6" stroke-dasharray="1 3" stroke-linecap="round"/>'
            f'<circle cx="8.6" cy="8.6" r="2.1" fill="{SUN_C}"/>')


def _cloud(c):
    return f'<path d="M7.4 18h9.2a3.6 3.6 0 000-7.2 5.4 5.4 0 00-10.2 2.3A2.9 2.9 0 007.4 18z" fill="none" stroke="{c}" stroke-width="1.7" stroke-linejoin="round"/>'


def _drops(c, n):
    return "".join(f'<line x1="{8.5 + i * 3.4:g}" y1="19" x2="{7.7 + i * 3.4:g}" y2="22" stroke="{c}" stroke-width="1.7" stroke-linecap="round"/>' for i in range(n))


def _wisps(c):
    return "".join(f'<line x1="5" y1="{10 + i * 4}" x2="{19 - i * 2}" y2="{10 + i * 4}" stroke="{c}" stroke-width="1.7" stroke-linecap="round"/>' for i in range(3))


def _snow(n):
    xs = (9, 12.5, 16)[:n] if n < 3 else (9, 12.5, 16)
    return "".join(f'<circle cx="{x:g}" cy="{19.6 if i % 2 == 0 else 21.2:g}" r="1.25" fill="{SNOW_C}"/>' for i, x in enumerate(xs))


def _pellets():
    return "".join(f'<circle cx="{x:g}" cy="{19.6 if i % 2 == 0 else 21.2:g}" r="1.1" fill="none" stroke="{DRIZZLE_C}" stroke-width="1.2"/>' for i, x in enumerate((9, 12.5, 16)))


def _bolt():
    return f'<path d="M12.8 15.4l-2.9 4.4h2.6l-1.2 3.4 4.1-5.1h-2.7l1.6-2.7z" fill="{BOLT_C}"/>'


def _moon():
    return f'<path d="M20.5 13.2A8.6 8.6 0 1 1 10.8 3.5a6.8 6.8 0 0 0 9.7 9.7z" fill="{MOON_C}"/>'


def _moon_sm():
    return f'<g transform="translate(-.5 -.5) scale(.6)">{_moon()}</g>'


GLYPH_SVG = {
    # day
    "sunny": _sun(),
    "mainlysunny": _sun_sm() + _cloud(CLOUD_C),
    "partlycloudy": _sun_sm() + _cloud(CLOUD_C),
    "mostlycloudy": _cloud(CLOUD_C),
    "cloudy": _cloud(CLOUD_C),
    "showers": _cloud(RAIN_C) + _drops(DROP_C, 3),
    "lightrain": _cloud(RAIN_C) + _drops(DROP_C, 2),
    "rain": _cloud(RAIN_C) + _drops("#0ea5e9", 3),
    "drizzle": _cloud(RAIN_C) + _drops(DRIZZLE_C, 2),
    "freezingdrizzle": _cloud(RAIN_C) + _drops(FREEZE_C, 2) + _snow(1),
    "rainsnow": _cloud(RAIN_C) + _drops(DROP_C, 1) + _snow(2),
    "snow": _cloud(RAIN_C) + _snow(3),
    "snowshower": _cloud(RAIN_C) + _snow(2),
    "thunder": _cloud(RAIN_C) + _bolt(),
    "pellets": _cloud(RAIN_C) + _pellets(),
    "fog": _wisps(CLOUD_C),
    "haze": _wisps(HAZE_C),
    "smoke": _wisps(SMOKE_C),
    "windy": _wisps(WIND_C),
    # night: a moon, never a sun
    "clearnight": _moon(),
    "mainlyclearnight": f'<g transform="translate(-1.5 -2) scale(.84)">{_moon()}</g><g transform="translate(9.2 11.2) scale(.62)">{_cloud(CLOUD_C)}</g>',
    "partlycloudynight": _moon_sm() + _cloud(CLOUD_C),
    "mostlycloudynight": _cloud(CLOUD_C),
    "showersnight": _moon_sm() + _cloud(RAIN_C) + _drops(DROP_C, 3),
    "snowshowernight": _moon_sm() + _cloud(RAIN_C) + _snow(2),
    "thundernight": _moon_sm() + _cloud(RAIN_C) + _bolt(),
}

# icon_code -> glyph key. ONLY codes seen in wtf.aurora_city_obs (last 30 days, 2026-10-14) are mapped; the text in brackets is what ECCC calls them there.
ICON_CODE_TO_KEY = {
    "00": "sunny",  # Sunny
    "01": "mainlysunny",  # Mainly Sunny
    "02": "partlycloudy",  # Partly Cloudy
    "03": "mostlycloudy",  # Mostly Cloudy
    "06": "showers",  # Light Rainshower
    "08": "snowshower",  # Light Snowshower
    "10": "cloudy",  # Cloudy
    "12": "lightrain",  # Light Rain (+ and Fog / and Drizzle)
    "13": "rain",  # Rain / Rainshower / Heavy Rain
    "14": "freezingdrizzle",  # Light Freezing Drizzle
    "15": "rainsnow",  # Light Rain and Snow
    "16": "snow",  # Light Snow
    "19": "thunder",  # Thunderstorm (+ with rain / rainshowers)
    "23": "haze",  # Haze
    "24": "fog",  # Mist / Fog / Shallow Fog / Fog Patches / Freezing Fog
    "27": "pellets",  # Ice Pellets / Snow Pellets
    "28": "drizzle",  # Light Drizzle (+ and Fog)
    "30": "clearnight",  # Clear
    "31": "mainlyclearnight",  # Mainly Clear
    "32": "partlycloudynight",  # Partly Cloudy
    "33": "mostlycloudynight",  # Mostly Cloudy
    "36": "showersnight",  # Light Rainshower
    "38": "snowshowernight",  # Light Snowshower
    "39": "thundernight",  # Thunderstorm
    "44": "smoke",  # Smoke
}

# Text fallback for a code we have not mapped (or no code at all). ORDER IS LOAD-BEARING: first match wins, so "rain and snow" and "freezing" must be tried
# before the bare "rain"/"snow", and "mainly sunny" before "sunny". Ambiguous clear/mainly-clear are deliberately absent (sun or moon is unknowable).
_TEXT_RULES = (
    (("smoke",), "smoke"),
    (("haze",), "haze"),
    (("fog", "mist"), "fog"),
    (("thunder",), "thunder"),
    (("freezing drizzle", "freezing rain"), "freezingdrizzle"),
    (("rain and snow", "snow and rain", "rain/snow"), "rainsnow"),
    (("pellets", "hail"), "pellets"),
    (("snowshower", "snow shower", "flurr"), "snowshower"),
    (("snow", "blizzard"), "snow"),
    (("drizzle",), "drizzle"),
    (("shower",), "showers"),
    (("light rain",), "lightrain"),
    (("rain",), "rain"),
    (("wind",), "windy"),
    (("mainly sunny", "mix of sun"), "mainlysunny"),
    (("partly",), "partlycloudy"),
    (("mostly cloudy", "mainly cloudy"), "mostlycloudy"),
    (("overcast", "cloud"), "cloudy"),
    (("sunny",), "sunny"),
)


def symbol_from_text(condition):
    c = (condition or "").strip().lower()
    if not c:
        return None
    for needles, key in _TEXT_RULES:
        if any(n in c for n in needles):
            return key
    return None


def attach_glyphs(cities):
    """Add a "glyph" key (or None) to every city dict of the /weather payload, in place, and return the list."""
    for c in cities:
        c["glyph"] = wx_symbol(c.get("icon_code"), c.get("condition"))
    return cities


def wx_symbol(icon_code, condition=None):
    """The glyph key for one observation, or None (draw nothing)."""
    code = str(icon_code).strip().zfill(2) if icon_code not in (None, "") and str(icon_code).strip() else ""
    if code in ICON_CODE_TO_KEY:
        return ICON_CODE_TO_KEY[code]
    return symbol_from_text(condition)
