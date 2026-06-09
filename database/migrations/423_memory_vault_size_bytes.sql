-- 423_memory_vault_size_bytes.sql
-- Email Memory Vault (Project #377) — capture per-message size so the progress chip
-- can show ingestion VOLUME (MB), not just message count. Gmail's messages.get returns
-- `sizeEstimate` (bytes); the triage worker writes it onto the ledger row.
-- Idempotent.

ALTER TABLE profile_ingest_ledger
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT;
