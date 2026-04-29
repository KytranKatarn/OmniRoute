# WTF Brand & UI Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform what-the-fact.com into a fully branded Canadian AI newsroom with Georgian serif editorial aesthetic, real agent portraits, and a 3-layer interactive Canada map with article pins.

**Architecture:** Three independent PRs. PR A ships brand CSS + nav redesign. PR B ships /team portrait grid with real Media Studio portraits. PR C ships the 3-layer map pin system (new wtf-tech geo endpoint + Leaflet JS cluster + bias dot layers).

**Tech Stack:** Flask + Jinja2 (wtf-consumer, wtf-tech), CSS custom properties (prefers-color-scheme), Leaflet.js 1.9.x, SQLAlchemy + text(), platform.kytranempowerment.com (portrait image source), PostgreSQL wtf schema.

---

## File Map

| File | Action | PR |
|------|--------|----|
| `what-the-fact/consumer/static/style.css` | Rewrite — full brand CSS system | A |
| `what-the-fact/consumer/templates/base.html` | Modify — new nav with wordmark + LIVE dot | A |
| `what-the-fact/consumer/routes.py` | Modify — add source_count + update TEAM_AGENTS with portrait_url/accent_colour | A + B |
| `what-the-fact/consumer/templates/team.html` | Rewrite — portrait grid with real images | B |
| `what-the-fact/tech/routes.py` | Modify — add GET /api/v1/articles/geo | C |
| `what-the-fact/consumer/templates/index.html` | Modify — add cluster layer + bias pin layer JS | C |

---

## PR A — Brand CSS + Nav

### Task 1: Rewrite style.css with full brand CSS system

**Files:**
- Rewrite: `what-the-fact/consumer/static/style.css`

- [ ] **Step 1: Read the current file**

```bash
cat /mnt/archie_brain/what-the-fact/consumer/static/style.css
```

Note the current variable names so nothing is accidentally broken.

- [ ] **Step 2: Rewrite the entire file**

Write `what-the-fact/consumer/static/style.css` with this complete content:

```css
/* ===== WTF BRAND SYSTEM ===== */

/* Light mode defaults */
:root {
  --wtf-bg:           #f9fafb;
  --wtf-bg-card:      #ffffff;
  --wtf-bg-panel:     #f3f4f6;
  --wtf-text:         #111111;
  --wtf-text-muted:   #6b7280;
  --wtf-border:       #e5e7eb;
  --wtf-accent:       #dc2626;
  --wtf-map-bg:       #0d1117;

  --wtf-left:         #3b82f6;
  --wtf-center-left:  #93c5fd;
  --wtf-center:       #9ca3af;
  --wtf-center-right: #fca5a5;
  --wtf-right:        #ef4444;

  --wtf-fact:    #dc2626;
  --wtf-bias:    #f59e0b;
  --wtf-verify:  #10b981;
  --wtf-local:   #3b82f6;
  --wtf-aurora:  #7c3aed;
}

/* Dark mode overrides */
@media (prefers-color-scheme: dark) {
  :root {
    --wtf-bg:         #0d1117;
    --wtf-bg-card:    #0a0f1a;
    --wtf-bg-panel:   #060d14;
    --wtf-text:       #f9fafb;
    --wtf-text-muted: #6b7280;
    --wtf-border:     #1f2937;
  }
}

/* Reset */
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  font-family: 'IBM Plex Mono', 'Courier New', monospace;
  background: var(--wtf-bg);
  color: var(--wtf-text);
}
a { color: inherit; }

/* Nav */
.wtf-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 2rem;
  border-bottom: 1px solid var(--wtf-border);
  background: var(--wtf-bg);
  position: sticky;
  top: 0;
  z-index: 100;
  gap: 1rem;
}
.wtf-nav-brand { display: flex; flex-direction: column; gap: 0; }
.wtf-wordmark {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--wtf-text);
  line-height: 1.1;
}
.wtf-subbrand {
  font-size: 0.6rem;
  letter-spacing: 0.2em;
  color: var(--wtf-text-muted);
  text-transform: uppercase;
}
.wtf-nav-links { display: flex; gap: 1.5rem; align-items: center; }
.wtf-nav-links a {
  font-size: 0.75rem;
  letter-spacing: 0.1em;
  color: var(--wtf-text-muted);
  text-decoration: none;
  text-transform: uppercase;
}
.wtf-nav-links a:hover { color: var(--wtf-text); }
.wtf-nav-live {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.65rem;
  letter-spacing: 0.15em;
  color: var(--wtf-accent);
  white-space: nowrap;
}
.wtf-live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--wtf-accent);
  display: inline-block;
  animation: wtf-pulse 1.2s ease-in-out infinite;
}
@keyframes wtf-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.35; }
}
.lang-switcher { display: flex; gap: 0.4rem; }
.lang-btn {
  background: none;
  border: 1px solid var(--wtf-border);
  color: var(--wtf-text-muted);
  padding: 0.2rem 0.5rem;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.7rem;
  font-family: inherit;
}
.lang-btn:hover { color: var(--wtf-text); border-color: var(--wtf-text-muted); }

/* Footer */
.wtf-footer {
  padding: 2rem;
  border-top: 1px solid var(--wtf-border);
  color: var(--wtf-text-muted);
  font-size: 0.8rem;
}

/* Map zone (always dark) */
#wtf-map-zone {
  background: var(--wtf-map-bg) !important;
  color: #e6edf3;
  padding: 12px;
  border-bottom: 1px solid #1a3a5a;
}
#wtf-map-zone h2 {
  font-size: 10px;
  letter-spacing: 3px;
  color: #0af;
  margin: 0 0 8px;
}
#wtf-canada-map {
  height: 300px;
  border-radius: 4px;
  border: 1px solid #1a3a5a;
}

/* Layout */
#wtf-main { display: flex; min-height: 400px; }
#wtf-editorial {
  flex: 0 0 38%;
  background: var(--wtf-bg-panel);
  padding: 14px;
  border-right: 1px solid var(--wtf-border);
  overflow-y: auto;
}
#wtf-feed {
  flex: 1;
  background: var(--wtf-bg);
  padding: 14px;
  overflow-y: auto;
}
.wtf-section-label {
  font-size: 10px;
  letter-spacing: 2px;
  color: var(--wtf-accent);
  margin: 0 0 10px;
}

/* Activity feed */
.wtf-activity-item {
  background: var(--wtf-bg-card);
  border-radius: 3px;
  padding: 8px;
  margin-bottom: 6px;
  display: flex;
  gap: 8px;
  align-items: flex-start;
  border: 1px solid var(--wtf-border);
}
.wtf-agent-icon {
  width: 24px; height: 24px;
  border-radius: 50%;
  background: var(--wtf-bg-panel);
  display: flex; align-items: center; justify-content: center;
  font-size: 9px; font-weight: bold; flex-shrink: 0;
}
.wtf-activity-text { font-size: 11px; color: var(--wtf-text-muted); }
.wtf-activity-time { font-size: 9px; color: var(--wtf-text-muted); opacity: 0.6; }
.wtf-top-story {
  font-size: 11px;
  color: var(--wtf-text);
  padding: 5px 0;
  border-bottom: 1px solid var(--wtf-border);
}

/* Article cards */
.wtf-article-card {
  background: var(--wtf-bg-card);
  border-radius: 3px;
  padding: 10px;
  margin-bottom: 8px;
  border: 1px solid var(--wtf-border);
  border-left-width: 3px;
}
.wtf-article-card--left        { border-left-color: var(--wtf-left); }
.wtf-article-card--center-left { border-left-color: var(--wtf-center-left); }
.wtf-article-card--center      { border-left-color: var(--wtf-center); }
.wtf-article-card--center-right{ border-left-color: var(--wtf-center-right); }
.wtf-article-card--right       { border-left-color: var(--wtf-right); }

.wtf-card-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 10px;
  color: var(--wtf-text-muted);
}
.wtf-card-title {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 14px;
  line-height: 1.4;
  color: var(--wtf-text);
  text-decoration: none;
  display: block;
  margin-bottom: 4px;
}
.wtf-card-title:hover { color: var(--wtf-accent); }
.wtf-card-badge {
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 2px;
}
.wtf-badge-ai    { background: #0a2a1a; color: #4a9; }
.wtf-badge-quick { background: #1a1a0a; color: #aa9; }

/* Bias pills */
.wtf-bias-pill {
  font-size: 9px;
  padding: 2px 6px;
  border-radius: 2px;
}
.wtf-bias-left        { background: #0a1a40; color: var(--wtf-left); }
.wtf-bias-center-left { background: #0a1530; color: var(--wtf-center-left); }
.wtf-bias-center      { background: var(--wtf-bg-panel); color: var(--wtf-center); }
.wtf-bias-center-right{ background: #2a1010; color: var(--wtf-center-right); }
.wtf-bias-right       { background: #2a0a0a; color: var(--wtf-right); }

/* Team page */
.wtf-team-hero {
  background: #050d1a;
  color: #e0e0e0;
  padding: 40px 20px;
  text-align: center;
  border-bottom: 1px solid #112233;
}
.wtf-team-hero-live {
  font-size: 10px;
  letter-spacing: 3px;
  color: var(--wtf-accent);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.wtf-team-hero h1 {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 28px;
  letter-spacing: 4px;
  color: #f9fafb;
  margin: 0 0 10px;
}
.wtf-team-hero p {
  font-size: 11px;
  color: #6b7280;
  max-width: 500px;
  margin: 0 auto;
  line-height: 1.7;
}
.wtf-team-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  padding: 24px 16px;
  max-width: 1200px;
  margin: 0 auto;
  background: var(--wtf-bg);
}
.wtf-team-card {
  background: var(--wtf-bg-card);
  border: 1px solid var(--wtf-border);
  border-radius: 4px;
  padding: 20px;
  position: relative;
}
.wtf-team-card--coming { opacity: 0.7; }
.wtf-team-card--teaser { border-color: #7c3aed; border-style: dashed; }

.wtf-team-portrait {
  width: 72px;
  height: 90px;
  border-radius: 4px;
  border: 2px solid var(--wtf-border);
  background-color: var(--wtf-bg-panel);
  background-size: cover;
  background-position: center top;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  margin-bottom: 12px;
}
.wtf-team-card--coming .wtf-team-portrait { filter: grayscale(70%); }

.wtf-team-name {
  font-size: 16px;
  font-weight: bold;
  letter-spacing: 1px;
  margin-bottom: 4px;
}
.wtf-team-expansion {
  font-size: 9px;
  color: var(--wtf-text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
  line-height: 1.4;
}
.wtf-team-role {
  font-size: 11px;
  color: var(--wtf-text-muted);
  margin-bottom: 6px;
}
.wtf-team-model {
  display: inline-block;
  background: var(--wtf-bg-panel);
  border: 1px solid var(--wtf-border);
  color: #4a9;
  font-size: 9px;
  padding: 2px 7px;
  border-radius: 2px;
  margin-bottom: 10px;
}
.wtf-team-desc {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 12px;
  color: var(--wtf-text-muted);
  line-height: 1.6;
}
.wtf-team-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  font-size: 9px;
  padding: 2px 7px;
  border-radius: 2px;
}
.wtf-badge-active { background: #0a2a1a; color: #4a9; }
.wtf-badge-soon   { background: var(--wtf-bg-panel); color: var(--wtf-text-muted); }
.wtf-badge-phase2 { background: #1a0a3a; color: #a0f; }

.wtf-team-footer {
  text-align: center;
  padding: 24px;
  font-size: 11px;
  color: var(--wtf-text-muted);
  border-top: 1px solid var(--wtf-border);
  background: var(--wtf-bg);
}
.wtf-team-footer a { color: var(--wtf-accent); text-decoration: none; }
```

- [ ] **Step 3: Verify required classes exist**

```bash
grep -c "wtf-nav\|wtf-wordmark\|wtf-live-dot\|wtf-pulse\|wtf-card-title\|wtf-map-bg\|wtf-team-portrait\|prefers-color-scheme" \
  /mnt/archie_brain/what-the-fact/consumer/static/style.css
```

Expected: 8

- [ ] **Step 4: Commit**

```bash
git add what-the-fact/consumer/static/style.css
git commit -m "feat(wtf): brand CSS system — Georgian serif, light/dark theme, bias classes, team styles"
```

---

### Task 2: Nav redesign + source_count in routes

**Files:**
- Modify: `what-the-fact/consumer/templates/base.html`
- Modify: `what-the-fact/consumer/routes.py`

- [ ] **Step 1: Read both files**

```bash
cat /mnt/archie_brain/what-the-fact/consumer/templates/base.html
grep -n "def index\|render_template\|source_count" /mnt/archie_brain/what-the-fact/consumer/routes.py
```

- [ ] **Step 2: Replace nav/header in base.html**

Find the `<header ...>` block and replace it with:

```html
<nav class="wtf-nav">
  <div class="wtf-nav-brand">
    <span class="wtf-wordmark">WHAT&middot;THE&middot;FACT</span>
    <span class="wtf-subbrand">CANADIAN AI NEWSROOM</span>
  </div>
  <div class="wtf-nav-links">
    <a href="/">News</a>
    <a href="/team">Team</a>
    <a href="https://what-the-fact.tech/transparency">Methodology</a>
    <a href="https://what-the-fact.tech/score">Score Text</a>
  </div>
  <div class="wtf-nav-live">
    <span class="wtf-live-dot"></span>
    <span>LIVE &middot; {{ source_count | default(0) }} SOURCES</span>
  </div>
  <div class="lang-switcher">
    <button class="lang-btn" data-lang="en">EN</button>
    <button class="lang-btn" data-lang="fr">FR</button>
    <button class="lang-btn" data-lang="es">ES</button>
  </div>
</nav>
```

- [ ] **Step 3: Add source_count to the index route in routes.py**

In the `index()` function, after the articles query, add before the `return render_template(...)`:

```python
        source_count = c.execute(
            text(f"SELECT COUNT(*) FROM {S}.sources")
        ).scalar() or 0
```

And add `source_count=source_count` to the `render_template()` call.

- [ ] **Step 4: Verify Jinja2 syntax**

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/mnt/archie_brain/what-the-fact/consumer/templates'))
env.get_template('base.html')
print('OK')
"
```

Expected: `OK`

- [ ] **Step 5: Rsync + rebuild + restart on VPS**

```bash
rsync -az --delete \
  -e "ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no" \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" --exclude=".env" \
  /mnt/archie_brain/what-the-fact/ \
  kytran@76.13.107.109:/opt/archie-products/what-the-fact/

ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no kytran@76.13.107.109 "
cd /opt/archie-products/what-the-fact
docker build -f Dockerfile.consumer -t wtf-consumer:brand . 2>&1 | tail -3
docker stop wtf_consumer && docker rm wtf_consumer
docker run -d --name wtf_consumer --network what-the-fact_default \
  --env-file .env -p 8103:8103 wtf-consumer:brand
sleep 4 && docker logs wtf_consumer --tail 6
"
```

- [ ] **Step 6: Smoke test**

```bash
curl -s http://76.13.107.109:8103/ | grep -c "WHAT" && echo "wordmark OK"
curl -s http://76.13.107.109:8103/ | grep -c "wtf-live-dot" && echo "live dot OK"
curl -s http://76.13.107.109:8103/static/style.css | grep -c "Georgia" && echo "Georgia in CSS OK"
```

Expected: `1 wordmark OK`, `1 live dot OK`, `N Georgia in CSS OK` (N >= 3)

- [ ] **Step 7: Commit**

```bash
git add what-the-fact/consumer/templates/base.html what-the-fact/consumer/routes.py
git commit -m "feat(wtf): nav redesign — WHAT·THE·FACT wordmark, LIVE dot, source count"
```

---

## PR B — /team Portrait Redesign

### Task 3: Team page with real portraits

**Files:**
- Modify: `what-the-fact/consumer/routes.py` (TEAM_AGENTS)
- Rewrite: `what-the-fact/consumer/templates/team.html`

- [ ] **Step 1: Read current TEAM_AGENTS and team.html**

```bash
grep -n "TEAM_AGENTS\|portrait\|coming_soon" /mnt/archie_brain/what-the-fact/consumer/routes.py | head -20
cat /mnt/archie_brain/what-the-fact/consumer/templates/team.html
```

- [ ] **Step 2: Replace TEAM_AGENTS list in routes.py**

Find `TEAM_AGENTS = [` and replace the entire list through its closing `]` with:

```python
_PLATFORM = "https://platform.kytranempowerment.com"

TEAM_AGENTS = [
    {
        "name": "F.A.C.T.",
        "full": "Factual Analysis, Credibility & Transparency",
        "role": "Director & Orchestrator",
        "model": "gemma3:12b",
        "description": "F.A.C.T. leads every ingest cycle — selecting the stories most worth investigating deeply, coordinating the team, and ensuring coverage is fair and complete.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/c78a58f0-ee5.png",
        "accent_colour": "#dc2626",
    },
    {
        "name": "B.I.A.S.",
        "full": "Balanced Information Analysis & Scoring",
        "role": "Bias Analyst",
        "model": "gemma2:9b",
        "description": "B.I.A.S. reads every priority article and scores it on the political spectrum, surfacing the trigger phrases and framing choices that reveal editorial perspective.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/05821aee-a2e.png",
        "accent_colour": "#f59e0b",
    },
    {
        "name": "V.E.R.I.F.Y.",
        "full": "Verification, Evidence Review & Integrity",
        "role": "Fact-Checker",
        "model": "gemma2:9b",
        "description": "V.E.R.I.F.Y. extracts verifiable claims from each article and assigns a verdict — verified, mixed, disputed, or unverifiable — with reasoning.",
        "coming_soon": False,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/5d0d0525-a4e.png",
        "accent_colour": "#10b981",
    },
    {
        "name": "L.O.C.A.L.",
        "full": "Local Observer, Coverage & Area Liaison",
        "role": "Geographic Intelligence Analyst",
        "model": "llama3.2:3b",
        "description": "L.O.C.A.L. maps every story to a Canadian province, tracks coverage gaps across regions, and identifies news deserts where communities go unheard.",
        "coming_soon": False,
        "portrait_url": "",
        "accent_colour": "#3b82f6",
    },
    {
        "name": "I.N.K.",
        "full": "Investigative News & Knowledge",
        "role": "News Investigator",
        "model": "dolphin3",
        "description": "I.N.K. will detect investigative story threads across article clusters — finding the through-line when the same story unfolds across days and outlets.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/9e1efa5f-5a7.png",
        "accent_colour": "#6b7280",
    },
    {
        "name": "D.R.A.F.T.",
        "full": "Data Reduction & Factual Translation",
        "role": "Staff Writer",
        "model": "dolphin3",
        "description": "D.R.A.F.T. will generate WTF editorial summaries — translating dense news cycles into plain-language explainers.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/70bc27b1-ede.png",
        "accent_colour": "#6b7280",
    },
    {
        "name": "P.U.B.L.I.S.H.",
        "full": "Publish & Unified Broadcasting",
        "role": "Broadcast Editor",
        "model": "mistral:7b",
        "description": "P.U.B.L.I.S.H. will push top stories to social media and newsletter subscribers, bringing AI journalism to where Canadians actually consume news.",
        "coming_soon": True,
        "portrait_url": _PLATFORM + "/static/media/images/2026-04-20/e7149ec2-f73.png",
        "accent_colour": "#6b7280",
    },
]
```

- [ ] **Step 3: Rewrite team.html**

Write `what-the-fact/consumer/templates/team.html` with:

```html
{% extends "base.html" %}
{% block content %}

<div class="wtf-team-hero">
  <div class="wtf-team-hero-live">
    <span class="wtf-live-dot"></span>
    LIVE &middot; AI NEWSROOM
  </div>
  <h1>MEET THE TEAM</h1>
  <p>Seven AI agents. One mission &mdash; radical transparency in Canadian journalism. No opinion. No agenda. Just data.</p>
</div>

<div class="wtf-team-grid">
  {% for agent in agents %}
  <div class="wtf-team-card {% if agent.coming_soon %}wtf-team-card--coming{% else %}wtf-team-card--active{% endif %}">

    {% if agent.coming_soon %}
    <span class="wtf-team-badge wtf-badge-soon">Coming Soon</span>
    {% else %}
    <span class="wtf-team-badge wtf-badge-active">Active</span>
    {% endif %}

    {% if agent.portrait_url %}
    <div class="wtf-team-portrait"
         style="background-image: url('{{ agent.portrait_url }}'); border-color: {{ agent.accent_colour }};">
    </div>
    {% else %}
    <div class="wtf-team-portrait" style="border-color: {{ agent.accent_colour }};">📍</div>
    {% endif %}

    <div class="wtf-team-name" style="color: {{ agent.accent_colour }};">{{ agent.name }}</div>
    <div class="wtf-team-expansion">{{ agent.full }}</div>
    <div class="wtf-team-role">{{ agent.role }}</div>
    <span class="wtf-team-model">{{ agent.model }}</span>
    <div class="wtf-team-desc">{{ agent.description }}</div>
  </div>
  {% endfor %}

  <div class="wtf-team-card wtf-team-card--teaser">
    <span class="wtf-team-badge wtf-badge-phase2">Phase 2</span>
    <div class="wtf-team-portrait" style="border-color: #7c3aed; font-size: 28px;">🌌</div>
    <div class="wtf-team-name" style="color: #7c3aed;">A.U.R.O.R.A.</div>
    <div class="wtf-team-expansion">Atmospheric &amp; Universal Resource for Observation, Research &amp; Analysis</div>
    <div class="wtf-team-role">Weather Intelligence</div>
    <span class="wtf-team-model">qwen2.5:7b</span>
    <div class="wtf-team-desc">Environment Canada + NASA EarthData + NOAA. Weather intelligence integrated into every story &mdash; because in Canada, the weather IS the news.</div>
  </div>
</div>

<div class="wtf-team-footer">
  Portraits generated by Media Studio &middot;
  <a href="https://what-the-fact.tech/transparency">Radical Transparency &rarr;</a>
</div>

{% endblock %}
```

- [ ] **Step 4: Verify portrait_url fields**

```bash
grep -c "portrait_url" /mnt/archie_brain/what-the-fact/consumer/routes.py
```

Expected: 7 (one per agent)

- [ ] **Step 5: Rsync + rebuild + restart on VPS**

```bash
rsync -az --delete \
  -e "ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no" \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" --exclude=".env" \
  /mnt/archie_brain/what-the-fact/ \
  kytran@76.13.107.109:/opt/archie-products/what-the-fact/

ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no kytran@76.13.107.109 "
cd /opt/archie-products/what-the-fact
docker build -f Dockerfile.consumer -t wtf-consumer:portraits . 2>&1 | tail -3
docker stop wtf_consumer && docker rm wtf_consumer
docker run -d --name wtf_consumer --network what-the-fact_default \
  --env-file .env -p 8103:8103 wtf-consumer:portraits
sleep 4 && docker logs wtf_consumer --tail 4
"
```

- [ ] **Step 6: Smoke tests**

```bash
curl -s http://76.13.107.109:8103/team | grep -c "wtf-team-card" && echo "cards OK"
curl -s http://76.13.107.109:8103/team | grep -c "platform.kytranempowerment.com" && echo "portrait URLs OK"
curl -s http://76.13.107.109:8103/team | grep -c "A.U.R.O.R.A." && echo "aurora OK"
```

Expected: `8 cards OK`, `≥6 portrait URLs OK`, `1 aurora OK`

- [ ] **Step 7: Commit**

```bash
git add what-the-fact/consumer/routes.py what-the-fact/consumer/templates/team.html
git commit -m "feat(wtf): /team portrait grid — real Media Studio portraits, agent accent colours, AURORA teaser"
```

---

## PR C — Map Pins

### Task 4: wtf-tech GET /api/v1/articles/geo

**Files:**
- Modify: `what-the-fact/tech/routes.py`

- [ ] **Step 1: Find insertion point**

```bash
grep -n "def agent_activity\|def analyze_article" /mnt/archie_brain/what-the-fact/tech/routes.py
```

Note the line number after `agent_activity` closes and before `analyze_article` starts. Insert the new endpoint there.

- [ ] **Step 2: Add the endpoint**

After the closing of `agent_activity()` and before `analyze_article()`, insert:

```python
@bp.get("/api/v1/articles/geo")
def articles_geo():
    """Articles with lat/lng for map pins (last 24h). Max 500 rows."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.province_code,
                   a.lat, a.lng,
                   bs.band AS bias_band,
                   s.name AS source_name,
                   a.ai_analyzed
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            LEFT JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.published_at >= NOW() - INTERVAL '24 hours'
              AND a.lat IS NOT NULL
              AND a.lng IS NOT NULL
            ORDER BY a.published_at DESC
            LIMIT 500
        """)).fetchall()
    return jsonify({"articles": [
        {
            "id": r.id,
            "title": r.title,
            "province_code": r.province_code,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "bias_band": r.bias_band or "center",
            "source_name": r.source_name,
            "ai_analyzed": bool(r.ai_analyzed),
        }
        for r in rows
    ]})
```

- [ ] **Step 3: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/what-the-fact/tech/routes.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Rsync + rebuild wtf-tech**

```bash
rsync -az --delete \
  -e "ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no" \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" --exclude=".env" \
  /mnt/archie_brain/what-the-fact/ \
  kytran@76.13.107.109:/opt/archie-products/what-the-fact/

ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no kytran@76.13.107.109 "
cd /opt/archie-products/what-the-fact
docker build -f Dockerfile.tech -t wtf-tech:mapdata . 2>&1 | tail -3
docker stop wtf_tech && docker rm wtf_tech
docker run -d --name wtf_tech --network what-the-fact_default \
  --env-file .env -p 8104:8104 wtf-tech:mapdata
sleep 4 && docker logs wtf_tech --tail 4
"
```

- [ ] **Step 5: Smoke test**

```bash
curl -s http://76.13.107.109:8104/api/v1/articles/geo | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert 'articles' in d, 'missing articles key'
print('geo endpoint OK, articles:', len(d['articles']))
"
```

Expected: `geo endpoint OK, articles: N` (N may be 0 if no geo data yet — that's fine)

- [ ] **Step 6: Commit**

```bash
git add what-the-fact/tech/routes.py
git commit -m "feat(wtf-tech): GET /api/v1/articles/geo — 24h article pins with lat/lng/bias_band"
```

---

### Task 5: Map JS — cluster badges + bias pin layers

**Files:**
- Modify: `what-the-fact/consumer/templates/index.html`

- [ ] **Step 1: Find existing JS layer variable and init sequence**

```bash
grep -n "provinceLayer\|loadMapData\|loadAgentActivity\|setInterval" \
  /mnt/archie_brain/what-the-fact/consumer/templates/index.html
```

Note the line with `var provinceLayer = null;` and the init block at the bottom.

- [ ] **Step 2: Add clusterLayer and pinLayer variables**

After `var provinceLayer = null;`, add:

```javascript
var clusterLayer = null;
var pinLayer = null;
```

- [ ] **Step 3: Add province centroids, colours, and loadArticlesGeo() function**

After the `timeAgo()` function and before the init sequence (`loadMapData();`), insert this complete block:

```javascript
var PROVINCE_CENTROIDS = {
  "ON":[51.25,-85.32],"QC":[53.00,-70.00],"BC":[53.73,-127.65],
  "AB":[53.93,-116.58],"SK":[52.94,-106.45],"MB":[56.42,-98.74],
  "NB":[46.57,-66.46],"NS":[44.68,-63.74],"NL":[53.14,-57.66],
  "PE":[46.51,-63.42],"YT":[64.28,-135.00],"NT":[64.28,-119.18],"NU":[70.30,-83.11]
};
var PROVINCE_COLOURS = {
  "ON":"#0af","QC":"#a78bfa","AB":"#f59e0b","BC":"#4ade80",
  "SK":"#34d399","MB":"#60a5fa","NS":"#f97316","NB":"#f97316",
  "NL":"#94a3b8","PE":"#94a3b8","YT":"#94a3b8","NT":"#94a3b8","NU":"#94a3b8"
};

function loadArticlesGeo() {
  fetch(WTF_TECH_URL + "/api/v1/articles/geo")
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var articles = data.articles || [];

      // Layer 2: Province cluster badges
      if (clusterLayer) map.removeLayer(clusterLayer);
      clusterLayer = L.layerGroup();
      var provinceCounts = {};
      articles.forEach(function(a) {
        if (a.province_code) {
          provinceCounts[a.province_code] = (provinceCounts[a.province_code] || 0) + 1;
        }
      });
      Object.keys(provinceCounts).forEach(function(pc) {
        var centroid = PROVINCE_CENTROIDS[pc];
        if (!centroid) return;
        var count = provinceCounts[pc];
        var radius = Math.min(6 + count * 0.4, 20);
        var colour = PROVINCE_COLOURS[pc] || "#9ca3af";
        var circle = L.circleMarker(centroid, {
          radius: radius,
          fillColor: colour,
          fillOpacity: 0.85,
          color: "#ffffff",
          weight: 1.5,
          interactive: true,
        });
        circle.bindTooltip(pc + " · " + count + " stories");
        circle.on("click", function() { map.setView(centroid, 6); });
        clusterLayer.addLayer(circle);
        var label = L.marker(centroid, {
          icon: L.divIcon({
            html: "<div style='font-size:9px;font-family:monospace;color:#fff;text-align:center;line-height:1;margin-top:-3px;'>" + count + "</div>",
            className: "",
            iconSize: [20, 12],
            iconAnchor: [10, 6],
          }),
          interactive: false,
        });
        clusterLayer.addLayer(label);
      });
      clusterLayer.addTo(map);

      // Layer 3: Individual bias pins (visible at zoom >= 5)
      if (pinLayer) map.removeLayer(pinLayer);
      pinLayer = L.layerGroup();
      var currentZoom = map.getZoom();
      var pinOpacity = currentZoom >= 5 ? 0.9 : 0;
      articles.forEach(function(a) {
        if (!a.lat || !a.lng) return;
        var colour = BIAS_COLOURS[a.bias_band] || BIAS_COLOURS["center"];
        var pin = L.circleMarker([a.lat, a.lng], {
          radius: 5,
          fillColor: colour,
          fillOpacity: pinOpacity,
          color: colour,
          weight: 1,
          opacity: pinOpacity,
        });
        pin.bindTooltip(esc(a.source_name || "") + " — " + esc(a.bias_band || "center"));
        pin.on("click", function() { window.location = "/article/" + a.id; });
        pinLayer.addLayer(pin);
      });
      pinLayer.addTo(map);

      // Show/hide pins on zoom
      map.off("zoomend.pins");
      map.on("zoomend.pins", function() {
        var opacity = map.getZoom() >= 5 ? 0.9 : 0;
        pinLayer.eachLayer(function(layer) {
          layer.setStyle({ fillOpacity: opacity, opacity: opacity });
        });
      });
    })
    .catch(function(e) {
      console.warn("WTF geo pins load failed:", e);
    });
}
```

- [ ] **Step 4: Update the init sequence**

Replace:
```javascript
loadMapData();
loadAgentActivity();
setInterval(loadMapData, 1800000);
setInterval(loadAgentActivity, 60000);
```

With:
```javascript
loadMapData();
loadAgentActivity();
loadArticlesGeo();
setInterval(loadMapData, 1800000);
setInterval(loadAgentActivity, 60000);
setInterval(loadArticlesGeo, 1800000);
```

- [ ] **Step 5: Verify JS constants present**

```bash
grep -c "PROVINCE_CENTROIDS\|loadArticlesGeo\|clusterLayer\|pinLayer" \
  /mnt/archie_brain/what-the-fact/consumer/templates/index.html
```

Expected: 4

- [ ] **Step 6: Rsync + rebuild + restart wtf-consumer**

```bash
rsync -az --delete \
  -e "ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no" \
  --exclude=".git" --exclude="__pycache__" --exclude="*.pyc" --exclude=".env" \
  /mnt/archie_brain/what-the-fact/ \
  kytran@76.13.107.109:/opt/archie-products/what-the-fact/

ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no kytran@76.13.107.109 "
cd /opt/archie-products/what-the-fact
docker build -f Dockerfile.consumer -t wtf-consumer:mappins . 2>&1 | tail -3
docker stop wtf_consumer && docker rm wtf_consumer
docker run -d --name wtf_consumer --network what-the-fact_default \
  --env-file .env -p 8103:8103 wtf-consumer:mappins
sleep 4 && docker logs wtf_consumer --tail 4
"
```

- [ ] **Step 7: Smoke tests**

```bash
curl -s http://76.13.107.109:8103/ | grep -c "PROVINCE_CENTROIDS\|loadArticlesGeo" && echo "map JS OK"
```

Expected: `2 map JS OK`

- [ ] **Step 8: Commit**

```bash
git add what-the-fact/consumer/templates/index.html
git commit -m "feat(wtf): map Layer 2 cluster badges + Layer 3 bias pins with zoom-reveal at z>=5"
```

---

### Task 6: Final push + PR creation

- [ ] **Step 1: Push to main**

```bash
git push origin main
```

- [ ] **Step 2: Full smoke test suite**

```bash
echo "=== Homepage ===" && \
curl -s http://76.13.107.109:8103/ | grep -c "WHAT" && \
curl -s http://76.13.107.109:8103/ | grep -c "wtf-live-dot" && \
echo "=== Team page ===" && \
curl -s http://76.13.107.109:8103/team | grep -c "wtf-team-card" && \
curl -s http://76.13.107.109:8103/team | grep -c "platform.kytranempowerment.com" && \
echo "=== Geo endpoint ===" && \
curl -s http://76.13.107.109:8104/api/v1/articles/geo | python3 -c "import sys,json; d=json.load(sys.stdin); print('articles:', len(d['articles']))" && \
echo "=== CSS ===" && \
curl -s http://76.13.107.109:8103/static/style.css | grep -c "Georgia" && \
echo "All smoke tests done"
```

Expected:
- `1` (wordmark)
- `1` (live dot)
- `≥8` (team cards including AURORA)
- `≥6` (portrait URLs)
- `articles: N` (geo endpoint, N ≥ 0)
- `≥3` (Georgia in CSS)

- [ ] **Step 3: Commit final state**

```bash
git add -A
git status  # should be clean
echo "WTF Brand & UI Overhaul complete"
```

---

## Success Criteria

- **Brand:** Light/dark system theme active, Georgia serif on all headlines, red LIVE dot pulses in nav, map zone stays dark in both modes
- **Nav:** WHAT·THE·FACT wordmark + CANADIAN AI NEWSROOM subtext + source count visible
- **/team:** 4+ agents show real portrait images from platform, colour-coded borders, greyscale coming-soon, AURORA teaser in purple
- **Map:** Province heat fills existing (from PR 2), cluster badges appear on load, bias pins visible at zoom ≥ 5, click → article
- **geo endpoint:** `/api/v1/articles/geo` returns JSON `{articles: [...]}` with lat/lng/bias_band per article
