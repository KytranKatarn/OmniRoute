# Media Studio Layer 9: Workflow Templates & Pipeline Execution — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable pipeline templates (generate + edit + batch) with versioning, collections, one-click execution, and a pipeline builder UI.

**Architecture:** `template_service.py` handles template CRUD with versioning. `pipeline_executor.py` runs step sequences in a background thread with Flask app_context. Templates stored in `media_templates` + `media_template_steps`. Pipeline execution tracked in `media_pipeline_executions`. Frontend adds a Templates view with library cards, pipeline builder modal, and execution progress bar.

**Tech Stack:** Flask, PostgreSQL, Background threads (threading.Thread), HTML5, JavaScript

**Key patterns from existing code:**
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`, `psycopg2.extras.Json()` for JSONB
- Routes: `@media_studio_bp.route()` + `@login_required`, local imports, `jsonify()`, section comment `# ── S23 ... ──`
- JS: IIFE nested in outer IIFE, `window.funcName`, `api(method, path, body)`, `_clearChildren()`, `document.createElement`
- CSS: `ms-` prefix, `var(--ms-border, #334)`, `var(--ms-accent, #f90)`, `var(--ms-text, #aab)`
- Collections: `media_collections` + `media_collection_items` — junction table with `collection_id`/`media_id`, no `item_type` column
- No existing background thread pattern in Media Studio — pipeline executor will use `threading.Thread` + `with app.app_context():` (pattern from agent_loop.py batch jobs)
- `submit_generation()` and `submit_edit()` are fire-and-forget — client polls status. Pipeline executor must implement its own polling loop.
- `create_batch()` signature: `(name, owner_type, owner_id, media_type, prompts, base_params, sweep_param=None, sweep_values=None)`

---

## Task 1: Database Migration 155

**Files:**
- Create: `database/migrations/155_media_templates.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 155: Workflow templates + pipeline execution tracking
-- Idempotent: safe to run multiple times

-- Template definitions
CREATE TABLE IF NOT EXISTS media_templates (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL,
    visibility VARCHAR(20) DEFAULT 'private',
    version INTEGER DEFAULT 1,
    parent_id INTEGER REFERENCES media_templates(id),
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Template steps (ordered pipeline)
CREATE TABLE IF NOT EXISTS media_template_steps (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES media_templates(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_type VARCHAR(30) NOT NULL,
    step_name VARCHAR(100) DEFAULT '',
    params JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Pipeline execution tracking
CREATE TABLE IF NOT EXISTS media_pipeline_executions (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES media_templates(id),
    owner_type VARCHAR(20) DEFAULT 'user',
    owner_id INTEGER NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER NOT NULL,
    result_ids JSONB DEFAULT '[]',
    error_message TEXT,
    failed_at_step INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Template collection support: add template_id to collection_items
-- Since media_collection_items only has media_id (FK to media_library),
-- we need a separate junction table for template collections
CREATE TABLE IF NOT EXISTS media_template_collection_items (
    id SERIAL PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES media_collections(id) ON DELETE CASCADE,
    template_id INTEGER NOT NULL REFERENCES media_templates(id) ON DELETE CASCADE,
    sort_order INTEGER DEFAULT 0,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(collection_id, template_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_media_templates_owner ON media_templates(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_templates_visibility ON media_templates(visibility);
CREATE INDEX IF NOT EXISTS idx_media_templates_parent ON media_templates(parent_id);
CREATE INDEX IF NOT EXISTS idx_media_template_steps_template ON media_template_steps(template_id, step_order);
CREATE INDEX IF NOT EXISTS idx_media_pipeline_exec_owner ON media_pipeline_executions(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_pipeline_exec_status ON media_pipeline_executions(status);
CREATE INDEX IF NOT EXISTS idx_media_tpl_coll_items_coll ON media_template_collection_items(collection_id);
```

Note: Since `media_collection_items` has a FK to `media_library`, we can't reuse it for templates. Instead, we create a parallel `media_template_collection_items` table that links collections to templates.

- [ ] **Step 2: Run migration in Docker**

```bash
docker cp database/migrations/155_media_templates.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/155_media_templates.sql
```

Expected: `CREATE TABLE` x4, `CREATE INDEX` x7 (or notices if already exist).

- [ ] **Step 3: Verify schema**

```bash
docker exec archie_database psql -U archie -d archie -c "\d media_templates"
docker exec archie_database psql -U archie -d archie -c "\d media_template_steps"
docker exec archie_database psql -U archie -d archie -c "\d media_pipeline_executions"
docker exec archie_database psql -U archie -d archie -c "\d media_template_collection_items"
```

Expected: All 4 tables with correct columns.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/155_media_templates.sql
git commit -m "feat(media-studio): add migration 155 — templates + pipeline execution tables"
```

---

## Task 2: Template Service

**Files:**
- Create: `platform_v2/tools/media_studio/services/template_service.py`

**Dependencies:** Task 1 (tables must exist)

- [ ] **Step 1: Write the template service**

Create `template_service.py` (~220 lines) with these functions:

```python
"""Workflow template service — CRUD, versioning, cloning.

Public API:
- create_template()      — create template with steps
- update_template()      — version-aware update (new row)
- get_template()         — load template + steps
- list_templates()       — filtered list (latest versions only)
- delete_template()      — ownership-verified delete
- get_template_versions() — version history
- clone_template()       — copy to new owner
"""
```

**`create_template(name, description, steps, owner_type, owner_id, visibility='private', tags=None)`**

1. Validate `name` is non-empty string
2. Call `_validate_steps(steps)` — returns `{"error": ...}` or `None`
3. Insert into `media_templates` (use `psycopg2.extras.Json(tags or [])`)
4. For each step in `steps`: insert into `media_template_steps` with `step_order` = index, `params` wrapped in `Json()`
5. Return `{"template_id": id, "version": 1}`

**`update_template(template_id, owner_type, owner_id, updates)`**

Creates a new version:
1. Load existing template, verify ownership (owner matches)
2. Find root: walk `parent_id` chain to find row with `parent_id IS NULL`
3. Get max version: `SELECT MAX(version) FROM media_templates WHERE id = root_id OR parent_id = root_id`
4. Insert new `media_templates` row with:
   - `parent_id = root_id` (all versions point to root)
   - `version = max_version + 1`
   - Updated fields from `updates` dict (name, description, tags, visibility)
   - Copy unchanged fields from original
5. If `updates` contains `steps`: insert new steps. Otherwise, copy steps from original template.
6. Return `{"template_id": new_id, "version": new_version}`

**`get_template(template_id, include_steps=True)`**

1. SELECT from `media_templates WHERE id = template_id`
2. If `include_steps`: SELECT from `media_template_steps WHERE template_id = ... ORDER BY step_order`
3. Serialize datetimes, return dict with `steps` list

**`list_templates(owner_type=None, owner_id=None, visibility_filter=None, tag_filter=None)`**

Query that returns only the latest version per root:
```sql
SELECT DISTINCT ON (COALESCE(parent_id, id)) *
FROM media_templates
WHERE (visibility = 'shared' OR (owner_type = %s AND owner_id = %s))
ORDER BY COALESCE(parent_id, id), version DESC
```
Filter by `visibility_filter` and `tag_filter` (JSONB `@>` operator) if provided.
Return list of dicts with step_count (subquery: `SELECT COUNT(*) FROM media_template_steps WHERE template_id = t.id`).

**`delete_template(template_id, owner_type, owner_id)`**

1. Verify ownership
2. `DELETE FROM media_templates WHERE id = %s` (CASCADE removes steps)
3. Return `{"success": True}` or `{"error": "..."}`

**`get_template_versions(template_id)`**

1. Find root by walking `parent_id` (max 50 iterations)
2. `SELECT id, version, name, created_at, updated_at FROM media_templates WHERE id = root_id OR parent_id = root_id ORDER BY version`
3. Return list of version dicts

**`clone_template(template_id, new_owner_type, new_owner_id)`**

1. Load template + steps
2. Insert new `media_templates` row with new owner, `version=1`, `parent_id=NULL`
3. Copy all steps with new `template_id`
4. Return `{"template_id": new_id}`

**`_validate_steps(steps)`**

```python
VALID_STEP_TYPES = {
    'generate', 'edit_inpaint', 'edit_outpaint', 'edit_upscale',
    'edit_img2img', 'edit_style_transfer', 'batch'
}

def _validate_steps(steps):
    if not steps or not isinstance(steps, list):
        return {"error": "steps must be a non-empty list"}
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return {"error": f"step {i} must be a dict"}
        st = step.get("step_type")
        if st not in VALID_STEP_TYPES:
            return {"error": f"step {i}: invalid step_type '{st}'"}
        # Type-specific required params
        params = step.get("params", {})
        if st == 'generate' and not params.get("prompt"):
            return {"error": f"step {i}: generate requires prompt"}
        if st == 'edit_inpaint' and not params.get("prompt"):
            return {"error": f"step {i}: edit_inpaint requires prompt"}
        if st == 'edit_upscale' and params.get("scale_factor") not in (2, 4):
            return {"error": f"step {i}: edit_upscale requires scale_factor 2 or 4"}
        if st == 'edit_img2img' and not params.get("prompt"):
            return {"error": f"step {i}: edit_img2img requires prompt"}
        if st == 'edit_style_transfer' and not params.get("style_prompt") and not params.get("reference_image_id"):
            return {"error": f"step {i}: style_transfer requires style_prompt or reference_image_id"}
        if st == 'batch' and not params.get("prompts"):
            return {"error": f"step {i}: batch requires prompts list"}
    return None
```

- [ ] **Step 2: Verify imports**

```bash
docker exec archie_platform python3 -c "from tools.media_studio.services.template_service import create_template, update_template, get_template, list_templates, delete_template, clone_template; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/template_service.py
git commit -m "feat(media-studio): add template service with CRUD + versioning + cloning"
```

---

## Task 3: Pipeline Executor

**Files:**
- Create: `platform_v2/tools/media_studio/services/pipeline_executor.py`

**Dependencies:** Task 1 (tables), Task 2 (template_service)

- [ ] **Step 1: Write the pipeline executor**

Create `pipeline_executor.py` (~170 lines):

```python
"""Pipeline executor — runs template steps sequentially in a background thread.

Public API:
- execute_pipeline()     — start pipeline, returns execution_id immediately
- get_pipeline_status()  — check execution progress

Internal:
- _run_pipeline()        — background thread entry point
- _execute_step()        — dispatch single step
- _wait_for_completion() — poll until step completes
"""

import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Timeout per step type (seconds)
STEP_TIMEOUTS = {
    'generate': 600,      # 10 min (video can be slow)
    'edit_inpaint': 300,
    'edit_outpaint': 300,
    'edit_upscale': 300,
    'edit_img2img': 300,
    'edit_style_transfer': 300,
    'batch': 1800,        # 30 min (many items)
}
POLL_INTERVAL = 3  # seconds
```

**`execute_pipeline(template_id, overrides=None, owner_type='user', owner_id=0)`**

1. Load template + steps via `template_service.get_template(template_id)`
2. If template not found, return `{"error": "Template not found"}`
3. Apply `overrides` — dict keyed by step index (string), values merged over step params:
   ```python
   if overrides:
       for idx_str, ovr in overrides.items():
           idx = int(idx_str)
           if 0 <= idx < len(steps):
               steps[idx]['params'] = {**steps[idx]['params'], **ovr}
   ```
4. Insert `media_pipeline_executions` row: status='running', total_steps=len(steps), result_ids='[]'
5. Get Flask app reference: `from flask import current_app; app = current_app._get_current_object()`
6. Start background thread:
   ```python
   t = threading.Thread(
       target=_run_pipeline,
       args=(app, execution_id, steps, owner_type, owner_id),
       daemon=True,
   )
   t.start()
   ```
7. Return `{"execution_id": execution_id, "status": "running"}`

**`_run_pipeline(app, execution_id, steps, owner_type, owner_id)`**

```python
with app.app_context():
    result_ids = []
    prev_result_id = None
    try:
        for i, step in enumerate(steps):
            # Update progress
            _update_execution(execution_id, current_step=i + 1)
            # Execute step
            result = _execute_step(step, prev_result_id, owner_type, owner_id)
            if 'error' in result:
                _fail_execution(execution_id, result['error'], failed_at_step=i + 1)
                return
            prev_result_id = result.get('result_id')
            result_ids.append(prev_result_id)
            _update_execution(execution_id, result_ids=result_ids)
        # All done
        _complete_execution(execution_id, result_ids)
    except Exception as e:
        logger.error(f"Pipeline {execution_id} failed: {e}")
        _fail_execution(execution_id, str(e), failed_at_step=i + 1)
```

**`_execute_step(step, prev_result_id, owner_type, owner_id)`**

Route by step_type:
- `generate`: call `submit_generation(owner_id, step.params.get('media_type', 'image'), step.params['prompt'], step.params.get('negative_prompt', ''), params=step.params, owner_type=owner_type, owner_id=owner_id)`. Get `queue_id`. Poll `media_generation_queue` status until completed. Query `media_library` for the result (match by queue metadata or latest entry).
- `edit_*`: extract edit_type from step_type (strip `edit_` prefix). Call `submit_edit(source_id=prev_result_id, edit_type=..., params=step.params, mask_data=None, owner_type=owner_type, owner_id=owner_id)`. Get `edit_id`. Poll `media_edits` status until completed. Return `result_id` from the edit row.
- `batch`: call `create_batch(name=f'pipeline_batch', owner_type=owner_type, owner_id=owner_id, media_type=step.params.get('media_type', 'image'), prompts=step.params['prompts'], base_params=step.params.get('base_params', {}))`. Get `batch_id`. Poll `media_batches` status until completed. Return batch_id as result_id.

**`_wait_for_completion(table, id_col, id_val, timeout)`**

```python
def _wait_for_completion(table, id_col, id_val, timeout=300):
    """Poll a table row's status until completed/failed or timeout."""
    from database import get_db_cursor
    elapsed = 0
    while elapsed < timeout:
        with get_db_cursor() as (conn, cur):
            cur.execute(f"SELECT status, error_message FROM {table} WHERE {id_col} = %s", (id_val,))
            row = cur.fetchone()
        if not row:
            return {"error": f"Row {id_val} not found in {table}"}
        if row['status'] in ('completed', 'complete'):
            return {"status": "completed"}
        if row['status'] == 'failed':
            return {"error": row.get('error_message', 'Step failed')}
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    return {"error": f"Step timed out after {timeout}s"}
```

Note: The `table` parameter is limited to known tables ('media_generation_queue', 'media_edits', 'media_batches') — never from user input, so SQL injection is not a concern.

**`_update_execution(execution_id, current_step=None, result_ids=None)`** — UPDATE media_pipeline_executions

**`_complete_execution(execution_id, result_ids)`** — SET status='completed', completed_at=NOW()

**`_fail_execution(execution_id, error_message, failed_at_step)`** — SET status='failed'

**`get_pipeline_status(execution_id)`** — SELECT from media_pipeline_executions, return dict or None

- [ ] **Step 2: Verify imports**

```bash
docker exec archie_platform python3 -c "from tools.media_studio.services.pipeline_executor import execute_pipeline, get_pipeline_status; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/pipeline_executor.py
git commit -m "feat(media-studio): add pipeline executor with background step execution"
```

---

## Task 4: API Routes — Template & Pipeline Endpoints

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py` (append S23 section)

**Dependencies:** Task 2 (template_service), Task 3 (pipeline_executor)

- [ ] **Step 1: Read end of routes.py to find append location**

Read last ~30 lines to find where S22 ends.

- [ ] **Step 2: Append S23 section with 8 routes**

Add `# ── S23  Workflow Templates ──` comment, then:

**`POST /api/media-studio/templates`**
```python
@media_studio_bp.route("/api/media-studio/templates", methods=["POST"])
@login_required
def api_create_template():
    from tools.media_studio.services.template_service import create_template
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    result = create_template(
        name=name,
        description=data.get("description", ""),
        steps=data.get("steps", []),
        owner_type="user",
        owner_id=current_user.id,
        visibility=data.get("visibility", "private"),
        tags=data.get("tags"),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`GET /api/media-studio/templates`**
```python
@media_studio_bp.route("/api/media-studio/templates", methods=["GET"])
@login_required
def api_list_templates():
    from tools.media_studio.services.template_service import list_templates
    visibility = request.args.get("visibility")
    owner_type = request.args.get("owner_type")
    tag = request.args.get("tag")
    templates = list_templates(
        owner_type=owner_type or "user",
        owner_id=current_user.id,
        visibility_filter=visibility,
        tag_filter=tag,
    )
    for t in templates:
        for k, v in list(t.items()):
            if hasattr(v, "isoformat"):
                t[k] = v.isoformat()
    return jsonify(templates)
```

**`GET /api/media-studio/templates/<int:template_id>`**
```python
@media_studio_bp.route("/api/media-studio/templates/<int:template_id>", methods=["GET"])
@login_required
def api_get_template(template_id):
    from tools.media_studio.services.template_service import get_template
    result = get_template(template_id)
    if result is None:
        return jsonify({"error": "Template not found"}), 404
    for k, v in list(result.items()):
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    if "steps" in result:
        for s in result["steps"]:
            for k, v in list(s.items()):
                if hasattr(v, "isoformat"):
                    s[k] = v.isoformat()
    return jsonify(result)
```

**`PUT /api/media-studio/templates/<int:template_id>`**
```python
@media_studio_bp.route("/api/media-studio/templates/<int:template_id>", methods=["PUT"])
@login_required
def api_update_template(template_id):
    from tools.media_studio.services.template_service import update_template
    data = request.get_json() or {}
    result = update_template(
        template_id=template_id,
        owner_type="user",
        owner_id=current_user.id,
        updates=data,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`DELETE /api/media-studio/templates/<int:template_id>`**
```python
@media_studio_bp.route("/api/media-studio/templates/<int:template_id>", methods=["DELETE"])
@login_required
def api_delete_template(template_id):
    from tools.media_studio.services.template_service import delete_template
    result = delete_template(template_id, "user", current_user.id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`POST /api/media-studio/templates/<int:template_id>/clone`**
```python
@media_studio_bp.route("/api/media-studio/templates/<int:template_id>/clone", methods=["POST"])
@login_required
def api_clone_template(template_id):
    from tools.media_studio.services.template_service import clone_template
    result = clone_template(template_id, "user", current_user.id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`POST /api/media-studio/templates/<int:template_id>/run`**
```python
@media_studio_bp.route("/api/media-studio/templates/<int:template_id>/run", methods=["POST"])
@login_required
def api_run_pipeline(template_id):
    from tools.media_studio.services.pipeline_executor import execute_pipeline
    data = request.get_json() or {}
    result = execute_pipeline(
        template_id=template_id,
        overrides=data.get("overrides"),
        owner_type="user",
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`GET /api/media-studio/pipeline/<int:execution_id>`**
```python
@media_studio_bp.route("/api/media-studio/pipeline/<int:execution_id>", methods=["GET"])
@login_required
def api_get_pipeline_status(execution_id):
    from tools.media_studio.services.pipeline_executor import get_pipeline_status
    result = get_pipeline_status(execution_id)
    if result is None:
        return jsonify({"error": "Execution not found"}), 404
    for k, v in list(result.items()):
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return jsonify(result)
```

- [ ] **Step 3: Verify routes register**

```bash
docker exec archie_platform python3 -c "
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'media-studio' in r.rule and ('templates' in r.rule or 'pipeline' in r.rule)]
print(f'{len(rules)} routes: {rules}')
"
```

Expected: 8 routes.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add template + pipeline API routes (8 endpoints)"
```

---

## Task 5: Template Library HTML + Builder Modal

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Dependencies:** Task 4 (routes must exist for JS to call)

- [ ] **Step 1: Read the HTML file to find insertion points**

Find: (a) gallery filter buttons for adding Templates toggle, (b) where S22 modal ends for S23 modal, (c) where S22 JS ends for S23 JS.

- [ ] **Step 2: Add Templates view toggle button**

Add a 4th button to `#msGalleryFilter`:
```html
<button class="ms-btn-xs ms-gallery-filter-btn" data-filter="templates" onclick="setOwnerFilter('templates')">Templates</button>
```

Add templates container div (hidden by default, shown when templates filter active):
```html
<!-- ── S23  Workflow Templates ── -->
<div id="msTemplateView" style="display:none;">
  <div class="ms-template-header">
    <span class="ms-template-title">Workflow Templates</span>
    <div class="ms-template-filter">
      <button class="ms-btn-xs ms-template-filter-btn active" data-tfilter="mine" onclick="setTemplateFilter('mine')">My Templates</button>
      <button class="ms-btn-xs ms-template-filter-btn" data-tfilter="shared" onclick="setTemplateFilter('shared')">Shared</button>
      <button class="ms-btn-xs ms-template-filter-btn" data-tfilter="agent" onclick="setTemplateFilter('agent')">Agent</button>
    </div>
    <button class="ms-btn ms-btn-primary" onclick="openTemplateModal()">New Template</button>
  </div>
  <div id="msTemplateList" class="ms-template-list"></div>
</div>
```

- [ ] **Step 3: Add pipeline builder modal**

Insert after the S22 edit modal:

```html
<!-- S23 Template Builder Modal -->
<div id="msTemplateModal" class="ms-template-modal" style="display:none;">
  <div class="ms-template-modal-content">
    <div class="ms-template-modal-header">
      <span>Pipeline Builder</span>
      <button class="ms-edit-modal-close" onclick="closeTemplateModal()">&times;</button>
    </div>
    <div class="ms-template-modal-body">
      <label>Name: <input type="text" id="msTplName" class="ms-input-xs" placeholder="Template name"></label>
      <label>Description: <textarea id="msTplDesc" rows="2" class="ms-input-xs" placeholder="Optional description"></textarea></label>
      <div class="ms-template-steps-header">
        <span>Steps</span>
        <div class="ms-template-add-step">
          <select id="msTplAddStepType" class="ms-input-xs">
            <option value="generate">Generate</option>
            <option value="edit_inpaint">Inpaint</option>
            <option value="edit_outpaint">Outpaint</option>
            <option value="edit_upscale">Upscale</option>
            <option value="edit_img2img">Img2Img</option>
            <option value="edit_style_transfer">Style Transfer</option>
            <option value="batch">Batch</option>
          </select>
          <button class="ms-btn-xs" onclick="addTemplateStep()">Add Step</button>
        </div>
      </div>
      <div id="msTplSteps" class="ms-template-steps"></div>
    </div>
    <div class="ms-template-modal-footer">
      <label>
        <select id="msTplVisibility" class="ms-input-xs">
          <option value="private">Private</option>
          <option value="shared">Shared</option>
        </select>
      </label>
      <label>Tags: <input type="text" id="msTplTags" class="ms-input-xs" placeholder="comma,separated"></label>
      <button class="ms-btn ms-btn-primary" onclick="saveTemplate()">Save Template</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add pipeline progress bar**

Insert after template list div:
```html
<div id="msPipelineProgress" class="ms-pipeline-progress" style="display:none;">
  <span id="msPipelineLabel">Running step 1/3...</span>
  <div class="ms-pipeline-bar">
    <div id="msPipelineBarFill" class="ms-pipeline-bar-fill" style="width:0%"></div>
  </div>
</div>
```

- [ ] **Step 5: Commit HTML**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add template library HTML + pipeline builder modal"
```

---

## Task 6: Template JavaScript

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` (append JS)

**Dependencies:** Task 5 (HTML elements must exist)

- [ ] **Step 1: Update setOwnerFilter to handle 'templates' mode**

Find the existing `setOwnerFilter` function. Add a branch:
```javascript
if (filter === 'templates') {
    document.getElementById('msGalleryGrid').style.display = 'none';  // or whatever the gallery container ID is
    document.getElementById('msTemplateView').style.display = '';
    loadTemplateLibrary();
    return;
} else {
    document.getElementById('msTemplateView').style.display = 'none';
    document.getElementById('msGalleryGrid').style.display = '';  // restore gallery
}
```

Find the gallery container element ID by reading the HTML. It may be `ms-gallery-grid` or similar.

- [ ] **Step 2: Add S23 JavaScript block**

Append after the S22 JS block (~200 lines in IIFE):

```javascript
// ── S23  Workflow Templates JS ──────────────────────────────────────

var _tplFilter = 'mine';
var _editingTemplateId = null;
var _tplSteps = [];

window.setTemplateFilter = function(filter) {
    _tplFilter = filter;
    document.querySelectorAll('.ms-template-filter-btn').forEach(function(b) {
        b.classList.toggle('active', b.dataset.tfilter === filter);
    });
    loadTemplateLibrary();
};

window.loadTemplateLibrary = function() {
    var params = '';
    if (_tplFilter === 'shared') params = '?visibility=shared';
    else if (_tplFilter === 'agent') params = '?owner_type=agent';
    api('GET', '/api/media-studio/templates' + params).then(function(data) {
        var list = document.getElementById('msTemplateList');
        _clearChildren(list);
        if (!Array.isArray(data) || data.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'ms-text-muted';
            empty.textContent = 'No templates found';
            list.appendChild(empty);
            return;
        }
        data.forEach(function(tpl) {
            var card = document.createElement('div');
            card.className = 'ms-template-card';

            var info = document.createElement('div');
            info.className = 'ms-template-card-info';

            var name = document.createElement('div');
            name.className = 'ms-template-card-name';
            name.textContent = tpl.name;
            info.appendChild(name);

            var desc = document.createElement('div');
            desc.className = 'ms-template-card-desc';
            desc.textContent = tpl.description || '';
            info.appendChild(desc);

            var meta = document.createElement('div');
            meta.className = 'ms-template-card-meta';
            meta.textContent = (tpl.step_count || 0) + ' steps';
            if (tpl.version > 1) {
                var vBadge = document.createElement('span');
                vBadge.className = 'ms-version-badge';
                vBadge.textContent = 'v' + tpl.version;
                meta.appendChild(vBadge);
            }
            if (tpl.visibility === 'shared') {
                var vis = document.createElement('span');
                vis.className = 'ms-template-shared-badge';
                vis.textContent = 'shared';
                meta.appendChild(vis);
            }
            info.appendChild(meta);
            card.appendChild(info);

            var actions = document.createElement('div');
            actions.className = 'ms-template-card-actions';

            var runBtn = document.createElement('button');
            runBtn.className = 'ms-btn-xs';
            runBtn.textContent = 'Run';
            runBtn.onclick = function(e) { e.stopPropagation(); runTemplate(tpl.id); };
            actions.appendChild(runBtn);

            var custBtn = document.createElement('button');
            custBtn.className = 'ms-btn-xs';
            custBtn.textContent = 'Customize';
            custBtn.onclick = function(e) { e.stopPropagation(); customizeTemplate(tpl.id); };
            actions.appendChild(custBtn);

            if (_tplFilter === 'shared') {
                var cloneBtn = document.createElement('button');
                cloneBtn.className = 'ms-btn-xs';
                cloneBtn.textContent = 'Clone';
                cloneBtn.onclick = function(e) { e.stopPropagation(); cloneTemplate(tpl.id); };
                actions.appendChild(cloneBtn);
            }

            if (_tplFilter === 'mine') {
                var delBtn = document.createElement('button');
                delBtn.className = 'ms-btn-xs ms-btn-danger';
                delBtn.textContent = 'Delete';
                delBtn.onclick = function(e) {
                    e.stopPropagation();
                    if (confirm('Delete this template?')) deleteTemplate(tpl.id);
                };
                actions.appendChild(delBtn);
            }

            card.appendChild(actions);
            list.appendChild(card);
        });
    });
};

window.openTemplateModal = function(templateId) {
    _editingTemplateId = templateId || null;
    _tplSteps = [];
    document.getElementById('msTplName').value = '';
    document.getElementById('msTplDesc').value = '';
    document.getElementById('msTplTags').value = '';
    document.getElementById('msTplVisibility').value = 'private';
    _clearChildren(document.getElementById('msTplSteps'));
    document.getElementById('msTemplateModal').style.display = 'flex';

    if (templateId) {
        api('GET', '/api/media-studio/templates/' + templateId).then(function(tpl) {
            document.getElementById('msTplName').value = tpl.name || '';
            document.getElementById('msTplDesc').value = tpl.description || '';
            document.getElementById('msTplVisibility').value = tpl.visibility || 'private';
            var tags = tpl.tags || [];
            document.getElementById('msTplTags').value = tags.join(', ');
            _tplSteps = (tpl.steps || []).map(function(s) {
                return {step_type: s.step_type, step_name: s.step_name || '', params: s.params || {}};
            });
            renderTplSteps();
        });
    }
};

window.closeTemplateModal = function() {
    document.getElementById('msTemplateModal').style.display = 'none';
    _editingTemplateId = null;
    _tplSteps = [];
};

window.addTemplateStep = function() {
    var type = document.getElementById('msTplAddStepType').value;
    _tplSteps.push({step_type: type, step_name: '', params: {}});
    renderTplSteps();
};

window.removeTemplateStep = function(idx) {
    _tplSteps.splice(idx, 1);
    renderTplSteps();
};

window.moveTemplateStep = function(idx, dir) {
    var newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= _tplSteps.length) return;
    var tmp = _tplSteps[idx];
    _tplSteps[idx] = _tplSteps[newIdx];
    _tplSteps[newIdx] = tmp;
    renderTplSteps();
};

function renderTplSteps() {
    var container = document.getElementById('msTplSteps');
    _clearChildren(container);
    _tplSteps.forEach(function(step, idx) {
        var div = document.createElement('div');
        div.className = 'ms-template-step';

        var header = document.createElement('div');
        header.className = 'ms-template-step-header';

        var badge = document.createElement('span');
        badge.className = 'ms-template-step-type ms-step-type-' + step.step_type.split('_')[0];
        badge.textContent = step.step_type.replace('edit_', '').replace('_', ' ');
        header.appendChild(badge);

        var orderNum = document.createElement('span');
        orderNum.className = 'ms-text-muted';
        orderNum.textContent = 'Step ' + (idx + 1);
        header.appendChild(orderNum);

        var btnGroup = document.createElement('span');
        if (idx > 0) {
            var upBtn = document.createElement('button');
            upBtn.className = 'ms-btn-xs';
            upBtn.textContent = '\u25B2';
            upBtn.onclick = function() { moveTemplateStep(idx, -1); };
            btnGroup.appendChild(upBtn);
        }
        if (idx < _tplSteps.length - 1) {
            var downBtn = document.createElement('button');
            downBtn.className = 'ms-btn-xs';
            downBtn.textContent = '\u25BC';
            downBtn.onclick = function() { moveTemplateStep(idx, 1); };
            btnGroup.appendChild(downBtn);
        }
        var rmBtn = document.createElement('button');
        rmBtn.className = 'ms-btn-xs ms-btn-danger';
        rmBtn.textContent = '\u00D7';
        rmBtn.onclick = function() { removeTemplateStep(idx); };
        btnGroup.appendChild(rmBtn);
        header.appendChild(btnGroup);
        div.appendChild(header);

        // Params editor
        var paramsDiv = document.createElement('div');
        paramsDiv.className = 'ms-template-step-params';
        buildStepParamEditor(paramsDiv, step, idx);
        div.appendChild(paramsDiv);

        container.appendChild(div);
    });
}

function buildStepParamEditor(container, step, idx) {
    var type = step.step_type;
    var p = step.params;

    function addField(label, id, value, fieldType) {
        var lbl = document.createElement('label');
        lbl.textContent = label + ': ';
        var input;
        if (fieldType === 'textarea') {
            input = document.createElement('textarea');
            input.rows = 2;
        } else {
            input = document.createElement('input');
            input.type = fieldType || 'text';
        }
        input.className = 'ms-input-xs';
        input.value = value || '';
        input.dataset.stepIdx = idx;
        input.dataset.paramKey = id;
        input.onchange = function() {
            var val = input.value;
            if (fieldType === 'number') val = parseFloat(val);
            _tplSteps[parseInt(input.dataset.stepIdx)].params[input.dataset.paramKey] = val;
        };
        lbl.appendChild(input);
        container.appendChild(lbl);
    }

    if (type === 'generate' || type === 'edit_img2img' || type === 'edit_inpaint') {
        addField('Prompt', 'prompt', p.prompt, 'textarea');
        addField('Negative Prompt', 'negative_prompt', p.negative_prompt, 'textarea');
    }
    if (type === 'generate') {
        addField('Width', 'width', p.width || 1024, 'number');
        addField('Height', 'height', p.height || 1024, 'number');
        addField('Steps', 'steps', p.steps || 25, 'number');
        addField('CFG', 'cfg', p.cfg || 7, 'number');
    }
    if (type === 'edit_inpaint' || type === 'edit_img2img' || type === 'edit_style_transfer') {
        addField('Strength', 'strength', p.strength || 0.75, 'number');
    }
    if (type === 'edit_outpaint') {
        addField('Direction', 'direction', p.direction || 'right', 'text');
        addField('Pixels', 'pixels', p.pixels || 128, 'number');
        addField('Prompt', 'prompt', p.prompt, 'textarea');
    }
    if (type === 'edit_upscale') {
        addField('Scale Factor', 'scale_factor', p.scale_factor || 2, 'number');
        addField('Method', 'method', p.method || 'ai', 'text');
    }
    if (type === 'edit_style_transfer') {
        addField('Style Prompt', 'style_prompt', p.style_prompt, 'textarea');
        addField('Reference Image ID', 'reference_image_id', p.reference_image_id, 'number');
    }
    if (type === 'batch') {
        addField('Prompts (one per line)', 'prompts_text', (p.prompts || []).join('\n'), 'textarea');
    }
}

window.saveTemplate = function() {
    var name = document.getElementById('msTplName').value.trim();
    if (!name) { alert('Template name is required'); return; }

    // Collect latest param values from DOM before saving
    // (already updated via onchange handlers)

    // Fix batch prompts: convert text to array
    _tplSteps.forEach(function(s) {
        if (s.step_type === 'batch' && s.params.prompts_text) {
            s.params.prompts = s.params.prompts_text.split('\n').filter(function(l) { return l.trim(); });
            delete s.params.prompts_text;
        }
    });

    var tagsStr = document.getElementById('msTplTags').value;
    var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];

    var body = {
        name: name,
        description: document.getElementById('msTplDesc').value,
        steps: _tplSteps,
        visibility: document.getElementById('msTplVisibility').value,
        tags: tags,
    };

    if (_editingTemplateId) {
        api('PUT', '/api/media-studio/templates/' + _editingTemplateId, body).then(function(data) {
            if (data.error) { alert(data.error); return; }
            closeTemplateModal();
            loadTemplateLibrary();
        });
    } else {
        api('POST', '/api/media-studio/templates', body).then(function(data) {
            if (data.error) { alert(data.error); return; }
            closeTemplateModal();
            loadTemplateLibrary();
        });
    }
};

window.runTemplate = function(templateId) {
    api('POST', '/api/media-studio/templates/' + templateId + '/run', {}).then(function(data) {
        if (data.error) { alert(data.error); return; }
        showPipelineProgress(data.execution_id);
    });
};

window.customizeTemplate = function(templateId) {
    openTemplateModal(templateId);
    // Change save button to "Run with Changes"
    // (or user can just save + run separately)
};

window.cloneTemplate = function(templateId) {
    api('POST', '/api/media-studio/templates/' + templateId + '/clone', {}).then(function(data) {
        if (data.error) { alert(data.error); return; }
        setTemplateFilter('mine');
    });
};

window.deleteTemplate = function(templateId) {
    api('DELETE', '/api/media-studio/templates/' + templateId).then(function(data) {
        if (data.error) { alert(data.error); return; }
        loadTemplateLibrary();
    });
};

function showPipelineProgress(executionId) {
    var progress = document.getElementById('msPipelineProgress');
    progress.style.display = '';
    pollPipelineStatus(executionId);
}

window.pollPipelineStatus = function(executionId) {
    var interval = setInterval(function() {
        api('GET', '/api/media-studio/pipeline/' + executionId).then(function(data) {
            var label = document.getElementById('msPipelineLabel');
            var fill = document.getElementById('msPipelineBarFill');
            if (data.status === 'running') {
                var pct = data.total_steps > 0 ? Math.round((data.current_step / data.total_steps) * 100) : 0;
                label.textContent = 'Running step ' + data.current_step + '/' + data.total_steps + '...';
                fill.style.width = pct + '%';
            }
            if (data.status === 'completed' || data.status === 'failed') {
                clearInterval(interval);
                if (data.status === 'completed') {
                    label.textContent = 'Pipeline complete!';
                    fill.style.width = '100%';
                    if (typeof loadGallery === 'function') loadGallery();
                } else {
                    label.textContent = 'Pipeline failed at step ' + (data.failed_at_step || '?') + ': ' + (data.error_message || 'Unknown error');
                }
                setTimeout(function() {
                    document.getElementById('msPipelineProgress').style.display = 'none';
                }, 5000);
            }
        });
    }, 3000);
};
```

- [ ] **Step 2: Commit JS**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add template library + pipeline builder JavaScript"
```

---

## Task 7: Template CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css` (append)

**Dependencies:** Task 5 (HTML classes must exist)

- [ ] **Step 1: Append S23 CSS block**

```css
/* ── S23  Workflow Templates ── */
.ms-template-header {
    display: flex; align-items: center; gap: 1rem;
    padding: 0.5rem 0; margin-bottom: 0.75rem;
    border-bottom: 1px solid var(--ms-border, #334);
}
.ms-template-title {
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90); font-size: 1rem;
}
.ms-template-filter { display: flex; gap: 0.25rem; }
.ms-template-filter-btn { font-size: 0.7rem; }
.ms-template-filter-btn.active {
    background: var(--ms-accent, #f90); color: #000;
}
.ms-template-list {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 0.75rem;
}
.ms-template-card {
    background: rgba(255,255,255,0.02); border: 1px solid var(--ms-border, #334);
    border-radius: 6px; padding: 0.75rem;
    display: flex; flex-direction: column; gap: 0.5rem;
    transition: border-color 0.2s;
}
.ms-template-card:hover { border-color: var(--ms-accent, #f90); }
.ms-template-card-name {
    font-family: 'Antonio', sans-serif; color: var(--ms-accent, #f90);
    font-size: 0.9rem; text-transform: uppercase;
}
.ms-template-card-desc {
    font-size: 0.7rem; color: var(--ms-text, #aab);
    overflow: hidden; text-overflow: ellipsis;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.ms-template-card-meta {
    display: flex; gap: 0.5rem; align-items: center;
    font-size: 0.65rem; color: var(--ms-text, #aab);
}
.ms-template-shared-badge {
    background: #4a9; color: #000; padding: 1px 4px;
    border-radius: 3px; font-size: 0.55rem;
}
.ms-template-card-actions {
    display: flex; gap: 0.25rem; margin-top: auto;
}
.ms-btn-danger { color: #f44; border-color: #f44; }
.ms-btn-danger:hover { background: rgba(255,68,68,0.1); }

/* Template Modal */
.ms-template-modal {
    position: fixed; inset: 0; z-index: 9999;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.85);
}
.ms-template-modal-content {
    background: var(--ms-bg, #1a1a2e);
    border: 1px solid var(--ms-accent, #f90);
    border-radius: 8px;
    width: 90vw; max-width: 800px; max-height: 90vh;
    display: flex; flex-direction: column; overflow: hidden;
}
.ms-template-modal-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--ms-border, #334);
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90);
}
.ms-template-modal-body {
    padding: 1rem; overflow-y: auto; flex: 1;
    display: flex; flex-direction: column; gap: 0.5rem;
    font-size: 0.75rem; color: var(--ms-text, #aab);
}
.ms-template-modal-body label { display: flex; flex-direction: column; gap: 0.25rem; }
.ms-template-modal-footer {
    display: flex; justify-content: flex-end; align-items: center; gap: 0.75rem;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--ms-border, #334);
}
.ms-template-steps-header {
    display: flex; justify-content: space-between; align-items: center;
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90); margin-top: 0.5rem;
}
.ms-template-add-step { display: flex; gap: 0.25rem; align-items: center; }
.ms-template-steps {
    display: flex; flex-direction: column; gap: 0.5rem;
    min-height: 60px;
}
.ms-template-step {
    border: 1px solid var(--ms-border, #334); border-radius: 4px;
    padding: 0.5rem; background: rgba(255,255,255,0.02);
}
.ms-template-step-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 0.5rem;
}
.ms-template-step-type {
    padding: 2px 6px; border-radius: 3px;
    font-size: 0.6rem; text-transform: uppercase;
    font-family: 'Antonio', sans-serif;
}
.ms-step-type-generate { background: #2a5; color: #000; }
.ms-step-type-edit { background: #47b; color: #fff; }
.ms-step-type-batch { background: #85c; color: #fff; }
.ms-template-step-params {
    display: flex; flex-direction: column; gap: 0.25rem;
    font-size: 0.7rem;
}
.ms-template-step-params label { flex-direction: row; gap: 0.5rem; align-items: center; }

/* Pipeline Progress */
.ms-pipeline-progress {
    padding: 0.75rem; margin: 0.5rem 0;
    border: 1px solid var(--ms-accent, #f90);
    border-radius: 4px; background: rgba(255,153,0,0.05);
    font-size: 0.75rem; color: var(--ms-accent, #f90);
}
.ms-pipeline-bar {
    height: 6px; background: var(--ms-border, #334);
    border-radius: 3px; margin-top: 0.5rem; overflow: hidden;
}
.ms-pipeline-bar-fill {
    height: 100%; background: var(--ms-accent, #f90);
    border-radius: 3px; transition: width 0.5s ease;
}
```

- [ ] **Step 2: Commit CSS**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add template library + pipeline builder CSS"
```

---

## Task 8: Integration Test

**Files:**
- Create: `/tmp/test_layer9.py`

**Dependencies:** All previous tasks

- [ ] **Step 1: Write integration test**

```python
import sys, json, os, logging, inspect
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test imports
from tools.media_studio.services.template_service import (
    create_template, update_template, get_template, list_templates,
    delete_template, get_template_versions, clone_template, _validate_steps,
)
results.append(('Import template_service', 'OK', True))

from tools.media_studio.services.pipeline_executor import (
    execute_pipeline, get_pipeline_status,
)
results.append(('Import pipeline_executor', 'OK', True))

from app import app
with app.app_context():
    # Test step validation
    r = _validate_steps(None)
    results.append(('Reject None steps', r.get('error', ''), 'error' in r))

    r = _validate_steps([])
    results.append(('Reject empty steps', r.get('error', ''), 'error' in r))

    r = _validate_steps([{'step_type': 'bad'}])
    results.append(('Reject bad step_type', r.get('error', ''), 'error' in r))

    r = _validate_steps([{'step_type': 'generate', 'params': {}}])
    results.append(('Generate needs prompt', r.get('error', ''), 'error' in r))

    r = _validate_steps([{'step_type': 'generate', 'params': {'prompt': 'test'}}])
    results.append(('Valid generate step', r, r is None))

    r = _validate_steps([
        {'step_type': 'generate', 'params': {'prompt': 'test'}},
        {'step_type': 'edit_upscale', 'params': {'scale_factor': 2}},
    ])
    results.append(('Valid 2-step pipeline', r, r is None))

    r = _validate_steps([{'step_type': 'edit_upscale', 'params': {'scale_factor': 3}}])
    results.append(('Upscale bad scale', r.get('error', ''), 'error' in r))

    # Test create + get + list + delete cycle
    from database import get_db_cursor
    cr = create_template(
        name='Test Template',
        description='Integration test',
        steps=[
            {'step_type': 'generate', 'step_name': 'gen', 'params': {'prompt': 'test img'}},
            {'step_type': 'edit_upscale', 'step_name': 'upscale', 'params': {'scale_factor': 2}},
        ],
        owner_type='user', owner_id=1, visibility='private', tags=['test'],
    )
    results.append(('Create template', cr.get('template_id', 0) > 0, 'error' not in cr))
    tpl_id = cr.get('template_id')

    if tpl_id:
        # Get
        tpl = get_template(tpl_id)
        results.append(('Get template name', tpl['name'], tpl['name'] == 'Test Template'))
        results.append(('Get template steps', len(tpl.get('steps', [])), len(tpl.get('steps', [])) == 2))
        results.append(('Steps ordered', tpl['steps'][0]['step_type'], tpl['steps'][0]['step_type'] == 'generate'))

        # Update (creates version 2)
        ur = update_template(tpl_id, 'user', 1, {'name': 'Test Template v2'})
        results.append(('Update creates new version', ur.get('version', 0), ur.get('version', 0) == 2))
        new_id = ur.get('template_id')

        # List should show latest version
        tpls = list_templates(owner_type='user', owner_id=1)
        found = [t for t in tpls if t.get('name') == 'Test Template v2']
        results.append(('List shows latest version', len(found), len(found) >= 1))

        # Clone
        cl = clone_template(tpl_id, 'user', 999)
        results.append(('Clone template', cl.get('template_id', 0) > 0, 'error' not in cl))

        # Version history
        versions = get_template_versions(tpl_id)
        results.append(('Version history', len(versions), len(versions) >= 2))

        # Delete
        dr = delete_template(tpl_id, 'user', 1)
        results.append(('Delete original', dr.get('success', False), dr.get('success', False)))
        if new_id:
            delete_template(new_id, 'user', 1)
        if cl.get('template_id'):
            delete_template(cl['template_id'], 'user', 999)

    # DB tables exist
    with get_db_cursor() as (conn, cur):
        for tbl in ['media_templates', 'media_template_steps', 'media_pipeline_executions', 'media_template_collection_items']:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {tbl}")
            cnt = cur.fetchone()['cnt']
            results.append((f'{tbl} table exists', cnt >= 0, True))

    # Routes registered
    rules = [r.rule for r in app.url_map.iter_rules()
             if 'media-studio' in r.rule and ('templates' in r.rule or 'pipeline' in r.rule)]
    results.append(('Template/pipeline routes', len(rules), len(rules) >= 8))

    # HTML checks
    html_path = '/app/tools/media_studio/templates/tools/media_studio/media_studio.html'
    with open(html_path) as f:
        html = f.read()
    for elem in ['msTemplateView', 'msTemplateModal', 'msTplSteps', 'msTplName',
                 'loadTemplateLibrary', 'openTemplateModal', 'saveTemplate',
                 'runTemplate', 'pollPipelineStatus', 'msPipelineProgress']:
        results.append((f'HTML has {elem}', elem, elem in html))

    # CSS checks
    css_path = '/app/tools/media_studio/static/css/media-studio.css'
    with open(css_path) as f:
        css = f.read()
    for cls in ['.ms-template-card', '.ms-template-modal', '.ms-template-steps',
                '.ms-template-step', '.ms-pipeline-progress', '.ms-pipeline-bar',
                '.ms-step-type-generate']:
        results.append((f'CSS has {cls}', cls, cls in css))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_layer9.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_layer9.py
```

Expected: All tests PASS.

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 9: Deploy + Git Push + Dev HQ Update

**Dependencies:** Task 8 (all tests pass)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify running**

```bash
docker logs --tail 20 archie_platform
```

- [ ] **Step 3: Push to remote**

```bash
git push origin main
```

- [ ] **Step 4: Update Dev HQ**

Use MCP tools:
- `complete_task` for Layer 9 task
- `log_decision` for architectural choices (template versioning via parent_id roots, separate template_collection_items table, background thread pipeline executor)
- `store_memory` for roadmap update (Layer 9 complete)
- `update_project_understanding` for Media Studio project
