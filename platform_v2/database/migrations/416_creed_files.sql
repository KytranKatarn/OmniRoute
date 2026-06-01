-- 416: E.T.H.O.S. document library for the C.R.E.E.D. Command Files tab (#3614)
-- File bytes stored in-DB (bytea) — self-contained, persists, backs up with the DB.
-- Optional link to a grant (creed_grants) and/or a mail thread (mail_ref = 'box:uid').
CREATE TABLE IF NOT EXISTS creed_files (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    tag TEXT,
    grant_id INTEGER REFERENCES creed_grants(id) ON DELETE SET NULL,
    mail_ref TEXT,
    data BYTEA NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_creed_files_uploaded ON creed_files (uploaded_at DESC);
