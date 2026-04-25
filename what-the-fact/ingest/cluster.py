"""Story clustering — group articles about the same event across outlets.

Algorithm: Jaccard similarity on normalized title word sets within a 24-hour
window. No external NLP dependencies required.

Threshold 0.25 catches same-event stories while allowing different angles.
"""
import re
import logging
import os
from datetime import datetime, timedelta
from sqlalchemy import text

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = float(os.environ.get("WTF_CLUSTER_THRESHOLD", "0.25"))
CLUSTER_WINDOW_HOURS = int(os.environ.get("WTF_CLUSTER_WINDOW_HOURS", "24"))

_STOPWORDS = frozenset(
    "a an the and or but in on at to for of with is are was were be been"
    " has have had will would could should may might this that these those"
    " it its from by into about as up out do did does not no can".split()
)


def _tokens(title: str) -> frozenset:
    words = re.findall(r"[a-z]+", title.lower())
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def find_or_create_cluster(engine, article_id: int, title: str, published_at: datetime) -> int:
    """Assign article to an existing cluster or create a new one. Returns cluster_id."""
    S = os.environ.get("WTF_SCHEMA", "wtf")
    tokens = _tokens(title)
    window_start = published_at - timedelta(hours=CLUSTER_WINDOW_HOURS)
    result_cid = None

    with engine.begin() as c:
        rows = c.execute(
            text(f"""
                SELECT sc.id, sc.representative_title
                FROM {S}.story_clusters sc
                WHERE sc.latest_published_at >= :ws
                ORDER BY sc.latest_published_at DESC
                LIMIT 200
            """),
            {"ws": window_start},
        ).fetchall()

        best_id = None
        best_score = 0.0
        for row in rows:
            cand_tokens = _tokens(row[1])
            score = _jaccard(tokens, cand_tokens)
            if score > best_score:
                best_score = score
                best_id = row[0]

        if best_score >= SIMILARITY_THRESHOLD and best_id is not None:
            c.execute(
                text(f"""
                    UPDATE {S}.story_clusters
                    SET latest_published_at = GREATEST(latest_published_at, :p),
                        article_count = article_count + 1,
                        updated_at = now()
                    WHERE id = :cid
                """),
                {"p": published_at, "cid": best_id},
            )
            c.execute(
                text(f"UPDATE {S}.articles SET cluster_id = :cid WHERE id = :aid"),
                {"cid": best_id, "aid": article_id},
            )
            logger.debug(
                "article %d → cluster %d (jaccard=%.2f title=%r)",
                article_id, best_id, best_score, title[:60],
            )
            result_cid = best_id
        else:
            # No matching cluster — create one
            row = c.execute(
                text(f"""
                    INSERT INTO {S}.story_clusters
                        (representative_title, earliest_published_at, latest_published_at)
                    VALUES (:t, :p, :p)
                    RETURNING id
                """),
                {"t": title[:1024], "p": published_at},
            ).fetchone()
            cid = row[0]
            c.execute(
                text(f"UPDATE {S}.articles SET cluster_id = :cid WHERE id = :aid"),
                {"cid": cid, "aid": article_id},
            )
            logger.debug("article %d → new cluster %d title=%r", article_id, cid, title[:60])
            result_cid = cid

    # Re-summarize cluster after tx commits (non-fatal)
    if result_cid is not None:
        try:
            from ingest.summarize import summarize_cluster
            summarize_cluster(engine, result_cid)
        except Exception as exc:
            logger.warning("summarization failed for cluster %d: %s", result_cid, exc)

    return result_cid
