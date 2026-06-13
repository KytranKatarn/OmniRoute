-- 434_welfare_ewma_score.sql — D3: EWMA-smoothed welfare score columns.
-- The raw `score` is an instantaneous snapshot; a single bad moment tanks the grade.
-- ewma_score/ewma_grade carry the exponentially-weighted moving average so the
-- HEADLINE grade is steady. Additive + idempotent — the raw columns are unchanged.
--
-- Apply: docker exec -i archie_database psql -U archie -d archie < 434_welfare_ewma_score.sql

ALTER TABLE agent_welfare_scores ADD COLUMN IF NOT EXISTS ewma_score numeric(6,2);
ALTER TABLE agent_welfare_scores ADD COLUMN IF NOT EXISTS ewma_grade varchar(4);
