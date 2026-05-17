-- 010_source_ownership.sql
-- Promote SOURCE_OWNERS from in-code dict (consumer/routes.py) to first-class
-- columns on wtf.sources. Unlocks media-consolidation features (#2913 alerts,
-- #2914 literacy score, #2915 public API) and lets ops add a new source
-- without editing application code.
--
-- owner_type values:
--   public      — public broadcaster (CBC/Radio-Canada)
--   corporate   — for-profit chain (Postmedia, Bell Media, Corus, Quebecor, Torstar, Globe & Mail)
--   independent — for-profit independent (Canadaland, Ricochet, etc.)
--   non_profit  — non-profit / co-op / academic (Le Devoir, La Presse, The Tyee, etc.)

ALTER TABLE wtf.sources ADD COLUMN IF NOT EXISTS owner_name VARCHAR(100);
ALTER TABLE wtf.sources ADD COLUMN IF NOT EXISTS owner_type VARCHAR(20);

ALTER TABLE wtf.sources DROP CONSTRAINT IF EXISTS sources_owner_type_check;
ALTER TABLE wtf.sources ADD CONSTRAINT sources_owner_type_check
    CHECK (owner_type IS NULL OR owner_type IN ('public', 'corporate', 'independent', 'non_profit'));

CREATE INDEX IF NOT EXISTS idx_sources_owner_name ON wtf.sources(owner_name);
CREATE INDEX IF NOT EXISTS idx_sources_owner_type ON wtf.sources(owner_type);

-- Seed the 31 known mappings. UPDATE is no-op for sources not yet in the table.
-- Postmedia (national chain — owns ~10 sources)
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='national_post';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='vancouver_sun';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='ottawa_citizen';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='montreal_gazette';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='calgary_herald';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='edmonton_journal';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='saskatoon_starphoenix';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='regina_leaderpost';
UPDATE wtf.sources SET owner_name='Postmedia', owner_type='corporate' WHERE slug='financial_post';
UPDATE wtf.sources SET owner_name='Postmedia (ex-SaltWire, 2024)', owner_type='corporate' WHERE slug='saltwire_news';

-- Public broadcaster
UPDATE wtf.sources SET owner_name='CBC/Radio-Canada', owner_type='public' WHERE slug='cbc_english';
UPDATE wtf.sources SET owner_name='CBC/Radio-Canada', owner_type='public' WHERE slug='radio_canada';

-- Bell Media
UPDATE wtf.sources SET owner_name='Bell Media', owner_type='corporate' WHERE slug='ctv_news';
UPDATE wtf.sources SET owner_name='Bell Media', owner_type='corporate' WHERE slug='bnn_bloomberg';

-- Other corporate chains
UPDATE wtf.sources SET owner_name='Corus Entertainment', owner_type='corporate' WHERE slug='global_news';
UPDATE wtf.sources SET owner_name='Quebecor', owner_type='corporate' WHERE slug='journal_de_montreal';
UPDATE wtf.sources SET owner_name='Torstar', owner_type='corporate' WHERE slug='toronto_star';
UPDATE wtf.sources SET owner_name='Globe and Mail Inc. (Woodbridge)', owner_type='corporate' WHERE slug='globe_mail';

-- Independent local / for-profit independents
UPDATE wtf.sources SET owner_name='FP Newspapers (independent local)', owner_type='independent' WHERE slug='winnipeg_free_press';
UPDATE wtf.sources SET owner_name='Mishmash Media', owner_type='independent' WHERE slug='lactualite';
UPDATE wtf.sources SET owner_name='Ricochet Media Inc.', owner_type='independent' WHERE slug='ricochet_media';
UPDATE wtf.sources SET owner_name='Canadaland', owner_type='independent' WHERE slug='canadaland';
UPDATE wtf.sources SET owner_name='iPolitics Inc.', owner_type='independent' WHERE slug='ipolitics';

-- Non-profit / co-op / academic
UPDATE wtf.sources SET owner_name='Le Devoir (independent co-op)', owner_type='non_profit' WHERE slug='le_devoir';
UPDATE wtf.sources SET owner_name='La Presse (non-profit since 2018)', owner_type='non_profit' WHERE slug='la_presse';
UPDATE wtf.sources SET owner_name='Tyee Solutions Society', owner_type='non_profit' WHERE slug='the_tyee';
UPDATE wtf.sources SET owner_name='Broadbent Institute', owner_type='non_profit' WHERE slug='press_progress';
UPDATE wtf.sources SET owner_name='The Narwhal (non-profit)', owner_type='non_profit' WHERE slug='the_narwhal';
UPDATE wtf.sources SET owner_name='The Conversation (academic)', owner_type='non_profit' WHERE slug='the_conversation_canada';
UPDATE wtf.sources SET owner_name='APTN (Indigenous-owned)', owner_type='non_profit' WHERE slug='aptn_news';
