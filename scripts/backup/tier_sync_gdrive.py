#!/usr/bin/env python3
"""scripts/backup/tier_sync_gdrive.py <run_dir> <mode>

Uploads backup components to Google Drive via the existing Kytran Work Suite
OAuth connection. Files are encrypted client-side with BACKUP_GDRIVE_PASSPHRASE
(AES-256-CBC + PBKDF2) before upload, so Google never sees plaintext.

Drive API calls are delegated to the archie_platform container because the
OAuth token lives there (see tools/google_work_suite/services/drive_service.py
— backup_* functions).

mode: daily | weekly | monthly — determines which components go to cold tier.

Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md §6, §7
Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 15
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

COMPONENTS_BY_MODE = {
    "daily":   {"database", "code", "gitbundles", "config"},
    "weekly":  {"database", "code", "gitbundles", "config", "kb_export"},
    "monthly": {"database", "code", "gitbundles", "config", "kb_export", "monthly_full"},
}

GDRIVE_FOLDER_NAME = "ARCHIE Backups"


def log_db(component: str, status: str, path: str, size: int, dur_ms: int, err: str = "") -> None:
    err_sql = err.replace("'", "''")
    sql = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='backup_log' AND column_name='component') THEN
        INSERT INTO backup_log
            (component, tier, status, file_path, size_bytes, duration_ms, error_message, created_at)
        VALUES
            ('{component}', 'gdrive', '{status}', '{path}', {size}, {dur_ms},
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


def is_oauth_ready() -> bool:
    """Check that Work Suite OAuth is connected in the platform container."""
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "python3", "-c",
         "from tools.google_work_suite.services.drive_service import backup_is_oauth_configured; "
         "print('1' if backup_is_oauth_configured() else '0')"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and r.stdout.strip().endswith("1")


def upload_via_platform(local_path: str, remote_name: str) -> tuple[bool, str]:
    """Delegate the upload to archie_platform (owns OAuth token)."""
    py = (
        "from tools.google_work_suite.services.drive_service "
        "import backup_ensure_folder, backup_upload_file\n"
        f"fid = backup_ensure_folder('{GDRIVE_FOLDER_NAME}')\n"
        f"r = backup_upload_file(fid, '{local_path}', '{remote_name}')\n"
        "print(r)\n"
    )
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "python3", "-c", py],
        capture_output=True, text=True,
    )
    return (r.returncode == 0, (r.stdout + r.stderr).strip())


def encrypt(src: str, dst: str, passphrase: str) -> None:
    """AES-256-CBC + PBKDF2 encrypt src → dst."""
    subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
         "-salt", "-in", src, "-out", dst, "-pass", f"pass:{passphrase}"],
        check=True,
    )


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: tier_sync_gdrive.py <run_dir> <mode>", file=sys.stderr)
        sys.exit(2)

    run_dir = Path(sys.argv[1])
    mode = sys.argv[2]
    components = COMPONENTS_BY_MODE.get(mode, COMPONENTS_BY_MODE["daily"])

    # Load passphrase from host .env (this script runs on host).
    passphrase = os.environ.get("BACKUP_GDRIVE_PASSPHRASE")
    if not passphrase:
        env_path = "/mnt/archie_brain/.env"
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("BACKUP_GDRIVE_PASSPHRASE="):
                        passphrase = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break

    if not passphrase:
        print("BACKUP_GDRIVE_PASSPHRASE not set — skipping gdrive tier", file=sys.stderr)
        log_db("gdrive", "skipped", str(run_dir), 0, 0, "no passphrase")
        sys.exit(0)

    if not is_oauth_ready():
        print("Work Suite OAuth not configured — skipping gdrive tier", file=sys.stderr)
        log_db("gdrive", "skipped", str(run_dir), 0, 0, "oauth not configured")
        sys.exit(0)

    failures = 0
    for component in sorted(os.listdir(run_dir)):
        if component not in components:
            continue
        src_dir = run_dir / component
        if not src_dir.is_dir():
            continue
        for f in src_dir.rglob("*"):
            if not f.is_file():
                continue
            start = time.time()
            # Stage an encrypted temp file (unless already .enc from config tier).
            with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as tf:
                enc_path = tf.name
            up_src = enc_path
            try:
                if str(f).endswith(".enc"):
                    up_src = str(f)
                else:
                    encrypt(str(f), enc_path, passphrase)
                remote_name = f"{run_dir.name}/{f.relative_to(run_dir)}"
                if not str(f).endswith(".enc"):
                    remote_name += ".enc"
                ok, msg = upload_via_platform(up_src, remote_name)
                dur_ms = int((time.time() - start) * 1000)
                size = os.path.getsize(up_src)
                if ok:
                    log_db(component, "success", remote_name, size, dur_ms)
                    print(f"gdrive ok: {remote_name} ({size}B)")
                else:
                    failures += 1
                    log_db(component, "failed", remote_name, size, dur_ms, msg[:500])
                    print(f"gdrive FAIL: {remote_name}: {msg[:200]}", file=sys.stderr)
            finally:
                if up_src == enc_path and os.path.exists(enc_path):
                    os.unlink(enc_path)

    sys.exit(failures)


if __name__ == "__main__":
    main()
