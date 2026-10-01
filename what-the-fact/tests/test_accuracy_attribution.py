"""The accuracy page scores Environment Canada's forecasts (ingest/weather/citypage.py reads
MSC Datamart), not one of ours. Labelling them "our forecast" misattributes them — and would
blur the line once A.U.R.O.R.A. publishes forecasts of its own (Dev HQ #7071)."""
from pathlib import Path

T = Path(__file__).resolve().parents[1] / "consumer" / "templates"
FA = (T / "forecast_accuracy.html").read_text(encoding="utf-8")
WX = (T / "weather.html").read_text(encoding="utf-8")


def test_no_template_calls_the_scored_forecast_ours():
    for src in (FA, WX):
        assert "our forecast" not in src.lower()


def test_the_series_is_attributed_to_environment_canada():
    assert "Environment Canada forecast (average miss)" in FA
    assert "Environment Canada publishes" in FA
    assert "How accurate is the Environment Canada forecast?" in WX


def test_the_scoring_itself_stays_ours():
    assert "the scoring and the measurements are ours" in FA
