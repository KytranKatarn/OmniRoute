-- 437_mailbox_story_synthesis.sql — Mailbox Story Extractor Phase 3 (timeline + story synthesis).
-- Timeline = deterministic from mailbox_email_facts (dated events). Stories = per-entity cluster,
-- a LOCAL LLM (local_only) writes the narrative arc. Privacy: synthesis dispatch is local-only.
-- Design §5: .claude/plans/2026-06-16-mailbox-story-extractor-design.md.

CREATE TABLE IF NOT EXISTS mailbox_timeline_events (
    id          SERIAL PRIMARY KEY,
    import_id   INTEGER NOT NULL REFERENCES mailbox_imports(id) ON DELETE CASCADE,
    event_date  DATE,
    title       TEXT,
    description TEXT,
    sensitivity TEXT,                          -- carried from the source email's fact (advisory)
    email_id    INTEGER REFERENCES mailbox_emails(id) ON DELETE CASCADE,
    entity_ids  INTEGER[] NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mailbox_timeline_import ON mailbox_timeline_events(import_id, event_date);

-- One story per entity/project cluster (rebuildable — wiped + rewritten per build).
CREATE TABLE IF NOT EXISTS mailbox_stories (
    id            SERIAL PRIMARY KEY,
    import_id     INTEGER NOT NULL REFERENCES mailbox_imports(id) ON DELETE CASCADE,
    cluster_key   TEXT NOT NULL,               -- e.g. person:minister roberts / project:northstar
    title         TEXT,                        -- display name of the cluster
    narrative     TEXT,
    span_start    TIMESTAMPTZ,
    span_end      TIMESTAMPTZ,
    email_count   INTEGER NOT NULL DEFAULT 0,
    model_used    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (import_id, cluster_key)
);
CREATE INDEX IF NOT EXISTS idx_mailbox_stories_import ON mailbox_stories(import_id, email_count DESC);

-- Track whether story synthesis has run for an import (so the worker doesn't re-build endlessly).
ALTER TABLE mailbox_imports ADD COLUMN IF NOT EXISTS story_built_at TIMESTAMPTZ;
