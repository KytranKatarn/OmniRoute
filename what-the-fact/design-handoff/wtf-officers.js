/* Officers of Parliament: mandate, power, and every finding on record.

   The previous version of this page listed eight mandates behind a paywall and
   showed no findings, which made the accountability spine of the site its
   thinnest page. Findings now come from wtf-accountability.js — the same
   source the party records read, so the two cannot disagree. */

(function () {
'use strict';

const $ = function (id) { return document.getElementById(id); };
const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};
const LEVEL = { federal:'Federal', provincial:'Provincial', municipal:'Municipal' };
const PLACE = { ON:'Ontario', QC:'Québec', BC:'British Columbia', AB:'Alberta' };

/* Colour marks the LEVEL of government, not a verdict — a finding's own colour
   comes from its kind. */
const LEVEL_COL = { federal:'var(--wtf-accent)', provincial:'var(--wtf-local)', municipal:'var(--wtf-aurora)' };

let S = { q:'', level:'', kind:'', onlyWith:false };

/* Same preview mechanism as the MP and senator profiles: its own sessionStorage
   key, never the tier flag, so a design review cannot be mistaken for a login. */
let PREVIEW = false;
try { PREVIEW = WTFTier.isSubscriber(); } catch (e) {}
function togglePreview() {
  PREVIEW = !PREVIEW;
  try { WTFTier.set(PREVIEW); } catch (e) {}
  const b = $('of-pv'); if (b) { b.textContent = PREVIEW ? 'Show the gate' : 'Show subscriber view'; b.style.color = PREVIEW ? 'var(--wtf-accent)' : ''; }
  draw();
}
window.toggleOfficersPreview = togglePreview;

const findingsFor = function (id) {
  return FINDINGS.filter(function (f) { return f.officer === id; })
    .sort(function (a, b) { return b.year - a.year; });
};

/* ── stats ──────────────────────────────────────────────────────────────── */
(function () {
  const independent = OFFICERS.filter(function (o) { return !o.notIndependent; });
  const fed = OFFICERS.filter(function (o) { return o.level === 'federal' && !o.notIndependent; });
  const contra = FINDINGS.filter(function (f) { return f.kind === 'contravention'; }).length;
  /* Derived, not asserted. A hardcoded 2 was contradicted by four cards on the
     same screen and understated the regime. */
  const enforcing = OFFICERS.filter(function (o) { return o.enforcement; });
  $('of-stats').innerHTML = [
    [String(OFFICERS.length), 'Offices on this page'],
    [String(independent.length), 'Independent officers'],
    [String(FINDINGS.length), 'Findings on record'],
    [String(contra), 'Contraventions found'],
    [enforcing.length + ' / ' + OFFICERS.length, 'With any enforcement power']
  ].map(function (r) {
    return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
  }).join('');
})();

$('of-kinds').innerHTML = Object.keys(FINDING_KINDS).map(function (k) {
  const v = FINDING_KINDS[k];
  return '<div class="wtf-of-kind" style="--kc:' + v.c + '">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:' + v.c + ';margin-bottom:5px">' + v.l + '</div>' +
    '<div style="font-size:12px;line-height:1.65;color:var(--wtf-text-2)">' + esc(v.note) + '</div></div>';
}).join('');

/* ── list ───────────────────────────────────────────────────────────────── */
function visible() {
  const q = S.q.toLowerCase();
  return OFFICERS.filter(function (o) {
    const fs = findingsFor(o.id);
    if (S.level && o.level !== S.level) return false;
    if (S.kind && !fs.some(function (f) { return f.kind === S.kind; })) return false;
    if (S.onlyWith && !fs.length) return false;
    if (!q) return true;
    /* Finding text is searchable only when it is visible; otherwise a search
       would confirm gated content exists by matching on it. */
    const hay = o.name + ' ' + o.mandate + ' ' + o.power + ' ' + (o.prov || '') + ' ' + (o.city || '') +
      (PREVIEW ? ' ' + fs.map(function (f) { return f.subject + ' ' + f.summary + ' ' + f.ref; }).join(' ') : '');
    return hay.toLowerCase().indexOf(q) >= 0;
  });
}

function findingRow(f) {
  const k = FINDING_KINDS[f.kind] || { l:f.kind, c:'var(--wtf-text-muted)' };
  const ctx = (typeof RECORD_CONTEXT !== 'undefined' && f.ctxKey) ? RECORD_CONTEXT[f.ctxKey] : null;
  return '<div class="wtf-of-f">' +
    '<span class="wtf-of-fy">' + f.year + '</span>' +
    '<span>' +
      '<span class="wtf-of-fs">' + esc(f.subject) +
        (f.role ? ' <span style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);font-weight:400">' + esc(f.role) + '</span>' : '') +
      '</span>' +
      '<div class="wtf-of-fr">' + esc(f.ref) +
        (f.party ? ' \u00b7 <a href="wtf-parties.html?party=' + encodeURIComponent(f.party) + '" style="color:var(--wtf-local);text-decoration:none">party record &rarr;</a>' : '') +
      '</div>' +
      '<div class="wtf-of-fd">' + esc(f.summary) + '</div>' +
      /* Where an officer publishes without naming the subject, say so rather
         than letting the row look like an omission on our side. */
      (f.unnamed ? '<div class="wtf-of-un">' + esc(f.unnamed) + '</div>' : '') +
      (ctx && ctx.caveat ? '<div class="wtf-of-un" style="border-left-color:var(--wtf-developing)"><strong style="color:var(--wtf-developing);font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;display:block;margin-bottom:2px;font-weight:500">Worth noting</strong>' + esc(ctx.caveat) + '</div>' : '') +
    '</span>' +
    '<span class="wtf-of-tag" style="color:' + k.c + ';border-color:' + k.c + '55">' + k.l + '</span>' +
  '</div>';
}

function draw() {
  const rows = visible();
  /* Most findings first — an office with a record is the one worth reading,
     and mandate text alone was the failure of the previous version. */
  rows.sort(function (a, b) {
    return findingsFor(b.id).length - findingsFor(a.id).length ||
      (a.level === b.level ? a.est - b.est : (a.level === 'federal' ? -1 : 1));
  });
  const shown = rows.reduce(function (n, o) { return n + findingsFor(o.id).length; }, 0);
  $('of-count').textContent = rows.length + ' of ' + OFFICERS.length + ' offices \u00b7 ' + shown + ' findings';

  $('of-list').innerHTML = rows.length ? rows.map(function (o) {
    let fs = findingsFor(o.id);
    if (S.kind) fs = fs.filter(function (f) { return f.kind === S.kind; });
    const col = LEVEL_COL[o.level] || 'var(--wtf-border)';
    return '<div class="wtf-of-card" style="--oc:' + col + '">' +
      '<div class="wtf-of-h">' +
        '<span class="wtf-of-n">' + esc(o.name) + '</span>' +
        '<span class="wtf-of-tag" style="color:' + col + ';border-color:' + col + '55">' + LEVEL[o.level] + '</span>' +
        (o.prov ? '<span class="wtf-of-tag">' + esc(PLACE[o.prov] || o.prov) + '</span>' : '') +
        (o.city ? '<span class="wtf-of-tag">' + esc(o.city) + '</span>' : '') +
        '<span class="wtf-of-tag">Est. ' + o.est + '</span>' +
        (o.notIndependent ? '<span class="wtf-of-tag" style="color:var(--wtf-developing);border-color:rgba(245,158,11,.4)">not an independent officer</span>' : '') +
        '<span class="wtf-of-tag" style="margin-left:auto;color:' + (fs.length ? 'var(--wtf-text)' : 'var(--wtf-text-muted)') + '">' +
          fs.length + ' finding' + (fs.length === 1 ? '' : 's') + '</span>' +
      '</div>' +
      '<div class="wtf-of-mand">' + esc(o.mandate) + '</div>' +
      '<div class="wtf-of-pow"><strong style="color:var(--wtf-text-2)">What it can actually do:</strong> ' + esc(o.power) + '</div>' +
      (o.enforcement
        ? '<div class="wtf-of-un" style="border-left-color:var(--wtf-established)">' +
          '<strong style="color:var(--wtf-established);font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;display:block;margin-bottom:3px;font-weight:500">Has enforcement power</strong>' +
          esc(o.enforcementWhy) + '</div>'
        : '') +
      '<div style="display:flex;flex-wrap:wrap;gap:7px;margin-top:9px">' +
        '<span class="wtf-of-tag">Appointed by ' + esc(o.appointed) + '</span>' +
        '<span class="wtf-of-tag">Term: ' + esc(o.term) + '</span>' +
      '</div>' +
      (fs.length
        ? '<div class="wtf-of-fh">Findings on record <span style="color:var(--wtf-text-muted);letter-spacing:0;text-transform:none">(' + fs.length + ')</span></div>' +
          (PREVIEW
            ? fs.map(findingRow).join('')
            /* The gate names what it is withholding — a count and the years —
               rather than teasing. */
            : '<div class="wtf-of-gate">' +
                '<div style="font-family:var(--wtf-font-mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--wtf-accent);margin-bottom:6px">Starter+</div>' +
                '<div style="font-size:13px;line-height:1.65;color:var(--wtf-text-2);max-width:60ch">' +
                  fs.length + ' finding' + (fs.length === 1 ? '' : 's') + ' on record, ' +
                  Math.min.apply(null, fs.map(function (f) { return f.year; })) + '\u2013' +
                  Math.max.apply(null, fs.map(function (f) { return f.year; })) +
                  ', with the subject named, the report cited and the context explained. ' +
                  'The office itself is public record and shown above; the compiled findings are the newsroom\u2019s work.</div>' +
                '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">' +
                  '<a class="wtf-of-tag" style="text-decoration:none;background:var(--wtf-accent);border-color:var(--wtf-accent);color:#fff;padding:7px 14px" href="/login?next=/officers">Unlock with Starter &rarr;</a>' +
                  '<a class="wtf-of-tag" style="text-decoration:none;padding:7px 14px" href="/join">See plans</a>' +
                '</div></div>')
        : '<div class="wtf-of-none">No finding on record in the period this site covers. That is not a statement that the office found nothing \u2014 only that nothing is in our dataset.</div>') +
    '</div>';
  }).join('')
  : '<div class="panel" style="text-align:center;color:var(--wtf-text-muted);font-size:13px">No office matches those filters.</div>';
}

$('of-q').addEventListener('input', function (e) { S.q = e.target.value.trim(); draw(); });
$('of-level').addEventListener('change', function (e) { S.level = e.target.value; draw(); });
$('of-kind').addEventListener('change', function (e) { S.kind = e.target.value; draw(); });
$('of-only').addEventListener('click', function () {
  S.onlyWith = !S.onlyWith;
  $('of-only').classList.toggle('on', S.onlyWith);
  draw();
});

/* The claim that IS true of all of them, stated where the false one was. */
(function () {
  const enforcing = OFFICERS.filter(function (o) { return o.enforcement; });
  const host = document.querySelector('#of-kinds');
  if (!host || !host.parentNode) return;
  const p = host.parentNode.querySelector('.wtf-of-note');
  if (!p) return;
  p.innerHTML = 'Neither kind is a criminal finding. <strong>' + NO_REMOVAL + '</strong> ' +
    enforcing.length + ' of the ' + OFFICERS.length + ' offices here can do more than publish, and they are ' +
    'listed below with the specific power named — the Chief Electoral Officer’s route is the only one that can ' +
    'end in a conviction. That gap between what these offices can find and what they can enforce is the ' +
    'recurring theme of this page.';
})();

draw();

})();
