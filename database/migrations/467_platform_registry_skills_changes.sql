-- 467_platform_registry_skills_changes.sql — Living Platform Registry, Phases 3+4 (task #5230)
--
-- TWO TABLES, answering the two halves of the owner's original ask:
-- "an indexed document tracking features / updates / skills / services".
-- Phases 1-2 gave modules + services. This adds SKILLS and, crucially, UPDATES.
--
-- WHY THE CHANGE FEED IS THE POINT
-- A registry that only holds current state answers "what exists?" but never
-- "what changed?" — and every incident this session began with something having
-- changed that nobody noticed: a DNS rewrite swept in `mesh.`, a node's control
-- URL pointed at a dead tunnel for a month, backups stopped reaching Drive for
-- three weeks, a module index kept asserting two tables that never existed.
-- In each case the state was observable; the TRANSITION was not.
--
-- APPEND-ONLY, DELIBERATELY. Rows are never updated or deleted. A feed you can
-- rewrite is not evidence. Retention, if it is ever needed, is a dated DELETE
-- performed knowingly — not an UPDATE that quietly rewrites history.

CREATE TABLE IF NOT EXISTS platform_registry_skill (
    skill_key     TEXT PRIMARY KEY,        -- '<kind>:<name>'  e.g. 'skill:warden-agent'
    kind          TEXT        NOT NULL
                              CHECK (kind IN ('skill', 'command', 'capability')),
    name          TEXT        NOT NULL,
    description   TEXT,
    source_path   TEXT,                    -- repo-relative; NULL for capabilities (code-defined)
    department    TEXT,                    -- capabilities only: from CAPABILITY_DEPARTMENT_MAP

    -- human-owned; the collector must never write it (same rule as modules/services)
    notes         TEXT,

    status        TEXT        NOT NULL DEFAULT 'present'
                              CHECK (status IN ('present', 'absent')),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prk_kind   ON platform_registry_skill (kind);
CREATE INDEX IF NOT EXISTS idx_prk_status ON platform_registry_skill (status);

-- ---------------------------------------------------------------- changes ----
CREATE TABLE IF NOT EXISTS platform_registry_change (
    id           BIGSERIAL PRIMARY KEY,
    entity_type  TEXT        NOT NULL CHECK (entity_type IN ('module', 'service', 'skill')),
    entity_key   TEXT        NOT NULL,
    change_type  TEXT        NOT NULL
                             CHECK (change_type IN ('appeared', 'vanished', 'reappeared', 'changed')),
    field        TEXT,                     -- NULL for appeared/vanished/reappeared
    old_value    TEXT,
    new_value    TEXT,
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prc_detected ON platform_registry_change (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_prc_entity   ON platform_registry_change (entity_type, entity_key);
-- 'vanished' is the row anyone actually pages on; keep it cheap to find.
CREATE INDEX IF NOT EXISTS idx_prc_vanished ON platform_registry_change (detected_at DESC)
    WHERE change_type = 'vanished';

COMMENT ON TABLE platform_registry_change IS
    'APPEND-ONLY change feed (task #5230 phase 4). Never UPDATE or DELETE a row — '
    'a feed you can rewrite is not evidence. Answers "what changed?", which current-state '
    'tables cannot; every incident this session was a transition nobody observed.';
COMMENT ON COLUMN platform_registry_skill.notes IS
    'Human-owned. The collector MUST NOT overwrite this column.';
