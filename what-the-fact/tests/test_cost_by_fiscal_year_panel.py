"""/cost and /parties: House expenses by FISCAL year (FY2010-FY2015, annual reports).

Rules pinned here: the panel is separate from the calendar-year one, fiscal years are labelled FY####, 'Unattributed' sorts
last and is never folded away, an all-members total row closes the table, mid-year party changes are counted and printed,
a missing view hides the panel instead of breaking the page.
"""
import re
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
COST = (ROOT / "consumer" / "templates" / "cost.html").read_text(encoding="utf-8")
PARTIES = (ROOT / "consumer" / "templates" / "parties.html").read_text(encoding="utf-8")


def _ns():
    a = re.search(r"^_PARTY_COST_CACHE: dict.*?(?=^def _party_cost_panel)", SRC, re.S | re.M).group(0)
    b = re.search(r"^_ANNUAL_COST_CACHE: dict.*?(?=^@bp\.get\(\"/parties\"\))", SRC, re.S | re.M).group(0)
    ns = {"os": __import__("os"), "time": __import__("time"), "text": lambda s: s}
    exec(a, ns)
    exec(b, ns)
    return ns


class _Res:
    def __init__(self, rows):
        self._r = rows

    def mappings(self):
        return self

    def all(self):
        return self._r


class _Conn:
    def __init__(self, results):
        self.results = list(results)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *_):
        return self.results.pop(0)


def _db(results):
    class _E:
        def begin(self):
            return _Conn(results)
    return lambda: _E()


def _panel():
    ns = _ns()
    by = [{"fy": 2010, "party": "Conservative", "amt": 68_100_000, "retired": 6_000_000},
          {"fy": 2010, "party": "Unattributed", "amt": 500_000, "retired": 0},
          {"fy": 2010, "party": "NDP", "amt": 18_300_000, "retired": 0},
          {"fy": 2011, "party": "Conservative", "amt": 63_000_000, "retired": 0},
          {"fy": 2011, "party": "NDP", "amt": 16_800_000, "retired": 0}]
    meta = [{"fy": 2010, "n": 200, "changed": 3, "partial": 8}, {"fy": 2011, "n": 190, "changed": 3, "partial": 9}]
    ns["_db"] = _db([_Res(by), _Res(meta)])
    return ns["_annual_cost_panel"]()


def test_rows_are_sorted_unattributed_last_with_a_total_row_and_dashes():
    p = _panel()
    assert p["years"] == [2010, 2011] and p["cols"] == [("FY2010", "num"), ("FY2011", "num")]
    assert [r["party"] for r in p["rows"]] == ["Conservative", "NDP", "Unattributed", "All members"]
    assert p["rows"][2]["cells"][1] == "—"                       # no FY2011 row -> a dash, never a zero
    tot = p["rows"][-1]
    assert tot["is_total"] and tot["cells"][0] == "$86.9M" and tot["total"] == "$166.7M"
    assert p["rows"][0]["retired_share"] == "5%"


def test_changes_and_partial_years_are_counted():
    p = _panel()
    assert p["changed"] == 6 and p["partial"] == 17 and p["members"] == 390


def test_missing_view_hides_the_panel_not_the_page():
    ns = _ns()

    class _Boom:
        def begin(self):
            raise RuntimeError("relation does not exist")
    ns["_db"] = lambda: _Boom()
    assert ns["_annual_cost_panel"]()["rows"] == []


def test_routes_pass_the_panel_to_both_pages():
    assert SRC.count("annual_costs=_annual_cost_panel()") == 3     # /cost + both /parties renders


def test_cost_template_renders_labelled_fiscal_year_table():
    html = jinja2.Environment().from_string(COST[COST.index("{% if annual_costs"):COST.index('<div>\n    <a class="cost-cta"')]).render(
        annual_costs=_panel())
    assert "data-cost-by-fiscal-year" in html and "FY2010" in html and "April to March" in html
    assert "salaries are not included" in html and "6 member-years" in html
    assert html.index("Unattributed") < html.index("All members")


def test_empty_panel_renders_nothing():
    html = jinja2.Environment().from_string(COST[COST.index("{% if annual_costs"):COST.index('<div>\n    <a class="cost-cta"')]).render(
        annual_costs={"rows": []})
    assert "data-cost-by-fiscal-year" not in html


def test_parties_template_has_the_section_inside_the_cost_block():
    assert "data-fiscal-year-costs" in PARTIES
    assert PARTIES.index("data-fiscal-year-costs") > PARTIES.index('id="party-costs"')
