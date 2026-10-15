/* Behavioural test for raster overlays in the shared map (wtf-map.js), WX-1b. Real wtf-map.js + real wtf-raster.js against a stubbed d3 + DOM + fetch.
 * Run: node tests/test_wtf_map_overlay.js */
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log("  FAIL:", m); } };
const wait = ms => new Promise(r => setTimeout(r, ms));

function node(tag) {
  const n = { tag, attrs: {}, children: [], listeners: {}, _text: "", style: {}, innerHTML: "" };
  n.setAttribute = (k, v) => { n.attrs[k] = String(v); }; n.getAttribute = k => n.attrs[k]; n.removeAttribute = k => { delete n.attrs[k]; };
  n.appendChild = c => { n.children.push(c); return c; }; n.addEventListener = (e, f) => { n.listeners[e] = f; };
  Object.defineProperty(n, "textContent", { get() { return n.children.length ? n.children.map(c => c.textContent).join("") : n._text; }, set(v) { n._text = v; n.children = []; } });
  n.querySelectorAll = () => []; n.classList = { add() {}, remove() {}, toggle() {} };
  return n;
}
function load(extra) {
  const host = node("div"); host.clientWidth = 800; host.clientHeight = 500;
  const state = { fetches: [], timers: [], now: 1_000_000 };
  const win = { addEventListener() {}, DOMParser: function () { this.parseFromString = () => ({ documentElement: { childNodes: [] } }); } };
  win.document = { getElementById: () => host, createElementNS: (ns, t) => node(t), createElement: t => node(t), createTextNode: s => { const n = node("#text"); n._text = s; return n; }, importNode: n => n };
  const proj = ll => [(ll[0] + 141) * 5, (84 - ll[1]) * 6];
  proj.invert = xy => [xy[0] / 5 - 141, 84 - xy[1] / 6];
  proj.fitExtent = () => proj; proj.parallels = () => proj; proj.rotate = () => proj;
  win.d3 = { geoConicConformal: () => proj, geoNaturalEarth1: () => proj, geoPath: () => { const p = () => "M0 0L1 1"; p.area = () => 0; p.centroid = () => [0, 0]; p.bounds = () => [[0, 0], [1, 1]]; return p; } };
  const routes = (extra && extra.routes) || {};
  const ctx = { window: win, document: win.document, console, isFinite, Math, String, Object, Array, Promise, Error, Date: { now: () => state.now },
    setTimeout: (f, ms) => { state.timers.push({ f, ms }); return state.timers.length; }, clearTimeout: () => {},
    fetch: url => { state.fetches.push(url); const r = routes[url.split("?")[0]]; if (typeof r === "function") return r(url);
      if (url.indexOf("canada-provinces") >= 0) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ type: "FeatureCollection", features: [{ properties: { name: "Ontario" } }, { properties: { name: "Quebec" } }] }) });
      return Promise.reject(new Error("no route " + url)); } };
  win.fetch = ctx.fetch;
  vm.createContext(ctx);
  if (!(extra && extra.noRaster)) vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "consumer", "static", "js", "wtf-raster.js"), "utf8"), ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "consumer", "static", "js", "wtf-map.js"), "utf8"), ctx);
  return { win, host, state, WTFMap: win.WTFMap, ctx };
}
const json = (o, status) => () => Promise.resolve({ ok: (status || 200) < 400, status: status || 200, json: () => Promise.resolve(o) });
const png = (status) => () => Promise.resolve({ ok: (status || 200) < 400, status: status || 200, blob: () => Promise.resolve({}) });
const META = { key: "radar", png_url: "/weather/overlay/radar.png?v=T1", bbox: [-141, 41, -52, 84], nearest: true, age_s: 100, stale: false, stale_after_s: 1800, kind: "observed", valid_time: "T1" };
const IMG = { data: new Uint8ClampedArray(4 * 4 * 2).fill(255), width: 4, height: 2 };
const walk = h => { const all = []; (function w(n) { n.children.forEach(c => { all.push(c); w(c); }); })(h); return all; };
const images = h => walk(h).filter(n => n.tag === "image");

function mk(env, opts, layerExtra) {
  const events = [];
  const layers = [{ id: "plain", ramp: [[1, "#fff", "x"]], metric: () => null }, Object.assign({ id: "radar", metric: () => null, overlay: { baseUrl: "/weather/overlay/radar", opacity: 0.8, refreshMs: 300000 } }, layerExtra || {})];
  const m = env.WTFMap.create(Object.assign({ el: env.host, layers, active: "plain", onOverlay: e => events.push(e),
    decodeImage: () => Promise.resolve(IMG), encodeImage: () => "data:image/png;base64,FAKE" }, opts || {}));
  return { m, events };
}

(async () => {
  console.log("wtf-map overlays");
  // 1. happy path
  let env = load({ routes: { "/weather/overlay/radar/meta.json": json(META), "/weather/overlay/radar.png": png() } });
  let { m, events } = mk(env); await wait(20); m.setLayer("radar"); await wait(40);
  ok(events.map(e => e.state).join() === "loading,ready", "states: loading then ready (" + events.map(e => e.state).join() + ")");
  ok(env.state.fetches.some(u => u === "/weather/overlay/radar.png?v=T1"), "fetches the PNG the metadata NAMES (frame-pinned url)");
  const im = images(env.host)[0];
  ok(im && im.attrs.href === "data:image/png;base64,FAKE" && im.attrs.opacity === "0.8" && im.attrs.width === "800", "an <image> with the reprojected data is drawn at map size");
  ok(walk(env.host).filter(n => n.tag === "path" && n.attrs.stroke === "#e2e8f0").length === 2, "province outlines are redrawn above the overlay");
  ok(events[1].meta && events[1].meta.valid_time === "T1" && events[1].stale === false, "the ready event carries the frame's own meta, not stale");
  // 2. cached: leave and come back = no refetch
  const n0 = env.state.fetches.length; m.setLayer("plain"); await wait(10);
  ok(images(env.host).length === 0, "switching to a plain layer removes the overlay");
  m.setLayer("radar"); await wait(20);
  ok(env.state.fetches.length === n0 && images(env.host).length === 1, "returning to the layer repaints from cache without refetching");

  // 3. 409: the frame rolled over between meta and png -> meta is read again, once
  let calls = 0;
  env = load({ routes: { "/weather/overlay/radar/meta.json": () => { calls++; return json(Object.assign({}, META, { png_url: "/weather/overlay/radar.png?v=T" + calls }))(); },
                         "/weather/overlay/radar.png": u => (u.indexOf("v=T1") >= 0 ? png(409)() : png()()) } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(50);
  ok(calls === 2 && events[events.length - 1].state === "ready", "a 409 re-reads meta once and succeeds (meta reads: " + calls + ")");

  // 4. failures are shown, nothing is drawn
  env = load({ routes: { "/weather/overlay/radar/meta.json": json({ error: "unavailable" }, 503) } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(40);
  ok(events[events.length - 1].state === "error" && /503/.test(events[events.length - 1].error) && images(env.host).length === 0, "meta 503 -> error state, no image drawn");
  env = load({ routes: { "/weather/overlay/radar/meta.json": json(META), "/weather/overlay/radar.png": png(500) } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(40);
  ok(events[events.length - 1].state === "error" && images(env.host).length === 0, "png 500 -> error state, no image drawn");
  const nf = env.state.fetches.length; m.setLayer("plain"); m.setLayer("radar"); await wait(20);
  ok(env.state.fetches.length === nf, "an error is not retried in a tight loop (30 s back-off)");
  env = load({ noRaster: true, routes: {} });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(20);
  ok(events[events.length - 1].state === "error" && /not loaded/.test(events[events.length - 1].error), "missing wtf-raster.js is reported in words");

  // 5. staleness
  env = load({ routes: { "/weather/overlay/radar/meta.json": json(Object.assign({}, META, { stale: true })), "/weather/overlay/radar.png": png() } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(40);
  ok(events[events.length - 1].stale === true, "server-marked stale is passed through");
  env = load({ routes: { "/weather/overlay/radar/meta.json": json(Object.assign({}, META, { age_s: 1700 })), "/weather/overlay/radar.png": png() } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(40);
  ok(events[events.length - 1].stale === false, "1700 s old is still fresh against a 1800 s limit");
  env.state.now += 200 * 1000; m.setLayer("plain"); m.setLayer("radar"); await wait(20);
  ok(events[events.length - 1].stale === true && events[events.length - 1].ageNowS > 1800, "a page left open becomes stale on its own (age is advanced client-side)");

  // 6. refresh: new frame replaces the old; a failed refresh keeps the last frame and says so
  let frame = 1;
  env = load({ routes: { "/weather/overlay/radar/meta.json": () => json(Object.assign({}, META, { valid_time: "T" + frame, png_url: "/weather/overlay/radar.png?v=T" + frame }))(),
                         "/weather/overlay/radar.png": u => (frame === 3 ? png(500)() : png()()) } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(40);
  ok(env.state.timers.some(t => t.ms === 300000), "a refresh is scheduled");
  frame = 2; env.state.timers.filter(t => t.ms === 300000).pop().f(); await wait(40);
  ok(events[events.length - 1].meta.valid_time === "T2" && images(env.host).length === 1, "refresh swaps in the new frame");
  frame = 3; env.state.timers.filter(t => t.ms === 300000).pop().f(); await wait(40);
  const last = events[events.length - 1];
  ok(last.state === "ready" && last.error && images(env.host).length === 1 && last.meta.valid_time === "T2", "a failed refresh keeps the last good frame and reports the error");

  // 7. never two frame loads for one layer at once (review #3879): a refresh timer firing twice, plus a 409 retry, must still be ONE request chain
  let active = 0, maxActive = 0, metaReads = 0;
  const track = fn => u => { active++; maxActive = Math.max(maxActive, active); metaReads += u.indexOf("meta.json") >= 0 ? 1 : 0;
    return new Promise(res => setTimeout(res, 15)).then(() => { active--; return fn(u); }); };
  let n409 = 0;
  env = load({ routes: { "/weather/overlay/radar/meta.json": track(() => json(META)()), "/weather/overlay/radar.png": track(() => (n409++ === 0 ? png(409)() : png()())) } });
  ({ m, events } = mk(env)); await wait(20); m.setLayer("radar"); await wait(200);
  ok(maxActive === 1 && n409 === 2, "initial load with a 409 retry is one sequential chain (max concurrent requests " + maxActive + ", png attempts " + n409 + ")");
  metaReads = 0; maxActive = 0;
  const tm = env.state.timers.filter(t => t.ms === 300000).pop();
  tm.f(); tm.f(); tm.f(); m.setLayer("plain"); m.setLayer("radar"); await wait(200);
  ok(metaReads === 1 && maxActive === 1, "three refresh triggers at once start ONE load (meta reads " + metaReads + ", max concurrent " + maxActive + ")");

  console.log(`  ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
