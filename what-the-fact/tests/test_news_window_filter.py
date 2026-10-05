"""/news time window (All time / 24 hours / 7 days / 30 days) — port of the design's "Window".

What can go wrong here is quiet, and it is the reason for each group below:

* CACHE KEY. `/news` caches its whole result per filter combination. A filter that is applied
  to the SQL but missing from the key serves one visitor's 7-day page to the next visitor's
  all-time request. (TestRoute.test_window_is_part_of_the_cache_key)
* AN OPEN VALUE. The route sits behind a page cache and faceted-crawl guards built for a
  bounded set of filter values (see the August 2026 incident notes in routes.py). An open
  `?window=<anything>` would mint a cache key and a DB query per distinct string. The value is
  therefore a CLOSED SET, anything else collapses to "all", and the hours are a BOUND integer.
* LOST STATE. Eleven links on the page rebuild the query string; one that forgets the window
  silently drops it when you click a band, a province or the next page.
* BYTE-IDENTICAL DEFAULTS. With no window chosen, no URL may change at all (`window=` must not
  appear), so existing links, caches and the "clean /news is never throttled" rule are untouched.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from shared import news_window as nw

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
TPL = ROOT / "consumer" / "templates"


def _news_body() -> str:
    a = ROUTES.index("def news():")
    return ROUTES[a:ROUTES.index("\n@bp.get", a + 1)]


# ── the closed set ───────────────────────────────────────────────────────────
class TestClosedSet:
    @pytest.mark.parametrize("key", ["all", "24h", "7d", "30d"])
    def test_known_keys_pass_through(self, key):
        assert nw.normalize_window(key) == key

    @pytest.mark.parametrize("junk", [None, "", " ", "7D", "24H", "1y", "9999999", "-1", "7d ", "all;DROP", "7d&x=1",
                                       "../etc", "a" * 5000, 7, 24, ["7d"], b"7d", "None", "null", "true"])
    def test_anything_else_collapses_to_all_never_to_a_new_key(self, junk):
        assert nw.normalize_window(junk) == "all"

    def test_hours_come_from_a_closed_table(self):
        assert nw.window_hours("all") is None
        assert (nw.window_hours("24h"), nw.window_hours("7d"), nw.window_hours("30d")) == (24, 168, 720)
        assert nw.window_hours("garbage") is None, "an unknown key must mean NO restriction, not an error"

    def test_there_are_exactly_four_windows_so_the_url_space_is_bounded(self):
        assert [k for k, _ in nw.WINDOW_META] == list(nw.WINDOWS) == ["all", "24h", "7d", "30d"]

    def test_default_adds_nothing_to_a_url_and_a_choice_adds_one_param(self):
        assert nw.query_suffix("all") == "" and nw.query_suffix(None) == "" and nw.query_suffix("junk") == ""
        assert nw.query_suffix("7d") == "&window=7d"


# ── the route ────────────────────────────────────────────────────────────────
class TestRoute:
    def test_window_is_parsed_through_the_closed_set(self):
        body = _news_body()
        assert 'window_filter = _normalize_window(_req.args.get("window"))' in body
        assert "from shared.news_window import" in body

    def test_window_is_part_of_the_cache_key(self):
        m = re.search(r"_ck = \(([^)]*)\)", _news_body(), re.S)
        assert m and "window_filter" in m.group(1), (
            "the window filters the SQL; if it is not in the cache key one visitor's window is "
            "served to another")
        assert m.group(1).rstrip().endswith("page"), "page stays last in the key"

    def test_the_clause_is_a_bound_parameter_never_interpolated(self):
        body = _news_body()
        line = next(l for l in body.splitlines() if 'filter_clauses["window"]' in l)
        assert "make_interval(hours => :window_hours)" in line
        assert not re.search(r'f"|\.format\(|%s|\+\s*str|\{', line), f"window clause must not interpolate: {line!r}"
        assert 'params["window_hours"] = _window_hours(window_filter)' in body

    def test_it_joins_the_shared_filter_clauses_so_every_count_honours_it(self):
        body = _news_body()
        # facets/total/mix/rows all build their WHERE from filter_clauses via _where_except();
        # adding the axis there is what makes them agree. A hand-edited per-query clause would not.
        assert 'filter_clauses["window"]' in body
        assert "_where_except('window')" not in body, "the window has no facet of its own"

    def test_both_render_paths_receive_the_window(self):
        body = _news_body()
        assert len(re.findall(r'render_template\("news\.html"', body)) == 2
        assert body.count("window_filter=window_filter, window_meta=_WINDOW_META") == 2, (
            "the cached-path render AND the live render must both pass it, or the cached page "
            "would drop the pills")

    def test_header_vitals_stay_unfiltered(self):
        # articles_24h / clustered_stories_24h are feed-health vitals, deliberately independent of
        # every filter (see the route comment). The window must not leak into them.
        body = _news_body()
        seg = body[body.index("articles_24h = c.execute"):body.index("params = {}")]
        assert "window" not in seg


# ── the template ─────────────────────────────────────────────────────────────
_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"
_CTX = dict(total=3, source_count=46, page=2, total_pages=3, page_size=50, band_filter="all",
            province_filter="all", beat_filter="all", scope_filter="all", riding_filter="all", outlet_filter="all",
            ridings=[], beat_meta=[], sources=[], band_mix=[], band_facets={}, province_facets={},
            beat_facets={}, scope_facets={}, verdict_filter="all", verdict_meta=[], verdict_facets={},
            articles=[], articles_24h=1, clustered_stories_24h=1, blindspot_flags_24h=0,
            today_str="2026-10-05", yesterday_str="2026-10-04", is_subscriber=True)


def _render(**over):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]))
    ctx = dict(_CTX); ctx.update(over)
    return env.get_template("news.html").render(**ctx)


def _hrefs(html):
    return re.findall(r'href="(/news\?[^"]*)"', html)


def _pill_row(html):
    m = re.search(r'wtf-nw-window-row.*?</div>', html, re.S)
    assert m, "window pill row missing"
    return m.group(0)


class TestTemplate:
    def test_four_pills_with_the_designs_labels_and_the_active_one_marked(self):
        row = _pill_row(_render(window_filter="7d", window_meta=nw.WINDOW_META))
        for label in ("All time", "24 hours", "7 days", "30 days"):
            assert label in row
        active = re.findall(r'class="[^"]*wtf-act-filter--active[^"]*"[^>]*>([^<]+)<', row)
        assert active == ["7 days"], active
        assert row.count('aria-current="true"') == 1

    def test_default_marks_all_time_active(self):
        row = _pill_row(_render(window_filter="all", window_meta=nw.WINDOW_META))
        assert re.findall(r'wtf-act-filter--active[^>]*>([^<]+)<', row) == ["All time"]

    def test_rendering_without_the_new_variables_still_works(self):
        # news.html is rendered by older callers/tests that predate the window.
        html = _render()
        assert "All time" in _pill_row(html)

    def test_pills_keep_every_other_filter_and_replace_only_the_window(self):
        html = _render(window_filter="7d", window_meta=nw.WINDOW_META, band_filter="left", province_filter="ON")
        pills = re.findall(r'href="(/news\?[^"]*)"', _pill_row(html))
        assert len(pills) == 4
        assert all("band=left" in p and "province=ON" in p for p in pills)
        by = {p: p for p in pills}
        assert sum("window=24h" in p for p in pills) == 1 and sum("window=7d" in p for p in pills) == 1
        assert sum("window=30d" in p for p in pills) == 1
        assert sum("window=" in p for p in pills) == 3, "'All time' must DROP the parameter, not send window=all"

    def test_no_window_means_no_existing_url_changes(self):
        html = _render(window_filter="all", window_meta=nw.WINDOW_META)
        # The three non-default pills legitimately carry their own window; nothing ELSE may.
        rest = html.replace(_pill_row(html), "")
        assert "window=" not in rest, "with no window chosen no pre-existing URL may carry the parameter"

    def test_every_rebuilt_link_carries_the_chosen_window(self):
        html = _render(window_filter="7d", window_meta=nw.WINDOW_META,
                       sources=[{"name": "CBC", "slug": "cbc", "article_count": 5, "bias_lean": "left", "bias_band": "left"}])
        pill = _pill_row(html)
        others = [h for h in _hrefs(html.replace(pill, "")) ]
        assert len(others) >= 10, f"expected the 10 filter/pager links, found {len(others)}"
        missing = [h for h in others if "window=7d" not in h]
        assert not missing, f"links that would DROP the window when clicked: {missing[:3]}"
        assert re.search(r"window\.location='/news\?outlet=[^']*&window=7d'", html), "outlet icon dropped the window"

    def test_pagination_keeps_the_window(self):
        html = _render(window_filter="30d", window_meta=nw.WINDOW_META, page=2, total_pages=3)
        assert any("page=1" in h and "window=30d" in h for h in _hrefs(html)), "previous-page link"
        assert any("page=3" in h and "window=30d" in h for h in _hrefs(html)), "next-page link"

    def test_a_window_alone_counts_as_an_active_filter_so_clear_all_appears(self):
        # The HEADER link, identified by its glyph: the empty-state paragraph has its own
        # "Clear all filters" link (this test renders no articles) and would match a bare string.
        assert "\u2715 Clear all filters" in _render(window_filter="24h", window_meta=nw.WINDOW_META)
        assert "\u2715 Clear all filters" not in _render(window_filter="all", window_meta=nw.WINDOW_META)
