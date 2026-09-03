/* wtf-map.js — ONE map component for every layered map on this site.
 *
 * WHY THIS EXISTS
 * There were THREE separate Leaflet implementations inline in templates:
 * weather.html (province choropleth + station/city markers), index.html (lean
 * choropleth + article markers) and map.html (news circles). Same library, same
 * province geometry, three copies of the logic — which is exactly why the
 * weather legend could drift out of sync with its ramp while the other two were
 * unaffected: a fix in one reached none of the others.
 *
 * A new data layer (crime, for instance) should be a REGISTRATION, not a fourth
 * copy of a map.
 *
 * ── RENDERER: D3-GEO, NOT LEAFLET (2026-09-02) ─────────────────────────────
 * Three reasons, in order of how much they matter to a reader:
 *
 * 1. PROJECTION. Leaflet is Web Mercator, which inflates area with latitude —
 *    on a map of Canada that means Nunavut and the Northwest Territories are
 *    drawn far larger than they are. On a map of NEWS COVERAGE that is the
 *    worst possible distortion, because the emptiest regions are exactly the
 *    ones Mercator makes biggest. This uses a Lambert conformal conic
 *    (parallels 49°/77°), the projection Canadian atlases use.
 *
 * 2. NO THIRD-PARTY REQUESTS. map.html loaded raster basemap tiles from
 *    basemaps.cartocdn.com, so every reader's browser announced itself to a
 *    third party on every pan — while this module's own docstring promised
 *    "NO third-party tiles". Leaflet itself came from unpkg. Both are gone:
 *    d3-geo is vendored under /static/vendor (60 KB total, versions recorded in
 *    vendor/VERSIONS.txt) and the geometry was already local.
 *
 * 3. SIZE. 60 KB of vendored d3-geo replaces ~145 KB of Leaflet + its CSS + a
 *    tile request per viewport per pan.
 *
 * ⚠️ `.map` (the Leaflet instance) IS GONE FROM THE PUBLIC API, deliberately.
 * weather.html called `wtfmap.map.flyTo(...)`, and keeping a `flyTo` shim on a
 * component with no Leaflet in it would be an interface that lies about what is
 * underneath. Callers use focusProvince(code) / resetView() instead.
 *
 * WHAT IT OWNS (the genuinely shared part)
 *   - a bounded Canada map with a designed ground and NO third-party tiles
 *   - the province choropleth, driven by a per-layer metric function
 *   - the legend, DERIVED from the active layer's ramp so the two cannot drift
 *   - "no data" rendered as visibly different from a low value
 *   - points that fall outside the projection, COUNTED and reported
 *   - layer switching
 *
 * WHAT IT DOES NOT OWN
 * Where the numbers come from. Each page supplies `metric(code)` and its own
 * point markers. This module never fetches domain data — it would have to know
 * about weather AND crime AND coverage to do that, which is how a shared
 * component turns into a god object.
 *
 * ⚠️ HONESTY RULES BAKED IN — these are not styling choices:
 *   1. A region with NO DATA on the active layer is drawn dimmed AND dashed,
 *      never as a darker shade of the ramp. Absence and "a low number" are
 *      different facts and must not look alike.
 *   2. The legend is generated from the ramp array. Every colour the map can
 *      paint therefore has an entry. Do not hand-write a stop list.
 *   3. Every ramp stop carries its own label: [threshold, colour, label].
 *   4. A point the projection cannot place is COUNTED AND STATED, never
 *      dropped. A Canada projection necessarily clips anything outside Canada,
 *      and silently clipping is how a map claims coverage it does not have.
 *   5. All point/tooltip text goes in via textContent. Article titles are
 *      external content (WTF XSS rule) and never touch innerHTML.
 */
(function (global) {
  "use strict";

  var GEOJSON_URL = "/static/canada-provinces.geojson";
  var NO_DATA = "#1b2430";

  // Kept for callers that still pass bounds; the conic projection is fitted to
  // the geometry itself, so this is no longer what frames the map.
  var CANADA_BOUNDS = [[38.0, -150.0], [86.0, -45.0]];

  // GeoJSON property "name" -> province code. The dataset spells Yukon two
  // ways; both map to YT. One canonicalisation point, as with _canon_prov
  // server-side — a second one is how a province goes missing.
  var PROVINCE_CODES = {
    "Alberta": "AB", "British Columbia": "BC", "Manitoba": "MB",
    "New Brunswick": "NB", "Newfoundland and Labrador": "NL",
    "Nova Scotia": "NS", "Northwest Territories": "NT", "Nunavut": "NU",
    "Ontario": "ON", "Prince Edward Island": "PE", "Quebec": "QC",
    "Saskatchewan": "SK", "Yukon": "YT", "Yukon Territory": "YT"
  };

  var SVG_NS = "http://www.w3.org/2000/svg";

  /** First stop whose threshold >= v. Stops are [threshold, colour, label]. */
  function ramp(stops, v) {
    for (var i = 0; i < stops.length; i++) if (v <= stops[i][0]) return stops[i][1];
    return stops[stops.length - 1][1];
  }

  function el(tag, attrs) {
    var n = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) n.setAttribute(k, attrs[k]);
    return n;
  }

  function create(opts) {
    var host = typeof opts.el === "string" ? document.getElementById(opts.el) : opts.el;
    if (!host) return null;
    // Fail loudly and in words. A blank rectangle is the one outcome a map
    // must never produce silently.
    if (!global.d3 || !global.d3.geoConicConformal) {
      host.textContent = "Map library failed to load.";
      return null;
    }

    var layers = opts.layers || [];
    var active = opts.active || (layers[0] && layers[0].id);
    var selected = null;
    var geo = null;              // the GeoJSON FeatureCollection
    var projection = null;
    var path = null;
    var focusCode = null;        // province the view is fitted to, or null
    var offscreen = 0;           // points the projection placed off-canvas
    var invalidCount = 0;        // points whose coordinates are impossible

    host.textContent = "";
    host.classList.add("wtf-map-d3");
    var svg = el("svg", { class: "wtf-map-svg", role: "img" });
    var gProv = el("g", { class: "wtf-map-provinces" });
    var gPts = el("g", { class: "wtf-map-points" });
    svg.appendChild(gProv);
    svg.appendChild(gPts);
    host.appendChild(svg);

    var tip = document.createElement("div");
    tip.className = "wtf-map-tip";
    tip.setAttribute("hidden", "hidden");
    host.appendChild(tip);

    function showTip(text, evt) {
      if (!text) return;
      tip.textContent = text;          // RULE 5 — never innerHTML
      tip.removeAttribute("hidden");
      var b = host.getBoundingClientRect();
      tip.style.left = (evt.clientX - b.left + 12) + "px";
      tip.style.top = (evt.clientY - b.top + 12) + "px";
    }
    function hideTip() { tip.setAttribute("hidden", "hidden"); }

    function layerDef(id) {
      for (var i = 0; i < layers.length; i++) if (layers[i].id === id) return layers[i];
      return null;
    }

    function size() {
      var w = host.clientWidth || 640;
      var h = host.clientHeight || Math.round(w * 0.62);
      return [Math.max(w, 240), Math.max(h, 200)];
    }

    /** Fit the conic projection to `feature` (or all of Canada when null). */
    function fit(feature) {
      var wh = size();
      svg.setAttribute("viewBox", "0 0 " + wh[0] + " " + wh[1]);
      svg.setAttribute("width", wh[0]);
      svg.setAttribute("height", wh[1]);
      projection = global.d3.geoConicConformal()
        .parallels([49, 77])
        .rotate([96, 0]);
      // A little padding so a focused province is not flush with the edge.
      var pad = 12;
      projection.fitExtent(
        [[pad, pad], [wh[0] - pad, wh[1] - pad]],
        feature || geo
      );
      path = global.d3.geoPath(projection);
    }

    function featureFor(code) {
      if (!geo || !code) return null;
      for (var i = 0; i < geo.features.length; i++) {
        var f = geo.features[i];
        if (PROVINCE_CODES[f.properties && f.properties.name] === code) return f;
      }
      return null;
    }

    function styleOf(code) {
      var def = layerDef(active);
      var m = (def && def.metric && code) ? def.metric(code) : null;
      var isSel = selected && code === selected;
      // RULE 1 — absence is dimmed AND dashed, never a darker fill.
      return {
        fill: m ? m.col : NO_DATA,
        "fill-opacity": m ? (isSel ? 1 : 0.92) : 0.45,
        stroke: isSel ? "#e6edf6" : "#0b1220",
        "stroke-width": isSel ? 2.2 : 0.8,
        "stroke-dasharray": m ? null : "3,3"
      };
    }

    function drawProvinces() {
      gProv.textContent = "";
      if (!geo || !path) return;
      var def = layerDef(active);
      geo.features.forEach(function (f) {
        var code = PROVINCE_CODES[f.properties && f.properties.name];
        var d = path(f);
        if (!d) return;
        var p = el("path", { d: d, class: "wtf-map-prov", "data-code": code || "" });
        var st = styleOf(code);
        for (var k in st) if (st[k] !== null) p.setAttribute(k, st[k]);
        if (def && def.tooltip && code) {
          var text = def.tooltip(code);
          p.addEventListener("mousemove", function (e) { showTip(text, e); });
          p.addEventListener("mouseleave", hideTip);
        }
        p.addEventListener("click", function () {
          select(code === selected ? null : code);
        });
        gProv.appendChild(p);
      });
    }

    function drawPoints() {
      gPts.textContent = "";
      offscreen = 0; invalidCount = 0;
      var drawnPts = [], offPts = [], invalidPts = [];
      var def = layerDef(active);
      if (!def || !def.points || !projection) { drawLegend(); return; }
      var wh = size();
      def.points(selected).forEach(function (p) {
        if (p.lat === null || p.lat === undefined || p.lon === null || p.lon === undefined) return;
        // ⚠️ AN IMPOSSIBLE COORDINATE IS NOT AN OUT-OF-VIEW ONE, and the two
        // must not be reported with the same words. Measured in the live feed:
        // a story carries lat -117.95 / lng 49.28 — latitude cannot exceed 90,
        // so the pair is transposed and the real location is in BC. Rolling
        // that into "falls outside this view of Canada" would tell the reader
        // something false about where the story is.
        if (!isFinite(p.lat) || !isFinite(p.lon) ||
            p.lat < -90 || p.lat > 90 || p.lon < -180 || p.lon > 180) {
          invalidPts.push(p); invalidCount++;
          return;
        }
        var xy = projection([p.lon, p.lat]);
        // RULE 4 — a point the projection clips is counted, not dropped.
        //
        // ⚠️ THIS IS THE COST OF A CANADA PROJECTION AND IT MUST BE PAID OUT
        // LOUD. A conic fitted to Canada necessarily puts everything else off
        // the canvas. A page whose legend tallies every pin it was GIVEN would
        // then report international coverage that no reader can see. So the
        // component hands back both lists and the page tallies what was
        // actually DRAWN — see onRender.
        if (!xy || !isFinite(xy[0]) || !isFinite(xy[1]) ||
            xy[0] < 0 || xy[1] < 0 || xy[0] > wh[0] || xy[1] > wh[1]) {
          offscreen++;
          offPts.push(p);
          return;
        }
        drawnPts.push(p);
        var c = el("circle", {
          cx: xy[0], cy: xy[1],
          r: p.r === undefined ? 5 : p.r,
          fill: p.col || NO_DATA,
          "fill-opacity": p.faded ? 0.35 : 0.9,
          stroke: p.faded ? "#6b7280" : "#020617",
          "stroke-width": p.faded ? 1.5 : 1,
          "stroke-dasharray": p.faded ? "2,2" : null,
          class: "wtf-map-pt"
        });
        if (p.tip) {
          c.addEventListener("mousemove", function (e) { showTip(p.tip, e); });
          c.addEventListener("mouseleave", hideTip);
        }
        if (p.onClick) c.addEventListener("click", function () { p.onClick(p); });
        gPts.appendChild(c);
      });
      drawLegend();
      // The page gets the two lists so its own legend can describe what is on
      // SCREEN rather than what was handed in.
      if (opts.onRender) opts.onRender({ drawn: drawnPts, offscreen: offPts,
                                         invalid: invalidPts });
    }

    function drawLegend() {
      var box = opts.legendEl
        ? (typeof opts.legendEl === "string" ? document.getElementById(opts.legendEl) : opts.legendEl)
        : null;
      if (!box) return;
      box.textContent = "";
      var def = layerDef(active);
      if (!def || !def.ramp) return;

      var row = document.createElement("div");
      row.className = "wtf-map-legend-row";
      // RULE 2 — derived from the ramp. Never a hand-written stop list.
      def.ramp.forEach(function (s) {
        var sp = document.createElement("span");
        var sw = document.createElement("i");
        sw.className = "wtf-map-swatch";
        sw.style.background = s[1];
        sp.appendChild(sw);
        sp.appendChild(document.createTextNode(s[2]));
        row.appendChild(sp);
      });
      var na = document.createElement("span");
      var naSw = document.createElement("i");
      naSw.className = "wtf-map-swatch is-nodata";
      naSw.style.background = NO_DATA;
      na.appendChild(naSw);
      na.appendChild(document.createTextNode(def.noDataLabel || "no data on this layer"));
      row.appendChild(na);
      box.appendChild(row);

      // Coverage is a fact about the layer, not a footnote — state it here.
      if (def.coverageNote) {
        var cov = document.createElement("div");
        cov.className = "wtf-map-legend-note";
        cov.textContent = def.coverageNote();
        box.appendChild(cov);
      }
      // RULE 4, stated where the reader is already looking for caveats.
      if (offscreen > 0) {
        var off = document.createElement("div");
        off.className = "wtf-map-legend-note is-offscreen";
        off.textContent = offscreen === 1
          ? "1 location falls outside this view of Canada and is not drawn."
          : offscreen + " locations fall outside this view of Canada and are not drawn.";
        box.appendChild(off);
      }
      if (invalidCount > 0) {
        // Distinct wording from the line above ON PURPOSE — see drawPoints.
        var bad = document.createElement("div");
        bad.className = "wtf-map-legend-note is-offscreen";
        bad.textContent = invalidCount === 1
          ? "1 location has coordinates outside the possible range and cannot be placed."
          : invalidCount + " locations have coordinates outside the possible range and cannot be placed.";
        box.appendChild(bad);
      }
    }

    function restyle() { drawProvinces(); drawPoints(); }

    function select(code) {
      selected = code;
      if (opts.onSelect) opts.onSelect(code);
      restyle();
    }

    function setLayer(id) {
      if (!layerDef(id)) return;
      active = id;
      if (opts.onLayer) opts.onLayer(id);
      restyle();
    }

    /** Frame the map on one province. Replaces the old `map.flyTo(centroid)`. */
    function focusProvince(code) {
      var f = featureFor(code);
      if (!f) return resetView();
      focusCode = code;
      fit(f);
      restyle();
    }

    function resetView() {
      focusCode = null;
      if (geo) { fit(null); restyle(); }
    }

    var resizeTimer = null;
    function onResize() {
      if (!geo) return;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        fit(focusCode ? featureFor(focusCode) : null);
        restyle();
      }, 120);
    }
    global.addEventListener("resize", onResize);

    fetch(GEOJSON_URL).then(function (r) { return r.json(); }).then(function (gj) {
      geo = gj;
      fit(null);
      restyle();
    }).catch(function () {
      // Never leave a silent blank rectangle — say the geometry failed.
      var box = opts.legendEl
        ? (typeof opts.legendEl === "string" ? document.getElementById(opts.legendEl) : opts.legendEl)
        : null;
      if (box) box.textContent = "Province outlines could not be loaded; point markers are unaffected.";
    });

    return {
      setLayer: setLayer,
      select: select,
      refresh: restyle,
      focusProvince: focusProvince,
      resetView: resetView,
      getLayer: function () { return active; },
      getSelected: function () { return selected; },
      // Points the active layer asked for that the projection could not place.
      getOffscreenCount: function () { return offscreen; },
      getInvalidCount: function () { return invalidCount; }
    };
  }

  global.WTFMap = {
    create: create,
    ramp: ramp,
    PROVINCE_CODES: PROVINCE_CODES,
    NO_DATA: NO_DATA,
    CANADA_BOUNDS: CANADA_BOUNDS
  };
})(window);
