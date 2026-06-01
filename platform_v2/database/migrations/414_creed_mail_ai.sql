-- 414: E.T.H.O.S. triage + draft-reply results for the C.R.E.E.D. Command Inbox (#3620)
-- One row per (mailbox, message uid, kind). Async worker fills result; client polls.
CREATE TABLE IF NOT EXISTS creed_mail_ai (
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

CREATE INDEX IF NOT EXISTS idx_creed_mail_ai_box_uid ON creed_mail_ai (box, uid);
