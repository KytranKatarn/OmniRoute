"""send_alert had no cooldown, so watchdogs re-announced standing conditions forever.

MEASURED 2026-09-22, 24h of ACTUAL DELIVERIES (status='sent', not log rows — the log also
records throttled messages that never left the building):

    system            486   <- this file
    approval_request  318   <- #6834, separate
    everything else    38

Top `system` titles, all one unresolved condition repeated:
    76x  HR Alert: Ollama KEEP_ALIVE stalled on 1 model(s)
    28x  WTF ingest stalled
    28x  Platform Watchdog: DISK_PRIMARY pressure
    28x  Platform Watchdog: BACKUP_TIER_HEALTH pressure

ROOT CAUSE: two send paths, one guard. `send_system` passes cooldown_hours=2.0 into
`submit_via_inbox`, which dedups. Every watchdog instead calls `send_alert`, which had
ONLY `is_snoozed()` — a manual, human-set mute. Nothing automatic. Same house shape as
#5194 / #5862 / #2738: a correct guard that the other path does not use.

⚠️ THE COOLDOWN IS DB-BACKED, NOT IN-PROCESS. `director_report_service._dedup_cache` is a
module-level dict, and `archie_platform` runs `--workers 4`, so an in-memory cooldown lets
up to 4x through (KB #282671) and resets on restart. `telegram_message_log` already records
every delivery, so it is the durable cross-process source of truth and needs no new table.

⚠️ FAIL-OPEN. A DB error must let the alert through: suppressing on error would silence a
watchdog exactly when the platform is unhealthy, which is when it matters most.
"""

from __future__ import annotations

import pytest

from database import get_db_cursor
from services.telegram_service import _recently_delivered

_TITLE = "pytest_cooldown_probe_title"
_CAT = "system"


@pytest.fixture
def clean():
    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute("DELETE FROM telegram_message_log WHERE title = %s", (_TITLE,))
    yield
    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute("DELETE FROM telegram_message_log WHERE title = %s", (_TITLE,))


def _seed(status="sent", minutes_ago=5):
    with get_db_cursor(commit=True) as (_c, cur):
        cur.execute(
            "INSERT INTO telegram_message_log (category, title, message, status, created_at)"
            " VALUES (%s,%s,'probe',%s, now() - (%s || ' minutes')::interval)",
            (_CAT, _TITLE, status, str(minutes_ago)),
        )


def test_nothing_sent_recently_means_send(clean):
    assert _recently_delivered(_CAT, _TITLE, cooldown_hours=2.0) is False


def test_a_recent_delivery_suppresses(clean):
    _seed(minutes_ago=5)
    assert _recently_delivered(_CAT, _TITLE, cooldown_hours=2.0) is True


def test_an_old_delivery_does_not_suppress(clean):
    _seed(minutes_ago=200)  # older than the 2h window
    assert _recently_delivered(_CAT, _TITLE, cooldown_hours=2.0) is False


def test_a_throttled_row_is_not_a_delivery(clean):
    """The log records throttled messages that never reached Telegram.

    Counting one as a delivery would suppress an alert the owner never actually saw —
    exactly the mistake that made the first read of this data say 2,255 instead of 842.
    """
    _seed(status="throttled", minutes_ago=5)
    assert _recently_delivered(_CAT, _TITLE, cooldown_hours=2.0) is False


def test_zero_cooldown_disables_suppression(clean):
    _seed(minutes_ago=1)
    assert _recently_delivered(_CAT, _TITLE, cooldown_hours=0) is False


def test_a_different_title_is_a_different_condition(clean):
    _seed(minutes_ago=1)
    assert _recently_delivered(_CAT, "some other condition", cooldown_hours=2.0) is False


def test_send_alert_actually_consults_the_cooldown():
    """A guard nobody calls is the bug this fixes — #5194/#5862/#2738 all over again.

    Parsed with `ast`, not grepped: a source-grep matches this docstring.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("/app/services/alert_actions_service.py").read_text())
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "send_alert"),
        None,
    )
    assert fn is not None, "send_alert not found — the wiring target moved"
    names = {getattr(c.func, "id", "") or getattr(c.func, "attr", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_recently_delivered" in names, "send_alert never checks the cooldown — floods again"
