"""Guards for /candidates — search over completed GE43+GE44 candidacies.

⚠️ MANUAL MUTATION-TEST NOTE (per feedback_mutation-check-no-runtime-git.md):
authored by verifying these tests FAIL against a deliberately broken copy
(e.g. dropping the `len(q) >= _CANDIDATE_MIN_QUERY_LEN` guard, or removing
the LIMIT) and PASS against the real code. That is a one-time authoring
check, not something to encode as a live git diff baked into the suite —
never mutate the shipped file to re-run it; copy it via importlib instead.

Render tests use the same standalone-Jinja idiom as test_races_pages.py /
test_ridings_page.py. Source-inspection tests cover invariants a template
render cannot see: the query-length gate, the result cap, and reuse of the
existing party-canonicalisation boundary.
"""

from __future__ import annotations

import html

import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

flask = pytest.importorskip("flask")
jinja2 = pytest.importorskip("jinja2")


@pytest.fixture(scope="module")
def env():
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader("consumer/templates"),
        autoescape=True,
    )


import datetime

ROWS = [
    {"candidate_name": "Brenda Shanahan", "party": "Liberal",
     "district_number": "24019", "district_name": "Châteauguay--Lacolle",
     "province": "Quebec", "votes": 18029, "vote_share": 37.0, "elected": True,
     "ge_number": 44, "election_date": datetime.date(2021, 9, 20)},
    {"candidate_name": "Brenda Shanahan", "party": "Liberal",
     "district_number": "24019", "district_name": "Châteauguay--Lacolle",
     "province": "Quebec", "votes": 15000, "vote_share": 33.0, "elected": True,
     "ge_number": 43, "election_date": datetime.date(2019, 10, 21)},
]


def _render(env, **kw):
    src = open("consumer/templates/candidates.html", encoding="utf-8").read()
    body = src.split("{% block content %}", 1)[1].rsplit("{% endblock %}", 1)[0]
    macros = '{% from "_archetypes.html" import stat_tiles, segment, data_table %}'
    defaults = dict(q="", party="", parties=[], candidate_rows=[], has_query=False,
                     matched_total=0, capped=False, cap=200, min_query_len=2,
                     total_candidates=4156)
    defaults.update(kw)
    return env.from_string(macros + body).render(**defaults)


def test_no_query_shows_a_prompt_not_a_dumped_table(env):
    """With neither q nor party, the page must not render the full roster."""
    out = _render(env)
    assert "4,156" in out
    assert "Search" in out
    assert "wtf-a-tbl" not in out  # data_table wrapper never rendered


def test_a_query_renders_the_results_table(env):
    out = _render(env, q="Shanahan", has_query=True, candidate_rows=ROWS,
                  matched_total=2)
    assert "wtf-a-tbl" in out
    assert "Brenda Shanahan" in out


def test_the_same_person_appears_ONCE_PER_ELECTION_not_merged(env):
    """One row per candidacy — a person who ran twice must render as TWO
    rows, never collapsed into a single profile."""
    out = _render(env, q="Shanahan", has_query=True, candidate_rows=ROWS,
                  matched_total=2)
    assert out.count("Brenda Shanahan") == 2
    # Both elections show up as distinct rows — the site's existing ordinal
    # convention is always "Nth" (races.html does the same, e.g. "44th"),
    # not grammatically-correct ordinals, so GE43 renders "43th" here too.
    assert "44th" in out and "43th" in out


def test_won_and_lost_are_both_renderable(env):
    lost = dict(ROWS[0], elected=False)
    out = _render(env, q="x", has_query=True, candidate_rows=[ROWS[0], lost],
                  matched_total=2)
    assert ">Won<" in out
    assert ">Lost<" in out


def test_candidate_name_is_escaped(env):
    row = dict(ROWS[0], candidate_name="Bad <script>alert(1)</script>")
    out = _render(env, q="x", has_query=True, candidate_rows=[row], matched_total=1)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_capped_result_says_so_by_name_with_the_real_total(env):
    out = _render(env, q="a", has_query=True, candidate_rows=ROWS, capped=True,
                  cap=200, matched_total=531)
    assert "200" in out
    assert "531" in out
    assert "refine your search" in out.lower()


def test_uncapped_result_does_not_claim_a_truncation(env):
    out = _render(env, q="Shanahan", has_query=True, candidate_rows=ROWS,
                  capped=False, matched_total=2)
    assert "refine your search" not in out.lower()


def test_empty_match_says_no_candidates_match(env):
    out = _render(env, q="zzznobodyrealz", has_query=True, candidate_rows=[],
                  matched_total=0)
    assert "No candidates match this search." in out


def test_party_dropdown_is_built_from_the_passed_in_list_not_hardcoded(env):
    out = _render(env, parties=["Liberal", "Conservative", "Marxist-Leninist"])
    assert '<option value="Liberal"' in out
    assert '<option value="Marxist-Leninist"' in out


def test_selected_party_is_marked_selected(env):
    out = _render(env, party="Liberal", parties=["Liberal", "Conservative"],
                  has_query=True, candidate_rows=ROWS, matched_total=2)
    assert '<option value="Liberal" selected>' in out


def test_ge43_and_ge44_disclosure_is_on_the_page(env):
    out = _render(env)
    assert "GE43 and GE44 only" in out


# --------------------------------------------------------------------------
# Source-level invariants a template render cannot see
# --------------------------------------------------------------------------


def _routes_source() -> str:
    return (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")


def _candidates_route_source() -> str:
    """From the cap/min-length constants to end of file — /candidates is the
    last thing routes.py defines, so there is no following block to bound
    against (and bounding on the first blank-line pair would stop right
    after the two constants, before the route body they belong to)."""
    src = _routes_source()
    start = src.index("_CANDIDATE_RESULT_CAP = 200")
    return src[start:]


def test_the_query_length_gate_exists_and_is_two():
    """1-char searches must be IGNORED, not treated as a wildcard match."""
    pytest.importorskip("flask")
    from consumer.routes import _CANDIDATE_MIN_QUERY_LEN
    assert _CANDIDATE_MIN_QUERY_LEN == 2
    body = _candidates_route_source()
    assert "len(q) >= _CANDIDATE_MIN_QUERY_LEN" in body


def test_the_result_cap_constant_exists_and_is_applied_in_sql():
    """Confirms both halves: the cap CONSTANT, and that it actually reaches
    the query's LIMIT clause rather than being computed and ignored."""
    pytest.importorskip("flask")
    from consumer.routes import _CANDIDATE_RESULT_CAP
    assert _CANDIDATE_RESULT_CAP == 200
    body = _candidates_route_source()
    assert "LIMIT :cap" in body
    assert 'params["cap"] = _CANDIDATE_RESULT_CAP' in body


def test_candidates_reuses_party_case_sql_not_a_second_alias_table():
    body = _candidates_route_source()
    assert "_party_case_sql()" in body
    assert "_ALIASES" not in body
    assert "People's Party" not in body


def test_party_dropdown_is_a_real_query_never_a_hardcoded_list():
    """The <select> options must come from a DISTINCT query over the real
    data, not a literal Python list of party names."""
    body = _candidates_route_source()
    assert "SELECT DISTINCT" in body
    assert '"Liberal"' not in body
    assert "'Liberal'" not in body


def test_a_short_query_alone_does_not_run_the_search():
    """With only a 1-char q and no party, has_query must be False — the
    route must never fall through to a bare `if q:` that ignores length."""
    body = _candidates_route_source()
    assert "q_active = len(q) >= _CANDIDATE_MIN_QUERY_LEN" in body
    assert "has_query = q_active or bool(party)" in body
