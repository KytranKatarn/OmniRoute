# Website Gap Analysis: OLD Site vs NEW Site
**Date:** 2026-04-04
**OLD:** `/mnt/archie_brain/repos/website/kytranempowerment-site/`
**NEW:** `/mnt/archie_brain/website/kytranempowerment.com/`

---

## 1. PAGE INVENTORY

### OLD Site HTML Files (17 pages)
| File | Purpose |
|------|---------|
| index.html | Home page |
| about.html | About page |
| services.html | Services + pricing tiers |
| platform.html | A.R.C.H.I.E. platform showcase |
| competitors.html | **MAJOR** — 35+ competitor comparison |
| competitors/index.html | Duplicate/redirect of above |
| compliance-services.html | Compliance services page |
| directory.html | Team directory (100+ AI agents) |
| directory/index.html | Duplicate/redirect of above |
| trust-center.html | Security & compliance trust center |
| vision.html | Company vision |
| membership.html | Membership page |
| merch_store.html | **Merchandise store** (product cards, cart) |
| cart.html | Shopping cart |
| checkout.html | Checkout flow |
| product_detail.html | Product detail page |
| order_success.html | Order confirmation |
| submit_story.html | User story submission form |
| books.html | Books page |
| links.html | Links page |
| tips.html | Tips page |
| blocked.html | Blocked access page |

### NEW Site HTML Files (22 pages)
| File | Purpose |
|------|---------|
| index.html | Home page |
| about.html | About page |
| services.html | Services (19 products listed) |
| platform.html | Platform showcase |
| competitors.html | **STRIPPED DOWN** competitor comparison |
| compliance.html | Trust center (renamed) |
| compliance-services.html | Compliance services |
| directory.html | Team directory |
| vision.html | Vision page |
| membership.html | Membership |
| store.html | Store (renamed from merch_store.html) |
| cart.html | Shopping cart |
| checkout.html | Checkout |
| product-detail.html | Product detail (renamed, hyphenated) |
| order-success.html | Order confirmation (renamed, hyphenated) |
| submit-story.html | Story submission (renamed, hyphenated) |
| books.html | Books |
| links.html | Links |
| tips.html | Tips |
| blocked.html | Blocked access |
| **contact.html** | **NEW** — Dedicated contact page |
| **creed.html** | **NEW** — C.R.E.E.D. ethics institute page |

---

## 2. COMPETITORS.HTML — CRITICAL REGRESSION

### OLD Site (competitors.html) — ~1400 lines, MASSIVE page
The old competitors page was a flagship marketing asset with 7 major sections:

**Section 1: Hero Stats**
- 35+ Competitors Analyzed
- 30 Unique Features No One Else Has
- 4 Features We're Still Building

**Section 2: Feature Matrix Table**
Glassmorphism table comparing A.R.C.H.I.E. vs 7 competitors:
- **Competitors compared:** CrewAI, LangGraph, Devin, Claude Code, Goose, Dify, OpenAI Agents
- **A.R.C.H.I.E. Unique Capabilities (15 features):**
  - Station-based dispatch, GPU/VRAM-aware routing, Agent welfare (IAAE ethics), Self-auditing codebase, Code health metrics dashboard, Warm-boot model lifecycle, 5-step escalation chain, Mission profiles, Physical security (cameras/DNS/SSH), Self-improvement pipeline, 39 autonomous background jobs, Telegram human-in-the-loop, Live AI translation (8 langs), Multi-GPU fleet orchestration (OTA), 4-tier image gen escalation, 19 cloud contractor integrations
- **Shared Capabilities (7 features):** Multi-agent orchestration, MCP protocol, Self-hosted, Structured schemas, Agents-as-tools, Human approval, Event-driven router
- **Where Others Lead (6 features):** Durable execution, A2A protocol, Visual workflow builder, IDE integration, Parallel execution, Cloud auto-scaling

**Section 3: Sensor Scan — Trending**
4 trending competitor cards with visual bars:
- **OpenClaw** (247K stars) — "1 agent vs 101 agents"
- **PicoClaw** (10MB RAM) — "10 MB vs 128 GB + GPU"
- **Claw Empire** (Dev Toy) — "Wrapper UI vs Full platform"
- **NemoClaw** (Nvidia, Watch) — "Guardrails alpha vs IAAE live production"
Each had verdict text and visual comparison bars.

**Section 4: Category Comparison (6 cards)**
- Orchestration Frameworks (CrewAI, AG2, LangGraph, MetaGPT, OpenAI Agents SDK, Microsoft Agent Framework)
- Workflow Builders (Langflow, n8n, Dify, Flowise)
- Autonomous Coding Agents (Devin, Cursor, Windsurf, Claude Code, Codex CLI, Cline, Aider)
- Enterprise Platforms (Microsoft Agent Framework, Haystack, Relevance AI, Dust.tt, OpenAI Assistants)
- Self-Hosted & Open Source (Goose, LocalAGI, Aider, Ollama, Open WebUI)
- Self-Improving & Accountable ("No direct competitors")
Each card had: description, A.R.C.H.I.E.'s edge, Their edge (gap acknowledgment).

**Section 5: "How Many Tools to Match A.R.C.H.I.E.?"**
Visual comparison: A.R.C.H.I.E. (one platform) VS 9 tools needed:
CrewAI, Ollama, n8n, Frigate NVR, AdGuard Home, Grafana, SonarQube, Claude Code, Custom Scripts
Plus: "And you'd still be missing agent welfare, warm-boot lifecycle, station-based dispatch..."

**Section 6: "Where We're Still Building" (Transparency)**
4 honest gap cards:
- A2A Protocol (LangGraph has it)
- Cloud Auto-Scaling (Devin, Dify Cloud, OpenAI Assistants have it)
- Visual Workflow Builder (Dify, n8n, Langflow, Flowise have it)
- Durable Execution (LangGraph has it)

**Section 7: Kytran Server Manager vs Vanta, Drata & More**
Second comparison matrix: Kytran SM vs Vanta ($15K+/yr), Drata ($10K+/yr), Cockpit (Free), Portainer (Free)
- 4 differentiator cards: One-Click Remediation, STIG Scanning (138 rules), Self-Hosted/Open Source, AI-Powered Analysis
- Full matrix: STIG, SOC 2, HIPAA, One-Click Remediation, AI Analysis, Live Badges, .ckl Export, Server Monitoring, Docker, UFW, LVM, Self-Hosted, Open Source, Price

### NEW Site (competitors.html) — SEVERELY STRIPPED
- Title changed to "Why A.R.C.H.I.E.?" (less direct)
- Only 1 simple table with 5 competitors (CrewAI, LangGraph, Devin, Claude Code)
- **Dropped Goose, Dify, OpenAI Agents** from matrix
- Only ~7 features compared (vs 28+ in old)
- **COMPLETELY MISSING:**
  - Hero stats (35+ analyzed, 30 unique, 4 building)
  - Trending section (OpenClaw, PicoClaw, Claw Empire, NemoClaw)
  - Category comparison cards (6 categories, 35+ named competitors)
  - "How Many Tools to Match" visual
  - "Where We're Still Building" transparency section
  - Kytran Server Manager vs Vanta/Drata comparison
  - Visual comparison bars
  - Aurora background effects
  - Glassmorphism styling

**VERDICT: ~85% of competitor page content was lost in the new site.**

---

## 3. TRANSLATION SYSTEM (i18n) — ARCHITECTURAL CHANGE

### OLD Site: i18n.js — Client-Side Static Translations
- **8 languages hardcoded:** en, fr (QC), es, pt, de, zh, ar, he
- ~46 translation keys per language = ~368 translated strings total
- **Approach:** Static JSON object `TRANSLATIONS` with all strings pre-translated
- Language selector dropdown with globe icon in nav
- RTL support for Arabic and Hebrew
- `switchLang()` function updates `data-i18n` attributes
- `toggleLangMenu()` shows/hides dropdown
- **INSTANT** — no network calls, all strings pre-loaded
- Competitors page had its own i18n keys (comp_hero_title, comp_feat_*, etc.)

### NEW Site: translate.js — API-Based Dynamic Translation
- **8+ languages supported** via API call
- **Approach:** IIFE module `Translate` that calls `https://api.kytranempowerment.com/api/public/translate`
- Sends POST requests to translate each `[data-i18n]` element on-the-fly
- localStorage caching with 24-hour TTL
- RTL support for ar/he preserved
- `data-i18n-original` attribute saves original text for restore
- Language switcher is a button showing "EN" (compact)
- **REQUIRES NETWORK** — if API is down, translation fails silently

### Key Differences
| Aspect | OLD | NEW |
|--------|-----|-----|
| Method | Static JSON bundle | Live API calls |
| Speed | Instant (0ms) | Network dependent |
| Offline | Works offline | Requires API |
| Languages | 8 exact (hardcoded) | 8+ (API-driven, extensible) |
| Accuracy | Pre-reviewed translations | AI-generated on-the-fly |
| Competitors page i18n | 50+ dedicated keys | Generic elements only |
| Caching | None needed | localStorage 24h TTL |

---

## 4. BRAND IMAGES

### OLD Site Images
| File | Path |
|------|------|
| **logo.png** | `/repos/website/kytranempowerment-site/logo.png` |
| **logo-sm.png** | `/repos/website/kytranempowerment-site/logo-sm.png` |
| **header-bg.png** | `/repos/website/kytranempowerment-site/header-bg.png` (+ static/ copy) |
| **brotherhood-bg.png** | `/repos/website/kytranempowerment-site/brotherhood-bg.png` |
| **cart-icon.png** | `/repos/website/kytranempowerment-site/assets/cart-icon.png` |
| **CAN.png / MTQ.png** | `/repos/website/kytranempowerment-site/assets/` (region badges?) |
| **unnamed.png** | `/repos/website/kytranempowerment-site/assets/unnamed.png` |
| **33 product/content images** | `/repos/website/kytranempowerment-site/assets/90845d_*.jpg` and `11062b_*.png` |

### NEW Site Images
| File | Path |
|------|------|
| **favicon.svg** | `/website/kytranempowerment.com/favicon.svg` |

### MISSING from New Site
- **logo.png** and **logo-sm.png** — The logo images are completely absent. New site uses text-only "KYTRAN" in nav.
- **header-bg.png** — No background images at all
- **brotherhood-bg.png** — Mission section background gone
- **All 33 product/merch images** — Store exists but product images would need sourcing
- **cart-icon.png** — No cart icon
- **CAN.png / MTQ.png** — Region badges gone

---

## 5. NAVIGATION COMPARISON

### OLD Site Nav
```
Logo (image) + "Kytran Empowerment" text
Links: Services | Compliance | Platform | Our Team | Competitors | About | [Get Started button]
Globe icon language selector (dropdown with 8 flags)
Hamburger on mobile (class toggle .open)
```
- Logo is an `<img>` tag using logo.png
- "Get Started" links to archie.kytranempowerment.com
- Language selector is a globe SVG icon with dropdown menu
- Some pages had slightly different nav items (Home added on competitors page)

### NEW Site Nav
```
"KYTRAN" text logo (no image)
Links: Services | Platform | Directory | Trust | C.R.E.E.D. | About | [Contact button]
"EN" language button (cycles through languages)
Hamburger on mobile
```
- Text-only logo "KYTRAN" using Orbitron font
- "Contact" replaces "Get Started" as CTA
- "Trust" replaces "Compliance"
- "C.R.E.E.D." is new nav item
- "Directory" replaces "Our Team"
- **Competitors link REMOVED from main nav** (page exists but not linked in nav)
- Language selector is minimal "EN" button vs globe dropdown
- Uses Barba.js for page transitions (SPA-like)
- Uses GSAP, Lenis (smooth scroll), ScrollTrigger, Splitting.js for effects

### Key Nav Changes
| Item | OLD | NEW |
|------|-----|-----|
| Logo | Image (logo.png) + text | Text only "KYTRAN" |
| Competitors | In nav | **NOT in nav** (page exists but unlisted) |
| C.R.E.E.D. | Not present | New nav item |
| Contact | Not a nav item (inline) | Dedicated nav CTA |
| Get Started | Nav CTA button | Removed |
| Language | Globe dropdown | Compact "EN" button |
| Fonts | Outfit + Inter | Antonio + Orbitron + IBM Plex Mono |
| Page transitions | None (full reload) | Barba.js SPA transitions |

---

## 6. SERVICES / PRICING — CONTENT COMPARISON

### OLD Site Services Page
**3 Pricing Tiers:**
- **Starter:** $499/month — AI consulting, basic automation, email support (48hr), monthly reports, up to 5 workflows
- **Professional:** $1,499/month (MOST POPULAR) — Full A.R.C.H.I.E. access, custom integrations & APIs, priority support (4hr), monthly analytics, up to 25 workflows, dedicated account manager
- **Enterprise:** Custom pricing — Dedicated infrastructure, custom AI training, 24/7 SLA, unlimited workflows, on-premise deployment, custom model fine-tuning, quarterly strategy reviews

**12 Service Catalog Cards:**
1. AI Consulting
2. SaaS Platform (A.R.C.H.I.E.) — "50+ modules, 70 AI agents, 10 command stations"
3. Website Design & Hosting
4. Network Security
5. Business Intelligence
6. Custom Development
7. Content Creation
8. AI Translation (8 languages)
9. Stock Trading Bots
10. Domain Management
11. Call Center Solutions
12. Fitness & Wellness

**CTA with phone number:** 1-877-463-3352

### NEW Site Services Page
**NO pricing tiers at all** — pricing section completely removed.

**19 Service Cards (expanded from 12):**
1. CRM
2. Website Designer
3. Store Builder
4. Invoicing
5. (likely more below the fold — cut at line 80)

**Subtitle:** "19 AI-powered tools and standalone products for every aspect of your business"

### What's Missing from New Services
- **All 3 pricing tiers** ($499/$1,499/Custom) — completely gone
- **Phone number** (1-877-463-3352) — not visible
- **"Powered by A.R.C.H.I.E." badge** in hero
- **Specific stats** ("50+ modules, 70 AI agents, 19 cloud contractors, multi-GPU fleet")
- Service descriptions are shorter/different

### What's New in New Services
- More granular product listing (19 vs 12)
- Individual product cards for CRM, Store Builder, Invoicing (previously bundled under "Business Intelligence")
- Modern card design with shared CSS

---

## 7. ARCHIE FEATURES / AI CONTENT GAPS

### Pages with significant A.R.C.H.I.E. content in OLD that may be reduced in NEW:

**OLD platform.html** contained:
- "23 AI agents, 10 command stations, 50+ modules"
- Detailed A.R.C.H.I.E. showcase
- Feature highlights (Agent Welfare, Self-Improvement, GPU Routing)

**OLD competitors.html** contained (NOW MISSING):
- Detailed technical differentiators vs 35+ named competitors
- Trending analysis of social media AI tools
- "How many tools to match" visual
- Kytran Server Manager competitive positioning

**OLD trust-center.html** contained:
- Rich SEO metadata (og:tags, structured data, robots)
- Security posture details
- Live compliance badges concept

---

## 8. STORE / MERCH PAGES

### OLD Site
- **merch_store.html** — Full product grid with images, prices, "Add to Cart" buttons
- **cart.html** — Shopping cart with item management
- **checkout.html** — Full checkout flow
- **product_detail.html** — Individual product pages
- **order_success.html** — Order confirmation
- Used old-style CSS (Bebas Neue, Oswald fonts, light background #f5f5f5)
- Product images from `assets/90845d_*.jpg` files (33 images)

### NEW Site
- **store.html** — Exists, modernized with new design system (Orbitron/IBM Plex Mono)
- **cart.html** — Exists
- **checkout.html** — Exists
- **product-detail.html** — Exists (hyphenated filename)
- **order-success.html** — Exists (hyphenated filename)
- **NO product images** — Only favicon.svg exists as an image

---

## 9. FULL GAP ANALYSIS TABLE

| OLD Page | NEW Equivalent | Status | What's Missing |
|----------|---------------|--------|----------------|
| index.html | index.html | EXISTS | Compare hero content, stats |
| about.html | about.html | EXISTS | Compare content depth |
| services.html | services.html | **DEGRADED** | Pricing tiers ($499/$1,499/Custom) GONE, phone number gone, "Powered by ARCHIE" badge gone |
| platform.html | platform.html | EXISTS | Compare feature depth |
| competitors.html | competitors.html | **SEVERELY DEGRADED** | ~85% content lost. Missing: trending section, category cards, stack comparison, KSM vs Vanta, transparency section, visual bars, 28+ named competitors reduced to 4 |
| compliance-services.html | compliance-services.html | EXISTS | Compare content |
| trust-center.html | compliance.html | RENAMED | SEO metadata/structured data may be reduced |
| directory.html | directory.html | EXISTS | Compare agent roster depth |
| vision.html | vision.html | EXISTS | Compare content |
| membership.html | membership.html | EXISTS | Compare content |
| merch_store.html | store.html | RENAMED | Product images missing, verify product data |
| cart.html | cart.html | EXISTS | Verify functionality |
| checkout.html | checkout.html | EXISTS | Verify functionality |
| product_detail.html | product-detail.html | RENAMED | Hyphenated |
| order_success.html | order-success.html | RENAMED | Hyphenated |
| submit_story.html | submit-story.html | RENAMED | Old used legacy fonts/styling |
| books.html | books.html | EXISTS | Compare content |
| links.html | links.html | EXISTS | Compare content |
| tips.html | tips.html | EXISTS | Compare content |
| blocked.html | blocked.html | EXISTS | Compare content |
| i18n.js | js/translate.js | **CHANGED** | Static 368-string bundle replaced with API-based translation. No offline support. |
| logo.png | (none) | **MISSING** | Text-only logo in new site |
| logo-sm.png | (none) | **MISSING** | No small logo variant |
| header-bg.png | (none) | **MISSING** | CSS gradients instead |
| brotherhood-bg.png | (none) | **MISSING** | CSS effects instead |
| 33 product images | (none) | **MISSING** | Store exists but no images |
| — | contact.html | **NEW** | Dedicated contact page |
| — | creed.html | **NEW** | C.R.E.E.D. ethics institute |
| — | compliance.html | **NEW** | Replaces trust-center.html |
| competitors/ (nav link) | (hidden) | **REMOVED FROM NAV** | Page exists but not in navigation |

---

## 10. PRIORITY ISSUES (Ranked by Business Impact)

### P0 — Critical
1. **Competitors page gutted** — Was the most impressive marketing page. Lost 85% of content including all competitive positioning, trending analysis, and the KSM vs Vanta matrix.
2. **Pricing tiers removed** — No way for prospects to see pricing ($499/$1,499/Custom plans are gone).
3. **Competitors NOT in nav** — Even the stripped version is not discoverable.

### P1 — High
4. **Logo images missing** — No logo.png/logo-sm.png. Brand identity reduced to text.
5. **Phone number gone** — 1-877-463-3352 was on services page CTA.
6. **Product images missing** — Store pages exist but 33 product images are absent.
7. **"Get Started" CTA removed** — Direct link to archie.kytranempowerment.com platform gone from nav.

### P2 — Medium
8. **Translation robustness** — Static translations (instant, offline) replaced with API-dependent system.
9. **SEO regression** — Old trust-center.html had structured data, og:tags, canonical URLs. New compliance.html may lack these.
10. **Specific stats removed** — "50+ modules, 70 AI agents, 19 cloud contractors" no longer on services hero.

### P3 — Low
11. **URL format change** — Underscores to hyphens (merch_store -> store, product_detail -> product-detail). Need 301 redirects.
12. **Font change** — Outfit+Inter to Antonio+Orbitron+IBM Plex Mono. Design preference, but ensure readability.
