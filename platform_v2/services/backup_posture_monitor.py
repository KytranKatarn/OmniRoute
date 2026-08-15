"""Alert-only watchdog for the PRIMARY backup tier and every OFF-SITE tier.

Born from 2026-07-20: full backups had been OOM-killed for an unknown length of time, the
last successful primary backup silently aged past 12 hours, and NOTHING told anyone. It
surfaced only because someone happened to query `backup_log` while chasing an unrelated bug.

There WAS a job meant to catch this — W.A.R.D.E.N.'s "Daily Backup Integrity Check" — and it
had two independent defects:

  1. it queried ``FROM backups``, a table that does not exist (the table is ``backup_log``),
     so every run threw and its ``except`` swallowed the error; and
  2. even on success it had no alert path at all — it asked an LLM to "flag anything that
     needs attention" and wrote the answer into a log row nobody reads.

So the checks here are DETERMINISTIC and do not depend on a model being warm, reachable, or
correct. An alert that only fires when an LLM cooperates is not an alert. This mirrors
``dr_posture_monitor`` (same shape, same send_system cooldowns) but watches tier='primary'
— DR freshness was already monitored; the tier we actually restore from was not.

Widened 2026-07-22 (#5094): watching only tier='primary' left the same blind spot one level
out. The nightly local dump succeeded every night from 2026-06-29 to 07-21 while the Google
Drive copy of the database did not exist (quota full) and, from 07-11, no off-site tier was
being written at all — and this module reported healthy throughout. Check 3 now measures the
last SUCCESS per off-site tier independently.

Never mutates anything.
"""

from __future__ import annotations

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

# The primary backup is nightly, so anything past ~a day means a run was missed or failed.
# Deliberately NOT the 6h deploy-gate threshold — that governs whether it is safe to deploy,
# which is a stricter question than whether backups are healthy.
PRIMARY_STALE_HOURS = 26.0

# Window for "attempts are failing". A failed nightly matters even when a later manual
# backup succeeded — the automation is still broken and will be relied on unattended.
FAILURE_LOOKBACK_HOURS = 24.0

# backup_log.status values seen in the wild: success / failed / partial / skipped / prune.
# 'partial' counts as a failure: a half-written backup is not a restore point, and it is the
# most dangerous value because it looks plausible.
_FAILURE_STATUSES = ("failed", "partial")

# ---------------------------------------------------------------------------------------
# OFF-SITE tier freshness (#5094, born from #5092).
#
# The primary tier can look perfectly green while every OFF-SITE copy is dead. That is
# exactly what happened 2026-06-29 -> 07-21: the DB dump stopped reaching Google Drive
# (free-tier quota full, nothing ever pruned the gdrive tier), and from 07-11 a failed
# non-critical component skipped ALL tier sync. The nightly local dump succeeded the whole
# time, so the primary check above stayed happy and NOTHING paged for three weeks.
#
# usb gets more slack than the network tiers on purpose: it is removable media, and a drive
# unplugged over a long weekend should not page. Every value is overridable at runtime via
# platform_settings key 'backup:freshness:<tier>' (hours) — no deploy needed.
OFFSITE_STALE_HOURS = {
    "gdrive": 48.0,
    "dr": 48.0,
    "vps": 48.0,
    "usb": 72.0,
}

# ---------------------------------------------------------------------------------------
# #5619: an alert must QUOTE the recorded failure, not merely count failures.
#
# These two are PURE so they can be tested without a database — and that matters here:
# pytest's conftest points at a TEST db with no backup_log rows, so every tier reports
# 'unknown' and no alert is emitted. An end-to-end assertion like "a fresh tier produces
# no alert" therefore passes WITHOUT EXERCISING ANYTHING. Test the decision, not the wiring.
# ---------------------------------------------------------------------------------------
_CAUSE_MAX = 300
_TRACEBACK_MARKER = "Traceback (most recent call last)"


def short_cause(msg) -> str:
    """Condense a stored error_message to the actionable head.

    Drops an appended Python traceback: the useful sentence is always first, and a
    traceback would consume the whole budget and push the real cause out of the alert.
    Measured on the live gdrive row, whose stored text is cause + full traceback.
    Falls back to the raw text when the message is ONLY a traceback, so a non-empty
    error can never render as blank.
    """
    text = str(msg or "")
    head = text.split(_TRACEBACK_MARKER)[0]
    return " ".join(head.split())[:_CAUSE_MAX] or " ".join(text.split())[:_CAUSE_MAX]


def cause_line(err) -> str:
    """The sentence that leads the alert body.

    With a recorded cause the alert points at the real problem; without one it says so
    plainly and names the file that does have it, rather than implying the DB holds an
    answer it does not. On 2026-08-15 the static advice sent an investigation at Drive
    quota for the better part of an hour while every failed row already said
    `invalid_grant` — an expired OAuth token.
    """
    if err:
        return "RECORDED CAUSE (newest failed row): %s -- fix THIS before following the " "generic advice below. " % err
    return (
        "No error_message recorded on any failed row for this tier, so the cause is NOT "
        "in the DB — read /var/log/archie_backup.log. "
    )


def _threshold_overrides(cur) -> dict:
    """Read platform_settings 'backup:freshness:<tier>' -> hours. Never raises.

    Settings being unreadable must not blind the watchdog, so any failure falls back to
    the code defaults rather than skipping the check.
    """
    out: dict = {}
    try:
        cur.execute("SELECT key, value FROM platform_settings WHERE key LIKE 'backup:freshness:%%'")
        for row in cur.fetchall() or []:
            key = row["key"] if isinstance(row, dict) else row[0]
            val = row["value"] if isinstance(row, dict) else row[1]
            try:
                out[str(key).rsplit(":", 1)[-1]] = float(val)
            except (TypeError, ValueError):
                continue
    except Exception as exc:
        logger.warning("backup_posture: threshold overrides unreadable (using defaults): %s", exc)
    return out


def check_backup_posture(
    stale_hours: float = PRIMARY_STALE_HOURS,
    offsite_stale_hours: dict | None = None,
):
    """Check primary-tier AND off-site tier backup health, and alert.

    Returns a dict; never raises. ``offsite_stale_hours`` overrides the per-tier limits
    (tests pass it directly; production reads platform_settings on top of the defaults).
    """
    result = {
        "checked": True,
        "alerted": [],
        "success_age_h": None,
        "recent_failures": 0,
        "tiers": {},
    }
    try:
        from services.telegram_service import send_system
    except Exception as exc:  # comms unavailable — never take the loop down with us
        logger.warning("backup_posture: telegram unavailable: %s", exc)
        return {"checked": False, "error": str(exc), "alerted": []}

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # ---- 1. FRESHNESS of the last SUCCESSFUL primary backup ------------------
            # status='success' is load-bearing: a FAILED backup also writes a tier='primary'
            # row, and measuring the newest row regardless of status is exactly the bug
            # fixed in #5013 — it certifies a restore point that does not exist.
            cur.execute(
                """
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(created_at))) / 3600.0 AS age_h
                FROM backup_log
                WHERE tier = 'primary' AND status = 'success'
                """
            )
            row = cur.fetchone()
            age_h = (row["age_h"] if isinstance(row, dict) else row[0]) if row else None
            result["success_age_h"] = round(float(age_h), 1) if age_h is not None else None

            if age_h is None or float(age_h) > stale_hours:
                send_system(
                    "Backup posture: no recent successful backup",
                    "Newest tier='primary' backup_log success is %s (limit %.0fh). "
                    "The restore point is stale — check Backup Manager and the nightly "
                    "backup_triage.sh. A failed run still writes a 'primary' row, so the "
                    "dashboard can look current while no usable backup exists."
                    % ("MISSING ENTIRELY" if age_h is None else "%.0fh old" % float(age_h), stale_hours),
                    cooldown_hours=12.0,
                )
                result["alerted"].append("primary_backup_stale")

            # ---- 2. ARE ATTEMPTS FAILING? -------------------------------------------
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM backup_log
                WHERE tier = 'primary'
                  AND status = ANY(%s)
                  AND created_at > NOW() - (%s * INTERVAL '1 hour')
                """,
                (list(_FAILURE_STATUSES), FAILURE_LOOKBACK_HOURS),
            )
            row = cur.fetchone()
            n = int((row["n"] if isinstance(row, dict) else row[0]) or 0) if row else 0
            result["recent_failures"] = n

            if n:
                send_system(
                    "Backup posture: backup attempts are failing",
                    "%d primary backup attempt(s) failed or completed partially in the last "
                    "%.0fh. Even if a later run succeeded, the unattended path is broken. "
                    "Check container memory — a full dump that OOMs dies part-written "
                    "(see task #5014)." % (n, FAILURE_LOOKBACK_HOURS),
                    cooldown_hours=6.0,
                )
                result["alerted"].append("primary_backup_failures")

            # ---- 3. OFF-SITE TIER FRESHNESS (#5094) ---------------------------------
            # Checks 1-2 only ever looked at tier='primary'. Google Drive stopped
            # receiving the database dump on 2026-06-29 and every off-site leg died on
            # 07-11, yet the local nightly kept succeeding — so this module reported
            # healthy for three weeks while the off-site restore path did not exist.
            limits = dict(OFFSITE_STALE_HOURS)
            if offsite_stale_hours is None:
                # Runtime overrides win over the code defaults, but only for tiers we
                # actually watch — a stray settings row must not invent a new tier.
                limits.update({t: h for t, h in _threshold_overrides(cur).items() if t in limits})
            else:
                limits = dict(offsite_stale_hours)

            if limits:
                cur.execute(
                    """
                    SELECT tier,
                           EXTRACT(EPOCH FROM (NOW() - MAX(created_at)
                               FILTER (WHERE status = 'success'))) / 3600.0 AS success_age_h,
                           COUNT(*) AS total_rows
                    FROM backup_log
                    WHERE tier = ANY(%s)
                    GROUP BY tier
                    """,
                    (list(limits),),
                )
                seen: dict = {}
                for row in cur.fetchall() or []:
                    tier = row["tier"] if isinstance(row, dict) else row[0]
                    age = row["success_age_h"] if isinstance(row, dict) else row[1]
                    total = row["total_rows"] if isinstance(row, dict) else row[2]
                    seen[tier] = (None if age is None else float(age), int(total or 0))

                # The recorded cause, per tier. #5619: this alert used to carry only
                # STATIC advice ("check the quota"), so on 2026-08-15 it sent an
                # investigation at quota for ~an hour while every failed gdrive row
                # already held `invalid_grant: Bad Request` — an expired OAuth token,
                # not a full Drive. The answer was one column away and nobody read it.
                # An alert that quotes the failure beats one that counts failures.
                last_errors: dict = {}
                cur.execute(
                    """
                    SELECT DISTINCT ON (tier) tier, error_message
                    FROM backup_log
                    WHERE tier = ANY(%s)
                      AND error_message IS NOT NULL
                      AND status IN ('failed', 'partial')
                    ORDER BY tier, created_at DESC
                    """,
                    (list(limits),),
                )
                for row in cur.fetchall() or []:
                    t = row["tier"] if isinstance(row, dict) else row[0]
                    msg = row["error_message"] if isinstance(row, dict) else row[1]
                    if msg:
                        last_errors[t] = short_cause(msg)

                for tier, limit_h in sorted(limits.items()):
                    age_h, total_rows = seen.get(tier, (None, 0))

                    # No rows at ALL = this tier is not configured on this install.
                    # Deliberately not an alert (a fresh deploy must not page), but it is
                    # reported as 'unknown' rather than omitted — a tier that can never
                    # alarm while looking absent is how #5092 hid for three weeks.
                    if total_rows == 0:
                        result["tiers"][tier] = {"status": "unknown", "age_h": None}
                        continue

                    fresh = age_h is not None and age_h <= limit_h
                    result["tiers"][tier] = {
                        "status": "ok" if fresh else "stale",
                        "age_h": None if age_h is None else round(age_h, 1),
                    }
                    if fresh:
                        continue

                    # The tier name is in the TITLE on purpose: send_system dedups on
                    # (title, source), so each tier keeps its own cooldown instead of one
                    # stale tier muting the alerts for all the others.
                    # Lead with the RECORDED cause when we have one — generic advice
                    # goes last, and only as a fallback (#5619).
                    _cause = cause_line(last_errors.get(tier))
                    send_system(
                        "Backup posture: off-site tier '%s' has no recent successful backup" % tier,
                        "Newest tier='%s' backup_log success is %s (limit %.0fh). %s"
                        "The PRIMARY "
                        "tier can be perfectly healthy while this off-site copy is dead — that "
                        "is how the Google Drive database backup went unnoticed for three weeks "
                        "(#5092). Check the tier-sync legs in scripts/backup/run_backup.sh (and "
                        "backup_triage.sh for 'dr'); for 'gdrive' also check the account storage "
                        "quota — a full Drive rejects large uploads while small files still fit."
                        % (
                            tier,
                            ("MISSING ENTIRELY (rows exist, none succeeded)" if age_h is None else "%.0fh old" % age_h),
                            limit_h,
                            _cause,
                        ),
                        cooldown_hours=12.0,
                    )
                    result["alerted"].append("offsite_%s_stale" % tier)

    except Exception as exc:
        # A watchdog that crashes is a watchdog that stops watching — and this whole module
        # exists because the previous one failed silently. Log loudly, return honestly.
        logger.error("backup_posture: check FAILED (backups are now unmonitored): %s", exc)
        result["checked"] = False
        result["error"] = str(exc)

    return result
