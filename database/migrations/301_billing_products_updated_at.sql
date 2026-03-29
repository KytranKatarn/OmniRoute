-- 301: Add updated_at column to billing_products
-- stripe_service.py register_product() uses updated_at for upsert tracking

ALTER TABLE billing_products
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

-- Backfill existing rows
UPDATE billing_products SET updated_at = created_at WHERE updated_at IS NULL;
