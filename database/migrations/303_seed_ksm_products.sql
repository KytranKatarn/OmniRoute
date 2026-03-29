-- 303: Seed KSM billing products (3 tiers x 2 cycles = 6 rows)
-- Placeholder Stripe IDs — replace with real IDs from Stripe Dashboard

INSERT INTO billing_products
    (stripe_product_id, stripe_price_id, module, name, description,
     amount_cents, currency, billing_interval, is_active)
VALUES
    -- Monthly plans
    ('prod_ksm_pro', 'price_ksm_pro_monthly', 'ksm',
     'KSM Pro', '3 compliance packs, 6h scan interval, 3 themes',
     2900, 'cad', 'month', true),

    ('prod_ksm_business', 'price_ksm_business_monthly', 'ksm',
     'KSM Business', '5 compliance packs, 1h scan interval, 5 themes',
     4900, 'cad', 'month', true),

    ('prod_ksm_enterprise', 'price_ksm_enterprise_monthly', 'ksm',
     'KSM Enterprise', 'All packs, custom scan interval, all themes, priority support',
     9900, 'cad', 'month', true),

    -- Yearly plans (2 months free)
    ('prod_ksm_pro_yr', 'price_ksm_pro_yearly', 'ksm',
     'KSM Pro (Annual)', '3 compliance packs, 6h scan interval, 3 themes',
     29000, 'cad', 'year', true),

    ('prod_ksm_business_yr', 'price_ksm_business_yearly', 'ksm',
     'KSM Business (Annual)', '5 compliance packs, 1h scan interval, 5 themes',
     49000, 'cad', 'year', true),

    ('prod_ksm_enterprise_yr', 'price_ksm_enterprise_yearly', 'ksm',
     'KSM Enterprise (Annual)', 'All packs, custom scan interval, all themes, priority support',
     99000, 'cad', 'year', true)

ON CONFLICT (stripe_price_id) DO NOTHING;
