-- 175_phase9_products.sql — Phase 9 new products in marketplace_products
-- Idempotent.

INSERT INTO marketplace_products (slug, name, url, category, price_monthly, is_free)
VALUES
    ('content-studio',
     'AI Content Studio',
     'https://platform.kytranempowerment.com/tools/content-studio',
     'creative',
     79.00,
     FALSE),

    ('agent-as-a-service',
     'Agent-as-a-Service',
     'https://kytranempowerment.com/agent-as-a-service.html',
     'ai',
     49.00,
     FALSE),

    ('community',
     'Community + AI Certification',
     'https://kytranempowerment.com/community.html',
     'community',
     29.00,
     FALSE)

ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    price_monthly = EXCLUDED.price_monthly;
