"""Weather alert strip (PORT-STATUS row 8): counted header, clean summaries, folded evacuations.

Live /weather led with a wall of raw Environment Canada text (markdown "###" leaked through)
and a long BC evacuation list pushed the map far below the fold. The data is unchanged; it is
re-flowed. Pure helpers are tested directly; route/template wiring is asserted at source level.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from consumer.aurora_map import alert_counts, clean_alert_text  # noqa: E402

ROUTES = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
WEATHER = (ROOT / "consumer" / "templates" / "weather.html").read_text(encoding="utf-8")


def test_clean_text_cuts_at_the_first_markdown_heading():
    raw = "Conditions are favourable for severe thunderstorms.\n\n###\n\nLocal utility outages are possible."
    out = clean_alert_text(raw)
    assert out == "Conditions are favourable for severe thunderstorms."
    assert "#" not in out


def test_a_leading_bare_heading_does_not_blank_the_summary():
    assert clean_alert_text("###\n\nPeriods of heavy rain continue.") == "Periods of heavy rain continue."


def test_empty_or_all_markup_returns_none_not_a_blank_line():
    for bad in (None, "", "   ", "### ### ***", 42):
        assert clean_alert_text(bad) is None


def test_long_text_truncates_on_a_word_boundary_with_an_ellipsis():
    out = clean_alert_text("word " * 100, limit=50)
    assert out.endswith("…") and len(out) <= 51
    assert not out[:-1].endswith("wor")  # never mid-word


def test_counts_use_the_real_severity_field_only():
    c = alert_counts(5, ["Extreme", "severe", "Moderate", None, "Minor"])
    assert c == {"total": 5, "severe": 2}


def test_counts_tolerate_missing_input():
    assert alert_counts(0, None) == {"total": 0, "severe": 0}
    assert alert_counts(None, []) == {"total": 0, "severe": 0}


def test_total_comes_from_its_own_query_not_the_limited_list():
    # The shown list is LIMIT 20; a header built from len(list) would under-report.
    assert "alert_counts(len(_alert_sev), _alert_sev)" in ROUTES
    assert "alert_summary=alert_summary" in ROUTES


def test_route_attaches_a_cleaned_summary_to_every_alert():
    assert '_al["summary"] = clean_alert_text(' in ROUTES


def test_template_renders_the_clean_summary_never_the_raw_description():
    assert "al.summary" in WEATHER
    assert "al.description" not in WEATHER


def test_header_states_total_and_severe_and_the_cap_honestly():
    assert "alert_summary.total" in WEATHER and "alert_summary.severe" in WEATHER
    assert "most severe" in WEATHER  # says so when the list is capped


def test_evacuations_are_folded_but_still_present():
    assert '<details class="wtf-wx-evacpanel wtf-wx-evacfold"' in WEATHER
    assert "</details>" in WEATHER
    # counts are visible while folded, and every item is still rendered inside
    assert "active_evacuations_naad|length" in WEATHER and "active_evacuations_bc|length" in WEATHER
    assert "for ev in active_evacuations_bc" in WEATHER


def test_alert_strip_scrolls_horizontally():
    assert "overflow-x:auto" in WEATHER
