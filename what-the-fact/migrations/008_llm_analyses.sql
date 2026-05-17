-- migration 008: wtf.llm_analyses — cached per-article LLM deep-analysis
--
-- Backs the "LLM Analyzed" metric on the activity page (currently 9%, target 100%).
-- One row per (article_id, model) holds the JSONB sections returned by V.E.R.I.F.Y.
-- via the wtf-hub deep_analysis task. Consumer reads this row on click → instant
-- response, no on-demand LLM call.
--
-- sections_json shape (example, not enforced):
--   {
--     "bias_summary": "...",
--     "key_claims": [{"claim": "...", "verdict": "true|false|misleading|unverifiable", "evidence": "..."}, ...],
--     "geo_entities": [{"name": "...", "type": "city|province|country", "lat": ..., "lng": ...}, ...],
--     "editorial_take": "..."
--   }

CREATE TABLE IF NOT EXISTS wtf.llm_analyses (
    id              SERIAL PRIMARY KEY,
    article_id      INTEGER NOT NULL REFERENCES wtf.articles(id) ON DELETE CASCADE,
    sections_json   JSONB NOT NULL,
    model           VARCHAR(64) NOT NULL,
    dispatched_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP,
    UNIQUE (article_id, model)
);

CREATE INDEX IF NOT EXISTS idx_llm_analyses_article
    ON wtf.llm_analyses(article_id);

CREATE INDEX IF NOT EXISTS idx_llm_analyses_pending
    ON wtf.llm_analyses(dispatched_at)
    WHERE completed_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_llm_analyses_completed
    ON wtf.llm_analyses(completed_at DESC)
    WHERE completed_at IS NOT NULL;
