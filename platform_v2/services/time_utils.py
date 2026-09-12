"""
Platform-wide timezone helpers.

The platform contract:
  * **Storage** — Postgres TIMESTAMPTZ, normalized to UTC.
  * **Backend internals** — timezone-aware UTC datetimes (never naive).
  * **User-facing strings** — America/Toronto with EDT/EST suffix.

Use these helpers for any datetime that flows TO a user (HTML reports,
Telegram messages, audit pages, exported docs). Never construct
user-facing time strings with bare `datetime.now().strftime(...)` —
that's ambiguous about TZ and silently broken across DST transitions.

For internal/storage timestamps, use `now_utc()` instead of the
deprecated `datetime.utcnow()` (Python 3.12+).

Examples:
  from services.time_utils import now_utc, now_local_str, format_local

  row["created_at"] = now_utc()                       # → aware UTC
  msg = f"Report generated {now_local_str()}"          # → "2026-05-05 14:32:01 EDT"
  age = format_local(row["created_at"], "%b %d, %I:%M %p")  # → "May 5, 02:32 PM"
"""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Toronto")
UTC = timezone.utc

# Default formats for the most common cases — keep both forms because
# strftime "%Z" gives you the TZ abbreviation (EDT/EST) which is the
# whole point of localizing.
FMT_DATETIME_LOCAL = "%Y-%m-%d %H:%M:%S %Z"
FMT_DATETIME_LOCAL_SHORT = "%Y-%m-%d %H:%M %Z"
FMT_DATE_ONLY = "%Y-%m-%d"
FMT_FILENAME_TIMESTAMP = "%Y%m%d_%H%M%S"  # for filenames; TZ-agnostic, just date+time digits


def now_utc() -> datetime:
    """Current time as a timezone-aware UTC datetime.

    Replacement for `datetime.utcnow()` (deprecated in Python 3.12) — never
    returns a naive datetime, so it composes safely with TIMESTAMPTZ writes
    and timezone-aware comparisons."""
    return datetime.now(UTC)


def now_local() -> datetime:
    """Current time as a timezone-aware America/Toronto datetime."""
    return datetime.now(LOCAL_TZ)


def now_local_str(fmt: str = FMT_DATETIME_LOCAL) -> str:
    """Current time formatted in America/Toronto with TZ suffix.

    Default output: '2026-05-05 14:32:01 EDT' (DST-aware — flips to EST
    automatically in winter)."""
    return now_local().strftime(fmt)


def to_local(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert any datetime to America/Toronto.

    Naive datetimes are assumed UTC (defence in depth — psycopg2 returns
    aware UTC for TIMESTAMPTZ columns, but legacy code may pass naive).

    Returns None if input is None — keeps callers simple."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ)


def format_local(dt: Optional[datetime], fmt: str = FMT_DATETIME_LOCAL) -> str:
    """Render a datetime in America/Toronto.

    Returns empty string for None — callers can use this directly in
    template f-strings without an explicit guard."""
    local = to_local(dt)
    if local is None:
        return ""
    return local.strftime(fmt)


def format_duration(ms: int) -> str:
    """Render a millisecond duration as a compact human string.

    * < 1000 ms        → "500ms"
    * < 60 s           → one decimal second, e.g. "1.5s"
    * ≥ 60 s           → "1m 5s" (seconds omitted when zero, e.g. "2m")

    Raises ValueError on negative input."""
    if ms < 0:
        raise ValueError(f"duration cannot be negative: {ms}")
    if ms < 1000:
        return f"{ms}ms"
    tenths = (ms + 50) // 100
    if tenths < 600:
        return f"{tenths / 10:.1f}s"
    total_s = (tenths + 5) // 10
    minutes, secs = divmod(total_s, 60)
    if secs:
        return f"{minutes}m {secs}s"
    return f"{minutes}m"
