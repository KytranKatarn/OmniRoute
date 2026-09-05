"""Regression coverage for /archive's batch-11 additions (2026-09-04, #6149).

Implemented this batch (all real, server-verified — see routes.py):
  · Custom date range (date_from/date_to), an ALTERNATIVE to the fixed
    7/30/90/365 windows, never combined with them.
  · CSV export (/archive/export.csv), gated on the same is_subscriber() the
    page itself already uses — no new gating rule, no scope change.
  · A BLINDSPOT badge driven by the real story_clusters.coverage_gap_score
    signal (same threshold /blindspot already uses: 0 < gap <= 0.15).
  · A copy-link button (progressive enhancement — the href already works
    with scripting off).
  · A lean-mix bar computed from rows[] already in the template context
    (no extra query), honestly labelled "on this page".

Deliberately NOT built (see the PR description for the reasoning): saved /
unread lists (need per-user accounts), a rollup analytics view (needs a
dedicated build), and a 3-tier pricing comparison (WTF has exactly one real
paid tier today — Starter, $4.99/mo — so a 3-tier display would have to
invent a "Research" tier and price that do not exist; `test_no_fabricated_
pricing_tier_was_added` below pins that as a deliberate absence).
"""

from __future__ import annotations

import datetime
import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"

# Mirrors consumer/routes.py's _ARCHIVE_SORTS — only the label at index 0 is
# read by the template (`sorts[f.sort][0]`), so this is kept minimal rather
# than importing the DB-touching routes module (house style: source-inspect
# routes.py as text; render templates against a hand-built stub context).
_SORTS = {
    "filed": ("Filed · newest", "last_pub DESC"),
    "oldest": ("Filed · oldest", "last_pub ASC"),
    "outlets": ("Outlets · most", "outlets DESC, last_pub DESC"),
    "headline": ("Headline · A–Z", "title ASC"),
    "outlet": ("Outlet · A–Z", "outlet ASC, last_pub DESC"),
}


def _routes_src() -> str:
    return ROUTES.read_text(encoding="utf-8")


def _func_body(name: str) -> str:
    """Source-inspection helper (house style — see test_mp_hero_links.py).

    Reads consumer/routes.py as TEXT and slices out one function's body
    between `def <name>` and the next top-level `def`/`@bp.` line, rather
    than importing the module (which drags in sqlalchemy engine creation
    and Flask app-context assumptions the test suite deliberately avoids).
    """
    src = _routes_src()
    start = src.index(f"def {name}(")
    # next top-level def or decorator after this one
    rest = src[start + 1:]
    end_markers = [rest.index(m) for m in ("\ndef ", "\n@bp.") if m in rest]
    end = start + 1 + (min(end_markers) if end_markers else len(rest))
    return src[start:end]


def _row(cluster_id=1, title="Headline", outlet="CBC", outlets=1, lean="left",
         verdict="verified", last_pub=None, is_blindspot=False, age_text="1d"):
    return {
        "cluster_id": cluster_id, "title": title, "outlet": outlet,
        "outlets": outlets, "lean": lean, "verdict": verdict,
        "last_pub": last_pub or datetime.datetime(2026, 9, 1, 12, 0),
        "article_id": cluster_id, "coverage_gap_score": None,
        "is_blindspot": is_blindspot, "age_text": age_text,
    }


_F_BASE = dict(
    view="story", days=30, sort="filed", page=1, q="",
    lean="all", verdict="all", beat="all", lang="all", outlet="all",
    date_from=None, date_to=None,
)


def _render(rows, *, is_subscriber=True, gated=False, cap=10, total=None,
            f_overrides=None, url_export="/archive/export.csv?view=story",
            url_permalink="/archive?days=30"):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    f = dict(_F_BASE)
    if f_overrides:
        f.update(f_overrides)
    return env.get_template("archive.html").render(
        rows=rows, total=(total if total is not None else len(rows)), f=f,
        sorts=_SORTS, windows=(7, 30, 90, 365),
        outlets=[{"name": "CBC", "n": 12}], beats=["business", "sports"],
        page_size=50, is_subscriber=is_subscriber, gated=gated, cap=cap,
        url_story="/archive?view=story", url_article="/archive?view=article",
        url_windows=[(7, "/archive?days=7"), (30, "/archive?days=30"),
                     (90, "/archive?days=90"), (365, "/archive?days=365")],
        url_sorts=[(k, v[0], f"/archive?sort={k}") for k, v in _SORTS.items()],
        url_clear="/archive", url_prev=None, url_next="/archive?page=2",
        url_export=url_export, url_permalink=url_permalink,
    )


# ── date range: parsed on the route side, never string-interpolated ────────

def test_date_range_parsed_via_a_real_calendar_date_parser():
    body = _func_body("_parse_archive_date")
    assert "datetime.date.fromisoformat" in body, (
        "an invalid date_from/date_to must be dropped, not crash the page — "
        "fromisoformat is what makes that a caught ValueError"
    )
    assert "except (ValueError, AttributeError)" in body


def test_date_range_where_clause_is_parameterised_not_interpolated():
    body = _func_body("_archive_where")
    assert ":date_from" in body and ":date_to_excl" in body, (
        "the date range must bind as SQL parameters, matching every other "
        "filter in this function — never f-string the date value into the SQL"
    )
    # Guard against the f-string-interpolation regression this file is
    # otherwise full of legitimate examples of (the whole WHERE builder uses
    # f-strings for column/table names) — the VALUES must never join that way.
    assert "{f['date_from']}" not in body and '{f["date_from"]}' not in body


def test_date_range_replaces_the_days_window_never_combines_with_it():
    body = _func_body("_archive_where")
    # The days-window predicate must live in the else-branch of the
    # date-range check, not be appended unconditionally alongside it.
    idx_range = body.index("date_from")
    idx_days = body.index("make_interval(days")
    assert idx_range < idx_days, "date-range branch must be checked first"
    assert "else:" in body[idx_range:idx_days]


def test_reversed_date_range_is_swapped_not_rejected():
    body = _func_body("_archive_filters")
    assert "date_from, date_to = date_to, date_from" in body


# ── CSV export: gated on the SAME is_subscriber(), never a new rule ────────

def test_export_route_checks_is_subscriber_before_querying_data():
    body = _func_body("archive_export")
    assert "if not is_subscriber():" in body
    gate_idx = body.index("if not is_subscriber():")
    query_idx = body.index("_archive_export_rows(f)")
    assert gate_idx < query_idx, "the gate must run before any row is fetched"
    assert 'redirect("/join?gated=export")' in body


def test_export_is_capped_not_an_unbounded_dump():
    body = _func_body("_archive_export_rows")
    assert "_ARCHIVE_EXPORT_LIMIT" in body
    assert "LIMIT :lim" in body


def test_export_route_present_in_template_only_when_subscriber():
    html = _render([_row()], is_subscriber=True,
                    url_export="/archive/export.csv?view=story")
    assert 'href="/archive/export.csv?view=story"' in html
    assert ">Export CSV<" in html


def test_export_is_a_locked_join_link_for_non_subscribers():
    html = _render([_row()], is_subscriber=False)
    assert 'href="/join?gated=export"' in html
    # The real download link must never leak into the markup for a
    # non-subscriber — only the CTA to /join should be present.
    assert "/archive/export.csv" not in html


def test_csv_formula_injection_is_defused():
    body = _func_body("_csv_safe")
    assert '"=", "+", "-", "@"' in body or "'=', '+', '-', '@'" in body
    assert "leading apostrophe" in body.lower() or "'\\'' + s" in body or "(\"'\" + s)" in body


# ── BLINDSPOT badge: real signal, same threshold as /blindspot ─────────────

def test_blindspot_threshold_matches_the_blindspot_pages_own_default():
    src = _routes_src()
    assert "_ARCHIVE_BLINDSPOT_MAX_GAP = 0.15" in src
    # /blindspot's own predicate, so a future change to one is visible
    # against the other rather than silently diverging.
    assert "max_gap=0.15" in src


def test_blindspot_badge_renders_only_for_flagged_rows():
    html = _render([_row(cluster_id=1, is_blindspot=True, title="Flagged story"),
                     _row(cluster_id=2, is_blindspot=False, title="Ordinary story")])
    idx_flagged = html.index("Flagged story")
    idx_ordinary = html.index("Ordinary story")
    # BLINDSPOT badge text must appear right after the flagged row's title
    # and not appear at all near the ordinary row's.
    window_flagged = html[idx_flagged:idx_flagged + 300]
    window_ordinary = html[idx_ordinary:idx_ordinary + 300]
    assert "BLINDSPOT" in window_flagged
    assert "BLINDSPOT" not in window_ordinary


def test_no_blindspot_badge_anywhere_when_nothing_is_flagged():
    html = _render([_row(is_blindspot=False)])
    assert "BLINDSPOT" not in html


# ── copy link: a plain permalink anchor, NEVER a <script> ──────────────────
# This page has a pre-existing, tested invariant — every control works with
# scripting off (test_archive_index.py::test_the_page_works_without_
# javascript) — so "Copy link" must be a real, working <a> and nothing else.

def test_copy_link_is_a_plain_anchor_to_the_canonical_permalink():
    html = _render([_row()], url_permalink="/archive?days=30&lean=left")
    assert '>Copy link<' in html
    assert 'href="/archive?days=30&lean=left"' in html


def test_archive_page_never_emits_a_script_tag():
    # Redundant with the pre-existing site-wide guard, kept here too so a
    # regression in THIS batch's own diff fails locally and specifically.
    html = _render([_row()])
    assert "<script" not in html.lower()


# ── lean mix: computed from rows already in context, honestly scoped ───────

def test_lean_mix_percentages_computed_from_the_current_page_only():
    rows = ([_row(cluster_id=i, lean="left") for i in range(3)]
            + [_row(cluster_id=4, lean="right")]
            + [_row(cluster_id=5, lean=None)])
    html = _render(rows, total=500)  # total is corpus-wide; must not leak in
    assert "Lean mix of what's showing here" in html
    # 3 of 4 SCORED rows are left -> 75%; 1 of 4 is right -> 25%.
    assert "Left 75%" in html
    assert "Right 25%" in html
    assert "1 unscored" in html
    assert "on this page" in html


def test_lean_mix_block_absent_when_no_row_is_scored():
    html = _render([_row(lean=None), _row(cluster_id=2, lean=None)])
    assert "Lean mix of what's showing here" not in html


def test_lean_mix_never_divides_by_the_corpus_total():
    # A single scored row must read 100%, regardless of how large `total`
    # (the corpus-wide count) is — dividing by `total` instead of the
    # on-page scored count would silently read near-0% for any real filter.
    html = _render([_row(lean="center")], total=28_204)
    assert "Center 100%" in html


# ── deliberately deferred pieces stay absent ────────────────────────────────

def test_no_fabricated_pricing_tier_was_added():
    html = _render([_row()], is_subscriber=False, gated=True, cap=1, total=1)
    # WTF has exactly one real paid tier (Starter, $4.99/mo — consumer/
    # tiers.py + connect.html). A "Research"/$19 tier, as the design mockup
    # shows, does not exist as a real product and must never be fabricated.
    assert "Research" not in html
    assert "$19" not in html


def test_saved_and_unread_are_still_documented_as_deferred():
    html = _render([_row()])
    assert "account feature we have not built" in html
