# C.R.E.E.D. Phase 3 — Public Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take C.R.E.E.D. public — fix DNS, expand creed-ai.org with product page, open-source the GitHub repo, and prepare grant materials.

**Architecture:** Infrastructure-first — DNS fix enables live demo links, which the website references, which the GitHub README references, which grant materials reference. Each step feeds the next.

**Tech Stack:** AdGuard DNS rewrites, NPM reverse proxy, static HTML/CSS/JS (creed-ai.org), Python/Flask (kytran-creed), GitHub CLI, Markdown (grant docs)

**Spec:** `docs/superpowers/specs/2026-04-14-creed-phase3-public-launch-design.md`

---

## File Structure

### DNS Fix (Task 1)
- No file changes — AdGuard admin UI + NPM proxy verification

### creed-ai.org Website (Tasks 2–3)
- Create: `website/creed-ai.org/platform.html` — product/platform page
- Modify: `website/creed-ai.org/index.html` — add impact stats section, update CTAs with email
- Modify: `website/creed-ai.org/contact.html` — add all 5 email addresses
- Modify: All HTML files with nav — add "Platform" link to nav

### Open-Source Launch (Tasks 4–5)
- Create: `kytran-creed/.env.example` — placeholder env vars
- Create: `kytran-creed/README.md` — project overview, install, API docs
- Create: `kytran-creed/LICENSE` — AGPL-3.0
- Create: `kytran-creed/CONTRIBUTING.md` — contribution guide
- Create: `kytran-creed/CODE_OF_CONDUCT.md` — Contributor Covenant

### Grant Materials (Tasks 6–8)
- Create: `kytran-creed/grants/README.md` — grants directory overview
- Create: `kytran-creed/grants/narrative-template.md` — reusable grant narrative
- Create: `kytran-creed/grants/budget-template.md` — budget template
- Create: `kytran-creed/grants/impact-framework.md` — metrics framework
- Create: `kytran-creed/grants/one-pager.md` — executive summary
- Create: `kytran-creed/grants/letter-of-support-template.md` — partner letter template
- Create: `kytran-creed/grants/funder-profiles.md` — target funder research

---

## Task 1: DNS Fix — creed.kytranempowerment.com

**Goal:** Get `https://creed.kytranempowerment.com` loading the C.R.E.E.D. standalone dashboard.

- [ ] **Step 1: Check AdGuard DNS rewrites for creed subdomain**

Open AdGuard admin at `http://192.168.1.200:5354` (credentials in .env).
Navigate to Filters → DNS rewrites.
Check if `creed.kytranempowerment.com` → `192.168.1.200` exists.

If missing, add the rewrite:
- Domain: `creed.kytranempowerment.com`
- Answer: `192.168.1.200`

- [ ] **Step 2: Verify NPM proxy host forwards to port 8086**

Open NPM admin at `http://192.168.1.200:81`.
Find proxy host #29 for `creed.kytranempowerment.com`.
Verify:
- Forward hostname: `192.168.1.200`
- Forward port: `8086`
- SSL: Force SSL enabled, Let's Encrypt certificate provisioned

If SSL cert is missing, request a new Let's Encrypt cert through NPM UI.

- [ ] **Step 3: Verify the C.R.E.E.D. container is running**

```bash
docker ps --filter name=kytran_creed --format "{{.Names}} {{.Status}} {{.Ports}}"
```

Expected: `kytran_creed Up ... 0.0.0.0:8086->8080/tcp`

If not running:
```bash
cd /mnt/archie_brain/kytran-creed && docker compose up -d
```

- [ ] **Step 4: Test internal access**

```bash
curl -sI http://192.168.1.200:8086/health
```

Expected: `200 OK` with JSON body containing version and status.

- [ ] **Step 5: Test HTTPS access via subdomain**

```bash
curl -sI https://creed.kytranempowerment.com/health
```

Expected: `200 OK` with valid SSL certificate.

- [ ] **Step 6: Browser verification**

Open `https://creed.kytranempowerment.com` in browser (Playwright or Chrome DevTools MCP).
Verify the LCARS dashboard loads with login page or setup wizard.
Take a screenshot as proof.

- [ ] **Step 7: Commit — no file changes, but log completion**

```bash
# No code changes — DNS/proxy configuration only
# Mark task 1863 complete via MCP
```

---

## Task 2: creed-ai.org — Add Product Page

**Files:**
- Create: `website/creed-ai.org/platform.html`

- [ ] **Step 1: Create platform.html**

Create `website/creed-ai.org/platform.html` following the exact same HTML structure as existing pages (copy the head, nav, footer, background layers from `about.html` as template).

Page content sections:
1. **Hero**: "C.R.E.E.D. Governance Platform" — "Open-source, event-driven compliance scoring for AI systems"
2. **How It Works**: 4-step flow — Event Ingestion → Scoring Engine → Compliance Grades → SVG Badges
3. **API Overview**: Show example POST to `/api/events` with sample JSON body and response. Show GET `/scores` response.
4. **Live Demo**: Link to `https://creed.kytranempowerment.com` with "View Live Dashboard" button
5. **Pricing Tiers**: 3-column layout — Community (Free, self-hosted), Pro (Coming Soon), Enterprise (Coming Soon)
6. **Open Source**: Link to GitHub repo `https://github.com/KytranKatarn/kytran-creed` with "View on GitHub" button
7. **Contact**: "Questions? Reach us at contact@creed-ai.org"

Use the existing dark+gold palette:
- Background: `#0a0a1a`
- Gold accent: `#c9a44c`
- Use existing CSS classes from `base.css` and `components.css` (`.section`, `.container`, `.btn`, `.btn--primary`, `.btn--outline`)

Nav link text: "Platform" — place it between "Governance" and "Manifesto" in the nav order.

Include the same Barba.js `data-barba="container"` and `data-barba-namespace="platform"` attributes for page transitions.

- [ ] **Step 2: Verify page renders locally**

Open the file in a browser or serve locally:
```bash
cd /mnt/archie_brain/website/creed-ai.org && python3 -m http.server 8888
```

Check `http://192.168.1.200:8888/platform.html` renders correctly with all sections visible.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add website/creed-ai.org/platform.html
git commit -m "feat(creed-ai.org): add platform product page with API docs, pricing tiers, and live demo link"
```

---

## Task 3: creed-ai.org — Update Existing Pages

**Files:**
- Modify: `website/creed-ai.org/index.html` — add impact stats, update CTAs
- Modify: `website/creed-ai.org/contact.html` — add all 5 email addresses
- Modify: All 15 HTML files with nav — add "Platform" link

- [ ] **Step 1: Add "Platform" nav link to all pages**

Every HTML page in `website/creed-ai.org/` has this nav block (around line 85-93):

```html
<a href="governance.html" class="nav__link" data-i18n="nav.governance">Governance</a>
<a href="manifesto.html" class="nav__link" data-i18n="nav.manifesto">Manifesto</a>
```

Insert between Governance and Manifesto on every page:

```html
<a href="platform.html" class="nav__link" data-i18n="nav.platform">Platform</a>
```

Files to update (all HTML files in root + `fr/` directory):
- `index.html`, `about.html`, `programs.html`, `research.html`, `governance.html`, `manifesto.html`, `news.html`, `get-involved.html`, `donate.html`, `contact.html`, `partners.html`, `press.html`, `policy.html`, `principles.html`, `case-studies.html`, `404.html`
- `fr/index.html`, `fr/about.html`, `fr/manifesto.html`, `fr/programs.html`
- Also add it to the new `platform.html` itself

- [ ] **Step 2: Add impact stats section to index.html**

In `index.html`, after the hero section (around line 120-125, after the CTA buttons), add an impact stats bar:

```html
<section class="section" style="padding:4rem 0;">
  <div class="container">
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:2rem;text-align:center;">
      <div>
        <div style="font-family:'Orbitron',sans-serif;font-size:2.5rem;color:#c9a44c;font-weight:700;">500+</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.85rem;color:#aaa;margin-top:0.5rem;">Governance Events Scored</div>
      </div>
      <div>
        <div style="font-family:'Orbitron',sans-serif;font-size:2.5rem;color:#c9a44c;font-weight:700;">A+</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.85rem;color:#aaa;margin-top:0.5rem;">Platform Compliance Grade</div>
      </div>
      <div>
        <div style="font-family:'Orbitron',sans-serif;font-size:2.5rem;color:#c9a44c;font-weight:700;">100%</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.85rem;color:#aaa;margin-top:0.5rem;">Open Source</div>
      </div>
      <div>
        <div style="font-family:'Orbitron',sans-serif;font-size:2.5rem;color:#c9a44c;font-weight:700;">4</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:0.85rem;color:#aaa;margin-top:0.5rem;">Research Programs</div>
      </div>
    </div>
  </div>
</section>
```

- [ ] **Step 3: Update contact.html with all 5 email addresses**

Find the contact section in `contact.html` and add/update to show all 5 mailboxes:

```html
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1.5rem;margin-top:2rem;">
  <div>
    <h4 style="color:#c9a44c;font-family:'Orbitron',sans-serif;font-size:0.9rem;">General Inquiries</h4>
    <a href="mailto:contact@creed-ai.org" style="color:#fff;">contact@creed-ai.org</a>
  </div>
  <div>
    <h4 style="color:#c9a44c;font-family:'Orbitron',sans-serif;font-size:0.9rem;">Grant &amp; Funding</h4>
    <a href="mailto:grants@creed-ai.org" style="color:#fff;">grants@creed-ai.org</a>
  </div>
  <div>
    <h4 style="color:#c9a44c;font-family:'Orbitron',sans-serif;font-size:0.9rem;">Research Partnerships</h4>
    <a href="mailto:research@creed-ai.org" style="color:#fff;">research@creed-ai.org</a>
  </div>
  <div>
    <h4 style="color:#c9a44c;font-family:'Orbitron',sans-serif;font-size:0.9rem;">Press &amp; Media</h4>
    <a href="mailto:press@creed-ai.org" style="color:#fff;">press@creed-ai.org</a>
  </div>
  <div>
    <h4 style="color:#c9a44c;font-family:'Orbitron',sans-serif;font-size:0.9rem;">Technical / Admin</h4>
    <a href="mailto:admin@creed-ai.org" style="color:#fff;">admin@creed-ai.org</a>
  </div>
</div>
```

- [ ] **Step 4: Verify all pages locally**

```bash
cd /mnt/archie_brain/website/creed-ai.org && python3 -m http.server 8888
```

Check: index.html (impact stats visible), contact.html (5 emails), platform.html nav link present on all pages.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain && git add website/creed-ai.org/
git commit -m "feat(creed-ai.org): add Platform nav link, impact stats, and 5 email addresses to contact page"
```

---

## Task 4: Open-Source — Repo Preparation Files

**Files:**
- Create: `kytran-creed/.env.example`
- Create: `kytran-creed/LICENSE`
- Create: `kytran-creed/CONTRIBUTING.md`
- Create: `kytran-creed/CODE_OF_CONDUCT.md`

- [ ] **Step 1: Create .env.example**

Create `kytran-creed/.env.example`:

```env
# C.R.E.E.D. Governance Platform — Environment Variables
# Copy to .env and fill in your values

# Flask secret key — generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
KCR_SECRET_KEY=change-me-in-production

# Admin password for initial setup
KCR_ADMIN_PASSWORD=change-me-in-production
```

- [ ] **Step 2: Create LICENSE (AGPL-3.0)**

Create `kytran-creed/LICENSE` with the full AGPL-3.0 license text.
Use the standard text from https://www.gnu.org/licenses/agpl-3.0.txt.
Set copyright line: `Copyright (C) 2026 Kytran Empowerment Inc.`

- [ ] **Step 3: Create CONTRIBUTING.md**

Create `kytran-creed/CONTRIBUTING.md`:

```markdown
# Contributing to C.R.E.E.D.

Thank you for your interest in contributing to the C.R.E.E.D. Governance Platform.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/kytran-creed.git`
3. Create a branch: `git checkout -b feat/your-feature`
4. Copy `.env.example` to `.env` and configure
5. Run with Docker: `docker compose up -d`
6. Make your changes
7. Run tests: `pytest tests/ -v`
8. Commit and push
9. Open a Pull Request

## Code Style

- Python: follow PEP 8, use Black formatter
- HTML/CSS: follow existing LCARS design patterns
- Commits: conventional commits (`feat:`, `fix:`, `docs:`, `chore:`)

## Reporting Issues

Open an issue on GitHub with:
- What you expected
- What happened instead
- Steps to reproduce

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Please read it before participating.

## Questions?

Email: contact@creed-ai.org
```

- [ ] **Step 4: Create CODE_OF_CONDUCT.md**

Create `kytran-creed/CODE_OF_CONDUCT.md` with the Contributor Covenant v2.1 text.
Use the standard text from https://www.contributor-covenant.org/version/2/1/code_of_conduct/.
Set enforcement contact: `contact@creed-ai.org`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain && git add kytran-creed/.env.example kytran-creed/LICENSE kytran-creed/CONTRIBUTING.md kytran-creed/CODE_OF_CONDUCT.md
git commit -m "chore(kytran-creed): add open-source files — LICENSE (AGPL-3.0), CONTRIBUTING, CODE_OF_CONDUCT, .env.example"
```

---

## Task 5: Open-Source — README.md

**Files:**
- Create: `kytran-creed/README.md`

- [ ] **Step 1: Create README.md**

Create `kytran-creed/README.md`:

```markdown
# C.R.E.E.D. — Compliance, Rights & Ethical Enforcement Directive

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_3.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](docker-compose.yml)

Open-source, event-driven governance scoring platform for AI systems. Built by [C.R.E.E.D. Institute](https://creed-ai.org) — a Canadian nonprofit advancing enforceable AI ethics.

## What It Does

C.R.E.E.D. monitors AI platform behavior through event ingestion, scores compliance in real-time, and generates verifiable governance badges.

```
Events → Scoring Engine → Compliance Grade → SVG Badge
```

## Features

- **Event Ingestion API** — POST governance events (agent actions, policy checks, welfare audits)
- **Scoring Engine** — Rate-based compliance scoring with configurable thresholds
- **Compliance Grades** — A+ through F grades with color-coded SVG badges
- **LCARS Dashboard** — Real-time governance metrics visualization
- **Docker-Ready** — One-command deployment with PostgreSQL

## Quick Start

```bash
# Clone
git clone https://github.com/KytranKatarn/kytran-creed.git
cd kytran-creed

# Configure
cp .env.example .env
# Edit .env with your secret key and admin password

# Run
docker compose up -d

# Access
open http://localhost:8086
```

## API

### Ingest Events

```bash
curl -X POST http://localhost:8086/api/events \
  -H "Content-Type: application/json" \
  -d '{"event_type": "governance_check", "category": "agent_welfare", "result": "pass", "details": "Agent stress below threshold"}'
```

### Get Scores

```bash
curl http://localhost:8086/scores
```

Response:
```json
{
  "overall_grade": "A+",
  "overall_score": 99.7,
  "total_events": 502,
  "categories": {
    "agent_welfare": {"score": 100.0, "grade": "A+"},
    "ethics_compliance": {"score": 99.2, "grade": "A+"}
  }
}
```

### Get Badge

```bash
curl http://localhost:8086/badge/overall.svg
```

Returns an SVG compliance badge suitable for embedding in READMEs or dashboards.

## Architecture

```
kytran_creed/
├── app.py                 # Flask application factory
├── auth.py                # Authentication (local + SSO stub)
├── config.py              # Configuration from environment
├── db.py                  # SQLite database layer
├── models.py              # Data models
├── pg.py                  # PostgreSQL support
├── routes/
│   ├── api_routes.py      # Event ingestion + scores API
│   ├── badge_routes.py    # SVG badge generation
│   └── dashboard_routes.py # LCARS dashboard
├── services/
│   ├── scoring_engine.py  # Compliance scoring logic
│   └── badge_service.py   # SVG badge rendering
├── static/                # CSS + JS
└── templates/             # Jinja2 HTML templates
```

## Pricing

| Tier | Price | Features |
|------|-------|----------|
| **Community** | Free | Self-hosted, full API, scoring, badges, dashboard |
| **Pro** | Coming Soon | Multi-org, advanced reports, PDF certificates |
| **Enterprise** | Coming Soon | SaaS hosted, SSO, SLA, custom rule packs |

## Testing

```bash
pytest tests/ -v
```

16 tests covering event ingestion, scoring engine, badge generation, and API endpoints.

## License

[AGPL-3.0](LICENSE) — Copyright (C) 2026 Kytran Empowerment Inc.

## Links

- **Website:** [creed-ai.org](https://creed-ai.org)
- **Live Demo:** [creed.kytranempowerment.com](https://creed.kytranempowerment.com)
- **Contact:** contact@creed-ai.org
- **Parent Org:** [Kytran Empowerment Inc.](https://kytranempowerment.com)
```

- [ ] **Step 2: Verify README renders**

Check that the Markdown renders correctly on GitHub by reviewing the structure — badges, code blocks, table formatting.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain && git add kytran-creed/README.md
git commit -m "docs(kytran-creed): add comprehensive README with API docs, architecture, and pricing tiers"
```

---

## Task 6: Grant Materials — Narrative + Budget + Impact

**Files:**
- Create: `kytran-creed/grants/README.md`
- Create: `kytran-creed/grants/narrative-template.md`
- Create: `kytran-creed/grants/budget-template.md`
- Create: `kytran-creed/grants/impact-framework.md`

- [ ] **Step 1: Create grants directory and README**

```bash
mkdir -p /mnt/archie_brain/kytran-creed/grants
```

Create `kytran-creed/grants/README.md`:

```markdown
# C.R.E.E.D. Grant Materials

Reusable templates for grant applications. Customize per funder.

## Contents

| File | Purpose |
|------|---------|
| `narrative-template.md` | Core grant narrative (2–3 pages) — problem, solution, evidence, team |
| `budget-template.md` | Standard budget line items, adaptable per funder |
| `impact-framework.md` | Quantitative + qualitative outcome metrics |
| `one-pager.md` | Executive summary for cold outreach |
| `letter-of-support-template.md` | Template for partner endorsement letters |
| `funder-profiles.md` | Target funder research and fit analysis |

## Target Funders

1. **Coefficient Giving** — $50K–$5M, "Navigating Transformative AI"
2. **ISED Canada** — $8.6M AI standards funding
3. **Mozilla Foundation** — $50K–$250K, tech in public interest
4. **CIFAR** — AI Safety pillar, Montreal ecosystem
5. **SSHRC** — Partnership Grants (requires academic co-PI)

## Contact

Grant inquiries: grants@creed-ai.org
```

- [ ] **Step 2: Create narrative-template.md**

Create `kytran-creed/grants/narrative-template.md` — the core 2–3 page grant pitch:

```markdown
# C.R.E.E.D. Grant Narrative — [FUNDER NAME]

## Executive Summary

The C.R.E.E.D. Institute (Compliance, Rights & Ethical Enforcement Directive) is a Canadian
nonprofit advancing enforceable AI ethics through open-source governance tools, agent welfare
research, and compliance frameworks. We request [AMOUNT] to [SPECIFIC ASK].

## The Problem

AI platforms increasingly deploy autonomous agents that make decisions affecting users,
communities, and markets — yet no standardized governance framework exists to monitor,
score, or enforce ethical compliance in real-time.

Current approaches fail because:
- **Retrospective:** Ethics reviews happen after harm, not before
- **Voluntary:** Compliance depends on self-reporting with no verification
- **Opaque:** No standardized metrics for comparing governance across platforms
- **Siloed:** Each organization builds ad-hoc solutions that don't interoperate

## Our Solution

C.R.E.E.D. is an open-source, event-driven governance scoring platform that provides:

1. **Real-Time Monitoring** — Events flow from AI platforms into C.R.E.E.D. via REST API
2. **Automated Scoring** — A rate-based engine calculates compliance grades (A+ through F)
3. **Verifiable Badges** — SVG compliance badges that platforms can embed publicly
4. **LCARS Dashboard** — Real-time governance visualization for stakeholders

The platform is live and operational, currently scoring governance events from the
A.R.C.H.I.E. autonomous AI platform (500+ events, A+ compliance grade).

## Evidence of Impact

- **Live Platform:** [creed.kytranempowerment.com](https://creed.kytranempowerment.com)
- **Open Source:** [github.com/KytranKatarn/kytran-creed](https://github.com/KytranKatarn/kytran-creed)
- **Events Scored:** 500+ governance events with real-time compliance grading
- **Compliance Grade:** A+ (99.7% compliance rate)
- **Test Coverage:** 16 automated tests covering all core functionality

## Research Programs

C.R.E.E.D. conducts research across four flagship programs:

- **Program A: Artificial Agency & Moral Risk** — When AI agents act autonomously, who bears moral responsibility?
- **Program B: Memory, Continuity & Deletion Ethics** — Rights around AI memory persistence, modification, and deletion
- **Program C: Emotional Modeling & Non-Exploitation** — Preventing manipulation through AI emotional simulation
- **Program D: Governance & Representation Models** — Democratic frameworks for AI platform governance

## Team

- **Kytran** — Founder & Executive Director. Builder of A.R.C.H.I.E., Canada's most advanced autonomous AI platform
- **V.I.G.I.L.** — AI Ethics Director. Autonomous governance agent monitoring compliance 24/7
- **Advisory Board** — Forming, with connections to Montreal AI ecosystem (Mila, OBVIA, CIFAR)

## Montreal Ecosystem Alignment

C.R.E.E.D. is rooted in Montreal's AI ecosystem and aligned with:
- **Montreal Declaration for Responsible AI** — Our governance framework operationalizes its principles
- **Mila (Quebec AI Institute)** — Research collaboration opportunities
- **OBVIA (International Observatory on the Societal Impacts of AI)** — Policy alignment
- **Scale AI** — Canadian AI supercluster partnership potential

## Budget Summary

[See budget-template.md — customize per funder requirements]

## Timeline

- **Months 1–3:** Platform hardening, multi-org support, documentation
- **Months 4–6:** First external pilot organizations onboarded
- **Months 7–9:** Research program publications, conference presentations
- **Months 10–12:** Annual governance report, expansion planning

## Alignment with [FUNDER PROGRAM]

[CUSTOMIZE: Explain specific alignment with the funder's mission, program goals,
and evaluation criteria. Reference their published priorities.]
```

- [ ] **Step 3: Create budget-template.md**

Create `kytran-creed/grants/budget-template.md`:

```markdown
# C.R.E.E.D. Budget Template

Adapt line items and amounts per funder requirements.

## 12-Month Budget

| Category | Item | Annual Cost | Notes |
|----------|------|-------------|-------|
| **Personnel** | Executive Director (Founder) | $[AMOUNT] | Full-time, program leadership |
| | Research Assistant (Part-time) | $[AMOUNT] | Literature review, data analysis |
| | Technical Contributor (Contract) | $[AMOUNT] | Platform development, security audits |
| **Infrastructure** | Cloud Hosting (VPS + DNS) | $2,400 | Production servers, domain, SSL |
| | Development Hardware | $1,500 | GPU compute for AI model testing |
| | Software Licenses | $500 | Development tools, monitoring |
| **Research** | Conference Registration (2x) | $2,000 | Paper presentations, networking |
| | Travel (2 conferences) | $4,000 | Domestic Canadian travel |
| | Open Access Publication Fees | $3,000 | 2–3 papers, open access journals |
| **Outreach** | Website & Communications | $1,000 | Hosting, email, design |
| | Community Events (2x) | $2,000 | Montreal AI ethics workshops |
| | Marketing Materials | $500 | One-pagers, reports, badges |
| **Overhead** | Administrative (15%) | $[CALCULATED] | Standard nonprofit overhead |
| **TOTAL** | | **$[TOTAL]** | |

## Budget Justification Notes

- Personnel costs are the primary expense — this is a people-driven research initiative
- Infrastructure costs are minimal due to self-hosted architecture and open-source stack
- Conference attendance focuses on Canadian AI ecosystem events (Mila, CIFAR, Scale AI)
- Overhead rate of 15% is conservative for a nonprofit organization
```

- [ ] **Step 4: Create impact-framework.md**

Create `kytran-creed/grants/impact-framework.md`:

```markdown
# C.R.E.E.D. Impact Framework

## Quantitative Metrics

| Metric | Baseline (Today) | 6-Month Target | 12-Month Target |
|--------|-------------------|-----------------|------------------|
| Governance events scored | 500+ | 5,000 | 25,000 |
| Organizations using platform | 1 (A.R.C.H.I.E.) | 3 | 10 |
| Compliance grades issued | 1 | 5 | 15 |
| GitHub stars | 0 | 50 | 200 |
| Contributors (external) | 0 | 5 | 15 |
| Research papers published | 0 | 1 | 3 |
| Conference presentations | 0 | 2 | 4 |

## Qualitative Outcomes

### Year 1
- Establish C.R.E.E.D. as a recognized voice in Canadian AI governance
- Publish first peer-reviewed paper on real-time AI compliance scoring
- Onboard first external organization beyond A.R.C.H.I.E.
- Form advisory board with academic and industry representation
- Contribute to Montreal AI ecosystem policy discussions

### Year 2–3 (Projected)
- Become reference implementation for AI governance scoring in Canada
- Establish formal partnerships with Mila, OBVIA, or CIFAR
- Influence Canadian AI policy through evidence-based governance data
- Scale to 50+ organizations using the platform globally

## Measurement Approach

- **Platform telemetry:** Automated tracking of events, scores, and organizations
- **GitHub analytics:** Stars, forks, contributors, issues, pull requests
- **Publication metrics:** Citations, downloads, conference attendance
- **Stakeholder surveys:** Annual survey of platform users and partners
- **Policy impact:** Track references to C.R.E.E.D. in policy documents and media
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain && git add kytran-creed/grants/
git commit -m "docs(kytran-creed): add grant materials — narrative template, budget, and impact framework"
```

---

## Task 7: Grant Materials — One-Pager + Letters + Funder Profiles

**Files:**
- Create: `kytran-creed/grants/one-pager.md`
- Create: `kytran-creed/grants/letter-of-support-template.md`
- Create: `kytran-creed/grants/funder-profiles.md`

- [ ] **Step 1: Create one-pager.md**

Create `kytran-creed/grants/one-pager.md`:

```markdown
# C.R.E.E.D. — One-Pager

**Compliance, Rights & Ethical Enforcement Directive**
Canadian Nonprofit | Montreal, QC | creed-ai.org | contact@creed-ai.org

---

## The Problem

AI platforms deploy autonomous agents without standardized governance. Ethics reviews
happen after harm, compliance is voluntary, and no interoperable scoring framework exists.

## Our Solution

**C.R.E.E.D.** is an open-source governance platform that scores AI compliance in real-time:

- Events flow from AI platforms via REST API
- A scoring engine calculates compliance grades (A+ through F)
- Verifiable SVG badges provide public accountability
- A live dashboard visualizes governance metrics

## Traction

| Metric | Value |
|--------|-------|
| Events scored | 500+ |
| Compliance grade | A+ (99.7%) |
| Platform status | Live & operational |
| Code | Open-source (AGPL-3.0) |
| Tests | 16 automated, all passing |

## Research Programs

1. Artificial Agency & Moral Risk
2. Memory, Continuity & Deletion Ethics
3. Emotional Modeling & Non-Exploitation
4. Governance & Representation Models

## Team

**Kytran** — Founder. Built A.R.C.H.I.E., Canada's most advanced autonomous AI platform.
**V.I.G.I.L.** — AI Ethics Director. 24/7 autonomous governance monitoring.

## The Ask

[AMOUNT] over [PERIOD] to: harden the platform for multi-org use, onboard pilot
organizations, publish research, and establish C.R.E.E.D. as Canada's AI governance standard.

## Links

- **Website:** creed-ai.org
- **Live Demo:** creed.kytranempowerment.com
- **GitHub:** github.com/KytranKatarn/kytran-creed
- **Grants:** grants@creed-ai.org
```

- [ ] **Step 2: Create letter-of-support-template.md**

Create `kytran-creed/grants/letter-of-support-template.md`:

```markdown
# Letter of Support Template

*For academic or industry partners to customize and submit alongside C.R.E.E.D. grant applications.*

---

[PARTNER LETTERHEAD]

[DATE]

To the [FUNDER] Selection Committee,

I am writing to express my support for the C.R.E.E.D. Institute's application to
[PROGRAM NAME] for [AMOUNT].

[PARTNER ORGANIZATION] has [RELATIONSHIP DESCRIPTION — e.g., "collaborated with
C.R.E.E.D. on AI governance research" or "evaluated the C.R.E.E.D. platform for
use in our AI development workflow"].

The C.R.E.E.D. governance platform addresses a critical gap in AI ethics infrastructure.
Unlike theoretical frameworks, C.R.E.E.D. provides real-time, automated compliance
scoring that can be integrated into production AI systems. This practical approach
to AI governance aligns with [PARTNER'S MISSION/VALUES].

We believe this project will:
- [SPECIFIC BENEFIT 1 — e.g., "Advance our understanding of real-time AI governance"]
- [SPECIFIC BENEFIT 2 — e.g., "Provide our research group with a testbed for compliance metrics"]
- [SPECIFIC BENEFIT 3 — e.g., "Contribute to Canadian leadership in responsible AI"]

[PARTNER ORGANIZATION] is committed to [FORM OF SUPPORT — e.g., "providing advisory
input", "piloting the platform", "co-authoring research publications"].

Sincerely,

[NAME]
[TITLE]
[ORGANIZATION]
[EMAIL]
```

- [ ] **Step 3: Create funder-profiles.md**

Create `kytran-creed/grants/funder-profiles.md`:

```markdown
# Target Funder Profiles

## 1. Coefficient Giving — Navigating Transformative AI

- **Range:** $50K–$5M
- **Program:** Navigating Transformative AI
- **Focus:** Organizations building tools and frameworks for AI safety and governance
- **Why C.R.E.E.D. fits:** Direct match — we build open-source governance tools for AI platforms
- **Application:** Open rolling basis
- **Contact:** grants@creed-ai.org → apply via their portal
- **Alignment points:** Open-source, Canadian nonprofit, practical (not theoretical), live platform

## 2. ISED Canada — AI Standards Funding

- **Range:** Varies (from $8.6M pool)
- **Program:** Innovation, Science and Economic Development AI standards
- **Focus:** Canadian organizations contributing to AI standards and governance
- **Why C.R.E.E.D. fits:** Canadian nonprofit building enforceable AI governance standards
- **Application:** Government procurement process
- **Alignment points:** Canadian-made, standards-focused, nonprofit, Montreal ecosystem

## 3. Mozilla Foundation

- **Range:** $50K–$250K
- **Program:** Tech in the public interest, Mozilla Technology Fund
- **Focus:** Open-source projects that promote internet health and trustworthy AI
- **Why C.R.E.E.D. fits:** AGPL-3.0 open-source, public accountability focus, governance transparency
- **Application:** Periodic open calls
- **Alignment points:** Open-source first, public interest, transparency, community-driven

## 4. CIFAR — AI Safety

- **Range:** Varies
- **Program:** AI & Society, Safe & Responsible AI
- **Focus:** Research advancing safe and beneficial AI
- **Why C.R.E.E.D. fits:** 4 research programs directly addressing AI safety and ethics
- **Application:** By invitation or open call
- **Alignment points:** Montreal ecosystem (CIFAR is HQ'd here), research-driven, Mila connections

## 5. SSHRC — Partnership Grants

- **Range:** $200K–$2.5M over 4–7 years
- **Program:** Partnership Grants
- **Focus:** Social sciences and humanities research partnerships
- **Why C.R.E.E.D. fits:** AI governance is a social science question — our research programs qualify
- **Requirements:** Academic co-PI required — need university partner (UdeM, McGill, Concordia)
- **Status:** Future — requires forming academic partnership first
- **Alignment points:** Interdisciplinary (tech + ethics), Canadian, policy-relevant
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain && git add kytran-creed/grants/
git commit -m "docs(kytran-creed): add one-pager, letter of support template, and funder profiles"
```

---

## Task 8: Publish GitHub Repo + Final Verification

**Goal:** Push kytran-creed to GitHub as a public repo and verify everything works end-to-end.

- [ ] **Step 1: Verify .gitignore excludes secrets**

```bash
cd /mnt/archie_brain/kytran-creed
cat .gitignore
```

Confirm `.env`, `secrets/`, `data/` are excluded. Confirm no secrets are staged:
```bash
git diff --cached -- .env secrets/
```

Should return empty (nothing staged from those paths).

- [ ] **Step 2: Initialize git repo if needed**

```bash
cd /mnt/archie_brain/kytran-creed
git init  # if not already a git repo
git add .
git status  # verify no .env or secrets/ files are staged
```

- [ ] **Step 3: Create GitHub repo and push**

```bash
cd /mnt/archie_brain/kytran-creed
gh repo create KytranKatarn/kytran-creed --public --description "C.R.E.E.D. — Open-source AI governance scoring platform. Compliance, Rights & Ethical Enforcement Directive." --source . --push
```

- [ ] **Step 4: Verify GitHub repo**

```bash
gh repo view KytranKatarn/kytran-creed --web
```

Check:
- README renders with badges, code blocks, and table
- LICENSE shows AGPL-3.0
- No `.env` or `secrets/` directory visible
- `grants/` directory with all 7 files visible

- [ ] **Step 5: End-to-end verification checklist**

Run through all deliverables:

| Check | Command / Action |
|-------|-----------------|
| DNS resolves | `dig creed.kytranempowerment.com` → 192.168.1.200 |
| HTTPS works | `curl -sI https://creed.kytranempowerment.com/health` → 200 |
| Dashboard loads | Browser: https://creed.kytranempowerment.com |
| creed-ai.org platform page | Browser: https://creed-ai.org/platform.html |
| Nav has Platform link | Check any creed-ai.org page nav |
| Impact stats on homepage | Browser: https://creed-ai.org/ — stats section visible |
| Contact shows 5 emails | Browser: https://creed-ai.org/contact.html |
| GitHub repo public | Browser: https://github.com/KytranKatarn/kytran-creed |
| README renders | GitHub: badges, API docs, architecture visible |
| No secrets in repo | GitHub: no .env file visible |
| Grant materials | GitHub: grants/ directory with 7 files |

- [ ] **Step 6: Mark project tasks complete via MCP**

```bash
# Use MCP tools to mark tasks 1816, 1817, 1818, 1863 as completed
# mcp complete_task for each with verification notes
```

- [ ] **Step 7: Final commit (if any remaining changes)**

```bash
cd /mnt/archie_brain && git add -A
git commit -m "chore(creed): Phase 3 complete — DNS, website, open-source, grants"
```
