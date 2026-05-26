-- Migration 396: add tier_name + product_id to billing_subscriptions
-- Required by watch_billing_handler._update_billing_subscription()
-- These columns were in the billing spec (billing.md) but missing from the table.

ALTER TABLE billing_subscriptions
    ADD COLUMN IF NOT EXISTS tier_name  VARCHAR(50),
    ADD COLUMN IF NOT EXISTS product_id VARCHAR(100);

-- Back-fill product_id from module column where module matches a known product_id
UPDATE billing_subscriptions
SET product_id = module
WHERE product_id IS NULL AND module IS NOT NULL;

COMMENT ON COLUMN billing_subscriptions.tier_name  IS 'Canonical tier (solo/team/agency/starter/free) for this subscription row';
COMMENT ON COLUMN billing_subscriptions.product_id IS 'Product identifier matching billing_product_plans.product_id';
