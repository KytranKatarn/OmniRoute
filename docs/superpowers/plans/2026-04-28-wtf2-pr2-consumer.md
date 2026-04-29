# WTF 2.0 — PR 2: Consumer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild what-the-fact.com with a 3-zone homepage (Leaflet Canada map + editorial desk + news feed), agent bylines on articles, Deep Dive button, and /team page showcasing the AI newsroom.

**Architecture:** wtf-tech gets 3 new API endpoints (map-data, agent-activity, on-demand analyze); wtf-consumer templates are rebuilt using Jinja2 with Leaflet.js from CDN and Statistics Canada GeoJSON; article page gets bias/factcheck/byline panels; no new Python services — thin routes calling existing wtf schema queries.

**Tech Stack:** Flask + Jinja2 (wtf-consumer), Leaflet.js 1.9.x (CDN), Statistics Canada province GeoJSON (bundled as static file), SQLAlchemy + text() (wtf-tech API), Docker (VPS rebuild).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `what-the-fact/tech/routes.py` | Modify | Add /api/v1/map-data, /api/v1/agent-activity, /api/v1/articles/<id>/analyze |
| `what-the-fact/consumer/static/canada-provinces.geojson` | Create | Statistics Canada province boundaries (simplified) |
| `what-the-fact/consumer/templates/index.html` | Modify | 3-zone homepage |
| `what-the-fact/consumer/templates/article.html` | Modify | Bias panel + fact-check panel + Deep Dive + bylines |
| `what-the-fact/consumer/templates/team.html` | Create | AI newsroom team page |
| `what-the-fact/consumer/routes.py` | Modify | Add /team route |
| `what-the-fact/consumer/static/css/wtf-main.css` | Create/Modify | Shared styles for new layout |

---

### Task 1: wtf-tech new API endpoints

**Files:**
- Modify: `what-the-fact/tech/routes.py`

- [ ] **Step 1: Add map-data endpoint.**

```python
@bp.get("/api/v1/map-data")
def map_data():
    """Province-level news stats for Canada map.

    Returns:
    {
        "provinces": {
            "ON": { "articles": 23, "avg_bias": -0.15, "band": "center-left", "dominant_outlet": "CBC" },
            ...
        }
    }
    """
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        rows = c.execute(text(f"""
            SELECT
                a.province_code,
                COUNT(*) AS cnt,
                AVG(bs.score) AS avg_score,
                MODE() WITHIN GROUP (ORDER BY s.slug) AS top_outlet
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            LEFT JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.published_at >= NOW() - INTERVAL '24 hours'
              AND a.province_code IS NOT NULL
            GROUP BY a.province_code
        """)).fetchall()

    def _band(score):
        if score is None: return "center"
        s = float(score)
        if s < -0.6: return "left"
        if s < -0.2: return "center-left"
        if s < 0.2:  return "center"
        if s < 0.6:  return "center-right"
        return "right"

    provinces = {}
    for row in rows:
        pc = row.province_code
        if pc:
            provinces[pc] = {
                "articles": row.cnt,
                "avg_bias": round(float(row.avg_score or 0), 3),
                "band": _band(row.avg_score),
                "dominant_outlet": row.top_outlet or "",
            }

    return jsonify({"provinces": provinces})
```

- [ ] **Step 2: Add agent-activity endpoint.**

```python
@bp.get("/api/v1/agent-activity")
def agent_activity():
    """Recent AI agent analysis activity for editorial desk feed.

    Returns last 10 analysis events across all articles.
    """
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        bias_rows = c.execute(text(f"""
            SELECT 'B.I.A.S.' AS agent, a.title, bs.band, bs.created_at AS ts,
                   s.name AS source_name
            FROM {S}.bias_scores bs
            JOIN {S}.articles a ON a.id = bs.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE bs.analyzed_by = 'BIAS_LLM'
            ORDER BY bs.created_at DESC LIMIT 5
        """)).fetchall()

        fact_rows = c.execute(text(f"""
            SELECT 'V.E.R.I.F.Y.' AS agent, a.title, fc.overall_verdict AS band,
                   fc.created_at AS ts, s.name AS source_name
            FROM {S}.fact_checks fc
            JOIN {S}.articles a ON a.id = fc.article_id
            JOIN {S}.sources s ON s.id = a.source_id
            WHERE fc.analyzed_by = 'VERIFY_LLM'
            ORDER BY fc.created_at DESC LIMIT 5
        """)).fetchall()

    events = [
        {"agent": r.agent, "title": r.title[:80], "result": r.band, "source": r.source_name,
         "ts": r.ts.isoformat() if r.ts else None}
        for r in list(bias_rows) + list(fact_rows)
    ]
    events.sort(key=lambda x: x["ts"] or "", reverse=True)
    return jsonify({"events": events[:10]})
```

- [ ] **Step 3: Add on-demand article analyze endpoint.**

```python
@bp.post("/api/v1/articles/<int:article_id>/analyze")
def analyze_article(article_id: int):
    """Trigger on-demand AI analysis for an article not yet AI-analyzed."""
    from flask import jsonify
    import os, requests as _requests
    HUB_URL = os.environ.get("WTF_HUB_URL", "")
    HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
    if not HUB_URL or not HUB_TOKEN:
        return jsonify({"ok": False, "error": "hub not configured"}), 503

    S = _schema()
    with _db().connect() as c:
        article = c.execute(text(f"""
            SELECT id, title, body, source_id FROM {S}.articles WHERE id = :id
        """), {"id": article_id}).fetchone()

    if not article:
        return jsonify({"ok": False, "error": "article not found"}), 404

    results = {}
    for task in ("bias", "factcheck", "geo"):
        try:
            resp = _requests.post(
                f"{HUB_URL}/tools/wtf-hub/api/analyze",
                json={"task": task, "article_id": article_id,
                      "title": article.title or "", "body": article.body or ""},
                headers={"Authorization": f"Bearer {HUB_TOKEN}"},
                timeout=90,
            )
            data = resp.json()
            if data.get("ok"):
                results[task] = data.get("result")
        except Exception:
            pass

    return jsonify({"ok": True, "results": results, "article_id": article_id})
```

- [ ] **Step 4: Commit.**

```bash
git add what-the-fact/tech/routes.py
git commit -m "feat(wtf-tech): map-data + agent-activity + on-demand analyze endpoints"
```

---

### Task 2: Statistics Canada GeoJSON + Homepage Template

**Files:**
- Create: `what-the-fact/consumer/static/canada-provinces.geojson`
- Modify: `what-the-fact/consumer/templates/index.html`

- [ ] **Step 1: Download simplified Canada GeoJSON.**

```bash
curl -sL "https://raw.githubusercontent.com/codeforgermany/click_that_hood/main/public/data/canada.geojson" \
  -o what-the-fact/consumer/static/canada-provinces.geojson
# Verify it has province features
python3 -c "import json; d=json.load(open('what-the-fact/consumer/static/canada-provinces.geojson')); print('Features:', len(d['features']))"
```

Expected: Features: 13

- [ ] **Step 2: Rewrite `what-the-fact/consumer/templates/index.html`.**

The full template must implement the 3-zone layout: Canada map (top, full-width), editorial desk (left), news feed (right). Key Jinja2 variables available: `articles` (list), `sources` (list). JavaScript fetches map-data and agent-activity from wtf-tech API.

The template must include:
- `<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">`
- `<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>`
- A `<div id="wtf-canada-map" style="height:300px"></div>`
- JavaScript that fetches `/api/v1/map-data` from wtf-tech, creates a Leaflet map using the bundled GeoJSON, colours provinces by bias band, and adds article pins
- An editorial desk section showing `agent-activity` feed
- A news feed section showing `articles` with bias band colour coding

Implement the template following the design in the spec and the homepage mockup approved during brainstorming. Use CSS variables `--wtf-left: #3b82f6; --wtf-center-left: #93c5fd; --wtf-center: #9ca3af; --wtf-center-right: #fca5a5; --wtf-right: #ef4444;` for bias colours.

- [ ] **Step 3: Commit.**

```bash
git add what-the-fact/consumer/static/canada-provinces.geojson \
        what-the-fact/consumer/templates/index.html
git commit -m "feat(wtf-consumer): Leaflet Canada map + 3-zone editorial homepage"
```

---

### Task 3: Article page with bias/factcheck/bylines/Deep Dive

**Files:**
- Modify: `what-the-fact/consumer/templates/article.html`

- [ ] **Step 1: Rewrite `what-the-fact/consumer/templates/article.html`.**

The article page must display:
1. Article title, source name, published date, province tag
2. Bias panel: score bar (-1 to +1), band label, rationale (if AI-analyzed), trigger phrases
3. Fact-check panel: claim list with verdict chips (if AI-analyzed), overall verdict
4. "Analyzed by" bylines: agent name + role (B.I.A.S. / V.E.R.I.F.Y. / L.O.C.A.L.)
5. If NOT ai_analyzed: "Quick Score" badge + "Deep Dive" button
6. If ai_analyzed: "AI Analyzed" badge
7. Deep Dive button: `onclick="deepDive({{ a.id }})"` calls `POST /api/v1/articles/<id>/analyze`
8. "How we scored this" details block (per Plan 3 Task 4)
9. Cross-source: "N other outlets covered this story" link to `/clusters/<cluster_id>`

The Jinja2 context from `routes.py` must be updated to pass: `a` (article dict with bias_score, bias_band, bias_rationale, fact_check_claims, overall_verdict, ai_analyzed, lat, lng, province_code).

- [ ] **Step 2: Update `what-the-fact/consumer/routes.py` article view to include joined data.**

```python
@bp.get("/article/<int:article_id>")
def article(article_id):
    WTF_TECH = os.environ.get("WTF_TECH_URL", "https://what-the-fact.tech")
    import requests as _requests
    resp = _requests.get(f"{WTF_TECH}/api/v1/articles/{article_id}", timeout=10)
    if not resp.ok:
        return "Article not found", 404
    article_data = resp.json()
    return render_template("article.html", a=article_data)
```

- [ ] **Step 3: Commit.**

```bash
git add what-the-fact/consumer/templates/article.html \
        what-the-fact/consumer/routes.py
git commit -m "feat(wtf-consumer): article page bias panel + fact-check + agent bylines + Deep Dive"
```

---

### Task 4: /team page

**Files:**
- Create: `what-the-fact/consumer/templates/team.html`
- Modify: `what-the-fact/consumer/routes.py`

- [ ] **Step 1: Add `/team` route to `what-the-fact/consumer/routes.py`.**

```python
TEAM_AGENTS = [
    {"name": "F.A.C.T.", "full": "Factual Analysis, Credibility & Transparency",
     "role": "Director & Orchestrator", "model": "gemma3:12b",
     "description": "F.A.C.T. leads every ingest cycle — selecting the stories most worth investigating deeply, coordinating the team, and ensuring coverage is fair and complete.",
     "portrait": "/static/portraits/fact.png"},
    {"name": "B.I.A.S.", "full": "Balanced Information Analysis & Scoring",
     "role": "Bias Analyst", "model": "gemma2:9b",
     "description": "B.I.A.S. reads every priority article and scores it on the political spectrum, surfacing the trigger phrases and framing choices that reveal editorial perspective.",
     "portrait": "/static/portraits/bias.png"},
    {"name": "V.E.R.I.F.Y.", "full": "Verification, Evidence Review & Integrity",
     "role": "Fact-Checker", "model": "gemma2:9b",
     "description": "V.E.R.I.F.Y. extracts verifiable claims from each article and assigns a verdict — verified, mixed, disputed, or unverifiable — with reasoning.",
     "portrait": "/static/portraits/verify.png"},
    {"name": "L.O.C.A.L.", "full": "Local Observer, Coverage & Area Liaison",
     "role": "Geographic Intelligence Analyst", "model": "llama3.2:3b",
     "description": "L.O.C.A.L. maps every story to a Canadian province, tracks coverage gaps across regions, and identifies news deserts where communities go unheard.",
     "portrait": "/static/portraits/local.png"},
    {"name": "I.N.K.", "full": "Investigative News & Knowledge",
     "role": "News Investigator (coming soon)", "model": "dolphin3",
     "description": "I.N.K. will detect investigative story threads across article clusters — finding the through-line when the same story unfolds across days and outlets.",
     "portrait": "/static/portraits/ink.png"},
    {"name": "D.R.A.F.T.", "full": "Data Reduction & Factual Translation",
     "role": "Staff Writer (coming soon)", "model": "dolphin3",
     "description": "D.R.A.F.T. will generate WTF editorial summaries — translating dense news cycles into plain-language explainers.",
     "portrait": "/static/portraits/draft.png"},
    {"name": "P.U.B.L.I.S.H.", "full": "Publish & Unified Broadcasting",
     "role": "Broadcast Editor (coming soon)", "model": "mistral:7b",
     "description": "P.U.B.L.I.S.H. will push top stories to social media and newsletter subscribers, bringing AI journalism to where Canadians actually consume news.",
     "portrait": "/static/portraits/publish.png"},
]

@bp.get("/team")
def team():
    return render_template("team.html", agents=TEAM_AGENTS)
```

- [ ] **Step 2: Create `what-the-fact/consumer/templates/team.html`.**

The template iterates `agents` and renders a card grid. Each card shows:
- Portrait image (from /static/portraits/ — use existing Media Studio portraits if available, else placeholder)
- Agent name (large, coloured)
- Acronym expansion
- Role
- Model badge
- Description
- "Coming soon" badge if role contains "coming soon"

Include an A.U.R.O.R.A. teaser card at the end:
```html
<div class="wtf-team-card wtf-team-card--teaser">
  <div class="wtf-team-portrait-placeholder">🌌</div>
  <h3>A.U.R.O.R.A.</h3>
  <p class="wtf-team-expansion">Atmospheric & Universal Resource for Observation, Research & Analysis</p>
  <span class="wtf-team-badge">Coming Phase 2</span>
  <p>Environment Canada + NASA EarthData + NOAA. Weather intelligence integrated into every story — because in Canada, the weather IS the news.</p>
</div>
```

- [ ] **Step 3: Commit.**

```bash
git add what-the-fact/consumer/templates/team.html \
        what-the-fact/consumer/routes.py
git commit -m "feat(wtf-consumer): /team page — AI newsroom showcase + A.U.R.O.R.A. teaser"
```

---

### Task 5: VPS rebuild + smoke tests

- [ ] **Step 1: Rebuild wtf-consumer and wtf-tech on VPS.**

```bash
rsync -az -e "ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no" \
  /mnt/archie_brain/what-the-fact/ kytran@76.13.107.109:/opt/archie-products/what-the-fact/

ssh -i ~/.ssh/repair_bay_deploy kytran@76.13.107.109 "
cd /opt/archie-products/what-the-fact

docker build -f Dockerfile.tech -t wtf-tech:pr2 .
docker stop wtf_tech && docker rm wtf_tech
docker run -d --name wtf_tech --network what-the-fact_default \
  --env-file .env -p 8104:8104 wtf-tech:pr2

docker build -f Dockerfile.consumer -t wtf-consumer:pr2 .
docker stop wtf_consumer && docker rm wtf_consumer
docker run -d --name wtf_consumer --network what-the-fact_default \
  --env-file .env -p 8103:8103 wtf-consumer:pr2
"
```

- [ ] **Step 2: Smoke tests.**

```bash
# Homepage renders
curl -sf https://what-the-fact.com | grep -q "wtf-canada-map" && echo "map div: OK"

# Map data API returns province data
curl -sf https://what-the-fact.tech/api/v1/map-data | python3 -c "
import sys,json; d=json.load(sys.stdin); assert 'provinces' in d; print('map-data: OK, provinces:', list(d['provinces'].keys())[:3])
"

# Agent activity API
curl -sf https://what-the-fact.tech/api/v1/agent-activity | python3 -c "
import sys,json; d=json.load(sys.stdin); print('agent-activity: OK, events:', len(d.get('events',[])))
"

# Team page
curl -sf https://what-the-fact.com/team | grep -q "F.A.C.T." && echo "/team: OK"
```

---

## Success Criteria

- Canada map renders with correct Leaflet province shapes (from Statistics Canada GeoJSON)
- Province heat updates on /api/v1/map-data response
- Article pins appear within 30 min of ingest (lat/lng from PR 1)
- Agent activity feed on editorial desk shows last 10 B.I.A.S. + V.E.R.I.F.Y. events
- Article page shows bias panel, fact-check panel, agent bylines
- Deep Dive button triggers on-demand analysis
- /team page shows all 7 agents + A.U.R.O.R.A. teaser
