"""newsletter_kbs_sync.py — push new WTF newsletter subscribers into KBS CRM.

Upserts each not-yet-synced active subscriber as a kbs_crm contact via the
KBS internal endpoint (X-Internal-Key auth), then stamps kbs_synced_at so the
row is never pushed twice. Runs once per ingest cycle, batch-capped; a dead
KBS simply defers the batch to the next cycle (self-healing, no data loss —
the unsynced rows stay flagged until the push succeeds).

Default OFF — activates when KBS_INTERNAL_KEY is set.
KBS_INTERNAL_URL defaults to the hub mesh IP (never public hostnames).
"""
import logging
import os

import requests
from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

_KBS_URL = os.environ.get("KBS_INTERNAL_URL", "http://100.64.0.4:8091")
_KBS_KEY = os.environ.get("KBS_INTERNAL_KEY", "")
_BATCH = int(os.environ.get("WTF_KBS_SYNC_BATCH", "50"))
_ENDPOINT = "/plugins/crm/api/internal/upsert-contact"

_ALLOWED_SCHEMAS = frozenset({"wtf"})


def run_sync(engine, schema: str = "wtf") -> dict:
    if not _KBS_KEY:
        return {"synced": 0, "stopped": "disabled"}
    if schema not in _ALLOWED_SCHEMAS:
        return {"synced": 0, "stopped": "bad_schema"}

    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT id, email, source
                FROM {schema}.newsletter_subscribers
                WHERE active = TRUE AND kbs_synced_at IS NULL
                ORDER BY id
                LIMIT :n
            """),
            {"n": _BATCH},
        ).mappings().all()
    if not rows:
        return {"synced": 0, "stopped": "empty"}

    synced = errors = 0
    for r in rows:
        try:
            resp = requests.post(
                f"{_KBS_URL}{_ENDPOINT}",
                json={
                    "email": r["email"],
                    "source": f"wtf-{r['source']}",
                    "tags": ["wtf-newsletter"],
                },
                headers={"X-Internal-Key": _KBS_KEY},
                timeout=8,
            )
            if resp.status_code in (200, 201):
                with engine.begin() as c:
                    c.execute(
                        text(f"""
                            UPDATE {schema}.newsletter_subscribers
                            SET kbs_synced_at = NOW() WHERE id = :i
                        """),
                        {"i": r["id"]},
                    )
                synced += 1
            else:
                errors += 1
                logger.warning(
                    "newsletter_kbs_sync: %s -> HTTP %s", r["email"], resp.status_code
                )
        except requests.RequestException as exc:
            errors += 1
            logger.warning("newsletter_kbs_sync: %s failed: %s", r["email"], exc)
            break  # KBS unreachable — yield the batch, retry next cycle

    return {"synced": synced, "errors": errors}
