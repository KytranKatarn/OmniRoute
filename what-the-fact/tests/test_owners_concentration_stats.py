"""Regression coverage for /owners' concentration stat tiles (2026-09-04,
KB vault_note #304357).

Computed entirely from the already-fetched owners[] in the template — no
route change, same pattern the existing TYPE-breakdown tiles already use.
Measures CONCENTRATION (how much of the tracked outlet population sits
with one owner), a different question than the type-breakdown tiles.

Deliberately NOT added: a per-owner "articles scored / % of corpus" metric
(routes.py's query has no article-count aggregation) or the interactive
sort control / gradient scale-bar from the mockup — those need real route
or CSS work beyond this batch's scope, and are correctly left as documented
gaps rather than half-built here.
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _render(owners, source_count, unattributed=0):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("owners.html").render(
        owners=owners, source_count=source_count, unattributed=unattributed, is_subscriber=True,
    )


def _outlet(bias_lean):
    return {"name": "x", "slug": "x", "url": None, "bias_lean": bias_lean, "avg_score": None}


_OWNERS = [
    {"owner_name": "Postmedia", "owner_type": "corporate", "outlet_count": 9,
     "avg_bias": 0.3, "sample_lean": "center", "bias_band": "center-right",
     "outlets": [_outlet("center-right")] * 5 + [_outlet("center")] * 4},
    {"owner_name": "Solo Outlet Co", "owner_type": "independent", "outlet_count": 1,
     "avg_bias": None, "sample_lean": None, "bias_band": None,
     "outlets": [_outlet(None)]},
    {"owner_name": "CBC", "owner_type": "public", "outlet_count": 1,
     "avg_bias": -0.1, "sample_lean": "center-left", "bias_band": "center-left",
     "outlets": [_outlet("center-left")]},
]


def test_largest_share_is_computed_against_source_count():
    html = _render(_OWNERS, source_count=46)
    # 9/46 = 19.56% -> rounds to 20
    assert "20%" in html
    assert "Largest share" in html


def test_span_2plus_bands_counts_only_owners_with_a_real_spread():
    html = _render(_OWNERS, source_count=46)
    idx = html.find("Span 2+ bands")
    snippet = html[idx:idx + 200]
    assert ">1<" in snippet, "only Postmedia (center-right + center) should count"


def test_single_outlet_counts_owners_with_exactly_one_outlet():
    html = _render(_OWNERS, source_count=46)
    idx = html.find("Single-outlet")
    snippet = html[idx:idx + 200]
    assert ">2<" in snippet, "Solo Outlet Co and CBC both have outlet_count=1"


def test_null_bias_lean_outlets_do_not_count_as_a_band():
    # An owner whose only outlet has bias_lean=None must not be counted as
    # "spanning 2+ bands" via a None-vs-something comparison.
    owners = [{"owner_name": "Unscored Co", "owner_type": "independent", "outlet_count": 2,
               "avg_bias": None, "sample_lean": None, "bias_band": None,
               "outlets": [_outlet(None), _outlet(None)]}]
    html = _render(owners, source_count=10)
    idx = html.find("Span 2+ bands")
    snippet = html[idx:idx + 200]
    assert ">0<" in snippet


def test_empty_owners_list_does_not_crash():
    html = _render([], source_count=0)
    assert "Largest share" in html
    assert "0%" in html
