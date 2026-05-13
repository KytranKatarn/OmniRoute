CREATE TABLE IF NOT EXISTS demo_sessions (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) UNIQUE NOT NULL,
    label VARCHAR(200),
    expires_at TIMESTAMP NOT NULL,
    created_by INTEGER REFERENCES users(id),
    ephemeral_user_id INTEGER REFERENCES users(id),
    used_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_demo_sessions_token ON demo_sessions(token);
