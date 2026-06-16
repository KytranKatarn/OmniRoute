-- 436_mailbox_story_enrich.sql — Mailbox Story Extractor Phase 2 (local-only enrichment).
-- Per extracted email, a LOCAL fleet LLM extracts a summary/topic/category/sensitivity +
-- entities (people/orgs/projects/topics) + an optional dated event. Results land here.
-- Privacy: enrichment dispatch is pinned local-only (no cloud); see services/mailbox_enrich_service.py.
-- Timeline + stories tables are Phase 3. Design §5: .claude/plans/2026-06-16-mailbox-story-extractor-design.md.

-- One fact row per email (upsert on re-enrich).
CREATE TABLE IF NOT EXISTS mailbox_email_facts (
    id          SERIAL PRIMARY KEY,
    email_id    INTEGER NOT NULL UNIQUE REFERENCES mailbox_emails(id) ON DELETE CASCADE,
    summary     TEXT,
    topic       TEXT,
    category    TEXT,                  -- coarse bucket the LLM proposes (e.g. procurement, hr, legal)
    sensitivity TEXT,                  -- ADVISORY tag: normal / gov / secret / personal (human-confirmed, never auto-acted)
    sentiment   TEXT,                  -- positive / neutral / negative
    event_date  DATE,                  -- a concrete dated event the email is about, if any
    event_title TEXT,
    model_used  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Distinct entities per import (people/orgs/projects/topics), deduped by normalized name + type.
CREATE TABLE IF NOT EXISTS mailbox_entities (
    id              SERIAL PRIMARY KEY,
    import_id       INTEGER NOT NULL REFERENCES mailbox_imports(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,                 -- display name as first seen
    entity_type     TEXT NOT NULL,                 -- person / org / project / topic
    normalized_name TEXT NOT NULL,                 -- lower/trimmed key for dedup
    mention_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (import_id, entity_type, normalized_name)
);
CREATE INDEX IF NOT EXISTS idx_mailbox_entities_import ON mailbox_entities(import_id);
CREATE INDEX IF NOT EXISTS idx_mailbox_entities_rank   ON mailbox_entities(import_id, mention_count DESC);

-- Which entities appear in which email, with an optional role tag (sender/recipient/mentioned).
CREATE TABLE IF NOT EXISTS mailbox_email_entities (
    email_id    INTEGER NOT NULL REFERENCES mailbox_emails(id) ON DELETE CASCADE,
    entity_id   INTEGER NOT NULL REFERENCES mailbox_entities(id) ON DELETE CASCADE,
    role        TEXT,
    PRIMARY KEY (email_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_mailbox_email_entities_entity ON mailbox_email_entities(entity_id);
