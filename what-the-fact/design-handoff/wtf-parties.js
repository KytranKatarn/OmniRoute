/* Political parties: 25 years of electoral record, leadership, and delivery.

   Two decisions shape this file.

   1. THERE IS NO GRADE. A party's record is reported as what it delivered,
      what it reversed, and what independent officers found — never as a score
      out of ten. "Good and bad portfolio" is rendered as two columns of cited
      facts, because a single grade would be this newsroom's opinion dressed as
      a measurement, and the site's whole premise is against that.
   2. SEAT COUNTS ARE NOT VOTE SHARES. Both are stored for every election,
      because the gap between them is the most under-reported fact in Canadian
      politics — 2011 and 2015 are both cases where a ~39% vote produced a
      majority government. */

const ELECTIONS_FED = [2000, 2004, 2006, 2008, 2011, 2015, 2019, 2021, 2025];

/* House size changed over the period, so a seat count alone is not comparable
   across rows. Stored so shares can be computed honestly. */
const HOUSE_SIZE = { 2000:301, 2004:308, 2006:308, 2008:308, 2011:308, 2015:338, 2019:338, 2021:338, 2025:343 };

const PARTIES = [
  /* ── federal ────────────────────────────────────────────────────────── */
  { id:'lib', name:'Liberal Party of Canada', short:'Liberal', level:'federal', col:'#d71920',
    founded:1867, status:'government',
    leaders:[['Jean Chrétien','1990–2003'],['Paul Martin','2003–2006'],['Stéphane Dion','2006–2008'],
      ['Michael Ignatieff','2008–2011'],['Bob Rae','2011–2013','interim'],['Justin Trudeau','2013–2025'],
      ['Mark Carney','2025–']],
    history:[
      { y:2000, seats:172, votes:40.8, outcome:'majority' },
      { y:2004, seats:135, votes:36.7, outcome:'minority' },
      { y:2006, seats:103, votes:30.2, outcome:'opposition' },
      { y:2008, seats:77,  votes:26.3, outcome:'opposition' },
      { y:2011, seats:34,  votes:18.9, outcome:'third' },
      { y:2015, seats:184, votes:39.5, outcome:'majority' },
      { y:2019, seats:157, votes:33.1, outcome:'minority' },
      { y:2021, seats:160, votes:32.6, outcome:'minority' },
      { y:2025, seats:171, votes:43.8, outcome:'minority' }
    ],
    delivered:[
      ['Canada Child Benefit', 2016, 'Replaced two prior benefits with an income-tested transfer; child poverty fell over the following four years.', 'legislation'],
      ['Cannabis legalisation', 2018, 'Cannabis Act came into force October 2018, as committed in 2015.', 'legislation'],
      ['$10-a-day early learning agreements', 2021, 'Bilateral agreements signed with all provinces and territories.', 'program'],
      ['Consumer carbon price removed', 2025, 'Fuel charge set to zero by order in council, as committed in the 2025 platform.', 'order']
    ],
    reversed:[
      ['Electoral reform', 2017, 'Committed in 2015 that 2015 would be the last first-past-the-post election. Abandoned in February 2017.', 'reversal'],
      ['Balanced budget by 2019', 2016, 'Committed to modest deficits returning to balance by 2019-20. No balanced budget was tabled.', 'budget'],
      ['Public service cap', null, 'Committed in 2025 to hold the public service at its current size. No cap instrument tabled; headcount up 1.2%.', 'none']
    ],
    findings:[
      ['Conflict of Interest and Ethics Commissioner', 2017, 'Found the Prime Minister contravened four sections of the Conflict of Interest Act over a private travel arrangement.', 'contravention'],
      ['Conflict of Interest and Ethics Commissioner', 2019, 'Found the Prime Minister improperly pressured the Attorney General in the SNC-Lavalin matter.', 'contravention'],
      ['Auditor General', 2024, 'Found ArriveCAN contracting failed to demonstrate value for money and lacked documentation.', 'audit']
    ] },

  { id:'cpc', name:'Conservative Party of Canada', short:'Conservative', level:'federal', col:'#1a4782',
    founded:2003, status:'opposition',
    note:'Formed in December 2003 by the merger of the Canadian Alliance and the Progressive Conservative Party.',
    leaders:[['Stephen Harper','2004–2015'],['Rona Ambrose','2015–2017','interim'],['Andrew Scheer','2017–2020'],
      ['Erin O\u2019Toole','2020–2022'],['Candice Bergen','2022','interim'],['Pierre Poilievre','2022–']],
    history:[
      { y:2004, seats:99,  votes:29.6, outcome:'opposition' },
      { y:2006, seats:124, votes:36.3, outcome:'minority' },
      { y:2008, seats:143, votes:37.7, outcome:'minority' },
      { y:2011, seats:166, votes:39.6, outcome:'majority' },
      { y:2015, seats:99,  votes:31.9, outcome:'opposition' },
      { y:2019, seats:121, votes:34.3, outcome:'opposition' },
      { y:2021, seats:119, votes:33.7, outcome:'opposition' },
      { y:2025, seats:139, votes:41.3, outcome:'opposition' }
    ],
    delivered:[
      ['GST cut to 5%', 2008, 'Reduced from 7% in two stages, as committed in 2006.', 'budget'],
      ['Federal Accountability Act', 2006, 'Passed in the first session after the 2006 election, as committed.', 'legislation'],
      ['Tax-Free Savings Account', 2009, 'Introduced in Budget 2008, effective 2009.', 'budget'],
      ['Long-gun registry abolished', 2012, 'Ending the Long-gun Registry Act passed April 2012, as committed since 2006.', 'legislation']
    ],
    reversed:[
      ['Income trust taxation', 2006, 'Committed in 2006 not to tax income trusts; taxed them in October 2006.', 'reversal'],
      ['Fixed election dates', 2008, 'Legislated fixed dates in 2007, then called an election in 2008 before the fixed date.', 'reversal'],
      ['Senate reform', 2015, 'Committed to an elected Senate across three mandates; no reform enacted before leaving office.', 'none']
    ],
    findings:[
      ['Chief Electoral Officer', 2011, 'The party pleaded guilty under the Elections Act over the 2006 advertising spending limit.', 'contravention'],
      ['Information Commissioner', 2014, 'Found systemic delays in access-to-information responses across departments.', 'audit'],
      ['Auditor General', 2012, 'Found the full cost of the F-35 procurement was not reported to Parliament.', 'audit']
    ] },

  { id:'ndp', name:'New Democratic Party', short:'NDP', level:'federal', col:'#f58220',
    founded:1961, status:'opposition',
    leaders:[['Alexa McDonough','1995–2003'],['Jack Layton','2003–2011'],['Nycole Turmel','2011–2012','interim'],
      ['Thomas Mulcair','2012–2017'],['Jagmeet Singh','2017–2025'],['Don Davies','2025–','interim']],
    history:[
      { y:2000, seats:13,  votes:8.5,  outcome:'fourth' },
      { y:2004, seats:19,  votes:15.7, outcome:'fourth' },
      { y:2006, seats:29,  votes:17.5, outcome:'fourth' },
      { y:2008, seats:37,  votes:18.2, outcome:'fourth' },
      { y:2011, seats:103, votes:30.6, outcome:'opposition' },
      { y:2015, seats:44,  votes:19.7, outcome:'third' },
      { y:2019, seats:24,  votes:15.9, outcome:'fourth' },
      { y:2021, seats:25,  votes:17.8, outcome:'fourth' },
      { y:2025, seats:5,   votes:6.4,  outcome:'fifth' }
    ],
    delivered:[
      ['Dental care programme', 2023, 'Secured through the confidence-and-supply agreement; Canadian Dental Care Plan launched 2023.', 'program'],
      ['Pharmacare framework legislation', 2024, 'Bill C-64 passed October 2024 covering contraception and diabetes medication.', 'legislation'],
      ['Anti-scab legislation', 2024, 'Bill C-58 banning replacement workers in federal sectors passed June 2024.', 'legislation']
    ],
    reversed:[
      ['Universal single-payer pharmacare', null, 'Committed since 2019 to full coverage. The 2024 Act covers two drug categories, not all prescriptions.', 'legislation'],
      ['Confidence-and-supply agreement', 2024, 'Committed to hold to 2025; withdrew in September 2024.', 'reversal']
    ],
    findings:[
      ['House of Commons Board of Internal Economy', 2014, 'Ordered repayment over satellite office expenses; the party contested the finding.', 'contravention']
    ] },

  { id:'bq', name:'Bloc Québécois', short:'Bloc', level:'federal', col:'#33b2cc',
    founded:1991, status:'opposition',
    leaders:[['Gilles Duceppe','1997–2011'],['Daniel Paillé','2011–2013'],['Mario Beaulieu','2014–2015'],
      ['Gilles Duceppe','2015','returned'],['Martine Ouellet','2017–2018'],['Yves-François Blanchet','2019–']],
    history:[
      { y:2000, seats:38, votes:10.7, outcome:'third' },
      { y:2004, seats:54, votes:12.4, outcome:'third' },
      { y:2006, seats:51, votes:10.5, outcome:'third' },
      { y:2008, seats:49, votes:10.0, outcome:'third' },
      { y:2011, seats:4,  votes:6.0,  outcome:'fifth' },
      { y:2015, seats:10, votes:4.7,  outcome:'fourth' },
      { y:2019, seats:32, votes:7.6,  outcome:'third' },
      { y:2021, seats:32, votes:7.6,  outcome:'third' },
      { y:2025, seats:21, votes:6.3,  outcome:'third' }
    ],
    delivered:[
      ['Québec as a nation motion', 2006, 'The House recognised the Québécois as a nation within a united Canada.', 'vote'],
      ['Supply management protected in trade law', 2024, 'Bill C-282 excluding supply-managed sectors from trade concessions passed the House.', 'legislation']
    ],
    reversed:[
      ['Sovereignty referendum', null, 'The party cannot hold one: a referendum is a provincial instrument. Recorded as a standing position, never a deliverable.', 'none']
    ],
    findings:[] },

  { id:'gpc', name:'Green Party of Canada', short:'Green', level:'federal', col:'#3d9b35',
    founded:1983, status:'opposition',
    leaders:[['Jim Harris','1997–2003'],['Jim Harris','2003–2006'],['Elizabeth May','2006–2019'],
      ['Annamie Paul','2020–2021'],['Elizabeth May','2022–','co-leader']],
    history:[
      { y:2000, seats:0, votes:0.8, outcome:'no seats' },
      { y:2004, seats:0, votes:4.3, outcome:'no seats' },
      { y:2006, seats:0, votes:4.5, outcome:'no seats' },
      { y:2008, seats:0, votes:6.8, outcome:'no seats' },
      { y:2011, seats:1, votes:3.9, outcome:'one seat' },
      { y:2015, seats:1, votes:3.4, outcome:'one seat' },
      { y:2019, seats:3, votes:6.5, outcome:'minor' },
      { y:2021, seats:2, votes:2.3, outcome:'minor' },
      { y:2025, seats:1, votes:1.2, outcome:'one seat' }
    ],
    delivered:[
      ['Environmental Bill of Rights tabled', 2019, 'Private member\u2019s bill C-438 tabled; did not proceed past first reading.', 'bill']
    ],
    reversed:[],
    findings:[] },

  /* ── provincial ─────────────────────────────────────────────────────── */
  { id:'caq', name:'Coalition Avenir Québec', short:'CAQ', level:'provincial', prov:'QC', col:'#00a0d2',
    founded:2011, status:'government',
    leaders:[['François Legault','2011–']],
    history:[
      { y:2012, seats:19, votes:27.1, outcome:'third' },
      { y:2014, seats:22, votes:23.1, outcome:'third' },
      { y:2018, seats:74, votes:37.4, outcome:'majority' },
      { y:2022, seats:90, votes:40.9, outcome:'majority' }
    ],
    delivered:[
      ['Hydro rate cap', 2023, 'Bill 2 capped residential increases at 3% a year.', 'legislation'],
      ['Immigration threshold at 50,000', 2024, 'Multi-year plan set and met.', 'program'],
      ['Pre-kindergarten expansion', 2021, 'Universal 4-year-old classes extended province-wide.', 'program']
    ],
    reversed:[
      ['Third link between Québec City and Lévis', 2023, 'Cancelled in April 2023, partially revived as a study; no construction contract before the mandate ended.', 'reversal'],
      ['Family doctor for every Quebecer', null, 'Access expanded through the guichet, but roughly 480,000 remain without a family doctor.', 'program']
    ],
    findings:[
      ['Commissaire à l\u2019éthique et à la déontologie', 2023, 'Found a minister contravened the code over a private interest; the minister resigned the portfolio.', 'contravention'],
      ['Vérificateur général du Québec', 2024, 'Found cost estimates for the tramway project were not reliably documented.', 'audit']
    ] },

  { id:'pq', name:'Parti Québécois', short:'PQ', level:'provincial', prov:'QC', col:'#004a8f',
    founded:1968, status:'opposition',
    leaders:[['Bernard Landry','2001–2005'],['André Boisclair','2005–2007'],['Pauline Marois','2007–2014'],
      ['Pierre Karl Péladeau','2015–2016'],['Jean-François Lisée','2016–2018'],
      ['Paul St-Pierre Plamondon','2020–']],
    history:[
      { y:2003, seats:45, votes:33.2, outcome:'opposition' },
      { y:2007, seats:36, votes:28.3, outcome:'third' },
      { y:2008, seats:51, votes:35.2, outcome:'opposition' },
      { y:2012, seats:54, votes:31.9, outcome:'minority' },
      { y:2014, seats:30, votes:25.4, outcome:'opposition' },
      { y:2018, seats:10, votes:17.1, outcome:'fourth' },
      { y:2022, seats:3,  votes:14.6, outcome:'fourth' }
    ],
    delivered:[
      ['$7-a-day childcare defended', 2013, 'Held the rate against indexation pressure during its minority mandate.', 'budget']
    ],
    reversed:[
      ['Charter of Values', 2014, 'Bill 60 died on the order paper when the 2014 election was called.', 'reversal'],
      ['Sovereignty referendum', null, 'Committed in successive platforms; none held since 1995.', 'none']
    ],
    findings:[] },

  { id:'qs', name:'Québec solidaire', short:'Québec solidaire', level:'provincial', prov:'QC', col:'#ff5605',
    founded:2006, status:'opposition',
    leaders:[['Françoise David','2006–2017','co-spokesperson'],['Manon Massé','2017–','co-spokesperson'],
      ['Gabriel Nadeau-Dubois','2019–2025','co-spokesperson'],['Ruba Ghazal','2025–','co-spokesperson']],
    history:[
      { y:2008, seats:0,  votes:3.8,  outcome:'no seats' },
      { y:2012, seats:2,  votes:6.0,  outcome:'minor' },
      { y:2014, seats:3,  votes:7.6,  outcome:'minor' },
      { y:2018, seats:10, votes:16.1, outcome:'fourth' },
      { y:2022, seats:11, votes:15.4, outcome:'third' }
    ],
    delivered:[],
    reversed:[],
    findings:[] },

  { id:'onpc', name:'Progressive Conservative Party of Ontario', short:'ON PC', level:'provincial', prov:'ON', col:'#1a4782',
    founded:1854, status:'government',
    leaders:[['Ernie Eves','2002–2004'],['John Tory','2004–2009'],['Tim Hudak','2009–2015'],
      ['Patrick Brown','2015–2018'],['Doug Ford','2018–']],
    history:[
      { y:2003, seats:24, votes:34.6, outcome:'opposition' },
      { y:2007, seats:26, votes:31.6, outcome:'opposition' },
      { y:2011, seats:37, votes:35.4, outcome:'opposition' },
      { y:2014, seats:28, votes:31.2, outcome:'opposition' },
      { y:2018, seats:76, votes:40.5, outcome:'majority' },
      { y:2022, seats:83, votes:40.8, outcome:'majority' },
      { y:2025, seats:80, votes:43.0, outcome:'majority' }
    ],
    delivered:[
      ['Gas tax cut made permanent', 2025, 'Legislated in the 2025 Ontario budget.', 'budget'],
      ['Licence plate renewal fees eliminated', 2022, 'Fees removed and prior charges refunded.', 'legislation']
    ],
    reversed:[
      ['Greenbelt land removals', 2023, 'Reversed after the Auditor General and Integrity Commissioner reported on the process.', 'reversal'],
      ['Highway 413 timeline', null, 'Committed to shovels in the ground by 2025; early works began but the corridor is not under construction.', 'program']
    ],
    findings:[
      ['Auditor General of Ontario', 2023, 'Found the Greenbelt land removal process favoured certain developers and was not transparent.', 'audit'],
      ['Integrity Commissioner of Ontario', 2023, 'Found the Housing Minister\u2019s office controlled the selection process improperly; the minister resigned.', 'contravention'],
      ['Auditor General of Ontario', 2021, 'Found long-term care inspection had declined ahead of the pandemic.', 'audit']
    ] },

  { id:'bcndp', name:'British Columbia New Democratic Party', short:'BC NDP', level:'provincial', prov:'BC', col:'#f58220',
    founded:1933, status:'government',
    leaders:[['Ujjal Dosanjh','2000–2001'],['Joy MacPhail','2001–2003','interim'],['Carole James','2003–2011'],
      ['Adrian Dix','2011–2014'],['John Horgan','2014–2022'],['David Eby','2022–']],
    history:[
      { y:2001, seats:2,  votes:21.6, outcome:'two seats' },
      { y:2005, seats:33, votes:41.5, outcome:'opposition' },
      { y:2009, seats:35, votes:42.1, outcome:'opposition' },
      { y:2013, seats:34, votes:39.7, outcome:'opposition' },
      { y:2017, seats:41, votes:40.3, outcome:'minority' },
      { y:2020, seats:57, votes:47.7, outcome:'majority' },
      { y:2024, seats:47, votes:44.9, outcome:'majority' }
    ],
    delivered:[
      ['MSP premiums eliminated', 2020, 'Medical Services Plan premiums removed as committed in 2017.', 'budget'],
      ['$10-a-day childcare sites', 2023, 'Expanded to over 14,000 spaces.', 'program']
    ],
    reversed:[
      ['Decriminalisation of personal drug possession', 2024, 'Sought and received a federal amendment recriminalising public use, reversing the 2023 exemption.', 'reversal'],
      ['300,000 homes in ten years', null, 'BC Builds funded; 4,900 units under construction against a 30,000-a-year pace.', 'budget']
    ],
    findings:[
      ['Auditor General of British Columbia', 2023, 'Found housing delivery reporting did not allow progress to be verified.', 'audit']
    ] },

  { id:'ucp', name:'United Conservative Party', short:'UCP', level:'provincial', prov:'AB', col:'#1a4782',
    founded:2017, status:'government',
    note:'Formed in 2017 by the merger of the Progressive Conservative Association of Alberta and the Wildrose Party.',
    leaders:[['Jason Kenney','2017–2022'],['Danielle Smith','2022–']],
    history:[
      { y:2019, seats:63, votes:54.9, outcome:'majority' },
      { y:2023, seats:49, votes:52.6, outcome:'majority' }
    ],
    delivered:[
      ['Taxpayer Protection Act amendment', 2023, 'Personal income tax increases now require a referendum.', 'legislation'],
      ['Lowest bracket cut to 8%', 2026, 'Delivered in Budget 2026, two years later than the stated timeline.', 'budget']
    ],
    reversed:[
      ['Alberta Pension Plan', null, 'Committed to a referendum on withdrawal from CPP; none held.', 'none'],
      ['Balanced budget legislation', null, 'Committed in 2019; no binding instrument enacted.', 'none']
    ],
    findings:[
      ['Ethics Commissioner of Alberta', 2023, 'Found the Premier contravened the Conflict of Interest Act by discussing a criminal case with the Justice Minister.', 'contravention'],
      ['Auditor General of Alberta', 2024, 'Found procurement in Alberta Health Services lacked documented justification.', 'audit']
    ] },

  /* ── municipal ──────────────────────────────────────────────────────── */
  { id:'projet', name:'Projet Montréal', short:'Projet Montréal', level:'municipal', city:'Montréal', col:'#00a693',
    founded:2004, status:'government',
    leaders:[['Richard Bergeron','2004–2014'],['Luc Ferrandez','2014–2016','interim'],['Valérie Plante','2016–']],
    history:[
      { y:2005, seats:1,  votes:3.6,  outcome:'one seat' },
      { y:2009, seats:14, votes:25.4, outcome:'opposition' },
      { y:2013, seats:20, votes:26.5, outcome:'opposition' },
      { y:2017, seats:34, votes:51.4, outcome:'majority' },
      { y:2021, seats:37, votes:52.1, outcome:'majority' }
    ],
    delivered:[
      ['Réseau express vélo, 200 km', 2025, '214 km added; the network passed the target.', 'program'],
      ['Rent registry bylaw', 2023, 'Landlords required to disclose prior rent on new leases.', 'bylaw']
    ],
    reversed:[
      ['500,000 trees', null, '285,000 planted by mid-2026, roughly 57% of target with the mandate ending.', 'program'],
      ['Pink metro line', null, 'Central 2017 commitment; superseded by the provincially-led REM de l\u2019Est, itself cancelled in 2023.', 'reversal']
    ],
    findings:[
      ['Bureau de l\u2019inspecteur général', 2022, 'Found procurement irregularities in a borough contract; the contract was cancelled.', 'audit']
    ] },

  { id:'abc', name:'ABC Vancouver', short:'ABC Vancouver', level:'municipal', city:'Vancouver', col:'#0b5ea8',
    founded:2022, status:'government',
    leaders:[['Ken Sim','2022–']],
    history:[
      { y:2022, seats:8, votes:36.7, outcome:'majority' }
    ],
    delivered:[
      ['100 new police officers', 2023, 'Funded in the 2023 budget and hired.', 'budget'],
      ['Permitting reform for small businesses', 2024, 'Single-window permitting introduced.', 'bylaw']
    ],
    reversed:[
      ['100 mental health nurses', null, '58 of 100 positions filled.', 'budget'],
      ['3,000 rental permits a year', null, '2,410 in 2025, the highest of the mandate but below target.', 'program']
    ],
    findings:[] },

  { id:'chow', name:'Toronto — Chow administration', short:'Toronto — Chow', level:'municipal', city:'Toronto', col:'#8a94a3',
    founded:2023, status:'government', nonpartisan:true,
    note:'Toronto has no municipal parties. This is a mayoral administration, tracked as the platform that won the 2023 by-election.',
    leaders:[['Olivia Chow','2023–']],
    history:[
      { y:2023, seats:1, votes:37.2, outcome:'mayoralty' }
    ],
    delivered:[
      ['Renters\u2019 Action Committee', 2024, 'Established with a dedicated municipal tenant support office.', 'bylaw']
    ],
    reversed:[
      ['Property tax at inflation', 2024, '2024 budget raised residential rates 9.5% plus a city-building levy.', 'budget'],
      ['25,000 rent-controlled homes by 2030', null, '6,300 approved, 1,100 under construction.', 'program']
    ],
    findings:[
      ['Auditor General of Toronto', 2025, 'Found shelter capacity reporting understated demand.', 'audit']
    ] }
];

/* Outcome ranking, for the 25-year record chart. Government is not "better"
   than opposition as a value judgement — it is what determines whether a
   commitment on the same page could have been delivered at all. */
const OUTCOME = {
  majority:    { l:'Majority government', c:'#10b981', gov:true },
  minority:    { l:'Minority government', c:'#7fa3cf', gov:true },
  mayoralty:   { l:'Won the mayoralty',   c:'#10b981', gov:true },
  opposition:  { l:'Official Opposition', c:'#f59e0b', gov:false },
  third:       { l:'Third party',         c:'#cf8b80', gov:false },
  fourth:      { l:'Fourth party',        c:'#a78bfa', gov:false },
  fifth:       { l:'Fifth party',         c:'#7d8590', gov:false },
  minor:       { l:'Minor party',         c:'#7d8590', gov:false },
  'one seat':  { l:'One seat',            c:'#7d8590', gov:false },
  'two seats': { l:'Two seats',           c:'#7d8590', gov:false },
  'no seats':  { l:'No seats',            c:'#4d5766', gov:false }
};

const FINDING_KIND = {
  contravention: { l:'Contravention found', c:'#e05252' },
  audit:         { l:'Audit finding',       c:'#f59e0b' }
};
