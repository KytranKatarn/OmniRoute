-- 171_translation_command_center.sql
-- Adds translation_domain_registry table and performance indexes
-- Part of Translation Coverage System — WS5 Consciousness Languages Tab
-- 2026-04-28

CREATE TABLE IF NOT EXISTS translation_domain_registry (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(100) NOT NULL UNIQUE,
    display_name     VARCHAR(150) NOT NULL,
    url              VARCHAR(500) NOT NULL,
    translations_url VARCHAR(500) NOT NULL,
    deploy_method    VARCHAR(20) DEFAULT 'hostinger'
                     CHECK (deploy_method IN ('hostinger', 'vps')),
    active_languages TEXT[] DEFAULT ARRAY['en','fr','es'],
    is_active        BOOLEAN DEFAULT TRUE,
    last_audit_at    TIMESTAMP,
    created_at       TIMESTAMP DEFAULT NOW()
);

INSERT INTO translation_domain_registry
    (name, display_name, url, translations_url, deploy_method, active_languages, is_active)
VALUES
    ('kytranempowerment_com', 'kytranempowerment.com',
     'https://kytranempowerment.com',
     'https://kytranempowerment.com/data/translations.json',
     'hostinger', ARRAY['en','fr','es','pt','de','zh','ar','he','ai'], TRUE),
    ('creed_ai_org', 'creed-ai.org',
     'https://creed-ai.org',
     'https://creed-ai.org/data/translations.json',
     'hostinger', ARRAY['en','fr','es','pt','de','zh','ar','he','ai'], TRUE),
    ('kytran_gov_watch', 'Gov Watch',
     'https://gov.kytranempowerment.com',
     'https://gov.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('kytran_civic_watch', 'Civic Watch',
     'https://civic.kytranempowerment.com',
     'https://civic.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('kytran_legal_watch', 'Legal Watch',
     'https://legal.kytranempowerment.com',
     'https://legal.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('kytran_market_watch', 'Market Watch',
     'https://market.kytranempowerment.com',
     'https://market.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('what_the_fact_com', 'What The Fact (Consumer)',
     'https://what-the-fact.com',
     'https://what-the-fact.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('what_the_fact_tech', 'What The Fact (Tech)',
     'https://what-the-fact.tech',
     'https://what-the-fact.tech/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE)
ON CONFLICT (name) DO NOTHING;

-- Performance indexes for gap queries
CREATE INDEX IF NOT EXISTS idx_translation_gaps_domain_source
    ON translation_gaps(source, status, language)
    WHERE source LIKE 'domain:%';

CREATE INDEX IF NOT EXISTS idx_translation_gaps_recent
    ON translation_gaps(created_at DESC, status);
