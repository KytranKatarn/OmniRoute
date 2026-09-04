"""Regression coverage for /journalists' outlet+lean subline (2026-09-04,
KB vault_note #304357).

Source-grepped for the route (no live DB in this suite — 42 DB-less errors
is the accepted baseline) + a Jinja render smoke test for the template
(no DB needed, same DictLoader pattern as test_directory_pages.py).

Lean is attributed to the journalist's TOP OUTLET (sources.bias_lean, the
site's existing stable per-source vocabulary), never invented as a
per-journalist score — a byline at one outlet doesn't inherit an individual
bias rating just from writing there.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _journalists_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def journalists_listing")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def _render(journalists):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("journalists.html").render(
        journalists=journalists, q="", total=len(journalists), source_count=46, is_subscriber=True,
    )


def test_route_selects_outlet_name_and_outlet_lean():
    body = _journalists_route_body()
    assert "outlet_name" in body and "outlet_lean" in body
    assert "src.bias_lean AS outlet_lean" in body, (
        "lean must come from sources.bias_lean (the outlet), not a fabricated "
        "per-journalist score"
    )


def test_top_outlet_is_picked_by_article_count_not_arbitrarily():
    body = _journalists_route_body()
    assert "ORDER BY entity_id, n DESC" in body


def test_card_shows_outlet_and_lean_when_known():
    html = _render([{
        "id": 1, "canonical_name": "Jane Doe", "article_count": 12,
        "outlet_name": "CBC News", "outlet_lean": "center-left",
    }])
    assert "12 articles · CBC News" in html
    assert "Center Left" in html
    assert "var(--wtf-center-left)" in html


def test_card_degrades_cleanly_with_no_outlet_data():
    # A journalist with zero visible articles (vc.article_count NULL-coalesced
    # to 0) has no outlet_counts rows either — must not crash or show "None".
    html = _render([{
        "id": 2, "canonical_name": "No Outlet Person", "article_count": 0,
        "outlet_name": None, "outlet_lean": None,
    }])
    assert "No Outlet Person" in html
    assert "None" not in html
    # Scope to the spine span only — the page's own chrome legitimately uses
    # var(--wtf-border) / var(--wtf-font-serif), which a whole-page grep
    # would false-positive on.
    card = html.split('href="/journalist/2"')[1].split("</a>")[0]
    assert "var(--wtf-" not in card


def test_singular_article_count_grammar_unaffected():
    html = _render([{
        "id": 3, "canonical_name": "Solo Byline", "article_count": 1,
        "outlet_name": None, "outlet_lean": None,
    }])
    assert "1 article" in html
    assert "1 articles" not in html
