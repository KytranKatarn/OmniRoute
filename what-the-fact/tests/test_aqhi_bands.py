"""AQHI colour bands on /weather. The behaviour check is tests/js/aqhi_bands_smoke.js
(node); these pin the template so the upper-bound semantics of WTFMap.ramp() can't be
forgotten again (stops written as band STARTS shifted every reading up one band)."""
import pathlib

W = (pathlib.Path(__file__).resolve().parents[1] / "consumer/templates/weather.html").read_text(encoding="utf-8")


def test_stops_are_upper_bounds_at_the_rounding_boundaries():
    assert "[3.5," in W and "[6.5," in W and "[10.5," in W


def test_old_band_start_stops_are_gone():
    assert '[[1,"#10b981","1"]' not in W


def test_tooltip_and_ranked_rows_name_the_risk_band():
    assert "aqhiBandName(s.aqhi_value)" in W and W.count("aqhiBandName(s.aqhi_value)") >= 2


def test_fire_legend_labels_name_intervals_not_the_wrong_end():
    assert '[10,"#78350f","10+"]' not in W and '[1e9,"#7f1d1d","5,000+"]' not in W
    assert W.count('"11\\u2013100"') == 2  # default + colourblind twin
