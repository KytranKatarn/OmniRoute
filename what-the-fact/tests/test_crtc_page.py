"""Regression coverage for crtc_decisions() (2026-09-04, KB vault_note #304357).

Source-grepped rather than DB-driven: this repo's tests run without a live DB
(42 DB-less errors is the accepted baseline), and the route's query text and
render_template() call are unambiguous to search for directly. The real
query behavior (280/280 rows returned, numeric sort differs from
lexicographic) was verified live against the real `wtf` database during
implementation — see PR description.

Three defects fixed, none of which showed up as a failing page load:
  1. A hard `LIMIT 200` permanently hid ~80 of the table's 280 real rulings.
  2. `{{ decisions|length }}` (the LIMIT-capped result size) and a hardcoded
     '280' string in the paywall copy could disagree — the header and the
     paywall promo text showed two different totals on the same page.
  3. `decision_number` is stored as TEXT ("<year>-<seq>") and was sorted
     lexicographically, so '2024-100' could sort below '2024-99' within a
     year — affecting exactly which rows survived the LIMIT truncation.
"""

from __future__ import annotations

import pathlib

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "routes.py"
TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"


def _crtc_route_body() -> str:
    src = ROUTES.read_text(encoding="utf-8")
    start = src.index("def crtc_decisions")
    end = src.index("\n@bp.get", start + 1)
    return src[start:end]


class TestCrtcRouteWiring:
    def test_limit_no_longer_truncates_the_real_table(self):
        body = _crtc_route_body()
        assert "LIMIT 200" not in body, (
            "the old LIMIT 200 hid ~80 of the table's 280 real rulings — "
            "raise it (or paginate) so decisions|length can be trusted"
        )

    def test_order_by_sorts_numerically_not_lexicographically(self):
        body = _crtc_route_body()
        assert "ORDER BY decision_number DESC" not in body, (
            "decision_number is TEXT ('<year>-<seq>'); a plain DESC sort lets "
            "'2024-100' sort below '2024-99' within a year"
        )
        assert "::integer" in body or "::int" in body, (
            "the sequence part of decision_number must be cast to an integer "
            "for a correct numeric sort"
        )

    def test_total_rulings_is_computed_from_a_real_count(self):
        body = _crtc_route_body()
        assert "COUNT(*)" in body and "total_rulings" in body, (
            "the paywall promo copy's rulings count must come from a live "
            "SELECT COUNT(*), not a hardcoded literal that goes stale as "
            "ingest adds more decisions"
        )
        assert "total_rulings=total_rulings" in body, (
            "total_rulings must actually be passed to render_template(), "
            "not just computed and discarded"
        )


class TestCrtcTemplateWiring:
    def test_paywall_copy_uses_the_live_total_not_a_hardcoded_280(self):
        src = (TPL / "crtc.html").read_text(encoding="utf-8")
        assert "'280 CRTC" not in src, (
            "the paywall promo copy must not hardcode the rulings count — "
            "it will silently go stale as ingest adds more decisions"
        )
        assert "total_rulings" in src, (
            "crtc.html must render the route-supplied total_rulings value"
        )
