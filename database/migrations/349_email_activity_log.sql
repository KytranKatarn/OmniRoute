-- Migration 349: email_activity_log
-- Every sent/received email across all mailboxes

CREATE TABLE IF NOT EXISTS email_activity_log (
    id SERIAL PRIMARY KEY,
    mailbox_address VARCHAR(200) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('sent', 'received')),
    from_address TEXT,
    to_address TEXT,
    subject TEXT,
    message_id VARCHAR(500),
    size_bytes INTEGER,
    read_at TIMESTAMP,
    logged_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_activity_mailbox
    ON email_activity_log(mailbox_address, logged_at DESC);

CREATE INDEX IF NOT EXISTS idx_email_activity_direction
    ON email_activity_log(direction, logged_at DESC);
