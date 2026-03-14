# Social Media Manager — Media Publishing Integration — Design Spec

## Overview

Connect Media Studio's gallery to the Social Media Manager module for publishing AI-generated images and videos to social platforms. Users can quick-share a single image with an AI-generated caption or bulk-send multiple items as drafts for review in the Social Media UI.

**Goal:** Add a "Share" button to Media Studio gallery cards that opens a composer modal with auto-generated AI caption, platform selection, and schedule/post-now options. Bulk share sends selected items as drafts to the Social Media module. Publishing uses the existing `social_worker` queue.

## Scope

Three capabilities:
1. **Quick share** — single image share with AI caption, platform select, immediate/scheduled post
2. **Bulk share** — send multiple gallery items as drafts to Social Media module
3. **AI caption generation** — auto-fill caption from image prompt/tags via Bridge AI

## Database Schema

### Schema change: `social_posts`

```sql
ALTER TABLE social_posts
ADD COLUMN IF NOT EXISTS media_library_id INTEGER REFERENCES media_library(id);

CREATE INDEX IF NOT EXISTS idx_social_posts_media_library ON social_posts(media_library_id) WHERE media_library_id IS NOT NULL;
```

Nullable FK linking a social post to a Media Studio asset. When set, the social worker resolves the file path from `media_library` instead of `social_media_library`.

No new tables needed.

## Publishing Service

**New file:** `platform_v2/tools/social_media/publishing_service.py` (~150 lines)

### `publish_from_media_studio(media_library_id, platforms, caption=None, schedule_at=None, owner_id=None)`

1. Validate `media_library_id` exists in `media_library`, get file_path and metadata
2. If `caption` is None or empty, call `generate_caption(media_library_id)` for AI auto-fill
3. For each platform in `platforms`:
   - Verify platform has a connected account in `social_accounts` for the owner
   - Insert into `social_posts`: content=caption, platform=platform, status='queued' or 'scheduled', `media_library_id=media_library_id`, `scheduled_at=schedule_at`
   - If no schedule_at (immediate): insert into `social_media_queue` with status='pending'
   - If scheduled: set status='scheduled' (existing scheduler picks it up)
4. Return `{"post_ids": [ids], "status": "queued"|"scheduled"}`

### `bulk_publish_from_media_studio(media_library_ids, platforms, schedule_at=None, owner_id=None)`

1. Validate all IDs exist in `media_library`
2. For each media_library_id: call `generate_caption()`, then create posts as drafts (status='draft')
3. Return `{"draft_ids": [ids], "count": len}`

### `generate_caption(media_library_id)`

1. Load media_library row — get `prompt`, tags from metadata JSONB, `media_type`
2. Build AI prompt: "Write a social media caption for this AI-generated {media_type}. Original prompt: {prompt}. Tags: {tags}. Keep it engaging, under 280 characters."
3. Call Bridge dispatcher: `dispatcher.request_work(capability='text_generation', prompt=ai_prompt, module_id='social_media', priority='normal')`
4. Return generated caption string, or fallback to the original generation prompt if AI fails or is unavailable

### `get_connected_platforms(owner_id)`

Query `social_accounts WHERE owner_id = %s AND status = 'active'`. Return list of `{platform, account_name, account_id}`.

## Social Worker Patch

**Modified file:** `platform_v2/tools/social_media/social_worker.py`

When processing a queued post, check if `media_library_id` is set. If so, resolve the file path by querying `media_library`:

```python
if post.get('media_library_id'):
    # Resolve from Media Studio
    cur.execute("SELECT file_path FROM media_library WHERE id = %s", (post['media_library_id'],))
    row = cur.fetchone()
    media_path = row['file_path'] if row else None
else:
    # Existing logic: resolve from social_media_library
    media_path = post.get('media_url')
```

Small patch (~10 lines) in the existing publish flow.

## API Routes

### Media Studio side (2 endpoints)

**Modified file:** `platform_v2/tools/media_studio/routes.py`

#### `POST /api/media-studio/share`
Quick share single image. Body: `{media_library_id, platforms: [...], caption, schedule_at}`.
Response: `{post_ids: [...], status: "queued"|"scheduled"}`

#### `POST /api/media-studio/share/bulk`
Bulk send as drafts. Body: `{media_library_ids: [...], platforms: [...]}`.
Response: `{draft_ids: [...], count: int}`

### Social Media side (2 endpoints)

**Modified file:** `platform_v2/tools/social_media/routes.py`

#### `GET /api/social-media/connected-platforms`
Returns platforms with active connected accounts for current user.
Response: `[{platform, account_name, account_id}]`

#### `GET /api/social-media/media-studio-posts`
Returns social posts linked to Media Studio assets.
Response: `[{post_id, media_library_id, platform, status, caption, scheduled_at}]`

## Frontend

**Modified file:** `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

### Share button on gallery cards

Added to `_createGalleryCard` alongside existing Edit button:
```javascript
var shareBtn = document.createElement('button');
shareBtn.className = 'ms-card-action-btn';
shareBtn.textContent = 'Share';
shareBtn.onclick = function(e) { e.stopPropagation(); openShareModal(g.id); };
```

### Share modal (`#msShareModal`)

Compact modal:
- Image thumbnail preview
- Caption textarea (auto-filled with AI caption, editable)
- Platform checkboxes (dynamically loaded from connected platforms)
- Schedule datetime picker (optional)
- Three action buttons: "Post Now", "Schedule", "Save as Draft"
- Loading state while AI caption generates

### Bulk share

"Share Selected" button in gallery header area. Opens a simplified modal (no caption editing — auto-generated per item, all sent as drafts).

### JS functions (~80 lines)

- `openShareModal(mediaId)` — fetch platforms, generate caption, show modal
- `closeShareModal()`
- `submitShare(mode)` — 'now', 'schedule', or 'draft'. POST /api/media-studio/share
- `bulkShare()` — collect selected IDs, POST /api/media-studio/share/bulk
- `loadConnectedPlatforms()` — GET /api/social-media/connected-platforms, render checkboxes

## CSS

**Modified file:** `platform_v2/tools/media_studio/static/css/media-studio.css`

New styles (~40 lines):
- `.ms-share-modal` — compact modal (max-width 500px), reuses edit modal pattern
- `.ms-share-preview` — thumbnail area
- `.ms-share-caption` — textarea with AI indicator
- `.ms-share-platforms` — checkbox grid for platforms
- `.ms-share-schedule` — datetime picker row
- `.ms-share-actions` — button group

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/157_social_media_publishing.sql` | `media_library_id` FK on `social_posts` + index |
| **Create** | `platform_v2/tools/social_media/publishing_service.py` | Publishing service (~150 lines) |
| **Modify** | `platform_v2/tools/media_studio/routes.py` | 2 endpoints: share + bulk share (S25) |
| **Modify** | `platform_v2/tools/social_media/routes.py` | 2 endpoints: connected-platforms + media-studio-posts |
| **Modify** | `platform_v2/tools/social_media/social_worker.py` | Patch: resolve file from media_library when FK set (~10 lines) |
| **Modify** | `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Share button + modal + JS (~80 lines) |
| **Modify** | `platform_v2/tools/media_studio/static/css/media-studio.css` | Share modal styles (~40 lines) |

**Total:** ~270 lines new code, ~30 lines modifications

## Dependencies

None new — uses existing Bridge AI suggestion and social_worker queue infrastructure.

## Scope constraints

- No image cropping/resizing per platform
- No multi-image carousel posts (one image per post)
- No analytics feedback from social posts back to Media Studio
- No direct OAuth from Media Studio — accounts connected in Social Media module
- Bulk share creates drafts only (user reviews in Social Media UI)
