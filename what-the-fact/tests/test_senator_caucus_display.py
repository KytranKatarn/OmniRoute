"""Caucus-history stints on /senator/<slug>: consecutive same-caucus quarters collapse; a change after a missing quarter is
flagged rather than pinned to the quarter we first saw it; a missing table hides the section instead of failing the page."""
import re
from datetime import date
from pathlib import Path

import jinja2

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "consumer" / "routes.py").read_text(encoding="utf-8")
TPL = (ROOT / "consumer" / "templates" / "senator.html").read_text(encoding="utf-8")


def _helper(rows=None, boom=False):
    m = re.search(r"^def _senator_caucus_history.*?(?=^@bp\.get\(\"/senator/<slug>\"\))", SRC, re.S | re.M)
    assert m
    ns = {"text": lambda s: s}

    class _R:
        def mappings(self):
            return self

        def all(self):
            return rows

    class _C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_):
            return _R()

    class _E:
        def begin(self):
            if boom:
                raise RuntimeError("no table")
            return _C()
    ns["_db"] = lambda: _E()
    exec(m.group(0), ns)
    return ns["_senator_caucus_history"]


def _r(period, d, label):
    return {"period": period, "q_start": d, "label": label}


def test_consecutive_quarters_collapse_newest_first():
    rows = [_r("2018-Q1", date(2018, 1, 1), "ISG"), _r("2018-Q2", date(2018, 4, 1), "ISG"),
            _r("2018-Q3", date(2018, 7, 1), "CSG")]
    out = _helper(rows)(1)
    assert [s["caucus"] for s in out] == ["CSG", "ISG"]
    assert out[1]["quarters"] == 2 and out[1]["from_period"] == "2018-Q1" and out[1]["to_period"] == "2018-Q2"
    assert out[0]["gap_before"] is False


def test_change_after_missing_quarters_is_flagged():
    rows = [_r("2018-Q1", date(2018, 1, 1), "ISG"), _r("2019-Q3", date(2019, 7, 1), "CSG")]
    out = _helper(rows)(1)
    assert out[0]["caucus"] == "CSG" and out[0]["gap_before"] is True
    assert out[1]["gap_before"] is False  # first stint has no predecessor


def test_return_to_an_earlier_caucus_is_a_new_stint():
    rows = [_r("2018-Q1", date(2018, 1, 1), "ISG"), _r("2018-Q2", date(2018, 4, 1), "PSG"),
            _r("2018-Q3", date(2018, 7, 1), "ISG")]
    assert [s["caucus"] for s in _helper(rows)(1)] == ["ISG", "PSG", "ISG"]


def test_failure_hides_the_section():
    assert _helper(boom=True)(1) == []


def test_template_renders_stints_and_gap_note():
    sec = TPL[TPL.index("{% if senator.caucus_history %}"):TPL.index("{# ── Paywalled detail section")]
    out = jinja2.Environment(autoescape=True).from_string(sec).render(senator={"caucus_history": [
        {"caucus": "CSG", "from_period": "2019-Q3", "to_period": "2019-Q3", "quarters": 1, "gap_before": True},
        {"caucus": "ISG", "from_period": "2018-Q1", "to_period": "2018-Q2", "quarters": 2, "gap_before": False}]})
    assert "2018-Q1 to 2018-Q2" in out and "2 quarters on record" in out and "1 quarter on record" in out
    assert out.count("moved sometime before this") == 1 and "from the third quarter of 2016 only" in out


def test_template_omits_section_when_empty_and_route_wires_it():
    sec = TPL[TPL.index("{% if senator.caucus_history %}"):TPL.index("{# ── Paywalled detail section")]
    assert jinja2.Environment().from_string(sec).render(senator={"caucus_history": []}).strip() == ""
    assert 'senator["caucus_history"] = _senator_caucus_history(senator["id"])' in SRC
