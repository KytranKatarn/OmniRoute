"""DB writes: upsert articles + bias scores + audit trail. Dead-letter on failure."""
import json
import logging
import os
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _schema() -> str:
    return os.environ.get("WTF_SCHEMA", "wtf")


def upsert_article(engine, source_id: int, article: dict, bias: dict) -> bool:
    """Insert article + bias_score + audit entry in one tx. Returns True on insert, False on dedupe."""
    S = _schema()
    with engine.begin() as c:
        r = c.execute(text(f"""
            INSERT INTO {S}.articles (source_id, external_id, title, body, url, published_at)
            VALUES (:sid, :eid, :t, :b, :u, :p)
            ON CONFLICT (source_id, external_id) DO NOTHING
            RETURNING id
        """), {
            "sid": source_id, "eid": article["external_id"], "t": article["title"],
            "b": article["body"], "u": article["url"], "p": article["published_at"],
        })
        row = r.fetchone()
        if not row:
            return False
        aid = row[0]
        c.execute(text(f"""
            INSERT INTO {S}.bias_scores (article_id, band, score, heuristic_version, rationale)
            VALUES (:aid, :band, :score, :v, :rat)
        """), {"aid": aid, "band": bias["band"], "score": bias["score"],
               "v": bias["heuristic_version"], "rat": bias["rationale"]})
        c.execute(text(f"""
            INSERT INTO {S}.audit_trail (article_id, event_type, payload)
            VALUES (:aid, 'ingested', :p)
        """), {"aid": aid, "p": json.dumps({"source_id": source_id, "bias": bias})})
    return True


def record_failure(engine, source_slug: str, raw: dict, error: str) -> None:
    S = _schema()
    with engine.begin() as c:
        c.execute(text(f"""
            INSERT INTO {S}.failed_ingest (source_slug, raw_payload, error)
            VALUES (:s, :r, :e)
        """), {"s": source_slug, "r": json.dumps(raw, default=str), "e": error})
    logger.warning("dead-letter: %s - %s", source_slug, error[:100])
