-- 174_faith_module.sql
-- Faith module: spiritual care companion (Project #284, 2026-04-28)

CREATE TABLE IF NOT EXISTS faith_sessions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faith_journal (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title          VARCHAR(255),
    content        TEXT NOT NULL,
    scripture_ref  VARCHAR(255),
    tags           VARCHAR(50)[] DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faith_checkins (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score       SMALLINT NOT NULL CHECK (score BETWEEN 1 AND 5),
    reflection  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS faith_practices_log (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    practice_type  VARCHAR(50) NOT NULL
                   CHECK (practice_type IN ('devotional','prayer','scripture','lectio','checkin')),
    notes          TEXT,
    completed_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_faith_sessions_user ON faith_sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_faith_journal_user  ON faith_journal(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_faith_checkins_user ON faith_checkins(user_id, created_at DESC);
