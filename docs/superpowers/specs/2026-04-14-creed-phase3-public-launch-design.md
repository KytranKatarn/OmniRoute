# C.R.E.E.D. Phase 3 — Public Launch, Grants & Open Source

**Date**: 2026-04-14
**Project**: #248 — C.R.E.E.D. Governance Platform — Consolidation + Standalone
**Phase**: 3 (final)
**Status**: Design approved

---

## Context

Phases 1 and 2 are complete:
- **Phase 1**: Internal C.R.E.E.D. code consolidated from `team_management/` into `tools/creed/`
- **Phase 2**: Standalone product built at `/mnt/archie_brain/kytran-creed/` — Flask app, event ingestion API, scoring engine, SVG badges, LCARS dashboard, Docker + Postgres, 16 tests passing, reporter agent loop job forwarding events from ARCHIE (every 5m, 100/batch), 502+ events already scored

Phase 3 takes C.R.E.E.D. public: fix infrastructure, expand the website, open-source the code, and prepare grant materials.

## Execution Order

Infrastructure-first approach — each step feeds the next:

1. DNS fix → live demo available
2. creed-ai.org expansion → public presence established
3. Open-source launch → code credibility
4. Grant materials → everything above referenced as evidence

---

## Step 1: DNS Fix (creed.kytranempowerment.com)

**Goal**: Get `https://creed.kytranempowerment.com` resolving to the standalone product on port 8086.

**Tasks**:
- Add/fix AdGuard DNS rewrite: `creed.kytranempowerment.com` → `192.168.1.200`
- Verify NPM proxy host (#29) is correctly forwarding to port 8086
- Verify SSL certificate is provisioned (Let's Encrypt via NPM)
- Test: HTTPS loads the LCARS dashboard externally and internally

**Verification**: Browser test from both internal network and external (VPN/mobile).

---

## Step 2: creed-ai.org Website Expansion

**Goal**: Transform the 7-page static site into a grant-ready nonprofit website.

**Current state**: Dark (#0a0a1a) + gold (#c9a44c) palette, hosted on Hostinger shared hosting.

**Email**: contact@creed-ai.org (primary), plus grants@, research@, press@, admin@ — all on Hostinger free webmail (5 accounts total).

### Pages to Add/Update

#### 2a. Homepage Refresh
- Mission statement: AI governance for the autonomous age
- Impact stats section (events scored, compliance grades issued, organizations monitored)
- Call-to-action: "Get Started" → product page, "Contact Us" → contact@creed-ai.org
- Partner/ecosystem logos section (Mila, OBVIA, CIFAR, Montreal Declaration references)

#### 2b. Product Page (NEW)
- What C.R.E.E.D. does — event-driven governance scoring for AI platforms
- Architecture overview: event ingestion → scoring engine → compliance grades → SVG badges
- API overview with example requests/responses
- Live demo link: creed.kytranempowerment.com
- Open-source link: GitHub repo
- Pricing tiers summary (Community free, Pro paid, Enterprise custom)

#### 2c. Programs Page (NEW)
- 4 flagship research programs:
  - **Program A**: Artificial Agency & Moral Risk
  - **Program B**: Memory, Continuity & Deletion Ethics
  - **Program C**: Emotional Modeling & Non-Exploitation
  - **Program D**: Governance & Representation Models
- Each program: description, research questions, relevance to industry

#### 2d. Team Page (NEW)
- Founder profile (Kytran)
- V.I.G.I.L. as AI Ethics Director
- Advisory board: "forming" with invitation to join
- Montreal AI ecosystem alignment (Mila, OBVIA, UdeM/McGill/Concordia)

#### 2e. Resources Page (NEW)
- Free compliance toolkit overview
- API documentation link
- Badge integration guide
- Link to GitHub repo for self-hosting

### Design Constraints
- Keep existing dark+gold palette and animation stack
- Responsive at 480/768/1024px breakpoints
- Same Hostinger shared hosting deployment (FTP/git push)

---

## Step 3: Open-Source Launch

**Goal**: Publish `kytran-creed` as a public GitHub repo under KytranKatarn.

### Repo Preparation
- **Secrets audit**: Remove any hardcoded values, ensure `.env.example` exists with placeholder values
- **README.md**: Project overview, features, architecture diagram, install instructions, API docs, contributing guide, license
- **LICENSE**: AGPL-3.0 (open-core SaaS model — same approach as KSO per Decision #389)
- **CONTRIBUTING.md**: How to contribute, code style, PR process
- **CODE_OF_CONDUCT.md**: Standard Contributor Covenant
- **.gitignore**: Ensure no secrets, `.env`, database files, or build artifacts

### Pricing Tiers (Open-Core Model)

| Tier | Price | Features |
|------|-------|----------|
| Community | Free | Self-hosted, event ingestion, scoring engine, SVG badges, LCARS dashboard |
| Pro | Paid | Multi-org support, advanced reports, PDF compliance certificates, priority support |
| Enterprise | Custom | SaaS hosted, SSO integration, full audit trail, SLA, custom rule packs |

Pro and Enterprise tiers are future — not built yet. The README and product page describe them as "coming soon" to establish the pricing model.

---

## Step 4: Grant Application Materials

**Goal**: Produce reusable grant materials ready to customize per funder.

### Target Funders (Priority Order)

| # | Funder | Range | Fit |
|---|--------|-------|-----|
| 1 | Coefficient Giving | $50K–$5M | "Navigating Transformative AI" program — direct match |
| 2 | ISED Canada | Varies | $8.6M AI standards funding — government credibility |
| 3 | Mozilla Foundation | $50K–$250K | Tech in public interest — open-source alignment |
| 4 | CIFAR | Varies | AI Safety pillar — Montreal ecosystem |
| 5 | SSHRC | Varies | Needs academic co-PI — future once partnership formed |

### Materials to Produce

#### 4a. Grant Narrative Template (2–3 pages)
- **Problem**: AI governance gap — platforms deploy autonomous agents without standardized compliance
- **Solution**: C.R.E.E.D. — open-source, event-driven governance scoring platform
- **Evidence**: Live dashboard (creed.kytranempowerment.com), 500+ events scored, A+ compliance grade, open-source on GitHub
- **Team**: Founder + V.I.G.I.L. AI Ethics Director + Montreal ecosystem connections
- **Impact**: Measurable governance improvements for AI platforms
- **Alignment**: Montreal Declaration on Responsible AI, Canadian AI strategy

#### 4b. Budget Template
- Personnel (founder salary, research assistants)
- Infrastructure (hosting, compute, domain costs)
- Research program costs
- Outreach and partnerships
- Overhead (standard 15–20%)

#### 4c. Impact Framework
- Quantitative: organizations using platform, events scored per month, compliance scores tracked
- Qualitative: governance best practices published, partnerships formed, policy influence

#### 4d. One-Pager (Executive Summary PDF)
- Single-page overview for cold outreach to funders
- Problem → Solution → Evidence → Ask
- Contact: contact@creed-ai.org

#### 4e. Letters of Support Template
- Template for academic/industry partners to customize
- Pre-filled with C.R.E.E.D. context and partnership value proposition

### Output Location
All grant materials written to `/mnt/archie_brain/kytran-creed/grants/` directory.

---

## What's NOT in Scope

- Payment processing or Stripe integration for pricing tiers
- Blog or CMS for creed-ai.org
- Donation payment flow
- Partner portal
- Annual report generator
- Actually submitting grant applications (user decides timing)
- Academic co-PI recruitment for SSHRC

---

## File Locations

| Deliverable | Location |
|-------------|----------|
| Standalone product | `/mnt/archie_brain/kytran-creed/` |
| creed-ai.org website | `/mnt/archie_brain/website/creed-ai.org/` |
| Grant materials | `/mnt/archie_brain/kytran-creed/grants/` |
| This spec | `/mnt/archie_brain/docs/superpowers/specs/2026-04-14-creed-phase3-public-launch-design.md` |

## References

- Previous spec: `2026-04-13-creed-governance-platform-design.md`
- Memory: `project_creed-grant-readiness.md`, `project_creed-institute.md`
- Operational state: `.claude/rules/operational-state.md` (port 8086, container kytran_creed)
