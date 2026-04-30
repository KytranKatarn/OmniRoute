-- Add video_path column and rendering status to social_video_queue
ALTER TABLE social_video_queue ADD COLUMN IF NOT EXISTS video_path TEXT;

-- Add error_message for failed renders
ALTER TABLE social_video_queue ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Expand status to include rendering/failed
ALTER TABLE social_video_queue DROP CONSTRAINT IF EXISTS social_video_queue_status_check;
