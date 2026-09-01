-- 067: recompute the bias ensemble for articles whose heuristic measured NOTHING.
--
-- WHY
-- ---
-- `bias_v2_backlog_worker._persist` blended the heuristic and the ML score with:
--
--     if tier1_score is None:  ensemble = v2
--     else:                    ensemble = 0.5*tier1 + 0.5*v2
--
-- But `bias.score_bias()` writes a REAL row with score = 0.0 when it matched no
-- trigger terms. That 0.0 is not None, so it was averaged in at full weight:
--
--     0.5 * 0.0  +  0.5 * (-0.256)  =  -0.128   ->  band "center"
--
-- while the same article page rendered "NO SIGNAL DETECTED (not a centrist
-- finding)" directly underneath. Header and breakdown disagreed because one
-- consulted signal_detected and the other did not.
--
-- Because the absent value is always 0.0 and the blend is a mean, the error is
-- SYSTEMATIC, not random: every real lean was halved toward centre.
--
-- MEASURED (2026-09-01, before this migration)
-- --------------------------------------------
--   articles with both a v2 score and a heuristic row      120,918
--   ...of which the heuristic detected NO signal            84,809
--   ...of those, in the WRONG BAND                          41,203  (48.6%)
--
--   published "center" -> actually center-right             34,732
--   published "center" -> actually center-left               5,460
--   other shifts                                             1,011
--
-- 97.5% of the corrections are a real lean being un-flattened out of "center",
-- on a site whose entire product is detecting exactly that.
--
-- WHAT THIS DOES
-- --------------
-- For articles where the heuristic explicitly reported NO signal, the ensemble
-- becomes the ML score alone — the same thing the fixed code will now write.
--
-- ⚠️ SCOPED TO `signal_detected IS FALSE`. A NULL means the column predates
-- migration 063 and we cannot tell signal from absence; those rows are LEFT
-- ALONE rather than assumed absent, so this never discards a heuristic reading
-- it merely cannot classify. A row with signal_detected = TRUE and score 0.0 is
-- a genuine centrist FINDING and must keep diluting — that is a measurement.
--
-- Band thresholds are `_BANDS` in ingest/bias.py, kept byte-identical here:
--     < -0.55 left | < -0.15 center-left | < 0.25 center | < 0.65 center-right
--     otherwise right
--
-- IDEMPOTENT: re-running rewrites the same values and reports 0 changed rows.

BEGIN;

UPDATE wtf.articles a
   SET bias_ensemble_score = a.bias_v2_score,
       bias_ensemble_band  =
           CASE WHEN a.bias_v2_score < -0.55 THEN 'left'
                WHEN a.bias_v2_score < -0.15 THEN 'center-left'
                WHEN a.bias_v2_score <  0.25 THEN 'center'
                WHEN a.bias_v2_score <  0.65 THEN 'center-right'
                ELSE 'right'
           END
  FROM wtf.bias_scores bs
 WHERE bs.article_id = a.id
   AND a.bias_v2_score IS NOT NULL
   AND bs.signal_detected IS FALSE
   AND (a.bias_ensemble_score IS DISTINCT FROM a.bias_v2_score
        OR a.bias_ensemble_band IS DISTINCT FROM
           CASE WHEN a.bias_v2_score < -0.55 THEN 'left'
                WHEN a.bias_v2_score < -0.15 THEN 'center-left'
                WHEN a.bias_v2_score <  0.25 THEN 'center'
                WHEN a.bias_v2_score <  0.65 THEN 'center-right'
                ELSE 'right'
           END);

COMMIT;
