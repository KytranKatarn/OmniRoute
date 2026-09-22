-- DS9 Phase 2 (quota awareness): omniroute_quota_snapshots table. Idempotent.
-- One row per upstream provider per scan (every 15 min, see
-- platform_v2/services/omniroute_quota_service.py), so the DHQ dashboard card
-- and Telegram alert logic have a real trend, not just a point-in-time read.
--
-- Lives in scripts/omniroute/ (beside seed_contractor_row.sql) — the lane's
-- in-scope home for OmniRoute DB objects. Applied manually, exactly like the
-- contractor seed. If the platform ever grows an auto-migration runner, this
-- belongs in database/migrations/ as 486_omniroute_quota_snapshots.sql.
CREATE TABLE IF NOT EXISTS omniroute_quota_snapshots (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(100) NOT NULL,
    window_hours INTEGER NOT NULL,
    total_calls INTEGER NOT NULL,
    throttled_calls INTEGER NOT NULL,
    rate NUMERIC(6,4),
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_omniroute_quota_provider_created
    ON omniroute_quota_snapshots(provider, created_at DESC);