/* Cross-Watch: the entity join across registers.

   Findings, lobbying contacts, appointments and coverage all name entities and
   nothing connected them — four unlinked lists. This joins them on the name.

   The framing is load-bearing. A match is a fact about paperwork: two records
   exist bearing the same name. It is not a finding about a person, there is no
   score, and every row shows its source record so a reader checks the register
   rather than trusting this page. */

(function () {
'use strict';

const $ = function (id) { return document.getElementById(id); };
const esc = function (x) {
  return String(x == null ? '' : x).replace(/[&<>"]/g, function (c) {
    return ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c];
  });
};

/* Register → Watch series. The series is the collection that produced the
   record, which is how a claim here is traced back to a source. */
const REGISTERS = {
  finding:     { l:'Officer finding', series:'Gov Watch',    c:'var(--wtf-local)',      page:'wtf-officers.html' },
  ethics:      { l:'Ethics ruling',   series:'Legal Watch',  c:'var(--wtf-contested)',  page:'wtf-ethics.html' },
  lobbying:    { l:'Lobbying',        series:'Civic Watch',  c:'var(--wtf-aurora)',     page:'wtf-lobbying.html' },
  appointment: { l:'Appointment',     series:'Gov Watch',    c:'var(--wtf-established)',page:'wtf-gic.html' },
  vacancy:     { l:'Vacant post',     series:'Gov Watch',    c:'var(--wtf-developing)', page:'wtf-gic.html' },
  coverage:    { l:'News coverage',   series:'What The Fact', c:'var(--wtf-brand)',       page:'wtf-search.html' },
  competition: { l:'Competition Bureau item', series:'Legal Watch', c:'var(--wtf-aurora)', page:'wtf-claims.html' },
  market:      { l:'Federal contracts won \u00b7 listed', series:'Market Watch', c:'var(--wtf-developing)', page:'wtf-markets.html' }
};

/* The live site's six Watch products. Each register here belongs to one of
   them, which is what the badge row on every entity shows. Colours stay off
   the lean spectrum: no red/blue pairing that could read as left/right. */
const PRODUCTS = {
  'gov-watch':    { l:'Gov',        full:'Federal Procurement', sub:'Gov Watch',     c:'var(--wtf-local)' },
  'civic-watch':  { l:'Civic',      full:'Civic & Lobbying',    sub:'Civic Watch',   c:'var(--wtf-established)' },
  'legal-watch':  { l:'Legal',      full:'Legal & Rulings',     sub:'Legal Watch',   c:'var(--wtf-aurora)' },
  'market-watch': { l:'Market',     full:'Markets',             sub:'Market Watch',  c:'var(--wtf-developing)' },
  'wtf':          { l:'News',       full:'News Coverage',       sub:'What The Fact', c:'var(--wtf-brand)' },
  'parliament':   { l:'Parliament', full:'Parliament',          sub:'Parliament',    c:'var(--wtf-accent)' }
};
const REG_PRODUCT = { finding:'gov-watch', ethics:'legal-watch', lobbying:'civic-watch', appointment:'parliament', vacancy:'parliament', coverage:'wtf', competition:'legal-watch', market:'market-watch' };

const ETHICS_IDS = { ethics:1, 'int-on':1, 'eth-ab':1, 'eth-qc':1, boie:1 };
const officerOf = function (id) {
  return OFFICERS.filter(function (o) { return o.id === id; })[0] || {};
};

/* Build the index. Every appearance carries the register, the record, and a
   route to the page where the original can be read. */
const index = {};
/* One body, one entry. Register wordings differ — a finding says "Canada
   Border Services Agency" where coverage says "CBSA" — and splitting them
   would hide exactly the match this page is for. */
const ALIAS = {
  'CBSA':'Canada Border Services Agency',
  'Canada Revenue Agency':'Canada Revenue Agency',
  'Conservative Party of Canada':'Conservative Party of Canada',
  'New Democratic Party':'New Democratic Party',
  'Auditor General':'Auditor General of Canada',
  'Employment and Social Development Canada':'Employment and Social Development Canada'
};
function add(name, type, register, record, link) {
  if (!name) return;
  const key = (ALIAS[String(name).trim()] || String(name).trim());
  const e = index[key] || (index[key] = { name:key, type:type, apps:[] });
  if (type && e.type === 'unknown') e.type = type;
  e.apps.push({ register:register, record:record, link:link || REGISTERS[register].page });
}

/* Officer findings and ethics rulings. */
if (typeof FINDINGS !== 'undefined') {
  FINDINGS.forEach(function (f) {
    if (f.unnamed) return;                     /* never index an unnamed subject */
    const o = officerOf(f.officer);
    const reg = ETHICS_IDS[f.officer] ? 'ethics' : 'finding';
    const type = /party$/i.test(f.role || '') || /Party/.test(f.subject) ? 'party'
      : /department|agency|ministry|division|board|tribunal/i.test(f.role || '') ? 'institution'
      : /contract/i.test(f.role || '') ? 'contract'
      : /system-wide|government/i.test(f.role || '') ? 'institution' : 'person';
    add(f.subject, type, reg,
      f.year + ' \u00b7 ' + (o.short || f.officer) + ' \u2014 ' + f.ref,
      f.party ? 'wtf-parties.html?party=' + encodeURIComponent(f.party) : REGISTERS[reg].page);
  });
}

/* Vacant Governor-in-Council posts: the body, not a person, since the post is
   what is empty. */
if (typeof GIC_VACANCIES !== 'undefined') {
  GIC_VACANCIES.forEach(function (v) {
    add(v.body, 'institution', 'vacancy', 'Vacant since ' + v.vacantSince + ' \u2014 ' + v.post);
  });
}

/* Lobbying organisations. Registration is a legal requirement, so presence
   here is compliance and is labelled as such on the row. */
const LOBBY_ORGS = [
  ['Canadian Bankers Association', 412], ['Pharmaceutical Research', 368],
  ['Canadian Chamber of Commerce', 344], ['Canadian Association of Petroleum Producers', 331],
  ['Unifor', 287], ['Canadian Medical Association', 263], ['Business Council of Canada', 241],
  ['Assembly of First Nations', 218], ['Canadian Federation of Agriculture', 196],
  ['Insurance Bureau of Canada', 184], ['Council of Canadian Innovators', 171],
  ['Canadian Labour Congress', 158], ['Mining Association of Canada', 142],
  ['Canadian Cancer Society', 127], ['Railway Association of Canada', 114],
  ['Canadian Real Estate Association', 103]
];
LOBBY_ORGS.forEach(function (o) {
  add(o[0], 'organisation', 'lobbying', o[1] + ' registered communications on file');
});

/* Coverage: entities the corpus itself names, which is the join that makes
   this page a newsroom product rather than a registry mirror. */
if (typeof ARTICLES !== 'undefined' && typeof ENTITY_MAP !== 'undefined') {
  const stories = ARTICLES.filter(function (a) { return a.first; });
  ENTITY_MAP.forEach(function (row) {
    const re = row[0], name = row[1], type = row[2];
    const n = stories.filter(function (a) { return re.test(a.t + ' ' + (a.note || '')); }).length;
    if (n) add(name, type, 'coverage', n + ' stor' + (n === 1 ? 'y' : 'ies') + ' in the current window',
      'wtf-search.html?q=' + encodeURIComponent(name));
  });
}

/* Officers are entities too: an office that issues findings and is itself
   written about appears in two registers, which is exactly the kind of match
   this page exists to surface. */
if (typeof OFFICERS !== 'undefined' && typeof FINDINGS !== 'undefined') {
  OFFICERS.forEach(function (o) {
    const n = FINDINGS.filter(function (f) { return f.officer === o.id; }).length;
    if (n) add(o.name, 'institution', 'finding',
      n + ' finding' + (n === 1 ? '' : 's') + ' issued \u00b7 ' + (o.notIndependent ? 'not an independent officer' : 'officer of Parliament'),
      'wtf-officers.html');
  });
}

/* Public office holders recorded as lobbied. The registry names them, so they
   are a register appearance in their own right \u2014 and the MP profile pages
   carry the same contacts, so the two agree. */
const LOBBIED = [
  ['Chrystia Freeland', 'Canadian Bankers Association'],
  ['Michelle Rempel Garner', 'Canadian Association of Petroleum Producers'],
  ['Nathaniel Erskine-Smith', 'Canadian Real Estate Association'],
  ['Alexandre Boulerice', 'Unifor'],
  ['Ruby Sahota', 'Canadian Chamber of Commerce'],
  ['Pierre Paul-Hus', 'Business Council of Canada'],
  ['Elizabeth May', 'Canadian Cancer Society'],
  ['Randeep Sarai', 'Council of Canadian Innovators'],
  ['Yves Perron', 'Canadian Federation of Agriculture'],
  ['Heather McPherson', 'Assembly of First Nations'],
  ['Bill Morneau', 'Insurance Bureau of Canada'],
  ['Steve Clark', 'Canadian Real Estate Association']
];
LOBBIED.forEach(function (r) {
  add(r[0], 'person', 'lobbying', 'Recorded contact with ' + r[1],
    'wtf-lobbying.html');
});

/* Governor-in-Council appointees, and the bodies they were appointed to. */
const APPOINTED = [
  ['A. Chen', 'Federal Court'], ['M. Tremblay', 'CRTC'],
  ['S. Okonkwo', 'Bank of Canada'], ['J. Beaulieu', 'Canada Revenue Agency'],
  ['R. Sandhu', 'Immigration and Refugee Board'], ['K. Doucette', 'CBC/Radio-Canada'],
  ['L. Fortin', 'Canadian Human Rights Tribunal'], ['D. Moreau', 'Competition Tribunal']
];
APPOINTED.forEach(function (r) {
  add(r[0], 'person', 'appointment', 'Appointed to ' + r[1], 'wtf-gic.html');
  add(r[1], 'institution', 'appointment', 'Appointment made \u2014 ' + r[0], 'wtf-gic.html');
});

const COMPETITION = [
  ['Canadian Bankers Association', 'Bureau statement on retail banking fee transparency review', 'https://competition-bureau.canada.ca'],
  ['Canadian Real Estate Association', 'Consent agreement on listing-data access, 2024', 'https://competition-bureau.canada.ca'],
  ['Canadian Association of Petroleum Producers', 'Market study on retail fuel pricing \u2014 submissions', 'https://competition-bureau.canada.ca']
];
COMPETITION.forEach(function (r) { add(r[0], 'organisation', 'competition', r[1], r[2]); });
const MARKET = {
  'Canada Post': null,
  'CBC/Radio-Canada': null,
  'Canadian Bankers Association': null,
  'Railway Association of Canada': null
};
/* Listed companies that are also federal contractors \u2014 public money meeting the
   markets. Approximate and partial (CanadaBuys via Gov Watch); an upper bound
   where joint ventures are included. */
const LISTED = [
  ['Canadian National Railway', 'TSX', 'CNR', 41, 187400000, false],
  ['Telus', 'TSX', 'T', 27, 96200000, false],
  ['CGI Inc.', 'TSX', 'GIB.A', 118, 412900000, true],
  ['Bombardier', 'TSX', 'BBD.B', 9, 64300000, false]
];
LISTED.forEach(function (r) {
  add(r[0], 'organisation', 'market', 'Trades as ' + r[1] + ':' + r[2] + ' \u00b7 ' + r[3] + ' federal contract awards \u00b7 $' + r[4].toLocaleString('en-CA') + (r[5] ? ' (incl. joint ventures it leads \u2014 upper bound)' : ''), 'wtf-markets.html');
  add(r[0], 'organisation', 'finding', r[3] + ' CanadaBuys awards on record', 'wtf-chain.html');
});

/* Live: the route passes entities[] ({name, type, products[], mentions}) as
   window.__WTF_ENTITIES; when present it replaces the register join above. */
const INJECTED = (typeof WTFLive !== 'undefined') ? WTFLive.injected('__WTF_ENTITIES', null) : null;
if (INJECTED) { Object.keys(index).forEach(function (k) { delete index[k]; });
  INJECTED.forEach(function (e) { (e.products || ['wtf']).forEach(function (p) { add(e.name, e.type || 'unknown', Object.keys(REG_PRODUCT).find(function (r) { return REG_PRODUCT[r] === p; }) || 'coverage', (e.mentions || 0) + ' mentions', 'wtf-cross-watch.html'); }); }); }
const ENTITIES = Object.keys(index).map(function (k) {
  const e = index[k];
  const regs = {};
  e.apps.forEach(function (a) { regs[a.register] = 1; });
  e.registers = Object.keys(regs);
  const prods = {};
  e.registers.forEach(function (r) { prods[REG_PRODUCT[r] || 'wtf'] = 1; });
  e.products = Object.keys(prods);
  e.mentions = e.apps.reduce(function (n, a) { const m = String(a.record).match(/^(\d[\d,]*)/); return n + (m ? parseInt(m[1].replace(/,/g, ''), 10) : 1); }, 0);
  return e;
});
const badges = function (e) {
  return '<span class="wtf-cw-badges">' + e.products.map(function (p) {
    const P = PRODUCTS[p];
    return '<span class="wtf-cw-badge" style="color:' + P.c + ';border-color:color-mix(in srgb,' + P.c + ' 35%,transparent)">' + P.l + '</span>';
  }).join('') + '<span class="wtf-cw-mentions">' + e.mentions.toLocaleString('en-CA') + ' mentions</span></span>';
};

let S = { q:'', min:2, type:'' };

/* ── legend and stats ───────────────────────────────────────────────────── */
(function () {
  const series = {};
  Object.keys(REGISTERS).forEach(function (k) {
    const r = REGISTERS[k];
    (series[r.series] = series[r.series] || { c:r.c, regs:[] }).regs.push(r.l);
  });
  $('cw-legend').innerHTML = Object.keys(series).map(function (s) {
    return '<i style="--c:' + series[s].c + '">' + s + ' \u00b7 ' + series[s].regs.join(', ') + '</i>';
  }).join('');

  const multi = ENTITIES.filter(function (e) { return e.registers.length >= 2; }).length;
  const three = ENTITIES.filter(function (e) { return e.registers.length >= 3; }).length;
  $('cw-stats').innerHTML = [
    [String(ENTITIES.length), 'Entities indexed'],
    [String(multi), 'In two or more registers'],
    [String(three), 'In three or more'],
    [String(Object.keys(REGISTERS).length), 'Registers joined'],
    [String(ENTITIES.reduce(function (n, e) { return n + e.apps.length; }, 0)), 'Records matched']
  ].map(function (r) {
    return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>';
  }).join('');

  const types = {};
  ENTITIES.forEach(function (e) { types[e.type] = 1; });
  $('cw-type').innerHTML = '<option value="">Every type</option>' +
    Object.keys(types).sort().map(function (t) {
      return '<option value="' + esc(t) + '">' + esc(t.charAt(0).toUpperCase() + t.slice(1)) + '</option>';
    }).join('');
})();

/* ── list ───────────────────────────────────────────────────────────────── */
const TYPE_COL = { person:'var(--wtf-accent)', party:'var(--wtf-local)', organisation:'var(--wtf-aurora)',
  institution:'var(--wtf-center-right)', journalist:'var(--wtf-developing)', regulator:'var(--wtf-center)',
  contract:'var(--wtf-text-muted)', unknown:'var(--wtf-border)' };

function draw() {
  const q = S.q.toLowerCase();
  const rows = ENTITIES.filter(function (e) {
    if (e.registers.length < S.min) return false;
    if (S.type && e.type !== S.type) return false;
    if (!q) return true;
    return (e.name + ' ' + e.type + ' ' + e.apps.map(function (a) { return a.record; }).join(' '))
      .toLowerCase().indexOf(q) >= 0;
  });
  /* Ordered by number of registers, which is a count of records and not a
     ranking of significance \u2014 stated on the page. */
  rows.sort(function (a, b) {
    return b.registers.length - a.registers.length || b.apps.length - a.apps.length ||
      a.name.localeCompare(b.name);
  });
  $('cw-count').textContent = rows.length + ' of ' + ENTITIES.length + ' entities';

  $('cw-list').innerHTML = rows.length ? rows.map(function (e) {
    const col = TYPE_COL[e.type] || 'var(--wtf-border)';
    return '<div class="wtf-cw-ent" style="--ec:' + col + '">' +
      '<div class="wtf-cw-h">' +
        '<a class="wtf-cw-n" href="wtf-cross-watch.html?entity=' + encodeURIComponent(e.name) + '" style="text-decoration:none;color:inherit">' + esc(e.name) + '</a>' +
        '<span class="wtf-of-tag" style="color:' + col + ';border-color:' + col + '55">' + esc(e.type) + '</span>' +
        badges(e) +
        '<span class="wtf-cw-score">' + e.registers.length + ' register' + (e.registers.length === 1 ? '' : 's') +
          ' \u00b7 ' + e.apps.length + ' record' + (e.apps.length === 1 ? '' : 's') + '</span>' +
      '</div>' +
      '<div class="wtf-cw-regs">' +
        e.registers.map(function (r) {
          const R = REGISTERS[r];
          return '<span class="wtf-cw-reg" style="background:' + R.c + '1f;color:' + R.c + '"><i></i>' + R.l + '</span>';
        }).join('') +
      '</div>' +
      e.apps.map(function (a) {
        const R = REGISTERS[a.register];
        return '<div class="wtf-cw-row" style="--rc:' + R.c + '">' +
          '<span class="wtf-cw-rk">' + R.l + '</span>' +
          '<span class="wtf-cw-rt">' + esc(a.record) +
            ' <a href="' + esc(a.link) + '" style="color:' + R.c + ';text-decoration:none;font-family:var(--wtf-font-mono);font-size:9.5px">open &rarr;</a>' +
            '<div style="font-family:var(--wtf-font-mono);font-size:8.5px;letter-spacing:.09em;text-transform:uppercase;color:var(--wtf-text-muted);margin-top:3px">' +
              'collected by ' + R.series + '</div>' +
          '</span></div>';
      }).join('') +
      (e.registers.indexOf('lobbying') >= 0
        ? '<div class="wtf-of-un" style="border-left-color:var(--wtf-aurora)">Registration under the Lobbying Act is a legal requirement. Appearing in that registry records compliance, not impropriety.</div>'
        : '') +
    '</div>';
  }).join('')
  : '<div class="panel" style="text-align:center;color:var(--wtf-text-muted);font-size:13px">' +
    'No entity appears in ' + S.min + ' or more registers under those filters. ' +
    'That is the expected result on a small window: cross-register matches are rare, which is why they are worth looking at.</div>';
}

/* Entity footprint \u2014 the live /entity/<id> page, opened in place. Free: the
   footprint tiles, recent coverage, Competition Bureau items, listed-contractor
   line. Starter+: accountability chain and co-mentions. */
let PREVIEW = false;
try { PREVIEW = WTFTier.isSubscriber(); } catch (e) {}
function openEntity(name) {
  const e = ENTITIES.filter(function (x) { return x.name === name; })[0];
  const host = $('cw-detail');
  if (!e) { host.innerHTML = ''; return; }
  const byProd = {};
  e.apps.forEach(function (a) { const p = REG_PRODUCT[a.register] || 'wtf'; byProd[p] = (byProd[p] || 0) + 1; });
  const stories = (typeof ARTICLES !== 'undefined' && typeof ENTITY_MAP !== 'undefined')
    ? (function () { const row = ENTITY_MAP.filter(function (r) { return r[1] === name; })[0];
        return row ? ARTICLES.filter(function (a) { return a.first && row[0].test(a.t + ' ' + (a.note || '')); }).slice(0, 5) : []; })()
    : [];
  const comp = COMPETITION.filter(function (r) { return r[0] === name; });
  const listed = LISTED.filter(function (r) { return r[0] === name; })[0];
  const chain = [
    ['Named in officer findings', true, e.apps.filter(function (a) { return a.register === 'finding' || a.register === 'ethics'; }).length, 0],
    ['Lobbying communications', true, 0, e.apps.filter(function (a) { return a.register === 'lobbying'; }).length],
    ['Appointments and vacancies', true, e.apps.filter(function (a) { return a.register === 'appointment' || a.register === 'vacancy'; }).length, 0],
    ['Co-mentioned in coverage', false, stories.length, 0]
  ].filter(function (l) { return l[2] || l[3]; });
  const co = ENTITIES.filter(function (x) { return x !== e && x.type === 'person' && x.registers.length >= 2; }).slice(0, 6);

  host.innerHTML =
    '<div class="wtf-cw-ent" style="--ec:var(--wtf-brand);margin-bottom:14px">' +
      '<a href="wtf-cross-watch.html" class="wtf-of-tag" style="text-decoration:none">&larr; Cross-Watch</a>' +
      '<div class="wtf-cw-h" style="margin-top:10px"><span class="wtf-cw-n" style="font-size:24px">' + esc(e.name) + '</span>' +
        '<span class="wtf-of-tag">' + esc(e.type) + '</span></div>' +
      '<div class="statrow" style="margin:6px 0 14px">' +
        [[e.products.length, 'Watch products'], [e.mentions.toLocaleString('en-CA'), 'Total mentions'], [stories.length, 'Recent stories']]
        .map(function (r) { return '<div class="stat"><div class="stat-n">' + r[0] + '</div><div class="stat-l">' + r[1] + '</div></div>'; }).join('') + '</div>' +

      '<div class="psec">Cross-Watch footprint \u2014 where this ' + esc(e.type) + ' appears</div>' +
      '<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:6px">' + e.products.map(function (p) {
        const P = PRODUCTS[p];
        return '<div class="wtf-cw-prod" style="border-left-color:' + P.c + '"><span><span class="wtf-cw-prod-l">' + P.full + '</span><span class="wtf-cw-prod-s">' + P.sub + '</span></span>' +
          '<span class="wtf-cw-prod-n" style="color:' + P.c + '">' + (byProd[p] || 0) + '</span></div>';
      }).join('') + '</div>' +
      '<div class="wtf-of-note">Entities matching this name across our datasets \u2014 coverage grows as Legal &amp; Market link in.</div>' +

      '<div class="psec" style="margin-top:16px">Recent news coverage</div>' +
      (stories.length ? stories.map(function (a) { const b = bandOf(a.lean);
        return '<div class="wtf-cw-row" style="--rc:' + b.hex + ';grid-template-columns:10px minmax(0,1fr)"><span style="width:8px;height:8px;border-radius:50%;background:' + b.hex + ';margin-top:6px"></span>' +
          '<span class="wtf-cw-rt"><a href="wtf-article.html?id=' + encodeURIComponent(a.id) + '" style="color:var(--wtf-text);text-decoration:none">' + esc(a.t) + '</a>' +
          '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin-top:2px">' + esc(a.src) + ' \u00b7 ' + ago(a.min) + ' \u00b7 the dot is the article\u2019s band, not the entity\u2019s</div></span></div>'; }).join('')
        : '<div class="wtf-of-none">No linked news articles in the current window.</div>') +

      (comp.length ? '<div class="psec" style="margin-top:16px">Named in Competition Bureau items \u2014 via Legal Watch</div>' + comp.map(function (c) {
        return '<div class="wtf-cw-row" style="--rc:var(--wtf-aurora);grid-template-columns:10px minmax(0,1fr)"><span style="width:8px;height:8px;border-radius:50%;background:var(--wtf-aurora);margin-top:6px"></span>' +
          '<span class="wtf-cw-rt"><a href="' + c[2] + '" target="_blank" rel="noopener" style="color:var(--wtf-text);text-decoration:none">' + esc(c[1]) + ' &#8599;</a>' +
          '<div style="font-family:var(--wtf-font-mono);font-size:9px;color:var(--wtf-text-muted);margin-top:2px">Competition Bureau Canada \u00b7 named in this item</div></span></div>'; }).join('') +
        '<div class="wtf-of-note">Inclusion does not imply wrongdoing or any finding.</div>' : '') +

      (listed ? '<div class="psec" style="margin-top:16px">Publicly traded \u2014 federal contracts won</div>' +
        '<div class="wtf-cw-prod" style="border-left-color:var(--wtf-developing);max-width:none"><span><span class="wtf-cw-prod-l">Trades as <strong>' + listed[1] + ':' + listed[2] + '</strong></span>' +
        '<span class="wtf-cw-prod-s">Federal contracts won \u00b7 ' + listed[3] + ' awards \u00b7 cumulative</span></span>' +
        '<span class="wtf-cw-prod-n" style="color:var(--wtf-developing)">$' + listed[4].toLocaleString('en-CA') + '</span></div>' +
        '<div class="wtf-of-note">A publicly listed company that is also a federal contractor \u2014 where public money meets the markets. Approximate and partial (CanadaBuys open procurement data, via Gov Watch)' + (listed[5] ? '; includes joint ventures it leads, so the total is an upper bound' : '') + '. Not investment advice.</div>' : '') +

      (PREVIEW
        ? '<div class="psec" style="margin-top:16px">Accountability chain \u2014 how this ' + esc(e.type) + ' connects</div>' +
          (chain.length ? chain.map(function (l) { return '<div class="wtf-cw-link"><span style="flex:1;color:var(--wtf-text-2)">' + l[0] + (l[1] ? '' : ' <span style="color:var(--wtf-text-muted);font-size:9px">enrichment</span>') + '</span>' +
              (l[2] ? '<span style="color:var(--wtf-local);font-family:var(--wtf-font-mono)">\u2192 ' + l[2] + '</span>' : '') +
              (l[3] ? '<span style="color:var(--wtf-established);font-family:var(--wtf-font-mono)">\u2190 ' + l[3] + '</span>' : '') + '</div>'; }).join('')
            : '<div class="wtf-of-none">No chain-link relationships recorded yet.</div>') +
          (co.length ? '<div class="psec" style="margin-top:16px">Co-mentioned in the news</div><div style="display:flex;flex-wrap:wrap;gap:7px">' + co.map(function (c) {
              return '<a class="wtf-of-tag" style="text-decoration:none" href="wtf-cross-watch.html?entity=' + encodeURIComponent(c.name) + '">' + esc(c.name) + ' <span style="color:var(--wtf-text-muted)">' + esc(c.type) + '</span> <span style="color:var(--wtf-local)">' + c.registers.length + '</span></a>'; }).join('') + '</div>' : '')
        : '<div class="wtf-a-pay" style="margin-top:16px"><div class="wtf-a-pay-t">Accountability chain \u2014 Starter+</div>' +
          '<p class="wtf-a-pay-b">The full accountability chain (contracts, donations, votes, lobbying) and co-mentioned entities for ' + esc(e.name) + ' are available to subscribers.</p>' +
          '<a class="wtf-a-pay-cta" href="/login?next=/entity/">Unlock with Starter &rarr;</a><div><a class="wtf-a-pay-plans" href="/join">See plans</a></div></div>') +
      '<div class="wtf-of-note" style="margin-top:14px">Cross-Watch resolves the same person or organization across Gov, Civic, Legal &amp; Market Watch and the news. Matches are name-based and grow as datasets link in.</div>' +
    '</div>';
  host.scrollTop = 0;
}
(function () {
  const want = new URLSearchParams(location.search).get('entity');
  if (want) { openEntity(want); }
  const pv = $('cw-pv');
  if (pv) {
    const lab = function () { pv.textContent = PREVIEW ? 'Show the gate' : 'Show subscriber view'; pv.style.color = PREVIEW ? 'var(--wtf-accent)' : ''; };
    lab();
    pv.addEventListener('click', function () { PREVIEW = !PREVIEW;
      try { WTFTier.set(PREVIEW); } catch (e) {}
      lab(); if (want) openEntity(want); });
  }
})();

$('cw-q').addEventListener('input', function (e) { S.q = e.target.value.trim(); draw(); });
$('cw-min').addEventListener('change', function (e) { S.min = +e.target.value; draw(); });
$('cw-type').addEventListener('change', function (e) { S.type = e.target.value; draw(); });

draw();

})();
