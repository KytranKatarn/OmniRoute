"""Regression coverage for /article's batch-11 additions (#6153, wtf-article
design handoff): the pickup-order timeline, the "what we measured" coverage
summary, and the client-side citation generator.

All three are computed / derived from data the route already fetches for
every article — `cluster_articles` (the existing, subscriber-gated sibling
list) plus this article's own row. No new query, no new table, nothing
fabricated: an "analyst note" panel and a 6-agent "who worked this story"
rail card were both considered and DROPPED from this batch because no real
per-article data source exists for either (see the PR description).

The pickup-order and coverage-summary logic lives as a nested closure inside
`article()` in routes.py (it needs `a`/`cluster_articles`, which are locals
of that request, and reuses the module-level `_BAND_ORDER`/`_band_label`
pair the file already declares once for exactly this reason — a private
re-encoding of the 5-band vocabulary is how a "median" stops matching the
bands the page actually renders, per that pair's own docstring). routes.py
imports flask/db/sqlalchemy at module scope, so it cannot be imported
directly in a bare unit test — the fixture below execs ONLY that slice
(dedented back to module level) plus the two small helpers it calls, the
same technique test_facet_rate_limit.py uses for the /news rate limiter.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import textwrap
import types

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = ROOT / "consumer" / "routes.py"
TPL_DIR = ROOT / "consumer" / "templates"
_BASE_STUB = "{% block title %}{% endblock %}{% block meta %}{% endblock %}{% block content %}{% endblock %}"


# ---------------------------------------------------------------------------
# Route-logic fixture — exec's the pickup-order/coverage-summary slice in
# isolation, plus the pre-existing _BAND_ORDER/_band_label pair it calls.
# ---------------------------------------------------------------------------

def _load_pickup_logic(a: dict, cluster_articles: list):
    """Run the ACTUAL shipped slice of article() against synthetic inputs.

    Returns (pickup_order, coverage_stats) exactly as the route would compute
    them, without a Flask app, a DB connection, or re-implementing the logic
    a second time in the test (which would only prove the test agrees with
    itself).
    """
    src = ROUTES.read_text(encoding="utf-8")

    # The two small module-level helpers the slice calls (declared once,
    # much later in the file, on purpose — see their own docstring).
    band_start = src.index("_BAND_ORDER = (")
    band_end = src.index("def _spread_sentence")
    band_src = src[band_start:band_end]

    # The nested closure inside article() — indented at function-body level,
    # so it is dedented back to module level before exec.
    slice_start = src.index("    def _fmt_pickup_offset(hours: float) -> str:")
    slice_end = src.index("# Outlet sparkline", slice_start)
    slice_src = textwrap.dedent(src[slice_start:slice_end])

    mod = types.ModuleType("article_pickup_slice")
    exec(compile(band_src, "routes_band_helpers", "exec"), mod.__dict__)
    mod.__dict__["a"] = a
    mod.__dict__["cluster_articles"] = cluster_articles
    exec(compile(slice_src, "routes_pickup_slice", "exec"), mod.__dict__)
    return mod.__dict__["pickup_order"], mod.__dict__["coverage_stats"]


def _article(id=1, title="Current", source_name="Current Outlet",
             published_at=None, bias_band=None, bias_ensemble_band=None):
    return {
        "id": id, "title": title, "source_name": source_name,
        "published_at": published_at, "bias_band": bias_band,
        "bias_ensemble_band": bias_ensemble_band,
    }


def _sibling(id, title, source_name, published_at, bias_band=None):
    return {"id": id, "title": title, "source_name": source_name,
            "published_at": published_at, "bias_band": bias_band}


_T0 = dt.datetime(2026, 9, 1, 8, 0)


class TestPickupOrder:
    def test_no_cluster_means_no_pickup_order(self):
        pickup, coverage = _load_pickup_logic(_article(published_at=_T0), [])
        assert pickup == []
        assert coverage is None

    def test_a_solo_sibling_with_no_timestamp_stays_empty_not_one_row(self):
        """A single real entry says nothing about 'order' — the route
        requires 2+ timestamped rows before it shows anything."""
        a = _article(published_at=_T0)
        siblings = [_sibling(2, "Other", "Other Outlet", None)]
        pickup, _ = _load_pickup_logic(a, siblings)
        assert pickup == []

    def test_sorts_ascending_earliest_first_regardless_of_input_order(self):
        a = _article(published_at=_T0 + dt.timedelta(hours=5))
        siblings = [
            _sibling(2, "Mid", "Mid Outlet", _T0 + dt.timedelta(hours=2)),
            _sibling(3, "First", "First Outlet", _T0),
        ]
        pickup, _ = _load_pickup_logic(a, siblings)
        assert [p["id"] for p in pickup] == [3, 2, 1]
        assert pickup[0]["offset_label"] == "First to report"

    def test_hour_offsets_are_computed_not_guessed(self):
        a = _article(published_at=_T0 + dt.timedelta(hours=3))
        siblings = [_sibling(2, "First", "First Outlet", _T0)]
        pickup, _ = _load_pickup_logic(a, siblings)
        assert pickup[0]["offset_label"] == "First to report"
        assert pickup[1]["offset_label"] == "+3h"

    def test_multi_day_offset_shows_days_and_hours(self):
        a = _article(published_at=_T0 + dt.timedelta(days=1, hours=2))
        siblings = [_sibling(2, "First", "First Outlet", _T0)]
        pickup, _ = _load_pickup_logic(a, siblings)
        assert pickup[1]["offset_label"] == "+1d 2h"

    def test_near_simultaneous_publication_reads_as_same_time_not_plus_zero_h(self):
        a = _article(published_at=_T0 + dt.timedelta(minutes=1))
        siblings = [_sibling(2, "First", "First Outlet", _T0)]
        pickup, _ = _load_pickup_logic(a, siblings)
        assert pickup[1]["offset_label"] == "Same time"

    def test_the_current_article_is_marked_and_flows_through_the_sort(self):
        a = _article(id=1, published_at=_T0 + dt.timedelta(hours=1))
        siblings = [_sibling(2, "First", "First Outlet", _T0)]
        pickup, _ = _load_pickup_logic(a, siblings)
        current = next(p for p in pickup if p["is_current"])
        assert current["id"] == 1
        assert pickup[0]["is_current"] is False


class TestCoverageSummary:
    def test_no_scored_bands_anywhere_yields_no_panel(self):
        """Bias not yet run on any outlet in the cluster — the panel must
        not render zeros, it must not exist at all."""
        a = _article(published_at=_T0, bias_band=None, bias_ensemble_band=None)
        siblings = [_sibling(2, "Other", "Other Outlet", _T0, bias_band=None)]
        _, coverage = _load_pickup_logic(a, siblings)
        assert coverage is None

    def test_outlets_covering_counts_current_plus_every_sibling(self):
        a = _article(published_at=_T0, bias_band="center")
        siblings = [
            _sibling(2, "A", "A", _T0, bias_band="center-right"),
            _sibling(3, "B", "B", _T0, bias_band=None),  # unscored, still counted here
        ]
        _, coverage = _load_pickup_logic(a, siblings)
        assert coverage["outlets_covering"] == 3

    def test_unscored_siblings_are_excluded_from_the_band_spread(self):
        """An absent bias_band must not be counted as a 'center' reading —
        the whole point of #065's wire-exclusion precedent applied here."""
        a = _article(published_at=_T0, bias_band="left")
        siblings = [_sibling(2, "Unscored", "Unscored", _T0, bias_band=None)]
        _, coverage = _load_pickup_logic(a, siblings)
        assert coverage["bands_spanned"] == 1
        assert coverage["widest_label"] == "Left"

    def test_ensemble_band_wins_over_the_single_band_for_the_current_article(self):
        """Matches the SAME precedence already used elsewhere on this page
        (`a.bias_ensemble_band or a.bias_band`) — a second, disagreeing rule
        here would make the two panels contradict each other on one page."""
        a = _article(published_at=_T0, bias_band="left", bias_ensemble_band="right")
        siblings = [_sibling(2, "X", "X", _T0, bias_band="left")]
        _, coverage = _load_pickup_logic(a, siblings)
        assert coverage["widest_label"] == "Left → Right"

    def test_widest_spread_orders_left_to_right_not_input_order(self):
        a = _article(published_at=_T0, bias_band="right")
        siblings = [
            _sibling(2, "A", "A", _T0, bias_band="left"),
            _sibling(3, "B", "B", _T0, bias_band="center"),
        ]
        _, coverage = _load_pickup_logic(a, siblings)
        assert coverage["bands_spanned"] == 3
        assert coverage["widest_label"] == "Left → Right"

    def test_a_single_band_has_no_arrow(self):
        a = _article(published_at=_T0, bias_band="center-left")
        siblings = [_sibling(2, "X", "X", _T0, bias_band="center-left")]
        _, coverage = _load_pickup_logic(a, siblings)
        assert coverage["bands_spanned"] == 1
        assert coverage["widest_label"] == "Center-Left"
        assert "→" not in coverage["widest_label"]


# ---------------------------------------------------------------------------
# Template rendering — same DictLoader/FileSystemLoader harness the two
# preceding batch-11-style tests (test_mp_hero_links.py, test_owners_
# concentration_stats.py) already use.
# ---------------------------------------------------------------------------

_ARTICLE_CTX = dict(
    article_entities=[], key_figures=[], is_subscriber=False, is_paywalled=False,
    is_limited_body=False, google_fact_checks=[], cluster_articles=[],
    reading_time_min=2, article_type="news", sparkline=[], local_articles=[],
    local_place=None, tickers=[], is_wire=False, mp_claims=[],
    cross_watch_entities=[], pickup_order=[], coverage_stats=None,
)


def _article_row(**overrides):
    row = {
        "id": 42, "title": "A Test Headline", "body": "word " * 400,
        "url": "https://example.com/story", "published_at": _T0,
        "ai_analyzed": True, "ai_analyzed_at": _T0, "province_code": "ON",
        "cluster_id": None, "city": None, "geo_scope": "province",
        "content_type": "news", "suppressed_reason": None,
        "canonical_article_id": None, "analysis_tier": "tier1",
        "tier2_pending": False, "bias_v2_score": None, "bias_v2_label": None,
        "bias_ensemble_score": None, "bias_ensemble_band": None,
        "source_name": "Test Source", "source_slug": "test-source",
        "owner_name": None, "owner_type": None, "source_country": "CA",
        "bias_band": "center", "bias_score": 0.0, "bias_rationale": None,
        "trigger_phrases": [], "bias_confidence": 0.7,
        "bias_analyzed_by": "dhq_v1", "bias_signal_detected": True,
        "outlet_avg_score": 0.0, "outlet_rolling_band": "center",
        "outlet_sample_count": 5, "outlet_window_days": 30,
        "outlet_article_count": 50, "overall_verdict": None,
        "fact_check_claims": [], "fc_analyzed_by": None,
    }
    row.update(overrides)
    return row


def _render(**overrides):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    ctx = dict(_ARTICLE_CTX)
    ctx.update(overrides)
    return env.get_template("article.html").render(**ctx)


class TestWhatWeMeasuredPanel:
    def test_renders_when_coverage_stats_present(self):
        html = _render(a=_article_row(), coverage_stats={
            "outlets_covering": 3, "bands_spanned": 2, "widest_label": "Left → Center",
        })
        assert "What we measured" in html
        assert "Outlets covering" in html
        assert ">3<" in html
        assert "Left → Center" in html

    def test_absent_when_coverage_stats_is_none(self):
        """No real bias data recorded for the story -> no panel, not a
        panel full of zeros."""
        html = _render(a=_article_row(), coverage_stats=None)
        assert "What we measured" not in html


class TestPickupOrderPanel:
    _PICKUP = [
        {"id": 42, "title": "A Test Headline", "source_name": "Test Source",
         "published_at": _T0, "is_current": True, "offset_label": "First to report"},
        {"id": 7, "title": "Other Story", "source_name": "Other Outlet",
         "published_at": _T0 + dt.timedelta(hours=4), "is_current": False, "offset_label": "+4h"},
    ]

    # NOTE: the INSTANTIATED opening tag (`class="wtf-art-rail-item
    # wtf-art-pickup-panel"`), never a bare class-name substring. The class
    # name alone is a false positive either way it points: it is also the
    # CSS selector in this file's own <style> block, which renders
    # unconditionally — and "Pickup order" (the heading text) is quoted
    # verbatim in a CSS *comment* right above that same rule. Both render
    # regardless of is_subscriber/pickup_order, so a bare substring check on
    # either would pass even when the panel itself never rendered.
    _PANEL_TAG = 'class="wtf-art-rail-item wtf-art-pickup-panel"'

    def test_renders_for_subscribers(self):
        html = _render(a=_article_row(cluster_id=9), is_subscriber=True,
                        cluster_articles=[{"id": 7, "title": "Other Story", "url": "https://x.com",
                                            "published_at": _T0, "source_name": "Other Outlet",
                                            "source_slug": "other", "bias_band": "center", "bias_score": 0.0}],
                        pickup_order=self._PICKUP)
        assert self._PANEL_TAG in html
        assert "First to report" in html
        assert "+4h" in html
        assert 'href="/article/7"' in html

    def test_hidden_from_non_subscribers_same_gate_as_the_sibling_panel(self):
        """This is the SAME gate the existing sibling-comparison panel uses
        (is_subscriber) — pickup order is a companion view of identical
        per-outlet detail, and this batch is explicitly told not to change
        that panel's paywall scope. A free reader must not get the detail
        through a second, newer panel."""
        html = _render(a=_article_row(cluster_id=9), is_subscriber=False,
                        cluster_articles=[{"id": 7, "title": "Other Story", "url": "https://x.com",
                                            "published_at": _T0, "source_name": "Other Outlet",
                                            "source_slug": "other", "bias_band": "center", "bias_score": 0.0}],
                        pickup_order=self._PICKUP)
        assert self._PANEL_TAG not in html
        assert "First to report" not in html

    def test_absent_when_pickup_order_empty(self):
        html = _render(a=_article_row(), is_subscriber=True, pickup_order=[])
        assert self._PANEL_TAG not in html


class TestCiteThisAnalysis:
    def test_panel_renders_with_the_real_article_metadata(self):
        html = _render(a=_article_row(id=99, title="A Very Specific Title",
                                       source_name="Specific Outlet", published_at=_T0))
        assert "Cite this analysis" in html
        assert 'data-cite-title="A Very Specific Title"' in html
        assert 'data-cite-source="Specific Outlet"' in html
        assert 'data-cite-date="2026-09-01"' in html
        assert 'data-cite-permalink="https://what-the-fact.com/article/99"' in html

    def test_renders_for_non_subscribers_too_metadata_is_not_paid_content(self):
        html = _render(a=_article_row(), is_subscriber=False)
        assert "Cite this analysis" in html

    def test_no_fabricated_author_falls_back_to_the_publisher_name(self):
        """No journalist/byline field exists on this schema. The citation
        must use the ORGANIZATION as author (a valid APA 7 form, §9.11),
        never an invented person's name."""
        html = _render(a=_article_row(source_name=None))
        assert 'data-cite-source="What The Fact"' in html

    def test_uses_value_assignment_not_innerhtml_for_the_citation_output(self):
        """House XSS rule: DB-sourced content reaching the DOM via JS must
        use textContent/.value, never innerHTML."""
        src = (TPL_DIR / "article.html").read_text(encoding="utf-8")
        cite_js = src[src.index("Cite this analysis (#6153)") : src.index("printBtn.addEventListener")]
        assert "output.value = build(" in cite_js
        assert ".innerHTML" not in cite_js


# ---------------------------------------------------------------------------
# Mutation check (house rule): prove these assertions FAIL against the
# pre-fix template, so a future revert of article.html is caught here too.
# ---------------------------------------------------------------------------

# Mutation check (house rule #7) run once at authoring time. Originally
# implemented as a runtime `git merge-base HEAD origin/main` lookup — a
# smarter attempt than a bare `git show HEAD:...` (it survives the branch
# gaining review commits), but it still collapses once this branch is
# squash-merged and deleted: on `main` post-merge, HEAD and origin/main are
# the same commit, so merge-base again resolves to the post-fix tip and the
# check compares the new template against itself (confirmed: this is
# exactly how it failed on the first full-suite run after merge). There is
# no ordinary git ref that stays "pre-fix" once the fix is mainline — the
# verification below was run once, by hand, against the true parent commit,
# and is not re-derivable from any ref this repo keeps around afterward.
#
# Confirmed then: none of "What we measured", "Pickup order", or "Cite this
# analysis" appeared anywhere in article.html before this batch's commit.
