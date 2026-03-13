"""ComfyUI fleet manager — discovers instances, classifies GPU tiers, ranks nodes.

Wraps ai_bridge.comfyui_service for local ComfyUI. Queries remote_nodes
for fleet-wide ComfyUI status reported via heartbeat.
"""

import logging
from typing import Dict, List, Optional, Tuple

from database import get_db_cursor

logger = logging.getLogger(__name__)

# GPU tier definitions — VRAM thresholds and supported features
GPU_TIERS = {
    "high": {
        "min_vram_mb": 24576,
        "features": [
            "sdxl",
            "animatediff_sdxl",
            "ip_adapter",
            "instantid",
            "large_batch",
        ],
    },
    "mid": {
        "min_vram_mb": 10240,
        "features": ["sdxl", "animatediff_sd15", "ip_adapter", "instantid"],
    },
    "base": {
        "min_vram_mb": 6144,
        "features": ["sd15", "sdxl_single", "animatediff_sd15", "ip_adapter_tight"],
    },
    "cpu": {
        "min_vram_mb": 0,
        "features": ["sd15_slow", "tts"],
    },
}

# Map operations to minimum required features
OPERATION_REQUIREMENTS = {
    "image_sd15": "sd15",
    "image_sdxl": "sdxl",
    "animatediff_sd15": "animatediff_sd15",
    "animatediff_sdxl": "animatediff_sdxl",
    "ip_adapter": "ip_adapter",
    "instantid": "instantid",
}


def classify_gpu_tier(vram_mb: int) -> str:
    """Classify a GPU into a capability tier based on VRAM."""
    for tier_name in ["high", "mid", "base"]:
        if vram_mb >= GPU_TIERS[tier_name]["min_vram_mb"]:
            return tier_name
    return "cpu"


def tier_supports_feature(tier: str, feature: str) -> bool:
    """Check if a GPU tier supports a specific feature."""
    tier_def = GPU_TIERS.get(tier, GPU_TIERS["cpu"])
    return feature in tier_def["features"]


def get_fleet_comfyui_status() -> List[Dict]:
    """Get ComfyUI status for all nodes including Starbase.

    Returns list of dicts with node_id, node_name, comfyui_healthy,
    vram_mb, gpu_name, gpu_tier, and supported features.
    """
    from ai_bridge.comfyui_service import get_comfyui_service

    nodes = []

    # Starbase (local) ComfyUI
    try:
        svc = get_comfyui_service()
        healthy = svc.health_check()
        stats = svc.get_system_stats() if healthy else {}
        vram_mb = 0
        gpu_name = "Unknown"
        if stats:
            devices = stats.get("devices", [])
            if devices:
                dev = devices[0]
                vram_mb = int(dev.get("vram_total", 0) / (1024 * 1024))
                gpu_name = dev.get("name", "Unknown")
        tier = classify_gpu_tier(vram_mb)
        nodes.append(
            {
                "node_id": None,
                "node_name": "Archie Starbase",
                "is_local": True,
                "comfyui_healthy": healthy,
                "vram_mb": vram_mb,
                "gpu_name": gpu_name,
                "gpu_tier": tier,
                "features": GPU_TIERS[tier]["features"],
            }
        )
    except Exception as e:
        logger.warning(f"Failed to check local ComfyUI: {e}")
        nodes.append(
            {
                "node_id": None,
                "node_name": "Archie Starbase",
                "is_local": True,
                "comfyui_healthy": False,
                "vram_mb": 0,
                "gpu_name": "Unknown",
                "gpu_tier": "cpu",
                "features": [],
            }
        )

    # Fleet nodes — read GPU info from remote_nodes.metadata
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, node_name, metadata, last_heartbeat,
                       EXTRACT(EPOCH FROM (NOW() - last_heartbeat)) as heartbeat_age_s
                FROM remote_nodes
                WHERE status = 'online'
                ORDER BY node_name
                """
            )
            for row in cur.fetchall():
                meta = row["metadata"] or {}
                gpu_info = meta.get("gpu", {})
                vram_mb = gpu_info.get("vram_mb", 0)
                gpu_name = gpu_info.get("name", "Unknown")
                tier = gpu_info.get("tier") or classify_gpu_tier(vram_mb)
                comfyui_ok = meta.get("comfyui_healthy", False)
                # Stale heartbeat (>2 min) = unhealthy
                if row["heartbeat_age_s"] and row["heartbeat_age_s"] > 120:
                    comfyui_ok = False
                nodes.append(
                    {
                        "node_id": row["id"],
                        "node_name": row["node_name"],
                        "is_local": False,
                        "comfyui_healthy": comfyui_ok,
                        "vram_mb": vram_mb,
                        "gpu_name": gpu_name,
                        "gpu_tier": tier,
                        "features": GPU_TIERS.get(tier, GPU_TIERS["cpu"])["features"],
                    }
                )
    except Exception as e:
        logger.warning(f"Failed to query fleet nodes: {e}")

    return nodes


def get_available_models() -> List[Dict]:
    """Get available ComfyUI checkpoints from local instance."""
    from ai_bridge.comfyui_service import get_comfyui_service

    try:
        svc = get_comfyui_service()
        models = svc.get_models()
        return [{"name": m, "source": "local"} for m in models]
    except Exception as e:
        logger.warning(f"Failed to get models: {e}")
        return []


def can_node_handle(node_status: Dict, operation: str) -> bool:
    """Check if a node can handle the requested operation."""
    if not node_status.get("comfyui_healthy"):
        return False
    required_feature = OPERATION_REQUIREMENTS.get(operation)
    if not required_feature:
        return True
    return required_feature in node_status.get("features", [])


def rank_nodes_for_operation(operation: str) -> List[Dict]:
    """Return fleet nodes ranked best-first for a given operation.

    Filters to capable + healthy nodes, sorts by VRAM descending.
    """
    fleet = get_fleet_comfyui_status()
    capable = [n for n in fleet if can_node_handle(n, operation)]
    capable.sort(key=lambda n: n["vram_mb"], reverse=True)
    return capable


def build_txt2img_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
) -> Dict:
    """Build a ComfyUI txt2img workflow JSON for the /prompt API.

    Returns a workflow dict with nodes:
    1: CheckpointLoaderSimple, 2: EmptyLatentImage,
    3: CLIPTextEncode (positive), 4: CLIPTextEncode (negative),
    5: KSampler, 6: VAEDecode, 7: SaveImage
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**63)

    return {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt or "blurry, low quality, distorted, deformed",
                    "clip": ["1", 1],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["2", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {"images": ["6", 0], "filename_prefix": "media_studio"},
            },
        }
    }
