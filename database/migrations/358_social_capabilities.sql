-- database/migrations/358_social_capabilities.sql
-- Seed social media capabilities on S.I.G.N.A.L. (141), A.R.C.H.I.E. (2), B.A.S.E. (139)

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
VALUES
    (141, 'social_post_draft',        5, NULL),
    (2,   'social_post_approve',      5, NULL),
    (139, 'social_account_provision', 5, NULL)
ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level;
