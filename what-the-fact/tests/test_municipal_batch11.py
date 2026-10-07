"""Regression coverage for /municipal's Batch 11 change (2026-09-04).

The design-handoff mockup (design-handoff/wtf-municipal.html) links a
"Election coverage readiness ->" panel to wtf-elections.html#coverage. That
target does not exist as a route -- base.html's own Elections nav already
links /elections#coverage to nothing (a pre-existing dead link, confirmed by
grep against consumer/routes.py: no `/elections` route is registered). The
mockup's two other new panels (a "silent cities" coverage-gap list and a
council/ward structure table) are backed by hardcoded JS sample data in the
mockup, not a DB query, and the live template's own top-of-file comment
already documents them as deliberately not ported (no canonical Canadian
city/province registry or council-structure table exists in this DB).

The ONE piece of that ask that IS real and live: /races (federal riding
results, PRs #3084/#3086) and /parties (vote share vs seat share, PR #3087)
are genuine DB-backed pages under the site's Elections nav group. This batch
adds a single honestly-worded cross-link from /municipal to /races -- named
for what it actually is ("federal riding results & races"), not borrowing
the mockup's "coverage readiness" language for a page that isn't that.

Mutation-check (manual, per house convention): with the two Edits in this
commit stashed (`git stash`), test_elections_crosslink_present_by_default
and test_elections_crosslink_present_with_city_filter both fail with
`AssertionError` on the pre-fix template -- confirmed by running this file
against `git stash` before writing it, then `git stash pop` to restore the
change. Not re-encoded as an automated git-diff test here because, unlike
test_mp_hero_links.py's HoC-id regex, there is no PRE-EXISTING behaviour to
diff against: this is new content, not a fix to a wrong value.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block title %}{% endblock %}{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _render(articles=None, cities=None, active_city="", total=0, is_subscriber=False):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("municipal.html").render(
        articles=articles or [],
        cities=cities or [],
        active_city=active_city,
        total=total,
        is_subscriber=is_subscriber,
    )


def test_elections_crosslink_present_by_default():
    html = _render()
    assert 'href="/races"' in html
    assert "federal riding results" in html.lower()


def test_elections_crosslink_present_with_city_filter():
    # The link must not be scoped inside the `{% if cities %}` filter-chip
    # block by accident -- it should render regardless of whether any city
    # facet exists yet.
    html = _render(
        articles=[{"id": 1, "title": "City Hall Meeting", "url": "#", "source": "Test Outlet",
                   "city": "Toronto", "province_code": "ON", "band": "center",
                   "published_at": None, "cluster_id": None, "cluster_size": None}],
        cities=[{"city": "Toronto", "n": 5}],
        active_city="Toronto",
        total=42,
    )
    assert 'href="/races"' in html


def test_no_dead_link_to_the_mockups_nonexistent_elections_route():
    # The mockup's own target (wtf-elections.html#coverage / a live
    # /elections#coverage) does not exist as a Flask route -- never wire it
    # from here, honest or not.
    html = _render()
    assert "elections#coverage" not in html
    assert "wtf-elections" not in html
    assert "coverage readiness" not in html.lower()


def test_existing_all_municipal_coverage_link_untouched():
    html = _render()
    assert 'href="/news?beat=municipal"' in html
    assert "All Municipal Coverage" in html


def test_no_fabricated_silent_cities_or_ward_data():
    # Guards against a future regression that half-ports the mockup's two
    # data-less panels. Neither concept has a live query backing it.
    html = _render()
    lower = html.lower()
    assert "silent cities" not in lower
    assert "ward" not in lower
    assert "council seat" not in lower


def test_elections_route_exists_but_municipal_does_not_link_to_a_missing_anchor():
    # /elections went live in #3577, so the old "no route yet" premise is gone. The municipal page must still not link to
    # an anchor that page does not have (elections#coverage) -- that is checked by the dead-link test above.
    src = ROUTES.read_text(encoding="utf-8")
    assert '@bp.get("/elections")' in src


def test_races_route_exists_and_is_real():
    # Cross-check the link target is not a guess -- /races must be a real,
    # DB-backed route in this file (not a redirect, not a 404).
    src = ROUTES.read_text(encoding="utf-8")
    assert '@bp.get("/races")' in src
    assert "parliament.election_candidates" in src


def test_empty_state_still_renders_with_the_crosslink():
    html = _render(articles=[], cities=[], active_city="", total=0)
    assert "No municipal stories in the feed right now." in html
    assert 'href="/races"' in html
