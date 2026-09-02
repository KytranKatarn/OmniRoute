/* Party platforms and commitment tracking.

   A promise tracker is a verdict machine pointed at politicians, so it needs
   the same discipline as V.E.R.I.F.Y. Four rules hold throughout:

   1. A COMMITMENT IS A QUOTE WITH A SOURCE. Every entry cites the platform
      document, its section, and the date. Nothing is tracked from a media
      characterisation of what a party "essentially promised".
   2. "NOT DONE YET" IS NOT "BROKEN". This is the failure mode of almost every
      promise tracker. A commitment inside its mandate window with no movement
      is `stalled`; only an explicit reversal, cancellation, or a mandate that
      has ended without delivery is `broken`. The two are never merged, and the
      remaining mandate time is shown beside every unfinished item.
   3. A PARTY OUT OF POWER CANNOT DELIVER. Opposition commitments are tracked as
      POSITIONS, not as delivery, and are never scored against a party in
      government. Scoring an opposition party's "kept" rate would be
      meaningless and would flatter whoever is out of office.
   4. EVERY STATUS NEEDS EVIDENCE. A bill number, an order-in-council, a budget
      line, a signed agreement, or a public reversal. `verdict` without
      `evidence` is not renderable. */

const PROMISE_STATUS = {
  kept:        { l:'Kept',         c:'#10b981', def:'Delivered as stated, with a document to point at.' },
  partial:     { l:'Partly kept',  c:'#7fa3cf', def:'Delivered in weaker or narrower form than the commitment stated.' },
  progress:    { l:'In progress',  c:'#f59e0b', def:'Legislation or funding is moving and the mandate has not ended.' },
  stalled:     { l:'Stalled',      c:'#cf8b80', def:'No measurable movement, but the mandate has not ended. Not the same as broken.' },
  broken:      { l:'Broken',       c:'#e05252', def:'Explicitly reversed or cancelled, or the mandate ended without delivery.' },
  notstarted:  { l:'Not started',  c:'#7d8590', def:'Nothing filed yet. Early in a mandate this is normal.' },
  position:    { l:'Position',     c:'#a78bfa', def:'Held by a party not in government, which cannot deliver it. Not scored.' }
};

/* Only these statuses count toward a delivery record. A position is excluded
   by definition, and "not started" is excluded early in a mandate. */
const SCORED = ['kept', 'partial', 'progress', 'stalled', 'broken'];

const PARTY_META = {
  /* federal */
  'Liberal':      { id:'lib', col:'#d71920', level:'federal', power:true,  mandate:['2025-04-28','2029-10-15'], seats:171 },
  'Conservative': { id:'cpc', col:'#1a4782', level:'federal', power:false, mandate:['2025-04-28','2029-10-15'], seats:139 },
  'Bloc':         { id:'bq', col:'#33b2cc', level:'federal', power:false, mandate:['2025-04-28','2029-10-15'], seats:21 },
  'NDP':          { id:'ndp', col:'#f58220', level:'federal', power:false, mandate:['2025-04-28','2029-10-15'], seats:5 },
  /* provincial */
  'CAQ':          { id:'caq', col:'#00a0d2', level:'provincial', prov:'QC', power:true,  mandate:['2022-10-03','2026-10-05'], seats:90 },
  'PQ':           { id:'pq', col:'#004a8f', level:'provincial', prov:'QC', power:false, mandate:['2022-10-03','2026-10-05'], seats:4 },
  'Québec solidaire': { id:'qs', col:'#ff5605', level:'provincial', prov:'QC', power:false, mandate:['2022-10-03','2026-10-05'], seats:11 },
  'BC NDP':       { id:'bcndp', col:'#f58220', level:'provincial', prov:'BC', power:true,  mandate:['2024-10-19','2028-10-21'], seats:47 },
  'UCP':          { id:'ucp', col:'#1a4782', level:'provincial', prov:'AB', power:true,  mandate:['2023-05-29','2027-10-18'], seats:49 },
  'ON PC':        { id:'onpc', col:'#1a4782', level:'provincial', prov:'ON', power:true,  mandate:['2025-02-27','2029-06-07'], seats:80 },
  /* municipal — mostly no party, so the "party" is the mayoralty itself */
  'Toronto — Chow':      { id:'chow', col:'#8a94a3', level:'municipal', city:'Toronto',   power:true, mandate:['2023-06-26','2026-10-26'], nonpartisan:true },
  'Projet Montréal':     { id:'projet', col:'#00a693', level:'municipal', city:'Montréal',  power:true, mandate:['2021-11-07','2026-11-01'] },
  'ABC Vancouver':       { id:'abc', col:'#0b5ea8', level:'municipal', city:'Vancouver', power:true, mandate:['2022-10-15','2026-10-17'] },
  'Calgary — Gondek':    { id:'gondek', col:'#8a94a3', level:'municipal', city:'Calgary',   power:false, mandate:['2021-10-18','2025-10-20'], nonpartisan:true, past:true }
};

/* Commitments. `text` is the commitment as the platform states it; `source`
   names the document so a reader can check the wording themselves. */
const PROMISES = [
  /* ── federal, in government ─────────────────────────────────────────── */
  { party:'Liberal', text:'Double the pace of housing construction to nearly 500,000 new homes a year.',
    source:'Liberal platform 2025, Housing', made:'2025-03-24', theme:'Housing',
    status:'progress', evidence:'Build Canada Homes announced; starts up 4% year over year, far below the pace required.',
    evidenceType:'program', checked:'2026-08-28' },
  { party:'Liberal', text:'Cut the middle-class income tax rate by one percentage point.',
    source:'Liberal platform 2025, Affordability', made:'2025-03-24', theme:'Taxes',
    status:'kept', evidence:'Enacted in the 2025 budget implementation act, effective 1 July 2025.',
    evidenceType:'legislation', checked:'2026-08-28' },
  { party:'Liberal', text:'Remove the consumer carbon price.',
    source:'Liberal platform 2025, Climate', made:'2025-03-24', theme:'Climate',
    status:'kept', evidence:'Consumer fuel charge set to zero by order in council, 14 March 2025.',
    evidenceType:'order', checked:'2026-08-28' },
  { party:'Liberal', text:'Meet the NATO defence spending target of two percent of GDP by 2030.',
    source:'Liberal platform 2025, Defence', made:'2025-03-24', theme:'Defence',
    status:'progress', evidence:'Budget 2026 sets a path to 2.0% by 2030-31; current spending is 1.76%.',
    evidenceType:'budget', checked:'2026-08-28' },
  { party:'Liberal', text:'Cap the public service at its current size while eliminating duplication.',
    source:'Liberal platform 2025, Government spending', made:'2025-03-24', theme:'Spending',
    status:'stalled', evidence:'No cap instrument tabled. Headcount is up 1.2% since the commitment was made.',
    evidenceType:'none', checked:'2026-08-28' },
  { party:'Liberal', text:'Build one Canadian economy out of thirteen by removing federal barriers to internal trade.',
    source:'Liberal platform 2025, Economy', made:'2025-03-24', theme:'Economy',
    status:'partial', evidence:'One Canadian Economy Act passed June 2025; mutual recognition covers some sectors, not all.',
    evidenceType:'legislation', checked:'2026-08-28' },

  /* ── federal, opposition: POSITIONS, not delivery ───────────────────── */
  { party:'Conservative', text:'Repeal the industrial carbon price and end federal emissions pricing entirely.',
    source:'Conservative platform 2025, Energy', made:'2025-04-08', theme:'Climate',
    status:'position', evidence:'Not in government. Voted against the retained industrial price in June 2025.',
    evidenceType:'vote', checked:'2026-08-28' },
  { party:'Conservative', text:'Tie federal infrastructure funding to municipal housing starts.',
    source:'Conservative platform 2025, Housing', made:'2025-04-08', theme:'Housing',
    status:'position', evidence:'Not in government. Tabled as a private member\u2019s motion, defeated.',
    evidenceType:'vote', checked:'2026-08-28' },
  { party:'NDP', text:'Establish universal single-payer pharmacare covering all prescription medication.',
    source:'NDP platform 2025, Health', made:'2025-04-02', theme:'Health',
    status:'position', evidence:'Not in government. Supported Bill C-22 at second reading.',
    evidenceType:'vote', checked:'2026-08-28' },
  { party:'Bloc', text:'Transfer full immigration selection powers to Qu\u00e9bec.',
    source:'Bloc platform 2025, Immigration', made:'2025-04-05', theme:'Immigration',
    status:'position', evidence:'Not in government. Motion adopted by the House in 2025 but non-binding.',
    evidenceType:'vote', checked:'2026-08-28' },

  /* ── provincial: Québec, mandate ends in weeks ──────────────────────── */
  { party:'CAQ', text:'Build a third road link between Qu\u00e9bec City and L\u00e9vis.',
    source:'CAQ platform 2022, Transport', made:'2022-09-12', theme:'Transport',
    status:'broken', evidence:'Cancelled April 2023, partially revived as a study in 2024, no construction contract awarded before the mandate ended.',
    evidenceType:'reversal', checked:'2026-08-30' },
  { party:'CAQ', text:'Cap annual increases to Hydro-Qu\u00e9bec residential rates at three percent.',
    source:'CAQ platform 2022, Affordability', made:'2022-09-12', theme:'Energy',
    status:'kept', evidence:'Legislated in Bill 2 (2023); residential increases held to 3% or less each year since.',
    evidenceType:'legislation', checked:'2026-08-30' },
  { party:'CAQ', text:'Add 3,000 family doctors and give every Quebecer access to a front-line clinician.',
    source:'CAQ platform 2022, Health', made:'2022-09-12', theme:'Health',
    status:'partial', evidence:'Guichet d\u2019acc\u00e8s expanded to cover most of the population; roughly 480,000 remain without a family doctor.',
    evidenceType:'program', checked:'2026-08-30' },
  { party:'CAQ', text:'Reduce immigration thresholds to 50,000 permanent admissions a year.',
    source:'CAQ platform 2022, Immigration', made:'2022-09-12', theme:'Immigration',
    status:'kept', evidence:'2024\u201326 plan set at 50,000; met in both years.',
    evidenceType:'program', checked:'2026-08-30' },
  { party:'CAQ', text:'Deliver the Qu\u00e9bec City tramway.',
    source:'CAQ platform 2022, Transport', made:'2022-09-12', theme:'Transport',
    status:'progress', evidence:'Mandate transferred to CDPQ Infra in 2024; construction start now scheduled beyond this mandate.',
    evidenceType:'program', checked:'2026-08-30' },
  { party:'Québec solidaire', text:'Introduce free public transit for students and seniors province-wide.',
    source:'QS platform 2022, Transport', made:'2022-09-01', theme:'Transport',
    status:'position', evidence:'Not in government. Bill 894 tabled, not called for debate.',
    evidenceType:'bill', checked:'2026-08-30' },
  { party:'PQ', text:'Hold a referendum on sovereignty in a first mandate.',
    source:'PQ platform 2022, Constitution', made:'2022-09-05', theme:'Constitution',
    status:'position', evidence:'Not in government. Restated as a 2026 platform commitment.',
    evidenceType:'none', checked:'2026-08-30' },

  /* ── provincial: other governments ──────────────────────────────────── */
  { party:'BC NDP', text:'Deliver 300,000 new homes over ten years through BC Builds and related programs.',
    source:'BC NDP platform 2024, Housing', made:'2024-09-21', theme:'Housing',
    status:'progress', evidence:'BC Builds funded in Budget 2025; 4,900 units under construction against a 30,000-a-year pace.',
    evidenceType:'budget', checked:'2026-08-25' },
  { party:'BC NDP', text:'Open a new urgent and primary care centre in every regional health authority.',
    source:'BC NDP platform 2024, Health', made:'2024-09-21', theme:'Health',
    status:'partial', evidence:'Opened in four of five authorities; Northern Health outstanding.',
    evidenceType:'program', checked:'2026-08-25' },
  { party:'UCP', text:'Legislate that provincial personal income tax rates cannot rise without a referendum.',
    source:'UCP platform 2023, Taxes', made:'2023-05-01', theme:'Taxes',
    status:'kept', evidence:'Alberta Taxpayer Protection Amendment Act passed 2023.',
    evidenceType:'legislation', checked:'2026-08-25' },
  { party:'UCP', text:'Cut the lowest personal income tax bracket to eight percent.',
    source:'UCP platform 2023, Taxes', made:'2023-05-01', theme:'Taxes',
    status:'partial', evidence:'Reduced to 8% in Budget 2026, two years later than the stated timeline.',
    evidenceType:'budget', checked:'2026-08-25' },
  { party:'ON PC', text:'Build Highway 413 and the Bradford Bypass.',
    source:'ON PC platform 2025, Transport', made:'2025-02-01', theme:'Transport',
    status:'progress', evidence:'Early works contracts awarded 2025; federal environmental review concluded.',
    evidenceType:'program', checked:'2026-08-25' },
  { party:'ON PC', text:'Keep the gas tax cut in place permanently.',
    source:'ON PC platform 2025, Affordability', made:'2025-02-01', theme:'Taxes',
    status:'kept', evidence:'Made permanent in the 2025 Ontario budget.',
    evidenceType:'budget', checked:'2026-08-25' },

  /* ── municipal ──────────────────────────────────────────────────────── */
  { party:'Toronto — Chow', text:'Build 25,000 rent-controlled homes on city-owned land by 2030.',
    source:'Mayoral platform 2023, Housing', made:'2023-05-15', theme:'Housing',
    status:'progress', evidence:'Housing Action Plan adopted; 6,300 units approved, 1,100 under construction.',
    evidenceType:'program', checked:'2026-08-20' },
  { party:'Toronto — Chow', text:'Restore the 2019 level of TTC service.',
    source:'Mayoral platform 2023, Transit', made:'2023-05-15', theme:'Transit',
    status:'partial', evidence:'Service hours restored to 96% of 2019; overnight network still reduced.',
    evidenceType:'program', checked:'2026-08-20' },
  { party:'Toronto — Chow', text:'Hold the residential property tax increase to inflation.',
    source:'Mayoral platform 2023, Budget', made:'2023-05-15', theme:'Taxes',
    status:'broken', evidence:'2024 budget raised residential rates 9.5%, well above inflation, alongside a new city-building levy.',
    evidenceType:'budget', checked:'2026-08-20' },
  { party:'Projet Montréal', text:'Plant 500,000 trees across the city.',
    source:'Projet Montr\u00e9al platform 2021, Environment', made:'2021-09-15', theme:'Environment',
    status:'partial', evidence:'285,000 planted by mid-2026, roughly 57% of target with the mandate ending.',
    evidenceType:'program', checked:'2026-08-20' },
  { party:'Projet Montréal', text:'Add 200 kilometres to the R\u00e9seau express v\u00e9lo.',
    source:'Projet Montr\u00e9al platform 2021, Transport', made:'2021-09-15', theme:'Transit',
    status:'kept', evidence:'214 km added; network passed the target in 2025.',
    evidenceType:'program', checked:'2026-08-20' },
  { party:'ABC Vancouver', text:'Hire 100 new police officers and 100 mental health nurses.',
    source:'ABC platform 2022, Safety', made:'2022-09-20', theme:'Safety',
    status:'partial', evidence:'100 officers funded and hired; 58 of 100 nurse positions filled.',
    evidenceType:'budget', checked:'2026-08-20' },
  { party:'ABC Vancouver', text:'Approve permits for 3,000 new rental units a year.',
    source:'ABC platform 2022, Housing', made:'2022-09-20', theme:'Housing',
    status:'progress', evidence:'2,410 permits in 2025, the highest of the mandate but below target.',
    evidenceType:'program', checked:'2026-08-20' },

  /* ── a completed mandate, so the record is closed ───────────────────── */
  { party:'Calgary — Gondek', text:'Declare a climate emergency and fund a citywide climate strategy.',
    source:'Mayoral platform 2021, Climate', made:'2021-09-20', theme:'Climate',
    status:'kept', evidence:'Declared November 2021; strategy funded at $87M over the term.',
    evidenceType:'program', checked:'2025-10-21' },
  { party:'Calgary — Gondek', text:'Remove single-family-only zoning citywide.',
    source:'Mayoral platform 2021, Housing', made:'2021-09-20', theme:'Housing',
    status:'kept', evidence:'Blanket rezoning approved May 2024 after public hearings.',
    evidenceType:'bylaw', checked:'2025-10-21' },
  { party:'Calgary — Gondek', text:'Hold property tax increases below three percent annually.',
    source:'Mayoral platform 2021, Budget', made:'2021-09-20', theme:'Taxes',
    status:'broken', evidence:'Increases of 4.4%, 7.8% and 3.6% over the term; mandate ended without the commitment met.',
    evidenceType:'budget', checked:'2025-10-21' }
];
