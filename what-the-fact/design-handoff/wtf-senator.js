/* Senator profile. Mirrors consumer/templates/senator.html.

   Deliberately NOT a copy of the MP page: the Senate has its own vocabulary and
   the template reflects it — ballots are yea / nay / abstention rather than
   Yes / No / Paired, membership is a caucus group rather than a party, seats
   are appointed rather than won, and every senator has a mandatory retirement
   date at 75 that the House has no equivalent of. */

const ICO = {
  cost:'<path d="M12 2v20M17 5.5c0-1.9-2.2-3-5-3s-5 1.1-5 3 2.2 3 5 3 5 1.1 5 3-2.2 3-5 3-5-1.1-5-3"/>',
  house:'<path d="M3 21h18"/><path d="M5 21V10M19 21V10M9 21V10M15 21V10"/><path d="M12 3l9 5H3z"/>',
  vote:'<path d="M4 12l5 5L20 6"/>',
  phone:'<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2.2 2A16 16 0 0 1 3 6.2 2 2 0 0 1 5 4z"/>',
  list:'<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3.5 2"/>'
};
const ic = k => '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICO[k] || '') + '</svg>';
const esc = x => String(x == null ? '' : x).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const meas = (v, fmt) => (v == null || v === '') ? '<span style="color:var(--wtf-text-muted)">&mdash;</span>' : (fmt ? fmt(v) : esc(v));
const money = v => '$' + Number(v).toLocaleString('en-CA', { maximumFractionDigits: 0 });
const dfmt = d => d.toLocaleDateString('en-CA', { month:'long', day:'numeric', year:'numeric' });
const dshort = d => d.toLocaleDateString('en-CA', { month:'short', day:'numeric', year:'numeric' });

const slug = new URLSearchParams(location.search).get('slug');
const sen = SENATORS.find(s => s.slug === slug) || SENATORS[0];
const CC = sen.colour;

function seed(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 233280; return () => ((h = (h * 9301 + 49297) % 233280) / 233280); }
const r = seed(sen.slug);
const ri = n => Math.floor(r() * n);

/* Appointment maths is real: mandatory retirement is the 75th birthday, so age
   and years remaining are derived from one date rather than stated separately
   and allowed to disagree. */
const age = 52 + ri(23);
const dob = new Date(Date.UTC(2026 - age, ri(12), 1 + ri(27)));
const retire = new Date(Date.UTC(dob.getUTCFullYear() + 75, dob.getUTCMonth(), dob.getUTCDate()));
const yearsLeft = Math.max(0, Math.round((retire - Date.now()) / 3.15576e10));
const appointed = new Date(Date.UTC(2026 - (1 + ri(17)), ri(12), 1 + ri(27)));
const yearsIn = Math.max(0, Math.round((Date.now() - appointed) / 3.15576e10));
const PMS = [['Justin Trudeau', 2015, 2025], ['Mark Carney', 2025, 2027], ['Stephen Harper', 2006, 2015]];
const appointedBy = (PMS.find(p => appointed.getUTCFullYear() >= p[1] && appointed.getUTCFullYear() < p[2]) || PMS[0])[0];

const COMMITTEES = [
  ['Standing Senate Committee on Legal and Constitutional Affairs', 'LCJC', 'member'],
  ['Standing Senate Committee on National Finance', 'NFFN', 'chair'],
  ['Standing Senate Committee on Indigenous Peoples', 'APPA', 'member'],
  ['Standing Senate Committee on Social Affairs, Science and Technology', 'SOCI', 'deputy_chair']
].slice(0, 1 + ri(4));

const MOTIONS = [
  ['Third reading of Bill C-9, an Act respecting federal housing', 'C-9', 'Adopted', 58, 21],
  ['Report of the Standing Senate Committee on National Finance', null, 'Adopted', 61, 14],
  ['Second reading of Bill C-22, pharmacare framework amendments', 'C-22', 'Adopted', 54, 26],
  ['Amendment to Bill C-14 respecting procurement disclosure', 'C-14', 'Negatived', 31, 47],
  ['Motion to adjourn debate on Bill S-11', 'S-11', 'Adopted', 49, 22],
  ['Third reading of Bill S-4, an Act to amend the Criminal Code', 'S-4', 'Adopted', 66, 9]
];
const BALLOTS = MOTIONS.map((m, i) => {
  const k = ri(10);
  return { title: m[0], bill: m[1], result: m[2], yea: m[3], nay: m[4],
           ballot: k < 6 ? 'yea' : k < 9 ? 'nay' : 'abstention',
           date: new Date(Date.now() - (11 + i * 17) * 864e5) };
});
const BALLOT_STYLE = {
  yea:        ['#10b981', '\u2713', 'Voted yea'],
  nay:        ['#e05252', '\u2717', 'Voted nay'],
  abstention: ['#f59e0b', '\u21cc', 'Abstained']
};

const BIOS = [
  'Called to the Senate after a career in provincial public service, with earlier work in municipal administration and community legal aid.',
  'A former journalist and broadcaster who covered provincial politics before appointment, and has sat on committees dealing with communications policy since.',
  'Practised law for two decades before appointment, principally in constitutional and Indigenous rights litigation.',
  'Worked in health administration and as a hospital board chair, and has focused on federal transfer arrangements since being called.'
];
const bio = BIOS[ri(BIOS.length)];

const initials = sen.name.split(' ').filter(Boolean).map(w => w[0]).slice(0, 2).join('');
const caucusLabel = CAUCUS_LAB[sen.caucus] || sen.caucus;

document.title = sen.name + ' \u2014 Senator profile \u00b7 What The Fact';

const sec = (icon, title, note, inner) =>
  '<div class="wtf-mp-sec"><div class="wtf-mp-sec-t">' + ic(icon) + title +
  (note ? '<em>' + note + '</em>' : '') + '</div>' + inner + '</div>';

document.getElementById('sen-app').innerHTML =

'<div class="wtf-mp-hero" style="--pc:' + CC + '">' +
  '<div class="wtf-mp-av">' + initials + '<small>No photo</small></div>' +
  '<div class="wtf-mp-hi">' +
    '<a class="wtf-mp-back" href="wtf-mps.html">&larr; Senate</a>' +
    '<h1 class="wtf-mp-name">' + esc(sen.name) + '</h1>' +
    '<div class="wtf-mp-badges">' +
      '<span class="wtf-mp-pill" style="background:' + CC + '22;color:' + CC + ';border:1px solid ' + CC + '44">' + esc(caucusLabel) + '</span>' +
      '<span style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-text-muted)">' + esc(PROV_FULL[sen.prov] || sen.prov) + '</span>' +
    '</div>' +
    '<div class="wtf-mp-riding">Appointed ' + dfmt(appointed) + ' &middot; ' + yearsIn + (yearsIn === 1 ? ' year' : ' years') + ' in the Senate<br>' +
      '<span style="font-size:13px;color:var(--wtf-text-muted)">On the advice of Prime Minister ' + esc(appointedBy) + '</span></div>' +
    '<div class="wtf-mp-links">' +
      '<a href="https://sencanada.ca/en/senators/" target="_blank" rel="noopener">Senate of Canada profile &#8599;</a>' +
      '<a href="wtf-search.html?q=' + encodeURIComponent(sen.name) + '">Coverage of ' + esc(sen.name.split(' ').slice(-1)[0]) + ' &rarr;</a>' +
    '</div>' +
  '</div>' +
'</div>' +

/* Appointment facts are public and derived from one birth date, so age,
   retirement and years remaining cannot contradict each other. */
'<div class="wtf-sen-stats">' +
  [[age, 'years old'], [dfmt(retire), 'mandatory retirement'],
   [yearsLeft + 'y', 'until retirement'], ['75', 'retirement age']]
  .map(([v, l]) => '<div class="wtf-sen-stat"><b>' + v + '</b><span>' + l + '</span></div>').join('') +
'</div>' +

sec('cost', 'Cost to taxpayers &mdash; approximate', 'public',
  '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">' +
  [['Sessional indemnity', '$185,300', 'base salary, 2026'],
   ['Office budget', '$236,000', 'Senators\u2019 research and office'],
   ['Travel points', '64', 'per fiscal year'],
   ['Years remaining', yearsLeft + 'y', 'to mandatory retirement']]
  .map(([l, v, d]) => '<div style="background:var(--wtf-bg-card);border:1px solid var(--wtf-border);border-radius:9px;padding:12px 13px">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:15px;color:var(--wtf-text);font-variant-numeric:tabular-nums">' + v + '</div>' +
    '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-top:4px">' + l + '</div>' +
    '<div style="font-size:11px;line-height:1.5;color:var(--wtf-text-muted);margin-top:5px">' + d + '</div></div>').join('') +
  '</div>' +
  '<div style="font-size:12px;line-height:1.7;color:var(--wtf-text-2);margin-top:11px;max-width:70ch;text-wrap:pretty">Entitlements attached to the office, not amounts claimed. ' +
  'Because a Senate seat runs to 75 rather than to the next election, the years-remaining figure is the one number with no House equivalent.</div>' +
  (function () {
    /* Per-senator cost, same shape as the MP panel: five complete years, then
       the current year as disclosed. Sample values seeded off the slug. */
    const yrs = [2021, 2022, 2023, 2024, 2025].map((y, i) => { const ind = [164800, 169600, 174900, 181100, 185300][i]; const off = 120000 + ri(90000); return { y, ind, off, total: ind + off }; });
    const five = yrs.reduce((n, y) => n + y.total, 0);
    const q1 = Math.round(185300 / 4 + 28000 + ri(22000));
    return '<div style="margin-top:14px"><div style="font-family:var(--wtf-font-mono);font-size:9.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-bottom:8px">Five complete years \u00b7 2021\u20132025</div>' +
      '<div style="display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-bottom:8px"><span style="font-family:var(--wtf-font-mono);font-size:24px;font-weight:600;color:var(--wtf-accent);line-height:1">' + money(five) + '</span><span style="font-family:var(--wtf-font-mono);font-size:10.5px;color:var(--wtf-text-muted)">approximate 5-year cost to taxpayers \u00b7 indemnity + office</span></div>' +
      '<table class="wtf-mp-tbl"><thead><tr><th>Year</th><th class="n">Indemnity</th><th class="n">Office</th><th class="n">Total</th></tr></thead><tbody>' +
      yrs.map(y => '<tr><td style="color:var(--wtf-text)">' + y.y + '</td><td class="n">' + money(y.ind) + '</td><td class="n">' + money(y.off) + '</td><td class="n" style="color:var(--wtf-text)">' + money(y.total) + '</td></tr>').join('') +
      '<tr><td style="color:var(--wtf-developing)">2026 \u00b7 Q1 so far</td><td class="n">' + money(46325) + '</td><td class="n">' + money(q1 - 46325) + '</td><td class="n" style="color:var(--wtf-developing)">' + money(q1) + '</td></tr>' +
      '</tbody></table>' +
      '<div style="font-family:var(--wtf-font-mono);font-size:10px;color:var(--wtf-text-muted);margin-top:8px">2026 is one disclosed quarter, shown for completeness and not in the 5-year figure; a full-year projection appears once \u2265 2 quarters are on file.</div></div>';
  })() +
  '<div class="wtf-mp-src">Source: Senate Administrative Rules and the Parliament of Canada Act &middot; ' +
  '<a href="https://sencanada.ca/en/about/transparency/" target="_blank" rel="noopener">sencanada.ca transparency</a></div>') +

'<div class="wtf-a-pay" id="sen-gate">' +
  '<div class="wtf-a-pay-t">Full profile &mdash; Starter+</div>' +
  '<p class="wtf-a-pay-b">Contact information, committee memberships, full biography and Senate voting record.</p>' +
  '<a class="wtf-a-pay-cta" href="/login?next=/senator/' + encodeURIComponent(sen.slug) + '">Unlock with Starter &rarr;</a>' +
  '<div><a class="wtf-a-pay-plans" href="/join">See plans</a></div>' +
'</div>' +

'<div id="sen-subscriber" hidden>' +

sec('phone', 'Contact', null,
  '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px">' +
  [['Office', '613-555-' + (1000 + ri(8999)), 'tel'],
   ['Email', sen.slug.split('-').slice(1).join('.') + '@sen.parl.gc.ca', 'mail'],
   ['Chamber', 'Senate of Canada, Ottawa ON K1A 0A4', null]]
  .map(([l, v, kind]) => '<div style="background:var(--wtf-bg-card);border:1px solid var(--wtf-border);border-radius:9px;padding:11px 13px">' +
    '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--wtf-text-muted);margin-bottom:5px">' + l + '</div>' +
    '<div style="font-size:12.5px;color:var(--wtf-text);word-break:break-word">' +
      (kind === 'mail' ? '<a href="mailto:' + esc(v) + '" style="color:var(--wtf-accent);text-decoration:none">' + esc(v) + '</a>'
       : kind === 'tel' ? '<a href="tel:' + esc(v) + '" style="color:var(--wtf-text-2);text-decoration:none">' + esc(v) + '</a>'
       : esc(v)) + '</div></div>').join('') +
  '</div>') +

sec('house', 'Committee memberships', COMMITTEES.length + ' of 18 standing committees',
  '<div class="wtf-mp-chips">' + COMMITTEES.map(c => {
    const role = c[2] === 'chair' ? 'Chair' : c[2] === 'deputy_chair' ? 'Deputy chair' : null;
    return '<a class="wtf-mp-chip" href="https://sencanada.ca/en/committees/' + c[1] + '/" target="_blank" rel="noopener"' +
      (role ? ' style="border-color:' + CC + '55"' : '') + '>' +
      esc(c[0]) + ' <b>' + c[1] + '</b>' +
      (role ? ' <span style="color:' + CC + '">' + role + '</span>' : '') +
      ' <span style="color:var(--wtf-text-muted)">&#8599;</span></a>';
  }).join('') + '</div>' +
  '<div class="wtf-mp-src">Senate committees do the chamber\u2019s detailed legislative review, which is where most amendments to House bills originate. Source: ' +
  '<a href="https://sencanada.ca/en/committees/" target="_blank" rel="noopener">sencanada.ca/committees</a></div>') +

sec('vote', 'Recent Senate votes', BALLOTS.length + ' divisions',
  BALLOTS.map(v => {
    const st = BALLOT_STYLE[v.ballot];
    return '<div class="wtf-mp-ballot">' +
      '<div class="wtf-mp-bi" style="background:' + st[0] + '1f;border:1px solid ' + st[0] + '55;color:' + st[0] + '" title="' + st[2] + '">' + st[1] + '</div>' +
      '<div style="flex:1;min-width:0">' +
        '<div class="wtf-mp-bd">' + esc(v.title) +
          (v.bill ? ' <span style="font-family:var(--wtf-font-mono);font-size:9.5px;color:var(--wtf-text-muted)">' + v.bill + '</span>' : '') + '</div>' +
        '<div class="wtf-mp-bm"><span>' + dshort(v.date) + '</span>' +
          '<span class="wtf-mp-res" style="background:' + (v.result === 'Adopted' ? 'rgba(16,185,129,.14);color:var(--wtf-established)' : 'rgba(224,82,82,.14);color:var(--wtf-contested)') + '">' + v.result + '</span>' +
          '<span>' + v.yea + '&ndash;' + v.nay + '</span>' +
          '<span style="color:' + st[0] + '">' + st[2] + '</span></div>' +
      '</div></div>';
  }).join('') +
  '<div class="wtf-mp-src">Senate ballots are yea, nay or abstention &mdash; a distinct vocabulary from the House. Abstention is a recorded position, not an absence.</div>') +

sec('list', 'Biography', null,
  '<p style="font-family:var(--wtf-font-serif);font-size:15px;line-height:1.72;color:var(--wtf-text-2);margin:0;max-width:72ch;text-wrap:pretty">' + esc(bio) + '</p>') +

'</div>' +

sec('clock', 'About the Senate', null,
  '<p style="font-size:13px;line-height:1.78;color:var(--wtf-text-2);margin:0 0 11px;max-width:74ch;text-wrap:pretty">Senators are appointed by the Governor General on the advice of the Prime Minister and serve until age 75. ' +
  'The Senate reviews, amends and votes on legislation passed by the House of Commons. Because senators face no election, the chamber is designed to take positions the House cannot, ' +
  'which is why caucus groups here are looser than parties and cross a good deal more often.</p>' +
  '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
    '<a class="wtf-mp-chip" href="wtf-mps.html">&larr; Back to Parliament</a>' +
    '<a class="wtf-mp-chip" href="https://sencanada.ca" target="_blank" rel="noopener">Senate of Canada <span style="color:var(--wtf-text-muted)">&#8599;</span></a>' +
  '</div>');

(function () {
  const btn = document.getElementById('pv-btn');
  const sub = document.getElementById('sen-subscriber');
  const gate = document.getElementById('sen-gate');
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
