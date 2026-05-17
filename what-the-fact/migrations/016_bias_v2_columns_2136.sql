-- WTF Bias Scoring v2 — DistilBERT zero-shot signal alongside LLM tier-1
-- Task #2136 — adds a second independent bias signal + ensemble columns.
-- Does NOT replace v1/v3 heuristic or LLM tier-1 — those stay for audit trail.

ALTER TABLE wtf.articles
  ADD COLUMN IF NOT EXISTS bias_v2_score        NUMERIC(4,3),
  ADD COLUMN IF NOT EXISTS bias_v2_label        TEXT,
  ADD COLUMN IF NOT EXISTS bias_v2_confidence   NUMERIC(4,3),
  ADD COLUMN IF NOT EXISTS bias_v2_model        TEXT,
  ADD COLUMN IF NOT EXISTS bias_v2_computed_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS bias_ensemble_score  NUMERIC(4,3),
  ADD COLUMN IF NOT EXISTS bias_ensemble_band   TEXT;

CREATE INDEX IF NOT EXISTS idx_articles_bias_v2_pending
  ON wtf.articles (id)
  WHERE bias_v2_score IS NULL;

COMMENT ON COLUMN wtf.articles.bias_v2_score IS
  'DistilBERT zero-shot bias score, signed [-1.0, +1.0] (negative=left, positive=right)';
COMMENT ON COLUMN wtf.articles.bias_v2_label IS
  'Top label from zero-shot: left | center | right';
COMMENT ON COLUMN wtf.articles.bias_v2_confidence IS
  'Top-label probability from classifier, [0.0, 1.0]';
COMMENT ON COLUMN wtf.articles.bias_v2_model IS
  'HF model id used for scoring (e.g., valhalla/distilbart-mnli-12-3)';
COMMENT ON COLUMN wtf.articles.bias_ensemble_score IS
  '0.5 * bias_score (LLM tier-1) + 0.5 * bias_v2_score (DistilBERT)';
COMMENT ON COLUMN wtf.articles.bias_ensemble_band IS
  'Band derived from bias_ensemble_score via _band_for()';
