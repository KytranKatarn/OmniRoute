"""Rolling aggregate outlet bias scores — recomputed after each ingest pass.

Aggregates the last 30 days of article bias_scores per source and writes
to wtf.outlet_bias_scores (one row per source, upserted each run).
"""
import logging
import os
from sqlalchemy import text

logger = logging.getLogger(__name__)
WINDOW_DAYS = int(os.environ.get("WTF_OUTLET_BIAS_WINDOW_DAYS", "30"))

_BANDS = [
    (-0.6, "left"),
    (-0.2, "center-left"),
    (0.2, "center"),
    (0.6, "center-right"),
    (1.01, "right"),
]


def _band(score: float) -> str:
    for threshold, name in _BANDS:
        if score < threshold:
            return name
    return "right"


def recompute_outlet_bias(engine) -> dict:
    """Recompute rolling outlet bias for all sources. Returns stats dict."""
    S = os.environ.get("WTF_SCHEMA", "wtf")
    updated = 0
    try:
        with engine.begin() as c:
            rows = c.execute(
                text(f"""
                    -- ⚠️ signal_detected IS NOT FALSE, not a bare AVG.
                    -- A row where the detector matched NOTHING carries score 0.0
                    -- for schema reasons only; averaging it in drags the outlet
                    -- toward centre and UNDER-REPORTS its lean. Measured: removing
                    -- these roughly DOUBLED the measured lean at every major outlet
                    -- (CTV News -0.013 -> -0.031, 57.7% of its rows were no-signal).
                    -- These averages roll up into Media-Sources / Owners /
                    -- Journalists / CRTC, so the distortion reaches named orgs.
                    -- `IS NOT FALSE` (not `= true`) so legacy NULLs still count.
                    SELECT a.source_id,
                           COUNT(*)                    AS n,
                           AVG(b.score)                AS avg_score
                    FROM {S}.articles a
                    JOIN {S}.bias_scores b ON b.article_id = a.id
                    WHERE a.ingested_at >= now() - INTERVAL '{WINDOW_DAYS} days'
                      AND b.signal_detected IS NOT FALSE
                      -- Wire/press-release copy carries no partisan lean to
                      -- average. Same family as signal_detected above: an
                      -- absence of signal, not a measurement of centrism.
                      -- Measured on Financial Post, 30d: 43% of its scored
                      -- articles were wire at avg -0.023, against journalism
                      -- at -0.191 — pulling the PUBLISHED figure to -0.107,
                      -- the midpoint of two unrelated populations. That is
                      -- the difference between reporting the outlet as
                      -- "center" and "center-left". Migration 065.
                      AND a.content_type <> 'wire'
                    GROUP BY a.source_id
                """)
            ).fetchall()

            for row in rows:
                sid, n, avg = row[0], int(row[1]), float(row[2])
                band = _band(avg)
                avg_r = round(avg, 3)
                # Snapshot today's value for drift tracking — one row per source per day
                c.execute(
                    text(f"""
                        INSERT INTO {S}.outlet_bias_history
                            (source_id, avg_score, band, article_count, window_days)
                        VALUES (:sid, :avg, :band, :n, :wd)
                        ON CONFLICT (source_id, snapshot_date) DO NOTHING
                    """),
                    {"sid": sid, "avg": avg_r, "band": band, "n": n, "wd": WINDOW_DAYS},
                )
                c.execute(
                    text(f"""
                        INSERT INTO {S}.outlet_bias_scores
                            (source_id, article_count, avg_score, band, window_days, computed_at)
                        VALUES (:sid, :n, :avg, :band, :wd, now())
                        ON CONFLICT (source_id) DO UPDATE SET
                            article_count = EXCLUDED.article_count,
                            avg_score     = EXCLUDED.avg_score,
                            band          = EXCLUDED.band,
                            computed_at   = EXCLUDED.computed_at
                    """),
                    {"sid": sid, "n": n, "avg": avg_r, "band": band, "wd": WINDOW_DAYS},
                )
                updated += 1
        logger.info("outlet_bias: updated %d sources", updated)
    except Exception as exc:
        logger.warning("outlet_bias recompute failed: %s", exc)
    return {"updated": updated}
