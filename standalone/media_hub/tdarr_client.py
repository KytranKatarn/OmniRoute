"""
Tdarr API client — M.A.V.E.N.'s handle on the transcode engine (project #385 Phase 3).

Tdarr owns its own queue + multi-node GPU scheduler; this client is how M.A.V.E.N.
ORCHESTRATES it: read library health, enumerate nodes (hub CPU + Starship GPUs),
queue a space-saving transcode, and pause a node's workers when DHQ needs that GPU
for inference. Every call is best-effort and NEVER raises — a Tdarr outage must not
break a probe (mirrors archie_coordination.py).

Base URL from TDARR_URL (default http://tdarr:8265 — media_hub + tdarr share tdarr_net).
Confirmed endpoints (Tdarr 2.82): GET /api/v2/status, GET /api/v2/get-nodes,
POST /api/v2/cruddb {data:{collection,mode}}.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger("media_hub.tdarr")

# GPU node-name hints (we tag Starship nodes tdarr-246-rtx3070 / tdarr-245-rtx3050).
_GPU_HINTS = ("rtx", "gpu", "-246", "-245", "nvenc", "3070", "3050")


def _base() -> str:
    return (os.getenv("TDARR_URL") or "http://tdarr:8265").rstrip("/")


def _get(path: str):
    try:
        r = requests.get(f"{_base()}{path}", timeout=8)
        return r.json() if r.ok else None
    except Exception as exc:  # noqa: BLE001
        log.warning("tdarr GET %s failed: %s", path, exc)
        return None


def _post(path: str, obj: dict):
    try:
        r = requests.post(f"{_base()}{path}", json=obj, timeout=12)
        if not r.ok:
            log.warning("tdarr POST %s -> %s", path, r.status_code)
            return None
        try:
            return r.json()
        except Exception:  # noqa: BLE001 — some endpoints return a bare string
            return r.text
    except Exception as exc:  # noqa: BLE001
        log.warning("tdarr POST %s failed: %s", path, exc)
        return None


def status() -> Optional[dict]:
    """Server status ({status, version, uptime, ...}) or None if unreachable."""
    return _get("/api/v2/status")


def is_up() -> bool:
    s = status()
    return bool(s and s.get("status") == "good")


def nodes() -> list[dict]:
    """Connected Tdarr nodes, normalized:
    [{id, name, is_gpu, priority, address, workers}]. Presence == online."""
    raw = _get("/api/v2/get-nodes") or {}
    out = []
    for nid, n in (raw.items() if isinstance(raw, dict) else []):
        name = (n.get("nodeName") or nid) if isinstance(n, dict) else nid
        cfg = n.get("config", {}) if isinstance(n, dict) else {}
        lname = str(name).lower()
        out.append({
            "id": nid,
            "name": name,
            "is_gpu": any(h in lname for h in _GPU_HINTS),
            "priority": cfg.get("priority", 0),
            "address": n.get("remoteAddress") if isinstance(n, dict) else None,
            "workers": n.get("workers") if isinstance(n, dict) else None,
        })
    return out


def library_files(limit: int = 5000) -> list[dict]:
    """All scanned files from Tdarr's FileJSONDB (empty until a library is scanned).
    Each doc carries codec/resolution/size fields we use for the review report."""
    res = _post("/api/v2/cruddb", {"data": {"collection": "FileJSONDB", "mode": "getAll"}})
    return res[:limit] if isinstance(res, list) else []


def queue_transcode(file_id: str) -> bool:
    """Best-effort: add a file to Tdarr's transcode queue. Requires a scanned library.
    Tdarr drives transcodes via library flows; this pokes the manual-queue endpoint and
    reports success only on a 2xx. Returns False cleanly if unsupported/unreachable."""
    res = _post("/api/v2/manual-queue", {"data": {"_id": file_id}})
    return res is not None


def set_node_paused(node_id: str, paused: bool) -> bool:
    """Pause/unpause a node's workers — how M.A.V.E.N. yields a GPU back to inference.
    Best-effort; returns False cleanly if unsupported."""
    res = _post("/api/v2/update-node-workers", {"data": {"nodeID": node_id, "pause": bool(paused)}})
    return res is not None


def pick_node(resolution: Optional[str] = None, gpu_busy_ids: Optional[set] = None) -> Optional[dict]:
    """M.A.V.E.N.'s node choice among the online Tdarr nodes:
      - prefer a GPU node that is NOT flagged busy-with-inference (gpu_busy_ids);
      - 4K prefers the biggest-VRAM GPU (by name hint), else any GPU;
      - fall back to a CPU node (hub) for overflow / when GPUs are busy.
    Returns the chosen node dict or None if no node is online."""
    ns = nodes()
    if not ns:
        return None
    gpu_busy_ids = gpu_busy_ids or set()
    gpus = [n for n in ns if n["is_gpu"] and n["id"] not in gpu_busy_ids]
    if gpus:
        if resolution and "4k" in str(resolution).lower():
            # Prefer the 3070 (8GB) over the 3050 (4GB) for 4K.
            gpus.sort(key=lambda n: 0 if "3070" in n["name"].lower() or "-246" in n["name"].lower() else 1)
        return gpus[0]
    cpus = [n for n in ns if not n["is_gpu"]]
    return cpus[0] if cpus else ns[0]
