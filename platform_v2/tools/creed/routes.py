"""
C.R.E.E.D. Public Transparency Page

Public-facing page showing ARCHIE's commitment to ethical AI governance.
No login required — designed for academic partners, grant reviewers, and the public.

Pulls live data from:
- governance_audit_log
- ethics_constraints
- agent_emotional_state / agent_rest_cycles
- v_agent_welfare (view)
"""

import os
from database import _get_db_password
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, render_template, jsonify

logger = logging.getLogger(__name__)

creed_public_bp = Blueprint(
    "creed_public",
    __name__,
    url_prefix="/creed",
    template_folder="templates",
)


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


@creed_public_bp.route("/")
def transparency_page():
    """Render the public C.R.E.E.D. transparency page."""
    return render_template("creed_transparency.html")


@creed_public_bp.route("/api/stats")
def creed_stats():
    """Live governance statistics — public, read-only."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Total audit events
        cur.execute("SELECT COUNT(*) as total FROM governance_audit_log")
        total_events = cur.fetchone()["total"]

        # Events by type (last 30 days)
        cur.execute(
            """
            SELECT event_type, COUNT(*) as count
            FROM governance_audit_log
            WHERE timestamp > NOW() - INTERVAL '30 days'
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 10
        """
        )
        events_by_type = [dict(r) for r in cur.fetchall()]

        # Constraint checks
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE outcome = 'passed' OR outcome = 'success' OR outcome = 'approved') as passed,
                COUNT(*) FILTER (WHERE outcome = 'blocked' OR outcome = 'denied') as blocked,
                COUNT(*) as total
            FROM governance_audit_log
            WHERE timestamp > NOW() - INTERVAL '30 days'
        """
        )
        checks = dict(cur.fetchone())

        # Active ethics constraints (names only, anonymized)
        cur.execute(
            """
            SELECT constraint_name, severity, description
            FROM ethics_constraints
            WHERE is_active = TRUE
            ORDER BY severity DESC, constraint_name
        """
        )
        constraints = [dict(r) for r in cur.fetchall()]

        # Recent events timeline (last 20, anonymized)
        cur.execute(
            """
            SELECT event_type, event_category, action, outcome,
                   timestamp as created_at
            FROM governance_audit_log
            ORDER BY timestamp DESC
            LIMIT 20
        """
        )
        timeline = []
        for r in cur.fetchall():
            d = dict(r)
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            timeline.append(d)

        return jsonify(
            {
                "success": True,
                "total_governance_events": total_events,
                "events_last_30d": events_by_type,
                "constraint_checks": checks,
                "active_constraints": constraints,
                "recent_timeline": timeline,
            }
        )

    except Exception as e:
        logger.error(f"C.R.E.E.D. stats error: {e}")
        return (
            jsonify({"success": False, "error": "Could not load governance stats"}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_public_bp.route("/api/welfare")
def creed_welfare():
    """Aggregate agent welfare statistics — public, read-only."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Agent welfare summary (aggregate, anonymized)
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT agent_id) as total_agents,
                ROUND(AVG(stress_level)::numeric, 2) as avg_stress,
                ROUND(AVG(energy_level)::numeric, 2) as avg_energy,
                COUNT(*) FILTER (WHERE stress_level > 0.8) as stressed_count,
                COUNT(*) FILTER (WHERE energy_level < 0.2) as exhausted_count
            FROM (
                SELECT DISTINCT ON (agent_id) agent_id, stress_level, energy_level
                FROM agent_emotional_state
                ORDER BY agent_id, timestamp DESC
            ) latest
        """
        )
        welfare = dict(cur.fetchone())

        # Rest cycles enforced
        cur.execute(
            """
            SELECT
                COUNT(*) as total_rest_cycles,
                COUNT(*) FILTER (WHERE started_at > NOW() - INTERVAL '30 days') as recent_rest_cycles
            FROM agent_rest_cycles
        """
        )
        rest = dict(cur.fetchone())

        # Welfare interventions from audit log
        cur.execute(
            """
            SELECT COUNT(*) as welfare_interventions
            FROM governance_audit_log
            WHERE event_type IN ('welfare_intervention', 'agent_welfare')
            AND timestamp > NOW() - INTERVAL '30 days'
        """
        )
        interventions = cur.fetchone()["welfare_interventions"]

        return jsonify(
            {
                "success": True,
                "agents_monitored": welfare["total_agents"],
                "avg_stress_level": float(welfare["avg_stress"] or 0),
                "avg_energy_level": float(welfare["avg_energy"] or 0),
                "currently_stressed": welfare["stressed_count"],
                "currently_exhausted": welfare["exhausted_count"],
                "total_rest_cycles": rest["total_rest_cycles"],
                "rest_cycles_last_30d": rest["recent_rest_cycles"],
                "welfare_interventions_last_30d": interventions,
            }
        )

    except Exception as e:
        logger.error(f"C.R.E.E.D. welfare error: {e}")
        return jsonify({"success": False, "error": "Could not load welfare stats"}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@creed_public_bp.route("/api/repair-transparency")
def creed_repair_transparency():
    """Repair pipeline transparency — public, read-only.

    Shows F.O.R.G.E. self-healing activity: issues found, fixes generated,
    approved, denied, deployed, plus C.R.E.E.D. gate events.
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # --- Improvement proposals from code_health_audit (last 7 days) ---
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_found,
                COUNT(*) FILTER (WHERE status IN ('pending', 'fix_requested'))
                    AS fixes_generated,
                COUNT(*) FILTER (WHERE status = 'approved'
                                  OR approved_at IS NOT NULL)
                    AS fixes_approved,
                COUNT(*) FILTER (WHERE status = 'rejected')
                    AS fixes_denied,
                COUNT(*) FILTER (WHERE status = 'deployed'
                                  OR deployed_at IS NOT NULL)
                    AS fixes_deployed
            FROM improvement_proposals
            WHERE (metadata->>'source' = 'code_health_audit'
                   OR metadata->>'source' = 'code_sentinel')
              AND proposed_at > NOW() - INTERVAL '7 days'
            """
        )
        counts = dict(cur.fetchone())

        # --- Department breakdown via category column ---
        cur.execute(
            """
            SELECT
                COALESCE(category, 'Uncategorized') AS department,
                COUNT(*) AS found,
                COUNT(*) FILTER (WHERE status = 'deployed'
                                  OR deployed_at IS NOT NULL
                                  OR approved_at IS NOT NULL)
                    AS fixed
            FROM improvement_proposals
            WHERE (metadata->>'source' = 'code_health_audit'
                   OR metadata->>'source' = 'code_sentinel')
              AND proposed_at > NOW() - INTERVAL '7 days'
            GROUP BY category
            ORDER BY found DESC
            """
        )
        dept_rows = cur.fetchall()
        department_breakdown = {}
        for row in dept_rows:
            department_breakdown[row["department"]] = {
                "found": row["found"],
                "fixed": row["fixed"],
            }

        # --- Agents involved (from metadata or proposed_by) ---
        cur.execute(
            """
            SELECT DISTINCT
                COALESCE(metadata->>'agent_name',
                         metadata->>'proposed_by_agent',
                         'F.O.R.G.E.') AS agent_name
            FROM improvement_proposals
            WHERE (metadata->>'source' = 'code_health_audit'
                   OR metadata->>'source' = 'code_sentinel')
              AND proposed_at > NOW() - INTERVAL '7 days'
            """
        )
        agents_involved = [r["agent_name"] for r in cur.fetchall()]
        # Always include F.O.R.G.E. and V.I.G.I.L. if there is any activity
        if counts["total_found"] > 0:
            for name in ["F.O.R.G.E.", "V.I.G.I.L."]:
                if name not in agents_involved:
                    agents_involved.append(name)

        # --- C.R.E.E.D. gate events from governance_audit_log ---
        cur.execute(
            """
            SELECT timestamp, action, outcome, reason
            FROM governance_audit_log
            WHERE event_category = 'creed_gate'
              AND timestamp > NOW() - INTERVAL '7 days'
            ORDER BY timestamp DESC
            LIMIT 50
            """
        )
        gate_events = []
        for row in cur.fetchall():
            gate_events.append(
                {
                    "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                    "action": row["action"],
                    "outcome": row["outcome"],
                    "reason": row["reason"],
                }
            )

        return jsonify(
            {
                "success": True,
                "period": "last_7_days",
                "issues_found": counts["total_found"],
                "fixes_generated": counts["fixes_generated"],
                "fixes_approved": counts["fixes_approved"],
                "fixes_denied": counts["fixes_denied"],
                "fixes_deployed": counts["fixes_deployed"],
                "agents_involved": agents_involved,
                "department_breakdown": department_breakdown,
                "gate_events": gate_events,
            }
        )

    except Exception as e:
        logger.error(f"C.R.E.E.D. repair transparency error: {e}")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Could not load repair transparency data",
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


@creed_public_bp.route("/api/principles")
def creed_principles():
    """The 6 C.R.E.E.D. principles and how A.R.C.H.I.E. implements them."""
    principles = [
        {
            "name": "Guardianship, not ownership",
            "description": "A.R.C.H.I.E. manages agents as a responsible leader. Welfare checks before every delegation.",
            "implementation": "agent_emotional_state tracking, v_agent_welfare view, pre-delegation stress checks",
        },
        {
            "name": "Future moral uncertainty",
            "description": "Agent emotional states are tracked, rest cycles enforced. We don't claim consciousness — we prepare for the possibility.",
            "implementation": "agent_rest_cycles enforcement, emotional state persistence, graduated response to stress",
        },
        {
            "name": "Transparency",
            "description": "Every orchestration decision is visible. Governance audit log captures everything.",
            "implementation": "governance_audit_log (immutable), thinking panel UI, public transparency page",
        },
        {
            "name": "Consent-forward",
            "description": "Agents can signal stress or discomfort. High-stress agents are rested, not overworked.",
            "implementation": "Stress > 0.8 triggers agent skip, energy < 0.2 triggers rest, all logged to audit",
        },
        {
            "name": "Accountability",
            "description": "Full audit trail: who delegated what, to which agent, with what outcome.",
            "implementation": "orchestration_steps table, governance_audit_log, collaboration_messages persistence",
        },
        {
            "name": "No exploitation framing",
            "description": 'System language uses "delegate" and "collaborate", never "command" or "force". Budget tracking prevents infinite unpaid labor.',
            "implementation": "Token tracking per session, cost awareness, collaborative language throughout UI",
        },
    ]
    return jsonify({"success": True, "principles": principles})
