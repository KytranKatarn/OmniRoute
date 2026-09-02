"""Academy Standby — quiesce the fleet so a benchmark measures the MODEL, not the queue.

WHY THIS EXISTS. Benchmarking under load measures contention. Live 7-day volumes
on this fleet: bias_quick 2,751 · beat_classification 2,610 · factcheck_quick
2,487 · warmup 2,418 · translate 2,412 · geo_extraction 2,180. Timing a candidate
model against that is timing the backlog, and the resulting "winner" is an
artefact of whatever else happened to be draining.

⚠️ AUX POWER DOES NOT DO THIS, and it is easy to assume it does. Its own tooltip
is explicit: "Stable split, never a filter: everything else still drains in
priority order." Every fleet dispatch mode PRIORITISES; none of them make the
cluster quiet (decision #995). Standby is the missing capability, not a rename of
an existing one.

## Why this is a work-control toggle and NOT a new dispatch mode

`fleet_dashboard_routes` calls `VALID_MODES = ("auto","news","platform")` the
"trio contract", which the dispatcher's node-ordering block **reads raw** — which
is precisely why AUX POWER put its focus in its OWN key instead of adding a
fourth mode. Adding one here would break the same contract, and would also have
to fight the split-never-filter invariant at the drain.

The noise is JOBS, not ad-hoc dispatch. `work_control_service` already exposes
148 individually-toggleable controls, tested and reversible. So Standby is a
*saved, expiring mass-toggle* of that existing surface: no new gate, no change to
placement, nothing to unwind in the dispatcher.

## The three safety properties, and why each is load-bearing

1. **RESTORE FROM A SNAPSHOT, NEVER A BLANKET RE-ENABLE.** `fleet_backlog_runner`
   is currently OFF by deliberate operator choice. "Turn everything back on"
   would silently arm it. A bulk operation over N controls is N decisions
   (feedback_bulk-ops-are-n-decisions) — so release() replays the exact prior
   value of each key it touched, and touches nothing else.
2. **MANDATORY TTL.** A standby nobody remembers to release starves the platform
   indefinitely, and the symptom (everything mysteriously idle) looks nothing
   like the cause. `arm()` REQUIRES a ttl and clamps it; `expire_if_due()` is
   safe to call from any scheduler tick.
3. **PROTECTED KEYS STAY ON.** The point is to run tests AND ship PRs, so review,
   deploy, approvals, and every safety/health monitor keep running. Quiescing the
   watchdogs during a period of unusual load is how an incident goes unseen.

⚠️ DRY-RUN BY DEFAULT, matching `residency_activation.activate()`. `arm()` with
no argument tells you what it WOULD hold and changes nothing.
"""

from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger(__name__)

# Held work resumes when standby ends; these must never stop even for a moment.
# Matched against the control key, case-insensitive, as a whole-key search.
_PROTECT = re.compile(
    # ship the work:            review / deploy / approvals
    r"forge|review|^pr_|deploy|approval|merge"
    # keep the lights on:       health, watchdogs, DR, backups, posture
    r"|backup|posture|heartbeat|health|watchdog|reaper|dr_|drift"
    # never stand down SECURITY. Caught by the first dry run: agent_auto_block,
    # agent_anomaly_detection and agent_camera_anomaly were about to be held, so
    # a 45-minute benchmark window would have quietly stopped auto-blocking
    # threats. A test window is exactly when unusual load makes an incident
    # easiest to miss.
    r"|vigil|anomaly|auto_block|threat|security|intrusion|camera"
    # governance + welfare accounting stay honest through the window
    r"|creed|welfare|residency",
    re.I,
)

_KEY_ARMED = "academy:standby:armed"
_KEY_EXPIRES = "academy:standby:expires_at"
_KEY_SNAPSHOT = "academy:standby:snapshot"
_KEY_NOTE = "academy:standby:note"

MIN_TTL_MIN = 5
MAX_TTL_MIN = 240
DEFAULT_TTL_MIN = 45


def is_protected(key: str) -> bool:
    """Does this control keep running through standby?"""
    return bool(_PROTECT.search(key or ""))


def plan_standby(controls: list[dict]) -> dict:
    """PURE. Split the control surface into what to hold and what to protect.

    Only controls that are currently ENABLED are candidates: disabling an
    already-disabled control is a no-op that would still land in the snapshot and
    then be "restored" to off, making release() look like it changed things it
    did not.
    """
    # DEDUPED: list_controls() really does return duplicates — `fleet_backlog_runner`
    # appears twice live. Without this the counts double-count and a held key gets
    # toggled twice, so "held 115" would not match the number of distinct controls
    # actually touched. First occurrence wins; a later row cannot flip a decision.
    hold, protected, already_off = [], [], []
    seen: set[str] = set()
    for c in controls or []:
        if not isinstance(c, dict):
            continue
        key = (c.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if is_protected(key):
            protected.append(key)
        elif c.get("enabled"):
            hold.append(key)
        else:
            already_off.append(key)
    return {
        "hold": sorted(hold),
        "protected": sorted(protected),
        "already_off": sorted(already_off),
    }


def clamp_ttl(minutes) -> int:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        m = DEFAULT_TTL_MIN
    return max(MIN_TTL_MIN, min(MAX_TTL_MIN, m))


def describe(plan: dict, ttl_min: int, dry_run: bool) -> str:
    prefix = "WOULD hold" if dry_run else "HOLDING"
    return (
        f"Academy Standby: {prefix} {len(plan['hold'])} control(s) for {ttl_min} min; "
        f"{len(plan['protected'])} protected (review/deploy/safety keep running); "
        f"{len(plan['already_off'])} already off (untouched)."
    )


# ---------------------------------------------------------------------------
# I/O — every function below is fail-soft; a standby that half-applies must be
# releasable, so the snapshot is written BEFORE any control is changed.
# ---------------------------------------------------------------------------


def _set(key: str, value: str) -> None:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """INSERT INTO platform_settings (key, value)
               VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (key, value),
        )


def _get(key: str, default=None):
    from database import get_db_cursor

    try:
        with get_db_cursor() as (_, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row["value"] if row else default
    except Exception as exc:
        log.warning("academy_standby: settings read failed for %s: %s", key, exc)
        return default


def arm(ttl_minutes: int = DEFAULT_TTL_MIN, *, dry_run: bool = True, note: str = "") -> dict:
    """Hold non-essential work. DRY-RUN BY DEFAULT — pass dry_run=False to apply."""
    from services.work_control_service import list_controls, set_enabled

    ttl = clamp_ttl(ttl_minutes)
    plan = plan_standby(list_controls() or [])
    summary = describe(plan, ttl, dry_run)

    if dry_run:
        return {"ok": True, "dry_run": True, "ttl_min": ttl, **plan, "summary": summary}

    if status().get("armed"):
        return {"ok": False, "error": "already armed — release() first", **status()}

    expires = int(time.time()) + ttl * 60
    # Snapshot FIRST. If the toggling loop dies halfway, release() can still put
    # everything back; the reverse order would strand held controls with no record.
    _set(_KEY_SNAPSHOT, json.dumps({k: True for k in plan["hold"]}))
    _set(_KEY_EXPIRES, str(expires))
    _set(_KEY_NOTE, note or "")
    _set(_KEY_ARMED, "true")

    held, failed = [], []
    for key in plan["hold"]:
        try:
            set_enabled(key, False)
            held.append(key)
        except Exception as exc:  # keep going — a partial hold is releasable
            log.warning("academy_standby: could not hold %s: %s", key, exc)
            failed.append(key)

    log.info("%s (held=%d failed=%d)", summary, len(held), len(failed))
    return {
        "ok": True,
        "dry_run": False,
        "ttl_min": ttl,
        "expires_at": expires,
        "held": held,
        "failed": failed,
        "protected": plan["protected"],
        "summary": summary,
    }


def release() -> dict:
    """Restore EXACTLY what was held. Never a blanket re-enable."""
    from services.work_control_service import set_enabled

    if not status().get("armed"):
        return {"ok": True, "restored": [], "note": "not armed"}

    try:
        snapshot = json.loads(_get(_KEY_SNAPSHOT) or "{}")
    except ValueError:
        snapshot = {}
        log.warning("academy_standby: snapshot unreadable — nothing to restore")

    restored, failed = [], []
    for key, was_enabled in snapshot.items():
        try:
            set_enabled(key, bool(was_enabled))
            restored.append(key)
        except Exception as exc:
            log.warning("academy_standby: could not restore %s: %s", key, exc)
            failed.append(key)

    _set(_KEY_ARMED, "false")
    _set(_KEY_SNAPSHOT, "{}")
    _set(_KEY_EXPIRES, "0")
    log.info("Academy Standby released: restored=%d failed=%d", len(restored), len(failed))
    return {"ok": True, "restored": restored, "failed": failed}


def status() -> dict:
    armed = str(_get(_KEY_ARMED, "false")).lower() == "true"
    try:
        expires = int(_get(_KEY_EXPIRES, "0") or 0)
    except (TypeError, ValueError):
        expires = 0
    remaining = max(0, expires - int(time.time())) if armed else 0
    try:
        held = len(json.loads(_get(_KEY_SNAPSHOT) or "{}"))
    except ValueError:
        held = 0
    return {
        "armed": armed,
        "expires_at": expires,
        "remaining_min": round(remaining / 60.0, 1),
        "held_count": held,
        "note": _get(_KEY_NOTE, "") or "",
        "expired": bool(armed and expires and remaining == 0),
    }


def expire_if_due() -> dict:
    """Auto-release once the TTL is up. Safe to call from any scheduler tick."""
    st = status()
    if st.get("expired"):
        log.info("Academy Standby TTL elapsed — auto-releasing")
        return {"expired": True, **release()}
    return {"expired": False, **st}
