-- C-2 (Project #366): pr_reviews.metadata column was missing, causing merge-tier
-- writes in pr_review_service to crash and archie_pr_review_worker to no-op.
-- Idempotent.
ALTER TABLE pr_reviews ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
