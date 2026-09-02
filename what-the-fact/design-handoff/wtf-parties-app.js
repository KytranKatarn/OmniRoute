/* Party profiles: index by level, detail at ?party=<id>.

   IIFE-scoped per the project rule — this page loads wtf-parties.js and
   wtf-promises.js alongside it. */

(function () {
'use strict';

const $ = function (id) { return document.getElementById(id); };
const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};
const LEVEL = { federal:'Federal', provincial:'Provincial', municipal:'Municipal' };
const PLACE = { ON:'Ontario', QC:'Québec', BC:'British Columbia', AB:'Alberta', MB:'Manitoba',
  SK:'Saskatchewan', NS:'Nova Scotia', NB:'New Brunswick', NL:'Newfoundland & Labrador',
  PE:'Prince Edward Island', YT:'Yukon', NT:'Northwest Territories', NU:'Nunavut' };
const whereOf = function (p) { return p.city || PLACE[p.prov] || 'Canada'; };
const byId = function (id) { return PARTIES.filter(function (p) { return p.id === id; })[0]; };

/* Commitments on the platforms page are keyed by the party's SHORT name, so
   the two pages agree without duplicating the data. */
const promisesFor = function (p) {
  if (typeof PROMISES === 'undefined') return [];
  return PROMISES.filter(function (x) { return x.party === p.short; });
};

/* ── detail ─────────────────────────────────────────────────────────────── */
function detail(p) {
  const hist = p.history.slice().sort(function (a, b) { return a.y - b.y; });
  const maxSeat = Math.max.apply(null, hist.map(function (h) { return h.seats; }).concat([1]));
  const maxVote = Math.max.apply(null, hist.map(function (h) { return h.votes; }).concat([1]));
  const govYears = hist.filter(function (h) { return (OUTCOME[h.outcome] || {}).gov; }).length;
  const span = hist.length ? hist[0].y + '\u2013' + hist[hist.length - 1].y : '\u2014';
  const proms = promisesFor(p);
  const scored = proms.filter(function (x) { return typeof SCORED !== 'undefined' && SCORED.indexOf(x.status) >= 0; });
  const kept = scored.filter(function (x) { return x.status === 'kept'; }).length;

  /* Seats and votes on one row, because the gap between them is the point.
     A ~39% vote produced a majority in both 2011 and 2015. */
  const recordTable =
    '<div style="overflow-x:auto"><table class="wtf-pt-tbl"><thead><tr>' +
      '<th>Election</th><th>Result</th><th style="min-width:120px">Seats / vote share</th>' +
      '<th class="n">Seats</th><th class="n">Share of seats</th><th class="n">Vote</th>' +
    '</tr></thead><tbody>' +
    hist.slice().reverse().map(function (h) {
      const o = OUTCOME[h.outcome] || { l:h.outcome, c:'var(--wtf-text-muted)' };
      const size = (typeof HOUSE_SIZE !== 'undefined' && HOUSE_SIZE[h.y]) || null;
      const seatPct = size ? (h.seats / size * 100) : null;
      /* A seat share far above the vote share is the system converting votes
         into power unevenly. Flagged, not editorialised. */
      const gap = seatPct === null ? null : seatPct - h.votes;
      return '<tr>' +
        '<td style="font-family:var(--wtf-font-mono);font-size:11.5px;color:var(--wtf-text)">' + h.y + '</td>' +
        '<td><span class="wtf-pt-pill" style="font-size:9px;background:' + o.c + '22;color:' + o.c + '">' + o.l + '</span></td>' +
        '<td><span class="wtf-pt-dual" style="--qc:' + p.col + '">' +
          '<span class="s" style="width:' + (h.seats / maxSeat * 100) + '%"></span>' +
          '<span class="v" style="width:' + (h.votes / maxVote * 100) + '%"></span></span></td>' +
        '<td class="n" style="color:var(--wtf-text)">' + h.seats + '</td>' +
        '<td class="n" style="color:' + (gap !== null && Math.abs(gap) >= 8 ? 'var(--wtf-developing)' : 'var(--wtf-text-2)') + '">' +
          (seatPct === null ? '\u2014' : seatPct.toFixed(1) + '%') + '</td>' +
        '<td class="n" style="color:var(--wtf-text-2)">' + h.votes.toFixed(1) + '%</td>' +
      '</tr>';
    }).join('') +
    '</tbody></table></div>' +
    '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:10px">' +
      '<span style="display:inline-flex;align-items:center;gap:6px;font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">' +
        '<span style="width:16px;height:5px;border-radius:3px;background:' + p.col + '"></span>seats</span>' +
      '<span style="display:inline-flex;align-items:center;gap:6px;font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">' +
        '<span style="width:16px;height:5px;border-radius:3px;background:' + p.col + ';opacity:.4"></span>vote share</span>' +
    '</div>' +
    '<p class="wtf-pt-note" style="margin-top:10px">Share of seats is highlighted where it diverges from the vote by eight points or more. ' +
    'Single-member districts convert votes into seats unevenly, so a party can win more seats on fewer votes \u2014 that is a property of the ' +
    'system, not of the party.</p>';

  /* Context lives in wtf-record-context.js, keyed partyId|title. An entry with
     no context renders with no expander — nothing is padded to make the
     interface look complete. */
  const ctxOf = function (title) {
    if (typeof RECORD_CONTEXT === 'undefined') return null;
    return RECORD_CONTEXT[p.id + '|' + title] || null;
  };

  const expander = function (key, ctx, col) {
    if (!ctx) return '';
    return '<button class="wtf-pt-more" data-k="' + esc(key) + '" style="--rc:' + col + '" ' +
        'aria-expanded="false" aria-controls="ctx-' + esc(key) + '">Full context <span>+</span></button>' +
      '<div class="wtf-pt-ctx" id="ctx-' + esc(key) + '" hidden>' +
        '<div class="wtf-pt-ctxt">' + esc(ctx.context) + '</div>' +
        (ctx.caveat ? '<div class="wtf-pt-cav"><strong>Worth noting</strong> ' + esc(ctx.caveat) + '</div>' : '') +
        (ctx.source ? '<div class="wtf-pt-csrc">Source: ' + esc(ctx.source) + '</div>' : '') +
      '</div>';
  };

  let ctxSeq = 0;
  const recList = function (rows, kind) {
    const col = kind === 'delivered' ? 'var(--wtf-established)' : 'var(--wtf-contested)';
    if (!rows || !rows.length) {
      return '<div class="wtf-pt-none">' +
        (kind === 'delivered'
          ? 'Nothing recorded as delivered. A party that has never governed has no delivery record, which is a fact about opportunity rather than about intent.'
          : 'Nothing recorded as reversed or abandoned.') + '</div>';
    }
    return rows.map(function (r) {
      const ctx = ctxOf(r[0]);
      const key = kind + '-' + (ctxSeq++);
      return '<div class="wtf-pt-rec' + (ctx ? ' has-ctx' : '') + '" style="--rc:' + col + '">' +
        '<div class="wtf-pt-rt">' + esc(r[0]) + '</div>' +
        '<div class="wtf-pt-ry">' + (r[1] ? r[1] : 'no date \u2014 outstanding') + ' \u00b7 ' + esc(r[3]) + '</div>' +
        '<div class="wtf-pt-rd">' + esc(r[2]) + '</div>' +
        expander(key, ctx, col) +
      '</div>';
    }).join('');
  };

  const findings = (p.findings || []).length
    ? p.findings.map(function (f, i) {
        const k = FINDING_KIND[f[3]] || { l:f[3], c:'var(--wtf-text-muted)' };
        /* Findings by the same officer share one context entry, since the
           context describes that officer's reports together. */
        const ctx = ctxOf(f[0]);
        const key = 'find-' + i;
        return '<div class="wtf-pt-rec' + (ctx ? ' has-ctx' : '') + '" style="--rc:' + k.c + '">' +
          '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:5px">' +
            '<span class="wtf-pt-tag" style="color:' + k.c + ';border-color:' + k.c + '55">' + k.l + '</span>' +
            '<span style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">' + f[1] + '</span></div>' +
          '<div class="wtf-pt-rt" style="font-size:12.5px">' + esc(f[0]) + '</div>' +
          '<div class="wtf-pt-rd" style="margin-top:4px">' + esc(f[2]) + '</div>' +
          (i === 0 || p.findings.filter(function (x) { return x[0] === f[0]; }).indexOf(f) === 0
            ? expander(key, ctx, k.c) : '') +
        '</div>';
      }).join('')
    : '<div class="wtf-pt-none">No finding by an independent officer on record in this period.</div>';

  return '<div class="wtf-pt-hero" style="text-align:center">' +
    '<a class="wtf-pt-back" href="wtf-parties.html">&larr; All parties</a>' +
    (window.WTFBrand ? '<div style="margin:14px 0 4px">' + WTFBrand.tile(p, { size:72 }) + '</div>' : '') +
    '<h1 class="wtf-pt-h1">' + esc(p.name) + '</h1>' +
    '<div class="wtf-pt-badges" style="justify-content:center">' +
      '<span class="wtf-pt-pill" style="background:' + p.col + '22;color:' + p.col + ';border:1px solid ' + p.col + '55">' + LEVEL[p.level] + '</span>' +
      '<span class="wtf-pt-tag">' + esc(whereOf(p)) + '</span>' +
      '<span class="wtf-pt-tag">Founded ' + p.founded + '</span>' +
      '<span class="wtf-pt-tag">' + span + ' on record</span>' +
      (p.nonpartisan ? '<span class="wtf-pt-tag" style="color:var(--wtf-text-muted)">no municipal parties here</span>' : '') +
    '</div>' +
    (p.note ? '<p style="font-size:13px;line-height:1.7;color:var(--wtf-text-2);margin:12px auto 0;max-width:72ch;text-wrap:pretty">' + esc(p.note) + '</p>' : '') +
  '</div>' +

  '<div class="statrow">' +
    [[String(hist.length), 'Elections contested'],
     [govYears + ' / ' + hist.length, 'Held government'],
     [String(Math.max.apply(null, hist.map(function (h) { return h.seats; }))), 'Best seat count'],
     [(p.delivered || []).length + ' / ' + ((p.delivered || []).length + (p.reversed || []).length), 'Commitments delivered'],
     [String((p.findings || []).length), 'Officer findings']]
    .map(function (r) {
      return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
    }).join('') +
  '</div>' +

  '<div class="wtf-pt-panel"><div class="psec">Electoral record</div>' + recordTable + '</div>' +

  '<div class="wtf-pt-panel"><div class="psec">Time in government</div>' +
    '<div class="wtf-pt-gov">' +
      hist.map(function (h) {
        const o = OUTCOME[h.outcome] || { c:'var(--wtf-text-muted)', l:h.outcome };
        return '<i style="width:' + (100 / hist.length) + '%;background:' + o.c +
          '" title="' + h.y + ' \u2014 ' + o.l + ', ' + h.seats + (h.seats === 1 ? ' seat' : ' seats') + '">' +
          String(h.y).slice(2) + '</i>';
      }).join('') +
    '</div>' +
    '<p class="wtf-pt-note">Government is not a merit ranking here. It is the precondition for delivery: the commitments below could only have ' +
    'been delivered in the periods shaded as government, which is why an opposition party\u2019s record is thin by definition rather than by failure.</p>' +
  '</div>' +

  '<div class="wtf-pt-panel"><div class="psec">Leadership</div>' +
    p.leaders.map(function (l) {
      return '<div class="wtf-pt-lead">' +
        '<span style="font-size:13px;color:var(--wtf-text)">' + esc(l[0]) +
          (l[2] ? ' <span style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">' + esc(l[2]) + '</span>' : '') + '</span>' +
        '<span style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-text-2);text-align:right">' + esc(l[1]) + '</span></div>';
    }).join('') +
  '</div>' +

  '<div class="wtf-pt-two">' +
    '<div class="wtf-pt-panel" style="margin:0"><div class="psec" style="color:var(--wtf-established)">Delivered</div>' +
      recList(p.delivered, 'delivered') + '</div>' +
    '<div class="wtf-pt-panel" style="margin:0"><div class="psec" style="color:var(--wtf-contested)">Reversed or abandoned</div>' +
      recList(p.reversed, 'reversed') + '</div>' +
  '</div>' +

  '<div class="wtf-pt-panel" style="margin-top:12px"><div class="psec">Findings by independent officers</div>' +
    findings +
    '<p class="wtf-pt-note" style="margin-top:10px">Findings are by officers who do not report to the government of the day \u2014 auditors general, ' +
    'ethics and integrity commissioners, the Chief Electoral Officer. A contravention finding is not a criminal finding and carries no penalty ' +
    'beyond the report. An empty list means nothing on record in this period, not that nothing happened.</p>' +
  '</div>' +

  (proms.length
    ? '<div class="wtf-pt-panel"><div class="psec">Current mandate commitments</div>' +
        '<div style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:11px">' +
          Object.keys(PROMISE_STATUS).filter(function (k) {
            return proms.some(function (x) { return x.status === k; });
          }).map(function (k) {
            const n = proms.filter(function (x) { return x.status === k; }).length;
            const s = PROMISE_STATUS[k];
            return '<span class="wtf-pt-tag" style="color:' + s.c + ';border-color:' + s.c + '55">' + s.l + ' ' + n + '</span>';
          }).join('') +
        '</div>' +
        (scored.length
          ? '<div style="font-size:13px;line-height:1.7;color:var(--wtf-text-2);max-width:74ch">' + kept + ' of ' + scored.length +
            ' scorable commitments in the current mandate are delivered as stated. The rest, and the evidence behind each verdict, are on the promise tracker.</div>'
          : '<div style="font-size:13px;line-height:1.7;color:var(--wtf-text-2);max-width:74ch">These are positions rather than deliverables: the party is not in government, so none of them is scored.</div>') +
        '<a class="wtf-pt-tag" style="display:inline-block;margin-top:11px;padding:8px 15px;text-decoration:none" href="wtf-platforms.html#' + p.level + '">Promise tracker &rarr;</a>' +
      '</div>'
    : '') +

  '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:14px">' +
    '<a class="wtf-pt-tag" style="padding:9px 16px;text-decoration:none" href="wtf-parties.html">&larr; All parties</a>' +
    '<a class="wtf-pt-tag" style="padding:9px 16px;text-decoration:none" href="wtf-elections.html#' + p.level + '">' + LEVEL[p.level] + ' elections &rarr;</a>' +
    '<a class="wtf-pt-tag" style="padding:9px 16px;text-decoration:none" href="wtf-races.html#' + p.level + '">Candidates &amp; races &rarr;</a>' +
    (p.level === 'federal' ? '<a class="wtf-pt-tag" style="padding:9px 16px;text-decoration:none" href="wtf-mps.html">Members of Parliament &rarr;</a>' : '') +
  '</div>';
}

/* ── index ──────────────────────────────────────────────────────────────── */
let level = 'federal';

function card(p) {
  const hist = p.history.slice().sort(function (a, b) { return a.y - b.y; });
  const max = Math.max.apply(null, hist.map(function (h) { return h.seats; }).concat([1]));
  const gov = hist.filter(function (h) { return (OUTCOME[h.outcome] || {}).gov; }).length;
  const last = hist[hist.length - 1];
  const o = OUTCOME[last.outcome] || { l:last.outcome, c:'var(--wtf-text-muted)' };
  const brand = window.WTFBrand
    ? WTFBrand.wordmark(p, { size:40, nameSize:17,
        sub:whereOf(p) + ' \u00b7 founded ' + p.founded + ' \u00b7 ' + hist.length + ' elections' })
    : '<div class="wtf-pt-nm">' + esc(p.short) + '</div>';
  return '<a class="wtf-pt-card" style="--qc:' + p.col + '" href="wtf-parties.html?party=' + encodeURIComponent(p.id) + '">' +
    brand +
    '<div class="wtf-pt-spark">' +
      hist.map(function (h) {
        const oo = OUTCOME[h.outcome] || { c:'var(--wtf-text-muted)' };
        return '<i style="height:' + Math.max(4, Math.round(h.seats / max * 100)) + '%;background:' + oo.c +
          '" title="' + h.y + ' \u2014 ' + h.seats + (h.seats === 1 ? ' seat' : ' seats') + '"></i>';
      }).join('') +
    '</div>' +
    '<div class="wtf-pt-years"><span>' + hist[0].y + '</span><span>' + hist[hist.length - 1].y + '</span></div>' +
    '<div class="wtf-pt-tags">' +
      '<span class="wtf-pt-tag" style="color:' + o.c + ';border-color:' + o.c + '55">' + o.l + '</span>' +
      '<span class="wtf-pt-tag">' + gov + ' of ' + hist.length + ' in government</span>' +
      ((p.findings || []).length ? '<span class="wtf-pt-tag" style="color:var(--wtf-developing);border-color:rgba(245,158,11,.4)">' + p.findings.length + ' finding' + (p.findings.length === 1 ? '' : 's') + '</span>' : '') +
    '</div>' +
  '</a>';
}

function drawIndex() {
  const rows = PARTIES.filter(function (p) { return p.level === level; });
  /* Governing parties first \u2014 they are the ones with a delivery record to read. */
  const lastSeats = function (p) {
    const h = p.history;
    return h.length ? h[h.length - 1].seats : 0;
  };
  rows.sort(function (a, b) {
    const ag = a.status === 'government' ? 1 : 0, bg = b.status === 'government' ? 1 : 0;
    return (bg - ag) || (lastSeats(b) - lastSeats(a)) || a.short.localeCompare(b.short);
  });
  const totalFindings = rows.reduce(function (n, p) { return n + (p.findings || []).length; }, 0);
  const totalDelivered = rows.reduce(function (n, p) { return n + (p.delivered || []).length; }, 0);
  const totalReversed = rows.reduce(function (n, p) { return n + (p.reversed || []).length; }, 0);

  $('pt-stats').innerHTML = [
    [String(rows.length), 'Parties tracked'],
    [String(rows.filter(function (p) { return p.status === 'government'; }).length), 'In government'],
    [String(totalDelivered), 'Commitments delivered'],
    [String(totalReversed), 'Reversed or abandoned'],
    [String(totalFindings), 'Officer findings']
  ].map(function (r) {
    return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
  }).join('');
  $('pt-list').innerHTML = '<div class="wtf-pt-grid">' + rows.map(card).join('') + '</div>';
}

function indexShell() {
  return '<header class="phead" style="text-align:center;max-width:82ch;margin-left:auto;margin-right:auto">' +
    '<div class="eyebrow">Twenty-five years of record</div>' +
    '<h1>Political parties</h1>' +
    '<p class="lede" style="margin-left:auto;margin-right:auto">Seats and vote share back to 2000, every leader since, what each party delivered, ' +
    'what it reversed, and what independent officers found. No party is given a grade.</p>' +
    '</header>' +
    '<div class="statrow" id="pt-stats"></div>' +
    '<div class="wtf-pl-tabs" id="pt-tabs">' +
      '<button class="wtf-pl-tab on" data-l="federal">Federal</button>' +
      '<button class="wtf-pl-tab" data-l="provincial">Provincial</button>' +
      '<button class="wtf-pl-tab" data-l="municipal">Municipal</button>' +
    '</div>' +
    '<div id="pt-list"></div>' +
    '<div class="wtf-pt-panel" style="margin-top:16px;border-left:3px solid var(--wtf-developing)">' +
      '<div class="psec" style="color:var(--wtf-developing)">Why there is no score</div>' +
      '<div style="font-size:13px;line-height:1.8;color:var(--wtf-text-2);max-width:78ch;text-wrap:pretty">' +
      '<p style="margin:0 0 10px">A party record reduced to a grade would be this newsroom\u2019s opinion wearing the clothes of a measurement. ' +
      'So the record is two columns of cited facts instead: what was <strong>delivered</strong>, what was <strong>reversed or abandoned</strong>, ' +
      'and what <strong>independent officers found</strong> \u2014 each with a date and a document. Readers weigh those themselves.</p>' +
      '<p style="margin:0 0 10px">Two asymmetries are stated rather than smoothed over. A party that has never governed has almost nothing in the ' +
      'delivered column, and that is a fact about opportunity, not intent. And a party that governs for twenty years accumulates more findings than ' +
      'one that governs for two \u2014 more government means more auditing, so raw finding counts favour whoever held office least.</p>' +
      '<p style="margin:0">Seat counts and vote shares are both shown for every election because the gap between them is the most under-reported ' +
      'fact in Canadian politics. Roughly 39% of the vote produced a majority government in 2011 and again in 2015, for different parties.</p>' +
      '</div></div>';
}

/* ── boot ───────────────────────────────────────────────────────────────── */
const wanted = new URLSearchParams(location.search).get('party');
const party = wanted && byId(wanted);

if (party) {
  document.title = party.short + ' \u2014 party record \u00b7 What The Fact';
  $('pt-app').innerHTML = detail(party);
  $('pt-app').addEventListener('click', function (e) {
    const b = e.target.closest('.wtf-pt-more');
    if (!b) return;
    const box = document.getElementById('ctx-' + b.dataset.k);
    if (!box) return;
    const open = box.hidden;
    box.hidden = !open;
    b.setAttribute('aria-expanded', String(open));
    b.classList.toggle('on', open);
    b.querySelector('span').textContent = open ? '\u2212' : '+';
    b.firstChild.textContent = open ? 'Hide context ' : 'Full context ';
  });
} else {
  $('pt-app').innerHTML = indexShell();
  $('pt-tabs').addEventListener('click', function (e) {
    const b = e.target.closest('[data-l]');
    if (!b) return;
    level = b.dataset.l;
    document.querySelectorAll('#pt-tabs .wtf-pl-tab').forEach(function (x) { x.classList.toggle('on', x === b); });
    const want = level === 'federal' ? '' : '#' + level;
    if (location.hash !== want) history.replaceState(null, '', level === 'federal' ? location.pathname : want);
    drawIndex();
  });
  const h = location.hash.slice(1);
  if (['provincial', 'municipal'].indexOf(h) >= 0) {
    level = h;
    document.querySelectorAll('#pt-tabs .wtf-pl-tab').forEach(function (x) {
      x.classList.toggle('on', x.dataset.l === level);
    });
  }
  drawIndex();
}

})();
