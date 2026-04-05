# Auto-Tag Bridge Dispatches with Project ID — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-detect which project a bridge dispatch belongs to via cached keyword matching, and pass explicit project_id from call sites that already have it.

**Architecture:** A cached `_detect_project_id(text)` function inside `bridge_dispatcher.py` infers project from prompt text. Injected in `request_work()` when `project_id` is None. Call sites with project context pass it explicitly. Explicit always wins over auto-detect.

**Tech Stack:** Python, PostgreSQL, psycopg2 (ai_bridge/db.py pattern).

**Spec:** `docs/superpowers/specs/2026-04-05-auto-tag-bridge-dispatches-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `ai_bridge/bridge_dispatcher.py` | Add `_detect_project_id()`, `_load_project_keywords()`, cache vars, inject in `request_work()` |
| Modify | `ai_bridge/orchestration_engine.py` | Accept `project_id` param, pass to `request_work()` |
| Modify | `platform_v2/api_gateway.py` | Extract optional `project_id` from request, pass to orchestrate |
| Modify | `platform_v2/tools/archie_chat/ha_bridge.py` | Extract `project_id` from `user_context`, pass to dispatch |
| Modify | `platform_v2/api_standalone.py` | Extract optional `project_id` from request, pass to dispatch |

---

### Task 1: Auto-Detect Function in Bridge Dispatcher

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py`

- [ ] **Step 1: Add cache variables and imports near the top of the file**

Find the imports section near the top of `bridge_dispatcher.py`. After the existing imports, add:

```python
import time as _time
```

Then find a suitable location after the imports (before the class definition) and add the cache variables:

```python
# --- Project auto-detect cache ---
_project_keyword_cache: Dict[str, int] = {}
_project_cache_time: float = 0
_PROJECT_CACHE_TTL = 300  # 5 minutes
```

Verify `time` isn't already imported. If it is, skip the import and use `time.time()` instead of `_time.time()` in the functions below.

- [ ] **Step 2: Add `_load_project_keywords()` function**

Add after the cache variables:

```python
def _load_project_keywords() -> Dict[str, int]:
    """Load project keywords from DB for auto-detection.

    Returns {keyword: project_id} dict. Keywords are slug words (4+ chars)
    and tags (4+ chars) from active/planning projects.
    """
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, slug, tags FROM unified_projects WHERE status IN ('active', 'planning')"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        keywords = {}
        for row in rows:
            pid, slug, tags = row[0], row[1], row[2]
            # Split slug on hyphens
            for word in (slug or "").split("-"):
                if len(word) >= 4:
                    keywords[word.lower()] = pid
            # Add tags
            if isinstance(tags, list):
                for tag in tags:
                    if len(tag) >= 4:
                        keywords[tag.lower()] = pid
        return keywords
    except Exception as e:
        logger.warning("[Dispatcher] Failed to load project keywords: %s", e)
        return {}
```

- [ ] **Step 3: Add `_detect_project_id()` function**

Add right after `_load_project_keywords()`:

```python
def _detect_project_id(text: str) -> Optional[int]:
    """Infer project_id from prompt/capability text via cached keyword matching.

    Returns project_id if 2+ keywords match, None otherwise.
    Cache refreshes every 5 minutes.
    """
    global _project_keyword_cache, _project_cache_time

    now = _time.time()
    if now - _project_cache_time > _PROJECT_CACHE_TTL or not _project_keyword_cache:
        _project_keyword_cache = _load_project_keywords()
        _project_cache_time = now

    if not _project_keyword_cache or not text:
        return None

    text_lower = text[:500].lower()
    scores: Dict[int, int] = {}
    for keyword, pid in _project_keyword_cache.items():
        if keyword in text_lower:
            scores[pid] = scores.get(pid, 0) + 1

    if not scores:
        return None

    best_score = max(scores.values())
    if best_score < 2:
        return None

    # Deterministic tie-breaking: lowest project_id among highest scorers
    best_pids = [pid for pid, score in scores.items() if score == best_score]
    return min(best_pids)
```

- [ ] **Step 4: Inject auto-detect in `request_work()`**

Find the bridge_jobs INSERT in `request_work()` (around line 5230). Right BEFORE the INSERT block, add:

```python
        # Auto-detect project if not explicitly provided
        if project_id is None:
            project_id = _detect_project_id(f"{capability} {prompt}")
```

Search for the line that starts the INSERT transaction to find the exact location. It should be just before:
```python
cur.execute(
    """
    INSERT INTO bridge_jobs (job_type, module_source, description,
```

- [ ] **Step 5: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/ai_bridge/bridge_dispatcher.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat: add project auto-detect to bridge dispatcher via cached keyword matching"
```

---

### Task 2: Orchestration Engine — Accept and Pass project_id

**Files:**
- Modify: `ai_bridge/orchestration_engine.py`

- [ ] **Step 1: Add `project_id` to `orchestrate()` signature**

Find `def orchestrate(` at line 200. The current signature is:

```python
def orchestrate(
    self,
    message: str,
    user_id: int,
    conversation_id: Optional[str] = None,
    voice_mode: bool = False,
    user_context: Optional[Dict] = None,
    agent_target: Optional[str] = None,
) -> OrchestrationResult:
```

Add `project_id` parameter:

```python
def orchestrate(
    self,
    message: str,
    user_id: int,
    conversation_id: Optional[str] = None,
    voice_mode: bool = False,
    user_context: Optional[Dict] = None,
    agent_target: Optional[str] = None,
    project_id: Optional[int] = None,
) -> OrchestrationResult:
```

- [ ] **Step 2: Pass `project_id` to `request_work()` call**

Find the `dispatcher.request_work()` call around line 1381. Currently:

```python
result = dispatcher.request_work(
    capability=capability,
    prompt=message,
    module_id="orchestration_engine",
    user_id=user_id,
    timeout=120,
)
```

Add `project_id`:

```python
result = dispatcher.request_work(
    capability=capability,
    prompt=message,
    module_id="orchestration_engine",
    user_id=user_id,
    timeout=120,
    project_id=project_id,
)
```

- [ ] **Step 3: Also check for project_id in user_context**

Right before the `request_work()` call, add a fallback to extract project_id from user_context if not explicitly provided:

```python
        # Extract project_id from user_context if not explicitly provided
        if project_id is None and user_context and isinstance(user_context, dict):
            project_id = user_context.get("project_id")
```

- [ ] **Step 4: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/ai_bridge/orchestration_engine.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat: pass project_id through orchestration engine to dispatcher"
```

---

### Task 3: API Gateway — Extract project_id from Request

**Files:**
- Modify: `platform_v2/api_gateway.py`

- [ ] **Step 1: Extract `project_id` from request JSON**

Find the chat route handler (around line 235). The request body is already parsed earlier in the function. Find where `message` and `agent_target` are extracted from the request JSON. Add `project_id` extraction nearby:

```python
project_id = data.get("project_id")
if project_id is not None:
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        project_id = None
```

If `data` is the request JSON dict, add this right after the existing field extractions.

- [ ] **Step 2: Pass `project_id` to `engine.orchestrate()`**

Find the `engine.orchestrate()` call at line 271. Currently:

```python
result = engine.orchestrate(
    message=contextual_message,
    user_id=gateway_user_id,
    conversation_id=str(conv["conversation_uuid"]),
    agent_target=agent_target,
    user_context={
        "username": "gateway",
        "conversation_history": conversation_history,
        "original_message": message,
```

Add `project_id` parameter:

```python
result = engine.orchestrate(
    message=contextual_message,
    user_id=gateway_user_id,
    conversation_id=str(conv["conversation_uuid"]),
    agent_target=agent_target,
    project_id=project_id,
    user_context={
        "username": "gateway",
        "conversation_history": conversation_history,
        "original_message": message,
```

- [ ] **Step 3: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/api_gateway.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/api_gateway.py
git commit -m "feat: extract and pass project_id from API gateway to orchestration"
```

---

### Task 4: Archie Chat — Extract project_id from user_context

**Files:**
- Modify: `platform_v2/tools/archie_chat/ha_bridge.py`

- [ ] **Step 1: Pass project_id from user_context to dispatch**

Find the `dispatcher.dispatch()` call around line 204. Currently:

```python
result = dispatcher.dispatch(
    prompt=query,
    user_id=KYTRAN_USER_ID,
    conversation_id=conversation_id,
    agent_target="ARCHIE",
    user_context=user_context,
)
```

Add `project_id` extraction from user_context:

```python
result = dispatcher.dispatch(
    prompt=query,
    user_id=KYTRAN_USER_ID,
    conversation_id=conversation_id,
    agent_target="ARCHIE",
    user_context=user_context,
    project_id=user_context.get("project_id") if isinstance(user_context, dict) else None,
)
```

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/tools/archie_chat/ha_bridge.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/archie_chat/ha_bridge.py
git commit -m "feat: pass project_id from user_context through Archie Chat dispatch"
```

---

### Task 5: API Standalone — Extract project_id from Request

**Files:**
- Modify: `platform_v2/api_standalone.py`

- [ ] **Step 1: Extract project_id and pass to dispatch**

Find the `dispatcher.dispatch()` call around line 139. Currently:

```python
result = dispatcher.dispatch(
    capability="compliance_analysis",
    prompt=prompt,
    module_id="security-network",
    system_prompt=system_prompt,
)
```

Read the surrounding code to find where the request JSON is parsed. Extract `project_id` from it, then add to dispatch:

```python
project_id = data.get("project_id") if isinstance(data, dict) else None

result = dispatcher.dispatch(
    capability="compliance_analysis",
    prompt=prompt,
    module_id="security-network",
    system_prompt=system_prompt,
    project_id=project_id,
)
```

If `data` isn't the variable name, find the actual request JSON variable by reading the route handler.

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/api_standalone.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/api_standalone.py
git commit -m "feat: pass project_id from standalone API to dispatch"
```

---

### Task 6: Deploy, Verify, Complete

**Files:** None (verification only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify auto-detect works**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
from bridge_dispatcher import _detect_project_id, _load_project_keywords

keywords = _load_project_keywords()
print(f'Keywords loaded: {len(keywords)}')
for kw, pid in sorted(keywords.items()):
    print(f'  {kw} -> project {pid}')

# Test detection
tests = [
    'Fix LCARS UI consolidation CSS compliance issue',
    'Update auth for KytranAuth standalone products',
    'Business billing launch readiness stripe',
    'Hello world test',
]
for t in tests:
    pid = _detect_project_id(t)
    print(f'  \"{t[:50]}\" -> project_id={pid}')
"
```

Expected: Keywords loaded, test prompts match relevant projects, "Hello world" returns None.

- [ ] **Step 3: Verify bridge_jobs get tagged**

Trigger a dispatch and check if project_id was set:

```bash
docker exec archie_database psql -U archie -d archie -t -c "
SELECT id, job_type, project_id, LEFT(description, 50)
FROM bridge_jobs
WHERE project_id IS NOT NULL
ORDER BY created_at DESC LIMIT 5
"
```

- [ ] **Step 4: Complete MCP task**

```
mcp complete_task 1634 "Auto-tag bridge dispatches: cached keyword auto-detect in request_work() + explicit project_id passthrough in orchestration engine, API gateway, Archie Chat, and standalone API."
```
