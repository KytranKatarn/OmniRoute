-- Migration 073: TOTP 2FA columns for Google Authenticator integration
-- Ensures users table has columns for TOTP-based two-factor authentication

ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_verified_at TIMESTAMP;

-- Index for quick lookup of 2FA-enabled users
CREATE INDEX IF NOT EXISTS idx_users_totp_enabled ON users (totp_enabled) WHERE totp_enabled = TRUE;
