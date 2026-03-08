-- Migration 142: Pre-populate OPERATIONS + ENGINEERING stations for approved remote nodes
-- Part of the Starship Station Terminals feature — ensures all approved nodes
-- have station assignments for the two initial LCARS terminals.
-- Idempotent: ON CONFLICT DO NOTHING skips existing assignments.

INSERT INTO node_station_assignments (node_id, station_id, is_active)
SELECT rn.id, bs.id, true
FROM remote_nodes rn
CROSS JOIN bridge_stations bs
WHERE rn.status = 'approved'
  AND bs.station_code IN ('OPERATIONS', 'ENGINEERING')
  AND bs.is_active = true
ON CONFLICT DO NOTHING;
