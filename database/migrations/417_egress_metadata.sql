-- Migration 417: egress_metadata on remote_nodes for external_fetch routing (#2881/#2884)
-- Adds per-node egress profile: regions, residential flag, datacenter flag.
-- Heartbeat updates this on every sync; seeds below cover the current fleet.

ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS egress_metadata JSONB DEFAULT '{}';

-- Hub (Archie Starbase) — residential CA/US IP, best for gov API scraping
UPDATE remote_nodes
SET egress_metadata = '{"egress_regions":["CA","US"],"residential":true,"datacenter_ip":false}'
WHERE id = 68;

-- Outpost - United States (Ashburn VA datacenter)
UPDATE remote_nodes
SET egress_metadata = '{"egress_regions":["US"],"residential":false,"datacenter_ip":true}'
WHERE id = 93;

-- Outpost - Singapore
UPDATE remote_nodes
SET egress_metadata = '{"egress_regions":["SG","ASIA"],"residential":false,"datacenter_ip":true}'
WHERE id = 125;

-- Outpost - Lithuania
UPDATE remote_nodes
SET egress_metadata = '{"egress_regions":["LT","EU"],"residential":false,"datacenter_ip":true}'
WHERE id = 126;

-- Outpost - United Kingdom
UPDATE remote_nodes
SET egress_metadata = '{"egress_regions":["GB","EU"],"residential":false,"datacenter_ip":true}'
WHERE id = 127;

-- Citadel - United States (boston-2, DR standby — not a scraping egress node)
UPDATE remote_nodes
SET egress_metadata = '{"egress_regions":["US"],"residential":false,"datacenter_ip":true}'
WHERE id = 128;
