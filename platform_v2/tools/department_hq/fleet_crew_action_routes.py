"""Department HQ fleet crew editing and assignment routes."""

import json
import logging
from flask import jsonify, request
from flask_login import current_user
from database import get_db_cursor, check_fleet_model_unique
from .fleet_helpers import _get_node_for_user_by_int_id

logger = logging.getLogger(__name__)


def register_crew_action_routes(bp, auth_decorator):
    """Register crew editing routes with the supplied authentication guard."""

    @bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>", methods=["PUT"])
    @auth_decorator
    def api_update_node_agent(node_id, agent_id):
        """Update a node agent and trigger smart sync."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        user_id = current_user.id
        node = _get_node_for_user_by_int_id(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Get current agent
                cur.execute(
                    "SELECT id, name, config_version FROM node_agents WHERE id = %s AND node_id = %s",
                    (agent_id, node_id),
                )
                agent = cur.fetchone()
                if not agent:
                    return (
                        jsonify({"success": False, "error": "Agent not found"}),
                        404,
                    )

                # Fleet-wide unique model constraint
                new_model = data.get("model")
                if new_model:
                    is_unique, conflict = check_fleet_model_unique(cur, new_model, exclude_node_agent_id=agent_id)
                    if not is_unique:
                        return (
                            jsonify({"success": False, "error": conflict}),
                            409,
                        )

                # Update fields
                new_version = (agent["config_version"] or 1) + 1
                cur.execute(
                    """
                    UPDATE node_agents SET
                        first_name = COALESCE(%s, first_name),
                        last_name = COALESCE(%s, last_name),
                        display_name = COALESCE(%s, display_name),
                        title = COALESCE(%s, title),
                        model = COALESCE(%s, model),
                        system_prompt = COALESCE(%s, system_prompt),
                        config_version = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        data.get("first_name"),
                        data.get("last_name"),
                        ((data.get("first_name", "") or "") + " " + (data.get("last_name", "") or "")).strip() or None,
                        data.get("title"),
                        data.get("model"),
                        data.get("system_prompt"),
                        new_version,
                        agent_id,
                    ),
                )

                # Smart sync: write/update agent_config in mesh_sync_log
                cur.execute("SELECT node_id FROM remote_nodes WHERE id = %s", (node_id,))
                node_rec = cur.fetchone()
                if node_rec:
                    node_id_str = node_rec["node_id"]

                    # Debounce: check for existing unack'd agent_config sync (5s window)
                    cur.execute(
                        """
                        SELECT id FROM mesh_sync_log
                        WHERE node_id = %s AND sync_type = 'agent_config'
                          AND status = 'sent' AND ack_at IS NULL
                          AND sent_at > NOW() - INTERVAL '5 seconds'
                        ORDER BY sent_at DESC LIMIT 1
                        """,
                        (node_id_str,),
                    )
                    existing = cur.fetchone()

                    # Build sync payload with updated agent info
                    cur.execute(
                        """
                        SELECT na.name, na.display_name, na.title, na.model,
                               na.system_prompt, na.capabilities, na.station_codes,
                               na.is_allowed, na.status
                        FROM node_agents na
                        WHERE na.node_id = %s AND na.status = 'active'
                        ORDER BY na.display_name
                        """,
                        (node_id,),
                    )
                    agents = cur.fetchall()
                    payload = json.dumps(
                        {
                            "agents": [dict(a) for a in agents],
                            "agent_count": len(agents),
                            "config_version": new_version,
                        }
                    )

                    if existing:
                        # Update existing sync entry (debounce)
                        cur.execute(
                            "UPDATE mesh_sync_log SET payload = %s, sent_at = NOW() WHERE id = %s",
                            (payload, existing["id"]),
                        )
                        sync_status = "debounced"
                    else:
                        # Create new sync entry
                        cur.execute(
                            """
                            INSERT INTO mesh_sync_log (node_id, sync_type, payload, status, sent_at)
                            VALUES (%s, 'agent_config', %s, 'sent', NOW())
                            """,
                            (node_id_str, payload),
                        )
                        sync_status = "sent"
                else:
                    sync_status = "no_node"

                return jsonify(
                    {
                        "success": True,
                        "config_version": new_version,
                        "sync": sync_status,
                    }
                )
        except Exception:
            logger.exception("Failed to update node agent %s on node %s", agent_id, node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/agents/add", methods=["POST"])
    @auth_decorator
    def api_add_agent_to_node(node_id):
        """Add a cloneable Bridge agent to a node's crew.

        Simple INSERT — validates agent exists and is cloneable,
        checks fleet model uniqueness, then inserts into node_agents.
        """
        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        if not agent_id:
            return jsonify({"success": False, "error": "agent_id required"}), 400

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Fetch the Bridge agent — must be cloneable
                cur.execute(
                    """
                    SELECT a.id, a.name, a.first_name, a.last_name, a.title,
                           a.model, a.system_prompt, a.capabilities,
                           ARRAY[a.department] as station_codes
                    FROM agents a
                    WHERE a.id = %s AND a.is_cloneable = true AND a.status = 'active'
                    """,
                    (agent_id,),
                )
                agent = cur.fetchone()
                if not agent:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Agent not found or not cloneable",
                            }
                        ),
                        400,
                    )

                # Check not already on this node
                cur.execute(
                    "SELECT id FROM node_agents WHERE node_id = %s AND source_agent_id = %s",
                    (node_id, agent_id),
                )
                if cur.fetchone():
                    return (
                        jsonify({"success": False, "error": "Agent already on this node"}),
                        400,
                    )

                # Fleet-wide unique model constraint
                if agent["model"]:
                    is_unique, conflict = check_fleet_model_unique(cur, agent["model"])
                    if not is_unique:
                        return (
                            jsonify({"success": False, "error": conflict}),
                            409,
                        )

                # Build display name from hub agent data
                fname = agent.get("first_name") or agent["name"]
                lname = agent.get("last_name") or ""
                display = f"{fname} {lname}".strip() if lname else fname

                # Filter out NULL station codes from LEFT JOIN
                station_codes = [c for c in (agent["station_codes"] or []) if c is not None]

                cur.execute(
                    """
                    INSERT INTO node_agents
                        (node_id, source_agent_id, hub_agent_id, name,
                         first_name, last_name, display_name, title,
                         model, system_prompt, capabilities,
                         station_codes, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                    ON CONFLICT (node_id, name) DO NOTHING
                    RETURNING id, display_name, name, model, title, station_codes
                    """,
                    (
                        node_id,
                        agent["id"],
                        agent["id"],
                        agent["name"],
                        fname,
                        lname,
                        display,
                        agent["title"],
                        agent["model"],
                        agent["system_prompt"],
                        json.dumps(agent["capabilities"]) if agent["capabilities"] else None,
                        station_codes,
                    ),
                )
                row = cur.fetchone()
                if not row:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Insert conflict — agent may already exist",
                            }
                        ),
                        400,
                    )

                return jsonify(
                    {
                        "success": True,
                        "message": "Agent added",
                        "agent": {
                            "id": row["id"],
                            "display_name": row["display_name"],
                            "name": row["name"],
                            "model": row["model"],
                            "title": row["title"],
                            "station_codes": row["station_codes"],
                        },
                    }
                )
        except Exception:
            logger.exception("Failed to add agent to node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>", methods=["DELETE"])
    @auth_decorator
    def api_remove_agent_from_node(node_id, agent_id):
        """Remove an agent from a node's crew."""
        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "DELETE FROM node_agents WHERE node_id = %s AND id = %s RETURNING id",
                    (node_id, agent_id),
                )
                deleted = cur.fetchone()
                if not deleted:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Agent not found on this node",
                            }
                        ),
                        404,
                    )
            return jsonify({"success": True, "message": "Agent removed"})
        except Exception:
            logger.exception("Failed to remove agent %s from node %s", agent_id, node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/assign-agents", methods=["POST"])
    @auth_decorator
    def api_assign_agents_to_node(node_id):
        """Auto-assign barracked agents to a node based on its hardware capabilities."""
        try:
            # Verify user owns this node
            node = _get_node_for_user_by_int_id(node_id, current_user.id)
            if not node:
                return (
                    jsonify({"success": False, "error": "Node not found or not owned by you"}),
                    404,
                )

            max_agents = request.json.get("max_agents", 5) if request.is_json else 5
            max_agents = min(int(max_agents), 10)  # cap at 10

            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            assigned = dispatcher.assign_agents_to_node(node_id, max_agents=max_agents)

            return jsonify(
                {
                    "success": True,
                    "assigned": assigned,
                    "count": len(assigned),
                    "message": f"Assigned {len(assigned)} agents to node",
                }
            )
        except Exception:
            logger.exception("Failed to assign agents to node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500
