"""Symbol plates on the /weather 'Current weather' map (task 7236): runs the node behavioural harness and pins the page's half of the wiring."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = (ROOT / "consumer" / "templates" / "weather.html").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_plate_harness_passes():
    r = subprocess.run(["node", str(ROOT / "tests" / "test_wtf_map_plates.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_city_points_hand_the_map_a_constant_glyph_and_a_text_label():
    assert "WX_GLYPHS[c.glyph]" in PAGE and 'glyph: g ? { svg: g, label: c.temp + "\\u00b0" } : null' in PAGE


def test_a_city_with_no_reading_stays_a_dot_not_a_blank_plate():
    assert "c.glyph && c.temp !== null" in PAGE


def test_home_city_is_placed_first_and_marked():
    assert "home: !!homeCity && c.name === homeCity" in PAGE and "homeCity && a.name === homeCity ? 0 : 2" in PAGE
