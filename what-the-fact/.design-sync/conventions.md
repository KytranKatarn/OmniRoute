# What The Fact — design conventions

## 🔴 WHERE THIS CODE LIVES — read before connecting a repo

**Two repos exist. Only ONE is deployed. This will change, so check the date below.**

| Repo | Role right now (as of 2026-09-05) |
|---|---|
| `KytranKatarn/archie-platform`, path `what-the-fact/` | 🟢 **THE DEPLOYED SOURCE.** what-the-fact.com runs from here. Any change meant to reach production goes here. |
| `KytranKatarn/kytran-what-the-fact` | 🟡 **History mirror, not yet live.** Same code, full preserved history (602 commits: 600 for the app + the static landing page's history merged in under `static-site/`), created so Design tooling has a real repo with real git history to work against. **Nothing pushed here reaches what-the-fact.com until a separate, explicitly-gated cutover (new DB instance + F.O.R.G.E. token grant + deploy retarget) happens.** |

Live site: `what-the-fact.com` — Flask + Jinja2 + Postgres, ~30 consumer routes.

| | |
|---|---|
| Consumer pages/routes | `consumer/routes.py` (one large file) |
| Templates | `consumer/templates/*.html` |
| The shared shell (`css/style.css`) | `consumer/static/` |
| Ingest / clustering / scoring | `ingest/` |
| Migrations | `migrations/` |
| Static landing page (pre-app, retired) | `static-site/` — only in `kytran-what-the-fact`, not in archie-platform's `what-the-fact/` |

🔴 **DO NOT connect `KytranKatarn/what-the-fact-site`, `kytran-news`, or
`kytran-news-site`.** All three are archived dead ends from the April 2026
pre-launch attempt (`what-the-fact-site` = static "Coming Soon" page, `kytran-news`
= the pre-consolidation app skeleton before it was folded into this codebase,
`kytran-news-site` = a landing page for a domain that no longer even resolves).
`what-the-fact-site`'s README used to call itself the "Official website", which
is why a Design session connected to it on 2026-09-01, found no app, and had to
review the live site by hand instead. All three now carry corrective READMEs and
are archived — but the name is still the trap; believe this file, not theirs.

⚠️ **Until cutover, `archie-platform` stays authoritative for deploys.**
`kytran-what-the-fact` is real and current as of the push date above, but it is
not re-synced automatically — treat it as a snapshot for exploration/coordination,
and verify anything load-bearing against `archie-platform`'s live `what-the-fact/`
before assuming it reflects the current deployed state.

## Setup
No provider or wrapper. Dark editorial ground: `css/style.css` puts `--wtf-bg`
(#0d1117) and `--wtf-text` (#f2f1ed) on `body` — never paint your own page background.
Fonts load via `styles.css` from Google Fonts: **Newsreader** (`--wtf-font-serif`,
headlines — this serif IS the editorial identity), **IBM Plex Sans**
(`--wtf-font-body`), **IBM Plex Mono** (`--wtf-font-mono`, data/labels). Utility
classes `.serif` and `.mono` switch families inline.

## Styling idiom — `wtf-` namespaced classes, meaning carried by color tokens
Every class is `wtf-`-prefixed; new page-level styles get their own sub-namespace
(existing pages use `wtf-bs-`, `wtf-dv-`, `wtf-ec-`, `wtf-mu-`, `wtf-wx-`). No utility
grid — write flex/grid glue yourself with the tokens. Surfaces step up from
`--wtf-bg` → `--wtf-bg-card` (#11161f) → `--wtf-bg-panel` (#171e2a), bordered
`--wtf-border` (#222b39).

Shell vocabulary (all in `css/style.css`):
`.wtf-nav`, `.wtf-nav-brand`, `.wtf-nav-links`, `.wtf-nav-live`, `.wtf-nav-search`,
`.wtf-nav-subscribe` · `.wtf-wordmark` · `.wtf-section-label` (mono, uppercase kicker)
· `.wtf-top-story` · `.wtf-article-card` with lean modifiers
`.wtf-article-card--left|--center-left|--center|--center-right|--right` ·
`.wtf-card-title` (Newsreader), `.wtf-card-meta` (mono), `.wtf-card-badge` ·
`.wtf-bias-pill` colored by `.wtf-bias-left|center-left|center|center-right|right` ·
`.wtf-badge-ai`, `.wtf-badge-active`, `.wtf-live-dot` · `.wtf-footer`.

Color tokens carry MEANING — never repurpose them decoratively:
- Masthead accent: `--wtf-accent` #dc2626 (red)
- Bias spectrum (Canadian convention, left=red → right=blue): `--wtf-left` #d84b47 ·
  `--wtf-center-left` · `--wtf-center` #929aa5 · `--wtf-center-right` ·
  `--wtf-right` #4a72d8
- Fact-check verdicts: `--wtf-established` #10b981 (green) · `--wtf-developing`
  #f59e0b (amber) · `--wtf-contested` #e05252 (red)
- Product/agent accents: `--wtf-fact` red · `--wtf-bias` amber · `--wtf-verify`
  green · `--wtf-local` blue · `--wtf-aurora` violet
- Text ramp: `--wtf-text` → `--wtf-text-2` → `--wtf-text-muted`

## Where the truth lives
Read `css/style.css` before styling — it is the whole shared shell (tokens `:root`
at top, then nav, cards, bias pills, badges, footer). Page-specific styles on the
live site sit in per-template `<style>` blocks and are not part of this bundle.

## Idiomatic example
```html
<article class="wtf-article-card wtf-article-card--center-left">
  <div class="wtf-card-meta mono">CBC NEWS · 2H AGO</div>
  <h3 class="wtf-card-title serif">Parliament votes on procurement transparency bill</h3>
  <span class="wtf-bias-pill wtf-bias-center-left">Center-Left</span>
  <span class="wtf-card-badge" style="color: var(--wtf-established);">✓ Established</span>
</article>
```
