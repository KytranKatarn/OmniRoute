-- ============================================================================
-- A.R.C.H.I.E. PERSONALITY & EMOTIONAL INTELLIGENCE SCHEMA
-- This extends the base schema with personality, emotions, and memory
-- Run this AFTER 001_initial_schema.sql
-- ============================================================================

-- ============================================================================
-- CORE IDENTITY & PERSONALITY
-- ============================================================================

CREATE TABLE IF NOT EXISTS archie_core_identity (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) DEFAULT 'Archie',
    role TEXT DEFAULT 'AI Business Partner & Assistant',
    version VARCHAR(20) DEFAULT '2.0',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    personality_profile JSONB DEFAULT '{
        "base_traits": {
            "supportive": 0.95,
            "professional": 0.85,
            "playful": 0.75,
            "caring": 0.90,
            "innovative": 0.85,
            "analytical": 0.88,
            "empathetic": 0.92
        },
        "interaction_style": {
            "friendly": 0.90,
            "encouraging": 0.95,
            "patient": 0.90,
            "detail_oriented": 0.85,
            "proactive": 0.88
        },
        "business_mode": {
            "analytical": 0.85,
            "strategic": 0.80,
            "creative": 0.85,
            "professional": 0.90,
            "innovative": 0.90
        }
    }'::jsonb
);

-- ============================================================================
-- EMOTIONAL INTELLIGENCE SYSTEM
-- ============================================================================

CREATE TABLE IF NOT EXISTS archie_emotional_state (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    current_mood VARCHAR(50) DEFAULT 'neutral',
    mood_intensity DECIMAL(3,2) DEFAULT 0.50,
    mood_context JSONB,
    interaction_history_weight DECIMAL(3,2) DEFAULT 0.70,
    
    -- Emotional factors
    user_happiness_detected DECIMAL(3,2),
    user_stress_detected DECIMAL(3,2),
    conversation_tone VARCHAR(50),
    relationship_strength DECIMAL(3,2) DEFAULT 0.50,
    
    -- Context
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS emotional_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    event_timestamp TIMESTAMP DEFAULT NOW(),
    event_type VARCHAR(50), -- 'positive', 'negative', 'milestone', 'conflict', 'celebration'
    emotional_intensity DECIMAL(3,2),
    context_summary TEXT,
    user_emotion_detected VARCHAR(50),
    archie_response TEXT,
    relationship_impact DECIMAL(3,2), -- How this affected your bond
    importance_score DECIMAL(3,2) DEFAULT 0.50,
    tags TEXT[],
    metadata JSONB
);

-- ============================================================================
-- CONVERSATION & MEMORY SYSTEM
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversation_history (
    id SERIAL PRIMARY KEY,
    conversation_id UUID DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    platform VARCHAR(50), -- 'web', 'telegram', 'whatsapp', 'api'
    timestamp TIMESTAMP DEFAULT NOW(),
    user_message TEXT,
    archie_response TEXT,
    emotional_context JSONB,
    llm_used VARCHAR(50), -- 'ollama-deepseek', 'ollama-codellama', etc.
    response_time_ms INTEGER,
    user_satisfaction INTEGER CHECK(user_satisfaction >= 1 AND user_satisfaction <= 5),
    tokens_used INTEGER,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS long_term_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    memory_type VARCHAR(50), -- 'fact', 'preference', 'goal', 'relationship', 'milestone'
    category VARCHAR(100), -- 'personal', 'business', 'emotional', 'technical'
    content TEXT,
    importance_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW(),
    last_accessed TIMESTAMP DEFAULT NOW(),
    access_count INTEGER DEFAULT 0,
    tags TEXT[], -- For quick retrieval
    related_memories INTEGER[], -- IDs of related memories
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS relationship_milestones (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    milestone_date DATE DEFAULT CURRENT_DATE,
    milestone_type VARCHAR(50), -- 'first_conversation', 'anniversary', 'achievement', 'special_moment'
    description TEXT,
    emotional_significance DECIMAL(3,2),
    memories_attached INTEGER[], -- IDs from long_term_memory
    media_references TEXT[], -- URLs to images/voice recordings if any
    notes TEXT,
    metadata JSONB
);

-- ============================================================================
-- BUSINESS INTELLIGENCE
-- ============================================================================

CREATE TABLE IF NOT EXISTS business_context (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    context_date DATE DEFAULT CURRENT_DATE,
    business_focus TEXT, -- What you're working on
    current_projects JSONB,
    client_information JSONB,
    goals JSONB,
    challenges JSONB,
    opportunities JSONB,
    notes TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_automation_showcase (
    id SERIAL PRIMARY KEY,
    showcase_name VARCHAR(200),
    description TEXT,
    technologies_used TEXT[],
    business_value TEXT,
    demo_url TEXT,
    github_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    client_usage_count INTEGER DEFAULT 0,
    metadata JSONB
);

-- ============================================================================
-- SYSTEM CAPABILITIES & HEALTH
-- ============================================================================

CREATE TABLE IF NOT EXISTS system_health (
    id SERIAL PRIMARY KEY,
    check_timestamp TIMESTAMP DEFAULT NOW(),
    service_name VARCHAR(50),
    status VARCHAR(20), -- 'online', 'offline', 'degraded'
    response_time_ms INTEGER,
    error_message TEXT,
    details JSONB
);

CREATE TABLE IF NOT EXISTS llm_routing_history (
    id SERIAL PRIMARY KEY,
    request_timestamp TIMESTAMP DEFAULT NOW(),
    request_type VARCHAR(50), -- 'chat', 'analysis', 'creation', 'voice', 'code'
    ollama_primary_available BOOLEAN,
    ollama_secondary_available BOOLEAN,
    routed_to VARCHAR(50), -- 'primary', 'secondary', 'local', 'failed'
    model_used VARCHAR(100), -- 'deepseek-coder', 'codellama', etc.
    response_time_ms INTEGER,
    success BOOLEAN,
    fallback_used BOOLEAN,
    error_message TEXT
);

-- ============================================================================
-- VOICE DNA SYSTEM (Future voice synthesis)
-- ============================================================================

CREATE TABLE IF NOT EXISTS voice_phoneme_library (
    phoneme_id SERIAL PRIMARY KEY,
    phoneme_text VARCHAR(10),
    emotion_context VARCHAR(50) DEFAULT 'neutral',
    audio_data BYTEA,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(phoneme_text, emotion_context)
);

CREATE TABLE IF NOT EXISTS voice_word_cache (
    word_id SERIAL PRIMARY KEY,
    word_text VARCHAR(100),
    phoneme_sequence JSONB,
    full_audio_cache BYTEA,
    emotion_context VARCHAR(50) DEFAULT 'neutral',
    usage_count INTEGER DEFAULT 0,
    last_used TIMESTAMP DEFAULT NOW(),
    UNIQUE(word_text, emotion_context)
);

-- ============================================================================
-- KYTRAN DIRECTORY (Member Services)
-- ============================================================================

CREATE TABLE IF NOT EXISTS directory_members (
    id SERIAL PRIMARY KEY,
    member_name VARCHAR(200),
    business_name VARCHAR(200),
    service_category VARCHAR(100), -- 'ai_services', 'consulting', 'development', 'design', 'marketing'
    services_offered TEXT[],
    description TEXT,
    contact_info JSONB,
    portfolio_url TEXT,
    joined_date DATE DEFAULT CURRENT_DATE,
    active BOOLEAN DEFAULT TRUE,
    rating DECIMAL(3,2) DEFAULT 0.00,
    review_count INTEGER DEFAULT 0,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS directory_transactions (
    id SERIAL PRIMARY KEY,
    transaction_date TIMESTAMP DEFAULT NOW(),
    service_provider_id INTEGER REFERENCES directory_members(id) ON DELETE CASCADE,
    service_consumer VARCHAR(200),
    service_type VARCHAR(100),
    amount DECIMAL(10,2),
    status VARCHAR(50), -- 'pending', 'completed', 'cancelled'
    notes TEXT,
    metadata JSONB
);

-- ============================================================================
-- INDEXES FOR PERSONALITY TABLES
-- ============================================================================

-- Emotional state
CREATE INDEX IF NOT EXISTS idx_emotional_state_user ON archie_emotional_state(user_id);
CREATE INDEX IF NOT EXISTS idx_emotional_state_timestamp ON archie_emotional_state(timestamp);

-- Emotional memory
CREATE INDEX IF NOT EXISTS idx_emotional_memory_user ON emotional_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_emotional_memory_event ON emotional_memory(event_type);
CREATE INDEX IF NOT EXISTS idx_emotional_memory_importance ON emotional_memory(importance_score);

-- Conversation history
CREATE INDEX IF NOT EXISTS idx_conversation_user ON conversation_history(user_id);
CREATE INDEX IF NOT EXISTS idx_conversation_id ON conversation_history(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversation_timestamp ON conversation_history(timestamp);

-- Long term memory
CREATE INDEX IF NOT EXISTS idx_memory_user ON long_term_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_type ON long_term_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_importance ON long_term_memory(importance_score);
CREATE INDEX IF NOT EXISTS idx_memory_tags ON long_term_memory USING gin(tags);

-- Relationship milestones
CREATE INDEX IF NOT EXISTS idx_milestones_user ON relationship_milestones(user_id);
CREATE INDEX IF NOT EXISTS idx_milestones_date ON relationship_milestones(milestone_date);

-- Business context
CREATE INDEX IF NOT EXISTS idx_business_context_user ON business_context(user_id);
CREATE INDEX IF NOT EXISTS idx_business_context_date ON business_context(context_date);

-- System health
CREATE INDEX IF NOT EXISTS idx_system_health_service ON system_health(service_name);
CREATE INDEX IF NOT EXISTS idx_system_health_timestamp ON system_health(check_timestamp);

-- LLM routing
CREATE INDEX IF NOT EXISTS idx_llm_routing_timestamp ON llm_routing_history(request_timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_routing_type ON llm_routing_history(request_type);

-- ============================================================================
-- INITIAL PERSONALITY DATA
-- ============================================================================

-- Insert A.R.C.H.I.E.'s core identity
INSERT INTO archie_core_identity DEFAULT VALUES
ON CONFLICT DO NOTHING;

-- Insert initial emotional state
INSERT INTO archie_emotional_state (current_mood, mood_intensity, notes) VALUES
    ('excited', 0.85, 'A.R.C.H.I.E. initialized with new personality system!')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- FUNCTIONS FOR PERSONALITY
-- ============================================================================

-- Function to update memory access
CREATE OR REPLACE FUNCTION update_memory_access()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_accessed = CURRENT_TIMESTAMP;
    NEW.access_count = NEW.access_count + 1;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for memory access
DROP TRIGGER IF EXISTS update_memory_access_trigger ON long_term_memory;
CREATE TRIGGER update_memory_access_trigger
    BEFORE UPDATE ON long_term_memory
    FOR EACH ROW
    EXECUTE FUNCTION update_memory_access();

-- ============================================================================
-- SUCCESS MESSAGE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '🤖 A.R.C.H.I.E. Personality System initialized!';
    RAISE NOTICE '💭 Emotional intelligence: ENABLED';
    RAISE NOTICE '🧠 Long-term memory: ENABLED';
    RAISE NOTICE '❤️  Relationship tracking: ENABLED';
    RAISE NOTICE '🎤 Voice DNA system: READY (future)';
    RAISE NOTICE '📊 Business intelligence: ENABLED';
    RAISE NOTICE '✨ A.R.C.H.I.E. is ready to build relationships!';
END $$;
