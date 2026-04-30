CREATE TABLE IF NOT EXISTS email_assignments (
    id              SERIAL PRIMARY KEY,
    email_id        INTEGER,
    mailbox_id      INTEGER REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    assigned_agent  VARCHAR(100),
    assigned_by     VARCHAR(100) DEFAULT 'system',
    status          VARCHAR(50)  NOT NULL DEFAULT 'open',
    notes           TEXT,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_email_assignments_status ON email_assignments (status);
CREATE INDEX IF NOT EXISTS idx_email_assignments_agent  ON email_assignments (assigned_agent);

CREATE TABLE IF NOT EXISTS email_rules (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    condition_field VARCHAR(50)  NOT NULL DEFAULT 'from_domain',
    condition_value TEXT         NOT NULL,
    action          VARCHAR(50)  NOT NULL DEFAULT 'assign_agent',
    action_value    TEXT,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO email_rules (name, condition_field, condition_value, action, action_value)
VALUES ('Route subscription inquiries to R.E.S.O.L.V.E.',
        'subject_contains', 'subscription', 'assign_agent', 'R.E.S.O.L.V.E.')
ON CONFLICT DO NOTHING;
