# Live contracts — Money section, Journalists, CRTC (read from the repo 2026-09-02)

Captured so the rebuild can proceed without re-reading the repo. Source:
`what-the-fact/consumer/templates/{cost,economy,rates,journalists,journalist,crtc}.html`
and `consumer/static/js/cost.js` at `main`.

## /cost — "What Parliament Costs Canadians" (`cost.html` + `static/js/cost.js`)

Template is a shell of `data-cost-*` hosts; **all rendering is in `cost.js`**
against three cached APIs (single source of truth is `ingest.parliament.cost`):
`GET /api/cost/summary`, `GET /api/cost/mp/<id>`, `GET /api/cost/senator/<id>`,
`GET /api/cost/reconciliation` (`?members=all` for the full JSON download).

Layout, top to bottom:
1. Kicker "Accountability · Public money" · title · lede (verbatim: approximate
   cost of the federal legislature — every MP and senator's salary plus office
   expenses (travel, hospitality, contracts, staff); from public disclosures and
   Library of Parliament salary tables; pensions and central costs excluded; all
   figures approximate and cited).
2. **Headline**: `grand_total_5yr` huge (clamp 40–72px, red), then
   `fmtFull · approximate — <window.label>`, then amber line
   "＋ $X ministerial travel & hospitality (borne centrally — not in the total
   above) · combined ≈ $Y".
3. **Addenda** (`data.addenda[]`): partial years, e.g. current year-to-date with
   quarters listed, "$N disclosed so far — shown for completeness, not in the
   total above", split House (n MPs) · Senate (n senators) · ministerial; a
   projected full year only once ≥2 quarters are on file, always labelled an
   estimate.
4. **Stat tiles**: latest-year total (red) · change first→last year (%) · avg
   per MP / year · "MPs + senators" count.
5. **Chart** "The rising cost of Parliament": one stacked bar per year — MP
   salary + top-ups · MP office expenses · Senators — with legend. Plain divs,
   no chart library, heights as % of the largest total.
6. CTA "See every MP & senator →" (/mps) + "Each member's profile shows their
   own 5-year cost breakdown."
7. **Methodology panel** "How we calculated this — member by member": the
   reconciliation statement (headline = independent sum of every member; ✓ or ⚠;
   ministerial line; cross-check difference stated as $0 or rounding), then
   What's counted / What's excluded / The window (tracked automatically — a year
   enters the headline when its 4th quarter is disclosed) / Current year &
   projections / How members are matched (name-matched to the Library of
   Parliament roster; an unmatched official is not counted, so the total is a
   floor) / Data coverage rows (source · first→last · records) / Sources /
   Costliest members top N / download link.
8. **Honesty footer**: "⚠ <_note>" + Sources list (indemnity, office_expenses,
   senator_expenses).

Per-member panel (`renderMember`, used on mp/senator pages): 5-year total,
stacked bars per year (indemnity · role top-up · office), latest-year
breakdown table (indemnity, top-up, office travel/hospitality/contracts/staff,
total), ministerial box (borne centrally, combined figure), federal contracts
the minister's portfolio oversees (CanadaBuys via Gov Watch — NOT personal
cost), current partial year + projection, honesty block.

Honesty rails are mandatory: every figure labelled approximate, components
always shown, sources always cited, XSS-safe (textContent only).

## /economy — "Economy & Markets — M.A.R.K.E.T." (`economy.html`, namespace `wtf-ec-`)

- Label "M.A.R.K.E.T. · Market Analysis, Research & Knowledge for Economic Tracking"
- Title "ECONOMY & MARKETS" · desc "Business, economy, and foreign-policy stories
  from 46 Canadian outlets — bias-scored and geo-mapped. Follow the money behind
  the headlines." · attribution "Powered by WTF + Market Watch ↗"
  (https://market.kytranempowerment.com)
- Stats row: Economy stories · Business stories · Foreign policy · 46 outlets
- Section "Recent economy, business & foreign-policy stories": cards with beat
  pill (economy amber / business green / foreign-policy gold), outlet link,
  province tag, published time, BAND, title → /article/<id>, cluster footer
  "📰 N outlets covering this" → /cluster/<id>; empty state.
- Links: All Economy → /news?beat=economy · All Business → /news?beat=business ·
  All Foreign Policy → /news?beat=foreign-policy
- Market Watch CTA: "Want deeper market intelligence? Market Watch tracks stocks,
  commodities, and economic indicators alongside Canadian news coverage." →
  "Open Market Watch ↗"
Requested addition: historical indicator charts (CPI YoY, unemployment, GDP,
overnight rate, CAD/USD) with StatCan / BoC Valet series ids, release dates.

## /rates (`rates.html`, ARCHETYPE 3 data explorer)

Title "Bank of Canada rate decisions" · sub "Every cut, hike and hold since 2000 ·
Bank of Canada Valet API (series V122514)". Stat tiles: Overnight rate target
(as of date) · Decisions on record (2000–2026). **Starter+ gate** on the
decision table (Direction CUT/HIKE/FIRST as text, never colour alone · date ·
rate · change in bps). "About the overnight rate" block + BoC link +
/parliament/officers link. Requested addition: 2000–2026 decision-path chart
with era annotations as public historical background; keep the table gated.

## /journalists + /journalist/<id>

Directory (ARCHETYPE 2): h1 "Journalists" · "{total} writers tracked, captured
from bylines as articles are ingested. Coverage grows over time." · search form
(?q=) · `person_card` grid (name, "N articles", → /journalist/<id>) · "Showing
the top 200 by coverage volume — use search to narrow." · empty state.

Profile: back link · name · "Declared outlets: …" · stats (Articles, Outlets) ·
**free**: Outlets — where they publish (chips with counts → /source/<slug>);
Recent coverage (band dot, title → /article, outlet, date) · **Starter+**: Bias
lean — outlet bias of their coverage (band counts); Volume by month; Who they
cover — co-mentioned entities (name, type, count) · gate "Coverage analysis —
Starter+" · footer "Bylines captured from RSS feeds as articles are ingested."
Requested: integrate directory + our table + the profile sections in one page.

## /crtc (`crtc.html`)

Header "CRTC Decisions" · "{n} rulings · 2024–2026 · CRTC".
**Ownership concentration panel** (if owners_summary): "Media Ownership
Concentration" + badge "<label> · top 3 own N% of tracked outlets"; owner bars
(name, bar = share of tracked outlets, "N outlets · avg bias ±x.xx"), type
colours corporate / public / non_profit / independent; note "Bias scores are
rolling averages from AI analysis. Bar width = share of tracked outlets." →
/owners. Filters: All · Broadcasting · Telecom · Compliance (?type=). **Starter+
gate**: "280 CRTC broadcasting and telecom rulings (2024–2026) with cross-links
to WTF outlet profiles." Rows: decision number (→ decision_url), type pill
(Broadcasting / Telecom / Enforcement / Online News), "🔗 WTF source →" when the
subject is a tracked outlet, subject, description (200 chars), scope. About
block + CRTC index link + Media Owners link.

## Colour note for the rebuild
Live cost.js uses sky/amber/red/violet for cost components and the CRTC panel
uses red/blue for owner types and ±bias. Under the house rule (tokens carry
meaning; blue = right-lean, red = left-lean/accent) the rebuild should keep cost
components and owner types OFF the lean spectrum: e.g. salary `--wtf-text-2`,
top-up `--wtf-developing`, office `--wtf-accent`, senators `--wtf-aurora`; owner
types by shape/label rather than red/blue.
