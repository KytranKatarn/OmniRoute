-- Migration 107: Agent Identity — Diverse Names
-- Hand-curated first/last names for team member agents

-- Add name columns if not present
ALTER TABLE agents ADD COLUMN IF NOT EXISTS first_name VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_name VARCHAR(50);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS display_name VARCHAR(100);

-- Reset display_name for agents that got fallback names (display_name = name)
UPDATE agents SET first_name = NULL, last_name = NULL, display_name = NULL
    WHERE display_name = name AND name != 'ARCHIE';

-- Assign names to existing agents (by actual codename in DB)
-- ARCHIE (id=2) keeps as-is — she IS the platform
UPDATE agents SET first_name = 'Vigil', last_name = '', display_name = 'Vigil (Sentinel)'
    WHERE name = 'Sentinel' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Aria', last_name = 'Chen', display_name = 'Aria Chen (CodeSmith)'
    WHERE name = 'CodeSmith' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Marcus', last_name = 'Rivera', display_name = 'Marcus Rivera (Architect)'
    WHERE name = 'Architect' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Liam', last_name = 'O''Brien', display_name = 'Liam O''Brien (OpsMaster)'
    WHERE name = 'OpsMaster' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Nia', last_name = 'Williams', display_name = 'Nia Williams (CommRelay)'
    WHERE name = 'CommRelay' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Amara', last_name = 'Osei', display_name = 'Amara Osei (DataMind)'
    WHERE name = 'DataMind' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Jin', last_name = 'Park', display_name = 'Jin Park (Nexus)'
    WHERE name = 'Nexus' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Dante', last_name = 'Morales', display_name = 'Dante Morales (Wordsmith)'
    WHERE name = 'Wordsmith' AND (first_name IS NULL OR first_name = name);

UPDATE agents SET first_name = 'Sofia', last_name = 'Petrov', display_name = 'Sofia Petrov (Scholar)'
    WHERE name = 'Scholar' AND (first_name IS NULL OR first_name = name);

-- For any remaining unnamed agents, set display_name = name
UPDATE agents SET display_name = name WHERE display_name IS NULL;
