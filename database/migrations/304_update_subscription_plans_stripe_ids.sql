-- 304: Sync placeholder Stripe IDs into subscription_plans
-- These match the billing_products seeded in 303

UPDATE subscription_plans
SET stripe_product_id = 'prod_ksm_pro',
    stripe_price_id_monthly = 'price_ksm_pro_monthly',
    stripe_price_id_yearly = 'price_ksm_pro_yearly'
WHERE slug = 'pro';

UPDATE subscription_plans
SET stripe_product_id = 'prod_ksm_business',
    stripe_price_id_monthly = 'price_ksm_business_monthly',
    stripe_price_id_yearly = 'price_ksm_business_yearly'
WHERE slug = 'business';

UPDATE subscription_plans
SET stripe_product_id = 'prod_ksm_enterprise',
    stripe_price_id_monthly = 'price_ksm_enterprise_monthly',
    stripe_price_id_yearly = 'price_ksm_enterprise_yearly'
WHERE slug = 'enterprise';
