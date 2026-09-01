# Kytran Empowerment Website — design conventions

## Setup
No provider or wrapper. Plain HTML on a dark ground: `css/base.css` styles `body` with
`--color-base` (#0a0a1a) and `--color-text` (#e0e0e0) — never paint your own page
background, the closure does it. Fonts load from Google Fonts via `styles.css`:
**Antonio** (`--font-nav`), **Orbitron** (`--font-heading`), **IBM Plex Mono**
(`--font-body` — body copy is monospace by design). Reduced-motion overrides import
last; keep any animation you add inside `@media (prefers-reduced-motion: no-preference)`
or rely on the existing classes.

## Styling idiom — semantic classes + BEM `--` modifiers, tokens for glue
This is NOT a utility-class system. Compose from the component vocabulary, style your
own layout glue with custom CSS using the tokens. There is no Bootstrap-style row/col grid —
use flex/grid in your own rules.

Components (from `css/components.css` / `css/base.css`):
`.nav` (fixed, `--nav-height` 80px; `.nav--scrolled` variant) · `.hero` ·
`.section` (vertical rhythm via `--space-section` 8rem) · `.glass-panel`
(the signature glassmorphism surface: `--color-glass-bg` + `--color-glass-border` +
backdrop blur) · `.card` and `.card-grid` · `.btn` with `.btn--primary`,
`.btn--outline`, `.btn--lg` · `.cta-section` · `.trust-strip` · `.footer`.

Tokens (all defined in `css/base.css` `:root`):
- Color: `--color-base` #0a0a1a · `--color-primary` #00e5ff (cyan) ·
  `--color-secondary` #8b5cf6 (violet) · `--color-accent` #f472b6 (pink) ·
  `--color-text` · `--color-text-muted` · `--color-border` ·
  `--color-glass-bg` · `--color-glass-border`
- Type scale: `--text-xs` … `--text-4xl`, `--text-hero` (clamp 2.5–5rem)
- Space: `--space-xs` … `--space-3xl`, `--space-section`
- Shape/motion: `--border-radius` 12px · `--ease-out` · `--speed-fast|medium|slow`
- Layout: `--max-width` 1200px · `--nav-height`

## Where the truth lives
Read `css/base.css` (tokens + reset + body ground) and `css/components.css` before
styling. `css/responsive.css` holds the breakpoints; `css/reduced-motion.css` the
accessibility overrides. Page-specific styles are staged under `css/pages/` but NOT
imported — the closure carries `home.css` + `hero-animations.css` only.

## Idiomatic example
```html
<section class="section">
  <div class="glass-panel" style="max-width: var(--max-width); margin: 0 auto; padding: var(--space-2xl);">
    <h2 style="font-family: var(--font-heading); font-size: var(--text-3xl); color: var(--color-primary);">
      Sovereign Canadian AI
    </h2>
    <p style="color: var(--color-text-muted); margin-block: var(--space-md) var(--space-xl);">
      Local-first inference on Canadian-owned hardware.
    </p>
    <a class="btn btn--primary btn--lg" href="#">Get Started</a>
    <a class="btn btn--outline" href="#">Learn More</a>
  </div>
</section>
```
