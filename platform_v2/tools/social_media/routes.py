"""
Social Media Routes
===================
Social media command center for A.R.C.H.I.E. Business Tools.

Features:
- Multi-platform account management
- Content scheduling and queue
- Visual content calendar
- Campaign management
- Analytics dashboard
- Media library
- Template system
- AI content suggestions

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, date
import os
from database import _get_db_password
import json
import time
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# Import user context helpers
try:
    from services.user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


from tools.department_hq.services.department_dispatcher import dispatch_json

BRIDGE_AVAILABLE = True

# Create blueprint
social_media_bp = Blueprint(
    "social_media",
    __name__,
    url_prefix="/tools/social-media",
    template_folder="../../templates/tools",
)

# Platform configurations
PLATFORMS = {
    "facebook": {
        "name": "Facebook",
        "icon": "fab fa-facebook",
        "lucide_icon": "facebook",
        "color": "#1877F2",
        "features": ["posts", "images", "videos", "stories", "reels"],
    },
    "instagram": {
        "name": "Instagram",
        "icon": "fab fa-instagram",
        "lucide_icon": "instagram",
        "color": "#E4405F",
        "features": ["posts", "images", "videos", "stories", "reels", "carousels"],
    },
    "twitter": {
        "name": "Twitter/X",
        "icon": "fab fa-twitter",
        "lucide_icon": "twitter",
        "color": "#1DA1F2",
        "features": ["posts", "images", "videos", "threads"],
    },
    "linkedin": {
        "name": "LinkedIn",
        "icon": "fab fa-linkedin",
        "lucide_icon": "linkedin",
        "color": "#0A66C2",
        "features": ["posts", "images", "videos", "articles"],
    },
    "tiktok": {
        "name": "TikTok",
        "icon": "fab fa-tiktok",
        "lucide_icon": "clapperboard",
        "color": "#000000",
        "features": ["videos", "stories"],
    },
    "youtube": {
        "name": "YouTube",
        "icon": "fab fa-youtube",
        "lucide_icon": "youtube",
        "color": "#FF0000",
        "features": ["videos", "shorts", "community"],
    },
    "pinterest": {
        "name": "Pinterest",
        "icon": "fab fa-pinterest",
        "lucide_icon": "pin",
        "color": "#BD081C",
        "features": ["pins", "images", "videos"],
    },
}


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, timedelta):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


# ============================================================================
# MAIN PAGE
# ============================================================================


@social_media_bp.route("/")
@login_required
def index():
    """Main Social Media command center"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get connected accounts
        cur.execute(
            """
            SELECT * FROM social_accounts
            WHERE user_id = %s
            ORDER BY platform
        """,
            (current_user.id,),
        )
        accounts = cur.fetchall()

        # Get upcoming scheduled posts
        cur.execute(
            """
            SELECT p.*, array_agg(pr.platform) as target_platforms_actual
            FROM social_posts p
            LEFT JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s AND p.status = 'scheduled'
            AND p.scheduled_at > NOW()
            GROUP BY p.id
            ORDER BY p.scheduled_at
            LIMIT 10
        """,
            (current_user.id,),
        )
        scheduled_posts = cur.fetchall()

        # Get recent posts
        cur.execute(
            """
            SELECT p.*, array_agg(pr.platform) as posted_platforms
            FROM social_posts p
            LEFT JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s AND p.status = 'published'
            GROUP BY p.id
            ORDER BY p.published_at DESC
            LIMIT 10
        """,
            (current_user.id,),
        )
        recent_posts = cur.fetchall()

        # Get templates
        cur.execute(
            """
            SELECT * FROM social_templates
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY times_used DESC
            LIMIT 10
        """,
            (current_user.id,),
        )
        templates = cur.fetchall()

        # Calculate stats
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_active = TRUE) as active_accounts,
                COUNT(*) as total_accounts
            FROM social_accounts
            WHERE user_id = %s
        """,
            (current_user.id,),
        )
        account_stats = cur.fetchone()

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'draft') as drafts,
                COUNT(*) FILTER (WHERE status = 'scheduled') as scheduled,
                COUNT(*) FILTER (WHERE status = 'published') as published,
                COUNT(*) FILTER (WHERE status = 'published' AND published_at >= CURRENT_DATE - INTERVAL '7 days') as published_week
            FROM social_posts
            WHERE user_id = %s
        """,
            (current_user.id,),
        )
        post_stats = cur.fetchone()

        # Get total engagement
        cur.execute(
            """
            SELECT
                COALESCE(SUM(likes_count), 0) as total_likes,
                COALESCE(SUM(comments_count), 0) as total_comments,
                COALESCE(SUM(shares_count), 0) as total_shares,
                COALESCE(SUM(views_count), 0) as total_views
            FROM social_post_results pr
            JOIN social_posts p ON pr.post_id = p.id
            WHERE p.user_id = %s
        """,
            (current_user.id,),
        )
        engagement_stats = cur.fetchone()

        stats = {
            "active_accounts": account_stats["active_accounts"] or 0,
            "total_accounts": account_stats["total_accounts"] or 0,
            "drafts": post_stats["drafts"] or 0,
            "scheduled": post_stats["scheduled"] or 0,
            "published": post_stats["published"] or 0,
            "published_week": post_stats["published_week"] or 0,
            "total_likes": engagement_stats["total_likes"] or 0,
            "total_comments": engagement_stats["total_comments"] or 0,
            "total_shares": engagement_stats["total_shares"] or 0,
            "total_views": engagement_stats["total_views"] or 0,
        }

        return render_template(
            "tools/social_media.html",
            accounts=accounts,
            scheduled_posts=scheduled_posts,
            recent_posts=recent_posts,
            templates=templates,
            stats=stats,
            platforms=PLATFORMS,
        )

    except Exception as e:
        current_app.logger.error(f"Social media index error: {str(e)}")
        return render_template(
            "tools/social_media.html",
            accounts=[],
            scheduled_posts=[],
            recent_posts=[],
            templates=[],
            stats={},
            platforms=PLATFORMS,
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ACCOUNTS API
# ============================================================================


@social_media_bp.route("/api/accounts")
@login_required
def get_accounts():
    """Get all connected accounts"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM social_accounts
            WHERE user_id = %s
            ORDER BY platform, account_name
        """,
            (current_user.id,),
        )

        accounts = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "accounts": json.loads(json.dumps(accounts, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/accounts/<int:account_id>")
@login_required
def get_account(account_id):
    """Get a specific account"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM social_accounts
            WHERE id = %s AND user_id = %s
        """,
            (account_id, current_user.id),
        )

        account = cur.fetchone()

        if not account:
            return jsonify({"success": False, "error": "Account not found"}), 404

        return jsonify(
            {
                "success": True,
                "account": json.loads(json.dumps(account, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/accounts", methods=["POST"])
@login_required
def create_account():
    """Create/connect a new account"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_accounts (
                user_id, platform, platform_username, account_name,
                account_type, is_active, auto_post_enabled
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("platform"),
                data.get("platform_username"),
                data.get("account_name"),
                data.get("account_type", "profile"),
                data.get("is_active", True),
                data.get("auto_post_enabled", False),
            ),
        )

        account = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "account": json.loads(json.dumps(account, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/accounts/<int:account_id>", methods=["PUT"])
@login_required
def update_account(account_id):
    """Update an account"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE social_accounts SET
                platform_username = COALESCE(%s, platform_username),
                account_name = COALESCE(%s, account_name),
                account_type = COALESCE(%s, account_type),
                is_active = COALESCE(%s, is_active),
                auto_post_enabled = COALESCE(%s, auto_post_enabled),
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            (
                data.get("platform_username"),
                data.get("account_name"),
                data.get("account_type"),
                data.get("is_active"),
                data.get("auto_post_enabled"),
                account_id,
                current_user.id,
            ),
        )

        account = cur.fetchone()
        conn.commit()

        if not account:
            return jsonify({"success": False, "error": "Account not found"}), 404

        return jsonify(
            {
                "success": True,
                "account": json.loads(json.dumps(account, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/accounts/<int:account_id>", methods=["DELETE"])
@login_required
def delete_account(account_id):
    """Delete/disconnect an account"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM social_accounts
            WHERE id = %s AND user_id = %s
        """,
            (account_id, current_user.id),
        )

        deleted = cur.rowcount > 0
        conn.commit()

        if not deleted:
            return jsonify({"success": False, "error": "Account not found"}), 404

        return jsonify({"success": True, "message": "Account disconnected"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/accounts/<int:account_id>/toggle", methods=["POST"])
@login_required
def toggle_account(account_id):
    """Toggle account active status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE social_accounts SET
                is_active = NOT is_active,
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            (account_id, current_user.id),
        )

        account = cur.fetchone()
        conn.commit()

        if not account:
            return jsonify({"success": False, "error": "Account not found"}), 404

        return jsonify({"success": True, "is_active": account["is_active"]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# OAUTH API - Instagram & TikTok Authentication
# ============================================================================


@social_media_bp.route("/api/oauth/status")
@login_required
def get_oauth_status():
    """Get OAuth configuration status for all platforms."""
    try:
        from .oauth_handler import InstagramOAuth, TikTokOAuth

        instagram = InstagramOAuth()
        tiktok = TikTokOAuth()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get platform configs
        cur.execute("SELECT platform, enabled FROM social_platform_config")
        configs = {row["platform"]: row["enabled"] for row in cur.fetchall()}

        return jsonify(
            {
                "success": True,
                "platforms": {
                    "instagram": {
                        "configured": instagram.is_configured(),
                        "enabled": configs.get("instagram", False),
                        "name": "Instagram",
                    },
                    "tiktok": {
                        "configured": tiktok.is_configured(),
                        "enabled": configs.get("tiktok", False),
                        "name": "TikTok",
                    },
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/oauth/instagram/authorize")
@login_required
def instagram_authorize():
    """Get Instagram OAuth authorization URL."""
    try:
        from .oauth_handler import InstagramOAuth

        oauth = InstagramOAuth()
        if not oauth.is_configured():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Instagram OAuth not configured. Set INSTAGRAM_APP_ID, INSTAGRAM_APP_SECRET, INSTAGRAM_REDIRECT_URI in environment.",
                    }
                ),
                400,
            )

        auth_url, state = oauth.get_authorization_url()

        # Store state in session for CSRF validation
        from flask import session

        session["instagram_oauth_state"] = state

        return jsonify({"success": True, "auth_url": auth_url, "state": state})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/oauth/instagram/callback")
@login_required
def instagram_callback():
    """Handle Instagram OAuth callback."""

    try:
        from flask import session
        from .oauth_handler import InstagramOAuth, store_oauth_token, log_oauth_job

        start_time = time.time()

        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")

        if error:
            log_oauth_job("authorize", "failed", error_message=f"User denied: {error}")
            return (
                jsonify({"success": False, "error": f"Authorization denied: {error}"}),
                400,
            )

        if not code:
            return (
                jsonify({"success": False, "error": "No authorization code received"}),
                400,
            )

        # Validate state (CSRF protection)
        stored_state = session.get("instagram_oauth_state")
        if state != stored_state:
            log_oauth_job("authorize", "failed", error_message="Invalid state token")
            return jsonify({"success": False, "error": "Invalid state token"}), 400

        oauth = InstagramOAuth()

        # Exchange code for token
        token_data = oauth.exchange_code(code)
        short_token = token_data.get("access_token")

        # Get long-lived token
        long_token_data = oauth.get_long_lived_token(short_token)
        access_token = long_token_data.get("access_token")
        expires_in = long_token_data.get("expires_in", 5184000)  # Default 60 days

        # Get user profile
        profile = oauth.get_user_profile(access_token)

        # Create or update social account
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_accounts (
                user_id, platform, platform_user_id, platform_username,
                account_name, profile_image_url, followers_count,
                is_active, last_sync_at, platform_metadata
            ) VALUES (%s, 'instagram', %s, %s, %s, %s, %s, TRUE, NOW(), %s)
            ON CONFLICT (user_id, platform, platform_user_id) DO UPDATE SET
                platform_username = EXCLUDED.platform_username,
                profile_image_url = EXCLUDED.profile_image_url,
                followers_count = EXCLUDED.followers_count,
                is_active = TRUE,
                last_sync_at = NOW(),
                platform_metadata = EXCLUDED.platform_metadata,
                updated_at = NOW()
            RETURNING id
        """,
            (
                current_user.id,
                profile["platform_user_id"],
                profile["username"],
                f"@{profile['username']}",
                profile.get("profile_picture_url"),
                profile.get("followers_count", 0),
                json.dumps(
                    {
                        "page_id": profile.get("page_id"),
                        "media_count": profile.get("media_count"),
                    }
                ),
            ),
        )

        account_id = cur.fetchone()["id"]
        conn.commit()

        # Store encrypted token
        store_oauth_token(
            account_id=account_id,
            platform="instagram",
            access_token=access_token,
            expires_in=expires_in,
            scopes=oauth.SCOPES,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        log_oauth_job("authorize", "success", account_id=account_id, duration_ms=duration_ms)

        # Clear session state
        session.pop("instagram_oauth_state", None)

        return jsonify(
            {
                "success": True,
                "account_id": account_id,
                "username": profile["username"],
                "message": f'Successfully connected Instagram account @{profile["username"]}',
            }
        )

    except Exception as e:
        log_oauth_job("authorize", "failed", error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/oauth/tiktok/authorize")
@login_required
def tiktok_authorize():
    """Get TikTok OAuth authorization URL."""
    try:
        from .oauth_handler import TikTokOAuth

        oauth = TikTokOAuth()
        if not oauth.is_configured():
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "TikTok OAuth not configured. Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI in environment.",
                    }
                ),
                400,
            )

        auth_url, state = oauth.get_authorization_url()

        from flask import session

        session["tiktok_oauth_state"] = state

        return jsonify({"success": True, "auth_url": auth_url, "state": state})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/oauth/tiktok/callback")
@login_required
def tiktok_callback():
    """Handle TikTok OAuth callback."""

    try:
        from flask import session
        from .oauth_handler import TikTokOAuth, store_oauth_token, log_oauth_job

        start_time = time.time()

        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")

        if error:
            log_oauth_job("authorize", "failed", error_message=f"User denied: {error}")
            return (
                jsonify({"success": False, "error": f"Authorization denied: {error}"}),
                400,
            )

        if not code:
            return (
                jsonify({"success": False, "error": "No authorization code received"}),
                400,
            )

        stored_state = session.get("tiktok_oauth_state")
        if state != stored_state:
            log_oauth_job("authorize", "failed", error_message="Invalid state token")
            return jsonify({"success": False, "error": "Invalid state token"}), 400

        oauth = TikTokOAuth()

        # Exchange code for tokens
        token_data = oauth.exchange_code(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 86400)  # Default 24 hours

        # Get user profile
        profile = oauth.get_user_profile(access_token)

        # Create or update social account
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_accounts (
                user_id, platform, platform_user_id, platform_username,
                account_name, profile_image_url, followers_count,
                is_active, last_sync_at
            ) VALUES (%s, 'tiktok', %s, %s, %s, %s, %s, TRUE, NOW())
            ON CONFLICT (user_id, platform, platform_user_id) DO UPDATE SET
                platform_username = EXCLUDED.platform_username,
                profile_image_url = EXCLUDED.profile_image_url,
                followers_count = EXCLUDED.followers_count,
                is_active = TRUE,
                last_sync_at = NOW(),
                updated_at = NOW()
            RETURNING id
        """,
            (
                current_user.id,
                profile["platform_user_id"],
                profile["username"],
                f"@{profile['username']}",
                profile.get("profile_picture_url"),
                profile.get("followers_count", 0),
            ),
        )

        account_id = cur.fetchone()["id"]
        conn.commit()

        # Store encrypted tokens
        store_oauth_token(
            account_id=account_id,
            platform="tiktok",
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scopes=oauth.SCOPES,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        log_oauth_job("authorize", "success", account_id=account_id, duration_ms=duration_ms)

        session.pop("tiktok_oauth_state", None)

        return jsonify(
            {
                "success": True,
                "account_id": account_id,
                "username": profile["username"],
                "message": f'Successfully connected TikTok account @{profile["username"]}',
            }
        )

    except Exception as e:
        log_oauth_job("authorize", "failed", error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/oauth/refresh/<int:account_id>", methods=["POST"])
@login_required
def refresh_oauth_token(account_id):
    """Refresh OAuth token for an account."""

    try:
        from .oauth_handler import (
            get_oauth_token,
            store_oauth_token,
            log_oauth_job,
            InstagramOAuth,
            TikTokOAuth,
        )

        start_time = time.time()

        # Get current token
        token_data = get_oauth_token(account_id)
        if not token_data:
            return (
                jsonify({"success": False, "error": "No token found for account"}),
                404,
            )

        platform = token_data["platform"]
        current_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")

        new_token_data = None

        if platform == "instagram":
            oauth = InstagramOAuth()
            new_token_data = oauth.refresh_token(current_token)
        elif platform == "tiktok":
            if not refresh_token:
                return (
                    jsonify({"success": False, "error": "No refresh token available"}),
                    400,
                )
            oauth = TikTokOAuth()
            new_token_data = oauth.refresh_token(refresh_token)
        else:
            return (
                jsonify({"success": False, "error": f"Unsupported platform: {platform}"}),
                400,
            )

        # Store new token
        store_oauth_token(
            account_id=account_id,
            platform=platform,
            access_token=new_token_data.get("access_token"),
            refresh_token=new_token_data.get("refresh_token", refresh_token),
            expires_in=new_token_data.get("expires_in"),
        )

        duration_ms = int((time.time() - start_time) * 1000)
        log_oauth_job("refresh_token", "success", account_id=account_id, duration_ms=duration_ms)

        return jsonify(
            {
                "success": True,
                "message": "Token refreshed successfully",
                "expires_in": new_token_data.get("expires_in"),
            }
        )

    except Exception as e:
        log_oauth_job("refresh_token", "failed", account_id=account_id, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/oauth/revoke/<int:account_id>", methods=["DELETE"])
@login_required
def revoke_oauth_token(account_id):
    """Revoke OAuth token and disconnect account."""
    try:
        from .oauth_handler import delete_oauth_token, log_oauth_job

        # Delete token
        delete_oauth_token(account_id)

        # Deactivate account
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE social_accounts
            SET is_active = FALSE, updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """,
            (account_id, current_user.id),
        )

        conn.commit()

        log_oauth_job("revoke", "success", account_id=account_id)

        return jsonify({"success": True, "message": "Account disconnected successfully"})

    except Exception as e:
        log_oauth_job("revoke", "failed", account_id=account_id, error_message=str(e))
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/oauth/tokens/expiring")
@login_required
def get_expiring_tokens():
    """Get tokens expiring soon (for admin dashboard)."""
    try:
        from .oauth_handler import get_expiring_tokens as fetch_expiring

        days = request.args.get("days", 7, type=int)
        tokens = fetch_expiring(days)

        return jsonify(
            {
                "success": True,
                "count": len(tokens),
                "tokens": [dict(t) for t in tokens],
            },
            default=json_serial,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# POSTS API
# ============================================================================


@social_media_bp.route("/api/posts")
@login_required
def get_posts():
    """Get all posts with optional filters"""
    try:
        status = request.args.get("status", "")
        platform = request.args.get("platform", "")
        limit = request.args.get("limit", 50)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT p.*,
                   array_agg(DISTINCT pr.platform) FILTER (WHERE pr.platform IS NOT NULL) as posted_platforms,
                   COALESCE(SUM(pr.likes_count), 0) as total_likes,
                   COALESCE(SUM(pr.comments_count), 0) as total_comments
            FROM social_posts p
            LEFT JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s
        """
        params = [current_user.id]

        if status:
            query += " AND p.status = %s"
            params.append(status)

        if platform:
            query += " AND %s = ANY(p.target_platforms)"
            params.append(platform)

        query += " GROUP BY p.id ORDER BY COALESCE(p.scheduled_at, p.created_at) DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        posts = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "posts": json.loads(json.dumps(posts, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts/<int:post_id>")
@login_required
def get_post(post_id):
    """Get a specific post with results"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM social_posts
            WHERE id = %s AND user_id = %s
        """,
            (post_id, current_user.id),
        )
        post = cur.fetchone()

        if not post:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Post not found"}), 404

        # Get platform results
        cur.execute(
            """
            SELECT pr.*, sa.account_name, sa.platform_username
            FROM social_post_results pr
            JOIN social_accounts sa ON pr.account_id = sa.id
            WHERE pr.post_id = %s
        """,
            (post_id,),
        )
        results = cur.fetchall()

        post["results"] = results

        return jsonify({"success": True, "post": json.loads(json.dumps(post, default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts", methods=["POST"])
@login_required
def create_post():
    """Create a new post"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_posts (
                user_id, content, media_urls, media_type, hashtags, mentions,
                link_url, target_platforms, status, scheduled_at, category, tags,
                ai_generated, campaign_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("content"),
                json.dumps(data.get("media_urls", [])),
                data.get("media_type"),
                data.get("hashtags", []),
                data.get("mentions", []),
                data.get("link_url"),
                data.get("target_platforms", []),
                data.get("status", "draft"),
                data.get("scheduled_at"),
                data.get("category"),
                data.get("tags", []),
                data.get("ai_generated", False),
                data.get("campaign_id"),
            ),
        )

        post = cur.fetchone()
        conn.commit()

        # If scheduled, add to queue
        if post["status"] == "scheduled" and post["scheduled_at"]:
            for platform in data.get("target_platforms", []):
                # Get the account for this platform
                cur.execute(
                    """
                    SELECT id FROM social_accounts
                    WHERE user_id = %s AND platform = %s AND is_active = TRUE
                    LIMIT 1
                """,
                    (current_user.id, platform),
                )
                account = cur.fetchone()

                if account:
                    cur.execute(
                        """
                        INSERT INTO social_media_queue (post_id, account_id, scheduled_time, status)
                        VALUES (%s, %s, %s, 'pending')
                    """,
                        (post["id"], account["id"], post["scheduled_at"]),
                    )

            conn.commit()

        return jsonify({"success": True, "post": json.loads(json.dumps(post, default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts/<int:post_id>", methods=["PUT"])
@login_required
def update_post(post_id):
    """Update a post"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE social_posts SET
                content = COALESCE(%s, content),
                media_urls = COALESCE(%s, media_urls),
                media_type = COALESCE(%s, media_type),
                hashtags = COALESCE(%s, hashtags),
                mentions = COALESCE(%s, mentions),
                link_url = COALESCE(%s, link_url),
                target_platforms = COALESCE(%s, target_platforms),
                status = COALESCE(%s, status),
                scheduled_at = COALESCE(%s, scheduled_at),
                category = COALESCE(%s, category),
                tags = COALESCE(%s, tags),
                campaign_id = COALESCE(%s, campaign_id),
                updated_at = NOW()
            WHERE id = %s AND user_id = %s
            RETURNING *
        """,
            (
                data.get("content"),
                json.dumps(data.get("media_urls")) if data.get("media_urls") else None,
                data.get("media_type"),
                data.get("hashtags"),
                data.get("mentions"),
                data.get("link_url"),
                data.get("target_platforms"),
                data.get("status"),
                data.get("scheduled_at"),
                data.get("category"),
                data.get("tags"),
                data.get("campaign_id"),
                post_id,
                current_user.id,
            ),
        )

        post = cur.fetchone()
        conn.commit()

        if not post:
            return jsonify({"success": False, "error": "Post not found"}), 404

        return jsonify({"success": True, "post": json.loads(json.dumps(post, default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts/<int:post_id>", methods=["DELETE"])
@login_required
def delete_post(post_id):
    """Delete a post"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM social_posts
            WHERE id = %s AND user_id = %s
        """,
            (post_id, current_user.id),
        )

        deleted = cur.rowcount > 0
        conn.commit()

        if not deleted:
            return jsonify({"success": False, "error": "Post not found"}), 404

        return jsonify({"success": True, "message": "Post deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts/<int:post_id>/publish", methods=["POST"])
@login_required
def publish_post(post_id):
    """Publish a post immediately to connected platforms."""
    try:
        from .social_worker import trigger_immediate_post

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the post
        cur.execute(
            """
            SELECT * FROM social_posts
            WHERE id = %s AND user_id = %s
        """,
            (post_id, current_user.id),
        )
        post = cur.fetchone()

        if not post:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Post not found"}), 404

        # Check for connected accounts
        target_platforms = post["target_platforms"] or []
        if not target_platforms:
            return (
                jsonify({"success": False, "error": "No target platforms specified"}),
                400,
            )

        # Get active accounts for target platforms
        cur.execute(
            """
            SELECT id, platform FROM social_accounts
            WHERE user_id = %s AND platform = ANY(%s) AND is_active = TRUE
        """,
            (current_user.id, target_platforms),
        )
        accounts = cur.fetchall()

        if not accounts:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No connected accounts for target platforms. Connect an account first.",
                    }
                ),
                400,
            )

        # Create queue entries for each account
        queue_ids = []
        for account in accounts:
            cur.execute(
                """
                INSERT INTO social_media_queue (
                    post_id, account_id, scheduled_time, status, priority
                ) VALUES (%s, %s, NOW(), 'pending', 10)
                ON CONFLICT DO NOTHING
                RETURNING id
            """,
                (post_id, account["id"]),
            )
            result = cur.fetchone()
            if result:
                queue_ids.append(result["id"])

        # Update post status to publishing
        cur.execute(
            """
            UPDATE social_posts SET status = 'publishing', updated_at = NOW()
            WHERE id = %s
        """,
            (post_id,),
        )

        conn.commit()

        # Trigger immediate processing
        result = trigger_immediate_post(post_id)

        return jsonify(
            {
                "success": result.get("success", False),
                "message": ("Post queued for publishing" if result.get("success") else "Publishing started"),
                "queue_ids": queue_ids,
                "results": result.get("results", []),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts/<int:post_id>/schedule", methods=["POST"])
@login_required
def schedule_post(post_id):
    """Schedule a post for future publishing."""
    try:
        data = request.get_json() or {}
        scheduled_at = data.get("scheduled_at")

        if not scheduled_at:
            return jsonify({"success": False, "error": "scheduled_at is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get the post
        cur.execute(
            """
            SELECT * FROM social_posts
            WHERE id = %s AND user_id = %s
        """,
            (post_id, current_user.id),
        )
        post = cur.fetchone()

        if not post:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Post not found"}), 404

        target_platforms = post["target_platforms"] or []

        # Get active accounts
        cur.execute(
            """
            SELECT id, platform FROM social_accounts
            WHERE user_id = %s AND platform = ANY(%s) AND is_active = TRUE
        """,
            (current_user.id, target_platforms),
        )
        accounts = cur.fetchall()

        if not accounts:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "No connected accounts for target platforms",
                    }
                ),
                400,
            )

        # Update post
        cur.execute(
            """
            UPDATE social_posts
            SET status = 'scheduled', scheduled_at = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (scheduled_at, post_id),
        )
        updated_post = cur.fetchone()

        # Create queue entries
        queue_ids = []
        for account in accounts:
            cur.execute(
                """
                INSERT INTO social_media_queue (
                    post_id, account_id, scheduled_time, status, priority
                ) VALUES (%s, %s, %s, 'pending', 5)
                ON CONFLICT DO NOTHING
                RETURNING id
            """,
                (post_id, account["id"], scheduled_at),
            )
            result = cur.fetchone()
            if result:
                queue_ids.append(result["id"])

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Post scheduled for {scheduled_at}",
                "queue_ids": queue_ids,
                "post": json.loads(json.dumps(updated_post, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/posts/<int:post_id>/status")
@login_required
def get_post_publish_status(post_id):
    """Get publishing status for a post across all platforms."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get post results
        cur.execute(
            """
            SELECT r.platform, r.status, r.platform_post_id, r.platform_post_url,
                   r.error_message, r.published_at,
                   a.platform_username, a.account_name
            FROM social_post_results r
            JOIN social_accounts a ON r.account_id = a.id
            WHERE r.post_id = %s
        """,
            (post_id,),
        )
        results = cur.fetchall()

        # Get queue status
        cur.execute(
            """
            SELECT q.id, q.status, q.attempts, q.error_message,
                   q.scheduled_time, q.next_retry_at, a.platform
            FROM social_media_queue q
            JOIN social_accounts a ON q.account_id = a.id
            WHERE q.post_id = %s
        """,
            (post_id,),
        )
        queue_items = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "results": json.loads(json.dumps(results, default=json_serial)),
                "queue": json.loads(json.dumps(queue_items, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# QUEUE MANAGEMENT API
# ============================================================================


@social_media_bp.route("/api/queue/status")
@login_required
def get_queue_status():
    """Get queue status summary."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE q.status = 'pending') as pending,
                COUNT(*) FILTER (WHERE q.status = 'processing') as processing,
                COUNT(*) FILTER (WHERE q.status = 'failed') as failed,
                COUNT(*) FILTER (WHERE q.status = 'completed' AND q.processed_at::date = CURRENT_DATE) as completed_today
            FROM social_media_queue q
            JOIN social_posts p ON q.post_id = p.id
            WHERE p.user_id = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        return jsonify({"success": True, "stats": dict(stats) if stats else {}})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/queue/failed")
@login_required
def get_failed_jobs():
    """Get failed queue jobs."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT q.*, p.content, a.platform, a.platform_username
            FROM social_media_queue q
            JOIN social_posts p ON q.post_id = p.id
            JOIN social_accounts a ON q.account_id = a.id
            WHERE p.user_id = %s AND q.status = 'failed'
            ORDER BY q.processed_at DESC
            LIMIT 50
        """,
            (current_user.id,),
        )
        jobs = cur.fetchall()

        return jsonify({"success": True, "jobs": json.loads(json.dumps(jobs, default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/queue/<int:queue_id>/retry", methods=["POST"])
@login_required
def retry_queue_job(queue_id):
    """Retry a failed queue job."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute(
            """
            SELECT q.* FROM social_media_queue q
            JOIN social_posts p ON q.post_id = p.id
            WHERE q.id = %s AND p.user_id = %s
        """,
            (queue_id, current_user.id),
        )
        job = cur.fetchone()

        if not job:
            return jsonify({"success": False, "error": "Job not found"}), 404

        # Reset job for retry
        cur.execute(
            """
            UPDATE social_media_queue
            SET status = 'pending',
                attempts = 0,
                error_message = NULL,
                next_retry_at = NULL,
                scheduled_time = NOW()
            WHERE id = %s
        """,
            (queue_id,),
        )

        conn.commit()

        return jsonify({"success": True, "message": "Job requeued for retry"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/queue/<int:queue_id>/cancel", methods=["DELETE"])
@login_required
def cancel_queue_job(queue_id):
    """Cancel a pending queue job."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM social_media_queue q
            USING social_posts p
            WHERE q.post_id = p.id
            AND q.id = %s AND p.user_id = %s
            AND q.status IN ('pending', 'failed')
            RETURNING q.id
        """,
            (queue_id, current_user.id),
        )

        deleted = cur.fetchone()
        conn.commit()

        if not deleted:
            return (
                jsonify({"success": False, "error": "Job not found or cannot be cancelled"}),
                404,
            )

        return jsonify({"success": True, "message": "Job cancelled"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# TEMPLATES API
# ============================================================================


@social_media_bp.route("/api/templates")
@login_required
def get_templates():
    """Get all templates"""
    try:
        category = request.args.get("category", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT * FROM social_templates
            WHERE user_id = %s AND is_active = TRUE
        """
        params = [current_user.id]

        if category:
            query += " AND category = %s"
            params.append(category)

        query += " ORDER BY times_used DESC, name"

        cur.execute(query, params)
        templates = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "templates": json.loads(json.dumps(templates, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/templates", methods=["POST"])
@login_required
def create_template():
    """Create a new template"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_templates (
                user_id, name, description, content_template,
                media_urls, default_hashtags, category, platforms, post_type
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("name"),
                data.get("description"),
                data.get("content_template"),
                json.dumps(data.get("media_urls", [])),
                data.get("default_hashtags", []),
                data.get("category"),
                data.get("platforms", []),
                data.get("post_type"),
            ),
        )

        template = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "template": json.loads(json.dumps(template, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/templates/<int:template_id>/use", methods=["POST"])
@login_required
def use_template(template_id):
    """Use a template to create a post draft"""
    try:
        data = request.get_json()
        variables = data.get("variables", {})

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get template
        cur.execute(
            """
            SELECT * FROM social_templates
            WHERE id = %s AND user_id = %s
        """,
            (template_id, current_user.id),
        )
        template = cur.fetchone()

        if not template:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Template not found"}), 404

        # Process template content with variables
        content = template["content_template"]
        for key, value in variables.items():
            content = content.replace("{{" + key + "}}", str(value))

        # Create draft post
        cur.execute(
            """
            INSERT INTO social_posts (
                user_id, content, media_urls, hashtags,
                target_platforms, status, category
            ) VALUES (%s, %s, %s, %s, %s, 'draft', %s)
            RETURNING *
        """,
            (
                current_user.id,
                content,
                template["media_urls"],
                template["default_hashtags"],
                template["platforms"],
                template["category"],
            ),
        )
        post = cur.fetchone()

        # Update template usage
        cur.execute(
            """
            UPDATE social_templates SET
                times_used = times_used + 1,
                last_used_at = NOW()
            WHERE id = %s
        """,
            (template_id,),
        )

        conn.commit()

        return jsonify({"success": True, "post": json.loads(json.dumps(post, default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CALENDAR API
# ============================================================================


@social_media_bp.route("/api/calendar")
@login_required
def get_calendar_events():
    """Get calendar events for date range"""
    try:
        start = request.args.get("start")
        end = request.args.get("end")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get scheduled posts
        cur.execute(
            """
            SELECT
                p.id,
                p.content,
                p.scheduled_at as start,
                p.target_platforms,
                p.status,
                'post' as event_type,
                CASE p.status
                    WHEN 'scheduled' THEN '#6366f1'
                    WHEN 'published' THEN '#10b981'
                    WHEN 'draft' THEN '#9ca3af'
                    ELSE '#f59e0b'
                END as color
            FROM social_posts p
            WHERE p.user_id = %s
            AND p.scheduled_at IS NOT NULL
            AND p.scheduled_at BETWEEN %s AND %s
        """,
            (current_user.id, start, end),
        )
        posts = cur.fetchall()

        # Get calendar events
        cur.execute(
            """
            SELECT
                ce.id,
                ce.title,
                ce.event_date as start,
                ce.event_type,
                ce.color,
                ce.all_day,
                ce.description
            FROM social_calendar_events ce
            WHERE ce.user_id = %s
            AND ce.event_date BETWEEN %s AND %s
        """,
            (current_user.id, start, end),
        )
        events = cur.fetchall()

        # Combine and format
        all_events = []
        for post in posts:
            all_events.append(
                {
                    "id": f"post_{post['id']}",
                    "title": ((post["content"][:50] + "...") if len(post["content"] or "") > 50 else post["content"]),
                    "start": post["start"].isoformat() if post["start"] else None,
                    "color": post["color"],
                    "extendedProps": {
                        "type": "post",
                        "post_id": post["id"],
                        "platforms": post["target_platforms"],
                        "status": post["status"],
                    },
                }
            )

        for event in events:
            all_events.append(
                {
                    "id": f"event_{event['id']}",
                    "title": event["title"],
                    "start": event["start"].isoformat() if event["start"] else None,
                    "color": event["color"],
                    "allDay": event["all_day"],
                    "extendedProps": {
                        "type": event["event_type"],
                        "description": event["description"],
                    },
                }
            )

        return jsonify({"success": True, "events": all_events})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CAMPAIGNS API
# ============================================================================


@social_media_bp.route("/api/campaigns")
@login_required
def get_campaigns():
    """Get all campaigns"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT c.*,
                   COUNT(p.id) as post_count,
                   COUNT(p.id) FILTER (WHERE p.status = 'published') as published_count
            FROM social_campaigns c
            LEFT JOIN social_posts p ON p.campaign_id = c.id
            WHERE c.user_id = %s
            GROUP BY c.id
            ORDER BY c.start_date DESC NULLS LAST
        """,
            (current_user.id,),
        )

        campaigns = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "campaigns": json.loads(json.dumps(campaigns, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/campaigns", methods=["POST"])
@login_required
def create_campaign():
    """Create a new campaign"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_campaigns (
                user_id, name, description, start_date, end_date,
                status, goal_type, target_reach, target_engagement, color
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("name"),
                data.get("description"),
                data.get("start_date"),
                data.get("end_date"),
                data.get("status", "draft"),
                data.get("goal_type"),
                data.get("target_reach"),
                data.get("target_engagement"),
                data.get("color", "#10b981"),
            ),
        )

        campaign = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "campaign": json.loads(json.dumps(campaign, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ANALYTICS API
# ============================================================================


@social_media_bp.route("/api/analytics")
@login_required
def get_analytics():
    """Get analytics overview"""
    try:
        period = request.args.get("period", "7d")

        # Calculate date range
        if period == "7d":
            start_date = date.today() - timedelta(days=7)
        elif period == "30d":
            start_date = date.today() - timedelta(days=30)
        elif period == "90d":
            start_date = date.today() - timedelta(days=90)
        else:
            start_date = date.today() - timedelta(days=7)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get overall stats
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT p.id) as total_posts,
                COALESCE(SUM(pr.likes_count), 0) as total_likes,
                COALESCE(SUM(pr.comments_count), 0) as total_comments,
                COALESCE(SUM(pr.shares_count), 0) as total_shares,
                COALESCE(SUM(pr.views_count), 0) as total_views,
                COALESCE(SUM(pr.reach), 0) as total_reach,
                COALESCE(SUM(pr.impressions), 0) as total_impressions
            FROM social_posts p
            JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s
            AND p.published_at >= %s
        """,
            (current_user.id, start_date),
        )
        overall = cur.fetchone()

        # Get per-platform stats
        cur.execute(
            """
            SELECT
                pr.platform,
                COUNT(DISTINCT p.id) as posts,
                COALESCE(SUM(pr.likes_count), 0) as likes,
                COALESCE(SUM(pr.comments_count), 0) as comments,
                COALESCE(SUM(pr.shares_count), 0) as shares,
                COALESCE(AVG(pr.engagement_rate), 0) as avg_engagement
            FROM social_posts p
            JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s
            AND p.published_at >= %s
            GROUP BY pr.platform
            ORDER BY posts DESC
        """,
            (current_user.id, start_date),
        )
        by_platform = cur.fetchall()

        # Get daily trend
        cur.execute(
            """
            SELECT
                p.published_at::date as date,
                COUNT(DISTINCT p.id) as posts,
                COALESCE(SUM(pr.likes_count), 0) as likes,
                COALESCE(SUM(pr.views_count), 0) as views
            FROM social_posts p
            JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s
            AND p.published_at >= %s
            GROUP BY p.published_at::date
            ORDER BY date
        """,
            (current_user.id, start_date),
        )
        daily_trend = cur.fetchall()

        # Get top posts
        cur.execute(
            """
            SELECT
                p.id, p.content, p.published_at,
                COALESCE(SUM(pr.likes_count), 0) as likes,
                COALESCE(SUM(pr.comments_count), 0) as comments,
                COALESCE(SUM(pr.views_count), 0) as views,
                array_agg(DISTINCT pr.platform) as platforms
            FROM social_posts p
            JOIN social_post_results pr ON p.id = pr.post_id
            WHERE p.user_id = %s
            AND p.status = 'published'
            GROUP BY p.id
            ORDER BY likes + comments DESC
            LIMIT 5
        """,
            (current_user.id,),
        )
        top_posts = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "analytics": {
                    "overall": json.loads(json.dumps(overall, default=json_serial)),
                    "by_platform": json.loads(json.dumps(by_platform, default=json_serial)),
                    "daily_trend": json.loads(json.dumps(daily_trend, default=json_serial)),
                    "top_posts": json.loads(json.dumps(top_posts, default=json_serial)),
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/analytics/overview")
@login_required
def get_analytics_overview():
    """Get enhanced analytics overview using aggregator."""
    try:
        from .analytics_aggregator import get_analytics_overview as fetch_overview

        period = request.args.get("period", "30d")
        data = fetch_overview(current_user.id, period)

        return jsonify({"success": True, "analytics": data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/analytics/top-posts")
@login_required
def get_analytics_top_posts():
    """Get top performing posts."""
    try:
        from .analytics_aggregator import get_top_posts

        limit = request.args.get("limit", 10, type=int)
        sort_by = request.args.get("sort", "engagement")
        posts = get_top_posts(current_user.id, limit, sort_by)

        return jsonify({"success": True, "posts": posts})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/analytics/accounts")
@login_required
def get_analytics_accounts():
    """Get stats for all connected accounts."""
    try:
        from .analytics_aggregator import get_account_stats

        accounts = get_account_stats(current_user.id)

        return jsonify({"success": True, "accounts": accounts})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/analytics/frequency")
@login_required
def get_analytics_frequency():
    """Analyze posting frequency and optimal times."""
    try:
        from .analytics_aggregator import get_posting_frequency

        days = request.args.get("days", 30, type=int)
        data = get_posting_frequency(current_user.id, days)

        return jsonify({"success": True, "frequency": data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/analytics/compare")
@login_required
def get_analytics_comparison():
    """Compare current period with previous period."""
    try:
        from .analytics_aggregator import get_comparison_with_previous

        period = request.args.get("period", "30d")
        data = get_comparison_with_previous(current_user.id, period)

        return jsonify({"success": True, "comparison": data})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/analytics/refresh", methods=["POST"])
@login_required
def refresh_analytics():
    """Trigger immediate analytics refresh for all accounts."""
    try:
        from .social_worker import fetch_post_analytics

        result = fetch_post_analytics()

        return jsonify(
            {
                "success": True,
                "message": f"Updated metrics for {result.get('updated', 0)} posts",
                "updated": result.get("updated", 0),
                "errors": result.get("errors", []),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# MEDIA LIBRARY API
# ============================================================================


@social_media_bp.route("/api/media")
@login_required
def get_media():
    """Get media library items"""
    try:
        file_type = request.args.get("type", "")
        folder = request.args.get("folder", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT * FROM social_media_library
            WHERE user_id = %s
        """
        params = [current_user.id]

        if file_type:
            query += " AND file_type = %s"
            params.append(file_type)

        if folder:
            query += " AND folder = %s"
            params.append(folder)

        query += " ORDER BY created_at DESC"

        cur.execute(query, params)
        media = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "media": json.loads(json.dumps(media, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/media", methods=["POST"])
@login_required
def upload_media():
    """Add media to library"""
    try:
        data = request.get_json()
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO social_media_library (
                user_id, filename, file_url, file_type, file_size,
                mime_type, width, height, duration, alt_text, tags, folder
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data.get("filename"),
                data.get("file_url"),
                data.get("file_type"),
                data.get("file_size"),
                data.get("mime_type"),
                data.get("width"),
                data.get("height"),
                data.get("duration"),
                data.get("alt_text"),
                data.get("tags", []),
                data.get("folder"),
            ),
        )

        media = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "media": json.loads(json.dumps(media, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# AI SUGGESTIONS API
# ============================================================================


@social_media_bp.route("/api/ai/suggest", methods=["POST"])
@login_required
def ai_suggest_content():
    """Get AI content suggestions"""
    try:
        data = request.get_json()
        topic = data.get("topic", "")
        platform = data.get("platform", "general")
        tone = data.get("tone", "professional")

        if not topic:
            return jsonify({"success": False, "error": "Topic is required"}), 400

        # Build prompt for AI content suggestions
        prompt = f"""Generate 3 different social media post suggestions about: {topic}

Platform: {platform}
Tone: {tone}

For each suggestion, provide:
1. The post content (optimized for {platform})
2. 3-5 relevant hashtags
3. Post type (promotional, engagement, educational, or inspirational)

Format as JSON array with objects containing: content, hashtags (array), type"""

        # Call DHQ dispatcher (ADR-013)
        try:
            result = dispatch_json(
                capability="creative",
                prompt=prompt,
                module_id="social_media",
                system_prompt=f"You are a social media expert. Create engaging {platform} posts. Return only valid JSON array.",
            )
            ai_response = result.get("response", "") if isinstance(result, dict) else str(result or "")
            if ai_response:
                try:
                    import re

                    json_match = re.search(r"\[.*\]", ai_response, re.DOTALL)
                    if json_match:
                        suggestions = json.loads(json_match.group())
                        return jsonify({"success": True, "suggestions": suggestions})
                except json.JSONDecodeError:
                    logger.warning("Could not parse AI response as JSON, returning raw")
                return jsonify(
                    {
                        "success": True,
                        "suggestions": [
                            {
                                "content": ai_response,
                                "hashtags": [topic.replace(" ", "")],
                                "type": "general",
                            }
                        ],
                    }
                )
        except Exception as ai_error:
            logger.warning(f"dispatch_json call failed: {ai_error}")

        # Fallback suggestions when AI not available
        suggestions = [
            {
                "content": f"Exciting news! We're thrilled to share our latest update on {topic}. Stay tuned for more! #Innovation #Growth",
                "hashtags": ["Innovation", "Growth", topic.replace(" ", "")],
                "type": "promotional",
            },
            {
                "content": f"Did you know? Here's an interesting fact about {topic} that might surprise you! What do you think? Comment below!",
                "hashtags": ["DidYouKnow", "Facts", topic.replace(" ", "")],
                "type": "engagement",
            },
            {
                "content": f"Quick tip: When it comes to {topic}, remember these key points... #Tips #Advice",
                "hashtags": ["Tips", "Advice", topic.replace(" ", "")],
                "type": "educational",
            },
        ]

        return jsonify({"success": True, "suggestions": suggestions})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_media_bp.route("/api/ai/hashtags", methods=["POST"])
@login_required
def ai_suggest_hashtags():
    """Get AI hashtag suggestions"""
    try:
        data = request.get_json()
        content = data.get("content", "")
        platform = data.get("platform", "general")

        if not content:
            return jsonify({"success": False, "error": "Content is required"}), 400

        # Build prompt for AI hashtag suggestions
        prompt = f"""Analyze this social media post and suggest 8-10 relevant, trending hashtags:

"{content}"

Platform: {platform}

Return only a JSON array of hashtag strings (without # symbol). Example: ["Marketing", "Business", "Growth"]"""

        # Call DHQ dispatcher (ADR-013)
        try:
            result = dispatch_json(
                capability="creative",
                prompt=prompt,
                module_id="social_media",
                system_prompt="You are a social media expert. Suggest relevant, trending hashtags. Return only valid JSON array.",
            )
            ai_response = result.get("response", "") if isinstance(result, dict) else str(result or "")
            if ai_response:
                try:
                    import re

                    json_match = re.search(r"\[.*\]", ai_response, re.DOTALL)
                    if json_match:
                        hashtags = json.loads(json_match.group())
                        return jsonify({"success": True, "hashtags": hashtags[:10]})
                except json.JSONDecodeError:
                    logger.warning("Could not parse AI response as JSON")
        except Exception as ai_error:
            logger.warning(f"dispatch_json call failed: {ai_error}")

        # Fallback: Extract keywords and suggest relevant hashtags
        words = content.lower().split()
        suggested = []

        # Common relevant hashtags
        common_tags = ["Marketing", "Business", "Growth", "Success", "Entrepreneur"]

        for word in words:
            if len(word) > 4 and word.isalpha():
                suggested.append(word.capitalize())

        suggested.extend(common_tags[: 5 - len(suggested)])

        return jsonify({"success": True, "hashtags": suggested[:10]})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# QUEUE API
# ============================================================================


@social_media_bp.route("/api/queue")
@login_required
def get_queue():
    """Get posting queue"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                q.*,
                p.content,
                p.target_platforms,
                sa.platform,
                sa.account_name
            FROM social_media_queue q
            JOIN social_posts p ON q.post_id = p.id
            JOIN social_accounts sa ON q.account_id = sa.id
            WHERE p.user_id = %s
            ORDER BY q.scheduled_time
        """,
            (current_user.id,),
        )

        queue = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "queue": json.loads(json.dumps(queue, default=json_serial)),
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@social_media_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get counts
        cur.execute("SELECT COUNT(*) as count FROM social_accounts WHERE is_active = TRUE")
        accounts = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM social_posts WHERE status = 'scheduled'")
        scheduled = cur.fetchone()["count"]

        return jsonify(
            {
                "module": "social_media",
                "status": "operational",
                "healthy": True,
                "active_accounts": accounts,
                "scheduled_posts": scheduled,
                "platforms": list(PLATFORMS.keys()),
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "social_media",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@social_media_bp.route("/api/social-media/connected-platforms", methods=["GET"])
@login_required
def api_connected_platforms():
    from tools.social_media.publishing_service import get_connected_platforms

    platforms = get_connected_platforms(current_user.id)
    return jsonify(platforms)


@social_media_bp.route("/api/social-media/media-studio-posts", methods=["GET"])
@login_required
def api_media_studio_posts():
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, media_library_id, target_platforms, status, content, scheduled_at, published_at
            FROM social_posts
            WHERE user_id = %s AND media_library_id IS NOT NULL
            ORDER BY created_at DESC LIMIT 50
        """,
            (current_user.id,),
        )
        posts = []
        for r in cur.fetchall():
            p = dict(r)
            for k, v in list(p.items()):
                if hasattr(v, "isoformat"):
                    p[k] = v.isoformat()
            posts.append(p)
    return jsonify(posts)
