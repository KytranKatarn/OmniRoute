-- Migration: Triage policy — escalate github_audit director_reports
INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
SELECT 'info', 'github_audit', 'escalate',
       'Weekly F.O.R.G.E. GitHub presence audit — notify Kytran', 5, TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM triage_policies WHERE category_prefix = 'github_audit'
);
