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

date: 2026-09-02T11:24:36Z
mode: read-only exploration (no write access from this project)

### Updated in this project
- Rebuilt 39 pages as HTML design references, delivered as a Claude Code
  handoff package (`design_handoff_wtf_newsroom/`) rather than a push.
- Nav IA reworked to the live six-group structure: News, Politics, Money,
  Media, Data, About — Weather moved under News, Data group added.
- Corrected ten factual defects found in the live site; listed in the handoff
  README's corrections table.
- Lifted the live `SEAT_XY` (343) and `SENATOR_XY` (96) floor-plan tables from
  `templates/mps.html` so both chamber maps use real seat positions.

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

## Sync history

- 2026-09-01 — recorded as `KytranKatarn/what-the-fact-site`; that repo turned
  out to be the Coming Soon landing page, corrected above.
