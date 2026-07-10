-- 455_welfare_staffing_settings.sql
-- K.I.N. pool-saturation staffing-gap detector thresholds.
--
-- Context: once per-agent token accounting is honest (the A.R.M.A.D.A. attribution fix +
-- backfill), a NEW signal becomes meaningful — a skill whose ENTIRE active agent pool is
-- pinned at its 24h token-budget ceiling. That is the "the whole department is at capacity,
-- add an agent" signal (distinct from the zero-agent capability gap, and from the sole-agent
-- staffing_gap in welfare_governance.recommend which only fires for single-agent skills).
-- K.I.N. turns it into a CREED-gated, human-approved hiring recommendation.
--
--   welfare:staffing:pool_gap_ratio — the least-loaded agent in the pool must be at/over this
--     fraction of its 24h token budget for the pool to count as saturated. 1.0 = fully at
--     budget: a deliberately higher bar than the 0.9 backlog-pause ratio, so a hire is only
--     recommended when the pool is truly maxed, not merely busy. (Read via
--     pool_over_budget_by_skill(skill, settings_key='welfare:staffing:pool_gap_ratio').)
--   welfare:staffing:min_backlog — minimum non-terminal dispatch_pending_queue depth for the
--     capability required alongside saturation, so a transient burst never triggers a hire.
--
-- Tunable at runtime (no deploy). Idempotent.
INSERT INTO platform_settings (key, value, value_type, description)
VALUES
  ('welfare:staffing:pool_gap_ratio', '1.0', 'float',
   'K.I.N. pool-saturation hire signal: least-loaded pool agent 24h token ratio must be >= this for the whole pool to count as at-capacity (1.0 = fully at budget).'),
  ('welfare:staffing:min_backlog', '3', 'integer',
   'K.I.N. pool-saturation hire signal: minimum non-terminal dispatch_pending_queue depth for a capability required alongside pool saturation (filters transient bursts).')
ON CONFLICT (key) DO NOTHING;
