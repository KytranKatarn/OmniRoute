"""
Indeed Employer API Client
==========================
Wrapper for posting recruitment videos to Indeed via the Employer API.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-30
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

INDEED_API_BASE = "https://apis.indeed.com/employer"


class IndeedClient:
    """Indeed Employer API client for posting recruitment video content."""

    def __init__(self):
        self.api_key = os.getenv("INDEED_API_KEY", "")
        self.employer_id = os.getenv("INDEED_EMPLOYER_ID", "")

    def is_configured(self) -> bool:
        """Return True if both API key and employer ID are set."""
        return bool(self.api_key and self.employer_id)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def post_video(self, video_path: str, caption: str, hashtags=None) -> dict:
        """
        Post a recruitment video to Indeed (two-step: upload then create post).

        Args:
            video_path: Local path to the video file
            caption: Post description/caption
            hashtags: Optional list of hashtag strings (# prepended if missing)

        Returns:
            Dict with success, post_id, post_url, platform — or error details
        """
        try:
            # Normalise hashtags
            tag_list = []
            if hashtags:
                for tag in hashtags:
                    tag_list.append(tag if tag.startswith("#") else f"#{tag}")

            # Step 1: Upload media file
            upload_url = f"{INDEED_API_BASE}/{self.employer_id}/media"
            with open(video_path, "rb") as video_file:
                upload_resp = requests.post(
                    upload_url,
                    headers=self._headers(),
                    files={"file": video_file},
                    timeout=120,
                )
            upload_resp.raise_for_status()
            media_id = upload_resp.json().get("mediaId") or upload_resp.json().get("id")

            # Step 2: Create post
            post_url = f"{INDEED_API_BASE}/{self.employer_id}/posts"
            payload = {
                "mediaId": media_id,
                "description": caption,
                "hashtags": tag_list,
            }
            post_resp = requests.post(
                post_url,
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            post_resp.raise_for_status()
            post_data = post_resp.json()

            post_id = post_data.get("postId") or post_data.get("id")
            post_link = post_data.get(
                "postUrl",
                f"https://www.indeed.com/employer/posts/{post_id}",
            )

            return {
                "success": True,
                "post_id": post_id,
                "post_url": post_link,
                "platform": "indeed",
            }

        except Exception as e:
            logger.error("Indeed post_video failed: %s", e)
            return {"success": False, "error": str(e), "platform": "indeed"}

    def get_post_stats(self, post_id: str) -> dict:
        """
        Retrieve stats for a published Indeed post.

        Args:
            post_id: Indeed post ID

        Returns:
            Dict with success, stats, platform — or error details
        """
        try:
            url = f"{INDEED_API_BASE}/{self.employer_id}/posts/{post_id}/stats"
            resp = requests.get(url, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            return {"success": True, "stats": resp.json(), "platform": "indeed"}

        except Exception as e:
            logger.error("Indeed get_post_stats failed for post %s: %s", post_id, e)
            return {"success": False, "error": str(e), "platform": "indeed"}
