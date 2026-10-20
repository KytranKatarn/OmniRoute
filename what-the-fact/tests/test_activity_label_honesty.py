"""/activity tile labels must say what their query counts; /methodology must list every verdict (#7328 review).

Found 2026-10-19 comparing the live /activity numbers with consumer/routes.py and the live DB:
F.A.C.T. "verdicts recorded" counted ALL audit_trail rows, V.E.R.I.F.Y. "claims checked" counted
quick-pass rows that are 100% 'unverified' (extracted, not checked), L.O.C.A.L. "articles placed"
counts finished lookups incl. 'unmappable', and I.N.K. read articles.ingested_at while its feed rows
are story_clusters. /methodology omitted `mostly_true`, which the system emits.
"""

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "consumer" / "routes.py").read_text()
ACTIVITY = (ROOT / "consumer" / "templates" / "activity.html").read_text()
METHOD = (ROOT / "consumer" / "templates" / "methodology.html").read_text()


def _rows():
    tree = ast.parse(ROUTES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_AGENT_SOURCES" for t in node.targets):
            # a row may carry an optional 5th element that is a Name (the predicate constant), so parse by hand
            rows = []
            for elt in node.value.elts:
                rows.append([ast.literal_eval(e) if isinstance(e, ast.Constant) else ast.unparse(e) for e in elt.elts])
            return rows
    raise AssertionError("_AGENT_SOURCES not found")


def _sources():
    """Unique-name rows (V.E.R.I.F.Y. appears twice since #7339: assessed headline + extracted volume)."""
    return {row[0]: row for row in _rows() if row[0] != "V.E.R.I.F.Y."}


def _verify_rows():
    return [row for row in _rows() if row[0] == "V.E.R.I.F.Y."]


def test_no_tile_claims_verdicts_or_checks_it_does_not_count():
    src = _sources()
    assert "verdict" not in src["F.A.C.T."][3]  # it counts audit_trail rows, not verdicts
    assert src["F.A.C.T."][3].startswith("audit events")
    assert "unmappable" in src["L.O.C.A.L."][3]  # geo_processed_at is stamped on unmappable too


def test_verify_shows_both_the_assessed_headline_and_the_extraction_volume():
    """#7339 owner decision: full-pass claims are the headline; total extracted stays visible beside it."""
    assessed, extracted = _verify_rows()
    assert "full pass" in assessed[3] and len(assessed) == 5  # restricted by a predicate
    assert assessed[4] == "_FULL_PASS_CLAIMS_SQL"
    assert "extracted" in extracted[3] and "quick" in extracted[3] and len(extracted) == 4  # unrestricted
    assert "checked" not in extracted[3]  # quick-pass claims are extracted, not checked


def test_the_assessed_predicate_counts_full_tier_and_named_agent_rows_only():
    """Measured 2026-10-19: of 4,636 claim rows in 24h only 285 were assessed; the rest were quick-pass
    placeholders (100% unverified), Google Fact Check lookups that found nothing (0 evidence chars) and
    heuristic rows. 'Not quick' would have counted the 1,203 empty partner lookups as assessments."""
    assert "def _full_pass_claims_sql(alias" in ROUTES
    assert "{alias}analysis_tier LIKE '%full'" in ROUTES  # quick_v1+full, quick_v1_failed+full
    assert "{alias}agent_name IS NOT NULL" in ROUTES  # named newsroom agents write untiered rows
    assert "NOT IN ('quick_v1'" not in ROUTES  # the first, wrong predicate: it counted partner lookups


def test_the_stats_query_qualifies_analysis_tier_because_articles_has_one_too():
    stats_sql = ROUTES.split("AS fact_checked_articles,", 1)[1].split("AS fact_checked_full_articles", 1)[0]
    assert "_full_pass_claims_sql('f.')" in stats_sql
    assert "a.suppressed_reason IS NULL" in stats_sql  # same suppression rule as every other published count


def test_throughput_counts_only_the_predicate_rows_but_keeps_the_window_over_the_whole_table():
    body = ROUTES.split("def _activity_agent_throughput", 1)[1].split("out = []", 1)[0]
    assert "for name, table, col, what, *_pred in _AGENT_SOURCES" in body
    assert "FILTER (WHERE {col} > now() - interval '24 hours'{extra})" in body
    assert "min({col})" in body and "min({col}) FILTER" not in body  # window/partial stay table-wide (comparable rates)


def test_ink_tile_reads_the_same_table_as_its_feed_and_methodology():
    src = _sources()
    assert src["I.N.K."][1] == "story_clusters"
    assert src["I.N.K."][3] == "clusters formed"
    feed = ROUTES.split('"I.N.K.": f"""', 1)[1].split('"""', 1)[0]
    assert "story_clusters" in feed  # tile and feed agree


def test_a_tile_label_never_reuses_another_agents_label():
    labels = [row[3] for row in _rows()]
    assert len(labels) == len(set(labels))  # F.A.C.T. and I.N.K. both said "...ingested" before


def test_coverage_cards_do_not_overclaim_and_show_both_verify_numbers():
    assert "'Fact-checked'" not in ACTIVITY
    assert "'Full AI analysis'" not in ACTIVITY
    assert "quick or full" in ACTIVITY  # tier-1 quick pass counts as analysed; say so
    assert "Fact-checked (full pass)" in ACTIVITY and "Claims extracted (any pass)" in ACTIVITY
    assert "stats.fact_checked_full_articles | default(0)" in ACTIVITY  # an older cached snapshot lacks the key
    assert "extracted, not verified" in ACTIVITY


def test_methodology_lists_every_article_level_verdict():
    block = METHOD.split("FACT-CHECK METHODOLOGY", 1)[1]
    for verdict in ("verified", "mostly_true", "mixed", "disputed", "unverifiable", "descriptive_reporting"):
        assert re.search(rf"<strong>{verdict}</strong>", block), f"{verdict} missing from /methodology"


def test_methodology_says_quick_pass_claims_are_not_checked():
    block = METHOD.split("FACT-CHECK METHODOLOGY", 1)[1]
    assert "Two passes record claims" in block
    assert "not checked" in block
