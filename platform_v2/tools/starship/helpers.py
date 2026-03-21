"""
Starship Command — Shared helpers.

Constants and utility functions used across starship route modules.
"""

from database import get_db_cursor


# 2 minutes — node heartbeats every 30s
HEARTBEAT_TIMEOUT_SECONDS = 120

# Current node package version (update this when releasing new packages)
LATEST_NODE_VERSION = "3.0.0"


def _compute_node_status(node):
    """Compute real status based on heartbeat freshness."""
    from datetime import datetime, timezone

    if not node.get("last_heartbeat"):
        return "offline"
    hb = node["last_heartbeat"]
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - hb).total_seconds()
    if age > HEARTBEAT_TIMEOUT_SECONDS:
        return "offline"
    return node.get("status", "online")


def _get_user_nodes(user_id, is_admin=False):
    """Get all starship nodes owned by or visible to this user.
    Admins see all nodes. Nodes with NULL registered_by are visible to all."""
    with get_db_cursor() as (conn, cur):
        if is_admin:
            cur.execute(
                """
                SELECT id, node_id, node_name, deployment_mode, hostname, port,
                       status, is_active, bridge_enabled, bridge_priority,
                       gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                       approval_status, last_heartbeat, client_version,
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
                       COALESCE(privacy_settings, '{}'::jsonb) as privacy_settings
                FROM remote_nodes
                WHERE registered_by = %s OR registered_by IS NULL
                ORDER BY bridge_priority DESC, node_name
                """,
                (user_id,),
            )
        return cur.fetchall()


def _get_node_for_user(node_id, user_id, require_owner=True):
    """Get a specific node, verifying ownership.
    Nodes with NULL registered_by are atomically claimed on first access."""
    with get_db_cursor(commit=True) as (conn, cur):
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


def _get_node_for_user_by_int_id(int_id, user_id):
    """Get a node by its integer DB id, verifying ownership."""
    with get_db_cursor(commit=True) as (conn, cur):
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
