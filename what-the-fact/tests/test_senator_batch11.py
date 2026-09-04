"""Regression coverage for /senator/<slug> (Batch 11, 2026-09-04).

Three real, DB-independent additions to the senator profile template — no
route change, all logic lives in senator.html itself:

1. A "75 · retirement age" stat tile. Constitution Act, 1867 s.29(2) (as
   amended by the Constitution Act, 1965) fixes mandatory Senate retirement
   at age 75 — a constant constitutional fact, not a per-senator figure, so
   it needs no DB column. Shown alongside the age/DOB/retirement-date tiles
   that are already derived from that same 75-year cap (route.py), so the
   two can never disagree.
2. Committee chips are now real outbound links to
   https://sencanada.ca/en/committees/<abbr>/ — mechanical, using the
   `committee_abbr` value the route already selects from
   parliament.senator_committees (verified live: all current abbrs are
   bare uppercase strings, e.g. BANC/LCJC/NFFN — safe to interpolate into
   a URL path segment un-encoded).
3. A "Chamber — Senate of Canada, Ottawa ON K1A 0A4" contact line — the
   Senate's real, public mailing address — shown ONLY for `is_current`
   senators. A former senator no longer holds a Senate office, so stating
   the Chamber address for them would misrepresent their current standing;
   gating it on `is_current` (a column the route already selects) avoids
   that.

Deliberately NOT built: the wtf-mp-* class-family reskin the audit also
flagged (hero/stats/section-title/vote-row markup unification with
mp.html) — that is a large mechanical migration across shared design-system
classes, correctly left as a documented follow-up rather than half-done
here. Also not built: the mockup's fabricated "Appointed by <seeded PM
name>" line — the live route already carries a REAL `appointed_by` column,
and regressing toward the mockup's seeded-RNG fabrication would make the
page less honest, not more.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


class _FakeRequest:
    path = "/senator/jane-doe"


def _render(senator, source_count=46, is_subscriber=True):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _FakeRequest()
    return env.get_template("senator.html").render(
        senator=senator, source_count=source_count, is_subscriber=is_subscriber,
    )


def _base_senator(**overrides):
    sen = {
        "id": 1, "slug": "doe-jane", "name": "Doe, Jane", "given_name": "Jane",
        "family_name": "Doe", "caucus": "ISG", "caucus_label": "Independent Senators Group",
        "caucus_colour": "#cc0000", "province": "Ontario", "photo_url": None,
        "profile_url": None, "appointed_at": None, "date_of_birth": None,
        "appointed_by": None, "biography": None, "office_phone": None,
        "office_email": None, "twitter_handle": None, "linkedin_url": None,
        "website_url": None, "is_current": True, "committees": [], "votes": [],
    }
    sen.update(overrides)
    return sen


# ── 1. Retirement-age constitutional-fact tile ──────────────────────────

def test_retirement_age_tile_present_when_appointment_dates_are_known():
    sen = _base_senator(age=61, years_until_retirement=14)
    html = _render(sen)
    assert ">75<" in html
    assert "retirement age" in html


def test_retirement_age_tile_absent_when_no_dates_are_known_at_all():
    # No `age` / `retirement_date` key at all -> the whole stats row (an
    # existing, unchanged gate) does not render, so the new tile must not
    # appear detached from the figures it's paired with.
    sen = _base_senator()
    html = _render(sen)
    assert "retirement age" not in html


# ── 2. Committee chips link to the real committee page ──────────────────

def test_committee_chip_links_to_the_official_committee_page():
    sen = _base_senator(committees=[
        {"committee_abbr": "BANC", "committee_name": "Standing Senate Committee on Banking",
         "role": "member"},
    ])
    html = _render(sen)
    assert 'href="https://sencanada.ca/en/committees/BANC/"' in html
    assert 'target="_blank"' in html
    assert "Standing Senate Committee on Banking" in html


def test_committee_chip_is_a_real_anchor_not_a_bare_span():
    # Proves the fix: the pre-fix markup rendered a <span> with no href at
    # all, so a committee name was not a link anywhere on the page.
    sen = _base_senator(committees=[
        {"committee_abbr": "LCJC", "committee_name": "Legal and Constitutional Affairs",
         "role": "chair"},
    ])
    html = _render(sen)
    assert '<a class="wtf-committee-chip' in html
    assert "<span class=\"wtf-committee-chip" not in html


def test_no_committees_does_not_crash():
    html = _render(_base_senator(committees=[]))
    assert "Doe, Jane" in html


# ── 3. Chamber address — current senators only ───────────────────────────

def test_chamber_address_shown_for_a_current_senator():
    sen = _base_senator(is_current=True, office_phone="613-555-1000")
    html = _render(sen, is_subscriber=True)
    assert "K1A 0A4" in html
    assert "Senate of Canada, Ottawa" in html


def test_chamber_address_absent_for_a_former_senator_even_with_a_phone_on_file():
    # A former senator may still have a stale office_phone value in the DB
    # (12 former senators carry voting history per routes.py's own
    # comment) — the Chamber line must be gated on is_current specifically,
    # not on "the Contact section rendered at all".
    sen = _base_senator(is_current=False, office_phone="613-555-1000")
    html = _render(sen, is_subscriber=True)
    assert "613-555-1000" in html  # the real phone still shows
    assert "K1A 0A4" not in html   # but the Chamber address does not


def test_chamber_address_absent_when_signed_out_current_senator_hidden_behind_paywall():
    sen = _base_senator(is_current=True)
    html = _render(sen, is_subscriber=False)
    assert "K1A 0A4" not in html
