"""Regression coverage for /weather -> /weather/accuracy link (Batch 11, #6280).

The forecast-accuracy page (`weather_accuracy()` in routes.py, rendering
forecast_accuracy.html) is a fully real, DB-backed feature — it joins every
published city forecast (`wtf.aurora_city_forecast`) against what the
stations actually observed (`wtf.aurora_city_obs`) via `consumer.aurora_verify`
— but shipped with ZERO links pointing to it from the main /weather page.
This is the one clear, safe win from the Batch 11 audit for this page; every
other missing_piece (alerts ticker, my-city picker, colourblind toggle,
share-link/hash state, time-scrub playback, 6 missing map layers, animated
icons, fire-spread-prediction section) needs a new ingest pipeline, a new
schema, or a dedicated interactive-widget build, and is deliberately
deferred — see the PR description.

Route/template correction: the module docstring in the task brief says
routes.py:740-741 for weather() — the function actually starts at line 741
(`def weather():`), with weather_city() at :920 and weather_accuracy() at
:1005 in this checkout. Not a real discrepancy, just noted for the record.
"""

from __future__ import annotations

import datetime
import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


class _FakeRequest:
    path = "/weather"


# Mirrors exactly the kwargs weather() passes to render_template("weather.html", ...)
# in consumer/routes.py — see the return statement at the end of that function.
_WEATHER_CTX = dict(
    city_stale_min=180,
    articles=[],
    climate_count=0,
    sci_count=0,
    source_count=46,
    layers=[],
    fire_provinces=[],
    fire_summary=None,
    windiest=[],
    aurora_map=None,
    aurora_cities=None,
    obs_time=None,
    is_subscriber=False,
)


def _render(**overrides):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _FakeRequest()
    ctx = dict(_WEATHER_CTX)
    ctx.update(overrides)
    return env.get_template("weather.html").render(**ctx)


def _weather_accuracy_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def weather_accuracy")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def test_weather_page_renders_with_no_optional_data():
    # Guards the render itself — every optional block (map/cities/layers/
    # fire/windiest) is None or empty here, the same shape the route hits
    # on a cold DB. Must not raise.
    html = _render()
    assert "Weather" in html or "weather" in html


def test_weather_page_links_to_the_accuracy_page():
    html = _render()
    assert 'href="/weather/accuracy"' in html


def test_accuracy_link_survives_with_real_stat_data_present():
    # The card must not be crowded out or accidentally scoped inside the
    # `{% if layers %}` block — it should render whether or not the fire
    # layers section has data.
    html = _render(
        layers=[{
            "layer_key": "firewx", "layer_label": "Fire weather", "issuing_body": "CWFIS",
            "dataset_id": "cwfis", "data_latest": None,
            "last_pull": datetime.datetime(2026, 9, 4, 12, 0),
            "record_count": 5, "stale_after_hours": 48, "is_stale": False,
        }],
        climate_count=12,
        sci_count=8,
    )
    assert 'href="/weather/accuracy"' in html


def test_accuracy_link_text_makes_no_fabricated_claim():
    # No invented number (e.g. a fake "% accurate") is attached to the link —
    # the accuracy page computes its own numbers from real joined data; this
    # entry point must not pre-empt that with a guessed figure.
    html = _render()
    idx = html.find('href="/weather/accuracy"')
    assert idx != -1
    card = html[max(0, idx - 200): idx + 400]
    for bad in ("99%", "100% accurate", "always right"):
        assert bad not in card


def test_weather_accuracy_route_still_exists_and_is_real():
    # Sanity check that the target of the new link is not a stub — it must
    # actually query the DB-backed aurora tables, not return a placeholder.
    body = _weather_accuracy_route_body()
    assert "aurora_city_forecast" in body
    assert "aurora_city_obs" in body
    assert "forecast_accuracy.html" in body
