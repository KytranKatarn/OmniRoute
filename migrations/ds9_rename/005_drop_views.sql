-- DS9 Criterion 4 — Phase 5a: Drop views that reference contractor columns
DROP VIEW IF EXISTS v_contractor_approval_queue;
DROP VIEW IF EXISTS v_contractor_spending;
DROP VIEW IF EXISTS v_escalation_analysis;
DROP VIEW IF EXISTS v_internal_agents;
DROP VIEW IF EXISTS v_module_usage_stats;
