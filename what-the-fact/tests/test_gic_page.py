"""Regression coverage for gic_appointments() (2026-09-04, KB vault_note #304357).

Source-grepped rather than DB-driven: this repo's tests run without a live DB
(42 DB-less errors is the accepted baseline). The route's SELECT text and
render_template() call are unambiguous to search for directly; the render
smoke test below uses a DictLoader base.html stub (no DB needed) to prove the
template actually renders with the new variables, same pattern as
test_directory_pages.py.

Three additions, matching the design-integration audit's scoped
recommendation (ship the header stats + search, do NOT build the mockup's
"Vacant posts" panel — no gov_watch.gic_vacancies table exists anywhere):
  1. A 3-tile header stat row (Appointments in window / Organisations /
     Departments), computed from the already-fetched rows/depts — no new
     query.
  2. A `q` search param (appointee_name / organization / pc_number, ILIKE)
     alongside the existing `dept` filter.
  3. The "Related registers" panel restored to 5 links (was missing
     Lobbying and Cross-Watch).
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"

_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _gic_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def gic_appointments")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


def _render(**ctx):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    # the route always passes total_appointments; the template formats it with {:,}
    ctx.setdefault("total_appointments", len(ctx.get("appointments", [])))
    return env.get_template("gic.html").render(**ctx)


class TestGicRouteWiring:
    def test_search_param_filters_on_three_fields(self):
        body = _gic_route_body()
        assert "_req.args.get(\"q\"" in body, "gic_appointments() must read a q search param"
        assert "appointee_name ILIKE :q" in body
        assert "organization ILIKE :q" in body
        assert "pc_number ILIKE :q" in body

    def test_stats_are_passed_to_the_template(self):
        body = _gic_route_body()
        assert "organisations_count=organisations_count" in body
        assert "departments_count=len(depts)" in body

    def test_organisations_count_derived_from_rows_not_a_new_query(self):
        body = _gic_route_body()
        # The stat must come from the ALREADY-FETCHED `rows`, not a second
        # DB round trip — the audit's whole point was "no new query needed".
        assert 'organisations_count = len({r["organization"] for r in rows' in body

    def test_no_fabricated_vacancy_table(self):
        # Grep only actual query/identifier text, not this file's own prose —
        # a naive whole-body substring check would false-positive on the
        # route's own explanatory comment about why vacancies are excluded.
        import re
        body = _gic_route_body()
        code_only = "\n".join(
            line for line in body.splitlines() if not line.strip().startswith("#")
        )
        assert not re.search(r"vacan", code_only, re.IGNORECASE), (
            "no gov_watch.gic_vacancies (or equivalent) table exists anywhere "
            "in this codebase — a vacancy count would be fabricated"
        )


class TestGicTemplateRendering:
    CTX = dict(
        appointments=[{
            "pc_number": "2026-0001", "oic_date": None, "department": "Justice",
            "subject": "Judge appointment", "precis": "", "oic_url": "https://example.com",
            "appointee_name": "Jane Smith", "organization": "Federal Court",
        }],
        depts=["Justice", "Health"],
        dept="all",
        q="",
        organisations_count=1,
        departments_count=2,
        source_count=46,
        is_subscriber=True,
        nav_source_count=46,
    )

    def test_renders_the_stat_row(self):
        html = _render(**self.CTX)
        assert "Appointments in window" in html
        assert "Organisations" in html
        assert "Departments" in html

    def test_renders_a_search_box(self):
        html = _render(**self.CTX)
        assert 'aria-label="Search appointments"' in html
        assert "Appointee, organisation, order number" in html

    def test_related_registers_has_all_five_links(self):
        html = _render(**self.CTX)
        for label in ("Officers of Parliament", "Ethics rulings", "Lobbying registry", "Cross-Watch"):
            assert label in html, f"related-registers panel is missing '{label}'"

    def test_search_box_only_renders_for_subscribers(self):
        ctx = dict(self.CTX, is_subscriber=False)
        html = _render(**ctx)
        assert 'aria-label="Search appointments"' not in html, (
            "the search form filters the gated appointments list — it must "
            "not render for a non-subscriber"
        )
