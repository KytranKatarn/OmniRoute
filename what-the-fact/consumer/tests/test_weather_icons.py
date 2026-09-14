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
    "entity.html", "ethics.html", "index.html", "journalist.html",
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
