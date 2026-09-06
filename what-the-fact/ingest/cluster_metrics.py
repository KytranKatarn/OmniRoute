"""Cluster-level metrics: Coverage Gap Score (#3010), Certainty Labeling (#3012),
Blindspot lean imbalance, and Divergence score (task #6524).

Coverage Gap Score  = distinct_sources_in_cluster / total_active_sources  (0.0–1.0)
Certainty Label     = established | developing | contested
Blindspot side      = 'L' | 'R' | NULL — see _blindspot_side()'s docstring.
Divergence score    = 0-100 — see _divergence_score()'s docstring.

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
# Rows per write transaction. Bounds transaction LIFETIME, which is the whole
# point: a 27-minute open transaction blocked DDL and stalled autovacuum.
_WRITE_BATCH = int(os.environ.get("WTF_CLUSTER_METRICS_WRITE_BATCH", "500"))

# Ported verbatim from design-handoff/wtf-blindspot.js — do not retune without
# also updating that file's comment, they must describe the same rule.
_BLINDSPOT_MIN_TOTAL = 4    # fewer articles than this, no pattern to call
_BLINDSPOT_MIN_SIDES = 4    # partisan (L+R) coverage needed before a side is judged
_BLINDSPOT_MINOR_MAX = 0.25 # quiet side must be <= 25% of the two-sided coverage
_BLINDSPOT_MIN_DIFF = 3     # and at least this many articles behind in absolute terms


def _blindspot_side(l_count: int, c_count: int, r_count: int):
    """L/R when one side is a lean-imbalance blindspot, else None.

    A political-lean coverage imbalance, distinct from coverage_gap_score
    (which measures outlet-count silence, not which side covered a story).
    An 8-to-2 split calls; a 5-to-4 split doesn't — see the module-level
    threshold constants for the exact rule, ported from the mockup.
    """
    total = l_count + c_count + r_count
    if total < _BLINDSPOT_MIN_TOTAL:
        return None
    sides = l_count + r_count
    if sides < _BLINDSPOT_MIN_SIDES:
        return None
    minor = min(l_count, r_count)
    diff = abs(l_count - r_count)
    if sides and minor / sides <= _BLINDSPOT_MINOR_MAX and diff >= _BLINDSPOT_MIN_DIFF:
        return "R" if l_count > r_count else "L"
    return None


def _divergence_score(band_counts: list[int]) -> int:
    """0-100 — mean pairwise |band_index_i - band_index_j| across every article
    pair in the cluster, normalized /4*100. Ported from design-handoff/
    wtf-divergence.js's score(): `d += |idx(a)-idx(b)|` over every pair,
    `Math.round(d / n / 4 * 100)`.

    band_counts is [band0_left, band1_center_left, band2_center,
    band3_center_right, band4_right] — the same 5 bands _blindspot_side's
    docstring and migration 079/080 use (ingest/bias.py._BANDS).

    Closed-form from counts rather than enumerating article pairs: articles
    in the SAME band contribute 0 to the pairwise sum, so
        sum_{i<j} |i-j| * count_i * count_j
    over the 5 bands equals the mockup's per-article double loop, and
    total_pairs = C(total, 2) equals its `n`. Returns None (not 0) when
    fewer than 2 scored articles exist — a 1-article cluster has no pair to
    diverge, which is a different fact than "scored 0, no divergence found".
    """
    total = sum(band_counts)
    if total < 2:
        return None
    pair_sum = 0
    for i in range(5):
        for j in range(i + 1, 5):
            pair_sum += (j - i) * band_counts[i] * band_counts[j]
    total_pairs = total * (total - 1) // 2
    if total_pairs == 0:
        return None
    return round(pair_sum / total_pairs / 4 * 100)


def compute_cluster_metrics(engine) -> dict:
    """Recompute source_count, coverage_gap_score, certainty_label for all clusters.

    Three phases, deliberately separated so no lock is held across the pass:
      1. READ  — aggregate per cluster, in its own short transaction.
      2. COMPUTE — pure Python, NO connection held.
      3. WRITE — executemany in batches of _WRITE_BATCH, each its own txn.

    ⚠️ This docstring used to claim "2. Bulk UPDATE" while the code ran one
    round-trip UPDATE per cluster inside a single transaction that also held the
    read locks. It was never bulk. Now it is.
    """
    S = os.environ.get("WTF_SCHEMA", "wtf")
    updated = skipped = 0
    try:
        # ── PHASE 1: READ, in its own SHORT transaction ──────────────────────
        #
        # ⚠️ This whole function used to be ONE `engine.begin()` wrapping the
        # read, the per-cluster Python compute AND every UPDATE. The SELECT
        # below touches articles + fact_checks, so that transaction held
        # AccessShareLock on both for the entire pass over 13,705+ clusters.
        #
        # Measured 2026-08-31: a connection from this path sat `idle in
        # transaction` for 27m26s, which
        #   • blocked ALL DDL on fact_checks (migration 062 failed 25 times), and
        #   • prevented autovacuum reclaiming dead tuples on three hot tables
        #     for the duration, so they bloat.
        # It had to be pg_terminate_backend'd to let a migration land.
        #
        # The docstring already claimed "2. Bulk UPDATE" — it was never bulk.
        # Now it is: read, release, compute unconnected, write in bounded batches.
        with engine.connect() as c:
            # Total active sources for normalising coverage gap
            total_sources = c.execute(
                text(f"SELECT COUNT(*) FROM {S}.sources")
            ).scalar() or 1

            # ⚠️ TWO separate CTEs, not one query with both LEFT JOINs. fact_checks
            # is 1:many per article (fc_total counts multiple checks) while
            # bias_scores is 1:1 (UNIQUE article_id) — joining both off the same
            # articles row in one SELECT fans the 1:1 bias_scores value out once
            # per fact_checks row on that article, overcounting lean_*_count by
            # that article's fact-check count. Aggregating each relationship in
            # its own CTE first, then joining the two ALREADY-AGGREGATED (one row
            # per cluster) results, avoids the fan-out entirely.
            rows = c.execute(
                text(f"""
                    WITH fc_agg AS (
                        SELECT
                            a.cluster_id,
                            COUNT(DISTINCT a.source_id)                         AS source_count,
                            COUNT(fc.id)                                        AS fc_total,
                            COUNT(fc.id) FILTER (
                                WHERE fc.verdict IN ('false','disputed')
                            )                                                   AS fc_contested,
                            MIN(a.published_at)                                 AS earliest,
                            MAX(a.published_at)                                 AS latest
                        FROM {S}.articles a
                        LEFT JOIN {S}.fact_checks fc ON fc.article_id = a.id
                        WHERE a.cluster_id IS NOT NULL
                          AND a.suppressed_reason IS NULL
                        GROUP BY a.cluster_id
                    ),
                    -- L/C/R bucketed straight from bias_scores.score, at the SAME
                    -- -0.15 / 0.25 boundaries as ingest/bias.py's _BANDS (left+
                    -- center-left vs center vs center-right+right — a distinct
                    -- axis from coverage_gap_score, which counts outlets not
                    -- lean). Literals, not an imported constant: SQL can't call
                    -- a Python function per row without a round trip per
                    -- article. If _BANDS' -0.15/0.25 thresholds ever move, these
                    -- two literals must move with them — same acknowledged risk
                    -- as migration 078's verdict-enum mirror.
                    --
                    -- band0..4 (added task #6524 divergence score) are the SAME
                    -- 5 bands split back out to their individual boundaries
                    -- (-0.55/-0.15/0.25/0.65) instead of folded into l/c/r —
                    -- _divergence_score() needs the raw 5 counts, l/c/r alone
                    -- can't reconstruct them. lean_l/c/r_count stay UNCHANGED
                    -- (already shipped, /blindspot and /news/archive read them).
                    lean_agg AS (
                        SELECT
                            a.cluster_id,
                            COUNT(*) FILTER (WHERE bs.score < -0.15)             AS lean_l_count,
                            COUNT(*) FILTER (
                                WHERE bs.score >= -0.15 AND bs.score < 0.25
                            )                                                   AS lean_c_count,
                            COUNT(*) FILTER (WHERE bs.score >= 0.25)            AS lean_r_count,
                            COUNT(*) FILTER (WHERE bs.score < -0.55)            AS band0_count,
                            COUNT(*) FILTER (
                                WHERE bs.score >= -0.55 AND bs.score < -0.15
                            )                                                   AS band1_count,
                            COUNT(*) FILTER (
                                WHERE bs.score >= 0.25 AND bs.score < 0.65
                            )                                                   AS band3_count,
                            COUNT(*) FILTER (WHERE bs.score >= 0.65)            AS band4_count
                        FROM {S}.articles a
                        JOIN {S}.bias_scores bs ON bs.article_id = a.id
                        WHERE a.cluster_id IS NOT NULL
                          AND a.suppressed_reason IS NULL
                        GROUP BY a.cluster_id
                    )
                    SELECT
                        fc_agg.cluster_id, fc_agg.source_count, fc_agg.fc_total,
                        fc_agg.fc_contested, fc_agg.earliest, fc_agg.latest,
                        COALESCE(lean_agg.lean_l_count, 0) AS lean_l_count,
                        COALESCE(lean_agg.lean_c_count, 0) AS lean_c_count,
                        COALESCE(lean_agg.lean_r_count, 0) AS lean_r_count,
                        COALESCE(lean_agg.band0_count, 0) AS band0_count,
                        COALESCE(lean_agg.band1_count, 0) AS band1_count,
                        COALESCE(lean_agg.band3_count, 0) AS band3_count,
                        COALESCE(lean_agg.band4_count, 0) AS band4_count
                    FROM fc_agg
                    LEFT JOIN lean_agg ON lean_agg.cluster_id = fc_agg.cluster_id
                """)
            ).fetchall()

        # ── PHASE 2: COMPUTE with NO connection held ─────────────────────────
        # Pure Python. The read transaction above has already been released, so
        # nothing is locked while this runs.
        payload = []
        for row in rows:
            cid         = row[0]
            src_count   = int(row[1])
            fc_total    = int(row[2])
            fc_contested = int(row[3])
            earliest    = row[4]
            latest      = row[5]
            lean_l      = int(row[6])
            lean_c      = int(row[7])
            lean_r      = int(row[8])
            band0       = int(row[9])
            band1       = int(row[10])
            band3       = int(row[11])
            band4       = int(row[12])

            gap_score = round(src_count / total_sources, 4)
            blindspot_side = _blindspot_side(lean_l, lean_c, lean_r)
            divergence_score = _divergence_score([band0, band1, lean_c, band3, band4])

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

            payload.append({
                "sc": src_count, "gs": gap_score, "cl": certainty, "cid": cid,
                "ll": lean_l, "lc": lean_c, "lr": lean_r, "bs": blindspot_side,
                "b0": band0, "b1": band1, "b3": band3, "b4": band4,
                "ds": divergence_score,
            })

        # ── PHASE 3: WRITE in BOUNDED batches ────────────────────────────────
        # One executemany per batch, each its own short transaction. Transaction
        # lifetime is now bounded by _WRITE_BATCH rows instead of by the whole
        # cluster population, so no lock is held across the full pass.
        upd = text(f"""
            UPDATE {S}.story_clusters
            SET source_count       = :sc,
                coverage_gap_score = :gs,
                certainty_label    = :cl,
                lean_l_count       = :ll,
                lean_c_count       = :lc,
                lean_r_count       = :lr,
                blindspot_side     = :bs,
                band0_count        = :b0,
                band1_count        = :b1,
                band3_count        = :b3,
                band4_count        = :b4,
                divergence_score   = :ds,
                metrics_updated_at = NOW()
            WHERE id = :cid
        """)
        for i in range(0, len(payload), _WRITE_BATCH):
            batch = payload[i:i + _WRITE_BATCH]
            with engine.begin() as wc:
                wc.execute(upd, batch)
            updated += len(batch)

        logger.info(
            "cluster_metrics: updated=%d skipped=%d total_sources=%d",
            updated, skipped, total_sources,
        )
    except Exception as exc:
        logger.warning("cluster_metrics: failed: %s", exc)
    return {"updated": updated, "skipped": skipped}
