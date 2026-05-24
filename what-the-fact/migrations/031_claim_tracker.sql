-- 031_claim_tracker.sql
-- MP election claim tracker

CREATE TABLE IF NOT EXISTS wtf.claim_tracker (
    id               SERIAL PRIMARY KEY,
    mp_id            INTEGER NOT NULL REFERENCES parliament.mps(id),
    politician_slug  TEXT NOT NULL,
    politician_name  TEXT NOT NULL,
    claim_text       TEXT NOT NULL,
    claim_date       DATE,
    source_url       TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','verified_true','partially_true','misleading','false','contested')),
    verdict_summary  TEXT,          -- gated: Deep Dive subscribers only
    article_ids      INTEGER[],     -- articles referencing this claim
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_claim_tracker_mp ON wtf.claim_tracker (mp_id);
CREATE INDEX IF NOT EXISTS ix_claim_tracker_slug ON wtf.claim_tracker (politician_slug);
CREATE INDEX IF NOT EXISTS ix_claim_tracker_status ON wtf.claim_tracker (status);
