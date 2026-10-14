"""/weather gets its Forecast accuracy section, from the SAME data as /weather/accuracy (task #7220, found by the design-port rig).

The section is real: it renders the shared payload (skill curve, persistence baseline, worst miss) or is omitted. These tests render the real
template block through Jinja, check the structure, and run the real CSS in a real browser at phone width (no horizontal overflow). The
climate stories section already existed live; only its heading wording and the mockup's two framing notes were missing.
"""
import re
import time
from datetime import date
from pathlib import Path

import pytest
from jinja2 import Environment

C = Path(__file__).resolve().parents[1] / "consumer"
HTML = (C / "templates" / "weather.html").read_text(encoding="utf-8")
ROUTES = (C / "routes.py").read_text(encoding="utf-8")


def _section():
    m = re.search(r"\{% if accuracy and accuracy\.skill_curve.*?\{% endif %\}\n(?=\n\{% if aurora_map %\})", HTML, flags=re.S)
    assert m, "accuracy section not found in weather.html"
    return m.group(0)


def _payload(**over):
    p = {
        "skill_curve": [
            {"lead_days": 0, "pairs": 400, "mae_c": 1.2, "bias_c": 0.1, "thin": False},
            {"lead_days": 1, "pairs": 380, "mae_c": 2.0, "bias_c": 0.2, "thin": False},
            {"lead_days": 4, "pairs": 20, "mae_c": 3.6, "bias_c": -0.5, "thin": True},
        ],
        "persistence_curve": {1: {"pairs": 300, "mae_c": 2.8, "thin": False}, 4: {"pairs": 15, "mae_c": 3.0, "thin": True}},
        "chart_max_mae": 3.6,
        "summary": {"same_day_mae_c": 1.2, "same_day_within3_pct": 91, "longest_lead_days": 4, "longest_mae_c": 3.6,
                    "longest_within3_pct": 52, "window_days": 38},
        "worst_miss": {"city": "Yellowknife", "forecast_c": 19.0, "observed_c": 28.0, "target_day": date(2026, 10, 3), "lead_days": 2},
    }
    p.update(over)
    return p


def _render(accuracy):
    return Environment().from_string(_section()).render(accuracy=accuracy)


def test_section_renders_real_bars_stats_and_worst_call():
    out = _render(_payload())
    assert out.count("wtf-wx-acc-bar-wrap") == 3
    assert "Forecast accuracy" in out and "Scoring the forecaster" in out and 'href="/weather/accuracy"' in out
    assert "&plusmn;1.2&deg;" in out and "91% within 3" in out and "4-day average miss" in out
    assert "Called 19&deg;C for Yellowknife on 3 October, 2 days out. It reached 28&deg;C." in out


def test_bar_heights_scale_to_the_chart_max_and_persistence_decides_the_colour():
    out = _render(_payload())
    assert "height:100.0%" in out  # the 3.6 bar is the max
    assert "height:33.3%" in out  # 1.2 / 3.6
    assert 'wtf-wx-acc-bar lose' in out  # +4d: 3.6 >= persistence 3.0
    assert 'wtf-wx-acc-bar beat' in out  # +1d: 2.0 < persistence 2.8
    assert out.count("wtf-wx-acc-persist") == 2  # only leads that have a persistence value


def test_thin_samples_are_labelled_not_hidden():
    assert "(thin sample)" in _render(_payload())


@pytest.mark.parametrize("accuracy", [None, {}, {"skill_curve": []}, {"skill_curve": [{"lead_days": 0}], "chart_max_mae": 0}])
def test_no_data_means_no_section_not_an_empty_one(accuracy):
    assert _render(accuracy).strip() == ""


def test_missing_worst_miss_and_persistence_degrade_quietly():
    out = _render(_payload(worst_miss=None, persistence_curve={}))
    assert "Worst call" not in out and "wtf-wx-acc-persist" not in out and "dashed line" not in out
    assert out.count("wtf-wx-acc-bar-wrap") == 3


def test_section_is_inside_the_page_container_after_the_lower_grid():
    assert HTML.index("<div class=\"wtf-wx-below\">") < HTML.index('<section class="wtf-wx-acc"') < HTML.index("{% if aurora_map %}\n<script")


def test_climate_heading_matches_the_mockup_and_gets_its_two_framing_notes():
    assert "Recent climate and science stories" in HTML and "Recent climate &amp; science stories" not in HTML
    assert "it is not a verdict on the underlying science" in HTML and "Read the cluster." in HTML


def test_both_routes_use_the_one_shared_payload_builder():
    wa = ROUTES.split("def weather_accuracy():", 1)[1].split("\n\n\n", 1)[0]
    assert "_aurora_accuracy_payload(S)" in wa and "persistence_rows" not in wa
    w = ROUTES.split("def weather():", 1)[1].split("\n\n\n", 1)[0]
    assert "_aurora_accuracy_payload_cached(S)" in w and "accuracy=accuracy_payload" in w
    assert "weather(): forecast-accuracy payload failed" in w  # failure isolation: a bad query never takes the page down


def test_cache_serves_repeat_calls_and_expires(monkeypatch):
    from consumer import routes

    calls = []
    monkeypatch.setattr(routes, "_aurora_accuracy_payload", lambda S: calls.append(1) or {"n": len(calls)})
    monkeypatch.setitem(routes._ACC_CACHE, "v", None)
    assert routes._aurora_accuracy_payload_cached("s") == {"n": 1}
    assert routes._aurora_accuracy_payload_cached("s") == {"n": 1} and len(calls) == 1
    monkeypatch.setitem(routes._ACC_CACHE, "t", time.monotonic() - routes._ACC_TTL_S - 1)
    assert routes._aurora_accuracy_payload_cached("s") == {"n": 2} and len(calls) == 2


@pytest.mark.parametrize("width", [1280, 390])
def test_section_has_no_horizontal_overflow_in_a_real_browser(width):
    sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed: the real-browser check did NOT run")
    css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", HTML, flags=re.S))
    css = re.sub(r"\{#.*?#\}|\{%.*?%\}|\{\{.*?\}\}", "", css, flags=re.S)
    markup = _render(_payload())
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"chromium is not available ({str(exc)[:60]}): the real-browser check did NOT run")
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.set_content(f"<!doctype html><meta name=viewport content='width=device-width'><style>:root{{--wtf-bg-card:#0b1220;--wtf-border:#1f2937;"
                         f"--wtf-text-muted:#6b7280;--wtf-text-2:#d1d5db}}body{{margin:0;padding:0 16px}}{css}</style><div style='max-width:1080px;margin:0 auto'>{markup}</div>")
        over = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        cols = page.evaluate("() => getComputedStyle(document.querySelector('.wtf-wx-acc-grid')).gridTemplateColumns.split(' ').length")
        browser.close()
    finally:
        pw.stop()
    assert over <= 1, f"horizontal overflow of {over}px at {width}px"
    assert cols == (1 if width == 390 else 2)
