"""/parties cost + floor-crossing panel: the helper's rules and the template's honesty text.

The numbers come from parliament.v_mp_expenses_by_party (migrations 095-097). What these tests pin is what the page
may and may not claim: complete calendar years only, 'Unattributed' kept as its own row, retired MPs' share shown, and
a failing/missing view hiding the panel instead of 500-ing /parties.
"""
import re
import sys
import types
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "consumer" / "templates"
SRC = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")


def _load_helpers():
    """Exec only the cost-panel helpers out of routes.py (importing routes needs the whole app)."""
    m = re.search(r"^_PARTY_COST_CACHE: dict.*?(?=^@bp\.get\(\"/parties\"\))", SRC, re.S | re.M)
    assert m, "party cost helpers not found in routes.py"
    ns = {"os": __import__("os"), "time": __import__("time"), "text": lambda s: s}
    exec(m.group(0), ns)
    return ns


class _Res:
    def __init__(self, rows=None, scalar=0):
        self._r, self._s = rows or [], scalar

    def mappings(self):
        return self

    def all(self):
        return self._r

    def scalar(self):
        return self._s


class _Conn:
    def __init__(self, results):
        self.results = list(results)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *_):
        return self.results.pop(0)


def _fake_db(results):
    class _E:
        def begin(self):
            return _Conn(results)
    return lambda: _E()


def _rows(year, party, amt, mps, retired=0):
    return {"yr": year, "party": party, "amt": amt, "mps": mps, "retired": retired}


def test_only_complete_years_and_unattributed_last():
    ns = _load_helpers()
    by = [_rows(2019, "Liberal", 6_000_000, 100, 600_000), _rows(2019, "Conservative", 8_000_000, 90),
          _rows(2019, "Unattributed", 9_000_000, 3), _rows(2020, "Liberal", 1_000_000, 100)]
    qs = [{"yr": 2019, "q": 4}, {"yr": 2020, "q": 1}]  # 2020 is partial -> excluded
    cross = [{"from_party": "Conservative", "to_party": "Liberal", "n": 2}]
    ns["_db"] = _fake_db([_Res(by), _Res(qs), _Res(cross), _Res(scalar=2)])
    p = ns["_party_cost_panel"]()
    assert p["years"] == [2019] and p["latest"] == 2019
    assert [r["party"] for r in p["rows"]] == ["Conservative", "Liberal", "Unattributed"]  # by size, Unattributed last
    lib = p["rows"][1]
    assert lib["total"] == "$6.0M" and lib["retired_share"] == "10%" and lib["per_mp"] == "$60K"
    assert p["crossings"] == [{"from": "Conservative", "to": "Liberal", "n": 2}] and p["n_crossings"] == 2
    assert p["years_cols"] == [("2019", "num")]


def test_a_missing_view_hides_the_panel_not_the_page():
    ns = _load_helpers()

    class _Boom:
        def begin(self):
            raise RuntimeError("relation does not exist")
    ns["_db"] = lambda: _Boom()
    p = ns["_party_cost_panel"]()
    assert p["rows"] == [] and p["years"] == []


def test_no_complete_year_shows_nothing():
    ns = _load_helpers()
    ns["_db"] = _fake_db([_Res([_rows(2020, "Liberal", 1, 1)]), _Res([{"yr": 2020, "q": 2}]), _Res([]), _Res(scalar=0)])
    assert ns["_party_cost_panel"]()["rows"] == []


def test_fmt_m():
    f = _load_helpers()["_fmt_m"]
    assert f(0) == "—" and f(None) == "—" and f(845_000) == "$845K" and f(1_234_567) == "$1.2M"


def _render(party_costs):
    base = "{% block content %}{% endblock %}"
    env = jinja2.Environment(loader=jinja2.DictLoader({
        "base.html": base,
        "parties.html": (TPL / "parties.html").read_text(encoding="utf-8"),
        "_archetypes.html": (TPL / "_archetypes.html").read_text(encoding="utf-8"),
    }), autoescape=True)
    # Render only the cost section: lift it out so the test does not need the whole election bundle.
    t = (TPL / "parties.html").read_text(encoding="utf-8")
    start = t.index("{% if party_costs and party_costs.rows %}")
    end = t.index("How parties are matched across elections")
    end = t.rfind("<p class=\"wtf-pt-note\">", 0, end)
    section = t[start:end]
    macro_src = (TPL / "_archetypes.html").read_text(encoding="utf-8")
    macro = macro_src[macro_src.index("{% macro data_table"):macro_src.index("{%- endmacro %}", macro_src.index("{% macro data_table")) + 15]
    return env.from_string(macro + section).render(party_costs=party_costs)


def test_template_renders_honesty_text_and_rows():
    panel = {"years": [2019], "years_cols": [("2019", "num")], "latest": 2019, "n_crossings": 1,
             "rows": [{"party": "Liberal", "cells": ["$6.0M"], "total": "$6.0M", "retired_share": "10%", "per_mp": "$60K"}],
             "crossings": [{"from": "Conservative", "to": "Liberal", "n": 1}]}
    html = _render(panel)
    assert "the party the MP sat for in that quarter" in html
    assert "after</em> an MP left office" in html and "Complete calendar years only" in html
    # headers are deliberately SHORT: 'Retired MPs' share' + 'Per MP, <year>' made the table 13 columns wide and clipped the
    # last column at 1280px (seen in a P.R.O.B.E. screenshot, 2026-10-07). The year and the meaning live in the hint text.
    assert "Unattributed" in html and "Per MP" in html and "Retired" in html
    assert "Retired MPs\u2019 share" not in html and "Per MP, 2019" not in html
    assert "cost per MP in 2019" in html and "no longer sitting" in html
    assert "Conservative → Liberal" in html and "Floor-crossings since 2000 (1)" in html


def test_template_omits_panel_when_empty():
    assert _render({"rows": []}).strip() == ""


def test_both_render_calls_pass_party_costs():
    body = SRC[SRC.index('@bp.get("/parties")'):]
    body = body[:body.index("\n@bp.", 10)]
    assert body.count("party_costs=_party_cost_panel()") == 2
