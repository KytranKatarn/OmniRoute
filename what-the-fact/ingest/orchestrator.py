"""orchestrator.py — F.A.C.T. priority picker for AI deep-analysis."""
import logging

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

_ALLOWED_SCHEMAS = frozenset({"wtf"})

BREAKING_KEYWORDS = [
    "breaking",
    "urgent",
    "alert",
    "emergency",
    "crisis",
    "shooting",
    "death",
    "killed",
    "explosion",
    "resign",
]
MAX_PRIORITY_PER_CYCLE = 20  # bumped from 10 after source count doubled (15 → 31)


def score_priority(title: str, heuristic_bias_score: float, cross_source_count: int) -> int:
    """Return an integer priority score (0 = not priority, higher = more important)."""
    score = 0
    if cross_source_count >= 3:
        score += 3
    if abs(heuristic_bias_score) > 0.5:
        score += 2
    title_lower = title.lower()
    if any(kw in title_lower for kw in BREAKING_KEYWORDS):
        score += 1
    return score


def pick_priority_articles(engine, schema: str, batch_article_ids: list[int]) -> list[int]:
    """Given this cycle's inserted article IDs, return up to MAX_PRIORITY_PER_CYCLE for AI analysis.

    Scores each article using F.A.C.T. priority logic:
    - 3 pts: same story in 3+ outlets (cross_source_count)
    - 2 pts: heuristic bias score > 0.5
    - 1 pt: breaking keyword in title
    Returns top MAX_PRIORITY_PER_CYCLE by score (minimum score 1 to qualify).
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"pick_priority_articles: disallowed schema {schema!r}")

    if not batch_article_ids:
        return []

    try:
        with engine.connect() as c:
            rows = c.execute(
                text(f"""
                    SELECT a.id, a.title,
                           bs.score AS heuristic_score,
                           (
                               SELECT COUNT(DISTINCT a2.source_id)
                               FROM {schema}.articles a2
                               WHERE a2.cluster_id IS NOT NULL
                                 AND a2.cluster_id = a.cluster_id
                                 AND a2.id != a.id
                           ) AS cross_source_count
                    FROM {schema}.articles a
                    LEFT JOIN {schema}.bias_scores bs ON bs.article_id = a.id
                    WHERE a.id = ANY(:ids) AND a.ai_analyzed = FALSE
                """),
                {"ids": batch_article_ids},
            ).fetchall()
    except Exception as exc:
        logger.warning("orchestrator: DB query failed: %s", exc)
        return []

    scored = []
    for row in rows:
        p = score_priority(
            row.title or "",
            float(row.heuristic_score or 0.0),
            int(row.cross_source_count or 0),
        )
        if p >= 1:
            scored.append((p, row.id))

    scored.sort(reverse=True)
    return [article_id for _, article_id in scored[:MAX_PRIORITY_PER_CYCLE]]
