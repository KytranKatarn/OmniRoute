"""ranked_bars(): every row must share one set of columns.

Each .wtf-a-ranked-row was its own grid, so its `auto` value column was sized to ITS OWN text: the bar's
left edge and width drifted row to row (616/620/625/629px on /parties, 711-724px on /team) and bars could
not be compared by eye. Subgrid gives all rows the parent's columns. On a phone the 187px value column left
the track 37-58px wide, so <=520px the value sits beside the label and the bar goes full width beneath.

Source-level guards; the rendered before/after (one track edge per page at 1280/768/400) was measured in
Chrome, which is the only place this defect is visible.
"""
import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1] / "consumer" / "static" / "style.css").read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", "", CSS)


def test_rows_share_the_parents_columns_via_subgrid():
    assert "@supports(grid-template-columns:subgrid){.wtf-a-ranked{display:grid;" in FLAT
    assert ".wtf-a-ranked-row{grid-template-columns:subgrid;grid-column:1/-1;}" in FLAT


def test_browsers_without_subgrid_keep_the_per_row_layout():
    # the base rules must remain outside @supports, or an old browser would lose the layout entirely
    base = re.search(r"\.wtf-a-ranked-row\s*\{([^}]*)\}", CSS).group(1).replace(" ", "")
    assert "display:grid" in base and "grid-template-columns:minmax(120px,1.4fr)1frauto" in base.replace(" ", "")


def test_phones_stack_the_bar_under_the_label_and_value():
    assert "@media(max-width:520px){.wtf-a-ranked-row{grid-template-columns:1frauto;" in FLAT
    assert ".wtf-a-ranked-row>.wtf-a-bar-track{grid-column:1/-1;order:3;}" in FLAT
    # and the subgrid variant of the same breakpoint, or the shared columns would still be 3-wide
    assert "@media(max-width:520px){.wtf-a-ranked{grid-template-columns:1frauto;}" in FLAT
