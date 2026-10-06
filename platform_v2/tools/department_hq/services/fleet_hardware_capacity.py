"""Fleet hardware-capacity collection; caller retains cache and dependency ownership."""

import logging
import os
import subprocess
import time

import requests

logger = logging.getLogger(__name__)


def get_cached_capacity(get_loaded_models, db_cursor, *, cache, ttl):
    """Get hardware capacity info with 30s cache (GPU, RAM, model breakdown)."""
    now = time.time()
    if cache["data"] and (now - cache["time"]) < ttl:
        return cache["data"]

    import psutil

    mem = psutil.virtual_memory()
    total_gb = round(mem.total / (1024**3), 1)
    available_gb = round(mem.available / (1024**3), 1)
    usage_pct = round(mem.percent, 1)
    # RAM budget: 70% LLM / 15% host / 15% security services (ADR-078 updated)
    reserve_gb = round(total_gb * 0.15, 1)  # 15% host reserve (OS, Docker, platform, DB)
    security_gb = round(total_gb * 0.15, 1)  # 15% security services (Frigate, CrowdSec, Suricata, etc.)

    # Ollama loaded models — categorize GPU vs CPU
    ps_models = get_loaded_models()
    models_loaded = len(ps_models)
    models_ram_gb = round(sum(m.get("size", 0) for m in ps_models) / (1024**3), 1)
    gpu_models = []
    cpu_models = []
    for pm in ps_models:
        pm_name = pm.get("name", "").replace(":latest", "")
        pm_total = pm.get("size", 0) or 0
        pm_size = round(pm_total / (1024**3), 1)
        pm_vram = pm.get("size_vram", 0) or 0
        # `size` vs `size_vram` is exactly what `ollama ps` uses to compute its
        # PROCESSOR column, so the GPU/CPU split is derivable here and needs no
        # second source. It was being discarded: the panel printed a GB figure
        # when vram>0 and the bare word "CPU" otherwise, so GPU residency was
        # implied by the PRESENCE of a number and never actually stated.
        if pm_vram <= 0:
            processor, gpu_pct = "cpu", 0
        elif pm_vram >= pm_total:
            processor, gpu_pct = "gpu", 100
        else:
            processor, gpu_pct = "split", int(round(pm_vram / pm_total * 100)) if pm_total else 0
        entry = {
            "name": pm_name,
            "size_gb": pm_size,
            "vram_gb": round(pm_vram / (1024**3), 1),
            "processor": processor,
            "gpu_pct": gpu_pct,
        }
        (gpu_models if pm_vram > 0 else cpu_models).append(entry)

    # GPU info from nvidia-smi (may fail inside Docker without GPU passthrough)
    gpu_info = None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                # uuid is the JOIN KEY to --query-compute-apps, which is the only
                # way to say which card carries which model (/api/ps does not say).
                # Index is NOT usable for that join and is misleading besides: the
                # TITAN is index 1, not 0, and ai-bridge.md warns to identify these
                # cards by UUID precisely because an index assumption was wrong once.
                "--query-gpu=name,memory.total,memory.used,memory.free,uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # ONE LINE PER GPU. Splitting the whole payload on "," merged the rows:
            # measured 2026-09-20 on the hub, parts became
            #   ['Quadro M4000','8192','4','8116\nNVIDIA TITAN X (Pascal)','12288',...]
            # so parts[1]/parts[2] described GPU 0 ALONE -> the platform reported a
            # single 8GB card with 0.0GB used while a 12GB TITAN held 4.9GB. The
            # identical bug was found and fixed in scripts/host_monitor.py (KSO's
            # collector) on 2026-07-26; this copy was never fixed.
            cards = []
            for line in result.stdout.strip().splitlines():
                parts = [c.strip() for c in line.split(",")]
                if len(parts) < 4:
                    continue
                try:
                    c_total = round(float(parts[1]) / 1024, 1)
                    c_used = round(float(parts[2]) / 1024, 1)
                    c_free = round(float(parts[3]) / 1024, 1)
                except ValueError:
                    continue
                cards.append(
                    {
                        "index": len(cards),
                        "name": parts[0],
                        # Absent on older nvidia-smi builds; consumers must treat a
                        # missing uuid as "cannot join", not as a blank that matches.
                        "uuid": parts[4] if len(parts) > 4 else None,
                        "vram_total_gb": c_total,
                        "vram_used_gb": c_used,
                        "vram_free_gb": c_free,
                        "usage_pct": round(c_used / c_total * 100, 1) if c_total > 0 else 0,
                    }
                )
            if cards:
                vram_total = round(sum(c["vram_total_gb"] for c in cards), 1)
                vram_used = round(sum(c["vram_used_gb"] for c in cards), 1)
                vram_free = round(sum(c["vram_free_gb"] for c in cards), 1)
                largest_free = max(c["vram_free_gb"] for c in cards)
                gpu_info = {
                    "name": " + ".join(c["name"] for c in cards),
                    "gpus": cards,
                    "gpu_count": len(cards),
                    "vram_total_gb": vram_total,
                    "vram_used_gb": vram_used,
                    "vram_free_gb": vram_free,
                    "largest_free_gb": largest_free,
                    "total_known": True,
                    "usage_pct": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                    # Keyed on the LARGEST SINGLE card, not the sum: a model has to
                    # fit on one card, so 2GB free spread over two cards is not 2GB
                    # of capacity. Same rule as remote_nodes.gpu_vram_gb (fleet.md).
                    "status": "red" if largest_free < 1.0 else ("amber" if largest_free < 2.0 else "green"),
                    "models": gpu_models,
                }
    except Exception as e:
        logger.warning("nvidia-smi query failed (expected in Docker without GPU passthrough): %s", e)

    # Fallback: build GPU info from Ollama VRAM data if nvidia-smi unavailable
    if gpu_info is None and gpu_models:
        vram_used = round(sum(m["vram_gb"] for m in gpu_models), 1)
        # No nvidia-smi: we know what Ollama placed on a GPU but NOT how much VRAM
        # exists, so the total is reported as unknown rather than assumed. This
        # previously hardcoded 8.0 ("Quadro M4000") and computed a usage percentage
        # against it -- on a 20GB two-card host that is a confident wrong number.
        # An unknown capacity is reported as unknown (ADR-017).
        gpu_info = {
            "name": "GPU (via Ollama)",
            "gpus": [],
            "gpu_count": 0,
            "vram_total_gb": None,
            "vram_used_gb": vram_used,
            "vram_free_gb": None,
            "largest_free_gb": None,
            "total_known": False,
            "usage_pct": None,
            "status": "unknown",
            "models": gpu_models,
        }

    # ComfyUI VRAM usage (loads SDXL on-demand, torch_vram_total > 0 when active)
    comfyui_vram_gb = 0
    comfyui_status = "idle"
    comfyui_reserved_gb = 0
    try:
        comfyui_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
        _cfu_resp = requests.get(f"{comfyui_host}/system_stats", timeout=3)
        if _cfu_resp.status_code == 200:
            for dev in _cfu_resp.json().get("devices", []):
                if dev.get("type") == "cuda":
                    torch_vram = dev.get("torch_vram_total", 0)
                    comfyui_vram_gb = round(torch_vram / (1024**3), 1)
                    comfyui_status = "loaded" if torch_vram > 0 else "idle"
    except Exception as e:
        logger.warning("ComfyUI system_stats fetch failed: %s", e)
    # Estimate reserved VRAM for the configured checkpoint (SDXL ~6.5GB)
    if comfyui_status == "idle":
        try:
            with db_cursor(commit=False) as (_cconn, _ccur):
                _ccur.execute(
                    "SELECT image_model FROM agents WHERE image_model IS NOT NULL AND status = 'active' LIMIT 1"
                )
                _crow = _ccur.fetchone()
                if _crow:
                    ckpt = _crow["image_model"]
                    # Estimate VRAM from checkpoint name
                    if "xl" in ckpt.lower():
                        comfyui_reserved_gb = 6.5
                    else:
                        comfyui_reserved_gb = 4.0
        except Exception:
            comfyui_reserved_gb = 6.5  # Default SDXL estimate
    if gpu_info:
        gpu_info["comfyui_vram_gb"] = comfyui_vram_gb
        gpu_info["comfyui_status"] = comfyui_status
        gpu_info["comfyui_reserved_gb"] = comfyui_reserved_gb

    llm_budget_gb = round(total_gb * 0.70, 1)  # 70% for LLM agents
    agent_budget_gb = round(llm_budget_gb * 0.90, 1)  # 90% of LLM budget for active agents
    swap_buffer_gb = round(llm_budget_gb * 0.10, 1)  # 10% swap buffer for model rotation
    # Status: red if eating into reserve+security, amber if swap depleted, green if within budget
    swap_used_gb = max(0, models_ram_gb - agent_budget_gb)
    min_free = reserve_gb + security_gb  # Total non-LLM allocation
    if available_gb <= reserve_gb:
        ram_status = "red"
    elif available_gb <= min_free or swap_used_gb >= swap_buffer_gb:
        ram_status = "amber"
    else:
        ram_status = "green"

    capacity = {
        "ram": {
            "total_gb": total_gb,
            "available_gb": available_gb,
            "usage_pct": usage_pct,
            "reserve_gb": reserve_gb,
            "security_gb": security_gb,
            "llm_budget_gb": llm_budget_gb,
            "agent_budget_gb": agent_budget_gb,
            "swap_buffer_gb": swap_buffer_gb,
            "status": ram_status,
        },
        "gpu": gpu_info,
        "models_loaded": models_loaded,
        "models_ram_gb": models_ram_gb,
        "gpu_models": gpu_models,
        "cpu_models": cpu_models,
    }
    cache["data"] = capacity
    cache["time"] = now
    return capacity
