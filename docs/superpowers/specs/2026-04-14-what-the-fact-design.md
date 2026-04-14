# What The Fact — AI-Powered Transparent News Platform

**Date**: 2026-04-14
**Status**: Design approved
**Domains**: what-the-fact.com, what-the-fact.tech
**Parent**: Kytran Empowerment Inc.

---

## Vision

What The Fact is Canada's first AI-powered news platform built on radical transparency. It pulls from multiple news sources, uses AI to summarize, detect bias, and fact-check — then shows its entire methodology openly. Every article has an audit trail. Every AI decision is logged. C.R.E.E.D. monitors the platform's governance continuously.

The goal: find the center of the truth by exposing how different media outlets report the same story, proving bias with data, and letting readers see exactly how conclusions were reached.

## Brand Architecture

| Property | Domain | Role |
|----------|--------|------|
| **What The Fact** | what-the-fact.com | Consumer news portal — articles, bias spectrum, fact-checks |
| **WTF Tech** | what-the-fact.tech | Transparency + developer platform — audit trails, methodology, API, GitHub |

Both monitored by C.R.E.E.D. governance scoring.

## Data Architecture

```
PRIMARY SOURCES (WTF's own research)
├── Canadian news outlets (CBC, Globe & Mail, National Post, CTV, Toronto Star, etc.)
├── Government databases (Parliament, court records, StatsCan, public data)
├── Press releases, official statements
└── Social media / public discourse

ENRICHMENT SOURCES (optional depth)
├── Civic Watch — municipal/provincial civic data
├── Legal Watch — court filings, legal analysis
├── Market Watch — financial/economic data
└── Gov Watch — federal government activity

        ↓ all sources ↓

    WTF AI PIPELINE
    ├── 1. Ingest — pull articles/data from all sources
    ├── 2. Summarize — AI-generated neutral summary
    ├── 3. Bias Detect — score each source (left/center/right)
    ├── 4. Fact-Check — cross-reference claims against data
    ├── 5. Truth Spectrum — visualize where truth lands
    └── 6. Audit — log every AI decision → C.R.E.E.D.

        ↓ output ↓

    what-the-fact.com        what-the-fact.tech
    (reader-facing)          (transparency layer)
```

## Categories

Matching the Watch product domains but not dependent on them:

- **Civic** — municipal, provincial, community news
- **Legal** — courts, law, justice system
- **Market** — economy, business, finance
- **Government** — federal politics, policy, Parliament
- **General** — stories that span categories

## Sub-Project 1: Infrastructure & Domains

**Goal**: Get both domains live and serving content.

### DNS Configuration
- `what-the-fact.com` → A record → VPS IP (76.13.107.109)
- `www.what-the-fact.com` → CNAME → what-the-fact.com
- `what-the-fact.tech` → A record → VPS IP (76.13.107.109)
- `www.what-the-fact.tech` → CNAME → what-the-fact.tech

### VPS Reverse Proxy (Caddy)
- what-the-fact.com → port 8103 (rebrand existing The News container)
- what-the-fact.tech → port 8104 (new container)
- SSL via Caddy auto-HTTPS (Let's Encrypt)

### Container Plan
- `kytran_wtf_news` — what-the-fact.com (port 8103, replaces kytran_news)
- `kytran_wtf_tech` — what-the-fact.tech (port 8104, new)
- `kytran_wtf_pipeline` — AI pipeline worker (no public port, internal only)
- Shared Postgres database: `wtf` (on VPS or hub)

### Redirect
- thenews.kytranempowerment.com → 301 redirect to what-the-fact.com

### Hostinger Deploys (Bundle with pending work)
- Deploy creed-ai.org updates (pending from this session)
- Deploy kytranempowerment.com updates (pending from this session)
- Configure what-the-fact.com DNS in Hostinger
- Configure what-the-fact.tech DNS in Hostinger

### Deliverables
- [ ] DNS records configured for both domains
- [ ] Caddy reverse proxy entries added on VPS
- [ ] SSL certificates provisioned
- [ ] Container(s) running and accessible
- [ ] thenews.kytranempowerment.com redirects to what-the-fact.com
- [ ] Pending Hostinger deploys completed (creed-ai.org, kytranempowerment.com)

---

## Sub-Project 2: AI News Pipeline

**Goal**: Build the engine that ingests, summarizes, detects bias, and fact-checks.

### Components

#### 2a. News Ingestion
- RSS/API feeds from major Canadian outlets
- Source registry: name, URL, known bias lean (seeded from media bias databases)
- Scheduled scraping (every 15-30 min for breaking, hourly for general)
- Article deduplication (same story from multiple outlets = one "story cluster")
- Watch product API integration (optional enrichment, not dependency)

#### 2b. AI Summarization
- For each story cluster: generate a neutral summary from all source articles
- Use Bridge dispatch or direct LLM (configurable)
- Summary includes: headline, 2-3 paragraph summary, key claims extracted
- Multiple summary lengths: headline (1 line), brief (1 paragraph), full (3 paragraphs)

#### 2c. Bias Detection
- Score each source article on a spectrum: Far Left → Left → Center-Left → Center → Center-Right → Right → Far Right
- Methodology: language analysis, framing analysis, source selection, headline sentiment
- Per-story "bias map" showing where each outlet falls
- Aggregate outlet bias score (rolling, updated with each article)
- Confidence score on each bias assessment

#### 2d. Fact-Checking
- Extract claims from articles (AI-powered claim extraction)
- Cross-reference against: government databases, court records, StatsCan, public data
- Watch product data as enrichment source
- Verdict per claim: Verified / Partially True / Misleading / False / Unverifiable
- Evidence chain: what data supports the verdict

#### 2e. C.R.E.E.D. Integration
- Every AI decision emits a governance event to C.R.E.E.D.
- Event types: article_summarized, bias_scored, claim_checked, verdict_issued
- Categories: accountability, fairness, transparency
- C.R.E.E.D. monitors for: bias in WTF's own AI, consistency of fact-checks, transparency compliance

### Database Schema (Postgres)
- `stories` — story clusters (multiple articles about the same event)
- `articles` — individual source articles linked to stories
- `sources` — news outlet registry with bias profiles
- `summaries` — AI-generated summaries per story
- `bias_scores` — per-article and per-source bias assessments
- `claims` — extracted claims from articles
- `fact_checks` — verdict + evidence chain per claim
- `audit_trail` — every AI decision logged with inputs/outputs/model/confidence
- `pipeline_runs` — job tracking for ingestion/analysis cycles

### Deliverables
- [ ] News ingestion from 10+ Canadian sources
- [ ] Story clustering (dedup same event across outlets)
- [ ] AI summarization (3 lengths)
- [ ] Bias detection scoring per article and per outlet
- [ ] Claim extraction and fact-checking
- [ ] C.R.E.E.D. event emission for all AI decisions
- [ ] Pipeline scheduler (APScheduler or cron)
- [ ] Database schema and migrations

---

## Sub-Project 3: what-the-fact.com (Consumer Site)

**Goal**: Reader-facing news portal with bias visualization and fact-checks.

### Pages

#### Homepage
- Top stories with bias spectrum preview
- Category navigation (Civic, Legal, Market, Government, General)
- "Truth Score" indicator per story (how well-sourced/verified)
- Search
- WTF branding (bold, modern, trustworthy)

#### Story Page
- Neutral AI summary (with "How we wrote this" link → .tech)
- Bias spectrum visualization — horizontal bar showing where each source falls
- Source comparison — side-by-side excerpts from different outlets
- Fact-check section — claims with verdicts and evidence
- "View Full Audit Trail" link → what-the-fact.tech
- C.R.E.E.D. badge showing governance grade

#### Category Pages
- Civic, Legal, Market, Government, General
- Filtered story list with bias indicators
- Category-level bias trends ("This week, coverage of X leaned Y")

#### About Page
- Mission: find the center of the truth
- How it works (simplified)
- Team / AI transparency
- Link to what-the-fact.tech for full methodology

### Design
- NOT LCARS (this is consumer-facing, not admin)
- Clean, modern, high-trust design (think Reuters/AP meets Ground News)
- Dark/light mode toggle
- Mobile-first responsive
- Fast loading (static generation where possible)

### Tech Stack
- Flask or Next.js (TBD based on team preference)
- Postgres (shared with pipeline)
- Server-side rendering for SEO
- Docker on VPS

### Deliverables
- [ ] Homepage with top stories and bias previews
- [ ] Story page with full bias spectrum + fact-checks
- [ ] Category pages
- [ ] About page
- [ ] Search functionality
- [ ] Mobile responsive
- [ ] C.R.E.E.D. badge integration

---

## Sub-Project 4: what-the-fact.tech (Transparency Platform)

**Goal**: Full transparency + developer platform.

### Pages

#### Transparency Dashboard
- Live pipeline status (articles processed, claims checked, bias scores issued)
- C.R.E.E.D. governance grade (embedded from creed.kytranempowerment.com/results)
- Recent audit trail entries

#### Per-Article Audit Trail
- Every article linked from .com has a corresponding .tech page
- Shows: all sources pulled, AI prompts used, model + version, bias scoring breakdown, fact-check evidence chain, confidence levels, processing time
- Fully transparent — nothing hidden

#### Methodology
- How bias scoring works (algorithm, training data, known limitations)
- How fact-checking works (data sources, cross-reference methodology)
- How summarization works (model, prompting strategy, quality controls)
- Known biases and limitations of the system itself

#### API Documentation
- Public API for querying:
  - Stories and articles
  - Bias scores per outlet
  - Fact-check verdicts
  - Audit trails
- Rate limits: generous free tier, API key for heavy use
- OpenAPI/Swagger docs

#### Developer Hub
- GitHub links to open-source components
- Contributing guide
- Issue tracker
- Rule packs for fact-checking (community-contributed)

### Design
- Dark theme with tech/terminal aesthetic (similar to creed-ai.org)
- Code-heavy, data-dense
- Developer-friendly

### Deliverables
- [ ] Transparency dashboard with live stats
- [ ] Per-article audit trail pages
- [ ] Methodology documentation
- [ ] Public API with documentation
- [ ] Developer hub with GitHub links
- [ ] C.R.E.E.D. integration (governance badge + live scores)

---

## Email Accounts (what-the-fact.com)

Set up via Hostinger webmail (5 free accounts per domain):

| Email | Purpose |
|-------|---------|
| tips@what-the-fact.com | News tips submission |
| press@what-the-fact.com | Press/media inquiries |
| api@what-the-fact.com | API support / developer inquiries |
| contact@what-the-fact.com | General contact |
| admin@what-the-fact.com | Technical/admin |

## C.R.E.E.D. Monitoring

What The Fact emits governance events to C.R.E.E.D. for:
- Every AI summarization (was it neutral? did it hallucinate?)
- Every bias score (was the scoring consistent? any drift?)
- Every fact-check verdict (evidence quality, confidence level)
- Pipeline health (uptime, error rates, processing times)

C.R.E.E.D. categories for WTF:
- **Accountability** — AI decisions are logged and auditable
- **Fairness** — bias detection is applied consistently across all outlets
- **Transparency** — methodology is public, audit trails available
- **Privacy** — no user tracking beyond essentials
- **Safety** — no amplification of misinformation

## Implementation Order

1. **Sub-Project 1: Infrastructure** — domains, DNS, containers, redirects
2. **Sub-Project 2: AI Pipeline** — the engine (can develop on hub, deploy to VPS later)
3. **Sub-Project 3: what-the-fact.com** — consumer site connected to pipeline
4. **Sub-Project 4: what-the-fact.tech** — transparency layer

Sub-projects 2 and 3 can partially overlap (build pipeline + basic site together).
Sub-project 4 comes after 2+3 have data flowing.

## What's NOT in Scope (First Release)

- User accounts / login on .com (readers don't need accounts)
- Comments or community features
- Paid subscriptions
- Mobile app
- Non-Canadian news (future expansion)
- Real-time breaking news alerts (future)
- Video/podcast content

## File Locations

| Component | Location |
|-----------|----------|
| This spec | `docs/superpowers/specs/2026-04-14-what-the-fact-design.md` |
| .com site | TBD — likely `/mnt/archie_brain/what-the-fact/` or VPS |
| .tech site | TBD — likely `/mnt/archie_brain/what-the-fact-tech/` or VPS |
| Pipeline | TBD — likely within .com repo or separate |
| Current The News | `website/thenews.kytranempowerment.com/` |

## References

- The News product: `website/thenews.kytranempowerment.com/` (static Nginx, port 8103, VPS)
- Watch products: Civic :8099, Legal :8100, Market :8101, Gov :8102 (all VPS)
- C.R.E.E.D.: creed.kytranempowerment.com (hub, port 8086)
- VPS: 76.13.107.109 with Caddy reverse proxy
