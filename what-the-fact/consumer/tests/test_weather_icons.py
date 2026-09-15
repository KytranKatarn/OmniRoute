"""/weather must render stroked SVG icons, never emoji.

WHY THIS TEST EXISTS
--------------------
The #3162/#3163 sweep converted emoji to stroked SVG across 11 templates —
`map.html` among them — and **skipped `weather.html`**. Nothing failed, because
nothing pinned the rule; both PRs reported success for the files they did touch.
Sixteen emoji then sat live on /weather for weeks: the alert/evacuation glyphs
(⚠️🚨🔴🟡) and, more visibly, the scope and layer buttons (🍁🔥🌡🌤🌫) plus
🔗🌱🔬📰📊 and the JS-rendered 💨💧🔥⚠.

A scan that greps a GUESSED emoji list is how the layer buttons were missed on the
first pass here too — the guess covered weather glyphs and not 🍁/🔗/📊. So this
test scans by UNICODE RANGE over every consumer template, not by a list.
"""

import pathlib
import re

import pytest

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"

# Pictographs + dingbats + misc symbols. Deliberately broad: the failure mode this
# guards is "the glyph wasn't in my list", so the list must not be the mechanism.
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿]")
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)

# Variation selector / ZWJ carry no glyph of their own.
IGNORE = {"️", "‍"}


def _rendered_text(path: pathlib.Path) -> str:
    """Template body with Jinja comments stripped — those never reach a browser."""
    return JINJA_COMMENT.sub("", path.read_text(encoding="utf-8"))


def _emoji_hits(path: pathlib.Path):
    hits = []
    for lineno, line in enumerate(_rendered_text(path).splitlines(), 1):
        found = [c for c in EMOJI.findall(line) if c not in IGNORE]
        if found:
            hits.append((lineno, "".join(found), line.strip()[:100]))
    return hits


def test_weather_template_has_no_rendered_emoji():
    hits = _emoji_hits(TEMPLATES / "weather.html")
    assert not hits, "emoji found in weather.html (use the wx_icon/alert_icon macros):\n" + "\n".join(
        f"  L{ln} {chars}  {txt}" for ln, chars, txt in hits
    )


def test_weather_uses_the_shared_icon_macros():
    """Non-vacuity: the file must actually CALL the macros.

    Without this, deleting every icon would pass the no-emoji test above.
    """
    src = (TEMPLATES / "weather.html").read_text(encoding="utf-8")
    assert "_archetypes.html" in src and "wx_icon" in src, "weather.html must import the icon macros"
    assert src.count("wx_icon(") >= 10, "expected the scope/layer/link/beat/cluster/accuracy/stale icons"
    for macro in ("alert_icon", "evac_icon", "evac_status_icon"):
        assert macro + "(" in src, f"{macro} should render the alert/evacuation glyphs"


def test_js_icon_table_is_defined_where_macros_cannot_reach():
    """The JS-rendered chips can't call a Jinja macro, so they use the WXI table.

    If someone deletes WXI but leaves the call sites, the chips render `undefined`
    — which looks like a data bug, not an icon bug.
    """
    src = (TEMPLATES / "weather.html").read_text(encoding="utf-8")
    assert "var WXI = {" in src, "WXI inline-SVG table must exist for the JS chips"
    for key in ("wind", "droplet", "fire", "warn"):
        assert f"{key}:" in src, f"WXI.{key} is referenced by the JS chips"


# ─── RATCHET ────────────────────────────────────────────────────────────────
# Measured 2026-09-14: 26 of the consumer templates still carry emoji. That is a
# real backlog, NOT something this PR invented and NOT something it fixes — the
# task here was /weather. Rather than narrow the sweep to weather.html (which
# would hide the finding) or fail the suite red on pre-existing debt, the list is
# recorded and ratcheted:
#
#   * a template NOT on this list must stay clean          → catches regressions
#   * a template ON this list that has become clean must be REMOVED from it
#                                                          → keeps the list honest
#
# So the list can only shrink, and it cannot rot into a stale allowlist that
# silently excuses new drift. Burn it down a page at a time; delete the constant
# when it is empty.
KNOWN_EMOJI_TEMPLATES = {
    "account.html", "activity.html", "alerts.html", "article.html", "base.html",
    "beat_landing.html", "cluster.html", "connect.html", "cost.html",
    "cross_watch.html", "crtc.html", "dedup_review.html", "economy.html",
    "entity.html", "ethics.html", "journalist.html",
    "literacy_score.html", "lobbying.html", "markets.html", "mp.html", "mps.html",
    "municipal.html", "news.html", "senator.html", "team.html",
}


@pytest.mark.parametrize(
    "template",
    sorted(p.name for p in TEMPLATES.glob("*.html")),
)
def test_no_template_regresses_to_emoji(template):
    """Whole-directory sweep, so the NEXT page to drift fails here first.

    weather.html and map.html were each covered by one cleanup batch and missed by
    the other; a per-file test would have caught neither.
    """
    if template in KNOWN_EMOJI_TEMPLATES:
        pytest.skip(f"{template} is on the known-emoji backlog (see KNOWN_EMOJI_TEMPLATES)")
    hits = _emoji_hits(TEMPLATES / template)
    assert not hits, f"emoji in {template} — use a stroked SVG macro:\n" + "\n".join(
        f"  L{ln} {chars}  {txt}" for ln, chars, txt in hits
    )


def test_the_backlog_list_does_not_go_stale():
    """A cleaned template must be REMOVED from the backlog, and the list must be real.

    Without this the ratchet rots into a permanent allowlist: someone cleans a page,
    the entry stays, and that page silently stops being guarded forever after.
    """
    present = {p.name for p in TEMPLATES.glob("*.html")}
    ghosts = KNOWN_EMOJI_TEMPLATES - present
    assert not ghosts, f"backlog names templates that no longer exist — drop them: {sorted(ghosts)}"

    cleaned = sorted(t for t in KNOWN_EMOJI_TEMPLATES if not _emoji_hits(TEMPLATES / t))
    assert not cleaned, (
        "these templates are now emoji-free — remove them from KNOWN_EMOJI_TEMPLATES "
        f"so they stay guarded: {cleaned}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ONE icon registry (#6763 follow-up — the design-handoff alignment pass)
# ─────────────────────────────────────────────────────────────────────────────


def _env():
    from jinja2 import Environment, FileSystemLoader

    return Environment(loader=FileSystemLoader(str(TEMPLATES)))


def test_there_is_exactly_one_icon_registry():
    """base.html must not keep a private copy of the paths.

    It used to hold its own `_p` dict for the nav. The two registries had already
    converged on a byte-identical 'news' glyph independently — which is precisely
    how the third copy gets added and the set starts to drift.
    """
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "_ICON_PATHS" not in base, "the registry lives in _archetypes.html, not base.html"
    assert "set _p = {" not in base, "base.html must not reintroduce a private icon dict"
    assert "_archetypes.html" in base, "base.html must import the shared registry"

    arch = (TEMPLATES / "_archetypes.html").read_text(encoding="utf-8")
    assert arch.count("set _ICON_PATHS = {") == 1, "exactly one registry"
    assert "set _WX_PATHS" not in arch, "_WX_PATHS was renamed — no stale second dict"


def test_icon_macro_renders_stroked_svg_and_fails_visibly():
    m = _env().get_template("_archetypes.html").module
    for name in ("pin", "maple", "globe", "eye", "close", "news", "politics",
                 "money", "media", "data", "about", "check", "bolt", "warn"):
        out = str(m.icon(name, 12))
        assert "<svg" in out, name
        # stroke, never fill: an icon inherits its context's colour and cannot
        # assert a status of its own (the lean/verdict colour rule, ADR-023).
        assert 'stroke="currentColor"' in out and 'fill="none"' in out, name
        assert 'aria-hidden="true"' in out, f"{name} must not be announced — the text label is"

    # an unknown name must render something VISIBLE; rendering nothing hides the typo
    assert "<svg" in str(m.icon("no-such-icon")), "unknown name vanished instead of falling back"


def test_wx_icon_is_an_alias_not_a_second_implementation():
    """weather.html (#3336) keeps working, and cannot drift from the shared set."""
    m = _env().get_template("_archetypes.html").module
    for name in ("fire", "thermo", "wind", "droplet", "warn"):
        assert str(m.wx_icon(name, 14)) == str(m.icon(name, 14)), name


def test_province_button_icon_survives_the_js_label_update():
    """The homepage's province button sets its label from JS.

    Assigning .textContent to the BUTTON would delete the svg sitting next to it —
    the icon would be correct on first paint and vanish on first interaction. The
    handlers must write a dedicated label span instead, and must keep using
    textContent (not innerHTML) so the province value stays escaped.
    """
    src = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert 'id="wtf-province-btn-label"' in src, "the button needs a separate label span"
    # Match the ASSIGNMENT, not the words: an earlier draft of this test matched
    # the phrase "btn.textContent" and so failed on the comment explaining the rule.
    assert not re.search(r"\bbtn\.textContent\s*=", src), (
        "assigning textContent to the button itself deletes the icon beside it"
    )
    assert "btnLabel.innerHTML" not in src and "btnLabel2.innerHTML" not in src, (
        "the province code is data — it must go through textContent, not innerHTML"
    )


_ICO_KEYS = ("news", "parliament", "check", "bolt", "warn")


def _ico_block() -> str:
    """The `var ICO = {...};` literal as it appears in index.html, braces included."""
    src = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert "var ICO = {" in src, "JS-side icon table missing"
    start = src.index("var ICO = {")
    return src[start : src.index("\n};", start) + 3]


def test_homepage_js_icon_table_is_sourced_from_the_macro_not_copied():
    """The chips are built as HTML strings — but that does NOT require copied geometry.

    A Jinja macro CAN be called from inside a JS string via `|tojson`, which emits an
    escaped JS string literal. An earlier revision hardcoded five full <svg> blobs here
    and they had ALREADY drifted from the macro (the copies were missing
    `focusable="false"`). This test fails if anyone re-inlines the geometry.
    """
    block = _ico_block()
    assert "icon(" in block, "ICO table must CALL the icon() macro, not restate it"
    assert "tojson" in block, "macro output must be escaped into JS with |tojson"
    for marker in ("<svg", "<path", "viewBox"):
        assert marker not in block, (
            f"raw {marker!r} in the ICO table — geometry belongs in _ICON_PATHS only, "
            "otherwise the homepage chip and its design-system icon can drift apart"
        )
    for key in _ICO_KEYS:
        assert key in block, f"ICO.{key} missing"

    src = (TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert "ICO.news" in src and "ICO.parliament" in src, "table defined but never used"


def test_homepage_js_icon_table_renders_to_the_macro_geometry():
    """Render it for real: every key must produce the macro's own paths.

    A source-text test alone would pass on a table that renders to nothing (a typo'd
    key silently yields the `warn` fallback, or an empty string).
    """
    import json
    import re

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    rendered = env.from_string(
        '{% from "_archetypes.html" import icon %}' + _ico_block()
    ).render()

    body = rendered.strip()[len("var ICO =") :].rstrip(";").strip()
    body = re.sub(r"^\s*(\w+):", lambda m: '"%s":' % m.group(1), body, flags=re.M)
    table = json.loads(body)  # also proves it is a VALID JS string literal

    assert sorted(table) == sorted(_ICO_KEYS)
    macros = (TEMPLATES / "_archetypes.html").read_text(encoding="utf-8")
    for key, markup in table.items():
        paths = re.findall(r"<path[^>]*>", markup)
        assert paths, f"ICO.{key} rendered with no <path> — macro lookup failed"
        for path in paths:
            assert path in macros, f"ICO.{key} path not found in _ICON_PATHS: {path}"
