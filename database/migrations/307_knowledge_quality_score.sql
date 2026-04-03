-- Migration 307: Add quality scoring columns to knowledge_base
-- Supports Quality-Gated Knowledge Pipeline (Project #215)

-- Quality score: LLM-assessed content quality (0.0-1.0)
-- NULL = not yet scored, 0.0 = garbage, 1.0 = exceptional
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS quality_score NUMERIC(3,2) DEFAULT NULL;

-- Review status: tracks quality gate state
-- pending = awaiting first score, scored = has quality_score,
-- flagged = needs human review (0.3-0.5), rejected = below threshold
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending';

-- When the quality score was last computed
ALTER TABLE knowledge_base
    ADD COLUMN IF NOT EXISTS quality_scored_at TIMESTAMP DEFAULT NULL;

-- Index for efficient queries: find unscored, find flagged, sort by quality
CREATE INDEX IF NOT EXISTS idx_kb_quality_score ON knowledge_base(quality_score)
    WHERE quality_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_kb_review_status ON knowledge_base(review_status);
CREATE INDEX IF NOT EXISTS idx_kb_unscored ON knowledge_base(review_status)
    WHERE review_status = 'pending';

-- Composite index for search ranking: quality + importance together
CREATE INDEX IF NOT EXISTS idx_kb_quality_importance
    ON knowledge_base(quality_score DESC, importance_score DESC)
    WHERE quality_score IS NOT NULL;
