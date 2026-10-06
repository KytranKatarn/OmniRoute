"""The national /cost chart puts the current partial year IN THE ROW with the full years.

2026-10-06: the MP and senator profiles already drew "2026*" as a dimmed, dashed bar; the national page showed
2026 only as a text addendum under the headline, so a visitor looking at the chart saw 2021-2025 and no 2026.
The chart now gets the same starred bar, built from the summary's `latest_ytd` addendum — and the headline total
still counts complete years only.

cost.js is a browser IIFE, so this runs the REAL file under node against a minimal fake DOM and the real
/api/cost/summary shape (fetched from the live endpoint 2026-10-06).
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
COST_JS = os.path.join(ROOT, "consumer", "static", "js", "cost.js")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

HARNESS = r"""
const fs = require('fs');
const api = JSON.parse(process.argv[1]);
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.textContent = ''; this.attrs = {}; this.className = ''; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); return c; }
  get firstChild() { return this.children[0] || null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; }
  querySelector() { return null; }
}
const document = { readyState: 'complete', createElement: t => new Node(t), querySelector: () => null,
                   querySelectorAll: () => [], addEventListener: () => {} };
const window = { document, fetch: undefined };
global.document = document; global.window = window;
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(api) });
new Function('window', fs.readFileSync(process.argv[2], 'utf8'))(window);

const parts = { '[data-cost-headline]': new Node('div'), '[data-cost-stats]': new Node('div'),
                '[data-cost-chart]': new Node('div'), '[data-cost-footer]': new Node('div'),
                '[data-cost-addenda]': new Node('div') };
const root = new Node('div');
root.querySelector = sel => parts[sel] || null;
window.WTFCost.renderSummary(root);
setTimeout(() => {
  const walk = (n, out) => { out.push(n); n.children.forEach(c => walk(c, out)); return out; };
  const chart = walk(parts['[data-cost-chart]'], []);
  const head = walk(parts['[data-cost-headline]'], []);
  const add = walk(parts['[data-cost-addenda]'], []);
  console.log(JSON.stringify({
    chartTexts: chart.map(n => n.textContent).filter(Boolean),
    headTexts: head.map(n => n.textContent).filter(Boolean),
    addTexts: add.map(n => n.textContent).filter(Boolean),
    dimmed: chart.filter(n => n.style.opacity === '0.55').length,
    dashed: chart.filter(n => (n.style.outline || '').indexOf('dashed') >= 0).length,
  }));
}, 50);
"""


def _render(api):
    out = subprocess.run(["node", "-e", HARNESS, json.dumps(api), COST_JS], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _y(year, total=100_000_000):
    return {"year": year, "mp_count": 300, "mp_office_total": total // 2, "mp_indemnity_total": total // 4,
            "senator_count": 90, "senator_total": total // 4, "total": total, "ministerial_total": 1_000_000,
            "avg_per_mp": total // 300}


def _ytd(year=2026, quarters=("Q1", "Q4"), parl=113_000_000):
    return {"year": year, "kind": "latest_ytd", "quarters": list(quarters), "mp": parl - 4_000_000,
            "mp_office": parl - 40_000_000, "mp_indemnity": 36_000_000, "senator": 4_000_000,
            "parliamentary": parl, "ministerial": 1_700_000, "combined": parl + 1_700_000,
            "mp_count": 341, "senator_count": 93, "projected": None}


API = {
    "_note": "approximate", "_source": {}, "window": {"label": "5 complete fiscal years (2021–2025)", "years": [2021, 2022, 2023, 2024, 2025]},
    "by_year": [_y(y) for y in (2021, 2022, 2023, 2024, 2025)],
    "grand_total_5yr": 500_000_000, "ministerial_grand_5yr": 5_000_000, "combined_grand_5yr": 505_000_000,
    "addenda": [{"year": 2020, "kind": "partial_pre_window", "quarters": ["Q2", "Q3"], "mp": 1, "senator": 0,
                 "mp_office": 1, "mp_indemnity": 0, "parliamentary": 1, "ministerial": 0, "combined": 1,
                 "mp_count": 1, "senator_count": 0, "projected": None}, _ytd()],
}


def test_the_current_year_is_a_starred_bar_in_the_row():
    r = _render(API)
    assert "2026*" in r["chartTexts"]
    assert "2 quarters so far" in r["chartTexts"]
    for y in ("2021", "2022", "2023", "2024", "2025"):
        assert y in r["chartTexts"]


def test_only_that_bar_is_dimmed_and_dashed_and_the_legend_says_why():
    r = _render(API)
    assert r["dimmed"] == 1 and r["dashed"] == 1
    assert any("2026 year to date" in t and "not in the total above" in t for t in r["chartTexts"])


def test_an_older_partial_year_is_not_drawn_as_a_bar():
    """2020 (pre-window, 2 quarters) stays an addendum line; only the CURRENT year goes in the row."""
    assert "2020*" not in _render(API)["chartTexts"]


def test_the_headline_total_does_not_include_the_partial_year():
    r = _render(API)
    assert any("$500,000,000" in t for t in r["headTexts"])
    assert not any("$613,000,000" in t for t in r["headTexts"])      # 500M + 113M would mean it leaked in


def test_no_current_year_means_no_extra_bar_and_no_legend_line():
    api = dict(API, addenda=[a for a in API["addenda"] if a["kind"] != "latest_ytd"])
    r = _render(api)
    assert not any(t.endswith("*") and t[:4].isdigit() for t in r["chartTexts"])
    assert r["dimmed"] == 0 and r["dashed"] == 0


def test_a_zero_current_year_is_not_drawn():
    api = dict(API, addenda=[_ytd(parl=0)])
    assert "2026*" not in _render(api)["chartTexts"]


def test_after_the_2027_roll_the_row_is_2022_to_2026_plus_a_2027_star():
    api = dict(API, window={"label": "5 complete fiscal years (2022–2026)", "years": [2022, 2023, 2024, 2025, 2026]},
               by_year=[_y(y) for y in (2022, 2023, 2024, 2025, 2026)], addenda=[_ytd(year=2027, quarters=("Q4",))])
    r = _render(api)
    assert "2021" not in r["chartTexts"] and "2026" in r["chartTexts"] and "2027*" in r["chartTexts"]
    assert "1 quarter so far" in r["chartTexts"]


# ------------------------------------------------------------------ projection + track record (the addenda block)

PROJ = {"mp": 290_000_000, "senator": 27_000_000, "parliamentary": 317_000_000, "ministerial": 2_300_000,
        "combined": 319_300_000, "low": 300_000_000, "high": 380_000_000, "combined_low": 302_000_000,
        "combined_high": 383_000_000, "from_quarters": 2, "method": "seasonal", "share": 0.509, "n_prior": 5}
TRACK = {
    "typical_error_pct": {"2": 11.2, "3": 5.0},
    "backtest": [
        {"year": 2024, "stage_quarters": 2, "projected": 131_868_037, "actual": 130_568_215, "error_pct": 1.0},
        {"year": 2024, "stage_quarters": 3, "projected": 129_412_173, "actual": 130_568_215, "error_pct": -0.9},
        {"year": 2025, "stage_quarters": 2, "projected": 123_126_229, "actual": 156_567_838, "error_pct": -21.4},
    ],
    "snapshots": [],
}


def _with(proj=PROJ, track=TRACK):
    ytd = dict(_ytd(), projected=proj)
    return dict(API, addenda=[a for a in API["addenda"] if a["kind"] != "latest_ytd"] + [ytd],
                projection_track_record=track)


def test_the_projection_shows_its_range_its_method_and_how_often_it_has_missed():
    t = _render(_with())["addTexts"]
    assert any("projected full year ≈ $319,300,000" in x and "range $302.0M–$383.0M" in x for x in t)
    assert any("same 2 quarters' share of the year in each of the last 5 complete years (median 51%)" in x for x in t)
    assert any("Revised each time a new quarter is released" in x for x in t)
    assert any("typically off by about ±11.2% at this stage" in x for x in t)


def test_the_track_record_lists_what_the_method_would_have_said_and_how_wrong_it_was():
    t = _render(_with())["addTexts"]
    assert "How these projections have performed" in t
    assert any(x.startswith("2024: after 2 quarters ≈ $131.9M (+1.0%) · after 3 quarters ≈ $129.4M (-0.9%)") and "actual $130.6M" in x for x in t)
    assert any(x.startswith("2025: after 2 quarters ≈ $123.1M (-21.4%)") for x in t)
    assert any("election" in x for x in t)            # the disrupted-year caveat is stated, not hidden


def test_a_published_projection_is_compared_with_the_actual_once_the_year_is_complete():
    track = dict(TRACK, snapshots=[
        {"year": 2026, "quarters": ["Q1", "Q4"], "as_of": "2026-10-06T14:00:00+00:00", "parliamentary": 317_000_000,
         "combined": 319_300_000, "low": None, "high": None, "method": "seasonal", "actual": 330_000_000, "error_pct": -3.9},
        {"year": 2026, "quarters": ["Q1", "Q2", "Q4"], "as_of": "2026-11-20T14:00:00+00:00", "parliamentary": 325_000_000,
         "combined": 327_000_000, "low": None, "high": None, "method": "seasonal", "actual": 330_000_000, "error_pct": -1.5}])
    t = _render(_with(track=track))["addTexts"]
    line = [x for x in t if x.startswith("2026 — ")][0]
    assert "after 2 quarters (2026-10-06): ≈ $317.0M (-3.9% vs actual $330.0M)" in line
    assert "after 3 quarters (2026-11-20): ≈ $325.0M (-1.5% vs actual $330.0M)" in line


def test_a_live_year_snapshot_shows_the_projection_on_record_without_an_error():
    track = dict(TRACK, snapshots=[{"year": 2026, "quarters": ["Q1", "Q4"], "as_of": "2026-10-06T14:00:00+00:00",
                                    "parliamentary": 317_000_000, "combined": 319_300_000, "low": None, "high": None, "method": "seasonal"}])
    line = [x for x in _render(_with(track=track))["addTexts"] if x.startswith("2026 — ")][0]
    assert "after 2 quarters (2026-10-06): ≈ $317.0M" in line and "vs actual" not in line


def test_without_history_the_page_still_renders_and_says_when_a_projection_will_appear():
    r = _render(dict(API, projection_track_record={"backtest": [], "snapshots": [], "typical_error_pct": {}}))
    assert not any("How these projections have performed" in x for x in r["addTexts"])
    assert any("a full-year projection appears here once ≥2 quarters are disclosed" in x for x in r["addTexts"])


def test_an_annualized_fallback_says_so_instead_of_claiming_a_seasonal_basis():
    p = dict(PROJ, method="annualized", combined_low=None, combined_high=None)
    t = _render(_with(proj=p))["addTexts"]
    assert any("Annualized from 2 quarters (not enough history yet for a seasonal estimate)" in x for x in t)
    assert not any("range $" in x for x in t)
