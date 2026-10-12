"""/lobbying sections as the design's cards, with the design's table (PORT-STATUS row 15).

Each `.wtf-lob-section` becomes the design's `.panel`; the table takes the design's mono headers and
10px cells; colours come from the shared --wtf-* tokens (the old block was dark-only hex, so none of
it followed light mode). Source-level guards: the rendered before/after was measured in Chrome.
"""
import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates" / "lobbying.html").read_text(encoding="utf-8")
CSS = SRC[: SRC.index("</style>")]
BODY = SRC[SRC.index("</style>"):]


def rule(sel):
    m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", CSS)
    assert m, "rule not found: " + sel
    return m.group(1).replace("\n", " ")


def test_sections_are_rounded_cards_on_the_card_ground():
    r = rule(".wtf-lob-section")
    assert "border-radius:14px" in r.replace(" ", "")
    assert "var(--wtf-bg-card)" in r and "var(--wtf-border)" in r and "box-shadow" in r


def test_table_headers_and_cells_are_the_designs():
    th, td = rule(".wtf-lob-table th"), rule(".wtf-lob-table td")
    assert "var(--wtf-font-mono)" in th and "8.5px" in th and "letter-spacing:.13em" in th.replace(" ", "")
    assert "padding:10px" in td.replace(" ", "")


def test_no_dark_only_hex_left_in_the_card_and_table_rules():
    # the one intentional hex is the link colour (the org name IS the link to its record)
    block = CSS[CSS.index(".wtf-lob-section {"):CSS.index(".wtf-lob-back")]
    hexes = set(re.findall(r"#[0-9a-fA-F]{3,6}\b", block))
    assert hexes <= {"#60a5fa"}, hexes


def test_every_date_cell_cannot_break_mid_value():
    # "2026-06-/03" wrapped on tablet/phone once the cells got the design's looser padding
    assert "white-space:nowrap" in rule(".wtf-lob-date").replace(" ", "")
    assert BODY.count('class="wtf-lob-date"') == 4  # recent contacts x2, MP last-seen, org last-seen


def test_search_input_uses_a_class_not_inline_dark_hex():
    assert 'class="wtf-lob-search"' in BODY
    assert "background:#060d14" not in BODY
    assert "var(--wtf-bg-card)" in rule(".wtf-lob-search")


def test_phones_get_tighter_cells_and_the_name_column_keeps_room():
    css = CSS.replace(" ", "")
    assert "@media(max-width:640px)" in css and "@media(max-width:420px)" in css
    assert ".wtf-lob-tabletd:first-child{min-width:132px" in css
