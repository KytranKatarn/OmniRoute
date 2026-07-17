-- 460_collaborator_facts.sql
-- Per-collaborator curated facts — grounding source for persona email drafts (#4959).
-- Read into the collaborator draft prompt AND passed to validate_draft_no_fabrication
-- as the allowed-facts source. Keyed by agent_id (generic); only the collaborator draft
-- path consumes it. Idempotent.
CREATE TABLE IF NOT EXISTS collaborator_facts (
    id          SERIAL PRIMARY KEY,
    agent_id    INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    fact_text   TEXT    NOT NULL,
    category    VARCHAR(60),
    importance  SMALLINT DEFAULT 5,
    is_active   BOOLEAN  DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    created_by  VARCHAR(120),
    updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_collab_facts_agent_active
    ON collaborator_facts (agent_id, is_active);
