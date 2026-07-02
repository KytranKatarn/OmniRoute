-- 446: comment deep-link capture on engagement-ledger comment rows (#4632 follow-up)
-- linkedin_comment now returns the posted comment's ?commentUrn= deep-link (captured
-- from the comment node's data-id at posting time). Persisting it here lets
-- run_cross_boost propose likes on OUR engagement comments made on THIRD-party
-- posts — those have no notification-bell deep-link (linkedin_comments only covers
-- comments on our own posts). Idempotent.
ALTER TABLE linkedin_engagement_ledger
    ADD COLUMN IF NOT EXISTS comment_url TEXT;
