-- Migration: Fix W.A.T.C.H. agent missing acronym fields
-- Task: #1401 - Agent profile cleanup
-- Date: 2026-03-29

UPDATE agents
SET
    acronym = 'W.A.T.C.H.',
    acronym_expansion = 'Watchdog for Accountability, Transparency, Civic Health'
WHERE name = 'W.A.T.C.H.'
  AND (acronym IS NULL OR acronym = '');
