"""
Email Manager Routes
====================
Email communications hub for A.R.C.H.I.E. Business Tools.

Features:
- Email templates with variable substitution
- SMTP configuration management
- Send emails (single and bulk)
- Email tracking (sent, opened, clicked)
- Campaign management
- Integration with CRM and Invoicing

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from functools import wraps

from flask import Blueprint, render_template, request, jsonify, current_app, abort
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from rbac import Permission, has_permission
except ImportError:
    Permission = None
    has_permission = None


def admin_required(f):
    """Decorator to require admin access."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if has_permission and Permission:
            if not has_permission(Permission.ADMIN_ACCESS, current_user):
                abort(403)
        else:
            if not getattr(current_user, "is_admin", False):
                abort(403)
        return f(*args, **kwargs)

    return decorated_function


# Import user context helpers
try:
    from services.user_context import is_admin_user
    from .access_control import email_access_required
except ImportError:
    email_access_required = None

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
email_manager_bp = Blueprint(
    "email_manager",
    __name__,
    url_prefix="/tools/email-manager",
    template_folder="../../templates/tools",
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def render_template_vars(template_str, variables):
    """Replace {{variable}} placeholders with actual values"""
    if not template_str:
        return template_str
    for key, value in variables.items():
        template_str = template_str.replace("{{" + key + "}}", str(value))
    return template_str


def get_smtp_for_sending(cur, account_id=None):
    """Resolve SMTP config: per-account first, then legacy fallback."""
    if account_id:
        cur.execute(
            """SELECT smtp_host, smtp_port, smtp_user, smtp_password_encrypted,
                      smtp_encryption AS encryption, from_email, from_name, reply_to
               FROM email_imap_settings
               WHERE id = %s AND smtp_host IS NOT NULL""",
            (account_id,),
        )
        smtp = cur.fetchone()
        if smtp:
            return dict(smtp)
    # Fallback to legacy email_settings
    cur.execute("SELECT * FROM email_settings WHERE is_default = true AND is_active = true")
    smtp = cur.fetchone()
    return dict(smtp) if smtp else None


# ============================================================================
# MAIN PAGE
# ============================================================================


@email_manager_bp.route("/")
@login_required
@email_access_required
def index():
    """Main Email Manager dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get email stats (last 30 days)
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
            WHERE created_at > NOW() - INTERVAL '30 days'
        """
        )
        stats = cur.fetchone()

        # Get templates
        cur.execute(
            """
            SELECT id, name, subject, template_type, is_active, created_at
            FROM email_templates
            ORDER BY name
        """
        )
        templates = cur.fetchall()

        # Get recent emails
        cur.execute(
            """
            SELECT id, recipient, subject, status, sent_at, opened_at, created_at
            FROM email_logs
            ORDER BY created_at DESC
            LIMIT 10
        """
        )
        recent_emails = cur.fetchall()

        # Get campaigns
        cur.execute(
            """
            SELECT c.*, t.name as template_name
            FROM email_campaigns c
            LEFT JOIN email_templates t ON c.template_id = t.id
            ORDER BY c.created_at DESC
            LIMIT 5
        """
        )
        campaigns = cur.fetchall()

        # Get SMTP settings status
        cur.execute(
            """
            SELECT id, name, from_email, is_default, test_result
            FROM email_settings
            WHERE is_active = true
            LIMIT 1
        """
        )
        smtp_status = cur.fetchone()

        # Get unread inbox count for nav badge (only user's accounts)
        email_unread_count = 0
        try:
            cur.execute(
                """SELECT COUNT(*) as c FROM email_inbox e
                JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
                WHERE e.is_read = FALSE AND e.is_archived = FALSE AND eis.user_id = %s""",
                (current_user.id,),
            )
            email_unread_count = cur.fetchone()["c"]
        except Exception:
            email_unread_count = 0

        return render_template(
            "email_manager.html",
            stats=stats,
            templates=templates,
            recent_emails=recent_emails,
            campaigns=campaigns,
            smtp_status=smtp_status,
            is_admin=is_admin_user(),
            email_unread_count=email_unread_count,
            email_access_required=email_access_required,
        )
    except Exception as e:
        current_app.logger.error(f"[EmailManager] Error loading dashboard: {e}")
        return render_template(
            "email_manager.html",
            stats={
                "total_sent": 0,
                "delivered": 0,
                "opened": 0,
                "clicked": 0,
                "failed": 0,
                "bounced": 0,
            },
            templates=[],
            recent_emails=[],
            campaigns=[],
            smtp_status=None,
            error=str(e),
            email_access_required=email_access_required,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# Import route registrations from split modules
from .routes_templates import *  # noqa: E402, F401, F403
from .routes_send import *  # noqa: E402, F401, F403
from .routes_stats import *  # noqa: E402, F401, F403
