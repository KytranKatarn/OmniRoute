-- Migration 181: VPN mesh support for Headscale integration
-- Adds mesh networking fields to remote_nodes and creates mesh health tracking tables

-- Add mesh networking columns to remote_nodes
ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS mesh_ip VARCHAR(45),
    ADD COLUMN IF NOT EXISTS mesh_hostname VARCHAR(255),
    ADD COLUMN IF NOT EXISTS mesh_status VARCHAR(20) DEFAULT 'disconnected',
    ADD COLUMN IF NOT EXISTS mesh_last_seen TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS mesh_latency_ms INTEGER,
    ADD COLUMN IF NOT EXISTS mesh_connection_type VARCHAR(20),
    ADD COLUMN IF NOT EXISTS headscale_node_id VARCHAR(64);

-- Add constraints (safe — won't fail if values already valid)
DO $$ BEGIN
    ALTER TABLE remote_nodes
        ADD CONSTRAINT chk_mesh_status
        CHECK (mesh_status IN ('connected', 'disconnected', 'relay', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE remote_nodes
        ADD CONSTRAINT chk_mesh_connection_type
        CHECK (mesh_connection_type IS NULL OR mesh_connection_type IN ('direct', 'relay'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Mesh health log — VPN-layer health tracking (separate from app heartbeats)
CREATE TABLE IF NOT EXISTS mesh_health_log (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    mesh_ip VARCHAR(45),
    latency_ms INTEGER,
    connection_type VARCHAR(20),
    is_reachable BOOLEAN DEFAULT TRUE,
    checked_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mesh_health_node_time
    ON mesh_health_log(node_id, checked_at DESC);

-- Headscale auth keys — track pre-auth keys for node registration
CREATE TABLE IF NOT EXISTS headscale_authkeys (
    id SERIAL PRIMARY KEY,
    key_prefix VARCHAR(20) NOT NULL,
    key_hash VARCHAR(256) NOT NULL,
    created_by INTEGER REFERENCES users(id),
    is_ephemeral BOOLEAN DEFAULT TRUE,
    is_reusable BOOLEAN DEFAULT FALSE,
    is_used BOOLEAN DEFAULT FALSE,
    used_by_node INTEGER REFERENCES remote_nodes(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_headscale_authkeys_unused
    ON headscale_authkeys(is_used, expires_at)
    WHERE is_used = FALSE;

COMMENT ON COLUMN remote_nodes.mesh_ip IS 'Headscale/Tailscale VPN IP (100.64.x.x range)';
COMMENT ON COLUMN remote_nodes.mesh_hostname IS 'Headscale MagicDNS hostname (e.g. node-246.mesh.archie)';
COMMENT ON COLUMN remote_nodes.mesh_status IS 'VPN mesh connection: connected, disconnected, relay, unknown';
COMMENT ON COLUMN remote_nodes.mesh_connection_type IS 'direct = peer-to-peer WireGuard, relay = via DERP server';
COMMENT ON TABLE mesh_health_log IS 'VPN mesh health checks — latency and reachability per node';
COMMENT ON TABLE headscale_authkeys IS 'Pre-auth keys for Headscale node registration';
