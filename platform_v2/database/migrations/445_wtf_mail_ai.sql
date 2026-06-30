-- 445: News-agent triage + draft-reply results for the WTF Hub Inbox.
-- Clone of 414_creed_mail_ai. One row per (mailbox, message uid, kind).
-- Async worker fills result; client polls. See tools/wtf_hub/mail_routes.py.
CREATE TABLE IF NOT EXISTS wtf_mail_ai (
    id SERIAL PRIMARY KEY,
    box TEXT NOT NULL,
    uid TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('triage', 'draft')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'error')),
    result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (box, uid, kind)
);

CREATE INDEX IF NOT EXISTS idx_wtf_mail_ai_box_uid ON wtf_mail_ai (box, uid);
