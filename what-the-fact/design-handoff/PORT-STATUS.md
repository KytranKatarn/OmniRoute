# Design port status

The single place that says which design pages are live. **Claude CLI updates
this file in the same PR that changes a template.** Claude Design reads it
before designing anything, so it never works against stale code.

Status: `todo` · `pr` (open, add number) · `merged` · `live` (deployed and checked)
Spec: `design-handoff/<design file>`. Rules: `.design-sync/DESIGN-BRIEF.md`.

| # | Design file | Template | Status | PR | Notes |
|---|---|---|---|---|---|
| 1 | shell (`_nav.html`, `wtf-shell.css`) | `base.html`, `static/style.css` | pr | #3544 | PR 01 (logo + brand cyan) applied. NOT yet ported: nav bar background, one-row layout with LIVE pill, globe+EN, search circle, SIGN IN as plain text, chip order, ECONOMY emoji |
| 2 | `wtf-home.html` map zone | `index.html` | todo | | Leaflet → `wtf-map.js`: prepared as PR 02 |
| 3 | world projection | `static/js/wtf-map.js` | todo | | Shared component — own PR |
| 4 | `wtf-home.html` rest (weather strip glyphs, feed spread, gate) | `index.html` | todo | | |
| 5 | `wtf-news.html` | `news.html` | todo | | |
| 6 | `wtf-archive.html` | `archive.html` | todo | | |
| 7 | `wtf-article.html` | `article.html` | todo | | |
| 8 | `wtf-weather.html` | `weather.html` | todo | | Already on `wtf-map.js`; diff layers only |
| 9 | `wtf-city.html` | weather city view | todo | | |
| 10 | `wtf-mps.html` | `mps.html` | todo | | Riding / province / party from DB — never derived |
| 11 | `wtf-mp.html`, `wtf-senator.html` | `mp.html`, `senator.html` | todo | | |
| 12 | `wtf-blindspot.html` | `blindspot.html` | todo | | |
| 13 | `wtf-divergence.html` | `divergence.html` | todo | | |
| 14 | `wtf-clusters.html` | `clusters.html` | todo | | |
| 15 | `wtf-lobbying.html` | `lobbying.html` | todo | | |
| 16 | `wtf-gic.html` | `gic.html` | todo | | |
| 17 | `wtf-ethics.html` | `ethics.html` | todo | | |
| 18 | `wtf-officers.html` | `officers.html` | todo | | Gate moves below mandates — see README |
| 19 | `wtf-municipal.html` | `municipal.html` | todo | | |
| 20 | `wtf-parties.html`, `wtf-platforms.html` | `parties.html`, `platforms.html` | todo | | |
| 21 | `wtf-elections.html`, `wtf-races.html` | `elections.html`, `races.html` | todo | | |
| 22 | `wtf-economy.html` | `economy.html` | todo | | |
| 23 | `wtf-rates.html` | `rates.html` | todo | | |
| 24 | `wtf-cost.html` | `cost.html` | todo | | |
| 25 | `wtf-global.html`, `wtf-debt.html` | new routes | todo | | |
| 26 | `wtf-markets.html` | `markets.html` | todo | | |
| 27 | `wtf-sources.html`, `wtf-outlet.html` | `sources.html`, `source.html` | todo | | |
| 28 | `wtf-owners.html` | `owners.html` | todo | | |
| 29 | `wtf-journalists.html` | `journalists.html`, `journalist.html` | todo | | Delete the green-centre ramp |
| 30 | `wtf-crtc.html` | `crtc.html` | todo | | |
| 31 | `wtf-echo.html` | new route | todo | | |
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

Templates are the likely target by name. Confirm the real filename in
`consumer/templates/` before starting a row, and correct this table if it differs.

---

## Rows 1 and 2 are blocked

The standing brief says to apply two prepared PRs, `pr-01-shell-branding/` and
`pr-02-homepage-map/`. **Neither exists** — not in `design-handoff/`, not in the
handoff zip, not in any other bundle on the host (checked 2026-09-23). Rows 1 and
2 stay `todo` until Claude Design delivers them **as a PR into this repo**, not as
an archive. Start at row 3 or later in the meantime; nothing else depends on them.
