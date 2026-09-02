/* Platforms and promise delivery.

   Scoped in an IIFE per the project rule: this page loads wtf-promises.js
   alongside it and must not collide at global scope. */

(function () {
'use strict';

const $ = function (id) { return document.getElementById(id); };
const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};
const REF = new Date('2026-09-02T12:00:00Z');
const dfmt = function (iso) {
  return new Date(iso + 'T12:00:00Z').toLocaleDateString('en-CA', { month:'short', day:'numeric', year:'numeric' });
};
const monthsBetween = function (a, b) {
  return Math.round((new Date(b) - new Date(a)) / 2629800000);
};

/* Evidence provenance maps to the Watch series that collects it. This is not
   decoration: it tells the reader which collection stands behind a verdict, and
   an evidence type with no series is a verdict with no source. */
const WATCH = {
  legislation: { s:'Gov Watch',    c:'var(--wtf-local)',   what:'bill passage and royal assent' },
  bill:        { s:'Gov Watch',    c:'var(--wtf-local)',   what:'bills tabled and their stage' },
  vote:        { s:'Gov Watch',    c:'var(--wtf-local)',   what:'recorded divisions' },
  order:       { s:'Gov Watch',    c:'var(--wtf-local)',   what:'orders-in-council' },
  program:     { s:'Civic Watch',  c:'var(--wtf-aurora)',  what:'programs delivered and their reported output' },
  bylaw:       { s:'Civic Watch',  c:'var(--wtf-aurora)',  what:'municipal bylaws and council decisions' },
  budget:      { s:'Market Watch', c:'var(--wtf-developing)', what:'budget lines, tax rates and fiscal plans' },
  reversal:    { s:'Legal Watch',  c:'var(--wtf-contested)', what:'cancellations, litigation and formal reversals' },
  none:        { s:'No source',    c:'var(--wtf-text-muted)', what:'nothing filed to point at' }
};

let S = { level:'federal', q:'', party:'', theme:'', status:'' };

const meta = function (p) { return PARTY_META[p] || {}; };
const atLevel = function (lvl) {
  return PROMISES.filter(function (p) { return meta(p.party).level === lvl; });
};

/* ── mandate progress ───────────────────────────────────────────────────── */
const mandateOf = function (party) {
  const m = meta(party);
  if (!m.mandate) return null;
  const start = new Date(m.mandate[0]), end = new Date(m.mandate[1]);
  const pct = Math.max(0, Math.min(100, (REF - start) / (end - start) * 100));
  const monthsLeft = Math.max(0, monthsBetween(REF.toISOString().slice(0, 10), m.mandate[1]));
  return { start:m.mandate[0], end:m.mandate[1], pct:pct, monthsLeft:monthsLeft, over:REF > end };
};

/* ── scorecards ─────────────────────────────────────────────────────────── */
function drawScore() {
  const rows = atLevel(S.level);
  const parties = [];
  rows.forEach(function (p) { if (parties.indexOf(p.party) < 0) parties.push(p.party); });
  /* Governing parties first: they are the only ones with a delivery record. */
  parties.sort(function (a, b) {
    return (meta(b).power ? 1 : 0) - (meta(a).power ? 1 : 0) || a.localeCompare(b);
  });

  $('pr-score').innerHTML = parties.map(function (party) {
    const m = meta(party);
    const mine = rows.filter(function (p) { return p.party === party; });
    const mand = mandateOf(party);
    const scored = mine.filter(function (p) { return SCORED.indexOf(p.status) >= 0; });
    const order = ['kept', 'partial', 'progress', 'stalled', 'broken'];

    const powerLabel = m.past ? 'mandate ended' : m.power ? 'in government' : 'not in government';
    const powerCol = m.past ? 'var(--wtf-text-muted)' : m.power
      ? 'background:rgba(16,185,129,.14);color:var(--wtf-established)'
      : 'background:rgba(167,139,250,.14);color:var(--wtf-aurora)';

    /* A party out of power gets no bar: there is nothing to score. */
    const body = scored.length
      ? '<div class="wtf-pr-bar">' +
          order.map(function (k) {
            const n = scored.filter(function (p) { return p.status === k; }).length;
            if (!n) return '';
            const pct = n / scored.length * 100;
            return '<i style="width:' + pct + '%;background:' + PROMISE_STATUS[k].c + '" title="' +
              PROMISE_STATUS[k].l + ' ' + n + '">' + (pct > 12 ? n : '') + '</i>';
          }).join('') +
        '</div>' +
        '<div class="wtf-pr-leg">' +
          order.filter(function (k) { return scored.some(function (p) { return p.status === k; }); })
            .map(function (k) {
              const n = scored.filter(function (p) { return p.status === k; }).length;
              return '<i style="--c:' + PROMISE_STATUS[k].c + '">' + PROMISE_STATUS[k].l + ' ' + n + '</i>';
            }).join('') +
        '</div>'
      : '<div style="font-size:12.5px;line-height:1.65;color:var(--wtf-text-muted);padding:6px 0">' +
        mine.length + ' commitment' + (mine.length === 1 ? '' : 's') + ' recorded as positions. ' +
        'Not scored \u2014 a party without a governing majority cannot deliver, and a kept-promise rate here ' +
        'would measure nothing.</div>';

    /* Same monogram the party pages use, so a party reads identically wherever
       it appears on the site. */
    const ent = { id:m.id || party.toLowerCase().replace(/[^a-z]/g, '').slice(0, 4),
                  short:party, name:party, col:m.col, level:m.level, city:m.city, nonpartisan:m.nonpartisan };
    return '<div class="wtf-pr-card" style="--qc:' + (m.col || 'var(--wtf-border)') + '">' +
      '<div class="wtf-pr-ph" style="align-items:center">' +
        (window.WTFBrand ? WTFBrand.tile(ent, { size:34 }) : '') +
        '<span class="wtf-pr-pn">' + esc(party) + '</span>' +
        '<span class="wtf-pr-pw" style="' + (typeof powerCol === 'string' && powerCol.indexOf('background') === 0 ? powerCol : 'background:var(--wtf-bg-panel);color:var(--wtf-text-muted)') + '">' + powerLabel + '</span>' +
      '</div>' +
      (mand
        ? '<div class="wtf-pr-mand">Mandate ' + dfmt(mand.start) + ' \u2013 ' + dfmt(mand.end) +
            (mand.over ? ' \u00b7 ended' : ' \u00b7 ' + mand.monthsLeft + ' months left') + '</div>' +
          '<div class="wtf-pr-mline"><i style="width:' + mand.pct.toFixed(0) + '%"></i></div>' +
          '<div class="wtf-pr-mand" style="margin-bottom:9px">' + mand.pct.toFixed(0) + '% of the mandate elapsed</div>'
        : '') +
      body +
    '</div>';
  }).join('');
}

/* ── stats ──────────────────────────────────────────────────────────────── */
function drawStats() {
  const rows = atLevel(S.level);
  const scored = rows.filter(function (p) { return SCORED.indexOf(p.status) >= 0; });
  const kept = scored.filter(function (p) { return p.status === 'kept'; }).length;
  const broken = scored.filter(function (p) { return p.status === 'broken'; }).length;
  const positions = rows.filter(function (p) { return p.status === 'position'; }).length;
  const cited = rows.filter(function (p) { return p.evidenceType && p.evidenceType !== 'none'; }).length;
  $('pr-stats').innerHTML = [
    [String(rows.length), 'Commitments tracked'],
    [kept + ' / ' + scored.length, 'Kept, of those scorable'],
    [String(broken), 'Reversed or expired'],
    [String(positions), 'Positions, not scored'],
    [Math.round(cited / rows.length * 100) + '%', 'With a document cited']
  ].map(function (r) {
    return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
  }).join('');
}

/* ── commitment list ────────────────────────────────────────────────────── */
function visible() {
  const q = S.q.toLowerCase();
  return atLevel(S.level).filter(function (p) {
    return (!S.party || p.party === S.party) &&
      (!S.theme || p.theme === S.theme) &&
      (!S.status || p.status === S.status) &&
      (!q || (p.text + ' ' + p.theme + ' ' + p.party + ' ' + p.evidence + ' ' + p.source).toLowerCase().indexOf(q) >= 0);
  });
}

function drawList() {
  const rows = visible();
  /* Order by how load-bearing the verdict is: reversals first, then stalled,
     then what is still moving, then what is settled. A settled promise is the
     least newsworthy row on the page. */
  const rank = { broken:0, stalled:1, partial:2, progress:3, notstarted:4, kept:5, position:6 };
  rows.sort(function (a, b) {
    return (rank[a.status] - rank[b.status]) || a.party.localeCompare(b.party);
  });
  $('pr-count').textContent = rows.length + ' of ' + atLevel(S.level).length + ' commitments';

  $('pr-list').innerHTML = rows.length ? rows.map(function (p) {
    const st = PROMISE_STATUS[p.status];
    const m = meta(p.party);
    const w = WATCH[p.evidenceType] || WATCH.none;
    const mand = mandateOf(p.party);
    /* The remaining-mandate line is what keeps "stalled" from reading as
       "failed" \u2014 it is the context a bare verdict removes. */
    const remain = (p.status === 'stalled' || p.status === 'progress' || p.status === 'notstarted') && mand
      ? (mand.over
          ? 'The mandate ended on ' + dfmt(mand.end) + ' without this being delivered.'
          : mand.monthsLeft + ' months of this mandate remain, so this is unfinished rather than failed.')
      : '';

    return '<div class="wtf-pr-item" style="--sc:' + st.c + '">' +
      '<div class="wtf-pr-top">' +
        '<span class="wtf-pr-status" style="background:' + st.c + '22;color:' + st.c + ';border:1px solid ' + st.c + '55">' + st.l + '</span>' +
        '<span class="wtf-pr-chip" style="color:' + (m.col || 'var(--wtf-text-2)') + ';border-color:' + (m.col || 'var(--wtf-border)') + '55">' + esc(p.party) + '</span>' +
        '<span class="wtf-pr-chip">' + esc(p.theme) + '</span>' +
        (m.prov ? '<span class="wtf-pr-chip">' + esc(m.prov) + '</span>' : '') +
        (m.city ? '<span class="wtf-pr-chip">' + esc(m.city) + '</span>' : '') +
      '</div>' +
      '<p class="wtf-pr-quote">' + esc(p.text) + '</p>' +
      '<div class="wtf-pr-src">' + esc(p.source) + ' \u00b7 stated ' + dfmt(p.made) + '</div>' +
      '<div class="wtf-pr-ev">' +
        '<div class="wtf-pr-evh">' +
          '<span class="wtf-pr-watch" style="background:' + w.c + '1f;color:' + w.c + '"><i></i>' + w.s + '</span>' +
          '<span style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">checked ' + dfmt(p.checked) + '</span>' +
        '</div>' +
        '<div class="wtf-pr-evt">' + esc(p.evidence) + '</div>' +
        (remain ? '<div class="wtf-pr-remain">' + remain + '</div>' : '') +
      '</div>' +
    '</div>';
  }).join('')
  : '<div class="wtf-pr-none">No commitment matches those filters.</div>';
}

/* ── verdict definitions and Watch provenance ───────────────────────────── */
$('pr-defs').innerHTML = Object.keys(PROMISE_STATUS).map(function (k) {
  const s = PROMISE_STATUS[k];
  return '<div class="wtf-pr-def" style="--sc:' + s.c + '">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:' + s.c + ';margin-bottom:5px">' + s.l + '</div>' +
    '<div style="font-size:12px;line-height:1.6;color:var(--wtf-text-2)">' + s.def + '</div></div>';
}).join('');

(function () {
  /* One row per Watch series, with how many verdicts on this page rest on it. */
  const series = {};
  Object.keys(WATCH).forEach(function (k) {
    const w = WATCH[k];
    const g = series[w.s] || (series[w.s] = { c:w.c, what:[], n:0 });
    if (g.what.indexOf(w.what) < 0) g.what.push(w.what);
  });
  PROMISES.forEach(function (p) {
    const w = WATCH[p.evidenceType] || WATCH.none;
    if (series[w.s]) series[w.s].n++;
  });
  $('pr-watch').innerHTML = Object.keys(series).map(function (name) {
    const g = series[name];
    return '<div style="display:grid;grid-template-columns:118px minmax(0,1fr) 42px;gap:11px;align-items:center;padding:8px 0;border-bottom:1px solid #161d29">' +
      '<span class="wtf-pr-watch" style="background:' + g.c + '1f;color:' + g.c + '"><i></i>' + name + '</span>' +
      '<span style="font-size:12.5px;line-height:1.55;color:var(--wtf-text-2)">' + g.what.join('; ') + '</span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' + g.n + '</span></div>';
  }).join('') +
    '<p class="wtf-pr-note" style="margin-top:11px">Counts are verdicts across all three levels resting on each series. ' +
    '&ldquo;No source&rdquo; is not a gap in collection \u2014 it means the commitment has produced nothing to point at, which is ' +
    'itself the finding, and those items are marked stalled rather than given a verdict they have not earned.</p>';
})();

/* ── controls ───────────────────────────────────────────────────────────── */
function fillSelects() {
  const rows = atLevel(S.level);
  const uniq = function (key) {
    const out = [];
    rows.forEach(function (p) { if (out.indexOf(p[key]) < 0) out.push(p[key]); });
    return out.sort();
  };
  $('pr-party').innerHTML = '<option value="">Every party</option>' +
    uniq('party').map(function (v) { return '<option value="' + esc(v) + '">' + esc(v) + '</option>'; }).join('');
  $('pr-theme').innerHTML = '<option value="">Every theme</option>' +
    uniq('theme').map(function (v) { return '<option value="' + esc(v) + '">' + esc(v) + '</option>'; }).join('');
  $('pr-status').innerHTML = '<option value="">Every verdict</option>' +
    Object.keys(PROMISE_STATUS).filter(function (k) {
      return rows.some(function (p) { return p.status === k; });
    }).map(function (k) { return '<option value="' + k + '">' + PROMISE_STATUS[k].l + '</option>'; }).join('');
  S.party = ''; S.theme = ''; S.status = '';
}

$('pr-tabs').addEventListener('click', function (e) {
  const b = e.target.closest('[data-l]');
  if (!b) return;
  S.level = b.dataset.l;
  document.querySelectorAll('#pr-tabs .wtf-pl-tab').forEach(function (x) { x.classList.toggle('on', x === b); });
  const want = S.level === 'federal' ? '' : '#' + S.level;
  if (location.hash !== want) history.replaceState(null, '', S.level === 'federal' ? location.pathname : want);
  fillSelects(); drawStats(); drawScore(); drawList();
});
$('pr-q').addEventListener('input', function (e) { S.q = e.target.value.trim(); drawList(); });
$('pr-party').addEventListener('change', function (e) { S.party = e.target.value; drawList(); });
$('pr-theme').addEventListener('change', function (e) { S.theme = e.target.value; drawList(); });
$('pr-status').addEventListener('change', function (e) { S.status = e.target.value; drawList(); });
window.addEventListener('hashchange', function () {
  const h = location.hash.slice(1);
  if (['federal', 'provincial', 'municipal'].indexOf(h) >= 0) {
    const b = document.querySelector('#pr-tabs [data-l="' + h + '"]');
    if (b) b.click();
  }
});

(function () {
  const h = location.hash.slice(1);
  if (['provincial', 'municipal'].indexOf(h) >= 0) S.level = h;
  document.querySelectorAll('#pr-tabs .wtf-pl-tab').forEach(function (x) {
    x.classList.toggle('on', x.dataset.l === S.level);
  });
  fillSelects(); drawStats(); drawScore(); drawList();
})();

})();
