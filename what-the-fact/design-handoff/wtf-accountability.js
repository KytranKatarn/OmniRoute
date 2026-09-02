/* Accountability: officers, their findings, vacancies, and the entity join.

   One source for four pages. Officers, Ethics, Cross-Watch and the party
   records all read from here, so a finding cannot appear with one wording on
   one page and another elsewhere.

   Rules carried through:
   - A FINDING NAMES ITS SUBJECT. "Report on a minister" is not citable. Where
     a subject cannot be named it is not published.
   - A CONTRAVENTION IS NOT A CRIME. These officers can find and publish. They
     cannot fine, sanction or remove, and every surface says so.
   - MORE OVERSIGHT PRODUCES MORE FINDINGS. Counts are never compared across
     jurisdictions with different oversight regimes without saying so. */

const OFFICERS = [
  { id:'oag', name:'Auditor General of Canada', short:'Auditor General', level:'federal', est:1878,
    mandate:'Audits federal spending and reports directly to the House of Commons.',
    power:'Can audit, report and recommend. Cannot compel a department to act.',
    appointed:'Governor in Council on address of the House', term:'10 years, non-renewable' },
  { id:'ethics', name:'Conflict of Interest and Ethics Commissioner', short:'Ethics Commissioner', level:'federal', est:2007,
    mandate:'Administers the Conflict of Interest Act for public office holders and the Members\u2019 Code for MPs.',
    power:'Can investigate and publish a finding of contravention. No penalty, no removal.',
    appointed:'Governor in Council after consultation with party leaders', term:'7 years, renewable' },
  { id:'lobby', enforcement:'ban', enforcementWhy:'Can ban a lobbyist from lobbying for up to two years, and refer to the RCMP.', name:'Commissioner of Lobbying', short:'Commissioner of Lobbying', level:'federal', est:2008,
    mandate:'Maintains the lobbyists\u2019 registry and enforces the Lobbying Act and code of conduct.',
    power:'Can investigate, publish, and refer to the RCMP. Can ban a lobbyist for up to two years.',
    appointed:'Governor in Council on resolution of both Houses', term:'7 years, renewable' },
  { id:'privacy', name:'Privacy Commissioner of Canada', short:'Privacy Commissioner', level:'federal', est:1983,
    mandate:'Oversees federal privacy law and PIPEDA in the private sector.',
    power:'Can investigate and recommend. Order-making power has been repeatedly recommended and not granted.',
    appointed:'Governor in Council on resolution of both Houses', term:'7 years, renewable' },
  { id:'info', enforcement:'order', enforcementWhy:'Holds binding order-making power since 2019, enforceable through Federal Court.', name:'Information Commissioner of Canada', short:'Information Commissioner', level:'federal', est:1983,
    mandate:'Investigates complaints about access to federal records.',
    power:'Can issue binding orders since 2019. Compliance is enforced through Federal Court.',
    appointed:'Governor in Council on resolution of both Houses', term:'7 years, renewable' },
  { id:'ol', name:'Commissioner of Official Languages', short:'Official Languages', level:'federal', est:1970,
    mandate:'Enforces English and French language rights in federal institutions.',
    power:'Can investigate, report, and apply to Federal Court on a complainant\u2019s behalf.',
    appointed:'Governor in Council on resolution of both Houses', term:'7 years, renewable' },
  { id:'ceo', enforcement:'prosecute', enforcementWhy:'The Commissioner of Canada Elections can lay charges and prosecute — the only route on this list that can end in a conviction.', name:'Chief Electoral Officer', short:'Chief Electoral Officer', level:'federal', est:1920,
    mandate:'Administers federal elections. The Commissioner of Canada Elections enforces the Act.',
    power:'The Commissioner can enter compliance agreements, lay charges and prosecute.',
    appointed:'Resolution of the House of Commons', term:'10 years, non-renewable' },
  { id:'psic', name:'Public Sector Integrity Commissioner', short:'Integrity Commissioner', level:'federal', est:2007,
    mandate:'Receives disclosures of wrongdoing from federal public servants and handles reprisal complaints.',
    power:'Can investigate and report to Parliament. Reprisal cases go to a tribunal.',
    appointed:'Governor in Council on resolution of both Houses', term:'7 years, renewable' },
  /* Provincial and municipal equivalents, so a finding is not orphaned. */
  { id:'oag-on', name:'Auditor General of Ontario', short:'AG Ontario', level:'provincial', prov:'ON', est:1886,
    mandate:'Audits provincial spending and reports to the Legislative Assembly.',
    power:'Can audit, report and recommend.', appointed:'Order of the Assembly', term:'10 years' },
  { id:'int-on', name:'Integrity Commissioner of Ontario', short:'Integrity Ontario', level:'provincial', prov:'ON', est:1988,
    mandate:'Administers the Members\u2019 Integrity Act and the lobbyists\u2019 registry.',
    power:'Can find a contravention and recommend a sanction to the Assembly.', appointed:'Order of the Assembly', term:'5 years' },
  { id:'oag-ab', name:'Auditor General of Alberta', short:'AG Alberta', level:'provincial', prov:'AB', est:1978,
    mandate:'Audits provincial spending and reports to the Legislative Assembly.',
    power:'Can audit, report and recommend.', appointed:'Order of the Assembly', term:'5 years' },
  { id:'eth-ab', name:'Ethics Commissioner of Alberta', short:'Ethics Alberta', level:'provincial', prov:'AB', est:1991,
    mandate:'Administers the Conflicts of Interest Act for members and public office holders.',
    power:'Can find a contravention and recommend a sanction to the Assembly.', appointed:'Order of the Assembly', term:'5 years' },
  { id:'oag-bc', name:'Auditor General of British Columbia', short:'AG British Columbia', level:'provincial', prov:'BC', est:1977,
    mandate:'Audits provincial spending and reports to the Legislative Assembly.',
    power:'Can audit, report and recommend.', appointed:'Order of the Assembly', term:'8 years' },
  { id:'eth-qc', name:'Commissaire \u00e0 l\u2019\u00e9thique et \u00e0 la d\u00e9ontologie', short:'\u00c9thique Qu\u00e9bec', level:'provincial', prov:'QC', est:2010,
    mandate:'Administers the code of ethics for members of the National Assembly.',
    power:'Can find a contravention and recommend a sanction to the Assembly.', appointed:'Vote of the National Assembly', term:'5 years' },
  { id:'vgq', name:'V\u00e9rificateur g\u00e9n\u00e9ral du Qu\u00e9bec', short:'VG Qu\u00e9bec', level:'provincial', prov:'QC', est:1867,
    mandate:'Audits provincial spending and reports to the National Assembly.',
    power:'Can audit, report and recommend.', appointed:'Vote of the National Assembly', term:'10 years' },
  { id:'ig-mtl', enforcement:'cancel', enforcementWhy:'Can cancel or suspend a municipal contract on its own authority, without going to council or a court.', name:'Bureau de l\u2019inspecteur g\u00e9n\u00e9ral de Montr\u00e9al', short:'IG Montr\u00e9al', level:'municipal', city:'Montr\u00e9al', est:2014,
    mandate:'Oversees municipal contracting. Created following the Charbonneau Commission.',
    power:'Can cancel or suspend a municipal contract outright \u2014 unusually strong for a municipal office.',
    appointed:'Montr\u00e9al city council', term:'5 years' },
  { id:'ag-tor', name:'Auditor General of Toronto', short:'AG Toronto', level:'municipal', city:'Toronto', est:2002,
    mandate:'Audits city programmes and reports to council.',
    power:'Can audit, report and recommend.', appointed:'Toronto city council', term:'indefinite' },
  { id:'boie', enforcement:'repay', enforcementWhy:'Can order repayment. Not an independent officer, so this power sits with MPs judging MPs.', name:'Board of Internal Economy', short:'Board of Internal Economy', level:'federal', est:1985,
    mandate:'Governs House of Commons spending by MPs.',
    power:'Can order repayment. Composed of MPs from all parties, so it is not an independent officer.',
    appointed:'Members of the House', term:'per Parliament', notIndependent:true }
];

/* Findings, named and dated. `subject` is who the finding is about; `party`
   links it back to the party record page; `ctxKey` reaches the shared context
   file so the explanation is not duplicated. */
const FINDINGS = [
  { officer:'ethics', year:2017, subject:'Justin Trudeau', role:'Prime Minister', party:'lib',
    kind:'contravention', ref:'Trudeau Report',
    summary:'Contravened four sections of the Conflict of Interest Act by accepting private travel and hospitality from a person with dealings with the government.',
    ctxKey:'lib|Conflict of Interest and Ethics Commissioner' },
  { officer:'ethics', year:2019, subject:'Justin Trudeau', role:'Prime Minister', party:'lib',
    kind:'contravention', ref:'Trudeau II Report',
    summary:'Improperly sought to influence the Attorney General regarding the prosecution of SNC-Lavalin.',
    ctxKey:'lib|Conflict of Interest and Ethics Commissioner' },
  { officer:'ethics', year:2021, subject:'Bill Morneau', role:'former Finance Minister', party:'lib',
    kind:'contravention', ref:'Morneau II Report',
    summary:'Contravened the Act over the WE Charity contribution agreement and undeclared travel.' },
  { officer:'oag', year:2024, subject:'Canada Border Services Agency', role:'agency', party:'lib',
    kind:'audit', ref:'Report 1, ArriveCAN',
    summary:'Could not establish the true cost of ArriveCAN, found roughly $59.5M spent with documentation so poor that value for money could not be demonstrated.',
    ctxKey:'lib|Auditor General' },
  { officer:'oag', year:2012, subject:'National Defence', role:'department', party:'cpc',
    kind:'audit', ref:'Chapter 2, Spring 2012',
    summary:'Found the F-35 life-cycle cost of roughly $25B had not been reported to Parliament, against the $15B presented publicly.',
    ctxKey:'cpc|Auditor General' },
  { officer:'oag', year:2022, subject:'Employment and Social Development Canada', role:'department', party:'lib',
    kind:'audit', ref:'Report 10, COVID benefits',
    summary:'Found $4.6B in pandemic benefit overpayments to ineligible recipients and a further $27B requiring verification.' },
  { officer:'info', year:2014, subject:'Federal institutions', role:'system-wide', party:'cpc',
    kind:'audit', ref:'Special report 2014',
    summary:'Found extension times had grown substantially and warned the access system risked becoming irrelevant.',
    ctxKey:'cpc|Information Commissioner' },
  { officer:'ceo', year:2011, subject:'Conservative Party of Canada', role:'political party', party:'cpc',
    kind:'contravention', ref:'2011 plea agreement',
    summary:'The party and its fundraising arm pleaded guilty to exceeding the 2006 national advertising spending limit and paid the maximum fine.',
    ctxKey:'cpc|Chief Electoral Officer' },
  { officer:'boie', year:2014, subject:'New Democratic Party', role:'political party', party:'ndp',
    kind:'contravention', ref:'Satellite offices decision',
    summary:'Ordered roughly $2.7M in repayment over parliamentary resources used for satellite offices and mailings. The party contested the finding and lost in Federal Court.',
    ctxKey:'ndp|House of Commons Board of Internal Economy' },
  { officer:'lobby', year:2023, subject:'Registered lobbyists', role:'system-wide',
    kind:'audit', ref:'Annual report 2022-23',
    summary:'Reported that a minority of monthly communication returns were filed late or incompletely, and that enforcement capacity limits verification.' },
  { officer:'psic', year:2023, subject:'Federal public service', role:'system-wide',
    kind:'audit', ref:'Annual report 2022-23',
    summary:'Reported that fear of reprisal continues to suppress disclosure, and that the Act\u2019s protections have been recommended for reform since 2017.' },
  { officer:'oag-on', year:2023, subject:'Government of Ontario', role:'government', party:'onpc',
    kind:'audit', ref:'Greenbelt special report',
    summary:'Found the Greenbelt land removal process was not transparent, favoured specific developers, and was not needed to meet housing targets.',
    ctxKey:'onpc|Auditor General of Ontario' },
  { officer:'oag-on', year:2021, subject:'Ministry of Long-Term Care', role:'ministry', party:'onpc',
    kind:'audit', ref:'Annual report 2021',
    summary:'Found long-term care inspection frequency had declined substantially in the years before the pandemic.',
    ctxKey:'onpc|Auditor General of Ontario' },
  { officer:'int-on', year:2023, subject:'Steve Clark', role:'Housing Minister', party:'onpc',
    kind:'contravention', ref:'Greenbelt report',
    summary:'Found the Minister failed to oversee a process controlled by his chief of staff, contravening the Members\u2019 Integrity Act. Both resigned.',
    ctxKey:'onpc|Integrity Commissioner of Ontario' },
  { officer:'eth-ab', year:2023, subject:'Danielle Smith', role:'Premier', party:'ucp',
    kind:'contravention', ref:'Smith report',
    summary:'Found the Premier contravened the Conflicts of Interest Act by discussing a specific criminal prosecution with the Justice Minister.',
    ctxKey:'ucp|Ethics Commissioner of Alberta' },
  { officer:'oag-ab', year:2024, subject:'Alberta Health Services', role:'agency', party:'ucp',
    kind:'audit', ref:'2024 report',
    summary:'Found procurement decisions lacked documented justification.',
    ctxKey:'ucp|Auditor General of Alberta' },
  { officer:'oag-bc', year:2023, subject:'BC Housing', role:'agency', party:'bcndp',
    kind:'audit', ref:'2023 report',
    summary:'Found housing programme reporting did not allow progress against targets to be independently verified.',
    ctxKey:'bcndp|Auditor General of British Columbia' },
  { officer:'eth-qc', year:2023, subject:'a member of the National Assembly', role:'minister', party:'caq',
    kind:'contravention', ref:'2023 report',
    summary:'Found a contravention of the code over a private interest intersecting the portfolio. The minister resigned the portfolio and kept the seat.',
    ctxKey:'caq|Commissaire \u00e0 l\u2019\u00e9thique et \u00e0 la d\u00e9ontologie',
    unnamed:'The Commissioner published the finding without naming the member, which the office does in some categories of report.' },
  { officer:'vgq', year:2024, subject:'Minist\u00e8re des Transports', role:'ministry', party:'caq',
    kind:'audit', ref:'2024 report',
    summary:'Found tramway cost estimates were not reliably documented and were presented publicly with more confidence than the analysis supported.',
    ctxKey:'caq|V\u00e9rificateur g\u00e9n\u00e9ral du Qu\u00e9bec' },
  { officer:'ig-mtl', year:2022, subject:'a borough contract', role:'municipal contract', party:'projet',
    kind:'audit', ref:'2022 report',
    summary:'Found procurement irregularities. The contract was cancelled under the office\u2019s own authority.',
    ctxKey:'projet|Bureau de l\u2019inspecteur g\u00e9n\u00e9ral' },
  { officer:'ag-tor', year:2025, subject:'Shelter, Support and Housing Administration', role:'division', party:'chow',
    kind:'audit', ref:'2025 report',
    summary:'Found shelter capacity reporting understated demand because turned-away requests were not consistently counted.',
    ctxKey:'chow|Auditor General of Toronto' }
];

/* Governor-in-Council vacancies. The story in appointments is usually the
   seat left empty: a tribunal that cannot sit, a watchdog post unfilled. */
const GIC_VACANCIES = [
  { post:'Member, Immigration and Refugee Board', body:'Immigration and Refugee Board', vacantSince:'2025-11-14',
    consequence:'Panel capacity reduced; the Board\u2019s backlog is the largest of any federal tribunal.' },
  { post:'Chairperson, Canadian Human Rights Tribunal', body:'Canadian Human Rights Tribunal', vacantSince:'2026-03-02',
    consequence:'Full-panel hearings cannot be scheduled without a chair or acting chair.' },
  { post:'Member, Parole Board of Canada (Prairie region)', body:'Parole Board of Canada', vacantSince:'2026-01-20',
    consequence:'Regional hearing capacity reduced; hearings deferred.' },
  { post:'Commissioner, Competition Tribunal', body:'Competition Tribunal', vacantSince:'2026-05-08',
    consequence:'Quorum for contested merger reviews is harder to constitute.' },
  { post:'Director, Canada Post Corporation board', body:'Canada Post', vacantSince:'2025-09-30',
    consequence:'Board operating below its full complement during a service review.' },
  { post:'Member, Veterans Review and Appeal Board', body:'Veterans Review and Appeal Board', vacantSince:'2026-06-11',
    consequence:'Appeal wait times lengthen; the Board has reported capacity pressure.' }
];

/* True of every office here without exception, and the reason the page exists:
   a finding can end a portfolio but never a seat. */
const NO_REMOVAL = 'No office on this list — independent or not — can remove anyone from office. ' +
  'The strongest outcome available to most of them is a published finding and a recommendation the ' +
  'legislature is free to ignore.';

const FINDING_KINDS = {
  contravention: { l:'Contravention found', c:'var(--wtf-contested)',
    note:'A specific statutory or code provision was breached. Not a criminal finding, and no penalty attaches beyond the report itself.' },
  audit: { l:'Audit finding', c:'var(--wtf-developing)',
    note:'A finding about spending, process or documentation. Recommendations are not binding unless the officer holds order-making power.' }
};
