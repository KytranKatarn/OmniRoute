-- Docker Stacks table: tracks managed Docker Compose stacks for multi-stack operations
CREATE TABLE IF NOT EXISTS docker_stacks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    compose_directory VARCHAR(500) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#00D4AA',
    is_system BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for stack lookups by name
CREATE INDEX IF NOT EXISTS idx_docker_stacks_name ON docker_stacks(name);

-- Index for filtering system vs user stacks
CREATE INDEX IF NOT EXISTS idx_docker_stacks_is_system ON docker_stacks(is_system);

COMMENT ON TABLE docker_stacks IS 'Managed Docker Compose stacks - supports multi-stack container operations';

-- Seed the A.R.C.H.I.E. system stack
INSERT INTO docker_stacks (name, display_name, compose_directory, description, color, is_system)
VALUES (
    'archie',
    'A.R.C.H.I.E. Platform',
    '/mnt/archie_brain',
    'System stack - A.R.C.H.I.E. core services',
    '#00D4AA',
    TRUE
) ON CONFLICT (name) DO NOTHING;
