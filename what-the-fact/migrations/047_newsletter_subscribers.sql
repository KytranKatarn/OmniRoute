-- 047_newsletter_subscribers.sql — public weekly-digest signup (#4899, ADR-011)
-- CASL: express consent captured at the form (consent_at), unsubscribe token
-- in every digest email, sender identified (hello@kytranempowerment.com).

CREATE TABLE IF NOT EXISTS wtf.newsletter_subscribers (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    source          TEXT NOT NULL DEFAULT 'footer',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    unsub_token     UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    consent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unsubscribed_at TIMESTAMPTZ,
    kbs_synced_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_newsletter_active
    ON wtf.newsletter_subscribers (active) WHERE active;

-- Partial index drives the KBS CRM sync worker's "not yet pushed" scan.
CREATE INDEX IF NOT EXISTS idx_newsletter_kbs_unsynced
    ON wtf.newsletter_subscribers (id) WHERE kbs_synced_at IS NULL AND active;

-- The consumer + ingest connect as the limited wtfuser role (not the table
-- owner) — without these grants every INSERT 500s with InsufficientPrivilege.
GRANT SELECT, INSERT, UPDATE ON wtf.newsletter_subscribers TO wtfuser;
GRANT USAGE ON SEQUENCE wtf.newsletter_subscribers_id_seq TO wtfuser;
