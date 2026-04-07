-- Migration 309: Family Hints table for AI Record Hints feature
-- Stores potential record matches from research APIs, scored by confidence.

CREATE TABLE IF NOT EXISTS family_hints (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    person_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    source_api VARCHAR(50) NOT NULL,
    external_id VARCHAR(255),
    title TEXT,
    snippet TEXT,
    url TEXT,
    confidence_score NUMERIC(3,2) DEFAULT 0.50,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, accepted, dismissed
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_family_hints_user ON family_hints(user_id);
CREATE INDEX IF NOT EXISTS idx_family_hints_person ON family_hints(person_id);
