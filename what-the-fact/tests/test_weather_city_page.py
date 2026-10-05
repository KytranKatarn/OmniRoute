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


class TestHomeCityButton:
    """PORT-STATUS 9a — the design's "set home" control, ported to the key the
    live site actually reads.

    /weather ("My city" select) and the homepage weather strip both use
    localStorage key ``wtf.homeCity`` and compare it to the city's DISPLAY NAME.
    The design mock also wrote ``wtf-default-city``, which nothing reads, so a
    button that wrote only that key would look like it worked and change
    nothing. These tests pin the key, the value, and the toggle behaviour.
    """

    def _script(self, html):
        # The inline script that owns the button — the only <script> that
        # mentions wtf-wxc-home. Asserting it was FOUND keeps every check below
        # from passing on an empty string.
        blocks = [b.split("</script>")[0] for b in html.split("<script>")[1:]]
        mine = [b for b in blocks if "wtf-wxc-home" in b]
        assert len(mine) == 1, "expected exactly one inline script owning the home button"
        return mine[0]

    def test_button_carries_the_city_display_name(self, env):
        html = _render(env, FRESH_CITY)
        assert 'id="wtf-wxc-home"' in html
        assert 'data-city="Toronto"' in html
        # plain button, not a submit — it must never navigate or post
        assert '<button type="button" id="wtf-wxc-home"' in html

    def test_a_name_with_an_apostrophe_cannot_break_out_of_the_attribute(self, env):
        city = dict(FRESH_CITY, name="St. John's \"x\" <b>")
        html = _render(env, city, cities=[city])
        assert 'data-city="St. John&#39;s &#34;x&#34; &lt;b&gt;"' in html
        assert "<b>" not in html.split('id="wtf-wxc-home"')[1].split(">")[0]

    def test_it_uses_the_key_the_rest_of_the_site_reads(self, env):
        js = self._script(_render(env, FRESH_CITY))
        assert '"wtf.homeCity"' in js
        assert "wtf-default-city" not in js, (
            "the design mock's second key is read by nothing on the live site — "
            "do not write it"
        )

    def test_value_is_written_with_textcontent_not_innerhtml(self, env):
        js = self._script(_render(env, FRESH_CITY))
        assert "innerHTML" not in js
        assert "textContent" in js

    def test_the_toggle_sets_and_unsets_the_key_in_a_real_run(self, env, tmp_path):
        import json, shutil, subprocess
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not installed — behaviour is covered statically above")
        js = self._script(_render(env, FRESH_CITY))
        harness = tmp_path / "run.js"
        harness.write_text("""
const store = {};
global.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};
const attrs = { "data-city": "Toronto" };
let handler = null; const classes = new Set();
const btn = {
  getAttribute: k => attrs[k], setAttribute: (k, v) => { attrs[k] = v; },
  classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) },
  addEventListener: (ev, fn) => { if (ev === "click") handler = fn; },
  textContent: "",
};
global.document = { getElementById: id => (id === "wtf-wxc-home" ? btn : null) };
global.window = { addEventListener: () => {} };
eval(process.argv[2]);
const out = [];
const snap = () => out.push({ store: JSON.stringify(store), label: btn.textContent,
  pressed: attrs["aria-pressed"], on: classes.has("is-on") });
snap();            // fresh load, nothing stored
handler(); snap(); // click -> set
handler(); snap(); // click again -> unset
store["wtf.homeCity"] = "Regina"; handler(); snap(); // different home -> replaced, not toggled off
console.log(JSON.stringify(out));
""", encoding="utf-8")
        r = subprocess.run([node, str(harness), js], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        s0, s1, s2, s3 = json.loads(r.stdout)
        assert s0["store"] == "{}" and s0["label"] == "Set as my city" and s0["pressed"] == "false"
        assert s1["store"] == '{"wtf.homeCity":"Toronto"}' and s1["pressed"] == "true" and s1["on"] is True
        assert "unset" in s1["label"]
        assert s2["store"] == "{}" and s2["label"] == "Set as my city" and s2["on"] is False
        assert s3["store"] == '{"wtf.homeCity":"Toronto"}', "another city was home: click must make THIS city home"

    def test_another_tab_changing_the_key_repaints_this_button(self, env, tmp_path):
        """A `storage` event fires in OTHER tabs when the key changes. Without a
        listener this page's button keeps a stale label until clicked."""
        import json, shutil, subprocess
        node = shutil.which("node")
        if node is None:
            pytest.skip("node not installed")
        js = self._script(_render(env, FRESH_CITY))
        assert "storage" in js, "no storage listener: cross-tab changes would be invisible"
        harness = tmp_path / "xtab.js"
        harness.write_text("""
const store = {};
global.localStorage = { getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } };
const attrs = { "data-city": "Toronto" }; let label = "";
const btn = { getAttribute: k => attrs[k], setAttribute: (k, v) => { attrs[k] = v; },
  classList: { toggle: () => {} }, addEventListener: () => {},
  get textContent() { return label; }, set textContent(v) { label = v; } };
global.document = { getElementById: () => btn };
const listeners = {};
global.window = { addEventListener: (ev, fn) => { listeners[ev] = fn; } };
eval(process.argv[2]);
const out = [label];
store["wtf.homeCity"] = "Toronto"; listeners.storage({ key: "wtf.homeCity" }); out.push(label);   // another tab made Toronto home
store["wtf.homeCity"] = "Regina";  listeners.storage({ key: "wtf.homeCity" }); out.push(label);   // ...then Regina
store["wtf.homeCity"] = "Toronto"; listeners.storage({ key: "unrelated" });     out.push(label);   // unrelated key: ignored
store["wtf.homeCity"] = "Toronto"; listeners.storage({ key: "wtf.homeCity" }); out.push(label);   // on again, so the clear below is observable
delete store["wtf.homeCity"];      listeners.storage({ key: null });            out.push(label);   // storage cleared
console.log(JSON.stringify(out));
""", encoding="utf-8")
        r = subprocess.run([node, str(harness), js], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        a, b, c, d, on_again, e = json.loads(r.stdout)
        assert a == "Set as my city"
        assert "unset" in b, "another tab set THIS city as home: button must show it"
        assert c == "Set as my city", "another tab chose a different home: button must reset"
        assert c == d, "an unrelated key must not repaint"
        assert "unset" in on_again, "precondition: button must be ON before the clear, or the check below proves nothing"
        assert e == "Set as my city", "storage cleared (key null) must repaint"
