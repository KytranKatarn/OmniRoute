"""/weather: real weather symbols on the city cards, driven by the Environment Canada icon_code (task 7233).

Covers the mapping and its honesty rules, the artwork's safety, the payload, and (real browser) the card helper and the compact-strip layout, with a
control that restores the old clipping rules and must show the bug.
"""
import json
import re
from pathlib import Path

import pytest

from consumer import wx_symbols as w
from consumer.aurora_map import _aurora_city_payload

C = Path(__file__).resolve().parents[1] / "consumer"
HTML = (C / "templates" / "weather.html").read_text(encoding="utf-8")
ROUTES = (C / "routes.py").read_text(encoding="utf-8")

# every (icon_code, ECCC text) pair seen in wtf.aurora_city_obs over the 30 days to 2026-10-14, with the glyph it must get
REAL = [
    ("00", "Sunny", "sunny"), ("01", "Mainly Sunny", "mainlysunny"), ("02", "Partly Cloudy", "partlycloudy"), ("03", "Mostly Cloudy", "mostlycloudy"),
    ("06", "Light Rainshower", "showers"), ("08", "Light Snowshower", "snowshower"), ("10", "Cloudy", "cloudy"), ("12", "Light Rain", "lightrain"),
    ("12", "Light Rain and Fog", "lightrain"), ("12", "Light Rain and Drizzle", "lightrain"), ("13", "Rain", "rain"), ("13", "Rainshower", "rain"),
    ("13", "Heavy Rain", "rain"), ("14", "Light Freezing Drizzle", "freezingdrizzle"), ("15", "Light Rain and Snow", "rainsnow"), ("16", "Light Snow", "snow"),
    ("19", "Thunderstorm", "thunder"), ("19", "Thunderstorm with Light Rain", "thunder"), ("23", "Haze", "haze"), ("24", "Fog", "fog"), ("24", "Mist", "fog"),
    ("24", "Freezing Fog", "fog"), ("27", "Ice Pellets", "pellets"), ("27", "Snow Pellets", "pellets"), ("28", "Light Drizzle", "drizzle"),
    ("28", "Light Drizzle and Fog", "drizzle"), ("30", "Clear", "clearnight"), ("31", "Mainly Clear", "mainlyclearnight"),
    ("32", "Partly Cloudy", "partlycloudynight"), ("33", "Mostly Cloudy", "mostlycloudynight"), ("36", "Light Rainshower", "showersnight"),
    ("38", "Light Snowshower", "snowshowernight"), ("39", "Thunderstorm", "thundernight"), ("44", "Smoke", "smoke"),
]


@pytest.mark.parametrize("code,text,want", REAL)
def test_every_real_code_gets_its_glyph(code, text, want):
    assert w.wx_symbol(code, text) == want


def test_every_mapped_key_has_artwork_and_no_glyph_is_orphaned():
    assert set(w.ICON_CODE_TO_KEY.values()) <= set(w.GLYPH_SVG)
    # the only glyph not reachable from a seen code is "windy", which the condition-text fallback uses
    assert set(w.GLYPH_SVG) - set(w.ICON_CODE_TO_KEY.values()) == {"windy"}


def test_no_observation_draws_nothing_never_a_default_sun():
    assert w.wx_symbol(None, None) is None and w.wx_symbol("", "") is None and w.wx_symbol(None, "") is None and w.wx_symbol("  ", None) is None


def test_ambiguous_clear_without_a_code_draws_nothing_but_sunny_is_a_day_word():
    assert w.wx_symbol(None, "Clear") is None and w.wx_symbol("", "Mainly clear") is None  # sun or moon: unknowable
    assert w.wx_symbol(None, "Sunny") == "sunny"


def test_an_unmapped_code_falls_back_to_the_condition_text():
    assert w.wx_symbol("99", "Heavy Snow") == "snow"
    assert w.wx_symbol("17", "Blizzard") == "snow"
    assert w.wx_symbol("99", "unintelligible") is None


@pytest.mark.parametrize("text,want", [("Freezing Rain", "freezingdrizzle"), ("Rain and Snow", "rainsnow"), ("Light Rain", "lightrain"), ("Rain", "rain"),
                                        ("Mainly Sunny", "mainlysunny"), ("Thunderstorm with hail", "thunder"), ("Snow Showers", "snowshower"), ("Windy", "windy")])
def test_text_fallback_order_is_load_bearing(text, want):
    assert w.symbol_from_text(text) == want


def test_day_and_night_glyphs_differ_and_night_never_draws_a_sun():
    assert w.GLYPH_SVG["sunny"] != w.GLYPH_SVG["clearnight"]
    for key in [k for k in w.GLYPH_SVG if k.endswith("night")]:
        assert w.SUN_C not in w.GLYPH_SVG[key], f"{key} draws a sun after dark"
        assert w.MOON_C in w.GLYPH_SVG[key] or key == "mostlycloudynight"


def test_artwork_is_inert_constant_svg():
    for key, svg in w.GLYPH_SVG.items():
        assert not re.search(r"<script|\son\w+\s*=|href|xlink|url\(|<style|javascript:", svg, re.I), key
        assert not re.findall(r"<(?!/?(?:circle|path|line|g)\b)[a-z]+", svg), f"{key}: unexpected element"
        for colour in re.findall(r'(?:stroke|fill)="([^"]+)"', svg):
            assert colour == "none" or re.fullmatch(r"#[0-9a-f]{6}", colour), (key, colour)


def test_the_table_is_json_serialisable_for_the_template():
    assert json.loads(json.dumps(w.GLYPH_SVG)) == w.GLYPH_SVG


def _row(**over):
    r = {"site_code": "s0000047", "display_name": None, "name_en": "Calgary", "source_prov": "AB", "lat": 51.1, "lon": -114.0, "last_obs_status": "ok",
         "observed_utc": None, "age_min": 12, "temp_c": 12.3, "condition_text": "Mostly Cloudy", "rel_humidity_pct": 60, "wind_speed_kmh": 10,
         "wind_is_calm": False, "wind_gust_kmh": None, "wind_dir": "W", "humidex": None, "pressure_kpa": 90.1, "icon_code": "03"}
    r.update(over)
    return r


def test_the_city_payload_carries_the_raw_icon_code_and_the_route_attaches_the_glyph():
    payload = _aurora_city_payload([_row()], [])
    assert payload["cities"][0]["icon_code"] == "03" and "glyph" not in payload["cities"][0]  # aurora_map stays stdlib-only
    assert w.attach_glyphs(payload["cities"])[0]["glyph"] == "mostlycloudy"


def test_a_city_with_no_observation_has_no_glyph():
    cities = w.attach_glyphs(_aurora_city_payload([_row(icon_code=None, condition_text=None, temp_c=None)], [])["cities"])
    assert cities[0]["glyph"] is None


def test_aurora_map_stays_importable_on_its_own():
    """test_home_weather_bands and test_aurora_provenance load aurora_map as a standalone stdlib-only module; a package-relative import breaks them."""
    src = (C / "aurora_map.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*from\s+\.", src, re.M), "a package-relative import would break the standalone import"
    assert not re.search(r"^\s*(?:from|import)\b[^\n]*wx_symbols", src, re.M)


def test_wiring_the_query_the_template_table_and_the_route_argument():
    weather_fn = ROUTES.split("def weather():", 1)[1].split("\n@bp.get", 1)[0]
    assert "o.condition_text, o.icon_code," in weather_fn, "weather() must select icon_code"
    assert "wx_glyphs=_wx_symbols.GLYPH_SVG" in weather_fn and '_wx_symbols.attach_glyphs(city_payload["cities"])' in weather_fn
    assert "var WX_GLYPHS = {{ (wx_glyphs or {}) | tojson }};" in HTML


# ---- real browser ----------------------------------------------------------------------------------------------------------------------------------
def _fn(name):
    m = re.search(r"  function %s\(.*?\n  \}\n" % re.escape(name), HTML, flags=re.S)
    assert m, f"function {name} not found in weather.html"
    return m.group(0)


def _css():
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", HTML, flags=re.S))
    return re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", "", css, flags=re.S)


def _browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        b = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser checks did NOT run")
    return pw, b


def test_the_card_helper_draws_an_inert_svg_or_nothing():
    pw, b = _browser()
    try:
        page = b.new_page()
        page.set_content("<body></body>")
        out = page.evaluate("() => { var WX_GLYPHS = " + json.dumps(w.GLYPH_SVG) + ";" + _fn("_wxSymbol") + """
          var a = _wxSymbol('lightrain', 38), n1 = _wxSymbol(null, 38), n2 = _wxSymbol('nope', 38);
          return {svg: !!a.querySelector('svg'), aria: a.querySelector('svg').getAttribute('aria-hidden'), size: a.querySelector('svg').getAttribute('width'),
                  glyph: a.getAttribute('data-glyph'), none1: n1 === null, none2: n2 === null, scripts: a.querySelectorAll('script').length};}""")
    finally:
        b.close(); pw.stop()
    assert out == {"svg": True, "aria": "true", "size": "38", "glyph": "lightrain", "none1": True, "none2": True, "scripts": 0}


TOKENS = ":root{--wtf-bg-card:#0b1220;--wtf-border:#1f2937;--wtf-text:#f3f4f6;--wtf-text-2:#d1d5db;--wtf-text-muted:#6b7280;--wtf-local:#3b82f6;--wtf-aurora:#8b5cf6;--wtf-font-mono:monospace}body{margin:0;padding:12px;font-family:sans-serif}"


def _card_html():
    periods = ("Today", "Tonight", "Thursday", "Thu night")
    fc = "".join(f'<div class="wtf-wx-fc-day"><div class="wtf-wx-fc-lbl">{p}</div><div class="wtf-wx-fc-t">12&deg;</div></div>' for p in periods)
    return (f'<div id="grid" class="wtf-wx-citygrid" style="grid-template-columns:repeat(auto-fill,minmax(208px,1fr));width:%WIDTH%px"><a class="wtf-wx-citycard" href="#">'
            f'<div class="wtf-wx-city-top"><span class="wtf-wx-city-name">Calgary</span></div>'
            f'<div class="wtf-wx-city-main"><div class="wtf-wx-city-temp">12.3<span class="wtf-wx-u">&deg;C</span></div>'
            f'<span class="wx-sym"><svg width="38" height="38" viewBox="0 0 24 24">{w.GLYPH_SVG["partlycloudy"]}</svg></span></div>'
            f'<div class="wtf-wx-city-cond">Partly Cloudy</div><div class="wtf-wx-city-fc">{fc}</div><div class="wtf-wx-city-age">2 h ago</div></a></div>')


OLD_STRIP = ".wtf-wx-city-fc:not(.is-full){display:flex;overflow-x:auto;gap:8px}.wtf-wx-city-fc:not(.is-full) .wtf-wx-fc-day{min-width:48px}.wtf-wx-city-fc:not(.is-full) .wtf-wx-fc-lbl{white-space:nowrap;letter-spacing:.08em}"


def _strip(width, control=False):
    pw, b = _browser()
    try:
        page = b.new_page(viewport={"width": width + 40, "height": 800})
        page.set_content(f"<!doctype html><style>{TOKENS}{_css()}{OLD_STRIP if control else ''}</style>" + _card_html().replace("%WIDTH%", str(width)))
        return page.evaluate("""() => {
          const card = document.querySelector('.wtf-wx-citycard').getBoundingClientRect(), fc = document.querySelector('.wtf-wx-city-fc');
          const labels = [...fc.querySelectorAll('.wtf-wx-fc-lbl')].map(e => { const r = e.getBoundingClientRect(); return {right: r.right, w: e.scrollWidth - e.clientWidth}; });
          const sym = document.querySelector('.wx-sym').getBoundingClientRect(), temp = document.querySelector('.wtf-wx-city-temp').getBoundingClientRect();
          return {stripOverflow: fc.scrollWidth - fc.clientWidth, labelsPastCard: labels.filter(l => l.right > card.right + 0.5).length, labelClipped: labels.some(l => l.w > 0),
                  symInside: sym.right <= card.right && sym.left >= temp.right - 0.5, over: document.documentElement.scrollWidth - window.innerWidth};}""")
    finally:
        b.close(); pw.stop()


@pytest.mark.parametrize("width", [238, 208, 354])
def test_the_compact_strip_never_clips_a_label_and_the_symbol_sits_beside_the_temperature(width):
    out = _strip(width)
    assert out["stripOverflow"] <= 0 and out["labelsPastCard"] == 0 and not out["labelClipped"], out
    assert out["symInside"] and out["over"] <= 1, out


def test_control_the_old_scrolling_strip_does_clip():
    out = _strip(238, control=True)
    assert out["stripOverflow"] > 0 or out["labelsPastCard"] > 0, f"the control should reproduce the clipped label: {out}"
