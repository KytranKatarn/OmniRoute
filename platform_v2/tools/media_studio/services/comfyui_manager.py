"""ComfyUI fleet manager — discovers instances, classifies GPU tiers, ranks nodes.

Wraps ai_bridge.comfyui_service for local ComfyUI. Queries remote_nodes
for fleet-wide ComfyUI status reported via heartbeat.
"""

import logging
import os
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

IDENTITY_NODE_NAME = os.getenv("MEDIA_STUDIO_IDENTITY_NODE", "Starship - Defiant - USS-246")
IDENTITY_MODE_PROMPT = "prompt"
IDENTITY_MODE_FACEID = "faceid"
IDENTITY_MODE_INSTANTID = "instantid"
IDENTITY_MODE_FACEID_DETAIL = "faceid_detail"
IDENTITY_MODE_INSTANTID_DETAIL = "instantid_detail"
IDENTITY_MODE_AUTO = "auto"
IDENTITY_MODES = (
    IDENTITY_MODE_PROMPT,
    IDENTITY_MODE_FACEID,
    IDENTITY_MODE_INSTANTID,
    IDENTITY_MODE_FACEID_DETAIL,
    IDENTITY_MODE_INSTANTID_DETAIL,
)
IDENTITY_MODE_VALUES = (IDENTITY_MODE_AUTO,) + IDENTITY_MODES
IDENTITY_MODE_REQUIRES_REFERENCE = frozenset(
    {
        IDENTITY_MODE_FACEID,
        IDENTITY_MODE_INSTANTID,
        IDENTITY_MODE_FACEID_DETAIL,
        IDENTITY_MODE_INSTANTID_DETAIL,
    }
)
IDENTITY_LOCAL_MODELS = frozenset(
    {
        "RealVisXL_V4.0.safetensors",
        "juggernautXL_v9.safetensors",
        "sd_xl_base_1.0.safetensors",
    }
)


def identity_mode_requires_reference(mode: str) -> bool:
    return mode in IDENTITY_MODE_REQUIRES_REFERENCE


def identity_mode_uses_detailer(mode: str) -> bool:
    return mode in {IDENTITY_MODE_FACEID_DETAIL, IDENTITY_MODE_INSTANTID_DETAIL}


def normalize_identity_mode(
    value: Optional[str] = None,
    has_reference: bool = False,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    mode = str(value or IDENTITY_MODE_AUTO).strip().lower()
    if mode not in IDENTITY_MODE_VALUES:
        raise ValueError(f"Unknown portrait identity mode: {mode}")
    if provider and mode != IDENTITY_MODE_PROMPT:
        if mode == IDENTITY_MODE_AUTO:
            mode = IDENTITY_MODE_PROMPT
        else:
            raise ValueError("Character consistency modes require a local ComfyUI provider")
    if mode == IDENTITY_MODE_AUTO:
        mode = (
            IDENTITY_MODE_FACEID_DETAIL
            if has_reference and (model is None or model in IDENTITY_LOCAL_MODELS)
            else IDENTITY_MODE_PROMPT
        )
    if identity_mode_requires_reference(mode) and not has_reference:
        raise ValueError("Character consistency requires an approved canonical reference")
    if mode != IDENTITY_MODE_PROMPT and model and model not in IDENTITY_LOCAL_MODELS:
        raise ValueError("Character consistency is available only for supported SDXL portrait checkpoints")
    return mode


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


def _get_identity_comfyui_url(model_name: Optional[str]) -> Tuple[str, str]:
    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT node_name, extra_capabilities->>'comfyui_url' AS comfyui_url,
                       extra_capabilities->'comfyui_models' AS comfyui_models
                FROM remote_nodes
                WHERE node_name = %s
                  AND status = 'online'
                  AND gpu_available = TRUE
                  AND comfyui_available = TRUE
                  AND extra_capabilities ? 'comfyui_url'
                  AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                LIMIT 1
                """,
                (IDENTITY_NODE_NAME,),
            )
            row = cur.fetchone()
    except Exception as exc:
        raise RuntimeError(f"Identity ComfyUI node {IDENTITY_NODE_NAME} is unavailable") from exc

    if not row or not row.get("comfyui_url"):
        raise RuntimeError(f"Identity ComfyUI node {IDENTITY_NODE_NAME} is unavailable")

    fleet_models = row.get("comfyui_models") or []
    if isinstance(fleet_models, str):
        import json as _json

        try:
            fleet_models = _json.loads(fleet_models)
        except (TypeError, ValueError):
            fleet_models = []
    if model_name and model_name not in fleet_models:
        raise RuntimeError(f"Identity model {model_name} is not installed on {IDENTITY_NODE_NAME}")
    return row["comfyui_url"], row["node_name"]


def get_best_comfyui_url(
    model_name: Optional[str] = None,
    identity_mode: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Return (comfyui_url, node_name) for the best available ComfyUI node.

    Prefers fleet nodes with higher VRAM over hub — RTX Starships beat the
    hub's Quadro M4000 for image generation throughput. Falls back to hub on
    any error or when no fleet node is healthy.

    If model_name is provided, only routes to a fleet node when that model
    is listed in extra_capabilities['comfyui_models'] — prevents 400 errors
    for models that haven't been transferred to the fleet node yet.

    Uses extra_capabilities.comfyui_url + gpu_vram_gb from remote_nodes
    (populated by heartbeat), not metadata.gpu which is unreliable.
    Identity modes fail closed to the configured identity node instead of
    falling back to a node without the required model stack.
    """

    if identity_mode and identity_mode != IDENTITY_MODE_PROMPT:
        return _get_identity_comfyui_url(model_name)

    hub_url = os.environ.get("COMFYUI_HOST", "http://host.docker.internal:8188")
    hub_vram_mb = 8192  # Quadro M4000 8 GB

    # #5332: UNDOCKED Starships are left alone — this selector actively PREFERS
    # them (ORDER BY gpu_vram_gb DESC), so without this gate an undocked ship
    # still got image-gen work. Fail-open on any predicate error.
    _exclude_starships = False
    try:
        from tools.department_hq.fleet_helpers import is_starships_undocked

        _exclude_starships = is_starships_undocked()
    except Exception:
        pass

    try:
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT node_name, gpu_vram_gb,
                       extra_capabilities->>'comfyui_url' AS comfyui_url,
                       extra_capabilities->'comfyui_models' AS comfyui_models
                FROM remote_nodes
                WHERE status = 'online'
                  AND gpu_available = TRUE
                  AND extra_capabilities ? 'comfyui_url'
                  AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                  AND (%s = FALSE OR deployment_mode IS DISTINCT FROM 'starship')
                ORDER BY gpu_vram_gb DESC NULLS LAST
                LIMIT 1
                """,
                (_exclude_starships,),
            )
            row = cur.fetchone()

        if row and row["comfyui_url"]:
            fleet_url = row["comfyui_url"]
            fleet_vram_mb = int((row["gpu_vram_gb"] or 0) * 1024)
            # Only prefer fleet node if it has comparable or more VRAM
            if fleet_vram_mb >= hub_vram_mb * 0.75:
                # Model availability check — only route to fleet if model is known there
                if model_name:
                    import json as _json

                    fleet_models = row.get("comfyui_models") or []
                    if isinstance(fleet_models, str):
                        fleet_models = _json.loads(fleet_models)
                    if model_name not in fleet_models:
                        logger.info(
                            "[ComfyUI] Model %s not on fleet node %s — falling back to hub",
                            model_name,
                            row["node_name"],
                        )
                        return hub_url, None
                # Heartbeat freshness already confirms node is alive — skip live ping
                # (live ping times out under SDXL inference load, causing false fallbacks)
                logger.info(
                    "[ComfyUI] Fleet routing → %s (%s) %d MB VRAM",
                    row["node_name"],
                    fleet_url,
                    fleet_vram_mb,
                )
                return fleet_url, row["node_name"]
    except Exception as exc:
        logger.debug("[ComfyUI] Fleet discovery failed: %s", exc)

    return hub_url, None


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


def build_identity_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 30,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    reference_image: str = "",
    identity_mode: str = IDENTITY_MODE_FACEID,
    identity_weight: float = 0.85,
    detailer_denoise: float = 0.28,
) -> Dict:
    """Build a modern FaceID, InstantID, or detailer portrait workflow."""
    import random

    mode = str(identity_mode or IDENTITY_MODE_PROMPT).strip().lower()
    if mode not in IDENTITY_MODE_REQUIRES_REFERENCE:
        raise ValueError(f"Identity workflow does not support mode: {mode}")
    if not reference_image:
        raise ValueError("Identity workflow requires a reference image")
    if seed < 0:
        seed = random.randint(0, 2**63)

    nodes: Dict[str, Dict] = {
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
    }

    if mode in {IDENTITY_MODE_FACEID, IDENTITY_MODE_FACEID_DETAIL}:
        nodes.update(
            {
                "5": {
                    "class_type": "IPAdapterUnifiedLoaderFaceID",
                    "inputs": {
                        "model": ["1", 0],
                        "preset": "FACEID PLUS V2",
                        "lora_strength": 0.6,
                        "provider": "CUDA",
                    },
                },
                "6": {
                    "class_type": "LoadImage",
                    "inputs": {"image": reference_image},
                },
                "7": {
                    "class_type": "IPAdapterAdvanced",
                    "inputs": {
                        "model": ["5", 0],
                        "ipadapter": ["5", 1],
                        "image": ["6", 0],
                        "weight": float(identity_weight),
                        "weight_type": "linear",
                        "combine_embeds": "concat",
                        "start_at": 0.0,
                        "end_at": 1.0,
                        "embeds_scaling": "V only",
                    },
                },
            }
        )
        sampler_inputs = {
            "model": ["7", 0],
            "positive": ["3", 0],
            "negative": ["4", 0],
        }
    else:
        nodes.update(
            {
                "5": {
                    "class_type": "InstantIDModelLoader",
                    "inputs": {"instantid_file": "ip-adapter.bin"},
                },
                "6": {
                    "class_type": "InstantIDFaceAnalysis",
                    "inputs": {"provider": "CUDA"},
                },
                "7": {
                    "class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": "instantid_xl.safetensors"},
                },
                "8": {
                    "class_type": "LoadImage",
                    "inputs": {"image": reference_image},
                },
                "9": {
                    "class_type": "ApplyInstantID",
                    "inputs": {
                        "instantid": ["5", 0],
                        "insightface": ["6", 0],
                        "control_net": ["7", 0],
                        "image": ["8", 0],
                        "model": ["1", 0],
                        "positive": ["3", 0],
                        "negative": ["4", 0],
                        "weight": float(identity_weight),
                        "start_at": 0.0,
                        "end_at": 1.0,
                    },
                },
            }
        )
        sampler_inputs = {
            "model": ["9", 0],
            "positive": ["9", 1],
            "negative": ["9", 2],
        }

    nodes["10"] = {
        "class_type": "KSampler",
        "inputs": {
            **sampler_inputs,
            "latent_image": ["2", 0],
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": "normal",
            "denoise": 1.0,
        },
    }
    nodes["11"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["10", 0], "vae": ["1", 2]},
    }

    output_node = "11"
    if identity_mode_uses_detailer(mode):
        nodes["12"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": "bbox/face_yolov8n.pt"},
        }
        nodes["13"] = {
            "class_type": "SAMLoader",
            "inputs": {"model_name": "sam_vit_b_01ec64.pth", "device_mode": "AUTO"},
        }
        nodes["14"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": ["11", 0],
                "model": ["1", 0],
                "clip": ["1", 1],
                "vae": ["1", 2],
                "guide_size": 384,
                "guide_size_for": True,
                "max_size": min(width, height),
                "seed": seed,
                "steps": max(12, min(24, steps)),
                "cfg": max(4.0, min(8.0, cfg)),
                "sampler_name": sampler,
                "scheduler": "normal",
                "positive": ["3", 0],
                "negative": ["4", 0],
                "denoise": max(0.1, min(0.6, float(detailer_denoise))),
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": 0.5,
                "bbox_dilation": 10,
                "bbox_crop_factor": 3.0,
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "bbox_detector": ["12", 0],
                "wildcard": "",
                "cycle": 1,
                "sam_model_opt": ["13", 0],
            },
        }
        output_node = "14"

    nodes[str(int(output_node) + 1)] = {
        "class_type": "SaveImage",
        "inputs": {
            "images": [output_node, 0],
            "filename_prefix": "portrait_identity",
        },
    }
    return {"prompt": nodes}


def build_ipadapter_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 30,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    ip_adapter_ref: str = "",
    ip_adapter_weight: float = 0.85,
    detailer_denoise: float = 0.28,
) -> Dict:
    """Build a FaceID Plus v2 workflow for an approved reference image."""
    return build_identity_workflow(
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        reference_image=ip_adapter_ref,
        identity_mode=IDENTITY_MODE_FACEID,
        identity_weight=ip_adapter_weight,
        detailer_denoise=detailer_denoise,
    )


def build_instantid_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 30,
    cfg: float = 5.0,
    sampler: str = "euler_ancestral",
    reference_image: str = "",
    identity_weight: float = 0.8,
    detailer_denoise: float = 0.28,
) -> Dict:
    """Build a native InstantID workflow for an approved reference image."""
    return build_identity_workflow(
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        reference_image=reference_image,
        identity_mode=IDENTITY_MODE_INSTANTID,
        identity_weight=identity_weight,
        detailer_denoise=detailer_denoise,
    )


def build_animatediff_workflow(
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    motion_model: str = "mm_sd_v15_v2.safetensors",
    width: int = 512,
    height: int = 512,
    frames: int = 16,
    fps: int = 8,
    seed: int = -1,
    steps: int = 20,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    motion_strength: float = 1.0,
    ref_image: Optional[str] = None,
) -> Dict:
    """Build ComfyUI AnimateDiff workflow for video generation.

    Requires ComfyUI-AnimateDiff-Evolved and ComfyUI-VideoHelperSuite.
    ref_image: optional basename for image-to-video mode (must be in ComfyUI input dir).
    Returns workflow dict for /prompt API.
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**63)

    # Sanitize ref_image to prevent path traversal
    if ref_image:
        ref_image = os.path.basename(ref_image)

    workflow = {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "2": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": frames,
                },
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt or "blurry, low quality, distorted, deformed, static",
                    "clip": ["1", 1],
                },
            },
            "10": {
                "class_type": "ADE_AnimateDiffLoaderWithContext",
                "inputs": {
                    "model_name": motion_model,
                    "beta_schedule": "sqrt_linear (AnimateDiff)",
                    "motion_scale": motion_strength,
                    "model": ["1", 0],
                },
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["10", 0],
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
                "class_type": "VHS_VideoCombine",
                "inputs": {
                    "images": ["6", 0],
                    "frame_rate": fps,
                    "loop_count": 0,
                    "filename_prefix": "animatediff",
                    "format": "video/h264-mp4",
                    "save_output": True,
                },
            },
        }
    }

    # Image-to-video: load reference image and use as init latent
    if ref_image:
        workflow["prompt"]["20"] = {
            "class_type": "LoadImage",
            "inputs": {"image": ref_image},
        }
        workflow["prompt"]["21"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["20", 0], "vae": ["1", 2]},
        }
        # Replace empty latent with encoded reference repeated across frames
        workflow["prompt"]["22"] = {
            "class_type": "RepeatLatentBatch",
            "inputs": {"samples": ["21", 0], "amount": frames},
        }
        # Point KSampler to repeated latent instead of empty
        workflow["prompt"]["5"]["inputs"]["latent_image"] = ["22", 0]
        workflow["prompt"]["5"]["inputs"]["denoise"] = 0.7

    return workflow


def build_inpaint_workflow(
    image_path: str,
    mask_path: str,
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    width: int = 1024,
    height: int = 1024,
    seed: int = -1,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    denoise: float = 0.75,
) -> Dict:
    """Build ComfyUI inpainting workflow.

    Loads image + mask, encodes to latent, applies noise mask,
    runs KSampler with partial denoise, decodes and saves.
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
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt or "blurry, low quality, distorted, deformed",
                    "clip": ["1", 1],
                },
            },
            "4": {
                "class_type": "LoadImage",
                "inputs": {"image": image_path},
            },
            "5": {
                "class_type": "LoadImage",
                "inputs": {"image": mask_path},
            },
            "6": {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["4", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SetLatentNoiseMask",
                "inputs": {"samples": ["6", 0], "mask": ["5", 1]},
            },
            "8": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["7", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": denoise,
                },
            },
            "9": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
            },
            "10": {
                "class_type": "SaveImage",
                "inputs": {"images": ["9", 0], "filename_prefix": "edit_inpaint"},
            },
        }
    }


def build_outpaint_workflow(
    image_path: str,
    prompt: str,
    negative_prompt: str = "",
    direction: str = "right",
    pixels: int = 128,
    model: str = "sd_xl_base_1.0.safetensors",
    seed: int = -1,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    denoise: float = 0.8,
) -> Dict:
    """Build ComfyUI outpainting workflow.

    Uses ImagePadForOutpaint to extend canvas in a given direction,
    then inpaints the new region via KSampler.
    direction: 'left' | 'right' | 'top' | 'bottom' | 'all'
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**63)

    left_px = right_px = top_px = bottom_px = 0
    if direction == "all":
        left_px = right_px = top_px = bottom_px = pixels
    elif direction == "left":
        left_px = pixels
    elif direction == "right":
        right_px = pixels
    elif direction == "top":
        top_px = pixels
    elif direction == "bottom":
        bottom_px = pixels

    return {
        "prompt": {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": model},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt or "blurry, low quality, distorted, deformed",
                    "clip": ["1", 1],
                },
            },
            "4": {
                "class_type": "LoadImage",
                "inputs": {"image": image_path},
            },
            "5": {
                "class_type": "ImagePadForOutpaint",
                "inputs": {
                    "image": ["4", 0],
                    "left": left_px,
                    "top": top_px,
                    "right": right_px,
                    "bottom": bottom_px,
                    "feathering": 40,
                },
            },
            "6": {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["5", 0], "vae": ["1", 2]},
            },
            "7": {
                "class_type": "SetLatentNoiseMask",
                "inputs": {"samples": ["6", 0], "mask": ["5", 1]},
            },
            "8": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["7", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": denoise,
                },
            },
            "9": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
            },
            "10": {
                "class_type": "SaveImage",
                "inputs": {"images": ["9", 0], "filename_prefix": "edit_outpaint"},
            },
        }
    }


def build_upscale_workflow(
    image_path: str,
    model_name: str = "RealESRGAN_x4plus.pth",
    target_scale: int = 4,
) -> Dict:
    """Build ComfyUI upscale workflow using a model-based upscaler.

    Loads an upscale model (e.g. RealESRGAN) and applies it to the image.
    Always outputs at 4x native resolution; caller handles further scaling.
    """
    return {
        "prompt": {
            "1": {
                "class_type": "UpscaleModelLoader",
                "inputs": {"model_name": model_name},
            },
            "2": {
                "class_type": "LoadImage",
                "inputs": {"image": image_path},
            },
            "3": {
                "class_type": "ImageUpscaleWithModel",
                "inputs": {"upscale_model": ["1", 0], "image": ["2", 0]},
            },
            "4": {
                "class_type": "SaveImage",
                "inputs": {"images": ["3", 0], "filename_prefix": "edit_upscale"},
            },
        }
    }


def build_img2img_workflow(
    image_path: str,
    prompt: str,
    negative_prompt: str = "",
    model: str = "sd_xl_base_1.0.safetensors",
    seed: int = -1,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler_ancestral",
    denoise: float = 0.6,
) -> Dict:
    """Build ComfyUI img2img workflow.

    Encodes the input image to latent space, then runs KSampler
    with partial denoise to produce a variation guided by the prompt.
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
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1", 1]},
            },
            "3": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "text": negative_prompt or "blurry, low quality, distorted, deformed",
                    "clip": ["1", 1],
                },
            },
            "4": {
                "class_type": "LoadImage",
                "inputs": {"image": image_path},
            },
            "5": {
                "class_type": "VAEEncode",
                "inputs": {"pixels": ["4", 0], "vae": ["1", 2]},
            },
            "6": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["5", 0],
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": "normal",
                    "denoise": denoise,
                },
            },
            "7": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
            },
            "8": {
                "class_type": "SaveImage",
                "inputs": {"images": ["7", 0], "filename_prefix": "edit_img2img"},
            },
        }
    }
