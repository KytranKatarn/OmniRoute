"""The "Cost to taxpayers" panel puts the current partial year IN THE ROW with the full years.

2026-10-06: the MP and senator profiles drew 2021-2025 as bars but showed 2026 only in a dashed box
underneath ("2026 so far"), because a partial year must never inflate the 5-year total. The owner wanted it
next to the other years. The chart now gets a 2026* bar — dimmed + dashed + labelled "so far", with a legend
line saying it is partial — while the 5-year total, and the "latest year breakdown", still use complete
years only.

cost.js is a browser IIFE, so this runs the REAL file under node against a minimal fake DOM and the real API
shape (/api/cost/mp/87 and /api/cost/senator/2, 2026-10-06).
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
const document = {
  readyState: 'complete',
  createElement: t => new Node(t),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
const window = { document, fetch: undefined };
global.document = document;
global.window = window;
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(api) });
new Function('window', fs.readFileSync(process.argv[2], 'utf8'))(window);

const container = new Node('div');
container.attrs = { 'data-kind': 'mp', 'data-id': '87' };
window.WTFCost.renderMember(container);
setTimeout(() => {
  const all = [];
  (function walk(n) { all.push(n); n.children.forEach(walk); })(container);
  const texts = all.map(n => n.textContent).filter(Boolean);
  const dimmed = all.filter(n => n.style.opacity === '0.55');
  const dashed = all.filter(n => (n.style.outline || '').indexOf('dashed') >= 0);
  console.log(JSON.stringify({ texts, dimmed: dimmed.length, dashed: dashed.length }));
}, 50);
"""


def _render(api):
    out = subprocess.run(["node", "-e", HARNESS, json.dumps(api), COST_JS], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _year(y, total):
    return {"year": y, "indemnity": 0, "top_up": 0, "office_total": total, "total": total, "served": True,
            "office": {"travel": 1, "hospitality": 1, "contracts": 0, "salaries": 1}}


MP = {
    "_note": "approximate", "_source": "src", "five_year_total": 3421274,
    "years": [_year(2021, 573830), _year(2022, 584023), _year(2023, 746604), _year(2024, 780058), _year(2025, 736759)],
    "current": {"year": 2026, "quarters": 2, "total": 312003, "indemnity": 0, "top_up": 0,
                "office_total": 312003, "projected_full_year": 624006},
}


def test_current_year_is_a_bar_in_the_row_marked_partial():
    r = _render(MP)
    assert "2026*" in r["texts"]
    assert "2 quarters so far" in r["texts"]
    assert "$312k" in r["texts"]                       # the YTD value is on the bar
    assert [t for t in r["texts"] if "partial, not in the 5-year total" in t]   # legend says so
    for y in ("2021", "2022", "2023", "2024", "2025"):  # the full years are still there
        assert y in r["texts"]


def test_the_partial_bar_is_visibly_different_and_only_it():
    r = _render(MP)
    assert r["dimmed"] == 1 and r["dashed"] == 1


def test_five_year_total_still_excludes_the_partial_year():
    r = _render(MP)
    assert any("$3,421,274" in t for t in r["texts"])
    assert not any("$3,733,277" in t for t in r["texts"])   # 3,421,274 + 312,003 would mean it leaked in


def test_the_dashed_box_with_the_projection_is_kept():
    r = _render(MP)
    assert "2026 so far" in r["texts"]
    assert any("projected full year" in t for t in r["texts"])


def test_no_current_year_means_no_partial_bar():
    api = dict(MP)
    api.pop("current")
    r = _render(api)
    assert not any(t.endswith("*") and t[:4].isdigit() for t in r["texts"])
    assert r["dimmed"] == 0 and r["dashed"] == 0
    assert not any("partial, not in the 5-year total" in t for t in r["texts"])


def test_a_zero_current_year_is_not_drawn():
    api = dict(MP, current=dict(MP["current"], total=0, office_total=0))
    r = _render(api)
    assert "2026*" not in r["texts"]


def test_senator_shape_works_too():
    sen = {"_note": "n", "_source": "s", "five_year_total": 554255,
           "years": [_year(2024, 268294), _year(2025, 285961)],
           "current": {"year": 2026, "quarters": 2, "total": 78329, "indemnity": 0, "top_up": 0,
                       "office_total": 78329, "projected_full_year": 156658}}
    r = _render(sen)
    assert "2026*" in r["texts"] and "2025" in r["texts"] and r["dimmed"] == 1
