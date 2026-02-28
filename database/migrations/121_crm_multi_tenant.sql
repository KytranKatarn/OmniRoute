-- Migration 121: Multi-tenant CRM — enforce created_by ownership on customers/segments
-- Date: 2026-02-27
-- Purpose: Each user owns their own CRM data (customers, segments, interactions)

-- 1. Backfill existing data to Kytran (user_id=2)
UPDATE crm_customers SET created_by = 2 WHERE created_by IS NULL;
UPDATE crm_segments SET created_by = 2 WHERE created_by IS NULL;
UPDATE crm_interactions SET created_by = 2 WHERE created_by IS NULL;

-- 2. Make created_by NOT NULL with default
ALTER TABLE crm_customers ALTER COLUMN created_by SET NOT NULL;
ALTER TABLE crm_customers ALTER COLUMN created_by SET DEFAULT 2;
ALTER TABLE crm_segments ALTER COLUMN created_by SET NOT NULL;
ALTER TABLE crm_segments ALTER COLUMN created_by SET DEFAULT 2;

-- 3. Add user_id to crm_imports if missing
ALTER TABLE crm_imports ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) DEFAULT 2;

-- 4. Indexes for tenant filtering
CREATE INDEX IF NOT EXISTS idx_crm_customers_created_by ON crm_customers(created_by);
CREATE INDEX IF NOT EXISTS idx_crm_segments_created_by ON crm_segments(created_by);
CREATE INDEX IF NOT EXISTS idx_crm_interactions_created_by ON crm_interactions(created_by);
CREATE INDEX IF NOT EXISTS idx_crm_imports_user ON crm_imports(user_id);
