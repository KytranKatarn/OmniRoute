-- 482: indexes for the Phase 4 cockpit read endpoints (#6653)
--
-- get_agent_recent_work (services/agent_service.py) runs
--   SELECT ... FROM task_execution_log WHERE agent_id = %s ORDER BY id DESC LIMIT 5
-- Measured 2026-09-10: 0.17 ms for agent 2 vs 88,399 ms for agent 16
-- (1,517,807 rows filtered by a backward walk of the PK). A composite
-- (agent_id, id DESC) index makes both a sub-millisecond index walk.
--
-- GET /api/internal/cloud-code/runs filters bridge_jobs by job_type and
-- orders by id DESC; measured 1.2 s parallel seq scan per call.
--
-- NOTE: plain CREATE INDEX (not CONCURRENTLY) is used deliberately. The
-- migration runner wraps each file in a transaction, where CREATE INDEX
-- CONCURRENTLY errors ("cannot run inside a transaction block") and a
-- failed CONCURRENTLY build leaves an INVALID index behind — precedent
-- 470_knowledge_search_trgm.sql. On a live table of this size, build each
-- index BY HAND first in psql autocommit with
--   CREATE INDEX CONCURRENTLY IF NOT EXISTS <same name> ON ...;
-- verify pg_index.indisvalid, and this file then no-ops via IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS idx_tel_agent_id_id_desc
    ON task_execution_log (agent_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_bridge_jobs_job_type_id_desc
    ON bridge_jobs (job_type, id DESC);
