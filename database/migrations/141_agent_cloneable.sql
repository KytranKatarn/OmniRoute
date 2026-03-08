-- Migration 141: Agent cloneability classification
-- Hub-only singletons (ARCHIE, Vigil, Kytran) never cloned to nodes.

ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_cloneable BOOLEAN DEFAULT true;

-- Mark hub-only singletons
UPDATE agents SET is_cloneable = false WHERE id IN (2, 3);
UPDATE agents SET is_cloneable = false WHERE name ILIKE '%kytran%';

-- Clean up existing bad clones
DELETE FROM node_agents
WHERE source_agent_id IN (SELECT id FROM agents WHERE is_cloneable = false);
