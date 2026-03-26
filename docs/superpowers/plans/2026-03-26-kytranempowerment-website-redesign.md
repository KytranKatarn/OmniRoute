# kytranempowerment.com Website Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a showstopper marketing website for Kytran Empowerment with LCARS-inspired sci-fi aesthetic, advanced visual effects (GSAP, Three.js, Lenis), 10 pages, live AI directory integration, 8-language translation, and compliance trust center — all deployed to Hostinger CDN.

**Architecture:** Multi-page static site with Barba.js page transitions. Shared visual effects library (`effects.js`) provides aurora, cursor, particles, scroll animations. JavaScript `fetch()` calls to `api.kytranempowerment.com` for dynamic data (directory, translation, badges) with graceful fallbacks. Build tool: none (vanilla HTML/CSS/JS for simplicity and Hostinger compatibility).

**Tech Stack:** HTML5, CSS3 (custom properties, `backdrop-filter`, `clip-path`), vanilla JS + GSAP 3.12 + ScrollTrigger + Lenis + splitting.js + Barba.js + Three.js/OGL (hero only), deployed as static files to Hostinger.

**Depends on:** Plan A (Foundation + Public API) must be complete first.

**Spec:** `docs/superpowers/specs/2026-03-26-hostinger-migration-website-redesign-design.md` sections 4.1-4.7

**Visual Research:** `research/modern-web-effects-2025-2026.md`

**Security Note:** All `innerHTML` usage renders data from our own trusted API endpoints, not user input. However, when implementing, use `textContent` for plain text fields and only use `innerHTML` for structured card templates with escaped data. Consider adding DOMPurify if the directory data ever includes user-editable fields.

---

## File Structure

```
website/kytranempowerment.com/
  index.html                    -- Home/Hero page
  services.html                 -- Services showcase
  platform.html                 -- A.R.C.H.I.E. platform overview
  directory.html                -- Agent directory (API-connected)
  compliance.html               -- Trust center + compliance badges
  competitors.html              -- Comparison page
  about.html                    -- Vision & story
  creed.html                    -- C.R.E.E.D. overview + link
  membership.html               -- Pricing tiers
  contact.html                  -- Contact form
  assets/
    fonts/                      -- Antonio, Orbitron, IBM Plex Mono (self-hosted)
    images/                     -- Optimized images, noise texture, agent portraits
    favicon.ico
  css/
    base.css                    -- Reset, custom properties, typography, dot grid, aurora, noise
    components.css              -- Glass panels, cards, buttons, nav, footer, badges
    pages/
      home.css                  -- Hero-specific styles
      directory.css             -- Agent card grid, filters, live status
      compliance.css            -- Badge layout, gauges
    responsive.css              -- 480px / 768px / 1024px breakpoints
    reduced-motion.css          -- prefers-reduced-motion overrides
  js/
    lib/                        -- Third-party libraries (vendored)
      gsap.min.js               -- GSAP core (~28KB gzip)
      ScrollTrigger.min.js      -- ScrollTrigger plugin (~12KB gzip)
      lenis.min.js              -- Smooth scroll (~5KB gzip)
      splitting.min.js          -- Text splitting (~2KB gzip)
      barba.min.js              -- Page transitions (~7KB gzip)
      three.min.js              -- Three.js (only loaded on home page)
    effects.js                  -- Shared effects: aurora, cursor, magnetic, scramble, tilt
    nav.js                      -- Navigation: mobile menu, language switcher, active states
    directory.js                -- Directory page: API fetch, cards, filters, live polling
    translate.js                -- Translation: API calls, localStorage cache, RTL support
    compliance.js               -- Badge rendering, score gauges
    hero.js                     -- Hero page: Three.js particles, counter animations
    transitions.js              -- Barba.js page transition config
    app.js                      -- Entry point: init Lenis, Barba, global effects
  data/
    directory-fallback.json     -- Static roster snapshot for API-down fallback
    badges-fallback.json        -- Static badge data for API-down fallback
```

**Total JS budget target: < 100KB gzipped** (excluding Three.js which lazy-loads on hero only)

---

### Task 1: Project Scaffold + Base CSS

**Files:**
- Create: `website/kytranempowerment.com/css/base.css`
- Create: `website/kytranempowerment.com/index.html` (skeleton)

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/website/kytranempowerment.com/{css/pages,js/lib,assets/{fonts,images},data}
```

- [ ] **Step 2: Download vendored libraries**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com/js/lib
curl -sL https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js -o gsap.min.js
curl -sL https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/ScrollTrigger.min.js -o ScrollTrigger.min.js
curl -sL https://cdn.jsdelivr.net/npm/lenis@1.1.18/dist/lenis.min.js -o lenis.min.js
curl -sL https://cdn.jsdelivr.net/npm/splitting@1.0.6/dist/splitting.min.js -o splitting.min.js
curl -sL https://cdn.jsdelivr.net/npm/@barba/core@2.10.3/dist/barba.umd.js -o barba.min.js
```

Three.js is large — only load on home page:
```bash
curl -sL https://cdn.jsdelivr.net/npm/three@0.171.0/build/three.module.min.js -o three.min.js
```

- [ ] **Step 3: Create base.css**

Design tokens (colors, typography, spacing), CSS reset, aurora background, dot grid, noise overlay, cursor glow, gradient text utility. See spec section 4.2 for color palette:
- Base: `#0a0a1a`, Primary: `#00e5ff`, Secondary: `#8b5cf6`, Accent: `#f472b6`, Text: `#e0e0e0`
- Fonts: Antonio (nav), Orbitron (headings), IBM Plex Mono (body)

Key CSS custom properties to define:
```css
:root {
    --color-base: #0a0a1a;
    --color-primary: #00e5ff;
    --color-secondary: #8b5cf6;
    --color-accent: #f472b6;
    --color-text: #e0e0e0;
    --color-border: rgba(255,255,255,0.1);
    --font-nav: 'Antonio', sans-serif;
    --font-heading: 'Orbitron', sans-serif;
    --font-body: 'IBM Plex Mono', monospace;
    --nav-height: 80px;
    --max-width: 1200px;
}
```

Aurora effect: two fixed pseudo-elements with large blurred radial gradients, slow drift animation.
Dot grid: `radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)` at 32px spacing.

- [ ] **Step 4: Create skeleton index.html**

Full HTML structure with:
- `<html data-barba="wrapper">`
- Font preconnect + Google Fonts link
- CSS links: base.css, components.css, pages/home.css, responsive.css, reduced-motion.css
- Global background layers: `.aurora`, `.dot-grid`, `.noise-overlay`, `.cursor-glow`
- Navigation: logo, 7 page links, language switcher, hamburger menu
- `<main data-barba="container" data-barba-namespace="home">`
  - Hero section: `[data-scramble="KYTRAN EMPOWERMENT"]`, stats with `[data-count]`, CTAs
  - Services preview: card grid with `[data-stagger]`
  - Trust badge strip
  - CTA section
- Footer: brand, links, copyright
- Language overlay (8 buttons)
- Scripts: gsap, ScrollTrigger, lenis, splitting, barba, effects, nav, translate, transitions, hero, app

- [ ] **Step 5: Commit scaffold**

```bash
git add website/kytranempowerment.com/
git commit -m "feat(website): scaffold kytranempowerment.com with base CSS and index.html"
```

---

### Task 2: Components CSS

**Files:**
- Create: `website/kytranempowerment.com/css/components.css`

- [ ] **Step 1: Create components.css**

Shared UI components:
- **Nav**: Fixed, backdrop-blur, logo (Orbitron), links with underline-grow hover, CTA button, language button, mobile hamburger
- **Buttons**: `.btn--primary` (teal bg), `.btn--outline` (teal border), `.btn--lg`, hover glow effects
- **Glass panels**: `backdrop-filter: blur(20px)`, subtle border, `border-radius: 12px`
- **Card grid**: CSS Grid `auto-fill, minmax(300px, 1fr)`, card with glass bg + 3D tilt styles
- **Footer**: border-top, flex layout, brand + links + copyright
- **Language overlay**: fixed fullscreen, glass panel centered, 2-column button grid
- **Section title**: centered with bottom margin
- **Hero**: min-height 100vh, flex center, stats row, CTA row, canvas overlay

- [ ] **Step 2: Commit**

```bash
git add website/kytranempowerment.com/css/components.css
git commit -m "feat(website): components CSS — nav, footer, buttons, glass panels, cards"
```

---

### Task 3: Shared Effects JS

**Files:**
- Create: `website/kytranempowerment.com/js/effects.js`

- [ ] **Step 1: Create effects.js with all shared visual effects**

The `Effects` object provides:
- `initCursorGlow()` — mousemove positions `.cursor-glow` div, disabled on touch devices
- `initMagnetic()` — GSAP elastic on `.magnetic` elements, disabled on touch
- `initScramble()` — `[data-scramble]` elements: IntersectionObserver triggers random-char-to-final-char animation
- `initTilt()` — `[data-tilt]` and `.card` elements: perspective + rotateX/Y on mousemove
- `initScrollReveal()` — `ScrollTrigger.batch` for `[data-stagger] > *` children (opacity + y), `[data-split]` text word-by-word reveal via splitting.js + GSAP
- `initCountUp()` — `[data-count]` elements: GSAP tweens textContent to target number
- `init()` — calls all sub-inits, OR if `prefers-reduced-motion` is set, shows content statically with no animation

All effects check `(pointer: coarse)` or `(prefers-reduced-motion: reduce)` before attaching mouse handlers.

- [ ] **Step 2: Commit**

```bash
git add website/kytranempowerment.com/js/effects.js
git commit -m "feat(website): shared effects JS — cursor, magnetic, scramble, tilt, scroll reveals"
```

---

### Task 4: App Entry Point + Navigation + Transitions

**Files:**
- Create: `website/kytranempowerment.com/js/app.js`
- Create: `website/kytranempowerment.com/js/transitions.js`
- Create: `website/kytranempowerment.com/js/nav.js`

- [ ] **Step 1: Create nav.js**

`Nav` object: mobile menu toggle, active link highlighting based on `window.location.pathname`, language switcher opens/closes overlay, language button click calls `Translate.setLanguage(lang)`.

- [ ] **Step 2: Create transitions.js**

`Transitions` object: Barba.js init with `lcars-sweep` transition — leave (opacity 0, x -50) and enter (opacity 0 x 50 to 1 0). After transition: reinit Effects, Nav.highlightActive, scroll to top. Prefetch ignores `/api` paths.

- [ ] **Step 3: Create app.js**

Entry point on `DOMContentLoaded`:
1. Init Lenis smooth scroll (duration 1.2, connect to ScrollTrigger)
2. Init Nav, Effects, Transitions
3. Check `data-barba-namespace` for page-specific init (Hero on `home`, Directory on `directory`, Compliance on `compliance`)

- [ ] **Step 4: Commit**

```bash
git add website/kytranempowerment.com/js/{app,nav,transitions}.js
git commit -m "feat(website): app entry point with Lenis, Barba transitions, nav"
```

---

### Task 5: Translation Integration

**Files:**
- Create: `website/kytranempowerment.com/js/translate.js`

- [ ] **Step 1: Create translate.js**

`Translate` object:
- `API_URL`: `https://api.kytranempowerment.com/api/public/translate`
- `CACHE_TTL`: 24h
- `setLanguage(lang)`: Sets `dir="rtl"` for ar/he, restores originals if `en`, otherwise iterates `[data-i18n]` elements — checks localStorage cache first, then calls API, stores result
- `translate(text, targetLang)`: POST to API, returns translated text
- `restoreOriginals()`: Puts back `data-i18n-original` text
- `getCache(key, lang)` / `setCache(key, lang, text)`: localStorage with TTL
- `init()`: Check `localStorage` for saved language preference, apply if not English

Content elements that need translation get `data-i18n="unique-key"` attribute. On first translation, original text is saved to `data-i18n-original`.

- [ ] **Step 2: Commit**

```bash
git add website/kytranempowerment.com/js/translate.js
git commit -m "feat(website): translation integration with API fallback and localStorage cache"
```

---

### Task 6: Directory Page

**Files:**
- Create: `website/kytranempowerment.com/directory.html`
- Create: `website/kytranempowerment.com/js/directory.js`
- Create: `website/kytranempowerment.com/css/pages/directory.css`

- [ ] **Step 1: Create directory.js**

`Directory` object:
- `init()`: Fetch from API, fallback to `/data/directory-fallback.json`, render filters + agents, start live polling
- `renderAgents(agents)`: Build agent card HTML — avatar (img or initial placeholder), live status dot, acronym display (for AI Directors), full name, title, type badge, department
- `renderFilters()`: Department dropdown, type dropdown, search input — built from agent data
- `bindEvents()`: Search input, department select, type select all call `applyFilters()`
- `applyFilters()`: Filter `this.agents` by department, type, search text, re-render
- `startLivePolling()`: Every 30s fetch `/directory/live`, update status dot classes
- `showOfflineNotice()`: Yellow banner "Live status unavailable — showing cached roster"

**Agent card structure:**
- Avatar (80px circle, border, placeholder with initial if no image)
- Live status dot (positioned absolute bottom-right of avatar): green=active, blue=deployed, gray=barracked, dim=off_duty, yellow=winding_down, purple=cooldown
- For AI Directors: `.agent-card__acronym` (e.g., "A.R.C.H.I.E.") + `.agent-card__expansion` (italic below)
- For others: `.agent-card__name` (full name)
- Title, type badge (color-coded: teal for AI Director, purple for AI Staff, pink for Human), department

- [ ] **Step 2: Create directory.css**

Styles for: directory hero (title + subtitle), filters bar, agent card grid, avatar, status dots (6 shift states), acronym display, type badges, offline notice, error state.

- [ ] **Step 3: Create directory.html**

Same skeleton as index.html but:
- `data-barba-namespace="directory"`
- Title: "Directory — Kytran Empowerment"
- Content: hero section, filters container, card grid container
- Scripts include `directory.js` instead of `hero.js`
- No Three.js script tag

- [ ] **Step 4: Generate fallback JSON**

```bash
curl -s http://192.168.1.200:3000/api/public/directory > /mnt/archie_brain/website/kytranempowerment.com/data/directory-fallback.json
```

- [ ] **Step 5: Commit**

```bash
git add website/kytranempowerment.com/{directory.html,js/directory.js,css/pages/directory.css,data/directory-fallback.json}
git commit -m "feat(website): directory page with API integration, filters, live status"
```

---

### Task 7: Compliance Page

**Files:**
- Create: `website/kytranempowerment.com/compliance.html`
- Create: `website/kytranempowerment.com/js/compliance.js`
- Create: `website/kytranempowerment.com/css/pages/compliance.css`

- [ ] **Step 1: Create compliance.js**

`Compliance` object:
- `init()`: Fetch badges from API, fallback to `/data/badges-fallback.json`, render
- `renderBadges(badges)`: For each badge: grade letter (colored), framework name, score percentage, progress bar (filled to score%), rule count

- [ ] **Step 2: Create compliance.html**

Content sections:
1. Hero: "Trust Center" title
2. Compliance badges grid (auto-populated from API)
3. SOC 2 Trust Service Criteria section (static content: Security, Availability, Processing Integrity, Confidentiality, Privacy)
4. C.R.E.E.D. governance link
5. "How We Scan" section (rule packs overview)

- [ ] **Step 3: Create compliance.css**

Badge card styles: large grade letter, score bar, framework name. SOC 2 section layout.

- [ ] **Step 4: Generate badge fallback JSON**

```bash
curl -s http://192.168.1.200:3000/api/public/compliance/badges > /mnt/archie_brain/website/kytranempowerment.com/data/badges-fallback.json
```

- [ ] **Step 5: Commit**

```bash
git add website/kytranempowerment.com/{compliance.html,js/compliance.js,css/pages/compliance.css,data/badges-fallback.json}
git commit -m "feat(website): compliance trust center with live badge scores"
```

---

### Task 8: Hero Three.js Particle Scene

**Files:**
- Create: `website/kytranempowerment.com/js/hero.js`
- Create: `website/kytranempowerment.com/css/pages/home.css`

- [ ] **Step 1: Create hero.js**

`Hero` object:
- `init()`: Skip if mobile (768px) or reduced-motion. Get `#heroCanvas`. Create Three.js scene:
  - 800 particles in BufferGeometry, random positions in 20x20x20 cube
  - Colors: random teal (#00e5ff) or purple (#8b5cf6) per particle
  - PointsMaterial: size 0.05, vertexColors, transparent, sizeAttenuation
  - Camera at z=5, slow rotation, mouse-reactive position lerp
  - Resize handler for responsive canvas
- Uses `Math.min(window.devicePixelRatio, 2)` for performance

- [ ] **Step 2: Create home.css**

Hero canvas opacity, services preview section, trust strip flex layout.

- [ ] **Step 3: Commit**

```bash
git add website/kytranempowerment.com/js/hero.js website/kytranempowerment.com/css/pages/home.css
git commit -m "feat(website): hero Three.js particle scene + home page styles"
```

---

### Task 9: Remaining Content Pages

**Files:**
- Create: `website/kytranempowerment.com/services.html`
- Create: `website/kytranempowerment.com/platform.html`
- Create: `website/kytranempowerment.com/competitors.html`
- Create: `website/kytranempowerment.com/about.html`
- Create: `website/kytranempowerment.com/creed.html`
- Create: `website/kytranempowerment.com/membership.html`
- Create: `website/kytranempowerment.com/contact.html`

Each page uses the same HTML skeleton: fonts, CSS links, global bg layers, nav, `<main data-barba>`, footer, lang overlay, scripts. Differences are `data-barba-namespace`, `<title>`, and page content.

- [ ] **Step 1: services.html**

10 service cards in a grid (CRM, Website Designer, Store Builder, Invoicing, Content Studio, Social Media, Call Center, StockBot, Google Work Suite, Compliance). Each card: SVG icon area, title, description, "Learn more" link. Optional: horizontal scroll showcase section with GSAP ScrollTrigger pin.

- [ ] **Step 2: platform.html**

High-level A.R.C.H.I.E. overview. "What is A.R.C.H.I.E.?" section. Department breakdown with animated cards (16 departments). Agent count stat. AI Bridge concept explanation. **Boundary:** No model names, no infra details, no API internals.

- [ ] **Step 3: competitors.html**

Feature comparison grid. Side-by-side cards. Checkmark icons that SVG-draw-in on scroll.

- [ ] **Step 4: about.html**

Founding story. Mission statement. Values. Team overview. Parallax storytelling layout with scroll-pinned timeline.

- [ ] **Step 5: creed.html**

C.R.E.E.D. bridge page — introduces the institute, manifesto excerpt, 4 research pillars as preview cards. Gold accent color on this page via CSS override: `--color-creed-gold: #c9a44c`. CTA links to `https://creed-ai.org`.

- [ ] **Step 6: membership.html**

3 pricing cards (Free / Pro / Enterprise or similar). Glass panels with hover glow. Feature comparison table below.

- [ ] **Step 7: contact.html**

Contact form: name, email, department routing dropdown, message textarea. Company info sidebar: Kytran Empowerment Inc., Montreal, Canada. Magnetic focus effect on form fields.

- [ ] **Step 8: Commit all pages**

```bash
git add website/kytranempowerment.com/*.html
git commit -m "feat(website): all content pages — services, platform, competitors, about, creed, membership, contact"
```

---

### Task 10: Responsive CSS + Reduced Motion

**Files:**
- Create: `website/kytranempowerment.com/css/responsive.css`
- Create: `website/kytranempowerment.com/css/reduced-motion.css`

- [ ] **Step 1: Create responsive.css**

Three breakpoints:
- **1024px**: Reduce section padding, smaller card grid min
- **768px**: Hide nav links (show hamburger), stack hero stats/CTAs vertically, stack filters, clamp heading sizes
- **480px**: Further reduce spacing, single-column card grid, stack footer, single-column lang overlay

- [ ] **Step 2: Create reduced-motion.css**

`@media (prefers-reduced-motion: reduce)`: Zero-out animation durations/iterations/transitions, hide cursor-glow, disable aurora animation, force `scroll-behavior: auto`.

- [ ] **Step 3: Commit**

```bash
git add website/kytranempowerment.com/css/{responsive,reduced-motion}.css
git commit -m "feat(website): responsive breakpoints + reduced-motion accessibility"
```

---

### Task 11: Deploy to Hostinger + Verify

- [ ] **Step 1: Deploy static site to Hostinger**

Use Hostinger MCP: `mcp__hostinger-api__hosting_deployStaticWebsite()` with the contents of `website/kytranempowerment.com/`.

- [ ] **Step 2: Smoke test all pages**

Verify in browser at `https://kytranempowerment.com`:
- [ ] Home: aurora, scramble text, particle hero, stats count-up, nav works
- [ ] Services: 10 cards render, scroll reveals work
- [ ] Platform: department cards, agent count
- [ ] Directory: API data loads, filters work, live status polls
- [ ] Compliance: badges load from API, score bars render
- [ ] Competitors: comparison grid renders
- [ ] About: parallax/timeline scrolls correctly
- [ ] C.R.E.E.D.: gold accent visible, link to creed-ai.org works
- [ ] Membership: pricing cards render
- [ ] Contact: form fields work
- [ ] Mobile: hamburger nav, no Three.js, stacked layouts
- [ ] Language: switcher triggers translation, RTL works for Arabic/Hebrew
- [ ] Reduced motion: content visible, no animations

- [ ] **Step 3: Lighthouse audit**

Target: 90+ Performance, 90+ Accessibility, 90+ Best Practices, 90+ SEO

Common fixes if needed:
- Compress/resize images
- Add `alt` attributes to all images
- Add `<meta name="theme-color" content="#0a0a1a">`
- Defer non-critical JS with `defer` attribute
- Add `rel="noopener"` to external links

- [ ] **Step 4: Commit fixes, redeploy, verify**

---

## Dependency Summary

```
Task 1 (Scaffold + Base CSS) ──> Task 2 (Components) ──> Task 3 (Effects JS)
                                                     ──> Task 4 (App/Nav/Transitions)
                                                     ──> Task 5 (Translation)
Task 3 + Task 4 ──> Task 6 (Directory Page)
Task 3 + Task 4 ──> Task 7 (Compliance Page)
Task 3 + Task 4 ──> Task 8 (Hero Three.js)
Task 3 + Task 4 ──> Task 9 (Remaining Pages) -- these 4 are independent of each other
Task 1 ──> Task 10 (Responsive + Reduced Motion)
All ──> Task 11 (Deploy + Verify)
```
