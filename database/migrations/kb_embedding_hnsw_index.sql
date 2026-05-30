-- #3522 — Migrate knowledge_base vector index from ivfflat → HNSW.
--
-- Why: idx_kb_embedding was ivfflat WITH (lists=100), built when the table was
-- far smaller and never rebuilt as it grew to ~30K rows. Recall became stale and
-- NON-MONOTONIC (probes=20 found a target, probes=40 missed it, 100 found it) and
-- the default probes=1 silently dropped best matches. HNSW has no lists to size,
-- does not degrade as data grows, and needs no periodic REINDEX.
--
-- Runtime recall knob changes from `ivfflat.probes` to `hnsw.ef_search` (set in
-- tools/consciousness/memory_service.semantic_search).
--
-- NOTE (operational): a PARALLEL HNSW build needs a large /dev/shm segment which
-- the postgres container does not have (failed with "could not resize shared
-- memory segment"). Build with parallel workers OFF so it uses backend-local
-- maintenance_work_mem instead. ~24s for 30K rows on this host.

SET max_parallel_maintenance_workers = 0;
SET maintenance_work_mem = '256MB';

-- Build HNSW first (CONCURRENTLY in prod to avoid locking; plain CREATE in a
-- fresh DB is fine). IF NOT EXISTS makes this idempotent.
CREATE INDEX IF NOT EXISTS idx_kb_embedding_hnsw
  ON knowledge_base USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Drop the stale ivfflat index once HNSW exists.
DROP INDEX IF EXISTS idx_kb_embedding;
