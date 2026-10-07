"""/cost: Senate expenses by caucus. Same honesty rules as the House panel, plus one deliberate fold that must be printed.

Rules pinned here: only COMPLETE years (4 quarters), the 2016-17 'Non-affiliated (...)' transition labels fold into
'Non-affiliated', ISG/CSG/PSG are expanded, 'Unattributed' sorts last and is never folded away, a missing view hides the panel.
"""
import re
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
TPL = (ROOT / "consumer" / "templates" / "cost.html").read_text(encoding="utf-8")


def _ns():
    a = re.search(r"^_PARTY_COST_CACHE: dict.*?(?=^def _party_cost_panel)", SRC, re.S | re.M).group(0)       # _fmt_m + TTL
    b = re.search(r"^_CAUCUS_COST_CACHE: dict.*?(?=^@bp\.get\(\"/cost\"\))", SRC, re.S | re.M).group(0)
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


def _r(yr, caucus, amt, sen, retired=0):
    return {"yr": yr, "caucus": caucus, "amt": amt, "senators": sen, "retired": retired}


def test_complete_years_fold_expansion_and_unattributed_last():
    ns = _ns()
    by = [_r(2023, "ISG", 4_000_000, 40, 400_000), _r(2023, "Conservative", 1_000_000, 17),
          _r(2023, "Unattributed", 50_000, 2), _r(2024, "ISG", 4_200_000, 42), _r(2025, "ISG", 1, 1)]
    qs = [{"yr": 2023, "q": 4}, {"yr": 2024, "q": 4}, {"yr": 2025, "q": 2}]     # 2025 partial -> excluded
    ns["_db"] = _db([_Res(by), _Res(qs)])
    p = ns["_caucus_cost_panel"]()
    assert p["years"] == [2023, 2024] and p["latest"] == 2024
    assert [r["caucus"] for r in p["rows"]] == ["Independent Senators Group", "Conservative", "Unattributed"]
    isg = p["rows"][0]
    assert isg["total"] == "$8.2M" and isg["retired_share"] == "5%" and isg["per_senator"] == "$100K"
    assert p["rows"][1]["cells"][1] == "—"  # no 2024 row for that caucus -> a dash, never a zero


def test_the_fold_is_done_in_sql_and_the_labels_are_named():
    body = SRC[SRC.index("def _caucus_cost_panel"):]
    body = body[:body.index('@bp.get("/cost")')]
    assert "LIKE 'Non-affiliated (%'" in body and "THEN 'Non-affiliated'" in body
    assert "count(DISTINCT senator_id)" in body          # distinct senators are counted AFTER the fold, not summed across labels


def test_a_missing_view_hides_the_panel_not_the_page():
    ns = _ns()

    class _Boom:
        def begin(self):
            raise RuntimeError("relation does not exist")
    ns["_db"] = lambda: _Boom()
    assert ns["_caucus_cost_panel"]()["rows"] == []


def _render(panel):
    t = TPL[TPL.index("{% if caucus_costs and caucus_costs.rows %}"):TPL.index('  <div>\n    <a class="cost-cta"')]
    return jinja2.Environment(autoescape=True).from_string(t).render(caucus_costs=panel)


PANEL = {"years": [2023, 2024], "latest": 2024, "years_cols": [],
         "rows": [{"caucus": "Independent Senators Group", "cells": ["$4.0M", "$4.2M"], "total": "$8.2M",
                   "retired_share": "5%", "per_senator": "$100K"}]}


def test_template_states_the_limits_and_the_fold():
    html = _render(PANEL)
    assert "<th>2023</th><th>2024</th>" in html and "Independent Senators Group" in html and "Per senator" in html
    assert "salaries are not included here" in html and "third quarter of 2016" in html
    assert "counted under Non-affiliated" in html and "in that quarter" in html


def test_template_omits_the_panel_when_empty_and_the_route_wires_it():
    assert _render({"rows": []}).strip() == "" and _render(None).strip() == ""
    body = SRC[SRC.index("def cost_of_parliament"):]
    body = body[:body.index("\ndef ", 10)]
    assert "caucus_costs=_caucus_cost_panel()" in body and "party_costs=_party_cost_panel()" in body
