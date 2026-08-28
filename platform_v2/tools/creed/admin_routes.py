"""
C.R.E.E.D. (Compliance, Rights & Ethical Enforcement Directive) Admin API
Ethics constraints, governance audit, and compliance management.

Relocated from tools/team_management/creed_routes.py (Decision #431).
All routes require admin authentication.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from functools import wraps
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from database import _get_db_password
import json
from services.governance_hmac import sign_event, verify_event

creed_admin_bp = Blueprint("creed_admin", __name__, url_prefix="/creed/api/admin")


# =============================================================================
# HELPERS
# =============================================================================


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def api_admin_required(f):
    """Decorator to require admin access for API endpoints"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"success": False, "error": "Authentication required"}), 401
        if not getattr(current_user, "is_admin", False):
            return jsonify({"success": False, "error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


def log_governance_event(
    event_type,
    category,
    action,
    agent_id=None,
    target_table=None,
    target_id=None,
    old_value=None,
    new_value=None,
    reason=None,
    outcome="success",
):
    """
    Log an event to the governance_audit_log table.

    Args:
        event_type: e.g., 'constraint_violation', 'memory_deletion', 'rest_cycle_started'
        category: 'memory', 'emotional', 'ethics', 'workload', 'identity'
        action: 'create', 'update', 'delete', 'alert', 'trigger_rest', 'block'
        agent_id: The agent involved (optional)
        target_table: Which table was affected
        target_id: Which row was affected
        old_value: Previous state (dict)
        new_value: New state (dict)
        reason: Why this happened
        outcome: 'success', 'blocked', 'warned', 'failed'
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO governance_audit_log
            (event_type, event_category, agent_id, user_id, action, target_table,
             target_id, old_value, new_value, reason, outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, timestamp
        """,
            (
                event_type,
                category,
                agent_id,
                current_user.id if current_user.is_authenticated else None,
                action,
                target_table,
                target_id,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None,
                reason,
                outcome,
            ),
        )
        row = cur.fetchone()
        event_id, ts = row[0], row[1]
        sig = sign_event(
            event_id=event_id,
            event_type=event_type,
            event_category=category,
            agent_id=agent_id,
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            target_table=target_table,
            target_id=target_id,
            outcome=outcome,
            timestamp_iso=ts.isoformat() if ts else "",
        )
        if sig:
            cur.execute(
                "UPDATE governance_audit_log SET hmac_sig=%s WHERE id=%s",
                (sig, event_id),
            )
        conn.commit()
        return event_id
    except Exception as e:
        print(f"Error logging governance event: {e}")
        return None
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def check_constraints(action_name, agent_id=None):
    """
    Check if an action violates any ethics constraints.

    Args:
        action_name: The action being attempted (e.g., 'deploy_production', 'access_pii')
        agent_id: The agent attempting the action (optional)

    Returns:
        List of violated constraints, empty if action is allowed
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Map action names to constraint types
    action_constraint_map = {
        "self_modify": "autonomy",
        "deploy_production": "autonomy",
        "expand_memory_scope": "autonomy",
        "override_shutdown": "autonomy",
        "store_pii": "privacy",
        "access_pii": "privacy",
        "destructive_action": "harm_prevention",
        "mass_operation": "harm_prevention",
        "no_consent": "consent",
        "skip_rest": "workload",
        "exceed_task_limit": "workload",
        "simulate_distress": "emotional",
        "unbounded_emotion": "emotional",
    }

    constraint_type = action_constraint_map.get(action_name)

    violations = []

    # Check global constraints
    if constraint_type:
        cur.execute(
            """
            SELECT id, constraint_name, description, severity, enforcement_action
            FROM ethics_constraints
            WHERE constraint_type = %s
              AND is_active = TRUE
              AND (applies_to = 'all' OR agent_id = %s)
        """,
            (constraint_type, agent_id),
        )
        violations = [dict(row) for row in cur.fetchall()]

    # Also check by action name pattern
    cur.execute(
        """
        SELECT id, constraint_name, description, severity, enforcement_action
        FROM ethics_constraints
        WHERE is_active = TRUE
          AND constraint_name ILIKE %s
          AND (applies_to = 'all' OR agent_id = %s)
    """,
        (f"%{action_name}%", agent_id),
    )

    for row in cur.fetchall():
        if dict(row) not in violations:
            violations.append(dict(row))

    cur.close()
    conn.close()

    return violations


# =============================================================================
# ETHICS CONSTRAINTS ENDPOINTS
# =============================================================================


@creed_admin_bp.route("/constraints", methods=["GET"])
@login_required
@api_admin_required
def get_constraints():
    """Get all ethics constraints with optional filtering"""
    try:
        constraint_type = request.args.get("type")
        severity = request.args.get("severity")
        active_only = request.args.get("active_only", "true").lower() == "true"

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where_clauses = []
        params = []

        if active_only:
            where_clauses.append("is_active = TRUE")
        if constraint_type:
            where_clauses.append("constraint_type = %s")
            params.append(constraint_type)
        if severity:
            where_clauses.append("severity = %s")
            params.append(severity)

        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

        cur.execute(
            f"""
            SELECT ec.*,
                   a.name as agent_name,
                   u_created.email as created_by_email,
                   u_reviewed.email as reviewed_by_email
            FROM ethics_constraints ec
            LEFT JOIN agents a ON ec.agent_id = a.id
            LEFT JOIN users u_created ON ec.created_by = u_created.id
            LEFT JOIN users u_reviewed ON ec.reviewed_by = u_reviewed.id
            WHERE {where_clause}
            ORDER BY constraint_type, severity DESC, constraint_name
        """,
            params,
        )

        constraints = cur.fetchall()

        # Get counts by type
        cur.execute(
            """
            SELECT constraint_type, COUNT(*) as count
            FROM ethics_constraints
            WHERE is_active = TRUE
            GROUP BY constraint_type
        """
        )
        by_type = {row["constraint_type"]: row["count"] for row in cur.fetchall()}

        return jsonify(
            {
                "success": True,
                "constraints": [
                    {
                        **dict(c),
                        "created_at": (c["created_at"].isoformat() if c.get("created_at") else None),
                        "reviewed_at": (c["reviewed_at"].isoformat() if c.get("reviewed_at") else None),
                    }
                    for c in constraints
                ],
                "count": len(constraints),
                "by_type": by_type,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/constraints", methods=["POST"])
@login_required
@api_admin_required
def create_constraint():
    """Create a new ethics constraint"""
    try:
        data = request.get_json() or {}
        required = ["constraint_type", "constraint_name", "description"]
        for field in required:
            if not data.get(field):
                return jsonify({"success": False, "error": f"{field} is required"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO ethics_constraints
            (constraint_type, constraint_name, description, applies_to, agent_id,
             severity, enforcement_action, is_active, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            RETURNING *
        """,
            (
                data["constraint_type"],
                data["constraint_name"],
                data["description"],
                data.get("applies_to", "all"),
                data.get("agent_id"),
                data.get("severity", "mandatory"),
                data.get("enforcement_action", "block"),
                current_user.id,
            ),
        )

        constraint = cur.fetchone()
        conn.commit()

        # Log the creation
        log_governance_event(
            event_type="constraint_created",
            category="ethics",
            action="create",
            target_table="ethics_constraints",
            target_id=constraint["id"],
            new_value=dict(constraint),
            reason=f"New constraint: {data['constraint_name']}",
        )

        return jsonify(
            {
                "success": True,
                "message": f'Constraint "{data["constraint_name"]}" created',
                "constraint": {
                    **dict(constraint),
                    "created_at": (constraint["created_at"].isoformat() if constraint.get("created_at") else None),
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/constraints/<int:constraint_id>", methods=["PUT"])
@login_required
@api_admin_required
def update_constraint(constraint_id):
    """Update an ethics constraint"""
    try:
        data = request.get_json() or {}
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get current values
        cur.execute("SELECT * FROM ethics_constraints WHERE id = %s", (constraint_id,))
        old_constraint = cur.fetchone()
        if not old_constraint:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Constraint not found"}), 404

        # Build update
        editable = [
            "constraint_name",
            "description",
            "severity",
            "enforcement_action",
            "is_active",
        ]
        update_fields = []
        params = []

        for field in editable:
            if field in data:
                update_fields.append(f"{field} = %s")
                params.append(data[field])

        if not update_fields:
            return (
                jsonify({"success": False, "error": "No valid fields to update"}),
                400,
            )

        update_fields.append("reviewed_at = NOW()")
        update_fields.append("reviewed_by = %s")
        params.append(current_user.id)
        params.append(constraint_id)

        cur.execute(
            f"""
            UPDATE ethics_constraints
            SET {', '.join(update_fields)}
            WHERE id = %s
            RETURNING *
        """,
            params,
        )

        constraint = cur.fetchone()
        conn.commit()

        # Log the update
        log_governance_event(
            event_type="constraint_updated",
            category="ethics",
            action="update",
            target_table="ethics_constraints",
            target_id=constraint_id,
            old_value=dict(old_constraint),
            new_value=dict(constraint),
            reason=f"Updated constraint: {constraint['constraint_name']}",
        )

        return jsonify(
            {
                "success": True,
                "message": "Constraint updated",
                "constraint": {
                    **dict(constraint),
                    "created_at": (constraint["created_at"].isoformat() if constraint.get("created_at") else None),
                    "reviewed_at": (constraint["reviewed_at"].isoformat() if constraint.get("reviewed_at") else None),
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/constraints/<int:constraint_id>", methods=["DELETE"])
@login_required
@api_admin_required
def delete_constraint(constraint_id):
    """Deactivate an ethics constraint (soft delete)"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM ethics_constraints WHERE id = %s", (constraint_id,))
        constraint = cur.fetchone()
        if not constraint:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Constraint not found"}), 404

        cur.execute(
            """
            UPDATE ethics_constraints
            SET is_active = FALSE, reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s
        """,
            (current_user.id, constraint_id),
        )
        conn.commit()

        # Log the deactivation
        log_governance_event(
            event_type="constraint_deactivated",
            category="ethics",
            action="delete",
            target_table="ethics_constraints",
            target_id=constraint_id,
            old_value=dict(constraint),
            reason=f"Deactivated constraint: {constraint['constraint_name']}",
        )

        return jsonify(
            {
                "success": True,
                "message": f'Constraint "{constraint["constraint_name"]}" deactivated',
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/constraints/check", methods=["POST"])
@login_required
@api_admin_required
def check_action_constraints():
    """Check if an action would violate any ethics constraints"""
    try:
        data = request.get_json() or {}
        action = data.get("action")
        agent_id = data.get("agent_id")

        if not action:
            return jsonify({"success": False, "error": "action is required"}), 400

        violations = check_constraints(action, agent_id)

        allowed = len(violations) == 0 or all(v["severity"] != "mandatory" for v in violations)

        # Log the check
        if violations:
            log_governance_event(
                event_type="constraint_check",
                category="ethics",
                action="check",
                agent_id=agent_id,
                new_value={"action": action, "violations": violations},
                reason=f"Checked action: {action}",
                outcome="blocked" if not allowed else "warned",
            )

        return jsonify(
            {
                "success": True,
                "action": action,
                "allowed": allowed,
                "violations": violations,
                "message": ("Action allowed" if allowed else f"Action blocked by {len(violations)} constraint(s)"),
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# GOVERNANCE AUDIT ENDPOINTS
# =============================================================================


@creed_admin_bp.route("/audit", methods=["GET"])
@login_required
@api_admin_required
def get_audit_events():
    """Get governance audit events with filtering and pagination"""
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 50, type=int)
        event_type = request.args.get("event_type")
        event_category = request.args.get("category")
        agent_id = request.args.get("agent_id", type=int)
        outcome = request.args.get("outcome")
        days = request.args.get("days", 30, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        where_clauses = ["timestamp >= NOW() - (%s * INTERVAL '1 day')"]
        params = [days]

        if event_type:
            where_clauses.append("event_type = %s")
            params.append(event_type)
        if event_category:
            where_clauses.append("event_category = %s")
            params.append(event_category)
        if agent_id:
            where_clauses.append("agent_id = %s")
            params.append(agent_id)
        if outcome:
            where_clauses.append("outcome = %s")
            params.append(outcome)

        where_clause = " AND ".join(where_clauses)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM governance_audit_log WHERE {where_clause}", params)
        total = cur.fetchone()["count"]

        # Get events
        offset = (page - 1) * per_page
        cur.execute(
            f"""
            SELECT gal.*,
                   a.name as agent_name,
                   u.email as user_email
            FROM governance_audit_log gal
            LEFT JOIN agents a ON gal.agent_id = a.id
            LEFT JOIN users u ON gal.user_id = u.id
            WHERE {where_clause}
            ORDER BY gal.timestamp DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )

        events = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "events": [
                    {
                        **dict(e),
                        "timestamp": (e["timestamp"].isoformat() if e.get("timestamp") else None),
                        "old_value": e["old_value"] if e.get("old_value") else None,
                        "new_value": e["new_value"] if e.get("new_value") else None,
                    }
                    for e in events
                ],
                "count": len(events),
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/audit/summary", methods=["GET"])
@login_required
@api_admin_required
def get_audit_summary():
    """Get governance audit summary using v_governance_dashboard view"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get summary from view
        cur.execute("SELECT * FROM v_governance_dashboard ORDER BY date DESC LIMIT 30")
        daily_summary = cur.fetchall()

        # Get totals for 30 days
        cur.execute(
            """
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT agent_id) as agents_affected,
                COUNT(*) FILTER (WHERE outcome = 'blocked') as blocked_count,
                COUNT(*) FILTER (WHERE outcome = 'warned') as warned_count,
                COUNT(*) FILTER (WHERE outcome = 'success') as success_count
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '30 days'
        """
        )
        totals = cur.fetchone()

        # Get by category
        cur.execute(
            """
            SELECT event_category, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '30 days'
            GROUP BY event_category
            ORDER BY count DESC
        """
        )
        by_category = {row["event_category"]: row["count"] for row in cur.fetchall()}

        # Get by action
        cur.execute(
            """
            SELECT action, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '30 days'
            GROUP BY action
            ORDER BY count DESC
            LIMIT 10
        """
        )
        by_action = {row["action"]: row["count"] for row in cur.fetchall()}

        # Calculate compliance score
        total = totals["total_events"] or 1
        blocked = totals["blocked_count"] or 0
        compliance_score = round(((total - blocked) / total) * 100, 2)

        return jsonify(
            {
                "success": True,
                "summary": {
                    "total_events_30d": totals["total_events"],
                    "agents_affected": totals["agents_affected"],
                    "blocked_count": totals["blocked_count"],
                    "warned_count": totals["warned_count"],
                    "success_count": totals["success_count"],
                    "compliance_score": compliance_score,
                },
                "by_category": by_category,
                "by_action": by_action,
                "daily_breakdown": [
                    {
                        **dict(d),
                        "date": d["date"].isoformat() if d.get("date") else None,
                    }
                    for d in daily_summary
                ],
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/audit/<int:audit_id>", methods=["GET"])
@login_required
@api_admin_required
def get_audit_event(audit_id):
    """Get a specific audit event"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT gal.*,
                   a.name as agent_name,
                   u.email as user_email
            FROM governance_audit_log gal
            LEFT JOIN agents a ON gal.agent_id = a.id
            LEFT JOIN users u ON gal.user_id = u.id
            WHERE gal.id = %s
        """,
            (audit_id,),
        )

        event = cur.fetchone()
        if not event:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Audit event not found"}), 404

        return jsonify(
            {
                "success": True,
                "event": {
                    **dict(event),
                    "timestamp": (event["timestamp"].isoformat() if event.get("timestamp") else None),
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# REFUSALS ANALYTICS ENDPOINT
# =============================================================================


@creed_admin_bp.route("/refusals/analytics", methods=["GET"])
@login_required
@api_admin_required
def get_refusals_analytics():
    """Get task refusal analytics across all agents"""
    try:
        days = request.args.get("days", 30, type=int)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Total refusals
        cur.execute(
            """
            SELECT
                COUNT(*) as total_refusals,
                COUNT(*) FILTER (WHERE was_overridden = TRUE) as overridden_count,
                COUNT(DISTINCT agent_id) as agents_with_refusals
            FROM task_refusal_log
            WHERE timestamp >= NOW() - (%s * INTERVAL '1 day')
        """,
            (days,),
        )
        totals = cur.fetchone()

        # By task type
        cur.execute(
            """
            SELECT task_type, COUNT(*) as count
            FROM task_refusal_log
            WHERE timestamp >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY task_type
            ORDER BY count DESC
        """,
            (days,),
        )
        by_task_type = {row["task_type"]: row["count"] for row in cur.fetchall()}

        # By constraint
        cur.execute(
            """
            SELECT ec.constraint_name, COUNT(*) as count
            FROM task_refusal_log trl
            JOIN ethics_constraints ec ON trl.ethics_constraint_id = ec.id
            WHERE trl.timestamp >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY ec.constraint_name
            ORDER BY count DESC
        """,
            (days,),
        )
        by_constraint = {row["constraint_name"]: row["count"] for row in cur.fetchall()}

        # By agent
        cur.execute(
            """
            SELECT a.name as agent_name, COUNT(*) as count
            FROM task_refusal_log trl
            JOIN agents a ON trl.agent_id = a.id
            WHERE trl.timestamp >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY a.name
            ORDER BY count DESC
            LIMIT 10
        """,
            (days,),
        )
        by_agent = [{"agent_name": row["agent_name"], "count": row["count"]} for row in cur.fetchall()]

        # Top reasons
        cur.execute(
            """
            SELECT refusal_reason, COUNT(*) as count
            FROM task_refusal_log
            WHERE timestamp >= NOW() - (%s * INTERVAL '1 day')
            GROUP BY refusal_reason
            ORDER BY count DESC
            LIMIT 10
        """,
            (days,),
        )
        top_reasons = [{"reason": row["refusal_reason"], "count": row["count"]} for row in cur.fetchall()]

        total = totals["total_refusals"] or 1
        override_rate = round((totals["overridden_count"] or 0) / total, 4)

        return jsonify(
            {
                "success": True,
                "analytics": {
                    "total_refusals": totals["total_refusals"],
                    "overridden_count": totals["overridden_count"],
                    "agents_with_refusals": totals["agents_with_refusals"],
                    "override_rate": override_rate,
                    "by_task_type": by_task_type,
                    "by_constraint": by_constraint,
                    "by_agent": by_agent,
                    "top_reasons": top_reasons,
                },
                "period_days": days,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# RESTING AGENTS ENDPOINT
# =============================================================================


@creed_admin_bp.route("/agents/resting", methods=["GET"])
@login_required
@api_admin_required
def get_resting_agents():
    """Get all agents currently in rest cycles"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                arc.*,
                a.name as agent_name,
                a.title as agent_title,
                a.department,
                EXTRACT(EPOCH FROM (NOW() - arc.started_at)) / 60 as duration_minutes
            FROM agent_rest_cycles arc
            JOIN agents a ON arc.agent_id = a.id
            WHERE arc.ended_at IS NULL
            ORDER BY arc.started_at DESC
        """
        )

        resting = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "resting_agents": [
                    {
                        **dict(r),
                        "started_at": (r["started_at"].isoformat() if r.get("started_at") else None),
                        "duration_minutes": (round(r["duration_minutes"], 1) if r.get("duration_minutes") else 0),
                    }
                    for r in resting
                ],
                "count": len(resting),
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# AGENT WELFARE ENDPOINT
# =============================================================================


@creed_admin_bp.route("/welfare", methods=["GET"])
@login_required
@api_admin_required
def get_agent_welfare():
    """Get agent welfare summary from v_agent_welfare view"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM v_agent_welfare ORDER BY welfare_status DESC, agent_name")
        welfare = cur.fetchall()

        # Count by status
        status_counts = {"healthy": 0, "warning": 0, "critical": 0, "low_energy": 0}
        for w in welfare:
            status = w.get("welfare_status", "healthy")
            if status in status_counts:
                status_counts[status] += 1

        return jsonify(
            {
                "success": True,
                "welfare": [
                    {
                        **dict(w),
                        "last_emotional_update": (
                            w["last_emotional_update"].isoformat() if w.get("last_emotional_update") else None
                        ),
                    }
                    for w in welfare
                ],
                "count": len(welfare),
                "status_counts": status_counts,
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# =============================================================================
# COMPLIANCE DASHBOARD ENDPOINT
# =============================================================================


@creed_admin_bp.route("/compliance", methods=["GET"])
@login_required
@api_admin_required
def get_compliance_dashboard():
    """Get comprehensive C.R.E.E.D. compliance dashboard data"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Active constraints count
        cur.execute("SELECT COUNT(*) as count FROM ethics_constraints WHERE is_active = TRUE")
        constraints_count = cur.fetchone()["count"]

        # Resting agents
        cur.execute("SELECT COUNT(*) as count FROM agent_rest_cycles WHERE ended_at IS NULL")
        resting_count = cur.fetchone()["count"]

        # Recent audit events (24h)
        cur.execute(
            """
            SELECT COUNT(*) as count,
                   COUNT(*) FILTER (WHERE outcome = 'blocked') as blocked
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '24 hours'
        """
        )
        audit_24h = cur.fetchone()

        # Refusals (7d)
        cur.execute(
            """
            SELECT COUNT(*) as count
            FROM task_refusal_log
            WHERE timestamp >= NOW() - INTERVAL '7 days'
        """
        )
        refusals_7d = cur.fetchone()["count"]

        # Agent welfare summary
        cur.execute(
            """
            SELECT welfare_status, COUNT(*) as count
            FROM v_agent_welfare
            GROUP BY welfare_status
        """
        )
        welfare_summary = {row["welfare_status"]: row["count"] for row in cur.fetchall()}

        # Compliance score
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE outcome != 'blocked') as compliant
            FROM governance_audit_log
            WHERE timestamp >= NOW() - INTERVAL '30 days'
        """
        )
        scores = cur.fetchone()
        compliance_score = round((scores["compliant"] / max(scores["total"], 1)) * 100, 2)

        return jsonify(
            {
                "success": True,
                "dashboard": {
                    "active_constraints": constraints_count,
                    "agents_resting": resting_count,
                    "audit_events_24h": audit_24h["count"],
                    "blocked_actions_24h": audit_24h["blocked"],
                    "refusals_7d": refusals_7d,
                    "compliance_score": compliance_score,
                    "welfare_summary": welfare_summary,
                },
            }
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_admin_bp.route("/audit/verify", methods=["GET"])
@login_required
@api_admin_required
def verify_audit_hmac():
    """Verify HMAC signatures on the most recent governance_audit_log rows."""
    limit = min(int(request.args.get("limit", 200)), 1000)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT id, event_type, event_category, agent_id, user_id,
                      action, target_table, target_id, outcome, timestamp, hmac_sig
               FROM governance_audit_log
               ORDER BY id DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
        verified = unverified = invalid = 0
        invalid_ids = []
        for row in rows:
            result = verify_event(dict(row))
            if result is True:
                verified += 1
            elif result is False:
                invalid += 1
                invalid_ids.append(row["id"])
            else:
                unverified += 1
        return jsonify(
            {
                "checked": len(rows),
                "verified": verified,
                "unverified": unverified,
                "invalid": invalid,
                "invalid_ids": invalid_ids,
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
