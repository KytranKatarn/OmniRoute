-- Migration: 181_portrait_variants_benchmark.sql
-- Task #1151: Allow multiple portraits per agent + benchmark columns
-- Currently agent_portraits has 1 per agent. This adds variant support
-- and generation parameter tracking for benchmarking across models/GPUs.

BEGIN;

-- Variant identification
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS variant_name VARCHAR(50) DEFAULT 'default';
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS is_primary BOOLEAN DEFAULT TRUE;

-- Generation parameters (for reproducibility + benchmarking)
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS checkpoint_name VARCHAR(200);
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS sampler VARCHAR(50);
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS steps INTEGER;
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS cfg_scale NUMERIC(4,1);
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS seed BIGINT;
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS prompt TEXT;
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS negative_prompt TEXT;

-- Benchmark scoring
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS benchmark_score NUMERIC(5,2);
ALTER TABLE agent_portraits ADD COLUMN IF NOT EXISTS benchmark_notes TEXT;

-- Allow multiple portraits per agent (remove unique constraint if exists)
-- Add composite index for efficient lookup
CREATE INDEX IF NOT EXISTS idx_portraits_agent_variant
    ON agent_portraits(agent_id, variant_name);
CREATE INDEX IF NOT EXISTS idx_portraits_agent_primary
    ON agent_portraits(agent_id) WHERE is_primary = TRUE;

-- Set existing portraits as 'default' variant and primary
UPDATE agent_portraits SET variant_name = 'default', is_primary = TRUE
WHERE variant_name IS NULL OR variant_name = 'default';

COMMIT;
