"""Homepage map: on-map province code + story count, outlines in the region colour
(design wtf-home). Source pins — the behaviour is exercised by
tests/js/map_labels_smoke.js (node, fake DOM)."""
import pathlib

C = pathlib.Path(__file__).resolve().parents[1] / "consumer"
MAP = (C / "static/js/wtf-map.js").read_text(encoding="utf-8")
HOME = (C / "templates/index.html").read_text(encoding="utf-8")


def test_labels_are_opt_in_canada_only_and_never_pointer_blocking():
    assert "function drawLabels(def)" in MAP
    # Must be a TYPE check, not truthiness: `label` is overloaded. weather.html
    # passes a display-name string ({ id:"fire", label:"Fire activity" }), which is
    # truthy, so a `!def.label` guard let it through and drawLabels then called it —
    # "TypeError: def.label is not a function" out of restyle/onResize.
    assert 'scope !== "canada"' in MAP and 'typeof def.label !== "function"' in MAP
    assert "!def.label" not in MAP, "truthiness guard reintroduced — string labels will throw"
    assert '"pointer-events": "none"' in MAP  # labels must not eat province clicks


def test_small_provinces_are_skipped_not_crowded():
    assert "area > 240" in MAP and "area > 760" in MAP


def test_layers_without_the_options_render_as_before():
    assert 'stroke: isSel ? "#e6edf6" : (outlined ? m.col : "#0b1220")' in MAP
    assert "0.92" in MAP  # default fill opacity unchanged


def test_homepage_opts_both_layers_in_and_unmeasured_gets_no_number():
    assert HOME.count("outline: true, fillOpacity: 0.4, label: mapLabel") == 2
    assert "return c ? c.toLocaleString() : null;" in HOME  # never prints 0 for no data
