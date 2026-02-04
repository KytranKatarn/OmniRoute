-- Migration 076: Mesh Hub Tables
-- Date: 2026-02-03
-- Phase: Hub Preparation for Mesh Cluster Architecture
-- Description: Adds hub-level tables for code versioning, learning patterns, agent loans, and subscriptions

-- ============================================================================
-- 1. MESH CODE VERSIONS (track what version each node runs)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_code_versions (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) NOT NULL,
    version VARCHAR(50) NOT NULL,
    git_commit VARCHAR(40),
    migration_version INTEGER,
    modules_list JSONB DEFAULT '[]',
    reported_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_code_version_node FOREIGN KEY (node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE,
    CONSTRAINT uq_code_version_node UNIQUE (node_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_code_versions_node ON mesh_code_versions(node_id);

-- ============================================================================
-- 2. MESH LEARNING PATTERNS (anonymized insights from all nodes)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_learning_patterns (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) NOT NULL,
    pattern_type VARCHAR(50) NOT NULL,
    category VARCHAR(100),
    insight TEXT NOT NULL,
    metric_name VARCHAR(100),
    metric_value FLOAT,
    metric_unit VARCHAR(50),
    context JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_learning_node FOREIGN KEY (node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mesh_learning_node ON mesh_learning_patterns(node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_learning_type ON mesh_learning_patterns(pattern_type);
CREATE INDEX IF NOT EXISTS idx_mesh_learning_created ON mesh_learning_patterns(created_at);

-- ============================================================================
-- 3. MESH AGENT LOANS (track agent lending between nodes)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_agent_loans (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL,
    source_node_id VARCHAR(50) NOT NULL,
    target_node_id VARCHAR(50) NOT NULL,
    task_description TEXT,
    status VARCHAR(20) DEFAULT 'active',
    lent_at TIMESTAMP DEFAULT NOW(),
    returned_at TIMESTAMP,
    work_summary TEXT,
    initiated_by VARCHAR(50) DEFAULT 'archie',
    CONSTRAINT fk_loan_source FOREIGN KEY (source_node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE,
    CONSTRAINT fk_loan_target FOREIGN KEY (target_node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mesh_loans_source ON mesh_agent_loans(source_node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_loans_target ON mesh_agent_loans(target_node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_loans_status ON mesh_agent_loans(status);
CREATE INDEX IF NOT EXISTS idx_mesh_loans_active ON mesh_agent_loans(status) WHERE status = 'active';

-- ============================================================================
-- 4. SUBSCRIPTIONS (tier, features, billing for business nodes)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_subscriptions (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL,
    tier VARCHAR(20) NOT NULL DEFAULT 'core',
    features JSONB DEFAULT '[]',
    started_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    CONSTRAINT fk_subscription_org FOREIGN KEY (org_id)
        REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT uq_subscription_org UNIQUE (org_id)
);

CREATE INDEX IF NOT EXISTS idx_mesh_subscriptions_org ON mesh_subscriptions(org_id);
CREATE INDEX IF NOT EXISTS idx_mesh_subscriptions_tier ON mesh_subscriptions(tier);

-- ============================================================================
-- 5. ADD deployment_mode TO remote_nodes (if not exists)
-- ============================================================================

ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS deployment_mode VARCHAR(30) DEFAULT 'ollama_only';

-- ============================================================================
-- 6. MESH SYNC LOG (hub tracks what was synced to each node)
-- ============================================================================

CREATE TABLE IF NOT EXISTS mesh_sync_log (
    id SERIAL PRIMARY KEY,
    node_id VARCHAR(50) NOT NULL,
    sync_type VARCHAR(50) NOT NULL,
    payload JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'sent',
    sent_at TIMESTAMP DEFAULT NOW(),
    acknowledged_at TIMESTAMP,
    error_message TEXT,
    CONSTRAINT fk_sync_node FOREIGN KEY (node_id)
        REFERENCES remote_nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mesh_sync_node ON mesh_sync_log(node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_sync_type ON mesh_sync_log(sync_type);

-- ============================================================================
-- 7. HELPER VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_mesh_cluster_overview AS
SELECT
    rn.node_id,
    rn.node_name,
    rn.vpn_ip,
    rn.status,
    rn.approval_status,
    rn.deployment_mode,
    rn.gpu_model,
    rn.gpu_vram_gb,
    rn.cpu_cores,
    rn.ram_gb,
    rn.current_load,
    rn.max_concurrent,
    rn.bridge_enabled,
    rn.last_heartbeat,
    o.name AS org_name,
    o.id AS org_id,
    ms.tier AS subscription_tier,
    mcv.version AS code_version,
    mcv.git_commit,
    (SELECT COUNT(*) FROM node_ollama_models nom WHERE nom.node_id = rn.node_id) AS model_count,
    (SELECT COUNT(*) FROM mesh_agent_loans mal WHERE mal.source_node_id = rn.node_id AND mal.status = 'active') AS agents_lent,
    (SELECT COUNT(*) FROM mesh_agent_loans mal WHERE mal.target_node_id = rn.node_id AND mal.status = 'active') AS agents_borrowed
FROM remote_nodes rn
LEFT JOIN organizations o ON o.node_id = rn.node_id
LEFT JOIN mesh_subscriptions ms ON ms.org_id = o.id
LEFT JOIN mesh_code_versions mcv ON mcv.node_id = rn.node_id
WHERE rn.is_active = true AND rn.approval_status = 'approved';

CREATE OR REPLACE VIEW v_mesh_agent_availability AS
SELECT
    mal.id AS loan_id,
    mal.agent_id,
    mal.source_node_id,
    sn.node_name AS source_node_name,
    mal.target_node_id,
    tn.node_name AS target_node_name,
    mal.task_description,
    mal.status,
    mal.lent_at,
    mal.returned_at
FROM mesh_agent_loans mal
JOIN remote_nodes sn ON sn.node_id = mal.source_node_id
JOIN remote_nodes tn ON tn.node_id = mal.target_node_id;
