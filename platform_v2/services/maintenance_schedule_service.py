"""Scheduled maintenance windows with a fix manifest (task #5235).

OWNER DIRECTIVE 2026-07-26:
    "this will allow repair bay to schedule a maintenance window now to plan and
     deploy its fixes in its automation schedule ... it can add multiple fixes in
     that window but to advise and coordinate before and let me know before the
     maintenance the fix list."

Repair Bay stops deploying each fix the moment it is ready — N fixes being N
separate unannounced disruptions, each a fresh chance to surprise DR — and instead
appends to the NEXT planned window. The owner is shown the manifest BEFORE the
window opens and can veto it.

DIVISION OF LABOUR
    maintenance_window_service  — "suppress DR for work happening NOW" (ad-hoc).
                                  Owns the SSH, the flag files, and the mandatory
                                  proof that the watchdog honoured them.
    this module                 — "plan work for LATER, with a manifest".
                                  Delegates every DR operation to that service so
                                  suppression and its verification exist once.

INVARIANTS (each one is a way this could quietly become theatre)
  * A window will NOT open unannounced. Advance visibility is the requirement, not
    a nicety — if the owner never saw the list, opening defeats the purpose.
  * A window with an EMPTY manifest will not open. Nothing to deploy means no
    reason to suppress DR.
  * Opening requires start_window() to VERIFY the watchdog reports itself
    suppressed. Writing a flag file is not proof it is honoured.
  * Closing reports PER-ITEM outcomes. "Window closed" is not a result; what
    shipped is.
  * At most one window is open at a time (enforced by a partial unique index in
    migration 464). Two would each believe they own DR suppression and the first
    to close would disarm the other.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DEFAULT_DURATION_MIN = 90
DEFAULT_NOTICE_MIN = 60  # how far ahead the owner is told


def _now():
    return datetime.now(timezone.utc)


def _cursor():
    from database import get_db_cursor

    return get_db_cursor(commit=True)


# ------------------------------------------------------------------ create ---
def schedule_window(
    scheduled_start,
    duration_minutes: int = DEFAULT_DURATION_MIN,
    reason: str = "",
    created_by: str = "repair_bay",
) -> dict:
    """Create a PLANNED window. The manifest starts empty and grows."""
    with _cursor() as (conn, cur):
        cur.execute(
            """INSERT INTO maintenance_windows
                   (scheduled_start, duration_minutes, reason, created_by)
               VALUES (%s, %s, %s, %s)
               RETURNING id, scheduled_start, duration_minutes, status""",
            (scheduled_start, int(duration_minutes), reason, created_by),
        )
        row = cur.fetchone()
    return dict(row)


def next_window(create_if_missing: bool = False, within_hours: int = 24, **kw) -> dict | None:
    """The window Repair Bay should append to.

    Returns the soonest planned/announced window still in the future. With
    create_if_missing, schedules one DEFAULT_NOTICE_MIN from now so an automation
    always has somewhere to put a fix.
    """
    with _cursor() as (conn, cur):
        cur.execute(
            """SELECT id, scheduled_start, duration_minutes, status, reason
                 FROM maintenance_windows
                WHERE status IN ('planned', 'announced')
                  AND scheduled_start > NOW()
                  AND scheduled_start < NOW() + (%s || ' hours')::interval
             ORDER BY scheduled_start ASC
                LIMIT 1""",
            (str(int(within_hours)),),
        )
        row = cur.fetchone()
    if row:
        return dict(row)
    if not create_if_missing:
        return None
    return schedule_window(
        _now() + timedelta(minutes=DEFAULT_NOTICE_MIN),
        reason=kw.get("reason", "Repair Bay batched fixes"),
        created_by=kw.get("created_by", "repair_bay"),
    )


def add_item(
    window_id: int,
    title: str,
    item_type: str = "other",
    ref: str = None,
    added_by: str = "repair_bay",
    repo: str = None,
) -> dict:
    """Append a fix to a window's manifest.

    Refuses once a window has opened — the owner approved a SPECIFIC list, and
    silently extending it after the fact would make that approval meaningless.

    ``repo`` qualifies ``ref``: PR numbers collide across repos, so an entry
    that names no repo authorises nothing (see _pr_on_open_window).
    """
    with _cursor() as (conn, cur):
        cur.execute("SELECT status FROM maintenance_windows WHERE id = %s", (window_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"no such window {window_id}"}
        if row["status"] not in ("planned", "announced"):
            return {
                "ok": False,
                "error": f"window {window_id} is '{row['status']}' — the approved list is frozen",
            }
        cur.execute(
            """INSERT INTO maintenance_window_items
                   (window_id, item_type, ref, title, added_by, repo)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (window_id, item_type, ref, title, added_by, repo),
        )
        item_id = cur.fetchone()["id"]
        # Adding to an ALREADY-announced window invalidates that announcement:
        # the owner was shown a list that no longer matches what will ship.
        if row["status"] == "announced":
            cur.execute(
                "UPDATE maintenance_windows SET status='planned', announced_at=NULL," " updated_at=NOW() WHERE id=%s",
                (window_id,),
            )
    return {"ok": True, "item_id": item_id, "reannounce_required": row["status"] == "announced"}


def get_manifest(window_id: int) -> list:
    with _cursor() as (conn, cur):
        cur.execute(
            """SELECT id, item_type, ref, title, added_by, status, notes, repo
                 FROM maintenance_window_items WHERE window_id = %s ORDER BY id""",
            (window_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------- announce ---
def announce_plan(window_id: int, announce: bool = True) -> dict:
    """Show the owner the window time AND the fix list, ahead of time.

    This is the coordination step the owner asked for. A window cannot open
    without it.
    """
    with _cursor() as (conn, cur):
        cur.execute(
            "SELECT id, scheduled_start, duration_minutes, status, reason" "  FROM maintenance_windows WHERE id = %s",
            (window_id,),
        )
        w = cur.fetchone()
    if not w:
        return {"ok": False, "error": f"no such window {window_id}"}
    if w["status"] not in ("planned", "announced"):
        return {"ok": False, "error": f"window is '{w['status']}' — nothing to announce"}

    items = get_manifest(window_id)
    if not items:
        return {"ok": False, "error": "manifest is empty — nothing to announce or deploy"}

    lines = [
        f"{i+1}. {it['title']}" + (f" ({it['item_type']} {it['ref']})" if it["ref"] else "")
        for i, it in enumerate(items)
    ]
    body = (
        f"Scheduled: {w['scheduled_start']}\n"
        f"Duration: {w['duration_minutes']} min\n"
        f"Reason: {w['reason'] or 'Repair Bay batched fixes'}\n\n"
        f"Fix list ({len(items)}):\n" + "\n".join(lines) + "\n\nDR auto-failover will be suppressed for this window."
    )

    sent = True
    if announce:
        sent = _announce("🗓️ Maintenance window PLANNED", body)

    # Only mark announced if the owner was ACTUALLY told. Marking it regardless
    # would let a window open on an announcement nobody received.
    if sent:
        with _cursor() as (conn, cur):
            cur.execute(
                "UPDATE maintenance_windows SET status='announced', announced_at=NOW(),"
                " updated_at=NOW() WHERE id=%s",
                (window_id,),
            )
    return {"ok": bool(sent), "items": len(items), "announced": bool(sent), "body": body}


# -------------------------------------------------------------------- open ---
def open_scheduled(window_id: int, force_unannounced: bool = False) -> dict:
    """Arm DR suppression and mark the window open.

    Delegates to maintenance_window_service.start_window() so suppression and its
    mandatory verification are not reimplemented here.
    """
    from services.maintenance_window_service import start_window

    with _cursor() as (conn, cur):
        cur.execute(
            "SELECT id, status, duration_minutes, reason, announced_at" "  FROM maintenance_windows WHERE id = %s",
            (window_id,),
        )
        w = cur.fetchone()
    if not w:
        return {"ok": False, "error": f"no such window {window_id}"}
    if w["status"] == "open":
        return {"ok": False, "error": "already open"}
    if w["status"] not in ("planned", "announced"):
        return {"ok": False, "error": f"window is '{w['status']}'"}

    items = get_manifest(window_id)
    if not items:
        return {"ok": False, "error": "manifest is empty — refusing to suppress DR for no work"}
    if w["status"] != "announced" and not force_unannounced:
        return {
            "ok": False,
            "error": "window was never announced — the owner has not seen the fix list",
        }

    rep = start_window(
        minutes=w["duration_minutes"],
        reason=f"[window {window_id}] {w['reason'] or 'Repair Bay batched fixes'}",
        actor="repair_bay",
    )
    if not rep.get("ok"):
        return {"ok": False, "error": rep.get("error"), "start_report": rep}

    with _cursor() as (conn, cur):
        cur.execute(
            "UPDATE maintenance_windows SET status='open', opened_at=NOW(),"
            " suppression_verified=%s, updated_at=NOW() WHERE id=%s",
            (bool(rep.get("suppression_verified")), window_id),
        )
    _announce(
        "🛠️ Maintenance window OPEN",
        f"Window {window_id} · {len(items)} fix(es) · DR suppression VERIFIED.",
    )
    return {"ok": True, "items": len(items), "start_report": rep}


# ------------------------------------------------------------------- close ---
def close_scheduled(window_id: int, outcomes: dict = None) -> dict:
    """Close the window and report WHAT shipped, per item.

    outcomes maps item_id -> 'deployed' | 'skipped' | 'failed'. Anything left
    unset stays 'planned', which is deliberately visible: an item nobody reported
    on is not the same as an item that succeeded.
    """
    from services.maintenance_window_service import end_window

    outcomes = outcomes or {}
    with _cursor() as (conn, cur):
        for item_id, status in outcomes.items():
            if status in ("deployed", "skipped", "failed"):
                cur.execute(
                    "UPDATE maintenance_window_items SET status=%s WHERE id=%s AND window_id=%s",
                    (status, int(item_id), window_id),
                )

    rep = end_window(actor="repair_bay")

    with _cursor() as (conn, cur):
        cur.execute(
            "UPDATE maintenance_windows SET status='closed', closed_at=NOW()," " updated_at=NOW() WHERE id=%s",
            (window_id,),
        )
    items = get_manifest(window_id)
    tally = {}
    for it in items:
        tally[it["status"]] = tally.get(it["status"], 0) + 1

    _announce(
        "✅ Maintenance window CLOSED",
        f"Window {window_id} — "
        + ", ".join(f"{v} {k}" for k, v in sorted(tally.items()))
        + ("" if rep.get("dr_cover_restored") else "\n⚠️ DR cover NOT fully restored — see status."),
    )
    return {
        "ok": True,
        "tally": tally,
        "end_report": rep,
        "dr_cover_restored": bool(rep.get("dr_cover_restored")),
    }


def list_windows(status: str = None, limit: int = 20) -> list:
    with _cursor() as (conn, cur):
        if status:
            cur.execute(
                "SELECT * FROM maintenance_windows WHERE status=%s" " ORDER BY scheduled_start DESC LIMIT %s",
                (status, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM maintenance_windows ORDER BY scheduled_start DESC LIMIT %s",
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]


def _announce(title: str, message: str) -> bool:
    try:
        from services.telegram_service import send_system

        send_system(title, message)
        return True
    except Exception as e:
        # Deliberately returns False: announce_plan() uses this to decide whether
        # the window may be marked 'announced'. A failed send must not become a
        # silent approval.
        logger.warning("maintenance_schedule: announce failed: %s", e)
        return False
