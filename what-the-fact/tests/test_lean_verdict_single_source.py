"""Lean and verdict colour each have ONE definition (task #6310).

article.html carried FIVE independent copies of the lean map and THREE of the
verdict map. They did not merely drift from the design tokens — they disagreed
with EACH OTHER, and two of them were wrong in ways a reader could see:

  1. `.wtf-band-right` and `.wtf-band-left` were BOTH reds. The two poles of a
     diverging left/right scale rendered in the same colour family, so the band
     label under the B.I.A.S. bar could not distinguish them.

  2. Four of the five put GREEN at the centre of the lean spectrum — including
     `.wtf-bias-bar`, the most prominent element on the page. Green is a VERDICT
     colour in this design system (`--wtf-established`). Painting a centrist
     outlet green says it is a CORRECT one, which is an editorial claim the site
     does not make. `lean_pill`'s own docstring had forbidden exactly this since
     it was written — the guard existed and was never applied at the call sites.

  3. One story could show three different greens for "verified": the kicker
     chip, the V.E.R.I.F.Y. headline and the third-party fact-check row each
     had their own map.

Everything now resolves through `lean_token()` / `verdict_class()` in
_archetypes.html. These tests pin that, and pin the two properties that made the
old state a defect rather than a preference.

NOT pinned here, deliberately: the exact token VALUES. Those live in style.css
and are the designer's to change. What must not change is that there is one
place to change them.

Non-vacuity, measured against the pre-fix files from git rather than asserted:
four of the six file-scanning tests FAIL on the old article.html (both palette
scanners, the B.I.A.S. gradient, the resolver imports). Two PASS on it, and that
is correct — they are FORWARD guards, not detectors of this bug:
  • `test_svg_lean_colour_...` — the old code used a hex literal in the
    presentation attribute, which paints fine. The failure mode it guards only
    becomes reachable once a var() is in play, i.e. after this change.
  • `test_the_two_poles_...` — style.css was already right; the bug was that
    article.html did not USE it. This guards the tokens against a future edit.
"""
import pathlib
import re

import jinja2
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TPL = ROOT / "consumer" / "templates"
ARTICLE = TPL / "article.html"
CSS = ROOT / "consumer" / "static" / "style.css"

# The retired palettes, verbatim. Any reappearance in article.html means a sixth
# copy of the map was born.
RETIRED_LEAN = ["#dc2626", "#f97316", "#22c55e", "#0ea5e9", "#2563eb"]
RETIRED_VERDICT = ["#4ade80", "#fbbf24", "#f87171", "#84cc16", "#a3e635"]

# The defect is not "a hex exists in article.html". A 1,069-line page carries
# many colours on many axes — cross-watch PRODUCT identity, section headings, a
# job-result badge — and forcing those onto lean/verdict tokens would be the
# MIRROR of the bug this file exists to prevent: a colour made to mean something
# it does not mean.
#
# The defect is specifically COLOUR CHOSEN FROM A MEASUREMENT. So the scanner
# looks for a retired hex on a line that also branches on the measurement. That
# is a positive signature of the bug rather than a growing allowlist of
# innocents — an allowlist has to be extended every time the page grows, and
# each extension is a chance to wave through a real sixth map.
_MEASUREMENT_DRIVEN = re.compile(
    r"\bclaim\.status\b|\boverall_verdict\b|\bgfc\.verdict\b"     # verdict axis
    r"|\bbias_band\b|\boutlet_rolling_band\b|\bsource_bias_lean\b"  # lean axis
    r"|\bpt\.band\b|\b_b ==|\b_cb ==|\bob ==\b"                   # their locals
    r"|wtf-band-(left|center|right)|wtf-bias-bar"                 # the band CSS classes
)


def _macros():
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TPL)))
    return env.get_template("_archetypes.html").module


# Comments cannot paint anything, and a comment EXPLAINING a retired palette is
# the most likely place for one to appear. Scanning them produces a permanent
# false positive that pressures the next author to delete the explanation — so
# strip Jinja and CSS comments before looking for live colour.
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _code_only(path):
    """File content with comments blanked out, line numbering preserved."""
    src = path.read_text(encoding="utf-8")
    for pat in (_JINJA_COMMENT, _CSS_COMMENT):
        src = pat.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return src


# ── the resolvers themselves ────────────────────────────────────────────────

@pytest.mark.parametrize("bucket,token", [
    ("left", "--wtf-left"),
    ("center-left", "--wtf-center-left"),
    ("center", "--wtf-center"),
    ("center-right", "--wtf-center-right"),
    ("right", "--wtf-right"),
])
def test_lean_token_maps_every_band(bucket, token):
    assert str(_macros().lean_token(bucket)) == token


def test_lean_token_emits_no_whitespace():
    """A stray newline inside var(...) is a silently unstyled element.

    The macro is interpolated straight into `var({{ ... }})`, so Jinja
    whitespace control is load-bearing, not cosmetic.
    """
    for b in ["left", "center", "right", "", None, "bogus"]:
        v = str(_macros().lean_token(b))
        assert v == v.strip() and "\n" not in v, f"{b!r} -> {v!r}"


def test_an_unscored_outlet_is_muted_not_centre():
    """Absence of a lean is not a middling lean.

    Rendering an unscored outlet as `center` asserts a measurement we do not
    have — the same objection as ADR-020 (no province filter over a column that
    is 66% populated).
    """
    m = _macros()
    for absent in ["", None, "unscored", "bogus"]:
        assert str(m.lean_token(absent)) == "--wtf-text-muted"


def test_lean_pill_keeps_its_own_fallback():
    """lean_pill is called from 8 templates; its rendering must not move here.

    It passes an explicit '--wtf-center' fallback so this refactor is invisible
    to the seven pages that are not article.html.
    """
    assert "var(--wtf-center)" in str(_macros().lean_pill(""))


@pytest.mark.parametrize("verdict,cls", [
    ("verified", "is-established"),
    ("true", "is-established"),
    ("mostly_true", "is-established"),
    ("mixed", "is-developing"),
    ("disputed", "is-contested"),
    ("false", "is-contested"),
])
def test_verdict_class_maps_every_verdict(verdict, cls):
    assert str(_macros().verdict_class(verdict)) == cls


@pytest.mark.parametrize("verdict", [
    "unverifiable", "descriptive_reporting", "unverified", None, "", "bogus",
])
def test_no_verdict_is_muted_never_amber(verdict):
    """"No claims to check" is an ABSENCE of a verdict.

    Amber (`is-developing`) reads as "disputed" — a different and false claim.
    wtf.md is explicit that descriptive_reporting warrants no chip at all.
    """
    assert str(_macros().verdict_class(verdict)) == "is-unestablished"


# ── the page ────────────────────────────────────────────────────────────────

def test_article_has_no_sixth_copy_of_the_lean_map():
    src = _code_only(ARTICLE)
    offenders = [
        f"line {i}: {ln.strip()[:90]}"
        for i, ln in enumerate(src.splitlines(), 1)
        for hexv in RETIRED_LEAN
        if hexv in ln and _MEASUREMENT_DRIVEN.search(ln)
    ]
    assert not offenders, (
        "Retired lean palette is back in article.html. Use lean_token():\n  "
        + "\n  ".join(offenders)
    )


def test_article_has_no_fourth_copy_of_the_verdict_map():
    src = _code_only(ARTICLE)
    offenders = [
        f"line {i}: {ln.strip()[:90]}"
        for i, ln in enumerate(src.splitlines(), 1)
        for hexv in RETIRED_VERDICT
        if hexv in ln and _MEASUREMENT_DRIVEN.search(ln)
    ]
    assert not offenders, (
        "Retired verdict palette is back in article.html. Use verdict_class():\n  "
        + "\n  ".join(offenders)
    )


def test_the_two_poles_are_not_the_same_colour():
    """The defect that made this a bug and not a preference.

    `.wtf-band-left` and `.wtf-band-right` were both reds, so a right-leaning
    article's band label looked like a left-leaning one. Whatever the tokens
    become, the poles must stay distinct.
    """
    css = CSS.read_text(encoding="utf-8")

    def value(token):
        m = re.search(rf"{re.escape(token)}:\s*(#[0-9a-fA-F]{{3,8}})", css)
        assert m, f"{token} is not defined in style.css"
        return m.group(1).lower()

    left, right, centre = value("--wtf-left"), value("--wtf-right"), value("--wtf-center")
    assert left != right, "the two poles of the lean scale resolve to one colour"
    assert centre not in (left, right), "the centre collides with a pole"


def test_the_centre_of_the_lean_scale_is_not_a_verdict_colour():
    """Green at the midpoint reads as "centre = correct". It is a verdict hue."""
    css = CSS.read_text(encoding="utf-8")

    def value(token):
        m = re.search(rf"{re.escape(token)}:\s*(#[0-9a-fA-F]{{3,8}})", css)
        return m.group(1).lower() if m else None

    centre = value("--wtf-center")
    verdict_hues = {value(t) for t in
                    ("--wtf-established", "--wtf-developing", "--wtf-contested")}
    assert centre not in verdict_hues, (
        f"--wtf-center ({centre}) is also a verdict colour — the lean midpoint "
        "must not carry a judgement"
    )


def test_bias_scale_gradient_is_the_five_tokens():
    """The design package specifies "a gradient of the five band colours"."""
    src = _code_only(ARTICLE)
    m = re.search(r"\.wtf-bias-bar\s*\{[^}]*\}", src, re.S)
    assert m, ".wtf-bias-bar rule not found"
    rule = m.group(0)
    for token in ("--wtf-left", "--wtf-center-left", "--wtf-center",
                  "--wtf-center-right", "--wtf-right"):
        assert f"var({token})" in rule, f"B.I.A.S. gradient is missing {token}"


def test_article_imports_the_resolvers():
    src = ARTICLE.read_text(encoding="utf-8")
    assert re.search(r'{%\s*from\s+"_archetypes\.html"\s+import\b[^%]*\blean_token\b', src)
    assert re.search(r'{%\s*from\s+"_archetypes\.html"\s+import\b[^%]*\bverdict_class\b', src)


def test_svg_lean_colour_uses_style_not_a_presentation_attribute():
    """`stroke="var(--x)"` paints NOTHING — custom properties do not resolve in
    an SVG presentation attribute. They do resolve in `style`."""
    src = _code_only(ARTICLE)
    bad = re.findall(r'(?:stroke|fill)="var\(--', src)
    assert not bad, f"{len(bad)} SVG presentation attribute(s) use var() and will not paint"
