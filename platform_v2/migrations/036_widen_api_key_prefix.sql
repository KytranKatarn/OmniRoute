-- Migration 036: Widen mcp_api_keys.key_prefix to VARCHAR(16)
-- Reason: handler generates "arch_" + 6 random chars = 11 chars, but column was VARCHAR(10),
-- causing every POST /api/api-keys to 500 with "value too long for type character varying(10)".
-- Idempotent — ALTER COLUMN TYPE is a no-op if already wide enough.

-- Covers every schema that has a mcp_api_keys table (public, sandbox, tenant_*).
DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT table_schema
        FROM information_schema.columns
        WHERE table_name = 'mcp_api_keys'
          AND column_name = 'key_prefix'
          AND character_maximum_length < 16
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.mcp_api_keys ALTER COLUMN key_prefix TYPE VARCHAR(16)',
            rec.table_schema
        );
    END LOOP;
END$$;
