-- Phase 3: Add location and type metadata to remote_nodes
-- Idempotent: uses IF NOT EXISTS

ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS location_label VARCHAR(100);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS node_type VARCHAR(20) DEFAULT 'starship';

-- Backfill existing nodes
UPDATE remote_nodes SET location_label = 'Toronto, Canada' WHERE hostname = '192.168.1.200' AND location_label IS NULL;
UPDATE remote_nodes SET location_label = 'US East (Hostinger)', node_type = 'outpost' WHERE hostname LIKE '76.%' AND location_label IS NULL;
UPDATE remote_nodes SET node_type = 'starship' WHERE node_type IS NULL;
