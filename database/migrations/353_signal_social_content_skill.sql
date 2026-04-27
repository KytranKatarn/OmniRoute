-- Migration 353: Seed S.I.G.N.A.L. social_content skill
-- Adds exact capability string used by department_dispatcher.dispatch(capability='social_content')
-- S.I.G.N.A.L. (id=141) — Marketing & Communications director

INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
VALUES (141, 'social_content', 'marketing', 5)
ON CONFLICT (agent_id, skill_name) DO UPDATE
    SET proficiency_level = 5,
        skill_category    = 'marketing';

-- Upgrade existing social_media to Lv5
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
VALUES (141, 'social_media', 'marketing', 5)
ON CONFLICT (agent_id, skill_name) DO UPDATE
    SET proficiency_level = 5,
        skill_category    = 'marketing';

-- Add social_scheduling for weekly job dispatch
INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
VALUES (141, 'social_scheduling', 'marketing', 5)
ON CONFLICT (agent_id, skill_name) DO UPDATE
    SET proficiency_level = 5,
        skill_category    = 'marketing';
