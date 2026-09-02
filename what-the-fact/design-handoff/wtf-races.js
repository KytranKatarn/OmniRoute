/* Races: an index of contests, and a per-race view reached by ?race=id.
   Per-race rather than per-candidate because during a campaign the useful
   question is "who is running here", and a per-candidate page for a private
   citizen with no record would be a page about a person we know nothing about. */

(function () {
'use strict';


const $ = id => document.getElementById(id);
const esc = x => String(x == null ? '' : x).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const NOW = new Date('2026-09-02T12:00:00Z');
const days = iso => Math.round((new Date(iso + 'T12:00:00Z') - NOW) / 864e5);
const dfmt = iso => new Date(iso + 'T12:00:00Z').toLocaleDateString('en-CA', { month:'short', day:'numeric', year:'numeric' });
const urgency = d => d < 45 ? 'var(--wtf-contested)' : d < 200 ? 'var(--wtf-developing)' : d < 800 ? 'var(--wtf-local)' : 'var(--wtf-text-muted)';
const colOf = p => CAND_COL[p] || null;
const initials = n => n.split(/[\s.]+/).filter(Boolean).map(w => w[0]).slice(0, 2).join('');
const PROV_FULL = { ON:'Ontario', QC:'Qu\u00e9bec', BC:'British Columbia', AB:'Alberta', MB:'Manitoba',
  SK:'Saskatchewan', NS:'Nova Scotia', NB:'New Brunswick', NL:'Newfoundland & Labrador',
  PE:'Prince Edward Island', YT:'Yukon', NT:'Northwest Territories', NU:'Nunavut' };

/* Past races carry a result and no candidate slate, so every helper has to
   tolerate a missing cands array rather than assume a live race. */
const RACES = ALL_RACES.concat(PAST_RACES.map(r => ({ ...r, cands:r.cands || [], past:true })));
const confirmedOf = r => (r.cands || []).filter(c => c.status === 'confirmed');
const declaredOf  = r => (r.cands || []).filter(c => c.status === 'declared');

/* ── race detail ────────────────────────────────────────────────────────── */
/* A municipal race stores seat and city separately, so the seat alone
   ('mayor') cannot be a headline — 12 cities would share the byte-identical
   title "mayor" on a page whose whole job is saying who is running HERE. */
function headingFor(r) {
  if (r.level !== 'municipal' || !r.city) return r.seat;
  const seat = /^(mayor|council)/.test(r.seat) ? r.seat.charAt(0).toUpperCase() + r.seat.slice(1) : r.seat;
  return r.city + ' \u2014 ' + seat;
}

function detail(r) {
  const conf = confirmedOf(r), decl = declaredOf(r);
  const n = days(r.date);
  const lvl = RACE_LEVELS[r.level];
  const inc = r.incumbent;

  const card = c => {
    const col = colOf(c.party);
    const np = !col;
    return '<div class="wtf-ca-card' + (np ? ' np' : '') + '"' + (col ? ' style="--pc:' + col + '"' : '') + '>' +
      '<div class="wtf-ca-av"' + (col ? ' style="--pc:' + col + '"' : '') + '>' + initials(c.name) + '<small>No photo</small></div>' +
      (c.inc ? '<span class="wtf-ca-inc">Incumbent</span>' : '') +
      '<div class="wtf-ca-nm">' + esc(c.name) + '</div>' +
      '<div class="wtf-ca-pt"' + (col ? ' style="--pc:' + col + '"' : '') + '>' + esc(c.party) + '</div>' +
      '<div class="wtf-ca-cf">Nominated ' + dfmt(c.confirmed) + '</div>' +
      /* Mentions are counted FROM the nomination date, so a challenger
         confirmed in August is not compared against a minister's full year. */
      '<div class="wtf-ca-mn">' + c.mentions + ' mention' + (c.mentions === 1 ? '' : 's') + ' since nomination</div>' +
      (c.inc && r.incumbent && r.incumbent.slug
        ? '<a href="wtf-mp.html?slug=' + encodeURIComponent(r.incumbent.slug) + '" style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-local);text-decoration:none;margin-top:4px">Their record &rarr;</a>'
        : '') +
      '</div>';
  };

  const mentionBars = () => {
    if (conf.length < 2) return '';
    const max = Math.max.apply(null, conf.map(c => c.mentions).concat([1]));
    return '<div class="wtf-ca-panel"><div class="psec">Coverage since nomination</div>' +
      conf.slice().sort((a, b) => b.mentions - a.mentions).map(c => {
        const col = colOf(c.party) || 'var(--wtf-text-muted)';
        return '<div class="wtf-ca-bars"><span style="font-size:12.5px;color:var(--wtf-text-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' +
          esc(c.name) + (c.inc ? ' <span style="color:var(--wtf-developing)">\u25cf</span>' : '') + '</span>' +
          '<span class="wtf-ca-bt"><i style="width:' + Math.round(c.mentions / max * 100) + '%;background:' + col + '"></i></span>' +
          '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' + c.mentions + '</span></div>';
      }).join('') +
      '<p class="wtf-ca-note" style="margin-top:10px">Counted from each candidate\u2019s own nomination date, not from a shared start, ' +
      'so a late nomination is not penalised for arriving late. An incumbent still leads almost every one of these: ' +
      'holding office generates coverage by itself, which is a fact about the office and not a measure of the campaign.</p></div>';
  };

  const resultPanel = () => {
    const R = r.result;
    if (!R) return '';
    const arc = COVERAGE_ARC.find(a => a.city === r.city);
    return '<div class="wtf-ca-panel" style="border-left:3px solid var(--wtf-established)">' +
      '<div class="psec" style="color:var(--wtf-established)">Result</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:baseline;margin-bottom:13px">' +
        '<span style="font-family:var(--wtf-font-serif);font-size:22px;font-weight:600;color:var(--wtf-text)">' + esc(R.winner) + '</span>' +
        '<span class="wtf-ca-tag" style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:' +
          (colOf(R.winnerParty) || 'var(--wtf-text-muted)') + '">' + esc(R.winnerParty) + '</span>' +
        '<span style="font-family:var(--wtf-font-mono);font-size:11px;color:var(--wtf-text-2)">won by ' + R.margin.toFixed(1) + ' points</span>' +
      '</div>' +
      R.tally.map(t => {
        const col = colOf(t[1]) || 'var(--wtf-text-muted)';
        const win = t[0] === R.winner;
        return '<div class="wtf-ca-bars"><span style="font-size:12.5px;color:' + (win ? 'var(--wtf-text)' : 'var(--wtf-text-2)') + '">' +
          esc(t[0]) + '</span>' +
          '<span class="wtf-ca-bt"><i style="width:' + t[2] + '%;background:' + col + ';opacity:' + (win ? 1 : .6) + '"></i></span>' +
          '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text);text-align:right">' + t[2].toFixed(1) + '</span></div>';
      }).join('') +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:14px;padding-top:12px;border-top:1px solid var(--wtf-border)">' +
        '<div><div class="wtf-ca-cf">Turnout</div><div style="font-family:var(--wtf-font-mono);font-size:17px;color:' +
          (R.turnout < 35 ? 'var(--wtf-contested)' : R.turnout < 55 ? 'var(--wtf-developing)' : 'var(--wtf-established)') +
          '">' + R.turnout.toFixed(1) + '%</div></div>' +
        '<div><div class="wtf-ca-cf">Ballots cast</div><div style="font-family:var(--wtf-font-mono);font-size:17px;color:var(--wtf-text)">' + R.ballots.toLocaleString() + '</div></div>' +
        (arc ? '<div><div class="wtf-ca-cf">Articles, week of vote</div><div style="font-family:var(--wtf-font-mono);font-size:17px;color:var(--wtf-local)">' + arc.during + '</div></div>' : '') +
      '</div>' +
      '<p class="wtf-ca-note" style="margin-top:11px">Margin is in points of the vote, so a two-point win and a forty-point win cannot be made to look alike. ' +
      (R.turnout < 40 ? 'A turnout under 40% means the winner was chosen by a minority of eligible voters \u2014 normal at this level, and worth stating rather than glossing. ' : '') +
      (arc ? 'Coverage ran ' + arc.before + ' articles a week before the vote and ' + arc.after + ' after it. ' : '') +
      '</p></div>';
  };

  return '<div class="wtf-ca-hero">' +
    '<a class="wtf-ca-back" href="wtf-races.html">&larr; All races</a>' +
    '<h1 class="wtf-ca-h1">' + esc(headingFor(r)) + '</h1>' +
    '<div class="wtf-ca-meta">' +
      '<span class="wtf-ca-tag" style="background:var(--wtf-bg-panel);color:var(--wtf-text-2);border:1px solid var(--wtf-border)">' + lvl.label + '</span>' +
      '<span class="wtf-ca-place">' + esc(PROV_FULL[r.prov] || r.prov) + '</span>' +
      (r.pop ? '<span class="wtf-ca-place">' + r.pop.toLocaleString() + ' residents</span>' : '') +
      '<span class="wtf-ca-tag" style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:' + urgency(n) + '">' +
        dfmt(r.date) + ' \u00b7 ' + n + ' days</span>' +
    '</div></div>' +

    /* Incumbency is a flag with a link out. The race never renders a voting
       record — that would give one candidate a page the others cannot have. */
    resultPanel() +

    (inc ? '<div class="wtf-ca-panel" style="margin-top:0;border-left:3px solid var(--wtf-developing)">' +
      '<div class="psec" style="color:var(--wtf-developing)">Sitting member</div>' +
      '<div style="font-size:13.5px;line-height:1.7;color:var(--wtf-text-2);max-width:74ch">' +
        '<strong style="color:var(--wtf-text)">' + esc(inc.name) + '</strong> (' + esc(inc.party) + ') holds this seat and ' +
        (inc.running ? 'is standing again' : 'is <strong>' + esc(inc.note || 'not standing again') + '</strong>') + '. ' +
        'Their record is on their own profile rather than here \u2014 a voting record belongs to an office holder, and printing it inside a race would hand one candidate a page their opponents cannot have.</div>' +
      '<a class="wtf-ca-tag" style="display:inline-block;margin-top:11px;text-decoration:none;background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-2);padding:7px 14px" href="wtf-mp.html?slug=' + encodeURIComponent(inc.slug) + '">' +
        esc(inc.name) + '\u2019s record &rarr;</a></div>' : '') +

    (r.past ? '' : '<div class="wtf-ca-panel"><div class="psec">Confirmed nominations <span style="text-transform:none;letter-spacing:0;color:var(--wtf-text-muted)">(' + conf.length + ')</span></div>' +
      (conf.length
        ? '<div class="wtf-ca-grid">' + conf.map(card).join('') + '</div>'
        : '<div class="wtf-ca-none">No nomination confirmed in this ' + lvl.unit + ' yet.<br>' +
          '<span style="font-size:12px">An empty slate this close to the vote is itself worth reporting \u2014 it is not a gap in our data.</span></div>') +
      '<p class="wtf-ca-note" style="margin-top:11px">Confirmed means the nomination is on file with ' + lvl.body + '. ' +
      (r.partisan === false ? 'This race is <strong>non-partisan</strong>: candidates run without a party, which is how most Canadian municipal elections work. Party colour is absent here by design. ' : '') +
      'Photographs come from each candidate\u2019s own filing and are not shown until supplied.</p></div>') +

    mentionBars() +

    (decl.length ? '<div class="wtf-ca-panel" style="border-left:3px solid var(--wtf-text-muted)">' +
      '<div class="psec">Declared but not confirmed <span style="text-transform:none;letter-spacing:0;color:var(--wtf-text-muted)">(' + decl.length + ')</span></div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:7px;margin-bottom:10px">' +
        decl.map(c => '<span class="wtf-ca-pip' + (colOf(c.party) ? '' : ' np') + '"' +
          (colOf(c.party) ? ' style="--pc:' + colOf(c.party) + '"' : '') + '><i></i>' + esc(c.name) +
          ' <span style="color:var(--wtf-text-muted)">' + esc(c.party) + '</span></span>').join('') + '</div>' +
      '<p class="wtf-ca-note">These names have said publicly that they intend to run, and no nomination is on file. ' +
      'They are kept out of the slate above and carry no mention count, because counting coverage of an unconfirmed candidate ' +
      'would treat an intention as a candidacy.</p></div>' : '') +

    '<div class="wtf-ca-panel"><div class="psec">Where this sits</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        '<a class="wtf-ca-tag" style="text-decoration:none;background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-2);padding:8px 15px" href="wtf-elections.html#' + r.level + '">' + lvl.label + ' calendar &rarr;</a>' +
        (r.riding ? '<a class="wtf-ca-tag" style="text-decoration:none;background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-2);padding:8px 15px" href="wtf-mps.html?rd=' + encodeURIComponent(r.riding) + '#ridings">This riding on the map &rarr;</a>' : '') +
        (r.level === 'municipal'
          ? '<a class="wtf-ca-tag" style="text-decoration:none;background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-2);padding:8px 15px" href="wtf-municipal.html">Municipal coverage &rarr;</a>'
          : '<a class="wtf-ca-tag" style="text-decoration:none;background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);color:var(--wtf-text-2);padding:8px 15px" href="wtf-mps.html#ridings">Riding boundaries &rarr;</a>') +
      '</div></div>';
}

/* ── index ──────────────────────────────────────────────────────────────── */
let S = { level:'', q:'', prov:'', sort:'date', gaps:false, past:false };

function indexShell() {
  return '<header class="phead" style="text-align:center;max-width:82ch;margin-left:auto;margin-right:auto">' +
    '<div class="eyebrow">Confirmed nominations only</div>' +
    '<h1>Candidates &amp; races</h1>' +
    '<p class="lede" style="margin-left:auto;margin-right:auto">Who is actually running, at all three levels \u2014 including mayors and ward councillors, because a ward decides the zoning on one street and a mayor does not.</p>' +
    '</header>' +
    '<div class="statrow" id="ca-stats"></div>' +
    '<div class="wtf-pl-tabs" id="ca-tabs">' +
      '<button class="wtf-pl-tab on" data-l="">All levels</button>' +
      '<button class="wtf-pl-tab" data-l="federal">Federal</button>' +
      '<button class="wtf-pl-tab" data-l="provincial">Provincial</button>' +
      '<button class="wtf-pl-tab" data-l="municipal">Municipal</button>' +
    '</div>' +
    '<div class="wtf-ca-ctrl">' +
      '<input type="search" id="ca-q" placeholder="Riding, city, ward, candidate&hellip;" aria-label="Search races">' +
      '<select id="ca-prov" aria-label="Province"></select>' +
      '<select id="ca-sort" aria-label="Sort">' +
        '<option value="date">Soonest vote</option>' +
        '<option value="field">Largest field</option>' +
        '<option value="name">Alphabetical</option>' +
      '</select>' +
      '<button class="wtf-pl-tab" id="ca-gaps">Empty slates only</button>' +
      '<button class="wtf-pl-tab" id="ca-past">Past results</button>' +
      '<span id="ca-count" style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted);margin-left:auto"></span>' +
    '</div>' +
    '<div id="ca-list"></div>' +
    '<div class="wtf-ca-panel" style="border-left:3px solid var(--wtf-developing)">' +
      '<div class="psec" style="color:var(--wtf-developing)">What this list is not</div>' +
      '<p style="font-size:13px;line-height:1.75;color:var(--wtf-text-2);margin:0;max-width:76ch;text-wrap:pretty">' +
      'It is not a full slate. A nomination appears here once it is on file, so most races are incomplete this far out and ' +
      'that incompleteness is the reporting rather than a defect. It carries no endorsement, no ranking and no prediction: ' +
      'candidates are ordered by nomination date, and a mention count measures how often a name appears in coverage \u2014 never ' +
      'how likely they are to win. We do not name anyone as a candidate before their nomination is filed.</p></div>';
}

function raceRow(r) {
  const conf = confirmedOf(r), n = days(r.date);
  const lvlCol = { federal:'var(--wtf-accent)', provincial:'var(--wtf-local)', municipal:'var(--wtf-aurora)' }[r.level];
  return '<a class="wtf-ca-race" style="--rc:' + lvlCol + '" href="wtf-races.html?race=' + encodeURIComponent(r.id) + '">' +
    '<div class="wtf-ca-rh">' +
      '<span class="wtf-ca-seat">' + esc(r.seat) + '</span>' +
      '<span class="wtf-ca-place">' + esc(r.city ? r.city + ' \u00b7 ' + r.prov : PROV_FULL[r.prov] || r.prov) + '</span>' +
      '<span class="wtf-ca-date" style="color:' + (r.past ? 'var(--wtf-text-muted)' : urgency(n)) + '">' +
      dfmt(r.date) + (r.past ? '' : ' \u00b7 ' + n + 'd') + '</span>' +
    '</div>' +
    (r.past && r.result
      ? '<div class="wtf-ca-slate"><span class="wtf-ca-pip"' +
        (colOf(r.result.winnerParty) ? ' style="--pc:' + colOf(r.result.winnerParty) + '"' : ' class="wtf-ca-pip np"') + '><i></i>' +
        esc(r.result.winner) + ' <b>WON +' + r.result.margin.toFixed(1) + '</b></span>' +
        '<span class="wtf-ca-pip np"><i></i>' + r.result.turnout.toFixed(1) + '% turnout</span></div>'
      : conf.length
      ? '<div class="wtf-ca-slate">' + conf.map(c => {
          const col = colOf(c.party);
          return '<span class="wtf-ca-pip' + (col ? '' : ' np') + '"' + (col ? ' style="--pc:' + col + '"' : '') + '><i></i>' +
            esc(c.name) + (c.inc ? ' <b>INC</b>' : '') + '</span>';
        }).join('') + '</div>'
      : '<div class="wtf-ca-empty">No nomination confirmed yet \u2014 ' + n + ' days out</div>') +
    '</a>';
}

function visible() {
  const q = S.q.toLowerCase();
  return RACES.filter(r =>
    (!S.level || r.level === S.level) &&
    (!S.prov || r.prov === S.prov) &&
    (!S.gaps || !confirmedOf(r).length) &&
    (S.past ? !!r.past : !r.past) &&
    (!q || (r.seat + ' ' + (r.city || '') + ' ' + r.prov + ' ' + (PROV_FULL[r.prov] || '') + ' ' +
      r.cands.map(c => c.name + ' ' + c.party).join(' ')).toLowerCase().includes(q)));
}

function renderIndex() {
  const list = visible();
  list.sort((a, b) =>
    S.sort === 'field' ? confirmedOf(b).length - confirmedOf(a).length :
    S.sort === 'name'  ? a.seat.localeCompare(b.seat) :
    (a.date.localeCompare(b.date) || a.seat.localeCompare(b.seat)));
  $('ca-count').textContent = list.length + ' of ' + RACES.length + ' races';
  $('ca-list').innerHTML = list.length
    ? list.map(raceRow).join('')
    : '<div class="wtf-ca-none">No race matches that filter.</div>';
}

function renderStats() {
  const scope = (S.level ? RACES.filter(r => r.level === S.level) : RACES)
    .filter(r => S.past ? !!r.past : !r.past);
  const conf = scope.reduce((n, r) => n + confirmedOf(r).length, 0);
  const empty = scope.filter(r => !confirmedOf(r).length).length;
  const incRun = scope.reduce((n, r) => n + confirmedOf(r).filter(c => c.inc).length, 0);
  const wards = scope.filter(r => r.level === 'municipal' && /ward|borough|council/i.test(r.seat)).length;
  const withRes = scope.filter(r => r.result);
  const avgTurn = withRes.length
    ? (withRes.reduce((n, r) => n + r.result.turnout, 0) / withRes.length).toFixed(1) + '%' : null;
  $('ca-stats').innerHTML = (S.past ? [
    [String(scope.length), 'Results on record'],
    [avgTurn || '\u2014', 'Average turnout'],
    [String(withRes.filter(r => r.result.turnout < 40).length), 'Under 40% turnout'],
    [String(withRes.filter(r => r.result.margin < 10).length), 'Margin under 10 pts'],
    [String(wards), 'Ward &amp; council seats']
  ] : [
    [String(scope.length), 'Races tracked'],
    [String(conf), 'Confirmed nominations'],
    [String(empty), 'No candidate yet'],
    [String(incRun), 'Incumbents standing'],
    [String(wards), 'Ward &amp; council seats']
  ]).map(([n, l]) => '<div class="stat"><div class="stat-n">' + n + '</div><div class="stat-l">' + l + '</div></div>').join('');
}

/* ── boot ───────────────────────────────────────────────────────────────── */
const wanted = new URLSearchParams(location.search).get('race');
const race = wanted && RACES.find(r => r.id === wanted);

if (race) {
  document.title = headingFor(race) + ' \u2014 candidates \u00b7 What The Fact';
  $('ca-app').innerHTML = detail(race);
} else {
  $('ca-app').innerHTML = indexShell();
  $('ca-prov').innerHTML = '<option value="">Every province</option>' +
    [...new Set(RACES.map(r => r.prov))].sort()
      .map(p => '<option value="' + p + '">' + (PROV_FULL[p] || p) + '</option>').join('');
  $('ca-tabs').addEventListener('click', e => {
    const b = e.target.closest('[data-l]'); if (!b) return;
    S.level = b.dataset.l;
    document.querySelectorAll('#ca-tabs .wtf-pl-tab').forEach(x => x.classList.toggle('on', x === b));
    renderStats(); renderIndex();
  });
  $('ca-q').addEventListener('input', e => { S.q = e.target.value.trim(); renderIndex(); });
  $('ca-prov').addEventListener('change', e => { S.prov = e.target.value; renderIndex(); });
  $('ca-sort').addEventListener('change', e => { S.sort = e.target.value; renderIndex(); });
  $('ca-past').addEventListener('click', () => {
    S.past = !S.past;
    $('ca-past').classList.toggle('on', S.past);
    if (S.past) { S.gaps = false; $('ca-gaps').classList.remove('on'); }
    renderStats(); renderIndex();
  });
  $('ca-gaps').addEventListener('click', () => {
    S.gaps = !S.gaps;
    $('ca-gaps').classList.toggle('on', S.gaps);
    renderIndex();
  });
  const lvl = location.hash.slice(1);
  if (['federal','provincial','municipal'].includes(lvl)) {
    S.level = lvl;
    document.querySelectorAll('#ca-tabs .wtf-pl-tab').forEach(x => x.classList.toggle('on', x.dataset.l === lvl));
  }
  renderStats(); renderIndex();
}


})();
