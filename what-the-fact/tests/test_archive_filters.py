"""Guard: /archive filter validation, WHERE assembly and URL building (#6149).

Pure imports — no DB, no network, no app context, so this cannot silently SKIP.

🔴 THE LOAD-BEARING TEST IS test_no_filter_value_is_interpolated_into_sql.

Every filter on /archive is user input that reaches a WHERE clause. The values
are validated against CLOSED sets and bound as parameters; ORDER BY cannot be
parameterised at all, so it may only ever come from the constant map. An edit
that f-strings any of these in would look ordinary in review and would be the
whole ballgame.

These helpers ship AHEAD of the route that consumes them, deliberately. The
first attempt put the helpers, the route, the template and the tests in one PR;
F.O.R.G.E. could then only read ~2% of routes.py before its window ran out, so
the APPROVE it returned did not actually cover the SQL. Landing the injection
surface on its own — 4.1 KB, inside even the smaller reviewer's 9,000-char
window — is what makes an honest read possible. See PR #3060's comments.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from consumer.routes import (  # noqa: E402
    _ARCHIVE_FREE_ARTICLES,
    _ARCHIVE_FREE_STORIES,
    _ARCHIVE_PAGE,
    _ARCHIVE_SORTS,
    _ARCHIVE_WINDOWS,
    _archive_filters,
    _archive_qs,
    _archive_where,
)


# ────────────────────────────── 🔴 no user value reaches SQL as text

@pytest.mark.parametrize("evil", [
    "' OR 1=1--",
    "x'; DROP TABLE wtf.articles;--",
    "center'/**/UNION/**/SELECT",
    "../../etc/passwd",
    "%' AND (SELECT pg_sleep(5)) IS NOT NULL--",
])
def test_no_filter_value_is_interpolated_into_sql(evil):
    """Hostile input is either rejected by the closed set or bound as a
    parameter — never spliced into the WHERE text."""
    f = _archive_filters({"lean": evil, "verdict": evil, "beat": evil,
                          "lang": evil, "outlet": evil, "q": evil, "view": evil,
                          "sort": evil, "days": evil, "page": evil})
    where, params = _archive_where(f)
    assert evil not in where, "a raw filter value reached the SQL string"
    for k in ("lean", "verdict", "beat", "lang"):
        assert f[k] == "all", f"{k} accepted a value outside its closed set"
    assert f["view"] in ("story", "article")
    assert f["sort"] in _ARCHIVE_SORTS
    assert f["days"] in _ARCHIVE_WINDOWS
    assert f["page"] >= 1


def test_free_text_still_reaches_the_query_but_only_as_a_bound_param():
    """Non-vacuity for the test above: rejecting EVERYTHING would pass it
    trivially and break search. `q` and `outlet` must still work."""
    f = _archive_filters({"q": "carbon tax", "outlet": "CBC News"})
    where, params = _archive_where(f)
    assert ":q" in where and params["q"] == "%carbon tax%"
    assert ":outlet" in where and params["outlet"] == "CBC News"
    assert "carbon tax" not in where


def test_the_sort_key_is_closed_and_its_clauses_are_inert():
    """ORDER BY cannot be parameterised, so the only safe design is: the request
    picks a KEY, and the clause comes from this constant map.

    ⚠️ The companion assertion — that the query builder actually reads the map
    rather than the request — lives with `_archive_rows` in the route PR, not
    here. A guard belongs in the PR that carries the line it guards; asserting
    it here would have failed on this branch and taught the next person to
    delete it.
    """
    assert _archive_filters({"sort": "; DROP TABLE x"})["sort"] == "filed"
    for key, (_, sql) in _ARCHIVE_SORTS.items():
        assert ";" not in sql and "--" not in sql, f"{key} clause is not inert"


def test_an_absent_filter_adds_no_clause():
    """A default must not silently narrow the result set."""
    where, params = _archive_where(_archive_filters({}))
    for absent in (":lean", ":verdict", ":beat", ":lang", ":outlet", ":q"):
        assert absent not in where
    assert "suppressed_reason IS NULL" in where, "suppression filter must always apply"
    assert params["days"] == 30


def test_suppressed_rows_can_never_be_opted_back_in():
    """Suppression is unconditional — no filter combination may expose them."""
    for f in (_archive_filters({}),
              _archive_filters({"view": "article", "q": "x", "lean": "left"}),
              _archive_filters({"days": "365", "sort": "oldest"})):
        assert "a.suppressed_reason IS NULL" in _archive_where(f)[0]


# ──────────────────────────────────────────────────── query-string assembly

def test_qs_preserves_filters_and_applies_overrides():
    f = _archive_filters({"view": "article", "days": "90", "lean": "left"})
    url = _archive_qs(f, sort="outlets")
    assert url.startswith("/archive?")
    for part in ("view=article", "days=90", "lean=left", "sort=outlets"):
        assert part in url


def test_qs_drops_defaults_so_a_shared_link_stays_readable():
    url = _archive_qs(_archive_filters({}))
    for noise in ("lean=all", "verdict=all", "beat=all", "lang=all",
                  "outlet=all", "page=1", "q="):
        assert noise not in url


def test_qs_encodes_hostile_text_rather_than_emitting_it_raw():
    """A filter value lands in an href; unencoded quotes would break out of it."""
    url = _archive_qs(_archive_filters({"q": 'a b&c="x"'}))
    assert '"' not in url and " " not in url and "&c=" not in url


def test_qs_round_trips_through_the_validator():
    """The URL a control emits must parse back to the same filter state, or a
    click silently changes something the reader did not touch."""
    original = _archive_filters({"view": "article", "days": "90", "lean": "left",
                                 "beat": "politics", "sort": "outlets"})
    from urllib.parse import parse_qs, urlparse
    parsed = {k: v[0] for k, v in parse_qs(urlparse(_archive_qs(original)).query).items()}
    assert _archive_filters(parsed) == original


# ──────────────────────────────────────────────────────────── constants

def test_free_caps_and_page_size_match_the_spec():
    assert _ARCHIVE_FREE_STORIES == 10
    assert _ARCHIVE_FREE_ARTICLES == 50
    assert _ARCHIVE_PAGE >= _ARCHIVE_FREE_ARTICLES, (
        "page size must be >= the free cap, or the gate could never trigger"
    )


def test_every_sort_names_its_direction():
    """'Filed · newest' beats an ambiguous arrow — the reader should not have to
    guess which end of the range they are looking at."""
    for key, (label, sql) in _ARCHIVE_SORTS.items():
        assert "·" in label, f"{key} does not name a direction"
        assert ("ASC" in sql) or ("DESC" in sql)


def test_windows_are_a_closed_set():
    """An open integer would let a crawler request arbitrarily expensive scans."""
    assert _ARCHIVE_WINDOWS == (7, 30, 90, 365)
    assert _archive_filters({"days": "100000"})["days"] == 30
