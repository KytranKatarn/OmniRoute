-- Migration 030: Shared Entity Graph
-- Tasks #3026 (schema) + #3126 (person dedup back-links)
-- Run: psql $WTF_DATABASE_URL < migrations/030_shared_entity_graph.sql

-- ── Schema ────────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS shared;

-- ── Core entity registry ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS shared.entities (
    id              SERIAL PRIMARY KEY,
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('person', 'organization')),
    canonical_name  TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,          -- normalized-name-with-hyphens (dedup key)
    aliases         TEXT[]    NOT NULL DEFAULT '{}',
    roles           JSONB     NOT NULL DEFAULT '[]',
    metadata        JSONB     NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entities_type    ON shared.entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_slug    ON shared.entities(slug);
CREATE INDEX IF NOT EXISTS idx_entities_roles   ON shared.entities USING GIN (roles);
CREATE INDEX IF NOT EXISTS idx_entities_aliases ON shared.entities USING GIN (aliases);

-- ── Cross-product mention ledger ──────────────────────────────────────────────
-- Records each time an entity appears in a piece of content across any Watch product.
CREATE TABLE IF NOT EXISTS shared.entity_mentions (
    id              SERIAL PRIMARY KEY,
    entity_id       INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    product         TEXT NOT NULL,        -- 'wtf', 'gov-watch', 'civic-watch', 'legal-watch', 'market-watch'
    content_type    TEXT NOT NULL,        -- 'article', 'gic_appointment', 'vote', 'tender', 'ruling', 'lobby_comm'
    content_id      TEXT NOT NULL,        -- string to accommodate different PK types across products
    mention_context TEXT,
    confidence      NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, product, content_type, content_id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity  ON shared.entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_product ON shared.entity_mentions(product);
CREATE INDEX IF NOT EXISTS idx_mentions_content ON shared.entity_mentions(product, content_type, content_id);

-- ── Entity relationship graph ─────────────────────────────────────────────────
-- Records directional relationships between entities across all sources.
CREATE TABLE IF NOT EXISTS shared.entity_relationships (
    id                SERIAL PRIMARY KEY,
    from_entity_id    INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    to_entity_id      INTEGER NOT NULL REFERENCES shared.entities(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,      -- 'appointed_to', 'lobbied_by', 'donated_to', 'employs', 'contracts_with'
    source_product    TEXT,
    source_id         TEXT,
    valid_from        DATE,
    valid_to          DATE,
    metadata          JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
);
CREATE INDEX IF NOT EXISTS idx_relationships_from ON shared.entity_relationships(from_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_to   ON shared.entity_relationships(to_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON shared.entity_relationships(relationship_type);

-- ── Back-links on parliament source tables ────────────────────────────────────
-- Nullable FKs — populated by ingest/shared/entity_graph.py
ALTER TABLE parliament.senators ADD COLUMN IF NOT EXISTS entity_id INTEGER REFERENCES shared.entities(id);
ALTER TABLE parliament.mps      ADD COLUMN IF NOT EXISTS entity_id INTEGER REFERENCES shared.entities(id);
ALTER TABLE parliament.officers ADD COLUMN IF NOT EXISTS entity_id INTEGER REFERENCES shared.entities(id);

CREATE INDEX IF NOT EXISTS idx_senators_entity_id ON parliament.senators(entity_id);
CREATE INDEX IF NOT EXISTS idx_mps_entity_id      ON parliament.mps(entity_id);
CREATE INDEX IF NOT EXISTS idx_officers_entity_id ON parliament.officers(entity_id);
