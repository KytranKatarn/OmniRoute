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


OWNERS = [
    {
        "owner_name": "Postmedia Network", "owner_type": "corporate",
        "outlet_count": 3, "avg_bias": 0.42, "bias_band": "center-right",
        "outlets": [
            {"slug": "national-post", "name": "National Post", "bias_lean": "right"},
            {"slug": "montreal-gazette", "name": "Montreal Gazette", "bias_lean": "center"},
            # an UNSCORED outlet — must render as "not yet scored", never as centre
            {"slug": "regina-leaderpost", "name": "Regina Leader-Post", "bias_lean": None},
        ],
    },
    {
        "owner_name": "CBC/Radio-Canada", "owner_type": "public",
        "outlet_count": 1, "avg_bias": None, "bias_band": None,
        "outlets": [{"slug": "cbc", "name": "CBC News", "bias_lean": "center-left"}],
    },
    # SINGLE-BAND owner: proves the "spans N bands" note appears only when the
    # portfolio actually spreads, rather than on every card.
    {
        "owner_name": "Canadaland", "owner_type": "independent",
        "outlet_count": 1, "avg_bias": -0.61, "bias_band": "left",
        "outlets": [{"slug": "canadaland", "name": "Canadaland", "bias_lean": "left"}],
    },
]

# The RETIRED ramp this page used to define privately. Green at the midpoint.
RETIRED_RAMP = ["#ef4444", "#f97316", "#22c55e", "#0ea5e9", "#2563eb"]


def owners_html(env, *, subscriber):
    return env.get_template("owners.html").render(
        owners=OWNERS, source_count=46, unattributed=2, is_subscriber=subscriber)


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


class TestOwnersLeanIsHonest:
    """The reason /owners was migrated. Not cosmetic — editorial integrity.

    The page privately defined the RETIRED ramp (green at the midpoint) and drew
    lean as a bare 8px dot whose only text was a title="" attribute.
    """

    def test_the_retired_ramp_is_gone(self, env):
        html = owners_html(env, subscriber=True)
        for hexcode in RETIRED_RAMP:
            assert hexcode not in html, (
                f"{hexcode} is from the retired lean scale — /owners must not "
                "redefine the palette"
            )

    def test_no_green_is_used_for_the_centre(self, env):
        """A green midpoint reads as 'centre = good' — an editorial claim this
        site must not make. The diverging scale is red pole / neutral / blue."""
        html = owners_html(env, subscriber=True)
        assert "#22c55e" not in html and "22c55e" not in html

    def test_every_lean_carries_a_TEXT_label_not_just_colour(self, env):
        """Colour alone fails common colour-vision deficiencies."""
        html = owners_html(env, subscriber=True)
        # every bucket present in the fixture must appear as readable text
        for label in ("Right", "Center", "Center Left", "Center Right"):
            assert label in html, f"lean {label!r} rendered without its text label"

    def test_lean_uses_the_shared_tokens(self, env):
        html = owners_html(env, subscriber=True)
        for token in ("--wtf-right", "--wtf-center", "--wtf-center-left"):
            assert f"var({token})" in html, f"{token} not used — page is off-palette"

    def test_an_unscored_outlet_is_not_silently_called_centre(self, env):
        """Absence of a score and a centre score are different facts."""
        html = owners_html(env, subscriber=True)
        assert "Not yet scored" in html
        assert "Regina Leader-Post" in html

    def test_an_owner_with_no_band_still_renders(self, env):
        """CBC has avg_bias=None/bias_band=None — it must not vanish."""
        html = owners_html(env, subscriber=True)
        assert "CBC/Radio-Canada" in html and "CBC News" in html

    def test_the_average_says_it_is_an_average_and_over_how_many(self, env):
        """F.O.R.G.E. #2968: a single pill presented as THE owner's lean reads
        as uniform. Postmedia really does span two bands over 9 outlets live."""
        html = owners_html(env, subscriber=True)
        assert "Average across 2 scored outlets" in html, (
            "the aggregate must name itself an average and state its N"
        )

    def test_a_multi_band_portfolio_says_so(self, env):
        """An owner at opposite poles averages to the CENTRE — describing a
        polarised portfolio as centrist. Same shape as the green-midpoint bug."""
        html = owners_html(env, subscriber=True)
        assert "spans 2 bands" in html

    def test_a_single_band_owner_does_NOT_claim_a_spread(self, env):
        """The note must be EARNED, not printed on every card.

        Renders the single-band owner ALONE. An earlier version of this test
        sliced the full page on the owner name and passed no matter what — the
        name occurs twice (owner and outlet), so [-1] landed in the footer,
        which never contains "spans". Mutating the condition to
        `bands|length > 0` did not fail it. A single-owner render cannot be
        trivially true this way.
        """
        single = [o for o in OWNERS if o["owner_name"] == "Canadaland"]
        html = env.get_template("owners.html").render(
            owners=single, source_count=46, unattributed=0, is_subscriber=True)
        assert "Canadaland" in html, "fixture did not render"
        assert "Average across 1 scored outlet" in html
        assert "spans" not in html, "a one-band portfolio must not claim a spread"


class TestOwnershipSharesAreArithmeticallyPossible:
    """Shares of one population cannot exceed 100%.

    Found live AFTER deploy: the four concentration tiles read
    55% + 10% + 45% + 39% = 149%. `source_count` counted outlets that had
    PUBLISHED IN THE LAST 48 HOURS (31 of 46) while `outlet_count` counts ALL of
    an owner's outlets — two different populations. The header also claimed
    "31 outlets tracked" for a site tracking 46. Fixed in routes.py by counting
    every source; pinned here at BOTH ends, because the template is arithmetic
    and the route is the denominator.
    """

    def test_the_shares_cannot_exceed_one_hundred_percent(self, env):
        total = sum(o["outlet_count"] for o in OWNERS)
        html = env.get_template("owners.html").render(
            owners=OWNERS, source_count=total, unattributed=0, is_subscriber=True)

        # Scope to the CONCENTRATION TILES. The per-owner cards use the same
        # "% of tracked" wording, and those are the same population counted a
        # second time — summing every match on the page double-counts and the
        # assertion fails on correct markup. (It did; that is why this is
        # scoped.) The tiles are the only set that must partition to 100%.
        tiles = html.split('class="wtf-a-tiles"', 1)
        assert len(tiles) == 2, "tile block not found — assertion would be vacuous"
        block = tiles[1].split("</div>\n</div>", 1)[0]

        pcts = [int(m) for m in re.findall(r"(\d+)% of tracked", block)]
        assert pcts, "no tile shares rendered — this assertion would be vacuous"
        # one point of slack per share for independent rounding
        assert sum(pcts) <= 100 + len(pcts), (
            f"tile shares sum to {sum(pcts)}% — the denominator does not match "
            "the population being partitioned"
        )

    def test_the_route_denominator_is_not_time_windowed(self):
        """Route-level guard: the count feeding every share must not filter on
        recency. Read from source, so it needs no database."""
        src = (TPL.parents[1] / "consumer" / "routes.py").read_text()
        start = src.index("def owners_listing():")
        body = src[start:src.index("\n@bp.", start)]
        line = [ln for ln in body.splitlines() if "source_count =" in ln]
        assert line, "source_count assignment not found in owners_listing"
        assert "INTERVAL" not in line[0] and "ingested_at" not in line[0], (
            "source_count is time-windowed again — shares will not sum to 100% "
            "and the header will understate how many outlets are tracked"
        )


class TestOwnersPageShape:
    def test_concentration_tiles_render(self, env):
        html = owners_html(env, subscriber=True)
        for label in ("Corporate", "Public", "Non-profit", "Independent"):
            assert label in html

    def test_anonymous_gets_the_shared_paywall_not_a_cyan_one(self, env):
        html = owners_html(env, subscriber=False)
        assert "wtf-a-pay" in html and "/login?next=/owners" in html
        assert "#0af" not in html, "the old cyan-on-black CTA is back"

    def test_no_gated_owner_leaks_to_anonymous(self, env):
        html = owners_html(env, subscriber=False)
        for secret in ("Postmedia Network", "National Post", "CBC/Radio-Canada"):
            assert secret not in html

    @pytest.mark.parametrize("sub", [True, False])
    def test_anchor_depth_is_at_most_one(self, env, sub):
        html = owners_html(env, subscriber=sub)
        depth = worst = 0
        for tok in re.findall(r"</?a\b", html):
            depth += 1 if tok == "<a" else -1
            worst = max(worst, depth)
        assert worst <= 1, f"nested anchors (depth {worst})"

    def test_no_orbitron_and_no_literal_hex(self, env):
        html = owners_html(env, subscriber=True)
        assert "Orbitron" not in html
        hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b", html))
        assert not hexes, f"owners.html hardcodes {sorted(hexes)}"
