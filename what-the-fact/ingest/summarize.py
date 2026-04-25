"""Extractive summarization — generates headline, brief, full per story cluster.

Approach: pure Python, no LLM required. Pulls sentences from cluster articles
and selects the most representative ones.

For each cluster:
  headline  — representative title trimmed to ≤ 120 chars
  brief     — first 2 sentences from the lead article body (~1 paragraph)
  full_text — first sentence from each article body, deduplicated, joined

LLM path upgrade: replace `_summarize_extractive()` with a Bridge dispatch
call to the hub at https://api.kytranempowerment.com when AI is available.
"""
import json
import logging
import os
import re
from datetime import datetime
from sqlalchemy import text

logger = logging.getLogger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.split(text) if s.strip()]


def _summarize_extractive(titles: list[str], bodies: list[str]) -> dict:
    """Build headline, brief, full_text from article titles + bodies."""
    # Headline: longest title, truncated to 120 chars, stripping source tags
    headline = max(titles, key=len) if titles else ""
    headline = re.sub(r"\s*[\|–—]\s*[^|–—]+$", "", headline).strip()[:120]

    # Brief: first 2 sentences from the lead (most recent) article body
    lead_sentences = _split_sentences(bodies[0]) if bodies else []
    brief = " ".join(lead_sentences[:2]) or headline

    # Full: first sentence from each article body, deduplicated
    seen = set()
    para_sentences = []
    for body in bodies:
        sents = _split_sentences(body)
        if sents:
            s = sents[0]
            key = s.lower()[:60]
            if key not in seen:
                seen.add(key)
                para_sentences.append(s)

    # Split into up to 3 paragraphs of ~3 sentences each
    chunk = 3
    paras = []
    for i in range(0, min(9, len(para_sentences)), chunk):
        paras.append(" ".join(para_sentences[i : i + chunk]))
    while len(paras) < 3:
        paras.append("")
    full_text = "\n\n".join(paras[:3]).strip() or brief

    return {"headline": headline, "brief": brief, "full_text": full_text}


def summarize_cluster(engine, cluster_id: int) -> None:
    """Fetch cluster articles and upsert a summary. Non-fatal on error."""
    S = os.environ.get("WTF_SCHEMA", "wtf")
    try:
        with engine.begin() as c:
            rows = c.execute(
                text(f"""
                    SELECT a.id, a.title, a.body
                    FROM {S}.articles a
                    WHERE a.cluster_id = :cid
                    ORDER BY a.published_at DESC
                    LIMIT 10
                """),
                {"cid": cluster_id},
            ).fetchall()

        if not rows:
            return

        article_ids = [r[0] for r in rows]
        titles = [r[1] for r in rows]
        bodies = [r[2] for r in rows if r[2]]

        summary = _summarize_extractive(titles, bodies)

        with engine.begin() as c:
            c.execute(
                text(f"""
                    INSERT INTO {S}.summaries
                        (cluster_id, headline, brief, full_text, article_ids, updated_at)
                    VALUES (:cid, :h, :b, :f, :ids, now())
                    ON CONFLICT (cluster_id) DO UPDATE SET
                        headline = EXCLUDED.headline,
                        brief = EXCLUDED.brief,
                        full_text = EXCLUDED.full_text,
                        article_ids = EXCLUDED.article_ids,
                        updated_at = now()
                """),
                {
                    "cid": cluster_id,
                    "h": summary["headline"],
                    "b": summary["brief"],
                    "f": summary["full_text"],
                    "ids": json.dumps(article_ids),
                },
            )
        logger.debug("cluster %d summarized (%d articles)", cluster_id, len(article_ids))
    except Exception as exc:
        logger.warning("summarize_cluster %d failed: %s", cluster_id, exc)
