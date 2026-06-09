-- 424_email_memory_vault_phase2.sql
-- Email Memory Vault — Phase 2 (extract + entity + profile). Project #377.
-- Design: .claude/plans/email-history-ingestion-design.md
--
-- Owner-scoped profile store. NOT the KB quarantine (agent_kb_service PII-rejects
-- email/phone) — these tables hold the personal profile derived from the owner's mail
-- by LOCAL agents only (allow_cloud=False). Idempotent.

CREATE EXTENSION IF NOT EXISTS vector;

-- Evidence-linked facts extracted from individual important emails (7B analyze).
CREATE TABLE IF NOT EXISTS profile_facts (
    id              BIGSERIAL PRIMARY KEY,
    owner_id        INTEGER NOT NULL,
    account_id      INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    ledger_id       BIGINT REFERENCES profile_ingest_ledger(id) ON DELETE CASCADE,
    source_gmail_id TEXT,
    account_context TEXT,                         -- 'personal' | 'business'
    fact_type       TEXT NOT NULL,                -- summary|person|org|commitment|event|topic|sentiment
    subject         TEXT,                          -- entity this fact is about (name/org)
    content         TEXT NOT NULL,                 -- the fact itself
    confidence      REAL DEFAULT 0.7,
    entity_id       INTEGER,                       -- nullable future #373 link (cross-DB, read-only)
    embedding       VECTOR(768),                   -- nomic-embed-text (filled by embed worker)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_profile_facts_owner ON profile_facts (owner_id);
CREATE INDEX IF NOT EXISTS idx_profile_facts_type ON profile_facts (owner_id, fact_type);
CREATE INDEX IF NOT EXISTS idx_profile_facts_ledger ON profile_facts (ledger_id);

-- Per-contact rolled-up profile (relationship + communication-style fingerprint).
CREATE TABLE IF NOT EXISTS profile_contacts (
    id                  BIGSERIAL PRIMARY KEY,
    owner_id            INTEGER NOT NULL,
    email               TEXT NOT NULL,             -- normalized (lower, +tag stripped)
    display_name        TEXT,
    account_context     TEXT,
    entity_id           INTEGER,                   -- nullable future #373 link
    relationship_summary TEXT,                     -- filled by synthesis worker
    comm_style          JSONB,                     -- how the owner talks to them (synthesis)
    message_count       INTEGER NOT NULL DEFAULT 0,
    first_seen          TIMESTAMPTZ,
    last_seen           TIMESTAMPTZ,
    embedding           VECTOR(768),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_profile_contacts_owner_email UNIQUE (owner_id, email)
);
CREATE INDEX IF NOT EXISTS idx_profile_contacts_owner ON profile_contacts (owner_id);

-- Email-address → contact bridge (multiple addresses can map to one person; entity dedup).
CREATE TABLE IF NOT EXISTS profile_contact_addresses (
    id          BIGSERIAL PRIMARY KEY,
    owner_id    INTEGER NOT NULL,
    email       TEXT NOT NULL,
    contact_id  BIGINT REFERENCES profile_contacts(id) ON DELETE CASCADE,
    account_id  INTEGER,
    CONSTRAINT uq_profile_contact_addr UNIQUE (owner_id, email)
);

-- The global "who is Kytran" profile (one row per owner).
CREATE TABLE IF NOT EXISTS profile_owner (
    id            BIGSERIAL PRIMARY KEY,
    owner_id      INTEGER NOT NULL UNIQUE,
    summary       TEXT,                            -- synthesized "who is the owner"
    default_voice TEXT,                            -- communication-style fingerprint
    timeline      JSONB,                           -- life/founding events timeline
    embedding     VECTOR(768),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
