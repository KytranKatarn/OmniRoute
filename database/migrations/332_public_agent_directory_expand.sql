-- Migration 332: expand public_agent_directory view for directory consolidation
--
-- Context: two public directory endpoints existed with different shapes —
--   1. /tools/department-hq/api/agents/public-roster (rich: display_name,
--      code_name, floor, is_department_ai, worker_type, avatar_thumb_url)
--   2. /api/public/directory (lean: full_name, acronym, agent_type only)
--
-- Project #262 consolidates to one canonical endpoint at
-- /api/public/directory backed by this view. The view is the schema-level
-- single source of truth for "what's public about an agent".
--
-- Changes:
--   - Add: display_name, code_name (agents.name), floor, is_department_ai,
--          worker_type
--   - Filter: shift_state != 'decommissioned' (matches public-roster;
--     previously filtered status='active' which excluded barracked agents)

DROP VIEW IF EXISTS public_agent_directory;

CREATE VIEW public_agent_directory AS
SELECT
    a.id,
    COALESCE(
        NULLIF(
            TRIM(
                COALESCE(a.first_name, '')::text
                || ' '
                || COALESCE(a.last_name, '')::text
            ),
            ''
        ),
        a.display_name::text,
        a.name::text
    ) AS full_name,
    a.display_name,
    a.name AS code_name,
    a.acronym,
    a.acronym_expansion,
    a.title,
    a.department,
    a.floor,
    a.bio,
    a.avatar_url,
    a.pronouns,
    a.status,
    a.shift_state,
    a.worker_type,
    a.is_department_ai,
    at.name AS agent_type
FROM agents a
LEFT JOIN agent_types at ON a.type_id = at.id
WHERE a.shift_state::text != 'decommissioned'
ORDER BY
    CASE a.floor
        WHEN 'BRIDGE' THEN 1
        WHEN 'OPERATIONS' THEN 2
        WHEN 'ENGINEERING' THEN 3
        WHEN 'CREATIVE' THEN 4
        WHEN 'SERVICES' THEN 5
        ELSE 6
    END,
    a.department,
    a.is_department_ai DESC,
    a.display_name;

COMMENT ON VIEW public_agent_directory IS
    'Schema-level source of truth for the public agent directory. '
    'Consumed by services/public_roster_service.py which powers '
    '/api/public/directory and /api/public/directory/live. '
    'Excludes decommissioned agents. Migration 332.';
