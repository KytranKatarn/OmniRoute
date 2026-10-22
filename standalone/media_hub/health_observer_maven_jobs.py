"""Media Hub scheduled health jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from health_observer_common import *  # noqa: F401,F403

def _maven_removal_executor() -> None:
    """Execute A.R.C.H.I.E.-approved M.A.V.E.N. removals; drop denied ones.
    project #385 task #4745. Wrapped so a failure never kills the scheduler."""
    try:
        from maven_manager import process_approved_removals

        process_approved_removals()
    except Exception as exc:  # noqa: BLE001
        log.error("maven_removal_executor failed: %s", exc)

def _maven_optimize_executor() -> None:
    """Queue A.R.C.H.I.E.-approved Tdarr transcodes; drop denied. project #385 Phase 3."""
    try:
        from maven_manager import process_approved_optimizes

        process_approved_optimizes()
    except Exception as exc:  # noqa: BLE001
        log.error("maven_optimize_executor failed: %s", exc)

def _maven_daily_optimize_proposal() -> None:
    """Daily: raise ONE optimize approval (Telegram + Department HQ Approvals tab) to reclaim
    space. M.A.V.E.N. picks the top oversized candidate and proposes it via request_optimize,
    which fans out to Telegram Approve/Deny + the DHQ approvals feed like any other request.
    Dedup-guarded — skips when an optimize is already awaiting approval or a Tdarr run is active,
    so proposals never stack (one steady approval a day; approve it to reclaim ~size).
    Owner-requested pacing. project #385 Phase 3."""
    try:
        import tdarr_client
        from maven_manager import request_optimize, video_review

        if tdarr_client.is_processing():
            log.info("maven_daily_optimize: a Tdarr run is active — skipping today's proposal")
            return
        try:
            from database import get_db_cursor
            from maven_manager import _ensure_table

            _ensure_table()
            with get_db_cursor(cursor_factory=None) as (_c, cur):
                cur.execute(
                    "SELECT count(*) FROM maven_pending_actions "
                    "WHERE status='awaiting' AND action='optimize'"
                )
                if (cur.fetchone() or [0])[0]:
                    log.info("maven_daily_optimize: an optimize is already awaiting approval — skipping")
                    return
        except Exception:  # noqa: BLE001
            log.warning(
                "maven_daily_optimize: dedup check failed — relying on request_optimize dedup",
                exc_info=True,
            )

        rev = video_review(min_gb=4.0, top=1) or {}
        cands = rev.get("candidates") or []
        if not cands:
            log.info("maven_daily_optimize: no optimize candidates found today")
            return
        top = cands[0]
        fid = top.get("id") or top.get("path")
        res = request_optimize(
            file_id=fid,
            title=top.get("title") or str(fid or "").split("/")[-1],
            resolution=top.get("resolution"),
            est_savings_gb=rev.get("est_savings_gb"),
            reason="daily space optimize",
        )
        log.info("maven_daily_optimize: proposed optimize -> %s", res)
    except Exception as exc:  # noqa: BLE001
        log.error("maven_daily_optimize_proposal failed: %s", exc)

def _tdarr_library_review() -> None:
    """Periodic Tdarr rescan + library review — M.A.V.E.N. refreshes her own view
    of the library (#4754) then reports space-optimize candidates on the fresh
    data. Phase 3."""
    try:
        from maven_manager import library_scan, video_review

        library_scan()  # #4754 — pick up newly-downloaded/removed files first
        video_review()
    except Exception as exc:  # noqa: BLE001
        log.error("tdarr_library_review failed: %s", exc)

def _tdarr_dispatch_orchestration() -> None:
    """Dispatch-orchestrated Tdarr drain (#385 v2). The two Tdarr GPU nodes (USS-246 /
    USS-245) are ALSO fleet inference nodes whose warm models fully own the 8GB/4GB VRAM,
    so a transcode can't co-run with inference. While an approved optimize RUN is active
    M.A.V.E.N. treats the drain as a PRIORITY QUEUE, not a starving background task:
      • node idle  -> transcode (resume workers);
      • node busy with DHQ inference -> yield (pause workers) — inference wins;
      • node busy but the drain has been YIELDED past _ORCH_MAX_STARVE_MIN -> grant a bounded
        OPPORTUNITY WINDOW: lease the node (VRAM-evict its Ollama models via the hub, mirroring
        the ComfyUI/SDXL swap), transcode for _ORCH_WINDOW_MIN, then release (reload models).
    Only ONE node is ever leased at a time (the other stays available for inference). When NO
    run is active, any paused/leased node is restored (cleanup). Fail-open on the hub signal;
    every step best-effort — a failure never kills the scheduler."""
    try:
        import re
        from datetime import datetime, timedelta, timezone

        import tdarr_client
        from archie_coordination import fleet_gpu_lease, fleet_gpu_load, fleet_inference_pressure

        gpu_nodes = [n for n in tdarr_client.nodes() if n.get("is_gpu")]
        if not gpu_nodes:
            return
        now = datetime.now(timezone.utc)
        actions: list = []

        # No active run → release any lease + restore any paused node, reset state, stop.
        if not tdarr_client.is_processing():
            for n in gpu_nodes:
                st = _orch_state.get(n["id"])
                if st:
                    _orch_release(n["name"], st, fleet_gpu_lease, tdarr_client, actions, "run ended")
                if (tdarr_client.node_worker_limit(n["id"]) or 0) < 1:
                    if tdarr_client.resume_gpu_transcodes(n["id"], 1):
                        actions.append(f"restored {n['name']} transcodegpu=1 (no active run)")
            _orch_state.clear()
            _log_selfheal("tdarr_dispatch_orchestration", "media_optimize", actions)
            return

        # Active run → consult the hub for per-node inference load (fail-open).
        load = fleet_gpu_load()
        if not load or not load.get("ok"):
            log.info("tdarr_dispatch_orchestration: fleet-gpu-load unavailable — leaving worker limits as-is")
            return
        busy_by_key, nodeid_by_key = {}, {}
        for fn in load.get("nodes") or []:
            k = fn.get("match_key")
            if k:
                busy_by_key[str(k)] = bool(fn.get("busy"))
                nodeid_by_key[str(k)] = fn.get("node_id")

        pending = tdarr_client.transcode_pending()
        starve_s, window_s, gap_s = (
            _ORCH_MAX_STARVE_MIN * 60, _ORCH_WINDOW_MIN * 60, _ORCH_MIN_GAP_MIN * 60,
        )
        # Never evict more than one GPU at once — keep a node for inference.
        window_active = any(
            (s.get("window_until") and now < s["window_until"]) for s in _orch_state.values()
        )

        for n in gpu_nodes:
            nid = n["id"]
            m = re.search(r"(\d{3})", str(n.get("name") or ""))
            key = m.group(1) if m else None
            busy = busy_by_key.get(key) if key else None
            st = _orch_state.setdefault(
                nid, {"yield_since": None, "window_until": None, "leased_models": [],
                      "last_window_at": None, "fleet_node_id": None}
            )
            if key:
                st["fleet_node_id"] = nodeid_by_key.get(key)
            cur = tdarr_client.node_worker_limit(nid) or 0

            # (1) In an active opportunity window → keep transcoding.
            if st.get("window_until") and now < st["window_until"]:
                if cur < 1:
                    tdarr_client.resume_gpu_transcodes(nid, 1)
                continue

            # (2) Window just ended → release the lease, then fall back to yield/idle.
            if st.get("window_until") and now >= st["window_until"]:
                _orch_release(n["name"], st, fleet_gpu_lease, tdarr_client, actions, "window ended")
                st["last_window_at"] = now
                if busy is False:
                    tdarr_client.resume_gpu_transcodes(nid, 1)
                    st["yield_since"] = None
                else:
                    tdarr_client.pause_gpu_transcodes(nid)
                    st["yield_since"] = now
                continue

            # (3) Node idle → transcode.
            if busy is False:
                if cur < 1 and tdarr_client.resume_gpu_transcodes(nid, 1):
                    actions.append(f"resume {n['name']} transcode (node idle)")
                st["yield_since"] = None
                continue

            # (4) Node busy → yield, unless the drain has starved long enough to earn a window.
            if busy is True:
                if not st.get("yield_since"):
                    st["yield_since"] = now
                if cur > 0 and tdarr_client.pause_gpu_transcodes(nid):
                    actions.append(f"yield {n['name']} → DHQ inference (transcodegpu 0)")
                starved = (now - st["yield_since"]).total_seconds() >= starve_s
                gap_ok = (not st.get("last_window_at")) or (now - st["last_window_at"]).total_seconds() >= gap_s
                would_grant = (starved and gap_ok and pending > 0 and not window_active
                               and st.get("fleet_node_id") and _orch_windows_enabled())
                if would_grant:
                    # Welfare gate (#4766): a window EVICTS this node's inference models, so
                    # skip it when the fleet is actively serving inference. Fail-open: if the
                    # pressure signal is unavailable (None), proceed rather than wedge the drain.
                    pressure = fleet_inference_pressure(load)
                    cap = _orch_window_max_pressure()
                    if pressure is not None and pressure >= cap:
                        actions.append(
                            f"window for {n['name']} DEFERRED (welfare) — fleet inference "
                            f"pressure {pressure} ≥ {cap}"
                        )
                    else:
                        lease = fleet_gpu_lease(st["fleet_node_id"], "acquire")
                        if lease and lease.get("ok"):
                            st["leased_models"] = lease.get("unloaded") or []
                            st["window_until"] = now + timedelta(seconds=window_s)
                            st["yield_since"] = None
                            window_active = True
                            tdarr_client.resume_gpu_transcodes(nid, 1)
                            actions.append(
                                f"OPPORTUNITY WINDOW on {n['name']} — VRAM leased "
                                f"(evicted {len(st['leased_models'])} model(s)); transcoding {_ORCH_WINDOW_MIN}m"
                            )
                        # lease failed → stay yielded (fail-open; inference stays safe)
            # busy is None (node not matched) → leave as-is, don't starve the drain

        _log_selfheal("tdarr_dispatch_orchestration", "media_optimize", actions)
    except Exception as exc:  # noqa: BLE001
        log.error("tdarr_dispatch_orchestration failed: %s", exc)
