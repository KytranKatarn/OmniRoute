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


# Real Media library id (folder=/media). The junk 'Library Name'/BUQ0l-6oQ lib is ignored.
_DEFAULT_LIBRARY = "medialib1"


def library_scan(db_id: str = _DEFAULT_LIBRARY, mode: str = "scanFindNew") -> bool:
    """Trigger a Tdarr library scan so FileJSONDB reflects current media.
    mode='scanFindNew' = incremental (pick up newly-downloaded / removed files);
    'scanFresh' = full re-probe. Returns True if Tdarr ACCEPTED the scan (it then
    runs async — Tdarr logs 'Starting file scan'). Requires the library mount
    intact (BOTH split drives; a broken /media/movies symlink aborts the scanner
    with 'Files found:0' — KB #279356 / PR #2120). Best-effort; never raises."""
    res = _post(
        "/api/v2/scan-files",
        {"data": {"scanConfig": {"dbID": db_id, "arrayOrPath": [], "mode": mode}}},
    )
    # Tdarr returns the bare string 'OK' on accept (some builds return a dict/list).
    return res is not None and (res == "OK" or res is True or isinstance(res, (dict, list)))


def queue_transcode(file_id: str = "") -> bool:
    """DEPRECATED per-file trigger. Tdarr 2.82 has NO manual per-file queue
    (/api/v2/manual-queue is 404). Tdarr transcodes by-LIBRARY via its processing
    engine — so M.A.V.E.N. keeps the engine OFF (approval-gated) and starts an
    owner-approved optimize RUN by enabling it. file_id is ignored (Tdarr selects
    the eligible candidates itself). Back-compat shim -> set_processing(True). #4762."""
    return set_processing(True)


# ── Approval-gated optimize RUN (#4762) — Tdarr 2.82 optimizes by-library, not per-file ──
_TRANSCODE_EFFICIENT = ("hevc", "h265", "av1", "vp9")


def set_processing(enabled: bool) -> bool:
    """Enable/disable Tdarr's transcode engine on the Media library
    (processLibrary/processTranscodes gate whether the engine assigns Queued files
    to node workers). M.A.V.E.N. keeps this OFF and flips it ON only for an
    owner-APPROVED optimize run, then OFF when the queue drains. Returns True on a
    successful update. Best-effort; never raises."""
    libs = _post("/api/v2/cruddb", {"data": {"collection": "LibrarySettingsJSONDB", "mode": "getAll"}})
    lib = next((l for l in libs if l.get("_id") == _DEFAULT_LIBRARY), None) if isinstance(libs, list) else None
    if not lib:
        return False
    lib["processLibrary"] = bool(enabled)
    if "processTranscodes" in lib:
        lib["processTranscodes"] = bool(enabled)
    r = _post("/api/v2/cruddb", {"data": {"collection": "LibrarySettingsJSONDB", "mode": "update",
                                          "docID": _DEFAULT_LIBRARY, "obj": lib}})
    return r is not None


def is_processing() -> bool:
    """True if the library's transcode engine is currently enabled (a run is active)."""
    libs = _post("/api/v2/cruddb", {"data": {"collection": "LibrarySettingsJSONDB", "mode": "getAll"}})
    lib = next((l for l in libs if l.get("_id") == _DEFAULT_LIBRARY), None) if isinstance(libs, list) else None
    return bool(lib and lib.get("processLibrary"))


def transcode_active() -> int:
    """Count in-flight transcode workers across all nodes (0 = nothing transcoding)."""
    raw = _get("/api/v2/get-nodes") or {}
    return sum(
        1
        for n in (raw.values() if isinstance(raw, dict) else [])
        if isinstance(n, dict)
        for wk in (n.get("workers") or {}).values()
        if str((wk or {}).get("workerType", "")).startswith("transcode")
    )


def transcode_pending() -> int:
    """Count non-HEVC files still awaiting a transcode decision ('Queued'). During an
    active run this drains to 0 once every eligible file is assessed + transcoded."""
    n = 0
    for d in library_files():
        codec = str(d.get("video_codec_name") or "").lower()
        if str(d.get("TranscodeDecisionMaker")) == "Queued" and not any(e in codec for e in _TRANSCODE_EFFICIENT):
            n += 1
    return n


def set_node_paused(node_id: str, paused: bool) -> bool:
    """Pause/unpause a node's workers — how M.A.V.E.N. yields a GPU back to inference.
    Best-effort; returns False cleanly if unsupported."""
    res = _post("/api/v2/update-node-workers", {"data": {"nodeID": node_id, "pause": bool(paused)}})
    return res is not None


# ── Per-node GPU worker-limit control (dispatch-orchestrated yield, #385) ──
# Tdarr exposes each node's `workerLimits.transcodegpu` in get-nodes. alter-worker-limit
# steps it ±1 and PERSISTS (verified Phase B). M.A.V.E.N. yields a GPU to DHQ inference by
# dropping that node's transcodegpu limit to 0, and resumes by raising it back to 1.

def node_worker_limit(node_id: str, worker_type: str = "transcodegpu") -> Optional[int]:
    """Current worker LIMIT for a node+type (not live worker count), or None if unknown."""
    raw = _get("/api/v2/get-nodes") or {}
    n = raw.get(node_id) if isinstance(raw, dict) else None
    if not isinstance(n, dict):
        return None
    lim = (n.get("workerLimits") or {}).get(worker_type)
    try:
        return int(lim)
    except (TypeError, ValueError):
        return None


def set_node_worker_limit(node_id: str, target: int, worker_type: str = "transcodegpu") -> bool:
    """Step a node's worker LIMIT to an absolute `target` via alter-worker-limit (±1 per
    call). Reads the current limit so it's idempotent (no-op when already at target) and
    never over/under-shoots. Best-effort; never raises. Bounded to ≤16 steps as a guard."""
    cur = node_worker_limit(node_id, worker_type)
    if cur is None:
        return False
    target = max(0, int(target))
    steps = 0
    while cur != target and steps < 16:
        process = "increase" if target > cur else "decrease"
        r = _post("/api/v2/alter-worker-limit",
                  {"data": {"nodeID": node_id, "process": process, "workerType": worker_type}})
        if r is None:
            return False
        cur += 1 if process == "increase" else -1
        steps += 1
    return cur == target


def pause_gpu_transcodes(node_id: str) -> bool:
    """Yield a GPU node to DHQ inference — drop its transcodegpu worker limit to 0."""
    return set_node_worker_limit(node_id, 0, "transcodegpu")


def resume_gpu_transcodes(node_id: str, target: int = 1) -> bool:
    """Give the GPU back to Tdarr — restore the node's transcodegpu worker limit (default 1)."""
    return set_node_worker_limit(node_id, target, "transcodegpu")


def gpu_node_ids() -> list[str]:
    """Tdarr node ids that are GPU nodes (transcode targets M.A.V.E.N. orchestrates)."""
    return [n["id"] for n in nodes() if n.get("is_gpu")]


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
