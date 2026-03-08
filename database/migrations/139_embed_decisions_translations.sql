-- Add embedding columns to decisions and translations for unified intelligence search
-- Idempotent: uses IF NOT EXISTS

ALTER TABLE project_decisions
ADD COLUMN IF NOT EXISTS embedding vector(768),
ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP;

ALTER TABLE translations
ADD COLUMN IF NOT EXISTS embedding vector(768),
ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP;
