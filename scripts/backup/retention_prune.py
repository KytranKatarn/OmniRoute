#!/usr/bin/env python3
"""scripts/backup/retention_prune.py

Enforces per-tier retention from a declarative config.

Monotonic — never deletes a backup that is the most recent of its kind at
that tier. Retention is expressed per-component, per-tier as a tuple of
(daily_keep, weekly_keep, monthly_keep) where:
- daily:   any run, newest first
- weekly:  runs that fall on Sunday
- monthly: runs that fall on day-of-month ≤ 3

Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md §6
Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 17
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# (daily, weekly, monthly) keep counts per (component, tier).
# Keys are folder names under a run_dir (which tier_sync scripts mirror to tiers).
RETENTION = {
    "database": {"primary": (30, 12, 6), "usb": (14, 4, 0), "gdrive": (0, 4, 6), "vps": (7, 0, 0)},
    "code": {"primary": (14, 8, 0), "usb": (7, 4, 0), "gdrive": (0, 4, 0), "vps": (0, 0, 0)},
    "gitbundles": {"primary": (14, 0, 12), "usb": (7, 4, 0), "gdrive": (0, 4, 6), "vps": (7, 0, 0)},
    "config": {"primary": (14, 0, 12), "usb": (7, 0, 0), "gdrive": (0, 0, 12), "vps": (7, 0, 0)},
    "volumes": {"primary": (14, 4, 0), "usb": (0, 4, 0), "gdrive": (0, 0, 0), "vps": (0, 0, 0)},
    "convlogs": {"primary": (0, 8, 0), "usb": (0, 0, 0), "gdrive": (0, 0, 0), "vps": (0, 0, 0)},
    "kb_export": {"primary": (0, 12, 6), "usb": (0, 0, 0), "gdrive": (0, 0, 6), "vps": (0, 0, 0)},
    "vps_pull": {"primary": (0, 8, 3), "usb": (0, 0, 0), "gdrive": (0, 0, 0), "vps": (0, 0, 0)},
    "monthly_full": {"primary": (0, 0, 6), "usb": (0, 0, 0), "gdrive": (0, 0, 6), "vps": (0, 0, 0)},
    "pre-change": {"primary": (20, 0, 0), "usb": (0, 0, 0), "gdrive": (0, 0, 0), "vps": (0, 0, 0)},
}

PRIMARY_ROOT = Path(os.environ.get("BACKUP_ROOT", "/mnt/data2/backups"))
USB_ROOT = Path(os.environ.get("BACKUP_USB", "/mnt/external-backup"))

DATE_RE = re.compile(r"^(\d{8})_")

# --dry-run: report what WOULD be pruned without deleting anything (DR-critical safety).
DRY_RUN = "--dry-run" in sys.argv

# Run-dir housekeeping files (written per-backup by write_backup_metadata.sh, #4049) that must
# NOT keep an otherwise-pruned run dir alive — treat a dir with only these left as empty.
HOUSEKEEPING = {"metadata.json", "rollback.sh"}


def parse_ts(name: str):
    m = DATE_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d")
    except ValueError:
        return None


def classify(date: datetime) -> set[str]:
    tags = {"daily"}
    if date.weekday() == 6:  # Sunday
        tags.add("weekly")
    if date.day <= 3:
        tags.add("monthly")
    return tags


def prune_dir(root: Path, component: str, tier: str) -> int:
    keep_d, keep_w, keep_m = RETENTION.get(component, {}).get(tier, (0, 0, 0))
    if not root.is_dir():
        return 0

    runs = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        ts = parse_ts(child.name)
        if not ts:
            continue
        comp_path = child / component
        if not comp_path.exists():
            continue
        runs.append((ts, child, comp_path))

    if not runs:
        return 0

    kept_d = kept_w = kept_m = 0
    deleted = 0
    for ts, run_dir, comp_path in runs:
        tags = classify(ts)
        keep = False
        if "monthly" in tags and kept_m < keep_m:
            kept_m += 1
            keep = True
        elif "weekly" in tags and kept_w < keep_w:
            kept_w += 1
            keep = True
        elif kept_d < keep_d:
            kept_d += 1
            keep = True
        if not keep:
            if DRY_RUN:
                print(f"[dry-run] would remove {comp_path}")
                deleted += 1
                continue
            print(f"prune: removing {comp_path}")
            try:
                shutil.rmtree(comp_path)
                deleted += 1
                # Remove the run dir if nothing but housekeeping files (#4049) remains.
                try:
                    leftover = {p.name for p in run_dir.iterdir()}
                    if not leftover or leftover <= HOUSEKEEPING:
                        shutil.rmtree(run_dir)
                except OSError:
                    pass
            except Exception as e:
                print(f"failed to remove {comp_path}: {e}", file=sys.stderr)

    return deleted


def prune_usb_via_container(component: str) -> int:
    """USB is root-owned; delegate to archie_platform container."""
    keep_d, keep_w, keep_m = RETENTION.get(component, {}).get("usb", (0, 0, 0))
    if keep_d == 0 and keep_w == 0 and keep_m == 0:
        return 0

    # Script-in-a-string approach — keeps this function self-contained.
    script = f"""
set -e
cd /mnt/external-backup 2>/dev/null || exit 0
DAILY={keep_d}; WEEKLY={keep_w}; MONTHLY={keep_m}
kept_d=0; kept_w=0; kept_m=0
deleted=0
for d in $(ls -r | grep -E '^[0-9]{{8}}_'); do
    date_part=${{d:0:8}}
    dow=$(date -d "${{date_part:0:4}}-${{date_part:4:2}}-${{date_part:6:2}}" +%u 2>/dev/null || echo 0)
    day=$((10#${{date_part:6:2}}))
    comp_path="$d/{component}"
    [ ! -e "$comp_path" ] && continue
    keep=0
    if [ "$day" -le 3 ] && [ "$kept_m" -lt "$MONTHLY" ]; then kept_m=$((kept_m+1)); keep=1
    elif [ "$dow" -eq 7 ] && [ "$kept_w" -lt "$WEEKLY" ]; then kept_w=$((kept_w+1)); keep=1
    elif [ "$kept_d" -lt "$DAILY" ]; then kept_d=$((kept_d+1)); keep=1
    fi
    if [ "$keep" -eq 0 ]; then
        rm -rf "$comp_path"
        deleted=$((deleted+1))
        [ -z "$(ls -A "$d" 2>/dev/null)" ] && rmdir "$d" 2>/dev/null || true
    fi
done
echo $deleted
"""
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "bash", "-c", script],
        capture_output=True,
        text=True,
    )
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def main() -> None:
    total_deleted = 0
    for component in RETENTION.keys():
        total_deleted += prune_dir(PRIMARY_ROOT, component, "primary")
        if not DRY_RUN:
            total_deleted += prune_usb_via_container(component)

    if DRY_RUN:
        print(f"[dry-run] retention prune: {total_deleted} items WOULD be removed (primary tier only)")
        return

    # Record the run: backup_log row + system_config retention_last_run/deleted_count so the
    # Backup Manager UI reflects THIS canonical engine (it was stale because the old module job
    # was the only writer — #4051).
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "archie_database",
            "psql",
            "-U",
            "archie",
            "-d",
            "archie",
            "-c",
            f"INSERT INTO backup_log (component, tier, status, notes, created_at) "
            f"VALUES ('retention', 'primary', 'prune', '{total_deleted} deleted', NOW());"
            f"UPDATE system_config SET value = NOW()::text WHERE key = 'retention_last_run';"
            f"UPDATE system_config SET value = '{total_deleted}' WHERE key = 'retention_last_deleted_count';",
        ],
        check=False,
        capture_output=True,
    )
    print(f"retention prune: {total_deleted} items removed")


if __name__ == "__main__":
    main()
