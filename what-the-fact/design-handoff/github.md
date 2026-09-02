repo: KytranKatarn/archie-platform
branch: main
path: what-the-fact

> The newsroom lives in a SUBDIRECTORY of the archie-platform monorepo, not in
> its own repo. `KytranKatarn/what-the-fact-site` (recorded here previously) is
> the April 2026 "Coming Soon" landing page and a different codebase.

## Layout

- `what-the-fact/consumer/` — the deployed Flask app. `routes.py` is 268KB and
  holds ~30 routes; `templates/` has 49 Jinja templates; `static/style.css` is
  the shared shell.
- `what-the-fact/tech/` — what-the-fact.tech, a separate domain and stylesheet.
  Deliberately out of scope.
- `what-the-fact/.design-sync/` — a **styles-only, one-way** sync: it bundles
  `consumer/static/style.css` INTO the design system
  (projectId 71f3c387-35fc-4956-beb5-5dff218ad1b9, the one attached to this
  project). It is not a path for pushing pages back to the repo.
- `what-the-fact/design-reference/` — 19 `.dc.html` artboards from an earlier
  design session. `.design-sync/NOTES.md` says explicitly: unrelated to the
  sync, do not upload.

## Conventions that bind new work

From `.design-sync/conventions.md` and `NOTES.md`:

- Every class is `wtf-`-prefixed. **New pages get their own sub-namespace** —
  existing ones use `wtf-bs-`, `wtf-dv-`, `wtf-ec-`, `wtf-mu-`, `wtf-wx-`.
- Page-level styles live in per-template `<style>` blocks, NOT in the shared
  stylesheet. They are not extractable into the bundle by design.
- **There is no bare `.wtf-card`.** The card is `.wtf-article-card` plus a
  per-lean modifier. Do not invent base classes.
- Colour tokens carry meaning and must not be repurposed decoratively.

## Last sync

date: 2026-09-02T16:15:33Z
mode: read-only exploration (no write access from this project)

### Final sweep — every page, every link, every script
All 46 pages load with zero runtime errors; every internal href, script and
stylesheet resolves; every nav deep link lands on a populated pane; every
query route (`?slug`, `?party`, `?id`, `?src`, `?q`) resolves. The handoff
README now ends with a **generated migration manifest** (page → live route →
nav group → scripts → CDN → gate) and a single shared-layer table.

Defects found and fixed by the sweep, each of which would have shipped:
- `wtf-mps.js` called `drawWave()` / `drawBills()` after a rewrite had dropped
  them — threw on every load and blocked the `#senate` / `#ridings` deep links.
- `#ridings` opened an empty pane: `wtf-ridings.js` loads after the hash
  handler, so it now initialises itself when its pane is already showing.
- Four pages built from the CRTC donor (`chain`, `edu`, `governance`, `score`)
  still ran the CRTC inline script against elements they do not have.
- Social metadata (og / twitter title + description) was CRTC boilerplate on 37
  pages; now derived from each page's own title and description.
- The lobbying organisation drill-down (live `detail.org_label`) had been lost
  in the table rebuild; restored, with contacts routing to MP profiles.
- Three paywall-preview keys were in play and the archive deleted the one the
  feed used. One key now: `sessionStorage['wtf-gate-preview']`.
- Map page had no footer; journalists had seven dead links; the inline accuracy
  section did not link to the full report; the LIVE label lacked the class its
  responsive rule targets, so the nav overflowed under 1180 px.

### Final sweep — visual pass + Claude CLI integration brief
Every page re-read for content, links and layout; visual refresh applied through
`wtf-shell.css` (lifted panels, pill controls, tabular numerals, consistent
radii, hover lift, focus rings, reduced-motion) so the pass costs no per-page
markup. Bundle is 50 pages / 29 scripts / 1 stylesheet / local
geometry. `deploy/CLAUDE_CLI_INTEGRATION.md` is the order of operations and
the six non-negotiables for whoever runs the phases; `deploy/sync-diff.md`
refreshed. Handoff folder is byte-identical to the working files.

### Divergence and Clusters rebuilt from the corpus; Blindspot links fixed
Both were five-row stubs. **Divergence** now qualifies stories by rule (six+
outlets, spread crossing the centre, a named checkable point), quotes both
sides' headlines verbatim with outlet and band, scores divergence 0–100 (mean
pairwise band distance), shows the V.E.R.I.F.Y. verdict or "opinion, not
scored", and lists the 12 excluded stories with the reason each failed.
**Clusters** is the I.N.K. view: spread bar, median (not mean), size, pickup
timeline (who filed first, +hours), every headline, blindspot-seed flag under six
outlets. Both take `?story=<cid>` and open that card. **Blindspot** passed `?a=`
to an article page that reads `?id=` — fixed, and its three chips now target the
specific story. The article page's provenance block gains "Divergence view" and
"Full cluster" beside Compare coverage. On the live site the point-in-dispute
map (`POINT` in wtf-divergence.js) is editorial data and belongs in the
database, not the template; the dispute rule is duplicated in wtf-clusters.js
(`DISPUTED`) and must read from the same source.

### Team page: the whole department, not just the named eight
Below the eight `TEAM_AGENTS` cards the page now lists the rest of News & Media —
P.R.O.O.F., E.C.H.O., V.E.T., A.X.I.O.M., C.O.N.D.U.I.T., T.A.L.O.N.,
R.A.N.G.E.R. (the fact-checkers K.I.N. hired as the queue outgrew V.E.R.I.F.Y.),
V.E.R.I.F.Y.-B (migration 385, hub backlog), M.A.V.E.N. (curation, migration
157/162) and S.T.R.I.N.G.E.R. (idle, per the classify-pool design note). These
agents exist only in the database (hire queue), not in code, so **the live page
must render them from `get_public_roster(department='News & Media')` minus the
eight** — titles, expansions and portraits as the directory publishes them. The
design shows name, task volume from `_newsroom_agents` and shift state, and says
"from the directory when published" where it does not know. 18 of 22 are named
in the repo; the other 4 had no attributed task and come from the directory.

### Team page rebuilt from `TEAM_AGENTS` in routes.py
The design showed six agents; the live roster is **eight** — F.A.C.T., B.I.A.S.,
V.E.R.I.F.Y., L.O.C.A.L., I.N.K., D.R.A.F.T., **P.U.B.L.I.S.H.** and A.U.R.O.R.A. —
with the live expansions, roles, models, accent colours and platform portrait
URLs (initials fallback on error). I.N.K. is "Investigative News & Knowledge",
not clustering, and its live colour is #ec4899; D.R.A.F.T. is #06b6d4. **Agent
colours elsewhere in the design (news drawer, article rail, activity) still use
the earlier palette — align them to `accent_colour` in Phase 3.** The page also
adds the "who actually did the work" roster from `_newsroom_agents`: 22 agents
in News & Media, dispatch by capability, P.R.O.O.F. / E.C.H.O. / V.E.T. /
A.X.I.O.M. / C.O.N.D.U.I.T. / T.A.L.O.N. / R.A.N.G.E.R. performing most
fact-checks, unattributed counted separately. Both blocks must loop the data
(`TEAM_AGENTS` + the attribution query), never a hardcoded list.

### Methodology → what-the-fact.tech/transparency
The methodology page is now the plain-language front door: it links to the
transparency portal for the full method (model cards, scoring rules, compliance
scans, pipeline) and lists what lives there. The portal is a separate domain with
its own stylesheet, so it is linked, not reproduced.

### Echo (new route `/echo`, Media group) and "Where the money goes"
**Echo** tracks repetition: slogans in circulation with first-heard, weekly
lifecycle bars, uses and **pickup** (share of uses that came from outlets rather
than the speaker — the closest honest proxy for a phrase working); words the news
cannot stop using, per day ("Trump" leads every day of the window); posting
frequency of leaders and premiers by channel; and a slot for the platform's
social layer when it links in. The page states what it will not say: that a
slogan is effective, honest or good.
**Where the money goes** — a departmental breakdown on the Debt tracker (21
portfolios, Public Accounts Vol. II, approximate), with Global Affairs in the
same scale so $10.3 **billion** abroad reads against $150B through ESDC and $158B
through Finance. "B" is now spelled out as billions where a reader lands first,
after the figure was read as millions.

### Two new Money pages (new routes: `/global`, `/debt`)
**Global Affairs spending** — ten years of international assistance, share of
national income against the 0.7% target, Ukraine support with loans shown
separately, largest recipients and channels, and aid placed in proportion to all
federal spending (~1.9¢ of each dollar). **Debt tracker** — ten fiscal years of
revenue, expenses, balance, accumulated deficit, debt-to-GDP and interest, with
revenue and expense composition and a four-measure "better or worse" panel that
names its measure rather than picking one. Both cross-reference Gov, Civic,
Market Watch, Cross-Watch, Parliament and coverage. Figures are the design's
reading of the Public Accounts, Fiscal Monitor, GAC Statistical Report and OECD
DAC — approximate, labelled, to be read from Finance Canada / GAC open data.

### 2026 on every cost surface
The national chart now carries the current year as a dashed year-to-date column
(House · Senate · ministerial) and a fifth stat tile, both outside the 5-year
total. MP profiles gain a "2026 so far" panel mirroring `cost.js` `current` —
disclosed quarters, YTD, projection only at ≥2 quarters. Senator profiles gain
the five complete years and the 2026 Q1 row they never had. The 2026 indemnity
($209,800 MP / $185,300 senator) is stated as accruing, not claimed.

### Pre-deploy platform layer
One tier check (`wtf-tier.js`, server-injectable), live-data hooks with sample
fallbacks (`wtf-live.js`), an accessibility floor (`wtf-a11y.js`), the
eight-language toggle on the repo's own `I18n` contract (`wtf-i18n.js`; en fr es
pt de zh ar he, RTL for ar/he), a designed 404, local-first geometry, narrow-
screen rules, and `wtf-corpus.js` pruned where unread. Smoke test gains a
"Tier in page" column. Details in `deploy/DEPLOY.md › Platform layer`.

### Money, Media, Data and About pages rebuilt to their live contracts
Cost, Economy, Rates, Journalists, CRTC, Cross-Watch (+ entity footprint),
Accountability Chain, Governance and C.R.E.E.D. are rebuilt against
`templates/*.html` and `static/js/cost.js` read from `main` today. All nine load
with zero runtime errors; every query view (`?j=`, `?entity=`, `?e=`) verified by
real navigation. Details in the README section "Rebuilt to live contracts".

### Money section + Journalists + CRTC — contracts read, rebuild queued
Read `templates/cost.html` + `static/js/cost.js` (all rendering is client-side
against `/api/cost/summary`, `/api/cost/mp|senator/<id>`,
`/api/cost/reconciliation`), `economy.html` (M.A.R.K.E.T. framing, Market Watch
attribution and CTA, beat pills, `/news?beat=` links), `rates.html` (Valet
V122514, Starter+ table), `journalists.html` + `journalist.html` (directory +
gated profile sections) and `crtc.html` (ownership-concentration panel, type
filters, gated 280-ruling list). Captured verbatim in
`design-handoff/reference/money-media-contracts.md` so the rebuild does not
depend on re-reading the repo. Five pages are queued (see todo list); none is
rebuilt yet — the session hit its usage limit at this point.

### Deploy kit (`design-handoff/deploy/`)
The repo already holds `what-the-fact/design-handoff/` — the 39-page snapshot
from earlier today. This bundle supersedes it (26 added, 44 changed, 7
unchanged, none removed; `deploy/sync-diff.md` is computed by git blob SHA-1).
`deploy/DEPLOY.md` is the runbook against the repo's real mechanism —
`what-the-fact/deploy.sh consumer` rsyncs to the VPS and rebuilds only the
consumer container; there is no CI between merge and live, so the one-PR-per-
phase rule is the safety net. `deploy/smoke-test.html` is the error-injection
harness from this sweep, parametrised on live routes, to be served from
`consumer/static/dev/` and run after every deploy. `deploy/CLAUDE_CODE_BRIEF.md`
is the Phase 1 brief with acceptance criteria.

Also fixed on the verifier's report: the Ridings "Seats by province" panel drew
before the Represent fetch resolved and read "0 seats across 0 provinces"; it
now draws inside the load promise and guards against an empty list.

### Earlier in this sync
- Built the two missing member detail pages from `templates/mp.html` and
  `templates/senator.html`: full section order, and the public/paid split as
  the templates set it.
- MP profile keeps **cost to taxpayers and House committees above the paywall**,
  per the repo's own comment (owner decision 2026-08-18): committee membership
  is one click away on ourcommons.ca, so "paywalling it buys no exclusivity and
  reads as charging for a public record."
- Senate page written to Senate vocabulary rather than copied from the House —
  yea/nay/abstention ballots, caucus groups not parties, and mandatory
  retirement at 75 derived from one birth date so age and years-remaining
  cannot disagree.
- Added the lobbying organisation drill-down the live template has
  (`detail.org_label`) and ours was missing; appointments now deep-link to
  orders-in-council.canada.ca and ethics rows to the public registry.
- Roster cards and both floor plans now route to the new profiles instead of
  dead-ending in search.

### Ridings is a third chamber tab, not a separate page
A riding is a place and an MP is a person, but the reader's question ("who
represents me?") starts at the riding and ends at the member — two nav items
buried the postal lookup that is the actual entry point. So `/mps` now carries
three tabs: **House of Commons · Senate · Ridings**, deep-linkable as
`#hoc` / `#senate` / `#ridings`, with the ridings tab initialising on first
open rather than pulling ~400 boundaries on every visit to the roster.
`wtf-ridings.html` is left as a redirect so existing links keep working. In
Flask this is one route with a tab param, not two templates.

### Riding layer
New page `wtf-ridings.html` reads the **Represent API** (OpenNorth, CORS-enabled)
for real riding names, simplified boundaries and postal-code lookup: 338
districts with correct em-dash and accented spellings, all 338 centroids
plotted on a Lambert projection, boundary drawn on selection, and a
six-character postal lookup that resolves to a riding.

It names **no member**. The riding-to-member join lives in
`parliament.mps.riding_name`; deriving it from geography would put a real
person in the wrong seat, so a riding links into the member directory instead.

Represent serves 338 districts (the order it currently publishes) while the
House seats 343, so the two are briefly out of step after a redistribution —
the page says so. On implementation read ridings from the database and drop the
API dependency.

### Photos — deliberately not faked
`mp.html`, `senator.html` and `mps.html` all read `photo_url` (ourcommons.ca
and sencanada.ca headshots) with a `👤` emoji fallback. These are real named
people, so the design files show an **initials disc ringed in the member's
party or caucus colour** with a small "No photo" label, never a stand-in face.
On implementation the `<img src="{{ photo_url }}">` fills that disc and the
initials become the `onerror` fallback. Replace the emoji with the icon set
while you are in those templates.

## Screen map

| Design file | Repo target |
| --- | --- |
| `wtf-home.html` | `consumer/templates/index.html` |
| `wtf-news.html` | `consumer/templates/news.html` |
| `wtf-archive.html` | new template + route |
| `wtf-article.html` | `consumer/templates/article.html` |
| `wtf-weather.html` | `consumer/templates/weather.html` |
| `wtf-city.html` | `consumer/templates/weather.html` (city view) |
| `wtf-accuracy.html` | `consumer/templates/forecast_accuracy.html` |
| `wtf-mps.html` | `consumer/templates/mps.html` |
| `wtf-mp.html` + `wtf-mp.js` | `consumer/templates/mp.html` |
| `wtf-senator.html` + `wtf-senator.js` | `consumer/templates/senator.html` |
| `wtf-ridings.js` (ridings tab in `wtf-mps.html`) | `mps.html` third tab + `parliament.mps.riding_name` |
| `wtf-accountability.js` | shared officers / findings / vacancies; read by officers, ethics, cross-watch and party records |
| `wtf-officers.html` + `wtf-officers.js` | `consumer/templates/officers.html` |
| `wtf-ethics.html` + `wtf-ethics.js` | `consumer/templates/ethics.html` |
| `wtf-cross-watch.html` + `wtf-cross-watch.js` | `consumer/templates/cross_watch.html` |
| `wtf-brand.js` | shared monogram/wordmark helper; swap in real `logoUrl` assets |
| `wtf-record-context.js` | context for every party record entry, keyed `partyId\|title` |
| `wtf-parties.html` + `wtf-parties-app.js` + `wtf-parties.js` | new route + template; electoral history from Elections Canada / Élections Québec / provincial CEOs |
| `wtf-platforms.html` + `wtf-platforms.js` + `wtf-promises.js` | new route + template; commitments from platform PDFs, verdicts from the Watch series |
| `wtf-races.html` + `wtf-races.js` + `wtf-candidates.js` | new route + template; nominations from Elections Canada / Élections Québec / municipal clerks |
| `wtf-elections.html` + `wtf-elections.js` | new route + template; municipal list from `weather.html` `CITIES` |
| `wtf-parliament.js` | `SEAT_XY` / `SENATOR_XY` in `mps.html` + roster from DB |
| `wtf-officers.html` | `consumer/templates/officers.html` |
| `wtf-gic.html` | `consumer/templates/gic.html` |
| `wtf-ethics.html` | `consumer/templates/ethics.html` |
| `wtf-lobbying.html` | `consumer/templates/lobbying.html` |
| `wtf-municipal.html` | `consumer/templates/municipal.html` |
| `wtf-rates.html` | `consumer/templates/rates.html` |
| `wtf-economy.html` | `consumer/templates/economy.html` |
| `wtf-cost.html` | `consumer/templates/cost.html` |
| `wtf-markets.html` | `consumer/templates/markets.html` |
| `wtf-sources.html` / `wtf-outlet.html` | `consumer/templates/sources.html`, `source.html` |
| `wtf-owners.html` | `consumer/templates/owners.html` |
| `wtf-journalists.html` | `consumer/templates/journalists.html`, `journalist.html` |
| `wtf-crtc.html` | `consumer/templates/crtc.html` |
| `wtf-blindspot.html` | `consumer/templates/blindspot.html` |
| `wtf-divergence.html` | `consumer/templates/divergence.html` |
| `wtf-clusters.html` | `consumer/templates/cluster.html` |
| `wtf-activity.html` | `consumer/templates/activity.html` |
| `wtf-map.html` | `consumer/templates/map.html` |
| `wtf-search.html` | `consumer/templates/search.html` |
| `wtf-claims.html` | `consumer/templates/claims.html` |
| `wtf-chain.html` | `consumer/templates/chain.html` |
| `wtf-cross-watch.html` | `consumer/templates/cross_watch.html` |
| `wtf-api.html` | `consumer/templates/api_docs.html` |
| `wtf-edu.html` | `consumer/templates/edu.html` |
| `wtf-methodology.html` | `consumer/templates/score.html` (methodology) |
| `wtf-score.html` | `consumer/templates/score.html` |
| `wtf-creed.html` | `consumer/templates/governance.html` (C.R.E.E.D.) |
| `wtf-governance.html` | `consumer/templates/governance.html` |
| `wtf-team.html` | `consumer/templates/team.html` |
| `wtf-literacy.html` | `consumer/templates/literacy.html` |
| `_nav.html`, `wtf-shell.css` | `consumer/templates/base.html`, `consumer/static/style.css` |

### Elections — new section (`/elections`)
A seventh nav group, above Money. Elections span three levels of government, so
they do not belong inside Politics, which is federal-only. Four tabs, hash-addressable:

- **Federal** — 45th general election seats and popular vote, plus a
  seat-share-minus-vote-share chart. That distortion is the point: the Bloc gains
  most (concentrated vote), the Greens lose most (spread thin). Next fixed date
  is presented as the *latest* date, since a minority can fall on confidence.
- **Provincial** — all 13 legislatures, shaded on a real Natural Earth admin-1
  map by time to the polls. Québec votes 5 Oct 2026, the only provincial general
  election this year.
- **Municipal** — **reads the same 66-city list the newsroom reports on**,
  imported from `weather.html`'s `CITIES` rather than retyped, so the municipal
  calendar and the coverage claim cannot drift. Autumn 2026 is four provincial
  cycles in three weeks: BC 17 Oct, ON 26 Oct, MB 28 Oct, QC 1 Nov.
- **Coverage readiness** — which cities about to elect a council have no source
  reporting. Uses the same freshness window as the weather page.

Municipal dates attach to a **province**, not a city: they are set by each
province's local elections act. One rule, 66 cities.

### Invented greys replaced with the token (contrast)
383 instances of `#5d6875` and `#4d5766` across 47 files — neither is in the
What The Fact token set, and both measure 3.27:1 on card ground, failing WCAG AA
for text under 18.66px. All now `var(--wtf-text-muted)` (#7d8590, 4.98:1).
These were load-bearing labels in places (province groupings, source lines), not
decoration. Keep tokens only; do not reintroduce a hand-picked grey.

### One city list, three pages
`municipal.html` detected cities from a hand-typed 29-name array, so the
municipal beat could only ever see part of the network it claims to cover.
It now reads the same 66 cities as `weather.html` and `/elections` — one list,
so "cities we report on" means the same thing everywhere. In Flask this should
be a single `CITIES` constant (or a DB table) imported by all three, never
re-declared per template. Matching is longest-name-first so "Québec City" is
not swallowed by "Québec".

The page now also names the **silent cities** — those in the network with no
municipal story in the window, grouped by province, with capitals flagged and a
link through to election coverage readiness. That absence is the page's actual
subject.

### Parliament additions
- Senate roster gained the sorts the House had, plus its own axis — years to
  retirement, which the House has no equivalent of — and coverage counts, so
  the chamber is no longer decorative beside the House.
- **Forced turnover chart**: 96 birth dates give ten years of exact vacancies,
  every one filled by the PM of the day with no election. Fixed, not forecast.
- **Same bill, both chambers**: the join that makes two floor plans on one page
  worth having. C-14 shows the Senate rejecting what the House passed.
- Ridings tab gained a seats-per-province summary, clickable as a filter.

### Politics section connected — one accountability source
`wtf-accountability.js` is now the single source for officers, their findings,
Governor-in-Council vacancies and the finding kinds. Officers, Ethics,
Cross-Watch and the party records all read it, so a finding cannot appear with
one wording on one page and another elsewhere.

**Officers paywall — the split, decided and recorded.** The live page gates the
whole of `/officers` as Starter+. This rebuild applies the same precedent the
MP profile records (owner decision 2026-08-18: committee membership is a public
record, so paywalling it buys no exclusivity): the **office itself** — mandate,
what it can actually do, appointment route, term — is public record and stays
free; the **compiled findings list** is the newsroom's own work and is the
Starter+ layer. The gate names what it withholds (count and year span) rather
than teasing. Preview toggle uses `sessionStorage['wtf-gate-preview']`, the same
key as the MP and senator profiles, never the tier flag. Gated finding text is
excluded from search so a query cannot confirm gated content by matching on it.
**Do not ship this page fully free by accident** — an earlier pass did exactly
that without recording the decision.

**Enforcement power is derived, never asserted.** A hardcoded "2 of 17 with
enforcement power" was contradicted by four cards on the same screen and
understated the regime — the wrong direction for this page. `OFFICERS` now
carries an explicit `enforcement` kind and `enforcementWhy` reason, the stat is
computed from it, and the card shows the specific power. Five of eighteen
offices can do more than publish: the Commissioner of Lobbying (two-year ban),
the Information Commissioner (binding orders since 2019), the Chief Electoral
Officer (the only route that can end in a conviction), IG Montréal (can cancel
a contract outright) and the Board of Internal Economy (can order repayment,
but is MPs judging MPs). **`NO_REMOVAL` is the one claim true of all of them**
and is shared with the ethics page so the two cannot drift.

Stat labels now say what they count — "Offices on this page" 18 against
"Independent officers" 17 — after two different totals for the same list
appeared on one screen.

**Officers of Parliament** was the thinnest page in Politics — eight mandates
behind a paywall and no findings — and is now the section's spine: 18 offices
(federal, provincial and municipal equivalents) with mandate, **what each can
actually do**, appointment route, term, and every finding on record. The
recurring theme is stated: only 2 of 17 independent offices hold any enforcement
power. The Board of Internal Economy is listed and explicitly flagged as **not**
an independent officer, since it is composed of MPs.

**Ethics rulings** listed rows as "Report on a minister" — no name, no date, no
citation, unusable for a reader and indefensible on a site built on checkable
claims. Now 7 named findings with the report cited, plus an **enforcement gap**
table: not one ethics office in Canada can remove a member or impose a fine, and
the strongest available outcome is a published finding the legislature may
ignore. Where a commissioner publishes without naming a subject (Québec 2023),
the row says so rather than looking like our omission.

**Cross-Watch** was a stub, and the four registers it should join were unlinked
lists. It now indexes 93 entities across six registers — officer findings,
ethics rulings, lobbying, appointments, vacant posts, coverage — each tagged
with the **Watch series** that collected it, and finds 8 genuine cross-register
matches (Bill Morneau: ethics + lobbying; Immigration and Refugee Board:
appointment + vacancy; Auditor General: findings issued + coverage).

**No score, no ranking.** Entities order by register count, which is a count of
records and not a measure of influence. The page states that a match is a fact
about paperwork rather than a finding about a person, that lobbying registration
records compliance with the law requiring it, and that exact-name matching
produces false positives in any system — which is why every row shows the
source record, not just the name.

### Three more Politics gaps closed
- **Party discipline on MP profiles.** Votes against own caucus, derived from
  the caucus majority on each division. Framed carefully: a high rate is not
  loyalty and a low one is not independence, because most divisions are
  procedural and unanimous within a caucus — what matters is which votes the
  exceptions were on.
- **Vacant Governor-in-Council posts.** An appointment is a decision; a vacancy
  is also a decision, taken by not deciding. Six posts, longest vacant 337 days,
  each with its consequence named (a tribunal that cannot constitute a panel is
  a different fact from an unfilled board seat). Unlike a by-election, **no
  statute sets a deadline**, and the page says so.
- **Municipal council layer.** 274 council seats across 12 cities, with
  residents-per-seat and story counts. Vancouver and Surrey elect at-large so no
  councillor answers for one neighbourhood; Montréal runs 103 seats across 19
  boroughs. Links through to ward races.

### Branding: monograms, not other people's logos
`wtf-brand.js` (`window.WTFBrand`) renders a **monogram** built from the party's
own colour and authored initials — LPC, CPC, CAQ, QS — and a **city shield**
for municipal entries, since most Canadian municipalities have no parties and
the city is the honest unit there (TO, MTL, VAN, YYC).

Two constraints, both deliberate:
- **We do not ship party logos or municipal crests.** They are trademarks. The
  monogram is a designed placeholder, not an imitation. When a real asset
  exists, `logoUrl` fills the same tile and the monogram becomes the `onerror`
  fallback — identical to the member-photo pattern.
- **A monogram is identification, never endorsement.** It carries party colour
  only, never a delivery verdict or a lean band, so a Conservative blue tile
  cannot be misread as a right-lean score.

Loaded on `/parties`, `/platforms` and `/races` so a party looks the same
everywhere it appears. Initials are authored in `MONO`, not derived, because
"Québec solidaire" must initialise to QS and not "Qs".

### Record entries expand to full context
`wtf-record-context.js` keys explanation on `partyId|title` — roughly 60
entries covering delivered, reversed and findings across all 14 parties. Each
carries `context` (mechanism and meaning), an optional `caveat`, and a
`source` document.

**An entry with no context renders no expander.** Nothing is padded to make the
interface look complete: a missing explanation is better than an invented one.

The caveats are the substance. They record things a bare verdict removes —
that the pre-2020 deficit miss and the post-2020 fiscal position are different
facts; that the Bloc cannot hold a referendum because it is a provincial
instrument, so recording it as broken would penalise a party for lacking a power
it never claimed; that Montréal's inspector general generates findings
comparable cities would never produce, so finding counts are not comparable
across oversight regimes; and that Calgary's blanket rezoning was delivered and
helped end the mandate, which promise trackers rarely admit is possible.

### Political parties (`/parties`) — new, 25 years
Index by level (federal / provincial / municipal), profile at `?party=<id>`.
14 parties, 2000–2026. Heads the Politics menu, since a party is the unit the
rest of that menu hangs off, and also linked from Elections as "Party records".

**There is no grade, by decision.** A party record reduced to a score would be
the newsroom's opinion wearing the clothes of a measurement, which is the exact
move this site exists to criticise. So "good and bad portfolio" renders as three
columns of cited facts: **delivered**, **reversed or abandoned**, and
**findings by independent officers** — each with a date and a document type.

Two asymmetries are stated on the page rather than smoothed away, because both
would otherwise be read as merit:

- A party that has never governed has almost nothing in the delivered column.
  That is opportunity, not intent — so the time-in-government bar is labelled
  as the *precondition for delivery*, not a merit ranking.
- A party that governs for twenty years accrues more officer findings than one
  that governs for two. More government means more auditing, so raw finding
  counts favour whoever held office least.

**Seats AND vote share are stored for every election** (`HOUSE_SIZE` per year so
seat share is comparable across a growing House). Share-of-seats is highlighted
where it diverges from the vote by 8+ points. Roughly 39% of the vote produced a
majority in 2011 and again in 2015, for different parties — that gap is the
most under-reported fact in Canadian politics and the reason both numbers are on
every row.

Party profiles join the promise tracker on the party's `short` name, so the two
pages cannot disagree about a commitment.

### Platforms & promises (`/platforms`) — new
Party commitments quoted from the platform that made them, with evidence for
where each now stands. Three tabs (federal / provincial / municipal),
hash-addressable. Reachable from both Elections ("Platforms & promises") and
Politics ("Promise tracker") — it is what a campaign promise becomes after the
campaign, and it belongs beside the members who voted on it.

**Four rules are structural, not editorial preference. Preserve all four.**

1. **"Not done yet" is not "broken."** This is the failure mode of almost every
   promise tracker and the single reason they mislead. `stalled` = no
   measurable movement, mandate still running. `broken` = explicitly reversed
   or cancelled, or mandate ended undelivered. Every unfinished item renders
   the remaining mandate ("18 months of this mandate remain, so this is
   unfinished rather than failed"), computed from `PARTY_META[party].mandate`.
   **Do not merge these two statuses to simplify the schema.**
2. **A party out of power cannot deliver.** Opposition commitments carry
   `status:'position'`, are excluded from `SCORED`, and their card shows no
   delivery bar at all — with the reason stated. A kept-promise rate for a
   party unable to legislate measures nothing and flatters whoever is out of
   office.
3. **Every verdict cites a document**, and the citation names the **Watch
   series** that collected it: Gov Watch (legislation, bills, votes, orders),
   Civic Watch (programs, bylaws, council), Market Watch (budget lines, tax
   rates), Legal Watch (reversals, litigation). `evidenceType:'none'` renders
   as "No source" and forces `stalled` rather than a verdict it has not earned.
4. **Rows sort by how load-bearing the verdict is** — broken, stalled, partial,
   in progress, not started, kept. A kept promise is the least newsworthy row
   on the page; leading with it would read as a scorecard for the government.

The scorecard also shows **mandate elapsed** as a progress line, because a 30%
kept rate at 20% of a mandate and at 95% of one are different findings.

### Global-scope collisions — a standing rule
Adding `wtf-corpus.js` to the elections page killed the entire page: both files
declare `PROVS` and `NOW` at top level, and a duplicate top-level `const` is a
**parse-time** error, so not one line of `wtf-elections.js` ran. Same bug class
as `wtf-ridings.js` vs `wtf-mps.js` (`$`, `esc`, `PROV_FULL`).

**Rule: every page script runs inside an IIFE and exports only what markup calls
(`window.showEl`).** Now scoped: `wtf-elections.js`, `wtf-elections-extra.js`,
`wtf-races.js`, `wtf-ridings.js`, `wtf-senator.js`. Audited all 45 pages for
pairwise identifier overlap between co-loaded scripts — 0 clashes. In Flask,
Jinja includes make this easier to reintroduce, not harder; keep the IIFE.

Second lesson from the same turn: a splice between two comment markers deleted
five working blocks that had been inserted between them. The restored blocks
live in `wtf-elections-extra.js`, which reads only the global DATA files and
never the other script's helpers.

### By-elections, electors, and a regraded readiness measure

**By-elections** are their own tab, because they are the one contest that is
CALLED rather than fixed: the Speaker reports a vacancy, and the writ must issue
inside a legal window (federally 11–180 days, `Canada Elections Act` s.31 and
s.57(1.1)). Where in that window the vote lands is the government's discretion,
so the page measures **days a seat has been vacant** and **days left to call**,
not just an election date. Turnout is shown against the same district's general
election — Toronto Ward 19 went 16.8% against 38.2%, and the winner took it by
four points.

**Electors** sit in the turnout tab because they are its denominator. The 2021
row is the reason: the register was flat, 1.3M fewer ballots were cast, and the
rate fell 4.4 points — reporting vote counts alone would have missed it.
Provincial registration is shown against population with the gap explained
(under-18s, permanent residents, other non-citizens), so the shortfall is not
presented as apathy.

**Readiness was regraded twice, and the page shows its own working.** Both
discarded versions are documented on the page, because the failures are
instructive and a reader should be able to see why the current measure exists.

- **v1 — binary freshness.** A city counted as ready if any source filed
  anything inside a freshness window. Returned 30 of 31 and read as
  reassurance: it measured whether we had a feed, not whether anyone was
  watching a council.
- **v2 — stories per 100,000 residents.** Inverted the thing it measured.
  Churchill (pop. 870) would clear the threshold on one story; Toronto needed
  twenty-eight for the same grade. News does not scale linearly with
  population — one reporter can cover one council whether the city has 900
  residents or 900,000. Every province came out at 0%, and **a measure that
  cannot discriminate between provinces is not a measure**.
- **v3 — absolute bands** (current): None / Minimal (1–2) / Some (3–9) /
  Sustained (10+, roughly weekly). Population and stories-per-100k are shown
  as CONTEXT beside each city and are explicitly not the threshold.

The panel also states plainly that the counts derive from the 24-story sample
corpus, so they measure the size of the window rather than real municipal
output, and that the readable signal is the shape of the gap between provinces
rather than the absolute figures. **Keep that disclosure until the live corpus
is wired in** — without it the panel reads as a claim about the newsroom that
the data cannot support.

The three things the measure still cannot see are stated on the page: campaign
vs other council stories, attendance vs rewritten release, mentioned-in vs
written-from — all of which mean the real picture is worse, not better.

### Results, deadlines, turnout and the coverage arc
Five additions to the elections section, and one deliberate refusal.

- **Results.** `PAST_RACES` carries winner, margin in points of the vote,
  turnout, ballots cast and the full tally. Without this the whole section only
  pointed forward, and on 6 October the Québec pages would have had nothing to
  say. Past races appear behind a "Past results" toggle on `/races`, with the
  stat row switching to turnout and margin metrics.
- **Deadlines.** Nomination close, registration cut-off, advance voting and
  mail-in request per election. Passed deadlines are shown as closed rather
  than hidden — knowing a slate is already final is as useful as knowing one
  is still open, and **nomination close is when a district with no candidate
  becomes a story rather than a wait**.
- **Turnout by level.** Federal 68% against ward races at 29%. Set beside the
  coverage counts, that forty-point gap is the strongest case the site can make
  that thin local reporting has consequences.
- **Coverage arc.** Articles per week before / during / after each past vote,
  with a "% in vote week" spike ratio. Grande Prairie got two articles and 22%
  turnout; Calgary got 38 and cleared 38%. Presented explicitly as a
  correlation across six cities, not a causal claim — but it is the
  correlation a newsroom should be willing to publish about itself.
- **Riding-to-race join.** A race with a riding name links to
  `/mps?rd=<name>#ridings`, which selects and flies to that boundary. Matches on
  name with a case-insensitive fallback, and says so when the 2023
  redistribution renamed the district rather than failing silently.

**No polls or projections, by decision.** Aggregating horse-race numbers would
put this newsroom in the prediction business, and a site whose premise is that
framing shapes perception should not spend a campaign telling people who is
winning. The published comparison is retrospective and checkable instead:
coverage against turnout against outcome. Do not add an aggregator later
without revisiting that reasoning — it is stated on the page.

### Candidate "Coverage" link was a dead end
Candidate names are not tagged in the corpus (verified: no match for Legault,
Chow, Plante or Carney), so a per-candidate coverage search returned nothing for
every candidate — the same defect class as the riding coverage link. Removed;
incumbents now link to their own profile, which is real. Restore a per-candidate
coverage link only once nomination-time entity tagging exists.

### Candidates & races (`/races`) — new
Per-RACE, not per-candidate: during a campaign the useful question is "who is
running here", and a per-candidate page for a private citizen with no record
would be a page about someone we know nothing about. Index at `/races`
(hash-addressable by level), detail at `/races?race=<id>`.

Three rules are load-bearing and must survive implementation:

1. **Confirmed nominations only.** A nomination is a fact with a date and a
   filing body. `status:'declared'` entries are shown in a separate panel with
   no mention count, because counting coverage of an unconfirmed candidate
   treats an intention as a candidacy. Never name a private citizen as a
   candidate before their nomination is filed.
2. **Incumbency is a flag, not a record.** A sitting member is marked and the
   race links OUT to their profile; the race never renders a voting record.
   Printing it inside a race would hand one candidate a page their opponents
   cannot have. `incumbent.running:false` is shown explicitly — a retiring
   member must not read as a candidate.
3. **Municipal is non-partisan.** Most Canadian municipalities have no parties,
   so party colour is ABSENT by design rather than defaulted to grey. Vancouver
   (ABC / OneCity / COPE) and Montréal (Projet / Ensemble) run civic parties
   and are flagged `partisan:true`.

Mayors AND wards, since a ward councillor decides zoning on one street.
Coverage is counted **from each candidate's own nomination date**, so a late
nomination is not penalised — and the panel states plainly that an incumbent
leads almost every one of these because office generates coverage by itself.

An empty slate renders as "no nomination confirmed yet" with the days remaining:
that emptiness is the reporting, not a gap in our data.

## Data still owed by the database

The design files carry sample values for everything below. Each is marked in
the handoff as replace-on-implementation, and none should ship as-is:

- **Postal lookup must pin on the set slug, not the set name** (provincial-set
  trap). Represent returns provincial districts ("Alberta electoral district")
  and superseded federal representation orders in the same array; a
  `/electoral/i` name match reported Calgary-Buffalo, an Alberta provincial
  riding, as the reader's federal riding. Filter on
  `url.startsWith('/boundaries/federal-electoral-districts/')`. Keep this rule
  if the lookup moves server-side.
- **No riding-to-member chip** — a "Find the member" link from a riding was a
  dead end for 333 of 338 districts, so it is removed rather than left to
  return nothing. Add it back in the same commit that fills
  `parliament.mps.riding_name`, and add `riding` to the roster's search haystack
  at the same time.
- **Province filter on the House roster** — removed, not hidden: with province
  blank for 338 of 343 members it filtered on empty values. Restore the control
  in the same commit that fills the column.
- **MP riding and province** — blank in `wtf-parliament.js` for 338 of 343
  members and all 96 senators. The page renders an em dash and says the riding
  is not in the dataset. Do not derive these; an earlier hash-based fallback
  produced confident false claims about named MPs.
- **Party and caucus** — derived from seat arc position so the totals match the
  published standings (L 171 / C 139 / BQ 21 / NDP 5 / GP 1). Totals are right;
  an individual seat may not be.
- **Ballots, expenses, donations, lobbying contacts, disclosures, promises** —
  all seeded off the member slug for stability across reloads. Real sources are
  named in each section footer.
- **Senator age, appointment date and appointing PM** — derived, not read. The
  retirement-wave chart is only as good as these dates; it is the one chart on
  the site that becomes *more* accurate under real data rather than merely
  correct.
- **Provincial and municipal election dates** — hand-entered from fixed-date
  statutes, current as of Sept 2026. These need a scheduled re-check, not a
  feed: a premier calling early invalidates a date, and the page says so.
- **Bill vote tallies** — sample division records joined on bill number. The
  join key is right; the numbers are not.
- **Candidate nominations** — the shape is right and the riding, city and ward
  names are real, but the candidate names are samples except where they are
  sitting members or party leaders. Wire to Elections Canada's confirmed-candidate
  feed, Élections Québec, and per-city clerk filings. **The confirmed/declared
  distinction must be preserved by whatever feeds it** — collapsing the two
  would publish rumours about private citizens under a nomination heading.
- **Results, turnout and the coverage arc** — real in shape, sample in value.
  Turnout and margins must come from each returning officer; the arc must be
  computed from the corpus over real date windows rather than stored.
- **Findings and vacancies** — every finding describes a real, documented
  report and names its subject, but each needs its **report URL attached**. Wire
  vacancies to the Privy Council Office appointments feed. **Preserve the
  `unnamed` field** — some commissioners publish without naming a subject, and
  collapsing that into a blank subject would recreate the defect this rebuild
  fixed.
- **Cross-Watch matching** — currently exact-name with a small alias table.
  Production needs proper entity resolution; until then the false-positive
  warning on the page must stay, and no row should ever render without its
  source record visible.
- **Party logos** — `logoUrl` is unset everywhere. If real logos are licensed
  or permitted, drop them in and the monogram becomes the fallback; do not
  scrape them. Municipal crests generally cannot be reproduced at all.
- **Record context** — the explanations describe real, documented events, but
  each `source` is a document NAME and needs a URL or citation attached before
  publication. The `caveat` field is editorial judgement and should be reviewed
  by the desk, not treated as data.
- **Party electoral history** — seat counts and vote shares 2000–2026 are real
  published results and should be verified against Elections Canada and each
  provincial CEO before publication, not trusted from this file. Leadership
  dates are real. The delivered / reversed / findings entries describe real,
  documented events but need their **source document and citation attached** —
  a finding attributed to an Auditor General must link to the report.
- **Municipal party coverage is thin by nature** — most Canadian municipalities
  have no parties, so only Montréal and Vancouver have real civic parties here;
  Toronto is tracked as a mayoral administration and flagged as such.
- **Platform commitments** — the wording is drawn from real, publicly stated
  platform positions and the statuses reflect the real record as of Sept 2026,
  but each `text` should be replaced with the **verbatim platform sentence and a
  page or section reference** before publication. A paraphrase under a quotation
  mark is the one thing this page cannot survive. `checked` dates must be real
  review dates, and a stale `checked` should visibly age the verdict.
- **Watch series join** — `evidenceType` currently maps to a series by category.
  Wire it to the actual Watch record (bill id, OIC number, budget line, bylaw
  number) so a reader can open the source document.
- **Vacancies and by-elections** — the legal windows are real statute; the
  vacancy list is a sample. Wire to the Speaker's vacancy notices and each
  provincial/municipal clerk. **Keep the days-vacant and days-left-to-call
  figures** — an election date alone hides the discretionary delay.
- **Elector counts** — Elections Canada national figures are close to real;
  provincial splits are approximate. Replace with the official register.
- **Election deadlines** — hand-entered from each statute. These move, and a
  passed nomination date changes what the page should say, so they need a
  scheduled re-check.
- **Ward inventories** — only a sample of wards is listed per city. Toronto has
  25, Ottawa 24, Québec City 21, Montréal 19 boroughs; the full ward list per
  municipality has to come from each clerk.
- **Cabinet roles** — assigned to the government bench's most-covered members so
  ministers are distinguishable from backbenchers at all. Live reads
  `mp.cabinet_role`; replace before shipping.
- **Caucus baselines and "broke with caucus" flags** — the comparison is real in
  shape but the per-division caucus majority must come from the division record,
  not from which side won.

## Sync history

- 2026-09-01 — recorded as `KytranKatarn/what-the-fact-site`; that repo turned
  out to be the Coming Soon landing page, corrected above.
