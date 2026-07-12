"""COO command surface — COMs/Telegram hub read layer (Slice 2). Reproduces the DHQ COMs
tab's READ logic (telegram_message_log feed + config + migration) so the cockpit can surface
it read-only. Mutations stay in DHQ. DRY: reuses coms_routes.KNOWN_SENDERS."""

from __future__ import annotations

import os

_MSG_COLS = "id, category, title, message, source_agent, source_department, source_module, priority, status, created_at"


def _get_cursor():
    from database import get_db_cursor

    return get_db_cursor


def list_messages(limit=50, category=None, source_agent=None, status=None):
    q = f"SELECT {_MSG_COLS} FROM telegram_message_log WHERE 1=1"
    params = []
    if category:
        q += " AND category = %s"
        params.append(category)
    if source_agent:
        q += " AND source_agent = %s"
        params.append(source_agent)
    if status:
        q += " AND status = %s"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT %s"
    params.append(int(limit))
    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(q, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at") is not None:
            d["created_at"] = str(d["created_at"])
        out.append(d)
    return out


def config_summary():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    categories = {}
    try:
        from services.telegram_service import CATEGORIES

        for name, meta in (CATEGORIES or {}).items():
            categories[name] = {
                "icon": (meta or {}).get("icon", ""),
                "label": (meta or {}).get("label", name),
                "priority": (meta or {}).get("priority", ""),
            }
    except Exception:
        pass
    return {"bot_token_set": bool(token), "chat_id": chat_id, "categories": categories}


def migration_summary():
    try:
        from tools.department_hq.coms_routes import KNOWN_SENDERS
    except Exception:
        KNOWN_SENDERS = []
    seen = set()
    try:
        get_db_cursor = _get_cursor()
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute("SELECT DISTINCT source_module FROM telegram_message_log WHERE source_module IS NOT NULL")
            for r in cur.fetchall():
                seen.add(dict(r).get("source_module"))
    except Exception:
        pass
    senders = []
    migrated = 0
    for s in KNOWN_SENDERS:
        mod = s.get("module")
        st = "migrated" if mod in seen else "pending"
        if st == "migrated":
            migrated += 1
        senders.append(
            {
                "module": mod,
                "location": s.get("location"),
                "purpose": s.get("purpose"),
                "agent": s.get("agent"),
                "status": st,
            }
        )
    total = len(KNOWN_SENDERS)
    pct = round(migrated / total * 100) if total else 0
    return {"senders": senders, "progress": {"migrated": migrated, "total": total, "percentage": pct}}


def overview(limit=50, category=None, source_agent=None, status=None):
    return {
        "messages": list_messages(limit=limit, category=category, source_agent=source_agent, status=status),
        "config": config_summary(),
        "migration": migration_summary(),
    }
