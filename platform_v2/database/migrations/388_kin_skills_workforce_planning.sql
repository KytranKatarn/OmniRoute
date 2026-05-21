-- Migration 388: Seed K.I.N. agent_skills + add workforce_planning to CAPABILITY_DEPARTMENT_MAP
-- K.I.N. (id=145, Human Resources & Culture director) had zero entries in agent_skills,
-- causing all HR capability dispatches to hit the floor fallback in smart_router.
-- workforce_planning was also missing from CAPABILITY_DEPARTMENT_MAP entirely.

INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level, can_escalate_to)
VALUES
  (145, 'workforce_planning',   'hr', 5, NULL),
  (145, 'welfare',              'hr', 5, NULL),
  (145, 'workforce_welfare',    'hr', 5, NULL),
  (145, 'hr',                   'hr', 5, NULL),
  (145, 'training',             'hr', 4, NULL),
  (145, 'coaching',             'hr', 4, NULL),
  (145, 'employee_relations',   'hr', 5, NULL),
  (145, 'habit_formation',      'hr', 3, NULL),
  (145, 'event_organization',   'hr', 3, NULL),
  (145, 'executive_scheduling', 'hr', 4, NULL)
ON CONFLICT (agent_id, skill_name) DO UPDATE
  SET proficiency_level = EXCLUDED.proficiency_level,
      skill_category    = EXCLUDED.skill_category;
