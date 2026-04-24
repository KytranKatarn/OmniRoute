-- Migration: Triage policy — escalate repo_health director_reports
INSERT INTO triage_policies (severity, category_prefix, action, reason, priority, active)
SELECT 'warning', 'repo_health', 'escalate',
       'Repo missing README/description/topics/license — notify Kytran', 5, TRUE
WHERE NOT EXISTS (
    SELECT 1 FROM triage_policies WHERE category_prefix = 'repo_health'
);
