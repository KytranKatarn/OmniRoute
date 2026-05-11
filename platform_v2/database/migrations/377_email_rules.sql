-- Migration 377: align email_rules table for Email HQ Phase 6
-- Existing table has: name, condition_field, condition_value, action, action_value, is_active, created_at
-- Adding: mailbox_id, condition_op; renaming action→action_type

BEGIN;

-- Add mailbox_id if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_rules' AND column_name = 'mailbox_id'
    ) THEN
        ALTER TABLE email_rules ADD COLUMN mailbox_id INTEGER REFERENCES email_mailboxes(id) ON DELETE CASCADE;
    END IF;
END $$;

-- Add condition_op if missing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_rules' AND column_name = 'condition_op'
    ) THEN
        ALTER TABLE email_rules ADD COLUMN condition_op TEXT NOT NULL DEFAULT 'contains';
    END IF;
END $$;

-- Rename action → action_type if needed
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_rules' AND column_name = 'action'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_rules' AND column_name = 'action_type'
    ) THEN
        ALTER TABLE email_rules RENAME COLUMN action TO action_type;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_email_rules_mailbox ON email_rules(mailbox_id)
    WHERE is_active = TRUE;

COMMIT;
