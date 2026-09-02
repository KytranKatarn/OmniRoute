# Deploying the newsroom rebuild

Repo `KytranKatarn/archie-platform`, path `what-the-fact/`. The app deploys with
`what-the-fact/deploy.sh`, which rsyncs the directory to the VPS and runs
`docker compose up -d --build` — there is no other deploy path, and no CI step
between merge and live. That makes the phase discipline below the safety net.

Nothing in this bundle reaches the repo through `.design-sync/` — that syncs
`consumer/static/style.css` *out* to the design system, one way, styles only.

## 0. Land the handoff in the repo (no runtime effect)

The repo already carries `what-the-fact/design-handoff/` — the 39-page snapshot
from earlier on 2026-09-02. This bundle supersedes it: 26 files added, 44
changed, 7 unchanged, none removed (`deploy/sync-diff.md` lists every one).

```bash
git checkout -b design/newsroom-final-sweep
rm -rf what-the-fact/design-handoff
cp -r design_handoff_wtf_newsroom what-the-fact/design-handoff
git add -A what-the-fact/design-handoff
git commit -m "design-handoff: final sweep — 46 pages, zero runtime errors, migration manifest"
```

Open a PR. It touches nothing under `consumer/`, so it can merge immediately;
it exists so every later PR can cite a file in `design-handoff/` by path.

## 1. Implementation PRs — one per phase

Claude Code does the template work. `deploy/CLAUDE_CODE_BRIEF.md` is the
brief for Phase 1 and the template for the rest. The phases, their contents
and their hard requirements are in `README.md › Deploying this`; the file →
route → script mapping is in `README.md › Migration manifest`.

| Phase | Scope | Deploy risk |
| --- | --- | --- |
| 1 | `base.html` nav + `static/style.css` shell rules | Visible on every page; blocks the rest |
| 2 | `/archive`, `/search`, `/score`, `/activity`, `/elections`, `/parties`, `/races`, `/platforms` | Additive routes; zero risk to existing pages |
| 3 | `index.html`, `news.html`, `article.html` | Highest traffic; one template per deploy |
| 4 | `weather.html` + city view | Self-contained |
| 5 | `mps.html`, `mp.html`, `senator.html` | **Needs riding / province / party from the DB** |
| 6 | Politics, Media, Data, About sections | Independent of each other |

Rules that every PR must satisfy before it merges:

- `pytest tests/` passes (`pip install -r requirements-dev.txt` first).
- Every route in the PR renders against a **real database read** — no page
  ships with values from `wtf-corpus.js` or the other sample files.
- Page styles live in the template's own `<style>` block under its own
  `wtf-xx-` namespace; only shell rules go into `static/style.css`, and never
  in the same commit as page styles.
- Nothing reads `sessionStorage['wtf-gate-preview']` — every gate reads the
  real tier from `consumer/access.py`.
- No derived ridings, provinces or parties (Phase 5). An empty field renders an
  em dash. This is the one failure mode the site cannot afford.

## 2. Deploy a phase

```bash
cd what-the-fact
pytest tests/                       # must be green
./deploy.sh consumer                # rsync + docker compose up -d --build wtf-consumer
```

`deploy.sh consumer` rebuilds only the consumer service. Do not run
`./deploy.sh` with no argument for a template change — it rebuilds ingest and
the API too, which nothing in this handoff touches.

## 3. Smoke-test what just went live

Copy `deploy/smoke-test.html` to `consumer/static/dev/smoke-test.html` once
(Phase 1 PR). After every deploy, open

    https://what-the-fact.com/static/dev/smoke-test.html
    http://localhost:8103/static/dev/smoke-test.html      # local compose

It loads every route from the same origin with an error hook written into each
page before its scripts run, and reports per route: runtime errors, shared nav
and footer present, body content, `undefined` / `NaN` leaked into text, broken
images, dead `href="#"`. This is the harness that found the defects listed in
the manifest; nothing here is optional. `?pages=/mps,/elections` narrows it to
the phase you just shipped.

Then the checks a harness cannot do — per phase, on a real phone as well:
numbers match a direct database query; dropdowns open on tap; nothing is
clipped; `prefers-reduced-motion` is honoured; no page paints its own
background. After Phase 3 in particular: any count that should be per-story
rather than per-article-row, and any place a verdict or lean colour is used for
something that is not a verdict or a lean.

## 4. Roll back

Templates are stateless, so rollback is a redeploy of the previous commit:

```bash
git revert -m 1 <merge-sha>         # or git checkout <previous-sha> -- what-the-fact/consumer
./deploy.sh consumer
```

No migration in this handoff touches the database, so there is nothing to roll
back on the data side.

## Platform layer added before deploy

Four shared scripts now load on every page, right after the nav, in this order:

- `wtf-tier.js` — **the only tier check on the site.** `WTFTier.isSubscriber()`
  reads `window.__WTF_TIER` when the server sets it (`base.html`:
  `<script>window.__WTF_TIER = {{ tier|tojson }}</script>` from `access.py`) and
  removes every "Show subscriber view" control. The sessionStorage branch is
  the design-review toggle and is never reached in production. The smoke test's
  "Tier in page" column must read **no** on every live route.
- `wtf-i18n.js` — the repo's `I18n` contract (`wtf-lang`, `.lang-btn`,
  `data-i18n`, RTL for ar/he) with the eight platform languages in the nav
  toggle: en fr es pt de zh ar he. In production load `static/js/i18n.js` and
  `static/data/translations.json` instead; the nav markup is already on the
  contract. Copy that should translate needs `data-i18n` keys — the design
  files mark none yet, so translation coverage is a content task on
  platform.kytranempowerment.com, not a template task.
- `wtf-live.js` — `WTFLive.get(url, fallback)` fetches a same-origin endpoint
  and falls back to the page's sample constants, marking the page "sample
  figures" when it does; `WTFLive.injected(name, fallback)` reads
  server-injected data. Wired: cost (`/api/cost/summary`), chain
  (`/api/public/chain/links`), governance (`window.__WTF_SCAN`), rates
  (`window.__WTF_DECISIONS`), cross-watch (`window.__WTF_ENTITIES`). When the
  endpoint answers, the sample never renders.
- `wtf-a11y.js` — keyboard activation for every clickable non-link, names for
  every unlabelled SVG, visible focus. Keep it; it costs nothing.

Also added: `wtf-404.html` (wire to `@app.errorhandler(404)`), geometry loads
try `canada-provinces.geojson` locally before the CDN, and the narrow-screen
rules in `wtf-shell.css` (≤720 px stacks the grid rows, ≤900 px collapses the
two-column layouts). `wtf-corpus.js` is loaded only on pages that read it.

## Static assets to add in Phase 1

- `consumer/static/dev/smoke-test.html` (above).
- `consumer/static/canada-provinces.geojson` — Natural Earth 50m admin-1
  filtered to Canada. The design files load the ~2 MB world file from jsDelivr;
  the pages that need it are weather, map and elections. Serve the trimmed file
  and change the three fetch URLs.
- Shared JS from the manifest's shared-layer table goes to
  `consumer/static/js/` **only where it is genuinely static** — seat coordinates
  (`SEAT_XY`, `SENATOR_XY`), the brand helper, the nav script. Everything that
  stands in for a database query (`wtf-corpus.js`, rosters, findings, promises,
  candidates) becomes a query in `routes.py`, not a static file.
