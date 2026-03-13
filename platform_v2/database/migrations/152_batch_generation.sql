-- Migration 152: Batch Generation & Queue Management
-- Adds media_batches table and batch_id FK on media_generation_queue

-- media_batches: groups queue entries into a single user action
CREATE TABLE IF NOT EXISTS media_batches (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    owner_type VARCHAR(20) NOT NULL,
    owner_id INTEGER NOT NULL,
    media_type VARCHAR(20) NOT NULL,
    base_params JSONB NOT NULL DEFAULT '{}',
    sweep_param VARCHAR(50),
    sweep_values JSONB,
    total_items INTEGER NOT NULL,
    completed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_batches_owner ON media_batches (owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_media_batches_status ON media_batches (status);

-- Add batch_id to media_generation_queue
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'media_generation_queue' AND column_name = 'batch_id'
    ) THEN
        ALTER TABLE media_generation_queue ADD COLUMN batch_id INTEGER REFERENCES media_batches(id) ON DELETE SET NULL;
        CREATE INDEX idx_media_queue_batch ON media_generation_queue (batch_id);
    END IF;
END $$;
