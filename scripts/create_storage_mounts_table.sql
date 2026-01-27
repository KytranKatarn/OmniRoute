-- Storage Mounts table: tracks managed partitions for cross-tab integration
CREATE TABLE IF NOT EXISTS storage_mounts (
    id SERIAL PRIMARY KEY,
    device VARCHAR(100) NOT NULL,
    mount_point VARCHAR(500),
    filesystem VARCHAR(50),
    label VARCHAR(100),
    capacity_gb DECIMAL(10,2),
    drive_model VARCHAR(200),
    is_managed BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(device)
);

-- Index for Docker bridge lookups
CREATE INDEX IF NOT EXISTS idx_storage_mounts_managed ON storage_mounts(is_managed) WHERE is_managed = TRUE;

COMMENT ON TABLE storage_mounts IS 'Managed storage partitions - bridge between Storage and Docker tabs';
