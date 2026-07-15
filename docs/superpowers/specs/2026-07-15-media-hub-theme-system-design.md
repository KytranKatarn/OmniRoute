# Media Hub — Swappable Theme System (design spec)

**Project:** #385 Media Hub pre-release audit remediation · **Task:** #4743 (Custom design phase)
**Date:** 2026-07-15 · **Owner review:** pending · **Status:** design → (next) implementation plan
**Visual mock:** `claude.ai/code/artifact/4ba1086c-d2fd-4978-823c-521f99eb0c0c` (interactive 5-theme preview)

## 1. Context & problem

The standalone Media Hub (`mediahub_app`, media.kytranempowerment.com, image-baked `COPY .`) ships one
hardcoded look: a Plex-gold accent (`#E5A00D`) with scattered color literals across a **135 KB**
`static/css/media-hub.css`, a partial `--mh-accent*` token block (`media-hub.css:2121`), and a
one-off `body.light-mode .media-hub` override (`:2754`). There is **no** complete token layer, **no**
`data-theme` switch mechanism, and **no** user-facing theme choice.

This phase turns that into a **user-selectable theme system**: one complete token layer, five shipped
themes, a Settings picker, and per-browser persistence — with the chrome re-designed to be
**poster-forward** (neutral chrome, artwork carries the color).

## 2. Goals / non-goals

**Goals**
- A complete, semantic **CSS token layer** every component styles through (no raw color literals in
  component rules).
- **5 themes**, switchable at runtime, persisted per-browser: **Neutral Poster-Forward** (new default),
  **LCARS**, **Light**, **Plex Classic** (today's gold, preserved), **OLED True-Black**.
- A **Settings → Appearance** picker with swatches + live apply.
- **No theme flash** on load (theme applied before first paint).
- Preserve today's users: the existing `body.light-mode` experience becomes the real **Light** theme;
  nothing regresses for people who like the gold look (it's **Plex Classic**).

**Non-goals (this phase)**
- Server-side / per-account theme sync (v1 is `localStorage`, per-browser). Noted as a follow-up.
- Per-theme custom layouts — themes reskin, they don't restructure the DOM.
- Theming the login/landing marketing pages beyond inheriting the default (poster grid + dashboard is
  the scope that matters).

## 3. The five themes (validated token sets)

Palettes below are the validated values from the approved mock. Neutrals carry a slight hue bias (chosen,
not default grey). Semantic state colors (`good/warn/crit`) are **independent of each theme's accent** so
status always reads at a glance.

| token | neutral (default) | lcars | light | plex | oled |
|---|---|---|---|---|---|
| `--mh-bg` | `#0d0f13` | `#000000` | `#f4f6f9` | `#0a0a0f` | `#000000` |
| `--mh-surface` | `#161a21` | `#0c0b08` | `#ffffff` | `#14141c` | `#0a0a0a` |
| `--mh-surface-2` | `#1e232c` | `#17130a` | `#eef1f5` | `#1c1c26` | `#141414` |
| `--mh-text` | `#e9ecf1` | `#f4e7d3` | `#171a1f` | `#ececec` | `#ffffff` |
| `--mh-text-muted` | `#98a0ad` | `#c7a061` | `#5b6472` | `#9a9aa8` | `#8b8b8b` |
| `--mh-border` | `rgba(255,255,255,.09)` | `#ff9966` | `rgba(20,24,31,.12)` | `rgba(229,160,13,.18)` | `rgba(255,255,255,.10)` |
| `--mh-accent` | `#6ea8fe` | `#ff9966` | `#2f6bff` | `#e5a00d` | `#22d3ee` |
| `--mh-accent-ink` | `#0b1220` | `#150a03` | `#ffffff` | `#160f00` | `#00181c` |
| `--mh-good` | `#3ecf8e` | `#77cc99` | `#12a15f` | `#46b26a` | `#34d399` |
| `--mh-warn` | `#e6b450` | `#ffcc66` | `#b7791f` | `#e5a00d` | `#fbbf24` |
| `--mh-crit` | `#f87171` | `#cc6666` | `#d64545` | `#e06666` | `#fb7185` |
| `--mh-radius` | `12px` | `22px` | `12px` | `12px` | `12px` |
| display treatment | normal | **uppercase, +0.06em, Antonio** | normal | normal | normal |

LCARS additionally sets `--mh-radius: 22px`, `--mh-display-tt: uppercase`, `--mh-display-ls: .06em`,
`--mh-font-display: Antonio` (self-hosted, §7). Every other theme leaves those knobs at neutral defaults.

## 4. Token architecture

New file **`static/css/theme-tokens.css`**, linked **before** `media-hub.css` so components resolve
tokens. Structure:

```css
/* Defaults = Neutral Poster-Forward (so no attribute still yields the shipped default) */
:root { --mh-bg:#0d0f13; --mh-surface:#161a21; /* …full set… */
        --mh-radius:12px; --mh-radius-sm:8px;
        --mh-font-ui: system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
        --mh-font-display: var(--mh-font-ui);
        --mh-display-tt: none; --mh-display-ls: normal; --mh-display-weight:700;
        /* back-compat aliases so un-migrated rules keep working mid-migration: */
        --mh-accent-bright:#8fc0ff; --mh-accent-dim:#3f6aa8;
        --mh-accent-alpha-10:rgba(110,168,254,.10); /* …etc… */ }

html[data-mh-theme="lcars"] { /* token overrides only */ }
html[data-mh-theme="light"] { … }
html[data-mh-theme="plex"]  { … }   /* = today's gold, verbatim */
html[data-mh-theme="oled"]  { … }
```

Token categories: **surface** (`--mh-bg`, `--mh-surface`, `--mh-surface-2`), **text**
(`--mh-text`, `--mh-text-muted`, `--mh-text-faint`), **border** (`--mh-border`, `--mh-border-strong`),
**accent** (`--mh-accent`, `--mh-accent-ink`, `--mh-accent-soft`, + `-bright`/`-dim`/`-alpha-*` aliases
for back-compat), **semantic** (`--mh-good`, `--mh-warn`, `--mh-crit`, `--mh-info`), **shape/type**
(`--mh-radius`, `--mh-radius-sm`, `--mh-font-ui`, `--mh-font-display`, `--mh-display-tt`,
`--mh-display-ls`, `--mh-display-weight`, `--mh-shadow`, `--mh-glow`), **chip** (`--mh-chip`).

**Back-compat rule:** the existing `--mh-accent`, `--mh-accent-bright`, `--mh-accent-dim`,
`--mh-accent-alpha-*`, `--mh-glow` names are **retained as aliases** in every theme block. This lets the
135 KB migration (§6) proceed component-by-component without a flag day — un-migrated rules keep
rendering with the active theme's accent.

## 5. Switch mechanism (+ no-flash)

- Attribute **`data-mh-theme`** on `<html>` (documentElement). Absent → `:root` defaults = Neutral.
- **No-flash inline script** at the very top of `<head>` in the base template, before any CSS link:
  ```html
  <script>try{var t=localStorage.getItem('mh-theme');if(t)document.documentElement.setAttribute('data-mh-theme',t);}catch(e){}</script>
  ```
  Runs synchronously before first paint → no theme flash.
- **`static/js/theme-switcher.js`**: `applyTheme(name)` sets the attribute + `localStorage['mh-theme']`,
  updates the picker's pressed state, and (v1) does nothing server-side. Exposes the theme registry
  (name → label → swatch) so the Settings UI renders from one source.

## 6. CSS migration strategy (the bulk of the work — phased)

`media-hub.css` is 135 KB with scattered literals. Per `.claude/rules/ui-refactoring.md` (one component
at a time, screenshot before/after, CSS-only), migrate in **component slices**, each independently
deployable and verifiable:

1. **Slice A — foundation:** add `theme-tokens.css` + no-flash script + switcher JS + the 5 token blocks.
   Fold `body.light-mode .media-hub` → `html[data-mh-theme="light"]`; move current gold defaults →
   `html[data-mh-theme="plex"]`. At this point Neutral is live via the token layer; components not yet
   migrated still read the alias tokens.
2. **Slice B — core chrome:** convert `.hub-header`, `.hub-nav`/`.nav-tab`, `.stat-card`, `.poster-card`
   & children, `.panel`, `.media-modal` color literals → `var(--mh-*)`. This is the visible surface area
   from the mock.
3. **Slice C — Settings picker** (§8) + wire `theme-switcher.js`.
4. **Slice D — long tail:** sweep remaining hardcoded colors (badges, charts, TV mode, discover/series
   sub-views) → tokens. `tv-mode.css` inherits tokens; verify OLED + TV mode together.

Acceptance for each slice: all 5 themes render that component correctly at desktop + mobile; no console
errors; contrast legible.

## 7. Fonts (LCARS authenticity)

LCARS needs a condensed display face. **Antonio** is already the platform nav font (`.claude/rules/frontend.md`).
**Self-host** it (woff2) under `static/fonts/` with a local `@font-face` (CSP-safe, no CDN — matches the
standalone-extraction font rule). `--mh-font-display` points at it **only** in the LCARS block; all other
themes keep the system UI stack. If vendoring is deferred, LCARS falls back to
`"Arial Narrow",system-ui` (the mock's behavior) — acceptable but not final.

## 8. Settings UI (Appearance picker)

Add an **Appearance** section to the Settings tab (`.settings-section`): a row of 5 theme cards, each a
mini swatch (bg + surface + accent) + label + `aria-pressed`. Selecting one calls
`applyTheme(name)`. Renders from the `theme-switcher.js` registry (single source of truth). Keyboard
accessible, visible focus ring, honors `prefers-reduced-motion`.

## 9. Files touched

| Action | Path |
|---|---|
| **NEW** | `standalone/media_hub/static/css/theme-tokens.css` (token layer + 5 theme blocks) |
| **NEW** | `standalone/media_hub/static/js/theme-switcher.js` (registry + apply + persist) |
| **NEW** | `standalone/media_hub/static/fonts/antonio-*.woff2` + `@font-face` (LCARS) |
| **EDIT** | `templates/maven_base.html` (+ any standalone template linking media-hub.css): no-flash `<head>` script, `<link>` theme-tokens.css **before** media-hub.css, include theme-switcher.js |
| **EDIT** | `static/css/media-hub.css`: literals → tokens (phased, Slices B/D); `body.light-mode` → `[data-mh-theme="light"]`; gold defaults → `[data-mh-theme="plex"]` |
| **EDIT** | Settings template + section: Appearance picker (Slice C) |

## 10. Testing & acceptance

- All **5 themes** render header/nav/stats/poster-grid/downloading-panel correctly at 1280 / 768 / 480 px.
- Theme **persists** across reload; **no flash** on load (verify with a slow-network throttle).
- **Contrast:** body text ≥ WCAG AA on each theme's ground; accent legible on its ink.
- **Semantic** good/warn/crit remain distinct from accent in every theme (the "Stalled" row stays red).
- Existing **light-mode** users land on the **Light** theme with no regression; **Plex Classic** = pixel-
  equivalent to today's gold.
- P.R.O.B.E./Playwright as the media-hub identity: no console 404s (theme-tokens.css, switcher.js, font).

## 11. Deploy

Image-baked: after merge to clean main, `scripts/deploy_with_sha.sh standalone/media_hub mediahub_app`
→ `scripts/deploy_drift_check.py` (running image reports main HEAD) → browser-verify all 5 themes +
persistence live. Never deploy the prod container from a feature branch (deploy-provenance rule).

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| 135 KB CSS refactor is large/risky | Phase it (Slices A–D), one component group at a time, screenshot before/after; back-compat aliases mean partial migration never breaks |
| Theme flash (FOUC) | Synchronous no-flash `<head>` script before CSS |
| `color-mix()` used for chips | Widely supported (2023+); provide precomputed fallbacks for the few chip tints if needed |
| LCARS uppercase/radius bleeding into unintended elements | `--mh-display-tt` applied only to labels/headings/nav, never body copy; radius via `--mh-radius` on cards only |
| Un-migrated literals during rollout | Alias tokens keep active theme's accent; long-tail sweep in Slice D |

## 13. Execution & ownership

The token layer + switcher (small, new files) and the Settings picker are straightforward. The **135 KB
`media-hub.css` migration is complex precision work on a critical file** → executed **hands-on by Claude**,
phased, verified live per slice. **Not** delegated to a 7B fleet agent (M.U.S.E.), which would mangle a
file this size; M.U.S.E./Claude-Design already served the visual-concept step (the mock).

## 14. Open decisions (chosen defaults — adjustable at spec review)

1. **Neutral default look:** cool near-black `#0d0f13` + restrained azure accent (as mocked). *Adjustable.*
2. **Theme set:** all 5 kept, incl. Plex Classic (owner selected all). *Adjustable — could drop Plex.*
3. **LCARS font:** self-host Antonio (matches platform). *Adjustable — could keep system-stack fallback.*

## 15. Out of scope / follow-ups

- Server-side per-account theme sync (v1 = localStorage).
- Theming marketing/login pages.
- Per-theme poster-card shape variants.
