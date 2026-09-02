/* Elections: electors, by-elections, deadlines, turnout and the coverage arc.

   Split out of wtf-elections.js deliberately. Both files run inside their own
   IIFE and read only the global DATA files (wtf-candidates.js), never each
   other's helpers — which is what stops the identifier collisions that broke
   this page when wtf-corpus.js was added alongside it. */

(function () {
'use strict';

const $ = function (id) { return document.getElementById(id); };
const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};
const REF = new Date('2026-09-02T12:00:00Z');
const days = function (iso) { return Math.round((new Date(iso + 'T12:00:00Z') - REF) / 864e5); };
const dfmt = function (iso) {
  return new Date(iso + 'T12:00:00Z').toLocaleDateString('en-CA', { month:'short', day:'numeric', year:'numeric' });
};
const urgency = function (d) {
  return d < 45 ? 'var(--wtf-contested)' : d < 200 ? 'var(--wtf-developing)'
    : d < 800 ? 'var(--wtf-local)' : 'var(--wtf-text-muted)';
};
const PROV_NAME = { ON:'Ontario', QC:'Québec', BC:'British Columbia', AB:'Alberta', MB:'Manitoba',
  SK:'Saskatchewan', NS:'Nova Scotia', NB:'New Brunswick', NL:'Newfoundland & Labrador',
  PE:'Prince Edward Island', YT:'Yukon', NT:'Northwest Territories', NU:'Nunavut' };
const pn = function (p) { return PROV_NAME[p] || p; };

/* ── electors: the denominator under every turnout figure ───────────────── */
(function () {
  const host = $('el-electors');
  if (!host || typeof ELECTORS_TREND === 'undefined') return;
  const th = function (h, i) {
    return '<th style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.13em;' +
      'text-transform:uppercase;color:var(--wtf-text-muted);text-align:' + (i ? 'right' : 'left') +
      ';padding:0 10px 9px 0;border-bottom:1px solid var(--wtf-border)">' + h + '</th>';
  };
  const td = 'padding:9px 10px 9px 0;border-bottom:1px solid #161d29;';
  host.innerHTML =
    '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse"><thead><tr>' +
    ['Election', 'Registered', 'Ballots cast', 'Turnout'].map(th).join('') +
    '</tr></thead><tbody>' +
    ELECTORS_TREND.map(function (t, i) {
      const prev = ELECTORS_TREND[i - 1];
      const fell = prev && t.pct < prev.pct;
      return '<tr>' +
        '<td style="' + td + 'font-family:var(--wtf-font-mono);font-size:11.5px;color:var(--wtf-text)">' + t.year + '</td>' +
        '<td style="' + td + 'text-align:right;font-family:var(--wtf-font-mono);font-size:11px;color:var(--wtf-text-2)">' + (t.reg / 1e6).toFixed(2) + 'M</td>' +
        '<td style="' + td + 'text-align:right;font-family:var(--wtf-font-mono);font-size:11px;color:var(--wtf-text-2)">' + (t.voted / 1e6).toFixed(2) + 'M</td>' +
        '<td style="padding:9px 0;border-bottom:1px solid #161d29;text-align:right;font-family:var(--wtf-font-mono);font-size:11.5px;color:' +
          (fell ? 'var(--wtf-contested)' : 'var(--wtf-established)') + '">' + t.pct.toFixed(1) + '%' +
          (prev ? ' <span style="font-size:9px;color:var(--wtf-text-muted)">' +
            (t.pct >= prev.pct ? '+' : '\u2212') + Math.abs(t.pct - prev.pct).toFixed(1) + '</span>' : '') +
        '</td></tr>';
    }).join('') +
    '</tbody></table></div>' +
    '<p class="wtf-el-note" style="margin-top:11px">2021 is the row worth pausing on: the register was ' +
    'essentially flat and 1.3 million fewer ballots were cast, a 4.4-point fall. In 2025 the register grew by ' +
    '1.2 million and turnout recovered to 68.4% \u2014 both the numerator and the denominator moved, so reporting ' +
    'either one alone would mislead.</p>';
})();

(function () {
  const host = $('el-reg');
  if (!host || typeof ELECTORS_PROV === 'undefined') return;
  const rows = ELECTORS_PROV.slice().sort(function (a, b) { return b.reg - a.reg; });
  const max = rows[0].reg;
  const totReg = rows.reduce(function (n, r) { return n + r.reg; }, 0);
  const totPop = rows.reduce(function (n, r) { return n + r.pop; }, 0);
  host.innerHTML = rows.map(function (r) {
    return '<div class="wtf-el-cov">' +
      '<span style="font-size:12.5px;color:var(--wtf-text-2)">' + pn(r.p) + '</span>' +
      '<span class="wtf-el-cov-t"><i style="width:' + Math.round(r.reg / max * 100) + '%;background:var(--wtf-local)"></i></span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' +
        (r.reg >= 1e6 ? (r.reg / 1e6).toFixed(1) + 'M' : Math.round(r.reg / 1e3) + 'k') + '</span></div>' +
      '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin:-2px 0 8px 160px">' +
        (r.reg / r.pop * 100).toFixed(0) + '% of population registered</div>';
  }).join('') +
    '<p class="wtf-el-note" style="margin-top:10px">' + (totReg / 1e6).toFixed(1) + 'M registered against ' +
    (totPop / 1e6).toFixed(1) + 'M residents, or ' + (totReg / totPop * 100).toFixed(0) + '%. That gap is not all ' +
    'apathy: it includes everyone under eighteen, permanent residents and other non-citizens, all of whom count in ' +
    'the population and none of whom can register.</p>';
})();

/* ── turnout by level ───────────────────────────────────────────────────── */
(function () {
  const host = $('el-turnout');
  if (!host || typeof TURNOUT === 'undefined') return;
  const max = Math.max.apply(null, TURNOUT.map(function (t) { return t.pct; }));
  const col = function (p) {
    return p < 32 ? 'var(--wtf-contested)' : p < 55 ? 'var(--wtf-developing)' : 'var(--wtf-established)';
  };
  host.innerHTML = TURNOUT.map(function (t) {
    return '<div class="wtf-el-cov">' +
      '<span style="font-size:12.5px;color:var(--wtf-text-2)">' + t.level + '</span>' +
      '<span class="wtf-el-cov-t"><i style="width:' + Math.round(t.pct / max * 100) + '%;background:' + col(t.pct) + '"></i></span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' + t.pct.toFixed(1) + '%</span></div>' +
      '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin:-2px 0 8px 160px">' + t.note + '</div>';
  }).join('') +
    '<p class="wtf-el-note" style="margin-top:10px">A ward councillor is elected by under three voters in ten, and ' +
    'decides the zoning on one street. The gap between the top and bottom rows is roughly forty points \u2014 the same ' +
    'direction as the coverage gap, which is the point.</p>';
})();

/* ── coverage arc: did coverage follow the campaign? ────────────────────── */
(function () {
  const host = $('el-arc');
  if (!host || typeof COVERAGE_ARC === 'undefined') return;
  /* A share of a tiny total is noise: 100% of two articles is an absence, not
     a concentration. Below ten articles the ratio is withheld. */
  const MIN_N = 10;
  const peak = Math.max.apply(null, COVERAGE_ARC.map(function (a) {
    return Math.max(a.before, a.during, a.after);
  }).concat([1]));
  const bar = function (v, lab, c) {
    return '<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px">' +
      '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text)">' + v + '</span>' +
      '<span style="width:100%;height:' + Math.max(2, Math.round(v / peak * 46)) + 'px;background:' + c + ';border-radius:3px 3px 0 0"></span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:8px;letter-spacing:.06em;color:var(--wtf-text-muted)">' + lab + '</span></div>';
  };
  host.innerHTML =
    '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:11px">' +
    COVERAGE_ARC.slice().sort(function (a, b) {
      return (b.before + b.during + b.after) - (a.before + a.during + a.after);
    }).map(function (a) {
      const tot = a.before + a.during + a.after;
      const spike = tot >= MIN_N ? Math.round(a.during / tot * 100) : null;
      return '<div style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);border-radius:10px;padding:12px 13px">' +
        '<div style="display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:9px">' +
          '<span style="font-size:13.5px;color:var(--wtf-text)">' + esc(a.city) + '</span>' +
          '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted)">' + a.prov + '</span></div>' +
        '<div style="display:flex;align-items:flex-end;gap:5px;height:74px">' +
          bar(a.before, 'BEFORE', 'var(--wtf-local)') +
          bar(a.during, 'VOTE', 'var(--wtf-accent)') +
          bar(a.after, 'AFTER', 'var(--wtf-text-muted)') +
        '</div>' +
        '<div style="margin-top:9px;padding-top:8px;border-top:1px solid var(--wtf-border);display:flex;flex-direction:column;gap:5px">' +
          '<div style="display:flex;justify-content:space-between;gap:8px">' +
            '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:' +
              (tot < MIN_N ? 'var(--wtf-contested)' : 'var(--wtf-text)') + '">' + tot + ' articles in nine weeks</span>' +
            '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:' +
              (a.turnout < 32 ? 'var(--wtf-contested)' : 'var(--wtf-developing)') + '">' + a.turnout.toFixed(1) + '% turnout</span></div>' +
          '<span style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted)">' +
            (spike === null ? 'too few articles to distribute'
              : spike + '% of it in vote week' + (spike >= 70 ? ' \u2014 heavily concentrated' : '')) + '</span>' +
        '</div></div>';
    }).join('') + '</div>' +
    '<p class="wtf-el-note" style="margin-top:12px">Cards are ordered by total volume, which is the number that ' +
    'matters here. Grande Prairie and Red Deer received two and three articles across the whole nine weeks and came in ' +
    'under 25% turnout; Calgary received 61 and cleared 38%. Where a city has fewer than ten articles the vote-week ' +
    'share is withheld: all of two articles landing in one week is an absence of coverage, not a concentration of it, ' +
    'and printing it as 100% would rank the least-covered city as the most intensively covered. This is a correlation ' +
    'across six cities, not a causal claim \u2014 but it is the correlation a newsroom should be willing to publish about ' +
    'itself.</p>';
})();

/* ── deadlines ──────────────────────────────────────────────────────────── */
(function () {
  const host = $('el-deadlines');
  if (!host || typeof DEADLINES === 'undefined') return;
  host.innerHTML = DEADLINES.slice()
    .sort(function (a, b) { return a.vote.localeCompare(b.vote); })
    .map(function (d) {
      const vn = days(d.vote);
      return '<div class="wtf-el-panel">' +
        '<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin-bottom:12px">' +
          '<span style="font-family:var(--wtf-font-serif);font-size:18px;font-weight:600;color:var(--wtf-text)">' + esc(d.election) + '</span>' +
          '<span class="wtf-el-tag" style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:' + urgency(vn) + '">' +
            'votes ' + dfmt(d.vote) + ' \u00b7 ' + vn + ' days</span></div>' +
        /* Authored order is not date order, and this is the chronology tab. */
        d.items.slice().sort(function (a, b) { return a[1].localeCompare(b[1]); }).map(function (it) {
          const n = days(it[1]);
          const passed = n < 0;
          return '<div class="wtf-el-row" style="grid-template-columns:104px minmax(0,1fr) auto">' +
            '<span class="wtf-el-date" style="color:' + (passed ? 'var(--wtf-text-muted)' : urgency(n)) + '">' + dfmt(it[1]) +
              '<span>' + (passed ? Math.abs(n) + ' days ago' : 'in ' + n + ' days') + '</span></span>' +
            '<span><span class="wtf-el-place"' + (passed ? ' style="color:var(--wtf-text-muted)"' : '') + '>' + esc(it[0]) + '</span>' +
              '<span class="wtf-el-sub">' + esc(it[2]) + '</span></span>' +
            '<span class="wtf-el-tag" style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:' +
              (passed ? 'var(--wtf-established)' : 'var(--wtf-developing)') + '">' + (passed ? 'closed' : 'open') + '</span></div>';
        }).join('') +
      '</div>';
    }).join('');
})();

/* ── by-elections: called, not scheduled ────────────────────────────────── */
(function () {
  if (typeof BYELECTIONS === 'undefined' || !$('el-by-stats')) return;
  const CAUSE_COL = { resignation:'var(--wtf-developing)', death:'var(--wtf-text-muted)',
    'appointment to another office':'var(--wtf-local)' };
  const LVL = { federal:'Federal', provincial:'Provincial', municipal:'Municipal' };

  $('el-by-law').innerHTML = Object.keys(BYELECTION_LAW).map(function (k) {
    return '<div style="display:grid;grid-template-columns:96px minmax(0,1fr);gap:11px;padding:6px 0;border-bottom:1px solid #161d29">' +
      '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--wtf-text-2)">' + LVL[k] + '</span>' +
      '<span style="font-size:12px;line-height:1.6;color:var(--wtf-text-muted)">' + esc(BYELECTION_LAW[k]) + '</span></div>';
  }).join('');

  const pending = BYELECTIONS.filter(function (b) { return b.status === 'pending'; });
  const other = BYELECTIONS.filter(function (b) { return b.status !== 'pending'; });
  const held = BYELECTIONS.filter(function (b) { return b.status === 'held'; });
  const avgGap = held.length
    ? held.reduce(function (n, b) { return n + (b.genTurnout - b.turnout); }, 0) / held.length : 0;

  $('el-by-stats').innerHTML = [
    [String(BYELECTIONS.length), 'By-elections tracked'],
    [String(pending.length), 'Seats vacant, no writ'],
    [String(BYELECTIONS.filter(function (b) { return b.status === 'scheduled'; }).length), 'Writ issued'],
    ['\u2212' + avgGap.toFixed(1) + ' pts', 'Turnout vs the general'],
    [String(Math.max.apply(null, pending.map(function (b) { return days(b.deadline); }).concat([0]))), 'Longest days left to call']
  ].map(function (r) {
    return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
  }).join('');

  /* Days VACANT is the number that goes unreported \u2014 an election date alone
     hides how long a seat sat empty inside a lawful window. */
  $('el-by-pending').innerHTML = pending.length
    ? pending.slice().sort(function (a, b) { return a.deadline.localeCompare(b.deadline); }).map(function (b) {
        const vacantFor = -days(b.vacated);
        const left = days(b.deadline);
        return '<div class="wtf-el-row" style="grid-template-columns:104px minmax(0,1fr) auto">' +
          '<span class="wtf-el-date" style="color:' + urgency(left) + '">' + left + ' days<span>left to call</span></span>' +
          '<span><span class="wtf-el-place">' + esc(b.seat) + '</span>' +
            '<span class="wtf-el-sub">' + LVL[b.level] + ' \u00b7 ' + pn(b.prov) + ' \u00b7 vacant ' + vacantFor + ' days</span>' +
            '<span class="wtf-el-sub" style="color:var(--wtf-text-2)">' + esc(b.former) + ' (' + esc(b.formerParty) + ') \u2014 ' +
              esc(b.cause) + '. ' + esc(b.note) + '</span></span>' +
          '<span class="wtf-el-tag" style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:' +
            (CAUSE_COL[b.cause] || 'var(--wtf-text-muted)') + '">no writ</span></div>';
      }).join('')
    : '<div class="wtf-el-none">No seat is currently vacant without a writ.</div>';

  $('el-by-held').innerHTML = other.length
    ? other.slice().sort(function (a, b) {
        return (b.held || b.called || '').localeCompare(a.held || a.called || '');
      }).map(function (b) {
        const isHeld = b.status === 'held';
        const when = b.held || b.called;
        return '<div class="wtf-el-row" style="grid-template-columns:104px minmax(0,1fr) auto">' +
          '<span class="wtf-el-date" style="color:' + (isHeld ? 'var(--wtf-text-muted)' : urgency(days(when))) + '">' +
            dfmt(when) + '<span>' + (isHeld ? 'held' : 'writ issued') + '</span></span>' +
          '<span><span class="wtf-el-place">' + esc(b.seat) + '</span>' +
            '<span class="wtf-el-sub">' + LVL[b.level] + ' \u00b7 ' + pn(b.prov) + ' \u00b7 ' + esc(b.cause) + '</span>' +
            (isHeld
              ? '<span class="wtf-el-sub" style="color:var(--wtf-text-2)">' + esc(b.winner) + ' won by ' + b.margin.toFixed(1) +
                ' pts on ' + b.turnout.toFixed(1) + '% turnout, against ' + b.genTurnout.toFixed(1) + '% at the general</span>'
              : '<span class="wtf-el-sub" style="color:var(--wtf-text-2)">' + esc(b.note) + '</span>') + '</span>' +
          (isHeld
            ? '<span class="wtf-el-tag" style="background:rgba(224,82,82,.14);color:var(--wtf-contested)">\u2212' +
              (b.genTurnout - b.turnout).toFixed(1) + ' pts</span>'
            : '<a class="wtf-el-tag" style="text-decoration:none;background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-2)" href="wtf-races.html#' + b.level + '">candidates &rarr;</a>') +
          '</div>';
      }).join('')
    : '<div class="wtf-el-none">Nothing called or held in this window.</div>';

  $('el-by-turnout').innerHTML =
    '<p style="font-size:13px;line-height:1.75;color:var(--wtf-text-2);margin:0 0 13px;max-width:76ch;text-wrap:pretty">' +
      'A by-election decides one seat and changes no government, so far fewer people vote in it. Every one held here ' +
      'came in well below the general election in the same district \u2014 which means a member can take a seat on the ' +
      'support of roughly one voter in six and hold it until the next general.</p>' +
    held.slice().sort(function (a, b) {
      return (a.genTurnout - a.turnout) - (b.genTurnout - b.turnout);
    }).map(function (b) {
      return '<div style="margin-bottom:13px">' +
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:5px">' +
          '<span style="font-size:12.5px;color:var(--wtf-text-2)">' + esc(b.seat) + '</span>' +
          '<span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-contested)">\u2212' +
            (b.genTurnout - b.turnout).toFixed(1) + ' points</span></div>' +
        '<div style="position:relative;height:16px;background:var(--wtf-bg);border-radius:4px;overflow:hidden">' +
          '<span style="position:absolute;left:0;top:0;bottom:0;width:' + b.genTurnout + '%;background:var(--wtf-established);opacity:.28"></span>' +
          '<span style="position:absolute;left:0;top:0;bottom:0;width:' + b.turnout + '%;background:var(--wtf-contested)"></span></div>' +
        '<div style="display:flex;justify-content:space-between;font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin-top:3px">' +
          '<span>by-election ' + b.turnout.toFixed(1) + '%</span><span>general ' + b.genTurnout.toFixed(1) + '%</span></div>' +
      '</div>';
    }).join('') +
    '<p class="wtf-el-note">Toronto Ward 19 is the extreme case: 16.8% against 38.2% at the general, and the winner ' +
    'took it by four points. Council could have appointed instead of voting, and chose the by-election \u2014 which is ' +
    'the more accountable option even at that turnout.</p>';
})();

})();
