"""
Social Media Background Worker
==============================
APScheduler-based worker for processing scheduled posts and fetching analytics.

Jobs:
- process_queue: Every 60 seconds - process pending posts
- refresh_tokens: Every hour - refresh expiring tokens
- fetch_analytics: Every hour - update post metrics

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

import os
from database import _get_db_password
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List

import psycopg2
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger(__name__)

# Retry configuration
RETRY_DELAYS = [60, 300, 900]  # 1 min, 5 min, 15 min
MAX_RETRIES = 3


def get_db_connection():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# =============================================================================
# QUEUE PROCESSING
# =============================================================================


def get_pending_jobs(limit: int = 10) -> List[Dict]:
    """
    Get jobs ready to be processed.

    Returns jobs that are:
    - Status = 'pending'
    - scheduled_time <= NOW
    - Either no next_retry_at or next_retry_at <= NOW
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT q.*, p.content, p.media_urls, p.media_library_id, p.target_platforms,
                   a.platform, a.platform_user_id
            FROM social_media_queue q
            JOIN social_posts p ON q.post_id = p.id
            JOIN social_accounts a ON q.account_id = a.id
            WHERE q.status = 'pending'
            AND q.scheduled_time <= NOW()
            AND (q.next_retry_at IS NULL OR q.next_retry_at <= NOW())
            AND q.attempts < q.max_attempts
            ORDER BY q.priority DESC, q.scheduled_time ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        """,
            (limit,),
        )

        jobs = cur.fetchall()

        # Mark as processing
        if jobs:
            job_ids = [j["id"] for j in jobs]
            cur.execute(
                """
                UPDATE social_media_queue
                SET status = 'processing', last_attempt_at = NOW()
                WHERE id = ANY(%s)
            """,
                (job_ids,),
            )
            conn.commit()

        return [dict(j) for j in jobs]

    finally:
        cur.close()
        conn.close()


def process_job(job: Dict) -> Dict:
    """
    Process a single queue job (publish post).

    Args:
        job: Queue job dict

    Returns:
        Result dict with success, error, platform_response
    """
    from .platform_clients import (
        get_client_for_account,
        InstagramAPIError,
        TikTokAPIError,
    )

    start_time = time.time()
    account_id = job["account_id"]
    platform = job["platform"]
    post_id = job["post_id"]
    content = job["content"]
    media_urls = job.get("media_urls") or []

    # Resolve media from Media Studio if linked
    media_library_id = job.get("media_library_id")
    if media_library_id and (not media_urls or media_urls == [None] or media_urls == []):
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT file_path FROM media_library WHERE id = %s", (media_library_id,))
                ml_row = cur.fetchone()
                if ml_row and ml_row["file_path"]:
                    media_urls = [ml_row["file_path"]]
        except Exception as e:
            logger.warning(f"Failed to resolve media_library path: {e}")

    logger.info(f"Processing job {job['id']} for {platform} post {post_id}")

    try:
        # Get client
        client = get_client_for_account(account_id)

        result = None

        if platform == "instagram":
            # Determine content type
            if media_urls:
                first_url = media_urls[0] if isinstance(media_urls, list) else media_urls
                if any(ext in first_url.lower() for ext in [".mp4", ".mov", ".avi"]):
                    # Video post
                    result = client.post_video(video_url=first_url, caption=content)
                else:
                    # Image post
                    result = client.post_image(image_url=first_url, caption=content)
            else:
                raise ValueError("Instagram requires media (image or video)")

        elif platform == "tiktok":
            if not media_urls:
                raise ValueError("TikTok requires a video")

            first_url = media_urls[0] if isinstance(media_urls, list) else media_urls
            result = client.post_video(video_url=first_url, title=content[:150])  # TikTok title limit

        else:
            raise ValueError(f"Unsupported platform: {platform}")

        duration_ms = int((time.time() - start_time) * 1000)

        # Mark job as completed
        mark_job_completed(
            job["id"],
            post_id,
            platform,
            result.get("media_id") or result.get("platform_post_id"),
            result.get("platform_post_url"),
            result,
            duration_ms,
        )

        return {"success": True, "result": result, "duration_ms": duration_ms}

    except (InstagramAPIError, TikTokAPIError) as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"API error processing job {job['id']}: {e}")

        if e.is_retryable() and job["attempts"] < MAX_RETRIES:
            mark_job_retry(job["id"], str(e), e.response)
            return {"success": False, "error": str(e), "retryable": True}
        else:
            mark_job_failed(job["id"], post_id, platform, str(e), getattr(e, "response", None))
            return {"success": False, "error": str(e), "retryable": False}

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(f"Error processing job {job['id']}: {e}")
        mark_job_failed(job["id"], post_id, platform, str(e))
        return {"success": False, "error": str(e), "retryable": False}


def mark_job_completed(
    queue_id: int,
    post_id: int,
    platform: str,
    platform_post_id: str,
    platform_post_url: str,
    response: dict,
    duration_ms: int,
):
    """Mark a job as successfully completed."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Update queue
        cur.execute(
            """
            UPDATE social_media_queue
            SET status = 'completed', processed_at = NOW()
            WHERE id = %s
        """,
            (queue_id,),
        )

        # Update post result
        cur.execute(
            """
            INSERT INTO social_post_results (
                post_id, platform, platform_post_id, platform_post_url,
                status, published_at, platform_response
            ) VALUES (%s, %s, %s, %s, 'published', NOW(), %s)
            ON CONFLICT (post_id, platform) DO UPDATE SET
                platform_post_id = EXCLUDED.platform_post_id,
                platform_post_url = EXCLUDED.platform_post_url,
                status = 'published',
                published_at = NOW(),
                platform_response = EXCLUDED.platform_response
        """,
            (post_id, platform, platform_post_id, platform_post_url, Json(response)),
        )

        # Update post status
        cur.execute(
            """
            UPDATE social_posts
            SET status = 'published', published_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """,
            (post_id,),
        )

        # Log success
        cur.execute(
            """
            INSERT INTO social_job_logs (
                queue_id, post_id, job_type, status, platform_response, duration_ms
            ) VALUES (%s, %s, 'post', 'success', %s, %s)
        """,
            (queue_id, post_id, Json(response), duration_ms),
        )

        conn.commit()
        logger.info(f"Job {queue_id} completed successfully")

    finally:
        cur.close()
        conn.close()


def mark_job_retry(queue_id: int, error: str, response: dict = None):
    """Mark a job for retry with exponential backoff."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get current attempt count
        cur.execute("SELECT attempts FROM social_media_queue WHERE id = %s", (queue_id,))
        job = cur.fetchone()
        attempts = job["attempts"] if job else 0

        # Calculate next retry time
        delay = RETRY_DELAYS[min(attempts, len(RETRY_DELAYS) - 1)]
        next_retry = datetime.now() + timedelta(seconds=delay)

        cur.execute(
            """
            UPDATE social_media_queue
            SET status = 'pending',
                attempts = attempts + 1,
                error_message = %s,
                next_retry_at = %s
            WHERE id = %s
        """,
            (error, next_retry, queue_id),
        )

        # Log retry
        cur.execute(
            """
            INSERT INTO social_job_logs (
                queue_id, job_type, status, error_message, platform_response,
                attempt_number
            ) VALUES (%s, 'post', 'retry', %s, %s, %s)
        """,
            (queue_id, error, Json(response) if response else None, attempts + 1),
        )

        conn.commit()
        logger.info(f"Job {queue_id} scheduled for retry at {next_retry}")

    finally:
        cur.close()
        conn.close()


def mark_job_failed(queue_id: int, post_id: int, platform: str, error: str, response: dict = None):
    """Mark a job as permanently failed."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            UPDATE social_media_queue
            SET status = 'failed',
                error_message = %s,
                processed_at = NOW()
            WHERE id = %s
        """,
            (error, queue_id),
        )

        # Update post result
        cur.execute(
            """
            INSERT INTO social_post_results (
                post_id, platform, status, error_message, platform_response
            ) VALUES (%s, %s, 'failed', %s, %s)
            ON CONFLICT (post_id, platform) DO UPDATE SET
                status = 'failed',
                error_message = EXCLUDED.error_message,
                platform_response = EXCLUDED.platform_response
        """,
            (post_id, platform, error, Json(response) if response else None),
        )

        # Log failure
        cur.execute(
            """
            INSERT INTO social_job_logs (
                queue_id, post_id, job_type, status, error_message, platform_response
            ) VALUES (%s, %s, 'post', 'failed', %s, %s)
        """,
            (queue_id, post_id, error, Json(response) if response else None),
        )

        conn.commit()
        logger.warning(f"Job {queue_id} failed permanently: {error}")

    finally:
        cur.close()
        conn.close()


def process_queue_batch():
    """Process a batch of pending jobs."""
    jobs = get_pending_jobs(limit=5)

    if not jobs:
        return {"processed": 0}

    results = []
    for job in jobs:
        result = process_job(job)
        results.append({"job_id": job["id"], "post_id": job["post_id"], **result})

    successful = sum(1 for r in results if r.get("success"))
    logger.info(f"Processed {len(jobs)} jobs: {successful} successful")

    return {"processed": len(jobs), "successful": successful, "results": results}


# =============================================================================
# TOKEN REFRESH
# =============================================================================


def refresh_expiring_tokens():
    """Refresh tokens expiring within 7 days."""
    from .oauth_handler import (
        get_expiring_tokens,
        InstagramOAuth,
        TikTokOAuth,
        store_oauth_token,
    )

    tokens = get_expiring_tokens(days=7)
    refreshed = 0
    errors = []

    for token in tokens:
        try:
            platform = token["platform"]
            account_id = token["account_id"]

            # Get current decrypted token
            from .oauth_handler import get_oauth_token

            current = get_oauth_token(account_id)

            if not current:
                continue

            new_data = None

            if platform == "instagram":
                oauth = InstagramOAuth()
                new_data = oauth.refresh_token(current["access_token"])
            elif platform == "tiktok":
                if not current.get("refresh_token"):
                    continue
                oauth = TikTokOAuth()
                new_data = oauth.refresh_token(current["refresh_token"])

            if new_data:
                store_oauth_token(
                    account_id=account_id,
                    platform=platform,
                    access_token=new_data.get("access_token"),
                    refresh_token=new_data.get("refresh_token", current.get("refresh_token")),
                    expires_in=new_data.get("expires_in"),
                )
                refreshed += 1
                logger.info(f"Refreshed token for account {account_id}")

        except Exception as e:
            logger.error(f"Failed to refresh token for account {token.get('account_id')}: {e}")
            errors.append({"account_id": token.get("account_id"), "error": str(e)})

    return {"refreshed": refreshed, "errors": errors}


# =============================================================================
# ANALYTICS FETCHING
# =============================================================================


def fetch_post_analytics():
    """Fetch analytics for published posts."""
    from .platform_clients import get_client_for_account

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get published posts that need metrics update (last 30 days)
        cur.execute(
            """
            SELECT r.id, r.post_id, r.platform, r.platform_post_id, r.account_id
            FROM social_post_results r
            JOIN social_posts p ON r.post_id = p.id
            WHERE r.status = 'published'
            AND r.platform_post_id IS NOT NULL
            AND r.published_at > NOW() - INTERVAL '30 days'
            AND (r.last_metrics_sync IS NULL OR r.last_metrics_sync < NOW() - INTERVAL '1 hour')
            ORDER BY r.published_at DESC
            LIMIT 50
        """
        )

        posts = cur.fetchall()
        updated = 0
        errors = []

        for post in posts:
            try:
                client = get_client_for_account(post["account_id"])
                platform = post["platform"]
                metrics = {}

                if platform == "instagram":
                    metrics = client.get_media_insights(post["platform_post_id"])
                elif platform == "tiktok":
                    # TikTok requires fetching video list
                    videos = client.get_videos(max_count=50)
                    for video in videos:
                        if video.get("id") == post["platform_post_id"]:
                            metrics = {
                                "views": video.get("view_count", 0),
                                "likes": video.get("like_count", 0),
                                "comments": video.get("comment_count", 0),
                                "shares": video.get("share_count", 0),
                            }
                            break

                if metrics:
                    # Calculate engagement rate
                    cur.execute(
                        """
                        SELECT followers_count FROM social_accounts WHERE id = %s
                    """,
                        (post["account_id"],),
                    )
                    account = cur.fetchone()
                    followers = account["followers_count"] if account else 0

                    interactions = metrics.get("likes", 0) + metrics.get("comments", 0) + metrics.get("shares", 0)
                    engagement_rate = round((interactions / followers * 100), 2) if followers > 0 else 0

                    # Update metrics
                    cur.execute(
                        """
                        UPDATE social_post_results
                        SET views_count = COALESCE(%s, views_count),
                            likes_count = COALESCE(%s, likes_count),
                            comments_count = COALESCE(%s, comments_count),
                            shares_count = COALESCE(%s, shares_count),
                            saves_count = COALESCE(%s, saves_count),
                            reach = COALESCE(%s, reach),
                            impressions = COALESCE(%s, impressions),
                            engagement_rate = %s,
                            last_metrics_sync = NOW()
                        WHERE id = %s
                    """,
                        (
                            metrics.get("views") or metrics.get("impressions"),
                            metrics.get("likes") or metrics.get("engagement"),
                            metrics.get("comments"),
                            metrics.get("shares"),
                            metrics.get("saved"),
                            metrics.get("reach"),
                            metrics.get("impressions"),
                            engagement_rate,
                            post["id"],
                        ),
                    )
                    updated += 1

            except Exception as e:
                logger.error(f"Failed to fetch analytics for post {post['id']}: {e}")
                errors.append({"post_id": post["id"], "error": str(e)})

        conn.commit()
        return {"updated": updated, "errors": errors}

    finally:
        cur.close()
        conn.close()


# =============================================================================
# SCHEDULER SETUP
# =============================================================================


def init_scheduler(app):
    """
    Initialize APScheduler with social media jobs.

    Args:
        app: Flask application instance
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.warning("APScheduler not installed. Social media worker disabled.")
        return None

    scheduler = BackgroundScheduler()

    # Process queue every 60 seconds
    scheduler.add_job(
        func=process_queue_batch,
        trigger=IntervalTrigger(seconds=60),
        id="social_process_queue",
        name="Process social media queue",
        replace_existing=True,
    )

    # Refresh tokens every hour
    scheduler.add_job(
        func=refresh_expiring_tokens,
        trigger=IntervalTrigger(hours=1),
        id="social_refresh_tokens",
        name="Refresh expiring tokens",
        replace_existing=True,
    )

    # Fetch analytics every hour
    scheduler.add_job(
        func=fetch_post_analytics,
        trigger=IntervalTrigger(hours=1),
        id="social_fetch_analytics",
        name="Fetch post analytics",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Social media scheduler started")

    return scheduler


# =============================================================================
# MANUAL TRIGGER ENDPOINTS
# =============================================================================


def trigger_immediate_post(post_id: int) -> Dict:
    """
    Trigger immediate posting for a specific post.

    Args:
        post_id: Post ID to publish

    Returns:
        Result dict
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get queue jobs for this post
        cur.execute(
            """
            SELECT q.*, a.platform
            FROM social_media_queue q
            JOIN social_accounts a ON q.account_id = a.id
            WHERE q.post_id = %s AND q.status IN ('pending', 'processing')
        """,
            (post_id,),
        )

        jobs = cur.fetchall()

        if not jobs:
            return {"success": False, "error": "No pending jobs found for this post"}

        results = []
        for job in jobs:
            # Update to process immediately
            cur.execute(
                """
                UPDATE social_media_queue
                SET scheduled_time = NOW(), status = 'pending', next_retry_at = NULL
                WHERE id = %s
            """,
                (job["id"],),
            )
            conn.commit()

            # Process job
            result = process_job(dict(job))
            results.append(result)

        return {"success": all(r.get("success") for r in results), "results": results}

    finally:
        cur.close()
        conn.close()
