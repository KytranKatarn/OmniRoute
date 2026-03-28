-- Migration 201: Department Hard Cutover
-- Adds floor column to agents, enforces department/floor constraints,
-- drops station_assignments, adds department to autonomy_loop_log,
-- deprecates bridge_stations.
-- Idempotent: safe to run multiple times.

BEGIN;

-- 1. Add floor column to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS floor VARCHAR(20);

-- 2. Backfill floor from department
UPDATE agents SET floor = CASE
    WHEN department = 'Executive Office' THEN 'BRIDGE'
    WHEN department IN ('Operations & Infrastructure', 'Logistics & Supply Chain', 'Finance & Accounting') THEN 'OPERATIONS'
    WHEN department IN ('Engineering & Technology', 'Security & Compliance', 'Research & Development') THEN 'ENGINEERING'
    WHEN department IN ('Creative & Design', 'Marketing & Communications', 'Documentation & Knowledge') THEN 'CREATIVE'
    WHEN department IN ('Customer Success & Support', 'Human Resources & Culture', 'Medical & Wellness', 'Legal & Regulatory', 'Diplomatic & External Relations', 'Analytics & Intelligence') THEN 'SERVICES'
    ELSE 'SERVICES'
END
WHERE floor IS NULL;

-- 3. Add NOT NULL constraints (safe after backfill)
ALTER TABLE agents ALTER COLUMN department SET NOT NULL;
ALTER TABLE agents ALTER COLUMN floor SET NOT NULL;

-- 4. Add CHECK constraints (drop first for idempotency)
ALTER TABLE agents DROP CONSTRAINT IF EXISTS chk_agents_department;
ALTER TABLE agents ADD CONSTRAINT chk_agents_department CHECK (
    department IN (
        'Executive Office', 'Operations & Infrastructure', 'Logistics & Supply Chain',
        'Finance & Accounting', 'Engineering & Technology', 'Security & Compliance',
        'Research & Development', 'Creative & Design', 'Marketing & Communications',
        'Documentation & Knowledge', 'Customer Success & Support', 'Human Resources & Culture',
        'Medical & Wellness', 'Legal & Regulatory', 'Diplomatic & External Relations',
        'Analytics & Intelligence'
    )
);

ALTER TABLE agents DROP CONSTRAINT IF EXISTS chk_agents_floor;
ALTER TABLE agents ADD CONSTRAINT chk_agents_floor CHECK (
    floor IN ('BRIDGE', 'OPERATIONS', 'ENGINEERING', 'CREATIVE', 'SERVICES')
);

-- 5. Drop station_assignments table
DROP TABLE IF EXISTS station_assignments CASCADE;

-- 6. Add department column to autonomy_loop_log
ALTER TABLE autonomy_loop_log ADD COLUMN IF NOT EXISTS department VARCHAR(100);

-- 7. Mark bridge_stations as deprecated (keep for historical reference)
COMMENT ON TABLE bridge_stations IS 'DEPRECATED: replaced by agents.department + agents.floor. Kept for historical reference.';

COMMIT;
