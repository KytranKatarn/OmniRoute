"""/mps stat row + text tab labels (design wtf-mps.html). Run: python3 tests/test_mps_stat_tiles.py"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ps", ROOT / "consumer" / "parliament_stats.py")
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)

MPS = [{"party": "Liberal"}] * 5 + [{"party": "Conservative"}] * 3 + [{"party": "NDP"}] * 1 + [{"party": None}]
SEN = [{"caucus": "ISG"}, {"caucus": "ISG"}, {"caucus": "CSG"}, {"caucus": ""}]


def by(tiles):
    return {t["label"]: t for t in tiles}


def test_tiles_come_from_the_rows_and_never_name_an_office():
    t = by(ps.chamber_tiles(MPS, SEN, 10, filtered=False))
    assert t["House members"]["value"] == "10"
    assert t["Largest party"]["value"] == "5" and "Liberal" in t["Largest party"]["detail"]
    assert t["Second-largest party"]["value"] == "3" and "Conservative" in t["Second-largest party"]["detail"]
    assert t["Senators"]["value"] == "4" and t["Senate groups"]["value"] == "2"  # '' is not a group
    joined = " ".join(x["label"] + x["detail"] for x in t.values())
    assert "Government" not in joined and "Opposition" not in joined


def test_party_tiles_are_omitted_when_a_filter_is_active():
    t = by(ps.chamber_tiles(MPS[:3], SEN, 10, filtered=True))
    assert "Largest party" not in t and "Second-largest party" not in t
    assert "House members" in t and "Senators" in t


def test_nothing_measured_means_no_tile_not_a_zero():
    assert ps.chamber_tiles([], [], 0, filtered=False) == []
    assert "Senators" not in by(ps.chamber_tiles(MPS, [], 10, filtered=False))


def test_tie_breaks_are_deterministic():
    t = by(ps.chamber_tiles([{"party": "B"}, {"party": "A"}], [], 2, filtered=False))
    assert "A" in t["Largest party"]["detail"] and "B" in t["Second-largest party"]["detail"]


def test_template_has_text_tabs_and_wires_the_tiles():
    src = (ROOT / "consumer" / "templates" / "mps.html").read_text(encoding="utf-8")
    assert ">House of Commons</button>" in src and ">Senate</button>" in src and ">Ridings</button>" in src
    for emoji in ("🏛 House", "🔴 Senate", "🗺 Ridings"):
        assert emoji not in src
    assert "{% if stat_tiles_data %}{{ stat_tiles(stat_tiles_data) }}{% endif %}" in src


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
