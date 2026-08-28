"""
Social Media Analytics Aggregator
=================================
Cross-platform analytics normalization and aggregation.

Provides unified metrics view across Instagram and TikTok.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

import os
from database import _get_db_password
import logging
from datetime import datetime, timedelta
from typing import Dict, List

import psycopg2
from psycopg2.extras import RealDictCursor

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
# METRICS NORMALIZATION
# =============================================================================


class NormalizedMetrics:
    """Cross-platform metrics normalization."""

    # Instagram -> Normalized
    INSTAGRAM_MAPPING = {
        "impressions": "views",
        "reach": "reach",
        "engagement": "engagement",
        "likes": "likes",
        "comments": "comments",
        "saved": "saves",
        "shares": "shares",
    }

    # TikTok -> Normalized
    TIKTOK_MAPPING = {
        "view_count": "views",
        "like_count": "likes",
        "comment_count": "comments",
        "share_count": "shares",
    }

    @staticmethod
    def normalize_instagram(metrics: Dict) -> Dict:
        """Normalize Instagram metrics to standard format."""
        normalized = {}
        for ig_key, norm_key in NormalizedMetrics.INSTAGRAM_MAPPING.items():
            if ig_key in metrics:
                normalized[norm_key] = metrics[ig_key]
        return normalized

    @staticmethod
    def normalize_tiktok(metrics: Dict) -> Dict:
        """Normalize TikTok metrics to standard format."""
        normalized = {}
        for tt_key, norm_key in NormalizedMetrics.TIKTOK_MAPPING.items():
            if tt_key in metrics:
                normalized[norm_key] = metrics[tt_key]
        return normalized

    @staticmethod
    def calculate_engagement_rate(metrics: Dict, followers: int) -> float:
        """
        Calculate standard engagement rate.

        Formula: (likes + comments + shares) / followers * 100
        """
        if followers <= 0:
            return 0.0

        interactions = metrics.get("likes", 0) + metrics.get("comments", 0) + metrics.get("shares", 0)

        return round((interactions / followers) * 100, 2)


# =============================================================================
# AGGREGATION QUERIES
# =============================================================================


def get_analytics_overview(user_id: int, period: str = "30d") -> Dict:
    """
    Get analytics overview for a user.

    Args:
        user_id: User ID
        period: '7d', '30d', '90d'

    Returns:
        Dict with totals, by_platform, and trend data
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Parse period
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        start_date = datetime.now() - timedelta(days=days)

        # Get totals
        cur.execute(
            """
            SELECT
                COALESCE(SUM(r.views_count), 0) as total_views,
                COALESCE(SUM(r.likes_count), 0) as total_likes,
                COALESCE(SUM(r.comments_count), 0) as total_comments,
                COALESCE(SUM(r.shares_count), 0) as total_shares,
                COALESCE(SUM(r.saves_count), 0) as total_saves,
                COALESCE(AVG(r.engagement_rate), 0) as avg_engagement_rate,
                COUNT(DISTINCT r.post_id) as total_posts
            FROM social_post_results r
            JOIN social_posts p ON r.post_id = p.id
            WHERE p.user_id = %s
            AND r.status = 'published'
            AND r.published_at >= %s
        """,
            (user_id, start_date),
        )
        totals = cur.fetchone()

        # Get by platform
        cur.execute(
            """
            SELECT
                r.platform,
                COALESCE(SUM(r.views_count), 0) as views,
                COALESCE(SUM(r.likes_count), 0) as likes,
                COALESCE(SUM(r.comments_count), 0) as comments,
                COALESCE(SUM(r.shares_count), 0) as shares,
                COALESCE(AVG(r.engagement_rate), 0) as avg_engagement,
                COUNT(*) as post_count
            FROM social_post_results r
            JOIN social_posts p ON r.post_id = p.id
            WHERE p.user_id = %s
            AND r.status = 'published'
            AND r.published_at >= %s
            GROUP BY r.platform
        """,
            (user_id, start_date),
        )
        by_platform = {row["platform"]: dict(row) for row in cur.fetchall()}

        # Get daily trend
        cur.execute(
            """
            SELECT
                DATE(r.published_at) as date,
                COALESCE(SUM(r.views_count), 0) as views,
                COALESCE(SUM(r.likes_count), 0) as likes,
                COALESCE(SUM(r.comments_count), 0) as comments,
                COALESCE(SUM(r.shares_count), 0) as shares,
                COUNT(*) as posts
            FROM social_post_results r
            JOIN social_posts p ON r.post_id = p.id
            WHERE p.user_id = %s
            AND r.status = 'published'
            AND r.published_at >= %s
            GROUP BY DATE(r.published_at)
            ORDER BY date
        """,
            (user_id, start_date),
        )
        trend = [dict(row) for row in cur.fetchall()]

        # Convert dates to strings for JSON
        for item in trend:
            item["date"] = item["date"].isoformat()

        return {
            "period": period,
            "days": days,
            "totals": {
                "views": int(totals["total_views"]),
                "likes": int(totals["total_likes"]),
                "comments": int(totals["total_comments"]),
                "shares": int(totals["total_shares"]),
                "saves": int(totals["total_saves"]),
                "engagement_rate": float(totals["avg_engagement_rate"]),
                "posts": int(totals["total_posts"]),
            },
            "by_platform": by_platform,
            "trend": trend,
        }

    finally:
        cur.close()
        conn.close()


def get_top_posts(user_id: int, limit: int = 10, sort_by: str = "engagement") -> List[Dict]:
    """
    Get top performing posts.

    Args:
        user_id: User ID
        limit: Number of posts to return
        sort_by: 'engagement', 'views', 'likes'

    Returns:
        List of post dicts with metrics
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        order_column = {
            "engagement": "r.engagement_rate",
            "views": "r.views_count",
            "likes": "r.likes_count",
            "comments": "r.comments_count",
        }.get(sort_by, "r.engagement_rate")

        cur.execute(
            f"""
            SELECT
                p.id, p.content, p.media_urls, p.created_at,
                r.platform, r.platform_post_url,
                r.views_count, r.likes_count, r.comments_count,
                r.shares_count, r.saves_count, r.engagement_rate,
                r.published_at
            FROM social_posts p
            JOIN social_post_results r ON p.id = r.post_id
            WHERE p.user_id = %s
            AND r.status = 'published'
            ORDER BY {order_column} DESC NULLS LAST
            LIMIT %s
        """,
            (user_id, limit),
        )

        posts = []
        for row in cur.fetchall():
            post = dict(row)
            # Convert datetime to string
            if post.get("created_at"):
                post["created_at"] = post["created_at"].isoformat()
            if post.get("published_at"):
                post["published_at"] = post["published_at"].isoformat()
            posts.append(post)

        return posts

    finally:
        cur.close()
        conn.close()


def get_account_stats(user_id: int) -> List[Dict]:
    """
    Get stats for all connected accounts.

    Args:
        user_id: User ID

    Returns:
        List of account stats
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                a.id, a.platform, a.platform_username, a.account_name,
                a.profile_image_url, a.followers_count, a.following_count,
                a.posts_count, a.is_active, a.last_sync_at,
                COUNT(DISTINCT p.id) as archie_posts,
                COALESCE(SUM(r.views_count), 0) as total_views,
                COALESCE(SUM(r.likes_count), 0) as total_likes,
                COALESCE(AVG(r.engagement_rate), 0) as avg_engagement
            FROM social_accounts a
            LEFT JOIN social_post_results r ON a.id = r.account_id
            LEFT JOIN social_posts p ON r.post_id = p.id AND p.user_id = %s
            WHERE a.user_id = %s
            GROUP BY a.id
            ORDER BY a.platform, a.account_name
        """,
            (user_id, user_id),
        )

        accounts = []
        for row in cur.fetchall():
            account = dict(row)
            if account.get("last_sync_at"):
                account["last_sync_at"] = account["last_sync_at"].isoformat()
            accounts.append(account)

        return accounts

    finally:
        cur.close()
        conn.close()


def get_posting_frequency(user_id: int, days: int = 30) -> Dict:
    """
    Analyze posting frequency and optimal times.

    Args:
        user_id: User ID
        days: Days to analyze

    Returns:
        Dict with posting patterns
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        start_date = datetime.now() - timedelta(days=days)

        # Posts by day of week
        cur.execute(
            """
            SELECT
                EXTRACT(DOW FROM r.published_at) as day_of_week,
                COUNT(*) as post_count,
                COALESCE(AVG(r.engagement_rate), 0) as avg_engagement
            FROM social_post_results r
            JOIN social_posts p ON r.post_id = p.id
            WHERE p.user_id = %s
            AND r.status = 'published'
            AND r.published_at >= %s
            GROUP BY EXTRACT(DOW FROM r.published_at)
            ORDER BY day_of_week
        """,
            (user_id, start_date),
        )
        by_day = [dict(row) for row in cur.fetchall()]

        # Posts by hour
        cur.execute(
            """
            SELECT
                EXTRACT(HOUR FROM r.published_at) as hour,
                COUNT(*) as post_count,
                COALESCE(AVG(r.engagement_rate), 0) as avg_engagement
            FROM social_post_results r
            JOIN social_posts p ON r.post_id = p.id
            WHERE p.user_id = %s
            AND r.status = 'published'
            AND r.published_at >= %s
            GROUP BY EXTRACT(HOUR FROM r.published_at)
            ORDER BY hour
        """,
            (user_id, start_date),
        )
        by_hour = [dict(row) for row in cur.fetchall()]

        # Find best times
        best_day = max(by_day, key=lambda x: x["avg_engagement"]) if by_day else None
        best_hour = max(by_hour, key=lambda x: x["avg_engagement"]) if by_hour else None

        day_names = [
            "Sunday",
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
        ]

        return {
            "by_day_of_week": by_day,
            "by_hour": by_hour,
            "best_day": (
                {
                    "day": int(best_day["day_of_week"]) if best_day else None,
                    "name": (day_names[int(best_day["day_of_week"])] if best_day else None),
                    "avg_engagement": (float(best_day["avg_engagement"]) if best_day else 0),
                }
                if best_day
                else None
            ),
            "best_hour": (
                {
                    "hour": int(best_hour["hour"]) if best_hour else None,
                    "avg_engagement": (float(best_hour["avg_engagement"]) if best_hour else 0),
                }
                if best_hour
                else None
            ),
            "total_posts_analyzed": sum(d["post_count"] for d in by_day),
        }

    finally:
        cur.close()
        conn.close()


def get_comparison_with_previous(user_id: int, period: str = "30d") -> Dict:
    """
    Compare current period with previous period.

    Args:
        user_id: User ID
        period: '7d', '30d', '90d'

    Returns:
        Dict with current, previous, and change percentages
    """
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        current_start = datetime.now() - timedelta(days=days)
        previous_start = current_start - timedelta(days=days)

        def get_period_stats(start, end):
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(r.views_count), 0) as views,
                    COALESCE(SUM(r.likes_count), 0) as likes,
                    COALESCE(SUM(r.comments_count), 0) as comments,
                    COALESCE(AVG(r.engagement_rate), 0) as engagement,
                    COUNT(*) as posts
                FROM social_post_results r
                JOIN social_posts p ON r.post_id = p.id
                WHERE p.user_id = %s
                AND r.status = 'published'
                AND r.published_at >= %s
                AND r.published_at < %s
            """,
                (user_id, start, end),
            )
            return cur.fetchone()

        current = get_period_stats(current_start, datetime.now())
        previous = get_period_stats(previous_start, current_start)

        def calc_change(current_val, previous_val):
            if previous_val == 0:
                return 100.0 if current_val > 0 else 0.0
            return round(((current_val - previous_val) / previous_val) * 100, 1)

        return {
            "period": period,
            "current": dict(current),
            "previous": dict(previous),
            "changes": {
                "views": calc_change(current["views"], previous["views"]),
                "likes": calc_change(current["likes"], previous["likes"]),
                "comments": calc_change(current["comments"], previous["comments"]),
                "engagement": calc_change(current["engagement"], previous["engagement"]),
                "posts": calc_change(current["posts"], previous["posts"]),
            },
        }

    finally:
        cur.close()
        conn.close()
