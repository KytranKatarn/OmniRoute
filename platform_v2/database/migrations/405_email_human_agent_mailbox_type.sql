-- Migration 405: Add 'human_agent' to email_mailboxes mailbox_type constraint
-- Enables a Human Agents section in Email HQ sidebar for internal staff.

ALTER TABLE email_mailboxes
  DROP CONSTRAINT email_mailboxes_mailbox_type_check;

ALTER TABLE email_mailboxes
  ADD CONSTRAINT email_mailboxes_mailbox_type_check
    CHECK (mailbox_type IN ('ai_agent', 'business', 'owner', 'human_agent'));
