"""Guards for the homepage MARKUP half of the design (#6149, Phase 2).

Split from the stylesheet guards (tests/test_home_design_css.py) so each half
ships in the PR carrying the lines it guards — a source-asserting test in the
wrong half fails there and teaches the next person to delete it.

These read index.html ONLY. They deliberately do not assert anything about
style.css, so this half is green whichever order the two PRs land in.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "consumer" / "templates" / "index.html"

# The pre-redesign palette. These are not "some old colours" — they are the exact
# values index.html painted its bands with, inline, which is why correcting the
# tokens in :root produced no visible change for two attempts running.
RETIRED_NAVY = ("#050d1a", "#060d14", "#060a10", "#112233", "#0a1520")


@pytest.fixture(scope="module")
def tpl() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _markup_only(tpl: str) -> str:
    """The template minus its <script> bodies.

    Scoped deliberately: one retired hex survives inside the Leaflet label
    builder (`div.style.cssText = "background:#0a1520cc;…"`). That is map
    internals, and the spec's standing constraint is not to restyle the map
    blind — so it is left for the phase that owns the map, not quietly
    recoloured here. test_the_known_navy_residual_does_not_grow pins it.
    """
    return re.sub(r"<script\b.*?</script>", "", tpl, flags=re.S | re.I)


def test_the_homepage_template_carries_no_page_stylesheet(tpl: str):
    """An inline page stylesheet renders after base.html's <link>, so it
    outranks the design system. That is precisely how this page kept the old
    palette while :root already held the right tokens. Same rule the
    /clusters and /archive guards assert for their templates."""
    assert "<style" not in tpl.lower(), "page CSS belongs in static/style.css"


def test_the_homepage_markup_does_not_hardcode_the_retired_navy(tpl: str):
    """Inline styles beat any stylesheet rule, so a single reintroduced hex
    silently un-ships this phase for whichever band it lands on."""
    found = sorted({h for h in RETIRED_NAVY if h in _markup_only(tpl)})
    assert not found, f"retired palette back in index.html markup: {found}"


def test_no_retired_navy_remains_in_the_page_scripts(tpl: str):
    """The one retired hex that used to live in the Leaflet map-label JS went with
    Leaflet (PORT-STATUS row 2, homepage map on wtf-map.js). The residual is now
    zero: any retired navy in a <script> is a new hardcoded colour — fix it."""
    scripts = "".join(re.findall(r"<script\b.*?</script>", tpl, flags=re.S | re.I))
    residual = sorted(h for h in RETIRED_NAVY if h in scripts)
    assert residual == [], f"retired navy back in the page scripts: {residual}"


def test_the_js_display_hook_survives_on_every_toggled_band(tpl: str):
    """The beat banner, province banner and featured strip are shown by JS
    assigning `.style.display` directly. Stripping their inline `display:none`
    while handing painting to CSS would leave all three permanently visible."""
    for el in ("wtf-beat-banner", "wtf-province-banner", "wtf-featured-strip"):
        block = re.search(r'id="' + el + r'"[^>]*>', tpl)
        assert block, f"#{el} is gone from the homepage"
        assert "display:none" in block.group(0), (
            f"#{el} must keep its inline display:none — JS toggles it"
        )
