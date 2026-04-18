-- Migration 322: fix translation_gaps unique constraint so scans are idempotent (#231, #232)
--
-- Two problems with the original constraint UNIQUE (source, gap_type, language, key, file_path, line_number):
--
--   1. Default NULL semantics treat every NULL as distinct, so untagged gaps
--      (language=NULL, key=NULL) never dedupe — every scan doubles row count.
--
--   2. (file_path, line_number) is not unique within a file: two untagged strings
--      on the same physical line collide. _line_no_of() returns the first
--      occurrence, so distinct snippets can share a line number. `suggested_key`
--      (a slugified snippet) IS unique per snippet and must be part of the
--      natural key for untagged gaps.
--
-- Natural key by gap_type:
--   untagged:         (source, gap_type, file_path, line_number, suggested_key)
--   missing:          (source, gap_type, language, key)
--   quality_suspect:  (source, gap_type, language, key)
--
-- One constraint that covers all three (with NULLS NOT DISTINCT) is:
--   (source, gap_type, language, key, suggested_key, file_path, line_number)
--
-- Requires PostgreSQL 15+ for NULLS NOT DISTINCT.

BEGIN;

-- 1. Clean up existing duplicates produced by the broken constraint.
--    Keep the oldest id in each natural-key group.
DELETE FROM translation_gaps g1
USING translation_gaps g2
WHERE g1.id > g2.id
  AND g1.source        IS NOT DISTINCT FROM g2.source
  AND g1.gap_type       IS NOT DISTINCT FROM g2.gap_type
  AND g1.language       IS NOT DISTINCT FROM g2.language
  AND g1.key            IS NOT DISTINCT FROM g2.key
  AND g1.suggested_key  IS NOT DISTINCT FROM g2.suggested_key
  AND g1.file_path      IS NOT DISTINCT FROM g2.file_path
  AND g1.line_number    IS NOT DISTINCT FROM g2.line_number;

-- 2. Replace the constraint.
ALTER TABLE translation_gaps
    DROP CONSTRAINT IF EXISTS translation_gaps_unique_key;

ALTER TABLE translation_gaps
    ADD CONSTRAINT translation_gaps_unique_key
    UNIQUE NULLS NOT DISTINCT
        (source, gap_type, language, key, suggested_key, file_path, line_number);

COMMIT;
