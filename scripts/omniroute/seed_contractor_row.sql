-- #6653 Phase 3a: OmniRoute as ONE contractor_providers row. Idempotent (upsert).
-- Run with the concrete default model chosen from GET /v1/models (NEVER an auto/* id):
--   docker exec -i archie_database psql -U archie -d archie \
--     -v default_model='<concrete id>' -f - < scripts/omniroute/seed_contractor_row.sql
--
-- is_cloud_proxy MUST be false: in this codebase true means "route via call_ollama_cloud"
-- (external_providers.call_external / dispatcher._execute_llm), which would bypass the
-- gateway. tier_position 9 => the A/B lane's free_tier bucket (>= 8 AND NOT is_cloud_proxy).
-- models[] feeds external_providers._model_provider_map (model name -> provider_key);
-- OmniRoute ids are provider/model-namespaced, so they cannot collide with other rows'
-- bare ids. auto/coding variants are SELECTABLE (attribution reads back the served model);
-- the DEFAULT stays concrete per the owner rule.
INSERT INTO contractor_providers
  (provider_key, display_name, base_url, default_model, auth_method, auth_env_var,
   is_cloud_proxy, tier_position, models, rate_limits, is_active, capabilities,
   creed_compliance_tier)
VALUES
  ('omniroute', 'OmniRoute (self-hosted gateway)', 'http://omniroute:20128/v1',
   :'default_model', 'api_key', 'OMNIROUTE_API_KEY',
   false, 9,
   jsonb_build_array(
     jsonb_build_object('name', :'default_model'),
     jsonb_build_object('name', 'auto/coding'),
     jsonb_build_object('name', 'auto/coding:free')),
   '{}'::jsonb, true, '["text_chat"]'::jsonb, 2)
ON CONFLICT (provider_key) DO UPDATE SET
  display_name          = EXCLUDED.display_name,
  base_url              = EXCLUDED.base_url,
  default_model         = EXCLUDED.default_model,
  auth_method           = EXCLUDED.auth_method,
  auth_env_var          = EXCLUDED.auth_env_var,
  is_cloud_proxy        = false,
  tier_position         = EXCLUDED.tier_position,
  models                = EXCLUDED.models,
  is_active             = true,
  capabilities          = EXCLUDED.capabilities,
  creed_compliance_tier = EXCLUDED.creed_compliance_tier,
  updated_at            = NOW();
