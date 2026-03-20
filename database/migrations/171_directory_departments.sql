-- Migration 171: Populate agent departments from benchmark skill data + set reporting hierarchy
-- Idempotent: safe to re-run

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 1: Build skill_category → department mapping in a temp table
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS _dept_map;
CREATE TEMP TABLE _dept_map (
    skill_category TEXT PRIMARY KEY,
    department     TEXT NOT NULL
);

INSERT INTO _dept_map (skill_category, department) VALUES
    ('analytics',        'Analytics & Intelligence'),
    ('ai',               'Analytics & Intelligence'),
    ('finance',          'Analytics & Intelligence'),
    ('engineering',      'Engineering'),
    ('devops',           'Engineering'),
    ('qa',               'Engineering'),
    ('creative',         'Creative & Design'),
    ('design',           'Creative & Design'),
    ('communications',   'Communications & Marketing'),
    ('marketing',        'Communications & Marketing'),
    ('research',         'Research & Development'),
    ('education',        'Research & Development'),
    ('security',         'Security & Compliance'),
    ('compliance',       'Security & Compliance'),
    ('governance',       'Security & Compliance'),
    ('legal',            'Security & Compliance'),
    ('operations',       'Operations & Infrastructure'),
    ('facilities',       'Operations & Infrastructure'),
    ('construction',     'Operations & Infrastructure'),
    ('manufacturing',    'Operations & Infrastructure'),
    ('logistics',        'Logistics & Supply Chain'),
    ('agriculture',      'Logistics & Supply Chain'),
    ('diplomacy',        'Diplomatic & Human Relations'),
    ('hr',               'Diplomatic & Human Relations'),
    ('community',        'Diplomatic & Human Relations'),
    ('hospitality',      'Diplomatic & Human Relations'),
    ('medical',          'Medical & Wellness'),
    ('health',           'Medical & Wellness'),
    ('wellness',         'Medical & Wellness'),
    ('customer_success', 'Customer Experience'),
    ('support',          'Customer Experience'),
    ('sales',            'Customer Experience'),
    ('documentation',    'Documentation & Knowledge'),
    ('admin',            'Documentation & Knowledge'),
    ('management',       'Documentation & Knowledge'),
    ('product',          'Documentation & Knowledge');

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 2: Normalize existing department values for all active agents
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE agents SET department = CASE
    WHEN UPPER(TRIM(department)) IN ('ANALYTICS', 'AI')
        THEN 'Analytics & Intelligence'
    WHEN UPPER(TRIM(department)) IN ('ENGINEERING', 'DEVOPS', 'QA')
        THEN 'Engineering'
    WHEN UPPER(TRIM(department)) IN ('CREATIVE', 'DESIGN')
        THEN 'Creative & Design'
    WHEN UPPER(TRIM(department)) IN ('COMMUNICATIONS', 'MARKETING')
        THEN 'Communications & Marketing'
    WHEN UPPER(TRIM(department)) IN ('RESEARCH', 'R&D', 'EDUCATION')
        THEN 'Research & Development'
    WHEN UPPER(TRIM(department)) IN ('SECURITY', 'COMPLIANCE', 'GOVERNANCE', 'LEGAL')
        THEN 'Security & Compliance'
    WHEN UPPER(TRIM(department)) IN ('OPERATIONS', 'FACILITIES', 'INFRASTRUCTURE')
        THEN 'Operations & Infrastructure'
    WHEN UPPER(TRIM(department)) IN ('LOGISTICS', 'SUPPLY CHAIN')
        THEN 'Logistics & Supply Chain'
    WHEN UPPER(TRIM(department)) IN ('DIPLOMACY', 'HR', 'HUMAN RELATIONS')
        THEN 'Diplomatic & Human Relations'
    WHEN UPPER(TRIM(department)) IN ('MEDICAL', 'HEALTH', 'WELLNESS')
        THEN 'Medical & Wellness'
    WHEN UPPER(TRIM(department)) IN ('CUSTOMER SUCCESS', 'SUPPORT', 'SALES')
        THEN 'Customer Experience'
    WHEN UPPER(TRIM(department)) IN ('DOCUMENTATION', 'ADMIN', 'KNOWLEDGE', 'MANAGEMENT')
        THEN 'Documentation & Knowledge'
    WHEN UPPER(TRIM(department)) IN ('COMMAND')
        THEN 'Operations & Infrastructure'
    ELSE department
END
WHERE status = 'active'
  AND department IS NOT NULL
  AND department != '';

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 3: For agents missing department — derive from highest-proficiency skill
-- ─────────────────────────────────────────────────────────────────────────────
WITH ranked_skills AS (
    SELECT
        s.agent_id,
        dm.department,
        ROW_NUMBER() OVER (
            PARTITION BY s.agent_id
            ORDER BY s.proficiency_level DESC, s.skill_category ASC
        ) AS rn
    FROM agent_skills s
    JOIN _dept_map dm ON dm.skill_category = s.skill_category
    WHERE s.skill_category IS NOT NULL
),
best_dept AS (
    SELECT agent_id, department
    FROM ranked_skills
    WHERE rn = 1
)
UPDATE agents a
SET department = bd.department
FROM best_dept bd
WHERE a.id = bd.agent_id
  AND a.status = 'active'
  AND (a.department IS NULL OR a.department = '');

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 4: Title-based fallback for agents still missing a department
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE agents SET department = CASE
    WHEN LOWER(title) LIKE '%engineer%' OR LOWER(title) LIKE '%developer%' OR LOWER(title) LIKE '%devops%'
        THEN 'Engineering'
    WHEN LOWER(title) LIKE '%analytic%' OR LOWER(title) LIKE '%intelligence%' OR LOWER(title) LIKE '%data%'
        THEN 'Analytics & Intelligence'
    WHEN LOWER(title) LIKE '%creative%' OR LOWER(title) LIKE '%design%' OR LOWER(title) LIKE '%artist%'
        THEN 'Creative & Design'
    WHEN LOWER(title) LIKE '%communicat%' OR LOWER(title) LIKE '%market%' OR LOWER(title) LIKE '%media%'
        THEN 'Communications & Marketing'
    WHEN LOWER(title) LIKE '%research%' OR LOWER(title) LIKE '%scientist%' OR LOWER(title) LIKE '%educat%'
        THEN 'Research & Development'
    WHEN LOWER(title) LIKE '%security%' OR LOWER(title) LIKE '%compliance%' OR LOWER(title) LIKE '%legal%' OR LOWER(title) LIKE '%ethics%'
        THEN 'Security & Compliance'
    WHEN LOWER(title) LIKE '%operation%' OR LOWER(title) LIKE '%infrastructure%' OR LOWER(title) LIKE '%facilit%'
        THEN 'Operations & Infrastructure'
    WHEN LOWER(title) LIKE '%logistic%' OR LOWER(title) LIKE '%supply%'
        THEN 'Logistics & Supply Chain'
    WHEN LOWER(title) LIKE '%diplomat%' OR LOWER(title) LIKE '%human resource%' OR LOWER(title) LIKE '%community%'
        THEN 'Diplomatic & Human Relations'
    WHEN LOWER(title) LIKE '%medical%' OR LOWER(title) LIKE '%health%' OR LOWER(title) LIKE '%wellness%'
        THEN 'Medical & Wellness'
    WHEN LOWER(title) LIKE '%customer%' OR LOWER(title) LIKE '%support%' OR LOWER(title) LIKE '%sales%'
        THEN 'Customer Experience'
    WHEN LOWER(title) LIKE '%document%' OR LOWER(title) LIKE '%knowledge%' OR LOWER(title) LIKE '%admin%'
        THEN 'Documentation & Knowledge'
    ELSE 'Operations & Infrastructure'
END
WHERE status = 'active'
  AND (department IS NULL OR department = '');

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 5: Force ARCHIE & Vigil to known departments
-- ─────────────────────────────────────────────────────────────────────────────
-- ARCHIE is AI Director — Analytics & Intelligence is most fitting non-Command dept
UPDATE agents SET department = 'Analytics & Intelligence'
WHERE id = 2; -- A.R.C.H.I.E.

-- Vigil is Ethics/Security Officer
UPDATE agents SET department = 'Security & Compliance'
WHERE id = 3; -- Vigil

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 6: Set reporting hierarchy
-- ─────────────────────────────────────────────────────────────────────────────

-- Clear all existing hierarchy (idempotent reset)
UPDATE agents SET reports_to_agent_id = NULL WHERE status = 'active';

-- ARCHIE reports to nobody (he's the AI Director)
-- (already NULL after reset)

-- Vigil reports to ARCHIE
UPDATE agents SET reports_to_agent_id = 2
WHERE id = 3; -- Vigil → ARCHIE

-- Find department heads: highest performance_score per department
-- excluding ARCHIE (id=2), Vigil (id=3), and agents with department NULL
WITH dept_heads AS (
    SELECT DISTINCT ON (department)
        id,
        department,
        COALESCE(performance_score, 0) AS perf
    FROM agents
    WHERE status = 'active'
      AND id NOT IN (2, 3)
      AND department IS NOT NULL
      AND department != ''
    ORDER BY department, COALESCE(performance_score, 0) DESC, id ASC
)
-- Department heads report to ARCHIE
UPDATE agents a
SET reports_to_agent_id = 2
FROM dept_heads dh
WHERE a.id = dh.id;

-- All other agents report to their department head
WITH dept_heads AS (
    SELECT DISTINCT ON (department)
        id AS head_id,
        department
    FROM agents
    WHERE status = 'active'
      AND id NOT IN (2, 3)
      AND department IS NOT NULL
      AND department != ''
    ORDER BY department, COALESCE(performance_score, 0) DESC, id ASC
)
UPDATE agents a
SET reports_to_agent_id = dh.head_id
FROM dept_heads dh
WHERE a.department = dh.department
  AND a.status = 'active'
  AND a.id NOT IN (2, 3)       -- not ARCHIE or Vigil
  AND a.id != dh.head_id       -- not the head themselves
  AND a.reports_to_agent_id IS NULL; -- not already set

-- Vigil already set above; ensure her chain is intact
-- (Vigil reports to ARCHIE regardless of dept head)

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 7: Verify summary
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    missing_dept  INTEGER;
    missing_chain INTEGER;
BEGIN
    SELECT COUNT(*) INTO missing_dept
    FROM agents
    WHERE status = 'active' AND (department IS NULL OR department = '');

    SELECT COUNT(*) INTO missing_chain
    FROM agents
    WHERE status = 'active'
      AND id NOT IN (2)          -- ARCHIE is exempt
      AND reports_to_agent_id IS NULL;

    RAISE NOTICE 'Migration 171 complete — agents missing department: %, missing reports_to: %',
        missing_dept, missing_chain;
END $$;
