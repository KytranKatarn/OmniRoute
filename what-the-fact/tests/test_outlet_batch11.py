"""Regression coverage for /source/<slug> batch 11 additions (2026-09-04).

Implements: fact-checked + filed-first stat tiles, a coverage-profile panel
(main beat / main region), a "scores closest to this one" peer panel, a
full-article-list "show all N" expand past the LIMIT 20 default, honest
header quick-action links, and a continuous left/right bias-position gauge.

Deliberately NOT implemented (see PR description for the full reasoning):
  - "Blindspot count" stat tile — no per-outlet definition or schema support
    exists anywhere in this codebase; inventing one would be exactly the kind
    of fabricated metric the task's hard rules forbid.
  - Fact-check rate % / filed-first % — the narrowed scope for this page
    asked for plain COUNTS, not percentages.
  - Paywall gating scope — unchanged; product/monetization decision.
  - The mockup's literal "Filter the feed" button — it deep-links to a
    #src= fragment that /news's JS never reads, and /news has no per-source
    filter query param (checked its VALID_* axes: band/province/beat/scope/
    riding only). Adding one is a change to a DIFFERENT route, out of this
    page's scope, so the header action was relabeled to a real, working
    link ("Full news feed →" -> /news) instead of shipping a dead button.

Route-logic assertions below are done via source-inspection of
consumer/routes.py (per this batch's house testing convention — see
tests/test_mp_hero_links.py), not by executing SQL against a live DB.
Template-only behaviour is rendered via a standalone Jinja environment
(see tests/test_owners_concentration_stats.py) with no live Flask app and
no DB connection.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


class _FakeRequest:
    path = "/source/ipolitics"


def _source_profile_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def source_profile")
    end = src.index("\n@bp.", start + 1)
    return src[start:end]


def _src(**overrides):
    base = dict(
        id=1, slug="ipolitics", name="iPolitics", url="https://ipolitics.ca",
        bias_lean="center-left", country="CA", language="en",
        owner_name=None, owner_type=None,
        avg_score=None, rolling_band=None,
        total_articles=42, articles_7d=3,
    )
    base.update(overrides)
    return base


def _article(i, **overrides):
    row = dict(id=i, title=f"Story {i}", url="https://x.example/" + str(i),
               published_at=None, band=None, score=None)
    row.update(overrides)
    return row


_BASE_CTX = dict(
    band_counts=[], recent=[],
    fact_checked_count=0, filed_first_count=0,
    coverage={"main_beat": None, "main_region": None},
    peers=[], show_all=False, article_list_cap=300,
    is_subscriber=True,
)


def _render(src, **ctx_overrides):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _FakeRequest()
    ctx = dict(_BASE_CTX)
    ctx.update(ctx_overrides)
    return env.get_template("source.html").render(src=src, **ctx)


# ── stat tiles ────────────────────────────────────────────────────────────

def test_fact_checked_and_filed_first_tiles_render_with_counts():
    html = _render(_src(), fact_checked_count=12, filed_first_count=3)
    assert "Fact-Checked" in html
    assert "Filed First" in html
    fc_idx = html.find("Fact-Checked")
    assert ">12<" in html[max(0, fc_idx - 250):fc_idx]
    ff_idx = html.find("Filed First")
    assert ">3<" in html[max(0, ff_idx - 250):ff_idx]


def test_stat_tiles_render_zero_honestly_not_blank():
    html = _render(_src(), fact_checked_count=0, filed_first_count=0)
    fc_idx = html.find("Fact-Checked")
    assert ">0<" in html[max(0, fc_idx - 250):fc_idx]


def test_stat_tiles_absent_when_context_missing_default_to_zero():
    # A future caller that forgets to pass the new kwargs must not 500 —
    # the template's `| default(0)` guards this the same way the pre-existing
    # Total Articles / Last 7 Days tiles already guard their own values.
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _FakeRequest()
    html = env.get_template("source.html").render(
        src=_src(), band_counts=[], recent=[],
        coverage={"main_beat": None, "main_region": None}, peers=[],
        show_all=False, article_list_cap=300, is_subscriber=True,
    )
    assert "Fact-Checked" in html


# ── coverage profile panel ───────────────────────────────────────────────

def test_coverage_profile_renders_main_beat_and_region():
    html = _render(_src(), coverage={"main_beat": "science-tech", "main_region": "ON"})
    assert "Coverage Profile" in html
    assert "Science Tech" in html
    assert "ON" in html


def test_coverage_profile_absent_when_nothing_known():
    html = _render(_src(), coverage={"main_beat": None, "main_region": None})
    assert "Coverage Profile" not in html


def test_coverage_profile_renders_with_only_one_field_known():
    html = _render(_src(), coverage={"main_beat": None, "main_region": "QC"})
    assert "Coverage Profile" in html
    assert "Main Region" in html
    assert "Main Beat" not in html


# ── peer panel ────────────────────────────────────────────────────────────

def test_peer_panel_renders_names_scores_and_links():
    peers = [
        {"id": 2, "slug": "cbc", "name": "CBC", "avg_score": -0.15, "band": "center-left"},
        {"id": 3, "slug": "globe-and-mail", "name": "The Globe and Mail",
         "avg_score": 0.05, "band": "center"},
    ]
    html = _render(_src(avg_score=-0.1, rolling_band="center-left"), peers=peers)
    assert "Scores Closest To This One" in html
    assert "CBC" in html
    assert 'href="/source/cbc"' in html
    assert "The Globe and Mail" in html
    assert "-0.15" in html


def test_peer_panel_absent_when_no_peers():
    html = _render(_src(avg_score=None), peers=[])
    assert "Scores Closest To This One" not in html


# ── full article list / show-all expand ─────────────────────────────────

def test_show_all_link_present_when_more_articles_than_shown():
    html = _render(_src(total_articles=45),
                    recent=[_article(i) for i in range(20)], show_all=False)
    assert "Show all 45 articles" in html
    assert "?all=1" in html


def test_show_all_link_absent_when_every_article_already_shown():
    html = _render(_src(total_articles=3),
                    recent=[_article(i) for i in range(3)], show_all=False)
    assert "Show all" not in html


def test_show_fewer_link_and_count_when_show_all_active():
    html = _render(_src(total_articles=45),
                    recent=[_article(i) for i in range(45)], show_all=True)
    assert "Show fewer" in html
    assert "Showing 45 of 45 articles" in html
    assert "most recent" not in html


def test_show_all_discloses_the_hard_cap_when_total_exceeds_it():
    html = _render(_src(total_articles=500),
                    recent=[_article(i) for i in range(300)],
                    show_all=True, article_list_cap=300)
    assert "Showing 300 of 500 articles" in html
    assert "most recent 300" in html


def test_panel_title_switches_between_recent_and_all():
    html_default = _render(_src(), show_all=False)
    assert "Recent Articles" in html_default
    html_all = _render(_src(), recent=[_article(1)], show_all=True)
    assert "All Articles" in html_all


def test_show_all_block_omitted_on_empty_outlet():
    html = _render(_src(total_articles=0), recent=[], show_all=True)
    assert "No articles tracked yet." in html
    assert "Showing 0 of 0" not in html


# ── header quick-action links ────────────────────────────────────────────

def test_header_links_are_real_and_working():
    html = _render(_src())
    assert 'href="/sources"' in html
    assert "All outlets" in html
    assert 'href="/news"' in html


def test_mockups_dead_filter_link_was_not_shipped():
    # The mockup's button deep-links to wtf-news.html#src=<name> — a
    # fragment /news's real JS never reads. Ship a working link, not that.
    html = _render(_src())
    assert "Filter the feed" not in html
    assert "#src=" not in html


# ── continuous bias-position gauge ───────────────────────────────────────

def test_gauge_renders_marker_at_the_correct_position():
    html = _render(_src(avg_score=0.5, rolling_band="center-right"))
    assert "Where This Outlet Lands" in html
    assert "left:75.0%" in html
    assert "+0.50" in html


def test_gauge_clamps_at_the_left_extreme():
    html = _render(_src(avg_score=-1.0, rolling_band="left"))
    assert "left:0.0%" in html


def test_gauge_clamps_when_input_exceeds_the_measured_domain():
    # Domain is measured [-1, 1] (SELECT min/max FROM wtf.bias_scores) — this
    # only exercises the display clamp as a safety net, not a real value.
    # (Jinja's min/max on a mixed float/int tie returns the plain int 100
    # here rather than 100.0 — cosmetically different from the 75.0/0.0
    # cases above, but an equally correct clamp, so both spellings pass.)
    html = _render(_src(avg_score=2.0, rolling_band="right"))
    assert "left:100%" in html or "left:100.0%" in html


def test_gauge_absent_without_a_rolling_score():
    html = _render(_src(avg_score=None, rolling_band=None))
    assert "Where This Outlet Lands" not in html


# ── route logic (source-inspection — no live DB) ─────────────────────────

def test_recent_articles_limit_is_parameterized_not_hardcoded():
    body = _source_profile_route_body()
    assert "ORDER BY a.published_at DESC LIMIT :lim" in body
    assert "LIMIT 20" not in body, "the old hardcoded cap must be replaced by the :lim param"
    assert 'request.args.get("all")' in body


def test_fact_checked_count_dedupes_by_distinct_article_id():
    body = _source_profile_route_body()
    assert "COUNT(DISTINCT fc.article_id)" in body


def test_filed_first_uses_the_clusters_earliest_published_at_column():
    body = _source_profile_route_body()
    assert "sc.earliest_published_at" in body
    assert "story_clusters" in body


def test_coverage_query_excludes_the_none_beat_placeholder():
    # beat='none' is a real stored value ("no beat assigned"), not a beat —
    # regression guard for the same class of bug /news already avoids.
    body = _source_profile_route_body()
    assert "beat <> 'none'" in body


def test_peer_query_is_gated_on_this_outlets_own_avg_score():
    body = _source_profile_route_body()
    assert 'if src["avg_score"] is not None:' in body
    assert "obs.source_id != :sid" in body
