"""Regression coverage for /news' verdict filter (2026-09-05, task #16
follow-up — the piece deliberately deferred out of
test_news_filters_collapse_and_empty_state.py, migration 078).

The naive plan (move the fact_checks LATERAL earlier into the existing
top_recent CTE, over a bounded window) was measured against the live DB
before writing any code and rejected: verdicts are wildly uneven (verified
10,896 / mixed 5,481 / unverifiable 5,491 / descriptive_reporting 572 /
disputed 532 / mostly_true 92, out of 119,574 articles), so a candidate
window big enough for common verdicts is still nowhere near enough for rare
ones, and every filter combination is its own cache key — the same shape of
abuse this route already survived twice (#5719, the 2026-08-30 bot flood).

The actual fix: articles.latest_verdict (migration 078) is a real indexed
column, kept current by an AFTER trigger on fact_checks rather than by
touching the 6 separate ingest call sites that write fact_checks (a
write-through column update at each site is a correctness footgun — miss
one, or a 7th site added later, and that pipeline's articles silently stop
filtering correctly). Verified live before shipping:
`EXPLAIN ANALYZE ... WHERE latest_verdict = 'disputed'` uses
idx_articles_latest_verdict, 0.6ms — same cost class as province/beat/scope,
not the fact_checks correlated-subquery path.
"""

from __future__ import annotations

import pathlib

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from sqlalchemy import text

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES_PY = REPO_ROOT / "consumer" / "routes.py"
TPL_DIR = REPO_ROOT / "consumer" / "templates"
MIGRATION_078 = REPO_ROOT / "migrations" / "078_articles_latest_verdict.sql"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"

_VALID_VERDICTS = {"verified", "mostly_true", "mixed", "disputed",
                    "unverifiable", "descriptive_reporting"}


def _news_route_body() -> str:
    src = ROUTES_PY.read_text(encoding="utf-8")
    start = src.index("@bp.get(\"/news\")")
    end = src.index("\n@bp.get", src.index("def news():"))
    return src[start:end]


# ────────────────────────── source-inspection (rule #6) ──────────────────

def test_valid_verdicts_matches_the_db_check_constraint_enum():
    src = ROUTES_PY.read_text(encoding="utf-8")
    start = src.index("VALID_VERDICTS = {")
    end = src.index("}", start)
    block = src[start:end]
    for v in _VALID_VERDICTS:
        assert f'"{v}"' in block, f"{v} missing from VALID_VERDICTS"
    assert '"all"' in block


def test_verdict_meta_covers_every_valid_value_exactly_once():
    src = ROUTES_PY.read_text(encoding="utf-8")
    start = src.index("VERDICT_META = [")
    end = src.index("]", start)
    block = src[start:end]
    for v in _VALID_VERDICTS:
        assert block.count(f'"{v}"') == 1, f"{v} should appear exactly once in VERDICT_META"


def test_route_validates_verdict_filter_against_the_allowlist():
    body = _news_route_body()
    assert 'verdict_filter = _req.args.get("verdict", "all")' in body
    assert "if verdict_filter not in VALID_VERDICTS:" in body


def test_route_filters_on_the_indexed_column_not_a_correlated_subquery():
    # Mutation check (house rule #7) run once at authoring time — NOT a
    # permanent test, per feedback_mutation-check-no-runtime-git.md. Before
    # this change, news() had no `verdict` key in filter_clauses at all, and
    # a naive first draft (never shipped) filtered by joining fact_checks
    # directly in top_recent's WHERE — both would fail this assertion.
    body = _news_route_body()
    assert 'filter_clauses["verdict"] = "a.latest_verdict = :verdict"' in body
    assert "SELECT" not in body[body.index('filter_clauses["verdict"]'):
                                 body.index('filter_clauses["verdict"]') + 200]


def test_cache_key_includes_verdict_filter():
    body = _news_route_body()
    ck_line = body[body.index("_ck = ("):body.index(")", body.index("_ck = ("))]
    assert "verdict_filter" in ck_line


def test_verdict_facet_query_joins_bias_scores_for_active_band_filter():
    # Same reasoning already documented for province/beat/scope: _where_except
    # carries 'b.band = :band' whenever a band filter is active, so every
    # facet query needs the join even though it doesn't select from it.
    body = _news_route_body()
    start = body.index("verdict_facet_rows = c.execute")
    end = body.index(")", body.index("mappings().all()", start))
    block = body[start:end]
    assert "LEFT JOIN {S}.bias_scores b" in block
    assert "_where_except('verdict')" in block


# ────────────────────────── migration content ──────────────────────────────

def test_migration_check_constraint_matches_valid_verdicts():
    sql = MIGRATION_078.read_text(encoding="utf-8")
    for v in _VALID_VERDICTS:
        assert f"'{v}'" in sql
    assert "article_latest_verdict_check" in sql


def test_migration_defines_an_index_and_a_trigger():
    sql = MIGRATION_078.read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS idx_articles_latest_verdict" in sql
    assert "published_at DESC" in sql
    assert "CREATE TRIGGER trg_sync_article_latest_verdict" in sql
    assert "AFTER INSERT OR UPDATE OF overall_verdict, checker OR DELETE" in sql


def test_migration_backfill_uses_a_scalar_subquery_not_update_from_lateral():
    # A `FROM LATERAL (...)` correlated to the UPDATE target is not valid
    # Postgres — confirmed live: "invalid reference to FROM-clause entry for
    # table a". Pin the working form so it can't regress back to the broken
    # one. Scoped to the backfill statement itself, not the file as a whole —
    # the migration's own explanatory comment mentions "FROM LATERAL" in prose.
    sql = MIGRATION_078.read_text(encoding="utf-8")
    backfill_start = sql.rindex("UPDATE wtf.articles a")
    backfill = sql[backfill_start:]
    assert "FROM LATERAL" not in backfill
    assert "SET latest_verdict = (" in backfill


# ────────────────────────── DB behaviour: the trigger ─────────────────────

@pytest.fixture()
def verdict_schema(clean_schema, engine):
    """Layers migration 078 onto the standard wtf_test schema (clean_schema
    already has real articles/fact_checks tables from 001_wtf_schema.sql —
    unlike the general _SCHEMA_PATCHES convention, THIS fixture applies the
    real migration, because what's under test here is the trigger itself,
    not just a column's presence."""
    sql = MIGRATION_078.read_text(encoding="utf-8").replace("wtf.", "wtf_test.")
    # NOT split-and-loop like conftest's own _apply() — that naive `;\n`
    # splitter cuts the PL/pgSQL function body's own internal `;` mid-DECLARE
    # (confirmed live: "unterminated dollar-quoted string"). Migration 078
    # has zero bind params, so sending it as one blob is safe — psycopg2's
    # simple query protocol runs multi-statement SQL sequentially either way.
    with engine.begin() as conn:
        conn.execute(text(sql))
    yield


def _insert_article(conn, article_id):
    conn.execute(text("""
        INSERT INTO wtf_test.articles
            (id, source_id, external_id, title, body, url, published_at)
        VALUES (:id, 1, :ext, 'headline', 'body', 'https://example.com/a', NOW())
    """), {"id": article_id, "ext": f"ext-{article_id}"})


def _insert_source(conn):
    conn.execute(text("""
        INSERT INTO wtf_test.sources (id, slug, name, url)
        VALUES (1, 'test-source', 'Test Source', 'https://example.com')
        ON CONFLICT (id) DO NOTHING
    """))


def test_insert_a_factcheck_sets_latest_verdict(verdict_schema, engine):
    with engine.begin() as conn:
        _insert_source(conn)
        _insert_article(conn, 1001)
        before = conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1001"
        )).scalar()
        assert before is None

        conn.execute(text("""
            INSERT INTO wtf_test.fact_checks
                (article_id, claim, verdict, evidence, checker, overall_verdict)
            VALUES (1001, 'a claim', 'mixed', 'evidence', 'real_checker', 'disputed')
        """))
        after = conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1001"
        )).scalar()
        assert after == "disputed"


def test_googlefct_checker_is_ignored(verdict_schema, engine):
    with engine.begin() as conn:
        _insert_source(conn)
        _insert_article(conn, 1002)
        conn.execute(text("""
            INSERT INTO wtf_test.fact_checks
                (article_id, claim, verdict, evidence, checker, overall_verdict)
            VALUES (1002, 'a claim', 'mixed', 'evidence', 'GoogleFCT_v1', 'verified')
        """))
        after = conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1002"
        )).scalar()
        assert after is None


def test_the_newest_non_googlefct_check_wins(verdict_schema, engine):
    with engine.begin() as conn:
        _insert_source(conn)
        _insert_article(conn, 1003)
        conn.execute(text("""
            INSERT INTO wtf_test.fact_checks
                (article_id, claim, verdict, evidence, checker, overall_verdict)
            VALUES (1003, 'claim one', 'mixed', 'evidence', 'checker_a', 'mixed')
        """))
        conn.execute(text("""
            INSERT INTO wtf_test.fact_checks
                (article_id, claim, verdict, evidence, checker, overall_verdict)
            VALUES (1003, 'claim two', 'true', 'evidence', 'checker_b', 'verified')
        """))
        after = conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1003"
        )).scalar()
        assert after == "verified"


def test_updating_overall_verdict_on_an_existing_row_propagates(verdict_schema, engine):
    with engine.begin() as conn:
        _insert_source(conn)
        _insert_article(conn, 1004)
        row_id = conn.execute(text("""
            INSERT INTO wtf_test.fact_checks
                (article_id, claim, verdict, evidence, checker, overall_verdict)
            VALUES (1004, 'a claim', 'unverified', 'evidence', 'checker_c', 'unverifiable')
            RETURNING id
        """)).scalar()
        conn.execute(text(
            "UPDATE wtf_test.fact_checks SET overall_verdict = 'verified' WHERE id = :id"
        ), {"id": row_id})
        after = conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1004"
        )).scalar()
        assert after == "verified"


def test_deleting_the_only_factcheck_row_reverts_to_null(verdict_schema, engine):
    with engine.begin() as conn:
        _insert_source(conn)
        _insert_article(conn, 1005)
        row_id = conn.execute(text("""
            INSERT INTO wtf_test.fact_checks
                (article_id, claim, verdict, evidence, checker, overall_verdict)
            VALUES (1005, 'a claim', 'false', 'evidence', 'checker_d', 'disputed')
            RETURNING id
        """)).scalar()
        assert conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1005"
        )).scalar() == "disputed"

        conn.execute(text("DELETE FROM wtf_test.fact_checks WHERE id = :id"), {"id": row_id})
        after = conn.execute(text(
            "SELECT latest_verdict FROM wtf_test.articles WHERE id = 1005"
        )).scalar()
        assert after is None


def test_check_constraint_rejects_an_invalid_verdict(verdict_schema, engine):
    with pytest.raises(Exception):
        with engine.begin() as conn:
            _insert_article(conn, 1006)
            conn.execute(text(
                "UPDATE wtf_test.articles SET latest_verdict = 'not_a_real_verdict' WHERE id = 1006"
            ))


# ────────────────────────── template render ────────────────────────────────

def _env():
    return Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))


_TPL_CTX = dict(
    total=1, source_count=46, page=1, total_pages=1, page_size=50,
    band_filter="all", province_filter="all", beat_filter="all",
    scope_filter="all", riding_filter="all", ridings=[], beat_meta=[],
    sources=[], band_mix=[], band_facets={}, province_facets={},
    beat_facets={}, scope_facets={}, is_subscriber=True,
    articles_24h=12, clustered_stories_24h=3, blindspot_flags_24h=2,
    today_str="2026-09-05", yesterday_str="2026-09-04",
)


def _article(id=1):
    import datetime
    return {
        "id": id, "title": "headline", "url": "https://example.com/a",
        "published_at": datetime.datetime.now(datetime.timezone.utc),
        "source": "CBC", "source_id": 1, "band": "center", "ai_analyzed": False,
        "province_code": None, "beat": None, "geo_scope": None,
        "cluster_id": id, "cluster_size": None, "coverage_gap_score": None,
        "overall_verdict": None, "mp_mentions": None,
    }


def _render(**overrides):
    ctx = dict(_TPL_CTX)
    ctx["articles"] = [_article()]
    ctx["verdict_filter"] = "all"
    ctx["verdict_meta"] = [
        ("verified", "Verified"), ("disputed", "Disputed"),
    ]
    ctx["verdict_facets"] = {"verified": 10896, "disputed": 532}
    ctx.update(overrides)
    return _env().get_template("news.html").render(**ctx)


def test_verdict_chip_row_renders_with_live_counts():
    html = _render()
    assert "VERDICT" in html
    assert "Verified" in html
    assert "Disputed" in html
    assert '<span class="wtf-act-filter-n">10896</span>' in html
    assert '<span class="wtf-act-filter-n">532</span>' in html


def test_active_verdict_chip_is_marked_active():
    html = _render(verdict_filter="disputed")
    block_start = html.index('span class="wtf-nw-chip-label">VERDICT')
    block_end = html.index("</div>", block_start)
    block = html[block_start:block_end]
    disputed_link_start = block.index("verdict=disputed")
    disputed_link_end = block.index("</a>", disputed_link_start)
    disputed_link = block[disputed_link_start:disputed_link_end]
    assert "wtf-act-filter--active" in disputed_link
    # and the OTHER real chip (verified) must not also be marked active
    verified_link_start = block.index("verdict=verified")
    verified_link_end = block.index("</a>", verified_link_start)
    assert "wtf-act-filter--active" not in block[verified_link_start:verified_link_end]


def test_verdict_filter_expands_the_collapsed_panel():
    html = _render(verdict_filter="verified")
    assert 'id="wtf-news-filters-panel" hidden' not in html
    assert '<span class="wtf-act-filter-n">1</span>' in html.split(
        'id="wtf-news-filters-toggle"')[1].split("</button>")[0]


def test_band_and_province_links_carry_the_active_verdict_through():
    # Switching band/province/beat/scope/riding must not silently drop an
    # active verdict filter — every chip link is a full-page navigation.
    html = _render(verdict_filter="mixed")
    assert "verdict=mixed" in html
    # spot-check the band row and the province row both carry it
    band_link = html[html.index("wtf-nw-band-row"):html.index("wtf-news-mix", html.index("wtf-nw-band-row"))]
    assert "verdict={{" not in band_link  # must be rendered, not literal Jinja
    assert "verdict=mixed" in band_link


def test_no_verdict_facet_count_renders_as_empty_not_zero():
    html = _render(verdict_meta=[("mostly_true", "Mostly True")], verdict_facets={})
    block_start = html.index('span class="wtf-nw-chip-label">VERDICT')
    block_end = html.index("</div>", block_start)
    block = html[block_start:block_end]
    assert "wtf-act-filter--empty" in block
    assert "<span class=\"wtf-act-filter-n\">0</span>" not in block
