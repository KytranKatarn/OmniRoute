"""Planned maintenance windows — tell DR before you take the hub down.

WHY THIS EXISTS
On 2026-07-25 a PLANNED power-down (2x PSU adapter + GPU install) was read by
`dr-watchdog.timer` as a hub failure. It promoted boston-2 and blanket-flipped all
21 Beacon upstreams, taking ~20 healthy hub-only services offline. Nothing
malfunctioned: the quorum worked exactly as designed. The gap is that **no vantage
can distinguish "planned" from "dead"** — and the safety that would have prevented
it already existed (`/opt/archie-dr/.watchdog_disabled`); nobody set it, because it
is an undocumented dotfile on a remote host.

This module makes that impossible to forget, and — per the owner — makes it
automatic when WE are the cause: "especially if we call it from inside, it's not a
surprise." Restarts, migrations, power-downs and long restores all open a window.

DESIGN DECISIONS (owner, 2026-07-26)
- Default 90 minutes, auto-extending while work continues (`heartbeat`), because a
  hardware job routinely overruns 60 and a window that expires mid-job re-arms DR
  against a hub that is legitimately down.
- Early close: the WATCHDOG ends the snooze itself once the hub is healthy for
  K_UP consecutive cycles (see scripts/dr/watchdog/dr_watchdog.sh). We do not need
  the hub to be alive to end a window — which matters, because the hub being down
  is the whole premise.
- Degraded DR posture (today: boston-2 is a promoted fork with no replication)
  does NOT block a window. Suppressing a watchdog aimed at a dead replica is
  strictly safer than leaving it armed. We warn loudly and itemise.

⚠️ SNOOZE, NOT KILL SWITCH. `.snooze_until` auto-expires and can close early.
`.watchdog_disabled` never does — a forgotten one silently disarms DR forever,
which is exactly the state boston-2 has been in since 2026-07-25. `--indefinite`
is therefore opt-in and always reported by `status`.

⚠️ WRITING A FILE IS NOT PROOF IT IS HONOURED. `start` runs one real watchdog
cycle afterwards and asserts the log says `snoozed`/`disabled`. If it cannot
confirm suppression it reports NOT SAFE — the same discipline that caught the
loopback-probe and the 30s-window bugs.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Same host + key idiom as services/deploy_service.py — the id_ed25519
# bind-mounted into archie_platform/archie_scheduler at /root/.ssh/.
DR_HOST = os.getenv("DR_HOST", "root@100.64.0.10")
DR_KEY = os.getenv("REPAIR_BAY_VPS_KEY", "/root/.ssh/id_ed25519")
DR_DIR = os.getenv("DR_DIR", "/opt/archie-dr")

SNOOZE_FILE = f"{DR_DIR}/.snooze_until"
DISABLED_FLAG = f"{DR_DIR}/.watchdog_disabled"
WATCHDOG = f"{DR_DIR}/watchdog/dr_watchdog.sh"

DEFAULT_MINUTES = int(os.getenv("MAINTENANCE_DEFAULT_MINUTES", "90"))

_SSH_OPTS = [
    "-i",
    DR_KEY,
    "-o",
    "ConnectTimeout=15",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "LogLevel=ERROR",
]


def _ssh(remote_cmd: str, timeout: int = 30):
    """Run a command on the DR host. Returns (rc, combined_output)."""
    try:
        p = subprocess.run(
            ["ssh"] + _SSH_OPTS + [DR_HOST, remote_cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s"
    except Exception as e:  # pragma: no cover - ssh binary/key missing
        return 1, f"{type(e).__name__}: {e}"


def _now() -> int:
    return int(time.time())


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- posture ----
def _posture_warnings() -> list:
    """Itemised reasons DR cover is not what it looks like. Never raises."""
    warnings = []
    try:
        from services.dr_posture_monitor import check_dr_posture

        p = check_dr_posture() or {}
        if p.get("error"):
            warnings.append(f"DR posture check errored: {p['error']}")
        if p.get("slot_active") is False:
            warnings.append("replication slot INACTIVE — boston-2 is not streaming from the hub")
        lag = p.get("replay_lag_s")
        if isinstance(lag, (int, float)) and lag > 300:
            warnings.append(f"replica replay lag {int(lag)}s")
        age = p.get("dr_backup_age_h")
        if isinstance(age, (int, float)) and age > 48:
            warnings.append(f"DR cold backup is {int(age)}h old")
    except Exception as e:
        warnings.append(f"could not read DR posture ({type(e).__name__})")

    rc, out = _ssh(f"test -f {DR_DIR}/.failed_over && echo yes || echo no", timeout=20)
    if rc == 0 and "yes" in out:
        warnings.append(
            ".failed_over is SET on boston-2 — it is a promoted fork, not a replica. "
            "A failover cannot be relied on until scripts/dr/setup_replica.sh re-clones it."
        )
    rc, out = _ssh(f"test -f {DISABLED_FLAG} && cat {DISABLED_FLAG} || true", timeout=20)
    if rc == 0 and out.strip():
        warnings.append(f".watchdog_disabled already present: {out.strip()[:120]}")
    return warnings


# ------------------------------------------------------------------ start ----
def start_window(
    minutes: int = DEFAULT_MINUTES,
    reason: str = "",
    indefinite: bool = False,
    actor: str = "claude",
    announce: bool = True,
) -> dict:
    """Open a maintenance window. Returns an itemised, honest report.

    Never raises on a degraded DR posture — it warns. Suppressing a watchdog
    pointed at a dead replica is safer than leaving it armed (owner, 2026-07-26).
    """
    report = {
        "ok": False,
        "mode": "indefinite" if indefinite else "snooze",
        "minutes": None if indefinite else int(minutes),
        "reason": reason,
        "actor": actor,
        "warnings": _posture_warnings(),
        "suppression_verified": False,
        "safe_to_power_off": False,
    }

    if indefinite:
        note = f"{reason or 'planned maintenance'} | set_by={actor} | at={_iso(_now())}"
        rc, out = _ssh(f"printf '%s\\n' {_shq(note)} > {DISABLED_FLAG}")
        report["expires_at"] = None
    else:
        until = _now() + int(minutes) * 60
        rc, out = _ssh(f"echo {until} > {SNOOZE_FILE}")
        report["expires_at"] = _iso(until)

    if rc != 0:
        report["error"] = f"could not arm suppression on {DR_HOST}: {out.strip()[:200]}"
        return report

    # VERIFY — writing the file is not proof the watchdog honours it. Run one
    # real cycle and read what it decided. It exits at the suppression check, so
    # this cannot trigger anything.
    rc, out = _ssh(f"bash {WATCHDOG} 2>&1 | tail -5", timeout=90)
    decided = out.lower()
    report["watchdog_said"] = out.strip()[-300:]
    report["suppression_verified"] = ("snoozed" in decided) or ("disabled" in decided)

    if not report["suppression_verified"]:
        report["error"] = (
            "watchdog did NOT report itself suppressed after arming — do NOT power off. "
            "Check the timer and the flag path on the DR host."
        )
        return report

    report["ok"] = True
    report["safe_to_power_off"] = True

    if announce:
        _announce(
            "🛠️ Maintenance window OPEN",
            _summary_text(report),
        )
    return report


def heartbeat(minutes: int = DEFAULT_MINUTES) -> dict:
    """Re-stamp the expiry while work is still going (auto-extend).

    A window sized for the worst case still expires if you walk away; a window
    that only ever extends while someone is actively working cannot be forgotten.
    """
    until = _now() + int(minutes) * 60
    rc, out = _ssh(f"test -f {SNOOZE_FILE} && echo {until} > {SNOOZE_FILE} && echo extended || echo no_window")
    return {
        "ok": rc == 0 and "extended" in out,
        "expires_at": _iso(until) if "extended" in out else None,
        "detail": out.strip()[:200],
    }


# ----------------------------------------------------------------- status ----
def window_status() -> dict:
    """Live truth, including a HALF-APPLIED window (spec requirement)."""
    st = {"snooze_remaining_s": None, "indefinite": False, "failed_over": False}
    rc, out = _ssh(
        f"cat {SNOOZE_FILE} 2>/dev/null || echo none; echo '---'; "
        f"cat {DISABLED_FLAG} 2>/dev/null || echo none; echo '---'; "
        f"test -f {DR_DIR}/.failed_over && echo yes || echo no"
    )
    if rc != 0:
        return {"error": f"cannot reach {DR_HOST}: {out.strip()[:200]}", **st}

    parts = [p.strip() for p in out.split("---")]
    if parts and parts[0] not in ("none", ""):
        try:
            st["snooze_remaining_s"] = max(0, int(parts[0].splitlines()[-1]) - _now())
        except (ValueError, IndexError):
            st["snooze_remaining_s"] = None
    if len(parts) > 1 and parts[1] not in ("none", ""):
        st["indefinite"] = True
        st["indefinite_note"] = parts[1][:200]
    if len(parts) > 2:
        st["failed_over"] = "yes" in parts[2]

    st["open"] = bool(st["snooze_remaining_s"]) or st["indefinite"]
    st["warnings"] = _posture_warnings()
    return st


# -------------------------------------------------------------------- end ----
def end_window(actor: str = "claude", announce: bool = True) -> dict:
    """Close the window and state plainly whether DR cover is genuinely back.

    Idempotent — safe when no window is open.
    """
    rc, out = _ssh(f"rm -f {SNOOZE_FILE} {DR_DIR}/.snooze_up_streak {DISABLED_FLAG} && echo cleared")
    report = {"ok": rc == 0 and "cleared" in out, "actor": actor, "detail": out.strip()[:200]}

    rc, out = _ssh(f"bash {WATCHDOG} 2>&1 | tail -5", timeout=90)
    report["watchdog_said"] = out.strip()[-300:]
    low = out.lower()
    report["watchdog_scanning"] = ("snoozed" not in low) and ("disabled" not in low)

    # Be honest: clearing our flags does NOT make a promoted fork a replica.
    report["warnings"] = _posture_warnings()
    report["dr_cover_restored"] = report["watchdog_scanning"] and not report["warnings"]
    if not report["dr_cover_restored"]:
        report["note"] = (
            "watchdog is scanning again, but DR cover is NOT fully restored — see warnings. "
            "A promoted fork needs scripts/dr/setup_replica.sh before a failover means anything."
        )
    if announce:
        _announce("✅ Maintenance window CLOSED", _summary_text(report))
    return report


# --------------------------------------------------- internal auto-announce --
@contextmanager
def maintenance_window(reason: str, minutes: int = DEFAULT_MINUTES, actor: str = "internal"):
    """Wrap any hub-disrupting operation so DR is never surprised by our own work.

    Owner: "especially if we call it from inside it's not a surprise."
    Intended callers: platform/scheduler restarts, schema migrations, host
    power-down/reboot, long backups and restores.

    FAIL-OPEN: if the window cannot be opened (DR host unreachable), the wrapped
    work still runs. Blocking a deploy because a REMOTE host is unreachable would
    be a worse failure than the one this prevents — but it is logged loudly.
    """
    opened = False
    try:
        rep = start_window(minutes=minutes, reason=reason, actor=actor)
        opened = bool(rep.get("ok"))
        if not opened:
            logger.warning(
                "maintenance_window: could NOT arm DR suppression for %r (%s) — proceeding anyway",
                reason,
                rep.get("error") or rep.get("warnings"),
            )
    except Exception as e:  # pragma: no cover
        logger.warning("maintenance_window: start failed for %r: %s", reason, e)

    try:
        yield
    finally:
        if opened:
            try:
                end_window(actor=actor)
            except Exception as e:  # pragma: no cover
                logger.error(
                    "maintenance_window: FAILED TO CLOSE window for %r: %s — DR may still be "
                    "suppressed; the snooze will auto-expire, but check `status`.",
                    reason,
                    e,
                )


# ---------------------------------------------------------------- helpers ----
def _shq(s: str) -> str:
    """Single-quote for a remote shell."""
    return "'" + str(s).replace("'", "'\\''") + "'"


def _summary_text(report: dict) -> str:
    bits = []
    if report.get("reason"):
        bits.append(f"reason: {report['reason']}")
    if report.get("expires_at"):
        bits.append(f"expires: {report['expires_at']}")
    if report.get("mode") == "indefinite":
        bits.append("mode: INDEFINITE (does not auto-expire)")
    if report.get("watchdog_scanning") is True:
        bits.append("watchdog: scanning")
    if report.get("suppression_verified"):
        bits.append("watchdog: suppression VERIFIED")
    for w in report.get("warnings") or []:
        bits.append(f"⚠️ {w}")
    return " | ".join(bits) or "no detail"


def _announce(title: str, message: str) -> None:
    try:
        from services.telegram_service import send_system

        send_system(title, message)
    except Exception as e:  # pragma: no cover - comms must never break the window
        logger.warning("maintenance_window: announce failed: %s", e)
