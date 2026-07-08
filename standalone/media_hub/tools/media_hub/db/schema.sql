-- Media Hub — Standalone Postgres Schema
-- =========================================
-- Self-contained DDL for a standalone Media Hub container (Project #273).
-- Apply against a fresh Postgres database:
--
--     psql "$DATABASE_URL" -f schema.sql
--
-- The standalone container MUST set DATABASE_URL to its own dedicated
-- Postgres instance — do NOT point it at the ARCHIE platform DB.
--
-- Current scope: only media_hub_services. The FK-linked tables
-- (media_library_cache, media_requests, media_upcoming_episodes,
-- media_download_queue) exist in the platform schema but are
-- unused by current Media Hub code. They will be added to this
-- file in a later PR when the corresponding features ship.

BEGIN;

-- Timestamp trigger used by updated_at columns.
CREATE OR REPLACE FUNCTION update_media_hub_timestamp()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

-- Registry of external media services the hub federates
-- (Plex, Jellyfin, Sonarr, Radarr, Overseerr, Prowlarr, SABnzbd).
-- api_key_encrypted stores Fernet ciphertext using MEDIA_HUB_ENCRYPTION_KEY.
CREATE TABLE IF NOT EXISTS media_hub_services (
    id                SERIAL PRIMARY KEY,
    service_type      VARCHAR(50)  NOT NULL,
    name              VARCHAR(100) NOT NULL,
    host              VARCHAR(255) NOT NULL,
    port              INTEGER      NOT NULL,
    use_ssl           BOOLEAN      DEFAULT FALSE,
    api_key_encrypted TEXT,
    is_primary        BOOLEAN      DEFAULT FALSE,
    is_enabled        BOOLEAN      DEFAULT TRUE,
    config_path       TEXT,
    last_health_check TIMESTAMP,
    health_status     VARCHAR(20)  DEFAULT 'unknown',
    health_message    TEXT,
    created_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT media_hub_services_service_type_host_port_key
        UNIQUE (service_type, host, port)
);

CREATE INDEX IF NOT EXISTS idx_media_hub_services_enabled
    ON media_hub_services (is_enabled);
CREATE INDEX IF NOT EXISTS idx_media_hub_services_primary
    ON media_hub_services (is_primary);
CREATE INDEX IF NOT EXISTS idx_media_hub_services_type
    ON media_hub_services (service_type);

DROP TRIGGER IF EXISTS trigger_media_hub_services_updated ON media_hub_services;
CREATE TRIGGER trigger_media_hub_services_updated
    BEFORE UPDATE ON media_hub_services
    FOR EACH ROW
    EXECUTE FUNCTION update_media_hub_timestamp();

-- Local users — only populated in the standalone container. In the
-- platform-embedded mode the ARCHIE users table stays authoritative.
-- Dual-auth: sso_sub set → Kytran SSO user. password_hash set → local user.
-- Constraint enforces at least one auth method present.
CREATE TABLE IF NOT EXISTS media_hub_users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash TEXT,
    is_admin      BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    sso_sub       VARCHAR(255),
    email         VARCHAR(255),
    display_name  VARCHAR(128),
    role          VARCHAR(32),
    product_tiers JSONB,
    CONSTRAINT media_hub_users_auth_method_chk
        CHECK (sso_sub IS NOT NULL OR password_hash IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_media_hub_users_username
    ON media_hub_users (username);

CREATE UNIQUE INDEX IF NOT EXISTS media_hub_users_sso_sub_unique
    ON media_hub_users (sso_sub) WHERE sso_sub IS NOT NULL;

COMMIT;
-- Media Hub Phase 2 (Project #384): feature tables missing from the standalone
-- bootstrap. Idempotent. Source of truth: platform_v2/migrations/027_media_hub.sql
-- Backs: library cache/search, request history, upcoming-episode calendar, download-queue view.

-- Timestamp trigger fn (idempotent; may already exist for media_hub_services)
CREATE OR REPLACE FUNCTION update_media_hub_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- media_library_cache
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_library_cache (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES media_hub_services(id) ON DELETE CASCADE,
    media_type VARCHAR(20) NOT NULL,
    external_id VARCHAR(100) NOT NULL,
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    overview TEXT,
    poster_url TEXT,
    backdrop_url TEXT,
    rating DECIMAL(3, 1),
    rating_source VARCHAR(20),
    genres TEXT[],
    runtime_minutes INTEGER,
    quality VARCHAR(20),
    file_size_bytes BIGINT,
    file_path TEXT,
    added_at TIMESTAMP,
    parent_id INTEGER REFERENCES media_library_cache(id) ON DELETE CASCADE,
    season_number INTEGER,
    episode_number INTEGER,
    tmdb_id INTEGER,
    imdb_id VARCHAR(20),
    tvdb_id INTEGER,
    metadata_json JSONB,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_id, media_type, external_id)
);
CREATE INDEX IF NOT EXISTS idx_media_library_title ON media_library_cache USING gin(to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_media_library_type ON media_library_cache(media_type);
CREATE INDEX IF NOT EXISTS idx_media_library_service ON media_library_cache(service_id);
CREATE INDEX IF NOT EXISTS idx_media_library_added ON media_library_cache(added_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_library_tmdb ON media_library_cache(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_media_library_imdb ON media_library_cache(imdb_id);
CREATE INDEX IF NOT EXISTS idx_media_library_parent ON media_library_cache(parent_id);

-- ---------------------------------------------------------------------------
-- media_requests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_requests (
    id SERIAL PRIMARY KEY,
    request_service_id INTEGER REFERENCES media_hub_services(id) ON DELETE SET NULL,
    external_request_id VARCHAR(100),
    media_type VARCHAR(20) NOT NULL,
    tmdb_id INTEGER,
    tvdb_id INTEGER,
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    poster_url TEXT,
    requested_by VARCHAR(100),
    requested_at TIMESTAMP NOT NULL,
    status VARCHAR(30) NOT NULL,
    download_status VARCHAR(30),
    download_progress INTEGER,
    seasons_requested INTEGER[],
    notes TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(request_service_id, external_request_id)
);
CREATE INDEX IF NOT EXISTS idx_media_requests_status ON media_requests(status);
CREATE INDEX IF NOT EXISTS idx_media_requests_requested ON media_requests(requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_requests_tmdb ON media_requests(tmdb_id);

-- ---------------------------------------------------------------------------
-- media_upcoming_episodes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_upcoming_episodes (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES media_hub_services(id) ON DELETE CASCADE,
    series_id INTEGER NOT NULL,
    series_title VARCHAR(500) NOT NULL,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    episode_title VARCHAR(500),
    air_date DATE NOT NULL,
    air_time TIME,
    overview TEXT,
    poster_url TEXT,
    runtime_minutes INTEGER,
    has_file BOOLEAN DEFAULT FALSE,
    monitored BOOLEAN DEFAULT TRUE,
    metadata_json JSONB,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_id, series_id, season_number, episode_number)
);
CREATE INDEX IF NOT EXISTS idx_upcoming_episodes_airdate ON media_upcoming_episodes(air_date);
CREATE INDEX IF NOT EXISTS idx_upcoming_episodes_service ON media_upcoming_episodes(service_id);
CREATE INDEX IF NOT EXISTS idx_upcoming_episodes_series ON media_upcoming_episodes(series_id);

-- ---------------------------------------------------------------------------
-- media_download_queue
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS media_download_queue (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES media_hub_services(id) ON DELETE CASCADE,
    external_id VARCHAR(100) NOT NULL,
    filename VARCHAR(500),
    category VARCHAR(100),
    size_bytes BIGINT,
    size_left_bytes BIGINT,
    progress_percent INTEGER,
    eta_seconds INTEGER,
    speed_bytes_sec BIGINT,
    status VARCHAR(30) NOT NULL,
    priority INTEGER DEFAULT 0,
    added_at TIMESTAMP,
    completed_at TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_download_queue_status ON media_download_queue(status);
CREATE INDEX IF NOT EXISTS idx_download_queue_service ON media_download_queue(service_id);

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_media_library_stats AS
SELECT s.id as service_id, s.name as service_name, s.service_type,
    COUNT(CASE WHEN c.media_type = 'movie' THEN 1 END) as movie_count,
    COUNT(CASE WHEN c.media_type = 'show' THEN 1 END) as show_count,
    COUNT(CASE WHEN c.media_type = 'episode' THEN 1 END) as episode_count,
    COALESCE(SUM(c.file_size_bytes), 0) as total_size_bytes,
    MAX(c.added_at) as last_added, MAX(c.indexed_at) as last_indexed
FROM media_hub_services s
LEFT JOIN media_library_cache c ON s.id = c.service_id
WHERE s.service_type IN ('plex', 'jellyfin')
GROUP BY s.id, s.name, s.service_type;

CREATE OR REPLACE VIEW v_media_upcoming_week AS
SELECT e.*, s.name as service_name
FROM media_upcoming_episodes e
JOIN media_hub_services s ON e.service_id = s.id
WHERE e.air_date >= CURRENT_DATE AND e.air_date <= CURRENT_DATE + INTERVAL '7 days'
ORDER BY e.air_date, e.air_time;

CREATE OR REPLACE VIEW v_media_active_downloads AS
SELECT d.*, s.name as service_name, s.service_type
FROM media_download_queue d
JOIN media_hub_services s ON d.service_id = s.id
WHERE d.status IN ('queued', 'downloading', 'paused', 'extracting')
ORDER BY d.priority DESC, d.added_at;

-- ---------------------------------------------------------------------------
-- media_requests updated_at trigger
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_media_requests_updated ON media_requests;
CREATE TRIGGER trigger_media_requests_updated
    BEFORE UPDATE ON media_requests
    FOR EACH ROW
    EXECUTE FUNCTION update_media_hub_timestamp();
