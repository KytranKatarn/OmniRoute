"""A.U.R.O.R.A. weather page colour convergence (weather.html, sibling of #6310).

`consumer/templates/weather.html` carried the SAME defect family that
`tests/test_lean_verdict_single_source.py` fixed on article.html and
`tests/test_index_colour_convergence.py` fixed on index.html — the design
system declares a token, and this page quietly ignored it and hardcoded the
same colour (or a near-miss of it) independently, more than once.

Three separate instances, plus one unrelated dead-code shadow found in the
same pass:

  1. `--wtf-aurora: #8b5cf6` (style.css) was never referenced. The page
     independently hardcoded `#7c3aed` (eyebrow text, article-card border,
     one footer link) AND `#a78bfa` (aurora badge text, the OTHER footer
     link) — two different near-purples for what is meant to be one accent,
     in the same card. Fixed by pointing every site at `var(--wtf-aurora)`.

  2. `--wtf-developing: #f59e0b` (style.css) was fully honoured by THIS
     SAME FILE's own client-side JS-driven styling for the "is stale"
     semantic (`.wtf-wx-age-stale { color: var(--wtf-developing) }`,
     `.wtf-wx-citycard.is-stale { border-left-color: var(--wtf-developing) }`
     — both untouched, both already correct) — while the Jinja-rendered
     provenance-card block, driven by the SAME boolean (`L.is_stale`) two
     hundred lines away, hardcoded `#7f1d1d` for the card border and
     `#ef4444` for the "⚠ STALE" text: two more independent near-misses of
     the token this page had already proven it knows how to use correctly.
     Fixed by pointing both at `var(--wtf-developing)`, matching the
     pattern the file already proves correct in its own CSS.

  3. `.wtf-wx-card { border-left: 3px solid #f59e0b }` silently duplicated
     `--wtf-developing`'s exact value without referencing the token — a
     fourth independent copy of the same colour. Fixed by referencing the
     token directly.

  4. Dead code, not colour: the page locally redeclared its own
     `PROVINCE_CODES` name→code map and `CENTROIDS` code→lat/lon map, even
     though `WTFMap.PROVINCE_CODES` (the shared `wtf-map.js` component) is
     already loaded on this page and is the copy this file's OWN
     `provinceTooltip()` actually reads. The local copies were referenced
     nowhere else in the file — a pure shadow, deleted.

Deliberately NOT touched (filed separately, confirmed still present below):
`FIRE_STOPS` (fire-hotspot-COUNT ramp) legitimately keeps its own
`#7f1d1d` — a different measurement on a different axis that happens to
share a hex with the is_stale defect above by coincidence, not by copying.
`TEMP_STOPS` (air-temperature ramp) and the "Warmest reading" bar
legitimately keep `#f59e0b` for the same reason. A blanket "this hex must
never appear in the file" rule would be WRONG here — it would delete a
correct, independent design decision along with the bug. See
`_MEASUREMENT_DRIVEN`-style scoping in test_lean_verdict_single_source.py
for the same principle applied to article.html.

Per this session's established rule (also followed by the two sibling
files), none of the retired hex literals are reproduced anywhere in this
file's OWN comments either — a comment quoting a retired/replaced hex is a
permanent grep false positive for any future regression test.

Non-vacuity, measured against the pre-fix file from git rather than
asserted (same method as both sibling files):
`git show HEAD:what-the-fact/consumer/templates/weather.html`, run through
the detector functions below, BEFORE this fix was committed —

    aurora offenders:            ['#7c3aed', '#a78bfa']
    stale-hex(#ef4444) offenders: ['#ef4444']
    is_stale-line offenders (7f1d1d/ef4444 on a line naming L.is_stale):
        ['line 311: <div style="background:#060d14;border:1px solid '
         '{% if L.is_stale %}#7f1d1d{% else %}#1a3a5a{% endif ']
    .wtf-wx-card hardcoded #f59e0b: True

and against the fixed working tree —

    aurora offenders:             []
    stale-hex(#ef4444) offenders: []
    is_stale-line offenders:      []
    .wtf-wx-card hardcoded #f59e0b: False

This was run once, by hand, to prove the detectors are not vacuous — it is
not re-run as a live git-diffing test here, because the moment this fix is
committed `HEAD` stops being "the pre-fix file" and a permanent
git-history assertion would become either meaningless or actively wrong.
The tests below assert forward, against the file as shipped.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEATHER = ROOT / "consumer" / "templates" / "weather.html"

# Fully retired: neither hex has any legitimate remaining use anywhere in
# weather.html, so a blanket file-wide ban is safe (unlike #7f1d1d/#f59e0b
# below, each of which has a genuine surviving unrelated use).
RETIRED_AURORA_HEX = ["#7c3aed", "#a78bfa"]
RETIRED_STALE_TEXT_HEX = ["#ef4444"]


def _retired_aurora_offenders(src: str) -> list:
    return [h for h in RETIRED_AURORA_HEX if h in src]


def _retired_stale_text_offenders(src: str) -> list:
    return [h for h in RETIRED_STALE_TEXT_HEX if h in src]


def _is_stale_line_offenders(src: str) -> list:
    """Lines that name `L.is_stale` and STILL hardcode #7f1d1d or #ef4444 on
    that same line — the exact shape of the split-styling defect. Anchored
    per-line, not as a multi-line span, so it cannot bleed into the
    unrelated FIRE_STOPS ramp lower in the file, which legitimately keeps
    #7f1d1d for a different measurement."""
    offenders = []
    for i, ln in enumerate(src.splitlines(), 1):
        if "is_stale" in ln and ("#7f1d1d" in ln or "#ef4444" in ln):
            offenders.append(f"line {i}: {ln.strip()[:100]}")
    return offenders


def _card_rule_hardcodes_f59e0b(src: str) -> bool:
    m = re.search(r"\.wtf-wx-card\s*\{[^}]*\}", src, re.S)
    assert m, ".wtf-wx-card rule not found"
    return "#f59e0b" in m.group(0)


# ── the file, as shipped ────────────────────────────────────────────────────

def test_weather_has_no_retired_aurora_hex():
    src = WEATHER.read_text(encoding="utf-8")
    offenders = _retired_aurora_offenders(src)
    assert not offenders, (
        "Retired aurora near-purples are back in weather.html: "
        + ", ".join(offenders)
    )


def test_weather_has_no_retired_stale_text_hex():
    src = WEATHER.read_text(encoding="utf-8")
    offenders = _retired_stale_text_offenders(src)
    assert not offenders, (
        "Retired STALE-text hex is back in weather.html: " + ", ".join(offenders)
    )


def test_is_stale_provenance_card_has_no_hardcoded_hex():
    src = WEATHER.read_text(encoding="utf-8")
    offenders = _is_stale_line_offenders(src)
    assert not offenders, (
        "The is_stale provenance card hardcodes a colour again instead of "
        "using var(--wtf-developing):\n  " + "\n  ".join(offenders)
    )


def test_wtf_wx_card_border_has_no_hardcoded_f59e0b():
    src = WEATHER.read_text(encoding="utf-8")
    assert not _card_rule_hardcodes_f59e0b(src), (
        ".wtf-wx-card border-left still hardcodes #f59e0b instead of "
        "var(--wtf-developing)"
    )


def test_aurora_styling_resolves_from_css_token():
    """Positive-shape check, not just absence: every one of the five aurora
    sites must resolve through var(--wtf-aurora) specifically."""
    src = WEATHER.read_text(encoding="utf-8")
    m = re.search(r"\.wtf-wx-eyebrow\s*\{[^}]*\}", src)
    assert m and "color:var(--wtf-aurora)" in m.group(0), "eyebrow text"

    m = re.search(r"\.wtf-wx-article-card\s*\{[^}]*\}", src)
    assert m and "border-left:3px solid var(--wtf-aurora)" in m.group(0), (
        "article-card border"
    )

    m = re.search(r"\.wtf-wx-aurora-badge\s*\{[^}]*\}", src, re.S)
    assert m and "color:var(--wtf-aurora)" in m.group(0), "aurora badge text"

    footer_links = re.findall(
        r'<a href="/news\?beat=[\w-]+"[^>]*style="color:var\(--wtf-aurora\)', src
    )
    assert len(footer_links) == 2, (
        f"expected both climate-beat footer links to resolve via "
        f"var(--wtf-aurora), found {len(footer_links)}"
    )


def test_is_stale_provenance_card_resolves_from_developing_token():
    """Positive-shape check for fix #2: BOTH the card border and the STALE
    text must resolve through var(--wtf-developing) — the same token this
    file's own JS-driven .wtf-wx-age-stale / .wtf-wx-citycard.is-stale rules
    already use for the identical semantic.

    Was a literal match on the inline-conditional-style string this fix
    landed as (`{% if L.is_stale %}var(--wtf-developing){% else %}...`).
    The #6149 Phase 4 slice 1 refactor (PR #3110) extracted the layer-
    provenance card from inline styles into classes — verified visually
    identical via a stashed-vs-unstashed rendered-text diff — so the
    literal inline string no longer exists. This now pins the class-based
    rule instead, same semantic: is_stale -> var(--wtf-developing), both
    for the card border and for the STALE label text.
    """
    src = WEATHER.read_text(encoding="utf-8")
    assert (
        ".wtf-wx-layercard.is-stale { border-color:var(--wtf-developing); }"
        in src
    ), "is_stale provenance-card border does not resolve via var(--wtf-developing)"
    assert (
        ".wtf-wx-layercard-stale-flag { color:var(--wtf-developing); }"
        in src
    ), "STALE label text does not resolve via var(--wtf-developing)"
    assert 'class="wtf-wx-layercard-stale-flag">⚠ STALE' in src, (
        "STALE label markup no longer uses the stale-flag class"
    )


def test_wtf_wx_card_border_resolves_from_developing_token():
    src = WEATHER.read_text(encoding="utf-8")
    m = re.search(r"\.wtf-wx-card\s*\{[^}]*\}", src, re.S)
    assert m and "border-left:3px solid var(--wtf-developing)" in m.group(0)


def test_fire_and_temp_ramps_are_untouched():
    """Forward guard for the boundary of this fix, not a detector of it: the
    two out-of-scope colour ramps must still hold their OWN, unrelated,
    coincidentally-matching hex literals. If either regresses to empty this
    fix over-reached into a different, already-filed task (the ramp VALUES),
    which is exactly the mistake the line-scoped detectors above exist to
    avoid making."""
    src = WEATHER.read_text(encoding="utf-8")
    # Arrays of arrays — match up to the statement-terminating "];" rather
    # than the first "]" (which is only an inner sub-array's closer).
    m = re.search(r"var FIRE_STOPS\s*=\s*\[.*?\];", src, re.S)
    assert m and "#7f1d1d" in m.group(0), (
        "FIRE_STOPS should still carry its own #7f1d1d (fire-hotspot-count "
        "ramp, unrelated to is_stale) — this fix must not touch ramp values"
    )
    m = re.search(r"var TEMP_STOPS\s*=\s*\[.*?\];", src, re.S)
    assert m and "#f59e0b" in m.group(0), (
        "TEMP_STOPS should still carry its own #f59e0b (air-temperature "
        "ramp, unrelated to --wtf-developing) — this fix must not touch "
        "ramp values"
    )


def test_local_province_codes_and_centroids_are_gone():
    """Fix #4: the dead-code shadow. weather.html must no longer declare its
    own PROVINCE_CODES / CENTROIDS — it must read the shared component's
    copy, which is the one this same file's provinceTooltip() already uses."""
    src = WEATHER.read_text(encoding="utf-8")
    assert "var PROVINCE_CODES" not in src, (
        "weather.html still locally redeclares PROVINCE_CODES, shadowing "
        "WTFMap.PROVINCE_CODES"
    )
    assert "var CENTROIDS" not in src, (
        "weather.html still locally redeclares CENTROIDS (now unused dead code)"
    )
    # No bare (non-WTFMap-prefixed) use of either identifier should remain —
    # a dangling reference to a deleted local variable would be a real bug,
    # not just untidiness.
    bare_province = re.findall(r"(?<!WTFMap\.)\bPROVINCE_CODES\b", src)
    assert not bare_province, (
        f"found {len(bare_province)} bare PROVINCE_CODES reference(s) not "
        "prefixed with WTFMap. — a dangling reference to the deleted local"
    )
    assert "CENTROIDS" not in src, "CENTROIDS identifier still referenced somewhere"


def test_shared_wtfmap_province_codes_still_used():
    """Confirms the deletion didn't just remove code — provinceTooltip()
    still reads province names via the shared component's copy, exactly as
    before. Matched against the actual usage shape (a `for...in` loop over
    it, then an indexed read) rather than a raw substring count, so this
    test cannot be thrown off by an unrelated mention of the same name in
    an explanatory code comment elsewhere in the file."""
    src = WEATHER.read_text(encoding="utf-8")
    assert re.search(r"for\s*\(var k in WTFMap\.PROVINCE_CODES\)", src), (
        "provinceTooltip()'s WTFMap.PROVINCE_CODES loop is missing"
    )
    assert re.search(r"WTFMap\.PROVINCE_CODES\[k\]\s*===\s*code", src), (
        "provinceTooltip()'s WTFMap.PROVINCE_CODES indexed read is missing"
    )
