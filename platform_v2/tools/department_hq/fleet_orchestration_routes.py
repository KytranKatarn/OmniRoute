"""Fleet Orchestration Routes — Cluster Orchestration panel API (Project #352)."""

import logging
from datetime import datetime, timezone

from flask import jsonify, request

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_orchestration_routes(bp, admin_required):

    @bp.route("/api/orchestration/status")
    @admin_required
    def get_orchestration_status():
        """Live overview: agent overflow scores, queue depths, global pause state.

        Reads agent_overflow_state directly from DB — not the in-memory cache,
        which is per-gunicorn-worker and inconsistent across a 4-worker setup.
        """
        try:
            enriched = []
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT aos.agent_id, aos.capability,
                           aos.overflow_score::float AS score, aos.is_active,
                           a.name AS agent_name, a.department
                    FROM agent_overflow_state aos
                    JOIN agents a ON a.id = aos.agent_id
                    WHERE aos.expires_at > NOW()
                    ORDER BY aos.overflow_score DESC
                    """
                )
                for r in cur.fetchall() or []:
                    enriched.append(
                        {
                            "agent_id": r["agent_id"],
                            "agent_name": r["agent_name"],
                            "department": r["department"],
                            "capability": r["capability"],
                            "score": round(float(r["score"]), 3),
                            "is_active": r["is_active"],
                        }
                    )

            queues = []
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT capability, COUNT(*) AS depth
                    FROM dispatch_pending_queue
                    WHERE status = 'pending'
                    GROUP BY capability ORDER BY depth DESC
                    """
                )
                queues = [{"capability": r["capability"], "depth": r["depth"]} for r in (cur.fetchall() or [])]

            global_paused = False
            with get_db_cursor() as (_, cur):
                cur.execute(
                    "SELECT overflow_paused FROM cluster_orchestration_config " "WHERE scope = 'global' LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    global_paused = bool(row["overflow_paused"])

            return jsonify(
                {
                    "agents": enriched,
                    "queues": queues,
                    "global_paused": global_paused,
                    "last_scan": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as e:
            logger.exception("orchestration/status failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/orchestration/config", methods=["GET"])
    @admin_required
    def get_orchestration_config():
        """Return all orchestration config rows."""
        try:
            with get_db_cursor() as (_, cur):
                cur.execute("SELECT * FROM cluster_orchestration_config ORDER BY scope, id")
                rows = [dict(r) for r in (cur.fetchall() or [])]
            return jsonify({"configs": rows})
        except Exception as e:
            logger.exception("orchestration/config GET failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/orchestration/config", methods=["POST"])
    @admin_required
    def update_orchestration_config():
        """Upsert a config row for a scope/agent/capability/node combination."""
        data = request.get_json() or {}
        scope = data.get("scope", "global")
        agent_id = data.get("agent_id")
        capability = data.get("capability")
        node_id = data.get("node_id")

        allowed = {
            "idle_threshold_minutes",
            "utilization_threshold_pct",
            "queue_pressure_threshold",
            "idle_weight",
            "utilization_weight",
            "queue_pressure_weight",
            "overflow_enabled",
            "overflow_paused",
            "priority_boost",
            "max_overflow_concurrent",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return jsonify({"error": "no valid fields to update"}), 400

        set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
        updates.update(
            {
                "scope": scope,
                "agent_id": agent_id,
                "capability": capability,
                "node_id": node_id,
            }
        )

        try:
            with get_db_cursor(commit=True) as (_, cur):
                # UPDATE first — avoids duplicate rows from INSERT+ON CONFLICT DO NOTHING
                # (ON CONFLICT DO NOTHING only fires on PK conflict, never on scope/agent/etc.)
                cur.execute(
                    f"UPDATE cluster_orchestration_config "
                    f"SET {set_clause}, updated_at=NOW() "
                    f"WHERE scope=%(scope)s "
                    f"AND (agent_id IS NOT DISTINCT FROM %(agent_id)s) "
                    f"AND (capability IS NOT DISTINCT FROM %(capability)s) "
                    f"AND (node_id IS NOT DISTINCT FROM %(node_id)s)",
                    updates,
                )
                if cur.rowcount == 0:
                    # No existing row — insert defaults then apply the requested fields
                    cur.execute(
                        """
                        INSERT INTO cluster_orchestration_config
                            (scope, agent_id, capability, node_id,
                             idle_threshold_minutes, utilization_threshold_pct,
                             queue_pressure_threshold, idle_weight, utilization_weight,
                             queue_pressure_weight, overflow_enabled, overflow_paused,
                             priority_boost, max_overflow_concurrent)
                        VALUES (%(scope)s, %(agent_id)s, %(capability)s, %(node_id)s,
                                5, 60.0, 10, 0.3, 0.3, 0.4, true, false, 0, 3)
                        """,
                        updates,
                    )
            return jsonify({"ok": True})
        except Exception as e:
            logger.exception("orchestration/config POST failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/orchestration/pause", methods=["POST"])
    @admin_required
    def pause_orchestration():
        """Set overflow_paused for a scope/agent/capability."""
        try:
            data = request.get_json() or {}
            scope = data.get("scope", "global")
            agent_id = data.get("agent_id")
            capability = data.get("capability")
            paused = bool(data.get("paused", True))

            with get_db_cursor(commit=True) as (_, cur):
                cur.execute(
                    "UPDATE cluster_orchestration_config "
                    "SET overflow_paused=%s, updated_at=NOW() "
                    "WHERE scope=%s "
                    "AND (agent_id IS NOT DISTINCT FROM %s) "
                    "AND (capability IS NOT DISTINCT FROM %s)",
                    (paused, scope, agent_id, capability),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        """
                        INSERT INTO cluster_orchestration_config
                            (scope, agent_id, capability, overflow_paused)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (scope, agent_id, capability, paused),
                    )
            return jsonify({"ok": True, "paused": paused})
        except Exception as e:
            logger.exception("orchestration/pause failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/orchestration/boost", methods=["POST"])
    @admin_required
    def boost_capability():
        """Set priority_boost for a capability."""
        try:
            data = request.get_json() or {}
            capability = data.get("capability")
            boost = int(data.get("boost", 10))
            if not capability:
                return jsonify({"error": "capability required"}), 400

            with get_db_cursor(commit=True) as (_, cur):
                cur.execute(
                    "UPDATE cluster_orchestration_config "
                    "SET priority_boost=%s, updated_at=NOW() "
                    "WHERE scope='capability' AND capability=%s",
                    (boost, capability),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        """
                        INSERT INTO cluster_orchestration_config
                            (scope, capability, priority_boost)
                        VALUES ('capability', %s, %s)
                        """,
                        (capability, boost),
                    )
            return jsonify({"ok": True, "capability": capability, "boost": boost})
        except Exception as e:
            logger.exception("orchestration/boost failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/orchestration/trigger", methods=["POST"])
    @admin_required
    def trigger_orchestration():
        """Run one scoring cycle synchronously and return summary."""
        try:
            import time as _time
            import json as _json
            from services.cluster_orchestration_service import (
                compute_overflow_score,
                resolve_config,
                update_overflow_cache,
            )
            from services.fleet_resource_router import utilization_pct

            cycle_start = _time.monotonic()

            node_util: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, gpu_vram_gb, ram_gb, last_heartbeat
                    FROM remote_nodes
                    WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                """
                )
                for row in cur.fetchall() or []:
                    node_util[row["id"]] = utilization_pct(dict(row))

            agent_idle: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT a.id,
                           COALESCE(
                               EXTRACT(EPOCH FROM NOW() - MAX(tel.created_at)) / 60,
                               999
                           ) AS idle_minutes
                    FROM agents a
                    LEFT JOIN task_execution_log tel
                        ON tel.agent_name = a.name
                       AND tel.created_at > NOW() - INTERVAL '60 minutes'
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                    GROUP BY a.id
                """
                )
                for row in cur.fetchall() or []:
                    agent_idle[row["id"]] = float(row["idle_minutes"] or 999)

            queue_depths: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT capability, COUNT(*) AS depth
                    FROM dispatch_pending_queue
                    WHERE status = 'pending'
                    GROUP BY capability
                """
                )
                for row in cur.fetchall() or []:
                    queue_depths[row["capability"]] = row["depth"]

            with get_db_cursor() as (_, cur):
                cur.execute("SELECT * FROM cluster_orchestration_config")
                all_configs = [dict(r) for r in (cur.fetchall() or [])]

            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT na.hub_agent_id AS agent_id, na.node_id,
                           sk.skill_name AS capability
                    FROM node_agents na
                    JOIN agents a ON a.id = na.hub_agent_id
                    JOIN agent_skills sk ON sk.agent_id = na.hub_agent_id
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                      AND na.node_id IN (
                          SELECT id FROM remote_nodes
                          WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                      )
                """
                )
                assignments = cur.fetchall() or []

            upsert_rows = []
            for row in assignments:
                agent_id_ = row["agent_id"]
                node_id_ = row["node_id"]
                capability_ = row["capability"]
                cfg = resolve_config(all_configs, agent_id_, capability_, node_id_)
                if not cfg.get("overflow_enabled", True):
                    continue
                score = compute_overflow_score(
                    idle_minutes=agent_idle.get(agent_id_, 999),
                    util_pct=node_util.get(node_id_, 100.0),
                    queue_depth=queue_depths.get(capability_, 0),
                    config=cfg,
                )
                is_active = (score >= 0.5) and not cfg.get("overflow_paused", False)
                upsert_rows.append(
                    {
                        "agent_id": agent_id_,
                        "capability": capability_,
                        "overflow_score": score,
                        "is_active": is_active,
                        "node_id": node_id_,
                        "reason": {
                            "idle_mins": round(agent_idle.get(agent_id_, 999), 1),
                            "util_pct": round(node_util.get(node_id_, 100), 1),
                            "queue_depth": queue_depths.get(capability_, 0),
                        },
                    }
                )

            if upsert_rows:
                with get_db_cursor(commit=True) as (_, cur):
                    for r in upsert_rows:
                        cur.execute(
                            """
                            INSERT INTO agent_overflow_state
                                (agent_id, capability, overflow_score, is_active,
                                 activated_at, expires_at, node_id, reason, updated_at)
                            VALUES (%s, %s, %s, %s,
                                CASE WHEN %s THEN NOW() ELSE NULL END,
                                NOW() + INTERVAL '90 seconds',
                                %s, %s::jsonb, NOW())
                            ON CONFLICT (agent_id, capability) DO UPDATE SET
                                overflow_score = EXCLUDED.overflow_score,
                                is_active      = EXCLUDED.is_active,
                                activated_at   = CASE
                                    WHEN EXCLUDED.is_active
                                     AND NOT agent_overflow_state.is_active
                                    THEN NOW()
                                    ELSE agent_overflow_state.activated_at END,
                                expires_at     = EXCLUDED.expires_at,
                                node_id        = EXCLUDED.node_id,
                                reason         = EXCLUDED.reason,
                                updated_at     = NOW()
                        """,
                            (
                                r["agent_id"],
                                r["capability"],
                                r["overflow_score"],
                                r["is_active"],
                                r["is_active"],
                                r["node_id"],
                                _json.dumps(r["reason"]),
                            ),
                        )

            with get_db_cursor(commit=True) as (_, cur):
                cur.execute("DELETE FROM agent_overflow_state WHERE expires_at < NOW()")

            update_overflow_cache(upsert_rows)
            elapsed_ms = int((_time.monotonic() - cycle_start) * 1000)
            active_count = sum(1 for r in upsert_rows if r["is_active"])
            return jsonify(
                {
                    "ok": True,
                    "scored": len(upsert_rows),
                    "active": active_count,
                    "elapsed_ms": elapsed_ms,
                }
            )
        except Exception as e:
            logger.exception("orchestration/trigger failed")
            return jsonify({"error": str(e)}), 500
