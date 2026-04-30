-- platform_v2/database/migrations/172_access_grants.sql
-- Access grants: which users can access which products
CREATE TABLE IF NOT EXISTS access_grants (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_slug VARCHAR(100) NOT NULL,
    source      VARCHAR(50) NOT NULL DEFAULT 'stripe',
    valid_from  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_access_grants_user_product
    ON access_grants (user_id, product_slug);

CREATE INDEX IF NOT EXISTS idx_access_grants_product ON access_grants (product_slug);

-- Product registry cache (synced from KBS marketplace_registry)
CREATE TABLE IF NOT EXISTS marketplace_products (
    slug        VARCHAR(100) PRIMARY KEY,
    name        VARCHAR(255) NOT NULL,
    url         VARCHAR(500),
    icon        VARCHAR(100),
    category    VARCHAR(100) NOT NULL,
    price_monthly NUMERIC(10, 2),
    is_free     BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Seed known products
INSERT INTO marketplace_products (slug, name, url, icon, category, price_monthly, is_free) VALUES
    ('archie-platform',   'ARCHIE Platform',         'https://platform.kytranempowerment.com',       '🧠', 'core',        149.00, FALSE),
    ('kbs-core',          'KBS Core',                 'https://business.kytranempowerment.com',        '💼', 'core',         79.00, FALSE),
    ('signal-linkedin',   'S.I.G.N.A.L. LinkedIn AI', 'https://platform.kytranempowerment.com/tools/department-hq#social', '📣', 'social', 99.00, FALSE),
    ('wtf-free',          'What The Fact',            'https://what-the-fact.com',        '📰', 'intelligence',  0.00, TRUE),
    ('wtf-premium',       'WTF Premium',              'https://what-the-fact.com',        '📰', 'intelligence', 39.00, FALSE),
    ('kso-compliance',    'Kytran System Operations', 'https://server.kytranempowerment.com',        '🛡', 'compliance',  129.00, FALSE),
    ('civic-watch',       'Civic Watch',              'https://civic.kytranempowerment.com', '🏙', 'intelligence', 99.00, FALSE),
    ('legal-watch',       'Legal Watch',              'https://legal.kytranempowerment.com', '⚖️', 'intelligence', 99.00, FALSE),
    ('market-watch',      'Market Watch',             'https://market.kytranempowerment.com', '📈', 'intelligence', 99.00, FALSE),
    ('gov-watch',         'Gov Watch',                'https://gov.kytranempowerment.com', '🏛', 'intelligence', 199.00, FALSE),
    ('gov-watch-alerts',  'Gov Watch Starter Alerts', 'https://gov.kytranempowerment.com', '🏛', 'intelligence', 49.00, FALSE)
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name, url = EXCLUDED.url, price_monthly = EXCLUDED.price_monthly,
    is_free = EXCLUDED.is_free, updated_at = NOW();

-- Enforce NOT NULL on category (safe — all seed rows have a value)
ALTER TABLE marketplace_products ALTER COLUMN category SET NOT NULL;

-- Drop redundant single-column index — covered by unique composite idx_access_grants_user_product
DROP INDEX IF EXISTS idx_access_grants_user_id;
