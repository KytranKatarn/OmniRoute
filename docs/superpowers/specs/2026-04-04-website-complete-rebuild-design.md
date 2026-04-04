# Website Complete Rebuild — Design Spec

**Date:** 2026-04-04
**Project:** #220 — Business Launch Readiness
**Status:** Approved via brainstorm session

---

## Goal

Merge the original site (22 pages, jQuery, 368 i18n strings, full competitor data) and the new site (22 pages, GSAP/Barba, modern design) into one definitive 28-page website that showcases every product, service, feature, and differentiator Kytran Empowerment offers. Fix all responsive bugs, restore the logo, rebuild the translation system, and add market-comparison pricing.

## Approach

**Option C — Fresh Build From Both Sources.** Use the new site's CSS/JS architecture (GSAP, Barba, Lenis) but treat both sites as content sources. Page by page, take the best version — sometimes old, sometimes new, sometimes enhanced beyond either.

---

## Site Structure (28 pages)

### Core Pages (8)
| Page | Purpose |
|------|---------|
| `index.html` | Homepage — hero, mission, testimonials, FAQ, JSON-LD, CTAs |
| `about.html` | Our Story — vision, values, team, company history |
| `contact.html` | Get in Touch — form, phone (1-877-463-3352), email |
| `directory.html` | Our Team — Staff directory + AI Directors showcase |
| `vision.html` | Our Vision — retreat center, four pillars, long-term goals |
| `links.html` | Programs & Resources — external links, government programs |
| `tips.html` | Tips & Tricks — business guides, quick wins |
| `blocked.html` | Access Denied — security block page |

### Products & Services (8)
| Page | Purpose |
|------|---------|
| `services.html` | All Services — every product listed with pricing tiers |
| `platform.html` | Meet A.R.C.H.I.E. — 16 departments, AI Directors, architecture, capabilities |
| `competitors.html` | Why A.R.C.H.I.E. — ENHANCED: 35+ competitors, feature matrix, trend scan, interactive cost calculator, transparency section, KSM vs Vanta/Drata |
| `membership.html` | Choose Your Plan — 6 tiers with side-by-side market price comparison cards |
| `compliance.html` | Trust Center — live compliance scores, SOC 2, badges |
| `compliance-services.html` | Compliance Scanning — enterprise plans, KSM vs Vanta ($15K) vs Drata ($10K) |
| `ai-directors.html` | **NEW** — Meet the 16 AI Directors, what they manage, C.R.E.E.D. standards |
| `archie-code.html` | **NEW** — ARCHIE Code CLI product page, features, roadmap |

### Watch Products (4 — NEW dedicated pages)
| Page | Purpose |
|------|---------|
| `market-watch.html` | **NEW** — Market Watch features, pricing, link to market.kytranempowerment.com |
| `civic-watch.html` | **NEW** — Civic Watch features, pricing, link to civic.kytranempowerment.com |
| `legal-watch.html` | **NEW** — Legal Watch features, pricing, link to legal.kytranempowerment.com |
| `gov-watch.html` | **NEW** — Gov Watch features, pricing, link to gov.kytranempowerment.com |

### Ethics & Community (3)
| Page | Purpose |
|------|---------|
| `creed.html` | C.R.E.E.D. Institute — ethics, 4 research pillars, governance |
| `books.html` | Our Books — publications, educational resources |
| `submit-story.html` | Submit Your Story — community submissions |

### E-Commerce (5)
| Page | Purpose |
|------|---------|
| `store.html` | Merchandise — full catalog with restored 33+ product images |
| `product-detail.html` | Product detail view |
| `cart.html` | Shopping cart |
| `checkout.html` | Payment flow |
| `order-success.html` | Order confirmation |

---

## Navigation — Hybrid Dropdown + Mobile Accordion

### Desktop: Mega Menu Dropdowns
```
[Logo] Products ▾  Services ▾  Trust ▾  Company ▾  Store  Contact  [Get Started] [🌐 Lang]
```

**Products dropdown:**
- Platform (A.R.C.H.I.E.)
- AI Directors
- ARCHIE Code CLI
- Market Watch
- Civic Watch
- Legal Watch
- Gov Watch
- Business Suite

**Services dropdown:**
- All Services
- Compliance Scanning
- Membership / Pricing

**Trust dropdown:**
- Trust Center
- Why A.R.C.H.I.E. (Competitors)
- C.R.E.E.D.

**Company dropdown:**
- About
- Vision
- Directory
- Books
- Tips & Tricks

### Mobile: Accordion Sections
- Hamburger opens a bounded panel (NOT fullscreen)
- Each group (Products, Services, Trust, Company) is a collapsible accordion
- Store and Contact are direct links
- "Get Started" CTA button at bottom
- Language switcher accessible
- Max height: 80vh with scroll, not fullscreen takeover

### Breakpoints
- Desktop: 1024px+ (full mega menu)
- Tablet: 768px–1023px (hamburger with accordion, bounded to ~60% screen width)
- Mobile: <768px (hamburger with accordion, bounded to ~85% screen width, max-height 80vh)
- Small mobile: <480px (full-width accordion, max-height 80vh with scroll)

---

## Branding

### Logo
- Restore `logo.png` and `logo-sm.png` from old site (`/repos/website/kytranempowerment-site/`)
- Logo in nav header on all pages
- Favicon: keep current `favicon.svg`

### Agent Terminology
- **AI Directors** — The 16 acronym agents (A.R.C.H.I.E., V.I.G.I.L., F.O.R.G.E., M.U.S.E., S.I.G.N.A.L., C.O.D.E.X., D.A.R.W.I.N., B.A.S.E., C.A.R.G.O., L.E.D.G.E.R., R.E.S.O.L.V.E., K.I.N., V.I.T.A.L., G.A.V.E.L., A.C.C.O.R.D., S.P.E.C.T.R.A.) — showcased as unique AI leaders
- **Staff** — The 107 human-like agents — presented as "Kytran Staff"
- AI Directors are featured prominently; Staff are the supporting team

### Contact Info
- Phone: 1-877-463-3352 (restore to header/footer)
- "Get Started" CTA in nav linking to membership.html

---

## Subscription Tiers

### 6 Tiers (managed by Account Center module)
| Tier | Target | Access | Pricing Strategy |
|------|--------|--------|-----------------|
| **Free / Explorer** | Curious visitors | Limited demo, see the platform | $0 |
| **Starter** | Small business / solo | Core modules (CRM, Invoicing, Store, Content) | Undercut market ~60% |
| **Professional** | Growing business | All platform modules + 1-2 Watch products | Undercut market ~65% |
| **Enterprise** | Larger orgs | Everything + fleet compute + custom AI directors | Undercut market ~70% |
| **VIP** | Premium partners | Full unrestricted access | By invitation |
| **Kytran Staff** | Internal team | Full unrestricted access | Internal only |

### Account Center Integration
- Account Center module manages subscription-based access
- Kytran Staff and VIP tiers bypass all restrictions
- Other tiers see/access modules based on their plan
- Upgrade prompts on locked features

### Pricing Display
- **membership.html** — Side-by-side price cards with crossed-out market average above Kytran price, savings percentage shown (e.g., "Market avg: $2,500/mo → Kytran: $799/mo — Save 68%")
- **competitors.html** — Interactive cost calculator: visitor checks features they need, we show "Tool A ($X) + Tool B ($Y) + Tool C ($Z) = $TOTAL vs. Kytran: $price" with real competitor pricing
- Shared pricing data source (JSON or JS module) so both pages stay in sync
- Final dollar amounts TBD — based on competitor research from the 35+ companies already analyzed

---

## Competitors Page — Full Restoration + Enhancement

### Sections to Restore (from old 1,589-line page)
1. **Hero stats banner** — "35+ analyzed, 30 unique features, 6 categories"
2. **Full feature matrix** — 30 rows across 3 groups (16 ARCHIE-exclusive, 7 shared, 6 where others lead) with 8 competitor columns
3. **Sensor Scan: What's Trending** — 4 trend cards (OpenClaw, PicoClaw, Claw Empire, NemoClaw) with visual comparison bars and verdicts
4. **Category Comparison** — 6 cards covering Orchestration Frameworks, Workflow Builders, Autonomous Coding Agents, Enterprise Platforms, Self-Hosted & Open Source, Self-Improving & Accountable
5. **How Many Tools to Match A.R.C.H.I.E.** — 9-tool stack comparison with "still missing" callout
6. **Where We're Still Building** — Transparency section with "Who has it" attribution
7. **KSM vs Vanta/Drata** — 4 differentiator cards + 14-row comparison matrix with pricing

### New Enhancement
8. **Interactive Cost Calculator** — Checkbox feature selector showing competitor costs stacked vs. single Kytran price

---

## Translation System — Hybrid (Static + API)

### Architecture
- Ship a static JS bundle with all 8 languages pre-translated (instant load, offline-capable)
- Languages: English, French (Québécois), Spanish, Portuguese, German, Chinese, Arabic (RTL), Hebrew (RTL)
- On page load: apply static translations immediately
- Then fetch from `api.kytranempowerment.com/api/public/translate` for updates/corrections
- API results cached in localStorage (24h TTL)
- If API unavailable, static bundle serves as full fallback

### Implementation
- `data-i18n` attributes on all translatable elements (matching ARCHIE platform pattern)
- Language switcher in nav (globe icon + dropdown)
- RTL support for Arabic and Hebrew (dir attribute + CSS overrides)
- Translation keys follow `{page}.{section}.{element}` naming convention

### Coverage Target
- All 28 pages fully tagged with `data-i18n` attributes
- Minimum 500+ translation keys across the site
- Wordsmith agent (ARCHIE platform) manages translation quality

---

## Responsive Fixes

### Hamburger Menu (Current Bug)
- **Problem:** Opens too big on tablet, fullscreen on mobile
- **Root cause:** `backdrop-filter` on `.nav` creates containing block trapping `position: fixed` children
- **Fix:** Accordion-based mobile menu with bounded max-height (80vh), scroll overflow, independent section expansion

### Centering/Alignment
- Audit all pages at 480px, 768px, 1024px breakpoints
- Fix shifted/off-center boxes and content
- Ensure all grid layouts use proper responsive breakpoints
- Test all 28 pages at all 4 breakpoints before deploy

### Breakpoint Testing Matrix
| Breakpoint | Width | Test Focus |
|-----------|-------|------------|
| Small mobile | <480px | Single column, hamburger, readable text |
| Mobile | 480–767px | Content width, image scaling, touch targets |
| Tablet | 768–1023px | 2-column layouts, nav transition, card grids |
| Desktop | 1024px+ | Full mega menu, multi-column, hero sections |

---

## Removed

- **StockBot** — All references removed from the site
- **ui-ux-pro-max** — Not used, not referenced

---

## Technical Stack (Unchanged)
- GSAP + ScrollTrigger (animations)
- Barba.js (page transitions)
- Lenis (smooth scroll)
- Splitting.js (text effects)
- No jQuery, no framework dependencies
- Static HTML deployed to Hostinger via tar.gz + API

## Deploy
- Build in `/mnt/archie_brain/website/kytranempowerment.com/`
- Deploy: tar.gz from site dir → `mcp__hostinger-api__hosting_deployStaticWebsite`
- Must run tar from `/mnt/archie_brain/website/kytranempowerment.com/` (not project root)
- Cache bust: `?v=YYYYMMDD` on all CSS/JS refs

---

## Success Criteria

1. All 28 pages live and linked from navigation
2. Logo visible on every page
3. Competitors page restored with all 35+ competitors + new interactive calculator
4. Pricing visible on membership + services pages with market comparison
5. 8-language translation working on all pages
6. Hamburger menu properly bounded on tablet/mobile
7. All content centered and aligned at all 4 breakpoints
8. Store flow working end-to-end (store → product → cart → checkout → success)
9. All internal links working (no orphaned pages)
10. Phone number and "Get Started" CTA visible
11. AI Directors page showcasing all 16 with C.R.E.E.D. context
12. Watch product pages linking to their live apps
13. ARCHIE Code CLI page ready for feature expansion
