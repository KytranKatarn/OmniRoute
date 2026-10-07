"""/cost shows House expenses by party. What it must not do: imply salaries are included, or fold Unattributed away."""
import re
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
TPL = (ROOT / "consumer" / "templates" / "cost.html").read_text(encoding="utf-8")

PANEL = {"years": [2023, 2024], "latest": 2024, "years_cols": [], "crossings": [], "n_crossings": 0,
         "rows": [{"party": "Liberal", "cells": ["$7.1M", "$7.4M"], "total": "$14.5M", "retired_share": "3%", "per_mp": "$60K"},
                  {"party": "Unattributed", "cells": ["$0.1M", "—"], "total": "$0.1M", "retired_share": "0%", "per_mp": "—"}]}


def _render(pc):
    t = TPL[TPL.index("{% if party_costs and party_costs.rows %}"):TPL.index('  <div>\n    <a class="cost-cta"')]
    return jinja2.Environment(autoescape=True).from_string(t).render(party_costs=pc)


def test_panel_renders_years_rows_and_the_salary_caveat():
    html = _render(PANEL)
    assert "<th>2023</th><th>2024</th>" in html and "$14.5M" in html and "Per MP, 2024" in html
    assert "salaries are not included here" in html and "The House only, not the Senate" in html
    assert "Unattributed" in html and "never folded in" in html


def test_empty_panel_is_omitted():
    assert _render({"rows": []}).strip() == ""
    assert _render(None).strip() == ""


def test_route_passes_the_panel_and_stays_a_shell():
    body = SRC[SRC.index('def cost_of_parliament'):]
    body = body[:body.index("\ndef ", 10)]
    assert "party_costs=_party_cost_panel()" in body
    assert "data-cost-by-party" in TPL and "data-cost-headline" in TPL  # existing client-rendered sections untouched
