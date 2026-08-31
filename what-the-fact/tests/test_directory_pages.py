"""Directory pages render correctly in BOTH branches (#6165, phase 3).

WHY BOTH BRANCHES. officers and gic are subscriber-gated. An anonymous request
returns 200 while exercising ONLY the paywall — so a staged smoke test can pass
with the subscriber half completely broken. That is exactly how the /rates
migration nearly shipped a broken gated view (#6149). These render the gated
half offline with mock data, which needs no subscriber session.

WHY record_card EXISTS, pinned here. Every one of these records carries its own
outbound link (an OIC entry, an official site, a latest report). person_card is
a single <a>, so composing them with it produces NESTED ANCHORS — invalid HTML
that browsers silently reflow, dropping the inner link's clickable area. The
anchor-depth test is the guard: it fails if anyone "simplifies" record_card back
into an anchor.

Each test was mutation-checked against a COPY of the template: reverting the
Orbitron font, the paywall macro, and the non-anchor card each made the
corresponding test fail. A test that cannot fail is worse than no test.
"""

import datetime
import pathlib
import re

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"

# base.html pulls the whole site shell (nav, context processors). These pages
# only need their own {% block content %}, so stub the parent.
_STUB = ("{% block title %}{% endblock %}{% block meta %}{% endblock %}"
         "<body>{% block content %}{% endblock %}</body>")


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=ChoiceLoader([DictLoader({"base.html": _STUB}), FileSystemLoader(str(TPL))]),
        autoescape=select_autoescape(["html"]),
    )


OFFICERS = [
    {
        "title": "Auditor General of Canada",
        "current_holder": "Karen Hogan",
        "appointed_at": datetime.date(2020, 6, 8),
        "cross_links": ["gov-watch", "wtf"],
        # a hostile mandate string — this product renders scraped text
        "mandate_summary": "Audits federal spending <script>alert(1)</script>.",
        "website_url": "https://oag-bvg.gc.ca",
        "report_url": "https://oag-bvg.gc.ca/r1",
        "report_title": "A report title well past forty characters so truncation is exercised",
    },
    # the SPARSE record: no holder, no links, no cross-product tags
    {
        "title": "Commissioner of Lobbying",
        "current_holder": None, "appointed_at": None, "cross_links": [],
        "mandate_summary": "Administers the Lobbying Act.",
        "website_url": None, "report_url": None, "report_title": None,
    },
]

GIC = [
    {
        "pc_number": "PC 2026-0421", "department": "Justice",
        "oic_date": datetime.date(2026, 4, 21), "appointee_name": "Jane Doe",
        "subject": "Appointment of a judge", "organization": "Federal Court",
        "oic_url": "https://orders-in-council.canada.ca/1",
    },
    # the SPARSE record: no appointee, no org, no OIC link, no department
    {
        "pc_number": "PC 2026-0099", "department": None, "oic_date": None,
        "appointee_name": None, "subject": "Regulatory board appointment",
        "organization": None, "oic_url": None,
    },
]


def officers_html(env, *, subscriber):
    return env.get_template("officers.html").render(officers=OFFICERS, is_subscriber=subscriber)


def gic_html(env, *, subscriber):
    return env.get_template("gic.html").render(
        appointments=GIC, depts=["Justice", "Finance"], dept="all", is_subscriber=subscriber)


class TestSubscriberBranchRenders:
    """The half a staged anonymous 200 never touches."""

    def test_officers_shows_every_record(self, env):
        html = officers_html(env, subscriber=True)
        assert "Auditor General of Canada" in html
        assert "Karen Hogan" in html and "appointed June 2020" in html
        assert "Gov Watch" in html and "WTF" in html
        assert "Official site" in html
        # the sparse record must still render, not vanish on its missing fields
        assert "Commissioner of Lobbying" in html
        assert "Administers the Lobbying Act." in html

    def test_gic_shows_every_record(self, env):
        html = gic_html(env, subscriber=True)
        assert "Jane Doe" in html and "Federal Court" in html
        assert "PC 2026-0421" in html and "Apr 21, 2026" in html
        assert "Regulatory board appointment" in html and "PC 2026-0099" in html

    def test_gic_marks_the_active_department_filter(self, env):
        html = gic_html(env, subscriber=True)
        assert "is-active" in html, "the current filter must be distinguishable"


class TestPaywallBranchRenders:
    def test_officers_anonymous_gets_the_shared_paywall(self, env):
        html = officers_html(env, subscriber=False)
        assert "wtf-a-pay" in html
        assert "/login?next=/parliament/officers" in html
        assert "See plans" in html

    def test_gic_anonymous_gets_the_shared_paywall(self, env):
        html = gic_html(env, subscriber=False)
        assert "wtf-a-pay" in html and "/login?next=/gic" in html

    @pytest.mark.parametrize("page", ["officers", "gic"])
    def test_gated_content_never_leaks_to_anonymous(self, env, page):
        # Assert on values that appear ONLY in gated records. "Auditor General"
        # is NOT one of them — the always-public explainer says "When the
        # Auditor General flags waste", so matching it would fail on correct
        # markup. A probe must name the thing it actually measures.
        html = officers_html(env, subscriber=False) if page == "officers" \
            else gic_html(env, subscriber=False)
        for secret in ("Karen Hogan", "Jane Doe", "Federal Court",
                       "Auditor General of Canada", "PC 2026-0421",
                       "Administers the Lobbying Act"):
            assert secret not in html, f"{page}: gated record {secret!r} leaked to anonymous"


class TestNoNestedAnchors:
    """record_card exists because person_card is an <a>. Depth must never exceed 1."""

    @pytest.mark.parametrize("page,sub", [("officers", True), ("gic", True),
                                          ("officers", False), ("gic", False)])
    def test_anchor_depth_is_at_most_one(self, env, page, sub):
        html = officers_html(env, subscriber=sub) if page == "officers" \
            else gic_html(env, subscriber=sub)
        depth = worst = 0
        for tok in re.findall(r"</?a\b", html):
            depth += 1 if tok == "<a" else -1
            worst = max(worst, depth)
        assert worst <= 1, f"{page}: nested anchors (depth {worst}) — invalid HTML"


class TestNoPrivateStyling:
    """The class of bug this whole phase undoes: a page styling itself."""

    @pytest.mark.parametrize("page", ["officers.html", "gic.html"])
    def test_no_orbitron_in_rendered_output(self, env, page):
        # Orbitron is referenced across the site but loaded NOWHERE, so every
        # such heading silently renders as a generic sans.
        html = (officers_html(env, subscriber=True) if page == "officers.html"
                else gic_html(env, subscriber=True))
        assert "Orbitron" not in html

    @pytest.mark.parametrize("page", ["officers.html", "gic.html"])
    def test_no_hardcoded_hex_colours_in_rendered_output(self, env, page):
        html = (officers_html(env, subscriber=True) if page == "officers.html"
                else gic_html(env, subscriber=True))
        hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b", html))
        assert not hexes, f"{page} hardcodes {sorted(hexes)} — use a --wtf-* token"

    def test_the_paywall_cta_is_not_a_hardcoded_colour(self, env):
        """It had drifted to four different colours, none of them --wtf-accent."""
        html = officers_html(env, subscriber=False)
        assert "#ef4444" not in html and "#3b82f6" not in html and "#0af" not in html


class TestExternalTextIsEscaped:
    def test_mandate_summary_is_escaped(self, env):
        html = officers_html(env, subscriber=True)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "<script>alert(1)" not in html
