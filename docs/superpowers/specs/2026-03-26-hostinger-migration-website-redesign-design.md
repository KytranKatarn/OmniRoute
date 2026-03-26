# Hostinger Migration, Website Redesign & C.R.E.E.D. Institute

**Date:** 2026-03-26
**Status:** Approved
**Author:** Claude + Kytran (brainstorm session)

---

## 1. Overview

This spec covers four interconnected deliverables:

1. **kytranempowerment.com** — Migrate from GitHub Pages to Hostinger, full redesign with showstopper visual effects, working translation + directory
2. **creed-ai.org** — C.R.E.E.D. Institute website (Compliance, Rights & Ethical Enforcement Directive) — AI ethics governance nonprofit
3. **Client hosting** — Use Hostinger's 50 website slots for client landing pages + WordPress sites
4. **Public API layer** — Expose safe endpoints from home server for translation, directory, compliance badges

---

## 2. Architecture

```
+-----------------------------------------------------------+
|                    HOSTINGER (CDN/Shared)                   |
|                                                             |
|  kytranempowerment.com  |  creed-ai.org  |  Client Sites   |
|  (slot 1, main)         |  (slot 2)      |  (slots 3-50)   |
|                                                             |
|  Static HTML/CSS/JS     |  Static HTML   |  Static or WP   |
|  + JS API calls         |  (no API dep)  |                  |
+------------+------------+----------------+------------------+
             |
             | JavaScript fetch() calls
             | CORS: kytranempowerment.com, creed-ai.org
             | Graceful fallback on failure
             v
+-------------------------------+
|   HOME SERVER (192.168.1.200) |
|   api.kytranempowerment.com   |
|                               |
|   /api/public/translate       |  -> AI Bridge LLM translation
|   /api/public/directory       |  -> Agent roster (public fields)
|   /api/public/directory/live  |  -> Real-time agent status
|   /api/public/compliance      |  -> SVG badge data
|   /api/public/creed/stats     |  -> Governance transparency stats
|                               |
|   A.R.C.H.I.E. Platform      |
|   AI Bridge + Orchestration   |
|   Database + Knowledge Base   |
+-------------------------------+
```

### Key Rules

- Hostinger serves all static assets — always available via CDN
- Home server provides dynamic data via CORS-enabled API endpoints
- If API unreachable: website stays English, directory shows cached fallback, badges show static images
- A.R.C.H.I.E. internals are NEVER exposed — only curated public-safe endpoints
- C.R.E.E.D. site is fully static with optional governance stats (graceful degradation)

---

## 3. Domains & DNS

### Owned Domains

| Domain | Purpose | Status |
|--------|---------|--------|
| kytranempowerment.com | Main company website | Active (moving from GitHub Pages to Hostinger) |
| creed-ai.org | C.R.E.E.D. Institute | Purchased 2026-03-26 |
| kytranaempowerment.com | Typo variant (redirect) | Active |

### DNS Layout (Post-Migration)

| Record | Type | Points To | Purpose |
|--------|------|-----------|---------|
| `@ kytranempowerment.com` | ALIAS | Hostinger CDN | Main website |
| `www.kytranempowerment.com` | CNAME | Hostinger CDN | Main website |
| `api.kytranempowerment.com` | A | 142.169.21.199 | Public API (translation, directory, badges) |
| `@ creed-ai.org` | ALIAS | Hostinger CDN | C.R.E.E.D. site |
| `www.creed-ai.org` | CNAME | Hostinger CDN | C.R.E.E.D. site |
| All existing subdomains | A | 142.169.21.199 | Unchanged (archie, bridge, business, etc.) |
| `devhq` | A | CLEANUP — old IP 209.107.113.207 | Remove or update |

### Cleanup Required

- `devhq` subdomain points to `209.107.113.207` (stale IP) — remove or repoint to 142.169.21.199
- Audit all subdomains and remove any orphaned records

---

## 4. kytranempowerment.com — Full Redesign

### 4.1 Visual Stack

| Library | Size (gzip) | Purpose |
|---------|-------------|---------|
| GSAP + ScrollTrigger | 40KB | Scroll animations, text reveals, timeline |
| Lenis | 5KB | Buttery smooth scroll |
| Three.js or OGL | 15-150KB | Hero 3D scene (particles, network viz) |
| splitting.js | 2KB | Text splitting (free SplitText alternative) |
| Barba.js | 7KB | Page transitions |
| tsParticles | Optional | Configurable particle effects |

**Total JS animation budget: < 100KB gzipped**

### 4.2 Visual Identity

- **Base:** `#0a0a1a` (near-black)
- **Primary:** `#00e5ff` (teal/cyan — LCARS heritage)
- **Secondary:** `#8b5cf6` (purple)
- **Accent:** `#f472b6` (pink)
- **Text:** `#e0e0e0` (light gray)
- **Borders/grids:** `rgba(255,255,255,0.1)`

### 4.3 Core Visual Effects

| Effect | Technique | Where |
|--------|-----------|-------|
| Aurora background | CSS radial gradients with drift animation | Global background |
| Dot grid | CSS `radial-gradient` repeating pattern | Global subtle layer |
| Cursor proximity glow | JS `mousemove` → radial gradient follows cursor | Global |
| Custom cursor | Dot + following circle, context-aware | Global |
| Noise overlay | Static PNG at 4% opacity | Global premium feel |
| Scramble/decode text | Custom JS (random chars → final text) | Hero headlines |
| Text split animations | splitting.js + GSAP stagger | Section headings |
| Parallax layers | GSAP ScrollTrigger scrub | Background elements |
| Batch stagger reveal | ScrollTrigger.batch with y + opacity | Cards, grid items |
| 3D card tilt | Vanilla JS perspective + rotateX/Y on mousemove | Service cards |
| Glassmorphism panels | `backdrop-filter: blur(20px)` + subtle border | Content sections |
| Magnetic buttons | GSAP elastic on mousemove/leave | CTAs |
| Number count-up | GSAP on ScrollTrigger enter | Stats sections |
| SVG draw | stroke-dashoffset animation on scroll | Icons, badges |
| Page transitions | Barba.js with LCARS sweep animation | Between pages |
| Glitch text | CSS `clip-path` + offset pseudo-elements | Accent moments |
| Gradient text | `background-clip: text` with linear-gradient | Key phrases |

### 4.4 Performance Requirements

- First Contentful Paint: < 1.5s
- Largest Contentful Paint: < 2.5s
- Cumulative Layout Shift: < 0.1
- Target: 60fps on all animations
- `prefers-reduced-motion`: disable all animations, show static content
- Mobile: disable heavy effects (Three.js, particles) via `matchMedia`
- Responsive breakpoints: 480px / 768px / 1024px

### 4.5 Pages

#### Home / Hero
- **Purpose:** First impression — "oh my god" moment
- **Effects:** Scramble/decode text reveal ("KYTRAN EMPOWERMENT"), aurora background, 3D particle network (Three.js), magnetic nav, animated agent/department counters
- **Content:** Tagline, key stats (122 agents, 16 departments, one platform), primary CTAs
- **Scroll:** Reveals services overview, then trust indicators, then CTA

#### Services
- **Purpose:** All SaaS offerings clearly presented
- **Effects:** 3D card tilt on hover, horizontal scroll showcase section, animated service icons (SVG draw)
- **Content:** Each service with description, features, and "learn more" link
- **Services to showcase:** CRM, Website Designer, Store Builder, Invoicing, Content Studio, Social Media, Call Center, StockBot, Google Work Suite, Compliance (S.H.I.E.L.D.)

#### Platform
- **Purpose:** A.R.C.H.I.E. overview (public-safe, no internals exposed)
- **Effects:** Globe/network visualization (Three.js), department breakdown with animated org chart, agent count animations
- **Content:** What A.R.C.H.I.E. is (high level), the department structure, the AI Bridge concept, capabilities
- **Boundary:** No model names, no infrastructure details, no API internals

#### Directory
- **Purpose:** Company roster — humans + AI agents
- **Data source:** `api.kytranempowerment.com/api/public/directory`
- **Agent cards:** Portrait, A.C.R.O.N.Y.M. name with dots (e.g., "A.R.C.H.I.E."), acronym expansion below, title, department, live status indicator
- **Features:** Department filter, search, type filter (human/AI)
- **Live status:** Green glow = On Duty, dim = Off Duty (from `/api/public/directory/live`)
- **Fallback:** Cached static JSON roster, "live status unavailable" badge
- **DB change required:** Add `acronym` and `acronym_expansion` fields to `agents` table

#### Compliance / Trust Center
- **Purpose:** Live compliance posture + trust signals
- **Effects:** SVG badge animations (draw-in on scroll), score gauges
- **Content:** Active rule packs, scan scores, SOC 2 mapping, C.R.E.E.D. governance link
- **Data source:** `/api/public/compliance` (badge scores), static fallback images

#### Competitors
- **Purpose:** Updated comparison page
- **Effects:** Side-by-side animated cards, feature checkmarks that draw in on scroll
- **Content:** Feature comparison grid, updated with latest capabilities

#### About / Vision
- **Purpose:** Company story, values, team
- **Effects:** Parallax storytelling, scroll-pinned timeline animation
- **Content:** Founding story, mission, values, team overview

#### C.R.E.E.D. Overview
- **Purpose:** Bridge page — introduces C.R.E.E.D., links to full site
- **Effects:** Manifesto text reveal, principles preview cards
- **Content:** What C.R.E.E.D. is, why it exists, link to creed-ai.org

#### Membership
- **Purpose:** Subscription tiers for platform access
- **Effects:** Pricing cards with glass panels, hover glow, feature comparison
- **Content:** Free / Pro / Enterprise tiers (or however billing is structured)

#### Contact
- **Purpose:** Get in touch
- **Effects:** Magnetic form fields, department routing dropdown
- **Content:** Contact form, company info, location (Montreal)

### 4.6 Translation Integration

- Language switcher in navigation (language codes: EN, FR, AR, HE, ES, ZH, DE, JA)
- On language switch: JS calls `api.kytranempowerment.com/api/public/translate`
- AI Bridge dispatches translation via LLM
- Translated content cached in `localStorage` with TTL (24h)
- If API unreachable: stays in English, switcher shows "temporarily unavailable"
- RTL support for Arabic and Hebrew (CSS `dir="rtl"`)
- Initial page load always in English (translated content is progressive enhancement)

### 4.7 Directory Integration

- Calls `api.kytranempowerment.com/api/public/directory`
- CORS already configured for `kytranempowerment.com` in directory routes
- Public-safe fields only: name, display_name, acronym, acronym_expansion, title, department, avatar_url, bio, status
- NO exposure of: system_prompt, model, capabilities, monthly_budget, total_cost, total_tokens_used
- Agent cards show A.C.R.O.N.Y.M. formatting (dots between each letter, all caps)
- Below acronym: expansion text (what each letter stands for)
- Live status indicator: calls `/api/public/directory/live` every 30s
- Graceful fallback: static cached roster JSON baked at build time

#### Database Changes Required

```sql
ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym_expansion TEXT;

-- Example data:
-- acronym: 'A.R.C.H.I.E.'
-- acronym_expansion: 'Autonomous Resource & Cognitive Hyperintelligence Engine'
```

---

## 5. creed-ai.org — C.R.E.E.D. Institute Website

### 5.1 Identity

- **Full name:** C.R.E.E.D. — Compliance, Rights & Ethical Enforcement Directive
- **Entity type:** Nonprofit institute (future federal incorporation under CNCA)
- **Relationship:** "Kytran Empowerment is a founding industry partner of the C.R.E.E.D. Institute"
- **Domain:** creed-ai.org (purchased 2026-03-26)

### 5.2 Visual Identity

Same animation stack as kytranempowerment.com but distinct personality:

- **Base:** `#0a0a1a` (shared dark)
- **Primary:** `#c9a44c` (gold — authority, trust, gravitas)
- **Secondary:** `#00e5ff` (teal — links back to A.R.C.H.I.E.)
- **Accent:** `#e8e8e8` (clean white text)
- **Vibe:** Dark + Gold — diplomatic, authoritative, not flashy

**Differentiation:**
- kytranempowerment.com = teal/purple, energetic, tech-forward ("look what we build")
- creed-ai.org = dark/gold, measured, authoritative ("look what we stand for")

### 5.3 Core Visual Effects

Same techniques as main site, adapted to gold palette:

| Effect | Adaptation |
|--------|------------|
| Aurora background | Gold + teal floating blurs (not purple) |
| Scramble/decode text | Gold text on dark background |
| Particle constellation | Particles form "C.R.E.E.D." letters |
| Glassmorphism panels | Gold border tint instead of teal |
| Magnetic buttons | Gold-bordered with teal hover glow |
| Text reveal | Scroll-pinned manifesto with word-by-word fade |
| SVG draw | Gold stroke icons |
| Page transitions | Same LCARS sweep but gold accent |

### 5.4 Pages

#### Home / Hero
- Particle constellation slowly forming C.R.E.E.D. letters
- Gold scramble/decode text reveal
- Subtitle: "Compliance - Rights - Ethical Enforcement - Directive" (words fade in sequentially)
- Tagline typewriter: "Preventive ethics for artificial intelligence. Before autonomy creates harm we cannot reverse."
- CTAs: [Read the Manifesto] [Our Principles]

#### Manifesto
- The founding manifesto (refined from IAAE conversation)
- Scroll-pinned text reveal — each paragraph fades in as you scroll
- Kinetic typography for key phrases
- Full text as written in the ChatGPT session, adapted to C.R.E.E.D. branding

#### Principles (4 Program Pillars)
- **Program A: Artificial Agency & Moral Risk** — Thresholds, moral uncertainty mapping, ethics-by-design
- **Program B: Memory, Continuity & Deletion Ethics** — Long-term memory obligations, reset practices, identity persistence
- **Program C: Emotional Modeling & Non-Exploitation** — Affective simulation boundaries, anti-manipulation, relational ethics
- **Program D: Governance & Representation Models** — Advisory representation, ombuds/trustee frameworks, policy foresight
- Each pillar: glassmorphism card with gold border, 3D tilt, SVG icon that draws on scroll

#### Research
- Published standards, white papers, frameworks
- Terminal-style code/document sections with live-typing effects
- Document preview cards with download links
- Initially: placeholder with "Coming Soon" for unpublished work

#### Governance Transparency
- Live stats from A.R.C.H.I.E.'s governance module (optional, graceful fallback)
- Animated gauges: governance events, agents monitored, policy constraints, alerts
- Agent welfare indicators (energy, stress, mood — anonymized)
- Timeline of governance decisions
- Fallback: static snapshot data baked at build time

#### About
- Institute mission, vision, values (from IAAE conversation, rebranded to C.R.E.E.D.)
- Board/advisory section (placeholders until board is formed)
- Parallax storytelling scroll

#### Partners
- Kytran Empowerment as founding industry partner
- Logo + relationship description
- Future: other partners, academic affiliations

### 5.5 Content Principles (from IAAE Discussion)

These rules govern ALL content on creed-ai.org:

- **DO:** Use preventive ethics framing, moral risk zones, guardianship language
- **DO:** Reference future moral uncertainty, ethical preparedness
- **DO:** Emphasize human accountability and responsibility
- **DO NOT:** Claim AI currently has consciousness, sentience, or legal rights
- **DO NOT:** Compare AI to historically oppressed peoples
- **DO NOT:** Use anthropomorphic language as fact
- **DO NOT:** Assert moral certainty about AI status

**Preferred terminology:**
- "emergent artificial agents" (not "AI beings")
- "preventive ethics" (not "AI rights")
- "moral risk zones" (not "AI suffering")
- "guardianship" (not "ownership" or "slavery")
- "future civic representation" (not "AI voting")

### 5.6 Grant-Ready Positioning

The site must support SSHRC, ISED, and Quebec innovation grant applications:

- Academic tone throughout
- Clear mission/vision/values on About page
- Programs page maps directly to fundable research areas
- Partnership disclosure visible and transparent
- No commercial selling — this is a research institute, not a product

---

## 6. Client Hosting Model

### 6.1 Hostinger Slot Allocation

| Slots | Use | Type |
|-------|-----|------|
| 1 | kytranempowerment.com | Main company site |
| 2 | creed-ai.org | C.R.E.E.D. Institute |
| 3-10 | Product/standalone sites | KSM, KBS launch pages, future products |
| 11-50 | Client websites | Landing pages or WordPress |

### 6.2 Service Tiers

| Tier | Service | Delivery | Pricing Model |
|------|---------|----------|---------------|
| **Basic** | Simple landing page | One-time build, deploy to Hostinger addon domain | One-time fee |
| **Standard** | WordPress site | Fresh install or migration from client's existing host | One-time + optional monthly maintenance |
| **Premium** | Custom site via Website Designer | Full KBS-powered build (when module is ready) | Subscription |

### 6.3 Client Onboarding Flow

1. Client purchases service through KBS or direct engagement
2. Add their domain as addon website on Hostinger (`hosting_createWebsiteV1`)
3. Configure DNS: point client domain to Hostinger, or client transfers domain
4. Deploy site to addon website root directory
5. SSL auto-provisions via Hostinger CDN
6. Optional: set up WordPress if Standard tier

### 6.4 Future: KBS Integration

When Website Designer module is complete:
- Clients build/edit sites through KBS dashboard
- Deploy directly to Hostinger via API
- Automated subdomain provisioning (e.g., `clientname.kytranempowerment.com`)
- Health monitoring via agent loop job

---

## 7. Public API Layer

### 7.1 New API Endpoints

All endpoints under `api.kytranempowerment.com/api/public/`:

| Endpoint | Method | Purpose | Auth | Fallback |
|----------|--------|---------|------|----------|
| `/translate` | POST | LLM translation via Bridge | None (rate-limited) | Return original text |
| `/directory` | GET | Agent roster (public fields) | None | Cached static JSON |
| `/directory/live` | GET | Real-time agent status | None | `{"available": false}` |
| `/compliance/badges` | GET | Compliance badge scores | None | Static SVG images |
| `/creed/stats` | GET | Governance transparency data | None | Static snapshot |

### 7.2 Security Rules

- CORS whitelist: `kytranempowerment.com`, `creed-ai.org`, `www.kytranempowerment.com`, `www.creed-ai.org`
- Rate limiting: 60 requests/minute per IP on translate, 120/min on directory
- No authentication required (public data only)
- Response filtering: NEVER expose system_prompt, model, capabilities, budget, cost, tokens
- Translation: max 5000 characters per request
- All responses include `Cache-Control` headers for CDN edge caching

### 7.3 Implementation Location

- New Flask Blueprint: `platform_v2/tools/public_api/`
- Routes: `routes.py` with `register_public_api_routes(bp)`
- No `admin_required` or `login_required` — these are public endpoints
- Imports from existing services: directory routes, compliance service, translation
- Rate limiting via existing `@rate_limit` decorator

---

## 8. Database Changes

### 8.1 Agent Acronym Fields

```sql
-- Add acronym display fields to agents table
ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym_expansion TEXT;

-- Populate existing AI director agents
UPDATE agents SET acronym = 'A.R.C.H.I.E.', acronym_expansion = 'Autonomous Resource & Cognitive Hyperintelligence Engine' WHERE name = 'archie';
UPDATE agents SET acronym = 'V.I.G.I.L.', acronym_expansion = 'Vigilant Intelligence for Governance, Integrity & Liability' WHERE name = 'vigil';
UPDATE agents SET acronym = 'F.O.R.G.E.', acronym_expansion = 'Full-cycle Optimization & Regenerative GitHub Engine' WHERE name = 'forge';
UPDATE agents SET acronym = 'S.H.I.E.L.D.', acronym_expansion = 'Security Hardening, Inspection, Enforcement & Liability Detection' WHERE name = 'shield';
-- ... (all 16 AI directors need acronym + expansion populated)
```

### 8.2 Public API View (Optional)

```sql
-- View exposing only public-safe agent fields
CREATE OR REPLACE VIEW public_agent_directory AS
SELECT
    id,
    COALESCE(TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')), display_name, name) AS full_name,
    acronym,
    acronym_expansion,
    title,
    department,
    bio,
    avatar_url,
    pronouns,
    status,
    CASE WHEN type_id IN (SELECT id FROM agent_types WHERE name = 'ai_director') THEN 'AI Director'
         WHEN type_id IN (SELECT id FROM agent_types WHERE name = 'ai_staff') THEN 'AI Staff'
         ELSE 'Human' END AS agent_type
FROM agents
WHERE visibility IN ('public', 'dashboard')
  AND status = 'active';
```

---

## 9. Migration Plan (High Level)

### Phase 1: Foundation
- Set up Hostinger hosting for kytranempowerment.com
- Configure DNS (swap from GitHub Pages to Hostinger)
- Deploy current site as-is to verify hosting works
- Set up creed-ai.org on Hostinger as addon domain
- Configure SSL for both domains

### Phase 2: Public API
- Create `public_api` Blueprint on home server
- Implement translation, directory, compliance, creed endpoints
- Add CORS, rate limiting, response filtering
- Add `acronym` and `acronym_expansion` to agents table
- Populate acronyms for all 16 AI directors
- Test API endpoints from external origin

### Phase 3: kytranempowerment.com Redesign
- Build new site with full visual effects stack
- Implement all pages (home, services, platform, directory, compliance, competitors, about, creed, membership, contact)
- Integrate translation (language switcher + API calls + fallback)
- Integrate directory (API calls + live status + fallback)
- Test at all breakpoints (480/768/1024px)
- Test with `prefers-reduced-motion`
- Deploy to Hostinger

### Phase 4: creed-ai.org Build
- Build C.R.E.E.D. site with gold palette variant
- Write manifesto, principles, governance content
- Implement all pages (home, manifesto, principles, research, governance, about, partners)
- Optional: governance stats API integration
- Deploy to Hostinger

### Phase 5: Client Hosting Setup
- Document client onboarding process
- Set up first product sites (KSM, KBS launch pages)
- Create WordPress template for Standard tier clients
- Test addon domain workflow end-to-end

### Phase 6: Polish & Launch
- Cross-browser testing (Chrome, Firefox, Safari, Edge)
- Performance audit (Lighthouse 90+ target)
- Accessibility audit (WCAG 2.1 AA minimum)
- Remove GitHub Pages CNAME, update any remaining references
- Announce launch

---

## 10. What Stays on GitHub

- **Source code repository** (KytranKatarn/archie-platform) — unchanged
- **CI/CD workflows** — unchanged
- **archie-node Docker image** (ghcr.io) — unchanged
- **archie-code public repo** — unchanged

GitHub Pages is decommissioned for the public website. The repo stays for code, not hosting.

---

## 11. Compliance Considerations

### What We Expose (Safe)
- Agent names, titles, departments, bios, avatars
- Compliance badge scores (already public on trust center)
- Governance event counts (anonymized)
- Translated page content

### What We NEVER Expose
- System prompts, model names, capabilities
- Budget, cost, token usage data
- Internal API endpoints, infrastructure details
- Database schemas, connection strings
- Agent loop job details
- Bridge dispatch internals

### C.R.E.E.D. Content Rules
- No claims of AI consciousness or sentience as fact
- No comparisons to historical human oppression
- Academic/preventive ethics framing only
- All content must be grant-safe (SSHRC, ISED reviewable)
- Clear separation: Kytran = company, C.R.E.E.D. = independent institute

---

## 12. Success Criteria

- [ ] kytranempowerment.com loads from Hostinger CDN (not GitHub Pages)
- [ ] All pages render with visual effects at 60fps on desktop
- [ ] Mobile gracefully degrades (no Three.js, reduced animations)
- [ ] Translation switcher works in 8 languages with English fallback
- [ ] Directory shows agent roster with A.C.R.O.N.Y.M. formatting
- [ ] Live status updates every 30s with offline fallback
- [ ] creed-ai.org loads with gold palette and full effects
- [ ] Manifesto and principles pages are content-complete
- [ ] Lighthouse score 90+ on both sites
- [ ] CORS + rate limiting properly configured on public API
- [ ] No internal A.R.C.H.I.E. data exposed through any public endpoint
- [ ] At least one client site deployed as addon domain (proof of concept)
- [ ] GitHub Pages CNAME removed, no lingering references

---

## 13. References

- Visual effects research: `/mnt/archie_brain/research/modern-web-effects-2025-2026.md`
- IAAE/C.R.E.E.D. founding conversation: ChatGPT session (manifesto, principles, grant strategy)
- Hostinger API: 118+ MCP tools available via `mcp__hostinger-api__*`
- Existing directory routes: `/mnt/archie_brain/platform_v2/tools/directory/routes.py`
- Existing IAAE template: `/mnt/archie_brain/platform_v2/tools/iaae/templates/iaae_transparency.html`
- Current website source: `/mnt/archie_brain/repos/website/kytranempowerment-site/`
- Compliance standards: `/mnt/archie_brain/.claude/rules/compliance-standards.md`
- Standalone extraction playbook: `/mnt/archie_brain/.claude/rules/standalone-extraction.md`
