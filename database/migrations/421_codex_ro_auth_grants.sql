-- 421_codex_ro_auth_grants.sql
-- The MCP gateway authenticates each request with MCPAuthenticator.validate_api_key(),
-- which SELECTs mcp_api_keys (key hashes — NOT plaintext) and bumps last_used_at.
-- Grant codex_ro exactly that: read the keys table + update only the last_used_at column.
-- This keeps the role's data surface to "read-only KB + auth bookkeeping" — still no
-- ability to write knowledge content or touch any other table. Idempotent.

GRANT SELECT ON mcp_api_keys TO codex_ro;
GRANT UPDATE (last_used_at) ON mcp_api_keys TO codex_ro;
