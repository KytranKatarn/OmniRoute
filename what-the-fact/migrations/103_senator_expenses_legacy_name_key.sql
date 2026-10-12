-- 103: parliament.senator_expenses_legacy.name_key — a form-independent identity key for the PUBLISHED name.
--
-- 578 of 2,240 legacy rows (26%, ~$24.7M of ~$106M) have senator_id NULL: 98 former senators are not on parliament.senators
-- (the roster loader reads the CURRENT list only), and migration 102 deliberately keeps them by published name rather than
-- giving them stub roster rows that other pages would then list. The cost of that choice is that the SAME person printed as
-- 'CHAPUT, HON. MARIA' and 'HON. MARIA CHAPUT' (two layouts across the 23 periods) could not be grouped.
-- name_key (senate_legacy.name_key()) is a deterministic, accent-folded, honorific-free, initial-free, sorted-word key, so both
-- forms share one value. It is NOT a roster link and never guesses: names differing by a real word get different keys.
--
-- Populated by the loader (INSERT and the ON CONFLICT UPDATE), so re-running the loader backfills every existing row.
-- Nullable, additive, idempotent. wtfuser's existing table-level INSERT/UPDATE/SELECT grant covers the new column; DELETE and
-- TRUNCATE stay revoked (nothing here widens a privilege).

ALTER TABLE parliament.senator_expenses_legacy ADD COLUMN IF NOT EXISTS name_key TEXT;
CREATE INDEX IF NOT EXISTS senator_expenses_legacy_name_key_idx ON parliament.senator_expenses_legacy (name_key);

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('103', '103_senator_expenses_legacy_name_key.sql', 'Legacy senator expenses: name_key groups the same person across published name forms (no roster stubs)', now())
ON CONFLICT (version) DO NOTHING;
