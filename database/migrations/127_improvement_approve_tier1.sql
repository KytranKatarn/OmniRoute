-- Add improvement_approve to Tier 1 auto-approve types
-- This allows low-risk auto-generated improvement proposals to be approved automatically
UPDATE autonomy_config
SET config_value = jsonb_set(
    config_value,
    '{types}',
    (config_value->'types') || '["improvement_approve"]'::jsonb
),
    updated_at = NOW()
WHERE config_key = 'tier1_auto_approve'
  AND NOT (config_value->'types' @> '"improvement_approve"'::jsonb);
