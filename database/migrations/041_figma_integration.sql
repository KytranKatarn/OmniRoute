-- ============================================================================
-- Migration 041: Figma Integration Tables
-- Phase 44: Figma Integration Production-Ready
-- Date: 2026-01-19
-- ============================================================================

-- ============================================================================
-- FIGMA OAUTH TOKENS
-- ============================================================================

CREATE TABLE IF NOT EXISTS figma_oauth_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    figma_user_id VARCHAR(255),
    figma_email VARCHAR(255),
    figma_handle VARCHAR(255),
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    token_type VARCHAR(50) DEFAULT 'Bearer',
    expires_at TIMESTAMP,
    scopes TEXT[],
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id)
);

-- ============================================================================
-- FIGMA IMPORTS (Design Files)
-- ============================================================================

CREATE TABLE IF NOT EXISTS figma_imports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    figma_file_key VARCHAR(255) NOT NULL,
    figma_file_name VARCHAR(500),
    figma_file_url TEXT,
    thumbnail_url TEXT,
    version_id VARCHAR(255),
    last_modified TIMESTAMP,
    import_status VARCHAR(50) DEFAULT 'pending',  -- pending, parsing, parsed, generating, completed, failed
    components_count INTEGER DEFAULT 0,
    pages_count INTEGER DEFAULT 0,
    styles_extracted JSONB DEFAULT '{}',
    design_tokens JSONB DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- FIGMA PARSED DESIGNS
-- ============================================================================

CREATE TABLE IF NOT EXISTS figma_parsed_designs (
    id SERIAL PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES figma_imports(id) ON DELETE CASCADE,
    parse_status VARCHAR(50) DEFAULT 'pending',  -- pending, parsing, completed, failed
    structure JSONB DEFAULT '{}',  -- Full parsed structure
    sections JSONB DEFAULT '[]',   -- Detected sections (header, hero, features, etc.)
    detected_components JSONB DEFAULT '[]',  -- Components found in design
    design_tokens JSONB DEFAULT '{}',  -- Colors, typography, spacing
    ai_analysis JSONB DEFAULT '{}',  -- AI-generated insights
    parsed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- FIGMA COMPONENT MAPPINGS
-- ============================================================================

CREATE TABLE IF NOT EXISTS figma_component_mappings (
    id SERIAL PRIMARY KEY,
    parsed_design_id INTEGER NOT NULL REFERENCES figma_parsed_designs(id) ON DELETE CASCADE,
    figma_node_id VARCHAR(255) NOT NULL,
    figma_node_name VARCHAR(500),
    figma_node_type VARCHAR(100),
    component_type VARCHAR(100),  -- button, card, input, nav, hero, footer, etc.
    suggested_component_name VARCHAR(255),
    framework VARCHAR(50),  -- react, vue, html
    props JSONB DEFAULT '[]',
    styles JSONB DEFAULT '{}',
    generated_code TEXT,
    confidence_score FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- FIGMA CODE GENERATIONS
-- ============================================================================

CREATE TABLE IF NOT EXISTS figma_code_generations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    import_id INTEGER REFERENCES figma_imports(id) ON DELETE SET NULL,
    parsed_design_id INTEGER REFERENCES figma_parsed_designs(id) ON DELETE SET NULL,
    framework VARCHAR(50) NOT NULL,  -- react, vue, html
    styling VARCHAR(50) DEFAULT 'tailwind',  -- tailwind, css, styled-components
    generation_status VARCHAR(50) DEFAULT 'pending',  -- pending, generating, completed, failed
    files_generated JSONB DEFAULT '[]',  -- Array of {path, language, content}
    total_files INTEGER DEFAULT 0,
    total_lines INTEGER DEFAULT 0,
    options JSONB DEFAULT '{}',  -- Generation options
    preview_url TEXT,
    exported_to_project INTEGER REFERENCES app_builder_projects(id),
    error_message TEXT,
    generated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- FIGMA ASSETS
-- ============================================================================

CREATE TABLE IF NOT EXISTS figma_assets (
    id SERIAL PRIMARY KEY,
    import_id INTEGER NOT NULL REFERENCES figma_imports(id) ON DELETE CASCADE,
    figma_node_id VARCHAR(255),
    asset_type VARCHAR(50),  -- image, icon, svg, illustration
    original_url TEXT,
    local_path VARCHAR(500),
    file_name VARCHAR(255),
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    format VARCHAR(20),  -- png, jpg, svg, pdf
    scale FLOAT DEFAULT 1.0,
    downloaded BOOLEAN DEFAULT FALSE,
    optimized BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_figma_oauth_user ON figma_oauth_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_figma_imports_user ON figma_imports(user_id);
CREATE INDEX IF NOT EXISTS idx_figma_imports_file_key ON figma_imports(figma_file_key);
CREATE INDEX IF NOT EXISTS idx_figma_imports_status ON figma_imports(import_status);
CREATE INDEX IF NOT EXISTS idx_figma_parsed_import ON figma_parsed_designs(import_id);
CREATE INDEX IF NOT EXISTS idx_figma_mappings_parsed ON figma_component_mappings(parsed_design_id);
CREATE INDEX IF NOT EXISTS idx_figma_generations_user ON figma_code_generations(user_id);
CREATE INDEX IF NOT EXISTS idx_figma_generations_import ON figma_code_generations(import_id);
CREATE INDEX IF NOT EXISTS idx_figma_assets_import ON figma_assets(import_id);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE figma_oauth_tokens IS 'Figma OAuth tokens per user';
COMMENT ON TABLE figma_imports IS 'Imported Figma design files';
COMMENT ON TABLE figma_parsed_designs IS 'Parsed design structures with AI analysis';
COMMENT ON TABLE figma_component_mappings IS 'Figma components mapped to code components';
COMMENT ON TABLE figma_code_generations IS 'Generated code from Figma designs';
COMMENT ON TABLE figma_assets IS 'Assets exported from Figma (images, icons)';

-- ============================================================================
-- VIEWS
-- ============================================================================

CREATE OR REPLACE VIEW v_figma_user_stats AS
SELECT
    u.id as user_id,
    u.username,
    CASE WHEN fot.id IS NOT NULL THEN true ELSE false END as figma_connected,
    COUNT(DISTINCT fi.id) as total_imports,
    COUNT(DISTINCT CASE WHEN fi.import_status = 'completed' THEN fi.id END) as completed_imports,
    COUNT(DISTINCT fcg.id) as total_generations,
    SUM(fcg.total_files) as total_files_generated
FROM users u
LEFT JOIN figma_oauth_tokens fot ON u.id = fot.user_id
LEFT JOIN figma_imports fi ON u.id = fi.user_id
LEFT JOIN figma_code_generations fcg ON u.id = fcg.user_id
GROUP BY u.id, u.username, fot.id;

-- ============================================================================
-- DONE
-- ============================================================================

SELECT 'Migration 041: Figma Integration tables created successfully' as result;
