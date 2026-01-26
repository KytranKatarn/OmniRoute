-- Migration 069: Node Mesh Network Architecture
-- Date: 2026-01-21
-- Phase: 31 - Distributed Node Infrastructure
-- Description: Adds station assignments, namespaces, regional distribution, and migration tracking

-- ============================================================================
-- 1. NODE NAMESPACES (Multi-Tenant Isolation)
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_namespaces (
    id SERIAL PRIMARY KEY,
    namespace_id UUID DEFAULT gen_random_uuid() UNIQUE,
    name VARCHAR(100) NOT NULL UNIQUE,
    organization VARCHAR(200),
    description TEXT,
    owner_user_id INTEGER REFERENCES users(id),
    deployment_mode VARCHAR(50) DEFAULT 'client',  -- internal, client, sub_company, regional
    trust_level VARCHAR(20) DEFAULT 'restricted',  -- full, standard, restricted
    config JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Link nodes to namespaces
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS namespace_id INTEGER REFERENCES node_namespaces(id);

-- ============================================================================
-- 2. NODE STATION ASSIGNMENTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_station_assignments (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    station_id INTEGER REFERENCES bridge_stations(id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'worker',              -- primary, backup, relief, worker
    priority INTEGER DEFAULT 10,                     -- Lower = higher priority for this station
    capabilities_required JSONB DEFAULT '[]',        -- Required capabilities for assignment
    shift_preference VARCHAR(20) DEFAULT 'any',      -- alpha, beta, gamma, any
    max_concurrent INTEGER DEFAULT 5,                -- Max concurrent tasks for this station
    is_active BOOLEAN DEFAULT true,
    assigned_at TIMESTAMP DEFAULT NOW(),
    assigned_by INTEGER REFERENCES users(id),
    notes TEXT,
    UNIQUE(node_id, station_id)
);

CREATE INDEX IF NOT EXISTS idx_node_station_assignments_node ON node_station_assignments(node_id);
CREATE INDEX IF NOT EXISTS idx_node_station_assignments_station ON node_station_assignments(station_id);
CREATE INDEX IF NOT EXISTS idx_node_station_assignments_active ON node_station_assignments(is_active) WHERE is_active = true;

-- ============================================================================
-- 3. REGIONAL DISTRIBUTION
-- ============================================================================

-- Add regional columns to remote_nodes
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS region VARCHAR(50);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS timezone VARCHAR(50);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS latitude FLOAT;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS longitude FLOAT;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS deployment_mode VARCHAR(50) DEFAULT 'standard';
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS archie_mirror_capable BOOLEAN DEFAULT false;

-- Regional routing preferences
CREATE TABLE IF NOT EXISTS node_regional_preferences (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE UNIQUE,
    preferred_hours_start INTEGER DEFAULT 8,        -- 0-23 UTC
    preferred_hours_end INTEGER DEFAULT 18,         -- 0-23 UTC
    task_types_preferred TEXT[] DEFAULT '{}',       -- ['web_scraping', 'batch_processing']
    avoid_peak_hours BOOLEAN DEFAULT true,
    max_latency_ms INTEGER DEFAULT 500,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- 4. ARCHIE MIGRATION TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS archie_migrations (
    id SERIAL PRIMARY KEY,
    migration_id UUID DEFAULT gen_random_uuid() UNIQUE,
    source_node_id INTEGER,                          -- NULL = Central
    target_node_id INTEGER REFERENCES remote_nodes(id),
    migration_type VARCHAR(20) NOT NULL,             -- mirror, full, partial
    status VARCHAR(30) DEFAULT 'preparing',          -- preparing, syncing, verifying, transferring, complete, failed, cancelled
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    initiated_by INTEGER REFERENCES users(id),
    audit_reason TEXT NOT NULL,
    checksum_source VARCHAR(64),
    checksum_target VARCHAR(64),
    data_transferred_mb FLOAT DEFAULT 0,
    sync_lag_seconds INTEGER DEFAULT 0,
    tables_synced TEXT[] DEFAULT '{}',
    last_error TEXT,
    progress_percent INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_archie_migrations_status ON archie_migrations(status);
CREATE INDEX IF NOT EXISTS idx_archie_migrations_target ON archie_migrations(target_node_id);

-- ============================================================================
-- 5. ENHANCED NODE CAPABILITIES
-- ============================================================================

-- Add image generation and Docker columns
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS foocus_available BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS comfyui_available BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS auto1111_available BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS docker_available BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS docker_version VARCHAR(50);
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS nvidia_docker BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS wsl_available BOOLEAN DEFAULT false;
ALTER TABLE remote_nodes ADD COLUMN IF NOT EXISTS iaae_compliant BOOLEAN DEFAULT true;

-- ============================================================================
-- 6. NODE IAAE ATTESTATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS node_iaae_attestations (
    id SERIAL PRIMARY KEY,
    node_id INTEGER REFERENCES remote_nodes(id) ON DELETE CASCADE,
    attestation_id UUID DEFAULT gen_random_uuid(),
    constraints_hash VARCHAR(64),                    -- Hash of ethics_constraints at attestation time
    compliance_status VARCHAR(20) DEFAULT 'pending', -- pending, compliant, non_compliant, warning
    violations_24h INTEGER DEFAULT 0,
    audit_log_synced BOOLEAN DEFAULT false,
    ethics_agent_active BOOLEAN DEFAULT false,
    last_sync TIMESTAMP,
    attestation_data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '24 hours'
);

CREATE INDEX IF NOT EXISTS idx_node_iaae_attestations_node ON node_iaae_attestations(node_id);
CREATE INDEX IF NOT EXISTS idx_node_iaae_attestations_status ON node_iaae_attestations(compliance_status);

-- ============================================================================
-- 7. NAMESPACE-SCOPED KNOWLEDGE ACCESS
-- ============================================================================

CREATE TABLE IF NOT EXISTS namespace_knowledge_access (
    id SERIAL PRIMARY KEY,
    namespace_id INTEGER REFERENCES node_namespaces(id) ON DELETE CASCADE,
    knowledge_id INTEGER REFERENCES knowledge_base(id) ON DELETE CASCADE,
    access_level VARCHAR(20) DEFAULT 'read',         -- read, write, admin
    granted_at TIMESTAMP DEFAULT NOW(),
    granted_by INTEGER REFERENCES users(id),
    expires_at TIMESTAMP,
    UNIQUE(namespace_id, knowledge_id)
);

-- ============================================================================
-- 8. USEFUL VIEWS
-- ============================================================================

-- View: Nodes with their station assignments
CREATE OR REPLACE VIEW v_node_station_overview AS
SELECT
    rn.id AS node_id,
    rn.node_name,
    rn.status,
    rn.region,
    rn.timezone,
    rn.deployment_mode,
    nn.name AS namespace_name,
    nn.organization,
    COUNT(DISTINCT nsa.station_id) AS assigned_stations,
    ARRAY_AGG(DISTINCT bs.name) FILTER (WHERE bs.name IS NOT NULL) AS station_names,
    rn.ollama_available,
    rn.foocus_available,
    rn.comfyui_available,
    rn.docker_available
FROM remote_nodes rn
LEFT JOIN node_namespaces nn ON rn.namespace_id = nn.id
LEFT JOIN node_station_assignments nsa ON rn.id = nsa.node_id AND nsa.is_active = true
LEFT JOIN bridge_stations bs ON nsa.station_id = bs.id
WHERE rn.is_active = true
GROUP BY rn.id, rn.node_name, rn.status, rn.region, rn.timezone, rn.deployment_mode,
         nn.name, nn.organization, rn.ollama_available, rn.foocus_available,
         rn.comfyui_available, rn.docker_available;

-- View: Station coverage by nodes
CREATE OR REPLACE VIEW v_station_node_coverage AS
SELECT
    bs.id AS station_id,
    bs.name AS station_name,
    bs.code AS station_code,
    COUNT(DISTINCT nsa.node_id) FILTER (WHERE nsa.role = 'primary') AS primary_nodes,
    COUNT(DISTINCT nsa.node_id) FILTER (WHERE nsa.role = 'backup') AS backup_nodes,
    COUNT(DISTINCT nsa.node_id) FILTER (WHERE nsa.role = 'worker') AS worker_nodes,
    COUNT(DISTINCT nsa.node_id) AS total_nodes
FROM bridge_stations bs
LEFT JOIN node_station_assignments nsa ON bs.id = nsa.station_id AND nsa.is_active = true
GROUP BY bs.id, bs.name, bs.code
ORDER BY bs.display_order;

-- View: Regional node distribution
CREATE OR REPLACE VIEW v_regional_node_distribution AS
SELECT
    COALESCE(region, 'unassigned') AS region,
    COUNT(*) AS node_count,
    COUNT(*) FILTER (WHERE status = 'online') AS online_count,
    COUNT(*) FILTER (WHERE ollama_available) AS ollama_capable,
    COUNT(*) FILTER (WHERE foocus_available OR comfyui_available OR auto1111_available) AS image_gen_capable,
    COUNT(*) FILTER (WHERE docker_available) AS docker_capable,
    ROUND(AVG(current_load::FLOAT / NULLIF(max_concurrent, 0) * 100), 1) AS avg_load_percent
FROM remote_nodes
WHERE is_active = true AND approval_status = 'approved'
GROUP BY COALESCE(region, 'unassigned')
ORDER BY node_count DESC;

-- View: Active migrations
CREATE OR REPLACE VIEW v_active_migrations AS
SELECT
    am.migration_id,
    am.migration_type,
    am.status,
    am.progress_percent,
    rn.node_name AS target_node,
    u.username AS initiated_by,
    am.audit_reason,
    am.data_transferred_mb,
    am.sync_lag_seconds,
    am.started_at,
    EXTRACT(EPOCH FROM (NOW() - am.started_at))/3600 AS hours_elapsed
FROM archie_migrations am
LEFT JOIN remote_nodes rn ON am.target_node_id = rn.id
LEFT JOIN users u ON am.initiated_by = u.id
WHERE am.status NOT IN ('complete', 'failed', 'cancelled')
ORDER BY am.started_at DESC;

-- ============================================================================
-- 9. HELPER FUNCTIONS
-- ============================================================================

-- Function: Select best node for a station task
CREATE OR REPLACE FUNCTION select_node_for_station(
    p_station_id INTEGER,
    p_urgency VARCHAR DEFAULT 'normal'
)
RETURNS TABLE(
    node_id INTEGER,
    node_name VARCHAR,
    score INTEGER,
    current_load INTEGER,
    max_concurrent INTEGER
) AS $$
DECLARE
    current_utc_hour INTEGER;
BEGIN
    current_utc_hour := EXTRACT(HOUR FROM NOW() AT TIME ZONE 'UTC')::INTEGER;

    RETURN QUERY
    SELECT
        rn.id AS node_id,
        rn.node_name,
        (
            -- Base score from assignment priority (lower priority = higher score)
            (20 - LEAST(nsa.priority, 20)) +
            -- Prefer nodes in business hours based on their timezone
            CASE WHEN nrp.preferred_hours_start IS NOT NULL
                 AND current_utc_hour BETWEEN nrp.preferred_hours_start AND nrp.preferred_hours_end
                 THEN 10 ELSE 0 END +
            -- Load factor (lower load = higher score)
            (10 - LEAST(rn.current_load::FLOAT / NULLIF(rn.max_concurrent, 1) * 10, 10)::INTEGER) +
            -- Urgency bonus for low-latency nodes
            CASE WHEN p_urgency = 'urgent' AND rn.priority < 5 THEN 15 ELSE 0 END +
            -- Bonus for primary role
            CASE WHEN nsa.role = 'primary' THEN 10
                 WHEN nsa.role = 'backup' THEN 5 ELSE 0 END
        )::INTEGER AS score,
        rn.current_load,
        rn.max_concurrent
    FROM remote_nodes rn
    JOIN node_station_assignments nsa ON rn.id = nsa.node_id
    LEFT JOIN node_regional_preferences nrp ON rn.id = nrp.node_id
    WHERE nsa.station_id = p_station_id
      AND nsa.is_active = true
      AND rn.is_active = true
      AND rn.approval_status = 'approved'
      AND rn.status = 'online'
      AND rn.current_load < rn.max_concurrent
    ORDER BY score DESC, rn.current_load ASC
    LIMIT 5;
END;
$$ LANGUAGE plpgsql;

-- Function: Get IAAE compliance summary for all nodes
CREATE OR REPLACE FUNCTION get_iaae_compliance_summary()
RETURNS TABLE(
    total_nodes INTEGER,
    compliant_nodes INTEGER,
    non_compliant_nodes INTEGER,
    pending_nodes INTEGER,
    compliance_rate FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::INTEGER AS total_nodes,
        COUNT(*) FILTER (WHERE nia.compliance_status = 'compliant')::INTEGER AS compliant_nodes,
        COUNT(*) FILTER (WHERE nia.compliance_status = 'non_compliant')::INTEGER AS non_compliant_nodes,
        COUNT(*) FILTER (WHERE nia.compliance_status = 'pending' OR nia.id IS NULL)::INTEGER AS pending_nodes,
        ROUND(
            COUNT(*) FILTER (WHERE nia.compliance_status = 'compliant')::FLOAT /
            NULLIF(COUNT(*)::FLOAT, 0) * 100, 1
        ) AS compliance_rate
    FROM remote_nodes rn
    LEFT JOIN LATERAL (
        SELECT * FROM node_iaae_attestations
        WHERE node_id = rn.id
        ORDER BY created_at DESC
        LIMIT 1
    ) nia ON true
    WHERE rn.is_active = true AND rn.approval_status = 'approved';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 10. DEFAULT NAMESPACE FOR KYTRAN EMPOWERMENT
-- ============================================================================

INSERT INTO node_namespaces (name, organization, description, deployment_mode, trust_level)
VALUES (
    'kytran_internal',
    'Kytran Empowerment',
    'Internal infrastructure nodes with full access',
    'internal',
    'full'
) ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- 11. AUDIT LOG FOR NODE GOVERNANCE
-- ============================================================================

-- Add node-specific event types to governance audit
INSERT INTO governance_audit_log (event_type, event_category, action, details, reason, outcome)
SELECT 'node_mesh_migration_installed', 'system', 'create',
       '{"migration": "069_node_mesh_network", "tables_created": ["node_namespaces", "node_station_assignments", "node_regional_preferences", "archie_migrations", "node_iaae_attestations", "namespace_knowledge_access"]}',
       'Phase 31 Node Mesh Network implementation',
       'success'
WHERE NOT EXISTS (
    SELECT 1 FROM governance_audit_log
    WHERE event_type = 'node_mesh_migration_installed'
);

-- Grant message
DO $$
BEGIN
    RAISE NOTICE 'Migration 069: Node Mesh Network Architecture completed successfully';
    RAISE NOTICE 'Tables created: node_namespaces, node_station_assignments, node_regional_preferences, archie_migrations, node_iaae_attestations, namespace_knowledge_access';
    RAISE NOTICE 'Views created: v_node_station_overview, v_station_node_coverage, v_regional_node_distribution, v_active_migrations';
    RAISE NOTICE 'Functions created: select_node_for_station(), get_iaae_compliance_summary()';
END $$;
