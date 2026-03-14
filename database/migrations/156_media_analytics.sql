-- Migration 156: Media analytics snapshots + cost rates
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS media_analytics_snapshots (
    id SERIAL PRIMARY KEY,
    period_type VARCHAR(10) NOT NULL,
    period_start TIMESTAMP NOT NULL,
    period_end TIMESTAMP NOT NULL,
    scope_type VARCHAR(20) DEFAULT 'global',
    scope_id INTEGER DEFAULT 0,
    metrics JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(period_type, period_start, scope_type, scope_id)
);

CREATE TABLE IF NOT EXISTS media_cost_rates (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL UNIQUE,
    cost_per_generation NUMERIC(10,6) DEFAULT 0,
    vram_gb_per_sec NUMERIC(10,6) DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_snap_period ON media_analytics_snapshots(period_type, period_start);
CREATE INDEX IF NOT EXISTS idx_analytics_snap_scope ON media_analytics_snapshots(scope_type, scope_id);

INSERT INTO media_cost_rates (model_name, cost_per_generation, vram_gb_per_sec) VALUES
    ('sd_xl_base_1.0.safetensors', 0.002, 0.0003),
    ('RealESRGAN_x4plus.pth', 0.001, 0.0001),
    ('mm_sd_v15_v2.safetensors', 0.005, 0.0008),
    ('ip-adapter_sdxl.safetensors', 0.003, 0.0004),
    ('lanczos', 0.0, 0.0)
ON CONFLICT (model_name) DO NOTHING;
