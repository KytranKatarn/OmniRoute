-- 104: six parliament.senator_expenses_legacy rows hold an amount that lost its LEADING digits when the old reader parsed the PDF.
--
-- Found by re-reading all 2,240 stored rows against the Senate's own PDFs (2026-10-12) and then reading each flagged row off a RENDERED
-- image of the page, not off the extracted text: the old reader dropped the first piece of an amount whenever kerning split it across runs
-- ('1','3' at x=634/639 -> kept only '3,951.03'; '13,' -> kept '940.03'; '4,' fused into the previous run '0 4,' -> kept '867.92').
-- Each total_cad is the sum of its parts, so every figure below is wrong by the same dropped amount and no checksum could have caught it.
--
--   period_end  code    column                stored      printed on the PDF
--   2013-11-30  CoolsA  travel_other_cad       3,951.03    13,951.03
--   2015-08-31  NgoT    travel_other_cad         940.03    13,940.03
--   2016-06-30  LovelS  travel_regular_cad        71.32     6,571.32
--   2013-05-31  WhiteV  travel_other_cad         867.92     4,867.92
--   2014-02-28  CoolsA  travel_other_cad         683.40     4,683.40
--   2016-06-30  BoisvP  travel_regular_cad       842.99     4,842.99
--
-- The reader fix (senate_legacy.parse_fragments, same change) makes re-running the loader write these same values, so this migration and a
-- loader run are interchangeable. It exists so the data does not depend on remembering to re-run a loader.
--
-- GUARDED and idempotent: every UPDATE matches the known-WRONG stored value as well as the key, so it can never overwrite a different
-- figure, and it is a no-op once the row is right (whether this ran first or the loader did). travel_cad and total_cad are re-derived from
-- the row's own other columns, never from a hard-coded total. UPDATE only: no new privilege, no DELETE, no schema change.

UPDATE parliament.senator_expenses_legacy
   SET travel_other_cad = 13951.03,
       travel_cad = travel_regular_cad + 13951.03,
       total_cad = office_cad + hospitality_cad + living_cad + travel_regular_cad + 13951.03
 WHERE period_end = '2013-11-30' AND source_code = 'CoolsA' AND travel_other_cad = 3951.03;

UPDATE parliament.senator_expenses_legacy
   SET travel_other_cad = 13940.03,
       travel_cad = travel_regular_cad + 13940.03,
       total_cad = office_cad + hospitality_cad + living_cad + travel_regular_cad + 13940.03
 WHERE period_end = '2015-08-31' AND source_code = 'NgoT' AND travel_other_cad = 940.03;

UPDATE parliament.senator_expenses_legacy
   SET travel_regular_cad = 6571.32,
       travel_cad = 6571.32 + travel_other_cad,
       total_cad = office_cad + hospitality_cad + living_cad + 6571.32 + travel_other_cad
 WHERE period_end = '2016-06-30' AND source_code = 'LovelS' AND travel_regular_cad = 71.32;

UPDATE parliament.senator_expenses_legacy
   SET travel_other_cad = 4867.92,
       travel_cad = travel_regular_cad + 4867.92,
       total_cad = office_cad + hospitality_cad + living_cad + travel_regular_cad + 4867.92
 WHERE period_end = '2013-05-31' AND source_code = 'WhiteV' AND travel_other_cad = 867.92;

UPDATE parliament.senator_expenses_legacy
   SET travel_other_cad = 4683.40,
       travel_cad = travel_regular_cad + 4683.40,
       total_cad = office_cad + hospitality_cad + living_cad + travel_regular_cad + 4683.40
 WHERE period_end = '2014-02-28' AND source_code = 'CoolsA' AND travel_other_cad = 683.40;

UPDATE parliament.senator_expenses_legacy
   SET travel_regular_cad = 4842.99,
       travel_cad = 4842.99 + travel_other_cad,
       total_cad = office_cad + hospitality_cad + living_cad + 4842.99 + travel_other_cad
 WHERE period_end = '2016-06-30' AND source_code = 'BoisvP' AND travel_regular_cad = 842.99;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('104', '104_senator_expenses_legacy_leading_digit_corrections.sql', 'Legacy senator expenses: 6 rows whose amount lost its leading digits in the old PDF reader, corrected to the figure printed on the PDF (guarded, idempotent)', now())
ON CONFLICT (version) DO NOTHING;
