"""Regression coverage for /mp/<slug>'s hero links + Backbench fallback
(2026-09-04, KB vault_note #304357).

The mockup's own House of Commons URL pattern
(ourcommons.ca/members/en/<slug>) was tested live against the real site
and silently redirects to the generic member-search page for every MP —
the numeric-id form (ourcommons.ca/Members/en/<id>) is the one confirmed
to load the actual profile. parl_mp_id is stored as the literal text
"['88515']" (a stringified Python list from the ingest script, not an
actual array column) — 337/337 current MPs match this single-numeric-id
pattern (verified against the live DB).
"""

from __future__ import annotations

import pathlib
import re

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


class _FakeRequest:
    path = "/mp/jane-doe"


def _mp_profile_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def mp_profile")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


_MP_CTX = dict(
    votes=[], articles=[], stats={}, total_votes=0, source_count=46,
    riding_donor_totals=[], top_named_donors=[], lobbying_contacts=[],
    expense_periods=[], disclosures=[], promises=[], committees=[], is_subscriber=False,
)


def _render(mp):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["url_for"] = lambda *a, **k: "#"
    env.globals["request"] = _FakeRequest()
    return env.get_template("mp.html").render(mp=mp, **_MP_CTX)


def test_hoc_id_is_extracted_with_a_regex_not_array_indexing():
    body = _mp_profile_route_body()
    assert 're.search(r"\\d+", mp.get("parl_mp_id")' in body, (
        "parl_mp_id is a stringified list literal in a varchar column, not "
        "a real array — indexing it would raise, not extract the id"
    )


def test_extracts_the_real_id_from_the_stringified_list_format():
    m = re.search(r"\d+", "['88515']")
    assert m.group(0) == "88515"


def test_backbench_fallback_renders_when_no_cabinet_role():
    mp = {"name": "Jane Doe", "party": "Liberal", "party_colour": "#dc2626",
          "province_code": "ON", "riding_name": "Test Riding", "photo_url": None,
          "openparl_url": None, "hoc_member_id": None, "twitter": None,
          "email": None, "cabinet_role": None}
    html = _render(mp)
    assert "Backbench" in html


def test_backbench_fallback_absent_when_cabinet_role_present():
    mp = {"name": "Jane Doe", "party": "Liberal", "party_colour": "#dc2626",
          "province_code": "ON", "riding_name": "Test Riding", "photo_url": None,
          "openparl_url": None, "hoc_member_id": None, "twitter": None,
          "email": None, "cabinet_role": "Minister of Test"}
    html = _render(mp)
    assert "Backbench" not in html
    assert "Minister of Test" in html


def test_house_of_commons_link_uses_the_numeric_id_form():
    mp = {"name": "Jane Doe", "party": "Liberal", "party_colour": "#dc2626",
          "province_code": "ON", "riding_name": "Test Riding", "photo_url": None,
          "openparl_url": None, "hoc_member_id": "88515", "twitter": None,
          "email": None, "cabinet_role": None}
    html = _render(mp)
    assert "https://www.ourcommons.ca/Members/en/88515" in html
    # The mockup's slug-based form must never ship — verified broken live.
    assert "ourcommons.ca/members/en/jane-doe" not in html.lower()


def test_house_of_commons_link_omitted_without_an_id_no_crash():
    mp = {"name": "Jane Doe", "party": "Liberal", "party_colour": "#dc2626",
          "province_code": "ON", "riding_name": "Test Riding", "photo_url": None,
          "openparl_url": None, "hoc_member_id": None, "twitter": None,
          "email": None, "cabinet_role": None}
    html = _render(mp)
    assert "House of Commons" not in html
    assert "Jane Doe" in html


def test_coverage_search_link_uses_the_mp_name():
    mp = {"name": "Jane Doe", "party": "Liberal", "party_colour": "#dc2626",
          "province_code": "ON", "riding_name": "Test Riding", "photo_url": None,
          "openparl_url": None, "hoc_member_id": None, "twitter": None,
          "email": None, "cabinet_role": None}
    html = _render(mp)
    assert "Coverage of Jane Doe" in html
    assert "/search?q=Jane" in html


def test_races_link_present():
    mp = {"name": "Jane Doe", "party": "Liberal", "party_colour": "#dc2626",
          "province_code": "ON", "riding_name": "Test Riding", "photo_url": None,
          "openparl_url": None, "hoc_member_id": None, "twitter": None,
          "email": None, "cabinet_role": None}
    html = _render(mp)
    assert 'href="/races"' in html
