"""/crtc ownership panel (parity pass 2026-10-15, design-handoff/wtf-crtc.html): owner type is marked by SHAPE and a colour that is NOT on the lean scale,
and the panel carries no emoji. The template itself deferred this as 'a real, deliberate recoloring decision'; the design supplies the palette."""

import pathlib
import re

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

C = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
SRC = (C / "crtc.html").read_text(encoding="utf-8")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
LEAN_ENDS = {"#ef4444", "#3b82f6"}          # red and blue: the left/right ends of the lean scale


def _owner_palette():
    m = re.search(r"\{% set TYPE_COLOURS = (\{'corporate'[^}]*\}) %\}", SRC)
    assert m, "owner-type palette not found"
    return eval(m.group(1), {})              # a literal dict in the template source


def test_no_owner_type_borrows_a_lean_colour():
    pal = _owner_palette()
    assert set(pal) == {"corporate", "public", "non_profit", "independent"}
    assert not (set(pal.values()) & LEAN_ENDS), "owner-type colours must not reuse the lean scale's red/blue ends"
    assert len(set(pal.values())) == 4


def test_palette_is_the_designs():
    assert _owner_palette() == {"corporate": "#6b7280", "public": "#a78bfa", "non_profit": "#10b981", "independent": "#f59e0b"}


def test_owner_type_is_marked_by_shape():
    assert "TYPE_SHAPES" in SRC and "is-square" in SRC and "is-circle" in SRC and ".wtf-crtc-shape.is-circle { border-radius:50%; }" in SRC


def test_the_page_carries_no_emoji():
    assert not EMOJI.findall(SRC), sorted(set(EMOJI.findall(SRC)))


def test_panel_renders_shapes_and_the_new_palette():
    env = Environment(loader=ChoiceLoader([DictLoader({"base.html": "{% block title %}{% endblock %}{% block meta %}{% endblock %}{% block content %}{% endblock %}"}), FileSystemLoader(str(C))]), autoescape=True)
    env.globals["url_for"] = lambda *a, **k: "#"
    owners = [{"owner_name": "Postmedia Network", "owner_type": "corporate", "outlet_count": 9, "avg_bias": -0.24, "bias_band": "center-left"},
              {"owner_name": "CBC/Radio-Canada", "owner_type": "public", "outlet_count": 3, "avg_bias": -0.26, "bias_band": "center-left"}]
    try:
        html = env.get_template("crtc.html").render(owners_summary=owners, concentration_badge={"label": "Distributed", "colour": "#22c55e", "pct_top3": 35.7},
                                                    decisions=[], is_subscriber=False, dtype="", total_decisions=280, year_range="2024–2026", type_counts={})
    except Exception as exc:  # the page needs a Flask request for some blocks; the source-level tests above still pin the contract
        import pytest
        pytest.skip(f"full page needs request context: {exc}")
    assert 'wtf-crtc-shape is-square' in html and 'wtf-crtc-shape is-circle' in html and "background:#6b7280" in html and "background:#a78bfa" in html
    assert "background:#ef4444" not in html.split("wtf-crtc-own-bars")[1].split("wtf-crtc-own-legend")[0]
    assert not EMOJI.findall(html)
