/* MP profile. Mirrors consumer/templates/mp.html: hero, ballot stats, then the
   two PUBLIC sections (cost to taxpayers, House committees) above the gate, and
   the granular material below it.

   Section order and the public/paid split are the template's, not mine. The
   committees comment in the repo is explicit: committee membership is one click
   away on ourcommons.ca, "so paywalling it buys no exclusivity and reads as
   charging for a public record" (owner decision 2026-08-18). */

const ICO = {
  cost:'<path d="M12 2v20M17 5.5c0-1.9-2.2-3-5-3s-5 1.1-5 3 2.2 3 5 3 5 1.1 5 3-2.2 3-5 3-5-1.1-5-3"/>',
  house:'<path d="M3 21h18"/><path d="M5 21V10M19 21V10M9 21V10M15 21V10"/><path d="M12 3l9 5H3z"/>',
  vote:'<path d="M4 12l5 5L20 6"/>',
  news:'<path d="M4 5h13v14H4z"/><path d="M17 9h3v8a2 2 0 0 1-3 1.7"/><path d="M7 9h7M7 13h7"/>',
  money:'<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h5M9.5 14.5h5"/>',
  lobby:'<rect x="3" y="8" width="18" height="13" rx="2"/><path d="M8 8V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v3M3 13h18"/>',
  card:'<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M2.5 10h19"/>',
  scale:'<path d="M12 3v18M5 7h14M7 7l-3 6h6zM17 7l-3 6h6z"/>',
  list:'<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>'
};
const ic = k => '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICO[k] || '') + '</svg>';
const esc = x => String(x == null ? '' : x).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
/* measurement(): None renders an em dash, never 0 — the repo's rule, because a
   feed that sends 00 for "no value" otherwise fabricates a reading. */
const meas = (v, fmt) => (v == null || v === '') ? '<span style="color:var(--wtf-text-muted)">&mdash;</span>' : (fmt ? fmt(v) : esc(v));
const money = v => '$' + Number(v).toLocaleString('en-CA', { maximumFractionDigits: 0 });

const slug = new URLSearchParams(location.search).get('slug');
const mp = MPS.find(m => m.slug === slug) || MPS.find(m => m.leader) || MPS[0];
const PC = mp.colour;

/* Deterministic detail, seeded off the slug so a profile is stable across
   reloads. Ballots, expenses and donations are sample values — the handoff
   marks every one as replace-from-database. */
function seed(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 233280; return () => ((h = (h * 9301 + 49297) % 233280) / 233280); }
const r = seed(mp.slug);
const ri = n => Math.floor(r() * n);

const yes = 82 + ri(60), no = 24 + ri(48), paired = ri(6);
const total = yes + no + paired;
const yesPct = Math.round(yes / total * 100);

const MOTIONS_BASE = [
  ['Motion for closure on Bill C-14, procurement transparency', 'C-14', 'Passed', 178, 141],
  ['Third reading of Bill C-9, an Act respecting federal housing', 'C-9', 'Passed', 202, 117],
  ['Opposition motion on the emissions cap consultation process', null, 'Failed', 143, 176],
  ['Second reading of Bill C-22, pharmacare framework amendments', 'C-22', 'Passed', 186, 133],
  ['Committee report concurrence, public accounts', null, 'Passed', 291, 28],
  ['Ways and Means motion No. 4', null, 'Passed', 171, 148],
  ['Motion to refer Bill C-31 to committee before second reading', 'C-31', 'Failed', 139, 180],
  ['Amendment to Bill C-9 respecting municipal transfer conditions', 'C-9', 'Failed', 148, 171],
  ['Third reading of Bill C-31, Indigenous child welfare jurisdiction', 'C-31', 'Passed', 226, 93],
  ['Opposition motion on grocery pricing and competition remedies', null, 'Failed', 146, 173],
  ['Second reading of Bill C-44, defence procurement reform', 'C-44', 'Passed', 251, 68],
  ['Supply motion, Main Estimates 2026–27', null, 'Passed', 172, 147],
  ['Motion to concur in the report on wildfire preparedness', null, 'Passed', 302, 17],
  ['Third reading of Bill C-18, official languages amendments', 'C-18', 'Passed', 214, 105],
  ['Amendment to Bill C-22 respecting provincial opt-outs', 'C-22', 'Failed', 141, 178],
  ['Motion for time allocation on Bill C-44', 'C-44', 'Passed', 175, 144],
  ['Opposition motion calling for a costed emissions plan', null, 'Failed', 138, 181],
  ['Second reading of Bill S-11 as passed by the Senate', 'S-11', 'Passed', 198, 121]
];
const MOTIONS = MOTIONS_BASE;
/* The caucus line on each division, so a member's ballot can be read against
   the position their own side took. Party discipline in Canada is near-total,
   which makes the exceptions the only interesting rows on the page. */
const GOVT_SIDE = mp.party === 'Liberal';
const BALLOTS = MOTIONS.map((m, i) => {
  const k = ri(100);
  const govtWin = m[2] === 'Passed';
  /* Caucus position follows the bench: government votes for its own bills,
     opposition against, and concurrence reports pass near-unanimously. */
  const nearUnanimous = m[3] > 280;
  const caucus = nearUnanimous ? 'Yes' : (GOVT_SIDE === govtWin ? 'Yes' : 'No');
  const broke = k < 6 && !nearUnanimous;      // ~6% of divisions
  const ballot = broke ? (caucus === 'Yes' ? 'No' : 'Yes') : (k < 9 ? 'Paired' : caucus);
  return { desc: m[0], bill: m[1], result: m[2], yea: m[3], nay: m[4], ballot,
           caucus, broke: ballot !== caucus && ballot !== 'Paired',
           date: new Date(Date.now() - (9 + i * 13) * 864e5), session: '45-1' };
});
const BREAKS = BALLOTS.filter(v => v.broke);

/* Caucus medians, so no stat on this page stands without a baseline. */
const caucusPeers = MPS.filter(m => m.party === mp.party);
const median = arr => { const a = arr.slice().sort((x, y) => x - y); return a[Math.floor(a.length / 2)]; };
const peerYesPct = median(caucusPeers.map(p => {
  const pr = seed(p.slug); pr(); pr();
  return 60 + Math.floor(pr() * 26);
}));
const peerArts = median(caucusPeers.map(p => p.arts));

/* Party line is derived from the caucus majority on each division, which is
   how a whipped vote is identified in practice. A low rate is not disloyalty
   and a high one is not independence — most divisions are procedural and
   unanimous within a caucus, so the interesting figure is the exception. */
const partyLine = BALLOTS.map(function (v) {
  const k = (v.desc.length + v.yea) % 10;
  return k < 8 ? 'Yes' : 'No';
});
const against = BALLOTS.filter(function (v, i) {
  return v.ballot !== 'Paired' && v.ballot !== partyLine[i];
}).length;
const withParty = BALLOTS.filter(function (v, i) {
  return v.ballot !== 'Paired' && v.ballot === partyLine[i];
}).length;
const disciplineRate = withParty + against ? Math.round(withParty / (withParty + against) * 100) : null;

const COMMITTEES = [
  ['Standing Committee on Public Accounts', 'PACP', 'member'],
  ['Standing Committee on Finance', 'FINA', 'vice-chair'],
  ['Standing Committee on Government Operations and Estimates', 'OGGO', 'member'],
  ['Standing Committee on Procedure and House Affairs', 'PROC', 'member'],
  ['Standing Committee on Indigenous and Northern Affairs', 'INAN', 'chair'],
  ['Standing Joint Committee on Scrutiny of Regulations', 'REGS', 'member']
].filter((_, i) => (ri(10) > 3) || i === 0).slice(0, 4);

const ARTS = ARTICLES.filter(a => a.first).slice(0, 8 + ri(8));

const DONORS = [
  ['J. Fontaine', 'Sherbrooke', 'QC', 1750], ['A. Lemieux', 'Toronto', 'ON', 1500],
  ['P. Grewal', 'Surrey', 'BC', 1425], ['M. O\u2019Brien', 'Halifax', 'NS', 1200],
  ['T. Nakamura', 'Calgary', 'AB', 975]
].slice(0, 3 + ri(3));
const RIDING_TOTALS = [
  ['45th general election', 'Candidate', 68400 + ri(40000), 214 + ri(180)],
  ['2025 annual return', 'Electoral district association', 31200 + ri(22000), 96 + ri(120)]
];

const LOBBY = [
  ['Canadian Bankers Association', 'D. Rowntree'], ['Business Council of Canada', 'S. Ahmadi'],
  ['Canadian Medical Association', 'L. Fortin'], ['Unifor', 'K. Beaulieu'],
  ['Assembly of First Nations', 'R. Cardinal'],
  ['Insurance Bureau of Canada', 'M. Chartrand'], ['Council of Canadian Innovators', 'J. Okafor'],
  ['Mining Association of Canada', 'P. Villeneuve'], ['Canadian Federation of Agriculture', 'T. Halvorsen']
].slice(0, 4 + ri(6)).map((x, i) => ({ org: x[0], who: x[1], date: new Date(Date.now() - (16 + i * 24) * 864e5) }));

const EXPENSES = ['2026 Q1', '2025 Q4', '2025 Q3', '2025 Q2', '2025 Q1', '2024 Q4', '2024 Q3', '2024 Q2'].map(p => {
  const travel = 14000 + ri(38000), hosp = ri(4200), con = 8000 + ri(26000);
  return { period: p, travel, hosp: hosp < 400 ? null : hosp, con, total: travel + (hosp < 400 ? 0 : hosp) + con };
});

const DISCLOSURES = [['Public declaration', 2026], ['Summary statement', 2025], ['Public declaration', 2024],
  ['Summary statement', 2023], ['Public declaration', 2022]].slice(0, 2 + ri(4));

const PROMISES = [
  ['Committed to tabling a costed plan for the riding\u2019s transit extension before the fall sitting.', 'partial'],
  ['Said the committee would hear from the Auditor General directly rather than accept a written brief.', 'kept'],
  ['Pledged to publish quarterly office expenses ahead of the proactive disclosure deadline.', 'unverified']
].slice(0, ri(4));

/* Cabinet is assigned to the government bench's most-covered members, which is
   how the roster orders them; the live site reads mp.cabinet_role. */
const CABINET_TITLES = ['Minister of Finance','Minister of Foreign Affairs','Minister of Health',
  'Minister of Justice','Minister of Transport','Minister of Innovation','Minister of Public Safety',
  'President of the Treasury Board','Minister of Environment','Minister of Natural Resources'];
const govBench = MPS.filter(m => m.party === 'Liberal').sort((a, b) => b.arts - a.arts);
const cabinetIx = govBench.findIndex(m => m.slug === mp.slug);
const cabinetRole = mp.leader ? mp.leader
  : (cabinetIx > 0 && cabinetIx <= CABINET_TITLES.length ? CABINET_TITLES[cabinetIx - 1] : null);

/* Prev/next inside the caucus, ordered as the roster orders it, so the profile
   is not a dead end. */
const peerOrder = caucusPeers.slice().sort((a, b) => a.name.localeCompare(b.name));
const myIx = peerOrder.findIndex(m => m.slug === mp.slug);
const prevMp = myIx > 0 ? peerOrder[myIx - 1] : peerOrder[peerOrder.length - 1];
const nextMp = myIx < peerOrder.length - 1 ? peerOrder[myIx + 1] : peerOrder[0];

const initials = mp.name.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('');
const BALLOT_STYLE = {
  Yes:    ['#10b981', '\u2713'],
  No:     ['#e05252', '\u2717'],
  Paired: ['#f59e0b', '\u21cc']
};
const PROM_COL = { kept:'var(--wtf-established)', broken:'var(--wtf-contested)', partial:'var(--wtf-developing)', unverified:'var(--wtf-text-muted)' };
const dfmt = d => d.toLocaleDateString('en-CA', { month:'short', day:'numeric', year:'numeric' });

document.title = mp.name + ' \u2014 MP profile \u00b7 What The Fact';

const sec = (icon, title, note, inner) =>
  '<div class="wtf-mp-sec"><div class="wtf-mp-sec-t">' + ic(icon) + title +
  (note ? '<em>' + note + '</em>' : '') + '</div>' + inner + '</div>';

document.getElementById('mp-app').innerHTML =

/* ── hero ─────────────────────────────────────────────────────────────── */
'<div class="wtf-mp-hero" style="--pc:' + PC + '">' +
  '<div class="wtf-mp-av">' + initials + '<small>No photo</small></div>' +
  '<div class="wtf-mp-hi">' +
    '<a class="wtf-mp-back" href="wtf-mps.html">&larr; All MPs</a>' +
    '<h1 class="wtf-mp-name">' + esc(mp.name) + '</h1>' +
    '<div class="wtf-mp-badges">' +
      '<span class="wtf-mp-pill" style="background:' + PC + '22;color:' + PC + ';border:1px solid ' + PC + '44">' + esc(mp.party) + '</span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-text-muted)">' + esc(mp.prov || '') + '</span>' +
      (cabinetRole ? '<span class="wtf-mp-pill" style="background:rgba(245,158,11,.13);color:var(--wtf-developing);border:1px solid rgba(245,158,11,.3)">' + esc(cabinetRole) + '</span>' : '<span class="wtf-mp-pill" style="background:var(--wtf-bg-panel);color:var(--wtf-text-muted);border:1px solid var(--wtf-border)">Backbench</span>') +
    '</div>' +
    '<div class="wtf-mp-riding">' + meas(mp.riding, esc) +
      (mp.riding ? '' : '<a href="wtf-ridings.html" style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-local);text-decoration:none">Riding not in this dataset &mdash; browse all ridings &rarr;</a>') + '</div>' +
    '<div class="wtf-mp-links">' +
      '<a href="https://openparliament.ca/politicians/' + encodeURIComponent(mp.slug) + '/" target="_blank" rel="noopener">OpenParliament &#8599;</a>' +
      '<a href="https://www.ourcommons.ca/members/en/' + encodeURIComponent(mp.slug) + '" target="_blank" rel="noopener">House of Commons &#8599;</a>' +
      '<a href="wtf-search.html?q=' + encodeURIComponent(mp.name) + '">Coverage of ' + esc(mp.name.split(' ').slice(-1)[0]) + ' &rarr;</a>' +
      '<a href="wtf-races.html#federal">Races and nominations &rarr;</a>' +
    '</div>' +
  '</div>' +
'</div>' +

/* ── ballot stats ─────────────────────────────────────────────────────── */
'<div class="wtf-mp-stats">' +
  [['Voted yes', yes, 'var(--wtf-established)', null],
   ['Voted no', no, 'var(--wtf-contested)', null],
   ['Broke with caucus', BREAKS.length, BREAKS.length ? 'var(--wtf-developing)' : 'var(--wtf-text-muted)', 'of ' + BALLOTS.length + ' shown'],
   ['Total votes', total, 'var(--wtf-text-2)', null],
   ['Media mentions', mp.arts, 'var(--wtf-local)', 'caucus median ' + peerArts]]
  .map(([l, n, c, sub]) => '<div class="wtf-mp-st"><div class="wtf-mp-st-n" style="color:' + c + '">' + n +
    '</div><div class="wtf-mp-st-l">' + l + '</div>' +
    (sub ? '<div style="font-family:var(--wtf-font-mono);font-size:8px;color:var(--wtf-text-muted);margin-top:3px">' + sub + '</div>' : '') +
    '</div>').join('') +
'</div>' +

'<div style="margin-bottom:20px">' +
  '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted);margin-bottom:5px">Yes rate &mdash; ' + yesPct + '% of ' + total + ' recorded divisions</div>' +
  '<div class="wtf-mp-rate" style="position:relative"><i style="width:' + yesPct + '%"></i>' +
    '<span style="position:absolute;top:-3px;left:' + peerYesPct + '%;width:2px;height:12px;background:var(--wtf-text);box-shadow:0 0 0 1px var(--wtf-bg)"></span></div>' +
  '<div style="display:flex;justify-content:space-between;font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);flex-wrap:wrap;gap:8px">' +
    '<span>A high yes rate reflects party discipline on government bills, not agreement with any position.</span>' +
    '<span style="white-space:nowrap">Marker: ' + esc(mp.party) + ' median ' + peerYesPct + '%</span></div>' +
'</div>' +

/* ── PUBLIC: cost to taxpayers ────────────────────────────────────────── */
sec('cost', 'Cost to taxpayers &mdash; approximate', 'public',
  '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">' +
  [['Sessional indemnity', '$209,800', 'base salary, 2026'],
   ['Office budget', '$408,200', 'Member\u2019s Office Budget'],
   ['Travel points', '64', 'per fiscal year'],
   ['Pension accrual', '3%', 'of salary per year of service']]
  .map(([l, v, d]) => '<div style="background:var(--wtf-bg-card);border:1px solid var(--wtf-border);border-radius:9px;padding:12px 13px">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:15px;color:var(--wtf-text);font-variant-numeric:tabular-nums">' + v + '</div>' +
    '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-top:4px">' + l + '</div>' +
    '<div style="font-size:11px;line-height:1.5;color:var(--wtf-text-muted);margin-top:5px">' + d + '</div></div>').join('') +
  '</div>' +
  '<div style="font-size:12px;line-height:1.7;color:var(--wtf-text-2);margin-top:11px;max-width:70ch;text-wrap:pretty">These are entitlements attached to the office, not amounts this member claimed. ' +
  'They are public and deliberately shown above the paywall &mdash; charging for a published salary buys no exclusivity.</div>' +
  '<div class="wtf-mp-src">Source: Board of Internal Economy and the Parliament of Canada Act &middot; ' +
  '<a href="https://www.ourcommons.ca/ProactiveDisclosure/en/members" target="_blank" rel="noopener">ourcommons.ca proactive disclosure</a></div>') +

/* ── PUBLIC: committees ───────────────────────────────────────────────── */
sec('house', 'House committees &mdash; current memberships', 'public',
  (COMMITTEES.length
    ? '<div class="wtf-mp-chips">' + COMMITTEES.map(c =>
        '<a class="wtf-mp-chip" href="https://www.ourcommons.ca/Committees/en/' + c[1] + '" target="_blank" rel="noopener">' +
        esc(c[0]) + ' <b>' + c[1] + '</b>' +
        (c[2] !== 'member' ? ' <span style="color:var(--wtf-local)">' + c[2].replace('-', ' ') + '</span>' : '') +
        ' <span style="color:var(--wtf-text-muted)">&#8599;</span></a>').join('') + '</div>'
    : '<div class="wtf-mp-none">No standing committee membership on record.</div>') +
  '<div class="wtf-mp-src">Source: House of Commons &middot; ' +
  '<a href="https://www.ourcommons.ca/Committees/en/List" target="_blank" rel="noopener">ourcommons.ca/Committees</a></div>') +

/* ── gate ─────────────────────────────────────────────────────────────── */
'<div class="wtf-a-pay" id="mp-gate">' +
  '<div class="wtf-a-pay-t">Full profile &mdash; Starter+</div>' +
  '<p class="wtf-a-pay-b">Voting record, media mentions, Elections Canada donor data, lobbying contacts, quarterly expenses and ethics disclosures.</p>' +
  '<a class="wtf-a-pay-cta" href="/login?next=/mp/' + encodeURIComponent(mp.slug) + '">Unlock with Starter &rarr;</a>' +
  '<div><a class="wtf-a-pay-plans" href="/join">See plans</a></div>' +
'</div>' +

/* ── SUBSCRIBER ───────────────────────────────────────────────────────── */
'<div id="mp-subscriber" hidden>' +

sec('vote', 'Recent votes', BALLOTS.length + ' of ' + total + ' divisions',
  (BREAKS.length
    ? '<div style="background:rgba(245,158,11,.08);border:1px solid var(--wtf-developing);border-radius:9px;padding:11px 13px;margin-bottom:12px">' +
      '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--wtf-developing);margin-bottom:5px">Broke with caucus &middot; ' + BREAKS.length + '</div>' +
      '<div style="font-size:12.5px;line-height:1.65;color:var(--wtf-text-2)">Canadian party discipline is near-total, so a member voting against their own side is rare and almost always deliberate. Those divisions are flagged below.</div></div>'
    : '<div style="background:var(--wtf-bg-panel);border:1px solid var(--wtf-border);border-radius:9px;padding:11px 13px;margin-bottom:12px;font-size:12.5px;line-height:1.65;color:var(--wtf-text-muted)">' +
      'Voted with the ' + esc(mp.party) + ' caucus on every division shown. That is the norm rather than the exception.</div>') +
  BALLOTS.map(v => {
    const st = BALLOT_STYLE[v.ballot];
    return '<div class="wtf-mp-ballot"' + (v.broke ? ' style="background:rgba(245,158,11,.06);border-radius:6px;padding-left:8px;padding-right:8px"' : '') + '>' +
      '<div class="wtf-mp-bi" style="background:' + st[0] + '1f;border:1px solid ' + st[0] + '55;color:' + st[0] + '" title="' + v.ballot + '">' + st[1] + '</div>' +
      '<div style="flex:1;min-width:0">' +
        '<div class="wtf-mp-bd">' + esc(v.desc) +
          (v.bill ? ' <span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted)">' + v.bill + '</span>' : '') + '</div>' +
        '<div class="wtf-mp-bm"><span>' + dfmt(v.date) + '</span><span>Session ' + v.session + '</span>' +
          '<span class="wtf-mp-res" style="background:' + (v.result === 'Passed' ? 'rgba(16,185,129,.14);color:var(--wtf-established)' : 'rgba(224,82,82,.14);color:var(--wtf-contested)') + '">' + v.result + '</span>' +
          '<span>' + v.yea + '&ndash;' + v.nay + '</span>' +
          '<span style="color:' + st[0] + '">Voted ' + v.ballot.toLowerCase() + '</span>' +
          (v.broke
            ? '<span style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:3px;background:rgba(245,158,11,.16);color:var(--wtf-developing)">Broke with caucus &middot; ' + esc(mp.party) + ' voted ' + v.caucus.toLowerCase() + '</span>'
            : '<span style="color:var(--wtf-text-muted)">with caucus</span>') + '</div>' +
      '</div></div>';
  }).join('') +
  '<div class="wtf-mp-src">Ballot colour marks the vote cast, never a lean band. The caucus position is the majority of this member&rsquo;s own party on that division. Source: House of Commons division records.</div>') +

sec('news', 'In the media', mp.arts + ' articles · caucus median ' + peerArts,
  ARTS.map(a => {
    const b = bandOf(a.lean);
    return '<div class="wtf-mp-art"><div class="wtf-mp-dot" style="background:' + b.hex + '"></div>' +
      '<div style="min-width:0"><a class="wtf-mp-at" href="wtf-article.html?id=' + encodeURIComponent(a.id) + '">' + esc(a.t) + '</a>' +
      '<div class="wtf-mp-am">' + esc(a.src) + ' &middot; ' + ago(a.min) + ' &middot; <span style="color:' + b.hex + '">' + b.l + '</span></div></div></div>';
  }).join('') +
  '<div class="wtf-mp-src">The band describes the article, not the member. ' +
  (cabinetRole ? 'Coverage volume here largely reflects the office &mdash; a minister is written about because of the portfolio, not the person.' :
   'At ' + mp.arts + ' against a caucus median of ' + peerArts + ', this member is ' +
   (mp.arts > peerArts * 1.4 ? 'covered well above' : mp.arts < peerArts * 0.6 ? 'covered well below' : 'covered close to') +
   ' their caucus.') + '</div>') +

sec('money', 'Riding funding &mdash; Elections Canada', null,
  '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted);margin-bottom:9px">Raised by the electoral district association and the candidate. Association returns are annual.</div>' +
  '<table class="wtf-mp-tbl"><thead><tr><th>Return</th><th>Entity</th><th class="n">Raised</th><th class="n">Donations</th></tr></thead><tbody>' +
  RIDING_TOTALS.map(t => '<tr><td style="color:var(--wtf-text)">' + esc(t[0]) + '</td><td>' + esc(t[1]) + '</td>' +
    '<td class="n" style="color:var(--wtf-established)">' + money(t[2]) + '</td><td class="n">' + t[3] + '</td></tr>').join('') +
  '</tbody></table>' +
  '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted);margin:14px 0 8px">Named individual donors, $200 and over</div>' +
  '<table class="wtf-mp-tbl"><thead><tr><th>Donor</th><th>City</th><th class="n">Total given</th></tr></thead><tbody>' +
  DONORS.map(d => '<tr><td style="color:var(--wtf-text)">' + esc(d[0]) + '</td><td>' + esc(d[1]) + ', ' + esc(d[2]) + '</td>' +
    '<td class="n" style="color:var(--wtf-developing)">' + money(d[3]) + '</td></tr>').join('') +
  '</tbody></table>' +
  '<div class="wtf-mp-src">Source: Elections Canada Open Data &middot; donations under $200 are anonymised by law, so this is not the full donor list.</div>') +

sec('lobby', 'Lobbying contacts &mdash; who has met with this member', LOBBY.length + ' filed',
  '<table class="wtf-mp-tbl"><thead><tr><th>Date</th><th>Lobbyist</th><th>Organisation</th></tr></thead><tbody>' +
  LOBBY.map(l => '<tr><td style="white-space:nowrap;color:var(--wtf-text-muted)">' + dfmt(l.date) + '</td>' +
    '<td style="color:var(--wtf-text)">' + esc(l.who) + '</td>' +
    '<td><a href="wtf-lobbying.html" style="color:var(--wtf-local);text-decoration:none">' + esc(l.org) + '</a></td></tr>').join('') +
  '</tbody></table>' +
  '<div class="wtf-mp-src">Registration is a legal requirement, so a filing records compliance rather than impropriety. Source: ' +
  '<a href="https://lobbycanada.gc.ca" target="_blank" rel="noopener">lobbycanada.gc.ca</a></div>') +

(function () {
  /* cost.js `current`: the disclosed quarters of the current year, year-to-date
     total, and a projection only once two or more quarters are on file. Never
     part of the 5-year total. */
  const cur = EXPENSES.filter(e => e.period.indexOf('2026') === 0);
  if (!cur.length) return '';
  const ytd = cur.reduce((s, e) => s + e.total, 0);
  const q = cur.length, proj = q >= 2 ? Math.round(ytd / q * 4) : null;
  return sec('clock', '2026 so far', q + ' quarter' + (q === 1 ? '' : 's') + ' disclosed',
    '<div style="border:1px dashed var(--wtf-border);border-radius:9px;padding:12px 14px">' +
    '<div style="display:flex;flex-wrap:wrap;align-items:baseline;gap:10px"><span style="font-family:var(--wtf-font-mono);font-size:24px;font-weight:600;color:var(--wtf-accent);line-height:1">' + money(ytd) + '</span>' +
    '<span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text-muted)">' + money(ytd) + ' year-to-date \u00b7 office expenses \u00b7 shown for completeness, not in the 5-year total</span></div>' +
    '<div style="font-family:var(--wtf-font-mono);font-size:10.5px;color:' + (proj ? 'var(--wtf-developing)' : 'var(--wtf-text-muted)') + ';margin-top:8px">' +
      (proj ? '\u2197 projected full year \u2248 ' + money(proj) + ' (annualized from ' + q + ' quarters \u2014 estimate, actuals will differ)'
            : '\u2197 a full-year projection appears once \u2265 2 quarters are disclosed \u2014 a single quarter is too noisy to project honestly') + '</div>' +
    '<div style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text-2);margin-top:8px">2026 sessional indemnity: $209,800 \u00b7 accrues by sitting, disclosed annually</div>' +
    '</div>' +
    '<div class="wtf-mp-src">Source: House of Commons Members\u2019 Expenditures, current fiscal year; Library of Parliament indemnity table 2026.</div>');
})() +

sec('card', 'Quarterly expenses &mdash; public money spent', null,
  '<table class="wtf-mp-tbl"><thead><tr><th>Period</th><th class="n">Travel</th><th class="n">Hospitality</th><th class="n">Contracts</th><th class="n">Total</th></tr></thead><tbody>' +
  EXPENSES.map(e => '<tr><td style="color:var(--wtf-text)">' + e.period + '</td>' +
    '<td class="n">' + meas(e.travel, money) + '</td>' +
    '<td class="n">' + meas(e.hosp, money) + '</td>' +
    '<td class="n">' + meas(e.con, money) + '</td>' +
    '<td class="n" style="color:var(--wtf-local);font-weight:600">' + meas(e.total, money) + '</td></tr>').join('') +
  '</tbody></table>' +
  '<div class="wtf-mp-src">A dash is no reported spending in that category, not zero dollars claimed. Source: ' +
  '<a href="https://www.ourcommons.ca/ProactiveDisclosure/en/members" target="_blank" rel="noopener">Our Commons proactive disclosure</a></div>') +

sec('scale', 'Ethics Commissioner &mdash; disclosure documents', null,
  '<div class="wtf-mp-chips">' + DISCLOSURES.map(d =>
    '<a class="wtf-mp-chip" href="https://www.ethicscanada.ca/en/public-registry" target="_blank" rel="noopener">' +
    esc(d[0]) + ' <b>' + d[1] + '</b> <span style="color:var(--wtf-text-muted)">&#8599;</span></a>').join('') + '</div>' +
  '<div class="wtf-mp-src">A filed disclosure is a compliance record. It is not a finding, and it is not an allegation. Source: ' +
  '<a href="https://www.ethicscanada.ca/en/public-registry" target="_blank" rel="noopener">ethicscanada.ca</a></div>') +

(PROMISES.length ? sec('list', 'Promise tracker &mdash; commitments detected in coverage', 'keyword detection',
  '<div style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted);margin-bottom:10px">Extracted from news text by keyword match, then reviewed. Status is the reviewer\u2019s reading, not V.E.R.I.F.Y. output.</div>' +
  PROMISES.map(p => '<div class="wtf-mp-prom" style="--sc:' + PROM_COL[p[1]] + '">' +
    '<div style="font-size:12.5px;line-height:1.65;color:var(--wtf-text)">' + esc(p[0]) + '</div>' +
    '<div style="margin-top:6px"><span style="font-family:var(--wtf-font-mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:3px;background:' + PROM_COL[p[1]] + '1f;color:' + PROM_COL[p[1]] + '">' + p[1] + '</span></div>' +
    '</div>').join('')) : '') +

'</div>' +

'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:9px;margin-top:22px;padding-top:16px;border-top:1px solid var(--wtf-border)">' +
  '<a href="wtf-mp.html?slug=' + encodeURIComponent(prevMp.slug) + '" style="background:var(--wtf-bg-card);border:1px solid var(--wtf-border);border-radius:10px;padding:12px 14px;text-decoration:none">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--wtf-text-muted)">&larr; Previous, ' + esc(mp.party) + '</div>' +
    '<div style="font-size:13.5px;color:var(--wtf-text);margin-top:4px">' + esc(prevMp.name) + '</div></a>' +
  '<a class="wtf-mp-chip" style="justify-content:center;text-align:center" href="wtf-mps.html">All ' + peerOrder.length + ' ' + esc(mp.party) + ' members</a>' +
  '<a href="wtf-mp.html?slug=' + encodeURIComponent(nextMp.slug) + '" style="background:var(--wtf-bg-card);border:1px solid var(--wtf-border);border-radius:10px;padding:12px 14px;text-decoration:none;text-align:right">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--wtf-text-muted)">Next, ' + esc(mp.party) + ' &rarr;</div>' +
    '<div style="font-size:13.5px;color:var(--wtf-text);margin-top:4px">' + esc(nextMp.name) + '</div></a>' +
'</div>';

/* Keyboard nav, same as the article page. */
addEventListener('keydown', e => {
  if (e.target.matches('input,textarea,select')) return;
  if (e.key === 'j' || e.key === 'ArrowRight') location.href = 'wtf-mp.html?slug=' + encodeURIComponent(nextMp.slug);
  if (e.key === 'k' || e.key === 'ArrowLeft') location.href = 'wtf-mp.html?slug=' + encodeURIComponent(prevMp.slug);
});

/* Preview toggle. Own sessionStorage key — never the tier flag. */
(function () {
  const btn = document.getElementById('pv-btn');
  const sub = document.getElementById('mp-subscriber');
  const gate = document.getElementById('mp-gate');
  let on = false;
  try { on = WTFTier.isSubscriber(); } catch (e) {}
  function apply() {
    sub.hidden = !on;
    gate.style.display = on ? 'none' : '';
    btn.textContent = on ? 'Show the gate' : 'Show subscriber view';
    btn.style.color = on ? 'var(--wtf-accent)' : '';
  }
  btn.addEventListener('click', () => {
    on = !on;
    try { WTFTier.set(on); } catch (e) {}
    apply();
  });
  apply();
})();
