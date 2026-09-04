"""Regression coverage for /lobbying's org search + monthly sparkline
(2026-09-04, KB vault_note #304357).

Source-grepped for the route (no live DB in this suite) + Jinja render
smoke tests (DictLoader base.html stub, same pattern as test_directory_pages.py).

Deliberately NOT added: a sector filter/column. The route's own docstring
confirms subject_matter is 100% NULL in parliament.lobbyist_contacts —
a sector filter over data that doesn't exist would be fabrication, not a
feature. Only organization-name search was added.
"""

from __future__ import annotations

import datetime
import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


class _FakeRequest:
    path = "/lobbying"


def _lobbying_payload_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def _lobbying_payload")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def _render(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    env.globals["request"] = _FakeRequest()
    return env.get_template("lobbying.html").render(**ctx)


_STATS = {"contacts": 100, "orgs": 10, "mps": 5, "last_30d": 2,
          "first_seen": datetime.date(2020, 1, 1), "last_seen": datetime.date(2026, 1, 1),
          "synced_at": None}


class TestLobbyingRouteWiring:
    def test_org_search_filters_on_client_org_only(self):
        body = _lobbying_payload_body()
        assert "lc.client_org ILIKE :q" in body

    def test_no_sector_filter_was_added(self):
        body = _lobbying_payload_body()
        assert "sector" not in body.lower(), (
            "subject_matter/sector is 100% NULL in this table (per the route's "
            "own docstring) — no sector filter should exist"
        )

    def test_monthly_sparkline_uses_real_communication_date(self):
        body = _lobbying_payload_body()
        assert "date_trunc('month', lc.communication_date)" in body
        assert '"monthly":' in body, "the monthly rows must actually be returned to the template"


class TestLobbyingTemplateRendering:
    def test_index_search_box_renders(self):
        html = _render(detail=None, stats=_STATS, top_orgs=[], top_mps=[], recent=[],
                        q="", org="", is_subscriber=False, monthly=[])
        assert 'aria-label="Search organizations"' in html

    def test_index_no_results_message(self):
        html = _render(detail=None, stats=_STATS, top_orgs=[], top_mps=[], recent=[],
                        q="nonexistent-org-xyz", org="", is_subscriber=False, monthly=[])
        assert "No organizations match" in html
        assert "nonexistent-org-xyz" in html

    def test_detail_sparkline_renders_with_data(self):
        html = _render(
            detail={"org_label": "Test Org", "contacts": 100, "mps": 5,
                     "first_seen": datetime.date(2020, 1, 1), "last_seen": datetime.date(2026, 1, 1)},
            stats=_STATS, org_mps=[], contacts=[],
            monthly=[{"month": "2025-01", "n": 5}, {"month": "2025-02", "n": 10}],
            top_orgs=[], top_mps=[], recent=[], q="", org="Test Org", is_subscriber=True,
        )
        assert "Filings by month" in html
        assert "peak 10 in one month" in html

    def test_detail_no_monthly_data_does_not_crash(self):
        # max() of an empty sequence raises — must not reach that call when
        # an org genuinely has zero contacts inside the 24-month window.
        html = _render(
            detail={"org_label": "Test Org", "contacts": 100, "mps": 5,
                     "first_seen": None, "last_seen": None},
            stats=_STATS, org_mps=[], contacts=[], monthly=[],
            top_orgs=[], top_mps=[], recent=[], q="", org="Test Org", is_subscriber=True,
        )
        assert "Filings by month" not in html
        assert "Test Org" in html
