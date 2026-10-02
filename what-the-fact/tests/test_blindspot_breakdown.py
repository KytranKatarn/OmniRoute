"""Blindspot five-tile breakdown. One rule (shared/blindspot_rules.py) must agree with
the ingest's stored call for every count combination. Run: python3 tests/test_blindspot_breakdown.py"""
from __future__ import annotations

import itertools
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

from shared.blindspot_rules import breakdown, classify  # noqa: E402


def _cluster_metrics():
    try:
        import sqlalchemy  # noqa: F401
    except ImportError:
        sys.modules["sqlalchemy"] = types.SimpleNamespace(text=lambda x: x)
    import ingest.cluster_metrics as cm
    return cm


def test_page_rule_agrees_with_the_ingest_for_every_count_combination():
    cm = _cluster_metrics()
    for l, c, r in itertools.product(range(0, 11), range(0, 6), range(0, 11)):
        stored = cm._blindspot_side(l, c, r)
        mine = classify(l, c, r)
        assert (mine if mine in ("L", "R") else None) == stored, (l, c, r, mine, stored)


def test_known_cases():
    assert classify(8, 0, 2) == "R"       # left covered it, right quiet
    assert classify(2, 0, 8) == "L"
    assert classify(5, 0, 4) == "balanced"
    assert classify(1, 1, 1) == "thin"    # under 4 total
    assert classify(0, 6, 1) == "thin"    # plenty of articles, too few partisan ones
    assert classify(0, 0, 0) == "thin"    # unscored cluster is thin, never "balanced"


def test_every_cluster_lands_in_exactly_one_bucket():
    b = breakdown([(8, 0, 2, 3), (2, 0, 8, 2), (5, 0, 4, 7), (1, 1, 1, 11)])
    assert b == {"examined": 23, "called": 5, "left": 2, "right": 3, "balanced": 7, "thin": 11}
    assert b["left"] + b["right"] + b["balanced"] + b["thin"] == b["examined"]


def _render(**kw):
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block meta %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(str(ROOT / "consumer" / "templates"))]))
    return env.get_template("blindspot.html").render(
        blindspots=[], total_in_window=5, days=7, windows=[7, 30], is_subscriber=False, **kw)


def test_five_tiles_when_breakdown_available():
    html = _render(breakdown=breakdown([(8, 0, 2, 3), (5, 0, 4, 7), (1, 1, 1, 11)]))
    for label in ("Blindspots called", "Balanced", "Left-side gaps", "Right-side gaps", "Too thin to call"):
        assert label in html, label


def test_falls_back_to_the_original_tiles_never_to_made_up_zeros():
    html = _render(breakdown=None)
    assert "Blind spots in window" in html and "Too thin to call" not in html


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
