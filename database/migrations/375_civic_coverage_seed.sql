-- database/migrations/375_civic_coverage_seed.sql
-- Phase 1 Civic Transparency, acceptance criterion #9.
-- Seeds civic_transparency.org_units.coverage for known cases.
--
-- This UPDATE is safe to run before Pass A (zero rows affected — schema only),
-- and meaningful after Pass A has populated org_units. OrgUnitWriter.upsert
-- (services/civic_geds_pass_a.py) does NOT overwrite coverage on ON CONFLICT,
-- so seeded values persist across subsequent crawls.

-- Full coverage: departments that publish all employees in GEDS.
UPDATE civic_transparency.org_units
   SET coverage = 'full'
 WHERE parent_id IS NULL
   AND abbreviation_en IN
       ('TBS','PCO','PSPC','ESDC','HC','PHAC','SC','TC','GAC','FIN');

-- Partial coverage: national-security or other agencies that omit some staff.
UPDATE civic_transparency.org_units
   SET coverage = 'partial'
 WHERE parent_id IS NULL
   AND abbreviation_en IN
       ('CSIS','RCMP','DND','CSE','CFIA');

-- Departments with no GEDS presence at all (rare; opt-out by design).
-- Add to this list as discovered.
-- UPDATE civic_transparency.org_units
--    SET coverage = 'opted_out'
--  WHERE abbreviation_en IN (...);
