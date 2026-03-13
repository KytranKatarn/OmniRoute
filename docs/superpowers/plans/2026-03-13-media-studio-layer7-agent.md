# Media Studio Layer 7: Agent Integration & Automation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable ARCHIE agents to autonomously generate media via schedules, with private galleries, publish-to-shared, global daily cap, and orchestration routing.

**Architecture:** New `agent_media_service.py` wraps existing `submit_generation()` with agent-specific logic (config lookup, cap checks, visibility). Agent loop gets a 15-min scheduled job that checks cron configs. Orchestration engine gets a new `media_generate` intent type.

**Tech Stack:** Python/Flask, PostgreSQL, APScheduler, croniter

**Spec:** `docs/superpowers/specs/2026-03-13-media-studio-layer7-agent-design.md`

---

## Chunk 1: Backend — Database + Agent Media Service + Agent Loop + Orchestration

### Task 1: Database Migration 153

**Files:**
- Create: `database/migrations/153_media_agent_config.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 153: Agent media configuration + gallery visibility
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS media_agent_config (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL UNIQUE,
    enabled BOOLEAN DEFAULT FALSE,
    media_type VARCHAR(20) DEFAULT 'image',
    schedule_cron VARCHAR(50) DEFAULT '0 */4 * * *',
    default_prompt TEXT,
    default_negative TEXT DEFAULT '',
    default_params JSONB DEFAULT '{}',
    daily_cap INTEGER DEFAULT 10,
    last_generated_at TIMESTAMP,
    gallery_visibility VARCHAR(20) DEFAULT 'private',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE media_generations
ADD COLUMN IF NOT EXISTS gallery_visibility VARCHAR(20) DEFAULT 'shared';

CREATE INDEX IF NOT EXISTS idx_media_agent_config_enabled
ON media_agent_config(enabled) WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_media_generations_gallery_visibility
ON media_generations(gallery_visibility);

CREATE INDEX IF NOT EXISTS idx_media_generations_owner_type
ON media_generations(owner_type) WHERE owner_type = 'agent';
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor(commit=True) as (conn, cur):
    with open('/app/database/migrations/153_media_agent_config.sql') as f:
        cur.execute(f.read())
    print('Migration 153 applied')
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='media_agent_config' ORDER BY ordinal_position\")
    print('media_agent_config columns:', [r[0] for r in cur.fetchall()])
    cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='media_generations' AND column_name='gallery_visibility'\")
    print('gallery_visibility column exists:', cur.fetchone() is not None)
"
```

Expected: Migration applied, all columns present, gallery_visibility exists on media_generations.

- [ ] **Step 3: Commit**

```bash
git add database/migrations/153_media_agent_config.sql
git commit -m "feat(media-studio): add migration 153 — media_agent_config table + gallery_visibility"
```

---

### Task 2: Agent Media Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/agent_media_service.py`

**Context:** This is the core service file (~150 lines). It imports `submit_generation` from `generation_service.py` (line 77, signature: `submit_generation(user_id, media_type, prompt, negative_prompt="", params=None, owner_type="user", owner_id=None, batch_id=None)`). It uses `from database import get_db_cursor` with the `with get_db_cursor(commit=True) as (conn, cur):` pattern.

- [ ] **Step 1: Write the failing test**

Create `/tmp/test_agent_media_service.py`:

```python
import sys, os, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test 1: Import
try:
    from tools.media_studio.services.agent_media_service import (
        agent_generate, publish_generation, get_agent_gallery, orchestration_generate,
        GLOBAL_DAILY_CAP,
    )
    results.append(('Import agent_media_service', 'OK', True))
except Exception as e:
    results.append(('Import agent_media_service', str(e), False))

# Test 2: Verify GLOBAL_DAILY_CAP
results.append(('GLOBAL_DAILY_CAP is 100', GLOBAL_DAILY_CAP, GLOBAL_DAILY_CAP == 100))

# Test 3-6: Function signatures
import inspect
for fn_name, expected_params in [
    ('agent_generate', ['agent_name', 'media_type', 'prompt', 'params']),
    ('publish_generation', ['generation_id', 'agent_name']),
    ('get_agent_gallery', ['agent_name', 'include_private']),
    ('orchestration_generate', ['agent_name', 'intent_data']),
]:
    fn = locals().get(fn_name) or globals().get(fn_name)
    sig = inspect.signature(fn)
    has_all = all(p in sig.parameters for p in expected_params)
    results.append((f'{fn_name} params', list(sig.parameters.keys()), has_all))

from app import app
with app.app_context():
    # Test 7: agent_generate with no config returns error
    r = agent_generate('nonexistent_agent_xyz')
    results.append(('No config returns error', r.get('error', ''), 'not found' in r.get('error', '').lower() or 'not configured' in r.get('error', '').lower()))

    # Test 8: get_agent_gallery returns list structure
    gallery = get_agent_gallery('nonexistent_agent_xyz')
    results.append(('Empty gallery returns list', type(gallery).__name__, isinstance(gallery, list)))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python3 /tmp/test_agent_media_service.py
```

Expected: FAIL on import (module doesn't exist yet).

- [ ] **Step 3: Write the agent_media_service.py**

```python
"""Agent media generation service.

Wraps submit_generation() with agent-specific logic:
config lookup, daily cap checks, gallery visibility.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

GLOBAL_DAILY_CAP = 100


def _get_agent_config(agent_name: str) -> Optional[Dict]:
    """Load agent media config from DB."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM media_agent_config WHERE agent_name = %s",
            (agent_name,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _get_daily_count(owner_id: Optional[str] = None) -> int:
    """Count agent generations in the last 24 hours."""
    with get_db_cursor() as (conn, cur):
        if owner_id:
            cur.execute(
                """SELECT COUNT(*) FROM media_generations
                   WHERE owner_type = 'agent' AND owner_id = %s
                   AND created_at > NOW() - INTERVAL '1 day'""",
                (owner_id,),
            )
        else:
            cur.execute(
                """SELECT COUNT(*) FROM media_generations
                   WHERE owner_type = 'agent'
                   AND created_at > NOW() - INTERVAL '1 day'"""
            )
        return cur.fetchone()[0]


def agent_generate(
    agent_name: str,
    media_type: Optional[str] = None,
    prompt: Optional[str] = None,
    params: Optional[Dict] = None,
) -> Dict:
    """Generate media for an agent.

    Falls back to agent config defaults for unset parameters.
    Checks both global and per-agent daily caps.
    """
    config = _get_agent_config(agent_name)
    if not config:
        return {"error": f"Agent '{agent_name}' not configured for media generation"}

    if not config["enabled"]:
        return {"error": f"Agent '{agent_name}' media generation is disabled"}

    # Fall back to config defaults
    media_type = media_type or config["media_type"]
    prompt = prompt or config.get("default_prompt", "")
    neg = config.get("default_negative", "")
    gen_params = dict(config.get("default_params") or {})
    if params:
        gen_params.update(params)

    if not prompt:
        return {"error": "No prompt provided and no default_prompt configured"}

    # Check global daily cap
    global_count = _get_daily_count()
    if global_count >= GLOBAL_DAILY_CAP:
        return {"error": "Global agent daily cap reached"}

    # Check per-agent daily cap
    agent_count = _get_daily_count(agent_name)
    if agent_count >= config["daily_cap"]:
        return {"error": f"Agent '{agent_name}' daily cap ({config['daily_cap']}) reached"}

    # Import here to avoid circular imports
    from tools.media_studio.services.generation_service import submit_generation

    result = submit_generation(
        user_id=0,  # system-level generation
        media_type=media_type,
        prompt=prompt,
        negative_prompt=neg,
        params=gen_params,
        owner_type="agent",
        owner_id=agent_name,
    )

    # Update last_generated_at
    if "id" in result:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE media_agent_config
                   SET last_generated_at = NOW(), updated_at = NOW()
                   WHERE agent_name = %s""",
                (agent_name,),
            )
            # Set gallery visibility based on agent config
            cur.execute(
                """UPDATE media_generations
                   SET gallery_visibility = %s
                   WHERE id = %s""",
                (config["gallery_visibility"], result["id"]),
            )

    return result


def publish_generation(generation_id: int, agent_name: str) -> Dict:
    """Publish an agent's generation to the shared gallery."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE media_generations
               SET gallery_visibility = 'shared'
               WHERE id = %s AND owner_type = 'agent' AND owner_id = %s
               RETURNING id""",
            (generation_id, agent_name),
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Generation not found or not owned by this agent"}
        return {"success": True}


def get_agent_gallery(
    agent_name: str, include_private: bool = False
) -> List[Dict]:
    """Retrieve agent's media generations."""
    with get_db_cursor() as (conn, cur):
        if include_private:
            cur.execute(
                """SELECT id, media_type, prompt, status, file_path,
                          thumbnail_path, gallery_visibility, created_at
                   FROM media_generations
                   WHERE owner_type = 'agent' AND owner_id = %s
                   ORDER BY created_at DESC""",
                (agent_name,),
            )
        else:
            cur.execute(
                """SELECT id, media_type, prompt, status, file_path,
                          thumbnail_path, gallery_visibility, created_at
                   FROM media_generations
                   WHERE owner_type = 'agent' AND owner_id = %s
                   AND gallery_visibility = 'shared'
                   ORDER BY created_at DESC""",
                (agent_name,),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def orchestration_generate(agent_name: str, intent_data: Dict) -> Dict:
    """Entry point for orchestration engine media_generate intents."""
    return agent_generate(
        agent_name=agent_name,
        media_type=intent_data.get("media_type"),
        prompt=intent_data.get("prompt"),
        params=intent_data.get("params"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform python3 /tmp/test_agent_media_service.py
```

Expected: 8/8 passed.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/services/agent_media_service.py
git commit -m "feat(media-studio): add agent media service with generate, publish, gallery"
```

---

### Task 3: Agent Loop Integration

**Files:**
- Modify: `ai_bridge/agent_loop.py:397-406` (insert new job before `self._running = True`)
- Modify: `ai_bridge/agent_loop.py:430` (add job ID to stop list)

**Context:** The last `scheduler.add_job()` is at line 397 (`agent_performance_rankings`). `self._running = True` is at line 405. The `stop()` method has a list of job IDs at lines 410-430, last entry is `"agent_performance_rankings"`. All jobs use the pattern: `self.scheduler.add_job(with_app_context(self._method), trigger=IntervalTrigger(...), id="...", name="...", replace_existing=True)`.

- [ ] **Step 1: Write the failing test**

Create `/tmp/test_agent_loop_media.py`:

```python
import sys, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test 1: AgentLoop has _check_media_schedules method
from ai_bridge.agent_loop import AgentLoop
has_method = hasattr(AgentLoop, '_check_media_schedules')
results.append(('AgentLoop has _check_media_schedules', has_method, has_method))

# Test 2: Check stop() includes the new job ID
import inspect
stop_source = inspect.getsource(AgentLoop.stop)
has_job_id = 'agent_media_generation' in stop_source
results.append(('stop() has agent_media_generation', has_job_id, has_job_id))

# Test 3: Check start() registers the job
start_source = inspect.getsource(AgentLoop.start)
has_registration = 'agent_media_generation' in start_source
results.append(('start() registers media job', has_registration, has_registration))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python3 /tmp/test_agent_loop_media.py
```

Expected: FAIL — method doesn't exist yet.

- [ ] **Step 3: Add _check_media_schedules method to AgentLoop**

Add this method to the `AgentLoop` class (before the `stop()` method, around line 404):

```python
    def _check_media_schedules(self):
        """Check agent media generation schedules and trigger if due."""
        try:
            from croniter import croniter
            from database import get_db_cursor
            from tools.media_studio.services.agent_media_service import (
                agent_generate,
                GLOBAL_DAILY_CAP,
                _get_daily_count,
            )

            # Check global cap first
            if _get_daily_count() >= GLOBAL_DAILY_CAP:
                return

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT agent_name, schedule_cron, last_generated_at "
                    "FROM media_agent_config WHERE enabled = TRUE"
                )
                configs = cur.fetchall()

            now = datetime.now()
            for agent_name, cron_expr, last_gen in configs:
                try:
                    cron = croniter(cron_expr, now)
                    prev_fire = cron.get_prev(datetime)
                    if last_gen is None or prev_fire > last_gen:
                        result = agent_generate(agent_name)
                        if "error" in result:
                            logger.debug(
                                f"Agent media skip {agent_name}: {result['error']}"
                            )
                        else:
                            logger.info(
                                f"Agent media generated for {agent_name}: "
                                f"id={result.get('id')}"
                            )
                except Exception as e:
                    logger.error(
                        f"Agent media schedule error for {agent_name}: {e}"
                    )
        except ImportError:
            logger.warning("croniter not available — skipping media schedules")
        except Exception as e:
            logger.error(f"Agent media schedule check failed: {e}")
```

- [ ] **Step 4: Add scheduler.add_job call in start()**

Insert after line 403 (after the `agent_performance_rankings` job), before `self._running = True`:

```python
        self.scheduler.add_job(
            with_app_context(self._check_media_schedules),
            trigger=IntervalTrigger(minutes=15),
            id="agent_media_generation",
            name="Agent Loop: Media Generation Schedules",
            replace_existing=True,
        )
```

Update the logger line from "20 jobs" to "21 jobs".

- [ ] **Step 5: Add job ID to stop() list**

Add `"agent_media_generation"` after `"agent_performance_rankings"` in the stop() method's job ID list (line 430).

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker exec archie_platform python3 /tmp/test_agent_loop_media.py
```

Expected: 3/3 passed.

- [ ] **Step 7: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(media-studio): add media generation schedule job to agent loop"
```

---

### Task 4: Orchestration Engine Hook

**Files:**
- Modify: `ai_bridge/orchestration_engine.py:374-383` (add new elif branch)

**Context:** The intent dispatch is at lines 374-383. The pattern is:
```python
elif intent_type in ("team_management", "station_management", "status_query", "dev_hq_status"):
    response_text = self._execute_team_action(intent_type, message, user_id, intent, steps)
```
We add a new `elif` branch before this for `media_generate`.

- [ ] **Step 1: Write the failing test**

Create `/tmp/test_orchestration_media.py`:

```python
import sys, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

import inspect
from ai_bridge.orchestration_engine import OrchestrationEngine
source = inspect.getsource(OrchestrationEngine)

has_media_generate = 'media_generate' in source
results.append(('Orchestration has media_generate intent', has_media_generate, has_media_generate))

has_import = 'agent_media_service' in source
results.append(('Orchestration imports agent_media_service', has_import, has_import))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python3 /tmp/test_orchestration_media.py
```

Expected: FAIL.

- [ ] **Step 3: Add media_generate intent handler**

In `orchestration_engine.py`, insert a new `elif` branch at line 374, **before** the team management block:

```python
            elif intent_type == "media_generate":
                try:
                    from tools.media_studio.services.agent_media_service import (
                        orchestration_generate,
                    )

                    agent_name = intent.get("agent_name", "")
                    result = orchestration_generate(agent_name, intent)
                    if "error" in result:
                        response_text = f"Media generation failed: {result['error']}"
                    else:
                        response_text = (
                            f"Media generation queued for {agent_name} "
                            f"(ID: {result.get('id', 'unknown')})"
                        )
                    steps.append(
                        ThinkingStep(
                            step_type=StepType.EXECUTE.value,
                            label=f"Media Generate: {agent_name}",
                            data=result,
                            duration_ms=0,
                        )
                    )
                except Exception as e:
                    logger.error(f"Media generate intent failed: {e}")
                    response_text = f"Media generation error: {e}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec archie_platform python3 /tmp/test_orchestration_media.py
```

Expected: 2/2 passed.

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(media-studio): add media_generate intent to orchestration engine"
```

---

### Task 5: API Routes — Agent Config + Gallery Filter

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py` (append after line 1034)

**Context:** All routes use `@media_studio_bp.route()` + `@login_required`. The existing `/api/generations` endpoint handles gallery listing. We add 4 new endpoints at the end of the file + modify the existing generations endpoint to support `owner_type` filter.

- [ ] **Step 1: Write the failing test**

Create `/tmp/test_agent_routes.py`:

```python
import sys, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

from app import app

# Check route registration
rules = [r.rule for r in app.url_map.iter_rules() if 'media-studio' in r.rule and 'agent' in r.rule]
results.append(('Agent routes registered', len(rules), len(rules) >= 3))

# Check specific routes exist
all_rules = [r.rule for r in app.url_map.iter_rules()]
for route in [
    '/tools/media-studio/api/agent-config',
    '/tools/media-studio/api/agent-config/<agent_name>',
    '/tools/media-studio/api/agent-config/<agent_name>/trigger',
    '/tools/media-studio/api/agent-config/<agent_name>/publish/<int:generation_id>',
]:
    exists = route in all_rules
    results.append((f'Route {route}', exists, exists))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python3 /tmp/test_agent_routes.py
```

Expected: FAIL — routes don't exist yet.

- [ ] **Step 3: Add agent config routes to routes.py**

Append to end of `routes.py`. Use `import psycopg2.extras` at the top of the file or inline. Use safe parameter binding (never string-format SQL). All endpoints use `@login_required`.

Four endpoints:
1. `GET /api/agent-config` — list all configs, serialize datetimes with `.isoformat()`
2. `PUT /api/agent-config/<agent_name>` — update config fields (allowlist: enabled, media_type, schedule_cron, default_prompt, default_negative, default_params, daily_cap, gallery_visibility). Upsert pattern: UPDATE first, if no row affected then INSERT.
3. `POST /api/agent-config/<agent_name>/trigger` — call `agent_generate(agent_name)`, return result
4. `POST /api/agent-config/<agent_name>/publish/<int:generation_id>` — call `publish_generation(generation_id, agent_name)`, return result

- [ ] **Step 4: Add owner_type filter to existing generations endpoint**

Find the existing `api_get_generations` function in `routes.py`. Add `owner_type` query parameter handling to the SQL query. If `owner_type=agent` is passed, filter to `WHERE owner_type='agent' AND gallery_visibility='shared'`. If `agent_name` is also passed, add `AND owner_id = %s`. This requires reading the existing function first to find the exact insertion point.

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker exec archie_platform python3 /tmp/test_agent_routes.py
```

Expected: 5/5 passed.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add agent config routes + gallery owner_type filter"
```

---

## Chunk 2: Frontend — Gallery Filter + Admin Panel + CSS

### Task 6: Gallery Filter + Agent Config HTML/JS

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Context:** The gallery tab is at lines 349-524. The gallery search area is at line 351 (`ms-gallery-search`). The gallery sidebar filters are at line 435 (`msGallerySidebar`). JS is in an IIFE at the bottom of the file (ends at line 2488). Use `ms` prefix for all IDs. Follow existing patterns: `window.funcName`, `api()` helper, `_clearChildren()`.

- [ ] **Step 1: Add gallery filter buttons**

In the gallery tab area, add filter buttons near the gallery search/controls section (around line 351):

```html
<div class="ms-gallery-filter" id="msGalleryFilter">
  <button class="ms-btn-xs ms-gallery-filter-btn active" data-filter="mine" onclick="setGalleryFilter('mine')">Mine</button>
  <button class="ms-btn-xs ms-gallery-filter-btn" data-filter="agents" onclick="setGalleryFilter('agents')">Agent Art</button>
  <button class="ms-btn-xs ms-gallery-filter-btn" data-filter="all" onclick="setGalleryFilter('all')">All</button>
</div>
```

- [ ] **Step 2: Add agent config admin panel HTML**

Add a new collapsible admin config section near existing settings/controls. Use a button to toggle visibility:

```html
<div class="ms-agent-config" id="msAgentConfig" style="display:none;">
  <div class="ms-section-header">
    <span>Agent Media Config</span>
  </div>
  <div id="msAgentConfigBody"></div>
</div>
```

Add a toggle button somewhere near existing controls:
```html
<button class="ms-btn-xs" onclick="toggleAgentConfig()">
  <i data-lucide="bot"></i> Agent Config
</button>
```

- [ ] **Step 3: Add gallery filter + agent config JavaScript**

Add inside the existing IIFE. **Use safe DOM methods — no innerHTML with user data.** Use `textContent` for plain text, `document.createElement` for structure. The agent config table can use a builder pattern:

Key functions to implement:
- `window.setGalleryFilter(filter)` — toggles active class, calls `loadGallery()`
- `window.loadAgentGallery()` — fetches `/api/generations?owner_type=agent`, renders cards with `.ms-agent-badge` using `textContent`
- `window.toggleAgentConfig()` — shows/hides the config panel, loads data
- `window.loadAgentConfig()` — fetches `/api/agent-config`, builds table rows using `document.createElement` and `textContent` (never interpolating agent names into HTML)
- `window.updateAgentConfig(agentName, field, value)` — PUTs field update
- `window.triggerAgentGeneration(agentName)` — POSTs trigger, shows result

For the config table, build each row with DOM methods:
```javascript
const td = document.createElement('td');
td.textContent = config.agent_name;  // safe — no innerHTML
tr.appendChild(td);
```

For checkboxes and inputs, create elements and set properties directly:
```javascript
const checkbox = document.createElement('input');
checkbox.type = 'checkbox';
checkbox.checked = config.enabled;
checkbox.addEventListener('change', () => updateAgentConfig(config.agent_name, 'enabled', checkbox.checked));
```

- [ ] **Step 4: Integrate filter into existing loadGallery**

Modify the existing `loadGallery` (or equivalent gallery-loading function) to check `_galleryFilter`:
- If `'mine'`: existing behavior (user's own generations)
- If `'agents'`: call `loadAgentGallery()` instead
- If `'all'`: load user's + append agent shared generations

- [ ] **Step 5: Verify HTML elements exist**

```bash
docker exec archie_platform python3 -c "
with open('/app/tools/media_studio/templates/tools/media_studio/media_studio.html') as f:
    html = f.read()
checks = ['msGalleryFilter', 'msAgentConfig', 'setGalleryFilter', 'loadAgentConfig', 'toggleAgentConfig', 'triggerAgentGeneration', 'ms-agent-badge', 'updateAgentConfig']
for c in checks:
    print(f'[{\"PASS\" if c in html else \"FAIL\"}] {c}')
"
```

Expected: 8/8 PASS.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add agent gallery filter + admin config panel HTML/JS"
```

---

### Task 7: Agent CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css` (append after line 2152)

- [ ] **Step 1: Append agent CSS section**

```css
/* ── S21  Agent Gallery & Config ──────────────────────────────────────── */

.ms-gallery-filter {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}

.ms-gallery-filter-btn {
  padding: 4px 12px;
  border: 1px solid var(--ms-border, #334);
  border-radius: 4px;
  background: transparent;
  color: var(--ms-text, #aab);
  cursor: pointer;
  font-size: 0.75rem;
  transition: all 0.2s;
}

.ms-gallery-filter-btn:hover {
  border-color: var(--ms-accent, #f90);
}

.ms-gallery-filter-btn.active {
  background: var(--ms-accent, #f90);
  color: #000;
  border-color: var(--ms-accent, #f90);
}

.ms-agent-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  background: rgba(139, 92, 246, 0.2);
  color: #a78bfa;
  font-size: 0.7rem;
  font-family: 'IBM Plex Mono', monospace;
  margin-right: 6px;
}

.ms-agent-config {
  margin-top: 16px;
  padding: 12px;
  border: 1px solid var(--ms-border, #334);
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.2);
}

.ms-agent-config-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.ms-agent-config-table th {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--ms-border, #334);
  color: var(--ms-accent, #f90);
  font-family: 'Antonio', sans-serif;
  text-transform: uppercase;
  font-size: 0.7rem;
}

.ms-agent-config-table td {
  padding: 6px 8px;
  border-bottom: 1px solid rgba(51, 51, 68, 0.3);
}

.ms-agent-config-row:hover {
  background: rgba(255, 153, 0, 0.05);
}

.ms-input-xs {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--ms-border, #334);
  color: var(--ms-text, #aab);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.75rem;
  font-family: 'IBM Plex Mono', monospace;
}

.ms-input-xs:focus {
  border-color: var(--ms-accent, #f90);
  outline: none;
}

.ms-text-muted {
  color: rgba(170, 170, 187, 0.5);
  font-size: 0.8rem;
  font-style: italic;
}
```

- [ ] **Step 2: Verify CSS classes exist**

```bash
docker exec archie_platform python3 -c "
with open('/app/tools/media_studio/static/css/media-studio.css') as f:
    css = f.read()
checks = ['.ms-gallery-filter', '.ms-agent-badge', '.ms-agent-config', '.ms-agent-config-table', '.ms-input-xs', '.ms-text-muted']
for c in checks:
    print(f'[{\"PASS\" if c in css else \"FAIL\"}] {c}')
"
```

Expected: 6/6 PASS.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add agent gallery + config panel CSS"
```

---

## Chunk 3: Integration Test + Deploy + Dev HQ

### Task 8: Integration Test

**Files:**
- Create: `/tmp/test_layer7.py`

- [ ] **Step 1: Write comprehensive integration test**

Test all Layer 7 components:
- Import `agent_media_service` (all 4 functions + `GLOBAL_DAILY_CAP`)
- Verify `GLOBAL_DAILY_CAP == 100`
- Verify function signatures
- `agent_generate('nonexistent')` returns error
- `get_agent_gallery('nonexistent')` returns empty list
- `orchestration_generate('nonexistent', {...})` returns error
- `publish_generation(999999, 'nonexistent')` returns error
- DB: `media_agent_config` table exists
- DB: `gallery_visibility` column exists on `media_generations`
- `AgentLoop._check_media_schedules` method exists
- `OrchestrationEngine` source contains `media_generate`
- Agent routes registered (>= 3)
- HTML: `msGalleryFilter`, `msAgentConfig`, `setGalleryFilter`, `loadAgentConfig`, `triggerAgentGeneration`, `ms-agent-badge`
- CSS: `.ms-gallery-filter`, `.ms-agent-badge`, `.ms-agent-config`

- [ ] **Step 2: Run integration test**

```bash
docker exec archie_platform python3 /tmp/test_layer7.py
```

Expected: All tests pass.

- [ ] **Step 3: Fix any failures, re-run until green**

---

### Task 9: Deploy + Git Push + Dev HQ Update

- [ ] **Step 1: Restart platform to pick up changes**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify platform comes back healthy**

```bash
docker exec archie_platform python3 -c "
from app import app
with app.app_context():
    print('Platform healthy')
    from tools.media_studio.services.agent_media_service import GLOBAL_DAILY_CAP
    print(f'Agent media service loaded, cap={GLOBAL_DAILY_CAP}')
"
```

- [ ] **Step 3: Git push**

```bash
git push origin main
```

- [ ] **Step 4: Update Dev HQ**

Use MCP tools:
- `complete_task` for the Layer 7 implementation task with notes
- `update_project_understanding` for the Media Studio project
- `log_decision` for "Agent media generation architecture: agent_media_service wraps submit_generation, agent loop checks cron schedules every 15min, orchestration engine routes media_generate intents"
- `store_memory` (vault_note) for Layer 7 completion details

- [ ] **Step 5: Verify clean git status**
