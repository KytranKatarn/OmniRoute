"""
Analytics Routes
================
Unified metrics dashboard for A.R.C.H.I.E. Business Tools.

Features:
- Real-time metrics from all business modules
- Custom dashboards with widgets
- Historical snapshots and trends
- Scheduled reports
- Goals and targets tracking

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date  # noqa: F401
import os
import json
from decimal import Decimal

# Import user context helpers
try:
    from user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
analytics_bp = Blueprint("analytics", __name__, url_prefix="/tools/analytics", template_folder="../../templates/tools")


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def safe_query(query, params=None, default=None):
    """Execute query safely, returning default on error"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, params or ())
        result = cur.fetchone() if default is not None else cur.fetchall()
        cur.close()
        conn.close()
        return result or default
    except Exception as e:
        current_app.logger.error(f"Query error: {e}")
        return default


# ============================================================================
# MAIN PAGE
# ============================================================================


@analytics_bp.route("/")
@login_required
def index():
    """Main Analytics dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get live metrics from various sources
        metrics = {}

        # Revenue metrics (from invoices)
        cur.execute(
            """
            SELECT
                COALESCE(SUM(total) FILTER (WHERE paid_at IS NOT NULL), 0) as total_revenue,
                COALESCE(SUM(total) FILTER (WHERE paid_at >= NOW() - INTERVAL '30 days'), 0) as revenue_30d,
                COALESCE(SUM(total) FILTER (WHERE paid_at >= NOW() - INTERVAL '7 days'), 0) as revenue_7d,
                COALESCE(SUM(total) FILTER (WHERE paid_at::DATE = CURRENT_DATE), 0) as revenue_today
            FROM invoices
        """
        )
        revenue = cur.fetchone() or {}
        metrics.update(revenue)

        # Customer metrics (from CRM)
        cur.execute(
            """
            SELECT
                COUNT(*) as total_customers,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') as new_customers_30d,
                COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as new_customers_7d,
                COUNT(*) FILTER (WHERE last_activity >= NOW() - INTERVAL '30 days') as active_customers
            FROM crm_customers
        """
        )
        customers = cur.fetchone() or {}
        metrics.update(customers)

        # Subscription metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_subscriptions,
                COUNT(*) FILTER (WHERE status = 'active') as active_subscriptions,
                COALESCE(SUM(amount) FILTER (
                    WHERE status = 'active' AND billing_cycle = 'monthly'), 0) as mrr,
                COUNT(*) FILTER (
                    WHERE next_billing_date <= NOW() + INTERVAL '7 days'
                    AND status = 'active') as renewals_upcoming
            FROM subscription_schedules
        """
        )
        subscriptions = cur.fetchone() or {}
        metrics["mrr"] = subscriptions.get("mrr", 0)
        metrics["arr"] = float(metrics.get("mrr", 0)) * 12
        metrics.update(subscriptions)

        # Invoice metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_invoices,
                COUNT(*) FILTER (WHERE status = 'draft') as invoices_draft,
                COUNT(*) FILTER (WHERE status IN ('sent', 'open')) as invoices_outstanding,
                COUNT(*) FILTER (WHERE status = 'overdue') as invoices_overdue,
                COUNT(*) FILTER (WHERE status = 'paid') as invoices_paid,
                COALESCE(SUM(balance_due) FILTER (WHERE status IN ('sent', 'open', 'overdue')), 0) as amount_outstanding
            FROM invoices
        """
        )
        invoices = cur.fetchone() or {}
        metrics.update(invoices)

        # Email metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_emails,
                COUNT(*) FILTER (WHERE sent_at IS NOT NULL) as emails_sent,
                COUNT(*) FILTER (WHERE opened_at IS NOT NULL) as emails_opened,
                COUNT(*) FILTER (WHERE clicked_at IS NOT NULL) as emails_clicked
            FROM email_logs
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """
        )
        emails = cur.fetchone() or {}
        emails["email_open_rate"] = round(
            (emails.get("emails_opened", 0) / max(emails.get("emails_sent", 1), 1)) * 100, 1
        )
        metrics.update(emails)

        # Event metrics
        cur.execute(
            """
            SELECT
                COUNT(*) as total_events,
                COUNT(*) FILTER (
                    WHERE start_time >= NOW()
                    AND start_time < NOW() + INTERVAL '7 days') as upcoming_events,
                COUNT(*) FILTER (WHERE status = 'completed') as completed_events
            FROM calendar_events
            WHERE start_time >= NOW() - INTERVAL '30 days'
        """
        )
        events = cur.fetchone() or {}
        metrics.update(events)

        # Get chart data - Revenue trend (last 30 days)
        cur.execute(
            """
            SELECT
                paid_at::DATE as date,
                SUM(total) as revenue
            FROM invoices
            WHERE paid_at >= NOW() - INTERVAL '30 days'
            GROUP BY paid_at::DATE
            ORDER BY date
        """
        )
        revenue_trend = cur.fetchall()

        # Get chart data - New customers (last 30 days)
        cur.execute(
            """
            SELECT
                created_at::DATE as date,
                COUNT(*) as count
            FROM crm_customers
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY created_at::DATE
            ORDER BY date
        """
        )
        customer_trend = cur.fetchall()

        # Get top customers
        cur.execute(
            """
            SELECT
                c.id, c.first_name, c.last_name, c.email, c.company,
                c.total_spent, c.subscription_tier, c.total_orders
            FROM crm_customers c
            ORDER BY c.total_spent DESC NULLS LAST
            LIMIT 10
        """
        )
        top_customers = cur.fetchall()

        # Get recent activity
        cur.execute(
            """
            (SELECT 'invoice' as type,
                'Invoice ' || invoice_number || ' paid' as description,
                paid_at as timestamp
             FROM invoices WHERE paid_at IS NOT NULL ORDER BY paid_at DESC LIMIT 5)
            UNION ALL
            (SELECT 'customer' as type,
                'New customer: ' || first_name || ' ' || last_name as description,
                created_at as timestamp
             FROM crm_customers ORDER BY created_at DESC LIMIT 5)
            UNION ALL
            (SELECT 'email' as type,
                'Email sent to ' || recipient as description,
                sent_at as timestamp
             FROM email_logs WHERE sent_at IS NOT NULL ORDER BY sent_at DESC LIMIT 5)
            ORDER BY timestamp DESC
            LIMIT 10
        """
        )
        recent_activity = cur.fetchall()

        # Get goals
        cur.execute(
            """
            SELECT * FROM analytics_goals
            WHERE status = 'in_progress'
            ORDER BY end_date
            LIMIT 5
        """
        )
        goals = cur.fetchall()

        cur.close()
        conn.close()

        return render_template(
            "tools/analytics.html",
            metrics=metrics,
            revenue_trend=json.dumps([dict(r) for r in revenue_trend], default=json_serial),
            customer_trend=json.dumps([dict(c) for c in customer_trend], default=json_serial),
            top_customers=top_customers,
            recent_activity=recent_activity,
            goals=goals,
        )

    except Exception as e:
        current_app.logger.error(f"Analytics index error: {str(e)}")
        return render_template(
            "tools/analytics.html",
            metrics={},
            revenue_trend="[]",
            customer_trend="[]",
            top_customers=[],
            recent_activity=[],
            goals=[],
            error=str(e),
        )


# ============================================================================
# METRICS API
# ============================================================================


@analytics_bp.route("/api/metrics")
@login_required
def get_metrics():
    """Get all metrics"""
    try:
        period = request.args.get("period", "30d")

        # Parse period
        days = 30
        if period == "7d":
            days = 7
        elif period == "90d":
            days = 90
        elif period == "year":
            days = 365

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        metrics = {}

        # Revenue
        cur.execute(
            """
            SELECT COALESCE(SUM(total), 0) as value
            FROM invoices WHERE paid_at >= NOW() - INTERVAL '%s days'
        """,
            (days,),
        )
        metrics["revenue"] = cur.fetchone()["value"]

        # Previous period for comparison
        cur.execute(
            """
            SELECT COALESCE(SUM(total), 0) as value
            FROM invoices WHERE paid_at >= NOW() - INTERVAL '%s days'
              AND paid_at < NOW() - INTERVAL '%s days'
        """,
            (days * 2, days),
        )
        prev_revenue = cur.fetchone()["value"]
        metrics["revenue_change"] = calculate_change(metrics["revenue"], prev_revenue)

        # Customers
        cur.execute("SELECT COUNT(*) as value FROM crm_customers")
        metrics["customers"] = cur.fetchone()["value"]

        cur.execute(
            """
            SELECT COUNT(*) as value FROM crm_customers
            WHERE created_at >= NOW() - INTERVAL '%s days'
        """,
            (days,),
        )
        metrics["new_customers"] = cur.fetchone()["value"]

        # MRR
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as value
            FROM subscription_schedules
            WHERE status = 'active' AND billing_cycle = 'monthly'
        """
        )
        metrics["mrr"] = cur.fetchone()["value"]
        metrics["arr"] = float(metrics["mrr"]) * 12

        # Invoices outstanding
        cur.execute(
            """
            SELECT COALESCE(SUM(balance_due), 0) as value
            FROM invoices WHERE status IN ('sent', 'open', 'overdue')
        """
        )
        metrics["outstanding"] = cur.fetchone()["value"]

        # Email metrics
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE sent_at IS NOT NULL) as sent,
                COUNT(*) FILTER (WHERE opened_at IS NOT NULL) as opened
            FROM email_logs WHERE created_at >= NOW() - INTERVAL '%s days'
        """,
            (days,),
        )
        email_data = cur.fetchone()
        metrics["emails_sent"] = email_data["sent"]
        metrics["email_open_rate"] = round((email_data["opened"] / max(email_data["sent"], 1)) * 100, 1)

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "metrics": json.loads(json.dumps(metrics, default=json_serial)), "period": period}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def calculate_change(current, previous):
    """Calculate percentage change"""
    if not previous or previous == 0:
        return 0 if not current else 100
    return round(((float(current) - float(previous)) / float(previous)) * 100, 1)


@analytics_bp.route("/api/metrics/<metric_name>")
@login_required
def get_metric(metric_name):
    """Get a specific metric value"""
    try:
        date_from = request.args.get("from")
        date_to = request.args.get("to")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Use the database function
        cur.execute(
            """
            SELECT get_metric_value(%s, %s::DATE, %s::DATE) as value
        """,
            (metric_name, date_from, date_to),
        )

        result = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({"success": True, "metric": metric_name, "value": float(result["value"]) if result else 0})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# CHART DATA API
# ============================================================================


@analytics_bp.route("/api/charts/revenue")
@login_required
def get_revenue_chart():
    """Get revenue chart data"""
    try:
        period = request.args.get("period", "30d")
        group_by = request.args.get("group_by", "day")

        days = {"7d": 7, "30d": 30, "90d": 90, "year": 365}.get(period, 30)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if group_by == "day":
            cur.execute(
                """
                SELECT
                    paid_at::DATE as date,
                    SUM(total) as revenue,
                    COUNT(*) as count
                FROM invoices
                WHERE paid_at >= NOW() - INTERVAL '%s days'
                GROUP BY paid_at::DATE
                ORDER BY date
            """,
                (days,),
            )
        elif group_by == "week":
            cur.execute(
                """
                SELECT
                    DATE_TRUNC('week', paid_at)::DATE as date,
                    SUM(total) as revenue,
                    COUNT(*) as count
                FROM invoices
                WHERE paid_at >= NOW() - INTERVAL '%s days'
                GROUP BY DATE_TRUNC('week', paid_at)
                ORDER BY date
            """,
                (days,),
            )
        else:  # month
            cur.execute(
                """
                SELECT
                    DATE_TRUNC('month', paid_at)::DATE as date,
                    SUM(total) as revenue,
                    COUNT(*) as count
                FROM invoices
                WHERE paid_at >= NOW() - INTERVAL '%s days'
                GROUP BY DATE_TRUNC('month', paid_at)
                ORDER BY date
            """,
                (days,),
            )

        data = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "data": json.loads(json.dumps([dict(d) for d in data], default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/charts/customers")
@login_required
def get_customers_chart():
    """Get customer growth chart data"""
    try:
        period = request.args.get("period", "30d")

        days = {"7d": 7, "30d": 30, "90d": 90, "year": 365}.get(period, 30)

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                created_at::DATE as date,
                COUNT(*) as new_customers,
                SUM(COUNT(*)) OVER (ORDER BY created_at::DATE) as cumulative
            FROM crm_customers
            WHERE created_at >= NOW() - INTERVAL '%s days'
            GROUP BY created_at::DATE
            ORDER BY date
        """,
            (days,),
        )

        data = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({"success": True, "data": json.loads(json.dumps([dict(d) for d in data], default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/charts/subscriptions")
@login_required
def get_subscriptions_chart():
    """Get subscription metrics chart"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Subscription by tier
        cur.execute(
            """
            SELECT tier, COUNT(*) as count, SUM(amount) as revenue
            FROM subscription_schedules
            WHERE status = 'active'
            GROUP BY tier
            ORDER BY revenue DESC
        """
        )
        by_tier = cur.fetchall()

        # Subscription by status
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM subscription_schedules
            GROUP BY status
        """
        )
        by_status = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "by_tier": json.loads(json.dumps([dict(d) for d in by_tier], default=json_serial)),
                "by_status": [dict(d) for d in by_status],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# DASHBOARDS API
# ============================================================================


@analytics_bp.route("/api/dashboards")
@login_required
def get_dashboards():
    """Get user's dashboards"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM analytics_dashboards
            WHERE user_id = %s OR is_public = true
            ORDER BY is_default DESC, name
        """,
            (current_user.id,),
        )

        dashboards = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "dashboards": json.loads(json.dumps([dict(d) for d in dashboards], default=json_serial))}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/dashboards", methods=["POST"])
@login_required
def create_dashboard():
    """Create a new dashboard"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO analytics_dashboards (name, description, layout, filters, user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("description"),
                json.dumps(data.get("layout", [])),
                json.dumps(data.get("filters", {})),
                current_user.id,
            ),
        )

        dashboard = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"success": True, "dashboard": json.loads(json.dumps(dict(dashboard), default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# GOALS API
# ============================================================================


@analytics_bp.route("/api/goals")
@login_required
def get_goals():
    """Get goals"""
    try:
        status = request.args.get("status", "")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = "SELECT * FROM analytics_goals WHERE 1=1"
        params = []

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY end_date"

        cur.execute(query, params)
        goals = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "goals": json.loads(json.dumps([dict(g) for g in goals], default=json_serial))}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/goals", methods=["POST"])
@login_required
def create_goal():
    """Create a new goal"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO analytics_goals (
                name, metric_name, target_value, period, start_date, end_date, user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("metric_name"),
                data.get("target_value"),
                data.get("period", "monthly"),
                data.get("start_date"),
                data.get("end_date"),
                current_user.id,
            ),
        )

        goal = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"success": True, "goal": json.loads(json.dumps(dict(goal), default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/goals/<int:goal_id>", methods=["PUT"])
@login_required
def update_goal(goal_id):
    """Update a goal"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE analytics_goals SET
                name = COALESCE(%s, name),
                target_value = COALESCE(%s, target_value),
                current_value = COALESCE(%s, current_value),
                status = COALESCE(%s, status),
                progress_percentage = CASE
                    WHEN %s IS NOT NULL AND target_value > 0
                    THEN ROUND((%s::DECIMAL / target_value) * 100, 2)
                    ELSE progress_percentage
                END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (
                data.get("name"),
                data.get("target_value"),
                data.get("current_value"),
                data.get("status"),
                data.get("current_value"),
                data.get("current_value"),
                goal_id,
            ),
        )

        goal = cur.fetchone()
        conn.commit()

        cur.close()
        conn.close()

        if not goal:
            return jsonify({"success": False, "error": "Goal not found"}), 404

        return jsonify({"success": True, "goal": json.loads(json.dumps(dict(goal), default=json_serial))})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/goals/<int:goal_id>", methods=["DELETE"])
@login_required
def delete_goal(goal_id):
    """Delete a goal"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("DELETE FROM analytics_goals WHERE id = %s", (goal_id,))
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"success": True, "message": "Goal deleted"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# REPORTS API
# ============================================================================


@analytics_bp.route("/api/reports")
@login_required
def get_reports():
    """Get saved reports"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM analytics_reports
            WHERE user_id = %s
            ORDER BY updated_at DESC
        """,
            (current_user.id,),
        )

        reports = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "reports": json.loads(json.dumps([dict(r) for r in reports], default=json_serial))}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/reports/generate", methods=["POST"])
@login_required
def generate_report():
    """Generate a report"""
    try:
        data = request.get_json()
        report_type = data.get("type", "revenue")
        date_from = data.get("from")
        date_to = data.get("to")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if report_type == "revenue":
            cur.execute(
                """
                SELECT
                    paid_at::DATE as date,
                    invoice_number,
                    customer_name,
                    total as amount,
                    payment_method
                FROM invoices i
                LEFT JOIN crm_customers c ON i.customer_id = c.id
                WHERE i.paid_at >= %s AND i.paid_at <= %s
                ORDER BY paid_at DESC
            """,
                (date_from, date_to),
            )
        elif report_type == "customers":
            cur.execute(
                """
                SELECT
                    created_at::DATE as date,
                    first_name, last_name, email,
                    company, subscription_tier, total_spent
                FROM crm_customers
                WHERE created_at >= %s AND created_at <= %s
                ORDER BY created_at DESC
            """,
                (date_from, date_to),
            )
        elif report_type == "subscriptions":
            cur.execute(
                """
                SELECT
                    s.created_at::DATE as date,
                    c.first_name || ' ' || c.last_name as customer_name,
                    s.tier, s.billing_cycle, s.amount, s.status,
                    s.next_billing_date
                FROM subscription_schedules s
                LEFT JOIN crm_customers c ON s.customer_id = c.id
                WHERE s.created_at >= %s AND s.created_at <= %s
                ORDER BY s.created_at DESC
            """,
                (date_from, date_to),
            )
        else:
            return jsonify({"success": False, "error": "Invalid report type"}), 400

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "report": {
                    "type": report_type,
                    "date_from": date_from,
                    "date_to": date_to,
                    "rows": json.loads(json.dumps([dict(r) for r in rows], default=json_serial)),
                    "count": len(rows),
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SNAPSHOT API
# ============================================================================


@analytics_bp.route("/api/snapshots/generate", methods=["POST"])
@login_required
def generate_snapshot():
    """Generate a daily snapshot"""
    try:
        data = request.get_json()
        snapshot_date = data.get("date", date.today().isoformat())

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT generate_daily_snapshot(%s::DATE)", (snapshot_date,))
        snapshot_id = cur.fetchone()[0]
        conn.commit()

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "snapshot_id": snapshot_id, "message": f"Snapshot generated for {snapshot_date}"}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@analytics_bp.route("/api/snapshots")
@login_required
def get_snapshots():
    """Get historical snapshots"""
    try:
        days = int(request.args.get("days", 30))
        snapshot_type = request.args.get("type", "daily")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT * FROM analytics_snapshots
            WHERE snapshot_type = %s
              AND snapshot_date >= NOW() - INTERVAL '%s days'
            ORDER BY snapshot_date DESC
        """,
            (snapshot_type, days),
        )

        snapshots = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify(
            {"success": True, "snapshots": json.loads(json.dumps([dict(s) for s in snapshots], default=json_serial))}
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@analytics_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM analytics_snapshots")
        snapshot_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM analytics_dashboards")
        dashboard_count = cur.fetchone()[0]

        cur.close()
        conn.close()

        return jsonify(
            {
                "module": "analytics",
                "status": "operational",
                "healthy": True,
                "snapshots": snapshot_count,
                "dashboards": dashboard_count,
            }
        )

    except Exception as e:
        return jsonify({"module": "analytics", "status": "error", "healthy": False, "error": str(e)}), 500
