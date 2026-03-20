-- Migration 174: Normalize departments, rebuild hierarchy, fix emails
-- Date: 2026-03-20

BEGIN;

-- ============================================================
-- STEP 1: Normalize department names
-- ============================================================

-- "Engineering" -> "Engineering & Technology"
UPDATE agents SET department = 'Engineering & Technology' WHERE department = 'Engineering';

-- "Communications & Marketing" -> "Marketing & Communications"
UPDATE agents SET department = 'Marketing & Communications' WHERE department = 'Communications & Marketing';

-- "Diplomatic & Human Relations" -> "Diplomatic & External Relations"
UPDATE agents SET department = 'Diplomatic & External Relations' WHERE department = 'Diplomatic & Human Relations';

-- ============================================================
-- STEP 2: Rebuild hierarchy (reports_to_agent_id)
-- ============================================================

-- Reset all
UPDATE agents SET reports_to_agent_id = NULL WHERE status = 'active';

-- ARCHIE reports to nobody (COO)
-- Vigil reports to ARCHIE
UPDATE agents SET reports_to_agent_id = (
  SELECT id FROM agents WHERE display_name LIKE '%A.R.C.H.I.E.%' LIMIT 1
) WHERE display_name LIKE '%Vigil%' AND status = 'active';

-- C-suite (Chief%) report to ARCHIE
UPDATE agents SET reports_to_agent_id = (
  SELECT id FROM agents WHERE display_name LIKE '%A.R.C.H.I.E.%' LIMIT 1
) WHERE title LIKE 'Chief%'
  AND display_name NOT LIKE '%A.R.C.H.I.E.%'
  AND display_name NOT LIKE '%Vigil%'
  AND status = 'active';

-- Department heads (highest performance_score per dept, excluding C-suite and Exec Office)
-- report to ARCHIE
WITH dept_heads AS (
  SELECT DISTINCT ON (department)
    id, department
  FROM agents
  WHERE status = 'active'
    AND department != 'Executive Office'
    AND title NOT LIKE 'Chief%'
  ORDER BY department, COALESCE(performance_score, 0) DESC, id ASC
)
UPDATE agents a
SET reports_to_agent_id = (
  SELECT id FROM agents WHERE display_name LIKE '%A.R.C.H.I.E.%' LIMIT 1
)
FROM dept_heads dh
WHERE a.id = dh.id;

-- Everyone else (non-C-suite, non-Exec Office) reports to their department head
WITH dept_heads AS (
  SELECT DISTINCT ON (department)
    id, department
  FROM agents
  WHERE status = 'active'
    AND department != 'Executive Office'
    AND title NOT LIKE 'Chief%'
  ORDER BY department, COALESCE(performance_score, 0) DESC, id ASC
)
UPDATE agents a
SET reports_to_agent_id = dh.id
FROM dept_heads dh
WHERE a.department = dh.department
  AND a.id != dh.id
  AND a.status = 'active'
  AND a.department != 'Executive Office'
  AND a.title NOT LIKE 'Chief%';

-- Executive Office staff (non-C-suite, non-ARCHIE, non-Vigil) report to ARCHIE
UPDATE agents SET reports_to_agent_id = (
  SELECT id FROM agents WHERE display_name LIKE '%A.R.C.H.I.E.%' LIMIT 1
) WHERE department = 'Executive Office'
  AND title NOT LIKE 'Chief%'
  AND display_name NOT LIKE '%A.R.C.H.I.E.%'
  AND display_name NOT LIKE '%Vigil%'
  AND status = 'active'
  AND reports_to_agent_id IS NULL;

-- ============================================================
-- STEP 3: Fix emails for anyone still missing
-- ============================================================

UPDATE agents SET email = LOWER(
  CASE
    WHEN display_name LIKE '% (%' THEN
      REPLACE(LOWER(SPLIT_PART(display_name, ' (', 1)), ' ', '.') || '@kytranempowerment.com'
    WHEN display_name LIKE '% %' THEN
      REPLACE(LOWER(display_name), ' ', '.') || '@kytranempowerment.com'
    ELSE
      LOWER(COALESCE(display_name, name)) || '@kytranempowerment.com'
  END
) WHERE status = 'active' AND (email IS NULL OR email = '');

COMMIT;
