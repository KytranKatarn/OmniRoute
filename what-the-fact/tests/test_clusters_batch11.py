"""Regression coverage for /clusters' batch-11 filters + sort (#6149, 2026-09-04).

Pure imports + a Jinja render harness — no DB, no network, no Flask app
context, so this cannot silently SKIP. Same house pattern as
test_owners_concentration_stats.py / test_mp_hero_links.py.

Adds: a search box (event / outlet / beat), beat / size / median-band
filter dropdowns, and a named sort control (Spread / Size / Most recent /
Slowest pickup) — all plain GET query params, validated against closed sets
in `_cluster_filters`, and built back into links by `_cluster_qs`. Mirrors
/archive's `_archive_filters`/`_archive_qs`.

Mutation-check performed before shipping this file (not baked in as a live
git-diff, since referencing a moving `HEAD` inside a permanent test would be
meaningless the moment this lands): at the pre-fix commit,
`git show HEAD:what-the-fact/consumer/routes.py | grep -c
"_cluster_filters\\|_cluster_qs\\|_CLUSTER_SIZES\\|_CLUSTER_SORTS"` and
`git show HEAD:what-the-fact/consumer/templates/clusters.html | grep -c
'name="q"\\|name="beat"\\|name="size"\\|name="median"'` both returned 0 —
none of the symbols or markup exercised below existed before this change, so
none of these assertions can be a test that "cannot fail".

Deferred, and NOT tested here because it isn't built: the design mockup's
expandable inline per-cluster detail body (per-outlet grid, quote-flip) —
the card still links out to /cluster/<id>, unchanged from before this PR.
"""
from __future__ import annotations

import pathlib
import re
import sys

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TPL_DIR = ROOT / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"

from consumer.routes import (  # noqa: E402
    _BAND_ORDER,
    _CLUSTER_SIZE_HAVING,
    _CLUSTER_SIZES,
    _CLUSTER_SORTS,
    _CLUSTER_WINDOWS,
    _cluster_filters,
    _cluster_qs,
    VALID_BEATS,
)


class _Args(dict):
    """Minimal stand-in for Flask's `request.args` — `_cluster_filters` only
    ever calls `.get(name)` on it, which plain `dict` already provides."""


# ───────────────────────────────────────────────── _cluster_filters (closed sets)

def test_defaults_when_nothing_is_passed():
    assert _cluster_filters(_Args()) == {
        "days": 7, "sort": "spread", "q": "",
        "beat": "all", "size": "all", "median": "all",
    }


def test_days_outside_the_closed_set_falls_back_to_7():
    assert _cluster_filters(_Args(days="14"))["days"] == 7


def test_non_numeric_days_does_not_raise():
    assert _cluster_filters(_Args(days="banana"))["days"] == 7


def test_unknown_sort_falls_back_to_spread():
    assert _cluster_filters(_Args(sort="alphabetical"))["sort"] == "spread"


def test_unknown_beat_never_reaches_sql_falls_back_to_all():
    assert _cluster_filters(_Args(beat="<script>"))["beat"] == "all"


def test_unknown_size_falls_back_to_all():
    assert _cluster_filters(_Args(size="huge"))["size"] == "all"


def test_unknown_median_falls_back_to_all():
    assert _cluster_filters(_Args(median="purple"))["median"] == "all"


def test_a_real_beat_and_a_real_median_pass_through():
    f = _cluster_filters(_Args(beat="sports", median="center-left"))
    assert f["beat"] == "sports"
    assert f["median"] == "center-left"


def test_search_text_is_stripped_and_capped_at_120():
    f = _cluster_filters(_Args(q="  " + "x" * 200 + "  "))
    assert f["q"] == "x" * 120
    assert len(f["q"]) == 120


# ────────────────────────────────────────── _CLUSTER_SIZES / _CLUSTER_SORTS shape

def test_every_size_bucket_except_all_has_a_having_clause():
    for key in _CLUSTER_SIZES:
        if key == "all":
            assert key not in _CLUSTER_SIZE_HAVING
        else:
            assert key in _CLUSTER_SIZE_HAVING, f"{key!r} has a label but no SQL"


def test_size_buckets_match_the_design_mockup_thresholds():
    """12+ / 6-11 / under-6 — the mockup's #cl-size options
    (design-handoff/wtf-clusters.html), not an invented scheme."""
    assert _CLUSTER_SIZE_HAVING["big"] == "COUNT(DISTINCT a.source_id) >= 12"
    assert _CLUSTER_SIZE_HAVING["mid"] == "COUNT(DISTINCT a.source_id) BETWEEN 6 AND 11"
    assert _CLUSTER_SIZE_HAVING["small"] == "COUNT(DISTINCT a.source_id) < 6"


def test_the_four_sort_keys_match_the_design_mockup():
    """Size / Spread / Most recent / Slowest pickup — the mockup's
    .wtf-dv-sort buttons (data-s="size|spread|recent|pickup")."""
    assert set(_CLUSTER_SORTS) == {"size", "spread", "recent", "pickup"}
    assert _CLUSTER_SORTS["pickup"][0] == "Slowest pickup"


def test_pickup_sort_orders_by_a_real_derived_span_not_recency():
    """'Slowest pickup' must reference the derived pickup_span column — if it
    quietly fell back to `m.last_pub DESC` it would be identical to 'recent'."""
    assert "pickup_span" in _CLUSTER_SORTS["pickup"][1]
    assert _CLUSTER_SORTS["pickup"][1] != _CLUSTER_SORTS["recent"][1]


def test_default_sort_is_still_spread_first():
    """The page's whole claim is framing spread — adding a sort control must
    not quietly change the ordering a reader saw before this PR."""
    assert _cluster_filters(_Args())["sort"] == "spread"
    assert _CLUSTER_SORTS["spread"][1].startswith("spread DESC")


def test_median_filter_uses_the_same_band_scale_the_badge_already_renders():
    """A second copy of the band list is how the filter and the median badge
    (`_BAND_ORDER` in routes.py) drift apart."""
    assert set(_BAND_ORDER) == {"left", "center-left", "center", "center-right", "right"}


# ──────────────────────────────────────────────────────────────── _cluster_qs

def test_qs_keeps_real_filters():
    qs = _cluster_qs(_cluster_filters(_Args(beat="sports", q="jays")))
    assert "beat=sports" in qs
    assert "q=jays" in qs
    assert "size=" not in qs
    assert "median=" not in qs


def test_qs_override_replaces_without_mutating_the_input_dict():
    f = _cluster_filters(_Args(sort="spread"))
    qs = _cluster_qs(f, sort="pickup")
    assert "sort=pickup" in qs
    assert f["sort"] == "spread"


def test_qs_clear_drops_every_filter_but_keeps_the_window_and_sort():
    f = _cluster_filters(_Args(days="30", q="x", beat="sports", size="big", median="left"))
    cleared = _cluster_qs({**f, "q": "", "beat": "all", "size": "all", "median": "all"})
    assert cleared == "/clusters?days=30&sort=spread"


# ───────────────────────────────────────────────── template: the filter form

def _render_clusters(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("clusters.html").render(**ctx)


def _base_ctx(**over):
    f = {"days": 7, "sort": "spread", "q": "", "beat": "all", "size": "all", "median": "all"}
    f.update(over)
    return dict(
        clusters=[], totals={"qualifying": 0, "with_spread": 0, "blindspot_seeds": 0, "widest": 0},
        f=f, days=f["days"], windows=_CLUSTER_WINDOWS,
        # VALID_BEATS contains "all" as a literal member — excluded the same
        # way the route does, or this fixture would mask the route's own
        # double-"All"-option bug instead of catching it.
        beats=sorted(VALID_BEATS - {"all"}), sizes=_CLUSTER_SIZES, medians=_BAND_ORDER,
        shown=0,
        url_windows=[(w, f"/clusters?days={w}") for w in _CLUSTER_WINDOWS],
        url_sorts=[(k, s[0], f"/clusters?sort={k}") for k, s in _CLUSTER_SORTS.items()],
        url_clear="/clusters",
    )


def test_beat_dropdown_never_doubles_the_all_option():
    """VALID_BEATS literally contains "all" as one of its own members (see
    /news' beat_filter validation) — a naive `sorted(VALID_BEATS)` would
    render a second, redundant `<option value="all">All</option>` right
    after the dropdown's own hand-written "Every beat" option."""
    html = _render_clusters(**_base_ctx())
    idx = html.find('name="beat"')
    snippet = html[idx:idx + 400]
    assert snippet.count('value="all"') == 1


def test_the_search_box_and_all_three_dropdowns_render():
    html = _render_clusters(**_base_ctx())
    assert 'name="q"' in html
    assert 'name="beat"' in html
    assert 'name="size"' in html
    assert 'name="median"' in html


def test_the_sort_row_renders_all_four_named_directions():
    html = _render_clusters(**_base_ctx())
    for label in ("Spread", "Size", "Most recent", "Slowest pickup"):
        assert label in html


def _select_block(html: str, name: str) -> str:
    start = html.index(f'name="{name}"')
    return html[start:html.index("</select>", start)]


def test_a_selected_beat_is_marked_selected_not_silently_dropped():
    html = _render_clusters(**_base_ctx(beat="sports"))
    beat_block = _select_block(html, "beat")
    assert 'value="sports" selected' in beat_block
    # and no OTHER beat option is also (wrongly) marked selected
    assert beat_block.count(" selected") == 1


def test_empty_state_names_filters_only_when_a_filter_is_active():
    cleared = _render_clusters(**_base_ctx())
    filtered = _render_clusters(**_base_ctx(beat="sports"))
    assert "carried by two or more" in cleared
    assert "matches these filters" in filtered
    # and the unfiltered page must NOT show the filtered copy, or vice versa
    assert "matches these filters" not in cleared
    assert "carried by two or more" not in filtered


def test_clear_link_is_reachable_from_the_page():
    html = _render_clusters(**_base_ctx(beat="sports", q="jays"))
    assert 'href="/clusters"' in html


def test_no_template_uses_a_filter_this_app_does_not_register():
    """Same class-1 guard as test_clusters_index.py, re-checked here because
    this PR adds new `|replace`/`|title` usages to the same template — this
    app registers NO custom Jinja filters, so an unknown one is a 500, not a
    no-op."""
    from jinja2.filters import FILTERS

    builtin = set(FILTERS)
    body = (TPL_DIR / "clusters.html").read_text()
    used = set(re.findall(r"\|\s*([a-zA-Z_][a-zA-Z0-9_]*)", body))
    unknown = sorted(used - builtin)
    assert not unknown, (
        f"clusters.html uses filter(s) this app never registers: {unknown} — "
        "that is a TemplateAssertionError at render time, not a no-op"
    )
