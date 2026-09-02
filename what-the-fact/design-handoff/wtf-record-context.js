/* Context for party record entries.

   Keyed `partyId|entry title`. A record line says what happened; this says
   what it meant, what the mechanism was, and where the reader can check.

   Rule: an entry with no context here renders with no expander. Nothing is
   padded to make the interface look complete — a missing explanation is
   better than an invented one. */

const RECORD_CONTEXT = {

  /* ── Liberal ───────────────────────────────────────────────────────── */
  'lib|Canada Child Benefit': {
    context:'Replaced the Canada Child Tax Benefit and the Universal Child Care Benefit with a single income-tested, non-taxable monthly transfer. Because it phases out with income, it moved money toward lower-income families rather than distributing it evenly, which is why its effect on child poverty was measurable within a few years. It is indexed to inflation, so it did not erode the way its predecessors had.',
    caveat:'Indexation was itself a later decision, not part of the original design.',
    source:'Budget Implementation Act 2016, Part 1' },
  'lib|Cannabis legalisation': {
    context:'The Cannabis Act created a federal licensing and quality framework while leaving retail distribution to the provinces, which is why availability and pricing still differ sharply by province. Legalisation was a 2015 platform commitment and came into force in October 2018, roughly a year later than the government first signalled.',
    caveat:'Pardons and record expungement for prior simple possession were handled separately and more slowly.',
    source:'Cannabis Act, S.C. 2018, c. 16' },
  'lib|$10-a-day early learning agreements': {
    context:'Delivered as bilateral agreements rather than a national programme, meaning each province negotiated its own targets and timelines. Every province and territory signed. The federal government funds; the provinces deliver, so fee reductions arrived at different times and space creation has lagged fee reduction almost everywhere.',
    caveat:'A fee cut without new spaces reduces cost for families who already have a spot and does nothing for those on a waitlist.',
    source:'Canada-wide Early Learning and Child Care agreements' },
  'lib|Consumer carbon price removed': {
    context:'The consumer fuel charge was set to zero by order in council, which is why it took effect in weeks rather than requiring legislation. The industrial carbon price was retained, so the policy was narrowed rather than repealed. The associated rebate ended with the charge, which for lower-income households in backstop provinces meant losing a payment as well as a cost.',
    caveat:'Whether the net effect on a given household was positive depends on their fuel use relative to the rebate they had been receiving.',
    source:'Order in Council, 14 March 2025' },
  'lib|Electoral reform': {
    context:'The 2015 platform stated that 2015 would be the last election held under first-past-the-post. A special committee reported in December 2016 recommending a referendum on a proportional system. In February 2017 the mandate letter commitment was withdrawn, with the government citing a lack of consensus. No alternative was put to voters.',
    caveat:'This is recorded as reversed rather than stalled because the commitment was explicitly abandoned by the government that made it.',
    source:'Special Committee on Electoral Reform, final report; Minister of Democratic Institutions mandate letter, Feb 2017' },
  'lib|Balanced budget by 2019': {
    context:'The 2015 platform committed to deficits of roughly $10B for three years, returning to balance in 2019-20. The first deficit was larger than projected and no budget since has projected a return to balance. The pandemic changed the fiscal picture from 2020 onward, but the commitment had already been missed by then.',
    caveat:'The pre-2020 miss and the post-2020 fiscal situation are different facts and should not be merged into one excuse or one indictment.',
    source:'Budget 2016 through Budget 2019 fiscal tables' },
  'lib|Public service cap': {
    context:'The 2025 platform committed to capping the public service at its then-current size while eliminating duplication. No cap instrument — legislative, regulatory, or a directive to Treasury Board — has been tabled. Headcount has risen 1.2% since the commitment was made.',
    caveat:'The mandate runs to 2029, so this is stalled rather than broken: there is time, and no reversal has been announced.',
    source:'no instrument on file' },
  'lib|Conflict of Interest and Ethics Commissioner': {
    context:'The 2017 report found the Prime Minister contravened four sections of the Conflict of Interest Act by accepting private travel and hospitality from a person with dealings with the government. The 2019 report found he improperly sought to influence the Attorney General regarding a prosecution. Neither carried a penalty: the Commissioner can find a contravention and publish, and nothing more.',
    caveat:'A contravention of the Act is not a criminal finding. The Commissioner has no power to fine, sanction or remove.',
    source:'Trudeau Report (2017); Trudeau II Report (2019)' },
  'lib|Auditor General': {
    context:'The 2024 ArriveCAN audit found the application cost roughly $59.5M with documentation so poor that the true figure could not be established. The Auditor General reported that contracting rules were disregarded and that the government could not demonstrate value for money. The RCMP subsequently opened an investigation into related contracting.',
    caveat:'The audit concerns procurement process and documentation, not the app\u2019s public health function.',
    source:'Office of the Auditor General, Report 1, February 2024' },

  /* ── Conservative ──────────────────────────────────────────────────── */
  'cpc|GST cut to 5%': {
    context:'Reduced from 7% to 6% in July 2006 and to 5% in January 2008, delivering the headline commitment of the 2006 platform in full and early. Most economists at the time argued an income tax cut of equivalent cost would have done more for growth, but the commitment as stated was met.',
    caveat:'Delivered as promised is a separate question from whether it was the best available policy.',
    source:'Budget 2006; Budget 2007 implementation acts' },
  'cpc|Federal Accountability Act': {
    context:'Passed in the first session after the 2006 election. It banned corporate and union political donations, capped individual contributions, created the Parliamentary Budget Officer, and strengthened the lobbying regime. The PBO in particular has since produced costings that have repeatedly embarrassed successive governments, including the one that created it.',
    caveat:'The PBO was initially placed within the Library of Parliament rather than made a full officer of Parliament, which limited its independence until later reform.',
    source:'Federal Accountability Act, S.C. 2006, c. 9' },
  'cpc|Tax-Free Savings Account': {
    context:'Introduced in Budget 2008, effective January 2009, with a $5,000 annual limit. The contribution room accumulates and is not lost, which is why the instrument became more consequential over time than its initial limit suggested. The limit was raised to $10,000 in 2015 and reduced to $5,500 by the incoming government.',
    caveat:'Benefit rises with the ability to save, so distributional effects differ sharply from a refundable credit.',
    source:'Budget 2008; Income Tax Act s.146.2' },
  'cpc|Long-gun registry abolished': {
    context:'Committed in every platform from 2006 and delivered in 2012 once the party held a majority. The Act also required destruction of existing registry records, which triggered litigation with Quebec that reached the Supreme Court; the Court ruled in the federal government\u2019s favour in 2015.',
    caveat:'The commitment had been blocked in two prior minority Parliaments, so the delay reflects arithmetic rather than reversal.',
    source:'Ending the Long-gun Registry Act, S.C. 2012, c. 6' },
  'cpc|Income trust taxation': {
    context:'The 2006 platform stated the party would not tax income trusts. In October 2006 the Finance Minister announced a distribution tax on them, citing an accelerating shift of corporate structures that was eroding the tax base. The announcement caused a sharp one-day fall in trust unit values, and the reversal was explicit and acknowledged.',
    caveat:'The policy rationale was widely accepted by economists; the reversal of a stated commitment is a separate fact from whether the reversal was justified.',
    source:'Department of Finance, Tax Fairness Plan, 31 October 2006' },
  'cpc|Fixed election dates': {
    context:'The government legislated fixed four-year election dates in 2007, then advised dissolution in September 2008 before the fixed date arrived. The Act preserved the Governor General\u2019s discretion, so the early call was lawful — which is precisely the criticism: the legislation constrained nothing it was presented as constraining.',
    caveat:'Every subsequent government of any party has also called elections before the fixed date. The defect is in the instrument, not unique to one party.',
    source:'Canada Elections Act s.56.1; dissolution 7 September 2008' },
  'cpc|Senate reform': {
    context:'Committed across the 2006, 2008 and 2011 platforms to an elected Senate with term limits. Legislation was introduced repeatedly and never passed. In 2014 the Supreme Court held that term limits and consultative elections require substantial provincial consent under the amending formula, which ended the approach.',
    caveat:'The Court ruling made unilateral federal reform constitutionally unavailable, so this is closer to an unachievable commitment than an abandoned one \u2014 but it was still promised three times as achievable.',
    source:'Reference re Senate Reform, 2014 SCC 32' },
  'cpc|Chief Electoral Officer': {
    context:'The party and its fundraising arm pleaded guilty in 2011 to exceeding the national advertising spending limit in the 2006 election through transfers to local campaigns, and paid the maximum fine. Four officials had faced charges, which were withdrawn as part of the plea.',
    caveat:'A guilty plea under the Elections Act is a regulatory offence, not a finding about the election result.',
    source:'Commissioner of Canada Elections, 2011 plea agreement' },
  'cpc|Information Commissioner': {
    context:'The 2014 special report found extension times had grown substantially and that the access system was, in the Commissioner\u2019s words, at risk of becoming irrelevant. The finding concerned systemic administration across departments rather than a single decision.',
    caveat:'Access-to-information delays have been reported as worsening under governments of both parties since.',
    source:'Information Commissioner of Canada, special report 2014' },
  'cpc|Auditor General': {
    context:'The 2012 audit found that the full life-cycle cost of the F-35 programme — roughly $25B against the $15B presented publicly — had not been reported to Parliament, and that National Defence understood the difference. The procurement was subsequently reset.',
    caveat:'The audit concerns what Parliament was told, not whether the aircraft was the right choice.',
    source:'Office of the Auditor General, Chapter 2, Spring 2012' },

  /* ── NDP ───────────────────────────────────────────────────────────── */
  'ndp|Dental care programme': {
    context:'Secured as a condition of the 2022 confidence-and-supply agreement rather than won at an election, which is the mechanism by which a fifth-place party delivered a national programme. The Canadian Dental Care Plan phased in by age and income from 2023.',
    caveat:'Delivered by a Liberal government under agreement. Attribution is genuinely shared, and both parties claim it.',
    source:'Confidence-and-supply agreement, March 2022; CDCP launch 2023' },
  'ndp|Pharmacare framework legislation': {
    context:'Bill C-64 established a framework and first-dollar coverage for contraception and diabetes medication, negotiated under the same agreement. It is a framework act: it commits to a process and two drug categories, not to universal coverage.',
    caveat:'This is why the party\u2019s own universal pharmacare commitment is recorded separately as not delivered.',
    source:'Pharmacare Act, S.C. 2024' },
  'ndp|Anti-scab legislation': {
    context:'Bill C-58 bans the use of replacement workers during legal strikes and lockouts in federally regulated sectors. Long-standing NDP policy, repeatedly tabled and defeated as a private member\u2019s bill before being passed as government legislation under the supply agreement.',
    caveat:'Applies to federally regulated industries only, which is a minority of Canadian workers.',
    source:'Bill C-58, S.C. 2024' },
  'ndp|Universal single-payer pharmacare': {
    context:'Committed since 2019 to full public coverage of prescription medication. What was delivered in 2024 covers contraception and diabetes drugs. The gap between the framework and the commitment is the substance of the criticism from within the party as well as outside it.',
    caveat:'Recorded against the commitment as stated, not against what was achievable in a minority Parliament.',
    source:'Pharmacare Act, S.C. 2024, compared with NDP platform 2019 and 2021' },
  'ndp|Confidence-and-supply agreement': {
    context:'The 2022 agreement was to hold to June 2025. The party withdrew in September 2024, citing the government\u2019s record on labour and affordability. The withdrawal ended the mechanism through which the party\u2019s major deliverables had been secured.',
    caveat:'Whether withdrawal was a reversal or a legitimate response to the other party\u2019s conduct is contested; recorded here as a departure from a stated commitment.',
    source:'Party statement, 4 September 2024' },
  'ndp|House of Commons Board of Internal Economy': {
    context:'The Board ordered repayment of roughly $2.7M over the use of parliamentary resources for satellite offices in Quebec and mailings. The party disputed the finding and challenged it in Federal Court, which upheld the Board\u2019s jurisdiction.',
    caveat:'The Board is composed of MPs from all parties, not an independent officer, which the party argued was the basis of its objection.',
    source:'Board of Internal Economy decision, 2014; Federal Court 2016' },

  /* ── Bloc ──────────────────────────────────────────────────────────── */
  'bq|Québec as a nation motion': {
    context:'The Bloc tabled a motion recognising Quebec as a nation. The government amended it to read that the Québécois form a nation within a united Canada, and it passed with support from all parties. The Bloc voted for the amended version while arguing it had been diluted.',
    caveat:'Symbolic recognition with no legal effect. An intergovernmental affairs minister resigned over it.',
    source:'House of Commons, 27 November 2006' },
  'bq|Supply management protected in trade law': {
    context:'Bill C-282 would prohibit trade negotiators from making concessions on supply-managed sectors. It passed the House with support from all parties and stalled in the Senate, where committee members raised concerns about constraining the trade mandate.',
    caveat:'Passing the House is not enactment. A bill that dies in the Senate has not become law.',
    source:'Bill C-282, 44th Parliament' },
  'bq|Sovereignty referendum': {
    context:'A referendum on sovereignty is a provincial instrument: only the Quebec National Assembly can call one. The Bloc sits federally and therefore cannot deliver it under any circumstances, which is why this is recorded as a standing position rather than an unkept promise.',
    caveat:'The distinction matters. Recording it as broken would penalise a party for lacking a power it never claimed to hold.',
    source:'not a federal instrument' },

  /* ── Green ─────────────────────────────────────────────────────────── */
  'gpc|Environmental Bill of Rights tabled': {
    context:'A private member\u2019s bill establishing a right to a healthy environment and standing to sue over federal environmental decisions. Tabled and never called for second reading, which is the ordinary fate of a private member\u2019s bill from a party with fewer than a dozen seats.',
    caveat:'Tabling a bill is a position, not a delivery. Recorded here because it is the only legislative act the party has been able to take.',
    source:'Bill C-438, 42nd Parliament' },

  /* ── CAQ ───────────────────────────────────────────────────────────── */
  'caq|Hydro rate cap': {
    context:'Bill 2 capped residential Hydro-Québec increases at 3% annually through the mandate. It applied to residential customers only; commercial and industrial rates were set separately and rose faster. The cap has held each year since.',
    caveat:'A rate cap on a Crown utility shifts cost rather than removing it \u2014 the utility\u2019s revenue shortfall appears elsewhere.',
    source:'Loi 2 (2023), Québec' },
  'caq|Immigration threshold at 50,000': {
    context:'The multi-year plan set permanent admissions at approximately 50,000 a year and the target was met in both years. Temporary immigration — students and temporary foreign workers, which the province controls only partly — rose substantially over the same period, so total newcomers increased while permanent admissions were held.',
    caveat:'A commitment about permanent admissions was frequently reported as a commitment about immigration overall. Those are different figures moving in opposite directions.',
    source:'Plan pluriannuel d\u2019immigration 2024-2026' },
  'caq|Pre-kindergarten expansion': {
    context:'Universal four-year-old kindergarten classes were extended province-wide, a central 2018 commitment. Space creation ran ahead of teacher recruitment, so a significant share of new classes opened with staffing gaps and some in non-purpose-built rooms.',
    caveat:'Delivered on the count of classes; contested on quality of delivery.',
    source:'Ministère de l\u2019\u00c9ducation, annual reporting' },
  'caq|Third link between Québec City and Lévis': {
    context:'A central commitment in 2018 and again in 2022, presented in successive versions as a bridge, a highway tunnel, and a transit-only tunnel. Cancelled in April 2023 on cost and traffic-projection grounds, then partially revived as a study in 2024 after political pressure in the Quebec City region. No construction contract was awarded before the mandate ended.',
    caveat:'Recorded as broken because the mandate has now ended without delivery — the strict test this site applies.',
    source:'Ministère des Transports announcements, April 2023 and 2024' },
  'caq|Family doctor for every Quebecer': {
    context:'The commitment was access to a front-line clinician, and the guichet d\u2019accès was expanded to cover most of the population. But access to a clinician and having a family doctor are different things, and roughly 480,000 Quebecers remain without a family doctor.',
    caveat:'The government met the commitment as it later defined it, not as most voters understood it in 2018. Recorded as partial for that reason.',
    source:'RAMQ enrolment data; Guichet d\u2019accès à un médecin de famille' },
  'caq|Commissaire à l\u2019éthique et à la déontologie': {
    context:'The Commissioner found a minister had contravened the code of ethics over a private interest that intersected with their portfolio. The minister resigned the portfolio but remained in the National Assembly, which is the usual outcome: the Commissioner can find and report, not remove.',
    source:'Rapport du Commissaire à l\u2019éthique, 2023' },
  'caq|Vérificateur général du Québec': {
    context:'The audit found cost estimates for the Quebec City tramway were not reliably documented and that the projected budget had been presented publicly with more confidence than the underlying analysis supported. The project was subsequently transferred to CDPQ Infra.',
    source:'Vérificateur général du Québec, rapport 2024' },

  /* ── PQ ────────────────────────────────────────────────────────────── */
  'pq|Charter of Values': {
    context:'Bill 60 would have prohibited public sector employees from wearing conspicuous religious symbols. It was tabled in 2013, dominated public debate, and died on the order paper when the 2014 election was called — an election the party lost, in part on this issue.',
    caveat:'A comparable measure was later enacted by a different government as Bill 21, which is why this is recorded as reversed rather than as an idea that disappeared.',
    source:'Projet de loi 60, 40e législature' },
  'pq|Sovereignty referendum': {
    context:'Committed in successive platforms since 1995. The party has held government once in the period, as a minority in 2012-14, and did not call one. No referendum has been held since 1995.',
    caveat:'A minority government could not have carried a referendum bill, which is context rather than exoneration.',
    source:'no referendum since 1995' },

  /* ── Ontario PC ────────────────────────────────────────────────────── */
  'onpc|Gas tax cut made permanent': {
    context:'The 5.7 cents-per-litre cut was introduced as temporary in 2022, extended repeatedly, and made permanent in the 2025 budget. Delivered as stated. It costs roughly $1B a year in forgone revenue, which the budget accommodates without an offsetting measure.',
    source:'Ontario Budget 2025' },
  'onpc|Licence plate renewal fees eliminated': {
    context:'Fees were removed and prior payments dating to March 2020 were refunded by cheque, at a cost of roughly $1.1B including the refunds. The refunds were mailed in the months before the 2022 election, which drew criticism about timing rather than about the policy.',
    source:'Ontario Regulation 2022; Financial Accountability Office costing' },
  'onpc|Greenbelt land removals': {
    context:'In November 2022 the government removed roughly 7,400 acres from the Greenbelt for housing. The Auditor General and Integrity Commissioner both reported that the selection process had favoured specific developers and had been driven by the Housing Minister\u2019s office rather than by planning criteria. The government reversed the removals in September 2023 and the Premier apologised.',
    caveat:'A reversal following independent findings is a different fact from a reversal on policy grounds, and this page records both the reversal and the findings that produced it.',
    source:'Auditor General of Ontario special report, August 2023' },
  'onpc|Highway 413 timeline': {
    context:'Committed as a shovels-in-the-ground project. Early works contracts have been awarded and the federal environmental review concluded, but the corridor itself is not under construction. The mandate runs to 2029.',
    caveat:'Unfinished with mandate time remaining, so recorded against the timeline rather than as abandoned.',
    source:'Ontario Ministry of Transportation contract awards' },
  'onpc|Auditor General of Ontario': {
    context:'The 2023 Greenbelt report found the process was not transparent, that a small number of developers benefited, and that the removals were not needed to meet housing targets. The 2021 long-term care report found inspection frequency had declined substantially in the years before the pandemic.',
    source:'Auditor General of Ontario, special report 2023; annual report 2021' },
  'onpc|Integrity Commissioner of Ontario': {
    context:'Found the Housing Minister\u2019s chief of staff had controlled the site selection process and that the Minister had failed to oversee it, contravening the Members\u2019 Integrity Act. The chief of staff resigned and the Minister resigned the portfolio.',
    source:'Integrity Commissioner of Ontario, report August 2023' },

  /* ── BC NDP ────────────────────────────────────────────────────────── */
  'bcndp|MSP premiums eliminated': {
    context:'Medical Services Plan premiums were halved in 2018 and eliminated in January 2020, as committed in 2017. The revenue was replaced by an Employer Health Tax, so the cost shifted from individuals to employers rather than disappearing.',
    caveat:'Delivered as stated. The replacement tax was not itself a 2017 commitment.',
    source:'Budget 2018; Employer Health Tax Act' },
  'bcndp|$10-a-day childcare sites': {
    context:'Expanded to over 14,000 spaces at the $10-a-day rate, funded partly through the federal bilateral agreement. The commitment was universal $10-a-day care; what exists is a growing subset of spaces at that rate, with the rest at reduced but higher fees.',
    caveat:'Recorded as delivered on the site count that was committed, not on universality.',
    source:'ChildCareBC; Budget 2023' },
  'bcndp|Decriminalisation of personal drug possession': {
    context:'British Columbia obtained a federal exemption in January 2023 decriminalising possession of small amounts of certain drugs. In April 2024 the province requested and received an amendment recriminalising use in public spaces, following sustained public and municipal pressure. The policy was narrowed by the government that had sought it.',
    caveat:'Whether this was a reversal or a mid-course correction is genuinely contested. Recorded as a reversal because the province asked to undo what it had asked for.',
    source:'Controlled Drugs and Substances Act exemption, amended May 2024' },
  'bcndp|300,000 homes in ten years': {
    context:'BC Builds was funded in Budget 2025. Roughly 4,900 units are under construction against a pace of 30,000 a year required to meet the target. The mandate runs to 2028, so the commitment is early rather than expired.',
    caveat:'Unfinished with four years of mandate remaining. Recorded against the pace, not as failure.',
    source:'BC Budget 2025; BC Builds reporting' },
  'bcndp|Auditor General of British Columbia': {
    context:'The audit found housing programme reporting did not allow progress against targets to be independently verified — a finding about measurement rather than about the units themselves.',
    source:'Auditor General of British Columbia, 2023' },

  /* ── UCP ───────────────────────────────────────────────────────────── */
  'ucp|Taxpayer Protection Act amendment': {
    context:'Extended the existing referendum requirement — previously covering a provincial sales tax — to personal income tax rate increases. Delivered as committed. An ordinary majority can amend or repeal the Act itself, so the constraint binds only as long as a government chooses to leave it in place.',
    caveat:'A statutory constraint on a legislature is a political commitment, not a legal barrier.',
    source:'Alberta Taxpayer Protection Amendment Act, 2023' },
  'ucp|Lowest bracket cut to 8%': {
    context:'Committed in 2023 with a stated timeline of 2024. Delivered in Budget 2026, two years later, with the government citing fiscal conditions. The rate change itself matches the commitment.',
    caveat:'Recorded as partial: the substance was delivered, the timeline was not.',
    source:'Alberta Budget 2026' },
  'ucp|Alberta Pension Plan': {
    context:'The government committed to a referendum on withdrawing from the Canada Pension Plan and commissioned an actuarial report claiming Alberta was entitled to roughly half of CPP assets — a figure the federal Chief Actuary later contradicted. No referendum has been called.',
    caveat:'No reversal has been announced and the mandate runs to 2027, so this is stalled rather than broken.',
    source:'LifeWorks report 2023; Office of the Chief Actuary response 2024' },
  'ucp|Balanced budget legislation': {
    context:'Committed in 2019 to legislate balanced budgets. No binding instrument has been enacted. Budgets have been balanced in some years through resource revenue rather than through a legislated rule.',
    source:'no instrument on file' },
  'ucp|Ethics Commissioner of Alberta': {
    context:'Found the Premier contravened the Conflict of Interest Act by discussing a specific criminal prosecution with the Justice Minister, interfering with the administration of justice. As elsewhere, the Commissioner could find and publish but not sanction.',
    source:'Ethics Commissioner of Alberta, report May 2023' },
  'ucp|Auditor General of Alberta': {
    context:'Found procurement decisions in Alberta Health Services lacked documented justification, in the context of contracting arrangements that later became the subject of a separate public inquiry.',
    source:'Auditor General of Alberta, 2024' },

  /* ── Projet Montréal ───────────────────────────────────────────────── */
  'projet|Réseau express vélo, 200 km': {
    context:'214 km of protected cycling network was added, passing the 200 km commitment in 2025. The network is contiguous rather than a set of disconnected lanes, which is what the commitment specified and what makes it usable.',
    caveat:'Lane removals to build it were locally contested in several boroughs, and that opposition is a real cost of delivery.',
    source:'Ville de Montréal, REV progress reporting' },
  'projet|Rent registry bylaw': {
    context:'Requires landlords to disclose the previous tenant\u2019s rent on a new lease, which was already required under Quebec law but not enforced municipally. The bylaw created a municipal enforcement mechanism, delivering the commitment.',
    caveat:'Enforcement capacity remains limited, so disclosure rates are not the same as compliance.',
    source:'Règlement, Ville de Montréal, 2023' },
  'projet|500,000 trees': {
    context:'285,000 trees were planted by mid-2026, roughly 57% of the commitment, with the mandate ending in November. Survival rate rather than planting count is the measure that matters for canopy, and it is not consistently reported.',
    caveat:'Recorded as partial rather than broken because planting continued through the mandate; it will become a closed record after the November vote.',
    source:'Ville de Montréal, canopy reporting' },
  'projet|Pink metro line': {
    context:'The central transit commitment of the 2017 campaign, running northeast to southwest. A metro line requires provincial funding and the province did not fund it, offering the REM de l\u2019Est instead — which was itself cancelled in 2023. The line was never designed.',
    caveat:'A municipal government cannot build a metro alone. Recorded as reversed because the commitment was made without the power to deliver it, which is a fact about the promise rather than about the province.',
    source:'ARTM planning documents; REM de l\u2019Est cancellation, 2023' },
  'projet|Bureau de l\u2019inspecteur général': {
    context:'The Inspector General found procurement irregularities in a borough contract and the contract was cancelled. Montreal is the only Canadian municipality with a permanent independent inspector general, created after the Charbonneau Commission — so findings appear here that comparable cities would never generate.',
    caveat:'More findings can indicate better oversight rather than worse conduct. Comparing finding counts across cities with different oversight regimes is not meaningful.',
    source:'Bureau de l\u2019inspecteur général, 2022' },

  /* ── ABC Vancouver ─────────────────────────────────────────────────── */
  'abc|100 new police officers': {
    context:'Funded in the 2023 budget and hired, delivering the commitment on the officer count. The paired mental health nurse commitment was not delivered at the same rate, which matters because the platform presented the two as a single integrated response.',
    caveat:'Half of a paired commitment delivered is not the same as the commitment delivered.',
    source:'City of Vancouver Budget 2023' },
  'abc|Permitting reform for small businesses': {
    context:'A single-window permitting process was introduced, reducing the number of separate applications a small business must file. Delivered as committed; median processing time has improved but remains above the target the platform implied.',
    source:'City of Vancouver, permitting service reporting 2024' },
  'abc|100 mental health nurses': {
    context:'58 of 100 positions were filled. The constraint is recruitment rather than funding: the positions exist and are budgeted, and there are not enough available nurses to fill them.',
    caveat:'A hiring shortfall driven by labour supply is a different failure from one driven by a funding decision, and this page distinguishes them.',
    source:'Vancouver Coastal Health staffing reports' },
  'abc|3,000 rental permits a year': {
    context:'2,410 permits issued in 2025, the highest of the mandate and still below target. Permit issuance is partly demand-driven: the city can approve only what developers apply to build, and interest rates suppressed applications through the middle of the mandate.',
    caveat:'Unfinished with the mandate ending in October, so this becomes a closed record after the vote.',
    source:'City of Vancouver permit data' },

  /* ── Toronto ───────────────────────────────────────────────────────── */
  'chow|Renters\u2019 Action Committee': {
    context:'Established with a dedicated municipal tenant support office, delivering the commitment as stated. Its powers are advisory and supportive: rent regulation is provincial, so a municipal tenant office can assist and advocate but cannot set rents.',
    source:'Toronto City Council, 2024' },
  'chow|Property tax at inflation': {
    context:'The 2024 budget raised residential rates 9.5% plus a 1.5% city-building levy, against a commitment to hold increases to inflation. The city faced a roughly $1.8B shortfall, and the increase was passed with a new intergovernmental funding agreement in place. The commitment was explicit and was not met in the first budget after it was made.',
    caveat:'The fiscal position was known in outline when the commitment was made, which is why this is recorded as broken rather than as an unforeseeable reversal.',
    source:'City of Toronto Budget 2024' },
  'chow|25,000 rent-controlled homes by 2030': {
    context:'6,300 units approved and 1,100 under construction. The commitment runs to 2030, beyond the current term, so the relevant question is pace rather than completion: the current rate falls short of what 25,000 by 2030 requires.',
    caveat:'A commitment with a horizon past the mandate cannot be closed by this election, and should not be scored as though it could.',
    source:'Toronto Housing Action Plan reporting' },
  'chow|Auditor General of Toronto': {
    context:'Found shelter capacity reporting understated demand, because turned-away requests were not consistently counted. A measurement finding rather than a finding about the shelter system\u2019s capacity itself.',
    source:'Auditor General of Toronto, 2025' },

  /* ── Calgary, closed mandate ───────────────────────────────────────── */
  'gondek|Declare a climate emergency and fund a citywide climate strategy': {
    context:'Declared in November 2021, in the first weeks of the term, and the strategy was funded at $87M over the term. Delivered as committed. The declaration itself carried no binding obligation; the funding did.',
    source:'Calgary City Council, November 2021' },
  'gondek|Remove single-family-only zoning citywide': {
    context:'Blanket rezoning was approved in May 2024 after the longest public hearing in the city\u2019s history. It permits row houses and duplexes citywide as of right. Delivered, and politically costly: it became a central issue in the 2025 election the mayor lost.',
    caveat:'A delivered commitment can end a mandate. That is worth recording precisely because promise trackers usually imply delivery is always rewarded.',
    source:'Calgary City Council, Bylaw 2024' },
  'gondek|Hold property tax increases below three percent annually': {
    context:'Increases of 4.4%, 7.8% and 3.6% across the term, all above the committed ceiling. The mandate ended in October 2025 without the commitment met, which closes the record.',
    caveat:'Recorded as broken on the strict test: the mandate is over, so there is no remaining time in which it could be met.',
    source:'City of Calgary budgets 2022\u20132025' }
};
