-- Migration 402: GDPR / PIPEDA right-to-erasure request framework (T3256)
-- C.R.E.E.D. privacy pillar — tracks data deletion requests and logs
-- erasure events to governance_audit_log (event_category='privacy').

CREATE TABLE IF NOT EXISTS creed_erasure_requests (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    user_email      VARCHAR(255) NOT NULL,  -- captured at request time (user may be deleted)
    requested_by    VARCHAR(100) NOT NULL DEFAULT 'self',  -- 'self' | admin username
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'processing', 'completed', 'rejected', 'cancelled')),
    legal_basis     VARCHAR(100) DEFAULT 'gdpr_art17',  -- or 'pipeda_s11'
    rejection_reason TEXT,                 -- set when status='rejected'
    tables_affected  JSONB,               -- populated after erasure: {"deleted": [...], "anonymized": [...]}
    rows_affected    JSONB,               -- {"users": 1, "sessions": 4, ...}
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    processed_at    TIMESTAMPTZ,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_er_user_id   ON creed_erasure_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_er_status    ON creed_erasure_requests(status);
CREATE INDEX IF NOT EXISTS idx_er_requested ON creed_erasure_requests(requested_at DESC);

COMMENT ON TABLE creed_erasure_requests IS
    'C.R.E.E.D. T3256 — GDPR Art. 17 / PIPEDA s.11 erasure request lifecycle. '
    'Admin-reviewed before processing. Erasure events logged to governance_audit_log (privacy pillar).';
COMMENT ON COLUMN creed_erasure_requests.tables_affected IS
    'JSON: {"deleted": ["sessions","conversations",...], "anonymized": ["users","billing_customers"]}';
COMMENT ON COLUMN creed_erasure_requests.rows_affected IS
    'JSON: count of rows deleted/anonymized per table, populated after processing';
