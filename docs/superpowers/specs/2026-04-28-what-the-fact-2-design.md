# What The Fact 2.0 — AI News Team + Radical Transparency Design

**Goal:** Transform what-the-fact.com from a data pipeline demo into a real Canadian AI newsroom — News & Media agents wired into the pipeline, Radical Transparency scoring, Leaflet Canada map with accurate province shapes, and the AI team as the editorial identity of the site.

**Architecture:** Three sequential PRs. PR 1 upgrades the ingest pipeline (F.A.C.T. orchestrator, B.I.A.S. + V.E.R.I.F.Y. LLM analysis, L.O.C.A.L. geolocation). PR 2 rebuilds the consumer site (Canada map, editorial desk homepage, agent bylines). PR 3 ships Radical Transparency (methodology page + live scorer on what-the-fact.tech).

**Tech Stack:** Python (wtf-ingest), Flask (wtf-consumer, wtf-tech), Leaflet.js + Statistics Canada GeoJSON (Canada map), Bridge dispatch (agent LLM calls), PostgreSQL (wtf schema on VPS), Environment Canada RSS + NASA EarthData (A.U.R.O.R.A., Phase 2).

---

## Project #293 — Task references
- #2393 Full spec (this doc)
- #2394 PR 1: Pipeline
- #2395 PR 3: Radical Transparency
- #2396 Canada map (part of PR 2)
- #2397 PR 2: Consumer redesign + news team showcase

---

## Audience

Two-tier design:

| Tier | Who | What they see |
|------|-----|---------------|
| General public | Canadians checking bias | Clean homepage, Canada map, simple bias band per article, agent bylines |
| Researchers / journalists | Media critics, academics | Deep Dive panel with full AI reasoning, claim-by-claim breakdown, Radical Transparency methodology, live article scorer |

---

## News & Media Team — Roles in WTF 2.0

| Agent | Model | WTF Role |
|-------|-------|----------|
| **F.A.C.T.** | gemma3:12b | Orchestrator — priority picker per ingest cycle |
| **B.I.A.S.** | gemma2:9b | LLM bias scoring (priority articles) |
| **V.E.R.I.F.Y.** | gemma2:9b | LLM fact-check (priority articles) |
| **L.O.C.A.L.** | llama3.2:3b | Geo extraction + coverage analytics (all articles) |
| **I.N.K.** | dolphin3 | Future: investigative story thread detection |
| **D.R.A.F.T.** | dolphin3 | Future: WTF editorial summaries |
| **P.U.B.L.I.S.H.** | mistral:7b | Future: social/newsletter distribution |
| **A.U.R.O.R.A.** | qwen2.5:7b | Phase 2: weather intelligence (Environment Canada + NASA + NOAA) |

**L.O.C.A.L.** = Local Observer, Coverage & Area Liaison — new agent, created as part of PR 1.
**A.U.R.O.R.A.** = Atmospheric & Universal Resource for Observation, Research & Analysis — Phase 2.

---

## PR 1 — Pipeline: AI Agents + Geolocation

### F.A.C.T. Orchestrator

Runs every 30-min ingest cycle after heuristic pass completes:

```python
# Priority scoring per article
def score_priority(article, cross_source_overlap, heuristic_bias_score):
    score = 0
    if cross_source_overlap >= 3:  # same story in 3+ outlets
        score += 3
    if abs(heuristic_bias_score) > 0.5:  # high heuristic bias
        score += 2
    if any(kw in article["title"].lower() for kw in BREAKING_KEYWORDS):
        score += 1
    return score
```

Top 5-10 per cycle get queued for B.I.A.S. + V.E.R.I.F.Y. via Bridge dispatch.

### B.I.A.S. Agent

Input: article title + body + source slug
Output:
```json
{
  "score": -0.4,
  "band": "center-left",
  "rationale": "Article uses framing language consistent with center-left perspective...",
  "trigger_phrases": ["job-killing regulations", "vulnerable communities"],
  "confidence": 0.82,
  "analyzed_by": "BIAS_LLM"
}
```
Stored in `wtf.bias_scores` with `analyzed_by = 'BIAS_LLM'` (vs `'heuristic'`).

### V.E.R.I.F.Y. Agent

Input: article body
Output:
```json
{
  "claims": [
    {"text": "unemployment dropped to 5.8%", "verdict": "verified", "reasoning": "StatsCan Q3 2025 report confirms 5.8%"},
    {"text": "worst inflation in 40 years", "verdict": "mixed", "reasoning": "True for 2022 peak but outdated for current context"}
  ],
  "overall_verdict": "mostly_true",
  "confidence": 0.76,
  "analyzed_by": "VERIFY_LLM"
}
```

### L.O.C.A.L. Agent (new)

Runs on ALL articles (lightweight, fast model):
```json
{
  "province_code": "ON",
  "city": "Toronto",
  "lat": 43.6532,
  "lng": -79.3832,
  "geo_scope": "provincial",
  "geo_confidence": 0.91
}
```
`geo_scope`: `national` | `provincial` | `municipal` | `international`

Weekly geo report (APScheduler job, Mondays 06:00 EDT):
- Province × outlet coverage matrix
- News deserts (provinces < expected coverage per population)
- Stored in `wtf.geo_reports`

### New DB columns (VPS migration 006)

```sql
ALTER TABLE wtf.articles ADD COLUMN province_code VARCHAR(2);
ALTER TABLE wtf.articles ADD COLUMN city VARCHAR(100);
ALTER TABLE wtf.articles ADD COLUMN lat DECIMAL(9,6);
ALTER TABLE wtf.articles ADD COLUMN lng DECIMAL(9,6);
ALTER TABLE wtf.articles ADD COLUMN geo_scope VARCHAR(20) DEFAULT 'national';
ALTER TABLE wtf.articles ADD COLUMN ai_analyzed BOOLEAN DEFAULT FALSE;

ALTER TABLE wtf.bias_scores ADD COLUMN analyzed_by VARCHAR(20) DEFAULT 'heuristic';
ALTER TABLE wtf.fact_checks ADD COLUMN analyzed_by VARCHAR(20) DEFAULT 'heuristic';

CREATE TABLE IF NOT EXISTS wtf.geo_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    province_coverage JSONB,
    outlet_province_matrix JSONB,
    news_deserts JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_province ON wtf.articles(province_code);
CREATE INDEX IF NOT EXISTS idx_articles_ai ON wtf.articles(ai_analyzed);
```

### Bridge dispatch from wtf-ingest

wtf-ingest (VPS container) calls the hub platform Bridge via HTTP:
```
POST https://platform.kytranempowerment.com/api/bridge/dispatch
{
  "capability": "bias_analysis",
  "agent_id": <BIAS_AGENT_ID>,
  "prompt": "<article title + body>",
  "module_id": "wtf_ingest"
}
```
The hub routes to B.I.A.S./V.E.R.I.F.Y./L.O.C.A.L. via existing dispatcher.

---

## PR 2 — Consumer Redesign: what-the-fact.com

### Homepage Layout

Three zones:

**Zone 1 — Canada Live Map** (full-width, top)
- Leaflet.js + Statistics Canada GeoJSON (official province boundaries)
- Province fill colour: bias concentration (blue=left, grey=center, red=right)
- Province opacity: news volume (more stories = more opaque)
- Article pins: coloured dots at geocoded lat/lng, cluster at zoom-out
- Hover province: tooltip "Ontario — 23 stories today, avg bias: center-left"
- Click pin: article card slides in from right
- A.U.R.O.R.A. Phase 2 slot: weather alert badge in province corner (reserved in DOM)

**Zone 2 — Editorial Desk** (below map, left ~38%)
- Live agent activity feed (last 5 actions with timestamp)
- F.A.C.T. Top Stories (5 AI-curated picks)
- Agent mini-cards: portrait + name + "analyzing now"

**Zone 3 — News Feed** (below map, right ~62%)
- Article cards: title, source, province, bias band (colour-coded)
- Filter bar: province | outlet | bias band | AI Analyzed only
- "AI Analyzed" badge vs "Quick Score" badge
- Infinite scroll, 30-min auto-refresh

### Article Page

- Full article display
- **Bias panel**: B.I.A.S. score bar + band + rationale + trigger phrases highlighted in text
- **Fact-check panel**: V.E.R.I.F.Y. claim list with verdict per claim
- **Analyzed by bylines**: agent portrait + name (or "Quick Score — not yet AI analyzed")
- **Deep Dive button**: triggers on-demand B.I.A.S. + V.E.R.I.F.Y. if not already done; result cached
- **Cross-source**: "3 other outlets covered this story — compare bias →"
- **How we scored this**: expandable panel linking to /transparency

### /team page

Agent cards for all 7 current agents + A.U.R.O.R.A. teaser:
- Sci-fi portrait (from Media Studio)
- Acronym expansion
- Role in WTF pipeline
- "Articles analyzed today: N"
- Link to their analysis examples

---

## PR 3 — Radical Transparency: what-the-fact.tech

### /transparency (methodology page)

Fully public documentation:
- Bias scoring: trigger term list + weights, band thresholds, heuristic vs LLM criteria
- Fact-check: claim extraction patterns, source credibility whitelist, verdict logic
- Geolocation: province extraction rules, L.O.C.A.L. agent prompt
- Hybrid threshold: what makes an article "priority" for AI analysis
- Agent model cards: which model, what it was prompted with, known limitations
- Error reporting form: "Flag a score you think is wrong" → routes to V.E.R.I.F.Y. queue

### /score (live article scorer)

```
POST /api/v1/score
{ "url": "https://...", "text": "..." }

Response:
{
  "bias": { "score": -0.3, "band": "center-left", "rationale": "...", "trigger_phrases": [...] },
  "factcheck": { "claims": [...], "overall_verdict": "mostly_true" },
  "geo": { "province_code": "QC", "city": "Montreal" },
  "analyzed_by": "BIAS_LLM + VERIFY_LLM + LOCAL_LLM",
  "processing_ms": 4200
}
```

Rate limits: 5 req/day unauthenticated, unlimited with KBS Pro subscription.

---

## A.U.R.O.R.A. — Phase 2

**Agent**: A.U.R.O.R.A. (Atmospheric & Universal Resource for Observation, Research & Analysis)
**Sources**: Environment Canada RSS weather alerts + NASA EarthData satellite API + NOAA forecasts
**Function**:
- Provincial weather alert extraction (severe, warning, watch, advisory)
- Satellite-derived ground truth (wildfire smoke, flood extent, ice coverage)
- Long-range prediction (LLM + NASA ensemble model data)
- Correlation: weather alert → news story spike detection

**Map integration**: Province corner badge showing alert severity. Click → weather detail panel.

Phase 2 is architecturally reserved — the map DOM and DB have placeholder hooks from day one.

---

## Success Criteria

**PR 1:**
- F.A.C.T. picks 5-10 priority articles per cycle
- B.I.A.S. + V.E.R.I.F.Y. return structured JSON via Bridge dispatch
- L.O.C.A.L. extracts province_code for ≥80% of articles
- wtf.articles has lat/lng/province_code populated
- Weekly geo_reports job runs

**PR 2:**
- Canada map renders with correct Leaflet + Statistics Canada province shapes
- Article pins appear within 30min of ingest
- Agent activity feed shows live actions
- Deep Dive button triggers on-demand analysis

**PR 3:**
- /transparency page fully documents every scoring method
- /score endpoint processes URLs and text, returns full analysis
- "How we scored this" panel on every article page
- Error flagging routes to V.E.R.I.F.Y. queue
