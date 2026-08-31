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
 * WHAT IT OWNS (the genuinely shared part)
 *   - a bounded Canada map with a designed ground and NO third-party tiles
 *   - the province choropleth, driven by a per-layer metric function
 *   - the legend, DERIVED from the active layer's ramp so the two cannot drift
 *   - "no data" rendered as visibly different from a low value
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
 */
(function (global) {
  "use strict";

  var GEOJSON_URL = "/static/canada-provinces.geojson";
  var NO_DATA = "#1b2430";

  // Canada, with enough slack to pan a little without revealing empty space.
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

  /** First stop whose threshold >= v. Stops are [threshold, colour, label]. */
  function ramp(stops, v) {
    for (var i = 0; i < stops.length; i++) if (v <= stops[i][0]) return stops[i][1];
    return stops[stops.length - 1][1];
  }

  function create(opts) {
    var el = typeof opts.el === "string" ? document.getElementById(opts.el) : opts.el;
    if (!el) return null;
    if (!global.L) { el.textContent = "Map library failed to load."; return null; }

    var layers = opts.layers || [];
    var active = opts.active || (layers[0] && layers[0].id);
    var selected = null;
    var provLayer = null;

    var map = L.map(el, {
      center: opts.center || [62, -96],
      zoom: opts.zoom || 3,
      minZoom: opts.minZoom || 3,
      maxZoom: opts.maxZoom || 7,
      zoomControl: opts.zoomControl !== false,
      scrollWheelZoom: false,
      maxBounds: L.latLngBounds(opts.bounds || CANADA_BOUNDS),
      maxBoundsViscosity: 0.85,
      // No third-party tiles anywhere, so there is nothing to attribute. The
      // province geometry IS the geography this site maps.
      attributionControl: false
    });
    map.createPane("provPane"); map.getPane("provPane").style.zIndex = 400;
    map.createPane("ptPane");   map.getPane("ptPane").style.zIndex = 500;
    var ptLayer = L.layerGroup([], { pane: "ptPane" }).addTo(map);

    function layerDef(id) {
      for (var i = 0; i < layers.length; i++) if (layers[i].id === id) return layers[i];
      return null;
    }

    function styleFor(feature) {
      var def = layerDef(active);
      var code = PROVINCE_CODES[feature.properties && feature.properties.name];
      var m = (def && def.metric && code) ? def.metric(code) : null;
      var isSel = selected && code === selected;
      // RULE 1 — absence is dimmed AND dashed, never a darker fill.
      return {
        fillColor: m ? m.col : NO_DATA,
        fillOpacity: m ? (isSel ? 1 : 0.92) : 0.45,
        color: isSel ? "#e6edf6" : "#0b1220",
        weight: isSel ? 2.2 : 0.8,
        dashArray: m ? null : "3,3"
      };
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
    }

    function drawPoints() {
      ptLayer.clearLayers();
      var def = layerDef(active);
      if (!def || !def.points) return;
      def.points(selected).forEach(function (p) {
        if (p.lat === null || p.lat === undefined || p.lon === null || p.lon === undefined) return;
        var m = L.circleMarker([p.lat, p.lon], {
          pane: "ptPane",
          radius: p.r === undefined ? 5 : p.r,
          fillColor: p.col || NO_DATA,
          fillOpacity: p.faded ? 0.35 : 0.9,
          color: p.faded ? "#6b7280" : "#020617",
          weight: p.faded ? 1.5 : 1,
          dashArray: p.faded ? "2,2" : null
        });
        if (p.tip) m.bindTooltip(p.tip, { sticky: true });
        ptLayer.addLayer(m);
      });
    }

    function restyle() {
      if (provLayer) provLayer.setStyle(styleFor);
      drawPoints();
      drawLegend();
    }

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

    fetch(GEOJSON_URL).then(function (r) { return r.json(); }).then(function (gj) {
      provLayer = L.geoJSON(gj, {
        pane: "provPane",
        style: styleFor,
        onEachFeature: function (f, lyr) {
          var code = PROVINCE_CODES[f.properties && f.properties.name];
          var def = layerDef(active);
          if (def && def.tooltip && code) lyr.bindTooltip(def.tooltip(code), { sticky: true });
          lyr.on("click", function () { select(code === selected ? null : code); });
          lyr.on("mouseover", function () { lyr.setStyle({ weight: 2.2, color: "#e6edf6" }); });
          lyr.on("mouseout", function () {
            if (provLayer) provLayer.resetStyle(lyr);
            if (selected) restyle();
          });
        }
      }).addTo(map);
      restyle();
    }).catch(function () {
      // Never leave a silent blank rectangle — say the geometry failed.
      var box = opts.legendEl
        ? (typeof opts.legendEl === "string" ? document.getElementById(opts.legendEl) : opts.legendEl)
        : null;
      if (box) box.textContent = "Province outlines could not be loaded; point markers are unaffected.";
      drawPoints();
    });

    return {
      map: map,
      setLayer: setLayer,
      select: select,
      refresh: restyle,
      getLayer: function () { return active; },
      getSelected: function () { return selected; }
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
