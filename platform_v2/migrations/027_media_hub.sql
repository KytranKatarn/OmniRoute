-- Migration 027: Media Hub Module
-- Purpose: Database schema for unified Media Hub (Plex/Jellyfin + *arr ecosystem)
-- Date: 2026-01-30
-- Phase: Media Hub Implementation
-- Note: Supports both Plex and Jellyfin as media servers with abstraction layer

-- ============================================================================
-- MEDIA HUB SERVICES - Stores service configurations with encrypted API keys
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_hub_services (
    id SERIAL PRIMARY KEY,
    service_type VARCHAR(50) NOT NULL,  -- 'plex', 'jellyfin', 'sonarr', 'radarr', 'prowlarr', 'overseerr', 'jellyseerr', 'sabnzbd'
    name VARCHAR(100) NOT NULL,         -- Display name
    host VARCHAR(255) NOT NULL,         -- Host address (IP or hostname)
    port INTEGER NOT NULL,              -- Service port
    use_ssl BOOLEAN DEFAULT FALSE,      -- Use HTTPS
    api_key_encrypted TEXT,             -- Fernet-encrypted API key
    is_primary BOOLEAN DEFAULT FALSE,   -- Primary media server (for Plex/Jellyfin switching)
    is_enabled BOOLEAN DEFAULT TRUE,    -- Service enabled
    config_path TEXT,                   -- Path to config file (for auto-discovery)
    last_health_check TIMESTAMP,
    health_status VARCHAR(20) DEFAULT 'unknown',  -- 'healthy', 'unhealthy', 'degraded', 'unknown'
    health_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(service_type, host, port)
);

-- Index for quick service lookups
CREATE INDEX IF NOT EXISTS idx_media_hub_services_type ON media_hub_services(service_type);
CREATE INDEX IF NOT EXISTS idx_media_hub_services_enabled ON media_hub_services(is_enabled);
CREATE INDEX IF NOT EXISTS idx_media_hub_services_primary ON media_hub_services(is_primary);

-- ============================================================================
-- MEDIA LIBRARY CACHE - Caches library items for fast local search
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_library_cache (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES media_hub_services(id) ON DELETE CASCADE,
    media_type VARCHAR(20) NOT NULL,      -- 'movie', 'show', 'season', 'episode'
    external_id VARCHAR(100) NOT NULL,    -- ID from the media server
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    overview TEXT,
    poster_url TEXT,
    backdrop_url TEXT,
    rating DECIMAL(3, 1),                 -- e.g., 8.5
    rating_source VARCHAR(20),            -- 'imdb', 'tmdb', 'tvdb', 'internal'
    genres TEXT[],                        -- Array of genres
    runtime_minutes INTEGER,
    quality VARCHAR(20),                  -- '1080p', '4K', 'SD', etc.
    file_size_bytes BIGINT,
    file_path TEXT,
    added_at TIMESTAMP,                   -- When added to library
    parent_id INTEGER REFERENCES media_library_cache(id) ON DELETE CASCADE,  -- For seasons/episodes
    season_number INTEGER,                -- For seasons/episodes
    episode_number INTEGER,               -- For episodes
    tmdb_id INTEGER,
    imdb_id VARCHAR(20),
    tvdb_id INTEGER,
    metadata_json JSONB,                  -- Additional metadata
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(service_id, media_type, external_id)
);

-- Indexes for search and filtering
CREATE INDEX IF NOT EXISTS idx_media_library_title ON media_library_cache USING gin(to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_media_library_type ON media_library_cache(media_type);
CREATE INDEX IF NOT EXISTS idx_media_library_service ON media_library_cache(service_id);
CREATE INDEX IF NOT EXISTS idx_media_library_added ON media_library_cache(added_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_library_tmdb ON media_library_cache(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_media_library_imdb ON media_library_cache(imdb_id);
CREATE INDEX IF NOT EXISTS idx_media_library_parent ON media_library_cache(parent_id);

-- ============================================================================
-- MEDIA REQUESTS - Tracks media requests from Overseerr/Jellyseerr
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_requests (
    id SERIAL PRIMARY KEY,
    request_service_id INTEGER REFERENCES media_hub_services(id) ON DELETE SET NULL,
    external_request_id VARCHAR(100),     -- ID from Overseerr/Jellyseerr
    media_type VARCHAR(20) NOT NULL,      -- 'movie', 'tv'
    tmdb_id INTEGER,
    tvdb_id INTEGER,
    title VARCHAR(500) NOT NULL,
    year INTEGER,
    poster_url TEXT,
    requested_by VARCHAR(100),            -- Username who requested
    requested_at TIMESTAMP NOT NULL,
    status VARCHAR(30) NOT NULL,          -- 'pending', 'approved', 'declined', 'available', 'processing'
    download_status VARCHAR(30),          -- 'queued', 'downloading', 'complete', 'failed'
    download_progress INTEGER,            -- 0-100
    seasons_requested INTEGER[],          -- For TV shows, which seasons
    notes TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(request_service_id, external_request_id)
);

-- Index for request queries
CREATE INDEX IF NOT EXISTS idx_media_requests_status ON media_requests(status);
CREATE INDEX IF NOT EXISTS idx_media_requests_requested ON media_requests(requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_requests_tmdb ON media_requests(tmdb_id);

-- ============================================================================
-- MEDIA UPCOMING EPISODES - Caches upcoming episodes from Sonarr
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_upcoming_episodes (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES media_hub_services(id) ON DELETE CASCADE,
    series_id INTEGER NOT NULL,           -- Sonarr series ID
    series_title VARCHAR(500) NOT NULL,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    episode_title VARCHAR(500),
    air_date DATE NOT NULL,
    air_time TIME,                        -- If known
    overview TEXT,
    poster_url TEXT,
    runtime_minutes INTEGER,
    has_file BOOLEAN DEFAULT FALSE,       -- Whether episode file exists
    monitored BOOLEAN DEFAULT TRUE,
    metadata_json JSONB,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(service_id, series_id, season_number, episode_number)
);

-- Indexes for calendar queries
CREATE INDEX IF NOT EXISTS idx_upcoming_episodes_airdate ON media_upcoming_episodes(air_date);
CREATE INDEX IF NOT EXISTS idx_upcoming_episodes_service ON media_upcoming_episodes(service_id);
CREATE INDEX IF NOT EXISTS idx_upcoming_episodes_series ON media_upcoming_episodes(series_id);

-- ============================================================================
-- MEDIA DOWNLOAD QUEUE - Tracks active downloads from SABnzbd/NZBGet
-- ============================================================================

CREATE TABLE IF NOT EXISTS media_download_queue (
    id SERIAL PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES media_hub_services(id) ON DELETE CASCADE,
    external_id VARCHAR(100) NOT NULL,    -- NZB ID from downloader
    filename VARCHAR(500),
    category VARCHAR(100),                -- 'movies', 'tv', etc.
    size_bytes BIGINT,
    size_left_bytes BIGINT,
    progress_percent INTEGER,             -- 0-100
    eta_seconds INTEGER,
    speed_bytes_sec BIGINT,
    status VARCHAR(30) NOT NULL,          -- 'queued', 'downloading', 'paused', 'completed', 'failed', 'extracting'
    priority INTEGER DEFAULT 0,
    added_at TIMESTAMP,
    completed_at TIMESTAMP,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(service_id, external_id)
);

-- Index for download queries
CREATE INDEX IF NOT EXISTS idx_download_queue_status ON media_download_queue(status);
CREATE INDEX IF NOT EXISTS idx_download_queue_service ON media_download_queue(service_id);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View for library statistics per service
CREATE OR REPLACE VIEW v_media_library_stats AS
SELECT
    s.id as service_id,
    s.name as service_name,
    s.service_type,
    COUNT(CASE WHEN c.media_type = 'movie' THEN 1 END) as movie_count,
    COUNT(CASE WHEN c.media_type = 'show' THEN 1 END) as show_count,
    COUNT(CASE WHEN c.media_type = 'episode' THEN 1 END) as episode_count,
    COALESCE(SUM(c.file_size_bytes), 0) as total_size_bytes,
    MAX(c.added_at) as last_added,
    MAX(c.indexed_at) as last_indexed
FROM media_hub_services s
LEFT JOIN media_library_cache c ON s.id = c.service_id
WHERE s.service_type IN ('plex', 'jellyfin')
GROUP BY s.id, s.name, s.service_type;

-- View for upcoming week's episodes
CREATE OR REPLACE VIEW v_media_upcoming_week AS
SELECT
    e.*,
    s.name as service_name
FROM media_upcoming_episodes e
JOIN media_hub_services s ON e.service_id = s.id
WHERE e.air_date >= CURRENT_DATE
  AND e.air_date <= CURRENT_DATE + INTERVAL '7 days'
ORDER BY e.air_date, e.air_time;

-- View for active downloads
CREATE OR REPLACE VIEW v_media_active_downloads AS
SELECT
    d.*,
    s.name as service_name,
    s.service_type
FROM media_download_queue d
JOIN media_hub_services s ON d.service_id = s.id
WHERE d.status IN ('queued', 'downloading', 'paused', 'extracting')
ORDER BY d.priority DESC, d.added_at;

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_media_hub_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for media_hub_services
DROP TRIGGER IF EXISTS trigger_media_hub_services_updated ON media_hub_services;
CREATE TRIGGER trigger_media_hub_services_updated
    BEFORE UPDATE ON media_hub_services
    FOR EACH ROW
    EXECUTE FUNCTION update_media_hub_timestamp();

-- Trigger for media_requests
DROP TRIGGER IF EXISTS trigger_media_requests_updated ON media_requests;
CREATE TRIGGER trigger_media_requests_updated
    BEFORE UPDATE ON media_requests
    FOR EACH ROW
    EXECUTE FUNCTION update_media_hub_timestamp();

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE media_hub_services IS 'Service configurations for Media Hub (Plex, Jellyfin, Sonarr, Radarr, etc.)';
COMMENT ON TABLE media_library_cache IS 'Cached library items for fast local search';
COMMENT ON TABLE media_requests IS 'Media request tracking from Overseerr/Jellyseerr';
COMMENT ON TABLE media_upcoming_episodes IS 'Upcoming episode calendar from Sonarr';
COMMENT ON TABLE media_download_queue IS 'Active download queue from SABnzbd/NZBGet';

COMMENT ON COLUMN media_hub_services.api_key_encrypted IS 'Fernet-encrypted API key - never store plaintext';
COMMENT ON COLUMN media_hub_services.is_primary IS 'Primary media server for the abstraction layer';
COMMENT ON COLUMN media_library_cache.external_id IS 'ID from the source service (Plex rating key, Jellyfin item ID)';
COMMENT ON COLUMN media_requests.seasons_requested IS 'For TV shows, array of requested season numbers';

-- ============================================================================
-- SEED DATA - Default service configurations (without API keys)
-- ============================================================================

-- Only insert if no services exist
INSERT INTO media_hub_services (service_type, name, host, port, use_ssl, is_primary, config_path)
SELECT * FROM (VALUES
    ('plex', 'Plex Media Server', '192.168.1.200', 32400, FALSE, TRUE, '/mnt/Plex/config/plex/Library/Application Support/Plex Media Server/Preferences.xml'),
    ('sonarr', 'Sonarr', '192.168.1.200', 8989, FALSE, FALSE, '/mnt/Plex/config/sonarr/config.xml'),
    ('radarr', 'Radarr', '192.168.1.200', 7878, FALSE, FALSE, '/mnt/Plex/config/radarr/config.xml'),
    ('prowlarr', 'Prowlarr', '192.168.1.200', 9696, FALSE, FALSE, '/mnt/Plex/config/prowlarr/config.xml'),
    ('overseerr', 'Overseerr', '192.168.1.200', 5055, FALSE, FALSE, '/mnt/Plex/config/overseerr/settings.json'),
    ('sabnzbd', 'SABnzbd', '192.168.1.200', 8083, FALSE, FALSE, '/mnt/Plex/config/sabnzbd/sabnzbd.ini')
) AS v(service_type, name, host, port, use_ssl, is_primary, config_path)
WHERE NOT EXISTS (SELECT 1 FROM media_hub_services LIMIT 1);
