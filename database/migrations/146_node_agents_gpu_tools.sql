-- Migration 146: Add gpu_tools column to node_agents
-- Stores GPU tool configuration (e.g. ComfyUI) per agent
-- Idempotent: safe to re-run

ALTER TABLE node_agents ADD COLUMN IF NOT EXISTS gpu_tools jsonb DEFAULT '[]'::jsonb;

-- Set Iris (KYTRAN-StarShip) as ComfyUI agent
UPDATE node_agents
SET gpu_tools = '[{"provider": "comfyui", "type": "image_generation"}]'::jsonb
WHERE name = 'Iris' AND node_id = 67 AND gpu_tools = '[]'::jsonb;
