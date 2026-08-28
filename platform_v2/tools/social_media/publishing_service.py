"""
Social Media Publishing Service
================================
Bridges Media Studio with social media publishing pipeline.

Handles:
- Single media item publishing to one or more platforms
- Bulk draft creation from media library
- AI caption generation via Archie Bridge
- Connected platform discovery

Author: A.R.C.H.I.E. Platform
Date: 2026-03-14
"""

import logging
from psycopg2.extras import Json

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Bridge availability flag
try:
    from tools.department_hq.services.department_dispatcher import dispatch_json

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False
    logger.warning("Department HQ dispatcher not available, AI captions will use fallback")


def generate_caption(media_library_id):
    """
    Generate a caption for a media item using AI or fallback text.

    Loads metadata from media_library, builds a prompt from prompt/tags fields,
    calls archie_bridge for a caption, falls back gracefully.

    Returns caption string (max 280 chars).
    """
    prompt_text = None
    tags = []

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT file_path, media_type, metadata FROM media_library WHERE id = %s",
                (media_library_id,),
            )
            row = cur.fetchone()
            if row:
                metadata = row["metadata"] or {}
                if isinstance(metadata, str):
                    import json

                    metadata = json.loads(metadata)
                prompt_text = metadata.get("prompt") or metadata.get("caption_hint")
                tags = metadata.get("tags") or []
    except Exception as e:
        logger.warning("Could not load media metadata for caption: %s", e)

    # Build AI prompt
    base_hint = prompt_text or "a creative image"
    tag_str = ", ".join(tags) if tags else ""
    ai_prompt = (
        f"Write a short, engaging social media caption (max 240 characters) for an image. "
        f"Image description: {base_hint}."
        + (f" Relevant tags: {tag_str}." if tag_str else "")
        + " Be concise and compelling."
    )

    if BRIDGE_AVAILABLE:
        try:
            result = dispatch_json(capability="creative", prompt=ai_prompt, module_id="social_media")
            caption = ""
            if isinstance(result, dict):
                caption = result.get("response") or result.get("content") or ""
            elif isinstance(result, str):
                caption = result
            caption = caption.strip()
            if caption:
                return caption[:280]
        except Exception as e:
            logger.warning("Bridge caption generation failed: %s", e)

    # Fallback: use prompt_text or generic
    fallback = (prompt_text or "Check out this amazing content!") + ((" #" + " #".join(tags)) if tags else "")
    return fallback[:280]


def get_connected_platforms(owner_id):
    """
    Return list of active social accounts for owner_id.

    Returns list of dicts: {account_id, platform, account_name}.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id AS account_id, platform, account_name
                FROM social_accounts
                WHERE user_id = %s AND is_active = true
                ORDER BY platform
                """,
                (owner_id,),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_connected_platforms error: %s", e)
        return []


def publish_from_media_studio(media_library_id, platforms, caption=None, schedule_at=None, owner_id=None):
    """
    Publish a media library item to one or more social platforms.

    Steps:
    1. Validate media_library_id exists, fetch file_path and media_type.
    2. Generate caption if not provided.
    3. For each platform, verify active account, insert social_post, queue if immediate.

    Returns {"post_ids": [...], "status": "queued"|"scheduled"} or {"error": ...}.
    """
    if not platforms:
        return {"error": "No platforms specified"}

    # 1. Validate media item
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, file_path, media_type, metadata FROM media_library WHERE id = %s",
                (media_library_id,),
            )
            media = cur.fetchone()
    except Exception as e:
        logger.error("DB error fetching media_library %s: %s", media_library_id, e)
        return {"error": f"Database error: {e}"}

    if not media:
        return {"error": f"Media item {media_library_id} not found"}

    file_path = media["file_path"]
    media_type = media["media_type"]

    # 2. Generate caption if missing
    if not caption:
        caption = generate_caption(media_library_id)

    post_status = "scheduled" if schedule_at else "queued"
    post_ids = []

    # 3. Per-platform insert
    for platform in platforms:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Verify account exists
                cur.execute(
                    """
                    SELECT id FROM social_accounts
                    WHERE user_id = %s AND platform = %s AND is_active = true
                    LIMIT 1
                    """,
                    (owner_id, platform),
                )
                account = cur.fetchone()
                if not account:
                    logger.info("No active %s account for user %s — skipping", platform, owner_id)
                    continue

                account_id = account["id"]

                # Insert social_post
                cur.execute(
                    """
                    INSERT INTO social_posts
                        (user_id, content, media_urls, media_type, media_library_id,
                         target_platforms, status, scheduled_at, ai_generated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        owner_id,
                        caption,
                        Json([file_path]),
                        media_type,
                        media_library_id,
                        [platform],
                        post_status,
                        schedule_at,
                        True,
                    ),
                )
                post_id = cur.fetchone()["id"]
                post_ids.append(post_id)

                # Queue immediately if no schedule
                if not schedule_at:
                    cur.execute(
                        """
                        INSERT INTO social_media_queue (post_id, account_id, status, priority)
                        VALUES (%s, %s, 'pending', 5)
                        """,
                        (post_id, account_id),
                    )

        except Exception as e:
            logger.error("Error publishing to %s for media %s: %s", platform, media_library_id, e)
            continue

    if not post_ids:
        return {"error": "No posts created — check that accounts are connected for requested platforms"}

    return {"post_ids": post_ids, "status": post_status}


def bulk_publish_from_media_studio(media_library_ids, platforms, owner_id=None):
    """
    Create draft posts for multiple media items across platforms.

    Validates up to 20 items, generates captions, inserts with status='draft'.

    Returns {"draft_ids": [...], "count": int} or {"error": ...}.
    """
    if not media_library_ids:
        return {"error": "No media items specified"}

    if len(media_library_ids) > 20:
        return {"error": "Maximum 20 items per bulk operation"}

    if not platforms:
        return {"error": "No platforms specified"}

    draft_ids = []

    for media_library_id in media_library_ids:
        # Validate media item
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT id, file_path, media_type FROM media_library WHERE id = %s",
                    (media_library_id,),
                )
                media = cur.fetchone()
        except Exception as e:
            logger.warning("DB error fetching media %s: %s — skipping", media_library_id, e)
            continue

        if not media:
            logger.warning("Media item %s not found — skipping", media_library_id)
            continue

        file_path = media["file_path"]
        media_type = media["media_type"]
        caption = generate_caption(media_library_id)

        for platform in platforms:
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        INSERT INTO social_posts
                            (user_id, content, media_urls, media_type, media_library_id,
                             target_platforms, status, ai_generated)
                        VALUES (%s, %s, %s, %s, %s, %s, 'draft', %s)
                        RETURNING id
                        """,
                        (
                            owner_id,
                            caption,
                            Json([file_path]),
                            media_type,
                            media_library_id,
                            [platform],
                            True,
                        ),
                    )
                    draft_id = cur.fetchone()["id"]
                    draft_ids.append(draft_id)
            except Exception as e:
                logger.error(
                    "Error creating draft for media %s / platform %s: %s",
                    media_library_id,
                    platform,
                    e,
                )
                continue

    return {"draft_ids": draft_ids, "count": len(draft_ids)}
