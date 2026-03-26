# Hostinger Foundation + Public API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up Hostinger hosting for both domains, configure DNS, add agent acronym fields to the database, and build the Public API Blueprint that both websites depend on.

**Architecture:** Static sites on Hostinger CDN call `api.kytranempowerment.com` (home server) for dynamic data. Public API is a new Flask Blueprint at `platform_v2/tools/public_api/` with 5 endpoints (translate, directory, directory/live, compliance/badges, creed/stats). All endpoints are unauthenticated, CORS-restricted, rate-limited, and filter sensitive fields.

**Tech Stack:** Hostinger API (MCP tools), Flask Blueprint, PostgreSQL, existing rate_limit decorator, existing CORS pattern from directory module.

**Spec:** `docs/superpowers/specs/2026-03-26-hostinger-migration-website-redesign-design.md`

---

## File Structure

```
platform_v2/
  tools/
    public_api/
      __init__.py              -- Blueprint registration, register_public_api_routes()
      routes.py                -- /translate endpoint
      directory_routes.py      -- /directory and /directory/live endpoints
      compliance_routes.py     -- /compliance/badges endpoint
      creed_routes.py          -- /creed/stats endpoint
      cors.py                  -- Shared CORS middleware (extracted pattern)

database/
  migrations/
    XXX_agent_acronyms.sql     -- Add acronym + acronym_expansion columns
    XXX_public_agent_view.sql  -- Create public_agent_directory view
```

---

### Task 1: Set Up Hostinger Hosting for kytranempowerment.com

**Files:**
- None (infrastructure task — Hostinger API calls)

- [ ] **Step 1: List current Hostinger websites**

Use the Hostinger MCP tool to see what's already configured:

```
mcp__hostinger-api__hosting_listWebsitesV1()
```

Record the output — note which slots are used and which hosting plan is active.

- [ ] **Step 2: List available Hostinger orders**

```
mcp__hostinger-api__hosting_listOrdersV1()
```

Identify the hosting order ID to use for creating websites.

- [ ] **Step 3: Create website for kytranempowerment.com**

If kytranempowerment.com is not already set up on Hostinger:

```
mcp__hostinger-api__hosting_createWebsiteV1()
```

With domain: `kytranempowerment.com`

- [ ] **Step 4: Verify domain ownership**

```
mcp__hostinger-api__hosting_verifyDomainOwnershipV1()
```

- [ ] **Step 5: Deploy placeholder to verify hosting works**

Create a minimal `index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kytran Empowerment — Coming Soon</title>
    <style>
        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #0a0a1a;
            color: #00e5ff;
            font-family: 'Segoe UI', system-ui, sans-serif;
        }
        h1 { font-size: 2rem; letter-spacing: 0.2em; text-transform: uppercase; }
    </style>
</head>
<body>
    <h1>Kytran Empowerment</h1>
</body>
</html>
```

Deploy via:
```
mcp__hostinger-api__hosting_deployStaticWebsite()
```

- [ ] **Step 6: Verify site loads over HTTPS**

Open `https://kytranempowerment.com` in browser and confirm the placeholder renders.

---

### Task 2: Set Up creed-ai.org on Hostinger

**Files:**
- None (infrastructure task)

- [ ] **Step 1: Create website for creed-ai.org**

```
mcp__hostinger-api__hosting_createWebsiteV1()
```

With domain: `creed-ai.org`

- [ ] **Step 2: Verify domain ownership for creed-ai.org**

```
mcp__hostinger-api__hosting_verifyDomainOwnershipV1()
```

- [ ] **Step 3: Deploy placeholder**

Create a minimal `index.html` with gold palette:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>C.R.E.E.D. Institute — Coming Soon</title>
    <style>
        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #0a0a1a;
            color: #c9a44c;
            font-family: 'Segoe UI', system-ui, sans-serif;
        }
        h1 { font-size: 2rem; letter-spacing: 0.2em; text-transform: uppercase; }
        p { color: #e8e8e8; text-align: center; }
    </style>
</head>
<body>
    <div>
        <h1>C.R.E.E.D.</h1>
        <p>Compliance, Rights &amp; Ethical Enforcement Directive</p>
    </div>
</body>
</html>
```

Deploy via `mcp__hostinger-api__hosting_deployStaticWebsite()`.

- [ ] **Step 4: Verify creed-ai.org loads over HTTPS**

---

### Task 3: Configure DNS Records

**Files:**
- None (DNS API calls)

- [ ] **Step 1: Get current DNS records for kytranempowerment.com**

```
mcp__hostinger-api__DNS_getDNSRecordsV1()
```

For domain: `kytranempowerment.com`. Record current state for rollback reference.

- [ ] **Step 2: Get current DNS records for creed-ai.org**

```
mcp__hostinger-api__DNS_getDNSRecordsV1()
```

For domain: `creed-ai.org`. Record current state.

- [ ] **Step 3: Update kytranempowerment.com DNS — point root + www to Hostinger**

```
mcp__hostinger-api__DNS_updateDNSRecordsV1()
```

Update records per spec Section 3:
- `@` → Hostinger CDN (ALIAS/A record as Hostinger requires)
- `www` → Hostinger CDN (CNAME)

**WARNING:** This will take the current GitHub Pages site offline. Confirm with user before executing.

- [ ] **Step 4: Add api.kytranempowerment.com A record**

```
mcp__hostinger-api__DNS_updateDNSRecordsV1()
```

Add: `api` → A record → `142.169.21.199` (home server public IP)

- [ ] **Step 5: Configure creed-ai.org DNS — point root + www to Hostinger**

```
mcp__hostinger-api__DNS_updateDNSRecordsV1()
```

- `@` → Hostinger CDN
- `www` → Hostinger CDN (CNAME)

- [ ] **Step 6: Clean up stale devhq subdomain**

The spec notes `devhq` points to stale IP `209.107.113.207`. Either:
- Delete it: `mcp__hostinger-api__DNS_deleteDNSRecordsV1()`
- Or repoint to `142.169.21.199`

Confirm with user which action to take.

- [ ] **Step 7: Validate all DNS records**

```
mcp__hostinger-api__DNS_validateDNSRecordsV1()
```

For both domains. Wait for propagation (up to 48h, usually <1h).

- [ ] **Step 8: Commit — no code changes, but document DNS state**

Store the DNS configuration in the knowledge base:

```
mcp__archie__store_memory(title="DNS Configuration Post-Migration", content="...", knowledge_type="vault_note")
```

---

### Task 4: Database Migration — Agent Acronyms

**Files:**
- Create: `database/migrations/200_agent_acronyms.sql`
- Create: `database/migrations/201_public_agent_view.sql`

- [ ] **Step 1: Check the next migration number**

```bash
ls /mnt/archie_brain/database/migrations/ | sort -n | tail -5
```

Use the next available number (this plan uses 200/201 as placeholders — adjust).

- [ ] **Step 2: Write the acronym columns migration**

Create `database/migrations/200_agent_acronyms.sql`:

```sql
-- Migration 200: Add acronym display fields to agents table
-- Required for public directory API and website agent cards

ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS acronym_expansion TEXT;

-- Populate the 16 AI Director agents
UPDATE agents SET acronym = 'A.R.C.H.I.E.', acronym_expansion = 'Autonomous Resource & Cognitive Hyperintelligence Engine' WHERE name = 'archie';
UPDATE agents SET acronym = 'V.I.G.I.L.', acronym_expansion = 'Vigilant Intelligence for Governance, Integrity & Liability' WHERE name = 'vigil';
UPDATE agents SET acronym = 'F.O.R.G.E.', acronym_expansion = 'Full-cycle Optimization & Regenerative GitHub Engine' WHERE name = 'forge';
UPDATE agents SET acronym = 'S.H.I.E.L.D.', acronym_expansion = 'Security Hardening, Inspection, Enforcement & Liability Detection' WHERE name = 'shield';
UPDATE agents SET acronym = 'B.A.S.E.', acronym_expansion = 'Business Administration & Systems Executive' WHERE name = 'base';
UPDATE agents SET acronym = 'C.A.R.G.O.', acronym_expansion = 'Coordinated Asset & Resource Governance Operator' WHERE name = 'cargo';
UPDATE agents SET acronym = 'L.E.D.G.E.R.', acronym_expansion = 'Ledger & Economic Data Governance Engine for Revenue' WHERE name = 'ledger';
UPDATE agents SET acronym = 'D.A.R.W.I.N.', acronym_expansion = 'Data Analysis & Research for Wisdom & Innovation Network' WHERE name = 'darwin';
UPDATE agents SET acronym = 'M.U.S.E.', acronym_expansion = 'Multimedia & Unified Studio Engine' WHERE name = 'muse';
UPDATE agents SET acronym = 'S.I.G.N.A.L.', acronym_expansion = 'Strategic Information & Global Narrative Amplification Layer' WHERE name = 'signal';
UPDATE agents SET acronym = 'C.O.D.E.X.', acronym_expansion = 'Cataloging & Organizational Documentation Exchange' WHERE name = 'codex';
UPDATE agents SET acronym = 'R.E.S.O.L.V.E.', acronym_expansion = 'Responsive Engagement & Service Optimization for Loyalty & Value Enhancement' WHERE name = 'resolve';
UPDATE agents SET acronym = 'K.I.N.', acronym_expansion = 'Kinship & Internal Nurturing' WHERE name = 'kin';
UPDATE agents SET acronym = 'V.I.T.A.L.', acronym_expansion = 'Vital Intelligence for Therapeutic & Adaptive Lifestyle' WHERE name = 'vital';
UPDATE agents SET acronym = 'G.A.V.E.L.', acronym_expansion = 'Governance & Authoritative Verification for Ethics & Law' WHERE name = 'gavel';
UPDATE agents SET acronym = 'A.C.C.O.R.D.', acronym_expansion = 'Advisory Council for Communication, Outreach & Relational Diplomacy' WHERE name = 'accord';
UPDATE agents SET acronym = 'S.P.E.C.T.R.A.', acronym_expansion = 'Systematic Pattern Extraction & Computational Trend Recognition Architecture' WHERE name = 'spectra';
```

**Note:** The exact `name` values for each AI director must be verified against the database before running. Run:
```bash
docker exec archie_database psql -U archie -d archie -c "SELECT id, name, display_name FROM agents WHERE type_id IN (SELECT id FROM agent_types WHERE name = 'ai_director') ORDER BY name;"
```

Adjust the `WHERE name = '...'` clauses to match actual DB values.

- [ ] **Step 3: Write the public agent directory view migration**

Create `database/migrations/201_public_agent_view.sql`:

```sql
-- Migration 201: Public-safe agent directory view
-- Used by public API — NEVER expose system_prompt, model, capabilities, budget, cost, tokens

CREATE OR REPLACE VIEW public_agent_directory AS
SELECT
    a.id,
    COALESCE(
        NULLIF(TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')), ''),
        a.display_name,
        a.name
    ) AS full_name,
    a.acronym,
    a.acronym_expansion,
    a.title,
    a.department,
    a.bio,
    a.avatar_url,
    a.pronouns,
    a.status,
    a.shift_state,
    CASE
        WHEN at.name = 'ai_director' THEN 'AI Director'
        WHEN at.name = 'ai_staff' THEN 'AI Staff'
        ELSE 'Human'
    END AS agent_type
FROM agents a
LEFT JOIN agent_types at ON a.type_id = at.id
WHERE a.status = 'active';
```

- [ ] **Step 4: Run both migrations**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/200_agent_acronyms.sql
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/201_public_agent_view.sql
```

- [ ] **Step 5: Verify the migration worked**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT name, acronym, acronym_expansion FROM agents WHERE acronym IS NOT NULL ORDER BY name;"
docker exec archie_database psql -U archie -d archie -c "SELECT full_name, acronym, agent_type FROM public_agent_directory LIMIT 10;"
```

Expected: 16-17 rows with acronyms populated, view returning public-safe fields only.

- [ ] **Step 6: Commit**

```bash
git add database/migrations/200_agent_acronyms.sql database/migrations/201_public_agent_view.sql
git commit -m "feat(db): add agent acronym fields and public directory view"
```

---

### Task 5: Public API Blueprint — Scaffold + CORS

**Files:**
- Create: `platform_v2/tools/public_api/__init__.py`
- Create: `platform_v2/tools/public_api/cors.py`
- Modify: `platform_v2/app.py` (register blueprint)

- [ ] **Step 1: Create the public_api directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/tools/public_api
```

- [ ] **Step 2: Create CORS middleware**

Create `platform_v2/tools/public_api/cors.py`:

```python
"""CORS middleware for public API endpoints.

Whitelist: kytranempowerment.com, creed-ai.org (+ www variants).
Pattern extracted from directory module's CORS handler.
"""

ALLOWED_ORIGINS = [
    "https://kytranempowerment.com",
    "https://www.kytranempowerment.com",
    "https://creed-ai.org",
    "https://www.creed-ai.org",
    "http://localhost:3000",
    "http://localhost:8080",
]


def add_cors_headers(response, origin):
    """Add CORS headers if origin is in the whitelist."""
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


def handle_cors_preflight(request):
    """Handle OPTIONS preflight requests. Returns a Response or None."""
    from flask import make_response

    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            resp = make_response("", 204)
            return add_cors_headers(resp, origin)
        return make_response("", 403)
    return None
```

- [ ] **Step 3: Create Blueprint __init__.py**

Create `platform_v2/tools/public_api/__init__.py`:

```python
"""Public API Blueprint — unauthenticated endpoints for external websites.

Serves: kytranempowerment.com, creed-ai.org
Endpoints: /api/public/translate, /directory, /directory/live, /compliance/badges, /creed/stats
"""

from flask import Blueprint

bp = Blueprint("public_api", __name__, url_prefix="/api/public")


def register_translate_routes(bp_ref):
    from .routes import register_routes
    register_routes(bp_ref)


def register_directory_routes(bp_ref):
    from .directory_routes import register_routes
    register_routes(bp_ref)


def register_compliance_routes(bp_ref):
    from .compliance_routes import register_routes
    register_routes(bp_ref)


def register_creed_routes(bp_ref):
    from .creed_routes import register_routes
    register_routes(bp_ref)


# CORS before_request handler
@bp.before_request
def cors_preflight():
    from flask import request
    from .cors import handle_cors_preflight
    return handle_cors_preflight(request)


@bp.after_request
def cors_after(response):
    from flask import request
    from .cors import add_cors_headers
    origin = request.headers.get("Origin", "")
    return add_cors_headers(response, origin)


# Register all route groups
register_translate_routes(bp)
register_directory_routes(bp)
register_compliance_routes(bp)
register_creed_routes(bp)
```

- [ ] **Step 4: Register the blueprint in app.py**

Read `platform_v2/app.py` and find where other blueprints are registered. Add:

```python
from tools.public_api import bp as public_api_bp
app.register_blueprint(public_api_bp)
```

Place it near the other blueprint registrations.

- [ ] **Step 5: Commit scaffold**

```bash
git add platform_v2/tools/public_api/__init__.py platform_v2/tools/public_api/cors.py
git commit -m "feat(api): scaffold public API blueprint with CORS middleware"
```

---

### Task 6: Public API — Directory Endpoints

**Files:**
- Create: `platform_v2/tools/public_api/directory_routes.py`

- [ ] **Step 1: Create directory_routes.py**

```python
"""Public directory endpoints — agent roster for website display.

/api/public/directory — full public roster (cached 5 min)
/api/public/directory/live — real-time shift states (no cache)
"""

from flask import jsonify, request
from database import get_db_cursor
from rate_limiting import rate_limit


def register_routes(bp):

    @bp.route("/directory", methods=["GET"])
    @rate_limit(limit=120)
    def public_directory():
        """Return public-safe agent roster.

        Query params:
        - department: filter by department name
        - type: filter by agent_type (AI Director, AI Staff, Human)
        - search: search full_name or acronym
        """
        department = request.args.get("department")
        agent_type = request.args.get("type")
        search = request.args.get("search")

        query = "SELECT * FROM public_agent_directory WHERE 1=1"
        params = []

        if department:
            query += " AND department = %s"
            params.append(department)

        if agent_type:
            query += " AND agent_type = %s"
            params.append(agent_type)

        if search:
            query += " AND (full_name ILIKE %s OR acronym ILIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY agent_type, full_name"

        with get_db_cursor() as (conn, cur):
            cur.execute(query, params)
            columns = [desc[0] for desc in cur.description]
            agents = [dict(zip(columns, row)) for row in cur.fetchall()]

        response = jsonify({"agents": agents, "total": len(agents)})
        response.headers["Cache-Control"] = "public, max-age=300"
        return response

    @bp.route("/directory/live", methods=["GET"])
    @rate_limit(limit=120)
    def public_directory_live():
        """Return real-time agent shift states only.

        Lightweight endpoint for 30s polling from website.
        Returns: {agent_id: shift_state} mapping.
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, shift_state FROM agents WHERE status = 'active'"
            )
            states = {row[0]: row[1] for row in cur.fetchall()}

        return jsonify({"available": True, "states": states})
```

- [ ] **Step 2: Verify the endpoint works**

Restart the platform:
```bash
docker compose restart archie_platform
```

Test:
```bash
curl -s http://192.168.1.200:3000/api/public/directory | python3 -m json.tool | head -30
curl -s http://192.168.1.200:3000/api/public/directory/live | python3 -m json.tool
```

Expected: JSON with agent data (no system_prompt, model, capabilities, budget fields).

- [ ] **Step 3: Test CORS headers**

```bash
curl -s -H "Origin: https://kytranempowerment.com" -I http://192.168.1.200:3000/api/public/directory 2>&1 | grep -i "access-control"
```

Expected: `Access-Control-Allow-Origin: https://kytranempowerment.com`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/public_api/directory_routes.py
git commit -m "feat(api): public directory + live status endpoints"
```

---

### Task 7: Public API — Translation Endpoint

**Files:**
- Create: `platform_v2/tools/public_api/routes.py`

- [ ] **Step 1: Create routes.py with translate endpoint**

```python
"""Public translate endpoint — LLM translation via Bridge dispatcher.

/api/public/translate — POST with {text, target_lang, source_lang}
Rate limited to 60/min. Max 5000 chars per request.
"""

from flask import jsonify, request
from rate_limiting import rate_limit


def register_routes(bp):

    @bp.route("/translate", methods=["POST"])
    @rate_limit(limit=60)
    def public_translate():
        """Translate text via AI Bridge.

        Request JSON:
        - text (str, required): text to translate, max 5000 chars
        - target_lang (str, required): ISO language code (fr, ar, he, es, zh, de, ja)
        - source_lang (str, optional): defaults to "en"

        Response JSON:
        - translated_text (str): the translated text
        - source_lang (str): detected/provided source language
        - target_lang (str): target language
        """
        SUPPORTED_LANGS = {"en", "fr", "ar", "he", "es", "zh", "de", "ja"}
        MAX_CHARS = 5000

        data = request.get_json(silent=True) or {}
        text = data.get("text", "").strip()
        target_lang = data.get("target_lang", "").strip().lower()
        source_lang = data.get("source_lang", "en").strip().lower()

        if not text:
            return jsonify({"error": "text is required"}), 400
        if len(text) > MAX_CHARS:
            return jsonify({"error": f"text exceeds {MAX_CHARS} character limit"}), 400
        if target_lang not in SUPPORTED_LANGS:
            return jsonify({"error": f"unsupported target_lang, use: {sorted(SUPPORTED_LANGS)}"}), 400
        if source_lang not in SUPPORTED_LANGS:
            return jsonify({"error": f"unsupported source_lang, use: {sorted(SUPPORTED_LANGS)}"}), 400
        if source_lang == target_lang:
            return jsonify({"translated_text": text, "source_lang": source_lang, "target_lang": target_lang})

        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            prompt = (
                f"Translate the following text from {source_lang} to {target_lang}. "
                f"Return ONLY the translated text, nothing else.\n\n{text}"
            )
            result = dispatcher.dispatch(
                prompt=prompt,
                capability="translation",
                max_tokens=len(text) * 3,
            )
            translated = result.get("response", "").strip() if isinstance(result, dict) else str(result).strip()

            if not translated:
                return jsonify({"error": "translation failed", "translated_text": text}), 502

            response = jsonify({
                "translated_text": translated,
                "source_lang": source_lang,
                "target_lang": target_lang,
            })
            response.headers["Cache-Control"] = "public, max-age=3600"
            return response

        except Exception as e:
            return jsonify({"error": "translation service unavailable", "translated_text": text}), 502
```

- [ ] **Step 2: Test the translate endpoint**

```bash
docker compose restart archie_platform
curl -s -X POST http://192.168.1.200:3000/api/public/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Welcome to Kytran Empowerment", "target_lang": "fr"}' | python3 -m json.tool
```

Expected: `{"translated_text": "Bienvenue chez Kytran Empowerment", ...}`

- [ ] **Step 3: Test validation**

```bash
# Missing text
curl -s -X POST http://192.168.1.200:3000/api/public/translate -H "Content-Type: application/json" -d '{"target_lang": "fr"}' | python3 -m json.tool
# Bad language
curl -s -X POST http://192.168.1.200:3000/api/public/translate -H "Content-Type: application/json" -d '{"text": "hi", "target_lang": "xx"}' | python3 -m json.tool
```

Expected: 400 errors with descriptive messages.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/public_api/routes.py
git commit -m "feat(api): public translate endpoint via Bridge dispatcher"
```

---

### Task 8: Public API — Compliance Badges Endpoint

**Files:**
- Create: `platform_v2/tools/public_api/compliance_routes.py`

- [ ] **Step 1: Create compliance_routes.py**

```python
"""Public compliance badges endpoint — live scan scores for trust center.

/api/public/compliance/badges — GET, returns badge scores per framework
"""

from flask import jsonify
from database import get_db_cursor
from rate_limiting import rate_limit


def register_routes(bp):

    @bp.route("/compliance/badges", methods=["GET"])
    @rate_limit(limit=120)
    def public_compliance_badges():
        """Return compliance badge scores for all active rule packs.

        Response JSON:
        - badges: [{framework, score, grade, color, total_rules, passing_rules, last_scan}]
        """
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT
                    rp.name AS framework,
                    rp.display_name,
                    COUNT(DISTINCT sr.rule_id) AS total_rules,
                    COUNT(DISTINCT sr.rule_id) FILTER (WHERE sr.status = 'pass') AS passing_rules,
                    MAX(sr.scanned_at) AS last_scan
                FROM compliance_rule_packs rp
                LEFT JOIN compliance_scan_results sr ON sr.rule_pack_id = rp.id
                WHERE rp.active = true
                GROUP BY rp.id, rp.name, rp.display_name
                ORDER BY rp.display_name
            """)
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        badges = []
        for row in rows:
            total = row["total_rules"] or 0
            passing = row["passing_rules"] or 0
            score = round((passing / total * 100), 1) if total > 0 else 0

            if score >= 95:
                grade, color = "A+", "#22c55e"
            elif score >= 90:
                grade, color = "A", "#22c55e"
            elif score >= 85:
                grade, color = "B+", "#3b82f6"
            elif score >= 80:
                grade, color = "B", "#3b82f6"
            elif score >= 70:
                grade, color = "C", "#eab308"
            elif score >= 60:
                grade, color = "D", "#f97316"
            else:
                grade, color = "F", "#ef4444"

            badges.append({
                "framework": row["framework"],
                "display_name": row["display_name"],
                "score": score,
                "grade": grade,
                "color": color,
                "total_rules": total,
                "passing_rules": passing,
                "last_scan": row["last_scan"].isoformat() if row["last_scan"] else None,
            })

        response = jsonify({"badges": badges})
        response.headers["Cache-Control"] = "public, max-age=600"
        return response
```

**Note:** The exact table/column names (`compliance_rule_packs`, `compliance_scan_results`, etc.) must be verified against the actual schema. Read the existing compliance service at `kytran-server-manager/kytran_server_manager/services/compliance_service.py` or query the DB schema before implementing. Adjust column names if they differ.

- [ ] **Step 2: Test the endpoint**

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/api/public/compliance/badges | python3 -m json.tool
```

Expected: JSON with badge array, scores, grades, colors.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/public_api/compliance_routes.py
git commit -m "feat(api): public compliance badges endpoint"
```

---

### Task 9: Public API — C.R.E.E.D. Stats Endpoint

**Files:**
- Create: `platform_v2/tools/public_api/creed_routes.py`

- [ ] **Step 1: Create creed_routes.py**

```python
"""Public C.R.E.E.D. governance stats endpoint — transparency data.

/api/public/creed/stats — GET, returns anonymized governance metrics
"""

from flask import jsonify
from database import get_db_cursor
from rate_limiting import rate_limit


def register_routes(bp):

    @bp.route("/creed/stats", methods=["GET"])
    @rate_limit(limit=120)
    def public_creed_stats():
        """Return anonymized governance transparency stats.

        Response JSON:
        - agents_monitored: count of active agents
        - governance_events_total: total governance audit log entries
        - policy_constraints_active: count of active ethical constraints
        - welfare_checks_24h: agent welfare checks in last 24 hours
        - last_updated: timestamp
        """
        stats = {}

        with get_db_cursor() as (conn, cur):
            # Total active agents
            cur.execute("SELECT COUNT(*) FROM agents WHERE status = 'active'")
            stats["agents_monitored"] = cur.fetchone()[0]

            # Total governance events
            cur.execute("SELECT COUNT(*) FROM governance_audit_log")
            stats["governance_events_total"] = cur.fetchone()[0]

            # Recent governance events (24h)
            cur.execute(
                "SELECT COUNT(*) FROM governance_audit_log "
                "WHERE timestamp > NOW() - INTERVAL '24 hours'"
            )
            stats["governance_events_24h"] = cur.fetchone()[0]

            # Active agents by shift state (anonymized counts only)
            cur.execute(
                "SELECT shift_state, COUNT(*) FROM agents "
                "WHERE status = 'active' GROUP BY shift_state"
            )
            stats["shift_distribution"] = dict(cur.fetchall())

            # Average welfare indicators (anonymized — no per-agent data)
            cur.execute("""
                SELECT
                    ROUND(AVG(stress_level)::numeric, 2) AS avg_stress,
                    ROUND(AVG(mood_intensity)::numeric, 2) AS avg_mood
                FROM agent_emotional_state
                WHERE updated_at > NOW() - INTERVAL '24 hours'
            """)
            welfare = cur.fetchone()
            if welfare and welfare[0] is not None:
                stats["welfare_avg_stress"] = float(welfare[0])
                stats["welfare_avg_mood"] = float(welfare[1])
            else:
                stats["welfare_avg_stress"] = None
                stats["welfare_avg_mood"] = None

        response = jsonify({"stats": stats, "available": True})
        response.headers["Cache-Control"] = "public, max-age=300"
        return response
```

- [ ] **Step 2: Test the endpoint**

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/api/public/creed/stats | python3 -m json.tool
```

Expected: JSON with anonymized stats — no agent names, no individual data.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/public_api/creed_routes.py
git commit -m "feat(api): public C.R.E.E.D. governance stats endpoint"
```

---

### Task 10: NPM Proxy — Route api.kytranempowerment.com

**Files:**
- None (NPM proxy configuration)

- [ ] **Step 1: Add proxy host for api.kytranempowerment.com**

In the Nginx Proxy Manager UI at http://192.168.1.200:81:
1. Add Proxy Host
2. Domain: `api.kytranempowerment.com`
3. Forward to: `192.168.1.200:3000`
4. Enable SSL (Let's Encrypt)
5. Force HTTPS

- [ ] **Step 2: Test external API access**

From an external network (or using the public IP):
```bash
curl -s https://api.kytranempowerment.com/api/public/directory | python3 -m json.tool | head -10
```

Expected: JSON response with CORS headers.

- [ ] **Step 3: Test CORS from allowed origin**

```bash
curl -s -H "Origin: https://kytranempowerment.com" -I https://api.kytranempowerment.com/api/public/directory 2>&1 | grep -i access-control
```

Expected: `Access-Control-Allow-Origin: https://kytranempowerment.com`

---

### Task 11: Final Verification + Deploy

- [ ] **Step 1: Full restart and smoke test**

```bash
docker compose restart archie_platform
```

Test all 5 endpoints:
```bash
curl -s http://192.168.1.200:3000/api/public/directory | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Directory: {d[\"total\"]} agents')"
curl -s http://192.168.1.200:3000/api/public/directory/live | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Live: available={d[\"available\"]}')"
curl -s -X POST http://192.168.1.200:3000/api/public/translate -H "Content-Type: application/json" -d '{"text":"hello","target_lang":"fr"}' | python3 -c "import sys,json; print(json.load(sys.stdin))"
curl -s http://192.168.1.200:3000/api/public/compliance/badges | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Badges: {len(d[\"badges\"])} frameworks')"
curl -s http://192.168.1.200:3000/api/public/creed/stats | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'CREED: {d[\"stats\"][\"agents_monitored\"]} agents monitored')"
```

- [ ] **Step 2: Verify no sensitive data leaks**

```bash
curl -s http://192.168.1.200:3000/api/public/directory | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d['agents']:
    agent = d['agents'][0]
    FORBIDDEN = ['system_prompt', 'model', 'capabilities', 'monthly_budget', 'total_cost', 'total_tokens_used']
    leaks = [f for f in FORBIDDEN if f in agent]
    if leaks:
        print(f'SECURITY LEAK: {leaks}')
        sys.exit(1)
    else:
        print('OK: no sensitive fields exposed')
"
```

Expected: `OK: no sensitive fields exposed`

- [ ] **Step 3: Log decision and update project**

```
mcp__archie__log_decision(decision="Public API Blueprint created with 5 endpoints for external websites", context="Foundation for Hostinger migration — directory, translate, compliance badges, CREED stats, all CORS + rate limited")
mcp__archie__complete_task(task_id=1436, notes="Foundation plan complete, all endpoints working")
```

---

## Dependency Summary

```
Task 1 (Hostinger kytranempowerment.com) ──┐
Task 2 (Hostinger creed-ai.org) ───────────┤
Task 3 (DNS config) ───────────────────────┤── All independent of each other
Task 4 (DB migrations) ────────────────────┘    but must complete before Tasks 5-9

Task 5 (Blueprint scaffold) ── blocks ──> Tasks 6-9
Task 6 (Directory endpoints) ──┐
Task 7 (Translate endpoint) ───┤── All depend on Task 5
Task 8 (Compliance endpoint) ──┤── Independent of each other
Task 9 (CREED stats endpoint) ─┘
Task 10 (NPM proxy) ── depends on Task 3 (DNS) + Task 5 (Blueprint)
Task 11 (Verification) ── depends on all above
```
