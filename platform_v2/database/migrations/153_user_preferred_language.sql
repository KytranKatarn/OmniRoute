-- Migration 153: Add preferred_language column to users table
-- Supports per-user language preference for i18n across the platform.

ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_language TEXT DEFAULT 'en';
