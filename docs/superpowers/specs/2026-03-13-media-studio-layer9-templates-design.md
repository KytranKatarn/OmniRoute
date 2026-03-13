# Media Studio Layer 9: Workflow Templates & Pipeline Execution — Design Spec

## Overview

Add reusable workflow templates to Media Studio. Users and agents save generation + edit + batch configurations as multi-step pipeline templates. Templates are versioned, shareable, organized in collections, and executable with one click or customizable before running.

**Goal:** Save any combination of generation, editing, and batch operations as a reusable pipeline template. Execute templates instantly or tweak params before running. Share templates across users and agents. Track pipeline execution progress step by step.

## Scope

Four capabilities:
1. **Template CRUD** — create, update (versioned), list, delete, clone templates with ordered steps
2. **Pipeline execution** — sequential step runner that chains generate → edit → batch operations
3. **Template library** — browsable/filterable template list with personal, shared, and agent templates
4. **Pipeline builder** — modal UI to compose multi-step templates with type-specific param editors

## Database Schema

### New table: `media_templates`

```sql
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
```

### New table: `media_template_steps`

```sql
CREATE TABLE IF NOT EXISTS media_template_steps (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES media_templates(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_type VARCHAR(30) NOT NULL,
    step_name VARCHAR(100) DEFAULT '',
    params JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
```

Step types: `generate`, `edit_inpaint`, `edit_outpaint`, `edit_upscale`, `edit_img2img`, `edit_style_transfer`, `batch`

Params JSONB holds type-specific config:
- **generate**: `{prompt, negative_prompt, media_type, model, width, height, steps, cfg, sampler, seed}`
- **edit_***: `{prompt, strength, direction, pixels, scale_factor, method, style_prompt, reference_image_id}`
- **batch**: `{prompts: [...], sweep_param, sweep_values, base_params}`

### New table: `media_pipeline_executions`

```sql
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
```

### Reuse existing `media_collections`

Templates are added to collections via `media_collection_items` with `item_type='template'` and `item_id` referencing `media_templates.id`.

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_media_templates_owner ON media_templates(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_templates_visibility ON media_templates(visibility);
CREATE INDEX IF NOT EXISTS idx_media_templates_parent ON media_templates(parent_id);
CREATE INDEX IF NOT EXISTS idx_media_template_steps_template ON media_template_steps(template_id, step_order);
CREATE INDEX IF NOT EXISTS idx_media_pipeline_exec_owner ON media_pipeline_executions(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_pipeline_exec_status ON media_pipeline_executions(status);
```

## Template Service

**New file:** `platform_v2/tools/media_studio/services/template_service.py` (~200 lines)

### `create_template(name, description, steps, owner_type, owner_id, visibility, tags)`
1. Validate name is non-empty
2. Validate each step via `_validate_steps(steps)`
3. Insert into `media_templates`, then insert each step into `media_template_steps` with incrementing `step_order`
4. Return `{template_id, version: 1}`

### `update_template(template_id, owner_type, owner_id, updates)`
Creates a new version:
1. Verify ownership
2. Copy existing template to new row with `parent_id=template_id`, `version=max+1`
3. Copy steps if not provided in updates, otherwise use new steps
4. Apply field updates (name, description, tags, visibility)
5. Return `{template_id: new_id, version: new_version}`

### `get_template(template_id, include_steps=True)`
Load template + optionally its steps ordered by `step_order`. Return dict.

### `list_templates(owner_type, owner_id, visibility_filter=None, tag_filter=None)`
Query templates filtered by owner and/or visibility. Shared templates visible to all. Return list of dicts (without steps for performance).

### `delete_template(template_id, owner_type, owner_id)`
Verify ownership, DELETE (cascade removes steps). Return success/error.

### `get_template_versions(template_id)`
Walk `parent_id` chain to root, return all versions sorted by version number.

### `clone_template(template_id, new_owner_type, new_owner_id)`
Copy template + steps with new owner, `version=1`, `parent_id=NULL`.

### `_validate_steps(steps)`
Validate each step dict has:
- `step_type` in allowed set
- Required params per type (reuses validation logic from edit_service and generation patterns)
- Returns `{"error": "..."}` or `None`

## Pipeline Executor

**New file:** `platform_v2/tools/media_studio/services/pipeline_executor.py` (~150 lines)

### `execute_pipeline(template_id, overrides, owner_type, owner_id)`

1. Load template + steps via `template_service.get_template()`
2. Apply `overrides` dict — keys are step indices (as strings), values are param dicts merged over saved params
3. Insert `media_pipeline_executions` row with status `running`, `total_steps=len(steps)`
4. Launch background thread for sequential execution
5. Return `{execution_id, status: "running"}` immediately

### Background execution loop

For each step in order:
- **`generate`**: Call `submit_generation()` with step params. Poll `media_generation_queue` until completed. Store resulting `media_library.id`.
- **`edit_*`**: Call `submit_edit()` with `source_id` from previous step's output + step params. Poll `media_edits` until completed. Store `result_id`.
- **`batch`**: Call `create_batch()` with step params. Poll batch status. Store batch result IDs.
- After each step: update `pipeline_execution.current_step` and append result to `result_ids`
- On completion: set status `completed`, `completed_at=NOW()`
- On failure: set status `failed`, `error_message`, `failed_at_step`

### `get_pipeline_status(execution_id)`
Simple SELECT from `media_pipeline_executions`, return dict.

### `_wait_for_step(step_type, step_id, timeout=300)`
Poll appropriate status endpoint every 3 seconds until completed/failed or timeout.

## API Routes

**Modified file:** `platform_v2/tools/media_studio/routes.py`

### Template CRUD (4 endpoints)

#### `POST /api/media-studio/templates`
Create template. Body: `{name, description, steps: [{step_type, step_name, params}], visibility, tags}`.
Response: `{template_id, version}`

#### `GET /api/media-studio/templates`
List templates. Query: `?visibility=shared`, `?tag=portrait`, `?owner_type=agent`.
Response: `[{id, name, description, step_count, version, visibility, tags, created_at}]`

#### `GET /api/media-studio/templates/<int:template_id>`
Get template with steps.
Response: `{id, name, ..., steps: [{step_order, step_type, step_name, params}]}`

#### `DELETE /api/media-studio/templates/<int:template_id>`
Delete template. Owner only.
Response: `{success: true}`

### Versioning & cloning (2 endpoints)

#### `PUT /api/media-studio/templates/<int:template_id>`
Update template (creates new version). Body: `{name, description, steps, tags, visibility}`.
Response: `{template_id: new_id, version}`

#### `POST /api/media-studio/templates/<int:template_id>/clone`
Clone shared template to own library.
Response: `{template_id: new_id}`

### Pipeline execution (2 endpoints)

#### `POST /api/media-studio/templates/<int:template_id>/run`
Execute pipeline. Body: `{overrides: {"0": {param_overrides}, "1": {...}}}` (optional).
Response: `{execution_id, status: "running"}`

#### `GET /api/media-studio/pipeline/<int:execution_id>`
Pipeline execution status.
Response: `{id, status, current_step, total_steps, result_ids, error_message, failed_at_step}`

## Frontend

**Modified file:** `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

### Template library view

Activated via a "Templates" button alongside existing gallery filters. When active, replaces gallery with:
- Template cards showing name, description, step count, version badge, visibility icon
- Filter bar: My Templates | Shared | Agent Templates
- Collection sidebar (reuses Layer 5 pattern)
- "New Template" button

### Template card actions
- **Run** — executes immediately with saved params
- **Customize** — opens builder pre-filled for tweaking before run
- **Clone** (shared templates) — copies to own library
- **Edit** (own templates) — opens builder for editing
- **Delete** (own templates)

### Pipeline builder modal (`#msTemplateModal`)
- Name input + description textarea
- Ordered step list with type badge, params summary, up/down/delete buttons
- "Add Step" dropdown with step types
- Clicking a step expands inline param editor (reuses same fields as edit modal)
- Footer: visibility toggle, tags input, Save button

### Pipeline progress indicator
When running, shows progress bar: "Running step 2/4: Upscale 2x..." Polls every 3 seconds. On completion, refreshes gallery.

### JS functions (~180 lines)
- `loadTemplateLibrary()` — fetch and render template cards
- `openTemplateModal(templateId?)` — open builder, optionally pre-filled
- `addTemplateStep(stepType)` — append step to builder
- `removeTemplateStep(index)` — remove step
- `moveTemplateStep(index, direction)` — reorder up/down
- `saveTemplate()` — collect steps + metadata, POST/PUT
- `runTemplate(templateId)` — POST run, start polling
- `customizeTemplate(templateId)` — open builder pre-filled, run on save
- `cloneTemplate(templateId)` — POST clone
- `pollPipelineStatus(executionId)` — poll until done
- `loadTemplateVersions(templateId)` — show version history

## CSS

**Modified file:** `platform_v2/tools/media_studio/static/css/media-studio.css`

New styles (~90 lines):
- `.ms-template-card` — template list card
- `.ms-template-card-actions` — button group
- `.ms-template-modal` — pipeline builder modal
- `.ms-template-steps` — step list container
- `.ms-template-step` — step card with type icon
- `.ms-template-step-expanded` — expanded param editor
- `.ms-template-step-type` — color-coded type badge
- `.ms-template-add-step` — add step dropdown
- `.ms-template-visibility` — toggle
- `.ms-pipeline-progress` — execution progress bar
- `.ms-template-filter` — filter bar

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/155_media_templates.sql` | 3 tables + indexes |
| **Create** | `platform_v2/tools/media_studio/services/template_service.py` | Template CRUD + versioning (~200 lines) |
| **Create** | `platform_v2/tools/media_studio/services/pipeline_executor.py` | Sequential step runner (~150 lines) |
| **Modify** | `platform_v2/tools/media_studio/routes.py` | 8 new endpoints |
| **Modify** | `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Template library + builder modal + JS (~180 lines) |
| **Modify** | `platform_v2/tools/media_studio/static/css/media-studio.css` | Template + pipeline styles (~90 lines) |

**Total:** ~620 lines new code, ~50 lines modifications

## Dependencies

None new — reuses existing services (submit_generation, submit_edit, create_batch)

## Scope constraints

- No conditional/branching steps (linear only)
- No template marketplace or rating system
- No template import/export as files
- No real-time preview of pipeline output between steps
- No parallel step execution
