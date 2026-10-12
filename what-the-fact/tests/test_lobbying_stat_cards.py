"""/lobbying stat cards (PORT-STATUS row 15): the shared stat_tiles() macro, centred like the design's
.stat cards, replacing the page's own small left-aligned chips.

The figures must not change with the markup: same five numbers from the same `stats` row, the Coverage
card still dropped when there are no dates, absent numbers still 0 (as the old template did).
"""
import datetime
import pathlib
import re

import pytest
from jinja2 import Environment, FileSystemLoader

C = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
SRC = (C / "lobbying.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def render_tiles():
    env = Environment(loader=FileSystemLoader(str(C)))
    start = SRC.index("{# Same five figures")
    end = SRC.index("</div>", SRC.index('<div class="wtf-lob-tiles">')) + 6
    tpl = env.from_string('{% from "_archetypes.html" import stat_tiles %}' + SRC[start:end])

    def go(**stats):
        html = tpl.render(stats=stats)
        return re.findall(r'wtf-a-tile-l">([^<]*)</span>\s*<span class="wtf-a-tile-n">([^<]*)<', html)

    return go


D = datetime.date


def test_same_five_figures_from_the_same_row(render_tiles):
    got = render_tiles(contacts=68015, orgs=3619, mps=341, last_30d=0,
                       first_seen=D(2008, 1, 1), last_seen=D(2026, 8, 12))
    assert got == [("Communications", "68,015"), ("Organizations", "3,619"), ("MPs lobbied", "341"),
                   ("Last 30 days", "0"), ("Coverage", "2008–2026")]


def test_coverage_card_is_dropped_without_dates_and_absent_numbers_are_zero(render_tiles):
    got = render_tiles(contacts=None, orgs=None, mps=None, last_30d=None, first_seen=None, last_seen=None)
    assert got == [("Communications", "0"), ("Organizations", "0"), ("MPs lobbied", "0"), ("Last 30 days", "0")]


def test_the_old_chip_markup_and_css_are_gone():
    for dead in ("wtf-lob-stats", "wtf-lob-stat-n", "wtf-lob-stat-n--sm"):
        assert not re.search(r"(?<![\w-])" + dead + r"(?![\w-])", SRC), dead
    # .wtf-lob-stat-l is still used by the monthly caption, so it must survive
    assert "wtf-lob-stat-l" in SRC


def test_cards_are_centred_and_values_cannot_wrap():
    css = SRC.replace(" ", "")
    assert ".wtf-lob-tiles.wtf-a-tile{text-align:center" in css
    assert "white-space:nowrap" in css  # "2008–2026" wrapped to two lines in a ~137px tablet card
    assert "minmax(130px,1fr)" in css  # two across on a phone, not five stacked full-width
