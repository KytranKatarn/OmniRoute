"""promise_tracker.py — Campaign promise extraction from WTF articles.

Scans articles tagged with MPs (wtf.article_mp_tags) looking for promise
language: "promised", "committed", "pledged", "vowed", "will introduce",
"will bring", "will pass", "will table", "will deliver". Extracts the
sentence containing the keyword and stores it as an mp_promise.

v1: keyword-based extraction only (no LLM). Sentence extraction via
regex sentence splitter. Runs weekly, processes last 90 days of articles.
Idempotent (UNIQUE on mp_id + article_id + promise_text).
"""
import logging
import re

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest.promises")

_PROMISE_PATTERNS = [
    r"\bpromised?\b",
    r"\bcommitted?\s+to\b",
    r"\bpledged?\b",
    r"\bvowed?\b",
    r"\bwill\s+introduce\b",
    r"\bwill\s+bring\s+(?:in|forward)\b",
    r"\bwill\s+pass\b",
    r"\bwill\s+table\b",
    r"\bwill\s+deliver\b",
    r"\bwill\s+ensure\b",
    r"\bwill\s+implement\b",
    r"\bwill\s+create\b",
    r"\bwill\s+fund\b",
    r"\bwill\s+build\b",
    r"\bwill\s+invest\b",
    r"\bcampaign\s+promise\b",
    r"\belection\s+promise\b",
]
_PROMISE_RE = re.compile("|".join(_PROMISE_PATTERNS), re.IGNORECASE)

# Sentence splitter: split on . ! ? followed by space + capital
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

_MAX_PROMISE_LEN = 500
_DAYS_BACK = 90


def _extract_promise_sentences(text_blob: str) -> list[str]:
    """Return sentences containing promise language."""
    if not text_blob:
        return []
    sentences = _SENT_SPLIT.split(text_blob)
    return [
        s.strip() for s in sentences
        if _PROMISE_RE.search(s) and 20 < len(s.strip()) < _MAX_PROMISE_LEN
    ]


def run_promise_tracker(engine) -> dict:
    """Scan MP-tagged articles for promise language and store extractions."""
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT t.mp_id, a.id AS article_id, a.title, a.url, a.published_at,
                   LEFT(a.body, 8000) AS body_excerpt
            FROM wtf.article_mp_tags t
            JOIN wtf.articles a ON a.id = t.article_id
            WHERE a.published_at > NOW() - INTERVAL '{_DAYS_BACK} days'
              AND (a.title IS NOT NULL OR a.body IS NOT NULL)
        """)).fetchall()

    logger.info("promise_tracker: scanning %d mp-article pairs", len(rows))

    inserted = 0
    skipped = 0

    for mp_id, article_id, title, url, published_at, body in rows:
        text_blob = (title or "") + " " + (body or "")
        promises = _extract_promise_sentences(text_blob)
        if not promises:
            continue

        for promise_text in promises:
            try:
                with engine.begin() as c:
                    c.execute(text("""
                        INSERT INTO parliament.mp_promises
                            (mp_id, article_id, promise_text, source_url, published_at)
                        VALUES (:mp, :art, :txt, :url, :pub)
                        ON CONFLICT (mp_id, article_id, promise_text) DO NOTHING
                    """), {
                        "mp": mp_id,
                        "art": article_id,
                        "txt": promise_text[:_MAX_PROMISE_LEN],
                        "url": url,
                        "pub": published_at,
                    })
                inserted += 1
            except Exception as exc:
                logger.debug("promise_tracker: insert failed mp=%s art=%s: %s",
                             mp_id, article_id, exc)
                skipped += 1

    logger.info("promise_tracker: inserted=%d skipped=%d", inserted, skipped)
    return {
        "articles_scanned": len(rows),
        "promises_inserted": inserted,
        "skipped": skipped,
    }
