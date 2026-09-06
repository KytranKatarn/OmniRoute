"""dispute_backlog_worker.py — fill /divergence's "checkable fact in dispute" gap.

Reads qualifying clusters missing a wtf.cluster_disputes row, builds a
multi-article coverage digest, dispatches the wtf-hub 'dispute' task,
inserts result into wtf.cluster_disputes. Default OFF —
set WTF_DISPUTE_BACKLOG_ENABLED=true.

Same shape as factcheck_backlog_worker.py, with one deliberate difference:
no tier_router two-tier gate. factcheck's Tier 1 answers a cheap yes/no
("does this article have >=3 claims") before paying for Tier 2. There is no
equivalent cheap pre-filter for "does this cluster have a checkable dispute"
— the qualification gate here (article_count >= 6, spans both L and R lean)
is pure SQL/arithmetic, already free, so every qualifying cluster goes
straight to the one real LLM call.

Distinct storage from factcheck_backlog_worker: this fills
wtf.cluster_disputes (a NEW, separate table+vocabulary — contested/
developing/established, answering "has this dispute been resolved by a
document") not wtf.fact_checks (verified/mostly_true/mixed/disputed/
unverifiable/descriptive_reporting, answering "is this claim true"). Do not
conflate the two enums or the two tables.
"""
import logging
import os
import time

from sqlalchemy import text

from . import ai_dispatcher

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_DISPUTE_BACKLOG_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_DISPUTE_BACKLOG_BATCH_SIZE", "15"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_DISPUTE_BACKLOG_DISPATCH_SLEEP_SEC", "5"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_DISPUTE_BACKLOG_MAX_RUNS_PER_NIGHT", "100"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})

# Same qualification gate as the mockup (design-handoff/wtf-divergence.js):
# arts.length >= 6 && L.length && R.length. L/R here reuse the SAME band
# split as _blindspot_side (band index <2 = L, >2 = R) — band0+band1 vs
# band3+band4, i.e. lean_l_count/lean_r_count already precomputed by
# cluster_metrics.py, not re-derived here.
_MIN_ARTICLES = 6

_VALID_VERDICTS = frozenset({"contested", "developing", "established"})


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT sc.id, sc.representative_title, sc.article_count,
                       sc.lean_l_count, sc.lean_r_count
                FROM {schema}.story_clusters sc
                WHERE sc.article_count >= :min_articles
                  AND sc.lean_l_count > 0
                  AND sc.lean_r_count > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM {schema}.cluster_disputes cd
                      WHERE cd.cluster_id = sc.id
                  )
                ORDER BY sc.latest_published_at DESC NULLS LAST
                LIMIT :limit
            """),
            {"min_articles": _MIN_ARTICLES, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def _fetch_digest_articles(engine, schema: str, cluster_id: int) -> list[dict]:
    """Up to 2 representative articles per side (L/R), newest first — enough
    spread for V.E.R.I.F.Y. to see the disagreement without exceeding the
    hub route's 3000-char body cap once labeled and joined."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_digest_articles: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT a.title, s.name AS source_name, bs.score
                FROM {schema}.articles a
                JOIN {schema}.sources s ON s.id = a.source_id
                JOIN {schema}.bias_scores bs ON bs.article_id = a.id
                WHERE a.cluster_id = :cid
                ORDER BY a.published_at DESC
            """),
            {"cid": cluster_id},
        ).mappings().all()
    return [dict(r) for r in rows]


def _band_label(score: float) -> str:
    """Same 5-band thresholds as ingest/bias.py._BANDS — literal here for the
    same reason cluster_metrics.py's SQL carries its own literal copy: no
    per-row Python round trip. If _BANDS ever moves, this moves with it."""
    if score < -0.55:
        return "LEFT"
    if score < -0.15:
        return "CENTER-LEFT"
    if score < 0.25:
        return "CENTER"
    if score < 0.65:
        return "CENTER-RIGHT"
    return "RIGHT"


def _build_digest(articles: list[dict], max_per_side: int = 2) -> str:
    """Labeled excerpt digest for the dispute prompt — 2 from the left side of
    the spectrum, 2 from the right, so V.E.R.I.F.Y. sees the actual framing
    gap rather than one article's text."""
    left = [a for a in articles if a["score"] < -0.15][:max_per_side]
    right = [a for a in articles if a["score"] >= 0.25][:max_per_side]
    lines = []
    for a in left + right:
        lines.append(f"[{_band_label(a['score'])}] {a['source_name']}: {a['title']}")
    return "\n".join(lines)


def _persist(engine, schema: str, cluster_id: int, result: dict) -> None:
    """Persist V.E.R.I.F.Y.'s dispute finding. disputed_point NULL is a real,
    valid answer ("disagreement is on tone, not a checkable point") — the row
    is still written so the NOT EXISTS filter above doesn't re-fetch it."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")
    verdict = result.get("verdict")
    if verdict not in _VALID_VERDICTS:
        verdict = None
    disputed_point = result.get("disputed_point")
    if not isinstance(disputed_point, str) or not disputed_point.strip():
        disputed_point = None
    is_opinion = bool(result.get("is_opinion"))
    # Both verdict and is_opinion are properties OF a disputed point — neither
    # means anything without one. Measured live (2026-09-06, first real batch):
    # the model returned is_opinion=true with NO disputed_point on a routine
    # health advisory and a weather forecast (neither a real dispute at all),
    # and separately returned a non-null verdict with no disputed_point on
    # another cluster — both are nonsensical combinations this must not persist.
    if disputed_point is None:
        verdict = None
        is_opinion = False
    # is_opinion clusters are never scored — no document settles a forecast,
    # matching the mockup's OPINION lookup (verdict always null there).
    elif is_opinion:
        verdict = None
    confidence = result.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None

    with engine.begin() as c:
        c.execute(
            text(f"""
                INSERT INTO {schema}.cluster_disputes
                    (cluster_id, disputed_point, verdict, is_opinion, confidence, checker)
                VALUES (:cid, :point, :verdict, :opinion, :conf, 'V.E.R.I.F.Y.')
                ON CONFLICT (cluster_id) DO UPDATE SET
                    disputed_point = EXCLUDED.disputed_point,
                    verdict        = EXCLUDED.verdict,
                    is_opinion     = EXCLUDED.is_opinion,
                    confidence     = EXCLUDED.confidence,
                    generated_at   = NOW()
            """),
            {
                "cid": cluster_id,
                "point": disputed_point,
                "verdict": verdict,
                "opinion": is_opinion,
                "conf": confidence,
            },
        )


def run_backlog(engine, schema: str = "wtf") -> dict:
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "stopped": "disabled"}

    processed = 0
    rate_limited = 0
    failed = 0
    while processed + rate_limited + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "rate_limited": rate_limited,
                    "failed": failed, "stopped": "no_backlog"}

        for cluster in batch:
            if processed + rate_limited + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "rate_limited": rate_limited,
                        "failed": failed, "stopped": "max_runs"}

            articles = _fetch_digest_articles(engine, schema, cluster["id"])
            digest = _build_digest(articles)
            if not digest:
                # Precomputed lean counts said L>0 and R>0, but a race (a
                # re-cluster between the two queries) left nothing to show —
                # skip this cycle rather than dispatch an empty prompt.
                failed += 1
                continue

            outcome = ai_dispatcher.analyze_with_status(
                task="dispute",
                article_id=cluster["id"],  # cluster id, not an article id — see routes.py's comment
                title=cluster["representative_title"] or "",
                body=digest,
            )
            status = outcome["status"]

            if status == "rate_limited":
                rate_limited += 1
            elif status == "failed":
                failed += 1
                logger.warning("[dispute_backlog] cluster=%s dispatch failed", cluster["id"])
            else:
                try:
                    _persist(engine, schema, cluster["id"], outcome["result"] or {})
                    processed += 1
                    logger.info("[dispute_backlog] cluster=%s persisted", cluster["id"])
                except Exception as exc:
                    failed += 1
                    logger.exception("[dispute_backlog] cluster=%s persist failed: %s", cluster["id"], exc)
            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "rate_limited": rate_limited,
            "failed": failed, "stopped": "max_runs"}
