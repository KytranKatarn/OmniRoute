"""Fleet node lookups and model-based crew assignment with caller-owned DB access."""


def get_user_nodes(user_id, is_admin=False, *, db_cursor):
    """Get all starship nodes owned by or visible to this user.
    Admins see all nodes. Nodes with NULL registered_by are visible to all."""
    with db_cursor() as (conn, cur):
        if is_admin:
            cur.execute(
                """
                SELECT id, node_id, node_name, deployment_mode, hostname, port,
                       status, is_active, bridge_enabled, bridge_priority,
                       gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                       approval_status, last_heartbeat, client_version,
                       -- #5218: node_role + mesh_status are what let the caller tell
                       -- "an agent phoned home" apart from "this node is reachable".
                       -- Without them _compute_node_health() degrades to the old
                       -- heartbeat-only verdict.
                       COALESCE(node_role, 'agent') AS node_role,
                       mesh_status, mesh_last_seen, mesh_latency_ms, reachable_port,
                       COALESCE(privacy_settings, '{}'::jsonb) as privacy_settings
                FROM remote_nodes
                ORDER BY bridge_priority DESC, node_name
                """
            )
        else:
            cur.execute(
                """
                SELECT id, node_id, node_name, deployment_mode, hostname, port,
                       status, is_active, bridge_enabled, bridge_priority,
                       gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                       approval_status, last_heartbeat, client_version,
                       -- #5218: node_role + mesh_status are what let the caller tell
                       -- "an agent phoned home" apart from "this node is reachable".
                       -- Without them _compute_node_health() degrades to the old
                       -- heartbeat-only verdict.
                       COALESCE(node_role, 'agent') AS node_role,
                       mesh_status, mesh_last_seen, mesh_latency_ms, reachable_port,
                       COALESCE(privacy_settings, '{}'::jsonb) as privacy_settings
                FROM remote_nodes
                WHERE registered_by = %s OR registered_by IS NULL
                ORDER BY bridge_priority DESC, node_name
                """,
                (user_id,),
            )
        return cur.fetchall()


def get_node_for_user(node_id, user_id, require_owner=True, *, db_cursor):
    """Get a specific node, verifying ownership.
    Nodes with NULL registered_by are atomically claimed on first access."""
    with db_cursor(commit=True) as (conn, cur):
        if require_owner:
            # Try to claim orphan nodes atomically
            cur.execute(
                """UPDATE remote_nodes SET registered_by = %s
                   WHERE node_id = %s AND registered_by IS NULL""",
                (user_id, node_id),
            )
            cur.execute(
                """SELECT * FROM remote_nodes
                   WHERE node_id = %s AND registered_by = %s""",
                (node_id, user_id),
            )
        else:
            cur.execute("SELECT * FROM remote_nodes WHERE node_id = %s", (node_id,))
        return cur.fetchone()


def get_node_for_user_by_int_id(int_id, user_id, *, db_cursor):
    """Get a node by its integer DB id, verifying ownership."""
    with db_cursor(commit=True) as (conn, cur):
        # Claim orphan if needed
        cur.execute(
            """UPDATE remote_nodes SET registered_by = %s
               WHERE id = %s AND registered_by IS NULL""",
            (user_id, int_id),
        )
        cur.execute(
            """SELECT * FROM remote_nodes
               WHERE id = %s AND registered_by = %s""",
            (int_id, user_id),
        )
        return cur.fetchone()


def auto_assign_agents_for_model(node_id_str: str, model_name: str, *, db_cursor) -> int:
    """Auto-assign hub AI agents whose model matches to a fleet node.

    Called after a model becomes available on a node (heartbeat model sync or
    OTA model_pull ack). Inserts into node_agents with auto_assigned=TRUE.
    Skips agents already assigned to this node. Returns count assigned.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        with db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO node_agents
                    (node_id, source_agent_id, hub_agent_id, name, display_name,
                     model, department, status, auto_assigned)
                SELECT
                    rn.id,
                    a.id, a.id,
                    a.name, COALESCE(a.display_name, a.name),
                    a.model, a.department,
                    'active', TRUE
                FROM agents a
                JOIN remote_nodes rn ON rn.node_id = %s
                WHERE a.model = %s
                  AND a.worker_type = 'ai'
                  AND a.shift_state IN ('active', 'barracked')
                  AND NOT EXISTS (
                      SELECT 1 FROM node_agents na2
                      WHERE na2.hub_agent_id = a.id
                        AND na2.node_id = rn.id
                  )
                ON CONFLICT (node_id, name)
                DO UPDATE SET status = 'active', auto_assigned = TRUE
                RETURNING id
                """,
                (node_id_str, model_name),
            )
            count = len(cur.fetchall())
            if count:
                logger.info(
                    "fleet: auto-assigned %d agent(s) with model %s to node %s",
                    count,
                    model_name,
                    node_id_str,
                )
            return count
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "auto_assign_agents_for_model failed for %s/%s: %s", node_id_str, model_name, exc
        )
        return 0
