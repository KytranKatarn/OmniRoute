"""wtf-aurora token convergence — the drifted literal pair is gone from every
site this session actually changed (task #6314).

style.css declares `--wtf-aurora: #8b5cf6`. `git log -p -- style.css` shows
the token was "corrected #7c3aed -> #8b5cf6 per the spec", but that
correction was never propagated to the sites that hardcoded the OLD value
directly instead of referencing the custom property. Same defect *class* as
test_lean_verdict_single_source.py and test_index_colour_convergence.py — a
design value drifts because nothing forces call sites through the token —
on a different axis (agent / CREED-governance branding purple, not lean or
verdict colour).

This file does NOT assert the retired pair is gone from the codebase, or
even from every file it touches — either would be wrong. Several sites use
the identical hex for a genuinely different, unrelated semantic and were
deliberately left alone after reading each one's surrounding context
(element, class, what the colour is FOR), the same discipline the two
sibling files above establish for the CWP cross-watch product-identity map:

  * mps.html, and routes.py's /senator/<slug> route — the hex is the real
    display colour of the Progressive Senate Group caucus (confirmed via
    the adjacent CAUCUS_LABELS entry, 'PSG': 'Progressive Senate Group').
    Recolouring a real political caucus tag because it happens to share a
    hex with an unrelated AI-branding purple would be a NEW bug.
  * article.html, news.html, and index.html's OWN MP-mentions badge — a
    cross-watch CONTENT-TYPE colour (procurement/parliament_vote/
    legal_ruling/civic_event), a distinct axis. index.html therefore has
    ONE site fixed (AGENT_COLOURS' A.U.R.O.R.A. entry) and ONE left alone
    (the MP-mentions badge) — a whole-file "zero occurrences" sweep would
    be WRONG for this file, so it gets site-scoped assertions instead.
  * entity.html, cross_watch.html — a cross-watch PRODUCT-identity colour
    map (legal-watch's slot happens to be purple).
  * crtc.html — a media-ownership TYPE colour map (corporate/public/
    non_profit/independent).
  * routes.py's BEAT_META — a news-beat colour, the same exemption class as
    index.html's BEAT_CONFIG in test_index_colour_convergence.py's scope.
    routes.py therefore ALSO gets site-scoped assertions, not a sweep.
  * weather.html — out of scope for this task (fixed concurrently, in a
    separate change, by a different process).

Three files (style.css, governance.html, activity.html) had EVERY occurrence
on the aurora axis, so those get an honest whole-file sweep. routes.py and
index.html had a mix, so those get one assertion per site instead — proving
both that the fixed site changed and that the deliberately-untouched site
did NOT.

Non-vacuity, measured against `git show HEAD:<path>` from immediately
before this session's fix (not re-run live here — same reasoning as
test_index_colour_convergence.py's docstring: once committed, HEAD stops
being "the pre-fix file" and a permanent git-history assertion would become
either meaningless or actively wrong). Confirmed by hand, once, by writing
each pre-fix `git show HEAD:...` blob to a temp file and running the SAME
`_offenders()` detector below against it:

    consumer/static/style.css          1 offender  (.wtf-team-card--teaser)
    consumer/routes.py                 3 offenders (AURORA entry + the 2
                                        deliberately-untouched BEAT_META /
                                        PSG sites — see routes.py's own
                                        site-scoped tests below)
    consumer/templates/index.html      2 offenders (AGENT_COLOURS entry +
                                        the deliberately-untouched MP badge)
    consumer/templates/governance.html 9 offenders
    consumer/templates/activity.html   10 offenders

all matching this file's own accounting of what was fixed vs. deliberately
left alone. That same non-vacuity pass is also what caught two real bugs in
an earlier draft of this file's own comment-stripper — see the comment
above `_JINJA_COMMENT`/`_CSS_COMMENT` below.
"""
import io
import pathlib
import re
import tokenize

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONSUMER = ROOT / "consumer"

STYLE_CSS = CONSUMER / "static" / "style.css"
ROUTES_PY = CONSUMER / "routes.py"
GOVERNANCE = CONSUMER / "templates" / "governance.html"
ACTIVITY = CONSUMER / "templates" / "activity.html"
INDEX = CONSUMER / "templates" / "index.html"
MPS = CONSUMER / "templates" / "mps.html"  # deliberately left alone

# Files where EVERY occurrence was on the aurora axis — a whole-file sweep
# for zero retired-hex lines is the correct, honest end state.
FULLY_CONVERGED_FILES = [STYLE_CSS, GOVERNANCE, ACTIVITY]

RETIRED_AURORA_HEX = ["#7c3aed", "#a78bfa"]

# Comments cannot paint anything, and an explanatory comment naming the
# retired hex (e.g. this session's own routes.py note, "was the
# pre-correction literal #7c3aed") is the most likely place for one to
# appear. Scanning comments would be a permanent false positive that
# pressures the next author to delete the explanation — the exact reasoning
# test_lean_verdict_single_source.py's _code_only() documents; these two
# patterns are copied verbatim from it.
#
# Deliberately NOT a naive `#.*$` / `//.*$` line-comment regex for the HTML
# templates: `#` opens a hex literal (the very thing this test looks for)
# and `//` appears in every `https://` URL on these pages (e.g.
# governance.html's `href="https://creed-ai.org" style="color:#7c3aed;"` —
# the hex sits AFTER the `//`). A naive regex would blank the hex it exists
# to find. Caught live: an earlier draft of this test used exactly that
# regex (plus an unconditional `#.*$` "Python comment" strip applied to
# EVERY file type), and the non-vacuity pass documented in the module
# docstring came back 0 offenders on all five pre-fix files where it should
# have found real ones — the detector was silently eating its own targets.
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_python_comments(src: str) -> str:
    """Blank out genuine Python '#' comments via `tokenize` — never string
    literals, which is exactly where our target hex values live in
    routes.py (e.g. `"accent_colour": "#7c3aed"`). A regex cannot tell a
    comment from a string; the tokenizer can."""
    lines = src.splitlines(keepends=True)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                (srow, scol), (erow, ecol) = tok.start, tok.end
                if srow == erow:
                    line = lines[srow - 1]
                    lines[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
    except tokenize.TokenizeError:
        return src
    return "".join(lines)


def _code_only(path: pathlib.Path) -> str:
    """File content with comments blanked out, line numbering preserved."""
    src = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return _strip_python_comments(src)
    for pat in (_JINJA_COMMENT, _CSS_COMMENT):
        src = pat.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), src)
    return src


def _offenders(path: pathlib.Path) -> list:
    src = _code_only(path)
    return [
        f"line {i}: {ln.strip()[:90]}"
        for i, ln in enumerate(src.splitlines(), 1)
        for hexv in RETIRED_AURORA_HEX
        if hexv in ln
    ]


# ── the three files where EVERY occurrence was fixed ────────────────────────

@pytest.mark.parametrize(
    "path", FULLY_CONVERGED_FILES,
    ids=[str(p.relative_to(ROOT)) for p in FULLY_CONVERGED_FILES],
)
def test_fully_converged_file_has_no_live_retired_aurora_hex(path):
    offenders = _offenders(path)
    assert not offenders, (
        f"{path.relative_to(ROOT)} still carries the retired --wtf-aurora "
        "literal — reference var(--wtf-aurora) instead:\n  "
        + "\n  ".join(offenders)
    )


def test_style_css_token_value_itself_is_unchanged():
    """This task converges REFERENCES to the token — it must never repoint
    the token's own declared value. --wtf-aurora stays #8b5cf6."""
    src = STYLE_CSS.read_text(encoding="utf-8")
    m = re.search(r"--wtf-aurora:\s*(#[0-9a-fA-F]{3,8});", src)
    assert m, "--wtf-aurora is not declared in style.css"
    assert m.group(1).lower() == "#8b5cf6"


_POSITIVE_REFERENCE_CASES = [
    (STYLE_CSS, "var(--wtf-aurora)"),
    (ROUTES_PY, '"var(--wtf-aurora)"'),
    (INDEX, '"A.U.R.O.R.A.":"var(--wtf-aurora)"'),
    (GOVERNANCE, "color:var(--wtf-aurora);"),
    (ACTIVITY, "color:var(--wtf-aurora);"),
]


@pytest.mark.parametrize(
    "path,needle", _POSITIVE_REFERENCE_CASES,
    ids=[str(p.relative_to(ROOT)) for p, _ in _POSITIVE_REFERENCE_CASES],
)
def test_the_fix_is_a_positive_reference_not_merely_an_absence(path, needle):
    """Forward guard: deleting the colour outright (leaving no accent at
    all) would satisfy the "no retired hex" test above without actually
    converging on the token. Pin the real shape of the fix, not just the
    absence of the old one."""
    assert needle in path.read_text(encoding="utf-8")


# ── the two files that were PARTIALLY converged — one site fixed, one or
#    more sites deliberately left alone for a different, real semantic ──────

def test_routes_py_aurora_entry_is_fixed_but_beat_and_caucus_sites_are_not():
    """routes.py's TEAM_AGENTS A.U.R.O.R.A. entry is the same axis as
    style.css's token and was fixed. Its BEAT_META 'science-tech' beat
    colour and its /senator/<slug> route's PSG caucus colour are a
    different, real semantic each (a news beat; a Senate caucus) and were
    deliberately left untouched — a whole-file sweep would be wrong here,
    so each site is asserted individually, in both directions."""
    src = ROUTES_PY.read_text(encoding="utf-8")
    assert '"accent_colour": "#7c3aed"' not in src
    assert '"accent_colour": "var(--wtf-aurora)"' in src
    # Regression guards: these deliberately-untouched sites are unchanged.
    assert '"science-tech",   "🔬 Sci-Tech",     "#a78bfa"' in src
    assert '"PSG": "#7c3aed", "GRO": "#b45309", "Non-affiliated": "#888888"' in src


def test_index_aurora_agent_colour_is_fixed_but_mp_badge_is_not():
    """index.html's AGENT_COLOURS map holds one entry per newsroom agent;
    the other four tokened entries (FACT/BIAS/VERIFY/LOCAL) already matched
    their CSS tokens, only A.U.R.O.R.A. had drifted, and it is now fixed.
    The MP-mentions card badge a few hundred lines later is an unrelated
    "Parliament content" colour (same hex, same pattern as news.html's
    identical badge) and was deliberately left untouched."""
    src = INDEX.read_text(encoding="utf-8")
    assert '"A.U.R.O.R.A.":"#7c3aed"' not in src
    assert '"A.U.R.O.R.A.":"var(--wtf-aurora)"' in src
    # Regression guard: the MP-mentions badge is unchanged.
    assert 'color:#a78bfa;border:1px solid #4c1d9544' in src


def test_mps_caucus_colour_was_correctly_left_alone():
    """The one call site this task's own instructions singled out for
    caution. mps.html's '#7c3aed' is the Progressive Senate Group's real
    caucus colour (CAUCUS_LABELS: 'PSG': 'Progressive Senate Group'), not
    the AI-branding purple — recolouring a real political caucus because it
    shares a hex with an unrelated token would be a new bug, not a fix.
    This is a REGRESSION guard, not a claim that mps.html is "correct" in
    some absolute sense — only that this task did not touch it."""
    src = MPS.read_text(encoding="utf-8")
    assert "'PSG':'#7c3aed'" in src
    assert "Progressive Senate Group" in src
