"""Regression coverage for /sources — MIN_N honesty floor, real per-outlet
fact-checked count, search + sort, and the footer methodology note
(2026-09-04, batch 11).

Deliberately NOT built here (see routes.py's `sources_list` docstring for the
measured reasons): the mockup's 6 clickable stat-tile filters, the up-to-3
compare tray, and the visual band-range scale bar (all need real client-side
interactive state), and the mockup's "filed first" metric (real, computable
data via articles.cluster_id + published_at, but measured 400ms-3.5s as a
live query with no supporting index for that access pattern — a scheduled/
materialized aggregate, not a page-load query on a public directory page).

Follows the house pattern from test_mp_hero_links.py (source-inspection of
the route body via slicing, since we don't execute against a live DB from
inside a test) and test_owners_concentration_stats.py (Jinja render via
ChoiceLoader/DictLoader/FileSystemLoader, no live Flask app).
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _sources_block() -> str:
    """Everything this batch touches in routes.py: the MIN_N constant, the
    sort allowlist, the cached fact-checked-count helper, and the route
    itself. Bounded to the NEXT route so an assertion here can never pass by
    accidentally matching unrelated code elsewhere in this 7000+ line file."""
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("# ── /sources — MIN_N honesty floor")
    end = src.index('\n@bp.get("/source/<slug>")', start)
    return src[start:end]


def _render(sources, q="", sort="articles", min_n=5):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    return env.get_template("sources.html").render(
        sources=sources, q=q, sort=sort, min_n=min_n,
    )


def _outlet(name, **overrides):
    base = {
        "id": 1, "slug": "test-outlet", "name": name, "url": None,
        "bias_lean": None, "owner_name": None, "owner_type": None,
        "avg_score": None, "rolling_band": None, "total_articles": 100,
        "articles_7d": 3, "below_min_n": False, "fact_checked_count": 0,
    }
    base.update(overrides)
    return base


# ── SQL / logic source-inspection (no live DB — per house test convention) ──

def test_min_n_floor_is_five_and_gates_on_scored_not_total_articles():
    body = _sources_block()
    assert "_SOURCES_MIN_N = 5" in body
    # The gate must read the ROLLING-WINDOW scored count, never the lifetime
    # total_articles figure — an outlet can have thousands of total articles
    # while the current scoring window holds only one or two.
    assert "scored_article_count" in body
    assert 'int(d.get("scored_article_count") or 0) < _SOURCES_MIN_N' in body
    assert "COALESCE(obs.article_count, 0) AS scored_article_count" in body


def test_search_filters_by_name_with_a_bound_parameter():
    body = _sources_block()
    assert "s.name ILIKE :q" in body
    assert 'params["q"] = f"%{q}%"' in body


def test_sort_is_an_allowlist_not_a_raw_column_name():
    body = _sources_block()
    assert '_SOURCES_SORTS = {' in body
    assert '"articles": "total_articles DESC"' in body
    assert '"name": "s.name ASC"' in body
    # Anything outside the allowlist must fall back, never reach the SQL string.
    assert "if sort not in _SOURCES_SORTS" in body


def test_fact_checked_count_is_cached_not_a_per_request_full_table_scan():
    body = _sources_block()
    # The cache dict + TTL pattern that _NAV_SOURCE_CACHE/_ACTIVITY_CACHE use
    # elsewhere in this file for the exact same reason (measured 20-36s
    # uncached whole-table fact_checks aggregates before that fix existed).
    assert "_SOURCES_FC_CACHE" in body
    assert "_SOURCES_FC_CACHE_TTL" in body
    assert "hit[0] > now" in body
    # DISTINCT-first, never a bare COUNT(DISTINCT article_id) GROUP BY — the
    # latter measured 2-3.5s live because fact_checks has no unique
    # constraint on article_id (up to 8 claims per article).
    assert "SELECT DISTINCT article_id FROM {S}.fact_checks" in body


def test_no_paywall_gate_added_to_the_route():
    # /sources has never been gated. Adding is_subscriber here while closing
    # a polish gap would be a silent monetization change (forbidden by the
    # task's hard rules) — this pins that it never sneaks back in.
    body = _sources_block()
    assert "is_subscriber" not in body


# ── Template rendering — MIN_N honesty label ─────────────────────────────

def test_below_min_n_shows_the_honesty_label_not_a_computed_band():
    sources = [_outlet(
        "Test Outlet Below", below_min_n=True, bias_lean="right",
        rolling_band=None, avg_score=None,
    )]
    html = _render(sources)
    idx = html.find("Test Outlet Below")
    assert idx != -1
    snippet = html[idx:idx + 400]
    assert "Not enough to average" in snippet
    # The band pill for 'right' renders the word "Right" (lean_pill titles
    # the bucket name) — it must not leak through via the bias_lean fallback
    # once below_min_n is set, even though bias_lean is still populated.
    assert "Right" not in snippet


def test_at_or_above_min_n_shows_the_real_band_pill():
    sources = [_outlet(
        "Test Outlet Above", below_min_n=False, rolling_band="left",
    )]
    html = _render(sources)
    idx = html.find("Test Outlet Above")
    snippet = html[idx:idx + 400]
    assert "Not enough to average" not in snippet
    assert "Left" in snippet


def test_unscored_outlet_with_no_band_at_all_shows_unscored_chip():
    sources = [_outlet(
        "Test Outlet Unscored", below_min_n=False, rolling_band=None, bias_lean=None,
    )]
    html = _render(sources)
    idx = html.find("Test Outlet Unscored")
    snippet = html[idx:idx + 400]
    assert "Unscored" in snippet
    assert "Not enough to average" not in snippet


# ── Template rendering — fact-checked count ──────────────────────────────

def test_fact_checked_count_renders_when_positive():
    sources = [_outlet("Test Outlet FC", fact_checked_count=12)]
    html = _render(sources)
    idx = html.find("Test Outlet FC")
    snippet = html[idx:idx + 400]
    assert "12 fact-checked" in snippet


def test_fact_checked_count_omitted_when_zero():
    sources = [_outlet("Test Outlet NoFC", fact_checked_count=0)]
    html = _render(sources)
    idx = html.find("Test Outlet NoFC")
    snippet = html[idx:idx + 400]
    assert "fact-checked" not in snippet


# ── Template rendering — search + sort + empty state ─────────────────────

def test_search_box_is_a_plain_get_form_prefilled_with_q():
    html = _render([_outlet("X")], q="cbc")
    assert '<form method="get" action="/sources"' in html
    assert 'name="q"' in html
    assert 'value="cbc"' in html


def test_sort_segments_render_and_mark_the_active_one():
    html = _render([_outlet("X")], sort="name")
    assert "Most articles" in html
    assert "Name A" in html  # "Name A–Z" — avoid the en-dash in the assertion
    # The active segment carries is-active; inactive ones do not.
    active_idx = html.find("Name A")
    active_snippet = html[max(0, active_idx - 120):active_idx]
    assert "is-active" in active_snippet


def test_sort_param_is_carried_as_a_hidden_field_when_not_the_default():
    html = _render([_outlet("X")], sort="name")
    assert '<input type="hidden" name="sort" value="name">' in html


def test_default_sort_omits_the_hidden_field():
    html = _render([_outlet("X")], sort="articles")
    assert '<input type="hidden" name="sort"' not in html


def test_empty_search_result_shows_a_clear_search_link_no_crash():
    html = _render([], q="zzznotarealoutlet")
    assert "No outlets match" in html
    assert 'href="/sources"' in html


def test_empty_sources_list_does_not_crash_without_a_search():
    html = _render([])
    assert "outlets tracked" in html


# ── Template rendering — footer methodology note ─────────────────────────

def test_footer_methodology_note_explains_min_n_and_the_band_is_a_range():
    html = _render([_outlet("X")], min_n=5)
    normalized = " ".join(html.split())
    assert "Not enough to average" in normalized
    assert "fewer than 5 scored articles" in normalized
    assert "rolling average" in normalized
