"""Cluster-level metrics: Coverage Gap Score (#3010) and Certainty Labeling (#3012).

Coverage Gap Score  = distinct_sources_in_cluster / total_active_sources  (0.0–1.0)
Certainty Label     = established | developing | contested

Certainty rules (evaluated in order):
  contested   — majority of fact_checks in the cluster are 'false'/'disputed'
  established — source_count >= 4 AND cluster age > 6h AND not contested
  developing  — everything else (new story, few sources, no factchecks yet)

Called from run.py after each ingest pass.
"""
import logging
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)

_CONTESTED_VERDICTS = {"false", "disputed"}
_ESTABLISHED_MIN_SOURCES = 4
_ESTABLISHED_MIN_AGE_HOURS = 6


def compute_cluster_metrics(engine) -> dict:
    """Recompute source_count, coverage_gap_score, certainty_label for all clusters.

    Runs in two queries:
      1. Aggregate source + factcheck data per cluster.
      2. Bulk UPDATE story_clusters.
    """
    S = os.environ.get("WTF_SCHEMA", "wtf")
    updated = skipped = 0
    try:
        with engine.begin() as c:
            # Total active sources for normalising coverage gap
            total_sources = c.execute(
                text(f"SELECT COUNT(*) FROM {S}.sources")
            ).scalar() or 1

            rows = c.execute(
                text(f"""
                    SELECT
                        a.cluster_id,
                        COUNT(DISTINCT a.source_id)                             AS source_count,
                        COUNT(fc.id)                                            AS fc_total,
                        COUNT(fc.id) FILTER (
                            WHERE fc.verdict IN ('false','disputed')
                        )                                                       AS fc_contested,
                        MIN(a.published_at)                                     AS earliest,
                        MAX(a.published_at)                                     AS latest
                    FROM {S}.articles a
                    LEFT JOIN {S}.fact_checks fc ON fc.article_id = a.id
                    WHERE a.cluster_id IS NOT NULL
                    GROUP BY a.cluster_id
                """)
            ).fetchall()

            for row in rows:
                cid         = row[0]
                src_count   = int(row[1])
                fc_total    = int(row[2])
                fc_contested = int(row[3])
                earliest    = row[4]
                latest      = row[5]

                gap_score = round(src_count / total_sources, 4)

                # Age of cluster in hours (time since first article)
                age_hours = 0.0
                if earliest and latest:
                    age_hours = (latest - earliest).total_seconds() / 3600

                # Certainty label
                if fc_total > 0 and fc_contested / fc_total > 0.5:
                    certainty = "contested"
                elif src_count >= _ESTABLISHED_MIN_SOURCES and age_hours >= _ESTABLISHED_MIN_AGE_HOURS:
                    certainty = "established"
                else:
                    certainty = "developing"

                c.execute(
                    text(f"""
                        UPDATE {S}.story_clusters
                        SET source_count       = :sc,
                            coverage_gap_score = :gs,
                            certainty_label    = :cl,
                            metrics_updated_at = NOW()
                        WHERE id = :cid
                    """),
                    {"sc": src_count, "gs": gap_score, "cl": certainty, "cid": cid},
                )
                updated += 1

        logger.info(
            "cluster_metrics: updated=%d skipped=%d total_sources=%d",
            updated, skipped, total_sources,
        )
    except Exception as exc:
        logger.warning("cluster_metrics: failed: %s", exc)
    return {"updated": updated, "skipped": skipped}
