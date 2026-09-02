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
let S = { q: '', party: '', sort: 'party', sq: '', caucus: '' };

/* ── tabs ─────────────────────────────────────────────────────────────── */
document.querySelectorAll('.wtf-pl-tab[data-pane]').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.wtf-pl-tab[data-pane]').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.wtf-pl-pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + b.dataset.pane));
  tip.style.display = 'none';
}));

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
  const g = chamber(svg, { speaker: SEAT_SPEAKER, rule: '#2b3a4f', label: '#5d6875' });
  const [cx, cy] = SEAT_SPEAKER;

  MPS.forEach(m => {
    if (hidden.has(m.party)) return;
    const [x, y] = m.xy;
    const d = Math.hypot(x - cx, y - cy);
    // Inner rows sit closer together, so their dots shrink to stay legible.
    let r = 1.9 + (d - 60) / (300 - 60) * 2.6;
    r = Math.max(1.7, Math.min(4.4, r));
    if (m.leader) r += 1.1;

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
      (m.leader ? m.leader + ' \u00b7 ' : '') + m.party + ' \u00b7 ' + m.arts + ' articles'));
    c.addEventListener('mousemove', e => showTip(e, m.name,
      (m.leader ? m.leader + ' \u00b7 ' : '') + m.party + ' \u00b7 ' + m.arts + ' articles'));
    c.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    c.addEventListener('click', () => { location.href = 'wtf-search.html?q=' + encodeURIComponent(m.name); });
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
    c.addEventListener('click', () => { location.href = 'wtf-search.html?q=' + encodeURIComponent(s.name); });
    g.appendChild(c);
  });
}

/* ── rosters ──────────────────────────────────────────────────────────── */
const PERSON = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="8" r="3.4"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/></svg>';

/* Only five ridings are on record. Everything else says so rather than
   guessing — a wrong riding on a named MP is a fabricated fact. */
function ridingOf(m) {
  return m.riding
    ? m.riding + ' <span style="color:#5d6875">' + m.provKnown + '</span>'
    : '<span style="color:#3a4657">Riding not recorded</span>';
}

function card(p, colour, badge, sub, arts) {
  return '<a class="wtf-pl-card" style="--pc:' + colour + '" href="wtf-search.html?q=' + encodeURIComponent(p.name) + '">' +
    '<div class="wtf-pl-ph">' + PERSON + '</div>' +
    '<div class="wtf-pl-nm">' + p.name + '</div>' +
    '<div class="wtf-pl-rd" style="color:' + colour + '">' + badge + '</div>' +
    '<div class="wtf-pl-rd">' + sub + '</div>' +
    (p.leader ? '<div class="wtf-pl-role">' + p.leader + '</div>' : '') +
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

function renderRoster() {
  const list = mpVisible();
  $('pl-count').textContent = list.length + ' of ' + MPS.length + ' members';
  if (!list.length) {
    $('pl-roster').innerHTML = '<div class="wtf-pl-none"><div style="font-family:var(--wtf-font-serif);font-size:18px;margin-bottom:5px">No member matches</div>' +
      '<div style="font-size:13px;color:var(--wtf-text-muted)">Clear a filter, or check the party legend above &mdash; a hidden party is also hidden here.</div></div>';
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
$('pl-party').addEventListener('change', e => { S.party = e.target.value; renderRoster(); });
$('pl-sort').addEventListener('change', e => { S.sort = e.target.value; renderRoster(); });
$('pl-sq').addEventListener('input', e => { S.sq = e.target.value.trim(); renderSenRoster(); });
$('pl-caucus').addEventListener('change', e => { S.caucus = e.target.value; renderSenRoster(); });

drawLegend(); drawHoC(); drawSenate(); renderRoster(); renderSenRoster();
