"""Regression coverage for /claims' aggregate stat row (2026-09-04, batch 11,
task #6284).

Scope note: `wtf.claim_tracker` holds 0 rows platform-wide (verified live via
`docker exec archie_database psql -U archie -d wtf -tAc "select count(*) from
wtf.claim_tracker"`), so this batch intentionally implements ONLY the stat-row
query — it will honestly render "0" / "0%" until real fact-check data lands.
The table restyle, source-citation column, taxonomy change, and page-level
paywall gate box from the design mockup are all deferred (see the PR body):
building them against an empty table would mean guessing at layout for data
nobody has seen yet, and the taxonomy the mockup uses (Established/Contested/
Developing) does not exist in `claim_tracker_status_check` at all (real values:
pending/verified_true/partially_true/misleading/false/contested) — inventing
a mapping onto it would be exactly the kind of fabrication this project's
rules forbid.

Two layers, matching house convention (test_mp_hero_links.py /
test_owners_concentration_stats.py):
  1. Source-inspection of consumer/routes.py — the aggregate SQL and percent
     math live in Python, not in the template, so that's where they must be
     tested (rule #6 in the batch-11 brief: route/query logic -> read the
     function body as text).
  2. Jinja render tests of claims.html via the same
     ChoiceLoader([DictLoader({"base.html": stub}), FileSystemLoader(...)])
     pattern as the other batch-11/10 template tests — no live Flask app, no
     live DB connection inside the test.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _routes_source() -> str:
    return ROUTES.read_text(encoding="utf-8")


def _claims_index_body() -> str:
    src = _routes_source()
    start = src.index("def claims_index")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def _render(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    base_ctx = dict(claims=[], is_subscriber=False, active_status="all")
    base_ctx.update(ctx)
    return env.get_template("claims.html").render(**base_ctx)


# ── source-inspection: the aggregate query + percent math ──────────────────

def test_stat_query_excludes_pending_like_the_list_query_does():
    src = _routes_source()
    start = src.index("def _claim_stat_tiles")
    end = src.index("\n@bp.get", start + 1)
    body = src[start:end]
    assert "status != 'pending'" in body
    assert "GROUP BY status" in body


def test_stat_row_is_unfiltered_by_the_status_query_param():
    """The totals row must not silently change when a filter chip is
    clicked -- it queries the tracker directly, not the paginated `rows`
    list (which is capped at LIMIT 50 and may be status-filtered)."""
    src = _routes_source()
    start = src.index("def _claim_stat_tiles")
    end = src.index("\n@bp.get", start + 1)
    body = src[start:end]
    assert "params" not in body
    assert ":status" not in body


def test_claims_index_calls_the_stat_helper_and_passes_it_to_the_template():
    body = _claims_index_body()
    assert "_claim_stat_tiles(c, S)" in body
    assert "claim_stats=claim_stats" in body


def test_claims_index_defaults_claim_stats_to_empty_on_any_failure():
    """Mirrors the existing `claims = []` except-path -- a query failure
    must never 500 the page, and must never leave claim_stats stale from a
    partially-successful try block."""
    body = _claims_index_body()
    except_idx = body.index("except Exception:")
    except_block = body[except_idx:body.index("subscribed = is_subscriber()")]
    assert "claim_stats = []" in except_block


def test_percent_math_guards_division_by_zero():
    """With 0 rows platform-wide today, total_checked is 0 for every status
    -- the pct expression must not raise ZeroDivisionError."""
    src = _routes_source()
    start = src.index("def _claim_stat_tiles")
    end = src.index("\n@bp.get", start + 1)
    body = src[start:end]
    assert "if total_checked else 0" in body


def test_no_established_contested_developing_taxonomy_invented():
    """The mockup's 3-way taxonomy has no counterpart in
    claim_tracker_status_check (verified live: pending/verified_true/
    partially_true/misleading/false/contested -- no 'Established', no
    'Developing' state at all). Guards against re-introducing the taxonomy
    mismatch the audit flagged, e.g. via a label-mapping dict."""
    src = _routes_source()
    start = src.index("def _claim_stat_tiles")
    end = src.index("\n@bp.get", start + 1)
    body = src[start:end]
    for invented_label in ("Established", "Developing"):
        assert invented_label not in body


# ── template rendering ──────────────────────────────────────────────────

def test_stat_row_renders_on_index_with_real_zero_data():
    """The exact shape /claims produces today: claim_tracker is empty, so
    every tile is a real, honestly-computed zero -- not hidden, not faked."""
    zero_tiles = [
        {"label": "Claims checked", "value": 0, "detail": None},
        {"label": "Verified True", "value": "0%", "detail": "0 claims"},
        {"label": "Partially True", "value": "0%", "detail": "0 claims"},
        {"label": "Misleading", "value": "0%", "detail": "0 claims"},
        {"label": "False", "value": "0%", "detail": "0 claims"},
        {"label": "Contested", "value": "0%", "detail": "0 claims"},
    ]
    html = _render(claim_stats=zero_tiles)
    assert "Claims checked" in html
    tiles_start = html.index("wtf-a-tiles")
    tiles_end = html.index("</div>\n</div>", tiles_start) + len("</div>\n</div>")
    tiles_html = html[tiles_start:tiles_end]
    assert tiles_html.count("0 claims") == 5


def test_stat_row_renders_real_nonzero_percentages():
    tiles = [
        {"label": "Claims checked", "value": 4, "detail": None},
        {"label": "Verified True", "value": "50%", "detail": "2 claims"},
        {"label": "Contested", "value": "25%", "detail": "1 claim"},
    ]
    html = _render(claim_stats=tiles)
    assert "50%" in html
    assert "2 claims" in html
    assert "1 claim<" in html  # singular "claim" (not "claims") for a count of 1


def test_stat_row_absent_when_claim_stats_not_passed():
    """The per-politician page (claims_by_politician) never passes
    claim_stats -- the sitewide totals row must not appear there."""
    html = _render(politician_slug="jane-doe", politician_name="Jane Doe")
    assert "wtf-a-tiles" not in html


def test_stat_row_absent_on_index_when_claim_stats_is_empty():
    """The route's except-path sets claim_stats=[] on a query failure --
    the row must not render an empty shell in that case."""
    html = _render(claim_stats=[])
    assert "wtf-a-tiles" not in html


def test_existing_filter_bar_and_claim_list_still_render():
    """Regression guard: adding the stat row must not disturb the existing
    index-page filter bar or the claim-card list."""
    html = _render(claim_stats=[{"label": "Claims checked", "value": 0, "detail": None}])
    assert "wtf-claims-filters" in html
    assert 'href="/claims?status=contested"' in html
