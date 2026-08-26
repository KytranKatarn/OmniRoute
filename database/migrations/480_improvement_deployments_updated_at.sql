-- 480: the trigger trigger_improvement_deployment_updated has ALWAYS assigned
-- NEW.updated_at, but the column never existed — so EVERY UPDATE on
-- improvement_deployments raised UndefinedColumn. This is a 4th mechanism behind
-- the 370 rows stuck status='deploying': completion paths could not update them.
-- Found by the Phase-2 merge-completion tests (spec 2026-08-26 §6.4).
ALTER TABLE improvement_deployments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
