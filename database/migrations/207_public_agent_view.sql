-- Migration 207: Public-safe agent directory view
-- Used by public API — NEVER expose system_prompt, model, capabilities, budget, cost, tokens

CREATE OR REPLACE VIEW public_agent_directory AS
SELECT
    a.id,
    COALESCE(
        NULLIF(TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')), ''),
        a.display_name,
        a.name
    ) AS full_name,
    a.acronym,
    a.acronym_expansion,
    a.title,
    a.department,
    a.bio,
    a.avatar_url,
    a.pronouns,
    a.status,
    a.shift_state,
    at.name AS agent_type
FROM agents a
LEFT JOIN agent_types at ON a.type_id = at.id
WHERE a.status = 'active';
