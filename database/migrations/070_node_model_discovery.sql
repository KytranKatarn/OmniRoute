-- Migration 070: Node Model Discovery (Phase 70)
-- Enable nodes to share their Ollama models with the central Bridge
-- Date: 2026-01-22

-- ============================================================================
-- 1. Add bridge_enabled column to remote_nodes
-- ============================================================================

ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS bridge_enabled BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS bridge_priority INTEGER DEFAULT 50;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS last_model_sync TIMESTAMP;

COMMENT ON COLUMN remote_nodes.bridge_enabled IS 'When true, Bridge can route LLM requests to this node';
COMMENT ON COLUMN remote_nodes.bridge_priority IS 'Priority for load balancing (1-100, higher = preferred)';
COMMENT ON COLUMN remote_nodes.last_model_sync IS 'Last time models were synced from this node';

-- ============================================================================
-- 2. Create node_ollama_models table
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_ollama_models (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    model_family VARCHAR(50),           -- e.g., 'llama', 'deepseek', 'qwen', 'mistral'
    parameter_size VARCHAR(20),         -- e.g., '7b', '13b', '70b'
    quantization VARCHAR(20),           -- e.g., 'q4_0', 'q8_0', 'f16'
    model_size_gb DECIMAL(6,2),
    context_length INTEGER,
    capabilities TEXT[],                -- ['chat', 'code', 'vision', 'embedding', 'function_calling']
    is_available BOOLEAN DEFAULT true,
    last_used TIMESTAMP,
    total_requests INTEGER DEFAULT 0,
    avg_response_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_node_ollama_models_node
        FOREIGN KEY (node_id) REFERENCES remote_nodes(node_id) ON DELETE CASCADE,
    CONSTRAINT uq_node_model UNIQUE(node_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_node_ollama_models_node ON node_ollama_models(node_id);
CREATE INDEX IF NOT EXISTS idx_node_ollama_models_name ON node_ollama_models(model_name);
CREATE INDEX IF NOT EXISTS idx_node_ollama_models_available ON node_ollama_models(is_available);
CREATE INDEX IF NOT EXISTS idx_node_ollama_models_family ON node_ollama_models(model_family);

COMMENT ON TABLE node_ollama_models IS 'Ollama models available on each node for Bridge routing';

-- ============================================================================
-- 3. Create view for available models across all bridge-enabled nodes
-- ============================================================================

CREATE OR REPLACE VIEW v_bridge_available_models AS
SELECT
    m.model_name,
    m.model_family,
    m.parameter_size,
    COUNT(DISTINCT n.node_id) as node_count,
    ARRAY_AGG(DISTINCT n.node_name ORDER BY n.node_name) as available_on_nodes,
    ARRAY_AGG(DISTINCT n.node_id ORDER BY n.node_id) as node_ids,
    MIN(n.current_load) as min_load,
    MAX(n.current_load) as max_load,
    AVG(n.bridge_priority)::INTEGER as avg_priority,
    SUM(m.total_requests) as total_requests,
    AVG(m.avg_response_ms)::INTEGER as avg_response_ms,
    BOOL_OR(n.gpu_available) as gpu_available,
    MAX(m.context_length) as max_context_length,
    m.capabilities[1] as primary_capability
FROM node_ollama_models m
JOIN remote_nodes n ON m.node_id = n.node_id
WHERE n.bridge_enabled = true
  AND n.status = 'online'
  AND n.approval_status = 'approved'
  AND n.ollama_available = true
  AND m.is_available = true
GROUP BY m.model_name, m.model_family, m.parameter_size, m.capabilities
ORDER BY node_count DESC, m.model_name;

COMMENT ON VIEW v_bridge_available_models IS 'Aggregate view of all models available for Bridge routing';

-- ============================================================================
-- 4. Create view for node model summary
-- ============================================================================

CREATE OR REPLACE VIEW v_node_model_summary AS
SELECT
    n.node_id,
    n.node_name,
    n.vpn_ip,
    n.status,
    n.bridge_enabled,
    n.bridge_priority,
    n.current_load,
    n.gpu_model,
    n.gpu_vram_gb,
    n.last_model_sync,
    COUNT(m.id) as model_count,
    ARRAY_AGG(m.model_name ORDER BY m.model_name) FILTER (WHERE m.is_available) as available_models,
    SUM(m.total_requests) as total_model_requests
FROM remote_nodes n
LEFT JOIN node_ollama_models m ON n.node_id = m.node_id
WHERE n.ollama_available = true
  AND n.approval_status = 'approved'
GROUP BY n.node_id, n.node_name, n.vpn_ip, n.status, n.bridge_enabled,
         n.bridge_priority, n.current_load, n.gpu_model, n.gpu_vram_gb, n.last_model_sync
ORDER BY n.bridge_enabled DESC, n.bridge_priority DESC, n.node_name;

COMMENT ON VIEW v_node_model_summary IS 'Summary of each node and its available models';

-- ============================================================================
-- 5. Function to select best node for a model request
-- ============================================================================

CREATE OR REPLACE FUNCTION select_node_for_model(
    p_model_name VARCHAR(100),
    p_prefer_gpu BOOLEAN DEFAULT true
)
RETURNS TABLE (
    node_id VARCHAR(64),
    vpn_ip VARCHAR(45),
    port INTEGER,
    node_name VARCHAR(100),
    current_load INTEGER,
    bridge_priority INTEGER,
    gpu_available BOOLEAN,
    selection_score DECIMAL(10,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        n.node_id,
        n.vpn_ip,
        n.port,
        n.node_name,
        n.current_load,
        n.bridge_priority,
        n.gpu_available,
        -- Selection score: higher is better
        (
            (100 - COALESCE(n.current_load, 0)) * 0.4 +  -- Lower load = better (40%)
            COALESCE(n.bridge_priority, 50) * 0.3 +       -- Higher priority = better (30%)
            CASE WHEN n.gpu_available AND p_prefer_gpu THEN 30 ELSE 0 END  -- GPU bonus (30%)
        )::DECIMAL(10,2) as selection_score
    FROM remote_nodes n
    JOIN node_ollama_models m ON n.node_id = m.node_id
    WHERE n.bridge_enabled = true
      AND n.status = 'online'
      AND n.approval_status = 'approved'
      AND n.ollama_available = true
      AND m.model_name = p_model_name
      AND m.is_available = true
    ORDER BY selection_score DESC
    LIMIT 5;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION select_node_for_model IS 'Select best available nodes for a specific model request';

-- ============================================================================
-- 6. Function to sync models from a node
-- ============================================================================

CREATE OR REPLACE FUNCTION sync_node_models(
    p_node_id VARCHAR(64),
    p_models JSONB
)
RETURNS INTEGER AS $$
DECLARE
    v_model JSONB;
    v_count INTEGER := 0;
    v_model_name VARCHAR(100);
    v_model_size DECIMAL(6,2);
    v_param_size VARCHAR(20);
    v_family VARCHAR(50);
BEGIN
    -- Mark all existing models as unavailable first
    UPDATE node_ollama_models
    SET is_available = false, updated_at = NOW()
    WHERE node_id = p_node_id;

    -- Process each model from the JSONB array
    FOR v_model IN SELECT * FROM jsonb_array_elements(p_models)
    LOOP
        v_model_name := v_model->>'name';
        v_model_size := (v_model->>'size')::BIGINT / 1073741824.0;  -- Convert bytes to GB

        -- Extract parameter size from model name (e.g., '7b', '13b', '70b')
        v_param_size := (regexp_match(v_model_name, '(\d+\.?\d*[bB])'))[1];

        -- Extract family from model name
        v_family := split_part(v_model_name, ':', 1);
        v_family := split_part(v_family, '-', 1);

        -- Upsert the model
        INSERT INTO node_ollama_models (
            node_id, model_name, model_family, parameter_size, model_size_gb, is_available
        ) VALUES (
            p_node_id, v_model_name, v_family, v_param_size, v_model_size, true
        )
        ON CONFLICT (node_id, model_name) DO UPDATE SET
            model_size_gb = EXCLUDED.model_size_gb,
            is_available = true,
            updated_at = NOW();

        v_count := v_count + 1;
    END LOOP;

    -- Update the node's last_model_sync timestamp
    UPDATE remote_nodes
    SET last_model_sync = NOW(), updated_at = NOW()
    WHERE node_id = p_node_id;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION sync_node_models IS 'Sync Ollama models from a node heartbeat';

-- ============================================================================
-- 7. Function to log model request routing
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_model_requests (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(64) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    request_type VARCHAR(20) DEFAULT 'generate',  -- 'generate', 'chat', 'embed'
    tokens_in INTEGER,
    tokens_out INTEGER,
    response_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT fk_node_model_requests_node
        FOREIGN KEY (node_id) REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_node_model_requests_node ON node_model_requests(node_id);
CREATE INDEX IF NOT EXISTS idx_node_model_requests_model ON node_model_requests(model_name);
CREATE INDEX IF NOT EXISTS idx_node_model_requests_created ON node_model_requests(created_at);

COMMENT ON TABLE node_model_requests IS 'Log of all model requests routed through Bridge';

-- ============================================================================
-- 8. Update existing nodes - enable bridge for nodes with Ollama
-- ============================================================================

-- Enable bridge for existing approved nodes with Ollama
UPDATE remote_nodes
SET bridge_enabled = true, bridge_priority = 50
WHERE ollama_available = true
  AND approval_status = 'approved'
  AND bridge_enabled IS NULL OR bridge_enabled = false;

-- ============================================================================
-- 9. Grant permissions
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON node_ollama_models TO archie;
GRANT SELECT, INSERT ON node_model_requests TO archie;
GRANT USAGE, SELECT ON SEQUENCE node_ollama_models_id_seq TO archie;
GRANT USAGE, SELECT ON SEQUENCE node_model_requests_id_seq TO archie;
GRANT SELECT ON v_bridge_available_models TO archie;
GRANT SELECT ON v_node_model_summary TO archie;

-- ============================================================================
-- Done
-- ============================================================================

SELECT 'Migration 070: Node Model Discovery complete' as status;
