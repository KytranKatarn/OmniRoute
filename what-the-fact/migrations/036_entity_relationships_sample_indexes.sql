-- 036_entity_relationships_sample_indexes.sql
-- Project #373 — chain-query API perf (party-node latency).
-- The /api/public/chain/entity/<slug> sample previously windowed ALL edges of a node
-- (row_number() OVER (PARTITION BY relationship_type ...)) just to keep 25 per type —
-- ~1.7s on a 226k-edge party node (e.g. org-conservative-party-of-canada). These
-- composite indexes let the rewritten per-type sample
--   WHERE <anchor>_entity_id = X AND relationship_type = Y ORDER BY id DESC LIMIT 25
-- run as a direct backward index scan (~ms), and turn the per-(direction,type) COUNT
-- into an index-only scan.
--
-- CONCURRENTLY = no write-lock on the live shared.entity_relationships table (the
-- ingest endpoint writes to it). NOT wrapped in a transaction (CONCURRENTLY can't be).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rel_to_type_id
    ON shared.entity_relationships (to_entity_id, relationship_type, id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_rel_from_type_id
    ON shared.entity_relationships (from_entity_id, relationship_type, id);
