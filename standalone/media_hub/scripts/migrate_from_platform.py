"""
Data Migration — Platform → Standalone Media Hub
================================================
One-shot script that copies every media_hub_services row from the
ARCHIE platform DB into the standalone Media Hub DB.

Designed to run inside the mediahub_app container so DATABASE_URL
(standalone) is already configured. The platform DB is addressed via
SOURCE_DATABASE_URL.

Usage (from repo root):

    docker compose -f standalone/media_hub/docker-compose.yml run --rm \\
        -e SOURCE_DATABASE_URL="postgresql://archie:<pw>@192.168.1.200:5432/archie" \\
        -e SOURCE_MEDIA_HUB_ENCRYPTION_KEY="<platform-fernet-key>" \\
        mediahub_app python3 /app/scripts/migrate_from_platform.py [--dry-run]

Behaviour

- Reads every row from platform media_hub_services.
- If SOURCE_MEDIA_HUB_ENCRYPTION_KEY equals the standalone's
  MEDIA_HUB_ENCRYPTION_KEY, ciphertext is copied verbatim — no
  decrypt/encrypt round trip.
- Otherwise: decrypt with SOURCE key, re-encrypt with the standalone
  key. Any InvalidToken aborts the whole transaction (no half-migrated
  state — the UNIQUE(service_type, host, port) constraint makes upsert
  safe to retry after fixing the source-side problem).
- UPSERT via ON CONFLICT (service_type, host, port) DO UPDATE — safe to
  re-run; later runs re-sync any rows that have drifted on the platform
  side while the standalone hasn't yet been touched.
- --dry-run prints what would change and commits nothing.

Does NOT migrate:
- health_status / health_message / last_health_check — the standalone's
  own scheduled health job will repopulate these within 10 minutes.
- The 4 FK-child tables (media_library_cache, media_requests,
  media_upcoming_episodes, media_download_queue) — the current Media Hub
  code doesn't read them, and the standalone schema doesn't yet include
  them (see Project #273 audit notes).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import contextmanager

import psycopg2
from cryptography.fernet import Fernet, InvalidToken

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("media_hub.migrate")


def _env_or_die(var: str) -> str:
    v = os.getenv(var)
    if not v:
        log.error("Missing required env var: %s", var)
        sys.exit(2)
    return v


@contextmanager
def _connect(url: str, *, readonly: bool = False):
    conn = psycopg2.connect(url)
    try:
        conn.autocommit = False
        if readonly:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
        yield conn
    finally:
        conn.close()


def _need_reencrypt(src_key: str, dst_key: str) -> bool:
    return src_key.strip() != dst_key.strip()


def migrate(dry_run: bool) -> int:
    src_url = _env_or_die("SOURCE_DATABASE_URL")
    dst_url = _env_or_die("DATABASE_URL")
    src_key = _env_or_die("SOURCE_MEDIA_HUB_ENCRYPTION_KEY")
    dst_key = _env_or_die("MEDIA_HUB_ENCRYPTION_KEY")

    if src_url == dst_url:
        log.error("SOURCE_DATABASE_URL and DATABASE_URL are identical — refusing to self-migrate")
        return 2

    rekey = _need_reencrypt(src_key, dst_key)
    if rekey:
        src_fernet = Fernet(src_key.encode())
        dst_fernet = Fernet(dst_key.encode())
        log.info("re-encryption ENABLED — source & target keys differ")
    else:
        src_fernet = dst_fernet = None
        log.info("re-encryption skipped — source & target keys match, ciphertext copied verbatim")

    with _connect(src_url, readonly=True) as src_conn, _connect(dst_url) as dst_conn:
        with src_conn.cursor() as scur:
            scur.execute(
                """
                SELECT service_type, name, host, port, use_ssl, api_key_encrypted,
                       is_primary, is_enabled, config_path
                FROM media_hub_services
                ORDER BY id
                """
            )
            rows = scur.fetchall()

        log.info("source rows found: %d", len(rows))
        if not rows:
            log.info("nothing to migrate")
            return 0

        migrated = 0
        rekeyed = 0

        with dst_conn.cursor() as dcur:
            for row in rows:
                (service_type, name, host, port, use_ssl, enc, is_primary, is_enabled, config_path) = row

                new_enc = enc
                if rekey and enc:
                    try:
                        plaintext = src_fernet.decrypt(enc.encode("utf-8"))
                    except InvalidToken:
                        log.error(
                            "Row (%s %s:%s) cannot be decrypted with SOURCE key. "
                            "Aborting — nothing committed.",
                            service_type, host, port,
                        )
                        dst_conn.rollback()
                        return 3
                    new_enc = dst_fernet.encrypt(plaintext).decode("utf-8")
                    rekeyed += 1

                dcur.execute(
                    """
                    INSERT INTO media_hub_services
                        (service_type, name, host, port, use_ssl, api_key_encrypted,
                         is_primary, is_enabled, config_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (service_type, host, port) DO UPDATE SET
                        name              = EXCLUDED.name,
                        use_ssl           = EXCLUDED.use_ssl,
                        api_key_encrypted = EXCLUDED.api_key_encrypted,
                        is_primary        = EXCLUDED.is_primary,
                        is_enabled        = EXCLUDED.is_enabled,
                        config_path       = EXCLUDED.config_path,
                        updated_at        = CURRENT_TIMESTAMP
                    """,
                    (service_type, name, host, port, use_ssl, new_enc,
                     is_primary, is_enabled, config_path),
                )
                migrated += 1
                log.info("upsert %s %s:%s%s", service_type, host, port,
                         " (re-encrypted)" if rekey and enc else "")

        if dry_run:
            dst_conn.rollback()
            log.info("DRY RUN — rolled back. would-upsert=%d would-rekey=%d", migrated, rekeyed)
            return 0

        dst_conn.commit()
        log.info("migration complete — upserted=%d rekeyed=%d", migrated, rekeyed)
        log.info("next: log in to https://media.kytranempowerment.com/ and click 'Test Connection' on each service")
        return 0


def _parse_args():
    ap = argparse.ArgumentParser(description="Migrate media_hub_services rows platform → standalone.")
    ap.add_argument("--dry-run", action="store_true", help="Print changes and roll back without committing.")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(migrate(dry_run=args.dry_run))
