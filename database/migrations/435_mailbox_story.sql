-- 435_mailbox_story.sql — Mailbox Story Extractor (Applications & Concepts).
-- Phase 1: upload a .pst -> readpst extract -> structured emails. Local-only, admin-gated.
-- Privacy: files live on local disk (stored_path), never cloud; enrichment (Phase 2) runs
-- on local fleet LLMs only. See .claude/plans/2026-06-16-mailbox-story-extractor-design.md.

CREATE TABLE IF NOT EXISTS mailbox_imports (
    id              SERIAL PRIMARY KEY,
    owner_id        INTEGER,
    filename        TEXT NOT NULL,
    stored_path     TEXT NOT NULL,                    -- local disk path of the .pst
    status          TEXT NOT NULL DEFAULT 'uploaded', -- uploaded/extracting/extracted/enriching/done/error
    email_count     INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    purge_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mailbox_emails (
    id              SERIAL PRIMARY KEY,
    import_id       INTEGER NOT NULL REFERENCES mailbox_imports(id) ON DELETE CASCADE,
    folder          TEXT,
    message_id      TEXT,
    in_reply_to     TEXT,
    from_addr       TEXT,
    to_addrs        TEXT,
    cc_addrs        TEXT,
    sent_at         TIMESTAMPTZ,
    subject         TEXT,
    body_text       TEXT,
    has_attachments BOOLEAN NOT NULL DEFAULT false,
    enrich_status   TEXT NOT NULL DEFAULT 'pending',  -- pending/done/error (Phase 2)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mailbox_emails_import ON mailbox_emails(import_id);
CREATE INDEX IF NOT EXISTS idx_mailbox_emails_sent   ON mailbox_emails(import_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_mailbox_emails_enrich ON mailbox_emails(import_id, enrich_status);

-- Per-import read access grants (owner can share ONE mailbox with a collaborator).
CREATE TABLE IF NOT EXISTS mailbox_import_grants (
    import_id       INTEGER NOT NULL REFERENCES mailbox_imports(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (import_id, user_id)
);
