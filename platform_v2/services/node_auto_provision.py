"""Auto-provision a node's recommended warm-set at enrollment (#3732, project #371).

Closes the loop on the hardware-aware wizard (#3731): instead of a human clicking
"Download recommended models" on each new node, this scans approved + online nodes
and queues the GAP between what the hardware recommends (services.node_provisioning)
and what the node already reports having (extra_capabilities.ollama_models /
comfyui_models) into the SAME mesh_sync_log OTA queue the manual button uses.

Idempotent + self-healing: a fully-stocked node is a no-op; a model already present
or with a recent pending pull is skipped, so it never re-queues storms. Gated behind
platform_settings 'node_auto_provision_enabled' (default off) and rate-limited
(max_nodes per cycle) so it can't flood the cluster.
"""

from __future__ import annotations

import json
import logging
import os

from database import get_db_cursor
from services.node_provisioning import recommend_from_node_row

logger = logging.getLogger(__name__)

SETTING_KEY = "node_auto_provision_enabled"
RECENT_PULL_HOURS = 2
CHECKPOINT_DIR = "/comfyui/models/checkpoints"
# Hub serves checkpoints over the mesh at the PREFIXED path (KB #266408).
HUB_CHECKPOINT_BASE = "http://100.64.0.4:3000/tools/department-hq/api/fleet/checkpoints/"


def _is_enabled(cur) -> bool:
    cur.execute("SELECT value FROM platform_settings WHERE key = %s", (SETTING_KEY,))
    row = cur.fetchone()
    if not row:
        return False
    val = row["value"] if isinstance(row, dict) else row[0]
    return str(val).strip().lower() in ("1", "true", "on", "yes", "enabled")


def _ollama_present(model: str, present_full: set, present_bases: set) -> bool:
    """Is *model* already on the node? Handles the ':latest' tag quirk —
    a tagless recommendation (e.g. 'nomic-embed-text') matches a present
    'nomic-embed-text:latest' by base name; a tagged one needs an exact match."""
    if model in present_full:
        return True
    if ":" in model:
        return False
    return model.split(":")[0] in present_bases


def auto_provision_nodes(dry_run: bool = False, max_nodes: int = 2) -> dict:
    """Scan approved+online nodes and queue the recommended-minus-present model gap.

    dry_run=True previews (no inserts, bypasses the enable gate so you can see what
    it WOULD do). Live runs respect the platform_settings gate and rate-limit to
    max_nodes that actually have a gap.
    """
    # In DR mode the hub (checkpoint source) is down and boston-2 has no checkpoint
    # files, so skip ComfyUI checkpoint pulls — they resume after failback. Ollama
    # model_pull is node-local (pulls from the registry) and proceeds normally.
    dr_mode = os.getenv("ARCHIE_DR_MODE", "0") == "1"
    summary = {
        "enabled": False,
        "scanned": 0,
        "provisioned": [],
        "skipped_stocked": 0,
        "dry_run": dry_run,
        "dr_mode": dr_mode,
    }
    with get_db_cursor(commit=not dry_run) as (conn, cur):
        enabled = _is_enabled(cur)
        summary["enabled"] = enabled
        if not dry_run and not enabled:
            return summary

        cur.execute(
            """
            SELECT id, node_id, node_name, cpu_cores, ram_gb, gpu_available,
                   gpu_vram_gb, gpu_model, extra_capabilities
            FROM remote_nodes
            WHERE approval_status = 'approved' AND status = 'online'
              AND last_heartbeat > NOW() - INTERVAL '10 minutes'
              -- wizard-enrolled fleet nodes only; never the hub ('archie-starbase',
              -- which has no node sync agent to drain mesh_sync_log)
              AND (node_id LIKE 'outpost%' OR node_id LIKE 'starship%')
            ORDER BY created_at DESC
            """
        )
        nodes = cur.fetchall()
        summary["scanned"] = len(nodes)

        # Recently queued pulls per node — avoid re-queueing an in-flight download.
        cur.execute(
            """
            SELECT node_id, payload FROM mesh_sync_log
            WHERE sync_type IN ('model_pull', 'checkpoint_pull')
              AND sent_at > NOW() - make_interval(hours => %s)
            """,
            (RECENT_PULL_HOURS,),
        )
        recent: dict = {}
        for r in cur.fetchall():
            payload = r["payload"]
            if not isinstance(payload, dict):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = {}
            key = payload.get("model_name") or payload.get("filename")
            if key:
                recent.setdefault(r["node_id"], set()).add(key)

        acted = 0
        for node in nodes:
            if acted >= max_nodes:
                break
            rec = recommend_from_node_row(node)
            extra = node.get("extra_capabilities") or {}
            present_list = extra.get("ollama_models") or []
            present_full = {str(m) for m in present_list}
            present_bases = {str(m).split(":")[0] for m in present_list}
            present_comfy = {str(m) for m in (extra.get("comfyui_models") or [])}
            node_recent = recent.get(node["node_id"], set())

            to_pull = [
                m
                for m in rec.recommended_ollama
                if not _ollama_present(m, present_full, present_bases) and m not in node_recent
            ]
            ckpt = rec.recommended_comfyui
            pull_ckpt = bool(ckpt and ckpt not in present_comfy and ckpt not in node_recent and not dr_mode)

            if not to_pull and not pull_ckpt:
                summary["skipped_stocked"] += 1
                continue

            if not dry_run:
                for m in to_pull:
                    cur.execute(
                        "INSERT INTO mesh_sync_log (node_id, sync_type, payload, status, sent_at) "
                        "VALUES (%s, 'model_pull', %s, 'sent', NOW())",
                        (node["node_id"], json.dumps({"model_name": m})),
                    )
                if pull_ckpt:
                    cur.execute(
                        "INSERT INTO mesh_sync_log (node_id, sync_type, payload, status, sent_at) "
                        "VALUES (%s, 'checkpoint_pull', %s, 'sent', NOW())",
                        (
                            node["node_id"],
                            json.dumps(
                                {
                                    "url": HUB_CHECKPOINT_BASE + ckpt,
                                    "filename": ckpt,
                                    "checkpoints_dir": CHECKPOINT_DIR,
                                }
                            ),
                        ),
                    )
                logger.info(
                    "[node_auto_provision] queued for %s: ollama=%s ckpt=%s",
                    node["node_name"],
                    to_pull,
                    ckpt if pull_ckpt else None,
                )
            summary["provisioned"].append(
                {
                    "node": node["node_name"],
                    "tier": rec.tier,
                    "models": list(to_pull),
                    "checkpoint": ckpt if pull_ckpt else None,
                }
            )
            acted += 1
    return summary
