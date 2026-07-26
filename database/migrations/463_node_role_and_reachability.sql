-- 463 — separate "an agent phoned home" from "this node is reachable" (task #5218)
--
-- INCIDENT 2026-07-26. remote_nodes.status was wrong in BOTH directions inside one hour:
--
--   FALSE ONLINE  — both Starships showed status='online' with 1-minute-old heartbeats
--                   while their MESH IPs were unreachable and dispatch could not land.
--                   They heartbeat over the LAN (192.168.1.246/.245); dispatch routes over
--                   the mesh. Nothing checked the path the traffic actually uses.
--
--   FALSE OFFLINE — Beacon showed status='offline' with last_heartbeat frozen at the
--                   power-down, while headscale reported it online, it answered ping, and
--                   it was serving live public traffic. Beacon runs NO node agent BY DESIGN
--                   ("no Ollama/agents, bridge_off") yet is registered as a full node, so it
--                   is judged by a signal it structurally cannot send. Its status could
--                   never recover on its own.
--
-- "beacon and citadel are down" sent the investigation to the nodes when the fault was
-- entirely hub-side. Same family as #5214/#5215: a status that outlived, or never measured,
-- the evidence.
--
-- This migration adds the missing VOCABULARY. The behaviour lives in
-- services/node_reachability.py + the two fleet health jobs.

-- ---------------------------------------------------------------------------
-- node_role — what this node is FOR, and therefore what may fairly judge it.
--   'agent'   (default) runs a node agent + inference; heartbeat is meaningful.
--   'ingress' front door / relay (Beacon). Serves traffic, runs no agent. Judging
--             it by heartbeat is a category error — measure REACHABILITY instead.
-- ---------------------------------------------------------------------------
ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS node_role VARCHAR(20) NOT NULL DEFAULT 'agent';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'remote_nodes_node_role_chk'
    ) THEN
        ALTER TABLE remote_nodes
            ADD CONSTRAINT remote_nodes_node_role_chk
            CHECK (node_role IN ('agent', 'ingress'));
    END IF;
END$$;

-- ---------------------------------------------------------------------------
-- reachable_port — WHICH port answered on the last successful reachability probe.
-- The probe used to TCP-connect to mesh_ip:11434 (Ollama) and call that
-- "mesh_status". That is an INFERENCE-CAPABILITY check, not a reachability check:
-- Beacon deliberately runs no Ollama, so it could never pass, and the mesh signal
-- was as structurally broken as the heartbeat one. Recording the port that answered
-- keeps the distinction visible rather than implied.
-- ---------------------------------------------------------------------------
ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS reachable_port INTEGER;

COMMENT ON COLUMN remote_nodes.node_role IS
    'agent = runs a node agent, heartbeat is meaningful. ingress = front door/relay '
    '(Beacon): serves traffic, runs no agent, MUST be judged by reachability not heartbeat. #5218';
COMMENT ON COLUMN remote_nodes.reachable_port IS
    'Port that answered the last successful mesh reachability probe. NULL = unreachable '
    'or never probed. Distinguishes "host is up" from "Ollama is up". #5218';
COMMENT ON COLUMN remote_nodes.status IS
    'AGENT LIVENESS (did a node agent phone home recently) — NOT reachability. For '
    'reachability read mesh_status/mesh_last_seen. An agent can heartbeat over the LAN '
    'while the MESH path dispatch uses is dead. #5218';

-- Beacon is the ingress node. Idempotent, keyed on the stable node_id (never the int PK —
-- passing the int id to a varchar node_id predicate aborts the txn, see fleet.md).
UPDATE remote_nodes
   SET node_role = 'ingress'
 WHERE node_id = 'beacon_01699263f6cd9dc9'
   AND node_role <> 'ingress';

CREATE INDEX IF NOT EXISTS idx_remote_nodes_node_role ON remote_nodes (node_role);
