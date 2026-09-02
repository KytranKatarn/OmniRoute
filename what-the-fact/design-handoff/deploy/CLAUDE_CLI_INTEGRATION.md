# Claude CLI integration brief — What The Fact design bundle

**Repo:** `kytran-empowerment/kytran-platform` · **Scope:** `what-the-fact/consumer/`
**Bundle:** this folder (`design-handoff/` in the repo) — 50 pages, 29 scripts, 1 stylesheet, 1 geometry file.
**Deploy mechanism:** `what-the-fact/deploy.sh consumer` (rsync + rebuild the consumer container). No CI between merge and live: **one PR per phase is the safety net.**

Read `deploy/DEPLOY.md` (runbook), `deploy/sync-diff.md` (what changed vs the repo copy), and `README.md` (per-page contracts) before touching a template. This file is the order of operations and the non-negotiables.

## Non-negotiables — check every PR against these

1. **Nothing hand-entered where an API exists.** Cost `/api/cost/summary`, chain `/api/public/chain/*`, governance `/api/creed-badge`, rates Valet V122514, cross-watch entities, weather/fire feeds, team roster `get_public_roster`. The design files carry sample constants behind `WTFLive.get(url, fallback)`; when the endpoint answers the sample never renders. A page rendering its sample in production is a bug.
2. **Riding, province, party come from the database.** Absent → em dash. No derivation, no hash fallback. (MPs, Senators, Ridings, Races, Candidates.)
3. **One tier check.** `wtf-tier.js` reads `window.__WTF_TIER` set by `base.html` from `access.py`. Delete the sessionStorage preview branch on the server side; the smoke test's "Tier in page" column must read *no* on every route.
4. **Per-story counts, never per-outlet-row.** Fact-checked, blindspot, dispute counts. The archive stat was wrong once already.
5. **Meaning colours stay meaning colours.** Lean spectrum (red→blue), verdict green/amber/red, agent accents from `TEAM_AGENTS.accent_colour`. Party colours appear only as solid dots on floor plans, never beside a lean band. Cost components and owner types use shape/neutral, never red/blue.
6. **Loop the data, never hardcode a roster.** Team page (`TEAM_AGENTS` + directory), nav groups, beat pills, source lists.

## Order of operations (one PR each)

| Phase | Files | Gate to merge |
| --- | --- | --- |
| 0 | Replace `design-handoff/` with this bundle | none — reference only |
| 1 | `base.html`, `static/style.css`, `static/js/{tier,live,a11y,i18n}.js`, `static/dev/smoke-test.html`, `static/canada-provinces.geojson`, 404 handler, placeholder routes for every nav link | every route 200s; nav opens on hover **and** tap; smoke test green; no `overflow` on `.wtf-nav` |
| 2 | `/archive`, `/search`, `/score`, `/activity`, `/echo`, `/global`, `/debt`, `/parties`, `/platforms`, `/races`, `/ridings`, `/elections` | additive; smoke test green |
| 3 | `index`, `news`, `article`, `blindspot`, `divergence`, `clusters`, agent colours aligned to `accent_colour` | one page at a time; per-story counts verified against SQL |
| 4 | `weather`, `city`, `accuracy`, `map` | local geojson served; feeds wired; sample flag never visible |
| 5 | `mps`, `mp`, `senator`, `officers`, `gic`, `ethics`, `lobbying`, `municipal`, `rates` | DB values for riding/province/party; Represent API cached server-side |
| 6 | `cost`, `economy`, `markets`, `journalists`, `journalist`, `sources`, `outlet`, `owners`, `crtc`, `cross-watch`, `entity`, `chain`, `claims`, `api`, `edu`, `methodology`, `team`, `governance`, `creed`, `literacy` | any order; C.R.E.E.D. grade from `/api/creed-badge` only |

## Template conventions (Jinja side)

- Page styles live in the template's own `<style>` block, namespaced `wtf-<pg>-`. Only shell rules go to `static/style.css` (and never in the same commit as a page style — `.design-sync/` re-exports it).
- Every `wtf-*.js` in the bundle becomes `static/js/<name>.js`; the inline `<script>` in each design page becomes the template's script block, with sample constants replaced by `{{ data|tojson }}` injections or the `WTFLive.get` URL.
- `_nav.html` → the nav block in `base.html`. The i18n toggle already sits on the repo's `I18n` contract (`wtf-lang`, `.lang-btn`, `data-i18n`, RTL for ar/he); load `static/js/i18n.js` + `translations.json` instead of `wtf-i18n.js`.
- Deep-link params are part of the contract: `?id=` (article), `?story=` (divergence/clusters), `?entity=` (cross-watch), `?e=` (chain), `?j=` (journalist), `?city=` (weather).

## After each deploy

`./deploy.sh consumer` → open `/static/dev/smoke-test.html` → all rows green (errors 0, nav ok, footer ok, tier-in-page **no**, no `href="#"`) → spot-check three numbers against a direct query → next phase.

## Known reconciliations (decide before Phase 6)

- C.R.E.E.D.: case study says A+, scan returns 58/F. Show the endpoint, never a hand grade.
- Rates: decisions after March 2025 are placeholders until Valet is wired.
- Fire perimeters and stations: the design's polygons are generated; production geometry is CWFIS.
- Cost: 2026 figures are year-to-date addenda and must never sum into the 5-year headline.
