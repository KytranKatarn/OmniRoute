-- Migration 120: Add network_type and ssh_enabled to remote_nodes
-- Supports local vs external node detection and SSH toggle feature

ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS network_type VARCHAR(20) DEFAULT 'local'
        CHECK (network_type IN ('local', 'external', 'vpn')),
    ADD COLUMN IF NOT EXISTS ssh_enabled BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ssh_enabled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ssh_auto_disable_at TIMESTAMPTZ;

-- Backfill existing nodes as local (they're all on the LAN)
UPDATE remote_nodes SET network_type = 'local' WHERE network_type IS NULL;

COMMENT ON COLUMN remote_nodes.network_type IS 'local=LAN, external=public IP, vpn=WireGuard tunnel';
COMMENT ON COLUMN remote_nodes.ssh_enabled IS 'Whether SSH support access is currently enabled on this node';
