-- Migration 051: Restructure KYTRAN-StarShip to 5 GPU-optimized agents, 3 stations
-- Node ID: 67 (node_7e33e91ba868d446), Hardware: RTX 3070 8GB, i9-12900K, 32GB RAM
-- Target: 5 agents fitting in 8GB VRAM, 3 stations (COMMAND, ENGINEERING, OPERATIONS)
-- Idempotent: safe to run multiple times

BEGIN;

-- Step 1: Remove 6 agents that don't fit the GPU node profile
-- CommRelay (phi4:14b) — too large for 8GB VRAM
-- DataMind (qwen25-classify) — embedding model, better on hub
-- Nexus (arctic-embed-cpu) — CPU-only embedding model
-- Wordsmith (gemma3:12b) — too large alongside other models
-- Compass (aya:8b) — no hub_agent_id linked
-- Titan (qwen3-coder-cpu) — 51.7GB, way too large
DELETE FROM node_agents
WHERE node_id = 67
  AND id IN (48, 49, 50, 51, 54, 55);

-- Step 2: Update station_codes for kept agents
-- CodeSmith (id 45) — captain, COMMAND only
UPDATE node_agents SET station_codes = '{COMMAND}'
WHERE id = 45 AND node_id = 67;

-- Atom (id 53) — first officer, COMMAND only
UPDATE node_agents SET station_codes = '{COMMAND}'
WHERE id = 53 AND node_id = 67;

-- Architect (id 46) — ENGINEERING
UPDATE node_agents SET station_codes = '{ENGINEERING}'
WHERE id = 46 AND node_id = 67;

-- Pixel (id 52) — ENGINEERING (vision model, GPU accelerated)
UPDATE node_agents SET station_codes = '{ENGINEERING}'
WHERE id = 52 AND node_id = 67;

-- OpsMaster (id 47) — OPERATIONS
UPDATE node_agents SET station_codes = '{OPERATIONS}'
WHERE id = 47 AND node_id = 67;

-- Step 3: Rebuild node_station_assignments for node 67
-- Clear old assignments
DELETE FROM node_station_assignments WHERE node_id = 67;

-- COMMAND station (bridge_stations id=1)
INSERT INTO node_station_assignments (node_id, station_id, role, priority, is_active, notes)
VALUES (67, 1, 'command', 10, true, 'KYTRAN-StarShip command deck — CodeSmith (captain) + Atom (first officer)')
ON CONFLICT (node_id, station_id) DO UPDATE SET
  role = EXCLUDED.role,
  priority = EXCLUDED.priority,
  is_active = EXCLUDED.is_active,
  notes = EXCLUDED.notes;

-- ENGINEERING station (bridge_stations id=6)
INSERT INTO node_station_assignments (node_id, station_id, role, priority, is_active, notes)
VALUES (67, 6, 'operations', 10, true, 'KYTRAN-StarShip engineering — Architect + Pixel (GPU-accelerated)')
ON CONFLICT (node_id, station_id) DO UPDATE SET
  role = EXCLUDED.role,
  priority = EXCLUDED.priority,
  is_active = EXCLUDED.is_active,
  notes = EXCLUDED.notes;

-- OPERATIONS station (bridge_stations id=5)
INSERT INTO node_station_assignments (node_id, station_id, role, priority, is_active, notes)
VALUES (67, 5, 'operations', 10, true, 'KYTRAN-StarShip operations — OpsMaster')
ON CONFLICT (node_id, station_id) DO UPDATE SET
  role = EXCLUDED.role,
  priority = EXCLUDED.priority,
  is_active = EXCLUDED.is_active,
  notes = EXCLUDED.notes;

COMMIT;
