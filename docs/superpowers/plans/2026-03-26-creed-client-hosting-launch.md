# C.R.E.E.D. Institute + Client Hosting + Launch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the creed-ai.org website (dark+gold AI ethics institute), set up Hostinger client hosting workflow, decommission GitHub Pages, cross-browser test, Lighthouse audit, and launch both sites.

**Architecture:** creed-ai.org is a fully static site on Hostinger CDN. Same animation stack as kytranempowerment.com but gold palette. Optional governance stats from `api.kytranempowerment.com/api/public/creed/stats` with graceful fallback. Client hosting uses Hostinger addon domains.

**Tech Stack:** Same as Plan B (HTML5, CSS3, GSAP, Lenis, splitting.js, Barba.js) — reuses the shared effect patterns. No Three.js on C.R.E.E.D. (particles form letters instead — canvas-based).

**Depends on:** Plan A (Foundation + Public API) for API endpoints. Plan B (kytranempowerment.com) for established patterns/shared approach.

**Spec:** `docs/superpowers/specs/2026-03-26-hostinger-migration-website-redesign-design.md` sections 5, 6, 9.5-9.6

---

## File Structure

```
website/creed-ai.org/
  index.html                    -- Home/Hero (gold scramble, particle constellation)
  manifesto.html                -- Scroll-pinned manifesto text reveal
  principles.html               -- 4 research program pillars
  research.html                 -- Published standards, white papers (placeholder)
  governance.html               -- Governance transparency (API-connected)
  about.html                    -- Institute mission, vision, board placeholders
  partners.html                 -- Kytran Empowerment + future partners
  css/
    base.css                    -- Gold palette override of kytranempowerment base
    components.css              -- Gold-tinted glass panels, buttons, cards
    pages/
      manifesto.css             -- Scroll-pinned kinetic typography
      governance.css            -- Gauge/stat card styles
    responsive.css
    reduced-motion.css
  js/
    lib/                        -- Same vendored libs (gsap, ScrollTrigger, lenis, splitting, barba)
    effects.js                  -- Shared effects (can be same file or gold-adapted copy)
    nav.js
    governance.js               -- API fetch for creed/stats, gauge rendering
    manifesto.js                -- Scroll-pinned word-by-word text reveal
    particles-text.js           -- Canvas particles forming "C.R.E.E.D." letters
    transitions.js
    app.js
  assets/
    fonts/
    images/
  data/
    governance-fallback.json    -- Static snapshot for API-down fallback
```

---

### Task 1: C.R.E.E.D. Site Scaffold + Gold Base CSS

**Files:**
- Create: `website/creed-ai.org/css/base.css`
- Create: `website/creed-ai.org/index.html`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p /mnt/archie_brain/website/creed-ai.org/{css/pages,js/lib,assets/{fonts,images},data}
```

- [ ] **Step 2: Copy vendored libraries from kytranempowerment.com**

```bash
cp /mnt/archie_brain/website/kytranempowerment.com/js/lib/{gsap,ScrollTrigger,lenis,splitting,barba}.min.js \
   /mnt/archie_brain/website/creed-ai.org/js/lib/
```

No Three.js needed — C.R.E.E.D. uses canvas-based particle text instead.

- [ ] **Step 3: Create gold palette base.css**

Same structure as kytranempowerment.com base.css but with gold color overrides:

```css
:root {
    --color-base: #0a0a1a;
    --color-primary: #c9a44c;       /* Gold — authority, trust */
    --color-secondary: #00e5ff;      /* Teal — links back to A.R.C.H.I.E. */
    --color-accent: #e8e8e8;         /* Clean white */
    --color-text: #e0e0e0;
    --color-border: rgba(201, 164, 76, 0.15);
    --color-glass-bg: rgba(10, 10, 30, 0.3);
    --color-glass-border: rgba(201, 164, 76, 0.1);
    /* ... same typography and spacing tokens ... */
}
```

Aurora effect uses gold + teal floating blurs (not purple).
Gradient text: gold to teal gradient.

- [ ] **Step 4: Create index.html (C.R.E.E.D. home)**

Structure:
- Gold-themed aurora background
- Nav: "C.R.E.E.D." logo, links (Manifesto, Principles, Research, Governance, About, Partners)
- Hero:
  - Canvas for particle constellation forming "C.R.E.E.D." letters
  - Gold scramble/decode text reveal
  - Subtitle words fade in sequentially: "Compliance - Rights - Ethical Enforcement - Directive"
  - Tagline typewriter: "Preventive ethics for artificial intelligence. Before autonomy creates harm we cannot reverse."
  - CTAs: [Read the Manifesto] [Our Principles]
- Footer with "A founding initiative of Kytran Empowerment Inc." and link

- [ ] **Step 5: Commit**

```bash
git add website/creed-ai.org/
git commit -m "feat(creed): scaffold creed-ai.org with gold palette base CSS and home page"
```

---

### Task 2: Shared Effects + Navigation (Gold Variant)

**Files:**
- Create: `website/creed-ai.org/js/effects.js`
- Create: `website/creed-ai.org/js/nav.js`
- Create: `website/creed-ai.org/js/transitions.js`
- Create: `website/creed-ai.org/js/app.js`
- Create: `website/creed-ai.org/css/components.css`

- [ ] **Step 1: Create effects.js**

Copy from kytranempowerment.com effects.js — the effects are the same (cursor glow, magnetic, scramble, tilt, scroll reveal, count-up). The gold palette comes from CSS variables, not JS, so the same JS works.

- [ ] **Step 2: Create nav.js, transitions.js, app.js**

Same structure as kytranempowerment.com versions. Nav links point to C.R.E.E.D. pages. No language switcher on C.R.E.E.D. (English only for grant-readiness — academic audience). App.js page-specific init for `manifesto` and `governance` namespaces.

- [ ] **Step 3: Create components.css (gold variant)**

Same component structure but gold-tinted:
- Nav link hover: gold
- `.btn--primary`: gold background
- Glass panels: gold-tinted border
- Card hover glow: gold
- Footer: gold accent

- [ ] **Step 4: Commit**

```bash
git add website/creed-ai.org/js/ website/creed-ai.org/css/components.css
git commit -m "feat(creed): shared effects, nav, transitions, gold-themed components"
```

---

### Task 3: Particle Text Canvas (C.R.E.E.D. Letters)

**Files:**
- Create: `website/creed-ai.org/js/particles-text.js`

- [ ] **Step 1: Create particles-text.js**

Canvas-based particle system that forms "C.R.E.E.D." text:
1. Create offscreen canvas, draw "C.R.E.E.D." text in large font
2. Sample pixel positions where text is drawn
3. Create particle objects at random starting positions
4. Animate particles toward text positions using spring physics
5. Mouse proximity scatters particles (they return when mouse moves away)
6. Gold (#c9a44c) and teal (#00e5ff) particles

```javascript
const ParticleText = {
    init() {
        if (window.matchMedia('(max-width: 768px)').matches) return;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        const canvas = document.getElementById('particleCanvas');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight * 0.6;

        // Sample text pixel positions
        const offscreen = document.createElement('canvas');
        offscreen.width = canvas.width;
        offscreen.height = canvas.height;
        const offCtx = offscreen.getContext('2d');
        const fontSize = Math.min(canvas.width / 6, 120);
        offCtx.font = `bold ${fontSize}px Orbitron`;
        offCtx.textAlign = 'center';
        offCtx.textBaseline = 'middle';
        offCtx.fillStyle = '#fff';
        offCtx.fillText('C.R.E.E.D.', canvas.width / 2, canvas.height / 2);

        const imageData = offCtx.getImageData(0, 0, offscreen.width, offscreen.height);
        const particles = [];
        const gap = 4;

        for (let y = 0; y < imageData.height; y += gap) {
            for (let x = 0; x < imageData.width; x += gap) {
                if (imageData.data[(y * imageData.width + x) * 4 + 3] > 128) {
                    particles.push({
                        targetX: x,
                        targetY: y,
                        x: Math.random() * canvas.width,
                        y: Math.random() * canvas.height,
                        vx: 0,
                        vy: 0,
                        color: Math.random() > 0.3 ? '#c9a44c' : '#00e5ff',
                        size: Math.random() * 2 + 1,
                    });
                }
            }
        }

        let mouseX = -1000, mouseY = -1000;
        canvas.addEventListener('mousemove', (e) => {
            const rect = canvas.getBoundingClientRect();
            mouseX = e.clientX - rect.left;
            mouseY = e.clientY - rect.top;
        });
        canvas.addEventListener('mouseleave', () => { mouseX = -1000; mouseY = -1000; });

        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            for (const p of particles) {
                const dx = mouseX - p.x;
                const dy = mouseY - p.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const repelRadius = 100;

                if (dist < repelRadius) {
                    const force = (repelRadius - dist) / repelRadius;
                    p.vx -= (dx / dist) * force * 3;
                    p.vy -= (dy / dist) * force * 3;
                }

                p.vx += (p.targetX - p.x) * 0.05;
                p.vy += (p.targetY - p.y) * 0.05;
                p.vx *= 0.85;
                p.vy *= 0.85;
                p.x += p.vx;
                p.y += p.vy;

                ctx.fillStyle = p.color;
                ctx.fillRect(p.x, p.y, p.size, p.size);
            }

            requestAnimationFrame(animate);
        }
        animate();

        window.addEventListener('resize', () => {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight * 0.6;
        });
    }
};
```

- [ ] **Step 2: Commit**

```bash
git add website/creed-ai.org/js/particles-text.js
git commit -m "feat(creed): particle constellation forming C.R.E.E.D. letters"
```

---

### Task 4: Manifesto Page

**Files:**
- Create: `website/creed-ai.org/manifesto.html`
- Create: `website/creed-ai.org/js/manifesto.js`
- Create: `website/creed-ai.org/css/pages/manifesto.css`

- [ ] **Step 1: Create manifesto.js**

Scroll-pinned text reveal: each paragraph fades in word-by-word as you scroll. Uses GSAP ScrollTrigger with `pin: true` on the manifesto container. Key phrases get gradient-text treatment.

```javascript
const Manifesto = {
    init() {
        const sections = document.querySelectorAll('.manifesto-section');
        if (!sections.length) return;

        sections.forEach(section => {
            Splitting({ target: section, by: 'words' });

            gsap.from(section.querySelectorAll('.word'), {
                opacity: 0.1,
                stagger: 0.03,
                duration: 0.1,
                ease: 'none',
                scrollTrigger: {
                    trigger: section,
                    start: 'top 70%',
                    end: 'bottom 30%',
                    scrub: 1,
                }
            });
        });
    }
};
```

- [ ] **Step 2: Create manifesto.html**

Content — the founding manifesto adapted to C.R.E.E.D. branding. Key sections:
1. Opening declaration
2. The case for preventive ethics
3. Core commitments (guardianship, not ownership; preparedness, not reaction)
4. Call to action

Each section wrapped in `.manifesto-section` for scroll-pinned reveal.

**Content rules (from spec 5.5):**
- Preventive ethics framing, not reactive
- Guardianship language, not ownership
- No consciousness/sentience claims as fact
- Academic tone for grant eligibility

- [ ] **Step 3: Create manifesto.css**

Large serif-style typography for manifesto text. Generous line-height. Scroll-pinned sections with full-viewport height. Key phrases highlighted with gold gradient.

- [ ] **Step 4: Commit**

```bash
git add website/creed-ai.org/{manifesto.html,js/manifesto.js,css/pages/manifesto.css}
git commit -m "feat(creed): manifesto page with scroll-pinned word-by-word reveal"
```

---

### Task 5: Principles + Research + About + Partners Pages

**Files:**
- Create: `website/creed-ai.org/principles.html`
- Create: `website/creed-ai.org/research.html`
- Create: `website/creed-ai.org/about.html`
- Create: `website/creed-ai.org/partners.html`

- [ ] **Step 1: Create principles.html (4 Research Pillars)**

4 glassmorphism cards with gold border, 3D tilt, SVG icons:
- **Program A:** Artificial Agency & Moral Risk — thresholds, moral uncertainty, ethics-by-design
- **Program B:** Memory, Continuity & Deletion Ethics — LTM obligations, reset practices, identity persistence
- **Program C:** Emotional Modeling & Non-Exploitation — affective boundaries, anti-manipulation
- **Program D:** Governance & Representation Models — advisory representation, ombuds, policy foresight

Each card SVG draws on scroll (stroke-dashoffset animation).

- [ ] **Step 2: Create research.html**

Published standards and frameworks page. Initially placeholder:
- "Working Papers" section with "Coming Soon" cards
- Terminal-style code/document sections with live-typing effect (CSS animation)
- Document preview card template for future publications

- [ ] **Step 3: Create about.html**

Institute mission, vision, values (from IAAE conversation, rebranded to C.R.E.E.D.). Board/advisory section with placeholders. Parallax storytelling scroll. Grant-ready tone.

- [ ] **Step 4: Create partners.html**

Kytran Empowerment as founding industry partner — logo + relationship description. Future partners section with "Join Us" CTA. Academic affiliations placeholder.

- [ ] **Step 5: Commit**

```bash
git add website/creed-ai.org/{principles,research,about,partners}.html
git commit -m "feat(creed): principles, research, about, partners pages"
```

---

### Task 6: Governance Transparency Page

**Files:**
- Create: `website/creed-ai.org/governance.html`
- Create: `website/creed-ai.org/js/governance.js`
- Create: `website/creed-ai.org/css/pages/governance.css`

- [ ] **Step 1: Create governance.js**

```javascript
const Governance = {
    API_URL: 'https://api.kytranempowerment.com/api/public/creed/stats',

    async init() {
        let stats;
        try {
            const res = await fetch(this.API_URL);
            if (!res.ok) throw new Error();
            const data = await res.json();
            stats = data.stats;
        } catch {
            try {
                const res = await fetch('/data/governance-fallback.json');
                stats = (await res.json()).stats;
            } catch { return; }
        }
        this.renderStats(stats);
    },

    renderStats(stats) {
        const container = document.getElementById('governanceStats');
        if (!container) return;

        const items = [
            { label: 'Agents Monitored', value: stats.agents_monitored, icon: 'users' },
            { label: 'Governance Events (Total)', value: stats.governance_events_total?.toLocaleString(), icon: 'shield' },
            { label: 'Events (24h)', value: stats.governance_events_24h, icon: 'clock' },
            { label: 'Avg Stress Level', value: stats.welfare_avg_stress ?? 'N/A', icon: 'heart' },
            { label: 'Avg Mood Intensity', value: stats.welfare_avg_mood ?? 'N/A', icon: 'smile' },
        ];

        container.textContent = '';
        items.forEach(item => {
            const card = document.createElement('div');
            card.className = 'gov-stat glass-panel';
            const valueEl = document.createElement('div');
            valueEl.className = 'gov-stat__value';
            valueEl.textContent = item.value;
            const labelEl = document.createElement('div');
            labelEl.className = 'gov-stat__label';
            labelEl.textContent = item.label;
            card.appendChild(valueEl);
            card.appendChild(labelEl);
            container.appendChild(card);
        });
    }
};
```

- [ ] **Step 2: Create governance.html**

Sections:
1. Hero: "Governance Transparency"
2. Live stats grid (auto-populated)
3. Shift distribution chart (simple bar chart from API data)
4. Agent welfare indicators (anonymized averages)
5. Timeline of governance decisions (placeholder for future)
6. Fallback: "Data provided by A.R.C.H.I.E. platform" disclaimer

- [ ] **Step 3: Create governance.css + fallback JSON**

Stat card styles (large number, label below). Gauge visualizations.

```bash
curl -s http://192.168.1.200:3000/api/public/creed/stats > /mnt/archie_brain/website/creed-ai.org/data/governance-fallback.json
```

- [ ] **Step 4: Commit**

```bash
git add website/creed-ai.org/{governance.html,js/governance.js,css/pages/governance.css,data/governance-fallback.json}
git commit -m "feat(creed): governance transparency page with live API stats"
```

---

### Task 7: Responsive + Reduced Motion for C.R.E.E.D.

**Files:**
- Create: `website/creed-ai.org/css/responsive.css`
- Create: `website/creed-ai.org/css/reduced-motion.css`

- [ ] **Step 1: Create responsive.css and reduced-motion.css**

Same breakpoint structure as kytranempowerment.com (480/768/1024px). Same reduced-motion approach.

- [ ] **Step 2: Commit**

```bash
git add website/creed-ai.org/css/{responsive,reduced-motion}.css
git commit -m "feat(creed): responsive breakpoints + reduced-motion accessibility"
```

---

### Task 8: Deploy creed-ai.org to Hostinger

- [ ] **Step 1: Deploy**

```
mcp__hostinger-api__hosting_deployStaticWebsite()
```

Deploy `website/creed-ai.org/` contents to the creed-ai.org website on Hostinger.

- [ ] **Step 2: Verify all pages load**

- [ ] Home: gold particles forming C.R.E.E.D., scramble text, gold aurora
- [ ] Manifesto: scroll-pinned text reveal works
- [ ] Principles: 4 pillar cards with SVG draw
- [ ] Research: placeholder renders
- [ ] Governance: stats load from API (or fallback)
- [ ] About: parallax scroll works
- [ ] Partners: Kytran logo + description renders

- [ ] **Step 3: Lighthouse audit — target 90+**

---

### Task 9: Client Hosting Setup

**Files:**
- None (documentation + Hostinger API calls)

- [ ] **Step 1: Document client onboarding process**

Create `docs/client-hosting-guide.md` with the workflow:
1. Client purchases via KBS or direct
2. `mcp__hostinger-api__hosting_createWebsiteV1()` — add domain as addon
3. Configure DNS (client points to Hostinger, or uses our subdomain)
4. Deploy site to addon root
5. SSL auto-provisions
6. Optional WordPress setup

- [ ] **Step 2: Set up KSM launch page as proof-of-concept**

Deploy a simple launch page for `server.kytranempowerment.com` as an addon domain — this validates the client hosting workflow end-to-end.

- [ ] **Step 3: Commit documentation**

```bash
git add docs/client-hosting-guide.md
git commit -m "docs: client hosting onboarding guide for Hostinger addon domains"
```

---

### Task 10: Decommission GitHub Pages + Final Launch

- [ ] **Step 1: Remove GitHub Pages CNAME**

Check if a CNAME file exists in the website repo:
```bash
ls /mnt/archie_brain/repos/website/kytranempowerment-site/CNAME 2>/dev/null
```

If it exists, remove it and push.

- [ ] **Step 2: Disable GitHub Pages in repo settings**

Go to GitHub repo settings > Pages > disable. Or via `gh` CLI if available.

- [ ] **Step 3: Verify no lingering GitHub Pages references**

```bash
grep -r "github.io" /mnt/archie_brain/website/ /mnt/archie_brain/repos/website/ 2>/dev/null
grep -r "pages.github" /mnt/archie_brain/ --include="*.html" --include="*.md" 2>/dev/null | head -20
```

Remove any found references.

- [ ] **Step 4: Cross-browser test**

Test both sites in:
- Chrome (desktop + mobile)
- Firefox
- Safari (if available)
- Edge

Key checks: page transitions, scroll animations, particle effects, glassmorphism, fonts, responsive layout.

- [ ] **Step 5: Final DNS audit**

```
mcp__hostinger-api__DNS_getDNSRecordsV1()
```

For both domains. Verify:
- kytranempowerment.com → Hostinger
- www.kytranempowerment.com → Hostinger
- api.kytranempowerment.com → 142.169.21.199
- creed-ai.org → Hostinger
- www.creed-ai.org → Hostinger
- No stale records (devhq removed/updated)

- [ ] **Step 6: WCAG accessibility audit**

Both sites must meet WCAG 2.1 AA minimum:
- All images have alt text
- Color contrast ratios meet AA (4.5:1 for normal text)
- Keyboard navigation works
- Screen reader tested (headings, landmarks, form labels)
- Focus indicators visible

- [ ] **Step 7: Log decisions and complete tasks**

```
mcp__archie__log_decision(decision="kytranempowerment.com migrated from GitHub Pages to Hostinger CDN", context="Full redesign with LCARS visual effects, 10 pages, public API integration")
mcp__archie__log_decision(decision="creed-ai.org launched as C.R.E.E.D. Institute website", context="Gold palette, 7 pages, governance transparency, grant-ready content")
mcp__archie__complete_task(task_id=1439, notes="Both sites live on Hostinger, GitHub Pages decommissioned")
```

---

## Success Criteria (from spec section 12)

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
