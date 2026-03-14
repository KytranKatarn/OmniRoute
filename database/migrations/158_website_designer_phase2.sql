-- Migration 158: Website Designer Phase 2 — deployment URL + chat history
-- Idempotent: safe to run multiple times

ALTER TABLE website_deployments
ADD COLUMN IF NOT EXISTS deployment_url VARCHAR(500);

ALTER TABLE website_builder_projects
ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
