"""backfill_partner_relevance.py — retro-gate existing GoogleFCT matches (#2137).

The partner worker used to persist EVERY title-matched FCTAPI result, so the
live table holds name-collision false positives (a Snopes review of "Trump's
Easter message" attached to a Strait-of-Hormuz article). This one-off re-runs
the two-stage relevance gate over the already-persisted real matches and deletes
the ones that fail — fixing the live data. Sentinel rows ('GoogleFCT:none') are
never touched.

Dry-run by default. Run in the wtf-ingest container:
    python -c "from sqlalchemy import create_engine; import os; \
        from ingest.backfill_partner_relevance import run_backfill; \
        print(run_backfill(create_engine(os.environ['WTF_DATABASE_URL']), apply=False))"
Then re-run with apply=True.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from .factcheck_partner_worker import (
    _RELEVANCE_LLM,
    _distinctive_overlap_ok,
    _llm_relevant,
)

logger = logging.getLogger("wtf-ingest")

_ALLOWED_SCHEMAS = frozenset({"wtf"})


def run_backfill(engine, schema: str = "wtf", apply: bool = False,
                 limit: int = 5000) -> dict:
    """Re-score persisted GoogleFCT matches; delete the irrelevant ones.

    apply=False (default) reports counts without deleting. Returns
    {total, kept, drop_stage1, drop_stage2, deferred, deleted}.
    """
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"run_backfill: disallowed schema {schema!r}")

    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT fc.id, fc.article_id, fc.claim, fc.checker,
                   a.title, LEFT(a.body, 1500) AS body
            FROM {schema}.fact_checks fc
            JOIN {schema}.articles a ON a.id = fc.article_id
            WHERE fc.checker LIKE 'GoogleFCT:%'
              AND fc.checker != 'GoogleFCT:none'
            ORDER BY fc.id
            LIMIT :limit
        """), {"limit": limit}).mappings().all()

    kept = drop1 = drop2 = deferred = 0
    to_delete: list[int] = []

    for r in rows:
        article_text = f"{r['title'] or ''} {r['body'] or ''}"
        if not _distinctive_overlap_ok(r["claim"] or "", article_text):
            drop1 += 1
            to_delete.append(r["id"])
            continue
        if _RELEVANCE_LLM:
            verdict = _llm_relevant(r["article_id"], r["title"] or "", r["claim"] or "")
            if verdict is None:
                deferred += 1          # hub busy — leave this row for a later pass
                continue
            if not verdict:
                drop2 += 1
                to_delete.append(r["id"])
                continue
        kept += 1

    deleted = 0
    if apply and to_delete:
        with engine.begin() as c:
            # Delete in chunks to bound statement size.
            for i in range(0, len(to_delete), 500):
                chunk = to_delete[i:i + 500]
                res = c.execute(
                    text(f"DELETE FROM {schema}.fact_checks WHERE id = ANY(:ids)"),
                    {"ids": chunk},
                )
                deleted += res.rowcount or 0
        logger.info("[backfill] deleted %d irrelevant GoogleFCT rows", deleted)

    return {
        "total": len(rows),
        "kept": kept,
        "drop_stage1": drop1,
        "drop_stage2": drop2,
        "deferred": deferred,
        "deleted": deleted,
        "apply": apply,
    }
