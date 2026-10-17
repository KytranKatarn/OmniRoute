"""
Email Manager Routes — Stats, Tracking & Status
===============================================
Analytics, open/click tracking pixels, and health check.

Registered on the existing email_manager_bp blueprint.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import jsonify, request
from flask_login import current_user, login_required
from psycopg2.extras import RealDictCursor

from .routes import email_manager_bp, get_db_connection


# ============================================================================
# STATS & ANALYTICS
# ============================================================================


@email_manager_bp.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    """Get email statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats (last 30 days, per user)
        cur.execute(
            """
            SELECT
                COUNT(*) as total_sent,
                COUNT(*) FILTER (WHERE status = 'sent') as delivered,
                COUNT(*) FILTER (WHERE status = 'opened') as opened,
                COUNT(*) FILTER (WHERE status = 'clicked') as clicked,
                COUNT(*) FILTER (WHERE status = 'failed') as failed,
                COUNT(*) FILTER (WHERE status = 'bounced') as bounced
            FROM email_logs
            WHERE created_at > NOW() - INTERVAL '30 days' AND created_by = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Daily trend
        cur.execute(
            """
            SELECT DATE(created_at) as date,
                   COUNT(*) as sent,
                   COUNT(*) FILTER (WHERE status = 'opened') as opened
            FROM email_logs
            WHERE created_at > NOW() - INTERVAL '30 days' AND created_by = %s
            GROUP BY DATE(created_at)
            ORDER BY date
        """,
            (current_user.id,),
        )
        daily_trend = cur.fetchall()

        # Template usage
        cur.execute(
            """
            SELECT t.name, COUNT(l.id) as send_count
            FROM email_templates t
            LEFT JOIN email_logs l ON t.id = l.template_id AND l.created_by = %s
            WHERE l.created_at > NOW() - INTERVAL '30 days' OR l.id IS NULL
            GROUP BY t.id, t.name
            ORDER BY send_count DESC
            LIMIT 10
        """,
            (current_user.id,),
        )
        template_usage = cur.fetchall()

        # Calculate rates
        total = stats["total_sent"] or 1
        stats["delivery_rate"] = round((stats["delivered"] / total) * 100, 1)
        stats["open_rate"] = round((stats["opened"] / total) * 100, 1)
        stats["click_rate"] = round((stats["clicked"] / total) * 100, 1)

        return jsonify(
            {
                "success": True,
                "stats": dict(stats),
                "daily_trend": [dict(d) for d in daily_trend],
                "template_usage": [dict(t) for t in template_usage],
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
# TRACKING ENDPOINTS
# ============================================================================


@email_manager_bp.route("/track/open/<int:log_id>")
def track_open(log_id):
    """Track email open (1x1 pixel)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE email_logs
            SET status = 'opened', opened_at = NOW()
            WHERE id = %s AND opened_at IS NULL
        """,
            (log_id,),
        )

        conn.commit()

    except Exception:
        pass

    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
    # Return 1x1 transparent GIF
    gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    return gif, 200, {"Content-Type": "image/gif"}


@email_manager_bp.route("/track/click/<int:log_id>")
def track_click(log_id):
    """Track email link click"""
    try:
        url = request.args.get("url", "/")

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE email_logs
            SET status = 'clicked', clicked_at = NOW()
            WHERE id = %s AND clicked_at IS NULL
        """,
            (log_id,),
        )

        conn.commit()

        return "", 302, {"Location": url}

    except Exception:
        return "", 302, {"Location": "/"}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@email_manager_bp.route("/api/status")
def status():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) FROM email_templates WHERE is_active = true")
        template_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM email_logs WHERE created_at > NOW() - INTERVAL '24 hours'")
        recent_emails = cur.fetchone()["count"]

        cur.execute("SELECT test_result FROM email_settings WHERE is_default = true AND is_active = true")
        smtp_status = cur.fetchone()

        return jsonify(
            {
                "module": "email_manager",
                "status": "healthy",
                "healthy": True,
                "templates": template_count,
                "recent_emails": recent_emails,
                "smtp_configured": smtp_status is not None,
                "smtp_tested": (smtp_status["test_result"] == "success" if smtp_status else False),
                "message": f"Email Manager operational with {template_count} templates",
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "module": "email_manager",
                    "status": "error",
                    "healthy": False,
                    "message": str(e),
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
