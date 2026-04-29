# WTF 2.0 — PR 1: AI Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire F.A.C.T. orchestrator, B.I.A.S. + V.E.R.I.F.Y. LLM analysis, and L.O.C.A.L. geolocation into the wtf-ingest pipeline, replacing heuristics for priority articles.

**Architecture:** New `ingest/ai_dispatcher.py` posts to hub endpoint `POST /tools/wtf-hub/api/analyze`; `ingest/orchestrator.py` implements F.A.C.T. priority picker; `ingest/geocoder.py` wraps L.O.C.A.L.; `run.py` calls orchestrator after heuristic pass; DB migration 006 adds geo columns and geo_reports table.

**Tech Stack:** Python 3.11 (wtf-ingest), SQLAlchemy + text(), requests (hub HTTP), PostgreSQL wtf schema, Flask Blueprint (hub wtf-hub module), Bridge dispatcher (platform).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `what-the-fact/migrations/006_ai_pipeline.sql` | Create | DB columns + geo_reports table |
| `what-the-fact/ingest/ai_dispatcher.py` | Create | HTTP client → hub /tools/wtf-hub/api/analyze |
| `what-the-fact/ingest/orchestrator.py` | Create | F.A.C.T. priority picker |
| `what-the-fact/ingest/geocoder.py` | Create | L.O.C.A.L. geo extraction wrapper |
| `what-the-fact/ingest/persist.py` | Modify | Save province_code, city, lat, lng, ai_analyzed |
| `what-the-fact/ingest/run.py` | Modify | Wire orchestrator after heuristic pass |
| `platform_v2/tools/wtf_hub/__init__.py` | Create | Flask Blueprint for hub-side WTF dispatch |
| `platform_v2/tools/wtf_hub/routes.py` | Create | POST /tools/wtf-hub/api/analyze |
| `platform_v2/module_registry.py` | Modify | Register wtf_hub (internal only) |

---

### Task 1: DB Migration 006 (VPS)

**Files:**
- Create: `what-the-fact/migrations/006_ai_pipeline.sql`

- [ ] **Step 1: Write the migration.**

```sql
-- 006_ai_pipeline.sql — WTF 2.0 AI pipeline columns + geo_reports

ALTER TABLE wtf.articles
    ADD COLUMN IF NOT EXISTS province_code VARCHAR(2),
    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
    ADD COLUMN IF NOT EXISTS lat DECIMAL(9,6),
    ADD COLUMN IF NOT EXISTS lng DECIMAL(9,6),
    ADD COLUMN IF NOT EXISTS geo_scope VARCHAR(20) DEFAULT 'national',
    ADD COLUMN IF NOT EXISTS ai_analyzed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ai_analyzed_at TIMESTAMP;

ALTER TABLE wtf.bias_scores
    ADD COLUMN IF NOT EXISTS analyzed_by VARCHAR(20) DEFAULT 'heuristic',
    ADD COLUMN IF NOT EXISTS trigger_phrases JSONB,
    ADD COLUMN IF NOT EXISTS confidence DECIMAL(4,3);

ALTER TABLE wtf.fact_checks
    ADD COLUMN IF NOT EXISTS analyzed_by VARCHAR(20) DEFAULT 'heuristic',
    ADD COLUMN IF NOT EXISTS claims JSONB,
    ADD COLUMN IF NOT EXISTS overall_verdict VARCHAR(50);

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
CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_reports_date ON wtf.geo_reports(report_date);
```

- [ ] **Step 2: Apply on VPS.**

```bash
# Copy migration to VPS, run against wtf_db
docker cp what-the-fact/migrations/006_ai_pipeline.sql wtf_db:/tmp/006.sql
ssh -i ~/.ssh/repair_bay_deploy kytran@76.13.107.109 \
  "docker exec wtf_db psql -U wtfuser -d wtf -f /tmp/006.sql"
```

Expected output: `ALTER TABLE` x3, `CREATE TABLE`, `CREATE INDEX` x3

- [ ] **Step 3: Verify columns exist.**

```bash
ssh -i ~/.ssh/repair_bay_deploy kytran@76.13.107.109 \
  "docker exec wtf_db psql -U wtfuser -d wtf -c '\d wtf.articles'" | grep -E "province|city|lat|lng|ai_analyzed"
```

Expected: 5 new columns visible

- [ ] **Step 4: Commit.**

```bash
git add what-the-fact/migrations/006_ai_pipeline.sql
git commit -m "feat(wtf): migration 006 — AI pipeline columns + geo_reports table"
```

---

### Task 2: L.O.C.A.L. Agent + Hub wtf-hub Blueprint

**Files:**
- Modify: Platform DB (agent seed via psql)
- Create: `platform_v2/tools/wtf_hub/__init__.py`
- Create: `platform_v2/tools/wtf_hub/routes.py`
- Modify: `platform_v2/module_registry.py`

- [ ] **Step 1: Seed L.O.C.A.L. agent in platform DB.**

```bash
docker exec archie_database psql -U archie -d archie -c "
INSERT INTO agents (name, display_name, title, department, model, worker_type, shift_state,
                    bio, system_prompt)
VALUES (
  'L.O.C.A.L.',
  'L.O.C.A.L.',
  'Geographic Intelligence Analyst',
  'News & Media',
  'llama3.2:3b',
  'ai',
  'active',
  'L.O.C.A.L. — Local Observer, Coverage & Area Liaison. Geolocation intelligence for What The Fact. Extracts province, city, and coordinates from Canadian news articles. Tracks coverage patterns by province and outlet. Identifies news deserts.',
  'You are L.O.C.A.L. (Local Observer, Coverage & Area Liaison), geographic intelligence analyst for What The Fact. Given a news article, extract the primary Canadian location. Return ONLY valid JSON with keys: province_code (2-letter CA code or null), city (string or null), lat (float or null), lng (float or null), geo_scope (national|provincial|municipal|international), geo_confidence (0.0-1.0). If no clear Canadian location, set geo_scope national and leave province_code null.'
)
ON CONFLICT (name) DO UPDATE SET
  model = EXCLUDED.model,
  system_prompt = EXCLUDED.system_prompt;
SELECT id, name, model FROM agents WHERE name = 'L.O.C.A.L.';
"
```

Expected: agent row returned with an id

- [ ] **Step 2: Add deploy_static + deploy_vps to agent_skills for L.O.C.A.L. (skip — L.O.C.A.L. uses geo capability, wire later).**

Skip this step — skill wiring for geo capability is post-PR scope.

- [ ] **Step 3: Create `platform_v2/tools/wtf_hub/__init__.py`.**

```python
"""WTF Hub — internal Bridge dispatch surface for What The Fact ingest pipeline."""

from flask import Blueprint

wtf_hub_bp = Blueprint("wtf_hub", __name__, url_prefix="/tools/wtf-hub")

from . import routes  # noqa: E402, F401
```

- [ ] **Step 4: Create `platform_v2/tools/wtf_hub/routes.py`.**

```python
"""WTF Hub routes — internal API for wtf-ingest to dispatch to News & Media agents."""
from __future__ import annotations

import logging
import os

from flask import jsonify, request
from flask_login import login_required

from . import wtf_hub_bp

logger = logging.getLogger(__name__)

# Token for ingest → hub auth (set WTF_HUB_TOKEN in both .env files)
_HUB_TOKEN = os.getenv("WTF_HUB_TOKEN", "")

# Agent IDs for News & Media team
_AGENT_IDS = {
    "bias": None,      # B.I.A.S. — resolved at runtime
    "factcheck": None, # V.E.R.I.F.Y. — resolved at runtime
    "geo": None,       # L.O.C.A.L. — resolved at runtime
}


def _get_agent_id(name: str) -> int | None:
    try:
        from database import get_db_cursor
        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT id FROM agents WHERE name = %s", (name,))
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception:
        return None


def _resolve_agents():
    if not _AGENT_IDS["bias"]:
        _AGENT_IDS["bias"] = _get_agent_id("B.I.A.S.")
    if not _AGENT_IDS["factcheck"]:
        _AGENT_IDS["factcheck"] = _get_agent_id("V.E.R.I.F.Y.")
    if not _AGENT_IDS["geo"]:
        _AGENT_IDS["geo"] = _get_agent_id("L.O.C.A.L.")


def _auth_ok(req) -> bool:
    if not _HUB_TOKEN:
        return True  # no token = open (dev mode only)
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {_HUB_TOKEN}"


@wtf_hub_bp.route("/api/analyze", methods=["POST"])
def analyze():
    """Dispatch a WTF analysis task to the appropriate News & Media agent.

    Auth: Authorization: Bearer <WTF_HUB_TOKEN>

    Request JSON:
      task        (str) — "bias" | "factcheck" | "geo"
      article_id  (int) — wtf article id (0 for on-demand scoring)
      title       (str) — article title
      body        (str) — article body (first 3000 chars used)
      source_slug (str) — e.g. "cbc_english"

    Response JSON:
      { "ok": true, "result": { ...agent output... } }
    """
    if not _auth_ok(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    task = data.get("task", "")
    if task not in ("bias", "factcheck", "geo"):
        return jsonify({"ok": False, "error": f"unknown task: {task}"}), 400

    title = (data.get("title") or "")[:200]
    body = (data.get("body") or "")[:3000]
    source_slug = data.get("source_slug", "")

    if not title and not body:
        return jsonify({"ok": False, "error": "title or body required"}), 400

    _resolve_agents()

    prompts = {
        "bias": (
            f"Analyze the bias of this Canadian news article.\n\n"
            f"Source: {source_slug}\nTitle: {title}\nBody: {body}\n\n"
            "Return ONLY valid JSON: {score: float -1 to 1, band: string, "
            "rationale: string, trigger_phrases: list[str], confidence: float}"
        ),
        "factcheck": (
            f"Fact-check the claims in this Canadian news article.\n\n"
            f"Title: {title}\nBody: {body}\n\n"
            "Return ONLY valid JSON: {claims: [{text, verdict, reasoning}], "
            "overall_verdict: string, confidence: float}. "
            "Verdicts: verified | mixed | disputed | unverifiable"
        ),
        "geo": (
            f"Title: {title}\nBody: {body[:1000]}"
        ),
    }

    agent_names = {"bias": "B.I.A.S.", "factcheck": "V.E.R.I.F.Y.", "geo": "L.O.C.A.L."}
    agent_id = _AGENT_IDS.get(task)
    if not agent_id:
        return jsonify({"ok": False, "error": f"agent not found for task: {task}"}), 503

    try:
        from tools.department_hq.services.department_dispatcher import dispatch
        result = dispatch(
            capability="conversation" if task != "geo" else "conversation",
            prompt=prompts[task],
            module_id="wtf_hub",
            agent_id_override=agent_id,
            json_mode=True,
        )
        if result.success:
            import json as _json
            try:
                parsed = _json.loads(result.response)
            except Exception:
                parsed = {"raw": result.response}
            return jsonify({"ok": True, "result": parsed, "agent": agent_names[task]})
        else:
            return jsonify({"ok": False, "error": result.error or "dispatch failed"}), 500
    except Exception as exc:
        logger.exception("[WTFHub] dispatch failed for task=%s", task)
        return jsonify({"ok": False, "error": str(exc)}), 500
```

- [ ] **Step 5: Register in `module_registry.py` (disabled, internal only).**

Find where `id="faith"` was added and add after it:

```python
        ModuleDefinition(
            id="wtf_hub",
            name="WTF Hub",
            description="Internal Bridge dispatch surface for What The Fact ingest pipeline",
            icon="globe",
            category=ModuleCategory.AI_COMMAND,
            route="/tools/wtf-hub",
            blueprint_import="tools.wtf_hub.routes:wtf_hub_bp",
            status=ModuleStatus.ENABLED,
            health_check=None,
            required_permissions=["admin"],
        ),
```

- [ ] **Step 6: Restart hub and test analyze endpoint.**

```bash
docker compose restart archie_platform && sleep 6
# Test bias analysis (admin auth needed for /tools/wtf-hub)
# The endpoint is protected — test via direct dispatch or curl with admin session
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.wtf_hub.routes import _resolve_agents, _AGENT_IDS
_resolve_agents()
print('Agent IDs resolved:', _AGENT_IDS)
"
```

Expected: BIAS, VERIFY, LOCAL agent IDs printed

- [ ] **Step 7: Commit.**

```bash
git add platform_v2/tools/wtf_hub/__init__.py \
        platform_v2/tools/wtf_hub/routes.py \
        platform_v2/module_registry.py
git commit -m "feat(wtf-hub): hub-side dispatch Blueprint for WTF ingest agent calls"
```

---

### Task 3: ingest/ai_dispatcher.py + ingest/orchestrator.py + ingest/geocoder.py

**Files:**
- Create: `what-the-fact/ingest/ai_dispatcher.py`
- Create: `what-the-fact/ingest/orchestrator.py`
- Create: `what-the-fact/ingest/geocoder.py`

- [ ] **Step 1: Create `what-the-fact/ingest/ai_dispatcher.py`.**

```python
"""ai_dispatcher.py — HTTP client calling hub /tools/wtf-hub/api/analyze."""
import logging
import os
import requests

logger = logging.getLogger("wtf-ingest")

_HUB_URL = os.environ.get("WTF_HUB_URL", "https://platform.kytranempowerment.com")
_HUB_TOKEN = os.environ.get("WTF_HUB_TOKEN", "")
_TIMEOUT = int(os.environ.get("WTF_HUB_TIMEOUT", "90"))
_ENABLED = bool(_HUB_URL and _HUB_TOKEN)


def analyze(task: str, article_id: int, title: str, body: str, source_slug: str = "") -> dict | None:
    """Dispatch analysis task to hub. Returns parsed result dict or None on failure."""
    if not _ENABLED:
        logger.debug("ai_dispatcher: WTF_HUB_URL or WTF_HUB_TOKEN not set — skipping %s", task)
        return None
    try:
        resp = requests.post(
            f"{_HUB_URL}/tools/wtf-hub/api/analyze",
            json={
                "task": task,
                "article_id": article_id,
                "title": title,
                "body": body[:3000],
                "source_slug": source_slug,
            },
            headers={
                "Authorization": f"Bearer {_HUB_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        data = resp.json()
        if data.get("ok"):
            return data.get("result")
        logger.warning("ai_dispatcher: task=%s failed: %s", task, data.get("error"))
        return None
    except Exception as exc:
        logger.warning("ai_dispatcher: task=%s exception: %s", task, exc)
        return None
```

- [ ] **Step 2: Create `what-the-fact/ingest/geocoder.py`.**

```python
"""geocoder.py — L.O.C.A.L. geo extraction wrapper with province centroid fallback."""
import re
from .ai_dispatcher import analyze

# Province centroids for fallback when city not extracted
PROVINCE_CENTROIDS = {
    "AB": (53.9333, -116.5765), "BC": (53.7267, -127.6476),
    "MB": (56.4152, -98.7394),  "NB": (46.5653, -66.4619),
    "NL": (53.1355, -57.6604),  "NS": (44.6820, -63.7443),
    "NT": (64.2823, -119.1820), "NU": (70.2998, -83.1076),
    "ON": (51.2538, -85.3232),  "PE": (46.5107, -63.4168),
    "QC": (53.0000, -70.0000),  "SK": (52.9399, -106.4509),
    "YT": (64.2823, -135.0000),
}

VALID_PROVINCES = set(PROVINCE_CENTROIDS.keys())


def extract_geo(article_id: int, title: str, body: str) -> dict:
    """Extract geo info via L.O.C.A.L. agent. Falls back to heuristic if agent unavailable."""
    result = analyze("geo", article_id, title, body)
    if result and isinstance(result, dict) and result.get("province_code") in VALID_PROVINCES:
        pc = result["province_code"]
        if not result.get("lat") and pc in PROVINCE_CENTROIDS:
            result["lat"], result["lng"] = PROVINCE_CENTROIDS[pc]
        return result

    # Heuristic fallback: province name in title or first 500 chars of body
    text = f"{title} {body[:500]}".lower()
    province_patterns = {
        "ON": r"\b(ontario|toronto|ottawa|hamilton|london|windsor)\b",
        "QC": r"\b(quebec|montreal|laval|gatineau|longueuil)\b",
        "BC": r"\b(british columbia|vancouver|surrey|burnaby|victoria)\b",
        "AB": r"\b(alberta|calgary|edmonton|red deer|lethbridge)\b",
        "SK": r"\b(saskatchewan|regina|saskatoon)\b",
        "MB": r"\b(manitoba|winnipeg|brandon)\b",
        "NS": r"\b(nova scotia|halifax|dartmouth)\b",
        "NB": r"\b(new brunswick|moncton|saint john|fredericton)\b",
        "NL": r"\b(newfoundland|labrador|st\.? john's)\b",
        "PE": r"\b(prince edward island|pei|charlottetown)\b",
        "YT": r"\b(yukon|whitehorse)\b",
        "NT": r"\b(northwest territories|yellowknife)\b",
        "NU": r"\b(nunavut|iqaluit)\b",
    }
    for pc, pattern in province_patterns.items():
        if re.search(pattern, text):
            lat, lng = PROVINCE_CENTROIDS[pc]
            return {"province_code": pc, "city": None, "lat": lat, "lng": lng,
                    "geo_scope": "provincial", "geo_confidence": 0.5}
    return {"province_code": None, "city": None, "lat": None, "lng": None,
            "geo_scope": "national", "geo_confidence": 0.0}
```

- [ ] **Step 3: Create `what-the-fact/ingest/orchestrator.py`.**

```python
"""orchestrator.py — F.A.C.T. priority picker for AI deep-analysis."""
import logging
from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

BREAKING_KEYWORDS = [
    "breaking", "urgent", "alert", "emergency", "crisis",
    "shooting", "death", "killed", "explosion", "resign",
]
MAX_PRIORITY_PER_CYCLE = 10


def score_priority(title: str, heuristic_bias_score: float, cross_source_count: int) -> int:
    """Return an integer priority score (0 = no priority, higher = more important)."""
    score = 0
    if cross_source_count >= 3:
        score += 3
    if abs(heuristic_bias_score) > 0.5:
        score += 2
    title_lower = title.lower()
    if any(kw in title_lower for kw in BREAKING_KEYWORDS):
        score += 1
    return score


def pick_priority_articles(engine, schema: str, batch_article_ids: list[int]) -> list[int]:
    """Given this cycle's inserted article IDs, return up to MAX_PRIORITY_PER_CYCLE for AI analysis.

    Criteria:
    1. Score each article using score_priority()
    2. Return top MAX_PRIORITY_PER_CYCLE by score (minimum score 1)
    """
    if not batch_article_ids:
        return []

    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT a.id, a.title,
                       bs.score AS heuristic_score,
                       (
                           SELECT COUNT(DISTINCT a2.source_id)
                           FROM {schema}.articles a2
                           JOIN {schema}.story_clusters sc2 ON sc2.id = a2.cluster_id
                           JOIN {schema}.story_clusters sc ON sc.id = a.cluster_id
                           WHERE sc.id = sc2.id AND a2.id != a.id
                       ) AS cross_source_count
                FROM {schema}.articles a
                LEFT JOIN {schema}.bias_scores bs ON bs.article_id = a.id
                WHERE a.id = ANY(:ids) AND a.ai_analyzed = FALSE
            """),
            {"ids": batch_article_ids},
        ).fetchall()

    scored = []
    for row in rows:
        p = score_priority(
            row.title or "",
            float(row.heuristic_score or 0.0),
            int(row.cross_source_count or 0),
        )
        if p >= 1:
            scored.append((p, row.id))

    scored.sort(reverse=True)
    return [article_id for _, article_id in scored[:MAX_PRIORITY_PER_CYCLE]]
```

- [ ] **Step 4: Commit.**

```bash
git add what-the-fact/ingest/ai_dispatcher.py \
        what-the-fact/ingest/orchestrator.py \
        what-the-fact/ingest/geocoder.py
git commit -m "feat(wtf-ingest): ai_dispatcher + F.A.C.T. orchestrator + L.O.C.A.L. geocoder"
```

---

### Task 4: Wire orchestrator + geocoder into run.py and persist.py

**Files:**
- Modify: `what-the-fact/ingest/run.py`
- Modify: `what-the-fact/ingest/persist.py`

- [ ] **Step 1: Add geo save to `persist.py` — add after `upsert_article` inserts the article row.**

In `persist.py`, find the INSERT into `{S}.articles` and its RETURNING id. After getting `aid`, add:

```python
def save_geo(engine, article_id: int, schema: str, geo: dict) -> None:
    """Save geocoder result to wtf.articles geo columns."""
    if not geo or not article_id:
        return
    try:
        with engine.begin() as c:
            c.execute(text(f"""
                UPDATE {schema}.articles
                SET province_code = :pc, city = :city, lat = :lat, lng = :lng,
                    geo_scope = :scope
                WHERE id = :aid
            """), {
                "pc": geo.get("province_code"),
                "city": geo.get("city"),
                "lat": geo.get("lat"),
                "lng": geo.get("lng"),
                "scope": geo.get("geo_scope", "national"),
                "aid": article_id,
            })
    except Exception:
        pass  # geo failure is non-fatal


def mark_ai_analyzed(engine, article_id: int, schema: str) -> None:
    """Mark article as AI-analyzed."""
    try:
        with engine.begin() as c:
            c.execute(text(f"""
                UPDATE {schema}.articles
                SET ai_analyzed = TRUE, ai_analyzed_at = NOW()
                WHERE id = :aid
            """), {"aid": article_id})
    except Exception:
        pass
```

- [ ] **Step 2: Add geo call in `upsert_article` in `persist.py` — immediately after article insert.**

After the article is inserted and `aid` is obtained, add:
```python
    # Geo extraction for every article (L.O.C.A.L. via hub or heuristic fallback)
    from ingest.geocoder import extract_geo
    geo = extract_geo(aid, article.get("title", ""), article.get("body", ""))
    save_geo(engine, aid, S, geo)
```

- [ ] **Step 3: Wire orchestrator into `run.py` — add AI analysis loop after `run_once` completes.**

In `run.py`, add imports at top:
```python
from ingest.orchestrator import pick_priority_articles
from ingest.ai_dispatcher import analyze as ai_analyze
from ingest.persist import mark_ai_analyzed
```

After `totals = run_once(engine)`, add:

```python
    # F.A.C.T. orchestrator: AI deep-analysis for priority articles
    try:
        priority_ids = pick_priority_articles(engine, "wtf", totals.get("inserted_ids", []))
        for article_id in priority_ids:
            # Fetch title + body for dispatch
            with engine.connect() as c:
                row = c.execute(text(
                    "SELECT title, body, source_id FROM wtf.articles WHERE id = :id"
                ), {"id": article_id}).fetchone()
            if not row:
                continue
            # B.I.A.S.
            bias_result = ai_analyze("bias", article_id, row.title or "", row.body or "")
            if bias_result:
                with engine.begin() as c:
                    c.execute(text("""
                        UPDATE wtf.bias_scores SET
                            analyzed_by = 'BIAS_LLM',
                            trigger_phrases = :tp,
                            confidence = :conf
                        WHERE article_id = :aid
                    """), {
                        "tp": __import__("json").dumps(bias_result.get("trigger_phrases", [])),
                        "conf": bias_result.get("confidence"),
                        "aid": article_id,
                    })
            # V.E.R.I.F.Y.
            verify_result = ai_analyze("factcheck", article_id, row.title or "", row.body or "")
            if verify_result:
                with engine.begin() as c:
                    c.execute(text("""
                        UPDATE wtf.fact_checks SET
                            analyzed_by = 'VERIFY_LLM',
                            claims = :claims,
                            overall_verdict = :verdict
                        WHERE article_id = :aid
                    """), {
                        "claims": __import__("json").dumps(verify_result.get("claims", [])),
                        "verdict": verify_result.get("overall_verdict"),
                        "aid": article_id,
                    })
            mark_ai_analyzed(engine, article_id, "wtf")
        log.info("orchestrator: %d articles AI-analyzed this cycle", len(priority_ids))
    except Exception as exc:
        log.warning("orchestrator: failed: %s", exc)
```

**Note:** `totals` must return `inserted_ids` — add `"inserted_ids": inserted_ids` to the return dict in `run_once()` alongside the current stats.

- [ ] **Step 4: Add `inserted_ids` tracking to `run_once` in `run.py`.**

In `run_once`, find where `stats["inserted"] += 1` is incremented and also add:
```python
inserted_ids = []
# ... in the loop where articles are inserted:
if upsert_article(engine, source_id, article, bias, source_slug):
    stats["inserted"] += 1
    inserted_ids.append(last_inserted_id)  # persist.py must return article_id
```

Update `upsert_article` in `persist.py` to return the article_id (it currently returns bool). Change `return True` to `return aid` and `return False` to `return None`.

- [ ] **Step 5: Run ingest locally to test orchestrator.**

```bash
cd what-the-fact
WTF_DATABASE_URL="postgresql+psycopg2://wtfuser:f567e82fd6b38c6cc528b0721fac522a3d3bbc660120fbed@localhost:5433/wtf" \
WTF_HUB_URL="https://platform.kytranempowerment.com" \
WTF_HUB_TOKEN="your-token-here" \
WTF_POLL_SECS=0 \
python -c "
from sqlalchemy import create_engine
import os
from ingest.run import run_once
engine = create_engine(os.environ['WTF_DATABASE_URL'])
stats = run_once(engine)
print('Stats:', stats)
"
```

Expected: `Stats: {'inserted': N, 'skipped': M, 'failed': 0, 'inserted_ids': [...]}`

- [ ] **Step 6: Commit.**

```bash
git add what-the-fact/ingest/run.py what-the-fact/ingest/persist.py
git commit -m "feat(wtf-ingest): wire F.A.C.T. orchestrator + L.O.C.A.L. geocoder into ingest pipeline"
```

---

### Task 5: Weekly geo report APScheduler job

**Files:**
- Modify: `what-the-fact/ingest/run.py`

- [ ] **Step 1: Add weekly geo report function to `run.py`.**

```python
def run_geo_report(engine) -> None:
    """Weekly geo report: province coverage matrix + news deserts → wtf.geo_reports."""
    import json
    from datetime import date
    today = date.today()
    with engine.connect() as c:
        # Province × outlet coverage for last 7 days
        rows = c.execute(text("""
            SELECT a.province_code, s.slug AS outlet, COUNT(*) AS cnt
            FROM wtf.articles a
            JOIN wtf.sources s ON s.id = a.source_id
            WHERE a.published_at >= NOW() - INTERVAL '7 days'
              AND a.province_code IS NOT NULL
            GROUP BY a.province_code, s.slug
            ORDER BY a.province_code, cnt DESC
        """)).fetchall()

    matrix = {}
    for row in rows:
        pc = row.province_code
        if pc not in matrix:
            matrix[pc] = {}
        matrix[pc][row.outlet] = row.cnt

    # Province totals
    province_coverage = {pc: sum(outlets.values()) for pc, outlets in matrix.items()}

    # News deserts: provinces with < 5 articles in last 7 days
    all_provinces = ["AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"]
    news_deserts = [pc for pc in all_provinces if province_coverage.get(pc, 0) < 5]

    with engine.begin() as c:
        c.execute(text("""
            INSERT INTO wtf.geo_reports (report_date, province_coverage, outlet_province_matrix, news_deserts)
            VALUES (:d, :pc, :matrix, :nd)
            ON CONFLICT (report_date) DO UPDATE SET
                province_coverage = EXCLUDED.province_coverage,
                outlet_province_matrix = EXCLUDED.outlet_province_matrix,
                news_deserts = EXCLUDED.news_deserts
        """), {
            "d": today,
            "pc": json.dumps(province_coverage),
            "matrix": json.dumps(matrix),
            "nd": json.dumps(news_deserts),
        })
    log.info("geo_report: %d provinces covered, %d news deserts", len(province_coverage), len(news_deserts))
```

- [ ] **Step 2: Add weekly scheduler to `run.py` main loop.**

In the `if __name__ == "__main__"` section (or main loop), add weekly report trigger:

```python
import datetime

last_report_date = None
while True:
    today = datetime.date.today()
    if today.weekday() == 0 and last_report_date != today:  # Monday
        try:
            run_geo_report(engine)
            last_report_date = today
        except Exception as exc:
            log.warning("geo_report failed: %s", exc)

    stats = run_once(engine)
    log.info("run_once: %s", stats)
    time.sleep(POLL_SECS)
```

- [ ] **Step 3: Commit.**

```bash
git add what-the-fact/ingest/run.py
git commit -m "feat(wtf-ingest): weekly geo report job — province coverage + news deserts"
```

---

### Task 6: Env vars + VPS rebuild

**Files:**
- Modify: `/opt/archie-products/what-the-fact/.env` (VPS only)

- [ ] **Step 1: Add env vars to VPS .env.**

```bash
ssh -i ~/.ssh/repair_bay_deploy kytran@76.13.107.109 "
echo 'WTF_HUB_URL=https://platform.kytranempowerment.com' >> /opt/archie-products/what-the-fact/.env
echo 'WTF_HUB_TOKEN=<generate-shared-token>' >> /opt/archie-products/what-the-fact/.env
echo 'WTF_HUB_TIMEOUT=90' >> /opt/archie-products/what-the-fact/.env
"
```

Also add `WTF_HUB_TOKEN` to `/mnt/archie_brain/platform_v2/.env` on the hub.

- [ ] **Step 2: Rebuild and deploy wtf-ingest on VPS.**

```bash
# From hub, rsync updated ingest code to VPS
rsync -az -e "ssh -i ~/.ssh/repair_bay_deploy -o StrictHostKeyChecking=no" \
  --exclude=".git" --exclude="__pycache__" \
  /mnt/archie_brain/what-the-fact/ \
  kytran@76.13.107.109:/opt/archie-products/what-the-fact/

# On VPS: build new image and restart
ssh -i ~/.ssh/repair_bay_deploy kytran@76.13.107.109 "
cd /opt/archie-products/what-the-fact
docker build -f Dockerfile.ingest -t wtf-ingest:0.4.0 .
docker stop wtf_ingest && docker rm wtf_ingest
docker run -d --name wtf_ingest --network what-the-fact_default \
  --env-file .env \
  wtf-ingest:0.4.0
docker logs wtf_ingest --tail 20
"
```

Expected logs: `run_once: {'inserted': N, 'skipped': M, 'failed': 0}` + `orchestrator: N articles AI-analyzed this cycle`

---

## Success Criteria

- Migration 006 applied: `wtf.articles` has province_code, city, lat, lng, geo_scope, ai_analyzed
- L.O.C.A.L. agent in platform DB with llama3.2:3b
- Hub `/tools/wtf-hub/api/analyze` returns valid JSON for bias/factcheck/geo tasks
- wtf-ingest logs show "orchestrator: N articles AI-analyzed this cycle" on each poll
- At least 80% of articles have province_code populated after 24h
- Weekly geo report writes to `wtf.geo_reports` on Monday
