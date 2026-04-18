-- Migration 321: add source_label column to translations (#232)
--
-- Discovered during implementation of the Translation Coverage System: the
-- spec assumed `translations.source` held product/site labels like
-- `website_kytranempowerment` or `product_civic_watch`. It doesn't —
-- `source` is origin tracking ('ai_generated' | 'human_edited' | 'imported').
-- Partitioning by product was implicit via key prefix (`account_center.*`,
-- `system_operations.*`, etc.).
--
-- This migration adds an explicit, indexed `source_label` column and
-- backfills it from the key prefix for existing rows. New inserts from
-- the coverage scan will populate it directly.

BEGIN;

ALTER TABLE translations
    ADD COLUMN IF NOT EXISTS source_label VARCHAR(100);

-- Backfill: for existing rows, derive from the key prefix (first "."-segment).
-- SPLIT_PART returns the whole string if no separator, which is acceptable —
-- such keys simply become their own single-bucket label.
UPDATE translations
SET source_label = SPLIT_PART(key, '.', 1)
WHERE source_label IS NULL;

CREATE INDEX IF NOT EXISTS idx_translations_source_label
    ON translations(source_label);

-- Composite index to match the scanner's common query shape (source+lang+key).
CREATE INDEX IF NOT EXISTS idx_translations_source_lang
    ON translations(source_label, language);

COMMIT;
