# What The Fact — redesign canvas (18 artboards)

Source: Claude Design canvas artifact **"What The Fact Redesign"**
https://claude.ai/code/artifact/2160fd2a-ea32-409c-8b48-84da665f2b6f (owner-private)

These are the **verbatim `.dc.html` artboard sources** lifted from the canvas bundle's
`appifact-doc` record, plus `canvas.json` (layout, page groups, annotations).

> ⚠️ **Corrected 2026-08-30.** An earlier extraction here held only 4 lossy HTML
> slices (`board_01..04`) and its README claimed the design covered home + weather
> only. That was wrong — it missed **14 of the 18 artboards**, including the entire
> Core loop and every page archetype. Those slices have been deleted. Read
> `canvas.json` for the authoritative structure; these files are exact sources, not
> slices.

## The design in one line

**Premium editorial dark.** Keeps the brand DNA — `#0d1117` ink ground, `#dc2626` red
accent, verdict + agent colour meanings, mono data labels. New: Newsreader headline
serif + IBM Plex Sans body (actually loaded this time), photo-led cards, a designed
coverage map, nav regrouped from 24 links into 6, and the 87-chip riding wall
collapsed into a filter bar.

## Artboards

### Core loop — the shell every page inherits
| file | covers |
|---|---|
| `DesignLanguage.dc.html` | tokens, type scale, colour meanings, icon set |
| `Main.dc.html` | home / masthead, live counter, beat nav, hero, Blindspot + Divergence teasers |
| `NewsFeed.dc.html` | the feed + filter bar |
| `Article.dc.html` | article page |
| `HomeMobile.dc.html` · `NewsFeedMobile.dc.html` | mobile home + feed (filter-token style) |

### Five archetypes — these cover the remaining ~40 pages
All 46 templates extend `base.html`, so the Core-loop shell lifts every page
automatically. What is designed is each page **BODY** — one pattern per repeating
shape, **not one design per page**.

| # | file | covers |
|---|---|---|
| 1 | `EntityProfile.dc.html` | mp, senator, entity, journalist, source, owner detail |
| 2 | `Directory.dc.html` | mps, journalists, officers, owners, gic, sources |
| 3 | `DataExplorer.dc.html` | lobbying, economy, rates, cost, markets, crtc, claims, municipal, blindspot, divergence |
| 4 | `MapGeo.dc.html` | map, weather, municipal |
| 5 | `EditorialAccount.dc.html` | methodology, team, governance, ethics, literacy, edu, api_docs · account, alerts, beats, api_keys, connect |

### Flagship pages — the four a generic pattern could not serve
| file | why it is bespoke |
|---|---|
| `Weather.dc.html` | the site's most complex page (807 lines); own city grid + forecast strip |
| `ChainExplorer.dc.html` | Money → MP → Vote → Policy → Contract → Market → Coverage → Public — the product's whole thesis |
| `ToolsActivity.dc.html` | score-an-article is a tool, not a page |
| `MobileNav.dc.html` | the live drawer is 19 flat items, two sharing the same 🔗 glyph |

### Weather deep-dive
`WeatherMap.dc.html` · `WeatherCity.dc.html` · `ForecastAccuracy.dc.html`

## Rules the design encodes (do not lose these in translation)

- **Lean scale is diverging red → neutral grey → blue.** The old red/orange/green/sky/blue
  ramp failed colour-vision checks (red vs orange nearly identical) and put **green at the
  midpoint**, which reads as a quality judgement. **Lean colour never appears without its
  text label** — same rule for party colour bars.
- **A dash means NOT ISSUED, never zero.** The ECCC feed sends `00` for "no gust" on ~94%
  of periods; rendering that as a measurement fabricates data.
- **"Calm" is a measured wind**, not missing data.
- **Per-layer freshness**: city obs 3h, forecast 12h, fire 48h. A 40-hour-old reading must
  not render as current.
- **Disjoint coverage is greyed, not zeroed.** Fire stations and hotspots cover opposite
  halves of the country; switching layer greys what that layer cannot see.
- **Provenance is never blended.** ECCC and Open-Meteo values each carry a source chip
  (blue / violet) on the layer button, range control, forecast footer and extended-range
  banner. For a site whose pitch is showing where data comes from, a silently-mixed
  forecast is the worst possible tell.
- **Extremes are "in our record so far"**, never "record high" — the DB holds ~12 days,
  not a climate baseline. Temperature shading is **interpolated** between 25 stations and
  says so; only station dots are real measurements.
- **Chart magnitude is neutral slate**, red reserved for the highlighted value, so chart
  colour never collides with lean colour.
- **Circle AREA encodes volume** on the map (not radius).
- Photos are placeholders; the real build uses og:image thumbnails already collected at
  ingest, with the dark duotone block as the no-image fallback.
- Emoji headings (🏛 🏢 🌦) are replaced by the inline SVG icon set throughout.

## Measured, not assumed

The weather boards were built against the live DB: `wtf.aurora_city_obs` 4,098 rows /
25 cities / 11.8 days; `wtf.aurora_city_forecast` max `period_index` 12 (Today →
Saturday). **The ECCC public feed has no 14-day forecast and no cloud grid** — 1-day and
5-day ship on data we already hold; 14-day, cloud cover and precipitation need
Open-Meteo (free, no key, commercial use permitted).

`ForecastAccuracy.dc.html` numbers are computed, not invented: 3,481 forecast/outcome
pairs, same-day MAE 1.31 °C (n=656) → 6-day 2.22 °C (n=336), mean bias −1.20 °C at day
5–6 (ECCC under-calls the high at long range).

## Not a redesign problem

The live homepage and map render **"API KEY REQUIRED"** watermark tiles — a missing Carto
basemap key (or a swap to a free tile provider). Filed separately; a redesign does not
fix it.

## Integration

The live consumer is **Flask + Jinja** (`what-the-fact/consumer/`). Integration means
re-expressing these layouts in the existing template/CSS stack — **not** dropping these
files in. Tracked as **#6149**.
