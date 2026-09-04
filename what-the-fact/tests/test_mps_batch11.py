"""Regression coverage for /mps batch 11 additions (2026-09-04):
House + Senate client-side search/sort, the seats-by-province panel, the
senator retirement-wave chart, and the "what coverage counts are not"
methodology panel — all computed from data mps_listing() already fetches,
no new query. Route logic is source-inspected (per test_mp_hero_links.py's
convention) rather than executed against a live DB.

Deliberately NOT covered here: the interactive D3 riding-boundary map and
a postal-code geocoder for the Ridings tab — still deferred (no boundary
geometry or geocoder exists on this platform; the tab already documents
the gap in its own copy, unchanged by this batch). Also deliberately NOT
built: a cross-chamber "same bill, both chambers" tracker. Checked live —
bill_number IS a real, session-scoped joinable key between
parliament.bills and parliament.senate_votes when both are restricted to
session='45-1' (13 of 39 current-session House bills also carry a Senate
vote, titles agree on both sides) — so a join exists. What does NOT exist
is a "this is the bill's final/passage result" column: a bill_number can
carry several House vote rows (2nd reading, report stage, time allocation,
3rd reading...) and picking one to represent "the House's position" is an
editorial judgment call, not a mechanical join. Left as a dedicated
follow-up rather than guessed at here.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _mps_listing_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def mps_listing")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


_BASE_CTX = dict(
    parties=[], provinces=[], party_filter="all", province_filter="ALL",
    source_count=46,
)


def _render(mps=None, senators=None, total_seats=0, retirement_wave=None,
            max_retirement_count=0, senators_missing_dob=0, province_seats=None):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("mps.html").render(
        mps=mps or [], senators=senators or [], total_seats=total_seats,
        retirement_wave=retirement_wave or [], max_retirement_count=max_retirement_count,
        senators_missing_dob=senators_missing_dob, province_seats=province_seats or [],
        **_BASE_CTX,
    )


def _mp(slug, name, party="Liberal", party_colour="#d71920", riding_name="Test Riding",
        province_code="ON", photo_url=None, cabinet_role=None, mention_count=0):
    return {
        "slug": slug, "name": name, "party": party, "party_colour": party_colour,
        "riding_name": riding_name, "province_code": province_code,
        "photo_url": photo_url, "twitter": None, "cabinet_role": cabinet_role,
        "vote_count": 0, "mention_count": mention_count,
    }


def _senator(slug, name, caucus="ISG", province="Ontario", appointed_at="2016-01-01",
             retirement_year=2040):
    return {
        "slug": slug, "name": name, "given_name": name.split()[0],
        "family_name": name.split()[-1], "caucus": caucus, "province": province,
        "photo_url": None, "profile_url": None, "appointed_at": appointed_at,
        "retirement_year": retirement_year,
    }


# --- Template renders, given data mps_listing() would hand it -------------

def test_empty_page_does_not_crash():
    html = _render()
    assert "Members of Parliament" in html


def test_house_search_and_sort_controls_present():
    html = _render(mps=[_mp("jane-doe", "Jane Doe")])
    assert 'id="hoc-search-input"' in html
    assert 'id="hoc-sort-select"' in html
    assert '<option value="covered">Most covered</option>' in html


def test_senate_search_filter_sort_controls_present():
    html = _render(senators=[_senator("jane-sen", "Jane Senator")])
    assert 'id="sen-search-input"' in html
    assert 'id="sen-caucus-filter"' in html
    assert '<option value="retiring">Retiring soonest</option>' in html
    assert '<option value="tenure">Longest serving</option>' in html


def test_senate_caucus_filter_options_come_from_the_real_groupby_not_a_hardcoded_list():
    senators = [_senator("a", "A Name", caucus="ISG"),
                _senator("b", "B Name", caucus="C")]
    html = _render(senators=senators)
    assert "<option value=\"ISG\">ISG (1)</option>" in html
    assert "<option value=\"C\">C (1)</option>" in html


def test_senate_most_covered_sort_is_not_offered():
    # No article_mp_tags-equivalent table exists for senators (checked
    # live: wtf.article_mp_tags is MP-only) — offering the option would be
    # a control that silently does nothing when picked.
    html = _render(senators=[_senator("a", "A")])
    start = html.index('id="sen-sort-select"')
    select_html = html[start:html.index("</select>", start)]
    assert "covered" not in select_html


def test_methodology_panel_present_on_hoc_tab():
    html = _render(mps=[_mp("jane-doe", "Jane Doe", mention_count=3)])
    assert "What the coverage counts are not" in html
    assert "measures the job, not the person" in html


def test_seats_by_province_panel_renders_real_counts_sorted_desc():
    province_seats = [
        {"code": "ON", "name": "Ontario", "count": 120},
        {"code": "QC", "name": "Quebec", "count": 75},
    ]
    html = _render(province_seats=province_seats)
    assert "Seats by Province" in html
    on_idx = html.find("Ontario")
    qc_idx = html.find("Quebec")
    assert 0 <= on_idx < qc_idx, "Ontario (120) must render before Quebec (75) — desc by count"
    assert ">120<" in html
    assert ">75<" in html


def test_seats_by_province_panel_absent_when_no_data():
    html = _render(province_seats=[])
    assert "Seats by Province" not in html


def test_retirement_wave_chart_renders_year_and_count():
    wave = [{"year": 2027, "count": 3}, {"year": 2028, "count": 0}, {"year": 2029, "count": 5}]
    html = _render(retirement_wave=wave, max_retirement_count=5, senators_missing_dob=2,
                    senators=[_senator("a", "A")] * 3)
    assert "Forced Turnover" in html
    assert ">2027<" in html
    assert ">2029<" in html
    assert "2027" in html and "2029" in html and "–" in html
    # a real gap year (0 retirements that calendar year) must still render
    # as a bar, not be skipped — that is why routes.py fills every year in
    # the span, not just the years with a retirement. Count only inside the
    # rendered chart markup, not the <style> block (which also mentions the
    # class name in its selectors).
    chart_start = html.index('class="rw-chart"')
    chart_html = html[chart_start:html.index("</div>\n  <div class=\"rw-note\"", chart_start)]
    assert chart_html.count('class="rw-bar-col"') == 3


def test_retirement_wave_missing_dob_disclosed_honestly():
    html = _render(retirement_wave=[{"year": 2030, "count": 1}], max_retirement_count=1,
                    senators_missing_dob=3, senators=[_senator("a", "A")] * 4)
    assert "not on record" in html
    assert "3" in html.split("not on record")[0][-15:]


def test_retirement_wave_empty_does_not_crash_and_is_honest():
    html = _render(retirement_wave=[], max_retirement_count=0, senators=[])
    assert "No senator on record has a date of birth to chart." in html


def test_riding_az_nav_present():
    html = _render(mps=[_mp("jane-doe", "Jane Doe")])
    assert 'id="rd-az-nav"' in html


# --- Route logic, source-inspected per house convention (no live DB call) -

_ROUTE_BODY = _mps_listing_route_body()


def test_retirement_year_computed_as_dob_year_plus_75():
    assert "_dob.year + 75" in _ROUTE_BODY


def test_retirement_wave_fills_gap_years_not_just_years_with_a_retirement():
    assert "for y in range(_yr_lo, _yr_hi + 1)" in _ROUTE_BODY


def test_date_of_birth_is_dropped_from_the_senators_payload_sent_to_the_template():
    # The roster page's JSON/HTML has no reason to ship every sitting
    # senator's exact birthdate to the browser just to draw a bar chart.
    assert 'if k != "date_of_birth"' in _ROUTE_BODY


def test_senators_missing_dob_is_counted_not_silently_dropped():
    assert "senators_missing_dob" in _ROUTE_BODY


def test_province_seats_sorted_by_count_descending():
    assert "reverse=True" in _ROUTE_BODY


def test_province_seats_computed_from_the_same_filtered_mps_list_not_a_new_query():
    assert "for mp in mps:" in _ROUTE_BODY
    # unchanged from before this batch — confirms no new query was added
    assert _ROUTE_BODY.count("c.execute(") == 5
