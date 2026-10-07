"""/mp/<slug> serves FORMER members, shows dated party history, and a long expense series labelled by party.

Before: the route filtered `is_current = true`, so every retired MP was a 404 (and ~900 of them were added to the roster
on 2026-10-07); the expense table showed 12 quarters with no party; nothing said an MP had switched parties.
Rendering is tested against stubbed context (no DB) the same way tests/test_mp_hero_links.py does.
"""
from __future__ import annotations

import pathlib
import re
from datetime import date

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


class _Req:
    path = "/mp/x"


def _src() -> str:
    return ROUTES.read_text(encoding="utf-8")


def _route_body() -> str:
    s = _src()
    a = s.index("def mp_profile")
    return s[a:s.index("\n@bp.get", a + 1)]


CTX = dict(votes=[], articles=[], stats={}, total_votes=0, source_count=46, riding_donor_totals=[],
           top_named_donors=[], lobbying_contacts=[], disclosures=[], promises=[], committees=[],
           peer_mps=[], prev_mp=None, next_mp=None, party_history=[], expense_periods=[], is_subscriber=True)


def _render(mp, **over):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": _BASE_STUB}), FileSystemLoader(str(TPL_DIR))]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _Req()
    return env.get_template("mp.html").render(mp=mp, **{**CTX, **over})


def _mp(**kw):
    base = dict(id=7, slug="x", name="Jane Doe", party="Liberal", party_colour="#c00", riding_name="Somewhere",
                province_code="ON", photo_url=None, openparl_url="https://openparliament.ca/politicians/x/",
                hoc_member_id=None, cabinet_role="Minister of Stuff", is_current=True, twitter=None, email=None)
    base.update(kw)
    return base


def _q(i, party="Liberal", attribution="in_term"):
    return dict(period=f"20{10 + i // 4:02d}-Q{i % 4 + 1}", expense_party=party, attribution=attribution,
                travel_cad=1000.0 + i, hospitality_cad=0, contracts_cad=500.0, salaries_cad=2000.0,
                total_cad=3500.0 + i)


# ---- route ------------------------------------------------------------------------------------------------------------
def test_the_lookup_no_longer_filters_to_sitting_members_but_still_404s_an_unknown_slug():
    body = _route_body()
    lookup = body[body.index("FROM parliament.mps WHERE slug = :slug"):][:80]
    assert "is_current = true" not in lookup
    assert "cabinet_role, is_current" in body
    assert "abort(404)" in body[body.index("if not mp_row"):][:60]


def test_prev_next_walks_the_sitting_caucus_only():
    assert 'if mp.get("party") and mp.get("is_current"):' in _route_body()


def test_the_new_queries_live_in_guarded_helpers_not_in_the_swallow_everything_block():
    s = _src()
    for fn in ("_mp_expense_rows", "_mp_party_history"):
        h = s[s.index(f"def {fn}"):]
        h = h[:h.index("\n\n\n")]
        assert "except Exception" in h, f"{fn} must never raise into the page"
    body = _route_body()
    assert "expense_periods = _mp_expense_rows(mp[\"id\"])" in body and "party_history = _mp_party_history(mp[\"id\"])" in body
    assert "FROM parliament.mp_expenses" not in body            # the inline query that a failure would have silenced


def test_expense_helper_reads_the_party_view_newest_first_with_a_house_site_fallback():
    s = _src()
    h = s[s.index("def _mp_expense_rows"):]
    h = h[:h.index("\n\n\n")]
    assert "FROM parliament.v_mp_expenses_by_party" in h and "ORDER BY q_start DESC" in h
    assert "FROM parliament.mp_expenses" in h                   # fallback when 095-097 are not applied


# ---- template ---------------------------------------------------------------------------------------------------------
def test_a_sitting_mp_has_no_former_badge_and_keeps_the_cabinet_role():
    html = _render(_mp())
    assert "Former Member of Parliament" not in html and "Minister of Stuff" in html


def test_a_former_mp_is_badged_and_loses_the_stale_cabinet_role_and_year_to_date_box():
    html = _render(_mp(is_current=False), expense_periods=[_q(i) for i in range(3)])
    assert "Former Member of Parliament" in html and "Minister of Stuff" not in html
    assert "so far" not in html                                  # a year-to-date box is meaningless for a past member


def test_party_history_lists_stints_and_marks_a_floor_crossing():
    hist = [
        dict(party="Liberal", riding="Acadie—Annapolis", start_date=date(2025, 11, 5), end_date=None,
             switched_from="Conservative", gap_days=1),
        dict(party="Conservative", riding="West Nova", start_date=date(2019, 10, 21), end_date=date(2025, 4, 28)),
    ]
    html = _render(_mp(), party_history=hist)
    assert "Party and riding history" in html and "switched party 1×" in html
    assert "moved from Conservative" in html and "crossed the floor" in html
    assert html.index("Nov 2025") < html.index("Oct 2019")       # newest first


def test_a_later_return_under_another_banner_is_not_called_a_floor_crossing():
    hist = [dict(party="Liberal", riding="R", start_date=date(2015, 10, 19), end_date=None, switched_from="NDP", gap_days=2600)]
    html = _render(_mp(), party_history=hist)
    assert "crossed the floor" not in html and "returned after 7.1 yrs" in html


def test_no_history_means_no_history_section():
    assert "Party and riding history" not in _render(_mp(), party_history=[])


def test_the_expense_table_shows_party_per_quarter_and_folds_everything_after_twelve():
    rows = [_q(i, party="Conservative" if i < 5 else "Liberal") for i in range(30)]
    html = _render(_mp(), expense_periods=rows)
    assert "(30 quarters)" in html
    assert html.count("<details") == 1 and "Show 18 earlier quarters" in html
    first_table = html[:html.index("<details")]
    assert first_table.count('class="wtf-mp-tr"') == 12 and "Conservative" in html and "Liberal" in html


def test_a_wind_down_quarter_is_tagged_so_a_reader_can_see_it_is_post_service_cost():
    rows = [_q(0, attribution="wind_down")]
    html = _render(_mp(is_current=False), expense_periods=rows)
    assert "wind-down" in html and "after the member left office" in html


def test_twelve_or_fewer_quarters_need_no_fold():
    assert "<details" not in _render(_mp(), expense_periods=[_q(i) for i in range(12)])


def test_the_archive_provenance_is_stated():
    assert "archived reports" in _render(_mp(), expense_periods=[_q(0)])


def test_a_context_without_is_current_is_treated_as_a_sitting_member():
    mp = _mp()
    del mp["is_current"]
    html = _render(mp, expense_periods=[_q(0)])
    assert "Former Member of Parliament" not in html and "Minister of Stuff" in html
