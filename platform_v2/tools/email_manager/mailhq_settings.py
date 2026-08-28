"""Mail HQ — Slice 5 tunable settings, backed by platform_settings.

Single source of truth for the Smart Inbox knobs. Every key has a sensible default
so the feature works out of the box; values are tunable from the Mail HQ Settings
modal (GET/POST /api/email/settings) or a single UPDATE platform_settings.

Keys:
  mailhq:notify:enabled        bool   instant new-mail Telegram advisory on/off
  mailhq:notify:mailbox_types  csv    which mailbox types get the advisory (owner,business)
  mailhq:notify:quiet_hours    H-H    suppress the advisory in this local window ('' = none)
  mailhq:draft:enabled         bool   the Slice-3 draft-proposal job on/off (also read by draft_proposal_service)
  mailhq:draft:collaborators   bool   the collaborator persona-draft job on/off (human_agent mailboxes; default OFF)
  mailhq:digest:enabled        bool   the daily digest on/off
  mailhq:digest:time           HH:MM  local (ET) time the digest is sent
  mailhq:digest:include_drafts bool   include the "drafts awaiting approval" section
  mailhq:digest:time_evening   HH:MM  optional 2nd digest send time ('' = off)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TZ = "America/Toronto"

# key -> (default, kind) where kind is one of: bool, csv, quiet, time, str
SETTINGS_SPEC: dict[str, tuple[str, str]] = {
    "mailhq:notify:enabled": ("true", "bool"),
    "mailhq:notify:mailbox_types": ("owner,business", "csv"),
    "mailhq:notify:quiet_hours": ("22-7", "quiet"),
    "mailhq:draft:enabled": ("false", "bool"),
    "mailhq:draft:collaborators": ("false", "bool"),
    "mailhq:digest:enabled": ("true", "bool"),
    "mailhq:digest:time": ("08:00", "time"),
    "mailhq:digest:include_drafts": ("true", "bool"),
    "mailhq:digest:time_evening": ("", "time_opt"),
}

_TRUE = {"1", "true", "on", "yes"}


# --------------------------------------------------------------------------- #
# raw get / set
# --------------------------------------------------------------------------- #
def _get(key: str) -> str:
    from database import get_db_cursor

    default = SETTINGS_SPEC.get(key, ("", "str"))[0]
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
    except Exception as exc:
        logger.debug("[mailhq-settings] read failed for %s: %s", key, exc)
        return default
    if not row:
        return default
    val = row["value"] if isinstance(row, dict) else row[0]
    return val if val is not None else default


def is_enabled(key: str) -> bool:
    """True iff the platform_setting `key` holds a truthy flag value."""
    return str(_get(key) or "").strip().lower() in ("1", "true", "on", "yes")


def get_all() -> dict:
    """Return every setting's current (typed) value — drives the Settings modal."""
    out: dict = {}
    for key, (_default, kind) in SETTINGS_SPEC.items():
        raw = _get(key)
        if kind == "bool":
            out[key] = str(raw).strip().lower() in _TRUE
        elif kind == "csv":
            out[key] = [t.strip() for t in str(raw).split(",") if t.strip()]
        else:
            out[key] = raw
    return out


def set_many(updates: dict) -> dict:
    """Validate + persist a subset of settings. Returns {ok, applied, errors}."""
    from database import get_db_cursor

    applied: dict = {}
    errors: list = []
    for key, value in (updates or {}).items():
        if key not in SETTINGS_SPEC:
            errors.append(f"unknown key {key}")
            continue
        kind = SETTINGS_SPEC[key][1]
        norm = _normalize(kind, value)
        if norm is None:
            errors.append(f"invalid value for {key}: {value!r}")
            continue
        applied[key] = norm

    if applied:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                for key, norm in applied.items():
                    cur.execute(
                        """INSERT INTO platform_settings (key, value) VALUES (%s, %s)
                           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                        (key, norm),
                    )
        except Exception as exc:
            logger.error("[mailhq-settings] write failed: %s", exc)
            return {"ok": False, "applied": {}, "errors": [str(exc)]}

    return {"ok": not errors, "applied": applied, "errors": errors}


def _normalize(kind: str, value) -> str | None:
    """Coerce + validate a UI value to its stored string form, or None if invalid."""
    if kind == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        return "true" if str(value).strip().lower() in _TRUE else "false"
    if kind == "csv":
        if isinstance(value, list):
            items = [str(t).strip() for t in value if str(t).strip()]
        else:
            items = [t.strip() for t in str(value).split(",") if t.strip()]
        allowed = {"owner", "business", "human_agent", "ai_agent"}
        if not items or any(t not in allowed for t in items):
            return None
        return ",".join(items)
    if kind == "time":
        try:
            hh, mm = str(value).strip().split(":")
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        except Exception:
            return None
        return None
    if kind == "quiet":
        raw = str(value).strip()
        if raw == "":
            return ""
        try:
            s, e = raw.split("-")
            si, ei = int(s), int(e)
            if 0 <= si <= 23 and 0 <= ei <= 23:
                return f"{si}-{ei}"
        except Exception:
            return None
        return None
    if kind == "time_opt":
        raw = str(value).strip()
        if raw == "":
            return ""
        try:
            hh, mm = raw.split(":")
            h, m = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        except Exception:
            return None
        return None
    return str(value)


# --------------------------------------------------------------------------- #
# typed getters used by the workers
# --------------------------------------------------------------------------- #
def _bool(key: str) -> bool:
    return str(_get(key)).strip().lower() in _TRUE


def notify_enabled() -> bool:
    return _bool("mailhq:notify:enabled")


def notify_mailbox_types() -> set:
    raw = _get("mailhq:notify:mailbox_types") or "owner,business"
    return {t.strip() for t in raw.split(",") if t.strip()}


def digest_enabled() -> bool:
    return _bool("mailhq:digest:enabled")


def digest_include_drafts() -> bool:
    return _bool("mailhq:digest:include_drafts")


def digest_time() -> tuple[int, int]:
    raw = _get("mailhq:digest:time") or "08:00"
    try:
        hh, mm = raw.split(":")
        return int(hh), int(mm)
    except Exception:
        return 8, 0


def digest_time_evening() -> tuple[int, int] | None:
    """Optional 2nd digest slot. Returns (hour, minute) or None when unset/off."""
    raw = (_get("mailhq:digest:time_evening") or "").strip()
    if not raw:
        return None
    try:
        hh, mm = raw.split(":")
        return int(hh), int(mm)
    except Exception:
        return None


def _local_now():
    from zoneinfo import ZoneInfo

    from services.time_utils import now_utc

    return now_utc().astimezone(ZoneInfo(_TZ))


def in_quiet_hours() -> bool:
    """True if the current local (ET) hour falls in the quiet window (e.g. '22-7')."""
    raw = (_get("mailhq:notify:quiet_hours") or "").strip()
    if not raw or "-" not in raw:
        return False
    try:
        s, e = raw.split("-")
        start, end = int(s), int(e)
    except Exception:
        return False
    if start == end:
        return False
    hour = _local_now().hour
    if start < end:
        return start <= hour < end
    # window wraps midnight (e.g. 22-7 => 22:00..06:59)
    return hour >= start or hour < end


# --------------------------------------------------------------------------- #
# digest schedule self-gating (so the time is UI-tunable with no redeploy)
# --------------------------------------------------------------------------- #
# internal state: "YYYY-MM-DD|slot,slot" (e.g. "2026-06-27|morning,evening").
# A bare legacy "YYYY-MM-DD" value is treated as the morning slot having been sent.
_DIGEST_LAST_SENT_KEY = "mailhq:digest:last_sent"


def _digest_sent_slots(today: str) -> set:
    """Which digest slots have already been sent today (per the stored marker)."""
    raw = (_get(_DIGEST_LAST_SENT_KEY) or "").strip()
    if not raw:
        return set()
    parts = raw.split("|", 1)
    if parts[0] != today:
        return set()  # marker is from a previous day → nothing sent today
    if len(parts) == 1:
        return {"morning"}  # legacy bare-date marker == morning already sent
    return {s for s in parts[1].split(",") if s}


def _digest_slots_due() -> set:
    """Slots ('morning' + optional 'evening') that are due NOW and unsent today."""
    if not digest_enabled():
        return set()
    now = _local_now()
    sent = _digest_sent_slots(now.strftime("%Y-%m-%d"))
    cur = (now.hour, now.minute)
    due = set()
    if "morning" not in sent and cur >= digest_time():
        due.add("morning")
    ev = digest_time_evening()
    if ev is not None and "evening" not in sent and cur >= ev:
        due.add("evening")
    return due


def digest_due() -> bool:
    """True if any digest slot (morning or optional evening) is due now and unsent
    today. The job runs every 15 min and gates here; kept bool for the caller."""
    return bool(_digest_slots_due())


def mark_digest_sent() -> None:
    """Mark the currently-due slot(s) as sent today (prevents re-send of that slot)."""
    from database import get_db_cursor

    now = _local_now()
    today = now.strftime("%Y-%m-%d")
    slots = _digest_sent_slots(today) | _digest_slots_due()
    if not slots:
        slots = {"morning"}  # defensive: only called right after a real send
    value = f"{today}|{','.join(sorted(slots))}"
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO platform_settings (key, value) VALUES (%s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (_DIGEST_LAST_SENT_KEY, value),
            )
    except Exception as exc:
        logger.debug("[mailhq-settings] mark_digest_sent failed: %s", exc)
