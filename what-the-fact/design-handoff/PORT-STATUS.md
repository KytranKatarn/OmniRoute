# Design port status

The single place that says which design pages are live. **Claude CLI updates
this file in the same PR that changes a template.** Claude Design reads it
before designing anything, so it never works against stale code.

Status: `todo` · `pr` (open, add number) · `merged` · `live` (deployed and checked)
Spec: `design-handoff/<design file>`. Rules: `.design-sync/DESIGN-BRIEF.md`.

| # | Design file | Template | Status | PR | Notes |
|---|---|---|---|---|---|
| 1 | shell (`_nav.html`, `wtf-shell.css`) | `base.html`, `static/style.css` | pr | #3544 merged, #3548 | Logo + brand cyan (#3544). Nav parity: bar ground, one row >820px, LIVE pill, globe + `EN`, search circle, SIGN IN as text, chip order. Repo source never had the ECONOMY emoji seen on the live site — deployed image is older than main |
| 2 | `wtf-home.html` map zone | `index.html` | merged | #3546, world wiring this PR | Leaflet -> `wtf-map.js` (#3546). World button now drives the real Natural Earth projection: country lean/volume layers, real names, click = that country's feed. The "projection coming" note is gone |
| 3 | world projection | `static/js/wtf-map.js` | merged | #3549 | `setScope('world')` on the shared map (Natural Earth, `/static/world-countries.geojson`, lazy). Canada stays the default. Homepage World button wiring is a follow-up after row 2 merges |
| 4 | `wtf-home.html` rest (weather strip glyphs, feed spread, gate) | `index.html` | merged | #3547 | Weather strip + Wildfire-and-alerts band ported. 6th tile 'Spread pressure' on this branch from `aurora_map.spread_pressure()` (row 8b's index), labelled **current conditions** — the design's 'next 48h' forecast is NOT claimed; omitted if the station table can't be read, em dash under 2 inputs. Feed spread + gate not done |
| 5 | `wtf-news.html` | `news.html` | partial (5a) | | Functionally already ahead of the design (stat strip, lean mix, filters, density, saved). 5a: header (eyebrow, sentence-case serif title, centred lede with the live source count) + tiles held to content width. Remaining: design's filter rows as pills (window/verdict), drop the outlet logo carousel for the OUTLET row |
| 6 | `wtf-archive.html` | `archive.html` | partial (6a) | | Live is functionally ahead (7/30/90/365, custom range, CSV export, sort, blindspot badge, no-script). 6a: centred eyebrow/title/lede + a content-width container (page was flush to the left edge) + tighter tiles. Not ported: design's '23 / 24 stories fact-checked' tile (README: counts outlet rows, not stories) and sample figures. Remaining: filter pill rows, lean-mix bar placement |
| 7 | `wtf-article.html` | `article.html` | partial (7a) | | Live already carries most of the design's sections (jump nav, What we measured, B.I.A.S., compare, verify, cite, how scored). 7a: fixed the layout defect — right-hand panels shared grid ROWS with the main column, leaving ~250px blank gaps on the left; they now sit in a real aside. Remaining: hero/meta styling, pickup-order timeline, analyst note (needs data — check first), prev/next |
| 8 | `wtf-weather.html` | `weather.html` | partial (8a, 8b, 8c) | | 8b: province spread-pressure index (current conditions from real rows, formula printed, 'no data' when under 2 inputs; NOT a forecast — A.U.R.O.R.A. predictions to be scored against it later). 8a: counted alert header + one scrolling strip, clean summaries (no leaked `###`), evacuations folded with counts so the map is reachable. 8c: forecast accuracy — live already has the real DB-backed /weather/accuracy page (14k+ checks, persistence baseline, worst call); the design's block uses hard-coded sample numbers so it is NOT ported. Fixed the misattribution: the scored series is Environment Canada's forecast, not ours. Remaining sub-slice: AQHI panel parity. NOT ported: the design's generated fire perimeters (sample shapes, not data) |
| 9 | `wtf-city.html` | weather city view | todo | | |
| 10 | `wtf-mps.html` | `mps.html` | partial (10a) | | Live already has the seating map, tabs, photos, filters. 10a: centred eyebrow/title/lede + content-width container (lede count = live `mps|length`, not the design's sample 343). Riding / province / party stay from DB — never derived. Remaining: stat tiles (needs per-party seat tallies from real rows), non-emoji tab labels |
| 11 | `wtf-mp.html`, `wtf-senator.html` | `mp.html`, `senator.html` | todo | | |
| 12 | `wtf-blindspot.html` | `blindspot.html` | live (12a) | #3566 | 12a: shared `.wtf-pg-*` header + 1080px container (centred eyebrow, serif title, lede keeps the live definition and adds the design's 'a coverage gap, not proof of suppression'). Remaining: design's 5-tile stat row (called / balanced / left / right / too-thin — from real rows), filter bar, row layout |
| 13 | `wtf-divergence.html` | `divergence.html` | todo | | |
| 14 | `wtf-clusters.html` | `clusters.html` | live (14a) | #3566 | 14a: shared `.wtf-pg-*` header + container. Remaining: row layout / filters. Row 13 (divergence) has several views — own slice |
| 15 | `wtf-lobbying.html` | `lobbying.html` | todo | | |
| 16 | `wtf-gic.html` | `gic.html` | todo | | |
| 17 | `wtf-ethics.html` | `ethics.html` | todo | | |
| 18 | `wtf-officers.html` | `officers.html` | todo | | Gate moves below mandates — see README |
| 19 | `wtf-municipal.html` | `municipal.html` | todo | | |
| 20 | `wtf-parties.html`, `wtf-platforms.html` | `parties.html`, `platforms.html` | todo | | |
| 21 | `wtf-elections.html`, `wtf-races.html` | `elections.html`, `races.html` | partial | races live; elections calendar on this branch (migration 085, curated + verification gate, drift-guard alarm). **All seed rows unverified — dates hidden until verified (see migration header).** Not ported: federal result bar, provincial map/party/premier, by-elections, municipal (planned: major cities) | |
| 22 | `wtf-economy.html` | `economy.html` | todo | | |
| 23 | `wtf-rates.html` | `rates.html` | todo | | |
| 24 | `wtf-cost.html` | `cost.html` | todo | | |
| 25 | `wtf-global.html`, `wtf-debt.html` | `debt.html`, `/global` | partial (25a) | | **25a `/debt` is REAL.** Weekly ingest of Statistics Canada 10-10-0172-01 (annual 1990→) + 10-10-0015-01 (quarterly, current to Apr–Jun 2026) + nominal GDP into `market_watch.fiscal_federal_*`; page shows latest-year stats, **2026 year-to-date vs same quarters of 2025**, an 8-quarter table, 11-year series, revenue/expense breakdown and a by-measure "better or worse". ⚠️ **Years are CALENDAR years (verified: the four quarters sum exactly to the annual), NOT Public Accounts fiscal years** — design labels ("15–16 … 24–25") and its sample numbers were not used. Not ported (no data): by-department table (Public Accounts Vol. II), "interest exceeds health transfers", Watch chips. **25b: Gov Watch bridge** — federal contracts SIGNED by department and year (value at signing, each contract counted once; NOT spending) via `scripts/gov_contracts_bridge.sh` (Citadel host cron, single-transaction, heartbeat + drift alarm). Department comes from the file's `owner_org_title`, NOT `buyer_name`. `/global` still a placeholder — needs a Global Affairs source |
| 26 | `wtf-markets.html` | `markets.html` | todo | | |
| 27 | `wtf-sources.html`, `wtf-outlet.html` | `sources.html`, `source.html` | todo | | |
| 28 | `wtf-owners.html` | `owners.html` | todo | | |
| 29 | `wtf-journalists.html` | `journalists.html`, `journalist.html` | partial | | Cards/Table toggle added on this branch (both views server-rendered, client flip). Not ported: medium filter, grouping, inline profile (no per-journalist medium/beat data). Delete the green-centre ramp |
| 30 | `wtf-crtc.html` | `crtc.html` | todo | | |
| 31 | `wtf-echo.html` | `echo.html` | partial (31a) | | Route already real (FTS counts from `wtf.articles`; see `echo_data.py`). 31a: shared centred header + container. Deliberately NOT ported, no data: pickup %, who-posts-most, Watch cross-links |
| 32 | `wtf-map.html` | `map.html` | todo | | Already on `wtf-map.js` |
| 33 | `wtf-chain.html` | `chain.html` | todo | | |
| 34 | `wtf-cross-watch.html` | `cross_watch.html`, `entity.html` | todo | | |
| 35 | `wtf-claims.html` | `claims.html` | todo | | |
| 36 | `wtf-search.html` | `search.html` | todo | | |
| 37 | `wtf-activity.html` | `activity.html` | todo | | |
| 38 | `wtf-methodology.html` | `methodology.html` | todo | | |
| 39 | `wtf-team.html` | `team.html` | todo | | Roster from directory API |
| 40 | `wtf-governance.html`, `wtf-creed.html` | `governance.html`, `creed.html` | todo | | Grade from `/api/creed-badge`, never hand-entered |
| 41 | `wtf-literacy.html`, `wtf-score.html`, `wtf-edu.html`, `wtf-api.html` | matching templates | todo | | |

## Audit 2026-10-01 — the `todo` column is stale for most rows

Structural audit of `consumer/templates/` against the design files. **~37 templates
already carry a "reconciled vs the Claude Design mockup" comment** with the gaps
documented as *Deliberately NOT added* (reason: no backing data, fabricated sample
numbers in the prototype, or a larger build). So most `todo` rows below are ported;
what remains is the documented gaps, not the page. Not verified in a browser.

Documented remaining gaps (from the template comments): journalists (medium grouping,
inline profile), sources (stat-tile filters, compare tray, band scale bar),
search (kinds facet, beat/lean facets), municipal (silent-cities panel, council table —
needs a city/province registry), cross_watch (inline entity detail view), ethics
(jurisdiction/office filters, finding badge — no column), governance (per-event feed),
weather_city (hourly/AQI/sun-moon — no ingest).

Design pages with **no template or route** at audit time: `wtf-debt` (since built, row 25a),
`wtf-global` (PR #3573, open), `wtf-elections` (calendar on this branch), `wtf-platforms`
(still a placeholder — needs a curated-document + human-review pipeline, see
`docs/specs/2026-10-01-wtf-missing-data-pages.md`). Name mismatches: city→`weather_city.html`,
accuracy→`forecast_accuracy.html`, api→`api_docs.html`, outlet→`source.html`.

`wtf-404` is ported on branch `feat/wtf-design-port-batch1` (`404.html` + app-level
handler; `/api/` paths excluded). Unmerged, untested in a browser.

Templates are the likely target by name. Confirm the real filename in
`consumer/templates/` before starting a row, and correct this table if it differs.

---

## Rows 1 and 2 are blocked

The standing brief says to apply two prepared PRs, `pr-01-shell-branding/` and
`pr-02-homepage-map/`. **Neither exists** — not in `design-handoff/`, not in the
handoff zip, not in any other bundle on the host (checked 2026-09-23). Rows 1 and
2 stay `todo` until Claude Design delivers them **as a PR into this repo**, not as
an archive. Start at row 3 or later in the meantime; nothing else depends on them.
