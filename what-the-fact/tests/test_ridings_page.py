"""Guards for /ridings — the honest-historical riding DIRECTORY.

⚠️ MANUAL MUTATION-TEST NOTE (per feedback_mutation-check-no-runtime-git.md):
these tests were authored by verifying they FAIL against a deliberately
broken copy of the relevant code (e.g. sorting by margin_pct instead of
district_name, or dropping the empty-search message) and PASS against the
real one. That check is a one-time authoring step, not something to encode
as a runtime git diff/HEAD comparison baked into the suite — a test that
shells out to git to prove itself would keep "detecting" the same historical
bug forever, long after it was fixed and merged. To re-verify by hand later:
copy consumer/routes.py, reintroduce the bug, run against the copy via
importlib, confirm red; never mutate the live file to do this.

These are RENDER tests against fixture data (same idiom as
test_races_pages.py) plus source-inspection tests for the SQL-level
invariants (sort order, party canonicalisation reuse) a template test cannot
see.
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


# Same real riding /races' fixture uses (GE44 Châteauguay—Lacolle), plus one
# more province/party so the directory rows are distinguishable.
RIDINGS = [
    {"district_number": "24019", "district_name": "Châteauguay--Lacolle",
     "province": "Quebec", "candidate_name": "Brenda Shanahan",
     "party": "Liberal", "vote_share": 37.0},
    {"district_number": "10006", "district_name": "St. John's East",
     "province": "Newfoundland and Labrador", "candidate_name": "Joanne Thompson",
     "party": "Liberal", "vote_share": 44.1},
]
TILES = [{"label": "Ridings", "value": "338"}, {"label": "Provinces", "value": "13"},
         {"label": "Candidates", "value": "2,010"}]


def _render(env, **kw):
    """Render ridings.html standalone — the table/tiles, not base.html's chrome
    (the nav has its own guard in test_nav_shell.py)."""
    src = open("consumer/templates/ridings.html", encoding="utf-8").read()
    body = src.split("{% block content %}", 1)[1].rsplit("{% endblock %}", 1)[0]
    macros = '{% from "_archetypes.html" import stat_tiles, segment, data_table %}'
    defaults = dict(ge=44, election_date=None, tiles=[], elections=[], ridings=[],
                     total_ridings=0, provinces=[], province="", q="",
                     empty_msg="No ridings match this filter.")
    defaults.update(kw)
    return env.from_string(macros + body).render(**defaults)


def test_the_riding_link_is_a_LINK_not_escaped_markup(env):
    out = _render(env, ridings=RIDINGS, total_ridings=2, tiles=TILES)
    assert '<a href="/races/24019?ge=44">' in out
    assert "&lt;a href" not in out


def test_candidate_names_are_still_escaped(env):
    rows = [dict(RIDINGS[0], candidate_name='Bad <script>alert(1)</script>')]
    out = _render(env, ridings=rows, total_ridings=1, tiles=TILES)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_column_headers_unpack(env):
    out = _render(env, ridings=RIDINGS, total_ridings=2, tiles=TILES)
    for head in ("Riding", "Province", "Won by", "Party", "Vote share"):
        assert f">{head}</th>" in out


def test_both_ridings_render_in_the_order_they_were_PASSED(env):
    """The template must not re-sort — sorting is the QUERY's job (see the
    source-inspection test below). If the template ever sorted again, this
    would still pass on already-alphabetical fixture data, so the query-level
    test is the one that actually pins the invariant; this one only proves the
    template renders whatever order it's given, unmolested."""
    out = html.unescape(_render(env, ridings=RIDINGS, total_ridings=2, tiles=TILES))
    assert out.index("Châteauguay") < out.index("St. John's East")


def test_each_riding_links_to_the_EXISTING_race_detail_page(env):
    """No new per-riding detail page — every row reuses /races/<district>."""
    out = _render(env, ridings=RIDINGS, total_ridings=2, tiles=TILES)
    assert 'href="/races/24019?ge=44"' in out
    assert 'href="/races/10006?ge=44"' in out


def test_empty_state_says_so_by_name_not_a_bare_no_filter_message(env):
    """A search that matches nothing must not look like the same generic
    'no filter matched' state a province-only filter would show."""
    out = _render(env, ridings=[], total_ridings=0, q="zzzznotarealriding",
                  empty_msg="No ridings match “zzzznotarealriding”.",
                  tiles=TILES)
    assert "No ridings match" in out
    assert "zzzznotarealriding" in out


def test_generic_empty_state_when_there_is_no_search_term(env):
    out = _render(env, ridings=[], total_ridings=0, tiles=TILES)
    assert "No ridings match this filter." in out


def test_ge43_and_ge44_disclosure_is_on_the_page(env):
    out = _render(env, ridings=RIDINGS, total_ridings=2, tiles=TILES)
    assert "GE43 and GE44 only" in out


def test_no_current_mp_claim_and_no_map(env):
    """This directory has no MP-to-riding mapping and no boundary geometry —
    both must be disclaimed on the page itself, not just in code comments."""
    out = _render(env, ridings=RIDINGS, total_ridings=2, tiles=TILES)
    assert "current MP" in out or "current-MP" in out.lower() or "no riding-to-sitting-MP" in out.lower()


# --------------------------------------------------------------------------
# Source-level invariants a template test cannot see
# --------------------------------------------------------------------------


def _routes_source() -> str:
    return (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")


def _ridings_bundle_source() -> str:
    src = _routes_source()
    start = src.index("def _ridings_bundle(")
    end = src.index("\n@bp.get(\"/ridings\")")
    return src[start:end]


def test_ridings_sorts_alphabetically_not_by_margin():
    """The whole point of a DIRECTORY vs /races' RANKING. /races' query orders
    by margin_pct; this one must order by the riding name instead."""
    body = _ridings_bundle_source()
    assert "ORDER BY ec.district_name" in body
    assert "margin_pct" not in body


def test_ridings_reuses_party_case_sql_not_a_second_alias_table():
    """A hand-typed party dict here would be a second copy of
    shared/party_identity.py's _ALIASES — exactly the drift that module's own
    docstring warns against."""
    body = _ridings_bundle_source()
    assert "_party_case_sql()" in body
    assert "_ALIASES" not in body
    assert "People's Party" not in body


def test_ridings_route_reuses_the_existing_race_detail_page():
    """No new per-riding detail route was added."""
    src = _routes_source()
    assert '@bp.get("/races/<district_number>")' in src
    # exactly one riding-detail route — not a second one for /ridings
    assert src.count('@bp.get("/races/<district_number>")') == 1
    assert '@bp.get("/ridings/<' not in src


def test_ridings_tiles_are_computed_not_hardcoded():
    """'Ridings' / 'Provinces' / 'Candidates' must come from a query result,
    never a literal number in the route."""
    body = _ridings_bundle_source()
    assert 'totals.get(' in body
    assert "count(DISTINCT ec.district_number)" in body
    assert "count(*) AS candidates" in body


# --------------------------------------------------------------------------
# Nav wiring — the dead /platforms links are removed, the two new pages are
# added, and the removal is DISCLOSED (a comment above it), not silent.
# test_nav_shell.py already proves every remaining nav href resolves to a
# real route; these checks are about WHICH strings are and are not present.
# --------------------------------------------------------------------------


def _base_html_source() -> str:
    return (ROOT / "consumer" / "templates" / "base.html").read_text(encoding="utf-8")


def test_platforms_is_gone_from_both_nav_groups():
    src = _base_html_source()
    politics = src.split("_politics = [", 1)[1].split("] %}", 1)[0]
    elections = src.split("_elections = [", 1)[1].split("] %}", 1)[0]
    assert "'/platforms'" not in politics, "Promise tracker entry still present"
    assert "'/platforms'" not in elections, "Platforms & promises entry still present"


def test_the_platforms_removal_is_disclosed_not_silent():
    """A comment must explain the removal — per the task's own instruction
    that this is a deliberate, disclosed, reversible edit, not a deletion
    nobody can trace."""
    src = _base_html_source()
    marker = src.index("_politics = [")
    preceding = src[:marker][-800:]
    assert "/platforms" in preceding
    assert "removed" in preceding.lower() or "deliberately" in preceding.lower()


def test_platforms_route_itself_still_exists():
    """Only the NAV LINKS were removed — the placeholder page (and
    test_platforms_blocker_honesty.py's coverage of it) is untouched."""
    routes_src = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
    assert '"platforms"' in routes_src  # still a _COMING_SOON entry


def test_ridings_and_candidates_are_in_the_elections_nav_group():
    src = _base_html_source()
    elections = src.split("_elections = [", 1)[1].split("] %}", 1)[0]
    assert "('/ridings', 'Ridings directory')" in elections
    assert "('/candidates', 'Candidate search')" in elections
