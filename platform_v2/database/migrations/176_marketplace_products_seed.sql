-- 176_marketplace_products_seed.sql — Seed marketplace_products for profile page product tiles.
-- Idempotent (ON CONFLICT DO UPDATE).

INSERT INTO marketplace_products (slug, name, url, icon, category, price_monthly, is_free)
VALUES
    ('archie-platform',     'ARCHIE Platform',              'https://platform.kytranempowerment.com',                                                   '🤖', 'core',         0.00,   TRUE),
    ('kbs-core',            'Kytran Business Suite',        'https://business.kytranempowerment.com',                                                   '💼', 'core',         79.00,  FALSE),
    ('civic-watch',         'Civic Watch',                  'https://civic.kytranempowerment.com',                                                      '🏛️', 'intelligence',  99.00,  FALSE),
    ('legal-watch',         'Legal Watch',                  'https://legal.kytranempowerment.com',                                                      '⚖️', 'intelligence',  99.00,  FALSE),
    ('market-watch',        'Market Watch',                 'https://market.kytranempowerment.com',                                                     '📈', 'intelligence',  99.00,  FALSE),
    ('gov-watch',           'Gov Watch',                    'https://gov.kytranempowerment.com',                                                        '🏛️', 'intelligence', 199.00,  FALSE),
    ('kso-compliance',      'System Operations',            'https://server.kytranempowerment.com',                                                     '🖥️', 'compliance',   129.00,  FALSE),
    ('wtf-premium',         'What The Fact Premium',        'https://what-the-fact.com',                                                                '📰', 'intelligence',  39.00,  FALSE),
    ('signal-linkedin',     'S.I.G.N.A.L. LinkedIn AI',    'https://business.kytranempowerment.com/billing/checkout?product=signal-linkedin',           '🔗', 'social',        99.00,  FALSE),
    ('community',           'Community + AI Certification', 'https://business.kytranempowerment.com/billing/checkout?product=community',                '🎓', 'community',     29.00,  FALSE),
    ('content-studio',      'AI Content Studio',            'https://business.kytranempowerment.com/billing/checkout?product=content-studio',           '✍️', 'creative',      79.00,  FALSE),
    ('agent-as-a-service',  'Agent-as-a-Service',           'https://business.kytranempowerment.com/billing/checkout?product=agent-as-a-service',       '🤝', 'ai',            49.00,  FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name          = EXCLUDED.name,
    url           = EXCLUDED.url,
    icon          = EXCLUDED.icon,
    price_monthly = EXCLUDED.price_monthly,
    updated_at    = NOW();
