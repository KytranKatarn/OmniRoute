# Handoff: What The Fact — newsroom rebuild (46 pages)

## Overview

A rebuild of the What The Fact newsroom front end: 39 pages covering the
homepage, the live feed, the full archive, article pages, the weather and
wildfire product (A.U.R.O.R.A.), both chambers of Parliament, and the Media,
Data and About sections. The work was a design review that turned into a
rebuild — the notes throughout call out where the live site's own numbers
contradict each other, and those corrections are part of the deliverable.

## Where this goes

**Repo:** `KytranKatarn/archie-platform`, branch `main`, subdirectory
`what-the-fact/`. The newsroom is a subdirectory of a monorepo, not its own
repo — `KytranKatarn/what-the-fact-site` is the April 2026 "Coming Soon"
landing page and a different codebase.

**The app:** `what-the-fact/consumer/` — Flask. `routes.py` (268KB, ~30
routes), `templates/` (49 Jinja templates), `static/style.css` (the shared
shell). Each design file maps to a template; the mapping table is in
`reference/github.md`.

**Out of scope:** `what-the-fact/tech/` is a separate domain with its own
stylesheet. `what-the-fact/design-reference/` holds 19 `.dc.html` artboards
from an earlier design session — `.design-sync/NOTES.md` says explicitly that
they are unrelated and should not be uploaded. Do not treat them as the
current design.

**`.design-sync/` is not a push path.** It bundles `consumer/static/style.css`
*into* the design system, one-way, styles only. Nothing in this handoff reaches
the repo through it.

## About the design files

The files in this bundle are **design references created in HTML** —
prototypes showing intended look and behaviour, not production code to drop
in. The live product is Flask + Jinja2 templates against a Postgres database.
The task is to recreate these designs as Jinja templates in that codebase,
reading real values from the database instead of the sample constants here.

Where a page here has a `<script>` block computing values from `wtf-corpus.js`,
that logic belongs in the Flask view. Where it filters or sorts client-side
(archive, feed, rosters), keep that client-side — it is deliberate, since the
whole point is exploring a result set without a round trip.

## House conventions — follow these exactly

The repo already has an **archetype macro system** at
`consumer/templates/_archetypes.html`. Five archetypes cover ~40 of the 47
templates, from its own comment: *"one pattern per repeating shape, not one
design per page."* **Compose these pages from those macros rather than the
prototype class names in this bundle.**

- **Archetype 1 Entity profile** — `entity_header`, `record_tabs` (mp,
  senator, entity, journalist, source, owner detail)
- **Archetype 2 Directory** — `person_card`, `record_card`,
  `directory_grid`, `record_links` (mps, journalists, officers, owners, gic,
  sources). `person_card` is a single `<a>`, so a record carrying its own
  links **must** use `record_card` — nesting anchors is invalid HTML.
- **Archetype 3 Data explorer** — `stat_tiles`, `ranked_bars`, `data_table`
  (lobbying, economy, rates, cost, markets, crtc, claims, municipal, blindspot,
  divergence)
- **Archetype 4 Map / geo** — `layer_switch`, `freshness`, `measurement`,
  `layer_row` (map, weather, municipal)
- **Archetype 5 Editorial + account** — `doc_shell`, `setting_row`, `field`
- Shared — `chip`, `segment`, `filter_chip`, `photo`, `lean_pill`, `paywall`

**Four honesty rules travel with these macros and must not be dropped.** Each
is written into the macro comments, and each matches a correction in the table
above — arrived at independently, which is worth knowing:

1. `lean_pill` renders **colour plus a text label, never colour alone.** The
   comment records that the old ramp put GREEN at the midpoint, which "reads as
   *centre = good*, an editorial claim this site must not make." Rendering lean
   as a bare swatch reintroduces that bug.
2. `ranked_bars`: **magnitude is neutral slate; the accent marks only the
   highlighted value**, so chart colour can never collide with lean colour.
3. Map archetype: **a region with no data for the active layer is greyed
   explicitly, never rendered as zero** — the fire layers cover disjoint halves
   of the country, so a single choropleth lies either way. And **freshness is
   per layer** (city obs 3h / forecast 12h / fire 48h); a 40-hour reading must
   not render as current.
4. `measurement(value)`: **`None` renders an em dash, never 0.** The ECCC feed
   sends `<gust>00</gust>` for "no gust" on ~94% of periods, so coercing to
   zero fabricates a measurement. This is the same reason the MP ridings in
   this bundle are blank rather than derived.

### Two more corrections applied in this pass

**Emoji removed.** Our archive page used 🔒 in two labels and `/lobbying` used
`&#128274;` in its gate title. Both are now stroked SVG padlocks. Live still
carries emoji headings on `/search`, `/activity`, `/source`, `/senator` and
`/mp` gate titles (🔒) — replace them with the icon set when those templates
are touched, as the repo comments already do elsewhere.

**`journalist.html` still has the forbidden ramp.** Live's journalist template
colours its bias bar with a five-stop scale that puts **green at the centre**,
which is exactly the pattern `_archetypes.html` documents as removed: *"reads
as centre = good, an editorial claim this site must not make."* Our
`/journalists` page uses `lean_pill` semantics instead — the band name as
text with the spectrum colour, no green anywhere. **When `journalist.html` is
implemented, port it onto `lean_pill` and delete the local ramp.** It is the
last page carrying the old scale.

**Every paywall CTA in this bundle now points at `/login?next=<route>` with a
`/join` "See plans" partner.** They previously pointed at the design bundle's
own home page, which would have shipped as dead links. Verified: 0 CTAs without
a route, 0 gates without a plans link, across all 39 pages.

**XSS rule is absolute** (`.claude/rules/wtf.md`): every macro escapes by
default, the product renders scraped RSS text, and **`|safe` must never be
added to a caller-supplied value.**

Styling for the archetypes lives in `static/style.css` under "ARCHETYPE
COMPONENTS", prefix `wtf-a-`. A page that hardcodes a hex stops tracking the
palette — there is a guard for it in
`tests/test_archetype_macros.py`. Run that test.

From `.design-sync/conventions.md` and `NOTES.md`:

- **Every class is `wtf-`-prefixed, and a new page gets its own sub-namespace.**
  Existing pages use `wtf-bs-` (blindspot), `wtf-dv-` (divergence), `wtf-ec-`
  (economy), `wtf-mu-` (municipal), `wtf-wx-` (weather). The namespaces in this
  bundle already follow the pattern: `wtf-pg-` for the Politics record pages
  and `wtf-pl-` for the Parliament floor plans. Keep them.
- **Page-level styles belong in the template's own `<style>` block**, not in
  `static/style.css`. That separation is deliberate — page styles are not
  extractable into the design-system bundle, and the shared stylesheet is meant
  to stay the shell only.
- **There is no bare `.wtf-card`.** The card is `.wtf-article-card` plus a
  per-lean modifier (`--left`, `--center-left`, `--center`, `--center-right`,
  `--right`). Do not invent base classes.
- Shell vocabulary already exists and should be reused rather than reinvented:
  `.wtf-nav`, `.wtf-nav-brand`, `.wtf-nav-links`, `.wtf-nav-live`,
  `.wtf-nav-search`, `.wtf-nav-subscribe`, `.wtf-wordmark`,
  `.wtf-section-label`, `.wtf-top-story`, `.wtf-card-title`, `.wtf-card-meta`,
  `.wtf-card-badge`, `.wtf-bias-pill`, `.wtf-badge-ai`, `.wtf-live-dot`,
  `.wtf-footer`.
- Utility classes `.serif` and `.mono` switch font family inline.
- Never paint a page background — `body` already carries `--wtf-bg`.
- **Colour tokens carry meaning and must never be repurposed decoratively.**
  This is house rule and it is also defects #2 and #4 in the table below.

The class names in this bundle are prototype names written before I could read
the repo. Where a shell class already exists for something, use the repo's name;
where the design introduces genuinely new page-level structure, the `wtf-pg-` /
`wtf-pl-` namespaces are correct by the convention above.

## Fidelity

**High-fidelity.** Final colours, typography, spacing, interaction states and
copy. Recreate pixel-for-pixel using the existing `css/style.css` shell and its
`wtf-` class vocabulary. Every colour used is an existing design-system token;
no new colours were invented.

Two exceptions, both flagged in-page:
- Pages under `Data` (`chain`, `cross-watch`, `edu`, `governance`) are labelled
  "Not yet built" and carry real titles and framing with dashes where values
  are unmeasured. They are structure, not finished screens.
- `score.html` validates a URL then states that scoring runs server-side. The
  form needs wiring to the real endpoint.

---

## What is corrected relative to the live site

These are deliberate and should survive implementation. Each was a factual or
interpretive defect found during review.

| # | Live behaviour | Corrected to |
| --- | --- | --- |
| 1 | Senate page states 96 senators, renders 93 | All 96 mapped and listed; the discrepancy is noted on the page |
| 2 | Coverage map used verdict-green for "Canadian", so a geography colour read as a fact-check verdict | Magnitude on neutral slate; accent marks only the top value |
| 3 | Lean shown for provinces with a handful of articles | Provinces under 20 articles draw dashed and uncoloured, never as "centre" |
| 4 | Fire intensity ramp ran yellow→red, colliding with the red→blue lean spectrum | Fire keeps its own ramp and is never adjacent to a lean pill |
| 5 | "232 fact-checked" (verdicts counted once per outlet row) | 23 / 24 **stories** — a verdict belongs to the story, not each sibling article |
| 6 | Activity page stated two different LLM-throughput totals | One figure, derived from the sparkline |
| 7 | Cluster panel bars all pegged full-width; rows labelled with the first filer | Bars scale to the sorted max; rows labelled with the story headline |
| 8 | LIVE pill was a dead span on every page | Links to `/activity` |
| 9 | Archive paywall never triggered in story view | Gates at 10 stories / 50 articles by view |
| 10 | Fire perimeters drawn as circles | Lobed polygons oriented on each fire's run bearing |

**Deliberate omissions.** MP ridings and provinces are carried for five members
only (the five on record). The other 338 read "Riding not recorded" and all 96
senators read "Region not recorded". An earlier draft derived province from a
hash of the slug, which produced confident false claims about named public
officials — Elizabeth May in Alberta. On a site that fact-checks named people,
an empty field costs less than a plausible wrong one. **When implementing,
fill these from the database; do not reintroduce a derivation.**

Similarly, party assignment on the floor plan is derived from seat arc position
so totals match published standings (Lib 171 / Con 139 / Bloc 21 / NDP 5 /
Green 1). Read the real party per member from the database instead.

---

## Screens

### Shell — every page

**Nav** (`_nav.html`, styles in `wtf-shell.css`). Sticky, 54px, `--wtf-bg-card`
ground, 1px `--wtf-border` bottom. Content gutter
`--gut: max(18px, calc((100vw - 1180px) / 2))` so bands run full-bleed while
content centres at 1180px.

Six groups, each a `.navgrp` with an `.grp` label and a `.navgrp-menu`
dropdown: **News** (Latest, Full archive, Activity log, Weather, Blindspot,
Divergence, Clusters) · **Politics** (MPs & ridings, Municipal, Lobbying,
Appointments, Ethics tracker, Officers, Rates) · **Money** (Economy, Cost of
Parliament, Markets) · **Media** (Sources, Owners, Journalists, CRTC) ·
**Data** (Coverage map, Accountability chain, Cross-Watch, Claims, Developer
API, Education API, Search everything) · **About** (Methodology, The newsroom,
Governance & ethics, C.R.E.E.D., Media literacy, Score an article).

Group labels: IBM Plex Mono 10px, `letter-spacing:.13em`, uppercase,
`--wtf-text-2`, hover `--wtf-text`. 17px stroked SVG icon at `opacity:.72`,
going to 1 and `--wtf-brand` on hover.

Dropdown: `position:absolute; left:-12px; top:100%; min-width:196px`,
`--wtf-bg-panel`, 4px radius, `box-shadow:0 14px 34px rgba(0,0,0,.6)`,
`z-index:600`. Opens on hover **and** on click (`.navgrp.open`, see
`wtf-nav.js`) — click matters on touch, where hover never fires.

> **Do not put `overflow` on `.nav` or `.navgrp`.** A scroll container cannot
> have visible overflow on the other axis, so `overflow-x:auto` silently clips
> every dropdown. `.nav,.navgrp{overflow:visible}` is asserted for this reason.

Responsive: ≤1180px hide the live pill's label (keep the dot) · ≤1090px hide
Sign in · ≤1010px `gap:10px` · ≤940px `gap:8px` and hide nav icons · ≤820px
the bar wraps to two rows · ≤760px hide the wordmark text.

Right cluster: live pill (6px `--wtf-brand` dot, `blink 1.8s` 1→.2 opacity,
label "Live · 41 sources") → search icon-btn (30px circle) → Sign in
`.btn-ghost` → Subscribe `.btn-sub` (`--wtf-accent`, hover `#b91c1c`).

**Footer.** Two rows split by a 1px border. Row 1: "Built on radical
transparency." in Newsreader 15px, then How we score bias / Developer hub, a
`C.R.E.E.D. Certified` pill (`--wtf-established` border and text, 6px dot),
right-aligned "41 sources tracked · scores are per-story, not permanent
labels". Row 2: Weekly Bias Digest signup, `what-the-fact.tech`,
`creed-ai.org`, EN · FR · ES.

**Type.** Newsreader (`--wtf-font-serif`) headlines, IBM Plex Sans body, IBM
Plex Mono data and labels. `font-optical-sizing:auto` on `html` — Newsreader
carries an optical-size axis and using it is the single biggest quality gain
available. All numerals `font-variant-numeric: tabular-nums lining-nums` so
values don't jitter as they animate. `letter-spacing:-.006em` on body,
`-.028em` on h1, positive tracking on mono labels. `text-wrap:balance` on
headings, `pretty` on paragraphs.

**Refresh layer.** Radii 14 / 10 / 7px. Card shadow
`0 1px 0 rgba(255,255,255,.045) inset, 0 8px 22px -12px rgba(0,0,0,.85)`,
raised variant `0 1px 0 rgba(255,255,255,.07) inset, 0 16px 38px -14px rgba(0,0,0,.9)`.
Easing `cubic-bezier(.32,.72,0,1)`. Pill controls (`border-radius:999px`),
hover `translateY(-1px)` on chips and `-2px` on cards. Focus ring
`2px solid var(--wtf-brand)` at `outline-offset:2px`. Full
`prefers-reduced-motion` fallback disabling transforms and transitions.

---

### `wtf-home.html` — homepage

Bands top to bottom: nav → beat pills → context banners → today's top story →
local weather strip → Canada/World map zone → editorial rail + feed → footer.

**Beat pills.** All, Parliament, Economy, Climate, Health, Crime, Business,
Sports. Mono 9px uppercase, `--wtf-bg-panel`, active
`rgba(220,38,38,.12)` on `--wtf-accent` border with `--wtf-accent` text.
Filters the map and the feed together.

**Local weather strip.** Horizontally scrolling cards, 152px min-width,
`--wtf-local` left border (amber `--wtf-developing` when the city has an
alert). Each: name, mono 22px temperature, drawn weather glyph (sun, partly
cloudy, overcast, rain, fog, wind, smoke), condition. Reads the default city
from `localStorage['wtf-default-city']` so it agrees with the weather page;
alert cities sort first with a pulsing dot.

**Map zone.** D3 + TopoJSON. Canada uses `geoConicConformal` with
`parallels([49,77]).rotate([96,0])`, fitted to the real container box (a
ResizeObserver refits, so the map fills the panel rather than letterboxing).
World uses `geoNaturalEarth1`. Province polygons from Natural Earth 50m
admin-1 filtered to Canada; country outlines from world-atlas 110m.

Two modes. **Dominant lean** fills each region with its leading band's colour
at `0.17 + (share/45) * 0.5` opacity — colour is the band, strength is how
concentrated the lead is. **Volume** uses neutral `--wtf-center` with
`--wtf-accent` on the single highest value only, so a chart colour can never
be read as a lean colour. Regions under 20 articles: dashed 4 3 stroke, no
fill, no figure.

Left index panel lists every region sorted by volume with a lean swatch, name
and count; clicking a row or a shape selects it and dims the rest. Legend sits
below the map, not over it. Labels are gated on projected polygon area — big
regions get code plus count, mid-size the code only, small ones nothing, since
the index carries every value anyway.

**Editorial rail.** F.A.C.T. top stories (numbered 01–05) and a live agent
ticker prepending a row every 4.2s, each agent in its own colour.

**Feed.** Eight cards, then a gate. The eight are chosen for **spread** — a
first pass takes one story per distinct lean band, beat and province — so the
free sample demonstrates range rather than eight versions of one story. Cards
carry a 3px left border in the lean colour, mono meta line, Newsreader title,
AI-analyzed and outlet-count badges. Gate names the withheld count with a
progress meter and routes to both the live feed and the archive.

Scroll position is saved to `sessionStorage['wtf-home-y']` on click-through
and restored on return.

### `wtf-news.html` — Latest

Live feed over the shared corpus. Filters: search, window, lean, verdict,
beat, province, outlet, density (card / row), saved, and quick filters
(Blindspot free; Français / English / Unread are Starter, shown with a padlock
that opens an inline upgrade prompt rather than a dead end).

Every filter chip carries a **count computed against the other active
filters**, so a chip never promises rows it can't deliver; impossible options
dim to `opacity:.4`.

Lean-mix bar sits directly under the stat tiles: a segmented bar plus a named
index (Left 8% · Center-Left 21% · Center 42% · Center-Right 21% · Right 8%)
— five bare percentages are not an index.

Read state in `localStorage['wtf-read']`: opened stories drop to `opacity:.6`
with muted titles, returning to full on hover. "Mark page read" clears a page.
This is free — it costs nothing to store and it is what makes a live feed
returnable.

Story drawer opens in place with tabs (Coverage, Sources, Timeline). Pickup
order lists every filing in a 230px scrollable list with "Show all N filings",
and states the real pickup span in hours. Analyst note panel renders **only**
when a note exists, labelled "Filed by the desk, not generated"; stories
without one say so.

French articles (Le Devoir, La Presse, Radio-Canada) carry their real French
headlines with an FR tag, and the drawer shows the English rendering beneath.

### `wtf-archive.html` — full archive

**By story / Every article** toggle: opens at 24 distinct stories, since 241
article rows repeat a 16-outlet cluster's headline 16 times and make sorting
by headline useless.

Sortable table (Filed, Outlet, Headline, Lean, Verdict, Outlets) with the sort
direction named — "Filed · newest", "Outlets · most", "Headline · A–Z" — not
an ambiguous arrow. Sticky header under the nav. Star column saves a row
without leaving the page. Search matches highlight in amber
(`rgba(245,158,11,.26)`) in both headline and outlet.

Filters: search, fixed windows, custom date range, lean, verdict, beat,
province, outlet (top 10 with "All 33 outlets"), language, saved, unread.
Summary toggle adds by-time / by-beat / by-outlet rollups, each row a lean-mix
bar — and the time axis buckets by hour, day or month depending on what the
window actually spans.

All state lives in the URL hash, with a Copy link button. CSV export is
Starter and says so when clicked rather than greying out silently.

Paywall gates at 10 stories or 50 articles by view. **Preview mode** is its
own state, not a fake subscription: it shows a persistent amber bar with an
Exit button, keyed `localStorage['wtf-preview']`.

### `wtf-article.html` — article page

Two columns, `minmax(0,1fr) 340px`. Kicker (outlet, date, read time,
AI-analyzed, verdict, C.R.E.E.D. audited, audit-trail link) → Newsreader 38px
headline → byline → key figures quoted verbatim → B.I.A.S. panel → coverage
spread → V.E.R.I.F.Y. → excerpt → provenance.

B.I.A.S. scale is a gradient of the five band colours with a white marker and
the numeric score shown between −1.0 and +1.0 endpoints. Read-time tag counts
down as you scroll and ends at "Finished".

Rail: Source Intelligence (rolling outlet bias, 7-day sparkline), the six
agents each with its own colour and what it did on *this* story, Cross-Watch
entities counted by **distinct stories** (not outlet rows), Blindspot panel
when flagged, digest signup.

### `wtf-weather.html` — A.U.R.O.R.A.

The largest page. Layers: temperature, cloud cover, rain, wind, fire activity,
fire weather, air quality, alerts. Zoom and pan via `d3.zoom` with
`scaleExtent([1,8])`; field animations are re-anchored to the projection on
every transform, so wind and rain stay over their real geography when you pan.

Fire perimeters are lobed polygons stretched along each fire's run bearing,
drawn as dark burn scars with a bright active edge and a dashed projected
front. 87 fire-weather stations, with per-province counts derived from the
station list rather than asserted separately.

Fire spread prediction with an operations brief per fire: tactic diagram
oriented to the real run bearing, water requirement, ferry distances, and a
national fleet table — all 13 provinces with scooper and tanker counts and a
straight-line ferry estimate. The brief reframes the ask as *time with the
actual fleet* rather than an aircraft count, because "117 aircraft" was a
formula artefact.

Also: 66 cities, city drawer with hourly then daily forecast, 14-day and
30-day outlooks dated from today, forecast accuracy scored against persistence
**and** Environment Canada, AQHI, evacuation orders, season-to-date burned
against the ten-year average, and a written A.U.R.O.R.A. outlook.

### `wtf-mps.html` — MPs & ridings

House/Senate tabs. Both floor plans use the live site's own coordinate tables
(`SEAT_XY` 343 seats, `SENATOR_XY` 96), so every dot sits where that member
actually sits. Speaker's chair at (350, 315), opposition left, government
right. Dot radius scales with distance from the Speaker (inner rows sit
closer, so they shrink) between 1.7 and 4.4px; leaders get +1.1px, a white
stroke, a pulsing halo animating r between +2.6 and +5.4, and a surname label
above the arc.

Party colours are the live site's own: Liberal `#d71920` · Conservative
`#3b82f6` · Bloc `#89cff0` · NDP `#f37021` · Green `#3d9b35` · Independent
`#888888`. Senate caucuses: ISG `#cc0000` · CSG `#059669` · PSG `#7c3aed` ·
C `#3b82f6` · GRO `#b45309` · Non-affiliated `#888888`.

Standings bar with a majority line at 172. Legend chips filter map and roster
together. Roster groups by party with 158px minimum cards.

> Party colour appears **only** as solid dots on the floor plan and never as a
> pill beside a lean band, so a Conservative blue cannot be misread as a
> right-lean score. Keep this separation.

### `wtf-lobbying.html`

Five stat tiles (Communications, Organizations, MPs lobbied, Last 30 days,
Coverage years) then three sections: most active organizations all-time,
most-lobbied MPs last 12 months, and recent activity gated as Starter+.
Carries the registry's own caveat: *the registry records that a communication
took place; it does not publish what was discussed.*

### `wtf-municipal.html` — L.O.C.A.L.

Article feed by city. Chips carry real counts, cards carry a city pill,
outlet, province tag, time, lean band and cluster link. Cities are **read out
of the headline text**, so a story only gets a pill when it names one and
every chip count is a real count.

### `wtf-activity.html`

Agent throughput for all six agents with progress against target, model name,
average duration, dispatch counts, success rates. C.R.E.E.D. governance panel
showing the failing F grade and 58% compliance rather than burying it — the
grade is the newsroom's own audit of itself, and publishing a failure is the
point. Analysis tiers, coverage gauges, pipeline health, throughput sparkline,
source health table with body-retrieval rates, and a stage-filterable event
log.

### Other pages

`wtf-search.html` faceted search across articles, MPs, outlets and claims ·
`wtf-blindspot.html` · `wtf-divergence.html` · `wtf-clusters.html` ·
`wtf-sources.html` / `wtf-outlet.html` · `wtf-owners.html` ·
`wtf-journalists.html` · `wtf-crtc.html` · `wtf-accuracy.html` ·
`wtf-city.html` · `wtf-map.html` · `wtf-gic.html` · `wtf-ethics.html` ·
`wtf-officers.html` (Starter+ gated) · `wtf-rates.html` (Starter+ gated) ·
`wtf-economy.html` · `wtf-cost.html` · `wtf-markets.html` ·
`wtf-methodology.html` · `wtf-creed.html` · `wtf-team.html` ·
`wtf-literacy.html` · `wtf-api.html` · `wtf-score.html`.

---

## Interactions & behaviour

- **Dropdowns**: hover on pointer devices, click-toggle everywhere
  (`wtf-nav.js` adds `.open`; a document listener closes others).
- **Filters**: all client-side over a loaded result set; counts recompute on
  every change against the other active axes.
- **Drawers**: open in place, do not navigate; opening marks the story read.
- **Transitions**: 160–260ms on `cubic-bezier(.32,.72,0,1)`. Map transitions
  500–520ms `easeCubicInOut`. Number tweens use `d3.interpolateRound`.
- **Animations**: `blink 1.8s` for live dots; leader halo 2.6s; fire flame
  flicker; wind particle advection on `requestAnimationFrame`, re-anchored on
  zoom.
- **Scroll restore**: `sessionStorage` per page, restored on load.
- **Reduced motion**: all transforms and transitions disabled.

## State

| Key | Store | Purpose |
| --- | --- | --- |
| `wtf-read` | localStorage | Story ids opened |
| `wtf-saved` | localStorage | Starred story ids |
| `wtf-gate-preview` | sessionStorage | Paywall preview on every gated page (design review only) |
| `wtf-default-city` | localStorage | Weather default city |
| `wtf-dens` | localStorage | Feed density |
| `wtf-home-y`, `wtf-archive-y` | sessionStorage | Scroll restore |
| URL hash | — | Archive filters, sort, view, page |
| URL `?id=` | — | Article page |

Nothing else is persisted. Never clear a key you did not write. `wtf-sub` and
`wtf-preview` were earlier keys and are gone; nothing reads them.

## Design tokens

All from the existing design system — no new colours.

**Surfaces** `--wtf-bg` #0d1117 · `--wtf-bg-card` #11161f ·
`--wtf-bg-panel` #171e2a · `--wtf-border` #222b39
**Text** `--wtf-text` #f2f1ed · `--wtf-text-2` #b9bdc5 ·
`--wtf-text-muted` #7d8590
**Accent** `--wtf-accent` #dc2626 · `--wtf-brand` #14bef0 (identity only —
logo, wordmark, live pill; **never** on data, because blue already means
right-of-centre)
**Bias spectrum** `--wtf-left` #d84b47 · `--wtf-center-left` #cf8b80 ·
`--wtf-center` #929aa5 · `--wtf-center-right` #7fa3cf · `--wtf-right` #4a72d8
**Verdicts** `--wtf-established` #10b981 · `--wtf-developing` #f59e0b ·
`--wtf-contested` #e05252
**Agents** F.A.C.T. #dc2626 · B.I.A.S. #f59e0b · V.E.R.I.F.Y. #10b981 ·
L.O.C.A.L. #4a72d8 · I.N.K. #a78bfa · D.R.A.F.T. #7fa3cf

Radii 14 / 10 / 7px, pills 999px. Gutter
`max(18px, calc((100vw - 1180px) / 2))`.

> Colour tokens carry meaning. Do not repurpose a verdict green or a lean blue
> decoratively — that was defect #2 and #4 above.

## Assets

- `assets/wtf-logo.png` — the existing logo, 1254×1254. Brand cyan #14bef0 was
  sampled from it.
- Fonts from Google Fonts: Newsreader (variable, optical size 6–72), IBM Plex
  Sans, IBM Plex Mono.
- Geometry: Natural Earth 50m admin-1 (provinces) and world-atlas 110m
  (countries), both public domain, loaded from CDN. **In production serve a
  trimmed local `canada-provinces.geojson`** — the CDN file is ~2MB and there
  is a visible moment before provinces fill in.
- Libraries: d3 7.9.0, topojson-client 3.1.0, both with SRI hashes.
- No photography. Image slots are placeholders for the media studio to fill.

## Files

Pages: the 46 `wtf-*.html` files in this bundle.
Shared: `wtf-shell.css` (nav, footer, wrap, stat tiles, cards) ·
`wtf-nav.js` (dropdown behaviour) · `wtf-corpus.js` (sample article corpus,
241 rows across 24 stories — **replace with database queries**) ·
`wtf-parliament.js` (seat coordinates, party colours, rosters) ·
`wtf-accountability.js` (officers, findings, vacancies) · `wtf-record-context.js` ·
`wtf-promises.js` · `wtf-candidates.js` · `wtf-elections-extra.js` · `wtf-brand.js` ·
per-page scripts (`wtf-mps.js`, `wtf-mp.js`, `wtf-senator.js`, `wtf-ridings.js`,
`wtf-elections.js`, `wtf-races.js`, `wtf-parties*.js`, `wtf-platforms.js`,
`wtf-officers.js`, `wtf-ethics.js`, `wtf-cross-watch.js`, `wtf-activity.js`,
`wtf-blindspot.js`) · `_nav.html` (canonical nav markup).
The **Migration manifest** at the end of this file maps every page to its
route, nav group and scripts.
Reference: `reference/reference-live-site.md` (live-site audit),
`reference/reference-templates.md` (template inventory),
`reference/github.md` (repo location, conventions, and the full
design-file → template mapping table).

## Paywall — the real contract

Read from `consumer/tiers.py`, `consumer/access.py` and
`consumer/templates/_archetypes.html`. **Do not invent gating logic.**

### Tier vocabulary

`tiers.py` holds the single source of truth, `SUBSCRIBED_TIERS`:
`starter`, `solo`, `team`, `agency`, `pro`, `enterprise`, plus elevated
identities `kytran`, `owner`, `admin`, plus legacy names `professional`,
`vip`, `business` kept for pre-canonical stored rows.

The file's own docstring records why: `auth.py`, `billing.py` and `access.py`
each carried a private drifted copy that omitted `solo`/`team`/`agency`, so a
paying subscriber was paywalled after paying. **Semantics are grant-only —
adding a name can only widen access.** Never narrow the set, never re-fork it.

Gating helpers, all in `access.py`: `is_authenticated()`, `get_tier()`,
`has_paid_tier()` (checks the tier set, then `wtf-starter` in
`wtf_entitlements` for bundle holders), `user_has_beat_access(slug)`, and the
`@require_product_access(slug)` decorator which redirects unauthenticated users
to `/login?next=` and returns 402 JSON for authenticated free tier.

### The paywall block

One macro, `paywall(title, blurb, next_url, plans_href="/join")` in
`_archetypes.html`. Its comment records that this identical four-part block was
hand-rolled in **14 templates** and had drifted to **four different CTA
colours** — a red on twelve pages, a second near-identical red, a blue on
`/gic`, and a cyan-on-black on `/owners` — and not one of them was
`--wtf-accent`. Use the macro. Do not restyle the button.

Shape: `.wtf-a-pay` → `.wtf-a-pay-t` title → `.wtf-a-pay-b` blurb →
`.wtf-a-pay-cta` to `/login?next=<route>` reading "Unlock with Starter →" →
`.wtf-a-pay-plans` to `/join` reading "See plans".

Prices in the live templates: **Starter $4.99/mo** (article gate, checkout at
`/billing/checkout/starter`), **beat subscription $2/mo CAD** at
`/subscribe/beat/<slug>`.

### What is gated, per page

Corrected in this bundle to match the live templates. The design files carry a
"Design review" toggle that reveals the subscriber view — it uses its own
`sessionStorage` key and is **not** a tier flag. Delete it on implementation.

| Route | Free | Starter+ |
| --- | --- | --- |
| `/parliament/officers` | Header, count, **all 8 offices with mandate and establishing year**, "why they matter" note, cross-links | Current holder, appointment date, latest tabled report, cross-product links |
| `/rates` | `stat_tiles` (current target, decisions on record) | The whole decisions table |
| `/gic` | Header and appointment count | The list **and** the department segment filter |
| `/ethics` | Everything — no gate | — |
| `/lobbying` | Tiles, orgs all-time, most-lobbied MPs | Recent activity detail |
| `/owners` | Tiles and list | Detail |
| `/map` | Base map | Layer detail |
| `/blindspot`, `/divergence` | Story list | Bias-score breakdown per cluster |
| `/mp/<slug>`, `/senator/<slug>` | Cost-to-taxpayer figures (deliberately public — the templates note that paywalling a public salary "reads as charging for a public record") | Voting record and coverage detail |
| `/beat/<slug>` | Preview | Full beat at $2/mo, separate from Starter |

**Data contracts** the templates declare in their own comments, unchanged:
`officers[], is_subscriber` · `current, decisions[], is_subscriber` ·
`appointments[], depts[], dept, is_subscriber`.

### One deliberate divergence from live: `/parliament/officers`

**This is the only place the bundle does not match the live gating, and it is
intentional.** Live wraps the entire `{% for o in officers %}` loop in
`{% if is_subscriber %}`, so a free reader sees a gate and an ungated note
arguing that these offices matter — with no way to learn what any of them do.
The gate hid the evidence for its own argument.

A mandate and an establishing statute are public statutory facts. Charging for
them reads the same way the `mp.html` comment describes charging for an MP's
public salary: *"paywalling it buys no exclusivity and reads as charging for a
public record."*

Moved: all 8 offices, mandates and establishing years are now **free**. The
gate sits below them and withholds what is genuinely the newsroom's work —
**current holder, appointment date, latest tabled report, and the Cross-Watch
links tying each finding to the coverage it generated.** The gate's own copy
changed from "Full profiles… mandates, current holders, and cross-product
intelligence links" to "Who holds each office right now, when they were
appointed, their latest tabled report, and the coverage each finding
generated," so it names what it actually withholds.

Implementation: keep `{% if is_subscriber %}` around the holder fields
(`o.current_holder`, `o.appointed_at`, `o.report_url`, `o.cross_links`) and
move `o.title`, `o.mandate_summary` and the establishing year outside it. The
`officers[]` data contract does not change. Holders with no value on record
render an em dash, per `measurement()` — never a fabricated name.

## Deploying this

> **Runbook:** `deploy/DEPLOY.md` has the exact commands — landing this bundle
> in the repo, the per-phase PR rules, `./deploy.sh consumer`, the live smoke
> test (`deploy/smoke-test.html`) and rollback. `deploy/CLAUDE_CODE_BRIEF.md`
> is the Phase 1 brief. `deploy/sync-diff.md` lists what this bundle changes
> against the `design-handoff/` snapshot already in the repo.

The goal is to get these changes live and testable. This is the order that
keeps the site deployable at every step rather than broken until the end.

### Ground rules

- **One PR per phase below.** Each phase leaves the site working. Do not open a
  single PR touching 39 templates.
- **Never edit `consumer/static/style.css` and page styles in the same commit.**
  The stylesheet is synced into the design system by `.design-sync/`, so a
  change there has a second consumer.
- **Page styles go in the template's own `<style>` block.** Only genuinely
  shared shell changes belong in `static/style.css`.
- `routes.py` is 268KB. Add new routes at the end of the relevant section
  rather than reorganising it, and keep the diff readable.
- Test each template against a real database read before moving on. Every
  number in these prototypes is sample data.

### Phase 1 — the shell (blocks everything else)

`consumer/templates/base.html` + `consumer/static/style.css`.

The nav IA changed, so this phase alone is visible on every page. Recreate
`_nav.html` into `base.html`'s nav block and add the shell rules from
`wtf-shell.css` to `static/style.css`.

Six groups: News (Latest, Full archive, Activity log, Weather, Blindspot,
Divergence, Clusters) · Politics (MPs & ridings, Municipal, Lobbying,
Appointments, Ethics tracker, Officers, Rates) · Money (Economy, Cost of
Parliament, Markets) · Media (Sources, Owners, Journalists, CRTC) · Data
(Coverage map, Accountability chain, Cross-Watch, Claims, Developer API,
Education API, Search everything) · About (Methodology, The newsroom,
Governance & ethics, C.R.E.E.D., Media literacy, Score an article).

**Deploy and check before Phase 2:** every existing route still renders, the
dropdowns open on hover AND on tap, and nothing is clipped. The clipping trap
is documented in the Shell section above — do not add `overflow` to `.wtf-nav`.

### Phase 2 — new routes that need no data work

`/archive`, `/search`, `/score`, `/activity` if it does not exist yet.

These are additive: new route, new template, no changes to existing pages. Safe
to deploy independently and the fastest way to get something new live.

### Phase 3 — the core reading loop

`index.html`, `news.html`, `article.html`.

Highest traffic, so deploy these one at a time and watch. The corrections in
the table above that matter here: the fact-checked count must be per story not
per outlet row (#5), and the homepage feed's eight free cards are selected for
spread, not recency.

Client-side filtering stays client-side. Server-side: the corpus queries that
`wtf-corpus.js` stands in for.

### Phase 4 — weather

`weather.html` and its city view. Largest single page and self-contained, so
it carries no risk to the rest of the site. Serve a trimmed local
`canada-provinces.geojson` from `consumer/static/` rather than the 2MB CDN
file.

### Phase 5 — Parliament

`mps.html`. Needs real party, riding and province values from the database.

**This phase has a hard requirement.** The prototype leaves riding and province
blank for 338 of 343 members and all 96 senators, and derives party from seat
arc position. Fill all three from the database. Do not ship the derivation, and
do not reintroduce a hash-based fallback — that produced confident false claims
about named MPs, which is the one failure mode this site cannot afford.

### Phase 6 — the rest

Politics, Media, Data and About sections. Independent of each other, so they
can go out in any order or together.

### Verifying live

Per phase: the route renders, numbers match a direct database query, the nav
works on a real phone, `prefers-reduced-motion` is honoured, and no page paints
its own background over `--wtf-bg`.

Two things worth watching after Phase 3, because they are the corrections most
likely to regress under real data: any count that should be per-story rather
than per-article-row, and any place a verdict or lean colour ends up used for
something that is not a verdict or a lean.

## Suggested order

1. `wtf-shell.css` + `_nav.html` + `wtf-nav.js` — every page depends on the
   shell, and the nav IA changed (Weather moved under News, Politics replaced
   Parliament, Data is new).
2. Homepage, Latest, Archive, Article — the core loop.
3. Weather — largest single page, self-contained.
4. MPs — needs real party and riding data from the database.
5. Politics, Media, Data, About sections.

---

### Rebuilt to live contracts — 2026-09-02 afternoon

Nine pages were rebuilt against the repo templates read the same day (captured
in `reference/money-media-contracts.md`), so their structure now matches what
`routes.py` already sends:

| Page | Live source | What changed |
| --- | --- | --- |
| `wtf-cost.html` | `cost.html` + `static/js/cost.js` | Headline 5-year total, year-to-date addenda that never sum into the headline, stat tiles, stacked bars per year, member-by-member reconciliation, honesty footer. Reads `/api/cost/summary` and `/api/cost/reconciliation` on the live site. Cost components stay off the lean spectrum (no blue). |
| `wtf-economy.html` | `economy.html` | M.A.R.K.E.T. framing, Market Watch attribution and CTA, beat pills, `/news?beat=` links, story counts — plus six indicator cards with 24-month history, each naming its StatCan table or Valet series and release. |
| `wtf-rates.html` | `rates.html` | 2000–2026 decision-path chart with six era notes as public background; the decision table stays Starter+. Decisions after March 2025 are flagged placeholder until Valet V122514 is wired. |
| `wtf-journalists.html` | `journalists.html` + `journalist.html` | Directory (cards/table, search, group by medium or outlet) and the full profile in one page: photo slot (initials until `photo_url`), every rated post with a band filter, outlets, recent coverage; bias lean, volume by month and co-mentions Starter+. |
| `wtf-crtc.html` | `crtc.html` | Ownership-concentration panel with top-3 badge and owner bars (owner type by shape, avg bias on the lean scale), type filters, Starter+ ruling list with outlet cross-links. |
| `wtf-cross-watch.html` | `cross_watch.html` + `entity.html` | The six Watch product badges on every entity, mentions, and the entity footprint view: product tiles, recent coverage, Competition Bureau items (Legal Watch), listed-contractor line (Market Watch); accountability chain and co-mentions Starter+. |
| `wtf-chain.html` | `chain.html` | The 8-link rail (Money → MP → Vote → Policy → Contract → Market → Coverage → Public) with live/no-data positions, search, entity view with per-link blocks and hop-through samples. Reads `/api/public/chain/*` on the live site. |
| `wtf-governance.html` | `governance.html` | The C.R.E.E.D. scan of the newsroom: overall/100, grade, event counts, six pillars with provisional marking under 100 events, the badge scale (green ≥90 · blue ≥80 · yellow ≥70 · red <60), and how the newsroom participates. |
| `wtf-creed.html` | creed-ai.org | The organization as it describes itself: Montreal nonprofit, 178 rules in five packs scanned every six hours, E.T.H.O.S., four programs, and the disclosed Kytran relationship. |

Two reconciliations to make on implementation: C.R.E.E.D.'s case study cites an
A+ badge for this newsroom while the scan on the Governance page returns 58 —
show whichever `/api/creed-badge` returns, never a hand-entered grade; and the
Rates page's post-March-2025 decisions are placeholders, not assertions.

## Migration manifest — generated 2026-09-02 14:32Z

Produced by reading the files in this bundle, not by hand, so it cannot drift
from what is actually here. Re-run the sweep after any edit.

### Final sweep result

- **46 pages** load with **zero runtime errors** (each page fetched, an
  error hook injected before its scripts, then loaded and settled).
- **Shared nav on 45 pages** (`wtf-ridings.html` is a redirect stub), shared
  footer on all, 7 groups, no overflow at 1280 / 1000 / 800 px.
- **Every internal href, script src and stylesheet resolves.** Every hash deep
  link in the nav lands on a real pane (`#senate`, `#ridings`, `#federal`,
  `#provincial`, `#municipal`, `#coverage`, `#accuracy`).
- **Every `?slug=` / `?party=` / `?id=` / `?src=` / `?q=` route resolves** to a
  populated page.
- Handoff copy is byte-identical to the working files.

Fixed in the sweep: `drawWave`/`drawBills` had been dropped from `wtf-mps.js`
while still called (threw, and blocked the `#senate`/`#ridings` deep links
behind it); the ridings tab never initialised on a deep link because
`wtf-ridings.js` loads after the hash handler runs; four pages built from the
CRTC donor still carried its inline script (`chain`, `edu`, `governance`,
`score`); social metadata on 37 pages was CRTC boilerplate; the lobbying
organisation drill-down (`/lobbying/<org>`) had been lost in the table
rebuild; seven dead `href="#"` on journalists; map page had no footer; the
inline accuracy section did not link to the full report; three different
paywall-preview keys were in play and the archive deleted the one the feed used.

### Shared layer — becomes static assets

| File | What it holds | On implementation |
| --- | --- | --- |
| `wtf-accountability.js` | OFFICERS with enforcement kind, FINDINGS (named, cited), GIC_VACANCIES, FINDING_KINDS, NO_REMOVAL. One source for officers, ethics, cross-watch, party records. | as-is |
| `wtf-brand.js` | window.WTFBrand — monogram tiles and wordmarks; swap in logoUrl when a licensed asset exists. | as-is |
| `wtf-candidates.js` | RACES with confirmed / declared candidates. | nominations table. |
| `wtf-corpus.js` | Sample article corpus (241 rows / 24 stories), BANDS, VERDICTS, entity map. | replace with DB queries; keep the field names. |
| `wtf-parliament.js` | SEAT_XY / SENATOR_XY floor plans (lifted from live mps.html), rosters, party + caucus colours, BILLS, RETIRE_WAVE. | riding, province, party come from the DB; keep the coordinates. |
| `wtf-promises.js` | Platform commitments and PARTY_META. | promise tracker table. |
| `wtf-record-context.js` | Context, caveat and source per party-record entry, keyed partyId|title. Editorial — desk review before publish. | as-is |

Load order matters where a page reads globals: `wtf-corpus.js` and
`wtf-parliament.js` before any page script; `wtf-accountability.js` before
`wtf-officers.js` / `wtf-ethics.js` / `wtf-cross-watch.js`; `wtf-brand.js`
before `wtf-parties.js` / `wtf-platforms.js` / `wtf-races.js`; `wtf-nav.js`
last on every page. The ridings tab (`wtf-ridings.js`) must initialise itself
if its pane is already showing when it loads — see the note at the end of that
file — or a `#ridings` deep link renders an empty pane.

### Page → route → dependencies

| Design file | Live route | Nav group | Page scripts | CDN | Gate |
| --- | --- | --- | --- | --- | --- |
| `wtf-accuracy.html` | `/forecast-accuracy` | News › Weather | — | — | — |
| `wtf-activity.html` | `/activity` | News | `wtf-corpus.js` `wtf-activity.js` | — | — |
| `wtf-api.html` | `/api` | Data | — | — | yes |
| `wtf-archive.html` | `/archive` | News | `wtf-corpus.js` | — | yes |
| `wtf-article.html` | `/article/<id>` | News (detail) | `wtf-corpus.js` | — | yes |
| `wtf-blindspot.html` | `/blindspot` | News | `wtf-corpus.js` `wtf-blindspot.js` | — | — |
| `wtf-chain.html` | `/chain` | Data | — | — | — |
| `wtf-city.html` | `/weather/city/<name>` | News › Weather (detail) | _inline_ | — | — |
| `wtf-claims.html` | `/claims` | Data | — | — | yes |
| `wtf-clusters.html` | `/clusters` | News | — | — | — |
| `wtf-cost.html` | `/cost` | Money | — | — | yes |
| `wtf-creed.html` | `/creed` | About | — | — | — |
| `wtf-cross-watch.html` | `/cross-watch` | Data | `wtf-accountability.js` `wtf-corpus.js` `wtf-cross-watch.js` | — | — |
| `wtf-crtc.html` | `/crtc` | Media | `wtf-corpus.js` | — | — |
| `wtf-divergence.html` | `/divergence` | News | — | — | yes |
| `wtf-economy.html` | `/economy` | Money | — | — | yes |
| `wtf-edu.html` | `/edu` | Data | — | — | — |
| `wtf-elections.html` | `/elections (#federal #provincial #municipal #coverage)` | Elections | `wtf-corpus.js` `wtf-candidates.js` `wtf-elections.js` `wtf-elections-extra.js` | d3 @7.9.0 topojson-client @3.1.0 | — |
| `wtf-ethics.html` | `/ethics` | Politics | `wtf-accountability.js` `wtf-record-context.js` `wtf-ethics.js` | — | — |
| `wtf-gic.html` | `/gic` | Politics | `wtf-corpus.js` `wtf-accountability.js` | — | yes |
| `wtf-governance.html` | `/governance` | About | — | — | — |
| `wtf-home.html` | `/` | Home | _inline_ | d3 @7.9.0 topojson-client @3.1.0 | yes |
| `wtf-journalists.html` | `/journalists` | Media | — | — | yes |
| `wtf-literacy.html` | `/literacy` | About | — | — | — |
| `wtf-lobbying.html` | `/lobbying, /lobbying/<org>` | Politics | `wtf-corpus.js` `wtf-parliament.js` | — | yes |
| `wtf-map.html` | `/map` | Data | _inline_ | d3 @7.9.0 topojson-client @3.1.0 | — |
| `wtf-markets.html` | `/markets` | Money | — | — | yes |
| `wtf-methodology.html` | `/methodology` | About | — | — | — |
| `wtf-mp.html` | `/mp/<slug>` | Politics (detail) | `wtf-parliament.js` `wtf-corpus.js` `wtf-mp.js` | — | yes |
| `wtf-mps.html` | `/mps (#hoc #senate #ridings)` | Politics | `wtf-parliament.js` `wtf-mps.js` `wtf-ridings.js` | d3 @7.9.0 topojson-client @3.1.0 | — |
| `wtf-municipal.html` | `/municipal` | Politics | `wtf-corpus.js` | — | — |
| `wtf-news.html` | `/news` | News | `wtf-corpus.js` | — | yes |
| `wtf-officers.html` | `/officers` | Politics | `wtf-accountability.js` `wtf-record-context.js` `wtf-officers.js` | — | yes |
| `wtf-outlet.html` | `/source/<name>` | Media (detail) | `wtf-corpus.js` | — | — |
| `wtf-owners.html` | `/owners` | Media | `wtf-corpus.js` | — | — |
| `wtf-parties.html` | `/parties, /parties/<id>` | Politics | `wtf-brand.js` `wtf-record-context.js` `wtf-parties.js` `wtf-promises.js` `wtf-parties-app.js` | — | — |
| `wtf-platforms.html` | `/platforms` | Politics | `wtf-brand.js` `wtf-promises.js` `wtf-platforms.js` | — | — |
| `wtf-races.html` | `/races, /races/<id>` | Elections | `wtf-brand.js` `wtf-candidates.js` `wtf-races.js` | — | — |
| `wtf-rates.html` | `/rates` | Money | `wtf-corpus.js` | — | yes |
| `wtf-ridings.html` | `(redirect)` | redirect → mps#ridings | _inline_ | — | — |
| `wtf-score.html` | `/score` | About | _inline_ | — | — |
| `wtf-search.html` | `/search?q=` | Data | `wtf-corpus.js` | — | — |
| `wtf-senator.html` | `/senator/<slug>` | Politics (detail) | `wtf-parliament.js` `wtf-senator.js` | — | yes |
| `wtf-sources.html` | `/sources` | Media | `wtf-corpus.js` | — | — |
| `wtf-team.html` | `/team` | About | — | — | — |
| `wtf-weather.html` | `/weather` | News | _inline_ | d3 @7.9.0 topojson-client @3.1.0 | — |

CDN: `d3 @7.9.0` and `topojson-client @3.1.0` from unpkg (pinned, with
integrity hashes on the pages that were built first); Natural Earth geometry
from jsDelivr on the weather, map and elections pages — **serve a trimmed
`canada-provinces.geojson` from `consumer/static/` instead** (the CDN file is
~2 MB). The ridings tab and the search page call the **Represent API**
(represent.opennorth.ca, CORS-enabled) live; on the live site the same fields
come from the newsroom database.

### Preview / paywall state

Every gate on the site now reads **one key**: `sessionStorage['wtf-gate-preview']`.
It is a design-review toggle, never a tier flag, and it is per-tab. Production
replaces every read of it with the real tier check from `consumer/access.py`;
nothing else on any page should decide what a subscriber sees.
