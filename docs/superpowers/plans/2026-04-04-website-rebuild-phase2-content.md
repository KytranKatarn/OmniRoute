# Website Rebuild Phase 2: Content Restoration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore all content stripped during the consolidation — full competitors page (35+ companies, feature matrix, trends, calculator), pricing tiers with market comparison, complete services listing, and enhanced content across existing pages.

**Architecture:** Page-by-page content restoration using old site as source, new site CSS/JS architecture. Competitors page gets the interactive cost calculator. Membership page gets side-by-side price cards with market comparison.

**Tech Stack:** Same as Phase 1 �� vanilla JS, CSS custom properties, GSAP/Barba/Lenis

**Depends on:** Phase 1 complete (nav, logo, i18n, responsive fixes)

**Reference:** Old site at `/mnt/archie_brain/repos/website/kytranempowerment-site/`
**Reference:** Gap analysis at `/mnt/archie_brain/website/GAP_ANALYSIS_OLD_VS_NEW.md`
**Reference:** Competitor deep read at `/mnt/archie_brain/docs/superpowers/plans/2026-04-04-competitors-page-restoration-reference.md`

**Security note:** The interactive calculator uses template literals to build DOM. All data comes from local JSON files (not user input), so XSS risk is minimal. However, implementers should use `textContent` for text values and DOM creation methods where practical instead of raw string interpolation.

---

## File Structure

### Modified Files
| File | Changes |
|------|---------|
| `competitors.html` | Full rebuild: 35+ competitors, 30-feature matrix, trends, categories, cost calculator, transparency, KSM comparison |
| `membership.html` | 6 subscription tiers with market price comparison cards |
| `services.html` | Complete services listing — all standalone products + platform modules + pricing CTAs |
| `platform.html` | Enhanced: all 16 departments, AI Director names, capabilities, architecture stats |
| `index.html` | Enhanced: restore testimonials, mission statement, comprehensive feature showcase |
| `compliance-services.html` | KSM vs Vanta/Drata pricing matrix restored |
| `contact.html` | Phone number, complete contact info |

### New Files
| File | Responsibility |
|------|---------------|
| `js/calculator.js` | Interactive cost calculator for competitors page |
| `css/pages/competitors.css` | Competitors page-specific styles |
| `css/pages/membership.css` | Membership/pricing page styles |
| `data/pricing.json` | Shared pricing data (tiers + competitor prices) |
| `data/competitors.json` | Competitor feature matrix data (drives both table and calculator) |

---

## Task 1: Create Shared Pricing & Competitor Data

**Files:**
- Create: `data/pricing.json`
- Create: `data/competitors.json`

These are the single source of truth for pricing displayed on both membership.html and competitors.html.

- [ ] **Step 1: Create pricing.json**

Create `data/pricing.json` with:
- 5 visible tiers: Explorer (free), Starter ($299/mo, market avg $800), Professional ($799/mo, market avg $2,500), Enterprise ($1,499/mo, market avg $5,000), VIP (invitation)
- Each tier: id, name, price, period, market_avg, tagline, features array, cta text, highlighted boolean
- competitor_prices object: 12 entries mapping feature categories to tools and their monthly prices (Salesforce $300, Vanta $1,250, CrewAI $200, Adobe CC $80, Webflow $49, Shopify Plus $299, QuickBooks $90, Hootsuite $99, Zendesk $115, Datadog $150, Google Workspace $18/user, Drata $833)

- [ ] **Step 2: Create competitors.json**

Create `data/competitors.json` with:
- competitors array: 8 named competitors with id, name, category
- features object with 3 groups: archie_exclusive (16 features), shared (7 features), others_lead (6 features with leader attribution)
- categories array: 6 category cards with name, competitor list, archie_edge, archie_gap
- tool_stack_comparison: 9 tools needed to match ARCHIE, their prices, total ($2,482/mo), archie_price ($799/mo), still_missing text

Read the old site's competitors.html for exact feature names and competitor lists to ensure nothing is missed.

- [ ] **Step 3: Commit data files**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add data/pricing.json data/competitors.json
git commit -m "feat(website): shared pricing + competitor data (single source of truth)"
```

---

## Task 2: Rebuild Competitors Page

**Files:**
- Rewrite: `competitors.html`
- Create: `css/pages/competitors.css`
- Create: `js/calculator.js`

This is the biggest single task. The old page was 1,589 lines. We rebuild it with the new design system plus the interactive cost calculator.

- [ ] **Step 1: Create competitors.css**

Create `css/pages/competitors.css` with styles for all 8 sections. Key classes:
- `.comp-hero` — hero stats banner (35+ analyzed, 30 features, 6 categories)
- `.comp-matrix` — feature comparison table with sticky header, horizontal scroll on mobile
- `.comp-matrix__check`, `.comp-matrix__cross` — green check / red cross indicators
- `.comp-trend-card` — trending competitor cards with visual comparison bars
- `.comp-category-card` — 6 category comparison cards with edge/gap sections
- `.comp-stack` — tool stack comparison visual (9 items stacked vs 1 Kytran)
- `.comp-transparency` — "where we're still building" section with "who has it" attribution
- `.comp-ksm` — KSM vs Vanta/Drata section with differentiator cards + comparison matrix
- `.comp-calculator` — interactive cost calculator container
- `.comp-calculator__checkbox` — feature checkbox labels with tool name and price
- `.comp-calculator__result` — running total display (their cost vs Kytran, savings %)

All styles use existing CSS custom properties from `base.css`. Follow glassmorphism aesthetic with `backdrop-filter` panels.

- [ ] **Step 2: Create calculator.js**

Create `js/calculator.js` — the interactive cost calculator:
- Loads pricing data from `data/pricing.json` on init
- Renders checkbox grid: each checkbox shows feature name, competitor tool name, and monthly price
- On checkbox change: recalculate total competitor cost, determine best matching Kytran tier, compute savings %
- Update result display using DOM creation methods (createElement + textContent, not string interpolation with user data)
- Result shows: "Their cost: $X/mo" vs "Kytran: $Y/mo" with "Save Z%" badge
- Tier matching logic: total > $2,000 = Enterprise ($1,499), > $800 = Professional ($799), > $0 = Starter ($299)
- Expose as `Calculator` module with `init()` method

- [ ] **Step 3: Rebuild competitors.html**

Rebuild the full competitors page. Read the old `competitors.html` at `/mnt/archie_brain/repos/website/kytranempowerment-site/competitors.html` for exact content. The page must include ALL 8 sections:

1. **Hero stats banner** — "35+ analyzed, 30 unique features, 6 categories"
2. **Feature matrix table** — 30 rows across 3 groups (16 ARCHIE-exclusive, 7 shared, 6 others lead) with 8 competitor columns. Green checks, red crosses, tooltips.
3. **Sensor Scan: What's Trending** — 4 trend cards (OpenClaw, PicoClaw, Claw Empire, NemoClaw) with visual comparison bars and verdicts
4. **Category Comparison** — 6 cards covering all competitor categories with edge/gap analysis
5. **How Many Tools to Match A.R.C.H.I.E.** — 9-tool stack with prices, total, "still missing" callout
6. **Interactive Cost Calculator** (NEW) — checkbox feature selector with live running total
7. **Where We're Still Building** — transparency section with "who has it" attribution for A2A, Cloud Auto-Scaling, Visual Workflow, Durable Execution, 10K+ Integrations, Enterprise SSO
8. **KSM vs Vanta/Drata** — 4 differentiator cards + 14-row comparison matrix with pricing ($15K+/yr Vanta, $10K+/yr Drata vs Free KSM)

Add `data-i18n` attributes to all translatable text. Add script/link tags for calculator.js and competitors.css.

- [ ] **Step 4: Add competitors page translations to data/translations.json**

Add ~30 new keys per language covering section titles, feature group names, CTAs, calculator labels, and transparency text.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add competitors.html css/pages/competitors.css js/calculator.js data/translations.json
git commit -m "feat(website): full competitors page — 35+ companies, feature matrix, cost calculator"
```

---

## Task 3: Rebuild Membership/Pricing Page

**Files:**
- Rewrite: `membership.html`
- Create: `css/pages/membership.css`

- [ ] **Step 1: Create membership.css**

Styles for pricing cards with market comparison:
- `.pricing-cards` — flexbox/grid container, responsive (3-col desktop, 2-col tablet, 1-col mobile)
- `.pricing-card` — glass panel card with border glow
- `.pricing-card--highlighted` — featured tier with purple border and "POPULAR" badge
- `.pricing-card__market` — crossed-out market average text (gray, line-through)
- `.pricing-card__price` — Kytran price (large, cyan, bold)
- `.pricing-card__savings` — savings percentage badge (green background, white text, pill shape)
- `.pricing-card__features` — feature list with check marks
- `.pricing-card__cta` — full-width action button matching tier color

- [ ] **Step 2: Rebuild membership.html**

Structure:
1. Hero: "Choose Your Plan" + subtitle "Everything you need. One platform. No tool sprawl."
2. Pricing cards section (5 visible tiers): renders from `data/pricing.json` via JS, with static HTML fallback for SEO
3. Feature comparison table: rows showing which features are in which tier
4. FAQ section: What's included, how billing works, upgrade/downgrade, refund policy
5. CTA: "Not sure? Try Explorer for free" + "Talk to sales for Enterprise"

JS loads `data/pricing.json` and builds cards with DOM methods. Each card shows market_avg crossed out, Kytran price, savings %, feature list, CTA.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add membership.html css/pages/membership.css
git commit -m "feat(website): membership page — 5 tiers with market price comparison cards"
```

---

## Task 4: Rebuild Services Page

**Files:**
- Rewrite: `services.html`

- [ ] **Step 1: Rebuild services.html with complete product listing**

The services page must list EVERY product and module:

**Section 1: Standalone Products** (hero cards — larger, prominent)
- ARCHIE Platform → platform.html
- ARCHIE Code CLI → archie-code.html
- Kytran Business Suite → business.kytranempowerment.com
- Market Watch → market-watch.html
- Civic Watch → civic-watch.html
- Legal Watch → legal-watch.html
- Gov Watch → gov-watch.html
- Kytran System Operations → server.kytranempowerment.com

**Section 2: Platform Modules by Category** (card grid)
- SaaS Services: CRM, Social Media, Website Designer, Store Builder, Call Center, Invoicing, Content Studio, Google Work Suite
- AI Command: Starbase, Repair Bay, Consciousness
- Admin Ops: Backup Manager, Security Network, Account Center, System Ops
- Media & Creative: Media Hub, Media Studio, Game Studio
- Applications: Fitness, Therapy, DOC
- Crypto: Archie Pool

**Section 3: Pricing CTA** — "See our plans" linking to membership.html, quick tier comparison

**Section 4: C.R.E.E.D. Trust Badge** — links to compliance.html and creed.html

Each card: name, one-line description, 3-4 feature bullets, CTA link. Add `data-i18n` to all text.

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add services.html
git commit -m "feat(website): complete services page — all products + modules listed"
```

---

## Task 5: Enhance Platform Page

**Files:**
- Modify: `platform.html`

- [ ] **Step 1: Enhance platform.html**

Add/restore:
1. Hero with live stats (16 departments, 123 agents, 22K+ knowledge entries)
2. "What is A.R.C.H.I.E.?" — expanded: Autonomous Resource & Cognitive Hyperintelligence Engine
3. 16 Departments grid — each card: department name, floor (BRIDGE/OPERATIONS/ENGINEERING/CREATIVE/SERVICES), AI Director acronym + full name, one-line role description
4. Architecture section — 4-system design (Autonomy, Department HQ, AI Bridge, Starbase Command)
5. Key capabilities: self-healing pipeline, fleet compute, ethics governance, multi-model AI, 8-language support
6. "Meet the AI Directors" CTA linking to ai-directors.html
7. CTA to membership.html

Department data (from MEMORY.md):
- BRIDGE: A.R.C.H.I.E. (Executive Office)
- OPERATIONS: B.A.S.E. (Operations), C.A.R.G.O. (Logistics), L.E.D.G.E.R. (Finance)
- ENGINEERING: F.O.R.G.E. (Engineering), V.I.G.I.L. (Security), D.A.R.W.I.N. (Research)
- CREATIVE: M.U.S.E. (Creative), S.I.G.N.A.L. (Marketing), C.O.D.E.X. (Documentation)
- SERVICES: R.E.S.O.L.V.E. (Customer Success), K.I.N. (HR), V.I.T.A.L. (Medical), G.A.V.E.L. (Legal), A.C.C.O.R.D. (Diplomatic), S.P.E.C.T.R.A. (Analytics)

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add platform.html
git commit -m "feat(website): enhanced platform page — 16 departments, AI Directors, architecture"
```

---

## Task 6: Enhance Homepage + Compliance Services + Contact

**Files:**
- Modify: `index.html`
- Modify: `compliance-services.html`
- Modify: `contact.html`

- [ ] **Step 1: Enhance index.html**

Restore/add:
- Testimonials section
- Mission statement with company values
- "What We Build" section showing standalone products + platform
- Stats counter (16 departments, 123 agents, 22K+ knowledge entries, 8 languages)
- Feature highlights (self-healing, AI directors, compliance, fleet compute)
- CTA sections linking to services.html and membership.html
- All sections with `data-i18n` attributes

- [ ] **Step 2: Restore KSM comparison in compliance-services.html**

Restore from old site:
- 4 differentiator cards (Self-Hosted, Free, Real-Time, Automated)
- 14-row comparison matrix: KSM vs Vanta ($15K+/yr) vs Drata ($10K+/yr)
- Features compared: pricing, deployment, scanning frequency, remediation, compliance frameworks, etc.
- CTA to membership or contact

- [ ] **Step 3: Update contact.html**

Ensure:
- Phone: 1-877-463-3352 (clickable tel: link)
- Email: contact@kytranempowerment.com
- Contact form (name, email, subject, message)
- Business hours
- Social links
- All text with `data-i18n` attributes

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add index.html compliance-services.html contact.html
git commit -m "feat(website): enhanced homepage + KSM comparison restored + complete contact info"
```

---

## Task 7: Deploy and Test Phase 2

- [ ] **Step 1: Update all translations**

Add all new i18n keys from this phase to `data/translations.json` in all 8 languages. Focus on section titles, CTAs, feature names, pricing labels, calculator UI text.

- [ ] **Step 2: Deploy**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
tar -czf /tmp/site-phase2.tar.gz .
```

Deploy via `mcp__hostinger-api__hosting_deployStaticWebsite`.

- [ ] **Step 3: Test all rebuilt pages at all breakpoints**

Browser test at 1024px, 768px, 480px:
1. **competitors.html** — All 8 sections render, feature matrix scrollable on mobile, calculator checkboxes work, totals update, KSM comparison visible
2. **membership.html** — All 5 tiers show, market prices crossed out, savings % visible, CTAs link correctly
3. **services.html** — All products listed, links work, responsive grid
4. **platform.html** — 16 departments visible, architecture section, AI Director names correct
5. **index.html** — Full content, stats, testimonials, CTAs
6. **compliance-services.html** — KSM comparison table renders
7. **contact.html** — Phone number clickable, form renders, complete info

- [ ] **Step 4: Commit hotfixes**

```bash
git add -A
git commit -m "fix(website): phase 2 hotfixes from browser testing"
```

---

## Phase 2 Complete Checklist

- [ ] Competitors page: 35+ competitors, 30-feature matrix, 6 categories
- [ ] Competitors page: trend cards, tool stack comparison, transparency section
- [ ] Competitors page: interactive cost calculator working
- [ ] Competitors page: KSM vs Vanta/Drata comparison
- [ ] Membership page: 5 tiers with market price comparison
- [ ] Membership page: savings percentages shown
- [ ] Services page: all standalone products listed
- [ ] Services page: all platform modules by category
- [ ] Platform page: 16 departments with AI Directors
- [ ] Homepage: enhanced with full feature showcase
- [ ] Contact page: phone number + complete info
- [ ] Shared pricing data drives both membership + calculator
- [ ] All new content has data-i18n attributes
- [ ] Deployed and browser tested at all breakpoints
