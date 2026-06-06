-- 420_codex_ro_role.sql
-- Read-only Postgres role for the Codex MCP gateway (Phase: codex containerized context).
-- The gateway connects as codex_ro so that even if its credentials leak, the blast
-- radius is read-only KB access. The MCP read tools (search_knowledge, recall_context)
-- SELECT from knowledge_base and bump knowledge_base.access_count/last_accessed, so we
-- grant SELECT + a NARROW column UPDATE on just those two counter columns — nothing else.
-- Idempotent. Password is NOT set here (never commit secrets); set out-of-band via:
--   ALTER ROLE codex_ro WITH LOGIN PASSWORD '<from secrets/codex/db_ro_password.txt>';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'codex_ro') THEN
        CREATE ROLE codex_ro NOLOGIN;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE archie TO codex_ro;
GRANT USAGE  ON SCHEMA public     TO codex_ro;

-- Read access to the knowledge base (the only table the read tools SELECT from).
GRANT SELECT ON knowledge_base TO codex_ro;

-- The read handlers bump an access counter; allow ONLY those two columns to be updated.
GRANT UPDATE (access_count, last_accessed) ON knowledge_base TO codex_ro;

-- Explicitly ensure no write surface elsewhere: codex_ro gets nothing on other tables.
-- (No GRANTs beyond the above; default-deny applies to every other object.)
