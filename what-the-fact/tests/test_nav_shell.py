"""Guards for the rebuilt nav shell (newsroom rebuild, Phase 1).

The nav gained a seventh group (Elections) and nine destinations that had no
route. The failure this file exists to prevent is stated in base.html's own
comment, written when the groups were introduced:

    a regrouped nav full of 404s would be worse than the one it replaces

So the load-bearing test here is not "the labels render" — it is
`test_every_nav_destination_has_a_route`, which walks the rendered nav and
resolves each href against the URL map. Add a nav entry without a route and it
goes red, at the moment the link is added rather than when a reader clicks it.

These render through the test client but touch no database: the placeholder
views are pure template renders, so the whole shell can be asserted without a
schema fixture.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from consumer.app import create_app

ROOT = Path(__file__).resolve().parents[1]

# Order is part of the contract — News first, About last, Elections third.
# The handoff's information architecture reads left to right as a narrowing:
# what happened, who decides, how they got there, what it costs.
EXPECTED_GROUPS = ["News", "Politics", "Elections", "Money", "Media", "Data", "About"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "test")
    monkeypatch.setenv("WTF_BILLING_DB_PATH", str(tmp_path / "b.db"))
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _nav_html(client) -> str:
    """The nav as rendered on a placeholder page (no DB reads on this path)."""
    r = client.get("/elections")
    assert r.status_code == 200, r.status_code
    body = r.get_data(as_text=True)
    assert '<div class="wtf-nav-links"' in body, "nav did not render"
    return body.split('<div class="wtf-nav-links"')[1].split("</nav>")[0]


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------


def test_seven_group_labels_render_in_order(client):
    labels = re.findall(
        r'<button class="wtf-navgrp-btn"[^>]*>.*?<span>([^<]+)</span>', _nav_html(client), re.S
    )
    assert labels == EXPECTED_GROUPS


def test_the_same_groups_reach_the_mobile_drawer(client):
    """base.html renders one nav_sections list into BOTH the desktop bar and the
    drawer. If they ever diverge, a phone gets a different site."""
    body = client.get("/elections").get_data(as_text=True)
    drawer = body.split('class="wtf-nav-mobile"')[1]
    for label in EXPECTED_GROUPS:
        assert f"<span>{label}</span>" in drawer, label


# --------------------------------------------------------------------------
# The one that matters
# --------------------------------------------------------------------------


def test_every_nav_destination_has_a_route(client):
    """No nav link may 404.

    Anchors are stripped before matching: /elections#federal is a section of a
    page that exists, and the placeholder has no such section yet — that is a
    content gap, not a broken link.
    """
    app = create_app()
    rules = {str(r.rule).rstrip("/") or "/" for r in app.url_map.iter_rules()}
    hrefs = set(re.findall(r'href="(/[^"]*)"', _nav_html(client)))
    missing = sorted(
        h for h in hrefs if (h.split("#")[0].rstrip("/") or "/") not in rules
    )
    assert not missing, f"nav links with no route: {missing}"


def test_placeholder_routes_are_all_reachable(client):
    # ⚠️ `races`, `parties`, `methodology`, `creed` and `echo` are
    # deliberately ABSENT: all five graduated to real pages
    # (test_races_pages.py, test_party_identity.py, test_methodology_page.py,
    # test_creed_page.py, test_echo_real_data.py). This test asserts
    # placeholders render with NO database, so a real page listed here fails
    # on the engine rather than on the view — which is exactly how each
    # graduation announced itself (echo's own failure here was exactly that:
    # sqlalchemy.exc.ArgumentError, not a 200/404). Slugs move OUT of this
    # list as they are built; a slug in both places is the bug.
    for slug in ("platforms", "elections", "global", "debt"):
        assert client.get(f"/{slug}").status_code == 200, slug


def test_a_built_page_is_no_longer_advertised_as_a_placeholder(client):
    """The two sets must stay disjoint. A page that exists while still being
    described as unbuilt tells the reader the opposite of the truth."""
    from consumer.routes import _COMING_SOON
    for built in ("races", "parties", "methodology", "creed", "echo"):
        assert built not in _COMING_SOON, built


# --------------------------------------------------------------------------
# Honesty of the placeholders
# --------------------------------------------------------------------------


def test_a_placeholder_says_it_is_not_live(client):
    """The lede describes what the finished page will show. Rendering that
    promise with no data and no disclaimer would tell a reader they are looking
    at the thing being described."""
    body = client.get("/platforms").get_data(as_text=True)
    assert "Not yet live" in body
    assert "designed but not built" in body


def test_a_placeholder_names_what_it_is_waiting_on(client):
    """A generic 'coming soon' is not accountable. Each says which data is
    missing, so the claim can be checked against the schema."""
    body = client.get("/platforms").get_data(as_text=True)
    assert "platform documents" in body
    assert "parliament.mp_promises" in body, "it names the table it can and cannot read"


# --------------------------------------------------------------------------
# The LIVE pill
# --------------------------------------------------------------------------


def test_live_pill_is_a_link_not_a_dead_span(client):
    """Item 10 of the handoff's corrections table: it advertised live activity
    and went nowhere."""
    body = client.get("/elections").get_data(as_text=True)
    assert '<a href="/activity" class="wtf-nav-live"' in body


def test_live_label_carries_the_class_the_breakpoint_hides(client):
    """The <=1180px rule drops the wording and keeps the dot. Without this class
    the rule silently matches nothing and the bar overflows instead."""
    body = client.get("/elections").get_data(as_text=True)
    assert 'class="wtf-live-label"' in body
    css = (ROOT / "consumer" / "static" / "style.css").read_text()
    assert ".wtf-nav-live .wtf-live-label { display: none; }" in css


# --------------------------------------------------------------------------
# Shell CSS invariants
# --------------------------------------------------------------------------


def test_nav_and_groups_stay_overflow_visible():
    """An absolutely-positioned menu escapes the bar; a scroll container on any
    ancestor clips every dropdown with no error and no visual clue."""
    css = (ROOT / "consumer" / "static" / "style.css").read_text()
    assert ".wtf-nav, .wtf-navgrp { overflow: visible; }" in css
    assert "overflow-x: auto" not in css.split(".wtf-nav {")[1].split("}")[0]


def test_tap_opens_a_menu():
    """Touch fires no :hover and :focus-within needs focus first, so without an
    .open class the first tap on a phone did nothing."""
    css = (ROOT / "consumer" / "static" / "style.css").read_text()
    assert ".wtf-navgrp.open .wtf-navgrp-menu { display: block; }" in css
    js = (ROOT / "consumer" / "static" / "js" / "wtf-nav.js").read_text()
    assert "classList.toggle('open'" in js
    assert "aria-expanded" in js, "the attribute must track the real state"


def test_page_styles_did_not_leak_into_the_shared_stylesheet():
    """static/style.css is synced into the design system by .design-sync/, so it
    has a second consumer. Placeholder page styles belong in the template."""
    css = (ROOT / "consumer" / "static" / "style.css").read_text()
    assert ".wtf-cs" not in css, "placeholder page styles leaked into style.css"
