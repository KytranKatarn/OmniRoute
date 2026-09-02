/* Elections. Federal and provincial figures are the published results and the
   fixed-date statutes; municipal dates come from each province's own local
   elections act. The city list is the newsroom's reporting list, imported
   verbatim so the calendar and the coverage claim cannot disagree. */

(function () {
'use strict';


const PARTY_COL = { Liberal:'#d71920', Conservative:'#1a4782', Bloc:'#33b2cc',
  NDP:'#f58220', Green:'#3d9b35', Independent:'#9ca3af',
  CAQ:'#00a0d2', PQ:'#004a8f', QS:'#ff5605', PLQ:'#d71920',
  'BC NDP':'#f58220', 'BC Conservative':'#1a4782', UCP:'#1a4782', 'AB NDP':'#f58220',
  'Sask Party':'#1a4782', PC:'#1a4782', OLP:'#d71920', 'ON NDP':'#f58220',
  'Consensus':'#9ca3af' };

/* 45th general election, seats and popular vote. */
const FED_RESULT = [
  { p:'Liberal',      seats:171, votes:43.8 },
  { p:'Conservative', seats:139, votes:41.3 },
  { p:'Bloc',         seats:21,  votes:6.3 },
  { p:'NDP',          seats:5,   votes:6.4 },
  { p:'Green',        seats:1,   votes:1.2 },
  { p:'Independent',  seats:6,   votes:1.0 }
];
const FED_NEXT = { date:'2029-10-15', law:'Canada Elections Act s.56.1 \u2014 third Monday of October in the fourth year' };

/* Every legislature with its fixed date. Seat counts are the real chamber
   sizes; the date is a legal deadline, not a forecast. */
const PROVS = [
  { c:'QC', n:'Qu\u00e9bec',                   seats:125, next:'2026-10-05', last:'2022-10-03', gov:'CAQ',            premier:'Fran\u00e7ois Legault' },
  { c:'AB', n:'Alberta',                  seats:87,  next:'2027-10-18', last:'2023-05-29', gov:'UCP',            premier:'Danielle Smith' },
  { c:'MB', n:'Manitoba',                 seats:57,  next:'2027-10-05', last:'2023-10-03', gov:'NDP',            premier:'Wab Kinew' },
  { c:'PE', n:'Prince Edward Island',     seats:27,  next:'2027-10-04', last:'2023-04-03', gov:'PC',             premier:'Rob Lantz' },
  { c:'NT', n:'Northwest Territories',    seats:19,  next:'2027-11-15', last:'2023-11-14', gov:'Consensus',      premier:'R.J. Simpson' },
  { c:'BC', n:'British Columbia',         seats:93,  next:'2028-10-21', last:'2024-10-19', gov:'BC NDP',         premier:'David Eby' },
  { c:'SK', n:'Saskatchewan',             seats:61,  next:'2028-10-30', last:'2024-10-28', gov:'Sask Party',     premier:'Scott Moe' },
  { c:'NB', n:'New Brunswick',            seats:49,  next:'2028-10-16', last:'2024-10-21', gov:'Liberal',        premier:'Susan Holt' },
  { c:'NS', n:'Nova Scotia',              seats:55,  next:'2028-07-15', last:'2024-11-26', gov:'PC',             premier:'Tim Houston' },
  { c:'ON', n:'Ontario',                  seats:124, next:'2029-06-07', last:'2025-02-27', gov:'PC',             premier:'Doug Ford' },
  { c:'NL', n:'Newfoundland & Labrador',  seats:40,  next:'2029-10-09', last:'2025-10-14', gov:'Liberal',        premier:'John Hogan' },
  { c:'YT', n:'Yukon',                    seats:19,  next:'2029-11-03', last:'2025-11-03', gov:'Liberal',        premier:'Mike Pemberton' },
  { c:'NU', n:'Nunavut',                  seats:22,  next:'2029-10-29', last:'2025-10-27', gov:'Consensus',      premier:'P.J. Akeeagok' }
];

const MUN_DATE = {"BC":["2026-10-17","fixed, every 4 years"],"ON":["2026-10-26","fixed, every 4 years"],"MB":["2026-10-28","fixed, every 4 years"],"QC":["2026-11-01","fixed, every 4 years"],"AB":["2029-10-15","last held Oct 2025"],"SK":["2028-11-08","last held Nov 2024"],"NS":["2028-10-21","last held Oct 2024"],"NB":["2030-05-13","last held May 2026"],"PE":["2026-11-02","fixed, every 4 years"],"NL":["2029-09-25","last held Sep 2025"],"YT":["2027-10-21","municipal, staggered"],"NT":["2027-10-18","municipal, staggered"],"NU":["2027-10-25","municipal, staggered"]};
const CITIES = [{"n":"Victoria","p":"BC","cap":true,"age":22},{"n":"Vancouver","p":"BC","cap":false,"age":8},{"n":"Kelowna","p":"BC","cap":false,"age":19},{"n":"Prince George","p":"BC","cap":false,"age":23},{"n":"Kamloops","p":"BC","cap":false,"age":16},{"n":"Nanaimo","p":"BC","cap":false,"age":34},{"n":"Fort St. John","p":"BC","cap":false,"age":41},{"n":"Edmonton","p":"AB","cap":true,"age":14},{"n":"Calgary","p":"AB","cap":false,"age":13},{"n":"Red Deer","p":"AB","cap":false,"age":26},{"n":"Lethbridge","p":"AB","cap":false,"age":18},{"n":"Fort McMurray","p":"AB","cap":false,"age":12},{"n":"Grande Prairie","p":"AB","cap":false,"age":29},{"n":"Regina","p":"SK","cap":true,"age":31},{"n":"Saskatoon","p":"SK","cap":false,"age":27},{"n":"Prince Albert","p":"SK","cap":false,"age":35},{"n":"Moose Jaw","p":"SK","cap":false,"age":44},{"n":"La Ronge","p":"SK","cap":false,"age":52},{"n":"Winnipeg","p":"MB","cap":true,"age":18},{"n":"Brandon","p":"MB","cap":false,"age":33},{"n":"Thompson","p":"MB","cap":false,"age":28},{"n":"Churchill","p":"MB","cap":false,"age":241},{"n":"Toronto","p":"ON","cap":true,"age":9},{"n":"Ottawa","p":"ON","cap":false,"age":7},{"n":"Hamilton","p":"ON","cap":false,"age":15},{"n":"London","p":"ON","cap":false,"age":20},{"n":"Windsor","p":"ON","cap":false,"age":24},{"n":"Sudbury","p":"ON","cap":false,"age":13},{"n":"Thunder Bay","p":"ON","cap":false,"age":21},{"n":"Kenora","p":"ON","cap":false,"age":37},{"n":"Timmins","p":"ON","cap":false,"age":30},{"n":"Kingston","p":"ON","cap":false,"age":17},{"n":"Québec City","p":"QC","cap":true,"age":12},{"n":"Montréal","p":"QC","cap":false,"age":10},{"n":"Gatineau","p":"QC","cap":false,"age":29},{"n":"Sherbrooke","p":"QC","cap":false,"age":25},{"n":"Trois-Rivières","p":"QC","cap":false,"age":32},{"n":"Saguenay","p":"QC","cap":false,"age":19},{"n":"Val-d'Or","p":"QC","cap":false,"age":46},{"n":"Rimouski","p":"QC","cap":false,"age":22},{"n":"Fredericton","p":"NB","cap":true,"age":26},{"n":"Moncton","p":"NB","cap":false,"age":17},{"n":"Saint John","p":"NB","cap":false,"age":14},{"n":"Bathurst","p":"NB","cap":false,"age":49},{"n":"Halifax","p":"NS","cap":true,"age":16},{"n":"Sydney","p":"NS","cap":false,"age":255},{"n":"Truro","p":"NS","cap":false,"age":31},{"n":"Yarmouth","p":"NS","cap":false,"age":23},{"n":"Charlottetown","p":"PE","cap":true,"age":20},{"n":"Summerside","p":"PE","cap":false,"age":38},{"n":"St. John's","p":"NL","cap":true,"age":11},{"n":"Corner Brook","p":"NL","cap":false,"age":27},{"n":"Gander","p":"NL","cap":false,"age":21},{"n":"Labrador City","p":"NL","cap":false,"age":196},{"n":"Happy Valley-Goose Bay","p":"NL","cap":false,"age":42},{"n":"Whitehorse","p":"YT","cap":true,"age":38},{"n":"Dawson City","p":"YT","cap":false,"age":63},{"n":"Watson Lake","p":"YT","cap":false,"age":58},{"n":"Yellowknife","p":"NT","cap":true,"age":24},{"n":"Inuvik","p":"NT","cap":false,"age":51},{"n":"Hay River","p":"NT","cap":false,"age":36},{"n":"Fort Smith","p":"NT","cap":false,"age":47},{"n":"Iqaluit","p":"NU","cap":true,"age":44},{"n":"Rankin Inlet","p":"NU","cap":false,"age":67},{"n":"Arviat","p":"NU","cap":false,"age":72},{"n":"Cambridge Bay","p":"NU","cap":false,"age":null}];
const PROV_FULL = {};
PROVS.forEach(p => PROV_FULL[p.c] = p.n);

const $ = id => document.getElementById(id);
const esc = x => String(x == null ? '' : x).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NOW = new Date('2026-09-02T12:00:00Z');
const days = iso => Math.round((new Date(iso + 'T12:00:00Z') - NOW) / 864e5);
const dfmt = iso => new Date(iso + 'T12:00:00Z').toLocaleDateString('en-CA', { month:'short', day:'numeric', year:'numeric' });
/* Urgency, not party: amber inside a month, red inside a season. */
const urgency = d => d < 45 ? 'var(--wtf-contested)' : d < 200 ? 'var(--wtf-developing)' : d < 800 ? 'var(--wtf-local)' : 'var(--wtf-text-muted)';

/* \u2500\u2500 next-up counters \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
(function () {
  const munNext = Object.keys(MUN_DATE)
    .map(p => ({ p, d:MUN_DATE[p][0] }))
    .filter(x => days(x.d) >= 0)
    .sort((a, b) => a.d.localeCompare(b.d))[0];
  const cityCount = CITIES.filter(c => c.p === munNext.p).length;
  const cards = [
    { d:PROVS[0].next, n:'Qu\u00e9bec general election', m:'125 seats \u00b7 fixed date' },
    { d:munNext.d,     n:(PROV_FULL[munNext.p] || munNext.p) + ' municipal elections', m:cityCount + ' cities we report on' },
    { d:'2026-10-26',  n:'Ontario municipal elections', m:CITIES.filter(c => c.p === 'ON').length + ' cities \u00b7 largest single cycle' },
    { d:FED_NEXT.date, n:'Next federal election', m:'343 seats \u00b7 fixed date' }
  ];
  $('el-next').innerHTML = cards.map(c => {
    const n = days(c.d);
    return '<div class="wtf-el-cd" style="--ec:' + urgency(n) + '">' +
      '<div class="wtf-el-cd-d">' + n + '</div>' +
      '<div class="wtf-el-cd-u">days away</div>' +
      '<div class="wtf-el-cd-n">' + c.n + '</div>' +
      '<div class="wtf-el-cd-m">' + dfmt(c.d) + ' \u00b7 ' + c.m + '</div></div>';
  }).join('');
})();

/* \u2500\u2500 federal \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
(function () {
  const tot = FED_RESULT.reduce((n, r) => n + r.seats, 0);
  const maj = Math.floor(tot / 2) + 1;
  $('el-fed-bar').innerHTML = FED_RESULT.map(r => {
    const pct = r.seats / tot * 100;
    return '<i style="width:' + pct + '%;background:' + PARTY_COL[r.p] + '" title="' + r.p + ' ' + r.seats + '">' +
      (pct > 6 ? r.seats : '') + '</i>';
  }).join('');
  $('el-fed-leg').innerHTML = FED_RESULT.map(r =>
    '<i style="--c:' + PARTY_COL[r.p] + '">' + r.p + ' ' + r.seats + ' \u00b7 ' + r.votes.toFixed(1) + '%</i>').join('') +
    '<i style="--c:var(--wtf-text)">' + maj + ' for a majority</i>';

  /* Seat share minus vote share. The distortion IS the story; a bar either
     side of zero says which way the system bent. */
  const rows = FED_RESULT.map(r => ({ ...r, gap:(r.seats / tot * 100) - r.votes }))
    .sort((a, b) => b.gap - a.gap);
  const span = Math.max.apply(null, rows.map(r => Math.abs(r.gap))) || 1;
  $('el-fed-dist').innerHTML = rows.map(r => {
    const w = Math.abs(r.gap) / span * 46;
    const pos = r.gap >= 0;
    return '<div style="display:grid;grid-template-columns:104px minmax(0,1fr) 62px;gap:10px;align-items:center;padding:5px 0">' +
      '<span style="font-size:12.5px;color:var(--wtf-text-2)">' + r.p + '</span>' +
      '<span style="position:relative;height:14px">' +
        '<span style="position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--wtf-border)"></span>' +
        '<span style="position:absolute;top:3px;height:8px;border-radius:2px;background:' + PARTY_COL[r.p] +
          ';' + (pos ? 'left:50%;' : 'right:50%;') + 'width:' + w + '%"></span></span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;text-align:right;color:' +
        (pos ? 'var(--wtf-established)' : 'var(--wtf-contested)') + '">' +
        (pos ? '+' : '\u2212') + Math.abs(r.gap).toFixed(1) + ' pt</span></div>';
  }).join('');

  const n = days(FED_NEXT.date);
  $('el-fed-next').innerHTML =
    '<div style="display:flex;flex-wrap:wrap;gap:14px;align-items:baseline">' +
      '<span style="font-family:var(--wtf-font-mono);font-size:24px;color:var(--wtf-text);font-variant-numeric:tabular-nums">' + dfmt(FED_NEXT.date) + '</span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:11px;color:var(--wtf-text-muted)">' + n.toLocaleString() + ' days \u00b7 ' + (n / 365).toFixed(1) + ' years</span></div>' +
    '<p class="wtf-el-note" style="margin-top:10px">' + FED_NEXT.law + '. A minority government can fall on a confidence vote at any time, so this is the latest date rather than the likely one \u2014 the current House sits with a Liberal minority.</p>';
})();

/* \u2500\u2500 provincial \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
let PS = { q:'', sort:'date' };
function renderProvs() {
  const q = PS.q.toLowerCase();
  const list = PROVS.filter(p =>
    !q || (p.n + ' ' + p.gov + ' ' + p.premier + ' ' + p.c).toLowerCase().includes(q));
  list.sort((a, b) =>
    PS.sort === 'seats' ? b.seats - a.seats :
    PS.sort === 'name'  ? a.n.localeCompare(b.n) :
    a.next.localeCompare(b.next));
  $('el-pcount').textContent = list.length + ' of ' + PROVS.length + ' legislatures';
  $('el-plist').innerHTML = list.length ? list.map(p => {
    const n = days(p.next);
    return '<div class="wtf-el-row">' +
      '<span class="wtf-el-date" style="color:' + urgency(n) + '">' + dfmt(p.next) +
        '<span>' + (n < 0 ? 'overdue' : n + ' days') + '</span></span>' +
      '<span><span class="wtf-el-place">' + esc(p.n) + '</span>' +
        '<span class="wtf-el-sub">' + p.seats + ' seats \u00b7 ' + esc(p.premier) + ' \u00b7 last ' + dfmt(p.last) + '</span></span>' +
      '<span class="wtf-el-tag" style="background:' + (PARTY_COL[p.gov] || '#9ca3af') + '22;color:' +
        (PARTY_COL[p.gov] || '#9ca3af') + ';border:1px solid ' + (PARTY_COL[p.gov] || '#9ca3af') + '55">' + esc(p.gov) + '</span></div>';
  }).join('') : '<div class="wtf-el-none">No legislature matches that search.</div>';
}
$('el-pq').addEventListener('input', e => { PS.q = e.target.value.trim(); renderProvs(); });
$('el-psort').addEventListener('change', e => { PS.sort = e.target.value; renderProvs(); });
renderProvs();

/* Provincial map: shaded by time to the polls, so the reader sees the season
   rather than reading thirteen dates. */
(function () {
  const W = 1000, H = 430;
  const svg = d3.select('#el-map').append('svg')
    .attr('viewBox', '0 0 ' + W + ' ' + H).attr('preserveAspectRatio', 'xMidYMid meet');
  const tip = $('el-tip');
  d3.json('https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/ne_50m_admin_1_states_provinces.geojson')
    .then(fc => {
      const keep = {}; PROVS.forEach(p => keep[p.c] = p);
      const feats = (fc.features || []).filter(f => f.properties.admin === 'Canada' && keep[f.properties.postal]);
      if (!feats.length) throw new Error('no geometry');
      const proj = d3.geoConicConformal().parallels([49, 77]).rotate([96, 0])
        .fitExtent([[24, 18], [W - 24, H - 24]], { type:'FeatureCollection', features:feats });
      const path = d3.geoPath(proj);
      svg.append('g').selectAll('path').data(feats).join('path')
        .attr('d', path)
        .attr('fill', f => urgency(days(keep[f.properties.postal].next)))
        .attr('fill-opacity', f => { const n = days(keep[f.properties.postal].next);
          return n < 45 ? .58 : n < 200 ? .44 : n < 800 ? .3 : .16; })
        .attr('stroke', '#31405a').attr('stroke-width', .8)
        .style('cursor', 'pointer')
        .on('mousemove', (e, f) => {
          const p = keep[f.properties.postal], n = days(p.next);
          tip.innerHTML = '<b>' + p.n + '</b><em>' + dfmt(p.next) + ' \u00b7 ' + n + ' days \u00b7 ' + p.seats + ' seats</em>';
          tip.style.display = 'block';
          tip.style.left = Math.min(e.clientX + 14, innerWidth - 220) + 'px';
          tip.style.top = Math.max(8, e.clientY - 46) + 'px';
        })
        .on('mouseleave', () => { tip.style.display = 'none'; });
      /* Labels only where the polygon can hold one. */
      svg.append('g').selectAll('text').data(feats.filter(f => path.area(f) > 900)).join('text')
        .attr('x', f => path.centroid(f)[0]).attr('y', f => path.centroid(f)[1])
        .attr('text-anchor', 'middle').attr('font-size', 9.5)
        .attr('font-family', 'IBM Plex Mono, monospace').attr('fill', 'var(--wtf-text)')
        .attr('paint-order', 'stroke').attr('stroke', '#0d1117').attr('stroke-width', 2.5)
        .text(f => f.properties.postal);
    })
    .catch(() => {
      $('el-map').insertAdjacentHTML('afterbegin',
        '<div style="padding:38px;text-align:center;color:var(--wtf-text-muted);font-size:13px">Provincial geometry could not be loaded. The list below carries every date.</div>');
    });
})();

/* \u2500\u2500 municipal \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
/* 2021 census. The grade needs a denominator, and a missing population must
   never silently become a failing grade — it is reported as unknown instead. */
const CITY_POP = {"Victoria":91867,"Vancouver":662248,"Kelowna":144576,"Prince George":76708,"Kamloops":97902,"Nanaimo":99863,"Fort St. John":21465,"Edmonton":1010899,"Calgary":1306784,"Red Deer":100844,"Lethbridge":98406,"Fort McMurray":68002,"Grande Prairie":64141,"Regina":226404,"Saskatoon":266141,"Prince Albert":37756,"Moose Jaw":33665,"La Ronge":2304,"Winnipeg":749607,"Brandon":51313,"Thompson":13035,"Churchill":870,"Toronto":2794356,"Ottawa":1017449,"Hamilton":569353,"London":422324,"Windsor":229660,"Sudbury":166004,"Thunder Bay":108843,"Kenora":14967,"Timmins":41145,"Kingston":132485,"Québec City":549459,"Montréal":1762949,"Gatineau":291041,"Sherbrooke":172950,"Trois-Rivières":139163,"Saguenay":144723,"Val-d'Or":32752,"Rimouski":48664,"Fredericton":63116,"Moncton":79470,"Saint John":69895,"Bathurst":12157,"Halifax":439819,"Sydney":29904,"Truro":12954,"Yarmouth":6518,"Charlottetown":38809,"Summerside":16001,"St. John's":110525,"Corner Brook":19316,"Gander":11880,"Labrador City":7412,"Happy Valley-Goose Bay":8040,"Whitehorse":28201,"Dawson City":1577,"Watson Lake":1074,"Yellowknife":20340,"Inuvik":3137,"Hay River":3169,"Fort Smith":2248,"Iqaluit":7429,"Rankin Inlet":2975,"Arviat":2864,"Cambridge Bay":1760};
const MUN = CITIES.map(c => ({
  ...c, pop:CITY_POP[c.n] || null,
  date:(MUN_DATE[c.p] || ['2029-01-01','unknown'])[0], law:(MUN_DATE[c.p] || ['','unknown'])[1]
}));

(function () {
  const by = {};
  MUN.forEach(m => { (by[m.date] = by[m.date] || []).push(m); });
  const dates = Object.keys(by).sort().filter(d => days(d) >= 0 && days(d) < 400);
  const max = Math.max.apply(null, dates.map(d => by[d].length).concat([1]));
  $('el-mun-waves').innerHTML = dates.map(d =>
    '<div class="wtf-el-cov"><span style="font-size:12.5px;color:var(--wtf-text-2)">' + dfmt(d) + '</span>' +
      '<span class="wtf-el-cov-t"><i style="width:' + Math.round(by[d].length / max * 100) + '%;background:' + urgency(days(d)) + '"></i></span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' + by[d].length + '</span></div>' +
    '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin:-2px 0 7px 160px">' +
      [...new Set(by[d].map(m => m.p))].join(', ') + ' \u00b7 ' + days(d) + ' days</div>').join('');
})();

let MS = { q:'', prov:'', sort:'date' };
$('el-mprov').innerHTML = '<option value="">Every province</option>' +
  [...new Set(MUN.map(m => m.p))].sort().map(p => '<option value="' + p + '">' + (PROV_FULL[p] || p) + '</option>').join('');
function renderMun() {
  const q = MS.q.toLowerCase();
  const list = MUN.filter(m => (!MS.prov || m.p === MS.prov) &&
    (!q || (m.n + ' ' + m.p + ' ' + (PROV_FULL[m.p] || '')).toLowerCase().includes(q)));
  list.sort((a, b) =>
    MS.sort === 'name' ? a.n.localeCompare(b.n) :
    MS.sort === 'prov' ? (a.p.localeCompare(b.p) || a.n.localeCompare(b.n)) :
    (a.date.localeCompare(b.date) || a.n.localeCompare(b.n)));
  $('el-mcount').textContent = list.length + ' of ' + MUN.length + ' cities';
  $('el-mlist').innerHTML = list.length ? list.map(m => {
    const n = days(m.date);
    return '<div class="wtf-el-row">' +
      '<span class="wtf-el-date" style="color:' + urgency(n) + '">' + dfmt(m.date) +
        '<span>' + n + ' days</span></span>' +
      '<span><span class="wtf-el-place">' + esc(m.n) +
        (m.cap ? ' <span class="wtf-el-tag" style="background:rgba(74,114,216,.14);color:var(--wtf-local)">capital</span>' : '') +
        '</span><span class="wtf-el-sub">' + (PROV_FULL[m.p] || m.p) + ' \u00b7 ' + m.law + '</span></span>' +
      '<a class="wtf-el-tag" style="text-decoration:none;background:var(--wtf-bg-panel);color:var(--wtf-text-2);border:1px solid var(--wtf-border)" href="wtf-municipal.html">Coverage &rarr;</a></div>';
  }).join('') : '<div class="wtf-el-none">No city matches that filter.</div>';
}
$('el-mq').addEventListener('input', e => { MS.q = e.target.value.trim(); renderMun(); });
$('el-mprov').addEventListener('change', e => { MS.prov = e.target.value; renderMun(); });
$('el-msort').addEventListener('change', e => { MS.sort = e.target.value; renderMun(); });
renderMun();

/* coverage readiness ---------------------------------------------------- */
(function () {
  /* Absolute story counts, not per-capita. A per-resident threshold made an
     870-person town clear on one story while Toronto needed twenty-eight, and
     it put every province at 0% — a grade that cannot discriminate is not a
     grade. One reporter can cover one council regardless of city size, so the
     bands are absolute and population is shown as context only. */
  const BANDS = [
    { k:'none',      l:'No story',  c:'var(--wtf-contested)',    d:'nobody filed' },
    { k:'minimal',   l:'Minimal',   c:'var(--wtf-developing)',   d:'1\u20132 \u2014 a council exists, nobody is following it' },
    { k:'some',      l:'Some',      c:'var(--wtf-center-right)', d:'3\u20139 in the window' },
    { k:'sustained', l:'Sustained', c:'var(--wtf-established)',  d:'10+ \u2014 roughly weekly' }
  ];
  const bandOfCount = function (n) {
    if (n >= 10) return BANDS[3];
    if (n >= 3) return BANDS[2];
    if (n >= 1) return BANDS[1];
    return BANDS[0];
  };

  const soon = MUN.filter(function (m) { return days(m.date) >= 0 && days(m.date) < 400; });

  /* Same city detection the municipal page uses, longest name first so
     "Québec City" is never swallowed by "Québec". */
  const names = MUN.map(function (m) { return m.n; }).slice()
    .sort(function (a, b) { return b.length - a.length; });
  const storyCount = {};
  let corpusStories = 0;
  if (typeof ARTICLES !== 'undefined') {
    const stories = ARTICLES.filter(function (a) { return a.first; });
    corpusStories = stories.length;
    stories.forEach(function (a) {
      const hay = a.t + ' ' + (a.note || '');
      for (let i = 0; i < names.length; i++) {
        if (hay.indexOf(names[i]) >= 0) { storyCount[names[i]] = (storyCount[names[i]] || 0) + 1; break; }
      }
    });
  }

  const graded = soon.map(function (m) {
    const n = storyCount[m.n] || 0;
    return { n:m.n, p:m.p, cap:m.cap, pop:m.pop, date:m.date, stories:n,
             per100k:m.pop ? n / (m.pop / 1e5) : null, band:bandOfCount(n) };
  });
  const count = function (k) { return graded.filter(function (g) { return g.band.k === k; }).length; };
  const followable = count('some') + count('sustained');
  const totalStories = graded.reduce(function (a, g) { return a + g.stories; }, 0);

  $('el-ready').innerHTML =
    '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:15px">' +
    [[String(graded.length), 'Cities voting within a year'],
     [String(count('none')), 'No municipal story at all'],
     [String(count('minimal')), 'One or two stories'],
     [String(followable), 'Three or more'],
     [String(totalStories), 'Stories across all of them']]
    .map(function (r) {
      return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
    }).join('') +
    '</div>' +
    '<div class="wtf-el-leg" style="margin-bottom:14px">' +
      BANDS.map(function (b) { return '<i style="--c:' + b.c + '">' + b.l + ' \u00b7 ' + b.d + '</i>'; }).join('') +
    '</div>' +
    (function () {
      const byProv = {};
      graded.forEach(function (g) { (byProv[g.p] = byProv[g.p] || []).push(g); });
      return Object.keys(byProv)
        .sort(function (a, b) { return byProv[a][0].date.localeCompare(byProv[b][0].date); })
        .map(function (p) {
          const rows = byProv[p];
          const silent = rows.filter(function (r) { return r.band.k === 'none'; }).length;
          const stories = rows.reduce(function (a, r) { return a + r.stories; }, 0);
          return '<div class="wtf-el-cov">' +
            '<span style="font-size:12.5px;color:var(--wtf-text-2)">' + (PROV_FULL[p] || p) + '</span>' +
            '<span class="wtf-el-cov-t" style="display:flex">' +
              BANDS.map(function (b) {
                const c = rows.filter(function (r) { return r.band.k === b.k; }).length;
                return c ? '<i style="width:' + (c / rows.length * 100) + '%;background:' + b.c + '"></i>' : '';
              }).join('') + '</span>' +
            '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;text-align:right;color:' +
              (stories === 0 ? 'var(--wtf-contested)' : 'var(--wtf-text)') + '">' + stories + '</span></div>' +
            '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin:-2px 0 8px 160px">' +
              rows.length + ' cities \u00b7 votes ' + dfmt(rows[0].date) + ' \u00b7 ' +
              silent + ' with no story \u00b7 ' + stories + ' stories total</div>';
        }).join('');
    })() +
    '<p class="wtf-el-note" style="margin-top:11px">The right-hand number is total municipal stories filed in that province\u2019s voting cities, ' +
    'not a pass rate. ' +
    (totalStories < 40
      ? '<strong>These counts come from the current sample corpus, which holds ' + corpusStories +
        ' distinct stories in total across every beat</strong> \u2014 so they measure the size of this window, not the newsroom\u2019s real ' +
        'municipal output. Against the live corpus the figures rise substantially. What to read here is the shape of the gap between ' +
        'provinces and cities, not the absolute numbers.'
      : 'Counted over the current window.') + '</p>';

  let filter = '';
  function drawList() {
    const rows = graded
      .filter(function (g) { return !filter || g.band.k === filter; })
      .sort(function (a, b) { return a.stories - b.stories || (b.pop || 0) - (a.pop || 0); });
    $('el-rcount').textContent = rows.length + ' of ' + graded.length + ' cities';
    $('el-rlist').innerHTML = rows.length ? rows.map(function (g) {
      return '<div class="wtf-el-row" style="grid-template-columns:104px minmax(0,1fr) auto">' +
        '<span class="wtf-el-date" style="color:' + g.band.c + '">' + g.band.l +
          '<span>' + g.stories + ' stor' + (g.stories === 1 ? 'y' : 'ies') + '</span></span>' +
        '<span><span class="wtf-el-place">' + esc(g.n) +
          (g.cap ? ' <span class="wtf-el-tag" style="background:rgba(74,114,216,.14);color:var(--wtf-local)">capital</span>' : '') +
          '</span><span class="wtf-el-sub">' + (PROV_FULL[g.p] || g.p) + ' \u00b7 ' +
          (g.pop ? g.pop.toLocaleString() + ' residents' : 'population not on file') +
          ' \u00b7 votes ' + dfmt(g.date) + '</span></span>' +
        '<span class="wtf-el-tag" style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-muted)">' +
          (g.per100k === null ? 'no population' : g.per100k.toFixed(2) + ' / 100k context') + '</span></div>';
    }).join('')
      : '<div class="wtf-el-none">No city in that band.</div>';
  }
  $('el-rgrade').addEventListener('change', function (e) { filter = e.target.value; drawList(); });
  drawList();
})();

/* \u2500\u2500 tabs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
function showEl(name) {
  document.querySelectorAll('.wtf-pl-tab[data-el]').forEach(b => b.classList.toggle('on', b.dataset.el === name));
  document.querySelectorAll('[id^="el-pane-"]').forEach(p => p.classList.toggle('on', p.id === 'el-pane-' + name));
  const want = name === 'federal' ? '' : '#' + name;
  if (location.hash !== want) history.replaceState(null, '', name === 'federal' ? location.pathname : want);
}
window.showEl = showEl;
document.querySelectorAll('.wtf-pl-tab[data-el]').forEach(b =>
  b.addEventListener('click', () => showEl(b.dataset.el)));
addEventListener('hashchange', () => {
  const h = location.hash.slice(1);
  if (['federal','provincial','municipal','byelections','deadlines','turnout','coverage'].includes(h)) showEl(h);
});
(function () {
  const h = location.hash.slice(1);
  if (['provincial','municipal','byelections','deadlines','turnout','coverage'].includes(h)) showEl(h);
})();

window.showEl = showEl;
})();
