/* Story clusters — the I.N.K. view over the same corpus. */
const idx = k => BANDS.findIndex(b => b.k === k);
/* Same qualification as the Divergence page: six outlets, spread crossing the
   centre, and a named checkable point. Range alone is not a dispute. */
const DISPUTED = { c0:1, c1:1, c2:1, c4:1, c5:1, c7:1, c8:1, c9:1, c11:1, c12:1, c14:1, c15:1, c17:1, c18:1 };
function spreadScore(arts) { let d = 0, n = 0; for (let i = 0; i < arts.length; i++) for (let j = i + 1; j < arts.length; j++) { d += Math.abs(idx(arts[i].lean) - idx(arts[j].lean)); n++; } return n ? Math.round(d / n / 4 * 100) : 0; }
const ROWS = CLUSTERS.map(c => {
  const arts = ARTICLES.filter(a => a.cid === c.id).sort((p, q) => p.min - q.min);
  const sorted = arts.map(a => idx(a.lean)).sort((p, q) => p - q);
  const median = BANDS[sorted[Math.floor(sorted.length / 2)]];
  const lo = BANDS[sorted[0]], hi = BANDS[sorted[sorted.length - 1]];
  const pickupH = Math.round((arts[arts.length - 1].min - arts[0].min) / 60);
  const dispute = arts.length >= 6 && sorted[0] < 2 && sorted[sorted.length - 1] > 2 && !!DISPUTED[c.id];
  return { c, arts, median, lo, hi, spread: spreadScore(arts), pickupH, small: arts.length < 6, dispute, min: c.min,
           byBand: BANDS.map(b => arts.filter(a => a.lean === b.k).length) };
});
const $ = id => document.getElementById(id);
const S = { q: '', beat: '', size: '', median: '', sort: 'size', open: new URLSearchParams(location.search).get('story') || null };
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const spec = r => '<div class="wtf-dv-spec">' + BANDS.map((b, i) => r.byBand[i] ? '<i style="width:' + (r.byBand[i] / r.arts.length * 100) + '%;background:' + b.hex + '"></i>' : '').join('') + '</div>';
function visible() {
  const q = S.q.toLowerCase();
  return ROWS.filter(r => (!S.beat || r.c.beat === S.beat) &&
    (!S.size || (S.size === 'big' ? r.arts.length >= 12 : S.size === 'mid' ? r.arts.length >= 6 && r.arts.length < 12 : r.arts.length < 6)) &&
    (!S.median || r.median.k === S.median) &&
    (!q || (r.c.t + ' ' + r.c.beat + ' ' + r.arts.map(a => a.src).join(' ')).toLowerCase().includes(q)))
  .sort((a, b) => S.sort === 'spread' ? b.spread - a.spread : S.sort === 'recent' ? a.min - b.min : S.sort === 'pickup' ? b.pickupH - a.pickupH : b.arts.length - a.arts.length);
}
function card(r) {
  const open = S.open === r.c.id;
  const first = r.arts[0];
  return '<div class="wtf-dv-card' + (open ? ' open' : '') + '" id="cl-' + r.c.id + '" style="' + (r.small ? 'border-left:3px solid var(--wtf-developing)' : '') + '">' +
    '<div class="wtf-dv-head" role="button" tabindex="0" aria-expanded="' + open + '" data-id="' + r.c.id + '">' +
      '<div><div class="wtf-dv-t">' + esc(r.c.t) + '</div>' +
        '<div class="wtf-dv-m">' + esc(r.c.beat) + ' &middot; ' + r.c.prov + ' &middot; ' + r.arts.length + ' outlet' + (r.arts.length === 1 ? '' : 's') + ' &middot; first ' + esc(first.src) + ' ' + ago(first.min) + ' &middot; pickup ' + r.pickupH + 'h' + (r.small ? ' &middot; <span style="color:var(--wtf-developing)">blindspot seed</span>' : '') + (r.dispute ? ' &middot; <span style="color:var(--wtf-contested)">checkable dispute</span>' : '') + '</div>' +
        (r.c.note ? '<div class="wtf-dv-q">' + esc(r.c.note) + '</div>' : '') + '</div>' +
      '<div class="wtf-dv-hide">' + spec(r) + '<div class="wtf-dv-specl"><span>' + r.lo.l + '</span><span>&rarr;</span><span>' + r.hi.l + '</span></div></div>' +
      '<div class="wtf-dv-hide wtf-dv-score" style="color:' + (r.spread >= 60 ? 'var(--wtf-contested)' : r.spread >= 35 ? 'var(--wtf-developing)' : 'var(--wtf-text-2)') + '" title="Spread, 0–100">' + r.spread + '</div>' +
      '<div class="wtf-dv-hide" style="text-align:center"><span class="wtf-dv-pill" style="background:' + r.median.hex + '1f;color:' + r.median.hex + '">' + r.median.l + ' median</span></div>' +
      '<div class="wtf-dv-car">&#9656;</div></div>' +
    '<div class="wtf-dv-body">' +
      '<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px" class="wtf-dv-sides">' +
        '<div><div class="psec" style="margin-bottom:9px">Pickup order &middot; who filed first</div><div class="wtf-dv-tl">' +
          r.arts.map((a, i) => '<div class="tm">' + (i === 0 ? 'first' : '+' + Math.round((a.min - first.min) / 60) + 'h') + '</div><div class="dot" style="background:' + bandOf(a.lean).hex + '"></div><div class="ev' + (i === r.arts.length - 1 ? ' last' : '') + '"><b>' + esc(a.src) + '</b> &middot; ' + bandOf(a.lean).l + (a.lang === 'fr' ? ' &middot; FR' : '') + '</div>').join('') +
        '</div></div>' +
        '<div><div class="psec" style="margin-bottom:9px">Every headline &middot; same event</div>' +
          r.arts.map(a => '<div class="wtf-dv-hl">&ldquo;' + esc(headlineFor(a)) + '&rdquo;<small>' + esc(a.src) + ' &middot; <span style="color:' + bandOf(a.lean).hex + '">' + bandOf(a.lean).l + '</span></small></div>').join('') + '</div></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:9px;margin-top:14px">' +
        [['Outlets', r.arts.length], ['Spread', r.spread + ' / 100'], ['Median', r.median.l], ['Pickup', r.pickupH + ' hours'], ['Range', r.lo.l + ' &rarr; ' + r.hi.l]]
        .map(k => '<div style="background:var(--wtf-bg);border:1px solid var(--wtf-border);border-radius:8px;padding:10px 12px"><div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;color:#5d6875">' + k[0] + '</div><div style="font-family:var(--wtf-font-mono);font-size:14px;color:var(--wtf-text);margin-top:3px">' + k[1] + '</div></div>').join('') + '</div>' +
      '<div class="wtf-dv-xl"><a class="wtf-dv-chip" href="wtf-article.html?id=' + encodeURIComponent(first.id) + '">Open the originating piece &rarr;</a>' +
        (r.dispute ? '<a class="wtf-dv-chip" href="wtf-divergence.html?story=' + r.c.id + '" style="border-color:rgba(224,82,82,.4);color:var(--wtf-contested)">How they diverge &rarr;</a>' : '') +
        (r.small ? '<a class="wtf-dv-chip" href="wtf-blindspot.html" style="border-color:rgba(245,158,11,.4);color:var(--wtf-developing)">Blindspot view &rarr;</a>' : '') +
        '<a class="wtf-dv-chip" href="wtf-archive.html#q=' + encodeURIComponent(r.c.t.split(' ').slice(0, 3).join(' ')) + '">In the archive &rarr;</a></div>' +
    '</div></div>';
}
function render() {
  const rows = visible();
  $('cl-count').textContent = rows.length + ' of ' + ROWS.length + ' clusters';
  $('cl-list').innerHTML = rows.length ? rows.map(card).join('') : '<div class="wtf-dv-none">No cluster matches that filter.</div>';
  if (S.open) { const el = $('cl-' + S.open); if (el && !render.scrolled) { render.scrolled = true; setTimeout(() => window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 80 }), 60); } }
}
$('cl-stats').innerHTML = [
  [ROWS.length, 'Clusters'], [ARTICLES.length, 'Articles clustered'],
  [Math.round(ARTICLES.length / ROWS.length * 10) / 10, 'Outlets per story'],
  [ROWS.filter(r => r.small).length, 'Blindspot seeds'],
  [ROWS.filter(r => r.dispute).length, 'Checkable disputes']
].map(k => '<div class="stat"><div class="stat-n">' + k[0] + '</div><div class="stat-l">' + k[1] + '</div></div>').join('');
$('cl-beat').innerHTML += [...new Set(CLUSTERS.map(c => c.beat))].sort().map(b => '<option>' + b + '</option>').join('');
$('cl-median').innerHTML += BANDS.map(b => '<option value="' + b.k + '">' + b.l + '</option>').join('');
$('cl-list').addEventListener('click', e => { const h = e.target.closest('.wtf-dv-head'); if (!h) return; S.open = S.open === h.dataset.id ? null : h.dataset.id; render(); });
$('cl-list').addEventListener('keydown', e => { const h = e.target.closest('.wtf-dv-head'); if (h && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); h.click(); } });
$('cl-q').addEventListener('input', e => { S.q = e.target.value.trim(); render(); });
['beat', 'size', 'median'].forEach(k => $('cl-' + k).addEventListener('change', e => { S[k] = e.target.value; render(); }));
document.querySelectorAll('.wtf-dv-sort button').forEach(b => b.addEventListener('click', () => { S.sort = b.dataset.s; document.querySelectorAll('.wtf-dv-sort button').forEach(x => x.classList.toggle('on', x === b)); render(); }));
render();
