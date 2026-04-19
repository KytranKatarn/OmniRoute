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
-- password_hash stores a werkzeug-format hash (pbkdf2:sha256 or scrypt).
CREATE TABLE IF NOT EXISTS media_hub_users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash TEXT         NOT NULL,
    is_admin      BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_hub_users_username
    ON media_hub_users (username);

COMMIT;
