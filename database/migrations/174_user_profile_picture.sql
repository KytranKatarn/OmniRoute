-- Migration 174: Add profile_picture column to users table
-- Stores the URL path to the user's uploaded profile picture

ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture TEXT;

COMMENT ON COLUMN users.profile_picture IS 'URL path to uploaded profile picture (e.g. /static/media/users/user_1_123456.jpg)';
