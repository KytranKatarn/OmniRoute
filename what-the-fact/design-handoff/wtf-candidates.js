/* Candidates and races.

   A candidate is not an office holder. An MP has a voting record; a candidate
   has a nomination date and nothing else, so this file deliberately cannot
   express a "record" for one. Three rules hold throughout:

   1. CONFIRMED ONLY. A nomination is a fact with a date and a filing body.
      A "likely candidate" is a rumour with a name attached, and naming a
      private citizen as a candidate before they are nominated is the single
      most damaging thing this section could do. Unconfirmed entries carry
      status:'declared' and are visually separated, never mixed into a slate.
   2. INCUMBENCY IS A FLAG, NOT A RECORD. A sitting member running again is
      marked, and links OUT to their profile. The race never pulls their
      voting record in — that would give one candidate a page their opponents
      cannot have.
   3. MUNICIPAL IS NON-PARTISAN. Most Canadian municipalities have no parties
      at all, so party colour is absent by design rather than defaulted to
      grey-as-independent. Vancouver and Montréal are the exceptions and are
      marked as such. */

const RACE_LEVELS = {
  federal:    { label:'Federal',    unit:'riding',   body:'Elections Canada' },
  provincial: { label:'Provincial', unit:'riding',   body:'Élections Québec' },
  municipal:  { label:'Municipal',  unit:'ward',     body:'municipal clerk' }
};

/* Party colour is the BALLOT vocabulary — the same set the floor plans use.
   It is never the bias spectrum, which measures articles, not people. */
const CAND_COL = {
  Liberal:'#d71920', Conservative:'#1a4782', Bloc:'#33b2cc', NDP:'#f58220',
  Green:'#3d9b35', 'People\u2019s Party':'#4f2683',
  CAQ:'#00a0d2', PQ:'#004a8f', 'Québec solidaire':'#ff5605', PLQ:'#d71920',
  'Parti conservateur du Québec':'#1a4782',
  'ABC Vancouver':'#0b5ea8', 'OneCity':'#e8112d', 'COPE':'#d4342f',
  'Projet Montréal':'#00a693', 'Ensemble Montréal':'#1a4782',
  Independent:'#8a94a3'
};
const NONPARTISAN = 'Non-partisan';

/* ── federal ────────────────────────────────────────────────────────────
   Real riding names. Confirmed nominations only, which is why most ridings
   have a partial slate this far out — that partial state IS the reporting. */
const FEDERAL_RACES = [
  { id:'f-toronto-centre', riding:'Toronto Centre', prov:'ON', pop:112500,
    incumbent:{ name:'Marci Ien', party:'Liberal', slug:'marci-ien', running:true },
    cands:[
      { name:'Marci Ien', party:'Liberal', confirmed:'2026-06-14', status:'confirmed', inc:true, mentions:34 },
      { name:'D. Ashfield', party:'Conservative', confirmed:'2026-07-02', status:'confirmed', mentions:6 },
      { name:'S. Okonkwo', party:'NDP', confirmed:'2026-07-19', status:'confirmed', mentions:3 },
      { name:'R. Villeneuve', party:'Green', confirmed:'2026-08-11', status:'confirmed', mentions:1 }
    ] },
  { id:'f-calgary-centre', riding:'Calgary Centre', prov:'AB', pop:107300,
    incumbent:{ name:'Greg McLean', party:'Conservative', slug:'greg-mclean', running:true },
    cands:[
      { name:'Greg McLean', party:'Conservative', confirmed:'2026-05-28', status:'confirmed', inc:true, mentions:19 },
      { name:'A. Kaur', party:'Liberal', confirmed:'2026-07-30', status:'confirmed', mentions:4 },
      { name:'T. Whitecalf', party:'NDP', confirmed:'2026-08-04', status:'confirmed', mentions:2 }
    ] },
  { id:'f-vancouver-granville', riding:'Vancouver Granville', prov:'BC', pop:104800,
    incumbent:{ name:'Taleeb Noormohamed', party:'Liberal', slug:'taleeb-noormohamed', running:false, note:'not seeking re-election' },
    cands:[
      { name:'P. Grewal', party:'Liberal', confirmed:'2026-08-19', status:'confirmed', mentions:5 },
      { name:'M. Chan', party:'Conservative', confirmed:'2026-07-11', status:'confirmed', mentions:7 },
      { name:'J. Ferreira', party:'NDP', confirmed:'2026-06-30', status:'confirmed', mentions:9 },
      { name:'L. Osei', party:'Green', status:'declared', mentions:0 }
    ] },
  { id:'f-papineau', riding:'Papineau', prov:'QC', pop:108900,
    incumbent:null,
    cands:[
      { name:'É. Brière', party:'Liberal', confirmed:'2026-08-01', status:'confirmed', mentions:11 },
      { name:'S. Lemire', party:'Bloc', confirmed:'2026-07-22', status:'confirmed', mentions:8 },
      { name:'A. Boulerice', party:'NDP', confirmed:'2026-06-05', status:'confirmed', mentions:14 }
    ] },
  { id:'f-halifax', riding:'Halifax', prov:'NS', pop:106200,
    incumbent:{ name:'Lena Metlege Diab', party:'Liberal', slug:'lena-metlege-diab', running:true },
    cands:[
      { name:'Lena Metlege Diab', party:'Liberal', confirmed:'2026-06-21', status:'confirmed', inc:true, mentions:16 },
      { name:'M. O\u2019Brien', party:'Conservative', confirmed:'2026-08-14', status:'confirmed', mentions:2 }
    ] },
  { id:'f-winnipeg-centre', riding:'Winnipeg Centre', prov:'MB', pop:96400,
    incumbent:{ name:'Leah Gazan', party:'NDP', slug:'leah-gazan', running:true },
    cands:[
      { name:'Leah Gazan', party:'NDP', confirmed:'2026-05-16', status:'confirmed', inc:true, mentions:21 },
      { name:'K. Doucette', party:'Liberal', confirmed:'2026-08-25', status:'confirmed', mentions:1 }
    ] },
  { id:'f-edmonton-strathcona', riding:'Edmonton Strathcona', prov:'AB', pop:110600,
    incumbent:{ name:'Heather McPherson', party:'NDP', slug:'heather-mcpherson', running:true },
    cands:[
      { name:'Heather McPherson', party:'NDP', confirmed:'2026-06-08', status:'confirmed', inc:true, mentions:27 },
      { name:'D. Moreau', party:'Conservative', confirmed:'2026-07-26', status:'confirmed', mentions:5 },
      { name:'H. Bissonnette', party:'Liberal', status:'declared', mentions:0 }
    ] },
  { id:'f-nunavut', riding:'Nunavut', prov:'NU', pop:40700,
    incumbent:{ name:'Lori Idlout', party:'NDP', slug:'lori-idlout', running:true },
    cands:[
      { name:'Lori Idlout', party:'NDP', confirmed:'2026-07-14', status:'confirmed', inc:true, mentions:8 }
    ] },
  { id:'f-mount-royal', riding:'Mount Royal', prov:'QC', pop:99800, incumbent:null, cands:[] },
  { id:'f-brampton-west', riding:'Brampton West', prov:'ON', pop:128400, incumbent:null, cands:[] }
];

/* ── provincial: Québec, 5 October 2026 ─────────────────────────────────
   The only provincial general election on the calendar, so it is the only one
   with nominations to report. Real riding names. */
const PROVINCIAL_RACES = [
  { id:'q-taschereau', riding:'Taschereau', prov:'QC', pop:53200, incumbent:null,
    cands:[
      { name:'C. Dorion', party:'Québec solidaire', confirmed:'2026-07-08', status:'confirmed', inc:true, mentions:22 },
      { name:'M. Tremblay', party:'CAQ', confirmed:'2026-07-15', status:'confirmed', mentions:6 },
      { name:'J. Fontaine', party:'PQ', confirmed:'2026-08-02', status:'confirmed', mentions:9 },
      { name:'A. Lemieux', party:'PLQ', confirmed:'2026-08-20', status:'confirmed', mentions:3 }
    ] },
  { id:'q-camille-laurin', riding:'Camille-Laurin', prov:'QC', pop:51900, incumbent:null,
    cands:[
      { name:'P. St-Pierre Plamondon', party:'PQ', confirmed:'2026-06-28', status:'confirmed', inc:true, mentions:41 },
      { name:'G. Desilets', party:'CAQ', confirmed:'2026-07-30', status:'confirmed', mentions:4 },
      { name:'R. Cardinal', party:'Québec solidaire', confirmed:'2026-08-09', status:'confirmed', mentions:2 }
    ] },
  { id:'q-lanaudiere', riding:'L\u2019Assomption', prov:'QC', pop:57400, incumbent:null,
    cands:[
      { name:'F. Legault', party:'CAQ', confirmed:'2026-06-19', status:'confirmed', inc:true, mentions:118 },
      { name:'S. Ahmadi', party:'PQ', confirmed:'2026-08-05', status:'confirmed', mentions:7 },
      { name:'L. Fortin', party:'PLQ', confirmed:'2026-08-22', status:'confirmed', mentions:2 }
    ] },
  { id:'q-mercier', riding:'Mercier', prov:'QC', pop:49800, incumbent:null,
    cands:[
      { name:'R. Massé', party:'Québec solidaire', confirmed:'2026-07-01', status:'confirmed', inc:true, mentions:17 },
      { name:'T. Blais', party:'PQ', confirmed:'2026-08-13', status:'confirmed', mentions:3 }
    ] },
  { id:'q-sherbrooke', riding:'Sherbrooke', prov:'QC', pop:55100, incumbent:null,
    cands:[
      { name:'C. Bélanger', party:'CAQ', confirmed:'2026-07-24', status:'confirmed', inc:true, mentions:11 },
      { name:'É. Roy', party:'Québec solidaire', confirmed:'2026-08-07', status:'confirmed', mentions:4 },
      { name:'N. Gagnon', party:'PLQ', status:'declared', mentions:0 }
    ] },
  { id:'q-westmount', riding:'Westmount\u2013Saint-Louis', prov:'QC', pop:52600, incumbent:null, cands:[] }
];

/* ── municipal ──────────────────────────────────────────────────────────
   Mayors AND wards, because a ward councillor decides the zoning on one
   street and a mayor does not. Most races are non-partisan; Vancouver and
   Montréal run civic parties and are marked. */
const MUNICIPAL_RACES = [
  { id:'m-toronto-mayor', city:'Toronto', prov:'ON', date:'2026-10-26', seat:'mayor',
    partisan:false, wards:25, pop:2794356,
    cands:[
      { name:'O. Chow', party:NONPARTISAN, confirmed:'2026-05-02', status:'confirmed', inc:true, mentions:87 },
      { name:'A. Furey', party:NONPARTISAN, confirmed:'2026-07-09', status:'confirmed', mentions:12 },
      { name:'B. Saunders', party:NONPARTISAN, confirmed:'2026-08-01', status:'confirmed', mentions:24 }
    ] },
  { id:'m-toronto-w13', city:'Toronto', prov:'ON', date:'2026-10-26', seat:'Ward 13 — Toronto Centre',
    partisan:false, pop:112800,
    cands:[
      { name:'C. Malik', party:NONPARTISAN, confirmed:'2026-06-30', status:'confirmed', inc:true, mentions:5 },
      { name:'D. Rowntree', party:NONPARTISAN, confirmed:'2026-08-12', status:'confirmed', mentions:1 }
    ] },
  { id:'m-toronto-w04', city:'Toronto', prov:'ON', date:'2026-10-26', seat:'Ward 4 — Parkdale-High Park',
    partisan:false, pop:105300,
    cands:[
      { name:'G. Perks', party:NONPARTISAN, confirmed:'2026-07-17', status:'confirmed', inc:true, mentions:4 }
    ] },
  { id:'m-toronto-w22', city:'Toronto', prov:'ON', date:'2026-10-26', seat:'Ward 22 — Scarborough-Agincourt',
    partisan:false, pop:118200, cands:[] },
  { id:'m-vancouver-mayor', city:'Vancouver', prov:'BC', date:'2026-10-17', seat:'mayor',
    partisan:true, wards:0, pop:662248,
    cands:[
      { name:'K. Sim', party:'ABC Vancouver', confirmed:'2026-05-21', status:'confirmed', inc:true, mentions:52 },
      { name:'C. Boyle', party:'OneCity', confirmed:'2026-06-18', status:'confirmed', mentions:18 },
      { name:'J. Swanson', party:'COPE', confirmed:'2026-07-25', status:'confirmed', mentions:6 }
    ] },
  { id:'m-vancouver-council', city:'Vancouver', prov:'BC', date:'2026-10-17', seat:'council (at-large, 10 seats)',
    partisan:true, pop:662248,
    cands:[
      { name:'S. Kirby-Yung', party:'ABC Vancouver', confirmed:'2026-06-02', status:'confirmed', inc:true, mentions:9 },
      { name:'P. Fry', party:'OneCity', confirmed:'2026-06-27', status:'confirmed', inc:true, mentions:7 },
      { name:'L. Osei', party:'COPE', confirmed:'2026-08-15', status:'confirmed', mentions:1 }
    ] },
  { id:'m-montreal-mayor', city:'Montréal', prov:'QC', date:'2026-11-01', seat:'mayor',
    partisan:true, wards:19, pop:1762949,
    cands:[
      { name:'V. Plante', party:'Projet Montréal', confirmed:'2026-05-11', status:'confirmed', inc:true, mentions:74 },
      { name:'A. Coderre', party:'Ensemble Montréal', confirmed:'2026-06-24', status:'confirmed', mentions:31 }
    ] },
  { id:'m-montreal-plateau', city:'Montréal', prov:'QC', date:'2026-11-01', seat:'Le Plateau-Mont-Royal — borough mayor',
    partisan:true, pop:104000,
    cands:[
      { name:'L. Gagnon', party:'Projet Montréal', confirmed:'2026-07-03', status:'confirmed', inc:true, mentions:6 },
      { name:'M. Beaulieu', party:'Ensemble Montréal', confirmed:'2026-08-18', status:'confirmed', mentions:2 }
    ] },
  { id:'m-winnipeg-mayor', city:'Winnipeg', prov:'MB', date:'2026-10-28', seat:'mayor',
    partisan:false, wards:15, pop:749607,
    cands:[
      { name:'S. Gillingham', party:NONPARTISAN, confirmed:'2026-06-09', status:'confirmed', inc:true, mentions:29 },
      { name:'K. Beaulieu', party:NONPARTISAN, confirmed:'2026-08-06', status:'confirmed', mentions:5 }
    ] },
  { id:'m-winnipeg-w07', city:'Winnipeg', prov:'MB', date:'2026-10-28', seat:'Ward 7 — Fort Rouge-East Fort Garry',
    partisan:false, pop:49900, cands:[] },
  { id:'m-surrey-mayor', city:'Surrey', prov:'BC', date:'2026-10-17', seat:'mayor',
    partisan:false, wards:0, pop:568322,
    cands:[
      { name:'B. Locke', party:NONPARTISAN, confirmed:'2026-07-12', status:'confirmed', inc:true, mentions:14 }
    ] },
  { id:'m-ottawa-mayor', city:'Ottawa', prov:'ON', date:'2026-10-26', seat:'mayor',
    partisan:false, wards:24, pop:1017449,
    cands:[
      { name:'M. Sutcliffe', party:NONPARTISAN, confirmed:'2026-06-16', status:'confirmed', inc:true, mentions:33 },
      { name:'C. McKenney', party:NONPARTISAN, confirmed:'2026-07-28', status:'confirmed', mentions:11 }
    ] },
  { id:'m-mississauga-mayor', city:'Mississauga', prov:'ON', date:'2026-10-26', seat:'mayor',
    partisan:false, wards:11, pop:717961,
    cands:[
      { name:'C. Parrish', party:NONPARTISAN, confirmed:'2026-08-03', status:'confirmed', inc:true, mentions:8 }
    ] },
  { id:'m-quebec-mayor', city:'Québec City', prov:'QC', date:'2026-11-01', seat:'mayor',
    partisan:false, wards:21, pop:549459,
    cands:[
      { name:'B. Marchand', party:NONPARTISAN, confirmed:'2026-06-05', status:'confirmed', inc:true, mentions:26 },
      { name:'C. Bélanger', party:NONPARTISAN, status:'declared', mentions:0 }
    ] },
  { id:'m-brampton-mayor', city:'Brampton', prov:'ON', date:'2026-10-26', seat:'mayor',
    partisan:false, wards:10, pop:656480, cands:[] },
  { id:'m-hamilton-mayor', city:'Hamilton', prov:'ON', date:'2026-10-26', seat:'mayor',
    partisan:false, wards:15, pop:569353,
    cands:[
      { name:'A. Horwath', party:NONPARTISAN, confirmed:'2026-07-20', status:'confirmed', inc:true, mentions:17 }
    ] },
  { id:'m-laval-mayor', city:'Laval', prov:'QC', date:'2026-11-01', seat:'mayor',
    partisan:false, wards:21, pop:438366, cands:[] },
  { id:'m-burnaby-mayor', city:'Burnaby', prov:'BC', date:'2026-10-17', seat:'mayor',
    partisan:false, wards:0, pop:249125,
    cands:[
      { name:'M. Hurley', party:NONPARTISAN, confirmed:'2026-08-10', status:'confirmed', inc:true, mentions:4 }
    ] }
];

const ALL_RACES = []
  .concat(FEDERAL_RACES.map(r => ({ ...r, level:'federal', date:'2029-10-15', seat:r.riding })))
  .concat(PROVINCIAL_RACES.map(r => ({ ...r, level:'provincial', date:'2026-10-05', seat:r.riding })))
  .concat(MUNICIPAL_RACES.map(r => ({ ...r, level:'municipal' })));


/* ── results ────────────────────────────────────────────────────────────
   A result is a count, not a narrative: winner, margin, turnout, and the
   coverage the race actually received. Margin is in points of the vote, so a
   two-point win and a forty-point win cannot look alike. */
const PAST_RACES = [
  { id:'p-calgary-mayor', level:'municipal', city:'Calgary', prov:'AB', date:'2025-10-20',
    seat:'mayor', partisan:false, pop:1306784,
    result:{ turnout:38.4, ballots:412800, winner:'J. Farkas', winnerParty:NONPARTISAN, margin:6.2,
      tally:[['J. Farkas',NONPARTISAN,41.3],['J. Gondek',NONPARTISAN,35.1],['B. Davison',NONPARTISAN,17.8],['Other',NONPARTISAN,5.8]] } },
  { id:'p-edmonton-mayor', level:'municipal', city:'Edmonton', prov:'AB', date:'2025-10-20',
    seat:'mayor', partisan:false, pop:1010899,
    result:{ turnout:33.1, ballots:274900, winner:'A. Sohi', winnerParty:NONPARTISAN, margin:11.4,
      tally:[['A. Sohi',NONPARTISAN,44.6],['T. Cartmell',NONPARTISAN,33.2],['M. Nickel',NONPARTISAN,15.9],['Other',NONPARTISAN,6.3]] } },
  { id:'p-edmonton-w08', level:'municipal', city:'Edmonton', prov:'AB', date:'2025-10-20',
    seat:'Ward papastew', partisan:false, pop:71400,
    result:{ turnout:29.7, ballots:16800, winner:'M. Janz', winnerParty:NONPARTISAN, margin:22.1,
      tally:[['M. Janz',NONPARTISAN,54.8],['S. Bhardwaj',NONPARTISAN,32.7],['Other',NONPARTISAN,12.5]] } },
  { id:'p-stjohns-mayor', level:'municipal', city:"St. John's", prov:'NL', date:'2025-09-25',
    seat:'mayor', partisan:false, pop:110525,
    result:{ turnout:41.2, ballots:31400, winner:'D. Breen', winnerParty:NONPARTISAN, margin:18.6,
      tally:[['D. Breen',NONPARTISAN,52.9],['S. Hickman',NONPARTISAN,34.3],['Other',NONPARTISAN,12.8]] } },
  { id:'p-nl-stjohns-east', level:'provincial', riding:'St. John\u2019s East\u2013Quidi Vidi', prov:'NL', date:'2025-10-14',
    seat:'St. John\u2019s East\u2013Quidi Vidi', pop:41200,
    result:{ turnout:52.8, ballots:14900, winner:'J. Dinn', winnerParty:'NDP', margin:9.3,
      tally:[['J. Dinn','NDP',42.1],['P. Lane','Liberal',32.8],['S. Mulrooney','PC',21.4],['Other','Independent',3.7] ] } },
  { id:'p-yt-whitehorse-centre', level:'provincial', riding:'Whitehorse Centre', prov:'YT', date:'2025-11-03',
    seat:'Whitehorse Centre', pop:2900,
    result:{ turnout:64.1, ballots:1740, winner:'E. White', winnerParty:'NDP', margin:14.7,
      tally:[['E. White','NDP',48.2],['M. Pemberton','Liberal',33.5],['R. Cathers','PC',16.1],['Other','Independent',2.2] ] } },
  { id:'p-fed-toronto-centre', level:'federal', riding:'Toronto Centre', prov:'ON', date:'2025-04-28',
    seat:'Toronto Centre', pop:112500,
    result:{ turnout:61.9, ballots:52100, winner:'Marci Ien', winnerParty:'Liberal', margin:24.8,
      tally:[['Marci Ien','Liberal',52.4],['D. Ashfield','Conservative',27.6],['S. Okonkwo','NDP',14.9],['Other','Green',5.1] ] } },
  { id:'p-fed-calgary-centre', level:'federal', riding:'Calgary Centre', prov:'AB', date:'2025-04-28',
    seat:'Calgary Centre', pop:107300,
    result:{ turnout:66.4, ballots:53800, winner:'Greg McLean', winnerParty:'Conservative', margin:17.2,
      tally:[['Greg McLean','Conservative',49.8],['A. Kaur','Liberal',32.6],['T. Whitecalf','NDP',14.1],['Other','Green',3.5] ] } }
];

/* ── deadlines ──────────────────────────────────────────────────────────
   For a reader the actionable date is rarely election day. For a newsroom,
   nomination close is when a slate becomes final and reportable. */
const DEADLINES = [
  { election:'Qu\u00e9bec general', level:'provincial', vote:'2026-10-05', items:[
    ['Nomination close', '2026-09-12', 'slate becomes final'],
    ['Register to vote', '2026-09-24', '\u00c9lections Qu\u00e9bec revision'],
    ['Advance voting', '2026-09-27', 'through 28 September'],
    ['Vote by mail request', '2026-09-22', 'application deadline'] ] },
  { election:'BC municipal', level:'municipal', vote:'2026-10-17', items:[
    ['Nomination period', '2026-09-08', 'opens; closes 18 September'],
    ['Advance voting', '2026-10-07', 'earliest permitted day'] ] },
  { election:'Ontario municipal', level:'municipal', vote:'2026-10-26', items:[
    ['Nomination close', '2026-08-21', 'already passed \u2014 slates are final'],
    ['Voters\u2019 list revision', '2026-10-13', 'add or correct'],
    ['Advance voting', '2026-10-10', 'set by each clerk'] ] },
  { election:'Manitoba municipal', level:'municipal', vote:'2026-10-28', items:[
    ['Nomination close', '2026-09-22', 'slate becomes final'],
    ['Advance voting', '2026-10-17', 'through 24 October'] ] },
  { election:'Qu\u00e9bec municipal', level:'municipal', vote:'2026-11-01', items:[
    ['Nomination close', '2026-10-02', 'slate becomes final'],
    ['Advance voting', '2026-10-25', '25 and 26 October'] ] }
];

/* ── turnout ────────────────────────────────────────────────────────────
   Municipal turnout runs roughly half the federal rate. Set beside a coverage
   count, that gap is the strongest case the site can make that thin local
   reporting has consequences. */
const TURNOUT = [
  { level:'Federal general', year:2025, pct:68.4, note:'343 ridings' },
  { level:'Provincial average', year:2025, pct:56.2, note:'across recent general elections' },
  { level:'Municipal \u2014 large cities', year:2025, pct:36.8, note:'population over 500,000' },
  { level:'Municipal \u2014 mid-size', year:2025, pct:31.4, note:'100,000 to 500,000' },
  { level:'Ward races', year:2025, pct:28.9, note:'single-ward councillor contests' }
];

/* ── coverage arc ───────────────────────────────────────────────────────
   The site's own argument applied to itself: did coverage follow the campaign,
   or the incumbent? Articles per week in the four weeks before a vote, the
   week of, and the four weeks after. */
const COVERAGE_ARC = [
  { city:'Calgary',      prov:'AB', vote:'2025-10-20', before:14, during:38, after:9,  turnout:38.4 },
  { city:'Edmonton',     prov:'AB', vote:'2025-10-20', before:11, during:29, after:7,  turnout:33.1 },
  { city:"St. John's",   prov:'NL', vote:'2025-09-25', before:6,  during:17, after:4,  turnout:41.2 },
  { city:'Lethbridge',   prov:'AB', vote:'2025-10-20', before:2,  during:5,  after:1,  turnout:27.6 },
  { city:'Red Deer',     prov:'AB', vote:'2025-10-20', before:1,  during:3,  after:0,  turnout:24.1 },
  { city:'Grande Prairie',prov:'AB',vote:'2025-10-20', before:0,  during:2,  after:0,  turnout:22.3 }
];


/* ── electors ───────────────────────────────────────────────────────────
   Turnout is a fraction, and this is its denominator. Published separately
   because the register grows every year: a rising vote count with a falling
   turnout rate is a real and easily-missed story. */
const ELECTORS_TREND = [
  { year:2015, reg:25939742, voted:17711983, pct:68.3 },
  { year:2019, reg:27373058, voted:18350359, pct:67.0 },
  { year:2021, reg:27366297, voted:17038368, pct:62.6 },
  { year:2025, reg:28529124, voted:19513922, pct:68.4 }
];
/* Registered electors by province at the last federal general, against
   population. The gap is unregistered eligible voters plus non-citizens. */
const ELECTORS_PROV = [
  { p:'ON', reg:11045000, pop:15996989 }, { p:'QC', reg:6431000, pop:9030684 },
  { p:'BC', reg:3823000, pop:5698977 },   { p:'AB', reg:3141000, pop:4849906 },
  { p:'MB', reg:920000,  pop:1484135 },   { p:'SK', reg:806000,  pop:1231043 },
  { p:'NS', reg:806000,  pop:1072545 },   { p:'NB', reg:625000,  pop:850894 },
  { p:'NL', reg:410000,  pop:541391 },    { p:'PE', reg:127000,  pop:177081 },
  { p:'YT', reg:31000,   pop:47141 },     { p:'NT', reg:31000,   pop:45074 },
  { p:'NU', reg:22000,   pop:41288 }
];

/* ── by-elections ───────────────────────────────────────────────────────
   A by-election is not a small general election. It is CALLED rather than
   fixed: when a seat falls vacant the Speaker notifies the Chief Electoral
   Officer, and the writ must issue between 11 and 180 days later — so the
   date is a government's discretion inside a legal window, which is itself
   worth reporting. Turnout typically runs 20–30 points below the general. */
const BYELECTION_LAW = {
  federal:'Canada Elections Act s.31 and s.57(1.1) — the writ must issue between 11 and 180 days after the Speaker reports the vacancy',
  provincial:'Provincial statutes vary; most set a 6-month outer limit',
  municipal:'Council may appoint or call a by-election, depending on how much of the term remains'
};
const BYELECTIONS = [
  { id:'b-fed-cloverdale', level:'federal', seat:'Cloverdale\u2014Langley City', prov:'BC',
    cause:'resignation', vacated:'2026-07-14', former:'A. Bhandari', formerParty:'Liberal',
    status:'pending', deadline:'2027-01-10', called:null,
    genTurnout:64.8, note:'Resigned to seek a provincial nomination.' },
  { id:'b-fed-lasalle', level:'federal', seat:'LaSalle\u2014\u00c9mard\u2014Verdun', prov:'QC',
    cause:'death', vacated:'2026-08-03', former:'M. Lapointe', formerParty:'Liberal',
    status:'pending', deadline:'2027-01-30', called:null,
    genTurnout:61.2, note:'Seat vacant since 3 August.' },
  { id:'b-fed-battle-river', level:'federal', seat:'Battle River\u2014Crowfoot', prov:'AB',
    cause:'resignation', vacated:'2026-06-02', former:'D. Kurek', formerParty:'Conservative',
    status:'scheduled', deadline:'2026-11-29', called:'2026-09-28',
    genTurnout:66.1, note:'Writ issued; candidates confirmed on the races page.' },
  { id:'b-prov-nb-fredericton', level:'provincial', seat:'Fredericton South\u2014Silverwood', prov:'NB',
    cause:'resignation', vacated:'2026-05-19', former:'D. Coon', formerParty:'Green',
    status:'held', held:'2026-08-25', turnout:31.4, genTurnout:58.7,
    winner:'S. Mitton', winnerParty:'Green', margin:8.9,
    note:'Held in August, mid-summer.' },
  { id:'b-mun-toronto-w19', level:'municipal', seat:'Toronto Ward 19 \u2014 Beaches-East York', prov:'ON',
    cause:'resignation', vacated:'2026-04-08', former:'B. Bradford', formerParty:NONPARTISAN,
    status:'held', held:'2026-06-16', turnout:16.8, genTurnout:38.2,
    winner:'L. Pham', winnerParty:NONPARTISAN, margin:4.2,
    note:'Council chose a by-election over appointment.' },
  { id:'b-mun-surrey-council', level:'municipal', seat:'Surrey council \u2014 one seat', prov:'BC',
    cause:'appointment to another office', vacated:'2026-07-22', former:'M. Nagra', formerParty:NONPARTISAN,
    status:'pending', deadline:'2027-01-18', called:null,
    genTurnout:33.5, note:'Under 12 months to the general election, so council may appoint instead.' }
];
