"""Read-only admission for large-model PR review escalation.

RAM fit / installed weights do not prove a review can finish within its deadline.
Only already-serving GPU placements may opt into the larger review window here.
Loading, eviction, inference and final admission remain Department HQ's concern.
"""

import logging
import math

from services.fleet_resource_router import can_node_run_model, is_stale, node_has_model, score_node_for_model
from services.model_service import ModelService

log = logging.getLogger(__name__)


def _resident_on_gpu(node, model):
    from tools.department_hq.fleet_helpers import node_inter_cluster_host

    host = node_inter_cluster_host(node)
    if not host:
        return False
    port = int(node.get("port") or 11434)
    if not 1 <= port <= 65535:
        return False
    service = ModelService(ollama_host=f"http://{host}:{port}")
    canonical = model.removesuffix(":latest")
    for entry in service.check_loaded_models():
        if (entry.get("name") or "").removesuffix(":latest") != canonical:
            continue
        size = float(entry.get("size") or 0)
        vram = float(entry.get("size_vram") or 0)
        # Reject CPU-only / mostly-offloaded runners, even when the node has a GPU.
        # Unknown/invalid measurements never count as ready.
        if math.isfinite(size) and math.isfinite(vram) and size > 0 and vram >= size * 0.9:
            return True
    return False


def ready_review_nodes(rows, model, *, starships_undocked=False):
    """Rank eligible, fresh, already-GPU-serving nodes; fail closed per candidate.

    This is a readiness snapshot, NOT a reservation or an Academy benchmark win.
    Missing inventory is rejected here even though the generic presence helper
    deliberately permits unknown inventories for other workloads.
    """
    if not model:
        return []
    admitted = []
    for node in rows:
        try:
            if node.get("status") != "online" or node.get("is_active") is not True or is_stale(node):
                continue
            if starships_undocked and node.get("deployment_mode") == "starship":
                continue
            if node.get("ollama_available") is not True or node.get("gpu_available") is not True:
                continue
            extra = node.get("extra_capabilities") or {}
            if not isinstance(extra, dict):
                continue
            inventory = extra.get("ollama_models")
            if not isinstance(inventory, list) or not inventory:
                continue
            limit = int(node.get("max_concurrent") or 0)
            if limit <= 0 or int(node.get("current_load") or 0) >= limit:
                continue
            if not can_node_run_model(node, model) or not node_has_model(node, model):
                continue
            if not _resident_on_gpu(node, model):
                continue
            score = score_node_for_model(node, model)
            # Fit, presence and live residency already admitted this candidate.
            # Generic scoring may demote a statically oversized model to CPU and
            # return None; use that only to rank it last, not undo observed readiness.
            if score is None:
                score = 0.001
            if math.isfinite(score) and node.get("node_id"):
                admitted.append((float(score), str(node["node_id"])))
        except Exception as exc:
            log.warning("Review placement rejected node %s: %s", node.get("node_id"), exc)
    return [node_id for _score, node_id in sorted(admitted, key=lambda item: (-item[0], item[1]))]
