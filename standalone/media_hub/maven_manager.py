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
    from archie_coordination import check_approval, notify_archie

    try:
        _ensure_table()
        from database import get_db_cursor

        with get_db_cursor(cursor_factory=None) as (_c, cur):
            cur.execute(
                """SELECT approval_id, media_type, tmdb_id, title, year
                     FROM maven_pending_actions
                    WHERE status='awaiting'
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
            from tools.media_hub.routes import _delete_library_item

            res = _delete_library_item(media_type=media_type, tmdb_id=tmdb_id, title=title, year=year)
            if res.get("success"):
                _mark(approval_id, "executed")
                notify_archie(f"Removed {media_type}: {label}",
                              f"Approved removal complete — {res.get('deleted')}",
                              priority="normal")
            else:
                _mark(approval_id, "failed")
                notify_archie(f"Removal FAILED: {label}",
                              f"Approved but the delete failed: {res.get('error')}",
                              priority="high")
        elif status in ("denied", "rejected", "cancelled"):
            _mark(approval_id, "denied")
            log.info("removal %s (%s) denied — dropped", approval_id, label)
        # else: still pending -> leave for the next cycle
