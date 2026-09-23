/* PR 02 — homepage map on the shared WTFMap component.
 *
 * Paste this over index.html's map code: from the line
 *     var map = L.map("wtf-canada-map", {
 * down to (NOT including) the line
 *     var BEAT_CONFIG = {
 * Everything in that span is Leaflet plumbing. The helpers this file relies on
 * are all defined ABOVE that span and stay untouched: _leanToken, BIAS_COLOURS,
 * VERDICT_COLOURS, ICO, esc, escAttr, buildActivityItem, loadAgentActivity is
 * inside the span and is re-declared below unchanged.
 *
 * Data: the same two endpoints the Leaflet map already read —
 *   /api/proxy/map-data?beat=        → provinces{PC:{articles, avg_bias, dominant_outlet}}
 *   /api/proxy/articles/geo?beat=&scope=&province=  → province_counts, articles
 * Nothing is derived. A province missing from the payload renders as no-data.
 */

var mapMode = 'canada';
var currentBeat = 'all';
var currentProvince = null;
var IS_SUBSCRIBER = {{ is_subscriber | tojson }};
var mapProvinces = {};     // map-data payload, keyed by province code
var geoCounts = {};        // articles/geo province_counts (canada) or country counts (world)
var wtfmap = null;

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
function escAttr(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}

/* buildActivityItem / loadAgentActivity / timeAgo — unchanged from the
   Leaflet version; copy them across verbatim from the old span. */

// ── lean helpers: unchanged, still one source of truth ────────────────────
var LEAN_MIN_N = 20;
var LEAN_ANCHOR = -0.028;
var LEAN_SPREAD = 0.06;
function _rgb(hex) {
  var h = (hex || "").trim().replace("#", "");
  if (h.length !== 6) return null;
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
var _LEAN_NEUTRAL = _rgb(BIAS_COLOURS["center"]);
var _LEAN_L       = _rgb(BIAS_COLOURS["left"]);
var _LEAN_R       = _rgb(BIAS_COLOURS["right"]);
function leanIsSufficient(avgScore, count) {
  return !(avgScore === null || avgScore === undefined || count < LEAN_MIN_N);
}
function leanColour(avgScore, count) {
  if (!leanIsSufficient(avgScore, count)) return null;   // component draws no-data
  var t = Math.max(-1, Math.min(1, (avgScore - LEAN_ANCHOR) / LEAN_SPREAD));
  var k = Math.abs(t), pole = t < 0 ? _LEAN_L : _LEAN_R;
  return "rgb(" + [0,1,2].map(function(i){
    return Math.round(_LEAN_NEUTRAL[i] + k * (pole[i] - _LEAN_NEUTRAL[i]));
  }).join(",") + ")";
}
function leanLabel(avgScore, count) {
  if (!leanIsSufficient(avgScore, count)) return " · lean: not measured (<" + LEAN_MIN_N + " articles)";
  var d = avgScore - LEAN_ANCHOR;
  if (d < -0.015) return " · coverage leans left";
  if (d > 0.015) return " · coverage leans right";
  return " · balanced coverage";
}

// ── volume: neutral slate, accent on the single highest value only ────────
// Handoff correction #2: a magnitude colour must never read as a lean colour.
var ACCENT = _leanToken("--wtf-accent") || "#dc2626";
var VOL_SHADES = ["#2a3342", "#465163", "#6b7686", "#929aa5"];
function provCount(pc) {
  var d = geoCounts[pc];
  if (d === undefined || d === null) return null;
  return typeof d === 'object' ? d.count : d;
}
function volMax() {
  var m = 0;
  Object.keys(geoCounts).forEach(function(pc){ var c = provCount(pc) || 0; if (c > m) m = c; });
  return m;
}
function volColour(c, max) {
  if (!c) return null;
  if (c === max) return ACCENT;
  var i = Math.min(3, Math.floor((c / max) * 4));
  return VOL_SHADES[i];
}
function volRamp() {
  var max = volMax() || 1;
  var q = function(f){ return Math.max(1, Math.round(max * f)); };
  return [
    [q(.25), VOL_SHADES[0], "≤ " + q(.25).toLocaleString()],
    [q(.5),  VOL_SHADES[1], "≤ " + q(.5).toLocaleString()],
    [q(.75), VOL_SHADES[2], "≤ " + q(.75).toLocaleString()],
    [max - 1, VOL_SHADES[3], "< " + max.toLocaleString()],
    [max,    ACCENT,        "highest · " + max.toLocaleString()]
  ];
}

function provName(pc) {
  return (PROVINCE_LIST.find(function(p){ return p.code === pc; }) || {}).name || pc;
}

var LAYERS = [
  { id: 'lean',
    metric: function(pc) {
      var pd = mapProvinces[pc];
      var col = pd ? leanColour(pd.avg_bias, pd.articles) : null;
      return col ? { col: col } : null;
    },
    tooltip: function(pc) {
      var pd = mapProvinces[pc];
      if (!pd) return provName(pc) + " · no stories in this window";
      return provName(pc) + " · " + pd.articles + " stories" + leanLabel(pd.avg_bias, pd.articles) +
             (pd.dominant_outlet ? " · top: " + pd.dominant_outlet : "");
    },
    ramp: [[-1, BIAS_COLOURS.left, "coverage leans left"],
           [0,  BIAS_COLOURS.center, "balanced"],
           [1,  BIAS_COLOURS.right, "coverage leans right"]],
    noDataLabel: "not measured (<" + LEAN_MIN_N + " articles)",
    coverageNote: function(){ return "Colour is the average lean of coverage in each province, scored per story. It is not a label on the province."; }
  },
  { id: 'volume',
    metric: function(pc) {
      var c = provCount(pc), col = volColour(c, volMax());
      return col ? { col: col } : null;
    },
    tooltip: function(pc) {
      var c = provCount(pc);
      return provName(pc) + " · " + (c ? c.toLocaleString() + " stories" : "no stories in this window");
    },
    ramp: volRamp(),
    noDataLabel: "no stories in this window",
    coverageNote: function(){ return "Volume is not importance — a province with more stories has more outlets in it."; }
  }
];

function setMapLayer(id) {
  if (!wtfmap) return;
  if (id === 'volume') LAYERS[1].ramp = volRamp();
  wtfmap.setLayer(id);
  document.getElementById('btn-lean').classList.toggle('active', id === 'lean');
  document.getElementById('btn-volume').classList.toggle('active', id === 'volume');
}

function initMap() {
  wtfmap = WTFMap.create({
    el: "wtf-canada-map",
    legendEl: "wtf-home-map-legend",
    layers: LAYERS,
    active: 'lean',
    onSelect: function(pc) {
      if (pc) setProvince(pc, true); else clearProvince(true);
    }
  });
}

function loadMapData() {
  if (mapMode === 'world') return;
  fetch("/api/proxy/map-data?beat=" + encodeURIComponent(currentBeat))
    .then(function(r){ return r.json(); })
    .then(function(data) {
      mapProvinces = data.provinces || {};
      if (wtfmap) wtfmap.refresh();
    })
    .catch(function(e){ console.warn("WTF map load failed:", e); });
}

// Ranked sidebar — unchanged behaviour, colours now from the active layer.
function renderMapIndex(rows, mode) {
  var list = document.getElementById('wtf-map-index-list');
  if (!list) return;
  rows.sort(function(a, b) { return b.count - a.count; });
  while (list.firstChild) list.removeChild(list.firstChild);
  if (!rows.length) {
    var empty = document.createElement('div');
    empty.className = 'wtf-map-index-empty';
    empty.textContent = 'No data for this view.';
    list.appendChild(empty);
    return;
  }
  rows.forEach(function(r, i) {
    var row = document.createElement('div');
    row.className = 'wtf-map-index-row' + (r.code === currentProvince ? ' is-active' : '');
    var sw = document.createElement('i');
    sw.className = 'wtf-map-index-swatch' + (r.colour ? '' : ' is-nodata');
    if (r.colour) sw.style.background = r.colour;
    var rank = document.createElement('b');
    rank.className = 'wtf-map-index-rank';
    rank.textContent = '#' + (i + 1);
    var name = document.createElement('span');
    name.className = 'wtf-map-index-name';
    name.textContent = r.name;
    var count = document.createElement('span');
    count.className = 'wtf-map-index-count';
    count.textContent = r.count.toLocaleString();
    row.appendChild(sw); row.appendChild(rank); row.appendChild(name); row.appendChild(count);
    row.addEventListener('click', function() {
      if (mode === 'canada') setProvince(r.code === currentProvince ? null : r.code);
      else loadArticleFeed_country(r.code);
    });
    list.appendChild(row);
  });
}

function loadArticlesGeo() {
  var scope = mapMode === 'world' ? 'world' : 'canada';
  var url = "/api/proxy/articles/geo?beat=" + encodeURIComponent(currentBeat) + "&scope=" + scope;
  if (scope === 'canada' && currentProvince) url += "&province=" + encodeURIComponent(currentProvince);
  fetch(url)
    .then(function(r){ return r.json(); })
    .then(function(data) {
      geoCounts = data.province_counts || {};
      if (scope === 'world') {
        renderMapIndex(Object.keys(geoCounts).map(function(cc) {
          var cd = geoCounts[cc] || {};
          return { code: cc, name: cc, count: cd.count || 0,
                   colour: BIAS_COLOURS[cd.band] || null };
        }), 'world');
        return;
      }
      LAYERS[1].ramp = volRamp();
      var layer = wtfmap ? wtfmap.getLayer() : 'lean';
      var max = volMax();
      renderMapIndex(Object.keys(geoCounts).map(function(pc) {
        var c = provCount(pc) || 0;
        var pd = mapProvinces[pc];
        var colour = layer === 'volume' ? volColour(c, max)
                   : (pd ? leanColour(pd.avg_bias, pd.articles) : null);
        return { code: pc, name: provName(pc), count: c, colour: colour };
      }), 'canada');
      if (wtfmap) wtfmap.refresh();
    })
    .catch(function(e){ console.warn("WTF geo load failed:", e); });
}

function setMapMode(mode) {
  mapMode = mode;
  document.getElementById('btn-canada').className = 'wtf-map-btn' + (mode === 'canada' ? ' active' : '');
  document.getElementById('btn-world').className = 'wtf-map-btn' + (mode === 'world' ? ' active' : '');
  document.getElementById('wtf-map-label').textContent =
    mode === 'canada' ? 'LIVE — CANADA NEWS MAP' : 'LIVE — WORLD COVERAGE';
  // The component projects Canada only (Lambert conic). Until PR 03 adds a
  // world projection, World shows the ranked index + feed and SAYS so, rather
  // than drawing countries off a Canada projection and clipping them silently.
  var host = document.getElementById('wtf-canada-map');
  var note = document.getElementById('wtf-world-note');
  var layerBtns = document.getElementById('wtf-map-layer-toggle');
  host.hidden = mode === 'world';
  note.hidden = mode !== 'world';
  layerBtns.hidden = mode === 'world';
  document.getElementById('wtf-home-map-legend').hidden = mode === 'world';
  if (mode === 'canada') { loadMapData(); }
  else if (currentProvince) { clearProvince(); return; }
  loadArticlesGeo();
  loadArticleFeed();
}

function loadArticleFeed_country(cc) {
  var url = '/api/v1/articles?limit=15&country=' + encodeURIComponent(cc);
  if (currentBeat && currentBeat !== 'all') url += '&beat=' + encodeURIComponent(currentBeat);
  var container = document.getElementById('wtf-feed-articles');
  if (!container) return;
  container.innerHTML = '<div style="color:#555;font-size:11px;padding:8px 0;">Loading ' + esc(cc) + ' articles...</div>';
  fetch(url)
    .then(function(r){ return r.json(); })
    .then(function(data) {
      var articles = data.articles || [];
      if (!articles.length) { container.innerHTML = '<div style="color:#555;font-size:11px;padding:8px 0;">No articles for ' + esc(cc) + '.</div>'; return; }
      container.innerHTML = articles.map(function(a) {
        var band = ((a.bias && a.bias.band) || 'center').replace(/ /g,'-');
        var src = (a.source && a.source.name) ? esc(a.source.name) : '';
        var ago = a.published_at ? ' &middot; <span style="color:#6b7280;">' + esc(timeAgo(a.published_at)) + '</span>' : '';
        return '<div class="wtf-article-card wtf-article-card--' + esc(band) + '">' +
          '<div class="wtf-card-meta"><span>' + src + ' &middot; ' + esc(cc) + ago + '</span>' +
          '<span class="wtf-bias-pill wtf-bias-' + esc(band) + '">' + esc(band.toUpperCase()) + '</span></div>' +
          '<a class="wtf-card-title" href="/article/' + parseInt(a.id) + '">' + esc(a.title) + '</a></div>';
      }).join('');
    })
    .catch(function(e){ console.warn('Country feed failed:', e); });
}

initMap();
loadMapData();
loadAgentActivity();
loadArticlesGeo();
setInterval(loadMapData, 1800000);
setInterval(loadAgentActivity, 60000);
setInterval(loadArticlesGeo, 1800000);
