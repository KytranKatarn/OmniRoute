#!/usr/bin/env python3
"""scripts/backup/tier_sync_usb.py <run_dir>

Copies the hot-tier components from a primary backup run dir to USB.
Uses the tar-pipe-through-archie_platform pattern because /mnt/external-backup
is root-owned on the host (kytran can read but not write), while archie_platform
has rw inside the container.

Components that land on USB (spec §6): database, code, gitbundles, config, volumes.

Writes one row per component to backup_log with tier='usb'.

Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md
Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 14
"""

import os
import subprocess
import sys
import time
from pathlib import Path

USB_ROOT = Path(os.environ.get("BACKUP_USB", "/mnt/external-backup"))
TIER_COMPONENTS = {"database", "code", "gitbundles", "config", "volumes"}


def log_db(component: str, status: str, path: str, size: int, dur_ms: int, err: str = "") -> None:
    """Write a row to backup_log via docker exec. Schema-aware (new/legacy)."""
    err_sql = err.replace("'", "''")
    sql = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='backup_log' AND column_name='component') THEN
        INSERT INTO backup_log
            (component, tier, status, file_path, size_bytes, duration_ms, error_message, created_at)
        VALUES
            ('{component}', 'usb', '{status}', '{path}', {size}, {dur_ms},
             NULLIF('{err_sql}', ''), NOW());
    ELSE
        INSERT INTO backup_log
            (backup_type, file_path, file_size_bytes, status, error_message, completed_at, created_at)
        VALUES
            ('{component}', '{path}', {size}, '{status}',
             NULLIF('{err_sql}', ''), NOW(), NOW());
    END IF;
END $$;
"""
    subprocess.run(
        ["docker", "exec", "-i", "archie_database", "psql", "-U", "archie", "-d", "archie", "-c", sql],
        check=False,
        capture_output=True,
    )


def usb_size_via_container(target: str) -> int:
    """Measure USB target size via archie_platform container (which has read access)."""
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "bash", "-c", f"du -sb '{target}' 2>/dev/null | awk '{{print $1}}'"],
        capture_output=True,
        text=True,
    )
    try:
        return int(r.stdout.strip() or "0")
    except ValueError:
        return 0


def sync_component(component: str, src: Path, target_run: str) -> tuple[bool, int, int, str]:
    """Pipe `src` → /mnt/external-backup/<target_run>/<component>/ via tar through archie_platform."""
    start = time.time()
    target_inside_container = f"/mnt/external-backup/{target_run}/{component}"

    # Ensure target dir exists inside container.
    mkdir = subprocess.run(
        ["docker", "exec", "archie_platform", "mkdir", "-p", target_inside_container],
        capture_output=True,
        text=True,
    )
    if mkdir.returncode != 0:
        return (False, 0, int((time.time() - start) * 1000), mkdir.stderr[:500])

    # Tar-pipe the component directory.
    tar_src = subprocess.Popen(
        ["tar", "-C", str(src.parent), "-cf", "-", src.name],
        stdout=subprocess.PIPE,
    )
    # On the receiving side, extract into the target with --strip-components=1
    # so we don't re-create the outer <component>/ wrapper.
    tar_dst = subprocess.Popen(
        [
            "docker",
            "exec",
            "-i",
            "archie_platform",
            "tar",
            "-C",
            target_inside_container,
            "--strip-components=1",
            "-xf",
            "-",
        ],
        stdin=tar_src.stdout,
        stderr=subprocess.PIPE,
    )
    tar_src.stdout.close()
    _, stderr = tar_dst.communicate()
    tar_src.wait()

    dur_ms = int((time.time() - start) * 1000)
    if tar_src.returncode != 0 or tar_dst.returncode != 0:
        return (False, 0, dur_ms, stderr.decode("utf-8", errors="replace")[:500])

    size = usb_size_via_container(target_inside_container)
    return (True, size, dur_ms, "")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: tier_sync_usb.py <run_dir>", file=sys.stderr)
        sys.exit(2)

    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"run_dir does not exist: {run_dir}", file=sys.stderr)
        sys.exit(2)

    target_run = run_dir.name
    failures = 0
    for component in sorted(os.listdir(run_dir)):
        if component not in TIER_COMPONENTS:
            continue
        src = run_dir / component
        if not src.is_dir():
            continue
        ok, size, dur_ms, err = sync_component(component, src, target_run)
        remote = f"/mnt/external-backup/{target_run}/{component}"
        if ok:
            log_db(component, "success", remote, size, dur_ms)
            print(f"usb ok: {component} {size}B {dur_ms}ms")
        else:
            failures += 1
            log_db(component, "failed", remote, 0, dur_ms, err)
            print(f"usb FAIL: {component} — {err[:200]}", file=sys.stderr)

    sys.exit(failures)


if __name__ == "__main__":
    main()
