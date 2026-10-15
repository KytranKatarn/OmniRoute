/* Behavioural test for symbol plates in the shared map (wtf-map.js), task 7236. Runs the REAL module against a stubbed d3 + DOM.
 * (tests/test_wtf_map_component.js still stubs Leaflet and fails on main before this change; it is not touched here.)
 * Run: node tests/test_wtf_map_plates.js
 */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log("  FAIL:", m); } };

function node(tag) {
  const n = { tag, attrs: {}, children: [], listeners: {}, _text: "", style: {}, innerHTML: "" };
  n.setAttribute = (k, v) => { n.attrs[k] = String(v); };
  n.getAttribute = k => n.attrs[k];
  n.appendChild = c => { n.children.push(c); return c; };
  n.addEventListener = (e, f) => { n.listeners[e] = f; };
  n.removeChild = c => { n.children = n.children.filter(x => x !== c); };
  Object.defineProperty(n, "textContent", { get() { return n.children.length ? n.children.map(c => c.textContent).join("") : n._text; },
    set(v) { n._text = v; n.children = []; } });
  Object.defineProperty(n, "firstChild", { get() { return n.children[0] || null; } });
  n.querySelectorAll = () => []; n.querySelector = () => null; n.classList = { add() {}, remove() {}, toggle() {} };
  return n;
}
const host = node("div"); host.clientWidth = 800; host.clientHeight = 500;
const win = { addEventListener() {}, document: null, d3: null };
// DOMParser stub: records the fragment on a marker child so the test can see exactly what was parsed (and that nothing was assigned as innerHTML).
win.DOMParser = function () { this.parseFromString = s => { const m = node("parsed"); m.fragment = s; return { documentElement: { childNodes: [m] } }; }; };
const document = { importNode: n => n, getElementById: () => host, createElementNS: (ns, t) => node(t), createElement: t => node(t), createTextNode: s => { const n = node("#text"); n._text = s; return n; } };
const proj = ll => [(ll[0] + 141) * 5, (84 - ll[1]) * 6];
proj.fitExtent = () => proj; proj.parallels = () => proj; proj.rotate = () => proj;
win.d3 = { geoConicConformal: () => proj, geoNaturalEarth1: () => proj, geoPath: () => { const p = () => ""; p.area = () => 0; p.centroid = () => [0, 0]; p.bounds = () => [[0, 0], [1, 1]]; return p; } };
const ctx = { window: win, document, fetch: () => Promise.resolve({ json: () => Promise.resolve({ type: "FeatureCollection", features: [] }) }),
  setTimeout, clearTimeout, console, isFinite, Math, String, Object, Array };
win.document = document; ctx.window = win; ctx.global = win;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "consumer", "static", "js", "wtf-map.js"), "utf8"), ctx);
const WTFMap = win.WTFMap;

const SVG = '<path d="M0 0"/>';
function run(points) {
  host.children = [];
  return new Promise(res => {
    let rendered = null;
    const m = WTFMap.create({ el: host, layers: [{ id: "cities", ramp: [[100, "#fff", "x"]], metric: () => null, points: () => points }],
      active: "cities", onRender: r => { rendered = r; } });
    setTimeout(() => {
      const all = []; (function walk(n) { n.children.forEach(c => { all.push(c); walk(c); }); })(host);
      res({ all, rendered });
    }, 30);
  });
}
const plates = a => a.filter(n => (n.attrs.class || "").indexOf("wtf-map-plate") >= 0);
const dots = a => a.filter(n => n.tag === "circle" && n.attrs.class === "wtf-map-pt");

(async () => {
  console.log("wtf-map plates");
  // 1. a point with a glyph becomes a plate carrying the page's constant svg and a textContent label
  let r = await run([{ lat: 50, lon: -100, col: "#0f0", glyph: { svg: SVG, label: "12°" }, tip: "A" }]);
  ok(plates(r.all).length === 1 && dots(r.all).length === 0, "glyph point draws a plate, not a dot");
  const plate = plates(r.all)[0];
  ok(plate && plate.children.some(g => g.children.some(c => c.fragment && c.fragment.indexOf(SVG) >= 0)), "plate carries the page-supplied svg fragment, parsed");
  ok(plate && plate.children.every(c => c.innerHTML === ""), "nothing was assigned as innerHTML");
  ok(plate && plate.children.some(c => c.tag === "text" && c.textContent === "12°"), "label is written as text");
  // 2. label is text, never markup
  r = await run([{ lat: 50, lon: -100, col: "#0f0", glyph: { svg: SVG, label: "<img onerror=x>" } }]);
  const t = plates(r.all)[0].children.find(c => c.tag === "text");
  ok(t.textContent === "<img onerror=x>" && t.innerHTML === "" && !t.children.length, "a hostile label stays inert text");
  // 3. a point with no glyph is still a dot
  r = await run([{ lat: 50, lon: -100, col: "#0f0" }]);
  ok(dots(r.all).length === 1 && plates(r.all).length === 0, "no glyph keeps the dot");
  // 4. overlapping plates: the first keeps its plate, the second falls back to a dot, and BOTH are still drawn and reported
  r = await run([{ lat: 50, lon: -100, col: "#0f0", glyph: { svg: SVG, label: "12°" }, tip: "first" },
                 { lat: 50.1, lon: -100.1, col: "#0f0", glyph: { svg: SVG, label: "13°" }, tip: "second" }]);
  ok(plates(r.all).length === 1 && dots(r.all).length === 1, "a crowded second city falls back to a dot");
  ok(r.rendered.drawn.length === 2, "both cities are counted as drawn");
  // 5. well-separated plates both stay
  r = await run([{ lat: 50, lon: -120, col: "#0f0", glyph: { svg: SVG, label: "5°" } },
                 { lat: 50, lon: -90, col: "#0f0", glyph: { svg: SVG, label: "7°" } }]);
  ok(plates(r.all).length === 2, "separated cities keep their plates");
  // 6. stale: faded plate with dashed stroke; home: heavier stroke
  r = await run([{ lat: 50, lon: -100, col: "#0f0", faded: true, glyph: { svg: SVG, label: "9°" } }]);
  ok(plates(r.all)[0].attrs.opacity === "0.5" && plates(r.all)[0].children[0].attrs["stroke-dasharray"] === "2,2", "stale plate is faded and dashed");
  r = await run([{ lat: 50, lon: -100, col: "#0f0", home: true, glyph: { svg: SVG, label: "9°" } }]);
  ok(parseFloat(plates(r.all)[0].children[0].attrs["stroke-width"]) > 2, "home city plate has a heavier outline");
  // 7. tooltip + click still wired on a plate
  let clicked = 0;
  r = await run([{ lat: 50, lon: -100, col: "#0f0", tip: "t", onClick: () => clicked++, glyph: { svg: SVG, label: "9°" } }]);
  const pl = plates(r.all)[0]; pl.listeners.click && pl.listeners.click();
  ok(clicked === 1 && !!pl.listeners.mousemove, "plate keeps click and tooltip");
  // 8. a plate for a city at the map edge is moved inward, never clipped (St. John's, live 2026-10-15). With the stub projection x = (lon+141)*5 and the
  // host is 800 wide, so lon 18 lands at x = 795: the plate (half-width 28) would overhang the edge if it were not clamped.
  r = await run([{ lat: 50, lon: 18, col: "#0f0", glyph: { svg: SVG, label: "12.8\u00b0" } }]);
  const ed = plates(r.all)[0];
  if (ed) { const m = /translate\(([-\d.]+),([-\d.]+)\)/.exec(ed.attrs.transform); const half = (22 + "12.8\u00b0".length * 7) / 2;
    ok(parseFloat(m[1]) + half <= 800 && parseFloat(m[1]) - half >= 0, "an edge plate is clamped inside the map (translate x " + m[1] + ", half-width " + half + ")"); }
  else ok(false, "edge plate was drawn");
  // 9. the dot of a crowded city is drawn BEFORE (under) every plate
  r = await run([{ lat: 50, lon: -100, col: "#0f0", glyph: { svg: SVG, label: "12\u00b0" } }, { lat: 50.1, lon: -100.1, col: "#0f0", glyph: { svg: SVG, label: "13\u00b0" } }]);
  const pts = r.all.find(n => (n.attrs.class || "") === "wtf-map-points");
  const order = pts ? pts.children.map(n => (n.attrs.class || "").indexOf("plate") >= 0 ? "plate" : "dot") : [];
  ok(order.join() === "dot,plate", "fallback dot sits under the plate (order: " + order.join() + ")");

  console.log(`  ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
