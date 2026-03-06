-- Migration 128: Station Actions Registry
-- Allows modules to register actionable commands that Bridge can trigger.
-- Part of Project #109: Bridge Station Action Panels.

CREATE TABLE IF NOT EXISTS station_actions (
    id SERIAL PRIMARY KEY,
    action_key VARCHAR(80) UNIQUE NOT NULL,
    station_code VARCHAR(20) NOT NULL,
    module_source VARCHAR(100) NOT NULL,
    label VARCHAR(50) NOT NULL,
    description TEXT,
    icon VARCHAR(20) DEFAULT 'play',
    color_class VARCHAR(20) DEFAULT 'purple',
    sort_order INTEGER DEFAULT 100,
    http_method VARCHAR(10) DEFAULT 'POST',
    endpoint_path TEXT NOT NULL,
    params_schema JSONB DEFAULT '[]'::jsonb,
    creates_job BOOLEAN DEFAULT TRUE,
    job_type VARCHAR(50),
    requires_admin BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_station_actions_station
    ON station_actions(station_code) WHERE is_active = TRUE;

-- Seed: Dev Pipeline actions (ENGINEERING station)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type)
VALUES
    ('dev_pipeline.scan.batch', 'ENGINEERING', 'dev_pipeline', 'BATCH SCAN', 'Run code scan across all tracked files', 'search', 'green', 10, 'POST', '/tools/dev-pipeline/api/scan/batch', '[]'::jsonb, TRUE, 'code_scan'),
    ('dev_pipeline.scan.run', 'ENGINEERING', 'dev_pipeline', 'SCAN FILE', 'Scan a specific file for issues', 'file', 'green', 20, 'POST', '/tools/dev-pipeline/api/scan/run', '[{"key":"file_path","label":"File Path","type":"text","required":true}]'::jsonb, TRUE, 'code_scan'),
    ('dev_pipeline.sandbox.run', 'ENGINEERING', 'dev_pipeline', 'RUN TESTS', 'Execute sandbox test suite', 'terminal', 'green', 30, 'POST', '/tools/dev-pipeline/api/sandbox/run', '[]'::jsonb, TRUE, 'sandbox_test')
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code,
    module_source = EXCLUDED.module_source,
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class,
    sort_order = EXCLUDED.sort_order,
    http_method = EXCLUDED.http_method,
    endpoint_path = EXCLUDED.endpoint_path,
    params_schema = EXCLUDED.params_schema,
    creates_job = EXCLUDED.creates_job,
    job_type = EXCLUDED.job_type,
    updated_at = NOW();

-- Seed: Consciousness actions (ANALYTICS station)
INSERT INTO station_actions (action_key, station_code, module_source, label, description, icon, color_class, sort_order, http_method, endpoint_path, params_schema, creates_job, job_type)
VALUES
    ('consciousness.analysis.start', 'ANALYTICS', 'consciousness', 'ANALYZE', 'Start batch knowledge analysis', 'brain', 'cyan', 10, 'POST', '/tools/consciousness/api/processing/start', '[]'::jsonb, TRUE, 'knowledge_analysis'),
    ('consciousness.embeddings.generate', 'ANALYTICS', 'consciousness', 'EMBED', 'Generate embeddings for unembedded entries', 'vector', 'cyan', 20, 'POST', '/tools/consciousness/api/processing/generate-embeddings', '[]'::jsonb, TRUE, 'embedding_generation'),
    ('consciousness.github.reindex', 'ANALYTICS', 'consciousness', 'REINDEX', 'Reindex all GitHub repositories', 'git', 'cyan', 30, 'POST', '/tools/consciousness/github/reindex-all', '[]'::jsonb, TRUE, 'github_reindex'),
    ('consciousness.translate.generate', 'ANALYTICS', 'consciousness', 'TRANSLATE', 'Generate missing translations', 'globe', 'cyan', 40, 'POST', '/tools/consciousness/api/translations/generate-async', '[]'::jsonb, TRUE, 'translation')
ON CONFLICT (action_key) DO UPDATE SET
    station_code = EXCLUDED.station_code,
    module_source = EXCLUDED.module_source,
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    icon = EXCLUDED.icon,
    color_class = EXCLUDED.color_class,
    sort_order = EXCLUDED.sort_order,
    http_method = EXCLUDED.http_method,
    endpoint_path = EXCLUDED.endpoint_path,
    params_schema = EXCLUDED.params_schema,
    creates_job = EXCLUDED.creates_job,
    job_type = EXCLUDED.job_type,
    updated_at = NOW();
