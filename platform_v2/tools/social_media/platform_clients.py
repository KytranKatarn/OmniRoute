"""
Social Media Platform API Clients
=================================
Wrapper classes for posting content to Instagram and TikTok.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

import os
from database import _get_db_password
import time
import logging
import requests
from typing import Dict, List
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger(__name__)


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
# RATE LIMIT TRACKING
# =============================================================================


def check_rate_limit(platform: str, endpoint: str, account_id: int = None) -> Dict:
    """
    Check if we're within rate limits for an endpoint.

    Args:
        platform: Platform name
        endpoint: Endpoint name (e.g., 'post', 'analytics')
        account_id: Optional account ID for per-account limits

    Returns:
        Dict with 'allowed', 'calls_remaining', 'reset_at'
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT * FROM social_api_rate_limits
            WHERE platform = %s AND endpoint = %s
            AND (account_id = %s OR account_id IS NULL)
            ORDER BY account_id NULLS LAST
            LIMIT 1
        """,
            (platform, endpoint, account_id),
        )

        limit = cur.fetchone()

        if not limit:
            # No limit defined - allow
            return {"allowed": True, "calls_remaining": None, "reset_at": None}

        # Check if window has expired
        window_end = limit["window_start"].timestamp() + limit["window_duration_seconds"]
        now = time.time()

        if now > window_end:
            # Reset window
            cur.execute(
                """
                UPDATE social_api_rate_limits
                SET calls_made = 0, window_start = NOW()
                WHERE id = %s
            """,
                (limit["id"],),
            )
            conn.commit()
            return {
                "allowed": True,
                "calls_remaining": limit["limit_max"],
                "reset_at": None,
            }

        calls_remaining = limit["limit_max"] - limit["calls_made"]

        return {
            "allowed": calls_remaining > 0,
            "calls_remaining": max(0, calls_remaining),
            "reset_at": datetime.fromtimestamp(window_end),
        }

    finally:
        cur.close()
        conn.close()


def increment_rate_limit(platform: str, endpoint: str, account_id: int = None):
    """Increment rate limit counter."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO social_api_rate_limits (platform, endpoint, account_id, calls_made, limit_max)
            VALUES (%s, %s, %s, 1, 200)
            ON CONFLICT (platform, endpoint, account_id) DO UPDATE
            SET calls_made = social_api_rate_limits.calls_made + 1
        """,
            (platform, endpoint, account_id),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


# =============================================================================
# INSTAGRAM CLIENT
# =============================================================================


class InstagramClient:
    """Instagram Graph API client for posting content."""

    API_VERSION = "v18.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

    def __init__(self, access_token: str, ig_user_id: str = None):
        """
        Initialize Instagram client.

        Args:
            access_token: Valid Instagram access token
            ig_user_id: Instagram Business Account ID (fetched if not provided)
        """
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self._page_id = None

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make API request with error handling."""
        url = f"{self.BASE_URL}{endpoint}"
        kwargs.setdefault("params", {})["access_token"] = self.access_token

        response = requests.request(method, url, timeout=60, **kwargs)

        try:
            data = response.json()
        except Exception:
            data = {"error": {"message": response.text}}

        if "error" in data:
            error = data["error"]
            raise InstagramAPIError(
                message=error.get("message", "Unknown error"),
                code=error.get("code"),
                error_subcode=error.get("error_subcode"),
                response=data,
            )

        return data

    def get_account_info(self) -> Dict:
        """Get Instagram account info and set user ID."""
        # Get pages first
        pages = self._request("GET", "/me/accounts")

        if not pages.get("data"):
            raise InstagramAPIError("No Facebook Pages found")

        page = pages["data"][0]
        self._page_id = page["id"]

        # Get Instagram account
        ig_data = self._request(
            "GET",
            f"/{self._page_id}",
            params={"fields": "instagram_business_account{id,username,profile_picture_url,followers_count}"},
        )

        ig_account = ig_data.get("instagram_business_account")
        if not ig_account:
            raise InstagramAPIError("No Instagram Business Account found on Page")

        self.ig_user_id = ig_account["id"]
        return ig_account

    def create_media_container(
        self,
        image_url: str = None,
        video_url: str = None,
        caption: str = "",
        media_type: str = "IMAGE",
    ) -> str:
        """
        Create a media container (step 1 of posting).

        Args:
            image_url: Public URL to image (for IMAGE or CAROUSEL_ALBUM)
            video_url: Public URL to video (for VIDEO or REELS)
            caption: Post caption
            media_type: 'IMAGE', 'VIDEO', 'REELS', or 'CAROUSEL_ALBUM'

        Returns:
            Container ID
        """
        if not self.ig_user_id:
            self.get_account_info()

        params = {"caption": caption}

        if media_type == "VIDEO" or media_type == "REELS":
            params["video_url"] = video_url
            params["media_type"] = media_type
        else:
            params["image_url"] = image_url

        data = self._request("POST", f"/{self.ig_user_id}/media", params=params)
        return data["id"]

    def publish_container(self, container_id: str) -> str:
        """
        Publish a media container (step 2 of posting).

        Args:
            container_id: Container ID from create_media_container

        Returns:
            Published media ID
        """
        if not self.ig_user_id:
            self.get_account_info()

        data = self._request(
            "POST",
            f"/{self.ig_user_id}/media_publish",
            params={"creation_id": container_id},
        )
        return data["id"]

    def check_container_status(self, container_id: str) -> Dict:
        """
        Check container status (for videos - async processing).

        Args:
            container_id: Container ID

        Returns:
            Dict with 'status_code' and 'status'
        """
        data = self._request("GET", f"/{container_id}", params={"fields": "status_code,status"})
        return data

    def post_image(self, image_url: str, caption: str = "") -> Dict:
        """
        Post a single image to Instagram.

        Args:
            image_url: Public URL to image
            caption: Post caption

        Returns:
            Dict with 'media_id', 'container_id'
        """
        # Check rate limit
        rate_check = check_rate_limit("instagram", "post")
        if not rate_check["allowed"]:
            raise InstagramAPIError(
                f"Rate limit exceeded. Reset at {rate_check['reset_at']}",
                code="rate_limit_exceeded",
            )

        # Create container
        container_id = self.create_media_container(image_url=image_url, caption=caption, media_type="IMAGE")

        # Publish
        media_id = self.publish_container(container_id)

        # Track rate limit
        increment_rate_limit("instagram", "post")

        return {
            "media_id": media_id,
            "container_id": container_id,
            "platform_post_url": f"https://www.instagram.com/p/{media_id}/",
        }

    def post_video(
        self,
        video_url: str,
        caption: str = "",
        media_type: str = "VIDEO",
        wait_for_processing: bool = True,
        max_wait_seconds: int = 300,
    ) -> Dict:
        """
        Post a video to Instagram.

        Args:
            video_url: Public URL to video
            caption: Post caption
            media_type: 'VIDEO' or 'REELS'
            wait_for_processing: Wait for video processing
            max_wait_seconds: Maximum wait time

        Returns:
            Dict with 'media_id', 'container_id'
        """
        rate_check = check_rate_limit("instagram", "post")
        if not rate_check["allowed"]:
            raise InstagramAPIError(
                f"Rate limit exceeded. Reset at {rate_check['reset_at']}",
                code="rate_limit_exceeded",
            )

        # Create container
        container_id = self.create_media_container(video_url=video_url, caption=caption, media_type=media_type)

        # Wait for processing if requested
        if wait_for_processing:
            start = time.time()
            while time.time() - start < max_wait_seconds:
                status = self.check_container_status(container_id)
                status_code = status.get("status_code")

                if status_code == "FINISHED":
                    break
                elif status_code == "ERROR":
                    raise InstagramAPIError(
                        f"Video processing failed: {status.get('status')}",
                        code="video_processing_failed",
                    )

                time.sleep(10)  # Check every 10 seconds
            else:
                raise InstagramAPIError("Video processing timeout", code="video_processing_timeout")

        # Publish
        media_id = self.publish_container(container_id)

        increment_rate_limit("instagram", "post")

        return {
            "media_id": media_id,
            "container_id": container_id,
            "platform_post_url": (
                f"https://www.instagram.com/reel/{media_id}/"
                if media_type == "REELS"
                else f"https://www.instagram.com/p/{media_id}/"
            ),
        }

    def get_media_insights(self, media_id: str) -> Dict:
        """
        Get insights for a media post.

        Args:
            media_id: Instagram media ID

        Returns:
            Dict with metrics
        """
        data = self._request(
            "GET",
            f"/{media_id}/insights",
            params={"metric": "impressions,reach,engagement,saved,likes,comments,shares"},
        )

        # Convert to flat dict
        metrics = {}
        for item in data.get("data", []):
            metrics[item["name"]] = item["values"][0]["value"]

        return metrics

    def get_account_insights(self, period: str = "day") -> Dict:
        """
        Get account-level insights.

        Args:
            period: 'day', 'week', 'days_28'

        Returns:
            Dict with metrics
        """
        if not self.ig_user_id:
            self.get_account_info()

        data = self._request(
            "GET",
            f"/{self.ig_user_id}/insights",
            params={
                "metric": "impressions,reach,follower_count,profile_views",
                "period": period,
            },
        )

        metrics = {}
        for item in data.get("data", []):
            metrics[item["name"]] = item["values"][0]["value"]

        return metrics


class InstagramAPIError(Exception):
    """Instagram API error."""

    def __init__(
        self,
        message: str,
        code: str = None,
        error_subcode: str = None,
        response: dict = None,
    ):
        self.message = message
        self.code = code
        self.error_subcode = error_subcode
        self.response = response or {}
        super().__init__(self.message)

    def is_retryable(self) -> bool:
        """Check if this error is retryable."""
        retryable_codes = [
            "rate_limit_exceeded",
            "service_unavailable",
            "timeout",
            "temporary_error",
            1,  # Unknown error
            2,  # Service temporarily unavailable
        ]
        return self.code in retryable_codes or self.error_subcode in retryable_codes


# =============================================================================
# TIKTOK CLIENT
# =============================================================================


class TikTokClient:
    """TikTok Content API client for posting videos."""

    API_URL = "https://open.tiktokapis.com/v2"

    def __init__(self, access_token: str, open_id: str = None):
        """
        Initialize TikTok client.

        Args:
            access_token: Valid TikTok access token
            open_id: TikTok user open_id
        """
        self.access_token = access_token
        self.open_id = open_id

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make API request with error handling."""
        url = f"{self.API_URL}{endpoint}"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"
        headers["Content-Type"] = "application/json"

        response = requests.request(method, url, headers=headers, timeout=60, **kwargs)

        try:
            data = response.json()
        except Exception:
            data = {"error": {"message": response.text}}

        if data.get("error") and data["error"].get("code") != "ok":
            error = data["error"]
            raise TikTokAPIError(
                message=error.get("message", "Unknown error"),
                code=error.get("code"),
                response=data,
            )

        return data

    def get_user_info(self) -> Dict:
        """Get TikTok user info."""
        data = self._request(
            "GET",
            "/user/info/",
            params={"fields": "open_id,union_id,avatar_url,display_name,follower_count"},
        )
        user = data.get("data", {}).get("user", {})
        self.open_id = user.get("open_id")
        return user

    def init_video_upload(self, video_url: str, title: str = "", privacy: str = "SELF_ONLY") -> str:
        """
        Initialize video upload from URL (pull from URL method).

        Args:
            video_url: Public URL to video (3-60 seconds, max 4GB)
            title: Video title/description
            privacy: 'PUBLIC_TO_EVERYONE', 'MUTUAL_FOLLOW_FRIENDS', 'SELF_ONLY'

        Returns:
            publish_id for tracking
        """
        rate_check = check_rate_limit("tiktok", "post")
        if not rate_check["allowed"]:
            raise TikTokAPIError(
                f"Rate limit exceeded. Reset at {rate_check['reset_at']}",
                code="rate_limit_exceeded",
            )

        data = self._request(
            "POST",
            "/post/publish/video/init/",
            json={
                "post_info": {
                    "title": title,
                    "privacy_level": privacy,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "video_url": video_url,
                },
            },
        )

        increment_rate_limit("tiktok", "post")

        return data.get("data", {}).get("publish_id")

    def check_publish_status(self, publish_id: str) -> Dict:
        """
        Check video publish status.

        Args:
            publish_id: From init_video_upload

        Returns:
            Dict with status info
        """
        data = self._request("POST", "/post/publish/status/fetch/", json={"publish_id": publish_id})

        return data.get("data", {})

    def post_video(
        self,
        video_url: str,
        title: str = "",
        privacy: str = "SELF_ONLY",
        wait_for_completion: bool = True,
        max_wait_seconds: int = 600,
    ) -> Dict:
        """
        Post a video to TikTok.

        Args:
            video_url: Public URL to video
            title: Video title/description
            privacy: Privacy level
            wait_for_completion: Wait for processing
            max_wait_seconds: Maximum wait time

        Returns:
            Dict with publish result
        """
        publish_id = self.init_video_upload(video_url, title, privacy)

        if not wait_for_completion:
            return {"publish_id": publish_id, "status": "PROCESSING"}

        # Wait for completion
        start = time.time()
        while time.time() - start < max_wait_seconds:
            status = self.check_publish_status(publish_id)
            status_code = status.get("status")

            if status_code == "PUBLISH_COMPLETE":
                return {
                    "publish_id": publish_id,
                    "status": "PUBLISH_COMPLETE",
                    "platform_post_id": status.get("publicaly_available_post_id", [{}])[0].get("id"),
                }
            elif status_code == "FAILED":
                raise TikTokAPIError(
                    f"Video publish failed: {status.get('fail_reason')}",
                    code="publish_failed",
                )

            time.sleep(15)  # Check every 15 seconds

        raise TikTokAPIError("Video publish timeout", code="publish_timeout")

    def get_videos(self, max_count: int = 20) -> List[Dict]:
        """
        Get user's recent videos with metrics.

        Args:
            max_count: Maximum videos to fetch

        Returns:
            List of video dicts with metrics
        """
        data = self._request(
            "POST",
            "/video/list/",
            params={
                "fields": "id,title,create_time,cover_image_url,share_url,like_count,comment_count,share_count,view_count"
            },
            json={"max_count": max_count},
        )

        return data.get("data", {}).get("videos", [])


class TikTokAPIError(Exception):
    """TikTok API error."""

    def __init__(self, message: str, code: str = None, response: dict = None):
        self.message = message
        self.code = code
        self.response = response or {}
        super().__init__(self.message)

    def is_retryable(self) -> bool:
        """Check if this error is retryable."""
        retryable_codes = [
            "rate_limit_exceeded",
            "service_unavailable",
            "timeout",
            "internal_error",
        ]
        return self.code in retryable_codes


# =============================================================================
# INDEED CLIENT
# =============================================================================

from .indeed_client import IndeedClient

_indeed_client = None


def get_indeed_client():
    global _indeed_client
    if _indeed_client is None:
        _indeed_client = IndeedClient()
    return _indeed_client


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_client_for_account(account_id: int):
    """
    Get appropriate platform client for an account.

    Args:
        account_id: Social account ID

    Returns:
        InstagramClient or TikTokClient instance
    """
    from .oauth_handler import get_oauth_token

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT platform, platform_user_id, platform_metadata
            FROM social_accounts WHERE id = %s
        """,
            (account_id,),
        )
        account = cur.fetchone()

        if not account:
            raise ValueError(f"Account {account_id} not found")

        # Get token
        token_data = get_oauth_token(account_id)
        if not token_data:
            raise ValueError(f"No token found for account {account_id}")

        if token_data["is_expired"]:
            raise ValueError(f"Token expired for account {account_id}")

        platform = account["platform"]
        access_token = token_data["access_token"]

        if platform == "instagram":
            return InstagramClient(access_token=access_token, ig_user_id=account["platform_user_id"])
        elif platform == "tiktok":
            return TikTokClient(access_token=access_token, open_id=account["platform_user_id"])
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    finally:
        cur.close()
        conn.close()


def log_api_call(
    platform: str,
    endpoint: str,
    account_id: int,
    success: bool,
    duration_ms: int,
    response: dict = None,
    error: str = None,
):
    """Log an API call to job_logs table."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO social_job_logs (
                job_type, status, account_id, error_message,
                platform_response, duration_ms, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
            (
                f"api_{endpoint}",
                "success" if success else "failed",
                account_id,
                error,
                Json(response) if response else None,
                duration_ms,
                Json({"platform": platform}),
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()
