-- 395_bundle_pricing.sql
-- Watch Series bundle pricing: cross-product subscriptions

ALTER TABLE billing_subscriptions
  ADD COLUMN IF NOT EXISTS bundle_id TEXT;

CREATE TABLE IF NOT EXISTS billing_bundle_products (
    id          SERIAL PRIMARY KEY,
    bundle_id   TEXT    NOT NULL,
    product_id  TEXT    NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bundle_id, product_id)
);

CREATE INDEX IF NOT EXISTS ix_bbp_bundle ON billing_bundle_products (bundle_id);
CREATE INDEX IF NOT EXISTS ix_bbp_product ON billing_bundle_products (product_id);

INSERT INTO billing_bundle_products (bundle_id, product_id) VALUES
    ('watch_bundle',        'civic-watch'),
    ('watch_bundle',        'legal-watch'),
    ('watch_bundle',        'gov-watch'),
    ('watch_bundle',        'market-watch'),
    ('intelligence_bundle', 'civic-watch'),
    ('intelligence_bundle', 'legal-watch'),
    ('intelligence_bundle', 'gov-watch'),
    ('intelligence_bundle', 'market-watch'),
    ('intelligence_bundle', 'wtf-starter')
ON CONFLICT DO NOTHING;
