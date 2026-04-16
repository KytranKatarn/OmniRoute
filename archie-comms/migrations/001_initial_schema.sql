-- A.R.C.H.I.E. Comms — Initial Schema Migration
-- Idempotent: safe to run multiple times (IF NOT EXISTS throughout)

-- Chat sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id INT,
    title VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_activity ON chat_sessions (last_activity);

-- Chat messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INT REFERENCES chat_sessions(id),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    agent_name VARCHAR(100),
    department VARCHAR(100),
    model VARCHAR(100),
    latency_ms INT,
    flight_deck JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id ON chat_messages (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages (created_at);

-- Chat API keys
CREATE TABLE IF NOT EXISTS chat_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INT,
    key_hash VARCHAR(128) NOT NULL,
    name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_api_keys_user_id ON chat_api_keys (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_api_keys_key_hash ON chat_api_keys (key_hash);

-- Outbound messages (Telegram, etc.)
CREATE TABLE IF NOT EXISTS outbound_messages (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    source_agent VARCHAR(100),
    source_department VARCHAR(100),
    source_module VARCHAR(100),
    channel VARCHAR(20) DEFAULT 'telegram',
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    result JSONB
);

CREATE INDEX IF NOT EXISTS idx_outbound_messages_status ON outbound_messages (status);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_channel ON outbound_messages (channel);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_created_at ON outbound_messages (created_at);

-- Collaboration sessions
CREATE TABLE IF NOT EXISTS collaboration_sessions (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(64) UNIQUE,
    topic VARCHAR(500),
    status VARCHAR(20) DEFAULT 'active',
    initiator_id INT,
    turn_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_collaboration_sessions_uuid ON collaboration_sessions (uuid);
CREATE INDEX IF NOT EXISTS idx_collaboration_sessions_status ON collaboration_sessions (status);

-- Collaboration messages
CREATE TABLE IF NOT EXISTS collaboration_messages (
    id SERIAL PRIMARY KEY,
    session_id INT REFERENCES collaboration_sessions(id),
    role VARCHAR(20),
    speaker_id VARCHAR(100),
    content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collaboration_messages_session_id ON collaboration_messages (session_id);

-- Work products from collaboration
CREATE TABLE IF NOT EXISTS work_products (
    id SERIAL PRIMARY KEY,
    session_id INT REFERENCES collaboration_sessions(id),
    title VARCHAR(500),
    content TEXT,
    status VARCHAR(20) DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_work_products_session_id ON work_products (session_id);
CREATE INDEX IF NOT EXISTS idx_work_products_status ON work_products (status);
