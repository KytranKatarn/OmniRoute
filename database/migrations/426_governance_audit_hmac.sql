-- Migration 426: Add HMAC signature column to governance_audit_log
-- Provides tamper-evident audit trail for ISO/IEC 42001 A.7 compliance
-- hmac_sig is NULL for rows written before this migration (counted as "unverified", not "invalid")

ALTER TABLE governance_audit_log
    ADD COLUMN IF NOT EXISTS hmac_sig TEXT;

COMMENT ON COLUMN governance_audit_log.hmac_sig IS
    'HMAC-SHA256 hex digest over canonical pipe-joined event fields. NULL = unverified (pre-migration or missing key).';
