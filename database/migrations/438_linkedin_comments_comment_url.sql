-- 438: comment deep-link (?commentUrn=) on linkedin_comments.
-- The deep-link is the only thing that renders a specific comment thread to the
-- automated session (KB #274178/#274179) and is what linkedin_comment_reply needs.
-- Sourced from notification cards (linkedin_notifications.comment_url).
ALTER TABLE linkedin_comments ADD COLUMN IF NOT EXISTS comment_url TEXT;
