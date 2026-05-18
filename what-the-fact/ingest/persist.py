"""DB writes: upsert articles + bias scores + audit trail + story clustering."""
import json
import logging
import os
from sqlalchemy import text

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMAS = frozenset({"wtf", "wtf_test"})


def _schema() -> str:
    return os.environ.get("WTF_SCHEMA", "wtf")


def upsert_article(engine, source_id: int, article: dict, bias: dict, source_slug: str = "") -> bool:
    """Insert article + bias_score + audit entry, then cluster + fact-check. Returns article_id (int) on insert, None on dedupe/failure."""
    S = _schema()
    aid = None
    with engine.begin() as c:
        r = c.execute(
            text(f"""
                INSERT INTO {S}.articles (source_id, external_id, title, body, url, published_at)
                VALUES (:sid, :eid, :t, :b, :u, :p)
                ON CONFLICT (source_id, external_id) DO NOTHING
                RETURNING id
            """),
            {
                "sid": source_id, "eid": article["external_id"], "t": article["title"],
                "b": article["body"], "u": article["url"], "p": article["published_at"],
            },
        )
        row = r.fetchone()
        if not row:
            return None
        aid = row[0]
        c.execute(
            text(f"""
                INSERT INTO {S}.bias_scores (article_id, band, score, heuristic_version, rationale)
                VALUES (:aid, :band, :score, :v, :rat)
            """),
            {"aid": aid, "band": bias["band"], "score": bias["score"],
             "v": bias["heuristic_version"], "rat": bias["rationale"]},
        )
        c.execute(
            text(f"INSERT INTO {S}.audit_trail (article_id, event_type, payload) VALUES (:aid, 'ingested', :p)"),
            {"aid": aid, "p": json.dumps({"source_id": source_id, "bias": bias})},
        )

    # Cluster in a separate transaction (article must be committed first)
    try:
        from ingest.cluster import find_or_create_cluster
        find_or_create_cluster(engine, aid, article["title"], article["published_at"])
    except Exception as exc:
        logger.warning("clustering failed for article %d: %s", aid, exc)

    # Fact-check claims (non-fatal)
    try:
        from ingest.factcheck import factcheck_article
        factcheck_article(engine, aid, article.get("body", ""), source_slug)
    except Exception as exc:
        logger.warning("factcheck failed for article %d: %s", aid, exc)

    # Geo extraction for every article
    try:
        from ingest.geocoder import extract_geo
        geo = extract_geo(aid, article.get("title", ""), article.get("body", ""), source_slug=source_slug)
        save_geo(engine, aid, S, geo)
    except Exception:
        pass  # geo is non-fatal

    return aid


def save_geo(engine, article_id: int, schema: str, geo: dict) -> None:
    """Save geocoder result to article geo columns."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"save_geo: disallowed schema {schema!r}")
    if not geo or not article_id:
        return
    try:
        with engine.begin() as c:
            c.execute(
                text(f"UPDATE {schema}.articles SET province_code = :pc, city = :city, lat = :lat, lng = :lng, geo_scope = :scope WHERE id = :aid"),
                {
                    "pc": geo.get("province_code"),
                    "city": geo.get("city"),
                    "lat": geo.get("lat"),
                    "lng": geo.get("lng"),
                    "scope": geo.get("geo_scope", "national"),
                    "aid": article_id,
                },
            )
    except Exception as exc:
        logger.debug("save_geo: failed for article_id=%s: %s", article_id, exc)


def mark_ai_analyzed(engine, article_id: int, schema: str) -> None:
    """Mark article as AI-analyzed."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"mark_ai_analyzed: disallowed schema {schema!r}")
    try:
        with engine.begin() as c:
            c.execute(
                text(f"UPDATE {schema}.articles SET ai_analyzed = TRUE, ai_analyzed_at = NOW() WHERE id = :aid"),
                {"aid": article_id},
            )
    except Exception as exc:
        logger.debug("mark_ai_analyzed: failed for article_id=%s: %s", article_id, exc)


def record_failure(engine, source_slug: str, raw: dict, error: str) -> None:
    S = _schema()
    with engine.begin() as c:
        c.execute(text(f"""
            INSERT INTO {S}.failed_ingest (source_slug, raw_payload, error)
            VALUES (:s, :r, :e)
        """), {"s": source_slug, "r": json.dumps(raw, default=str), "e": error})
    logger.warning("dead-letter: %s - %s", source_slug, error[:100])
