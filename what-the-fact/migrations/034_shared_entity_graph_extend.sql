-- ============================================================================
-- Migration 034_shared_entity_graph_extend.sql
-- Project archie-platform #373 — Shared Entity Graph — task #3790 (CORRECTED v2)
-- TARGET: hub `wtf` DB, `shared` schema   (apply: psql -U archie -d wtf -f 034_shared_entity_graph_extend.sql)
--
-- ⚠️ DUAL-SCHEMA WARNING (ADR-EG-001 §3 / must-fix S6):
--   The CANONICAL accountability graph is the hub `wtf` DB `shared` schema
--   (entity_type person|organization|journalist). It is the ONLY truth and the
--   ONLY target of this migration.
--   The hub `archie` DB ALSO has a `shared.entities` table (migration 393), but
--   that is a SEPARATE follow/alert SIGNAL BUS (entity_type department|topic|
--   keyword) for the follow/alert feature. THIS migration targets the `wtf` DB
--   ONLY. NEVER run it against the `archie` DB, and NEVER point a slug/id/
--   relationship/chain/dedup/external_id lookup at archie.shared.entities — the
--   wrong entity_type domain returns empty/wrong nodes (ADR-EG-001 §3.1).
--
-- NATURE: ADDITIVE + IDEMPOTENT. Safe to run on the LIVE migration-030 / -033
--   tables. No destructive ALTER, no DROP of data-bearing objects, no column
--   retype. Every CREATE uses IF NOT EXISTS; every seed uses ON CONFLICT;
--   re-running is a no-op. It builds on (does not replace) 030's
--   shared.entities / entity_mentions / entity_relationships.
--
-- WHAT IT ADDS (ADR-EG-001 + task #3790 corrections):
--   1. Extensions: pg_trgm, fuzzystrmatch, unaccent (vector deferred — §0).
--   2. ID / merge invariants on shared.entities: status, merged_into self-FK,
--      immutability + no-reuse + no-delete trigger guard.
--   3. Dedup + provenance machinery: entity_external_ids, source_mention,
--      entity_blocks, dedup_config, merge_review_queue, dedup_pair_decisions,
--      entity_merge_log (reversible tombstone snapshots).
--   4. Adapter coordination: adapter_registry, adapter_sync_state.
--   5. chain_link_types — the frozen 8-position chain catalog (ADR-EG-001 §2.5),
--      with is_spine + has_data, seeded ALL 12 rows (gaps marked has_data=FALSE).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS shared;   -- defensive: 030 already created it

-- ════════════════════════════════════════════════════════════════════════════
-- 1. EXTENSIONS  (fuzzy matching for Tier-2 dedup; ADR-EG-001 §4.4 / #3790)
--    Applied as superuser `archie`. pg_trgm = similarity()/% trigram search;
--    fuzzystrmatch = levenshtein()/metaphone()/dmetaphone(); unaccent =
--    accent-folding for name normalisation. All IF NOT EXISTS → idempotent.
--    NOTE: name_embedding (pgvector) is DEFERRED (§0 of #3790). The `vector`
--    extension is NOT enabled and no name_embedding column is added here —
--    it would require pgvector to be installed on the wtf DB and a model to
--    populate it. Adding it cheaply is not possible, so it is omitted entirely;
--    a future migration can add it once embeddings are wired.
-- ════════════════════════════════════════════════════════════════════════════
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- ════════════════════════════════════════════════════════════════════════════
-- 2. ID / MERGE INVARIANTS on shared.entities  (additive ALTERs — #3790)
--    entity id is immutable, never reused, never DELETEd (trigger-enforced).
--    status = active | merged | suppressed. merged_into = reversible tombstone
--    pointer (self-FK). Merges write a JSONB snapshot to entity_merge_log = undo.
-- ════════════════════════════════════════════════════════════════════════════

-- status lifecycle column (default active so all live rows stay active)
ALTER TABLE shared.entities
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';

-- self-referential tombstone pointer: a merged row points at its survivor.
ALTER TABLE shared.entities
    ADD COLUMN IF NOT EXISTS merged_into INTEGER;

-- attach the self-FK + status CHECK only if not already present (idempotent).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'entities_merged_into_fkey'
          AND conrelid = 'shared.entities'::regclass
    ) THEN
        ALTER TABLE shared.entities
            ADD CONSTRAINT entities_merged_into_fkey
            FOREIGN KEY (merged_into) REFERENCES shared.entities(id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'entities_status_check'
          AND conrelid = 'shared.entities'::regclass
    ) THEN
        ALTER TABLE shared.entities
            ADD CONSTRAINT entities_status_check
            CHECK (status IN ('active', 'merged', 'suppressed'));
    END IF;

    -- a merged row MUST point somewhere; a non-merged row MUST NOT.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'entities_merge_consistency_check'
          AND conrelid = 'shared.entities'::regclass
    ) THEN
        ALTER TABLE shared.entities
            ADD CONSTRAINT entities_merge_consistency_check
            CHECK (
                (status = 'merged'     AND merged_into IS NOT NULL) OR
                (status <> 'merged'    AND merged_into IS NULL)
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_entities_status      ON shared.entities(status);
CREATE INDEX IF NOT EXISTS idx_entities_merged_into ON shared.entities(merged_into);

-- trigram index on canonical_name for fuzzy candidate generation (ADR §4.4).
CREATE INDEX IF NOT EXISTS idx_entities_name_trgm
    ON shared.entities USING GIN (canonical_name gin_trgm_ops);

-- ── Immutability / no-reuse / no-delete trigger guard ───────────────────────
-- entity id is immutable (cannot be UPDATEd), never reused, and rows are never
-- physically DELETEd (merge = tombstone via status='merged', not DELETE).
CREATE OR REPLACE FUNCTION shared.entities_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'shared.entities rows are never deleted (id=% is immutable; merge via status=''merged'' + merged_into instead)',
            OLD.id
            USING ERRCODE = 'restrict_violation';
    ELSIF TG_OP = 'UPDATE' THEN
        IF NEW.id <> OLD.id THEN
            RAISE EXCEPTION
                'shared.entities.id is immutable and never reused (attempted % -> %)',
                OLD.id, NEW.id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- (re)create the trigger idempotently.
DROP TRIGGER IF EXISTS trg_entities_guard ON shared.entities;
CREATE TRIGGER trg_entities_guard
    BEFORE UPDATE OR DELETE ON shared.entities
    FOR EACH ROW EXECUTE FUNCTION shared.entities_guard();

-- ════════════════════════════════════════════════════════════════════════════
-- 3. ENTITY EXTERNAL IDS  (Tier-1 durable person/org/journalist keys only)
--    ADR-EG-001 §4.1: openparliament_slug, parl_mp_id, lobbying_comlog_id
--    (event-scoped — S3), wtf_source_slug. NO document/event keys here (S2:
--    procurement_reference / scc_citation / oic_pc_number / ethics_report_url
--    are entity_mentions content pointers, NOT external ids).
--    UNIQUE (key_type, key_value) = a durable id resolves to exactly one entity.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.entity_external_ids (
    id          SERIAL PRIMARY KEY,
    entity_id   INTEGER NOT NULL REFERENCES shared.entities(id),
    key_type    TEXT NOT NULL,   -- 'openparliament_slug','parl_mp_id','lobbying_comlog_id','wtf_source_slug'
    key_value   TEXT NOT NULL,   -- the durable id value (for lobbying_comlog_id store 'comlog_id:mp_id' — S3)
    source_product TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (key_type, key_value)
);
CREATE INDEX IF NOT EXISTS idx_external_ids_entity ON shared.entity_external_ids(entity_id);
CREATE INDEX IF NOT EXISTS idx_external_ids_keyval ON shared.entity_external_ids(key_type, key_value);

-- ════════════════════════════════════════════════════════════════════════════
-- 4. SOURCE MENTION  (raw pre-resolution staging + audit trail)
--    Every adapter row that MIGHT become an entity lands here FIRST, before the
--    resolver decides which canonical entity_id it maps to. Holds the raw name,
--    the source row pointer (source_row_id), and any alias/audit context.
--    resolved_entity_id is NULL until the single-writer resolver attaches it.
--    Idempotent UNIQUE on the natural source-row key so re-ingest is a no-op.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.source_mention (
    id                 SERIAL PRIMARY KEY,
    source_product     TEXT NOT NULL,   -- 'wtf','gov-watch','civic-watch','legal-watch','market-watch','parliament'
    source_table       TEXT NOT NULL,   -- e.g. 'parliament.mps','gov_watch.gic_appointments','parliament.ec_contributions'
    source_row_id      TEXT NOT NULL,   -- PK of the source row (string to span int/text PKs)
    raw_name           TEXT NOT NULL,   -- exact name as it appeared in the source
    normalized_name    TEXT,            -- resolver-computed normalize_name() result
    proposed_type      TEXT,            -- 'person' | 'organization' | 'journalist'
    raw_payload        JSONB NOT NULL DEFAULT '{}',  -- alias/audit context (postal, party, role, etc.)
    resolved_entity_id INTEGER REFERENCES shared.entities(id),  -- NULL until resolved
    resolution_method  TEXT,            -- 'tier1_exact' | 'tier2_auto' | 'tier2_review' | 'manual'
    confidence         NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    resolved_at        TIMESTAMP,
    UNIQUE (source_product, source_table, source_row_id)
);
CREATE INDEX IF NOT EXISTS idx_source_mention_resolved ON shared.source_mention(resolved_entity_id);
CREATE INDEX IF NOT EXISTS idx_source_mention_unresolved
    ON shared.source_mention(source_product) WHERE resolved_entity_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_source_mention_norm_trgm
    ON shared.source_mention USING GIN (normalized_name gin_trgm_ops);

-- ════════════════════════════════════════════════════════════════════════════
-- 5. ENTITY BLOCKS  (blocking keys to bound the O(n^2) dedup comparison)
--    Standard record-linkage blocking: only compare candidates that share a
--    block_key (e.g. metaphone of surname, first-3-of-postal, entity_type).
--    Many-to-one: one entity can sit in several blocks.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.entity_blocks (
    id          SERIAL PRIMARY KEY,
    entity_id   INTEGER NOT NULL REFERENCES shared.entities(id),
    block_key   TEXT NOT NULL,   -- e.g. 'person|dmeta:TRT|postal:M5V'
    block_kind  TEXT NOT NULL,   -- 'dmetaphone' | 'postal' | 'token' | 'type'
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (entity_id, block_key)
);
CREATE INDEX IF NOT EXISTS idx_entity_blocks_key    ON shared.entity_blocks(block_key);
CREATE INDEX IF NOT EXISTS idx_entity_blocks_entity ON shared.entity_blocks(entity_id);

-- ════════════════════════════════════════════════════════════════════════════
-- 6. DEDUP CONFIG  (tunable thresholds — change without code deploy)
--    Stage-1 deterministic merge ships Wave 1; Stage-2 fuzzy/review Wave 2.
--    Single-row config keyed by `key`; seeded with safe defaults.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.dedup_config (
    key         TEXT PRIMARY KEY,
    value       NUMERIC NOT NULL,
    description TEXT,
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
INSERT INTO shared.dedup_config(key, value, description) VALUES
    ('auto_merge_threshold',  0.92, 'similarity >= this AND same block -> auto-merge (Tier-2)'),
    ('review_threshold',      0.78, 'similarity in [review,auto) -> merge_review_queue'),
    ('trigram_min',           0.45, 'minimum trigram similarity() to even generate a candidate pair'),
    ('donor_min_aggregate',   200,  'EC donors materialize only at >= this aggregate CAD (owner decision)'),
    ('max_block_size',        500,  'skip blocks larger than this (too generic to be useful)')
ON CONFLICT (key) DO NOTHING;

-- ════════════════════════════════════════════════════════════════════════════
-- 7. MERGE REVIEW QUEUE  (Stage-2 fuzzy pairs awaiting human/agent decision)
--    A candidate pair scoring in [review_threshold, auto_merge_threshold).
--    UNIQUE on the ordered pair so a pair is queued once.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.merge_review_queue (
    id            SERIAL PRIMARY KEY,
    entity_id_a   INTEGER NOT NULL REFERENCES shared.entities(id),
    entity_id_b   INTEGER NOT NULL REFERENCES shared.entities(id),
    similarity    NUMERIC(4,3) CHECK (similarity BETWEEN 0 AND 1),
    block_key     TEXT,
    features      JSONB NOT NULL DEFAULT '{}',   -- why it scored what it scored
    status        TEXT NOT NULL DEFAULT 'pending', -- pending | merged | rejected | deferred
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    decided_at    TIMESTAMP,
    decided_by    TEXT,
    CHECK (entity_id_a < entity_id_b),   -- canonical ordering -> dedupe the queue itself
    CHECK (status IN ('pending','merged','rejected','deferred')),
    UNIQUE (entity_id_a, entity_id_b)
);
CREATE INDEX IF NOT EXISTS idx_merge_queue_status ON shared.merge_review_queue(status);

-- ════════════════════════════════════════════════════════════════════════════
-- 8. DEDUP PAIR DECISIONS  (durable record of every pair verdict)
--    A learned/sticky decision: 'same' (merge) or 'distinct' (never re-queue).
--    Lets the nightly scan skip pairs a human already ruled distinct.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.dedup_pair_decisions (
    id            SERIAL PRIMARY KEY,
    entity_id_a   INTEGER NOT NULL REFERENCES shared.entities(id),
    entity_id_b   INTEGER NOT NULL REFERENCES shared.entities(id),
    decision      TEXT NOT NULL,   -- 'same' | 'distinct'
    similarity    NUMERIC(4,3),
    decided_by    TEXT,            -- 'auto' | username | agent name
    decided_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (entity_id_a < entity_id_b),
    CHECK (decision IN ('same','distinct')),
    UNIQUE (entity_id_a, entity_id_b)
);
CREATE INDEX IF NOT EXISTS idx_pair_decisions_decision ON shared.dedup_pair_decisions(decision);

-- ════════════════════════════════════════════════════════════════════════════
-- 9. ENTITY MERGE LOG  (reversible tombstone snapshots = UNDO)
--    On merge: the loser's full row + its mentions/relationships/external_ids
--    snapshot is captured here as JSONB BEFORE re-pointing. To undo: restore the
--    snapshot, flip the loser's status back to 'active', clear merged_into.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.entity_merge_log (
    id              SERIAL PRIMARY KEY,
    survivor_id     INTEGER NOT NULL REFERENCES shared.entities(id),
    merged_id       INTEGER NOT NULL REFERENCES shared.entities(id),  -- the tombstoned (loser) row
    merged_snapshot JSONB NOT NULL,   -- full pre-merge snapshot of loser (row + FKs) = undo payload
    reason          TEXT,
    merged_by       TEXT,             -- 'auto' | username | agent
    merged_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    reverted_at     TIMESTAMP,        -- non-NULL once undone
    reverted_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_merge_log_survivor ON shared.entity_merge_log(survivor_id);
CREATE INDEX IF NOT EXISTS idx_merge_log_merged   ON shared.entity_merge_log(merged_id);
CREATE INDEX IF NOT EXISTS idx_merge_log_active   ON shared.entity_merge_log(merged_at) WHERE reverted_at IS NULL;

-- ════════════════════════════════════════════════════════════════════════════
-- 10. ADAPTER REGISTRY + SYNC STATE  (coordination for the 5 product feeds)
--    adapter_registry  = catalog of feeders + their interconnect role (W4).
--    adapter_sync_state = per-adapter incremental watermark + run audit.
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.adapter_registry (
    adapter_key   TEXT PRIMARY KEY,   -- 'wtf','gov-watch','civic-watch','legal-watch','market-watch','parliament'
    display_name  TEXT NOT NULL,
    write_mode    TEXT NOT NULL,      -- 'direct' (WTF/parliament hub-resident) | 'remote_push' (POST to ingest endpoint)
    interconnect_role TEXT,           -- W4 asymmetry: 'full_feed_deep' | 'feed_shallow' | 'chrome_only' | 'narrate_only'
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);
-- Seed the interconnect asymmetry (ADR-EG-001 §5.1 / must-fix W4) so it is data,
-- not folklore. write_mode: WTF + parliament write the wtf DB directly (single
-- writer, co-located); gov/civic/legal/market POST to the WTF ingest endpoint.
INSERT INTO shared.adapter_registry(adapter_key, display_name, write_mode, interconnect_role) VALUES
    ('wtf',          'What The Fact',  'direct',      'full_feed_deep'),
    ('parliament',   'Parliament',     'direct',      'full_feed_deep'),
    ('gov-watch',    'Gov Watch',      'remote_push', 'full_feed_deep'),
    ('civic-watch',  'Civic Watch',    'remote_push', 'feed_shallow'),
    ('legal-watch',  'Legal Watch',    'remote_push', 'feed_shallow'),
    ('market-watch', 'Market Watch',   'remote_push', 'chrome_only')
ON CONFLICT (adapter_key) DO UPDATE SET
    display_name      = EXCLUDED.display_name,
    write_mode        = EXCLUDED.write_mode,
    interconnect_role = EXCLUDED.interconnect_role;

CREATE TABLE IF NOT EXISTS shared.adapter_sync_state (
    id              SERIAL PRIMARY KEY,
    adapter_key     TEXT NOT NULL REFERENCES shared.adapter_registry(adapter_key),
    sync_task       TEXT NOT NULL,   -- e.g. 'gic_appointments','vendors','lobby_comms','bylines'
    last_cursor     TEXT,            -- incremental watermark (date / id / etc.)
    last_run_at     TIMESTAMP,
    records_seen    INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    last_error      TEXT,
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (adapter_key, sync_task)
);
CREATE INDEX IF NOT EXISTS idx_adapter_sync_adapter ON shared.adapter_sync_state(adapter_key);

-- ════════════════════════════════════════════════════════════════════════════
-- 11. CHAIN LINK TYPES  (frozen 8-position catalog — ADR-EG-001 §2.5)
--     The chain-ordering + has-data + spine/enrichment catalog. The traverse
--     filter and the public "which links have data" catalog (GET /api/public/
--     chain/links) read this byte-for-byte. relationship_type is the PK so the
--     frozen string set is enforced at the schema level; NODE positions carry a
--     sentinel relationship_type (__mp_node__/__public_node__) so the PK holds
--     while the catalog stays honest that they are nodes, not edges.
--     is_spine distinguishes the chain spine from enrichment edges; has_data is
--     FALSE on Link 4 (enacted_as) + Link 6 (market_reaction_to) — NO writer,
--     API returns status:no_data, UI permanently dims (owner honesty contract).
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS shared.chain_link_types (
    relationship_type TEXT PRIMARY KEY,   -- exact frozen string OR node sentinel
    link_position     INTEGER NOT NULL,   -- 1..8 (spine); enrichment uses attachment hint
    label             TEXT NOT NULL,
    has_data          BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE => API status:no_data, UI dim
    is_spine          BOOLEAN NOT NULL DEFAULT TRUE,   -- FALSE => enrichment edge (not chain spine)
    created_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chain_link_position ON shared.chain_link_types(link_position);

-- Seed ALL 12 rows verbatim from ADR-EG-001 §2.5 (must-fix S5).
INSERT INTO shared.chain_link_types(relationship_type, link_position, label, has_data, is_spine) VALUES
    ('donated_to',          1, 'Money -> MP',         TRUE,  TRUE),
    ('__mp_node__',         2, 'MP (node)',           TRUE,  TRUE),
    ('cast_vote',           3, 'MP -> Vote',          TRUE,  TRUE),
    ('enacted_as',          4, 'Vote -> Policy',      FALSE, TRUE),   -- no ingest pipeline
    ('awarded_to',          5, 'Policy -> Contract',  TRUE,  TRUE),
    ('contracts_with',      5, 'Contract',            TRUE,  TRUE),
    ('market_reaction_to',  6, 'Contract -> Market',  FALSE, TRUE),   -- no securities pipeline
    ('covered_by',          7, '-> Coverage',         TRUE,  TRUE),   -- derived at query time
    ('__public_node__',     8, 'Public (node)',       TRUE,  TRUE),
    -- enrichment edges (NOT spine; link_position = attachment hint only):
    ('lobbied_by',          2, 'Lobbying (enrichment)',    TRUE, FALSE),
    ('appointed_to',        5, 'Appointment (enrichment)', TRUE, FALSE),
    ('employs',             2, 'Employs (enrichment)',     TRUE, FALSE)
ON CONFLICT (relationship_type) DO UPDATE SET
    link_position = EXCLUDED.link_position,
    label         = EXCLUDED.label,
    has_data      = EXCLUDED.has_data,
    is_spine      = EXCLUDED.is_spine;

-- ════════════════════════════════════════════════════════════════════════════
-- 12. WTFUSER GRANTS  (mirror 033 §4 — this migration is applied as `archie`,
--     so the new tables are archie-owned and wtfuser gets NOTHING by default.
--     Without these grants the WTF consumer ingest endpoint (single writer,
--     runs as wtfuser) fails with "permission denied". Idempotent; guarded so
--     environments without the role skip cleanly.
-- ════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        -- table-level DML on every new shared object
        GRANT SELECT, INSERT, UPDATE, DELETE ON
            shared.entity_external_ids,
            shared.source_mention,
            shared.entity_blocks,
            shared.dedup_config,
            shared.merge_review_queue,
            shared.dedup_pair_decisions,
            shared.entity_merge_log,
            shared.adapter_registry,
            shared.adapter_sync_state,
            shared.chain_link_types
        TO wtfuser;

        -- sequences behind the SERIAL PKs (skip dedup_config + chain_link_types:
        -- they have no SERIAL/sequence — TEXT primary keys).
        GRANT USAGE, SELECT ON SEQUENCE
            shared.entity_external_ids_id_seq,
            shared.source_mention_id_seq,
            shared.entity_blocks_id_seq,
            shared.merge_review_queue_id_seq,
            shared.dedup_pair_decisions_id_seq,
            shared.entity_merge_log_id_seq,
            shared.adapter_sync_state_id_seq
        TO wtfuser;
    END IF;
END $$;

-- ============================================================================
-- END migration 034. Re-runnable: every object is IF NOT EXISTS / every seed is
-- ON CONFLICT / every ALTER is guarded. No destructive operation. Canonical
-- target = `wtf` DB `shared` schema; archie DB shared.entities is the separate
-- signal bus and is NEVER touched here (ADR-EG-001 §3 / must-fix S6).
-- ============================================================================
