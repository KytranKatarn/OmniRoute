/* Ethics rulings: named findings from the ethics and integrity commissioners.

   The previous version listed rows as "Report on a minister" with no name, no
   date and no citation — unusable for a reader and indefensible for a site
   built on checkable claims. Findings now come from wtf-accountability.js. */

(function () {
'use strict';

const $ = function (id) { return document.getElementById(id); };
const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};
const PLACE = { ON:'Ontario', QC:'Québec', BC:'British Columbia', AB:'Alberta' };

/* Ethics and integrity offices only — an auditor general is a different kind
   of officer and belongs on the officers page, not here. */
const ETHICS_IDS = { ethics:1, 'int-on':1, 'eth-ab':1, 'eth-qc':1, boie:1 };
const officerOf = function (id) {
  return OFFICERS.filter(function (o) { return o.id === id; })[0] || {};
};
const ROWS = FINDINGS.filter(function (f) { return ETHICS_IDS[f.officer]; })
  .sort(function (a, b) { return b.year - a.year; });

let S = { q:'', level:'', officer:'' };

/* ── stats ──────────────────────────────────────────────────────────────── */
(function () {
  const contra = ROWS.filter(function (f) { return f.kind === 'contravention'; }).length;
  const named = ROWS.filter(function (f) { return !f.unnamed; }).length;
  const offices = {};
  ROWS.forEach(function (f) { offices[f.officer] = 1; });
  const resigned = ROWS.filter(function (f) { return /resign/i.test(f.summary); }).length;
  $('eth-stats').innerHTML = [
    [String(ROWS.length), 'Findings on record'],
    [String(contra), 'Contraventions'],
    [named + ' / ' + ROWS.length, 'Subject named'],
    [String(Object.keys(offices).length), 'Commissioners'],
    [String(resigned), 'Followed by a resignation']
  ].map(function (r) {
    return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
  }).join('');
})();

$('eth-officer').innerHTML = '<option value="">Every commissioner</option>' +
  Object.keys(ROWS.reduce(function (a, f) { a[f.officer] = 1; return a; }, {}))
    .map(function (id) { return '<option value="' + id + '">' + esc(officerOf(id).short || id) + '</option>'; }).join('');

/* ── list ───────────────────────────────────────────────────────────────── */
function draw() {
  const q = S.q.toLowerCase();
  const rows = ROWS.filter(function (f) {
    const o = officerOf(f.officer);
    if (S.level && o.level !== S.level) return false;
    if (S.officer && f.officer !== S.officer) return false;
    if (!q) return true;
    return (f.subject + ' ' + (f.role || '') + ' ' + f.summary + ' ' + f.ref + ' ' + (o.name || ''))
      .toLowerCase().indexOf(q) >= 0;
  });
  $('eth-count').textContent = rows.length + ' of ' + ROWS.length + ' findings';

  $('eth-list').innerHTML = rows.length ? rows.map(function (f) {
    const o = officerOf(f.officer);
    const k = FINDING_KINDS[f.kind] || { l:f.kind, c:'var(--wtf-text-muted)' };
    const ctx = (typeof RECORD_CONTEXT !== 'undefined' && f.ctxKey) ? RECORD_CONTEXT[f.ctxKey] : null;
    return '<div class="wtf-of-card" style="--oc:' + k.c + '">' +
      '<div class="wtf-of-h">' +
        '<span class="wtf-of-n">' + esc(f.subject) + '</span>' +
        (f.role ? '<span class="wtf-of-tag">' + esc(f.role) + '</span>' : '') +
        '<span class="wtf-of-tag" style="color:' + k.c + ';border-color:' + k.c + '55">' + k.l + '</span>' +
        '<span class="wtf-of-tag" style="margin-left:auto">' + f.year + '</span>' +
      '</div>' +
      '<div class="wtf-of-mand">' + esc(f.summary) + '</div>' +
      '<div class="wtf-of-pow" style="border-left-color:' + k.c + '">' +
        '<strong style="color:var(--wtf-text-2)">' + esc(o.name || '') + '</strong> \u00b7 ' + esc(f.ref) +
        ' \u2014 ' + esc(o.power || '') +
      '</div>' +
      (f.unnamed ? '<div class="wtf-of-un">' + esc(f.unnamed) + '</div>' : '') +
      (ctx ? '<div class="wtf-of-un" style="border-left-color:var(--wtf-local)">' + esc(ctx.context) + '</div>' : '') +
      '<div style="display:flex;flex-wrap:wrap;gap:7px;margin-top:9px">' +
        (f.party ? '<a class="wtf-of-tag" style="text-decoration:none" href="wtf-parties.html?party=' + encodeURIComponent(f.party) + '">Party record &rarr;</a>' : '') +
        '<a class="wtf-of-tag" style="text-decoration:none" href="wtf-officers.html">' + esc(o.short || '') + ' &rarr;</a>' +
        '<a class="wtf-of-tag" style="text-decoration:none" href="wtf-search.html?q=' + encodeURIComponent(f.subject) + '">Coverage &rarr;</a>' +
      '</div>' +
    '</div>';
  }).join('')
  : '<div class="panel" style="text-align:center;color:var(--wtf-text-muted);font-size:13px">No finding matches those filters.</div>';
}

/* ── the enforcement gap ────────────────────────────────────────────────── */
(function () {
  /* What each ethics office can actually do, side by side. The pattern is the
     point: none of them can remove anyone. */
  const ids = Object.keys(ETHICS_IDS);
  $('eth-gap').innerHTML =
    ids.map(function (id) {
      const o = officerOf(id);
      if (!o.name) return '';
      const n = ROWS.filter(function (f) { return f.officer === id; }).length;
      return '<div style="display:grid;grid-template-columns:210px minmax(0,1fr) 34px;gap:12px;align-items:start;padding:9px 0;border-bottom:1px solid #161d29">' +
        '<span style="font-size:12.5px;color:var(--wtf-text)">' + esc(o.short) +
          (o.prov ? ' <span style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">' + esc(PLACE[o.prov] || o.prov) + '</span>' : '') +
          (o.notIndependent ? '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--wtf-developing);margin-top:3px">not independent</div>' : '') +
        '</span>' +
        '<span style="font-size:12px;line-height:1.6;color:var(--wtf-text-2)">' + esc(o.power) + '</span>' +
        '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' + n + '</span></div>';
    }).join('') +
    '<p class="wtf-of-note" style="margin-top:11px">' + (typeof NO_REMOVAL !== 'undefined' ? NO_REMOVAL + ' ' : '') +
    'The Board of Internal Economy is the one body here that can order money repaid, and it is composed of MPs rather than ' +
    'being an independent officer. ' +
    'In practice the consequence, where there is one, is political \u2014 a resignation from a portfolio while the seat is kept, ' +
    'which is what happened in ' + ROWS.filter(function (f) { return /resign/i.test(f.summary); }).length + ' of these ' + ROWS.length + ' cases.</p>';
})();

$('eth-q').addEventListener('input', function (e) { S.q = e.target.value.trim(); draw(); });
$('eth-level').addEventListener('change', function (e) { S.level = e.target.value; draw(); });
$('eth-officer').addEventListener('change', function (e) { S.officer = e.target.value; draw(); });

draw();

})();
