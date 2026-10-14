"""/weather: station cards stop printing SVG source, and the home city shows its whole forecast (task #7220 follow-up).

Live bug 2026-10-14: the fire-weather station cards showed `<svg class="wxi" ...>` as literal text, because the icon string was
written with textContent. And a city's card carried only 4 forecast slots (server sliced [:4], labels clipped to 9 chars so
"Thursday night" became a second "THURSDA"). The two helper functions are extracted from the REAL template and run in a real browser;
the control (the old textContent line) must reproduce the bug, or the check proves nothing.
"""
import re
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "consumer"
HTML = (C / "templates" / "weather.html").read_text(encoding="utf-8")
ICON = '<svg class="wxi" width="12" height="12" viewBox="0 0 24 24"><path d="M3 8h10"/></svg>'


def _fn(name):
    m = re.search(r"  function %s\(.*?\n  \}\n" % re.escape(name), HTML, flags=re.S)
    assert m, f"function {name} not found in weather.html"
    return m.group(0)


def _page():
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser checks did NOT run")
    pw = sync_api.sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser checks did NOT run")
    return pw, browser, browser.new_page()


def _run(js):
    pw, browser, page = _page()
    try:
        page.set_content("<!doctype html><body></body>")
        return page.evaluate(js)
    finally:
        browser.close()
        pw.stop()


PRE = "var WXI = {wind: %r, droplet: %r, fire: %r};" % (ICON, ICON, ICON)


def test_station_row_renders_icons_as_elements_not_text():
    out = _run("() => {" + PRE + _fn("_stationRow") + """
      var r = _stationRow({w: 75, h: 30, f: 12});
      return {svgs: r.querySelectorAll('svg').length, text: r.textContent, spans: r.children.length};}""")
    assert out["spans"] == 3 and out["svgs"] == 3
    assert "<svg" not in out["text"] and "75 km/h" in out["text"] and "30%" in out["text"] and "FWI 12" in out["text"]


def test_station_row_omits_missing_readings():
    out = _run("() => {" + PRE + _fn("_stationRow") + "var r=_stationRow({w:null,h:30,f:null}); return {n:r.children.length, t:r.textContent};}")
    assert out["n"] == 1 and "30%" in out["t"]


def test_control_the_old_textcontent_line_does_print_svg_source():
    out = _run("() => {" + PRE + """
      var e = document.createElement('span'); e.textContent = WXI.wind + ' ' + '75 km/h'; return e.textContent;}""")
    assert "<svg" in out


@pytest.mark.parametrize("label,want", [("Thursday night", "Thu night"), ("Friday night", "Fri night"), ("Thursday", "Thursday"),
                                         ("Today", "Today"), ("Tonight", "Tonight"), (None, "")])
def test_forecast_labels_keep_day_and_night_distinct(label, want):
    out = _run("() => {" + _fn("_fcLabel") + "return _fcLabel(%s);}" % ("null" if label is None else repr(label)))
    assert out == want


def test_thursday_and_thursday_night_are_no_longer_the_same_label():
    out = _run("() => {" + _fn("_fcLabel") + "return [_fcLabel('Thursday'), _fcLabel('Thursday night')];}")
    assert out[0] != out[1]


def test_server_sends_the_whole_forecast_not_four_periods():
    src = (C / "aurora_map.py").read_text(encoding="utf-8")
    assert '"forecast": by_site.get(code, [])[:14]' in src and "[:4]" not in src.split("def _aurora_city_payload", 1)[1].split("def ", 1)[0]


def test_home_card_expands_and_compact_cards_stay_at_four():
    assert 'c.forecast.slice(0, 4)' in HTML and "isHome ? c.forecast" in HTML
    assert 'wtf-wx-city-fc" + (isHome ? " is-full" : "")' in HTML and ".wtf-wx-city-fc.is-full" in HTML
