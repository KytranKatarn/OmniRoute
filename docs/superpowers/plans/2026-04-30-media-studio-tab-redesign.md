# Media Studio Tab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign Gallery, Dashboard, Generate, and Social Video tabs into a cohesive production studio — persistent state, DHQ roster-driven agent pickers, per-subject media kits, and an AutoShorts social video pipeline.

**Architecture:** Split the 5000-line monolithic template into per-tab includes + per-tab JS files. New shared backend APIs (`/api/agents/picker`, `/api/agents/gallery-subjects`) feed all agent pickers from DHQ live. Each tab ships independently after Task 1.

**Tech Stack:** Flask/Jinja2, vanilla JS, PostgreSQL, LCARS CSS, existing ComfyUI/DHQ/KBS/S.I.G.N.A.L. infrastructure.

---

## Task 1: Template Split — Extract tabs to include files

**Files:**
- Create: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_dashboard.html`
- Create: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_generate.html`
- Create: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_gallery.html`
- Create: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_social_video.html`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

- [ ] **Step 1: Extract each tab pane to its own include file**

Dashboard tab is at line 299, Generate at 386, Gallery at 647, Social Video at 1169 of `media_studio.html`. Cut each `<div id="ms-tab-X" ...>...</div>` block into its own file.

```bash
# Verify line numbers first
grep -n 'id="ms-tab-' platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
```

- [ ] **Step 2: Replace extracted blocks with Jinja2 includes**

In `media_studio.html`, where each tab block was:

```html
{% include 'tools/media_studio/_tab_dashboard.html' %}
{% include 'tools/media_studio/_tab_generate.html' %}
{% include 'tools/media_studio/_tab_gallery.html' %}
<!-- portraits and queue stay inline — not being redesigned -->
{% include 'tools/media_studio/_tab_social_video.html' %}
```

- [ ] **Step 3: Verify no regression**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/media-studio` — all 6 tabs render identically. Check browser console for errors.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/templates/
git commit -m "refactor(media-studio): split monolithic template into per-tab includes"
```

---

## Task 2: Shared Backend — Agent Picker + Gallery Subjects APIs

**Files:**
- Create: `platform_v2/tools/media_studio/services/roster_service.py`
- Modify: `platform_v2/tools/media_studio/routes.py`

- [ ] **Step 1: Create `roster_service.py`**

```python
# platform_v2/tools/media_studio/services/roster_service.py
from typing import Dict
from database import get_db_cursor


def get_agent_picker() -> Dict:
    """Returns grouped agent list for Generate tab. Pulls live from DHQ — new agents auto-appear."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT a.id, a.name, a.display_name, a.department, a.worker_type,
                   ap.canonical_image_path,
                   COUNT(ml.id) AS asset_count
            FROM agents a
            LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
            LEFT JOIN media_library ml ON ml.owner_id = a.id
                AND ml.owner_type = 'agent' AND ml.is_deleted = false
            WHERE a.shift_state != 'decommissioned' AND a.worker_type IN ('internal', 'ai')
            GROUP BY a.id, a.name, a.display_name, a.department, a.worker_type,
                     ap.canonical_image_path
            ORDER BY a.worker_type DESC, a.name
        """)
        rows = cur.fetchall()

    humans, ai_agents = [], []
    for row in rows:
        d = dict(row)
        d["avatar_thumb_url"] = d.pop("canonical_image_path", None) or ""
        if d["worker_type"] == "internal":
            humans.append(d)
        else:
            ai_agents.append(d)
    return {"humans": humans, "ai_agents": ai_agents}


def get_gallery_subjects() -> Dict:
    """Returns sidebar subject list for Gallery tab with asset counts per agent."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT a.id, a.name, a.display_name, a.department, a.worker_type,
                   ap.canonical_image_path,
                   COUNT(ml.id) AS asset_count
            FROM agents a
            LEFT JOIN agent_portraits ap ON ap.agent_id = a.id
            LEFT JOIN media_library ml ON ml.owner_id = a.id
                AND ml.owner_type = 'agent' AND ml.is_deleted = false
            WHERE a.shift_state != 'decommissioned' AND a.worker_type IN ('internal', 'ai')
            GROUP BY a.id, a.name, a.display_name, a.department, a.worker_type,
                     ap.canonical_image_path
            ORDER BY a.worker_type DESC, a.name
        """)
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS cnt FROM media_library WHERE owner_type='brand' AND is_deleted=false")
        brand_count = cur.fetchone()["cnt"]

    humans, ai_agents = [], []
    for row in rows:
        d = dict(row)
        d["avatar_thumb_url"] = d.pop("canonical_image_path", None) or ""
        if d["worker_type"] == "internal":
            humans.append(d)
        else:
            ai_agents.append(d)
    return {
        "humans": humans,
        "ai_agents": ai_agents,
        "brand": {"name": "Kytran Empowerment", "asset_count": brand_count},
    }
```

- [ ] **Step 2: Add 4 new routes to `routes.py` (after the `api_dashboard` route ~line 44)**

```python
@media_studio_bp.route("/api/agents/picker")
@login_required
def api_agents_picker():
    from .services.roster_service import get_agent_picker
    return jsonify(get_agent_picker())


@media_studio_bp.route("/api/agents/gallery-subjects")
@login_required
def api_gallery_subjects():
    from .services.roster_service import get_gallery_subjects
    return jsonify(get_gallery_subjects())


@media_studio_bp.route("/api/gallery/<int:media_id>/asset-type", methods=["PUT"])
@login_required
def api_set_asset_type(media_id):
    import psycopg2.extras
    from database import get_db_cursor
    data = request.get_json() or {}
    asset_type = data.get("asset_type", "")
    if asset_type not in ("headshot", "lifestyle", "social", "brand", "portrait"):
        return jsonify({"error": "invalid asset_type"}), 400
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_library SET metadata = metadata || %s WHERE id = %s AND is_deleted = false",
            (psycopg2.extras.Json({"asset_type": asset_type}), media_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
    return jsonify({"asset_type": asset_type})


@media_studio_bp.route("/api/gallery/<int:media_id>/featured", methods=["PUT"])
@login_required
def api_set_featured(media_id):
    import psycopg2.extras
    from database import get_db_cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT owner_type, owner_id FROM media_library WHERE id = %s AND is_deleted = false",
            (media_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        cur.execute(
            "UPDATE media_library SET metadata = metadata - 'featured' "
            "WHERE owner_type = %s AND owner_id = %s AND is_deleted = false",
            (row["owner_type"], row["owner_id"]),
        )
        cur.execute(
            "UPDATE media_library SET metadata = metadata || %s WHERE id = %s",
            (psycopg2.extras.Json({"featured": True}), media_id),
        )
    return jsonify({"featured": True})


@media_studio_bp.route("/api/portraits/<int:agent_id>/identity")
@login_required
def api_portrait_identity(agent_id):
    """Returns identity_prompt for an agent — used by Generate tab pre-fill."""
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT ap.identity_prompt, a.display_name, a.name "
            "FROM agents a LEFT JOIN agent_portraits ap ON ap.agent_id = a.id "
            "WHERE a.id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "identity_prompt": row["identity_prompt"] or "",
        "agent_name": row["display_name"] or row["name"],
    })
```

- [ ] **Step 3: Test the new endpoints**

```bash
docker compose restart archie_platform
```

In browser console on Media Studio page:
```js
fetch('/tools/media-studio/api/agents/picker').then(r=>r.json()).then(d=>console.log('humans:', d.humans.length, 'ai:', d.ai_agents.length))
// Expected: humans: N ai: M  (non-zero counts)
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/services/roster_service.py platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): agent picker + gallery subjects + identity APIs from DHQ roster"
```

---

## Task 3: Dashboard API Extension

**Files:**
- Modify: `platform_v2/tools/media_studio/services/generation_service.py`

- [ ] **Step 1: Add `pending_approvals` and `social_queue` to `get_dashboard_stats`**

In `get_dashboard_stats`, after the `active_jobs` query, add:

```python
        # Portraits completed but not yet approved
        cur.execute("""
            SELECT a.id AS agent_id, a.name, a.display_name,
                   ap.canonical_image_path, ap.id AS portrait_id,
                   ml.created_at
            FROM agent_portraits ap
            JOIN agents a ON a.id = ap.agent_id
            LEFT JOIN media_library ml ON ml.id = ap.result_media_id
            WHERE ap.canonical_image_path IS NOT NULL AND ap.is_approved = false
            ORDER BY ml.created_at DESC LIMIT 5
        """)
        counts["pending_approvals"] = [dict(r) for r in cur.fetchall()]
        for item in counts["pending_approvals"]:
            if hasattr(item.get("created_at"), "isoformat"):
                item["created_at"] = item["created_at"].isoformat()

        # Social video queue items
        try:
            cur.execute(
                "SELECT id, title, status, platform, scheduled_at, thumbnail_path "
                "FROM social_video_queue WHERE status IN ('draft','scheduled') "
                "ORDER BY scheduled_at ASC NULLS LAST LIMIT 5"
            )
            raw = cur.fetchall()
        except Exception:
            raw = []
        sq = []
        for r in raw:
            d = dict(r)
            if hasattr(d.get("scheduled_at"), "isoformat"):
                d["scheduled_at"] = d["scheduled_at"].isoformat()
            sq.append(d)
        counts["social_queue"] = sq
```

- [ ] **Step 2: Verify**

```bash
docker compose restart archie_platform
```
```js
fetch('/tools/media-studio/api/dashboard').then(r=>r.json()).then(d=>console.log(Object.keys(d)))
// Expected: keys include 'pending_approvals' and 'social_queue'
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/media_studio/services/generation_service.py
git commit -m "feat(media-studio): dashboard API adds pending_approvals + social_queue"
```

---

## Task 4: Dashboard Tab Rewrite

**Files:**
- Create: `platform_v2/tools/media_studio/static/js/ms-dashboard.js`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_dashboard.html`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

- [ ] **Step 1: Create `static/js/ms-dashboard.js`**

The dashboard JS module — 15s auto-refresh, renders 3 live columns + recent grid.

Key functions:
- `msDashboard.start()` — loads data and starts 15s interval
- `msDashboard.stop()` — clears interval on tab switch
- `msDashboard.load()` — fetches `/api/dashboard`, updates all sections
- `msDashboard._renderGenerating(jobs)` — populates `msDashGeneratingList`
- `msDashboard._renderApprovals(items)` — populates `msDashApprovalList` with inline approve buttons
- `msDashboard._renderSocialQueue(items)` — populates `msDashSocialList`
- `msDashboard._renderRecent(items)` — populates `msDashRecentGrid` (6 thumbnails)
- `msDashboard._approve(portraitId)` — calls `POST /api/portraits/<id>/approve`, reloads

Each render function sets element content using `createElement`/`appendChild` (no unsafe HTML injection).

Full implementation file: `platform_v2/tools/media_studio/static/js/ms-dashboard.js`
See spec for complete code — implement exactly these functions with the element IDs below.

- [ ] **Step 2: Rewrite `_tab_dashboard.html` with 5-stat row + 3-column ops panel + recent grid**

Element IDs required (used by `ms-dashboard.js`):
- `msDashStatGenerating`, `msDashStatApprovals`, `msDashStatSocial`, `msDashStatTotal`, `msDashStatFailed` — stat value spans
- `msDashGeneratingList` — active jobs list container
- `msDashApprovalList` — pending approval cards container
- `msDashSocialList` — social queue items container
- `msDashRecentGrid` — 6-image recent completions grid

Layout: cyan `#00ffff` LCARS frame (copy sidebar pattern from existing dashboard tab), then inside:
1. Row of 5 `.ms-stat-card` divs
2. 3-column grid (generating / approvals / social), each with colored border and section header
3. Recent completions section with 6-image grid

- [ ] **Step 3: Wire tab switch**

In `switchMsTab` in `media_studio.html`, replace `loadDashboard()` with:

```javascript
if (tabId === "dashboard") {
    if (window.msDashboard) msDashboard.start();
} else {
    if (window.msDashboard) msDashboard.stop();
}
```

Add script tag: `<script src="{{ url_for('media_studio_bp.static', filename='js/ms-dashboard.js') }}"></script>`

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Dashboard tab should show:
- Stats: Generating=4 (if queue active), Needs Approval=N, queue numbers
- Generating Now column: lists A.C.C.O.R.D., R.E.T.I.N.A., etc.
- Needs Approval: shows completed portraits with ✓/✕ buttons
- Recent Completions: 6 thumbnail grid of latest generated images

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/static/js/ms-dashboard.js \
        platform_v2/tools/media_studio/templates/tools/media_studio/_tab_dashboard.html \
        platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): Dashboard tab — production overview with live ops panel"
```

---

## Task 5: Gallery Tab Rewrite

**Files:**
- Create: `platform_v2/tools/media_studio/static/js/ms-gallery.js`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_gallery.html`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

- [ ] **Step 1: Create `static/js/ms-gallery.js`**

Key functions:
- `msGallery.init()` — restores persisted subject from `sessionStorage`, calls `loadSubjects()`
- `msGallery.loadSubjects()` — fetches `/api/agents/gallery-subjects`, calls `_renderSidebar(data)`
- `msGallery.selectSubject(type, id)` — saves to `sessionStorage('ms_gallery_subject')`, updates URL hash `#gallery/agent/13`, calls `loadAssets()`
- `msGallery._renderSidebar(data)` — builds Human Agents / AI Agents / Brand sections with `.ms-gallery-subject-item` divs from `createElement`
- `msGallery.loadAssets()` — fetches `/api/gallery?owner_type=agent&owner_id=X&per_page=50`, calls `_renderGrid(items)`
- `msGallery._renderSubjectHeader(agent)` — renders avatar + name + dept + "+ Generate" button into `msGallerySubjectHeader`
- `msGallery._renderGrid(items)` — renders `.ms-gallery-subject-card` divs into `msGallerySubjectGrid`; featured items get ★ badge; click → `showMediaDetail(item.id)`
- `msGallery.setFilter(filter)` — sets `_assetFilter`, updates `.ms-gallery-type-tab.active`, reloads assets

"+ Generate" button calls `msGenerate.preselectAgent(agentId)` then `switchMsTab('generate')`.

- [ ] **Step 2: Rewrite `_tab_gallery.html`**

Layout: green `#22c55e` LCARS frame. Inside: flex row with:
- Left sidebar (200px): `<div id="msGallerySidebarSubjects">` — populated by JS
- Right content area: `<div id="msGallerySubjectHeader">` + asset type filter row + `<div id="msGallerySubjectGrid" class="ms-gallery-subject-grid">`

Asset type filter tabs (button elements with class `ms-gallery-type-tab`):
```html
<button class="ms-gallery-type-tab active" data-filter="all" onclick="msGallery.setFilter('all')">All</button>
<button class="ms-gallery-type-tab" data-filter="headshot" onclick="msGallery.setFilter('headshot')">Headshots</button>
<button class="ms-gallery-type-tab" data-filter="lifestyle" onclick="msGallery.setFilter('lifestyle')">Lifestyle</button>
<button class="ms-gallery-type-tab" data-filter="social" onclick="msGallery.setFilter('social')">Social</button>
<button class="ms-gallery-type-tab" data-filter="portrait" onclick="msGallery.setFilter('portrait')">Portraits</button>
```

- [ ] **Step 3: Add CSS classes to `media_studio.html` style block**

```css
.ms-gallery-subject-item { display:flex;align-items:center;gap:7px;padding:5px 7px;border-radius:4px;cursor:pointer;margin-bottom:2px; }
.ms-gallery-subject-item:hover { background:rgba(34,197,94,0.08); }
.ms-gallery-subject-active { background:rgba(34,197,94,0.12)!important;border:1px solid rgba(34,197,94,0.25); }
.ms-gallery-subject-avatar { width:22px;height:22px;border-radius:50%;background:#1a2a3a;flex-shrink:0;overflow:hidden; }
.ms-gallery-subject-name { color:#aaa;font-size:0.65rem;flex:1; }
.ms-gallery-subject-active .ms-gallery-subject-name { color:#22c55e; }
.ms-gallery-subject-count { color:#555;font-size:0.58rem; }
.ms-gallery-sidebar-section-label { font-family:'Antonio',sans-serif;font-size:0.55rem;letter-spacing:2px;color:#555;text-transform:uppercase;margin:10px 0 5px; }
.ms-gallery-subject-grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px; }
.ms-gallery-subject-card { cursor:pointer;border-radius:5px;overflow:hidden;border:1px solid #1a1a2e;background:#0d1117; }
.ms-gallery-subject-card:hover { border-color:rgba(34,197,94,0.4); }
.ms-gallery-subject-thumb { aspect-ratio:1;background:#1a2a3a;position:relative;overflow:hidden; }
.ms-gallery-subject-thumb img { width:100%;height:100%;object-fit:cover; }
.ms-gallery-subject-star { position:absolute;top:3px;right:3px;background:#22c55e;color:#000;font-size:0.55rem;padding:1px 4px;border-radius:3px; }
.ms-gallery-subject-prompt { padding:4px 6px;font-size:0.58rem;color:#666;white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
.ms-gallery-type-tab { background:transparent;border:1px solid #333;color:#666;padding:3px 10px;border-radius:4px;font-size:0.62rem;font-family:'Antonio',sans-serif;letter-spacing:1px;cursor:pointer; }
.ms-gallery-type-tab.active { background:rgba(34,197,94,0.12);border-color:rgba(34,197,94,0.4);color:#22c55e; }
```

- [ ] **Step 4: Wire tab switch**

In `switchMsTab`, replace old gallery logic with:

```javascript
else if (tabId === "gallery") {
    if (window.msGallery) msGallery.init();
}
```

Remove old: `loadGallery(1); loadGalleryFacets(); loadCollections();`

Add script tag: `<script src="{{ url_for('media_studio_bp.static', filename='js/ms-gallery.js') }}"></script>`

- [ ] **Step 5: Deploy and verify**

```bash
docker compose restart archie_platform
```

Gallery tab should show:
- Left sidebar: Human Agents / AI Agents / Brand sections populated from DHQ
- First human agent auto-selected with their assets in right grid
- Switching to another tab and back: sidebar still shows same agent selected
- "+ Generate" button in subject header switches to Generate tab

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/media_studio/static/js/ms-gallery.js \
        platform_v2/tools/media_studio/templates/tools/media_studio/_tab_gallery.html \
        platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): Gallery tab — per-subject media kit with persistent state"
```

---

## Task 6: Generate Tab Rewrite

**Files:**
- Create: `platform_v2/tools/media_studio/static/js/ms-generate.js`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_generate.html`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

- [ ] **Step 1: Create `static/js/ms-generate.js`**

Key functions:
- `msGenerate.init()` — loads agent picker from `/api/agents/picker`, populates `msGenAgentPicker`; loads models into `msGenModel`
- `msGenerate.preselectAgent(agentId)` — called by Gallery's "+ Generate" button; stores `_agentId`, triggers `selectAgent()` after init
- `msGenerate.selectType(type)` — updates `.ms-gen-type-card.ms-gen-type-active`; "social" type calls `switchMsTab('social-video')` and returns early; shows `msGenStep2`
- `msGenerate.selectAgent(agentId)` — updates `.ms-gen-agent-pill.ms-gen-agent-active`; fetches `/api/portraits/<id>/identity`; sets `msGenPrompt.value` and `msGenPromptPrefill.textContent`; shows `msGenStep3`
- `msGenerate.submit()` — validates prompt, calls `POST /api/generate` with payload `{prompt, media_type:'image', model, width:1024, height:1024, steps:30, seed:-1}`; shows inline status in `msGenStatus`; on success switches to queue tab after 1200ms

- [ ] **Step 2: Rewrite `_tab_generate.html`**

Layout: blue `#3b82f6` LCARS frame. Inside (max-width 700px):

**Step 1 section** — 3 type cards (grid-template-columns: 1fr 1fr 1fr):
- Portrait card (`data-type="portrait"`, `onclick="msGenerate.selectType('portrait')"`) — active by default
- Brand Asset card (`data-type="brand"`)
- Social Content card (`data-type="social"`) — note: routes to Social Video tab

**Step 2 section** (`id="msGenStep2"`) — agent pills container `id="msGenAgentPicker"` (populated by JS)

**Step 3 section** (`id="msGenStep3"`, `display:none` initially) — prompt textarea `id="msGenPrompt"`, prefill hint `id="msGenPromptPrefill"`, negative prompt (collapsible details), advanced options (collapsible details with model select `id="msGenModel"`), Generate button `id="msGenBtn"` calling `msGenerate.submit()`, status div `id="msGenStatus"`

CSS classes needed:
```css
.ms-gen-type-card { background:#0d1117;border:1px solid #1a2a3a;border-radius:8px;padding:16px 12px;cursor:pointer;text-align:center;transition:border-color .15s,background .15s; }
.ms-gen-type-card:hover { border-color:rgba(59,130,246,0.4); }
.ms-gen-type-active { background:rgba(59,130,246,0.08)!important;border-color:rgba(59,130,246,0.5)!important; }
.ms-gen-agent-pill { background:transparent;border:1px solid #333;color:#888;padding:5px 12px;border-radius:20px;font-size:0.65rem;cursor:pointer;font-family:'Antonio',sans-serif;letter-spacing:1px; }
.ms-gen-agent-pill:hover { border-color:rgba(59,130,246,0.4);color:#60a5fa; }
.ms-gen-agent-active { background:rgba(59,130,246,0.12)!important;border-color:rgba(59,130,246,0.5)!important;color:#60a5fa!important; }
```

- [ ] **Step 3: Wire tab switch and add script tag**

In `switchMsTab`:
```javascript
else if (tabId === "generate") {
    if (window.msGenerate) msGenerate.init();
}
```

Add: `<script src="{{ url_for('media_studio_bp.static', filename='js/ms-generate.js') }}"></script>`

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Generate tab should:
- Show 3 type cards, Portrait active by default
- Agent pills appear immediately (loaded from DHQ)
- Selecting an agent pre-fills prompt from their identity
- "Social Content" card switches to Social Video tab
- Generate button: inline "Queuing via P.I.X.E.L. → Department HQ…" then "✓ Queued #N" then switches to Queue tab

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/static/js/ms-generate.js \
        platform_v2/tools/media_studio/templates/tools/media_studio/_tab_generate.html \
        platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): Generate tab — type-first 3-step flow with DHQ agent picker"
```

---

## Task 7: Social Video Backend

**Files:**
- Create: `platform_v2/tools/media_studio/services/social_video_service.py`
- Create: `database/migrations/342_social_video_queue.sql`
- Modify: `platform_v2/tools/media_studio/routes.py`

- [ ] **Step 1: Create migration**

File: `database/migrations/342_social_video_queue.sql`

```sql
CREATE TABLE IF NOT EXISTS social_video_queue (
    id SERIAL PRIMARY KEY,
    title TEXT,
    quote_text TEXT,
    audio_mode VARCHAR(20) DEFAULT 'music',
    platform VARCHAR(50) DEFAULT 'linkedin',
    status VARCHAR(20) DEFAULT 'draft',
    scheduled_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,
    thumbnail_path TEXT,
    media_ids INTEGER[],
    metadata JSONB DEFAULT '{}',
    created_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_svq_status ON social_video_queue(status);
CREATE INDEX IF NOT EXISTS idx_svq_scheduled ON social_video_queue(scheduled_at);
```

Run: `docker exec -i archie_database psql -U archie -d archie < database/migrations/342_social_video_queue.sql`

- [ ] **Step 2: Create `social_video_service.py`**

```python
# platform_v2/tools/media_studio/services/social_video_service.py
import psycopg2.extras
from typing import Dict, List, Optional
from database import get_db_cursor


def list_queue(status: Optional[str] = None, limit: int = 20) -> List[Dict]:
    with get_db_cursor() as (conn, cur):
        if status:
            cur.execute(
                "SELECT * FROM social_video_queue WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM social_video_queue ORDER BY created_at DESC LIMIT %s", (limit,)
            )
        rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        result.append(d)
    return result


def create_item(
    title: str, quote_text: str, media_ids: List[int],
    audio_mode: str, platform: str, scheduled_at: Optional[str], user_id: int,
) -> Dict:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO social_video_queue
               (title, quote_text, media_ids, audio_mode, platform, scheduled_at, status, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, status, created_at""",
            (title, quote_text, psycopg2.extras.Json(media_ids), audio_mode, platform,
             scheduled_at, "scheduled" if scheduled_at else "draft", user_id),
        )
        row = cur.fetchone()
    d = dict(row)
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    return d


def update_status(item_id: int, status: str) -> bool:
    if status not in ("draft", "scheduled", "pending_approval", "posted"):
        return False
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("UPDATE social_video_queue SET status = %s WHERE id = %s", (status, item_id))
        return cur.rowcount > 0
```

- [ ] **Step 3: Add social video routes to `routes.py`**

```python
@media_studio_bp.route("/api/social-video/queue")
@login_required
def api_sv_queue():
    from .services.social_video_service import list_queue
    return jsonify({"items": list_queue(status=request.args.get("status") or None)})


@media_studio_bp.route("/api/social-video/queue", methods=["POST"])
@login_required
def api_sv_create():
    from .services.social_video_service import create_item
    data = request.get_json() or {}
    if not data.get("quote_text") and not data.get("title"):
        return jsonify({"error": "title or quote_text required"}), 400
    item = create_item(
        title=data.get("title", "Untitled"),
        quote_text=data.get("quote_text", ""),
        media_ids=data.get("media_ids", []),
        audio_mode=data.get("audio_mode", "music"),
        platform=data.get("platform", "linkedin"),
        scheduled_at=data.get("scheduled_at"),
        user_id=current_user.id,
    )
    return jsonify(item), 201


@media_studio_bp.route("/api/social-video/queue/<int:item_id>/status", methods=["PUT"])
@login_required
def api_sv_update_status(item_id):
    from .services.social_video_service import update_status
    data = request.get_json() or {}
    ok = update_status(item_id, data.get("status", ""))
    if not ok:
        return jsonify({"error": "invalid status or not found"}), 400
    return jsonify({"status": data.get("status")})
```

- [ ] **Step 4: Test**

```bash
docker compose restart archie_platform
```

```js
// Create a draft item
fetch('/tools/media-studio/api/social-video/queue', {
  method: 'POST', headers: {'Content-Type':'application/json'},
  body: JSON.stringify({title: 'Test', quote_text: 'Hello world', media_ids: [], audio_mode: 'music', platform: 'linkedin'})
}).then(r=>r.json()).then(d=>console.log(d))
// Expected: {id: 1, status: 'draft', created_at: '...'}

fetch('/tools/media-studio/api/social-video/queue').then(r=>r.json()).then(d=>console.log(d.items.length))
// Expected: 1
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/services/social_video_service.py \
        platform_v2/tools/media_studio/routes.py \
        database/migrations/342_social_video_queue.sql
git commit -m "feat(media-studio): social video queue backend — CRUD + status updates"
```

---

## Task 8: Social Video Tab Rewrite

**Files:**
- Create: `platform_v2/tools/media_studio/static/js/ms-social-video.js`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/_tab_social_video.html`
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

- [ ] **Step 1: Create `static/js/ms-social-video.js`**

Key functions:
- `msSocialVideo.init()` — loads queue + image picker
- `msSocialVideo.switchImageSource(source)` — 'gallery' or 'portraits'; updates `.ms-sv-source-tab.active`; calls `loadImageSource()`
- `msSocialVideo.loadImageSource()` — fetches `/api/gallery?owner_type=agent&per_page=30`; calls `_renderImagePicker(items)`
- `msSocialVideo.toggleImage(id, el)` — adds/removes from `_selectedImages[]`; updates order badges; calls `_renderSelectedStrip()`
- `msSocialVideo.queueForPosting()` — posts to `/api/social-video/queue`; shows status in `msSvStatus`; reloads queue panel
- `msSocialVideo.loadQueue()` — fetches `/api/social-video/queue?status=<filter>`; calls `_renderQueue(items)`
- `msSocialVideo.filterQueue(status, el)` — updates `.ms-sv-queue-filter.active`; reloads queue
- `msSocialVideo.selectAudio(mode, el)` — updates `.ms-sv-audio-btn.active`

- [ ] **Step 2: Rewrite `_tab_social_video.html`**

Layout: purple `#8b5cf6` LCARS frame. Inside: flex row with:

**Left: Builder** (flex:1, padding 16px, border-right):
- Header: "BUILD NEW VIDEO" label
- Step 1 (Quote): text input `id="msSvTitle"` + textarea `id="msSvQuote"`
- Step 2 (Images): source tabs (Gallery/Portraits with class `ms-sv-source-tab`), selected strip `id="msSvSelectedStrip"`, picker grid `id="msSvImagePickerGrid"`
- Step 3 (Audio): 3 buttons with class `ms-sv-audio-btn` and `data-mode`
- Step 4 (Post): platform select `id="msSvPlatform"`, datetime input `id="msSvScheduled"`, posting path note "S.I.G.N.A.L. → KBS → Kytran's LinkedIn"
- Action: "📤 QUEUE FOR POSTING" button + status div `id="msSvStatus"`

**Right: Queue panel** (width 260px):
- Filter tabs with class `ms-sv-queue-filter` (All/Draft/Scheduled/Posted)
- Queue list `id="msSvQueueList"`

CSS needed:
```css
.ms-sv-pick-thumb { aspect-ratio:1;background:#1a2a3a;border-radius:4px;border:2px solid transparent;cursor:pointer;position:relative;overflow:hidden; }
.ms-sv-pick-thumb img { width:100%;height:100%;object-fit:cover; }
.ms-sv-pick-thumb.selected { border-color:#8b5cf6; }
.ms-sv-pick-order { position:absolute;bottom:2px;right:2px;background:#8b5cf6;color:#fff;font-size:0.5rem;padding:1px 4px;border-radius:2px;min-width:14px;text-align:center; }
.ms-sv-source-tab.active { background:rgba(139,92,246,0.15)!important;border-color:rgba(139,92,246,0.5)!important;color:#a78bfa!important; }
.ms-sv-audio-btn.active { background:rgba(139,92,246,0.15);border-color:rgba(139,92,246,0.5);color:#a78bfa; }
.ms-sv-queue-filter.active { background:rgba(139,92,246,0.12);border-color:rgba(139,92,246,0.4);color:#a78bfa; }
```

- [ ] **Step 3: Wire tab switch and script tag**

In `switchMsTab`:
```javascript
else if (tabId === "social-video") {
    if (window.msSocialVideo) msSocialVideo.init();
}
```

Add: `<script src="{{ url_for('media_studio_bp.static', filename='js/ms-social-video.js') }}"></script>`

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
```

Social Video tab should show:
- Builder: quote textarea, image grid loads gallery thumbnails, audio buttons, LinkedIn platform
- Creating a video item: fill quote, click "Queue for Posting" → item appears in right panel as Draft
- Queue panel: filter tabs work, items show status badges

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/static/js/ms-social-video.js \
        platform_v2/tools/media_studio/templates/tools/media_studio/_tab_social_video.html \
        platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): Social Video tab — AutoShorts builder + content queue"
```

---

## Self-Review

**Spec coverage:**
- ✅ Dashboard: 5 stats, 3-column ops panel (generating/approvals/social), recent grid, 15s refresh
- ✅ Gallery: DHQ roster sidebar auto-populated, Human/AI/Brand sections, persistent state via sessionStorage + URL hash
- ✅ Gallery: per-subject asset grid, type filter tabs, featured ★ badge, "+ Generate" context button
- ✅ Generate: 3 type cards, Social routes to Social Video tab, agent picker from DHQ, identity pre-fill
- ✅ Generate: advanced params collapsed, inline status messages (no alert())
- ✅ Social Video: Gallery + Portraits image sources (source tabs), 4-step builder
- ✅ Social Video: S.I.G.N.A.L. → KBS → Kytran LinkedIn posting path shown in UI
- ✅ Social Video: Draft/Scheduled/Posted queue panel with filters
- ✅ All agent pickers: live from DHQ, new agents appear automatically with no code changes
- ✅ `social_video_queue` table created in Task 7 before Task 3 references it (try/except guards)
- ✅ `GET /api/portraits/<id>/identity` added in Task 2 for Generate tab pre-fill
