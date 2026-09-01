# What The Fact — design conventions

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
