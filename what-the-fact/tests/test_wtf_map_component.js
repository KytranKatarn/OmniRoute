/* Behavioural tests for the shared map component (wtf-map.js).
 *
 * These run the REAL module against a stubbed Leaflet + DOM, so they test the
 * shipped logic rather than asserting on source text. The honesty rules are the
 * point: a shared component makes every map look uniform, and uniform-looking
 * maps are exactly where "no data" quietly becomes "zero".
 *
 * Run: node tests/test_wtf_map_component.js
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; } else { fail++; console.log("  FAIL:", msg); } };

// ── minimal DOM ────────────────────────────────────────────────────────────
function mkEl(tag) {
  return {
    tagName: (tag || "div").toUpperCase(), className: "", style: {},
    children: [], _text: "",
    set textContent(v) { this._text = v; this.children = []; },
    get textContent() {
      return this.children.length
        ? this.children.map(c => c.textContent).join("")
        : this._text;
    },
    appendChild(c) { this.children.push(c); return c; },
    querySelectorAll() { return []; },
  };
}
const legendEl = mkEl("div");
const mapEl = mkEl("div");
const document = {
  getElementById: id => (id === "legend" ? legendEl : id === "map" ? mapEl : null),
  createElement: mkEl,
  createTextNode: t => ({ textContent: String(t), children: [], appendChild() {} }),
};

// ── minimal Leaflet ────────────────────────────────────────────────────────
let styleFn = null;
const paneStub = { style: {} };
const L = {
  map: () => ({
    createPane: () => {}, getPane: () => paneStub,
    setView() { return this; }, on() { return this; },
  }),
  latLngBounds: b => b,
  layerGroup: () => ({ addTo() { return this; }, clearLayers() { this.n = 0; }, addLayer() { this.n = (this.n || 0) + 1; } }),
  circleMarker: (ll, o) => ({ ll, o, bindTooltip() { return this; } }),
  geoJSON: (gj, o) => { styleFn = o.style; return { addTo() { return this; }, setStyle() {}, resetStyle() {} }; },
};

// fetch MUST resolve: L.geoJSON (and therefore the style function) is only
// reached inside fetch().then(). A never-resolving stub silently skips the
// entire choropleth path — the first version of this file did exactly that and
// reported "style function was not captured" instead of testing anything.
const FAKE_GEOJSON = {
  type: "FeatureCollection",
  features: ["Ontario", "Quebec", "British Columbia"].map(n => ({
    type: "Feature", properties: { name: n }, geometry: { type: "Polygon", coordinates: [] },
  })),
};
const sandbox = {
  window: {}, document, L, console,
  fetch: () => Promise.resolve({ json: () => Promise.resolve(FAKE_GEOJSON) }),
};
sandbox.window.L = L;
sandbox.window.document = document;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "consumer", "static", "js", "wtf-map.js"), "utf8"), sandbox);
const WTFMap = sandbox.window.WTFMap;

console.log("wtf-map component");

// ── the layer under test ───────────────────────────────────────────────────
const RAMP = [[10, "#111111", "0-10"], [100, "#222222", "10-100"], [1e9, "#333333", "100+"]];
const DATA = { ON: 55, QC: 5 };            // BC deliberately absent
const layer = {
  id: "test", label: "Test", ramp: RAMP,
  metric: code => (DATA[code] === undefined ? null : { v: DATA[code], col: WTFMap.ramp(RAMP, DATA[code]) }),
  coverageNote: () => "Reported in 2 of 13 provinces & territories.",
};

const inst = WTFMap.create({ el: "map", legendEl: "legend", layers: [layer], active: "test" });
ok(inst !== null, "component constructs");

async function main() {
// ── RULE 2: legend is derived from the ramp ────────────────────────────────
const labels = legendEl.children[0].children.map(c => c.textContent);
ok(labels.length === RAMP.length + 1, `legend has one entry per ramp stop + no-data (got ${labels.length})`);
RAMP.forEach(s => ok(labels.some(l => l.includes(s[2])), `ramp label "${s[2]}" appears in the legend`));
ok(labels.some(l => /no data/i.test(l)), "the no-data grey has its own legend entry");

// A ramp stop added later must appear WITHOUT touching legend code.
RAMP.push([1e12, "#444444", "EXTREME"]);
inst.refresh();
const after = legendEl.children[0].children.map(c => c.textContent);
ok(after.some(l => l.includes("EXTREME")),
   "a NEW ramp stop appears in the legend automatically (this is the drift fix)");
RAMP.pop();

// ── coverage note ──────────────────────────────────────────────────────────
inst.refresh();
ok(legendEl.children.length === 2 && /2 of 13/.test(legendEl.children[1].textContent),
   "the layer's coverage limits are stated in the legend");

// ── RULE 1: absence is not a darker shade ──────────────────────────────────
// styleFn was captured by the L.geoJSON stub when the module loaded geometry.
const captured = styleFn;
const styleOf = name => captured({ properties: { name } });
if (captured) {
  const on = styleOf("Ontario"), bc = styleOf("British Columbia");
  ok(on.fillColor !== WTFMap.NO_DATA, "a province WITH data uses its ramp colour");
  ok(bc.fillColor === WTFMap.NO_DATA, "a province WITHOUT data uses the no-data colour");
  ok(bc.dashArray && !on.dashArray, "absence is DASHED and presence is not");
  ok(bc.fillOpacity < on.fillOpacity, "absence is dimmer than presence");
  ok(!(bc.fillColor === on.fillColor), "absence never renders as a band of the ramp");
} else { fail++; console.log("  FAIL: style function was not captured"); }

// ── no third-party tiles ───────────────────────────────────────────────────
const src = fs.readFileSync(path.join(__dirname, "..", "consumer", "static", "js", "wtf-map.js"), "utf8");
ok(!/tileLayer|cartocdn|openstreetmap\.org\/\{z\}|mapbox/i.test(src),
   "the component loads no third-party basemap tiles");
ok(/maxBounds/.test(src), "the view is bounded (no tiles means panning would show void)");

console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}
// let the resolved fetch() chain run before asserting
setTimeout(main, 0);
