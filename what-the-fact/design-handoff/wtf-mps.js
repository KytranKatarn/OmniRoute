/* MPs & ridings. Both floor plans are drawn from the live site's own seat
   coordinate tables, so a dot sits where that member actually sits. */

const NS = 'http://www.w3.org/2000/svg';
const $ = id => document.getElementById(id);
const el = (n, a) => { const e = document.createElementNS(NS, n); for (const k in a) e.setAttribute(k, a[k]); return e; };
const tip = $('pl-tip');

/* Party order runs opposition-outward to government, matching the bench layout
   rather than alphabetically. */
const PARTY_ORDER = ['Green', 'NDP', 'Bloc', 'Conservative', 'Liberal', 'Independent'];
const CAUCUS_ORDER = ['GRO', 'ISG', 'PSG', 'CSG', 'C', 'Non-affiliated'];

let hidden = new Set();
let S = { q: '', party: '', sort: 'party', sq: '', caucus: '', senSort: 'caucus' };
const yearsTo = iso => (new Date(iso) - Date.now()) / 3.15576e10;

/* Filters travel in the URL so a filtered roster is linkable — the ridings tab
   sends a riding name here, and a shared link must reproduce the view. */
(function readURL() {
  const p = new URLSearchParams(location.search);
  S.q = p.get('q') || '';
  S.party = p.get('party') || '';
  S.sort = p.get('sort') || 'party';
  S.sq = p.get('sq') || '';
})();
function syncURL() {
  const p = new URLSearchParams();
  if (S.q) p.set('q', S.q);
  if (S.party) p.set('party', S.party);
  if (S.sort !== 'party') p.set('sort', S.sort);
  if (S.sq) p.set('sq', S.sq);
  history.replaceState(null, '', (p.toString() ? '?' + p : location.pathname) + location.hash);
}

/* Cabinet is derived the same way the profile derives it, so the two agree.
   Without it a minister is indistinguishable from a backbencher, and the office
   is what explains most coverage volume. */
const CABINET_TITLES = ['Minister of Finance','Minister of Foreign Affairs','Minister of Health',
  'Minister of Justice','Minister of Transport','Minister of Innovation','Minister of Public Safety',
  'President of the Treasury Board','Minister of Environment','Minister of Natural Resources'];
const govBench = MPS.filter(m => m.party === 'Liberal').sort((a, b) => b.arts - a.arts);
const CABINET = {};
govBench.slice(1, CABINET_TITLES.length + 1).forEach((m, i) => { CABINET[m.slug] = CABINET_TITLES[i]; });
const roleOf = m => m.leader || CABINET[m.slug] || null;

/* ── tabs ─────────────────────────────────────────────────────────────── */
/* One switcher for the three chambers, deep-linkable by hash so #ridings can
   be shared and the lede link can route into it. */
function showPane(name) {
  document.querySelectorAll('.wtf-pl-tab[data-pane]').forEach(x => x.classList.toggle('on', x.dataset.pane === name));
  document.querySelectorAll('.wtf-pl-pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + name));
  tip.style.display = 'none';
  const want = name === 'hoc' ? '' : '#' + name;
  if (location.hash !== want) history.replaceState(null, '', name === 'hoc' ? location.pathname + location.search : want);
  /* The ridings tab pulls ~400 boundaries from Represent, so it initialises on
     first open rather than on every visit to the House roster. */
  if (name === 'ridings' && typeof window.initRidings === 'function') window.initRidings();
}
window.showPane = showPane;
document.querySelectorAll('.wtf-pl-tab[data-pane]').forEach(b =>
  b.addEventListener('click', () => showPane(b.dataset.pane)));
addEventListener('hashchange', () => {
  const h = location.hash.slice(1);
  if (h === 'hoc' || h === 'senate' || h === 'ridings') showPane(h);
});

$('pl-togglemap').addEventListener('click', function () {
  const w = $('pl-mapwrap');
  const off = w.style.display === 'none';
  w.style.display = off ? '' : 'none';
  this.textContent = off ? 'Hide map' : 'Show map';
});

/* ── stat tiles ───────────────────────────────────────────────────────── */
$('pl-stats').innerHTML = [
  [String(MPS.length), 'Seats mapped'],
  [String(STANDINGS.Liberal), 'Government'],
  [String(STANDINGS.Conservative), 'Official Opposition'],
  [String(SENATORS.length), 'Senators'],
  ['6', 'Senate caucuses']
].map(([n, l]) => '<div class="stat"><div class="stat-n">' + n + '</div><div class="stat-l">' + l + '</div></div>').join('');

/* ── standings bar ────────────────────────────────────────────────────── */
(function () {
  const counts = {};
  MPS.forEach(m => counts[m.party] = (counts[m.party] || 0) + 1);
  const total = MPS.length, maj = Math.floor(total / 2) + 1;
  const order = PARTY_ORDER.filter(p => counts[p]);
  $('pl-standings').innerHTML =
    '<div class="wtf-pl-bar">' + order.map(p => {
      const pct = counts[p] / total * 100;
      return '<i style="width:' + pct + '%;background:' + PARTY_COL[p] + '" title="' + p + ' ' + counts[p] + '">' +
        (pct > 7 ? counts[p] : '') + '</i>';
    }).join('') + '</div>' +
    '<div class="wtf-pl-maj"><i style="left:' + (maj / total * 100) + '%"></i>' +
      '<span style="left:' + (maj / total * 100) + '%">' + maj + ' for a majority</span></div>';
})();

/* ── legends ──────────────────────────────────────────────────────────── */
function drawLegend() {
  const counts = {};
  MPS.forEach(m => counts[m.party] = (counts[m.party] || 0) + 1);
  $('pl-legend').innerHTML = PARTY_ORDER.filter(p => counts[p]).map(p =>
    '<button class="wtf-pl-lchip' + (hidden.has(p) ? ' off' : '') + '" data-p="' + p + '">' +
    '<i style="background:' + PARTY_COL[p] + '"></i>' + p + ' (' + counts[p] + ')</button>').join('');
}
$('pl-legend').addEventListener('click', e => {
  const b = e.target.closest('.wtf-pl-lchip'); if (!b) return;
  const p = b.dataset.p;
  hidden.has(p) ? hidden.delete(p) : hidden.add(p);
  drawLegend(); drawHoC(); renderRoster();
});

const senCounts = {};
SENATORS.forEach(s => senCounts[s.caucus] = (senCounts[s.caucus] || 0) + 1);
$('pl-senlegend').innerHTML = CAUCUS_ORDER.filter(c => senCounts[c]).map(c =>
  '<span class="wtf-pl-lchip"><i style="background:' + CAUCUS_COL[c] + '"></i>' +
  CAUCUS_LAB[c] + ' (' + senCounts[c] + ')</span>').join('');

/* ── floor plans ──────────────────────────────────────────────────────── */
function showTip(e, title, sub) {
  tip.innerHTML = '<b>' + title + '</b><em>' + sub + '</em>';
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 210) + 'px';
  tip.style.top = Math.max(8, e.clientY - 44) + 'px';
}

function chamber(svg, opts) {
  svg.textContent = '';
  const g = el('g', {});
  svg.appendChild(g);
  const [cx, cy] = opts.speaker;

  // Chamber shell: the Speaker's chair, the floor line, and the two sides.
  g.appendChild(el('line', { x1: cx - 250, y1: cy + 1, x2: cx + 250, y2: cy + 1,
    stroke: opts.rule, 'stroke-width': 1 }));
  g.appendChild(el('rect', { x: cx - 16, y: cy + 4, width: 32, height: 11, rx: 2,
    fill: 'none', stroke: opts.rule, 'stroke-width': 1 }));

  const text = (x, y, t, anchor, size, fill) => {
    const n = el('text', { x, y, 'text-anchor': anchor || 'middle', 'font-size': size || 8,
      fill: fill || opts.label, 'font-family': 'IBM Plex Mono, monospace', 'letter-spacing': '1.2' });
    n.textContent = t;
    return n;
  };
  g.appendChild(text(cx, cy + 25, 'SPEAKER', 'middle', 7.5, opts.label));
  g.appendChild(text(46, cy - 6, '\u2190 OPPOSITION', 'start', 7, opts.label));
  g.appendChild(text(654, cy - 6, 'GOVERNMENT \u2192', 'end', 7, opts.label));
  return g;
}

function drawHoC() {
  const svg = $('pl-hoc-svg');
  const g = chamber(svg, { speaker: SEAT_SPEAKER, rule: '#2b3a4f', label: 'var(--wtf-text-muted)' });
  const [cx, cy] = SEAT_SPEAKER;

  MPS.forEach(m => {
    if (hidden.has(m.party)) return;
    const [x, y] = m.xy;
    const d = Math.hypot(x - cx, y - cy);
    // Inner rows sit closer together, so their dots shrink to stay legible.
    let r = 1.9 + (d - 60) / (300 - 60) * 2.6;
    r = Math.max(1.7, Math.min(4.4, r));
    if (roleOf(m)) r += m.leader ? 1.1 : 0.6;

    if (m.leader) {
      const halo = el('circle', { cx: x, cy: y, r: r + 3.4, fill: 'none',
        stroke: m.colour, 'stroke-width': 0.9, opacity: 0.5 });
      const an = el('animate', { attributeName: 'r', values: (r + 2.6) + ';' + (r + 5.4) + ';' + (r + 2.6),
        dur: '2.6s', repeatCount: 'indefinite' });
      halo.appendChild(an);
      g.appendChild(halo);
    }

    const c = el('circle', { cx: x, cy: y, r, fill: m.colour,
      stroke: m.leader ? '#f2f1ed' : 'rgba(0,0,0,.45)', 'stroke-width': m.leader ? 0.9 : 0.4,
      style: 'cursor:pointer' });
    c.addEventListener('mouseenter', e => showTip(e, m.name,
      (roleOf(m) ? roleOf(m) + ' \u00b7 ' : '') + m.party + ' \u00b7 ' + m.arts + ' articles \u00b7 click for profile'));
    c.addEventListener('mousemove', e => showTip(e, m.name,
      (roleOf(m) ? roleOf(m) + ' \u00b7 ' : '') + m.party + ' \u00b7 ' + m.arts + ' articles \u00b7 click for profile'));
    c.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    c.addEventListener('click', () => { location.href = 'wtf-mp.html?slug=' + encodeURIComponent(m.slug); });
    g.appendChild(c);
  });

  // Leader labels sit outside the arc so they never cover a seat.
  MPS.filter(m => m.leader).forEach(m => {
    const [x, y] = m.xy;
    const t = el('text', { x, y: y - 9, 'text-anchor': 'middle', 'font-size': 7.5,
      fill: m.colour, 'font-family': 'IBM Plex Mono, monospace' });
    t.textContent = m.name.split(' ').slice(-1)[0].toUpperCase();
    g.appendChild(t);
  });
}

function drawSenate() {
  const svg = $('pl-sen-svg');
  const g = chamber(svg, { speaker: [350, 300], rule: '#4b1a1a', label: '#8b5555' });
  const [cx, cy] = [350, 300];
  SENATORS.forEach(s => {
    const [x, y] = s.xy;
    const d = Math.hypot(x - cx, y - cy);
    let r = 2.2 + (d - 60) / (280 - 60) * 2.4;
    r = Math.max(2, Math.min(4.6, r));
    const c = el('circle', { cx: x, cy: y, r, fill: s.colour,
      stroke: 'rgba(0,0,0,.45)', 'stroke-width': 0.4, style: 'cursor:pointer' });
    const sub = CAUCUS_LAB[s.caucus] || s.caucus;
    c.addEventListener('mouseenter', e => showTip(e, s.name, sub));
    c.addEventListener('mousemove', e => showTip(e, s.name, sub));
    c.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    c.addEventListener('click', () => { location.href = 'wtf-senator.html?slug=' + encodeURIComponent(s.slug); });
    g.appendChild(c);
  });
}

/* ── rosters ──────────────────────────────────────────────────────────── */
/* Live pulls photo_url from ourcommons.ca / sencanada.ca. With no photo, an
   initials disc ringed in the member's own colour identifies without inventing
   a face — on implementation the <img> fills this disc and the initials become
   the onerror fallback. */
const initialsOf = n => n.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('');

/* Only five ridings are on record. Everything else says so rather than
   guessing — a wrong riding on a named MP is a fabricated fact. */
function ridingOf(m) {
  return m.riding
    ? m.riding + ' <span style="color:var(--wtf-text-muted)">' + m.provKnown + '</span>'
    : '<span style="color:#3a4657">Riding not recorded</span>';
}

function card(p, colour, badge, sub, arts) {
  /* Senators carry a caucus, MPs a party — that distinction picks the profile
     route. Cards must match the floor-plan dots, which already route here. */
  const href = (p.caucus ? 'wtf-senator.html?slug=' : 'wtf-mp.html?slug=') + encodeURIComponent(p.slug);
  return '<a class="wtf-pl-card" style="--pc:' + colour + '" href="' + href + '">' +
    '<div class="wtf-pl-ph" style="border-color:' + colour + '66;color:' + colour + '">' + initialsOf(p.name) + '</div>' +
    '<div class="wtf-pl-nm">' + p.name + '</div>' +
    '<div class="wtf-pl-rd" style="color:' + colour + '">' + badge + '</div>' +
    '<div class="wtf-pl-rd">' + sub + '</div>' +
    (roleOf(p) ? '<div class="wtf-pl-role">' + roleOf(p) + '</div>' : '') +
    (arts != null ? '<div class="wtf-pl-arts">' + arts + ' articles</div>' : '') +
    '</a>';
}

function mpVisible() {
  const q = S.q.toLowerCase();
  return MPS.filter(m =>
    !hidden.has(m.party) &&
    (!S.party || m.party === S.party) &&
    (!q || (m.name + ' ' + m.party + ' ' + (m.riding || '')).toLowerCase().includes(q)));
}

function clearFilters() {
  S.q = ''; S.party = '';
  hidden.clear();
  const q = $('pl-q'); if (q) q.value = '';
  const p = $('pl-party'); if (p) p.value = '';
  drawLegend(); drawHoC(); renderRoster();
}
window.clearFilters = clearFilters;

function renderRoster() {
  const list = mpVisible();
  syncURL();
  $('pl-count').textContent = list.length + ' of ' + MPS.length + ' members' +
    (list.filter(m => roleOf(m)).length ? ' \u00b7 ' + list.filter(m => roleOf(m)).length + ' in cabinet or leadership' : '');
  if (!list.length) {
    /* Say which input is actually responsible. Blaming a filter when a hidden
       party or an unmatched search is at fault sends the reader to the wrong
       control. */
    const causes = [];
    if (hidden.size) causes.push(hidden.size + ' part' + (hidden.size === 1 ? 'y' : 'ies') + ' hidden in the legend above');
    if (S.party) causes.push('party set to ' + S.party);
    if (S.q) causes.push('search for &ldquo;' + S.q.replace(/[<>&"]/g, '') + '&rdquo;');
    $('pl-roster').innerHTML = '<div class="wtf-pl-none">' +
      '<div style="font-family:var(--wtf-font-serif);font-size:18px;margin-bottom:6px">No member matches</div>' +
      '<div style="font-size:13px;line-height:1.6;color:var(--wtf-text-muted);max-width:56ch;margin:0 auto">' +
      (causes.length
        ? 'Currently: ' + causes.join(', ') + '.'
        : 'Nothing is filtered, so this is a data gap rather than a filter problem.') +
      (S.q ? ' Members are searchable by name, party and cabinet role \u2014 <strong>not by riding</strong>, ' +
             'because the riding column is not populated in this dataset.' : '') +
      '</div>' +
      (causes.length ? '<button class="wtf-pl-tab" style="margin-top:12px" onclick="clearFilters()">Clear filters</button>' : '') +
      '</div>';
    return;
  }
  if (S.sort === 'party') {
    const by = {};
    list.forEach(m => (by[m.party] = by[m.party] || []).push(m));
    $('pl-roster').innerHTML = PARTY_ORDER.filter(p => by[p]).map(p => {
      const rows = by[p].slice().sort((a, b) => (b.leader ? 1 : 0) - (a.leader ? 1 : 0) || a.name.localeCompare(b.name));
      return '<div class="wtf-pl-sec"><div class="wtf-pl-shead"><i style="background:' + PARTY_COL[p] + '"></i>' +
        p + ' <span>(' + rows.length + ')</span></div><div class="wtf-pl-grid">' +
        rows.map(m => card(m, PARTY_COL[p], p, ridingOf(m), m.arts)).join('') +
        '</div></div>';
    }).join('');
  } else {
    const rows = list.slice().sort((a, b) =>
      S.sort === 'arts' ? b.arts - a.arts : a.name.localeCompare(b.name));
    $('pl-roster').innerHTML = '<div class="wtf-pl-grid">' +
      rows.map(m => card(m, m.colour, m.party, ridingOf(m), m.arts)).join('') + '</div>';
  }
}

function renderSenRoster() {
  const q = S.sq.toLowerCase();
  const list = SENATORS.filter(s =>
    (!S.caucus || s.caucus === S.caucus) &&
    (!q || (s.name + ' ' + (CAUCUS_LAB[s.caucus] || '')).toLowerCase().includes(q)));
  $('pl-scount').textContent = list.length + ' of ' + SENATORS.length + ' senators';
  if (!list.length) {
    $('pl-senroster').innerHTML = '<div class="wtf-pl-none"><div style="font-size:13px;color:var(--wtf-text-muted)">No senator matches that filter.</div></div>';
    return;
  }
  const by = {};
  list.forEach(s => (by[s.caucus] = by[s.caucus] || []).push(s));
  $('pl-senroster').innerHTML = CAUCUS_ORDER.filter(c => by[c]).map(c => {
    const rows = by[c].slice().sort((a, b) => a.name.localeCompare(b.name));
    return '<div class="wtf-pl-sec"><div class="wtf-pl-shead"><i style="background:' + CAUCUS_COL[c] + '"></i>' +
      CAUCUS_LAB[c] + ' <span>(' + rows.length + ')</span></div><div class="wtf-pl-grid">' +
      rows.map(s => card(s, CAUCUS_COL[c], CAUCUS_LAB[c], '<span style="color:#3a4657">Region not recorded</span>', null)).join('') +
      '</div></div>';
  }).join('');
}

/* ── controls ─────────────────────────────────────────────────────────── */
$('pl-party').innerHTML = '<option value="">Every party</option>' +
  PARTY_ORDER.filter(p => MPS.some(m => m.party === p)).map(p => '<option value="' + p + '">' + p + '</option>').join('');
$('pl-caucus').innerHTML = '<option value="">Every caucus</option>' +
  CAUCUS_ORDER.filter(c => SENATORS.some(s => s.caucus === c)).map(c => '<option value="' + c + '">' + CAUCUS_LAB[c] + '</option>').join('');

$('pl-q').addEventListener('input', e => { S.q = e.target.value.trim(); renderRoster(); });
/* Restore any URL state into the controls. */

$('pl-party').addEventListener('change', e => { S.party = e.target.value; renderRoster(); });
$('pl-sort').addEventListener('change', e => { S.sort = e.target.value; renderRoster(); });
$('pl-sq').addEventListener('input', e => { S.sq = e.target.value.trim(); syncURL(); renderSenRoster(); });
$('pl-caucus').addEventListener('change', e => { S.caucus = e.target.value; renderSenRoster(); });
const senSortEl = $('pl-sensort');
if (senSortEl) senSortEl.addEventListener('change', e => { S.senSort = e.target.value; renderSenRoster(); });

[['pl-q', S.q], ['pl-sq', S.sq], ['pl-party', S.party], ['pl-sort', S.sort]]
  .forEach(([id, v]) => { const el = $(id); if (el && v) el.value = v; });
/* Turnover is knowable exactly — 96 birth dates give ten years of forced
   vacancies, which is a fact no other page here can state. */
function drawWave() {
  const host = $('pl-wave');
  if (!host || typeof RETIRE_WAVE === 'undefined') return;
  const years = Object.keys(RETIRE_WAVE).sort();
  if (!years.length) return;
  const max = Math.max.apply(null, years.map(y => RETIRE_WAVE[y]));
  const soon = years.slice(0, 4).reduce((n, y) => n + RETIRE_WAVE[y], 0);
  host.innerHTML =
    '<div style="display:flex;align-items:flex-end;gap:5px;height:74px;margin-bottom:7px">' +
    years.map(y => '<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:4px;align-items:center">' +
      '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text)">' + RETIRE_WAVE[y] + '</span>' +
      '<span style="width:100%;height:' + Math.round(RETIRE_WAVE[y] / max * 52) + 'px;background:var(--wtf-accent);opacity:' +
        (0.45 + 0.55 * RETIRE_WAVE[y] / max) + ';border-radius:3px 3px 0 0"></span></div>').join('') +
    '</div>' +
    '<div style="display:flex;gap:5px">' + years.map(y =>
      '<span style="flex:1;text-align:center;font-family:var(--wtf-font-mono);font-size:8.5px;color:var(--wtf-text-muted)">' + y.slice(2) + '</span>').join('') + '</div>' +
    '<p class="rd-note" style="margin-top:10px">' + soon + ' seats turn over by ' + years[3] +
    ' \u2014 every one filled by the Prime Minister of the day, with no election involved. ' +
    'Derived from birth dates, so these dates are fixed rather than forecast.</p>';
}

/* One bill, both chambers. Two floor plans on a page only earn each other if
   something connects them. */
function drawBills() {
  const host = $('pl-bills');
  if (!host || typeof BILLS === 'undefined') return;
  const bar = (v, tot, col) => '<span style="display:block;height:5px;border-radius:3px;background:var(--wtf-bg);overflow:hidden">' +
    '<span style="display:block;height:100%;width:' + Math.round(v / tot * 100) + '%;background:' + col + ';border-radius:3px"></span></span>';
  const chamber = (lab, d, col) => d
    ? '<div><div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-bottom:4px">' + lab + '</div>' +
      bar(d.yea, d.yea + d.nay, col) +
      '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-2);margin-top:4px">' +
        d.yea + '\u2013' + d.nay + ' \u00b7 ' + d.date + '</div></div>'
    : '<div><div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-bottom:4px">' + lab + '</div>' +
      '<div style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-text-muted);padding:6px 0">Not yet voted</div></div>';
  host.innerHTML = BILLS.map(b =>
    '<div style="background:var(--wtf-bg-card);border:1px solid var(--wtf-border);border-left:3px solid ' +
      (b.amended ? 'var(--wtf-developing)' : 'var(--wtf-border)') + ';border-radius:9px;padding:12px 13px;margin-bottom:8px">' +
      '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;margin-bottom:10px">' +
        '<span style="font-family:var(--wtf-font-mono);font-size:11px;color:var(--wtf-text)">' + b.id + '</span>' +
        '<span style="font-family:var(--wtf-font-serif);font-size:14px;color:var(--wtf-text-2);flex:1;min-width:140px">' + b.title + '</span>' +
        '<span style="font-family:var(--wtf-font-mono);font-size:9px;letter-spacing:.06em;padding:2px 8px;border-radius:3px;background:var(--wtf-bg-panel);color:' +
          (b.stage.indexOf('Defeated') === 0 ? 'var(--wtf-contested)' : b.stage === 'Royal Assent' ? 'var(--wtf-established)' : 'var(--wtf-developing)') +
          '">' + b.stage + '</span></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">' +
        chamber('House of Commons', b.hoc, 'var(--wtf-local)') +
        chamber('Senate', b.sen, 'var(--wtf-accent)') +
      '</div>' +
      (b.amended ? '<div class="rd-note" style="margin-top:9px">The Senate rejected this as it arrived, so it returns to the House. ' +
        'An appointed chamber blocking an elected one is the constitutional friction worth watching.</div>' : '') +
    '</div>').join('');
}

drawLegend(); drawHoC(); drawSenate(); renderRoster(); renderSenRoster();
drawWave(); drawBills();
(function () {
  const h = location.hash.slice(1);
  if (h === 'senate' || h === 'ridings') showPane(h);
})();
