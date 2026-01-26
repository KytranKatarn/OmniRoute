-- ============================================================================
-- A.R.C.H.I.E. Platform - Add Phone Field to Agents
-- Migration: 004 - Agent Phone Field
-- Created: 2025-12-31
-- Purpose: Add phone field to agents table for public directory contact info
-- ============================================================================

-- Add phone column to agents table
ALTER TABLE agents
ADD COLUMN IF NOT EXISTS phone VARCHAR(20);

-- Add index for phone lookups
CREATE INDEX IF NOT EXISTS idx_agents_phone ON agents(phone);

-- Add comment
COMMENT ON COLUMN agents.phone IS 'Public contact phone number for agent (displayed in directory)';
