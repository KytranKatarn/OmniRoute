-- Migration 163: Game World Interconnection — bonuses, config changes, market prices
-- Idempotent: uses IF NOT EXISTS / ON CONFLICT DO NOTHING

-- game_world_bonuses: cross-game bonuses generated from world events
CREATE TABLE IF NOT EXISTS game_world_bonuses (
    id              SERIAL PRIMARY KEY,
    game_type       VARCHAR(30)  NOT NULL,
    bonus_key       VARCHAR(100) NOT NULL,
    bonus_value     FLOAT        NOT NULL DEFAULT 0,
    source_event_id INTEGER      REFERENCES game_world_events(id) ON DELETE SET NULL,
    consumed        BOOLEAN      NOT NULL DEFAULT FALSE,
    expires_at      TIMESTAMP    NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gwb_game_type_consumed_expires
    ON game_world_bonuses (game_type, consumed, expires_at);

-- game_world_changes: pending config patches for a game type
CREATE TABLE IF NOT EXISTS game_world_changes (
    id              SERIAL PRIMARY KEY,
    game_type       VARCHAR(30)  NOT NULL,
    change_key      VARCHAR(100) NOT NULL,
    config_patch    JSONB        NOT NULL DEFAULT '{}',
    source_event_id INTEGER      REFERENCES game_world_events(id) ON DELETE SET NULL,
    applied         BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gwc_game_type_applied
    ON game_world_changes (game_type, applied);

-- game_market_prices: dynamic resource pricing driven by supply/demand
CREATE TABLE IF NOT EXISTS game_market_prices (
    id             SERIAL PRIMARY KEY,
    resource_type  VARCHAR(50) NOT NULL UNIQUE,
    base_price     FLOAT       NOT NULL DEFAULT 1.0,
    current_price  FLOAT       NOT NULL DEFAULT 1.0,
    supply_1h      FLOAT       NOT NULL DEFAULT 0,
    demand_1h      FLOAT       NOT NULL DEFAULT 0,
    updated_at     TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- Seed default market prices
INSERT INTO game_market_prices (resource_type, base_price, current_price)
VALUES
    ('military_credits', 1.0, 1.0),
    ('trade_goods',      1.5, 1.5),
    ('supplies',         1.2, 1.2),
    ('discoveries',      3.0, 3.0),
    ('population',       0.5, 0.5)
ON CONFLICT (resource_type) DO NOTHING;
