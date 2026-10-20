-- DS9 Criterion 4 — Phase 5b: Rename contractor columns to engineer
ALTER TABLE IF EXISTS agents RENAME COLUMN contractor_budget_monthly TO engineer_budget_monthly;
ALTER TABLE IF EXISTS agents RENAME COLUMN contractor_usage_this_month TO engineer_usage_this_month;
ALTER TABLE IF EXISTS improvement_proposals RENAME COLUMN contractor_agent_id TO engineer_agent_id;
ALTER TABLE IF EXISTS improvement_proposals RENAME COLUMN contractor_proposal TO engineer_proposal;
ALTER TABLE IF EXISTS improvement_proposals RENAME COLUMN escalated_to_contractor TO escalated_to_engineer;
ALTER TABLE IF EXISTS archie_command_log RENAME COLUMN contractor_id TO engineer_id;
ALTER TABLE IF EXISTS archie_command_log RENAME COLUMN escalated_to_contractor TO escalated_to_engineer;
ALTER TABLE IF EXISTS archie_complexity_patterns RENAME COLUMN requires_contractor TO requires_engineer;
