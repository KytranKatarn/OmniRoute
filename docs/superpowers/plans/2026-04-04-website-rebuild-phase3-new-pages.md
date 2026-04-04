# Website Rebuild Phase 3: New Pages

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the 6 new pages: AI Directors showcase, ARCHIE Code CLI product page, and 4 Watch product landing pages.

**Architecture:** Each new page follows the existing GSAP/Barba pattern, uses the Phase 1 nav partial, includes data-i18n attributes, and has page-specific CSS where needed.

**Tech Stack:** Same as Phase 1-2

**Depends on:** Phase 1 + Phase 2 complete

---

## Task 1: AI Directors Page

**Files:**
- Create: `ai-directors.html`
- Create: `css/pages/ai-directors.css`

- [ ] **Step 1: Create ai-directors.css**

Styles for the AI Directors showcase:
- `.directors-hero` — full-width hero with C.R.E.E.D. branding
- `.directors-grid` — responsive grid (3-col desktop, 2-col tablet, 1-col mobile)
- `.director-card` — glass panel with department color accent (use department colors from Starbase: BRIDGE #00e5ff, OPERATIONS #a3e635, ENGINEERING #fbbf24, CREATIVE #f472b6, SERVICES #8b5cf6)
- `.director-card__acronym` — large acronym display with dots
- `.director-card__name` — full expansion of acronym
- `.director-card__dept` — department name
- `.director-card__floor` — floor badge
- `.director-card__desc` — role description
- `.director-card__capabilities` — key capabilities list

- [ ] **Step 2: Create ai-directors.html**

Structure:
1. **Hero:** "Meet the AI Directors" — "16 autonomous leaders managing every aspect of your business under C.R.E.E.D. ethical governance"
2. **C.R.E.E.D. badge:** Brief explanation of ethical AI governance
3. **Floor sections** — Group directors by floor:

**BRIDGE (1 director)**
- A.R.C.H.I.E. — Autonomous Resource & Cognitive Hyperintelligence Engine — Executive Office — Chief executive AI, orchestrates all departments, final decision authority

**OPERATIONS (3 directors)**
- B.A.S.E. — Operations & Infrastructure
- C.A.R.G.O. — Logistics & Supply Chain
- L.E.D.G.E.R. — Finance & Accounting

**ENGINEERING (3 directors)**
- F.O.R.G.E. — Engineering & Technology
- V.I.G.I.L. — Security & Compliance
- D.A.R.W.I.N. — Research & Development

**CREATIVE (3 directors)**
- M.U.S.E. — Creative & Design
- S.I.G.N.A.L. — Marketing & Communications
- C.O.D.E.X. — Documentation & Knowledge

**SERVICES (6 directors)**
- R.E.S.O.L.V.E. — Customer Success & Support
- K.I.N. — Human Resources & Culture
- V.I.T.A.L. — Medical & Wellness
- G.A.V.E.L. — Legal & Regulatory
- A.C.C.O.R.D. — Diplomatic & External Relations
- S.P.E.C.T.R.A. — Analytics & Intelligence

4. **How They Work Together** — Brief architecture explanation: each director manages a department of Staff agents, reports to A.R.C.H.I.E., follows C.R.E.E.D. standards
5. **CTA:** "See what they can do for you" → services.html / membership.html

Each director card shows: acronym (large), full name, department, floor badge (colored), 2-3 sentence role description, 3 key capabilities.

Add `data-i18n` attributes. Include nav partial. Add page-specific CSS link.

- [ ] **Step 3: Add ai-directors translations to data/translations.json**

Add keys for page title, section titles, floor names, and CTA text in all 8 languages.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add ai-directors.html css/pages/ai-directors.css data/translations.json
git commit -m "feat(website): AI Directors showcase — 16 directors across 5 floors"
```

---

## Task 2: ARCHIE Code CLI Page

**Files:**
- Create: `archie-code.html`
- Create: `css/pages/archie-code.css`

- [ ] **Step 1: Create archie-code.css**

Styles for CLI product page:
- `.cli-hero` — hero with terminal-style aesthetics
- `.cli-terminal` — mock terminal window showing CLI commands
- `.cli-features` — feature grid cards
- `.cli-install` — installation code block with copy button
- `.cli-roadmap` — upcoming features timeline

- [ ] **Step 2: Create archie-code.html**

Structure:
1. **Hero:** "ARCHIE Code CLI" — "Your AI-powered development companion. Built by Kytran Empowerment."
2. **Terminal demo:** Show example CLI session (styled as terminal window):
   ```
   $ archie-code init
   $ archie-code ask "How does the auth system work?"
   $ archie-code fix --file src/auth.py
   ```
3. **Features grid:**
   - Context-aware code assistance
   - Full codebase understanding
   - Multi-language support
   - Knowledge base integration
   - Git-aware workflows
   - ARCHIE platform integration
4. **Installation section:**
   ```bash
   npm install -g archie-code
   ```
5. **Roadmap:** Planned features (expandable with future updates)
6. **CTA:** "Get Started" → GitHub repo or membership

Add `data-i18n`, nav partial, page CSS link.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add archie-code.html css/pages/archie-code.css
git commit -m "feat(website): ARCHIE Code CLI product page"
```

---

## Task 3: Watch Product Pages (4 pages)

**Files:**
- Create: `market-watch.html`, `civic-watch.html`, `legal-watch.html`, `gov-watch.html`
- Create: `css/pages/watch.css` (shared styles for all 4)

- [ ] **Step 1: Create shared watch.css**

Styles for Watch product landing pages:
- `.watch-hero` — hero with product-specific accent color
- `.watch-features` — feature grid
- `.watch-demo` — screenshot/demo section
- `.watch-pricing` — pricing card with market comparison
- `.watch-cta` — prominent CTA to the live app

Color accents per product:
- Market Watch: green (#10b981)
- Civic Watch: blue (#3b82f6)
- Legal Watch: amber (#f59e0b)
- Gov Watch: red (#ef4444)

- [ ] **Step 2: Create market-watch.html**

Structure:
1. **Hero:** "Market Watch" — "Real-time market intelligence. Track trends, monitor assets, stay ahead."
2. **Features:** Stock tracking, market analysis, alerts, portfolio monitoring, trend detection
3. **Live app link:** "Try it now" → market.kytranempowerment.com
4. **Pricing:** Part of Professional+ tiers, or standalone subscription
5. **CTA:** Sign up / membership

- [ ] **Step 3: Create civic-watch.html**

Structure:
1. **Hero:** "Civic Watch" — "Monitor civic developments. Stay informed about your community."
2. **Features:** Government meetings, civic alerts, community impact tracking, public records
3. **Live app link:** → civic.kytranempowerment.com
4. **Pricing + CTA**

- [ ] **Step 4: Create legal-watch.html**

Structure:
1. **Hero:** "Legal Watch" — "Track legal developments that matter to your business."
2. **Features:** Case monitoring, regulatory updates, compliance alerts, legal research
3. **Live app link:** → legal.kytranempowerment.com
4. **Pricing + CTA**

- [ ] **Step 5: Create gov-watch.html**

Structure:
1. **Hero:** "Gov Watch" — "Government policy tracking and analysis."
2. **Features:** Policy monitoring, government spending, regulatory changes, legislative tracking
3. **Live app link:** → gov.kytranempowerment.com
4. **Pricing + CTA**

- [ ] **Step 6: Add Watch translations to data/translations.json**

Add keys for all 4 Watch pages in all 8 languages.

- [ ] **Step 7: Commit all Watch pages**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add market-watch.html civic-watch.html legal-watch.html gov-watch.html css/pages/watch.css data/translations.json
git commit -m "feat(website): 4 Watch product landing pages with shared styling"
```

---

## Task 4: Deploy and Test Phase 3

- [ ] **Step 1: Verify all 6 new pages are linked from nav**

Check that the nav dropdowns (already set up in Phase 1) correctly link to:
- `ai-directors.html` (under Products)
- `archie-code.html` (under Products)
- `market-watch.html` (under Products)
- `civic-watch.html` (under Products)
- `legal-watch.html` (under Products)
- `gov-watch.html` (under Products)

All links should already work since the nav was built with these pages in mind during Phase 1.

- [ ] **Step 2: Deploy**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
tar -czf /tmp/site-phase3.tar.gz .
```

Deploy via Hostinger API.

- [ ] **Step 3: Test all 6 new pages**

Browser test at 1024px, 768px, 480px:
1. **ai-directors.html** — All 16 directors render, floor grouping correct, department colors show, cards responsive
2. **archie-code.html** — Terminal demo renders, feature grid responsive, install command visible
3. **market-watch.html** — Features listed, link to market.kytranempowerment.com works
4. **civic-watch.html** — Features listed, link works
5. **legal-watch.html** — Features listed, link works
6. **gov-watch.html** — Features listed, link works
7. **Nav links** — All 6 pages reachable from Products dropdown

- [ ] **Step 4: Commit hotfixes**

```bash
git add -A
git commit -m "fix(website): phase 3 hotfixes from browser testing"
```

---

## Phase 3 Complete Checklist

- [ ] ai-directors.html: 16 directors, 5 floors, C.R.E.E.D. context
- [ ] archie-code.html: CLI showcase, terminal demo, features, install
- [ ] market-watch.html: product page with live app link
- [ ] civic-watch.html: product page with live app link
- [ ] legal-watch.html: product page with live app link
- [ ] gov-watch.html: product page with live app link
- [ ] All 6 pages linked from nav Products dropdown
- [ ] All 6 pages responsive at all breakpoints
- [ ] All 6 pages have data-i18n attributes
- [ ] Translations added for all 8 languages
- [ ] Deployed and browser tested
