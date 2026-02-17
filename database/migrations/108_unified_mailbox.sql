-- Migration 108: Unified Mailbox — SMTP columns on email_imap_settings
-- Adds per-account SMTP send config alongside existing IMAP receive config.
-- Migrates data from legacy email_settings table by matching email domains.

-- 1. Add SMTP columns to email_imap_settings
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_host VARCHAR(255);
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_port INTEGER DEFAULT 587;
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_user VARCHAR(255);
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_password_encrypted TEXT;
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_encryption VARCHAR(20) DEFAULT 'tls';
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS from_email VARCHAR(255);
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS from_name VARCHAR(255);
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS reply_to VARCHAR(255);
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_test_result VARCHAR(50);
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_test_message TEXT;
ALTER TABLE email_imap_settings ADD COLUMN IF NOT EXISTS smtp_tested_at TIMESTAMP;

-- 2. Migrate data from email_settings → email_imap_settings
-- Match by domain: imap_user domain = smtp_user domain (primary) or from_email domain (fallback).
-- Only migrate active, tested-successfully SMTP configs.
-- Only update IMAP rows that don't already have SMTP configured.
-- Use DISTINCT ON to pick one SMTP config per IMAP account (prefer smtp_user domain match).
UPDATE email_imap_settings imap
SET
    smtp_host               = best.es_smtp_host,
    smtp_port               = best.es_smtp_port,
    smtp_user               = best.es_smtp_user,
    smtp_password_encrypted = best.es_smtp_password_encrypted,
    smtp_encryption         = best.es_encryption,
    from_email              = best.es_from_email,
    from_name               = best.es_from_name,
    reply_to                = best.es_reply_to,
    smtp_test_result        = best.es_test_result,
    smtp_test_message       = best.es_test_message,
    smtp_tested_at          = best.es_tested_at,
    updated_at              = NOW()
FROM (
    SELECT DISTINCT ON (imap_id)
        imap_id,
        es_smtp_host,
        es_smtp_port,
        es_smtp_user,
        es_smtp_password_encrypted,
        es_encryption,
        es_from_email,
        es_from_name,
        es_reply_to,
        es_test_result,
        es_test_message,
        es_tested_at,
        match_priority,
        es_id
    FROM (
        -- Priority 1: Match on smtp_user domain
        SELECT
            i.id                      AS imap_id,
            e.id                      AS es_id,
            e.smtp_host               AS es_smtp_host,
            e.smtp_port               AS es_smtp_port,
            e.smtp_user               AS es_smtp_user,
            e.smtp_password_encrypted AS es_smtp_password_encrypted,
            e.encryption              AS es_encryption,
            e.from_email              AS es_from_email,
            e.from_name               AS es_from_name,
            e.reply_to                AS es_reply_to,
            e.test_result             AS es_test_result,
            e.test_message            AS es_test_message,
            e.tested_at               AS es_tested_at,
            1                         AS match_priority
        FROM email_imap_settings i
        JOIN email_settings e
            ON LOWER(SPLIT_PART(i.imap_user, '@', 2)) = LOWER(SPLIT_PART(e.smtp_user, '@', 2))
        WHERE e.is_active = true
          AND e.test_result = 'success'
          AND i.smtp_host IS NULL

        UNION ALL

        -- Priority 2: Match on from_email domain
        SELECT
            i.id                      AS imap_id,
            e.id                      AS es_id,
            e.smtp_host               AS es_smtp_host,
            e.smtp_port               AS es_smtp_port,
            e.smtp_user               AS es_smtp_user,
            e.smtp_password_encrypted AS es_smtp_password_encrypted,
            e.encryption              AS es_encryption,
            e.from_email              AS es_from_email,
            e.from_name               AS es_from_name,
            e.reply_to                AS es_reply_to,
            e.test_result             AS es_test_result,
            e.test_message            AS es_test_message,
            e.tested_at               AS es_tested_at,
            2                         AS match_priority
        FROM email_imap_settings i
        JOIN email_settings e
            ON LOWER(SPLIT_PART(i.imap_user, '@', 2)) = LOWER(SPLIT_PART(e.from_email, '@', 2))
        WHERE e.is_active = true
          AND e.test_result = 'success'
          AND i.smtp_host IS NULL
    ) candidates
    ORDER BY imap_id, match_priority, es_id
) best
WHERE imap.id = best.imap_id
  AND imap.smtp_host IS NULL;
