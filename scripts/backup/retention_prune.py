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

import json
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
    # gdrive is a 15 GB FREE-TIER account — a 1.5 GB DB dump + a 0.9 GB code tar per
    # run means the old (0,4,6)=10 DB dumps alone would exceed the whole quota. Keep the
    # off-site Drive copy deliberately shallow (USB + boston-2 DR hold the deep history),
    # but the daily_keep>=1 is CRITICAL: off-site is a disaster-recovery tier, so the
    # NEWEST dump must always survive the nightly prune (keep_d=0 would trash tonight's
    # upload same night, leaving Drive only as fresh as the last Sunday). database keeps
    # the last 2 dailies + 1 weekly + 1 monthly (~4 dumps, ~6 GB); code lives in git so
    # off-site keeps just the last 2 (~1.6 GB). #5092.
    "database": {"primary": (30, 12, 6), "usb": (14, 4, 0), "gdrive": (2, 1, 1)},
    "code": {"primary": (14, 8, 0), "usb": (7, 4, 0), "gdrive": (2, 0, 0)},
    "gitbundles": {"primary": (14, 0, 12), "usb": (7, 4, 0), "gdrive": (0, 4, 6)},
    "config": {"primary": (14, 0, 12), "usb": (7, 0, 0), "gdrive": (0, 0, 12)},
    "volumes": {"primary": (14, 4, 0), "usb": (0, 4, 0), "gdrive": (0, 0, 0)},
    "convlogs": {"primary": (0, 8, 0), "usb": (0, 0, 0), "gdrive": (0, 0, 0)},
    "kb_export": {"primary": (0, 12, 6), "usb": (0, 0, 0), "gdrive": (0, 0, 6)},
    "vps_pull": {"primary": (0, 8, 3), "usb": (0, 0, 0), "gdrive": (0, 0, 0)},
    "monthly_full": {"primary": (0, 0, 6), "usb": (0, 0, 0), "gdrive": (0, 0, 6)},
    "pre-change": {"primary": (20, 0, 0), "usb": (0, 0, 0), "gdrive": (0, 0, 0)},
}

PRIMARY_ROOT = Path(os.environ.get("BACKUP_ROOT", "/mnt/data2/backups"))
USB_ROOT = Path(os.environ.get("BACKUP_USB", "/mnt/external-backup"))

# USB whole-dir age cap (see prune_usb_stale_dirs): the USB tier keeps <=4 weekly (~28d) + 0
# monthly for every component, so nothing the recurring retention keeps is older than ~35d.
# One-off / manual / test / Daily_Scheduled backups use a different internal layout that the
# per-component prune never matches, so they accumulate forever — sweep any older whole dir.
USB_MAX_AGE_DAYS = int(os.environ.get("BACKUP_USB_MAX_AGE_DAYS", "45"))

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


def prune_usb_via_container(component: str, dry_run: bool) -> int:
    """Per-component keep-newest-N on the USB tier (root-owned -> delegate to archie_platform).
    Honours dry_run: prints WOULD-PRUNE lines and deletes nothing."""
    keep_d, keep_w, keep_m = RETENTION.get(component, {}).get("usb", (0, 0, 0))
    if keep_d == 0 and keep_w == 0 and keep_m == 0:
        return 0

    dry = "1" if dry_run else "0"
    # Script-in-a-string approach — keeps this function self-contained.
    script = f"""
set -e
cd /mnt/external-backup 2>/dev/null || exit 0
DAILY={keep_d}; WEEKLY={keep_w}; MONTHLY={keep_m}; DRY={dry}
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
        if [ "$DRY" = "1" ]; then
            echo "WOULD-PRUNE $comp_path"
        else
            rm -rf "$comp_path"
            [ -z "$(ls -A "$d" 2>/dev/null)" ] && rmdir "$d" 2>/dev/null || true
        fi
        deleted=$((deleted+1))
    fi
done
echo $deleted
"""
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "bash", "-c", script],
        capture_output=True,
        text=True,
    )
    if dry_run:
        for line in r.stdout.splitlines():
            if line.startswith("WOULD-PRUNE "):
                print(f"[dry-run] usb/{component}: {line[len('WOULD-PRUNE '):]}")
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def prune_usb_stale_dirs(dry_run: bool) -> int:
    """Keep ONLY the single newest scheduled Daily_Triage backup on USB; sweep every other
    dated dir.

    The USB drive is the LAST-RESORT recovery copy — the one you reach for when both the DR
    server and Google Drive are unavailable — so by owner policy it holds exactly ONE copy: the
    latest full daily backup. This used to sweep only whole dirs older than 45 days, which let
    one-off / manual / test / pre-deploy snapshot dirs (a layout the per-component prune never
    matches) pile up forever — that is what filled the USB to 61 GB / 36 dirs. Now we keep the
    newest *_Daily_Triage and remove the rest, which also cleans out anything non-daily that
    landed here. If (edge case) no Daily_Triage is present, keep the newest dated dir so the USB
    is never left empty. Root-owned -> via archie_platform."""
    dry = "1" if dry_run else "0"
    script = f"""
set -e
cd /mnt/external-backup 2>/dev/null || exit 0
DRY={dry}
# newest scheduled daily is the one to KEEP; fall back to newest dated dir so USB is never empty
keep=$(ls -1d *_Daily_Triage 2>/dev/null | sort -r | head -1 || true)
if [ -z "$keep" ]; then keep=$(ls -1 2>/dev/null | grep -E '^[0-9]{{8}}_' | sort -r | head -1 || true); fi
deleted=0
for d in $(ls -1 2>/dev/null | grep -E '^[0-9]{{8}}_' || true); do
    if [ "$d" != "$keep" ]; then
        if [ "$DRY" = "1" ]; then echo "WOULD-SWEEP $d"; else rm -rf "$d"; fi
        deleted=$((deleted+1))
    fi
done
echo $deleted
"""
    cap = USB_MAX_AGE_DAYS  # retained for back-compat / env override; no longer used for the sweep
    _ = cap
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "bash", "-c", script],
        capture_output=True,
        text=True,
    )
    if dry_run:
        for line in r.stdout.splitlines():
            if line.startswith("WOULD-SWEEP "):
                print(f"[dry-run] usb sweep (keep newest Daily_Triage only): {line[len('WOULD-SWEEP '):]}")
    try:
        return int(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


# How many pre-deploy snapshots to retain. Small on purpose: each is ~1.6 GB and exists
# to roll back ONE deploy. Tune here — they are NOT in RETENTION (see the docstring below
# for why a RETENTION entry would silently match nothing).
PREDEPLOY_KEEP = 3

# Newest N module backups kept PER module in PRIMARY_ROOT/modules/ (owner ask 2026-07-23:
# every module backed up daily via the new daily_module_backup job → ~34/day; without a bound
# they accumulate unbounded). The per-module flat layout cannot be expressed as a RETENTION
# component (no run_dir/component shape) — see prune_modules(). (#5143)
MODULE_KEEP = 7

# Pre-deploy dirs that could NOT be deleted this run. main() turns a non-zero count into a
# non-zero exit so backup_triage.sh cannot log "retention prune OK" over a prune that removed
# nothing (#5030 — the fix shipped in #2378 did exactly that for a full day).
_PREDEPLOY_FAILURES = 0
_MODULE_FAILURES = 0

# The container's view of PRIMARY_ROOT. Only meaningful when PRIMARY_ROOT is the real backup
# root; a BACKUP_ROOT override (tests, DR drills) must NEVER cause an rm inside the container.
CONTAINER_BACKUP_ROOT = "/backups"
DEFAULT_PRIMARY_ROOT = Path("/mnt/data2/backups")


def _remove_predeploy_dir(run_dir: Path) -> bool:
    """Remove one pre-deploy snapshot, falling back to the container when the host can't.

    Repair Bay writes these from INSIDE archie_platform, so every file lands root:root 0755.
    This script runs from cron as the unprivileged backup user, which CAN unlink the run dir's
    entry (the parent `backups/` is user-owned) but CANNOT delete anything inside it —
    shutil.rmtree dies on the first `metadata.json` with EACCES. The dir survives, the loop
    swallows the OSError, and the run still reports success. Delegating the unlink to the
    process that owns the bytes is the fix; chown-ing at write time would only fix new ones.

    Returns True only when the directory is verifiably gone.
    """
    try:
        shutil.rmtree(run_dir)
        return True
    except OSError as exc:
        print(f"prune: host rmtree failed ({exc}) — retrying inside archie_platform")

    if PRIMARY_ROOT.resolve() != DEFAULT_PRIMARY_ROOT:
        print(
            f"prune: FAILED to remove {run_dir}: BACKUP_ROOT is overridden "
            f"({PRIMARY_ROOT}), refusing to rm inside the container"
        )
        return False

    # No shell: these names embed '#', ':' and '[]' taken from the proposal title.
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "rm", "-rf", "--", f"{CONTAINER_BACKUP_ROOT}/{run_dir.name}"],
        capture_output=True,
        text=True,
    )
    if run_dir.exists():
        print(
            f"prune: FAILED to remove {run_dir}: still present after container rm "
            f"(rc={r.returncode} {(r.stderr or '').strip()[:160]})"
        )
        return False
    return True


def prune_predeploy_snapshots(keep: int = PREDEPLOY_KEEP) -> int:
    """Keep only the newest `keep` pre-deploy snapshots; delete the rest WHOLE.

    These CANNOT go through prune_dir/RETENTION. That path requires a
    <run_dir>/<component>/ SUBDIRECTORY to exist and prunes that subdir — pre-deploy
    snapshots have no such shape: their payload is `database.sql.gz` (a FILE), and the
    run dir is nested under path fragments taken from the proposal title, e.g.
        20260720_184117_..._PYFLAKES:_repair_bay/services/nl_code_generator.py_/database.sql.gz
    (the title contains '/', which create_backup_programmatic does not sanitise — see
    task #5030). A RETENTION entry would therefore match NOTHING and silently prune 0.

    Until 2026-07-20 nothing pruned these at all: 18 had accumulated in a single evening
    totalling ~17.4 GB, because Repair Bay takes a full ~1.6 GB snapshot per approved
    deploy (ADR-009 replaces that with a module-scoped one; this is the interim bound).

    A pre-deploy snapshot exists to roll back ONE deploy. Once later deploys have
    succeeded on top of it, it is not a restore point anyone will use — the nightly
    tiers are. Hence a small count rather than a GFS ladder.
    """
    if not PRIMARY_ROOT.is_dir():
        return 0
    runs = []
    for child in PRIMARY_ROOT.iterdir():
        if not child.is_dir() or "Pre-deploy" not in child.name:
            continue
        # Sort on the full YYYYMMDD_HHMMSS prefix, NOT parse_ts(). parse_ts returns
        # DATE-ONLY (correct for the GFS daily/weekly/monthly ladder, useless here):
        # every snapshot taken on the same day parses to an identical timestamp, so
        # "keep the newest 3" would keep 3 ARBITRARY ones — potentially deleting the
        # most recent rollback point and retaining the oldest. These are taken minutes
        # apart, so intra-day precision is the whole point. The prefix is zero-padded
        # fixed-width, so lexicographic order IS chronological order.
        m = re.match(r"^(\d{8}_\d{6})", child.name)
        if not m:
            continue
        runs.append((m.group(1), child))
    runs.sort(key=lambda r: r[0], reverse=True)

    deleted = 0
    for _ts, run_dir in runs[keep:]:
        if DRY_RUN:
            print(f"[dry-run] would remove pre-deploy snapshot {run_dir}")
            deleted += 1
            continue
        print(f"prune: removing pre-deploy snapshot {run_dir}")
        if _remove_predeploy_dir(run_dir):
            deleted += 1
        else:
            global _PREDEPLOY_FAILURES
            _PREDEPLOY_FAILURES += 1
    return deleted


def _remove_module_dir(mod_dir: Path) -> bool:
    """Remove one module backup dir (host rmtree, container fallback for root-owned files).

    Module backups are written from INSIDE archie_platform (backup_module()), so their files
    land root:root and the unprivileged cron user cannot rmtree them — same problem and same
    fix as _remove_predeploy_dir. mod_dir lives at PRIMARY_ROOT/modules/<name>, so the
    container path is /backups/modules/<name>.
    """
    try:
        shutil.rmtree(mod_dir)
        return True
    except OSError as exc:
        print(f"prune: host rmtree failed ({exc}) — retrying inside archie_platform")

    if PRIMARY_ROOT.resolve() != DEFAULT_PRIMARY_ROOT:
        print(
            f"prune: FAILED to remove {mod_dir}: BACKUP_ROOT is overridden "
            f"({PRIMARY_ROOT}), refusing to rm inside the container"
        )
        return False

    r = subprocess.run(
        ["docker", "exec", "archie_platform", "rm", "-rf", "--", f"{CONTAINER_BACKUP_ROOT}/modules/{mod_dir.name}"],
        capture_output=True,
        text=True,
    )
    if mod_dir.exists():
        print(
            f"prune: FAILED to remove {mod_dir}: still present after container rm "
            f"(rc={r.returncode} {(r.stderr or '').strip()[:160]})"
        )
        return False
    return True


def prune_modules(keep_per_module: int = MODULE_KEEP) -> int:
    """Keep only the newest `keep_per_module` backups PER module in PRIMARY_ROOT/modules/.

    backup_module() writes PRIMARY_ROOT/modules/<YYYYMMDD_HHMMSS>_module_<name>/ — a flat,
    per-module layout with no run_dir/component shape, so prune_dir/RETENTION cannot express it
    (a RETENTION entry would match nothing, exactly like pre-deploy snapshots). The new
    daily_module_backup job backs up every module daily (~34/day), so without this they grow
    unbounded. Group by module name; keep the newest N each; delete the rest WHOLE.

    Orphan backup_log rows are left for the Backups tab's on-disk filter to hide — the same
    convention every other pruner here follows (none of them touch backup_log).
    """
    mroot = PRIMARY_ROOT / "modules"
    if not mroot.is_dir():
        return 0
    by_module: dict = {}
    for child in mroot.iterdir():
        if not child.is_dir():
            continue
        # <YYYYMMDD_HHMMSS>_module_<name> — fixed-width zero-padded prefix, so lexicographic
        # order IS chronological (intra-day precision matters: the daily job + a same-day
        # per-deploy backup land on the same date).
        m = re.match(r"^(\d{8}_\d{6})_module_(.+)$", child.name)
        if not m:
            continue
        by_module.setdefault(m.group(2), []).append((m.group(1), child))

    global _MODULE_FAILURES
    deleted = 0
    for _name, runs in by_module.items():
        runs.sort(key=lambda r: r[0], reverse=True)
        for _ts, mod_dir in runs[keep_per_module:]:
            if DRY_RUN:
                print(f"[dry-run] would remove module backup {mod_dir}")
                deleted += 1
                continue
            print(f"prune: removing module backup {mod_dir}")
            if _remove_module_dir(mod_dir):
                deleted += 1
            else:
                _MODULE_FAILURES += 1
    return deleted


def _gdrive_list_files():
    """Inventory the Drive backup folder via the archie_platform container.

    Drive credentials live in the platform container (this script runs on the
    host), so we delegate the API call the same way prune_usb_via_container does.
    Returns a list of {id, name, size} dicts, or None if Drive is unreachable /
    not configured (retention then leaves the gdrive tier untouched — fail-open).
    """
    code = (
        "import json, sys; sys.path.insert(0, '/app')\n"
        "from tools.google_work_suite.services.drive_service import ("
        " backup_get_drive_service, backup_ensure_folder, backup_list_backup_files)\n"
        "svc = backup_get_drive_service()\n"
        "fid = backup_ensure_folder(svc)\n"
        "print('JSON:' + json.dumps(backup_list_backup_files(svc, fid)))\n"
    )
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "python3", "-c", code],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"gdrive list failed: {r.stderr.strip()[:300]}", file=sys.stderr)
        return None
    for line in r.stdout.splitlines():
        if line.startswith("JSON:"):
            try:
                return json.loads(line[len("JSON:") :])
            except json.JSONDecodeError:
                return None
    return None


def _gdrive_delete_files(ids: list) -> int:
    """Permanently delete the given Drive file ids via the container. Returns count.

    Hard-delete (not trash): the 15 GB gdrive tier is quota-bound and Google counts
    TRASHED files against quota for ~30 days, so trashing would never actually free
    space or bound the tier. This matches the primary/usb tiers pruning with rmtree.
    Callers pass only recognised backup artifacts (see prune_gdrive).
    """
    if not ids:
        return 0
    code = (
        "import json, sys; sys.path.insert(0, '/app')\n"
        "from tools.google_work_suite.services.drive_service import ("
        " backup_get_drive_service, backup_delete_file)\n"
        "ids = json.loads(sys.stdin.read())\n"
        "svc = backup_get_drive_service()\n"
        "n = 0\n"
        "for i in ids:\n"
        "    try:\n"
        "        backup_delete_file(svc, i); n += 1\n"
        "    except Exception as e:\n"
        "        print(f'delete-fail {i}: {e}', file=sys.stderr)\n"
        "print('DELETED:' + str(n))\n"
    )
    r = subprocess.run(
        ["docker", "exec", "-i", "archie_platform", "python3", "-c", code],
        input=json.dumps(ids),
        capture_output=True,
        text=True,
    )
    for line in r.stdout.splitlines():
        if line.startswith("DELETED:"):
            return int(line[len("DELETED:") :])
    print(f"gdrive delete failed: {r.stderr.strip()[:300]}", file=sys.stderr)
    return 0


_BUNDLE_RE = re.compile(r"^(?P<repo>.+?)_(?P<kind>incremental|full)_(?P<ts>\d{8}_\d{6})\.bundle(\.enc)?$")


def _parse_bundle(name: str):
    """('repo', 'full'|'incremental', 'YYYYMMDD_HHMMSS') for a gitbundle path, else None."""
    parts = name.split("/")
    if len(parts) < 3 or parts[1] != "gitbundles":
        return None
    m = _BUNDLE_RE.match(parts[-1])
    if not m:
        return None
    return m.group("repo"), m.group("kind"), m.group("ts")


def _pin_gitbundle_bases(files: list, delete_ids: list) -> int:
    """Never delete a FULL git bundle that a RETAINED incremental still needs.

    `component_gitbundle.sh` cuts INCREMENTAL bundles (`git bundle create --since=...`).
    An incremental bundle CANNOT restore on its own — it needs the full bundle it was
    cut against. But the GFS ladder keeps whole RUN DIRS by date, with no idea that a
    bundle in one run dir depends on a bundle in an older one. So the ladder could
    delete the run dir holding a repo's base full while keeping newer run dirs packed
    with incrementals, leaving that repo UNRESTORABLE off-site — and silently, because
    every individual file still lists fine and the tier looks healthy (#5129).

    For each repo with retained incrementals, pin the newest full at-or-before the
    OLDEST retained incremental (that is the base the chain actually needs). If no
    full is old enough, pin the newest full available rather than deleting every base.

    Mutates `delete_ids` in place; returns how many ids were rescued. Bounded: at most
    one full per repo.
    """
    by_id = {}
    for f in files:
        parsed = _parse_bundle(f.get("name", ""))
        if parsed:
            by_id[f["id"]] = parsed

    if not by_id:
        return 0

    doomed = set(delete_ids)
    repos: dict = {}
    for fid, (repo, kind, ts) in by_id.items():
        repos.setdefault(repo, []).append((ts, kind, fid))

    pinned = set()
    for repo, entries in repos.items():
        retained_incr = [ts for ts, kind, fid in entries if kind == "incremental" and fid not in doomed]
        if not retained_incr:
            continue  # nothing depends on a base for this repo
        oldest_needed = min(retained_incr)
        fulls = sorted([(ts, fid) for ts, kind, fid in entries if kind == "full"])
        if not fulls:
            continue  # no base exists at all — a pre-existing gap, not ours to invent
        eligible = [(ts, fid) for ts, fid in fulls if ts <= oldest_needed]
        base_ts, base_id = eligible[-1] if eligible else fulls[-1]
        if base_id in doomed:
            pinned.add(base_id)
            print(f"gdrive: pinning base bundle for {repo} ({base_ts}) — retained incrementals need it")

    if pinned:
        delete_ids[:] = [i for i in delete_ids if i not in pinned]
    return len(pinned)


def prune_gdrive(dry_run: bool) -> int:
    """Apply the GFS ladder to the Google Drive tier by trashing old backup files.

    The gdrive tier never had a pruner, so the 'ARCHIE Backups' folder grew until
    the free-tier quota filled and the DB dump stopped uploading (#5092). Files are
    named '<TS>_<mode>/<component>/<file>.enc'; we parse that, group by (component,
    run-dir), keep per RETENTION[component]['gdrive'] with the SAME ladder as the
    disk tiers, and PERMANENTLY DELETE the rest (trash does not free a quota-bound
    tier — see _gdrive_delete_files). Unknown components and unparseable names are
    left alone — we never auto-delete something we can't classify.
    """
    files = _gdrive_list_files()
    if files is None:
        print("gdrive prune skipped — Drive unreachable/not configured", file=sys.stderr)
        return 0

    # component -> { run_dir_name -> [file_id, ...] }  (one entry per run dir, like prune_dir)
    comp_runs: dict = {}
    for f in files:
        parts = f.get("name", "").split("/")
        if len(parts) < 2:
            continue  # flat/unrecognised file — never auto-delete
        run_name, component = parts[0], parts[1]
        if component not in RETENTION or parse_ts(run_name) is None:
            continue
        comp_runs.setdefault(component, {}).setdefault(run_name, []).append(f["id"])

    delete_ids: list = []
    for component, runs in comp_runs.items():
        keep_d, keep_w, keep_m = RETENTION[component].get("gdrive", (0, 0, 0))
        kept_d = kept_w = kept_m = 0
        for run_name in sorted(runs.keys(), reverse=True):  # newest first
            tags = classify(parse_ts(run_name))
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
                delete_ids.extend(runs[run_name])

    # Chain integrity: rescue any FULL bundle a retained incremental still needs.
    # MUST run after the ladder has decided, and before anything is deleted (#5129).
    rescued = _pin_gitbundle_bases(files, delete_ids)
    if rescued:
        print(f"gdrive: kept {rescued} base bundle(s) the ladder would have orphaned")

    if not delete_ids:
        return 0
    if dry_run:
        print(f"[dry-run] gdrive: would delete {len(delete_ids)} file(s)")
        return len(delete_ids)
    n = _gdrive_delete_files(delete_ids)
    print(f"gdrive: deleted {n} file(s)")
    return n


def main() -> None:
    total_deleted = 0
    usb_deleted = 0
    for component in RETENTION.keys():
        total_deleted += prune_dir(PRIMARY_ROOT, component, "primary")
        usb_deleted += prune_usb_via_container(component, DRY_RUN)
    # Whole-dir age sweep for one-off / non-standard USB backups the per-component prune misses.
    usb_deleted += prune_usb_stale_dirs(DRY_RUN)
    total_deleted += usb_deleted
    # gdrive tier (off-site cloud): trash old Drive files per the GFS ladder. This tier had
    # no pruner, so the 15 GB free-tier quota filled and the DB dump stopped uploading (#5092).
    gdrive_deleted = prune_gdrive(DRY_RUN)
    total_deleted += gdrive_deleted
    # Pre-deploy snapshots: whole-dir, count-based — they do not fit the component model.
    total_deleted += prune_predeploy_snapshots()
    # Module backups: newest N PER module (flat per-module layout, see prune_modules). The daily
    # all-modules job (#5143) makes bounding this a requirement, not optional.
    module_deleted = prune_modules()
    total_deleted += module_deleted

    if DRY_RUN:
        print(
            f"[dry-run] retention prune: {total_deleted} items WOULD be removed "
            f"(primary + usb {usb_deleted}; gdrive {gdrive_deleted}; modules {module_deleted})"
        )
        return

    # Record the run: backup_log row + system_config retention_last_run/deleted_count so the
    # Backup Manager UI reflects THIS canonical engine (it was stale because the old module job
    # was the only writer — #4051). Undeletable pre-deploy snapshots go in the note too, so the
    # UI shows the shortfall instead of a clean "N deleted" that hides a stuck prune.
    note = f"{total_deleted} deleted ({usb_deleted} usb, {gdrive_deleted} gdrive, {module_deleted} modules)"
    if _PREDEPLOY_FAILURES:
        note += f", {_PREDEPLOY_FAILURES} pre-deploy FAILED"
    if _MODULE_FAILURES:
        note += f", {_MODULE_FAILURES} module FAILED"
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
            f"VALUES ('retention', 'primary', 'prune', '{note}', NOW());"
            f"UPDATE system_config SET value = NOW()::text WHERE key = 'retention_last_run';"
            f"UPDATE system_config SET value = '{total_deleted}' WHERE key = 'retention_last_deleted_count';",
        ],
        check=False,
        capture_output=True,
    )
    print(f"retention prune: {total_deleted} items removed")

    # Exit non-zero so backup_triage.sh logs "WARN: retention prune had errors" instead of
    # "retention prune OK". A prune that cannot delete is a disk-fill risk, not a clean run —
    # #2378 reported OK for a full day while removing nothing (#5030).
    if _PREDEPLOY_FAILURES:
        print(
            f"retention prune: {_PREDEPLOY_FAILURES} pre-deploy snapshot(s) could NOT be "
            f"removed — primary tier will keep growing"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
