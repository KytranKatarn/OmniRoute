-- 063 — distinguish "no bias signal detected" from "measured a lean of zero".
--
-- ingest/bias.py did:
--     score = total / weight if weight else 0.0
--
-- `weight == 0` means NO trigger term matched — the detector found NOTHING.
-- That is not a measurement of zero, but the code produced 0.0 and _band_for(0.0)
-- returned 'center', so "we detected no loaded vocabulary" was published as
-- "this article is politically centrist". 41,369 rows say so in their own
-- rationale: "triggers: none — defaulted center".
--
-- Same absent-vs-measured collapse as `float(x or 0.0)` in the LLM bias writers
-- (#3008/#3011) and `or "unverifiable"` in the fact-check writers (#3009). This
-- one is in the detector itself.
--
-- ⚠️ WHY A COLUMN AND NOT A NULL OR A NEW BAND.
--   score is NOT NULL.
--   band is CHECK-constrained to left|center-left|center|center-right|right —
--   five POLITICAL values, with no "undetermined" member.
-- Neither can express "unknown" without a breaking change to every consumer that
-- reads them. `signal_detected` adds the missing fact WITHOUT touching either:
-- score/band keep their schema-required values, and this column says whether
-- they mean anything.
--
-- ⚠️ THE ROLLUP IS THE POINT. ingest/outlet_bias.py did a bare AVG(b.score) over
-- every row, so tens of thousands of artificial zeros dragged each outlet toward
-- centre. Measured per-outlet, excluding no-signal rows roughly DOUBLES the
-- measured lean:
--     CTV News            57.7% no-signal   -0.013 -> -0.031
--     Le Quotidien        52.9%             -0.028 -> -0.060
--     Toronto Star        45.4%             -0.050 -> -0.092
--     Winnipeg Free Press 40.2%             -0.071 -> -0.118
-- Those averages feed Media-Sources / Owners / Journalists / CRTC, so the
-- distortion reaches claims about named organisations. The platform has been
-- systematically UNDER-REPORTING how partisan Canadian outlets are.
--
-- DEFAULT TRUE is deliberate: an unknown legacy row keeps counting, so this
-- migration can only ever REMOVE rows we can prove carry no signal. The rollup
-- uses `IS NOT FALSE` for the same reason.
--
-- ⚠️ New wtf columns must GRANT to wtfuser — apps do not connect as owner.

SET lock_timeout = '3s';

ALTER TABLE wtf.bias_scores
    ADD COLUMN IF NOT EXISTS signal_detected BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN wtf.bias_scores.signal_detected IS
  'FALSE = the detector matched NO trigger term for this article. score (0.0) and band (center) carry schema-required values ONLY and assert nothing — do NOT render such a row as a centrist finding. The outlet rollup (ingest/outlet_bias.py) averages `signal_detected IS NOT FALSE` rows only. TRUE = a real measurement, including a genuine 0.0.';

-- Backfill: heuristic rows whose own rationale records that nothing matched.
-- ⚠️ BOTH strings. bias.py's wording changed in this same PR from
-- "none — defaulted center" to "none — NO SIGNAL DETECTED (not a centrist
-- finding)"; matching only one silently misses half the population depending on
-- which side of the deploy a row was written.
UPDATE wtf.bias_scores SET signal_detected = FALSE
 WHERE signal_detected IS TRUE
   AND (rationale LIKE '%none — defaulted center%'
        OR rationale LIKE '%none — NO SIGNAL DETECTED%');

-- Rows from the LLM writers that were fabricated before #3008/#3011 landed:
-- score 0.0, band center, and NO rationale at all. The model returned no
-- reading; the code invented a centre. They cannot be recomputed (the real
-- answer was never stored), but they must stop polluting outlet averages.
UPDATE wtf.bias_scores SET signal_detected = FALSE
 WHERE signal_detected IS TRUE
   AND score = 0.0
   AND band = 'center'
   AND COALESCE(rationale, '') = ''
   AND analyzed_by IN ('dhq_v1', 'llm_v1', 'BIAS_LLM');

CREATE INDEX IF NOT EXISTS idx_bias_scores_no_signal
    ON wtf.bias_scores (article_id) WHERE signal_detected IS FALSE;

GRANT SELECT ON wtf.bias_scores TO wtfuser;
