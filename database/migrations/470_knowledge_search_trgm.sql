-- 470_knowledge_search_trgm.sql
-- Consciousness: trigram (pg_trgm) GIN indexes on knowledge_base title/content
-- to back ILIKE/substring knowledge search (quick-wins audit, Dev HQ task #5706).
--
-- WHY: knowledge search over ~38k rows does sequential ILIKE scans on title and
-- content; gin_trgm_ops indexes make those searches index-assisted.
--
-- NOTE: plain CREATE INDEX (not CONCURRENTLY) is used deliberately. This repo
-- has NO automated migration runner — migrations are applied by hand via
-- `docker exec archie_database psql ... -f <file>` and are sometimes piped
-- inside explicit transactions (see .claude/rules/database.md heredoc pattern),
-- where CREATE INDEX CONCURRENTLY would error ("cannot run inside a transaction
-- block") and a failed CONCURRENTLY build leaves an INVALID index that
-- IF NOT EXISTS then silently skips. At ~38k rows the plain build takes seconds
-- and the brief lock is acceptable.
--
-- Idempotent: IF NOT EXISTS on both the extension and the indexes.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_knowledge_base_title_trgm
    ON knowledge_base USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_content_trgm
    ON knowledge_base USING gin (content gin_trgm_ops);
