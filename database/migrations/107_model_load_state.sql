-- Migration 107: model_load_state table for restart recovery
-- Tracks which models were loaded on which host so they can be restored after restart
-- Referenced by department_dispatcher._save_model_state() / _restore_model_state()
-- and fleet_service.py for loaded model counts

BEGIN;

CREATE TABLE IF NOT EXISTS model_load_state (
    id SERIAL PRIMARY KEY,
    host_type VARCHAR(20) NOT NULL,
    node_db_id INTEGER,
    model_name VARCHAR(200) NOT NULL,
    tier VARCHAR(10) NOT NULL,
    size_gb NUMERIC(6,1),
    saved_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(host_type, node_db_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_model_load_state_host
    ON model_load_state(host_type, node_db_id);

COMMIT;
