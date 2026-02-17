"""
Proactive Intelligence Routes — Briefings, Anomaly Rules/Detections, Reports

Registered on the autonomy_bp blueprint.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from . import autonomy_bp
from .routes import admin_required

logger = logging.getLogger("intelligence_routes")

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


# ============================================================================
# Briefings
# ============================================================================


@autonomy_bp.route("/api/intelligence/briefings", methods=["GET"])
@login_required
@admin_required
def get_briefings():
    """Get briefing configurations."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT b.*, u.username,
                   (SELECT MAX(generated_at) FROM briefing_history bh WHERE bh.briefing_id = b.id) as last_generated
            FROM briefings b
            LEFT JOIN users u ON b.user_id = u.id
            ORDER BY b.created_at
            """
        )
        briefings = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "briefings": briefings})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/briefings", methods=["POST"])
@login_required
@admin_required
def create_briefing():
    """Create a new briefing configuration."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO briefings (name, briefing_type, schedule_cron, user_id, sections, delivery_channels)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["name"],
                data.get("briefing_type", "daily"),
                data["schedule_cron"],
                data.get("user_id", current_user.id),
                json.dumps(data.get("sections", ["notifications", "emails", "tasks"])),
                json.dumps(data.get("delivery_channels", ["notification"])),
            ),
        )
        briefing_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "id": briefing_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/briefings/<int:briefing_id>/generate", methods=["POST"])
@login_required
@admin_required
def generate_briefing_now(briefing_id):
    """Generate a briefing immediately."""
    try:
        from proactive_intelligence import BriefingGenerator

        bg = BriefingGenerator()
        history_id = bg.generate_briefing(briefing_id)
        if history_id:
            return jsonify({"success": True, "history_id": history_id})
        return jsonify({"success": False, "error": "Generation failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/briefings/<int:briefing_id>/history", methods=["GET"])
@login_required
@admin_required
def get_briefing_history(briefing_id):
    """Get generation history for a briefing."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, summary, delivery_status, generated_at
            FROM briefing_history
            WHERE briefing_id = %s
            ORDER BY generated_at DESC
            LIMIT 20
            """,
            (briefing_id,),
        )
        history = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/briefings/history/<int:history_id>", methods=["GET"])
@login_required
@admin_required
def get_briefing_detail(history_id):
    """Get full content of a generated briefing."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM briefing_history WHERE id = %s", (history_id,))
        entry = cur.fetchone()
        cur.close()
        conn.close()
        if not entry:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True, "briefing": dict(entry)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Anomaly Detection
# ============================================================================


@autonomy_bp.route("/api/intelligence/anomaly-rules", methods=["GET"])
@login_required
@admin_required
def get_anomaly_rules():
    """Get anomaly detection rules."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT ar.*,
                   (SELECT COUNT(*) FROM anomaly_detections ad WHERE ad.rule_id = ar.id) as total_triggers,
                   (SELECT COUNT(*) FROM anomaly_detections ad
                    WHERE ad.rule_id = ar.id AND ad.acknowledged = FALSE) as unack_triggers
            FROM anomaly_rules ar
            ORDER BY ar.created_at
            """
        )
        rules = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "rules": rules})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/anomaly-rules", methods=["POST"])
@login_required
@admin_required
def create_anomaly_rule():
    """Create a new anomaly detection rule."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO anomaly_rules
            (name, description, rule_type, rule_config, severity, check_interval_minutes, cooldown_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["name"],
                data.get("description"),
                data.get("rule_type", "sql_threshold"),
                json.dumps(data["rule_config"]),
                data.get("severity", "warning"),
                data.get("check_interval_minutes", 15),
                data.get("cooldown_minutes", 60),
            ),
        )
        rule_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "id": rule_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/anomaly-rules/<int:rule_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_anomaly_rule(rule_id):
    """Toggle an anomaly rule active/inactive."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "UPDATE anomaly_rules SET is_active = NOT is_active, updated_at = NOW() WHERE id = %s RETURNING is_active",
            (rule_id,),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "is_active": result["is_active"] if result else False})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/anomaly-rules/<int:rule_id>/check", methods=["POST"])
@login_required
@admin_required
def check_anomaly_rule(rule_id):
    """Manually check a single anomaly rule."""
    try:
        from proactive_intelligence import AnomalyDetector

        detector = AnomalyDetector()

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM anomaly_rules WHERE id = %s", (rule_id,))
        rule = cur.fetchone()
        cur.close()
        conn.close()

        if not rule:
            return jsonify({"success": False, "error": "Rule not found"}), 404

        conn2 = get_db()
        cur2 = conn2.cursor(cursor_factory=RealDictCursor)
        triggered, current_val, threshold_val = detector._check_rule(cur2, rule)
        cur2.close()
        conn2.close()

        return jsonify(
            {
                "success": True,
                "triggered": triggered,
                "current_value": float(current_val),
                "threshold_value": float(threshold_val),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/detections", methods=["GET"])
@login_required
@admin_required
def get_detections():
    """Get anomaly detections."""
    try:
        acknowledged = request.args.get("acknowledged", "false").lower() == "true"
        limit = min(int(request.args.get("limit", 50)), 200)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT ad.*, ar.name as rule_name
            FROM anomaly_detections ad
            JOIN anomaly_rules ar ON ad.rule_id = ar.id
            WHERE ad.acknowledged = %s
            ORDER BY
                CASE ad.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                ad.created_at DESC
            LIMIT %s
            """,
            (acknowledged, limit),
        )
        detections = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "detections": detections})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/detections/<int:detection_id>/acknowledge", methods=["POST"])
@login_required
@admin_required
def acknowledge_detection(detection_id):
    """Acknowledge an anomaly detection."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE anomaly_detections
            SET acknowledged = TRUE, acknowledged_by = %s, acknowledged_at = NOW()
            WHERE id = %s
            """,
            (current_user.id, detection_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Scheduled Reports
# ============================================================================


@autonomy_bp.route("/api/intelligence/reports", methods=["GET"])
@login_required
@admin_required
def get_reports():
    """Get scheduled report configurations."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT sr.*, u.username
            FROM scheduled_reports sr
            LEFT JOIN users u ON sr.user_id = u.id
            ORDER BY sr.created_at
            """
        )
        reports = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "reports": reports})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/reports", methods=["POST"])
@login_required
@admin_required
def create_report():
    """Create a new scheduled report."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO scheduled_reports
            (name, report_type, schedule_cron, user_id, report_config, output_format, delivery_channels)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["name"],
                data["report_type"],
                data["schedule_cron"],
                data.get("user_id", current_user.id),
                json.dumps(data.get("report_config", {})),
                data.get("output_format", "text"),
                json.dumps(data.get("delivery_channels", ["notification"])),
            ),
        )
        report_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "id": report_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/intelligence/reports/<int:report_id>/generate", methods=["POST"])
@login_required
@admin_required
def generate_report_now(report_id):
    """Generate a report immediately."""
    try:
        from proactive_intelligence import ReportEngine

        re = ReportEngine()
        content = re.generate_report(report_id)
        if content:
            return jsonify({"success": True, "content": content[:5000]})
        return jsonify({"success": False, "error": "Generation failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
