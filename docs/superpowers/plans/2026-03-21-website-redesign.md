# Website Redesign — Cyberpunk Aurora Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign www.kytranempowerment.com with Cyberpunk Aurora visual direction — GSAP animations, glassmorphism, live API data, classic org chart, full SEO/AIO — across index.html, directory.html, and competitors.html.

**Architecture:** Static HTML pages on GitHub Pages (`/mnt/archie_brain/repos/website/kytranempowerment-site/`) calling the ARCHIE platform API at `https://archie.kytranempowerment.com` for live data. All CSS/JS inlined per file (self-contained). GSAP + Lenis loaded from CDN.

**Tech Stack:** HTML5, CSS3 (custom properties, backdrop-filter, @keyframes), JavaScript (vanilla), GSAP 3 + ScrollTrigger (CDN), Lenis smooth scroll (CDN), JSON-LD structured data.

**Spec:** `docs/superpowers/specs/2026-03-21-website-redesign-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `index.html` | Full rewrite | Homepage — 12 sections, all effects, SEO |
| `directory.html` | Full rewrite | Org chart (tree) + team grid + profiles |
| `competitors.html` | Restyle | Aurora theme over existing content |
| `services.html` | Nav/footer sync | Match new nav/footer pattern |
| `platform.html` | Nav/footer sync | Match new nav/footer pattern |
| `about.html`, `vision.html`, `links.html` | Nav sync | Legacy pages, add new links |
| `books.html`, `membership.html`, `merch_store.html` | Nav sync | Legacy pages with mobile menu |

All files live in: `/mnt/archie_brain/repos/website/kytranempowerment-site/`

---

## Task 1: DB — Update Vigil Org Hierarchy (Decision #250)

**Files:**
- Create: `database/migrations/180_vigil_org_hierarchy.sql`
- Modify: DB `agents.reports_to_agent_id` for 13 agents

- [ ] **Step 1: Write migration SQL**

```sql
-- Migration: 180_vigil_org_hierarchy.sql
-- Decision #250: Vigil manages Security, Compliance, Privacy, DevOps, IT
BEGIN;

-- Get Vigil's agent ID
-- Vigil's name in DB is 'Vigil' or display_name contains 'Vigil'
-- Set reports_to_agent_id for all 13 agents to Vigil's ID

-- Security & Compliance
UPDATE agents SET reports_to_agent_id = (SELECT id FROM agents WHERE name = 'Vigil' LIMIT 1)
WHERE name IN ('Volkov', 'DataMind', 'Cipher', 'Thorn', 'Bastion', 'Ironclad', 'Sentinel-2', 'Mandate');

-- Privacy & Risk
UPDATE agents SET reports_to_agent_id = (SELECT id FROM agents WHERE name = 'Vigil' LIMIT 1)
WHERE name IN ('Vault', 'Shield');

-- DevOps & IT
UPDATE agents SET reports_to_agent_id = (SELECT id FROM agents WHERE name = 'Vigil' LIMIT 1)
WHERE name IN ('Pipeline', 'Forge', 'Helpdesk');

COMMIT;
```

Note: Verify exact agent `name` values from DB before running. Use `SELECT id, name, display_name FROM agents WHERE name IN (...)` to confirm.

- [ ] **Step 2: Verify agent names in DB**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT id, name, display_name FROM agents WHERE id IN (36, 8, 18, 34, 108, 132, 109, 87, 120, 42, 98, 21, 100)"`

- [ ] **Step 3: Run migration**

Run: `docker exec archie_database psql -U archie -d archie -f /path/to/180_vigil_org_hierarchy.sql`

- [ ] **Step 4: Verify hierarchy**

Run: `docker exec archie_database psql -U archie -d archie -c "SELECT a.display_name, a.title, m.display_name as reports_to FROM agents a LEFT JOIN agents m ON a.reports_to_agent_id = m.id WHERE m.name = 'Vigil' ORDER BY a.department"`

Expected: 13 rows, all reporting to Vigil.

- [ ] **Step 5: Commit migration**

```bash
cd /mnt/archie_brain
git add database/migrations/180_vigil_org_hierarchy.sql
git commit -m "feat(db): Vigil org hierarchy — 13 agents under Ethics & Governance (Decision #250)"
```

---

## Task 2: Homepage — Foundation (Nav + Aurora BG + Footer + SEO)

**Files:**
- Modify: `index.html` (full rewrite — start fresh)

This task creates the page skeleton with the design system, nav, footer, aurora background, and all SEO meta/JSON-LD. Subsequent tasks add sections.

- [ ] **Step 1: Create page skeleton with design system**

Write `index.html` with:
- `<!DOCTYPE html>` + `<html lang="en">`
- `<head>`: charset, viewport, title, meta description, canonical URL
- Open Graph tags: og:title, og:description, og:image, og:url, og:type, og:site_name
- Twitter Card: twitter:card, twitter:title, twitter:description, twitter:image
- Google Fonts: Outfit + Inter
- CDN: GSAP 3 + ScrollTrigger + Lenis (defer)
- CSS custom properties (all colors, spacing, fonts from spec)
- Aurora background (3 blobs with CSS @keyframes `auroraFloat`)
- Film grain SVG overlay
- `prefers-reduced-motion` media query (disable all animations)
- Skip-to-content link
- Frosted glass `<nav>` (fixed, backdrop-filter) with all links: Home, Services, Platform, Our Team, Competitors, About, Contact, Get Started CTA
- Mobile hamburger menu (768px breakpoint)
- `<main id="main-content">` wrapper
- Empty `<section>` placeholders for all 12 sections (IDs: hero, social-proof, services, platform, live-stats, team, competitors, mission, testimonials, faq, cta)
- `<footer>`: nav links, social links, contact, newsletter input, copyright
- Organization JSON-LD schema
- WebSite JSON-LD schema
- Lenis + GSAP initialization script

- [ ] **Step 2: Verify page loads in browser**

Open `index.html` locally or push to GitHub Pages. Check:
- Aurora blobs animate
- Nav is frosted glass, sticky
- Footer renders
- No console errors
- Lighthouse: check SEO score (should be 90+)

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/repos/website/kytranempowerment-site
git add index.html
git commit -m "feat: homepage foundation — nav, aurora bg, footer, SEO meta + JSON-LD"
```

---

## Task 3: Homepage — Hero Section

**Files:**
- Modify: `index.html` (fill hero section)

- [ ] **Step 1: Build hero section HTML + CSS + JS**

Inside the `#hero` section, add:
- Status badge: `<div class="hero-badge">` with green pulse dot + "Platform Online — X Agents Active"
- `<h1>` with typewriter text: "Build the Future with" + `<span class="gradient-text">AI-Powered Intelligence</span>` + blinking cursor
- Subtitle `<p>`
- Dual CTA buttons (`.btn-primary` gradient, `.btn-secondary` ghost)
- 4 glassmorphism stat cards (Agents 107, Online Now live, Stations 10, Fleet Nodes 2)
- Scroll indicator arrow

CSS additions:
- `.hero` (min-height 100vh, flex center)
- `.hero-badge` (pill shape, purple bg, pulse dot)
- `.gradient-text` (animated gradient background-clip)
- `.btn-primary` / `.btn-secondary` with hover effects
- `.hero-stat` cards (glassmorphism)
- `.cursor` (blinking CSS)
- `.scroll-hint` (bounce animation)
- Typewriter JS function
- Counter animation JS (counts 0 → value on viewport entry using ScrollTrigger)

JS additions:
- `typeWriter()` function for h1 text reveal
- Fetch `/api/directory/live-status` → update online count + badge
- GSAP ScrollTrigger on stat cards (stagger fade-in)
- Magnetic button effect on CTAs

- [ ] **Step 2: Test hero section**

Verify in browser:
- Typewriter animates on load
- Gradient text shifts colors
- Stat cards visible with glassmorphism
- Online count fetches from API (or shows fallback)
- Scroll arrow bounces
- Buttons have magnetic hover effect
- Reduced-motion: all animations disabled

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: hero section — typewriter, aurora, live stats, magnetic CTAs"
```

---

## Task 4: Homepage — Sections 2-5 (Social Proof, Services, Platform Demo, Live Stats)

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Section 2 — Social Proof Bar**

- Scrolling marquee of tech logos (SVG inline or text with icons)
- Logos: Ollama, ComfyUI, PostgreSQL, Flask, Headscale, Docker, Python
- CSS infinite scroll animation (duplicate logo strip for seamless loop)
- Grayscale → color on hover
- GSAP fade-in on scroll

- [ ] **Step 2: Section 3 — Services Cards**

- 4 glassmorphism cards in responsive grid (auto-fit, minmax 280px)
- Cards: AI Consulting, SaaS Platform, Fleet Orchestration, Creative Studio
- Each: emoji icon, h3 title, paragraph description
- Hover: translateY(-4px) + border-color glow + box-shadow
- GSAP stagger scroll-in (0.15s delay)

- [ ] **Step 3: Section 4 — Platform Showcase**

- Tabbed interface with 4 tabs: Bridge Command, Agent Roster, Starship Fleet, Dev HQ
- Tab buttons styled as glassmorphism pills
- Content area with mockup screenshots (placeholder divs styled as screenshots)
- Tab switch: crossfade animation (opacity transition)
- Link to platform login

- [ ] **Step 4: Section 5 — Live Stats Counter Dashboard**

- 4-6 large stat cards in grid
- Stats: Total Agents (107), Online Now (live), Knowledge Entries (5000+), Fleet Nodes (2), Tasks Completed (count), Departments (16)
- GSAP ScrollTrigger counter animation: 0 → target value on viewport entry
- Green live-dot on real-time values
- Fetch from `/api/directory/live-status` for live data
- Glassmorphism card treatment

- [ ] **Step 5: Test all 4 sections**

Verify:
- Logo marquee scrolls infinitely
- Service cards stagger in on scroll
- Platform tabs switch with animation
- Counter numbers animate up when scrolled into view
- Live data populates from API

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat: sections 2-5 — social proof, services, platform demo, live counters"
```

---

## Task 5: Homepage — Sections 6-8 (Team Org Chart, Competitors Teaser, Mission)

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Section 6 — Mini Org Chart + Featured Team**

- Compact 2-level org chart: CEO → ARCHIE (pyramid down, 8 station leads) + Vigil (right-branch, 3 sub-teams)
- Classic tree with clear connecting lines (CSS borders/pseudo-elements)
- Click to expand/collapse (JS toggle)
- Node cards: avatar circle (initials + dept color), name, title, online dot
- 3-4 featured agent cards below with portraits (img src prefixed with API_BASE)
- "View Full Team →" link to `/directory.html`
- Fetch from `/api/directory/org-chart` for hierarchy data
- GSAP scroll-in animation

- [ ] **Step 2: Section 7 — Competitor Teaser**

- Headline: "It takes 7+ tools to match what ARCHIE does in one"
- Mini matrix: 6 rows (Station dispatch, 107 agents, Fleet orchestration, Ethics AI, Image gen, Self-hosted)
- Columns: ARCHIE (green checks) vs "Others" (red X)
- "See Full Comparison →" link to `/competitors.html`
- GSAP fade-in

- [ ] **Step 3: Section 8 — Mission**

- Background: warm gradient (gold/amber shift from cyan theme)
- Headline: "Profits Support Men's Mental Health"
- Authentic copy about Kytran Empowerment's mission
- GSAP parallax on background
- Distinct visual break from tech sections

- [ ] **Step 4: Test sections 6-8**

Verify:
- Org chart renders with correct hierarchy
- Expand/collapse works
- Competitor matrix aligns properly
- Mission section has warm color shift
- All sections animate on scroll

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat: sections 6-8 — org chart, competitor teaser, mission"
```

---

## Task 6: Homepage — Sections 9-12 (Testimonials, FAQ, CTA, Footer Polish)

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Section 9 — Testimonials**

- 3 rotating glassmorphism cards with placeholder quotes
- Auto-rotate (8s interval) with navigation dots
- Each card: quote text, attribution name + role
- GSAP fade transition between cards

- [ ] **Step 2: Section 10 — FAQ Accordion**

- 6-8 FAQ items with expand/collapse
- Questions from spec: "What is ARCHIE?", "How does AI orchestration work?", etc.
- Smooth height animation on toggle
- Only one open at a time
- JSON-LD FAQPage schema in `<script type="application/ld+json">`
- Keyboard accessible (Enter to toggle, Tab to navigate)

- [ ] **Step 3: Section 11 — Final CTA**

- Full-width aurora gradient background
- Bold headline: "Ready to Command Your AI Fleet?"
- Subtitle text
- Dual buttons: "Get Started" (primary) + "Book a Demo" (secondary)
- GSAP parallax on background blobs

- [ ] **Step 4: Polish footer**

- Ensure footer matches new design system
- Verify all nav links work
- Newsletter input styled with glassmorphism
- Organization JSON-LD already added in Task 2

- [ ] **Step 5: Full page verification**

Verify end-to-end:
- All 12 sections render correctly
- Scroll animations fire at correct points
- Live data populates
- Mobile responsive (test 375px, 768px, 1024px, 1440px)
- Lighthouse: Performance 90+, SEO 90+, Accessibility 90+
- `prefers-reduced-motion` disables animations
- Keyboard navigation works throughout

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat: sections 9-12 — testimonials, FAQ + JSON-LD, CTA, footer polish"
```

---

## Task 7: Directory Page — Full Org Chart + Team Grid

**Files:**
- Modify: `directory.html` (full rewrite)

- [ ] **Step 1: Build directory page with Aurora design system**

Rewrite `directory.html` with:
- Same `<head>` pattern as index.html (meta, OG, fonts, GSAP, Lenis)
- Aurora background + grain overlay
- Frosted glass nav (same as homepage)
- Hero: "Our Team" + stats (total members, departments, online)
- og:title = "Our Team — Kytran Empowerment"

- [ ] **Step 2: Build full expandable org chart**

- Fetch hierarchy from `/api/directory/org-chart`
- Render classic tree dynamically from API data:
  - CEO at top
  - ARCHIE pyramid downward (8 station leads, each expandable)
  - Vigil right-branch (3 sub-teams: Security, Privacy, DevOps)
- Clear connecting lines (horizontal bars spanning siblings, vertical drops to children)
- Click to expand/collapse any node
- Green/gray status dots from live-status API
- Avatar circles with initials + department color
- Keyboard accessible (aria-expanded, role="tree", role="treeitem")
- Portrait images (prefixed with API_BASE) where available

- [ ] **Step 3: Build department card grid**

- Below org chart, render department cards (preserve current grid functionality)
- Glassmorphism card treatment
- Search input + department filter dropdown
- Cards show: name, title, portrait, live status dot
- GSAP staggered scroll-in

- [ ] **Step 4: Build profile slide-out panel**

- Click card → slide-out panel from right
- Fetch from `/api/directory/{id}`
- Show: portrait, name, title, pronouns, status badge, contact info, bio, skills
- Close button + overlay click to close
- No AI/Human labels (public page)
- No chat (public page)

- [ ] **Step 5: Add footer + SEO**

- Same footer pattern as homepage
- JSON-LD: Organization schema
- OG meta tags for directory page

- [ ] **Step 6: Test directory page**

Verify:
- Org chart renders from API data
- Expand/collapse works at all levels
- Vigil branch goes right, ARCHIE pyramid goes down
- Department grid loads with search/filter
- Profile panel opens/closes
- Portraits load (API_BASE prefix)
- Live status dots update
- Mobile responsive
- Keyboard navigation

- [ ] **Step 7: Commit**

```bash
git add directory.html
git commit -m "feat: directory page — full org chart tree, glassmorphism grid, Aurora theme"
```

---

## Task 8: Competitors Page — Aurora Restyle

**Files:**
- Modify: `competitors.html`

- [ ] **Step 1: Apply Aurora design system to competitors page**

- Replace current CSS with Aurora design system (same variables, fonts, colors)
- Aurora background + grain overlay
- Frosted glass nav (same pattern)
- Restyle all content sections with glassmorphism cards
- Feature matrix table: dark theme with cyan accent on ARCHIE column
- Category cards: glassmorphism treatment
- GSAP scroll-in animations on sections
- Keep all existing content and data-i18n attributes
- Same footer pattern

- [ ] **Step 2: Add SEO meta + JSON-LD**

- OG meta tags for competitors page
- Title: "ARCHIE vs The Competition — Kytran Empowerment"

- [ ] **Step 3: Test competitors page**

Verify:
- All content preserved
- Aurora theme consistent with homepage
- Feature matrix readable
- Animations work
- Mobile responsive
- data-i18n attributes intact

- [ ] **Step 4: Commit**

```bash
git add competitors.html
git commit -m "feat: competitors page — Aurora restyle, glassmorphism, GSAP animations"
```

---

## Task 9: Nav/Footer Sync Across All Pages

**Files:**
- Modify: `services.html`, `platform.html`, `about.html`, `vision.html`, `links.html`, `books.html`, `membership.html`, `merch_store.html`

- [ ] **Step 1: Update modern pages (services, platform)**

Replace nav and footer HTML in `services.html` and `platform.html` with the exact nav/footer from the new `index.html`. Ensure all links match.

- [ ] **Step 2: Update legacy pages**

Add "Our Team" and "Competitors" links to nav in: `about.html`, `vision.html`, `links.html`, `books.html`, `membership.html`, `merch_store.html`. For pages with mobile menu overlays, update those too.

- [ ] **Step 3: Verify all cross-links work**

Click through every nav link on every page. Verify no broken links, no stale platform URLs.

- [ ] **Step 4: Commit**

```bash
git add services.html platform.html about.html vision.html links.html books.html membership.html merch_store.html
git commit -m "feat: sync nav/footer across all pages with new design"
```

---

## Task 10: Final Integration + Push

**Files:**
- All modified files

- [ ] **Step 1: Cross-page consistency check**

Open each page and verify:
- Nav renders identically on all modern pages
- Footer renders identically on all modern pages
- Aurora background consistent on index, directory, competitors
- No console errors on any page

- [ ] **Step 2: Mobile testing**

Test at 375px, 768px, 1024px, 1440px:
- Hamburger menu works
- Org chart scrolls horizontally on mobile
- Cards stack to single column
- All text readable
- No horizontal overflow

- [ ] **Step 3: Accessibility check**

- Tab through entire homepage with keyboard
- Verify focus states visible on all interactive elements
- Org chart: Enter to expand, Escape to collapse
- Check `prefers-reduced-motion` (all animations stop)
- Screen reader: verify aria-labels, heading hierarchy

- [ ] **Step 4: Lighthouse audit**

Run Lighthouse on index.html:
- Performance: target 90+
- SEO: target 95+
- Accessibility: target 90+
- Best Practices: target 90+

Fix any issues found.

- [ ] **Step 5: Push to GitHub Pages**

```bash
cd /mnt/archie_brain/repos/website/kytranempowerment-site
git push origin main
```

- [ ] **Step 6: Verify live site**

Check:
- https://www.kytranempowerment.com (homepage loads, animations work)
- https://www.kytranempowerment.com/directory.html (org chart + grid)
- https://www.kytranempowerment.com/competitors.html (Aurora theme)
- Live API data populates (online count, team members)

- [ ] **Step 7: Update Dev HQ**

```
mcp complete_task #1157 (www.kytranempowerment.com professional polish)
mcp update_project_understanding (project #166)
```

---

## Execution Order

```
Task 1 (DB migration) ← no dependencies, do first
Task 2 (homepage foundation) ← sets design system for all pages
Task 3 (hero) ← depends on Task 2
Task 4 (sections 2-5) ← depends on Task 2
Task 5 (sections 6-8) ← depends on Task 2, uses org chart from Task 1
Task 6 (sections 9-12) ← depends on Task 2
Task 7 (directory) ← depends on Task 1 (hierarchy) + Task 2 (design system)
Task 8 (competitors) ← depends on Task 2 (design system)
Task 9 (nav sync) ← depends on Task 2 (final nav/footer)
Task 10 (integration) ← depends on all above
```

Tasks 3, 4, 5, 6 can be parallelized (independent sections of same page).
Tasks 7, 8 can be parallelized (independent pages).
