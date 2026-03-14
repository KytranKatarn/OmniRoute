-- Migration 159: Game Studio Phase 1 — chat history
-- Idempotent: safe to run multiple times
ALTER TABLE game_projects ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
