"""bias_v2_backlog_worker.py — DistilBERT zero-shot bias scoring backlog.

Task #2136. Reads articles with bias_v2_score IS NULL, runs the zero-shot
classifier (CPU on outpost-us), writes back bias_v2_* columns + ensemble.

Default OFF. Set WTF_BIAS_V2_ENABLED=true to run.

Ensemble formula: 0.5 * bias_score (LLM tier-1) + 0.5 * bias_v2_score.
Band derived from the existing _band_for() in `bias.py`.

Bypasses the priority filter — clears the historical backlog. Forward
ingestion can later wire bias_v2 into orchestrator.process_article().
"""
from __future__ import annotations

import logging
import os
import time

from sqlalchemy import text

from . import bias as bias_v1  # for _band_for thresholds
from . import bias_v2

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_BIAS_V2_ENABLED", "false").lower() == "true"
_BATCH_SIZE = int(os.environ.get("WTF_BIAS_V2_BATCH_SIZE", "50"))
_DISPATCH_SLEEP_SEC = float(os.environ.get("WTF_BIAS_V2_DISPATCH_SLEEP_SEC", "1"))
_MAX_RUNS_PER_NIGHT = int(os.environ.get("WTF_BIAS_V2_MAX_RUNS_PER_NIGHT", "500"))
_MAX_AGE_DAYS = int(os.environ.get("WTF_BIAS_V2_MAX_AGE_DAYS", "90"))

_ALLOWED_SCHEMAS = frozenset({"wtf"})


def _fetch_batch(engine, schema: str, limit: int) -> list[dict]:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_batch: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(
            text(f"""
                SELECT a.id, a.title, a.body,
                       bs.score AS bias_score_v1,
                       -- ⚠️ MUST travel with the score. The heuristic writes a REAL
                       -- row with score = 0.0 when it finds no trigger terms, so the
                       -- score alone cannot distinguish "measured centrist" from
                       -- "measured nothing". signal_detected is that distinction
                       -- (migration 063 / #3012) and _persist blends on it.
                       bs.signal_detected AS bias_signal_v1
                FROM {schema}.articles a
                LEFT JOIN {schema}.bias_scores bs ON bs.article_id = a.id
                WHERE a.bias_v2_score IS NULL
                  AND a.published_at > NOW() - make_interval(days => :max_age_days)
                ORDER BY a.ingested_at DESC NULLS LAST
                LIMIT :limit
            """),
            {"max_age_days": _MAX_AGE_DAYS, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def blend_ensemble(
    v2_score: float, tier1_score: float | None, tier1_signal: bool | None
) -> float:
    """Combine the ML score with the heuristic — but ONLY when the heuristic
    actually measured something. Pure; no DB, no I/O.

    ⚠️ A NO-SIGNAL HEURISTIC ROW IS AN ABSENCE, NOT A CENTRIST READING.

    `bias.score_bias()` writes a real row with score = 0.0 when it matched no
    trigger terms. The old guard was `if tier1_score is None`, so that 0.0 was
    not None and got averaged in at full 50% weight:

        0.5 * 0.0  +  0.5 * (-0.256)  =  -0.128   ->  band "center"

    while the very same page rendered "NO SIGNAL DETECTED (not a centrist
    finding)" underneath. The header and the breakdown contradicted each other
    because one read signal_detected and the other did not.

    Because the absent value is always 0.0 and the blend is a mean, the error is
    not random — it is a systematic pull TOWARD CENTER, halving every real lean.
    Measured over the 120,918 articles carrying both scores: 84,809 had a
    no-signal heuristic row and 41,203 of those (48.6%) sit in the WRONG BAND.
    34,732 are published "center" while the ML score says center-right; 5,460
    "center" that are center-left. 97.5% of the shifts are a real lean being
    flattened into center — on a site whose product is detecting exactly that.

    This is the same defect class as #3012 (no-signal rows averaged into the
    outlet mean) and #3026 (wire copy averaged into the outlet mean), one layer
    up: an absence given the numeric weight of a measurement.

    ⚠️ `tier1_signal is None` means the COLUMN was NULL — a row written before
    migration 063, where we cannot tell signal from absence. Those are treated
    as trustworthy (blended) rather than discarded, so this fix never silently
    throws away a heuristic reading it merely cannot classify. Only an explicit
    False is excluded.
    """
    if tier1_score is None or tier1_signal is False:
        return float(v2_score)
    return round(0.5 * float(tier1_score) + 0.5 * float(v2_score), 3)


def _persist(
    engine,
    schema: str,
    article_id: int,
    v2: dict,
    tier1_score: float | None,
    tier1_signal: bool | None = None,
) -> None:
    """Write bias_v2_* + ensemble columns, log audit_trail event."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_persist: disallowed schema {schema!r}")

    ensemble_score = blend_ensemble(v2["score"], tier1_score, tier1_signal)
    ensemble_band = bias_v1._band_for(ensemble_score)

    with engine.begin() as c:
        c.execute(
            text(f"""
                UPDATE {schema}.articles
                SET bias_v2_score        = :v2_score,
                    bias_v2_label        = :v2_label,
                    bias_v2_confidence   = :v2_conf,
                    bias_v2_model        = :v2_model,
                    bias_v2_computed_at  = NOW(),
                    bias_ensemble_score  = :ens_score,
                    bias_ensemble_band   = :ens_band
                WHERE id = :article_id
            """),
            {
                "article_id": article_id,
                "v2_score": v2["score"],
                "v2_label": v2["label"],
                "v2_conf": v2["confidence"],
                "v2_model": v2["model"],
                "ens_score": ensemble_score,
                "ens_band": ensemble_band,
            },
        )
        # audit_trail — keep tech/transparency happy
        c.execute(
            text(f"""
                INSERT INTO {schema}.audit_trail (article_id, event_type, payload, created_at)
                VALUES (:article_id, 'bias_v2_scored', CAST(:payload AS JSONB), NOW())
            """),
            {
                "article_id": article_id,
                "payload": _json({
                    "model": v2["model"],
                    "label": v2["label"],
                    "score": v2["score"],
                    "confidence": v2["confidence"],
                    "ensemble_score": ensemble_score,
                    "ensemble_band": ensemble_band,
                }),
            },
        )


def _json(d: dict) -> str:
    import json
    return json.dumps(d, separators=(",", ":"))


def run_backlog(engine, schema: str = "wtf") -> dict:
    """Process one shift of DistilBERT backlog. Returns counters."""
    if not _ENABLED:
        return {"processed": 0, "failed": 0, "stopped": "disabled"}

    processed = 0
    failed = 0
    while processed + failed < _MAX_RUNS_PER_NIGHT:
        batch = _fetch_batch(engine, schema, _BATCH_SIZE)
        if not batch:
            return {"processed": processed, "failed": failed, "stopped": "no_backlog"}

        for article in batch:
            if processed + failed >= _MAX_RUNS_PER_NIGHT:
                return {"processed": processed, "failed": failed, "stopped": "max_runs"}

            try:
                v2 = bias_v2.score_v2(article["title"] or "", article["body"] or "")
            except Exception as exc:
                failed += 1
                logger.exception("[bias_v2] article=%s classifier error: %s", article["id"], exc)
                continue

            try:
                _persist(
                    engine,
                    schema,
                    article["id"],
                    v2,
                    article.get("bias_score_v1"),
                    article.get("bias_signal_v1"),
                )
                processed += 1
                if processed % 25 == 0:
                    logger.info("[bias_v2] processed=%d failed=%d", processed, failed)
            except Exception as exc:
                failed += 1
                logger.exception("[bias_v2] article=%s persist failed: %s", article["id"], exc)

            time.sleep(_DISPATCH_SLEEP_SEC)

    return {"processed": processed, "failed": failed, "stopped": "max_runs"}
