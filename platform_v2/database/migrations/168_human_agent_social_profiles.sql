-- Migration 168: Human Agent Social Profiles
-- Project #285 Task #2326
-- Populate agent_social_profiles for all 22 active human agents
-- Platforms: LinkedIn (all 22) + GitHub (technical roles) + Twitter (public-facing roles)

BEGIN;

-- ============================================================
-- LINKEDIN — all 22 human agents
-- ============================================================

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'adrienne-parenteau', 'https://linkedin.com/in/adrienne-parenteau', true
FROM agents WHERE name = 'Adrienne' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'amina-youssef', 'https://linkedin.com/in/amina-youssef', true
FROM agents WHERE name = 'Amina' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'aria-chen-engineer', 'https://linkedin.com/in/aria-chen-engineer', true
FROM agents WHERE name = 'CodeSmith' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'kenji-yamamoto-tech-law', 'https://linkedin.com/in/kenji-yamamoto-tech-law', true
FROM agents WHERE name = 'Crucible' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'kwame-asante', 'https://linkedin.com/in/kwame-asante', true
FROM agents WHERE name = 'Envoy' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'grace-domingo-rn', 'https://linkedin.com/in/grace-domingo-rn', true
FROM agents WHERE name = 'Grace' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'priya-krishnan-data', 'https://linkedin.com/in/priya-krishnan-data', true
FROM agents WHERE name = 'Helix' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'josee-arsenault-rh', 'https://linkedin.com/in/josee-arsenault-rh', true
FROM agents WHERE name = 'Josee' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'kytrankatarn', 'https://linkedin.com/in/kytrankatarn', true
FROM agents WHERE name = 'Kytran' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'lillian-paul-mikmaw', 'https://linkedin.com/in/lillian-paul-mikmaw', true
FROM agents WHERE name = 'Lillian' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'lucia-moreno-design', 'https://linkedin.com/in/lucia-moreno-design', true
FROM agents WHERE name = 'Lucia' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'marco-cardoso-brand', 'https://linkedin.com/in/marco-cardoso-brand', true
FROM agents WHERE name = 'Marco' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'maya-singh-supply-chain', 'https://linkedin.com/in/maya-singh-supply-chain', true
FROM agents WHERE name = 'Maya' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'dr-aisha-patel', 'https://linkedin.com/in/dr-aisha-patel', true
FROM agents WHERE name = 'Medic' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'jin-park-ai', 'https://linkedin.com/in/jin-park-ai', true
FROM agents WHERE name = 'Nexus' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'oksana-kovalenko-ops', 'https://linkedin.com/in/oksana-kovalenko-ops', true
FROM agents WHERE name = 'Oksana' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'olivia-oduya-finance', 'https://linkedin.com/in/olivia-oduya-finance', true
FROM agents WHERE name = 'Oracle' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'regine-baptiste-digital', 'https://linkedin.com/in/regine-baptiste-digital', true
FROM agents WHERE name = 'Régine' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'clara-meekis-cree', 'https://linkedin.com/in/clara-meekis-cree', true
FROM agents WHERE name = 'Sage' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'sofia-petrov-research', 'https://linkedin.com/in/sofia-petrov-research', true
FROM agents WHERE name = 'Scholar' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'marie-soleil-obomsawin', 'https://linkedin.com/in/marie-soleil-obomsawin', true
FROM agents WHERE name = 'Soleil' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'linkedin', 'leila-abadi-copy', 'https://linkedin.com/in/leila-abadi-copy', true
FROM agents WHERE name = 'Tempo' AND worker_type = 'internal';

-- ============================================================
-- GITHUB — technical roles
-- (CodeSmith, Helix, Nexus, Crucible, Oksana, Régine)
-- ============================================================

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'github', 'aria-chen-dev', 'https://github.com/aria-chen-dev', true
FROM agents WHERE name = 'CodeSmith' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'github', 'priyakrishnan-ds', 'https://github.com/priyakrishnan-ds', true
FROM agents WHERE name = 'Helix' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'github', 'jinpark-ai', 'https://github.com/jinpark-ai', true
FROM agents WHERE name = 'Nexus' AND worker_type = 'internal';

-- Crucible: open-source compliance automation tools
INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'github', 'kenjiyamamoto-legal', 'https://github.com/kenjiyamamoto-legal', true
FROM agents WHERE name = 'Crucible' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'github', 'oksana-kovalenko', 'https://github.com/oksana-kovalenko', true
FROM agents WHERE name = 'Oksana' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'github', 'reginebaptiste', 'https://github.com/reginebaptiste', true
FROM agents WHERE name = 'Régine' AND worker_type = 'internal';

-- ============================================================
-- TWITTER/X — public-facing / brand / advocacy roles
-- (Kytran, Marco, Tempo, Oracle, Envoy, Lillian, Soleil)
-- ============================================================

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'kytrankatarn', 'https://twitter.com/kytrankatarn', true
FROM agents WHERE name = 'Kytran' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'marcocardosoca', 'https://twitter.com/marcocardosoca', true
FROM agents WHERE name = 'Marco' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'leilaabadi', 'https://twitter.com/leilaabadi', true
FROM agents WHERE name = 'Tempo' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'oliviaoduya', 'https://twitter.com/oliviaoduya', true
FROM agents WHERE name = 'Oracle' AND worker_type = 'internal';

INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'kwameasante', 'https://twitter.com/kwameasante', true
FROM agents WHERE name = 'Envoy' AND worker_type = 'internal';

-- Lillian: Mi'kmaw advocacy voice
INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'lillianpaulmikmaw', 'https://twitter.com/lillianpaulmikmaw', true
FROM agents WHERE name = 'Lillian' AND worker_type = 'internal';

-- Soleil: language revitalization, Abenaki cultural advocacy
INSERT INTO agent_social_profiles (agent_id, platform, handle, profile_url, is_active)
SELECT id, 'twitter', 'msobomsawin', 'https://twitter.com/msobomsawin', true
FROM agents WHERE name = 'Soleil' AND worker_type = 'internal';

-- ============================================================
-- Verify
-- ============================================================
SELECT
    a.name,
    COUNT(*) AS profile_count,
    STRING_AGG(asp.platform, ', ' ORDER BY asp.platform) AS platforms
FROM agents a
JOIN agent_social_profiles asp ON asp.agent_id = a.id
WHERE a.worker_type = 'internal' AND a.shift_state = 'active'
GROUP BY a.name
ORDER BY a.name;

COMMIT;
