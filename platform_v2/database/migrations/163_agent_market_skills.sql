-- Migration 163: Fix M.A.R.K.E.T. skills
-- Project #284 Phase 8 — M.A.R.K.E.T. was assigned data engineering skills
-- (Analytics Engineering:5, ETL Design:5, Metrics Definition:4, Query Optimization:4)
-- that belong to a data pipeline engineer, not a market execution agent.
-- NOTE: Applied directly to live DB 2026-04-27 — this migration is idempotent.

BEGIN;

DELETE FROM agent_skills
WHERE agent_id = (SELECT id FROM agents WHERE name = 'M.A.R.K.E.T.')
  AND skill_name NOT LIKE 'gh:%';

INSERT INTO agent_skills (agent_id, skill_name, proficiency_level, can_escalate_to)
SELECT id, 'market_execution',     5, NULL::integer FROM agents WHERE name = 'M.A.R.K.E.T.'
UNION ALL SELECT id, 'portfolio_management', 5, NULL::integer FROM agents WHERE name = 'M.A.R.K.E.T.'
UNION ALL SELECT id, 'risk_analysis',        4, NULL::integer FROM agents WHERE name = 'M.A.R.K.E.T.'
UNION ALL SELECT id, 'trade_timing',         4, NULL::integer FROM agents WHERE name = 'M.A.R.K.E.T.'
UNION ALL SELECT id, 'pnl_tracking',         4, NULL::integer FROM agents WHERE name = 'M.A.R.K.E.T.'
UNION ALL SELECT id, 'market_analysis',      3, NULL::integer FROM agents WHERE name = 'M.A.R.K.E.T.'
ON CONFLICT (agent_id, skill_name) DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level;

COMMIT;
