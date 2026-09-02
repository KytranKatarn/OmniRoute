/* Shared news corpus. Loaded by wtf-news.html and wtf-article.html so the
   feed, the drawer and the article page are all reading the same rows. */
/* ═══ feed data ══════════════════════════════════════════════════════════
   Each story carries its own coverage spread, so the lean shown on a card is
   a reading of that article against the same story elsewhere — never a
   standing label on the masthead. */
const BANDS = [
  { k:'left', l:'Left', hex:'#d84b47' }, { k:'center-left', l:'Center-Left', hex:'#cf8b80' },
  { k:'center', l:'Center', hex:'#929aa5' }, { k:'center-right', l:'Center-Right', hex:'#7fa3cf' },
  { k:'right', l:'Right', hex:'#4a72d8' }
];
const VERDICTS = { established:{l:'Established',c:'#10b981',g:'✓'}, developing:{l:'Developing',c:'#f59e0b',g:'◐'}, contested:{l:'Contested',c:'#e05252',g:'⚠'} };
const BEATS = ['Parliament','Economy','Climate','Health','Crime','Business','Justice','Indigenous','Sports'];
const PROVS = ['BC','AB','SK','MB','ON','QC','NB','NS','PE','NL','YT','NT','NU'];

const A = [
 ['Auditor general tables procurement findings; committee vote unanimous','CBC News','ON','Parliament','center-left','established',16,14,[12,34,28,17,9],'Coverage split on whether the findings implicate the current government or the previous one. The report itself names neither.',false],
 ['Bank of Canada holds overnight rate, signals data-dependent path','The Globe and Mail','ON','Economy','center','established',22,31,[9,24,38,20,9],'Every major outlet carried the hold. The divergence is in what they made of the forward guidance.',false],
 ['Alberta files judicial review over federal emissions cap','Calgary Herald','AB','Climate','right','developing',11,44,[8,14,22,25,31],'Framed as provincial defence in western outlets and as obstruction in central ones. Same filing.',false],
 ['Wildfire evacuation order lifted for two northern communities','CTV News','BC','Climate','center','established',7,52,[14,26,34,17,9],'Straight service reporting almost everywhere. Little framing variance to measure.',false],
 ['Québec tables bill on private clinic billing caps','Le Devoir','QC','Health','left','developing',9,68,[31,34,20,10,5],'Anglophone national outlets covered it thinly. The detail is mostly in French-language coverage.',true],
 ['Grocery price index cools for third consecutive month','Financial Post','ON','Economy','center-right','established',14,77,[11,22,30,24,13],'Business press led with relief; consumer desks led with the level still being high. Both are true.',false],
 ['Halifax council approves rezoning for 1,400 rental units','Halifax Examiner','NS','Business','center-left','established',4,95,[18,33,29,13,7],'Local story with almost no national pickup despite being the largest approval in the province this year.',true],
 ['RCMP release annual firearms enforcement statistics','National Post','ON','Crime','right','contested',12,112,[19,17,21,20,23],'The widest lean spread in the feed. Outlets disagree on what the numbers show, not on the numbers.',false],
 ['Manitoba signs bilateral health transfer agreement','Winnipeg Free Press','MB','Health','center','established',6,126,[13,25,35,18,9],'Signed quietly. Coverage is thin and largely procedural.',false],
 ['Ontario teachers reach tentative agreement, averting job action','Toronto Star','ON','Parliament','center-left','established',18,140,[16,32,27,16,9],'Broad pickup. Framing turns on whether the deal is described as a settlement or a climbdown.',false],
 ['Port of Vancouver container volumes hit quarterly record','Business in Vancouver','BC','Business','center-right','established',5,158,[10,20,31,25,14],'Trade press only. No general-audience outlet carried it.',true],
 ['Saskatchewan potash royalties revised upward in fiscal update','Regina Leader-Post','SK','Economy','center-right','developing',8,171,[9,17,27,27,20],'Prairie outlets treated it as a fiscal story; national outlets, where they carried it, as a commodities one.',false],
 ['Federal court rules on Indigenous consultation in pipeline review','APTN News','BC','Indigenous','left','established',13,189,[28,31,22,12,7],'APTN carried it first and in most depth. National pickup followed by several hours.',false],
 ['Blue Jays clinch wild-card berth in extra innings','Sportsnet','ON','Sports','center',null,9,203,[12,24,38,17,9],'',false],
 ['New Brunswick announces emergency room staffing plan','CBC New Brunswick','NB','Health','center','developing',5,224,[14,27,33,17,9],'Announced without a costing. Two outlets noted the omission; the rest did not.',false],
 ['Auto sector tariff exposure reviewed ahead of trade talks','Reuters Canada','ON','Business','center','established',17,241,[11,23,36,20,10],'Wire copy ran nearly verbatim in most outlets, which compresses the measurable spread.',false],
 ['Supreme Court declines to hear appeal in privacy case','The Canadian Press','ON','Justice','center','established',15,258,[13,26,34,18,9],'Declining to hear is not a ruling. Three outlets reported it as one.',false],
 ['Nova Scotia fishery quota cuts contested by inshore fleet','SaltWire','NS','Business','center-right','contested',6,276,[16,21,26,22,15],'Two accounts of the same consultation process, and they do not reconcile.',false],
 ['Yukon files land use plan for Peel watershed','Yukon News','YT','Indigenous','center-left','established',3,294,[22,30,28,13,7],'Almost no coverage south of 60. The plan follows a decade-long court process.',true],
 ['Federal housing accelerator payments delayed to four cities','CBC News','ON','Parliament','center','developing',10,311,[15,28,31,17,9],'The delay was confirmed in an emailed statement, not announced.',false],
 ['Montréal transit agency posts operating shortfall','La Presse','QC','Municipal','center-left','established',7,329,[24,33,25,12,6],'French-language coverage is substantially more detailed than the English summaries.',true],
 ['Alberta teachers vote to accept mediated settlement','Edmonton Journal','AB','Parliament','center-right','established',9,347,[10,19,29,24,18],'Ended a dispute that ran most of the school year.',false],
 ['CRTC opens consultation on local news funding','The Globe and Mail','ON','Media','center','developing',11,365,[14,27,32,18,9],'Outlets covering the consultation are also parties to it. Few disclosed that.',false],
 ['Newfoundland offshore wind bids attract five proponents','CBC Newfoundland','NL','Climate','center','established',4,384,[15,26,33,17,9],'Local coverage only, despite national energy relevance.',true]
];

/* A story is a CLUSTER; the database stores one row per ARTICLE. The seed
   rows above are the clusters — each one is expanded into the individual
   outlet articles that make it up, which is what a full archive holds and
   what "latest" has to sort over. */
const CLUSTERS = A.map((r, i) => ({
  id:'c'+i, t:r[0], src:r[1], prov:r[2], beat:r[3], lean:r[4], verdict:r[5],
  outlets:r[6], min:r[7], spread:r[8], note:r[9], blind:r[10]
}));

const POOL = [
  ['CBC News','center-left'], ['The Globe and Mail','center'], ['National Post','right'],
  ['Toronto Star','center-left'], ['CTV News','center'], ['Global News','center'],
  ['Financial Post','center-right'], ['Le Devoir','left'], ['La Presse','center-left'],
  ['Radio-Canada','center-left'], ['Reuters Canada','center'], ['The Canadian Press','center'],
  ['Calgary Herald','center-right'], ['Winnipeg Free Press','center'], ['APTN News','left'],
  ['The Tyee','left'], ['Western Standard','right'], ['Rebel News','right'],
  ['iPolitics','center'], ['The Hill Times','center'], ['Halifax Examiner','center-left'],
  ['Regina Leader-Post','center-right'], ['Vancouver Sun','center'], ['Montreal Gazette','center'],
  ['Business in Vancouver','center-right'], ['The Narwhal','left'], ['Blacklock\u2019s Reporter','center-right']
];

/* Deterministic so the archive is stable between reloads. */
function rnd(seed) { let x = seed * 9301 + 49297; return () => ((x = (x * 9301 + 49297) % 233280) / 233280); }

const ARTICLES = [];
CLUSTERS.forEach((c, ci) => {
  const r = rnd(ci + 7);
  const used = new Set([c.src]);
  // The originating outlet files first; the rest follow over the next hours.
  ARTICLES.push({ id:c.id+'-0', cid:c.id, t:c.t, src:c.src, prov:c.prov, beat:c.beat,
    lean:c.lean, verdict:c.verdict, outlets:c.outlets, min:c.min, spread:c.spread,
    note:c.note, blind:c.blind, first:true });
  for (let k = 1; k < c.outlets; k++) {
    let pick = POOL[Math.floor(r() * POOL.length)], guard = 0;
    while (used.has(pick[0]) && guard++ < 40) pick = POOL[Math.floor(r() * POOL.length)];
    used.add(pick[0]);
    const base = BANDS.findIndex(b => b.k === pick[1]);
    const pull = BANDS.findIndex(b => b.k === c.lean) - base;
    // Most pieces sit at the outlet's tendency; some drift, a few land across
    // the middle, and the story's own centre of gravity tugs them.
    const roll = r();
    const drift = roll < 0.46 ? 0 : roll < 0.78 ? (r() < 0.5 ? -1 : 1) : (r() < 0.5 ? -2 : 2);
    const idx = Math.max(0, Math.min(4, base + drift + (r() < 0.34 ? Math.sign(pull) : 0)));
    ARTICLES.push({ id:c.id+'-'+k, cid:c.id, t:c.t, src:pick[0], prov:c.prov, beat:c.beat,
      lean:BANDS[idx].k, verdict:c.verdict, outlets:c.outlets, min:c.min + Math.round(r() * 340) + 12,
      spread:c.spread, note:null, blind:c.blind, first:false });
  }
});


const NOW = new Date();
const dateOf = m => new Date(NOW.getTime() - m * 60000);
const ago = m => m < 60 ? m+'m ago' : m < 1440 ? Math.floor(m/60)+'h ago' : Math.floor(m/1440)+'d ago';
const bandOf = k => BANDS.find(b => b.k === k);
const byId = id => ARTICLES.find(a => a.id === id);

/* Sibling articles in the same cluster, filed order. */
const siblingsOf = a => ARTICLES.filter(x => x.cid === a.cid).sort((p,q) => p.min - q.min);

/* Each outlet frames the same event differently. The headline variants are
   derived from the cluster headline plus the outlet's band, so the framing
   shown always matches the lean recorded for that row. */
const FRAME = {
  left:          t => t.replace(/^(\w+)/, '$1') + ' — advocates warn of who absorbs the cost',
  'center-left': t => t + ', critics say questions remain',
  center:        t => t,
  'center-right':t => t + ' amid competitiveness concerns',
  right:         t => t.replace(/^/, '') + ' — Ottawa faces pushback'
};
const headlineFor = a => (FRAME[a.lean] || FRAME.center)(a.t);

/* Language is a real divergence axis in Canadian coverage, so it lives on the
   row rather than being inferred at render time. */
const LANG_SRC = { 'Le Devoir':'fr', 'La Presse':'fr', 'Radio-Canada':'fr', 'Montreal Gazette':'en' };
const FR_TITLE = {
  'Auditor general tables procurement findings; committee vote unanimous':'La vérificatrice générale dépose son rapport sur les marchés publics',
  'Bank of Canada holds overnight rate, signals data-dependent path':'La Banque du Canada maintient son taux directeur',
  'Québec tables bill on private clinic billing caps':'Québec dépose un projet de loi sur la facturation en clinique privée',
  'Montréal transit agency posts operating shortfall':'La STM affiche un déficit d\u2019exploitation',
  'Federal housing accelerator payments delayed to four cities':'Ottawa retarde les versements du Fonds pour accélérer la construction'
};
ARTICLES.forEach(a => {
  a.lang = LANG_SRC[a.src] || 'en';
  if (a.lang === 'fr') a.tFr = FR_TITLE[a.t] || null;
});
const titleOf = a => (a.lang === 'fr' && a.tFr) ? a.tFr : a.t;

/* Outlet reputation computed from the corpus, so a masthead reads the same on
   every article instead of being minted per page load. */
const OUTLET_STATS = (() => {
  const m = {}, val = k => (BANDS.findIndex(b => b.k === k) - 2) / 2;
  ARTICLES.forEach(a => {
    const o = m[a.src] || (m[a.src] = { n:0, sum:0, checked:0, blind:0, first:0, beats:{}, provs:{} });
    o.n++; o.sum += val(a.lean);
    if (a.verdict) o.checked++;
    if (a.blind) o.blind++;
    if (a.first) o.first++;
    o.beats[a.beat] = (o.beats[a.beat] || 0) + 1;
    o.provs[a.prov] = (o.provs[a.prov] || 0) + 1;
  });
  Object.values(m).forEach(o => {
    o.avg = +(o.sum / o.n).toFixed(3);
    o.band = BANDS[Math.max(0, Math.min(4, Math.round(o.avg * 2) + 2))];
    o.topBeat = Object.entries(o.beats).sort((x,y) => y[1]-x[1])[0][0];
    o.topProv = Object.entries(o.provs).sort((x,y) => y[1]-x[1])[0][0];
  });
  return m;
})();

/* Entities read out of the story text rather than a fixed list, so a name
   never appears on an article that does not mention it. */
const ENTITY_MAP = [
  [/auditor general/i, 'Auditor General of Canada', 'institution', 'wtf-officers.html'],
  [/bank of canada|overnight rate/i, 'Bank of Canada', 'institution', 'wtf-rates.html'],
  [/rcmp/i, 'RCMP', 'institution', 'wtf-officers.html'],
  [/crtc/i, 'CRTC', 'regulator', 'wtf-crtc.html'],
  [/federal court|supreme court/i, 'Federal courts', 'institution', 'wtf-claims.html'],
  [/committee/i, 'House committee', 'institution', 'wtf-mps.html'],
  [/procurement/i, 'Federal procurement', 'file', 'wtf-lobbying.html'],
  [/emissions cap/i, 'Federal emissions cap', 'file', 'wtf-economy.html'],
  [/tariff|trade talks/i, 'Canada-US trade file', 'file', 'wtf-markets.html'],
  [/housing accelerator/i, 'Housing Accelerator Fund', 'file', 'wtf-cost.html'],
  [/wildfire|evacuation/i, 'Wildfire response', 'file', 'wtf-weather.html'],
  [/indigenous|consultation/i, 'Duty to consult', 'file', 'wtf-claims.html'],
  [/potash|royalt/i, 'Resource royalties', 'file', 'wtf-economy.html'],
  [/teachers|bargaining|agreement/i, 'Public sector bargaining', 'file', 'wtf-cost.html'],
  [/lobby/i, 'Lobbying registry', 'file', 'wtf-lobbying.html'],
  [/clinic|health|emergency room/i, 'Health transfers', 'file', 'wtf-economy.html'],
  [/transit|stm/i, 'Municipal transit', 'file', 'wtf-municipal.html']
];
const PROV_NAMES = { BC:'British Columbia', AB:'Alberta', SK:'Saskatchewan', MB:'Manitoba', ON:'Ontario',
  QC:'Quebec', NB:'New Brunswick', NS:'Nova Scotia', PE:'Prince Edward Island',
  NL:'Newfoundland and Labrador', YT:'Yukon', NT:'Northwest Territories', NU:'Nunavut' };
function entitiesFor(a) {
  const hay = a.t + ' ' + (a.note || '');
  const out = [];
  ENTITY_MAP.forEach(([re, name, kind, href]) => {
    if (re.test(hay) && !out.some(e => e.name === name)) out.push({ name, kind, href });
  });
  out.push({ name: PROV_NAMES[a.prov] || a.prov, kind:'jurisdiction', href:'wtf-municipal.html' });
  return out.slice(0, 5);
}

/* Claim-level checks. Deterministic per article so the same story always
   shows the same claims, and every claim carries its own source. */
const CLAIM_KINDS = [
  { re:/procurement|auditor/i, claims:[
    ['The report was tabled without an attached costing.', 'established', 'Report text, p. 3'],
    ['Committee approved the findings without a dissenting vote.', 'established', 'Committee minutes'],
    ['The findings implicate the current government.', 'contested', 'No attribution in the report'] ]},
  { re:/bank of canada|overnight rate|inflation/i, claims:[
    ['The overnight rate was held at its previous level.', 'established', 'Bank of Canada release'],
    ['The Bank signalled a data-dependent path.', 'established', 'Governor\u2019s statement'],
    ['A cut is expected at the next decision.', 'developing', 'Analyst commentary only'] ]},
  { re:/emissions|climate|carbon/i, claims:[
    ['A judicial review application was filed.', 'established', 'Court registry'],
    ['The cap exceeds federal jurisdiction.', 'contested', 'Disputed by both governments'] ]},
  { re:/wildfire|evacuation/i, claims:[
    ['The evacuation order was lifted for the named communities.', 'established', 'Provincial emergency bulletin'],
    ['Conditions are expected to hold through the week.', 'developing', 'Forecast, not observation'] ]},
  { re:/health|clinic|emergency room/i, claims:[
    ['The bill was tabled in the legislature.', 'established', 'Order paper'],
    ['Billing caps will reduce wait times.', 'contested', 'No supporting study cited'] ]}
];
const GENERIC_CLAIMS = [
  ['The central factual assertion is supported by a primary document.', 'established', 'Source document'],
  ['Figures quoted match the originating release.', 'established', 'Originating release'],
  ['Causal framing in the headline is not established by the text.', 'developing', 'Article text']
];
function CLAIMS_FOR(a) {
  const hay = a.t + ' ' + (a.note || '');
  const hit = CLAIM_KINDS.find(k => k.re.test(hay));
  return (hit ? hit.claims : GENERIC_CLAIMS).map(([text, verdict, src]) => ({ text, verdict, src }));
}

/* How often an entity appears across the corpus — the number that makes it
   worth following. */
function entityCount(name) {
  const stories = ARTICLES.filter(x => x.first);
  const row = ENTITY_MAP.find(e => e[1] === name);
  if (row) return stories.filter(x => row[0].test(x.t + ' ' + (x.note || ''))).length;
  const code = Object.keys(PROV_NAMES).find(k => PROV_NAMES[k] === name);
  return code ? stories.filter(x => x.prov === code).length : 0;
}

/* Ownership. Grouping outlets by who controls them is the point of the map;
   an owner's average is reported ALONGSIDE its range, because a portfolio
   holding both poles averages to the centre and is not centrist. */
const OWNER_OF = {
  'CBC News':['Canadian Broadcasting Corporation','public'],
  'Radio-Canada':['Canadian Broadcasting Corporation','public'],
  'CBC New Brunswick':['Canadian Broadcasting Corporation','public'],
  'The Globe and Mail':['The Woodbridge Company','private'],
  'National Post':['Postmedia Network','public-company'],
  'Financial Post':['Postmedia Network','public-company'],
  'Calgary Herald':['Postmedia Network','public-company'],
  'Montreal Gazette':['Postmedia Network','public-company'],
  'Regina Leader-Post':['Postmedia Network','public-company'],
  'Toronto Star':['Torstar','private'],
  'CTV News':['Bell Media','public-company'],
  'Global News':['Corus Entertainment','public-company'],
  'Le Devoir':['Le Devoir (independent trust)','nonprofit'],
  'La Presse':['La Presse (nonprofit trust)','nonprofit'],
  'Winnipeg Free Press':['FP Canadian Newspapers','private'],
  'Halifax Examiner':['Halifax Examiner','independent'],
  'The Tyee':['Tyee Solutions Society','nonprofit'],
  'The Narwhal':['The Narwhal','nonprofit'],
  'APTN News':['Aboriginal Peoples Television Network','nonprofit'],
  'The Canadian Press':['The Canadian Press','cooperative'],
  'Reuters Canada':['Thomson Reuters','public-company'],
  'Sportsnet':['Rogers Sports & Media','public-company'],
  'Business in Vancouver':['Glacier Media','public-company'],
  'Blacklock\u2019s Reporter':['Blacklock\u2019s Reporter','independent'],
  'Vancouver Sun':['Postmedia Network','public-company'],
  'Edmonton Journal':['Postmedia Network','public-company'],
  'iPolitics':['iPolitics','independent'],
  'The Hill Times':['Hill Times Publishing','independent'],
  'Western Standard':['Western Standard New Media','private'],
  'CBC Newfoundland':['Canadian Broadcasting Corporation','public'],
  'SaltWire':['SaltWire Network','private'],
  'Yukon News':['Black Press Media','private'],
  'Rebel News':['Rebel News Network','independent']
};
const OWNER_TYPE_LABEL = { 'public':'Public broadcaster', 'public-company':'Publicly traded',
  'private':'Privately held', 'nonprofit':'Non-profit', 'cooperative':'Co-operative',
  'independent':'Independent' };
const OWNERS = (() => {
  const m = {};
  Object.keys(OUTLET_STATS).forEach(src => {
    const [own, type] = OWNER_OF[src] || [src, 'independent'];
    const o = m[own] || (m[own] = { name:own, type, outlets:[], articles:0 });
    o.outlets.push({ src, s:OUTLET_STATS[src] });
    o.articles += OUTLET_STATS[src].n;
  });
  Object.values(m).forEach(o => {
    o.outlets.sort((a, b) => a.s.avg - b.s.avg);
    o.avg = +(o.outlets.reduce((t, x) => t + x.s.avg * x.s.n, 0) / o.articles).toFixed(3);
    o.band = BANDS[Math.max(0, Math.min(4, Math.round(o.avg * 2) + 2))];
    o.lo = o.outlets[0].s.band; o.hi = o.outlets[o.outlets.length - 1].s.band;
    o.spanBands = new Set(o.outlets.map(x => x.s.band.k)).size;
  });
  return Object.values(m).sort((a, b) => b.outlets.length - a.outlets.length || b.articles - a.articles);
})();

/* CRTC rulings. Public record; each row names its own decision number. */
const CRTC_TYPES = { broadcasting:['Broadcasting','#4a72d8'], telecom:['Telecom','#a78bfa'],
  licensing:['Licensing','#10b981'], enforcement:['Enforcement','#e05252'], policy:['Policy','#f59e0b'] };
const CRTC = [
  ['2026-241','licensing','Licence renewal for a national news service','Renewed to 2031 with conditions on local news spending and closed captioning.','National','CBC News',18],
  ['2026-227','policy','Online Streaming Act base contributions','Set initial contribution levels for foreign streaming services toward Canadian content funds.','National','',34],
  ['2026-198','enforcement','Undue preference complaint dismissed','Commission found no undue preference in carriage terms between a distributor and an independent channel.','National','',52],
  ['2026-171','telecom','Wholesale fibre access rates','Final rates set for third-party access to incumbent fibre networks.','National','',66],
  ['2026-140','broadcasting','Local news exemption extended','Small-market television stations exempted from certain local programming quotas for one year.','Regional','Global News',88],
  ['2026-119','licensing','Ownership transfer approved','Approved transfer of effective control of four radio stations, with tangible benefits attached.','Regional','Corus',103],
  ['2026-094','enforcement','Accessibility non-compliance','Broadcaster directed to file a corrective plan after captioning shortfalls.','National','',129],
  ['2026-061','policy','Indigenous broadcasting policy review','Commission launched a review of the 1990 native broadcasting policy.','National','APTN News',162],
  ['2026-030','telecom','Wireless roaming obligations','Clarified obligations of national carriers toward regional competitors.','National','',201],
  ['2025-402','broadcasting','French-language services outside Quebec','Conditions imposed to sustain minority-language programming.','Regional','Radio-Canada',238]
].map(r => ({ num:r[0], type:r[1], subject:r[2], desc:r[3], scope:r[4], outlet:r[5], min:r[6] * 60 }));
