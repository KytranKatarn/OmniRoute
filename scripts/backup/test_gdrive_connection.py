#!/usr/bin/env python3
"""Smoke test for Google Drive backup wiring.
Checks: OAuth configured, service builds, folder id resolves, test upload + delete roundtrip."""

import subprocess
import sys
import tempfile
import time
import os


def run_in_platform(py: str) -> tuple[int, str]:
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "python3", "-c", py],
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def main() -> int:
    rc, out = run_in_platform(
        "from tools.google_work_suite.services.drive_service import backup_is_oauth_configured;"
        "print(backup_is_oauth_configured())"
    )
    if rc != 0 or "True" not in out:
        print(f"FAIL oauth not configured: {out}")
        return 1
    print("OK oauth configured")

    rc, out = run_in_platform(
        "from tools.google_work_suite.services.drive_service import "
        "backup_get_drive_service, backup_ensure_folder;"
        "svc = backup_get_drive_service();"
        "print(backup_ensure_folder(svc))"
    )
    if rc != 0:
        print(f"FAIL folder resolve: {out}")
        return 1
    folder_id = out.splitlines()[-1]
    print(f"OK folder_id={folder_id}")

    # Test upload.
    with tempfile.NamedTemporaryFile(prefix="dr_smoke_", suffix=".txt", delete=False) as tf:
        tf.write(f"smoke test {time.time()}\n".encode())
        local = tf.name
    remote = f"dr_smoke_{int(time.time())}.txt"

    try:
        rc, out = run_in_platform(
            "from tools.google_work_suite.services.drive_service import ("
            " backup_get_drive_service, backup_ensure_folder,"
            " backup_upload_file, backup_delete_file);"
            "svc = backup_get_drive_service();"
            f"fid = backup_ensure_folder(svc);"
            f"r = backup_upload_file(svc, {local!r}, fid, filename={remote!r});"
            "print(r['id']);"
            "print(backup_delete_file(svc, r['id']))"
        )
        if rc != 0 or "True" not in out:
            print(f"FAIL upload/delete: {out}")
            return 1
        print(f"OK upload+delete roundtrip")
        return 0
    finally:
        if os.path.exists(local):
            os.unlink(local)


if __name__ == "__main__":
    sys.exit(main())
