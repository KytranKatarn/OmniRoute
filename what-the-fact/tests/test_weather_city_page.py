"""/weather/city/<name> — a per-city detail page, SCOPED DOWN from the
design-handoff mockup (#6272, Batch 8).

design-handoff/wtf-city.html carries an hourly-forecast chart, a 14-day
outlook + precipitation chart, an AQI dial, a sun/moon panel, and a 30-day
"confidence-decaying" A.U.R.O.R.A. outlook — over a hand-authored 61-city
fabricated dataset. None of it is backed by real ingest: wtf.aurora_city_obs
holds one current reading per city and wtf.aurora_city_forecast holds exactly
ONE MSC citypage issue with 4 periods, not an hourly or 14-day series. This
page renders ONLY what the real tables hold — the same fields /weather's own
city cards already render honestly via the shared _aurora_city_payload().

Each test mutation-checked against the ORIGINAL bug this route+template pair
had while being written: `p.pop` in Jinja resolves to dict.pop() (the bound
method) rather than the "pop" dict key, because Jinja's `.` operator tries
getattr before getitem. That crashed the page outright — caught by this
file's own render smoke tests before it ever shipped, not left to a mutation
test to discover after the fact.
"""

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"

_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


FRESH_CITY = {
    "code": "s1", "name": "Toronto", "prov": "ON", "is_capital": True,
    "lat": 43.6, "lon": -79.4, "status": "ok",
    "observed": "2026-09-04T12:00:00", "age_min": 12,
    "temp": 21, "condition": "Cloudy", "humidity": 58,
    "wind": 16, "calm": False, "gust": 24, "dir": "E",
    "humidex": 23, "pressure": 101.2,
    "forecast": [
        {"label": "Today", "high": 22, "low": None, "pop": 40, "summary": "Cloudy with showers."},
        {"label": "Tonight", "high": None, "low": 15, "pop": 30, "summary": "Clearing."},
    ],
}

CALM_STALE_CITY = {
    "code": "s2", "name": "Regina", "prov": "SK", "is_capital": True,
    "lat": 50.4, "lon": -104.6, "status": "ok",
    "observed": "2026-09-04T09:00:00", "age_min": 400,
    "temp": 26, "condition": "Sunny", "humidity": 28,
    "wind": 0, "calm": True, "gust": None, "dir": None,
    "humidex": None, "pressure": None,
    "forecast": [],
}

SILENT_CITY = {
    "code": "s3", "name": "Cambridge Bay", "prov": "NU", "is_capital": False,
    "lat": 69.1, "lon": -105.0, "status": "silent",
    "observed": None, "age_min": None,
    "temp": None, "condition": None, "humidity": None,
    "wind": None, "calm": False, "gust": None, "dir": None,
    "humidex": None, "pressure": None,
    "forecast": [],
}

ALL_CITIES = [FRESH_CITY, CALM_STALE_CITY, SILENT_CITY]


def _render(env, city, **overrides):
    kwargs = dict(city=city, cities=ALL_CITIES, city_stale_min=180,
                  source_count=46, is_subscriber=False)
    kwargs.update(overrides)
    return env.get_template("weather_city.html").render(**kwargs)


class TestFreshReadingRenders:
    def test_temperature_and_condition(self, env):
        html = _render(env, FRESH_CITY)
        assert "Toronto weather" in html
        assert "21" in html
        assert "Cloudy" in html

    def test_freshness_is_honest_for_a_recent_reading(self, env):
        html = _render(env, FRESH_CITY)
        assert "observed 12 min ago" in html
        assert "shown as stale" not in html

    def test_wind_direction_and_gust_render(self, env):
        html = _render(env, FRESH_CITY)
        assert "from E" in html
        assert "gust 24" in html

    def test_forecast_periods_render_with_pop(self, env):
        # Regression: p.pop crashes in Jinja (dict.pop shadowing) unless the
        # template uses bracket access — this is the render actually failing
        # if that regresses, not a string search on dead code.
        html = _render(env, FRESH_CITY)
        assert "Today" in html
        assert "Cloudy with showers." in html
        assert "40% PoP" in html
        assert "Tonight" in html
        assert "Clearing." in html


class TestHonestAbsence:
    """Mirrors the house rule pinned across every other archetype-4 page on
    this site: an absent measurement renders as an em dash, never a
    fabricated 0, and calm wind is its own measurement, not "0 km/h"."""

    def test_calm_wind_says_calm_not_zero(self, env):
        html = _render(env, CALM_STALE_CITY)
        assert "Calm" in html
        assert "0 km/h" not in html

    def test_a_stale_reading_is_flagged(self, env):
        # 400 min > the 180 min threshold passed to the render.
        html = _render(env, CALM_STALE_CITY)
        assert "old" in html
        assert "shown as stale" in html

    def test_missing_humidex_and_pressure_are_dashes_not_zeros(self, env):
        html = _render(env, CALM_STALE_CITY)
        assert "0°C" not in html
        assert "0 kPa" not in html
        assert "—" in html or "&mdash;" in html

    def test_a_fully_silent_city_says_so(self, env):
        html = _render(env, SILENT_CITY)
        assert "no reading available" in html
        hero = html.split("wtf-wxc-hero")[1].split("wtf-wxc-section")[0]
        assert ">0<" not in hero and "0°" not in hero

    def test_a_city_with_no_forecast_issue_shows_no_forecast_section(self, env):
        html = _render(env, CALM_STALE_CITY)
        assert "Forecast</div>" not in html


class TestNoFabricatedSections:
    """The design mockup's hourly chart / 14-day outlook / AQI dial / sun-moon
    panel / 30-day outlook are all absent from this page ON PURPOSE — none of
    them are backed by real ingest. A future edit pulling from the mockup
    verbatim would reintroduce fabricated data; this guards against that."""

    def test_no_hourly_or_aqi_or_thirty_day_markup(self, env):
        html = _render(env, FRESH_CITY)
        for banned in ("Hourly forecast", "Air quality", "AQI", "30-day outlook",
                       "Sun and moon", "14 days"):
            assert banned not in html, f"fabricated section leaked in: {banned!r}"


class TestCityPicker:
    def test_every_city_is_an_option_and_current_city_is_selected(self, env):
        html = _render(env, FRESH_CITY)
        assert 'value="Toronto"' in html
        assert 'value="Regina"' in html
        assert 'value="Cambridge Bay"' in html
        # exactly one option carries selected, and it is the current city
        assert 'value="Toronto" selected' in html
        assert 'value="Regina" selected' not in html

    def test_back_link_to_the_full_weather_page(self, env):
        html = _render(env, FRESH_CITY)
        assert 'href="/weather"' in html


class TestWeatherCityRouteWiring:
    """Template-only tests above can't catch the ROUTE failing to find a
    city or building the payload wrong — mirrors TestOwnersRouteWiring's
    source-grep approach (this suite runs without a live DB)."""

    def test_route_aborts_404_for_an_unknown_city(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index('def weather_city(')
        end = src.index("\n@bp.get", start + 1)
        body = src[start:end]
        assert "abort(404)" in body, (
            "weather_city() must 404 an unrecognised city name, not silently "
            "render an empty/None city"
        )

    def test_route_reuses_the_shared_aurora_city_payload_builder(self):
        src = ROUTES.read_text(encoding="utf-8")
        start = src.index('def weather_city(')
        end = src.index("\n@bp.get", start + 1)
        body = src[start:end]
        assert "_aurora_city_payload(" in body, (
            "weather_city() must build its city data via the SAME "
            "_aurora_city_payload() /weather uses — a hand-rolled query here "
            "could disagree with what /weather's own cards show for the "
            "same city"
        )
