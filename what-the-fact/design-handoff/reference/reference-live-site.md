# Live site reference — what-the-fact.com

Pulled 2026-09-02 from the live site. This is the source of truth for IA, routes
and counts. Where our build disagrees, the live site wins.

## Navigation groups (LIVE — ours is wrong)

| Group | Items (in order) |
|---|---|
| **News** | Latest news `/` · Activity log `/activity` · Weather `/weather` · Blindspot `/blindspot` · Divergence `/divergence` |
| **Politics** | MPs & ridings `/mps` · Municipal `/municipal` · Lobbying `/lobbying` · Appointments `/gic` · Ethics tracker `/ethics` · Officers `/parliament/officers` · Rates `/rates` |
| **Money** | Economy `/economy` · Cost of Parliament `/cost` · Markets `/markets` |
| **Media** | Sources `/sources` · Owners `/owners` · Journalists `/journalists` · CRTC `/crtc` |
| **Data** | Coverage map `/map` · Accountability chain `/chain` · Cross-Watch `/cross-watch` · Claims `/claims` · Developer API `/api/docs` · Education API `/edu` |
| **About** | Methodology `what-the-fact.tech/transparency` · The newsroom `/team` · Governance & ethics `/governance` · Score an article `/score` |

Nav right: `LIVE · 41 SOURCES` · search `/search` · Subscribe `/join` · Sign in `/login`.
Language switcher: **English / Français / Español**.

### How our build differs
- We have a **Parliament** group; live calls it **Politics** and includes Rates and Municipal in it.
- We made **Weather** a top-level group; live has it inside **News**.
- We have a **Research** group; live has **About**, and Methodology points off-domain to `.tech`.
- We are missing the entire **Data** group: `/map`, `/chain`, `/cross-watch`, `/claims`, `/api/docs`, `/edu`.
- Live routes we got wrong: Officers is `/parliament/officers`, Appointments is `/gic`.
- Live says **41 sources**; we say 40 in every footer.
- Live footer carries `what-the-fact.tech`, a live **C.R.E.E.D. Certified** badge image
  (`/api/creed-badge`) linking to `/governance`, and `creed-ai.org`, plus a
  **Weekly Bias Digest** signup ("Top stories + outlet bias averages, Mondays").

## /mps — Members of Parliament

Title: `Members of Parliament · What The Fact`
H1: `🏛 Members of Parliament`
Sub: `337 current MPs tracked · votes, media coverage, accountability intelligence`

Controls: `🏛 House of Commons` / `🔴 Senate` toggle · party filter · province filter ·
`🏛 Seating Map` with Hide map toggle and a SPEAKER marker.

**House standings (337):** Liberal 171 · Conservative 139 · Bloc 21 · NDP 5 · Green 1.
Grouped by party, alphabetical within party.

Each card: avatar, name, party, riding, article count (`n articles`), and a role badge
where applicable. Links to `/mp/<slug>`.

Role badges seen: `⭐ Prime Minister` (Mark Carney, Nepean, 3414 articles) ·
`⭐ Opposition Leader` (Pierre Poilievre, Battle River—Crowfoot, 427) ·
`⭐ Bloc Leader` (Yves-François Blanchet, Beloeil—Chambly) ·
`⭐ NDP House Leader` (Don Davies, Vancouver Kingsway) ·
`⭐ Green Leader` (Elizabeth May, Saanich—Gulf Islands) ·
`🏛 Minister of …` on cabinet members (truncated in the card).

**Senate section:** `🔴 Senate of Canada — The Red Chamber`,
`96 current senators appointed until age 75. Six caucus groups sit in a
red-upholstered horseshoe chamber.` SPEAKER marker.
Source line: `Source: Senate of Canada · Data as of May 2026`.
Caucus groups listed: ISG 38 · CSG 17 · PSG 17 · C 11 · GRO 5 · Non-affiliated 5.
Senators render as `Surname, Given` with caucus + region. Links to `/senator/<slug>`.

Note: the page claims 96 senators; the listed rows total 93. Three non-affiliated
rows carry `—` for region, so the roster is visibly incomplete on the live site too.

## /parliament/officers — Officers of Parliament

Title: `Officers of Parliament — Canada's Accountability Watchdogs · What The Fact`
H1: `Officers of Parliament`
Sub: `8 independent watchdogs who report directly to Parliament — not to the
government of the day. Their findings and rulings are among the most
consequential accountability events in Canada.`

**Gated.** Panel reads `Officers of Parliament — Starter+`, body `Full profiles of
Canada's 8 independent accountability watchdogs — mandates, current holders, and
cross-product intelligence links.` CTAs: `Unlock with Starter →`
(`/login?next=/parliament/officers`) and `See plans` (`/join`).

Ungated explainer — `Why Officers of Parliament matter`:
fixed terms, cannot be removed by the Prime Minister, report directly to the House
or Senate creating a firewall against political interference; when the Auditor
General flags waste or the Ethics Commissioner rules on a conflict, it becomes a
formal parliamentary record.

Pager at the foot: `← Members of Parliament` / `Media Owners →`.

Named officers referenced in the meta description: Auditor General, Ethics
Commissioner, Commissioner of Lobbying.

## Template-level findings (from uploads/wtf-design-bundle/templates/)

The uploaded bundle IS the real Flask source — its officers.html paywall copy
matches the live page verbatim. GitHub does not carry it: `what-the-fact-site`
holds only the marketing landing page + `css/style.css`, and `kytran-news`
holds `app.py` with no templates committed.

### There are two generations of template in this codebase
Most Politics/Media pages have been migrated to the design system and now use
`_archetypes.html` macros — `record_card`, `person_card`, `record_links`,
`paywall` — with `wtf-a-*` classes and `var(--wtf-*)` tokens. Their header
comments say so explicitly, and name what was removed: emoji headings, an
'Orbitron' heading font the site never loaded, hardcoded hexes.

Migrated: `officers.html` · `gic.html` · `owners.html` · `rates.html` · `journalists.html`

**`mps.html` is NOT migrated** — it is still the pre-design-system page:
`font-family:'Orbitron'` on the title, hardcoded `#060d14` / `#1a3a5a` /
`#0af` / `#e5e7eb` / `#6b7280`, its own `.wtf-mps-*` and `.wtf-mp-*` block,
emoji in the H1. It is the largest page in the group and the one most visibly
off-system. This is the single biggest consistency defect found so far.

### Data contracts (keep these unchanged)
- `officers.html` — `officers[]`, `is_subscriber`
- `gic.html` — `appointments[]`, `depts[]`, `dept`, `is_subscriber`
- `owners.html` — `owners[]`, `source_count`, `unattributed`, `is_subscriber`
- `rates.html` — `current`, `decisions[]`, `is_subscriber` (Starter+ gated)
- `journalists.html` — `journalists[]`, `total`, `q`
- `mps.html` — `mps`, `parties`, `provinces`, `party_filter`, `province_filter`,
  plus `ALL_MPS` and senator data injected to JS

### /mps mechanics worth preserving
- Tabs are `wtfTab('hoc'|'senate'|'parties')`, filters POST to `/mps` via GET form.
- Seating map is a real `viewBox="0 0 700 330"` SVG with a **per-MP seat coordinate
  table** (`SEAT_XY`, keyed by slug, e.g. `"aaron-gunn":[69.1,245.9]`) — real
  positions, not generated. Leaders get a glow filter (`feGaussianBlur`) + halo.
- `LEADERS` map assigns titles by slug (`mark-carney` → Prime Minister).
- Cards carry `photo_url` with a 👤 fallback, `party_colour`, `cabinet_role`.
- Legend order: NDP, Green, Bloc, Liberal, Conservative, Independent.
- Senate caucus colours: C `#3b82f6` · ISG `#cc0000` · CSG `#059669` ·
  PSG `#7c3aed` · GRO `#b45309` · Non-affiliated `#888888`.
  Labels: Conservative · Independent Senators · Canadian Senators Group ·
  Progressive Senate Group · Gov. Representative · Non-affiliated.
  Senator popups link `/senator/<slug>`.

Note: those party/caucus colours collide with the bias spectrum tokens
(`--wtf-left` red → `--wtf-right` blue). Party colour and lean colour must stay
visually distinct or a Conservative blue dot reads as a right-lean score.

### /cost — What Parliament Costs Canadians
Kicker `💵 Accountability · Public money`, H1 `What Parliament Costs Canadians`.
Lede: approximate cost of the federal legislature — every MP and senator's salary
plus office expenses (travel, hospitality, contracts, staff), drawn from public
disclosures and the Library of Parliament's published salary tables. **Pensions and
some central costs are excluded.** All figures approximate and cited on the page.
Uses `.cost-*` classes and a `data-cost-summary` hook.

## Not yet pulled
`/cost` · `/gic` · `/ethics` · `/claims` · `/chain` · `/cross-watch` · `/score` ·
`/governance` · `/edu` · `/api/docs` · `/mp/<slug>` · `/senator/<slug>`
