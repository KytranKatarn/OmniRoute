"""Phone (390px) horizontal-overflow fixes found by the design-port rig (task #6604, PR #3829).

Four pages scrolled sideways on a phone: /methodology (stat strip, 57px), /weather/city (forecast row, 96px), /weather/accuracy (data table,
93px) and the home page (map control row, 24px). The CSS under test is the REAL CSS read from the templates and style.css, run in a real
browser at 390px against a representative DOM. Each case runs twice: with the shipped CSS (must not overflow) and with the fix removed (must
overflow), so a test that cannot fail cannot pass either.
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
T = C / "templates"


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _style_block(template):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", _read(T / template), flags=re.S))


STYLE_CSS = _read(C / "static" / "style.css")


def _unfix(css, pairs):
    for old, new in pairs:
        assert old in css, f"the fix text to remove is missing: {old[:60]!r}"
        css = css.replace(old, new)
    return css


# --- static checks: always run -------------------------------------------------------------------------------------------------------------
def test_methodology_stat_strip_wraps_on_a_phone():
    css = _style_block("methodology.html")
    m = re.search(r"@media \(max-width: 600px\) \{([^}]*\{[^}]*\}[^}]*\{[^}]*\})\s*\}", css)
    assert m and "flex-wrap: wrap" in m.group(1) and ".wtf-stat" in m.group(1)


def test_weather_city_forecast_row_wraps_and_summary_has_no_hard_min_width():
    css = _style_block("weather_city.html")
    assert re.search(r"\.wtf-wxc-fc-row \{[^}]*flex-wrap:wrap", css)
    assert re.search(r"\.wtf-wxc-fc-summary \{[^}]*flex:1 1 180px", css) and "min-width:180px" not in css.split(".wtf-wxc-fc-summary")[1].split("}")[0]


def test_forecast_accuracy_table_sits_in_a_scroll_box():
    html = _read(T / "forecast_accuracy.html")
    wrap = html.index('<div class="wtf-fa-table-wrap">')
    assert wrap < html.index('<table class="wtf-fa-table">') < html.index("</table>") < html.index("{# /.wtf-fa-table-wrap #}")
    assert re.search(r"\.wtf-fa-table-wrap \{[^}]*overflow-x:auto", _style_block("forecast_accuracy.html"))


def test_home_map_controls_wrap_on_a_phone():
    assert re.search(r"@media \(max-width: 600px\) \{ #wtf-map-zone \.wtf-h-row-between \{ flex-wrap: wrap;[^}]*\}[^}]*\.wtf-h-map-controls \{ flex: 1 1 100%; flex-wrap: wrap; \}[^}]*\.wtf-map-toggle \{ flex-wrap: wrap; \}", STYLE_CSS)


# --- real-browser checks -------------------------------------------------------------------------------------------------------------------
def _browser():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser overflow checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        return pw, pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser overflow checks did NOT run")


def _overflow(html, width=390):
    pw, browser = _browser()
    try:
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.set_content(html)
        return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    finally:
        browser.close()
        pw.stop()


def _page(css, body):
    return f"<!doctype html><meta name=viewport content='width=device-width'><style>body{{margin:0}}{css}</style>{body}"


STATS = "".join(f'<div class="wtf-stat"><div class="wtf-stat-num">12,345</div><div class="wtf-stat-label">ARTICLES (7 DAYS)</div></div>' for _ in range(4))
FORECAST = (
    '<div class="wtf-wxc-fc-row"><span class="wtf-wxc-fc-label">Tonight and tomorrow</span><span class="wtf-wxc-fc-temps">12° / 4°</span>'
    '<span class="wtf-wxc-fc-pop">40%</span><span class="wtf-wxc-fc-summary">Cloudy periods with a chance of showers late in the day.</span></div>'
)
TABLE_ROWS = "<tr>" + "".join(f"<th>Column heading {i}</th>" for i in range(8)) + "</tr><tr>" + "".join(f"<td>12.5 percent {i}</td>" for i in range(8)) + "</tr>"
CONTROLS = (
    '<div id="wtf-map-zone"><div class="wtf-h-row-between"><h2 id="wtf-map-label">LIVE: CANADA NEWS MAP</h2><div class="wtf-h-map-controls">'
    '<button class="wtf-map-btn">PROVINCE</button><button class="wtf-map-btn">DOMINANT LEAN</button><button class="wtf-map-btn">VOLUME</button>'
    '<div class="wtf-map-toggle"><button class="wtf-map-btn">CANADA</button><button class="wtf-map-btn">WORLD</button></div></div></div></div>'
)


def test_methodology_stats_do_not_overflow_a_phone_and_did_before_the_fix():
    fixed = _style_block("methodology.html")
    unfixed = _unfix(fixed, [("@media (max-width: 600px) { .wtf-trans-stats { flex-wrap: wrap; } .wtf-stat { flex: 1 1 45%; border-bottom: 1px solid #112233; } }", "")])
    body = f'<div class="wtf-trans-stats">{STATS}</div>'
    assert _overflow(_page(fixed, body)) <= 1
    assert _overflow(_page(unfixed, body)) > 20, "the unfixed CSS must overflow, or this test proves nothing"


def test_weather_city_forecast_row_does_not_overflow_a_phone_and_did_before_the_fix():
    fixed = _style_block("weather_city.html")
    unfixed = _unfix(fixed, [("display:flex; flex-wrap:wrap; gap:14px", "display:flex; gap:14px"), ("flex:1 1 180px", "flex:1; min-width:180px")])
    assert _overflow(_page(fixed, FORECAST)) <= 1
    assert _overflow(_page(unfixed, FORECAST)) > 20


def test_accuracy_table_scrolls_inside_its_box_not_the_page():
    fixed = _style_block("forecast_accuracy.html")
    wrapped = f'<div class="wtf-fa-table-wrap"><table class="wtf-fa-table">{TABLE_ROWS}</table></div>'
    bare = f'<table class="wtf-fa-table">{TABLE_ROWS}</table>'
    assert _overflow(_page(fixed, wrapped)) <= 1
    assert _overflow(_page(fixed, bare)) > 20, "an unwrapped wide table must overflow, or this test proves nothing"


def test_home_map_controls_do_not_overflow_a_phone_and_did_before_the_fix():
    unfixed = _unfix(STYLE_CSS, [("@media (max-width: 600px) { #wtf-map-zone .wtf-h-row-between { flex-wrap: wrap; gap: 8px; } .wtf-h-map-controls { flex: 1 1 100%; flex-wrap: wrap; } .wtf-map-toggle { flex-wrap: wrap; } }", "")])
    assert _overflow(_page(STYLE_CSS, CONTROLS)) <= 1
    assert _overflow(_page(unfixed, CONTROLS)) > 1, "the unfixed CSS must overflow, or this test proves nothing"


def test_desktop_layout_is_untouched_by_the_phone_rules():
    """The media blocks only apply <=600px; at 1280 none of the four patterns may overflow either way."""
    assert _overflow(_page(_style_block("methodology.html"), f'<div class="wtf-trans-stats">{STATS}</div>'), 1280) <= 1
    assert _overflow(_page(_style_block("weather_city.html"), FORECAST), 1280) <= 1
    assert _overflow(_page(STYLE_CSS, CONTROLS), 1280) <= 1
