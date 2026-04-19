"""
Encryption Key Rotation — Media Hub Standalone
==============================================
Re-encrypts every api_key_encrypted row in media_hub_services from the
OLD Fernet key to the NEW one in a single transaction. Either all
succeed or nothing changes.

Usage (from the project root, with the standalone stack running):

    docker compose -f standalone/media_hub/docker-compose.yml run --rm \\
        -e MEDIA_HUB_ENCRYPTION_KEY=<OLD_KEY> \\
        -e MEDIA_HUB_NEW_ENCRYPTION_KEY=<NEW_KEY> \\
        mediahub_app python3 /app/scripts/rotate_encryption_key.py

Steps after a successful run:
  1. Replace MEDIA_HUB_ENCRYPTION_KEY in .env with the NEW key
  2. docker compose up -d  (restart so the app picks up the new key)
  3. Smoke-test: sign in + click "Test Connection" on any service;
     confirmed-working means decryption works end-to-end with the new key.

Why a single transaction: Fernet rotation is all-or-nothing. A crash
midway would otherwise leave some rows decryptable by old key and
some by new, and there's no single env var that can serve both — the
app would start throwing InvalidToken on random reads.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager

import psycopg2
from cryptography.fernet import Fernet, InvalidToken

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("media_hub.rotate_key")


def _env_or_die(var: str) -> str:
    v = os.getenv(var)
    if not v:
        log.error("Missing required env var: %s", var)
        sys.exit(2)
    return v


def _build_fernet(name: str, key: str) -> Fernet:
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        log.error("%s is not a valid Fernet key: %s", name, e)
        sys.exit(2)


@contextmanager
def _tx():
    conn = psycopg2.connect(_env_or_die("DATABASE_URL"))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rotate() -> int:
    old_fernet = _build_fernet("MEDIA_HUB_ENCRYPTION_KEY", _env_or_die("MEDIA_HUB_ENCRYPTION_KEY"))
    new_fernet = _build_fernet("MEDIA_HUB_NEW_ENCRYPTION_KEY", _env_or_die("MEDIA_HUB_NEW_ENCRYPTION_KEY"))

    if os.environ["MEDIA_HUB_ENCRYPTION_KEY"] == os.environ["MEDIA_HUB_NEW_ENCRYPTION_KEY"]:
        log.error("OLD and NEW keys are identical — nothing to rotate")
        return 2

    rotated = 0
    skipped = 0
    with _tx() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, service_type, api_key_encrypted "
                "FROM media_hub_services "
                "WHERE api_key_encrypted IS NOT NULL "
                "ORDER BY id"
            )
            rows = cur.fetchall()
            for sid, stype, enc in rows:
                if not enc:
                    skipped += 1
                    continue
                try:
                    plaintext = old_fernet.decrypt(enc.encode("utf-8"))
                except InvalidToken:
                    log.error(
                        "Row id=%s (%s) cannot be decrypted with OLD key. "
                        "Aborting — DB left untouched. Check MEDIA_HUB_ENCRYPTION_KEY.",
                        sid,
                        stype,
                    )
                    raise
                new_enc = new_fernet.encrypt(plaintext).decode("utf-8")
                cur.execute(
                    "UPDATE media_hub_services SET api_key_encrypted = %s WHERE id = %s",
                    (new_enc, sid),
                )
                rotated += 1
                log.info("rotated id=%s service=%s", sid, stype)

    log.info("rotation complete — rotated=%d skipped=%d", rotated, skipped)
    log.info(
        "next: replace MEDIA_HUB_ENCRYPTION_KEY in your .env with the new value, then "
        "docker compose up -d to restart."
    )
    return 0


if __name__ == "__main__":
    sys.exit(rotate())
