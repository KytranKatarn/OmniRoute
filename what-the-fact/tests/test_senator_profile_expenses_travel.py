"""/senator/<slug>: quarterly expenses, an international/domestic/unclassified travel split, and delegations flagged so nothing
is counted twice. Rendering is tested against stubbed context (no DB), like tests/test_mp_hero_links.py."""
from __future__ import annotations

import pathlib
from datetime import date

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"


class _Req:
    path = "/senator/x"


def _src():
    return ROUTES.read_text(encoding="utf-8")


def _fn(name):
    s = _src()
    a = s.index(f"def {name}")
    return s[a:s.index("\n\n\n", a)]


def _render(senator, subscriber=True):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block meta %}{% endblock %}{% block content %}{% endblock %}"}),
                                           FileSystemLoader(str(TPL_DIR))]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _Req()
    return env.get_template("senator.html").render(senator=senator, source_count=46, is_subscriber=subscriber)


def _sen(**kw):
    base = dict(id=3, slug="x", name="Doe, Jane", caucus="C", caucus_colour="#3b82f6", caucus_label="Conservative", province="ON",
                photo_url=None, profile_url=None, is_current=True, committees=[], votes=[], expense_periods=[],
                travel=dict(split=dict(intl=(0, 0.0), domestic=(0, 0.0), unclassified=(0, 0.0)), intl_trips=[], delegations=[],
                            delegation_additive_cad=0.0))
    base.update(kw)
    return base


def _q(i):
    return dict(period=f"20{20 + i // 4}-Q{i % 4 + 1}", travel_cad=1000 + i, hospitality_cad=0, contracts_cad=0, office_cad=500,
                living_cad=250, total_cad=1750 + i)


# ---- route ----------------------------------------------------------------------------------------------------------
def test_the_route_loads_expenses_and_travel_through_guarded_helpers():
    body = _fn("senator_profile")
    assert 'senator["expense_periods"] = _senator_expense_rows(senator["id"])' in body
    assert 'senator["travel"] = _senator_travel(senator["id"])' in body
    for fn in ("_senator_expense_rows", "_senator_travel"):
        assert "except Exception" in _fn(fn), f"{fn} must never raise into the page"


def test_unknown_is_international_is_its_own_bucket_in_the_query_mapping():
    h = _fn("_senator_travel")
    assert 'is True else "domestic" if r["is_international"] is False else "unclassified"' in h


def test_only_delegations_not_already_in_own_expenses_are_additive():
    h = _fn("_senator_travel")
    assert 'if d["overlap"] == "not_in_expense_travel"' in h
    assert "e.source = 'iia' AND e.is_foreign" in h              # committee rows carry no per-senator amount


# ---- template -------------------------------------------------------------------------------------------------------
def test_a_senator_with_nothing_shows_no_expense_or_travel_sections():
    html = _render(_sen())
    assert "Expenses by quarter" not in html and "Travel</div>" not in html


def test_quarterly_expenses_render_and_fold_after_twelve():
    html = _render(_sen(expense_periods=[_q(i) for i in range(20)]))
    assert "Expenses by quarter (20 quarters)" in html and "Show 8 earlier quarters" in html
    assert html.count("<details") == 1
    assert "$1,000" in html and "$1,750" in html


def test_twelve_or_fewer_quarters_need_no_fold():
    assert "<details" not in _render(_sen(expense_periods=[_q(i) for i in range(12)]))


def test_the_split_reports_unclassified_separately_and_says_it_is_counted_as_neither():
    tr = dict(split=dict(intl=(2, 5000.0), domestic=(9, 3200.0), unclassified=(4, 1100.0)), intl_trips=[], delegations=[],
              delegation_additive_cad=0.0)
    html = _render(_sen(travel=tr))
    assert "<strong>2</strong> international legs ($5,000)" in html
    assert "<strong>9</strong> domestic ($3,200)" in html
    assert "<strong>4</strong> unclassified ($1,100)" in html and "counted as neither" in html


def test_a_single_international_leg_is_singular():
    tr = dict(split=dict(intl=(1, 700.0), domestic=(0, 0.0), unclassified=(0, 0.0)), intl_trips=[], delegations=[], delegation_additive_cad=0.0)
    assert "<strong>1</strong> international leg " in _render(_sen(travel=tr))


def test_international_trips_table_shows_dates_itinerary_and_cost():
    tr = dict(split=dict(intl=(1, 4200.0), domestic=(0, 0.0), unclassified=(0, 0.0)),
              intl_trips=[dict(trip_start=date(2023, 4, 3), trip_end=date(2023, 4, 7), itinerary="Ottawa - Paris - Ottawa",
                               purpose="Parliamentary meeting", traveller_name="Doe, Jane", traveller_kind="senator", total_cad=4200.0)],
              delegations=[], delegation_additive_cad=0.0)
    html = _render(_sen(travel=tr))
    assert "Ottawa - Paris - Ottawa" in html and "2023-04-03 → 04-07" in html and "$4,200" in html


def test_a_delegation_already_in_own_expenses_is_flagged_and_not_added_to_the_headline():
    tr = dict(split=dict(intl=(0, 0.0), domestic=(0, 0.0), unclassified=(0, 0.0)), intl_trips=[],
              delegations=[dict(event_start=date(2023, 4, 3), event_end=None, body="UIPU", title="IPU Assembly", destination="Manama",
                                cancelled=False, amount_cad=9000.0, overlap="in_expense_travel", source_url="x"),
                           dict(event_start=date(2024, 5, 1), event_end=None, body="CANA", title="NATO PA", destination="Sofia",
                                cancelled=False, amount_cad=6000.0, overlap="not_in_expense_travel", source_url="x")],
              delegation_additive_cad=6000.0)
    html = _render(_sen(travel=tr))
    assert "already in own expenses" in html
    assert "$6,000 paid by the delegation, not in the expenses above" in html
    assert "$15,000" not in html                                 # 9,000 + 6,000 must never be summed


def test_a_cancelled_delegation_is_labelled():
    tr = dict(split=dict(intl=(0, 0.0), domestic=(0, 0.0), unclassified=(0, 0.0)), intl_trips=[],
              delegations=[dict(event_start=date(2023, 4, 3), event_end=None, body="X", title="Trip", destination=None, cancelled=True,
                                amount_cad=100.0, overlap="not_in_expense_travel", source_url="x")], delegation_additive_cad=100.0)
    assert "cancelled" in _render(_sen(travel=tr))


def test_the_detail_is_inside_the_subscriber_gate_like_the_mp_expense_table():
    s = _sen(expense_periods=[_q(0)])
    assert "Expenses by quarter" in _render(s, subscriber=True)
    assert "Expenses by quarter" not in _render(s, subscriber=False)


def test_the_page_still_renders_when_the_travel_key_is_absent():
    s = _sen()
    del s["travel"]
    assert "Doe, Jane" in _render(s)
