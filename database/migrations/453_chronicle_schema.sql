-- 453: Chronicle schema — full-body + attachments + cross-source entity/story/voice (slice 02)
--
-- Chronicle program (spec: docs/superpowers/specs/2026-07-10-chronicle-multi-source-entity-hub-design.md).
-- Extends the mailbox_* per-import substrate for multi-source ingestion (full bodies +
-- attachments) and adds the cross-source chronicle_* layer (entity resolution, story, voice).
-- Fully idempotent + additive.

CREATE EXTENSION IF NOT EXISTS vector;

-- 1. mailbox_imports: source provenance
ALTER TABLE mailbox_imports ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'upload';
ALTER TABLE mailbox_imports ADD COLUMN IF NOT EXISTS source_account_id INTEGER;   -- google_accounts.id or agents.id; nullable
ALTER TABLE mailbox_imports ADD COLUMN IF NOT EXISTS is_live_source BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. mailbox_emails: full HTML body + retrieval embedding
ALTER TABLE mailbox_emails ADD COLUMN IF NOT EXISTS body_html TEXT;
ALTER TABLE mailbox_emails ADD COLUMN IF NOT EXISTS embedding vector(768);

-- 3. Attachments: file on disk + extracted/OCR text (one row per attachment)
CREATE TABLE IF NOT EXISTS mailbox_attachments (
    id             BIGSERIAL PRIMARY KEY,
    email_id       INTEGER NOT NULL REFERENCES mailbox_emails(id) ON DELETE CASCADE,
    filename       TEXT,
    mime_type      TEXT,
    size_bytes     BIGINT,
    sha256         TEXT,
    stored_path    TEXT,                                  -- /mnt/data2/mailbox_story/<import>/att/<email>/<filename>
    extracted_text TEXT,
    ocr_used       BOOLEAN NOT NULL DEFAULT FALSE,
    extract_status TEXT NOT NULL DEFAULT 'new',           -- new | done | error
    embedding      vector(768),
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mailbox_attachments_email  ON mailbox_attachments(email_id);
CREATE INDEX IF NOT EXISTS idx_mailbox_attachments_status ON mailbox_attachments(extract_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mailbox_attachments_email_sha ON mailbox_attachments(email_id, sha256);

-- 4. Cross-source entity (one person/org across all imports/sources)
CREATE TABLE IF NOT EXISTS chronicle_entity (
    id             BIGSERIAL PRIMARY KEY,
    owner_id       INTEGER NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL DEFAULT 'person',        -- person | org | project | topic
    aliases        JSONB NOT NULL DEFAULT '[]',
    primary_email  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chronicle_entity_owner ON chronicle_entity(owner_id);

-- 5. Map per-import mailbox_entities → the global chronicle_entity
CREATE TABLE IF NOT EXISTS chronicle_entity_link (
    id                  BIGSERIAL PRIMARY KEY,
    chronicle_entity_id BIGINT  NOT NULL REFERENCES chronicle_entity(id) ON DELETE CASCADE,
    mailbox_entity_id   INTEGER NOT NULL REFERENCES mailbox_entities(id) ON DELETE CASCADE,
    confidence          REAL    NOT NULL DEFAULT 1.0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chronicle_entity_link ON chronicle_entity_link(chronicle_entity_id, mailbox_entity_id);
CREATE INDEX IF NOT EXISTS idx_chronicle_entity_link_mbe ON chronicle_entity_link(mailbox_entity_id);

-- 6. Per-entity fused story
CREATE TABLE IF NOT EXISTS chronicle_entity_story (
    id                  BIGSERIAL PRIMARY KEY,
    chronicle_entity_id BIGINT NOT NULL UNIQUE REFERENCES chronicle_entity(id) ON DELETE CASCADE,
    narrative           TEXT,
    span_start          TIMESTAMPTZ,
    span_end            TIMESTAMPTZ,
    source_kinds        JSONB NOT NULL DEFAULT '[]',
    email_count         INTEGER NOT NULL DEFAULT 0,
    model_used          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. Per-entity voice profile (style guide from authored corpus)
CREATE TABLE IF NOT EXISTS chronicle_voice_profile (
    id                  BIGSERIAL PRIMARY KEY,
    chronicle_entity_id BIGINT NOT NULL UNIQUE REFERENCES chronicle_entity(id) ON DELETE CASCADE,
    style_guide         JSONB,                             -- {tone, greetings, sign_offs, phrasings, vocabulary, topics, links}
    sample_count        INTEGER NOT NULL DEFAULT 0,
    span_start          TIMESTAMPTZ,
    span_end            TIMESTAMPTZ,
    model_used          TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
