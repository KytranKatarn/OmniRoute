-- Migration 323: scope translations uniqueness by source_label (#231, #232)
--
-- The existing UNIQUE (key, language) means two products/sites that happen to
-- share a translation key (e.g. "nav.home", "footer.privacy") CANNOT coexist —
-- the generator's ON CONFLICT ... DO UPDATE will overwrite one site's
-- translation with another's on every nightly scan.
--
-- The natural key is (source_label, key, language). Making source_label part
-- of the UNIQUE unlocks multi-site translation without collision.
--
-- Pre-check: all existing rows have source_label populated and no duplicates
-- exist on the new natural key (verified 2026-04-18). No data migration
-- required, only the constraint swap.

BEGIN;

-- Safety backfill in case any NULL source_labels slipped in between the
-- pre-check and this migration running.
UPDATE translations SET source_label = 'platform' WHERE source_label IS NULL;

ALTER TABLE translations
    ALTER COLUMN source_label SET NOT NULL;

ALTER TABLE translations
    DROP CONSTRAINT IF EXISTS translations_key_language_key;

ALTER TABLE translations
    ADD CONSTRAINT translations_source_key_language_key
    UNIQUE (source_label, key, language);

COMMIT;
