"""Regression coverage for /cross-watch's Batch 11 design-integration pass
(2026-09-04): the #cw-stats aggregate row, the six-register legend, the
methodology caution panel, an informational (non-gating) subscriber note,
server-side type/min-register filters, and footer cross-links.

Two kinds of test, matching the house pattern in test_owners_concentration_stats.py
(template rendering) and test_mp_hero_links.py (route source-inspection):

1. Template tests render cross_watch.html directly via the Jinja harness with
   synthetic `entities` / `top_entities`, proving the new markup is correct
   independent of the database.
2. Route tests read consumer/routes.py as TEXT and assert the filtering logic
   is present verbatim, then re-execute that exact snippet inline (copied, not
   imported — routes.py is not safely importable without a live app/DB context,
   same reasoning as test_mp_hero_links.py) to prove the algorithm is correct.

Deliberately NOT covered (see routes.py's cross_watch_explorer docstring and
the template's own top-of-block comment for the reasoning):
- A "min=1 / any register" option — the cached default population is already
  pre-filtered to >=2 products by the underlying query (migration 075's
  snapshot), so offering "any register" would either silently show the same
  2+ set or require a second expensive (~5.8s, measured live) query.
- The inline #cw-detail entity-expansion / accountability-chain view — a
  dedicated build on the scale of /chain, not a template-polish item.
- The card-based per-entity layout — the flat row list stays (low-risk
  styling pass only).
- Any new is_subscriber-gated content — see test_page_renders_identically_
  regardless_of_subscriber_status below, which guards against scope creep.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _render(entities, top_entities, q="", type_filter="", min_filter="2",
            source_count=46, is_subscriber=False):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("cross_watch.html").render(
        entities=entities, top_entities=top_entities, q=q,
        type_filter=type_filter, min_filter=min_filter,
        source_count=source_count, is_subscriber=is_subscriber,
    )


def _entity(id, name, etype, products, mentions):
    return {"id": id, "name": name, "type": etype, "products": products, "mentions": mentions}


_TOP = [
    _entity(1, "University Of Everywhere", "organization", ["civic-watch", "gov-watch", "wtf"], 761),
    _entity(2, "Jane Politician", "person", ["gov-watch", "wtf"], 42),
    _entity(3, "Regional Co-op", "organization", ["civic-watch", "gov-watch"], 15),
]


def _cross_watch_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def cross_watch_explorer")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


# ── #cw-stats aggregate row (template) ──────────────────────────────────────

def test_stats_row_counts_top_entities_not_filtered_results():
    # entities (the filtered/search view) is deliberately SMALLER than
    # top_entities (the canonical cache-backed population) here — the stats
    # row must describe top_entities, not whatever is currently filtered/shown.
    html = _render(entities=[_TOP[0]], top_entities=_TOP)
    idx = html.find("Cross-linked entities")
    snippet = html[idx:idx + 200]
    assert ">3<" in snippet, "stats must count top_entities (3), not the filtered entities (1)"


def test_most_cross_linked_reports_the_real_max_span():
    html = _render(entities=_TOP, top_entities=_TOP)
    idx = html.find("Most cross-linked")
    snippet = html[idx:idx + 200]
    # University Of Everywhere spans 3 registers — the highest in _TOP.
    assert ">3<" in snippet


def test_in_3plus_registers_counts_only_real_3plus_spans():
    html = _render(entities=_TOP, top_entities=_TOP)
    idx = html.find("In 3+ registers")
    snippet = html[idx:idx + 200]
    # Only the first entity (3 registers) qualifies; the other two have 2.
    assert ">1<" in snippet


def test_empty_top_entities_stats_do_not_crash():
    html = _render(entities=[], top_entities=[])
    assert "Cross-linked entities" in html
    assert ">0<" in html[html.find("Cross-linked entities"):html.find("Cross-linked entities") + 200]


# ── six-register legend ──────────────────────────────────────────────────────

def test_legend_lists_all_six_registers_with_descriptions():
    html = _render(entities=_TOP, top_entities=_TOP)
    for label in ["Gov", "Civic", "Legal", "Market", "News", "Parliament"]:
        assert label in html
    assert "CanadaBuys" in html
    assert "CanLII" in html


def test_legend_marks_unlinked_registers_as_not_yet_linked():
    # Measured live against the wtf DB (2026-09-04): shared.entity_mentions has
    # ZERO rows with product='market-watch' or product='parliament' (only
    # gov-watch / civic-watch / wtf / legal-watch appear). Claiming these two
    # are live registers on equal footing with the other four would be a
    # fabrication (hard rule #1) — the legend must say so.
    html = _render(entities=_TOP, top_entities=_TOP)
    assert html.count("not yet linked") == 2


def test_legend_news_description_uses_the_real_source_count():
    html = _render(entities=_TOP, top_entities=_TOP, source_count=46)
    idx = html.find("News")
    snippet = html[idx:idx + 300]
    assert "46 Canadian outlets" in snippet


# ── methodology caution panel ────────────────────────────────────────────────

def test_methodology_panel_present():
    html = _render(entities=_TOP, top_entities=_TOP)
    assert "Read this page carefully" in html
    assert "no score and no ranking" in html


# ── subscriber note is informational only — no new gating ──────────────────

def test_page_renders_identically_regardless_of_subscriber_status():
    # Hard rule #2: never add new is_subscriber gating to previously-ungated
    # content. The core content (stats + legend + entity list) must be
    # byte-identical whether or not the viewer is a subscriber.
    html_free = _render(entities=_TOP, top_entities=_TOP, is_subscriber=False)
    html_sub = _render(entities=_TOP, top_entities=_TOP, is_subscriber=True)
    assert html_free == html_sub


def test_subscriber_note_is_informational_text_not_a_gate():
    html = _render(entities=_TOP, top_entities=_TOP)
    assert "Starter+" in html
    # It must not wrap the entity list or the stats in a conditional — proven
    # by the identical-output test above; this just confirms the wording exists.
    assert "free to everyone" in html


# ── footer cross-links ───────────────────────────────────────────────────────

def test_footer_links_to_officers_lobbying_and_appointments():
    html = _render(entities=_TOP, top_entities=_TOP)
    assert 'href="/parliament/officers"' in html
    assert 'href="/lobbying"' in html
    assert 'href="/gic"' in html


# ── type / min-register filter controls (selected-state rendering) ─────────

def test_type_filter_select_defaults_to_any():
    html = _render(entities=_TOP, top_entities=_TOP, type_filter="")
    idx = html.find('name="type"')
    snippet = html[idx:idx + 400]
    assert '<option value="" selected>' in snippet


def test_type_filter_select_marks_organization_selected():
    html = _render(entities=_TOP, top_entities=_TOP, type_filter="organization")
    idx = html.find('name="type"')
    snippet = html[idx:idx + 400]
    assert '<option value="organization" selected>' in snippet
    assert '<option value="person" selected>' not in snippet


def test_min_filter_select_defaults_to_two():
    html = _render(entities=_TOP, top_entities=_TOP, min_filter="2")
    idx = html.find('name="min"')
    snippet = html[idx:idx + 300]
    assert '<option value="2"  selected>' in snippet or '<option value="2" selected>' in snippet


def test_min_filter_select_marks_three_selected():
    html = _render(entities=_TOP, top_entities=_TOP, min_filter="3")
    idx = html.find('name="min"')
    snippet = html[idx:idx + 300]
    assert '<option value="3" selected>' in snippet


def test_no_min_1_any_register_option_offered():
    # Deliberately deferred — see module docstring.
    html = _render(entities=_TOP, top_entities=_TOP)
    idx = html.find('name="min"')
    snippet = html[idx:html.find("</select>", idx)]
    assert 'value="1"' not in snippet


def test_shown_count_reflects_the_filtered_entities_list():
    html = _render(entities=[_TOP[0]], top_entities=_TOP)
    assert "1 shown" in html


# ── route-level filtering logic (source-inspection + inline re-execution) ──

def test_route_defines_type_and_min_query_params():
    body = _cross_watch_route_body()
    assert 'type_filter = (request.args.get("type") or "").strip().lower()' in body
    assert 'min_filter = request.args.get("min") or "2"' in body


def test_route_rejects_invalid_type_and_min_values():
    body = _cross_watch_route_body()
    assert 'if type_filter not in ("person", "organization"):' in body
    assert 'if min_filter not in ("2", "3"):' in body


def test_route_applies_min_required_floor_to_every_branch_including_search():
    # This is the correctness fix bundled with the filter: previously the ?q=
    # search branch had NO product-count floor at all, so a single-product
    # name could appear on a page titled "entities resolved across the Watch
    # Series". The filter must be applied AFTER the if/else, not inside only
    # one branch.
    body = _cross_watch_route_body()
    entities_idx = body.index('entities = [e for e in entities if len(e["products"]) >= min_required]')
    if_q_idx = body.index("if q:")
    else_idx = body.index("else:", if_q_idx)
    top_entities_assign_idx = body.index("entities = top_entities", else_idx)
    assert entities_idx > if_q_idx
    assert entities_idx > top_entities_assign_idx, (
        "the min_required filter must be applied AFTER both the q= and the "
        "default branch, not nested inside just one of them"
    )


def test_min_required_filter_logic_drops_single_product_entities_by_default():
    # Re-executes the EXACT snippet asserted present above, against synthetic
    # data, to prove the algorithm (not just its presence) is correct.
    entities = [
        {"id": 1, "type": "organization", "products": ["gov-watch"]},
        {"id": 2, "type": "organization", "products": ["gov-watch", "wtf"]},
        {"id": 3, "type": "person", "products": ["gov-watch", "wtf", "civic-watch"]},
    ]
    min_required = 2  # the default, matching `min_filter = request.args.get("min") or "2"`
    entities = [e for e in entities if len(e["products"]) >= min_required]
    assert [e["id"] for e in entities] == [2, 3]


def test_min_required_filter_logic_with_three_drops_two_span_entities():
    entities = [
        {"id": 1, "type": "organization", "products": ["gov-watch"]},
        {"id": 2, "type": "organization", "products": ["gov-watch", "wtf"]},
        {"id": 3, "type": "person", "products": ["gov-watch", "wtf", "civic-watch"]},
    ]
    min_required = 3
    entities = [e for e in entities if len(e["products"]) >= min_required]
    assert [e["id"] for e in entities] == [3]


def test_type_filter_logic_matches_the_route_snippet():
    body = _cross_watch_route_body()
    assert 'entities = [e for e in entities if e["type"] == type_filter]' in body
    entities = [
        {"id": 1, "type": "person", "products": []},
        {"id": 2, "type": "organization", "products": []},
    ]
    type_filter = "organization"
    entities = [e for e in entities if e["type"] == type_filter]
    assert [e["id"] for e in entities] == [2]


def test_top_entities_is_always_computed_even_on_the_search_branch():
    # top_entities must be computed BEFORE the `if q:` branch, so the stats
    # row is populated even while a search is active.
    body = _cross_watch_route_body()
    top_idx = body.index("top_entities = _crosswatch_top(c, SH)")
    if_q_idx = body.index("if q:")
    assert top_idx < if_q_idx
