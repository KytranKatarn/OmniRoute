"""Regression coverage for /news' header stat row, date-rail headers, and
per-card Blindspot flag (2026-09-04, task #16 slice 1 / Batch 11).

Scope (deliberately narrower than task #16's full 13-piece interactive
layer — see the batch brief): a header stat row (Articles last 24h / Sources
in feed / Clustered stories), date-rail headers grouping the feed by day,
and the Blindspot flag/stat, reusing the /blindspot page's OWN
`_blindspot_total()` helper so the two pages can never disagree about what
counts as a blind spot. Search, sort, verdict/outlet/quick filter chips,
saved/bookmark, the slide-out drawer, and numbered pager/live-pull all stay
OUT of scope for this pass and remain documented gaps under task #16.
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


def _news_route_body(src: str) -> str:
    start = src.index("def news():")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def _article(id, published_at, coverage_gap_score=None, cluster_size=None,
             band="center", title="Some headline", source="CBC"):
    return {
        "id": id, "title": title, "url": "https://example.com/a",
        "published_at": published_at, "source": source, "source_id": 1,
        "band": band, "ai_analyzed": False, "province_code": None,
        "beat": None, "geo_scope": None, "cluster_id": id,
        "cluster_size": cluster_size, "coverage_gap_score": coverage_gap_score,
        "overall_verdict": None, "mp_mentions": None,
    }


_STATIC_CTX = dict(
    total=3, source_count=46, page=1, total_pages=1, page_size=50,
    band_filter="all", province_filter="all", beat_filter="all",
    scope_filter="all", riding_filter="all", ridings=[], beat_meta=[],
    sources=[], band_mix=[], band_facets={}, province_facets={},
    beat_facets={}, scope_facets={}, is_subscriber=True,
    # verdict filter (task #16 follow-up, migration 078) — added after this
    # file was written; news.html now `{% for %}`s verdict_meta, and Jinja
    # raises on iterating an Undefined.
    verdict_filter="all", verdict_meta=[], verdict_facets={},
)


def _env():
    return Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))


def _render_template_source(tpl_source, **ctx_overrides):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB, "news.html": tpl_source}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    ctx = dict(_STATIC_CTX)
    ctx.update(ctx_overrides)
    return env.get_template("news.html").render(**ctx)


def _render(articles, articles_24h=12, clustered_stories_24h=3,
            blindspot_flags_24h=2, today_str=None, yesterday_str=None):
    now = datetime.datetime.now(_UTC)
    today_str = today_str or now.strftime("%Y-%m-%d")
    yesterday_str = yesterday_str or (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return _render_template_source(
        (TPL_DIR / "news.html").read_text(encoding="utf-8"),
        articles=articles, articles_24h=articles_24h,
        clustered_stories_24h=clustered_stories_24h,
        blindspot_flags_24h=blindspot_flags_24h,
        today_str=today_str, yesterday_str=yesterday_str,
    )


# ── Header stat row ──────────────────────────────────────────────────────

def test_header_stat_row_renders_all_four_real_figures():
    html = _render([_article(1, datetime.datetime.now(_UTC))],
                    articles_24h=12, clustered_stories_24h=3, blindspot_flags_24h=2)
    assert "Articles, last 24h" in html
    assert "Sources in feed" in html
    assert "Clustered stories" in html
    assert "Blindspot flags" in html
    assert 'wtf-a-tile-n">12<' in html
    assert 'wtf-a-tile-n">46<' in html  # source_count, already-existing value
    assert 'wtf-a-tile-n">3<' in html
    assert 'wtf-a-tile-n">2<' in html


# ── Date-rail headers ────────────────────────────────────────────────────

def test_date_rail_groups_same_day_articles_under_one_rail():
    now = datetime.datetime.now(_UTC)
    same_day_a = _article(1, now.replace(hour=9, minute=0, second=0, microsecond=0))
    same_day_b = _article(2, now.replace(hour=15, minute=0, second=0, microsecond=0))
    yesterday = _article(3, (now - datetime.timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0))
    html = _render([same_day_a, same_day_b, yesterday])
    # NB: the bare string "wtf-nw-daterail" also appears twice in this page's
    # own <style> block regardless of content — count the actual rendered
    # rail elements, not the CSS rule text.
    assert html.count('<div class="wtf-nw-daterail">') == 2, (
        "two articles published the same calendar day must share ONE rail, "
        "not render a rail per article"
    )
    assert "Today" in html
    assert "Yesterday" in html


def test_date_rail_falls_back_to_a_formatted_date_beyond_yesterday():
    older = (datetime.datetime.now(_UTC) - datetime.timedelta(days=10)).replace(
        hour=12, minute=0, second=0, microsecond=0)
    html = _render([_article(1, older)])
    assert "Today" not in html
    assert "Yesterday" not in html
    assert older.strftime("%b %d, %Y") in html


def test_date_rail_skips_articles_with_no_published_at():
    # Should not raise, and should not print a rail element for a null
    # timestamp (the bare string also appears in this page's own CSS).
    html = _render([_article(1, None)])
    assert '<div class="wtf-nw-daterail">' not in html


# ── Blindspot flag (per-card) ────────────────────────────────────────────

def test_blindspot_badge_shows_for_a_qualifying_multi_outlet_low_coverage_story():
    html = _render([_article(1, datetime.datetime.now(_UTC),
                              coverage_gap_score=0.10, cluster_size=2)])
    assert "🔦 Blindspot" in html


def test_blindspot_badge_hidden_when_gap_score_exceeds_the_shared_threshold():
    html = _render([_article(1, datetime.datetime.now(_UTC),
                              coverage_gap_score=0.5, cluster_size=2)])
    assert "🔦 Blindspot" not in html


def test_blindspot_badge_hidden_for_a_single_outlet_story():
    # A story with only one outlet isn't a "blind spot" by the /blindspot
    # page's own definition (article_count/cluster_size >= 2) — an
    # unclustered single article must never render the badge.
    html = _render([_article(1, datetime.datetime.now(_UTC),
                              coverage_gap_score=0.05, cluster_size=1)])
    assert "🔦 Blindspot" not in html


def test_blindspot_badge_hidden_when_unscored():
    html = _render([_article(1, datetime.datetime.now(_UTC),
                              coverage_gap_score=None, cluster_size=None)])
    assert "🔦 Blindspot" not in html


# ── Source-inspection: reuse, not reinvent ───────────────────────────────

def test_blindspot_stat_reuses_the_blindspot_pages_own_helper():
    body = _news_route_body(ROUTES.read_text(encoding="utf-8"))
    assert "_blindspot_total(days=1)" in body, (
        "the header stat must call the /blindspot page's own helper — a "
        "second hardcoded 0.15 threshold here could silently drift from it"
    )


def test_news_query_selects_the_real_coverage_gap_score_column():
    body = _news_route_body(ROUTES.read_text(encoding="utf-8"))
    assert "sc.coverage_gap_score" in body, (
        "the per-card Blindspot badge needs this column selected from the "
        "story_clusters join the query already has"
    )


# ── Mutation check (house rule #7) ───────────────────────────────────────
#
# Deliberately NOT `git show HEAD:...` at runtime — HEAD stops being
# "pre-fix" the moment this PR merges, so a test built that way passes at
# authoring time and then fails forever afterward (it did, here, until this
# note replaced it — see test_article_batch11.py's docstring for the same
# reasoning). The mutation check itself was run once at authoring time by
# rendering `git show <parent-commit>:consumer/templates/news.html` and
# confirming every assertion in the tests above (header stat row, date-rail,
# Blindspot badge/stat) failed against it. That one-time verification is
# what justifies the tests above; it does not need to re-run on every CI
# invocation against a moving HEAD.
