-- database/migrations/451_coordinator_lane_settings.sql
-- Seed coordinator-lane settings so they are visible/tunable in the Autonomy tab.
-- get_coordinator_model() already defaults to qwen25-classify when absent; this makes it explicit.
INSERT INTO platform_settings (key, value)
VALUES
  ('dispatch:coordinator_model', 'qwen25-classify'),
  ('dispatch:coordinator_lane_enabled', 'true'),
  ('dispatch:coordinator_plan_max_steps', '6')
ON CONFLICT (key) DO NOTHING;
