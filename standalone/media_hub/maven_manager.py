"""
M.A.V.E.N. manager — agent-initiated, approval-gated library actions (project #385).

Owner policy: M.A.V.E.N. may auto-fix SAFE things, but DESTRUCTIVE actions
(currently: remove a movie/show + its files) NEVER run autonomously. The flow:

    request_removal(...)          # M.A.V.E.N. / chat wants to remove X
      -> archie_coordination.request_approval(...)   # A.R.C.H.I.E. Telegram Approve/Deny
      -> INSERT maven_pending_actions (status='awaiting')

    process_approved_removals()   # health_observer job, every few minutes
      -> check_approval(approval_id)
         'approved'  -> routes._delete_library_item(...)  + notify_archie, status='executed'
         'denied'    -> drop, status='denied'
         else        -> leave pending for the next cycle

Nothing here deletes without a confirmed 'approved' from the human. Best-effort
DB + coordination calls; a hub outage just leaves rows pending.
"""

import logging

log = logging.getLogger("media_hub.maven_manager")

_VALID = ("movie", "tv", "show", "series")


def _ensure_table() -> None:
    from database import get_db_cursor

    with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS maven_pending_actions (
                approval_id  INTEGER PRIMARY KEY,
                action       TEXT NOT NULL DEFAULT 'remove',
                media_type   TEXT,
                tmdb_id      INTEGER,
                title        TEXT,
                year         INTEGER,
                reason       TEXT,
                status       TEXT NOT NULL DEFAULT 'awaiting',
                created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
                resolved_at  TIMESTAMPTZ
            )
            """
        )
        # payload carries action-specific data (optimize: tdarr file_id + resolution).
        cur.execute("ALTER TABLE maven_pending_actions ADD COLUMN IF NOT EXISTS payload JSONB")


def _mark(approval_id: int, status: str) -> None:
    from database import get_db_cursor

    try:
        with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
            cur.execute(
                "UPDATE maven_pending_actions SET status=%s, resolved_at=now() WHERE approval_id=%s",
                (status, approval_id),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("_mark(%s,%s) failed: %s", approval_id, status, e)


def request_removal(media_type, tmdb_id=None, title=None, year=None, reason="removal") -> dict:
    """Raise a Telegram approval for a destructive removal + record it pending.
    Returns {success, approval_id, status} or {success:False, error}. NEVER deletes."""
    from archie_coordination import request_approval

    mt = (media_type or "").lower()
    if mt not in _VALID:
        return {"success": False, "error": "media_type must be 'movie' or 'tv'"}
    if not tmdb_id and not title:
        return {"success": False, "error": "need tmdb_id or title to identify the item"}

    label = title or (f"tmdb:{tmdb_id}" if tmdb_id else "unknown")
    if title and year:
        label = f"{title} ({year})"  # help the human approver disambiguate same-titled shows
    approval_id = request_approval(
        title=f"Remove {mt}: {label}",
        reason=reason,
        payload={"action": "media_hub_remove", "media_type": mt, "tmdb_id": tmdb_id,
                 "title": title, "year": year},
    )
    if not approval_id:
        return {"success": False,
                "error": "could not raise approval (hub unreachable or duplicate pending)"}

    try:
        _ensure_table()
        from database import get_db_cursor

        with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
            cur.execute(
                """INSERT INTO maven_pending_actions
                     (approval_id, action, media_type, tmdb_id, title, year, reason)
                   VALUES (%s,'remove',%s,%s,%s,%s,%s)
                   ON CONFLICT (approval_id) DO NOTHING""",
                (approval_id, mt, tmdb_id, title, year, reason),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("request_removal: failed to record pending row: %s", e)

    return {"success": True, "approval_id": approval_id, "status": "awaiting_approval"}


def process_approved_removals() -> None:
    """Observer job: execute the removals Kytran approved, drop the ones denied."""
    from archie_coordination import check_approval, log_dispatch, notify_archie

    try:
        _ensure_table()
        from database import get_db_cursor

        with get_db_cursor(cursor_factory=None) as (_c, cur):
            cur.execute(
                """SELECT approval_id, media_type, tmdb_id, title, year
                     FROM maven_pending_actions
                    WHERE status='awaiting' AND action='remove'
                    ORDER BY created_at LIMIT 20"""
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("process_approved_removals: read failed: %s", e)
        return

    for approval_id, media_type, tmdb_id, title, year in rows:
        status = check_approval(approval_id)
        label = title or f"tmdb:{tmdb_id}"
        if status == "approved":
            # Lazy import to avoid a load-time cycle (routes imports lots).
            import time as _time

            from tools.media_hub.routes import _delete_library_item

            _t0 = _time.monotonic()
            res = _delete_library_item(media_type=media_type, tmdb_id=tmdb_id, title=title, year=year)
            _dur = int((_time.monotonic() - _t0) * 1000)
            ok = bool(res.get("success"))
            if ok:
                _mark(approval_id, "executed")
                notify_archie(f"Removed {media_type}: {label}",
                              f"Approved removal complete — {res.get('deleted')}",
                              priority="normal")
            else:
                _mark(approval_id, "failed")
                notify_archie(f"Removal FAILED: {label}",
                              f"Approved but the delete failed: {res.get('error')}",
                              priority="high")
            # A.R.M.A.D.A. visibility (#4755) — 0-token row per executed action.
            log_dispatch("media_remove", capability="media_removal",
                         description=f"remove {media_type}: {label}", success=ok,
                         duration_ms=_dur, target=label,
                         error=(None if ok else str(res.get("error"))),
                         metadata={"media_type": media_type, "tmdb_id": tmdb_id})
        elif status in ("denied", "rejected", "cancelled"):
            _mark(approval_id, "denied")
            log.info("removal %s (%s) denied — dropped", approval_id, label)
        # else: still pending -> leave for the next cycle


# ── Video optimize (Tdarr) — approval-gated, mirrors the removal flow (Phase 3) ──

# Consider a file a space-optimize candidate if it's a large, non-efficient codec.
_EFFICIENT = ("hevc", "h265", "av1", "vp9")


def _file_info(doc: dict) -> dict:
    """Pull {id, path, codec, resolution, size_gb} from a Tdarr FileJSONDB doc,
    tolerating field-name variation across Tdarr versions."""
    def first(*keys):
        for k in keys:
            v = doc.get(k)
            if v not in (None, "", 0):
                return v
        return None

    size = first("file_size", "bytes", "size") or 0
    try:
        size_gb = round(float(size) / (1024 ** 3), 2) if float(size) > 1024 ** 2 else round(float(size) / 1024, 2)
    except Exception:  # noqa: BLE001
        size_gb = 0.0
    return {
        "id": doc.get("_id"),
        "path": first("file", "path", "_id"),
        "codec": str(first("video_codec_name", "ffProbeData_codec", "codec") or "").lower(),
        "resolution": str(first("video_resolution", "resolution") or ""),
        "size_gb": size_gb,
    }


def video_review(min_gb: float = 4.0, top: int = 15) -> dict:
    """Scan the Tdarr library and REPORT space-optimize candidates (no transcoding).
    Emits an A.R.C.H.I.E. notification. Returns {candidates, est_savings_gb}."""
    import time as _time

    import tdarr_client

    if not tdarr_client.is_up():
        return {"success": False, "error": "Tdarr unreachable", "candidates": []}
    _t0 = _time.monotonic()
    files = tdarr_client.library_files()
    cands = []
    for d in files:
        info = _file_info(d)
        if not info["id"]:
            continue
        eff = any(e in info["codec"] for e in _EFFICIENT)
        # Candidate: big AND not already an efficient codec (HEVC/AV1 saves ~30-50%).
        if info["size_gb"] >= min_gb and not eff:
            info["est_savings_gb"] = round(info["size_gb"] * 0.4, 2)
            cands.append(info)
    cands.sort(key=lambda c: c["est_savings_gb"], reverse=True)
    cands = cands[:top]
    est = round(sum(c["est_savings_gb"] for c in cands), 1)

    from archie_coordination import log_dispatch, notify_archie

    if cands:
        lines = "\n".join(f"• {(c['path'] or '').split('/')[-1][:48]} — {c['size_gb']}GB {c['codec'] or '?'} {c['resolution']}"
                          for c in cands[:8])
        notify_archie(
            "Media Hub: video optimize candidates",
            f"{len(cands)} file(s) could save ~{est}GB by re-encoding to HEVC:\n{lines}",
            priority="normal",
        )
    else:
        notify_archie("Media Hub: library already efficient",
                      "No large non-HEVC files found to optimize.", priority="low")
    # A.R.M.A.D.A. visibility (#4755) — record the review as a 0-token action.
    log_dispatch("video_review", capability="video_review",
                 description=f"reviewed library — {len(cands)} candidate(s), ~{est}GB",
                 success=True, duration_ms=int((_time.monotonic() - _t0) * 1000),
                 metadata={"candidates": len(cands), "est_savings_gb": est})
    return {"success": True, "candidates": cands, "est_savings_gb": est}


def request_optimize(file_id, title=None, resolution=None, est_savings_gb=None, reason="optimize") -> dict:
    """Raise a Telegram approval for a space-saving transcode (REPLACES the original =
    destructive). Records a pending 'optimize' row; process_approved_optimizes queues it
    on Tdarr only after Kytran approves. NEVER transcodes here."""
    from archie_coordination import request_approval

    if not file_id:
        return {"success": False, "error": "file_id required"}
    label = (title or str(file_id)).split("/")[-1][:60]
    approval_id = request_approval(
        title=f"Start HEVC optimize run on GPU (e.g. {label}" + (f", ~{est_savings_gb}GB" if est_savings_gb else "") + ")",
        reason=(reason + " — approving enables Tdarr's engine to re-encode the library's HEVC "
                "candidates on the GPU nodes (originals kept when the new file isn't smaller); "
                "M.A.V.E.N. turns the engine back off when the run drains. Tdarr 2.82 optimizes "
                "by-library, not per-file."),
        payload={"action": "media_hub_optimize", "file_id": file_id, "title": label,
                 "resolution": resolution},
    )
    if not approval_id:
        return {"success": False, "error": "could not raise approval (hub unreachable or duplicate)"}
    try:
        import json as _json

        _ensure_table()
        from database import get_db_cursor

        with get_db_cursor(cursor_factory=None, commit=True) as (_c, cur):
            cur.execute(
                """INSERT INTO maven_pending_actions
                     (approval_id, action, media_type, title, reason, payload)
                   VALUES (%s,'optimize','video',%s,%s,%s)
                   ON CONFLICT (approval_id) DO NOTHING""",
                (approval_id, label, reason,
                 _json.dumps({"file_id": file_id, "resolution": resolution})),
            )
    except Exception as e:  # noqa: BLE001
        log.warning("request_optimize: record failed: %s", e)
    return {"success": True, "approval_id": approval_id, "status": "awaiting_approval"}


def process_approved_optimizes() -> None:
    """Observer job (5-min). Tdarr 2.82 optimizes BY-LIBRARY (no per-file queue —
    /api/v2/manual-queue is 404), so M.A.V.E.N. keeps the engine OFF (approval-gated)
    and, on an owner-approved optimize, ENABLES it — the GPU nodes then re-encode the
    library's HEVC candidates. Two jobs: (1) auto-stop + report a run that has drained;
    (2) start a run for any freshly-approved request. #4762."""
    import tdarr_client
    from archie_coordination import check_approval, log_dispatch, notify_archie

    # (1) Auto-stop a finished run — keeps it approval-gated (engine OFF except during a run).
    try:
        if tdarr_client.is_processing() and tdarr_client.transcode_active() == 0 and tdarr_client.transcode_pending() == 0:
            tdarr_client.set_processing(False)
            # Restore any GPU node the dispatch-orchestration yield-loop left paused (#385)
            # so Tdarr's normal per-node worker limits return immediately.
            for _nid in tdarr_client.gpu_node_ids():
                tdarr_client.resume_gpu_transcodes(_nid, 1)
            notify_archie("Media Hub: optimize run complete",
                          "M.A.V.E.N. finished the approved HEVC optimize run — the Tdarr engine is back OFF (approval-gated).",
                          priority="low")
            log_dispatch("optimize_run_complete", capability="media_optimize",
                         description="approved HEVC optimize run drained — engine disabled, GPU workers restored", success=True)
    except Exception as e:  # noqa: BLE001
        log.warning("process_approved_optimizes: auto-stop check failed: %s", e)

    # (2) Start a run for any freshly-approved optimize request; drop the denied ones.
    try:
        _ensure_table()
        from database import get_db_cursor

        with get_db_cursor(cursor_factory=None) as (_c, cur):
            cur.execute(
                """SELECT approval_id, title FROM maven_pending_actions
                    WHERE status='awaiting' AND action='optimize'
                    ORDER BY created_at LIMIT 20"""
            )
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("process_approved_optimizes: read failed: %s", e)
        return

    for approval_id, title in rows:
        st = check_approval(approval_id)
        if st == "approved":
            import time as _time

            _t0 = _time.monotonic()
            ok = tdarr_client.set_processing(True)  # start the owner-approved optimize run
            _dur = int((_time.monotonic() - _t0) * 1000)
            _mark(approval_id, "executed" if ok else "failed")
            if ok:
                notify_archie("Media Hub: optimize run started",
                              f"Approved — M.A.V.E.N. started a HEVC optimize run on the GPU nodes ({title}). "
                              "Tdarr re-encodes the beneficial candidates and keeps originals when HEVC isn't "
                              "smaller; the engine turns back off when the run drains.", priority="normal")
            else:
                notify_archie(f"Optimize FAILED to start: {title}",
                              "Approved but M.A.V.E.N. could not enable the Tdarr engine (unreachable?).",
                              priority="high")
            log_dispatch("video_optimize", capability="media_optimize",
                         description=f"start approved HEVC optimize run ({title})", success=ok,
                         duration_ms=_dur, target=title)
        elif st in ("denied", "rejected", "cancelled"):
            _mark(approval_id, "denied")


# ── Tdarr library rescan (#4754) — M.A.V.E.N. refreshes her own view ──────────


def library_scan(mode: str = "scanFindNew") -> dict:
    """M.A.V.E.N. rescans the Tdarr library (non-destructive re-index) so
    video_review sees the current files (#4754). The scan runs async in Tdarr;
    success = the scan was accepted + started (Tdarr logs 'Starting file scan').
    Logs the action to the DHQ A.R.M.A.D.A. feed + notifies A.R.C.H.I.E.
    Returns {success, files, mode}."""
    import time as _time

    import tdarr_client

    if not tdarr_client.is_up():
        return {"success": False, "error": "Tdarr unreachable", "files": 0, "mode": mode}
    _t0 = _time.monotonic()
    ok = tdarr_client.library_scan(mode=mode)
    files = len(tdarr_client.library_files())
    _dur = int((_time.monotonic() - _t0) * 1000)

    from archie_coordination import log_dispatch, notify_archie

    # A.R.M.A.D.A. visibility (#4755) — record the rescan as a 0-token action.
    log_dispatch("library_scan", capability="library_scan",
                 description=f"Tdarr rescan ({mode}) — {files} files indexed",
                 success=ok, duration_ms=_dur,
                 metadata={"mode": mode, "files": files})
    if ok:
        notify_archie("Media Hub: Tdarr library rescanned",
                      f"M.A.V.E.N. triggered a Tdarr rescan ({mode}); {files} files indexed.",
                      priority="low")
    else:
        notify_archie("Media Hub: Tdarr rescan FAILED",
                      "M.A.V.E.N. could not trigger a Tdarr rescan (unreachable or rejected).",
                      priority="normal")
    return {"success": ok, "files": files, "mode": mode}
