-- DS9 Criterion 4 — Phase 1: Rename empty contractor tables to engineer
-- Tables: contractor_budget_history, contractor_consultations, contractor_approval_requests
-- All have 0 rows. Safe to rename.
-- Excludes: contractor_providers_backup_pre486 (rollback snapshot)

ALTER TABLE IF EXISTS contractor_budget_history RENAME TO engineer_budget_history;
ALTER TABLE IF EXISTS contractor_consultations RENAME TO engineer_consultations;
ALTER TABLE IF EXISTS contractor_approval_requests RENAME TO engineer_approval_requests;

-- Rename columns in engineer_approval_requests
ALTER TABLE IF EXISTS engineer_approval_requests RENAME COLUMN contractor_model TO engineer_model;
ALTER TABLE IF EXISTS engineer_approval_requests RENAME COLUMN contractor_provider TO engineer_provider;

-- Rename columns in engineer_consultations
ALTER TABLE IF EXISTS engineer_consultations RENAME COLUMN contractor_id TO engineer_id;
