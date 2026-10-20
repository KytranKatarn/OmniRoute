-- DS9 Criterion 4 — Phase 4: Rename contractor_providers (23 rows)
-- This is the last table rename since everything depends on it.
ALTER TABLE IF EXISTS contractor_providers RENAME TO engineer_providers;
