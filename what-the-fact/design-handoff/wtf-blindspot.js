/* Blindspot, computed from the corpus rather than typed in.
   Every number on the page comes from the same pass, so the stat row and the
   table can never disagree — which was the original defect here. */

/* Calling a blindspot needs a ratio, not a share. An 8-to-2 split is a real
   gap even though the difference is only 38% of all coverage, because the
   centre pile dilutes the score. So: the quieter side must hold a quarter or
   less of the two-sided coverage, and be at least three pieces behind. */
const MIN_TOTAL  = 4;   // fewer outlets than this and nothing is a pattern
const MIN_SIDES  = 4;   // partisan coverage needed before a side can be judged
const MINOR_MAX  = 0.25;
const MIN_DIFF   = 3;

const SIDE_OF = { 'left':'L', 'center-left':'L', 'center':'C', 'center-right':'R', 'right':'R' };
const SIDE_HEX = { L:'#d84b47', C:'#929aa5', R:'#4a72d8' };

/* Which outlets belong to which side, from their own home band in the pool —
   needed to say who was ABSENT, not just who was present. */
const HOME = {};
POOL.forEach(([name, band]) => { HOME[name] = SIDE_OF[band]; });
const ROSTER = { L:[], C:[], R:[] };
Object.keys(HOME).forEach(n => { if (ROSTER[HOME[n]]) ROSTER[HOME[n]].push(n); });

const ROWS = CLUSTERS.map(c => {
  const arts = ARTICLES.filter(a => a.cid === c.id);
  const side = { L:[], C:[], R:[] };
  arts.forEach(a => side[SIDE_OF[a.lean]].push(a));
  const L = side.L.length, C = side.C.length, R = side.R.length;
  const total = L + C + R;
  const gap = total ? Math.round(Math.abs(L - R) / total * 100) : 0;
  const sides = L + R, minor = Math.min(L, R), diff = Math.abs(L - R);
  const thin = total < MIN_TOTAL;
  const thinSides = !thin && sides < MIN_SIDES;
  const called = !thin && !thinSides && (sides ? minor / sides <= MINOR_MAX : false) && diff >= MIN_DIFF;
  const missing = called ? (L > R ? 'R' : 'L') : null;
  const firstMin = Math.min.apply(null, arts.map(a => a.min));
  const lastMin = Math.max.apply(null, arts.map(a => a.min));
  return { c, arts, side, L, C, R, total, gap, thin, thinSides, missing,
           open: +((lastMin - firstMin) / 60).toFixed(1), age: firstMin };
});

const label = k => k === 'L' ? 'Left' : k === 'R' ? 'Right' : 'Centre';
const verdictOf = r => r.thin ? ['Too thin to call', 'var(--wtf-text-muted)', '#2a3547']
  : r.thinSides ? ['Sides too thin', 'var(--wtf-text-muted)', '#2a3547']
  : r.missing ? [label(r.missing) + ' blindspot', SIDE_HEX[r.missing], SIDE_HEX[r.missing]]
  : ['Balanced', 'var(--wtf-text-muted)', '#2a3547'];

/* Why a story might be missing from one side, argued from the corpus rather
   than asserted. Suppression is the last explanation to reach for, not the first. */
function reasons(r) {
  const out = [];
  const m = r.missing;
  if (!m) return out;
  const roster = ROSTER[m] || [];
  const covered = new Set(r.arts.map(a => a.src));
  const absent = roster.filter(n => !covered.has(n));
  const provOutlets = roster.filter(n => {
    const st = OUTLET_STATS[n];
    return st && st.provs && st.provs[r.c.prov];
  });
  if (!provOutlets.length) {
    out.push(['No bureau on that side in ' + (PROV_NAMES[r.c.prov] || r.c.prov),
      'No outlet on the ' + label(m).toLowerCase() + ' side has filed from this province in the corpus at all, on any story.']);
  }
  const beatDepth = roster.reduce((n, o) => {
    const st = OUTLET_STATS[o];
    return n + (st && st.beats && st.beats[r.c.beat] ? st.beats[r.c.beat] : 0);
  }, 0);
  if (beatDepth < 4) {
    out.push([r.c.beat + ' is thinly staffed on that side',
      'Outlets on the ' + label(m).toLowerCase() + ' side have filed ' + beatDepth + ' pieces on ' + r.c.beat.toLowerCase() + ' across the whole corpus.']);
  }
  if (r.open < 6) {
    out.push(['The story is ' + r.open + ' hours old',
      'A gap this young is a news cycle, not an editorial position. It may close today.']);
  }
  if (absent.length && provOutlets.length && beatDepth >= 4) {
    out.push(['Staffed, and still absent',
      absent.length + ' outlet' + (absent.length === 1 ? '' : 's') + ' on that side cover this beat and this province elsewhere, and did not carry this.']);
  }
  return out;
}

/* The same story as each side framed it. Headlines come from the corpus framing
   model, so the wording shown always matches the lean recorded for that piece. */
function flip(r) {
  const pick = k => {
    const list = r.side[k];
    if (!list.length) return null;
    const a = list.slice().sort((x, y) => x.min - y.min)[0];
    return { a, head: headlineFor(a) };
  };
  return ['L', 'C', 'R'].map(k => ({ k, v: pick(k) }));
}

let S = { q:'', side:'', beat:'', prov:'', sort:'gap', bal:true, open:{} };

function visible() {
  const q = S.q.toLowerCase();
  return ROWS.filter(r => {
    if (S.side === 'balanced') { if (r.missing || r.thin || r.thinSides) return false; }
    else if (S.side && r.missing !== (S.side === 'left' ? 'L' : 'R')) return false;
    if (!S.bal && !S.side && !r.missing) return false;
    if (S.beat && r.c.beat !== S.beat) return false;
    if (S.prov && r.c.prov !== S.prov) return false;
    if (q) {
      const hay = (r.c.t + ' ' + r.c.beat + ' ' + r.c.prov + ' ' + (r.c.note || '') + ' ' +
                   r.arts.map(a => a.src).join(' ')).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }).sort((a, b) =>
    S.sort === 'total' ? b.total - a.total :
    S.sort === 'open'  ? b.open - a.open :
    S.sort === 'recent'? a.age - b.age :
                         b.gap - a.gap || b.total - a.total);
}

function renderStats() {
  const called = ROWS.filter(r => r.missing);
  const el = [
    [String(called.length), 'Blindspots called'],
    [String(ROWS.filter(r => !r.missing && !r.thin && !r.thinSides).length), 'Balanced'],
    [String(called.filter(r => r.missing === 'L').length), 'Left-side gaps'],
    [String(called.filter(r => r.missing === 'R').length), 'Right-side gaps'],
    [String(ROWS.filter(r => r.thin || r.thinSides).length), 'Too thin to call']
  ];
  document.getElementById('bs-stats').innerHTML = el.map(([n, l], i) =>
    '<div class="stat"><div class="stat-n"' + (i === 2 ? ' style="color:var(--wtf-left)"' : i === 3 ? ' style="color:var(--wtf-right)"' : '') + '>' + n + '</div>' +
    '<div class="stat-l">' + l + '</div></div>').join('');
}

function rowHTML(r, i) {
  const v = verdictOf(r);
  const w = k => r.total ? (r[k] / r.total * 100) : 0;
  const isOpen = !!S.open[r.c.id];
  const fl = flip(r);
  const rs = reasons(r);
  const roster = r.missing ? (ROSTER[r.missing] || []) : [];
  const covered = new Set(r.arts.map(a => a.src));
  const absent = roster.filter(n => !covered.has(n));

  return '<div class="wtf-bs-row' + (isOpen ? ' open' : '') + '" data-id="' + r.c.id + '" style="border-left-color:' + v[2] + '">' +
    '<div class="wtf-bs-head">' +
      '<div style="min-width:0"><div class="wtf-bs-t">' + r.c.t + '</div>' +
        '<div class="wtf-bs-m">' + r.c.beat.toUpperCase() + ' &middot; ' + r.c.prov + ' &middot; ' +
        r.total + ' outlet' + (r.total === 1 ? '' : 's') + ' &middot; ' + ago(r.age) + '</div></div>' +
      '<div class="wtf-bs-hide"><div class="wtf-bs-bar">' +
        '<i style="width:' + w('L') + '%;background:' + SIDE_HEX.L + '"></i>' +
        '<i style="width:' + w('C') + '%;background:' + SIDE_HEX.C + '"></i>' +
        '<i style="width:' + w('R') + '%;background:' + SIDE_HEX.R + '"></i></div>' +
        '<div class="wtf-bs-barl"><span>L ' + r.L + '</span><span>C ' + r.C + '</span><span>R ' + r.R + '</span></div></div>' +
      '<div class="wtf-bs-hide wtf-bs-g" style="color:' + (r.missing ? v[1] : 'var(--wtf-text-muted)') + '">' + r.gap + '</div>' +
      '<div class="wtf-bs-hide" style="text-align:center"><span class="wtf-bs-pill" style="background:' + v[1] + '1f;color:' + v[1] + '">' + v[0] + '</span></div>' +
      '<div class="wtf-bs-car">&#9656;</div>' +
    '</div>' +
    '<div class="wtf-bs-body">' +
      (r.c.note ? '<div class="wtf-bs-sec">What the split is about</div><div style="font-size:12.5px;line-height:1.7;color:var(--wtf-text-2)">' + r.c.note + '</div>' : '') +

      '<div class="wtf-bs-sec">The same story, as each side wrote it</div>' +
      '<div class="wtf-bs-flip">' + fl.map(f =>
        '<div class="wtf-bs-fq" style="border-left-color:' + SIDE_HEX[f.k] + '">' +
        '<b style="color:' + SIDE_HEX[f.k] + '">' + label(f.k) + '</b>' +
        (f.v ? '<q>' + f.v.head + '</q><em>' + f.v.a.src + ' &middot; ' + ago(f.v.a.min) + '</em>'
             : '<q style="color:var(--wtf-text-muted)">Not carried.</q><em>No outlet on this side filed</em>') +
        '</div>').join('') + '</div>' +

      '<div class="wtf-bs-sec">Who carried it, and who did not</div>' +
      '<div class="wtf-bs-grid">' +
        ['L', 'C', 'R'].map(k =>
          '<div class="wtf-bs-box"><div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:' + SIDE_HEX[k] + '">' +
          label(k) + ' &middot; ' + r[k] + ' carried</div><div class="wtf-bs-o">' +
          (r.side[k].length ? r.side[k].map(a => '<span>' + a.src + '</span>').join('')
            : '<span class="miss">none</span>') + '</div></div>').join('') +
      '</div>' +
      (absent.length ? '<div class="wtf-bs-box" style="margin-top:10px;border-style:dashed">' +
        '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-developing)">On the ' +
        label(r.missing).toLowerCase() + ' side and absent &middot; ' + absent.length + '</div>' +
        '<div class="wtf-bs-o">' + absent.map(n => '<span class="miss">' + n + '</span>').join('') + '</div></div>' : '') +

      (rs.length ? '<div class="wtf-bs-sec">Why it might be missing</div><div class="wtf-bs-why">' +
        rs.map(x => '<div><b>' + x[0] + '</b>' + x[1] + '</div>').join('') +
        '<div style="color:var(--wtf-text-muted);font-size:11px;padding-top:7px;border-top:1px solid var(--wtf-border)">' +
        'None of these is suppression. A gap becomes a story about an outlet only once the beat is staffed, the bureau exists, and the piece still did not run.</div></div>' : '') +

      '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">' +
        '<a class="wtf-bs-chip" href="wtf-clusters.html?story=' + encodeURIComponent(r.arts[0].cid) + '">Full cluster &amp; pickup order &rarr;</a>' +
        '<a class="wtf-bs-chip" href="wtf-article.html?id=' + encodeURIComponent(r.arts[0].id) + '">Read the originating piece &rarr;</a>' +
        '<a class="wtf-bs-chip" href="wtf-divergence.html?story=' + encodeURIComponent(r.arts[0].cid) + '">How they diverge &rarr;</a>' +
      '</div>' +
    '</div></div>';
}

function renderList() {
  const rows = visible();
  document.getElementById('bs-count').textContent =
    rows.length + ' of ' + ROWS.length + ' stories';
  const box = document.getElementById('bs-list');
  box.innerHTML = rows.length ? rows.map(rowHTML).join('')
    : '<div class="wtf-bs-empty"><div style="font-family:var(--wtf-font-serif);font-size:18px;margin-bottom:5px">No story matches this filter</div>' +
      '<div style="font-size:13px;color:var(--wtf-text-muted)">The corpus is a sample window, not the whole of Canadian news.</div></div>';
}

function renderPersist() {
  const called = ROWS.filter(r => r.missing).slice().sort((a, b) => b.open - a.open).slice(0, 6);
  const max = Math.max.apply(null, called.map(r => r.open).concat([1]));
  document.getElementById('bs-persist').innerHTML = called.length ? called.map(r => {
    const band = r.open >= 12 ? 'var(--wtf-contested)' : r.open >= 6 ? 'var(--wtf-developing)' : 'var(--wtf-established)';
    return '<div class="wtf-bs-line"><span style="font-size:12px;color:var(--wtf-text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + r.c.t + '</span>' +
      '<span class="wtf-bs-track"><i style="width:' + (r.open / max * 100) + '%;background:' + band + '"></i></span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;text-align:right;color:' + band + '">' + r.open + 'h</span></div>';
  }).join('') : '<div style="font-size:12px;color:var(--wtf-text-muted)">No gap is currently open.</div>';
}

function renderOutlets() {
  const miss = {};
  ROWS.filter(r => r.missing).forEach(r => {
    const covered = new Set(r.arts.map(a => a.src));
    (ROSTER[r.missing] || []).forEach(n => { if (!covered.has(n)) miss[n] = (miss[n] || 0) + 1; });
  });
  const list = Object.keys(miss).map(n => ({ n, v:miss[n], side:HOME[n] }))
    .sort((a, b) => b.v - a.v).slice(0, 8);
  const max = Math.max.apply(null, list.map(x => x.v).concat([1]));
  document.getElementById('bs-outlets').innerHTML = list.length ? list.map(x =>
    '<div class="wtf-bs-line"><a href="wtf-outlet.html?o=' + encodeURIComponent(x.n) + '" style="font-size:12px;color:var(--wtf-text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none">' + x.n + '</a>' +
    '<span class="wtf-bs-track"><i style="width:' + (x.v / max * 100) + '%;background:' + SIDE_HEX[x.side] + '"></i></span>' +
    '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;text-align:right;color:var(--wtf-text)">' + x.v + '</span></div>').join('')
    : '<div style="font-size:12px;color:var(--wtf-text-muted)">Nothing to report in this window.</div>';
}

/* ── controls ─────────────────────────────────────────────────────────── */
const beats = Array.from(new Set(ROWS.map(r => r.c.beat))).sort();
const provs = Array.from(new Set(ROWS.map(r => r.c.prov))).sort();
document.getElementById('bs-beat').innerHTML = '<option value="">Every beat</option>' +
  beats.map(b => '<option value="' + b + '">' + b + '</option>').join('');
document.getElementById('bs-prov').innerHTML = '<option value="">Every province</option>' +
  provs.map(p => '<option value="' + p + '">' + (PROV_NAMES[p] || p) + '</option>').join('');

document.getElementById('bs-q').addEventListener('input', e => { S.q = e.target.value.trim(); renderList(); });
document.getElementById('bs-side').addEventListener('change', e => { S.side = e.target.value; renderList(); });
document.getElementById('bs-beat').addEventListener('change', e => { S.beat = e.target.value; renderList(); });
document.getElementById('bs-prov').addEventListener('change', e => { S.prov = e.target.value; renderList(); });
document.getElementById('bs-showbal').addEventListener('click', function () {
  S.bal = !S.bal;
  this.classList.toggle('on', S.bal);
  this.textContent = S.bal ? 'Show balanced rows' : 'Balanced rows hidden';
  renderList();
});
document.querySelectorAll('.wtf-bs-sort').forEach(el => el.addEventListener('click', () => {
  S.sort = el.dataset.sort;
  document.querySelectorAll('.wtf-bs-sort').forEach(x => x.classList.toggle('on', x === el));
  renderList();
}));
document.getElementById('bs-list').addEventListener('click', e => {
  if (e.target.closest('a')) return;
  const row = e.target.closest('.wtf-bs-row');
  if (!row) return;
  const id = row.dataset.id;
  S.open[id] = !S.open[id];
  row.classList.toggle('open', S.open[id]);
});

renderStats(); renderList(); renderPersist(); renderOutlets();
