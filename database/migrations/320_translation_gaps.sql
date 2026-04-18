-- Migration 320: translation_gaps table + last_semantic_review_at column (#231, #232)

BEGIN;

CREATE TABLE IF NOT EXISTS translation_gaps (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(100) NOT NULL,
    gap_type        VARCHAR(30)  NOT NULL,      -- missing | untagged | quality_suspect
    language        VARCHAR(5),                 -- NULL for untagged (applies to all)
    key             VARCHAR(500),               -- NULL for untagged (no key yet)
    file_path       VARCHAR(500),
    line_number     INTEGER,
    snippet         TEXT,
    suggested_key   VARCHAR(500),
    confidence      NUMERIC(3,2),
    status          VARCHAR(20) DEFAULT 'open', -- open | routed | resolved | wontfix
    task_id         INTEGER,                    -- FK unified_tasks when routed
    created_at      TIMESTAMP DEFAULT NOW(),
    resolved_at     TIMESTAMP,
    CONSTRAINT translation_gaps_unique_key
        UNIQUE (source, gap_type, language, key, file_path, line_number)
);

CREATE INDEX IF NOT EXISTS idx_gaps_status   ON translation_gaps(status);
CREATE INDEX IF NOT EXISTS idx_gaps_source   ON translation_gaps(source);
CREATE INDEX IF NOT EXISTS idx_gaps_language ON translation_gaps(language);

ALTER TABLE translations
    ADD COLUMN IF NOT EXISTS last_semantic_review_at TIMESTAMP;

COMMIT;
