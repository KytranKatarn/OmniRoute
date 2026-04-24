-- Migration: Add triage policy to auto-escalate pr_reviewed director_reports
-- Inserts idempotently — safe to run multiple times.

INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
SELECT 'info', 'pr_reviewed', 'escalate',
       'F.O.R.G.E. PR review completed — notify Kytran via Telegram',
       10, TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM triage_policies WHERE category_prefix = 'pr_reviewed'
);
