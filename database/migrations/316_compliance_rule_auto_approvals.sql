-- Migration 316: compliance_rule_auto_approvals
-- Supports opt-in per-rule auto-apply and per-rule exemptions for
-- the Repair Bay compliance approval flow (spec 2026-04-11).

CREATE TABLE IF NOT EXISTS compliance_rule_auto_approvals (
    rule_id         VARCHAR(100) PRIMARY KEY,
    pack_id         VARCHAR(100) NOT NULL,
    status          VARCHAR(20)  NOT NULL
                    CHECK (status IN ('allow','exempt')),
    approved_by     INTEGER REFERENCES users(id),
    approved_at     TIMESTAMP DEFAULT now(),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_comp_auto_approvals_status
    ON compliance_rule_auto_approvals(status);
