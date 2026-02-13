-- Migration 086: Fix assess_command_complexity function ambiguity
-- Date: 2026-02-13
-- Problem: Migration 056 created assess_command_complexity(TEXT) and
--          migration 059 created assess_command_complexity(TEXT, VARCHAR DEFAULT NULL)
--          Both match single-argument calls, causing "function is not unique" errors.
-- Fix: Drop the old single-parameter version, keep the newer two-parameter one.

DROP FUNCTION IF EXISTS assess_command_complexity(TEXT);

COMMENT ON FUNCTION assess_command_complexity(TEXT, VARCHAR) IS
    'Assess command complexity - single-arg calls match via DEFAULT NULL';
