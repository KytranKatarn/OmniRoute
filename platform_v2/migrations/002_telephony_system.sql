-- ============================================================================
-- A.R.C.H.I.E. AI Call Handler System - Database Schema
-- Migration: 002 - Telephony System
-- Created: 2025-12-28
-- ============================================================================

-- ============================================================================
-- TELEPHONY PROVIDERS
-- ============================================================================

CREATE TABLE IF NOT EXISTS providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    type VARCHAR(30) NOT NULL CHECK (type IN ('telus', 'twilio', 'telnyx', 'custom_sip')),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'testing', 'error')),
    capabilities JSONB NOT NULL DEFAULT '{}',
    webhook_endpoints JSONB NOT NULL DEFAULT '{}',
    authentication JSONB NOT NULL DEFAULT '{}',
    cost_per_minute DECIMAL(6,4),
    quality_score INTEGER CHECK (quality_score BETWEEN 1 AND 10),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_providers_type ON providers(type);
CREATE INDEX IF NOT EXISTS idx_providers_status ON providers(status);

-- Sample provider data
INSERT INTO providers (name, type, capabilities, webhook_endpoints, cost_per_minute, quality_score)
VALUES
    ('telus_business_connect', 'telus',
     '{"inbound_calls": true, "outbound_calls": true, "call_recording": false}',
     '{"sip_call": "/webhook/telus/sip-call"}',
     0.0200, 7),
    ('twilio_production', 'twilio',
     '{"inbound_calls": true, "outbound_calls": true, "recording": true, "transcription": true, "conference": true}',
     '{"voice": "/webhook/twilio/voice", "status": "/webhook/twilio/status", "stream": "wss://domain/stream/twilio/audio"}',
     0.0140, 9),
    ('telnyx_backup', 'telnyx',
     '{"inbound_calls": true, "outbound_calls": true, "recording": true, "call_control": true, "webrtc": true}',
     '{"call_control": "/webhook/telnyx/call-control", "stream": "wss://domain/stream/telnyx/audio"}',
     0.0040, 8)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- CUSTOMERS / CALLERS
-- ============================================================================

CREATE TABLE IF NOT EXISTS customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_number VARCHAR(20) UNIQUE,
    email VARCHAR(255),
    name VARCHAR(255),
    company_name VARCHAR(255),
    customer_type VARCHAR(30) DEFAULT 'prospect' CHECK (customer_type IN ('prospect', 'active', 'inactive', 'vip')),
    crm_id VARCHAR(100),
    total_calls INTEGER DEFAULT 0,
    successful_calls INTEGER DEFAULT 0,
    escalated_calls INTEGER DEFAULT 0,
    average_satisfaction DECIMAL(2,1) CHECK (average_satisfaction BETWEEN 1.0 AND 5.0),
    lifetime_value DECIMAL(10,2),
    preferences JSONB DEFAULT '{}',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone_number);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);
CREATE INDEX IF NOT EXISTS idx_customers_crm_id ON customers(crm_id);
CREATE INDEX IF NOT EXISTS idx_customers_type ON customers(customer_type);

-- ============================================================================
-- CONVERSATIONS (CALLS)
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_sid VARCHAR(100) NOT NULL UNIQUE,
    provider_id UUID REFERENCES providers(id),
    customer_id UUID REFERENCES customers(id),
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    caller_number VARCHAR(20),
    called_number VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'failed', 'escalated', 'abandoned')),
    intent VARCHAR(50) CHECK (intent IN ('sales', 'support', 'general', 'escalation', 'billing', 'technical', 'unknown')),
    agent_type VARCHAR(30) CHECK (agent_type IN ('claude', 'archie', 'hybrid', 'human', 'tier1', 'tier2', 'tier3')),
    assigned_agent_id UUID REFERENCES agents(id),
    start_time TIMESTAMP NOT NULL DEFAULT NOW(),
    end_time TIMESTAMP,
    duration_seconds INTEGER,
    outcome VARCHAR(30) CHECK (outcome IN ('resolved', 'escalated', 'failed', 'abandoned', 'callback_scheduled', 'pending')),
    customer_satisfaction DECIMAL(2,1) CHECK (customer_satisfaction BETWEEN 1.0 AND 5.0),
    recording_url TEXT,
    transcript_url TEXT,
    cost DECIMAL(10,4),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_customer ON conversations(customer_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_start_time ON conversations(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_provider ON conversations(provider_id);
CREATE INDEX IF NOT EXISTS idx_conversations_agent ON conversations(assigned_agent_id);
CREATE INDEX IF NOT EXISTS idx_conversations_intent ON conversations(intent);

-- ============================================================================
-- CONVERSATION TURNS
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversation_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('customer', 'ai', 'system', 'human_agent')),
    content TEXT NOT NULL,
    audio_url TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    duration_seconds DECIMAL(6,2),
    confidence_score DECIMAL(3,2) CHECK (confidence_score BETWEEN 0.00 AND 1.00),
    intent VARCHAR(50),
    sentiment VARCHAR(20) CHECK (sentiment IN ('positive', 'neutral', 'negative', 'frustrated', 'satisfied', 'angry')),
    ai_source VARCHAR(30) CHECK (ai_source IN ('claude', 'archie', 'hybrid', 'n8n_workflow')),
    tokens_used INTEGER,
    processing_time_ms INTEGER,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_turns_conversation ON conversation_turns(conversation_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON conversation_turns(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_turns_sentiment ON conversation_turns(sentiment);

-- ============================================================================
-- ESCALATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS escalations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id),
    escalation_reason VARCHAR(100) NOT NULL,
    trigger_type VARCHAR(50) CHECK (trigger_type IN ('customer_request', 'confidence_threshold', 'sentiment', 'timeout', 'policy', 'complexity', 'billing_issue')),
    escalated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    assigned_to VARCHAR(100),
    assigned_to_user_id UUID REFERENCES users(id),
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    was_necessary BOOLEAN,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_escalations_conversation ON escalations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_escalations_reason ON escalations(escalation_reason);
CREATE INDEX IF NOT EXISTS idx_escalations_date ON escalations(escalated_at DESC);
CREATE INDEX IF NOT EXISTS idx_escalations_assigned ON escalations(assigned_to_user_id);

-- ============================================================================
-- AI PERFORMANCE METRICS
-- ============================================================================

CREATE TABLE IF NOT EXISTS ai_performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    agent_type VARCHAR(30) NOT NULL CHECK (agent_type IN ('claude', 'archie', 'hybrid', 'tier1', 'tier2', 'tier3')),
    intent_category VARCHAR(50),
    total_conversations INTEGER DEFAULT 0,
    successful_resolutions INTEGER DEFAULT 0,
    escalations INTEGER DEFAULT 0,
    average_handling_time_seconds INTEGER,
    average_confidence DECIMAL(3,2),
    average_satisfaction DECIMAL(2,1),
    total_cost DECIMAL(10,2),
    total_tokens_used BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(date, agent_type, intent_category)
);

CREATE INDEX IF NOT EXISTS idx_metrics_date ON ai_performance_metrics(date DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_agent ON ai_performance_metrics(agent_type, date DESC);

-- ============================================================================
-- KNOWLEDGE BASE QUERIES (for tracking archie searches)
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_base_queries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id),
    turn_id UUID REFERENCES conversation_turns(id),
    query TEXT NOT NULL,
    category VARCHAR(50),
    results_count INTEGER,
    top_result_confidence DECIMAL(3,2),
    query_time_ms INTEGER,
    was_helpful BOOLEAN,
    timestamp TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_queries_conversation ON knowledge_base_queries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_kb_queries_timestamp ON knowledge_base_queries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_kb_queries_category ON knowledge_base_queries(category);

-- ============================================================================
-- SYSTEM ALERTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type VARCHAR(50) NOT NULL CHECK (alert_type IN (
        'performance_degradation', 'high_escalation_rate', 'provider_failure',
        'ai_service_down', 'database_error', 'cost_threshold_exceeded'
    )),
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('info', 'warning', 'error', 'critical')),
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    acknowledged BOOLEAN DEFAULT false,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMP,
    resolved BOOLEAN DEFAULT false,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_unresolved ON system_alerts(resolved, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON system_alerts(alert_type);

-- ============================================================================
-- N8N WORKFLOW EXECUTIONS (tracking automation workflows)
-- ============================================================================

CREATE TABLE IF NOT EXISTS n8n_workflow_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id VARCHAR(100) NOT NULL,
    workflow_name VARCHAR(255),
    conversation_id UUID REFERENCES conversations(id),
    execution_id VARCHAR(100),
    status VARCHAR(30) CHECK (status IN ('running', 'success', 'error', 'waiting')),
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP,
    duration_ms INTEGER,
    error_message TEXT,
    input_data JSONB,
    output_data JSONB,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_n8n_executions_workflow ON n8n_workflow_executions(workflow_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_n8n_executions_conversation ON n8n_workflow_executions(conversation_id);
CREATE INDEX IF NOT EXISTS idx_n8n_executions_status ON n8n_workflow_executions(status);

-- ============================================================================
-- AGENT SKILL ASSIGNMENTS (for tiered agent system)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(50) CHECK (skill_category IN ('support', 'development', 'operations', 'sales', 'billing', 'technical')),
    proficiency_level INTEGER CHECK (proficiency_level BETWEEN 1 AND 5),
    can_escalate_to UUID REFERENCES agents(id),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(agent_id, skill_name)
);

CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_skills_category ON agent_skills(skill_category);
CREATE INDEX IF NOT EXISTS idx_agent_skills_proficiency ON agent_skills(proficiency_level DESC);

-- ============================================================================
-- CALL QUEUE (for managing incoming calls)
-- ============================================================================

CREATE TABLE IF NOT EXISTS call_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id),
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    queue_type VARCHAR(30) CHECK (queue_type IN ('sales', 'support', 'billing', 'general', 'vip')),
    customer_id UUID REFERENCES customers(id),
    assigned_agent_id UUID REFERENCES agents(id),
    status VARCHAR(20) DEFAULT 'waiting' CHECK (status IN ('waiting', 'assigned', 'in_progress', 'completed', 'abandoned')),
    queued_at TIMESTAMP NOT NULL DEFAULT NOW(),
    assigned_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    wait_time_seconds INTEGER,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_call_queue_status ON call_queue(status, priority DESC, queued_at);
CREATE INDEX IF NOT EXISTS idx_call_queue_type ON call_queue(queue_type, status);
CREATE INDEX IF NOT EXISTS idx_call_queue_agent ON call_queue(assigned_agent_id);

-- ============================================================================
-- TRIGGER FUNCTIONS FOR UPDATED_AT
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at trigger to relevant tables
DROP TRIGGER IF EXISTS update_providers_updated_at ON providers;
CREATE TRIGGER update_providers_updated_at BEFORE UPDATE ON providers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_customers_updated_at ON customers;
CREATE TRIGGER update_customers_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_conversations_updated_at ON conversations;
CREATE TRIGGER update_conversations_updated_at BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_agent_skills_updated_at ON agent_skills;
CREATE TRIGGER update_agent_skills_updated_at BEFORE UPDATE ON agent_skills
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Active conversations view
CREATE OR REPLACE VIEW active_conversations_view AS
SELECT
    c.id,
    c.call_sid,
    c.direction,
    c.status,
    c.intent,
    cust.name as customer_name,
    cust.phone_number,
    p.name as provider_name,
    a.name as agent_name,
    c.start_time,
    EXTRACT(EPOCH FROM (NOW() - c.start_time))::INTEGER as duration_seconds
FROM conversations c
LEFT JOIN customers cust ON c.customer_id = cust.id
LEFT JOIN providers p ON c.provider_id = p.id
LEFT JOIN agents a ON c.assigned_agent_id = a.id
WHERE c.status = 'active';

-- Today's performance summary
CREATE OR REPLACE VIEW daily_performance_summary AS
SELECT
    DATE(start_time) as date,
    COUNT(*) as total_calls,
    COUNT(*) FILTER (WHERE outcome = 'resolved') as resolved,
    COUNT(*) FILTER (WHERE outcome = 'escalated') as escalated,
    AVG(duration_seconds) as avg_duration,
    AVG(customer_satisfaction) as avg_satisfaction,
    SUM(cost) as total_cost
FROM conversations
WHERE start_time > CURRENT_DATE
GROUP BY DATE(start_time);

-- ============================================================================
-- GRANT PERMISSIONS (adjust as needed)
-- ============================================================================

-- Grant permissions to archie user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO archie;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO archie;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

-- Log migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('002', 'Telephony System Tables', NOW())
ON CONFLICT (version) DO NOTHING;

-- Success message
DO $$
BEGIN
    RAISE NOTICE '✅ Migration 002 - Telephony System completed successfully';
END $$;
