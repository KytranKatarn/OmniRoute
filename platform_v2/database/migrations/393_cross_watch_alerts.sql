-- Migration 393: Cross-Watch Alert System
-- Creates shared schema with entity graph, user follows, signals, and alerts.
-- Safe to re-run (all statements are idempotent).

CREATE SCHEMA IF NOT EXISTS shared;

-- ── Entities users can follow ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared.entities (
    id          SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN
                    ('person', 'org', 'topic', 'department', 'keyword')),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    aliases     TEXT[]  DEFAULT '{}',   -- extra match strings (abbrevs, short names)
    source      TEXT,                   -- 'gov_watch', 'platform', 'parliament'
    source_id   TEXT,                   -- PK in originating table
    metadata    JSONB   DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entities_slug ON shared.entities(slug);
CREATE INDEX IF NOT EXISTS idx_entities_name ON shared.entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON shared.entities(entity_type);

-- ── User follows ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared.user_follows (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL,        -- public.users(id)
    entity_id  INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_user_follows_user   ON shared.user_follows(user_id);
CREATE INDEX IF NOT EXISTS idx_user_follows_entity ON shared.user_follows(entity_id);

-- ── Cross-product signals ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared.cross_watch_signals (
    id             SERIAL PRIMARY KEY,
    entity_id      INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    signal_type    TEXT NOT NULL CHECK (signal_type IN (
                       'new_tender', 'lobbying_activity', 'bill_passed',
                       'news_coverage', 'market_movement', 'legal_ruling')),
    source_product TEXT NOT NULL,       -- 'gov_watch', 'civic_watch', 'wtf', etc.
    source_item_id TEXT NOT NULL,       -- PK of the triggering item in source product
    headline       TEXT NOT NULL,
    url            TEXT,
    metadata       JSONB DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(entity_id, source_product, source_item_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_entity  ON shared.cross_watch_signals(entity_id);
CREATE INDEX IF NOT EXISTS idx_signals_created ON shared.cross_watch_signals(created_at DESC);

-- ── Per-user alerts ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared.cross_watch_alerts (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    entity_id  INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    signal_id  INTEGER NOT NULL REFERENCES shared.cross_watch_signals(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    url        TEXT,
    is_read    BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, signal_id)          -- one alert per user per signal
);
CREATE INDEX IF NOT EXISTS idx_alerts_user   ON shared.cross_watch_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_unread ON shared.cross_watch_alerts(user_id, is_read)
    WHERE is_read = FALSE;
