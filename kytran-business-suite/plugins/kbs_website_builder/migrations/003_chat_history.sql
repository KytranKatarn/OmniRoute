-- Website Builder migration 003 — chat-based editing support.
-- Adds chat history column to website_projects.
-- All statements are idempotent. Run inside tenant schema.

ALTER TABLE website_projects ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
