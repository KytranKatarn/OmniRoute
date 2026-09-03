"""Homepage lean/verdict colour convergence (index.html, sibling of #6310).

`consumer/templates/index.html` had two independent copies of the SAME defect
family that `tests/test_lean_verdict_single_source.py` fixed on article.html:

  1. TWO lean-colour derivation sites. `BIAS_COLOURS` correctly resolved
     --wtf-left/--wtf-center-left/--wtf-center/--wtf-center-right/--wtf-right
     via `_leanToken()` for the discrete map pins. Separately, the choropleth
     ramp's `_LEAN_NEUTRAL`/`_LEAN_L`/`_LEAN_R` called `_leanToken()` a SECOND
     time for the same three tokens and converted the result with its own
     independent `_rgb(...) || [hardcoded fallback]` — a fallback that
     disagreed with BIAS_COLOURS's own "#929aa5" fallback (a missing
     --wtf-left would render the discrete pins grey but the choropleth ramp's
     pole in a hardcoded red). Fixed by deriving the ramp's RGB arrays from
     BIAS_COLOURS's already-resolved, already-fallback-safe hex strings
     instead of re-reading the CSS custom properties.

  2. A hardcoded verdict-colour map inside `loadArticleFeed()`: `#4ade80` /
     `#fbbf24` / `#f87171` for established/developing/contested, tracking no
     token at all. Fixed with a `VERDICT_COLOURS` object built the same way
     as `BIAS_COLOURS` (resolve via `_leanToken()`, fail-safe to a single
     grey) — mirroring the SAME mechanism rather than inventing a second one.
     Its fail-safe deliberately falls to `--wtf-text-muted`, never to another
     verdict's colour, so a missing token can never make an ESTABLISHED fact
     render as "developing" (amber) or vice versa.

Non-vacuity, measured against the pre-fix file from git rather than asserted
(same method as test_lean_verdict_single_source.py's docstring): the two
detector functions below (`_lean_derivation_offenders`,
`_retired_verdict_hex_offenders`), run against
`git show HEAD:what-the-fact/consumer/templates/index.html` BEFORE this fix
was committed, both report real offenders —

    lean offenders: ['_rgb(_leanToken(...)) second-derivation pattern present',
                      "lean token(s) read more than once: "
                      "{'--wtf-left': 2, '--wtf-center': 2, '--wtf-right': 2}"]
    verdict hex offenders: ['#4ade80', '#fbbf24', '#f87171']

and report nothing against the fixed working tree. This was run once, by
hand, to prove the detectors are not vacuous — it is not re-run as a live
git-diffing test here, because the moment this fix is committed `HEAD` stops
being "the pre-fix file" and a permanent git-history assertion would become
either meaningless or actively wrong. The tests below assert forward, against
the file as shipped, exactly like the sibling suite.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = ROOT / "consumer" / "templates" / "index.html"

# The retired verdict palette, verbatim. Must not reappear anywhere in
# index.html — not in live code, not even inside an explanatory comment (a
# comment quoting the retired hex is a permanent false negative for any
# grep-based regression test, per #6149/#6310).
RETIRED_VERDICT_HEX = ["#4ade80", "#fbbf24", "#f87171"]

# The literal shape of the old second derivation: read the token, convert it,
# right there — independent of BIAS_COLOURS.
_RGB_LEANTOKEN = re.compile(r"_rgb\(\s*_leanToken\(")

# Every place `_leanToken()` is asked for one of the three lean-ramp poles.
# Deliberately anchored on the closing quote+paren so "--wtf-center" cannot
# accidentally match "--wtf-center-left" / "--wtf-center-right" (a distinct,
# unrelated pair of tokens with their own single BIAS_COLOURS call site).
_LEAN_CALL = re.compile(r'_leanToken\(\s*"(--wtf-(?:left|center|right))"\s*\)')


def _lean_call_counts(src: str) -> dict:
    counts: dict = {}
    for m in _LEAN_CALL.finditer(src):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def _lean_derivation_offenders(src: str) -> list:
    """Non-empty iff a second, independent lean-colour derivation exists."""
    offenders = []
    if _RGB_LEANTOKEN.search(src):
        offenders.append(
            "_rgb(_leanToken(...)) second-derivation pattern present"
        )
    dup = {k: v for k, v in _lean_call_counts(src).items() if v > 1}
    if dup:
        offenders.append(f"lean token(s) read more than once: {dup}")
    return offenders


def _retired_verdict_hex_offenders(src: str) -> list:
    return [h for h in RETIRED_VERDICT_HEX if h in src]


# ── the file, as shipped ────────────────────────────────────────────────────

def test_lean_colour_has_a_single_derivation_site():
    src = INDEX.read_text(encoding="utf-8")
    offenders = _lean_derivation_offenders(src)
    assert not offenders, (
        "index.html has more than one lean-colour derivation site: "
        + "; ".join(offenders)
    )


def test_lean_ramp_arrays_derive_from_bias_colours():
    """Positive assertion of the fix's actual shape, not just "not the old
    pattern" — the choropleth ramp's RGB arrays must come from the SAME
    resolved-and-fallback-safe map the discrete pins use."""
    src = INDEX.read_text(encoding="utf-8")
    assert re.search(r'_LEAN_NEUTRAL\s*=\s*_rgb\(\s*BIAS_COLOURS\["center"\]\s*\)', src)
    assert re.search(r'_LEAN_L\s*=\s*_rgb\(\s*BIAS_COLOURS\["left"\]\s*\)', src)
    assert re.search(r'_LEAN_R\s*=\s*_rgb\(\s*BIAS_COLOURS\["right"\]\s*\)', src)


def test_index_has_no_retired_verdict_hex():
    src = INDEX.read_text(encoding="utf-8")
    offenders = _retired_verdict_hex_offenders(src)
    assert not offenders, (
        "Retired verdict palette is back in index.html: " + ", ".join(offenders)
    )


def test_verdict_colours_resolve_from_css_tokens():
    src = INDEX.read_text(encoding="utf-8")
    for token in ("--wtf-established", "--wtf-developing", "--wtf-contested"):
        assert f'_leanToken("{token}")' in src, f"{token} is not resolved via _leanToken()"
    for key in ("established", "developing", "contested"):
        assert f"VERDICT_COLOURS.{key}" in src, f"loadArticleFeed must read VERDICT_COLOURS.{key}"


def test_verdict_colour_fallback_is_muted_never_another_verdict():
    """An absent/unrecognised verdict token must fall to the muted "no data"
    grey this page already uses elsewhere — never silently borrow another
    verdict's hue (amber included). That is the failure mode that would make
    an ESTABLISHED fact render as "developing"."""
    src = INDEX.read_text(encoding="utf-8")
    m = re.search(
        r"Object\.keys\(VERDICT_COLOURS\)\.forEach\(function \(k\) \{\s*"
        r"if \(!VERDICT_COLOURS\[k\]\) \{ VERDICT_COLOURS\[k\] = ([^;]+); \}",
        src,
    )
    assert m, "VERDICT_COLOURS fail-safe forEach not found"
    fallback_expr = m.group(1)
    assert "--wtf-text-muted" in fallback_expr
    assert "--wtf-developing" not in fallback_expr
    assert "--wtf-established" not in fallback_expr
    assert "--wtf-contested" not in fallback_expr
