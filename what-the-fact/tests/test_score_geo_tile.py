"""Regression coverage for score.html's L.O.C.A.L. geo tile (2026-09-04,
KB vault_note #304357).

/api/v1/score (tech/routes.py) has always fetched and returned `geo` — the
consumer /score template just never read it, so real, already-paid-for
analysis was silently thrown away. Three cases matter, none of which show up
as a failing page load: geo populated, geo present but every field null
(honest fallback, never a guessed location), and geo absent entirely
(the backend call to L.O.C.A.L. failed — must not crash the whole page).
"""

from __future__ import annotations

import pathlib

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

TPL_DIR = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"
_BASE_STUB = "{% block meta %}{% endblock %}{% block content %}{% endblock %}"


def _render(result):
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": _BASE_STUB}),
        FileSystemLoader(str(TPL_DIR)),
    ]))
    return env.get_template("score.html").render(
        subscribed=True, error=None, article_text="x" * 100, source_count=46, result=result,
    )


_BASE_RESULT = {"ok": True, "bias": {"band": "center", "score": 0.1}, "factcheck": {"claims": []}}


def test_populated_geo_renders_the_location():
    html = _render({**_BASE_RESULT, "geo": {
        "city": "Toronto", "province_code": "ON", "country_code": "CA",
        "geo_scope": "municipal", "geo_confidence": 0.9,
    }})
    assert "L.O.C.A.L." in html
    assert "Toronto, ON, CA" in html
    assert "Municipal" in html


def test_all_null_geo_shows_an_honest_fallback_not_a_guess():
    html = _render({**_BASE_RESULT, "geo": {
        "city": None, "province_code": None, "country_code": None,
        "geo_scope": "international", "geo_confidence": 0.2,
    }})
    assert "Location not identified." in html
    # Must not fabricate ANY location string when every field is null.
    assert "None" not in html.split("L.O.C.A.L.")[1].split("</div>")[0]


def test_missing_geo_key_does_not_crash_the_page():
    # The backend call to L.O.C.A.L. can fail independently of bias/factcheck
    # (tech/routes.py's per-task try/except) — `geo` may be absent from the
    # response dict entirely, not just null.
    html = _render(dict(_BASE_RESULT))
    assert "L.O.C.A.L." not in html
    assert "Analyse article" in html  # the page still renders past the result section
