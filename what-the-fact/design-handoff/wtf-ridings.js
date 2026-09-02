/* Ridings. Boundaries, names and postal-code lookup come from the Represent
   API (OpenNorth), which is the standard open source for Canadian electoral
   geography and is CORS-enabled, so the page reads it directly.

   What this page deliberately does NOT do: claim which member represents a
   riding. The newsroom database joins parliament.mps.riding_name to do that;
   this project has no such mapping, and deriving one produced confident false
   claims about named MPs. So a riding here links INTO the member directory
   rather than asserting a name. */

(function () {
'use strict';
const API = 'https://represent.opennorth.ca';
const SET = 'federal-electoral-districts';
const $ = id => document.getElementById(id);
const esc = x => String(x == null ? '' : x).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

/* FED numbers encode the province in their first two digits — the only part of
   a riding's identity derivable without a lookup table. */
const FED_PROV = {
  10:'NL', 11:'PE', 12:'NS', 13:'NB', 24:'QC', 35:'ON',
  46:'MB', 47:'SK', 48:'AB', 59:'BC', 60:'YT', 61:'NT', 62:'NU'
};
const RD_PROV = { NL:'Newfoundland & Labrador', PE:'Prince Edward Island', NS:'Nova Scotia',
  NB:'New Brunswick', QC:'Qu\u00e9bec', ON:'Ontario', MB:'Manitoba', SK:'Saskatchewan',
  AB:'Alberta', BC:'British Columbia', YT:'Yukon', NT:'Northwest Territories', NU:'Nunavut' };
const provOf = id => FED_PROV[Math.floor(Number(id) / 1000)] || null;

let RIDINGS = [], centroids = {}, projection = null, canadaFeat = null, allFeat = null;
let S = { q: '', prov: '', selected: null };

const W = 1000, H = 480;
const svg = d3.select('#rd-map').append('svg')
  .attr('viewBox', '0 0 ' + W + ' ' + H)
  .attr('preserveAspectRatio', 'xMidYMid meet')
  .style('width', '100%').style('height', 'auto').style('display', 'block');
/* One transform group so land, boundary and centroids zoom together — zooming
   them separately would drift the dots off their own geography. */
const gZoom = svg.append('g');
const gLand = gZoom.append('g'), gShape = gZoom.append('g'), gPts = gZoom.append('g');

let zk = 1;
const zoom = d3.zoom().scaleExtent([1, 26])
  .on('zoom', ev => {
    zk = ev.transform.k;
    gZoom.attr('transform', ev.transform);
    /* Strokes and dots divide by the scale, so a riding outline stays a
       hairline at 20x instead of becoming a slab. */
    gZoom.selectAll('path').attr('stroke-width', function () {
      return (+this.getAttribute('data-sw') || 1) / zk;
    });
    gPts.selectAll('circle')
      .attr('r', d => (S.selected === d.id ? 5 : 2.6) / Math.sqrt(zk))
      .attr('stroke-width', 0.8 / zk);
  });
svg.call(zoom).on('dblclick.zoom', null);

function zoomBy(f) { svg.transition().duration(320).call(zoom.scaleBy, f); }
function zoomReset() { svg.transition().duration(520).call(zoom.transform, d3.zoomIdentity); }
window.zoomBy = zoomBy;
window.zoomReset = zoomReset;

/* Fly to a feature: fit its projected bounds into the frame with padding, so a
   selected riding is legible rather than a speck. */
function zoomTo(geo) {
  if (!projection || !geo) return;
  const [[x0, y0], [x1, y1]] = d3.geoPath(projection).bounds(geo);
  const w = Math.max(x1 - x0, 8), h = Math.max(y1 - y0, 8);
  const k = Math.min(22, 0.72 / Math.max(w / W, h / H));
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  svg.transition().duration(760).ease(d3.easeCubicInOut)
    .call(zoom.transform, d3.zoomIdentity.translate(W / 2, H / 2).scale(k).translate(-cx, -cy));
}

/* ── base geography ──────────────────────────────────────────────────── */
d3.json('https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json').then(topo => {
  allFeat = topojson.feature(topo, topo.objects.countries);
  canadaFeat = allFeat.features.find(f => f.id === '124');
  projection = d3.geoConicConformal().parallels([49, 77]).rotate([96, 0])
    .fitExtent([[26, 20], [W - 26, H - 28]], canadaFeat);
  const path = d3.geoPath(projection);
  gLand.append('g').selectAll('path').data(allFeat.features.filter(f => f.id !== '124'))
    .join('path').attr('d', path).attr('fill', '#0f151e').attr('stroke', '#1a2230')
    .attr('data-sw', .6).attr('stroke-width', .6);
  gLand.append('path').datum(canadaFeat).attr('d', path)
    .attr('fill', '#161f2d').attr('stroke', '#31405a')
    .attr('data-sw', 1).attr('stroke-width', 1);
  drawPoints();
}).catch(() => {
  $('rd-map').insertAdjacentHTML('afterbegin',
    '<div class="rd-note" style="padding:38px;text-align:center">Base geography could not be loaded.</div>');
});

/* ── riding list + centroids ─────────────────────────────────────────── */
async function load() {
  try {
    const [list, cent] = await Promise.all([
      fetch(API + '/boundaries/' + SET + '/?limit=400').then(r => r.json()),
      fetch(API + '/boundaries/' + SET + '/centroid?limit=400').then(r => r.json())
    ]);
    /* The centroid endpoint keys on name, not external_id — the two list
       shapes differ, so join on the name. */
    (cent.objects || []).forEach(o => {
      if (o.centroid && o.centroid.coordinates) centroids[o.name] = o.centroid.coordinates;
    });
    RIDINGS = (list.objects || []).map(o => ({
      id: o.external_id, name: o.name, url: o.url,
      prov: provOf(o.external_id), xy: centroids[o.name] || null
    })).sort((a, b) => a.name.localeCompare(b.name, 'en'));
    const plotted = RIDINGS.filter(r => r.xy).length;
    $('rd-status').textContent = RIDINGS.length + ' ridings loaded \u00b7 ' + plotted + ' plotted';
    buildProvFilter();
    render();
    drawPoints();
  } catch (e) {
    $('rd-status').textContent = 'Represent API unavailable';
    $('rd-list').innerHTML = '<div class="rd-none">Riding names and boundaries come from the Represent API, ' +
      'which could not be reached. On the live site this data is read from the newsroom database instead, ' +
      'so this page does not depend on a third-party service being up.</div>';
    $('rd-stats').innerHTML = '';
  }
}

function buildProvFilter() {
  const counts = {};
  RIDINGS.forEach(r => { if (r.prov) counts[r.prov] = (counts[r.prov] || 0) + 1; });
  const order = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
  $('rd-prov').innerHTML = '<option value="">Every province</option>' +
    order.map(p => '<option value="' + p + '">' + (RD_PROV[p] || p) + ' (' + counts[p] + ')</option>').join('');
  $('rd-stats').innerHTML = [
    [String(RIDINGS.length), 'Ridings'],
    [String(order.length), 'Provinces & territories'],
    [String(counts.ON || 0), 'Ontario seats'],
    [String(counts.QC || 0), 'Qu\u00e9bec seats']
  ].map(([n, l]) => '<div class="stat"><div class="stat-n">' + n + '</div><div class="stat-l">' + l + '</div></div>').join('');
}

/* ── map ─────────────────────────────────────────────────────────────── */
function drawPoints() {
  if (!projection || !RIDINGS.length) return;
  const vis = new Set(visible().map(r => r.id));
  const rows = RIDINGS.filter(r => r.xy && vis.has(r.id));
  gPts.selectAll('circle').data(rows, d => d.id)
    .join(enter => enter.append('circle')
        .attr('r', 0).style('cursor', 'pointer')
        .on('mouseenter', (e, d) => showTip(e, d))
        .on('mousemove', (e, d) => showTip(e, d))
        .on('mouseleave', () => { $('rd-tip').style.display = 'none'; })
        .on('click', (e, d) => select(d.id)))
    .attr('cx', d => projection(d.xy)[0])
    .attr('cy', d => projection(d.xy)[1])
    .attr('fill', d => S.selected === d.id ? 'var(--wtf-accent)' : '#7fa3cf')
    .attr('fill-opacity', d => S.selected === d.id ? 1 : .5)
    .attr('stroke', d => S.selected === d.id ? '#fff' : 'none')
    .attr('stroke-width', 0.8 / zk)
    .transition().duration(300)
    .attr('r', d => (S.selected === d.id ? 5 : 2.6) / Math.sqrt(zk));
}

function showTip(e, d) {
  const t = $('rd-tip');
  t.innerHTML = '<b>' + esc(d.name) + '</b><em>' + (RD_PROV[d.prov] || '') + ' \u00b7 FED ' + d.id + '</em>';
  t.style.display = 'block';
  t.style.left = Math.min(e.clientX + 14, innerWidth - 230) + 'px';
  t.style.top = Math.max(8, e.clientY - 46) + 'px';
}

/* Draw the boundary and fly to it BEFORE the data panel appears, so the reader
   sees where the riding is before being told about it. */
async function select(id) {
  S.selected = S.selected === id ? null : id;
  render(); drawPoints();
  gShape.selectAll('*').remove();
  if (!S.selected) { $('rd-detail').innerHTML = ''; zoomReset(); return; }
  const r = RIDINGS.find(x => x.id === S.selected);
  if (r && r.xy && projection) {
    /* Provisional fly to the centroid so motion starts immediately, rather
       than after the boundary request returns. */
    const p = projection(r.xy);
    svg.transition().duration(420).ease(d3.easeCubicOut)
      .call(zoom.transform, d3.zoomIdentity.translate(W / 2, H / 2).scale(7).translate(-p[0], -p[1]));
  }
  $('rd-detail').innerHTML = '<div class="rd-dt"><div class="rd-dt-h"><span class="rd-dt-n">' + esc(r.name) + '</span>' +
    '<span class="rd-chip">FED ' + r.id + '</span>' +
    '<span class="rd-chip">' + esc(RD_PROV[r.prov] || r.prov || '') + '</span>' +
    '<button class="rd-x" onclick="select(null)">Close</button></div>' +
    '<div class="rd-note" id="rd-shape-status">Loading boundary\u2026</div></div>';
  try {
    const j = await fetch(API + r.url + 'simple_shape').then(x => x.json());
    if (!projection || !j || !j.coordinates) throw new Error('no geometry');
    gShape.append('path').datum(j).attr('d', d3.geoPath(projection))
      .attr('fill', 'var(--wtf-accent)').attr('fill-opacity', .22)
      .attr('stroke', 'var(--wtf-accent)')
      .attr('data-sw', 1.2).attr('stroke-width', 1.2 / zk);
    zoomTo(j);
    const b = d3.geoBounds(j);
    $('rd-detail').querySelector('.rd-dt').insertAdjacentHTML('beforeend', boundaryPanel(r, b));
    const st = $('rd-shape-status'); if (st) st.remove();
  } catch (e) {
    const st = $('rd-shape-status');
    if (st) st.textContent = 'Boundary geometry unavailable for this riding.';
  }
}
window.select = select;

function boundaryPanel(r, b) {
  const [[w, s], [e, n]] = b;
  const kmWide = Math.round(Math.abs(e - w) * 111 * Math.cos((s + n) / 2 * Math.PI / 180));
  const kmTall = Math.round(Math.abs(n - s) * 111);
  return '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:12px">' +
    [['Extent', kmWide.toLocaleString() + ' \u00d7 ' + kmTall.toLocaleString() + ' km', 'bounding box, not area'],
     ['Centre', r.xy ? r.xy[1].toFixed(2) + '\u00b0N, ' + Math.abs(r.xy[0]).toFixed(2) + '\u00b0W' : '\u2014', 'geometric centroid'],
     ['FED number', r.id, 'Elections Canada identifier']]
    .map(([l, v, d]) => '<div style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);border-radius:8px;padding:11px 12px">' +
      '<div style="font-family:var(--wtf-font-mono);font-size:13px;color:var(--wtf-text)">' + v + '</div>' +
      '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-top:4px">' + l + '</div>' +
      '<div style="font-size:11px;color:var(--wtf-text-muted);margin-top:4px">' + d + '</div></div>').join('') +
    '</div>' +
    '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
      '<a class="rd-chip" style="text-decoration:none" href="wtf-archive.html#prov=' + (r.prov || '') + '">' +
        (r.prov ? 'Coverage from ' + esc(RD_PROV[r.prov] || r.prov) : 'Full archive') + ' &rarr;</a>' +
      '<a class="rd-chip" style="text-decoration:none" target="_blank" rel="noopener" href="https://www.elections.ca/Scripts/vis/Map?L=e&ED=' + r.id + '">Elections Canada map &#8599;</a>' +
    '</div>' +
    '<div class="rd-note" style="margin-top:10px">Coverage is tagged to a province, not to a riding &mdash; so that link gives ' +
    (r.prov ? esc(RD_PROV[r.prov] || r.prov) : 'the province') + ', not this district. ' +
    'There is no member lookup here either: the riding-to-member join lives in the newsroom database, and guessing it from geography would put a real person in the wrong seat.</div>';
}

/* ── postal lookup ───────────────────────────────────────────────────── */
async function lookup() {
  const raw = $('rd-postal').value.replace(/\s+/g, '').toUpperCase();
  const out = $('rd-postal-out');
  if (!/^[A-Z]\d[A-Z]\d[A-Z]\d$/.test(raw)) {
    out.className = 'rd-pc rd-pc--bad';
    out.innerHTML = 'That is not a full six-character postal code. A forward sortation area alone (the first three) can span several ridings, so the lookup needs all six.';
    return;
  }
  out.className = 'rd-pc';
  out.innerHTML = 'Looking up\u2026';
  try {
    const j = await fetch(API + '/postcodes/' + raw + '/').then(r => r.json());
    /* Pin on the set slug, never the display name. Represent interleaves
       PROVINCIAL sets ("Alberta electoral district") and superseded federal
       representation orders (2003 / 2013 / 2023) in the same array, all of
       which contain the word "electoral" — matching on the name reported
       Calgary-Buffalo, an Alberta provincial riding, as a federal one. The slug
       guarantees federal AND the current order, which also guarantees the name
       exists in RIDINGS so "Show on the map" always resolves. */
    const all = j.boundaries_centroid || [];
    const fed = all.find(b => (b.url || '').startsWith('/boundaries/' + SET + '/'));
    if (!fed) {
      out.className = 'rd-pc rd-pc--bad';
      out.innerHTML = all.length
        ? 'Found ' + esc(raw) + ' but no federal riding in the current representation order covers it. ' +
          'That usually means the boundary set is mid-update rather than that the code is invalid.'
        : 'No riding found for ' + esc(raw) + '. The code may be new, retired, or a business-only code the boundary set does not cover.';
      return;
    }
    const match = RIDINGS.find(r => r.name === fed.name);
    /* The API returns a bare two-letter code, which is not a place name. */
    const provName = RD_PROV[j.province] || j.province || '';
    out.className = 'rd-pc rd-pc--ok';
    out.innerHTML = '<div style="font-family:var(--wtf-font-mono);font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:var(--wtf-established);margin-bottom:6px">Your riding</div>' +
      '<div style="font-family:var(--wtf-font-serif);font-size:22px;font-weight:600;letter-spacing:-.018em">' + esc(fed.name) + '</div>' +
      '<div style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-text-muted);margin-top:4px">' +
        esc(j.city || '') + ', ' + esc(provName) + ' \u00b7 ' + raw + '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">' +
        (match ? '<button class="rd-chip" style="cursor:pointer" onclick="select(\'' + match.id + '\')">Show on the map</button>' : '') +
        '<a class="rd-chip" style="text-decoration:none" href="wtf-archive.html#prov=' + esc(j.province || '') + '">Coverage from ' + esc(provName) + ' &rarr;</a>' +
      '</div>' +
      '<div class="rd-note" style="margin-top:10px">Matched on the postal code\u2019s centroid. A code straddling a boundary is assigned to whichever riding contains its centre point, so a handful of addresses near an edge will resolve to the neighbouring riding.</div>';
    if (match) { S.q = ''; $('rd-q').value = ''; render(); drawPoints(); }
  } catch (e) {
    out.className = 'rd-pc rd-pc--bad';
    out.innerHTML = 'Could not look up ' + esc(raw) + '. The Represent API did not respond — this is a network failure, not a verdict on the postal code.';
  }
}
window.lookup = lookup;
$('rd-postal').addEventListener('keydown', e => { if (e.key === 'Enter') lookup(); });

/* ── directory ───────────────────────────────────────────────────────── */
function visible() {
  const q = S.q.trim().toLowerCase();
  return RIDINGS.filter(r =>
    (!S.prov || r.prov === S.prov) &&
    (!q || r.name.toLowerCase().includes(q) || String(r.id).includes(q)));
}

function render() {
  const list = visible();
  $('rd-count').textContent = list.length + ' of ' + RIDINGS.length + ' ridings';
  if (!list.length) {
    $('rd-list').innerHTML = '<div class="rd-none">No riding matches. Riding names carry hyphens and accents as Elections Canada spells them &mdash; try a single word.</div>';
    $('rd-az').innerHTML = '';
    return;
  }
  /* Grouped A–Z: 338 rows in one run is unreadable, and the alphabet rail is
     the only practical way to reach the middle of the list. */
  const by = {};
  list.forEach(r => {
    const k = r.name[0].toUpperCase().normalize('NFD')[0];
    (by[k] = by[k] || []).push(r);
  });
  const keys = Object.keys(by).sort();
  $('rd-az').innerHTML = keys.map(k =>
    '<a href="#rd-g-' + k + '" class="rd-az-l">' + k + '</a>').join('');
  $('rd-list').innerHTML = keys.map(k =>
    '<div class="rd-grp" id="rd-g-' + k + '">' +
      '<div class="rd-grp-h">' + k + ' <span>' + by[k].length + '</span></div>' +
      '<div class="rd-grid">' + by[k].map(r =>
        '<button class="rd-card' + (S.selected === r.id ? ' on' : '') + '" onclick="select(\'' + r.id + '\')">' +
          '<span class="rd-card-n">' + esc(r.name) + '</span>' +
          '<span class="rd-card-m">' + (r.prov || '\u2014') + ' \u00b7 ' + r.id + '</span>' +
        '</button>').join('') +
      '</div></div>').join('');
}

$('rd-q').addEventListener('input', e => { S.q = e.target.value; render(); drawPoints(); });
$('rd-prov').addEventListener('change', e => { S.prov = e.target.value; render(); drawPoints(); });

/* Seat counts per province, so the tab answers “how many seats does Alberta
   have” before anyone types a search. */
function drawProvSummary() {
  const host = $('rd-provbars');
  if (!host) return;
  if (!RIDINGS.length) { host.innerHTML = '<p class="rd-note">Seat counts appear once the riding list has loaded.</p>'; return; }
  const by = {};
  RIDINGS.forEach(r => { if (r.prov) by[r.prov] = (by[r.prov] || 0) + 1; });
  const rows = Object.keys(by).sort((a, b) => by[b] - by[a]);
  const max = Math.max.apply(null, rows.map(p => by[p]));
  const tot = rows.reduce((n, p) => n + by[p], 0);
  host.innerHTML = rows.map(p =>
    '<button class="rd-provbar" data-p="' + p + '">' +
      '<span class="rd-provbar-n">' + esc(RD_PROV[p] || p) + '</span>' +
      '<span class="rd-provbar-t"><i style="width:' + Math.round(by[p] / max * 100) + '%"></i></span>' +
      '<span class="rd-provbar-v">' + by[p] + '</span></button>').join('') +
    '<p class="rd-note" style="margin-top:9px">' + tot + ' seats across ' + rows.length +
    ' provinces and territories. Seats follow population with a floor, which is why the three territories hold one each.</p>';
  host.querySelectorAll('.rd-provbar').forEach(b => b.addEventListener('click', () => {
    S.prov = S.prov === b.dataset.p ? '' : b.dataset.p;
    const sel = $('rd-prov'); if (sel) sel.value = S.prov;
    host.querySelectorAll('.rd-provbar').forEach(x => x.classList.toggle('on', x.dataset.p === S.prov));
    render();
  }));
}

let started = false;
function initRidings() {
  if (started) return; started = true;
  load().then(() => {
    /* The province summary counts RIDINGS, so it can only draw once the fetch
       has resolved — drawn earlier it read "0 seats across 0 provinces". */
    drawProvSummary();
    /* A race hands over a riding NAME, so match on name and select it \u2014 the
       reader arrives already looking at the district they asked about. */
    const want = new URLSearchParams(location.search).get('rd');
    if (!want) return;
    const hit = RIDINGS.find(x => x.name === want) ||
                RIDINGS.find(x => x.name.toLowerCase() === want.toLowerCase());
    if (hit) { select(hit.id); }
    else {
      const out = $('rd-postal-out');
      if (out) {
        out.className = 'rd-pc rd-pc--bad';
        out.innerHTML = 'No riding named &ldquo;' + esc(want) + '&rdquo; in the current representation order. ' +
          'The name may have changed in the 2023 redistribution.';
      }
    }
  });
}
window.initRidings = initRidings;
/* Standalone page, or a deep link (#ridings) already applied by wtf-mps.js
   before this file finished loading \u2014 either way the pane is showing and
   must initialise now rather than wait for a click that already happened. */
const ridPane = document.getElementById('pane-ridings');
if (!ridPane || ridPane.classList.contains('on')) initRidings();
})();
