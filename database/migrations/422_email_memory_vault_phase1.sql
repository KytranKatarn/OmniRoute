-- 422_email_memory_vault_phase1.sql
-- Email Memory Vault — Phase 1 (ingest + triage + cache) scaffolding.
-- Project #377. Design: .claude/plans/email-history-ingestion-design.md
--
-- Two owner-scoped tables that drive the resumable, idempotent backfill:
--   profile_account_cursor  — per-account high-water mark (full-enumeration page token
--                             now; Gmail historyId reserved for Phase-3 incremental).
--   profile_ingest_ledger   — one row per (account, gmail_id); the triage state machine
--                             and the idempotency guard so a restart never re-does work.
-- Idempotent: safe to re-run.

-- ---------------------------------------------------------------------------
-- profile_account_cursor
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profile_account_cursor (
    account_id           INTEGER PRIMARY KEY
                           REFERENCES google_accounts(id) ON DELETE CASCADE,
    last_page_token      TEXT,                 -- Gmail messages.list nextPageToken (resume enumeration)
    last_history_id      TEXT,                 -- Gmail historyId (Phase-3 incremental; unused in P1)
    enumeration_complete BOOLEAN NOT NULL DEFAULT FALSE,
    total_enumerated     INTEGER NOT NULL DEFAULT 0,
    last_run_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- profile_ingest_ledger
-- ---------------------------------------------------------------------------
-- state machine:
--   new                -> just enumerated, awaiting triage
--   triaged_important  -> keep; eligible for Phase-2 deep extraction
--   triaged_bulk       -> bulk/promo/social/SSO noise; never extracted
--   triaged_skip       -> deduped (same thread/content already covered)
--   extracted          -> Phase-2 extraction done
--   error              -> triage/extraction error (see error col)
CREATE TABLE IF NOT EXISTS profile_ingest_ledger (
    id            BIGSERIAL PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    gmail_id      TEXT    NOT NULL,
    thread_id     TEXT,
    state         TEXT    NOT NULL DEFAULT 'new',
    triage_reason TEXT,                          -- which gate decided + why
    is_sent       BOOLEAN NOT NULL DEFAULT FALSE, -- SENT/Drafts = gold voice source (P2 priority)
    content_hash  TEXT,                          -- thread/content dedup (nullable in P1)
    account_context TEXT,                         -- 'personal' | 'business' (per owner decision)
    claimed_at    TIMESTAMPTZ,                   -- worker claim marker
    triaged_at    TIMESTAMPTZ,
    extracted_at  TIMESTAMPTZ,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_account_gmail UNIQUE (account_id, gmail_id)
);

-- Fast claim of unworked rows (partial index keeps it tiny as the backlog drains).
CREATE INDEX IF NOT EXISTS idx_ledger_state_new
    ON profile_ingest_ledger (account_id, id)
    WHERE state = 'new';

-- Phase-2 will claim important-but-not-yet-extracted rows; index ready now.
CREATE INDEX IF NOT EXISTS idx_ledger_state_important
    ON profile_ingest_ledger (account_id, is_sent DESC, id)
    WHERE state = 'triaged_important';

CREATE INDEX IF NOT EXISTS idx_ledger_thread
    ON profile_ingest_ledger (account_id, thread_id);
