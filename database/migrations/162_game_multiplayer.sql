-- Migration 162: Multiplayer — profiles, world state, events, sessions
-- Idempotent: safe to run multiple times

CREATE TABLE IF NOT EXISTS game_player_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    guest_session_id VARCHAR(100),
    display_name VARCHAR(50) NOT NULL,
    avatar_config JSONB DEFAULT '{}',
    stats JSONB DEFAULT '{}',
    inventory JSONB DEFAULT '[]',
    credits INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    last_active_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS game_world_state (
    id SERIAL PRIMARY KEY,
    resource_type VARCHAR(50) NOT NULL UNIQUE,
    amount NUMERIC DEFAULT 0,
    last_updated_by INTEGER,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS game_world_events (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    source_game_type VARCHAR(30),
    source_session_id VARCHAR(100),
    profile_id INTEGER REFERENCES game_player_profiles(id),
    data JSONB DEFAULT '{}',
    consumed_by JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS game_sessions (
    id SERIAL PRIMARY KEY,
    room_code VARCHAR(20) NOT NULL UNIQUE,
    game_id INTEGER REFERENCES game_projects(id),
    host_profile_id INTEGER REFERENCES game_player_profiles(id),
    game_type VARCHAR(30) NOT NULL,
    config JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'lobby',
    max_players INTEGER DEFAULT 8,
    current_players INTEGER DEFAULT 0,
    world_effects JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP
);

INSERT INTO game_world_state (resource_type, amount) VALUES
    ('military_credits', 1000),
    ('trade_goods', 500),
    ('supplies', 750),
    ('discoveries', 0),
    ('population', 100)
ON CONFLICT (resource_type) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_game_profiles_user ON game_player_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_game_profiles_guest ON game_player_profiles(guest_session_id);
CREATE INDEX IF NOT EXISTS idx_game_world_events_type ON game_world_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_game_sessions_status ON game_sessions(status);
CREATE INDEX IF NOT EXISTS idx_game_sessions_room ON game_sessions(room_code);
