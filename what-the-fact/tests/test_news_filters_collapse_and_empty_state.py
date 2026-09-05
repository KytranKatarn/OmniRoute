"""Regression coverage for /news' filters-collapsed toggle + empty-state
(2026-09-05, task #16 remainder).

Batch 11 (test_news_batch11.py) explicitly scoped these out: "Search, sort,
verdict/outlet/quick filter chips, saved/bookmark, the slide-out drawer,
and numbered pager/live-pull all stay OUT of scope... and remain documented
gaps under task #16." A fresh gap audit against design-handoff/wtf-news.html
found the live page (already ~60% redesigned across 7+ prior PRs) was
missing only: an honest empty-state for zero-result filter combos, and the
province/scope/beat/riding chip rows collapsed behind a toggle (pure
client-side show/hide of already-server-rendered chips, no new query).

Explicitly OUT of scope, per a product decision with Kytran: the mockup's
"live ticker" (fabricates fake headlines from a hardcoded array — a
no-fabrication trap, same shape as /team's and /economy's mockup traps) and
a "Saved" bookmarks filter (no backing table, would need new data-model
work). The verdict filter and a sort control are deferred to a separate PR
— this route's fact-check decoration and top-N-by-recency precomputation
are both performance-tuned with real incident history (#5719 rewrite,
faceted-crawl bot-flood guards), and moving that decoration earlier or
changing the ranking axis needs its own careful, isolated change.
"""

from __future__ import annotations

import datetime
import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = REPO_ROOT / "consumer" / "routes.py"
TPL_DIR = REPO_ROOT / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"
_UTC = datetime.timezone.utc


def _article(id, published_at=None, band="center", title="Some headline", source="CBC"):
    return {
        "id": id, "title": title, "url": "https://example.com/a",
        "published_at": published_at or datetime.datetime.now(_UTC),
        "source": source, "source_id": 1, "band": band, "ai_analyzed": False,
        "province_code": None, "beat": None, "geo_scope": None,
        "cluster_id": id, "cluster_size": None, "coverage_gap_score": None,
        "overall_verdict": None, "mp_mentions": None,
    }


_STATIC_CTX = dict(
    total=0, source_count=46, page=1, total_pages=1, page_size=50,
    band_filter="all", province_filter="all", beat_filter="all",
    scope_filter="all", riding_filter="all", ridings=[], beat_meta=[],
    sources=[], band_mix=[], band_facets={}, province_facets={},
    beat_facets={}, scope_facets={}, is_subscriber=True,
    articles_24h=12, clustered_stories_24h=3, blindspot_flags_24h=2,
    today_str="2026-09-05", yesterday_str="2026-09-04",
)


def _env():
    return Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))


def _render(articles=(), **overrides):
    ctx = dict(_STATIC_CTX)
    ctx["articles"] = list(articles)
    ctx.update(overrides)
    return _env().get_template("news.html").render(**ctx)


# ────────────────────────── source-inspection (rule #6) ──────────────────

def test_template_defines_the_toggle_and_panel():
    src = (TPL_DIR / "news.html").read_text(encoding="utf-8")
    assert 'id="wtf-news-filters-toggle"' in src
    assert 'id="wtf-news-filters-panel"' in src
    assert "wtf-news-filters-toggle" in src  # JS wiring present, not just markup

    # Mutation check (house rule #7) run once at authoring time — NOT a
    # permanent test, per feedback_mutation-check-no-runtime-git.md.
    # Confirmed then: the pre-fix template had no "wtf-news-filters-panel"
    # or "wtf-nw-empty" string anywhere, and the province/scope/beat/riding
    # chip rows rendered unconditionally with no wrapping toggle. This
    # test and test_route_no_route_changes_were_needed below would both
    # have failed against it.


def test_route_no_route_changes_were_needed():
    # This was deliberately a template-only change — the route already
    # computed everything the toggle/empty-state need (filter values,
    # `total`, `articles`). Confirms news() itself wasn't touched.
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def news():")
    end = src.index("\n@bp.get", start + 1)
    body = src[start:end]
    assert "wtf-news-filters" not in body
    assert "wtf-nw-empty" not in body


# ────────────────────────── empty-state ───────────────────────────────────

def test_empty_state_shows_when_no_articles():
    html = _render(articles=[], total=0)
    assert "No articles match this filter combination." in html
    assert 'href="/news"' in html  # clear-filters link


def test_empty_state_absent_when_articles_present():
    html = _render(articles=[_article(1)], total=1)
    assert "No articles match this filter combination." not in html


# ────────────────────────── filters-collapsed toggle ──────────────────────

def test_panel_collapsed_by_default_when_no_secondary_filter_active():
    html = _render(articles=[_article(1)], total=1)
    assert 'id="wtf-news-filters-panel" hidden' in html
    assert 'aria-expanded="false"' in html


def test_panel_auto_expanded_when_province_filter_active():
    html = _render(articles=[_article(1)], total=1, province_filter="ON")
    assert 'id="wtf-news-filters-panel">' in html
    assert 'id="wtf-news-filters-panel" hidden' not in html
    assert 'aria-expanded="true"' in html


def test_panel_auto_expanded_when_riding_filter_active():
    html = _render(articles=[_article(1)], total=1, riding_filter="Ottawa Centre")
    assert 'id="wtf-news-filters-panel" hidden' not in html


def test_band_filter_alone_does_not_expand_the_panel():
    # Band stays always-visible above the toggle (the primary axis) — it is
    # NOT one of the four axes the toggle/badge count track.
    html = _render(articles=[_article(1)], total=1, band_filter="left")
    assert 'id="wtf-news-filters-panel" hidden' in html


def test_active_count_badge_reflects_number_of_active_secondary_filters():
    html = _render(articles=[_article(1)], total=1, province_filter="ON", beat_filter="politics")
    # badge shows "2" for the two active axes (province + beat)
    assert '<span class="wtf-act-filter-n">2</span>' in html


def test_no_badge_when_nothing_active():
    html = _render(articles=[_article(1)], total=1)
    toggle_start = html.index("wtf-news-filters-toggle")
    toggle_end = html.index("</button>", toggle_start)
    assert "wtf-act-filter-n" not in html[toggle_start:toggle_end]


def test_province_scope_beat_riding_chips_still_render_inside_the_panel():
    # The redesign must not have accidentally dropped any of the four
    # existing, real, working chip rows while wrapping them.
    html = _render(articles=[_article(1)], total=1, province_filter="ON",
                    beat_meta=[("all", "All", None), ("politics", "Politics", "#f00")])
    assert "wtf-nw-chiprow" in html  # province row
    assert "SCOPE" in html
    assert "BEAT" in html
