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

ACKNOWLEDGED DISKS (task #6803): a KNOWN failing disk (sdb awaits a hardware swap) re-paged as CRITICAL every cooldown for weeks,
which is how the Telegram channel got muted, and a muted channel also hides backup / DR alerts. `--ack /dev/sdX` records the disk's
CURRENT counters as a baseline (keyed by SERIAL, which survives device renames). An acknowledged disk then pages only when
  - a counter rises >=25% AND by >=25 units over its baseline (or a counter that was 0 becomes >0), or
  - overall-health flips to FAILED, or the disk becomes unreadable (an unreadable drive is never a pass),
and after a worsening page the baseline moves up, so only the NEXT band pages again. Otherwise it stays silent except for ONE low-key
weekly reminder, so an acknowledgement cannot be forgotten. `--unack /dev/sdX` removes it; `--list-acks` shows them.
Acknowledging is the OWNER's decision: nothing here acknowledges a disk by itself.

KERNEL I/O ERRORS (task #6803, ported from the host-only /usr/local/bin/smart_watch.py): SMART counters can hold steady while the read
path is actively failing, so the kernel log is checked too: "medium error" / "unrecovered read error" / "I/O error" lines per disk in
the last hour. That count is ROLLING, so a still-failing disk reports non-zero on every run; alerting on presence would re-fire hourly
forever, hence only a RISE pages (vs the previous run for an unacknowledged disk, vs the acknowledged baseline band for an acknowledged one).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

SMARTCTL = "/usr/sbin/smartctl"
PLATFORM_CONTAINER = "archie_platform"

# Attribute IDs (ATA SMART)
ATTR_REALLOCATED = 5
ATTR_PENDING = 197
ATTR_OFFLINE_UNC = 198
ATTR_UDMA_CRC = 199

# --- acknowledged-disk policy (#6803) ---
ACK_PATH = os.environ.get("SMART_ACK_PATH", "/var/lib/smart_posture_ack.json")
ESCALATION_RATIO = 1.25  # a counter must grow by >=25% over its acknowledged baseline...
ESCALATION_MIN_STEP = 25  # ...AND by at least this many units, so jitter on a small counter never pages
REMINDER_DAYS = 7
STATE_PATH = os.environ.get("SMART_STATE_PATH", "/var/lib/smart_posture_state.json")
_KERNEL_ERR_RE = re.compile(r"medium error|unrecovered read error|I/O error", re.I)
_KERNEL_DEV_RE = re.compile(
    r"\b(sd[a-z]+)\d*\b"
)  # \d*: errors are often logged against a PARTITION (sdb1) but belong to the disk (sdb)


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


def counters_from_attrs(attrs, kerr=0):
    """The counters the policy tracks, as a plain dict (kerr = kernel I/O errors in the last hour)."""
    return {
        "realloc": int(attrs.get(ATTR_REALLOCATED, 0) or 0),
        "pending": int(attrs.get(ATTR_PENDING, 0) or 0),
        "offline": int(attrs.get(ATTR_OFFLINE_UNC, 0) or 0),
        "crc": int(attrs.get(ATTR_UDMA_CRC, 0) or 0),
        "kerr": int(kerr or 0),
    }


def worsened(baseline, counters, health_passed):
    """Reasons an ACKNOWLEDGED disk is worse than when it was acknowledged ([] = same band)."""
    reasons = []
    if health_passed is False and not baseline.get("health_failed"):
        reasons.append("SMART overall-health self-assessment is now FAILED")
    base_counters = baseline.get("counters", {})
    for key in ("realloc", "pending", "offline", "crc", "kerr"):
        base = int(base_counters.get(key, 0) or 0)
        cur = int(counters.get(key, 0) or 0)
        if cur <= base:
            continue
        if base == 0 or (cur >= base * ESCALATION_RATIO and cur - base >= ESCALATION_MIN_STEP):
            reasons.append(f"{key} {base} -> {cur}")
    return reasons


def decide(ack, counters, health_passed, now):
    """→ ('page'|'worsened'|'remind'|'suppress', reasons). Pure.

    No acknowledgement → 'page' (the original behaviour). Unreadable disks never reach this function's suppress branch: the caller
    only consults it for readable disks.
    """
    if not ack:
        return "page", []
    reasons = worsened(ack, counters, health_passed)
    if reasons:
        return "worsened", reasons
    last = float(ack.get("last_reminder") or ack.get("acked_at") or 0)
    if now - last >= REMINDER_DAYS * 86400:
        return "remind", []
    return "suppress", []


def load_acks(path=None):
    """{serial: ack}. Missing file → {}. A corrupt file is reported LOUDLY and treated as no acks (fail OPEN: page rather than mute)."""
    path = path or ACK_PATH
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(
            f"smart_posture_monitor: ACK FILE UNREADABLE ({path}: {exc}) - paging as if nothing were acknowledged",
            file=sys.stderr,
        )
        return {}


def save_acks(acks, path=None):
    path = path or ACK_PATH
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(acks, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception as exc:  # noqa: BLE001 — a broken probe must report unknown, not crash the sweep
        return -1, str(exc)


def parse_kernel_errors(text):
    """{'sdb': n, ...}: kernel medium/IO error lines per disk in the given journal text. Pure."""
    counts = {}
    for line in (text or "").splitlines():
        if _KERNEL_ERR_RE.search(line):
            m = _KERNEL_DEV_RE.search(line)
            if m:
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def kernel_errors():
    """Per-disk kernel I/O error count over the last hour. Any failure to read the journal → {} (and loud on stderr): an unreadable
    journal must not look like a clean disk, but it also must not take down the SMART sweep."""
    rc, out = _run(["journalctl", "-k", "--since", "-1 hour", "--no-pager"], timeout=60)
    if rc != 0:
        print(
            f"smart_posture_monitor: kernel journal unreadable (rc={rc}) - kernel I/O errors NOT checked this run",
            file=sys.stderr,
        )
        return {}
    return parse_kernel_errors(out)


def load_state(path=None):
    path = path or STATE_PATH
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(
            f"smart_posture_monitor: STATE FILE UNREADABLE ({path}: {exc}) - kernel-error rise cannot be judged this run",
            file=sys.stderr,
        )
        return {}


def save_state(state, path=None):
    path = path or STATE_PATH
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


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


def main(scan=None, read=None, push=None, ack_path=None, now=None, kernel=None, state_path=None):
    scan = scan or scan_disks
    read = read or read_disk
    push = push or push_alert
    now = time.time() if now is None else now
    disks = scan()
    if not disks:
        # No enumerable disks is itself an unknown, never a silent pass.
        push(
            "SMART monitor: no disks enumerable",
            "smartctl --scan-open returned nothing — the monitor cannot see any drive. " "Unmonitored is not healthy.",
            "warning",
            12,
        )
        print("no disks enumerable")
        return
    acks = load_acks(ack_path)
    kerr_now = (kernel or kernel_errors)()
    prev_state = load_state(state_path)
    new_state = {}
    dirty = False
    for dev in disks:
        health, attrs, model, serial = read(dev)
        findings = evaluate_disk(health, attrs)
        unreadable = health is None and not attrs
        short = os.path.basename(dev)
        kerr = int(kerr_now.get(short, 0) or 0)
        prev_kerr = int((prev_state.get(short) or {}).get("kerr", 0) or 0)
        new_state[short] = {"kerr": kerr}
        ack = acks.get(serial) if serial and not unreadable else None
        action, why = decide(ack, counters_from_attrs(attrs, kerr), health, now)
        # Kernel I/O errors: an unacknowledged disk pages on a RISE vs the previous run; an acknowledged one only via its band (in `why`).
        if kerr and (
            (action == "page" and kerr > prev_kerr)
            or (action == "worsened" and any(w.startswith("kerr ") for w in why))
        ):
            findings.append(
                (
                    "kernel",
                    f"kernel medium/I-O errors in the last hour: {prev_kerr} -> {kerr} (the read path is failing now)",
                )
            )
        if action == "worsened" and not findings:
            findings.append(("critical", "; ".join(why)))
        if action == "suppress":
            if findings:
                print(f"{dev}: acknowledged ({'; '.join(r for _, r in findings)}) - suppressed")
            else:
                print(f"{dev}: healthy")
            continue
        if action == "remind":
            c = counters_from_attrs(attrs)
            title = f"SMART ACKNOWLEDGED: {dev} ({model or 'unknown model'} {serial or ''})".strip()
            msg = (
                f"Still acknowledged and unchanged: pending {c['pending']}, uncorrectable {c['offline']}, reallocated {c['realloc']}, "
                f"CRC {c['crc']}. Acknowledged {time.strftime('%Y-%m-%d', time.gmtime(ack.get('acked_at', now)))}"
                f"{' - ' + ack['note'] if ack.get('note') else ''}. Weekly reminder only; it pages again if the disk worsens."
            )
            push(title, msg, "warning", 24)
            ack["last_reminder"] = now
            dirty = True
            print(f"{dev}: acknowledged - weekly reminder sent")
            continue
        for level, reason in findings:
            sev = "critical" if level in ("critical", "kernel") else "warning"
            if action == "worsened":
                reason = f"WORSENED since acknowledgement ({'; '.join(why)}). {reason}"
            # The kernel finding gets its OWN title: send_system dedups on (title, source), so sharing the sector finding's title would
            # silently drop it behind that alert.
            label = "KERNEL I/O" if level == "kernel" else level.upper()
            title = f"SMART {label}: {dev} ({model or 'unknown model'} {serial or ''})".strip()
            push(title, reason, sev, 6 if level == "critical" else 12)
            print(f"{dev}: {level} - {reason}")
        if action == "worsened":
            # Move the baseline up so only the NEXT band pages, not every cooldown.
            ack["counters"] = counters_from_attrs(attrs, kerr)
            ack["health_failed"] = health is False
            ack["last_reminder"] = now
            dirty = True
        if not findings:
            print(f"{dev}: healthy")
    try:
        save_state(new_state, state_path)
    except Exception as exc:  # noqa: BLE001
        print(
            f"smart_posture_monitor: could not save state ({exc}) - a still-failing disk may re-page next run",
            file=sys.stderr,
        )
    if dirty:
        try:
            save_acks(acks, ack_path)
        except Exception as exc:  # noqa: BLE001
            print(
                f"smart_posture_monitor: could not save ack state ({exc}) - the next run may repeat a page",
                file=sys.stderr,
            )


def cmd_ack(dev, note="", ack_path=None, read=None, now=None, kernel=None):
    read = read or read_disk
    health, attrs, model, serial = read(dev)
    if not serial:
        print(f"cannot acknowledge {dev}: no serial number readable (acks are keyed by serial)", file=sys.stderr)
        return 1
    if health is None and not attrs:
        print(
            f"cannot acknowledge {dev}: SMART data unreadable - an unreadable drive is never acknowledged",
            file=sys.stderr,
        )
        return 1
    now = time.time() if now is None else now
    acks = load_acks(ack_path)
    acks[serial] = {
        "dev": dev,
        "model": model,
        "counters": counters_from_attrs(attrs, (kernel or kernel_errors)().get(os.path.basename(dev), 0)),
        "health_failed": health is False,
        "acked_at": now,
        "last_reminder": now,
        "note": note,
    }
    save_acks(acks, ack_path)
    print(f"acknowledged {dev} ({model} {serial}): baseline {acks[serial]['counters']}")
    return 0


def cmd_unack(dev, ack_path=None, read=None):
    read = read or read_disk
    _, _, _, serial = read(dev)
    acks = load_acks(ack_path)
    if serial in acks:
        del acks[serial]
        save_acks(acks, ack_path)
        print(f"{dev} ({serial}) is no longer acknowledged")
        return 0
    print(f"{dev} ({serial}) was not acknowledged")
    return 1


def cmd_list(ack_path=None):
    acks = load_acks(ack_path)
    if not acks:
        print("no acknowledged disks")
    for serial, a in sorted(acks.items()):
        print(f"{serial}: {a.get('dev')} {a.get('model')} baseline={a.get('counters')} note={a.get('note', '')!r}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="SMART posture monitor (hourly cron); --ack/--unack/--list-acks manage acknowledged disks"
    )
    ap.add_argument(
        "--ack",
        metavar="DEV",
        help="acknowledge a known-failing disk at its current counters (owner decision; needs root)",
    )
    ap.add_argument("--note", default="", help="why (stored with --ack)")
    ap.add_argument("--unack", metavar="DEV")
    ap.add_argument("--list-acks", action="store_true")
    args = ap.parse_args()
    if args.ack:
        sys.exit(cmd_ack(args.ack, args.note))
    if args.unack:
        sys.exit(cmd_unack(args.unack))
    if args.list_acks:
        sys.exit(cmd_list())
    main()
