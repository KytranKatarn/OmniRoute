/* Divergence — built from the same clusters as Latest and the article page.
   The point in dispute is editorial; everything else is measured. */
const POINT = {
  c0:'Whether the findings implicate the current or the previous government',
  c1:'Whether the hold signals a cut at the next meeting',
  c2:'Whether the cap has statutory force before 2030',
  c4:'Whether the billing caps apply to existing private clinics',
  c5:'Whether the cooling is policy or base effects',
  c7:'What the enforcement numbers show about the buyback',
  c8:'Whether the funding is new money or reallocated',
  c9:'Whether the deal averted job action or deferred it',
  c11:'Whether royalties rose because of price or volume',
  c12:'Whether the ruling narrows or restates the duty to consult',
  c14:'Whether the staffing plan is funded in the current fiscal year',
  c15:'Which sectors are exposed at the stated tariff rate',
  c17:'Whether the quota cut follows the science advice or departs from it',
  c18:'Number of units that will be below market rate'
};
const OPINION = { c1:1, c9:1 };
const idx = k => BANDS.findIndex(b => b.k === k);
function score(arts) {
  let d = 0, n = 0;
  for (let i = 0; i < arts.length; i++) for (let j = i + 1; j < arts.length; j++) { d += Math.abs(idx(arts[i].lean) - idx(arts[j].lean)); n++; }
  return n ? Math.round(d / n / 4 * 100) : 0;
}
const ROWS = CLUSTERS.map(c => {
  const arts = ARTICLES.filter(a => a.cid === c.id).sort((p, q) => p.min - q.min);
  const L = arts.filter(a => idx(a.lean) < 2), R = arts.filter(a => idx(a.lean) > 2), C = arts.filter(a => idx(a.lean) === 2);
  const s = score(arts);
  const qualifies = arts.length >= 6 && L.length && R.length && !!POINT[c.id];
  const why = arts.length < 6 ? 'fewer than six outlets' : !(L.length && R.length) ? 'spread does not cross the centre' : !POINT[c.id] ? 'disagreement is on tone, not a checkable point' : '';
  return { c, arts, L, R, C, score: s, qualifies, why, point: POINT[c.id] || null, opinion: !!OPINION[c.id],
           verdict: OPINION[c.id] ? null : c.verdict, first: arts[0], last: arts[arts.length - 1], min: c.min };
});
const $ = id => document.getElementById(id);
const S = { q: '', verdict: '', beat: '', sort: 'score', excl: false, open: new URLSearchParams(location.search).get('story') || null };
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const spec = arts => { const t = arts.length || 1; return '<div class="wtf-dv-spec">' + BANDS.map(b => { const n = arts.filter(a => a.lean === b.k).length; return n ? '<i style="width:' + (n / t * 100) + '%;background:' + b.hex + '"></i>' : ''; }).join('') + '</div>'; };
const vpill = r => r.opinion ? '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted)">Opinion, not scored</span>'
  : r.verdict ? '<span class="wtf-dv-pill" style="background:' + VERDICTS[r.verdict].c + '1f;color:' + VERDICTS[r.verdict].c + '">' + VERDICTS[r.verdict].g + ' ' + VERDICTS[r.verdict].l + '</span>'
  : '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted)">&#9675; Not yet checked</span>';
const scoreCol = s => s >= 60 ? 'var(--wtf-contested)' : s >= 35 ? 'var(--wtf-developing)' : 'var(--wtf-text-2)';

function visible() {
  const q = S.q.toLowerCase();
  return ROWS.filter(r => (S.excl ? !r.qualifies : r.qualifies) &&
    (!S.verdict || (S.verdict === 'none' ? !r.verdict : r.verdict === S.verdict)) &&
    (!S.beat || r.c.beat === S.beat) &&
    (!q || (r.c.t + ' ' + (r.point || '') + ' ' + r.arts.map(a => a.src).join(' ')).toLowerCase().includes(q)))
  .sort((a, b) => S.sort === 'outlets' ? b.arts.length - a.arts.length : S.sort === 'recent' ? a.min - b.min : b.score - a.score || b.arts.length - a.arts.length);
}
function side(label, arts, hex) {
  return '<div class="wtf-dv-side" style="--sc:' + hex + '"><div class="wtf-dv-sl"><span>' + label + '</span><span>' + arts.length + ' article' + (arts.length === 1 ? '' : 's') + '</span></div>' +
    (arts.length ? arts.slice(0, 4).map(a => '<div class="wtf-dv-hl">&ldquo;' + esc(headlineFor(a)) + '&rdquo;<small>' + esc(a.src) + ' &middot; ' + bandOf(a.lean).l + ' &middot; ' + ago(a.min) + '</small></div>').join('') +
      (arts.length > 4 ? '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin-top:6px">+' + (arts.length - 4) + ' more in the cluster</div>' : '')
      : '<div style="font-size:12px;color:var(--wtf-text-muted)">No outlet on this side.</div>') + '</div>';
}
function card(r) {
  const open = S.open === r.c.id;
  return '<div class="wtf-dv-card' + (open ? ' open' : '') + '" id="dv-' + r.c.id + '">' +
    '<div class="wtf-dv-head" role="button" tabindex="0" aria-expanded="' + open + '" data-id="' + r.c.id + '">' +
      '<div><div class="wtf-dv-t">' + esc(r.c.t) + '</div><div class="wtf-dv-m">' + esc(r.c.beat) + ' &middot; ' + r.c.prov + ' &middot; ' + r.arts.length + ' outlets &middot; first filed ' + ago(r.first.min) + '</div>' +
        '<div class="wtf-dv-q">' + (r.point ? '<b style="color:var(--wtf-text);font-weight:500">In dispute:</b> ' + esc(r.point) : '<span style="color:var(--wtf-text-muted)">Excluded &mdash; ' + r.why + '.</span>') + '</div></div>' +
      '<div class="wtf-dv-hide">' + spec(r.arts) + '<div class="wtf-dv-specl"><span>L ' + r.L.length + '</span><span>C ' + r.C.length + '</span><span>R ' + r.R.length + '</span></div></div>' +
      '<div class="wtf-dv-hide wtf-dv-score" style="color:' + scoreCol(r.score) + '" title="Divergence score">' + r.score + '</div>' +
      '<div class="wtf-dv-hide" style="text-align:center">' + vpill(r) + '</div>' +
      '<div class="wtf-dv-car">&#9656;</div></div>' +
    '<div class="wtf-dv-body">' +
      '<div class="wtf-dv-sides">' + side('Reads it one way', r.L, BANDS[0].hex) + side('Reads it the other', r.R, BANDS[4].hex) + '</div>' +
      (r.C.length ? '<div style="font-size:12px;color:var(--wtf-text-muted);margin-top:10px">' + r.C.length + ' centre article' + (r.C.length === 1 ? '' : 's') + ' report the event without taking the disputed point: ' + r.C.slice(0, 5).map(a => esc(a.src)).join(', ') + (r.C.length > 5 ? '&hellip;' : '') + '</div>' : '') +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;margin-top:14px">' +
        [['Divergence', r.score + ' / 100', scoreCol(r.score)], ['Split', r.L.length + ' / ' + r.R.length, 'var(--wtf-text)'], ['Pickup', Math.round((r.last.min - r.first.min) / 60) + ' hours', 'var(--wtf-text)'], ['Verdict', r.opinion ? 'Opinion' : r.verdict ? VERDICTS[r.verdict].l : 'Not yet', r.verdict && !r.opinion ? VERDICTS[r.verdict].c : 'var(--wtf-text-muted)']]
        .map(k => '<div style="background:var(--wtf-bg);border:1px solid var(--wtf-border);border-radius:8px;padding:10px 12px"><div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;color:#5d6875">' + k[0] + '</div><div style="font-family:var(--wtf-font-mono);font-size:15px;color:' + k[2] + ';margin-top:3px">' + k[1] + '</div></div>').join('') + '</div>' +
      (r.opinion ? '<div style="font-size:12px;line-height:1.6;color:var(--wtf-text-muted);margin-top:11px">The dispute is about what happens next. No document settles a forecast, so V.E.R.I.F.Y. does not score it; the split is still real.</div>' : '') +
      '<div class="wtf-dv-xl"><a class="wtf-dv-chip" href="wtf-clusters.html?story=' + r.c.id + '">Full cluster &amp; pickup order &rarr;</a>' +
        '<a class="wtf-dv-chip" href="wtf-article.html?id=' + encodeURIComponent(r.first.id) + '">Read the originating piece &rarr;</a>' +
        '<a class="wtf-dv-chip" href="wtf-blindspot.html">Blindspot view &rarr;</a></div>' +
    '</div></div>';
}
function render() {
  const rows = visible();
  $('dv-count').textContent = rows.length + ' of ' + ROWS.filter(r => S.excl ? !r.qualifies : r.qualifies).length + (S.excl ? ' excluded' : ' disputes');
  $('dv-list').innerHTML = rows.length ? rows.map(card).join('') : '<div class="wtf-dv-none">No dispute matches that filter.</div>';
  $('dv-excl').textContent = S.excl ? 'Back to disputes' : 'Show ' + ROWS.filter(r => !r.qualifies).length + ' excluded stories';
  $('dv-excl').style.color = S.excl ? 'var(--wtf-accent)' : '';
  if (S.open) { const el = $('dv-' + S.open); if (el && !render.scrolled) { render.scrolled = true; setTimeout(() => window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 80 }), 60); } }
}
const q = ROWS.filter(r => r.qualifies);
$('dv-stats').innerHTML = [
  [q.length, 'Disputes called'], [ROWS.length - q.length, 'Stories excluded'],
  [q.filter(r => r.verdict === 'contested').length, 'Contested'],
  [q.filter(r => r.opinion).length, 'Opinion, not scored'],
  [Math.round(q.reduce((n, r) => n + r.score, 0) / (q.length || 1)), 'Mean divergence']
].map(k => '<div class="stat"><div class="stat-n">' + k[0] + '</div><div class="stat-l">' + k[1] + '</div></div>').join('');
$('dv-beat').innerHTML += [...new Set(CLUSTERS.map(c => c.beat))].sort().map(b => '<option>' + b + '</option>').join('');
$('dv-list').addEventListener('click', e => { const h = e.target.closest('.wtf-dv-head'); if (!h) return; S.open = S.open === h.dataset.id ? null : h.dataset.id; render(); });
$('dv-list').addEventListener('keydown', e => { const h = e.target.closest('.wtf-dv-head'); if (h && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); h.click(); } });
$('dv-q').addEventListener('input', e => { S.q = e.target.value.trim(); render(); });
$('dv-verdict').addEventListener('change', e => { S.verdict = e.target.value; render(); });
$('dv-beat').addEventListener('change', e => { S.beat = e.target.value; render(); });
$('dv-excl').addEventListener('click', () => { S.excl = !S.excl; render(); });
document.querySelectorAll('.wtf-dv-sort button').forEach(b => b.addEventListener('click', () => { S.sort = b.dataset.s; document.querySelectorAll('.wtf-dv-sort button').forEach(x => x.classList.toggle('on', x === b)); render(); }));
if (S.open && !ROWS.find(r => r.c.id === S.open && r.qualifies)) S.excl = !!ROWS.find(r => r.c.id === S.open);
render();
