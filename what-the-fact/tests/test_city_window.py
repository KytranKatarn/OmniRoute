"""The /weather/city/<name> window (task 7235): next 24 hours, sun, yesterday, regional normal, built from the S2 tables.

Pure-builder tests plus template render tests. Numbers come from a fixture shaped like the real rows; the builder never invents a figure.
"""

import pathlib
from datetime import date, datetime, timezone

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from consumer import city_window as cw
from consumer import wx_symbols

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
UTC = timezone.utc
NOW = datetime(2026, 10, 14, 18, 20, tzinfo=UTC)  # 2:20 PM in Toronto (EDT), 12:20 PM in Calgary (MDT)


def _h(hour, **kw):
    row = {"hour_utc": datetime(2026, 10, 14, hour, tzinfo=UTC), "condition": "Cloudy", "icon_code": "10", "temp_c": 12.0, "lop_pct": 0,
           "wind_speed_kmh": 14.0, "wind_is_calm": False, "wind_dir": "NW", "wind_gust_kmh": None}
    row.update(kw)
    return row


def _hours(start=17, n=30):
    out = []
    for i in range(n):
        t = datetime(2026, 10, 14, start, tzinfo=UTC) + __import__("datetime").timedelta(hours=i)
        out.append({"hour_utc": t, "condition": "Cloudy", "icon_code": "10", "temp_c": 10.0 + (i % 7), "lop_pct": 0,
                    "wind_speed_kmh": 10.0, "wind_is_calm": False, "wind_dir": "N", "wind_gust_kmh": None})
    return out


class TestHourly:
    def test_past_hours_are_dropped_and_the_first_is_now(self):
        rows = [_h(15), _h(17), _h(18), _h(19)]
        out = cw.build_hourly(rows, "ON", NOW, wx_symbols.wx_symbol)
        assert [h["label"] for h in out][0] == "Now"
        assert len(out) == 2  # 18:00 and 19:00; 15:00 and 17:00 are over (17:00 is 80 min old)

    def test_capped_at_24_and_labelled_in_the_cities_own_zone(self):
        out = cw.build_hourly(_hours(), "AB", NOW, wx_symbols.wx_symbol)
        assert len(out) == 24
        assert out[1]["label"] == "1 PM"   # 19:00 UTC in Calgary (MDT, UTC-6) is 1 PM, not 7 PM

    def test_day_break_marks_local_midnight_not_utc_midnight(self):
        out = cw.build_hourly(_hours(), "ON", NOW, wx_symbols.wx_symbol)
        breaks = [h["label"] for h in out if h["day_break"]]
        assert breaks == ["Now", "12 AM"]

    def test_calm_is_not_zero_and_missing_wind_is_none(self):
        out = cw.build_hourly([_h(18, wind_is_calm=True, wind_speed_kmh=None), _h(19, wind_speed_kmh=None)], "ON", NOW, wx_symbols.wx_symbol)
        assert out[0]["calm"] is True and out[0]["wind"] is None
        assert out[1]["calm"] is False and out[1]["wind"] is None

    def test_missing_temperature_stays_none(self):
        out = cw.build_hourly([_h(18, temp_c=None)], "ON", NOW, wx_symbols.wx_symbol)
        assert out[0]["temp"] is None

    def test_unknown_province_falls_back_without_guessing(self):
        out = cw.build_hourly([_h(18)], None, NOW, wx_symbols.wx_symbol)
        assert out[0]["label"] == "Now"


class TestTempLine:
    def test_needs_two_readings(self):
        assert cw.temp_line([{"temp": 5}]) is None
        assert cw.temp_line([{"temp": None}, {"temp": None}]) is None

    def test_a_gap_is_skipped_not_interpolated(self):
        hrs = [{"temp": 4}, {"temp": None}, {"temp": 8}]
        line = cw.temp_line(hrs)
        assert [p["i"] for p in line["points"]] == [0, 2]
        assert (line["min"], line["max"]) == (4, 8)

    def test_warmest_point_is_highest_on_the_chart(self):
        line = cw.temp_line([{"temp": 1}, {"temp": 9}, {"temp": 3}])
        ys = {p["temp"]: p["y"] for p in line["points"]}
        assert ys[9] < ys[3] < ys[1]

    def test_flat_series_does_not_divide_by_zero(self):
        assert cw.temp_line([{"temp": 5}, {"temp": 5}, {"temp": 5}])["max"] == 5


class TestSun:
    def _row(self, d):
        return {"sun_date": d, "sunrise_utc": datetime(2026, 10, 14, 11, 52, tzinfo=UTC), "sunset_utc": datetime(2026, 10, 14, 22, 31, tzinfo=UTC)}

    def test_local_today_row_is_used_and_formatted_locally(self):
        s = cw.build_sun([self._row(date(2026, 10, 13)), self._row(date(2026, 10, 14))], "ON", NOW)
        assert s["sunrise"] == "7:52 AM" and s["sunset"] == "6:31 PM"
        assert s["daylight"] == "10 h 39 min"

    def test_no_row_for_today_is_an_absence(self):
        assert cw.build_sun([self._row(date(2026, 10, 12))], "ON", NOW) is None

    def test_utc_evening_is_still_the_cities_previous_local_day(self):
        late = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)  # 10 PM on the 14th in Toronto
        assert cw.build_sun([self._row(date(2026, 10, 14))], "ON", late) is not None


class TestYesterdayAndNormals:
    def test_trace_is_not_zero_and_not_absent(self):
        y = cw.build_yesterday({"obs_date": date(2026, 10, 13), "high_c": 14.2, "low_c": 3.0, "rain_mm": None, "rain_trace": True,
                                "snow_cm": None, "snow_trace": False, "gust_kmh": None, "gust_dir": None})
        assert y["rain"] == "trace" and y["snow"] is None and y["gust"] is None
        assert (y["high"], y["low"]) == (14, 3)

    def test_measured_amounts_carry_units(self):
        y = cw.build_yesterday({"obs_date": date(2026, 10, 13), "high_c": 1, "low_c": -2, "rain_mm": 0.0, "rain_trace": False,
                                "snow_cm": 3.4, "snow_trace": False, "gust_kmh": 52.0, "gust_dir": "W"})
        assert y["rain"] == "0.0 mm" and y["snow"] == "3.4 cm" and y["gust"] == 52

    def test_no_row_means_none(self):
        assert cw.build_yesterday(None) is None and cw.build_normals(None, 10) is None

    def test_today_against_normal_is_a_signed_difference(self):
        assert cw.build_normals({"normal_high_c": 12.0, "normal_low_c": 3.0}, 15)["today_vs_normal"] == 3
        assert cw.build_normals({"normal_high_c": 12.0, "normal_low_c": 3.0}, 9)["today_vs_normal"] == -3

    def test_a_tonight_first_period_is_not_compared_to_the_normal_high(self):
        city = {"prov": "ON", "forecast": [{"label": "Tonight", "high": None, "low": 4}, {"label": "Thursday", "high": 20, "low": None}]}
        w = cw.build_window(city, [], [], None, {"normal_high_c": 12.0, "normal_low_c": 3.0}, NOW, wx_symbols.wx_symbol)
        assert w["normals"]["today_vs_normal"] is None


class TestWindowRenders:
    @pytest.fixture(scope="class")
    def env(self):
        stub = "{% block title %}{% endblock %}{% block meta %}{% endblock %}<body>{% block content %}{% endblock %}</body>"
        return Environment(loader=ChoiceLoader([DictLoader({"base.html": stub}), FileSystemLoader(str(TPL))]),
                           autoescape=select_autoescape(["html"]))

    CITY = {"code": "s1", "name": "Toronto", "prov": "ON", "is_capital": True, "lat": 43.6, "lon": -79.4, "status": "ok", "observed": "x",
            "age_min": 5, "temp": 14, "condition": "Cloudy", "humidity": 58, "wind": 10, "calm": False, "gust": None, "dir": "E",
            "humidex": None, "pressure": 101.2, "glyph": "cloudy",
            "forecast": [{"label": "Today", "high": 16, "low": None, "pop": 20, "summary": "Cloudy.", "glyph": "cloudy"}]}

    def _render(self, env, window):
        return env.get_template("weather_city.html").render(city=self.CITY, cities=[self.CITY], city_stale_min=180, source_count=46,
                                                            is_subscriber=False, window=window, wx_glyphs=wx_symbols.GLYPH_SVG)

    def _window(self):
        return cw.build_window(self.CITY, _hours(), [{"sun_date": date(2026, 10, 14), "sunrise_utc": datetime(2026, 10, 14, 11, 52, tzinfo=UTC),
                                                       "sunset_utc": datetime(2026, 10, 14, 22, 31, tzinfo=UTC)}],
                               {"obs_date": date(2026, 10, 13), "high_c": 14.2, "low_c": 3.0, "rain_mm": 2.5, "rain_trace": False,
                                "snow_cm": None, "snow_trace": False, "gust_kmh": 44.0, "gust_dir": "W"},
                               {"normal_high_c": 13.0, "normal_low_c": 4.0}, NOW, wx_symbols.wx_symbol)

    def test_full_window_renders_every_section(self, env):
        html = self._render(env, self._window())
        for needle in ("Next 24 hours", "Sunrise", "7:52 AM", "6:31 PM", "10 h 39 min of daylight", "Normal high / low",
                       "3&deg; above normal", "Yesterday high / low", "2.5 mm rain", "Yesterday peak gust", "<polyline", "wx-sym"):
            assert needle in html, needle
        assert html.count('<div class="wtf-wxc-hour-t">') == 24

    def test_no_window_renders_the_original_page(self, env):
        html = self._render(env, None)
        assert "Next 24 hours" not in html and "Today in context" not in html and "Current conditions" in html

    def test_an_empty_window_adds_nothing(self, env):
        html = self._render(env, cw.build_window(self.CITY, [], [], None, None, NOW, wx_symbols.wx_symbol))
        assert "Next 24 hours" not in html and "Today in context" not in html

    def test_route_wires_the_window_and_the_icon_column(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py").read_text()
        assert "f.abbrev_summary, f.text_summary, f.icon_code" in src and "window=window," in src and "_city_window_for(city)" in src
