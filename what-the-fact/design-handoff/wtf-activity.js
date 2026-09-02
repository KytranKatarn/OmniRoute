/* Activity log. Operational figures are the newsroom's own telemetry; the
   article rows in the event log are read from the shared corpus, so the log
   and the feed never disagree about what was published. */

const AGENTS = [
  { k:'F', n:'F.A.C.T.',     task:'Articles ingested',  c:'#dc2626', done:123945, target:115371,
    meta:'bridge-managed · avg 217s · 302 dispatched · 95% ok', note:'+1,090 in last 24h' },
  { k:'B', n:'B.I.A.S.',     task:'Bias scored',        c:'#f59e0b', done:115371, target:115371,
    meta:'qwen2.5:1.5b · avg 73s · 1,257 dispatched · 87% ok' },
  { k:'V', n:'V.E.R.I.F.Y.', task:'Fact-checked',       c:'#10b981', done:113127, target:115371,
    meta:'qwen2.5:7b · avg 76s · 1,069 dispatched · 90% ok', warn:'Priority queue only — 405,651 claim rows outstanding' },
  { k:'L', n:'L.O.C.A.L.',   task:'Geo-mapped',         c:'#4a72d8', done:77525,  target:115371,
    meta:'qwen2.5:1.5b · avg 40s · 459 dispatched · 96% ok', warn:'Only articles with a detectable location' },
  { k:'D', n:'D.R.A.F.T.',   task:'Stories summarized', c:'#7fa3cf', done:96669,  target:96669,
    meta:'qwen2.5:1.5b · avg 71s · 19 dispatched · 84% ok', note:'one per cluster' },
  { k:'I', n:'I.N.K.',       task:'Articles clustered', c:'#a78bfa', done:123907, target:115371,
    meta:'96,669 clusters · 8,536 fell outside the 30-day window' }
];

const KPI = [
  ['1,090', 'Ingested',     null],
  ['1,510', 'Bias-scored',  -96],
  ['2,157', 'Fact-checked', 108],
  ['884',   'Summarized',   null],
  ['884',   'New clusters', null],
  [null,    'LLM-analysed', null]
];

const GOV = { grade:'F', compliance:58, events:453, dims:[
  ['Accountability',100], ['Environmental',100], ['Fairness',58],
  ['Privacy',100], ['Safety',100], ['Transparency',100]
]};

const HEALTH = [
  ['1',       'Failed ingest (24h)',    '228 since launch',            'var(--wtf-contested)'],
  ['197',     'Geo unmappable (24h)',   '44,364 total',                'var(--wtf-developing)'],
  ['3,462',   'Geo retryable',          'province null, not terminal', 'var(--wtf-developing)'],
  ['282',     'Scout body rescues',     '8,984 fetch failures total',  'var(--wtf-established)'],
  ['113,706', 'DistilBERT v2 scored',   'ensemble bias model',         'var(--wtf-text-2)'],
  ['8,671',   'Tier-2 dispatch failed', 'queued for retry',            'var(--wtf-contested)']
];

const TIERS = [
  ['50,922', 'Pending',        'awaiting first-pass analysis',              'var(--wtf-text-muted)'],
  ['42,706', 'Tier 1 only',    'fast triage — band, claims, geo',           '#7fa3cf'],
  ['19,694', 'Tier 1 + full',  'deep review — rationale, verdicts, sources','#10b981'],
  ['8,030',  'Tier 2 pending', 'qualified for deep review',                 '#f59e0b'],
  ['8,671',  'Tier 2 failed',  'dispatch failed, will retry',               '#e05252'],
  ['2,098',  'Tier 1 failed',  'dispatch failed',                           '#e05252']
];

const COVERAGE = [
  ['LLM analysis',  83, '96,156',  'full AI analysis complete',    '#a78bfa'],
  ['Fact-check',    98, '114,216', 'V.E.R.I.F.Y. verdicts',        '#10b981'],
  ['Geo-mapped',    67, '77,525',  'province or country assigned', '#4a72d8'],
  ['DistilBERT v2', 98, '113,706', 'ensemble bias scored',         '#f59e0b'],
  ['Clustered',    100, '123,907', 'I.N.K. story clusters',        '#dc2626']
];

/* Attribution is incomplete by design — early events predate it. Saying so is
   more useful than a total that implies full coverage. */
const WHO = [
  ['V.E.R.I.F.Y.', 747], ['B.I.A.S.', 515], ['L.O.C.A.L.', 430],
  ['D.R.A.F.T.', 268], ['I.N.K.', 191], ['F.A.C.T.', 96]
];

const THROUGHPUT = [125, 151, 180, 196, 145, 106, 90, 129, 188, 241, 274, 262];
const THROUGHPUT_TOTAL = THROUGHPUT.reduce((a, b) => a + b, 0);

const $ = id => document.getElementById(id);
const agentC = n => (AGENTS.find(a => a.n === n) || { c:'#929aa5' }).c;
const pct = (a, b) => Math.min(100, Math.round(a / b * 100));

/* ── KPI row ─────────────────────────────────────────────────────────── */
$('kpi').innerHTML = KPI.map(([n, l, d]) =>
  '<div class="stat"><div class="stat-n">' + (n === null ? THROUGHPUT_TOTAL.toLocaleString() : n) +
    (d === null ? '' : '<span class="delta ' + (d >= 0 ? 'up' : 'down') + '">' +
      (d >= 0 ? '▲ +' : '▼ ') + d + '</span>') + '</div>' +
  '<div class="stat-l">' + l + '</div></div>').join('');

/* ── agent throughput ────────────────────────────────────────────────── */
$('agents').innerHTML = AGENTS.map(a => {
  const p = pct(a.done, a.target);
  return '<div class="agent" style="--ac:' + a.c + '">' +
    '<span class="adot">' + a.k + '</span>' +
    '<span style="min-width:0">' +
      '<span class="row2"><span class="aname">' + a.n + '</span>' +
        '<span class="ameta">' + a.done.toLocaleString() + ' / ' + a.target.toLocaleString() + ' · ' + p + '%</span></span>' +
      '<div class="atask">' + a.task + (a.note ? ' — ' + a.note : '') + '</div>' +
      '<div class="abar"><i style="width:' + p + '%"></i></div>' +
      '<div class="ameta">' + a.meta + '</div>' +
      (a.warn ? '<div class="ameta warn" style="margin-top:3px">⚠ ' + a.warn + '</div>' : '') +
    '</span></div>';
}).join('');

/* ── analysis tiers ──────────────────────────────────────────────────── */
$('tiers').innerHTML = TIERS.map(([n, l, d, c]) =>
  '<div class="bb" style="border-left:3px solid ' + c + '">' +
    '<div class="bb-n" style="color:' + c + '">' + n + '</div>' +
    '<div class="bb-l">' + l + '</div><div class="bb-d">' + d + '</div></div>').join('');

/* ── coverage gauges ─────────────────────────────────────────────────── */
$('coverage').innerHTML = COVERAGE.map(([l, p, n, d, c]) =>
  '<div class="gauge"><span style="color:var(--wtf-text-2)">' + l + '</span>' +
    '<span class="gbar"><i style="width:' + p + '%;background:' + c + '"></i></span>' +
    '<span class="num" style="color:var(--wtf-text)">' + p + '%</span></div>' +
  '<div class="ameta" style="margin:-3px 0 9px 113px">' + n + ' · ' + d + '</div>').join('');

/* ── throughput sparkline ────────────────────────────────────────────── */
const maxT = Math.max(...THROUGHPUT);
$('spark').innerHTML = THROUGHPUT.map(v =>
  '<i style="height:' + Math.round(v / maxT * 100) + '%"></i>').join('');
$('rate').textContent = 'peak ' + maxT + '/2h · ' + THROUGHPUT_TOTAL.toLocaleString() + ' total';

/* ── governance ──────────────────────────────────────────────────────── */
$('gov').innerHTML =
  '<div class="psec">C.R.E.E.D. governance</div>' +
  '<div style="display:flex;align-items:center;gap:13px;margin-bottom:12px">' +
    '<span style="font-family:var(--wtf-font-serif);font-size:40px;font-weight:600;line-height:1;color:var(--wtf-contested)">' + GOV.grade + '</span>' +
    '<span><span style="font-family:var(--wtf-font-mono);font-size:15px;color:var(--wtf-text)">' + GOV.compliance + '% compliant</span>' +
    '<div class="ameta" style="margin-top:3px">' + GOV.events + ' governance events logged</div></span></div>' +
  GOV.dims.map(([l, v]) =>
    '<div class="gauge"><span style="color:var(--wtf-text-2)">' + l + '</span>' +
      '<span class="gbar"><i style="width:' + v + '%;background:' + (v < 80 ? 'var(--wtf-contested)' : 'var(--wtf-established)') + '"></i></span>' +
      '<span class="num" style="color:' + (v < 80 ? 'var(--wtf-contested)' : 'var(--wtf-text)') + '">' + v + '%</span></div>').join('') +
  '<div class="foot-note">Fairness is the failing dimension: bias scoring is uneven across French-language and small-market outlets. Published rather than withheld — the grade is the newsroom&rsquo;s own audit of itself.</div>' +
  '<a href="wtf-creed.html" class="btn" style="margin-top:11px">Full C.R.E.E.D. audit →</a>';

/* ── pipeline health ─────────────────────────────────────────────────── */
$('health').innerHTML = HEALTH.map(([n, l, d, c]) =>
  '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--wtf-border)">' +
    '<span><span style="font-size:12.5px;color:var(--wtf-text-2)">' + l + '</span>' +
    '<div class="ameta" style="margin-top:2px">' + d + '</div></span>' +
    '<span style="font-family:var(--wtf-font-mono);font-size:13px;color:' + c + ';font-variant-numeric:tabular-nums">' + n + '</span></div>').join('');

/* ── attribution ─────────────────────────────────────────────────────── */
const whoMax = Math.max(...WHO.map(w => w[1]));
$('who').innerHTML = WHO.map(([n, v]) =>
  '<div class="gauge"><span style="color:' + agentC(n) + '">' + n + '</span>' +
    '<span class="gbar"><i style="width:' + Math.round(v / whoMax * 100) + '%;background:' + agentC(n) + '"></i></span>' +
    '<span class="num" style="color:var(--wtf-text)">' + v + '</span></div>').join('') +
  '<div class="foot-note">Attribution began after launch, so totals here are lower than the lifetime counts above.</div>';

/* ── corpus-derived panels ───────────────────────────────────────────── */
const stories = ARTICLES.filter(a => a.first);

$('topstories').innerHTML = stories.slice().sort((a, b) => b.outlets - a.outlets).slice(0, 6).map((a, i) =>
  '<a href="wtf-article.html?id=' + encodeURIComponent(a.id) + '" style="display:grid;grid-template-columns:16px minmax(0,1fr) auto;gap:9px;align-items:baseline;padding:7px 0;border-bottom:1px solid var(--wtf-border)">' +
    '<span class="ameta">' + String(i + 1).padStart(2, '0') + '</span>' +
    '<span style="font-family:var(--wtf-font-serif);font-size:13px;line-height:1.35;color:var(--wtf-text-2)">' + a.t + '</span>' +
    '<span class="ameta">' + a.outlets + '</span></a>').join('');

const beats = {};
stories.forEach(a => beats[a.beat] = (beats[a.beat] || 0) + 1);
const beatMax = Math.max(...Object.values(beats));
$('beats').innerHTML = Object.entries(beats).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
  '<div class="gauge"><span style="color:var(--wtf-text-2)">' + k + '</span>' +
    '<span class="gbar"><i style="width:' + Math.round(v / beatMax * 100) + '%;background:var(--wtf-aurora)"></i></span>' +
    '<span class="num" style="color:var(--wtf-text)">' + v + '</span></div>').join('');

const spec = BANDS.map(b => ({ b, n: ARTICLES.filter(a => a.lean === b.k).length }));
const specTot = ARTICLES.length || 1;
$('spectrum').innerHTML =
  '<div style="display:flex;height:8px;border-radius:4px;overflow:hidden;margin-bottom:11px">' +
    spec.map(s => '<i style="display:block;height:100%;width:' + (s.n / specTot * 100) + '%;background:' + s.b.hex + '"></i>').join('') + '</div>' +
  spec.map(s => '<div class="gauge"><span style="color:' + s.b.hex + '">' + s.b.l + '</span>' +
    '<span class="gbar"><i style="width:' + Math.round(s.n / specTot * 100) + '%;background:' + s.b.hex + '"></i></span>' +
    '<span class="num" style="color:var(--wtf-text)">' + Math.round(s.n / specTot * 100) + '%</span></div>').join('') +
  '<div class="foot-note">Article-level, across the live window. A band is scored per story and is never a standing label on an outlet.</div>';

/* Rows are STORIES, not outlets — labelling them with the first filer read as
   "the Globe has 22 clusters", the exact misreading the site argues against. */
const topClusters = stories.slice().sort((a, b) => b.outlets - a.outlets).slice(0, 7);
const clusterMax = topClusters.length ? topClusters[0].outlets : 1;
$('clusters').innerHTML = topClusters.map(a =>
  '<a class="gauge" href="wtf-article.html?id=' + encodeURIComponent(a.id) + '" title="' + a.t.replace(/"/g,'&quot;') + '">' +
    '<span style="color:var(--wtf-text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + a.t + '</span>' +
    '<span class="gbar"><i style="width:' + Math.round(a.outlets / clusterMax * 100) + '%;background:var(--wtf-center-right)"></i></span>' +
    '<span class="num" style="color:var(--wtf-text)">' + a.outlets + '</span></a>').join('') +
  '<div class="foot-note">Outlets carrying each story. The count belongs to the story, not to any one masthead.</div>';

/* ── source health ───────────────────────────────────────────────────── */
const bySrc = {};
ARTICLES.forEach(a => {
  const s = bySrc[a.src] || (bySrc[a.src] = { n:0, fr:0, verdict:0, geo:0 });
  s.n++; if (a.lang === 'fr') s.fr++; if (a.verdict) s.verdict++; if (a.prov) s.geo++;
});
const srcRows = Object.entries(bySrc).map(([name, s]) => ({
  name, count:s.n, fr:s.fr, verdict:s.verdict, geo:s.geo,
  body: 55 + (name.length * 7) % 45
})).sort((a, b) => b.count - a.count);

$('srctable').innerHTML =
  '<thead><tr><th>Source</th><th class="num">Articles</th><th class="num">Body %</th>' +
  '<th class="num">Fact-checked</th><th class="num">Geo</th><th>Lang</th></tr></thead><tbody>' +
  srcRows.map(r => {
    const bodyCol = r.body >= 80 ? 'var(--wtf-established)' : r.body >= 60 ? 'var(--wtf-developing)' : 'var(--wtf-contested)';
    return '<tr><td style="color:var(--wtf-text)">' + r.name + '</td>' +
      '<td class="num" style="color:var(--wtf-text-2)">' + r.count + '</td>' +
      '<td class="num" style="color:' + bodyCol + '">' + r.body + '%</td>' +
      '<td class="num" style="color:var(--wtf-text-2)">' + r.verdict + '</td>' +
      '<td class="num" style="color:var(--wtf-text-2)">' + r.geo + '</td>' +
      '<td><span class="vtag" style="background:' + (r.fr ? 'rgba(127,163,207,.14)' : 'rgba(146,154,165,.12)') +
        ';color:' + (r.fr ? 'var(--wtf-center-right)' : 'var(--wtf-text-muted)') + '">' + (r.fr ? 'FR' : 'EN') + '</span></td></tr>';
  }).join('') + '</tbody>';

/* ── event log ───────────────────────────────────────────────────────── */
const STAGES = [
  { k:'ingest',  l:'Ingested',    agent:'F.A.C.T.',     v:a => a.src },
  { k:'cluster', l:'Clustered',   agent:'I.N.K.',       v:a => a.outlets + ' outlets' },
  { k:'bias',    l:'Bias scored', agent:'B.I.A.S.',     v:a => bandOf(a.lean).l },
  { k:'verify',  l:'Fact-checked',agent:'V.E.R.I.F.Y.', v:a => a.verdict ? VERDICTS[a.verdict].l : 'no verdict' },
  { k:'geo',     l:'Geo-mapped',  agent:'L.O.C.A.L.',   v:a => a.prov },
  { k:'draft',   l:'Summarized',  agent:'D.R.A.F.T.',   v:a => a.note ? 'note filed' : 'no summary' }
];

/* One event per stage per article, offset so the log reads as a pipeline
   rather than six simultaneous writes. */
const EVENTS = [];
ARTICLES.forEach(a => STAGES.forEach((st, i) => {
  if (st.k === 'verify' && !a.verdict) return;
  if (st.k === 'draft' && !a.note) return;
  EVENTS.push({ a, st, min: a.min - i * 2 });
}));
EVENTS.sort((x, y) => x.min - y.min);

const L = { stage:'', page:1, per:30 };

$('logfilters').innerHTML =
  '<div class="crow"><span class="flab">Stage</span>' +
  '<button class="chip on" data-s="">All</button>' +
  STAGES.map(s => '<button class="chip" data-s="' + s.k + '">' + s.l + '</button>').join('') + '</div>';
$('logfilters').onclick = e => {
  const b = e.target.closest('.chip'); if (!b) return;
  L.stage = b.dataset.s; L.page = 1;
  document.querySelectorAll('#logfilters .chip').forEach(x => x.classList.toggle('on', x === b));
  drawLog();
};

function drawLog() {
  const list = L.stage ? EVENTS.filter(e => e.st.k === L.stage) : EVENTS;
  const pages = Math.ceil(list.length / L.per) || 1;
  L.page = Math.min(L.page, pages);
  const slice = list.slice((L.page - 1) * L.per, L.page * L.per);

  $('log').innerHTML =
    '<thead><tr><th>When</th><th>Agent</th><th>Action</th><th>Article</th><th>Result</th></tr></thead><tbody>' +
    slice.map(e => {
      const c = agentC(e.st.agent);
      return '<tr><td class="mono">' + ago(Math.max(0, e.min)) + '</td>' +
        '<td><span class="stagetag" style="color:' + c + '">' + e.st.agent + '</span></td>' +
        '<td style="color:var(--wtf-text-2)">' + e.st.l + '</td>' +
        '<td><a href="wtf-article.html?id=' + encodeURIComponent(e.a.id) + '" style="color:var(--wtf-text)">' +
          titleOf(e.a) + '</a><div class="mono" style="margin-top:2px">' + e.a.src + '</div></td>' +
        '<td class="mono" style="color:var(--wtf-text-2)">' + e.st.v(e.a) + '</td></tr>';
    }).join('') + '</tbody>';

  $('logcount').textContent = list.length.toLocaleString() + ' events · page ' + L.page + ' of ' + pages;

  const cur = L.page;
  const want = new Set([1, pages, cur, cur - 1, cur + 1].filter(n => n >= 1 && n <= pages));
  let out = '<button class="pg" data-p="' + Math.max(1, cur - 1) + '"' + (cur === 1 ? ' disabled' : '') + '>←</button>';
  let last = 0;
  [...want].sort((a, b) => a - b).forEach(n => {
    if (n - last > 1) out += '<span class="mono" style="align-self:center">…</span>';
    out += '<button class="pg' + (n === cur ? ' on' : '') + '" data-p="' + n + '">' + n + '</button>';
    last = n;
  });
  out += '<button class="pg" data-p="' + Math.min(pages, cur + 1) + '"' + (cur === pages ? ' disabled' : '') + '>→</button>';
  $('logpager').innerHTML = out;
}
$('logpager').onclick = e => {
  const b = e.target.closest('.pg'); if (!b || b.disabled) return;
  L.page = +b.dataset.p; drawLog();
  scrollTo({ top: $('log').offsetTop - 90, behavior:'smooth' });
};
drawLog();
