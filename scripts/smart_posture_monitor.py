#!/usr/bin/env python3
"""SMART posture monitor — hourly host cron, pushes disk-health ALERTS (#5438).

WHY THIS EXISTS: the SMART data was already collected perfectly (host_monitor
get_smart_details) and rendered perfectly (KSO Hardware tab) — and pushed
NOWHERE. /dev/sdb sat at 1,736→1,760 uncorrectable sectors "rendered correctly
in a tab nobody had open" for weeks. The inverse of the #2366 defect: here the
monitor works and is simply silent.

DESIGN (mirrors services/backup_posture_monitor.py — deterministic, no LLM):
  - Runs ON THE HOST (smartctl needs the block devices; containers can't see
    them) via /etc/cron.d/archie-smart-monitor, hourly.
  - Alerts route through `docker exec archie_platform … telegram_service
    .send_system` — NOT an HTTP call to 192.168.1.200:3000, which the
    userland-proxy:false hairpin breaks from the host itself (KB #275737).
    send_system dedups on (title, source) with a cooldown, so a persisting
    condition re-alerts on the cadence below instead of flooding.
  - The DEVICE NAME + serial is in the alert TITLE: send_system dedups on
    title, so without it one bad disk would mute every other one (the #5094
    per-tier backup-freshness trap).
  - A disk with unreadable SMART data reports `unknown` and ALERTS at warning
    level — an unreadable drive must never render as a pass.

SEVERITY MODEL (failure MODE over raw counts — task #5438 items 2+3):
  - Current_Pending_Sector (197) / Offline_Uncorrectable (198) > 0 with
    Reallocated (5) == 0  → CRITICAL: the drive is NOT remapping. That is sdb's
    signature (1,760 pending / 0 realloc) — it is failing, not aging.
  - Reallocated (5) > 0 with pending == 0 → WARNING: the drive is doing its
    job (sdc: 152 realloc). Watch the trend, plan replacement.
  - Both > 0 → CRITICAL (remapping AND falling behind).
  - UDMA_CRC_Error_Count (199) > 0 → separate WARNING naming the CABLE: it is
    a SATA link fault with a different remedy (reseat/replace cable), not
    platter damage.
  - smartctl overall-health FAILED → CRITICAL regardless of attributes.
"""

import json
import subprocess
import sys

SMARTCTL = "/usr/sbin/smartctl"
PLATFORM_CONTAINER = "archie_platform"

# Attribute IDs (ATA SMART)
ATTR_REALLOCATED = 5
ATTR_PENDING = 197
ATTR_OFFLINE_UNC = 198
ATTR_UDMA_CRC = 199


def evaluate_disk(health_passed, attrs):
    """Pure decision function → list of (level, reason) findings.

    ``health_passed``: True/False/None (None = unreadable).
    ``attrs``: {attr_id: raw_value} — missing ids treated as 0; an entirely
    empty dict with health None means the disk was unreadable → unknown.
    Levels: 'critical' | 'warning' | 'unknown'.
    """
    findings = []
    if health_passed is None and not attrs:
        return [("unknown", "SMART data unreadable — an unreadable drive is never a pass")]

    realloc = int(attrs.get(ATTR_REALLOCATED, 0) or 0)
    pending = int(attrs.get(ATTR_PENDING, 0) or 0)
    offline = int(attrs.get(ATTR_OFFLINE_UNC, 0) or 0)
    crc = int(attrs.get(ATTR_UDMA_CRC, 0) or 0)
    unreadable_sectors = max(pending, offline)

    if health_passed is False:
        findings.append(("critical", "SMART overall-health self-assessment: FAILED"))

    if unreadable_sectors > 0 and realloc == 0:
        findings.append(
            (
                "critical",
                f"{pending} pending / {offline} offline-uncorrectable sectors with ZERO reallocated — "
                f"the drive is NOT remapping (failing, not aging)",
            )
        )
    elif unreadable_sectors > 0 and realloc > 0:
        findings.append(
            (
                "critical",
                f"{pending} pending / {offline} offline-uncorrectable AND {realloc} reallocated — "
                f"remapping and still falling behind",
            )
        )
    elif realloc > 0:
        findings.append(
            (
                "warning",
                f"{realloc} reallocated sectors, no pending — the drive is remapping successfully; "
                f"watch the trend and plan replacement",
            )
        )

    if crc > 0:
        findings.append(
            (
                "warning",
                f"UDMA_CRC_Error_Count={crc} — SATA link fault (reseat/replace the CABLE, not the drive)",
            )
        )
    return findings


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception as exc:  # noqa: BLE001 — a broken probe must report unknown, not crash the sweep
        return -1, str(exc)


def scan_disks():
    rc, out = _run(["sudo", "-n", SMARTCTL, "--scan-open", "-j"])
    try:
        return [d["name"] for d in json.loads(out).get("devices", [])]
    except Exception:
        return []


def read_disk(dev):
    """→ (health_passed, attrs, model, serial). All-None/empty on unreadable."""
    rc, out = _run(["sudo", "-n", SMARTCTL, "-a", "-j", dev])
    try:
        data = json.loads(out)
    except Exception:
        return None, {}, "", ""
    health = data.get("smart_status", {}).get("passed")
    attrs = {}
    for a in (data.get("ata_smart_attributes", {}) or {}).get("table", []) or []:
        try:
            attrs[int(a.get("id"))] = int((a.get("raw") or {}).get("value", 0))
        except Exception:
            continue
    model = data.get("model_name") or ""
    serial = data.get("serial_number") or ""
    return health, attrs, model, serial


def push_alert(title, message, severity, cooldown_hours, retries=2):
    """send_system inside the platform container (hairpin-safe path).

    send_system's comms hop (archie_comms:3002) intermittently read-times-out
    at 5s — measured 2026-08-17: 2 of 4 first-run pushes were lost to it. The
    shim therefore prints send_system's RESULT, and this side retries a failed
    push (cooldown dedup makes retries of a delivered alert harmless). A push
    that still fails is reported loudly on stderr so cron surfaces it — a
    dropped disk alert must never be silent (that is the whole point of #5438).
    """
    payload = json.dumps({"title": title, "message": message, "severity": severity, "cooldown_hours": cooldown_hours})
    shim = (
        "import sys, json; sys.path.insert(0, '/app');"
        "from services.telegram_service import send_system;"
        "p = json.load(sys.stdin);"
        "r = send_system(p['title'], p['message'], severity=p['severity'], cooldown_hours=p['cooldown_hours']);"
        "print(json.dumps(r))"
    )
    import time

    for attempt in range(1, retries + 2):
        try:
            proc = subprocess.run(
                ["docker", "exec", "-i", PLATFORM_CONTAINER, "python3", "-c", shim],
                input=payload,
                text=True,
                timeout=60,
                capture_output=True,
            )
            result = {}
            for line in reversed((proc.stdout or "").strip().splitlines()):
                try:
                    result = json.loads(line)
                    break
                except Exception:
                    continue
            if result.get("success") or result.get("deduped") or result.get("suppressed"):
                return True
            last_err = result.get("error") or f"exit={proc.returncode} stderr={(proc.stderr or '')[-120:]}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        if attempt <= retries:
            time.sleep(5)
    print(
        f"smart_posture_monitor: ALERT PUSH FAILED after {retries + 1} attempts for {title!r}: {last_err}",
        file=sys.stderr,
    )
    return False


def main():
    disks = scan_disks()
    if not disks:
        # No enumerable disks is itself an unknown, never a silent pass.
        push_alert(
            "SMART monitor: no disks enumerable",
            "smartctl --scan-open returned nothing — the monitor cannot see any drive. " "Unmonitored is not healthy.",
            "warning",
            12,
        )
        print("no disks enumerable")
        return
    for dev in disks:
        health, attrs, model, serial = read_disk(dev)
        findings = evaluate_disk(health, attrs)
        for level, reason in findings:
            sev = "critical" if level == "critical" else "warning"
            title = f"SMART {level.upper()}: {dev} ({model or 'unknown model'} {serial or ''})".strip()
            push_alert(title, reason, sev, 6 if level == "critical" else 12)
            print(f"{dev}: {level} — {reason}")
        if not findings:
            print(f"{dev}: healthy")


if __name__ == "__main__":
    main()
