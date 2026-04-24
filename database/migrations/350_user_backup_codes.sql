-- 2FA backup codes for account recovery (#2063)
CREATE TABLE IF NOT EXISTS user_backup_codes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash VARCHAR(255) NOT NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_backup_codes_user ON user_backup_codes(user_id);
