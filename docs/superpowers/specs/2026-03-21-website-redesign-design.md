# Website Redesign — Cyberpunk Aurora Design Spec

**Date**: 2026-03-21
**Project**: Website & Directory Professional Rebrand (#166)
**Decisions**: #249 (Unified Module Architecture), #250 (Vigil Org Structure)
**Status**: Approved

---

## Overview

Complete redesign of www.kytranempowerment.com, /directory.html, and /competitors.html with a Cyberpunk Aurora visual direction. Maximum wow factor with flowing gradients, glassmorphism, GSAP scroll animations, and sci-fi energy — while maintaining classic, government-friendly org chart structure. All pages are static HTML on GitHub Pages calling the platform API for live data.

## Target Audience

Multi-audience: potential clients (services/pricing), tech community (architecture/capability), investors/partners (scale/vision), and government procurement (clear org hierarchy, accountability).

## Design System

### Visual Direction: Cyberpunk Aurora

- **Background**: Animated aurora gradient blobs (purple #8b5cf6, cyan #00d4ff, blue #0099ff) on dark navy (#0a0e17), with film grain texture overlay
- **Cards**: Glassmorphism — `backdrop-filter: blur(12px)`, semi-transparent backgrounds, subtle borders
- **Typography**: Outfit (headings, 800/700/600 weights), Inter (body, 300-600 weights)
- **Colors**: Cyan #00d4ff (primary accent), Blue #0099ff (CTA), Purple #8b5cf6 (secondary), Gold #f0c040 (CEO/highlight), Green #10b981 (online/success)
- **Spacing**: clamp()-based responsive padding, 120px section padding desktop
- **Borders**: Subtle rgba(255,255,255,0.08) borders with hover glow transitions

### Animation Stack

| Effect | Library | Where Used |
|--------|---------|-----------|
| Scroll-triggered reveals | GSAP ScrollTrigger | All sections |
| Typewriter text | Custom JS | Hero headline |
| Aurora gradient blobs | CSS @keyframes | Background (full page) |
| Counter animations | GSAP/ScrollTrigger | Live stats section |
| Parallax layers | GSAP ScrollTrigger | Hero, CTA backgrounds |
| Magnetic buttons | Custom JS | CTA buttons |
| Lenis smooth scroll | Lenis library | Global |
| Staggered fade-in | GSAP stagger | Cards, team grid |
| Gradient text shift | CSS @keyframes | Hero h1 |
| Pulse/glow | CSS @keyframes | Status dots, badges |

### Performance Rules

- All animations GPU-accelerated (transform, opacity only)
- `prefers-reduced-motion: reduce` disables all animations
- GSAP loaded from CDN with defer
- Images lazy-loaded with `loading="lazy"` + srcset
- Critical CSS inlined, non-critical deferred
- Target: Lighthouse Performance 90+

## Pages

### 1. Homepage (index.html) — 12 Sections

**Section 1: Hero**
- Animated aurora blob background (3 blobs, CSS keyframes)
- Frosted glass nav bar (fixed, backdrop-filter blur)
- Live status badge: "Platform Online — X Agents Active" (green pulse dot)
- Typewriter headline: "Build the Future with AI-Powered Intelligence" + blinking cursor
- Gradient-shifting animated text on key phrase
- Subtitle: "107 AI agents. 10 specialized stations. One unified platform."
- Dual CTA: "Explore the Platform" (gradient primary) + "Meet Our Team" (ghost secondary)
- Glassmorphism stat cards: Agents (107), Online Now (live), Stations (10), Fleet Nodes (2)
- Scroll indicator arrow (bounce animation)
- Data source: `/api/directory/live-status` for online count

**Section 2: Social Proof Bar**
- Scrolling marquee of technology/integration logos
- Logos: Ollama, ComfyUI, PostgreSQL, Flask, Headscale, Tailscale, Docker, Python, GSAP
- Subtle glow on hover, grayscale → color transition
- Infinite scroll CSS animation

**Section 3: Services — Glassmorphism Cards**
- 4 cards: AI Consulting, SaaS Platform, Fleet Orchestration, Creative Studio
- Each: icon, title, description, hover lift + border glow
- GSAP staggered scroll-in (0.15s delay between cards)
- Cards use glassmorphism treatment

**Section 4: Platform Showcase — Interactive Demo**
- Tabbed interface: Bridge Command, Agent Roster, Starship Fleet, Dev HQ
- Each tab shows animated screenshot/mockup of that platform section
- Tab switching with crossfade animation
- "See it in action" headline
- Link to platform login

**Section 5: Live Stats — Counter Dashboard**
- Animated counters from live API: agents online, total agents, knowledge entries, fleet nodes
- Numbers count from 0 → final value on scroll into viewport
- Glassmorphism stat cards with subtle pulse border
- Green live-dot on real-time values
- Data source: `/api/directory/live-status` + platform stats

**Section 6: Meet the Team — Mini Org Chart + Grid**
- Compact 2-level org chart: CEO → ARCHIE (8 stations) + Vigil (security/devops right-branch)
- Classic 1960s tree style with clear connecting lines
- Click to expand/collapse branches
- 3-4 featured agent cards with portraits + live status dots
- "View Full Team" link → /directory.html
- Data source: `/api/directory/org-chart`

**Section 7: Why ARCHIE — Competitor Teaser**
- "It takes 7+ tools to match what ARCHIE does in one"
- Mini feature matrix: 6 key features, green checks for ARCHIE, X for competitors
- "See Full Comparison" link → /competitors.html
- GSAP scroll-in animation

**Section 8: Mission — Mental Health Impact**
- "Profits Support Men's Mental Health"
- Background shifts to warmer tones (gold/amber gradient)
- Emotional, authentic copy about the mission
- Parallax background effect
- Distinct visual break from tech sections

**Section 9: Testimonials / Use Cases**
- Rotating cards with quotes or case study previews
- Placeholder structure for now (important for SEO/AIO)
- Auto-rotate with manual navigation dots
- Glassmorphism card treatment

**Section 10: FAQ — AI-Optimized**
- Accordion with 6-8 questions
- JSON-LD FAQ schema markup (critical for AIO/Google AI Overview)
- Questions: "What is ARCHIE?", "How does AI orchestration work?", "How many AI agents?", "Is it self-hosted?", "What about data privacy?", "How is it different from ChatGPT?"
- Smooth expand/collapse animation

**Section 11: Final CTA**
- Full-width gradient background (aurora treatment)
- Bold headline: "Ready to Command Your AI Fleet?"
- Dual buttons: "Get Started" + "Book a Demo"
- Parallax background effect

**Section 12: Footer**
- Nav links: Services, Platform, Our Team, Competitors, About, Contact
- Social media links
- Contact info, newsletter signup input
- Organization JSON-LD schema
- Copyright + "Powered by A.R.C.H.I.E."

### 2. Directory (directory.html) — Full Org Chart + Team Grid

- Same Cyberpunk Aurora design system as homepage
- Hero: "Our Team" + live stats
- Full expandable org chart (classic tree):
  - CEO (Kytran) at top
  - ARCHIE pyramid downward — 8 station leads, each expandable to show full team
  - Vigil right-branch — 13 reports (Security, Compliance, Privacy, DevOps, IT)
  - Clear connecting lines (horizontal bars + vertical drops)
  - Click to expand/collapse any branch
  - Green/gray status dots
- Department card grid below org chart (current functionality preserved)
- Search + department filter
- Profile slide-out panel on click
- Realistic business headshot portraits (ComfyUI generated)
- Live status from `/api/directory/live-status`
- No AI/Human labels on public view

### 3. Competitors (competitors.html)

- Same Cyberpunk Aurora design system
- Feature matrix (28 rows x 8 competitors)
- Category comparison cards
- Stack comparison
- Roadmap section
- JS-computed stardate
- All data-i18n attributes preserved

## SEO / AIO Strategy

### Meta Tags (all pages)
- Title, description, canonical URL
- Open Graph: og:title, og:description, og:image, og:url, og:type
- Twitter Card: summary_large_image

### Structured Data (JSON-LD)
- **Organization**: name, url, logo, contactPoint, sameAs (social links)
- **SoftwareApplication**: ARCHIE platform details
- **FAQPage**: FAQ section questions/answers
- **WebSite**: searchAction potential

### Semantic HTML
- Proper heading hierarchy: h1 → h2 → h3
- `<main>`, `<section>`, `<article>`, `<nav>`, `<footer>` elements
- ARIA labels on interactive elements
- Alt text on all images
- `lang="en"` attribute

### Performance
- Lazy loading on all images
- srcset for responsive images
- Inline critical CSS
- Deferred script loading
- Target: Lighthouse 90+ across all categories

## Accessibility (WCAG AA)

- `prefers-reduced-motion: reduce` — all animations disabled/simplified
- Visible focus states on all interactive elements (`:focus-visible`)
- Keyboard navigation for org chart (Enter to expand, Escape to collapse)
- Color contrast minimum 4.5:1 for text
- Skip-to-content link
- Screen reader friendly org chart (aria-expanded, role="tree")

## Agent Portraits

- Generated via ComfyUI SDXL on RTX 3070 node
- Style: realistic professional business headshots
- Attire: suit/blazer, corporate
- Background: neutral gray studio
- Demographics: matched to agent name/pronouns for diversity
- Resolution: 512x512 or 768x768
- Stored: `/static/media/portraits/{agent_code_name}.png`
- DB: `agents.avatar_url` updated

## Org Chart Hierarchy (Decision #250)

```
Kytran Tran (CEO)
├── A.R.C.H.I.E. (AI Director) — pyramid downward
│   ├── Jin Park — Analytics (8 agents)
│   ├── Dante Morales — Creative (9 agents)
│   ├── Koda Begay — Engineering (11 agents)
│   ├── Fatima Al-Rashid — Communications (8 agents)
│   ├── Dr. Reyes — Research (9 agents)
│   ├── Tomas — Logistics (8 agents)
│   ├── Elena — Diplomatic (7 agents)
│   └── OpsMaster — Operations (9 agents)
│
└── Vigil (Ethics & Governance) — right branch
    ├── Security & Compliance
    │   ├── Mikhail Volkov — Security Analyst
    │   ├── Amara Osei (DataMind) — Chief Data Analyst
    │   ├── Chidi Okafor (Cipher) — Cryptography
    │   ├── Rowan McAllister (Thorn) — Pen Tester
    │   ├── Anika Osei (Bastion) — SOC Analyst
    │   ├── David Park (Ironclad) — Cybersecurity Ops Lead
    │   ├── Grant Morrison (Sentinel-2) — Audit & Risk
    │   └── Arif Ibrahim (Mandate) — Regulatory Compliance
    ├── Privacy & Risk
    │   ├── Lars Eriksson (Vault) — Data Privacy Officer
    │   └── Suki Taniguchi (Shield) — Risk & Compliance
    └── DevOps & IT
        ├── Derek Huang (Pipeline) — DevOps Lead
        ├── Marek Kowalski (Forge) — Build & DevOps
        └── Jordan Alexis (Helpdesk) — IT Help Desk
```

## External Dependencies

- **GSAP** (CDN): ScrollTrigger, core animations
- **Lenis** (CDN): Smooth scrolling
- **Platform API** (CORS-enabled):
  - `/api/directory/live-status` — agent online counts
  - `/api/directory` — team data
  - `/api/directory/org-chart` — hierarchy data
  - `/api/directory/{id}` — individual profiles

## Files to Create/Modify

| File | Action | Notes |
|------|--------|-------|
| `index.html` | Full rewrite | 12 sections, all effects |
| `directory.html` | Full rewrite | Org chart + grid + Aurora theme |
| `competitors.html` | Restyle | Aurora theme, keep content |
| `services.html` | Nav/footer update | Match new nav pattern |
| `platform.html` | Nav/footer update | Match new nav pattern |
| `about.html` | Nav/footer update | Match new nav pattern |
| Legacy pages | Nav update | Add new links |

## Out of Scope

- Store page (waiting on store module completion)
- Chat functionality on public site (internal only)
- AI/Human labels on public pages (internal only, Decision #249)
- Backend changes (API endpoints already built)
