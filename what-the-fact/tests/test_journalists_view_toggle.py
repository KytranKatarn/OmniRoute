"""Cards/Table toggle on /journalists (Claude Design port). Jinja-only render,
no DB — same DictLoader pattern as test_journalists_lean_subline.py."""
from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"
ROWS = [
    {"id": 7, "canonical_name": "Ann <b>Lee</b>", "article_count": 1,
     "outlet_name": "CBC", "outlet_lean": "center-left"},
    {"id": 8, "canonical_name": "Bo Chan", "article_count": 12,
     "outlet_name": None, "outlet_lean": None},
]


def _render(journalists):
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}), FileSystemLoader(str(TPL_DIR))]))
    return env.get_template("journalists.html").render(
        journalists=journalists, q="", total=len(journalists), source_count=46)


def test_both_views_rendered_with_same_rows():
    html = _render(ROWS)
    assert 'id="jr-cards"' in html and 'id="jr-table"' in html
    assert html.count('href="/journalist/7"') == 2  # card + table row
    assert html.count('href="/journalist/8"') == 2


def test_table_is_hidden_by_default_so_no_js_means_cards():
    html = _render(ROWS)
    assert '<div class="wtf-a-tblwrap" id="jr-table" hidden>' in html
    assert 'id="jr-view" hidden' in html  # toggle only appears once JS runs


def test_table_never_scores_the_writer():
    html = _render(ROWS)
    assert "Median band" not in html and "median band" not in html
    assert "<th>Outlet lean</th>" in html


def test_names_are_escaped_and_absent_values_are_dashes():
    html = _render(ROWS)
    assert "<b>Lee</b>" not in html and "&lt;b&gt;Lee" in html
    assert "<td>—</td>" in html


def test_no_toggle_when_empty():
    assert 'id="jr-view"' not in _render([])


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
