-- 462_news_media_bridge_station.sql
--
-- Add the missing NEWS bridge station for the News & Media department (#5157).
--
-- WHY THIS ROW WAS MISSING
-- News & Media was added as the 17th department on 2026-04-14, after
-- bridge_stations had been seeded. Nothing back-filled a station row for it, so
-- it is the ONLY department of the 17 with no station — 16/16 others match.
--
-- WHY IT MATTERS NOW
-- station_assignments was DROPPED when agents moved to belonging to departments.
-- Since PR #2452 the station -> agent link is derived as
--     bridge_stations.station_name = agents.department
-- and the station's primary is the agent with is_department_ai. A department with
-- no station row therefore resolves to NO agent for every module it should own:
-- /api/module-agents returns {"agent_name": null}, and get_station_assignments
-- cannot see the crew. That degrades cleanly (it does not throw — pinned by
-- tests/test_dropped_station_assignments.py) but it is still wrong.
--
-- station_name MUST be exactly 'News & Media' — it is the join key against
-- agents.department, which is itself constrained by chk_agents_department to the
-- 17 canonical department names. Any drift here silently empties the station.
--
-- MODULES
-- 'wtf_hub' only. It is the What The Fact hub module and is currently claimed by
-- no station. Deliberately NOT claimed here:
--   * media_hub    — already owned by CREATIVE. M.A.V.E.N. sits in News & Media,
--                    so that mapping is arguably wrong, but re-homing a module
--                    that another station already serves is a separate decision
--                    and would silently change /api/module-agents for it.
--   * mailbox_story (Chronicle) — an admin-only cross-source person hub, closer
--                    to Documentation & Knowledge than to news production.
-- Adding a module later is a one-line array update, so this starts conservative.
--
-- COSMETICS follow the 9 most recent station rows (LOGISTICS, DIPLOMATIC, HR,
-- ...): position 0/0, max_primary 2, max_auxiliary 1, allow_overflow true,
-- default_llm left NULL (routing is chosen by the dispatcher, not pinned here).
-- Colour #0EA5E9 is not used by any existing station.
--
-- Idempotent via the UNIQUE (station_code) constraint. Re-running only refreshes
-- the descriptive columns; it never disturbs position or capacity, which an
-- operator may have tuned in the UI.

INSERT INTO bridge_stations (
    station_code, station_name, full_name, description,
    color, icon, default_llm, modules,
    position_row, position_order, max_primary, max_auxiliary,
    allow_overflow, is_active
)
VALUES (
    'NEWS',
    'News & Media',
    'News & Media',
    'Newsroom: ingestion, bias analysis, fact-checking and publication for the What The Fact products.',
    '#0EA5E9',
    '📰',
    NULL,
    ARRAY['wtf_hub'],
    0, 0, 2, 1,
    TRUE, TRUE
)
ON CONFLICT (station_code) DO UPDATE
SET station_name = EXCLUDED.station_name,
    full_name    = EXCLUDED.full_name,
    description  = EXCLUDED.description,
    color        = EXCLUDED.color,
    icon         = EXCLUDED.icon,
    modules      = EXCLUDED.modules,
    is_active    = TRUE,
    updated_at   = NOW();

-- Verification (informational; safe to re-run):
--   SELECT bs.station_code, a.name, a.is_department_ai
--   FROM bridge_stations bs
--   JOIN agents a ON a.department = bs.station_name
--                AND a.worker_type = 'ai' AND a.status = 'active'
--   WHERE bs.station_code = 'NEWS'
--   ORDER BY a.is_department_ai DESC;
-- Expect F.A.C.T. first (the News & Media department AI), then the newsroom crew.
