# Social Video Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI video content pipeline that generates and publishes agent moments, motivational videos, and employer branding content to Instagram, Facebook, and Indeed.

**Architecture:** Extends existing Media Studio video generation with a RunPod cloud GPU provider, adds a social content queue with approval tiers, and wires agent loop jobs for automated content creation and publishing. Leverages existing Social Media module's publishing infrastructure.

**Tech Stack:** Flask, PostgreSQL, LTX-Video (ComfyUI), RunPod Serverless API, Instagram Graph API, Facebook Graph API, Indeed Employer API, ffmpeg, APScheduler

**Security Note:** All UI rendering of queue data must use textContent or DOM methods for text fields, and DOMPurify or escHtml() for any HTML content. Queue data is admin-only but treat as untrusted.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `database/migrations/306_social_content_queue.sql` | New tables: social_content_queue, social_content_templates, social_content_approvals, cloud_gpu_usage |
| `platform_v2/tools/media_studio/services/runpod_provider.py` | RunPod Serverless API client extending VideoProvider pattern |
| `platform_v2/tools/media_studio/services/social_video_service.py` | Content queue CRUD, approval logic, template rendering, budget tracking |
| `platform_v2/tools/media_studio/social_video_routes.py` | Routes for Social Video tab (manual create, queue mgmt, approve/reject) |
| `platform_v2/tools/media_studio/services/social_video_worker.py` | Generation worker — routes to local ComfyUI or RunPod cloud |
| `platform_v2/tools/social_media/indeed_client.py` | Indeed Employer API client for video posts |

### Modified Files
| File | Change |
|------|--------|
| `platform_v2/tools/media_studio/__init__.py` | Register social_video_routes |
| `platform_v2/tools/media_studio/services/video_providers.py` | Import and register RunPodVideoProvider |
| `platform_v2/tools/social_media/platform_clients.py` | Add Indeed client singleton |
| `ai_bridge/agent_loop.py` | Add 3 new scheduled jobs (#59, #60, #61) |
| `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Add Social Video tab |
| `platform_v2/.env` | Add RUNPOD_*, INDEED_*, SOCIAL_VIDEO_* env vars |

---

### Task 1: Database Migration — Content Queue and Templates

**Files:**
- Create: `database/migrations/306_social_content_queue.sql`

- [ ] **Step 1: Write the migration SQL**

Create `database/migrations/306_social_content_queue.sql` with:
- `social_content_queue` table (id, content_type, agent_id FK, template_id, prompt, video_path, thumbnail_path, caption, hashtags TEXT[], target_platforms TEXT[], status with CHECK constraint, approval_tier, rejection_reason, scheduled_at, posted_at, post_urls JSONB, generation_params JSONB, cloud_cost DECIMAL, created_by, created_at, updated_at)
- `social_content_templates` table (id, content_type, name, prompt_template, caption_template, default_hashtags TEXT[], style_directive, video_params JSONB, platforms TEXT[], approval_tier, is_active, times_used, created_at)
- `social_content_approvals` table (id, agent_id FK, content_type, approved_count, auto_approved BOOLEAN, updated_at, UNIQUE on agent_id+content_type)
- `cloud_gpu_usage` table (id, provider, job_type, cost DECIMAL, gpu_seconds DECIMAL, metadata JSONB, created_at)
- Indexes on status, content_type, scheduled_at, agent_id, daily cost lookups
- 8 seed templates: 3 agent_moment (selfie, working late, team collab), 2 motivational (quote, progress), 2 employer_branding (project showcase, life at kytran), 1 recruitment (role spotlight)
- Status CHECK: draft, generating, ready, approved, scheduled, posted, rejected, failed
- Content type CHECK: agent_moment, motivational, employer_branding, recruitment
- Wrap in BEGIN/COMMIT, use IF NOT EXISTS and ON CONFLICT DO NOTHING for idempotency

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/306_social_content_queue.sql
```

Expected: CREATE TABLE x4, CREATE INDEX x5, INSERT 0 8

- [ ] **Step 3: Verify tables**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt social_content_*"
docker exec archie_database psql -U archie -d archie -c "SELECT count(*) FROM social_content_templates"
```

Expected: 3 tables listed, count = 8

- [ ] **Step 4: Commit**

```bash
git add database/migrations/306_social_content_queue.sql
git commit -m "feat(social-video): add content queue, templates, approvals, and GPU usage tables"
```

---

### Task 2: RunPod Video Provider

**Files:**
- Create: `platform_v2/tools/media_studio/services/runpod_provider.py`
- Modify: `platform_v2/tools/media_studio/services/video_providers.py`

**Context:** Existing `video_providers.py` has GoogleVeoProvider, ReplicateVideoProvider, HuggingFaceVideoProvider, LTXStudioProvider. Each has `generate()`, `get_status()`, `get_capabilities()`. Follow the same pattern.

- [ ] **Step 1: Create RunPod provider**

Create `platform_v2/tools/media_studio/services/runpod_provider.py` with class `RunPodVideoProvider`:

- `__init__`: reads RUNPOD_API_KEY and RUNPOD_LTX_ENDPOINT_ID from env
- `is_configured()`: returns True if both env vars set
- `generate(prompt, params)`: POST to `https://api.runpod.ai/v2/{endpoint_id}/run` with input payload (prompt, negative_prompt, width, height, num_frames, fps, num_inference_steps, guidance_scale). Returns dict with job_id, status, provider.
- `get_status(job_id)`: GET status endpoint, returns status + output_url when COMPLETED + estimated_cost (exec_time * $0.00036/sec for RTX 3090)
- `get_capabilities()`: returns name, type=cloud_gpu, supports_video=True, max_resolution=1024, max_frames=120, models=["ltx-video"], configured status
- `download_result(output_url, save_path)`: streams download to local file, returns success + path + size_bytes
- All HTTP calls use `requests` with explicit timeouts (30s submit, 15s status, 120s download)
- All errors logged and returned as `{"error": str(e)}`, never raised

- [ ] **Step 2: Register in video_providers.py**

Read `video_providers.py`, add import `from .runpod_provider import RunPodVideoProvider` and add `"runpod": RunPodVideoProvider()` to the provider registry.

- [ ] **Step 3: Add env vars**

Append to `platform_v2/.env`:
```
RUNPOD_API_KEY=
RUNPOD_LTX_ENDPOINT_ID=
SOCIAL_VIDEO_DAILY_BUDGET=5.00
SOCIAL_VIDEO_MONTHLY_BUDGET=50.00
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/services/runpod_provider.py platform_v2/tools/media_studio/services/video_providers.py platform_v2/.env
git commit -m "feat(social-video): add RunPod Serverless video provider with budget tracking"
```

---

### Task 3: Social Video Service — Queue and Template Logic

**Files:**
- Create: `platform_v2/tools/media_studio/services/social_video_service.py`

**Context:** Core business logic layer. All DB access for social content. Uses `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):` pattern.

- [ ] **Step 1: Create social_video_service.py**

Functions to implement:

**Template operations:**
- `get_templates(content_type=None, active_only=True)` — SELECT with optional filters, returns list of dicts
- `get_template(template_id)` — single template by ID
- `render_template(template_id, variables)` — fetches template, replaces `{placeholder}` in prompt_template and caption_template with provided variables dict, returns rendered prompt + caption + hashtags + video_params + approval_tier

**Queue CRUD:**
- `create_queue_item(content_type, prompt, caption, hashtags, target_platforms, agent_id, template_id, approval_tier, generation_params, created_by, scheduled_at)` — INSERT RETURNING *, generation_params wrapped with json.dumps
- `get_queue_items(status, content_type, limit=50, offset=0)` — SELECT with LEFT JOIN agents for display_name, ordered by created_at DESC
- `get_queue_item(item_id)` — single item with agent display_name join
- `update_queue_item(item_id, **kwargs)` — whitelist allowed fields (caption, hashtags, target_platforms, status, scheduled_at, video_path, thumbnail_path, post_urls, rejection_reason, cloud_cost, posted_at), auto-set updated_at, UPDATE RETURNING *

**Actions:**
- `approve_item(item_id)` — sets status=approved, calls _increment_approval_count if agent_id present
- `reject_item(item_id, reason)` — sets status=rejected + rejection_reason
- `schedule_item(item_id, scheduled_at)` — sets status=scheduled + scheduled_at

**Auto-approval:**
- `_increment_approval_count(agent_id, content_type)` — UPSERT into social_content_approvals, increments count, sets auto_approved=true when count >= AUTO_APPROVE_THRESHOLD (3)
- `should_auto_approve(agent_id, content_type)` — returns False for employer_branding/recruitment (always manual), True for motivational (always auto), checks social_content_approvals.auto_approved for agent_moment

**Budget:**
- `check_budget()` — queries cloud_gpu_usage for today's sum and month's sum, compares against SOCIAL_VIDEO_DAILY_BUDGET and SOCIAL_VIDEO_MONTHLY_BUDGET env vars, returns daily_remaining, monthly_remaining, can_generate boolean
- `log_gpu_usage(provider, job_type, cost, gpu_seconds, metadata)` — INSERT into cloud_gpu_usage

**Helpers:**
- `pick_agent_for_content(content_type)` — SELECT random active agent (shift_state=active, is_active=true), returns dict with id, name, display_name, department, personality, backstory
- `get_queue_stats()` — returns status_counts dict, posted_this_week count, monthly_cost sum

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/social_video_service.py
git commit -m "feat(social-video): add social video service — queue CRUD, templates, approval, budget"
```

---

### Task 4: Social Video Routes — Media Studio API

**Files:**
- Create: `platform_v2/tools/media_studio/social_video_routes.py`
- Modify: `platform_v2/tools/media_studio/__init__.py`

**Context:** Follows ADR-045 pattern: `register_social_video_routes(bp, admin_required)` called from `__init__.py`. Routes are thin HTTP handlers calling social_video_service.

- [ ] **Step 1: Create social_video_routes.py**

Function `register_social_video_routes(bp, admin_required)` with routes:

**Templates:**
- `GET /api/social-video/templates` — optional ?content_type filter, returns templates list
- `POST /api/social-video/templates/<id>/render` — accepts JSON body with variables, returns rendered prompt/caption/hashtags

**Queue:**
- `GET /api/social-video/queue` — optional ?status, ?content_type, ?limit, ?offset filters
- `GET /api/social-video/queue/<id>` — single item
- `PATCH /api/social-video/queue/<id>` — update caption/hashtags/platforms

**Actions:**
- `POST /api/social-video/queue/<id>/approve` — approve item
- `POST /api/social-video/queue/<id>/reject` — reject with optional reason in body
- `POST /api/social-video/queue/<id>/schedule` — schedule with scheduled_at in body (ISO format)

**Generate:**
- `POST /api/social-video/generate` — accepts content_type (required), prompt or template_id+template_variables, caption, hashtags, target_platforms, agent_id, quality (draft/standard/high). Quality maps to video params: draft=256x256/9frames, standard=512x512/24frames, high=768x512/48frames. Checks budget for non-draft. Creates queue item, sets status to "generating". Returns created item.

**Stats:**
- `GET /api/social-video/stats` — queue stats + budget info
- `GET /api/social-video/budget` — budget only

All routes decorated with `@admin_required`.

- [ ] **Step 2: Register routes in __init__.py**

Read `__init__.py`, add after existing route registrations:
```python
from .social_video_routes import register_social_video_routes
register_social_video_routes(bp, admin_required)
```

- [ ] **Step 3: Create upload directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/static/social_videos
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/social_video_routes.py platform_v2/tools/media_studio/__init__.py
git commit -m "feat(social-video): add Social Video routes — generate, queue, approve, schedule, budget"
```

---

### Task 5: Indeed Client

**Files:**
- Create: `platform_v2/tools/social_media/indeed_client.py`
- Modify: `platform_v2/tools/social_media/platform_clients.py`

- [ ] **Step 1: Create indeed_client.py**

Class `IndeedClient`:
- `__init__`: reads INDEED_API_KEY and INDEED_EMPLOYER_ID from env
- `is_configured()`: checks both env vars
- `post_video(video_path, caption, hashtags)`: two-step upload (POST media file, then POST create post with mediaId + description + hashtags). Returns success + post_id + post_url + platform="indeed"
- `get_post_stats(post_id)`: GET stats for engagement tracking
- API base: `https://apis.indeed.com/employer`
- All errors return `{"success": False, "error": str(e)}`, never raised
- Timeouts: 120s for upload, 30s for post creation, 15s for stats

- [ ] **Step 2: Register in platform_clients.py**

Add import and singleton pattern:
```python
from .indeed_client import IndeedClient
_indeed_client = None
def get_indeed_client():
    global _indeed_client
    if _indeed_client is None:
        _indeed_client = IndeedClient()
    return _indeed_client
```

- [ ] **Step 3: Add env vars to platform_v2/.env**

```
INDEED_API_KEY=
INDEED_EMPLOYER_ID=
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/social_media/indeed_client.py platform_v2/tools/social_media/platform_clients.py platform_v2/.env
git commit -m "feat(social-video): add Indeed Employer API client for recruitment video posts"
```

---

### Task 6: Generation Worker — Bridge Integration

**Files:**
- Create: `platform_v2/tools/media_studio/services/social_video_worker.py`

**Context:** Processes items in "generating" status. Routes drafts to local ComfyUI, standard/high to RunPod. Extracts thumbnails via ffmpeg.

- [ ] **Step 1: Create social_video_worker.py**

Function `process_queue()`:
- Fetches items with status="generating" (limit 5)
- For each, calls `_process_item(item)`
- On failure, sets status="failed"

Function `_process_item(item)`:
- Reads generation_params.quality
- Routes to `_generate_local()` for draft, `_generate_cloud()` for standard/high
- On success: extracts thumbnail, updates item to status="ready" with video_path + thumbnail_path + cloud_cost
- Logs GPU usage via `svs.log_gpu_usage()` for cloud jobs

Function `_generate_local(prompt, params)`:
- Loads `/mnt/archie_brain/comfyui/workflows/ltx-video-basic.json`
- Injects prompt into CLIPTextEncode positive node
- POSTs to ComfyUI at `http://192.168.1.200:8188/prompt`
- Polls `/history/{prompt_id}` every 5s, max 10 min
- Downloads output to `/mnt/archie_brain/platform_v2/static/social_videos/sv_{uuid}.webp`
- Returns success + path + provider="local" + cost=0

Function `_generate_cloud(prompt, params)`:
- Instantiates RunPodVideoProvider
- If not configured, falls back to `_generate_local()`
- Calls `provider.generate(prompt, params)`
- Polls `provider.get_status(job_id)` every 5s, max 5 min
- On COMPLETED: downloads via `provider.download_result()` to `sv_{uuid}.mp4`
- Returns success + path + provider="runpod" + cost + gpu_seconds

Function `_extract_thumbnail(video_path, thumb_path)`:
- Runs `ffmpeg -y -i {video_path} -vframes 1 -vf scale=320:-1 {thumb_path}`
- subprocess.run with capture_output=True, timeout=30
- Logs warning on failure, doesn't raise

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/services/social_video_worker.py
git commit -m "feat(social-video): add generation worker — local ComfyUI + RunPod cloud routing"
```

---

### Task 7: Agent Loop Jobs — Automated Pipeline

**Files:**
- Modify: `ai_bridge/agent_loop.py`

**Context:** Agent loop uses APScheduler. Currently 58 jobs. We add 3 new jobs. Functions import social_video_service lazily to avoid circular imports.

- [ ] **Step 1: Read agent_loop.py**

Find: import section, job registration section (scheduler.add_job calls), and where other job functions are defined.

- [ ] **Step 2: Add job function `_social_video_generate_content()`**

Runs every 4 hours. Logic:
1. Check budget via `svs.check_budget()` — skip if exceeded
2. Check pending queue items (generating + draft) — skip if >= 5 pending
3. Pick content type by weighted random: motivational (7x weight = daily), agent_moment (3x weight = 3-4x/week)
4. Get active templates for chosen type, pick random one
5. Build template variables:
   - agent_moment: pick random active agent, fill agent_name, department, personality_trait
   - motivational: pick random quote from a curated list of 8 quotes, pick random scene description
6. Render template
7. Determine approval tier (check should_auto_approve)
8. Create queue item with created_by="agent_loop"
9. Call `process_queue()` from social_video_worker to trigger immediate generation

- [ ] **Step 3: Add job function `_social_video_auto_approve()`**

Runs every 15 minutes. Logic:
1. Get items with status="ready"
2. For each with approval_tier="auto", call svs.approve_item()
3. Manual items stay in "ready" for human review

- [ ] **Step 4: Add job function `_social_video_publish()`**

Runs every 5 minutes. Logic:
1. Get items with status="scheduled"
2. For each where scheduled_at <= now:
   - Check video_path exists
   - For each target platform, call appropriate publishing function:
     - instagram/facebook: use existing publishing_service.publish_video()
     - indeed: use get_indeed_client().post_video()
   - Collect post_urls
   - Update item: status="posted" (or "failed"), posted_at=now, post_urls=JSON

- [ ] **Step 5: Register the 3 jobs**

Add scheduler.add_job calls:
- `social_video_generate`: interval 4 hours, id="social_video_generate"
- `social_video_auto_approve`: interval 15 minutes, id="social_video_auto_approve"
- `social_video_publish`: interval 5 minutes, id="social_video_publish"

All with `replace_existing=True`.

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(social-video): add 3 agent loop jobs — content gen, auto-approve, publish"
```

---

### Task 8: Media Studio UI — Social Video Tab

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Context:** Media Studio uses tabbed LCARS interface. Uses `switchMediaTab()` for tab switching. Uses `escHtml()` or `setHtml()` for safe rendering. All rendering MUST use safe DOM methods — no raw innerHTML with untrusted data.

- [ ] **Step 1: Read the existing template**

Read the template to understand: tab button HTML pattern, tab panel pattern, JS function patterns (especially `switchMediaTab`, `showNotification`, existing fetch/api patterns).

- [ ] **Step 2: Add Social Video tab button**

In the tab bar, add after existing tabs:
```html
<button class="ms-tab" data-tab="social-video" onclick="switchMediaTab('social-video')">Social Video</button>
```

- [ ] **Step 3: Add Social Video tab panel**

Create `<div class="ms-tab-panel" id="tab-social-video" style="display:none;">` with:

**Stats bar:** 4 stat boxes (daily budget, monthly budget, posted this week, awaiting review) using class prefix `sv-` to avoid conflicts.

**Create form:** Content type dropdown, agent picker (shown only for agent_moment), template dropdown (populates from API), prompt textarea, caption textarea, platform checkboxes (instagram, facebook, indeed), quality dropdown (draft/standard/high), Generate button.

**Queue section:** Filter buttons (All, Ready, Approved, Scheduled, Posted, Generating), queue list container.

- [ ] **Step 4: Add Social Video CSS**

LCARS-themed styles with `sv-` prefix:
- Stats bar: flex row, Orbitron font for values, cyan accent
- Form: dark inputs with cyan borders, IBM Plex Mono
- Buttons: cyan primary, green approve, red reject, purple schedule
- Queue items: dark cards with status-colored badges per content type (pink=agent_moment, yellow=motivational, purple=employer_branding, green=recruitment)
- Responsive at 480px/768px breakpoints

- [ ] **Step 5: Add Social Video JavaScript**

All functions prefixed with `sv` to avoid conflicts:

- `svLoadStats()` — fetch `/api/social-video/stats`, update stat elements using textContent (NOT innerHTML)
- `svLoadTemplates()` — fetch templates for selected content type, populate dropdown using DOM createElement
- `svPreviewTemplate()` — POST render template, fill prompt/caption textareas
- `svGenerate()` — collect form data, POST to `/api/social-video/generate`, show notification, reload queue
- `svLoadQueue()` — fetch queue with current filter, render items using DOM methods (createElement, textContent, appendChild — NOT innerHTML with interpolated data). Each item shows: content_type badge, status badge, agent name, date, truncated prompt, caption, platforms, action buttons
- `svFilterQueue(btn, status)` — toggle active filter, reload queue
- `svApprove(id)` — POST approve, notification, reload
- `svReject(id)` — prompt for reason, POST reject, notification, reload
- `svSchedule(id)` — prompt for datetime, POST schedule, notification, reload
- `initSocialVideo()` — called on tab switch, loads stats + templates + queue

Wire into `switchMediaTab()`:
```javascript
if (tabId === 'social-video') initSocialVideo();
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(social-video): add Social Video tab to Media Studio UI"
```

---

### Task 9: Deploy and Verify

- [ ] **Step 1: Run database migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/306_social_content_queue.sql
```

- [ ] **Step 2: Create video output directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/static/social_videos
```

- [ ] **Step 3: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 4: Check logs for import errors**

```bash
docker logs --tail 50 archie_platform 2>&1 | grep -iE "error|social_video|import"
```

Expected: No errors. 3 new jobs registered.

- [ ] **Step 5: Test API endpoints**

```bash
curl -sb http://192.168.1.200:3000/tools/media-studio/api/social-video/stats
curl -sb http://192.168.1.200:3000/tools/media-studio/api/social-video/templates
curl -sb http://192.168.1.200:3000/tools/media-studio/api/social-video/queue
```

Expected: 200 OK, 8 templates, empty queue.

- [ ] **Step 6: Test draft generation (local ComfyUI)**

```bash
curl -sX POST http://192.168.1.200:3000/tools/media-studio/api/social-video/generate \
  -H "Content-Type: application/json" \
  -d '{"content_type":"motivational","prompt":"Cinematic sunrise over mountains, golden light","quality":"draft"}'
```

Expected: Queue item created, status "generating".

- [ ] **Step 7: Browser test**

Navigate to `http://192.168.1.200:3000/tools/media-studio`, click Social Video tab:
- Stats bar shows budget numbers
- Templates populate on content type change
- Queue shows test item
- LCARS styling is consistent

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "feat(social-video): Social Video Engine v1 — complete pipeline deployed and verified"
```
