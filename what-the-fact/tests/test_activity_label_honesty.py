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


def _sources():
    tree = ast.parse(ROUTES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "_AGENT_SOURCES" for t in node.targets):
            return {row[0]: row for row in ast.literal_eval(node.value)}
    raise AssertionError("_AGENT_SOURCES not found")


def test_no_tile_claims_verdicts_or_checks_it_does_not_count():
    src = _sources()
    assert "verdict" not in src["F.A.C.T."][3]  # it counts audit_trail rows, not verdicts
    assert src["F.A.C.T."][3].startswith("audit events")
    assert "checked" not in src["V.E.R.I.F.Y."][3]  # quick-pass claims are extracted, not checked
    assert "quick" in src["V.E.R.I.F.Y."][3]
    assert "unmappable" in src["L.O.C.A.L."][3]  # geo_processed_at is stamped on unmappable too


def test_ink_tile_reads_the_same_table_as_its_feed_and_methodology():
    src = _sources()
    assert src["I.N.K."][1] == "story_clusters"
    assert src["I.N.K."][3] == "clusters formed"
    feed = ROUTES.split('"I.N.K.": f"""', 1)[1].split('"""', 1)[0]
    assert "story_clusters" in feed  # tile and feed agree


def test_a_tile_label_never_reuses_another_agents_label():
    labels = [row[3] for row in _sources().values()]
    assert len(labels) == len(set(labels))  # F.A.C.T. and I.N.K. both said "...ingested" before


def test_coverage_cards_do_not_overclaim():
    assert "'Fact-checked'" not in ACTIVITY
    assert "'Full AI analysis'" not in ACTIVITY
    assert "quick or full" in ACTIVITY  # tier-1 quick pass counts as analysed; say so
    assert "extracted not verified" in ACTIVITY


def test_methodology_lists_every_article_level_verdict():
    block = METHOD.split("FACT-CHECK METHODOLOGY", 1)[1]
    for verdict in ("verified", "mostly_true", "mixed", "disputed", "unverifiable", "descriptive_reporting"):
        assert re.search(rf"<strong>{verdict}</strong>", block), f"{verdict} missing from /methodology"


def test_methodology_says_quick_pass_claims_are_not_checked():
    block = METHOD.split("FACT-CHECK METHODOLOGY", 1)[1]
    assert "Two passes record claims" in block
    assert "not checked" in block
