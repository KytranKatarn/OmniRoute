"""/clusters 'How a cluster is built' must describe what ingest/cluster.py ACTUALLY does.
The Claude Design copy claimed the opposite (entities/dates/figures, not headlines; 72h),
so this pins the page to the code's own defaults. Run: python3 tests/test_clusters_method_copy.py"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE = (ROOT / "ingest" / "cluster.py").read_text(encoding="utf-8")


def _render():
    from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
    env = Environment(autoescape=True, loader=ChoiceLoader([
        DictLoader({"base.html": "{% block meta %}{% endblock %}{% block content %}{% endblock %}"}),
        FileSystemLoader(str(ROOT / "consumer" / "templates"))]))
    return env.get_template("clusters.html").render(
        clusters=[], totals=dict(qualifying=0, with_spread=0, widest=0, blindspot_seeds=0),
        f=dict(days=7, sort="spread", q="", beat="all", size="all", median="all"), days=7,
        windows=[7], beats=[], sizes={}, medians=[], shown=0, url_windows=[], url_sorts=[],
        url_clear="/clusters")


def test_panel_says_headlines_and_never_the_designs_false_claim():
    h = _render()
    assert "How a cluster is built" in h and "<strong>headlines</strong>" in h and "Jaccard" in h
    assert "not from headline similarity" not in h and "72-hour" not in h and "72 hours" not in h
    assert "It does not read entities, dates or quoted" in h


def test_panel_numbers_match_the_ingest_defaults():
    thr = re.search(r'WTF_CLUSTER_THRESHOLD", "([0-9.]+)"', CODE).group(1)
    hrs = re.search(r'WTF_CLUSTER_WINDOW_HOURS", "(\d+)"', CODE).group(1)
    h = _render()
    assert f"by default {thr}" in h or f"(by default {thr})" in h
    assert f"last {hrs} hours" in h


def test_failure_modes_are_disclosed_and_eyebrow_names_the_agent():
    h = _render()
    assert "split across two clusters" in h and "merged into one" in h
    assert "I.N.K. &middot; one event" in h or "I.N.K. · one event" in h


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
