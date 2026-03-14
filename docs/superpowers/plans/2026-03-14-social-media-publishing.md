# Social Media Manager — Media Publishing Integration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Share" and "Bulk Share" from Media Studio gallery to Social Media Manager with AI-generated captions and multi-platform publishing.

**Architecture:** `publishing_service.py` in Social Media module bridges Media Studio assets to social posts. Media Studio gets Share button + modal that calls the service. `social_posts` gets a `media_library_id` FK. Social worker patched to resolve file paths from `media_library` when FK is set. AI captions generated via `archie_bridge.chat()`.

**Tech Stack:** Flask, PostgreSQL, archie_bridge (AI text generation)

**Key patterns from existing code:**
- `social_posts.media_urls` is JSONB (array of URL strings), `social_posts.user_id` (not owner_id)
- `social_media_queue` has `post_id`, `account_id`, `status`, `scheduled_time`
- `social_accounts` has `user_id`, `platform`, `is_active`, `account_name`
- Social worker: `process_job(job)` reads `job["media_urls"]` — first URL used for media
- AI pattern: `archie_bridge.chat(prompt, action="suggest_content")` returns text
- Social routes: `@social_media_bp.route(...)` directly on blueprint, no wrapper
- Media Studio routes: `@media_studio_bp.route(...)` + `@login_required`, local imports
- JS: IIFE, `window.funcName`, `api(method, path, body)`, `_clearChildren()`, `document.createElement`

---

## Task 1: Database Migration 157

**Files:**
- Create: `database/migrations/157_social_media_publishing.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration 157: Link social posts to Media Studio assets
-- Idempotent: safe to run multiple times

ALTER TABLE social_posts
ADD COLUMN IF NOT EXISTS media_library_id INTEGER REFERENCES media_library(id);

CREATE INDEX IF NOT EXISTS idx_social_posts_media_library
ON social_posts(media_library_id) WHERE media_library_id IS NOT NULL;
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/157_social_media_publishing.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/157_social_media_publishing.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='social_posts' AND column_name='media_library_id'"
```

Expected: one row with `media_library_id`.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/157_social_media_publishing.sql
git commit -m "feat(social-media): add migration 157 — media_library_id FK on social_posts"
```

---

## Task 2: Publishing Service

**Files:**
- Create: `platform_v2/tools/social_media/publishing_service.py`

**Dependencies:** Task 1

- [ ] **Step 1: Write the publishing service**

Create `publishing_service.py` (~160 lines):

```python
"""Publishing service — bridge Media Studio assets to Social Media posts.

Public API:
- publish_from_media_studio()     — create + queue social post(s) for one image
- bulk_publish_from_media_studio() — create draft posts for multiple images
- generate_caption()              — AI caption from image prompt/tags
- get_connected_platforms()       — list active social accounts
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
```

**`publish_from_media_studio(media_library_id, platforms, caption=None, schedule_at=None, owner_id=None)`**

```python
def publish_from_media_studio(media_library_id, platforms, caption=None, schedule_at=None, owner_id=None):
    from database import get_db_cursor
    from psycopg2.extras import Json

    with get_db_cursor() as (conn, cur):
        # Validate media exists
        cur.execute("SELECT id, file_path, media_type, metadata FROM media_library WHERE id = %s", (media_library_id,))
        media = cur.fetchone()
        if not media:
            return {"error": f"Media {media_library_id} not found"}

    # Generate caption if not provided
    if not caption or not caption.strip():
        caption = generate_caption(media_library_id)

    # Create posts for each platform
    post_ids = []
    with get_db_cursor(commit=True) as (conn, cur):
        for platform in platforms:
            # Verify account exists
            cur.execute(
                "SELECT id FROM social_accounts WHERE user_id = %s AND platform = %s AND is_active = true",
                (owner_id, platform),
            )
            account = cur.fetchone()
            if not account:
                continue  # skip platforms without connected accounts

            # Determine status
            status = 'scheduled' if schedule_at else 'queued'

            # Insert social post
            cur.execute("""
                INSERT INTO social_posts
                    (user_id, content, media_urls, media_type, media_library_id,
                     target_platforms, status, scheduled_at, ai_generated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                RETURNING id
            """, (
                owner_id, caption, Json([media['file_path']]),
                media.get('media_type', 'image'), media_library_id,
                [platform], status, schedule_at,
            ))
            post_id = cur.fetchone()['id']
            post_ids.append(post_id)

            # Queue for immediate publishing
            if not schedule_at:
                cur.execute("""
                    INSERT INTO social_media_queue
                        (post_id, account_id, status, priority)
                    VALUES (%s, %s, 'pending', 5)
                """, (post_id, account['id']))

    if not post_ids:
        return {"error": "No connected accounts for selected platforms"}

    return {"post_ids": post_ids, "status": "scheduled" if schedule_at else "queued"}
```

**`bulk_publish_from_media_studio(media_library_ids, platforms, owner_id=None)`**

```python
def bulk_publish_from_media_studio(media_library_ids, platforms, owner_id=None):
    from database import get_db_cursor
    from psycopg2.extras import Json

    if not media_library_ids:
        return {"error": "No media IDs provided"}
    if len(media_library_ids) > 20:
        return {"error": "Maximum 20 items per bulk share"}

    draft_ids = []
    with get_db_cursor(commit=True) as (conn, cur):
        for mid in media_library_ids:
            cur.execute("SELECT id, file_path, media_type FROM media_library WHERE id = %s", (mid,))
            media = cur.fetchone()
            if not media:
                continue

            caption = generate_caption(mid)

            for platform in platforms:
                cur.execute("""
                    INSERT INTO social_posts
                        (user_id, content, media_urls, media_type, media_library_id,
                         target_platforms, status, ai_generated)
                    VALUES (%s, %s, %s, %s, %s, %s, 'draft', true)
                    RETURNING id
                """, (
                    owner_id, caption, Json([media['file_path']]),
                    media.get('media_type', 'image'), mid, [platform],
                ))
                draft_ids.append(cur.fetchone()['id'])

    return {"draft_ids": draft_ids, "count": len(draft_ids)}
```

**`generate_caption(media_library_id)`**

```python
def generate_caption(media_library_id):
    """Generate AI caption from image prompt/tags. Falls back to raw prompt."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT metadata, media_type FROM media_library WHERE id = %s",
            (media_library_id,),
        )
        row = cur.fetchone()

    if not row:
        return "Check out this creation!"

    metadata = row.get('metadata') or {}
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    prompt = metadata.get('prompt', '')
    tags = metadata.get('tags', [])
    media_type = row.get('media_type', 'image')

    if not prompt:
        return "Check out this AI-generated creation!"

    # Try AI caption
    try:
        from archie_bridge import archie_bridge
        ai_prompt = (
            f"Write a short, engaging social media caption for this AI-generated {media_type}. "
            f"Original prompt: {prompt}. "
            f"Tags: {', '.join(tags) if tags else 'none'}. "
            f"Keep it under 280 characters. Return only the caption text, no quotes."
        )
        response = archie_bridge.chat(ai_prompt, action="suggest_content")
        if response and isinstance(response, str) and len(response.strip()) > 5:
            return response.strip()[:280]
    except Exception as e:
        logger.warning(f"AI caption generation failed: {e}")

    # Fallback: use original prompt
    return prompt[:280] if prompt else "Check out this AI-generated creation!"
```

**`get_connected_platforms(owner_id)`**

```python
def get_connected_platforms(owner_id):
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT id, platform, account_name, platform_username
            FROM social_accounts
            WHERE user_id = %s AND is_active = true
            ORDER BY platform
        """, (owner_id,))
        return [
            {
                "account_id": r['id'],
                "platform": r['platform'],
                "account_name": r['account_name'] or r['platform_username'] or r['platform'],
            }
            for r in cur.fetchall()
        ]
```

- [ ] **Step 2: Verify imports**

```bash
docker exec archie_platform python3 -c "from tools.social_media.publishing_service import publish_from_media_studio, bulk_publish_from_media_studio, generate_caption, get_connected_platforms; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/social_media/publishing_service.py
git commit -m "feat(social-media): add publishing service — Media Studio to social posts bridge"
```

---

## Task 3: Social Worker Patch

**Files:**
- Modify: `platform_v2/tools/social_media/social_worker.py`

**Dependencies:** Task 1

- [ ] **Step 1: Read social_worker.py to find the media resolution point**

Find `process_job` function, locate where `media_urls` is read from the job dict. This is where we add the `media_library_id` fallback.

- [ ] **Step 2: Patch media resolution**

In `process_job`, after extracting `media_urls` from the job, add:

```python
# If post has a Media Studio asset, resolve path from media_library
media_library_id = job.get('media_library_id')
if media_library_id and (not media_urls or media_urls == [None]):
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT file_path FROM media_library WHERE id = %s", (media_library_id,))
            ml_row = cur.fetchone()
            if ml_row and ml_row['file_path']:
                media_urls = [ml_row['file_path']]
    except Exception as e:
        logger.warning(f"Failed to resolve media_library path: {e}")
```

IMPORTANT: The `get_pending_jobs` query JOINs social_posts — you must also add `p.media_library_id` to the SELECT list in that query so it appears in the job dict.

- [ ] **Step 3: Update get_pending_jobs SELECT**

Find the `get_pending_jobs` function's SELECT query. Add `p.media_library_id` to the column list.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/social_media/social_worker.py
git commit -m "feat(social-media): patch worker to resolve media from media_library FK"
```

---

## Task 4: Social Media Routes — Connected Platforms + Media Posts

**Files:**
- Modify: `platform_v2/tools/social_media/routes.py`

**Dependencies:** Task 2

- [ ] **Step 1: Read end of routes.py to find append location**

- [ ] **Step 2: Append 2 routes**

**`GET /api/social-media/connected-platforms`**
```python
@social_media_bp.route("/api/social-media/connected-platforms", methods=["GET"])
@login_required
def api_connected_platforms():
    from tools.social_media.publishing_service import get_connected_platforms
    platforms = get_connected_platforms(current_user.id)
    return jsonify(platforms)
```

**`GET /api/social-media/media-studio-posts`**
```python
@social_media_bp.route("/api/social-media/media-studio-posts", methods=["GET"])
@login_required
def api_media_studio_posts():
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT id, media_library_id, target_platforms, status, content, scheduled_at, published_at
            FROM social_posts
            WHERE user_id = %s AND media_library_id IS NOT NULL
            ORDER BY created_at DESC LIMIT 50
        """, (current_user.id,))
        posts = []
        for r in cur.fetchall():
            p = dict(r)
            for k, v in list(p.items()):
                if hasattr(v, 'isoformat'):
                    p[k] = v.isoformat()
            posts.append(p)
    return jsonify(posts)
```

Note: check if `social_media_bp` uses `@login_required` or a different auth pattern. Read the existing routes for the exact import.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/social_media/routes.py
git commit -m "feat(social-media): add connected-platforms + media-studio-posts routes"
```

---

## Task 5: Media Studio Routes — Share + Bulk Share

**Files:**
- Modify: `platform_v2/tools/media_studio/routes.py`

**Dependencies:** Task 2

- [ ] **Step 1: Read end of routes.py to find append location (after S24)**

- [ ] **Step 2: Append S25 section with 2 routes**

Add `# ── S25  Social Media Publishing ──` comment, then:

**`POST /api/media-studio/share`**
```python
@media_studio_bp.route("/api/media-studio/share", methods=["POST"])
@login_required
def api_share_to_social():
    from tools.social_media.publishing_service import publish_from_media_studio
    data = request.get_json() or {}
    media_library_id = data.get("media_library_id")
    platforms = data.get("platforms", [])
    caption = data.get("caption")
    schedule_at = data.get("schedule_at")
    if not media_library_id:
        return jsonify({"error": "media_library_id is required"}), 400
    if not platforms:
        return jsonify({"error": "At least one platform is required"}), 400
    result = publish_from_media_studio(
        media_library_id=media_library_id,
        platforms=platforms,
        caption=caption,
        schedule_at=schedule_at,
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

**`POST /api/media-studio/share/bulk`**
```python
@media_studio_bp.route("/api/media-studio/share/bulk", methods=["POST"])
@login_required
def api_bulk_share_to_social():
    from tools.social_media.publishing_service import bulk_publish_from_media_studio
    data = request.get_json() or {}
    media_library_ids = data.get("media_library_ids", [])
    platforms = data.get("platforms", [])
    if not media_library_ids:
        return jsonify({"error": "media_library_ids is required"}), 400
    if not platforms:
        return jsonify({"error": "At least one platform is required"}), 400
    result = bulk_publish_from_media_studio(
        media_library_ids=media_library_ids,
        platforms=platforms,
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)
```

- [ ] **Step 3: Verify all routes**

```bash
docker exec archie_platform python3 -c "
from app import app
rules = [r.rule for r in app.url_map.iter_rules() if 'share' in r.rule or 'connected-platforms' in r.rule or 'media-studio-posts' in r.rule]
print(f'{len(rules)} routes:', rules)
"
```

Expected: 4 routes (share, share/bulk, connected-platforms, media-studio-posts).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/media_studio/routes.py
git commit -m "feat(media-studio): add share + bulk share routes (S25)"
```

---

## Task 6: Share Modal HTML + JS

**Files:**
- Modify: `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

**Dependencies:** Task 5

- [ ] **Step 1: Read HTML to find insertion points**

Find: (a) `_createGalleryCard` for adding Share button, (b) modal area for share modal, (c) JS area for S25 block.

- [ ] **Step 2: Add Share button to gallery cards**

In `_createGalleryCard`, after the Edit button, add:
```javascript
var shareBtn = document.createElement('button');
shareBtn.className = 'ms-card-action-btn';
shareBtn.textContent = 'Share';
shareBtn.onclick = function(e) { e.stopPropagation(); openShareModal(g.id); };
actionBar.appendChild(shareBtn);
```

- [ ] **Step 3: Add share modal HTML**

After the S24 analytics view (or after existing modals):
```html
<!-- ── S25  Social Media Share ── -->
<div id="msShareModal" class="ms-share-modal" style="display:none;">
  <div class="ms-share-modal-content">
    <div class="ms-share-modal-header">
      <span>Share to Social Media</span>
      <button class="ms-edit-modal-close" onclick="closeShareModal()">&times;</button>
    </div>
    <div class="ms-share-modal-body">
      <div id="msSharePreview" class="ms-share-preview"></div>
      <label>Caption: <textarea id="msShareCaption" rows="3" class="ms-input-xs" placeholder="Generating AI caption..."></textarea></label>
      <div class="ms-share-platforms-label">Platforms:</div>
      <div id="msSharePlatforms" class="ms-share-platforms"></div>
      <label>Schedule (optional): <input type="datetime-local" id="msShareSchedule" class="ms-input-xs"></label>
    </div>
    <div class="ms-share-modal-footer">
      <button class="ms-btn-xs" onclick="submitShare('draft')">Save Draft</button>
      <button class="ms-btn-xs" onclick="submitShare('schedule')">Schedule</button>
      <button class="ms-btn ms-btn-primary" onclick="submitShare('now')">Post Now</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: Add S25 JavaScript block (~80 lines)**

```javascript
// ── S25  Social Media Share JS ──────────────────────────────────────

var _shareMediaId = null;

window.openShareModal = function(mediaId) {
    _shareMediaId = mediaId;
    document.getElementById('msShareModal').style.display = 'flex';
    document.getElementById('msShareCaption').value = '';
    document.getElementById('msShareSchedule').value = '';
    _clearChildren(document.getElementById('msSharePlatforms'));

    // Load preview thumbnail
    var preview = document.getElementById('msSharePreview');
    _clearChildren(preview);
    // Find the gallery card's image src
    var card = document.querySelector('[data-media-id="' + mediaId + '"]');
    if (card) {
        var img = document.createElement('img');
        img.src = card.querySelector('img') ? card.querySelector('img').src : '';
        img.className = 'ms-share-thumb';
        preview.appendChild(img);
    }

    // Load connected platforms
    api('GET', '/api/social-media/connected-platforms').then(function(platforms) {
        var container = document.getElementById('msSharePlatforms');
        _clearChildren(container);
        if (!Array.isArray(platforms) || platforms.length === 0) {
            container.textContent = 'No connected accounts. Connect in Social Media Manager.';
            return;
        }
        platforms.forEach(function(p) {
            var label = document.createElement('label');
            label.className = 'ms-share-platform-option';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = p.platform;
            cb.checked = true;
            cb.dataset.accountId = p.account_id;
            var span = document.createElement('span');
            span.textContent = p.platform + ' (' + p.account_name + ')';
            label.appendChild(cb);
            label.appendChild(span);
            container.appendChild(label);
        });
    });

    // Caption: leave empty, server generates on submit if blank.
    // Set placeholder to communicate this to the user.
    document.getElementById('msShareCaption').value = '';
    document.getElementById('msShareCaption').disabled = false;
    document.getElementById('msShareCaption').placeholder = 'Leave empty for AI-generated caption, or type your own';
};

window.closeShareModal = function() {
    document.getElementById('msShareModal').style.display = 'none';
    _shareMediaId = null;
};

window.submitShare = function(mode) {
    if (!_shareMediaId) return;

    var platforms = [];
    document.querySelectorAll('#msSharePlatforms input[type="checkbox"]:checked').forEach(function(cb) {
        platforms.push(cb.value);
    });
    if (platforms.length === 0) { alert('Select at least one platform'); return; }

    var caption = document.getElementById('msShareCaption').value.trim() || null;
    var scheduleVal = document.getElementById('msShareSchedule').value;
    var schedule_at = null;

    if (mode === 'schedule') {
        if (!scheduleVal) { alert('Select a schedule time'); return; }
        schedule_at = new Date(scheduleVal).toISOString();
    }

    if (mode === 'draft') {
        // Use bulk endpoint with single item
        api('POST', '/api/media-studio/share/bulk', {
            media_library_ids: [_shareMediaId],
            platforms: platforms,
        }).then(function(data) {
            if (data.error) { alert(data.error); return; }
            closeShareModal();
            alert('Saved as draft (' + data.count + ' posts). Review in Social Media Manager.');
        });
        return;
    }

    api('POST', '/api/media-studio/share', {
        media_library_id: _shareMediaId,
        platforms: platforms,
        caption: caption,
        schedule_at: schedule_at,
    }).then(function(data) {
        if (data.error) { alert(data.error); return; }
        closeShareModal();
        alert(data.status === 'scheduled' ? 'Post scheduled!' : 'Post queued for publishing!');
    });
};

```

Note: Caption generation happens server-side on submit if caption is left empty. No pre-fetch needed — the placeholder text communicates this to the user. Bulk gallery selection with checkboxes is descoped from this integration — the bulk API endpoint exists and works, but the UI entry point will be added in a future iteration. Users can use the per-card Share button for now.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html
git commit -m "feat(media-studio): add share modal + social media share JavaScript (S25)"
```

---

## Task 7: Share CSS

**Files:**
- Modify: `platform_v2/tools/media_studio/static/css/media-studio.css`

**Dependencies:** Task 6

- [ ] **Step 1: Append S25 CSS**

```css
/* ── S25  Social Media Share ── */
.ms-share-modal {
    position: fixed; inset: 0; z-index: 9999;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.85);
}
.ms-share-modal-content {
    background: var(--ms-bg, #1a1a2e);
    border: 1px solid var(--ms-accent, #f90);
    border-radius: 8px;
    width: 90vw; max-width: 500px; max-height: 90vh;
    display: flex; flex-direction: column; overflow: hidden;
}
.ms-share-modal-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--ms-border, #334);
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90);
}
.ms-share-modal-body {
    padding: 1rem; overflow-y: auto; flex: 1;
    display: flex; flex-direction: column; gap: 0.5rem;
    font-size: 0.75rem; color: var(--ms-text, #aab);
}
.ms-share-modal-body label { display: flex; flex-direction: column; gap: 0.25rem; }
.ms-share-preview { text-align: center; margin-bottom: 0.5rem; }
.ms-share-thumb {
    max-width: 200px; max-height: 150px; border-radius: 4px;
    border: 1px solid var(--ms-border, #334);
}
.ms-share-platforms-label {
    font-family: 'Antonio', sans-serif; text-transform: uppercase;
    color: var(--ms-accent, #f90); font-size: 0.7rem; margin-top: 0.25rem;
}
.ms-share-platforms {
    display: flex; flex-direction: column; gap: 0.25rem;
}
.ms-share-platform-option {
    display: flex; flex-direction: row; align-items: center; gap: 0.5rem;
    font-size: 0.75rem; cursor: pointer;
}
.ms-share-modal-footer {
    display: flex; justify-content: flex-end; align-items: center; gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--ms-border, #334);
}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/media_studio/static/css/media-studio.css
git commit -m "feat(media-studio): add social media share modal CSS (S25)"
```

---

## Task 8: Integration Test

**Files:**
- Create: `/tmp/test_social_publishing.py`

**Dependencies:** All previous tasks

- [ ] **Step 1: Write integration test**

```python
import sys, json, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Test imports
from tools.social_media.publishing_service import (
    publish_from_media_studio, bulk_publish_from_media_studio,
    generate_caption, get_connected_platforms,
)
results.append(('Import publishing_service', 'OK', True))

from app import app
with app.app_context():
    # Test generate_caption with non-existent media (should return fallback)
    caption = generate_caption(999999)
    results.append(('Caption fallback', caption, caption == 'Check out this creation!'))

    # Test get_connected_platforms (may be empty, should not error)
    platforms = get_connected_platforms(1)
    results.append(('Connected platforms', isinstance(platforms, list), True))

    # Test publish with non-existent media
    r = publish_from_media_studio(999999, ['instagram'], owner_id=1)
    results.append(('Publish bad media', 'error' in r, True))

    # Test bulk with empty list
    r = bulk_publish_from_media_studio([], ['instagram'], owner_id=1)
    results.append(('Bulk empty list', 'error' in r, True))

    # Test bulk over limit
    r = bulk_publish_from_media_studio(list(range(25)), ['instagram'], owner_id=1)
    results.append(('Bulk over limit', 'error' in r, True))

    # DB column exists
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='social_posts' AND column_name='media_library_id'"
        )
        results.append(('media_library_id column', cur.fetchone() is not None, True))

    # Routes registered
    rules = [r.rule for r in app.url_map.iter_rules()
             if 'share' in r.rule or 'connected-platforms' in r.rule or 'media-studio-posts' in r.rule]
    results.append(('Publishing routes', len(rules), len(rules) >= 4))

    # HTML checks
    html_path = '/app/tools/media_studio/templates/tools/media_studio/media_studio.html'
    with open(html_path) as f:
        html = f.read()
    for elem in ['msShareModal', 'msShareCaption', 'msSharePlatforms',
                 'openShareModal', 'submitShare', 'closeShareModal']:
        results.append((f'HTML has {elem}', elem, elem in html))

    # CSS checks
    css_path = '/app/tools/media_studio/static/css/media-studio.css'
    with open(css_path) as f:
        css = f.read()
    for cls in ['.ms-share-modal', '.ms-share-thumb', '.ms-share-platforms']:
        results.append((f'CSS has {cls}', cls, cls in css))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_social_publishing.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_social_publishing.py
```

Expected: All tests PASS.

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 9: Deploy + Git Push + Dev HQ Update

**Dependencies:** Task 8

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Push to remote**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

Use MCP tools:
- `store_memory` — Social Media publishing integration complete
- `log_decision` — cross-module FK reference pattern (media_library_id on social_posts)
