"""Per-lane dormancy observer (project #380).

WHY THIS EXISTS: every autonomous coder on this platform was built, merged, and
then quietly stopped. Codex last dispatched 2026-06-28; the archie_engine build
loop 2026-07-20. Neither was broken -- nothing queued work, and nothing reported
the silence. The three-lane design therefore treats a liveness signal as part of
the architecture, not a follow-up.

Same shape as ``backup_posture_monitor``: deterministic, NO LLM in the alert
path, send_system cooldowns, and a lane that has NEVER run reports 'unknown'
rather than alerting -- a fresh deploy must not page.
"""

from datetime import timezone

from services.time_utils import now_utc

# Lane -> the module_source values its dispatches carry in task_execution_log.
# Measured 2026-08-23: claude_cli / codex_cli / archie_engine+archie_code_engine.
LANES: dict = {
    "claude": {"label": "Claude CLI", "module_sources": ("claude_cli",)},
    "codex": {"label": "Codex CLI", "module_sources": ("codex_cli",)},
    "engine": {
        "label": "A.R.C.H.I.E. local",
        "module_sources": ("archie_engine", "archie_code_engine"),
    },
}

# Generous on purpose. These lanes are meant to be busy; the alarm is for
# "has fallen silent", not "is briefly idle".
STALE_HOURS: dict = {"claude": 72.0, "codex": 168.0, "engine": 168.0}


def lane_status(rows: list, now=None) -> list:
    """PURE. rows = [{module_source, last_dispatch}] -> one status dict per lane."""
    now = now or now_utc()
    newest: dict = {}
    for r in rows or []:
        src = r.get("module_source")
        ts = r.get("last_dispatch")
        if not src or not ts:
            continue
        for lane, cfg in LANES.items():
            if src in cfg["module_sources"]:
                if lane not in newest or ts > newest[lane]:
                    newest[lane] = ts

    out = []
    for lane, cfg in LANES.items():
        ts = newest.get(lane)
        if ts is None:
            out.append(
                {
                    "lane": lane,
                    "label": cfg["label"],
                    "last_dispatch": None,
                    "age_hours": None,
                    "status": "unknown",
                }
            )
            continue
        age = round((now - ts).total_seconds() / 3600.0, 1)
        out.append(
            {
                "lane": lane,
                "label": cfg["label"],
                "last_dispatch": ts.isoformat(),
                "age_hours": age,
                "status": "stale" if age > STALE_HOURS[lane] else "ok",
            }
        )
    return out


def check_lane_liveness(alert: bool = True) -> dict:
    """Measure every lane; alert on newly-stale ones. Never raises into a caller."""
    from database import get_db_cursor

    sources = [s for cfg in LANES.values() for s in cfg["module_sources"]]
    rows = []
    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT module_source, MAX(created_at) AS last_dispatch "
                "FROM task_execution_log WHERE module_source = ANY(%s) "
                "GROUP BY module_source",
                (sources,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            # task_execution_log.created_at is `timestamp WITHOUT time zone`
            # (deviates from the platform's TIMESTAMPTZ convention -- see
            # ai-bridge.md), so psycopg2 hands back naive datetimes here.
            # Treat them as UTC (the column is always written via now_utc()
            # elsewhere) so they compare against the aware now_utc() below.
            for row in rows:
                ts = row.get("last_dispatch")
                if ts is not None and ts.tzinfo is None:
                    row["last_dispatch"] = ts.replace(tzinfo=timezone.utc)
    except Exception as exc:  # observability must never break its caller
        return {"checked_at": now_utc().isoformat(), "lanes": [], "stale": [], "error": f"{type(exc).__name__}: {exc}"}

    lanes = lane_status(rows)
    stale = [d["lane"] for d in lanes if d["status"] == "stale"]

    if alert and stale:
        try:
            from services.telegram_service import send_system

            for d in lanes:
                if d["status"] != "stale":
                    continue
                # Lane name in the TITLE: send_system dedups on (title, source),
                # so a shared title would mute every other lane.
                send_system(
                    f"Coder lane dormant: {d['label']}",
                    f"No dispatch for {d['age_hours']}h "
                    f"(threshold {STALE_HOURS[d['lane']]}h). "
                    f"Last seen {d['last_dispatch']}.",
                    cooldown_hours=24.0,
                )
        except Exception:
            pass

    return {"checked_at": now_utc().isoformat(), "lanes": lanes, "stale": stale}
