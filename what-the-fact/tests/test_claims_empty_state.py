"""/claims: an empty tracker looks honest, not broken (design-port audit 2026-10-14).

`claim_tracker` has zero rows, so the page rendered a row of tiles that all read "0" / "0%" (a figure that implies something was measured), filter
chips that filter nothing, and a clipboard emoji in the title. The real template is rendered through Jinja in both directions: nothing tracked ->
no tiles, no chips, a plain explanation; claims present -> tiles, chips and the claim card are all there (so the fix is not "always hide").
"""
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

T = Path(__file__).resolve().parents[1] / "consumer" / "templates"

ZERO_TILES = [{"label": "Claims checked", "value": 0, "detail": None}] + [
    {"label": s, "value": "0%", "detail": "0 claims"} for s in ("Verified True", "Partially True", "Misleading", "False", "Contested")
]
LIVE_TILES = [{"label": "Claims checked", "value": 4, "detail": None}, {"label": "Verified True", "value": "50%", "detail": "2 claims"}]
CLAIM = {"id": 1, "politician_slug": "jane-doe", "politician_name": "Jane Doe", "claim_text": "The budget cuts nothing.", "claim_date": "2026-09-01",
         "status": "verified_true", "verdict_summary": "Matches Table 3.4.", "source_url": "https://example.org/doc"}


def _render(**ctx):
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block title %}{% endblock %}{% block content %}{% endblock %}"}), FileSystemLoader(str(T))]),
                      autoescape=select_autoescape(["html"]))
    base = {"claims": [], "claim_stats": [], "active_status": "all", "is_subscriber": False}
    base.update(ctx)
    return env.get_template("claims.html").render(**base)


def test_nothing_tracked_shows_no_zero_tiles_no_chips_no_emoji():
    out = _render(claim_stats=ZERO_TILES)
    assert "0%" not in out and "wtf-a-stat" not in out and "Claims checked" not in out
    assert 'class="wtf-claims-filters"' not in out and "Verified True" not in out
    assert "\U0001F4CB" not in out
    assert "Nothing is tracked yet" in out and "stays empty rather than show zeros" in out


def test_nothing_tracked_still_has_the_shared_header_and_the_contested_note():
    out = _render(claim_stats=ZERO_TILES)
    assert 'class="wtf-pg-head"' in out and '<h1 class="wtf-pg-title">Election Claim Tracker</h1>' in out
    assert "does not mean false" in out


def test_with_claims_the_tiles_chips_and_card_are_all_present():
    out = _render(claim_stats=LIVE_TILES, claims=[CLAIM])
    assert "Claims checked" in out and "50%" in out
    assert 'class="wtf-claims-filters"' in out and "Verified True" in out
    assert "The budget cuts nothing." in out and "1 claim" in out


def test_a_filter_with_no_matches_keeps_the_chips_and_says_which_status():
    out = _render(claim_stats=LIVE_TILES, claims=[], active_status="misleading")
    assert 'class="wtf-claims-filters"' in out and "No claims with status <strong>misleading</strong>." in out


def test_the_politician_page_has_the_back_link_and_no_site_wide_tiles():
    out = _render(politician_name="Jane Doe", politician_slug="jane-doe", claims=[], claim_stats=LIVE_TILES)
    assert "Claims — Jane Doe" in out and "All claims" in out and 'class="wtf-claims-filters"' not in out
    assert "No claims are tracked for this person yet." in out
