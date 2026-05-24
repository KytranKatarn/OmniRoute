-- Migration 393: Civic Watch × WTF Municipal Story Crossover (Task #3021)
--
-- 1. Add 'civic_event' to cross_watch_signals signal_type CHECK constraint
-- 2. Seed 10 Canadian city entities (municipality type) into shared.entities
--
-- Safe to re-run: all statements are idempotent.

-- ── Step 1: Extend signal_type CHECK ──────────────────────────────────────────
-- Drop old constraint, re-create with civic_event added.
ALTER TABLE shared.cross_watch_signals
    DROP CONSTRAINT IF EXISTS cross_watch_signals_signal_type_check;

ALTER TABLE shared.cross_watch_signals
    ADD CONSTRAINT cross_watch_signals_signal_type_check
    CHECK (signal_type = ANY (ARRAY[
        'new_tender'::text,
        'lobbying_activity'::text,
        'bill_passed'::text,
        'news_coverage'::text,
        'market_movement'::text,
        'legal_ruling'::text,
        'parliament_vote'::text,
        'civic_event'::text
    ]));

-- ── Step 2: Extend entity_type CHECK to include municipality ─────────────────
ALTER TABLE shared.entities
    DROP CONSTRAINT IF EXISTS entities_entity_type_check;

ALTER TABLE shared.entities
    ADD CONSTRAINT entities_entity_type_check
    CHECK (entity_type = ANY (ARRAY[
        'person'::text,
        'org'::text,
        'topic'::text,
        'department'::text,
        'keyword'::text,
        'municipality'::text
    ]));

-- ── Step 3: Seed Canadian city entities ───────────────────────────────────────
INSERT INTO shared.entities (entity_type, name, slug, aliases, source)
VALUES
    ('municipality', 'Toronto',      'toronto',       ARRAY['City of Toronto',      'Toronto City Council',    'TO'],         'seed'),
    ('municipality', 'Montreal',     'montreal',      ARRAY['City of Montreal',      'Montréal',                'MTL',
                                                             'Ville de Montréal'],                                             'seed'),
    ('municipality', 'Ottawa',       'ottawa',        ARRAY['City of Ottawa',        'Ottawa City Council'],                   'seed'),
    ('municipality', 'Vancouver',    'vancouver',     ARRAY['City of Vancouver',     'Vancouver City Council',  'Metro Vancouver'], 'seed'),
    ('municipality', 'Calgary',      'calgary',       ARRAY['City of Calgary',       'Calgary City Council'],                  'seed'),
    ('municipality', 'Edmonton',     'edmonton',      ARRAY['City of Edmonton',      'Edmonton City Council'],                 'seed'),
    ('municipality', 'Winnipeg',     'winnipeg',      ARRAY['City of Winnipeg',      'Winnipeg City Council'],                 'seed'),
    ('municipality', 'Quebec City',  'quebec-city',   ARRAY['Ville de Québec',       'Québec City',             'Quebec'],    'seed'),
    ('municipality', 'Hamilton',     'hamilton',      ARRAY['City of Hamilton',      'Hamilton City Council'],                 'seed'),
    ('municipality', 'Brampton',     'brampton',      ARRAY['City of Brampton',      'Brampton City Council'],                 'seed')
ON CONFLICT (slug) DO NOTHING;
